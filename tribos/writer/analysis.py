"""
Research-grounded checks on the code-computed results of an initial-value problem (tribos.writer.facts).

Convergence study (code verification). Following Roache's grid-convergence method as standardised in ASME V&V 20-2009
(Oberkampf & Roy, Verification and Validation in Scientific Computing, 2010): the fixed-step RK4 solution is repeated
on four systematically halved steps. With an exact solution the error of each run is measured directly and the
observed order of accuracy p = log2(E_h / E_{h/2}) is compared with the formal order 4; without one, the three finest
runs give a Richardson estimate of p, the extrapolated value and the grid convergence index GCI = 1.25 |e| / (2^p - 1).
Oscillatory convergence (differences of alternating sign) is reported as such: Richardson extrapolation does not apply
to it. A step-error fit C h^4 then predicts the error at the step the question asked for, and the measured error must
agree with it unless both sit at the round-off floor.

Physics consistency (PhySense, arXiv 2505.24823; Chung et al., arXiv 2506.06214; CMPhysBench, arXiv 2508.18124, which
proposes conservation and limiting-case tests as verifiers). For a x'' + b x' + c x = F(t) with constant coefficients:
- energy balance (work-energy theorem): the change of 1/2 a x'^2 + 1/2 c x^2 over the run equals the work of the forcing
  minus the energy dissipated by damping, both integrated numerically along the exact solution;
- stability: every characteristic root has a negative real part, so the free response decays (time constant 2a/b);
- the steady-state amplitude from the closed-form formula equals the amplitude of the solved steady-state part, an
  independent route to the same number;
- limiting cases of the amplitude formula X(w): the static limit w -> 0 gives F0/c, the undamped limit b -> 0 gives
  F0/|c - a w^2|, and X -> 0 as w -> infinity.
The amplitude formula is also sampled over frequency (the frequency response), with the resonance peak when it exists.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp

CONVERGENCE_RUNS = 4
FORMAL_ORDER = 4.0
ORDER_TOLERANCE = 0.3
ROUNDOFF_FLOOR = 1e-12  # relative to the solution scale: below it a measured error is round-off, not truncation
RESPONSE_POINTS = 241
MAX_CONVERGENCE_STEPS = 400_000


def _sig(value: float, digits: int = 6) -> str:
    if value == 0 or not math.isfinite(value):
        return str(value)
    return f"{value:.{digits}g}"


def _base_steps(rhs: Any, y0: list[float], t0: float, span: float, extra_rate: float) -> int:
    """Steps of the coarsest run: at most span/40, and small enough that h times the fastest rate of the problem
    (Jacobian eigenvalues at the start, the forcing frequency) is at most 0.25, inside RK4's asymptotic range."""
    y = np.array(y0, dtype=float)
    n = len(y)
    jac = np.empty((n, n))
    f0 = rhs(t0, y)
    for k in range(n):
        dy = np.zeros(n)
        dy[k] = 1e-6 * max(1.0, abs(y[k]))
        jac[:, k] = (rhs(t0, y + dy) - f0) / dy[k]
    rate = max([float(np.max(np.abs(np.linalg.eigvals(jac)))) if np.all(np.isfinite(jac)) else 0.0, extra_rate, 1e-9])
    return max(40, math.ceil(span * rate / 0.25))


