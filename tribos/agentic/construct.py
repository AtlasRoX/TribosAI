"""
Construct mode: evolutionary search for constructions, scored exactly by code (docs/plans/tribos-harness-landscape.md
item 4; the OpenEvolve / ShinkaEvolve / AlphaEvolve pattern).

The model writes Python programs `construct()` that return a candidate object; each program runs in the sandbox
together with the problem's exact scorer, which rejects invalid candidates. A small program database keeps the best
programs; every new program is a mutation of a parent chosen by tournament, shown with two other strong programs as
inspiration. Programs whose normalised source was seen before are not run again (novelty rejection, ShinkaEvolve).
The best candidate is scored a second time, alone, from its JSON, before it is reported.

The problem library holds construction problems with exact scorers and published reference values, so the result
can be compared with what is known. A score above the best known value is reported as a candidate result that needs
independent confirmation, never as a solved problem.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

CODE_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S | re.I)
RUN_TIMEOUT_S = 30.0
BATCH = 2  # programs written and scored concurrently per generation


@dataclass(frozen=True)
class Problem:
    key: str
    title: str
    statement: str  # what the program must return, for the model
    scorer: str  # Python source defining score(c) -> (valid: bool, value: float, note: str)
    seed: str  # a simple valid program to start from
    direction: str  # "max" | "min" (of the reported value)
    known_best: float | None
    known_note: str
    params: dict[str, Any] = field(default_factory=dict)


# Optimal Golomb ruler lengths (exhaustively verified; distributed.net OGR project): marks -> length.
GOLOMB_OPTIMAL = {2: 1, 3: 3, 4: 6, 5: 11, 6: 17, 7: 25, 8: 34, 9: 44, 10: 55, 11: 72, 12: 85, 13: 106, 14: 127}
# Largest cap sets in F_3^n (n <= 6: Pellegrino 1970 for n = 4, Edel et al. for n = 5, Potechin 2008 for n = 6).
CAP_SET_MAX = {1: 2, 2: 4, 3: 9, 4: 20, 5: 45, 6: 112}


def golomb(marks: int) -> Problem:
    return Problem(
        key=f"golomb_{marks}", title=f"Golomb ruler with {marks} marks",
        statement=(f"Return a list of {marks} distinct non-negative integers starting at 0 such that all pairwise "
                   "differences are distinct (a Golomb ruler). Shorter is better: the value is the largest mark."),
        scorer=f"""
def score(c):
    m = sorted(int(x) for x in c)
    if len(m) != {marks} or len(set(m)) != {marks} or m[0] != 0:
        return False, 0, "need {marks} distinct marks starting at 0"
    d = [b - a for i, a in enumerate(m) for b in m[i + 1:]]
    if len(d) != len(set(d)):
        return False, 0, "repeated difference"
    return True, m[-1], "valid Golomb ruler"
""",
        seed=f"""
def construct():
    # greedy: add the smallest mark that keeps all differences distinct
    marks, diffs, x = [0], set(), 0
    while len(marks) < {marks}:
        x += 1
        new = {{x - m for m in marks}}
        if not new & diffs and len(new) == len(marks):
            diffs |= new
            marks.append(x)
    return marks
""",
        direction="min", known_best=GOLOMB_OPTIMAL.get(marks),
        known_note="optimal length, proved by exhaustive search" if marks in GOLOMB_OPTIMAL else "",
        params={"marks": marks})


def cap_set(n: int) -> Problem:
    return Problem(
        key=f"cap_set_{n}", title=f"Cap set in F_3^{n}",
        statement=(f"Return a list of vectors of length {n} with entries in {{0, 1, 2}} such that no three distinct "
                   "vectors x, y, z satisfy x + y + z = 0 (mod 3) coordinatewise (no three on a line). Larger is better."),
        scorer=f"""
def score(c):
    pts = [tuple(int(v) % 3 for v in p) for p in c]
    if any(len(p) != {n} for p in pts) or len(set(pts)) != len(pts):
        return False, 0, "vectors must be distinct and of length {n}"
    s = set(pts)
    for i, x in enumerate(pts):
        for y in pts[i + 1:]:
            z = tuple((-a - b) % 3 for a, b in zip(x, y))
            if z != x and z != y and z in s:
                return False, 0, "three points on a line"
    return True, len(pts), "valid cap set"
""",
        seed=f"""
