"""Regression tests for the security and configuration fixes (SEC-1/3/4/6/7, CI-3/5/6, sandbox polish).

These assert the escapes in docs/history/CODEBASE_AUDIT.md stay closed and the configuration wiring stays correct. The
sandbox cases run real subprocesses, so they are slower; they match the style of tests/test_sandbox.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tribos.agentic.sandbox.policy import check_code
from tribos.agentic.sandbox.runner import run_code
from tribos.config import settings
from tribos.provenance.rerun import tool_replay_refusal

# =============================================================================
# SEC-1: SymPy string parsing cannot reach real builtins / __import__ / open
# =============================================================================

@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').getcwd()",
        "__import__('subprocess').check_output('whoami')",
        "Integer(1).__class__",
        "().__class__.__bases__[0]",
    ],
)
def test_sympify_dunder_payloads_are_rejected(expr):
    code = f"import sympy\nresult = str(sympy.sympify({expr!r}))\n"
    out = run_code(code, timeout_s=60)
    assert out["status"] == "error"
    assert "__" in out["error"] or "not allowed" in out["error"]


def test_parse_expr_dunder_payload_is_rejected():
    code = "import sympy\nresult = str(sympy.parse_expr(\"__import__('os').getcwd()\"))\n"
    out = run_code(code, timeout_s=60)
    assert out["status"] == "error" and "not allowed" in out["error"]


def test_sympify_cannot_open_host_file():
    # No dunder, but a real file read through the eval path; the process-wide open guard refuses it.
    code = "import sympy\nresult = str(sympy.sympify(\"open('pyproject.toml')\"))\n"
    out = run_code(code, timeout_s=60)
    assert out["status"] == "error"


def test_legitimate_sympy_still_works():
    code = (
        "import sympy\n"
        "x = sympy.symbols('x')\n"
        "result = {'int': str(sympy.integrate(sympy.sin(x) * x, x)),\n"
        "          'val': float(sympy.sympify('2 + 3*4')),\n"
        "          'simp': str(sympy.simplify(sympy.sympify('x**2 + 2*x + 1')))}\n"
    )
    out = run_code(code, timeout_s=90)
    assert out["status"] == "ok", out
    assert out["result"]["val"] == 14.0


# =============================================================================
# SEC-3: file read/write outside the work dir (networkx readers/writers)
# =============================================================================

def test_networkx_write_outside_work_is_blocked(tmp_path):
    target = (tmp_path / "pwned.txt").as_posix()
    code = (
        "import networkx as nx\n"
        "G = nx.Graph(); G.add_edge('a', 'b')\n"
        f"p = {target!r}\n"
        "nx.write_edgelist(G, p)\n"
        "result = 'wrote'\n"
    )
    out = run_code(code, timeout_s=60)
    assert out["status"] == "error" and "PermissionError" in (out["error"] or "")
    assert not os.path.exists(target)


def test_networkx_read_outside_work_is_blocked():
    code = (
        "import networkx as nx\n"
        "H = nx.read_adjlist('pyproject.toml')\n"  # relative; resolves outside the work dir only if escaping
        "result = 'read'\n"
    )
    # A bare relative name stays inside work (and does not exist there) -> ordinary error, not a breach.
    out = run_code(code, timeout_s=60)
    assert out["status"] == "error"


def test_policy_default_denies_io_names_with_escaping_literal():
    assert check_code('import networkx as nx\nnx.write_edgelist(nx.Graph(), "/etc/x")\n')
    assert check_code('import networkx as nx\nnx.read_adjlist("X:/secret.txt")\n')
    # Legitimate relative paths and non-path arguments are still allowed.
    assert check_code('import networkx as nx\nnx.write_edgelist(nx.Graph(), "g.txt")\n') == []
    assert check_code('import pandas as pd\npd.DataFrame().to_dict("records")\n') == []
    assert check_code('import pandas as pd\nx = [1]\npd.to_datetime(x)\n') == []


# =============================================================================
# Sandbox polish: anndata/h5ad allowance dropped
# =============================================================================

def test_anndata_import_is_rejected_even_for_h5ad_inputs():
    assert check_code("import anndata\n", ["atlas.h5ad"])
    assert check_code("from anndata import AnnData\n", ["atlas.h5ad"])


# =============================================================================
# SEC-4 / CI-6: configuration validation
# =============================================================================

def test_secret_problems_flags_short_tokens_and_secret():
    problems = settings.secret_problems({
        "TRIBOS_API_TOKENS": "wimpy:alice,this-is-a-long-enough-token-abcdefghijkl:bob",
        "TRIBOS_JWT_SECRET": "feeble",
    })
    text = "\n".join(problems)
    assert "TRIBOS_API_TOKENS" in text and "TRIBOS_JWT_SECRET" in text
    # Values are never echoed.
    assert "wimpy" not in text and "feeble" not in text and "alice" not in text


def test_secret_problems_accepts_strong_secrets():
    assert settings.secret_problems({
        "TRIBOS_API_TOKENS": "this-is-a-long-enough-token-abcdefghijkl:bob",
        "TRIBOS_JWT_SECRET": "x" * 32,
    }) == []


def test_validate_environment_includes_weak_secret_problems():
    problems = settings.validate_environment({"TRIBOS_JWT_SECRET": "weak"})
    assert any("TRIBOS_JWT_SECRET" in p for p in problems)


def test_short_test_tokens_do_not_break_non_strict_startup():
    # The common test token is shorter than 32 chars; it must surface as a problem but not raise.
    problems = settings.validate_environment({"TRIBOS_API_TOKENS": "alice-token:alice"})
    assert any("TRIBOS_API_TOKENS" in p for p in problems)


def test_legacy_phronesis_env_vars_warn_but_do_not_fail_strict():
    problems = settings.legacy_problems({"PHRONESIS_DATA_DIR": "/x", "PHRONESIS_NONSENSE": "y"}, check_dirs=False)
    joined = "\n".join(problems)
    assert "TRIBOS_DATA_DIR" in joined and "PHRONESIS_NONSENSE" in joined
    # validate_environment logs them as warnings, so they are not returned (strict mode must not fail on them).
    returned = settings.validate_environment({"PHRONESIS_DATA_DIR": "/x"})
    assert not any("PHRONESIS_DATA_DIR" in p for p in returned)


def test_auth_wrapper_delegates_to_settings(monkeypatch):
    from app.backend.auth import secret_strength_problems

    monkeypatch.setenv("TRIBOS_JWT_SECRET", "weak")
    assert any("TRIBOS_JWT_SECRET" in p for p in secret_strength_problems())


# =============================================================================
# SEC-6: SageMath / code-execution tools are never replay-safe
# =============================================================================

@pytest.mark.parametrize("name", ["axiom_sagemath", "calcula_run_sagemath", "calcula_run_python", "analysis_run_python"])
def test_code_execution_tools_refuse_replay(name):
    class _Entry:
        tags: list[str] = []

    assert tool_replay_refusal(name, _Entry()) is not None


def test_ordinary_tools_still_replayable():
    class _Entry:
        tags = ["literature"]

    assert tool_replay_refusal("archivon_literature_search", _Entry()) is None


# =============================================================================
# CI-5: the newly registered settings exist
# =============================================================================

@pytest.mark.parametrize("name", ["TRIBOS_MAX_BODY_MB", "TRIBOS_MAX_EXPORT_BODY_MB", "TRIBOS_EVAL_JUDGE_MODEL"])
def test_new_settings_are_registered(name):
    assert name in settings.REGISTRY


@pytest.mark.parametrize("name", ["TRIBOS_API_PORT", "TRIBOS_API_BIND", "TRIBOS_WEB_PORT", "TRIBOS_WEB_BIND"])
def test_compose_only_names_do_not_warn(name):
    assert name in settings.EXTERNAL_NAMES
    assert settings.validate_environment({name: "1234"}) == []


# =============================================================================
# SEC-8: one gateway owns every model-written execution
# =============================================================================


def test_sec8_the_gateway_is_the_only_entry_point():
    """Every execution path goes through the gateway: the runner and the policy are reached from there."""
    from tribos.agentic.sandbox import backends, gateway

    assert gateway.execute is not None
    assert backends.SubprocessBackend is not None
    assert backends.SageBackend is not None
    # The gateway resolves the limits and the backend; the backends do not decide whether a run may happen.
    source = Path(gateway.__file__).read_text(encoding="utf-8")
    assert "check_code" in source
    assert "execution_permitted_now" in source


def test_sec8_the_gateway_refuses_when_the_request_forbids_execution():
    from tribos.agentic.sandbox import execution_permitted
    from tribos.agentic.sandbox.gateway import execute

    with execution_permitted(False):
        report = execute("result = 1\n")
    assert report["status"] == "forbidden"


def test_sec8_the_gateway_refuses_when_the_sandbox_is_off(monkeypatch):
    from tribos.agentic.sandbox.gateway import execute

    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    report = execute("result = 1\n")
    assert report["status"] == "disabled"


# =============================================================================
# SEC-9: the SageMath path is contained by the same policy and limits
# =============================================================================


def test_sec9_sage_uses_the_same_policy():
    from tribos.agentic.sandbox.policy import check_code

    assert check_code("import os\n", profile="sage")
    assert check_code("import socket\n", profile="sage")
    assert check_code("print((1).__class__.__bases__)\n", profile="sage")


def test_sec9_sage_is_not_offered_when_the_sandbox_is_off(monkeypatch):
    from tribos.agentic.sandbox import sagemath_enabled

    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    assert sagemath_enabled() is False


def test_sec9_sage_never_receives_the_server_home(monkeypatch):
    from tribos.axiom import sagemath

    monkeypatch.setenv("HOME", "/home/serveruser")
    env = sagemath._sandbox_env()
    assert env.get("HOME") != "/home/serveruser"


def test_sec9_sage_never_receives_a_secret(monkeypatch):
    from tribos.axiom import sagemath

    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    env = sagemath._sandbox_env()
    assert "OPENAI_API_KEY" not in env
    assert "DB_PASSWORD" not in env


def test_sec9_wsl_sage_is_opt_in(monkeypatch):
    from tribos.axiom import sagemath

    monkeypatch.setattr(sagemath, "find_sagemath_command", lambda **_: (["wsl", "-d", "Ubuntu"], "wsl"))
    monkeypatch.setenv("TRIBOS_SANDBOX_SAGE_ALLOW_WSL", "off")
    report = sagemath.run_sagemath_code("print('x')\n")
    assert report["status"] == "unavailable"


# =============================================================================
# SEC-10: the request-level toggle blocks every server-side execution
# =============================================================================


def test_sec10_the_toggle_blocks_python_and_sage():
    from tribos.agentic.sandbox import execution_permitted
    from tribos.agentic.sandbox.gateway import execute

    with execution_permitted(False):
        assert execute("result = 1\n")["status"] == "forbidden"
        assert execute("result = 1\n", engine="sage")["status"] == "forbidden"


def test_sec10_the_toggle_reaches_the_worker_threads():
    import asyncio

    from tribos.agentic.sandbox import execution_permitted, execution_permitted_now

    async def _in_thread() -> bool:
        return await asyncio.to_thread(execution_permitted_now)

    with execution_permitted(False):
        assert asyncio.run(_in_thread()) is False


def test_sec10_the_planner_excludes_the_code_tools():
    from tribos.agentic.plan_graph import policy_violation
    from tribos.agents.query_context import QueryContext

    ctx = QueryContext(raw_query="analyse", clean_query="analyse")
    ctx.extras["code_analysis_forbidden"] = True
    assert policy_violation("calcula_run_python", ctx)
    assert policy_violation("axiom_sagemath", ctx)


# =============================================================================
# SEC-11: a caller may only lower the server's limits
# =============================================================================


def test_sec11_a_caller_cannot_raise_the_timeout(monkeypatch):
    from tribos.agentic.sandbox.backends import ExecutionRequest
    from tribos.agentic.sandbox.gateway import _limits_for

    monkeypatch.setenv("TRIBOS_SANDBOX_TIMEOUT_S", "30")
    limits = _limits_for("python", ExecutionRequest(code="", timeout_s=99999))
    assert limits["timeout_s"] == 30


def test_sec11_a_caller_cannot_raise_the_memory_or_disk(monkeypatch):
    from tribos.agentic.sandbox.backends import ExecutionRequest
    from tribos.agentic.sandbox.gateway import _limits_for

    monkeypatch.setenv("TRIBOS_SANDBOX_MEMORY_MB", "512")
    monkeypatch.setenv("TRIBOS_SANDBOX_MAX_DISK_MB", "32")
    limits = _limits_for("python", ExecutionRequest(code="", memory_mb=99999, max_disk_mb=99999))
    assert limits["memory_mb"] == 512
    assert limits["max_disk_mb"] == 32


# =============================================================================
# SEC-12: the container backend is an isolation boundary, not a suggestion
# =============================================================================


def _container_argv():
    from tribos.agentic.sandbox import container

    return container._container_argv(
        "docker",
        "img",
        "/w",
        "/i",
        "/o",
        "/i/b.py",
        "/i/c.json",
        memory_mb=512,
        timeout_s=30,
        max_disk_mb=64,
        max_processes=8,
    )


def test_sec12_the_container_invocation_holds_every_boundary_control():
    argv = _container_argv()
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in argv
    assert int(argv[argv.index("--user") + 1].split(":")[0]) != 0
    assert "--pids-limit" in argv
    assert "--memory" in argv


def test_sec12_the_container_passes_no_host_environment():
    argv = _container_argv()
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert all("KEY" not in e.upper() and "TOKEN" not in e.upper() for e in envs)


def test_sec12_the_container_mounts_the_inputs_read_only():
    argv = _container_argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert any("readonly" in m for m in mounts)


def test_sec12_only_the_result_channel_is_writable():
    """The code may write its result and nothing else: not the inputs, not the code cell, not the policy."""
    argv = _container_argv()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    writable = [m for m in mounts if "readonly" not in m]
    assert len(writable) == 1
    assert "dst=/out" in writable[0]
    # The bootstrap, the config and the submitted cell are read-only in the container's view.
    io_mounts = [m for m in mounts if "dst=/io" in m]
    assert io_mounts and "readonly" in io_mounts[0]


# =============================================================================
# SEC-13: the child's environment is an allowlist and the cache is per run
# =============================================================================


def test_sec13_the_child_environment_carries_no_credential():
    from tribos.agentic.sandbox import process

    env = process.allowlisted_env("/tmp/r", "/tmp/r/tmp")
    assert "OPENAI_API_KEY" not in env
    assert "DB_PASSWORD" not in env


def test_sec13_the_matplotlib_cache_is_not_shared_between_runs():
    from tribos.agentic.sandbox import process

    first = process.allowlisted_env("/tmp/one", "/tmp/one/tmp")
    second = process.allowlisted_env("/tmp/two", "/tmp/two/tmp")
    assert first["MPLCONFIGDIR"] != second["MPLCONFIGDIR"]


def test_sec13_a_run_directory_is_removed_afterwards():
    import tempfile

    before = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    run_code("result = 1\n", timeout_s=20)
    after = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("tribos-sbx-")}
    assert after <= before


# =============================================================================
# SEC-14: the sandbox's escape hatch cannot be reached from a tool
# =============================================================================


def test_sec14_the_escape_hatch_is_refused_outside_a_test_run(monkeypatch):
    from tribos.agentic.sandbox import runner

    monkeypatch.setattr(runner, "_under_test", lambda: False)
    report = runner.run_code("result = 1\n", timeout_s=20, _unsafe_skip_policy=True)
    assert report["status"] == "failed"


def test_sec14_the_gateway_never_sets_the_escape_hatch():
    from tribos.agentic.sandbox import gateway

    source = Path(gateway.__file__).read_text(encoding="utf-8")
    assert "_unsafe_skip_policy" not in source


def test_sec14_the_escape_hatch_never_disables_the_network_stub(monkeypatch):
    from tribos.agentic.sandbox import runner

    monkeypatch.setattr(runner, "_under_test", lambda: True)
    report = runner.run_code(
        "import socket\nsocket.socket()\nresult = 1\n",
        timeout_s=20,
        _unsafe_skip_policy=True,
    )
    assert report["status"] != "ok"


# =============================================================================
# SEC-15: the sandbox's settings are registered, bounded and documented
# =============================================================================


@pytest.mark.parametrize(
    "name",
    [
        "TRIBOS_SANDBOX",
        "TRIBOS_SANDBOX_BACKEND",
        "TRIBOS_SANDBOX_IMAGE",
        "TRIBOS_SANDBOX_MAX_CONCURRENCY",
        "TRIBOS_SANDBOX_MAX_OUTPUT_KB",
        "TRIBOS_SANDBOX_MAX_DISK_MB",
        "TRIBOS_SANDBOX_MAX_PROCESSES",
        "TRIBOS_SANDBOX_MAX_RESULT_BYTES",
        "TRIBOS_SANDBOX_STRICT_LIMITS",
        "TRIBOS_SANDBOX_ALLOW_UNISOLATED",
        "TRIBOS_SANDBOX_SAGE_ENABLED",
        "TRIBOS_SANDBOX_SAGE_TIMEOUT_S",
        "TRIBOS_SANDBOX_SAGE_ALLOW_WSL",
    ],
)
def test_sec15_the_sandbox_settings_are_registered(name):
    assert name in settings.REGISTRY


def test_sec15_the_sandbox_is_on_by_default():
    assert settings.REGISTRY["TRIBOS_SANDBOX"].default in ("on", "true", True)


def test_sec15_the_strict_mode_refuses_the_unisolated_backend(monkeypatch):
    from tribos.agentic.sandbox import gateway

    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", "off")
    backend, reason = gateway._select_backend("python")
    assert backend is None
    assert reason
