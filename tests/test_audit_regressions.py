"""
Offline regression tests for the defects reported in AUDIT_REPORT.md / AUDIT_FINDINGS.json.
No network or LLM access is required: tool executors and the LLM are replaced with recording fakes,
while the real tool input schemas, verifier, discovery engine, and memory engine are exercised.
"""

import asyncio
import threading
import time

import pytest

# =============================================================================
# Fakes (shared with the feature tests in tests/fakes.py; re-exported for older imports)
# =============================================================================
from tests.fakes import (  # noqa: E402,F401
    _TOOL_SCHEMAS,
    _fake_output,
    build_recording_registry,
    make_offline_orchestrator,
)
from tribos.agents.discovery import DiscoveryEngine
from tribos.tools import registry as registry_module
from tribos.tools.registry import (
    AdapterType,
    ErrorType,
    ToolRegistry,
    ToolResult,
    ToolUniverseEntry,
)
from tribos.utils.memory.research_memory import ResearchMemoryEngine
from tribos.verify.verifier import TribosVerifier


@pytest.fixture
def offline_orchestrator(monkeypatch, tmp_path):
    return make_offline_orchestrator(monkeypatch, tmp_path)


def _called(calls, tool_name):
    return [kw for name, kw in calls if name == tool_name]


# =============================================================================
# FINDING-01 / FINDING-02: routing
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Find KRAS papers only.",
        "Review recent Phase 2 clinical trials for HER2 antibody-drug conjugates in breast cancer without running simulations.",
        "Summarize KRAS literature, do not simulate anything.",
    ],
)
async def test_literature_only_requests_skip_simulation(offline_orchestrator, query):
    orch, calls = offline_orchestrator
    res = await orch.execute_inquiry(query, thread_id="t-lit", enable_web_search=True)  # literature needs Search on
    assert not _called(calls, "vivarix_simulate_time_course") and not _called(calls, "dynamis_simulate_ode") and not _called(calls, "dynamis_simulate_ode")
    assert "Vivarix" not in res.selected_agents and "Dynamis" not in res.selected_agents
    assert _called(calls, "lithoscribe_literature_synthesis") or _called(calls, "archivon_literature_search")


@pytest.mark.asyncio
async def test_gene_mention_alone_does_not_trigger_simulation(offline_orchestrator):
    orch, calls = offline_orchestrator
    await orch.execute_inquiry("Analyze KRAS G12D signaling and downstream targets.", thread_id="t-gene", enable_web_search=False)
    assert not _called(calls, "vivarix_simulate_time_course")


@pytest.mark.asyncio
async def test_explicit_simulation_request_still_runs(offline_orchestrator):
    orch, calls = offline_orchestrator
    res = await orch.execute_inquiry("Simulate the Lorenz system for 100 seconds.", thread_id="t-sim", enable_web_search=False)
    sims = _called(calls, "dynamis_simulate_ode")
    assert sims and sims[0].get("model_name") == "lorenz" and tuple(sims[0]["t_span"]) == (0.0, 100.0)
    assert "Dynamis" in res.selected_agents
    assert not _called(calls, "dynamis_equilibrium") and not _called(calls, "vivarix_compute_steady_state")


@pytest.mark.asyncio
async def test_steady_state_request_runs_root_finding(monkeypatch, tmp_path):
    from tests.fakes import make_offline_orchestrator
    from tribos.dynamis.schemas import DynamisEquilibriumInput

    fixed = {"fixed_point": {"x": 0.0, "v": 0.0}, "stability": "stable_spiral", "converged": True,
             "residual_norm": 0.0, "eigenvalues": [{"real": -0.3, "imag": 1.98, "str": "-0.3+1.98j"}]}
    orch, calls = make_offline_orchestrator(
        monkeypatch, tmp_path, extra_tools={"dynamis_equilibrium": (DynamisEquilibriumInput, lambda kw: fixed)}
    )
    res = await orch.execute_inquiry("Simulate the damped oscillator and compute its steady state.", thread_id="t-ss", enable_web_search=False)
    eq = _called(calls, "dynamis_equilibrium")
    assert eq and eq[0]["rhs"]["v"] == "-2 * zeta * omega * v - omega^2 * x" and eq[0]["guess"] == {"x": 1.0, "v": 0.0}
    assert res.execution_artifacts["dynamis"]["steady_state"]["fixed_point"] == {"x": 0.0, "v": 0.0}
    assert not _called(calls, "vivarix_compute_steady_state")


@pytest.mark.asyncio
async def test_single_cell_intent_without_dataset_reports_dataset_required(offline_orchestrator):
    orch, calls = offline_orchestrator
    res = await orch.execute_inquiry(
        "Perform single-cell transcriptomic clustering for the KRAS tumor microenvironment.", thread_id="t-nods", enable_web_search=False
    )
    assert not _called(calls, "lumicell_analyze_single_cell")
    assert "lumicell" not in res.execution_artifacts


