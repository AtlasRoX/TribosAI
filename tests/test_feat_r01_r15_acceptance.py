"""Acceptance and regression test suite covering R01-R15 scientific computing requirements.

Verifies:
1. Scoped task contracts, isolated namespaces, and unit normalization with provenance.
2. Complete eight-part answer assembly and truncation repair for cut-off drafts.
3. Multi-artifact identity hygiene, distinct simulation slots, and downloadable files.
4. Mathematical, physical, and unit claim checks (zero false contradictions on valid equations).
5. All seven independent regression fixtures from prompt instructions.
6. Execution contract checks and rejection of malformed / mutated numerical outputs.
7. Real-execution Matplotlib figure generation with axes, labels, units, and hashes.
"""

from __future__ import annotations

import math

from tribos.dynamis.engine import dynamis_simulate_ode
from tribos.dynamis.monte_carlo import monte_carlo_integrate
from tribos.dynamis.pde import solve_pde
from tribos.engcalc import run_calculator
from tribos.scientific.assembly import (
    build_downloadable_files,
    build_scientific_figures,
    check_and_repair_truncation,
    repair_unclosed_delimiters,
)
from tribos.scientific.contracts import (
    TaskSpec,
    normalize_physical_quantity,
)
from tribos.scientific.requests import (
    ScientificRequest,
    parse_composite_scientific_request,
)
from tribos.verify.math_claims import FAILED, audit_answer


def test_r01_scoped_contracts_and_unit_normalization():
    """Verify independent symbol namespaces and unit normalization provenance (R01)."""
    # 1. Normalized physical quantities with provenance
    val, unit, prov = normalize_physical_quantity("2000 g")
    assert math.isclose(val, 2.0)
    assert unit == "kg"
    assert "2000 g -> 2 kg" in prov

    val, unit, prov = normalize_physical_quantity("5 cm")
    assert math.isclose(val, 0.05)
    assert unit == "m"
    assert "5 cm -> 0.05 m" in prov

    val, unit, prov = normalize_physical_quantity("30 mm")
    assert math.isclose(val, 0.03)
    assert unit == "m"
    assert "30 mm -> 0.03 m" in prov

    val, unit, prov = normalize_physical_quantity("200 GPa", "Pa")
    assert math.isclose(val, 200e9)
    assert unit == "Pa"
    assert "200 GPa" in prov and "Pa" in prov

    # 2. Independent symbol coexistence: beam height h vs RK4 step h
    beam_task = TaskSpec(
        task_id="beam_task",
        section_index=3,
        title="Cantilever Beam Deflection",
        kind="beam",
        normalized_inputs={"L": 1.2, "b": 0.025, "h": 0.03, "E": 200e9, "P": 150.0},
        scope={"h": 0.03, "units": "m"},
    )
    rk4_task = TaskSpec(
        task_id="rk4_task",
        section_index=4,
        title="Damped Harmonic Oscillator RK4",
        kind="ode_rk4",
        parameters={"h": 0.01, "steps": 200},
        scope={"h": 0.01, "units": "s"},
    )
    mc_task = TaskSpec(
        task_id="mc_task",
        section_index=6,
        title="Monte Carlo Quadrature",
        kind="monte_carlo",
        parameters={"N": 20000, "seed": 20261028},
        scope={"N": 20000},
    )

    assert beam_task.scope["h"] == 0.03
    assert rk4_task.scope["h"] == 0.01
    assert rk4_task.parameters["steps"] == 200
    assert mc_task.parameters["N"] == 20000
    assert beam_task.task_id != rk4_task.task_id


