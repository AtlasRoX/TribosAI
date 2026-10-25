"""Thermo-fluid calculators: pipe pressure drop, heat exchangers and conduction through a layered wall."""

from __future__ import annotations

import math
from typing import Any

from .core import Calculator, Check, Outcome, Param, Reference, Result, to_si
from .materials import find_material

G = 9.80665  # standard gravity, m/s^2


# -- Pipe pressure drop ------------------------------------------------------------------------------------------


def colebrook(re: float, rel_roughness: float) -> float:
    """The Darcy friction factor from the Colebrook equation, by Newton iteration on x = 1/sqrt(f)."""
    sj = swamee_jain(re, rel_roughness)
    x = 1.0 / math.sqrt(sj)
    for _ in range(50):
        g = x + 2.0 * math.log10(rel_roughness / 3.7 + 2.51 * x / re)
        dg = 1.0 + 2.0 / math.log(10.0) * (2.51 / re) / (rel_roughness / 3.7 + 2.51 * x / re)
        step = g / dg
        x -= step
        if abs(step) < 1e-12 * abs(x):
            break
    return 1.0 / x**2


def swamee_jain(re: float, rel_roughness: float) -> float:
    return 0.25 / math.log10(rel_roughness / 3.7 + 5.74 / re**0.9) ** 2


def pipe(v: dict[str, Any]) -> Outcome:
    D, L, rho, mu, eps = v["diameter"], v["length"], v["density"], v["viscosity"], v["roughness"]
    area = math.pi * D**2 / 4.0
    if v.get("flow_rate") is not None:
        Q = v["flow_rate"]
        V = Q / area
    elif v.get("velocity") is not None:
        V = v["velocity"]
        Q = V * area
    else:
        raise ValueError("Give the flow_rate or the mean velocity.")
    re = rho * V * D / mu
    rr = eps / D
    out = Outcome(results=[])
    if re < 2300.0:
        f = 64.0 / re
        regime = "laminar"
        out.formulas.append("Laminar: f = 64 / Re")
    else:
        f = colebrook(re, rr)
        regime = "turbulent" if re > 4000.0 else "transitional"
        out.formulas.append("Colebrook: 1/sqrt(f) = -2 log10(eps / (3.7 D) + 2.51 / (Re sqrt(f)))")
        out.results.append(Result("friction_factor_swamee_jain", "Friction factor (Swamee-Jain, explicit)",
                                  swamee_jain(re, rr), "1"))
        out.validity.append(Check("Swamee-Jain range", 5e3 <= re <= 1e8 and 1e-6 <= rr <= 1e-2,
                                  f"Re = {re:.3g}, eps/D = {rr:.3g}; Swamee-Jain is fitted for 5e3-1e8 and 1e-6-1e-2"))
        if regime == "transitional":
            out.warnings.append(f"Re = {re:.0f} is transitional (2300-4000): the friction factor lies between the laminar "
                                f"value {64 / re:.4g} and the turbulent (Colebrook) value {f:.4g}; the turbulent one is used.")
    dyn = rho * V**2 / 2.0
    dp_friction = f * L / D * dyn
    dp_minor = v["minor_loss_coefficient"] * dyn
    dp_static = rho * G * (v["elevation_change"] or 0.0)
    dp = dp_friction + dp_minor + dp_static
    out.formulas += ["Re = rho V D / mu", "dp = f (L/D) rho V^2/2 + K rho V^2/2 + rho g dz", "power = Q dp"]
    out.results = [
        Result("reynolds_number", f"Reynolds number ({regime})", re, "1"),
        Result("friction_factor", "Darcy friction factor", f, "1"),
        Result("velocity", "Mean velocity", V, "m/s"),
        Result("flow_rate", "Flow rate", Q, "m^3/s", "L/s"),
        Result("pressure_drop_friction", "Friction pressure drop", dp_friction, "Pa", "kPa"),
        Result("pressure_drop", "Total pressure drop", dp, "Pa", "kPa"),
        Result("head_loss", "Friction head loss", dp_friction / (rho * G), "m"),
        Result("pumping_power", "Hydraulic power Q dp", Q * dp, "W"),
        *out.results,
    ]
    if v.get("allowable_pressure_drop") is not None:
        allow = v["allowable_pressure_drop"]
        out.checks.append(Check("pressure drop", dp <= allow, f"{dp / 1e3:.4g} kPa against {allow / 1e3:.4g} kPa",
                                utilisation=dp / allow))
    out.validity.append(Check("developed flow", L / D >= 10.0,
                              f"L/D = {L / D:.3g}; the friction factor is for fully developed flow (entrance effects "
                              "matter in short pipes)"))
    return out


