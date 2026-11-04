"""
Independent verifier for the mathematics agent.

The verifier never trusts the agent's own arguments or the tool's own `verified` flag. It re-parses the ORIGINAL
problem (ProblemSpec) and checks a candidate answer against it at increasing evidence levels:

    level 0  execution            the tool ran and returned a result
    level 1  semantic alignment   the tool's arguments encode the problem that was asked (same equation up to a
                                  nonzero factor, same integrand and bounds, same matrix and operation, ...)
    level 2  independent check    the answer satisfies the original problem by a second method (substitution,
                                  differentiation, quadrature, numeric limits, Cayley-Hamilton, ...)

A computation can execute perfectly and still answer the wrong question; level 1 is what catches that, and level 2
is what catches a wrong answer to the right question. The verdict separates "verified" (aligned and
independently checked, nothing known to be missing) from "partially_verified" (checked, but alignment could not be
established or the result is known to be incomplete, e.g. a periodic root family) from "unverified" and
"refuted". Every gap is listed in `uncertainty` so the final answer can say what was and was not checked.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import sympy as sp

from . import engine as E
from .problem import ProblemSpec
from .shapes import UnsupportedShapeError

Status = Literal["verified", "partially_verified", "unverified", "refuted"]

# Tool (and operation) that produces the final answer for each task kind.
ANSWER_TOOLS: dict[str, tuple[str, ...]] = {
    "solve": ("axiom_solve", "axiom_nsolve"),
    "simplify": ("axiom_simplify",),
    "evaluate": ("axiom_simplify",),
    "differentiate": ("axiom_calculus",),
    "integrate": ("axiom_calculus", "axiom_nintegrate"),
    "limit": ("axiom_calculus",),
    "series": ("axiom_calculus",),
    "sum": ("axiom_calculus",),
    "ode": ("axiom_dsolve",),
    "linalg": ("axiom_linalg",),
    "identity": ("axiom_verify_identity",),
    "optimize": ("axiom_optimize",),
    "inequality": ("axiom_inequality",),
    "tangent": ("axiom_tangent",),
    "number_theory": ("axiom_number_theory",),
    "recurrence": ("axiom_recurrence",),
    "transform": ("axiom_transform",),
    "vector_calculus": ("axiom_vector_calculus",),
    "probability": ("axiom_probability",),
    "statistics": ("calcula_statistics",),
    "structured": ("axiom_structured",),
}
CALCULUS_OP = {"differentiate": "diff", "integrate": "integrate", "limit": "limit", "series": "series", "sum": "sum"}


@dataclass
class Check:
    name: str
    passed: bool | None  # None: could not be run
    level: int
    detail: str = ""


@dataclass
class Verdict:
    status: Status
    level: int  # highest level with a passing check
    checks: list[Check] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    answer: dict[str, Any] = field(default_factory=dict)  # the checked answer: text, latex, values

    @property
    def sufficient(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answers_problem(spec: ProblemSpec, tool: str, args: dict[str, Any]) -> bool:
    """Is this tool call the kind of call whose result is a final answer to the problem?"""
    if spec.kind not in ANSWER_TOOLS:
        return tool in {t for tools in ANSWER_TOOLS.values() for t in tools}
    if tool not in ANSWER_TOOLS[spec.kind]:
        return False
    if tool == "axiom_calculus":
        return str(args.get("operation", "")).lower() == CALCULUS_OP[spec.kind]
    return True


# Helpers ----------------------------------------------------------------------------------------------------------

def _expr(text: Any, spec: ProblemSpec | None = None, local: dict[str, Any] | None = None) -> sp.Expr:
    return E.safe_parse_expr(str(text), local_dict=local, assumptions=(spec.assumptions or None) if spec else None)


def _by_name(expr: sp.Basic, values: dict[str, sp.Basic]) -> dict[sp.Symbol, sp.Basic]:
    return {s: values[s.name] for s in expr.free_symbols if isinstance(s, sp.Symbol) and s.name in values}


def _same(a: Any, b: Any) -> bool:
    """Two bound / point strings denote the same value (one-sided limit markers "0+" / "0-" must match too)."""
    if a is None or b is None:
        return a is None and b is None
    sa, sb = str(a).strip(), str(b).strip()
    side_a = sa[-1] if len(sa) > 1 and sa[-1] in "+-" else ""
    side_b = sb[-1] if len(sb) > 1 and sb[-1] in "+-" else ""
    if side_a != side_b:
        return False
    sa, sb = (sa[:-1] if side_a else sa), (sb[:-1] if side_b else sb)
    try:
        ea, eb = _expr(sa), _expr(sb)
        return bool(ea == eb or sp.simplify(ea - eb) == 0)
    except Exception:  # noqa: BLE001
        return sa == sb


def _equivalent(a: sp.Expr, b: sp.Expr) -> bool | None:
    """Exact or generic-numeric equivalence; None if neither could decide."""
    a_is_c = isinstance(a, (sp.Tuple, tuple, list))
    b_is_c = isinstance(b, (sp.Tuple, tuple, list))
    if a_is_c or b_is_c:
        if not (a_is_c and b_is_c) or len(a) != len(b):
            return False
        results = [_equivalent(item_a, item_b) for item_a, item_b in zip(a, b, strict=True)]
        if all(r is True for r in results):
            return True
        if any(r is False for r in results):
            return False
        return None
    try:
        ok, method = E._zero_check(a - b, "equivalence")
        if ok:
            return True
        return False if method.startswith("numeric counterexample") or method.startswith("symbolic") else None
    except Exception:
        return False


def _proportional(a: sp.Expr, b: sp.Expr) -> bool:
    """a = c*b for a nonzero constant c (the same equation written with a different scale or sign)."""
    if b == 0:
        return a == 0
    try:
        ratio = sp.simplify(sp.cancel(a / b))
        if not ratio.free_symbols and ratio != 0 and ratio.is_finite is not False:
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(_equivalent(a, b))


def _residual(eq_text: str, spec: ProblemSpec) -> sp.Expr:
    lhs, rhs, _ = E.safe_parse_equation(eq_text, assumptions=spec.assumptions or None)
    if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
        if not (isinstance(lhs, (sp.Tuple, tuple, list)) and isinstance(rhs, (sp.Tuple, tuple, list))):
            raise UnsupportedShapeError("Shape mismatch in equation: cannot equate container to scalar")
        if len(lhs) != len(rhs):
            raise UnsupportedShapeError(f"Shape length mismatch in equation: {len(lhs)} != {len(rhs)}")
        return sum((l - r) ** 2 for l, r in zip(lhs, rhs, strict=True))
    try:
        return lhs - rhs
    except TypeError as exc:
        raise UnsupportedShapeError(f"Cannot form residual: {exc}") from exc


def _num_zero(expr: sp.Expr, scale: float = 1.0) -> bool | None:
    try:
        if sp.simplify(expr) == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    val = E._num(expr, {})
    if val is None:
        return None
    return abs(val) <= 1e-9 * max(1.0, scale)


def _finish(checks: list[Check], uncertainty: list[str], answer: dict[str, Any], *, complete: bool = True) -> Verdict:
    failed = [c for c in checks if c.passed is False and c.level >= 1]
    passed_levels = [c.level for c in checks if c.passed]
    level = max(passed_levels, default=-1)
    aligned = any(c.passed for c in checks if c.level == 1)
    independent = any(c.passed for c in checks if c.level == 2)
    undefined = str((answer or {}).get("text", "")).strip().lower() in ("nan", "zoo", "complex infinity")
    if failed:
        status: Status = "refuted"
    elif undefined:
        # An undefined result (e.g. a divergent integral evaluated to NaN) is never partially verified (AUDIT-014).
        status = "unverified"
        uncertainty.append("the result is undefined (NaN): the quantity may diverge or not exist as posed")
    elif independent and aligned and complete:
        status = "verified"
    elif independent or (aligned and level >= 1):
        status = "partially_verified"
    else:
        status = "unverified"
    if not aligned and not failed:
        uncertainty.append("the tool call could not be matched against the original problem statement")
    if not independent and not failed:
        uncertainty.append("no independent check of the result was possible")
    return Verdict(status=status, level=level, checks=checks, uncertainty=uncertainty, answer=answer)


# Per-kind verification ----------------------------------------------------------------------------------------------

def _verify_solve(spec: ProblemSpec, tool: str, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    unc: list[str] = []
    from .correspondence import check_task_correspondence

    corr_ok, corr_detail, _ = check_task_correspondence(spec, tool, args, data)
    checks.append(Check("correspondence to original task", corr_ok, 1, corr_detail))
    if not corr_ok:
        unc.append(f"correspondence failed: {corr_detail}")

    problem_eqs = spec.equations or ([spec.expression] if spec.expression else [])
    tool_eqs = args.get("equations") or args.get("equation")
    tool_eqs = [tool_eqs] if isinstance(tool_eqs, str) else list(tool_eqs or [])
    originals = [_residual(e, spec) for e in problem_eqs] if problem_eqs else [_residual(e, spec) for e in tool_eqs]

    if problem_eqs:
        tool_res = [_residual(e, spec) for e in tool_eqs]
        aligned = len(tool_res) == len(originals) and all(any(_proportional(t, o) for t in tool_res) for o in originals)
        checks.append(Check("equations match the problem", aligned, 1, "" if aligned else f"tool solved {tool_eqs}, problem is {problem_eqs}"))
        if spec.domain == "real" and tool == "axiom_solve" and str(args.get("domain", "complex")).lower() not in ("real", "reals", "r"):
            unc.append("solved over the complex numbers for a real-valued question; non-real roots were discarded")

    if tool == "axiom_nsolve":
        var = str(data.get("variable") or spec.variable or "x")
        sols = [{var: str(r)} for r in data.get("roots") or []]
    else:
        sols = [dict(s) for s in data.get("solutions") or []]

    admissible: list[dict[str, str]] = []
    rejected: list[str] = []
    all_satisfy = True
    for sol in sols:
        try:
            values = {k: _expr(v) for k, v in sol.items()}
        except ValueError:
            all_satisfy = False
            continue
        ok_all = True
        for res in originals:
            scale = 1.0
            zero = _num_zero(res.subs(_by_name(res, values)), scale)
            if zero is not True:
                ok_all = False
        if not ok_all:
            all_satisfy = False
            rejected.append(f"{sol} does not satisfy the original equation(s)")
            continue
        reasons = []
        for name, val in values.items():
            if spec.domain == "real" and not E._is_real_value(val):
                reasons.append(f"{name} = {val} is not real")
            flag = spec.assumptions.get(name, "")
            num = E._num(val, {})
            if num is not None and "positive" in flag and not (abs(num.imag) < 1e-12 and num.real > 0):
                reasons.append(f"{name} = {val} violates {name} > 0")
            if num is not None and "nonnegative" in flag and not (abs(num.imag) < 1e-12 and num.real >= 0):
                reasons.append(f"{name} = {val} violates {name} >= 0")
            if "integer" in flag and val.is_integer is False:
                reasons.append(f"{name} = {val} is not an integer")
        if reasons:
            rejected.append("; ".join(reasons))
        else:
            admissible.append(sol)

    if sols:
        checks.append(Check(
            "each solution satisfies the original equation(s) by substitution",
            all_satisfy, 2, f"{len(sols)} candidate(s) substituted" + ("" if all_satisfy else f"; {len(sols) - len(admissible)} failed"),
        ))
    if rejected and all_satisfy:
        checks.append(Check("domain and constraints", True, 2, "discarded: " + "; ".join(rejected)))

    # Completeness is re-derived from the original equation, never taken from the tool's own `complete` flag: a
    # truncated or fabricated root list must not pass as the whole solution set.
    complete = True
    family: str | None = None
    if tool == "axiom_nsolve":
        complete = False
        lo, hi = (data.get("interval") or [None, None])[:2]
        unc.append(f"numerical scan of [{lo}, {hi}]: roots outside the interval or closely spaced roots may be missing")
    elif len(originals) == 1:
        var = spec.variable or (args.get("variables") if isinstance(args.get("variables"), str) else None) or next(iter(var_names_of(admissible)), None)
        ok, detail, family = _completeness(originals[0], spec, admissible, var)
        claimed = re.sub(r"\s+", "", str(data.get("solution_set") or ""))
        if family and claimed and claimed != re.sub(r"\s+", "", family):
            # Audit I32: the tool's own set must be the re-derived one; a wrong set (ℝ for ℝ ∖ {1}, a missing excluded
            # point or endpoint) is rejected, not silently replaced by the checker's answer.
            checks.append(Check("the tool's solution set equals the set re-derived from the original equation", False, 2,
                                f"tool reported {data.get('solution_set')}; the equation holds exactly on {family}"))
        if family and ok is True:
            checks.append(Check("infinite solution set re-derived independently (identity and excluded points)", True, 2, detail))
        elif family and ok is False:
            checks.append(Check("infinite solution set re-derived independently (identity and excluded points)", False, 2, detail))
        elif family:
            complete = False
            unc.append(f"the solution set is {family}; {detail}")
        elif ok is True:
            checks.append(Check("solution list is complete", True, 2, detail))
        elif ok is False:
            checks.append(Check("solution list is complete", False, 2, detail))
        else:
            complete = False
            unc.append(f"completeness of the solution list could not be established ({detail})")
    elif all_satisfy:
        ok, detail = _system_completeness(originals, admissible, spec)
        checks.append(Check("solution count re-derived from the original system", ok, 2, detail))
        if ok is None:
            complete = False
            unc.append("completeness of the system's solution list could not be established")

    var_names = sorted(var_names_of(admissible))
    # The answer is the solution set itself (audit I31): an empty list of isolated roots next to an infinite family is
    # that family, never "no solutions".
    univariate = len(originals) == 1 and len(var_names) <= 1
    var = (var_names[0] if var_names else spec.variable) or "x"
    full_set: sp.Set | None = None
    if (univariate and tool != "axiom_nsolve" and complete is not False) or family:
        try:
            if family:
                # The infinite set again from the original equation (no parsing of printed sets).
                sym = next(s for s in originals[0].free_symbols if getattr(s, "name", None) == var)
                full_set = sp.solveset(originals[0], sym, domain=_domain_set(spec, var) or sp.S.Complexes)
            else:
                full_set = sp.FiniteSet(*[_expr(s[var]) for s in admissible if var in s])
        except Exception:  # noqa: BLE001 - the text below still states the roots
            full_set = None
    if family:
        text = f"{var} ∈ {pretty_set(full_set)}" if full_set is not None else f"{var} ∈ {family}"
    else:
        text = "; ".join(", ".join(f"{k} = {v}" for k, v in s.items()) for s in admissible) or "no solutions"
    answer = {"text": text, "solutions": admissible, "variables": var_names}
    if full_set is not None:
        answer["set_text"] = pretty_set(full_set)
    if family:
        answer["solution_set"] = family
    return _finish(checks, unc, answer, complete=complete)


def _pretty_value(v: sp.Expr) -> str:
    s = str(sp.sstr(v)).replace("I", "i").replace("sqrt", "√").replace("**", "^").replace("-", "−")
    s = re.sub(r"\*i\b", "i", s).replace("*", "·")
    return s


def pretty_set(s: sp.Set | None) -> str:
    """Mathematical set notation: ∅, {2}, {−i, i}, ℝ ∖ {1}, ℝ, [0, 1)."""
    if s is None:
        return ""
    if s is sp.S.EmptySet:
        return "∅"
    if s is sp.S.Reals:
        return "ℝ"
    if s is sp.S.Complexes:
        return "ℂ"
    if isinstance(s, sp.FiniteSet):
        items = sorted(s, key=lambda v: (float(sp.re(v)), float(sp.im(v))) if v.is_number else (0.0, 0.0))
        return "{" + ", ".join(_pretty_value(v) for v in items) + "}"
    for universe, name in ((sp.S.Reals, "ℝ"), (sp.S.Complexes, "ℂ")):
        try:
            if s.is_subset(universe):
                gaps = sp.Complement(universe, s)
                if isinstance(gaps, sp.FiniteSet):
                    return f"{name} ∖ {pretty_set(gaps)}"
        except Exception:  # noqa: BLE001
            pass
    if isinstance(s, sp.Interval):
        lo = "−∞" if s.start == -sp.oo else _pretty_value(s.start)
        hi = "∞" if s.end == sp.oo else _pretty_value(s.end)
        return f"{'(' if s.left_open else '['}{lo}, {hi}{')' if s.right_open else ']'}"
    if isinstance(s, sp.Union):
        return " ∪ ".join(pretty_set(a) for a in s.args)
    return str(s)


def var_names_of(solutions: list[dict[str, str]]) -> set[str]:
    return {k for s in solutions for k in s}


def _domain_set(spec: ProblemSpec, name: str | None) -> sp.Set | None:
    flag = spec.assumptions.get(name or "", "")
    if "positive" in flag:
        return sp.Interval.open(0, sp.oo)
    if "nonnegative" in flag:
        return sp.Interval(0, sp.oo)
    if "integer" in flag:
        return None
    if str(spec.domain).startswith(("[", "(")):
        # A stated interval ("for x in [0, 2pi)"): the re-derived solution set is restricted to it, as the question asks.
        try:
            interval = E._parse_interval_domain(str(spec.domain))
        except ValueError:
            interval = None
        if interval is not None:
            return interval
    return sp.S.Reals if spec.domain == "real" else sp.S.Complexes


def _distinct(values: list[sp.Expr]) -> list[sp.Expr]:
    out: list[sp.Expr] = []
    for v in values:
        if not any(_equivalent(v, u) for u in out):
            out.append(v)
    return out


def _completeness(res: sp.Expr, spec: ProblemSpec, admissible: list[dict[str, str]], var: str | None) -> tuple[bool | None, str, str | None]:
    """(complete?, detail, general solution set when it is infinite) for one univariate equation."""
    sym = next((s for s in res.free_symbols if getattr(s, "name", None) == var), None)
    if sym is None:
        return None, "unknown variable", None
    domain = _domain_set(spec, var)
    if domain is None:
        return None, "integer domain", None
    found = _distinct([_expr(s[var]) for s in admissible if var in s])
    num, den = sp.fraction(sp.together(res))
    try:
        if num.is_polynomial(sym) and domain in (sp.S.Complexes, sp.S.Reals):
            core = sp.Poly(sp.sqf_part(num), sym)
            if den.has(sym):
                core = sp.quo(core, sp.gcd(core, sp.Poly(den, sym)))
            if domain is sp.S.Complexes:
                expected, how = core.degree(), "degree of the square-free numerator"
            elif not (core.free_symbols - {sym}):
                expected, how = core.count_roots(), "Sturm count of distinct real roots"
            else:
                expected, how = None, ""
            if expected is not None:
                if len(found) == expected:
                    return True, f"{expected} distinct root(s) ({how})", None
                if len(found) < expected:
                    return False, f"{expected} distinct roots exist ({how}), {len(found)} listed", None
    except Exception:  # noqa: BLE001
        pass
    try:
        sset = sp.solveset(res, sym, domain=domain)
    except Exception:  # noqa: BLE001
        return None, "solveset failed", None
    if isinstance(sset, sp.FiniteSet) or sset is sp.S.EmptySet:
        members = list(sset) if isinstance(sset, sp.FiniteSet) else []
        missing = [m for m in members if not any(_equivalent(m, f) for f in found)]
        if not missing:
            return True, f"matches solveset over {domain}", None
        return False, f"missing {missing}", None
    if isinstance(sset, sp.ConditionSet):
        return None, "solveset returned a condition set", None
    # An infinite set is checked without solveset (audit I32): the numerator of the equation over one denominator must
    # vanish identically, and the set must be the domain minus exactly the points where a written denominator is zero.
    ok, detail = _infinite_set_check(res, spec, sym, domain, sset)
    return ok, detail, str(sset)


def _infinite_set_check(res: sp.Expr, spec: ProblemSpec, sym: sp.Symbol, domain: sp.Set, sset: sp.Set) -> tuple[bool | None, str]:
    from .definitions import singular_points

    num, den = sp.fraction(sp.together(res))
    if sp.expand(num) != 0:
        return None, "infinite set reported for an equation that is not an identity: no independent check applies"
    written = spec.expression or ""
    excluded = set(singular_points(written.replace("=", "-(", 1) + ")" if "=" in written else written, sym.name))
    try:
        excluded |= {r for r in sp.solveset(den, sym, domain=domain) if r.is_number} if den.has(sym) else set()
    except Exception:  # noqa: BLE001
        return None, "the denominator's zeros could not be determined"
    expected = sp.Complement(domain, sp.FiniteSet(*excluded)) if excluded else domain
    same = sp.Complement(expected, sset) is sp.S.EmptySet and sp.Complement(sset, expected) is sp.S.EmptySet
    gaps = f" minus {{{', '.join(sp.sstr(e) for e in sorted(excluded, key=lambda v: float(sp.re(v))))}}}" if excluded else ""
    if same:
        return True, f"identity: the numerator over a common denominator is 0, so every point of {domain}{gaps} solves it"
    return False, f"the equation holds on {domain}{gaps}, not on the reported set {sset}"


def _system_completeness(originals: list[sp.Expr], admissible: list[dict[str, str]], spec: ProblemSpec) -> tuple[bool | None, str]:
    names = sorted(var_names_of(admissible)) or sorted({s.name for r in originals for s in r.free_symbols})
    syms = [next((s for r in originals for s in r.free_symbols if s.name == n), sp.Symbol(n)) for n in names]
    try:
        again = sp.solve(originals, syms, dict=True)
    except Exception:  # noqa: BLE001
        return None, "could not re-solve"
    if any(set(map(str, sol)) != set(names) for sol in again):
        return None, "the system has a parametric family of solutions"
    if spec.domain == "real":
        again = [s for s in again if all(E._is_real_value(v) for v in s.values())]
    if len(again) == len(admissible):
        return True, f"{len(again)} solution(s) when re-solved from the original equations"
    return False, f"{len(again)} solution(s) exist, {len(admissible)} listed"


def _verify_expression_tool(spec: ProblemSpec, args: dict[str, Any], arg_key: str = "expression") -> tuple[Check | None, sp.Expr | None]:
    """Level-1 check that the tool operated on the problem's expression; returns (check, original expr)."""
    tool_text = args.get(arg_key)
    if not spec.expression:
        return None, _expr(tool_text) if tool_text else None
    original = _expr(spec.expression, spec)
    if tool_text is None:
        return Check("expression matches the problem", None, 1, "no expression argument"), original
    try:
        same = _equivalent(_expr(tool_text, spec), original)
        if not same and spec.text:
            from .definitions import evaluate, parse_definitions, parse_with_definitions

            defs, _, _ = parse_definitions(spec.text)
            if defs:
                try:
                    orig_eval = evaluate(parse_with_definitions(str(spec.expression), defs), defs)
                    tool_eval = evaluate(parse_with_definitions(str(tool_text), defs), defs)
                    same = bool(_equivalent(tool_eval, orig_eval) or sp.simplify(tool_eval - orig_eval) == 0)
                except Exception:
                    pass
    except ValueError:
        same = False
    return Check("expression matches the problem", same, 1, "" if same else f"tool used {tool_text!r}, problem has {spec.expression!r}"), original


