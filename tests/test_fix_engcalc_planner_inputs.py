"""The engineering calculator accepts the input names model planners actually send (live runs failed on load_type with
the magnitude under "load", beam_type, a lower-case e and unit-suffixed names) and tells the planner how to retry."""

from __future__ import annotations

import pytest

from tribos.extensions.engcalc import execute_engineering_calc as run

# A simply supported steel beam (E = 200 GPa), 4 m span, 12 kN at midspan, 60 x 120 mm rectangle:
# I = 0.06 * 0.12^3 / 12 = 8.64e-6 m^4, deflection = P L^3 / (48 E I) = 9.259 mm, stress = M c / I = 83.33 MPa.
BEAM_VARIANTS = [
    {"support": "simply_supported", "load": "point", "length": "4 m", "point_load": "12 kN", "elastic_modulus": "200 GPa",
     "section": "rectangle", "width": "60 mm", "height": "120 mm"},
    {"beam_type": "simply_supported", "load_type": "point_load", "load": "12 kN", "span": "4 m", "e": "200 GPa",
     "width": "60 mm", "depth": "120 mm"},
    {"support": "simply supported", "load_case": "point load at midspan", "P_kN": 12, "span_m": 4, "E_GPa": 200,
     "b_mm": 60, "h_mm": 120},
    {"beam_type": "simply supported", "load": "12 kN", "L": 4, "E": 200e9, "b": 0.06, "h": 0.12},
]


def _results(r) -> dict[str, float]:
    assert r.success, r.error
    return {x["name"]: x.get("display_value") or x["value"] for x in r.data["results"]}


@pytest.mark.parametrize("inputs", BEAM_VARIANTS)
def test_the_demo_beam_in_planner_style_inputs(inputs):
    out = _results(run("beam", inputs))
    assert out["max_deflection"] == pytest.approx(9.2593, rel=1e-3)  # mm
    assert out["max_bending_stress"] == pytest.approx(83.333, rel=1e-3)  # MPa


def test_a_distributed_load_magnitude_sent_as_load_is_the_distributed_load():
    out = _results(run("beam", {"load": "5 kN/m", "load_type": "udl", "support": "cantilever", "L": "2 m",
                                "E": "70 GPa", "b": "40 mm", "h": "80 mm"}))
    assert out["max_deflection"] == pytest.approx(83.705, rel=1e-3)  # w L^4 / (8 E I), mm
    assert out["max_bending_moment"] == pytest.approx(10.0, rel=1e-3)  # w L^2 / 2, kN m


def test_a_pressure_vessel_with_unit_suffixed_names():
    out = _results(run("pressure_vessel", {"p_bar": 10, "diameter_mm": 500, "t_mm": 6, "yield_strength": "250 MPa"}))
    assert out["hoop_stress"] == pytest.approx(42.17, rel=2e-3)  # p (D + t) / (2 t) with D the inner diameter, MPa


def test_pipe_flow_with_a_compound_unit_in_the_name():
    out = _results(run("pipe_pressure_drop", {"flow_rate_m3_per_s": 0.01, "diameter_mm": 50, "length_m": 100}))
    assert out["velocity"] == pytest.approx(5.093, rel=1e-3)  # Q / (pi D^2 / 4), m/s


def test_an_unknown_input_gets_an_error_the_planner_can_act_on():
    r = run("beam", {"bogus_input": 3, "L": "4 m"})
    assert not r.success
    assert "bogus_input" in r.error and "Retry with these exact names" in r.error and '"support"' in r.error


def test_a_name_that_only_looks_like_a_unit_suffix_is_still_unknown():
    r = run("beam", {"span_furlongs_xyz": 4})
    assert not r.success and "span_furlongs_xyz" in r.error
