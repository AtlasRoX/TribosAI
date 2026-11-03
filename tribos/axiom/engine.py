"""
Axiom symbolic mathematics engine powered by SymPy and mpmath.

Provides deterministic symbolic simplification, equation/system solving with
substitution verification, symbolic & numeric calculus (with mpmath.quad cross-check),
symbolic ODE solving with checkodesol verification, exact linear algebra,
and symbolic + random-point identity verification.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from typing import Any, Literal

import mpmath
import sympy as sp

from .safe_expr import SAFE_NAMES as _SAFE_LOCALS
from .safe_expr import TRANSFORMATIONS, check_math_text, parse_math
from .shapes import UnsupportedShapeError, extract_free_symbols, to_sympy_container

_ASSUMPTION_KEYS = frozenset({
    "real",
    "positive",
    "negative",
    "nonnegative",
    "nonpositive",
    "nonzero",
    "integer",
    "even",
    "odd",
    "prime",
    "rational",
    "irrational",
    "finite",
    "complex",
    "commutative",
    "hermitian",
})


def _canonical_id(tool: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"comp:{tool}:{digest}"


def _build_assumption_symbols(assumptions: dict[str, str] | None) -> dict[str, sp.Symbol]:
    out: dict[str, sp.Symbol] = {}
    if not assumptions:
        return out
    for var_name, spec in assumptions.items():
        name = str(var_name).strip()
        if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        flags: dict[str, bool] = {}
        for token in re.split(r"[,;\s]+", str(spec or "").strip()):
            tok = token.strip().lower()
            if not tok:
                continue
            if tok.startswith("not_") and tok[4:] in _ASSUMPTION_KEYS:
                flags[tok[4:]] = False
            elif tok in _ASSUMPTION_KEYS:
                flags[tok] = True
        out[name] = sp.Symbol(name, **flags)
    return out


def _check_safe_string(text: str) -> str:
    """The NFKC-normalised ASCII text, or ValueError (see safe_expr.check_math_text)."""
    return check_math_text(text)


def safe_parse_expr(
    expression: Any,
    local_dict: dict[str, Any] | None = None,
    assumptions: dict[str, str] | None = None,
) -> sp.Basic:
    """Parse a mathematical expression string into a SymPy expression through the allowlist parser (safe_expr): the
    text is normalised, the generated code is validated (no attribute access, dunders or unlisted calls), and only
    then evaluated without builtins. Supported containers (tuples, lists) are converted to SymPy containers (sp.Tuple)."""
    if isinstance(expression, sp.Basic):
        return expression
    if isinstance(expression, (int, float, complex)):
        return sp.sympify(expression)
    if isinstance(expression, (tuple, list)):
        return to_sympy_container([safe_parse_expr(x, local_dict=local_dict, assumptions=assumptions) for x in expression])
    if isinstance(expression, dict):
        raise UnsupportedShapeError(f"Dictionary is not a valid mathematical expression: {expression!r}")

    cleaned = _check_safe_string(expression)
    env = dict(_SAFE_LOCALS)
    if assumptions:
        env.update(_build_assumption_symbols(assumptions))
    if local_dict:
        env.update(local_dict)
    try:
        parsed = parse_math(cleaned, env)
        if isinstance(parsed, (tuple, list)):
            return to_sympy_container(parsed)
        return parsed
    except Exception as exc:
        if isinstance(exc, (ValueError, TypeError, UnsupportedShapeError)):
            raise
        raise ValueError(f"Could not parse mathematical expression {cleaned!r}: {exc}") from exc


def safe_parse_equation(
    equation: str,
    local_dict: dict[str, Any] | None = None,
    assumptions: dict[str, str] | None = None,
) -> tuple[sp.Expr, sp.Expr, sp.Basic]:
    """Parse an equation 'LHS = RHS' or expression 'EXPR' (= 0). Returns (lhs, rhs, Eq(lhs, rhs))."""
    cleaned = _check_safe_string(equation)
    # Normalize '==' to '=' if present
    cleaned_eq = cleaned.replace("==", "=")
    if "=" in cleaned_eq and not cleaned_eq.startswith("Eq("):
        parts = cleaned_eq.split("=")
        if len(parts) != 2:
            raise ValueError(f"Invalid equation format (multiple '=' signs): {equation!r}")
        lhs = safe_parse_expr(parts[0], local_dict=local_dict, assumptions=assumptions)
        rhs = safe_parse_expr(parts[1], local_dict=local_dict, assumptions=assumptions)
        return lhs, rhs, sp.Eq(lhs, rhs)
    parsed = safe_parse_expr(cleaned, local_dict=local_dict, assumptions=assumptions)
    if isinstance(parsed, sp.Equality):
        return parsed.lhs, parsed.rhs, parsed
    if isinstance(parsed, sp.core.relational.Relational):
        # "lhs < rhs" has a solution set, not roots: say which tool solves it instead of failing on lhs - rhs.
        raise ValueError(f"{equation!r} is an inequality, not an equation; solve it with axiom_inequality.")
    return parsed, sp.Integer(0), sp.Eq(parsed, sp.Integer(0))


def axiom_latex(expression: str) -> dict[str, Any]:
    """Parse a mathematical expression or equation and return its canonical SymPy representation, LaTeX, and free symbols."""
    cleaned = _check_safe_string(expression)
    if "=" in cleaned.replace("==", "=") and not cleaned.startswith("Eq("):
        lhs, rhs, eq_obj = safe_parse_equation(cleaned)
        target: sp.Basic = eq_obj
        free_syms = extract_free_symbols(eq_obj)
    else:
        target = safe_parse_expr(cleaned)
        free_syms = extract_free_symbols(target)
    sympy_str = str(target)
    latex_str = sp.latex(target)
    cid = _canonical_id("axiom_latex", {"expression": cleaned, "sympy": sympy_str})
    return {
        "expression": cleaned,
        "sympy": sympy_str,
        "latex": latex_str,
        "free_symbols": free_syms,
        "canonical_id": cid,
    }


def _simplify_scalar_expr(
    expr: sp.Expr,
    assumptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    simplified_expr = sp.simplify(expr)
    try:
        trig_expr = sp.trigsimp(simplified_expr)
        if len(str(trig_expr)) < len(str(simplified_expr)):
            simplified_expr = trig_expr
    except Exception:
        trig_expr = simplified_expr
    try:
        factored_expr = sp.factor(expr)
    except Exception:
        factored_expr = simplified_expr
    try:
        expanded_expr = sp.expand(expr)
    except Exception:
        expanded_expr = simplified_expr
    try:
        canceled_expr = sp.cancel(expr)
    except Exception:
        canceled_expr = simplified_expr

    free_syms = sorted(str(s) for s in getattr(expr, "free_symbols", set()))
    return {
        "expression": str(expr),
        "simplified": str(simplified_expr),
        "latex": sp.latex(simplified_expr),
        "factored": str(factored_expr),
        "expanded": str(expanded_expr),
        "canceled": str(canceled_expr),
        "trig_simplified": str(trig_expr),
        "free_symbols": free_syms,
    }


def axiom_simplify(
    expression: Any,
    assumptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Simplify, factor, expand, trig-simplify, and cancel a symbolic mathematical expression or collection."""
    expr = safe_parse_expr(expression, assumptions=assumptions)

    if isinstance(expr, (sp.Tuple, tuple, list)):
        if len(expr) == 0:
            raise UnsupportedShapeError("Empty container cannot be simplified")

        items = [_simplify_scalar_expr(item, assumptions=assumptions) for item in expr]
        is_list = isinstance(expression, list) or (isinstance(expression, str) and expression.strip().startswith("["))
        op_bracket = "[" if is_list else "("
        cl_bracket = "]" if is_list else ")"

        def _join_str(key: str) -> str:
            return op_bracket + ", ".join(item[key] for item in items) + cl_bracket

        free_syms = sorted({s for item in items for s in item["free_symbols"]})
        latex_str = sp.latex(sp.Tuple(*(sp.sympify(item["simplified"]) for item in items)))
        cid = _canonical_id(
            "axiom_simplify",
            {"expression": str(expression), "assumptions": assumptions or {}, "simplified": _join_str("simplified")},
        )
        return {
            "expression": str(expr),
            "simplified": _join_str("simplified"),
            "latex": latex_str,
            "factored": _join_str("factored"),
            "expanded": _join_str("expanded"),
            "canceled": _join_str("canceled"),
            "trig_simplified": _join_str("trig_simplified"),
            "free_symbols": free_syms,
            "items": items,
            "shape": "list" if is_list else "tuple",
            "canonical_id": cid,
        }

    res = _simplify_scalar_expr(expr, assumptions=assumptions)
    cid = _canonical_id(
        "axiom_simplify",
        {"expression": str(expression), "assumptions": assumptions or {}, "simplified": res["simplified"]},
    )
    res["canonical_id"] = cid
    return res


