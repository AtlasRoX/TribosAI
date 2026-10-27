"""Agentic Engineering Harness & Cognitive Memory API Router.

Exposes REST endpoints for:
- Server-side conversation sessions (F-17)
- Answer revision tree & diffing (F-16)
- Durable execution run resumption (F-18)
- Artifact-level HITL sign-off & annotation (F-19)
- OpenTelemetry GenAI tracing & monetary cost tracking (F-14 / F-15)
- Engineering Substrate: Materials lookup, ASME compliance, CAE 14-gate review
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.backend.auth import get_current_user
from tribos.harness.cost_ledger import CostLedger
from tribos.harness.durable import DurableExecutionHarness
from tribos.harness.hitl import ArtifactHITLManager
from tribos.memory import get_memory_engine
from tribos.substrate import (
    CAEReviewer,
    check_asme_compliance,
    get_material,
    list_materials,
)

router = APIRouter(prefix="/api/harness", tags=["harness"])

# Shared engine instances
_mem_engine = get_memory_engine()
_durable_harness = DurableExecutionHarness()
_cost_ledger = CostLedger()
_hitl_manager = ArtifactHITLManager()


# Request / Response Schemas ------------------------------------------------------------------
class ThreadCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    metadata: dict[str, Any] | None = None


class TurnCreateRequest(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system|tool)$")
    content: str
    metadata: dict[str, Any] | None = None


class AnswerRevisionCreateRequest(BaseModel):
    content: str
    summary: str = ""
    branch_name: str = "main"
    parent_id: str | None = None
    author: str = "agent"
    metadata: dict[str, Any] | None = None


class AnswerDiffRequest(BaseModel):
    rev_id_a: str
    rev_id_b: str


class ArtifactSignOffRequest(BaseModel):
    project_id: str
    action: str = Field(..., pattern="^(approved|rejected|rework_requested|annotated)$")
    comments: str = ""
    metadata: dict[str, Any] | None = None


class MaterialLookupRequest(BaseModel):
    material_name: str
    temperature_celsius: float = 20.0


class ASMEComplianceRequest(BaseModel):
    clause_id: str = "ASME_VIII_1_UG27_CYL"
    pressure_mpa: float
    radius_mm: float
    allowable_stress_mpa: float
    wall_thickness_mm: float
    joint_efficiency: float = 1.0


class CAEReviewRequest(BaseModel):
    applied_load_n: float
    reaction_force_n: float
    coarse_stress_mpa: float
    fine_stress_mpa: float
    yield_strength_mpa: float
    analytical_stress_mpa: float
    stress_gradient_ratio: float = 1.8


# Sessions & Conversations (F-17) -------------------------------------------------------------
@router.post("/projects/{project_id}/threads")
async def create_thread(
    project_id: str,
    req: ThreadCreateRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    tid = _mem_engine.create_thread(project_id, req.title, req.metadata)
    return {"thread_id": tid, "project_id": project_id, "title": req.title}


@router.get("/projects/{project_id}/threads")
async def list_threads(
    project_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    threads = _mem_engine.list_project_threads(project_id)
    return {"project_id": project_id, "threads": threads}


@router.post("/threads/{thread_id}/turns")
async def add_thread_turn(
    thread_id: str,
    req: TurnCreateRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    turn_id = _mem_engine.add_turn(thread_id, req.role, req.content, req.metadata)
    return {"turn_id": turn_id, "thread_id": thread_id}


@router.get("/threads/{thread_id}/turns")
async def get_thread_turns(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    turns = _mem_engine.get_thread_turns(thread_id, limit=limit)
    return {
        "thread_id": thread_id,
        "turns": [
            {
                "id": t.id,
                "role": t.role,
                "content": t.content,
                "created_at": t.created_at,
                "metadata": t.metadata,
            }
            for t in turns
        ],
    }


# Answer Revision Tree & Diff (F-16) ----------------------------------------------------------
@router.post("/projects/{project_id}/revisions")
async def create_revision(
    project_id: str,
    req: AnswerRevisionCreateRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    rev = _mem_engine.create_answer_revision(
        project_id=project_id,
        content=req.content,
        summary=req.summary,
        branch_name=req.branch_name,
        parent_id=req.parent_id,
        author=req.author,
        metadata=req.metadata,
    )
    return {"revision_id": rev.id, "version_number": rev.version_number, "branch": rev.branch_name}


@router.get("/projects/{project_id}/revisions")
async def list_revisions(
    project_id: str,
    branch: str | None = None,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    revs = _mem_engine.list_answer_revisions(project_id, branch_name=branch)
    return {
        "project_id": project_id,
        "revisions": [
            {
                "id": r.id,
                "version_number": r.version_number,
                "branch_name": r.branch_name,
                "summary": r.summary,
                "parent_id": r.parent_id,
                "created_at": r.created_at,
                "author": r.author,
                "status": r.status,
            }
            for r in revs
        ],
    }


@router.post("/revisions/diff")
async def diff_revisions(
    req: AnswerDiffRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return _mem_engine.diff_answer_revisions(req.rev_id_a, req.rev_id_b)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Durable Execution & Run Resumption (F-18) ----------------------------------------------------
@router.get("/runs/{run_id}/checkpoints")
async def list_checkpoints(
    run_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    chks = _durable_harness.list_checkpoints(run_id)
    return {
        "run_id": run_id,
        "checkpoints": [
            {
                "id": c.id,
                "phase_name": c.phase_name,
                "phase_index": c.phase_index,
                "status": c.status,
                "created_at": c.created_at,
            }
            for c in chks
        ],
    }


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        res = _durable_harness.prepare_resumption(run_id)
        return {"status": "resumed", **res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Artifact-Level HITL Sign-Off (F-19) ---------------------------------------------------------
@router.post("/artifacts/{artifact_id}/signoff")
async def sign_off_artifact(
    artifact_id: str,
    req: ArtifactSignOffRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    reviewer_id = str(user or "engineer")
    review = _hitl_manager.sign_off_artifact(
        artifact_id=artifact_id,
        project_id=req.project_id,
        reviewer_id=reviewer_id,
        action=req.action,
        comments=req.comments,
        metadata=req.metadata,
    )
    return {
        "review_id": review.id,
        "artifact_id": review.artifact_id,
        "action": review.action,
        "signature_hash": review.signature_hash,
    }


@router.get("/artifacts/{artifact_id}/reviews")
async def list_artifact_reviews(
    artifact_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    reviews = _hitl_manager.list_artifact_reviews(artifact_id)
    return {
        "artifact_id": artifact_id,
        "reviews": [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "action": r.action,
                "comments": r.comments,
                "created_at": r.created_at,
                "signature_hash": r.signature_hash,
            }
            for r in reviews
        ],
    }


# Monetary Cost & Tracing (F-14 / F-15) -------------------------------------------------------
@router.get("/runs/{run_id}/cost")
async def get_run_cost(
    run_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    return _cost_ledger.get_run_cost(run_id)


@router.get("/projects/{project_id}/spend")
async def get_project_spend(
    project_id: str,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    return _cost_ledger.get_project_spend(project_id)


# Substrate: Materials, Standards, CAD & CAE --------------------------------------------------
@router.get("/substrate/materials")
async def get_materials_catalog(
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    return {"materials": list_materials()}


@router.post("/substrate/materials/lookup")
async def lookup_material(
    req: MaterialLookupRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    mat = get_material(req.material_name)
    if not mat:
        raise HTTPException(status_code=404, detail=f"Material '{req.material_name}' not found")
    return {
        "name": mat.name,
        "category": mat.category,
        "density_kg_m3": mat.density_kg_m3,
        "poisson_ratio": mat.poisson_ratio,
        "yield_strength_mpa": mat.yield_at_temp(req.temperature_celsius),
        "ultimate_strength_mpa": mat.ultimate_strength_mpa,
        "e_modulus_gpa": mat.e_at_temp(req.temperature_celsius),
        "thermal_conductivity_w_mk": mat.thermal_conductivity_w_mk,
        "temperature_celsius": req.temperature_celsius,
    }


@router.post("/substrate/standards/check")
async def evaluate_standard(
    req: ASMEComplianceRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    params = {
        "pressure_mpa": req.pressure_mpa,
        "radius_mm": req.radius_mm,
        "allowable_stress_mpa": req.allowable_stress_mpa,
        "wall_thickness_mm": req.wall_thickness_mm,
        "joint_efficiency": req.joint_efficiency,
    }
    return check_asme_compliance(params, clause_id=req.clause_id)


@router.post("/substrate/cae/review")
async def review_cae_simulation(
    req: CAEReviewRequest,
    user: str = Depends(get_current_user),
) -> dict[str, Any]:
    return CAEReviewer.run_full_cae_audit(
        applied_load_n=req.applied_load_n,
        reaction_force_n=req.reaction_force_n,
        coarse_stress_mpa=req.coarse_stress_mpa,
        fine_stress_mpa=req.fine_stress_mpa,
        yield_strength_mpa=req.yield_strength_mpa,
        analytical_stress_mpa=req.analytical_stress_mpa,
        stress_gradient_ratio=req.stress_gradient_ratio,
    )
