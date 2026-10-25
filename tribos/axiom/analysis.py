"""
Axiom analysis tools: optimization, inequalities, tangent lines, vector calculus, integral transforms and numerical
quadrature.

Same contract as engine.py: safe parsing (no eval of arbitrary code), a canonical id, and a `verified` flag that is
only True when a second, independent method agrees with the result (dense sampling, finite differences, a numerical
transform integral, a second quadrature rule). Each `check_*` function re-derives that check from the original
problem's inputs, so the verifier can call it with the problem statement instead of the tool's own arguments.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

import mpmath
import sympy as sp

from .engine import _canonical_id, _check_safe_string, _num, _quad, safe_parse_expr

_REL_RE = re.compile(r"(<=|>=|!=|≤|≥|≠|<|>)")
_REL = {"<": sp.StrictLessThan, ">": sp.StrictGreaterThan, "<=": sp.LessThan, ">=": sp.GreaterThan, "≤": sp.LessThan,
        "≥": sp.GreaterThan, "!=": sp.Ne, "≠": sp.Ne}


def _real_var(name: str) -> sp.Symbol:
    return sp.Symbol(_check_safe_string(name), real=True)


def _parse_in(expression: str, var: sp.Symbol) -> sp.Expr:
    expr = safe_parse_expr(expression, local_dict={var.name: var})
    extra = expr.free_symbols - {var}
    if extra:
        raise ValueError(f"Give numeric values for the parameters {sorted(str(s) for s in extra)}.")
    return expr


def _bound(text: str | float | None, default: sp.Expr) -> sp.Expr:
    if text is None or str(text).strip() == "":
        return default
    return safe_parse_expr(str(text))


def _f(expr: sp.Expr, var: sp.Symbol, x: sp.Expr | float) -> complex | None:
    return _num(expr, {var: x})


def _sample_points(lo: sp.Expr, hi: sp.Expr, n: int = 2001) -> list[sp.Rational]:
    """Grid over [lo, hi]; infinite ends are reached through x = tan(u)."""
    if lo.is_finite and hi.is_finite:
        a, b = float(lo), float(hi)
        return [sp.Rational(str(a + (b - a) * i / (n - 1))) for i in range(n)]
    ua = -math.pi / 2 + 1e-6 if not lo.is_finite else math.atan(float(lo))
    ub = math.pi / 2 - 1e-6 if not hi.is_finite else math.atan(float(hi))
    return [sp.Rational(str(round(math.tan(ua + (ub - ua) * i / (n - 1)), 9))) for i in range(n)]


# Optimization -------------------------------------------------------------------------------------------------------

def axiom_optimize(
    expression: str,
    variable: str = "x",
    lower: str | None = None,
    upper: str | None = None,
    lower_open: bool = False,
    upper_open: bool = False,
) -> dict[str, Any]:
    """Global maximum and minimum of f(x) on an interval: critical points (f' = 0 or undefined), endpoints and the
    limits at open / infinite ends and at poles, each classified; checked by dense sampling of f."""
    x = _real_var(variable)
    f = _parse_in(expression, x)
    lo, hi = _bound(lower, -sp.oo), _bound(upper, sp.oo)
    if (lo >= hi) is sp.true:
        raise ValueError("The interval needs lower < upper.")
    domain = sp.Interval(lo, hi, lower_open or not lo.is_finite, upper_open or not hi.is_finite)
    df = sp.diff(f, x)
    crit_set = sp.solveset(df, x, domain)
    complete = isinstance(crit_set, sp.FiniteSet) or crit_set is sp.S.EmptySet
    crit = sorted(crit_set, key=lambda v: float(v.evalf())) if complete else []
    if not complete:  # no closed form for f' = 0: locate its zeros numerically
        from .engine import axiom_nsolve

        a = float(lo) if lo.is_finite else -50.0
        b = float(hi) if hi.is_finite else 50.0
        crit = [sp.Float(r, 15) for r in axiom_nsolve(f"{df}", variable, a, b, 4000)["roots"]]
    singular = [s for s in sp.singularities(df, x, domain) if _f(f, x, s) is not None] if hasattr(sp, "singularities") else []
    poles = list(sp.singularities(f, x, domain)) if hasattr(sp, "singularities") else []

    def classify(c: sp.Expr) -> str:
        d2 = sp.diff(f, x, 2).subs(x, c)
        v = _num(d2, {})
        if v is None or abs(v) < 1e-12:
            left, right = _f(df, x, c - sp.Rational(1, 10**6)), _f(df, x, c + sp.Rational(1, 10**6))
            if left is not None and right is not None:
                if left.real > 0 > right.real:
                    return "local maximum"
                if left.real < 0 < right.real:
                    return "local minimum"
            return "stationary (neither)"
        return "local minimum" if v.real > 0 else "local maximum"

    candidates: list[tuple[sp.Expr, sp.Expr, bool, str]] = []  # (x, value, attained, kind)
    for c in crit:
        candidates.append((c, sp.simplify(f.subs(x, c)), True, classify(c)))
    for s in singular:
        candidates.append((s, sp.simplify(f.subs(x, s)), True, "non-differentiable point"))
    for end, is_open, side in ((lo, domain.left_open, "+"), (hi, domain.right_open, "-")):
        if end.is_finite and not is_open:
            candidates.append((end, sp.simplify(f.subs(x, end)), True, "endpoint"))
        else:
            lim = sp.limit(f, x, end, dir=side) if end.is_finite else sp.limit(f, x, end)
            candidates.append((end, lim, False, "limit at the boundary"))
    for p in poles:
        for side in ("+", "-"):
            candidates.append((p, sp.limit(f, x, p, dir=side), False, "limit at a pole"))

    def extreme(sign: int) -> dict[str, Any]:
        # is_extended_real, not is_real: sympy's oo is not "real", and an infinite boundary limit means unbounded
        vals = [(c, v, att, kind) for c, v, att, kind in candidates if v.is_extended_real is not False and not v.has(sp.AccumBounds, sp.nan, sp.zoo)]
        if not vals:
            return {"value": None, "at": [], "attained": False}
        blowups = [c for c, v, _, _ in vals if v == sign * sp.oo]
        if blowups:
            return {"value": str(sign * sp.oo), "at": [], "attained": False, "unbounded": True, "approached_at": [str(c) for c in blowups]}
        best = max(vals, key=lambda t: sign * float(t[1].evalf()))
        bv = float(best[1].evalf())
        ats = [c for c, v, att, _ in vals if att and abs(float(v.evalf()) - bv) <= 1e-12 * max(1.0, abs(bv))]
        attained = bool(ats)
        return {"value": str(best[1]), "numeric": bv, "at": [str(a) for a in dict.fromkeys(ats)], "attained": attained}

    maximum, minimum = extreme(1), extreme(-1)
    verified = check_optimize(f, x, domain, maximum, minimum)
    cid = _canonical_id("axiom_optimize", {"f": expression, "domain": str(domain), "max": maximum.get("value"), "min": minimum.get("value")})
    return {
        "expression": str(f),
        "variable": variable,
        "interval": str(domain),
        "maximum": maximum,
        "minimum": minimum,
        "critical_points": [{"x": str(c), "value": str(v), "type": kind} for c, v, _, kind in candidates if kind not in ("endpoint", "limit at the boundary", "limit at a pole")],
        "critical_points_exact": complete,
        "verified": verified,
        "verification": "dense sampling of f over the interval agrees with the extrema" if verified else "sampling disagrees or could not run",
        "canonical_id": cid,
    }


def check_optimize(f: sp.Expr, x: sp.Symbol, domain: sp.Interval, maximum: dict[str, Any], minimum: dict[str, Any]) -> bool:
    """Independent check: sample f densely; no sample may beat a claimed extremum, and a claimed attained extremum
    must equal f at its argument. Unbounded claims are checked by growth of the samples near the boundary."""
    pts = _sample_points(domain.start, domain.end)
    vals = [v.real for v in (_f(f, x, p) for p in pts) if v is not None and abs(v.imag) < 1e-9]
    if len(vals) < 50:
        return False
    for ext, sign in ((maximum, 1), (minimum, -1)):
        if ext.get("value") is None:
            return False
        if ext.get("unbounded"):
            # Approach each claimed blow-up point from inside the interval: sign * f must grow past 1e6.
            for where in ext.get("approached_at") or []:
                c = safe_parse_expr(where)
                if c in (sp.oo, -sp.oo):
                    seq = [sp.Integer(int(math.copysign(10**k, float(c == sp.oo) - 0.5))) for k in (3, 6, 9)]
                else:
                    inside = 1 if (domain.contains(c + sp.Rational(1, 10**9)) is sp.true) else -1
                    seq = [c + inside * sp.Rational(1, 10**k) for k in (3, 6, 9)]
                got = [_f(f, x, p) for p in seq]
                if any(g is None for g in got):
                    return False
                reals = [sign * g.real for g in got]  # type: ignore[union-attr]
                if not (reals[-1] > 1e6 and reals[0] < reals[1] < reals[2]):
                    return False
            continue
        claimed = float(ext["numeric"])
        tol = 1e-7 * max(1.0, abs(claimed))
        if any(sign * (v - claimed) > tol for v in vals):
            return False
        for a in ext.get("at") or []:
            v = _f(f, x, safe_parse_expr(a))
            if v is None or abs(v.real - claimed) > tol:
                return False
    return True


# Inequalities -------------------------------------------------------------------------------------------------------

def parse_inequality(text: str, var_name: str | None = None) -> tuple[sp.Basic, sp.Symbol]:
    cleaned = _check_safe_string(text)
    parts = _REL_RE.split(cleaned)
    if len(parts) != 3:
        raise ValueError("Give one inequality 'lhs < rhs' (operators <, >, <=, >=, !=).")
    probe = safe_parse_expr(parts[0]) - safe_parse_expr(parts[2])
    names = sorted(s.name for s in probe.free_symbols)
    name = var_name or (names[0] if len(names) == 1 else None)
    if name is None:
        raise ValueError(f"Specify the variable: the inequality has free symbols {names}.")
    x = _real_var(name)
    lhs, rhs = _parse_in(parts[0], x), _parse_in(parts[2], x)
    return _REL[parts[1]](lhs, rhs), x


def axiom_inequality(inequality: str, variable: str | None = None) -> dict[str, Any]:
    """Real solution set of a univariate inequality as intervals, checked by sampling points inside and outside."""
    rel, x = parse_inequality(inequality, variable)
    sol = sp.solveset(rel, x, sp.S.Reals)
    if isinstance(sol, sp.ConditionSet):
        raise ValueError("NotImplementedError: no exact method for this inequality")
    intervals = []
    for piece in (sol.args if isinstance(sol, sp.Union) else (sol,)):
        if isinstance(piece, sp.Interval):
            intervals.append({"lower": str(piece.start), "upper": str(piece.end), "lower_closed": not piece.left_open, "upper_closed": not piece.right_open})
        elif isinstance(piece, sp.FiniteSet):
            intervals.extend({"lower": str(p), "upper": str(p), "lower_closed": True, "upper_closed": True} for p in piece)
    verified = check_inequality(rel, x, sol)
    return {
        "inequality": str(rel),
        "variable": x.name,
        "solution_set": str(sol),
        "intervals": intervals,
        "latex": sp.latex(sol),
        "verified": verified,
        "verification": "membership agrees with the inequality at sampled points" if verified else "sampling disagrees",
        "canonical_id": _canonical_id("axiom_inequality", {"rel": str(rel), "sol": str(sol)}),
    }


def check_inequality(rel: sp.Basic, x: sp.Symbol, sol: sp.Set) -> bool:
    """Sample a grid plus points just around every boundary; set membership must match the inequality's truth."""
    bounds = [float(b) for b in sol.boundary if b.is_finite] if sol is not sp.S.EmptySet else []
    pts = [sp.Rational(str(round(-50 + i * 0.37, 4))) for i in range(271)]
    for b in bounds:
        pts += [sp.Rational(str(b)) + d for d in (sp.Rational(-1, 10**5), sp.Rational(1, 10**5))]
    checked = 0
    for p in pts:
        lhs, rhs = _num(rel.lhs.subs(x, p), {}), _num(rel.rhs.subs(x, p), {})
        if lhs is None or rhs is None or abs(lhs.imag) > 1e-12 or abs(rhs.imag) > 1e-12:
            continue
        holds = bool(rel.func(sp.Float(lhs.real, 30), sp.Float(rhs.real, 30)))
        if holds != bool(sol.contains(p)):
            return False
        checked += 1
    return checked >= 50


# Tangent line -------------------------------------------------------------------------------------------------------

def axiom_tangent(expression: str, point: str, variable: str = "x") -> dict[str, Any]:
    """Value, slope f'(a), tangent line and normal line of y = f(x) at x = a; slope checked by mpmath.diff."""
    x = _real_var(variable)
    f = _parse_in(expression, x)
    a = safe_parse_expr(str(point))
    fa, slope = sp.simplify(f.subs(x, a)), sp.simplify(sp.diff(f, x).subs(x, a))
    if fa.has(sp.zoo, sp.nan) or slope.has(sp.zoo, sp.nan):
        raise ValueError(f"f or f' is undefined at {variable} = {a}.")
    tangent = sp.expand(fa + slope * (x - a))
    normal = sp.expand(fa - (x - a) / slope) if slope != 0 else None
    verified = check_tangent(f, x, a, slope)
    return {
        "expression": str(f),
        "point": str(a),
        "value": str(fa),
        "slope": str(slope),
        "tangent_line": f"y = {tangent}",
        "normal_line": f"y = {normal}" if normal is not None else f"{variable} = {a}",
        "latex": f"y = {sp.latex(tangent)}",
        "verified": verified,
        "verification": "slope matches the numerical derivative" if verified else "numerical derivative disagrees",
        "canonical_id": _canonical_id("axiom_tangent", {"f": expression, "a": str(a), "slope": str(slope)}),
    }


def check_tangent(f: sp.Expr, x: sp.Symbol, a: sp.Expr, slope: sp.Expr) -> bool:
    try:
        f_mp = sp.lambdify(x, f, modules="mpmath")
        with mpmath.workdps(40):
            num = complex(mpmath.diff(f_mp, mpmath.mpf(str(sp.N(a, 40)))))
    except Exception:
        return False
    s = _num(slope, {})
    return s is not None and abs(num - s) <= 1e-8 * max(1.0, abs(s))


# Vector calculus ----------------------------------------------------------------------------------------------------

VectorOp = Literal["gradient", "divergence", "curl", "laplacian", "hessian", "jacobian"]


def axiom_vector_calculus(
    operation: VectorOp,
    expression: str | None = None,
    components: list[str] | None = None,
    variables: list[str] | None = None,
) -> dict[str, Any]:
    """Gradient / Laplacian / Hessian of a scalar field, divergence / curl / Jacobian of a vector field, in Cartesian
    coordinates; every partial derivative is checked by finite differences at sample points."""
    names = list(variables or ["x", "y", "z"])
    syms = [sp.Symbol(_check_safe_string(n)) for n in names]
    local = {s.name: s for s in syms}
    op = str(operation).lower()
    if op in ("gradient", "laplacian", "hessian"):
        if not expression:
            raise ValueError(f"{op} needs a scalar 'expression'.")
        phi = safe_parse_expr(expression, local_dict=local)
        if op == "gradient":
            res: Any = sp.Matrix([sp.diff(phi, s) for s in syms])
        elif op == "laplacian":
            res = sp.simplify(sum(sp.diff(phi, s, 2) for s in syms))
        else:
            res = sp.hessian(phi, syms)
        field_in: Any = phi
    else:
        if not components:
            raise ValueError(f"{op} needs the vector field 'components'.")
        F = [safe_parse_expr(c, local_dict=local) for c in components]
        if op == "divergence":
            if len(F) != len(syms):
                raise ValueError("divergence needs as many components as variables.")
            res = sp.simplify(sum(sp.diff(Fi, s) for Fi, s in zip(F, syms, strict=True)))
        elif op == "curl":
            if len(F) != 3 or len(syms) != 3:
                raise ValueError("curl needs a 3-component field in 3 variables.")
            (P, Q, R), (u, v, w) = F, syms
            res = sp.Matrix([sp.diff(R, v) - sp.diff(Q, w), sp.diff(P, w) - sp.diff(R, u), sp.diff(Q, u) - sp.diff(P, v)])
        elif op == "jacobian":
            res = sp.Matrix(F).jacobian(syms)
        else:
            raise ValueError(f"Unsupported vector calculus operation {operation!r}.")
        field_in = F
    verified = check_vector_calculus(op, field_in, syms, res)
    result = [[str(sp.simplify(c)) for c in res.row(i)] for i in range(res.rows)] if isinstance(res, sp.MatrixBase) else str(res)
    if isinstance(res, sp.MatrixBase) and res.cols == 1:
        result = [r[0] for r in result]
    return {
        "operation": op,
        "variables": names,
        "result": result,
        "latex": sp.latex(res),
        "verified": verified,
        "verification": "finite-difference partial derivatives at sample points" if verified else "finite differences disagree",
        "canonical_id": _canonical_id("axiom_vector_calculus", {"op": op, "in": str(field_in), "res": str(res)}),
    }


def _fd_partial(expr: sp.Expr, syms: list[sp.Symbol], pt: list[float], idx: tuple[int, ...]) -> complex | None:
    """mpmath partial derivative of expr at pt; idx lists the variable index of each differentiation."""
    try:
        f = sp.lambdify(syms, expr, modules="mpmath")
        orders = tuple(idx.count(i) for i in range(len(syms)))
        with mpmath.workdps(30):
            return complex(mpmath.diff(f, tuple(mpmath.mpf(p) for p in pt), orders))
    except Exception:
        return None


def check_vector_calculus(op: str, field_in: Any, syms: list[sp.Symbol], res: Any) -> bool:
    n = len(syms)
    for pt in ([0.71, 1.23, 0.57, 1.9][:n], [1.37, 0.43, 1.11, 0.66][:n]):
        subs = dict(zip(syms, [sp.Rational(str(p)) for p in pt], strict=True))

        def same(sym_expr: sp.Expr, fd: complex | None, subs: dict = subs) -> bool:
            v = _num(sym_expr, subs)
            return fd is not None and v is not None and abs(v - fd) <= 1e-6 * max(1.0, abs(v))

        if op == "gradient":
            ok = all(same(res[i], _fd_partial(field_in, syms, pt, (i,))) for i in range(n))
        elif op == "laplacian":
            fd = [_fd_partial(field_in, syms, pt, (i, i)) for i in range(n)]
            ok = None not in fd and same(res, sum(fd))  # type: ignore[arg-type]
        elif op == "hessian":
            ok = all(same(res[i, j], _fd_partial(field_in, syms, pt, (i, j))) for i in range(n) for j in range(n))
        elif op == "divergence":
            fd = [_fd_partial(field_in[i], syms, pt, (i,)) for i in range(n)]
            ok = None not in fd and same(res, sum(fd))  # type: ignore[arg-type]
        elif op == "jacobian":
            ok = all(same(res[i, j], _fd_partial(field_in[i], syms, pt, (j,))) for i in range(len(field_in)) for j in range(n))
        elif op == "curl":
            P, Q, R = field_in

            def d(e: sp.Expr, j: int, pt: list[float] = pt) -> complex:
                v = _fd_partial(e, syms, pt, (j,))
                return complex("nan") if v is None else v  # a zero partial is a valid (falsy) value

            expect = [d(R, 1) - d(Q, 2), d(P, 2) - d(R, 0), d(Q, 0) - d(P, 1)]
            ok = all(same(res[i], expect[i]) for i in range(3))
        else:
            return False
        if not ok:
            return False
    return True


# Integral transforms ----------------------------------------------------------------------------------------------

TransformKind = Literal["laplace", "inverse_laplace", "fourier"]


def axiom_transform(
    expression: str,
    transform: TransformKind,
    variable: str | None = None,
    transform_variable: str | None = None,
) -> dict[str, Any]:
    """Laplace transform F(s) = int_0^oo f(t) e^{-st} dt, its inverse, or the Fourier transform
    F(k) = int f(x) e^{-2 pi i k x} dx (SymPy's convention); checked numerically against the defining integral."""
    kind = str(transform).lower()
    if kind == "laplace":
        t, s = sp.Symbol(variable or "t", positive=True), sp.Symbol(transform_variable or "s")
        f = safe_parse_expr(expression, local_dict={t.name: t})
        F, abscissa, _cond = sp.laplace_transform(f, t, s)
        F = sp.simplify(F)
        verified = check_laplace(f, t, F, s, abscissa)
        out, inp = F, f
    elif kind == "inverse_laplace":
        s, t = sp.Symbol(variable or "s"), sp.Symbol(transform_variable or "t", positive=True)
        F = safe_parse_expr(expression, local_dict={s.name: s})
        f = sp.simplify(sp.inverse_laplace_transform(F, s, t))
        verified = check_laplace(f, t, F, s, None)
        out, inp = f, F
    elif kind == "fourier":
        x, k = sp.Symbol(variable or "x", real=True), sp.Symbol(transform_variable or "k", real=True)
        f = safe_parse_expr(expression, local_dict={x.name: x})
        out = sp.simplify(sp.fourier_transform(f, x, k))
        verified = check_fourier(f, x, out, k)
        inp = f
    else:
        raise ValueError(f"Unsupported transform {transform!r}.")
    if out.has(sp.LaplaceTransform, sp.InverseLaplaceTransform, sp.FourierTransform):
        raise ValueError("NotImplementedError: no closed-form transform found")
    return {
        "transform": kind,
        "input": str(inp),
        "result": str(out),
        "latex": sp.latex(out),
        "verified": verified,
        "verification": "matches the defining integral evaluated numerically" if verified else "numerical check failed or not applicable",
        "canonical_id": _canonical_id("axiom_transform", {"kind": kind, "in": expression, "out": str(out)}),
    }


def check_laplace(f: sp.Expr, t: sp.Symbol, F: sp.Expr, s: sp.Symbol, abscissa: Any) -> bool:
    """int_0^oo f(t) e^{-s t} dt by quadrature at two s values right of the convergence abscissa must equal F(s)."""
    try:
        base = float(abscissa) if abscissa is not None and sp.sympify(abscissa).is_finite else None
    except Exception:
        base = None
    if base is None:
        # Convergence half-plane from F itself: the defining integral converges right of F's rightmost pole.
        base = 0.0
        try:
            den = sp.denom(sp.together(F))
            if den.has(s):
                reals = [complex(r.evalf()).real for r in sp.Poly(den, s).all_roots()] if den.is_polynomial(s) else []
                base = max([0.0, *reals])
        except Exception:
            base = 0.0
    f_clean = f.replace(sp.Heaviside, lambda *a: sp.Integer(1))
    ok_points = 0
    for sv in (max(base, 0.0) + 1.3, max(base, 0.0) + 2.9):
        integrand = f_clean * sp.exp(-sp.Rational(str(sv)) * t)
        q = _quad(integrand, t, sp.Integer(0), sp.oo)
        v = _num(F.subs(s, sp.Rational(str(sv))), {})
        if q is None or v is None:
            return False
        if abs(q - v) > 1e-6 * max(1.0, abs(v)):
            return False
        ok_points += 1
    return ok_points == 2


def check_fourier(f: sp.Expr, x: sp.Symbol, F: sp.Expr, k: sp.Symbol) -> bool:
    for kv in (sp.Rational(3, 10), sp.Rational(7, 10)):
        integrand = f * sp.exp(-2 * sp.pi * sp.I * kv * x)
        q = _quad(integrand, x, -sp.oo, sp.oo)
        v = _num(F.subs(k, kv), {})
        if q is None or v is None or abs(q - v) > 1e-6 * max(1.0, abs(v)):
            return False
    return True


# Numerical quadrature ---------------------------------------------------------------------------------------------

def axiom_nintegrate(expression: str, lower: str, upper: str, variable: str = "x") -> dict[str, Any]:
    """Definite integral without a closed form (exp(-x^4), sin(x)/log(x), ...) by two independent quadrature rules
    (tanh-sinh and Gauss-Legendre); the value counts as verified when they agree to 1e-10."""
    x = sp.Symbol(_check_safe_string(variable))
    f = _parse_in(expression, x)
    a, b = safe_parse_expr(str(lower)), safe_parse_expr(str(upper))
    f_mp = sp.lambdify(x, f, modules="mpmath")

    def bound(v: sp.Expr) -> Any:
        return mpmath.inf if v == sp.oo else (-mpmath.inf if v == -sp.oo else mpmath.mpf(str(sp.N(v, 30))))

    with mpmath.workdps(30):
        v1, err1 = mpmath.quad(f_mp, [bound(a), bound(b)], method="tanh-sinh", error=True)
        try:
            v2 = mpmath.quad(f_mp, [bound(a), bound(b)], method="gauss-legendre")
        except Exception:
            v2 = None
    c1 = complex(v1)
    c2 = complex(v2) if v2 is not None else None
    agree = c2 is not None and abs(c1 - c2) <= 1e-10 * max(1.0, abs(c1))
    value = c1.real if abs(c1.imag) < 1e-14 else c1
    return {
        "expression": str(f),
        "lower": str(a),
        "upper": str(b),
        "value": value,
        "result": f"{value:.15g}" if isinstance(value, float) else str(value),
        "error_estimate": float(err1),
        "second_method": (c2.real if c2 is not None and abs(c2.imag) < 1e-14 else (str(c2) if c2 is not None else None)),
        "verified": bool(agree and math.isfinite(c1.real)),
        "verification": "tanh-sinh and Gauss-Legendre agree" if agree else "the two quadrature rules disagree",
        "canonical_id": _canonical_id("axiom_nintegrate", {"f": expression, "a": str(a), "b": str(b)}),
    }


__all__ = [
    "axiom_inequality",
    "axiom_nintegrate",
    "axiom_optimize",
    "axiom_tangent",
    "axiom_transform",
    "axiom_vector_calculus",
    "check_inequality",
    "check_optimize",
    "check_tangent",
    "check_vector_calculus",
    "parse_inequality",
]
