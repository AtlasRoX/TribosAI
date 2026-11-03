"""
Deterministic results for initial-value problems, computed by code for the writer (never by the writing model).

A question such as "Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t), x(0)=0.1, x'(0)=0; compute x(t) for t=0,0.5,...,5;
compare with RK4 and report the maximum absolute error" asks for numbers the writer must not invent and must not
refuse. This module reads the ODE, the initial conditions, the requested time points and the RK4 request from the
question itself, and returns:

- the exact solution (SymPy dsolve with the decimal inputs as exact rationals), checked by substitution (checkodesol)
  and against every initial condition;
- for a linear constant-coefficient second-order equation: natural frequency, damping ratio, damped frequency and,
  for sinusoidal forcing, the steady-state amplitude and phase lag, each exact and as a decimal; the transient and
  steady-state parts of the solution;
- the solution at the requested points;
- a classical fixed-step RK4 integration compared with the exact solution (or, for a nonlinear equation without a
  closed form, with a tight-tolerance DOP853 reference), with the maximum absolute error over every RK4 step.

Anything that cannot be established is left out with a note; nothing is estimated.
"""

from __future__ import annotations

import concurrent.futures
import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import sympy as sp

from ..axiom.engine import safe_parse_expr
from .analysis import convergence_study, physics_checks

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_PRIMES = re.compile(r"(?<![A-Za-z_\\])([a-zA-Z])\s*('{1,4}|′{1,4}|″)\s*(?:\(\s*([a-zA-Z])\s*\))?")
_LEIBNIZ = [
    re.compile(r"\\frac\{\s*d\^?\{?(\d)?\}?\s*([a-zA-Z])\s*\}\{\s*d\s*([a-zA-Z])\^?\{?(\d)?\}?\s*\}"),
    re.compile(r"d\^?(\d)?\s*([a-zA-Z])\s*/\s*d\s*([a-zA-Z])\^?(\d)?"),
]
_DOTS = [(re.compile(r"\\ddot\{?\s*([a-zA-Z])\s*\}?"), 2), (re.compile(r"\\dot\{?\s*([a-zA-Z])\s*\}?"), 1)]
_UNICODE_DOTS = {"ẍ": ("x", 2), "ẋ": ("x", 1), "ÿ": ("y", 2), "ẏ": ("y", 1)}
_RK4_RE = re.compile(r"runge[\s\u2010-\u2015-]*kutta|\brk[\s-]?4\b", re.I)
_SOLVE_TIMEOUT_S = 20.0
MAX_TABLE_POINTS = 201
CURVE_POINTS = 241
MAX_RK4_STEPS = 200_000


@dataclass
class OdeProblem:
    equation_text: str
    dependent: str
    independent: str
    order: int
    expr: sp.Expr  # residual F(t, X0..Xn) = 0, exact rationals
    ics: list[tuple[int, sp.Rational, sp.Rational]]  # (derivative order, t0, value)
    lhs: sp.Expr = sp.S.Zero
    rhs: sp.Expr = sp.S.Zero
    points: list[float] = field(default_factory=list)
    rk4: bool = False
    rk4_step: float | None = None
    t_unit: str = ""
    x_unit: str = ""
    span_end: float | None = None  # "on [0, 10] s": the end of the interval the question names

    def end_time(self, t0: float) -> float:
        """Where computations stop: the interval the question names or the last requested point, else t0 + 10."""
        ends = [e for e in (self.span_end, max(self.points) if self.points else None) if e is not None and e > t0]
        return max(ends) if ends else t0 + 10.0


def _derivative_symbol(k: int) -> sp.Symbol:
    return sp.Symbol(f"Xd{k}")


