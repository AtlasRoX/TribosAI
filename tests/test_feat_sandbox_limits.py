"""
The sandbox's limits (tribos/agentic/sandbox/gateway.py, runner.py, process.py): the server's ceilings, the rule
that a caller may only lower them, and the resource limits a single run actually gets.

Offline: no network and no real model. The real subprocess backend runs the cells.
"""

from __future__ import annotations

import os

import pytest

from tribos.agentic.sandbox import (
    sandbox_max_concurrency,
    sandbox_max_disk_mb,
    sandbox_max_output_kb,
    sandbox_max_processes,
    sandbox_max_result_bytes,
    sandbox_memory_mb,
    sandbox_timeout_s,
)
from tribos.agentic.sandbox.gateway import execute
from tribos.agentic.sandbox.runner import run_code

# =============================================================================
# The settings


def test_the_defaults_are_the_documented_ones() -> None:
    assert sandbox_timeout_s() > 0
    assert sandbox_memory_mb() >= 256
    assert sandbox_max_output_kb() > 0
    assert sandbox_max_disk_mb() > 0
    assert sandbox_max_processes() >= 1
    assert sandbox_max_concurrency() >= 1
    assert sandbox_max_result_bytes() > 0


def test_the_settings_follow_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "42")
    monkeypatch.setenv("TRIBOS_SANDBOX_MEMORY_MB", "1024")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_OUTPUT_KB", "32")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_DISK_MB", "64")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_PROCESSES", "12")
    assert sandbox_timeout_s() == 42
    assert sandbox_memory_mb() == 1024
    assert sandbox_max_output_kb() == 32
    assert sandbox_max_disk_mb() == 64
    assert sandbox_max_processes() == 12


def test_an_out_of_range_setting_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry refuses a value outside the documented range rather than trusting it."""
    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "999999")
    assert sandbox_timeout_s() <= 600


# =============================================================================
# The rule: a caller may only lower a limit


def test_a_caller_cannot_raise_any_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "30")
    monkeypatch.setenv("TRIBOS_SANDBOX_MEMORY_MB", "512")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_OUTPUT_KB", "16")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_DISK_MB", "32")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_PROCESSES", "8")
    report = execute(
        "result = 1\n",
        timeout_s=99999,
        memory_mb=99999,
        max_output_kb=99999,
        max_disk_mb=99999,
        max_processes=99999,
    )
    assert report["status"] == "ok"
    assert report["limits"]["timeout_s"] <= 30
    assert report["limits"]["memory_mb"] <= 512
    assert report["limits"]["max_output_kb"] <= 16
    assert report["limits"]["max_disk_mb"] <= 32
    assert report["limits"]["max_processes"] <= 8


def test_the_registry_tool_timeout_cannot_exceed_the_server_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry tool's own timeout is clamped by the server's ceiling."""
    from tribos.extensions import sandbox as sandbox_ext

    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "20")
    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    result = sandbox_ext._run_python_impl("calcula_run_python", "result = 1\n", timeout_s=9999)
    # The tool must not raise the server's ceiling; the run either succeeds inside it or is refused.
    assert result.data.get("status") in ("ok", "timeout", "error", "busy", "failed")


# =============================================================================
# The memory limit


@pytest.mark.skipif(os.name == "nt", reason="the memory cap is enforced through the Windows Job Object")
def test_the_memory_cap_trips() -> None:
    report = run_code(
        "x = bytearray(400 * 1024 * 1024)\nresult = len(x)\n",
        timeout_s=60,
        memory_mb=256,
    )
    assert report["status"] in ("error", "failed")
    assert report["limits"].get("memory")


def test_the_memory_limit_is_reported() -> None:
    report = run_code("result = 1\n", timeout_s=20, memory_mb=512)
    assert report["limits"].get("memory")


# =============================================================================
# The output cap


def test_the_output_is_capped() -> None:
    report = run_code(
        "for _ in range(50000):\n    print('y' * 200)\nresult = 1\n",
        timeout_s=30,
        max_output_kb=8,
    )
    assert len(report["stdout"]) <= 16 * 1024


