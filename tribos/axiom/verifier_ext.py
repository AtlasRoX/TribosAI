"""
Verification for the extended task kinds (optimize, inequality, tangent, number theory, recurrence, transform, vector
calculus, probability, statistics) and for numerical quadrature of integrals without a closed form.

Same two levels as verifier.py:
- level 1, alignment: the tool call must equal the call derived from the parsed problem (expected_call), compared
  semantically (equivalent expressions, equal numbers), so a model-written call that changes the problem is caught;
- level 2, independent check: the matching check_* function (analysis.py / discrete.py) re-run on the ORIGINAL
  problem's inputs against the tool's result: dense sampling, interval membership, finite differences, the defining
  transform integral, integer arithmetic, direct iteration, SciPy, textbook formulas.

expected_call is also the rule policy's routing for these kinds, so the action and its check share one definition.
"""

from __future__ import annotations

from typing import Any

import sympy as sp

from . import analysis as A
from . import discrete as D
from . import engine as E
from .problem import ProblemSpec
from .verifier import Check, Verdict, _equivalent, _expr, _finish

EXT_TOOLS: dict[str, str] = {
    "optimize": "axiom_optimize",
    "inequality": "axiom_inequality",
    "tangent": "axiom_tangent",
    "number_theory": "axiom_number_theory",
    "recurrence": "axiom_recurrence",
    "transform": "axiom_transform",
    "vector_calculus": "axiom_vector_calculus",
    "probability": "axiom_probability",
    "statistics": "calcula_statistics",
}
TOOL_KIND = {tool: kind for kind, tool in EXT_TOOLS.items()}
_EXPR_KEYS = frozenset({"expression", "inequality", "recurrence"})


def expected_call(spec: ProblemSpec) -> tuple[str, dict[str, Any]] | None:
    """The tool call that encodes the parsed problem exactly."""
    k, p = spec.kind, spec.params
    if k == "optimize":
        args = {"expression": spec.expression, "variable": spec.variable or "x", "lower": spec.lower, "upper": spec.upper,
                "lower_open": p.get("lower_open", False), "upper_open": p.get("upper_open", False)}
    elif k == "inequality":
        args = {"inequality": spec.expression, "variable": spec.variable}
    elif k == "tangent":
        args = {"expression": spec.expression, "point": p.get("point") or spec.point, "variable": spec.variable or "x"}
    elif k == "number_theory":
        args = {"operation": p["operation"], "numbers": p["numbers"], "modulus": p.get("modulus")}
    elif k == "recurrence":
        args = {"recurrence": p["recurrence"], "initial": p["initial"], "function": p.get("function", "a"), "variable": p.get("variable", "n")}
    elif k == "transform":
        args = {"expression": spec.expression, "transform": p["transform"]}
    elif k == "vector_calculus":
        args = {key: p[key] for key in ("operation", "expression", "components", "variables") if p.get(key) is not None}
    elif k == "probability":
        args = dict(p)
    elif k == "statistics":
        args = {key: p[key] for key in ("operation", "data", "data2", "mu0", "confidence") if key in p}
    else:
        return None
    return EXT_TOOLS[k], {key: v for key, v in args.items() if v is not None}


def spec_from_args(kind: str, text: str, args: dict[str, Any]) -> ProblemSpec:
    """A problem rebuilt from a tool call, for checking model-chosen calls on an unparsed question (no alignment)."""
    spec = ProblemSpec(text=text, kind=kind)  # type: ignore[arg-type]
    spec.expression = args.get("expression") or args.get("inequality") or args.get("recurrence")
    spec.variable, spec.lower, spec.upper = args.get("variable"), args.get("lower"), args.get("upper")
    spec.point = args.get("point")
    spec.params = dict(args)
    return spec


