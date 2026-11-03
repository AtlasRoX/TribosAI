from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tribos.agentic.confidence import computation_confidence
from tribos.agentic.math_agent import MathAgentPhase, _evidence_xml
from tribos.agentic.state import AgentState, RunBudget, RunControl
from tribos.axiom.agent import calibrated_confidence, clear_calibration_cache
from tribos.tools.registry import ToolRegistry, ToolResult
from tribos.verify.verifier import TribosVerifier


def _make_dummy_agent_state(query: str, options: dict[str, Any] | None = None) -> AgentState:
    from pydantic import BaseModel

    from tribos.tools.registry import ToolUniverseEntry

    class _EmptyInput(BaseModel):
        pass

    registry = ToolRegistry()
    registry.register(
        ToolUniverseEntry(name="axiom_solve", description="solve", domain="math", adapter_type="LOCAL_COMPUTE", input_schema=_EmptyInput),
        lambda **kw: {"status": "ok"},
    )
    budget = RunBudget()
    control = RunControl(user_id="test_user", interactive=False)
    llm = MagicMock()
    llm.available = False
    ctx = MagicMock()
    ctx.scope = "research"
    ctx.observed_identifiers.return_value = {}

    return AgentState(
        query=query,
        clean_query=query,
        ctx=ctx,
        registry=registry,
        user_id="test_user",
        thread_id="test_thread",
        model_name="test-model",
        api_key=None,
        framework="plan_execute",
        budget=budget,
        control=control,
        llm=llm,
        tool_results={},
        emit=AsyncMock(),
        send=AsyncMock(),
        options=options or {},
    )


@pytest.fixture(autouse=True)
def _reset_calibration():
    """Ensure clean calibration cache before and after each test."""
    clear_calibration_cache()
    yield
    clear_calibration_cache()


def test_f10_calibrated_confidence_grounded_fields():
    """calibrated_confidence returns traceable benchmark provenance for verified status, for a calibration fitted on
    the current code only (AUDIT-013)."""
    import json
    from pathlib import Path

    from tribos.axiom.agent import calibrated_code_sha256

    cal = json.loads(Path("tribos/axiom/calibration.json").read_text(encoding="utf-8"))
    if cal.get("code_sha256") != calibrated_code_sha256():
        assert calibrated_confidence("verified") is None  # stale calibration is not shown
        cal["code_sha256"] = calibrated_code_sha256()
    conf = calibrated_confidence("verified", cal=cal)
    assert conf is not None
    assert conf["n"] == 43
    assert conf["p_correct"] >= 0.95
    assert conf["lower_95"] >= 0.90
    assert conf["benchmark"] == "math-eval-v1"
    assert "holdout" in conf["split"]
    assert conf["scope"] == "final_expression_only"
    assert conf["is_probability"] is False
    assert "limitations" in conf


def test_f10_calibrated_confidence_rejects_unverified_and_tiny_samples():
    """Unverified, partially verified, failed, or tiny sample statuses return None."""
    assert calibrated_confidence("failed") is None
    assert calibrated_confidence("unverified") is None
    assert calibrated_confidence("partially_verified") is None  # n=1 is below significance threshold

    custom_cal = {
        "benchmark": "test-bench",
        "statuses": {
            "verified": {"n": 5, "confidence": 0.8, "lower_95": 0.5},  # n < 10 threshold
        },
    }
    assert calibrated_confidence("verified", cal=custom_cal) is None


def test_f10_calibrated_confidence_changed_record():
    """Changed benchmark record correctly updates precision, sample size, and provenance."""
    custom_cal = {
        "benchmark": "math-eval-v2",
        "fitted_on": "frozen_holdout_v2",
        "fitted_at": "2026-10-27T12:00:00Z",
        "statuses": {
            "verified": {"n": 50, "confidence": 0.88, "lower_95": 0.78},
        },
    }
    conf = calibrated_confidence("verified", cal=custom_cal)
    assert conf is not None
    assert conf["n"] == 50
    assert conf["p_correct"] == 0.88
    assert conf["lower_95"] == 0.78
    assert conf["benchmark"] == "math-eval-v2"
    assert conf["split"] == "frozen_holdout_v2"