PIPE = Calculator(
    id="pipe_pressure_drop",
    title="Pipe pressure drop (Darcy-Weisbach, Colebrook)",
    summary="Pressure drop of incompressible flow in a round pipe, with the Colebrook (and Swamee-Jain) friction factor.",
    reference=Reference("Colebrook, J. Inst. Civil Eng. 11 (1939) 133; Swamee & Jain, J. Hydraul. Div. ASCE 102 (1976) "
                        "657", "Darcy-Weisbach and the Moody chart as in White, Fluid Mechanics, Chapter 6"),
    params=(
        Param("diameter", "m", "Inside diameter D."),
        Param("length", "m", "Pipe length L."),
        Param("flow_rate", "m^3/s", "Volumetric flow rate Q.", optional=True),
        Param("velocity", "m/s", "Mean velocity V (instead of Q).", optional=True),
        Param("density", "kg/m^3", "Fluid density (water at 20 C by default).", default=998.2),
        Param("viscosity", "Pa*s", "Dynamic viscosity (water at 20 C by default).", default=1.002e-3),
        Param("roughness", "m", "Absolute roughness eps (commercial steel 0.045 mm by default).", default=4.5e-5,
              positive=False),
        Param("minor_loss_coefficient", "1", "Sum of the fitting loss coefficients K.", default=0.0, positive=False),
        Param("elevation_change", "m", "Outlet height minus inlet height.", default=0.0, positive=False),
        Param("allowable_pressure_drop", "Pa", "Allowable pressure drop, for the utilisation.", optional=True),
    ),
    compute=pipe,
    assumptions=("Incompressible, isothermal, steady flow", "Full, circular pipe", "Fully developed flow"),
    keywords=("pipe", "pressure drop", "friction factor", "colebrook", "darcy", "moody", "head loss", "flow"),
)


# -- Heat exchanger ----------------------------------------------------------------------------------------------


def _effectiveness(ntu: float, cr: float, arrangement: str) -> float:
    if arrangement == "parallel":
        return (1.0 - math.exp(-ntu * (1.0 + cr))) / (1.0 + cr)
    if abs(1.0 - cr) < 1e-9:
        return ntu / (1.0 + ntu)
    e = math.exp(-ntu * (1.0 - cr))
    return (1.0 - e) / (1.0 - cr * e)


