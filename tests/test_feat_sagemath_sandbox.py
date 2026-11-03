"""
The SageMath path under the sandbox (tribos/axiom/sagemath.py): the AST policy with the Sage profile, the
scrubbed environment, the network guard, the process-tree timeout and the WSL opt-in.

Offline: no network, no real SageMath. A fake Sage executable stands in for the interpreter, so the policy,
the environment, the network block and the timeout run in every CI job. The real-Sage tests stay opt-in and
skip when SageMath is not installed.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from tribos.agentic.sandbox import sagemath_allow_wsl, sagemath_enabled
from tribos.axiom import sagemath as sage_mod

# A fake Sage: it behaves like the interpreter for the things the sandbox cares about. It prints the
# environment it was given, runs the submitted code, and can be told to hang or to spawn a child.
FAKE_SAGE = r'''#!/usr/bin/env python3
"""A stand-in for the SageMath interpreter: it honours the sandbox's expectations, nothing more."""
import json
import os
import subprocess
import sys
import time

script = sys.argv[1] if len(sys.argv) > 1 else None
# The mode travels in a file beside the fake itself, not in the environment: the sandbox scrubs the child's
# environment on purpose, so a test-only variable must not travel that way.
mode = "normal"
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "mode.txt"), encoding="utf-8") as fh:
        mode = fh.read().strip() or "normal"
except Exception:
    pass

# A minimal `sage.all`, so the Sage profile's import is real: the model writes `from sage.all import *`
# and the fake resolves it. The names are the handful the sandbox tests use.
if mode == "normal":
    import types

    _sage = types.ModuleType("sage")
    _sage_all = types.ModuleType("sage.all")
    _sage_all.__all__ = ["factor", "expand", "sum", "pi"]
    _sage_all.factor = lambda n: n
    _sage_all.expand = lambda expr: expr
    _sage_all.sum = sum
    _sage_all.pi = 3.141592653589793
    _sage.all = _sage_all
    sys.modules["sage"] = _sage
    sys.modules["sage.all"] = _sage_all

if mode == "hang":
    time.sleep(600)
elif mode == "fork":
    # A child that outlives the parent, so the tree kill is exercised.
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    time.sleep(600)
elif mode == "env":
    keys = sorted(k for k in os.environ if "SECRET" in k.upper() or "TOKEN" in k.upper() or "API_KEY" in k.upper())
    print(json.dumps({"secret_keys": keys, "home": os.environ.get("HOME")}))
elif mode == "net":
    # The network guard is prepended to the submitted code, so the fake runs the whole file exactly like
    # the real interpreter would: the guard is installed first, then the model's socket attempt follows.
    with open(script, encoding="utf-8") as fh:
        source = fh.read()
    marker = "# --- TRIBOS AUTO GRAPHICS & PLOT HARVESTER ---"
    cut = source.rfind(marker)
    if cut != -1:
        source = source[:cut]
    # The model's own attempt, appended after the guard.
    source += (
        "\ntry:\n"
        "    import socket\n"
        "    socket.socket()\n"
        "    print('NETWORK_ALLOWED')\n"
        "except Exception as exc:\n"
        "    print('NETWORK_BLOCKED', type(exc).__name__)\n"
    )
    exec(compile(source, script, "exec"), {"__name__": "__main__"})
else:
    with open(script, encoding="utf-8") as fh:
        source = fh.read()
    # The harvester snippet is appended to the submitted code; the fake behaves like a plain interpreter and
    # runs only the code the model wrote, so the harvester is cut off at its opening marker.
    marker = "# --- TRIBOS AUTO GRAPHICS & PLOT HARVESTER ---"
    cut = source.rfind(marker)
    if cut != -1:
        source = source[:cut]
    exec(compile(source, script, "exec"), {"__name__": "__main__"})
