from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tribos.agentic.plan_execute import PlanExecutePhase
from tribos.agentic.router import choose_framework, rule_decision
from tribos.agentic.topologies import ProgressLedger, SupervisorPhase
from tribos.agents.evidence_need import assess_evidence_need, is_self_contained
from tribos.agents.orchestration.verify import check_and_correct
from tribos.agents.query_context import QueryContext
from tribos.agents.search_plan import _content_phrases, build_search_plan
from tribos.verify.verifier import DefectItem, VerificationReport


def test_f13_self_contained_evaluations_route_to_direct_workflow():
    """Self-contained function evaluations (S01/S02) route to Direct workflow, not Supervisor."""
    q = "Let r: {2, 3, ...} -> R be defined by r(n) = n^2 + 4. Evaluate r(0), r(1), r(6), r(7)."
    ctx = QueryContext(raw_query=q, clean_query=q, enable_web_search=True)
    ctx.evidence_need = assess_evidence_need(q, ctx)

    # Test deterministic rule decision
    decision = rule_decision(q, ctx)
    assert decision.label == "Direct workflow"
    assert decision.rule in ("closed_computation", "focused", "fully_specified")
    assert decision.framework != "supervisor"

    # Test choose_framework short-circuit
    async_decision = asyncio.run(choose_framework(q, ctx))
    assert async_decision.label == "Direct workflow"
    assert async_decision.rule == "closed_computation"
    assert async_decision.framework != "supervisor"


def test_f13_self_contained_inequality_routes_to_direct_workflow():
    """Self-contained inequality proofs (S08/S09) route to Direct workflow without supervisor."""
    q = "For nonnegative integers m, prove that 5m + 4 > 2m + 1."
    ctx = QueryContext(raw_query=q, clean_query=q, enable_web_search=True)
    ctx.evidence_need = assess_evidence_need(q, ctx)

    decision = asyncio.run(choose_framework(q, ctx))
    assert decision.label == "Direct workflow"
    assert decision.framework != "supervisor"


def test_f13_verbal_self_contained_math_skips_tool_planner():
    """Self-contained mathematical statements skip the tool planner DAG to avoid redundant model calls."""
    q = "Prove that the sum of two odd integers is even."
    ctx = QueryContext(raw_query=q, clean_query=q, enable_web_search=True)
    ctx.evidence_need = assess_evidence_need(q, ctx)
    assert is_self_contained(ctx)
    assert ctx.evidence_need.level == "none"

    state = SimpleNamespace(
        ctx=ctx,
        query=q,
        clean_query=q,
        options={},
        registry=SimpleNamespace(get_entry=lambda name: SimpleNamespace(name=name)),
        bag={"routing": {"rule": "closed_computation"}},
        budget=SimpleNamespace(max_plan_nodes=10, exhausted=lambda: False),
    )
    # The planner does not apply to self-contained mathematics
    planner_phase = PlanExecutePhase()
    assert not planner_phase.applies(state)


def test_f13_research_and_status_queries_retain_capabilities():
    """Legitimate research and status lookups retain research routing and search needs."""
    q_status = "What is the status of the Riemann Hypothesis?"
    ctx_status = QueryContext(raw_query=q_status, clean_query=q_status, enable_web_search=True)
    need_status = assess_evidence_need(q_status, ctx_status)
    assert need_status.level == "required"
    assert need_status.kind == "current"

    q_bio = "What mechanisms make bacterial biofilms tolerant to antibiotics? Cite papers."
    ctx_bio = QueryContext(raw_query=q_bio, clean_query=q_bio, enable_web_search=True)
    need_bio = assess_evidence_need(q_bio, ctx_bio)
    assert need_bio.level == "required"
    assert need_bio.kind == "literature"