def _normalise_derivatives(text: str) -> tuple[str, str | None, str | None]:
    """Replace every derivative notation by placeholder names Xd0..Xdn; (text, dependent, independent)."""
    dep: str | None = None
    ind: str | None = None
    s = text.replace("−", "-").replace("·", "*").replace("×", "*")
    for ch, (var, k) in _UNICODE_DOTS.items():
        if ch in s:
            dep = dep or var
            s = s.replace(ch, f" Xd{k} ")
    for pat, k in _DOTS:
        def dot_sub(m: re.Match[str], k: int = k) -> str:
            nonlocal dep
            dep = dep or m.group(1)
            return f" Xd{k} "
        s = pat.sub(dot_sub, s)
    for pat in _LEIBNIZ:
        def leib_sub(m: re.Match[str]) -> str:
            nonlocal dep, ind
            dep, ind = dep or m.group(2), ind or m.group(3)
            return f" Xd{int(m.group(1) or m.group(4) or 1)} "
        s = pat.sub(leib_sub, s)

    def prime_sub(m: re.Match[str]) -> str:
        nonlocal dep, ind
        primes = m.group(2)
        k = 2 if primes == "″" else len(primes)
        dep, ind = dep or m.group(1), ind or m.group(3)
        return f" Xd{k} "

    s = _PRIMES.sub(prime_sub, s)
    if dep is None:
        return s, None, None
    ind = ind or "t"
    s = re.sub(rf"(?<![A-Za-z_]){re.escape(dep)}\s*\(\s*{re.escape(ind)}\s*\)", " Xd0 ", s)
    s = re.sub(rf"(?<![A-Za-z_]){re.escape(dep)}(?![A-Za-z_(])", " Xd0 ", s)
    return s, dep, ind


def _equation_candidates(question: str) -> list[str]:
    parts = re.split(r"\n|;|\.\s+(?=[A-Z])", question)
    out = []
    for p in parts:
        if "=" not in p:
            continue
        p = p.split(":")[-1] if ":" in p else p
        p = re.split(r"\s+(?:with|where|for|subject\s+to|given|when|if)\b|,\s*(?=[a-zA-Z]\s*'*\s*\(\s*0)", p)[0]
        out.append(_strip_prose(p.strip().strip("$").strip()))
    return out


_MATH_WORDS = frozenset({"sin", "cos", "tan", "exp", "log", "ln", "sqrt", "sinh", "cosh", "tanh", "pi", "e"})


def _strip_prose(text: str) -> str:
    """'Solve the ODE y'(t) = -2y(t).' -> "y'(t) = -2y(t)": leading and trailing English words are not mathematics."""
    words = text.split()
    while words and re.fullmatch(r"[A-Za-z]{2,}[,:]?", words[0]) and words[0].lower().rstrip(",:") not in _MATH_WORDS:
        words.pop(0)
    while words and re.fullmatch(r"[A-Za-z]{2,}[.,;:]?", words[-1]) and words[-1].lower().rstrip(".,;:") not in _MATH_WORDS:
        words.pop()
    return " ".join(words).rstrip(".,;:")


def _initial_conditions(question: str, dep: str) -> list[tuple[int, sp.Rational, sp.Rational, str]]:
    """(order, t0, value, unit) for x(0)=.., x'(0)=.., ẋ(0)=.., \\dot{x}(0)=.., dx/dt(0)=..."""
    out: list[tuple[int, sp.Rational, sp.Rational, str]] = []
    d = re.escape(dep)
    forms = [
        (rf"(?<![A-Za-z]){d}\s*('{{0,4}})\s*\(\s*({_NUM})\s*\)\s*=\s*({_NUM})\s*([a-zA-Z/]+)?", None),
        (rf"\\dot\{{?\s*{d}\s*\}}?\s*\(\s*({_NUM})\s*\)\s*=\s*({_NUM})\s*([a-zA-Z/]+)?", 1),
        (rf"ẋ\s*\(\s*({_NUM})\s*\)\s*=\s*({_NUM})\s*([a-zA-Z/]+)?", 1),
        (rf"d{d}\s*/\s*dt\s*\(\s*({_NUM})\s*\)\s*=\s*({_NUM})\s*([a-zA-Z/]+)?", 1),
    ]
    for pat, fixed in forms:
        for m in re.finditer(pat, question):
            if fixed is None:
                k, t0, v, unit = len(m.group(1)), m.group(2), m.group(3), m.group(4) or ""
            else:
                k, t0, v, unit = fixed, m.group(1), m.group(2), m.group(3) or ""
            out.append((k, sp.Rational(t0), sp.Rational(v), unit))
    seen: dict[int, tuple[int, sp.Rational, sp.Rational, str]] = {}
    for ic in out:
        seen.setdefault(ic[0], ic)
    return [seen[k] for k in sorted(seen)]


