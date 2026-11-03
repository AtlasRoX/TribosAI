"""
Real polynomials the question asks about (nonnegativity, minimum, equality cases, sums of squares), analysed by
Python code so the answer reports what the code computed, not a description of what it would compute:

- grid sampling of the polynomial over a box (NumPy) and multi-start local minimisation (SciPy BFGS);
- every minimiser found is made exact (SymPy nsimplify) and checked exactly: the value and the gradient there;
- the half Newton polytope of the polynomial and its lattice points, and the "diagonal-only" test: a monomial of the
  polynomial with a negative coefficient whose exponent arises only as beta + beta from the half polytope cannot appear
  with that sign in a sum of squares (its coefficient there is a sum of squares of Gram-diagonal entries), which proves
  the polynomial is not a sum of squares of polynomials. When no such monomial exists the test is inconclusive and
  the result says so.

Sampling and minimisation are evidence, never a proof of nonnegativity; the result says that too.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

import numpy as np
import sympy as sp

GRID_RADIUS = 3.0
GRID_POINTS_2D = 801
GRID_POINTS_3D = 121
STARTS = 160

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_CUE_RE = re.compile(r"non-?negativ|≥\s*0|>=\s*0|\bpositive\s+semi|sum\s+of\s+squares|\bSOS\b|global\s+min|minim(?:um|is|iz)",
                     re.I)
_DEF_RE = re.compile(r"\b([A-Za-z])\s*\(\s*([a-z](?:\s*,\s*[a-z]){0,2})\s*\)\s*=\s*([^=\n]+?)(?:[.;](?:\s|$)|\n|$)")


def _normalise(text: str) -> str:
    out = []
    for ch in text or "":
        if ch in "⁰¹²³⁴⁵⁶⁷⁸⁹":
            # a run of superscript digits becomes one ^(...) exponent
            if out and out[-1].startswith("^("):
                out[-1] = out[-1][:-1] + ch.translate(_SUPERSCRIPTS) + ")"
            else:
                out.append("^(" + ch.translate(_SUPERSCRIPTS) + ")")
        else:
            out.append(ch)
    return ("".join(out).replace("−", "-").replace("–", "-").replace("·", "*").replace("×", "*")
            .replace(">=", "≥").replace("<=", "≤"))  # "M(x,y) = ... >= 0": the "=" of >= is not the definition's


def parse_polynomial(question: str, cue: re.Pattern[str] | None = None) -> tuple[str, list[sp.Symbol], sp.Expr] | None:
    """(name, variables, polynomial) for "M(x,y) = x^4y^2 + ..." in a question about nonnegativity or squares (or
    about what `cue` matches)."""
    q = _normalise(question)
    if not (cue or _CUE_RE).search(q):
        return None
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    for m in _DEF_RE.finditer(q):
        name, args, body = m.group(1), [a.strip() for a in m.group(2).split(",")], m.group(3).strip()
        # The formula ends where the sentence goes on in words ("... + 1 nonnegative, and is it ...").
        body = re.split(r",|\s*[<>≤≥]|\s+(?=(?:[A-Za-z]{4,}|and|for|with|is|on|has|at|to|in|of|as|by|be|are|its)\b)",
                        body)[0].strip()
        if not re.search(r"[a-z]", body) or re.search(r"[\\{}]|\b(?:sin|cos|exp|log|sqrt)\b", body):
            continue
        syms = [sp.Symbol(a, real=True) for a in args]
        try:
            expr = parse_expr(body, local_dict=dict(zip(args, syms, strict=True)),
                              transformations=standard_transformations + (implicit_multiplication_application, convert_xor))
        except Exception:  # noqa: BLE001 - not a polynomial the parser reads
            continue
        if not expr.free_symbols or not expr.free_symbols <= set(syms):
            continue
        try:
            poly = sp.Poly(sp.expand(expr), *syms)
        except sp.PolynomialError:
            continue
        if poly.total_degree() < 2 or any(not c.is_Rational for c in poly.coeffs()):
            continue
        return name, syms, sp.expand(expr)
    return None


def _half_polytope_points(exponents: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
    """Lattice points of half the Newton polytope (the convex hull of the exponents, halved)."""
    pts = np.array(exponents, float) / 2.0
    dim = pts.shape[1]
    hi = np.floor(pts.max(axis=0)).astype(int)
    lo = np.ceil(pts.min(axis=0)).astype(int)
    candidates = list(itertools.product(*[range(a, b + 1) for a, b in zip(lo, hi, strict=True)]))
    if dim == 1:
        return [c for c in candidates if pts.min() - 1e-9 <= c[0] <= pts.max() + 1e-9]
    from scipy.optimize import linprog

    out = []
    for c in candidates:
        # c in conv(pts)  <=>  lambda >= 0, sum lambda = 1, pts^T lambda = c is feasible
        a_eq = np.vstack([pts.T, np.ones(len(pts))])
        b_eq = np.concatenate([np.array(c, float), [1.0]])
        res = linprog(np.zeros(len(pts)), A_eq=a_eq, b_eq=b_eq, bounds=[(0, None)] * len(pts), method="highs")
        if res.status == 0:
            out.append(tuple(int(v) for v in c))
    return sorted(out)


def sos_certificate(expr: sp.Expr, syms: list[sp.Symbol], half: list[tuple[int, ...]]) -> dict[str, Any] | None:
    """An exact sum-of-squares decomposition p = sum_k d_k (l_k . z)^2 with rational d_k >= 0, or None.

    Peyrl & Parrilo's route: solve the Gram-matrix SDP numerically (cvxpy) over the half-Newton-polytope monomials z,
    pushed into the interior of the PSD cone; round the Gram matrix to rationals; project it exactly onto the
    coefficient constraints (each entry belongs to exactly one monomial, so the projection spreads each residual
    evenly over that monomial's entries); prove it PSD with an exact rational LDL^T; and check the identity in SymPy.
    """
    try:
        import cvxpy as cp
    except ImportError:
        return None
    poly = sp.Poly(expr, *syms)
    coeffs = dict(poly.terms())
    basis = list(half)
    n = len(basis)
    if n == 0 or n > 30:
        return None
    by_gamma: dict[tuple[int, ...], list[tuple[int, int]]] = {}
    for i in range(n):
        for j in range(n):
            gamma = tuple(a + b for a, b in zip(basis[i], basis[j], strict=True))
            by_gamma.setdefault(gamma, []).append((i, j))
    if any(g not in by_gamma for g in coeffs):
        return None  # a monomial of p that no product of basis monomials reaches
    gram = cp.Variable((n, n), symmetric=True)
    margin = cp.Variable()
    cons = [gram - margin * np.eye(n) >> 0]
    for gamma, cells in by_gamma.items():
        cons.append(sum(gram[i, j] for i, j in cells) == float(coeffs.get(gamma, 0)))
    try:
        cp.Problem(cp.Maximize(margin), cons + [margin <= 1]).solve(solver="CLARABEL")
    except Exception:  # noqa: BLE001 - a solver failure leaves the question undecided, never a wrong certificate
        return None
    if gram.value is None or margin.value is None or margin.value < -1e-7:
        return None
    zvec = [sp.Mul(*[s ** e for s, e in zip(syms, b, strict=True)]) for b in basis]
    for denominator in (10 ** 2, 10 ** 4, 10 ** 6, 10 ** 8):
        q = sp.Matrix(n, n, lambda i, j, d=denominator: sp.Rational(round(float(gram.value[i, j]) * d), d))
        q = (q + q.T) / 2
        for gamma, cells in by_gamma.items():
            residual = sp.Rational(coeffs.get(gamma, 0)) - sum(q[i, j] for i, j in cells)
            if residual:
                share = residual / len(cells)
                for i, j in cells:
                    q[i, j] += share
        ldl = _exact_ldl(q)
        if ldl is None:
            continue
        lower, diag = ldl
        terms = [(diag[k], sum(lower[i, k] * zvec[i] for i in range(n))) for k in range(n) if diag[k] != 0]
        if sp.expand(expr - sum(d * lin ** 2 for d, lin in terms)) == 0:
            return {
                "terms": [(sp.sstr(d), sp.sstr(sp.expand(lin))) for d, lin in terms],
                "latex": " + ".join(f"{sp.latex(d)}\\left({sp.latex(sp.expand(lin))}\\right)^2" for d, lin in terms),
                "basis": [sp.sstr(z) for z in zvec], "denominator": denominator,
            }
    return None


def _exact_ldl(q: sp.Matrix) -> tuple[sp.Matrix, list[sp.Rational]] | None:
    """Exact rational LDL^T of a symmetric matrix, or None when it is not positive semidefinite."""
    n = q.rows
    a = q.copy()
    lower = sp.eye(n)
    diag: list[sp.Rational] = []
    for k in range(n):
        pivot = a[k, k]
        if pivot < 0:
            return None
        if pivot == 0:
            if any(a[i, k] != 0 for i in range(k + 1, n)):
                return None  # a zero pivot with a nonzero column: not PSD
            diag.append(sp.Integer(0))
            continue
        diag.append(pivot)
        for i in range(k + 1, n):
            lower[i, k] = a[i, k] / pivot
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                a[i, j] -= lower[i, k] * pivot * lower[j, k]
    return lower, diag


def _monomial_tex(exp: tuple[int, ...], syms: list[sp.Symbol]) -> str:
    parts = [f"{s}^{{{e}}}" if e > 1 else str(s) for s, e in zip(syms, exp, strict=True) if e]
    return " ".join(parts) or "1"


def compute_poly_facts(question: str) -> dict[str, Any] | None:
    """Sampling, minimisation, exact checks and the Newton-polytope test for a stated real polynomial, or None."""
    parsed = parse_polynomial(question)
    if parsed is None:
        return None
    name, syms, expr = parsed
    n = len(syms)
    if n > 3:
        return None
    f = sp.lambdify(syms, expr, "numpy")
    grad = [sp.diff(expr, s) for s in syms]
    g = sp.lambdify(syms, grad, "numpy")
    args = ", ".join(map(str, syms))

    # Grid sampling.
    k = GRID_POINTS_2D if n <= 2 else GRID_POINTS_3D
    axes = [np.linspace(-GRID_RADIUS, GRID_RADIUS, k) for _ in range(n)]
    mesh = np.meshgrid(*axes, indexing="ij")
    values = np.asarray(f(*mesh), float) * np.ones_like(mesh[0])
    i_min = np.unravel_index(int(np.argmin(values)), values.shape)
    grid_min = float(values[i_min])
    grid_at = [float(axes[d][i_min[d]]) for d in range(n)]

    # Multi-start minimisation.
    from scipy.optimize import minimize

    rng = np.random.default_rng(0)
    starts = rng.uniform(-GRID_RADIUS, GRID_RADIUS, size=(STARTS, n))
    found: list[tuple[float, np.ndarray]] = []
    for x0 in starts:
        res = minimize(lambda v: float(f(*v)), x0, jac=lambda v: np.asarray(g(*v), float), method="BFGS",
                       options={"gtol": 1e-12, "maxiter": 2000})
        found.append((float(res.fun), res.x))
    best = min(v for v, _ in found)
    near = [x for v, x in found if v <= best + 1e-8]
    minimisers: list[np.ndarray] = []
    for x in near:
        if all(np.linalg.norm(x - y) > 1e-4 for y in minimisers):
            minimisers.append(x)

    # Exact checks of the minimisers (rounded to simple numbers, then evaluated exactly).
    exact_points = []
    for x in minimisers[:12]:
        cand = tuple(sp.nsimplify(round(float(c), 6), rational=True, tolerance=1e-5) for c in x)
        value = sp.simplify(expr.subs(dict(zip(syms, cand, strict=True))))
        grad_zero = all(sp.simplify(gi.subs(dict(zip(syms, cand, strict=True)))) == 0 for gi in grad)
        exact_points.append({"point": "(" + ", ".join(sp.sstr(c) for c in cand) + ")", "value": sp.sstr(value),
                             "gradient_zero": grad_zero})
    exact_points.sort(key=lambda p: p["point"])
    zero_points = [p for p in exact_points if p["value"] == "0"]

    # Newton polytope and the diagonal-only test.
    poly = sp.Poly(expr, *syms)
    terms = dict(poly.terms())
    exponents = list(terms)
    half = _half_polytope_points(exponents)
    certificate = None
    for gamma, coeff in sorted(terms.items()):
        if coeff >= 0:
            continue
        pairs = [(a, b) for a in half for b in half if tuple(x + y for x, y in zip(a, b, strict=True)) == gamma]
        if pairs and all(a == b for a, b in pairs):
            beta = pairs[0][0]
            certificate = {
                "monomial": _monomial_tex(gamma, syms), "coefficient": sp.sstr(coeff),
                "only_from": _monomial_tex(beta, syms),
                "text": (f"In any sum of squares sum_i f_i^2 with every f_i supported on the half Newton polytope, the "
                         f"monomial {sp.sstr(sp.Mul(*[s ** e for s, e in zip(syms, gamma, strict=True)]))} arises only "
                         f"as ({sp.sstr(sp.Mul(*[s ** e for s, e in zip(syms, beta, strict=True)]))})^2, so its "
                         f"coefficient is a sum of squares, >= 0; in {name} it is {sp.sstr(coeff)}."),
            }
            break
    # No Newton-polytope obstruction: look for an exact certificate that p IS a sum of squares (SDP, rational rounding).
    decomposition = None if certificate else sos_certificate(expr, syms, half)
    sos = ("not a sum of squares (Newton-polytope certificate)" if certificate
           else "a sum of squares (exact rational certificate)" if decomposition
           else "not decided (no Newton-polytope obstruction, no exact certificate found)")

    nonneg_evidence = grid_min >= -1e-9 and best >= -1e-9
    checks = [
        {"name": f"grid sampling of {name} over [-{GRID_RADIUS:g}, {GRID_RADIUS:g}]^{n} ({k}^{n} points, NumPy): smallest "
                 f"value {grid_min:.3g} at ({', '.join(f'{c:.3g}' for c in grid_at)})", "passed": grid_min >= -1e-9},
        {"name": f"multi-start minimisation ({STARTS} BFGS starts, SciPy): lowest value {best:.3g}, at "
                 f"{len(minimisers)} distinct point(s)", "passed": best >= -1e-9},
    ]
    if zero_points:
        # Only exact zeros are checked exactly: a positive minimum at an irrational point has no exact rational image.
        checks.append({"name": f"exact evaluation (SymPy) at the equality points: {name} = 0 at {len(zero_points)} "
                                f"point(s), gradient zero at {sum(p['gradient_zero'] for p in zero_points)} of "
                                f"{len(zero_points)}",
                       "passed": all(p["gradient_zero"] for p in zero_points)})
    if decomposition:
        checks.append({"name": f"exact sum-of-squares certificate: {len(decomposition['terms'])} squares with rational "
                                f"weights, Gram matrix proved PSD by exact LDL^T and {name} - sum = 0 checked in SymPy",
                       "passed": True})
    if certificate:
        checks.append({"name": f"Newton-polytope certificate: {certificate['monomial']} has coefficient "
                                f"{certificate['coefficient']} but arises only as ({certificate['only_from']})^2",
                       "passed": True})

    lowest = min(best, grid_min)
    shown = "0" if zero_points and abs(lowest) < 1e-12 else f"{lowest:.6g}"  # 0 exactly at the checked points
    params = [
        {"name": f"smallest value of {name} found (sampling and minimisation)", "value": shown,
         "unit": "", "aliases": ["minimum", "global minimum", "smallest value"]},
        {"name": "points where the minimum is attained (exact)", "value": ", ".join(p["point"] for p in exact_points[:8])
         or "none found", "unit": "", "aliases": ["equality case", "equality cases", "minimizers", "minimisers"]},
        {"name": "number of equality points found", "value": str(len(zero_points)), "unit": "",
         "aliases": ["equality points"]},
        {"name": "lattice points of the half Newton polytope", "value": ", ".join(str(p) for p in half), "unit": "",
         "aliases": ["half newton polytope", "newton polytope"]},
        {"name": "sum-of-squares test", "value": sos, "unit": "", "aliases": ["sum of squares", "sos"]},
    ]
    if decomposition:
        params.append({"name": "sum-of-squares decomposition", "value": f"{len(decomposition['terms'])} weighted squares",
                       "unit": "", "aliases": ["decomposition", "sum of squares decomposition", "the decomposition"],
                       # delivered when the answer writes out at least two squared terms
                       "match_regex": r"\)\s*\^\s*\{?\s*2[\s\S]{0,600}?\)\s*\^\s*\{?\s*2"})
    notes = ["Sampling and minimisation show the polynomial's values at finitely many points: evidence for "
             "nonnegativity, not a proof of it."]
    if certificate:
        notes.append("The Newton-polytope certificate is a proof: " + certificate["text"])
    if decomposition:
        notes.append(f"The decomposition {name} = sum of {len(decomposition['terms'])} weighted squares is exact (rational "
                     "weights, identity checked symbolically), so it proves nonnegativity outright.")

    slice_chart = None
    if n == 2:
        t = np.linspace(-1.8, 1.8, 241)
        slice_chart = {"t": [round(float(v), 4) for v in t],
                       "diagonal": [float(v) for v in np.asarray(f(t, t), float)],
                       "label": f"{name}(t, t)"}
    return {
        "kind": "polynomial_analysis",
        "name": name, "variables": [str(s) for s in syms],
        "polynomial_latex": f"{name}({args}) = {sp.latex(expr)}",
        "parameters": params, "checks": checks, "notes": notes,
        "minimisers": exact_points, "half_polytope": [list(p) for p in half],
        "exponents": [list(e) for e in exponents], "certificate": certificate, "sos_decomposition": decomposition,
        "nonnegativity_evidence": nonneg_evidence, "slice": slice_chart,
        "methods": ["NumPy grid sampling", "SciPy BFGS multi-start minimisation", "SymPy exact evaluation",
                    "SciPy linear programming for the half Newton polytope",
                    *(["cvxpy (Clarabel) Gram-matrix SDP with exact rational rounding"] if decomposition else [])],
    }


__all__ = ["compute_poly_facts", "parse_polynomial"]
