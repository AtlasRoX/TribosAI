"""
Long-running research projects (tribos.agentic.campaign): a goal worked through review -> hypotheses ->
experiments -> analysis -> report, each stage one background job.

Routes (scoped to the authenticated user; another user's project is a 404):
- POST /api/campaigns {goal, model?, project_id?, effort_level?, stages?, enable_web_search?} -> the campaign
- GET /api/campaigns, GET /api/campaigns/{id}
- GET /api/campaigns/{id}/report: the report and every stage record as Markdown (a download)
- POST /api/campaigns/{id}/cancel, POST /api/campaigns/{id}/resume, DELETE /api/campaigns/{id}
- POST /api/campaigns/{id}/continue {instruction, stages?}: another round on a project that stopped or finished
- GET /api/campaigns/{id}/thesis?format=pdf|docx|md|html|bundle: the research thesis (loop-mode projects)
- GET /api/campaigns/{id}/files/{name}: a figure or chart the project produced
- POST /api/campaigns/estimate {goal}: a rough duration before the project starts

Progress of the running stage streams from its job: GET /api/jobs/{stage.job_id}/events.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.backend.auth import get_current_user
from tribos.agentic.campaign import (
    CAMPAIGN_ID_RE,
    STAGE_KEYS,
    get_campaign_manager,
    public_campaign,
    report_markdown,
)
from tribos.agentic.jobs import JobError

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

CampaignIdPath = Path(..., min_length=4, max_length=64)


class CampaignCreate(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4000)
    model: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)
    effort_level: str = Field(default="high", pattern="^(low|medium|high)$")
    stages: list[str] | None = Field(default=None, max_length=len(STAGE_KEYS))
    enable_web_search: bool = True
    # "loop": the adaptive research loop (rounds until a conclusion, then a thesis); "stages": the fixed five stages.
    # Default: "loop", unless `stages` is given (a client choosing stages asks for the classic pipeline).
    mode: str | None = Field(default=None, pattern="^(loop|stages)$")


class CampaignEstimate(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4000)


class CampaignContinue(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=4000)
    stages: list[str] | None = Field(default=None, max_length=len(STAGE_KEYS))


def _check_id(campaign_id: str) -> None:
    if not CAMPAIGN_ID_RE.match(campaign_id or ""):
        raise HTTPException(status_code=404, detail="Research project not found")


def _found(campaign: dict[str, Any] | None) -> dict[str, Any]:
    if campaign is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return public_campaign(campaign)


@router.post("", status_code=201)
async def create_campaign(req: CampaignCreate, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    try:
        campaign = await get_campaign_manager().submit(
            user_id, req.goal, model=req.model, project_id=req.project_id, effort_level=req.effort_level,
            stages=req.stages, web_search=req.enable_web_search,
            mode=req.mode or ("stages" if req.stages else "loop"))
    except JobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return public_campaign(campaign)


@router.post("/estimate")
async def estimate_campaign(req: CampaignEstimate, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """A rough duration for a goal, before the plan exists (refined once the project has its plan)."""
    from tribos.agentic.research import rough_estimate

    del user_id
    return rough_estimate(req.goal)


@router.get("")
async def list_campaigns(limit: int = Query(default=50, ge=1, le=200),
                         user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    items = get_campaign_manager().list(user_id, limit)
    return {"campaigns": [public_campaign(c, full=False) for c in items], "stages": list(STAGE_KEYS)}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str = CampaignIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_id(campaign_id)
    return _found(get_campaign_manager().get(campaign_id, user_id))


@router.get("/{campaign_id}/report")
async def campaign_report(campaign_id: str = CampaignIdPath, user_id: str = Depends(get_current_user)) -> Response:
    _check_id(campaign_id)
    campaign = get_campaign_manager().get(campaign_id, user_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return Response(report_markdown(campaign), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{campaign_id}.md"'})


_FORMATS = {
    "pdf": ("application/pdf", "pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
    "bundle": ("application/zip", "zip"),
}
_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_KATEX_CDN = "https://cdn.jsdelivr.net/npm/katex@0.19.1/dist"


def _owned(campaign_id: str, user_id: str) -> dict[str, Any]:
    _check_id(campaign_id)
    campaign = get_campaign_manager().get(campaign_id, user_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return campaign


def _files_dir(campaign_id: str) -> str:
    return os.path.join(get_campaign_manager().store.storage_dir, f"{campaign_id}_files")


def _slug(title: str, fallback: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]+", "", title or "").strip().replace(" ", "_")[:60] or fallback


@router.get("/{campaign_id}/thesis")
async def campaign_thesis(campaign_id: str = CampaignIdPath, format: str = Query(default="pdf", pattern="^(pdf|docx|md|html|bundle)$"),
                          user_id: str = Depends(get_current_user)) -> Response:
    """The thesis of a finished (or stopped) research-loop project in the requested format."""
    from tribos.export import thesis as thesis_export

    campaign = _owned(campaign_id, user_id)
    thesis = campaign.get("thesis") or {}
    if campaign.get("mode") != "loop" or thesis.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="This project has no thesis yet")
    files = _files_dir(campaign_id)
    mime, ext = _FORMATS[format]
    headers = {"Content-Disposition": f'attachment; filename="{_slug(campaign.get("title") or "", campaign_id)}.{ext}"'}
    if format == "md":
        return Response(str(thesis.get("markdown") or ""), media_type=mime, headers=headers)
    if format == "html":
        html_text = await asyncio.to_thread(thesis_export.thesis_html, campaign, files, katex_href=_KATEX_CDN)
        return Response(html_text, media_type=mime, headers=headers)
    if format == "docx":
        return Response(await asyncio.to_thread(thesis_export.thesis_docx, campaign, files), media_type=mime, headers=headers)
    if format == "bundle":
        return Response(await asyncio.to_thread(thesis_export.thesis_bundle, campaign, files), media_type=mime, headers=headers)
    pdf, engine = await asyncio.to_thread(thesis_export.thesis_pdf, campaign, files)
    headers["X-Tribos-Pdf-Engine"] = engine
    return Response(pdf, media_type=mime, headers=headers)


@router.get("/{campaign_id}/files/{name}")
async def campaign_file(campaign_id: str = CampaignIdPath, name: str = Path(..., min_length=1, max_length=120),
                        user_id: str = Depends(get_current_user)) -> Response:
    """A figure or chart a project produced (only plain file names inside the project's own folder)."""
    _owned(campaign_id, user_id)
    if not _FILE_RE.match(name) or not name.endswith((".png", ".svg")):
        raise HTTPException(status_code=404, detail="File not found")
    base = os.path.realpath(_files_dir(campaign_id))
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="image/svg+xml" if name.endswith(".svg") else "image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str = CampaignIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_id(campaign_id)
    return _found(await get_campaign_manager().cancel(campaign_id, user_id))


@router.post("/{campaign_id}/resume")
async def resume_campaign(campaign_id: str = CampaignIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_id(campaign_id)
    try:
        return _found(await get_campaign_manager().resume(campaign_id, user_id))
    except JobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{campaign_id}/continue")
async def continue_campaign(req: CampaignContinue, campaign_id: str = CampaignIdPath,
                            user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    """Another round (default experiments -> analysis -> report) with a follow-up instruction."""
    _check_id(campaign_id)
    try:
        return _found(await get_campaign_manager().continue_(campaign_id, user_id, req.instruction, req.stages))
    except JobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str = CampaignIdPath, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    _check_id(campaign_id)
    if not await get_campaign_manager().delete(campaign_id, user_id):
        raise HTTPException(status_code=404, detail="Research project not found")
    return {"deleted": True, "campaign_id": campaign_id}
