"""
Dynamis numerics, dynamical systems, ODE simulation, and optimization engine powered by SciPy, NumPy, and SymPy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import numpy as np
import sympy as sp
from scipy import integrate, optimize

from tribos.axiom.engine import safe_parse_equation, safe_parse_expr
from tribos.axiom.safe_expr import check_math_text

ODE_PRESETS: dict[str, dict[str, Any]] = {
    "harmonic_oscillator": {
        "rhs": {"x": "v", "v": "-omega^2 * x"},
        "initial_state": {"x": 1.0, "v": 0.0},
        "parameters": {"omega": 1.0},
        "t_span": (0.0, 10.0),
        "invariant": "0.5 * v^2 + 0.5 * omega^2 * x^2",
    },
    "damped_oscillator": {
        "rhs": {"x": "v", "v": "-2 * zeta * omega * v - omega^2 * x"},
        "initial_state": {"x": 1.0, "v": 0.0},
        "parameters": {"omega": 2.0, "zeta": 0.15},
        "t_span": (0.0, 15.0),
    },
    "lorenz": {
        "rhs": {
            "x": "sigma * (y - x)",
            "y": "x * (rho - z) - y",
            "z": "x * y - beta * z",
        },
        "initial_state": {"x": 1.0, "y": 1.0, "z": 1.0},
        "parameters": {"sigma": 10.0, "rho": 28.0, "beta": 8.0 / 3.0},
        "t_span": (0.0, 20.0),
    },
    "lotka_volterra": {
        "rhs": {
            "x": "alpha * x - beta * x * y",
            "y": "delta * x * y - gamma_p * y",
        },
        "initial_state": {"x": 10.0, "y": 5.0},
        "parameters": {"alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma_p": 0.4},
        "t_span": (0.0, 30.0),
    },
    "van_der_pol": {
        "rhs": {"x": "v", "v": "mu * (1 - x^2) * v - x"},
        "initial_state": {"x": 2.0, "v": 0.0},
        "parameters": {"mu": 1.0},
        "t_span": (0.0, 20.0),
    },
    "sir": {
        "rhs": {
            "S": "-beta * S * I",
            "I": "beta * S * I - gamma_r * I",
            "R": "gamma_r * I",
        },
        "initial_state": {"S": 0.99, "I": 0.01, "R": 0.0},
        "parameters": {"beta": 0.5, "gamma_r": 0.1},
        "t_span": (0.0, 60.0),
        "invariant": "S + I + R",
    },
    "pendulum": {
        "rhs": {"theta": "omega", "omega": "-(g / L) * sin(theta)"},
        "initial_state": {"theta": 0.5, "omega": 0.0},
        "parameters": {"g": 9.80665, "L": 1.0},
        "t_span": (0.0, 10.0),
        "invariant": "0.5 * omega^2 - (g / L) * cos(theta)",
    },
    "rc_circuit": {
        "rhs": {"V": "(V_in - V) / (R * C)"},
        "initial_state": {"V": 0.0},
        "parameters": {"V_in": 5.0, "R": 1000.0, "C": 1e-3},
        "t_span": (0.0, 5.0),
    },
    "rlc_circuit": {
        "rhs": {"Q": "I_c", "I_c": "(V_in - R * I_c - Q / C) / L"},
        "initial_state": {"Q": 0.0, "I_c": 0.0},
        "parameters": {"V_in": 10.0, "R": 2.0, "L": 1.0, "C": 0.05},
        "t_span": (0.0, 10.0),
    },
}


def _canonical_id(tool: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"comp:{tool}:{digest}"


def _build_ode_exprs(
    rhs: dict[str, str],
    state_names: list[str],
    parameters: dict[str, float] | None = None,
) -> tuple[sp.Symbol, list[sp.Symbol], list[sp.Expr]]:
    t_sym = sp.Symbol("t")
    state_syms = [sp.Symbol(n) for n in state_names]
    local_env: dict[str, Any] = {"t": t_sym}
    for n, s in zip(state_names, state_syms, strict=False):
        local_env[n] = s
    param_subs: dict[sp.Symbol, float] = {}
    for pname, pval in (parameters or {}).items():
        psym = sp.Symbol(str(pname))
        local_env[str(pname)] = psym
        param_subs[psym] = float(pval)

    exprs: list[sp.Expr] = []
    for name in state_names:
        if name not in rhs:
            raise ValueError(f"Missing RHS equation for state variable {name!r}.")
        expr = safe_parse_expr(rhs[name], local_dict=local_env)
        if param_subs:
            expr = expr.subs(param_subs)
        unresolved = expr.free_symbols - ({t_sym} | set(state_syms))
        if unresolved:
            missing_names = sorted(str(s) for s in unresolved)
            raise ValueError(f"Unresolved parameter(s) in ODE RHS for {name!r}: {missing_names}")
        exprs.append(expr)
    return t_sym, state_syms, exprs


class FiniteTimeBlowUp(RuntimeError):
    """The adaptive solver stalled while the solution grew without bound: a finite-time singularity near t_last."""

    def __init__(self, t_last: float, growth: float, message: str) -> None:
        super().__init__(f"solution blows up near t = {t_last:.6g} (grew by a factor {growth:.3g}; {message})")
        self.t_last, self.growth = t_last, growth


def integrate_system(
    rhs: dict[str, str], initial_state: dict[str, float], t_span: tuple[float, float],
    parameters: dict[str, float] | None, method: str, times: np.ndarray, *, dense_output: bool = False,
    step_size: float | None = None, num_steps: int | None = None,
) -> tuple[Any, list[sp.Expr], list[sp.Symbol]]:
    """Shared safe integrator for trajectories and parameter estimation."""
    names = list(rhs)
    t_sym, syms, exprs = _build_ode_exprs(rhs, names, parameters)
    function = sp.lambdify((t_sym, syms), exprs, modules="numpy")
    if method.upper() == "RK4":
        from .fixed_step import rk4_integrate

        solution = rk4_integrate(
            lambda t, y: np.asarray(function(t, y), dtype=float).ravel(),
            [float(initial_state[n]) for n in names], t_span, step_size=step_size, num_steps=num_steps,
        )
        return solution, exprs, syms
    solution = integrate.solve_ivp(
        lambda t, y: np.asarray(function(t, y), dtype=float).ravel(), t_span,
        [float(initial_state[n]) for n in names], t_eval=times, method=method,
        rtol=1e-8, atol=1e-10, dense_output=dense_output,
    )
    if not solution.success or solution.y.shape[1] != len(times) or not np.isfinite(solution.y).all():
        # The step size collapsing while |y| has grown by many orders of magnitude is a singularity, not a solver
        # fault: y' = y^3 from y(0) = 1 stops at t = 1/2 whatever the tolerance.
        y0 = max(1.0, float(np.max(np.abs([float(initial_state[n]) for n in names]))))
        dense = solution.sol if dense_output else None
        t_last = float(dense.ts[-1]) if dense is not None and len(dense.ts) > 1 else None
        if solution.status == -1 and t_last is not None and t_last > t_span[0]:
            peak = float(np.max(np.abs(dense(t_last))))
            if not np.isfinite(peak) or peak > 1e6 * y0:
                raise FiniteTimeBlowUp(t_last, peak / y0, solution.message)
        raise RuntimeError(f"ODE integration failed ({solution.message})")
    return solution, exprs, syms


def dynamis_simulate_ode(
    rhs: dict[str, str] | None = None,
    initial_state: dict[str, float] | None = None,
    t_span: tuple[float, float] = (0.0, 10.0),
    parameters: dict[str, float] | None = None,
    method: str = "RK45",
    num_points: int = 200,
    model_name: str | None = None,
    step_size: float | None = None,
    num_steps: int | None = None,
    analytic_reference: bool = False,
    units: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Integrate a stated ODE system, using fixed-step RK4 or SciPy's adaptive solvers as requested."""
    invariant_expr_str: str | None = None
    if model_name:
        key = str(model_name).strip().lower()
        if key not in ODE_PRESETS:
            raise ValueError(f"Unknown ODE preset {model_name!r}. Available presets: {sorted(ODE_PRESETS)}")
        preset = ODE_PRESETS[key]
        rhs = dict(rhs) if rhs is not None else dict(preset["rhs"])
        base_init = dict(preset["initial_state"])
        if initial_state:
            base_init.update(initial_state)
        initial_state = base_init
        base_params = dict(preset.get("parameters") or {})
        if parameters:
            base_params.update(parameters)
        parameters = base_params
        # t_span is an execution contract. An explicit (0, 10) must not become a preset's (0, 15).
        invariant_expr_str = preset.get("invariant")

    if not rhs or not isinstance(rhs, dict):
        raise ValueError("rhs must be a non-empty dict of state variable -> derivative expression.")
    if not initial_state or not isinstance(initial_state, dict):
        raise ValueError("initial_state must be a non-empty dict of state variable -> initial float value.")

    state_names = list(rhs.keys())
    for name in state_names:
        if name not in initial_state:
            raise ValueError(f"initial_state is missing initial value for state variable {name!r}.")

    t0, tf = float(t_span[0]), float(t_span[1])
    if tf <= t0:
        raise ValueError(f"t_span end ({tf}) must be greater than start ({t0}).")

    n_pts = max(2, min(10000, int(num_points)))
    t_eval = np.linspace(t0, tf, n_pts)
    fixed = str(method).upper() == "RK4"
    if not fixed and (step_size is not None or num_steps is not None):
        raise ValueError("A fixed step/count requires method='RK4'; adaptive output samples are not solver steps.")
    blow_up: dict[str, Any] | None = None
    try:
        sol, exprs, state_syms = integrate_system(rhs, initial_state, (t0, tf), parameters, str(method), t_eval,
                                                 dense_output=not fixed, step_size=step_size, num_steps=num_steps)
    except FiniteTimeBlowUp as exc:
        # Report the singularity and the trajectory up to just before it, rather than a failed run.
        t_stop = t0 + (exc.t_last - t0) * 0.99
        blow_up = {"t_blow_up_estimate": exc.t_last, "requested_t_end": tf, "integrated_to": t_stop,
                   "growth_factor": exc.growth,
                   "note": f"The solution grows without bound as t approaches about {exc.t_last:.6g}; the trajectory "
                           f"is reported up to t = {t_stop:.6g}. This is numerical evidence of a singularity, not a "
                           "proof of one."}
        tf = t_stop
        t_eval = np.linspace(t0, tf, n_pts)
        sol, exprs, state_syms = integrate_system(rhs, initial_state, (t0, tf), parameters, str(method), t_eval,
                                                 dense_output=True)
    n_pts = len(sol.t)
    # The output samples are where the solution is reported, not where the solver stepped: extremes between samples
    # are found on the solver's dense (interpolating) output over a fine grid, and both are reported.
    n_dense = int(min(200_000, max(20 * n_pts, 20_001)))
    t_dense = np.linspace(t0, tf, n_dense)
    y_dense = sol.sol(t_dense) if sol.sol is not None else None
    internal_steps = n_pts - 1 if fixed else (int(len(sol.sol.ts) - 1) if sol.sol is not None and hasattr(sol.sol, "ts") else None)

    t_list = sol.t.tolist()
    trajectories: dict[str, list[float]] = {}
    summary: dict[str, dict[str, float]] = {}

    extrema: dict[str, dict[str, float | int]] = {}
    for idx, name in enumerate(state_names):
        series = sol.y[idx]
        trajectories[name] = series.tolist()
        summary[name] = {
            "initial": float(series[0]),
            "final": float(series[-1]),
            "min": float(np.min(series)),  # over the output samples (see "extrema" for the dense-output values)
            "max": float(np.max(series)),
            "mean": float(np.mean(series)),
        }
        entry: dict[str, float | int] = {
            "sampled_min": float(np.min(series)), "sampled_max": float(np.max(series)),
            "t_sampled_min": float(sol.t[int(np.argmin(series))]), "t_sampled_max": float(sol.t[int(np.argmax(series))]),
            "samples": int(len(series)),
        }
        if y_dense is not None:
            dense = y_dense[idx]
            entry.update({
                "dense_min": float(np.min(dense)), "dense_max": float(np.max(dense)),
                "t_dense_min": float(t_dense[int(np.argmin(dense))]), "t_dense_max": float(t_dense[int(np.argmax(dense))]),
                "dense_grid_points": n_dense,
            })
        extrema[name] = entry

    # Check conservation law (either explicit preset invariant or sum of derivatives == 0)
    conserved_check: dict[str, Any] = {"checked": False, "conserved": True, "drift": 0.0}
    try:
        if invariant_expr_str is None and len(exprs) > 1 and sp.simplify(sum(exprs)) == 0:
            invariant_expr_str = " + ".join(state_names)
        if invariant_expr_str is not None:
            local_env: dict[str, Any] = dict(zip(state_names, state_syms, strict=False))
            for pname, pval in (parameters or {}).items():
                local_env[str(pname)] = float(pval)
            inv_expr = safe_parse_expr(invariant_expr_str, local_dict=local_env)
            inv_fn = sp.lambdify(state_syms, inv_expr, modules="numpy")
            init_inv = float(inv_fn(*sol.y[:, 0]))
            final_inv = float(inv_fn(*sol.y[:, -1]))
            drift = abs(final_inv - init_inv)
            conserved_check = {
                "checked": True,
                "invariant": invariant_expr_str,
                "initial_value": init_inv,
                "final_value": final_inv,
                "drift": drift,
                "conserved": bool(drift <= 1e-4 * max(1.0, abs(init_inv))),
            }
    except Exception:
        pass

    cid = _canonical_id(
        "dynamis_simulate_ode",
        {"rhs": rhs, "initial_state": initial_state, "t_span": [t0, tf], "parameters": parameters or {},
         "method": method, "step_size": step_size, "num_steps": num_steps, "num_points": n_pts},
    )
    result = {
        "units": dict(units or {}),
        "model_name": model_name,
        "spec": {"rhs": dict(rhs), "parameters": dict(parameters or {}), "initial_state": dict(initial_state),
                 "t_span": [t0, tf], "method": str(method), "model_name": model_name,
                 **({"step_size": (tf - t0) / (n_pts - 1), "num_steps": n_pts - 1} if fixed else {})},
        "state_variables": state_names,
        "t_span": [t0, tf],
        "method": method,
        "rtol": None if fixed else 1e-8,
        "atol": None if fixed else 1e-10,
        "t": t_list,
        "trajectories": trajectories,
        "summary": summary,
        "extrema": extrema,
        "solver": {
            "method": str(method), "rtol": None if fixed else 1e-8, "atol": None if fixed else 1e-10, "t_span": [t0, tf],
            "output_samples": n_pts, "output_spacing": (tf - t0) / (n_pts - 1),
            "internal_steps": internal_steps, "function_evaluations": int(sol.nfev),
            "step_control": "fixed; output times are the actual RK4 steps" if fixed else "adaptive (error-controlled); output times are interpolated, not solver steps",
            "extrema_note": "sampled_* are over the actual RK4 steps; no dense interpolant" if fixed else "sampled_* are over the output samples; dense_* over the solver's dense output on a fine grid",
        },
        "conserved_check": conserved_check,
        "verified": bool(sol.success and conserved_check.get("conserved", True)),
        "canonical_id": cid,
    }
    if blow_up is not None:
        result["blow_up"] = blow_up
    if analytic_reference:
        from .fixed_step import linear_endpoint_reference

        reference = linear_endpoint_reference(exprs, state_syms, [float(initial_state[n]) for n in state_names], (t0, tf))
        if reference is not None:
            reference["absolute_errors"] = {
                n: abs(summary[n]["final"] - reference["endpoint"][n]) for n in state_names
            }
        result["analytical_reference"] = reference
    return result


