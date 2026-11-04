"""
SageMath integration engine for Tribos.

Supports running high-performance symbolic algebra, algebraic geometry,
number theory, combinatorics, and physics derivations via local SageMath
or WSL-hosted SageMath environments (e.g. micromamba/conda Sage 10.x).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from ..agentic.sandbox.process import (
    SAGE_ENV_ALLOWLIST,
    allowlisted_env,
    kill_tree,
    process_group_kwargs,
    read_capped,
)

logger = logging.getLogger(__name__)

_DISCOVERED_CMD: list[str] | None = None
_DISCOVERED_MODE: str | None = None
_CHECKED = False

# Environment passed to Sage: only what the interpreter (or wsl.exe) needs to start. Model-written code never
# sees the server's API keys, tokens or database credentials. The allowlist itself lives in the shared sandbox
# process module, so the Sage path and the Python path cannot drift apart.
_SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.I)
# stderr markers of a broken environment (not of the submitted code)
_INFRA_ERROR_RE = re.compile(
    r"command not found|cannot execute|Wsl/|Permission denied|MemoryError|Killed|out of memory|GLIBC|"
    r"ImportError: libsage|sage: not found",
    re.I,
)

# Installed before the submitted code runs: the Sage process is a fresh interpreter, so the runner's socket stub
# does not apply to it. Defence in depth only; the container's --network none is the layer that actually holds.
_NETWORK_GUARD = r"""
try:
    import socket as _sb_socket

    def _sb_deny(*_a, **_k):
        raise PermissionError("network access is disabled in the analysis sandbox")

    class _SBBlockedSocket(_sb_socket.socket):
        def __init__(self, *_a, **_k):
            _sb_deny()

    _sb_socket.socket = _SBBlockedSocket
    for _sb_name in ("create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
                     "gethostbyaddr", "socketpair", "fromfd"):
        if hasattr(_sb_socket, _sb_name):
            setattr(_sb_socket, _sb_name, _sb_deny)
except Exception:
    pass
"""

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_FIGURES_DELIM_RE = re.compile(r"__TRIBOS_FIGURES_START__(.*?)__TRIBOS_FIGURES_END__", re.DOTALL)

_HARVESTER_SNIPPET = r'''
# --- TRIBOS AUTO GRAPHICS & PLOT HARVESTER ---
try:
    import sys as _sys, os as _os, io as _io, base64 as _b64, json as _json, tempfile as _tmpfile, warnings as _warnings
    _warnings.filterwarnings("ignore")
    _tribos_figures = []

    # 1. Harvest open Matplotlib figures
    _plt = _sys.modules.get("matplotlib.pyplot")
    if _plt is not None:
        for _fignum in list(_plt.get_fignums())[:5]:
            try:
                _buf = _io.BytesIO()
                _plt.figure(_fignum).savefig(_buf, format="png", dpi=120, bbox_inches="tight")
                _data = _buf.getvalue()
                if len(_data) > 100:
                    _tribos_figures.append({"name": f"figure_{_fignum}.png", "png_base64": _b64.b64encode(_data).decode("ascii")})
            except Exception:
                pass
        try:
            _plt.close("all")
        except Exception:
            pass

    # 2. Harvest Sage Graphics objects in globals()
    for _var_name, _val in list(globals().items()):
        if _var_name.startswith("_") or type(_val).__name__ in ("LazyImport", "module"):
            continue
        try:
            _tname = type(_val).__name__
            if _tname in ("Graphics", "Graphics3d", "MultiGraphics") or (hasattr(_val, "save") and "plot" in str(type(_val)).lower()):
                _tf = _tmpfile.NamedTemporaryFile(suffix=".png", delete=False)
                _tf_name = _tf.name
                _tf.close()
                try:
                    _val.save(_tf_name, dpi=120)
                    if _os.path.exists(_tf_name) and _os.path.getsize(_tf_name) > 100:
                        with open(_tf_name, "rb") as _f:
                            _data = _f.read()
                        _tribos_figures.append({"name": f"{_var_name}.png", "png_base64": _b64.b64encode(_data).decode("ascii")})
                finally:
                    if _os.path.exists(_tf_name):
                        _os.unlink(_tf_name)
        except Exception:
            pass

    if _tribos_figures:
        print("\n__TRIBOS_FIGURES_START__" + _json.dumps(_tribos_figures[:5]) + "__TRIBOS_FIGURES_END__\n")
except Exception:
    pass
'''


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _sandbox_env(tmp_dir: str | None = None) -> dict[str, str]:
    """The Sage child's environment: an allowlist, never the server's credentials."""
    root = tmp_dir or tempfile.mkdtemp(prefix="tribos-sbx-")
    env = allowlisted_env(root, tmp_dir or root, allowlist=SAGE_ENV_ALLOWLIST)
    env = {k: v for k, v in env.items() if not _SECRET_NAME_RE.search(k)}
    env["WSLENV"] = ""  # share no Windows variables with the WSL side
    env.setdefault("MPLBACKEND", "Agg")
    # Sage needs a HOME for its own caches, but it must be the sandbox's scratch directory: the server
    # user's home holds the credentials, the SSH keys and the rest of the deployment.
    env["HOME"] = root
    env["USERPROFILE"] = root
    return env


def classify_failure(status: str, stderr: str) -> str:
    """'model_code_error' when the submitted code itself failed (syntax, NameError, wrong math API), 'timeout', or
    'infrastructure' when Sage could not run at all (missing install, broken WSL, killed by the OS). Only the first
    is evidence that the agent's action was wrong; the others must not be charged to the model."""
    if status == "ok":
        return "none"
    if status == "timeout":
        return "timeout"
    text = stderr or ""
    if status == "unavailable" or (_INFRA_ERROR_RE.search(text) and "Traceback" not in text):
        return "infrastructure"
    return "model_code_error"


