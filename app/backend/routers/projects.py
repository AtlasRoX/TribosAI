"""
Research projects shared with members, with reviewed memory, files and an activity log (T10).

A project groups threads; its memory is a bi-temporal fact graph (Zep, arXiv:2501.13956) written by the
project-memory phase from verified tool results (Mem0-style ADD/UPDATE/INVALIDATE/NOOP, arXiv:2504.19413) and
recalled with Personalized PageRank (HippoRAG, arXiv:2405.14831) plus recency x importance x relevance
(Generative Agents, arXiv:2304.03442). See tribos/utils/memory/project_store.py.

Every route needs a member: a non-member gets 404 (the project's existence is never revealed), a member whose role is
too low gets 403. Viewers read; editors also write settings, files and memory; the owner also manages members and
deletes the project.

- POST "" {name, description?, instructions?, icon?, color?}, GET "" -> {projects}
- GET / PATCH / DELETE /{id}
- GET /{id}/members, POST /{id}/members {user_id, role}, PATCH / DELETE /{id}/members/{user_id}
- GET /{id}/files, POST /{id}/files {dataset_id}, DELETE /{id}/files/{dataset_id}
- GET /{id}/memory?review_status=&query=&include_invalid=&limit=, POST /{id}/memory {subject, relation, object, ...}
- PATCH / DELETE /{id}/memory/{fact_id}, POST /{id}/memory/{fact_id}/review {decision, note?}
- GET /{id}/memory/{fact_id}/history -> {versions}, oldest first
- GET /{id}/activity?limit=50 -> {events}
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.backend.auth import get_current_user
from tribos.utils.memory.project_store import (
    FACT_ID_RE,
    PROJECT_ID_RE,
    ProjectAccessError,
    ProjectStoreError,
    get_project_store,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])

ProjectIdPath = Path(..., min_length=4, max_length=64)
FactIdPath = Path(..., min_length=4, max_length=64)
MemberPath = Path(..., min_length=1, max_length=128)
DatasetPath = Path(..., pattern=r"^ds_[0-9a-f]{12}$")


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=8000)
    icon: str = Field(default="", max_length=16)
    color: str = Field(default="", max_length=32)


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=8000)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, max_length=128)
    role: Literal["editor", "viewer"]


class MemberPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["editor", "viewer"]


class FileAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., pattern=r"^ds_[0-9a-f]{12}$")


class FactAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(..., min_length=1, max_length=500)
    relation: str = Field(..., min_length=1, max_length=64)
    object: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    note: str = Field(default="", max_length=300)


class FactReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=300)


class FactPatch(BaseModel):
    # Unknown fields are a client bug (e.g. {"valid": false} instead of {"invalidate": true}, BRK-8): refuse them with
    # 422 instead of answering 200 with nothing changed.
    model_config = ConfigDict(extra="forbid")

    invalidate: bool = Field(default=False, description="Mark the fact no longer valid (kept in the history)")
    reason: str = Field(default="", max_length=300)
    object: str | None = Field(default=None, min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=10)


def _check_project(project_id: str) -> None:
    if not PROJECT_ID_RE.match(project_id or ""):
        raise HTTPException(status_code=404, detail="Project not found")


def _check_fact(fact_id: str) -> None:
    if not FACT_ID_RE.match(fact_id or ""):
        raise HTTPException(status_code=404, detail="Fact not found")


async def _call(fn: Callable[..., Any], *args: Any, conflict: int = 422, **kwargs: Any) -> Any:
    """Run a store call in a thread; access errors keep their 403/404, other store errors become `conflict`."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ProjectAccessError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except ProjectStoreError as exc:
        raise HTTPException(status_code=conflict, detail=str(exc)) from exc


def _found(value: Any, what: str = "Project") -> Any:
    if value is None or value is False:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return value


# -- Projects -----------------------------------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_project(req: ProjectCreate, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return await _call(get_project_store().create_project, user_id, req.name, req.description, req.instructions,
                       req.icon, req.color)


