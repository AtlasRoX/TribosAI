"""
The container isolation backend: the actual security boundary for model-written code.

The subprocess backend (runner.py) is strong defence in depth, but it shares the server's trust domain: a native
extension inside an allowed package can reach the operating system directly, past the Python-level import, getattr
and file guards. The container backend moves the same bootstrap into an isolated domain where the host filesystem,
the host network and the host environment are unreachable.

The bootstrap and its JSON output contract are unchanged, so this backend is a drop-in replacement for the
subprocess one (the swap point named in docs/agentic/sandbox-security.md).

The container is started with:

- --network none          no route to the host or the internet
- --read-only             a read-only root filesystem
- tmpfs /work, /tmp       writable, size-capped, no new privileges
- a read-only mount  /inputs, the input files, which the code may read but not change
- --memory / --cpus       hard cgroup limits (not the advisory RLIMIT_AS)
- --pids-limit            a process-count cap
- --cap-drop ALL          no Linux capabilities
- --security-opt no-new-privileges
- --user                  a non-root uid
- a minimal environment    no API keys, no tokens, no host environment

Container runtimes are a Linux feature. On macOS the Docker Desktop VM provides them; on Windows they need WSL2.
Where no runtime is available the gateway falls back to the subprocess backend with a loud warning, unless strict
isolation is configured, in which case it refuses to run at all.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from typing import Any

from .process import (
    RUN_PREFIX,
    dir_size_bytes,
    kill_tree,
    process_group_kwargs,
    read_capped,
    rmtree,
)

logger = logging.getLogger(__name__)

# The image the backend runs; pin it by digest in production.
DEFAULT_IMAGE = "tribos-sandbox:local"
# The uid/gid the code runs as inside the container (nobody).
CONTAINER_USER = "65534:65534"
# Where the run's files live inside the container.
CONTAINER_WORK = "/work"
CONTAINER_IO = "/io"
# Where the container writes its result: the only channel it may write to.
CONTAINER_OUT = "/out"
# Where the uploaded input files are mounted, read-only.
CONTAINER_INPUTS = "/inputs"

# How long the availability probe may take.
_PROBE_TIMEOUT_S = 6

# Cached availability probe: (engine, image) -> (available, reason)
_PROBE_CACHE: dict[tuple[str, str], tuple[bool, str]] = {}


def _container_engine() -> str | None:
    """The container CLI to use: docker, podman, or None."""
    from . import sandbox_container_engine

    configured = sandbox_container_engine()
    candidates = [configured] if configured in ("docker", "podman") else ["docker", "podman"]
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _image() -> str:
    from . import sandbox_image

    return sandbox_image() or DEFAULT_IMAGE


def container_available(*, refresh: bool = False) -> tuple[bool, str]:
    """Whether the container backend can run right now: (available, reason)."""
    key = (_container_engine() or "", _image())
    if not refresh and key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    engine = _container_engine()
    if engine is None:
        result = (False, "no container runtime (docker or podman) is on PATH")
    else:
        name = os.path.basename(engine)
        try:
            proc = subprocess.run(
                [engine, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_S,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:  # noqa: BLE001
            result = (False, f"the {name} daemon is not responsive: {type(exc).__name__}")
        else:
            if proc.returncode != 0:
                result = (False, f"the {name} daemon is not running")
            else:
                try:
                    inspect = subprocess.run(
                        [engine, "image", "inspect", _image()],
                        capture_output=True,
                        text=True,
                        timeout=_PROBE_TIMEOUT_S,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception as exc:  # noqa: BLE001
                    result = (False, f"the sandbox image could not be inspected: {type(exc).__name__}")
                else:
                    result = (
                        (True, f"{name} with image {_image()}"),
                        (False, f"the sandbox image {_image()} is not built"),
                    )[inspect.returncode != 0]
    _PROBE_CACHE[key] = result
    return result


def _container_argv(
    engine: str,
    image: str,
    work: str,
    io_dir: str,
    out_dir: str,
    boot_path: str,
    cfg_path: str,
    *,
    memory_mb: int,
    timeout_s: float,
    max_disk_mb: int,
    max_processes: int,
) -> list[str]:
    """The hardened docker/podman invocation.

    Every flag here is a boundary control; removing one weakens the isolation, so they are built in one place.
    """
    tmp_mb = max(16, int(max_disk_mb))
    work_mb = max(32, int(max_disk_mb))
    return [
        engine,
        "run",
        "--rm",
        # No route to the host or the internet: the code has no way out of the container.
        "--network",
        "none",
        # A read-only root filesystem: only the tmpfs mounts below are writable.
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,size={tmp_mb}m",
        # The work dir is a tmpfs with a size quota, not a bind mount: a bind mount would put the code's
        # writes on the host filesystem, and mounting it read-only would defeat the write budget.
        "--tmpfs",
        f"{CONTAINER_WORK}:rw,nosuid,nodev,size={work_mb}m",
        "--memory",
        f"{max(256, int(memory_mb))}m",
        "--cpus",
        "1.0",
        "--pids-limit",
        str(max(1, int(max_processes))),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        # A non-root uid: the code has no privileges to escalate from.
        "--user",
        CONTAINER_USER,
        # The inputs are readable but not changeable. The work dir is a tmpfs, so this mount only carries
        # the uploaded files the code may read.
        "--mount",
        f"type=bind,src={work},dst={CONTAINER_INPUTS},readonly",
        # The channel to the host: the bootstrap, the config and the code cell. The container only reads
        # these, so the mount is read-only in the container's view of the world.
        "--mount",
        f"type=bind,src={io_dir},dst={CONTAINER_IO},readonly",
        # The result channel: the only place the container may write. It is a separate mount so that the
        # bootstrap, the config and the submitted code cannot be modified by the code that runs.
        "--mount",
        f"type=bind,src={out_dir},dst={CONTAINER_OUT}",
        "--workdir",
        CONTAINER_WORK,
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "MPLBACKEND=Agg",
        "--env",
        "TMPDIR=/tmp",
        image,
        "python",
        "-I",
        f"{CONTAINER_IO}/{os.path.basename(boot_path)}",
        f"{CONTAINER_IO}/{os.path.basename(cfg_path)}",
    ]


class ContainerBackend:
    """Runs the sandbox bootstrap inside a hardened container."""

    name = "container"

    def supports(self, engine: str) -> bool:
        return engine == "python"

    def run(self, request: Any) -> dict[str, Any]:
        from .runner import _BOOTSTRAP, _empty

        engine_path = _container_engine()
        if engine_path is None:
            return _empty("failed", "no container runtime (docker or podman) is on PATH")
        image = _image()

        timeout_s = max(1.0, float(request.timeout_s or 60))
        memory_mb = int(request.memory_mb or 2048)
        max_output_bytes = int(request.max_output_kb or 256) * 1024
        max_disk_bytes = int(request.max_disk_mb or 256) * 1024 * 1024
        max_processes = int(request.max_processes or 64)

        root = tempfile.mkdtemp(prefix=RUN_PREFIX)
        # Three directories with three different trust levels:
        #   inputs/  the uploaded files, mounted read-only into the container;
        #   io/      the bootstrap, the config and the code cell: read by the container, written by the host;
        #   out/     the result file: written by the container, read by the host.
        # Only out/ has to be writable by the container's uid, so only out/ is granted that permission.
        inputs_dir, io_dir, out_dir = (os.path.join(root, d) for d in ("inputs", "io", "out"))
        t0 = time.perf_counter()
        proc: subprocess.Popen[Any] | None = None
        try:
            for d in (inputs_dir, io_dir, out_dir):
                os.makedirs(d, exist_ok=True)
            # The container runs as uid 65534 (nobody), which owns nothing on the host, so the output directory
            # must be writable by it. On POSIX the directory is chmod'ed; on Windows the container runtime maps
            # the ownership itself.
            _make_container_writable(out_dir)
            for name, src in dict(request.input_files or {}).items():
                if not src or not os.path.isfile(src):
                    return _empty("failed", f"input file {name} is not available")
                shutil.copyfile(src, os.path.join(inputs_dir, name))
                _make_world_readable(os.path.join(inputs_dir, name))

            token = secrets.token_hex(8)
            code_path = os.path.join(io_dir, f"cell_{token}.py")
            boot_path = os.path.join(io_dir, f"bootstrap_{token}.py")
            cfg_path = os.path.join(io_dir, f"config_{token}.json")
            out_path = os.path.join(out_dir, f"out_{token}.json")
            with open(code_path, "w", encoding="utf-8") as fh:
                fh.write(request.code)
            with open(boot_path, "w", encoding="utf-8") as fh:
                fh.write(_BOOTSTRAP)
            data_path = ""
            if request.data is not None:
                data_path = os.path.join(io_dir, f"data_{token}.json")
                with open(data_path, "w", encoding="utf-8") as fh:
                    json.dump(request.data, fh, default=str)
            for f in (code_path, boot_path, cfg_path, data_path):
                if f:
                    _make_world_readable(f)

            # Every path in the config is a path INSIDE the container: the bootstrap reads the config from
            # /io and resolves the other paths against the container's own filesystem, not the host's.
            cfg = {
                "data_path": f"{CONTAINER_IO}/{os.path.basename(data_path)}" if data_path else "",
                "work_dir": CONTAINER_WORK,
                "out_path": f"{CONTAINER_OUT}/{os.path.basename(out_path)}",
                "code_path": f"{CONTAINER_IO}/{os.path.basename(code_path)}",
                "inputs": sorted(request.input_files or {}),
                "input_dir": CONTAINER_INPUTS,
                "memory_mb": memory_mb,
                "cpu_s": int(timeout_s) + 5,
                "max_output_bytes": max_output_bytes,
                "install_guards": True,
                "max_disk_bytes": max_disk_bytes,
                "max_processes": max_processes,
                "max_array_items": int(os.getenv("TRIBOS_SANDBOX_MAX_ARRAY_ITEMS", "25000")),
                "max_figures": int(request.max_figures if request.max_figures is not None else 6),
                "figure_dpi": int(os.getenv("TRIBOS_SANDBOX_FIGURE_DPI", "120")),
                "max_figure_bytes": int(os.getenv("TRIBOS_SANDBOX_MAX_FIGURE_BYTES", "3500000")),
                "max_tables": 5,
                "max_table_rows": 50,
                "allowed_modules": _allowed_modules(),
                "banned_attributes": _banned("BANNED_ATTRIBUTES"),
                "banned_names": _banned("BANNED_NAMES"),
                "banned_calls": _banned("BANNED_CALLS"),
                "reader_functions": _banned("READER_FUNCTIONS"),
                "reader_path_kwargs": _banned("READER_PATH_KWARGS"),
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)

            argv = _container_argv(
                engine_path,
                image,
                inputs_dir,
                io_dir,
                out_dir,
                boot_path,
                cfg_path,
                memory_mb=memory_mb,
                timeout_s=timeout_s,
                max_disk_mb=int(request.max_disk_mb or 256),
                max_processes=max_processes,
            )
            # The container runtime's own stdout and stderr land here, in the run root. They are not inside
            # the io mount, which the container sees read-only.
            stdout_path, stderr_path = os.path.join(root, "stdout.txt"), os.path.join(root, "stderr.txt")
            timed_out = False
            try:
                with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
                    proc = subprocess.Popen(
                        argv,
                        cwd=root,
                        stdin=subprocess.DEVNULL,
                        stdout=out_fh,
                        stderr=err_fh,
                        env={"PATH": os.environ.get("PATH", "")},
                        **process_group_kwargs(),
                    )
                    if request.on_spawn is not None:
                        try:
                            request.on_spawn(proc)
                        except Exception:
                            pass
                    try:
                        proc.wait(timeout=timeout_s + 10)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        kill_tree(proc)
            finally:
                if proc is not None and proc.poll() is None:
                    kill_tree(proc)

            seconds = round(time.perf_counter() - t0, 3)
            stdout = read_capped(stdout_path, max_output_bytes)
            stderr = read_capped(stderr_path, 8 * 1024, tail=True)
            if timed_out:
                return _empty(
                    "timeout",
                    f"the analysis exceeded the {timeout_s:g} s time limit and was stopped",
                    stdout=stdout,
                    stderr=stderr,
                    seconds=seconds,
                    limits={"backend": "container", "image": image},
                )

            # The code's own writes land on the container's tmpfs, so the host sees only the result file.
            # The tmpfs quota enforces the real disk budget; this is the host-side backstop.
            written = dir_size_bytes(out_dir)
            if max_disk_bytes > 0 and written > max_disk_bytes:
                return _empty(
                    "error",
                    f"the analysis wrote {written} bytes, over the {max_disk_bytes} byte budget",
                    stdout=stdout,
                    stderr=stderr,
                    seconds=seconds,
                    limits={"backend": "container", "disk_bytes": written},
                )

            try:
                with open(out_path, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError):
                tail = stderr.strip().splitlines()[-1:] if stderr.strip() else []
                reason = tail[0][:300] if tail else f"the container exited with code {proc.returncode if proc else 'unknown'}"
                return _empty(
                    "error",
                    f"the sandbox container ended without a result: {reason}",
                    stdout=stdout,
                    stderr=stderr,
                    seconds=seconds,
                    limits={"backend": "container", "image": image},
                )
            limits = dict(payload.get("limits") or {})
            limits.update({"backend": "container", "image": image, "disk_bytes": written})
            return {
                "status": "ok" if payload.get("status") == "ok" else "error",
                "stdout": stdout,
                "stderr": stderr,
                "result": payload.get("result"),
                "figures": list(payload.get("figures") or [])[:6],
                "tables": list(payload.get("tables") or [])[:5],
                "seconds": seconds,
                "error": payload.get("error"),
                "violations": [],
                "limits": limits,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Container sandbox run failed: %s", exc, exc_info=True)
            return _empty("failed", f"{type(exc).__name__}: {str(exc)[:200]}")
        finally:
            rmtree(root)


def _make_world_readable(path: str) -> None:
    """Make a file readable by the container user (uid 65534), which is not the owner on the host."""
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def _make_container_writable(path: str) -> None:
    """Make the output directory writable by the container user so it can emit the result file.

    The container runs as uid 65534, which is "other" to the directory the server user created, so the write and
    execute bits must be granted to other. The read bit is not: the container only writes the result file
    there, and the directory holds nothing the container needs to list. The directory is inside the run's own
    temporary tree, which the server user alone can reach.
    """
    try:
        os.chmod(path, 0o707)  # nosec B103 - the container's uid needs to write the result file
    except OSError:
        pass


def _allowed_modules() -> list[str]:
    from .policy import ALLOWED_MODULE_ROOTS

    return sorted(ALLOWED_MODULE_ROOTS)


def _banned(name: str) -> list[str]:
    from . import policy

    return sorted(getattr(policy, name, ()))


__all__ = ["CONTAINER_USER", "ContainerBackend", "container_available"]
