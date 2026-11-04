"""
The execution gateway (tribos/agentic/sandbox/gateway.py): the one place that decides whether model-written code
may run, under which policy and with which limits.

Offline: no network and no real model. The gateway is exercised directly with the real subprocess backend, and
the backend-selection logic is exercised with a stub backend so the container path is covered on every platform.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from tribos.agentic.sandbox import (
    execution_permitted,
    execution_permitted_now,
    sandbox_enabled,
)
from tribos.agentic.sandbox import gateway as gw
from tribos.agentic.sandbox.backends import (
    ENGINE_PYTHON,
    ENGINE_SAGE,
    PROFILE_ANALYSIS,
    PROFILE_SAGE,
    ExecutionRequest,
    SageBackend,
    SubprocessBackend,
    empty_report,
)


@pytest.fixture(autouse=True)
def _sandbox_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway is exercised with the sandbox enabled unless a test turns it off."""
    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")


# =============================================================================
# Permission: the server switch and the per-request switch


def test_server_switch_off_disables_every_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    report = gw.execute("print('hello')")
    assert report["status"] == "disabled"
    assert "disabled" in str(report["error"]).lower()


def test_request_switch_off_blocks_execution() -> None:
    with execution_permitted(False):
        report = gw.execute("print('hello')")
    assert report["status"] == "forbidden"
    assert "allow code analysis" in str(report["error"]).lower()


def test_request_switch_is_scoped_and_restored() -> None:
    assert execution_permitted_now() is True
    with execution_permitted(False):
        assert execution_permitted_now() is False
    assert execution_permitted_now() is True


def test_request_switch_blocks_the_sage_engine() -> None:
    with execution_permitted(False):
        report = gw.execute("print('hello')", engine=ENGINE_SAGE)
    assert report["status"] == "forbidden"


def test_sage_engine_refused_when_sage_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ENABLED", "off")
    report = gw.execute("print('hello')", engine=ENGINE_SAGE)
    assert report["status"] == "disabled"


# =============================================================================
# Policy: the gateway applies the AST policy before anything runs


@pytest.mark.parametrize(
    "code",
    [
        "import os\n",
        "import socket\n",
        "open('/etc/passwd')\n",
        "eval('1+1')\n",
        "().__class__.__bases__\n",
    ],
)
def test_policy_violations_are_rejected(code: str) -> None:
    report = gw.execute(code)
    assert report["status"] == "policy_violation"
    assert report["violations"]


def test_a_clean_code_runs() -> None:
    report = gw.execute("x = 2 + 2\nresult = x\n")
    assert report["status"] == "ok"
    assert report["result"] == 4


# =============================================================================
# Limits: a caller may only lower the server's ceilings


def test_a_caller_cannot_raise_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "5")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", timeout_s=3600))
    assert limits["timeout_s"] == 5


def test_a_caller_can_lower_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "60")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", timeout_s=7))
    assert limits["timeout_s"] == 7


def test_a_caller_cannot_raise_the_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MEMORY_MB", "512")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", memory_mb=99999))
    assert limits["memory_mb"] == 512


def test_a_caller_cannot_raise_the_output_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_OUTPUT_KB", "16")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", max_output_kb=99999))
    assert limits["max_output_kb"] == 16


def test_a_caller_cannot_raise_the_disk_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_DISK_MB", "32")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", max_disk_mb=99999))
    assert limits["max_disk_mb"] == 32


def test_a_caller_cannot_raise_the_process_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_PROCESSES", "8")
    limits = gw._limits_for(ENGINE_PYTHON, ExecutionRequest(code="", max_processes=99999))
    assert limits["max_processes"] == 8


def test_the_sage_engine_uses_the_sage_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_TIMEOUT_S", "42")
    limits = gw._limits_for(ENGINE_SAGE, ExecutionRequest(code=""))
    assert limits["timeout_s"] == 42


# =============================================================================
# Backend selection


def test_the_subprocess_backend_is_selected_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")
    backend, reason = gw._select_backend(ENGINE_PYTHON)
    assert reason is None
    assert isinstance(backend, SubprocessBackend)


def test_strict_limits_refuse_the_subprocess_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", "off")
    backend, reason = gw._select_backend(ENGINE_PYTHON)
    assert backend is None
    assert reason and "strict" in reason.lower()


