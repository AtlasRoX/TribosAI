"""T9: engineering calculators, checked against textbook closed forms and worked values."""

from __future__ import annotations

import math

import pytest

from tribos.engcalc import list_calculators, run_calculator


def _r(result: dict, name: str) -> float:
    return next(r["value"] for r in result["results"] if r["name"] == name)


# -- Beams --------------------------------------------------------------------------------------------------------

E, B, H = 200e9, 0.05, 0.1
I_RECT = B * H**3 / 12


@pytest.mark.parametrize(
    ("support", "load", "inputs", "delta", "moment"),
    [
        ("cantilever", "point", {"point_load": 1000.0}, 1000 * 2**3 / (3 * E * I_RECT), 1000 * 2),
        ("cantilever", "udl", {"distributed_load": 500.0}, 500 * 2**4 / (8 * E * I_RECT), 500 * 2**2 / 2),
        ("simply_supported", "point", {"point_load": 1000.0}, 1000 * 2**3 / (48 * E * I_RECT), 1000 * 2 / 4),
        ("simply_supported", "udl", {"distributed_load": 500.0}, 5 * 500 * 2**4 / (384 * E * I_RECT), 500 * 2**2 / 8),
    ],
)
def test_beam_cases_match_the_textbook_formulas(support, load, inputs, delta, moment):
    result = run_calculator("beam", {"support": support, "load": load, "length": 2.0, "elastic_modulus": E,
                                     "section": "rectangle", "width": B, "height": H, **inputs})
    assert _r(result, "max_deflection") == pytest.approx(delta, rel=1e-12)
    assert _r(result, "max_bending_moment") == pytest.approx(moment, rel=1e-12)
    assert _r(result, "max_bending_stress") == pytest.approx(moment * (H / 2) / I_RECT, rel=1e-12)
    assert "Roark" in result["reference"]["source"] and "Table 8.1" in result["reference"]["section"]


def test_an_off_centre_point_load_uses_the_general_formula():
    # Maximum deflection with the load at a = L/4 on a simply supported span (Roark case 1e).
    L, P, a = 4.0, 1000.0, 1.0
    b = L - a
    result = run_calculator("beam", {"length": L, "point_load": P, "load_position": a, "elastic_modulus": E,
                                     "second_moment_of_area": 1e-6, "extreme_fibre_distance": 0.05})
    expected = P * a * (L**2 - a**2) ** 1.5 / (9 * math.sqrt(3) * E * 1e-6 * L)
    assert _r(result, "max_deflection") == pytest.approx(expected, rel=1e-12)
    assert _r(result, "max_bending_moment") == pytest.approx(P * a * b / L)


def test_input_units_are_converted_and_material_fills_the_modulus():
    in_si = run_calculator("beam", {"support": "cantilever", "length": 2.0, "point_load": 1000.0, "section": "rectangle",
                                    "width": 0.05, "height": 0.1}, material="s355")
    in_units = run_calculator("beam", {"support": "cantilever", "length": "2000 mm", "point_load": "1 kN",
                                       "section": "rectangle", "width": {"value": 5, "unit": "cm"}, "height": "100 mm"},
                              material="S355")
    assert _r(in_units, "max_deflection") == pytest.approx(_r(in_si, "max_deflection"), rel=1e-12)
    modulus = next(i for i in in_units["inputs"] if i["name"] == "elastic_modulus")
    assert modulus["value"] == 210e9 and modulus["source"] == "material s355"
    assert any("not design allowables" in w for w in in_units["warnings"])
    deflection = next(r for r in in_units["results"] if r["name"] == "max_deflection")
    assert deflection["display_unit"] == "mm" and deflection["display_value"] == pytest.approx(3.047619, rel=1e-6)


def test_wrong_dimensions_and_unknown_inputs_are_rejected():
    with pytest.raises(ValueError, match="dimensions"):
        run_calculator("beam", {"length": "2 kg", "point_load": 1, "elastic_modulus": E, "second_moment_of_area": 1e-6})
    with pytest.raises(ValueError, match="Unknown input"):
        run_calculator("beam", {"length": 2, "span_mass": 3})
    with pytest.raises(ValueError, match="needs input"):
        run_calculator("beam", {"length": 2, "point_load": 1})


def test_an_unknown_calculator_returns_an_error():
    from tribos.extensions.engcalc import execute_engineering_calc

    with pytest.raises(ValueError, match="Unknown calculator"):
        run_calculator("flux_capacitor", {})
    res = execute_engineering_calc("flux_capacitor", {})
    assert not res.success and "Unknown calculator" in res.error