def convergence_study(rhs: Any, y0: list[float], t0: float, t1: float, rk4: Any, exact: Any | None,
                      requested_step: float, requested_error: float | None, forcing_rate: float = 0.0) -> dict[str, Any] | None:
    """Observed order of accuracy of the RK4 runs, Richardson extrapolation and GCI at the final time, and the error
    predicted at the requested step; None when the runs would be too long."""
    span = t1 - t0
    if span <= 0:
        return None
    n0 = _base_steps(rhs, y0, t0, span, forcing_rate)
    if n0 * 2 ** (CONVERGENCE_RUNS - 1) > MAX_CONVERGENCE_STEPS:
        return None
    runs = []
    coarse_times: np.ndarray | None = None
    for k in range(CONVERGENCE_RUNS):
        n = n0 * 2**k
        times, ys = rk4(rhs, y0, t0, t1, span / n)
        if coarse_times is None:
            coarse_times = times
        stride = 2**k
        run: dict[str, Any] = {"step": span / n, "steps": n, "final": float(ys[-1, 0])}
        if exact is not None:
            ref = np.array([float(exact(tt)) for tt in coarse_times])
            run["max_error"] = float(np.max(np.abs(ys[::stride, 0] - ref)))
        runs.append(run)

    out: dict[str, Any] = {
        "method": "RK4 on four halved steps (observed order of accuracy; Richardson extrapolation and GCI per ASME V&V 20)",
        "runs": [{"step": _sig(r["step"], 4), "steps": r["steps"], "final_value": _sig(r["final"], 10),
                  **({"max_error": _sig(r["max_error"], 3)} if "max_error" in r else {})} for r in runs],
        "formal_order": FORMAL_ORDER,
        "checks": [],
    }
    scale = max(1e-300, max(abs(r["final"]) for r in runs), max((abs(v) for v in y0), default=0.0))

    if exact is not None:
        errs = [r["max_error"] for r in runs]
        orders = [math.log2(errs[i] / errs[i + 1]) if errs[i + 1] > 0 and errs[i] > 0 else float("nan")
                  for i in range(len(errs) - 1)]
        out["observed_orders"] = [_sig(p, 4) for p in orders]
        observed = orders[-1]
        out["observed_order"] = _sig(observed, 4)
        ok = math.isfinite(observed) and abs(observed - FORMAL_ORDER) <= ORDER_TOLERANCE
        out["checks"].append({"name": f"observed order of accuracy {_sig(observed, 4)} matches RK4's formal order 4",
                              "passed": bool(ok)})
        # Error constant from the finest run, then the prediction at the requested step.
        c_fit = errs[-1] / runs[-1]["step"] ** FORMAL_ORDER
        predicted = c_fit * requested_step**FORMAL_ORDER
        out["error_constant"] = _sig(c_fit, 3)
        out["predicted_error_at_requested_step"] = _sig(predicted, 3)
        floor = ROUNDOFF_FLOOR * scale
        if requested_error is not None:
            if predicted < floor and requested_error < 100 * floor:
                out["notes"] = ["the requested step is so small that its error is at the round-off level of double "
                                "precision; the order of accuracy is measured on larger steps instead"]
            else:
                ratio = requested_error / predicted if predicted > 0 else float("inf")
                out["checks"].append({
                    "name": "measured RK4 error at the requested step agrees with the fourth-order prediction "
                            f"(measured/predicted = {_sig(ratio, 3)})",
                    "passed": bool(0.2 <= ratio <= 5.0)})

    # Richardson extrapolation on the three finest runs at the final time (works without an exact solution).
    f1, f2, f3 = runs[-1]["final"], runs[-2]["final"], runs[-3]["final"]
    d21, d32 = f2 - f1, f3 - f2
    rich: dict[str, Any] = {}
    if d21 == 0 or d32 == 0 or abs(d21) < ROUNDOFF_FLOOR * scale:
        rich["status"] = "converged to round-off"
    elif (d21 > 0) != (d32 > 0):
        rich["status"] = "oscillatory convergence: Richardson extrapolation does not apply"
    else:
        p = math.log(abs(d32 / d21)) / math.log(2)
        extrapolated = f1 + (f1 - f2) / (2**p - 1)
        gci = 1.25 * abs(d21 / f1) / (2**p - 1) if f1 != 0 else float("nan")
        rich.update(status="monotone convergence", observed_order=_sig(p, 4), extrapolated_value=_sig(extrapolated, 10),
                    gci_fine=_sig(gci, 3))
        if exact is not None:
            rich["extrapolation_error"] = _sig(abs(extrapolated - float(exact(t1))), 3)
        else:
            out["observed_order"] = _sig(p, 4)
            out["checks"].append({"name": f"Richardson observed order {_sig(p, 4)} at the final time matches RK4's "
                                          "formal order 4", "passed": bool(abs(p - FORMAL_ORDER) <= 0.5)})
    out["richardson_at_final_time"] = {"time": _sig(t1, 6), **rich}
    return out


