"""
The single execution gateway for model-written code.

Every path that can run code the model wrote goes through `execute()`:

- the analyst phase's CodeAct loop (tribos/agentic/analyst.py),
- the planner's plan DAG (tribos/agentic/executor.py -> calcula_run_python),
- a direct registry tool call (calcula_run_python, analysis_run_python),
- SageMath (axiom_sagemath, calcula_run_sagemath).

The gateway owns, in this order:

1. **Permission.** The server-wide switch (TRIBOS_SANDBOX) and the per-request switch (the "Allow code analysis on
   datasets" option) must both allow execution. When either forbids it, no backend is called.
2. **Policy.** The AST policy (policy.py) rejects the code before anything runs.
3. **Limits.** The effective timeout, memory, output, disk and process caps are resolved from the caller's request
   and the server's settings. A caller may only lower a limit, never raise it.
4. **Backend selection.** The configured backend (subprocess, container, or auto) runs the code.
5. **Audit.** One structured log line per execution: engine, backend, limits, status and duration. Never the code,
   never a secret.

This module is the reason the system is a sandbox rather than a set of parallel code paths: there is one place where
"may this run?" is decided, and every execution path must answer it there first.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .backends import (
    ENGINE_PYTHON,
    ENGINE_SAGE,
    PROFILE_ANALYSIS,
    PROFILE_SAGE,
    ExecutionRequest,
    SageBackend,
    SubprocessBackend,
    empty_report,
)
from .policy import check_code

logger = logging.getLogger(__name__)

# The report status values the tools understand.
STATUS_DISABLED = "disabled"
STATUS_FORBIDDEN = "forbidden"
STATUS_POLICY_VIOLATION = "policy_violation"
STATUS_FAILED = "failed"
STATUS_BUSY = "busy"


def _limits_for(engine: str, request: ExecutionRequest) -> dict[str, Any]:
    """The effective limits: the caller's request may only lower the server's ceilings."""
    from . import (
        sagemath_timeout_s,
        sandbox_max_disk_mb,
        sandbox_max_output_kb,
        sandbox_max_processes,
        sandbox_memory_mb,
        sandbox_timeout_s,
    )

    if engine == ENGINE_SAGE:
        server_timeout = float(sagemath_timeout_s())
    else:
        server_timeout = float(sandbox_timeout_s())
    requested_timeout = float(request.timeout_s) if request.timeout_s is not None else server_timeout
    effective_timeout = max(1.0, min(requested_timeout, server_timeout))

    server_memory = int(sandbox_memory_mb())
    effective_memory = min(int(request.memory_mb), server_memory) if request.memory_mb else server_memory

    server_output = int(sandbox_max_output_kb())
    effective_output = min(int(request.max_output_kb), server_output) if request.max_output_kb else server_output

    server_disk = int(sandbox_max_disk_mb())
    effective_disk = min(int(request.max_disk_mb), server_disk) if request.max_disk_mb else server_disk

    server_processes = int(sandbox_max_processes())
    effective_processes = (
        min(int(request.max_processes), server_processes) if request.max_processes else server_processes
    )
    return {
        "timeout_s": effective_timeout,
        "memory_mb": effective_memory,
        "max_output_kb": effective_output,
        "max_disk_mb": effective_disk,
        "max_processes": effective_processes,
    }


def _select_backend(engine: str) -> tuple[Any | None, str | None]:
    """The backend that will run this engine, and why it cannot (None, reason)."""
    from . import sandbox_allow_unisolated, sandbox_backend, sandbox_strict_limits

    if engine == ENGINE_SAGE:
        # SageMath has its own interpreter and command discovery; the container backend does not carry it yet, so it
        # runs without an OS-level boundary and strict isolation refuses it like the subprocess backend (AUDIT-103).
        if sandbox_strict_limits() and not sandbox_allow_unisolated():
            return None, ("the sandbox is configured for strict isolation, and SageMath runs without an OS-level "
                          "boundary (the container backend does not carry it); set TRIBOS_SANDBOX_ALLOW_UNISOLATED=1")
        return SageBackend(), None

    backend_name = sandbox_backend()
    if backend_name == "subprocess":
        if sandbox_strict_limits() and not sandbox_allow_unisolated():
            return None, (
                "the sandbox is configured for strict isolation, but the subprocess backend is not an "
                "OS-level boundary; install a container runtime or set TRIBOS_SANDBOX_ALLOW_UNISOLATED=1"
            )
        return SubprocessBackend(), None

    from .container import ContainerBackend, container_available

    if backend_name == "container":
        ok, reason = container_available()
        if not ok:
            return None, f"the container backend is not available: {reason}"
        return ContainerBackend(), None

    # auto: container when it is usable, subprocess otherwise.
    ok, _reason = container_available()
    if ok:
        return ContainerBackend(), None
    if sandbox_strict_limits() and not sandbox_allow_unisolated():
        return None, (
            "no OS-level isolation backend is available and the sandbox is configured for strict isolation; "
            "install a container runtime or set TRIBOS_SANDBOX_ALLOW_UNISOLATED=1"
        )
    _warn_unisolated(_reason)
    return SubprocessBackend(), None


_UNISOLATED_WARNED = False


def _warn_unisolated(reason: str | None) -> None:
    """Say once, loudly, that model-written code is running without an OS-level boundary (AUDIT-008)."""
    global _UNISOLATED_WARNED
    if not _UNISOLATED_WARNED:
        _UNISOLATED_WARNED = True
        logger.warning(
            "Sandbox: no container runtime (%s); model-written code runs in the subprocess backend, which is NOT an "
            "OS-level isolation boundary. Set TRIBOS_SANDBOX_STRICT_LIMITS=1 to refuse execution instead.", reason
        )


def isolation_status() -> dict[str, object]:
    """Which backend auto/explicit selection would use now, and whether it is an OS-level boundary."""
    backend, reason = _select_backend(ENGINE_PYTHON)
    name = getattr(backend, "name", None)
    return {"backend": name, "os_isolated": name == "container", "refused_reason": reason}


def _payload_bytes(report: dict[str, Any]) -> int:
    """Rough size of a report's payload (result, tables and figures)."""
    total = 0
    for figure in report.get("figures") or []:
        if isinstance(figure, dict):
            total += len(str(figure.get("png_base64") or "")) + len(str(figure.get("svg") or ""))
    for table in report.get("tables") or []:
        total += len(str(table))
    total += len(str(report.get("result")))
    return total


