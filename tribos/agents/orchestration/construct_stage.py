"""
Construct mode in the pipeline (tribos.agentic.construct): a construction problem from the library is searched by
evolving model-written programs, every candidate scored exactly in the sandbox. Runs inside compute_results, so the
result is shown and cited like any other code-computed result.
"""

from __future__ import annotations

from typing import Any

from .context import RunContext, logger


async def run_construct(run: RunContext, question: str) -> dict[str, Any] | None:
    from ...agentic.construct import detect_problem, facts, search
    from ...agentic.sandbox import execution_permitted_now, sandbox_enabled
    from ...config.settings import get_bool, get_int
    from .llm_call import ask, budget_admits

    if not get_bool("TRIBOS_CONSTRUCT") or not sandbox_enabled() or not execution_permitted_now():
        return None
    problem = detect_problem(question)
    if problem is None:
        return None
    candidates = get_int("TRIBOS_CONSTRUCT_GENERATIONS")
    if not budget_admits(run, candidates + 2):
        candidates = max(0, min(candidates, 4))
    await run.emit("construct", f"Searching constructions: {problem.title}",
                   f"{candidates} model-written programs, each scored exactly", status="running")

    async def progress(n: int, entry: Any, best: Any) -> None:
        got = f"value {entry.value}" if entry.valid else "invalid"
        await run.emit("construct", f"Program {n}: {got}", f"best so far {best.value}", status="running")

    try:
        result = await search(problem, lambda s, p: ask(run, s, p, timeout_s=180), candidates=candidates,
                              on_progress=progress)
    except Exception as exc:  # noqa: BLE001 - a failed search never blocks the answer
        logger.info("construct mode skipped: %s", exc)
        await run.emit("construct", "Construction search failed", str(exc)[:200], status="error")
        return None
    data = facts(result)
    await run.emit("construct", f"Best {problem.title}: {result['best'].value}", data["verdict"], status="done")
    return data


__all__ = ["run_construct"]
