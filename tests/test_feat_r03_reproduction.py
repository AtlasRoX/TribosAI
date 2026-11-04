from __future__ import annotations

import copy
from typing import Any

from tribos.agents.orchestration.scientific import _contract_checks
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

MC = (
    "Estimate the integral of exp(-x^2) from x = 0 to 1 using crude Monte Carlo with exactly 100,000 independent "
    "uniform samples. For reproducibility, use NumPy Generator with PCG64 and seed 20261028. Report the estimate, "
    "the sample-based standard error, and the number of standard errors between your estimate and the reference "
    "value 0.746824132812427. Return exactly three numbered items. State the sampling method and seed. Do not search the web."
)

HEAT = (
    "Simulate the one-dimensional heat equation ∂T/∂t = α∂²T/∂x² on 0 ≤ x ≤ 1 m, with α = 1×10^-4 m²/s. "
    "Use 11 equally spaced nodes (Δx = 0.1 m), the explicit FTCS method, and Δt = 20 s for exactly 10 steps. "
    "Set the boundary temperatures to T(0,t) = 100°C and T(1,t) = 0°C. Initially set all nine interior nodes "
    "to 0°C; apply the boundary values at every step. Return: 1. The stability parameter and stability. "
    "2. The temperatures at all 11 nodes after 10 steps. 3. A check of boundary values. Do not search the web."
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


def test_r03_malformed_ode_probe_is_rejected() -> None:
    """R03 Acceptance: ODE report with matching input metadata but only 1 sample and no 't' array MUST be rejected."""
    req = parse_scientific_request(OSCILLATOR)
    assert req is not None
    assert req.kind == "ode_rk4"

    malformed_ode_data: dict[str, Any] = {
        "method": "RK4",
        "spec": dict(req.args),
        "solver": {"internal_steps": 100},
        "trajectories": {"x": [0.1], "v": [0.0]},  # only 1 sample
        # No 't' time array!
    }

    checks = _contract_checks(req, malformed_ode_data)
    failed = [c["name"] for c in checks if not c["passed"]]
    assert len(failed) >= 1, "Malformed ODE probe must not pass contract checks"
    assert "Requested time span and strictly ordered grid" in failed
    assert "Requested ODE, initial state, and matching trajectory shapes" in failed


def test_r03_malformed_monte_carlo_probe_is_rejected() -> None:
    """R03 Acceptance: Monte Carlo report with wrong integrand, wrong bounds and negative SE MUST be rejected."""
    req = parse_scientific_request(MC)
    assert req is not None
    assert req.kind == "monte_carlo"

    malformed_mc_data: dict[str, Any] = {
        "generator": "numpy.random.Generator(PCG64)",
        "seed": req.args["seed"],
        "num_samples": req.args["num_samples"],
        "expression": "sin(x)",  # Different integrand
        "bounds": [0.0, 2.0],    # Different bounds
        "ddof": 1,
        "standard_error": -1.0,  # Negative standard error
        "estimate": 0.5,
    }

    checks = _contract_checks(req, malformed_mc_data)
    failed = [c["name"] for c in checks if not c["passed"]]
    assert len(failed) >= 1, "Malformed MC probe must not pass contract checks"
    assert "Requested integrand expression, variable, and bounds" in failed
    assert "Valid estimator and non-negative standard error" in failed


def test_r03_valid_workloads_all_pass() -> None:
    """All five legitimate numerical engines emit reports that satisfy tightened contract checks."""
    r_osc = parse_scientific_request(OSCILLATOR)
    assert r_osc is not None
    d_osc = dynamis_simulate_ode(**r_osc.args)
    assert all(c["passed"] for c in _contract_checks(r_osc, d_osc))

    r_mc = parse_scientific_request(MC)
    assert r_mc is not None
    d_mc = monte_carlo_integrate(**r_mc.args)
    assert all(c["passed"] for c in _contract_checks(r_mc, d_mc))

    r_heat = parse_scientific_request(HEAT)
    assert r_heat is not None
    d_heat = solve_pde(**r_heat.args)
    assert all(c["passed"] for c in _contract_checks(r_heat, d_heat))

    r_rc = parse_scientific_request(RC)
    assert r_rc is not None
    d_rc = run_calculator(r_rc.args["calculator"], r_rc.args["inputs"])
    assert all(c["passed"] for c in _contract_checks(r_rc, d_rc))

    r_beam = parse_scientific_request(BEAM)
    assert r_beam is not None
    d_beam = run_calculator(r_beam.args["calculator"], r_beam.args["inputs"])
    assert all(c["passed"] for c in _contract_checks(r_beam, d_beam))


def test_r03_field_mutations_cause_scoped_failures() -> None:
    """Mutating important input/output fields independently causes scoped failed checks."""
    r_osc = parse_scientific_request(OSCILLATOR)
    assert r_osc is not None
    d_osc = dynamis_simulate_ode(**r_osc.args)

    # Mutate method
    m1 = copy.deepcopy(d_osc)
    m1["method"] = "RK45"
    assert not all(c["passed"] for c in _contract_checks(r_osc, m1))

    # Mutate time grid (non-strictly-increasing)
    m2 = copy.deepcopy(d_osc)
    m2["t"] = list(reversed(d_osc["t"]))
    assert not all(c["passed"] for c in _contract_checks(r_osc, m2))

    # Mutate trajectory with NaN
    m3 = copy.deepcopy(d_osc)
    m3["trajectories"]["x"][50] = float("nan")
    assert not all(c["passed"] for c in _contract_checks(r_osc, m3))

    r_mc = parse_scientific_request(MC)
    assert r_mc is not None
    d_mc = monte_carlo_integrate(**r_mc.args)

    # Mutate seed
    m4 = copy.deepcopy(d_mc)
    m4["seed"] = 999999
    assert not all(c["passed"] for c in _contract_checks(r_mc, m4))

    # Mutate SE to negative
    m5 = copy.deepcopy(d_mc)
    m5["standard_error"] = -0.05
    assert not all(c["passed"] for c in _contract_checks(r_mc, m5))
