"""
Analysis and judgement after each research round, and the adaptive stopping rule.

The judge (one model call) reads the charter and the ledger and proposes: the status of every deliverable with the
findings behind it, a verdict on every hypothesis, the discrepancies it sees, new tests, and whether the project has
reached its conclusion. The code below accepts only what the evidence supports:

- a deliverable is "done" only when it cites a finding that exists, passed (not disputed), and meets the
  deliverable's required verification tier; otherwise it falls back to "partial" (some evidence) or "open";
- "infeasible" needs a stated reason;
- a hypothesis verdict needs at least one cited finding that exists (a decided verdict without evidence becomes
  "undecided");
- "concluded" holds only when every deliverable is done or infeasible.

Stopping (stop_reason): concluded; stagnation (TRIBOS_RESEARCH_STAGNATION_ROUNDS rounds without progress); nothing
left to run; or a safety ceiling (rounds, hours, test runs). Progress in a round is a deliverable newly done, a
hypothesis newly decided, or a finding newly at "replicated" or stronger.
"""

from __future__ import annotations

import time
from typing import Any

from .charter import charter_text
from .ledger import ledger_text, meets, rank

ANALYSIS_SYSTEM = """You are the critical analyst of a research project. Read the plan and every finding so far and write a short critical analysis in Markdown (at most 400 words):
- what the findings establish, with their exact numbers and finding ids (F1, F2, ...);
- disagreements, suspicious numbers, numerical artefacts, missing controls or checks;
- what is still missing for each deliverable that is not done.
Be specific and sceptical. A computation is evidence, not a proof. Never invent a number."""

JUDGE_SYSTEM = """You are the judge of a research project. Decide, from the evidence only, how far the project has got and what to do next.

Reply with ONE JSON object:
{
 "deliverables": [{"id": "D1", "status": "done|partial|open|infeasible", "evidence": ["F3"], "note": "one sentence"}],
 "hypotheses": [{"id": "H1", "verdict": "supported|refuted|undecided", "evidence": ["F2"], "note": "one sentence"}],
 "discrepancies": ["..."],
 "new_tests": [{"title": "...", "kind": "compute|prove|simulate|literature|estimate", "objective": "...", "method": "...", "acceptance": "...", "quantities": ["..."], "serves": ["D2"], "hypotheses": ["H1"], "depends_on": [], "cost": "s|m|l", "tier": "replicated|computed|certified|formal|sourced|reasoned"}],
 "concluded": false,
 "headline": "one sentence a reader should take away now"
}

Rules:
- "done" only when a passed finding fully meets the deliverable's acceptance criterion; cite it. "infeasible" only with a concrete reason (e.g. an open problem, or beyond any feasible computation) in the note.
- Propose new tests only for gaps that block a deliverable or a hypothesis verdict, or to resolve a discrepancy (re-run a doubtful number another way). Do not repeat a test that already passed. At most 6 new tests.
- "concluded" is true only when every deliverable is done or infeasible.
- Reply with the JSON object only."""


def round_context(campaign: dict[str, Any], *, chars: int = 24000) -> str:
    charter = campaign["charter"]
    parts = [f"Research goal:\n{campaign['goal']}", "", charter_text(charter), "",
             "Findings (ledger):", ledger_text(campaign.get("ledger") or [], limit_chars=chars)]
    instr = (campaign.get("loop") or {}).get("instructions") or []
    if instr:
        parts += ["", "Follow-up instructions from the user (must be addressed):"] + [f"- {i}" for i in instr[-5:]]
    return "\n".join(parts)