def test_beam_validity_warnings_fire_for_a_deep_beam():
    result = run_calculator("beam", {"length": 0.5, "point_load": 1e3, "section": "rectangle", "width": 0.1,
                                     "height": 0.2}, material="s235")
    assert any("Timoshenko" in w for w in result["warnings"])


# -- Columns ------------------------------------------------------------------------------------------------------


def test_euler_and_johnson_regimes():
    long = run_calculator("column_buckling", {"length": 3.0, "section": "circle", "diameter": 0.05, "axial_load": 5e4},
                          material="s355")
    inertia = math.pi * 0.05**4 / 64
    assert _r(long, "critical_load") == pytest.approx(math.pi**2 * 210e9 * inertia / 3.0**2, rel=1e-12)
    assert "Euler" in long["results"][0]["label"]
    assert long["utilisation"]["governing"] == "buckling" and not long["utilisation"]["ok"]  # n = 1.41 < 2

    short = run_calculator("column_buckling", {"length": 0.5, "section": "circle", "diameter": 0.05}, material="s355")
    sy, slender = 355e6, 0.5 / 0.0125
    assert _r(short, "critical_stress") == pytest.approx(sy - (sy * slender / (2 * math.pi)) ** 2 / 210e9, rel=1e-12)
    assert "Johnson" in short["results"][0]["label"]


def test_end_conditions_scale_the_effective_length():
    pinned = run_calculator("column_buckling", {"length": 3, "section": "circle", "diameter": 0.05}, material="s355")
    free = run_calculator("column_buckling", {"length": 3, "section": "circle", "diameter": 0.05,
                                              "end_condition": "fixed_free"}, material="s355")
    assert _r(free, "critical_load") == pytest.approx(_r(pinned, "critical_load") / 4, rel=1e-12)


# -- Pressure vessel, shaft, bolt ---------------------------------------------------------------------------------


def test_pressure_vessel_ug27_and_membrane_stresses():
    result = run_calculator("pressure_vessel", {"pressure": "2 MPa", "inner_diameter": "1 m", "thickness": "12 mm",
                                                "allowable_stress": "138 MPa", "joint_efficiency": 0.85})
    assert _r(result, "thickness_circumferential") == pytest.approx(2e6 * 0.5 / (138e6 * 0.85 - 0.6 * 2e6))
    assert _r(result, "thickness_longitudinal") == pytest.approx(2e6 * 0.5 / (2 * 138e6 * 0.85 + 0.4 * 2e6))
    assert _r(result, "hoop_stress") == pytest.approx(2e6 * (1.0 + 0.012) / (2 * 0.012))
    assert _r(result, "longitudinal_stress") == pytest.approx(2e6 * 1.0 / (4 * 0.012))
    assert "UG-27" in result["reference"]["section"]


def test_a_thick_wall_fires_the_thin_wall_validity_warning():
    result = run_calculator("pressure_vessel", {"pressure": "30 MPa", "inner_diameter": "100 mm", "thickness": "20 mm"},
                            material="ss316")
    assert any("thin-wall" in w for w in result["warnings"])
    assert any("ASME Section II" in w for w in result["warnings"])  # no allowable stress, so no code thickness


def test_shaft_torsion_and_von_mises():
    d, T, M = 0.04, 500.0, 300.0
    result = run_calculator("shaft", {"diameter": d, "torque": T, "bending_moment": M, "length": 1.0}, material="s355")
    tau = 16 * T / (math.pi * d**3)
    sigma = 32 * M / (math.pi * d**3)
    assert _r(result, "shear_stress") == pytest.approx(tau)
    assert _r(result, "von_mises_stress") == pytest.approx(math.sqrt(sigma**2 + 3 * tau**2))
    G = 210e9 / (2 * 1.3)
    assert _r(result, "angle_of_twist") == pytest.approx(T * 1.0 / (G * math.pi * d**4 / 32))


def test_bolt_m12_preload_and_torque():
    result = run_calculator("bolt_preload", {"diameter": "12 mm", "property_class": "8.8"})
    at = math.pi / 4 * (12 - 0.938194 * 1.75) ** 2 * 1e-6
    assert _r(result, "tensile_stress_area") == pytest.approx(at)
    assert _r(result, "tensile_stress_area") * 1e6 == pytest.approx(84.3, abs=0.05)  # ISO 898-1 table value
    assert _r(result, "preload") == pytest.approx(0.75 * at * 580e6)
    assert _r(result, "tightening_torque") == pytest.approx(0.2 * 0.75 * at * 580e6 * 0.012)
    loaded = run_calculator("bolt_preload", {"diameter": "12 mm", "external_load": "10 kN", "joint_constant": 0.25})
    fi = 0.75 * at * 580e6
    assert _r(loaded, "separation_factor") == pytest.approx(fi / (1e4 * 0.75))


