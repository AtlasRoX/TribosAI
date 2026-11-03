from __future__ import annotations

import base64
import io
from pathlib import Path
import zipfile

import pytest

from tribos.extensions.sandbox import run_calcula_python
from tribos.scientific.worker import (
    ExecutionJobRequest,
    PythonExecutionWorker,
    get_runtime_metadata,
    validate_execution_outputs,
)


@pytest.mark.asyncio
async def test_worker_runtime_metadata():
    meta = get_runtime_metadata()
    assert "versions" in meta
    vers = meta["versions"]
    assert "numpy" in vers and "scipy" in vers and "sympy" in vers
    assert "pandas" in vers and "matplotlib" in vers and "pint" in vers
    assert meta["runtime_digest"].startswith("runtime-")
    assert meta["backend"] == "headless_agg"
    assert "isolation" in meta
    assert "subprocess" in meta["isolation"]


@pytest.mark.asyncio
async def test_worker_scientific_execution_and_figures():
    worker = PythonExecutionWorker(concurrency=2, timeout_s=30)
    code = """
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

x = np.linspace(0, 2*np.pi, 50)
y = np.sin(x)

plt.figure(figsize=(6, 3))
plt.plot(x, y, 'r--', label='sin')
plt.title('Sine Wave')
plt.xlabel('x [rad]')
plt.ylabel('sin(x)')
plt.grid(True)

df = pd.DataFrame({'x': x, 'y': y})

result = {
    'count': len(x),
    'mean': float(np.mean(y)),
    'max': float(np.max(y)),
    'min': float(np.min(y)),
    'x': x.tolist(),
    'y': y.tolist(),
}
tables = {'wave_table': df}
"""
    req = ExecutionJobRequest(
        code=code,
        task_id="sine_wave_task",
        output_contract={
            "required_keys": ["count", "mean", "max", "min"],
            "expected_lengths": {"x": 50, "y": 50},
        },
    )
    res = await worker.execute_job(req)
    assert res.status == "completed"
    assert res.exit_code == 0
    assert res.result["count"] == 50
    assert abs(res.result["mean"]) < 1e-10
    assert len(res.figures) >= 1
    fig = res.figures[0]
    assert "png_base64" in fig and len(fig["png_base64"]) > 100
    assert "svg" in fig and "<svg" in fig["svg"]
    assert len(res.tables) >= 1
    assert res.validation_report["passed"] is True
    assert len(res.downloads) >= 2  # CSV trajectory + reproducibility bundle


