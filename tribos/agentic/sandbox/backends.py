"""
The backends the execution gateway can dispatch to.

A backend owns *how* model-written code runs; it does not decide *whether* it may run. That decision belongs to the
gateway (gateway.py), so every execution path — the analyst phase, the planner's plan DAG, a direct registry tool
call, SageMath — passes through the same enable/disable check, the same policy check and the same limits.

Three backends exist:

- SubprocessBackend: the current runner.py child process. Strong defence in depth, but it shares the server's
  trust domain: native code inside an allowed package can bypass the Python-level guards.
- ContainerBackend: the same bootstrap inside a hardened container. This is the actual security boundary.
- SageBackend: the SageMath interpreter, which needs its own command discovery and figure harvesting but the same
  policy, limits and permission checks.

No backend is allowed to raise the server's ceilings: a caller's request may only lower them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# The engines the gateway knows.
ENGINE_PYTHON = "python"
ENGINE_SAGE = "sage"

# The policy profile each engine is checked against.
PROFILE_ANALYSIS = "analysis"
PROFILE_SAGE = "sage"


@dataclass
class ExecutionRequest:
    """One request to execute model-written code."""

    code: str
    engine: str = ENGINE_PYTHON
    profile: str = PROFILE_ANALYSIS
    input_files: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] | None = None
    timeout_s: float | None = None
    memory_mb: int | None = None
    max_output_kb: int | None = None
    max_disk_mb: int | None = None
    max_processes: int | None = None
    max_figures: int | None = None
    on_spawn: Any = None


class ExecutionBackend(Protocol):
    """What every backend must offer the gateway."""

    name: str

    def supports(self, engine: str) -> bool:
        """True when this backend can run the given engine."""
        ...

    def run(self, request: ExecutionRequest) -> dict[str, Any]:
        """Execute the request and return the backend's structured report."""
        ...


def empty_report(status: str, error: str | None, **extra: Any) -> dict[str, Any]:
    """The report shape every backend returns (the same contract runner.py has always used)."""
    out: dict[str, Any] = {
        "status": status,
        "stdout": "",
        "stderr": "",
        "result": None,
        "figures": [],
        "tables": [],
        "seconds": 0.0,
        "error": error,
        "violations": [],
        "limits": {},
    }
    out.update(extra)
    return out


class SubprocessBackend:
    """Runs model-written Python in the current runner.py child process."""

    name = "subprocess"

    def supports(self, engine: str) -> bool:
        return engine == ENGINE_PYTHON

    def run(self, request: ExecutionRequest) -> dict[str, Any]:
        from .runner import run_code

        return run_code(
            request.code,
            input_files=dict(request.input_files),
            timeout_s=float(request.timeout_s or 60),
            max_output_kb=int(request.max_output_kb or 256),
            memory_mb=int(request.memory_mb or 2048),
            max_figures=int(request.max_figures if request.max_figures is not None else 6),
            data=request.data,
            on_spawn=request.on_spawn,
            max_disk_mb=int(request.max_disk_mb or 256),
            max_processes=int(request.max_processes or 64),
        )


class SageBackend:
    """Runs model-written SageMath in the hardened SageMath runner."""

    name = "sage"

    def supports(self, engine: str) -> bool:
        return engine == ENGINE_SAGE

    def run(self, request: ExecutionRequest) -> dict[str, Any]:
        from tribos.axiom.sagemath import run_sagemath_code

        report = run_sagemath_code(
            request.code,
            timeout_s=int(request.timeout_s or 120),
            memory_mb=int(request.memory_mb or 2048),
            max_output_kb=int(request.max_output_kb or 256),
        )
        # The Sage report uses its own key names; normalise them to the shared contract.
        return {
            "status": report.get("status", "error"),
            "stdout": report.get("stdout", ""),
            "stderr": report.get("stderr", ""),
            "result": report.get("result"),
            "figures": report.get("figures") or [],
            "tables": report.get("tables") or [],
            "seconds": float(report.get("execution_time_seconds", 0.0) or 0.0),
            "error": report.get("error"),
            "violations": report.get("violations") or [],
            "limits": report.get("limits") or {},
            "failure_class": report.get("failure_class"),
            "canonical_id": report.get("canonical_id", ""),
        }


__all__ = [
    "ENGINE_PYTHON",
    "ENGINE_SAGE",
    "ExecutionBackend",
    "ExecutionRequest",
    "PROFILE_ANALYSIS",
    "PROFILE_SAGE",
    "SageBackend",
    "SubprocessBackend",
    "empty_report",
]