def _is_real_value(val: sp.Basic) -> bool:
    if getattr(val, "is_real", None) is True:
        return True
    if getattr(val, "is_real", None) is False:
        return False
    try:
        cval = complex(val.evalf(30))
        return abs(cval.imag) < 1e-12
    except Exception:
        # A value that cannot be evaluated is not known to be real (it may be a complex root); a symbol declared real
        # was already accepted above.
        return False


_INTERVAL_DOMAIN_RE = re.compile(r"^\s*([\[(])\s*([^,\[\]()]+(?:\([^()]*\))?[^,\[\]()]*)\s*,\s*([^,\[\]()]+(?:\([^()]*\))?[^,\[\]()]*)\s*([\])])\s*$")


def _parse_interval_domain(domain: str) -> sp.Interval | None:
    """"[0, 2*pi)" -> Interval.Ropen(0, 2*pi); None for a named domain (real, complex, integer, ...)."""
    m = _INTERVAL_DOMAIN_RE.match(domain or "")
    if not m:
        return None
    lo = safe_parse_expr(m.group(2).replace("π", "pi"))
    hi = safe_parse_expr(m.group(3).replace("π", "pi"))
    if lo.free_symbols or hi.free_symbols or not (lo.is_real and hi.is_real) or bool(hi < lo):
        raise ValueError(f"Invalid interval domain {domain!r}")
    return sp.Interval(lo, hi, left_open=m.group(1) == "(", right_open=m.group(4) == ")")


def _solve_on_interval(eq_list: list[str], residual_exprs: list[sp.Expr], target_syms: list[sp.Symbol],
                       interval: sp.Interval, domain_text: str) -> dict[str, Any]:
    """A single equation in one unknown solved over a finite real interval with solveset: a periodic equation then has
    finitely many solutions, all listed, each back-substituted."""
    if len(residual_exprs) != 1 or len(target_syms) != 1:
        raise ValueError("An interval domain applies to one equation in one unknown.")
    sym = target_syms[0]
    real_sym = sp.Symbol(sym.name, real=True)
    expr = residual_exprs[0].subs(sym, real_sym)
    found = sp.solveset(expr, real_sym, domain=interval)
    finite = isinstance(found, sp.FiniteSet)
    values = sorted(found, key=lambda v: float(sp.N(v))) if finite else []
    solutions, latex_parts, residuals, ok = [], [], [], True
    for v in values:
        residual = sp.simplify(expr.subs(real_sym, v))
        zero = residual == 0 or abs(complex(sp.N(expr.subs(real_sym, v), 30))) < 1e-12
        ok = ok and bool(zero)
        solutions.append({sym.name: str(sp.simplify(v))})
        latex_parts.append(f"{sp.latex(sym)} = {sp.latex(sp.simplify(v))}")
        residuals.append(["0" if zero else str(residual)])
    return {
        "equations": eq_list,
        "variables": [sym.name],
        "domain": domain_text,
        "solutions": solutions,
        "latex": ", ".join(latex_parts),
        "verified": bool(solutions) and ok,
        "residuals": residuals,
        "complete": finite,
        "solution_set": str(found),
        "interval": str(interval),
    }


def axiom_solve(
    equations: str | list[str],
    variables: str | list[str] | None = None,
    domain: str = "complex",
) -> dict[str, Any]:
    """Solve algebraic or transcendental equation(s) or systems and verify each solution by back-substitution."""
    eq_list = [equations] if isinstance(equations, str) else list(equations)
    if not eq_list:
        raise ValueError("At least one equation must be provided.")

    parsed_pairs: list[tuple[sp.Expr, sp.Expr]] = []
    residual_exprs: list[sp.Expr] = []
    all_free: list[sp.Symbol] = []
    seen_names: set[str] = set()

    for eq_str in eq_list:
        lhs, rhs, _ = safe_parse_equation(eq_str)
        if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
            if not (isinstance(lhs, (sp.Tuple, tuple, list)) and isinstance(rhs, (sp.Tuple, tuple, list))):
                raise UnsupportedShapeError("Shape mismatch in equation: cannot equate container to scalar")
            if len(lhs) != len(rhs):
                raise UnsupportedShapeError(f"Shape length mismatch in equation: {len(lhs)} != {len(rhs)}")
            for l_item, r_item in zip(lhs, rhs, strict=True):
                parsed_pairs.append((l_item, r_item))
                try:
                    res = l_item - r_item
                except TypeError as exc:
                    raise UnsupportedShapeError(f"Cannot equate incompatible types in equation: {exc}") from exc
                residual_exprs.append(res)
                for sym in sorted(res.free_symbols, key=lambda s: s.name):
                    if sym.name not in seen_names:
                        seen_names.add(sym.name)
                        all_free.append(sym)
            continue
        parsed_pairs.append((lhs, rhs))
        try:
            res_expr = lhs - rhs
        except TypeError as exc:
            raise UnsupportedShapeError(f"Cannot equate incompatible types in equation: {exc}") from exc
        residual_exprs.append(res_expr)
        for sym in sorted(res_expr.free_symbols, key=lambda s: s.name):
            if sym.name not in seen_names:
                seen_names.add(sym.name)
                all_free.append(sym)

    def _clean_var(item: str) -> str:
        raw = str(item).strip().strip("$")
        raw = re.split(r"\\in|>|<|>=|<=|=", raw)[0].strip()
        m = re.search(r"[A-Za-z_]\w*", raw)
        if not m:
            raise ValueError(f"Invalid variable identifier: {item!r}")
        return m.group(0)

    clean_dom = str(domain or "complex").strip().lower()
    if clean_dom in ("real", "reals", "r"):
        norm_domain = "real"
    elif clean_dom in ("integer", "integers", "z"):
        norm_domain = "integer"
    elif clean_dom in ("positive_integer", "positive_integers", "natural", "n", "positive"):
        norm_domain = "positive_integer"
    elif clean_dom in ("complex", "c"):
        norm_domain = "complex"
    else:
        norm_domain = clean_dom

    if variables is None:
        target_syms = all_free
    elif isinstance(variables, str):
        names = [_clean_var(v) for v in variables.split(",") if v.strip()]
        target_syms = [sp.Symbol(n) for n in names]
    else:
        target_syms = [sp.Symbol(_clean_var(str(n))) for n in variables if str(n).strip()]

    if not target_syms:
        raise ValueError("No variables found to solve for.")

    interval = _parse_interval_domain(norm_domain)
    if interval is not None:
        return _solve_on_interval(eq_list, residual_exprs, target_syms, interval, norm_domain)
    want_real = norm_domain in ("real", "integer", "positive_integer")
    want_integer = norm_domain in ("integer", "positive_integer")
    want_positive = norm_domain == "positive_integer"
    if want_real:
        # Solve over real symbols, not only filter afterwards: Abs(x - 3) = 5 has no complex-domain method at all.
        real_map = {s: sp.Symbol(s.name, real=True) for s in target_syms if s.is_real is None}
        if real_map:
            residual_exprs = [r.subs(real_map) for r in residual_exprs]
            target_syms = [real_map.get(s, s) for s in target_syms]
    raw_solutions = sp.solve(residual_exprs, target_syms, dict=True)
    if len(residual_exprs) == 1 and len(target_syms) == 1:
        raw_solutions = _complete_polynomial_roots(residual_exprs[0], target_syms[0], want_real, raw_solutions)

    solutions_out: list[dict[str, str]] = []
    solutions_latex: list[dict[str, str]] = []
    residuals_out: list[list[str]] = []
    all_verified = True

    for sol in raw_solutions:
        if want_real and not all(_is_real_value(v) for v in sol.values()):
            continue
        if want_integer and not all(
            getattr(sp.simplify(v), "is_integer", None) is True
            or isinstance(v, (int, sp.Integer))
            or (isinstance(v, sp.Rational) and v.q == 1)
            for v in sol.values()
        ):
            continue
        if want_positive and not all(
            getattr(sp.simplify(v), "is_positive", None) is True
            or (isinstance(v, (int, float, sp.Number)) and float(v) > 0)
            for v in sol.values()
        ):
            continue
        sol_str = {str(k): str(sp.simplify(v)) for k, v in sol.items()}
        sol_ltx = {str(k): sp.latex(sp.simplify(v)) for k, v in sol.items()}
        sol_residuals: list[str] = []
        sol_ok = True
        for res_expr in residual_exprs:
            subbed = res_expr.subs(sol)
            simp = sp.simplify(subbed)
            is_zero = bool(simp == 0)
            if not is_zero:
                try:
                    num_val = complex(subbed.evalf(30))
                    is_zero = abs(num_val) < 1e-10
                except Exception:
                    is_zero = False
            if not is_zero:
                sol_ok = False
                sol_residuals.append(str(simp))
            else:
                sol_residuals.append("0")
        if not sol_ok:
            all_verified = False
        solutions_out.append(sol_str)
        solutions_latex.append(sol_ltx)
        residuals_out.append(sol_residuals)

    verified = bool(len(solutions_out) > 0 and all_verified)
    complete, solution_set = _solution_completeness(residual_exprs, target_syms, want_real, len(solutions_out))
    if len(target_syms) == 1:
        var_key = str(target_syms[0])
        latex_summary = ", ".join(
            f"{sp.latex(target_syms[0])} = {s[var_key]}" for s in solutions_latex if var_key in s
        )
    else:
        latex_summary = "; ".join(
            "(" + ", ".join(f"{k}={v}" for k, v in s.items()) + ")" for s in solutions_latex
        )

    cid = _canonical_id(
        "axiom_solve",
        {"equations": eq_list, "variables": [str(s) for s in target_syms], "domain": norm_domain, "solutions": solutions_out},
    )
    return {
        "equations": eq_list,
        "variables": [str(s) for s in target_syms],
        "domain": norm_domain,
        "solutions": solutions_out,
        "latex": latex_summary,
        "verified": verified,
        "residuals": residuals_out,
        # verified: every listed solution satisfies every equation. complete: the list is the whole solution set
        # (False when solveset finds an infinite family solve truncated, None when it could not decide).
        "complete": complete,
        "solution_set": solution_set,
        "canonical_id": cid,
    }


