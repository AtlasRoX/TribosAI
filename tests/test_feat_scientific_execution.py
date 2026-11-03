"""Executed scientific workflows, with independent numerical oracles and no LLM/network dependencies."""

from __future__ import annotations

import asyncio
import math
import time

import numpy as np
import pytest

from tribos.dynamis.engine import dynamis_simulate_ode
from tribos.dynamis.monte_carlo import monte_carlo_integrate
from tribos.dynamis.pde import solve_pde
from tribos.engcalc import run_calculator
from tribos.scientific.requests import parse_scientific_request

OSCILLATOR = (
    "Simulate the unforced damped oscillator m x'' + c x' + kx = 0 with m = 1 kg, c = 0.4 N·s/m, k = 4 N/m, "
    "x(0) = 0.1 m, and x'(0) = 0. Use classical fourth-order Runge–Kutta with a fixed step of 0.01 s "
    "for exactly 100 steps. Report x and velocity at t = 1 s. Also compute the exact analytical solution "
    "at t = 1 s and report the absolute errors. Do not search the web."
)
HEAT = (
    "Simulate the one-dimensional heat equation ∂T/∂t = α∂²T/∂x² on 0 ≤ x ≤ 1 m, with α = 1×10^-4 m²/s. "
    "Use 11 equally spaced nodes (Δx = 0.1 m), the explicit FTCS method, and Δt = 20 s for exactly 10 steps. "
    "Set the boundary temperatures to T(0,t) = 100°C and T(1,t) = 0°C. Initially set all nine interior nodes "
    "to 0°C; apply the boundary values at every step. Return: 1. The stability parameter and stability. "
    "2. The temperatures at all 11 nodes after 10 steps. 3. A check of boundary values. Do not search the web."
)
MC = (
    "Estimate the integral of exp(-x^2) from x = 0 to 1 using crude Monte Carlo with exactly 100,000 independent "
    "uniform samples. For reproducibility, use NumPy Generator with PCG64 and seed 20261028. Report the estimate, "
    "the sample-based standard error, and the number of standard errors between your estimate and the reference "
    "value 0.746824132812427. Return exactly three numbered items. State the sampling method and seed. Do not search the web."
)
RC = (
    "A 12 V ideal source is connected at t = 0 to a series resistor R = 10 kΩ and capacitor C = 100 μF. "
    "The capacitor is initially uncharged. 1. Calculate the time constant. 2. Calculate capacitor voltage at t = 1 s. "
    "3. Calculate the current at t = 0+ and t = 1 s. 4. Check Kirchhoff's voltage law at t = 1 s. "
    "Return exactly four numbered items with units. Show equations. Do not search the web."
)
BEAM = (
    "A uniform cantilever beam has length L = 1.5 m and a downward point load P = 200 N at its free end. "
    "Its rectangular cross-section has width b = 20 mm and vertical height h = 40 mm. Young's modulus is E = 200 GPa. "
    "Assume linear Euler–Bernoulli beam theory, ignore self-weight and shear deformation, and use I = bh^3/12. "
    "Calculate: 1. The second moment of area. 2. The maximum bending moment. 3. The magnitude of maximum bending stress. "
    "4. The tip deflection and its ratio to beam length. Show unit conversions and units. Return exactly four numbered items. "
    "Do not search the web."
)


def test_rk4_is_the_requested_grid_and_matches_the_closed_form():
    request = parse_scientific_request(OSCILLATOR)
    assert request is not None and not request.errors
    result = dynamis_simulate_ode(**request.args)
    assert result["method"] == "RK4"
    assert (
        result["solver"]["internal_steps"] == 100
        and result["solver"]["function_evaluations"] == 400
    )
    assert len(result["t"]) == 101 and result["t"][-1] == 1.0
    # Independent underdamped-oscillator formula, not the implementation's expm reference.
    omega = math.sqrt(4 - 0.2**2)
    x = 0.1 * math.exp(-0.2) * (math.cos(omega) + 0.2 / omega * math.sin(omega))
    v = -0.1 * math.exp(-0.2) * 4 / omega * math.sin(omega)
    assert abs(result["summary"]["x"]["final"] - x) < 2e-10
    assert abs(result["summary"]["v"]["final"] - v) < 4e-10
    assert result["analytical_reference"]["endpoint"]["x"] == pytest.approx(x, abs=1e-14)
    assert result["trajectories"]["x"][-1] != round(result["trajectories"]["x"][-1], 8)


