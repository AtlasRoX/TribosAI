"""
The request-level "Allow code analysis on datasets" option (tribos/agentic/sandbox/__init__.py): when it is off,
no server-side Python and no SageMath runs for that request, whatever asks for it.

Offline: no network and no real model. The permission travels in a context variable, so it reaches the worker
threads the registry tools run in, exactly like the dataset scope does.
"""

from __future__ import annotations

import asyncio

import pytest

from tribos.agentic.sandbox import execution_permitted, execution_permitted_now
from tribos.agentic.sandbox.gateway import execute
from tribos.agents import authoritative_orchestrator as orch_module

# =============================================================================
# The context variable


def test_the_permission_defaults_to_allowed() -> None:
    assert execution_permitted_now() is True


def test_the_permission_is_forbidden_inside_the_block() -> None:
    with execution_permitted(False):
        assert execution_permitted_now() is False


def test_the_permission_is_restored_after_the_block() -> None:
    with execution_permitted(False):
        pass
    assert execution_permitted_now() is True


def test_nested_blocks_restore_the_outer_value() -> None:
    with execution_permitted(False):
        with execution_permitted(True):
            assert execution_permitted_now() is True
        assert execution_permitted_now() is False
    assert execution_permitted_now() is True


def test_the_permission_reaches_a_worker_thread() -> None:
    """The registry tools run in a worker thread; the permission must travel with them."""

    async def _run() -> bool:
        return await asyncio.to_thread(execution_permitted_now)

    with execution_permitted(False):
        assert asyncio.run(_run()) is False
    assert asyncio.run(_run()) is True


# =============================================================================
# The gateway


def test_the_gateway_refuses_when_the_option_is_off() -> None:
    with execution_permitted(False):
        report = execute("result = 1\n")
    assert report["status"] == "forbidden"


def test_the_gateway_allows_when_the_option_is_on() -> None:
    with execution_permitted(True):
        report = execute("result = 1\n")
    assert report["status"] == "ok"


def test_the_refusal_names_the_option() -> None:
    with execution_permitted(False):
        report = execute("result = 1\n")
    assert "allow code analysis" in str(report["error"]).lower()


def test_the_refusal_happens_before_the_policy_check() -> None:
    """A permission refusal must not leak the policy's findings about the code."""
    with execution_permitted(False):
        report = execute("import os\n")
    assert report["status"] == "forbidden"
    assert report["violations"] == []


def test_the_refusal_happens_before_the_backend_runs() -> None:
    """No code runs at all when the option is off."""
    with execution_permitted(False):
        report = execute("open('/tmp/should-not-exist-sandbox-marker', 'w')\n")
    assert report["status"] == "forbidden"


# =============================================================================
# The request wiring


def test_the_orchestrator_binds_the_permission() -> None:
    """The orchestrator binds the request's option for the whole run."""
    import inspect

    source = inspect.getsource(orch_module.AuthoritativeOrchestrator)
    assert "execution_permitted(code_analysis_allowed)" in source
    assert 'get("enable_code_analysis", True) is not False' in source


def test_the_plan_stage_publishes_the_permission() -> None:
    """The planner reads the same option from ctx.extras, so it excludes the code tools up front."""
    import inspect

    from tribos.agents.orchestration import plan as plan_stage

    source = inspect.getsource(plan_stage)
    assert 'ctx.extras["code_analysis_forbidden"]' in source


# =============================================================================
# The planner's filter


def test_the_planner_excludes_code_tools_when_the_option_is_off() -> None:
    from tribos.agentic.plan_graph import policy_violation
    from tribos.agents.query_context import QueryContext

    ctx = QueryContext(raw_query="analyse the data", clean_query="analyse the data", scope="research")
    ctx.extras["code_analysis_forbidden"] = True
    reason = policy_violation("calcula_run_python", ctx)
    assert reason
    assert "code execution is disabled" in str(reason).lower()


def test_the_planner_allows_code_tools_when_the_option_is_on() -> None:
    from tribos.agentic.plan_graph import policy_violation
    from tribos.agents.query_context import QueryContext

    ctx = QueryContext(raw_query="analyse the data", clean_query="analyse the data", scope="research")
    ctx.extras["code_analysis_forbidden"] = False
    assert not policy_violation("calcula_run_python", ctx)


def test_the_sage_tool_is_a_code_tool() -> None:
    from tribos.agentic.plan_graph import executes_code

    assert executes_code("axiom_sagemath")
    assert executes_code("calcula_run_sagemath")
    assert executes_code("calcula_run_python")
    assert executes_code("analysis_run_python")


# =============================================================================
# The server switch


def test_the_server_switch_disables_sage_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    from tribos.agentic.sandbox import sagemath_enabled

    assert sagemath_enabled() is False
    report = execute("result = 1\n", engine="sage")
    assert report["status"] == "disabled"


def test_the_server_switch_disables_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    report = execute("result = 1\n")
    assert report["status"] == "disabled"


def test_the_calcula_tool_refuses_when_the_sandbox_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from tribos.extensions import sandbox as sandbox_ext

    monkeypatch.setenv("TRIBOS_SANDBOX", "off")
    result = sandbox_ext._run_python_impl("calcula_run_python", "result = 1\n")
    assert result.success is False
    assert result.data.get("status") == "disabled"
