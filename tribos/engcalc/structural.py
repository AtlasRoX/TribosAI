"""Structural calculators: beams, columns, thin-wall pressure vessels, shafts and bolted joints.

Every function takes SI floats (Pa, m, N, N*m) and returns an Outcome: the results, the limit-state checks that set
the utilisation, and the validity checks of the method's assumptions.
"""

from __future__ import annotations

import math
from typing import Any

from .core import Calculator, Check, Outcome, Param, Reference, Result

# -- Cross-sections ----------------------------------------------------------------------------------------------

SECTION_PARAMS: tuple[Param, ...] = (
    Param("section", "", "Cross-section shape (rectangle: width, height; circle: diameter; tube: diameter, "
          "inner_diameter; custom: second_moment_of_area, extreme_fibre_distance, area).",
          default="custom", choices=("rectangle", "circle", "tube", "custom")),
    Param("width", "m", "Rectangle width b.", optional=True),
    Param("height", "m", "Rectangle height h (in the bending plane).", optional=True),
    Param("diameter", "m", "Circle or tube outer diameter.", optional=True),
    Param("inner_diameter", "m", "Tube inner diameter.", optional=True),
    Param("second_moment_of_area", "m^4", "Second moment of area I (custom section).", optional=True),
    Param("extreme_fibre_distance", "m", "Distance c from the neutral axis to the extreme fibre (custom).",
          optional=True),
    Param("area", "m^2", "Cross-section area A (custom section).", optional=True),
)


def section_properties(v: dict[str, Any]) -> dict[str, float | None]:
    """A, I and c of the cross-section (None where a custom section did not give it)."""
    shape = v.get("section") or "custom"
    if shape == "custom" and v.get("second_moment_of_area") is None:
        # No shape was named and no I given: the dimensions that were given say which shape it is.
        if v.get("width") is not None and v.get("height") is not None:
            shape = "rectangle"
        elif v.get("diameter") is not None:
            shape = "tube" if v.get("inner_diameter") is not None else "circle"

    def need(*names: str) -> list[float]:
        missing = [n for n in names if v.get(n) is None]
        if missing:
            raise ValueError(f"A {shape} section needs {', '.join(missing)}.")
        return [float(v[n]) for n in names]

    if shape == "rectangle":
        b, h = need("width", "height")
        return {"A": b * h, "I": b * h**3 / 12.0, "c": h / 2.0, "depth": h}
    if shape == "circle":
        (d,) = need("diameter")
        return {"A": math.pi * d**2 / 4.0, "I": math.pi * d**4 / 64.0, "c": d / 2.0, "depth": d}
    if shape == "tube":
        d, di = need("diameter", "inner_diameter")
        if di >= d:
            raise ValueError("The tube's inner diameter must be smaller than its outer diameter.")
        return {"A": math.pi * (d**2 - di**2) / 4.0, "I": math.pi * (d**4 - di**4) / 64.0, "c": d / 2.0, "depth": d}
    (i,) = need("second_moment_of_area")
    c = v.get("extreme_fibre_distance")
    return {"A": v.get("area"), "I": i, "c": c, "depth": 2.0 * c if c else None}


def _strength_check(name: str, stress: float, strength: float | None, n_req: float, label: str) -> Check | None:
    if strength is None:
        return None
    sf = strength / stress if stress > 0 else math.inf
    return Check(name, sf >= n_req, f"{label}: safety factor {sf:.3g} against {n_req:.3g} required",
                 utilisation=n_req / sf if sf > 0 else math.inf)


# -- Beam --------------------------------------------------------------------------------------------------------


