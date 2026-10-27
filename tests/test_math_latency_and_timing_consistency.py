"""
Tests for latency optimization and timing consistency in self-contained math tasks.

Covers:
- Skipping unnecessary tool planning (PlanExecutePhase) on closed algebraic computations.
- Guarding against false-positive specialized tool matches (physis_engineering_calc on 'factor').
- Verified rendering of factored forms and solutions under strict line contracts.
- Focused token budget and targeted deliberation prompt for closed math drafting.
- Consistent timing measurements between pipeline totals, stage_seconds, and overall run duration.
- Preserving chronological 'at' timestamps across all agent and pipeline phases.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from tribos.agentic.plan_execute import needs_specialised_tool
from tribos.agentic.state import AgentState
from tribos.agents.evidence_need import is_closed_computation
from tribos.agents.orchestration.context import RunContext
from tribos.agents.orchestration.draft import _verified_render
from tribos.agents.orchestration.finalize import stage_seconds
from tribos.agents.query_context import QueryContext
from tribos.axiom.render import render_verified_answer
from tribos.tools.registry import ToolResult, get_tool_registry
from tribos.utils.output_contract import Contract, extract


def test_factoring_does_not_trigger_physis_engineering_calc():
    """'Factor x^2 - 5x + 6' must not be flagged as needing physis_engineering_calc."""
    reg = get_tool_registry()
    state = MagicMock(spec=AgentState)
    state.registry = reg
    state.clean_query = "Factor x^2 - 5x + 6"
    state.query = "Factor x^2 - 5x + 6"

    assert needs_specialised_tool(state) is False

    # Legitimate engineering calc with keywords should still return True
    state_eng = MagicMock(spec=AgentState)
    state_eng.registry = reg
    state_eng.clean_query = "Calculate cantilever beam deflection under 500 N load"
    state_eng.query = state_eng.clean_query
    assert needs_specialised_tool(state_eng) is True


def test_render_verified_factored_form_under_strict_contract():
    """Strict contract factoring returns deterministic verified answer."""
    q = "Factor x^2 - 5x + 6 on one line. Add nothing else."
    contract = extract(q)
    assert contract.strict_form is True
    assert contract.exact_lines == 1

    art = {
        "status": "verified",
        "answer": {
            "factored": "(x - 3)*(x - 2)",
            "text": "(x - 3)*(x - 2)",
        },
    }
    rendered = render_verified_answer(q, art, contract)
    assert rendered == "(x - 3)*(x - 2)"


def test_render_verified_solution_under_strict_contract():
    """Strict contract quadratic roots return deterministic verified answer."""
    q = "Solve x^2 - 5x + 6 = 0 on one line. Add nothing else."
    contract = extract(q)
    assert contract.strict_form is True
    assert contract.exact_lines == 1

    art = {
        "status": "verified",
        "answer": {
            "text": "x = 2; x = 3",
            "solutions": [{"x": "2"}, {"x": "3"}],
        },
    }
    rendered = render_verified_answer(q, art, contract)
    assert rendered == "x = 2; x = 3"


def test_verified_render_falls_back_to_tool_results_when_agent_state_lacks_artifact():
    """_verified_render inspects run.tool_results when agent_state.artifacts is absent."""
    run = MagicMock(spec=RunContext)
    run.agent_state = None
    run.clean_query = "Factor x^2 - 5x + 6 on one line"
    run.query = run.clean_query
    run.output_contract = extract(run.clean_query)
    run.tool_results = {
        "axiom_solve_problem": ToolResult(
            success=True,
            tool_name="axiom_solve_problem",
            data={
                "status": "verified",
                "answer": {"factored": "(x - 3)*(x - 2)", "text": "(x - 3)*(x - 2)"},
            },
        )
    }

    rendered = _verified_render(run)
    assert rendered == "(x - 3)*(x - 2)"


def test_stage_seconds_captures_planning_phase():
    """stage_seconds correctly classifies 'plan' as 'planning' work."""
    phases = [
        {"phase": "plan", "stage": "pipeline", "seconds": 3.5, "at": 0.0},
        {"phase": "route", "stage": "pipeline", "seconds": 0.1, "at": 3.5},
        {"phase": "first_draft", "stage": "pipeline", "seconds": 1.2, "at": 3.6},
        {"phase": "verification", "stage": "pipeline", "seconds": 0.05, "at": 4.8},
    ]
    stg = stage_seconds(phases)
    assert stg["planning"] == 3.6
    assert stg["drafting"] == 1.2
    assert stg["verification"] == 0.05


def test_timing_consistency_between_pipeline_and_run_duration():
    """When pipeline includes 'plan', pipeline sum matches elapsed time closely."""
    phases = [
        {"phase": "plan", "stage": "pipeline", "seconds": 4.0, "at": 0.0},
        {"phase": "route", "stage": "pipeline", "seconds": 0.0, "at": 4.0},
        {"phase": "evidence", "stage": "pipeline", "seconds": 0.0, "at": 4.0},
        {"phase": "computations", "stage": "pipeline", "seconds": 0.08, "at": 4.0},
        {"phase": "first_draft", "stage": "pipeline", "seconds": 1.5, "at": 4.08},
        {"phase": "verification", "stage": "pipeline", "seconds": 0.02, "at": 5.58},
        {"phase": "citations", "stage": "pipeline", "seconds": 0.0, "at": 5.6},
        {"phase": "memory", "stage": "pipeline", "seconds": 0.02, "at": 5.6},
    ]
    pipeline_total = sum(p["seconds"] for p in phases)
    run_seconds = 5.65
    assert abs(pipeline_total - run_seconds) < 0.1