@pytest.mark.asyncio
async def test_worker_oscillator_rk4_acceptance_demonstration():
    """
    Required Acceptance Demonstration:
    Oscillator m=2 kg, c=0.6 N*s/m, k=8 N/m, x(0)=0.05 m, v(0)=0.
    Classical RK4, h=0.01 s, exactly 200 steps to 2 s.
    """
    worker = PythonExecutionWorker(concurrency=2, timeout_s=30)
    oscillator_code = """
import numpy as np
import matplotlib.pyplot as plt

m = 2.0
c = 0.6
k = 8.0
x0 = 0.05
v0 = 0.0
h = 0.01
steps = 200

rhs_evals = 0
def f(t, y):
    global rhs_evals
    rhs_evals += 1
    pos, vel = y
    acc = -(c * vel + k * pos) / m
    return [vel, acc]

t_hist = [0.0]
x_hist = [x0]
v_hist = [v0]
y = [x0, v0]
t = 0.0

for _ in range(steps):
    k1 = f(t, y)
    k2 = f(t + 0.5 * h, [y[0] + 0.5 * h * k1[0], y[1] + 0.5 * h * k1[1]])
    k3 = f(t + 0.5 * h, [y[0] + 0.5 * h * k2[0], y[1] + 0.5 * h * k2[1]])
    k4 = f(t + h, [y[0] + h * k3[0], y[1] + h * k3[1]])
    y = [
        y[0] + (h / 6.0) * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0]),
        y[1] + (h / 6.0) * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1]),
    ]
    t += h
    t_hist.append(t)
    x_hist.append(y[0])
    v_hist.append(y[1])

plt.figure(figsize=(7, 4))
plt.plot(t_hist, x_hist, label='Displacement x(t) [m]')
plt.title('Damped Oscillator Classical RK4')
plt.xlabel('Time [s]')
plt.ylabel('x [m]')
plt.grid(True)

result = {
    'm': m, 'c': c, 'k': k, 'h': h, 'steps': steps,
    'time_levels': len(t_hist),
    'rhs_evaluations': rhs_evals,
    'x_end': float(x_hist[-1]),
    'v_end': float(v_hist[-1]),
    't': t_hist,
    'x': x_hist,
    'v': v_hist,
}
"""
    req = ExecutionJobRequest(
        code=oscillator_code,
        task_id="oscillator_rk4_eval",
        output_contract={
            "required_keys": ["time_levels", "rhs_evaluations", "x_end", "v_end"],
            "expected_lengths": {"t": 201, "x": 201, "v": 201},
            "analytical_reference": {
                "kind": "oscillator_rk4",
                "m": 2.0, "c": 0.6, "k": 8.0, "t_end": 2.0, "x0": 0.05, "v0": 0.0,
                "tolerance": 1e-6,
            },
        },
    )
    res = await worker.execute_job(req)
    assert res.status == "completed"
    assert res.exit_code == 0
    assert res.result["time_levels"] == 201
    assert res.result["rhs_evaluations"] == 800
    assert abs(res.result["x_end"] - (-0.026613563148218233)) < 1e-12
    assert abs(res.result["v_end"] - 0.055673034336488375) < 1e-12

    # Validation report checks
    assert res.validation_report["passed"] is True
    checks = {c["name"]: c["passed"] for c in res.validation_report["checks"]}
    assert checks.get("finite_numerical_values") is True
    assert checks.get("array_length_t") is True
    assert checks.get("array_length_x") is True
    assert checks.get("array_length_v") is True
    assert checks.get("oscillator_analytical_reference") is True

    # Figures and downloads
    assert len(res.figures) >= 1
    assert len(res.downloads) >= 2
    traj_csv = next(d for d in res.downloads if d["name"].endswith("_trajectory.csv"))
    assert "t,x,v" in traj_csv["content"]
    assert "201 rows" in traj_csv["meta"]

    bundle = next(d for d in res.downloads if d["name"].endswith("_reproducibility_bundle.zip"))
    assert bundle["bytes"] > 500


@pytest.mark.asyncio
async def test_worker_validation_rejections_and_strictness():
    """Verify validation strictly rejects scalars for dicts, nonnumeric/negative SE, and failed analytical checks."""
    # 1. Scalar output when required keys are specified
    val1 = validate_execution_outputs(
        result=42.0,
        contract={"required_keys": ["count", "mean"]},
    )
    assert val1["passed"] is False
    assert any("Output must be a dictionary" in err for err in val1["errors"])

    # 2. Nonnumeric standard error
    val2 = validate_execution_outputs(
        result={"mean": 1.5, "standard_error": "not_a_number"},
        contract={},
    )
    assert val2["passed"] is False
    assert any("Standard error is non-numeric" in err for err in val2["errors"])

    # 3. Negative standard error
    val3 = validate_execution_outputs(
        result={"mean": 1.5, "standard_error": -0.2},
        contract={},
    )
    assert val3["passed"] is False
    assert any("Invalid or negative standard error" in err for err in val3["errors"])

    # 4. Failed analytical reference calculation (endpoint discrepancy)
    val4 = validate_execution_outputs(
        result={"x_end": 10.0, "v_end": 0.0},
        contract={
            "analytical_reference": {
                "kind": "oscillator_rk4",
                "m": 2.0, "c": 0.6, "k": 8.0, "t_end": 2.0, "x0": 0.05, "v0": 0.0,
                "tolerance": 1e-6,
            }
        },
    )
    assert val4["passed"] is False
    assert any("Analytical endpoint discrepancy exceeds tolerance" in err for err in val4["errors"])

    # 5. Non-dict result with analytical reference
    val5 = validate_execution_outputs(
        result=[1, 2, 3],
        contract={"analytical_reference": {"kind": "oscillator_rk4"}},
    )
    assert val5["passed"] is False

    # 6. Unsupported analytical reference
    val6 = validate_execution_outputs(
        result={"ans": 1},
        contract={"analytical_reference": {"kind": "unsupported_physical_sim"}},
    )
    assert val6["passed"] is False


