"""
Statistics for the paired benchmark comparison (Tribos against the same model answering alone). Standard library
only, so the report needs nothing beyond the eval harness.

- wilson: the Wilson score interval for a binomial proportion (Wilson 1927; Newcombe 1998). It keeps close to its
  nominal coverage at small n and at 0% or 100%, where the Wald interval collapses to a point.
- mcnemar_exact: the exact McNemar test, a two-sided binomial test of the discordant pairs (b, c) against p = 1/2.
  Only the pairs where exactly one system is right carry information about which system is better.
- paired_diff_ci: an interval for the paired difference of two proportions, the adjusted Wald interval of
  Agresti and Min (2005), which adds half a count to each cell of the 2x2 table before the Wald formula.
- percentile: linear interpolation between order statistics (numpy's default "linear" method).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from typing import Any

Z95 = 1.959963984540054  # two-sided 95% normal quantile


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """The Wilson score interval for k successes in n trials; None when n is 0."""
    if n <= 0:
        return None
    if not 0 <= k <= n:
        raise ValueError(f"wilson: need 0 <= k <= n, got k={k}, n={n}")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, center - half)
    hi = 1.0 if k == n else min(1.0, center + half)
    return lo, hi


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: P(X <= min(b, c)) doubled, X ~ Binomial(b + c, 1/2), capped at 1.
    With no discordant pairs there is no evidence either way and p is 1."""
    if b < 0 or c < 0:
        raise ValueError("mcnemar_exact: counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def paired_diff_ci(both: int, only_first: int, only_second: int, neither: int, z: float = Z95) -> tuple[float, float] | None:
    """95% interval for p_first - p_second on paired binary outcomes (Agresti-Min adjusted Wald); None when n is 0.
    The point estimate it is reported with stays the unadjusted (only_first - only_second) / n."""
    n = both + only_first + only_second + neither
    if n <= 0:
        return None
    n_adj = n + 2.0
    p12 = (only_first + 0.5) / n_adj
    p21 = (only_second + 0.5) / n_adj
    diff = p12 - p21
    se = math.sqrt(max(0.0, p12 + p21 - diff * diff) / n_adj)
    return max(-1.0, diff - z * se), min(1.0, diff + z * se)


def percentile(values: Iterable[float], q: float) -> float | None:
    """The q-quantile (0 <= q <= 1) by linear interpolation between order statistics; None for no values."""
    s = sorted(float(v) for v in values)
    if not s:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("percentile: q must be in [0, 1]")
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def numbers(values: Iterable[Any]) -> list[float]:
    """The real numbers among values (None, booleans and non-numbers dropped)."""
    return [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))]


def mean_or_none(values: Iterable[Any]) -> float | None:
    vals = numbers(values)
    return statistics.fmean(vals) if vals else None


def proportion(k: int, n: int) -> dict[str, Any]:
    """{k, n, rate, ci95} for k of n; rate and ci95 are None when n is 0."""
    ci = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": list(ci) if ci else None}


def paired_summary(outcomes: Sequence[tuple[bool, bool]]) -> dict[str, Any]:
    """The 2x2 table of (first correct, second correct) pairs, the difference first - second with its interval,
    and the exact McNemar p-value."""
    a = sum(1 for x, y in outcomes if x and y)
    b = sum(1 for x, y in outcomes if x and not y)
    c = sum(1 for x, y in outcomes if y and not x)
    d = sum(1 for x, y in outcomes if not x and not y)
    n = a + b + c + d
    ci = paired_diff_ci(a, b, c, d)
    return {
        "n": n, "both_right": a, "only_first": b, "only_second": c, "both_wrong": d,
        "difference": (b - c) / n if n else None,
        "difference_ci95": list(ci) if ci else None,
        "mcnemar_p": mcnemar_exact(b, c) if n else None,
    }


__all__ = ["Z95", "mcnemar_exact", "mean_or_none", "numbers", "paired_diff_ci", "paired_summary", "percentile", "proportion",
           "wilson"]
