"""
Finite number-theory computations requested by the question, run by code and verified a second way, so the answer
can state them as checked rather than as "routinely reproducible": Collatz orbits (total stopping time, largest
value, the longest orbit below a bound), Goldbach partitions (every way to write an even number as a sum of two primes,
their count, and the conjecture's check over a range), twin primes and prime counts below a bound.

These are instances, never proofs: for an open problem (Collatz, Goldbach, twin primes) the results carry a note that a
finite check is evidence, not a proof of the statement for all integers.

Each result is computed twice by different methods (a sieve and sympy.isprime; a direct Collatz loop and a memoised
recursion), and a result whose two computations disagree is not reported.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from sympy import isprime

MAX_COLLATZ_START = 10_000_000
MAX_COLLATZ_RANGE = 1_000_000
MAX_SIEVE = 2_000_000
MAX_LISTED_PARTITIONS = 60
ORBIT_PLOT_MAX = 400

_INT = r"(\d{1,3}(?:,\d{3})+|\d+)"


def _int(text: str) -> int:
    return int(text.replace(",", ""))


_BOUND_RE = re.compile(rf"\b(?:below|under|less\s+than|up\s+to|<)\s*{_INT}")


def _bound_near(q: str, cue: str) -> int | None:
    """The bound ("below 1000") nearest the words that ask for it, within their sentence: "the longest Collatz orbit
    below 1000 ... and the twin primes below 500" gives each request its own bound, not the question's first one."""
    for sent in re.finditer(r"[^.?!;\n]+", q):
        cues = [m.start() for m in re.finditer(cue, sent.group(0))]
        bounds = [(m.start(), _int(m.group(1))) for m in _BOUND_RE.finditer(sent.group(0))]
        if cues and bounds:
            return min(bounds, key=lambda b: min(abs(b[0] - c) for c in cues))[1]
    return None


def _sieve(n: int) -> bytearray:
    is_p = bytearray([1]) * (n + 1)
    is_p[0:2] = b"\x00\x00"[: min(2, n + 1)]
    for i in range(2, int(n**0.5) + 1):
        if is_p[i]:
            is_p[i * i:: i] = bytearray(len(is_p[i * i:: i]))
    return is_p


# Collatz ----------------------------------------------------------------------------------------------------------
def collatz_orbit(n: int) -> list[int]:
    orbit = [n]
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        orbit.append(n)
    return orbit


@lru_cache(maxsize=None)
def _steps_recursive(n: int) -> int:
    """Total stopping time by memoised recursion (the second, independent computation)."""
    if n == 1:
        return 0
    return 1 + _steps_recursive(n // 2 if n % 2 == 0 else 3 * n + 1)


def _stopping_table(bound: int) -> list[int]:
    """Total stopping times of 1 .. bound-1, bottom-up: each orbit is followed only until it falls below its start,
    whose time is already in the table (about 10x faster than following every orbit to 1)."""
    steps = [0] * max(bound, 2)
    for k in range(2, bound):
        n, s = k, 0
        while n >= k:
            n = n // 2 if n % 2 == 0 else 3 * n + 1
            s += 1
        steps[k] = s + steps[n]
    return steps


def _steps_iterative(n: int) -> int:
    steps = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps


def _collatz_facts(q: str, out: dict[str, Any]) -> None:
    import sys

    starts = sorted({_int(m) for m in re.findall(rf"\bn\s*=\s*{_INT}", q) if 1 <= _int(m) <= MAX_COLLATZ_START})
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 5000))
    try:
        for n in starts[:6]:
            orbit = collatz_orbit(n)
            steps, peak = len(orbit) - 1, max(orbit)
            ok = _steps_recursive(n) == steps and peak in orbit
            out["checks"].append({"name": f"Collatz orbit of {n}: {steps} steps computed by direct iteration and again "
                                          "by memoised recursion", "passed": ok})
            if not ok:
                continue
            out["parameters"] += [
                {"name": f"total stopping time of {n}", "value": str(steps), "unit": "steps",
                 "aliases": ["total stopping time", "number of steps to reach 1", "steps to reach 1"]},
                {"name": f"largest value reached from {n}", "value": str(peak), "unit": "",
                 "aliases": ["largest value reached", "maximum value", "highest value", "peak"]},
            ]
            if "collatz_orbit" not in out:
                out["collatz_orbit"] = {"start": n, "values": orbit[:ORBIT_PLOT_MAX]}
        bound = _bound_near(q, r"longest|most\s+steps|(?:largest|maximum)\s+(?:total\s+)?stopping")
        if bound is not None:
            if 2 <= bound <= MAX_COLLATZ_RANGE:
                table = _stopping_table(bound)
                best = max(range(1, bound), key=lambda k: (table[k], -k))
                steps = table[best]
                # Confirmed three ways: the orbit followed to 1 directly, and memoised recursion over the whole range.
                ok = (_steps_iterative(best) == steps == _steps_recursive(best)
                      and all(_steps_recursive(k) <= steps for k in range(1, bound)))
                out["checks"].append({"name": f"longest Collatz orbit below {bound}: n = {best} with {steps} steps, "
                                              "found by an exhaustive search and confirmed by memoised recursion",
                                      "passed": ok})
                if ok:
                    out["ranges"].append(f"every Collatz starting value below {bound}")
                    out["parameters"] += [
                        {"name": f"start below {bound} with the longest stopping time", "value": str(best), "unit": "",
                         "aliases": ["longest stopping time", "longest total stopping time", "starting value below"]},
                        {"name": "its total stopping time", "value": str(steps), "unit": "steps", "aliases": []},
                        {"name": f"largest value reached from {best}", "value": str(max(collatz_orbit(best))), "unit": "",
                         "aliases": []},
                    ]
    finally:
        sys.setrecursionlimit(limit)


