"""
The research charter: what the goal asks for (deliverables), what is claimed (hypotheses), and how each is settled
(tests, a dependency graph). One model call proposes it; the code below decides what is accepted.

Validation rules (deterministic, after the model):
- Every numbered part of the goal ("(1) ...", "2. ...") is a deliverable, whether or not the model listed it.
- Ids are renumbered D1.., H1.., T1..; references to unknown ids are dropped; a dependency cycle is broken.
- Every deliverable is served by at least one test; an unserved one gets a compute test of its own.
- Caps: 12 deliverables, 8 hypotheses, 24 tests per charter (40 in all after revisions).
"""

from __future__ import annotations

import re
from typing import Any

KINDS = ("compute", "prove", "simulate", "literature", "estimate")
TIERS = ("formal", "certified", "replicated", "computed", "sourced", "reasoned")
COSTS = ("s", "m", "l")
MAX_DELIVERABLES = 12
MAX_HYPOTHESES = 8
MAX_TESTS = 24
MAX_TESTS_TOTAL = 40
_NUM_RE = re.compile(r"(?:^|\s)\((\d{1,2})\)\s+|(?:^|\n)\s*(\d{1,2})[.)]\s+")

CHARTER_SYSTEM = """You plan a research project the way a careful scientist writes a pre-registered study plan.

Given the research goal and the literature review, reply with ONE JSON object:
{
 "summary": "one paragraph: the question and how the project will settle it",
 "deliverables": [{"id": "D1", "title": "...", "acceptance": "what exactly must be produced for this to count as done", "tier": "computed|replicated|certified|formal|sourced|reasoned"}],
 "hypotheses": [{"id": "H1", "statement": "a specific, testable claim", "falsification": "the result that would refute it"}],
 "tests": [{"id": "T1", "title": "short name", "kind": "compute|prove|simulate|literature|estimate",
            "objective": "precisely what to compute, prove or find (inputs, ranges, parameters)",
            "method": "the algorithm or proof strategy", "acceptance": "what output settles it",
            "quantities": ["names of the values the test must report, snake_case"],
            "serves": ["D1"], "hypotheses": ["H1"], "depends_on": [], "cost": "s|m|l", "tier": "computed|replicated|certified|formal|sourced|reasoned"}]
}

Rules:
- One deliverable per thing the goal asks for, in the goal's order; keep the goal's numbers and ranges exactly.
- Tests must be executable now: a compute test is Python (numpy, scipy, sympy, mpmath, networkx, statsmodels, matplotlib) in a sandbox with no network, a few minutes per cell; a prove test is a precise mathematical statement to prove (formally in Lean 4 with Mathlib when possible); a literature test is a specific fact to find in published sources.
- Prefer exact arithmetic for integers and rationals. Numeric deliverables should be "replicated" (a separately written re-implementation with a different algorithm must agree). "certified" is reached only by exact integer results that the re-implementation reproduces exactly, so ask for it only when every quantity is an integer. Use "formal" only for statements small enough to prove in Lean.
- The project ends in a thesis with a chapter of theorems and proofs. For a mathematical goal, plan 1 to 3 "prove" tests for the statements the conclusions rely on and that can actually be proved: lemmas about the objects defined (e.g. a recurrence such as s(2n) = s(n) + 1), derivations of the constants used (e.g. a heuristic constant from its model), identities or bounds the computation assumes. State each as a precise, self-contained mathematical statement. Never plan a proof of an open problem.
- Split big work into tests that can run in parallel; use depends_on only when a test needs another test's numbers.
- Never plan a test for something the goal does not ask for. Never claim an open problem will be solved: plan what can be established and state the rest as limits.
- Reply with the JSON object only."""


def goal_items(goal: str) -> list[str]:
    """The numbered parts of a goal, in order ([] when it has fewer than two)."""
    text = goal or ""
    marks = [(m.start(), m.end(), int(m.group(1) or m.group(2))) for m in _NUM_RE.finditer(text)]
    if len(marks) < 2 or [n for *_, n in marks] != list(range(marks[0][2], marks[0][2] + len(marks))):
        return []
    items = []
    for i, (_, end, _) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        items.append(re.sub(r"\s+", " ", text[end:stop]).strip().rstrip(";,"))
    return [s for s in items if s]


def _ids(prefix: str, items: list[dict[str, Any]], key: str = "id") -> dict[str, str]:
    """Old id -> new id (D1, D2, ...)."""
    out: dict[str, str] = {}
    for i, it in enumerate(items, 1):
        old = str(it.get(key) or f"{prefix}{i}")
        out.setdefault(old, f"{prefix}{i}")
    return out


