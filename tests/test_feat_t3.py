"""Tests for Physis uncertainty propagation (T3)."""

from __future__ import annotations

import math

from tribos.physis.uncertainty import format_uncertainty_result, propagate_uncertainty


def test_linear_product_and_quotient_quadrature():
    # Product: y = a * b
    vars_prod = {
        "a": {"value": 10.0, "uncertainty": 1.0},   # rel unc = 0.1
        "b": {"value": 20.0, "uncertainty": 1.0},   # rel unc = 0.05
    }
    res_prod = propagate_uncertainty("a * b", vars_prod, method="linear")
    assert math.isclose(res_prod["nominal_value"], 200.0, rel_tol=1e-5)
    expected_rel_unc = math.sqrt(0.1**2 + 0.05**2)
    expected_std_unc = 200.0 * expected_rel_unc
    assert math.isclose(res_prod["standard_uncertainty"], expected_std_unc, rel_tol=1e-4)

    # Quotient: y = a / b
    res_quot = propagate_uncertainty("a / b", vars_prod, method="linear")
    assert math.isclose(res_quot["nominal_value"], 0.5, rel_tol=1e-5)
    expected_std_unc_q = 0.5 * expected_rel_unc
    assert math.isclose(res_quot["standard_uncertainty"], expected_std_unc_q, rel_tol=1e-4)


def test_monte_carlo_agrees_with_linear_for_linear_function():
    # y = 3*x1 - 2*x2 + 5
    variables = {
        "x1": {"value": 10.0, "uncertainty": 0.5, "distribution": "normal"},
        "x2": {"value": 4.0, "uncertainty": 0.2, "distribution": "normal"},
    }
    res = propagate_uncertainty("3*x1 - 2*x2 + 5", variables, method="both", seed=42, n_samples=50000)
    linear = res["linear"]
    mc = res["monte_carlo"]

    assert math.isclose(linear["nominal_value"], 3 * 10.0 - 2 * 4.0 + 5, rel_tol=1e-5)
    assert math.isclose(linear["nominal_value"], mc["mean"], rel_tol=0.01)
    assert math.isclose(linear["standard_uncertainty"], mc["std"], rel_tol=0.02)
    assert not res["warnings"]  # Linear model, so no nonlinearity warning


def test_nonlinear_case_produces_warning():
    # y = exp(5 * x) with moderate uncertainty causes strong asymmetric curvature
    variables = {
        "x": {"value": 1.0, "uncertainty": 0.25, "distribution": "normal"},
    }
    res = propagate_uncertainty("exp(5 * x)", variables, method="both", seed=42, n_samples=50000)
    assert res["warnings"]
    assert any("nonlinear" in w.lower() for w in res["warnings"])


def test_units_propagate():
    # Distance = speed * time
    variables = {
        "v": {"value": 15.0, "uncertainty": 0.5, "unit": "m/s"},
        "t": {"value": 2.0, "uncertainty": 0.1, "unit": "s"},
    }
    res = propagate_uncertainty("v * t", variables, method="linear")
    assert res["unit"] in ("meter", "m")
    assert math.isclose(res["nominal_value"], 30.0, rel_tol=1e-5)
    assert res["formatted"].endswith("m") or res["formatted"].endswith("meter")


def test_codata_autofill():
    # E = m * c^2 without defining c
    variables = {
        "m": {"value": 2.5e-3, "uncertainty": 1e-5, "unit": "kg"},
    }
    res = propagate_uncertainty("m * c^2", variables, autofill_constants=True, method="linear")
    assert "c" in res["autofilled_constants"]
    assert res["unit"] in ("joule", "J")
    assert math.isclose(res["nominal_value"], 2.5e-3 * (299792458.0**2), rel_tol=1e-5)


def test_format_value_expanded_uncertainty_k2():
    formatted = format_uncertainty_result(12.34567, 0.0341, unit="V", k=2.0)
    # k=2 -> U = 0.0682 -> 2 sig figs -> 0.068. Value rounded to 3 decimals: 12.346
    assert "12.346" in formatted
    assert "0.068" in formatted
    assert "V" in formatted


def test_tool_execution_and_evidence():
    from tribos.extensions.physis import execute_physis_uncertainty
    from tribos.agents.stem_evidence import render_physis

    res = execute_physis_uncertainty(
        expression="a + b",
        variables={"a": {"value": 1.0, "uncertainty": 0.1}, "b": {"value": 2.0, "uncertainty": 0.2}},
        method="linear",
    )
    assert res.success
    xml = render_physis(res)
    joined = "".join(xml)
    assert "physis_propagate_uncertainty" in joined or "uncertainty" in joined
    assert "nominal_value" in joined or "standard_uncertainty" in joined