def execute(
    code: str,
    *,
    engine: str = ENGINE_PYTHON,
    input_files: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout_s: float | None = None,
    memory_mb: int | None = None,
    max_output_kb: int | None = None,
    max_disk_mb: int | None = None,
    max_processes: int | None = None,
    max_figures: int | None = None,
    on_spawn: Any = None,
) -> dict[str, Any]:
    """
    Execute one cell of model-written code under the sandbox policy.

    Returns the shared report contract: {status, stdout, stderr, result, figures, tables, seconds, error,
    violations, limits}. The status is one of ok|error|timeout|policy_violation|failed|disabled|forbidden|busy.
    """
    from . import (
        execution_permitted_now,
        sagemath_enabled,
        sandbox_enabled,
        sandbox_max_result_bytes,
    )

    started = time.perf_counter()

    # 1. Permission: the server-wide switch, then the per-request switch.
    if not sandbox_enabled():
        return empty_report(STATUS_DISABLED, "Code execution is disabled on this server (TRIBOS_SANDBOX=off).")
    if engine == ENGINE_SAGE and not sagemath_enabled():
        return empty_report(STATUS_DISABLED, "SageMath execution is disabled on this server.")
    if not execution_permitted_now():
        return empty_report(
            STATUS_FORBIDDEN,
            "Code execution is disabled for this request (the 'Allow code analysis on datasets' option is off).",
        )

    # 2. Policy: the AST check, against the engine's profile.
    profile = PROFILE_SAGE if engine == ENGINE_SAGE else PROFILE_ANALYSIS
    inputs = dict(input_files or {})
    violations = check_code(code, inputs.keys(), profile=profile)
    if violations:
        logger.info("Sandbox rejected %s code: %s policy violation(s)", engine, len(violations))
        return empty_report(
            STATUS_POLICY_VIOLATION,
            "the code was rejected by the sandbox policy",
            violations=violations,
        )

    # 3. Limits: the caller's request may only lower the server's ceilings.
    limits = _limits_for(engine, ExecutionRequest(code=code, engine=engine, timeout_s=timeout_s, memory_mb=memory_mb,
                                                  max_output_kb=max_output_kb, max_disk_mb=max_disk_mb,
                                                  max_processes=max_processes))
    request = ExecutionRequest(
        code=code,
        engine=engine,
        profile=profile,
        input_files=inputs,
        data=data,
        timeout_s=limits["timeout_s"],
        memory_mb=limits["memory_mb"],
        max_output_kb=limits["max_output_kb"],
        max_disk_mb=limits["max_disk_mb"],
        max_processes=limits["max_processes"],
        max_figures=max_figures,
        on_spawn=on_spawn,
    )

    # 4. Backend.
    backend, reason = _select_backend(engine)
    if backend is None:
        logger.warning("Sandbox refused to execute %s code: %s", engine, reason)
        return empty_report(STATUS_FAILED, reason)

    # 5. Dispatch and audit.
    try:
        report = backend.run(request)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sandbox backend %s failed: %s", backend.name, exc, exc_info=True)
        return empty_report(STATUS_FAILED, f"{type(exc).__name__}: {str(exc)[:200]}")

    report = dict(report or {})
    report.setdefault("status", STATUS_FAILED)
    report.setdefault("limits", {})
    # The effective limits are part of the report: the caller must be able to see what actually applied,
    # not only what the backend happened to report about the child.
    effective = dict(report["limits"] or {})
    effective.update(
        {
            "backend": backend.name,
            "os_isolated": backend.name == "container",
            "engine": engine,
            "timeout_s": limits["timeout_s"],
            "memory_mb": limits["memory_mb"],
            "max_output_kb": limits["max_output_kb"],
            "max_disk_mb": limits["max_disk_mb"],
            "max_processes": limits["max_processes"],
        }
    )
    report["limits"] = effective
    seconds = round(time.perf_counter() - started, 3)
    report["seconds"] = seconds

    max_result = int(sandbox_max_result_bytes())
    if _payload_bytes(report) > max_result:
        report["figures"] = []
        report["tables"] = []
        report["result"] = "<result payload exceeded the sandbox result size limit>"
        report["status"] = "error"
        report["error"] = "the result payload exceeded the sandbox result size limit"

    logger.info(
        "Sandbox execution: engine=%s backend=%s status=%s seconds=%.3f timeout_s=%s memory_mb=%s",
        engine,
        backend.name,
        report.get("status"),
        seconds,
        limits["timeout_s"],
        limits["memory_mb"],
    )
    return report


__all__ = [
    "STATUS_BUSY",
    "STATUS_DISABLED",
    "STATUS_FAILED",
    "STATUS_FORBIDDEN",
    "STATUS_POLICY_VIOLATION",
    "execute",
]