def _complete_polynomial_roots(
    expr: sp.Expr, sym: sp.Symbol, want_real: bool, found: list[dict[sp.Basic, sp.Basic]]
) -> list[dict[sp.Basic, sp.Basic]]:
    """solve() returns nothing (or too little) for polynomials without a radical solution, e.g. x^5 - x - 1. Their
    roots are still exact as CRootOf objects; use those whenever solve() found fewer distinct roots than exist."""
    try:
        num, den = sp.fraction(sp.together(expr))
        if not num.is_polynomial(sym) or num.free_symbols - {sym}:
            return found
        core = sp.Poly(sp.sqf_part(num), sym)
        if core.degree() < 1:
            return found
        expected = core.count_roots() if want_real else core.degree()
        if len(found) >= expected:
            return found
        roots = core.real_roots() if want_real else core.all_roots()
        return [{sym: r} for r in dict.fromkeys(roots) if not den.has(sym) or den.subs(sym, r) != 0]
    except Exception:
        return found


def _solution_completeness(
    residuals: list[sp.Expr], syms: list[sp.Symbol], want_real: bool, n_found: int
) -> tuple[bool | None, str | None]:
    """Whether solve() returned the whole solution set of a single univariate equation.

    Polynomials are complete by construction; other equations are cross-checked with solveset, which returns
    periodic families (ImageSet) that solve() silently truncates, e.g. sin(x) = 0 -> [0, pi].
    """
    if len(residuals) != 1 or len(syms) != 1:
        return None, None
    expr, sym = residuals[0], syms[0]
    try:
        if expr.is_polynomial(sym):
            return True, None
    except Exception:
        pass
    try:
        sset = sp.solveset(expr, sym, domain=sp.S.Reals if want_real else sp.S.Complexes)
    except Exception:
        return None, None
    if isinstance(sset, sp.FiniteSet):
        return len(sset) <= n_found, str(sset)
    if sset is sp.S.EmptySet:
        return n_found == 0, str(sset)
    if isinstance(sset, sp.ConditionSet):
        return None, str(sset)
    return False, str(sset)  # ImageSet / Union / Interval: infinitely many solutions


def _to_mpmath_bound(expr: sp.Expr) -> Any:
    if expr == sp.oo:
        return mpmath.inf
    if expr == -sp.oo:
        return -mpmath.inf
    return float(expr.evalf(30))


# Independent numeric checks ----------------------------------------------------------------------------------------
# A closed form is only reported as verified when a second, numerical method agrees with it. Free parameters are
# pinned to fixed generic values so multivariate results are checked too instead of being waved through.

_PARAM_VALUES = (0.61, 0.83, 1.29, 1.47, 0.37, 1.91, 0.53, 1.13)


def _fix_parameters(syms: set[sp.Basic], var_sym: sp.Symbol | None = None) -> dict[sp.Symbol, sp.Basic]:
    others = sorted((s for s in syms if isinstance(s, sp.Symbol) and s != var_sym), key=lambda s: s.name)
    return {s: sp.Rational(str(_PARAM_VALUES[i % len(_PARAM_VALUES)])) for i, s in enumerate(others)}


def _num(expr: sp.Basic, subs: dict[sp.Symbol, Any]) -> complex | None:
    """expr evaluated to 30 digits (adaptive precision, so cancellation near a limit point is handled); None if
    it is not a finite number."""
    try:
        val = complex(expr.evalf(30, subs=subs) if subs else expr.evalf(30))
    except Exception:
        return None
    return val if math.isfinite(val.real) and math.isfinite(val.imag) else None


def _quad(integrand: sp.Expr, var_sym: sp.Symbol, low: sp.Expr, up: sp.Expr) -> complex | None:
    if integrand.free_symbols - {var_sym} or low.free_symbols or up.free_symbols:
        return None
    try:
        f_mp = sp.lambdify(var_sym, integrand, modules="mpmath")
        with mpmath.workdps(30):
            val = complex(mpmath.quad(f_mp, [_to_mpmath_bound(low), _to_mpmath_bound(up)]))
    except Exception:
        return None
    return val if math.isfinite(val.real) and math.isfinite(val.imag) else None


