"""Tests for Ticket F09: Invalidate stale verification after revisions and contradictory evidence.

Covers:
- S07 invalid-witness rejection: witness i = -1/7 refuting a claim on nonnegative integers (Z>=0)
  is rejected by correspondence and domain checks, tool result marked success=False and invalidated=True,
  artifact marked status="rejected", invalidated=True, historical=True.
- _evidence_xml omits passing domain checks and derivation, and emits <math_invalidated>.
- Wording-only change acts as a reuse control: math_claims.audit_answer reuses cached evaluations (reused=True).
- Answer revision reversal: revise correct answer to incorrect -> invalidates/fails; revise back -> restores verification.
- Altering domains: nonnegative integer vs real number updates record revision and domain checks appropriately.
- False generic verification prose: "independent domain checks passed" when witness was rejected
  is flagged as CLAIM_CONTRADICTED defect and stripped by remove_flagged_sentences.
- Answer revision reconciliation: reconcile_math_artifacts_with_answer updates artifacts and tool results.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tribos.agentic.math_agent import MathAgentPhase, _evidence_xml
from tribos.agentic.state import AgentState, RunBudget, RunControl
from tribos.agents.orchestration.context import RunContext
from tribos.agents.orchestration.verify import reconcile_math_artifacts_with_answer
from tribos.axiom.correspondence import check_task_correspondence
from tribos.axiom.definitions import (
    check_structured,
    domain_from_words,
    parse_structured,
)
from tribos.axiom.problem import parse_problem
from tribos.axiom.render import render_verified_answer
from tribos.tools.registry import ToolRegistry, ToolResult
from tribos.utils.output_contract import extract as extract_contract
from tribos.verify import math_claims
from tribos.verify.result_record import build_result_record
from tribos.verify.verifier import (
    DefectSeverity,
    TribosVerifier,
    removable_defects,
    remove_flagged_sentences,
)


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
    registry.register(
        ToolUniverseEntry(name="axiom_structured", description="structured", domain="math", adapter_type="LOCAL_COMPUTE", input_schema=_EmptyInput),
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


def test_f09_s07_domain_detection_and_correspondence_rejection() -> None:
    """S07: i in Z>=0 with candidate counterexample i = -1/7 is caught and rejected."""
    query = "Separately, for i in Z>=0, a(i)=16i+3,b(i)=9i+2, prove a(i)>b(i)."
    assert domain_from_words(query) == "nonnegative_integer"

    spec = parse_problem(query)
    # Simulate tool returning the candidate counterexample i = -1/7
    data = {
        "status": "disproved",
        "counterexample": {"i": "-1/7"},
        "results": [
            {
                "id": "claim",
                "op": "claim",
                "status": "disproved",
                "counterexample": "-1/7",
                "detail": "a(i) = 5/7, b(i) = 5/7",
            }
        ],
    }

    corr_ok, corr_detail, corr_meta = check_task_correspondence(spec, "axiom_structured", spec.params or {}, data)
    assert corr_ok is False
    assert "outside the problem's declared domain (nonnegative_integer)" in corr_detail
    assert corr_meta.get("mismatch") == "domain_violation"


def test_f09_s07_check_structured_fails_out_of_domain_witness() -> None:
    """check_structured fails when a witness violates the question's domain quantifier."""
    query = "Separately, for i in Z>=0, a(i)=16i+3,b(i)=9i+2, prove a(i)>b(i)."
    params, _ = parse_structured(query)
    data = {
        "results": [
            {
                "id": "claim",
                "status": "disproved",
                "counterexample": "-1/7",
                "detail": "a(i) = 5/7, b(i) = 5/7",
            }
        ]
    }
    checks = check_structured(params, data, query)
    dom_check = next((c for c in checks if "domain" in c[0]), None)
    assert dom_check is not None
    # Domain check must fail for i = -1/7
    assert dom_check[1] is False
    assert "-1/7" in dom_check[3]