# =============================================================================
# FINDING-03: KEGG argument contract
# =============================================================================


# =============================================================================
# FINDING-04: discovery scores reflect observations
# =============================================================================

def _vivarix(initial, final):
    return ToolResult(success=True, tool_name="vivarix", data={"initial_concentrations": initial, "final_concentrations": final})


def test_discovery_kinetic_score_tracks_flux_change():
    small = DiscoveryEngine.prioritize_hypotheses("q", "ERK2", {"vivarix": _vivarix({"Erk2-PP": 10.0}, {"Erk2-PP": 10.1})})
    large = DiscoveryEngine.prioritize_hypotheses("q", "ERK2", {"vivarix": _vivarix({"Erk2-PP": 10.0}, {"Erk2-PP": 200.0})})
    k_small = small.candidates[0].observed_components["pathway_kinetics"]
    k_large = large.candidates[0].observed_components["pathway_kinetics"]
    assert k_small < 0.05 < 0.9 < k_large
    assert k_small != 0.75 and k_large != 0.75


def test_discovery_single_cell_score_tracks_log_fold_change():
    def lum(lfc, padj):
        return ToolResult(
            success=True,
            tool_name="lumicell",
            data={"top_markers_by_cluster": {"0": [{"gene": "KRAS", "cluster": "0", "log_fold_change": lfc, "p_adj": padj}]}},
        )

    weak = DiscoveryEngine.prioritize_hypotheses("q", "KRAS", {"lumicell": lum(0.5, 0.01), "vivarix": _vivarix({"A": 1}, {"A": 2})})
    strong = DiscoveryEngine.prioritize_hypotheses("q", "KRAS", {"lumicell": lum(5.0, 0.01), "vivarix": _vivarix({"A": 1}, {"A": 2})})
    insignificant = DiscoveryEngine.prioritize_hypotheses("q", "KRAS", {"lumicell": lum(5.0, 0.4), "vivarix": _vivarix({"A": 1}, {"A": 2})})
    assert weak.candidates[0].observed_components["single_cell_marker_evidence"] == pytest.approx(0.125)
    assert strong.candidates[0].observed_components["single_cell_marker_evidence"] == pytest.approx(1.0)
    assert insignificant.candidates[0].observed_components["single_cell_marker_evidence"] is None


# =============================================================================
# FINDING-05 / FINDING-06 / FINDING-07 / FINDING-08 / FIX-13: verifier
# =============================================================================

def _sim_result():
    # A Dynamis time course (dynamis_simulate_ode output shape) of two coupled state variables.
    return ToolResult(
        success=True,
        tool_name="dynamis_simulate_ode",
        data={
            "model_name": "two_tank",
            "state_variables": ["h1", "h1_dot"],
            "t_span": [0.0, 120.0],
            "summary": {
                "h1": {"initial": 100.0, "final": 34.13, "min": 34.13, "max": 100.0, "mean": 55.0},
                "h1_dot": {"initial": 0.0, "final": 65.87, "min": 0.0, "max": 65.87, "mean": 40.0},
            },
        },
    )


def test_verifier_no_false_positive_on_suffixed_variable_name():
    report = TribosVerifier().verify_response(
        query="Simulate the two-tank system",
        response_markdown="h1_dot reached 65.87 while h1 was 34.13.\n| **h1** | 100.000 | 34.130 | -65.9% |",
        tool_results={"dynamis": _sim_result()},
    )
    assert report.numerical_checks_failed == 0
    assert not [d for d in report.defects if d.category == "NUMERICAL"]


def test_verifier_no_false_positive_with_unicode_hyphens():
    # Models typeset names with U+2011 and use narrow no-break spaces; "h1‑dot" must not read as "h1".
    sim = _sim_result()
    sim.data["summary"]["h1-dot"] = sim.data["summary"].pop("h1_dot")
    report = TribosVerifier().verify_response(
        query="Simulate the two-tank system",
        response_markdown="- h1‑dot = **65.87**\n- h1 = **34.13**\nThe flow h1‑dot rises to 65.87.",
        tool_results={"dynamis": sim},
    )
    assert not [d for d in report.defects if d.category == "NUMERICAL"]


def test_verifier_still_catches_errors_written_with_unicode_hyphens():
    sim = _sim_result()
    sim.data["summary"]["h1-dot"] = sim.data["summary"].pop("h1_dot")
    report = TribosVerifier().verify_response(
        query="Simulate the two-tank system",
        response_markdown="- final h1‑dot = **12.00**",
        tool_results={"dynamis": sim},
    )
    assert [d for d in report.defects if d.category == "NUMERICAL"]


