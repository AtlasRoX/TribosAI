"""
The code-writing stage before the first draft (tribos.agentic.codeact).

It runs when the question asks for computation, numerical exploration or Python, the sandbox may execute code, and
no code module already computed the answer (computed_results covers it). Its notebook (cells, outputs, the model's
summary) goes into the evidence under CODEACT; the draft cites the printed values.
"""

from __future__ import annotations

import re
from typing import Any

from ..result_keys import CODEACT
from .context import RunContext, logger

_COMPUTE_RE = re.compile(
    r"\b(?:compute|calculate|evaluate|count|enumerate|tabulate|numerically|numerical(?:ly)?|estimate|approximate|"
    r"simulat\w*|explore|test\s+(?:the\s+|a\s+|this\s+)?conjectures?|verify\s+(?:numerically|for\s+(?:all|n|small))|"
    r"check\s+(?:for|up\s+to|all)|find\s+(?:all|the\s+smallest|the\s+largest|every))\b",
    re.I,
)


def wants_codeact(run: RunContext) -> bool:
    from ...agentic.sandbox import execution_permitted_now, sandbox_enabled
    from ...axiom.problem import has_math_intent
    from ...config.settings import get_bool
    from ..query_planner import PYTHON_REQUEST_RE
    from .presentation import computations_cover_question

    if not get_bool("TRIBOS_CODEACT") or not sandbox_enabled() or not execution_permitted_now():
        return False
    if getattr(run.ctx, "scope", "research") != "research":
        return False
    # agent_options.codeact == "always": the caller needs code run (a research project's experiments stage), even when
    # a code module computed part of the question or the wording does not look computational.
    forced = (run.agent_options or {}).get("codeact") == "always"
    if not forced and str((run.agent_options or {}).get("effort_level") or "medium") == "low":
        return False
    if not forced and computations_cover_question(run.tool_results):
        return False
    # A dataset question is worked by the analyst phase's own code loop; Python another tool already ran is reused.
    if run.execution_artifacts.get("sandbox_analysis") or getattr(run.ctx, "dataset_attachment", None) is not None:
        return False
    if any(getattr(run.tool_results.get(k), "success", False) for k in ("calcula", "calcula_run_python",
                                                                           "analysis_run_python")):
        return False
    if forced:
        return True
    q = run.clean_query or run.query or ""
    from .plot_stage import wants_plot

    if wants_plot(run):
        # The plot script computes and prints the numbers the figure shows (and a "verify in Python" part forces this
        # session through the task plan): a second, free-form Python session only made the writer wait (35 s).
        return False
    return bool(PYTHON_REQUEST_RE.search(q) or (_COMPUTE_RE.search(q) and has_math_intent(q)))


def _context(run: RunContext) -> str:
    """What other tools already established, so the session builds on it instead of redoing it."""
    from ..stem_evidence import stem_evidence

    try:
        evidence = "\n".join(stem_evidence(run.tool_results))[:4000]
    except Exception:  # noqa: BLE001
        evidence = ""
    # A research project's earlier stages (the hypotheses and plan to test) arrive as an agent option.
    earlier = str((run.agent_options or {}).get("research_context") or "").strip()
    if earlier:
        evidence = f"{evidence}\n\nEarlier stages of this research project:\n{earlier[:6000]}".strip()
    return evidence


async def run_codeact(run: RunContext) -> None:
    from ...agentic.codeact import solve
    from ...config.settings import get_int
    from ...tools.registry import ToolResult
    from .llm_call import ask, budget_admits

    if not wants_codeact(run):
        return
    steps = get_int("TRIBOS_CODEACT_MAX_STEPS")
    if not budget_admits(run, steps + 2):
        return
    await run.emit("codeact", "Working the problem in Python", f"up to {steps} cells", status="running")

    async def on_cell(n: int, cell: dict[str, Any]) -> None:
        first = (cell.get("stdout") or cell.get("error") or "").strip().splitlines()[:1]
        await run.emit("codeact", f"Python cell {n}: {cell['status']}", (first[0] if first else "")[:200],
                       status="running")

    try:
        data = await solve(run.clean_query or run.query, lambda s, m: ask(run, s, m), max_steps=steps,
                           context=_context(run), on_cell=on_cell)
    except Exception as exc:  # noqa: BLE001 - a failed session never blocks the answer
        logger.info("codeact skipped: %s", exc)
        await run.emit("codeact", "Python session failed", str(exc)[:200], status="error")
        return
    ok = data["ok_cells"] > 0
    run.tool_results[CODEACT] = ToolResult(success=ok, tool_name=CODEACT, data=data,
                                           error=None if ok else "no Python cell ran successfully")
    run.execution_artifacts[CODEACT] = data
    await run.emit("codeact", "Worked the problem in Python",
                   f"{data['ok_cells']} of {data['steps']} cells ran; {data['stopped']}", status="done" if ok else "error")


__all__ = ["run_codeact", "wants_codeact"]
