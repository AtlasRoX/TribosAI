"""ODE calibration acceptance tests, with analytic data and offline orchestration."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tribos.dynamis.engine import dynamis_fit_parameters, dynamis_parameter_scan, dynamis_simulate_ode


def _inside(result, expected):
    for name, value in expected.items():
        assert result["confidence_intervals"][name][0] < value < result["confidence_intervals"][name][1]
        assert result["parameters"][name] == pytest.approx(value, rel=0.05)
    assert result["converged"]
    assert result["objective"]["rss"] >= 0
    assert np.isfinite(result["objective"]["aic"]) and np.isfinite(result["objective"]["bic"])
    json.dumps(result, allow_nan=False)


def test_oscillator_recovers_parameters_inside_ci():
    t = np.linspace(0, 8, 121)
    omega, zeta = 2.0, 0.2
    wd = omega * np.sqrt(1 - zeta**2)
    x = np.exp(-zeta * omega * t) * (np.cos(wd*t) + zeta*omega/wd*np.sin(wd*t))
    noisy = x + np.random.default_rng(4).normal(0, 0.02, len(t))
    result = dynamis_fit_parameters(model_name="damped_oscillator", data={"time": t, "x": noisy},
                                    param_names=["omega", "zeta"], initial_guess={"omega": 1.8, "zeta": 0.3},
                                    bounds={"omega": [1, 3], "zeta": [0.01, 0.9]}, n_starts=2)
    _inside(result, {"omega": omega, "zeta": zeta})
    assert len(result["fit"]["x"]["residuals"]) <= 200


def test_logistic_column_mapping_and_initial_condition(tmp_path):
    t = np.linspace(0, 10, 101)
    y = 10 / (1 + 9*np.exp(-0.7*t)) + np.random.default_rng(9).normal(0, 0.04, len(t))
    path = tmp_path / "measurements.csv"
    pd.DataFrame({"elapsed": t, "population": y}).to_csv(path, index=False)
    result = dynamis_fit_parameters(rhs={"n": "r*n*(1-n/K)"}, initial_state={"n": 0.9},
                                    parameters={"r": 0.6, "K": 9}, param_names=["r", "K"], data_path=str(path),
                                    time_column="elapsed", column_mapping={"n": "population"}, fit_initial_state=True,
                                    bounds={"r": [0.1, 2], "K": [5, 20], "initial:n": [0.2, 2]}, loss="soft_l1")
    _inside(result, {"r": 0.7, "K": 10})
    assert result["fitted_initial_state"]["n"] == pytest.approx(1, abs=0.05)
    assert result["column_mapping"] == {"n": "population"}
    assert result["metrics"]["n"]["r_squared"] > 0.99


def test_non_identifiable_parameters_do_not_get_false_precision():
    t = np.linspace(0, 5, 35)
    result = dynamis_fit_parameters(rhs={"x": "-a*b*x"}, initial_state={"x": 1},
                                    parameters={"a": 0.5, "b": 0.5}, param_names=["a", "b"],
                                    data={"t": t, "x": np.exp(-0.3*t)})
    assert any("singular" in warning.lower() or "correlat" in warning.lower() for warning in result["warnings"])
    assert not result["identifiable"]


@pytest.mark.parametrize("suffix", [".h5", ".mat", ".xlsx"])
def test_supported_measurement_formats(tmp_path, suffix):
    from tribos.dynamis.fitting import load_measurements

    t = np.arange(5, dtype=float)
    path = tmp_path / ("data" + suffix)
    if suffix == ".h5":
        import h5py
        with h5py.File(path, "w") as handle:
            handle["t"] = t
            handle["x"] = t * 2
    elif suffix == ".mat":
        from scipy.io import savemat
        savemat(path, {"t": t, "x": t*2})
    else:
        pd.DataFrame({"t": t, "x": t*2}).to_excel(path, index=False)
    frame = load_measurements(str(path))
    assert frame["x"].tolist() == (t*2).tolist()


def test_reproducible_specs_and_expression_fit_compatibility():
    sim = dynamis_simulate_ode(model_name="damped_oscillator", parameters={"zeta": 0.2})
    assert sim["spec"]["parameters"]["zeta"] == 0.2
    scan = dynamis_parameter_scan({"x": "-k*x"}, {"x": 1}, "k", (0.1, 0.2), num_points=2)
    assert scan["spec"]["rhs"] == {"x": "-k*x"}
    fit = dynamis_fit_parameters("a*x", "x", ["a"], [0, 1, 2], [0, 3, 6])
    assert fit["parameters"]["a"] == pytest.approx(3)


def test_invalid_data_and_unsafe_odes_are_rejected():
    with pytest.raises(ValueError):
        dynamis_fit_parameters(rhs={"x": "__import__('os').system('x')"}, initial_state={"x": 1},
                               parameters={"k": 1}, param_names=["k"], data={"t": [0, 1, 2], "x": [1, 2, 3]})
    with pytest.raises(ValueError, match="time"):
        dynamis_fit_parameters(rhs={"x": "-k*x"}, initial_state={"x": 1}, parameters={"k": 1},
                               param_names=["k"], data={"t": [0, 0, 1], "x": [1, 2, 3]})


def test_uploaded_fits_cannot_read_unbound_files_or_be_replayed(tmp_path):
    from types import SimpleNamespace
    from tribos.extensions.calibration import run_ode_fit_tool
    from tribos.provenance.rerun import tool_replay_refusal

    secret = tmp_path / "private.csv"
    secret.write_text("private", encoding="utf-8")
    result = run_ode_fit_tool(data_path=str(secret))
    assert not result.success and "attached" in result.error
    assert tool_replay_refusal("dynamis_fit_parameters", SimpleNamespace(tags=[])) is not None


@pytest.mark.asyncio
async def test_agentic_fit_runs_with_uploaded_dataset(monkeypatch, tmp_path):
    from tests.agentic_fakes import make_agentic_orchestrator
    from tribos.datasets.models import DatasetProvenanceIn
    from tribos.datasets.store import get_dataset_store
    from tribos.dynamis.schemas import DynamisFitParametersInput

    t = np.linspace(0, 8, 45)
    simulation = dynamis_simulate_ode(model_name="damped_oscillator", t_span=(0, 8), num_points=len(t))
    content = pd.DataFrame({"t": t, "x": simulation["trajectories"]["x"]}).to_csv(index=False).encode()
    async def chunks():
        yield content
    record = await get_dataset_store().create_from_stream("alice", chunks(), "oscillator.csv", DatasetProvenanceIn())
    orch, calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path, extra_tools={
        "dynamis_fit_parameters": (DynamisFitParametersInput, lambda kwargs: dynamis_fit_parameters(**kwargs)),
    })
    result = await orch.execute_inquiry("Fit the damped oscillator to my attached data", user_id="alice",
                                        thread_id="fit", framework="agentic-plan-execute", dataset_ids=[record.id])
    artifact = result.execution_artifacts["model_calibration"]
    assert artifact["status"] == "converged", artifact
    assert artifact["dataset_id"] == record.id and artifact["fit"]["x"]["observed"]
    assert any(name == "dynamis_fit_parameters" for name, _ in calls)
    assert any("model_calibration" in prompt for prompt in llm.prompts("synthesis"))