def test_f09_math_agent_phase_invalidates_and_marks_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """MathAgentPhase.run marks out-of-domain witnesses as rejected, invalidated, and historical."""
    monkeypatch.setenv("TRIBOS_MATH_AGENT", "1")
    query = "Separately, for i in Z>=0, a(i)=16i+3,b(i)=9i+2, prove a(i)>b(i)."
    state = _make_dummy_agent_state(query, {"enable_math_agent": True})

    phase = MathAgentPhase()

    # Mock solve_math_problem to return the candidate run with out-of-domain witness i = -1/7
    mock_run = MagicMock()
    mock_run.status = "verified"
    mock_run.answer = {
        "text": "False: at i = -1/7, a(i) = 5/7, b(i) = 5/7.",
        "results": [{"id": "claim", "status": "disproved", "counterexample": "-1/7", "steps": ["i = -1/7"]}],
    }
    mock_run.metrics = {"tool_executions": 1, "strategy_switches": 0, "llm_calls": 0, "seconds": 0.5}
    mock_run.to_dict.return_value = {
        "status": "verified",
        "answer": mock_run.answer,
        "verification": {"status": "verified", "level": 1, "checks": [{"name": "domain", "passed": True, "level": 1}]},
        "uncertainty": [],
        "confidence": {"p_correct": 0.98, "n": 43},
        "problem": {"text": query, "kind": "structured"},
        "steps": [],
        "metrics": mock_run.metrics,
    }

    import tribos.agentic.math_agent as ma_mod

    orig_solve = ma_mod.solve_math_problem
    ma_mod.solve_math_problem = AsyncMock(return_value=mock_run)
    try:
        outcome = asyncio.run(phase.run(state))
    finally:
        ma_mod.solve_math_problem = orig_solve

    art = outcome.artifacts["math_agent"]
    assert art["status"] == "rejected"
    assert art["invalidated"] is True
    assert art["historical"] is True
    assert "outside the problem's declared domain" in art["invalidation_reason"]
    assert art["confidence"] is None

    # Check verification checks in art
    domain_check = next((c for c in art["verification"]["checks"] if c["name"] == "domain"), None)
    assert domain_check is not None
    assert domain_check["passed"] is False

    # Check ToolResult in state
    tr = state.tool_results.get("agent.math_agent.result")
    assert tr is not None
    assert tr.success is False
    assert tr.metadata["invalidated"] is True
    assert tr.metadata["historical"] is True

    # Check evidence XML
    xml = _evidence_xml(art)
    assert 'invalidated="true"' in xml
    assert "<math_invalidated" in xml
    # Passing domain checks and derivation must be omitted
    assert 'result="passed">domain' not in xml
    assert "<math_derivation" not in xml


def test_f09_reuse_control_wording_only_change() -> None:
    """Prose contributes domain/case scope, so an edited answer must be audited again even with identical $math$."""
    math_claims._AUDIT_CACHE.clear()

    query = "Evaluate n^2 + 1 for n = 3."
    text_v1 = "We calculate: $n^2 + 1 = 10$."
    text_v2 = "Therefore, computing step-by-step gives: $n^2 + 1 = 10$."

    audit_v1 = math_claims.audit_answer(text_v1, query)
    assert audit_v1.reused is False
    assert any(c.status == "passed" for c in audit_v1.claims)
    assert not audit_v1.failed

    audit_v2 = math_claims.audit_answer(text_v2, query)
    # The cache covers the entire document, including values in tables and assumptions in prose.
    assert audit_v2.reused is False
    assert audit_v2.counts() == audit_v1.counts()
    assert math_claims.audit_answer(text_v2, query).reused is True


def test_f09_answer_revision_reversal_and_domain_changes() -> None:
    """Acceptance check 2: Revise correct answer into incorrect and back; alter domains."""
    math_claims._AUDIT_CACHE.clear()

    query = "Evaluate n^2 + 1 for n = 3."

    # Step 1: Correct answer
    correct_text = "We have $n^2 + 1 = 10$."
    audit_correct = math_claims.audit_answer(correct_text, query)
    assert audit_correct.counts()["failed"] == 0
    assert audit_correct.counts()["passed"] >= 1

    # Step 2: Revise to incorrect claim
    incorrect_text = "We have $n^2 + 1 = 10$. Also $2 + 2 = 5$."
    audit_incorrect = math_claims.audit_answer(incorrect_text, query)
    assert audit_incorrect.reused is False
    assert audit_incorrect.counts()["failed"] >= 1

    # Step 3: Revise back to correct
    audit_restored = math_claims.audit_answer(correct_text, query)
    assert audit_restored.counts()["failed"] == 0

    # Step 4: Alter domain to real numbers
    q_int = "For i in Z>=0, a(i)=16i+3, b(i)=9i+2, prove a(i)>b(i)."
    real_query = "For all real i, a(i)=16i+3, b(i)=9i+2, is a(i)>b(i) an identity?"
    real_rec = build_result_record(real_query, {})
    int_rec = build_result_record(q_int, {})
    # Stamped record revisions must differ across domains
    assert real_rec.revision != int_rec.revision

    # Over real numbers, i = -1/7 gives equality a(-1/7) = b(-1/7) = 5/7
    spec_real = parse_problem(real_query)
    data_ce = {"results": [{"counterexample": "-1/7"}]}
    corr_ok_real, _, _ = check_task_correspondence(spec_real, "axiom_structured", {}, data_ce)
    assert corr_ok_real is True  # -1/7 is in real domain!

    spec_int = parse_problem(q_int)
    corr_ok_int, detail_int, _ = check_task_correspondence(spec_int, "axiom_structured", {}, data_ce)
    assert corr_ok_int is False  # -1/7 is outside nonnegative integers!
    assert "outside the problem's declared domain" in detail_int


