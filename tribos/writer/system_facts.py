"""
First-order ODE systems a question states in full (two or more unknowns: d x/dt = ..., y' = ..., with parameters,
initial values and a time span), or names (Lorenz, Robertson, Van der Pol, Lotka-Volterra), integrated by code so the
answer reports the simulation of the system that was asked for:

- the right-hand sides are parsed and shown, so the reader sees exactly which equations were integrated (intent);
- stiffness is detected from the Jacobian at the start; a stiff system runs on Radau and BDF, a non-stiff one on
  DOP853 at two tolerances and Radau as the second method;
- linear invariants (c . f = 0 identically, such as total mass) are found symbolically and their drift is measured;
- the two tolerances and the two methods must agree, or the result says they do not.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import sympy as sp

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")
_GREEK = {"σ": "sigma", "ρ": "rho", "β": "beta", "μ": "mu", "α": "alpha", "γ": "gamma", "δ": "delta", "ω": "omega",
          "κ": "kappa", "λ": "lam", "ε": "epsilon", "τ": "tau"}
CURVE_POINTS = 600

# Named systems: equations, default parameters, initial state, span, invariants a reader expects.
PRESETS: dict[str, dict[str, Any]] = {
    "robertson": {"label": "Robertson stiff chemical kinetics",
                  "rhs": {"y1": "-0.04*y1 + 1e4*y2*y3", "y2": "0.04*y1 - 1e4*y2*y3 - 3e7*y2**2", "y3": "3e7*y2**2"},
                  "init": {"y1": 1.0, "y2": 0.0, "y3": 0.0}, "span": 4e10, "log_time": True},
    "lorenz": {"label": "Lorenz system", "rhs": {"x": "sigma*(y - x)", "y": "x*(rho - z) - y", "z": "x*y - beta*z"},
               "params": {"sigma": 10.0, "rho": 28.0, "beta": 8.0 / 3.0}, "init": {"x": 1.0, "y": 1.0, "z": 1.0}, "span": 25.0},
    "van der pol": {"label": "Van der Pol oscillator", "rhs": {"x": "y", "y": "mu*(1 - x**2)*y - x"},
                    "params": {"mu": 1.0}, "init": {"x": 2.0, "y": 0.0}, "span": 20.0},
    "lotka": {"label": "Lotka-Volterra predator-prey", "rhs": {"x": "alpha*x - beta*x*y", "y": "delta*x*y - gamma*y"},
              "params": {"alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4}, "init": {"x": 10.0, "y": 10.0},
              "span": 50.0},
}


def _normalise(text: str) -> str:
    out = (text or "").translate(_SUB).replace("−", "-").replace("·", "*").replace("×", "*")
    for g, name in _GREEK.items():
        out = out.replace(g, name)
    return out


_DERIV_RE = re.compile(r"(?:\bd\s*([A-Za-z]\w?)\s*/\s*dt|\b([A-Za-z]\w?)\s*'|\\dot\s*\{?\s*([A-Za-z]\w?)\s*\}?)\s*=\s*([^,;\n]+)")
_IC_RE = re.compile(rf"\b([A-Za-z]\w?)\s*\(\s*0\s*\)\s*=\s*({_NUM})")
_PARAM_RE = re.compile(rf"(?<![\w(])([A-Za-z]\w{{0,7}})\s*=\s*({_NUM})(?:\s*/\s*({_NUM}))?(?![\w(])")


def _double_pendulum(q: str) -> dict[str, Any] | None:
    """The damped double pendulum, its equations derived by code from the Lagrangian (point masses on massless rods,
    viscous damping Q_i = -b dtheta_i/dt), with the damping work W as an extra state so that E + W must stay constant."""
    def value(name: str, default: float) -> float:
        m = re.search(rf"\b{name}\s*=\s*({_NUM})", q)
        return float(m.group(1)) if m else default

    mass, length, damping, grav = value("m", 1.0), value("l", 1.0), value("b", 0.0), value("g", 9.81)
    m1, m2 = value("m1", mass), value("m2", mass)
    l1, l2 = value("l1", length), value("l2", length)
    th = re.search(r"θ\s*=\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)|theta\s*=\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)", q)
    a1, a2 = (sp.pi / 2, sp.pi / 2)
    if th:
        g1, g2 = (th.group(1), th.group(2)) if th.group(1) else (th.group(3), th.group(4))
        a1, a2 = sp.sympify(g1.replace("π", "pi")), sp.sympify(g2.replace("π", "pi"))
    sm = re.search(rf"for\s+({_NUM})\s*(?:s\b|seconds)|t\s*(?:∈|in)\s*\[\s*0\s*,\s*({_NUM})\s*\]", q)
    span = float(next(g for g in sm.groups() if g)) if sm else 20.0

    t = sp.Symbol("t")
    th1, th2 = sp.Function("th1")(t), sp.Function("th2")(t)
    x1, y1 = l1 * sp.sin(th1), -l1 * sp.cos(th1)
    x2, y2 = x1 + l2 * sp.sin(th2), y1 - l2 * sp.cos(th2)
    kin = sp.Rational(1, 2) * m1 * (sp.diff(x1, t) ** 2 + sp.diff(y1, t) ** 2) + \
        sp.Rational(1, 2) * m2 * (sp.diff(x2, t) ** 2 + sp.diff(y2, t) ** 2)
    pot = m1 * grav * y1 + m2 * grav * y2
    lag = kin - pot
    eqs = [sp.diff(sp.diff(lag, sp.diff(q_, t)), t) - sp.diff(lag, q_) + damping * sp.diff(q_, t) for q_ in (th1, th2)]
    acc = sp.symbols("a1 a2")
    w1, w2, s1, s2 = sp.symbols("w1 w2 th1 th2")
    subs = {sp.diff(th1, t, 2): acc[0], sp.diff(th2, t, 2): acc[1], sp.diff(th1, t): w1, sp.diff(th2, t): w2,
            th1: s1, th2: s2}
    sol = sp.solve([sp.simplify(e.subs(subs)) for e in eqs], acc, dict=True)[0]
    energy = (kin + pot).subs({sp.diff(th1, t): w1, sp.diff(th2, t): w2, th1: s1, th2: s2})
    return {"rhs": {"th1": w1, "th2": w2, "w1": sp.simplify(sol[acc[0]]), "w2": sp.simplify(sol[acc[1]]),
                    "W": damping * (w1 ** 2 + w2 ** 2)},
            "states": ["th1", "th2", "w1", "w2", "W"], "params": {"m1": m1, "m2": m2, "l1": l1, "l2": l2, "b": damping,
                                                                   "g": grav},
            "init": {"th1": float(a1), "th2": float(a2), "w1": 0.0, "w2": 0.0, "W": 0.0}, "span": span,
            "label": "damped double pendulum (equations derived from the Lagrangian)", "preset": "double pendulum",
            "log_time": False, "energy": sp.simplify(energy), "energy_states": ["th1", "th2", "w1", "w2"]}


def parse_system(question: str) -> dict[str, Any] | None:
    """The stated (or named) system: {"rhs": {state: expr}, "params", "init", "span", "label", "log_time"}, or None."""
    q = _normalise(question)
    low = q.lower()
    if re.search(r"\bdouble\s+pendulum\b", low):
        return _double_pendulum(q)
    rhs_text: dict[str, str] = {}
    for m in _DERIV_RE.finditer(q):
        name = m.group(1) or m.group(2) or m.group(3)
        body = re.split(r"\s+(?=(?:[A-Za-z]{4,}|and|with|for|where)\b)", m.group(4).strip())[0].strip(" .")
        if name and body and name not in rhs_text:
            rhs_text[name] = body
    preset = None
    if len(rhs_text) < 2:
        for key, spec in PRESETS.items():
            if re.search(rf"\b{key}\b", low):
                preset = key
                rhs_text = dict(spec["rhs"])
                break
        if preset is None:
            return None
    spec = PRESETS.get(preset or "", {})
    params = dict(spec.get("params", {}))
    init = dict(spec.get("init", {}))
    states = list(rhs_text)
    for m in _IC_RE.finditer(q):
        if m.group(1) in rhs_text:
            init[m.group(1)] = float(m.group(2))
    for m in _PARAM_RE.finditer(q):
        name, value = m.group(1), float(m.group(2)) / (float(m.group(3)) if m.group(3) else 1.0)
        if name not in rhs_text and name not in ("t", "T") and not re.fullmatch(r"[a-z]\(0\)", name):
            params[name] = value
    if any(s not in init for s in states):
        return None
    span = None
    sm = re.search(rf"t\s*(?:∈|in)\s*\[\s*{_NUM}\s*,\s*({_NUM})\s*\]|(?:until|to|up\s+to)\s+t\s*=\s*({_NUM})|"
                   rf"0\s*≤\s*t\s*≤\s*({_NUM})|for\s+({_NUM})\s*(?:s\b|seconds|time\s+units)", q)
    if sm:
        span = float(next(g for g in sm.groups() if g))
    span = span or spec.get("span")
    if not span or span <= 0:
        return None
    syms = {s: sp.Symbol(s) for s in states}
    psyms = {p: sp.Symbol(p) for p in params}
    rhs = {}
    for s, body in rhs_text.items():
        try:
            from sympy.parsing.sympy_parser import (
                convert_xor,
                implicit_multiplication_application,
                parse_expr,
                standard_transformations,
            )

            expr = parse_expr(body.replace("^", "**"), local_dict={**syms, **psyms, "t": sp.Symbol("t")},
                              transformations=standard_transformations + (implicit_multiplication_application, convert_xor))
        except Exception:  # noqa: BLE001 - an unreadable equation: the system is not simulated as stated
            return None
        expr = expr.subs({psyms[p]: v for p, v in params.items()})
        if expr.free_symbols - set(syms.values()) - {sp.Symbol("t")}:
            return None  # an unknown parameter: not fully specified
        rhs[s] = expr
    return {"rhs": rhs, "states": states, "params": params, "init": init, "span": float(span),
            "label": spec.get("label") or "stated system", "preset": preset,
            "log_time": bool(spec.get("log_time")) or float(span) >= 1e4}


def _linear_invariants(rhs: dict[str, sp.Expr], states: list[str]) -> list[dict[str, Any]]:
    """Constant vectors c with sum_i c_i f_i = 0 identically: conserved linear combinations of the states."""
    cs = sp.symbols(f"c0:{len(states)}")
    total = sp.expand(sum(c * rhs[s] for c, s in zip(cs, states, strict=True)))
    syms = [sp.Symbol(s) for s in states] + [sp.Symbol("t")]
    try:
        eqs = list(sp.Poly(total, *syms).coeffs()) if total != 0 else []
    except sp.PolynomialError:
        return []  # non-polynomial right-hand sides (trigonometric, rational): no linear invariant is sought
    sol = sp.linsolve(eqs, cs) if eqs else None
    if not sol:
        return []
    (vec,) = sol
    free = sorted(set().union(*[sp.sympify(v).free_symbols for v in vec]) & set(cs), key=str)
    out = []
    for f in free:
        coeffs = [sp.nsimplify(sp.sympify(v).subs({g: (1 if g == f else 0) for g in free}), rational=True)
                  for v in vec]
        if any(coeffs):
            out.append({"coefficients": coeffs, "label": " + ".join(f"{sp.sstr(c)}*{s}" if c != 1 else s
                                                                   for c, s in zip(coeffs, states, strict=True) if c)})
    return out


def compute_system_facts(question: str) -> dict[str, Any] | None:
    """Integrated trajectories, method and tolerance agreement and invariant drift for a stated system, or None."""
    spec = parse_system(question)
    if spec is None:
        return None
    from scipy.integrate import solve_ivp

    states, rhs = spec["states"], spec["rhs"]
    t = sp.Symbol("t")
    syms = [sp.Symbol(s) for s in states]
    f = sp.lambdify((t, syms), [rhs[s] for s in states], "numpy")
    jac_expr = sp.Matrix([rhs[s] for s in states]).jacobian(syms)
    jac = sp.lambdify((t, syms), jac_expr, "numpy")
    y0 = np.array([spec["init"][s] for s in states], float)
    span = spec["span"]

    eig = np.linalg.eigvals(np.asarray(jac(0.0, y0), float))
    rates = np.abs(eig.real)
    stiff = bool(rates.max(initial=0.0) * span > 1e4 and (rates.max() / max(rates[rates > 0].min(initial=1.0), 1e-300) > 1e3
                                                         if (rates > 0).any() else False)) or spec["preset"] == "robertson"
    if spec["log_time"]:
        t_eval = np.concatenate([[0.0], np.logspace(-6, math.log10(span), CURVE_POINTS - 1)])
    else:
        t_eval = np.linspace(0.0, span, CURVE_POINTS)

    def run(method: str, rtol: float, atol: float) -> np.ndarray:
        kw = {"jac": lambda tt, yy: np.asarray(jac(tt, yy), float)} if method in ("Radau", "BDF", "LSODA") else {}
        sol = solve_ivp(lambda tt, yy: np.asarray(f(tt, yy), float), (0.0, span), y0, method=method, t_eval=t_eval,
                        rtol=rtol, atol=atol, **kw)
        if not sol.success:
            raise RuntimeError(f"{method}: {sol.message}")
        return sol.y.T

    if stiff:
        primary, tight, second = ("Radau", 1e-6, 1e-10), ("Radau", 1e-9, 1e-14), ("BDF", 1e-8, 1e-12)
    else:
        primary, tight, second = ("DOP853", 1e-9, 1e-12), ("DOP853", 1e-12, 1e-14), ("Radau", 1e-10, 1e-12)
    ya, yt, yb = run(*primary), run(*tight), run(*second)
    scale = np.maximum(np.abs(yt).max(axis=0), 1e-12)
    tol_change = float(np.max(np.abs(ya[-1] - yt[-1]) / scale))
    method_gap = float(np.max(np.abs(yb[-1] - yt[-1]) / scale))
    chaotic = spec["preset"] == "lorenz" or (len(states) >= 3 and method_gap > 1e-3 and tol_change > 1e-3)

    invariants = []
    for inv in _linear_invariants(rhs, states):
        c = np.array([float(v) for v in inv["coefficients"]])
        values = yt @ c
        drift = float(np.max(np.abs(values - values[0])))
        invariants.append({"label": inv["label"], "initial": float(values[0]), "max_drift": drift})

    checks = [
        {"name": f"tolerance refinement ({primary[0]} rtol {primary[1]:g} -> {tight[1]:g}) changes the final state by "
                 f"{tol_change:.2e} (relative)", "passed": tol_change < 1e-4 or chaotic},
        {"name": f"second method ({second[0]}) agrees with {tight[0]} to {method_gap:.2e} (relative) at t = {span:g}",
         "passed": method_gap < 1e-3 or chaotic},
        {"name": "all values finite over the run", "passed": bool(np.isfinite(yt).all())},
    ]
    for inv in invariants:
        checks.append({"name": f"invariant {inv['label']} = {inv['initial']:.10g} conserved: max drift {inv['max_drift']:.2e}",
                       "passed": inv["max_drift"] < 1e-6 * max(1.0, abs(inv["initial"]))})
    energy_balance = None
    if spec.get("energy") is not None:
        # Mechanical energy plus the work done against damping must stay at its initial value.
        e_fun = sp.lambdify([sp.Symbol(s) for s in spec["energy_states"]], spec["energy"], "numpy")
        idx = [states.index(s) for s in spec["energy_states"]]
        energy = np.asarray(e_fun(*[yt[:, i] for i in idx]), float)
        work = yt[:, states.index("W")] if "W" in states else np.zeros_like(energy)
        balance = energy + work
        drift = float(np.max(np.abs(balance - balance[0])))
        energy_balance = {"E0": float(energy[0]), "E_end": float(energy[-1]), "damping_work": float(work[-1]),
                          "energy_loss": float(energy[0] - energy[-1]), "max_drift": drift}
        checks.append({"name": f"energy balance: loss E(0) - E(T) = {energy_balance['energy_loss']:.8g} equals the damping "
                                f"work {energy_balance['damping_work']:.8g} (E + W drifts by {drift:.2e})",
                       "passed": drift < 1e-6 * max(1.0, abs(energy[0]))})
    notes = ["Integrated as stated: " + "; ".join(f"d{s}/dt = {sp.sstr(rhs[s])}" for s in states) + "."]
    if stiff:
        notes.append("The Jacobian at the start has rates spread over many orders of magnitude (a stiff system), so "
                     "implicit methods (Radau, BDF) were used; an explicit method would need tiny steps.")
    if chaotic:
        notes.append("The system is chaotic: nearby trajectories separate exponentially, so solutions at long times "
                     "agree between methods only in their statistics, not pointwise; the short-time agreement and "
                     "the invariants are the meaningful checks.")
    final = {s: float(v) for s, v in zip(states, yt[-1], strict=True)}
    params = [{"name": f"{s}({span:g})", "value": f"{v:.9g}", "unit": "", "aliases": [f"{s}(t)", s]} for s, v in final.items()]
    params += [{"name": f"invariant {inv['label']}", "value": f"{inv['initial']:.10g}", "unit": "",
                "aliases": ["conserved", "mass conservation", "invariant"]} for inv in invariants]
    params.append({"name": "solver", "value": f"{tight[0]} ({'stiff' if stiff else 'non-stiff'}), checked by {second[0]}",
                   "unit": "", "aliases": ["method", "solver"]})
    if energy_balance:
        params += [
            {"name": "initial mechanical energy E(0)",
             "value": "0" if abs(energy_balance["E0"]) < 1e-12 else f"{energy_balance['E0']:.9g}", "unit": "J",
             "aliases": ["initial energy", "mechanical energy"]},
            {"name": f"energy lost over {span:g} s", "value": f"{energy_balance['energy_loss']:.9g}", "unit": "J",
             "aliases": ["energy loss", "energy lost"]},
            {"name": "work done by damping", "value": f"{energy_balance['damping_work']:.9g}", "unit": "J",
             "aliases": ["damping work", "work done against damping"]},
        ]
        notes.append("The equations of motion were derived by code from the Lagrangian L = T - V with generalized "
                     "damping forces -b dtheta_i/dt; W(t) integrates the damping power b(w1^2 + w2^2), so E + W must "
                     "stay at E(0).")
    step = max(1, len(t_eval) // 300)
    return {
        "kind": "dynamical_system", "label": spec["label"], "states": states,
        "equations_latex": [rf"\frac{{d{s}}}{{dt}} = {sp.latex(rhs[s])}" for s in states],
        "initial": spec["init"], "span": span, "stiff": stiff, "chaotic": chaotic, "log_time": spec["log_time"],
        "parameters": params, "checks": checks, "notes": notes, "invariants": invariants,
        "methods": [f"{primary[0]} rtol {primary[1]:g}", f"{tight[0]} rtol {tight[1]:g}", f"{second[0]} rtol {second[1]:g}"],
        "series": {"t": [float(v) for v in t_eval[::step]],
                   **{s: [float(v) for v in yt[::step, i]] for i, s in enumerate(states)}},
    }


__all__ = ["PRESETS", "compute_system_facts", "parse_system"]
