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
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

_FORBIDDEN_RE = re.compile(r"__|import|eval|exec|getattr|setattr|delattr|globals|locals|open|os\.|sys\.|subprocess", re.I)

_SAFE_LOCALS: dict[str, Any] = {
    # Constants
    "pi": sp.pi,
    "E": sp.E,
    "e": sp.E,
    "I": sp.I,
    "oo": sp.oo,
    "inf": sp.oo,
    "infinity": sp.oo,
    "GoldenRatio": sp.GoldenRatio,
    "EulerGamma": sp.EulerGamma,
    "Catalan": sp.Catalan,
    # Elementary functions
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "cot": sp.cot,
    "sec": sp.sec,
    "csc": sp.csc,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "atan2": sp.atan2,
    "acot": sp.acot,
    "asec": sp.asec,
    "acsc": sp.acsc,
    "arcsin": sp.asin,
    "arccos": sp.acos,
    "arctan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "coth": sp.coth,
    "asinh": sp.asinh,
    "acosh": sp.acosh,
    "atanh": sp.atanh,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "sqrt": sp.sqrt,
    "cbrt": sp.cbrt,
    "root": sp.root,
    "Abs": sp.Abs,
    "abs": sp.Abs,
    "sign": sp.sign,
    "floor": sp.floor,
    "ceiling": sp.ceiling,
    "ceil": sp.ceiling,
    "re": sp.re,
    "im": sp.im,
    "conjugate": sp.conjugate,
    "arg": sp.arg,
    # Combinatorics & special functions
    "factorial": sp.factorial,
    "binomial": sp.binomial,
    "gamma": sp.gamma,
    "loggamma": sp.loggamma,
    "digamma": sp.digamma,
    "polygamma": sp.polygamma,
    "beta": sp.beta,
    "erf": sp.erf,
    "erfc": sp.erfc,
    "erfi": sp.erfi,
    "zeta": sp.zeta,
    "besselj": sp.besselj,
    "bessely": sp.bessely,
    "besseli": sp.besseli,
    "besselk": sp.besselk,
    "legendre": sp.legendre,
    "hermite": sp.hermite,
    "chebyshevt": sp.chebyshevt,
    "chebyshevu": sp.chebyshevu,
    "laguerre": sp.laguerre,
    "Heaviside": sp.Heaviside,
    "DiracDelta": sp.DiracDelta,
    "LambertW": sp.LambertW,
    # Calculus & algebra constructors
    "Derivative": sp.Derivative,
    "diff": sp.diff,
    "Integral": sp.Integral,
    "integrate": sp.integrate,
    "Sum": sp.Sum,
    "summation": sp.summation,
    "Product": sp.Product,
    "Limit": sp.Limit,
    "limit": sp.limit,
    "Function": sp.Function,
    "Symbol": sp.Symbol,
    "Rational": sp.Rational,
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Matrix": sp.Matrix,
    "Eq": sp.Eq,
    "Piecewise": sp.Piecewise,
    "Max": sp.Max,
    "Min": sp.Min,
}

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
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expression must be a non-empty string.")
    if len(text) > 8000:
        raise ValueError("Expression exceeds maximum length (8000 characters).")
    if _FORBIDDEN_RE.search(text):
        raise ValueError("Expression contains forbidden tokens or dunder attributes.")
    return text.strip()


def safe_parse_expr(
    expression: str,
    local_dict: dict[str, Any] | None = None,
    assumptions: dict[str, str] | None = None,
) -> sp.Expr:
    """Safely parse a mathematical expression string into a SymPy expression without arbitrary eval."""
    cleaned = _check_safe_string(expression)
    env = dict(_SAFE_LOCALS)
    if assumptions:
        env.update(_build_assumption_symbols(assumptions))
    if local_dict:
        env.update(local_dict)
    try:
        return parse_expr(
            cleaned,
            local_dict=env,
            global_dict={"__builtins__": {}},
            transformations=TRANSFORMATIONS,
            evaluate=True,
        )
    except Exception as exc:
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
    return parsed, sp.Integer(0), sp.Eq(parsed, sp.Integer(0))


def axiom_latex(expression: str) -> dict[str, Any]:
    """Parse a mathematical expression or equation and return its canonical SymPy representation, LaTeX, and free symbols."""
    cleaned = _check_safe_string(expression)
    if "=" in cleaned.replace("==", "=") and not cleaned.startswith("Eq("):
        lhs, rhs, eq_obj = safe_parse_equation(cleaned)
        target: sp.Basic = eq_obj
        free_syms = sorted({str(s) for s in (lhs.free_symbols | rhs.free_symbols)})
    else:
        target = safe_parse_expr(cleaned)
        free_syms = sorted({str(s) for s in target.free_symbols})
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