def beam(v: dict[str, Any]) -> Outcome:
    L, E = v["length"], v["elastic_modulus"]
    sec = section_properties(v)
    inertia = float(sec["I"] or 0.0)
    
    # Normalize unambiguous support and load descriptions (e.g. 'tip point load' -> 'point')
    support_raw = str(v.get("support") or "simply_supported").lower().strip()
    if "cantilever" in support_raw or "fixed" in support_raw:
        support = "cantilever"
    elif "simply" in support_raw or "pin" in support_raw:
        support = "simply_supported"
    else:
        support = support_raw

    load_raw = str(v.get("load") or "point").lower().strip()
    if "point" in load_raw or "tip" in load_raw:
        load = "point"
    elif "udl" in load_raw or "distribut" in load_raw:
        load = "udl"
    else:
        load = load_raw

    out = Outcome(results=[])
    if load == "point":
        P_val = v.get("point_load")
        if P_val is None:
            # Fallback to P or load_value if given
            P_val = v.get("P") if v.get("P") is not None else v.get("load_value")
        if P_val is None:
            raise ValueError("A point load needs point_load (N).")
        P = float(P_val)
        a = v.get("load_position")
        if support == "simply_supported":
            a = L / 2.0 if a is None else a
            if not 0.0 < a < L:
                raise ValueError("load_position must lie between the supports (0 < a < L).")
            b = L - a
            short = min(a, b)
            M = P * a * b / L
            V = P * max(a, b) / L
            delta = P * short * (L**2 - short**2) ** 1.5 / (9.0 * math.sqrt(3.0) * E * inertia * L)
            out.formulas += ["M_max = P a b / L", "delta_max = P b (L^2 - b^2)^(3/2) / (9 sqrt(3) E I L), b = min(a, L - a)",
                             "(midspan: delta = P L^3 / (48 E I), M = P L / 4)"]
        else:
            a = L if a is None else a
            if not 0.0 < a <= L:
                raise ValueError("load_position (from the fixed end) must satisfy 0 < a <= L.")
            M, V = P * a, P
            delta = P * a**2 * (3.0 * L - a) / (6.0 * E * inertia)
            out.formulas += ["M_max = P a (at the fixed end)", "delta_tip = P a^2 (3L - a) / (6 E I)",
                             "(end load: delta = P L^3 / (3 E I))"]
    else:
        if v.get("distributed_load") is None:
            raise ValueError("A uniformly distributed load needs distributed_load (N/m).")
        w = v["distributed_load"]
        if support == "simply_supported":
            M, V, delta = w * L**2 / 8.0, w * L / 2.0, 5.0 * w * L**4 / (384.0 * E * inertia)
            out.formulas += ["M_max = w L^2 / 8", "delta_max = 5 w L^4 / (384 E I)"]
        else:
            M, V, delta = w * L**2 / 2.0, w * L, w * L**4 / (8.0 * E * inertia)
            out.formulas += ["M_max = w L^2 / 2", "delta_tip = w L^4 / (8 E I)"]
    out.results += [
        Result("second_moment_of_area", "Second moment of area", inertia, "m^4"),
        Result("deflection_ratio", "Deflection divided by span", delta / L, "1"),
        Result("max_deflection", "Maximum deflection", delta, "m", "mm"),
        Result("max_bending_moment", "Maximum bending moment", M, "N*m", "kN*m"),
        Result("max_shear_force", "Maximum shear force", V, "N", "kN"),
    ]
    if sec["c"]:
        sigma = M * float(sec["c"]) / inertia
        out.results.append(Result("max_bending_stress", "Maximum bending stress", sigma, "Pa", "MPa"))
        out.formulas.append("sigma_max = M_max c / I")
        check = _strength_check("bending stress", sigma, v.get("yield_strength"), v["required_safety_factor"],
                                "yield / bending stress")
        if check:
            out.checks.append(check)
        if v.get("yield_strength") is None:
            out.warnings.append("No yield strength (or material) was given, so the bending stress is not checked.")
    else:
        out.warnings.append("No extreme-fibre distance c was given, so the bending stress is not computed.")
    if v.get("deflection_limit_ratio") is not None:
        limit = L / v["deflection_limit_ratio"]
        out.checks.append(Check("deflection", delta <= limit,
                                f"deflection {delta * 1e3:.4g} mm against the serviceability limit L/{v['deflection_limit_ratio']:g} "
                                f"= {limit * 1e3:.4g} mm", utilisation=delta / limit))
    depth = sec.get("depth")
    if depth:
        ratio = L / float(depth)
        out.validity.append(Check("slenderness", ratio >= 10.0,
                                  f"span/depth = {ratio:.3g}; Euler-Bernoulli theory neglects shear deformation, which "
                                  "matters below about 10 (use Timoshenko beam theory)"))
    out.validity.append(Check("small deflection", delta <= L / 20.0,
                              f"deflection/span = {delta / L:.3g}; the linear theory assumes small deflections (< L/20)"))
    return out


