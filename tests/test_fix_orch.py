"""Regression tests for the ORCH fixes: STEM tool results reach the synthesis prompt (LOG-1/SUP-9), the vivarix
aliases never simulate a canned system (LOG-2), preset matching (LOG-5), Axiom and Calcula in the classic pipeline
(LOG-3/LOG-4), one equilibrium key (BRK-3), alias de-duplication (LOG-29), STEM follow-up subjects (LOG-27), effort
keys (LOG-26), raw-string prompts (BRK-5) and Physis upstream errors (BRK-1)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.fakes import called, make_offline_orchestrator
from tribos.agents import query_planner as qp
from tribos.agents.orchestration.gather import resolve_dynamis_preset
from tribos.agents.prompts import (
    CORRECTION_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    build_evidence_block,
)
from tribos.agents.result_keys import distinct_results
from tribos.dynamis.engine import dynamis_equilibrium, dynamis_parameter_scan, dynamis_simulate_ode
from tribos.tools.registry import ErrorType, ToolRegistry, ToolResult


def _ok(tool: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(success=True, tool_name=tool, data=data)


# -- LOG-1 / SUP-9: every STEM tool's successful result is in the evidence, with its key values ------------------
def test_dynamis_time_course_equilibrium_and_scan_reach_the_evidence():
    sim = dynamis_simulate_ode(model_name="lorenz", t_span=(0.0, 20.0), num_points=4001)
    eq = dynamis_equilibrium(rhs={"x": "v", "v": "-2*0.15*2*v - 4*x"}, guess={"x": 0.3, "v": 0.1})
    scan = dynamis_parameter_scan(rhs={"x": "-k*x"}, initial_state={"x": 1.0}, parameter="k", scan_range=(0.5, 2.0),
                                  num_points=4, t_span=(0.0, 1.0))
    block = build_evidence_block(
        {"dynamis": _ok("dynamis_simulate_ode", sim), "vivarix": None, "dynamis_equilibrium": _ok("dynamis_equilibrium", eq),
         "dynamis_scan": _ok("dynamis_parameter_scan", scan)}, "")
    assert '<dynamis tool="dynamis_simulate_ode" model="lorenz"' in block and 't_end="20.0"' in block
    assert "<state_variables>x, y, z</state_variables>" in block and "<final_state" in block
    final_x = sim["summary"]["x"]["final"]
    assert f"{final_x:.6g}" in block
    samples = block[block.index("<trajectory_samples"):block.index("</trajectory_samples>")]
    assert 'shown="21" of="4001"' in samples and len(samples) < 3000  # decimated
    assert 'stability="stable_spiral"' in block and "<fixed_point>" in block and "<eigenvalues>" in block
    assert '<dynamis_scan tool="dynamis_parameter_scan" parameter="k"' in block and block.count("<point ") == 4
    assert "<vivarix" not in block and "<biodiscovery_ranking>" not in block  # empty ranking is not emitted


def test_physis_axiom_and_calcula_reach_the_evidence():
    from tribos.axiom.agent import solve_problem_tool
    from tribos.extensions.physis import execute_physis_constants, execute_physis_units

    const = execute_physis_constants("fine-structure constant", limit=1)
    units = execute_physis_units(value=1.0, from_unit="eV", to_unit="J")
    ax = asyncio.run(solve_problem_tool("Solve dy/dx + 2y = e^{-x}"))
    calc = {"status": "ok", "stdout": "drag = 4.2e-05 N\n", "result": {"terminal_velocity_m_s": 3.871},
            "figures": [{"name": "figure_1.png", "png_base64": "AAAA"}], "tables": []}
    block = build_evidence_block({
        "physis": const, "axiom": _ok("axiom_solve_problem", ax), "calcula": _ok("calcula_run_python", calc),
    }, "")
    c = const.data["constants"][0]
    assert f'name="{c["name"]}"' in block and f'value="{c["value"]}"' in block and 'source="NIST CODATA 2022"' in block
    assert '<axiom tool="axiom_solve_problem" status="verified"' in block and "exp(-x)" in block and "<check passed=" in block
    assert "3.871" in block and "drag = 4.2e-05 N" in block and '<figures count="1">figure_1.png' in block
    assert "AAAA" not in block  # figure bytes never reach the prompt
    unit_block = build_evidence_block({"physis": units}, "")
    assert "<unit_conversion" in unit_block and 'from="1.0 eV"' in unit_block and "1.60218e-19" in unit_block


# -- LOG-2: the vivarix aliases never report a canned system as success ---------------------------------------
def _alias_registry() -> ToolRegistry:
    from tribos.tools.registry import register_default_tools

    reg = ToolRegistry()
    register_default_tools(reg)
    return reg


def test_vivarix_alias_rejects_biomodels_and_maps_named_presets():
    reg = _alias_registry()
    bad = asyncio.run(reg.execute("vivarix_compute_steady_state", biomodel_id="BIOMD0000000010"))
    assert not bad.success and bad.error_type == ErrorType.VALIDATION_ERROR and "BioModels" in (bad.error or "")
    assert bad.metadata.get("reason_code") == "MODEL_REQUIRED"
    sim = asyncio.run(reg.execute("vivarix_simulate_time_course", duration=5.0, intervals=10, model_label="Lotka-Volterra"))
    assert sim.success and sim.data["model_name"] == "lotka_volterra" and sim.data["t_span"] == [0.0, 5.0]
    ss = asyncio.run(reg.execute("vivarix_compute_steady_state", model_label="damped oscillator"))
    assert ss.success and abs(ss.data["fixed_point"]["x"]) < 1e-9
    scan = asyncio.run(reg.execute("vivarix_parameter_scan", parameter_name="V1", model_label="lorenz"))
    assert not scan.success and "not a parameter" in (scan.error or "")


# -- LOG-5: word-boundary preset matching, longest name first, nothing on no match ---------------------------
@pytest.mark.parametrize("text, preset", [
    ("Simulate a damped harmonic oscillator for 10 s", "damped_oscillator"),
    ("Simulate the harmonic oscillator", "harmonic_oscillator"),
    ("Control the pendulum to the desired angle", "pendulum"),
    ("What is the desired angle of attack?", None),
    ("Simulate the SIR model for 60 days", "sir"),
    ("Simulate the predator-prey system", "lotka_volterra"),
    ("Simulate KRAS using BIOMD0000000048", None),
    ("Simulate the circuit", None),
])
def test_preset_matching(text, preset):
    assert resolve_dynamis_preset(text) == preset


@pytest.mark.asyncio
async def test_unidentified_system_runs_no_stand_in(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry("Simulate KRAS using BIOMD0000000048 for 100 seconds.", thread_id="t-none",
                                     enable_web_search=False)
    assert not called(calls, "dynamis_simulate_ode") and not called(calls, "vivarix_simulate_time_course")
    assert res.task_status["task_status"] == "needs_input" and "BioModels" in res.task_status["reason"]


# -- LOG-3 / LOG-4: Axiom runs in the classic pipeline; Calcula never runs a placeholder ----------------------
@pytest.mark.asyncio
async def test_classic_pipeline_runs_axiom_and_skips_codeless_calcula(monkeypatch, tmp_path):
    from tribos.axiom.schemas import AxiomSolveProblemInput

    answer = {"status": "verified", "answer": {"text": "y(x) = (C1*exp(-x) + 1)*exp(-x)", "latex": "y"},
              "verification": {"status": "verified", "level": 2, "checks": []}, "uncertainty": [], "problem": {"kind": "ode"}}
    orch, calls = make_offline_orchestrator(
        monkeypatch, tmp_path, extra_tools={"axiom_solve_problem": (AxiomSolveProblemInput, lambda kw: answer)}
    )
    res = await orch.execute_inquiry("Solve dy/dx + 2y = e^{-x} and compute the value at x = 1.", thread_id="t-ax",
                                     enable_web_search=False)
    assert called(calls, "axiom_solve_problem") and res.execution_artifacts["axiom"]["status"] == "verified"
    assert not called(calls, "calcula_run_python") and not called(calls, "analysis_run_python")
    assert "Calcula" not in res.selected_agents


# -- BRK-3: the equilibrium is computed for the same system and read back under one key -----------------------
@pytest.mark.asyncio
async def test_equilibrium_key_is_read_by_the_task_status(monkeypatch, tmp_path):
    from tribos.dynamis.schemas import DynamisEquilibriumInput

    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path, extra_tools={
        "dynamis_equilibrium": (DynamisEquilibriumInput, lambda kw: dynamis_equilibrium(**kw)),
    })
    res = await orch.execute_inquiry("Simulate the Van der Pol oscillator and compute its steady state.", thread_id="t-eq",
                                     enable_web_search=False)
    eq = called(calls, "dynamis_equilibrium")
    assert eq and eq[0]["rhs"] == {"x": "v", "v": "mu * (1 - x^2) * v - x"}
    assert res.task_status["executed_operation"] == "steady_state"


# -- LOG-29: alias keys are not counted twice --------------------------------------------------------------
def test_alias_keys_are_deduplicated():
    lit = _ok("archivon_literature_search", {"ranked_passages": []})
    dyn = _ok("dynamis_simulate_ode", {"summary": {}})
    other = _ok("vivarix_simulate_time_course", {"final_concentrations": {}})
    assert set(distinct_results({"archivon": lit, "lithoscribe": lit, "dynamis": dyn, "vivarix": dyn})) == {"archivon", "dynamis"}
    assert set(distinct_results({"dynamis": dyn, "vivarix": other})) == {"dynamis", "vivarix"}
    assert set(distinct_results({"vivarix": other})) == {"vivarix"}


# -- LOG-27: a STEM follow-up resolves to the system, never to a fake gene --------------------------------------
@pytest.mark.asyncio
async def test_followup_resolves_to_the_lorenz_system():
    async def ctx_for(q: str, prior: dict[str, str] | None = None) -> Any:
        return await qp.build_query_context(query=q, clean_query=q, registry=None, enable_web_search=False,
                                            attachments=[], attachment_errors=[], user_id="u", thread_id="t",
                                            model_name="x", api_key=None, prior_subject=prior)

    first = await ctx_for("Simulate the Lorenz system for 20 seconds")
    subject = qp.active_subject(first)
    assert subject.get("system") == "lorenz" and "gene" not in subject
    second = await ctx_for("Now simulate it for 50 seconds", subject)
    assert second.primary_gene is None and not second.genes
    assert resolve_dynamis_preset(second.clean_query, *(e.label for e in second.systems), second.system_name) == "lorenz"
    assert second.simulation_plan.duration_seconds == 50.0


@pytest.mark.asyncio
async def test_memory_stores_the_stem_subject(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    await orch.execute_inquiry("Simulate the Lorenz system for 20 seconds", thread_id="t-mem", enable_web_search=False)
    stored = orch.memory.get_active_subject("default_user", "t-mem") or {}
    assert "gene" not in stored
    await orch.execute_inquiry("Now simulate it for 50 seconds", thread_id="t-mem", enable_web_search=False)
    sims = called(calls, "dynamis_simulate_ode")
    assert sims[-1]["model_name"] == "lorenz" and tuple(sims[-1]["t_span"]) == (0.0, 50.0)


# -- LOG-26 / BRK-5 / polish ------------------------------------------------------------------------------
def test_effort_depths_have_instructions_and_no_clinical_wording():
    import inspect

    from tribos.agentic.config import EFFORT_PROFILES
    from tribos.agents.orchestration import draft

    src = inspect.getsource(draft.write_first_draft)
    for profile in EFFORT_PROFILES.values():
        assert f'"{profile["deliberation_depth"]}":' in src
    for word in ("pharmacokinetic", "biomarker", "clinical trial"):
        assert word not in src


def test_prompts_have_no_literal_continuations_or_clinical_rules():
    for prompt in (SYNTHESIS_SYSTEM_PROMPT, CORRECTION_SYSTEM_PROMPT):
        assert "\\\n" not in prompt
    assert "species name" not in CORRECTION_SYSTEM_PROMPT


def test_physis_upstream_failures_use_the_real_error_type(monkeypatch):
    from tribos.extensions import physis as ext

    class Boom:
        async def lookup_oeis(self, **_kw: Any) -> Any:
            raise ConnectionError("down")

    monkeypatch.setattr(ext, "get_physis_engine", lambda: Boom())
    res = asyncio.run(ext.execute_physis_oeis("A000045"))
    assert not res.success and res.error_type == ErrorType.UPSTREAM_API_ERROR
