"""Execution, completeness, retrieval, memory and export fixes from the 2026-10-24 mass-spring capture.

Tests named "*_mocked_*" use fake tools to inject a failure (a slow tool, a failing call); every other test runs the
real code path (real schemas, the real sandbox, the real ODE integrator). Oracles are independent: closed-form
solutions evaluated here with NumPy, Crossref work types as published, hand-written plans.
"""

from __future__ import annotations

import asyncio
import math
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel, Field

from tests.fakes import build_recording_registry, called
from tests.test_agentic_planning import _ctx, _plan_dict, make_state
from tribos.agentic.executor import PlanExecutor
from tribos.agentic.plan_execute import link_recoveries
from tribos.agentic.plan_graph import PlanNode, parse_plan, validate_plan
from tribos.tools.registry import ErrorType, ToolResult


class _WithTimeout(BaseModel):
    query: str
    timeout_s: int = Field(default=60, ge=1, le=300)


class _Plain(BaseModel):
    query: str


class _Code(BaseModel):
    code: str = Field(..., max_length=50)


# -- orchestration controls are never silently dropped ----------------------------------------------------------------
def test_a_timeout_written_in_args_becomes_the_tools_own_timeout_argument():
    reg, _calls = build_recording_registry(extra_tools={"t_timeout": (_WithTimeout, lambda kw: {"ok": True})})
    graph = parse_plan(_plan_dict({"id": "n1", "tool": "t_timeout", "args": {"query": "q", "timeout_seconds": 30}}))
    validate_plan(graph, reg, _ctx())
    node = graph.get("n1")
    assert node is not None and not graph.rejected
    assert node.args == {"query": "q", "timeout_s": 30}
    assert node.timeout_s == 30
    assert "timeout_seconds → timeout_s" in node.adjusted


def test_a_timeout_for_a_tool_without_one_becomes_the_step_deadline():
    reg, _calls = build_recording_registry(extra_tools={"t_plain": (_Plain, lambda kw: {"ok": True})})
    graph = parse_plan(_plan_dict({"id": "n1", "tool": "t_plain", "args": {"query": "q", "timeout": "45"}}))
    validate_plan(graph, reg, _ctx())
    node = graph.get("n1")
    assert node is not None and node.args == {"query": "q"} and node.timeout_s == 45
    assert any("step deadline" in a for a in node.adjusted)


def test_a_node_level_timeout_is_read_from_the_node():
    graph = parse_plan(_plan_dict({"id": "n1", "tool": "t", "args": {}, "timeout_s": 12}))
    assert graph.get("n1").timeout_s == 12


def test_mocked_slow_tool_is_stopped_at_the_step_deadline():
    def slow(kw):
        time.sleep(2.0)
        return {"ok": True}

    reg, _calls = build_recording_registry(extra_tools={"t_slow": (_Plain, slow)})
    state, _steps, _ = make_state(reg)
    graph = parse_plan(_plan_dict({"id": "n1", "tool": "t_slow", "args": {"query": "q"}, "timeout_s": 0.2}))
    validate_plan(graph, reg, _ctx())
    asyncio.run(PlanExecutor(state).run(graph))
    node = graph.get("n1")
    assert node.status == "error" and "step deadline of 0.2 s" in node.error
    assert node.seconds is not None and node.seconds < 1.0  # the node stopped waiting at its deadline


def test_resolved_arguments_that_break_the_schema_are_rejected_before_dispatch():
    reg, calls = build_recording_registry(extra_tools={
        "t_source": (_Plain, lambda kw: {"text": "x = 1\n" * 30}),
        "t_code": (_Code, lambda kw: {"ran": True}),
    })
    state, _steps, _ = make_state(reg)
    graph = parse_plan(_plan_dict(
        {"id": "n1", "tool": "t_source", "args": {"query": "data"}},
        {"id": "n2", "tool": "t_code", "args": {"code": "$n1.text"}},
    ))
    validate_plan(graph, reg, _ctx())
    asyncio.run(PlanExecutor(state).run(graph))
    node = graph.get("n2")
    assert node.status == "error" and node.error.startswith("rejected before dispatch")
    assert "180 characters" in node.error and "`inputs`" in node.error
    assert not called(calls, "t_code")  # nothing was sent to the tool