BEAM = Calculator(
    id="beam",
    title="Beam deflection and bending stress",
    summary="Simply supported or cantilever beam under a point load or a uniformly distributed load.",
    reference=Reference("Roark's Formulas for Stress and Strain, 7th ed. (Young & Budynas)",
                        "Table 8.1, cases 1a, 2a (cantilever) and 1e, 2e (simply supported)"),
    params=(
        Param("support", "", "Support condition.", default="simply_supported", choices=("simply_supported", "cantilever")),
        Param("load", "", "Load type.", default="point", choices=("point", "udl")),
        Param("length", "m", "Span L."),
        Param("point_load", "N", "Point load P (load='point').", optional=True),
        Param("load_position", "m", "Point-load position a: from the left support (simply supported, default midspan) "
              "or from the fixed end (cantilever, default the free end).", optional=True),
        Param("distributed_load", "N/m", "Uniformly distributed load w (load='udl').", optional=True),
        Param("elastic_modulus", "Pa", "Young's modulus E.", material="E"),
        *SECTION_PARAMS,
        Param("yield_strength", "Pa", "Yield strength, for the stress check.", material="yield_strength", optional=True),
        Param("required_safety_factor", "1", "Required safety factor on yield.", default=1.5),
        Param("deflection_limit_ratio", "1", "Optional serviceability limit as a span ratio (e.g. 360 for L/360). No design limit is assumed.", optional=True),
    ),
    compute=beam,
    assumptions=("Linear-elastic, homogeneous, prismatic beam", "Euler-Bernoulli bending (plane sections remain plane)",
                 "Small deflections", "Self-weight not included unless added to the load"),
    keywords=("beam", "deflection", "cantilever", "simply supported", "bending", "moment", "udl"),
)


# -- Column buckling ---------------------------------------------------------------------------------------------

END_CONDITIONS = {"pinned_pinned": 1.0, "fixed_free": 2.0, "fixed_pinned": 0.699, "fixed_fixed": 0.5}


