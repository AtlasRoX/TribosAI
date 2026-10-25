"""Independent numerical verification of an analytical ODE solution: the numbers an engineering answer reports.

Given the ODE a question states (see stated_ode.py), the analytical solution the mathematics agent verified and the
time window, this computes, without any model call:

- the residual of the analytical solution in the ODE (symbolic, and its numeric maximum on a grid);
- the initial conditions it satisfies;
- fixed-step fourth-order Runge-Kutta solutions at halving step sizes, their maximum displacement and velocity errors
  against the analytical solution, and the observed order of convergence (4 expected);
- the analytical and numerical values at sample times;
- for a linear second-order system m x'' + c x' + k x = f(t): the energy balance
  E(T) - E(0) = W_in - W_d, with E = m v^2 / 2 + k x^2 / 2, W_in = integral of f v dt, W_d = integral of c v^2 dt;
- a self-contained Python script that reproduces every number.

Nothing is estimated: a quantity that cannot be computed for the stated system is left out, never filled in.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import sympy as sp

from ..axiom.engine import _normalize_ode_primes, safe_parse_equation, safe_parse_expr
from .stated_ode import stated_ode_system

STEP_SIZES = (0.1, 0.05, 0.025, 0.0125)
_trapezoid = getattr(np, "trapezoid", None) or np.trapz  # NumPy 2 renamed trapz
SAMPLE_TIMES = (0.0, 1.0, 2.0, 5.0, 10.0)
MAX_STEPS = 400_000  # the finest run stays well under a second


def _rk4(f: Any, y0: np.ndarray, t_end: float, h: float) -> tuple[np.ndarray, np.ndarray]:
    n = max(1, int(round(t_end / h)))
    h = t_end / n
    t = np.linspace(0.0, t_end, n + 1)
    y = np.empty((n + 1, len(y0)))
    y[0] = y0
    for i in range(n):
        ti, yi = t[i], y[i]
        k1 = f(ti, yi)
        k2 = f(ti + h / 2, yi + h / 2 * k1)
        k3 = f(ti + h / 2, yi + h / 2 * k2)
        k4 = f(ti + h, yi + h * k3)
        y[i + 1] = yi + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return t, y


def _linear_coefficients(expr: sp.Expr, top: sp.Symbol, v: sp.Symbol, x: sp.Symbol, t: sp.Symbol) -> dict[str, Any] | None:
    """m, c, k and the forcing f(t) of m x'' + c x' + k x - f(t) = 0, or None when the ODE is not linear with constant
    coefficients."""
    poly = sp.expand(expr)
    m, c, k = (poly.coeff(s) for s in (top, v, x))
    forcing = sp.simplify(-(poly - m * top - c * v - k * x))
    if any(q.free_symbols for q in (m, c, k)) or forcing.free_symbols - {t}:
        return None
    if m == 0:
        return None
    return {"m": float(m), "c": float(c), "k": float(k), "forcing": forcing}


def _harmonic_forcing(forcing: sp.Expr, t: sp.Symbol) -> tuple[float, float] | None:
    """(F0, omega) of a forcing a*cos(w t) + b*sin(w t) with one frequency (F0 = sqrt(a^2 + b^2)); None otherwise."""
    trig = [a for a in sp.preorder_traversal(forcing) if isinstance(a, (sp.cos, sp.sin))]
    omegas = {sp.simplify(a.args[0] / t) for a in trig}
    if len(omegas) != 1:
        return None
    w = omegas.pop()
    if w.free_symbols:
        return None
    a = sp.simplify(forcing.coeff(sp.cos(w * t)))
    b = sp.simplify(forcing.coeff(sp.sin(w * t)))
    if a.free_symbols or b.free_symbols or sp.simplify(forcing - a * sp.cos(w * t) - b * sp.sin(w * t)) != 0:
        return None
    return float(sp.sqrt(a**2 + b**2)), abs(float(w))


def characteristic_parameters(m: float, c: float, k: float, forcing: sp.Expr, t: sp.Symbol) -> dict[str, dict[str, Any]]:
    """The standard parameters of m x'' + c x' + k x = f(t), each {formula, value}: computed here so an answer never
    re-derives (and mis-derives) them."""
    out: dict[str, dict[str, Any]] = {}
    if m <= 0 or k <= 0 or c < 0:
        return out
    wn = math.sqrt(k / m)
    zeta = c / (2 * math.sqrt(m * k))
    sigma = c / (2 * m)
    out["natural_frequency"] = {"formula": "omega_n = sqrt(k/m)", "value": wn, "unit": "rad/s"}
    out["damping_ratio"] = {"formula": "zeta = c / (2 sqrt(m k))", "value": zeta, "unit": ""}
    regime = "underdamped" if zeta < 1 else "critically damped" if zeta == 1 else "overdamped"
    out["regime"] = {"formula": "zeta < 1 underdamped, = 1 critical, > 1 overdamped", "value": regime, "unit": ""}
    if zeta < 1:
        out["damped_frequency"] = {"formula": "omega_d = omega_n sqrt(1 - zeta^2)", "value": wn * math.sqrt(1 - zeta**2),
                                   "unit": "rad/s"}
    if sigma > 0:
        out["decay_rate"] = {"formula": "sigma = c / (2 m)", "value": sigma, "unit": "1/s"}
        out["time_constant"] = {"formula": "tau = 1 / sigma = 2 m / c", "value": 1 / sigma, "unit": "s"}
    harmonic = _harmonic_forcing(forcing, t)
    if harmonic is not None:
        f0, w = harmonic
        denom = math.hypot(k - m * w**2, c * w)
        if denom > 0:
            amp = f0 / denom
            phase = math.atan2(c * w, k - m * w**2)  # lag of the displacement behind the force, in [0, pi]
            out["forcing_amplitude"] = {"formula": "F0", "value": f0, "unit": "N"}
            out["forcing_frequency"] = {"formula": "omega", "value": w, "unit": "rad/s"}
            out["frequency_ratio"] = {"formula": "r = omega / omega_n", "value": w / wn, "unit": ""}
            out["static_deflection"] = {"formula": "F0 / k", "value": f0 / k, "unit": "m"}
            out["steady_state_amplitude"] = {"formula": "X = F0 / sqrt((k - m omega^2)^2 + (c omega)^2)", "value": amp,
                                             "unit": "m"}
            out["dynamic_amplification"] = {"formula": "X / (F0 / k)", "value": amp / (f0 / k), "unit": ""}
            out["phase_lag"] = {"formula": "phi = atan2(c omega, k - m omega^2)", "value": phase, "unit": "rad",
                                "degrees": math.degrees(phase)}
            out["mean_steady_power"] = {"formula": "P = c omega^2 X^2 / 2", "value": 0.5 * c * w**2 * amp**2, "unit": "W"}
    return out


def verify_ode_solution(equation: str, func: str, ics: dict[str, Any], solution: str, t_end: float) -> dict[str, Any] | None:
    """The verification report (see the module docstring), or None when the stated ODE or the solution cannot be
    evaluated."""
    system = stated_ode_system(equation, func, ics)
    m_func = re.match(r"^\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s*\)\s*$", func or "")
    if system is None or m_func is None or not (0 < t_end <= 1e4):
        return None
    fname, var = m_func.group(1), m_func.group(2)
    t = sp.Symbol(var)
    states = system["state_names"]
    order = len(states)
    syms = [sp.Symbol(s) for s in states]
    try:
        sol_text = solution.split("=", 1)[1] if re.match(rf"^\s*{re.escape(fname)}\s*\(", solution) and "=" in solution else solution
        x_exact = safe_parse_expr(sol_text, local_dict={var: t})
        rhs_exprs = [safe_parse_expr(system["rhs"][s], local_dict={var: t, **{s2: sp.Symbol(s2) for s2 in states}}) for s in states]
    except Exception:  # noqa: BLE001 - an unreadable solution is not verified, never guessed
        return None
    if x_exact.free_symbols - {t}:
        return None
    v_exact = sp.diff(x_exact, t)
    fx = sp.lambdify(t, x_exact, "numpy")
    fv = sp.lambdify(t, v_exact, "numpy")
    rhs_fn = sp.lambdify((t, *syms), rhs_exprs, "numpy")

    def f(ti: float, y: np.ndarray) -> np.ndarray:
        return np.array(rhs_fn(ti, *y), dtype=float)

    # Residual of the analytical solution in the ODE as stated.
    unknown = sp.Function(fname)
    lhs, rhs, _ = safe_parse_equation(_normalize_ode_primes(equation, fname, var), local_dict={var: t, fname: unknown})
    residual_expr = sp.simplify((lhs - rhs).subs(unknown(t), x_exact).doit())
    grid = np.linspace(0.0, t_end, 2001)
    residual_fn = sp.lambdify(t, residual_expr, "numpy")
    residual_max = float(np.max(np.abs(np.broadcast_to(residual_fn(grid), grid.shape))))

    y0 = np.array([system["initial_state"][s] for s in states], dtype=float)
    ic_checks = [{"condition": f"{fname}(0)", "stated": float(y0[0]), "analytical": float(fx(0.0))}]
    if order == 2:
        ic_checks.append({"condition": f"{fname}'(0)", "stated": float(y0[1]), "analytical": float(fv(0.0))})

    convergence: list[dict[str, Any]] = []
    finest: tuple[np.ndarray, np.ndarray] | None = None
    for h in STEP_SIZES:
        if t_end / h > MAX_STEPS:
            continue
        ts, ys = _rk4(f, y0, t_end, h)
        ex, ev = np.asarray(fx(ts), dtype=float) * np.ones_like(ts), np.asarray(fv(ts), dtype=float) * np.ones_like(ts)
        row = {"h": h, "steps": len(ts) - 1, "max_error_x": float(np.max(np.abs(ys[:, 0] - ex)))}
        if order == 2:
            row["max_error_v"] = float(np.max(np.abs(ys[:, 1] - ev)))
        if convergence and convergence[-1]["max_error_x"] > 0 and row["max_error_x"] > 0:
            row["observed_order"] = math.log2(convergence[-1]["max_error_x"] / row["max_error_x"])
        convergence.append(row)
        finest = (ts, ys)
    if finest is None:
        return None

    ts, ys = finest
    samples = []
    for when in sorted({*(s for s in SAMPLE_TIMES if s <= t_end), t_end}):
        num = float(np.interp(when, ts, ys[:, 0]))
        exact = float(fx(when))
        samples.append({"t": when, "analytical": exact, "numerical": num, "error": abs(num - exact)})

    report: dict[str, Any] = {
        "equation": equation,
        "function": func,
        "initial_state": system["initial_state"],
        "solution": str(x_exact),
        "t_end": t_end,
        "residual_symbolic": str(residual_expr),
        "residual_max": residual_max,
        "initial_conditions": ic_checks,
        "method": "classical fourth-order Runge-Kutta, fixed step",
        "convergence": convergence,
        "samples": samples,
    }

    if order == 2:
        top, vs, xs = sp.Symbol("__top__"), sp.Symbol(states[1]), sp.Symbol(states[0])
        expr = (lhs - rhs).subs(sp.Derivative(unknown(t), (t, 2)), top).subs(sp.Derivative(unknown(t), t), vs).subs(unknown(t), xs)
        coeffs = _linear_coefficients(expr, top, vs, xs, t)
        if coeffs is not None:
            fine = np.linspace(0.0, t_end, 20001)
            xe = np.asarray(fx(fine), dtype=float) * np.ones_like(fine)
            ve = np.asarray(fv(fine), dtype=float) * np.ones_like(fine)
            force = np.asarray(sp.lambdify(t, coeffs["forcing"], "numpy")(fine), dtype=float) * np.ones_like(fine)
            energy = 0.5 * coeffs["m"] * ve**2 + 0.5 * coeffs["k"] * xe**2
            w_in = float(_trapezoid(force * ve, fine))
            w_d = float(_trapezoid(coeffs["c"] * ve**2, fine))
            report["parameters"] = characteristic_parameters(coeffs["m"], coeffs["c"], coeffs["k"], coeffs["forcing"], t)
            report["energy"] = {
                "m": coeffs["m"], "c": coeffs["c"], "k": coeffs["k"], "forcing": str(coeffs["forcing"]),
                "E0": float(energy[0]), "ET": float(energy[-1]), "work_in": w_in, "work_damping": w_d,
                "balance_residual": float(energy[-1] - energy[0] - (w_in - w_d)),
            }
    report["script"] = reproduction_script(report, system)
    return report


def reproduction_script(report: dict[str, Any], system: dict[str, Any]) -> str:
    """A standalone NumPy script that recomputes the convergence table and the energy balance."""
    states = system["state_names"]
    rhs = ", ".join(system["rhs"][s] for s in states)
    y0 = ", ".join(repr(float(system["initial_state"][s])) for s in states)
    sol = report["solution"]
    energy = report.get("energy")
    lines = [
        '"""Reproduces the verification of the analytical solution (generated by Tribos)."""',
        "import numpy as np",
        "from numpy import sin, cos, tan, exp, log, sqrt, pi",
        "trapezoid = getattr(np, 'trapezoid', None) or np.trapz",
        "",
        f"T_END = {report['t_end']!r}",
        f"y0 = np.array([{y0}])",
        "",
        f"def rhs(t, y):\n    {', '.join(states)}, = y\n    return np.array([{rhs}])",
        "",
        f"def exact(t):\n    return {sol}",
        "",
        "def exact_rate(t, eps=1e-6):\n    return (exact(t + eps) - exact(t - eps)) / (2 * eps)",
        "",
        "def rk4(h):",
        "    n = int(round(T_END / h)); h = T_END / n",
        "    t = np.linspace(0.0, T_END, n + 1); y = np.empty((n + 1, len(y0))); y[0] = y0",
        "    for i in range(n):",
        "        k1 = rhs(t[i], y[i]); k2 = rhs(t[i] + h / 2, y[i] + h / 2 * k1)",
        "        k3 = rhs(t[i] + h / 2, y[i] + h / 2 * k2); k4 = rhs(t[i] + h, y[i] + h * k3)",
        "        y[i + 1] = y[i] + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)",
        "    return t, y",
        "",
        "prev = None",
        f"for h in {tuple(r['h'] for r in report['convergence'])}:",
        "    t, y = rk4(h)",
        "    err = np.max(np.abs(y[:, 0] - exact(t)))",
        "    order = np.log2(prev / err) if prev else float('nan')",
        "    print(f'h = {h:<7} max |x - x_exact| = {err:.3e}  observed order = {order:.2f}')",
        "    prev = err",
    ]
    if energy:
        lines += [
            "",
            f"m, c, k = {energy['m']!r}, {energy['c']!r}, {energy['k']!r}",
            f"def force(t):\n    return {energy['forcing']} + 0 * t",
            "t = np.linspace(0.0, T_END, 20001); x = exact(t); v = exact_rate(t)",
            "E = 0.5 * m * v**2 + 0.5 * k * x**2",
            "W_in = trapezoid(force(t) * v, t); W_d = trapezoid(c * v**2, t)",
            "print(f'E(0) = {E[0]:.6f} J, E(T) = {E[-1]:.6f} J, W_in = {W_in:.6f} J, W_d = {W_d:.6f} J')",
            "print(f'balance residual E(T) - E(0) - (W_in - W_d) = {E[-1] - E[0] - (W_in - W_d):.3e} J')",
        ]
    return "\n".join(lines) + "\n"


__all__ = ["STEP_SIZES", "reproduction_script", "verify_ode_solution"]
