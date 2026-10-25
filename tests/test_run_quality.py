"""Run-quality fixes from a 9-minute mass-spring run that ended with no answer: the empty draft, the time span, the
steady-state false positive, the search queries and the activity-step text."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.agentic_fakes import DEFAULT_SYNTHESIS, collect_events, make_agentic_orchestrator
from tribos.agentic import config as agent_config
from tribos.agentic.decompose import subquestion_summary
from tribos.agentic.executor import tool_display_name
from tribos.agentic.state import SubQuestion
from tribos.agents.authoritative_orchestrator import literature_query
from tribos.agents.query_planner import _STEADY_STATE_REQUEST_RE, parse_duration
from tribos.archivon.engine import _citation_label


def test_a_draft_with_reasoning_but_no_text_is_written_again_not_kept_empty(monkeypatch, tmp_path):
    drafts: list[int] = []

    def synthesis(_system: str, _user: str) -> str:
        drafts.append(1)
        # The first attempt spends everything on reasoning (an unclosed <think>): no answer text at all.
        return "<think>Let me work through the oscillator carefully..." if len(drafts) == 1 else DEFAULT_SYNTHESIS

    orch, _calls, _llm = make_agentic_orchestrator(monkeypatch, tmp_path, responses={"synthesis": synthesis})
    res, events = asyncio.run(collect_events(orch, query="Explain how a transistor works", thread_id="t-empty",
                                             framework=agent_config.AGENTIC))
    assert len(drafts) >= 2
    assert res.response.strip() and DEFAULT_SYNTHESIS.split()[0] in res.response
    titles = [e["data"].get("title", "") for e in events if e.get("type") == "thought"]
    assert any("Writing the answer again" in t for t in titles)


class InternalServerError(Exception):
    """Same name as the provider SDK's HTTP 500 error, which the draft treats as transient."""


def test_a_transient_provider_error_on_the_first_draft_is_retried(monkeypatch, tmp_path):
    drafts: list[int] = []

    def synthesis(_system: str, _user: str) -> str:
        drafts.append(1)
        if len(drafts) == 1:
            raise InternalServerError("Error code: 500 - Failed to generate completions")
        return DEFAULT_SYNTHESIS

    orch, _calls, _llm = make_agentic_orchestrator(monkeypatch, tmp_path, responses={"synthesis": synthesis})
    res, _events = asyncio.run(collect_events(orch, query="Explain how a transistor works", thread_id="t-500",
                                              framework=agent_config.AGENTIC))
    assert len(drafts) >= 2 and DEFAULT_SYNTHESIS.split()[0] in res.response  # the written answer, not the fallback
    assert "Results gathered for" not in res.response


@pytest.mark.parametrize(
    ("equation", "homogeneous"),
    [
        ("kg * m / s^2 = N; c x' = (N s/m) * (m/s) = N; k x = (N/m) * m = N; F0 cos(omega t) = N", True),
        ("(N s/m) * (m/s) = (N/m) * m = N", True),  # a chain: each neighbouring pair is checked
        ("J = N * m; W = J / s", True),
        ("kg * m/s = N", False),
    ],
)
def test_unit_checks_accept_the_sets_and_chains_models_write(equation, homogeneous):
    from tribos.physis.units import convert_units

    assert convert_units(check_equation=equation)["equation_homogeneous"] is homogeneous


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("Simulate the system over 0–20 s using a suitable numerical method", 20.0),
        ("Simulate the pendulum from 0 to 15 s", 15.0),
        ("Simulate the oscillator for t in [0, 30] s", 30.0),
        ("Simulate the circuit with 0 <= t <= 5 s", 5.0),
        ("Simulate BIOMD0000000010 for 100 s", 100.0),
    ],
)
def test_time_spans_are_durations(text, seconds):
    parsed = parse_duration(text)
    assert parsed.explicit and parsed.seconds == seconds and parsed.error_code is None


def test_an_approximate_length_is_not_read_as_a_span():
    assert not parse_duration("Simulate the reactor for 2-3 hours").explicit  # not "1 hour"


@pytest.mark.parametrize(
    ("text", "requested"),
    [
        ("Derive the solution, including transient and steady-state components", False),
        ("Calculate the steady-state amplitude and phase", False),
        ("Plot the steady-state response", False),
        ("Simulate BIOMD0000000010 and compute the steady state of the model", True),
        ("Run the model to steady state", True),
    ],
)
def test_only_a_request_for_the_equilibrium_is_a_steady_state_request(text, requested):
    assert bool(_STEADY_STATE_REQUEST_RE.search(text)) is requested