# -- Fatigue ------------------------------------------------------------------------------------------------------


def test_fatigue_criteria_match_shigley():
    sut, sy, se = 600e6, 400e6, 250e6
    base = {"stress_amplitude": 100e6, "mean_stress": 150e6, "ultimate_strength": sut, "yield_strength": sy,
            "endurance_limit": se}
    goodman = run_calculator("fatigue", {**base, "criterion": "goodman"})
    soderberg = run_calculator("fatigue", {**base, "criterion": "soderberg"})
    gerber = run_calculator("fatigue", {**base, "criterion": "gerber"})
    assert _r(goodman, "fatigue_safety_factor") == pytest.approx(1 / (100 / 250 + 150 / 600))
    assert _r(soderberg, "fatigue_safety_factor") == pytest.approx(1 / (100 / 250 + 150 / 400))
    n_gerber = 0.5 * (600 / 150) ** 2 * (100 / 250) * (-1 + math.sqrt(1 + (2 * 150 * 250 / (600 * 100)) ** 2))
    assert _r(gerber, "fatigue_safety_factor") == pytest.approx(n_gerber)
    assert _r(soderberg, "fatigue_safety_factor") < _r(goodman, "fatigue_safety_factor") < _r(gerber, "fatigue_safety_factor")


def test_basquin_life_and_miner_damage():
    sut, se, f = 600e6, 300e6, 0.9
    a = (f * sut) ** 2 / se
    b = -math.log10(f * sut / se) / 3
    result = run_calculator("fatigue", {
        "stress_amplitude": 400e6, "ultimate_strength": sut, "yield_strength": 450e6, "endurance_limit": se,
        "load_blocks": [{"stress_amplitude": "400 MPa", "cycles": 1e4}, {"stress_amplitude": "200 MPa", "cycles": 1e7}],
    })
    life = (400e6 / a) ** (1 / b)
    assert _r(result, "cycles_to_failure") == pytest.approx(life)
    assert _r(result, "miner_damage") == pytest.approx(1e4 / life)  # the 200 MPa block is below S_e
    # The S-N line passes through f S_ut at 10^3 cycles and S_e at 10^6 cycles.
    assert a * 1e3**b == pytest.approx(f * sut) and a * 1e6**b == pytest.approx(se)


def test_aluminium_without_an_endurance_limit_is_refused():
    with pytest.raises(ValueError, match="no endurance limit"):
        run_calculator("fatigue", {"stress_amplitude": "80 MPa"}, material="al6061_t6")


# -- Thermo-fluids ------------------------------------------------------------------------------------------------


def test_pipe_pressure_drop_with_colebrook():
    result = run_calculator("pipe_pressure_drop", {"diameter": "100 mm", "length": "100 m", "flow_rate": "10 L/s"})
    re = _r(result, "reynolds_number")
    f = _r(result, "friction_factor")
    rr = 4.5e-5 / 0.1
    assert 1 / math.sqrt(f) == pytest.approx(-2 * math.log10(rr / 3.7 + 2.51 / (re * math.sqrt(f))), rel=1e-10)
    assert f == pytest.approx(0.0195, abs=3e-4)  # the Moody chart at Re = 1.27e5, eps/D = 4.5e-4
    v = 0.01 / (math.pi * 0.1**2 / 4)
    assert _r(result, "pressure_drop") == pytest.approx(f * 1000 * 998.2 * v**2 / 2)
    laminar = run_calculator("pipe_pressure_drop", {"diameter": 0.01, "length": 1, "velocity": 0.1})
    assert _r(laminar, "friction_factor") == pytest.approx(64 / _r(laminar, "reynolds_number"))