@pytest.mark.parametrize("rate,end,step", [(1.3, 2.0, 0.02), (0.7, 0.5, 0.005)])
def test_fixed_step_engine_handles_other_systems_and_changed_inputs(rate, end, step):
    out = dynamis_simulate_ode(
        rhs={"z": f"-{rate}*z"},
        initial_state={"z": 2.0},
        t_span=(0, end),
        method="RK4",
        step_size=step,
    )
    assert abs(out["summary"]["z"]["final"] - 2 * math.exp(-rate * end)) < 1e-7
    assert out["solver"]["internal_steps"] == round(end / step)


def test_fixed_grid_conflicts_are_rejected_not_adjusted():
    with pytest.raises(ValueError, match="disagree"):
        dynamis_simulate_ode(
            rhs={"x": "-x"},
            initial_state={"x": 1},
            method="RK4",
            t_span=(0, 1),
            step_size=0.1,
            num_steps=9,
        )
    with pytest.raises(ValueError, match="integer number"):
        dynamis_simulate_ode(
            rhs={"x": "-x"}, initial_state={"x": 1}, method="RK4", t_span=(0, 1), step_size=0.3
        )
    with pytest.raises(ValueError, match="fixed step/count"):
        dynamis_simulate_ode(rhs={"x": "-x"}, initial_state={"x": 1}, step_size=0.1)


def test_ode_physical_givens_are_converted_to_si_before_substitution():
    req = parse_scientific_request(
        OSCILLATOR.replace("m = 1 kg", "m = 1000 g").replace("x(0) = 0.1 m", "x(0) = 100 mm")
    )
    assert req is not None and not req.errors
    result = dynamis_simulate_ode(**req.args)
    assert result["summary"]["x"]["initial"] == pytest.approx(0.1)
    assert result["summary"]["x"]["final"] == pytest.approx(-0.02580702619133871)
    assert result["units"] == {"x": "m", "t": "s", "v": "m/s"}


def test_an_explicit_default_looking_span_does_not_become_a_preset_span():
    out = dynamis_simulate_ode(model_name="damped_oscillator", t_span=(0, 10), num_points=11)
    assert out["t_span"] == [0.0, 10.0]


def test_interactive_rerun_preserves_the_actual_rk4_method_and_step_grid():
    from tribos.dynamis.interactive import simulate

    request = parse_scientific_request(OSCILLATOR)
    assert request is not None
    first = dynamis_simulate_ode(**request.args)
    again = simulate(first["spec"], num_points=400)
    assert again["method"] == "RK4" and again["solver"]["internal_steps"] == 100
    assert again["trajectories"]["x"] == first["trajectories"]["x"]


def test_heat_runs_exactly_ten_ftcs_steps_with_each_boundary_applied():
    request = parse_scientific_request(HEAT)
    assert request is not None and not request.errors
    result = solve_pde(**request.args)
    # Independent vectorised explicit stencil oracle, avoiding the sparse PDE implementation.
    state = np.zeros(11, dtype=np.float64)
    state[0] = 100
    for i in range(10):
        next_state = state.copy()
        next_state[1:-1] = state[1:-1] + 0.2 * (state[:-2] - 2 * state[1:-1] + state[2:])
        state = next_state
        assert result["snapshots"][i + 1]["values"] == pytest.approx(state.tolist(), abs=1e-12)
    assert result["field"] == pytest.approx(state.tolist(), abs=1e-12)
    assert result["stability"]["steps"] == 10 and result["stability"]["dt"] == 20
    assert result["t_span"] == [0, 200]


def test_unstable_requested_heat_step_is_not_silently_changed():
    req = parse_scientific_request(HEAT.replace("Δt = 20", "Δt = 100"))
    assert req is not None
    with pytest.raises(ValueError, match="unstable"):
        solve_pde(**req.args)


def test_monte_carlo_uses_the_exact_generator_seed_count_and_sample_variance():
    req = parse_scientific_request(MC)
    assert req is not None and not req.errors
    result = monte_carlo_integrate(**req.args)
    samples = np.random.Generator(np.random.PCG64(20261028)).uniform(0, 1, 100000)
    y = np.exp(-(samples**2))
    assert result["estimate"] == float(y.mean())
    assert result["standard_error"] == float(y.std(ddof=1) / np.sqrt(100000))
    assert result["standard_errors_from_reference"] == pytest.approx(
        abs(y.mean() - 0.746824132812427) / (y.std(ddof=1) / np.sqrt(100000))
    )
    other = monte_carlo_integrate("x^2", 0, 2, 12345, 17)
    assert other["num_samples"] == 12345 and other["seed"] == 17
    assert abs(other["estimate"] - 8 / 3) < 0.1
    assert other["sample_sha256"] != result["sample_sha256"]