def test_f13_search_plan_gated_when_retrieval_not_needed():
    """Search plan produces no queries when retrieval is not needed, and excludes proof stopwords."""
    q_self = "Let r: {2, 3, ...} -> R be defined by r(n) = n^2 + 4. Evaluate r(0), r(1), r(6), r(7)."
    ctx_self = QueryContext(raw_query=q_self, clean_query=q_self, enable_web_search=True)
    ctx_self.evidence_need = assess_evidence_need(q_self, ctx_self)

    plan = build_search_plan(ctx_self, q_self)
    assert plan.concepts == []
    assert len(plan.scholarly_queries()) == 0

    # Mathematical process words are stripped from content phrases
    q_collatz = "Prove or disprove that this process reaches 1 for every positive integer. Check rule steps."
    phrases = _content_phrases(q_collatz, covered=[])
    for phrase in phrases:
        for word in phrase.lower().split():
            assert word not in ("prove", "disprove", "integer", "rules", "reaches", "process")


def test_f13_noop_revision_terminates_cleanly():
    """A revision producing zero textual change and no verification score improvement terminates without looping."""
    emitted = []

    async def mock_emit(step: str, title: str = "", text: str = "", status: str = "ok", **kwargs):
        emitted.append({"step": step, "title": title, "text": text, "status": status})

    defect = DefectItem(category="unsupported", severity="MINOR", description="minor defect", suggested_correction="fix", claim="x")

    class DummyVerifier:
        def verify_response(self, **kwargs):
            return VerificationReport(
                passed=False,
                verification_score=0.75,
                defects=[defect],
            )

    class DummyOrch:
        verifier = DummyVerifier()
        def _sanitize_answer(self, text):
            return text

    async def mock_send(msg):
        pass

    async def mock_before(text):
        pass

    run = SimpleNamespace(
        orch=DummyOrch(),
        agent_state=None,
        ctx=SimpleNamespace(observed_identifiers=lambda: {}),
        query="Test query",
        api_key=None,
        tool_results={},
        execution_artifacts={},
        successful_sources=[],
        historical_identifiers={},
        emit=mock_emit,
        send=mock_send,
        record=lambda *args, **kwargs: None,
        on_reasoning=lambda delta: None,
        before_verification=mock_before,
        reasoning_parts=[],
        synthesis_model="test-model",
        system_prompt="sys",
        synthesis_prompt="synth",
        candidate_response="The draft answer.",
        streamed_draft="The draft answer.",
        watched=lambda name, coro: coro,
    )

    # Monkeypatch stream_buffered_with_retry and get_llm to avoid real model initialization
    import tribos.agents.orchestration.verify as verify_mod
    original_stream = verify_mod.orchestrator_module().stream_buffered_with_retry
    original_get_llm = verify_mod.orchestrator_module().get_llm

    async def mock_stream(*args, **kwargs):
        return ("The draft answer.", "")

    verify_mod.orchestrator_module().stream_buffered_with_retry = mock_stream
    verify_mod.orchestrator_module().get_llm = lambda *args, **kwargs: object()

    try:
        asyncio.run(check_and_correct(run))
        noop_emissions = [e for e in emitted if "Revision produced no change" in e.get("title", "")]
        assert len(noop_emissions) == 1
        assert "No textual or verification improvement" in noop_emissions[0]["text"]
        assert run.candidate_response == "The draft answer."
    finally:
        verify_mod.orchestrator_module().stream_buffered_with_retry = original_stream
        verify_mod.orchestrator_module().get_llm = original_get_llm