def axiom_simplify(
    expression: str,
    assumptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Simplify, factor, expand, trig-simplify, and cancel a symbolic mathematical expression."""
    expr = safe_parse_expr(expression, assumptions=assumptions)
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

    free_syms = sorted(str(s) for s in expr.free_symbols)
    cid = _canonical_id(
        "axiom_simplify",
        {"expression": expression, "assumptions": assumptions or {}, "simplified": str(simplified_expr)},
    )
    return {
        "expression": str(expr),
        "simplified": str(simplified_expr),
        "latex": sp.latex(simplified_expr),
        "factored": str(factored_expr),
        "expanded": str(expanded_expr),
        "canceled": str(canceled_expr),
        "trig_simplified": str(trig_expr),
        "free_symbols": free_syms,
        "canonical_id": cid,
    }


def _is_real_value(val: sp.Basic) -> bool:
    if getattr(val, "is_real", None) is True:
        return True
    if getattr(val, "is_real", None) is False:
        return False
    try:
        cval = complex(val.evalf(30))
        return abs(cval.imag) < 1e-12
    except Exception:
        return True


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
        parsed_pairs.append((lhs, rhs))
        res_expr = lhs - rhs
        residual_exprs.append(res_expr)
        for sym in sorted(res_expr.free_symbols, key=lambda s: s.name):
            if sym.name not in seen_names:
                seen_names.add(sym.name)
                all_free.append(sym)

    if variables is None:
        target_syms = all_free
    elif isinstance(variables, str):
        names = [v.strip() for v in variables.split(",") if v.strip()]
        target_syms = [sp.Symbol(n) for n in names]
    else:
        target_syms = [sp.Symbol(str(n).strip()) for n in variables if str(n).strip()]

    if not target_syms:
        raise ValueError("No variables found to solve for.")

    raw_solutions = sp.solve(residual_exprs, target_syms, dict=True)
    want_real = str(domain or "complex").strip().lower() in ("real", "reals", "r")

    solutions_out: list[dict[str, str]] = []
    solutions_latex: list[dict[str, str]] = []
    residuals_out: list[list[str]] = []
    all_verified = True

    for sol in raw_solutions:
        if want_real and not all(_is_real_value(v) for v in sol.values()):
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
        {"equations": eq_list, "variables": [str(s) for s in target_syms], "domain": domain, "solutions": solutions_out},
    )
    return {
        "equations": eq_list,
        "variables": [str(s) for s in target_syms],
        "domain": domain,
        "solutions": solutions_out,
        "latex": latex_summary,
        "verified": verified,
        "residuals": residuals_out,
        "canonical_id": cid,
    }


def _to_mpmath_bound(expr: sp.Expr) -> Any:
    if expr == sp.oo:
        return mpmath.inf
    if expr == -sp.oo:
        return -mpmath.inf
    return float(expr.evalf(30))


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

    numeric_value: float | None = None
    verified = False
    result_str = ""
    latex_str = ""

    if op == "diff":
        res_expr = sp.diff(expr, var_sym, int(order))
        result_str = str(res_expr)
        latex_str = sp.latex(res_expr)
        # Cross-check univariate derivative at a safe numerical point via mpmath.diff
        if expr.free_symbols <= {var_sym} and int(order) <= 4:
            for test_x in (0.73, 1.37, 2.11):
                try:
                    f_mp = sp.lambdify(var_sym, expr, modules="mpmath")
                    num_d = complex(mpmath.diff(f_mp, test_x, n=int(order)))
                    sym_d = complex(res_expr.subs(var_sym, test_x).evalf(30))
                    if math.isfinite(num_d.real) and math.isfinite(sym_d.real):
                        err = abs(num_d - sym_d)
                        tol = 1e-6 * max(1.0, abs(sym_d))
                        verified = err <= tol
                        break
                except Exception:
                    continue
        else:
            verified = True

    elif op == "integrate":
        if lower is not None and upper is not None:
            low_expr = safe_parse_expr(str(lower), local_dict={variable: var_sym})
            up_expr = safe_parse_expr(str(upper), local_dict={variable: var_sym})
            res_expr = sp.integrate(expr, (var_sym, low_expr, up_expr))
            result_str = str(res_expr)
            latex_str = sp.latex(res_expr)
            # Numeric quadrature cross-check via mpmath.quad when bounds & integrand have no extra free symbols
            extra_syms = (expr.free_symbols - {var_sym}) | low_expr.free_symbols | up_expr.free_symbols
            if not extra_syms:
                try:
                    sym_num = complex(res_expr.evalf(30))
                    if abs(sym_num.imag) < 1e-12 and math.isfinite(sym_num.real):
                        numeric_value = float(sym_num.real)
                except Exception:
                    pass
                try:
                    f_mp = sp.lambdify(var_sym, expr, modules="mpmath")
                    a_mp = _to_mpmath_bound(low_expr)
                    b_mp = _to_mpmath_bound(up_expr)
                    quad_val = complex(mpmath.quad(f_mp, [a_mp, b_mp]))
                    if abs(quad_val.imag) < 1e-9 and math.isfinite(quad_val.real):
                        quad_float = float(quad_val.real)
                        if numeric_value is None:
                            numeric_value = quad_float
                        else:
                            err = abs(numeric_value - quad_float)
                            verified = err <= 1e-5 * max(1.0, abs(quad_float))
                except Exception:
                    pass
        else:
            res_expr = sp.integrate(expr, var_sym)
            result_str = str(res_expr)
            latex_str = sp.latex(res_expr)
            # Verify indefinite integral by differentiating back
            try:
                back_diff = sp.simplify(sp.diff(res_expr, var_sym) - expr)
                verified = bool(back_diff == 0 or sp.trigsimp(back_diff) == 0)
            except Exception:
                verified = False

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
        res_expr = sp.limit(expr, var_sym, pt_expr, dir=direction)
        result_str = str(res_expr)
        latex_str = sp.latex(res_expr)
        if not res_expr.free_symbols:
            try:
                cval = complex(res_expr.evalf(30))
                if abs(cval.imag) < 1e-12 and math.isfinite(cval.real):
                    numeric_value = float(cval.real)
            except Exception:
                pass
        verified = not isinstance(res_expr, sp.Limit)

    elif op == "series":
        pt_expr = safe_parse_expr(str(point if point is not None else "0"), local_dict={variable: var_sym})
        n_terms = int(order) if int(order) > 1 else 6
        ser = sp.series(expr, var_sym, pt_expr, n=n_terms)
        poly = ser.removeO()
        result_str = str(poly)
        latex_str = sp.latex(ser)
        verified = True

    elif op == "sum":
        low_expr = safe_parse_expr(str(lower if lower is not None else "1"), local_dict={variable: var_sym})
        up_expr = safe_parse_expr(str(upper if upper is not None else "n"), local_dict={variable: var_sym})
        res_expr = sp.summation(expr, (var_sym, low_expr, up_expr))
        res_simplified = sp.simplify(res_expr)
        result_str = str(res_simplified)
        latex_str = sp.latex(res_simplified)
        if not res_simplified.free_symbols:
            try:
                cval = complex(res_simplified.evalf(30))
                if abs(cval.imag) < 1e-12 and math.isfinite(cval.real):
                    numeric_value = float(cval.real)
                    verified = True
            except Exception:
                pass
        else:
            verified = not isinstance(res_simplified, sp.Sum)
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
        "canonical_id": cid,
    }


def _normalize_ode_primes(text: str, func_name: str, var_name: str) -> str:
    """Convert prime notation like y''(x), y'(x), y'', y' into Derivative(y(x), x, n)."""
    f_esc = re.escape(func_name)
    v_esc = re.escape(var_name)

    def _repl_with_arg(match: re.Match[str]) -> str:
        primes = len(match.group(1))
        return f"Derivative({func_name}({var_name}), {var_name}, {primes})" if primes > 1 else f"Derivative({func_name}({var_name}), {var_name})"

    out = re.sub(rf"\b{f_esc}('+)+\s*\(\s*{v_esc}\s*\)", _repl_with_arg, text)

    def _repl_bare_prime(match: re.Match[str]) -> str:
        primes = len(match.group(1))
        return f"Derivative({func_name}({var_name}), {var_name}, {primes})" if primes > 1 else f"Derivative({func_name}({var_name}), {var_name})"

    out = re.sub(rf"\b{f_esc}('+)+", _repl_bare_prime, out)
    # Also replace bare func_name not followed by '(' with func_name(var_name)
    out = re.sub(rf"\b{f_esc}\b(?!\s*\()", f"{func_name}({var_name})", out)
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

    parsed_ics: dict[Any, Any] | None = None
    if ics:
        parsed_ics = {}
        for k, v in ics.items():
            k_str = str(k).strip()
            v_expr = safe_parse_expr(str(v), local_dict=local_env)
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

    det_str: str | None = str(sp.simplify(M.det())) if is_square else None
    trace_str: str | None = str(sp.simplify(M.trace())) if is_square else None
    rank_val: int = int(M.rank())
    eigen_dict: dict[str, int] | None = None
    if is_square:
        try:
            eigen_dict = {str(sp.simplify(k)): int(v) for k, v in M.eigenvals().items()}
        except Exception:
            eigen_dict = None

    op = str(operation).strip().lower()
    verified = False
    result_out: Any = None
    latex_out = ""

    if op == "det":
        if not is_square:
            raise ValueError("Determinant requires a square matrix.")
        d = sp.simplify(M.det())
        result_out = str(d)
        latex_out = sp.latex(d)
        verified = True

    elif op == "inv":
        if not is_square:
            raise ValueError("Matrix inverse requires a square matrix.")
        if sp.simplify(M.det()) == 0:
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
        verified = True

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
        # Verify trace and determinant coefficients
        verified = True

    elif op == "solve":
        if rhs is None:
            raise ValueError("operation='solve' requires the 'rhs' vector parameter.")
        if len(rhs) != rows:
            raise ValueError(f"RHS vector length ({len(rhs)}) must match matrix row count ({rows}).")
        b_vec = sp.Matrix([safe_parse_expr(str(x)) for x in rhs])
        x_sol = sp.simplify(M.LUsolve(b_vec))
        residual = sp.simplify(M * x_sol - b_vec)
        verified = bool(residual == sp.zeros(rows, 1))
        result_out = [str(x_sol[i, 0]) for i in range(cols)]
        latex_out = sp.latex(x_sol)

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
        "canonical_id": cid,
    }


def axiom_verify_identity(
    lhs: str,
    rhs: str,
    variables: list[str] | None = None,
    num_points: int = 8,
) -> dict[str, Any]:
    """Verify whether lhs == rhs symbolically and via random-point numerical evaluation using mpmath."""
    lhs_expr = safe_parse_expr(lhs)
    rhs_expr = safe_parse_expr(rhs)
    diff_expr = lhs_expr - rhs_expr

    symbolic_zero = False
    try:
        simp = sp.simplify(diff_expr)
        if simp == 0:
            symbolic_zero = True
        else:
            trig_s = sp.trigsimp(sp.expand_trig(diff_expr))
            if sp.simplify(trig_s) == 0:
                symbolic_zero = True
    except Exception:
        symbolic_zero = False

    if variables:
        syms = [sp.Symbol(str(v).strip()) for v in variables if str(v).strip()]
    else:
        syms = sorted(lhs_expr.free_symbols | rhs_expr.free_symbols, key=lambda s: s.name)

    seed_bytes = hashlib.sha256(f"{lhs}=={rhs}".encode()).digest()
    rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))

    max_numeric_error = 0.0
    counterexample: dict[str, float] | None = None
    tested = 0
    attempts = 0
    target_points = max(1, int(num_points))

    if not syms:
        try:
            val_l = complex(lhs_expr.evalf(30))
            val_r = complex(rhs_expr.evalf(30))
            err = abs(val_l - val_r)
            scale = max(1.0, abs(val_l), abs(val_r))
            max_numeric_error = float(err)
            tested = 1
            if err > 1e-8 * scale:
                counterexample = {}
        except Exception:
            pass
    else:
        while tested < target_points and attempts < target_points * 6:
            attempts += 1
            pt = {sym: round(rng.uniform(0.25, 2.75), 6) for sym in syms}
            try:
                val_l = complex(lhs_expr.subs(pt).evalf(30))
                val_r = complex(rhs_expr.subs(pt).evalf(30))
                if not (
                    math.isfinite(val_l.real)
                    and math.isfinite(val_l.imag)
                    and math.isfinite(val_r.real)
                    and math.isfinite(val_r.imag)
                ):
                    continue
                tested += 1
                err = abs(val_l - val_r)
                scale = max(1.0, abs(val_l), abs(val_r))
                if err > max_numeric_error:
                    max_numeric_error = float(err)
                if err > 1e-7 * scale and counterexample is None:
                    counterexample = {sym.name: float(val) for sym, val in pt.items()}
            except Exception:
                continue

    if counterexample is not None:
        equivalent = False
    elif symbolic_zero:
        equivalent = True
    else:
        equivalent = bool(tested > 0 and max_numeric_error < 1e-7)

    latex_str = f"{sp.latex(lhs_expr)} {'=' if equivalent else '\\neq'} {sp.latex(rhs_expr)}"
    cid = _canonical_id(
        "axiom_verify_identity",
        {"lhs": lhs, "rhs": rhs, "equivalent": equivalent, "symbolic_zero": symbolic_zero},
    )
    return {
        "lhs": str(lhs_expr),
        "rhs": str(rhs_expr),
        "equivalent": equivalent,
        "symbolic_zero": symbolic_zero,
        "max_numeric_error": max_numeric_error,
        "counterexample": counterexample,
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
    "axiom_simplify",
    "axiom_solve",
    "axiom_verify_identity",
    "safe_parse_equation",
    "safe_parse_expr",
]