def _wsl_sage_probe() -> list[str] | None:
    """Locate sage inside the default WSL distribution: PATH first, then the usual conda/mamba env locations."""
    probe = (
        "command -v sage || ls -1 $HOME/micromamba/envs/sage/bin/sage $HOME/miniforge3/envs/sage/bin/sage "
        "$HOME/mambaforge/envs/sage/bin/sage $HOME/miniconda3/envs/sage/bin/sage /opt/sage/sage 2>/dev/null"
    )
    try:
        proc = subprocess.run(["wsl", "-e", "sh", "-c", probe], capture_output=True, text=True, timeout=25)
    except Exception:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("/")]
    return ["wsl", "-e", lines[0]] if lines else None


def find_sagemath_command(*, force_recheck: bool = False) -> tuple[list[str], str] | None:
    """
    Locates the SageMath executable.
    Checks in order:
    1. TRIBOS_SAGEMATH_PATH (a native executable, or wsl:<wsl.exe arguments>, e.g. "wsl:-d Ubuntu -e /opt/sage/sage")
    2. Native PATH `sage`
    3. WSL SageMath (micromamba/conda envs or system sage in Ubuntu)
    Returns (command_prefix, mode) where mode is 'native' or 'wsl', or None if unavailable.
    """
    global _DISCOVERED_CMD, _DISCOVERED_MODE, _CHECKED

    if _CHECKED and not force_recheck:
        if _DISCOVERED_CMD is not None and _DISCOVERED_MODE is not None:
            return list(_DISCOVERED_CMD), _DISCOVERED_MODE
        return None

    _CHECKED = True

    # 1. Environment variable override
    from tribos.config.settings import get_str

    env_path = str(get_str("TRIBOS_SAGEMATH_PATH") or "").strip()
    if env_path:
        if os.path.isfile(env_path) or shutil.which(env_path):
            _DISCOVERED_CMD = [env_path]
            _DISCOVERED_MODE = "native"
            return list(_DISCOVERED_CMD), _DISCOVERED_MODE
        if env_path.startswith("wsl:"):
            wsl_parts = env_path[4:].split()
            _DISCOVERED_CMD = ["wsl"] + wsl_parts
            _DISCOVERED_MODE = "wsl"
            return list(_DISCOVERED_CMD), _DISCOVERED_MODE

    # 2. Native sage in PATH
    which_sage = shutil.which("sage")
    if which_sage:
        _DISCOVERED_CMD = [which_sage]
        _DISCOVERED_MODE = "native"
        return list(_DISCOVERED_CMD), _DISCOVERED_MODE

    # 3. WSL on Windows
    if sys.platform.startswith("win") and shutil.which("wsl"):
        cmd = _wsl_sage_probe()
        if cmd is not None:
            _DISCOVERED_CMD = cmd
            _DISCOVERED_MODE = "wsl"
            logger.info("Discovered SageMath via WSL: %s", " ".join(cmd))
            return list(_DISCOVERED_CMD), _DISCOVERED_MODE

    return None