def buckling(v: dict[str, Any]) -> Outcome:
    L, E, sy = v["length"], v["elastic_modulus"], v["yield_strength"]
    sec = section_properties(v)
    if not sec["A"]:
        raise ValueError("Column buckling needs the cross-section area (a shape, or area for a custom section).")
    A, inertia = float(sec["A"]), float(sec["I"] or 0.0)
    K = v.get("effective_length_factor") or END_CONDITIONS[v["end_condition"]]
    r = math.sqrt(inertia / A)
    slenderness = K * L / r
    transition = math.sqrt(2.0 * math.pi**2 * E / sy)
    out = Outcome(results=[])
    if slenderness >= transition:
        sigma_cr = math.pi**2 * E / slenderness**2
        regime = "Euler (long column)"
    else:
        sigma_cr = sy - (sy * slenderness / (2.0 * math.pi)) ** 2 / E
        regime = "Johnson (intermediate column)"
    P_cr = sigma_cr * A
    out.formulas += [
        "r = sqrt(I / A), slenderness = K L / r, transition (S_y / 2 point) C_c = sqrt(2 pi^2 E / S_y)",
        "Euler (KL/r >= C_c): P_cr = pi^2 E I / (K L)^2",
        "Johnson (KL/r < C_c): sigma_cr = S_y - (S_y KL/r / (2 pi))^2 / E",
    ]
    out.results += [
        Result("critical_load", f"Critical load ({regime})", P_cr, "N", "kN"),
        Result("critical_stress", "Critical stress", sigma_cr, "Pa", "MPa"),
        Result("slenderness_ratio", "Slenderness ratio KL/r", slenderness, "1"),
        Result("transition_slenderness", "Transition slenderness C_c", transition, "1"),
        Result("effective_length_factor", "Effective-length factor K", K, "1"),
    ]
    out.notes.append(f"KL/r = {slenderness:.4g} is {'above' if slenderness >= transition else 'below'} C_c = "
                     f"{transition:.4g}, so the {regime.split(' ')[0]} formula applies.")
    if v.get("effective_length_factor") is None and v["end_condition"] != "pinned_pinned":
        out.notes.append("K is the theoretical value; design codes recommend larger ones for imperfect fixity "
                         "(e.g. AISC: 2.1 fixed-free, 0.80 fixed-pinned, 0.65 fixed-fixed).")
    if v.get("axial_load") is not None:
        P = v["axial_load"]
        n = P_cr / P
        n_req = v["required_safety_factor"]
        out.results.append(Result("safety_factor", "Safety factor against buckling", n, "1"))
        out.checks.append(Check("buckling", n >= n_req, f"P_cr / P = {n:.3g} against {n_req:.3g} required",
                                utilisation=n_req / n))
    out.validity.append(Check("slenderness", slenderness >= 10.0,
                              f"KL/r = {slenderness:.3g}; below about 10 the member is a short block and crushing, "
                              "not buckling, governs"))
    return out


BUCKLING = Calculator(
    id="column_buckling",
    title="Column buckling (Euler / Johnson)",
    summary="Critical load of a centrally loaded column, Euler above the transition slenderness and Johnson below it.",
    reference=Reference("Shigley's Mechanical Engineering Design, 10th ed. (Budynas & Nisbett)",
                        "Sections 4-12 (long columns, Euler) and 4-13 (intermediate columns, Johnson)"),
    params=(
        Param("length", "m", "Column length L."),
        Param("end_condition", "", "End condition (sets K).", default="pinned_pinned", choices=tuple(END_CONDITIONS)),
        Param("effective_length_factor", "1", "Effective-length factor K (overrides the end condition).", optional=True),
        Param("elastic_modulus", "Pa", "Young's modulus E.", material="E"),
        Param("yield_strength", "Pa", "Yield strength S_y.", material="yield_strength"),
        *SECTION_PARAMS,
        Param("axial_load", "N", "Applied axial load P, for the safety factor.", optional=True),
        Param("required_safety_factor", "1", "Required safety factor against buckling.", default=2.0),
    ),
    compute=buckling,
    assumptions=("Straight, prismatic column", "Central (concentric) load", "Buckling about the weaker axis is the "
                 "section's I (give the minimum I)"),
    keywords=("column", "buckling", "euler", "johnson", "critical load", "slenderness", "strut"),
)


# -- Thin-wall pressure vessel -----------------------------------------------------------------------------------