# Physics consistency ------------------------------------------------------------------------------------------------
def _roots_latex(roots: list[sp.Expr]) -> str:
    """Characteristic roots as a reader writes them: a complex-conjugate pair as r = a ± b i."""
    if len(roots) == 2 and sp.im(roots[0]) != 0 and sp.simplify(roots[0] - sp.conjugate(roots[1])) == 0:
        re_part = sp.nsimplify(sp.re(roots[0]))
        im_part = sp.nsimplify(sp.Abs(sp.im(roots[0])))
        return rf"r = {sp.latex(re_part)} \pm {sp.latex(im_part)}\,i"
    return "r = " + ",\\ ".join(sp.latex(sp.nsimplify(z)) for z in roots)



def _amplitude_expr(a: sp.Expr, b: sp.Expr, c: sp.Expr, f0: sp.Expr, w: sp.Expr) -> sp.Expr:
    return f0 / sp.sqrt((c - a * w**2) ** 2 + (b * w) ** 2)


def _harmonics(forcing: sp.Expr, t: sp.Symbol) -> dict[sp.Expr, tuple[sp.Expr, sp.Expr]]:
    """The forcing as a sum of harmonics: {w: (A, B)} for A cos(w t) + B sin(w t); empty when it is not one."""
    out: dict[sp.Expr, tuple[sp.Expr, sp.Expr]] = {}
    for term in sp.Add.make_args(sp.expand(forcing)):
        coeff, fn = term.as_independent(t, as_Add=False)
        if not isinstance(fn, (sp.sin, sp.cos)):
            return {}
        w = sp.simplify(fn.args[0] / t)
        if w.has(t) or not w.is_positive:
            return {}
        a_, b_ = out.get(w, (sp.Integer(0), sp.Integer(0)))
        out[w] = (a_ + coeff, b_) if isinstance(fn, sp.cos) else (a_, b_ + coeff)
    return out


def _resonance_checks(a: sp.Expr, b: sp.Expr, c: sp.Expr, forcing: sp.Expr, t: sp.Symbol,
                      exact: sp.Expr) -> list[dict[str, Any]]:
    """Undamped forcing at the natural frequency w_n: the solution must contain a term growing linearly in time,
    t (A sin(w_n t) - B cos(w_n t)) / (2 a w_n) for the harmonic A cos + B sin, checked against the exact solution."""
    if b != 0 or forcing == 0:
        return []
    wn = sp.sqrt(c / a)
    harm = _harmonics(forcing, t)
    if wn not in harm:
        return []
    A, B = harm[wn]
    expected = t * (A * sp.sin(wn * t) - B * sp.cos(wn * t)) / (2 * a * wn)
    secular = sp.Integer(0)
    for term in sp.Add.make_args(sp.expand(exact)):
        for trig in (sp.sin(wn * t), sp.cos(wn * t)):
            if term.has(trig):
                k = sp.simplify(term / trig)  # the term's own factor: t * constant for a secular term
                if not k.has(sp.sin, sp.cos, sp.exp) and k.is_polynomial(t) and sp.degree(k, t) == 1:
                    secular += term
                break
    growth = sp.nsimplify(sp.sqrt(A**2 + B**2) / (2 * a * wn))
    return [{"name": "resonance: undamped forcing at the natural frequency gives a term growing linearly in time, "
                     "with the amplitude growth rate F0/(2 m w_n)",
             "passed": bool(sp.simplify(secular - expected) == 0),
             "detail": rf"\text{{growth rate }} {sp.latex(growth)}",
             "_growth": growth}]


