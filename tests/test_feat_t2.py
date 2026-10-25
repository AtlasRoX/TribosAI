"""T2: the Dynamis PDE solver, verified against analytic solutions, conservation laws and its own mesh study."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tribos.dynamis.pde import StabilityError, solve_pde
from tribos.dynamis.pde.expressions import ExpressionError


def _final(result: dict) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(result["x"], dtype=float), np.asarray(result["field"], dtype=float)


# -- Heat ---------------------------------------------------------------------------------------------------------


def test_heat_1d_matches_the_analytic_solution_with_second_order_convergence():
    # u_t = alpha u_xx on [0, 1], u = 0 at both ends, u(x, 0) = sin(pi x): u = exp(-alpha pi^2 t) sin(pi x).
    result = solve_pde(
        "heat", parameters={"alpha": 0.01}, initial_condition="sin(pi*x)", t_span=(0.0, 0.5), num_points=101,
        exact_solution="exp(-alpha*pi^2*t)*sin(pi*x)",
    )
    x, u = _final(result)
    assert np.max(np.abs(u - math.exp(-0.01 * math.pi**2 * 0.5) * np.sin(math.pi * x))) < 1e-4
    convergence = result["convergence"]
    assert len(convergence["levels"]) == 3
    assert [row["n"] for row in convergence["levels"]] == [101, 201, 401]
    assert convergence["order"] == pytest.approx(2.0, abs=0.3)
    assert convergence["converged"] is True
    assert convergence["reference"] == "analytic solution"
    assert result["verification"]["agrees"] is True
    assert result["stability"]["status"] == "unconditionally stable"


def test_heat_explicit_scheme_and_self_convergence_without_an_analytic_solution():
    result = solve_pde("heat", parameters={"alpha": 0.1}, initial_condition="x*(1-x)", t_span=(0, 0.5),
                       num_points=51, method="explicit")
    stability = result["stability"]
    assert stability["scheme"] == "explicit Euler"
    assert stability["number"] <= stability["limit"] == 0.5
    convergence = result["convergence"]
    assert convergence["reference"] == "next finer grid"
    assert convergence["order"] == pytest.approx(2.0, abs=0.3)
    # The Richardson estimate of the error is small and positive, and the result says it is not an analytic check.
    assert 0 < convergence["richardson_error"] < 1e-3
    assert result["verification"] is None


def test_heat_2d_matches_the_separable_solution():
    result = solve_pde(
        "heat", domain=[[0, 1], [0, 1]], parameters={"alpha": 0.1}, initial_condition="sin(pi*x)*sin(pi*y)",
        t_span=(0, 0.2), num_points=41, exact_solution="exp(-2*alpha*pi^2*t)*sin(pi*x)*sin(pi*y)",
    )
    assert result["dimension"] == 2
    assert np.asarray(result["field"]).shape == (41, 41)
    assert result["verification"]["relative_error"] < 1e-3
    assert result["convergence"]["converged"]


def test_neumann_flux_heats_a_bar_at_the_rate_the_flux_supplies():
    # An outward derivative du/dn = 1 on both ends of [0, 1] injects heat at rate alpha * 2: the mean of u grows as 2 t.
    result = solve_pde("heat", initial_condition="0", boundary="neumann", boundary_values={"x0": 1, "x1": 1},
                       t_span=(0, 0.1), num_points=51)
    x, u = _final(result)
    mean = float(np.sum((u[1:] + u[:-1]) * np.diff(x)) / 2)
    assert mean == pytest.approx(0.2, rel=1e-6)


# -- Wave ---------------------------------------------------------------------------------------------------------


def test_wave_1d_matches_d_alemberts_solution_and_conserves_energy():
    # Periodic: u = (f(x - ct) + f(x + ct)) / 2 for u(x, 0) = f and u_t(x, 0) = 0 (d'Alembert).
    result = solve_pde(
        "wave", parameters={"c": 1.0}, initial_condition="sin(2*pi*x)", boundary="periodic", t_span=(0, 0.3),
        num_points=200, exact_solution="(sin(2*pi*(x - c*t)) + sin(2*pi*(x + c*t)))/2",
    )
    assert result["verification"]["max_error"] < 1e-3
    assert result["convergence"]["order"] == pytest.approx(2.0, abs=0.3)
    energy = result["conservation"]
    assert energy["kind"] == "energy" and energy["conserved"] and energy["relative_drift"] < 1e-10


def test_wave_with_fixed_ends_is_the_standing_wave():
    result = solve_pde("wave", parameters={"c": 0.5}, initial_condition="sin(pi*x)", t_span=(0, 0.3), num_points=101,
                       exact_solution="sin(pi*x)*cos(pi*c*t)")
    assert result["verification"]["max_error"] < 1e-4
    assert result["conservation"]["conserved"]


def test_wave_2d_square_membrane():
    result = solve_pde("wave", domain=[[0, 1], [0, 1]], initial_condition="sin(pi*x)*sin(pi*y)", t_span=(0, 0.5),
                       num_points=41, exact_solution="sin(pi*x)*sin(pi*y)*cos(sqrt(2)*pi*t)")
    assert result["verification"]["relative_error"] < 1e-3
    assert result["convergence"]["order"] == pytest.approx(2.0, abs=0.3)


# -- Stability ----------------------------------------------------------------------------------------------------


def test_a_cfl_violation_is_refused_when_asked():
    with pytest.raises(StabilityError, match="CFL"):
        solve_pde("wave", parameters={"c": 5}, initial_condition="sin(pi*x)", num_points=51, dt=0.05,
                  on_unstable="refuse")


def test_a_cfl_violation_is_adapted_by_default_and_reported():
    result = solve_pde("wave", parameters={"c": 5}, initial_condition="sin(pi*x)", num_points=51, dt=0.05,
                       t_span=(0, 1), exact_solution="sin(pi*x)*cos(pi*c*t)")
    stability = result["stability"]
    assert stability["status"] == "adapted"
    assert stability["requested_dt"] == 0.05 and stability["dt"] < 0.004
    assert stability["number"] <= stability["limit"]
    assert any("reduced" in w for w in result["warnings"])
    assert result["verification"]["agrees"]


def test_an_unstable_explicit_heat_step_is_refused():
    with pytest.raises(StabilityError):
        solve_pde("heat", initial_condition="sin(pi*x)", num_points=101, method="explicit", dt=0.01,
                  on_unstable="refuse")


# -- Poisson ------------------------------------------------------------------------------------------------------


def test_poisson_2d_manufactured_solution():
    # u = sin(pi x) sin(pi y) solves -Laplacian(u) = 2 pi^2 sin(pi x) sin(pi y) with u = 0 on the boundary.
    result = solve_pde("poisson", domain=[[0, 1], [0, 1]], source="2*pi^2*sin(pi*x)*sin(pi*y)", num_points=41,
                       exact_solution="sin(pi*x)*sin(pi*y)")
    assert result["steady"] is True
    assert result["verification"]["max_error"] < 1e-3
    # The study refines to 81 and is capped at 6400 points in 2D, so it coarsens instead: 11, 21, 41.
    assert [row["n"] for row in result["convergence"]["levels"]] == [11, 21, 41]
    assert result["convergence"]["order"] == pytest.approx(2.0, abs=0.2)


def test_laplace_with_harmonic_boundary_data_is_exact_to_round_off():
    result = solve_pde(
        "poisson", domain=[[0, 1], [0, 2]], num_points=41, exact_solution="x^2 - y^2",
        boundary_values={"x0": "-y^2", "x1": "1 - y^2", "y0": "x^2", "y1": "x^2 - 4"},
    )
    assert result["verification"]["max_error"] < 1e-9
    assert result["convergence"]["converged"] and result["convergence"]["order"] is None
    assert "round-off" in result["convergence"]["note"]


def test_pure_neumann_poisson_needs_compatible_data():
    with pytest.raises(ValueError, match="compatible"):
        solve_pde("poisson", source="1", boundary="neumann", num_points=41)
    result = solve_pde("poisson", source="cos(pi*x)*pi^2", boundary="neumann", num_points=81,
                       exact_solution="cos(pi*x)")
    assert result["verification"]["max_error"] < 1e-3


# -- Conservation and the other equations -------------------------------------------------------------------------


def test_periodic_diffusion_conserves_mass():
    result = solve_pde("heat", parameters={"alpha": 0.05}, initial_condition="1 + sin(2*pi*x) + 0.5*cos(4*pi*x)",
                       boundary="periodic", t_span=(0, 0.5), num_points=100)
    mass = result["conservation"]
    assert mass["kind"] == "mass" and mass["conserved"] and mass["relative_drift"] < 1e-12
    assert mass["initial"] == pytest.approx(1.0)


def test_advection_diffusion_travels_and_decays():
    result = solve_pde("advection_diffusion", parameters={"v": 0.5, "D": 0.01}, initial_condition="sin(2*pi*x)",
                       boundary="periodic", t_span=(0, 0.5), num_points=100,
                       exact_solution="exp(-4*pi^2*D*t)*sin(2*pi*(x - v*t))")
    assert result["verification"]["relative_error"] < 5e-3
    assert result["conservation"]["conserved"]


def test_advection_dominated_flow_switches_to_upwind_and_says_so():
    result = solve_pde("advection_diffusion", parameters={"v": 1.0, "D": 1e-4}, initial_condition="sin(2*pi*x)",
                       boundary="periodic", t_span=(0, 0.2), num_points=100)
    assert "upwind" in result["stability"]["scheme"]
    assert result["convergence"]["expected_order"] == 1
    assert any("Peclet" in w for w in result["warnings"])


def test_fisher_kpp_front_stays_between_zero_and_one():
    result = solve_pde("fisher_kpp", parameters={"r": 1.0, "D": 0.001}, initial_condition="exp(-200*x^2)",
                       boundary="neumann", t_span=(0, 5), num_points=201)
    values = np.asarray([s["values"] for s in result["snapshots"]])
    assert values.min() > -1e-6 and values.max() < 1 + 1e-6
    assert "BDF" in result["stability"]["scheme"]
    assert result["convergence"]["converged"]


def test_burgers_conserves_mass_on_a_periodic_domain():
    result = solve_pde("burgers", parameters={"nu": 0.05}, initial_condition="0.5 + 0.2*sin(2*pi*x)",
                       boundary="periodic", t_span=(0, 0.3), num_points=100)
    assert result["conservation"]["conserved"]
    assert result["convergence"]["order"] == pytest.approx(2.0, abs=0.3)


def test_an_unresolved_shock_is_reported_as_unverified():
    result = solve_pde("burgers", parameters={"nu": 0.001}, initial_condition="sin(2*pi*x)", boundary="periodic",
                       t_span=(0, 0.3), num_points=200)
    assert result["convergence"]["converged"] is False
    assert any("unverified" in w for w in result["warnings"])


# -- Input safety and caps ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("expression", ["__import__('os').system('ls')", "x.__class__", "open('f')", "lambda: 1"])
def test_an_unsafe_expression_is_rejected(expression):
    with pytest.raises(ExpressionError):
        solve_pde("heat", initial_condition=expression, num_points=21)


def test_unknown_symbols_and_bad_inputs_are_rejected():
    with pytest.raises(ExpressionError, match="unknown symbol"):
        solve_pde("heat", initial_condition="sin(k*x)", num_points=21)
    with pytest.raises(ValueError, match="teleportation"):
        solve_pde("teleportation", initial_condition="0")
    with pytest.raises(ValueError, match="1D"):
        solve_pde("burgers", domain=[[0, 1], [0, 1]], initial_condition="0")
    with pytest.raises(ValueError, match="periodic"):
        solve_pde("heat", initial_condition="0", boundary={"x0": "periodic", "x1": "dirichlet"})
    with pytest.raises(ValueError, match="initial condition"):
        solve_pde("heat")


def test_the_grid_cap_is_enforced(monkeypatch):
    with pytest.raises(ValueError, match="cap"):
        solve_pde("heat", domain=[[0, 1], [0, 1]], initial_condition="0", num_points=200)
    monkeypatch.setenv("TRIBOS_PDE_MAX_GRID_1D", "500")
    with pytest.raises(ValueError, match="cap"):
        solve_pde("heat", initial_condition="0", num_points=501)


def test_the_wall_time_cap_stops_a_long_run(monkeypatch):
    from types import SimpleNamespace

    from tribos.dynamis.pde import solvers

    # The solver's clock jumps past every deadline, as a run that takes too long would.
    monkeypatch.setattr(solvers, "time", SimpleNamespace(monotonic=lambda: math.inf))
    with pytest.raises(solvers.ConvergenceError, match="time limit"):
        solve_pde("heat", initial_condition="sin(pi*x)", num_points=101, method="explicit")


# -- Output -------------------------------------------------------------------------------------------------------


def test_output_is_capped_and_carries_probes_and_the_spec():
    result = solve_pde("heat", parameters={"alpha": 0.01}, initial_condition="sin(pi*x)", t_span=(0, 0.2),
                       num_points=2001, num_times=100, probe_at=[0.5])
    assert len(result["snapshots"]) == 25 and len(result["x"]) <= 401
    assert all(len(s["values"]) == len(result["x"]) for s in result["snapshots"])
    probe = result["probes"][0]
    assert probe["x"] == 0.5 and len(probe["values"]) == 25 and probe["values"][0] == pytest.approx(1.0)
    spec = result["spec"]
    assert spec["equation"] == "heat" and spec["parameters"]["alpha"] == 0.01 and spec["num_points"] == 2001
    assert spec["initial_condition"] == "sin(pi*x)"


def test_2d_output_is_at_most_80_by_80_and_few_frames():
    result = solve_pde("heat", domain=[[0, 1], [0, 1]], initial_condition="sin(pi*x)*sin(pi*y)", num_points=80,
                       num_times=50, probe_at=[[0.5, 0.5]])
    assert np.asarray(result["field"]).shape == (80, 80)
    assert len(result["snapshots"]) <= 11
    assert result["probes"][0]["y"] == pytest.approx(0.5, abs=0.01)


# -- Tool, evidence and planner ----------------------------------------------------------------------------------


def test_the_tool_runs_and_reports_validation_errors():
    from tribos.extensions.pde import execute_pde_tool

    ok = execute_pde_tool(equation="heat", domain=[[0, 1]], initial_condition="sin(pi*x)", num_points=41)
    assert ok.success and ok.data["status"] == "ok" and ok.metadata["converged"] is True
    bad = execute_pde_tool(equation="heat", initial_condition="__import__('os')")
    assert not bad.success and "parse" in bad.error.lower()


def test_the_evidence_renderer_shows_the_verification():
    from tribos.agentic.evidence import render_result
    from tribos.extensions.pde import execute_pde_tool

    res = execute_pde_tool(equation="heat", initial_condition="sin(pi*x)", num_points=41,
                           exact_solution="exp(-pi^2*t)*sin(pi*x)", t_span=[0, 0.1])
    xml = render_result("agent.plan.1.dynamis", res, {"phase": "plan", "purpose": "solve"})
    assert "<dynamis_pde" in xml and "<convergence observed_order=" in xml and "<analytic_comparison" in xml
    assert "<data>" not in xml
    assert len(xml) < 6000


def test_the_result_card_artifact_is_built():
    from tribos.extensions.pde import _pde_artifact, execute_pde_tool

    res = execute_pde_tool(equation="heat", initial_condition="sin(pi*x)", num_points=21)
    assert _pde_artifact({"agent.plan.1.dynamis": res}, None)["pde"]["equation"] == "heat"


@pytest.mark.parametrize(
    "question",
    [
        "Solve the heat equation on [0,1] with u(x,0) = sin(pi x) and zero boundary values",
        "Solve the 1D wave equation with fixed ends and a plucked string initial shape",
        "Solve Poisson's equation on the unit square with a point-like source",
    ],
)
def test_the_planner_retrieves_the_pde_tool(question):
    from tribos.agentic.tool_retrieval import retrieve_tools
    from tribos.tools.registry import get_tool_registry

    names = [e.name for e in retrieve_tools(get_tool_registry(), question, k=3)]
    assert "dynamis_solve_pde" in names, names
