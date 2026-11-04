"""
How long a research project still needs: the tests left to run, run in parallel, plus the analysis, judging and the
thesis, using durations measured on earlier tests of the same kind and size (this project's first, then every
project's), falling back to priors. The band (low, high) widens with the rounds the loop may still add.
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any

# Seconds, (kind, cost) -> prior when nothing has been measured yet.
PRIOR = {
    ("compute", "s"): 120, ("compute", "m"): 300, ("compute", "l"): 720,
    ("simulate", "s"): 150, ("simulate", "m"): 360, ("simulate", "l"): 800,
    ("estimate", "s"): 90, ("estimate", "m"): 200, ("estimate", "l"): 400,
    ("prove", "s"): 150, ("prove", "m"): 300, ("prove", "l"): 600,
    ("literature", "s"): 180, ("literature", "m"): 240, ("literature", "l"): 360,
}
REVIEW_S, CHARTER_S, ANALYSIS_S, JUDGE_S, THESIS_S = 300, 90, 90, 90, 540


def measured(ledgers: list[list[dict[str, Any]]], tests_by_id: list[dict[str, dict[str, Any]]]) -> dict[tuple, float]:
    """Median seconds per (kind, cost) from finished findings."""
    samples: dict[tuple, list[float]] = {}
    for ledger, tests in zip(ledgers, tests_by_id, strict=False):
        for f in ledger:
            t = tests.get(str(f.get("test_id")))
            if t and f.get("seconds"):
                samples.setdefault((t["kind"], t["cost"]), []).append(float(f["seconds"]))
    return {k: statistics.median(v) for k, v in samples.items() if v}


def estimate(campaign: dict[str, Any], *, history: dict[tuple, float] | None = None, parallel: int = 2,
             now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    history = dict(history or {})
    charter = campaign.get("charter")
    loop = campaign.get("loop") or {}
    if campaign.get("status") in ("succeeded", "failed", "cancelled"):
        return {"remaining_s": 0, "low_s": 0, "high_s": 0, "basis": "finished", "updated_at": now}
    if not charter:
        rough = rough_estimate(campaign.get("goal") or "")
        review_left = 0 if (campaign.get("review") or {}).get("status") == "succeeded" else REVIEW_S
        rough.update(remaining_s=rough["remaining_s"] - (REVIEW_S - review_left), updated_at=now)
        return rough
    own = measured([campaign.get("ledger") or []], [{t["id"]: t for t in charter["tests"]}])
    durations = {**PRIOR, **history, **own}
    pending = [t for t in charter["tests"] if t["status"] in ("pending", "running", "retry")]
    work = [durations.get((t["kind"], t["cost"]), PRIOR.get((t["kind"], t["cost"]), 300)) for t in pending]
    # Running tests are partly done.
    for i, t in enumerate(pending):
        if t["status"] == "running" and t.get("started_at"):
            work[i] = max(30.0, work[i] - (now - float(t["started_at"])))
    lanes = max(1, parallel)
    test_time = (sum(work) / lanes + (max(work) if work else 0) * (1 - 1 / lanes)) if work else 0.0
    open_d = sum(1 for d in charter["deliverables"] if d.get("status") not in ("done", "infeasible"))
    rounds_left_low = 1 if (pending or open_d) else 0
    rounds_left_high = min(4, max(1, open_d)) if open_d else rounds_left_low
    per_round = ANALYSIS_S + JUDGE_S
    avg_test = statistics.median(list(durations.values()))
    base = test_time + rounds_left_low * per_round + THESIS_S
    low = base * 0.8
    high = base + (rounds_left_high - rounds_left_low) * (per_round + avg_test * 2 / lanes) + base * 0.25
    basis = (f"measured on {sum(1 for f in campaign.get('ledger') or [] if f.get('seconds'))} test(s) of this project"
             if own else ("durations of earlier projects' tests" if history else "typical durations (no measurements yet)"))
    if loop.get("phase") == "thesis":
        base, low, high = THESIS_S * 0.6, THESIS_S * 0.3, THESIS_S
    return {"remaining_s": int(base), "low_s": int(low), "high_s": int(high), "basis": basis,
            "pending_tests": len(pending), "open_deliverables": open_d, "updated_at": now}


_HEAVY_RE = re.compile(r"10\^?\s*[6-9]|10\*\*[6-9]|\bmillion|\bbillion|\bevery n up to|\bsweep|\bmonte carlo", re.I)
_PROOF_RE = re.compile(r"\bprove|\bproof|\btheorem|\blemma", re.I)


def rough_estimate(goal: str) -> dict[str, Any]:
    """Before the plan exists: from the goal's size (numbered parts, heavy computation, proofs, sources)."""
    from .charter import goal_items

    parts = max(1, len(goal_items(goal)) or 1 + goal.count(";") + len(re.findall(r"\band\b", goal)) // 3)
    heavy = bool(_HEAVY_RE.search(goal))
    proofs = len(_PROOF_RE.findall(goal))
    per_part = 360 if heavy else 240
    base = REVIEW_S + CHARTER_S + parts * per_part / 2 + proofs * 120 + 2 * (ANALYSIS_S + JUDGE_S) + THESIS_S
    return {"remaining_s": int(base), "low_s": int(base * 0.7), "high_s": int(base * 1.9),
            "basis": f"rough, from the goal ({parts} part(s){', heavy computation' if heavy else ''}"
                     f"{', proofs' if proofs else ''}); refined once the plan exists", "rough": True,
            "updated_at": time.time()}


__all__ = ["estimate", "measured", "rough_estimate"]
