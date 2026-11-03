"""
The container isolation backend (tribos/agentic/sandbox/container.py): the hardened invocation, the runtime and
image probe, and the boundary itself.

The boundary tests need a container runtime and the sandbox image; they skip when neither is available. The
invocation and the probe are tested everywhere, because a flag that is silently dropped is a hole.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tribos.agentic.sandbox import container as container_mod
from tribos.agentic.sandbox.backends import ExecutionRequest
from tribos.agentic.sandbox.container import (
    CONTAINER_INPUTS,
    CONTAINER_IO,
    CONTAINER_OUT,
    CONTAINER_USER,
    CONTAINER_WORK,
    ContainerBackend,
    container_available,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# The availability probe


def test_the_probe_reports_why_it_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: None)
    container_mod._PROBE_CACHE.clear()
    available, reason = container_available(refresh=True)
    assert available is False
    assert "runtime" in reason.lower()


def test_the_probe_fails_when_the_daemon_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: "/usr/bin/docker")
    container_mod._PROBE_CACHE.clear()

    class Result:
        returncode = 1
        stdout = ""
        stderr = "cannot connect"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    available, reason = container_available(refresh=True)
    assert available is False
    assert "not running" in reason.lower()


def test_the_probe_fails_when_the_image_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: "/usr/bin/docker")
    container_mod._PROBE_CACHE.clear()

    calls: list[list[str]] = []

    class Result:
        def __init__(self, code: int) -> None:
            self.returncode = code
            self.stdout = ""
            self.stderr = ""

    def _run(argv: list[str], **kwargs: object) -> Result:
        calls.append(argv)
        return Result(0 if "info" in argv else 1)

    monkeypatch.setattr(subprocess, "run", _run)
    available, reason = container_available(refresh=True)
    assert available is False
    assert "not built" in reason.lower()


def test_the_probe_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: None)
    container_mod._PROBE_CACHE.clear()
    container_available(refresh=True)
    assert container_mod._PROBE_CACHE
    cached = dict(container_mod._PROBE_CACHE)
    container_available(refresh=False)
    assert container_mod._PROBE_CACHE == cached


def test_the_engine_is_found_on_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX_CONTAINER_ENGINE", "podman")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "podman" else None)
    assert container_mod._container_engine() == "/usr/bin/podman"


# =============================================================================
# The hardened invocation


def _argv(**kwargs: object) -> list[str]:
    defaults: dict[str, object] = {
        "engine": "docker",
        "image": "tribos-sandbox:local",
        "work": "/tmp/work",
        "io_dir": "/tmp/io",
        "out_dir": "/tmp/out",
        "boot_path": "/tmp/io/bootstrap.py",
        "cfg_path": "/tmp/io/config.json",
        "memory_mb": 512,
        "timeout_s": 30,
        "max_disk_mb": 64,
        "max_processes": 8,
    }
    defaults.update(kwargs)
    return container_mod._container_argv(**defaults)  # type: ignore[arg-type]


def test_the_container_has_no_network() -> None:
    argv = _argv()
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"


def test_the_root_filesystem_is_read_only() -> None:
    argv = _argv()
    assert "--read-only" in argv


def test_the_capabilities_are_dropped() -> None:
    argv = _argv()
    assert "--cap-drop" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"


def test_no_new_privileges_is_set() -> None:
    argv = _argv()
    assert "--security-opt" in argv
    assert "no-new-privileges" in argv


def test_the_code_runs_as_a_non_root_user() -> None:
    argv = _argv()
    assert "--user" in argv
    assert argv[argv.index("--user") + 1] == CONTAINER_USER
    uid = int(CONTAINER_USER.split(":")[0])
    assert uid != 0


def test_the_memory_limit_is_applied() -> None:
    argv = _argv(memory_mb=777)
    assert argv[argv.index("--memory") + 1] == "777m"


def test_the_cpu_limit_is_applied() -> None:
    argv = _argv()
    assert "--cpus" in argv
    assert argv[argv.index("--cpus") + 1] == "1.0"


def test_the_process_limit_is_applied() -> None:
    argv = _argv(max_processes=13)
    assert argv[argv.index("--pids-limit") + 1] == "13"


def test_the_tmpfs_mounts_are_size_capped() -> None:
    argv = _argv(max_disk_mb=48)
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert any("/tmp" in t for t in tmpfs)
    assert any(CONTAINER_WORK in t for t in tmpfs)
    for mount in tmpfs:
        assert "size=" in mount
        assert "nosuid" in mount
        assert "nodev" in mount


def test_the_inputs_are_mounted_read_only() -> None:
    argv = _argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    input_mounts = [m for m in mounts if f"dst={CONTAINER_INPUTS}" in m]
    assert input_mounts
    assert "readonly" in input_mounts[0]


def test_the_io_channel_is_mounted_read_only() -> None:
    """The bootstrap, the config and the code cell may not be changed by the code that runs."""
    argv = _argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    io_mounts = [m for m in mounts if f"dst={CONTAINER_IO}" in m]
    assert io_mounts
    assert "readonly" in io_mounts[0]


def test_the_result_channel_is_the_only_writable_mount() -> None:
    """Only the output directory may be written; the inputs and the io channel are read-only."""
    argv = _argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    writable = [m for m in mounts if "readonly" not in m]
    assert len(writable) == 1
    assert f"dst={CONTAINER_OUT}" in writable[0]


def test_no_host_environment_reaches_the_container() -> None:
    """Only the three explicit variables are passed in; the host's environment is not inherited."""
    argv = _argv()
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert envs == ["PYTHONHASHSEED=0", "MPLBACKEND=Agg", "TMPDIR=/tmp"]
    for value in envs:
        assert "KEY" not in value.upper()
        assert "TOKEN" not in value.upper()