def _time_points(question: str, ind: str) -> list[float]:
    v = re.escape(ind)
    m = re.search(rf"\b{v}\s*=\s*({_NUM})\s*,\s*({_NUM})\s*,\s*(?:{_NUM}\s*,\s*)*(?:\.\.\.|…|\\ldots|\\dots)\s*,\s*({_NUM})", question)
    if m:
        a, b, c = (float(m.group(i)) for i in (1, 2, 3))
        step = b - a
        if step > 0 and c > a:
            n = round((c - a) / step)
            if math.isclose(a + n * step, c, rel_tol=1e-9, abs_tol=1e-9) and n + 1 <= MAX_TABLE_POINTS:
                return [round(a + i * step, 12) for i in range(n + 1)]
    m = re.search(rf"\bfrom\s+{v}\s*=\s*({_NUM})\s+to\s+{v}?\s*=?\s*({_NUM})\s+(?:in|with|at)\s+(?:steps?|increments?|intervals?)\s+(?:of\s+)?({_NUM})", question, re.I)
    if m:
        a, c, step = (float(m.group(i)) for i in (1, 2, 3))
        n = round((c - a) / step) if step > 0 else 0
        if 0 < n + 1 <= MAX_TABLE_POINTS:
            return [round(a + i * step, 12) for i in range(n + 1)]
    # "at t = 0.5, 2, 5 and 10 s", "t = 1, 2, and 3": the last separator may be ", and" or a bare "and".
    m = re.search(rf"\b(?:at|for)\s+{v}\s*=\s*((?:{_NUM}\s*(?:,\s*(?:and\s+)?|\s+and\s+))+{_NUM})", question)
    if m:
        vals = [float(x) for x in re.findall(_NUM, m.group(1))]
        return vals[:MAX_TABLE_POINTS]
    return []


def _span_end(question: str, ind: str) -> float | None:
    """The end of an interval the question names for the run: "on [0, 10] s", "0 <= t <= 10", "until t = 10"."""
    v = re.escape(ind)
    for pat in (rf"\b(?:on|over|in|for|from)\s+(?:the\s+interval\s+)?\[\s*({_NUM})\s*,\s*({_NUM})\s*\]",
                rf"({_NUM})\s*(?:<=|≤|<|\\le)\s*{v}\s*(?:<=|≤|<|\\le)\s*({_NUM})"):
        ends = [float(m.group(2)) for m in re.finditer(pat, question, re.I) if float(m.group(2)) > float(m.group(1))]
        if ends:
            return max(ends)
    m = re.search(rf"\b(?:until|up\s+to)\s+{v}\s*=\s*({_NUM})", question, re.I)
    return float(m.group(1)) if m else None


def _rk4_step(question: str) -> float | None:
    m = re.search(rf"(?:\bh\s*=\s*|step(?:\s*size)?\s*(?:of|=|h\s*=)?\s*)({_NUM})", question, re.I)
    if m:
        h = float(m.group(1))
        return h if 0 < h < 1e3 else None
    return None


def parse_ode_problem(question: str) -> OdeProblem | None:
    """The initial-value problem stated in the question, or None when there is none to read reliably."""
    if not question or not re.search(r"'|′|″|\\dot|ẋ|ẍ|d\^?\d?\s*[a-zA-Z]\s*/\s*d[a-zA-Z]|\\frac\{\s*d", question):
        return None
    for cand in _equation_candidates(question):
        # LaTeX-style exponents and products: "e^{-3t}" -> "e^(-3t)", "t\,e^{-3t}" -> "t e^(-3t)".
        cand = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", cand).replace("\\,", " ").replace("\\cdot", "*")
        text, dep, ind = _normalise_derivatives(cand)
        if dep is None or "Xd" not in text or "=" not in text:
            continue
        lhs_s, _, rhs_s = text.partition("=")
        if "=" in rhs_s:
            continue
        order = max(int(k) for k in re.findall(r"Xd(\d)", text))
        if order < 1 or order > 4:
            continue
        local = {f"Xd{k}": _derivative_symbol(k) for k in range(order + 1)}
        local[ind] = sp.Symbol(ind)
        try:
            lhs = safe_parse_expr(lhs_s.strip(), local_dict=local)
            rhs = safe_parse_expr(rhs_s.strip(), local_dict=local)
        except Exception:  # noqa: BLE001 - not an equation this module can read
            continue
        expr = sp.nsimplify(sp.sympify(lhs - rhs), rational=True)
        allowed = {sp.Symbol(ind), *(_derivative_symbol(k) for k in range(order + 1))}
        if not expr.free_symbols <= allowed or _derivative_symbol(order) not in expr.free_symbols:
            continue
        ics_raw = _initial_conditions(question, dep)
        ics = [(k, t0, v) for k, t0, v, _ in ics_raw if k < order]
        if len(ics) != order or len({t0 for _, t0, _ in ics}) != 1:
            ics = []
        t_unit = "s" if re.search(r"\bseconds?\b|\bs\b(?=[\s,.)])", question) else ""
        x_unit = next((u for k, _, _, u in ics_raw if k == 0 and u and u.isalpha()), "")
        return OdeProblem(
            equation_text=cand, dependent=dep, independent=ind, order=order, expr=expr, ics=ics,
            lhs=sp.nsimplify(lhs, rational=True), rhs=sp.nsimplify(rhs, rational=True),
            points=_time_points(question, ind), rk4=bool(_RK4_RE.search(question)), rk4_step=_rk4_step(question),
            span_end=_span_end(question, ind),
            t_unit=t_unit, x_unit=x_unit,
        )
    return None