def test_verifier_catches_role_and_sign_errors_and_converts_declared_units():
    verifier = TribosVerifier()
    wrong_role = verifier.verify_response("tank simulation", "The final h1 value: 100.0.", {"dynamis": _sim_result()})
    assert any(d.category == "NUMERICAL" for d in wrong_role.defects)
    negative = verifier.verify_response("tank simulation", "h1: -34.13 at the end of the run.", {"dynamis": _sim_result()})
    assert any(d.category == "NUMERICAL" for d in negative.defects)
    sim = _sim_result()
    sim.data["units"] = {"h1": "m"}
    converted = verifier.verify_response("tank simulation", "h1 ended at 34130 mm.", {"dynamis": sim})
    assert not any(d.category == "NUMERICAL" for d in converted.defects)
    # Without a stated unit, a prefixed value is not compared (its scale is unknown).
    unknown = verifier.verify_response("tank simulation", "h1 ended at 34130 mm.", {"dynamis": _sim_result()})
    assert not any(d.category == "NUMERICAL" for d in unknown.defects)


def test_verifier_flags_unobserved_arxiv_and_doi_but_not_observed_ones():
    passages = ToolResult(success=True, tool_name="archivon_literature_search", data={"ranked_passages": [
        {"arxiv_id": "1602.03837", "doi": "10.1103/PhysRevLett.116.061102", "passage_text": "Observation of GW150914."},
    ]})
    report = TribosVerifier().verify_response(
        "GW150914 detection",
        "GW150914 was reported in arXiv:1602.03837v2 (DOI 10.1103/PhysRevLett.116.061102), not in arXiv:9912.99999.",
        {"archivon": passages},
    )
    flagged = {d.claim for d in report.defects if d.category in ("IDENTIFIER", "CITATION")}
    assert "arXiv:9912.99999" in flagged
    assert not any("1602.03837" in f or "061102" in f for f in flagged)
    assert "ARXIV:1602.03837" in report.verified_identifiers


def _passages(*texts):
    return ToolResult(
        success=True,
        tool_name="archivon_literature_search",
        data={"ranked_passages": [{"arxiv_id": f"2401.0000{i}", "passage_text": t} for i, t in enumerate(texts, 1)]},
    )


def test_verifier_rejects_measured_claim_backed_by_unrelated_passages():
    report = TribosVerifier().verify_response(
        "YBCO critical temperature",
        "Experiments measured a critical temperature of 135 K for the YBCO film (arXiv:2401.00001).",
        {"archivon": _passages("Phonon transport in silicon nanowires.", "Turbulent boundary layers over riblets.")},
    )
    assert any(d.category == "UNSUPPORTED_CLAIM" and d.severity.value == "CRITICAL" for d in report.defects)
    assert report.passed is False


def test_verifier_accepts_measured_claim_grounded_in_passage():
    report = TribosVerifier().verify_response(
        "YBCO critical temperature",
        "Resistivity measurements gave a critical temperature of 92 K for the YBCO film (arXiv:2401.00001).",
        {"archivon": _passages(
            "Resistivity measurements of the YBCO film show a critical temperature of 92 K.",
            "Unrelated passage about turbulence.",
        )},
    )
    assert not any(d.category == "UNSUPPORTED_CLAIM" for d in report.defects)


def test_verifier_allows_honest_limitation_statements():
    report = TribosVerifier().verify_response(
        "compound X-99 superconducting transition",
        "No measured transition temperature is available for compound X-99; the value is unverified.",
        {"archivon": _passages("Cuprate superconductivity review.")},
    )
    assert not any(d.category == "UNSUPPORTED_CLAIM" for d in report.defects)


def test_verifier_equilibrium_distinction():
    verifier = TribosVerifier()
    asserted = verifier.verify_response("tank simulation", "h1 reaches an equilibrium of 34.13.", {"dynamis": _sim_result()})
    assert any(d.category == "MODELING_DISTINCTION" for d in asserted.defects)
    hedged = verifier.verify_response("tank simulation", "h1 ends at 34.13; this is not an equilibrium.", {"dynamis": _sim_result()})
    assert not any(d.category == "MODELING_DISTINCTION" for d in hedged.defects)


def test_verifier_suggested_experiment_is_not_an_equilibrium_claim():
    # Found by the evaluation harness: a "Suggested next experiments" bullet was flagged as a modelling claim.
    report = TribosVerifier().verify_response(
        "tank simulation",
        "h1 ends at 34.13.\n\n### Suggested next experiments\n"
        "- Run a systematic parameter sweep of the valve gain and record the equilibrium of h1 at 20 settings.",
        {"dynamis": _sim_result()},
    )
    assert not any(d.category == "MODELING_DISTINCTION" for d in report.defects)