def _zero_check(expr: sp.Expr, what: str) -> tuple[bool, str]:
    """Is expr identically zero? Cheap symbolic normal forms first, then simplify, then generic sample points."""
    try:
        if sp.expand(expr) == 0 or sp.cancel(expr) == 0 or sp.simplify(expr) == 0 or sp.trigsimp(sp.simplify(expr)) == 0:
            return True, f"symbolic: {what}"
    except Exception:
        pass
    syms = sorted(expr.free_symbols, key=lambda s: s.name)
    evaluated = 0
    for offset in range(4):
        pt = {s: sp.Rational(str(_PARAM_VALUES[(i + offset) % len(_PARAM_VALUES)])) for i, s in enumerate(syms)}
        val = _num(expr, pt)
        if val is None:
            continue
        if abs(val) > 1e-12:
            return False, f"numeric counterexample: {what} fails"
        evaluated += 1
    if evaluated >= 2:
        return True, f"numeric (sample points): {what}"
    return False, "not checked"


def _check_derivative(expr: sp.Expr, result: sp.Expr, var_sym: sp.Symbol, order: int) -> bool:
    if order > 8:
        return False
    params = _fix_parameters(expr.free_symbols, var_sym)
    f_mp = sp.lambdify(var_sym, expr.subs(params), modules="mpmath")
    res = result.subs(params)
    for test_x in ("0.73", "1.37", "2.11", "-0.59"):
        sym_d = _num(res, {var_sym: sp.Rational(test_x)})
        if sym_d is None:
            continue
        try:
            with mpmath.workdps(40):
                num_d = complex(mpmath.diff(f_mp, mpmath.mpf(test_x), n=order))
        except Exception:
            continue
        if not (math.isfinite(num_d.real) and math.isfinite(num_d.imag)):
            continue
        return abs(num_d - sym_d) <= 1e-6 * max(1.0, abs(sym_d))
    return False


def _check_limit(expr: sp.Expr, var_sym: sp.Symbol, point: sp.Expr, direction: str, result: sp.Expr) -> bool:
    """Evaluate expr ever closer to the limit point from each requested side and compare with the result."""
    params = _fix_parameters(expr.free_symbols | result.free_symbols, var_sym)
    f = expr.subs(params)
    infinite = result in (sp.oo, -sp.oo)
    target = None if infinite else _num(result.subs(params), {})
    if not infinite and target is None:
        return False
    if point in (sp.oo, -sp.oo):
        sign = 1 if point == sp.oo else -1
        paths = [[sp.Integer(sign * 10**6), sp.Integer(sign * 10**9)]]
    else:
        x0 = point.subs(params)
        if x0.free_symbols:
            return False
        sides = {"+": [1], "-": [-1]}.get(direction, [1, -1])
        paths = [[x0 + s * sp.Rational(1, 10**6), x0 + s * sp.Rational(1, 10**9)] for s in sides]
    for far, near in paths:
        v_near, v_far = _num(f, {var_sym: near}), _num(f, {var_sym: far})
        if v_near is None:
            return False
        if infinite:
            sign = 1 if result == sp.oo else -1
            if not (sign * v_near.real > 1e3 and v_far is not None and abs(v_near) >= abs(v_far)):
                return False
        elif abs(v_near - target) > 1e-3 * max(1.0, abs(target)):
            return False
    return True


def _check_series(expr: sp.Expr, poly: sp.Expr, var_sym: sp.Symbol, point: sp.Expr, n_terms: int) -> bool:
    """A truncated expansion of order n must agree with expr to O(h^n) near the expansion point."""
    if point.free_symbols or point in (sp.oo, -sp.oo):
        return False
    params = _fix_parameters(expr.free_symbols, var_sym)
    f, p = expr.subs(params), poly.subs(params)
    errs = []
    for h in (sp.Rational(1, 100), sp.Rational(1, 1000)):
        fv, pv = _num(f, {var_sym: point + h}), _num(p, {var_sym: point + h})
        if fv is None or pv is None:
            return False
        errs.append((abs(fv - pv), max(1.0, abs(fv)), float(h)))
    return all(err <= 10.0 * scale * h ** (n_terms - 0.5) for err, scale, h in errs)


def _check_sum(expr: sp.Expr, var_sym: sp.Symbol, low: sp.Expr, up: sp.Expr, result: sp.Expr) -> tuple[bool, str]:
    """Closed form vs direct partial sums (symbolic upper bound), direct summation, or mpmath.nsum (infinite)."""
    try:
        bound_syms = up.free_symbols - {var_sym}
        if low.is_integer and low.is_number and len(bound_syms) == 1:
            n_sym = next(iter(bound_syms))
            params = _fix_parameters(expr.free_symbols | result.free_symbols, var_sym)
            params.pop(n_sym, None)
            term = expr.subs(params)
            lo = int(low)
            for big_n in range(lo, lo + 6):
                direct = sp.Add(*[term.subs(var_sym, k) for k in range(lo, big_n + 1)])
                diff_val = _num(result.subs(params).subs(n_sym, big_n) - direct, {})
                if diff_val is None or abs(diff_val) > 1e-9 * max(1.0, abs(_num(direct, {}) or 1.0)):
                    return False, "closed form disagrees with direct partial sums"
            return True, "closed form matches direct partial sums for 6 values of the bound"
        params = _fix_parameters(expr.free_symbols | result.free_symbols, var_sym)
        term = expr.subs(params)
        target = _num(result.subs(params), {})
        if target is None or not (low.is_number and (up.is_number or up == sp.oo)):
            return False, "not checked"
        if up == sp.oo:
            f_mp = sp.lambdify(var_sym, term, modules="mpmath")
            with mpmath.workdps(30):
                approx = complex(mpmath.nsum(f_mp, [int(low), mpmath.inf]))
            ok = abs(approx - target) <= 1e-8 * max(1.0, abs(target))
            return ok, "mpmath.nsum cross-check" if ok else "mpmath.nsum disagrees with the closed form"
        if int(up) - int(low) <= 5000:
            direct = _num(sp.Add(*[term.subs(var_sym, k) for k in range(int(low), int(up) + 1)]), {})
            ok = direct is not None and abs(direct - target) <= 1e-9 * max(1.0, abs(target))
            return ok, "direct summation" if ok else "direct summation disagrees with the closed form"
    except Exception:
        pass
    return False, "not checked"