def test_a_long_worked_problem_is_searched_by_its_subject_not_its_paragraph():
    ctx = SimpleNamespace(focus_terms=lambda: ["Damped Harmonic Oscillator", "mass–spring system"], search_plan=None)
    long_q = "Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt). " * 4
    assert literature_query(ctx, long_q, SimpleNamespace(question_type="derivation")) == (
        "Damped Harmonic Oscillator mass–spring system analytical solution"
    )
    short = "Terminal velocity of a steel sphere in water"
    assert literature_query(ctx, short) == short


def test_subquestions_show_the_restated_problem_once():
    problem = "the forced damped mass–spring system with m = 2 kg, c = 3 N·s/m, k = 50 N/m, F0 = 10 N"
    subs = [
        SubQuestion(id="q1", text=f"For {problem}, derive the analytical solution."),
        SubQuestion(id="q2", text=f"Simulate {problem} over 0–20 s.", depends_on=["q1"]),
    ]
    lines = subquestion_summary(subs).split("\n")
    assert lines[0] == f"Common to all: {problem}"
    assert lines[1] == "q1. For the system, derive the analytical solution."
    assert lines[2] == "q2. Simulate the system over 0–20 s. (after q1)"


def test_tool_steps_use_current_agent_names():
    assert tool_display_name("lithoscribe_literature_synthesis") == "Archivon · literature synthesis"
    assert tool_display_name("vivarix_compute_steady_state") == "Dynamis · compute steady state"
    assert tool_display_name("axiom_dsolve") == "Axiom · dsolve"
    assert tool_display_name("custom_tool") == "custom tool"


def test_a_stated_ode_is_simulated_as_stated_not_as_a_preset():
    """The question's own forced oscillator (x0 = 0.1, F0 = 10 N), not the unforced damped_oscillator preset (x0 = 1)."""
    import numpy as np

    from tribos.axiom.problem import parse_problem
    from tribos.dynamis.engine import dynamis_simulate_ode
    from tribos.dynamis.stated_ode import stated_ode_system

    spec = parse_problem(
        "Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = 2 kg, "
        "c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, x(0) = 0.1 m, and x'(0) = 0. Simulate it over 0–20 s."
    )
    system = stated_ode_system(spec.expression, spec.func or "", spec.ics)
    assert system is not None and system["initial_state"] == {"x": 0.1, "v": 0.0}
    sim = dynamis_simulate_ode(rhs=system["rhs"], initial_state=system["initial_state"], t_span=(0.0, 20.0), num_points=2001)
    t, x = np.array(sim["t"]), np.array(sim["trajectories"]["x"])
    # Independent analytical reference values at t = 1, 5, 10, 20 s.
    for when, expected in ((1, -0.360984), (5, 0.387299), (10, -0.065464), (20, -0.297300)):
        assert abs(float(np.interp(when, t, x)) - expected) < 1e-5
    late = x[t >= 15]
    assert abs(late.max() - 0.46225) < 2e-3 and abs(late.min() + 0.46225) < 2e-3  # forced: never settles to zero
    assert stated_ode_system("y'' + y = 0", "y(t)", {"y(0)": "1"}) is None  # an unstated condition is never guessed


def test_a_solved_ode_is_verified_numerically_with_real_convergence_and_energy_numbers():
    from tribos.dynamis.verification import verify_ode_solution

    solution = ("x(t) = (-0.250656440625879*sin(sqrt(391)*t/4) - 0.284615384615385*cos(sqrt(391)*t/4))*exp(-3*t/4)"
                " + 10*sin(4*t)/39 + 5*cos(4*t)/13")
    rep = verify_ode_solution("(2) x'' + (3) x' + (50) x = (10) cos((4) t)", "x(t)", {"x(0)": "0.1", "x'(0)": "0"},
                              solution, 20.0)
    assert rep is not None and rep["residual_symbolic"] == "0"
    orders = [r["observed_order"] for r in rep["convergence"] if "observed_order" in r]
    assert orders and all(abs(o - 4) < 0.1 for o in orders)  # classical RK4 is fourth order
    assert rep["convergence"][-1]["max_error_x"] < 1e-6
    by_t = {s["t"]: s for s in rep["samples"]}
    assert abs(by_t[5.0]["analytical"] - 0.387299) < 1e-6 and by_t[5.0]["error"] < 1e-6
    energy = rep["energy"]
    assert (energy["m"], energy["c"], energy["k"]) == (2.0, 3.0, 50.0)
    assert abs(energy["balance_residual"]) < 1e-4  # E(T) - E(0) = W_in - W_d
    assert "def rk4" in rep["script"]
    # A wrong solution is caught: the residual is not zero.
    wrong = verify_ode_solution("(2) x'' + (3) x' + (50) x = (10) cos((4) t)", "x(t)", {"x(0)": "0.1", "x'(0)": "0"},
                                "x(t) = 0.1*cos(5*t)", 20.0)
    assert wrong is not None and wrong["residual_max"] > 1