def test_verifier_function_argument_is_not_a_value():
    # "h1(120) = 34.13": the argument is the time, not the value of h1.
    report = TribosVerifier().verify_response(
        "tank simulation",
        "| Variable | Value |\n|---|---|\n| h1(120) | 34.13 |\n| h1_dot(120) | 65.87 |",
        {"dynamis": _sim_result()},
    )
    assert not [d for d in report.defects if d.category == "NUMERICAL"], [d.description for d in report.defects]


def test_verifier_accepts_identifiers_from_verified_memory():
    verifier = TribosVerifier()
    text = "As established previously, arXiv:1602.03837 reported the first binary black hole merger."
    without = verifier.verify_response("previous GW conclusion", text, {})
    assert any(d.category == "IDENTIFIER" for d in without.defects)
    with_memory = verifier.verify_response(
        "previous GW conclusion", text, {}, historical_identifiers={"arxiv": {"arXiv:1602.03837"}}
    )
    assert not any(d.category == "IDENTIFIER" for d in with_memory.defects)


# =============================================================================
# FINDING-09: tenant isolation in the memory engine
# =============================================================================

@pytest.mark.asyncio
async def test_memory_scoped_by_user(tmp_path):
    mem = ResearchMemoryEngine(storage_dir=str(tmp_path))
    data = {"vivarix": {"model_id": "BIOMD0000000010", "final_concentrations": {"Mos": 1.0}}}
    await mem.consolidate_turn("shared-thread", "KRAS query", "resp", data, user_id="alice", is_turn_verified=True)
    await mem.consolidate_turn("shared-thread", "KRAS query", "resp", data, user_id="bob", is_turn_verified=True)

    assert mem.get_verified_identifiers("shared-thread", user_id="alice")["biomodels"] == {"BIOMD0000000010"}
    mem.clear_all_memory(user_id="alice")
    assert mem.get_memory_stats(user_id="alice")["total_nodes"] == 0
    assert mem.get_memory_stats(user_id="bob")["total_nodes"] > 0
    assert not mem.search_memory("KRAS", user_id="alice")
    assert mem.get_entity_vault(user_id="bob")


# =============================================================================
# FINDING-09: API authentication
# =============================================================================

@pytest.fixture
def api_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main

    engine = ResearchMemoryEngine(storage_dir=str(tmp_path))
    monkeypatch.setattr(backend_main, "get_research_memory_engine", lambda: engine)
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    return TestClient(backend_main.app), engine


def test_api_rejects_missing_or_invalid_token(api_client):
    client, _ = api_client
    assert client.get("/api/memory/stats").status_code == 401
    assert client.delete("/api/memory/clear", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_api_scopes_memory_to_authenticated_user(api_client):
    client, engine = api_client
    asyncio.run(engine.consolidate_turn("t1", "KRAS query", "resp", {}, user_id="bob", is_turn_verified=True))
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    assert client.get("/api/memory/thread/t1", headers=alice).json()["count"] == 0
    assert client.get("/api/memory/thread/t1", headers=bob).json()["count"] > 0
    assert client.delete("/api/memory/clear", headers=alice).status_code == 200
    assert client.get("/api/memory/thread/t1", headers=bob).json()["count"] > 0


def test_api_fails_closed_when_auth_unconfigured(api_client, monkeypatch):
    client, _ = api_client
    monkeypatch.delenv("TRIBOS_API_TOKENS", raising=False)
    assert client.get("/api/memory/stats").status_code == 503


def test_api_accepts_jwt_subject(api_client, monkeypatch):
    import jwt

    client, _ = api_client
    monkeypatch.setenv("TRIBOS_JWT_SECRET", "test-secret-with-enough-length-0123456789")
    token = jwt.encode({"sub": "carol", "exp": int(time.time()) + 60}, "test-secret-with-enough-length-0123456789", algorithm="HS256")
    resp = client.get("/api/memory/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    expired = jwt.encode({"sub": "carol", "exp": int(time.time()) - 60}, "test-secret-with-enough-length-0123456789", algorithm="HS256")
    assert client.get("/api/memory/stats", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


# =============================================================================
# FIX-14: synchronous executors do not block the event loop
# =============================================================================

@pytest.mark.asyncio
async def test_sync_executor_runs_off_event_loop_and_respects_timeout():
    reg = ToolRegistry()
    seen = {}

    def slow(query: str, max_results: int = 3):
        seen["thread"] = threading.get_ident()
        time.sleep(0.5)
        return {"query": query}

    reg.register(
        ToolUniverseEntry(
            name="slow_tool", description="slow", domain="test", adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=registry_module.WebSurferSearchInput, canonical_id_types=[], timeout_seconds=0.1, tags=[],
        ),
        executor=slow,
    )
    res = await reg.execute("slow_tool", query="x")
    assert res.success is False and res.error_type == ErrorType.TIMEOUT
    assert seen["thread"] != threading.get_ident()
