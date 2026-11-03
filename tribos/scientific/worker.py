"""
Real Python execution worker for scientific computing (Calcula).
Executes Python code in an isolated container or subprocess environment with
governed resource limits, read-only inputs, no application credentials,
independent result validation, code repair, and reproducibility bundle packaging.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import logging
import math
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..agentic.sandbox.gateway import execute as _gateway_execute
from ..agentic.sandbox.process import kill_tree as _kill_tree
from ..config.settings import get_float, get_int, get_str

logger = logging.getLogger(__name__)

WORKER_CONCURRENCY_DEFAULT = 4
WORKER_TIMEOUT_S_DEFAULT = 60
WORKER_MEMORY_MB_DEFAULT = 2048
MAX_PENDING_JOBS = 32
CACHE_CAPACITY = 256


def check_container_engine(engine: str) -> tuple[bool, str]:
    """Check if configured container engine is available, or return fallback."""
    engine_name = (engine or "auto").strip().lower()
    if engine_name == "subprocess":
        return True, "subprocess (development)"

    candidates = [engine_name] if engine_name in ("docker", "podman") else ["docker", "podman"]
    for cand in candidates:
        bin_path = shutil.which(cand)
        if bin_path:
            try:
                res = subprocess.run([bin_path, "info"], capture_output=True, text=True, timeout=4)
                if res.returncode == 0:
                    return True, f"{cand} container"
            except Exception:
                pass

    if engine_name in ("docker", "podman"):
        return False, f"Configured container engine '{engine_name}' is not running or responsive on host."

    return True, "subprocess (development)"


def get_runtime_metadata(isolation: str = "subprocess (development)") -> dict[str, Any]:
    """Return versioned scientific runtime metadata and deterministic digest."""
    import matplotlib
    import numpy as np
    import pandas as pd
    import pint
    import scipy
    import sympy

    versions = {
        "python": sys.version.split()[0],
        "numpy": getattr(np, "__version__", "unknown"),
        "scipy": getattr(scipy, "__version__", "unknown"),
        "sympy": getattr(sympy, "__version__", "unknown"),
        "pandas": getattr(pd, "__version__", "unknown"),
        "pint": getattr(pint, "__version__", "unknown"),
        "matplotlib": getattr(matplotlib, "__version__", "unknown"),
    }
    raw_str = ":".join(f"{k}={v}" for k, v in sorted(versions.items()))
    digest = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]
    return {
        "versions": versions,
        "runtime_digest": f"runtime-{digest}",
        "backend": "headless_agg",
        "isolation": isolation,
    }


@dataclass
class ExecutionJobRequest:
    code: str
    user_id: str = "default_user"
    project_id: str = "default_project"
    task_id: str = "task_001"
    run_id: str = "run_001"
    job_id: str = field(default_factory=lambda: f"job_{secrets.token_hex(8)}")
    input_artifact_ids: list[str] = field(default_factory=list)
    input_files: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    requested_outputs: list[str] = field(default_factory=list)
    output_contract: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 60.0
    memory_mb: int = 2048
    allow_repair: bool = True
    fresh_execution: bool = False


@dataclass
class ExecutionJobResult:
    job_id: str
    task_id: str
    run_id: str
    user_id: str
    project_id: str
    status: str  # "completed", "failed", "timeout", "policy_violation", "repaired", "failed_validation", "unavailable"
    exit_code: int
    source_hash: str
    input_hashes: dict[str, str]
    runtime_versions: dict[str, str]
    runtime_digest: str
    isolation: str = "subprocess (development)"
    start_time: float = 0.0
    end_time: float = 0.0
    elapsed_seconds: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    result: Any = None
    numerical_arrays: dict[str, list[float] | list[list[float]]] = field(default_factory=dict)
    tables: list[dict[str, Any]] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    downloads: list[dict[str, Any]] = field(default_factory=list)
    reproducibility_bundle: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    repaired_code: str | None = None
    repair_reason: str | None = None
    reused: bool = False
    reused_from_job_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_finite(val: Any) -> bool:
    """Recursively verify that numerical values contain no NaN or Infinity."""
    if val is None or val == "NaN" or val == "Infinity" or val == "-Infinity":
        return False
    if isinstance(val, (int, bool, str)):
        return True
    if isinstance(val, float):
        return math.isfinite(val)
    if isinstance(val, (list, tuple)):
        return all(_check_finite(x) for x in val)
    if isinstance(val, dict):
        return all(_check_finite(v) for v in val.values())
    if isinstance(val, np.ndarray):
        return bool(np.all(np.isfinite(val)))
    return True


def validate_execution_outputs(
    result: Any,
    contract: dict[str, Any],
    numerical_arrays: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Independent validator outside model-written code.
    Rejects invalid types, missing dictionary fields, nonnumeric/negative standard errors,
    and failed or unavailable analytical reference comparisons.
    """
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    arrays = numerical_arrays or {}

    # 1. Finite numerical values check
    finite_ok = _check_finite(result) and _check_finite(arrays)
    checks.append({
        "name": "finite_numerical_values",
        "passed": finite_ok,
        "detail": (
            "All numerical outputs and arrays are finite numbers."
            if finite_ok
            else "NaN or Infinity detected in outputs."
        ),
    })
    if not finite_ok:
        errors.append("Output contains non-finite numerical values (NaN or Inf).")

    # 2. Required fields / keys check
    req_keys = contract.get("required_keys") or []
    if req_keys:
        if not isinstance(result, dict):
            checks.append({
                "name": "required_output_keys",
                "passed": False,
                "detail": f"Expected dict containing keys {req_keys}, got {type(result).__name__}.",
            })
            errors.append(f"Output must be a dictionary to satisfy required keys: {req_keys}")
        else:
            missing = [k for k in req_keys if k not in result]
            passed = len(missing) == 0
            checks.append({
                "name": "required_output_keys",
                "passed": passed,
                "detail": "All required output keys present." if passed else f"Missing required keys: {missing}",
            })
            if not passed:
                errors.append(f"Missing required output fields: {missing}")

    # 3. Array length checks
    exp_lengths = contract.get("expected_lengths") or {}
    for arr_name, exp_len in exp_lengths.items():
        arr = arrays.get(arr_name)
        if arr is None and isinstance(result, dict):
            arr = result.get(arr_name)
        if arr is not None and hasattr(arr, "__len__"):
            actual_len = len(arr)
            passed = actual_len == exp_len
            checks.append({
                "name": f"array_length_{arr_name}",
                "passed": passed,
                "detail": f"Array '{arr_name}' has exactly {actual_len} items (expected {exp_len}).",
            })
            if not passed:
                errors.append(f"Array '{arr_name}' length mismatch: {actual_len} != {exp_len}")
        else:
            checks.append({
                "name": f"array_presence_{arr_name}",
                "passed": False,
                "detail": f"Array '{arr_name}' was not produced.",
            })
            errors.append(f"Required array '{arr_name}' was not produced.")

    # 4. Standard error check (must be numeric, finite, and >= 0)
    if isinstance(result, dict) and "standard_error" in result:
        se_raw = result["standard_error"]
        try:
            se_val = float(se_raw)
            passed = math.isfinite(se_val) and se_val >= 0.0
            checks.append({
                "name": "non_negative_standard_error",
                "passed": passed,
                "detail": (
                    f"Standard error {se_val:.6g} >= 0."
                    if passed
                    else f"Standard error is negative or non-finite: {se_raw}"
                ),
            })
            if not passed:
                errors.append(f"Invalid or negative standard error: {se_raw}")
        except (ValueError, TypeError):
            checks.append({
                "name": "non_negative_standard_error",
                "passed": False,
                "detail": f"Standard error is non-numeric: {se_raw!r}",
            })
            errors.append(f"Standard error is non-numeric: {se_raw!r}")

    # 5. Independent Analytical Reference Comparison
    analytical_ref = contract.get("analytical_reference")
    if analytical_ref:
        if not isinstance(result, dict):
            checks.append({
                "name": "analytical_reference",
                "passed": False,
                "detail": f"Result must be a dict for analytical verification, got {type(result).__name__}.",
            })
            errors.append("Analytical reference comparison requires dict output.")
        else:
            ref_kind = str(analytical_ref.get("kind") or "")
            if ref_kind == "oscillator_rk4":
                try:
                    import scipy.linalg as la

                    m = float(analytical_ref.get("m", 2.0))
                    c = float(analytical_ref.get("c", 0.6))
                    k = float(analytical_ref.get("k", 8.0))
                    t_end = float(analytical_ref.get("t_end", 2.0))
                    x0 = float(analytical_ref.get("x0", 0.05))
                    v0 = float(analytical_ref.get("v0", 0.0))
                    tol = float(analytical_ref.get("tolerance", 1e-6))

                    A = np.array([[0.0, 1.0], [-k / m, -c / m]], dtype=np.float64)
                    y_exact = la.expm(A * t_end) @ np.array([x0, v0], dtype=np.float64)
                    exact_x, exact_v = float(y_exact[0]), float(y_exact[1])

                    num_x = float(result.get("x_end", result.get("x", 0.0)))
                    num_v = float(result.get("v_end", result.get("v", 0.0)))
                    err_x = abs(num_x - exact_x)
                    err_v = abs(num_v - exact_v)

                    passed = err_x <= tol and err_v <= tol
                    checks.append({
                        "name": "oscillator_analytical_reference",
                        "passed": passed,
                        "detail": (
                            f"Discrepancy: dx={err_x:.3e} m, dv={err_v:.3e} m/s against matrix-exponential "
                            f"reference (x_ref={exact_x:.6f}, v_ref={exact_v:.6f}, tol={tol:.1e})."
                        ),
                    })
                    if not passed:
                        errors.append(
                            f"Analytical endpoint discrepancy exceeds tolerance: dx={err_x:.3e}, dv={err_v:.3e}"
                        )
                except Exception as exc:
                    checks.append({
                        "name": "oscillator_analytical_reference",
                        "passed": False,
                        "detail": f"Analytical oscillator evaluation failed: {exc}",
                    })
                    errors.append(f"Analytical oscillator calculation error: {exc}")
            elif ref_kind == "rc_charging":
                try:
                    v0 = float(analytical_ref.get("v0", 5.0))
                    r = float(analytical_ref.get("r", 1000.0))
                    c = float(analytical_ref.get("c", 1e-3))
                    t_end = float(analytical_ref.get("t_end", 5.0))
                    tol = float(analytical_ref.get("tolerance", 1e-4))
                    exact_v = v0 * (1.0 - math.exp(-t_end / (r * c)))
                    num_v = float(result.get("v_end", result.get("v", 0.0)))
                    err_v = abs(num_v - exact_v)
                    passed = err_v <= tol
                    checks.append({
                        "name": "rc_charging_analytical_reference",
                        "passed": passed,
                        "detail": (
                            f"Discrepancy: dv={err_v:.3e} V against RC formula "
                            f"(v_ref={exact_v:.6f}, tol={tol:.1e})."
                        ),
                    })
                    if not passed:
                        errors.append(f"Analytical RC discrepancy exceeds tolerance: dv={err_v:.3e}")
                except Exception as exc:
                    checks.append({
                        "name": "rc_charging_analytical_reference",
                        "passed": False,
                        "detail": f"Analytical RC evaluation failed: {exc}",
                    })
                    errors.append(f"Analytical RC calculation error: {exc}")
            else:
                checks.append({
                    "name": "analytical_reference",
                    "passed": False,
                    "detail": f"Unsupported or unavailable analytical reference kind: {ref_kind!r}",
                })
                errors.append(f"Unsupported analytical reference kind: {ref_kind!r}")

    # 6. Expected RHS evaluations and step counts (an endpoint match alone is not enough)
    if "expected_rhs_evaluations" in contract:
        exp_rhs = contract["expected_rhs_evaluations"]
        act_rhs = result.get("rhs_evaluations") if isinstance(result, dict) else None
        passed = act_rhs == exp_rhs
        checks.append({
            "name": "expected_rhs_evaluations",
            "passed": passed,
            "detail": f"RHS evaluations: {act_rhs} (expected {exp_rhs}).",
        })
        if not passed:
            errors.append(f"RHS evaluations mismatch: {act_rhs} != {exp_rhs}")

    # 7. Initial conditions verification
    if "initial_conditions" in contract and isinstance(result, dict):
        init_conds = contract["initial_conditions"]
        for k, exp_val in init_conds.items():
            act_val = result.get(k)
            if act_val is None and k in arrays and len(arrays[k]) > 0:
                act_val = arrays[k][0]
            passed = act_val is not None and abs(float(act_val) - float(exp_val)) <= 1e-9
            checks.append({
                "name": f"initial_condition_{k}",
                "passed": passed,
                "detail": f"Initial condition {k}: {act_val} (expected {exp_val}).",
            })
            if not passed:
                errors.append(f"Initial condition mismatch for {k}: {act_val} != {exp_val}")

    overall_passed = len(errors) == 0 and all(c["passed"] for c in checks)
    return {
        "passed": overall_passed,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }


def attempt_code_repair(code: str, error_msg: str, stderr: str) -> tuple[str | None, str | None]:
    """
    Attempt exactly one targeted repair for clearly repairable syntax or import errors.
    Returns (repaired_code, reason) if repair was made, else (None, None).
    """
    combined_err = f"{error_msg}\n{stderr}"

    # Case 1: Missing standard scientific import
    m_name = re.search(r"NameError:\s+name\s+'([A-Za-z0-9_]+)'\s+is\s+not\s+defined", combined_err)
    if m_name:
        missing_var = m_name.group(1)
        import_map = {
            "np": "import numpy as np",
            "numpy": "import numpy",
            "pd": "import pandas as pd",
            "pandas": "import pandas",
            "sp": "import sympy as sp",
            "sympy": "import sympy",
            "plt": "import matplotlib.pyplot as plt",
            "scipy": "import scipy",
            "math": "import math",
        }
        if missing_var in import_map:
            import_line = import_map[missing_var]
            if import_line not in code:
                repaired = f"{import_line}\n" + code
                return repaired, f"Injected missing standard scientific import '{import_line}'."

    # Case 2: IndentationError / unexpected EOF syntax error on trailing unclosed delimiters
    if "SyntaxError: unexpected EOF while parsing" in combined_err or "SyntaxError: invalid syntax" in combined_err or "unexpected EOF" in combined_err or "syntax error" in combined_err.lower():
        open_parens = code.count("(") - code.count(")")
        open_brackets = code.count("[") - code.count("]")
        open_braces = code.count("{") - code.count("}")
        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
            closing = ")" * max(0, open_parens) + "]" * max(0, open_brackets) + "}" * max(0, open_braces)
            repaired = code.rstrip() + closing + "\n"
            return repaired, f"Closed unclosed delimiters: '{closing}'."

    return None, None


