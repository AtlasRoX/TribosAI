"""
Agent2Agent (A2A) protocol v1.0.0 endpoint (feature 17), backed by background jobs (feature 13).

Spec: https://a2a-protocol.org/latest/specification/
- `GET /.well-known/agent-card.json`: the Agent Card (name, description, url, version, capabilities,
  default input/output modes, skills, bearer security scheme). Public, like any discovery document.
- `POST /a2a`: JSON-RPC 2.0 binding with the v1.0 PascalCase methods `SendMessage`, `GetTask`, `ListTasks`
  and `CancelTask`; the pre-1.0 names `message/send`, `tasks/get`, `tasks/list` and `tasks/cancel` are aliases.

A message becomes a job (its text parts are the question; `contextId` is the thread). A Task is the job seen
through A2A: id = job id, contextId = thread id, status.state in submitted | working | input-required |
completed | failed | canceled, and the answer as a text artifact once completed. Runs are non-interactive
(plan approvals are automatic), so `input-required` only appears while a REST client watching the job's
events holds an approval open. `configuration.blocking: true` waits for the result (bounded by
`TRIBOS_A2A_BLOCKING_TIMEOUT_S`, default 300 s). Every method is scoped to the authenticated user; another
user's task id is TaskNotFound (-32001). Streaming and push notifications are not offered.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.backend.auth import get_current_user
from app.backend.routers.mcp import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    RpcError,
    _server_info,
    dispatch_rpc,
    parse_body,
)
from tribos.agentic import config as agent_config
from tribos.agentic.jobs import JOB_ID_RE, JobError, get_job_manager
from tribos.config.settings import get_str

logger = logging.getLogger("tribos.backend.a2a")

router = APIRouter(tags=["a2a"])

A2A_VERSION = "1.0.0"
TASK_NOT_FOUND, TASK_NOT_CANCELABLE = -32001, -32002

_STATE = {
    "queued": "submitted",
    "running": "working",
    "waiting_approval": "input-required",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "canceled",
    "interrupted": "failed",
}

_SKILLS: list[dict[str, Any]] = [
    {
        "id": "stem-research",
        "name": "Engineering, Mathematics and Physics Research",
        "description": (
            "Answers a STEM research question with mathematics (Axiom), physics and reference data (Physis), "
            "numerical simulation (Dynamis), literature (Archivon), and sandboxed computation (Calcula); "
            "every claim is verified and cited."
        ),
        "tags": ["engineering", "mathematics", "physics", "simulation", "computer algebra", "literature"],
        "examples": [
            "Derive the dispersion relation for plasma oscillations and solve for the cutoff frequency.",
            "Simulate the harmonic oscillator ODE system with damping and plot the trajectory.",
            "What is the fine-structure constant and its CODATA 2022 recommended value?",
        ],
        "inputModes": ["text/plain"],
        "outputModes": ["text/plain", "text/markdown"],
    },
    {
        "id": "symbolic-numerical-simulation",
        "name": "Symbolic Mathematics and Numerical Simulation",
        "description": "Performs exact computer algebra with SymPy and numerical ODE simulation and optimization with SciPy.",
        "tags": ["symbolic math", "SymPy", "ODE", "SciPy", "simulation"],
        "examples": ["Solve the differential equation dy/dx + 2*y = exp(-x) with y(0) = 1."],
        "inputModes": ["text/plain"],
        "outputModes": ["text/plain", "text/markdown"],
    },
]


def _base_url(request: Request) -> str:
    """TRIBOS_PUBLIC_URL when it is an http(s) URL, else the request's own base URL. The Card is public and cacheable,
    so its URLs should not follow whatever Host header a caller sends."""
    public = str(get_str("TRIBOS_PUBLIC_URL") or "").strip().rstrip("/")
    if public:
        parts = urlsplit(public)
        if parts.scheme in ("http", "https") and parts.netloc:
            return public
        logger.warning("Ignoring TRIBOS_PUBLIC_URL: it is not an http(s) URL")
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/agent-card.json")
async def agent_card(request: Request) -> dict[str, Any]:
    base = _base_url(request)
    info = _server_info()
    return {
        "protocolVersion": A2A_VERSION,
        "name": "Tribos",
        "description": (
            "Engineering, Mathematics and Scientific R&D Assistant: plans and executes multi-agent investigations across "
            "literature (Archivon), symbolic mathematics (Axiom), numerical simulation (Dynamis), sandboxed Python (Calcula), "
            "and physical constants (Physis), returning verified, cited answers."
        ),
        "url": f"{base}/a2a",
        "preferredTransport": "JSONRPC",
        "supportedInterfaces": [{"url": f"{base}/a2a", "protocolBinding": "JSONRPC", "protocolVersion": A2A_VERSION}],
        "provider": {"organization": "Tribos", "url": base},
        "version": info["version"],
        "documentationUrl": f"{base}/docs",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "text/markdown"],
        "skills": _SKILLS,
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer", "description": "The Tribos API bearer token (static token or JWT)."}},
        "security": [{"bearer": []}],
    }


def _text_of(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or message.get("content") or []
    texts: list[str] = []
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind") or part.get("type")
        if isinstance(part.get("text"), str) and kind in (None, "text"):
            texts.append(part["text"])
    return "\n".join(t.strip() for t in texts if t.strip())


def _agent_message(text: str, task_id: str, context_id: str) -> dict[str, Any]:
    return {
        "kind": "message",
        "role": "agent",
        "messageId": f"msg_{uuid.uuid4().hex[:12]}",
        "taskId": task_id,
        "contextId": context_id,
        "parts": [{"kind": "text", "text": text}],
    }


def task_view(job: dict[str, Any]) -> dict[str, Any]:
    state = _STATE.get(job["status"], "unknown")
    status: dict[str, Any] = {"state": state, "timestamp": job.get("updated_at")}
    task: dict[str, Any] = {
        "kind": "task",
        "id": job["job_id"],
        "contextId": job["thread_id"],
        "status": status,
        "metadata": {"job_status": job["status"], "run_id": job.get("run_id"), "framework": job.get("framework")},
    }
    result = job.get("result") or {}
    if state == "completed" and result:
        report = result.get("verification_report") or {}
        task["artifacts"] = [
            {
                "artifactId": f"{job['job_id']}-answer",
                "name": "answer",
                "parts": [
                    {"kind": "text", "text": str(result.get("response", ""))},
                    {
                        "kind": "data",
                        "data": {
                            "task_status": result.get("task_status"),
                            "verification": {"passed": report.get("passed"), "verification_score": report.get("verification_score")},
                            "citations": result.get("citations") or {},
                        },
                    },
                ],
            }
        ]
    elif state in ("failed", "canceled") and job.get("error"):
        hint = " Resume it with POST /api/jobs/{id}/resume.".replace("{id}", job["job_id"]) if job["status"] == "interrupted" else ""
        status["message"] = _agent_message(f"{job['error']}{hint}", job["job_id"], job["thread_id"])
    return task


def _job_or_404(user_id: str, task_id: Any) -> dict[str, Any]:
    if not isinstance(task_id, str) or not JOB_ID_RE.match(task_id):
        raise RpcError(TASK_NOT_FOUND, "Task not found")
    job = get_job_manager().get(task_id, user_id)
    if job is None:
        raise RpcError(TASK_NOT_FOUND, "Task not found")
    return job


async def _send_message(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
    message = params.get("message")
    text = _text_of(message)
    if not text:
        raise RpcError(INVALID_PARAMS, "The message needs at least one text part")
    if len(text) > 20_000:
        raise RpcError(INVALID_PARAMS, "The message text is longer than 20000 characters")
    metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
    context_id = message.get("contextId") if isinstance(message, dict) else None
    if not isinstance(context_id, str) or not context_id.strip() or len(context_id) > 200:
        context_id = f"a2a_{uuid.uuid4().hex[:12]}"
    framework = agent_config.resolve_framework(str(metadata.get("framework") or ""), agent_config.AGENTIC)
    request = {"message": text, "thread_id": context_id, "framework": framework, "enable_web_search": bool(metadata.get("enable_web_search", True))}
    manager = get_job_manager()
    try:
        job = await manager.submit(user_id, request, origin="a2a")
    except JobError as exc:
        raise RpcError(INTERNAL_ERROR if exc.status_code != 422 else INVALID_PARAMS, str(exc)) from exc
    config = params.get("configuration") if isinstance(params.get("configuration"), dict) else {}
    if config.get("blocking"):
        timeout = float(os.getenv("TRIBOS_A2A_BLOCKING_TIMEOUT_S", "300") or 300)
        await manager.wait(job["job_id"], timeout)
    return task_view(manager.get(job["job_id"], user_id) or job)


async def _list_tasks(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        size = max(1, min(100, int(params.get("pageSize") or 50)))
    except (TypeError, ValueError):
        raise RpcError(INVALID_PARAMS, "pageSize must be an integer") from None
    context_id = params.get("contextId") if isinstance(params.get("contextId"), str) else None
    jobs = get_job_manager().list(user_id, limit=size, thread_id=context_id)
    tasks = [task_view(j) for j in jobs]
    wanted = params.get("status")
    if isinstance(wanted, str) and wanted:
        tasks = [t for t in tasks if t["status"]["state"] == wanted]
    return {"tasks": tasks, "nextPageToken": "", "pageSize": size, "totalSize": len(tasks)}


async def _cancel_task(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
    job = _job_or_404(user_id, params.get("id"))
    if job["status"] in ("succeeded", "failed", "cancelled"):
        raise RpcError(TASK_NOT_CANCELABLE, f"Task is already {_STATE[job['status']]}")
    updated = await get_job_manager().cancel(job["job_id"], user_id, reason="cancelled through A2A")
    return task_view(get_job_manager().get(job["job_id"], user_id) or updated or job)


async def _handle(user_id: str, method: str, params: dict[str, Any]) -> Any:
    if method in ("SendMessage", "message/send"):
        return await _send_message(user_id, params)
    if method in ("GetTask", "tasks/get"):
        return task_view(_job_or_404(user_id, params.get("id")))
    if method in ("ListTasks", "tasks/list"):
        return await _list_tasks(user_id, params)
    if method in ("CancelTask", "tasks/cancel"):
        return await _cancel_task(user_id, params)
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method[:80]}")


@router.post("/a2a")
async def a2a_endpoint(request: Request, user_id: str = Depends(get_current_user)) -> Response:
    payload, error = await parse_body(request)
    if error is not None:
        return error

    async def handler(method: str, req_id: Any, params: dict[str, Any]) -> Any:
        return await _handle(user_id, method, params)

    return await dispatch_rpc(payload, handler)


@router.get("/a2a")
async def a2a_get() -> Response:
    return JSONResponse({"detail": "POST JSON-RPC requests here; the Agent Card is at /.well-known/agent-card.json"}, status_code=405, headers={"Allow": "POST"})