def test_f10_computation_confidence_isolates_scope_and_prevents_leakage():
    """computation_confidence isolates benchmark precision to component_confidence, never whole answer."""
    # 1. Valid verified math
    math_art_ok = {
        "status": "verified",
        "confidence": {"p_correct": 0.9778, "lower_95": 0.918, "n": 43, "fitted_on": "math-eval-v1: holdout3"},
        "verification": {"checks": [{"name": "domain", "passed": True}]},
    }
    res_ok = computation_confidence(math_art_ok)
    assert res_ok["answer_confidence"] is None  # Never a whole-answer probability
    assert res_ok["component_confidence"] is not None
    assert res_ok["component_confidence"]["p_correct"] == 0.9778
    assert res_ok["component_confidence"]["n"] == 43
    assert res_ok["component_confidence"]["is_probability"] is False
    assert res_ok["calibration"]["calibrated"] is True
    assert res_ok["calibration"]["status"] == "measured"

    # 2. Invalidated / rejected math cannot inherit confidence from 98% badge
    math_art_inval = {
        "status": "rejected",
        "invalidated": True,
        "confidence": {"p_correct": 0.9778, "lower_95": 0.918, "n": 43},
    }
    res_inval = computation_confidence(math_art_inval)
    assert res_inval["answer_confidence"] is None
    assert res_inval["component_confidence"] is None
    assert res_inval["calibration"]["calibrated"] is False
    assert res_inval["calibration"]["status"] == "uncalibrated"
    assert "No held-out calibration is available" in res_inval["calibration"]["note"]


def test_f10_brief_notes_omit_unrequested_benchmark_metrics(monkeypatch: pytest.MonkeyPatch):
    """MathAgentPhase does not tell the writer model to paste benchmark percentages into solution prose."""
    monkeypatch.setenv("TRIBOS_MATH_AGENT", "1")
    run = MagicMock()
    run.status = "verified"
    run.metrics = {"tool_executions": 1, "strategy_switches": 0, "llm_calls": 0, "seconds": 0.1}
    mock_check = MagicMock()
    mock_check.name = "domain_check"
    mock_check.passed = True
    mock_check.level = 1
    run.verdict = MagicMock(checks=[mock_check])
    run.answer = {"text": "x = 3", "results": []}
    run.to_dict.return_value = {
        "status": "verified",
        "answer": run.answer,
        "problem": {"text": "Compute 1+2", "kind": "algebra"},
        "verification": {"checks": [{"name": "domain_check", "passed": True, "level": 1}]},
        "metrics": {"seconds": 0.1},
        "confidence": {"p_correct": 0.98, "n": 43},
        "uncertainty": [],
    }

    import tribos.agentic.math_agent as ma_mod
    monkeypatch.setattr(ma_mod, "solve_math_problem", AsyncMock(return_value=run))

    state = _make_dummy_agent_state(query="Compute 1+2", options={"enable_math_agent": True})
    phase = MathAgentPhase()

    asyncio.run(phase.run(state))

    assert len(state.brief_notes) > 0
    all_notes = " ".join(state.brief_notes)
    assert "benchmark" not in all_notes.lower()
    assert "98%" not in all_notes
    assert "n=43" not in all_notes


def test_f10_evidence_xml_contains_full_provenance():
    """_evidence_xml includes benchmark suite, split, and is_probability=false attributes."""
    art = {
        "status": "verified",
        "problem": {"text": "x = 3", "kind": "algebra"},
        "answer": {"text": "3"},
        "confidence": {
            "benchmark": "math-eval-v1",
            "split": "holdout3 set",
            "p_correct": 0.9778,
            "n": 43,
        },
    }
    xml = _evidence_xml(art)
    assert 'benchmark="math-eval-v1"' in xml
    assert 'benchmark_split="holdout3 set"' in xml
    assert 'benchmark_precision="0.9778"' in xml
    assert 'calibration_n="43"' in xml
    assert 'is_probability="false"' in xml


