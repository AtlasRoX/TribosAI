"""
Offline tests for STEM dataset uploads: the per-user store, structural validators, API,
attachment resolution, provenance tracking, and quota enforcement.

Supported STEM formats:
- Tables: .csv, .tsv, .xlsx, .parquet, .json
- Scientific containers: .h5, .hdf5, .mat
Legacy biomedical formats (.h5ad, .sbml, .xml) and GEO lookups are removed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.io as spio

from tests.fakes import make_offline_orchestrator
from tribos.agents.query_context import QueryContext
from tribos.datasets.attach import resolve_attachments
from tribos.datasets.models import DatasetKind, DatasetProvenanceIn
from tribos.datasets.paths import is_allowed_typed_path
from tribos.datasets.provenance import postprocess_dataset_result
from tribos.datasets.store import (
    DatasetNotFound,
    DatasetStoreError,
    get_dataset_store,
    reset_dataset_store,
)
from tribos.extensions import load_extensions
from tribos.extensions import uploads as uploads_ext
from tribos.tools.registry import ToolResult

REPO = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")


def _prov(**kw: Any) -> DatasetProvenanceIn:
    return DatasetProvenanceIn(**{"source": "in_house", "attests_no_direct_identifiers": True, **kw})


def _chunks(data: bytes, size: int = 4096) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"col_1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "col_2": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]},
        index=[f"row_{i}" for i in range(1, 7)],
    )


def _csv_bytes() -> bytes:
    return _sample_df().to_csv().encode("utf-8")


def _tsv_bytes() -> bytes:
    return _sample_df().to_csv(sep="\t").encode("utf-8")


def _xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    _sample_df().to_excel(buf)
    return buf.getvalue()


def _parquet_bytes() -> bytes:
    buf = io.BytesIO()
    _sample_df().to_parquet(buf)
    return buf.getvalue()


def _json_bytes() -> bytes:
    return _sample_df().to_json().encode("utf-8")


def _hdf5_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "sample.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("readings", data=np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]]))
    return p.read_bytes()


def _mat_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "sample.mat"
    spio.savemat(str(p), {"matrix": np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])})
    return p.read_bytes()


@pytest.fixture
def upload_root(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(root))
    for name in (
        "TRIBOS_UPLOAD_MAX_MB_HDF5",
        "TRIBOS_UPLOAD_MAX_MB_H5AD",
        "TRIBOS_UPLOAD_MAX_MB_CSV",
        "TRIBOS_UPLOAD_MAX_MB_MAT",
        "TRIBOS_UPLOAD_MAX_MB_SBML",
        "TRIBOS_UPLOAD_MAX_TOTAL_MB",
        "TRIBOS_UPLOAD_MAX_DATASETS",
        "TRIBOS_DATASET_ROOTS",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_dataset_store()
    yield root
    reset_dataset_store()


@pytest.fixture
def store(upload_root):
    return get_dataset_store()


@pytest.fixture
def upload_hooks():
    load_extensions()


def _no_part_files(root: Path) -> bool:
    return not list(root.rglob("*.part"))


# =============================================================================
# 1. STEM Datasets Acceptance (.csv, .tsv, .xlsx, .parquet, .json, .h5, .mat)
# =============================================================================

@pytest.mark.asyncio
async def test_valid_csv_is_accepted(store, upload_root):
    data = _csv_bytes()
    rec = await store.create_from_stream("alice", _chunks(data), "data.csv", _prov())
    assert ID_RE.match(rec.id)
    assert rec.kind == DatasetKind.TABLE
    assert rec.sha256 == hashlib.sha256(data).hexdigest()
    assert rec.size_bytes == len(data)
    assert rec.validation.n_rows == 6 and rec.validation.n_columns == 2
    ds_dir = store.user_dir("alice") / rec.id
    assert (ds_dir / "manifest.json").exists() and (ds_dir / "original.csv").exists()
    public = json.dumps(rec.public_provenance()) + json.dumps(rec.to_api())
    assert str(upload_root) not in public and "original.csv" not in public
    assert _no_part_files(upload_root)


@pytest.mark.asyncio
async def test_valid_tsv_is_accepted(store):
    data = _tsv_bytes()
    rec = await store.create_from_stream("alice", _chunks(data), "data.tsv", _prov())
    assert rec.kind == DatasetKind.TABLE
    assert rec.validation.n_rows == 6 and rec.validation.n_columns == 2


@pytest.mark.asyncio
async def test_valid_xlsx_is_accepted(store):
    data = _xlsx_bytes()
    rec = await store.create_from_stream("alice", _chunks(data), "data.xlsx", _prov())
    assert rec.kind == DatasetKind.TABLE
    assert rec.validation.format == "xlsx"
    assert rec.validation.n_rows == 6


@pytest.mark.asyncio
async def test_valid_parquet_is_accepted(store):
    data = _parquet_bytes()
    rec = await store.create_from_stream("alice", _chunks(data), "data.parquet", _prov())
    assert rec.kind == DatasetKind.TABLE
    assert rec.validation.format == "parquet"
    assert rec.validation.n_rows == 6


@pytest.mark.asyncio
async def test_valid_json_is_accepted(store):
    data = _json_bytes()
    rec = await store.create_from_stream("alice", _chunks(data), "data.json", _prov())
    assert rec.kind == DatasetKind.TABLE
    assert rec.validation.format == "json"
    assert rec.validation.n_rows == 6


@pytest.mark.asyncio
async def test_valid_hdf5_is_accepted(store, tmp_path):
    data = _hdf5_bytes(tmp_path)
    rec = await store.create_from_stream("alice", _chunks(data), "experiment.h5", _prov())
    assert rec.kind == DatasetKind.HDF5
    assert rec.validation.format == "hdf5"
    assert "readings" in rec.validation.datasets
    assert rec.validation.shapes["readings"] == [5, 2]


@pytest.mark.asyncio
async def test_valid_mat_is_accepted(store, tmp_path):
    data = _mat_bytes(tmp_path)
    rec = await store.create_from_stream("alice", _chunks(data), "simulation.mat", _prov())
    assert rec.kind == DatasetKind.MAT
    assert rec.validation.format == "mat"
    assert "matrix" in rec.validation.datasets


# =============================================================================
# 2. Legacy and Unsupported Types Rejection (.h5ad, .sbml, .xml, .exe)
# =============================================================================

@pytest.mark.asyncio
async def test_h5ad_and_sbml_rejected_as_unsupported(store, tmp_path):
    data = _csv_bytes()
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [data], "test.h5ad", _prov())
    assert err.value.status_code == 415
    assert err.value.reason_code == "unsupported_type"

    with pytest.raises(DatasetStoreError) as err2:
        await store.create_from_stream("alice", [b"<sbml></sbml>"], "model.xml", _prov())
    assert err2.value.status_code == 415
    assert err2.value.reason_code == "unsupported_type"

    with pytest.raises(DatasetStoreError) as err3:
        await store.create_from_stream("alice", [b"<sbml></sbml>"], "model.sbml", _prov())
    assert err3.value.status_code == 415
    assert err3.value.reason_code == "unsupported_type"


# =============================================================================
# 3. Structural Validation & Hostile File Rejection
# =============================================================================

@pytest.mark.asyncio
async def test_truncated_hdf5_is_rejected(store, tmp_path, upload_root):
    data = _hdf5_bytes(tmp_path)
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [data[: len(data) // 2]], "half.h5", _prov())
    assert (err.value.status_code, err.value.reason_code) == (422, "hdf5_unreadable")
    assert store.list("alice") == [] and _no_part_files(upload_root)


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["external", "soft"])
async def test_hdf5_with_links_is_rejected(store, tmp_path, link):
    crafted = tmp_path / "crafted.h5"
    with h5py.File(crafted, "w") as f:
        f.create_dataset("data", data=[1, 2, 3])
        f["leak"] = h5py.ExternalLink("other.h5", "/data") if link == "external" else h5py.SoftLink("/data")
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [crafted.read_bytes()], "crafted.h5", _prov())
    assert (err.value.status_code, err.value.reason_code) == (422, "hdf5_external_link")


@pytest.mark.asyncio
async def test_empty_hdf5_is_rejected(store, tmp_path):
    empty = tmp_path / "empty.h5"
    with h5py.File(empty, "w"):
        pass
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [empty.read_bytes()], "empty.h5", _prov())
    assert (err.value.status_code, err.value.reason_code) == (422, "hdf5_empty")


@pytest.mark.asyncio
async def test_csv_with_non_numeric_column_is_an_ordinary_table_but_not_a_matrix(store):
    df = _sample_df()
    df["label"] = "experiment_A"
    # An ordinary table may carry text (material names, sample labels): it is accepted with its types (AUDIT-108).
    rec = await store.create_from_stream("alice", [df.to_csv().encode()], "mixed.csv", _prov())
    assert rec.validation.dtypes.get("label") == "object"
    # Declared as an expression matrix, every value must be numeric.
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [df.to_csv().encode()], "mixed.csv",
                                       _prov(table_orientation="cells_by_genes"))
    assert (err.value.status_code, err.value.reason_code) == (422, "non_numeric_values")


# =============================================================================
# 4. Quotas, Orphans, Cleanup, Concurrency
# =============================================================================

@pytest.mark.asyncio
async def test_size_cap_while_streaming_leaves_no_part_file(store, upload_root, monkeypatch):
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_MB_CSV", "0.0001")  # very small cap
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", _chunks(_csv_bytes()), "data.csv", _prov())
    assert (err.value.status_code, err.value.reason_code) == (413, "too_large")
    assert _no_part_files(upload_root)
    assert not list(store.user_dir("alice").iterdir())


@pytest.mark.asyncio
async def test_startup_sweep_removes_orphaned_uploads(store, upload_root):
    data = _csv_bytes()
    rec = await store.create_from_stream("alice", [data], "keep.csv", _prov())
    udir = store.user_dir("alice")
    orphan = udir / "ds_0123456789ab"
    orphan.mkdir()
    (orphan / "upload.part").write_bytes(data[:100])
    stray = udir / rec.id / "upload.part"
    stray.write_bytes(b"x")
    old = time.time() - 7200
    for p in (orphan / "upload.part", orphan, stray, udir / rec.id):
        os.utime(p, (old, old))
    reset_dataset_store()
    fresh = get_dataset_store()
    assert not orphan.exists() and not stray.exists()
    assert [r.id for r in fresh.list("alice")] == [rec.id]


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows refuses to move a directory holding an open file")
async def test_delete_while_file_is_open_is_a_conflict(store):
    rec = await store.create_from_stream("alice", [_csv_bytes()], "busy.csv", _prov())
    analysis_path, _ = store.file_paths("alice", rec)
    with open(analysis_path, "rb"):
        with pytest.raises(DatasetStoreError) as err:
            store.delete("alice", rec.id)
    assert (err.value.status_code, err.value.reason_code) == (409, "in_use")
    assert store.get("alice", rec.id).id == rec.id
    store.delete("alice", rec.id)
    assert store.list("alice") == []


@pytest.mark.asyncio
async def test_total_quota_and_dataset_count(store, monkeypatch):
    data = _csv_bytes()
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_DATASETS", "1")
    await store.create_from_stream("alice", [data], "a.csv", _prov())
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", [data], "b.csv", _prov())
    assert (err.value.status_code, err.value.reason_code) == (507, "quota_exceeded")
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_DATASETS", "50")
    monkeypatch.setenv("TRIBOS_UPLOAD_MAX_TOTAL_MB", "0.0008")
    with pytest.raises(DatasetStoreError) as err:
        await store.create_from_stream("alice", _chunks(data), "c.csv", _prov())
    assert err.value.status_code == 507


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_env,limit", [("TRIBOS_UPLOAD_MAX_DATASETS", "1"), ("TRIBOS_UPLOAD_MAX_TOTAL_MB", "0.0004")])
async def test_parallel_uploads_cannot_exceed_user_limits(store, monkeypatch, limit_env, limit):
    import asyncio

    monkeypatch.setenv(limit_env, limit)
    gate = asyncio.Event()
    data = _csv_bytes()

    async def held_open():
        await gate.wait()
        yield data

    tasks = [asyncio.create_task(store.create_from_stream("alice", held_open(), f"{i}.csv", _prov())) for i in range(3)]
    for _ in range(10):
        await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 2 and all(isinstance(f, DatasetStoreError) and f.status_code == 507 for f in failures)
    assert len(store.list("alice")) == 1 and _no_part_files(store.root)


# =============================================================================
# 5. Isolation, Hashed User Directories, Path Sanitization
# =============================================================================

@pytest.mark.asyncio
async def test_per_user_isolation_and_safe_names(store, upload_root):
    data = _csv_bytes()
    rec = await store.create_from_stream("alice:lab-1", [data], "../../evil.csv", _prov())
    udir = store.user_dir("alice:lab-1")
    assert re.fullmatch(r"[0-9a-f]{16}", udir.name)
    assert all(":" not in str(p.relative_to(upload_root)) for p in upload_root.rglob("*"))
    assert rec.display_name == "evil.csv"

    found, errors = store.resolve_for_user("bob", [rec.id])
    assert found == [] and errors == [f"Attached dataset {rec.id} not found"]
    _, unknown = store.resolve_for_user("bob", ["ds_0123456789ab"])
    assert unknown == ["Attached dataset ds_0123456789ab not found"]
    with pytest.raises(DatasetNotFound):
        store.get("bob", rec.id)
    with pytest.raises(DatasetNotFound):
        store.get("alice:lab-1", "../" + rec.id)

    for name, expected in [("C:\\x\\y.csv", "y.csv"), ("a\x00b.csv", "ab.csv"), ("<script>.csv", "_script_.csv")]:
        r = await store.create_from_stream("alice:lab-1", [data], name, _prov())
        assert r.display_name == expected


@pytest.mark.asyncio
async def test_resolve_attachments_builds_refs_and_typed_mentions(store):
    rec = await store.create_from_stream("alice", [_csv_bytes()], "experiment.csv", _prov())
    res = await resolve_attachments("alice", [], f"Analyze {rec.id} please")
    assert [a.id for a in res.attachments] == [rec.id] and res.errors == []
    ref = res.attachments[0]
    assert ref.kind == "table" and ref.analysis_path
    assert "path" not in json.dumps(ref.to_public()).lower()
    foreign = await resolve_attachments("bob", [rec.id], "")
    assert foreign.attachments == [] and foreign.errors == [f"Attached dataset {rec.id} not found"]


@pytest.mark.asyncio
async def test_resolve_attachments_without_store_creates_nothing(upload_root):
    res = await resolve_attachments("alice", ["ds_0123456789ab"], "")
    assert res.errors == ["Attached dataset ds_0123456789ab not found"]
    assert not upload_root.exists()


# =============================================================================
# 6. REST API Endpoints
# =============================================================================

@pytest.fixture
def client(monkeypatch, upload_root):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main

    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    return TestClient(backend_main.app)


ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}
PROV_JSON = json.dumps({"source": "in_house", "attests_no_direct_identifiers": True})


def _post(client, headers, name="data.csv", data=None, provenance=PROV_JSON):
    files = {"file": (name, data if data is not None else _csv_bytes(), "application/octet-stream")}
    return client.post("/api/datasets", headers=headers, files=files, data={"provenance": provenance})


def test_api_rejects_unauthenticated_before_parsing(client, monkeypatch):
    from starlette.requests import Request

    def never(*_a, **_k):
        raise AssertionError("the body must not be parsed before authentication")

    monkeypatch.setattr(Request, "form", never)
    assert _post(client, {}).status_code == 401
    assert _post(client, {"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/datasets").status_code == 401


def test_api_length_size_type_and_provenance_errors(client, monkeypatch, tmp_path):
    def body():
        yield b"--x\r\n"

    r = client.post("/api/datasets", headers={**ALICE, "Content-Type": "multipart/form-data; boundary=x"}, content=body())
    assert r.status_code == 411 and r.json()["reason_code"] == "length_required"

    r = _post(client, ALICE, name="tool.exe", data=b"MZ\x90\x00")
    assert r.status_code == 415 and r.json()["reason_code"] == "unsupported_type"

    r = _post(client, ALICE, name="test.h5ad", data=_csv_bytes())
    assert r.status_code == 415 and r.json()["reason_code"] == "unsupported_type"

    r = _post(client, ALICE, name="test.xml", data=b"<sbml></sbml>")
    assert r.status_code == 415 and r.json()["reason_code"] == "unsupported_type"

    r = _post(client, ALICE, provenance="{not json")
    assert r.status_code == 422 and r.json()["reason_code"] == "invalid_provenance"

    r = _post(client, ALICE, name="broken.h5", data=b"\x89HDF\r\n\x1a\ncorrupted")
    assert r.status_code == 422 and r.json()["reason_code"] == "hdf5_unreadable"

    for name in ("TRIBOS_UPLOAD_MAX_MB_HDF5", "TRIBOS_UPLOAD_MAX_MB_CSV"):
        monkeypatch.setenv(name, "0.0001")
    r = _post(client, ALICE, data=_csv_bytes() * 100)
    assert r.status_code == 413 and r.json()["reason_code"] == "too_large"


def test_api_upload_list_and_cross_user_404(client):
    r = _post(client, ALICE)
    assert r.status_code == 201, r.text
    body = r.json()
    ds_id = body["id"]
    assert ID_RE.match(ds_id)
    assert body["declared_by"] == "uploader"
    assert "path" not in json.dumps(body).lower()

    assert [d["id"] for d in client.get("/api/datasets", headers=ALICE).json()["datasets"]] == [ds_id]
    assert client.get("/api/datasets", headers=BOB).json() == {"datasets": [], "count": 0}
    assert client.get(f"/api/datasets/{ds_id}", headers=BOB).status_code == 404
    assert client.delete(f"/api/datasets/{ds_id}", headers=BOB).status_code == 404
    assert client.get("/api/datasets/not-an-id", headers=ALICE).status_code == 404
    assert client.get(f"/api/datasets/{ds_id}", headers=ALICE).status_code == 200

    assert client.delete(f"/api/datasets/{ds_id}", headers=ALICE).status_code == 200
    assert client.get(f"/api/datasets/{ds_id}", headers=ALICE).status_code == 404


def test_api_patch_provenance_keeps_history(client):
    ds_id = _post(client, ALICE).json()["id"]
    r = client.patch(
        f"/api/datasets/{ds_id}/provenance",
        headers=ALICE,
        json={"source": "simulation", "description": "CFD flow field run 4", "attests_no_direct_identifiers": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"]["source"] == "simulation"
    assert len(body["provenance_history"]) == 1
    assert body["provenance_history"][0]["previous"]["provenance"]["source"] == "in_house"
    assert client.patch(f"/api/datasets/{ds_id}/provenance", headers=BOB, json={"source": "other"}).status_code == 404
    bad = client.patch(f"/api/datasets/{ds_id}/provenance", headers=ALICE, json="not-an-object")
    assert bad.status_code == 422


# =============================================================================
# 7. Orchestration, Attachment Resolution & Path Security
# =============================================================================

@pytest.mark.asyncio
async def test_foreign_attachment_is_an_error_step(store, upload_root, monkeypatch, tmp_path):
    rec = await store.create_from_stream("bob", [_csv_bytes()], "bob.csv", _prov())
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry("Analyze this dataset", thread_id="t-foreign", enable_web_search=False, user_id="alice", dataset_ids=[rec.id])
    step = next(t for t in res.thoughts if t["id"] == "attachments")
    assert step["status"] == "error" and step["title"] == f"Attached dataset {rec.id} not found"
    assert str(upload_root) not in json.dumps(calls, default=str)


@pytest.mark.asyncio
async def test_typed_path_outside_roots_is_ignored(store, upload_root, monkeypatch, tmp_path):
    outside = tmp_path / "elsewhere" / "data.csv"
    outside.parent.mkdir()
    outside.write_bytes(_csv_bytes())
    assert not is_allowed_typed_path(str(outside))

    rec = await store.create_from_stream("alice", [_csv_bytes()], "a.csv", _prov())
    analysis_path, _ = store.file_paths("alice", rec)
    monkeypatch.setenv("TRIBOS_DATASET_ROOTS", str(upload_root.parent))
    assert not is_allowed_typed_path(analysis_path)  # uploads reachable only by ID


def _attachment_ctx(ref, query: str = "q") -> QueryContext:
    return QueryContext(raw_query=query, clean_query=query, attachments=[ref])


@pytest.mark.asyncio
async def test_declared_provenance_keeps_file_values_and_redacts_paths(store, upload_root):
    rec = await store.create_from_stream("alice", [_csv_bytes()], "dataset.csv", _prov(domain="materials_science"))
    ref = (await resolve_attachments("alice", [rec.id], "")).attachments[0]
    ctx = _attachment_ctx(ref)
    res = ToolResult(
        success=True,
        tool_name="calcula_describe_dataset",
        data={"dataset_path": ref.analysis_path, "dataset_provenance": {"file_path": ref.analysis_path, "domain": "materials_science"}},
    )
    prov = postprocess_dataset_result(res, ctx).data["dataset_provenance"]
    assert prov["domain"] == "materials_science"
    assert prov["declared_by"] == "uploader"

    folder = str(Path(ref.analysis_path).parent)
    failed = ToolResult(success=False, tool_name="calcula_describe_dataset", error=f"Unable to open (dir = '{folder}', root {upload_root.resolve()})")
    err = postprocess_dataset_result(failed, ctx).error
    assert folder not in err and str(upload_root.resolve()) not in err


@pytest.mark.asyncio
async def test_scope_note_names_attachments_that_were_not_analyzed(store):
    a = await store.create_from_stream("alice", [_csv_bytes()], "first.csv", _prov())
    b = await store.create_from_stream("alice", [_csv_bytes()], "second.csv", _prov())
    ctx = QueryContext(raw_query="q", clean_query="q", attachments=(await resolve_attachments("alice", [a.id, b.id], "")).attachments)
    notes = uploads_ext.upload_scope_notes(ctx, {})
    assert any("not analyzed" in n and b.id in n and a.id not in n for n in notes)
