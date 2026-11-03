"""Render computed fields directly. A model is not needed to copy a numerical result into its requested form."""

from __future__ import annotations

from typing import Any

from .requests import ScientificRequest


def num(value: float) -> str:
    return f"{value:.12g}"


def render(request: ScientificRequest, data: dict[str, Any]) -> tuple[str, list[str]]:
    kind = request.kind
    if kind in ("rc_charge", "beam"):
        values = {r["name"]: float(r["value"]) for r in data["results"]}
        p = request.args["inputs"]
        if kind == "rc_charge":
            tau, vc, current = (
                values["time_constant"],
                values["capacitor_voltage"],
                values["current"],
            )
            t, voltage, resistance = p["time"], p["source_voltage"], p["resistance"]
            lines = [
                f"Time constant: τ = RC = ({num(resistance)} Ω)({num(p['capacitance'])} F) = {num(tau)} s.",
                f"Capacitor voltage: V_C(t) = V_s + (V_0 − V_s) exp(−t/τ); V_C({num(t)} s) = {num(vc)} V.",
                f"Current: I(t) = (V_s − V_0) exp(−t/τ)/R; I(0+) = {num(values['initial_current'])} A; "
                f"I({num(t)} s) = {num(current)} A.",
                f"KVL at {num(t)} s: V_R = RI = {num(values['resistor_voltage'])} V; V_R + V_C = "
                f"{num(values['resistor_voltage'] + vc)} V = V_s = {num(voltage)} V. Residual = {num(values['kvl_residual'])} V.",
            ]
        else:
            b, h, length, young, load = (
                p[k] for k in ("width", "height", "length", "elastic_modulus", "point_load")
            )
            lines = [
                f"b = {num(b)} m and h = {num(h)} m. I = bh³/12 = {num(values['second_moment_of_area'])} m⁴.",
                f"Maximum bending moment at the fixed end: |M_max| = PL = ({num(load)} N)({num(length)} m) "
                f"= {num(values['max_bending_moment'])} N·m.",
                f"c = h/2 = {num(h / 2)} m; |σ_max| = |M_max|c/I = {num(values['max_bending_stress'])} Pa "
                f"= {num(values['max_bending_stress'] / 1e6)} MPa.",
                f"E = {num(young)} Pa. |δ_tip| = PL³/(3EI) = {num(values['max_deflection'])} m "
                f"= {num(values['max_deflection'] * 1000)} mm; |δ_tip|/L = {num(values['deflection_ratio'])} "
                f"({num(100 * values['deflection_ratio'])}%).",
            ]
    elif kind == "heat_ftcs":
        s, grid = data["stability"], data["grid"]
        unit, steps = request.context["temperature_unit"], request.context["steps"]
        field = ", ".join(num(x) for x in data["field"])
        left, right = request.args["boundary_values"]["x0"], request.args["boundary_values"]["x1"]
        lines = [
            f"Float64 FTCS (forward Euler in time, centred second difference in space): "
            f"r = αΔt/(Δx)² = {num(s['number'])}; r ≤ 1/2, so this grid and step satisfy the diffusion stability limit. "
            f"Δx = {num(grid['spacing'][0])} m; Δt = {num(s['dt'])} s; exactly {s['steps']} steps.",
            f"At t = {num(data['t_span'][1])} s, the {grid['points']} node temperatures from left to right are "
            f"[{field}] {unit}.",
            f"Boundary check over all {steps + 1} stored time levels: left = {num(left)} {unit}, right = {num(right)} {unit}. "
            "Both values were reimposed after every FTCS step. These are values of the requested discrete scheme; "
            "stability alone does not establish continuum accuracy.",
        ]
    elif kind == "monte_carlo":
        lines = [
            f"Crude Monte Carlo estimate: {num(data['estimate'])}. Executed {data['num_samples']:,} independent uniform "
            f"samples on [{num(data['lower'])}, {num(data['upper'])}) using NumPy Generator(PCG64), seed {data['seed']}.",
            f"Sample-based standard error: s/√N = {num(data['standard_error'])}, using sample standard deviation "
            f"s = {num(data['sample_std'])} with ddof = 1.",
            (
                f"Absolute discrepancy from the supplied reference {num(data['reference'])}: "
                f"{num(abs(data['estimate'] - data['reference']))}; discrepancy/SE = "
                f"{num(data['standard_errors_from_reference']) if data['standard_errors_from_reference'] is not None else 'undefined (zero estimated standard error)'}. "
                if data["reference"] is not None
                else "No reference value was supplied for a discrepancy check. "
            )
            + "The standard error describes sampling uncertainty, not a guarantee of exactness.",
        ]
    elif kind == "ode_rk4":
        solver, spec = data["solver"], data["spec"]
        reference = data.get("analytical_reference")
        units = data.get("units") or {}
        endpoints = "; ".join(
            f"{name}({num(data['t_span'][1])} s) = {num(row['final'])} {units.get(name, '')}".rstrip()
            for name, row in data["summary"].items()
        )
        comparison = (
            (
                " Analytical reference: "
                + "; ".join(
                    f"{name} = {num(value)} {units.get(name, '')}, absolute error = {num(reference['absolute_errors'][name])} {units.get(name, '')}"
                    for name, value in reference["endpoint"].items()
                )
            )
            if reference
            else ""
        )
        lines = [
            f"Executed classical fixed-step RK4 in float64 from {num(data['t_span'][0])} to {num(data['t_span'][1])} s, "
            f"h = {num(spec['step_size'])} s, exactly {solver['internal_steps']} steps and {solver['function_evaluations']} "
            f"RHS evaluations. Initial state: {spec['initial_state']}; RHS: {spec['rhs']}.",
            "Computed endpoint: " + endpoints + "." + comparison + "." * bool(comparison),
            (
                "For Y = ["
                + ", ".join(data["state_variables"])
                + "], the analytical affine-system solution is "
                "[Y(t), 1]ᵀ = exp(B(t−t₀))[Y(t₀), 1]ᵀ with B = "
                + str(reference["augmented_matrix"])
                + ". "
                "The reference was evaluated separately with scipy.linalg.expm. "
                if reference
                else "No autonomous affine linear analytical reference was available; no analytical error is claimed. "
            )
            + "The complete executed trajectory and exact input specification are attached to this result.",
        ]
    else:
        raise ValueError(f"No renderer for scientific request {kind}.")
    return "\n\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)), lines