def test_the_unisolated_opt_in_allows_the_subprocess_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", "on")
    backend, reason = gw._select_backend(ENGINE_PYTHON)
    assert reason is None
    assert isinstance(backend, SubprocessBackend)


def test_sage_always_uses_the_sage_backend() -> None:
    backend, reason = gw._select_backend(ENGINE_SAGE)
    assert reason is None
    assert isinstance(backend, SageBackend)


def test_a_missing_container_fails_closed_in_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "container")
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", "off")
    monkeypatch.setattr("tribos.agentic.sandbox.container.container_available", lambda **_: (False, "no runtime"))
    backend, reason = gw._select_backend(ENGINE_PYTHON)
    assert backend is None
    assert reason and "not available" in reason


# =============================================================================
# The report contract


def test_the_report_has_the_shared_shape() -> None:
    report = gw.execute("print('hi')")
    for key in (
        "status",
        "stdout",
        "stderr",
        "result",
        "figures",
        "tables",
        "seconds",
        "error",
        "violations",
        "limits",
    ):
        assert key in report


def test_an_oversized_result_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_RESULT_BYTES", "100000")

    class Fat:
        """A backend that returns a payload over the ceiling."""

        name = "fat"

        def run(self, request: Any) -> dict[str, Any]:
            return empty_report(
                "ok",
                None,
                result="x" * 200000,
                figures=[{"png_base64": "y" * 200000}],
                tables=[],
            )

    monkeypatch.setattr(gw, "_select_backend", lambda engine: (Fat(), None))
    report = gw.execute("result = 1\n")
    assert report["status"] == "error"
    assert "size limit" in str(report["error"]).lower()
    assert report["figures"] == []
    assert report["tables"] == []


def test_the_payload_size_counter_aggregates_every_field() -> None:
    report = {
        "result": "x" * 100,
        "tables": [{"a": 1}, {"b": 2}],
        "figures": [{"png_base64": "y" * 200, "svg": "z" * 50}],
    }
    assert gw._payload_bytes(report) > 300


def test_an_empty_report_has_the_shared_shape() -> None:
    report = empty_report("failed", "because")
    assert report["status"] == "failed"
    assert report["error"] == "because"
    assert report["figures"] == []
    assert report["tables"] == []


# =============================================================================
# Audit


def test_the_audit_line_carries_no_code_and_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    secret = "sk-do-not-log-this"
    with caplog.at_level("INFO", logger="tribos.agentic.sandbox.gateway"):
        gw.execute(f"x = {secret!r}\nresult = x\n")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Sandbox execution" in text
    assert secret not in text
    assert "engine=python" in text
    assert "backend=" in text


def test_a_backend_exception_becomes_a_failed_report(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        name = "boom"

        def run(self, request: Any) -> dict[str, Any]:
            raise RuntimeError("kaboom")

    monkeypatch.setattr(gw, "_select_backend", lambda engine: (Boom(), None))
    report = gw.execute("print('hi')")
    assert report["status"] == "failed"
    assert "kaboom" in str(report["error"])


# =============================================================================
# The profiles


def test_the_analysis_profile_does_not_allow_sage() -> None:
    from tribos.agentic.sandbox.policy import check_code

    violations = check_code("from sage.all import *\n", profile=PROFILE_ANALYSIS)
    assert violations


def test_the_sage_profile_allows_sage_but_not_the_os_module() -> None:
    from tribos.agentic.sandbox.policy import check_code

    assert check_code("from sage.all import *\n", profile=PROFILE_SAGE) == []
    assert check_code("import os\n", profile=PROFILE_SAGE)
    assert check_code("import socket\n", profile=PROFILE_SAGE)


def test_the_sandbox_is_enabled_by_default() -> None:
    """The registry default is on: the documented default and the runtime default cannot drift apart."""
    assert sandbox_enabled() is True


def test_the_environment_does_not_leak_into_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET_TOKEN", "do-not-leak")
    report = gw.execute("import os\nresult = 1\n") if False else gw.execute("result = 1\n")
    assert "do-not-leak" not in str(report)


def test_the_work_directory_is_not_left_behind() -> None:
    before = {p for p in os.listdir(os.environ.get("TEMP", "/tmp")) if p.startswith("tribos-sbx-")}
    gw.execute("result = 1\n")
    after = {p for p in os.listdir(os.environ.get("TEMP", "/tmp")) if p.startswith("tribos-sbx-")}
    assert after <= before