def axiom_calculus(
    expression: str,
    operation: Literal["diff", "integrate", "limit", "series", "sum"],
    variable: str = "x",
    order: int = 1,
    lower: str | None = None,
    upper: str | None = None,
    point: str | None = None,
) -> dict[str, Any]:
    """Perform symbolic calculus (diff, integrate, limit, series, sum) with numerical cross-checking."""
    var_sym = sp.Symbol(_check_safe_string(variable))
    expr = safe_parse_expr(expression, local_dict={variable: var_sym})
    op = str(operation).strip().lower()

    if isinstance(expr, (sp.Tuple, tuple, list)):
        if op == "diff":
            items = [
                axiom_calculus(str(item), operation="diff", variable=variable, order=order)
                for item in expr
            ]
            res_tuple = sp.Tuple(*(sp.sympify(item["result"]) for item in items))
            return {
                "operation": "diff",
                "variable": variable,
                "order": int(order),
                "result": str(res_tuple),
                "latex": sp.latex(res_tuple),
                "verified": all(item["verified"] for item in items),
                "method": "element-wise derivative check",
                "items": items,
            }
        raise UnsupportedShapeError(f"Operation '{op}' requires a scalar expression, got container {type(expr).__name__}")

    numeric_value: float | None = None
    verified = False
    method = "not checked"
    one_sided: dict[str, str] | None = None
    result_str = ""
    latex_str = ""

    if op == "diff":
        res_expr = sp.diff(expr, var_sym, int(order))
        result_str = str(res_expr)
        latex_str = sp.latex(res_expr)
        verified = _check_derivative(expr, res_expr, var_sym, int(order))
        method = "mpmath.diff at sample points" if verified else "numeric derivative check failed or not applicable"

    elif op == "integrate":
        if lower is not None and upper is not None:
            low_expr = safe_parse_expr(str(lower), local_dict={variable: var_sym})
            up_expr = safe_parse_expr(str(upper), local_dict={variable: var_sym})
            res_expr = sp.integrate(expr, (var_sym, low_expr, up_expr))
            result_str = str(res_expr)
            latex_str = sp.latex(res_expr)
            # Free parameters (integrand or bounds) are pinned to fixed sample values so the closed form can still be
            # cross-checked against mpmath.quad; numeric_value is only reported for a parameter-free integral.
            params = _fix_parameters(expr.free_symbols | low_expr.free_symbols | up_expr.free_symbols, var_sym)
            pinned = res_expr.subs(params)  # also resolves Piecewise convergence conditions on the parameters
            sym_val = None if pinned.has(sp.Integral) else _num(pinned, {})
            if not params and sym_val is not None and abs(sym_val.imag) < 1e-12:
                numeric_value = float(sym_val.real)
            quad_val = _quad(expr.subs(params), var_sym, low_expr.subs(params), up_expr.subs(params))
            if quad_val is not None:
                if numeric_value is None and not params and abs(quad_val.imag) < 1e-9:
                    numeric_value = float(quad_val.real)
                if sym_val is not None:
                    verified = abs(sym_val - quad_val) <= 1e-5 * max(1.0, abs(quad_val))
                    method = "mpmath.quad cross-check" + (" (parameters pinned)" if params else "")
        else:
            res_expr = sp.integrate(expr, var_sym)
            result_str = str(res_expr)
            latex_str = sp.latex(res_expr)
            # Verify indefinite integral by differentiating back (symbolically, then numerically)
            if not res_expr.has(sp.Integral):
                back = sp.diff(res_expr, var_sym) - expr
                verified, method = _zero_check(back, "d/dx of the antiderivative equals the integrand")

    elif op == "limit":
        raw_pt = str(point if point is not None else "0").strip()
        direction = "+-"
        if raw_pt.endswith("+") and len(raw_pt) > 1:
            direction = "+"
            raw_pt = raw_pt[:-1].strip()
        elif raw_pt.endswith("-") and len(raw_pt) > 1 and not raw_pt.startswith("-"):
            direction = "-"
            raw_pt = raw_pt[:-1].strip()
        pt_expr = safe_parse_expr(raw_pt, local_dict={variable: var_sym})
        try:
            res_expr = sp.limit(expr, var_sym, pt_expr, dir=direction)
        except ValueError as exc:  # sympy: "The limit does not exist since left hand limit = ..."
            if direction != "+-" or "does not exist" not in str(exc):
                raise
            res_expr = sp.zoo
        if direction == "+-" and res_expr is sp.zoo and pt_expr.is_finite:
            # Two different one-sided limits (1/x at 0, sign(x) at 0): the two-sided limit does not exist.
            left = sp.limit(expr, var_sym, pt_expr, dir="-")
            right = sp.limit(expr, var_sym, pt_expr, dir="+")
            if left != right:
                one_sided = {"left": str(left), "right": str(right)}
                result_str = f"does not exist (left limit {left}, right limit {right})"
                latex_str = rf"\text{{does not exist: }} \lim_{{{sp.latex(var_sym)}\to {sp.latex(pt_expr)}^-}} = {sp.latex(left)},\ \lim_{{{sp.latex(var_sym)}\to {sp.latex(pt_expr)}^+}} = {sp.latex(right)}"
                verified = _check_limit(expr, var_sym, pt_expr, "-", left) and _check_limit(expr, var_sym, pt_expr, "+", right)
                method = "both one-sided limits checked numerically; they differ" if verified else "one-sided limits not confirmed"
        if one_sided is None:
            result_str = str(res_expr)
            latex_str = sp.latex(res_expr)
            if not res_expr.free_symbols:
                cval = _num(res_expr, {})
                if cval is not None and abs(cval.imag) < 1e-12:
                    numeric_value = float(cval.real)
            if not isinstance(res_expr, sp.Limit):
                verified = _check_limit(expr, var_sym, pt_expr, direction, res_expr)
                method = "numeric approach from each side" if verified else "numeric approach did not confirm the limit"

    elif op == "series":
        pt_expr = safe_parse_expr(str(point if point is not None else "0"), local_dict={variable: var_sym})
        n_terms = int(order) if int(order) > 1 else 6
        ser = sp.series(expr, var_sym, pt_expr, n=n_terms)
        poly = ser.removeO()
        result_str = str(poly)
        latex_str = sp.latex(ser)
        verified = _check_series(expr, poly, var_sym, pt_expr, n_terms)
        method = "truncation error scales as h^n" if verified else "truncation error check failed or not applicable"

    elif op == "sum":
        low_expr = safe_parse_expr(str(lower if lower is not None else "1"), local_dict={variable: var_sym})
        up_expr = safe_parse_expr(str(upper if upper is not None else "n"), local_dict={variable: var_sym})
        res_expr = sp.summation(expr, (var_sym, low_expr, up_expr))
        res_simplified = sp.simplify(res_expr)
        result_str = str(res_simplified)
        latex_str = sp.latex(res_simplified)
        if not res_simplified.free_symbols:
            cval = _num(res_simplified, {})
            if cval is not None and abs(cval.imag) < 1e-12:
                numeric_value = float(cval.real)
        if not res_simplified.has(sp.Sum):
            verified, method = _check_sum(expr, var_sym, low_expr, up_expr, res_simplified)
    else:
        raise ValueError(f"Unsupported calculus operation: {operation!r}")

    cid = _canonical_id(
        "axiom_calculus",
        {
            "expression": expression,
            "operation": op,
            "variable": variable,
            "order": order,
            "lower": lower,
            "upper": upper,
            "point": point,
            "result": result_str,
        },
    )
    return {
        "expression": str(expr),
        "operation": op,
        "variable": variable,
        "result": result_str,
        "latex": latex_str,
        "numeric_value": numeric_value,
        "verified": verified,
        "verification": method,
        "one_sided": one_sided,
        "canonical_id": cid,
    }