def test_literature_keeps_papers_and_drops_datasets_figures_and_data_products():
    from tribos.archivon.engine import clip_title, is_scholarly_work

    paper = {"type": "journal-article", "doi": "10.1590/s1806-11173742058", "title": "Forced damped oscillations"}
    assert is_scholarly_work(paper)
    junk = [
        {"type": "", "doi": "10.5270/esa-mqoctu8", "title": "S1-X-SPEDE-2-EDR-EP-MONITORING"},  # ESA data product
        {"type": "", "doi": "10.4211/hs.a270f893d7cd4a0f9bf98af40ea5eaa2", "title": "Harvey+Irma Flood Area Grids"},
        {"type": "", "doi": "10.7554/elife.12613.018", "title": "Supplementary file 2."},  # part of an eLife article
        {"type": "dataset", "doi": "10.1/x", "title": "Some measurements"},
        {"type": "component", "doi": "10.1/y", "title": "Figure 1."},
    ]
    assert not any(is_scholarly_work(r) for r in junk)
    assert len(clip_title("word " * 400)) <= 301  # a whole article body is not a title


def test_citation_labels_never_print_unknown_or_none():
    assert _citation_label({"year": "None", "doi": "10.7554/elife.12613.018"}, "Unknown") == "[DOI:10.7554/elife.12613.018]"
    assert _citation_label({"year": 2024, "doi": "10.1/x"}, "Asha Mishra, B. Rao") == "[Mishra et al., 2024 | DOI:10.1/x]"
    assert _citation_label({"year": None, "arxiv_id": "2401.00001"}, "Lee, K") == "[Lee et al. | arXiv:2401.00001]"


def test_characteristic_parameters_are_computed_not_left_to_the_writer():
    import math

    import sympy as sp

    from tribos.dynamis.verification import characteristic_parameters

    t = sp.Symbol("t")
    params = characteristic_parameters(2.0, 3.0, 50.0, 10 * sp.cos(4 * t), t)
    value = {k: v["value"] for k, v in params.items() if isinstance(v, dict) and "value" in v}
    assert abs(value["natural_frequency"] - 5.0) < 1e-12 and abs(value["damping_ratio"] - 0.15) < 1e-12
    assert abs(value["damped_frequency"] - math.sqrt(25 - 0.5625)) < 1e-9
    assert abs(value["steady_state_amplitude"] - 10 / math.sqrt(468)) < 1e-9  # 0.462250 m, not 10/sqrt(117)
    assert abs(value["phase_lag"] - math.atan2(12, 18)) < 1e-9  # 0.588 rad = 33.69 deg, not atan2(12, -18)
    assert abs(params["phase_lag"]["degrees"] - 33.690068) < 1e-5


def test_a_wrong_amplitude_or_phase_in_the_answer_is_flagged():
    import sympy as sp

    from tribos.agentic.ode_verification import PHASE_KEY, parameter_consistency_check
    from tribos.dynamis.verification import characteristic_parameters
    from tribos.tools.registry import ToolResult

    t = sp.Symbol("t")
    rep = {"parameters": characteristic_parameters(2.0, 3.0, 50.0, 10 * sp.cos(4 * t), t)}
    results = {PHASE_KEY: ToolResult(success=True, tool_name=PHASE_KEY, data=rep)}
    wrong = "The steady-state amplitude X = 10/√117 ≈ 0.92848 m, and phase φ = atan2(12, −18) ≈ 2.55359 rad."
    right = "The steady-state amplitude is X ≈ 0.462250 m and the phase lag φ ≈ 0.5880 rad (33.69°)."
    assert len(parameter_consistency_check(SimpleNamespace(tool_results=results, response=wrong))) == 2
    assert parameter_consistency_check(SimpleNamespace(tool_results=results, response=right)) == []


def test_a_fully_specified_problem_takes_the_direct_workflow_not_the_planner():
    from tribos.agentic import router

    q = ("Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = 2 kg, "
         "c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, x(0) = 0.1 m, and x'(0) = 0. Simulate it over 0–20 s and "
         "consult authoritative references.")
    assert router.is_fully_specified(q, router.RoutingSignals())
    assert not router.is_fully_specified(q, router.RoutingSignals(contested=True))
    assert not router.is_fully_specified("Compare finite element and finite volume methods for turbulence.",
                                         router.RoutingSignals())
    decision = asyncio.run(router.choose_framework(q, SimpleNamespace(scope="research", evidence_need=None)))
    assert (decision.rule, decision.display_label) == ("fully_specified", "Direct workflow")
    assert decision.to_artifact()["label"] == "Direct workflow"


