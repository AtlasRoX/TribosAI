"""
Where evaluation cases come from.

- Built-in suites ship with the package (tribos/evals/data/<name>.jsonl): "math" (curated mathematics and formal
  proof questions), "physics" (classical, quantum, statistical and relativistic physics questions), "engineering"
  (mechanical, electrical, control, fluids, materials and structural engineering questions), "behavior" (routing,
  scope, abstention, injection, dynamical simulation and experimental dataset behaviour), and "golden" (end-to-end
  questions with structured golden facts across orchestration frameworks). Cases tagged "live" need the live
  system (models, network); a suite whose every case is live is listed as live only.
- Any JSONL file of EvalCase objects: pass its path as the suite.
- Public benchmarks, downloaded on first use into the cache (TRIBOS_EVAL_CACHE, default ~/.cache/tribos/evals)
  and never committed:
  - "math500": HuggingFaceH4/MATH-500 (500 competition math problems, MIT)
  - "gsm8k": openai/gsm8k (grade-school math word problems, MIT)
  - "theoremqa": TIGER-Lab/TheoremQA (350+ STEM theorem questions, MIT)
  - "scibench": xw27/scibench (college physics/chemistry/math numerical problems, MIT)
  - "phybench": Eureka-Lab/PHYBench (symbolic physics olympiad problems, MIT)
  - "engdesign": Engineering design benchmark problems (Apache-2.0 / MIT)
  - "ugphysics": UGPhysics undergraduate physics benchmark (CC-BY-NC-4.0; requires --allow-noncommercial)
  - "gpqa": Idavidrein/gpqa (GPQA Diamond PhD-level science & physics multiple-choice; gated, uses HF_TOKEN)
"""

from __future__ import annotations

import ast
import json
import os
import random
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .schema import AnswerExpect, EvalCase

DATA_DIR = Path(__file__).parent / "data"
HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
EXTERNAL = ("math500", "gsm8k", "theoremqa", "scibench", "phybench", "engdesign", "ugphysics", "gpqa")


def cache_dir() -> Path:
    path = Path(os.getenv("TRIBOS_EVAL_CACHE") or Path.home() / ".cache" / "tribos" / "evals")
    path.mkdir(parents=True, exist_ok=True)
    return path


def builtin_suites() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.jsonl"))


def is_live_suite(cases: Iterable[EvalCase]) -> bool:
    """Every case is tagged live: it has nothing to score offline (no plan block that holds without the system)."""
    cases = list(cases)
    return bool(cases) and all("live" in c.tags for c in cases)


def read_jsonl(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip() and not line.lstrip().startswith("//"):
                try:
                    cases.append(EvalCase.model_validate_json(line))
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"{path}:{n}: invalid case: {exc}") from exc
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{path}: duplicate case ids {sorted(dupes)}")
    return cases


def _fetch_hf_rows(
    dataset: str,
    dest: Path,
    *,
    config: str = "default",
    split: str = "test",
    refresh: bool = False,
    token: str | None = None,
) -> list[dict[str, Any]]:
    if dest.exists() and not refresh:
        return json.loads(dest.read_text(encoding="utf-8"))
    import httpx

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = httpx.get(
            HF_ROWS_URL,
            timeout=120,
            headers=headers,
            params={"dataset": dataset, "config": config, "split": split, "offset": offset, "length": 100},
        )
        resp.raise_for_status()
        page = resp.json()
        batch = [r["row"] for r in page.get("rows", [])]
        rows.extend(batch)
        offset += 100
        total = int(page.get("num_rows_total") or 0)
        if not batch or offset >= total:
            break
    dest.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return [str(v) for v in ast.literal_eval(value)]
        except (ValueError, SyntaxError):
            return [value]
    return [str(value)] if value else []


def _parse_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    m = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------------------------
# MATH-500 (HuggingFaceH4/MATH-500, MIT): competition math with symbolic / numeric answers
# ---------------------------------------------------------------------------------------------------------------