@pytest.mark.asyncio
async def test_worker_cache_scope_isolation():
    """Verify cache keys isolate between different users, projects, contracts, and inputs."""
    worker = PythonExecutionWorker(concurrency=2)
    code = "result = {'computed': 100}"

    # User Alice execution
    req_alice = ExecutionJobRequest(code=code, user_id="alice", project_id="proj_shared", task_id="t_a")
    res_alice = await worker.execute_job(req_alice)
    assert res_alice.status == "completed"
    assert res_alice.reused is False

    # Same request by Alice hits cache
    req_alice_2 = ExecutionJobRequest(code=code, user_id="alice", project_id="proj_shared", task_id="t_a2")
    res_alice_2 = await worker.execute_job(req_alice_2)
    assert res_alice_2.reused is True
    assert res_alice_2.reused_from_job_id == res_alice.job_id

    # User Bob with same code and project must NOT hit Alice's cache
    req_bob = ExecutionJobRequest(code=code, user_id="bob", project_id="proj_shared", task_id="t_b")
    res_bob = await worker.execute_job(req_bob)
    assert res_bob.reused is False

    # User Alice with different project must NOT hit cache
    req_alice_p2 = ExecutionJobRequest(code=code, user_id="alice", project_id="proj_other", task_id="t_a_p2")
    res_alice_p2 = await worker.execute_job(req_alice_p2)
    assert res_alice_p2.reused is False

    # Different output contract must NOT hit cache
    req_contract = ExecutionJobRequest(
        code=code,
        user_id="alice",
        project_id="proj_shared",
        task_id="t_c",
        output_contract={"required_keys": ["computed"]},
    )
    res_contract = await worker.execute_job(req_contract)
    assert res_contract.reused is False

    # Stochastic request (skip cache)
    code_rand = "import random; result = {'rnd': random.random()}"
    res_stoch1 = await worker.execute_job(ExecutionJobRequest(code=code_rand, user_id="alice", task_id="t_r1"))
    res_stoch2 = await worker.execute_job(ExecutionJobRequest(code=code_rand, user_id="alice", task_id="t_r2"))
    assert res_stoch1.reused is False
    assert res_stoch2.reused is False


@pytest.mark.asyncio
async def test_reproducibility_bundle_base64_and_extraction():
    """Verify reproducibility bundle has valid Base64 encoding and can be extracted."""
    worker = PythonExecutionWorker(concurrency=2)
    code = "result = {'val': 3.141592653589793}"
    req = ExecutionJobRequest(code=code, task_id="bundle_test")
    res = await worker.execute_job(req)
    assert res.status == "completed"

    bundle_dl = next(d for d in res.downloads if d["name"].endswith("_reproducibility_bundle.zip"))
    b64_str = bundle_dl["content_base64"]
    raw_zip_bytes = base64.b64decode(b64_str)
    assert len(raw_zip_bytes) == bundle_dl["bytes"]

    # Open with zipfile and verify contents
    with zipfile.ZipFile(io.BytesIO(raw_zip_bytes), "r") as zf:
        names = zf.namelist()
        assert "executed_script.py" in names
        assert "inputs.json" in names
        assert "results.json" in names
        assert "runtime_manifest.json" in names
        assert "repair_log.json" in names

        script_text = zf.read("executed_script.py").decode("utf-8")
        assert "3.141592653589793" in script_text