def _verify_calculus(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    unc: list[str] = []
    align, original = _verify_expression_tool(spec, args)
    op = str(args.get("operation") or CALCULUS_OP.get(spec.kind, "")).lower()
    var_name = str(args.get("variable") or spec.variable or "x")
    var = sp.Symbol(var_name)
    if original is None:
        return _finish(checks, ["no expression to check"], {"text": str(data.get("result", ""))})
    original = original.subs({s: var for s in original.free_symbols if getattr(s, "name", None) == var_name})
    if align is not None:
        same_var = spec.variable is None or spec.variable == var_name
        same_bounds = _same(args.get("lower"), spec.lower) and _same(args.get("upper"), spec.upper) if op in ("integrate", "sum") else True
        same_point = (_same(args.get("point"), spec.point) if spec.point is not None else True) if op in ("limit", "series") else True
        same_order = int(args.get("order") or 1) == spec.order if op in ("diff", "series") and spec.kind in ("differentiate", "series") else True
        details = [d for d, ok in (("variable", same_var), ("bounds", same_bounds), ("point", same_point), ("order", same_order)) if not ok]
        if details and align.passed:
            align = Check(align.name, False, 1, "differs from the problem in " + ", ".join(details))
        checks.append(align)

    result_text = str(data.get("result", ""))
    sides = data.get("one_sided")
    if op == "limit" and sides:
        # "The limit does not exist": both one-sided limits re-checked on the original expression, and they differ.
        pt_text = str(spec.point if spec.point is not None else args.get("point", "0")).strip().rstrip("+-") or "0"
        pt = _expr(pt_text, None, {var_name: var})
        left, right = _expr(sides["left"]), _expr(sides["right"])
        ok = left != right and E._check_limit(original, var, pt, "-", left) and E._check_limit(original, var, pt, "+", right)
        checks.append(Check("one-sided limits differ, each checked numerically", ok, 2, f"left {left}, right {right}"))
        return _finish(checks, unc, {"text": result_text, "latex": data.get("latex", ""), "exists": False, "one_sided": sides})
    try:
        result = _expr(result_text, None, {var_name: var})
    except ValueError:
        checks.append(Check("result parses", False, 2, result_text[:200]))
        return _finish(checks, unc, {"text": result_text})
    condition: str | None = None
    if isinstance(result, sp.Piecewise):
        # Convergence-conditioned result: report the principal branch with its condition; the numeric check below
        # pins parameters to values where that condition holds.
        branch, cond = result.args[0]
        if not branch.has(sp.Integral, sp.Limit, sp.Sum) and cond is not sp.false:
            result, condition = branch, str(cond)
            unc_note = f"valid when {cond}"
            if cond is not sp.true:
                unc.append(f"the closed form is {unc_note}")
            result_text = str(branch)
    if result.has(sp.Integral, sp.Limit, sp.Sum):
        # An unevaluated Integral/Limit/Sum restates the question; it is never an answer, however well aligned.
        return Verdict("unverified", 0, checks, [f"the engine returned an unevaluated {op}"], {"text": result_text, "latex": data.get("latex", "")})

    passed: bool | None = None
    detail = ""
    if op == "diff":
        passed = E._check_derivative(original, result, var, int(args.get("order") or spec.order or 1))
        detail = "numerical derivative of the original expression at sample points"
    elif op == "integrate" and args.get("lower") is None:
        passed, detail = E._zero_check(sp.diff(result, var) - original, "derivative of the result equals the original integrand")
    elif op == "integrate":
        low, up = _expr(spec.lower or args.get("lower"), None, {var_name: var}), _expr(spec.upper or args.get("upper"), None, {var_name: var})
        params = E._fix_parameters(original.free_symbols | low.free_symbols | up.free_symbols, var)
        quad = E._quad(original.subs(params), var, low.subs(params), up.subs(params))
        val = E._num(result.subs(params), {})
        if quad is not None and val is not None:
            passed = abs(quad - val) <= 1e-6 * max(1.0, abs(quad))
            detail = f"mpmath.quad of the original integrand = {complex(quad).real:.12g}"
    elif op == "limit":
        pt_text = str(spec.point if spec.point is not None else args.get("point", "0")).strip()
        direction = "+-"
        if len(pt_text) > 1 and pt_text.endswith("+"):
            direction, pt_text = "+", pt_text[:-1]
        elif len(pt_text) > 1 and pt_text.endswith("-") and not pt_text.startswith("-"):
            direction, pt_text = "-", pt_text[:-1]
        passed = E._check_limit(original, var, _expr(pt_text, None, {var_name: var}), direction, result)
        detail = "the original expression evaluated ever closer to the limit point"
    elif op == "series":
        n = int(args.get("order") or spec.order or 6)
        n = n if n > 1 else 6
        passed = E._check_series(original, result, var, _expr(spec.point or args.get("point") or "0"), n)
        detail = f"truncation error of the original expression is O(h^{n})"
    elif op == "sum":
        low, up = _expr(spec.lower or args.get("lower") or "1", None, {var_name: var}), _expr(spec.upper or args.get("upper") or "n", None, {var_name: var})
        passed, detail = E._check_sum(original, var, low, up, result)
    checks.append(Check(f"independent {op} check", passed, 2, detail))
    answer = {"text": result_text, "latex": sp.latex(result) if condition else data.get("latex", ""), "numeric_value": data.get("numeric_value")}
    if condition:
        answer["condition"] = condition
    return _finish(checks, unc, answer)


def _verify_simplify(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    align, original = _verify_expression_tool(spec, args)
    if align is not None:
        checks.append(align)
    # The answer is the form the question asked for ("factor ..." -> factored); that form is what gets checked.
    key = {"factor": "factored", "expand": "expanded"}.get(spec.form, "simplified")
    simplified = str(data.get(key) or data.get("simplified", ""))
    unc: list[str] = []
    if original is not None and simplified:
        ident = E.axiom_verify_identity(str(original), simplified, assumptions=spec.assumptions or args.get("assumptions"))
        if ident["evidence"] == "symbolic":
            checks.append(Check("simplified form equals the original", True, 2, "symbolic"))
        elif ident["evidence"] == "numerical":
            checks.append(Check("simplified form equals the original", True, 2, "numerical agreement at sample points"))
            unc.append("equivalence of the simplified form is numerical, not symbolic")
        elif ident["evidence"] == "refuted":
            # Simplification may be valid only on the problem's domain (assumptions); report, do not accept.
            checks.append(Check("simplified form equals the original", False, 2, f"counterexample {ident['counterexample']}"))
        else:
            checks.append(Check("simplified form equals the original", None, 2, "inconclusive"))
    if spec.kind == "evaluate":
        val = E._num(_expr(simplified), {}) if simplified else None
        answer = {"text": simplified, "latex": data.get("latex", ""), "numeric_value": None if val is None else (val.real if abs(val.imag) < 1e-12 else str(val))}
    else:
        latex = data.get("latex", "") if key == "simplified" else sp.latex(_expr(simplified))
        answer = {"text": simplified, "latex": latex, "form": spec.form, "factored": data.get("factored"), "expanded": data.get("expanded")}
    return _finish(checks, unc, answer)


def _parse_ode(equation: str, func: str) -> tuple[sp.Basic, sp.Expr, sp.Symbol, dict[str, Any]]:
    m = re.match(r"^\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s*\)\s*$", func or "y(x)")
    fname, vname = (m.group(1), m.group(2)) if m else ("y", "x")
    var, fcls = sp.Symbol(vname), sp.Function(fname)
    local = {vname: var, fname: fcls}
    _, _, eq = E.safe_parse_equation(E._normalize_ode_primes(equation, fname, vname), local_dict=local)
    return eq, fcls(var), var, local


def _verify_ode(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    unc: list[str] = []
    func = spec.func or str(args.get("func") or "y(x)")
    eq, y, var, local = _parse_ode(spec.expression or str(args.get("equation")), func)
    if eq.has(sp.Float):
        # A stated decimal ("0.3 x'") is exact, as the solver reads it: a float residual of an exact solution is
        # rounding, not a failed check.
        eq = sp.Eq(sp.nsimplify(eq.lhs, rational=True), sp.nsimplify(eq.rhs, rational=True))
    if spec.expression and args.get("equation"):
        try:
            teq, _, _, _ = _parse_ode(str(args["equation"]), str(args.get("func") or func))
            same = _proportional(teq.lhs - teq.rhs, eq.lhs - eq.rhs)
        except Exception:  # noqa: BLE001
            same = False
        ics_same = {str(k).replace(" ", "") for k in (args.get("ics") or {})} == {k.replace(" ", "") for k in spec.ics}
        checks.append(Check("ODE and initial conditions match the problem", bool(same and ics_same), 1,
                            "" if same and ics_same else "different equation or initial conditions"))
    rhs_list = data.get("rhs")
    rhs_list = [rhs_list] if isinstance(rhs_list, str) else list(rhs_list or [])
    sols = []
    for r in rhs_list:
        try:
            sols.append(sp.Eq(y, _expr(r, None, local)))
        except ValueError:
            pass
    if not sols:
        checks.append(Check("solution parses", False, 2, str(rhs_list)[:200]))
        return _finish(checks, unc, {"text": str(data.get("solution"))})
    ode_ok = True
    for sol in sols:
        try:
            chk = sp.checkodesol(eq, sol, func=y)
            ode_ok = ode_ok and bool(chk[0] if isinstance(chk, tuple) else all(c[0] for c in chk))
        except Exception:  # noqa: BLE001
            ode_ok = False
    checks.append(Check("solution satisfies the original ODE (checkodesol)", ode_ok, 2))
    ics = spec.ics or {str(k): str(v) for k, v in (args.get("ics") or {}).items()}
    if ics:
        ic_ok = True
        for key, val in ics.items():
            m = re.match(r"^\s*[A-Za-z_]\w*('*)\s*\(\s*(.+)\s*\)\s*$", key)
            if not m:
                continue
            target = _expr(val, None, local)
            pt = _expr(m.group(2), None, local)
            for sol in sols:
                got = sp.diff(sol.rhs, var, len(m.group(1))).subs(var, pt) if m.group(1) else sol.rhs.subs(var, pt)
                ic_ok = ic_ok and _num_zero(got - target) is True
        checks.append(Check("initial / boundary conditions hold", ic_ok, 2))
    elif any(re.search(r"\bC\d+\b", str(s.rhs)) for s in sols):
        unc.append("general solution: the integration constants C1, C2, ... are arbitrary")
    text = "; ".join(f"{func} = {s.rhs}" for s in sols)
    return _finish(checks, unc, {"text": text, "latex": data.get("latex", "")})


def _matrix(rows: list[list[Any]]) -> sp.Matrix:
    return sp.Matrix([[_expr(c) for c in row] for row in rows])


def _verify_linalg(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    unc: list[str] = []
    op = str(args.get("operation") or spec.linalg_op or "").lower()
    M = _matrix(spec.matrix or args.get("matrix") or [[0]])
    if spec.matrix is not None:
        try:
            same = _matrix(args.get("matrix") or [[0]]).shape == M.shape and sp.simplify(_matrix(args["matrix"]) - M) == sp.zeros(*M.shape)
        except Exception:  # noqa: BLE001
            same = False
        same_op = spec.linalg_op is None or spec.linalg_op == op
        checks.append(Check("matrix and operation match the problem", bool(same and same_op), 1,
                            "" if same and same_op else f"operation {op} on {args.get('matrix')}"))
    res = data.get("result")
    n = M.rows
    passed: bool | None = None
    text = str(res)
    try:
        if op == "eigen":
            ok, total = True, 0
            parts = []
            for item in res or []:
                lam = _expr(item["eigenvalue"])
                total += int(item["multiplicity"])
                for vec in item["eigenvectors"]:
                    v = sp.Matrix([_expr(c) for c in vec])
                    ok = ok and sp.simplify(M * v - lam * v) == sp.zeros(n, 1) and v != sp.zeros(n, 1)
                parts.append(f"lambda = {item['eigenvalue']} (multiplicity {item['multiplicity']})")
            passed = ok and total == n
            text = "; ".join(parts)
            detail = "M v = lambda v for every eigenpair and multiplicities sum to n"
        elif op == "det":
            passed = sp.simplify(M.det(method="berkowitz") - _expr(res)) == 0
            detail = "Berkowitz determinant of the original matrix"
        elif op == "inv":
            X = _matrix(res)
            passed = sp.simplify(M * X - sp.eye(n)) == sp.zeros(n, n)
            detail = "M * M^-1 = I"
        elif op == "solve":
            x = sp.Matrix([_expr(c) for c in res])
            b = sp.Matrix([_expr(c) for c in (spec.rhs_vector or args.get("rhs") or [])])
            passed = sp.simplify(M * x - b) == sp.zeros(M.rows, 1)
            detail = "residual M x - b = 0"
            if data.get("free_parameters"):
                unc.append(f"infinitely many solutions, parametrised by {', '.join(data['free_parameters'])}")
        elif op == "nullspace":
            vecs = [sp.Matrix([_expr(c) for c in v]) for v in res or []]
            passed = all(sp.simplify(M * v) == sp.zeros(M.rows, 1) for v in vecs) and len(vecs) == M.cols - M.rank()
            detail = "M v = 0 and dim = n - rank"
        elif op == "charpoly":
            lam = sp.Symbol("lambda")  # "lambda" is a Python keyword: rename it before parsing the engine's output
            passed = sp.expand(_expr(re.sub(r"\blambda\b", "lambda_", str(res)), None, {"lambda_": lam}) - M.charpoly(lam).as_expr()) == 0
            detail = "det(lambda I - M) recomputed"
        elif op == "rref":
            ref, _ = M.rref()
            passed = sp.simplify(_matrix(res["rref"]) - ref) == sp.zeros(*M.shape)
            detail = "recomputed reduced row echelon form"
        elif op == "svd":
            mine = sorted(complex(_expr(s).evalf(30)).real for s in res["singular_values"])
            ref = sorted(complex(s.evalf(30)).real for s in M.singular_values())
            passed = len(mine) == len(ref) and all(abs(a - b) <= 1e-9 * max(1.0, abs(b)) for a, b in zip(mine, ref, strict=True))
            detail = "singular values recomputed numerically"
        else:
            detail = "no independent check for this operation"
    except Exception as exc:  # noqa: BLE001
        passed, detail = False, f"result could not be checked: {type(exc).__name__}: {str(exc)[:160]}"
    checks.append(Check(f"independent {op} check", bool(passed) if passed is not None else None, 2, detail))
    return _finish(checks, unc, {"text": text, "latex": data.get("latex", ""), "result": res})


def _verify_identity(spec: ProblemSpec, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    checks: list[Check] = []
    unc: list[str] = []
    from .correspondence import check_task_correspondence

    corr_ok, corr_detail, _ = check_task_correspondence(spec, "axiom_verify_identity", args, data)
    checks.append(Check("correspondence to original task", corr_ok, 1, corr_detail))
    if not corr_ok:
        unc.append(f"correspondence failed: {corr_detail}")
        return _finish(checks, unc, {"text": str(data.get("result") or data)[:500]})

    lhs_t: str | None = None
    rhs_t: str | None = None
    if spec.expression and "=" in str(spec.expression):
        lhs_t, rhs_t = (p.strip() for p in spec.expression.replace("==", "=").split("=", 1))
    elif spec.kind == "structured" and spec.params and "tasks" in spec.params:
        claim_task = next(
            (t for t in spec.params.get("tasks", []) if t.get("op") == "claim" and t.get("relation") == "="),
            None,
        )
        if claim_task and claim_task.get("lhs") is not None and claim_task.get("rhs") is not None:
            lhs_t, rhs_t = str(claim_task.get("lhs")), str(claim_task.get("rhs"))

    defs = None
    if spec.text:
        from .definitions import parse_definitions
        defs, _, _ = parse_definitions(spec.text)

    if lhs_t is not None and rhs_t is not None:
        try:
            tool_diff = _expr(args.get("lhs")) - _expr(args.get("rhs"))
            orig_diff = _expr(lhs_t) - _expr(rhs_t)
            same = _equivalent(tool_diff, orig_diff)
            same = bool(same) or _proportional(tool_diff, orig_diff)
            if not same and defs:
                from .definitions import evaluate, parse_with_definitions

                try:
                    orig_eval = evaluate(parse_with_definitions(f"({lhs_t}) - ({rhs_t})", defs), defs)
                    tool_eval = evaluate(parse_with_definitions(f"({args.get('lhs')}) - ({args.get('rhs')})", defs), defs)
                    same = bool(_equivalent(tool_eval, orig_eval) or sp.simplify(tool_eval - orig_eval) == 0)
                except Exception:
                    pass
        except ValueError:
            same = False
        checks.append(Check("identity matches the problem", same, 1))
    else:
        lhs_t, rhs_t = str(args.get("lhs")), str(args.get("rhs"))
    claimed = bool(data.get("equivalent"))
    assumptions = spec.assumptions or args.get("assumptions") or None
    if claimed:
        diff = _expr(lhs_t, spec) - _expr(rhs_t, spec)
        exact = E._is_symbolic_zero(diff)
        if not exact:
            tool_diff = _expr(args.get("lhs")) - _expr(args.get("rhs"))
            exact = E._is_symbolic_zero(tool_diff)
            if not exact and defs:
                from .definitions import evaluate, parse_with_definitions

                try:
                    diff_eval = evaluate(parse_with_definitions(f"({args.get('lhs')}) - ({args.get('rhs')})", defs), defs)
                    exact = E._is_symbolic_zero(diff_eval)
                    if not exact:
                        orig_eval = evaluate(parse_with_definitions(f"({lhs_t}) - ({rhs_t})", defs), defs)
                        exact = E._is_symbolic_zero(orig_eval)
                except Exception:
                    pass
        if exact:
            checks.append(Check("lhs - rhs simplifies to 0", True, 2, "symbolic proof"))
        else:
            again = E.axiom_verify_identity(lhs_t, rhs_t, assumptions=assumptions, num_points=24)
            checks.append(Check("numerical agreement at 24 fresh points", again["equivalent"], 2, again["evidence"]))
            unc.append("equivalence is supported numerically, not proven symbolically")
        text = f"{lhs_t} = {rhs_t} is an identity" + (f" (for {assumptions})" if assumptions else "")
    else:
        ce = data.get("counterexample")
        if ce is None:
            checks.append(Check("counterexample", None, 2, "the tool found no counterexample but could not prove equivalence"))
            text = "undetermined"
        else:
            # A disproof is checked exactly: substitute the counterexample into the original sides.
            values = {k: (sp.Rational(str(v)) if isinstance(v, (int, float)) else _expr(v)) for k, v in ce.items()}
            from .definitions import in_domain

            in_dom = True
            for k, val in values.items():
                if spec.domain and in_domain(val, spec.domain) is False:
                    in_dom = False
                    break
                asm = (assumptions or {}).get(k)
                if asm:
                    for flag in re.split(r"[\s,]+", asm):
                        flag = flag.strip().lower()
                        if flag == "positive" and (val.is_extended_real is False or val <= 0):
                            in_dom = False
                        elif flag == "nonnegative" and (val.is_extended_real is False or val < 0):
                            in_dom = False
                        elif flag == "integer" and val.is_integer is False:
                            in_dom = False
                        elif flag == "real" and val.is_extended_real is False:
                            in_dom = False
            if not in_dom:
                checks.append(Check("counterexample in problem domain", False, 1, f"counterexample {ce} violates domain/assumptions"))
            else:
                checks.append(Check("counterexample in problem domain", True, 1))

            lhs_e, rhs_e = _expr(lhs_t, spec), _expr(rhs_t, spec)
            dl, dr = E._num(lhs_e.subs(_by_name(lhs_e, values)), {}), E._num(rhs_e.subs(_by_name(rhs_e, values)), {})
            num_ok = dl is not None and dr is not None and abs(dl - dr) > 1e-9 * max(1.0, abs(dl), abs(dr))
            ok = in_dom and num_ok
            checks.append(Check("counterexample re-evaluated on the original sides", ok, 2, f"at {ce}: {dl} vs {dr}"))
            text = f"{lhs_t} = {rhs_t} is NOT an identity: fails at {ce}"
            if data.get("holds_on_positive_reals"):
                text += " (it does hold for positive real values)"
    return _finish(checks, unc, {"text": text, "equivalent": claimed, "counterexample": data.get("counterexample")})


def verify(spec: ProblemSpec, tool: str, args: dict[str, Any], data: dict[str, Any]) -> Verdict:
    """Independent verdict for one candidate answer (a successful tool call) against the original problem."""
    from . import verifier_ext as X

    kind = spec.kind
    from_args = False
    if kind == "unknown" and tool in X.TOOL_KIND:
        spec, kind, from_args = X.spec_from_args(X.TOOL_KIND[tool], spec.text, args), X.TOOL_KIND[tool], True
    if kind == "unknown" and tool == "axiom_nintegrate":
        spec, kind = ProblemSpec(text=spec.text, kind="integrate"), "integrate"
    if kind == "unknown":  # unparsed problem: check the result against the tool's own arguments only
        kind = {
            "axiom_solve": "solve", "axiom_nsolve": "solve", "axiom_simplify": "simplify", "axiom_dsolve": "ode",
            "axiom_linalg": "linalg", "axiom_verify_identity": "identity",
        }.get(tool, "")
        if tool == "axiom_calculus":
            kind = {v: k for k, v in CALCULUS_OP.items()}.get(str(args.get("operation", "")), "")
        if not kind:
            return Verdict("unverified", 0, [Check("tool executed", True, 0)], ["no verifier for this tool"], {"text": str(data)[:500]})
        spec = ProblemSpec(text=spec.text, kind=kind, domain=spec.domain, assumptions=spec.assumptions)  # type: ignore[arg-type]
    try:
        if tool == "axiom_verify_identity" and (kind in ("identity", "structured") or (spec.params and any(t.get("op") == "claim" for t in spec.params.get("tasks", [])))):
            v = _verify_identity(spec, args, data)
        elif kind in X.EXT_TOOLS:
            v = X.verify_extended(spec, tool, args, data, check_alignment=not from_args)
        elif tool == "axiom_nintegrate":
            v = X.verify_nintegrate(spec, args, data)
        elif kind == "solve":
            v = _verify_solve(spec, tool, args, data)
        elif kind in CALCULUS_OP:
            v = _verify_calculus(spec, args, data)
        elif kind in ("simplify", "evaluate"):
            v = _verify_simplify(spec, args, data)
        elif kind == "ode":
            v = _verify_ode(spec, args, data)
        elif kind == "linalg":
            v = _verify_linalg(spec, args, data)
        elif kind == "identity":
            v = _verify_identity(spec, args, data)
        else:
            return Verdict("unverified", 0, [Check("tool executed", True, 0)], ["no verifier for this task"], {"text": str(data)[:500]})
    except Exception as exc:  # noqa: BLE001 - a verifier crash is never a pass
        return Verdict(
            "unverified", 0,
            [Check("tool executed", True, 0), Check("verifier ran", None, 2, f"{type(exc).__name__}: {str(exc)[:200]}")],
            ["the verifier could not check this result"], {"text": str(data.get("result") or data)[:500]},
        )
    v.checks.insert(0, Check("tool executed", True, 0))
    from .correspondence import check_task_correspondence

    corr_ok, corr_detail, _ = check_task_correspondence(spec, tool, args, data)
    if not any(c.name == "correspondence to original task" for c in v.checks):
        v.checks.append(Check("correspondence to original task", corr_ok, 1, corr_detail))
    misread = _misread(spec, args) if kind != "structured" else []
    if misread:
        # The question defines these names as functions; a call that multiplies by them (T(n) read as T*n) or leaves
        # them undefined computes a different problem. That is an interpretation failure, not a disproof: the
        # candidate is set aside (refuted candidates are never answers) and the reason says which it is.
        v.status = "refuted"
        v.checks.append(Check("interpretation: defined functions are applied, never multiplied", False, 1,
                              f"the question defines {', '.join(misread)} as function(s); this call does not apply them"))
        v.uncertainty.insert(0, "interpretation failed: the computation answers a different problem than the question; "
                                "this says nothing about whether the question's own claim is true")
        return v
    if not corr_ok:
        v.status = "refuted"
        v.uncertainty.insert(0, f"correspondence failed: {corr_detail}")
        return v
    if spec.unaccounted and v.status in ("verified", "partially_verified"):
        # The answer was checked against the parsed problem, but the parse ignores part of the question.
        v.status = "unverified"
        v.checks.append(Check("parsed problem covers the whole question", None, 1, "unaccounted: " + ", ".join(spec.unaccounted)))
        v.uncertainty.insert(0, f"the parsed problem does not use {', '.join(map(repr, spec.unaccounted))} from the question; "
                                "the result may answer a different problem")
    return v


def _misread(spec: ProblemSpec, args: dict[str, Any]) -> list[str]:
    from .definitions import misread_functions
    from .problem import normalize_math_text

    tool_exprs: list[str] = []
    for key in ("equations", "equation", "expression", "lhs", "rhs", "inequality"):
        value = args.get(key)
        tool_exprs += [str(x) for x in value] if isinstance(value, list) else [str(value)] if value else []
    exprs = tool_exprs if tool_exprs else ([spec.expression or "", *spec.equations])
    try:
        return misread_functions(normalize_math_text(spec.text), exprs)
    except Exception:  # noqa: BLE001 - the guard never blocks a result on its own failure
        return []


def alignment_failed(verdict: Verdict) -> bool:
    return any(c.level == 1 and c.passed is False for c in verdict.checks)


__all__ = ["ANSWER_TOOLS", "Check", "Verdict", "alignment_failed", "answers_problem", "verify"]