import itertools
def construct():
    # greedy over the space in a fixed order
    chosen, s = [], set()
    for p in itertools.product(range(3), repeat={n}):
        if all(tuple((-a - b) % 3 for a, b in zip(p, q)) not in s or tuple((-a - b) % 3 for a, b in zip(p, q)) in (p, q)
               for q in chosen):
            chosen.append(p)
            s.add(p)
    return chosen
""",
        direction="max", known_best=CAP_SET_MAX.get(n),
        known_note="largest possible (proved)" if n in CAP_SET_MAX else "", params={"n": n})


def no_three_in_line(n: int) -> Problem:
    return Problem(
        key=f"no_three_{n}", title=f"No-three-in-line on the {n}×{n} grid",
        statement=(f"Return a list of points (x, y) with 0 <= x, y < {n} such that no three are collinear. Larger is "
                   f"better; at most 2·{n} = {2 * n} points are possible."),
        scorer=f"""
def score(c):
    pts = [(int(p[0]), int(p[1])) for p in c]
    if len(set(pts)) != len(pts) or any(not (0 <= x < {n} and 0 <= y < {n}) for x, y in pts):
        return False, 0, "points must be distinct and on the grid"
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            for k in range(j + 1, len(pts)):
                (a, b), (c2, d), (e, f) = pts[i], pts[j], pts[k]
                if (c2 - a) * (f - b) == (d - b) * (e - a):
                    return False, 0, "three collinear points"
    return True, len(pts), "valid"
""",
        seed=f"""
def construct():
    pts = []
    for x in range({n}):
        for y in range({n}):
            p = (x, y)
            if all((q[0] - p[0]) * (r[1] - p[1]) != (q[1] - p[1]) * (r[0] - p[0])
                   for i, q in enumerate(pts) for r in pts[i + 1:]):
                pts.append(p)
    return pts
""",
        direction="max", known_best=2 * n if n <= 46 else None,
        known_note="2n is the upper bound and is attained for every n <= 46" if n <= 46 else "", params={"n": n})


def sidon(limit: int) -> Problem:
    import math

    bound = math.sqrt(limit) + limit ** 0.25 + 1
    return Problem(
        key=f"sidon_{limit}", title=f"Sidon set in {{1, …, {limit}}}",
        statement=(f"Return a list of distinct integers in 1..{limit} whose pairwise sums a + b (a <= b) are all "
                   "distinct (a Sidon set). Larger is better."),
        scorer=f"""
def score(c):
    a = sorted(int(x) for x in c)
    if len(set(a)) != len(a) or any(x < 1 or x > {limit} for x in a):
        return False, 0, "distinct integers in 1..{limit}"
    sums = [x + y for i, x in enumerate(a) for y in a[i:]]
    if len(sums) != len(set(sums)):
        return False, 0, "repeated sum"
    return True, len(a), "valid Sidon set"
""",
        seed=f"""
def construct():
    a, sums = [], set()
    for x in range(1, {limit} + 1):
        new = {{x + y for y in a}} | {{2 * x}}
        if not new & sums and len(new) == len(a) + 1:
            sums |= new
            a.append(x)
    return a