def test_scripts_receive_earlier_results_as_data_not_as_code():
    """Real sandbox run: the `inputs` channel reaches the script; a 20,000+ character script is refused."""
    import os

    from tribos.extensions.sandbox import MAX_CODE_CHARS, AnalysisRunInput, run_calcula_python

    os.environ.setdefault("TRIBOS_SANDBOX", "on")
    res = run_calcula_python("import numpy as np\nresult = {'peak': float(np.max(inputs['x']))}", inputs={"x": [0.1, -0.5, 0.48]})
    if not res.success and "disabled" in str(res.error):
        pytest.skip("sandbox disabled on this server")
    assert res.success and res.data["result"] == {"peak": 0.48}
    with pytest.raises(Exception) as exc:
        AnalysisRunInput(code="x = 1\n" * (MAX_CODE_CHARS // 6 + 1))
    assert "at most 20000 characters" in str(exc.value)


# -- recovered and unresolved failures --------------------------------------------------------------------------------
def test_a_failed_step_replaced_by_a_later_successful_one_is_recovered():
    failed = ToolResult(success=False, tool_name="calcula_run_python", error="code too long", error_type=ErrorType.VALIDATION_ERROR)
    nodes = [
        PlanNode(id="n6", tool="calcula_run_python", purpose="Compute error metrics, energy balance for q3", status="error",
                 result_key="agent.plan_execute.6.calcula"),
        PlanNode(id="n9", tool="axiom_solve_problem", purpose="derive", status="done", result_key="k9"),
        PlanNode(id="r1_n6", tool="calcula_run_python", purpose="Compute error metrics, residuals and energy balance for q3",
                 status="done", result_key="agent.plan_execute.11.calcula", round=1),
    ]
    links = link_recoveries(nodes, {"agent.plan_execute.6.calcula": failed})
    assert links == [{"step": "n6", "recovered_by": "r1_n6", "tool": "calcula_run_python"}]
    assert nodes[0].recovered_by == "r1_n6"
    assert failed.metadata["recovered_by"] == "agent.plan_execute.11.calcula"


def test_a_failure_of_a_different_purpose_is_not_counted_as_recovered():
    nodes = [
        PlanNode(id="n1", tool="websurfer_search", purpose="find the MATLAB documentation page", status="error"),
        PlanNode(id="n2", tool="websurfer_search", purpose="energy balance damped oscillator lecture notes", status="done"),
    ]
    assert link_recoveries(nodes, {}) == []


def _outcome(tool_results: dict[str, Any]) -> Any:
    from tribos.agents.authoritative_orchestrator import AuthoritativeOrchestrator

    ctx = SimpleNamespace(should_run=lambda _n: False, has_single_cell_intent=False)
    return AuthoritativeOrchestrator._task_outcome(ctx, None, tool_results, None, True)


def test_a_recovered_failure_leaves_the_task_complete_and_is_reported_as_history():
    ok = ToolResult(success=True, tool_name="t", data={"v": 1})
    failed = ToolResult(success=False, tool_name="calcula_run_python", error="code too long",
                        metadata={"recovered_by": "agent.plan_execute.11.calcula"})
    out = _outcome({"axiom": ok, "agent.plan_execute.6.calcula": failed, "agent.plan_execute.11.calcula": ok})
    assert out.task_status == "completed"
    assert len(out.recovered_failures) == 1 and not out.unresolved_failures
    assert "recovered by a retry" in out.reason


def test_mocked_unrecovered_failure_makes_the_task_partial_and_names_its_effect():
    ok = ToolResult(success=True, tool_name="t", data={"v": 1})
    failed = ToolResult(success=False, tool_name="calcula_run_python", error="timed out")
    out = _outcome({"axiom": ok, "agent.plan_execute.6.calcula": failed})
    assert out.task_status == "partial"
    assert out.unresolved_failures and "missing from the answer" in out.unresolved_failures[0]["effect"]


# -- deliverables ------------------------------------------------------------------------------------------------------
REGRESSION_QUESTION = (
    "Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = 2 kg, "
    "c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, x(0) = 0.1 m, and x'(0) = 0. Derive the analytical solution, "
    "including transient and steady-state components. Calculate the natural frequency, damping ratio, damped natural "
    "frequency, steady-state amplitude, and phase. Simulate the system over 0–20 s using a suitable numerical method. "
    "Independently compare analytical and numerical results; report maximum absolute error, residual checks, and "
    "step-size convergence. Verify units and initial conditions. Investigate the energy balance and explain the effect "
    "of damping and external forcing."
)


def test_requested_deliverables_are_read_from_the_question():
    from tribos.agents.deliverables import requested_items

    items = [r["item"] for r in requested_items(REGRESSION_QUESTION)]
    for expected in ("natural frequency", "damping ratio", "damped natural frequency", "steady-state amplitude",
                     "phase", "maximum absolute error", "step-size convergence", "energy balance"):
        assert expected in items
    assert not any("system" in i or "=" in i for i in items)  # the subject and the given values are not deliverables


def test_a_contradicted_value_or_a_missing_quantity_makes_the_answer_partial():
    import pathlib

    from tribos.agents.deliverables import assess
    from tribos.agents.orchestration.finalize import apply_deliverables
    from tribos.verify.math_claims import audit_answer

    fix = pathlib.Path(__file__).parent / "fixtures" / "math"
    captured = (fix / "mass_spring_captured_answer.md").read_text(encoding="utf-8")
    corrected = (fix / "mass_spring_corrected_answer.md").read_text(encoding="utf-8")
    bad = assess(REGRESSION_QUESTION, captured, audit_answer(captured, REGRESSION_QUESTION, {}).to_dict())
    good = assess(REGRESSION_QUESTION, corrected, audit_answer(corrected, REGRESSION_QUESTION, {}).to_dict())
    status_bad = {d["item"]: d["status"] for d in bad}
    status_good = {d["item"]: d["status"] for d in good}
    assert status_bad["steady-state amplitude"] == "failed_check" and status_bad["phase"] == "failed_check"
    assert status_good["steady-state amplitude"] == "verified" and status_good["phase"] == "verified"
    out = apply_deliverables({"task_status": "completed", "reason": "Evidence gathered and synthesized."}, bad)
    assert out["task_status"] == "partial" and "steady-state amplitude" in out["reason"]


# -- literature classification and relevance ---------------------------------------------------------------------------
@pytest.mark.parametrize("record,study_type,doc_type", [
    ({"title": "Damped Mass Spring System", "doi": "10.1017/9781009198059.014", "type": "book-chapter",
      "journal": "Offshore Structure Hydrodynamics", "source": "crossref"}, "book_chapter", "book chapter"),
    ({"title": "The Damped Harmonic Oscillator", "doi": "10.1007/0-387-21851-3_23", "type": "book-chapter",
      "journal": "Classical Theoretical Physics"}, "book_chapter", "book chapter"),
    ({"title": "Coulomb friction effect on the forced vibration", "doi": "10.1016/j.jsv.2022.117085",
      "type": "journal-article", "journal": "Journal of Sound and Vibration"}, "peer_reviewed", "journal article"),
    ({"title": "A registered work", "doi": "10.5555/abc"}, "unclassified", "unknown"),
    ({"title": "Analytic solution of the mass-spring oscillator", "doi": "10.48550/arxiv.1505.03815",
      "source": "arxiv"}, "preprint", "preprint"),
    ({"title": "Damped Harmonic Oscillator", "type": "book", "doi": "10.1017/9781108769228"}, "monograph_standard", "book"),
])
def test_works_are_classified_by_their_registered_type_not_by_having_a_doi(record, study_type, doc_type):
    from tribos.archivon.grading import grade_article

    grade = grade_article(record)
    assert grade.study_type.value == study_type
    assert grade.document_type == doc_type
    if doc_type == "journal article":
        assert grade.peer_review == "journal venue (review not verified)"
    if doc_type == "preprint":
        assert grade.peer_review == "not peer reviewed"


def test_model_variants_the_question_does_not_ask_about_rank_lower():
    from tribos.archivon.engine import _query_terms, score_article_passage

    q = "forced damped harmonic oscillator analytical solution"
    terms = _query_terms(q)
    plain = {"title": "Analytical solution of the forced damped harmonic oscillator", "summary": "x" * 80}
    quantum = {"title": "Quantum damped harmonic oscillator: an analytical solution", "summary": "x" * 80}
    market = {"title": "Real estate markets as a network of damped harmonic oscillators", "summary": "x" * 80}
    s_plain, s_q, s_m = (score_article_passage(r, terms, 0.9, q) for r in (plain, quantum, market))
    assert s_plain > s_q and s_plain > s_m
    # A question about the quantum oscillator keeps its quantum papers.
    assert score_article_passage(quantum, _query_terms("quantum " + q), 0.9, "quantum " + q) > s_q


# -- simulation extrema --------------------------------------------------------------------------------------------------
def test_dense_extrema_catch_peaks_between_output_samples():
    """Real integration of the regression IVP; the oracle is the closed-form solution evaluated densely here."""
    from tribos.dynamis.engine import dynamis_simulate_ode

    res = dynamis_simulate_ode(rhs={"x": "v", "v": "(10*cos(4*t) - 3*v - 50*x)/2"}, initial_state={"x": 0.1, "v": 0.0},
                               t_span=(0, 20), num_points=100)
    t = np.linspace(0, 20, 400_001)
    wd = math.sqrt(391) / 4
    a, b = -37 / 130, -1933 / (390 * math.sqrt(391))  # transient coefficients from the brief
    x = np.exp(-0.75 * t) * (a * np.cos(wd * t) + b * np.sin(wd * t)) + 5 / 13 * np.cos(4 * t) + 10 / 39 * np.sin(4 * t)
    ex = res["extrema"]["x"]
    assert ex["dense_min"] == pytest.approx(float(x.min()), abs=1e-5)
    assert ex["dense_min"] == pytest.approx(-0.50001, abs=2e-5)
    assert ex["sampled_min"] > ex["dense_min"] + 0.02  # 100 output samples miss the trough
    solver = res["solver"]
    assert solver["output_samples"] == 100 and solver["internal_steps"] > 100 and solver["method"] == "RK45"


def test_units_come_from_the_question_itself():
    from tribos.dynamis.stated_ode import stated_units

    assert stated_units(REGRESSION_QUESTION, "x(t)", ["x", "v"]) == {"t": "s", "x": "m", "v": "m/s"}
    assert stated_units("Solve y' = -2y with y(0) = 1 over 0 to 5", "y(t)", ["y"]) == {}


# -- memory -----------------------------------------------------------------------------------------------------------
def test_a_turn_whose_checks_evaluated_nothing_stores_nothing_as_verified(tmp_path):
    from tribos.agents.orchestration.finalize import turn_fully_supported
    from tribos.utils.memory.research_memory import ResearchMemoryEngine, turn_fully_verified

    report = SimpleNamespace(passed=True, claims=[], coverage={"extracted": 0, "evaluated": 0},
                             unsupported_claims=0, contradicted_claims=0)
    assert turn_fully_supported(report) is False
    assert turn_fully_verified(True, {"passed": True, "fully_verified": True, "coverage": {"evaluated": 0}}) is False

    mem = ResearchMemoryEngine(storage_dir=str(tmp_path))
    mem.consolidate_turn_sync(
        thread_id="t1", query="q", response="X = 0.92848 m", user_id="u1", is_turn_verified=True,
        tool_results={"lithoscribe": {"ranked_passages": [{"title": "Quantum oscillator", "passage_text": "..."}]}},
        verification={"passed": True, "fully_verified": False, "coverage": {"evaluated": 3, "failed": 1},
                      "contradicted_statements": [{"text": "X = 0.92848", "detail": "computed X = 0.46225"}]},
    )
    import sqlite3

    rows = sqlite3.connect(mem.db_path).execute("SELECT memory_type, verification_status, content FROM memory_nodes").fetchall()
    assert not any(r[1] == "VERIFIED_EMPIRICAL" for r in rows)
    assert any(r[1] == "REFUTED" and "0.92848" in r[2] and "do not reuse" in r[2] for r in rows)
    assert any(r[0] == "DIALOGUE_TURN" and "contradicted by verification" in r[2] for r in rows)


def test_legacy_verified_evidence_is_requalified_with_its_history_kept(tmp_path):
    import json
    import sqlite3

    from tribos.utils.memory.research_memory import ResearchMemoryEngine

    mem = ResearchMemoryEngine(storage_dir=str(tmp_path))
    con = sqlite3.connect(mem.db_path)
    con.execute(
        "INSERT INTO memory_nodes (id, thread_id, user_id, memory_type, content, entity_refs_json, sources_json, "
        "verification_status, confidence, is_contradicted, contradiction_notes, created_at, updated_at) "
        "VALUES ('old1','t','u','RETRIEVED_EVIDENCE','Lithoscribe Peer-Reviewed Passage Evidence: ...','[]',?, "
        "'VERIFIED_EMPIRICAL',0.95,0,NULL,1,1)",
        (json.dumps({"tool": "lithoscribe", "turn_verified": True, "unresolved_claims": 0}),),
    )
    con.commit()
    out = mem.requalify_legacy_verified()
    assert out["requalified"] == 1
    status, conf, notes, content = con.execute(
        "SELECT verification_status, confidence, contradiction_notes, content FROM memory_nodes WHERE id='old1'").fetchone()
    assert status == "PROVISIONAL" and conf <= 0.6 and "evaluated no claims" in notes
    assert content.startswith("Lithoscribe")  # content kept


# -- exports and timing -------------------------------------------------------------------------------------------------
def test_exports_say_not_evaluated_instead_of_a_perfect_score():
    from tribos.export.report_model import VerificationSection, verification_lines

    lines = verification_lines(VerificationSection(passed=True, score=1.0, status="not_evaluated",
                                                   coverage={"extracted": 0, "evaluated": 0}))
    text = "\n".join(lines)
    assert "not evaluated" in text and "1.00 / 1.00" not in text
    lines = verification_lines(VerificationSection(passed=False, score=0.0, status="failed",
                                                   coverage={"extracted": 40, "evaluated": 38, "passed": 30, "failed": 8}))
    assert any("38 of 40 claims evaluated; 30 passed, 8 failed" in ln for ln in lines)


def test_stage_seconds_never_count_the_same_time_twice():
    from tribos.agents.orchestration.finalize import stage_seconds

    phases = [
        {"phase": "route", "stage": "pipeline", "seconds": 2.0},
        {"phase": "decompose", "stage": "before_evidence", "seconds": 1.5},  # runs inside "route"
        {"phase": "evidence", "stage": "pipeline", "seconds": 4.0},
        {"phase": "plan_execute", "stage": "augment", "seconds": 60.0},
        {"phase": "first_draft", "stage": "pipeline", "seconds": 200.0},
        {"phase": "rewrite_1", "stage": "pipeline", "seconds": 170.0},
        {"phase": "gaps", "stage": "after_draft", "seconds": 14.0},
        {"phase": "verification", "stage": "pipeline", "seconds": 2.5},
    ]
    assert stage_seconds(phases) == {"planning": 2.0, "retrieval": 18.0, "execution": 60.0, "drafting": 370.0,
                                     "verification": 2.5}


def test_off_model_works_are_left_out_when_enough_on_model_works_remain():
    import asyncio as _asyncio

    from tribos.archivon.engine import ArchivonEngine

    titles = [
        "Analytical solution of the forced damped harmonic oscillator",
        "Energy balance of a forced damped harmonic oscillator",
        "Numerical solution of the damped harmonic oscillator with Runge-Kutta methods",
        "Quantum probability applied to the damped harmonic oscillator",
        "A damped harmonic oscillator in fractional differential calculus",
    ]
    recs = [{"title": t, "summary": f"{t}. " + "damped harmonic oscillator forced response " * 3, "doi": f"10.1/x{i}",
             "journal": "J", "type": "journal-article", "source": "crossref"} for i, t in enumerate(titles)]

    class _Clients:
        async def search_crossref(self, *_a, **_k):
            return recs

    engine = ArchivonEngine.__new__(ArchivonEngine)
    engine.clients = _Clients()
    engine.check_integrity = False
    out = _asyncio.run(engine.literature_search("forced damped harmonic oscillator", sources=["crossref"], max_articles=10))
    kept = [p["title"] for p in out["ranked_passages"]]
    assert not any("Quantum" in t or "fractional" in t for t in kept) and len(kept) == 3
    assert any("other model variants (fractional, quantum)" in note for note in out["limitations"])
