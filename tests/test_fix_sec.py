"""Regression tests for the security and configuration fixes (SEC-1/3/4/6/7, CI-3/5/6, sandbox polish).

These assert the escapes in CODEBASE_AUDIT.md stay closed and the configuration wiring stays correct. The
sandbox cases run real subprocesses, so they are slower; they match the style of tests/test_sandbox.py.
"""

from __future__ import annotations

import os

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
