"""Regression tests for the agentic fixes (SEC-5/SUP-3, BRK-4, LOG-10, LOG-11, LOG-17 to LOG-24, router/jobs polish)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from tribos.agentic import approval as approval_mod
from tribos.agentic import clarify as clarify_mod
from tribos.agentic.confidence import _grade_weight, exact_match
from tribos.agentic.counter_evidence import negation_queries, recheck_pairs
from tribos.agentic.gaps import MODULE_PATTERNS, mentions_modules
from tribos.agentic.nli import candidate_passages, collect_documents
from tribos.agentic.plan_graph import is_expensive_tool, is_simulation_tool, policy_violation
from tribos.agentic.router import _first_json
from tribos.agentic.specialists import (
    MODULE_SIMULATION,
    fetch_new_literature,
    is_pure_derivation,
    not_requested_modules,
    query_entities,
)
from tribos.tools.registry import get_tool_registry


def _entry(name: str) -> Any:
    entry = get_tool_registry().get_entry(name)
    assert entry is not None, name
    return entry


# SEC-5 / SUP-3 / LOG-22 ---------------------------------------------------------------------------------------------
def test_code_execution_and_long_numerical_runs_need_approval():
    for name in ("calcula_run_python", "calcula_run_sagemath", "axiom_sagemath", "analysis_run_python",
                 "dynamis_simulate_ode", "dynamis_parameter_scan", "dynamis_fit_parameters", "dynamis_optimize"):
        assert is_expensive_tool(name, _entry(name)), name
    for name in ("axiom_simplify", "physis_constants", "archivon_literature_search", "dynamis_equilibrium"):
        assert not is_expensive_tool(name, _entry(name)), name


def test_simulation_ban_covers_every_dynamis_tool():
    ctx = SimpleNamespace(suppress_simulation=True, simulation_constraints=None, extras={})
    for name in ("dynamis_simulate_ode", "dynamis_parameter_scan", "dynamis_equilibrium", "dynamis_fit_parameters",
                 "dynamis_optimize", "vivarix_simulate_time_course"):
        assert is_simulation_tool(name, _entry(name))
        assert "simulation was forbidden" in (policy_violation(_entry(name), ctx) or "")
    assert policy_violation(_entry("axiom_dsolve"), ctx) is None


# LOG-23 -------------------------------------------------------------------------------------------------------------
def test_planner_policy_honours_skip_retrieval():
    need = SimpleNamespace(skip_retrieval=True, reason="self-contained calculation")
    ctx = SimpleNamespace(evidence_need=need, extras={}, enable_web_search=True)
    assert policy_violation(_entry("archivon_literature_search"), ctx) == "self-contained calculation"
    assert policy_violation(_entry("lithoscribe_literature_synthesis"), ctx)
    assert policy_violation(_entry("axiom_solve"), ctx) is None


# BRK-4 ----------------------------------------------------------------------------------------------------------------
def test_graded_documents_get_their_archivon_weight():
    assert _grade_weight({"grade_label": "Formal proof / theorem"}) == 1.0
    assert _grade_weight({"grade_label": "Preprint"}) == 0.6


# LOG-10 ---------------------------------------------------------------------------------------------------------------
def test_literature_search_receives_max_results():
    sent: dict[str, Any] = {}

    class State:
        registry = get_tool_registry()
        tool_results: dict[str, Any] = {}

        async def call_tool(self, tool: str, **kw: Any) -> Any:
            sent.update(tool=tool, **kw)
            return SimpleNamespace(success=False, data=None, error_type=None)

    asyncio.run(fetch_new_literature(State(), phase="gaps", query="Navier-Stokes slip", purpose="t", seen=set(),
                                     keywords=["slip"], max_articles=4))
    assert sent["tool"] == "archivon_literature_search"
    assert sent["max_results"] == 4 and "max_articles" not in sent  # arguments follow the tool's own schema


# LOG-11 / SUP-5 -----------------------------------------------------------------------------------------------------
def test_nli_documents_and_citations_use_shared_keys():
    res = SimpleNamespace(success=True, tool_name="archivon_literature_search", data={"ranked_passages": [
        {"arxiv_id": "2312.04511v2", "doi": "10.1000/ABC", "passage_text": "Slip flow breaks down at high Knudsen number."},
    ]})
    docs = collect_documents({"lit": res})
    assert docs[0]["source_key"] == "ARXIV:2312.04511" and "DOI:10.1000/abc" in docs[0]["keys"]
    picked = candidate_passages("As shown in arXiv:2312.04511, the model fails.", docs)
    assert picked and picked[0][0] == "ARXIV:2312.04511"


def test_recheck_never_pairs_a_claim_with_its_own_source_across_formats():
    claims = [{"id": "a1", "text": "Slip flow theory predicts the measured flow rate", "source_key": "DOI:10.1000/abc"}]
    rows = [{"passage": "Slip flow theory fails to predict the measured flow rate.", "source_key": "ARXIV:2312.04511",
             "keys": ["ARXIV:2312.04511", "DOI:10.1000/abc"]}]
    assert recheck_pairs(claims, rows) == []


def test_exact_match_recognises_arxiv_citations():
    doc = "we measure a drag coefficient of 0.47 for the sphere"
    assert exact_match("The drag coefficient is 0.47 (arXiv:2312.04511).", "ARXIV:2312.04511", doc)


# LOG-17 ---------------------------------------------------------------------------------------------------------------
def _sim_ctx(**kw: Any) -> SimpleNamespace:
    base = {"scope": "research", "genes": [], "attachments": [], "primary_target": None, "biomodel_id": None,
            "model_attachment": None, "is_simulation_intent": True}
    base.update(kw)
    return SimpleNamespace(**base)


def test_written_out_odes_are_not_clarified():
    for q in ("Simulate the ODE dx/dt = -2*x + sin(t) with x(0)=1 for 10 s",
              "Simulate y'' + 3y' + 2y = 0 with y(0)=1, y'(0)=0"):
        assert not clarify_mod.detect_signals(_sim_ctx(), q), q
    asked = clarify_mod.detect_signals(_sim_ctx(), "Simulate the model for 100 seconds")
    assert asked[0]["signal"] == "simulation_without_model"
    assert not any("BioModels" in o for o in asked[0]["options"])


# LOG-24 ---------------------------------------------------------------------------------------------------------------
def test_hdf5_and_mat_attachments_count_as_datasets():
    a = SimpleNamespace(kind="hdf5", display_name="run_a.h5", id="ds_1")
    b = SimpleNamespace(kind="mat", display_name="run_b.mat", id="ds_2")
    assert clarify_mod.detect_signals(_sim_ctx(is_simulation_intent=False, attachments=[a, b]), "Analyse the data")
    ctx = SimpleNamespace(should_run=lambda k: False, attachments=[a], biomodel_id=None, model_attachment=None)
    state = SimpleNamespace(ctx=ctx, clean_query="Run a regression on the data", options={})
    assert approval_mod.expensive_work(state) == ["sandboxed code analysis"]


# LOG-18 ---------------------------------------------------------------------------------------------------------------
def test_negation_queries_are_stem_and_never_drug_safety():
    ctx = SimpleNamespace(entities=[SimpleNamespace(type="equation", label="Navier-Stokes equations", mention="")])
    queries = negation_queries(query_entities(ctx))
    assert queries[0] == "Navier-Stokes equations limitations"
    assert not any("adverse" in q or "trial" in q for q in queries)
    assert query_entities(ctx)["drugs"] == []


# LOG-20 / LOG-21 ----------------------------------------------------------------------------------------------------
def test_pure_derivations_skip_gap_and_counter_evidence_searches():
    sub = [SimpleNamespace(focus="math"), SimpleNamespace(focus="physics")]
    assert is_pure_derivation(SimpleNamespace(ctx=SimpleNamespace(intents=set()), sub_questions=sub))
    assert is_pure_derivation(SimpleNamespace(ctx=SimpleNamespace(intents={"derive", "explain"}), sub_questions=[]))
    assert not is_pure_derivation(SimpleNamespace(ctx=SimpleNamespace(intents={"derive", "literature"}), sub_questions=sub))


def test_not_requested_simulation_is_never_a_gap():
    ctx = SimpleNamespace(intents=set(), is_simulation_intent=False, simulation_plan=None, biomodel_id=None,
                          model_attachment=None, suppress_simulation=False, simulation_constraints=None)
    modules = not_requested_modules(ctx, {})
    assert modules == [MODULE_SIMULATION] and MODULE_SIMULATION in MODULE_PATTERNS
    assert mentions_modules("A time-course simulation of the system could not be run.", modules)
    assert not mentions_modules("The closed form of the ODE was not established.", modules)


# Polish ---------------------------------------------------------------------------------------------------------------
def test_router_json_is_the_first_object_not_a_greedy_span():
    assert _first_json('reply {"a": 1} trailing {"b": 2}') == {"a": 1}
    assert _first_json("no json here") is None
