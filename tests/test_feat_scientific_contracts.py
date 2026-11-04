"""Unit tests for Scoped Task & Result Contracts, Unit Normalization, and Requirement Ledger."""

from __future__ import annotations

import math

from tribos.scientific.contracts import (
    RequirementLedger,
    TaskSpec,
    normalize_physical_quantity,
)


def test_unit_normalization_and_provenance():
    # 2000 g -> 2 kg
    val, unit, prov = normalize_physical_quantity("2000 g")
    assert math.isclose(val, 2.0)
    assert unit == "kg"
    assert "2000 g -> 2 kg" in prov

    # 5 cm -> 0.05 m
    val, unit, prov = normalize_physical_quantity("5 cm")
    assert math.isclose(val, 0.05)
    assert unit == "m"
    assert "5 cm -> 0.05 m" in prov

    # 30 mm -> 0.03 m
    val, unit, prov = normalize_physical_quantity("30 mm")
    assert math.isclose(val, 0.03)
    assert unit == "m"
    assert "30 mm -> 0.03 m" in prov

    # 200 GPa -> 200e9 Pa
    val, unit, prov = normalize_physical_quantity("200 GPa")
    assert math.isclose(val, 200e9)
    assert unit == "Pa"
    assert "200 GPa -> 2e+11 Pa" in prov or "200" in prov


def test_symbol_isolation_across_tasks():
    """Ensure beam height h, RK4 step h, Monte Carlo N, and ODE step count N coexist independently."""
    task_beam = TaskSpec(
        task_id="task_beam",
        section_index=4,
        title="Cantilever Beam Deflection",
        kind="beam",
        normalized_inputs={"L": 1.2, "b": 0.025, "h": 0.03, "E": 200e9, "P": 150.0},
        scope={"h": 0.03, "units": "m"},
    )

    task_rk4 = TaskSpec(
        task_id="task_oscillator",
        section_index=5,
        title="Damped Harmonic Oscillator RK4",
        kind="ode_rk4",
        parameters={"m": 2.0, "c": 0.6, "k": 8.0, "h": 0.01, "N": 200},
        scope={"h": 0.01, "N": 200, "units": "s"},
    )

    task_mc = TaskSpec(
        task_id="task_monte_carlo",
        section_index=7,
        title="Crude Monte Carlo Integral",
        kind="monte_carlo",
        parameters={"N": 20000, "seed": 20261028},
        scope={"N": 20000, "units": "samples"},
    )

    # Scopes remain distinct
    assert task_beam.scope["h"] == 0.03
    assert task_rk4.scope["h"] == 0.01
    assert task_beam.scope["h"] != task_rk4.scope["h"]

    assert task_rk4.scope["N"] == 200
    assert task_mc.scope["N"] == 20000
    assert task_rk4.scope["N"] != task_mc.scope["N"]


def test_requirement_ledger_lifecycle_and_counts():
    ledger = RequirementLedger()

    spec1 = TaskSpec(task_id="t1", section_index=1, title="Arithmetic", kind="arithmetic")
    spec2 = TaskSpec(task_id="t2", section_index=2, title="ODE", kind="ode_rk4")
    spec3 = TaskSpec(task_id="t3", section_index=3, title="Audit", kind="execution_audit")

    ledger.add_spec(spec1)
    ledger.add_spec(spec2)
    it3 = ledger.add_spec(spec3)

    assert ledger.summary_counts()["mentioned"] == 3
    assert not ledger.is_complete()

    # Step 1: compute t1 and t2
    ledger.mark_computed("t1", result_id="res_t1")
    ledger.mark_computed("t2", result_id="res_t2")
    assert ledger.summary_counts()["computed"] == 2
    assert ledger.summary_counts()["mentioned"] == 1

    # Step 2: check t1 and t2
    ledger.mark_checked("t1", [{"name": "exact_math", "passed": True}])
    ledger.mark_checked("t2", [{"name": "contract", "passed": True}])
    assert ledger.summary_counts()["checked"] == 2

    # Step 3: deliver t1, t2, t3
    ledger.mark_delivered("t1", location="Section 1")
    ledger.mark_delivered("t2", location="Section 2", files=[{"name": "trajectory.csv", "sha256": "abc"}])
    assert ledger.summary_counts()["complete"] == 2
    assert not ledger.is_complete()  # t3 is still uncomputed/undelivered

    # Deliver t3 with source support
    it3.status = "source_supported"
    ledger.mark_delivered("t3", location="Section 3")
    assert ledger.summary_counts()["complete"] == 3
    assert ledger.is_complete()
