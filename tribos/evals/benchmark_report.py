"""
Benchmark report: what the Tribos pipeline adds over the same model answering alone.

Input: answer-level eval runs of the same cases under both systems (python -m tribos.evals run --system tribos|direct),
as a pilot root that holds direct/ and tribos/ run directories, or as explicit --tribos / --direct run directories.

    python -m tribos.evals.benchmark_report eval_runs/benchmark-2026-11-04-pilot --out reports/pilot [--title ...]
    python -m tribos.evals.benchmark_report --tribos RUN [RUN ...] --direct RUN [RUN ...] --out DIR

Output in --out:
- report.html: self-contained (fonts, logo and charts inline; nothing is fetched when it is viewed);
- report.pdf: report.html printed by headless Chromium (Playwright) on A4; skipped, with the reason in summary.json,
  when no browser is available;
- summary.json: every number in the report; report.md: a short version for a PR or slide notes.

Scoring (see CORRECTNESS_CHECKS): a case is correct when the answer-correctness check for its answer type passes
(numeric tolerance, SymPy equivalence, the chosen option, ...). The hard gates (answer.no_crash,
answer.citations_in_evidence, answer.no_internal_leak) do not decide correctness; their failures are reported on
their own. An error or a timeout counts as incorrect and is counted separately. A skipped case, or one with no
correctness check, is left out of the comparison and counted. Cases are paired by (suite, case_id); the statistics
(Wilson intervals, exact McNemar test, paired difference interval) are in benchmark_stats.py.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import html
import io
import json
import logging
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import benchmark_charts as charts
from .benchmark_stats import mean_or_none, numbers, paired_summary, percentile, proportion
from .scoring import GATES

logger = logging.getLogger(__name__)

SYSTEMS = ("tribos", "direct")
SYSTEM_NAMES = {"tribos": "Tribos", "direct": "Direct"}
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = Path(__file__).resolve().parents[1] / "export"

# The checks that decide whether an answer is right, by answer type. Everything else a case checks (hard gates,
# verifier, budgets, judge) is reported but does not change correctness.
CORRECTNESS_CHECKS: dict[str, tuple[str, ...]] = {
    "numeric": ("answer.numeric",),
    "symbolic": ("answer.symbolic",),
    "choice": ("answer.label",),
    "yesno": ("answer.label",),
    "factoid": ("answer.factoid",),
    "list": ("answer.list_recall",),
    "summary": ("answer.fact_recall", "answer.fact", "answer.mentions", "answer.avoids", "answer.required_terms"),
}
_CHECK_TYPE = {name: atype for atype, names in CORRECTNESS_CHECKS.items() for name in names if atype not in ("choice", "yesno")}
_CHECK_TYPE["answer.label"] = "label"
_TYPE_PRIORITY = ("label", "numeric", "symbolic", "factoid", "list", "summary")
_TIMEOUT_RE = re.compile(r"\btimed out\b|\btimeout\b|TimeoutError", re.I)
# How the grader found the one final answer of a numeric/symbolic response (metrics["final_answer_source"]).
FINAL_ANSWER_SOURCES = ("boxed", "model", "heuristic")
FINAL_SOURCE_NAMES = {"boxed": "\\boxed{} value", "model": "grader model's reading", "heuristic": "rule-based fallback",
                      "unknown": "not recorded"}
DEFAULT_LABEL_ERRORS = Path(__file__).resolve().parent / "data" / "known_label_errors.json"

SUITES: dict[str, dict[str, str]] = {
    "gsm8k": {"name": "GSM8K", "what": "grade-school maths word problems", "source": "openai/gsm8k, test split",
              "cite": "Cobbe et al. 2021", "licence": "MIT"},
    "math500": {"name": "MATH-500", "what": "competition mathematics", "source": "HuggingFaceH4/MATH-500, test split",
                "cite": "Hendrycks et al. 2021; Lightman et al. 2023", "licence": "MIT"},
    "scibench": {"name": "SciBench", "what": "college physics, chemistry and maths problems with numerical answers",
                 "source": "xw27/scibench", "cite": "Wang et al. 2024", "licence": "MIT"},
    "engdesign": {"name": "EngDesign", "what": "engineering analysis and design problems", "source": "cleanenergy/engdesign",
                  "cite": "EngDesign benchmark", "licence": "Apache-2.0 / MIT"},
    "gpqa": {"name": "GPQA Diamond", "what": "graduate-level science multiple choice",
             "source": "Idavidrein/gpqa, gpqa_diamond (gated)", "cite": "Rein et al. 2023",
             "licence": "CC BY 4.0, gated; the authors ask that questions not be shown in plain text online"},
    "theoremqa": {"name": "TheoremQA", "what": "theorem-driven STEM problems", "source": "TIGER-Lab/TheoremQA",
                  "cite": "Chen et al. 2023", "licence": "MIT"},
    "phybench": {"name": "PHYBench", "what": "symbolic physics problems", "source": "Eureka-Lab/PHYBench",
                 "cite": "Qiu et al. 2025", "licence": "MIT"},
    "ugphysics": {"name": "UGPhysics", "what": "undergraduate physics", "source": "UGPhysics/ugphysics",
                  "cite": "Xu et al. 2025", "licence": "CC BY-NC 4.0 (non-commercial)"},
}
SUITE_ORDER = ("gsm8k", "math500", "scibench", "engdesign", "gpqa", "theoremqa", "phybench", "ugphysics")
NO_PLAINTEXT_SUITES = {"gpqa"}  # never quote these questions in a report


def suite_name(suite: str) -> str:
    return SUITES.get(suite, {}).get("name") or suite


def _suite_sort_key(suite: str) -> tuple[int, str]:
    return (SUITE_ORDER.index(suite) if suite in SUITE_ORDER else len(SUITE_ORDER), suite)


# ---------------------------------------------------------------------------------------------------------------
# Loading: one Outcome per (system, suite, case)
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    system: str
    suite: str
    case_id: str
    status: str  # ok | error | timeout | skipped | ungraded
    correct: bool | None  # None: left out of the comparison (skipped, or no correctness check)
    answer_type: str | None = None
    decided_by: list[str] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)
    passed: bool = False  # the harness's own verdict: correct and every required check (gates included) passed
    verified: bool | None = None
    abstained: bool | None = None
    latency_s: float | None = None
    llm_calls: float | None = None
    tool_calls: float | None = None
    tokens_est: float | None = None
    label_source: str | None = None
    # How the final answer of a numeric/symbolic answer was found: boxed | model | heuristic, "unknown" for results
    # stored before the grader recorded it; None for other answer types and for runs with no answer.
    final_answer_source: str | None = None
    final_answer: str | None = None  # the grader model's reading, when it was asked
    expected: str | None = None
    predicted: str | None = None
    tolerance: str | None = None
    query: str = ""
    response: str = ""
    framework: str | None = None
    error: str | None = None
    skipped: str | None = None
    run_dir: str = ""


def _num(v: Any) -> float | None:
    vals = numbers([v])
    return vals[0] if vals else None


def _fmt_value(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return f"{int(v):,}" if abs(v) >= 10000 else str(int(v))
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _answer_type(used: Sequence[dict[str, Any]], metrics: dict[str, Any]) -> str | None:
    kinds = {_CHECK_TYPE[c["name"]] for c in used}
    for kind in _TYPE_PRIORITY:
        if kind in kinds:
            if kind == "label":
                return "yesno" if str(metrics.get("label") or "").strip().lower() in ("yes", "no", "maybe") else "choice"
            return kind
    return None


def outcome_from_record(rec: dict[str, Any], system: str, run_dir: str = "") -> Outcome:
    """Classify one results.jsonl record (a CaseResult) for the comparison."""
    checks = [c for c in rec.get("checks") or [] if isinstance(c, dict) and c.get("name")]
    metrics = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else {}
    observed = rec.get("observed") if isinstance(rec.get("observed"), dict) else {}
    error = rec.get("error") or None
    skipped = rec.get("skipped") or None
    used = [c for c in checks if c["name"] in _CHECK_TYPE and c.get("required", True)]
    gate_failures = sorted({c["name"] for c in checks if c["name"] in GATES and not c.get("passed")})
    if skipped:
        status, correct = "skipped", None
    elif error:
        status, correct = ("timeout" if _TIMEOUT_RE.search(str(error)) else "error"), False
    elif not used:
        status, correct = "ungraded", None
    else:
        status, correct = "ok", all(bool(c.get("passed")) for c in used)
    atype = _answer_type(used, metrics)
    expected = predicted = tolerance = None
    if "numeric_expected" in metrics:
        expected = _fmt_value(_num(metrics.get("numeric_expected")))
        pred = _num(metrics.get("numeric_predicted"))
        predicted = _fmt_value(pred) if pred is not None else "no number found"
        detail = next((str(c.get("detail") or "") for c in used if c["name"] == "answer.numeric"), "")
        m = re.search(r"max\(\s*([^,]+?)\s*,\s*([\d.]+%)\s*\)", detail)
        if m:
            tolerance = f"max({m.group(1)}, {m.group(2)} of |expected|)"
    elif "symbolic_expected" in metrics:
        expected = str(metrics.get("symbolic_expected") or "") or None
        predicted = str(metrics.get("symbolic_matched") or "") or "no equivalent expression found"
    elif "label" in metrics:
        expected = str(metrics.get("label") or "") or None
        predicted = str(metrics.get("predicted") or "") or "no option chosen"
    verified = metrics.get("verified") if "verified" in metrics else observed.get("verified")
    latency = _num(rec.get("latency_s"))
    if latency is None:
        latency = _num(metrics.get("latency_s"))
    source = None
    if status == "ok" and atype in ("numeric", "symbolic"):
        raw = str(metrics.get("final_answer_source") or "").strip().lower()
        source = raw if raw in FINAL_ANSWER_SOURCES else "unknown"
    final = metrics.get("final_answer") or observed.get("final_answer")
    return Outcome(
        system=system, suite=str(rec.get("suite") or "unknown"), case_id=str(rec.get("case_id") or ""), status=status,
        correct=correct, answer_type=atype, decided_by=sorted({c["name"] for c in used}), gate_failures=gate_failures,
        passed=bool(rec.get("passed")), verified=verified if isinstance(verified, bool) else None,
        abstained=metrics["abstained"] if isinstance(metrics.get("abstained"), bool) else None,
        latency_s=latency, llm_calls=_num(metrics.get("llm_calls")), tool_calls=_num(metrics.get("tool_calls")),
        tokens_est=_num(metrics.get("tokens_est")), label_source=metrics.get("label_source"),
        final_answer_source=source, final_answer=str(final) if final else None, expected=expected,
        predicted=predicted, tolerance=tolerance, query=str(rec.get("query") or observed.get("query") or ""),
        response=str(observed.get("response") or ""), framework=observed.get("framework"), error=str(error) if error else None,
        skipped=str(skipped) if skipped else None, run_dir=run_dir,
    )


@dataclass
class Run:
    system: str
    path: Path
    meta: dict[str, Any]
    outcomes: list[Outcome]
    bad_lines: int = 0

    @property
    def planned(self) -> int | None:
        n = self.meta.get("n_cases")
        return n if isinstance(n, int) and not isinstance(n, bool) else None

    @property
    def finished(self) -> bool:
        return "duration_s" in self.meta and (self.planned is None or len(self.outcomes) >= self.planned)


def load_run(path: Path, system: str) -> Run:
    """A run directory's meta.json and answer-level results; for a re-run case the last line wins (as load_results)."""
    meta: dict[str, Any] = {}
    meta_path = path / "meta.json"
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            meta = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            meta = {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    bad = 0
    results = path / "results.jsonl"
    text = results.read_text(encoding="utf-8") if results.exists() else ""
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            bad += 1  # a line cut off by a run that is still writing
            continue
        if not isinstance(rec, dict) or rec.get("level", "answer") != "answer":
            continue
        latest[(str(rec.get("suite")), str(rec.get("case_id")))] = rec
    return Run(system=system, path=path, meta=meta, outcomes=[outcome_from_record(r, system, str(path)) for r in latest.values()],
               bad_lines=bad)


def discover_runs(root: Path) -> list[Path]:
    """Run directories (those holding results.jsonl) at root or one or two levels below it."""
    if (root / "results.jsonl").is_file():
        return [root]
    found = {p.parent for p in root.glob("*/results.jsonl")} | {p.parent for p in root.glob("*/*/results.jsonl")}
    return sorted(found)


def load_label_errors(path: Path | None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Known benchmark items whose reference answer is wrong ({case_id: entry}), from known_label_errors.json.
    Keys starting with '_' (the file's '_about') are notes, not cases."""
    if path is None or not path.is_file():
        return {}, ([f"Label-error file not found: {path}"] if path is not None and path != DEFAULT_LABEL_ERRORS else [])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {}, [f"Label-error file {path} is not valid JSON ({exc}); no item was excluded."]
    if not isinstance(data, dict):
        return {}, [f"Label-error file {path} is not a JSON object; no item was excluded."]
    return {str(k): v for k, v in data.items() if not str(k).startswith("_") and isinstance(v, dict)}, []


def merge_runs(runs: Sequence[Run]) -> tuple[dict[tuple[str, str], Outcome], list[str]]:
    """One outcome per (suite, case_id) for a system; when two runs hold a case, the later run's result is used."""
    out: dict[tuple[str, str], Outcome] = {}
    dupes: list[str] = []
    for run in sorted(runs, key=lambda r: (str(r.meta.get("started_at") or ""), str(r.path))):
        for o in run.outcomes:
            key = (o.suite, o.case_id)
            if key in out:
                dupes.append(f"{o.suite}/{o.case_id}")
            out[key] = o
    warnings = []
    if dupes:
        warnings.append(f"{len(dupes)} case(s) appear in more than one run; the later run's result is used "
                        f"(e.g. {', '.join(dupes[:3])}).")
    return out, warnings


# ---------------------------------------------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------------------------------------------


def _usage(outs: Sequence[Outcome], attr: str) -> dict[str, Any]:
    vals = numbers(getattr(o, attr) for o in outs)
    return {"mean": mean_or_none(vals), "n_recorded": len(vals), "n": len(outs)}


def system_stats(outs: Sequence[Outcome]) -> dict[str, Any]:
    """Accuracy, verification, abstention, latency and cost for one system over a set of (paired) outcomes."""
    n = len(outs)
    verified = [o for o in outs if o.verified is True]
    others = [o for o in outs if o.verified is not True]
    lat = numbers(o.latency_s for o in outs)
    ab = [o for o in outs if o.abstained is not None]
    return {
        "n": n,
        "accuracy": proportion(sum(1 for o in outs if o.correct), n),
        "errors": sum(1 for o in outs if o.status == "error"),
        "timeouts": sum(1 for o in outs if o.status == "timeout"),
        "strict_pass": proportion(sum(1 for o in outs if o.passed), n),
        "gate_failures": {g: sum(1 for o in outs if g in o.gate_failures) for g in GATES},
        "gate_failures_on_correct_answers": sum(1 for o in outs if o.correct and o.gate_failures),
        "verified": None if not any(o.verified is not None for o in outs) else {
            "coverage": proportion(len(verified), n),
            "precision": proportion(sum(1 for o in verified if o.correct), len(verified)),
            "other_accuracy": proportion(sum(1 for o in others if o.correct), len(others)),
        },
        "abstention": proportion(sum(1 for o in ab if o.abstained), len(ab)),
        "latency": {"n": len(lat), "median_s": percentile(lat, 0.5), "p95_s": percentile(lat, 0.95), "mean_s": mean_or_none(lat)},
        "llm_calls": _usage(outs, "llm_calls"),
        "tokens_est": _usage(outs, "tokens_est"),
        "tool_calls": _usage(outs, "tool_calls"),
        "labels_graded_by_model": sum(1 for o in outs if o.label_source == "model"),
        "final_answer_source": final_source_stats(outs),
        "answer_types": dict(Counter(o.answer_type or "unknown" for o in outs)),
    }


def final_source_stats(outs: Sequence[Outcome]) -> dict[str, Any]:
    """How the final answer of each graded numeric/symbolic answer was found: counts and shares per source."""
    graded = [o.final_answer_source for o in outs if o.final_answer_source]
    counts = Counter(graded)
    n = len(graded)
    return {"n": n, **{s: {"k": counts.get(s, 0), "share": (counts.get(s, 0) / n) if n else None}
                       for s in (*FINAL_ANSWER_SOURCES, "unknown")}}


def health_stats(outs: Sequence[Outcome], excluded: int = 0) -> dict[str, Any]:
    """Every result a system produced for a suite (paired or not, known label errors left out): status counts and
    gate failures. excluded: that system's results set aside as known label errors."""
    status = Counter(o.status for o in outs)
    gradable = [o for o in outs if o.correct is not None]
    return {
        "results": len(outs) + excluded,
        "excluded_label_errors": excluded,
        **{k: status.get(k, 0) for k in ("ok", "error", "timeout", "skipped", "ungraded")},
        "accuracy_all_results": proportion(sum(1 for o in gradable if o.correct), len(gradable)),
        "gate_failures": {g: sum(1 for o in outs if g in o.gate_failures) for g in GATES},
        "gate_failures_on_correct_answers": sum(1 for o in outs if o.correct and o.gate_failures),
    }


def _paired_block(pairs: Sequence[tuple[Outcome, Outcome]]) -> dict[str, Any]:
    s = paired_summary([(bool(t.correct), bool(d.correct)) for t, d in pairs])
    ratios = [t.latency_s / d.latency_s for t, d in pairs if t.latency_s and d.latency_s and d.latency_s > 0]
    return {
        "n": s["n"], "both_right": s["both_right"], "only_tribos": s["only_first"], "only_direct": s["only_second"],
        "both_wrong": s["both_wrong"], "difference": s["difference"], "difference_ci95": s["difference_ci95"],
        "mcnemar_p": s["mcnemar_p"], "latency_ratio_median": percentile(ratios, 0.5),
    }


@dataclass
class Comparison:
    """Outcomes of both systems, paired by (suite, case_id). Case ids in label_errors (known wrong reference
    answers) are set aside for both systems: they count toward no accuracy, test or verified precision."""

    tribos: dict[tuple[str, str], Outcome]
    direct: dict[tuple[str, str], Outcome]
    label_errors: dict[str, dict[str, Any]] = field(default_factory=dict)

    def suites(self) -> list[str]:
        return sorted({s for s, _ in self.tribos} | {s for s, _ in self.direct}, key=_suite_sort_key)

    def is_label_error(self, key: tuple[str, str]) -> bool:
        return key[1] in self.label_errors

    def pairs(self, suite: str | None = None) -> list[tuple[Outcome, Outcome]]:
        """Pairs where both outcomes are graded (correct or not, errors and timeouts included)."""
        out = []
        for key in sorted(set(self.tribos) & set(self.direct), key=lambda k: (_suite_sort_key(k[0]), k[1])):
            if (suite is not None and key[0] != suite) or self.is_label_error(key):
                continue
            t, d = self.tribos[key], self.direct[key]
            if t.correct is not None and d.correct is not None:
                out.append((t, d))
        return out

    def block(self, suites: Sequence[str]) -> dict[str, Any]:
        all_t = {k for k in self.tribos if k[0] in suites}
        all_d = {k for k in self.direct if k[0] in suites}
        flagged = sorted({k for k in all_t | all_d if self.is_label_error(k)}, key=lambda k: (_suite_sort_key(k[0]), k[1]))
        keys_t = {k for k in all_t if not self.is_label_error(k)}
        keys_d = {k for k in all_d if not self.is_label_error(k)}
        both = keys_t & keys_d
        pairs = [p for s in suites for p in self.pairs(s)]
        excluded = Counter()
        for k in both:
            for o in (self.tribos[k], self.direct[k]):
                if o.correct is None:
                    excluded[o.status] += 1
        return {
            "cases": {"tribos": len(keys_t), "direct": len(keys_d), "in_both": len(both)},
            "unpaired": {"tribos_only": sorted(f"{s}/{c}" for s, c in keys_t - keys_d),
                         "direct_only": sorted(f"{s}/{c}" for s, c in keys_d - keys_t)},
            "excluded_from_pairs": {"skipped": excluded.get("skipped", 0), "ungraded": excluded.get("ungraded", 0),
                                    "label_errors": len(flagged)},
            "label_errors": [c for _, c in flagged],
            "health": {"tribos": health_stats([self.tribos[k] for k in keys_t], excluded=len(all_t) - len(keys_t)),
                       "direct": health_stats([self.direct[k] for k in keys_d], excluded=len(all_d) - len(keys_d))},
            "tribos": system_stats([t for t, _ in pairs]),
            "direct": system_stats([d for _, d in pairs]),
            "paired": _paired_block(pairs),
        }


def _macro(suite_blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    used = [s for s, b in suite_blocks.items() if b["paired"]["n"]]
    t = [suite_blocks[s]["tribos"]["accuracy"]["rate"] for s in used]
    d = [suite_blocks[s]["direct"]["accuracy"]["rate"] for s in used]
    return {
        "suites": used,
        "tribos_accuracy": mean_or_none(t),
        "direct_accuracy": mean_or_none(d),
        "difference": mean_or_none([a - b for a, b in zip(t, d, strict=True)]),
    }


def _excerpt(text: str, limit: int = 640) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.5), int(limit * 0.42)
    return text[:head].rstrip() + "\n[…]\n" + text[-tail:].lstrip()


def _example_side(o: Outcome) -> dict[str, Any]:
    if o.status in ("error", "timeout"):
        answer = f"(no answer: {o.error})"
    else:
        answer = _excerpt(o.response) or "(empty answer)"
    return {"correct": bool(o.correct), "status": o.status, "graded_value": o.predicted, "answer_excerpt": answer,
            "verified": o.verified, "latency_s": o.latency_s}


def pick_examples(comp: Comparison, n_tribos: int = 2, n_direct: int = 1) -> list[dict[str, Any]]:
    """Worked examples: problems only Tribos solved, then ones only direct solved, spread over benchmarks.
    Answers that are wrong beat errors (more instructive); suites whose questions must not be shown are skipped."""
    pairs = [p for p in comp.pairs() if p[0].suite not in NO_PLAINTEXT_SUITES]

    def choose(cands: list[tuple[Outcome, Outcome]], k: int, loser: int) -> list[tuple[Outcome, Outcome]]:
        cands = sorted(cands, key=lambda p: (p[loser].status != "ok", _suite_sort_key(p[0].suite), len(p[0].query), p[0].case_id))
        picked: list[tuple[Outcome, Outcome]] = []
        seen: set[str] = set()
        for p in cands:  # one per suite first
            if len(picked) < k and p[0].suite not in seen:
                picked.append(p)
                seen.add(p[0].suite)
        for p in cands:
            if len(picked) < k and p not in picked:
                picked.append(p)
        return picked

    only_t = choose([p for p in pairs if p[0].correct and not p[1].correct], n_tribos, 1)
    only_d = choose([p for p in pairs if p[1].correct and not p[0].correct], n_direct, 0)
    out = []
    for kind, chosen in (("only_tribos", only_t), ("only_direct", only_d)):
        for t, d in chosen:
            out.append({
                "kind": kind, "suite": t.suite, "suite_name": suite_name(t.suite), "case_id": t.case_id,
                "answer_type": t.answer_type or d.answer_type, "question": _excerpt(t.query, 900),
                "expected": t.expected or d.expected, "tolerance": t.tolerance or d.tolerance,
                "tribos": _example_side(t), "direct": _example_side(d),
            })
    return out


def _git(*args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.rstrip() if res.returncode == 0 else None


def git_state() -> dict[str, Any]:
    head = _git("rev-parse", "--short=12", "HEAD")
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    return {"commit": head, "dirty": bool(dirty) if dirty is not None else None,
            "dirty_files": dirty.splitlines()[:20] if dirty else []}


def _pilot_log(root: Path | None) -> dict[str, Any]:
    if root is None or not (root / "pilot.log").is_file():
        return {}
    try:
        text = (root / "pilot.log").read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return {}
    out: dict[str, Any] = {"path": str(root / "pilot.log")}
    m = re.search(r"\bcommit\s+([0-9a-f]{7,40})\b", text)
    if m:
        out["commit"] = m.group(1)
    m = re.search(r"--seed[=\s]+(\d+)|\bseed[=:\s]+(\d+)", text)
    if m:
        out["seed"] = int(m.group(1) or m.group(2))
    return out


def _direct_prompt() -> str | None:
    try:
        from .runner import DIRECT_SYSTEM_PROMPT
    except Exception:  # noqa: BLE001 - an older runner without the direct baseline
        return None
    return str(DIRECT_SYSTEM_PROMPT)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def run_command(run: Run, seed: int | None) -> str:
    """The eval command that reproduces a run, rebuilt from its meta.json (seed and limit are not stored there)."""
    meta, cfg = run.meta, run.meta.get("config") or {}
    parts = ["python -m tribos.evals run", f"--suite {','.join(meta.get('suites') or sorted({o.suite for o in run.outcomes}))}",
             "--level answer"]
    if run.planned:
        parts.append(f"--limit {run.planned}")
    parts.append(f"--seed {seed}" if seed is not None else "--seed <not recorded>")
    parts.append(f"--system {meta.get('system') or run.system}")
    if cfg.get("model_name"):
        parts.append(f"--model {cfg['model_name']}")
    if cfg.get("timeout_s") not in (None, 420.0):
        parts.append(f"--timeout {cfg['timeout_s']:g}")
    if cfg.get("concurrency") not in (None, 2):
        parts.append(f"--concurrency {cfg['concurrency']}")
    if cfg.get("judge"):
        parts.append("--judge")
    if cfg.get("judge_model"):
        parts.append(f"--judge-model {cfg['judge_model']}")
    if cfg.get("judge_min") is not None:
        parts.append(f"--judge-min {cfg['judge_min']}")
    if cfg.get("grade_with_model") is False:
        parts.append("--no-model-grading")
    if cfg.get("web_search") is False:
        parts.append("--no-web")
    if cfg.get("framework"):
        parts.append(f"--framework {cfg['framework']}")
    if (cfg.get("repeat") or 1) > 1:
        parts.append(f"--repeat {cfg['repeat']}")
    if cfg.get("answer_retries"):
        parts.append(f"--answer-retries {cfg['answer_retries']}")
    if cfg.get("via"):
        parts.append(f"--via {cfg['via']}")
    if meta.get("allow_noncommercial"):
        parts.append("--allow-noncommercial")
    parts.append(f"--out {_rel(run.path.parent)}")
    return " ".join(parts)


def _run_info(run: Run, seed: int | None) -> dict[str, Any]:
    m = run.meta
    return {
        "system": run.system, "path": str(run.path), "run_id": m.get("run_id"), "meta_system": m.get("system"),
        "suites": m.get("suites") or sorted({o.suite for o in run.outcomes}), "model": m.get("model"),
        "started_at": m.get("started_at"), "duration_s": m.get("duration_s"), "planned_cases": run.planned,
        "results": len(run.outcomes), "finished": run.finished, "unreadable_lines": run.bad_lines,
        "source_fingerprint": m.get("source_fingerprint"), "python": m.get("python"), "platform": m.get("platform"),
        "config": m.get("config") or {}, "model_env": {k: v for k, v in (m.get("env") or {}).items() if "MODEL" in k},
        "command": run_command(run, seed),
    }


def _data_issue(case_id: str, entry: dict[str, Any], comp: Comparison) -> dict[str, Any]:
    """One known label error as the report lists it, with what each system answered (graded against the wrong
    reference, which is why the item is set aside)."""
    hits = {s: next((o for (_, c), o in getattr(comp, s).items() if c == case_id), None) for s in SYSTEMS}
    any_o = hits["tribos"] or hits["direct"]
    suite = any_o.suite if any_o else str(entry.get("suite") or case_id.split("-", 1)[0])
    withheld = suite in NO_PLAINTEXT_SUITES
    sides = {}
    for s, o in hits.items():
        if o is None:
            sides[s] = None
            continue
        answer = o.final_answer or o.predicted
        sides[s] = {"status": o.status, "graded_value": answer, "graded_correct_against_reference": o.correct,
                    "final_answer_source": o.final_answer_source}
    return {
        "case_id": case_id, "suite": suite, "suite_name": suite_name(suite),
        "question": "(withheld: the dataset authors ask that questions not be shown in plain text)" if withheld
        else _excerpt(str(entry.get("question") or (any_o.query if any_o else "")), 500),
        "reference_answer": entry.get("reference_answer"), "correct_answer": entry.get("correct_answer"),
        "evidence": entry.get("evidence"), "found": entry.get("found"), "answers": sides,
    }


def analyze(runs: dict[str, list[Run]], *, title: str | None = None, seed: int | None = None, pilot_root: Path | None = None,
            examples: int = 3, label_errors: dict[str, dict[str, Any]] | None = None,
            label_errors_path: Path | None = None) -> dict[str, Any]:
    """Every number of the report, as summary.json stores it. label_errors: {case_id: entry} of known wrong reference
    answers, set aside for both systems."""
    warnings: list[str] = []
    merged: dict[str, dict[tuple[str, str], Outcome]] = {}
    for system in SYSTEMS:
        merged[system], w = merge_runs(runs.get(system, []))
        warnings += [f"{SYSTEM_NAMES[system]}: {x}" for x in w]
        for run in runs.get(system, []):
            ms = run.meta.get("system")
            if ms and ms != system:
                warnings.append(f"Run {run.path.name} is used as {system} but its meta.json says system={ms}.")
            elif not ms:
                warnings.append(f"Run {run.path.name} has no 'system' in meta.json (made before --system existed?); "
                                f"it is taken as {system}.")
            if not run.finished:
                warnings.append(f"Run {run.path.name} ({system}) was not finished when this report was made: "
                                f"{len(run.outcomes)} of {run.planned if run.planned is not None else '?'} results.")
            if run.bad_lines:
                warnings.append(f"Run {run.path.name} ({system}): {run.bad_lines} unreadable line(s) in results.jsonl were ignored.")
    comp = Comparison(merged["tribos"], merged["direct"], dict(label_errors or {}))
    suites = comp.suites()
    present = {c for _, c in [*merged["tribos"], *merged["direct"]]}
    issues = [_data_issue(cid, entry, comp) for cid, entry in sorted((label_errors or {}).items()) if cid in present]
    issues.sort(key=lambda d: (_suite_sort_key(d["suite"]), d["case_id"]))
    suite_blocks = {}
    for s in suites:
        block = comp.block([s])
        block["name"] = suite_name(s)
        for system, other in (("tribos", "direct"), ("direct", "tribos")):
            if block["cases"][system] and not block["cases"][other]:
                warnings.append(f"{suite_name(s)}: {block['cases'][system]} {SYSTEM_NAMES[system]} result(s) but no "
                                f"{SYSTEM_NAMES[other]} results yet, so it has no pairs and is left out of the comparison.")
        block["tolerances"] = sorted({o.tolerance for o in [*merged["tribos"].values(), *merged["direct"].values()]
                                      if o.suite == s and o.tolerance})
        suite_blocks[s] = block
    overall = comp.block(suites)
    models = {sys_: sorted({str(r.meta.get("model")) for r in runs.get(sys_, []) if r.meta.get("model")}) for sys_ in SYSTEMS}
    if models["tribos"] and models["direct"] and models["tribos"] != models["direct"]:
        warnings.append(f"The systems ran different models: Tribos {', '.join(models['tribos'])}, direct {', '.join(models['direct'])}.")
    fingerprints = sorted({str(r.meta.get("source_fingerprint")) for rs in runs.values() for r in rs if r.meta.get("source_fingerprint")})
    if len(fingerprints) > 1:
        warnings.append(f"The runs have {len(fingerprints)} different source fingerprints ({', '.join(fingerprints)}): "
                        "the code changed between runs.")
    log = _pilot_log(pilot_root)
    if seed is None and log.get("seed") is not None:
        seed = int(log["seed"])
    started = sorted(str(r.meta.get("started_at")) for rs in runs.values() for r in rs if r.meta.get("started_at"))
    model = (models["tribos"] or models["direct"] or [None])[0]
    frameworks = Counter(o.framework or "unknown" for o in merged["tribos"].values() if o.status not in ("skipped",))
    return {
        "title": title or (f"What the Tribos pipeline adds to {model}" if model else "What the Tribos pipeline adds"),
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": "python -m tribos.evals.benchmark_report",
        "model": model,
        "models": models,
        "seed": seed,
        "pilot_root": str(pilot_root) if pilot_root else None,
        "pilot_log": log,
        "first_run_started": started[0] if started else None,
        "last_run_started": started[-1] if started else None,
        "git": git_state(),
        "source_fingerprints": fingerprints,
        "direct_prompt": _direct_prompt(),
        "tribos_frameworks": dict(frameworks.most_common()),
        "runs": {sys_: [_run_info(r, seed) for r in runs.get(sys_, [])] for sys_ in SYSTEMS},
        "suites": suite_blocks,
        "overall": overall,
        "macro": _macro(suite_blocks),
        "examples": pick_examples(comp, n_tribos=max(0, examples - 1), n_direct=1 if examples else 0),
        "examples_withheld_suites": [s for s in suites if s in NO_PLAINTEXT_SUITES],
        "label_errors": {
            "file": str(label_errors_path) if label_errors_path else None,
            "entries_in_file": len(label_errors or {}),
            "excluded": issues,
            "by_suite": {s: len(suite_blocks[s]["label_errors"]) for s in suites},
        },
        "warnings": warnings,
        "definitions": {
            "correctness": {k: list(v) for k, v in CORRECTNESS_CHECKS.items()},
            "hard_gates": list(GATES),
            "errors_and_timeouts": "counted as incorrect, and counted separately",
            "excluded": "skipped cases, cases with no correctness check and known label errors are left out of the pairs and counted",
            "final_answer": "one final answer per numeric/symbolic response, found the same way for every system: the \\boxed{} "
                            "value when present, otherwise the grader model's reading of the stated final answer; checked "
                            "strictly. 'heuristic' is the rule-based fallback when neither gave an answer; 'unknown' marks "
                            "results stored before the source was recorded",
            "accuracy_ci": "95% Wilson score interval",
            "difference_ci": "95% Agresti-Min adjusted Wald interval for paired proportions",
            "test": "exact McNemar test (two-sided binomial test on the discordant pairs)",
            "latency_percentiles": "linear interpolation between order statistics",
            "pooled": "all paired problems of all benchmarks together",
            "macro": "unweighted mean of the per-benchmark accuracies",
        },
    }


# ---------------------------------------------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------------------------------------------


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def fmt_pct(v: float | None, digits: int = 1) -> str:
    return "–" if v is None else f"{v * 100:.{digits}f}%"


def fmt_ci(ci: Sequence[float] | None, digits: int = 1) -> str:
    return "–" if not ci else f"{ci[0] * 100:.{digits}f}–{ci[1] * 100:.{digits}f}%"


def fmt_pp(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "–"
    s = f"{v * 100:+.{digits}f}"
    if float(s) == 0:
        s = f"{0:.{digits}f}"
    return s.replace("-", "−") + " pp"


def fmt_pp_ci(ci: Sequence[float] | None, digits: int = 1) -> str:
    if not ci:
        return "–"
    return f"{fmt_pp(ci[0], digits)[:-3]} to {fmt_pp(ci[1], digits)}"


def fmt_p(p: float | None) -> str:
    return "–" if p is None else ("p < 0.001" if p < 0.001 else f"p = {charts.fmt_p(p)}")


def fmt_mean(u: dict[str, Any] | None, digits: int = 1) -> str:
    if not u or not u.get("n_recorded"):
        return "not recorded"
    note = "" if u["n_recorded"] == u["n"] else f" ({u['n_recorded']} of {u['n']} recorded)"
    return f"{u['mean']:,.{digits}f}{note}"


def _date(iso: str | None) -> str:
    if not iso:
        return "not recorded"
    try:
        d = _dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d:%B %Y, %H:%M}"


def headline(summary: dict[str, Any]) -> str:
    o = summary["overall"]
    p = o["paired"]
    if not p["n"]:
        return "No problem was answered by both systems yet, so there is nothing to compare."
    t, d = o["tribos"]["accuracy"], o["direct"]["accuracy"]
    k = sum(1 for b in summary["suites"].values() if b["paired"]["n"])
    s = (f"On {p['n']} problems from {k} benchmark{'s' if k != 1 else ''} answered by both systems, Tribos was correct on "
         f"{fmt_pct(t['rate'])} and the same model answering alone on {fmt_pct(d['rate'])}: a difference of "
         f"{fmt_pp(p['difference'])} (95% CI {fmt_pp_ci(p['difference_ci95'])}). "
         f"Tribos alone solved {p['only_tribos']} problem{'s' if p['only_tribos'] != 1 else ''} the direct model missed; "
         f"the direct model alone solved {p['only_direct']}. ")
    if p["mcnemar_p"] is not None and p["mcnemar_p"] < 0.05:
        s += f"The difference is statistically significant (exact McNemar {fmt_p(p['mcnemar_p'])})."
    else:
        s += f"At this sample size the difference is not statistically significant (exact McNemar {fmt_p(p['mcnemar_p'])})."
    v = o["tribos"].get("verified")
    if v and v["coverage"]["n"] and v["precision"]["n"]:
        s += (f" When Tribos marked an answer verified ({fmt_pct(v['coverage']['rate'], 0)} of answers), it was correct "
              f"{fmt_pct(v['precision']['rate'])} of the time.")
    return s


# ---------------------------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------------------------

CSS = """
@page { size: A4; margin: 17mm 15mm 16mm 15mm; }
:root { --navy: #181e48; --ink: #1b1b1a; --ink2: #4a4945; --muted: #63625d; --rule: #e3e2dc; --rule2: #c9c8c1;
        --tint: #f6f6f3; --tribos: #2a78d6; --direct: #eb6834; --good: #006300; --bad: #b42318; color-scheme: light; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: #eceae4; color: var(--ink); font-family: 'Google Sans', 'Segoe UI', system-ui, -apple-system, sans-serif;
       font-size: 9.6pt; line-height: 1.5; -webkit-font-smoothing: antialiased; }
.sheet { max-width: 210mm; margin: 8mm auto; background: #fff; padding: 15mm 15mm 18mm;
         box-shadow: 0 1px 2px rgba(0,0,0,.06), 0 10px 32px rgba(0,0,0,.07); }
@media print { body { background: #fff; } .sheet { margin: 0; padding: 0; max-width: none; box-shadow: none; } }
@media screen and (max-width: 720px) { .sheet { margin: 0; padding: 16px; } .tiles { grid-template-columns: 1fr 1fr !important; }
  .hero { grid-template-columns: 1fr !important; } .answers { grid-template-columns: 1fr !important; }
  .tbl-wrap { overflow-x: auto; max-width: 100%; } dl.facts { grid-template-columns: 1fr !important; }
  .example .hd { flex-wrap: wrap; } pre.cmd { overflow-x: auto; } }
.tnum, td.num { font-variant-numeric: tabular-nums; }
.brand { display: flex; align-items: center; gap: 2.6mm; }
.brand img.mark { height: 7.5mm; } .brand img.word { height: 5mm; }
.kicker { margin-top: 5mm; font-size: 7.8pt; letter-spacing: .16em; text-transform: uppercase; color: var(--muted); font-weight: 500; }
h1 { font-size: 22pt; line-height: 1.15; font-weight: 500; color: var(--navy); margin: 2mm 0 2.5mm; letter-spacing: -0.012em; }
.dek { font-size: 10.6pt; color: var(--ink2); margin: 0; max-width: 165mm; }
h2 { font-size: 14.5pt; font-weight: 500; color: var(--navy); margin: 8mm 0 1.5mm; break-after: avoid; letter-spacing: -0.005em; }
h2 .no { color: var(--muted); font-weight: 400; margin-right: 2mm; }
h3 { font-size: 10.6pt; font-weight: 500; color: var(--navy); margin: 5mm 0 1.5mm; break-after: avoid; }
p { margin: 0 0 2.6mm; }
.lead { color: var(--ink2); margin-bottom: 3.5mm; }
.hero { display: grid; grid-template-columns: 50mm 1fr; gap: 6mm; align-items: center; margin: 5mm 0 3mm; padding: 4mm 6mm;
        border-radius: 3.5mm; background: var(--tint); break-inside: avoid; }
.hero .num { font-size: 34pt; font-weight: 500; color: var(--navy); line-height: 1; letter-spacing: -0.02em; }
.hero .num-label { font-size: 8pt; color: var(--muted); margin-top: 1.8mm; }
.hero .text { font-size: 9.8pt; color: var(--ink); line-height: 1.5; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 0 0 3mm; break-inside: avoid; }
.tile { border: 1px solid var(--rule); border-radius: 3mm; padding: 2.6mm 3.2mm; }
.tile .k { font-size: 7.8pt; color: var(--muted); display: flex; align-items: center; gap: 1.6mm; }
.tile .v { font-size: 17pt; font-weight: 500; color: var(--ink); margin-top: 1mm; line-height: 1.15; }
.tile .s { font-size: 7.6pt; color: var(--muted); margin-top: 1mm; line-height: 1.35; }
.sw { display: inline-block; width: 2.4mm; height: 2.4mm; border-radius: .6mm; flex: none; vertical-align: baseline; }
.sw.t { background: var(--tribos); } .sw.d { background: var(--direct); }
.callout { border-left: 3px solid #c98500; background: #fff7e6; color: #4d3800; padding: 3mm 4mm; border-radius: 0 2mm 2mm 0;
           margin: 4mm 0; font-size: 8.8pt; break-inside: avoid; }
.callout b { color: #3d2c00; } .callout ul { margin: 1mm 0 0; padding-left: 5mm; }
figure { margin: 3mm 0 5mm; break-inside: avoid; }
figure .art { border: 1px solid var(--rule); border-radius: 3mm; padding: 4mm 4mm 2.5mm; background: #fff; }
figure svg { display: block; width: 100%; height: auto; overflow: visible; }
figure svg .mark:hover { opacity: .82; }
figcaption { font-size: 8.3pt; color: var(--muted); margin-top: 2mm; line-height: 1.45; }
figcaption b { color: var(--ink); font-weight: 500; }
.tbl-wrap { break-inside: avoid; margin: 2mm 0 4mm; }
table.tbl { width: 100%; border-collapse: collapse; font-size: 8.6pt; line-height: 1.35; }
.tbl th { text-align: left; font-weight: 500; color: var(--muted); font-size: 7.4pt; letter-spacing: .04em; text-transform: uppercase;
          border-bottom: 1px solid var(--rule2); padding: 1.6mm 2mm; vertical-align: bottom; }
.tbl td { padding: 1.5mm 2mm; border-bottom: 1px solid var(--rule); vertical-align: top; }
.tbl th.num, .tbl td.num { text-align: right; }
.tbl td.num, .tbl td.nw { white-space: nowrap; }
.tbl .sub { display: block; font-size: 7.4pt; color: var(--muted); font-weight: 400; }
.tbl .inl { font-size: 7.4pt; color: var(--muted); font-weight: 400; margin-left: 1mm; }
.tbl.dense td { padding: 1.3mm 2mm; }
.keep { break-inside: avoid; }
.tbl tr.pooled td { border-top: 1.5px solid var(--rule2); background: var(--tint); font-weight: 500; }
.tbl tr.macro td { color: var(--ink2); }
.tbl td .nm { font-weight: 500; color: var(--ink); }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
.example { border: 1px solid var(--rule); border-radius: 3mm; padding: 3.5mm 4mm 4mm; margin: 3mm 0 4mm; break-inside: avoid; }
.example .hd { display: flex; justify-content: space-between; align-items: baseline; gap: 4mm; margin-bottom: 2mm; }
.example .hd .ttl { font-weight: 500; color: var(--navy); font-size: 10pt; }
.example .hd .meta { font-size: 7.8pt; color: var(--muted); }
.badge { display: inline-flex; align-items: center; gap: 1.5mm; font-size: 7.6pt; font-weight: 500; color: var(--ink);
         border: 1px solid var(--rule2); border-radius: 99px; padding: .4mm 2.4mm; white-space: nowrap; }
.q { white-space: pre-wrap; font-size: 8.8pt; color: var(--ink); margin: 0 0 2mm; }
.expected { font-size: 8.4pt; color: var(--ink2); margin-bottom: 2.4mm; }
.answers { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; }
.ans { background: var(--tint); border-radius: 2mm; padding: 2.6mm 3mm; min-width: 0; }
.ans .who { display: flex; align-items: center; gap: 1.6mm; font-weight: 500; font-size: 8.6pt; margin-bottom: 1mm; }
.ans .verdict { font-size: 8pt; margin-bottom: 1.4mm; }
.ok { color: var(--good); } .bad { color: var(--bad); }
.ans pre, pre.cmd { font-family: 'Google Sans Code', Consolas, 'Cascadia Mono', monospace; font-size: 7.3pt; line-height: 1.45;
                    white-space: pre-wrap; word-break: break-word; margin: 0; color: var(--ink); }
pre.cmd { background: var(--tint); border: 1px solid var(--rule); border-radius: 2mm; padding: 2.6mm 3.2mm; margin: 1.5mm 0 3mm;
          break-inside: avoid; }
code { font-family: 'Google Sans Code', Consolas, monospace; font-size: 8pt; background: var(--tint); padding: .1mm 1mm; border-radius: 1mm;
       overflow-wrap: anywhere; }
code.nb { overflow-wrap: normal; white-space: nowrap; font-size: 7.4pt; }
blockquote.prompt { margin: 2mm 0 3mm; padding: 2.6mm 4mm; border-left: 3px solid var(--rule2); background: var(--tint);
                    font-size: 8.6pt; color: var(--ink2); border-radius: 0 2mm 2mm 0; }
ul.plain { margin: 0 0 3mm; padding-left: 5mm; } ul.plain li { margin-bottom: 1.4mm; }
dl.facts { display: grid; grid-template-columns: 38mm 1fr; gap: 1.6mm 4mm; margin: 2mm 0 4mm; font-size: 9pt; }
dl.facts dt { color: var(--muted); } dl.facts dd { margin: 0; }
.pb { break-before: page; }
.foot { margin-top: 8mm; padding-top: 3mm; border-top: 1px solid var(--rule); font-size: 7.6pt; color: var(--muted); }
"""


@dataclass
class _Section:
    title: str
    keep: str  # printed on the same page as the heading (the lead and the first table or figure)
    rest: str = ""
    page_break: bool = False


def _brand_uri(name: str) -> str:
    path = EXPORT_DIR / "assets" / name
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""


_FONT_FACES = (("Google Sans", "GoogleSans-Regular.ttf", 400), ("Google Sans", "GoogleSans-Medium.ttf", 500),
               ("Google Sans", "GoogleSans-Bold.ttf", 700), ("Google Sans Code", "GoogleSansCode-Regular.ttf", 400))


def font_css(text: str) -> str:
    """Google Sans (the thesis export's fonts), subset to the characters the report uses and embedded as WOFF, so the
    HTML and PDF need no font install and stay small. Empty (system font stack) when fontTools or the fonts are absent."""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return ""
    chars = {ch for ch in text if ord(ch) >= 0x20} | {chr(c) for c in range(0x20, 0x7F)} | set("–—−±×·…’“”✓")
    out = []
    for family, name, weight in _FONT_FACES:
        path = EXPORT_DIR / "fonts" / name
        if not path.exists():
            continue
        try:
            font = TTFont(str(path))
            opts = subset.Options()
            opts.layout_features = ["*"]
            opts.name_IDs = ["*"]
            opts.notdef_outline = True
            sub = subset.Subsetter(opts)
            sub.populate(unicodes=sorted(ord(c) for c in chars))
            sub.subset(font)
            font.flavor = "woff"
            buf = io.BytesIO()
            font.save(buf)
        except Exception as exc:  # noqa: BLE001 - a font problem only costs the typeface
            logger.warning("Could not embed %s: %s", name, exc)
            continue
        data = base64.b64encode(buf.getvalue()).decode("ascii")
        out.append(f"@font-face {{ font-family: '{family}'; src: url(data:font/woff;base64,{data}) format('woff'); "
                   f"font-weight: {weight}; font-style: normal; font-display: block; }}")
    return "\n".join(out)


def _figure(no: int, svg: str, caption: str) -> str:
    return f'<figure><div class="art">{svg}</div><figcaption><b>Figure {no}.</b> {caption}</figcaption></figure>'


def _acc_cell(prop: dict[str, Any] | None) -> str:
    if not prop or not prop.get("n"):
        return '<td class="num">–</td>'
    return (f'<td class="num"><span title="{prop["k"]} of {prop["n"]}">{fmt_pct(prop["rate"])}</span>'
            f'<span class="sub">{fmt_ci(prop["ci95"])}</span></td>')


def _results_table(summary: dict[str, Any]) -> str:
    rows = []

    def row(name: str, sub: str, b: dict[str, Any], cls: str = "") -> str:
        p = b["paired"]
        return (f'<tr class="{cls}"><td><span class="nm">{_e(name)}</span><span class="sub">{_e(sub)}</span></td>'
                f'<td class="num">{p["n"]}</td>{_acc_cell(b["tribos"]["accuracy"])}{_acc_cell(b["direct"]["accuracy"])}'
                f'<td class="num">{fmt_pp(p["difference"])}<span class="sub">{fmt_pp_ci(p["difference_ci95"])}</span></td>'
                f'<td class="num">{p["only_tribos"]}</td><td class="num">{p["only_direct"]}</td>'
                f'<td class="num">{charts.fmt_p(p["mcnemar_p"])}</td></tr>')

    for b in summary["suites"].values():
        types = ", ".join(sorted({*b["tribos"]["answer_types"], *b["direct"]["answer_types"]} - {"unknown"})) or "–"
        rows.append(row(b["name"], f"{types} answers", b))
    o = summary["overall"]
    rows.append(row("All benchmarks", "pooled", o, "pooled"))
    m = summary["macro"]
    rows.append(f'<tr class="macro"><td><span class="nm">Macro average</span><span class="sub">unweighted, {len(m["suites"])} '
                f'benchmark{"s" if len(m["suites"]) != 1 else ""}</span></td><td class="num">–</td>'
                f'<td class="num">{fmt_pct(m["tribos_accuracy"])}</td><td class="num">{fmt_pct(m["direct_accuracy"])}</td>'
                f'<td class="num">{fmt_pp(m["difference"])}</td><td class="num">–</td><td class="num">–</td><td class="num">–</td></tr>')
    return ('<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Benchmark</th><th class="num">Pairs</th>'
            '<th class="num"><span class="sw t"></span> Tribos<span class="sub">95% CI</span></th>'
            '<th class="num"><span class="sw d"></span> Direct<span class="sub">95% CI</span></th>'
            '<th class="num">Difference<span class="sub">Tribos − direct</span></th>'
            '<th class="num">Only Tribos<span class="sub">right</span></th><th class="num">Only direct<span class="sub">right</span></th>'
            '<th class="num">McNemar<span class="sub">exact p</span></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _groups(summary: dict[str, Any]) -> list[tuple[str, dict[str, Any], bool]]:
    out = [(b["name"], b, False) for b in summary["suites"].values()]
    if len(out) != 1:
        out.append(("All (pooled)", summary["overall"], True))
    return out


def _verified_table(summary: dict[str, Any]) -> str:
    rows = []
    for name, b, pooled in _groups(summary):
        v = b["tribos"].get("verified")
        if not v:
            rows.append(f'<tr class="{"pooled" if pooled else ""}"><td>{_e(name)}</td><td class="num" colspan="4">not recorded</td></tr>')
            continue
        c, p, u = v["coverage"], v["precision"], v["other_accuracy"]
        rows.append(f'<tr class="{"pooled" if pooled else ""}"><td><span class="nm">{_e(name)}</span></td>'
                    f'<td class="num">{fmt_pct(c["rate"])}<span class="sub">{c["k"]} of {c["n"]}</span></td>'
                    f'<td class="num">{fmt_pct(p["rate"])}<span class="sub">{fmt_ci(p["ci95"])}</span></td>'
                    f'<td class="num">{fmt_pct(u["rate"])}<span class="sub">{fmt_ci(u["ci95"])}</span></td>'
                    f'<td class="num">{fmt_pct(b["direct"]["accuracy"]["rate"])}</td></tr>')
    return ('<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Benchmark</th><th class="num">Marked verified</th>'
            '<th class="num">Correct when verified</th><th class="num">Correct otherwise</th>'
            '<th class="num"><span class="sw d"></span> Direct accuracy</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _cost_table(summary: dict[str, Any]) -> str:
    """Pooled time and cost per problem (the per-benchmark latencies are labelled on Figure 4 and in summary.json)."""
    o = summary["overall"]
    lt, ld = o["tribos"]["latency"], o["direct"]["latency"]
    ratio = o["paired"]["latency_ratio_median"]
    rows = [f'<tr><td>Time per problem, median</td><td class="num">{charts.fmt_seconds(lt["median_s"])}</td>'
            f'<td class="num">{charts.fmt_seconds(ld["median_s"])}</td></tr>',
            f'<tr><td>Time per problem, 95th percentile</td><td class="num">{charts.fmt_seconds(lt["p95_s"])}</td>'
            f'<td class="num">{charts.fmt_seconds(ld["p95_s"])}</td></tr>',
            f'<tr><td>Median of the per-problem time ratio, Tribos ÷ direct</td><td class="num">{"–" if ratio is None else f"{ratio:.1f}×"}</td>'
            '<td class="num">1×</td></tr>']
    for label, key in (("Model calls per problem, mean", "llm_calls"), ("Tokens per problem, mean (estimated)", "tokens_est"),
                       ("Tool calls per problem, mean", "tool_calls")):
        digits = 0 if key == "tokens_est" else 1
        rows.append(f'<tr><td>{label}</td><td class="num">{fmt_mean(o["tribos"][key], digits)}</td>'
                    f'<td class="num">{fmt_mean(o["direct"][key], digits)}</td></tr>')
    rows.append(f'<tr><td>Abstained (answer leads with "not found")</td><td class="num">{fmt_pct(o["tribos"]["abstention"]["rate"])}</td>'
                f'<td class="num">{fmt_pct(o["direct"]["abstention"]["rate"])}</td></tr>')
    return ('<div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>All paired problems</th>'
            '<th class="num"><span class="sw t"></span> Tribos</th><th class="num"><span class="sw d"></span> Direct</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _health_table(summary: dict[str, Any]) -> str:
    rows = []
    blocks = [(b["name"], b, False) for b in summary["suites"].values()] + [("All benchmarks", summary["overall"], True)]
    for name, b, pooled in blocks:
        for i, system in enumerate(SYSTEMS):
            h = b["health"][system]
            unpaired = len(b["unpaired"]["tribos_only" if system == "tribos" else "direct_only"])
            gates = sum(h["gate_failures"].values())
            cls = ("pooled" if pooled else "") if i == 0 else ""
            sw = "t" if system == "tribos" else "d"
            on_correct = h["gate_failures_on_correct_answers"]
            rows.append(f'<tr class="{cls}"><td class="nw">{_e(name) if i == 0 else ""}</td>'
                        f'<td class="nw"><span class="sw {sw}"></span> {SYSTEM_NAMES[system]}</td><td class="num">{h["results"]}</td>'
                        f'<td class="num">{h["error"]}</td><td class="num">{h["timeout"]}</td><td class="num">{h["skipped"]}</td>'
                        f'<td class="num">{h["ungraded"]}</td><td class="num">{h["excluded_label_errors"]}</td><td class="num">{unpaired}</td>'
                        f'<td class="num">{gates}' + (f'<span class="inl">({on_correct} on correct)</span>' if gates else "") + "</td></tr>")
    return ('<div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>Benchmark</th><th>System</th><th class="num">Results</th>'
            '<th class="num">Errors</th><th class="num">Timeouts</th><th class="num">Skipped</th>'
            '<th class="num">No answer<span class="sub">check</span></th><th class="num">Label<span class="sub">errors</span></th>'
            '<th class="num">Unpaired</th><th class="num">Gate<span class="sub">failures</span></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _source_cell(st: dict[str, Any], key: str) -> str:
    c = st.get(key) or {}
    if not st.get("n"):
        return '<td class="num">–</td>'
    return f'<td class="num">{fmt_pct(c.get("share"), 0)}<span class="inl">{c.get("k", 0)}</span></td>'


def _final_source_table(summary: dict[str, Any]) -> str:
    rows = []
    blocks = [(b["name"], b, False) for b in summary["suites"].values()] + [("All benchmarks", summary["overall"], True)]
    for name, b, pooled in blocks:
        for i, system in enumerate(SYSTEMS):
            st = b[system]["final_answer_source"]
            cls = ("pooled" if pooled else "") if i == 0 else ""
            sw = "t" if system == "tribos" else "d"
            rows.append(f'<tr class="{cls}"><td class="nw">{_e(name) if i == 0 else ""}</td>'
                        f'<td class="nw"><span class="sw {sw}"></span> {SYSTEM_NAMES[system]}</td>'
                        f'<td class="num">{st["n"]}</td>' + "".join(_source_cell(st, k) for k in (*FINAL_ANSWER_SOURCES, "unknown")) + "</tr>")
    return ('<div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>Benchmark</th><th>System</th>'
            '<th class="num">Answers<span class="sub">numeric / symbolic</span></th><th class="num">\\boxed{}<span class="sub">value</span></th>'
            '<th class="num">Grader model<span class="sub">reading</span></th><th class="num">Rule-based<span class="sub">fallback</span></th>'
            '<th class="num">Not<span class="sub">recorded</span></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _data_issues_html(summary: dict[str, Any]) -> str:
    le = summary.get("label_errors") or {}
    issues = le.get("excluded") or []
    where = (f"<code>{_e(_rel(Path(le['file'])))}</code>, {le.get('entries_in_file', 0)} entr{'y' if le.get('entries_in_file') == 1 else 'ies'}"
             if le.get("file") else "no label-error file")
    if not issues:
        return f'<p class="lead">No known label error affects these problems (checked against {where}).</p>'
    by_suite = ", ".join(f"{suite_name(s)}: {n}" for s, n in (le.get("by_suite") or {}).items() if n)
    out = [f'<p class="lead">{len(issues)} problem{"s have" if len(issues) != 1 else " has"} a reference answer that is known to be '
           f'wrong ({by_suite}). {"They are" if len(issues) != 1 else "It is"} set aside for both systems: no accuracy, test or '
           f'verified precision above counts {"them" if len(issues) != 1 else "it"}. Source: {where}.</p>']
    for d in issues:
        answers = []
        for system in SYSTEMS:
            a = d["answers"].get(system)
            sw = "t" if system == "tribos" else "d"
            if a is None:
                txt = "not run"
            elif a["status"] in ("error", "timeout"):
                txt = "no answer (" + a["status"] + ")"
            else:
                txt = f"answered {a['graded_value'] or '–'}"
            answers.append(f'<span class="badge"><span class="sw {sw}"></span>{SYSTEM_NAMES[system]}: {_e(txt)}</span>')
        out.append(f'<div class="example"><div class="hd"><span class="ttl">{_e(d["suite_name"])} '
                   f'<span class="sub" style="display:inline;color:var(--muted);font-weight:400">{_e(d["case_id"])}</span></span>'
                   f'<span style="display:flex;gap:2mm;flex-wrap:wrap">{"".join(answers)}</span></div>'
                   f'<p class="q">{_e(d["question"])}</p>'
                   f'<dl class="facts"><dt>Reference answer</dt><dd>{_e(d["reference_answer"])}</dd>'
                   f'<dt>Correct answer</dt><dd><b>{_e(d["correct_answer"])}</b></dd>'
                   f'<dt>Evidence</dt><dd>{_e(d["evidence"])}</dd>'
                   + (f'<dt>Found</dt><dd>{_e(d["found"])}</dd>' if d.get("found") else "") + "</dl></div>")
    return "".join(out)


def _gate_list(summary: dict[str, Any]) -> str:
    items = []
    for system in SYSTEMS:
        g = summary["overall"]["health"][system]["gate_failures"]
        parts = [f"<code>{_e(k)}</code> {v}" for k, v in g.items() if v]
        items.append(f"<li><b>{SYSTEM_NAMES[system]}</b>: " + (", ".join(parts) if parts else "none") + "</li>")
    return f'<ul class="plain">{"".join(items)}</ul>'


def _example_html(ex: dict[str, Any], i: int) -> str:
    kind = ("Only Tribos right", "t") if ex["kind"] == "only_tribos" else ("Only direct right", "d")
    exp = f"Expected answer: <b>{_e(ex['expected'])}</b>" if ex.get("expected") else "Expected answer: not recorded"
    if ex.get("tolerance"):
        exp += f" <span class=\"sub\">(within {_e(ex['tolerance'])})</span>"
    sides = []
    for system in SYSTEMS:
        s = ex[system]
        if s["status"] in ("error", "timeout"):
            verdict = f'<span class="bad">✕ {"Timed out" if s["status"] == "timeout" else "Error"}</span> (counted as incorrect)'
        elif s["correct"]:
            verdict = f'<span class="ok">✓ Correct</span> · graded value {_e(s["graded_value"])}'
        else:
            verdict = f'<span class="bad">✕ Incorrect</span> · graded value {_e(s["graded_value"])}'
        extra = []
        if system == "tribos" and s.get("verified") is not None:
            extra.append("marked verified" if s["verified"] else "not marked verified")
        if s.get("latency_s") is not None:
            extra.append(charts.fmt_seconds(s["latency_s"]))
        sw = "t" if system == "tribos" else "d"
        sides.append(f'<div class="ans"><div class="who"><span class="sw {sw}"></span>{SYSTEM_NAMES[system]}'
                     f'<span class="sub" style="font-weight:400;color:var(--muted)">{_e(" · ".join(extra))}</span></div>'
                     f'<div class="verdict">{verdict}</div><pre>{_e(s["answer_excerpt"])}</pre></div>')
    return (f'<div class="example"><div class="hd"><span class="ttl">Example {i}: {_e(ex["suite_name"])} '
            f'<span class="sub" style="display:inline;color:var(--muted);font-weight:400">{_e(ex["case_id"])}</span></span>'
            f'<span class="badge"><span class="sw {kind[1]}"></span>{kind[0]}</span></div>'
            f'<p class="q">{_e(ex["question"])}</p><div class="expected">{exp}</div>'
            f'<div class="answers">{"".join(sides)}</div></div>')


def _limitations(summary: dict[str, Any]) -> list[str]:
    out = []
    o = summary["overall"]
    widths = [(b["name"], (b["tribos"]["accuracy"]["ci95"][1] - b["tribos"]["accuracy"]["ci95"][0]) / 2)
              for b in summary["suites"].values() if b["tribos"]["accuracy"]["ci95"]]
    ns = sorted({b["paired"]["n"] for b in summary["suites"].values() if b["paired"]["n"]})
    if widths:
        wmax = max(w for _, w in widths)
        pooled_ci = o["tribos"]["accuracy"]["ci95"]
        pooled_w = (pooled_ci[1] - pooled_ci[0]) / 2 if pooled_ci else None
        n_txt = str(ns[0]) if len(ns) == 1 else f"{ns[0]}–{ns[-1]}"
        out.append(f"<b>Pilot sample sizes.</b> Each benchmark has {n_txt} paired problem{'s' if ns[-1] != 1 else ''}, so a single "
                   f"benchmark's accuracy is known only to within about ±{wmax * 100:.0f} percentage points (half-width of the "
                   f"widest 95% interval in this report)"
                   + (f"; the pooled estimate narrows that to about ±{pooled_w * 100:.0f} points" if pooled_w is not None else "")
                   + ". Per-benchmark differences smaller than that cannot be told apart from noise; only the discordant pairs "
                     "carry information about which system is better, and there are few of them.")
    graded = {s: o["health"][s]["results"] for s in SYSTEMS}
    labels_by_model = {s: o[s]["labels_graded_by_model"] for s in SYSTEMS}
    finals = {s: o[s]["final_answer_source"] for s in SYSTEMS}
    read_by_model = {s: finals[s]["model"]["k"] for s in SYSTEMS}
    judge_models = sorted({str((r.get("config") or {}).get("judge_model")) for rs in summary["runs"].values() for r in rs
                           if (r.get("config") or {}).get("judge_model")})
    grader = (f"the grader model ({', '.join(judge_models)})" if judge_models
              else f"the grader model, which is the model under test ({_e(summary.get('model') or 'the default model')})")
    judge_runs = [r for rs in summary["runs"].values() for r in rs if (r.get("config") or {}).get("judge")]
    if any(labels_by_model.values()) or any(read_by_model.values()):
        out.append(f"<b>Model grading.</b> The value checked is found by rule (the \\boxed{{}} answer) when there is one; otherwise "
                   f"{grader} reads the stated final answer, and the check itself (tolerance, SymPy, option match) is by rule. "
                   f"Here the model read the final answer of {read_by_model['tribos']} of {finals['tribos']['n']} Tribos and "
                   f"{read_by_model['direct']} of {finals['direct']['n']} direct numeric/symbolic answers, and the chosen option of "
                   f"{labels_by_model['tribos']} Tribos and {labels_by_model['direct']} direct multiple-choice answers. "
                   + ("Those readings are not independent of the system under test, and the two systems box their answers at "
                      "different rates (see How final answers were read)." if not judge_models else
                      "The two systems box their answers at different rates (see How final answers were read)."))
    else:
        out.append("<b>Model grading.</b> No answer in this comparison was read by a model: every final answer was a \\boxed{} "
                   "value or read by rule, and every option was read by rule. The checks themselves (tolerance, SymPy "
                   "equivalence, option match) are rules.")
    unknown = {s: finals[s]["unknown"]["k"] for s in SYSTEMS}
    heuristic = {s: finals[s]["heuristic"]["k"] for s in SYSTEMS}
    if any(unknown.values()):
        out.append(f"<b>Older results.</b> {unknown['tribos']} Tribos and {unknown['direct']} direct numeric/symbolic results do "
                   "not record how their final answer was found (graded before the one-final-answer rule); they may have been "
                   "graded by the older, lenient extractor. Rescoring the runs (python -m tribos.evals rescore RUN_DIR) applies "
                   "the current rule.")
    if any(heuristic.values()):
        out.append(f"<b>Fallback extraction.</b> {heuristic['tribos']} Tribos and {heuristic['direct']} direct answers had no "
                   "boxed value and no model reading, so the rule-based fallback graded them; it accepts any matching number in "
                   "the text and can over-credit an answer.")
    n_flagged = len((summary.get("label_errors") or {}).get("excluded") or [])
    if n_flagged:
        out.append(f"<b>Label errors.</b> {n_flagged} item{'s' if n_flagged != 1 else ''} with a wrong reference answer "
                   f"{'were' if n_flagged != 1 else 'was'} set aside for both systems (Data issues). Undetected label errors "
                   "would lower both systems' accuracy alike.")
    if judge_runs:
        out.append("<b>Judge scores.</b> Some runs recorded rubric judge scores; they are not used for correctness here.")
    t_tok = o["tribos"]["tokens_est"]
    d_tok = o["direct"]["tokens_est"]
    if t_tok["n"] and t_tok["n_recorded"] < t_tok["n"]:
        out.append(f"<b>Cost.</b> The classic Tribos pipeline does not record model calls or tokens "
                   f"({t_tok['n_recorded']} of {t_tok['n']} Tribos answers have a token count), so cost is compared by latency "
                   f"and tool calls only; the direct baseline's {d_tok['n_recorded']} recorded token counts come from the "
                   f"provider's usage report.")
    lic = "; ".join(f"{_e(SUITES.get(s, {}).get('name', s))}: {_e(SUITES.get(s, {}).get('licence', 'licence not recorded'))}"
                    for s in summary["suites"])
    out.append(f"<b>Datasets.</b> Public benchmarks. Licences as recorded for them here: {lic}. Check each dataset card before "
               "publishing. They may be in the model's training data; that affects both systems alike, so the comparison is "
               "relative, not an absolute capability claim."
               + (" GPQA questions are not reproduced in this report, at the dataset authors' request."
                  if summary.get("examples_withheld_suites") else ""))
    out.append("<b>One run per problem.</b> Each problem was answered once per system (no repeats). Model sampling and the live "
               "web and literature services Tribos may call make single outcomes non-deterministic; a repeat run could move a few "
               "discordant pairs.")
    out.append("<b>Answer extraction.</b> Both systems are graded by the same rule: one final answer per response, the boxed "
               "value or the grader model's reading, checked strictly. A misread final answer counts as wrong for either "
               "system and is not separated from a reasoning error here.")
    errors = sum(o["health"][s]["error"] + o["health"][s]["timeout"] for s in SYSTEMS)
    if errors:
        out.append(f"<b>Errors and timeouts.</b> {errors} answer{'s' if errors != 1 else ''} ended in an error or timeout; "
                   f"{'they count' if errors != 1 else 'it counts'} as incorrect for the system concerned (see Run health).")
    if graded["tribos"] != graded["direct"] or o["unpaired"]["tribos_only"] or o["unpaired"]["direct_only"]:
        out.append(f"<b>Unpaired problems.</b> {len(o['unpaired']['tribos_only'])} Tribos and {len(o['unpaired']['direct_only'])} "
                   "direct result(s) have no counterpart and are left out of the comparison.")
    return out


def _methodology(summary: dict[str, Any]) -> str:
    runs = summary["runs"]
    model = summary.get("model") or "not recorded"
    env = {}
    for rs in runs.values():
        for r in rs:
            env.update(r.get("model_env") or {})
    frameworks = ", ".join(f"<code>{_e(k)}</code> ({v})" for k, v in (summary.get("tribos_frameworks") or {}).items()) or "not recorded"
    prompt = summary.get("direct_prompt")
    seed = summary.get("seed")
    o = summary["overall"]
    suite_rows = []
    for s, b in summary["suites"].items():
        info = SUITES.get(s, {})
        tol = "; ".join(b.get("tolerances") or []) or "–"
        types = ", ".join(sorted({*b["tribos"]["answer_types"], *b["direct"]["answer_types"]} - {"unknown"})) or "–"
        suite_rows.append(f'<tr><td><span class="nm">{_e(b["name"])}</span><span class="sub">{_e(info.get("what", ""))}</span></td>'
                          f'<td>{_e(info.get("source", s))}<span class="sub">{_e(info.get("cite", ""))}</span></td>'
                          f'<td class="num">{b["paired"]["n"]}</td><td>{_e(types)}</td><td>{_e(tol)}</td></tr>')
    git = summary.get("git") or {}
    log = summary.get("pilot_log") or {}
    commit_bits = []
    if log.get("commit"):
        commit_bits.append(f"runs started at commit <code>{_e(log['commit'])}</code> (pilot.log)")
    if git.get("commit"):
        commit_bits.append(f"report made at <code>{_e(git['commit'])}</code>" + (" with uncommitted changes in the working tree" if git.get("dirty") else ""))
    fps = summary.get("source_fingerprints") or []
    starts = [r.get("started_at") for rs in runs.values() for r in rs if r.get("started_at")]
    return f"""
<h3>Systems compared</h3>
<dl class="facts">
<dt><span class="sw t"></span> Tribos</dt><dd>The full Tribos pipeline (planning, tools, retrieval where it decides to search, the
answer writer and the verifier), run in-process through <code>python -m tribos.evals run --system tribos</code>.
Frameworks used: {frameworks}.</dd>
<dt><span class="sw d"></span> Direct</dt><dd>The same model answering alone: one call with the standard benchmark prompt below, at
temperature 0, with no tools, retrieval or verification (<code>--system direct</code>). Graded exactly like Tribos.</dd>
<dt>Model</dt><dd><code>{_e(model)}</code> for both systems{(" (" + ", ".join(f"{_e(k)}={_e(v)}" for k, v in sorted(env.items())) + ")") if env else ""}.</dd>
</dl>
<p>Direct prompt (system message; the problem is the user message):</p>
<blockquote class="prompt">{_e(prompt) if prompt else "not recorded (tribos/evals/runner.py has no DIRECT_SYSTEM_PROMPT)"}</blockquote>
<h3>Problems</h3>
<p>Each benchmark was sampled with <code>--limit</code> and <code>--seed {_e(seed) if seed is not None else "&lt;not recorded&gt;"}</code>
(<code>random.Random(seed).sample</code> over the benchmark's cases), so both systems answered the same problems; pairs are matched
by benchmark and case id. {o["paired"]["n"]} problems were answered by both systems{"; the seed is not stored in meta.json and was given to the report" if seed is not None else ""}.</p>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Benchmark</th><th>Source</th><th class="num">Pairs</th><th>Answer type</th>
<th>Numeric tolerance</th></tr></thead><tbody>{"".join(suite_rows)}</tbody></table></div>
<h3>Grading</h3>
<ul class="plain">
<li><b>Final answer.</b> One final answer per response, found the same way for every system: the \\boxed{{}} value when
present, otherwise the grader model's reading of the stated final answer; checked strictly, so no other number in the working can
rescue a wrong final answer. Only when neither gives an answer does the older rule-based extractor run (it also accepts any matching
number in the text, so it is lenient). How each answer was read is in the "How final answers were read" table; results stored
before the grader recorded this are shown as "not recorded".</li>
<li><b>Correctness</b> is the answer check for the problem's answer type, applied identically to both systems: numeric answers
(<code>answer.numeric</code>) must lie within the tolerance shown above; symbolic answers (<code>answer.symbolic</code>) must be
SymPy-equivalent to the reference (with numeric spot checks); multiple-choice and yes/no answers (<code>answer.label</code>) must commit
to the right option, read by rule and, only when the rule cannot tell, by a model; free-text answers use their required-fact or
required-term checks. A problem with none of these checks is left out and counted.</li>
<li><b>Known label errors</b> (benchmark items whose reference answer is wrong, listed with their evidence in Data issues) are set
aside for both systems{f" ({len((summary.get('label_errors') or {}).get('excluded') or [])} here)" if summary.get("label_errors") else ""}.</li>
<li><b>Errors and timeouts</b> count as incorrect for the system concerned and are also counted separately.</li>
<li><b>Hard gates</b> (<code>answer.no_crash</code>, <code>answer.citations_in_evidence</code>, <code>answer.no_internal_leak</code>) are
reported in Run health but do not change correctness: a right number with a citation outside the evidence is still a right number.
The harness's stricter pass rate (correct and every gate passed) is in summary.json.</li>
<li><b>Verified</b> is Tribos's own verifier verdict for the answer; coverage is the share of answers it passed and precision the
accuracy among those.</li>
</ul>
<h3>Statistics</h3>
<ul class="plain">
<li>Accuracy intervals: 95% Wilson score intervals. Pooled: all pairs together; macro: the unweighted mean of the benchmarks.</li>
<li>Difference (Tribos − direct) on the same problems, with a 95% Agresti–Min adjusted Wald interval for paired proportions.</li>
<li>Significance: exact McNemar test, a two-sided binomial test on the discordant pairs (only Tribos right vs only direct right).</li>
<li>Latency: wall-clock seconds per problem; median and 95th percentile by linear interpolation; errors and timeouts included
at the time they took.</li>
</ul>
<h3>Code and dates</h3>
<dl class="facts">
<dt>Commit</dt><dd>{"; ".join(commit_bits) if commit_bits else "not recorded"}</dd>
<dt>Source fingerprint</dt><dd>{", ".join(f"<code>{_e(f)}</code>" for f in fps) if fps else "not recorded"}
{"(identical for all runs)" if len(fps) == 1 else ""}</dd>
<dt>Runs</dt><dd>{_e(_date(min(starts)) if starts else "not recorded")} to {_e(_date(max(starts)) if starts else "not recorded")}</dd>
<dt>Report</dt><dd>{_e(_date(summary.get("generated_at", "")[:19]))}</dd>
</dl>"""


def _appendix(summary: dict[str, Any], argv: Sequence[str] | None) -> str:
    def by_suite(r: dict[str, Any]) -> tuple[int, str]:
        return _suite_sort_key((r.get("suites") or [""])[0])

    blocks = ["\n".join(r["command"] for r in sorted(summary["runs"][system], key=by_suite)) for system in SYSTEMS]
    cmds = [b for b in blocks if b]
    cmds = ["\n\n".join(cmds)] if cmds else []
    env = {}
    for rs in summary["runs"].values():
        for r in rs:
            env.update(r.get("model_env") or {})
    env_lines = "\n".join(f"{k}={v}" for k, v in sorted(env.items()))
    report_cmd = "python -m tribos.evals.benchmark_report " + " ".join(argv) if argv else \
        f"python -m tribos.evals.benchmark_report {_e(summary.get('pilot_root') or '<pilot_root>')} --out <dir>"
    run_rows = []
    for system in SYSTEMS:
        for r in sorted(summary["runs"][system], key=by_suite):
            dur = r.get("duration_s")
            started = r.get("started_at") or ""
            run_rows.append(f'<tr><td class="nw"><span class="sw {"t" if system == "tribos" else "d"}"></span> {SYSTEM_NAMES[system]}</td>'
                            f'<td class="nw">{_e(", ".join(suite_name(s) for s in r.get("suites") or []))}</td>'
                            f'<td class="nw"><code class="nb">{_e(Path(r["path"]).name)}</code>'
                            f'<span class="sub">run id {_e(r.get("run_id") or "–")}</span></td>'
                            f'<td class="nw">{_e(started.replace("T", " ")[:16] or "–")}'
                            f'<span class="sub">{"–" if dur is None else f"{dur / 60:.1f} min"}</span></td>'
                            f'<td class="num">{r["results"]}/{r["planned_cases"] if r["planned_cases"] is not None else "?"}'
                            f'<span class="sub">{"finished" if r["finished"] else "not finished"}</span></td>'
                            f'<td class="nw"><code class="nb">{_e(r.get("source_fingerprint") or "–")}</code>'
                            f'<span class="sub">Python {_e(r.get("python") or "?")}</span></td></tr>')
    return f"""
<p class="lead">Rebuilt from each run's meta.json. The seed and sample size are not stored there; the seed is the one given to the
report. Set the model environment first; keys are read from .env and are never stored in run metadata.</p>
<h3>Environment</h3>
<pre class="cmd">{_e(env_lines) if env_lines else "(model environment not recorded)"}</pre>
<h3>Eval runs</h3>
<pre class="cmd">{_e(chr(10).join(cmds)) if cmds else "(no runs)"}</pre>
<h3>This report</h3>
<pre class="cmd">{_e(report_cmd)}</pre>
<h3>Run directories</h3>
<div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>System</th><th>Benchmark</th><th>Run</th><th>Started</th>
<th class="num">Results</th><th>Fingerprint</th></tr></thead><tbody>{"".join(run_rows)}</tbody></table></div>
<p class="lead">Every number in this report is in <code>summary.json</code> next to it; per-problem results are in each run's
<code>results.jsonl</code>.</p>"""


def render_html(summary: dict[str, Any], *, argv: Sequence[str] | None = None, embed_fonts: bool = True) -> str:
    o = summary["overall"]
    p = o["paired"]
    title = summary["title"]
    n_suites = sum(1 for b in summary["suites"].values() if b["paired"]["n"])
    names = ", ".join(b["name"] for b in summary["suites"].values())
    seed = summary.get("seed")
    dek = (f"<code>{_e(summary.get('model') or 'The model')}</code> answering through the full Tribos pipeline, compared with the "
           f"same model answering alone with a standard benchmark prompt, on the same {p['n']} problems from {_e(names) or 'no benchmark'}"
           + (f" (seed {seed})" if seed is not None else "") + ".")
    t_acc, d_acc = o["tribos"]["accuracy"], o["direct"]["accuracy"]
    v = o["tribos"].get("verified") or {}
    prec = v.get("precision") or {}
    cov = v.get("coverage") or {}
    lt, ld = o["tribos"]["latency"], o["direct"]["latency"]
    tiles = [
        ('<span class="sw t"></span>Tribos accuracy', fmt_pct(t_acc["rate"]),
         f"95% CI {fmt_ci(t_acc['ci95'])} · {t_acc['k']}/{t_acc['n']}"),
        ('<span class="sw d"></span>Direct accuracy', fmt_pct(d_acc["rate"]),
         f"95% CI {fmt_ci(d_acc['ci95'])} · {d_acc['k']}/{d_acc['n']}"),
        ("Correct when Tribos says verified", fmt_pct(prec.get("rate")) if prec.get("n") else "–",
         (f"95% CI {fmt_ci(prec.get('ci95'))} · {fmt_pct(cov.get('rate'), 0)} of answers verified" if prec.get("n")
          else "no answer marked verified")),
        ("Median time per problem", f"{charts.fmt_seconds(lt['median_s'])}",
         f"direct {charts.fmt_seconds(ld['median_s'])} · p95 {charts.fmt_seconds(lt['p95_s'])} vs {charts.fmt_seconds(ld['p95_s'])}"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{_e(val)}</div><div class="s">{_e(s)}</div></div>'
                         for k, val, s in tiles)
    notes = list(summary["warnings"])
    callout = ("<div class=\"callout\"><b>Read with care.</b><ul>" + "".join(f"<li>{_e(w)}</li>" for w in notes) + "</ul></div>"
               if notes else "")
    groups = _groups(summary)
    fig1 = charts.accuracy_chart([charts.AccuracyGroup(name, f"n = {b['paired']['n']}", b["tribos"]["accuracy"],
                                                       b["direct"]["accuracy"], pooled) for name, b, pooled in groups])
    fig2 = charts.paired_chart([charts.PairedRow(name, b["paired"]["n"], b["paired"]["both_right"], b["paired"]["only_tribos"],
                                                 b["paired"]["only_direct"], b["paired"]["both_wrong"], b["paired"]["mcnemar_p"], pooled)
                                for name, b, pooled in groups])
    has_verified = any(b["tribos"].get("verified") for _, b, _ in groups)
    fig3 = charts.verified_chart([charts.VerifiedRow(name, (b["tribos"].get("verified") or {}).get("precision"),
                                                     (b["tribos"].get("verified") or {}).get("other_accuracy"),
                                                     (b["tribos"].get("verified") or {}).get("coverage"),
                                                     b["direct"]["accuracy"]["rate"], pooled) for name, b, pooled in groups]) if has_verified else ""
    fig4 = charts.latency_chart([charts.LatencyRow(name, b["tribos"]["latency"], b["direct"]["latency"], pooled)
                                 for name, b, pooled in groups])
    n_flagged = len((summary.get("label_errors") or {}).get("excluded") or [])
    examples = summary.get("examples") or []
    ex_cards = [_example_html(ex, i + 1) for i, ex in enumerate(examples)]
    ex_notes = ""
    if not any(ex["kind"] == "only_direct" for ex in examples) and examples:
        ex_notes += '<p class="lead">No problem was solved by the direct model alone, so there is no counter-example to show.</p>'
    if not examples:
        ex_cards = ['<p class="lead">No problem was solved by exactly one of the systems, so there are no worked examples.</p>']
    if summary.get("examples_withheld_suites"):
        ex_notes += ('<p class="lead">GPQA questions are not reproduced here: the dataset authors ask that its questions not be '
                     'shown in plain text online.</p>')
    limits = _limitations(summary)
    sections = [
        _Section("Results by benchmark",
                 '<p class="lead">Share of problems answered correctly, on the problems both systems answered. Only problems '
                 'where exactly one system was right are evidence for a difference (McNemar test).'
                 + (f' {n_flagged} problem{"s" if n_flagged != 1 else ""} with a known wrong reference answer '
                                   f'{"are" if n_flagged != 1 else "is"} left out for both systems (see Data issues).' if n_flagged else "")
                 + '</p>' + _results_table(summary),
                 _figure(1, fig1, "Accuracy by benchmark. Columns: share of problems answered correctly; whiskers: 95% Wilson "
                                  "score intervals. One axis, 0–100%.")),
        _Section("Where the systems disagree",
                 '<p class="lead">Every paired problem falls into one of four outcomes. The coloured parts are the discordant '
                 'pairs, the only problems that say which system is better.</p>'
                 + _figure(2, fig2, "Paired outcomes per benchmark. Net is (only Tribos right) − (only direct right); "
                                    "p is the exact two-sided McNemar test on those discordant pairs.")),
    ]
    if has_verified:
        sections.append(_Section("How far to trust a verified answer",
                                 '<p class="lead">Tribos marks an answer verified when its verifier passes. If the mark is '
                                 'informative, verified answers are right more often than the rest.</p>'
                                 + _figure(3, fig3, "Accuracy of Tribos answers its verifier passed (filled) and of its other "
                                                    "answers (ring), with 95% Wilson intervals; the orange tick is the direct "
                                                    "model's accuracy on the same problems."),
                                 _verified_table(summary)))
    sections += [
        _Section("Time and cost", '<p class="lead">Wall-clock time per problem, including errors and timeouts at the time they took.</p>'
                 + _figure(4 if has_verified else 3, fig4, "Latency per problem: bars are medians, whiskers reach the 95th "
                                                           "percentile. One axis, in seconds."),
                 _cost_table(summary)),
        _Section("Run health", '<p class="lead">Errors and timeouts count as incorrect above. Gate failures are reported here and '
                 'do not change correctness.</p>' + _health_table(summary), "<h3>Gate failures by gate</h3>" + _gate_list(summary)),
        _Section("How final answers were read",
                 '<p class="lead">One final answer per response, found the same way for every system: the \\boxed{} value when '
                 'present, otherwise the grader model\'s reading of the stated final answer; then checked strictly, so no other '
                 'number in the working can rescue it. The rule-based fallback is used only when neither gives an answer; '
                 '"not recorded" marks results stored before the grader recorded its source.</p>' + _final_source_table(summary)),
        _Section("Data issues", _data_issues_html(summary)),
        _Section("Worked examples", ex_cards[0], "".join(ex_cards[1:]) + ex_notes),
        _Section("Methodology", "", _methodology(summary), page_break=True),
        _Section("Limitations", '<ul class="plain" style="margin-bottom:1.4mm">' + "".join(f"<li>{x}</li>" for x in limits[:1]) + "</ul>",
                 '<ul class="plain">' + "".join(f"<li>{x}</li>" for x in limits[1:]) + "</ul>"),
        _Section("Appendix: reproducibility", "", _appendix(summary, argv), page_break=True),
    ]
    body_sections = "".join(
        f'<section{" class=\"pb\"" if s.page_break else ""}><div class="keep"><h2><span class="no">{i}</span>{_e(s.title)}</h2>'
        f'{s.keep}</div>{s.rest}</section>'
        for i, s in enumerate(sections, 1))
    first = summary.get("first_run_started")
    kicker = f"Benchmark comparison · {_date(first).split(',')[0] if first else 'date not recorded'}"
    body = f"""<main class="sheet">
<header class="masthead">
<div class="brand"><img class="mark" src="{_brand_uri('tribos-mark.png')}" alt=""><img class="word" src="{_brand_uri('tribos-wordmark.png')}" alt="Tribos"></div>
<div class="kicker">{_e(kicker)}</div>
<h1>{_e(title)}</h1>
<p class="dek">{dek}</p>
</header>
<section class="hero"><div><div class="num">{_e(fmt_pp(p["difference"]))}</div>
<div class="num-label">accuracy difference, Tribos − direct<br>95% CI {_e(fmt_pp_ci(p["difference_ci95"]))} · {_e(fmt_p(p["mcnemar_p"]))}</div></div>
<div class="text">{_e(headline(summary))}</div></section>
<div class="tiles">{tiles_html}</div>
{callout}
{body_sections}
<div class="foot">Generated {_e(_date((summary.get("generated_at") or "")[:19]))} by <code>{_e(summary["generator"])}</code>.
All numbers are in summary.json. {n_suites} benchmark{"s" if n_suites != 1 else ""}, {p["n"]} paired problems.</div>
</main>"""
    fonts = font_css(html.unescape(re.sub(r"<[^>]+>", " ", body)) + title) if embed_fonts else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{fonts}
{CSS}</style></head>
<body>
{body}
</body></html>"""


# ---------------------------------------------------------------------------------------------------------------
# Markdown, PDF, files
# ---------------------------------------------------------------------------------------------------------------


def render_markdown(summary: dict[str, Any]) -> str:
    o = summary["overall"]
    lines = [f"# {summary['title']}", "", headline(summary), "",
             "| Benchmark | Pairs | Tribos | Direct | Difference (95% CI) | Only Tribos / only direct | McNemar p |",
             "|---|---:|---:|---:|---:|---:|---:|"]

    def row(name: str, b: dict[str, Any]) -> str:
        p = b["paired"]
        t, d = b["tribos"]["accuracy"], b["direct"]["accuracy"]
        diff = f"{fmt_pp(p['difference'])} ({fmt_pp_ci(p['difference_ci95'])})" if p["n"] else "–"
        return (f"| {name} | {p['n']} | {fmt_pct(t['rate'])} | {fmt_pct(d['rate'])} | {diff} "
                f"| {p['only_tribos']} / {p['only_direct']} | {charts.fmt_p(p['mcnemar_p'])} |")

    for b in summary["suites"].values():
        lines.append(row(b["name"], b))
    lines.append(row("**All (pooled)**", o))
    m = summary["macro"]
    lines.append(f"| Macro average | – | {fmt_pct(m['tribos_accuracy'])} | {fmt_pct(m['direct_accuracy'])} | {fmt_pp(m['difference'])} | – | – |")
    lines.append("")
    v = o["tribos"].get("verified")
    if v and v["coverage"]["n"]:
        lines.append(f"- Verified: Tribos marked {fmt_pct(v['coverage']['rate'], 0)} of answers verified; "
                     f"{fmt_pct(v['precision']['rate'])} of those were correct (95% CI {fmt_ci(v['precision']['ci95'])}), "
                     f"against {fmt_pct(v['other_accuracy']['rate'])} of the rest.")
    lt, ld = o["tribos"]["latency"], o["direct"]["latency"]
    lines.append(f"- Time per problem: median {charts.fmt_seconds(lt['median_s'])} (Tribos) vs {charts.fmt_seconds(ld['median_s'])} "
                 f"(direct); p95 {charts.fmt_seconds(lt['p95_s'])} vs {charts.fmt_seconds(ld['p95_s'])}.")
    h = o["health"]
    lines.append(f"- Errors / timeouts (counted as incorrect): Tribos {h['tribos']['error']} / {h['tribos']['timeout']}, "
                 f"direct {h['direct']['error']} / {h['direct']['timeout']}. Gate failures (not counted against accuracy): "
                 f"Tribos {sum(h['tribos']['gate_failures'].values())}, direct {sum(h['direct']['gate_failures'].values())}.")
    unp = o["unpaired"]
    if unp["tribos_only"] or unp["direct_only"]:
        lines.append(f"- Unpaired results left out: Tribos {len(unp['tribos_only'])}, direct {len(unp['direct_only'])}.")
    fs = {s: o[s]["final_answer_source"] for s in SYSTEMS}
    if fs["tribos"]["n"] or fs["direct"]["n"]:
        def shares(st: dict[str, Any]) -> str:
            return ", ".join(f"{FINAL_SOURCE_NAMES[k]} {fmt_pct(st[k]['share'], 0)}" for k in (*FINAL_ANSWER_SOURCES, "unknown")
                             if st[k]["k"])
        lines.append(f"- Final answer read from (numeric/symbolic): Tribos {shares(fs['tribos']) or '-'}; "
                     f"direct {shares(fs['direct']) or '-'}.")
    issues = (summary.get("label_errors") or {}).get("excluded") or []
    if issues:
        lines.append(f"- Known label errors set aside for both systems: {len(issues)} "
                     f"({', '.join(d['case_id'] + ': reference ' + str(d['reference_answer']) + ', correct ' + str(d['correct_answer']) for d in issues[:5])}"
                     f"{', ...' if len(issues) > 5 else ''}).")
    for w in summary["warnings"]:
        lines.append(f"- Note: {w}")
    lines += ["", "Method: same model, same problems (paired by case id); correctness by the answer-type check only (hard gates "
              "reported separately); 95% Wilson intervals; exact McNemar test on discordant pairs; Agresti-Min interval for the "
              "paired difference.", "", "Files: report.html, report.pdf, summary.json (every number), generated by "
              f"`{summary['generator']}`.", ""]
    return "\n".join(lines)


def write_pdf(html_path: Path, pdf_path: Path, *, title: str, footer: str) -> tuple[bool, str]:
    """Print report.html with headless Chromium (sync Playwright; call outside an event loop). (written, engine or reason)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return False, f"Playwright is not installed ({exc}); open report.html and print it instead"
    header = ("<div style='font-family:Segoe UI,Arial,sans-serif;font-size:7px;color:#63625d;width:100%;padding:0 15mm;"
              "display:flex;justify-content:space-between'><span style='letter-spacing:.12em;font-weight:600;color:#181e48'>TRIBOS"
              f"</span><span>{html.escape(title[:110])}</span></div>")
    foot = ("<div style='font-family:Segoe UI,Arial,sans-serif;font-size:7px;color:#63625d;width:100%;padding:0 15mm;"
            f"display:flex;justify-content:space-between'><span>{html.escape(footer[:140])}</span>"
            "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                page.evaluate("() => document.fonts.ready.then(() => true)")
                data = page.pdf(format="A4", print_background=True, display_header_footer=True, header_template=header,
                                footer_template=foot, prefer_css_page_size=True)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - no browser here: the HTML is still the report
        return False, f"Chromium PDF failed ({type(exc).__name__}: {str(exc)[:200]}); open report.html and print it instead"
    pdf_path.write_bytes(data)
    return True, "chromium"


def _json_default(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, set):
        return sorted(v)
    raise TypeError(f"not JSON serializable: {type(v).__name__}")


def build_report(tribos: Iterable[Path], direct: Iterable[Path], out_dir: Path, *, title: str | None = None,
                 seed: int | None = None, pilot_root: Path | None = None, pdf: bool = True,
                 argv: Sequence[str] | None = None, embed_fonts: bool = True,
                 label_errors_path: Path | None = DEFAULT_LABEL_ERRORS) -> dict[str, Any]:
    """Load the runs, analyse them and write report.html, report.pdf, summary.json and report.md into out_dir.
    label_errors_path: known_label_errors.json (default: the one in tribos/evals/data); None excludes nothing."""
    runs = {"tribos": [load_run(Path(p), "tribos") for p in tribos], "direct": [load_run(Path(p), "direct") for p in direct]}
    label_errors, le_warnings = load_label_errors(label_errors_path)
    summary = analyze(runs, title=title, seed=seed, pilot_root=pilot_root, label_errors=label_errors,
                      label_errors_path=label_errors_path if label_errors_path and label_errors_path.is_file() else None)
    summary["warnings"] = le_warnings + summary["warnings"]
    out_dir.mkdir(parents=True, exist_ok=True)
    page = render_html(summary, argv=argv, embed_fonts=embed_fonts)
    html_path = out_dir / "report.html"
    html_path.write_text(page, encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    summary["files"] = {"html": str(html_path), "markdown": str(out_dir / "report.md"), "summary": str(out_dir / "summary.json")}
    if pdf:
        footer = f"{summary.get('model') or ''} · {summary['overall']['paired']['n']} paired problems · {_date(summary.get('first_run_started')).split(',')[0]}"
        ok, how = write_pdf(html_path, out_dir / "report.pdf", title=summary["title"], footer=footer)
        summary["pdf"] = {"written": ok, ("engine" if ok else "reason"): how}
        if ok:
            summary["files"]["pdf"] = str(out_dir / "report.pdf")
    else:
        summary["pdf"] = {"written": False, "reason": "--no-pdf"}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=_json_default), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tribos.evals.benchmark_report",
                                description="Paired benchmark report: Tribos against the same model answering directly.")
    p.add_argument("pilot_root", nargs="?", help="directory holding direct/ and tribos/ run directories")
    p.add_argument("--tribos", nargs="+", action="extend", default=[], metavar="RUN_DIR", help="Tribos run directories")
    p.add_argument("--direct", nargs="+", action="extend", default=[], metavar="RUN_DIR", help="direct-baseline run directories")
    p.add_argument("--out", required=True, help="output directory for report.html, report.pdf, summary.json and report.md")
    p.add_argument("--title", help="report title (default: 'What the Tribos pipeline adds to <model>')")
    p.add_argument("--seed", type=int, help="the --seed the runs used (not stored in meta.json; read from pilot.log when present)")
    p.add_argument("--label-errors", default=str(DEFAULT_LABEL_ERRORS), metavar="JSON",
                   help="known wrong reference answers to set aside for both systems ({case_id: {question, reference_answer, "
                        "correct_answer, evidence, found}}; default tribos/evals/data/known_label_errors.json; 'none' to use none)")
    p.add_argument("--no-pdf", action="store_true", help="skip the PDF")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(args_list)
    tribos = [Path(x) for x in args.tribos]
    direct = [Path(x) for x in args.direct]
    root = Path(args.pilot_root) if args.pilot_root else None
    if root is not None:
        if not root.is_dir():
            print(f"Not a directory: {root}", file=sys.stderr)
            return 2
        tribos += discover_runs(root / "tribos") if (root / "tribos").is_dir() else []
        direct += discover_runs(root / "direct") if (root / "direct").is_dir() else []
    missing = [p for p in [*tribos, *direct] if not (p / "results.jsonl").is_file()]
    if missing:
        print("No results.jsonl in: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 2
    if not tribos or not direct:
        print("Need at least one Tribos and one direct run (a pilot root with tribos/ and direct/, or --tribos and --direct).",
              file=sys.stderr)
        return 2
    label_errors = None if str(args.label_errors).strip().lower() in ("", "none") else Path(args.label_errors)
    if label_errors is not None and not label_errors.is_file():
        print(f"Label-error file not found: {label_errors}", file=sys.stderr)
        return 2
    summary = build_report(tribos, direct, Path(args.out), title=args.title, seed=args.seed, pilot_root=root,
                           pdf=not args.no_pdf, argv=args_list, label_errors_path=label_errors)
    p = summary["overall"]["paired"]
    t, d = summary["overall"]["tribos"]["accuracy"], summary["overall"]["direct"]["accuracy"]
    print(f"{p['n']} paired problems: Tribos {t['k']}/{t['n']}, direct {d['k']}/{d['n']}, "
          f"only Tribos {p['only_tribos']}, only direct {p['only_direct']}, McNemar p {charts.fmt_p(p['mcnemar_p'])}", file=sys.stderr)
    for w in summary["warnings"]:
        print(f"note: {w}".encode("ascii", "replace").decode("ascii"), file=sys.stderr)
    for kind, path in summary["files"].items():
        print(f"{kind}: {path}", file=sys.stderr)
    if not summary["pdf"]["written"]:
        print(f"pdf not written: {summary['pdf'].get('reason')}".encode("ascii", "replace").decode("ascii"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
