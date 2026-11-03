"""
Real roots of a stated one-variable polynomial, computed exactly in Python (SymPy, mpmath) so the answer reports the
code's outputs: the Sturm sequence in rational arithmetic and its sign changes at -inf and +inf (the number of
distinct real roots), disjoint rational isolating intervals of the requested width with the exact sign of p at both
ends, each root to the requested number of significant digits, and the exact residual p(r) at every reported decimal.

The root count is checked a second way (SymPy's count_roots), and every reported decimal must lie inside its
isolating interval.
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp

from .poly_facts import parse_polynomial

_ROOTS_CUE_RE = re.compile(r"\b(?:real\s+)?roots?\b|\bzeros?\b|\bsturm\b|\bisolat\w*", re.I)
MAX_DEGREE = 40


def _width(question: str) -> sp.Rational:
    m = re.search(r"width\s+(?:at\s+most|of\s+at\s+most|<=?|≤|below|under)?\s*10\s*(?:\^|\*\*)?\s*\{?\s*[-−⁻]\s*(\d+)", question)
    if not m:
        m = re.search(r"width[^.\n]{0,30}?10[⁻-]([¹²³⁴⁵⁶⁷⁸⁹⁰]+|\d+)", question)
    if m:
        digits = m.group(1).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        return sp.Rational(1, 10 ** int(digits))
    return sp.Rational(1, 10 ** 10)


def _digits(question: str) -> int:
    m = re.search(r"(\d{1,3})\s+significant\s+digits|(\d{1,3})\s+(?:decimal\s+)?digits", question)
    return int(m.group(1) or m.group(2)) if m else 15


def _truncated(decimal: str, significant: int) -> str:
    """The decimal cut (not rounded) after `significant` significant digits: "0.200064102629975" -> "0.2000641026"."""
    m = re.match(r"(-?)(\d*)\.?(\d*)", decimal)
    sign, whole, frac = m.group(1), m.group(2), m.group(3)
    lead = len(whole + frac) - len((whole + frac).lstrip("0"))  # zeros before the first significant digit
    kept = (whole + frac)[: lead + significant]
    if len(kept) <= len(whole):
        return sign + kept
    return sign + kept[: len(whole)] + "." + kept[len(whole):]


def _sign_changes(signs: list[int]) -> int:
    nz = [s for s in signs if s != 0]
    return sum(1 for a, b in zip(nz, nz[1:], strict=False) if a != b)


def compute_roots_facts(question: str) -> dict[str, Any] | None:
    """The Sturm count, isolating intervals, roots and residuals of a stated real polynomial, or None."""
    parsed = parse_polynomial(question, cue=_ROOTS_CUE_RE)
    if parsed is None:
        return None
    name, syms, expr = parsed
    if len(syms) != 1:
        return None
    x = syms[0]
    poly = sp.Poly(expr, x)
    if not 1 <= poly.degree() <= MAX_DEGREE:
        return None
    digits = max(1, min(_digits(question), 60))
    width = _width(question)

    # Sturm sequence in exact rational arithmetic, and its sign changes at -inf and +inf.
    seq = [sp.Poly(q, x) for q in sp.sturm(poly)]
    at_minus = [int(sp.sign(q.LC())) * (-1 if q.degree() % 2 else 1) for q in seq]
    at_plus = [int(sp.sign(q.LC())) for q in seq]
    v_minus, v_plus = _sign_changes(at_minus), _sign_changes(at_plus)
    count = v_minus - v_plus
    count_check = int(poly.count_roots())  # SymPy's own real-root count, a second method
    squarefree = sp.degree(sp.gcd(poly.as_expr(), poly.diff(x).as_expr()), x) == 0

    # Disjoint rational isolating intervals refined to the requested width, with the exact sign at both ends.
    intervals = poly.intervals(eps=width)
    rows = []
    roots = sorted(sp.real_roots(poly), key=lambda r: float(r))
    for (a, b), mult in intervals:
        a, b = sp.Rational(a), sp.Rational(b)
        pa, pb = poly.eval(a), poly.eval(b)
        root = next((r for r in roots if a <= r <= b), None)
        approx = sp.N(root, digits + 10) if root is not None else None
        decimal = sp.Rational(str(sp.N(approx, digits))) if approx is not None else None
        residual = poly.eval(decimal) if decimal is not None else None
        rows.append({
            "interval": (a, b), "width": b - a, "multiplicity": mult,
            "sign_a": int(sp.sign(pa)), "sign_b": int(sp.sign(pb)),
            "root": str(sp.N(approx, digits)) if approx is not None else "",
            "prefix": _truncated(str(approx), 10) if approx is not None else "",
            "inside": bool(decimal is not None and a <= decimal <= b),
            "residual": residual,
        })
    certified = _certify(poly, rows, digits)
    disjoint = all(r1["interval"][1] < r2["interval"][0] for r1, r2 in zip(rows, rows[1:], strict=False))
    widths_ok = all(r["width"] <= width for r in rows)
    # A rational root comes back as the exact point [r, r] with p(r) = 0: an exact root, no sign change needed.
    sign_change = all(r["sign_a"] * r["sign_b"] < 0 or (r["interval"][0] == r["interval"][1] and r["sign_a"] == 0)
                      for r in rows)

    checks = [
        {"name": f"Sturm count in rational arithmetic: V(-inf) - V(+inf) = {v_minus} - {v_plus} = {count}; SymPy "
                 f"count_roots gives {count_check}", "passed": count == count_check},
        {"name": f"{len(rows)} disjoint rational intervals, each of width at most {width} with p changing sign "
                 "exactly between its ends", "passed": disjoint and widths_ok and sign_change and len(rows) == count},
        {"name": f"every root to {digits} significant digits lies inside its isolating interval",
         "passed": all(r["inside"] for r in rows)},
        {"name": "p and p' are coprime (gcd is constant), so every root is simple", "passed": squarefree},
    ]
    if certified is not None:
        checks.append({
            "name": f"every reported digit certified by ball arithmetic (python-flint/Arb): each decimal is within half a "
                    f"unit of its last digit of a root enclosure of radius at most {certified['max_radius']:.1e}",
            "passed": certified["all_digits_correct"] and certified["real_count"] == count})
    resid = [r["residual"] for r in rows if r["residual"] is not None]
    params = [
        {"name": f"number of distinct real roots of {name}", "value": str(count), "unit": "",
         "aliases": ["how many real roots", "number of real roots", "real roots exist"]},
        {"name": f"real roots of {name} to {digits} significant digits", "value": ", ".join(r["root"] for r in rows),
         "unit": "", "aliases": ["every real root", "real root", "significant digits"],
         # Each root's first 10 significant digits (cut, not rounded, so any longer correct report contains them)
         # must be in the answer for this item to count as delivered.
         "match_all": [r["prefix"] for r in rows]},
        {"name": "largest |p| at the reported decimals (exact)", "value": f"{float(max(abs(v) for v in resid)):.3e}"
         if resid else "", "unit": "", "aliases": ["residual", "residuals"]},
    ]
    return {
        "kind": "polynomial_roots",
        "name": name, "variable": str(x),
        "polynomial_latex": f"{name}({x}) = {sp.latex(poly.as_expr())}",
        "sturm_latex": [sp.latex(q.as_expr()) for q in seq],
        "signs_minus_inf": at_minus, "signs_plus_inf": at_plus,
        "count": count, "digits": digits, "width": str(width),
        "roots": [{"root": r["root"], "a": str(r["interval"][0]), "b": str(r["interval"][1]),
                   "a_decimal": str(sp.N(r["interval"][0], digits + 2)), "b_decimal": str(sp.N(r["interval"][1], digits + 2)),
                   "sign_a": r["sign_a"], "sign_b": r["sign_b"],
                   "residual": f"{float(r['residual']):.3e}" if r["residual"] is not None else ""} for r in rows],
        "parameters": params, "checks": checks,
        "notes": ["The Sturm count and the endpoint signs are exact rational computations, so the count and the "
                  "isolation are proofs; "
                  + ("every reported digit is also proved: each decimal lies within half a unit of its last digit of a "
                     "certified Arb enclosure of the root." if certified and certified["all_digits_correct"] else
                     "the decimals are high-precision evaluations, each shown to lie inside its certified interval.")],
        "certified_roots": certified["balls"] if certified else [],
        "methods": ["SymPy sturm (exact rational arithmetic)", "SymPy count_roots", "SymPy interval isolation",
                    f"mpmath evaluation to {digits + 10} digits", "exact rational residuals",
                    *(["python-flint (Arb) certified root enclosures"] if certified else [])],
        "curve": _curve(poly, rows),
    }


def _certify(poly: sp.Poly, rows: list[dict[str, Any]], digits: int) -> dict[str, Any] | None:
    """Arb ball enclosures of the real roots (python-flint), and whether each reported decimal is correct in every
    digit: |decimal - root| < half a unit of its last digit, bounded with the enclosure's radius. None when
    python-flint is not installed."""
    try:
        import flint
    except ImportError:
        return None
    _, int_poly = poly.clear_denoms()
    coeffs = [int(c) for c in reversed(int_poly.all_coeffs())]
    old_prec = flint.ctx.prec
    flint.ctx.prec = int((digits + 20) * 3.33) + 32
    try:
        balls = [r for r, _m in flint.fmpz_poly(coeffs).complex_roots() if r.imag.contains(0) and r.imag.rad() == 0]
        reals = sorted((b.real for b in balls), key=lambda a: float(a.mid()))
        ok, max_rad, out = True, 0.0, []
        for row, ball in zip(rows, reals, strict=False):
            dec = sp.Rational(row["root"]) if row["root"] else None
            if dec is None or dec == 0:
                ok = False
                continue
            exponent = sp.floor(sp.log(abs(dec), 10))
            half_unit = flint.arb(flint.fmpq(1, 2)) * flint.arb(10) ** int(exponent - (digits - 1))
            gap = abs(flint.arb(flint.fmpq(int(dec.p), int(dec.q))) - ball)
            ok = ok and bool(gap < half_unit)
            max_rad = max(max_rad, float(ball.rad()))
            out.append(ball.str(digits + 5, radius=True))
        return {"all_digits_correct": ok and len(reals) == len(rows), "real_count": len(reals),
                "max_radius": max_rad, "balls": out}
    finally:
        flint.ctx.prec = old_prec


def _curve(poly: sp.Poly, rows: list[dict[str, Any]]) -> dict[str, Any]:
    roots = [float(r["interval"][0]) for r in rows] or [0.0]
    lo, hi = min(roots), max(roots)
    pad = max(0.5, 0.25 * (hi - lo))
    import numpy as np

    t = np.linspace(lo - pad, hi + pad, 241)
    f = sp.lambdify(poly.gens[0], poly.as_expr(), "numpy")
    return {"t": [round(float(v), 5) for v in t], "y": [float(v) for v in f(t)], "roots": roots}


__all__ = ["compute_roots_facts"]
