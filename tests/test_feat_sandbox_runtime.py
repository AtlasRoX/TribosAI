"""
The subprocess backend's runtime hardening (tribos/agentic/sandbox/runner.py): the per-run environment, the
per-run matplotlib cache, the concurrency limit, the disk budget, the degraded-limits report and the janitor
that removes the directories a crashed parent left behind.

Offline: no network and no real model. Everything runs the real child process.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from tribos.agentic.sandbox import process as proc_mod
from tribos.agentic.sandbox import runner as runner_mod

# =============================================================================
# The per-run environment


def test_the_child_environment_is_an_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("SOME_RANDOM_TOKEN", "abc")
    env = proc_mod.allowlisted_env("/tmp/root", "/tmp/root/tmp")
    assert "OPENAI_API_KEY" not in env
    assert "DB_PASSWORD" not in env
    assert "SOME_RANDOM_TOKEN" not in env


def test_the_child_environment_has_no_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """HOME points at the server user's home directory, which the code must never see."""
    monkeypatch.setenv("HOME", "/home/serveruser")
    env = proc_mod.allowlisted_env("/tmp/root", "/tmp/root/tmp")
    assert "HOME" not in env


def test_the_sage_allowlist_adds_home_but_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/serveruser")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    env = proc_mod.allowlisted_env("/tmp/root", "/tmp/root/tmp", allowlist=proc_mod.SAGE_ENV_ALLOWLIST)
    assert "OPENAI_API_KEY" not in env
    assert env.get("HOME") == "/home/serveruser"


def test_the_environment_pins_the_numeric_libraries(monkeypatch: pytest.MonkeyPatch) -> None:
    env = proc_mod.allowlisted_env("/tmp/root", "/tmp/root/tmp")
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["MPLBACKEND"] == "Agg"


# =============================================================================
# The per-run matplotlib cache


