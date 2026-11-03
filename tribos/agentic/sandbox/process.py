"""
Shared process primitives for every sandbox backend (subprocess, container, SageMath).

The security-critical behaviour of a run lives here so the Python runner and the SageMath runner cannot drift
apart: the child environment is an allowlist (never API keys), process trees are terminated as a unit, captured
output is capped, and resource limits are applied through the operating system rather than trusted to the code.

Nothing in this module is a security boundary on its own: the subprocess backend runs inside the same trust
domain as the server. The container backend (container.py) is the boundary; these helpers are the layers inside it.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any

logger = logging.getLogger(__name__)

# The child's whole environment: an allowlist. API keys, tokens and database credentials never reach a child.
# HOME is deliberately absent: it points at the server user's home directory, which the code must never see.
ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "PATHEXT",
)

# The SageMath interpreter needs a little more (a HOME for Sage's own caches, a locale, a timezone), but still
# never a credential.
SAGE_ENV_ALLOWLIST: tuple[str, ...] = ENV_ALLOWLIST + (
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LANGUAGE",
    "TZ",
    "DOT_SAGE",
    "SAGE_ROOT",
    "SAGE_LOCAL",
    "MPLBACKEND",
)

STDERR_TAIL_BYTES = 8 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_MAX_DISK_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_PROCESSES = 64
DEFAULT_KILL_GRACE_S = 2.0

# Directory prefix of every sandbox run; the janitor removes stale ones.
RUN_PREFIX = "tribos-sbx-"


def allowlisted_env(
    root: str,
    tmp: str,
    *,
    mpl_config_dir: str | None = None,
    extra: dict[str, str] | None = None,
    allowlist: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """The child's whole environment: an allowlist, never API keys or tokens."""
    env: dict[str, str] = {}
    for key in (allowlist if allowlist is not None else ENV_ALLOWLIST):
        value = os.environ.get(key)
        if value:
            env[key] = value
    mpl_dir = mpl_config_dir or os.path.join(root, "mpl")
    try:
        os.makedirs(mpl_dir, exist_ok=True)
    except OSError:
        mpl_dir = os.path.join(root, "mpl")
    env.update(
        {
            "TEMP": tmp,
            "TMP": tmp,
            "TMPDIR": tmp,
            "PYTHONHASHSEED": "0",
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": mpl_dir,
            "NUMBA_CACHE_DIR": tmp,
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def rmtree(path: str) -> None:
    """Remove a run directory even when the child left read-only files behind."""

    def onerror(func: Any, p: str, _exc: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onexc=onerror)


def kill_descendants(pid: int) -> bool:
    """Kill the live process `pid` and its descendants (psutil; a child older than its parent is a recycled-pid
    stranger and is skipped). False when psutil is unavailable or `pid` is gone, so the caller can fall back."""
    try:
        import psutil

        parent = psutil.Process(pid)
        born = parent.create_time()
        procs = [c for c in parent.children(recursive=True) if c.create_time() >= born] + [parent]
    except Exception:  # noqa: BLE001 - psutil missing, or the process already exited
        return False
    for p in procs:
        try:
            p.kill()
        except Exception:  # noqa: BLE001 - already gone
            pass
    return True


def kill_tree(proc: subprocess.Popen[Any], *, grace_s: float = DEFAULT_KILL_GRACE_S) -> None:
    """Terminate a child and every descendant it started, then reap it.

    POSIX: the child runs in its own session (start_new_session=True), so the process group is the whole tree.
    SIGTERM first so a child can clean up, then SIGKILL after the grace period.
    Windows: the Job Object is the reliable lever (descendants inherit it); taskkill /T and proc.kill() are the
    fallbacks for hosts where the Job Object could not be created.
    """
    if proc.poll() is not None and os.name != "nt":
        try:
            proc.wait(timeout=1)
        except Exception:  # noqa: BLE001
            pass
        return

    if os.name == "nt":
        # Never "taskkill /T" a pid that has exited: Windows does not re-parent orphans, so /T kills every process whose
        # recorded parent id equals that (possibly recycled) pid. It killed the server's supervisor, whose parent (a
        # WMI host) had exited and whose pid a sandbox child later reused.
        if proc.poll() is None and not kill_descendants(proc.pid):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        return

    try:
        group = os.getpgid(proc.pid)
    except (OSError, ProcessLookupError):
        group = None
    if group is not None:
        try:
            os.killpg(group, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        deadline = time.monotonic() + max(0.0, float(grace_s))
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                os.killpg(group, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass


def read_capped(path: str, limit: int, tail: bool = False) -> str:
    """Read at most `limit` bytes of a captured output file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if tail and size > limit:
                fh.seek(size - limit)
            data = fh.read(limit)
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > limit:
        text = ("...(truncated)\n" + text) if tail else (text + "\n...(truncated)")
    return text


def dir_size_bytes(path: str) -> int:
    """Total size of the files under a directory (the parent's backstop against a disk quota)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def sweep_stale_runs(max_age_s: float = 3600.0) -> list[str]:
    """Remove run directories left behind by a crashed parent; returns the removed paths."""
    removed: list[str] = []
    base = tempfile.gettempdir()
    cutoff = time.time() - max(0.0, float(max_age_s))
    try:
        entries = list(os.scandir(base))
    except OSError:
        return removed
    for entry in entries:
        if not entry.name.startswith(RUN_PREFIX) or not entry.is_dir(follow_symlinks=False):
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                continue
        except OSError:
            continue
        try:
            rmtree(entry.path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not remove stale sandbox directory %s: %s", entry.path, exc)
            continue
        removed.append(entry.path)
    return removed


def process_group_kwargs() -> dict[str, Any]:
    """Popen kwargs that put the child in its own process group / new console group."""
    if os.name == "nt":
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        }
    return {"start_new_session": True}


__all__ = [
    "DEFAULT_KILL_GRACE_S",
    "SAGE_ENV_ALLOWLIST",
    "DEFAULT_MAX_DISK_BYTES",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_MAX_PROCESSES",
    "ENV_ALLOWLIST",
    "RUN_PREFIX",
    "STDERR_TAIL_BYTES",
    "allowlisted_env",
    "dir_size_bytes",
    "kill_descendants",
    "kill_tree",
    "process_group_kwargs",
    "read_capped",
    "rmtree",
    "sweep_stale_runs",
]