def _with_timeout(fn: Any, timeout: float = _SOLVE_TIMEOUT_S) -> Any:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _sig(value: float, digits: int = 6) -> str:
    if value == 0 or not math.isfinite(value):
        return "0" if value == 0 else str(value)
    return f"{value:.{digits}g}"


def _ode(prob: OdeProblem) -> tuple[sp.Function, sp.Symbol, sp.Eq]:
    t = sp.Symbol(prob.independent, real=True)
    f = sp.Function(prob.dependent)
    subs = {_derivative_symbol(k): f(t).diff(t, k) for k in range(prob.order + 1)}
    subs[sp.Symbol(prob.independent)] = t
    return f, t, sp.Eq(prob.expr.subs(subs), 0)


def _linear_coefficients(prob: OdeProblem) -> tuple[list[sp.Expr], sp.Expr] | None:
    """[a_n, ..., a_0] and forcing F(t) when the equation is a_n x^(n) + ... + a_0 x = F(t) with constant a_k."""
    syms = [_derivative_symbol(k) for k in range(prob.order, -1, -1)]
    try:
        poly = sp.Poly(prob.expr, *syms)
    except sp.PolynomialError:
        return None
    if poly.total_degree() > 1:
        return None
    coeffs = [sp.simplify(prob.expr.diff(s)) for s in syms]
    if any(c.free_symbols for c in coeffs):
        return None
    forcing = sp.simplify(-(prob.expr - sum(c * s for c, s in zip(coeffs, syms, strict=True))))
    return coeffs, forcing


def _sinusoid(forcing: sp.Expr, t: sp.Symbol) -> tuple[sp.Expr, sp.Expr, sp.Expr] | None:
    """(p, q, w) with forcing = p cos(w t) + q sin(w t), w > 0, after dropping forcing terms that die out
    ("50 t e^{-3t} + 18 cos 3t": the steady state is driven by 18 cos 3t alone)."""
    terms = sp.Add.make_args(sp.expand(forcing))
    persistent = [term for term in terms if not (term.has(sp.exp) and sp.limit(term, t, sp.oo) == 0)]
    if persistent and len(persistent) < len(terms):
        forcing = sp.Add(*persistent)
    ws = {sp.simplify(a.args[0] / t) for a in forcing.atoms(sp.cos, sp.sin)}
    if len(ws) != 1:
        return None
    w = ws.pop()
    if w.free_symbols or not w.is_positive:
        return None
    p = forcing.coeff(sp.cos(w * t))
    q = forcing.coeff(sp.sin(w * t))
    if sp.simplify(forcing - p * sp.cos(w * t) - q * sp.sin(w * t)) != 0 or p.free_symbols or q.free_symbols:
        return None
    return p, q, w


def _fact(name: str, symbol: str, exact: sp.Expr, unit: str = "") -> dict[str, Any]:
    exact = sp.nsimplify(sp.simplify(exact))
    value = float(sp.N(exact, 30))
    return {"name": name, "symbol": symbol, "exact_latex": sp.latex(exact), "value": _sig(value, 6), "unit": unit}