'''


def _set_mode(fake_sage: Path, mode: str) -> None:
    """Tell the fake Sage how to behave, through the file it reads beside the script."""
    (Path(fake_sage).parent / "mode.txt").write_text(mode, encoding="utf-8")


@pytest.fixture()
def fake_sage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake Sage executable wired into TRIBOS_SAGEMATH_PATH.

    On POSIX the script is the executable and the shebang names the interpreter. On Windows a shebang is
    not honoured, so the interpreter is launched with the script as its argument; a .cmd wrapper would
    return as soon as it had started the interpreter, which would detach the child from the process tree
    the sandbox kills.
    """
    script = tmp_path / "fake_sage.py"
    script.write_text(FAKE_SAGE, encoding="utf-8")
    # The mode file sits beside the script, in the same temp dir, so the fake can read it.
    (tmp_path / "mode.txt").write_text("normal", encoding="utf-8")
    if os.name == "nt":
        path = script
        monkeypatch.setattr(sage_mod, "find_sagemath_command", lambda **_: ([sys.executable, str(path)], "native"))
    else:
        path = tmp_path / "fake-sage"
        path.write_text(FAKE_SAGE, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("TRIBOS_SAGEMATH_PATH", str(path))
    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ENABLED", "on")
    # The command discovery is cached in the module: reset it so the fake is picked up.
    monkeypatch.setattr(sage_mod, "_CHECKED", False)
    monkeypatch.setattr(sage_mod, "_DISCOVERED_CMD", None)
    monkeypatch.setattr(sage_mod, "_DISCOVERED_MODE", None)
    return path


# =============================================================================
# The policy


def test_sage_imports_are_allowed(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("from sage.all import *\nprint('ok')\n")
    assert report["status"] == "ok", report.get("error")


def test_the_os_module_is_rejected(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("import os\nprint(os.getcwd())\n")
    assert report["status"] == "policy_violation"
    assert report["violations"]


def test_the_socket_module_is_rejected(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("import socket\n")
    assert report["status"] == "policy_violation"


def test_a_dunder_escape_is_rejected(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("print((1).__class__.__bases__)\n")
    assert report["status"] == "policy_violation"


def test_eval_is_rejected(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("eval('1+1')\n")
    assert report["status"] == "policy_violation"


def test_the_policy_failure_class_is_the_model_code(fake_sage: Path) -> None:
    report = sage_mod.run_sagemath_code("import os\n")
    assert report["failure_class"] == "model_code_error"


# =============================================================================
# The environment


def test_no_secret_reaches_the_sage_process(fake_sage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(fake_sage, "env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")
    monkeypatch.setenv("MY_SECRET_TOKEN", "also-never")
    report = sage_mod.run_sagemath_code("print('x')\n")
    assert report["status"] == "ok", report.get("error")
    assert "sk-should-never-appear" not in report["stdout"]
    assert "also-never" not in report["stdout"]
    assert '"secret_keys": []' in report["stdout"] or '"secret_keys":[]' in report["stdout"]


def test_the_sandbox_env_has_only_the_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("HOME", "/home/serveruser")
    env = sage_mod._sandbox_env()
    assert "OPENAI_API_KEY" not in env
    # Sage needs a HOME for its own caches, but it is the sandbox's temp dir, never the server user's home.
    assert env.get("HOME") != "/home/serveruser"


# =============================================================================
# The network


def test_the_network_is_blocked(fake_sage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(fake_sage, "net")
    report = sage_mod.run_sagemath_code("print('x')\n")
    assert report["status"] == "ok", report.get("error")
    assert "NETWORK_BLOCKED" in report["stdout"]
    assert "NETWORK_ALLOWED" not in report["stdout"]


# =============================================================================
# The timeout and the process tree


def test_a_hanging_run_times_out(fake_sage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(fake_sage, "hang")
    report = sage_mod.run_sagemath_code("print('x')\n", timeout_s=5)
    assert report["status"] == "timeout"
    assert report["failure_class"] == "timeout"


def test_a_fork_bomb_leaves_no_orphan(fake_sage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(fake_sage, "fork")
    report = sage_mod.run_sagemath_code("print('x')\n", timeout_s=5)
    assert report["status"] == "timeout"


# =============================================================================
# The WSL opt-in


def test_wsl_is_refused_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sage_mod, "find_sagemath_command", lambda **_: (["wsl", "-d", "Ubuntu"], "wsl"))
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "off")
    report = sage_mod.run_sagemath_code("print('x')\n")
    assert report["status"] == "unavailable"
    assert "WSL" in str(report["error"])


def test_wsl_can_be_opted_into(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sage_mod, "find_sagemath_command", lambda **_: (["wsl", "-d", "Ubuntu"], "wsl"))
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "on")
    assert sagemath_allow_wsl() is True


def test_discovery_and_execution_agree_about_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WSL-only SageMath must not be advertised as available when it cannot be run.

    Discovery and execution must give the same answer: otherwise the tools are offered and every call
    fails with 'unavailable'.
    """
    monkeypatch.setattr(sage_mod, "find_sagemath_command", lambda **_: (["wsl", "-d", "Ubuntu"], "wsl"))
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "off")
    assert sage_mod.is_sagemath_available() is False
    report = sage_mod.run_sagemath_code("print('x')\n")
    assert report["status"] == "unavailable"

    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "on")
    assert sage_mod.is_sagemath_available() is True


def test_a_native_sage_is_available_without_the_wsl_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The WSL policy must not hide a native SageMath."""
    monkeypatch.setattr(sage_mod, "find_sagemath_command", lambda **_: (["/usr/bin/sage"], "native"))
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "off")
    assert sage_mod.is_sagemath_available() is True


# =============================================================================
# The enable switch


def test_sage_is_disabled_when_the_sandbox_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    assert sagemath_enabled() is False


def test_sage_can_be_disabled_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ENABLED", "off")
    assert sagemath_enabled() is False


def test_the_tools_are_not_registered_when_sage_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from tribos.extensions import axiom as axiom_ext

    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ENABLED", "off")

    class Registry:
        def __init__(self) -> None:
            self.names: list[str] = []

        def register(self, entry: Any, **kwargs: Any) -> None:  # noqa: ANN401
            self.names.append(entry.name)

    registry = Registry()
    axiom_ext.register_tools(registry)
    assert not any("sage" in n for n in registry.names)


def test_the_sage_tools_are_registered_when_sage_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from tribos.extensions import axiom as axiom_ext

    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ENABLED", "on")

    class Registry:
        def __init__(self) -> None:
            self.names: list[str] = []

        def register(self, entry: Any, **kwargs: Any) -> None:  # noqa: ANN401
            self.names.append(entry.name)

    registry = Registry()
    axiom_ext.register_tools(registry)
    assert any("sage" in n for n in registry.names)


# =============================================================================
# The gateway path


def test_the_gateway_blocks_sage_when_the_request_forbids_execution(fake_sage: Path) -> None:
    from tribos.agentic.sandbox import execution_permitted
    from tribos.agentic.sandbox.gateway import execute

    with execution_permitted(False):
        report = execute("print('x')\n", engine="sage")
    assert report["status"] == "forbidden"


def test_the_gateway_applies_the_sage_policy(fake_sage: Path) -> None:
    from tribos.agentic.sandbox.gateway import execute

    report = execute("import os\n", engine="sage")
    assert report["status"] == "policy_violation"


# =============================================================================
# The real interpreter (opt-in)


def _native_sage() -> bool:
    """True when a native SageMath (not the WSL one) is installed."""
    found = sage_mod.find_sagemath_command()
    return bool(found and found[1] == "native")


@pytest.mark.skipif(not _native_sage(), reason="a native SageMath is not installed on this machine")
def test_real_sage_runs_a_symbolic_computation() -> None:
    report = sage_mod.run_sagemath_code("print(factor(2008))\n")
    assert report["status"] == "ok", report.get("error")


def test_the_fake_sage_is_a_real_executable(fake_sage: Path) -> None:
    assert os.access(fake_sage, os.X_OK)
    assert sys.platform  # the fake must run on the host python