def physics_checks(coeffs: list[sp.Expr], forcing: sp.Expr, t: sp.Symbol, exact: sp.Expr, steady: sp.Expr | None,
                   sinusoid: tuple[sp.Expr, sp.Expr, sp.Expr] | None, t0: float, t1: float,
                   x_unit: str, t_unit: str) -> dict[str, Any]:
    """Energy balance, stability, amplitude cross-check and limiting cases for a x'' + b x' + c x = F(t)."""
    from scipy.integrate import quad

    a, b, c = coeffs
    checks: list[dict[str, Any]] = []
    quantities: list[dict[str, Any]] = []
    si = x_unit == "m" and t_unit == "s"
    energy_unit = "J" if si else ""

    # Energy balance along the exact solution: dE = W_forcing - D_damping.
    v = sp.diff(exact, t)
    x_fn = sp.lambdify(t, exact, "math")
    v_fn = sp.lambdify(t, v, "math")
    f_fn = sp.lambdify(t, forcing, "math")
    af, bf, cf = float(a), float(b), float(c)

    def energy(tt: float) -> float:
        return 0.5 * af * v_fn(tt) ** 2 + 0.5 * cf * x_fn(tt) ** 2

    span = t1 - t0
    if span > 0:
        limit = max(200, int(span * 50))
        work, _ = quad(lambda tt: f_fn(tt) * v_fn(tt), t0, t1, limit=limit, epsabs=1e-13, epsrel=1e-12)
        dissipated, _ = quad(lambda tt: bf * v_fn(tt) ** 2, t0, t1, limit=limit, epsabs=1e-13, epsrel=1e-12)
        change = energy(t1) - energy(t0)
        residual = abs(change - (work - dissipated))
        tol = 1e-8 * max(1e-12, abs(work), abs(dissipated), abs(energy(t0)), abs(energy(t1)))
        checks.append({"name": "energy balance: change in kinetic + potential energy equals forcing work minus damping "
                               "losses (work-energy theorem)", "passed": bool(residual <= tol),
                       "detail": f"residual {_sig(residual, 2)}"})
        quantities += [
            {"name": "work done by the forcing", "value": _sig(work, 6), "unit": energy_unit},
            {"name": "energy dissipated by damping", "value": _sig(dissipated, 6), "unit": energy_unit},
            {"name": "change in mechanical energy", "value": _sig(change, 6), "unit": energy_unit},
        ]

    # Stability of the free response.
    r = sp.Symbol("r")
    roots = sp.Poly(a * r**2 + b * r + c, r).all_roots()
    re_parts = [float(sp.re(sp.N(z))) for z in roots]
    stable = all(x < 0 for x in re_parts)
    distinct = len({sp.nsimplify(z) for z in roots}) == len(roots)
    if stable:
        name, ok = "stability: every characteristic root has a negative real part, so the transient decays", True
    elif all(x <= 0 for x in re_parts) and distinct:
        # Undamped: a property of the system, not a defect of the answer.
        name, ok = ("stability: marginally stable (roots on the imaginary axis, no damping), so the free oscillation "
                    "neither decays nor grows"), True
    else:
        name, ok = "stability: a characteristic root has a non-negative real part, so the free response grows", False
    checks.append({"name": name, "passed": ok, "detail": _roots_latex(roots)})
    for res in _resonance_checks(a, b, c, forcing, t, exact):
        growth = res.pop("_growth")
        checks.append(res)
        rate = f"{x_unit}/{t_unit}" if x_unit and t_unit else ""
        quantities.append({"name": "resonant amplitude growth rate", "exact_latex": sp.latex(growth),
                           "value": _sig(float(growth), 6), "unit": rate})
    if stable and b > 0:
        tau = 2 * a / b
        quantities.append({"name": "decay time constant", "exact_latex": sp.latex(sp.nsimplify(tau)),
                           "value": _sig(float(tau), 6), "unit": t_unit})
        quantities.append({"name": "settling time (2% band, about 4 time constants)",
                           "value": _sig(float(4 * tau), 6), "unit": t_unit})

    response = None
    # At undamped resonance the amplitude formula is infinite: no steady state to cross-check, limit or plot (the
    # resonance check above covers it).
    resonant = sinusoid is not None and sp.simplify((c - a * sinusoid[2] ** 2) ** 2 + (b * sinusoid[2]) ** 2) == 0
    if sinusoid is not None and not resonant:
        p, q, w_force = sinusoid
        f0 = sp.sqrt(p**2 + q**2)
        w = sp.Symbol("omega", positive=True)
        bs = sp.Symbol("b", nonnegative=True)
        amp_w = _amplitude_expr(a, b, c, f0, w)
        amp_formula = amp_w.subs(w, w_force)

        # Independent route: amplitude of the solved steady-state part, A cos(wt) + B sin(wt).
        if steady is not None:
            st = sp.expand(steady)
            ca = st.coeff(sp.cos(w_force * t))
            sa = st.coeff(sp.sin(w_force * t))
            if not (ca == 0 and sa == 0):
                solved_amp = sp.sqrt(ca**2 + sa**2)
                same = sp.simplify(solved_amp - amp_formula) == 0
                checks.append({"name": "steady-state amplitude from the closed-form formula equals the amplitude of the "
                                       "solved steady-state part", "passed": bool(same)})

        # Limiting cases of X(w) (and of X with symbolic damping b).
        static = sp.limit(amp_w, w, 0)
        checks.append({"name": "static limit: as the forcing frequency goes to 0 the amplitude tends to F0/k",
                       "passed": bool(sp.simplify(static - f0 / c) == 0)})
        checks.append({"name": "high-frequency limit: the amplitude tends to 0 as the forcing frequency grows",
                       "passed": bool(sp.limit(amp_w, w, sp.oo) == 0)})
        if sp.simplify(c - a * w_force**2) != 0:
            undamped = sp.limit(_amplitude_expr(a, bs, c, f0, w_force), bs, 0)
            checks.append({"name": "undamped limit: with no damping the amplitude becomes F0/|k - m w^2|",
                           "passed": bool(sp.simplify(undamped - f0 / sp.Abs(c - a * w_force**2)) == 0)})

        quantities.append({"name": "static deflection F0/k", "exact_latex": sp.latex(sp.nsimplify(f0 / c)),
                           "value": _sig(float(f0 / c), 6), "unit": x_unit})
        quantities.append({"name": "dynamic magnification factor X/(F0/k)",
                           "exact_latex": sp.latex(sp.nsimplify(sp.simplify(amp_formula / (f0 / c)))),
                           "value": _sig(float(amp_formula / (f0 / c)), 6), "unit": ""})
        zeta = b / (2 * sp.sqrt(a * c))
        wn = sp.sqrt(c / a)
        peak = None
        if zeta < 1 / sp.sqrt(2):
            wr = wn * sp.sqrt(1 - 2 * zeta**2)
            peak = (float(wr), float(amp_w.subs(w, wr)))
            quantities.append({"name": "resonance frequency (peak of the amplitude)", "exact_latex": sp.latex(sp.nsimplify(wr)),
                               "value": _sig(float(wr), 6), "unit": f"rad/{t_unit}" if t_unit else "rad per unit time"})
            quantities.append({"name": "peak steady-state amplitude", "value": _sig(peak[1], 6), "unit": x_unit})

        # Frequency response for the plot.
        top = max(3 * float(wn), 1.5 * float(w_force))
        amp_fn = sp.lambdify(w, amp_w, "numpy")
        grid = np.linspace(0.0, top, RESPONSE_POINTS)
        values = np.asarray(amp_fn(grid), dtype=float)
        if np.all(np.isfinite(values)):
            marks = [[round(float(w_force), 6), float(_sig(float(amp_formula), 6)), "forcing"]]
            if peak is not None:
                marks.append([round(peak[0], 6), float(_sig(peak[1], 6)), "resonance"])
            response = {"omega": [round(float(x), 6) for x in grid], "amplitude": [float(_sig(float(y), 6)) for y in values],
                        "marks": marks, "unit_rate": f"rad/{t_unit}" if t_unit else "", "unit_amplitude": x_unit}
    return {"checks": checks, "quantities": quantities, "frequency_response": response}


__all__ = ["convergence_study", "physics_checks"]