def test_f10_verifier_grounds_benchmark_statement():
    """Verifier grounds a benchmark assertion against the genuine benchmark record as supported."""
    verifier = TribosVerifier()
    text = (
        "The solution is x = 3.\n\n"
        "The agent's verified answers were correct in 98% of held-out benchmark problems (n=43)."
    )
    tool_results = {
        "agent.math_agent.result": ToolResult(
            tool_name="agent.math_agent.result",
            success=True,
            data={
                "status": "verified",
                "confidence": {
                    "benchmark": "math-eval-v1",
                    "split": "holdout3 set",
                    "p_correct": 0.9778,
                    "n": 43,
                    "lower_95": 0.918,
                },
            },
            metadata={"status": "verified", "invalidated": False},
        )
    }

    audit = verifier.verify_response(
        query="Solve x - 3 = 0",
        response_markdown=text,
        tool_results=tool_results,
    )

    bench_claims = [c for c in audit.claims if "benchmark" in c.claim_text.lower()]
    assert len(bench_claims) == 1
    assert bench_claims[0].status == "supported"
    assert "benchmark:math-eval-v1" in bench_claims[0].evidence[0].source_key
    assert "98%" in bench_claims[0].reason
    assert audit.unsupported_claims == 0
    assert not any(d.category == "GROUNDING" for d in audit.defects)


def test_f10_verifier_detects_contradicting_benchmark_metrics():
    """Verifier flags contradictory benchmark claims (e.g. 99.9% precision, n=500) as critical defects."""
    verifier = TribosVerifier()
    text = (
        "The solution is x = 3.\n\n"
        "The agent's verified answers were correct in 99.9% of held-out benchmark problems (n=500)."
    )
    tool_results = {
        "agent.math_agent.result": ToolResult(
            tool_name="agent.math_agent.result",
            success=True,
            data={
                "status": "verified",
                "confidence": {
                    "benchmark": "math-eval-v1",
                    "split": "holdout3 set",
                    "p_correct": 0.9778,
                    "n": 43,
                    "lower_95": 0.918,
                },
            },
            metadata={"status": "verified", "invalidated": False},
        )
    }

    audit = verifier.verify_response(
        query="Solve x - 3 = 0",
        response_markdown=text,
        tool_results=tool_results,
    )

    bench_claims = [c for c in audit.claims if "benchmark" in c.claim_text.lower()]
    assert len(bench_claims) == 1
    assert bench_claims[0].status == "contradicted"
    assert any(d.category == "CLAIM_CONTRADICTED" and "contradicts" in d.description.lower() for d in audit.defects)


def test_f10_verifier_rejects_benchmark_precision_on_invalidated_candidate():
    """Invalidated candidate mathematics cannot claim verified benchmark precision."""
    verifier = TribosVerifier()
    text = (
        "The candidate counterexample is i = -1/7.\n\n"
        "The agent's verified answers were correct in 98% of held-out benchmark problems (n=43)."
    )
    tool_results = {
        "agent.math_agent.result": ToolResult(
            tool_name="agent.math_agent.result",
            success=False,
            data={
                "status": "rejected",
                "invalidated": True,
                "confidence": None,
            },
            metadata={"status": "rejected", "invalidated": True},
        )
    }

    audit = verifier.verify_response(
        query="For i in Z>=0 prove a(i) > b(i)",
        response_markdown=text,
        tool_results=tool_results,
    )

    bench_claims = [c for c in audit.claims if "benchmark" in c.claim_text.lower()]
    assert len(bench_claims) == 1
    assert bench_claims[0].status == "contradicted"
    assert "rejected" in bench_claims[0].reason or "unverified" in bench_claims[0].reason
    assert any(d.category == "CLAIM_CONTRADICTED" for d in audit.defects)


def test_f10_self_contained_arithmetic_avoids_false_absent_literature_defects():
    """Self-contained arithmetic queries do not trigger false absent literature / completion defects."""
    verifier = TribosVerifier()
    query = "For i in Z>=0, a(i)=16i+3, b(i)=9i+2, prove a(i)>b(i)"
    answer = (
        "To prove $a(i) > b(i)$ for all $i \\in \\mathbb{Z}_{\\ge 0}$:\n\n"
        "Consider the difference:\n"
        "$$a(i) - b(i) = (16i + 3) - (9i + 2) = 7i + 1$$\n\n"
        "Since $i \\ge 0$, $7i \\ge 0$, which implies $7i + 1 \\ge 1 > 0$.\n"
        "Therefore, $a(i) > b(i)$ holds for all nonnegative integers $i$."
    )
    audit = verifier.verify_response(
        query=query,
        response_markdown=answer,
        tool_results={},
    )
    assert not any(d.category == "COMPLETION" and "unavailable" in d.description.lower() for d in audit.defects)
    assert audit.unsupported_claims == 0
