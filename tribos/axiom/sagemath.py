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

logger = logging.getLogger(__name__)

_DISCOVERED_CMD: list[str] | None = None
_DISCOVERED_MODE: str | None = None
_CHECKED = False

# Environment passed to Sage: only what the interpreter (or wsl.exe) needs to start. Model-written code never
# sees the server's API keys, tokens or database credentials.
_ENV_ALLOW = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TZ", "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "LOCALAPPDATA", "PROGRAMDATA", "SYSTEMDRIVE",
    "DOT_SAGE", "SAGE_ROOT", "SAGE_LOCAL", "MPLBACKEND",
})
_SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.I)
# stderr markers of a broken environment (not of the submitted code)
_INFRA_ERROR_RE = re.compile(
    r"command not found|cannot execute|Wsl/|Permission denied|MemoryError|Killed|out of memory|GLIBC|"
    r"ImportError: libsage|sage: not found",
    re.I,
)

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


def _sandbox_env() -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if (k.upper() in _ENV_ALLOW or k.upper().startswith("LC_")) and not _SECRET_NAME_RE.search(k)
    }
    env["WSLENV"] = ""  # share no Windows variables with the WSL side
    env.setdefault("MPLBACKEND", "Agg")
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
    """Returns True if SageMath is discovered and runnable on this system."""
    return find_sagemath_command(force_recheck=force_recheck) is not None


def _windows_to_wsl_path(path: str) -> str:
    """Translates a Windows path (e.g. X:\\foo\\bar) to WSL path (/mnt/x/foo/bar)."""
    abs_path = os.path.abspath(path)
    drive = abs_path[0].lower()
    rest = abs_path[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def run_sagemath_code(code: str, timeout_s: int = 60) -> dict[str, Any]:
    """
    Executes Python/Sage code inside the SageMath environment.
    Returns structured results with stdout, stderr, execution_time_seconds, and canonical_id.
    """
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

    wrapped_code = code + "\n" + _HARVESTER_SNIPPET

    with tempfile.NamedTemporaryFile("w", suffix=".sage", delete=False, encoding="utf-8") as tmp:
        tmp.write(wrapped_code)
        tmp_name = tmp.name

    try:
        script_arg = _windows_to_wsl_path(tmp_name) if mode == "wsl" else tmp_name
        exec_cmd = cmd_prefix + [script_arg]

        start_time = time.monotonic()
        proc = subprocess.run(
            exec_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5, min(180, int(timeout_s))),
            env=_sandbox_env(),
            stdin=subprocess.DEVNULL,
        )
        duration = round(time.monotonic() - start_time, 3)

        raw_stdout = _strip_ansi(proc.stdout)
        stderr = _strip_ansi(proc.stderr)

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

        if proc.returncode == 0:
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
            }
        return {
            "status": "error",
            "failure_class": classify_failure("error", stderr),
            "error": f"SageMath returned exit code {proc.returncode}: {stderr or stdout}",
            "stdout": stdout,
            "stderr": stderr,
            "figures": figures,
            "returncode": proc.returncode,
            "execution_time_seconds": duration,
            "mode": mode,
            "canonical_id": cid,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "failure_class": "timeout",
            "error": f"SageMath execution exceeded cutoff of {timeout_s}s",
            "stdout": "",
            "stderr": "",
            "figures": [],
            "execution_time_seconds": float(timeout_s),
            "mode": mode,
            "canonical_id": cid,
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
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


__all__ = [
    "classify_failure",
    "find_sagemath_command",
    "is_sagemath_available",
    "run_sagemath_code",
]
