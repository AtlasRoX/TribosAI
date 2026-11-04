"""Certified critical points for a question that asks for them (tribos.axiom.certified_critical).

Runs before the plot and the Python session: it takes well under a second, so the plot can mark exactly the proved
points and the answer can say the list is complete because interval arithmetic proved it, not because a multistart
search happened to find no more.
"""

from __future__ import annotations

import asyncio
import re

from .context import RunContext, logger

ARTIFACT = "critical_points"
_ASKS_RE = re.compile(r"\b(?:critical|stationary)\s+points?\b|\bextrem(?:a|um)\b|\blocal\s+(?:min|max)", re.I)


def _summary(result: dict) -> str:
    pts = result.get("points") or []
    if not pts:
        return "none"
    return "; ".join(f"({', '.join(f'{v:.6g}' for v in p['point'])}) with f = {p['value']:.6g}, {p['classification']}"
                     for p in pts)


async def run_certified_critical(run: RunContext) -> None:
    from ...axiom.certified_critical import certify_critical_points, extract_problem

    question = run.clean_query or run.query or ""
    if getattr(run.ctx, "scope", "research") != "research" or not _ASKS_RE.search(question):
        return
    problem = extract_problem(question)
    if problem is None:
        return
    expr, variables, bounds = problem
    try:
        result = await asyncio.to_thread(certify_critical_points, expr, variables, bounds)
    except Exception as exc:  # noqa: BLE001 - certification is extra assurance, never a blocker
        logger.info("Certified critical points skipped: %s", exc)
        return
    if result["status"] == "unsupported":
        return
    result["function"] = str(expr)
    run.execution_artifacts[ARTIFACT] = result
    domain = " × ".join(f"[{lo:g}, {hi:g}]" for lo, hi in bounds)
    found = _summary(result)
    if result["status"] == "complete":
        title = (f"Proved: exactly {len(result['points'])} critical point{'s' if len(result['points']) != 1 else ''}"
                 if result["points"] else "Proved: no critical points in the domain")
        note = (f"CERTIFIED CRITICAL POINTS (interval arithmetic, complete search of {domain}): {found}. This list is "
                "proved complete: state that completeness was proved by interval branch-and-bound with the Krawczyk "
                "uniqueness test, not merely found by root-finding from several starting points. Use exactly these "
                "points and values; do not add or drop any.")
    else:
        title = f"Certified {len(result['points'])} critical point(s); {result['undecided_count']} small region(s) undecided"
        note = (f"CRITICAL POINTS (interval arithmetic over {domain}): certified {found}; "
                f"{result['undecided_count']} small region(s) could not be decided, so completeness is NOT proved: say so.")
    run.gather_notes.append(note)
    await run.emit("critical_points", title, f"{found} · {result['boxes_examined']} boxes examined",
                   status="done", agent="Axiom")


def plot_hint(run: RunContext) -> str:
    """For the plot script: the proved critical points to mark (and only those)."""
    result = run.execution_artifacts.get(ARTIFACT)
    if not isinstance(result, dict) or result.get("status") not in ("complete", "incomplete"):
        return ""
    pts = result.get("points") or []
    proved = "proved complete" if result["status"] == "complete" else "certified, completeness not proved"
    if not pts:
        return (f"\n\nCritical points ({proved} by interval arithmetic): NONE in the domain. Mark none and print "
                "'critical points = none in the domain'.")
    listed = "; ".join(f"({', '.join(repr(v) for v in p['point'])}) {p['classification']}" for p in pts)
    return f"\n\nCritical points ({proved} by interval arithmetic): {listed}. Mark exactly these, no others."


__all__ = ["ARTIFACT", "plot_hint", "run_certified_critical"]