def _second_order_parameters(prob: OdeProblem, coeffs: list[sp.Expr], forcing: sp.Expr, t: sp.Symbol) -> tuple[list[dict[str, Any]], list[str]]:
    a, b, c = coeffs
    notes: list[str] = []
    out: list[dict[str, Any]] = []
    if not (a.is_positive and c.is_positive and b.is_nonnegative):
        return out, notes
    rate = f"rad/{prob.t_unit}" if prob.t_unit else "rad per unit time"
    wn = sp.sqrt(c / a)
    zeta = b / (2 * sp.sqrt(a * c))
    out.append(_fact("natural frequency", r"\omega_n = \sqrt{k/m}", wn, rate))
    out.append(_fact("damping ratio", r"\zeta = c/(2\sqrt{mk})", zeta, "dimensionless"))
    if zeta < 1:
        out.append(_fact("damped natural frequency", r"\omega_d = \omega_n\sqrt{1-\zeta^2}", wn * sp.sqrt(1 - zeta**2), rate))
        notes.append("underdamped (0 < zeta < 1)" if zeta > 0 else "undamped (zeta = 0)")
    else:
        notes.append("critically damped (zeta = 1)" if zeta == 1 else "overdamped (zeta > 1)")
    sin = _sinusoid(forcing, t) if forcing != 0 else None
    if sin is not None:
        p, q, w = sin
        f0 = sp.sqrt(p**2 + q**2)
        denom = sp.sqrt((c - a * w**2) ** 2 + (b * w) ** 2)
        unit = prob.x_unit or ""
        out.append(_fact("forcing frequency", r"\omega", w, rate))
        if sp.simplify(denom) == 0:
            # Undamped forcing at the natural frequency: no steady state, the amplitude grows linearly in time.
            out.append(_fact("resonant amplitude growth rate", r"F_0/(2 m \omega_n)", f0 / (2 * a * wn),
                             f"{unit}/{prob.t_unit}" if unit and prob.t_unit else ""))
            notes.append("resonance: undamped forcing at the natural frequency, so there is no steady state and the "
                         "amplitude grows linearly in time")
            return out, notes
        amp = f0 / denom
        out.append(_fact("steady-state amplitude", r"X = F_0/\sqrt{(k-m\omega^2)^2+(c\omega)^2}", amp, unit))
        lag = sp.atan2(b * w, c - a * w**2)
        out.append(_fact("phase lag of the response behind the forcing", r"\phi = \operatorname{atan2}(c\omega,\ k-m\omega^2)", lag, "rad"))
        out[-1]["value_degrees"] = _sig(float(sp.N(lag * 180 / sp.pi, 30)), 6)
    return out, notes


def _split_transient(solution: sp.Expr, t: sp.Symbol) -> tuple[sp.Expr, sp.Expr] | None:
    terms = sp.Add.make_args(sp.expand(solution))
    transient = [term for term in terms if term.has(sp.exp) and sp.limit(term, t, sp.oo) == 0]
    if not transient:
        return None
    tr = sp.Add(*transient)
    return sp.simplify(tr), sp.simplify(solution - tr)


def _readable(expr: sp.Expr, t: sp.Symbol) -> str:
    """LaTeX with one shared exponential factored out and the trigonometric terms collected, e.g.
    e^{-3t/4}(A cos(wt) + B sin(wt)) instead of one large fraction."""
    expr = sp.expand(expr)
    exps = set(expr.atoms(sp.exp))
    if len(exps) == 1:
        e = exps.pop()
        inner = sp.expand(sp.simplify(expr / e))
        if not inner.has(sp.exp):
            trig = sorted(inner.atoms(sp.cos, sp.sin), key=sp.default_sort_key)
            inner = sp.collect(inner, trig)
            return f"{sp.latex(e)}\\left({sp.latex(inner)}\\right)"
    trig = sorted(expr.atoms(sp.cos, sp.sin), key=sp.default_sort_key)
    return sp.latex(sp.collect(expr, trig) if trig else expr)


def _display_equation(prob: OdeProblem) -> str:
    dep, ind = prob.dependent, prob.independent
    names = {0: f"{dep}({ind})", 1: f"\\dot{{{dep}}}", 2: f"\\ddot{{{dep}}}"}
    subs = {_derivative_symbol(k): sp.Symbol(names.get(k, f"{dep}^{{({k})}}")) for k in range(prob.order + 1)}
    return f"{sp.latex(prob.lhs.subs(subs))} = {sp.latex(prob.rhs.subs(subs))}"