def pressure_vessel(v: dict[str, Any]) -> Outcome:
    P, Di = v["pressure"], v["inner_diameter"]
    S, Ej, ca = v.get("allowable_stress"), v["joint_efficiency"], v["corrosion_allowance"] or 0.0
    t = v.get("thickness")
    R = Di / 2.0 + ca  # the corroded inside radius
    out = Outcome(results=[])
    if Ej > 1.0:
        raise ValueError("The joint efficiency E is at most 1.")
    if S is not None:
        if S * Ej - 0.6 * P <= 0:
            raise ValueError("The pressure is too high for UG-27 with this allowable stress (S E <= 0.6 P).")
        t_circ = P * R / (S * Ej - 0.6 * P)
        t_long = P * R / (2.0 * S * Ej + 0.4 * P)
        t_req = max(t_circ, t_long) + ca
        out.results += [
            Result("required_thickness", "Required thickness (UG-27, incl. corrosion allowance)", t_req, "m", "mm"),
            Result("thickness_circumferential", "Thickness for circumferential stress", t_circ, "m", "mm"),
            Result("thickness_longitudinal", "Thickness for longitudinal stress", t_long, "m", "mm"),
        ]
        out.formulas += ["UG-27(c)(1): t = P R / (S E - 0.6 P)", "UG-27(c)(2): t = P R / (2 S E + 0.4 P)",
                         "R = inside radius in the corroded condition"]
        out.validity.append(Check("UG-27(c)(1) range", P <= 0.385 * S * Ej and t_circ <= R / 2.0,
                                  f"P = {P / 1e6:.4g} MPa against 0.385 S E = {0.385 * S * Ej / 1e6:.4g} MPa and "
                                  "t <= R/2 (else use Appendix 1-2 thick-shell formulas)"))
        out.validity.append(Check("UG-27(c)(2) range", P <= 1.25 * S * Ej,
                                  f"P against 1.25 S E = {1.25 * S * Ej / 1e6:.4g} MPa"))
        if t is not None:
            out.checks.append(Check("code thickness", t >= t_req, f"t = {t * 1e3:.4g} mm against t_required = "
                                    f"{t_req * 1e3:.4g} mm", utilisation=t_req / t))
    else:
        out.warnings.append("No allowable stress S was given, so the ASME UG-27 thickness is not computed: S comes from "
                            "ASME Section II, Part D for the material and design temperature.")
    if t is not None:
        tm = t - ca
        if tm <= 0:
            raise ValueError("The thickness must exceed the corrosion allowance.")
        sigma_h = P * (Di + 2 * ca + tm) / (2.0 * tm)
        sigma_l = P * (Di + 2 * ca) / (4.0 * tm)
        vm = math.sqrt(sigma_h**2 - sigma_h * sigma_l + sigma_l**2)
        out.results += [
            Result("hoop_stress", "Hoop (circumferential) stress", sigma_h, "Pa", "MPa"),
            Result("longitudinal_stress", "Longitudinal stress", sigma_l, "Pa", "MPa"),
            Result("von_mises_stress", "Von Mises membrane stress", vm, "Pa", "MPa"),
        ]
        out.formulas += ["sigma_h = P (D_i + t) / (2 t) (mean diameter)", "sigma_l = P D_i / (4 t)",
                         "sigma_vm = sqrt(sigma_h^2 - sigma_h sigma_l + sigma_l^2)"]
        check = _strength_check("membrane yield", vm, v.get("yield_strength"), v["required_safety_factor"],
                                "yield / von Mises membrane stress")
        if check:
            out.checks.append(check)
        if S is not None:
            out.checks.append(Check("allowable stress", sigma_h <= S * Ej, f"hoop stress {sigma_h / 1e6:.4g} MPa "
                                    f"against S E = {S * Ej / 1e6:.4g} MPa", utilisation=sigma_h / (S * Ej)))
        out.validity.append(Check("thin wall", tm <= R / 10.0,
                                  f"t/R = {tm / R:.3g}; membrane (thin-wall) theory needs t < R/10"))
    if t is None and S is None:
        raise ValueError("Give the wall thickness (for the stresses) and/or the allowable stress (for the UG-27 "
                         "required thickness).")
    return out