def _same_value(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return False
        norm = lambda d: {str(k).replace(" ", ""): v for k, v in d.items()}  # noqa: E731
        da, db = norm(a), norm(b)
        return da.keys() == db.keys() and all(_same_value(da[k], db[k]) for k in da)
    try:
        ea, eb = _expr(str(a)), _expr(str(b))
        return bool(ea == eb or sp.simplify(ea - eb) == 0)
    except Exception:  # noqa: BLE001
        return str(a).strip().lower() == str(b).strip().lower()


def _same_expression(key: str, a: Any, b: Any) -> bool:
    try:
        if key == "inequality":
            ra, _ = A.parse_inequality(str(a))
            rb, _ = A.parse_inequality(str(b))
            same_op = type(ra) is type(rb)
            flipped = {sp.StrictLessThan: sp.StrictGreaterThan, sp.LessThan: sp.GreaterThan}
            flip_op = flipped.get(type(ra)) is type(rb) or flipped.get(type(rb)) is type(ra)
            da, db = ra.lhs - ra.rhs, rb.lhs - rb.rhs
            if same_op:
                return bool(_equivalent(da, db))
            return bool(flip_op and _equivalent(da, -db))
        if key == "recurrence":
            la, ra_, _ = E.safe_parse_equation(str(a), local_dict={"a": sp.Function("a"), "n": sp.Symbol("n")})
            lb, rb_, _ = E.safe_parse_equation(str(b), local_dict={"a": sp.Function("a"), "n": sp.Symbol("n")})
            return bool(_equivalent(la - ra_, lb - rb_) or _equivalent(la - ra_, rb_ - lb))
        return bool(_equivalent(_expr(str(a)), _expr(str(b))))
    except Exception:  # noqa: BLE001
        return str(a).replace(" ", "") == str(b).replace(" ", "")


def alignment(spec: ProblemSpec, tool: str, args: dict[str, Any]) -> Check:
    exp = expected_call(spec)
    if exp is None:
        return Check("tool call matches the problem", None, 1, "no expected call")
    want_tool, want = exp
    if tool != want_tool:
        return Check("tool call matches the problem", False, 1, f"{tool} used, {want_tool} needed")
    defaults = {"lower_open": False, "upper_open": False, "lower_inclusive": True, "upper_inclusive": True, "mu0": 0.0, "confidence": 0.95}
    bad = []
    for key, value in want.items():
        got = args.get(key, defaults.get(key))
        ok = _same_expression(key, got, value) if key in _EXPR_KEYS else _same_value(got, value)
        if not ok:
            bad.append(f"{key}: {got!r} (problem: {value!r})")
    for key in set(args) - set(want):
        if args[key] not in (None, defaults.get(key)) and key not in ("variable", "function", "variables", "transform_variable"):
            bad.append(f"{key}: {args[key]!r} not in the problem")
    return Check("tool call matches the problem", not bad, 1, "; ".join(bad)[:400])


# Per-kind independent checks and answers ----------------------------------------------------------------------

def _pretty_set(s: sp.Set) -> str:
    def iv(i: sp.Basic) -> str:
        if isinstance(i, sp.Interval):
            return f"{'(' if i.left_open else '['}{i.start}, {i.end}{')' if i.right_open else ']'}"
        if isinstance(i, sp.FiniteSet):
            return "{" + ", ".join(map(str, i)) + "}"
        return str(i)

    if s is sp.S.EmptySet:
        return "no solutions"
    return " ∪ ".join(iv(p) for p in (s.args if isinstance(s, sp.Union) else (s,)))


def _ext_check(spec: ProblemSpec, tool: str, data: dict[str, Any]) -> tuple[Check, dict[str, Any], list[str]]:
    k, p = spec.kind, spec.params
    unc: list[str] = []
    if k == "optimize":
        x = sp.Symbol(spec.variable or "x", real=True)
        f = E.safe_parse_expr(spec.expression or "", local_dict={x.name: x})
        lo = E.safe_parse_expr(spec.lower) if spec.lower is not None else -sp.oo
        hi = E.safe_parse_expr(spec.upper) if spec.upper is not None else sp.oo
        domain = sp.Interval(lo, hi, p.get("lower_open", False) or not lo.is_finite, p.get("upper_open", False) or not hi.is_finite)
        ok = A.check_optimize(f, x, domain, data["maximum"], data["minimum"])
        goal = p.get("goal", "both")
        parts = []
        for name in (("maximum",) if goal == "max" else ("minimum",) if goal == "min" else ("maximum", "minimum")):
            ext = data[name]
            if ext.get("unbounded"):
                parts.append(f"no {name}: f is unbounded {'above' if name == 'maximum' else 'below'} ({name[:3]} = {ext['value']})")
            elif not ext.get("attained"):
                parts.append(f"{name} {ext['value']} is approached but not attained")
            else:
                parts.append(f"{name} = {ext['value']} at {spec.variable or 'x'} = {', '.join(ext['at'])}")
        if data.get("critical_points_exact") is False:
            unc.append("critical points were located numerically")
        answer = {"text": "; ".join(parts), "maximum": data["maximum"], "minimum": data["minimum"], "interval": str(domain)}
        return Check("global extrema confirmed by dense sampling of the original function", ok, 2), answer, unc
    if k == "inequality":
        rel, x = A.parse_inequality(spec.expression or "", spec.variable)
        sol = sp.sympify(data["solution_set"], locals={x.name: x})  # engine-generated set expression
        ok = A.check_inequality(rel, x, sol)
        return Check("solution set matches the inequality at sampled points", ok, 2), {"text": _pretty_set(sol), "solution_set": str(sol), "latex": sp.latex(sol)}, unc
    if k == "tangent":
        x = sp.Symbol(spec.variable or "x", real=True)
        f = E.safe_parse_expr(spec.expression or "", local_dict={x.name: x})
        a = E.safe_parse_expr(str(p.get("point") or spec.point))
        slope = E.safe_parse_expr(str(data["slope"]))
        line = E.safe_parse_expr(str(data["tangent_line"]).split("=", 1)[1], local_dict={x.name: x})
        ok = A.check_tangent(f, x, a, slope) and sp.simplify(line - (f.subs(x, a) + slope * (x - a))) == 0
        want = p.get("want", "line")
        text = {"slope": f"{data['slope']}", "normal": data["normal_line"]}.get(want, f"{data['tangent_line']} (slope {data['slope']})")
        return Check("slope matches a numerical derivative of the original function", ok, 2), {"text": text, "slope": data["slope"], "tangent_line": data["tangent_line"], "latex": data.get("latex", "")}, unc
    if k == "number_theory":
        nums = [D._int(v) for v in p["numbers"]]
        ok = D.check_number_theory(p["operation"], nums, p.get("modulus"), data["result"])
        return Check("re-checked with independent integer arithmetic", ok, 2), {"text": data["text"], "result": data["result"]}, unc
    if k == "recurrence":
        fname, vname = p.get("function", "a"), p.get("variable", "n")
        n, fn = sp.Symbol(vname, integer=True), sp.Function(fname)
        lhs, rhs, _ = E.safe_parse_equation(p["recurrence"], local_dict={vname: n, fname: fn})
        ics = {fn(E.safe_parse_expr(key.strip()[len(fname):].strip("() "))): E.safe_parse_expr(str(v)) for key, v in p["initial"].items()}
        terms = D.iterate_recurrence(lhs - rhs, fn, n, ics, 15)
        closed = E.safe_parse_expr(str(data["result"]), local_dict={vname: n})
        ok = D.check_recurrence(closed, n, terms)
        return Check(f"closed form equals {len(terms)} directly iterated terms of the original recurrence", ok, 2), {"text": f"{fname}({vname}) = {data['result']}", "latex": data.get("latex", "")}, unc
    if k == "transform":
        kind = p["transform"]
        if kind in ("laplace", "inverse_laplace"):
            t, s = sp.Symbol("t", positive=True), sp.Symbol("s")
            if kind == "laplace":
                f, F = E.safe_parse_expr(spec.expression or "", local_dict={"t": t}), E.safe_parse_expr(str(data["result"]), local_dict={"s": s})
            else:
                F, f = E.safe_parse_expr(spec.expression or "", local_dict={"s": s}), E.safe_parse_expr(str(data["result"]), local_dict={"t": t})
            ok = A.check_laplace(f, t, F, s, None)
        else:
            x, kk = sp.Symbol("x", real=True), sp.Symbol("k", real=True)
            ok = A.check_fourier(E.safe_parse_expr(spec.expression or "", local_dict={"x": x}), x, E.safe_parse_expr(str(data["result"]), local_dict={"k": kk}), kk)
        return Check("result matches the defining transform integral of the original function", ok, 2), {"text": str(data["result"]), "latex": data.get("latex", "")}, unc
    if k == "vector_calculus":
        names = p.get("variables") or ["x", "y", "z"]
        syms = [sp.Symbol(nm) for nm in names]
        local = {s.name: s for s in syms}
        op = p["operation"]
        field_in: Any = E.safe_parse_expr(p["expression"], local_dict=local) if p.get("expression") else [E.safe_parse_expr(c, local_dict=local) for c in p["components"]]
        res = data["result"]
        res_expr: Any = sp.Matrix([[E.safe_parse_expr(c, local_dict=local) for c in row] for row in res]) if isinstance(res, list) and res and isinstance(res[0], list) else (
            sp.Matrix([E.safe_parse_expr(c, local_dict=local) for c in res]) if isinstance(res, list) else E.safe_parse_expr(str(res), local_dict=local))
        ok = A.check_vector_calculus(op, field_in, syms, res_expr)
        return Check("every partial derivative matches finite differences of the original field", ok, 2), {"text": str(res), "result": res, "latex": data.get("latex", "")}, unc
    if k == "probability":
        params = [float(E.safe_parse_expr(str(v))) for v in p["parameters"]]
        lo = E.safe_parse_expr(str(p["lower"])) if p.get("lower") is not None else None
        hi = E.safe_parse_expr(str(p["upper"])) if p.get("upper") is not None else None
        ref = D.check_probability(p["distribution"], params, p["query"], lo, hi, p.get("lower_inclusive", True), p.get("upper_inclusive", True), p.get("value"))
        got = data.get("numeric_value")
        ok = ref is not None and got is not None and abs(float(got) - ref) <= 1e-9 * max(1.0, abs(ref))
        text = str(data["result"]) + (f" ≈ {float(got):.10g}" if got is not None and str(data["result"]) != f"{float(got):.12g}" else "")
        return Check("matches an independent SciPy computation", ok, 2), {"text": text, "value": got}, unc
    if k == "statistics":
        res = data["result"]
        ok = D.check_statistics(p["operation"], [float(v) for v in p["data"]], [float(v) for v in p["data2"]] if p.get("data2") else None,
                                float(p.get("mu0", 0.0)), float(p.get("confidence", 0.95)), res)
        want = p.get("want")
        key = {"standard deviation": "std", "average": "mean"}.get(want or "", want)
        text = f"{want} = {res[key]:.10g}" if key in res else data["text"]
        if want == "standard deviation":
            unc.append("sample standard deviation (n - 1 in the denominator)")
        return Check("textbook formulas agree with SciPy", ok, 2), {"text": text, "result": res}, unc
    raise ValueError(f"no extended verifier for {k}")


def verify_extended(spec: ProblemSpec, tool: str, args: dict[str, Any], data: dict[str, Any], *, check_alignment: bool = True) -> Verdict:
    """check_alignment=False when spec was rebuilt from the call itself (unparsed question): comparing a call with
    itself proves nothing, so no level-1 pass is recorded and the answer can be at most partially verified."""
    checks: list[Check] = []
    if check_alignment:
        checks.append(alignment(spec, tool, args))
    if any(c.passed is False for c in checks):
        return _finish(checks, [], {"text": str(data.get("text") or data.get("result") or "")[:300]})
    check, answer, unc = _ext_check(spec, tool, data)
    checks.append(check)
    return _finish(checks, unc, answer)


def verify_nintegrate(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    """A quadrature value for an integral with no closed form: aligned with the problem and re-integrated from the
    original integrand; reported as partially verified because no exact value exists to compare against."""
    checks: list[Check] = []
    var = sp.Symbol(spec.variable or args.get("variable") or "x")
    original = E.safe_parse_expr(spec.expression or str(args.get("expression")), local_dict={var.name: var})
    lo = E.safe_parse_expr(str(spec.lower if spec.lower is not None else args.get("lower")))
    hi = E.safe_parse_expr(str(spec.upper if spec.upper is not None else args.get("upper")))
    if spec.expression:
        same = bool(_equivalent(E.safe_parse_expr(str(args.get("expression")), local_dict={var.name: var}), original))
        same = same and _same_value(args.get("lower"), spec.lower) and _same_value(args.get("upper"), spec.upper)
        checks.append(Check("integrand and bounds match the problem", same, 1))
    q = E._quad(original, var, lo, hi)
    value = data.get("value")
    ok = q is not None and value is not None and abs(q - complex(value)) <= 1e-8 * max(1.0, abs(q))
    checks.append(Check("re-integrated from the original integrand", ok, 2, f"mpmath.quad = {q}"))
    unc = [f"numerical value (no closed form found); two quadrature rules agree, error estimate {data.get('error_estimate', 0):.1e}"]
    return _finish(checks, unc, {"text": str(data.get("result")), "value": value, "numeric": True}, complete=False)


__all__ = ["EXT_TOOLS", "TOOL_KIND", "alignment", "expected_call", "spec_from_args", "verify_extended", "verify_nintegrate"]
