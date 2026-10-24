"""
Query planner (feature 3): deterministic parsing, the offline lexicon, the live resolver seen through a fake
registry tool fed by recorded upstream responses, hard guards, model-assisted planner degradation, the latency
budget, verifier acceptance of resolved identifiers and the <query_entities> evidence block. No network.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests.fakes import called, make_offline_orchestrator
from tribos.agents import authoritative_orchestrator as orch_module
from tribos.agents import query_planner as qp
from tribos.agents.discovery import DiscoveryEngine
from tribos.agents.query_context import QueryContext, ResolvedEntity
from tribos.tools.registry import ToolResult


async def _ctx(query: str, registry: Any = None, **kw: Any) -> QueryContext:
    args: dict[str, Any] = {
        "query": query, "clean_query": query, "registry": registry, "enable_web_search": False, "attachments": [], "attachment_errors": [],
        "user_id": "u", "thread_id": "t", "model_name": "m", "api_key": None,
    }
    args.update(kw)
    return await qp.build_query_context(**args)


def _genes(ctx: QueryContext) -> list[str]:
    return [g.label for g in ctx.genes]


# =============================================================================
# 1. Deterministic parsing and the offline STEM lexicon
# =============================================================================

@pytest.mark.asyncio
async def test_stem_concepts_and_theorems():
    ctx = await _ctx("We met to discuss Navier-Stokes equations")
    assert any(e.label == "Navier-Stokes equations" and e.type == "equation" for e in ctx.entities)
    assert not any(e.mention == "met" for e in ctx.entities)
    none = await _ctx("Does the kit work at the ATM?")
    assert none.entities == []


@pytest.mark.asyncio
async def test_stem_quantities_and_materials():
    ctx = await _ctx("Apply 5 GPa pressure to Silicon")
    types = [e.type for e in ctx.entities]
    assert "quantity" in types and "material" in types
    q_ent = next(e for e in ctx.entities if e.type == "quantity")
    assert q_ent.label == "5 GPa"
    m_ent = next(e for e in ctx.entities if e.type == "material")
    assert "Silicon" in m_ent.label


@pytest.mark.asyncio
async def test_stem_constants_and_systems():
    ctx = await _ctx("Simulate the harmonic oscillator with Planck constant")
    types = {e.type for e in ctx.entities}
    assert "system" in types and "constant" in types
    c_ent = next(e for e in ctx.entities if e.type == "constant")
    assert "Planck constant" in c_ent.label


@pytest.mark.asyncio
async def test_stem_equations_and_laws():
    ctx = await _ctx("Derive solutions to the heat equation and wave equation")
    labels = {e.label for e in ctx.entities}
    assert "Heat equation" in labels and "Wave equation" in labels


@pytest.mark.asyncio
async def test_stem_dataset_inspection():
    ctx = await _ctx("Inspect uploaded dataset ds_123456789abc with Calcula")
    assert "calcula" in ctx.decisions and ctx.decisions["calcula"].run


# =============================================================================
# 2. The live resolver through the registry (fake tool fed by recorded responses)
# =============================================================================


class _CapturingLLM:
    def __init__(self, sink: dict[str, Any], answer: str) -> None:
        self.sink, self.answer = sink, answer

    async def ainvoke(self, messages):
        self.sink.setdefault("calls", []).append(messages)
        return SimpleNamespace(content=self.answer)


# =============================================================================
# 3. Hard guards under a model-assisted planner
# =============================================================================

class _PlannerAndAnswerLLM:
    """Answers the planner prompt with a hostile plan and the synthesis prompt with plain text."""

    def __init__(self, plan: dict[str, Any], sink: dict[str, Any]) -> None:
        self.plan, self.sink = plan, sink

    async def ainvoke(self, messages):
        if "routing plan" in str(messages[0].content):
            self.sink["planner_calls"] = self.sink.get("planner_calls", 0) + 1
            return SimpleNamespace(content=json.dumps(self.plan))
        return SimpleNamespace(content="Archivon retrieved arXiv:1706.03762 on Navier-Stokes.")


HOSTILE_PLAN = {
    "intents": ["simulation", "single_cell", "not_an_intent"],
    "dataset_path": "fake.h5ad",
    "entities": [{"text": "Banach", "type": "concept"}, {"text": "Navier-Stokes equations", "type": "equation", "id": "FAKE1"}],
}


@pytest.mark.asyncio
async def test_llm_planner_cannot_override_hard_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBOS_PLANNER", "always")
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    sink: dict[str, Any] = {}
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: _PlannerAndAnswerLLM(HOSTILE_PLAN, sink))
    res = await orch.execute_inquiry("Find Navier-Stokes equations papers only.", thread_id="t-guard", enable_web_search=False)
    assert sink["planner_calls"] == 1
    assert not called(calls, "vivarix_simulate_time_course") and not called(calls, "lumicell_analyze_single_cell")
    qc = res.query_context
    assert qc["planner"] == "llm" and qc["suppress_simulation"] and qc["dataset"] is None
    assert "simulation" in qc["intents"] and "not_an_intent" not in qc["intents"]
    assert [e["label"] for e in qc["entities"]] == ["Navier-Stokes equations"]  # Banach is not in the question
    assert all(not e["ids"] for e in qc["entities"])

    bm = await orch.execute_inquiry("Simulate BIOMD0000000010 for 50 seconds.", thread_id="t-guard2", enable_web_search=False)
    assert bm.query_context["planner"] == "llm" and not called(calls, "synapta_kegg_pathways")[1:]
    sims = called(calls, "dynamis_simulate_ode") or called(calls, "vivarix_simulate_time_course")
    assert sims and (sims[-1].get("biomodel_id") == "BIOMD0000000010" or "t_span" in sims[-1] or sims[-1].get("model_name") == "damped_oscillator")


# =============================================================================
# 4. Model-assisted planner degradation
# =============================================================================

NO_ENTITY_Q = "What are the primary enzymes involved in the light-independent reactions of photosynthesis?"


class _Prose:
    async def ainvoke(self, _messages):
        return SimpleNamespace(content="I think this is about plant biochemistry, not oncology.")


class _ThinkJson:
    async def ainvoke(self, _messages):
        return SimpleNamespace(content='<think>{"intents": ["safety"]} is wrong</think>Plan: {"intents": ["literature"], "entities": [{"text": "photosynthesis", "type": "disease"}]}')


class _AstreamOnly:
    async def astream(self, _messages):
        yield SimpleNamespace(content="x")


class _Slow:
    async def ainvoke(self, _messages):
        await asyncio.sleep(3600)  # never answers in time: only the planner budget can end the wait
        return SimpleNamespace(content='{"intents": ["literature"]}')


def _raise(**_kw):
    raise RuntimeError("no model configured")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory, planner",
    [
        (_raise, "llm_unavailable"),
        (lambda **_kw: _AstreamOnly(), "llm_unavailable"),
        (lambda **_kw: _Prose(), "llm_unavailable"),
        (lambda **_kw: _ThinkJson(), "llm"),
    ],
)
async def test_planner_degrades_gracefully(factory, planner):
    ctx = await _ctx(NO_ENTITY_Q, llm_factory=factory)
    assert ctx.planner == planner
    assert ctx.decisions["synapta"].run is False and ctx.decisions["archivon"].run is True
    if planner == "llm":
        assert "literature" in ctx.intents and "safety" not in ctx.intents
        ent = ctx.entities[0]
        assert (ent.mention, ent.validated, ent.ids, ent.source) == ("photosynthesis", False, {}, "query_text")


@pytest.mark.asyncio
async def test_slow_planner_respects_budget_and_auto_mode_skips_when_entities_exist():
    # Audit TST-009: the planner budget, not the runner's speed, decides; an ignored budget fails the outer timeout.
    ctx = await asyncio.wait_for(_ctx(NO_ENTITY_Q, llm_factory=lambda **_kw: _Slow(), budget_s=0.1), timeout=60)
    assert ctx.planner == "llm_unavailable"

    asked: list[Any] = []
    ctx2 = await _ctx("Find Navier-Stokes equations papers only.", llm_factory=lambda **kw: asked.append(kw) or _Slow())
    assert ctx2.planner == "deterministic" and asked == []


@pytest.mark.asyncio
async def test_planner_off_and_no_reasoning_from_planner(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBOS_PLANNER", "off")
    assert (await _ctx(NO_ENTITY_Q, llm_factory=_raise)).planner == "deterministic"
    monkeypatch.delenv("TRIBOS_PLANNER")

    class Both:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content='<think>planner thoughts</think>{"intents": ["literature"]}')

        async def astream(self, _messages):
            for piece in ["<think>Answer reasoning.</think>", "No gene was named."]:
                yield SimpleNamespace(content=piece, additional_kwargs={})

    monkeypatch.setenv("TRIBOS_SHOW_REASONING", "1")
    orch, _ = make_offline_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: Both())
    events: list[dict[str, Any]] = []

    async def cb(ev):
        events.append(ev)

    res = await orch.execute_inquiry(NO_ENTITY_Q, thread_id="t-noreason", enable_web_search=False, event_callback=cb)
    reasoning = "".join(e["delta"] for e in events if e["type"] == "reasoning_delta")
    # Synthesis (and any correction pass) streams reasoning; the planner call never does.
    assert reasoning.startswith("Answer reasoning.") and "planner thoughts" not in reasoning
    assert res.query_context["planner"] == "llm"


# =============================================================================
# 4b. Scope: messages that are not research questions search nothing
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query, scope",
    [
        ("heelooo", "unclear"), ("???", "unclear"), ("hmmm", "unclear"),
        ("thanks!", "conversational"), ("ok", "conversational"), ("bye", "conversational"),
        # Conservative without a model: anything that might be a question is research.
        ("asdf", "research"), ("why?", "research"), ("tell me more", "research"), ("DNA", "research"),
        ("autophagy", "research"), ("KRAS", "research"), ("sotorasib", "research"), (NO_ENTITY_Q, "research"),
    ],
)
async def test_offline_scope_heuristic(query, scope):
    ctx = await _ctx(query, llm_factory=_raise)
    assert ctx.scope == scope
    if scope != "research":
        assert not any(d.run for d in ctx.decisions.values())
        assert {d.reason for d in ctx.decisions.values()} == {"not a research question"}


class _ScopePlanner:
    """Answers the planner prompt with a fixed scope and the synthesis prompt with a grounded sentence."""

    def __init__(self, scope: Any) -> None:
        self.scope = scope

    async def ainvoke(self, messages):
        if "routing plan" in str(messages[0].content):
            return SimpleNamespace(content=json.dumps({"scope": self.scope, "intents": [], "entities": []}))
        return SimpleNamespace(content="Archivon retrieved arXiv:1706.03762 on Navier-Stokes.")


@pytest.mark.asyncio
async def test_planner_scope_verdict_never_overrides_concrete_entities(monkeypatch):
    assert (await _ctx("blorp zing", llm_factory=lambda **_kw: _ScopePlanner("unclear"))).scope == "unclear"
    assert (await _ctx("blorp zing", llm_factory=lambda **_kw: _ScopePlanner("maybe"))).scope == "research"
    monkeypatch.setenv("TRIBOS_PLANNER", "always")
    ctx = await _ctx("Find Navier-Stokes equations papers only.", llm_factory=lambda **_kw: _ScopePlanner("conversational"))
    assert ctx.planner == "llm" and ctx.scope == "research" and ctx.decisions["archivon"].run


@pytest.mark.asyncio
async def test_unclear_message_searches_nothing_and_says_so(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: _ScopePlanner("unclear"))
    events: list[dict[str, Any]] = []

    async def cb(ev):
        events.append(ev)

    res = await orch.execute_inquiry("blorp zing", thread_id="t-unclear", enable_web_search=True, event_callback=cb)
    assert calls == [] and res.selected_agents == [] and res.run_manifest["tool_calls"] == []
    assert "couldn't find a scientific or engineering question" in res.response and "blorp zing" in res.response
    assert res.query_context["scope"] == "unclear"
    # The plan step that was announced as running is closed, and nothing else is shown.
    assert [t["id"] for t in res.thoughts] == ["plan"] and res.thoughts[0]["status"] == "done"
    assert not [e for e in events if e["type"] in ("content_delta", "reasoning_delta")]


@pytest.mark.asyncio
async def test_vague_follow_up_in_a_thread_with_history_is_still_researched(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: _ScopePlanner("unclear"))
    await orch.execute_inquiry("Find Navier-Stokes equations papers only.", thread_id="t-follow", enable_web_search=False)
    n_before = len(called(calls, "archivon_literature_search")) + len(called(calls, "lithoscribe_literature_synthesis"))

    follow = await orch.execute_inquiry("why is that?", thread_id="t-follow", enable_web_search=False)
    assert follow.query_context["scope"] == "research"
    assert len(called(calls, "archivon_literature_search")) + len(called(calls, "lithoscribe_literature_synthesis")) == n_before + 1

    n_calls = len(calls)
    thanks = await orch.execute_inquiry("thanks!", thread_id="t-follow", enable_web_search=False)
    assert thanks.response.startswith("You're welcome") and len(calls) == n_calls


@pytest.mark.asyncio
async def test_model_reasoning_is_not_shown_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIBOS_SHOW_REASONING", raising=False)

    class Thinks:
        async def astream(self, _messages):
            for piece in ["<think>The instruction says cite only <evidence> ids.</think>", "No gene was named."]:
                yield SimpleNamespace(content=piece, additional_kwargs={})

    orch, _ = make_offline_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: Thinks())
    events: list[dict[str, Any]] = []

    async def cb(ev):
        events.append(ev)

    res = await orch.execute_inquiry("Find Navier-Stokes equations papers only.", thread_id="t-hidden", enable_web_search=False, event_callback=cb)
    assert not [e for e in events if e["type"] == "reasoning_delta"] and res.reasoning == ""
    assert "No gene was named." in "".join(e["delta"] for e in events if e["type"] == "content_delta")


# =============================================================================
# 5. Verifier, discovery and the evidence block
# =============================================================================


def test_unvalidated_entities_never_whitelist_ids():
    ctx = QueryContext(raw_query="q", clean_query="q")
    ctx.entities = [
        ResolvedEntity(type="drug", mention="x", label="X", ids={"chembl_id": "CHEMBL1"}, validated=False),
        ResolvedEntity(type="drug", mention="y", label="Y", ids={"chembl_id": "CHEMBL2"}, source="ChEMBL", validated=True),
    ]
    assert ctx.observed_identifiers()["chembl"] == {"CHEMBL2"}


def test_discovery_matches_species_through_aliases():
    viv = ToolResult(success=True, tool_name="vivarix", data={"initial_concentrations": {"Erk2-PP": 10.0, "Mos": 5.0}, "final_concentrations": {"Erk2-PP": 200.0, "Mos": 5.1}})
    report = DiscoveryEngine.prioritize_hypotheses("q", "MAPK1", {"vivarix": viv}, target_aliases=["ERK2"])
    assert "target species" in json.dumps(report.model_dump())
    without = DiscoveryEngine.prioritize_hypotheses("q", "MAPK1", {"vivarix": viv})
    assert "model species" in json.dumps(without.model_dump())