PRESSURE_VESSEL = Calculator(
    id="pressure_vessel",
    title="Thin-wall cylindrical pressure vessel",
    summary="Hoop and longitudinal stress of a cylindrical shell, and the ASME VIII-1 UG-27 required thickness.",
    reference=Reference("ASME Boiler and Pressure Vessel Code, Section VIII, Division 1",
                        "UG-27 (thickness of shells under internal pressure); membrane stresses per Shigley 10th ed. "
                        "Section 3-13"),
    params=(
        Param("pressure", "Pa", "Internal design pressure (gauge)."),
        Param("inner_diameter", "m", "Inside diameter D_i."),
        Param("thickness", "m", "Wall thickness t (for the stresses and the code check).", optional=True),
        Param("allowable_stress", "Pa", "Maximum allowable stress S (ASME II-D) for UG-27.", optional=True),
        Param("joint_efficiency", "1", "Weld joint efficiency E (UW-12).", default=1.0),
        Param("corrosion_allowance", "m", "Corrosion allowance.", default=0.0, positive=False),
        Param("yield_strength", "Pa", "Yield strength, for the membrane-yield check.", material="yield_strength",
              optional=True),
        Param("required_safety_factor", "1", "Required safety factor on yield (membrane check).", default=1.5),
    ),
    compute=pressure_vessel,
    assumptions=("Cylindrical shell away from heads, nozzles and supports", "Internal pressure only",
                 "Uniform wall thickness"),
    keywords=("pressure vessel", "hoop stress", "boiler", "tank", "cylinder", "asme", "ug-27", "wall thickness"),
)


# -- Shaft -------------------------------------------------------------------------------------------------------


def shaft(v: dict[str, Any]) -> Outcome:
    d, di = v["diameter"], v.get("inner_diameter") or 0.0
    if di >= d:
        raise ValueError("The inner diameter must be smaller than the outer diameter.")
    T, M, F = v["torque"], v["bending_moment"] or 0.0, v["axial_force"] or 0.0
    J = math.pi * (d**4 - di**4) / 32.0
    inertia = J / 2.0
    A = math.pi * (d**2 - di**2) / 4.0
    tau = T * (d / 2.0) / J
    sigma_b = M * (d / 2.0) / inertia
    sigma_a = F / A
    sigma = sigma_b + sigma_a
    vm = math.sqrt(sigma**2 + 3.0 * tau**2)
    tresca = math.sqrt((sigma / 2.0) ** 2 + tau**2)
    out = Outcome(results=[
        Result("shear_stress", "Torsional shear stress", tau, "Pa", "MPa"),
        Result("bending_stress", "Bending stress", sigma_b, "Pa", "MPa"),
        Result("von_mises_stress", "Von Mises stress", vm, "Pa", "MPa"),
        Result("max_shear_stress", "Maximum shear stress (Tresca)", tresca, "Pa", "MPa"),
    ])
    out.formulas += ["J = pi (d^4 - d_i^4) / 32, tau = T (d/2) / J", "sigma = 32 M d / (pi (d^4 - d_i^4)) + F / A",
                     "sigma' = sqrt(sigma^2 + 3 tau^2) (distortion energy)", "tau_max = sqrt((sigma/2)^2 + tau^2)"]
    if v.get("length") is not None:
        G = v.get("shear_modulus")
        if G is None:
            if v.get("elastic_modulus") is None or v.get("poisson_ratio") is None:
                raise ValueError("The angle of twist needs shear_modulus, or elastic_modulus and poisson_ratio (or a "
                                 "material).")
            G = v["elastic_modulus"] / (2.0 * (1.0 + v["poisson_ratio"]))
        theta = T * v["length"] / (G * J)
        out.results.append(Result("angle_of_twist", "Angle of twist", theta, "rad", "degree"))
        out.formulas.append("theta = T L / (G J), G = E / (2 (1 + nu))")
    check = _strength_check("von Mises yield", vm, v.get("yield_strength"), v["required_safety_factor"],
                            "yield / von Mises stress")
    if check:
        out.checks.append(check)
        sy = v["yield_strength"]
        out.results.append(Result("safety_factor_tresca", "Safety factor (Tresca)", sy / (2.0 * tresca), "1"))
    else:
        out.warnings.append("No yield strength (or material) was given, so the stresses are not checked.")
    out.warnings.append("Static check only: stress concentrations (shoulders, keyways) and fatigue under rotating "
                        "bending are not included; use the fatigue calculator with the fluctuating stresses.")
    return out


