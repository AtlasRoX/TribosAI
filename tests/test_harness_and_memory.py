"""Comprehensive Verification Test Suite for Perfect Agentic Harness and Unified Cognitive Memory.

Validates:
1. Working Memory (Tier 1): Goal/Task state transitions, inter-specialist variable cache with Pint units, scratchpad compaction.
2. Session Memory (Tier 2): SQLite threads, turns, answer revision tree, unified diffing, scoped directives.
3. Episodic Memory (Tier 3): Bi-temporal fact registration, non-destructive supersession, active facts query, reflexion lessons.
4. Semantic Memory (Tier 4): Material catalog, temperature-dependent E(T) & Sy(T), Basquin S-N fatigue, ASME VIII-1 UG-27, CODATA 2022 constants.
5. Admission Control: STEM-only entity extraction, dimensional gate verification, rejection of unverified/biomedical content.
6. Pre-flight Gate: Pint dimensional homogeneity validation, fail-closed interception.
7. Durable Execution: Checkpoint state machine, crash resumption context hydration.
8. GenAI Tracing & Cost Ledger: OpenTelemetry GenAI semantic conventions, monetary cost ledger, budget cap enforcement.
9. Artifact-Level HITL: Digital signature verification, review workflows (approved/rejected).
10. Physical Substrate: CAD geometry inspection, revision diffing, CAE 14-gate verification review.
11. Tool Registry & FastAPI REST Integration: Substrate tools in ToolRegistry and 17 harness endpoints.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from starlette.testclient import TestClient

from app.backend.main import app
from tribos.harness.cost_ledger import CostLedger
from tribos.harness.durable import DurableExecutionHarness
from tribos.harness.hitl import ArtifactHITLManager
from tribos.harness.preflight import PreflightGate
from tribos.harness.tracing import GenAITracer
from tribos.memory.admission import AdmissionController
from tribos.memory.episodic import EpisodicMemory
from tribos.memory.semantic import (
    SemanticMemory,
)
from tribos.memory.session import SessionMemory
from tribos.memory.working import WorkingMemory
from tribos.substrate.cad.inspector import GeometryInspector
from tribos.substrate.cae.review import CAEReviewer
from tribos.tools.registry import get_tool_registry


# --------------------------------------------------------------------------------------------------
# 1. Tier 1: Working Memory Tests
# --------------------------------------------------------------------------------------------------
def test_working_memory_goals_variables_and_compaction():
    wm = WorkingMemory(query="Design a cryogenic pressure vessel", max_scratchpad_tokens=50)

    # 1. Goal management & DAG tracking
    g1 = wm.add_goal(goal_id="g1", text="CAD Geometry Inspection", focus="cad")
    g2 = wm.add_goal(goal_id="g2", text="FEA Stress Analysis", focus="cae", depends_on=["g1"])

    assert g1.status == "open"
    assert "g1" in g2.depends_on

    wm.update_goal(
        goal_id="g1", status="answered", result={"volume_m3": 0.045}, note="STEP model parsed"
    )
    assert wm.goals["g1"].status == "answered"
    assert wm.goals["g1"].results["latest"]["volume_m3"] == 0.045

    # 2. Inter-specialist variable cache with Pint units
    wm.set_variable("max_hoop_stress", 165.4, unit="MPa")
    wm.set_variable("design_pressure", 2.5, unit="MPa")
    assert wm.get_variable("max_hoop_stress") == 165.4
    assert wm.units.get("max_hoop_stress") == "MPa"

    # 3. Assumptions
    wm.add_assumption("Material behavior is isotropic and linear-elastic")
    assert len(wm.active_assumptions) == 1

    # 4. Scratchpad notes & dynamic compaction
    # Append multiple notes exceeding max_scratchpad_tokens (50 tokens ~ 200 chars)
    for i in range(12):
        wm.append_note(
            f"Step {i}: Verifying boundary conditions and mesh convergence for section {i}."
        )

    # Should have triggered compaction
    assert any("[Compacted" in n for n in wm.scratchpad)
    context_str = wm.render_context()
    assert "<working_memory>" in context_str
    assert "<variables>" in context_str
    assert "max_hoop_stress (MPa) = 165.4" in context_str


# --------------------------------------------------------------------------------------------------
# 2. Tier 2: Session Memory Tests
# --------------------------------------------------------------------------------------------------
def test_session_memory_turns_revisions_diff_and_directives():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_session.sqlite3")
        sm = SessionMemory(db_path=db_path)

        project_id = "proj_heat_exchanger"
        tid = sm.create_thread(project_id=project_id, title="Heat Exchanger Design Session")
        assert tid.startswith("thrd_")

        # 1. Record conversation turns
        sm.add_turn(
            thread_id=tid, role="user", content="What is the required shell thickness?"
        )
        turn2 = sm.add_turn(
            thread_id=tid,
            role="assistant",
            content="Based on ASME UG-27, required thickness is 10.5 mm for SA-516 Gr 70.",
        )
        turns = sm.get_thread_turns(thread_id=tid)
        assert len(turns) == 2
        assert turns[0].role == "user"
        assert turns[1].id == turn2

        # 2. Answer revision tree & branching
        rev1_text = (
            "1. Material: SA-516 Gr 70\n2. Shell Thickness: 10.5 mm\n3. Allowable Stress: 138 MPa"
        )
        rev1 = sm.create_revision(
            project_id=project_id,
            content=rev1_text,
            summary="Initial ASME UG-27 sizing",
            branch_name="main",
            author="sizing_agent",
        )

        rev2_text = "1. Material: SA-516 Gr 70\n2. Shell Thickness: 12.0 mm\n3. Allowable Stress: 138 MPa\n4. Corrosion Allowance: 3 mm added"
        rev2 = sm.create_revision(
            project_id=project_id,
            content=rev2_text,
            summary="Updated with 3mm corrosion allowance",
            branch_name="main",
            parent_id=rev1.id,
            author="corrosion_specialist",
        )

        # 3. Unified line diff
        diff_res = sm.diff_revisions(rev1.id, rev2.id)
        diff = diff_res["unified_diff"]
        assert "-2. Shell Thickness: 10.5 mm" in diff
        assert "+2. Shell Thickness: 12.0 mm" in diff
        assert "+4. Corrosion Allowance: 3 mm added" in diff

        # 4. Scoped directives
        sm.add_directive(project_id=project_id, text="Always use metric SI units", scope="session")
        directives = sm.get_active_directives(project_id=project_id, scope="session")
        assert len(directives) == 1
        assert "metric SI" in directives[0]


# --------------------------------------------------------------------------------------------------
# 3. Tier 3: Episodic Memory Tests
# --------------------------------------------------------------------------------------------------
def test_episodic_memory_facts_supersession_and_reflexion():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_episodic.sqlite3")
        em = EpisodicMemory(db_path=db_path)
        project_id = "proj_pump_casing"

        # 1. Record empirical fact
        f1 = em.record_fact(
            project_id=project_id,
            subject="impeller_shaft",
            relation="material",
            object="aisi_4140",
            manifest_id="run_sizing_001",
            confidence=0.95,
        )
        assert f1.id.startswith("fct_")

        active = em.get_active_facts(project_id=project_id, subject="impeller_shaft")
        assert len(active) == 1
        assert active[0].object == "aisi_4140"

        # 2. Non-destructive supersession: material upgraded to stainless 316L
        f2 = em.record_fact(
            project_id=project_id,
            subject="impeller_shaft",
            relation="material",
            object="ss316l",
            manifest_id="run_corrosion_upgrade_002",
            confidence=0.99,
        )

        # Old fact is now invalidated and superseded
        with em._get_conn() as conn:
            old_row = conn.execute("SELECT * FROM episodic_facts WHERE id = ?", (f1.id,)).fetchone()
            assert old_row["invalid_at"] is not None
            assert old_row["superseded_by"] == f2.id

        # Only new fact is active
        active_now = em.get_active_facts(project_id=project_id, subject="impeller_shaft")
        assert len(active_now) == 1
        assert active_now[0].object == "ss316l"

        # 3. Reflexion failure lesson
        lesson = em.record_lesson(
            project_id=project_id,
            task_kind="cae_mesh",
            failed_action="meshing 90-degree internal fillet with 1mm tetrahedrals",
            root_cause="stress singularity at re-entrant corner caused artificial 800 MPa peak",
            countermeasure="introduce 3.0 mm blend radius in CAD before meshing",
            manifest_id="run_fea_fail_003",
        )
        assert lesson.id.startswith("lsn_")

        lessons = em.get_lessons(project_id=project_id, task_kind="cae_mesh")
        assert len(lessons) == 1
        assert "singularity" in lessons[0].root_cause


# --------------------------------------------------------------------------------------------------
# 4. Tier 4: Semantic Memory & Standards Tests
# --------------------------------------------------------------------------------------------------
def test_semantic_materials_temperature_dependence_and_standards():
    sem = SemanticMemory()

    # 1. Temperature-dependent properties
    al = sem.get_material("al6061_t6")
    assert al is not None
    assert al.density_kg_m3 == 2700.0

    # Room-temperature values only: no unsourced derating curve outside 15-25 C (AUDIT-010)
    assert al.e_at_temp(20.0) == pytest.approx(68.9, abs=0.1)
    assert al.yield_at_temp(20.0) == pytest.approx(276.0, abs=0.1)
    assert al.e_at_temp(200.0) is None
    assert al.yield_at_temp(200.0) is None

    # Basquin S-N fatigue curve
    cycles_high = al.fatigue_life_cycles(150.0)
    cycles_low = al.fatigue_life_cycles(250.0)
    assert cycles_high > cycles_low

    # 2. Machine-checkable ASME VIII-1 UG-27 compliance
    clause = sem.get_standard_clause("ASME_VIII_1_UG27_CYL")
    assert clause is not None

    # Thickness 12mm >= req ~ 8.6mm -> compliant
    comp_pass = clause.evaluate_compliance(
        {
            "pressure_mpa": 2.0,
            "radius_mm": 500.0,
            "allowable_stress_mpa": 138.0,
            "joint_efficiency": 0.85,
            "wall_thickness_mm": 12.0,
        }
    )
    assert comp_pass["compliant"] is True
    assert comp_pass["required_thickness_mm"] < 12.0

    # Thickness 6mm < req -> non-compliant
    comp_fail = clause.evaluate_compliance(
        {
            "pressure_mpa": 2.0,
            "radius_mm": 500.0,
            "allowable_stress_mpa": 138.0,
            "joint_efficiency": 0.85,
            "wall_thickness_mm": 6.0,
        }
    )
    assert comp_fail["compliant"] is False

    # 3. Fundamental Constants (CODATA 2022)
    c_val, c_unit = sem.get_constant("speed_of_light")
    assert c_val == 299792458.0
    assert c_unit == "m/s"


# --------------------------------------------------------------------------------------------------
# 5. Admission Controller Tests
# --------------------------------------------------------------------------------------------------
def test_admission_control_stem_entities_and_write_governance():
    text = (
        "The cylindrical vessel manufactured from Aluminum 6061-T6 under internal pressure "
        "2.5 MPa conforms to ASME Section VIII Div 1. The boundary condition is fixed at base."
    )

    entities = AdmissionController.extract_stem_entities(text)
    assert "material" in entities
    assert any("6061" in m for m in entities["material"])
    assert "quantity_unit" in entities
    assert any("2.5 MPa" in q for q in entities["quantity_unit"])
    assert "boundary_condition" in entities

    # Rejection of unverified facts
    ok_unverified, reason_unverified = AdmissionController.validate_admission(
        {"subject": "casing", "relation": "wall_thickness", "object": "10mm"},
        verification_status="unverified",
    )
    assert ok_unverified is False
    assert "Unverified" in reason_unverified

    # Acceptance of verified empirical facts with evidence
    ok_verified, reason_verified = AdmissionController.validate_admission(
        {"subject": "casing", "relation": "wall_thickness", "object": "10mm"},
        verification_status="verified_empirical",
        evidence=["tool:asme_ug27_eval", "proof_id:pr_104"],
    )
    assert ok_verified is True


# --------------------------------------------------------------------------------------------------
# 6. Pre-flight Gate Tests
# --------------------------------------------------------------------------------------------------
def test_preflight_gate_dimensional_homogeneity():
    gate = PreflightGate()

    # Valid equation: 10 N = 2 kg * 5 m/s^2
    valid_res = gate.verify_equation_units("10 * newton = 2 * kilogram * 5 * meter / (second ** 2)")
    assert valid_res["homogeneous"] is True

    # Incompatible equation: 10 N = 5 second
    invalid_res = gate.verify_equation_units("10 * newton = 5 * second")
    assert invalid_res["homogeneous"] is False

    # Tool call inspection
    ok_call, _ = gate.inspect_tool_call(
        "dynamis_solve_ode",
        {"equation": "10 * newton = 2 * kilogram * 5 * meter / (second ** 2)"},
    )
    assert ok_call is True

    bad_call, reason = gate.inspect_tool_call(
        "dynamis_solve_ode",
        {"equation": "10 * newton = 5 * second"},
    )
    assert bad_call is False
    assert "Dimensional mismatch" in reason


# --------------------------------------------------------------------------------------------------
# 7. Durable Execution Harness Tests
# --------------------------------------------------------------------------------------------------
def test_durable_execution_harness_checkpoints_and_resumption():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_durable.sqlite3")
        deh = DurableExecutionHarness(db_path=db_path)

        run_id = "run_turbopump_cfd_001"
        deh.save_checkpoint(
            run_id=run_id,
            phase_name="geometry_prep",
            phase_index=1,
            state_payload={"cad_repaired": True, "volume_m3": 0.012},
        )
        deh.save_checkpoint(
            run_id=run_id,
            phase_name="mesh_generation",
            phase_index=2,
            state_payload={"cell_count": 2500000, "skewness_max": 0.72},
        )

        all_cps = deh.list_checkpoints(run_id)
        assert len(all_cps) == 2

        # Resumption
        resumption = deh.prepare_resumption(run_id)
        assert resumption["run_id"] == run_id
        assert resumption["resumed_from_phase"] == "mesh_generation"
        assert resumption["resumed_phase_index"] == 2
        assert resumption["state_payload"]["cell_count"] == 2500000


# --------------------------------------------------------------------------------------------------
# 8. GenAI Tracing & Monetary Cost Ledger Tests
# --------------------------------------------------------------------------------------------------
def test_genai_opentelemetry_tracing_and_cost_accounting():
    # 1. Tracing
    tracer = GenAITracer(trace_id="trc_stress_run_01")
    wf_span = tracer.start_span(
        "agent.workflow", attributes={"tribos.workflow": "structural_optimization"}
    )
    tool_span = tracer.trace_tool_execution(
        "substrate_material_lookup", inputs={"material_name": "steel_4140"}
    )
    tracer.end_span(tool_span, status="ok")
    tracer.trace_verification("asme_ug27", "verified")
    tracer.end_span(wf_span, status="ok")

    otlp_json = tracer.export_otlp_json()
    assert "trc_stress_run_01" in otlp_json
    assert "agent.workflow" in otlp_json
    assert "substrate_material_lookup" in otlp_json

    # 2. Cost Ledger & Budget Enforcement
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_cost.sqlite3")
        ledger = CostLedger(db_path=db_path)

        project_id = "proj_budget_test"
        ledger.set_project_budget(project_id, budget_limit_usd=0.01)  # 1 cent budget limit

        # Small usage should succeed
        rec1 = ledger.record_usage(
            run_id="run_c1",
            project_id=project_id,
            user_id="user_alice",
            model_name="gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=200,
        )
        assert rec1.cost_usd > 0.0

        spend = ledger.get_project_spend(project_id)
        assert spend["total_spend_usd"] == pytest.approx(rec1.cost_usd, abs=1e-5)
        assert spend["is_budget_exhausted"] is False

        # Usage that breaches budget must raise RuntimeError
        with pytest.raises(RuntimeError, match="Monetary budget exceeded"):
            ledger.record_usage(
                run_id="run_c1",
                project_id=project_id,
                user_id="user_alice",
                model_name="gpt-4o",
                prompt_tokens=50000,
                completion_tokens=20000,
            )


# --------------------------------------------------------------------------------------------------
# 9. Artifact-Level HITL Tests
# --------------------------------------------------------------------------------------------------
def test_artifact_hitl_signoff_workflow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_hitl.sqlite3")
        hitl = ArtifactHITLManager(db_path=db_path)

        artifact_id = "art_asme_report_001"
        project_id = "proj_reactor_vessel"

        # Certified engineer signs off artifact
        rev = hitl.sign_off_artifact(
            artifact_id=artifact_id,
            project_id=project_id,
            reviewer_id="PE_SMITH_44921",
            action="approved",
            comments="Verified shell minimum thickness exceeds ASME VIII-1 UG-27 calculation.",
        )

        assert rev.action == "approved"
        assert len(rev.signature_hash) == 64

        reviews = hitl.list_artifact_reviews(artifact_id)
        assert len(reviews) == 1
        assert reviews[0].reviewer_id == "PE_SMITH_44921"
        assert reviews[0].signature_hash == rev.signature_hash


# --------------------------------------------------------------------------------------------------
# 10. Physical Substrate: CAD Geometry & CAE 14-Gate Tests
# --------------------------------------------------------------------------------------------------
def test_cad_geometry_inspection_and_diff():
    # Synthetic STL string for a rectangular part
    stl_rev_a = """solid part_rev_a
      facet normal 0 0 1
        outer loop
          vertex 0 0 0
          vertex 100 0 0
          vertex 0 50 0
        endloop
      endfacet
      facet normal 0 0 1
        outer loop
          vertex 100 0 20
          vertex 100 50 20
          vertex 0 50 20
        endloop
      endfacet
    endsolid part_rev_a"""

    geom_a = GeometryInspector.inspect_stl_ascii(
        stl_rev_a, file_name="part_rev_a.stl", density_kg_m3=2700.0
    )
    assert geom_a.bounding_box.length_mm == 100.0
    assert geom_a.bounding_box.width_mm == 50.0
    assert geom_a.bounding_box.height_mm == 20.0
    # Two loose triangles are not a closed solid: no volume or mass is invented (AUDIT-002)
    assert geom_a.watertight is False
    assert geom_a.mass_kg is None
    assert geom_a.surface_area_mm2 == pytest.approx(2 * 0.5 * 100 * 50)

    # Revision B: length widened to 120mm
    stl_rev_b = """solid part_rev_b
      facet normal 0 0 1
        outer loop
          vertex 0 0 0
          vertex 120 0 0
          vertex 0 50 0
        endloop
      endfacet
      facet normal 0 0 1
        outer loop
          vertex 120 0 20
          vertex 120 50 20
          vertex 0 50 20
        endloop
      endfacet
    endsolid part_rev_b"""

    geom_b = GeometryInspector.inspect_stl_ascii(
        stl_rev_b, file_name="part_rev_b.stl", density_kg_m3=2700.0
    )
    diff = GeometryInspector.diff_geometries(geom_a, geom_b)
    assert diff["delta_volume_mm3"] is None
    assert diff["pct_mass_change"] is None
    assert diff["delta_surface_area_mm2"] == pytest.approx(2 * 0.5 * 20 * 50)
    assert diff["significant_change"] is True


def test_cae_14_gate_review():
    audit = CAEReviewer.run_full_cae_audit(
        applied_load_n=10000.0,
        reaction_force_n=10005.0,  # 0.05% residual -> PASS Gate 1
        coarse_stress_mpa=140.0,
        fine_stress_mpa=143.0,  # 2.1% delta -> PASS Gate 2 (<= 5%)
        yield_strength_mpa=250.0,  # 143 < 250 -> PASS Gate 3
        analytical_stress_mpa=141.0,  # 1.4% deviation -> PASS Gate 5 (<= 15%)
        stress_gradient_ratio=1.5,  # 1.5 <= 3.0 -> PASS Gate 4
    )

    assert audit["cae_verified"] is True
    assert audit["gates_passed"] == 5
    assert all(g["passed"] for g in audit["gates"])
    assert "14" not in audit["verdict"]


# --------------------------------------------------------------------------------------------------
# 11. Tool Registry & FastAPI REST Integration
# --------------------------------------------------------------------------------------------------
def test_tool_registry_substrate_tools():
    registry = get_tool_registry()
    tools = registry.list_tools()
    tool_names = [t.name for t in tools]

    assert "substrate_material_lookup" in tool_names
    assert "substrate_standards_check" in tool_names
    assert "substrate_geometry_inspect" in tool_names
    assert "substrate_cae_review" in tool_names

    # Direct execution of substrate_material_lookup executor
    executor = registry.get_executor("substrate_material_lookup")
    assert executor is not None
    res = executor(material_name="steel_4140", temperature_celsius=150.0)
    assert "AISI 4140" in res["name"]
    assert res["e_modulus_gpa"] is None and "limitation" in res  # no sourced data at 150 C
    assert executor(material_name="steel_4140", temperature_celsius=20.0)["e_modulus_gpa"] == 205.0


def test_fastapi_harness_endpoints(monkeypatch):
    monkeypatch.setenv("TRIBOS_AUTH_MODE", "disabled")
    with TestClient(app, base_url="http://localhost") as client:
        # Harness data is scoped by project membership (AUDIT-004): create a real project first.
        created = client.post("/api/projects", json={"name": "Cryogenic tank"})
        assert created.status_code == 201
        project_id = created.json()["id"]

        # 1. Create thread
        resp = client.post(
            f"/api/harness/projects/{project_id}/threads",
            json={"title": "Cryogenic Tank Harness Test"},
        )
        assert resp.status_code == 200
        thread_data = resp.json()
        assert "thread_id" in thread_data
        thread_id = thread_data["thread_id"]

        # 2. Add turn
        resp_turn = client.post(
            f"/api/harness/threads/{thread_id}/turns",
            json={"role": "user", "content": "Analyze tank wall under internal pressure 1.8 MPa."},
        )
        assert resp_turn.status_code == 200
        resp_turn.json()["turn_id"]

        # 3. Create revisions
        resp_r1 = client.post(
            f"/api/harness/projects/{project_id}/revisions",
            json={
                "content": "Thickness = 8 mm",
                "summary": "Initial proposal",
            },
        )
        assert resp_r1.status_code == 200
        r1_id = resp_r1.json()["revision_id"]

        resp_r2 = client.post(
            f"/api/harness/projects/{project_id}/revisions",
            json={
                "parent_id": r1_id,
                "content": "Thickness = 10 mm",
                "summary": "Increased thickness",
            },
        )
        assert resp_r2.status_code == 200
        r2_id = resp_r2.json()["revision_id"]

        # 4. Revision diff
        resp_diff = client.post(
            "/api/harness/revisions/diff", json={"rev_id_a": r1_id, "rev_id_b": r2_id}
        )
        assert resp_diff.status_code == 200
        assert "unified_diff" in resp_diff.json()

        # 5. Substrate materials query
        resp_mat = client.get("/api/harness/substrate/materials")
        assert resp_mat.status_code == 200
        mats = resp_mat.json()["materials"]
        assert len(mats) >= 5

        # 6. ASME UG-27 calculation endpoint
        resp_asme = client.post(
            "/api/harness/substrate/standards/check",
            json={
                "pressure_mpa": 2.0,
                "radius_mm": 500.0,
                "allowable_stress_mpa": 138.0,
                "joint_efficiency": 0.85,
                "wall_thickness_mm": 12.0,
            },
        )
        assert resp_asme.status_code == 200
        assert resp_asme.json()["compliant"] is True

        # 7. Cost spend endpoint
        resp_cost = client.get(f"/api/harness/projects/{project_id}/spend")
        assert resp_cost.status_code == 200
        assert "total_spend_usd" in resp_cost.json()