def _clean(text: Any, limit: int = 1200) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= limit:
        return t
    cut = t[: limit - 1]
    return (cut[: cut.rfind(" ")] if cut.rfind(" ") > limit // 2 else cut).rstrip(" ,;:") + "…"



def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", (text or "").lower()))


def _break_cycles(tests: list[dict[str, Any]]) -> None:
    """Drop dependency edges that close a cycle (keeps the earliest edges)."""
    order = {t["id"]: i for i, t in enumerate(tests)}
    graph: dict[str, list[str]] = {t["id"]: [] for t in tests}
    for t in tests:
        kept = []
        for d in t["depends_on"]:
            graph[t["id"]].append(d)
            if _reaches(graph, d, t["id"]):
                graph[t["id"]].pop()
            else:
                kept.append(d)
        t["depends_on"] = sorted(kept, key=lambda d: order.get(d, 0))


def _reaches(graph: dict[str, list[str]], start: str, target: str) -> bool:
    seen, stack = set(), [start]
    while stack:
        n = stack.pop()
        if n == target:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(graph.get(n, []))
    return False


def normalise_test(raw: dict[str, Any], new_id: str, *, d_ids: set[str], h_ids: set[str],
                   round_added: int) -> dict[str, Any]:
    kind = str(raw.get("kind") or "compute").lower()
    kind = kind if kind in KINDS else "compute"
    tier = str(raw.get("tier") or "").lower()
    if tier not in TIERS:
        tier = {"prove": "formal", "literature": "sourced"}.get(kind, "replicated")
    cost = str(raw.get("cost") or "m").lower()
    quantities = [re.sub(r"[^a-z0-9_]+", "_", str(q).lower()).strip("_")[:60]
                  for q in (raw.get("quantities") or []) if str(q).strip()][:24]
    return {
        "id": new_id, "title": _clean(raw.get("title") or raw.get("objective"), 120) or new_id, "kind": kind,
        "objective": _clean(raw.get("objective") or raw.get("title"), 2000), "method": _clean(raw.get("method"), 1200),
        "acceptance": _clean(raw.get("acceptance"), 600), "quantities": [q for q in quantities if q],
        "serves": [d for d in (raw.get("serves") or []) if d in d_ids],
        "hypotheses": [h for h in (raw.get("hypotheses") or []) if h in h_ids],
        "depends_on": list(raw.get("depends_on") or []), "cost": cost if cost in COSTS else "m", "tier": tier,
        "status": "pending", "attempts": 0, "round_added": round_added, "last_error": None, "finding_ids": [],
    }


def _match_required_tiers(tests: list[dict[str, Any]], deliverables: list[dict[str, Any]]) -> None:
    """A computation serving a deliverable that must be replicated is itself run with an independent
    re-implementation: otherwise it could never settle that deliverable, and a round would be spent finding out."""
    need = {d["id"]: d.get("tier") for d in deliverables}
    for t in tests:
        if t["kind"] in ("compute", "simulate", "estimate") and t["tier"] in ("computed", "reasoned"):
            if any(need.get(d) in ("replicated", "certified") for d in t["serves"]):
                t["tier"] = "replicated"


def validate_charter(raw: Any, goal: str) -> dict[str, Any]:
    """The accepted charter from the model's proposal (see the module docstring)."""
    raw = raw if isinstance(raw, dict) else {}
    deliverables = [d for d in (raw.get("deliverables") or []) if isinstance(d, dict)][:MAX_DELIVERABLES]
    # Every numbered part of the goal is a deliverable: added when no proposed deliverable covers its words.
    for part in goal_items(goal):
        pw = _words(part)
        if not any(len(pw & _words(str(d.get("title")) + " " + str(d.get("acceptance")))) >= max(2, len(pw) // 3)
                   for d in deliverables):
            deliverables.append({"id": f"G{len(deliverables) + 1}", "title": part, "acceptance": part,
                                 "tier": "replicated"})
    if not deliverables:
        deliverables = [{"id": "D1", "title": _clean(goal, 160), "acceptance": _clean(goal, 600), "tier": "replicated"}]
    deliverables = deliverables[:MAX_DELIVERABLES]
    d_map = _ids("D", deliverables)
    hyps = [h for h in (raw.get("hypotheses") or []) if isinstance(h, dict)][:MAX_HYPOTHESES]
    h_map = _ids("H", hyps)
    tests_raw = [t for t in (raw.get("tests") or []) if isinstance(t, dict)][:MAX_TESTS]
    t_map = _ids("T", tests_raw)
    out_d: list[dict[str, Any]]
    out_h: list[dict[str, Any]]
    out_d = [{"id": d_map[str(d.get("id") or f"D{i}")], "title": _clean(d.get("title"), 200) or f"Deliverable {i}",
              "acceptance": _clean(d.get("acceptance") or d.get("title"), 800),
              "tier": (str(d.get("tier") or "").lower() if str(d.get("tier") or "").lower() in TIERS else "replicated"),
              "status": "open", "evidence": [], "note": ""}
             for i, d in enumerate(deliverables, 1)]
    out_h = [{"id": h_map[str(h.get("id") or f"H{i}")], "statement": _clean(h.get("statement"), 800),
              "falsification": _clean(h.get("falsification"), 600), "verdict": "untested", "evidence": [], "note": ""}
             for i, h in enumerate(hyps, 1) if _clean(h.get("statement"))]
    d_ids, h_ids = {d["id"] for d in out_d}, {h["id"] for h in out_h}
    tests = []
    for i, t in enumerate(tests_raw, 1):
        tid = t_map[str(t.get("id") or f"T{i}")]
        t = dict(t)
        t["serves"] = [d_map.get(str(x), "") for x in (t.get("serves") or [])]
        t["hypotheses"] = [h_map.get(str(x), "") for x in (t.get("hypotheses") or [])]
        t["depends_on"] = [t_map.get(str(x), "") for x in (t.get("depends_on") or [])]
        tests.append(normalise_test(t, tid, d_ids=d_ids, h_ids=h_ids, round_added=1))
    known = {t["id"] for t in tests}
    for t in tests:
        t["depends_on"] = [d for d in t["depends_on"] if d in known and d != t["id"]]
    _break_cycles(tests)
    _match_required_tiers(tests, out_d)
    served = {d for t in tests for d in t["serves"]}
    for d in out_d:
        if d["id"] not in served:
            tid = f"T{len(tests) + 1}"
            tests.append(normalise_test({"title": d["title"], "kind": "compute", "objective": d["acceptance"],
                                         "acceptance": d["acceptance"], "serves": [d["id"]], "tier": d["tier"]},
                                        tid, d_ids=d_ids, h_ids=h_ids, round_added=1))
    return {"summary": _clean(raw.get("summary"), 2000), "deliverables": out_d, "hypotheses": out_h, "tests": tests,
            "revisions": [{"round": 1, "added": [t["id"] for t in tests], "reason": "initial plan"}]}


def add_tests(charter: dict[str, Any], proposed: list[Any], round_no: int, reason: str) -> list[str]:
    """Append validated new tests (from the judge or a follow-up instruction); returns their ids."""
    tests = charter["tests"]
    room = MAX_TESTS_TOTAL - len(tests)
    d_ids = {d["id"] for d in charter["deliverables"]}
    h_ids = {h["id"] for h in charter["hypotheses"]}
    known = {t["id"] for t in tests}
    titles = {t["title"].lower() for t in tests}
    added = []
    for raw in [p for p in proposed if isinstance(p, dict)][:max(0, room)]:
        if _clean(raw.get("title")).lower() in titles and not raw.get("retry_of"):
            continue
        tid = f"T{len(tests) + 1}"
        t = normalise_test(raw, tid, d_ids=d_ids, h_ids=h_ids, round_added=round_no)
        t["depends_on"] = [d for d in t["depends_on"] if d in known]
        if not t["serves"] and not t["hypotheses"]:
            continue  # a test that settles nothing the goal asks for
        _match_required_tiers([t], charter["deliverables"])
        tests.append(t)
        known.add(tid)
        titles.add(t["title"].lower())
        added.append(tid)
    if added:
        charter["revisions"].append({"round": round_no, "added": added, "reason": _clean(reason, 400)})
    return added


def charter_text(charter: dict[str, Any], *, with_tests: bool = True) -> str:
    """The charter as plain text for prompts."""
    lines = ["Deliverables:"]
    lines += [f"- {d['id']} [{d.get('status', 'open')}] {d['title']} — done when: {d['acceptance']}" for d in charter["deliverables"]]
    if charter["hypotheses"]:
        lines.append("Hypotheses:")
        lines += [f"- {h['id']} [{h.get('verdict', 'untested')}] {h['statement']} (refuted if: {h['falsification']})"
                  for h in charter["hypotheses"]]
    if with_tests:
        lines.append("Tests:")
        lines += [f"- {t['id']} ({t['kind']}, {t['status']}, serves {','.join(t['serves']) or '-'}) {t['title']}: "
                  f"{t['objective'][:300]}" for t in charter["tests"]]
    return "\n".join(lines)


__all__ = ["CHARTER_SYSTEM", "KINDS", "TIERS", "add_tests", "charter_text", "goal_items", "validate_charter"]