@router.get("")
async def list_projects(limit: int = Query(default=100, ge=1, le=500), user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    projects = await asyncio.to_thread(get_project_store().list_projects, user_id, limit)
    return {"projects": projects, "count": len(projects)}


@router.get("/{project_id}")
async def get_project(project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return _found(await asyncio.to_thread(get_project_store().get_project, project_id, user_id))


@router.patch("/{project_id}")
async def patch_project(req: ProjectPatch, project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return _found(await _call(get_project_store().update_project, project_id, user_id, req.name, req.description,
                              req.instructions, req.icon, req.color))


@router.delete("/{project_id}")
async def delete_project(project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _found(await _call(get_project_store().delete_project, project_id, user_id))
    return {"success": True, "project_id": project_id}


# -- Members ------------------------------------------------------------------------------------------------------


@router.get("/{project_id}/members")
async def list_members(project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return {"members": await _call(get_project_store().list_members, project_id, user_id)}


@router.post("/{project_id}/members", status_code=201)
async def add_member(req: MemberAdd, project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return await _call(get_project_store().add_member, project_id, user_id, req.user_id, req.role, conflict=409)


@router.patch("/{project_id}/members/{member_id}")
async def patch_member(req: MemberPatch, project_id: str = ProjectIdPath, member_id: str = MemberPath,
                       user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return await _call(get_project_store().set_member_role, project_id, user_id, member_id, req.role, conflict=409)


@router.delete("/{project_id}/members/{member_id}")
async def remove_member(project_id: str = ProjectIdPath, member_id: str = MemberPath,
                        user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    await _call(get_project_store().remove_member, project_id, user_id, member_id, conflict=409)
    return {"success": True, "user_id": member_id}


# -- Files --------------------------------------------------------------------------------------------------------


@router.get("/{project_id}/files")
async def list_files(project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return {"files": await _call(get_project_store().list_files, project_id, user_id)}


@router.post("/{project_id}/files", status_code=201)
async def add_file(req: FileAdd, project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """Share one of the caller's own datasets with the project."""
    _check_project(project_id)
    store = get_project_store()
    if await asyncio.to_thread(store.role, project_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    from tribos.datasets.store import DatasetStoreError, get_dataset_store

    try:
        record = await asyncio.to_thread(get_dataset_store().get, user_id, req.dataset_id)
    except DatasetStoreError as exc:
        raise HTTPException(status_code=404, detail="Dataset not found among your uploads") from exc
    return await _call(store.add_file, project_id, user_id, record.id, record.display_name, record.kind.value,
                       record.size_bytes)


@router.delete("/{project_id}/files/{dataset_id}")
async def remove_file(project_id: str = ProjectIdPath, dataset_id: str = DatasetPath,
                      user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _found(await _call(get_project_store().remove_file, project_id, user_id, dataset_id), "File")
    return {"success": True, "dataset_id": dataset_id}


# -- Memory -------------------------------------------------------------------------------------------------------


@router.get("/{project_id}/memory")
async def project_memory(
    project_id: str = ProjectIdPath,
    query: str = Query(default="", max_length=2000),
    include_invalid: bool = Query(default=False),
    review_status: Literal["pending", "approved", "rejected"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Facts of a project: ranked for `query` (the recall the agent would get), else the newest first."""
    _check_project(project_id)
    store = get_project_store()
    if not await asyncio.to_thread(store.is_member, project_id, user_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if query.strip() and not review_status:
        facts = await asyncio.to_thread(store.recall, project_id, user_id, query, (), limit, False)
        mode = "ranked"
    else:
        facts = await asyncio.to_thread(store.list_facts, project_id, user_id, include_invalid, limit, review_status)
        mode = "recent"
    return {"project_id": project_id, "mode": mode, "facts": facts, "count": len(facts)}


@router.post("/{project_id}/memory", status_code=201)
async def add_fact(req: FactAdd, project_id: str = ProjectIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return await _call(get_project_store().add_fact, project_id, user_id, req.subject, req.relation, req.object,
                       req.confidence, req.note, conflict=409)


@router.post("/{project_id}/memory/{fact_id}/review")
async def review_fact(req: FactReview, project_id: str = ProjectIdPath, fact_id: str = FactIdPath,
                      user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _check_fact(fact_id)
    return _found(await _call(get_project_store().review_fact, project_id, fact_id, user_id, req.decision, req.note,
                              conflict=409), "Fact")


@router.get("/{project_id}/memory/{fact_id}/history")
async def fact_history(project_id: str = ProjectIdPath, fact_id: str = FactIdPath,
                       user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _check_fact(fact_id)
    return {"versions": await _call(get_project_store().fact_history, project_id, fact_id, user_id)}


@router.patch("/{project_id}/memory/{fact_id}")
async def patch_fact(req: FactPatch, project_id: str = ProjectIdPath, fact_id: str = FactIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _check_fact(fact_id)
    store = get_project_store()
    if req.invalidate:
        fact = await _call(store.invalidate_fact, project_id, fact_id, user_id,
                           req.reason or "invalidated by the researcher", conflict=409)
    else:
        fact = await _call(
            lambda: store.edit_fact(project_id, fact_id, user_id, object=req.object, value=req.value,
                                    confidence=req.confidence, verified=req.verified, tags=req.tags),
            conflict=409,
        )
    return _found(fact, "Fact")


@router.delete("/{project_id}/memory/{fact_id}")
async def delete_fact(project_id: str = ProjectIdPath, fact_id: str = FactIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    _check_fact(fact_id)
    _found(await _call(get_project_store().delete_fact, project_id, fact_id, user_id), "Fact")
    return {"success": True, "fact_id": fact_id}


# -- Activity -----------------------------------------------------------------------------------------------------


@router.get("/{project_id}/activity")
async def activity(project_id: str = ProjectIdPath, limit: int = Query(default=50, ge=1, le=500),
                   user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_project(project_id)
    return {"events": await _call(get_project_store().list_activity, project_id, user_id, limit)}