def apply_judgement(campaign: dict[str, Any], raw: Any) -> dict[str, Any]:
    """Validate the judge's proposal against the ledger and write it into the charter. Returns the accepted record."""
    raw = raw if isinstance(raw, dict) else {}
    charter = campaign["charter"]
    ledger = {f["id"]: f for f in campaign.get("ledger") or []}
    good = {fid for fid, f in ledger.items() if f.get("status") == "passed"}
    tests = {t["id"]: t for t in charter.get("tests") or []}

    def relevant(fid: str, key: str, item_id: str) -> bool:
        """The finding comes from a test the charter planned for this deliverable (serves) or hypothesis."""
        test = tests.get(ledger[fid].get("test_id"))
        return test is not None and item_id in (test.get(key) or [])

    props = {str(d.get("id")): d for d in raw.get("deliverables") or [] if isinstance(d, dict)}
    accepted_d = []
    for d in charter["deliverables"]:
        p = props.get(d["id"], {})
        status = str(p.get("status") or d.get("status") or "open").lower()
        evidence = [e for e in (p.get("evidence") or d.get("evidence") or []) if e in ledger]
        note = str(p.get("note") or (d.get("note") if not p else "") or "")[:400]
        if status == "done":
            # Done needs a passed finding at the required level from a test planned for this deliverable: a finding
            # of another deliverable's test, however strong, does not settle this one (audit AUDIT-106).
            strong = [e for e in evidence if e in good and meets(ledger[e].get("tier"), d.get("tier"))
                      and relevant(e, "serves", d["id"])]
            if not strong:
                weaker = [e for e in evidence if e in good and relevant(e, "serves", d["id"])]
                status = "partial" if weaker else "open"
                if weaker:
                    note = (note + " " if note else "") + (
                        f"(not yet at the required '{d.get('tier')}' verification level)")
                elif any(e in good for e in evidence):
                    note = (note + " " if note else "") + "(the cited findings come from tests for other deliverables)"
        elif status == "infeasible" and len(note) < 15:
            status = "partial" if evidence else "open"
        elif status not in ("partial", "open", "infeasible"):
            status = "partial" if evidence else "open"
        d.update(status=status, evidence=evidence, note=note.strip())
        accepted_d.append({"id": d["id"], "status": status, "evidence": evidence})
    hprops = {str(h.get("id")): h for h in raw.get("hypotheses") or [] if isinstance(h, dict)}
    for h in charter["hypotheses"]:
        p = hprops.get(h["id"], {})
        verdict = str(p.get("verdict") or h.get("verdict") or "untested").lower()
        # A judgement that says nothing about this hypothesis keeps its earlier verdict and evidence.
        evidence = [e for e in (p.get("evidence") or ([] if p else h.get("evidence")) or []) if e in ledger]
        note = str(p.get("note") or (h.get("note") if not p else "") or "")[:400]
        # A decided verdict needs evidence from a test planned for this hypothesis, at least at the `sourced` level
        # (a model-written argument alone decides nothing), and "supported" may not cite a finding that refutes it
        # (audit AUDIT-106).
        mine = [e for e in evidence if relevant(e, "hypotheses", h["id"])]
        decisive = [e for e in mine if e in good and meets(ledger[e].get("tier"), "sourced")]
        contrary = [e for e in mine if ledger[e].get("status") == "refuted"]
        reason = ""
        if verdict == "supported" and (contrary or not decisive):
            reason = ("a cited finding refutes it" if contrary else
                      "no finding of its own tests at the sourced level or stronger supports it")
        elif verdict == "refuted" and not (contrary or decisive):
            reason = "no finding of its own tests at the sourced level or stronger refutes it"
        if reason:
            verdict = "undecided"
            note = (note + " " if note else "") + f"(undecided: {reason})"
        if verdict not in ("supported", "refuted", "undecided", "untested"):
            verdict = "undecided"
        h.update(verdict=verdict, evidence=evidence or h.get("evidence") or [], note=note.strip())
    open_d = [d for d in charter["deliverables"] if d["status"] not in ("done", "infeasible")]
    return {"deliverables": accepted_d, "discrepancies": [str(x)[:400] for x in (raw.get("discrepancies") or [])][:10],
            "new_tests": [t for t in (raw.get("new_tests") or []) if isinstance(t, dict)][:6],
            "concluded": not open_d, "model_concluded": bool(raw.get("concluded")),
            "headline": str(raw.get("headline") or "")[:300]}


def progress_snapshot(campaign: dict[str, Any]) -> dict[str, Any]:
    charter = campaign["charter"]
    return {"done": sorted(d["id"] for d in charter["deliverables"] if d["status"] in ("done", "infeasible")),
            "decided": sorted(h["id"] for h in charter["hypotheses"] if h["verdict"] in ("supported", "refuted")),
            "strong": sorted(f["id"] for f in campaign.get("ledger") or []
                             if f.get("status") == "passed" and rank(f.get("tier")) >= rank("replicated"))}


def made_progress(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return any(set(after[k]) - set(before.get(k) or []) for k in ("done", "decided", "strong"))


def stop_reason(campaign: dict[str, Any], *, max_rounds: int, max_hours: float, max_test_runs: int,
                stagnation: int, ready_tests: int, now: float | None = None) -> str | None:
    """Why the loop stops now, or None to run another round."""
    loop = campaign["loop"]
    now = now or time.time()
    rounds = campaign.get("rounds") or []
    if rounds and rounds[-1].get("concluded"):
        return "concluded"
    if len(rounds) >= max_rounds:
        return "round ceiling"
    # Active running time (paused periods excluded); records from before active-time tracking use their round times.
    active = float(loop.get("active_s") or 0.0) + (now - float(loop["segment_started"]) if loop.get("segment_started") else 0.0)
    if not loop.get("active_s") and not loop.get("segment_started"):
        active = now - float(loop.get("started_at") or now)
    if active > max_hours * 3600:
        return "time ceiling"
    if int(loop.get("test_runs") or 0) >= max_test_runs:
        return "test-run ceiling"
    recent = rounds[-stagnation:]
    if len(rounds) >= stagnation and recent and not any(r.get("progress") for r in recent):
        return "stagnated"
    if ready_tests == 0:
        return "nothing left to run"
    return None


STOP_TEXT = {
    "concluded": "Every deliverable is done or shown infeasible.",
    "stagnated": "Recent rounds made no progress, so the project stopped and reported what it established.",
    "nothing left to run": "Every remaining test is blocked or finished; nothing further could be run.",
    "round ceiling": "The safety ceiling on rounds was reached.",
    "time ceiling": "The safety ceiling on running time was reached.",
    "test-run ceiling": "The safety ceiling on test runs was reached.",
    "stopped by user": "Stopped by the user.",
}

__all__ = ["ANALYSIS_SYSTEM", "JUDGE_SYSTEM", "STOP_TEXT", "apply_judgement", "made_progress", "progress_snapshot",
           "round_context", "stop_reason"]