SHAFT = Calculator(
    id="shaft",
    title="Shaft torsion with combined bending (von Mises)",
    summary="Torsional shear, bending and axial stress of a solid or hollow round shaft, combined by von Mises.",
    reference=Reference("Shigley's Mechanical Engineering Design, 10th ed. (Budynas & Nisbett)",
                        "Section 3-12 (torsion) and Section 5-5 (distortion-energy theory)"),
    params=(
        Param("diameter", "m", "Outer diameter d."),
        Param("inner_diameter", "m", "Inner diameter (hollow shaft).", optional=True),
        Param("torque", "N*m", "Torque T."),
        Param("bending_moment", "N*m", "Bending moment M at the section.", default=0.0, positive=False),
        Param("axial_force", "N", "Axial force (tension positive).", default=0.0, positive=False),
        Param("length", "m", "Length, for the angle of twist.", optional=True),
        Param("shear_modulus", "Pa", "Shear modulus G.", optional=True),
        Param("elastic_modulus", "Pa", "Young's modulus E (for G).", material="E", optional=True),
        Param("poisson_ratio", "1", "Poisson's ratio (for G).", material="nu", optional=True),
        Param("yield_strength", "Pa", "Yield strength.", material="yield_strength", optional=True),
        Param("required_safety_factor", "1", "Required safety factor on yield.", default=2.0),
    ),
    compute=shaft,
    assumptions=("Round, prismatic shaft", "Linear-elastic material", "Static loads at the section considered"),
    keywords=("shaft", "torsion", "torque", "twist", "von mises", "combined bending"),
)


# -- Bolted joint ------------------------------------------------------------------------------------------------

# ISO 261/262 coarse pitches (mm) and ISO 898-1 property classes: (proof, ultimate, yield) in MPa.
ISO_COARSE_PITCH_MM = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75,
                       14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0, 30: 3.5, 36: 4.0}
PROPERTY_CLASSES = {"4.6": (225, 400, 240), "4.8": (310, 420, 340), "5.8": (380, 520, 420), "8.8": (580, 800, 640),
                    "9.8": (650, 900, 720), "10.9": (830, 1040, 940), "12.9": (970, 1220, 1100)}