def test_f13_provenance_only_improvement_recognized():
    """A revision producing zero textual change but higher verification score is recognized as provenance improvement."""
    emitted = []

    async def mock_emit(step: str, title: str = "", text: str = "", status: str = "ok", **kwargs):
        emitted.append({"step": step, "title": title, "text": text, "status": status})

    defect = DefectItem(category="unsupported", severity="MINOR", description="minor defect", suggested_correction="fix", claim="x")

    class DummyVerifier:
        def __init__(self):
            self.calls = 0

        def verify_response(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return VerificationReport(
                    passed=False,
                    verification_score=0.70,
                    defects=[defect],
                )
            # Same text, but fewer defects / better grounding
            return VerificationReport(
                passed=True,
                verification_score=0.95,
                defects=[],
            )

    class DummyOrch:
        def __init__(self):
            self.verifier = DummyVerifier()

        def _sanitize_answer(self, text):
            return text

    async def mock_before(text):
        pass

    async def mock_send(msg):
        pass

    run = SimpleNamespace(
        orch=DummyOrch(),
        agent_state=None,
        ctx=SimpleNamespace(observed_identifiers=lambda: {}),
        query="Test query",
        api_key=None,
        tool_results={},
        execution_artifacts={},
        successful_sources=[],
        historical_identifiers={},
        emit=mock_emit,
        send=mock_send,
        record=lambda *args, **kwargs: None,
        on_reasoning=lambda delta: None,
        before_verification=mock_before,
        reasoning_parts=[],
        synthesis_model="test-model",
        system_prompt="sys",
        synthesis_prompt="synth",
        candidate_response="Draft with weak grounding.",
        streamed_draft="Draft with weak grounding.",
        watched=lambda name, coro: coro,
    )

    import tribos.agents.orchestration.verify as verify_mod
    original_stream = verify_mod.orchestrator_module().stream_buffered_with_retry
    original_get_llm = verify_mod.orchestrator_module().get_llm

    async def mock_stream(*args, **kwargs):
        return ("Draft with weak grounding.", "")

    verify_mod.orchestrator_module().stream_buffered_with_retry = mock_stream
    verify_mod.orchestrator_module().get_llm = lambda *args, **kwargs: object()

    try:
        asyncio.run(check_and_correct(run))
        prov_emissions = [e for e in emitted if "Revised claim provenance" in e.get("title", "")]
        assert len(prov_emissions) == 1
        assert "provenance and verification grounding improved" in prov_emissions[0]["text"]
    finally:
        verify_mod.orchestrator_module().stream_buffered_with_retry = original_stream
        verify_mod.orchestrator_module().get_llm = original_get_llm


def test_f13_supervisor_terminates_repeated_delegations():
    """SupervisorPhase terminates immediately when the model repeats identical specialist delegations."""
    dialogue_log = []

    class DummyDialogue:
        def add(self, actor, action, target, text):
            dialogue_log.append((actor, action, text))
        def step_id(self, name):
            return "step-1"
        def save(self):
            pass

    async def mock_step(*args, **kwargs):
        pass

    state = SimpleNamespace(
        ctx=SimpleNamespace(scope="research"),
        clean_query="Evaluate function",
        query="Evaluate function",
        tool_results={},
        sub_questions=[],
        registry=SimpleNamespace(list_tools=lambda: []),
        budget=SimpleNamespace(exhausted=lambda: False),
        control=SimpleNamespace(checkpoint=lambda: None),
        bag={},
        mark_phase=lambda *args: None,
        step=mock_step,
    )

    # Mock specialists
    sp = SimpleNamespace(
        name="calcula",
        label="Computation Specialist",
        tool_names=lambda: ["calcula_run_python"],
        spec=SimpleNamespace(role="Run mathematical computation."),
    )

    repeat_reply = ProgressLedger(
        is_done=False,
        next_specialist="calcula",
        instruction="compute f(2)",
        is_looping=False,
        is_progressing=True,
        reason="",
    )

    phase = SupervisorPhase()

    async def mock_ask_json(*args, **kwargs):
        return repeat_reply

    import tribos.agentic.topologies as topo_mod
    orig_ask = topo_mod.ask_json
    orig_team = topo_mod.team_specialists
    orig_dialogue = topo_mod.Dialogue
    orig_run_sp = topo_mod.run_specialist

    topo_mod.ask_json = mock_ask_json
    topo_mod.team_specialists = lambda s: {"calcula": sp}
    topo_mod.Dialogue = lambda *args, **kwargs: DummyDialogue()

    async def dummy_run_sp(*args, **kwargs):
        return {"calls": 1, "summary": "Done"}

    topo_mod.run_specialist = dummy_run_sp

    try:
        asyncio.run(phase.run(state))
        stops = [entry for entry in dialogue_log if entry[1] == "stop"]
        assert len(stops) >= 1
        assert "unproductive repair loop" in stops[0][2]
    finally:
        topo_mod.ask_json = orig_ask
        topo_mod.team_specialists = orig_team
        topo_mod.Dialogue = orig_dialogue
        topo_mod.run_specialist = orig_run_sp
