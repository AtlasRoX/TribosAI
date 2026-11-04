"""
Running one research test and turning its outcome into a ledger finding.

- compute / simulate / estimate: a CodeAct session (the model writes Python cells, the sandbox runs them) with the
  research time ceiling. The last cell sets `result`, a dict of the named quantities (and chart series). When the
  test asks for replication, a second session re-implements it independently, without seeing the first one's code,
  and every quantity is compared (tribos.axiom.accuracy.compare_results): agreement makes the finding "replicated".
- prove: a written proof plus formalisation in Lean 4 (tribos.verify.formal.prove.formalise_and_check); a clean Lean
  compile makes it "formal", otherwise the proof stands as "reasoned".
- literature: a research job (search on, memory recall off), whose cited answer is "sourced".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .ledger import quantities_from_result, save_figures
from .model import ResearchModel

logger = logging.getLogger(__name__)

JobRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]  # request -> {"status", "result", "error"}

COMPUTE_SYSTEM = """You run one experiment of a research project in a persistent Python session, like a careful scientist with a lab notebook.

Each reply: one or two sentences of reasoning, then exactly ONE ```python``` block. It runs in a sandbox and you see its printed output next turn. Only these modules can be imported: {modules}. Anything else (time, os, sys, random, heapq, bisect, subprocess, threading, files, network) is rejected: use numpy.random with a seed for randomness, and collections/itertools/functools for data structures. Variables persist between blocks, but every block re-runs the earlier successful blocks first, so put a heavy computation in one block, not across many.

Rules:
- Do exactly the experiment described. Use the exact ranges, parameters and definitions given. Prefer exact integer/rational arithmetic; with floats, say so and keep full precision.
- Print what you rely on. Check the result a second way inside the session when cheap (small cases by brute force, an identity, a known value).
- Seed randomness. Each block may run for at most {timeout} seconds; write vectorised or memoised code.
- When a plot helps the reader (a trend, a distribution, a fit), draw it with matplotlib: a title, labelled axes with units, a legend when there are several series. Do not call plt.show().
- Your LAST block must assign `result`, a dict whose keys include {quantities} (snake_case names, plain int/float/str values or short lists), plus optionally result["series"] = {{"name": {{"x": [...], "y": [...], "x_label": "...", "y_label": "..."}}}} for data worth charting (at most 400 points each).
- If something cannot be done as specified, say why in the final answer; never invent a number.

When the result is set and printed, reply with no code block and start with "FINAL ANSWER:", then state the results, how they were checked, and what they do and do not show."""

REPLICATE_NOTE = """
INDEPENDENT REPLICATION: another scientist already ran this experiment. Re-implement it from the description alone with a DIFFERENT algorithm or formulation than the obvious one (for example direct iteration instead of memoisation, a closed form instead of a sum, a different library routine). Report the same `result` keys so the two can be compared exactly."""

PROOF_SYSTEM = """You are a mathematician writing a complete, rigorous proof for a research report.