def bolt(v: dict[str, Any]) -> Outcome:
    d = v["diameter"]
    out = Outcome(results=[])
    p = v.get("pitch")
    if p is None:
        nominal = round(d * 1e3, 1)
        if nominal not in ISO_COARSE_PITCH_MM:
            raise ValueError(f"No ISO coarse pitch is tabulated for d = {nominal:g} mm; give the pitch.")
        p = ISO_COARSE_PITCH_MM[nominal] * 1e-3
        out.notes.append(f"ISO coarse pitch {p * 1e3:g} mm assumed.")
    At = math.pi / 4.0 * (d - 0.938194 * p) ** 2
    Sp = v.get("proof_strength")
    if Sp is None:
        proof = PROPERTY_CLASSES[v["property_class"]][0]
        if v["property_class"] == "8.8" and d > 16e-3:
            proof = 600
        Sp = proof * 1e6
    K = v["nut_factor"]
    if v.get("preload") is not None:
        Fi = v["preload"]
        T = K * Fi * d
        out.notes.append("Torque computed from the given preload.")
    elif v.get("torque") is not None:
        T = v["torque"]
        Fi = T / (K * d)
        out.notes.append("Preload computed from the given tightening torque.")
    else:
        Fi = v["preload_fraction"] * At * Sp
        T = K * Fi * d
        out.notes.append(f"Recommended preload F_i = {v['preload_fraction']:g} A_t S_p (0.75 reusable, 0.90 permanent).")
    out.results += [
        Result("tensile_stress_area", "Tensile-stress area A_t", At, "m^2", "mm^2"),
        Result("preload", "Preload F_i", Fi, "N", "kN"),
        Result("tightening_torque", "Tightening torque T", T, "N*m"),
        Result("preload_stress", "Preload stress F_i / A_t", Fi / At, "Pa", "MPa"),
    ]
    out.formulas += ["A_t = pi/4 (d - 0.938194 p)^2", "T = K F_i d", "F_i = 0.75 A_t S_p (reusable connection)"]
    out.checks.append(Check("preload against proof", Fi <= At * Sp, f"F_i / (A_t S_p) = {Fi / (At * Sp):.3g}",
                            utilisation=Fi / (At * Sp)))
    P = v.get("external_load")
    if P is not None:
        C = v.get("joint_constant")
        if C is None:
            out.warnings.append("No joint stiffness constant C = k_b / (k_b + k_m) was given, so the bolt load and the "
                                "separation check under the external load are not evaluated.")
        else:
            Fb = Fi + C * P
            n_load = (Sp * At - Fi) / (C * P)
            n_sep = Fi / (P * (1.0 - C))
            out.results += [
                Result("bolt_load", "Bolt load F_b = F_i + C P", Fb, "N", "kN"),
                Result("load_factor", "Yield load factor n_L", n_load, "1"),
                Result("separation_factor", "Joint separation factor n_0", n_sep, "1"),
            ]
            out.formulas += ["F_b = F_i + C P", "n_L = (S_p A_t - F_i) / (C P)", "n_0 = F_i / (P (1 - C))"]
            n_req = v["required_safety_factor"]
            out.checks.append(Check("bolt yield under load", n_load >= n_req, f"n_L = {n_load:.3g}",
                                    utilisation=n_req / n_load if n_load > 0 else math.inf))
            out.checks.append(Check("joint separation", n_sep >= n_req, f"n_0 = {n_sep:.3g}",
                                    utilisation=n_req / n_sep if n_sep > 0 else math.inf))
    out.warnings.append(f"The torque-preload relation T = K F_i d scatters by about +/-25-30% (K = {K:g} assumed); use "
                        "measured K or direct preload control for critical joints.")
    return out


BOLT = Calculator(
    id="bolt_preload",
    title="Bolt preload and tightening torque",
    summary="ISO metric bolt: tensile-stress area, recommended preload, torque, and the joint under an external load.",
    reference=Reference("Shigley's Mechanical Engineering Design, 10th ed. (Budynas & Nisbett)",
                        "Sections 8-8 (bolt torque and tension) and 8-9 (tension joints with preload); ISO 898-1 "
                        "property classes"),
    params=(
        Param("diameter", "m", "Nominal diameter d (e.g. 12 mm for M12)."),
        Param("pitch", "m", "Thread pitch (ISO coarse when omitted).", optional=True),
        Param("property_class", "", "ISO 898-1 property class.", default="8.8", choices=tuple(PROPERTY_CLASSES)),
        Param("proof_strength", "Pa", "Proof strength S_p (overrides the property class).", optional=True),
        Param("nut_factor", "1", "Torque (nut) factor K: 0.2 typical, 0.3 black finish, 0.18 lubricated.", default=0.2),
        Param("preload_fraction", "1", "Preload as a fraction of the proof load.", default=0.75),
        Param("preload", "N", "Given preload F_i.", optional=True),
        Param("torque", "N*m", "Given tightening torque.", optional=True),
        Param("external_load", "N", "External tensile load on the joint P.", optional=True),
        Param("joint_constant", "1", "Joint stiffness constant C = k_b / (k_b + k_m).", optional=True),
        Param("required_safety_factor", "1", "Required load and separation factors.", default=1.5),
    ),
    compute=bolt,
    assumptions=("ISO metric coarse or given thread", "Static tensile loading", "Joint members stay elastic"),
    keywords=("bolt", "preload", "torque", "fastener", "screw", "clamp", "tightening"),
)


CALCULATORS = (BEAM, BUCKLING, PRESSURE_VESSEL, SHAFT, BOLT)

__all__ = ["BEAM", "BOLT", "BUCKLING", "CALCULATORS", "PRESSURE_VESSEL", "SHAFT", "section_properties"]