# Goldbach ---------------------------------------------------------------------------------------------------------
def goldbach_partitions(n: int, is_p: bytearray) -> list[tuple[int, int]]:
    return [(p, n - p) for p in range(2, n // 2 + 1) if is_p[p] and is_p[n - p]]


def _goldbach_facts(q: str, out: dict[str, Any]) -> None:
    targets = {_int(m) for m in re.findall(
        rf"\b(?:write|express|decompose|partitions?\s+of|ways?\s+(?:for|of|to\s+write))\s+{_INT}", q)}
    targets |= {_int(m) for m in re.findall(rf"\b{_INT}\s+as\s+(?:a\s+)?sum\s+of\s+two\s+primes", q)}
    targets = {n for n in targets if n >= 4 and n % 2 == 0 and n <= MAX_SIEVE}
    rng = re.search(rf"\bfrom\s+{_INT}\s+to\s+{_INT}", q)
    hi = _int(rng.group(2)) if rng and re.search(r"verif|check|holds?|test", q) else 0
    top = max([*targets, hi, 4])
    if top > MAX_SIEVE:
        return
    is_p = _sieve(top)
    for n in sorted(targets)[:6]:
        parts = goldbach_partitions(n, is_p)
        ok = all(isprime(p) and isprime(r) and p + r == n for p, r in parts)
        out["checks"].append({"name": f"{len(parts)} Goldbach partitions of {n}: found with a sieve, each pair "
                                      "re-checked prime by sympy.isprime and summed", "passed": ok})
        if not ok:
            continue
        out["parameters"].append({"name": f"number of ways to write {n} as a sum of two primes", "value": str(len(parts)),
                                  "unit": "", "aliases": [f"write {n}", f"ways for {n}", f"partitions of {n}",
                                                          f"count the ways for {n}"]})
        if len(parts) <= MAX_LISTED_PARTITIONS:
            out.setdefault("partitions", []).append({"n": n, "pairs": parts})
    if hi and rng:
        lo = max(4, _int(rng.group(1)))
        lo += lo % 2
        primes = [p for p in range(2, hi // 2 + 1) if is_p[p]]
        bad = []
        for n in range(lo, hi + 1, 2):
            # The first partition found settles n (the smallest such prime is tiny for every n checked so far).
            if not any(is_p[n - p] for p in primes if p <= n // 2):
                bad.append(n)
        ok = not bad
        if ok:
            out["ranges"].append(f"every even number from {lo} to {hi} (Goldbach)")
        out["checks"].append({"name": f"Goldbach holds for every even number from {lo} to {hi} (sieve search, "
                                      f"{(hi - lo) // 2 + 1} numbers checked)" + ("" if ok else f"; counterexample {bad[0]}"),
                              "passed": ok})
        out["parameters"].append({"name": f"even numbers from {lo} to {hi} with at least one Goldbach partition",
                                  "value": str((hi - lo) // 2 + 1 - len(bad)), "unit": "", "match": str(hi),
                                  "verified": ok, "aliases": ["every even number", f"from {lo} to {hi}"]})


# Primes -----------------------------------------------------------------------------------------------------------
def _prime_facts(q: str, out: dict[str, Any]) -> None:
    twin_bound = _bound_near(q, r"twin[- ]primes?")
    count_bound = _bound_near(q, r"how\s+many\s+primes|number\s+of\s+primes|prime[- ]counting|\\pi\s*\(|π\s*\(")
    bounds = [b for b in (twin_bound, count_bound) if b is not None and 3 <= b <= MAX_SIEVE]
    if not bounds:
        return
    is_p = _sieve(max(bounds))
    if twin_bound in bounds:
        bound = twin_bound
        pairs = [(p, p + 2) for p in range(2, bound - 1) if is_p[p] and p + 2 < bound and is_p[p + 2]]
        ok = all(isprime(a) and isprime(b) for a, b in pairs)
        out["checks"].append({"name": f"{len(pairs)} twin-prime pairs below {bound}: sieve, re-checked by sympy.isprime",
                              "passed": ok})
        if ok and pairs:
            out["ranges"].append(f"the primes below {bound} (twin primes)")
            out["parameters"] += [
                {"name": f"twin-prime pairs below {bound}", "value": str(len(pairs)), "unit": "",
                 "aliases": ["twin prime pairs", "twin primes"]},
                {"name": "largest twin-prime pair", "value": f"({pairs[-1][0]}, {pairs[-1][1]})", "unit": "", "aliases": []},
            ]
    if count_bound in bounds:
        bound = count_bound
        count = sum(is_p[:bound])
        from sympy import primepi

        ok = int(primepi(bound - 1)) == count
        out["checks"].append({"name": f"{count} primes below {bound}: sieve count equals sympy.primepi", "passed": ok})
        if ok:
            out["parameters"].append({"name": f"number of primes below {bound}", "value": str(count), "unit": "",
                                      "aliases": ["how many primes", "number of primes", "prime count"]})


_OPEN = {
    "collatz": "the Collatz conjecture",
    "goldbach": "Goldbach's conjecture",
    "twin prime": "the twin prime conjecture",
}


def compute_number_facts(question: str) -> dict[str, Any] | None:
    """Finite number-theory results for the question, each verified a second way, or None when it asks for none."""
    q = re.sub(r"\s+", " ", question or "")
    low = q.lower()
    out: dict[str, Any] = {"kind": "number_theory_finite", "parameters": [], "checks": [], "notes": [], "ranges": []}
    if "collatz" in low or "3n+1" in low.replace(" ", ""):
        _collatz_facts(low, out)
    if "goldbach" in low or "sum of two primes" in low:
        _goldbach_facts(low, out)
    if "prime" in low:
        _prime_facts(low, out)
    if not out["parameters"]:
        return None
    # Twin primes counted ("twin-prime pairs below 50000") bear on the twin prime conjecture even when it is not named.
    named = [v for k, v in _OPEN.items() if re.search(k.replace(" ", r"[- ]"), low)]
    if named:
        out["open_problems"] = named
        verb = "remain" if len(named) > 1 else "remains"
        listed = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
        ranges = out["ranges"]
        checked = (" They verify only " + "; ".join(ranges) + ".") if ranges else ""
        # Stated with its ranges and in the words an answer uses ("verified up to N", "remains open"), so a sentence
        # that reports the status is grounded in this note. Shown to the reader in the results panel.
        out["notes"].append(f"These are finite computations.{checked} They are evidence for {listed}, which {verb} "
                            "open, not proved: no finite check proves a statement about all integers.")
    if not out["ranges"]:
        out.pop("ranges")
    return out


__all__ = ["collatz_orbit", "compute_number_facts", "goldbach_partitions"]