def _classify_stability(eigenvalues: np.ndarray, tol: float = 1e-7) -> str:
    reals = np.real(eigenvalues)
    imags = np.imag(eigenvalues)
    has_pos = bool(np.any(reals > tol))
    has_neg = bool(np.any(reals < -tol))
    has_zero = bool(np.any(np.abs(reals) <= tol))
    has_imag = bool(np.any(np.abs(imags) > tol))

    if has_pos and has_neg:
        return "saddle"
    if has_neg and not has_pos and not has_zero:
        return "stable_spiral" if has_imag else "stable_node"
    if has_pos and not has_neg and not has_zero:
        return "unstable_spiral" if has_imag else "unstable_node"
    if has_zero and not has_pos and not has_neg and has_imag:
        return "center"
    return "marginally_stable"


def dynamis_equilibrium(
    rhs: dict[str, str],
    guess: dict[str, float],
    parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Find a fixed point f(x*) = 0, compute the Jacobian J(x*) and its eigenvalues, and classify stability."""
    if not rhs:
        raise ValueError("rhs must be a non-empty dict.")
    state_names = list(rhs.keys())
    for name in state_names:
        if name not in guess:
            raise ValueError(f"guess is missing starting value for state variable {name!r}.")

    _, state_syms, exprs = _build_ode_exprs(rhs, state_names, parameters)
    sym_jac = sp.Matrix(exprs).jacobian(state_syms)

    f_vec = sp.lambdify(state_syms, exprs, modules="numpy")
    j_mat = sp.lambdify(state_syms, sym_jac, modules="numpy")

    def _func(x_arr: np.ndarray) -> np.ndarray:
        return np.asarray(f_vec(*x_arr), dtype=float).ravel()

    def _jac(x_arr: np.ndarray) -> np.ndarray:
        return np.asarray(j_mat(*x_arr), dtype=float)

    x0 = np.array([float(guess[n]) for n in state_names], dtype=float)
    root_res = optimize.root(_func, x0, jac=_jac, method="hybr", tol=1e-11)
    x_star = root_res.x
    residual_vec = _func(x_star)
    res_norm = float(np.linalg.norm(residual_vec))
    converged = bool(root_res.success or res_norm < 1e-8)

    J_num = _jac(x_star)
    eigvals = np.linalg.eigvals(J_num)
    stability = _classify_stability(eigvals)

    eig_out = [
        {"real": float(np.real(ev)), "imag": float(np.imag(ev)), "str": f"{np.real(ev):.6g}{np.imag(ev):+.6g}j" if abs(np.imag(ev)) > 1e-12 else f"{np.real(ev):.6g}"}
        for ev in eigvals
    ]
    fixed_point = {name: float(val) for name, val in zip(state_names, x_star, strict=False)}
    cid = _canonical_id(
        "dynamis_equilibrium",
        {"rhs": rhs, "guess": guess, "parameters": parameters or {}, "fixed_point": fixed_point},
    )
    return {
        "fixed_point": fixed_point,
        "jacobian": [[float(J_num[i, j]) for j in range(len(state_names))] for i in range(len(state_names))],
        "jacobian_symbolic": [[str(sym_jac[i, j]) for j in range(len(state_names))] for i in range(len(state_names))],
        "eigenvalues": eig_out,
        "stability": stability,
        "residual_norm": res_norm,
        "converged": converged,
        "verified": bool(converged and res_norm < 1e-6),
        "canonical_id": cid,
    }


def dynamis_parameter_scan(
    rhs: dict[str, str],
    initial_state: dict[str, float],
    parameter: str,
    scan_range: tuple[float, float],
    num_points: int = 10,
    t_span: tuple[float, float] = (0.0, 10.0),
    base_parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Scan a parameter across scan_range and record final, peak, min, and mean states for each value."""
    p_min, p_max = float(scan_range[0]), float(scan_range[1])
    n_pts = max(2, min(200, int(num_points)))
    param_values = np.linspace(p_min, p_max, n_pts)
    base_params = dict(base_parameters or {})

    scan_results: list[dict[str, Any]] = []
    for pval in param_values:
        params = dict(base_params)
        params[parameter] = float(pval)
        sim = dynamis_simulate_ode(
            rhs=rhs,
            initial_state=initial_state,
            t_span=t_span,
            parameters=params,
            num_points=100,
        )
        scan_results.append({
            "parameter_value": float(pval),
            "final_state": {k: v["final"] for k, v in sim["summary"].items()},
            "peak_state": {k: v["max"] for k, v in sim["summary"].items()},
            "min_state": {k: v["min"] for k, v in sim["summary"].items()},
            "mean_state": {k: v["mean"] for k, v in sim["summary"].items()},
        })

    cid = _canonical_id(
        "dynamis_parameter_scan",
        {"rhs": rhs, "parameter": parameter, "scan_range": [p_min, p_max], "num_points": n_pts},
    )
    return {
        "parameter": parameter,
        "spec": {"rhs": dict(rhs), "parameters": base_params, "initial_state": dict(initial_state),
                 "t_span": list(t_span), "method": "RK45", "model_name": None},
        "scan_range": [p_min, p_max],
        "num_points": n_pts,
        "parameter_values": [float(v) for v in param_values],
        "scan_results": scan_results,
        "verified": len(scan_results) == n_pts,
        "canonical_id": cid,
    }


_RELATION_RE = re.compile(r"(<=|>=|==|=|<|>)")


def _constraint_function(text: str, ctype: str, local_env: dict[str, Any]) -> tuple[str, sp.Expr]:
    """(SLSQP type, fun) for one constraint. A relation decides the type: "lhs >= rhs" is ineq with fun = lhs - rhs
    (SLSQP requires fun >= 0), "lhs <= rhs" is ineq with fun = rhs - lhs (strict < and > are read as their closures,
    which is all a continuous optimiser can enforce), and "lhs = rhs" / "lhs == rhs" is eq with fun = lhs - rhs. A
    bare expression keeps the declared type ("eq": fun = 0, "ineq": fun >= 0)."""
    cleaned = check_math_text(text)
    if cleaned.startswith("Eq("):
        _lhs, _rhs, eq = safe_parse_equation(cleaned, local_dict=local_env)
        return "eq", eq.lhs - eq.rhs
    if "!=" in cleaned:
        raise ValueError(f"Constraint {text!r}: '!=' cannot be enforced by a continuous optimiser.")
    parts = _RELATION_RE.split(cleaned)
    if len(parts) == 1:
        if ctype not in ("eq", "ineq"):
            raise ValueError(f"Constraint type must be 'eq' or 'ineq', got {ctype!r}.")
        return ctype, safe_parse_expr(cleaned, local_dict=local_env)
    if len(parts) != 3:
        raise ValueError(f"Constraint {text!r} must have exactly one relation (=, ==, <=, >=, <, >).")
    lhs = safe_parse_expr(parts[0], local_dict=local_env)
    rhs = safe_parse_expr(parts[2], local_dict=local_env)
    op = parts[1]
    if op in (">=", ">"):
        return "ineq", lhs - rhs
    if op in ("<=", "<"):
        return "ineq", rhs - lhs
    return "eq", lhs - rhs


def dynamis_optimize(
    objective: str,
    variables: list[str],
    bounds: dict[str, tuple[float | None, float | None]] | None = None,
    initial_guess: dict[str, float] | None = None,
    constraints: list[dict[str, Any]] | None = None,
    minimize: bool = True,
) -> dict[str, Any]:
    """Perform constrained or unconstrained numerical optimization using scipy.optimize.minimize."""
    if not variables:
        raise ValueError("variables list must not be empty.")
    var_syms = [sp.Symbol(str(v).strip()) for v in variables]
    local_env = {s.name: s for s in var_syms}
    obj_expr = safe_parse_expr(objective, local_dict=local_env)
    unresolved = obj_expr.free_symbols - set(var_syms)
    if unresolved:
        raise ValueError(f"Objective contains undeclared variable(s): {sorted(str(s) for s in unresolved)}")

    sign = 1.0 if minimize else -1.0
    grad_exprs = [sp.diff(obj_expr, s) for s in var_syms]
    f_obj = sp.lambdify(var_syms, obj_expr, modules="numpy")
    f_grad = sp.lambdify(var_syms, grad_exprs, modules="numpy")

    def _fun(x_arr: np.ndarray) -> float:
        return sign * float(f_obj(*x_arr))

    def _jac(x_arr: np.ndarray) -> np.ndarray:
        return sign * np.asarray(f_grad(*x_arr), dtype=float).ravel()

    x0_list: list[float] = []
    scipy_bounds: list[tuple[float | None, float | None]] | None = None
    if bounds:
        scipy_bounds = []
    for s in var_syms:
        val = float((initial_guess or {}).get(s.name, 0.0))
        if bounds and s.name in bounds:
            lo, hi = bounds[s.name]
            lo_f = float(lo) if lo is not None else None
            hi_f = float(hi) if hi is not None else None
            if lo_f is not None and val < lo_f:
                val = lo_f
            if hi_f is not None and val > hi_f:
                val = hi_f
            scipy_bounds.append((lo_f, hi_f))  # type: ignore[union-attr]
        elif scipy_bounds is not None:
            scipy_bounds.append((None, None))
        x0_list.append(val)

    x0 = np.array(x0_list, dtype=float)

    scipy_constraints = []
    for c in constraints or []:
        cexpr_str = str(c.get("expr") or c.get("fun") or "").strip()
        if not cexpr_str:
            continue
        ctype, cexpr = _constraint_function(cexpr_str, str(c.get("type", "eq")).strip().lower(), local_env)
        c_fn = sp.lambdify(var_syms, cexpr, modules="numpy")
        scipy_constraints.append({
            "type": ctype,
            "fun": lambda x_arr, _fn=c_fn: float(_fn(*x_arr)),
        })

    if scipy_constraints:
        method = "SLSQP"
        opts: dict[str, Any] = {"ftol": 1e-12, "maxiter": 500}
    elif scipy_bounds:
        method = "L-BFGS-B"
        opts = {"ftol": 1e-12, "gtol": 1e-8, "maxiter": 500}
    else:
        method = "BFGS"
        opts = {"gtol": 1e-8, "maxiter": 500}

    res = optimize.minimize(
        _fun,
        x0,
        jac=_jac,
        method=method,
        bounds=scipy_bounds,
        constraints=scipy_constraints if scipy_constraints else (),
        options=opts,
    )

    x_opt = res.x
    opt_val = float(f_obj(*x_opt))
    grad_at_opt = np.asarray(f_grad(*x_opt), dtype=float).ravel()
    grad_norm = float(np.linalg.norm(grad_at_opt))
    opt_point = {s.name: float(v) for s, v in zip(var_syms, x_opt, strict=False)}

    cid = _canonical_id(
        "dynamis_optimize",
        {"objective": objective, "variables": variables, "minimize": minimize, "optimal_point": opt_point},
    )
    return {
        "objective": objective,
        "minimize": minimize,
        "optimal_point": opt_point,
        "optimal_value": opt_val,
        "gradient_norm": grad_norm,
        "converged": bool(res.success),
        "iterations": int(getattr(res, "nit", 0)),
        "message": str(res.message),
        "verified": bool(res.success),
        "canonical_id": cid,
    }


def dynamis_fit_parameters(
    model_expr: str | None = None,
    independent_var: str = "t",
    param_names: list[str] | None = None,
    x_data: list[float] | None = None,
    y_data: list[float] | None = None,
    initial_guess: dict[str, float] | None = None,
    *, rhs: dict[str, str] | None = None, initial_state: dict[str, float] | None = None,
    parameters: dict[str, float] | None = None, model_name: str | None = None,
    data: dict[str, Any] | None = None, data_path: str | None = None,
    time_column: str | None = None, column_mapping: dict[str, str] | None = None,
    bounds: dict[str, tuple[float, float]] | None = None, n_starts: int = 1, loss: str = "linear",
    fit_initial_state: bool | list[str] = False, seed: int = 0, max_nfev: int = 200, method: str = "RK45",
    y_sigma: list[float] | None = None,
) -> dict[str, Any]:
    """Fit a safe expression or ODE system to measurements, with covariance and identifiability diagnostics.

    For an expression model, `y_sigma` (one standard uncertainty per y value) weights the fit and makes the
    parameter standard errors absolute; without it they are scaled by the residual variance. A standard error is None
    when it is not estimable (no degrees of freedom, or a singular covariance from unidentifiable parameters), never 0.
    """
    if rhs or model_name:
        from .fitting import fit_ode

        return fit_ode(rhs=rhs, initial_state=initial_state, parameters=parameters, model_name=model_name,
                       param_names=param_names, initial_guess=initial_guess, data=data, data_path=data_path,
                       time_column=time_column, column_mapping=column_mapping, bounds=bounds, n_starts=n_starts,
                       loss=loss, fit_initial_state=fit_initial_state, seed=seed, max_nfev=max_nfev, method=method)
    if not model_expr or not param_names or x_data is None or y_data is None:
        raise ValueError("Supply model_expr and x_data/y_data, or an ODE system and measurements.")
    if len(x_data) != len(y_data):
        raise ValueError(f"x_data length ({len(x_data)}) and y_data length ({len(y_data)}) must match.")
    if len(x_data) < len(param_names):
        raise ValueError(f"Need at least {len(param_names)} data points to fit {len(param_names)} parameters.")

    x_sym = sp.Symbol(str(independent_var).strip())
    p_syms = [sp.Symbol(str(p).strip()) for p in param_names]
    local_env = {x_sym.name: x_sym, **{s.name: s for s in p_syms}}
    expr = safe_parse_expr(model_expr, local_dict=local_env)

    f_model = sp.lambdify((x_sym, *p_syms), expr, modules="numpy")
    x_arr = np.asarray(x_data, dtype=float)
    y_arr = np.asarray(y_data, dtype=float)
    p0 = np.array([float((initial_guess or {}).get(p.name, 1.0)) for p in p_syms], dtype=float)

    def _curve_fn(x_in: np.ndarray, *params: float) -> np.ndarray:
        return np.asarray(f_model(x_in, *params), dtype=float)

    sigma_arr = None
    if y_sigma is not None:
        sigma_arr = np.asarray(y_sigma, dtype=float)
        if sigma_arr.shape != y_arr.shape or not np.all(np.isfinite(sigma_arr)) or np.any(sigma_arr <= 0):
            raise ValueError("y_sigma must give one positive, finite uncertainty per y value.")
    popt, pcov, _info, mesg, ier = optimize.curve_fit(
        _curve_fn, x_arr, y_arr, p0=p0, maxfev=10000, sigma=sigma_arr, absolute_sigma=sigma_arr is not None,
        full_output=True,
    )
    converged = ier in (1, 2, 3, 4)
    y_pred = _curve_fn(x_arr, *popt)
    residuals = y_arr - y_pred
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-15 else (1.0 if ss_res < 1e-15 else 0.0)
    dof = len(x_arr) - len(p_syms)

    std_errs: dict[str, float | None] = {}
    for idx, p in enumerate(p_syms):
        var = pcov[idx, idx] if pcov is not None else np.inf
        std_errs[p.name] = float(np.sqrt(var)) if dof > 0 and np.isfinite(var) and var >= 0 else None

    fitted_params = {p.name: float(val) for p, val in zip(p_syms, popt, strict=False)}
    # Parameters whose estimates are almost perfectly correlated cannot be separated by the data (e.g. a*b*x).
    max_corr = None
    if len(p_syms) > 1 and all(v is not None and v > 0 for v in std_errs.values()):
        sd = np.sqrt(np.diag(pcov))
        corr = pcov / np.outer(sd, sd)
        max_corr = float(np.max(np.abs(corr[~np.eye(len(p_syms), dtype=bool)])))
    estimable = all(v is not None for v in std_errs.values()) and (max_corr is None or max_corr < 0.999)
    # Verified means: the optimiser converged, the uncertainties are estimable, and the model explains the data
    # better than its mean (R^2 > 0). It does not certify that the model form is right.
    verified = bool(converged and estimable and math.isfinite(rmse) and r_squared > 0.0)
    issues = []
    if not converged:
        issues.append(f"the optimiser did not converge: {mesg}")
    if dof <= 0:
        issues.append("no degrees of freedom (as many parameters as points): standard errors are not estimable")
    elif not estimable:
        issues.append("at least one parameter is not identifiable from these data (singular covariance or parameter "
                      f"correlation {max_corr:.4f})" if max_corr is not None else
                      "singular covariance: at least one parameter is not identifiable from these data")
    if r_squared <= 0.0:
        issues.append(f"R^2 = {r_squared:.3g}: the model does not explain the data better than its mean")
    cid = _canonical_id(
        "dynamis_fit_parameters",
        {"model_expr": model_expr, "param_names": param_names, "parameters": fitted_params},
    )
    return {
        "model_expr": model_expr,
        "independent_var": independent_var,
        "parameters": fitted_params,
        "std_errors": std_errs,
        "std_error_basis": "absolute (from y_sigma)" if sigma_arr is not None else "scaled by residual variance",
        "degrees_of_freedom": dof,
        "max_parameter_correlation": max_corr,
        "rmse": rmse,
        "r_squared": r_squared,
        "residuals": [float(r) for r in residuals],
        "predictions": [float(y) for y in y_pred],
        "converged": converged,
        "verified": verified,
        "issues": issues,
        "canonical_id": cid,
    }


def dynamis_root_find(
    equations: str | list[str],
    initial_guess: dict[str, float],
    parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Find numerical roots of a single nonlinear equation or system of equations via scipy.optimize.root."""
    eq_list = [equations] if isinstance(equations, str) else list(equations)
    if not eq_list:
        raise ValueError("equations must not be empty.")
    if not initial_guess:
        raise ValueError("initial_guess must not be empty.")

    var_names = list(initial_guess.keys())
    var_syms = [sp.Symbol(n) for n in var_names]
    local_env: dict[str, Any] = dict(zip(var_names, var_syms, strict=False))
    param_subs: dict[sp.Symbol, float] = {}
    for pname, pval in (parameters or {}).items():
        psym = sp.Symbol(str(pname))
        local_env[str(pname)] = psym
        param_subs[psym] = float(pval)

    res_exprs: list[sp.Expr] = []
    for eq_str in eq_list:
        lhs, rhs, _ = safe_parse_equation(eq_str, local_dict=local_env)
        if isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list)):
            if not (isinstance(lhs, (sp.Tuple, tuple, list)) and isinstance(rhs, (sp.Tuple, tuple, list))):
                raise ValueError("Shape mismatch in equation: cannot equate container to scalar")
            if len(lhs) != len(rhs):
                raise ValueError(f"Shape length mismatch in equation: {len(lhs)} != {len(rhs)}")
            for l_item, r_item in zip(lhs, rhs, strict=True):
                try:
                    expr = l_item - r_item
                except TypeError as exc:
                    raise ValueError(f"Cannot equate incompatible types in equation: {exc}") from exc
                if param_subs:
                    expr = expr.subs(param_subs)
                res_exprs.append(expr)
            continue
        try:
            expr = lhs - rhs
        except TypeError as exc:
            raise ValueError(f"Cannot equate incompatible types in equation: {exc}") from exc
        if param_subs:
            expr = expr.subs(param_subs)
        res_exprs.append(expr)

    sym_jac = sp.Matrix(res_exprs).jacobian(var_syms)
    f_vec = sp.lambdify(var_syms, res_exprs, modules="numpy")
    j_mat = sp.lambdify(var_syms, sym_jac, modules="numpy")

    def _func(x_arr: np.ndarray) -> np.ndarray:
        return np.asarray(f_vec(*x_arr), dtype=float).ravel()

    def _jac(x_arr: np.ndarray) -> np.ndarray:
        return np.asarray(j_mat(*x_arr), dtype=float)

    x0 = np.array([float(initial_guess[n]) for n in var_names], dtype=float)
    method = "hybr" if len(res_exprs) == len(var_names) else "lm"
    sol = optimize.root(_func, x0, jac=_jac, method=method, tol=1e-11)
    residuals = _func(sol.x)
    res_norm = float(np.linalg.norm(residuals))
    converged = bool(sol.success or res_norm < 1e-8)
    roots = {name: float(val) for name, val in zip(var_names, sol.x, strict=False)}

    cid = _canonical_id(
        "dynamis_root_find",
        {"equations": eq_list, "initial_guess": initial_guess, "roots": roots},
    )
    return {
        "equations": eq_list,
        "roots": roots,
        "residuals": [float(r) for r in residuals],
        "residual_norm": res_norm,
        "converged": converged,
        "verified": bool(converged and res_norm < 1e-6),
        "canonical_id": cid,
    }


class DynamisEngine:
    """Object-oriented facade over Dynamis numerical simulation and optimization tools."""

    simulate_ode = staticmethod(dynamis_simulate_ode)
    equilibrium = staticmethod(dynamis_equilibrium)
    parameter_scan = staticmethod(dynamis_parameter_scan)
    optimize = staticmethod(dynamis_optimize)
    fit_parameters = staticmethod(dynamis_fit_parameters)
    root_find = staticmethod(dynamis_root_find)


DynamisSimulationEngine = DynamisEngine

__all__ = [
    "DynamisEngine",
    "DynamisSimulationEngine",
    "ODE_PRESETS",
    "dynamis_equilibrium",
    "dynamis_fit_parameters",
    "dynamis_optimize",
    "dynamis_parameter_scan",
    "dynamis_root_find",
    "dynamis_simulate_ode",
]