def heat_exchanger(v: dict[str, Any]) -> Outcome:
    arrangement = v["flow_arrangement"]
    th_in, tc_in = v["hot_inlet"], v["cold_inlet"]
    ch, cc = v.get("hot_capacity_rate"), v.get("cold_capacity_rate")
    out = Outcome(results=[])
    if th_in <= tc_in:
        raise ValueError("The hot inlet must be hotter than the cold inlet.")
    if v["method"] == "ntu":
        if ch is None or cc is None or v.get("overall_coefficient") is None or v.get("area") is None:
            raise ValueError("The effectiveness-NTU method needs both capacity rates (m cp), U and the area.")
        cmin, cmax = min(ch, cc), max(ch, cc)
        cr = cmin / cmax
        ntu = v["overall_coefficient"] * v["area"] / cmin
        eff = _effectiveness(ntu, cr, arrangement)
        q = eff * cmin * (th_in - tc_in)
        out.results += [
            Result("heat_duty", "Heat duty Q", q, "W", "kW"),
            Result("effectiveness", "Effectiveness", eff, "1"),
            Result("ntu", "NTU = UA / C_min", ntu, "1"),
            Result("capacity_ratio", "C_r = C_min / C_max", cr, "1"),
            Result("hot_outlet", "Hot outlet", th_in - q / ch, "degC"),
            Result("cold_outlet", "Cold outlet", tc_in + q / cc, "degC"),
        ]
        out.formulas += ["NTU = U A / C_min, C_r = C_min / C_max, Q = eps C_min (T_h,in - T_c,in)",
                         "counterflow: eps = (1 - exp(-NTU (1 - C_r))) / (1 - C_r exp(-NTU (1 - C_r)))"
                         if arrangement == "counterflow" else "parallel: eps = (1 - exp(-NTU (1 + C_r))) / (1 + C_r)"]
        out.checks.append(Check("thermodynamic limit", eff <= 1.0, f"Q / Q_max = {eff:.3g}", utilisation=eff))
        return out

    th_out, tc_out = v.get("hot_outlet"), v.get("cold_outlet")
    if th_out is None or tc_out is None:
        if ch is None or cc is None:
            raise ValueError("The LMTD method needs all four temperatures, or three of them with both capacity rates.")
        if th_out is None and tc_out is not None:
            th_out = th_in - cc * (tc_out - tc_in) / ch
        elif tc_out is None and th_out is not None:
            tc_out = tc_in + ch * (th_in - th_out) / cc
        else:
            raise ValueError("The LMTD method needs at least one outlet temperature (use method='ntu' otherwise).")
        out.notes.append("The missing outlet temperature follows from the energy balance.")
    if arrangement == "counterflow":
        dt1, dt2 = th_in - tc_out, th_out - tc_in
    else:
        dt1, dt2 = th_in - tc_in, th_out - tc_out
    if dt1 <= 0 or dt2 <= 0:
        raise ValueError(f"The temperatures cross (end differences {dt1:.3g} K and {dt2:.3g} K): impossible in a "
                         f"{arrangement} exchanger.")
    lmtd = dt1 if abs(dt1 - dt2) < 1e-9 else (dt1 - dt2) / math.log(dt1 / dt2)
    F = v["correction_factor"]
    out.results.append(Result("lmtd", "Log-mean temperature difference", lmtd, "K"))
    out.formulas += ["LMTD = (dT1 - dT2) / ln(dT1 / dT2)", "Q = U A F LMTD"]
    q = None
    if ch is not None:
        q = ch * (th_in - th_out)
    if cc is not None:
        qc = cc * (tc_out - tc_in)
        if q is not None and abs(q - qc) > 0.02 * max(abs(q), abs(qc)):
            out.warnings.append(f"The energy balance does not close: hot side {q / 1e3:.4g} kW, cold side {qc / 1e3:.4g} kW.")
        q = qc if q is None else q
    U, A = v.get("overall_coefficient"), v.get("area")
    if q is None and U is not None and A is not None:
        q = U * A * F * lmtd
    if q is None:
        raise ValueError("Give a capacity rate (to get Q from the temperatures) or U and the area.")
    out.results.append(Result("heat_duty", "Heat duty Q", q, "W", "kW"))
    out.results.append(Result("required_ua", "Required UA = Q / (F LMTD)", q / (F * lmtd), "W/K"))
    if U is not None:
        out.results.append(Result("required_area", "Required area", q / (U * F * lmtd), "m^2"))
        if A is not None:
            out.checks.append(Check("area", A >= q / (U * F * lmtd), f"A = {A:.4g} m^2 against "
                                    f"{q / (U * F * lmtd):.4g} m^2 required", utilisation=q / (U * F * lmtd) / A))
    if ch is not None and cc is not None:
        eff = q / (min(ch, cc) * (th_in - tc_in))
        out.results.append(Result("effectiveness", "Effectiveness", eff, "1"))
        out.checks.append(Check("thermodynamic limit", eff <= 1.0, f"Q / Q_max = {eff:.3g}", utilisation=eff))
    if F < 1.0:
        out.notes.append(f"LMTD correction factor F = {F:g} for a shell-and-tube or cross-flow geometry.")
    return out


HEAT_EXCHANGER = Calculator(
    id="heat_exchanger",
    title="Heat exchanger (LMTD and effectiveness-NTU)",
    summary="Duty, LMTD, required area or outlet temperatures of a counterflow or parallel-flow exchanger.",
    reference=Reference("Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed.",
                        "Sections 11.3 (LMTD method) and 11.4 (effectiveness-NTU method), Table 11.3"),
    params=(
        Param("method", "", "lmtd: from temperatures; ntu: outlet temperatures from U, A and the flows.",
              default="lmtd", choices=("lmtd", "ntu")),
        Param("flow_arrangement", "", "Flow arrangement.", default="counterflow", choices=("counterflow", "parallel")),
        Param("hot_inlet", "degC", "Hot-stream inlet temperature.", positive=False),
        Param("hot_outlet", "degC", "Hot-stream outlet temperature.", optional=True, positive=False),
        Param("cold_inlet", "degC", "Cold-stream inlet temperature.", positive=False),
        Param("cold_outlet", "degC", "Cold-stream outlet temperature.", optional=True, positive=False),
        Param("hot_capacity_rate", "W/K", "Hot capacity rate m cp.", optional=True),
        Param("cold_capacity_rate", "W/K", "Cold capacity rate m cp.", optional=True),
        Param("overall_coefficient", "W/(m^2*K)", "Overall heat-transfer coefficient U.", optional=True),
        Param("area", "m^2", "Heat-transfer area A.", optional=True),
        Param("correction_factor", "1", "LMTD correction factor F (1 for pure counter/parallel flow).", default=1.0),
    ),
    compute=heat_exchanger,
    assumptions=("Steady state, no heat loss to the surroundings", "Constant U and specific heats",
                 "No phase change unless the capacity rate is taken as very large"),
    keywords=("heat exchanger", "lmtd", "ntu", "effectiveness", "counterflow", "duty", "shell and tube"),
)