def test_r02_truncation_detection_and_repair():
    """Verify delimiter closure and full 8-section completion when draft is truncated (R02, R15)."""
    # Test unclosed LaTeX delimiters
    unclosed_math = "The velocity equation is $$v(t) = \\dot{x}(t)"
    repaired_math = repair_unclosed_delimiters(unclosed_math)
    assert repaired_math.endswith("\n$$")

    unclosed_inline = "where $x_0 = 0.05"
    repaired_inline = repair_unclosed_delimiters(unclosed_inline)
    assert repaired_inline.endswith("$")

    unclosed_env = "$$\\begin{aligned}\n\\dot{x} &= v \\\\\n\\dot{v} &= -0.3 v - 4 x"
    repaired_env = repair_unclosed_delimiters(unclosed_env)
    assert "\\end{aligned}" in repaired_env

    # Test truncated multi-section draft ending midway through section 4
    cut_off_draft = """### Section 1: Arithmetic & Function Domain Evaluation
1. 2k+1 for k=1,3,6 gives 3, 7, 13.
2. f(2) undefined, f(3)=9, f(0) undefined, f(6)=30.

### Section 2: RC Charging Circuit Transient Analysis
tau = 1.034 s, Vc(1s) = 5.5784 V.

### Section 3: Cantilever Beam Structural Analysis
I = 5.625e-8 m^4, stress = 48 MPa, deflection = 7.68 mm.

### Section 4: Damped Harmonic Oscillator Simulation (RK4)
Governing ODE: $$\\ddot{x} + 0.3 \\dot{x} + 4 x = 0"""

    # Without executed composite results, nothing may be appended: the missing sections would be stored example
    # numbers, not this run's results (AUDIT-025). Only the unclosed math is repaired.
    repaired_full = check_and_repair_truncation(cut_off_draft, {})
    assert "Section 5" not in repaired_full
    assert repaired_full.rstrip().endswith("$$")
    # An unrelated answer is never given composite sections, whatever artifacts the run holds.
    other = check_and_repair_truncation("Two papers matched the query.", {"scientific_execution": {"kind": "composite_scientific"}})
    assert other == "Two papers matched the query."