def test_f09_verifier_flags_false_generic_domain_checks_prose() -> None:
    """Verifier detects 'independent domain checks passed' when witness was rejected or invalidated."""
    verifier = TribosVerifier()
    query = "Separately, for i in Z>=0, a(i)=16i+3,b(i)=9i+2, prove a(i)>b(i)."

    tool_results = {
        "agent.math_agent.result": ToolResult(
            success=False,
            tool_name="axiom_solve_problem",
            error="witness '-1/7' lies outside the problem's declared domain (nonnegative_integer)",
            metadata={
                "invalidated": True,
                "historical": True,
                "verification_status": "rejected",
            },
            data={
                "verification": {"checks": [{"name": "domain", "passed": False}]},
            },
        )
    }

    # Draft contains contradictory assertion repeating generic prose
    response = (
        "The witness i = -1/7 gives a(-1/7) = b(-1/7) = 5/7, which is rejected as out of domain. "
        "However, independent domain checks passed. "
        "Algebraically, a(i) - b(i) = 7i + 1 >= 1 > 0."
    )

    report = verifier.verify_response(query=query, response_markdown=response, tool_results=tool_results)
    assert not report.passed
    domain_defect = next((d for d in report.defects if d.claim == "independent domain checks passed"), None)
    assert domain_defect is not None
    assert domain_defect.category == "CLAIM_CONTRADICTED"
    assert domain_defect.severity == DefectSeverity.CRITICAL

    # Test deterministic removal of the false verification sentence
    removables = removable_defects(report)
    assert domain_defect in removables
    pruned, removed = remove_flagged_sentences(response, removables)
    body, _, _ = pruned.partition("### Evidence limitations")
    assert "independent domain checks passed" not in body
    assert len(removed) >= 1


def test_f09_reconcile_math_artifacts_with_answer_revision() -> None:
    """reconcile_math_artifacts_with_answer updates math_agent artifact and tool results when answer rejects witness."""
    run = MagicMock(spec=RunContext)
    run.candidate_response = (
        "Candidate witness i = -1/7 gives a = b = 5/7, but is rejected as out of domain. "
        "For all nonnegative integers i, a(i) - b(i) = 7i + 1 >= 1 > 0 holds."
    )
    art = {
        "status": "verified",
        "answer": {
            "results": [{"id": "claim", "status": "disproved", "counterexample": "-1/7"}],
        },
        "verification": {"checks": [{"name": "domain", "passed": True}]},
        "confidence": {"p_correct": 0.98, "n": 43},
    }
    run.execution_artifacts = {"math_agent": art}
    run.agent_state = None
    run.tool_results = {
        "agent.math_agent.result": ToolResult(
            success=True,
            tool_name="axiom_solve_problem",
            data=dict(art),
            metadata={"verification_status": "verified"},
        )
    }

    reconcile_math_artifacts_with_answer(run)

    # Artifact must be updated to rejected / invalidated / historical
    updated_art = run.execution_artifacts["math_agent"]
    assert updated_art["status"] == "rejected"
    assert updated_art["invalidated"] is True
    assert updated_art["historical"] is True
    assert "rejected in revised answer" in updated_art["invalidation_reason"]

    # ToolResult must be marked failed / invalidated
    tr = run.tool_results["agent.math_agent.result"]
    assert tr.success is False
    assert tr.metadata["invalidated"] is True
    assert tr.metadata["historical"] is True


def test_f09_render_verified_answer_skips_invalidated_artifact() -> None:
    """render_verified_answer returns None when an artifact is invalidated or rejected."""
    contract = extract_contract("Compute 2+3. Return only the result on one line, no extra text.")
    valid_art = {"status": "verified", "answer": {"results": [{"op": "evaluate", "text": "5"}]}}
    invalid_art = {"status": "verified", "invalidated": True, "answer": {"results": [{"op": "evaluate", "text": "5"}]}}

    assert render_verified_answer("compute 2+3", valid_art, contract) == "5"
    assert render_verified_answer("compute 2+3", invalid_art, contract) is None
