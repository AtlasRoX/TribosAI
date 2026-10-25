"""Regression tests for the API fixes (BRK-7, LOG-36 to LOG-39, contracts 1-3 and the API polish items)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
ALICE = {"Authorization": "Bearer alice-token"}


@pytest.fixture
def api(monkeypatch):
    from app.backend import main as backend_main

    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    return TestClient(backend_main.app), backend_main


# -- BRK-7: the API starts without tribos.vision ------------------------------------------------------------------

def test_the_api_starts_and_keeps_image_text_without_the_vision_package():
    script = (
        "import sys\n"
        "sys.modules['tribos.vision'] = None  # import tribos.vision -> ImportError\n"
        "import app.backend.main as m\n"
        "assert 'app.backend.routers.vision' in m.DISABLED_ROUTERS, m.DISABLED_ROUTERS\n"
        "req = m.ChatRequest(message='Solve it.', image_context=[{'name': 'q.png', 'text': 'y + 1 = 2'}])\n"
        "print(repr(req.full_message))\n"
    )
    env = {**os.environ, "TRIBOS_AUTH_MODE": "disabled"}
    env.pop("TRIBOS_STRICT_ROUTERS", None)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "'Solve it.\\n\\nAttached image 1 (q.png), transcribed:\\ny + 1 = 2'" in proc.stdout


# -- LOG-36: security-middleware refusals carry CORS headers ------------------------------------------------------

def test_a_body_too_large_refusal_carries_the_cors_header(api):
    client, backend_main = api
    origin = backend_main._cors_origins[0]
    body = b'{"message": "' + b"x" * (3 * 1024 * 1024) + b'"}'
    res = client.post("/api/chat", content=body, headers={**ALICE, "Origin": origin, "Content-Type": "application/json"})
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == origin


def test_a_refused_origin_still_gets_no_cors_header(api):
    client, _ = api
    res = client.post("/api/chat", json={"message": "hi"}, headers={**ALICE, "Origin": "https://evil.example"})
    assert res.status_code == 403
    assert "access-control-allow-origin" not in res.headers


# -- LOG-37: background jobs store the typed text separately ------------------------------------------------------

def test_a_job_request_keeps_the_typed_message_for_display():
    from app.backend.routers.jobs import request_from_body

    request, _ = request_from_body({"message": "Solve it.", "image_context": [{"name": "q.png", "text": "x + 1 = 2"}]})
    assert request["display_message"] == "Solve it."
    assert request["message"].startswith("Solve it.\n\nAttached image 1 (q.png)") and "x + 1 = 2" in request["message"]


# -- LOG-38: client_request_id ------------------------------------------------------------------------------------

def test_a_retried_question_that_is_still_running_gets_409(api, monkeypatch):
    client, backend_main = api
    from app.backend.limits import RecentRequestIds, UserConcurrencyLimiter

    running = RecentRequestIds()
    slots = UserConcurrencyLimiter(2)
    monkeypatch.setattr(backend_main, "_running_requests", running)
    monkeypatch.setattr(backend_main, "_chat_slots", slots)
    assert running.claim("alice", "req-1")  # the first POST, still running
    for path in ("/api/chat", "/api/chat/stream"):
        res = client.post(path, json={"message": "hi", "client_request_id": "req-1"}, headers=ALICE)
        assert res.status_code == 409 and "already running" in res.json()["detail"]
    assert slots.active("alice") == 0  # a refused duplicate takes no chat slot

    release = backend_main._acquire_chat("alice", "req-2")
    with pytest.raises(Exception) as exc:
        backend_main._acquire_chat("alice", "req-2")
    assert getattr(exc.value, "status_code", None) == 409
    release()
    release()  # idempotent
    assert running.get("alice", "req-2") is None and slots.active("alice") == 0
    backend_main._acquire_chat("alice", "req-2")()  # accepted again once the first has finished


def test_a_429_does_not_leave_the_request_id_claimed(monkeypatch):
    from app.backend import main as backend_main
    from app.backend.limits import RecentRequestIds, UserConcurrencyLimiter

    running = RecentRequestIds()
    slots = UserConcurrencyLimiter(1)
    monkeypatch.setattr(backend_main, "_running_requests", running)
    monkeypatch.setattr(backend_main, "_chat_slots", slots)
    assert slots.try_acquire("alice")
    with pytest.raises(Exception) as exc:
        backend_main._acquire_chat("alice", "req-3")
    assert getattr(exc.value, "status_code", None) == 429
    assert running.get("alice", "req-3") is None


def test_client_request_id_is_validated():
    from pydantic import ValidationError

    from app.backend.main import ChatRequest

    assert ChatRequest(message="hi", client_request_id="0b6f-uuid_1:x.y").client_request_id == "0b6f-uuid_1:x.y"
    for bad in ("has space", "x" * 101, "<script>"):
        with pytest.raises(ValidationError):
            ChatRequest(message="hi", client_request_id=bad)


def test_request_id_table_is_bounded():
    from app.backend.limits import RecentRequestIds

    ids = RecentRequestIds(ttl_s=60, per_user=3, max_users=2)
    for i in range(10):
        ids.put("u1", f"r{i}")
    assert len(ids) == 3 and ids.get("u1", "r9") and ids.get("u1", "r0") is None
    ids.put("u2", "a")
    ids.put("u3", "b")
    assert ids.get("u1", "r9") is None  # least recently used user dropped
    expired = RecentRequestIds(ttl_s=0)
    expired.put("u", "r")
    assert expired.get("u", "r") is None


def test_a_retried_job_submission_returns_the_same_job(api, monkeypatch):
    client, _ = api
    from app.backend.limits import RecentRequestIds
    from app.backend.routers import jobs as jobs_router

    submitted: list[dict[str, Any]] = []

    class _Manager:
        async def submit(self, user_id: str, request: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
            submitted.append(request)
            return {"job_id": f"job_{len(submitted):012d}", "run_id": "run_x", "status": "queued", "thread_id": "t"}

    monkeypatch.setattr(jobs_router, "get_job_manager", lambda: _Manager())
    monkeypatch.setattr(jobs_router, "_submitted", RecentRequestIds(ttl_s=600))
    body = {"message": "hi", "client_request_id": "job-req-1"}
    first = client.post("/api/jobs", json=body, headers=ALICE).json()
    second = client.post("/api/jobs", json=body, headers=ALICE).json()
    assert len(submitted) == 1 and second["job_id"] == first["job_id"] and second["duplicate"] is True
    assert client.post("/api/jobs", json={"message": "hi"}, headers=ALICE).status_code == 201
    assert len(submitted) == 2


# -- LOG-39: legacy datasets --------------------------------------------------------------------------------------

def _legacy_manifest(store, user_id: str, ds_id: str, kind: str, payload: bytes) -> Path:
    ds_dir = store.user_dir(user_id) / ds_id
    ds_dir.mkdir(parents=True)
    (ds_dir / "original.h5ad").write_bytes(payload)
    manifest = {
        "id": ds_id, "kind": kind, "display_name": "cells.h5ad", "original_extension": ".h5ad",
        "size_bytes": len(payload), "sha256": "0" * 64, "uploaded_at": datetime.now(UTC).isoformat(),
        "provenance": {"source": "geo", "table_orientation": "cells_by_genes"},
        "validation": {"format": kind, "n_obs": 10, "n_vars": 5},
    }
    (ds_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ds_dir


@pytest.fixture
def store(monkeypatch, tmp_path):
    from tribos.datasets.store import DatasetStore, reset_dataset_store

    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(tmp_path / "uploads"))
    reset_dataset_store()
    yield DatasetStore(tmp_path / "uploads")
    reset_dataset_store()


@pytest.mark.parametrize("kind", ["h5ad", "sbml"])
def test_legacy_datasets_are_listed_counted_and_deletable(store, kind):
    from tribos.datasets.models import DatasetKind

    ds_dir = _legacy_manifest(store, "alice", "ds_00000000abcd", kind, b"x" * 1000)
    (store.user_dir("alice") / "ds_ffffffffffff").mkdir()  # a crashed upload: no manifest, not listable
    (store.user_dir("alice") / "ds_ffffffffffff" / "upload.part").write_bytes(b"y" * 5000)

    records = store.list("alice")
    assert [r.id for r in records] == ["ds_00000000abcd"]
    record = records[0]
    assert record.kind == DatasetKind.LEGACY and record.legacy_kind == kind and not record.analysable
    api_view = record.to_api()
    assert api_view["analysable"] is False and "no longer analyses" in api_view["unsupported_reason"]
    # Quota counts exactly what the user can list (and so delete).
    listed_bytes = sum(f.stat().st_size for f in ds_dir.iterdir())
    assert store.usage_bytes("alice") == listed_bytes

    found, errors = store.resolve_for_user("alice", ["ds_00000000abcd"])
    assert found == [] and "legacy" in errors[0]

    store.delete("alice", "ds_00000000abcd")
    assert store.list("alice") == [] and store.usage_bytes("alice") == 0


def test_legacy_dataset_api_round_trip(api, store, monkeypatch):
    client, _ = api
    from tribos.datasets import store as store_module

    monkeypatch.setattr(store_module, "_STORE", store)
    _legacy_manifest(store, "alice", "ds_00000000abce", "h5ad", b"z" * 10)
    listed = client.get("/api/datasets", headers=ALICE).json()["datasets"]
    assert [d["kind"] for d in listed] == ["legacy"]
    assert client.delete("/api/datasets/ds_00000000abce", headers=ALICE).status_code == 200


# -- contract 1: GET /api/datasets/limits -------------------------------------------------------------------------

def test_dataset_limits_endpoint(api, monkeypatch):
    client, _ = api
    for name in ("TRIBOS_UPLOAD_MAX_MB_CSV", "TRIBOS_UPLOAD_MAX_MB_HDF5", "TRIBOS_UPLOAD_MAX_MB_H5AD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_MB_MAT", "7")
    res = client.get("/api/datasets/limits", headers=ALICE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["extensions"] == {".csv": "table", ".tsv": "table", ".xlsx": "table", ".parquet": "table",
                                  ".json": "table", ".h5": "hdf5", ".hdf5": "hdf5", ".mat": "mat", ".pdf": "paper"}
    assert body["max_bytes"] == {"table": 100 * 1024 * 1024, "hdf5": 500 * 1024 * 1024, "mat": 7 * 1024 * 1024,
                                 "paper": 25 * 1024 * 1024}
    assert client.get("/api/datasets/limits").status_code == 401


def test_the_mat_cap_no_longer_follows_the_csv_cap(monkeypatch):
    from tribos.datasets.models import DatasetKind
    from tribos.datasets.store import kind_cap_bytes

    monkeypatch.delenv("TRIBOS_UPLOAD_MAX_MB_MAT", raising=False)
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_MB_CSV", "1")
    assert kind_cap_bytes(DatasetKind.MAT) == 100 * 1024 * 1024
    assert kind_cap_bytes(DatasetKind.TABLE) == 1024 * 1024


# -- contract 3: FactPatch refuses unknown fields -----------------------------------------------------------------

def test_fact_patch_refuses_unknown_fields():
    from pydantic import ValidationError

    from app.backend.routers.projects import FactPatch, ProjectCreate

    assert FactPatch.model_validate({"invalidate": True, "reason": "retracted"}).invalidate is True
    with pytest.raises(ValidationError):
        FactPatch.model_validate({"invalid": True})
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate({"name": "p", "colour": "red"})


# -- polish -------------------------------------------------------------------------------------------------------

def test_agent_card_uses_the_configured_public_url(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("TRIBOS_PUBLIC_URL", "https://tribos.example.org/")
    card = client.get("/.well-known/agent-card.json").json()
    assert card["url"] == "https://tribos.example.org/a2a" and card["provider"]["url"] == "https://tribos.example.org"
    monkeypatch.setenv("TRIBOS_PUBLIC_URL", "javascript:alert(1)")
    assert client.get("/.well-known/agent-card.json").json()["url"] == "http://testserver/a2a"


def test_health_cache_expires(api, monkeypatch):
    client, backend_main = api
    calls: list[int] = []

    async def probe() -> dict[str, Any]:
        calls.append(1)
        return {"mcp_remote_active": False, "direct_adapters": {}}

    monkeypatch.setattr(backend_main, "_readiness_probe", probe)
    monkeypatch.setitem(backend_main._health_cache, "readiness", None)
    monkeypatch.setenv("TRIBOS_HEALTH_CACHE_S", "0")
    client.get("/api/health")
    client.get("/api/health")
    assert len(calls) == 2
    monkeypatch.setenv("TRIBOS_HEALTH_CACHE_S", "60")
    client.get("/api/health")
    client.get("/api/health")
    assert len(calls) == 2  # the last probe is still fresh
    monkeypatch.setitem(backend_main._health_cache, "at", 0.0)  # ... until it is older than the TTL
    client.get("/api/health")
    assert len(calls) == 3
    details = client.get("/api/health/details", headers=ALICE).json()
    assert "service_readiness" in details and "biocontext_service_readiness" not in details


def test_heuristic_titles_keep_stem_acronyms():
    from app.backend.main import _heuristic_title

    assert _heuristic_title("explain cfd meshing for a pde on a fem grid") == "CFD Meshing for a PDE on a FEM Grid"
    assert _heuristic_title("what is the codata value in si units") == "CODATA Value in SI Units"


def test_image_reads_take_the_users_slot_before_parsing(api, monkeypatch):
    client, _ = api
    from app.backend.limits import UserConcurrencyLimiter, UserSemaphores
    from app.backend.routers import vision

    monkeypatch.setenv("TRIBOS_VISION", "1")
    monkeypatch.setattr(vision, "_user_reading", UserSemaphores(1))
    queued = UserConcurrencyLimiter(1)
    monkeypatch.setattr(vision, "_user_queued", queued)
    seen: list[bool] = []

    async def fake_read(request, limit):
        seen.append(vision._user_reading.get("alice").locked())
        return {"text": "ok"}

    monkeypatch.setattr(vision, "_read_upload", fake_read)
    files = {"file": ("q.png", b"\x89PNG....", "image/png")}
    assert client.post("/api/vision/read", files=files, headers=ALICE).json() == {"text": "ok"}
    assert seen == [True] and queued.active("alice") == 0
    assert queued.try_acquire("alice")  # alice already has the maximum waiting
    res = client.post("/api/vision/read", files=files, headers=ALICE)
    assert res.status_code == 429 and res.json()["reason"] == "busy" and len(seen) == 1


def test_a_full_rerun_takes_a_chat_slot(api, monkeypatch):
    client, backend_main = api
    from app.backend.limits import UserConcurrencyLimiter
    from app.backend.routers import export

    async def owned(user_id: str, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "query": "q"}

    class _Orch:
        async def execute_inquiry(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("must not run without a chat slot")

    slots = UserConcurrencyLimiter(1)
    monkeypatch.setattr(backend_main, "_chat_slots", slots)
    monkeypatch.setattr(export, "_load_owned", owned)
    monkeypatch.setattr(export, "_get_orchestrator", lambda: _Orch())
    assert slots.try_acquire("alice")
    res = client.post("/api/runs/run_abc/rerun", json={"mode": "full"}, headers=ALICE)
    assert res.status_code == 429
    slots.release("alice")
    assert slots.active("alice") == 0