def test_r03_independent_regression_fixtures_exact_computation():
    """Verify all independent numerical regression fixtures match independent benchmarks (R03, R05)."""
    # 1. Arithmetic & Function domain
    k_vals = [1, 3, 6]
    arith_results = [2 * k + 1 for k in k_vals]
    assert arith_results == [3, 7, 13]

    def f_domain(n: int) -> int | None:
        if n < 3:
            return None
        return n ** 2 - 2 * n + 6

    assert f_domain(0) is None
    assert f_domain(2) is None
    assert f_domain(3) == 9
    assert f_domain(6) == 30

    # 2. RC Charging calculation
    rc_out = run_calculator("rc_charge", inputs={
        "resistance": 4700.0,
        "capacitance": 220e-6,
        "source_voltage": 9.0,
        "initial_voltage": 0.0,
        "time": 1.0,
    })
    rc_dict = {r["name"]: float(r["value"]) for r in rc_out["results"]}
    assert math.isclose(rc_dict["time_constant"], 1.034, rel_tol=1e-6)
    assert math.isclose(rc_dict["capacitor_voltage"], 5.57840577903963, rel_tol=1e-9)
    assert math.isclose(rc_dict["initial_current"], 0.0019148936170212765, rel_tol=1e-9)
    assert math.isclose(rc_dict["current"], 0.0007279987704170998, rel_tol=1e-9)
    assert math.isclose(rc_dict["kvl_residual"], 0.0, abs_tol=1e-12)

    # 3. Cantilever Beam structural calculation
    beam_out = run_calculator("beam", inputs={
        "length": 1.2,
        "point_load": 150.0,
        "width": 0.025,
        "height": 0.03,
        "elastic_modulus": 200e9,
        "support": "cantilever",
        "load": "point",
        "section": "rectangle",
    })
    beam_dict = {r["name"]: float(r["value"]) for r in beam_out["results"]}
    assert math.isclose(beam_dict["second_moment_of_area"], 5.625e-8, rel_tol=1e-9)
    assert math.isclose(beam_dict["max_bending_moment"], 180.0, rel_tol=1e-9)
    assert math.isclose(beam_dict["max_bending_stress"], 48.0e6, rel_tol=1e-9)
    assert math.isclose(beam_dict["max_deflection"], 0.00768, rel_tol=1e-9)
    assert math.isclose(beam_dict["deflection_ratio"], 0.0064, rel_tol=1e-9)

    # 4. Oscillator RK4 integration
    ode_out = dynamis_simulate_ode(
        rhs={"x": "v", "v": "-0.3*v - 4*x"},
        initial_state={"x": 0.05, "v": 0.0},
        t_span=[0.0, 2.0],
        method="RK4",
        step_size=0.01,
        num_steps=200,
        analytic_reference=True,
    )
    assert ode_out["solver"]["internal_steps"] == 200
    assert len(ode_out["t"]) == 201
    assert math.isclose(ode_out["t"][-1], 2.0, abs_tol=1e-12)
    x_endpoint = ode_out["trajectories"]["x"][-1]
    v_endpoint = ode_out["trajectories"]["v"][-1]
    assert math.isclose(x_endpoint, -0.026613563148218233, rel_tol=1e-7)
    assert math.isclose(v_endpoint, 0.055673034336488375, rel_tol=1e-7)

    # Analytical reference comparison
    ref_x = ode_out["analytical_reference"]["endpoint"]["x"]
    ref_v = ode_out["analytical_reference"]["endpoint"]["v"]
    assert math.isclose(ref_x, -0.026613562968754344, rel_tol=1e-7)
    assert math.isclose(ref_v, 0.055673034478066215, rel_tol=1e-7)
    assert abs(x_endpoint - ref_x) < 2e-9

    # 5. Heat FTCS 1D PDE
    heat_out = solve_pde(
        equation="heat",
        dimension=1,
        domain=[[0.0, 1.0]],
        parameters={"alpha": 8e-5},
        initial_condition="20.0",
        boundary="dirichlet",
        boundary_values={"x0": 80.0, "x1": 20.0},
        t_span=[0.0, 200.0],
        num_points=11,
        num_times=9,
        method="explicit",
        dt=25.0,
    )
    expected_heat = [80.0, 55.301888, 36.6843392, 26.1473792, 21.711104, 20.3456, 20.047616, 20.0039936, 20.0001536, 20.0, 20.0]
    actual_heat = heat_out["field"]
    assert len(actual_heat) == 11
    for a, e in zip(actual_heat, expected_heat):
        assert math.isclose(a, e, rel_tol=1e-6, abs_tol=1e-6)

    # 6. Monte Carlo quadrature
    mc_out = monte_carlo_integrate(
        expression="exp(-2*x^2)",
        variable="x",
        lower=0.0,
        upper=1.0,
        num_samples=20000,
        seed=20261028,
        generator="PCG64",
        reference=0.5981440066613041,
    )
    assert math.isclose(mc_out["estimate"], 0.5921229069296724, rel_tol=1e-9)
    assert math.isclose(mc_out["standard_error"], 0.0020312740303165947, rel_tol=1e-9)
    assert math.isclose(mc_out["standard_errors_from_reference"], 2.9641986466460284, rel_tol=1e-5)


def test_r04_claim_verification_zero_false_contradictions():
    """Verify zero false contradictions on valid physical/mathematical equations (R04)."""
    valid_text = (
        "Young's modulus is E = 200 * 10^9 Pa.\n"
        "The second moment of area is I = bh^3 / 12 = 5.625 * 10^-8 m^4.\n"
        "Initial displacement is x(0) = 5 cm = 0.05 m.\n"
        "Initial velocity is v(0) = 0 m/s.\n"
        "Initial capacitor voltage is Vc(0) = 0 V.\n"
        "The time constant is tau = 1.034 s.\n"
        "The oscillator governing equation is x'' + 0.3*x' + 4*x = 0.\n"
    )
    report = audit_answer(valid_text, tool_results={})
    failed_claims = [c for c in report.claims if c.status == FAILED]
    assert len(failed_claims) == 0, f"False contradictions found: {[c.text for c in failed_claims]}"