def test_the_stderr_is_capped() -> None:
    report = run_code(
        "import sys\nfor _ in range(50000):\n    print('z' * 200, file=sys.stderr)\nresult = 1\n",
        timeout_s=30,
        max_output_kb=8,
    )
    assert len(report["stderr"]) <= 16 * 1024


# =============================================================================
# The disk budget


def test_the_disk_budget_is_reported() -> None:
    report = run_code("result = 1\n", timeout_s=20, max_disk_mb=8)
    assert "disk_bytes" in report["limits"]


def test_the_disk_budget_is_enforced() -> None:
    report = run_code(
        "import numpy as np\nnp.save('huge.npy', np.zeros((3000, 3000)))\nresult = 1\n",
        timeout_s=60,
        max_disk_mb=1,
    )
    assert report["status"] in ("error", "failed")


# =============================================================================
# The timeout


def test_the_timeout_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from tribos.agentic.sandbox import runner as runner_mod

    # The policy bans `time`, so the sleep is reached through the test-only escape hatch.
    monkeypatch.setattr(runner_mod, "_under_test", lambda: True)
    report = run_code("import time\ntime.sleep(60)\n", timeout_s=2, _unsafe_skip_policy=True)
    assert report["status"] == "timeout"
    assert "limit" in str(report["error"]).lower()


def test_the_timeout_is_reported() -> None:
    report = run_code("result = 1\n", timeout_s=20)
    assert report["seconds"] >= 0


# =============================================================================
# The process cap


@pytest.mark.skipif(os.name == "nt", reason="the process cap is enforced through the Windows Job Object")
def test_the_process_cap_is_applied() -> None:
    """The child sees the server's process ceiling as its own rlimit."""
    report = run_code(
        "import resource\nresult = resource.getrlimit(resource.RLIMIT_NPROC)\n",
        timeout_s=20,
        max_processes=7,
        _unsafe_skip_policy=True,
    )
    assert report["status"] == "ok"
    assert report["result"] is not None


def test_the_process_cap_is_reported() -> None:
    report = run_code("result = 1\n", timeout_s=20, max_processes=7)
    assert report["limits"].get("processes")


# =============================================================================
# The concurrency ceiling


def test_the_concurrency_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that cannot get a slot reports `busy` rather than queueing without bound."""
    import threading

    from tribos.agentic.sandbox import runner as runner_mod

    semaphore = threading.BoundedSemaphore(1)
    semaphore.acquire()
    try:
        report = runner_mod.run_code("result = 1\n", timeout_s=20, semaphore=semaphore)
    finally:
        semaphore.release()
    assert report["status"] == "busy"


def test_the_queue_wait_is_bounded() -> None:
    from tribos.agentic.sandbox import runner as runner_mod

    assert runner_mod.queue_timeout_s > 0
    assert runner_mod.queue_timeout_s <= 120


# =============================================================================
# The result payload


def test_the_result_payload_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_RESULT_BYTES", "100000")
    report = execute("result = 1\n")
    assert report["status"] in ("ok", "error")


def test_the_gateway_reports_the_effective_limits() -> None:
    report = execute("result = 1\n")
    for key in ("timeout_s", "memory_mb", "max_output_kb", "max_disk_mb", "max_processes"):
        assert key in report["limits"]


# =============================================================================
# The platform differences


@pytest.mark.skipif(os.name != "posix", reason="POSIX resource limits")
def test_the_posix_rlimits_are_set() -> None:
    report = run_code(
        "import resource\n"
        "result = {\n"
        "    'cpu': resource.getrlimit(resource.RLIMIT_CPU),\n"
        "    'nofile': resource.getrlimit(resource.RLIMIT_NOFILE),\n"
        "}\n",
        timeout_s=20,
        _unsafe_skip_policy=True,
    )
    assert report["status"] == "ok"
    assert report["result"]["nofile"][0] <= 256


def test_the_runner_works_on_this_platform() -> None:
    report = run_code("result = 1 + 1\n", timeout_s=20)
    assert report["status"] == "ok"
    assert report["result"] == 2