@pytest.mark.asyncio
async def test_worker_targeted_code_repair_and_provenance():
    """Verify code repair records original script, executed script, and repair_log.json."""
    worker = PythonExecutionWorker(concurrency=2)
    code_missing_import = "result = {'pi': math.pi * 2}"
    req = ExecutionJobRequest(code=code_missing_import, task_id="repair_test", allow_repair=True)
    res = await worker.execute_job(req)
    assert res.status in ("completed", "repaired")
    assert res.repaired_code is not None
    assert "import math" in res.repaired_code

    bundle_dl = next(d for d in res.downloads if d["name"].endswith("_reproducibility_bundle.zip"))
    raw_zip = base64.b64decode(bundle_dl["content_base64"])
    with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
        names = zf.namelist()
        assert "executed_script.py" in names
        assert "original_script.py" in names
        assert "repair_log.json" in names

        exec_text = zf.read("executed_script.py").decode("utf-8")
        orig_text = zf.read("original_script.py").decode("utf-8")
        assert "import math" in exec_text
        assert "import math" not in orig_text


@pytest.mark.asyncio
async def test_worker_container_engine_refusal_when_unavailable():
    """Verify configured container engine explicitly refuses when unavailable on host."""
    # 'docker' is not installed on this host
    worker = PythonExecutionWorker(container_engine="docker")
    assert worker.isolation_available is False
    res = await worker.execute_job(ExecutionJobRequest(code="result = 1", task_id="docker_test"))
    assert res.status == "unavailable"
    assert res.exit_code == 1
    assert "Container isolation 'docker' was requested but is not available" in (res.error or "")


@pytest.mark.asyncio
async def test_worker_tool_execution_integration(tmp_path: Path):
    """Verify calcula_run_python tool calls the worker and returns full metadata and bundles."""
    code = "result = {'calc': 123 * 456}"
    tool_res = run_calcula_python(code=code)
    assert tool_res.success is True
    data = tool_res.data
    assert data["status"] == "ok"
    assert data["result"]["calc"] == 56088
    assert "reproducibility_bundle" in data
    assert "runtime_manifest" in data
    assert "isolation" in data["runtime_manifest"]
    assert any(
        eng in data["runtime_manifest"]["isolation"]
        for eng in ("subprocess", "podman", "docker")
    )
    assert len(data["downloads"]) >= 1


@pytest.mark.asyncio
async def test_worker_changed_file_contents_under_same_id_causes_cache_miss(tmp_path: Path):
    """Verify that changing file contents under the same identifier changes the hash and misses cache."""
    worker = PythonExecutionWorker(concurrency=2, cache_dir=tmp_path)
    file_id = "ds_testfile0001"
    file_path = tmp_path / file_id
    file_path.write_text("initial content 123", encoding="utf-8")

    code = "result = {'val': 1}"
    req1 = ExecutionJobRequest(
        code=code,
        input_artifact_ids=[file_id],
        task_id="t_content_1",
    )
    res1 = await worker.execute_job(req1)
    assert res1.status == "completed"
    assert res1.reused is False

    # Second run with same file content hits cache
    req2 = ExecutionJobRequest(
        code=code,
        input_artifact_ids=[file_id],
        task_id="t_content_2",
    )
    res2 = await worker.execute_job(req2)
    assert res2.reused is True

    # Modify file content on disk under same ID
    file_path.write_text("modified content 999", encoding="utf-8")
    req3 = ExecutionJobRequest(
        code=code,
        input_artifact_ids=[file_id],
        task_id="t_content_3",
    )
    res3 = await worker.execute_job(req3)
    assert res3.reused is False
    assert res3.input_hashes.get(file_id) != res1.input_hashes.get(file_id)