def _rhs_function(prob: OdeProblem) -> Any:
    top = _derivative_symbol(prob.order)
    sol = sp.solve(prob.expr, top, dict=True)
    if len(sol) != 1:
        raise ValueError("the highest derivative cannot be isolated uniquely")
    t = sp.Symbol(prob.independent)
    state = [_derivative_symbol(k) for k in range(prob.order)]
    g = sp.lambdify((t, *state), sol[0][top], modules="numpy")

    def rhs(tt: float, y: np.ndarray) -> np.ndarray:
        return np.array([*y[1:], float(g(tt, *y))], dtype=float)

    return rhs


def _rk4(rhs: Any, y0: list[float], t0: float, t1: float, h: float) -> tuple[np.ndarray, np.ndarray]:
    n = round((t1 - t0) / h)
    times = t0 + h * np.arange(n + 1)
    ys = np.empty((n + 1, len(y0)))
    y = np.array(y0, dtype=float)
    ys[0] = y
    for i in range(n):
        tt = times[i]
        k1 = rhs(tt, y)
        k2 = rhs(tt + h / 2, y + h / 2 * k1)
        k3 = rhs(tt + h / 2, y + h / 2 * k2)
        k4 = rhs(tt + h, y + h * k3)
        y = y + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        ys[i + 1] = y
    return times, ys