def test_heat_exchanger_lmtd_and_ntu_agree():
    lmtd = run_calculator("heat_exchanger", {"hot_inlet": "150 degC", "hot_outlet": "100 degC", "cold_inlet": "20 degC",
                                             "cold_outlet": "80 degC", "hot_capacity_rate": 2000, "cold_capacity_rate":
                                             2000 * 50 / 60, "overall_coefficient": 500})
    assert _r(lmtd, "lmtd") == pytest.approx(10 / math.log(80 / 70))
    area = _r(lmtd, "required_area")
    ntu = run_calculator("heat_exchanger", {"method": "ntu", "hot_inlet": 150, "cold_inlet": 20, "hot_capacity_rate": 2000,
                                            "cold_capacity_rate": 2000 * 50 / 60, "overall_coefficient": 500, "area": area})
    assert _r(ntu, "heat_duty") == pytest.approx(100e3, rel=1e-9)
    assert _r(ntu, "hot_outlet") == pytest.approx(100.0, rel=1e-9)
    with pytest.raises(ValueError, match="cross"):
        run_calculator("heat_exchanger", {"flow_arrangement": "parallel", "hot_inlet": 150, "hot_outlet": 60,
                                          "cold_inlet": 20, "cold_outlet": 80, "hot_capacity_rate": 1000})


def test_layered_wall_resistances_in_series():
    result = run_calculator("layered_wall", {
        "layers": [{"thickness": "200 mm", "material": "concrete"}, {"thickness": "10 cm", "conductivity": 0.04}],
        "temperature_inside": "20 degC", "temperature_outside": "-5 degC", "h_inside": 8, "h_outside": 25,
    })
    total = 1 / 8 + 0.2 / 1.7 + 0.1 / 0.04 + 1 / 25
    assert _r(result, "total_resistance") == pytest.approx(total)
    assert _r(result, "heat_flux") == pytest.approx(25 / total)
    assert _r(result, "temperature_after_inside_film") == pytest.approx(20 - 25 / total / 8)


# -- Uncertainty, catalog, tool and planner -----------------------------------------------------------------------


def test_input_uncertainties_flow_to_the_results():
    result = run_calculator("beam", {"support": "cantilever", "length": {"value": 2, "unit": "m", "uncertainty": 0.01},
                                     "point_load": {"value": 1, "unit": "kN", "uncertainty": 0.02},
                                     "section": "rectangle", "width": 0.05, "height": 0.1}, material="s355")
    u = next(r for r in result["results"] if r["name"] == "max_deflection")["uncertainty"]
    # delta = P L^3 / (3 E I): the relative uncertainties add in quadrature, the length's tripled.
    rel = math.sqrt(0.02**2 + (3 * 0.005) ** 2)
    assert u["standard_uncertainty"] / _r(result, "max_deflection") == pytest.approx(rel, rel=1e-5)
    assert u["formatted"] == "(3.05 ± 0.15) mm"
    assert u["budget"][0]["variable"] == "point_load" and u["budget"][0]["percentage"] == pytest.approx(64, abs=0.1)


def test_every_calculator_is_listed_with_a_reference():
    catalog = list_calculators()
    ids = {c["id"] for c in catalog["calculators"]}
    assert ids == {"beam", "column_buckling", "pressure_vessel", "shaft", "bolt_preload", "fatigue",
                   "pipe_pressure_drop", "heat_exchanger", "layered_wall"}
    assert all(c["reference"]["source"] and c["reference"]["section"] for c in catalog["calculators"])
    assert len(catalog["materials"]) == 11 and "not design allowables" in catalog["materials_note"]


def test_the_evidence_and_the_card_artifact():
    from tribos.agentic.evidence import render_result
    from tribos.extensions.engcalc import _engineering_artifact, execute_engineering_calc

    res = execute_engineering_calc("shaft", {"diameter": "40 mm", "torque": "500 N*m"}, "s355")
    xml = render_result("agent.plan.2.physis", res, {"phase": "plan", "purpose": "shaft"})
    assert '<engineering_calc tool="physis_engineering_calc" calculator="shaft"' in xml
    assert "<utilisation governing=" in xml and "Shigley" in xml
    card = _engineering_artifact({"a": res, "b": res}, None)["engineering_calc"]
    assert len(card["calculations"]) == 2


@pytest.mark.parametrize(
    "question",
    [
        "What is the tip deflection of a steel cantilever beam 2 m long with a 1 kN end load?",
        "Will a 3 m pinned S355 column of 50 mm diameter buckle under 50 kN?",
        "Required wall thickness of a pressure vessel at 2 MPa, 1 m diameter, per ASME",
        "Tightening torque and preload for an M12 8.8 bolt",
        "Goodman fatigue safety factor for 150 MPa alternating and 100 MPa mean stress",
        "Pressure drop of water through 100 m of 100 mm steel pipe at 10 L/s",
    ],
)
def test_the_planner_retrieves_the_calculator(question):
    from tribos.agentic.tool_retrieval import retrieve_tools
    from tribos.tools.registry import get_tool_registry

    names = [e.name for e in retrieve_tools(get_tool_registry(), question, k=3)]
    assert "physis_engineering_calc" in names, names