@pytest.mark.asyncio
async def test_worker_cache_mutation_isolation():
    """Verify callers cannot mutate cached results."""
    worker = PythonExecutionWorker(concurrency=2)
    code = "result = {'items': [1, 2, 3]}"
    req1 = ExecutionJobRequest(code=code, task_id="t_mut_1")
    res1 = await worker.execute_job(req1)
    assert res1.result["items"] == [1, 2, 3]

    # Mutate the returned dictionary
    res1.result["items"].append(999)

    # Next call hitting cache must not see 999
    req2 = ExecutionJobRequest(code=code, task_id="t_mut_2")
    res2 = await worker.execute_job(req2)
    assert res2.reused is True
    assert res2.result["items"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_worker_queue_overload_rejection():
    """Verify queue bound rejects submissions when admission limit is reached."""
    worker = PythonExecutionWorker(concurrency=2)
    worker._pending_count = 32  # MAX_PENDING_JOBS
    req = ExecutionJobRequest(code="result = 1", task_id="t_overload")
    res = await worker.execute_job(req)
    assert res.status == "overloaded"
    assert res.exit_code == 1
    assert "queue limit exceeded" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_worker_running_cancellation():
    """Verify active job process tree is terminated on cancellation."""
    import asyncio
    worker = PythonExecutionWorker(concurrency=2)
    code_long = """
x = 0
for i in range(200_000_000):
    x += 1
result = {'x': x}
"""
    req = ExecutionJobRequest(code=code_long, timeout_s=30, task_id="t_cancel")
    task = asyncio.create_task(worker.execute_job(req))
    await asyncio.sleep(0.5)

    cancelled = worker.cancel_job(req.job_id)
    assert cancelled is True
    res = await task
    assert res.status in ("failed", "error", "timeout")


@pytest.mark.asyncio
async def test_worker_endpoint_match_alone_fails_when_rhs_evals_or_initial_conds_violated():
    """Verify that an endpoint match alone fails if RHS evaluations or initial conditions are violated."""
    from tribos.scientific.worker import validate_execution_outputs

    # Endpoint matches, but RHS evaluations was 200 instead of required 800 (meaning steps were skipped)
    val_rhs = validate_execution_outputs(
        result={"x_end": -0.026613563148, "v_end": 0.055673034336, "rhs_evaluations": 200},
        contract={"expected_rhs_evaluations": 800},
    )
    assert val_rhs["passed"] is False
    assert any("RHS evaluations mismatch" in err for err in val_rhs["errors"])

    # Initial condition mismatch: x(0) was 0.1 instead of 0.05
    val_init = validate_execution_outputs(
        result={"x0": 0.1, "x_end": -0.026613563148},
        contract={"initial_conditions": {"x0": 0.05}},
    )
    assert val_init["passed"] is False
    assert any("Initial condition mismatch" in err for err in val_init["errors"])


def test_evidence_rendering_includes_validation_and_bundle():
    """Verify stem_evidence render_calcula includes validation status and reproducibility bundle."""
    from tribos.agents.stem_evidence import render_calcula
    from types import SimpleNamespace

    mock_res = SimpleNamespace(
        tool_name="calcula_run_python",
        data={
            "status": "ok",
            "result": {"ans": 42},
            "validation": {
                "passed": True,
                "checks": [{"name": "finite_numerical_values", "passed": True}],
            },
            "reproducibility_bundle": {
                "filename": "task_reproducibility_bundle.zip",
                "sha256": "abc12345",
            },
        },
    )
    rendered = render_calcula(mock_res)
    xml_text = "\n".join(rendered)
    assert '<calcula tool="calcula_run_python"' in xml_text
    assert '<validation passed="true">' in xml_text
    assert '<reproducibility_bundle filename="task_reproducibility_bundle.zip"' in xml_text