def axiom_nsolve(
    equation: str,
    variable: str | None = None,
    lower: float = -10.0,
    upper: float = 10.0,
    samples: int = 400,
) -> dict[str, Any]:
    """Real roots of a univariate equation on [lower, upper]: sign-change and |f| local-minimum scan, refined with
    mpmath.findroot, each root kept only if its residual vanishes (which drops poles such as tan(x) = 0 at pi/2).

    The numeric fallback when no closed form exists (x = cos(x), x*exp(x) = 3). A scan cannot prove that it found
    every root, so `complete` is always None."""
    lhs, rhs, _ = safe_parse_equation(equation)
    if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
        if not (isinstance(lhs, (sp.Tuple, tuple, list)) and isinstance(rhs, (sp.Tuple, tuple, list))):
            raise UnsupportedShapeError("Shape mismatch in equation: cannot equate container to scalar")
        raise UnsupportedShapeError(f"Operation 'nsolve' requires a scalar equation, got container {type(lhs).__name__}")
    try:
        f_expr = lhs - rhs
    except TypeError as exc:
        raise UnsupportedShapeError(f"Cannot form residual for numeric solve: {exc}") from exc
    if isinstance(f_expr, (sp.Tuple, tuple, list)):
        raise UnsupportedShapeError(f"Operation 'nsolve' requires a scalar equation, got container {type(f_expr).__name__}")
    free = sorted(f_expr.free_symbols, key=lambda s: s.name)
    if variable:
        sym = next((s for s in free if s.name == variable), sp.Symbol(variable))
    elif len(free) == 1:
        sym = free[0]
    else:
        raise ValueError(f"Specify the variable: the equation has free symbols {[s.name for s in free]}.")
    if f_expr.free_symbols - {sym}:
        raise ValueError("Numeric root finding needs every parameter to have a value; only the unknown may be free.")
    lo, hi = float(lower), float(upper)
    if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
        raise ValueError("The search interval needs finite bounds with lower < upper.")
    n = max(20, min(5000, int(samples)))
    f_mp = sp.lambdify(sym, f_expr, modules="mpmath")

    def fval(x: float) -> float | None:
        try:
            v = complex(f_mp(mpmath.mpf(x)))
        except Exception:
            return None
        return v.real if math.isfinite(v.real) and abs(v.imag) <= 1e-9 * max(1.0, abs(v.real)) else None

    xs = [lo + (hi - lo) * i / n for i in range(n + 1)]
    ys = [fval(x) for x in xs]
    seeds: list[tuple[float, float] | float] = []
    for i in range(n):
        a, b = ys[i], ys[i + 1]
        if a is None or b is None:
            continue
        if a == 0:
            seeds.append(xs[i])
        elif a * b < 0:
            seeds.append((xs[i], xs[i + 1]))
        elif 0 < i and ys[i - 1] is not None and abs(a) <= abs(ys[i - 1]) and abs(a) <= abs(b):  # type: ignore[arg-type]
            seeds.append(xs[i])  # local minimum of |f|: a tangent (even-multiplicity) root may sit here
    roots: list[sp.Float] = []
    tol = 1e-9
    with mpmath.workdps(30):
        for seed in seeds:
            try:
                if isinstance(seed, tuple):
                    r = mpmath.findroot(f_mp, seed, solver="illinois")
                else:
                    r = mpmath.findroot(f_mp, mpmath.mpf(seed))
                r = complex(r)
            except Exception:
                continue
            if abs(r.imag) > 1e-12 or not (lo - 1e-9 <= r.real <= hi + 1e-9):
                continue
            res = _num(f_expr, {sym: sp.Float(r.real, 30)})
            if res is None or abs(res) > tol * max(1.0, abs(r.real)):
                continue
            if all(abs(float(r.real) - float(q)) > 1e-7 * max(1.0, abs(r.real)) for q in roots):
                roots.append(sp.Float(r.real, 15))
    roots.sort()
    residuals = [float(abs(_num(f_expr, {sym: q}) or 0.0)) for q in roots]
    cid = _canonical_id("axiom_nsolve", {"equation": equation, "variable": sym.name, "interval": [lo, hi], "roots": [str(r) for r in roots]})
    return {
        "equation": str(sp.Eq(lhs, rhs)),
        "variable": sym.name,
        "roots": [str(r) for r in roots],
        "residuals": residuals,
        "interval": [lo, hi],
        "samples": n,
        "method": "sign-change / |f| minimum scan + mpmath.findroot refinement, residual-checked",
        "verified": bool(roots) and all(r <= tol for r in residuals),
        "complete": None,
        "note": "Real roots only; roots outside the interval or closer together than the grid spacing may be missed.",
        "canonical_id": cid,
    }


def _normalize_ode_primes(text: str, func_name: str, var_name: str) -> str:
    """Convert prime notation like y''(x), y'(x), y'', y' into Derivative(y(x), x, n)."""
    f_esc = re.escape(func_name)
    v_esc = re.escape(var_name)

    def _repl_with_arg(match: re.Match[str]) -> str:
        primes = len(match.group(1))
        return f"Derivative({func_name}({var_name}), {var_name}, {primes})" if primes > 1 else f"Derivative({func_name}({var_name}), {var_name})"

    # (?<![A-Za-z_]) rather than \b: "2y" and "3y'" have no word boundary between the coefficient and the name
    out = re.sub(rf"(?<![A-Za-z_]){f_esc}('+)+\s*\(\s*{v_esc}\s*\)", _repl_with_arg, text)

    def _repl_bare_prime(match: re.Match[str]) -> str:
        primes = len(match.group(1))
        return f"Derivative({func_name}({var_name}), {var_name}, {primes})" if primes > 1 else f"Derivative({func_name}({var_name}), {var_name})"

    out = re.sub(rf"(?<![A-Za-z_]){f_esc}('+)+", _repl_bare_prime, out)
    # Also replace bare func_name not followed by '(' with func_name(var_name)
    out = re.sub(rf"(?<![A-Za-z_]){f_esc}\b(?!\s*\()", f"{func_name}({var_name})", out)
    return out


def axiom_dsolve(
    equation: str,
    func: str = "y(x)",
    ics: dict[str, float | int | str] | None = None,
) -> dict[str, Any]:
    """Solve an ordinary differential equation symbolically via sympy.dsolve and verify the solution."""
    func_clean = _check_safe_string(func)
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)$", func_clean)
    if m:
        func_name, var_name = m.group(1), m.group(2)
    else:
        func_name, var_name = func_clean, "x"

    var_sym = sp.Symbol(var_name)
    func_cls = sp.Function(func_name)
    y_of_x = func_cls(var_sym)
    local_env = {var_name: var_sym, func_name: func_cls}

    norm_eq = _normalize_ode_primes(equation, func_name, var_name)
    lhs, rhs, eq_obj = safe_parse_equation(norm_eq, local_dict=local_env)
    if isinstance(eq_obj, sp.Eq) and not eq_obj.has(sp.Derivative):
        # "n = 0" with func s(x) once reached sympy.dsolve and crashed with IndexError; say what is wrong instead.
        raise UnsupportedShapeError(
            f"'{equation[:80]}' is not a differential equation in {func_name}({var_name}): it has no derivative")
    if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
        raise UnsupportedShapeError(
            f"Operation 'dsolve' requires a scalar ODE, got container {type(lhs if isinstance(lhs, (sp.Tuple, tuple, list)) else rhs).__name__}"
        )

    # A decimal in a stated problem ("x(0) = 0.1", "0.3 x'") is exact: solve with rationals so the constants come out
    # as -37/130, not -0.284615384615385.
    if eq_obj.has(sp.Float):
        eq_obj = sp.Eq(sp.nsimplify(eq_obj.lhs, rational=True), sp.nsimplify(eq_obj.rhs, rational=True))
    parsed_ics: dict[Any, Any] | None = None
    if ics:
        parsed_ics = {}
        for k, v in ics.items():
            k_str = str(k).strip()
            v_expr = safe_parse_expr(str(v), local_dict=local_env)
            if v_expr.has(sp.Float):
                v_expr = sp.nsimplify(v_expr, rational=True)
            # Match y(x0), y'(x0), y''(x0)
            m_ic = re.match(rf"^{re.escape(func_name)}('*)\s*\(\s*(.+)\s*\)$", k_str)
            if m_ic:
                primes = len(m_ic.group(1))
                pt_expr = safe_parse_expr(m_ic.group(2), local_dict=local_env)
                if primes == 0:
                    key_expr = func_cls(pt_expr)
                else:
                    key_expr = sp.Derivative(y_of_x, var_sym, primes).subs(var_sym, pt_expr)
                parsed_ics[key_expr] = v_expr
            else:
                key_expr = safe_parse_expr(k_str, local_dict=local_env)
                parsed_ics[key_expr] = v_expr

    sol = sp.dsolve(eq_obj, y_of_x, ics=parsed_ics)
    verified = False
    try:
        chk = sp.checkodesol(eq_obj, sol, func=y_of_x)
        if isinstance(chk, tuple):
            verified = bool(chk[0])
        elif isinstance(chk, list):
            verified = all(bool(item[0]) for item in chk)
    except Exception:
        verified = False

    if isinstance(sol, list):
        sol_str = [str(s) for s in sol]
        rhs_str = [str(s.rhs) if isinstance(s, sp.Equality) else str(s) for s in sol]
        latex_str = ", ".join(sp.latex(s) for s in sol)
    else:
        sol_str = str(sol)
        rhs_str = str(sol.rhs) if isinstance(sol, sp.Equality) else str(sol)
        latex_str = sp.latex(sol)

    cid = _canonical_id(
        "axiom_dsolve",
        {"equation": equation, "func": func, "ics": ics or {}, "solution": sol_str},
    )
    return {
        "equation": str(eq_obj),
        "func": f"{func_name}({var_name})",
        "solution": sol_str,
        "rhs": rhs_str,
        "latex": latex_str,
        "verified": verified,
        "canonical_id": cid,
    }