@pytest.mark.parametrize("q,kind", [(RC, "rc_charge"), (BEAM, "beam")])
def test_engineering_inputs_keep_their_si_values_and_have_no_invented_design_limits(q, kind):
    req = parse_scientific_request(q)
    assert req is not None and req.kind == kind
    out = run_calculator(**req.args)
    vals = {r["name"]: r["value"] for r in out["results"]}
    if kind == "rc_charge":
        assert vals["time_constant"] == pytest.approx(1)
        assert vals["capacitor_voltage"] == pytest.approx(12 * (1 - math.exp(-1)))
        assert abs(vals["kvl_residual"]) < 1e-12
    else:
        assert vals["second_moment_of_area"] == pytest.approx(0.02 * 0.04**3 / 12)
        assert vals["max_bending_stress"] == pytest.approx(56.25e6)
        assert vals["max_deflection"] == pytest.approx(0.010546875)
        assert out["utilisation"] is None


@pytest.mark.parametrize("query", [OSCILLATOR, HEAT, MC, RC, BEAM])
def test_full_pipeline_executes_supported_requests_without_any_model_call(monkeypatch, query):
    import tribos.agents.authoritative_orchestrator as module
    from tribos.utils.output_contract import extract, validate

    def no_model(**_kw):
        raise AssertionError("This closed numerical execution must not call an LLM.")

    monkeypatch.setattr(module, "get_llm", no_model)
    started = time.perf_counter()
    answer = asyncio.run(
        module.AuthoritativeOrchestrator().execute_inquiry(
            query=query,
            thread_id="executed-science",
            framework="auto",
            enable_web_search=False,
            persist_memory=False,
            recall_memory=False,
        )
    )
    assert answer.task_status["task_status"] == "completed", answer.response
    record = answer.execution_artifacts["scientific_execution"]
    assert record["status"] in ("executed", "reused") and record["request_match"]
    assert all(c["passed"] for c in record["checks"])
    assert record["reproduction_script_executed"] is False
    assert not validate(answer.response, extract(query))
    assert (
        time.perf_counter() - started < 10
    )  # regression against multi-minute planning/writing, not a microbenchmark


def test_unrecognised_tasks_are_not_claimed_as_executed():
    assert (
        parse_scientific_request("Simulate a turbulent combustion chamber using a 3-D LES mesh.")
        is None
    )
    assert (
        parse_scientific_request(MC.replace("crude Monte Carlo", "importance-sampled Monte Carlo"))
        is None
    )


@pytest.mark.parametrize("analytical,expected", [(False, "completed"), (True, "partial")])
def test_exactly_n_steps_does_not_request_an_analytical_reference(
    monkeypatch, analytical, expected
):
    import tribos.agents.authoritative_orchestrator as module

    def no_model(**_kw):
        raise AssertionError("Numerical execution must not call the writing model.")

    monkeypatch.setattr(module, "get_llm", no_model)
    query = (
        "Simulate y' = -y^2 with y(0) = 1 using classical RK4 with a fixed step of 0.01 s "
        "for exactly 100 steps. Report y at t = 1 s. Do not search the web."
    )
    if analytical:
        query += " Also compute an analytical reference and the absolute error."
    request = parse_scientific_request(query)
    assert request is not None and request.args["analytic_reference"] is analytical
    answer = asyncio.run(
        module.AuthoritativeOrchestrator().execute_inquiry(
            query=query,
            thread_id="analytical-reference-scope",
            framework="auto",
            enable_web_search=False,
            persist_memory=False,
            recall_memory=False,
        )
    )
    assert answer.task_status["task_status"] == expected
    data = answer.execution_artifacts["dynamis"]
    assert data["summary"]["y"]["final"] == pytest.approx(0.5, abs=1e-9)
    assert data.get("analytical_reference") is None
    if analytical:
        assert answer.task_status["deliverables"][1]["check_state"] == "unverified"


def test_failed_numerical_execution_is_not_reported_as_a_completed_simulation(monkeypatch):
    import tribos.agents.authoritative_orchestrator as module

    def no_model(**_kw):
        raise AssertionError("Invalid simulation inputs must not trigger a writing-model retry.")

    monkeypatch.setattr(module, "get_llm", no_model)
    answer = asyncio.run(
        module.AuthoritativeOrchestrator().execute_inquiry(
            query=HEAT.replace("Δt = 20", "Δt = 100"),
            thread_id="failed-heat-execution",
            framework="auto",
            enable_web_search=False,
            persist_memory=False,
            recall_memory=False,
        )
    )
    assert answer.task_status["task_status"] == "failed"
    assert answer.execution_artifacts["scientific_execution"]["status"] == "failed"
    assert not answer.execution_artifacts.get("pde")
    assert not answer.task_status["deliverables"]
    assert not answer.verification_report["passed"]