def compute_ode_facts(question: str) -> dict[str, Any] | None:
    """The computed results for the initial-value problem in the question, or None when there is none."""
    prob = parse_ode_problem(question)
    if prob is None:
        return None
    f, t, ode = _ode(prob)
    t_plain = sp.Symbol(prob.independent)
    data: dict[str, Any] = {
        "kind": "ode_initial_value_problem",
        "equation_latex": _display_equation(prob),
        "dependent": prob.dependent,
        "independent": prob.independent,
        "order": prob.order,
        "units": {"time": prob.t_unit, "solution": prob.x_unit},
        "initial_conditions": [
            {"order": k, "at": str(t0), "value": str(v)} for k, t0, v in prob.ics
        ],
        "notes": [],
        "checks": [],
        "requested": {"points": bool(prob.points), "rk4": prob.rk4},
    }
    if len(prob.ics) != prob.order:
        data["notes"].append("the initial conditions could not all be read, so no particular solution was computed")
        return data

    exact: sp.Expr | None = None
    linear = _linear_coefficients(prob)
    t0 = prob.ics[0][1]
    ics = {f(t).diff(t, k).subs(t, t0) if k else f(t0): v for k, _, v in prob.ics}
    if linear is not None:
        try:
            sol = _with_timeout(lambda: sp.dsolve(ode, f(t), ics=ics))
            if isinstance(sol, sp.Eq):
                exact = sp.simplify(sol.rhs)
        except Exception as exc:  # noqa: BLE001 - reported, the numeric path remains
            data["notes"].append(f"no closed form was found ({type(exc).__name__})")
    if exact is not None:
        ok_ode = sp.checkodesol(ode, sp.Eq(f(t), exact))[0]
        ok_ics = all(sp.simplify(exact.diff(t, k).subs(t, t0) - v) == 0 for k, _, v in prob.ics)
        data["checks"].append({"name": "exact solution satisfies the differential equation (substitution)", "passed": bool(ok_ode)})
        data["checks"].append({"name": "exact solution satisfies every initial condition", "passed": bool(ok_ics)})
        if ok_ode and ok_ics:
            split = _split_transient(exact, t)
            lhs = f"{prob.dependent}({prob.independent})"
            if split is not None:
                data["transient_latex"] = _readable(split[0], t)
                data["steady_state_latex"] = _readable(split[1], t)
                data["_steady_expr"] = split[1]  # internal: sampled for the plot, removed before returning
                data["exact_solution_latex"] = f"{lhs} = {data['transient_latex']} + {data['steady_state_latex']}"
            else:
                data["exact_solution_latex"] = f"{lhs} = {_readable(exact, t)}"
        else:
            exact = None
            data["notes"].append("the symbolic solution failed its own check and is not reported")

    if linear is not None and prob.order == 2:
        params, notes = _second_order_parameters(prob, linear[0], linear[1].subs(t_plain, t), t)
        data["parameters"] = params
        data["notes"].extend(notes)
        if exact is not None and all(co.is_number for co in linear[0]):
            forcing = linear[1].subs(t_plain, t)
            t_stop = prob.end_time(float(t0))
            try:
                physics = _with_timeout(lambda: physics_checks(
                    linear[0], forcing, t, exact, data.get("_steady_expr"),
                    _sinusoid(forcing, t) if forcing != 0 else None, float(t0), float(t_stop), prob.x_unit, prob.t_unit))
                listed = {p["name"] for p in params}  # a quantity already among the parameters is not repeated
                data["physics"] = {"checks": physics["checks"],
                                   "quantities": [q for q in physics["quantities"] if q["name"] not in listed]}
                if physics.get("frequency_response"):
                    data["frequency_response"] = physics["frequency_response"]
            except Exception as exc:  # noqa: BLE001 - the checks are an addition, never a blocker
                data["notes"].append(f"the physics consistency checks could not be run ({type(exc).__name__})")

    # The requested points, from the exact solution.
    exact_fn = sp.lambdify(t, exact, modules="mpmath") if exact is not None else None
    if prob.points and exact_fn is not None:
        data["table"] = [{prob.independent: _sig(p, 6), prob.dependent: _sig(float(exact_fn(p)), 7)} for p in prob.points]
    if exact_fn is not None:
        # A dense sample of the exact solution (and its steady-state part) over the requested span, for plotting.
        t_start = float(t0)
        t_stop = prob.end_time(t_start)
        if t_stop > t_start:
            grid = np.linspace(t_start, t_stop, CURVE_POINTS)
            curve: dict[str, Any] = {"t": [round(float(v), 6) for v in grid],
                                     "x": [float(_sig(float(exact_fn(v)), 6)) for v in grid]}
            steady = data.get("_steady_expr")
            if steady is not None:
                steady_fn = sp.lambdify(t, steady, modules="mpmath")
                curve["steady"] = [float(_sig(float(steady_fn(v)), 6)) for v in grid]
            data["curve"] = curve
    data.pop("_steady_expr", None)

    if prob.rk4:
        try:
            rhs = _rhs_function(prob)
            y0 = [float(v) for _, _, v in prob.ics]
            t_start = float(t0)
            t_end = prob.end_time(t_start)
            h = prob.rk4_step or 1e-3
            if (t_end - t_start) / h > MAX_RK4_STEPS:
                raise ValueError(f"the RK4 run would need more than {MAX_RK4_STEPS} steps")
            times, ys = _rk4(rhs, y0, t_start, t_end, h)
            if exact_fn is not None:
                ref = np.array([float(exact_fn(tt)) for tt in times])
                reference = "exact solution"
            else:
                from scipy.integrate import solve_ivp

                ref_sol = solve_ivp(rhs, (t_start, t_end), y0, method="DOP853", rtol=1e-12, atol=1e-14, t_eval=times)
                if not ref_sol.success:
                    raise ValueError("the reference integration failed")
                ref = ref_sol.y[0]
                reference = "DOP853 reference integration (rtol 1e-12)"
            err = np.abs(ys[:, 0] - ref)
            i_max = int(np.argmax(err))
            rk: dict[str, Any] = {
                "method": "classical fourth-order Runge-Kutta, fixed step",
                "step": _sig(h, 6),
                "step_was_given": prob.rk4_step is not None,
                "steps": len(times) - 1,
                "compared_with": reference,
                "max_abs_error": _sig(float(err[i_max]), 3),
                "max_error_at": _sig(float(times[i_max]), 6),
            }
            if prob.points:
                idx = {round(float(tt), 9): i for i, tt in enumerate(times)}
                rows = []
                for p in prob.points:
                    i = idx.get(round(p, 9))
                    if i is not None:
                        rows.append({prob.independent: _sig(p, 6), "rk4": _sig(float(ys[i, 0]), 7),
                                     "reference": _sig(float(ref[i]), 7), "abs_error": _sig(float(err[i]), 3)})
                rk["at_points"] = rows
            data["rk4"] = rk
            try:
                sin = _sinusoid(linear[1].subs(t_plain, t), t) if linear is not None and linear[1] != 0 else None
                study = convergence_study(rhs, y0, t_start, t_end, _rk4,
                                          (lambda tt: float(exact_fn(tt))) if exact_fn is not None else None,
                                          h, float(err[i_max]), float(sin[2]) if sin is not None else 0.0)
                if study is not None:
                    data["convergence"] = study
            except Exception as exc:  # noqa: BLE001
                data["notes"].append(f"the convergence study could not be run ({type(exc).__name__})")
        except Exception as exc:  # noqa: BLE001
            data["notes"].append(f"the RK4 comparison could not be run: {exc}")
    return data


__all__ = ["OdeProblem", "compute_ode_facts", "parse_ode_problem"]