def is_sagemath_available(force_recheck: bool = False) -> bool:
    """Returns True if SageMath is discovered and runnable on this system.

    Discovery and execution must agree: a SageMath that is only reachable through WSL is not available
    unless the operator has explicitly accepted the risk (TRIBOS_SANDBOX_SAGE_ALLOW_WSL=1), because the
    Python-level sandbox guards do not reach into WSL's separate kernel.
    """
    found = find_sagemath_command(force_recheck=force_recheck)
    if found is None:
        return False
    _cmd, mode = found
    if mode == "wsl":
        from ..agentic.sandbox import sagemath_allow_wsl

        if not sagemath_allow_wsl():
            return False
    return True


def _windows_to_wsl_path(path: str) -> str:
    """Translates a Windows path (e.g. X:\\foo\\bar) to WSL path (/mnt/x/foo/bar)."""
    abs_path = os.path.abspath(path)
    drive = abs_path[0].lower()
    rest = abs_path[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def run_sagemath_code(
    code: str,
    timeout_s: int = 60,
    *,
    memory_mb: int = 2048,
    max_output_kb: int = 256,
) -> dict[str, Any]:
    """
    Executes Python/Sage code inside the SageMath environment, under the sandbox policy.

    The submitted code is untrusted (it was written by a model that read retrieved text and uploaded data), so it is
    checked against the AST policy first, runs with a scrubbed environment and a blocked network, is bounded by a
    wall-clock timeout that kills the whole process tree, and its output is capped.

    Returns structured results with stdout, stderr, execution_time_seconds, and canonical_id.
    """
    from ..agentic.sandbox.policy import check_code

    cmd_info = find_sagemath_command()
    if not cmd_info:
        return {
            "status": "unavailable",
            "error": "SageMath executable not found. Configure TRIBOS_SAGEMATH_PATH or install SageMath.",
            "stdout": "",
            "stderr": "",
            "execution_time_seconds": 0.0,
            "canonical_id": "",
            "failure_class": "infrastructure",
        }

    cmd_prefix, mode = cmd_info
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]
    cid = f"comp:sagemath:{digest}"

    # The same static policy as the Python path, with the Sage import profile.
    violations = check_code(code, profile="sage")
    if violations:
        return {
            "status": "policy_violation",
            "failure_class": "model_code_error",
            "error": "the code was rejected by the sandbox policy",
            "violations": violations,
            "stdout": "",
            "stderr": "",
            "figures": [],
            "execution_time_seconds": 0.0,
            "mode": mode,
            "canonical_id": cid,
        }

    # WSL crosses into another kernel where the Python-level guards do not apply; it stays off unless the operator
    # explicitly accepts that.
    if mode == "wsl":
        from ..agentic.sandbox import sagemath_allow_wsl

        if not sagemath_allow_wsl():
            return {
                "status": "unavailable",
                "failure_class": "infrastructure",
                "error": (
                    "SageMath was discovered inside WSL, where the sandbox guards do not apply. "
                    "Install a native SageMath, or set TRIBOS_SANDBOX_SAGE_ALLOW_WSL=1 to accept that risk."
                ),
                "stdout": "",
                "stderr": "",
                "execution_time_seconds": 0.0,
                "mode": mode,
                "canonical_id": cid,
            }

    wrapped_code = _NETWORK_GUARD + "\n" + code + "\n" + _HARVESTER_SNIPPET
    max_bytes = max(1, int(max_output_kb)) * 1024
    effective_timeout = max(5, min(180, int(timeout_s)))

    root = tempfile.mkdtemp(prefix="tribos-sbx-")
    script_path = os.path.join(root, "cell.sage")
    stdout_path = os.path.join(root, "stdout.txt")
    stderr_path = os.path.join(root, "stderr.txt")
    with open(script_path, "w", encoding="utf-8") as tmp:
        tmp.write(wrapped_code)

    proc = None
    try:
        script_arg = _windows_to_wsl_path(script_path) if mode == "wsl" else script_path
        exec_cmd = cmd_prefix + [script_arg]

        start_time = time.monotonic()
        timed_out = False
        try:
            with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
                proc = subprocess.Popen(
                    exec_cmd,
                    stdout=out_fh,
                    stderr=err_fh,
                    env=_sandbox_env(root),
                    stdin=subprocess.DEVNULL,
                    **process_group_kwargs(),
                )
                try:
                    proc.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill_tree(proc)
        finally:
            if proc is not None and proc.poll() is None:
                kill_tree(proc)
        duration = round(time.monotonic() - start_time, 3)

        raw_stdout = _strip_ansi(read_capped(stdout_path, max_bytes))
        stderr = _strip_ansi(read_capped(stderr_path, 8 * 1024, tail=True))

        if timed_out:
            return {
                "status": "timeout",
                "failure_class": "timeout",
                "error": f"SageMath execution exceeded cutoff of {effective_timeout}s",
                "stdout": raw_stdout,
                "stderr": stderr,
                "figures": [],
                "execution_time_seconds": duration,
                "mode": mode,
                "canonical_id": cid,
            }

        figures = []
        fig_match = _FIGURES_DELIM_RE.search(raw_stdout)
        if fig_match:
            try:
                figures = json.loads(fig_match.group(1).strip())
            except Exception:
                figures = []
            stdout = _FIGURES_DELIM_RE.sub("", raw_stdout).strip()
        else:
            stdout = raw_stdout.strip()

        returncode = proc.returncode if proc is not None else 1
        if returncode == 0:
            return {
                "status": "ok",
                "stdout": stdout,
                "stderr": stderr,
                "figures": figures,
                "returncode": 0,
                "execution_time_seconds": duration,
                "mode": mode,
                "canonical_id": cid,
                "failure_class": "none",
                "limits": {"memory_mb": int(memory_mb), "timeout_s": effective_timeout},
            }
        return {
            "status": "error",
            "failure_class": classify_failure("error", stderr),
            "error": f"SageMath returned exit code {returncode}: {stderr or stdout}",
            "stdout": stdout,
            "stderr": stderr,
            "figures": figures,
            "returncode": returncode,
            "execution_time_seconds": duration,
            "mode": mode,
            "canonical_id": cid,
            "limits": {"memory_mb": int(memory_mb), "timeout_s": effective_timeout},
        }
    except Exception as exc:
        return {
            "status": "error",
            "failure_class": "infrastructure",
            "error": f"{type(exc).__name__}: {exc}",
            "stdout": "",
            "stderr": "",
            "figures": [],
            "execution_time_seconds": 0.0,
            "mode": mode,
            "canonical_id": cid,
        }
    finally:
        from ..agentic.sandbox.process import rmtree

        rmtree(root)


__all__ = [
    "classify_failure",
    "find_sagemath_command",
    "is_sagemath_available",
    "run_sagemath_code",
]