def test_the_interpreter_is_isolated() -> None:
    argv = _argv()
    assert "-I" in argv


def test_the_container_is_removed_after_the_run() -> None:
    assert "--rm" in _argv()


def test_the_bootstrap_and_the_config_are_passed_in_io() -> None:
    argv = _argv(boot_path="/tmp/io/bootstrap_abc.py", cfg_path="/tmp/io/config_abc.json")
    assert f"{CONTAINER_IO}/bootstrap_abc.py" in argv
    assert f"{CONTAINER_IO}/config_abc.json" in argv


# =============================================================================
# The backend


def test_the_backend_refuses_without_a_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: None)
    report = ContainerBackend().run(ExecutionRequest(code="print('x')"))
    assert report["status"] == "failed"
    assert "runtime" in str(report["error"]).lower()


def test_the_backend_refuses_a_missing_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "_container_engine", lambda: "/usr/bin/docker")
    report = ContainerBackend().run(
        ExecutionRequest(code="print('x')", input_files={"missing.csv": "/nonexistent/file.csv"})
    )
    assert report["status"] == "failed"
    assert "not available" in str(report["error"]).lower()


def test_the_backend_supports_python_only() -> None:
    backend = ContainerBackend()
    assert backend.supports("python")
    assert not backend.supports("sage")


# =============================================================================
# The boundary (needs a runtime and the image)


def _runtime_and_image() -> bool:
    available, _reason = container_available(refresh=True)
    return available


@pytest.mark.skipif(not _runtime_and_image(), reason="no container runtime with the sandbox image is available")
def test_the_code_has_no_network() -> None:
    report = ContainerBackend().run(
        ExecutionRequest(code="import socket\nsocket.socket()\nresult = 1\n", timeout_s=30)
    )
    assert report["status"] != "ok"


@pytest.mark.skipif(not _runtime_and_image(), reason="no container runtime with the sandbox image is available")
def test_the_code_cannot_read_the_host_filesystem() -> None:
    report = ContainerBackend().run(
        ExecutionRequest(code="result = open('/etc/passwd').read()\n", timeout_s=30)
    )
    assert report["status"] != "ok"


@pytest.mark.skipif(not _runtime_and_image(), reason="no container runtime with the sandbox image is available")
def test_no_secret_reaches_the_container() -> None:
    os.environ["A_TEST_SECRET"] = "must-not-appear"
    try:
        report = ContainerBackend().run(
            ExecutionRequest(code="import os\nresult = os.environ.get('A_TEST_SECRET')\n", timeout_s=30)
        )
    finally:
        os.environ.pop("A_TEST_SECRET", None)
    assert "must-not-appear" not in str(report.get("result"))


@pytest.mark.skipif(not _runtime_and_image(), reason="no container runtime with the sandbox image is available")
def test_the_code_runs_in_the_container() -> None:
    report = ContainerBackend().run(ExecutionRequest(code="result = 6 * 7\n", timeout_s=60))
    assert report["status"] == "ok"
    assert report["result"] == 42
    assert report["limits"].get("backend") == "container"


@pytest.mark.skipif(not _runtime_and_image(), reason="no container runtime with the sandbox image is available")
def test_the_container_times_out() -> None:
    report = ContainerBackend().run(
        ExecutionRequest(code="import time\ntime.sleep(600)\n", timeout_s=5),
    )
    assert report["status"] == "timeout"


# =============================================================================
# The image


def test_the_sandbox_image_is_built_from_the_scientific_stack_only() -> None:
    """The image must not carry the API's dependencies: it holds no credentials and needs no model runtime."""
    requirements = (REPO_ROOT / "docker" / "sandbox-requirements.txt").read_text(encoding="utf-8")
    for forbidden in ("fastapi", "uvicorn", "openai", "httpx", "torch", "transformers", "langchain"):
        assert forbidden not in requirements.lower(), f"{forbidden} must not be in the sandbox image"


def test_the_sandbox_image_runs_as_a_non_root_user() -> None:
    dockerfile = (REPO_ROOT / "docker" / "sandbox.Dockerfile").read_text(encoding="utf-8")
    assert "USER 65534:65534" in dockerfile


def test_the_sandbox_image_has_no_network_tools() -> None:
    dockerfile = (REPO_ROOT / "docker" / "sandbox.Dockerfile").read_text(encoding="utf-8")
    for tool in ("curl", "wget", "git", "openssh"):
        assert tool not in dockerfile.lower(), f"{tool} must not be in the sandbox image"