def load_math500(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("HuggingFaceH4/MATH-500", cache_dir() / "math500_rows.json", config="default", split="test", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        uid = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(row.get("unique_id") or i)).strip("-")
        ans_str = str(row.get("answer") or "").strip()
        subject = str(row.get("subject") or "mathematics").lower().replace(" ", "_")
        level = row.get("level")
        tags = ["benchmark", "math500"]
        if level is not None:
            tags.append(f"level:{level}")
        cases.append(EvalCase(
            id=f"math500-{uid}",
            suite="math500",
            category=subject,
            query=str(row.get("problem") or "").strip(),
            answer=AnswerExpect(answer_type="symbolic", symbolic_answer=ans_str, verified=None),
            reference=str(row.get("solution") or ""),
            source="MATH-500 (Hendrycks et al. / Lightman et al., MIT)",
            tags=tags,
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# GSM8K (openai/gsm8k, MIT): multi-step grade-school mathematical reasoning with exact numerical answers
# ---------------------------------------------------------------------------------------------------------------

def load_gsm8k(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("openai/gsm8k", cache_dir() / "gsm8k_rows.json", config="main", split="test", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        solution = str(row.get("answer") or "")
        tail = solution.split("####")[-1].strip() if "####" in solution else solution
        num = _parse_float(tail)
        cases.append(EvalCase(
            id=f"gsm8k-{i}",
            suite="gsm8k",
            category="arithmetic_reasoning",
            query=str(row.get("question") or "").strip(),
            answer=AnswerExpect(
                answer_type="numeric",
                numeric_answer=num if num is not None else 0.0,
                numeric_tolerance=1e-3,
                verified=None,
            ),
            reference=solution,
            source="GSM8K (Cobbe et al. 2021, MIT)",
            tags=["benchmark", "gsm8k"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# TheoremQA (TIGER-Lab/TheoremQA, MIT): theorem-driven STEM problems across math, physics, EE & CS
# ---------------------------------------------------------------------------------------------------------------

def load_theoremqa(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("TIGER-Lab/TheoremQA", cache_dir() / "theoremqa_rows.json", config="default", split="test", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("Question") or row.get("question") or "").strip()
        raw_ans = row.get("Answer") if "Answer" in row else row.get("answer")
        atype = str(row.get("Answer_type") or row.get("answer_type") or "number").lower()
        field = str(row.get("field") or row.get("subfield") or "theorem").lower().replace(" ", "_")
        if "bool" in atype or str(raw_ans).lower() in ("true", "false", "yes", "no"):
            label = "yes" if str(raw_ans).lower() in ("true", "yes") else "no"
            expect = AnswerExpect(answer_type="yesno", label=label, options=["yes", "no"], verified=None)
        elif "option" in atype:
            label = str(raw_ans).strip()
            opts = _as_list(row.get("options")) or ["(a)", "(b)", "(c)", "(d)"]
            if label and label not in opts:
                opts = [label, *opts]
            expect = AnswerExpect(answer_type="choice", label=label, options=opts, verified=None)
        else:
            num = _parse_float(raw_ans)
            if num is not None:
                expect = AnswerExpect(answer_type="numeric", numeric_answer=num, numeric_rel_tol=0.01, numeric_tolerance=1e-3, verified=None)
            else:
                expect = AnswerExpect(answer_type="symbolic", symbolic_answer=str(raw_ans or ""), verified=None)
        cases.append(EvalCase(
            id=f"theoremqa-{row.get('id') or i}",
            suite="theoremqa",
            category=field,
            query=q,
            answer=expect,
            reference=str(row.get("Theorem") or row.get("explanation") or ""),
            source="TheoremQA (Chen et al. 2023, MIT)",
            tags=["benchmark", "theoremqa"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# SciBench (xw27/scibench, MIT): collegiate physics, chemistry and mathematics numerical problems
# ---------------------------------------------------------------------------------------------------------------

def load_scibench(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("xw27/scibench", cache_dir() / "scibench_rows.json", config="default", split="train", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("problem_text") or row.get("question") or "").strip()
        unit = str(row.get("unit") or "").strip()
        if unit and unit not in q:
            q = f"{q} (Express the final numerical answer in {unit}.)"
        num = _parse_float(row.get("answer_number") if "answer_number" in row else row.get("answer"))
        src_tag = str(row.get("source") or "scibench").lower()
        cases.append(EvalCase(
            id=f"scibench-{row.get('problemid') or i}",
            suite="scibench",
            category=src_tag,
            query=q,
            answer=AnswerExpect(
                answer_type="numeric",
                numeric_answer=num if num is not None else 0.0,
                numeric_rel_tol=0.02,
                numeric_tolerance=1e-2,
                verified=None,
            ),
            reference=str(row.get("solution") or ""),
            source="SciBench (Wang et al. 2024, MIT)",
            tags=["benchmark", "scibench", f"book:{src_tag}"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# PHYBench (Eureka-Lab/PHYBench, MIT): symbolic physics reasoning problems
# ---------------------------------------------------------------------------------------------------------------

def load_phybench(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("Eureka-Lab/PHYBench", cache_dir() / "phybench_rows.json", config="default", split="train", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("content") or row.get("question") or "").strip()
        ans = str(row.get("answer") or "").strip()
        cat = str(row.get("category") or row.get("tag") or "physics").lower().replace(" ", "_")
        cases.append(EvalCase(
            id=f"phybench-{row.get('id') or i}",
            suite="phybench",
            category=cat,
            query=q,
            answer=AnswerExpect(answer_type="symbolic", symbolic_answer=ans, verified=None),
            reference=str(row.get("solution") or ""),
            source="PHYBench (Qiu et al. 2025, MIT)",
            tags=["benchmark", "phybench"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# EngDesign: engineering analysis and design synthesis benchmark
# ---------------------------------------------------------------------------------------------------------------

def load_engdesign(refresh: bool = False) -> list[EvalCase]:
    rows = _fetch_hf_rows("cleanenergy/engdesign", cache_dir() / "engdesign_rows.json", config="default", split="test", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("question") or row.get("prompt") or "").strip()
        domain = str(row.get("domain") or row.get("category") or "engineering_design").lower().replace(" ", "_")
        num = _parse_float(row.get("numeric_answer")) if "numeric_answer" in row else None
        if num is not None:
            expect = AnswerExpect(answer_type="numeric", numeric_answer=num, numeric_rel_tol=0.05, verified=None)
        else:
            req = _as_list(row.get("required_terms"))
            expect = AnswerExpect(answer_type="summary", required_terms=req, verified=None)
        cases.append(EvalCase(
            id=f"engdesign-{row.get('id') or i}",
            suite="engdesign",
            category=domain,
            query=q,
            answer=expect,
            reference=str(row.get("reference") or row.get("solution") or ""),
            source="EngDesign Benchmark",
            tags=["benchmark", "engdesign"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# UGPhysics (CC-BY-NC-4.0): opt-in non-commercial undergraduate physics benchmark
# ---------------------------------------------------------------------------------------------------------------

def load_ugphysics(refresh: bool = False, *, allow_noncommercial: bool = False) -> list[EvalCase]:
    if not allow_noncommercial:
        raise ValueError(
            "UGPhysics is licensed CC-BY-NC-4.0 (non-commercial research only). "
            "Pass --allow-noncommercial (or allow_noncommercial=True) to load it."
        )
    rows = _fetch_hf_rows("UGPhysics/ugphysics", cache_dir() / "ugphysics_rows.json", config="default", split="test", refresh=refresh)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("problem") or row.get("question") or "").strip()
        ans = str(row.get("answer") or "").strip()
        subject = str(row.get("subject") or row.get("domain") or "undergraduate_physics").lower().replace(" ", "_")
        num = _parse_float(ans) if re.fullmatch(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", ans) else None
        if num is not None:
            expect = AnswerExpect(answer_type="numeric", numeric_answer=num, numeric_rel_tol=0.02, verified=None)
        else:
            expect = AnswerExpect(answer_type="symbolic", symbolic_answer=ans, verified=None)
        cases.append(EvalCase(
            id=f"ugphysics-{row.get('id') or i}",
            suite="ugphysics",
            category=subject,
            query=q,
            answer=expect,
            reference=str(row.get("solution") or ""),
            source="UGPhysics (Xu et al. 2025, CC-BY-NC-4.0)",
            tags=["benchmark", "ugphysics", "noncommercial"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------
# GPQA Diamond (Idavidrein/gpqa, gated): PhD-level physics, chemistry and STEM multiple-choice
# ---------------------------------------------------------------------------------------------------------------

INSUFFICIENT = "Insufficient information to answer the question"


def load_gpqa(refresh: bool = False) -> list[EvalCase]:
    dest = cache_dir() / "gpqa_rows.json"
    token = os.getenv("HF_TOKEN")
    if (not dest.exists() or refresh) and not token:
        raise ValueError("GPQA Diamond is a gated dataset; set HF_TOKEN in the environment to download it.")
    rows = _fetch_hf_rows("Idavidrein/gpqa", dest, config="gpqa_diamond", split="train", refresh=refresh, token=token)
    cases: list[EvalCase] = []
    for i, row in enumerate(rows):
        q = str(row.get("Question") or row.get("question") or "").strip()
        correct = str(row.get("Correct Answer") or row.get("ideal") or "").strip()
        distractors = [
            str(row.get(k) or "").strip()
            for k in ("Incorrect Answer 1", "Incorrect Answer 2", "Incorrect Answer 3")
            if row.get(k)
        ] or _as_list(row.get("distractors"))
        domain = str(row.get("Subdomain") or row.get("High-level domain") or "physics").lower().replace(" ", "_")
        cid = row.get("Record ID") or row.get("id") or i
        cases.append(EvalCase(
            id=f"gpqa-{cid}",
            suite="gpqa",
            category=domain,
            query=q,
            answer=AnswerExpect(
                answer_type="choice",
                label=correct,
                options=[correct, *distractors],
                verified=None,
            ),
            reference=str(row.get("Explanation") or ""),
            source="GPQA Diamond (Rein et al. 2023)",
            tags=["benchmark", "gpqa"],
        ))
    return cases


# ---------------------------------------------------------------------------------------------------------------

def load_suite(
    name: str,
    *,
    refresh: bool = False,
    allow_noncommercial: bool = False,
) -> list[EvalCase]:
    loaders: dict[str, Callable[[], list[EvalCase]]] = {
        "math500": lambda: load_math500(refresh),
        "gsm8k": lambda: load_gsm8k(refresh),
        "theoremqa": lambda: load_theoremqa(refresh),
        "scibench": lambda: load_scibench(refresh),
        "phybench": lambda: load_phybench(refresh),
        "engdesign": lambda: load_engdesign(refresh),
        "ugphysics": lambda: load_ugphysics(refresh, allow_noncommercial=allow_noncommercial),
        "gpqa": lambda: load_gpqa(refresh),
    }
    if name in loaders:
        return loaders[name]()
    path = Path(name)
    if path.suffix == ".jsonl" and path.exists():
        return read_jsonl(path)
    builtin = DATA_DIR / f"{name}.jsonl"
    if builtin.exists():
        return read_jsonl(builtin)
    raise ValueError(
        f"Unknown suite '{name}'. Built-in: {', '.join(builtin_suites())}; "
        f"external: {', '.join(EXTERNAL)}; or a .jsonl path"
    )


def select(
    cases: Iterable[EvalCase],
    *,
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int | None = None,
    seed: int | None = None,
) -> list[EvalCase]:
    """Filter by id (prefix match), category and tag; then sample `limit` cases (randomly when seed is given)."""
    out = list(cases)
    if ids:
        out = [c for c in out if any(c.id == i or c.id.startswith(i) for i in ids)]
    if categories:
        out = [c for c in out if c.category in categories]
    if tags:
        out = [c for c in out if set(tags) & set(c.tags)]
    if limit is not None and limit < len(out):
        out = random.Random(seed).sample(out, limit) if seed is not None else out[:limit]
    return out


__all__ = [
    "DATA_DIR",
    "EXTERNAL",
    "builtin_suites",
    "cache_dir",
    "is_live_suite",
    "load_engdesign",
    "load_gpqa",
    "load_gsm8k",
    "load_math500",
    "load_phybench",
    "load_scibench",
    "load_suite",
    "load_theoremqa",
    "load_ugphysics",
    "read_jsonl",
    "select",
]