def axiom_linalg(
    matrix: list[list[float | int | str]],
    operation: Literal["eigen", "det", "inv", "rref", "svd", "nullspace", "charpoly", "solve"],
    rhs: list[float | int | str] | None = None,
) -> dict[str, Any]:
    """Perform exact/symbolic linear algebra operations on a matrix with verification."""
    if not matrix or not all(isinstance(row, list) and len(row) == len(matrix[0]) for row in matrix):
        raise ValueError("Matrix must be a non-empty rectangular 2D list.")

    parsed_rows = [[safe_parse_expr(str(cell)) for cell in row] for row in matrix]
    M = sp.Matrix(parsed_rows)
    rows, cols = M.rows, M.cols
    is_square = rows == cols

    op = str(operation).strip().lower()
    numeric = not M.free_symbols
    det_val: sp.Expr | None = sp.simplify(M.det()) if is_square else None
    det_str: str | None = str(det_val) if det_val is not None else None
    trace_str: str | None = str(sp.simplify(M.trace())) if is_square else None
    rank_val: int = int(M.rank())
    eigen_dict: dict[str, int] | None = None
    # Eigenvalues are a side summary: computed for numeric matrices up to 4x4 or when asked for. A symbolic 4x4
    # goes through the quartic formula and can stall a tool call that only wanted a determinant.
    if is_square and (op in ("eigen", "charpoly") or (numeric and rows <= 4)):
        try:
            eigen_dict = {str(sp.simplify(k)): int(v) for k, v in M.eigenvals().items()}
        except Exception:
            eigen_dict = None

    verified = False
    result_out: Any = None
    latex_out = ""
    free_params: list[str] = []

    if op == "det":
        if not is_square:
            raise ValueError("Determinant requires a square matrix.")
        d = det_val
        result_out = str(d)
        latex_out = sp.latex(d)
        # Independent second algorithm (Berkowitz vs the default Bareiss elimination)
        verified = bool(sp.simplify(M.det(method="berkowitz") - d) == 0)

    elif op == "inv":
        if not is_square:
            raise ValueError("Matrix inverse requires a square matrix.")
        if det_val == 0:
            raise ValueError("Matrix is singular (determinant is 0) and cannot be inverted.")
        inv_M = sp.simplify(M.inv())
        prod = sp.simplify(M * inv_M - sp.eye(rows))
        verified = bool(prod == sp.zeros(rows, cols))
        result_out = [[str(inv_M[i, j]) for j in range(cols)] for i in range(rows)]
        latex_out = sp.latex(inv_M)

    elif op == "eigen":
        if not is_square:
            raise ValueError("Eigenvalue/eigenvector decomposition requires a square matrix.")
        evects = M.eigenvects()
        eig_list: list[dict[str, Any]] = []
        all_ok = True
        for val, mult, basis in evects:
            val_simp = sp.simplify(val)
            vecs_str = []
            for v in basis:
                v_simp = sp.simplify(v)
                vecs_str.append([str(v_simp[i, 0]) for i in range(rows)])
                diff_v = sp.simplify(M * v_simp - val_simp * v_simp)
                if diff_v != sp.zeros(rows, 1):
                    all_ok = False
            eig_list.append({
                "eigenvalue": str(val_simp),
                "multiplicity": int(mult),
                "eigenvectors": vecs_str,
            })
        verified = all_ok
        result_out = eig_list
        latex_out = ", ".join(f"\\lambda = {sp.latex(v)} \\text{{ (mult. {m})}}" for v, m, _ in evects)

    elif op == "rref":
        rref_M, pivots = M.rref()
        result_out = {
            "rref": [[str(sp.simplify(rref_M[i, j])) for j in range(cols)] for i in range(rows)],
            "pivots": [int(p) for p in pivots],
        }
        latex_out = sp.latex(rref_M)
        verified = len(pivots) == rank_val

    elif op == "svd":
        svals = [sp.simplify(s) for s in M.singular_values()]
        result_out = {"singular_values": [str(s) for s in svals]}
        latex_out = sp.latex(svals)
        # sum(sigma_i^2) equals the squared Frobenius norm, trace(M^H M)
        frob = (M.H * M).trace()
        verified = bool(sp.simplify(sp.Add(*[s**2 for s in svals]) - frob) == 0)

    elif op == "nullspace":
        ns = M.nullspace()
        basis_out = []
        all_ok = True
        for v in ns:
            v_simp = sp.simplify(v)
            basis_out.append([str(v_simp[i, 0]) for i in range(cols)])
            if sp.simplify(M * v_simp) != sp.zeros(rows, 1):
                all_ok = False
        result_out = basis_out
        latex_out = sp.latex(ns)
        verified = all_ok

    elif op == "charpoly":
        if not is_square:
            raise ValueError("Characteristic polynomial requires a square matrix.")
        lam = sp.Symbol("lambda")
        cp = M.charpoly(lam)
        cp_expr = sp.expand(cp.as_expr())
        result_out = str(cp_expr)
        latex_out = sp.latex(cp_expr)
        # Cayley-Hamilton: p(M) = 0, plus the trace and determinant coefficients
        coeffs = cp.all_coeffs()
        p_of_m = sp.zeros(rows, rows)
        for c in coeffs:
            p_of_m = p_of_m * M + c * sp.eye(rows)
        verified = bool(
            sp.simplify(p_of_m) == sp.zeros(rows, rows)
            and sp.simplify(coeffs[1] + M.trace()) == 0
            and sp.simplify(coeffs[-1] - (-1) ** rows * det_val) == 0
        )

    elif op == "solve":
        if rhs is None:
            raise ValueError("operation='solve' requires the 'rhs' vector parameter.")
        if len(rhs) != rows:
            raise ValueError(f"RHS vector length ({len(rhs)}) must match matrix row count ({rows}).")
        b_vec = sp.Matrix([safe_parse_expr(str(x)) for x in rhs])
        # Gauss-Jordan handles singular and non-square systems: a unique solution, a parametric family, or none.
        try:
            x_sol, params = M.gauss_jordan_solve(b_vec)
        except ValueError as exc:
            raise ValueError(f"Linear system is inconsistent (no solution): {exc}") from exc
        x_sol = sp.simplify(x_sol)
        residual = sp.simplify(M * x_sol - b_vec)
        verified = bool(residual == sp.zeros(rows, 1))
        result_out = [str(x_sol[i, 0]) for i in range(cols)]
        latex_out = sp.latex(x_sol)
        free_params = [str(t) for t in params]

    else:
        raise ValueError(f"Unsupported linear algebra operation: {operation!r}")

    cid = _canonical_id("axiom_linalg", {"matrix": matrix, "operation": op, "rhs": rhs, "result": result_out})
    return {
        "operation": op,
        "shape": [rows, cols],
        "result": result_out,
        "latex": latex_out,
        "eigenvalues": eigen_dict,
        "determinant": det_str,
        "trace": trace_str,
        "rank": rank_val,
        "verified": verified,
        "free_parameters": free_params,
        "canonical_id": cid,
    }


def _sample_value(sym: sp.Symbol, regime: int, rng: random.Random) -> sp.Basic:
    """A random test value for sym that respects its assumptions. Unconstrained symbols rotate through positive
    reals, negative reals and complex values: an identity that only holds for positive reals (sqrt(x^2) = x,
    log(x*y) = log(x) + log(y)) is not a general identity, and positive-only sampling would wrongly accept it."""
    def r(lo: float, hi: float) -> sp.Rational:
        return sp.Rational(str(round(rng.uniform(lo, hi), 6)))

    if sym.is_integer:
        lo = 1 if sym.is_positive else (0 if sym.is_nonnegative else -6)
        hi = -1 if sym.is_negative else 9
        return sp.Integer(rng.randint(min(lo, hi), max(lo, hi)))
    if sym.is_positive:
        return r(0.25, 2.75)
    if sym.is_nonnegative:
        return r(0.0, 2.75)
    if sym.is_negative:
        return -r(0.25, 2.75)
    if sym.is_real or regime < 2:
        return r(0.25, 2.75) if regime % 2 == 0 else -r(0.25, 2.75)
    return r(-2.0, 2.0) + sp.I * r(-1.5, 1.5)