def build_reproducibility_bundle(
    request: ExecutionJobRequest,
    result: Any,
    stdout: str,
    stderr: str,
    numerical_arrays: dict[str, Any],
    figures: list[dict[str, Any]],
    runtime_info: dict[str, Any],
    validation_report: dict[str, Any],
    repaired_code: str | None = None,
    repair_reason: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Generate downloadable reproducibility zip archive and export files with
    correct Base64 encoding, full IEEE-754 precision, and repair provenance.
    """
    downloads: list[dict[str, Any]] = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Executed and original script provenance
        executed_code = repaired_code if repaired_code is not None else request.code
        zf.writestr("executed_script.py", executed_code)
        if repaired_code is not None:
            zf.writestr("original_script.py", request.code)
            repair_meta = {
                "repaired": True,
                "repair_reason": repair_reason,
                "original_source_hash": hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
                "executed_source_hash": hashlib.sha256(executed_code.encode("utf-8")).hexdigest(),
            }
            zf.writestr("repair_log.json", json.dumps(repair_meta, indent=2))
        else:
            zf.writestr("repair_log.json", json.dumps({"repaired": False}, indent=2))

        # 2. Inputs & parameters manifest
        inputs_manifest = {
            "job_id": request.job_id,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "user_id": request.user_id,
            "project_id": request.project_id,
            "parameters": request.parameters,
            "source_hash": hashlib.sha256(executed_code.encode("utf-8")).hexdigest(),
        }
        zf.writestr("inputs.json", json.dumps(inputs_manifest, indent=2, default=str))

        # 3. Execution results
        results_data = {
            "result": result,
            "stdout": stdout,
            "stderr": stderr,
            "validation": validation_report,
        }
        zf.writestr("results.json", json.dumps(results_data, indent=2, default=str))

        # 4. Numerical arrays CSV with full IEEE-754 precision (17 significant figures)
        if numerical_arrays:
            max_len = max((len(v) for v in numerical_arrays.values() if hasattr(v, "__len__")), default=0)
            if max_len > 0:
                cols = [k for k, v in numerical_arrays.items() if hasattr(v, "__len__") and len(v) == max_len]
                csv_lines = [",".join(cols)]
                for i in range(max_len):
                    row_vals = [f"{float(numerical_arrays[c][i]):.17g}" for c in cols]
                    csv_lines.append(",".join(row_vals))
                csv_text = "\n".join(csv_lines)
                zf.writestr("numerical_trajectory.csv", csv_text)

                downloads.append({
                    "name": f"{request.task_id}_trajectory.csv",
                    "content": csv_text,
                    "mime": "text/csv",
                    "meta": f"CSV • {max_len} rows • {len(csv_text)} B",
                })

        # 5. Figures
        for idx, fig in enumerate(figures, start=1):
            name = fig.get("name") or f"figure_{idx}.png"
            if "png_base64" in fig:
                try:
                    png_bytes = base64.b64decode(fig["png_base64"])
                    zf.writestr(f"figures/{name}", png_bytes)
                except Exception:
                    pass
            if fig.get("svg"):
                zf.writestr(f"figures/{Path(name).stem}.svg", fig["svg"])

        # 6. Runtime manifest
        zf.writestr("runtime_manifest.json", json.dumps(runtime_info, indent=2, default=str))

    zip_bytes = zip_buffer.getvalue()
    bundle_hash = hashlib.sha256(zip_bytes).hexdigest()[:16]
    bundle_name = f"{request.task_id}_reproducibility_bundle.zip"
    b64_content = base64.b64encode(zip_bytes).decode("ascii")

    downloads.append({
        "name": bundle_name,
        "bytes": len(zip_bytes),
        "content_base64": b64_content,
        "mime": "application/zip",
        "meta": f"ZIP • {len(zip_bytes)} B • SHA-256: {bundle_hash}",
    })

    bundle_info = {
        "filename": bundle_name,
        "byte_size": len(zip_bytes),
        "sha256": bundle_hash,
    }
    return bundle_info, downloads


def is_stochastic_request(request: ExecutionJobRequest) -> bool:
    """Return True if execution has stochastic behavior without an explicit seed."""
    if request.output_contract.get("stochastic") or request.output_contract.get("skip_cache"):
        return True
    code = request.code
    params = request.parameters
    has_random = bool(re.search(r"\b(random\.|np\.random\.|scipy\.stats)\b", code))
    if has_random:
        has_seed_in_code = bool(re.search(r"\b(seed\s*\(|RandomState\s*\(|default_rng\s*\([0-9]+)", code))
        has_seed_in_params = "seed" in params or "random_seed" in params
        if not (has_seed_in_code or has_seed_in_params):
            return True
    return False


class PythonExecutionWorker:
    """
    Manages isolated scientific Python execution worker jobs with bounded concurrency,
    caching scoped by user/project/contract, output validation, and reproducibility bundles.
    """

    def __init__(
        self,
        concurrency: int | None = None,
        timeout_s: float | None = None,
        memory_mb: int | None = None,
        cache_dir: str | Path | None = None,
        container_engine: str | None = None,
    ) -> None:
        self.concurrency = concurrency or get_int("TRIBOS_PYTHON_WORKER_CONCURRENCY", WORKER_CONCURRENCY_DEFAULT)
        self.timeout_s = timeout_s or get_float("TRIBOS_PYTHON_WORKER_TIMEOUT_S", float(WORKER_TIMEOUT_S_DEFAULT))
        self.memory_mb = memory_mb or get_int("TRIBOS_PYTHON_WORKER_MEMORY_MB", WORKER_MEMORY_MB_DEFAULT)
        self.container_engine = container_engine or get_str("TRIBOS_PYTHON_WORKER_CONTAINER_ENGINE", "auto")
        self._thread_pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="tribos-worker")
        self._cache: OrderedDict[str, ExecutionJobResult] = OrderedDict()
        self._cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "tribos_worker_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._active_procs: dict[str, Any] = {}
        self._pending_count = 0
        self._lock = threading.Lock()

        # Engine validation
        self.isolation_available, self.isolation_label = check_container_engine(self.container_engine)
        self._runtime_info = get_runtime_metadata(isolation=self.isolation_label)

    def _compute_cache_key(self, request: ExecutionJobRequest, input_content_hashes: dict[str, str]) -> str:
        code_h = hashlib.sha256(request.code.strip().encode("utf-8")).hexdigest()
        params_h = hashlib.sha256(
            json.dumps(request.parameters, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        contract_h = hashlib.sha256(
            json.dumps(request.output_contract, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        inputs_h = hashlib.sha256(
            ":".join(f"{k}={v}" for k, v in sorted(input_content_hashes.items())).encode("utf-8")
        ).hexdigest()
        digest = self._runtime_info["runtime_digest"]
        # Explicit scope separation: user_id, project_id, code, params, inputs, contract, digest
        raw_key = f"{request.user_id}:{request.project_id}:{code_h}:{params_h}:{inputs_h}:{contract_h}:{digest}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def cancel_job(self, job_id: str) -> bool:
        """Cancel an actively executing job by terminating its process tree."""
        with self._lock:
            proc = self._active_procs.get(job_id)
        if proc is not None:
            _kill_tree(proc)
            return True
        return False

    def shutdown(self, wait: bool = True, cancel_futures: bool = True) -> None:
        """Cleanly terminate running child process trees and shut down thread pool."""
        with self._lock:
            for _jid, proc in list(self._active_procs.items()):
                if proc is not None:
                    _kill_tree(proc)
            self._active_procs.clear()
        self._thread_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    def execute_job_sync(self, request: ExecutionJobRequest) -> ExecutionJobResult:
        """Synchronous job execution entry point for extension tools."""
        return self._execute_sync(request)

    async def execute_job(self, request: ExecutionJobRequest) -> ExecutionJobResult:
        """Asynchronous execution entry point running outside the main event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._thread_pool, self._execute_sync, request)

    def _execute_sync(self, request: ExecutionJobRequest) -> ExecutionJobResult:
        t0 = time.perf_counter()

        with self._lock:
            if self._pending_count >= MAX_PENDING_JOBS:
                return ExecutionJobResult(
                    job_id=request.job_id,
                    task_id=request.task_id,
                    run_id=request.run_id,
                    user_id=request.user_id,
                    project_id=request.project_id,
                    status="overloaded",
                    exit_code=1,
                    source_hash=hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
                    input_hashes={},
                    runtime_versions=self._runtime_info["versions"],
                    runtime_digest=self._runtime_info["runtime_digest"],
                    isolation=self.isolation_label,
                    start_time=t0,
                    end_time=time.perf_counter(),
                    elapsed_seconds=0.0,
                    error=f"Worker queue limit exceeded ({MAX_PENDING_JOBS} jobs pending).",
                )
            self._pending_count += 1

        try:
            # Check container engine requirement
            if self.container_engine.strip().lower() in ("docker", "podman") and not self.isolation_available:
                return ExecutionJobResult(
                    job_id=request.job_id,
                    task_id=request.task_id,
                    run_id=request.run_id,
                    user_id=request.user_id,
                    project_id=request.project_id,
                    status="unavailable",
                    exit_code=1,
                    source_hash=hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
                    input_hashes={},
                    runtime_versions=self._runtime_info["versions"],
                    runtime_digest=self._runtime_info["runtime_digest"],
                    isolation=self.isolation_label,
                    start_time=t0,
                    end_time=time.perf_counter(),
                    elapsed_seconds=0.0,
                    error=f"Container isolation '{self.container_engine}' was requested but is not available on host.",
                )

            # Resolve input files & calculate actual content hashes
            input_files: dict[str, str] = dict(request.input_files)
            input_hashes: dict[str, str] = {}

            for art_id in request.input_artifact_ids:
                if "/" in art_id or "\\" in art_id or ".." in art_id:
                    raise ValueError(f"Invalid input artifact identifier: {art_id}")
                art_path = self._cache_dir / art_id
                if art_path.is_file():
                    input_files[art_id] = str(art_path)

            for name, path_str in sorted(input_files.items()):
                p = Path(path_str)
                if p.is_file():
                    try:
                        input_hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
                    except OSError:
                        input_hashes[name] = "unreadable"
                else:
                    input_hashes[name] = "missing"

            cache_key = self._compute_cache_key(request, input_hashes)
            stochastic = is_stochastic_request(request)

            # Check cache hit (unless fresh execution or stochastic run)
            if not request.fresh_execution and not stochastic:
                with self._lock:
                    cached = self._cache.get(cache_key)
                if cached is not None:
                    logger.info("Exact cache hit for job %s (original %s)", request.job_id, cached.job_id)
                    hit = copy.deepcopy(cached)
                    hit.job_id = request.job_id
                    hit.task_id = request.task_id
                    hit.run_id = request.run_id
                    hit.reused = True
                    hit.reused_from_job_id = cached.job_id
                    hit.start_time = t0
                    hit.end_time = time.perf_counter()
                    hit.elapsed_seconds = 0.001
                    return hit

            source_code = request.code
            source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
            effective_timeout = min(request.timeout_s, self.timeout_s)
            effective_mem = min(request.memory_mb, self.memory_mb)

            def _on_spawn(proc: Any) -> None:
                with self._lock:
                    self._active_procs[request.job_id] = proc

            t_exec_start = time.perf_counter()
            # The gateway owns the permission, policy, limit and backend decisions for every run, so the
            # worker never talks to a backend directly.
            report = _gateway_execute(
                source_code,
                input_files=input_files,
                timeout_s=effective_timeout,
                memory_mb=effective_mem,
                data=request.parameters or None,
                on_spawn=_on_spawn,
            )

            repaired_code = None
            repair_reason = None
            status = report.get("status", "error")

            # Targeted code repair on failure
            if status != "ok" and request.allow_repair:
                violations_msg = "\n".join(report.get("violations") or [])
                err_text = f"{report.get('error') or ''}\n{violations_msg}".strip()
                rep_code, rep_reason = attempt_code_repair(
                    source_code, err_text, report.get("stderr") or ""
                )
                if rep_code is not None:
                    logger.info("Attempting single targeted repair for job %s: %s", request.job_id, rep_reason)
                    rep_report = _gateway_execute(
                        rep_code,
                        input_files=input_files,
                        timeout_s=effective_timeout,
                        memory_mb=effective_mem,
                        data=request.parameters or None,
                    )
                    if rep_report.get("status") == "ok":
                        report = rep_report
                        source_code = rep_code
                        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
                        status = "repaired"
                        repaired_code = rep_code
                        repair_reason = rep_reason

            t_exec_end = time.perf_counter()
            exec_time = round(t_exec_end - t_exec_start, 4)

            raw_result = report.get("result")
            stdout = report.get("stdout", "")
            stderr = report.get("stderr", "")
            tables = report.get("tables", [])
            figures = report.get("figures", [])

            # Extract numerical arrays from result
            numerical_arrays: dict[str, Any] = {}
            if isinstance(raw_result, dict):
                for k, v in raw_result.items():
                    if isinstance(v, (list, tuple)) and all(isinstance(x, (int, float)) for x in v):
                        numerical_arrays[k] = [float(x) for x in v]
                    elif isinstance(v, dict) and all(isinstance(x, (int, float)) for x in v.values()):
                        numerical_arrays[k] = [float(x) for x in v.values()]

            # Independent output validation
            t_val_start = time.perf_counter()
            validation_report = validate_execution_outputs(
                result=raw_result,
                contract=request.output_contract,
                numerical_arrays=numerical_arrays,
                context={"parameters": request.parameters},
            )
            t_val_end = time.perf_counter()
            val_time = round(t_val_end - t_val_start, 4)

            final_status = "completed" if (status in ("ok", "repaired") and validation_report["passed"]) else (
                "failed_validation" if status in ("ok", "repaired") else status
            )
            exit_code = 0 if status in ("ok", "repaired") else 1

            # Build reproducibility bundle
            t_bnd_start = time.perf_counter()
            bundle_info, downloads = build_reproducibility_bundle(
                request=request,
                result=raw_result,
                stdout=stdout,
                stderr=stderr,
                numerical_arrays=numerical_arrays,
                figures=figures,
                runtime_info=self._runtime_info,
                validation_report=validation_report,
                repaired_code=repaired_code,
                repair_reason=repair_reason,
            )
            t_bnd_end = time.perf_counter()
            bnd_time = round(t_bnd_end - t_bnd_start, 4)

            t1 = time.perf_counter()
            elapsed = round(t1 - t0, 4)

            job_result = ExecutionJobResult(
                job_id=request.job_id,
                task_id=request.task_id,
                run_id=request.run_id,
                user_id=request.user_id,
                project_id=request.project_id,
                status=final_status,
                exit_code=exit_code,
                source_hash=source_hash,
                input_hashes=input_hashes,
                runtime_versions=self._runtime_info["versions"],
                runtime_digest=self._runtime_info["runtime_digest"],
                isolation=self.isolation_label,
                start_time=t0,
                end_time=t1,
                elapsed_seconds=elapsed,
                timings={
                    "execution_s": exec_time,
                    "validation_s": val_time,
                    "bundle_s": bnd_time,
                },
                stdout=stdout,
                stderr=stderr,
                result=raw_result,
                numerical_arrays=numerical_arrays,
                tables=tables,
                figures=figures,
                downloads=downloads,
                reproducibility_bundle=bundle_info,
                validation_report=validation_report,
                repaired_code=repaired_code,
                repair_reason=repair_reason,
                reused=False,
                error=report.get("error") or ("; ".join(validation_report["errors"]) if validation_report.get("errors") else None),
            )

            # Cache successful, valid executions (unless stochastic)
            if final_status == "completed" and not stochastic:
                with self._lock:
                    if len(self._cache) >= CACHE_CAPACITY:
                        self._cache.popitem(last=False)
                    self._cache[cache_key] = copy.deepcopy(job_result)

            return job_result

        finally:
            with self._lock:
                self._active_procs.pop(request.job_id, None)
                self._pending_count = max(0, self._pending_count - 1)


_WORKER_INSTANCE: PythonExecutionWorker | None = None


def get_python_worker() -> PythonExecutionWorker:
    """Singleton getter for Python execution worker."""
    global _WORKER_INSTANCE
    if _WORKER_INSTANCE is None:
        _WORKER_INSTANCE = PythonExecutionWorker()
    return _WORKER_INSTANCE