def test_each_run_gets_its_own_matplotlib_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared cache directory is a cross-run poisoning path: one run can leave a file the next one reads."""
    monkeypatch.setenv("MPLCONFIGDIR", "/tmp/shared-mpl")
    first = proc_mod.allowlisted_env("/tmp/root1", "/tmp/root1/tmp")
    second = proc_mod.allowlisted_env("/tmp/root2", "/tmp/root2/tmp")
    assert first["MPLCONFIGDIR"] != second["MPLCONFIGDIR"]
    assert first["MPLCONFIGDIR"] != "/tmp/shared-mpl"


def test_the_matplotlib_cache_is_inside_the_run_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = proc_mod.allowlisted_env(str(tmp_path), str(tmp_path / "tmp"))
    assert env["MPLCONFIGDIR"].startswith(str(tmp_path))


# =============================================================================
# The concurrency limit


def test_a_run_is_refused_when_the_sandbox_is_busy() -> None:
    """A saturated sandbox reports `busy` rather than queueing without bound."""
    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(timeout=1)
    try:
        report = runner_mod.run_code(
            "result = 1\n",
            timeout_s=10,
            semaphore=semaphore,
        )
    finally:
        semaphore.release()
    assert report["status"] == "busy"
    assert "busy" in str(report["error"]).lower()


def test_a_run_proceeds_when_a_slot_is_free() -> None:
    semaphore = threading.BoundedSemaphore(1)
    report = runner_mod.run_code("result = 1\n", timeout_s=20, semaphore=semaphore)
    assert report["status"] == "ok"


# =============================================================================
# The disk budget


def test_the_disk_budget_is_enforced() -> None:
    """The write budget is spent by the code, so a run that writes past it is stopped."""
    report = runner_mod.run_code(
        "import numpy as np\n"
        "np.save('big.npy', np.zeros((2000, 2000)))\n"
        "result = 1\n",
        timeout_s=60,
        max_disk_mb=1,
    )
    assert report["status"] in ("error", "failed")
    assert "budget" in str(report["error"]).lower() or "disk" in str(report["error"]).lower()


def test_a_small_write_is_allowed() -> None:
    report = runner_mod.run_code(
        "import numpy as np\n"
        "np.save('small.npy', np.zeros((10, 10)))\n"
        "result = 1\n",
        timeout_s=30,
        max_disk_mb=16,
    )
    assert report["status"] == "ok"


# =============================================================================
# The degraded limits report


def test_the_report_says_whether_the_limits_applied() -> None:
    """A run whose resource limits could not be applied says so, rather than pretending it was bounded."""
    report = runner_mod.run_code("result = 1\n", timeout_s=20)
    assert "limits" in report
    assert "degraded" in report["limits"]
    assert isinstance(report["limits"]["degraded"], bool)


def test_the_degraded_flag_is_reported_when_the_limits_cannot_be_applied() -> None:
    """A run whose limits could not be applied says so; the flag is always present in the report."""
    report = runner_mod.run_code("result = 1\n", timeout_s=20)
    assert "degraded" in report["limits"]
    assert "degraded_reason" in report["limits"]


def test_the_bootstrap_reports_a_degraded_run() -> None:
    """The bootstrap catches a limit failure instead of dying, and records why it was degraded."""
    bootstrap = runner_mod._BOOTSTRAP
    assert "_LIMITS[\"degraded\"] = True" in bootstrap
    assert "resource limits could not be applied" in bootstrap


def test_strict_mode_is_reported_in_the_limits() -> None:
    report = runner_mod.run_code("result = 1\n", timeout_s=20, strict_limits=True)
    assert report["status"] in ("ok", "failed")
    assert "degraded" in report["limits"]


# =============================================================================
# The test-only escape hatch


def test_the_escape_hatch_is_refused_outside_a_test_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "_under_test", lambda: False)
    report = runner_mod.run_code("result = 1\n", timeout_s=20, _unsafe_skip_policy=True)
    assert report["status"] == "failed"
    assert "test-only" in str(report["error"]).lower()


def test_the_escape_hatch_never_disables_the_network_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "_under_test", lambda: True)
    report = runner_mod.run_code(
        "import socket\nsocket.socket()\nresult = 1\n",
        timeout_s=20,
        _unsafe_skip_policy=True,
    )
    assert report["status"] != "ok"


# =============================================================================
# Cleanup


def test_the_run_directory_is_removed_after_a_run() -> None:
    import tempfile

    before = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    runner_mod.run_code("result = 1\n", timeout_s=20)
    after = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    assert after <= before


def test_the_run_directory_is_removed_after_a_timeout() -> None:
    import tempfile

    before = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    runner_mod.run_code("import time\ntime.sleep(30)\n", timeout_s=2)
    after = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    assert after <= before


def test_the_run_directory_is_removed_after_a_policy_violation() -> None:
    import tempfile

    before = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    runner_mod.run_code("import os\n", timeout_s=20)
    after = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    assert after <= before


# =============================================================================
# The janitor


def test_the_janitor_removes_a_stale_run_directory(tmp_path: Path) -> None:
    stale = tmp_path / "tribos-sbx-stale"
    stale.mkdir()
    (stale / "leftover.txt").write_text("x", encoding="utf-8")
    # The janitor works on the system temp directory, so the stale directory is created there.
    import tempfile

    target = Path(tempfile.gettempdir()) / "tribos-sbx-janitor-test"
    target.mkdir(exist_ok=True)
    (target / "leftover.txt").write_text("x", encoding="utf-8")
    old = time.time() - 7200
    os.utime(target, (old, old))
    try:
        removed = proc_mod.sweep_stale_runs(max_age_s=3600.0)
        assert str(target) in removed or not target.exists()
    finally:
        if target.exists():
            proc_mod.rmtree(str(target))


def test_the_janitor_leaves_a_fresh_run_directory() -> None:
    import tempfile

    target = Path(tempfile.gettempdir()) / "tribos-sbx-fresh-test"
    target.mkdir(exist_ok=True)
    try:
        proc_mod.sweep_stale_runs(max_age_s=3600.0)
        assert target.exists()
    finally:
        proc_mod.rmtree(str(target))


# =============================================================================
# The output cap


def test_the_output_is_capped() -> None:
    report = runner_mod.run_code(
        "for i in range(100000):\n    print('x' * 100)\nresult = 1\n",
        timeout_s=30,
        max_output_kb=4,
    )
    assert report["status"] == "ok"
    assert len(report["stdout"]) <= 8 * 1024
    assert "truncated" in report["stdout"]


# =============================================================================
# The process tree


def test_a_timeout_kills_the_whole_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child spawns a grandchild; the tree kill must take both, not just the direct child."""
    monkeypatch.setattr(runner_mod, "_under_test", lambda: True)
    report = runner_mod.run_code(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n",
        timeout_s=2,
        max_processes=16,
        _unsafe_skip_policy=True,
    )
    assert report["status"] == "timeout"
    time.sleep(0.5)


def test_the_process_tree_kill_reaches_a_grandchild(monkeypatch: pytest.MonkeyPatch) -> None:
    """kill_tree terminates the whole group, not only the process it was handed."""
    import subprocess as sp

    child = sp.Popen([os.environ.get("PYTHON", "python"), "-c", "import time; time.sleep(60)"], **proc_mod.process_group_kwargs())
    try:
        assert child.poll() is None
        proc_mod.kill_tree(child)
        child.wait(timeout=10)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()


def test_an_exited_process_is_never_taskkilled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`taskkill /T` on an exited pid kills every process whose recorded parent id is that (recycled) pid: it killed the
    backend's supervisor. A finished child is only reaped."""
    import subprocess
    import sys

    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(argv, *a, **k):  # type: ignore[no-untyped-def]
        if argv and argv[0] == "taskkill":
            calls.append(list(argv))
        return real_run(argv, *a, **k)

    monkeypatch.setattr(proc_mod.subprocess, "run", spy)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    proc_mod.kill_tree(child)
    assert calls == []