""",
        direction="max", known_best=None,
        known_note=f"upper bound sqrt(N) + N^(1/4) + 1 = {bound:.1f} (Erdős–Turán, Lindström)", params={"N": limit})


_DETECTORS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], Problem | None]]] = [
    (re.compile(r"golomb\s+rulers?\D{0,40}?(\d{1,2})\s*(?:marks|-mark|marks?)|(\d{1,2})[- ]mark\s+golomb", re.I),
     lambda m: golomb(int(m.group(1) or m.group(2))) if 3 <= int(m.group(1) or m.group(2)) <= 20 else None),
    (re.compile(r"cap\s*sets?\D{0,40}?(?:F_?3\^?\{?|dimension\s*|n\s*=\s*)(\d)", re.I),
     lambda m: cap_set(int(m.group(1))) if 1 <= int(m.group(1)) <= 7 else None),
    (re.compile(r"no[- ]three[- ]in[- ](?:a[- ])?line\D{0,40}?(\d{1,2})\s*(?:x|×|by)\s*\d{1,2}", re.I),
     lambda m: no_three_in_line(int(m.group(1))) if 3 <= int(m.group(1)) <= 30 else None),
    (re.compile(r"(?:sidon|B_?2)\s+sets?\D{0,40}?(?:1\s*(?:,|\.\.|…|to)\s*(?:\.\.\.\s*,?\s*)?|\[1\s*,\s*|N\s*=\s*)(\d{2,4})",
                re.I),
     lambda m: sidon(int(m.group(1))) if 10 <= int(m.group(1)) <= 2000 else None),
]


def detect_problem(question: str) -> Problem | None:
    for rx, build in _DETECTORS:
        m = rx.search(question or "")
        if m:
            problem = build(m)
            if problem is not None:
                return problem
    return None


def _normalise(code: str) -> str:
    code = re.sub(r"#[^\n]*", "", code)
    return hashlib.sha256(re.sub(r"\s+", "", code).encode()).hexdigest()


_HARNESS = """
import json
{scorer}
{program}
_c = construct()
_c = [list(x) if isinstance(x, (tuple, list)) else x for x in _c]
_ok, _v, _note = score(_c)
print("__RESULT__" + json.dumps({{"valid": bool(_ok), "value": _v, "note": _note, "candidate": _c}}))
"""


def evaluate(problem: Problem, program: str, timeout_s: float = RUN_TIMEOUT_S) -> dict[str, Any]:
    """Run a program with the scorer in the sandbox: {valid, value, note, candidate} or {valid: False, error}."""
    from .sandbox.gateway import execute

    report = execute(_HARNESS.format(scorer=problem.scorer, program=program), timeout_s=timeout_s)
    out = str(report.get("stdout") or "")
    if report.get("status") != "ok" or "__RESULT__" not in out:
        err = str(report.get("error") or report.get("stderr") or report.get("status") or "no result")
        return {"valid": False, "value": None, "error": err[-800:]}
    try:
        return json.loads(out.split("__RESULT__", 1)[1].strip().splitlines()[0])
    except (ValueError, IndexError) as exc:
        return {"valid": False, "value": None, "error": f"unreadable result: {exc}"}


def rescore(problem: Problem, candidate: Any) -> dict[str, Any]:
    """The candidate scored again, alone, from its JSON: no program code involved."""
    program = f"import json\ndef construct():\n    return json.loads({json.dumps(json.dumps(candidate))})\n"
    return evaluate(problem, program)


@dataclass
class Entry:
    program: str
    valid: bool
    value: float | None
    note: str = ""
    candidate: Any = None
    origin: str = "seed"


def _fitness(problem: Problem, e: Entry) -> float:
    if not e.valid or e.value is None:
        return float("-inf")
    return float(e.value) if problem.direction == "max" else -float(e.value)


_SYSTEM = """You improve programs for a mathematical construction problem, as in AlphaEvolve. Reply with brief reasoning and exactly ONE ```python``` block that defines construct() returning the candidate. Standard library and numpy only, deterministic (seed any randomness), finishing within 20 seconds. The candidate is checked exactly by the scorer shown; an invalid candidate scores nothing. Aim to beat the parent; try a genuinely different idea (algebraic constructions, known families, local search with restarts) rather than small edits when the parent has stalled."""


def _prompt(problem: Problem, parent: Entry, inspirations: list[Entry], best: Entry) -> str:
    def show(e: Entry) -> str:
        status = f"value {e.value}" if e.valid else f"invalid ({e.note[:200]})"
        return f"```python\n{e.program.strip()[:3000]}\n```\nResult: {status}"

    lines = [f"Problem: {problem.statement}", f"Objective: {'maximise' if problem.direction == 'max' else 'minimise'} "
             f"the value.", f"Scorer:\n```python\n{problem.scorer.strip()}\n```",
             f"Best value so far: {best.value}.", "Parent program to improve:", show(parent)]
    if inspirations:
        lines.append("Other strong programs:")
        lines += [show(e) for e in inspirations]
    return "\n\n".join(lines)


async def search(problem: Problem, ask: Callable[[str, str], Awaitable[str]], *, candidates: int = 10,
                 on_progress: Callable[[int, Entry, Entry], Awaitable[None]] | None = None,
                 seed: int = 0) -> dict[str, Any]:
    """Evolve programs for `problem`; `ask(system, prompt)` returns the model's reply."""
    rng = random.Random(seed)
    first = await asyncio.to_thread(evaluate, problem, problem.seed)
    db = [Entry(problem.seed, bool(first.get("valid")), first.get("value"), first.get("note") or first.get("error", ""),
                first.get("candidate"), "seed")]
    seen = {_normalise(problem.seed)}
    history = [{"program": 0, "best": db[0].value, "value": db[0].value, "valid": db[0].valid}]
    rejected = 0

    def best() -> Entry:
        return max(db, key=lambda e: _fitness(problem, e))

    async def one() -> Entry | None:
        nonlocal rejected
        ranked = sorted(db, key=lambda e: _fitness(problem, e), reverse=True)
        pool = ranked[: max(3, len(ranked) // 2)]
        parent = max(rng.sample(pool, min(2, len(pool))), key=lambda e: _fitness(problem, e))  # tournament of two
        inspirations = [e for e in ranked[:3] if e is not parent][:2]
        reply = await ask(_SYSTEM, _prompt(problem, parent, inspirations, best()))
        m = CODE_RE.search(reply)
        if m is None or "def construct" not in m.group(1):
            return None
        program = m.group(1)
        key = _normalise(program)
        if key in seen:
            rejected += 1
            return None
        seen.add(key)
        r = await asyncio.to_thread(evaluate, problem, program)
        return Entry(program, bool(r.get("valid")), r.get("value"), r.get("note") or r.get("error", ""),
                     r.get("candidate"), "mutation")

    written = 0
    while written < candidates:
        batch = min(BATCH, candidates - written)
        results = await asyncio.gather(*(one() for _ in range(batch)), return_exceptions=True)
        written += batch
        for r in results:
            if isinstance(r, Entry):
                db.append(r)
                history.append({"program": len(history), "best": best().value, "value": r.value, "valid": r.valid})
                if on_progress is not None:
                    await on_progress(written, r, best())
    top = best()
    confirm = await asyncio.to_thread(rescore, problem, top.candidate) if top.valid else {"valid": False}
    return {"problem": problem, "best": top, "history": history, "programs": len(db), "valid_programs":
            sum(1 for e in db if e.valid), "rejected_duplicates": rejected, "confirmed": bool(confirm.get("valid"))
            and confirm.get("value") == top.value, "seed_value": db[0].value}


def comparison(problem: Problem, value: float | None) -> str:
    if value is None or problem.known_best is None:
        return "no published optimum to compare with" + (f" ({problem.known_note})" if problem.known_note else "")
    better = value > problem.known_best if problem.direction == "max" else value < problem.known_best
    if value == problem.known_best:
        return f"matches the best known value {problem.known_best:g} ({problem.known_note})"
    if better:
        return (f"beats the best known value {problem.known_best:g}: a candidate new result that needs independent "
                f"confirmation (the scorer, the reference value and the literature) before any claim")
    return f"short of the best known value {problem.known_best:g} ({problem.known_note})"


def facts(result: dict[str, Any]) -> dict[str, Any]:
    """The construct-mode result as computed facts (kind construction_search) for the panel and the evidence."""
    problem: Problem = result["problem"]
    top: Entry = result["best"]
    verdict = comparison(problem, top.value if top.valid else None)
    checks = [
        {"name": "best candidate re-scored alone from its JSON by the exact scorer", "passed": bool(result["confirmed"])},
        {"name": "the seed program produced a valid candidate", "passed": result["seed_value"] is not None},
    ]
    params = [
        {"name": "best value found", "value": str(top.value if top.valid else "none"), "unit": "", "verified":
         bool(result["confirmed"]), "aliases": ["best", "found", "value"]},
        {"name": "best known value", "value": str(problem.known_best if problem.known_best is not None else "unknown"),
         "unit": "", "aliases": ["known", "record", "optimum"]},
        {"name": "comparison", "value": verdict, "unit": "", "aliases": ["compare", "beats", "matches"]},
        {"name": "programs evaluated", "value": str(result["programs"]), "unit": "", "aliases": ["programs"]},
        {"name": "starting value (greedy seed)", "value": str(result["seed_value"]), "unit": "", "aliases": ["seed"]},
    ]
    return {
        "kind": "construction_search", "problem": problem.title, "statement": problem.statement,
        "direction": problem.direction, "parameters": params, "checks": checks, "history": result["history"],
        "best_program": top.program, "candidate": top.candidate, "verdict": verdict,
        "known_note": problem.known_note, "rejected_duplicates": result["rejected_duplicates"],
        "methods": ["model-written programs evolved by tournament selection with novelty rejection",
                    "exact scorer run in the sandbox for every program", "independent re-scoring of the best candidate"],
        "notes": ["A value found by search is a construction, checked exactly; it says nothing about optimality "
                  "unless it reaches a proved upper bound."],
    }


__all__ = ["Problem", "comparison", "detect_problem", "evaluate", "facts", "rescore", "search"]