# -- Layered wall ------------------------------------------------------------------------------------------------


def layered_wall(v: dict[str, Any]) -> Outcome:
    layers = v.get("layers") or []
    if not isinstance(layers, list) or not layers:
        raise ValueError("Give the layers as [{thickness, conductivity (or material), name?}, ...] from inside to outside.")
    A = v["area"]
    resistances: list[tuple[str, float]] = []
    if v.get("h_inside") is not None:
        resistances.append(("inside film", 1.0 / (v["h_inside"] * A)))
    for k, layer in enumerate(layers):
        if not isinstance(layer, dict) or "thickness" not in layer:
            raise ValueError(f"Layer {k + 1} needs a thickness and a conductivity (or a material).")
        t = to_si(layer["thickness"], "m", f"layers[{k}].thickness")
        if layer.get("conductivity") is not None:
            cond = to_si(layer["conductivity"], "W/(m*K)", f"layers[{k}].conductivity")
        elif layer.get("material"):
            cond = float(find_material(str(layer["material"]))[1]["k"])
        else:
            raise ValueError(f"Layer {k + 1} needs a conductivity or a material.")
        resistances.append((str(layer.get("name") or f"layer {k + 1}"), t / (cond * A)))
        if v.get("contact_resistance") and k < len(layers) - 1:
            resistances.append((f"contact {k + 1}-{k + 2}", v["contact_resistance"] / A))
    if v.get("h_outside") is not None:
        resistances.append(("outside film", 1.0 / (v["h_outside"] * A)))
    total = sum(r for _, r in resistances)
    dT = v["temperature_inside"] - v["temperature_outside"]
    q = dT / total
    out = Outcome(results=[
        Result("heat_rate", "Heat flow q", q, "W"),
        Result("heat_flux", "Heat flux q''", q / A, "W/m^2"),
        Result("total_resistance", "Total thermal resistance", total, "K/W"),
        Result("u_value", "Overall U-value", 1.0 / (total * A), "W/(m^2*K)"),
    ])
    temperature = v["temperature_inside"]
    for name, r in resistances[:-1]:
        temperature -= q * r
        out.results.append(Result(f"temperature_after_{name.replace(' ', '_').replace('-', '_')}",
                                  f"Temperature after {name}", temperature, "degC"))
    out.formulas += ["R_layer = L / (k A), R_film = 1 / (h A), R_contact = R''_c / A", "q = (T_in - T_out) / sum R",
                     "T_(i+1) = T_i - q R_i"]
    out.notes.append("Resistances: " + ", ".join(f"{n} {r:.4g} K/W ({100 * r / total:.1f}%)" for n, r in resistances))
    if v.get("allowable_heat_flux") is not None:
        allow = v["allowable_heat_flux"]
        out.checks.append(Check("heat flux", abs(q / A) <= allow, f"|q''| = {abs(q / A):.4g} W/m^2 against "
                                f"{allow:.4g} W/m^2", utilisation=abs(q / A) / allow))
    return out


LAYERED_WALL = Calculator(
    id="layered_wall",
    title="Conduction through a layered (composite) plane wall",
    summary="Heat flow, U-value and interface temperatures of a plane wall of layers in series, with surface films.",
    reference=Reference("Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed.",
                        "Section 3.1 (the plane wall: thermal resistance, composite wall, contact resistance)"),
    params=(
        Param("layers", "m", "Layers from inside to outside: [{thickness, conductivity or material, name?}]."),
        Param("temperature_inside", "degC", "Inside (fluid or surface) temperature.", positive=False),
        Param("temperature_outside", "degC", "Outside (fluid or surface) temperature.", positive=False),
        Param("area", "m^2", "Wall area.", default=1.0),
        Param("h_inside", "W/(m^2*K)", "Inside convection coefficient (omit for a surface temperature).", optional=True),
        Param("h_outside", "W/(m^2*K)", "Outside convection coefficient.", optional=True),
        Param("contact_resistance", "m^2*K/W", "Contact resistance R''_c at each interface.", optional=True),
        Param("allowable_heat_flux", "W/m^2", "Allowable heat flux, for the utilisation.", optional=True),
    ),
    compute=layered_wall,
    assumptions=("Steady, one-dimensional conduction", "Constant conductivities, no heat generation",
                 "Perfect contact between layers unless a contact resistance is given"),
    keywords=("wall", "conduction", "insulation", "u-value", "thermal resistance", "composite", "heat loss"),
)

CALCULATORS = (PIPE, HEAT_EXCHANGER, LAYERED_WALL)

__all__ = ["CALCULATORS", "HEAT_EXCHANGER", "LAYERED_WALL", "PIPE", "colebrook", "swamee_jain"]