def test_a_planner_dependency_written_inside_args_orders_the_plan():
    from tribos.agentic.plan_graph import parse_plan

    graph = parse_plan({"nodes": [
        {"id": "n1", "tool": "axiom_dsolve", "args": {"equation": "y'' + y = 0"}},
        {"id": "n2", "tool": "calcula_run_python", "args": {"code": "result = 1", "depends_on": ["n1"]}},
    ]}, round_no=1)
    n2 = next(n for n in graph.nodes if n.id == "n2")
    assert n2.depends_on == ["n1"] and "depends_on" not in n2.args


def test_failed_sources_are_named_for_readers_not_by_internal_keys():
    from tribos.agentic.state import evidence_key_label

    assert "agent." not in evidence_key_label("agent.plan_execute.6.calcula")
    assert "(plan step)" in evidence_key_label("agent.plan_execute.6.calcula")


def test_a_skipped_planner_on_a_direct_route_is_not_a_partial_answer():
    from tribos.agentic.config import AGENTIC
    from tribos.agentic.state import core_phase_note

    state = SimpleNamespace(framework=AGENTIC, bag={"routing": {"rule": "fully_specified"}, "phases_ran": []},
                            ctx=SimpleNamespace(scope="research"))
    from tribos.agentic.state import AgentState

    assert AgentState.core_phase_status(state) is None
    state.bag["routing"]["rule"] = "computational"
    status = AgentState.core_phase_status(state)
    assert status is not None and status["status"] == "not_run" and core_phase_note(status)


def test_a_draft_cut_off_at_the_output_limit_is_continued_not_left_mid_sentence(monkeypatch, tmp_path):
    from tribos.agents import authoritative_orchestrator as orch_module

    orch, _calls, _llm = make_agentic_orchestrator(monkeypatch, tmp_path)
    head = "## Summary\n\nThe transistor amplifies a small base current into a larger collector cur"
    tail = "rent.\n\n## Evidence classification\n\nAll statements are textbook physics."
    calls: list[int] = []
    real = orch_module.astream_with_reasoning

    async def fake(llm, messages, on_reasoning=None, on_text=None, total_timeout=None, on_finish=None):
        system = str(getattr(messages[0], "content", ""))
        if "[phase:" in system[:40]:
            return await real(llm, messages, on_reasoning=on_reasoning, on_text=on_text, on_finish=on_finish)
        calls.append(1)
        text = head if len(calls) == 1 else "larger collector cur" + tail  # the continuation repeats a little
        if on_text:
            await on_text(text)
        if on_finish:
            on_finish("length" if len(calls) == 1 else "stop")
        return text, ""

    monkeypatch.setattr(orch_module, "astream_with_reasoning", fake)
    res, _events = asyncio.run(collect_events(orch, query="Explain how a transistor works", thread_id="t-len",
                                              framework=agent_config.AGENTIC))
    assert len(calls) >= 2
    assert "collector current." in res.response and "Evidence classification" in res.response
    assert "cur larger" not in res.response and "curlarger" not in res.response


def test_a_skipped_search_stops_at_once_and_is_marked_as_the_users_choice():
    from tribos.agentic.control import RunControl
    from tribos.agents.orchestration.gather import skippable

    async def slow_search():
        await asyncio.sleep(30)
        raise AssertionError("the search should have been cancelled")

    async def scenario():
        control = RunControl("u", interactive=True)
        run = SimpleNamespace(control=control)
        task = asyncio.ensure_future(skippable(run, "search", "archivon", slow_search()))
        await asyncio.sleep(0.05)
        assert control.request_skip("search") and not control.request_skip("everything")
        return await asyncio.wait_for(task, timeout=2)

    res = asyncio.run(scenario())
    assert res.success is False and res.metadata == {"skipped_by_user": True} and res.tool_name == "archivon"


def test_a_search_without_a_skip_returns_its_own_result():
    from tribos.agentic.control import RunControl
    from tribos.agents.orchestration.gather import skippable
    from tribos.tools.registry import ToolResult

    async def search():
        return ToolResult(success=True, tool_name="archivon", data={"n": 3})

    run = SimpleNamespace(control=RunControl("u", interactive=False))
    res = asyncio.run(skippable(run, "search", "archivon", search()))
    assert res.success and res.data == {"n": 3}


def test_the_route_preview_names_the_approach_without_a_model_call(monkeypatch):
    from fastapi.testclient import TestClient

    from app.backend.main import app

    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice")
    client = TestClient(app)
    auth = {"Authorization": "Bearer alice-token"}
    focused = client.post("/api/route/preview", json={"message": "Explain why the sky is blue."}, headers=auth).json()
    assert focused["label"] == "Direct workflow" and focused["approach"] == "direct"
    hyp = client.post("/api/route/preview", headers=auth,
                      json={"message": "Propose three testable hypotheses for why the beam fails early in fatigue tests."}).json()
    assert hyp["label"] == "Debate"
