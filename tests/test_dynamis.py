"""Comprehensive offline unit tests for the Dynamis numerical simulation and optimization package."""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from tribos.dynamis import (
    ODE_PRESETS,
    DynamisEngine,
    dynamis_equilibrium,
    dynamis_fit_parameters,
    dynamis_optimize,
    dynamis_parameter_scan,
    dynamis_root_find,
    dynamis_simulate_ode,
)
from tribos.extensions import dynamis as dynamis_ext
from tribos.tools.registry import ToolRegistry


def test_dynamis_simulate_ode_custom_and_presets():
    # Exponential decay dx/dt = -k*x, x(0) = 10, k = 0.5 at t = 2 -> 10 * exp(-1)
    sim = dynamis_simulate_ode(
        rhs={"x": "-k * x"},
        initial_state={"x": 10.0},
        t_span=(0.0, 2.0),
        parameters={"k": 0.5},
        num_points=50,
    )
    assert sim["verified"] is True
    assert sim["summary"]["x"]["initial"] == pytest.approx(10.0)
    assert sim["summary"]["x"]["final"] == pytest.approx(10.0 * math.exp(-1.0), rel=1e-5)
    assert sim["canonical_id"].startswith("comp:dynamis_simulate_ode:")

    # Named preset: harmonic_oscillator conserves total energy
    ho = dynamis_simulate_ode(model_name="harmonic_oscillator", t_span=(0.0, 2.0 * math.pi), num_points=100)
    assert ho["verified"] is True
    assert ho["conserved_check"]["checked"] is True
    assert ho["conserved_check"]["conserved"] is True
    assert ho["summary"]["x"]["final"] == pytest.approx(1.0, abs=1e-4)

    # Named preset: SIR model conserves S + I + R = 1.0
    sir = dynamis_simulate_ode(model_name="sir", t_span=(0.0, 30.0), num_points=60)
    assert sir["conserved_check"]["conserved"] is True
    assert len(ODE_PRESETS) >= 9


def test_dynamis_equilibrium_stability_classifications():
    # 1. Damped oscillator -> stable_spiral at (0, 0)
    eq_spiral = dynamis_equilibrium(
        rhs={"x": "v", "v": "-2 * zeta * omega * v - omega^2 * x"},
        guess={"x": 0.5, "v": -0.2},
        parameters={"omega": 2.0, "zeta": 0.25},
    )
    assert eq_spiral["converged"] is True
    assert eq_spiral["stability"] == "stable_spiral"
    assert eq_spiral["fixed_point"]["x"] == pytest.approx(0.0, abs=1e-9)
    assert eq_spiral["fixed_point"]["v"] == pytest.approx(0.0, abs=1e-9)

    # 2. Saddle point: dx/dt = x, dy/dt = -y
    eq_saddle = dynamis_equilibrium(
        rhs={"x": "x - 1", "y": "-(y - 2)"},
        guess={"x": 0.8, "y": 1.8},
    )
    assert eq_saddle["stability"] == "saddle"
    assert eq_saddle["fixed_point"]["x"] == pytest.approx(1.0, abs=1e-8)
    assert eq_saddle["fixed_point"]["y"] == pytest.approx(2.0, abs=1e-8)

    # 3. Stable node: dx/dt = -x, dy/dt = -2*y
    eq_node = dynamis_equilibrium(
        rhs={"x": "-x", "y": "-2*y"},
        guess={"x": 0.1, "y": 0.1},
    )
    assert eq_node["stability"] == "stable_node"

    # 4. Undamped harmonic oscillator -> center
    eq_center = dynamis_equilibrium(
        rhs={"x": "v", "v": "-4*x"},
        guess={"x": 0.1, "v": 0.1},
    )
    assert eq_center["stability"] == "center"


def test_dynamis_parameter_scan():
    scan = dynamis_parameter_scan(
        rhs={"x": "r - k * x"},
        initial_state={"x": 0.0},
        parameter="r",
        scan_range=(1.0, 5.0),
        num_points=5,
        t_span=(0.0, 20.0),
        base_parameters={"k": 1.0},
    )
    assert scan["verified"] is True
    assert len(scan["scan_results"]) == 5
    finals = [pt["final_state"]["x"] for pt in scan["scan_results"]]
    assert finals == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0], rel=1e-3)