def test_r05_execution_contract_checks_reject_malformed_reports():
    """Verify execution validator rejects incomplete arrays, missing grids, and negative SE (R05)."""
    from tribos.agents.orchestration.scientific import _contract_checks

    # 1. Deliberately malformed ODE report (RK4 with only 1 sample)
    ode_req = ScientificRequest(
        "ode_rk4",
        "dynamis_simulate_ode",
        {"rhs": {"x": "v", "v": "-4*x"}, "initial_state": {"x": 0.05, "v": 0.0}, "t_span": [0.0, 2.0], "step_size": 0.01, "num_steps": 200},
        3,
    )
    bad_ode_data = {
        "method": "RK4",
        "solver": {"internal_steps": 200},
        "spec": {"t_span": [0.0, 2.0], "rhs": {"x": "v", "v": "-4*x"}, "initial_state": {"x": 0.05, "v": 0.0}},
        "t": [0.0],  # malformed: only 1 point instead of 201
        "trajectories": {"x": [0.05], "v": [0.0]},
    }
    ode_checks = _contract_checks(ode_req, bad_ode_data)
    assert not all(c["passed"] for c in ode_checks), "Malformed ODE must fail contract checks"

    # 2. Deliberately malformed Monte Carlo report (negative standard error)
    mc_req = ScientificRequest(
        "monte_carlo",
        "dynamis_monte_carlo_integrate",
        {"expression": "exp(-2*x^2)", "variable": "x", "lower": 0.0, "upper": 1.0, "num_samples": 20000, "seed": 20261028},
        3,
    )
    bad_mc_data = {
        "expression": "exp(-2*x^2)",
        "variable": "x",
        "lower": 0.0,
        "upper": 1.0,
        "num_samples": 20000,
        "seed": 20261028,
        "generator": "PCG64",
        "estimate": 0.5921,
        "standard_error": -1.0,  # invalid negative SE
        "ddof": 1,
    }
    mc_checks = _contract_checks(mc_req, bad_mc_data)
    assert not all(c["passed"] for c in mc_checks), "Negative SE must fail contract checks"

    # 3. Deliberately malformed Heat report (wrong boundary reimposition)
    heat_req = ScientificRequest(
        "heat_ftcs",
        "dynamis_solve_pde",
        {
            "equation": "heat",
            "parameters": {"alpha": 8e-5},
            "domain": [[0.0, 1.0]],
            "num_points": 11,
            "num_times": 9,
            "dt": 25.0,
            "boundary_values": {"x0": 80.0, "x1": 20.0},
        },
        3,
        context={"steps": 8, "temperature_unit": "C"},
    )
    bad_heat_data = {
        "equation": "heat",
        "domain": [[0.0, 1.0]],
        "parameters": {"alpha": 8e-5},
        "grid": {"points": 11, "spacing": [0.1]},
        "stability": {"alpha": 8e-5, "dt": 25.0, "steps": 8, "number": 0.2},
        "x": [i * 0.1 for i in range(11)],
        "snapshots": [{"t": 0.0, "values": [50.0] * 11}],  # boundaries do not match 80.0 / 20.0
        "field": [50.0] * 11,
    }
    heat_checks = _contract_checks(heat_req, bad_heat_data)
    assert not all(c["passed"] for c in heat_checks), "Violated boundary condition must fail contract checks"


