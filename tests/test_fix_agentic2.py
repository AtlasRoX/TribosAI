"""AGENTIC2 fixes: STEM fixed-plan legs (BRK-11), no biomedical plan plumbing (BRK-10), arXiv critique keys
(LOG-7 debate), the hypothesis direction check (LOG-25) and Dynamis-backed hypothesis tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests.agentic_fakes import collect_events, make_agentic_orchestrator
from tribos.agentic import config as agent_config
from tribos.agentic import executor as executor_mod
from tribos.agentic import hypothesis as hyp
from tribos.agentic import topologies as topo
from tribos.agentic.budget import RunBudget
from tribos.agentic.control import RunControl
from tribos.agentic.llm import AgentLLM
from tribos.agentic.runtime import register_phase, restore_phases, snapshot_phases
from tribos.agentic.specialists import SPECS_BY_NAME, Specialist
from tribos.agentic.state import AgentState
from tribos.agents.query_planner import build_query_context
from tribos.tools.registry import get_tool_registry

BIOMEDICAL_TOOLS = ("depmap", "string_", "chembl", "openfda", "clinical_trials", "gtex", "primekg", "synapta", "vivarix")


def _ctx(question: str) -> Any:
    ctx = build_query_context(
        query=question, clean_query=question, registry=None, enable_web_search=False, attachments=[],
        attachment_errors=[], user_id="u", thread_id="t", model_name="none", api_key=None,
    )
    return asyncio.run(ctx) if asyncio.iscoroutine(ctx) else ctx


def _state(question: str, registry: Any = None, **kw: Any) -> AgentState:
    budget = RunBudget()
    steps: list[dict[str, Any]] = []

    async def emit(step_id, title, text="", status="done", agent=None, extra=None):
        steps.append({"id": step_id, "title": title, "text": text, "status": status})

    async def send(_event):
        return None

    state = AgentState(
        query=question, clean_query=question, ctx=kw.pop("ctx", None) or _ctx(question),
        registry=registry if registry is not None else get_tool_registry(), user_id="u", thread_id="t",
        model_name="m", api_key=None, framework=agent_config.AGENTIC, budget=budget, control=RunControl("u", interactive=False),
        llm=AgentLLM(None, "m", None, budget), tool_results={}, emit=emit, send=send, options=kw.pop("options", {}),
    )
    state.bag["steps"] = steps
    return state


STEM_QUESTIONS = (
    "Derive the period of a simple pendulum and simulate the pendulum for 10 s.",
    "Run a parameter scan of rho from 10 to 30 in the Lorenz system.",
    "Find the steady state of the Lotka-Volterra model.",
    "Convert 5 eV to J and give the Planck constant.",
    "What is the band gap of silicon? Cite papers on its measurement.",
    "Does increasing damping reduce overshoot in the damped harmonic oscillator?",
    "What safety factor does a steel beam need under cyclic loading? Review the literature.",
)


# BRK-11 -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("question", STEM_QUESTIONS)
def test_every_fixed_plan_tool_is_registered_and_its_arguments_validate(question):
    registry = get_tool_registry()
    state = _state(question, registry)
    calls = [c for leg, _rx in topo.LEG_CUES for c in topo.leg_calls(state, leg)]
    for name in SPECS_BY_NAME:
        tools = [e for e in registry.list_tools() if e.name.startswith(SPECS_BY_NAME[name].prefixes)]
        calls += topo.specialist_calls(state, Specialist(SPECS_BY_NAME[name], tools))
    assert calls, "every STEM question gets at least one fixed call"
    for tool, args in calls:
        entry = registry.get_entry(tool)
        assert entry is not None, f"{tool} is not a registered tool"
        entry.input_schema.model_validate(args)
        assert not tool.startswith(BIOMEDICAL_TOOLS), tool


def test_fixed_plan_legs_follow_the_stem_question():
    q = STEM_QUESTIONS[0]
    assert topo.question_legs(q) == ["symbolic", "numerical"]
    state = _state(q)
    assert topo.leg_calls(state, "symbolic") == [("axiom_solve_problem", {"problem": q})]
    sim = topo.leg_calls(state, "numerical")
    assert [t for t, _ in sim] == ["dynamis_simulate_ode"] and sim[0][1]["model_name"] == "pendulum"
    assert sim[0][1]["t_span"] == (0.0, 10.0)

    scan = topo.leg_calls(_state(STEM_QUESTIONS[1]), "numerical")
    assert scan[0][0] == "dynamis_parameter_scan" and scan[0][1]["parameter"] == "rho"
    assert scan[0][1]["scan_range"] == (10.0, 30.0)

    ref = topo.leg_calls(_state(STEM_QUESTIONS[3]), "reference")
    assert ("physis_units", {"value": 5.0, "from_unit": "eV", "to_unit": "J"}) in ref
    assert ("physis_constants", {"query": "Planck constant"}) in ref
    mats = topo.leg_calls(_state(STEM_QUESTIONS[4]), "reference")
    assert any(t == "physis_materials" for t, _ in mats)
    assert topo.leg_calls(_state(STEM_QUESTIONS[4]), "literature")[0][0] == "archivon_literature_search"


@pytest.mark.parametrize(
    ("question", "legs"),
    [
        ("Compute the safety factor of the shaft.", ["symbolic"]),
        ("How many trials of the drop test failed, and what do the labels on the plot mean?", []),
        ("Which partners in the consortium published the original paper?", ["literature"]),
        ("Simulate the RLC circuit and convert the peak current to mA.", ["numerical", "reference"]),
    ],
)
def test_question_legs_route_stem_wording(question, legs):
    assert topo.question_legs(question) == legs
    assert set(topo.LEG_SPECIALISTS) == {"symbolic", "numerical", "reference", "literature"}


def test_unit_conversion_needs_a_stated_conversion():
    assert topo.unit_conversion("convert 3.2 kcal/mol to kJ/mol") == {"value": 3.2, "from_unit": "kcal/mol", "to_unit": "kJ/mol"}
    assert topo.unit_conversion("What is 10 GPa in Pa?") == {"value": 10.0, "from_unit": "GPa", "to_unit": "Pa"}
    assert topo.unit_conversion("Find the 3 roots in the interval") is None


def test_no_biomedical_stubs_left_in_topologies():
    assert not hasattr(topo, "_named_trials") and not hasattr(topo, "_found_drug_names")


# LOG-7 (debate) ---------------------------------------------------------------------------------------------------
def test_debate_keeps_critiques_that_cite_arxiv_or_result_keys():
    valid = {topo._norm_key(k) for k in ["ARXIV:2312.04511", "DOI:10.1103/PhysRev.47.777", "axiom"]}
    final = {"physicist": topo.DebateReply(verdict="revise", critiques=[
        topo.Critique(claim="c1", issue="i", evidence_key="[arXiv:2312.04511v2]"),
        topo.Critique(claim="c2", issue="i", evidence_key="arXiv: 2312.04511"),
        topo.Critique(claim="c3", issue="i", evidence_key="doi:10.1103/physrev.47.777"),
        topo.Critique(claim="c4", issue="i", evidence_key="[Axiom]"),
        topo.Critique(claim="c5", issue="i", evidence_key="ARXIV:9999.00001"),
    ])}
    kept, dropped = topo.DebatePhase._valid_critiques(final, valid)
    assert [c["claim"] for c in kept] == ["c1", "c2", "c3", "c4"] and dropped == 1
    assert kept[0]["evidence_key"] == "ARXIV:2312.04511"


def test_debate_revision_carries_an_arxiv_critique(monkeypatch, tmp_path):

    saved = snapshot_phases()
    from tribos.extensions import load_extensions

    load_extensions()
    restore_phases({})
    register_phase(topo.DEBATE_PHASE)
    # The fake literature search returns arXiv:1706.03762 for this question; two critics cite it in the arXiv form
    # the prompt asks for (with a version suffix), one cites nothing.

    def debate(system: str, _user: str) -> str:
        if "You are the engineer" in system:
            return json.dumps({"critiques": [], "verdict": "accept"})
        return json.dumps({"critiques": [{"claim": "Overshoot rises with damping", "issue": "the source says it falls",
                                          "evidence_key": "[arXiv:1706.03762v5]", "severity": "high"}], "verdict": "revise"})

    try:
        orch, _calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path, responses={"debate": debate})
        res, _ = asyncio.run(collect_events(orch, query="How does damping change overshoot of a damped oscillator?",
                                            thread_id="d1", framework=agent_config.DEBATE))
    finally:
        restore_phases(saved)
    synth = llm.prompts("synthesis")
    # The arXiv critiques count and are sent back for the revision (they were dropped as unknown keys before).
    assert any("evidence: ARXIV:1706.03762; raised by" in s for s in synth[1:])
    assert res.execution_artifacts["agent_dialogue"]["topology"] == "debate"


# BRK-10 -----------------------------------------------------------------------------------------------------------
def test_executor_has_no_drug_or_gene_fallbacks():
    for name in ("run_known_drugs", "run_known_genes", "_NeedsTarget", "_drug_value", "_GENE_ARG_KEYS"):
        assert not hasattr(executor_mod, name), name
    assert not hasattr(executor_mod.PlanExecutor, "_fill_targets")


# LOG-25 -----------------------------------------------------------------------------------------------------------
def test_direction_check_keeps_valid_stem_factors():
    system = hyp.dynamis_system(_ctx("the damped oscillator"))
    phase = hyp.HypothesisPhase()

    def factor(kind: str, value: float) -> float | None:
        raw = {"statement": "s", "prediction": "decrease", "readout": "x", "metric": "range",
               "intervention": {"kind": kind, "parameter": "zeta", "factor": value}}
        h, reason = phase._validate(raw, system, source="llm")
        assert h is not None, reason
        return h.factor

    assert factor("variation", 2.0) == 2.0
    assert factor("variation", 0.5) == 0.5
    assert factor("elevation", 5.0) == 5.0
    assert factor("elevation", 0.5) == hyp.DEFAULT_FACTORS["elevation"]
    assert factor("reduction", 0.2) == 0.2
    assert factor("reduction", 3.0) == hyp.DEFAULT_FACTORS["reduction"]
    assert factor("overexpression", 4.0) == 4.0


# Hypotheses on Dynamis ------------------------------------------------------------------------------------------
def test_preset_matching_uses_whole_words_longest_first():
    assert hyp.preset_for(SimpleNamespace(), "the damped harmonic oscillator") == "damped_oscillator"
    assert hyp.preset_for(SimpleNamespace(), "a simple harmonic oscillator") == "harmonic_oscillator"
    assert hyp.preset_for(SimpleNamespace(), "the desired angle of the arm") is None
    assert hyp.preset_for(SimpleNamespace(), "an SIR epidemic model") == "sir"
    system = hyp.dynamis_system(_ctx("Simulate the damped oscillator with zeta = 0.3 for 20 s"))
    assert system is not None and system.parameters["zeta"] == 0.3 and system.t_span == (0.0, 20.0)


def test_hypothesis_phase_needs_intent_not_just_a_system():
    assert not hyp.HypothesisPhase().applies(_state("Simulate the Lorenz system for 20 s."))
    assert hyp.HypothesisPhase().applies(_state(STEM_QUESTIONS[5]))


def test_damping_hypothesis_is_tested_with_a_dynamis_scan():
    state = _state(STEM_QUESTIONS[5])
    asyncio.run(hyp.HypothesisPhase().run(state))
    art = state.artifacts["hypotheses"]
    assert art["model_id"] == "damped_oscillator" and art["experiments_run"] >= 1
    first = next(h for h in art["hypotheses"] if h["source"] == "deterministic")
    assert first["intervention"]["parameter"] == "zeta" and first["intervention"]["kind"] == "elevation"
    assert first["metric"] == "overshoot" and first["prediction"] == "decrease" and first["status"] == "tested"
    result = first["result"]
    assert result["supports"] is True and result["relative_change"] < -hyp.REL_CHANGE_THRESHOLD and result["monotonic"]
    tools = {t["tool"] for t in state.trace}
    assert tools == {"dynamis_parameter_scan"}
    assert any("<hypothesis_experiments" in s and 'metric="overshoot"' in s for s in state.evidence_sections)


def test_question_without_a_system_gets_no_tested_hypotheses():
    state = _state("What hypotheses explain the anomalous precession of Mercury's perihelion?")
    asyncio.run(hyp.HypothesisPhase().run(state))
    art = state.artifacts["hypotheses"]
    assert art["model_id"] is None and art["hypotheses"] == [] and art["experiments_run"] == 0
    # Audit I36: a hypothesis needs no dynamical system; only an in-silico test would, so none is demanded here.
    assert "No hypothesis was proposed" in art["note"] and "dynamical system" not in art["note"] and not state.trace


def test_simulation_switched_off_leaves_hypotheses_untested():
    question = STEM_QUESTIONS[5] + " Do not run any simulation."
    state = _state(question)
    assert hyp.simulation_block_reason(state.ctx)
    asyncio.run(hyp.HypothesisPhase().run(state))
    art = state.artifacts["hypotheses"]
    assert art["simulation"] == "blocked" and art["experiments_run"] == 0 and not state.trace
    assert all(h["status"] == "untested" for h in art["hypotheses"])