def test_dynamis_optimize_unconstrained_and_constrained():
    # Unconstrained minimization of (x - 3)^2 + (y + 2)^2 + 5
    opt = dynamis_optimize(
        objective="(x - 3)^2 + (y + 2)^2 + 5",
        variables=["x", "y"],
        initial_guess={"x": 0.0, "y": 0.0},
    )
    assert opt["converged"] is True
    assert opt["optimal_point"]["x"] == pytest.approx(3.0, abs=1e-6)
    assert opt["optimal_point"]["y"] == pytest.approx(-2.0, abs=1e-6)
    assert opt["optimal_value"] == pytest.approx(5.0, abs=1e-6)
    assert opt["gradient_norm"] < 1e-5

    # Constrained minimization: minimize x^2 + y^2 subject to x + y = 4 -> (2, 2), min = 8
    c_opt = dynamis_optimize(
        objective="x^2 + y^2",
        variables=["x", "y"],
        constraints=[{"type": "eq", "expr": "x + y - 4"}],
    )
    assert c_opt["converged"] is True
    assert c_opt["optimal_point"]["x"] == pytest.approx(2.0, abs=1e-5)
    assert c_opt["optimal_point"]["y"] == pytest.approx(2.0, abs=1e-5)
    assert c_opt["optimal_value"] == pytest.approx(8.0, abs=1e-5)

    # Maximization: maximize -(x - 1)^2 + 10 -> x = 1, max = 10
    max_opt = dynamis_optimize(
        objective="-(x - 1)^2 + 10",
        variables=["x"],
        minimize=False,
    )
    assert max_opt["converged"] is True
    assert max_opt["optimal_point"]["x"] == pytest.approx(1.0, abs=1e-6)
    assert max_opt["optimal_value"] == pytest.approx(10.0, abs=1e-6)


def test_dynamis_fit_parameters():
    t_vals = np.linspace(0.0, 4.0, 25)
    y_vals = 3.5 * np.exp(-0.8 * t_vals) + 1.2
    fit = dynamis_fit_parameters(
        model_expr="a * exp(-b * t) + c",
        independent_var="t",
        param_names=["a", "b", "c"],
        x_data=t_vals.tolist(),
        y_data=y_vals.tolist(),
        initial_guess={"a": 2.0, "b": 0.5, "c": 0.5},
    )
    assert fit["converged"] is True
    assert fit["parameters"]["a"] == pytest.approx(3.5, rel=1e-5)
    assert fit["parameters"]["b"] == pytest.approx(0.8, rel=1e-5)
    assert fit["parameters"]["c"] == pytest.approx(1.2, rel=1e-5)
    assert fit["rmse"] < 1e-7
    assert fit["r_squared"] == pytest.approx(1.0, abs=1e-9)


def test_dynamis_root_find_and_registry():
    rf = dynamis_root_find(
        equations=["x^2 + y^2 = 25", "x - y = 1"],
        initial_guess={"x": 3.5, "y": 2.5},
    )
    assert rf["converged"] is True
    assert rf["verified"] is True
    assert rf["roots"]["x"] == pytest.approx(4.0, abs=1e-8)
    assert rf["roots"]["y"] == pytest.approx(3.0, abs=1e-8)
    assert rf["residual_norm"] < 1e-9
    assert DynamisEngine.root_find("x^3 - 8 = 0", {"x": 1.5})["roots"]["x"] == pytest.approx(2.0, abs=1e-8)

    reg = ToolRegistry()
    dynamis_ext.register_tools(reg)
    names = {t.name for t in reg.list_tools(domain="dynamis")}
    assert names == {
        "dynamis_monte_carlo_integrate",
        "dynamis_simulate_ode",
        "dynamis_equilibrium",
        "dynamis_parameter_scan",
        "dynamis_optimize",
        "dynamis_fit_parameters",
        "dynamis_root_find",
    }

    res = asyncio.run(
        reg.execute(
            "dynamis_root_find",
            {
                "equations": "cos(x) - x = 0",
                "initial_guess": {"x": 0.7},
            },
        )
    )
    assert res.success, res.error
    assert res.data["roots"]["x"] == pytest.approx(0.7390851332, abs=1e-6)
    assert res.canonical_ids["computation_id"].startswith("comp:dynamis_root_find:")