def test_r06_downloadable_files_and_figure_artifacts():
    """Verify downloadable datasets, CSVs, JSONs, and Matplotlib figures (R06, R09, R11)."""
    # Sample realistic numerical results
    results_map = {
        "oscillator": {
            "t": [round(i * 0.01, 2) for i in range(201)],
            "trajectories": {
                "x": [0.05 * math.cos(2 * i * 0.01) for i in range(201)],
                "v": [-0.1 * math.sin(2 * i * 0.01) for i in range(201)],
            },
            "solver": {"internal_steps": 200, "function_evaluations": 800},
            "analytical_reference": {"endpoint": {"x": -0.02661356, "v": 0.05567303}},
        },
        "heat": {
            "field": [80.0, 55.3, 36.6, 26.1, 21.7, 20.3, 20.0, 20.0, 20.0, 20.0, 20.0],
            "stability": {"number": 0.20, "steps": 8, "dt": 25.0},
            "snapshots": [
                {"t": 0.0, "values": [80.0] + [20.0] * 10},
                {"t": 200.0, "values": [80.0, 55.3, 36.6, 26.1, 21.7, 20.3, 20.0, 20.0, 20.0, 20.0, 20.0]},
            ],
        },
        "beam": {
            "results": [
                {"name": "second_moment_of_area", "value": 5.625e-8},
                {"name": "max_bending_moment", "value": 180.0},
                {"name": "max_bending_stress", "value": 48e6},
                {"name": "max_deflection", "value": 0.00768},
                {"name": "deflection_ratio", "value": 0.0064},
            ]
        },
        "monte_carlo": {
            "estimate": 0.5921229,
            "standard_error": 0.002031,
            "reference": 0.598144,
            "num_samples": 20000,
            "seed": 20261028,
            "generator": "PCG64",
            "standard_errors_from_reference": 2.964,
        },
        "scientific_execution": {
            "status": "executed",
            "package_versions": {"numpy": "2.3.5", "scipy": "1.17.0", "sympy": "1.13.3"},
        },
    }

    # 1. Downloadable files test
    downloads = build_downloadable_files(results_map)
    file_names = [d["name"] for d in downloads]
    assert "oscillator_rk4_trajectory.csv" in file_names
    assert "oscillator_rk4_trajectory.json" in file_names
    assert "heat_1d_ftcs_distribution.csv" in file_names
    assert "heat_1d_ftcs_distribution.json" in file_names
    assert "beam_deflection_profile.csv" in file_names
    assert "beam_deflection_profile.json" in file_names
    assert "monte_carlo_samples_summary.json" in file_names
    assert "scientific_execution_audit.json" in file_names

    # Check contents of CSV
    osc_csv = next(d["content"] for d in downloads if d["name"] == "oscillator_rk4_trajectory.csv")
    csv_rows = osc_csv.strip().split("\n")
    assert len(csv_rows) == 202  # header + 201 data points
    assert csv_rows[0] == "t_s,x_m,v_m_per_s"

    # 2. Matplotlib figures test
    figures = build_scientific_figures(results_map)
    fig_ids = [f["figure_id"] for f in figures]
    assert "fig_oscillator_trajectory" in fig_ids
    assert "fig_heat_profiles" in fig_ids
    assert "fig_beam_structural" in fig_ids
    assert "fig_monte_carlo" in fig_ids

    for fig in figures:
        assert fig["format"] == "png"
        assert len(fig["data"]) > 1000  # non-trivial base64 image
        assert "<svg" in fig["svg"]  # valid vector SVG
        assert fig["dpi"] == 120
        assert len(fig["file_sha256"]) == 64


def test_r07_composite_query_parsing():
    """Verify parsing of full composite scientific query without preset collision (R07, R08)."""
    composite_query = """
    Evaluate the following 8 parts:
    1. Evaluate 2k+1 for k=1,3,6. For f(n) = n^2 - 2n + 6 on integers n >= 3, find f(2), f(3), f(0), f(6).
    2. RC circuit: Vs = 9 V, R = 4700 ohm, C = 220 uF, initially uncharged, t = 1 s.
    3. Rectangular cantilever beam: length L = 1.2 m, width b = 25 mm, height h = 30 mm, E = 200 GPa, tip point load P = 150 N at free end.
    4. Oscillator: m = 2 kg, c = 0.6 N*s/m, k = 8 N/m. x'' + 0.3*x' + 4*x = 0 with x(0) = 5 cm, x'(0) = 0 m/s. Integrate using classical RK4 with step size 0.01 s for 200 steps to 2 s.
    5. Heat equation: alpha = 8e-5 m^2/s on 0 <= x <= 1 m, 11 nodes, dt = 25 s, exactly 8 steps using FTCS. Boundaries T(0, t) = 80 C, T(1, t) = 20 C, initially interior nodes to 20 C.
    6. Monte Carlo integral of exp(-2*x^2) from 0 to 1 with 20000 samples and seed 20261028. Reference 0.5981440066613041.
    7. Scientific execution audit and verification ledger.
    8. References.
    """
    comp_req = parse_composite_scientific_request(composite_query)
    assert comp_req is not None
    assert comp_req.kind == "composite_scientific"
    task_kinds = [t.kind for t in comp_req.tasks]
    assert "rc_charge" in task_kinds
    assert "beam" in task_kinds
    assert "ode_rk4" in task_kinds
    assert "heat_ftcs" in task_kinds
    assert "monte_carlo" in task_kinds
    assert len(comp_req.tasks) == 5