Write: a precise statement (with every hypothesis), then a proof in clear steps that a referee can check, citing standard results by name. If the statement is false or cannot be proved with the information available, say so plainly and explain what can be proved instead. Use LaTeX ($...$, $$...$$). No preamble."""


def _test_prompt(test: dict[str, Any], goal: str, context: str) -> str:
    parts = [f"Research goal (for orientation only): {goal[:1500]}", "",
             f"Experiment {test['id']}: {test['title']}", f"Objective: {test['objective']}"]
    if test.get("method"):
        parts.append(f"Method: {test['method']}")
    if test.get("acceptance"):
        parts.append(f"Done when: {test['acceptance']}")
    if test.get("last_error"):
        parts.append(f"A previous attempt failed: {test['last_error'][:600]}\nUse a different approach this time.")
    if context.strip():
        parts += ["", "Earlier findings you may build on:", context.strip()[:6000]]
    return "\n".join(parts)


async def _codeact(model: ResearchModel, prompt: str, *, quantities: list[str], steps: int, effort: str,
                   timeout_s: int, replicate: bool, on_cell: Callable[[int, dict[str, Any]], Awaitable[None]] | None
                   ) -> tuple[dict[str, Any], Any, list[dict[str, Any]]]:
    from ..codeact import solve
    from ..sandbox import research_ceiling
    from ..sandbox.policy import ALLOWED_MODULE_ROOTS
    from ..sandbox.session import PythonSession

    system = COMPUTE_SYSTEM.replace("{modules}", ", ".join(sorted(ALLOWED_MODULE_ROOTS))).replace(
        "{timeout}", str(timeout_s)).replace(
        "{quantities}", ", ".join(quantities) if quantities else "the values the objective asks for")
    system = system.replace("{{", "{").replace("}}", "}") + (REPLICATE_NOTE if replicate else "")

    async def ask(_system: str, messages: list[tuple[str, str]]) -> str:
        return await model.text(system, messages, effort=effort, max_tokens=24000)

    session = PythonSession(timeout_s=float(timeout_s))
    with research_ceiling(timeout_s):
        data = await solve(prompt, ask, max_steps=steps, on_cell=on_cell, session=session)
    result = None
    figures: list[dict[str, Any]] = []
    for cell in session.history:
        if cell.status == "ok":
            if cell.result is not None:
                result = cell.result
            if cell.figures:
                # Every cell re-runs the earlier ones, so the last cell that drew anything holds every figure once.
                figures = list(cell.figures)
    return data, result, figures[-4:]


def _exact_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def replication_model() -> ResearchModel | None:
    """The model that re-implements numeric results, when TRIBOS_RESEARCH_REPLICATION_MODEL names one; otherwise the
    same model replicates (a separate session with a different algorithm, which the finding records)."""
    from ...config.settings import get_str
    from .model import LiveModel

    name = str(get_str("TRIBOS_RESEARCH_REPLICATION_MODEL") or "").strip()
    return LiveModel(name) if name else None


async def run_compute(model: ResearchModel, test: dict[str, Any], *, goal: str, context: str, finding_id: str,
                      files_dir: str, steps: int, effort: str, timeout_s: int, cross_check: bool,
                      on_progress: Callable[[str], Awaitable[None]] | None = None) -> dict[str, Any]:
    from ...axiom.accuracy import compare_results

    started = time.time()

    async def on_cell(n: int, cell: dict[str, Any]) -> None:
        if on_progress is not None:
            first = (cell.get("stdout") or cell.get("error") or "").strip().splitlines()[:1]
            await on_progress(f"{test['id']} cell {n}: {cell['status']}" + (f" — {first[0][:120]}" if first else ""))

    prompt = _test_prompt(test, goal, context)
    data, result, figures = await _codeact(model, prompt, quantities=test.get("quantities") or [], steps=steps,
                                           effort=effort, timeout_s=timeout_s, replicate=False, on_cell=on_cell)
    quantities, series = quantities_from_result(result, test.get("quantities"))
    cells = [{"code": c["code"][:20000], "stdout": c["stdout"][:4000], "status": c["status"],
              "error": (c.get("error") or "")[:2000], "seconds": c.get("seconds")} for c in data["cells"]]
    checks: list[dict[str, Any]] = []
    ok = data["ok_cells"] > 0 and result is not None and bool(quantities or series)
    tier = "computed" if ok else "none"
    replication = None
    wants_replication = test.get("tier") in ("replicated", "certified") or (cross_check and test.get("tier") != "computed")
    if ok and cross_check and wants_replication and quantities:
        if on_progress is not None:
            await on_progress(f"{test['id']}: separate re-implementation")
        try:
            replicator = replication_model() or model
            data_b, result_b, _ = await _codeact(replicator, prompt, quantities=[q["name"] for q in quantities],
                                                 steps=steps, effort=effort, timeout_s=timeout_s, replicate=True,
                                                 on_cell=None)
            keys = [q["name"] for q in quantities]
            cmp = compare_results(result if isinstance(result, dict) else {"result": result},
                                  result_b if isinstance(result_b, dict) else {"result": result_b},
                                  rtol=1e-6, atol=1e-9, keys=keys)
            same_model = getattr(replicator, "model_name", None) == getattr(model, "model_name", None)
            replication = {"status": cmp["status"], "agree": cmp["agree"], "disagree": cmp["disagree"],
                           "missing": cmp["missing"], "rows": cmp["rows"][:40],
                           "model": getattr(replicator, "model_name", None), "same_model": same_model,
                           "method": "a separate session, told to use a different algorithm, without the first code",
                           "code": "\n\n# ---\n\n".join(c["code"] for c in data_b["cells"] if c["status"] == "ok")[:20000]}
            all_agree = cmp["status"] == "agree"
            replication["conflicts"] = cmp["disagree"] - cmp["missing"]
            who = "the same model" if same_model else f"a second model ({replication['model']})"
            checks.append({"name": "separate re-implementation", "passed": all_agree,
                           "detail": (f"{cmp['note']} (re-implemented by {who} with a different algorithm)" if all_agree
                                      else f"{cmp['agree']} of {cmp['compared']} quantities agree; "
                                           f"{cmp['disagree'] - cmp['missing']} differ; {cmp['missing']} missing from one run")})
            if all_agree:
                tier = "replicated"
                # Exact arithmetic reproduced exactly: every compared quantity is an integer in both runs (Python
                # integers are exact) and the two separately written computations agree to the last digit. This is
                # the `certified` level (AUDIT-107); floating-point results stop at `replicated`.
                if cmp["rows"] and all(_exact_int(r.get("a")) and _exact_int(r.get("b")) and r.get("a") == r.get("b")
                                       for r in cmp["rows"]):
                    tier = "certified"
                    checks.append({"name": "exact arithmetic", "passed": True,
                                   "detail": f"all {len(cmp['rows'])} quantities are exact integers, reproduced exactly"})
        except Exception as exc:  # noqa: BLE001 - the first run still stands as computed
            checks.append({"name": "separate re-implementation", "passed": False,
                           "detail": f"could not run: {type(exc).__name__}: {str(exc)[:200]}"})
    figs = save_figures(files_dir, finding_id, figures) if ok else []
    status = "passed" if ok else "failed"
    if ok and replication and replication.get("conflicts", 0) > 0:
        status = "disputed"  # two implementations gave different values: neither is trusted until the judge resolves it
    error = None
    if not ok:
        last = next((c for c in reversed(cells) if c["status"] != "ok"), None)
        error = ("no `result` was set" if data["ok_cells"] else "no cell ran") + (
            f"; last error: {last['error'][:400]}" if last and last.get("error") else "")
    return {"id": finding_id, "test_id": test["id"], "kind": test["kind"], "status": status, "tier": tier,
            "summary": str(data.get("final") or "")[:3000], "quantities": quantities, "series": series,
            "cells": cells, "figures": figs, "checks": checks, "replication": replication, "error": error,
            "seconds": round(time.time() - started, 1)}


async def run_prove(model: ResearchModel, test: dict[str, Any], *, goal: str, context: str, finding_id: str,
                    effort: str, on_progress: Callable[[str], Awaitable[None]] | None = None) -> dict[str, Any]:
    from ...verify.formal.prove import formalise_and_check

    started = time.time()
    statement = test["objective"]
    proof_task = asyncio.create_task(model.text(
        PROOF_SYSTEM, f"Statement to prove: {statement}\nMethod hint: {test.get('method') or '-'}\n"
                      f"Context (research goal): {goal[:1200]}\n\nEarlier findings:\n{context[:3000]}",
        effort=effort, max_tokens=32000))

    async def complete(system: str, user: str) -> str:
        return await model.text(system, user, effort=effort, max_tokens=24000)

    async def on_step(msg: str) -> None:
        if on_progress is not None:
            await on_progress(f"{test['id']} Lean: {msg[:140]}")

    try:
        lean = await formalise_and_check(statement, complete, on_step=on_step)
    except Exception as exc:  # noqa: BLE001 - the written proof still stands
        lean = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}", "lean_code": "", "statement": ""}
    try:
        written = await proof_task
    except Exception as exc:  # noqa: BLE001
        written = ""
        logger.info("research proof text failed: %s", exc)
    verified = lean.get("status") == "verified"
    false_claim = bool(written) and any(w in written.lower()[:600] for w in ("is false", "counterexample", "cannot be proved"))
    tier = "formal" if verified else ("reasoned" if written and not false_claim else "none")
    status = "passed" if (verified or (written and not false_claim)) else ("refuted" if false_claim else "failed")
    return {"id": finding_id, "test_id": test["id"], "kind": "prove", "status": status, "tier": tier,
            "summary": (written.split("\n\n", 1)[0] if written else str(lean.get("error") or ""))[:1500],
            "quantities": [], "series": [], "cells": [], "figures": [],
            "checks": [{"name": "Lean 4 formal proof", "passed": verified,
                        "detail": str(lean.get("title") or lean.get("status") or "")[:200]}],
            "proof": {"statement": statement, "text": written[:20000], "lean_status": lean.get("status"),
                      "lean_statement": str(lean.get("statement") or "")[:4000],
                      "lean_code": str(lean.get("lean_code") or "")[:20000] if verified else "",
                      "lean_error": None if verified else str(lean.get("error") or "")[:800]},
            "error": None if status == "passed" else (lean.get("error") or "no proof was produced"),
            "seconds": round(time.time() - started, 1)}


async def run_literature(job: JobRunner, test: dict[str, Any], *, goal: str, context: str, finding_id: str,
                         request: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    req = dict(request)
    req["message"] = (f"Find in published sources: {test['objective']}\n\nAnswer precisely, quote the exact values or "
                      f"statements, and cite every source. Research goal for orientation: {goal[:800]}")
    out = await job(req)
    result = out.get("result") or {}
    text = str(result.get("response") or "")
    ok = out.get("status") == "succeeded" and bool(text.strip())
    cites = result.get("citations") or {}
    n_cites = len(cites.get("entries") or {}) if isinstance(cites, dict) else 0
    return {"id": finding_id, "test_id": test["id"], "kind": "literature", "status": "passed" if ok else "failed",
            "tier": "sourced" if ok and n_cites else ("reasoned" if ok else "none"),
            "summary": text[:4000], "quantities": [], "series": [], "cells": [], "figures": [],
            "checks": [{"name": "cited sources", "passed": n_cites > 0, "detail": f"{n_cites} source(s)"}],
            "citations": cites, "error": None if ok else (out.get("error") or "the search produced no answer"),
            "seconds": round(time.time() - started, 1)}


__all__ = ["COMPUTE_SYSTEM", "run_compute", "run_literature", "run_prove"]