def _is_symbolic_zero(diff_expr: sp.Expr) -> bool:
    try:
        if sp.expand(diff_expr) == 0 or sp.cancel(diff_expr) == 0:
            return True
        if sp.simplify(diff_expr) == 0:
            return True
        return bool(sp.simplify(sp.trigsimp(sp.expand_trig(diff_expr))) == 0)
    except Exception:
        return False


def axiom_verify_identity(
    lhs: str,
    rhs: str,
    variables: list[str] | None = None,
    num_points: int = 8,
    assumptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Verify whether lhs == rhs symbolically and at random points (positive, negative and complex values unless
    assumptions restrict a symbol's domain)."""
    lhs_expr = safe_parse_expr(lhs, assumptions=assumptions)
    rhs_expr = safe_parse_expr(rhs, assumptions=assumptions)

    lhs_is_container = isinstance(lhs_expr, (sp.Tuple, tuple, list))
    rhs_is_container = isinstance(rhs_expr, (sp.Tuple, tuple, list))

    if lhs_is_container or rhs_is_container:
        if not (lhs_is_container and rhs_is_container):
            return {
                "equivalent": False,
                "evidence": "refuted",
                "evidence_detail": "shape mismatch: cannot equate scalar and collection",
                "counterexample": {"error": "shape mismatch: container vs scalar"},
                "counterexample_regime": None,
                "max_numeric_error": float("inf"),
                "points_tested": 0,
                "holds_on_positive_reals": False,
                "canonical_id": _canonical_id("axiom_verify_identity", {"lhs": str(lhs), "rhs": str(rhs)}),
            }
        if len(lhs_expr) != len(rhs_expr):
            return {
                "equivalent": False,
                "evidence": "refuted",
                "evidence_detail": f"shape length mismatch: {len(lhs_expr)} != {len(rhs_expr)}",
                "counterexample": {"error": f"shape length mismatch: {len(lhs_expr)} != {len(rhs_expr)}"},
                "counterexample_regime": None,
                "max_numeric_error": float("inf"),
                "points_tested": 0,
                "holds_on_positive_reals": False,
                "canonical_id": _canonical_id("axiom_verify_identity", {"lhs": str(lhs), "rhs": str(rhs)}),
            }
        for left_item, right_item in zip(lhs_expr, rhs_expr, strict=True):
            sub_res = axiom_verify_identity(str(left_item), str(right_item), assumptions=assumptions, num_points=num_points, variables=variables)
            if not sub_res["equivalent"]:
                return sub_res
        return {
            "equivalent": True,
            "evidence": "symbolic",
            "evidence_detail": "element-wise symbolic equivalence across all container components",
            "counterexample": None,
            "counterexample_regime": None,
            "max_numeric_error": 0.0,
            "points_tested": len(lhs_expr),
            "holds_on_positive_reals": True,
            "canonical_id": _canonical_id("axiom_verify_identity", {"lhs": str(lhs), "rhs": str(rhs)}),
        }

    diff_expr = lhs_expr - rhs_expr
    symbolic_zero = _is_symbolic_zero(diff_expr)

    by_name = {s.name: s for s in (lhs_expr.free_symbols | rhs_expr.free_symbols) if isinstance(s, sp.Symbol)}
    if variables:
        syms = [by_name.get(str(v).strip(), sp.Symbol(str(v).strip())) for v in variables if str(v).strip()]
    else:
        syms = sorted(by_name.values(), key=lambda s: s.name)

    seed_bytes = hashlib.sha256(f"{lhs}=={rhs}".encode()).digest()
    rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))

    max_numeric_error = 0.0
    counterexample: dict[str, Any] | None = None
    counterexample_regime: str | None = None
    positive_failure = False
    tested = 0
    attempts = 0
    target_points = max(3, int(num_points))
    regimes = ("positive reals", "negative reals", "complex")

    if not syms:
        val_l, val_r = _num(lhs_expr, {}), _num(rhs_expr, {})
        if val_l is not None and val_r is not None:
            err = abs(val_l - val_r)
            max_numeric_error = float(err)
            tested = 1
            if err > 1e-8 * max(1.0, abs(val_l), abs(val_r)):
                counterexample = {}
                positive_failure = True
    else:
        while tested < target_points and attempts < target_points * 6:
            regime = attempts % 3
            attempts += 1
            pt = {sym: _sample_value(sym, regime, rng) for sym in syms}
            val_l, val_r = _num(lhs_expr, pt), _num(rhs_expr, pt)
            if val_l is None or val_r is None:
                continue
            tested += 1
            err = abs(val_l - val_r)
            max_numeric_error = max(max_numeric_error, float(err))
            if err > 1e-7 * max(1.0, abs(val_l), abs(val_r)):
                if all(bool(v.is_real) and v > 0 for v in pt.values()):
                    positive_failure = True
                if counterexample is None:
                    counterexample = {
                        s.name: (float(v) if v.is_real else str(sp.nsimplify(v))) for s, v in pt.items()
                    }
                    counterexample_regime = regimes[regime]

    if counterexample is not None:
        equivalent = False
        evidence = "refuted"
    elif symbolic_zero:
        equivalent = True
        evidence = "symbolic"
    else:
        equivalent = bool(tested > 0 and max_numeric_error < 1e-7)
        evidence = "numerical" if equivalent else "inconclusive"

    relation = "=" if equivalent else r"\neq"
    latex_str = f"{sp.latex(lhs_expr)} {relation} {sp.latex(rhs_expr)}"
    cid = _canonical_id(
        "axiom_verify_identity",
        {"lhs": lhs, "rhs": rhs, "assumptions": assumptions or {}, "equivalent": equivalent, "symbolic_zero": symbolic_zero},
    )
    return {
        "lhs": str(lhs_expr),
        "rhs": str(rhs_expr),
        "equivalent": equivalent,
        "symbolic_zero": symbolic_zero,
        # symbolic: exact proof by simplification; numerical: agreement at every sample point only (evidence, not a
        # proof); refuted: a counterexample was found; inconclusive: no sample point could be evaluated.
        "evidence": evidence,
        "holds_on_positive_reals": (not positive_failure) if counterexample is not None else None,
        "max_numeric_error": max_numeric_error,
        "counterexample": counterexample,
        "counterexample_domain": counterexample_regime,
        "points_tested": tested,
        "latex": latex_str,
        "canonical_id": cid,
    }


class AxiomEngine:
    """Object-oriented facade over Axiom symbolic mathematics functions."""

    simplify = staticmethod(axiom_simplify)
    solve = staticmethod(axiom_solve)
    calculus = staticmethod(axiom_calculus)
    dsolve = staticmethod(axiom_dsolve)
    linalg = staticmethod(axiom_linalg)
    nsolve = staticmethod(axiom_nsolve)
    verify_identity = staticmethod(axiom_verify_identity)
    latex = staticmethod(axiom_latex)


AxiomSymbolicEngine = AxiomEngine

__all__ = [
    "AxiomEngine",
    "AxiomSymbolicEngine",
    "TRANSFORMATIONS",
    "axiom_calculus",
    "axiom_dsolve",
    "axiom_latex",
    "axiom_linalg",
    "axiom_nsolve",
    "axiom_simplify",
    "axiom_solve",
    "axiom_verify_identity",
    "safe_parse_equation",
    "safe_parse_expr",
]
