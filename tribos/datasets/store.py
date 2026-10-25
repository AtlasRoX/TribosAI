"""
Per-user dataset store on local disk:

    <root>/<sha256(user_id)[:16]>/ds_<12 hex>/{original.<ext>, data.h5ad (optional), manifest.json}

User ids may contain ':' (valid in auth ids, illegal in Windows paths), so user directories are hashed.
Every path is server-generated and checked to lie under the root; uploader file names are kept only as a
sanitized display_name.
"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import AsyncIterable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    DATASET_ID_RE,
    UPLOAD_KINDS,
    DatasetKind,
    DatasetProvenanceIn,
    DatasetRecord,
    ResolvedAttachment,
)
from .validators import (
    ValidationFailure,
    validate_hdf5,
    validate_mat,
    validate_table,
)

logger = logging.getLogger(__name__)

EXTENSION_KINDS = {
    ".csv": DatasetKind.TABLE,
    ".tsv": DatasetKind.TABLE,
    ".xlsx": DatasetKind.TABLE,
    ".parquet": DatasetKind.TABLE,
    ".json": DatasetKind.TABLE,
    ".h5": DatasetKind.HDF5,
    ".hdf5": DatasetKind.HDF5,
    ".mat": DatasetKind.MAT,
}
CHUNK_BYTES = 1 << 20
_MB = 1024 * 1024
_ORPHAN_AGE_S = 3600
_MANIFEST = "manifest.json"
_PART = "upload.part"
_ANALYSIS = "data.h5ad"

Chunks = Iterable[bytes] | AsyncIterable[bytes]


class DatasetStoreError(Exception):
    """An upload or library failure with the HTTP status and stable reason code the API returns."""

    def __init__(self, status_code: int, detail: str, reason_code: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.reason_code = reason_code


class DatasetNotFound(DatasetStoreError):
    def __init__(self, ds_id: str) -> None:
        super().__init__(404, f"Dataset {str(ds_id)[:40]} not found", "not_found")


def default_upload_root() -> Path:
    env = os.getenv("TRIBOS_UPLOAD_ROOT")
    if env:
        return Path(env)
    from tribos.utils.paths import data_dir

    return data_dir("uploads") or Path(__file__).resolve().parents[2] / ".tribos_uploads"


def _env_mb(name: str, default_mb: float) -> int:
    try:
        return int(float(os.getenv(name, default_mb)) * _MB)
    except ValueError:
        return int(default_mb * _MB)


def kind_cap_bytes(kind: DatasetKind) -> int:
    if kind == DatasetKind.HDF5:
        # TRIBOS_UPLOAD_MAX_MB_H5AD is the biomedical release's name for the same cap (.h5ad files are HDF5).
        return _env_mb("TRIBOS_UPLOAD_MAX_MB_HDF5", _env_mb("TRIBOS_UPLOAD_MAX_MB_H5AD", 500) / _MB)
    if kind == DatasetKind.MAT:
        return _env_mb("TRIBOS_UPLOAD_MAX_MB_MAT", 100)
    if kind == DatasetKind.TABLE:
        return _env_mb("TRIBOS_UPLOAD_MAX_MB_CSV", 100)
    return 100 * _MB


def max_upload_bytes() -> int:
    """The largest single upload any kind allows; the API rejects larger Content-Length before parsing."""
    return max(kind_cap_bytes(k) for k in UPLOAD_KINDS)


def upload_limits() -> dict[str, dict[str, object]]:
    """Accepted extensions -> kind, and the byte cap of each kind (GET /api/datasets/limits)."""
    return {
        "extensions": {ext: kind.value for ext, kind in EXTENSION_KINDS.items()},
        "max_bytes": {kind.value: kind_cap_bytes(kind) for kind in UPLOAD_KINDS},
    }


def total_cap_bytes() -> int:
    return _env_mb("TRIBOS_UPLOAD_MAX_TOTAL_MB", 2048)


def max_datasets() -> int:
    try:
        return int(os.getenv("TRIBOS_UPLOAD_MAX_DATASETS", "50"))
    except ValueError:
        return 50


def sanitize_display_name(filename: str) -> str:
    """Basename only, with path separators, control characters and reserved characters removed."""
    name = (filename or "").replace("\x00", "")
    name = re.split(r"[\\/]", name)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\-()+ ]", "_", name).strip(" .")
    if len(name) > 128:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 127 - len(ext)] + "." + ext) if dot and len(ext) <= 8 else name[:128]
    return name or "upload"


def extension_of(filename: str) -> str:
    name = sanitize_display_name(filename)
    _, dot, ext = name.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def _is_within(path: Path, root: Path) -> bool:
    try:
        real, base = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([real, base]) == base
    except ValueError:  # different drives on Windows
        return False


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


async def _iterate(chunks: Chunks):
    if hasattr(chunks, "__aiter__"):
        async for chunk in chunks:  # type: ignore[union-attr]
            yield chunk
    else:
        for chunk in chunks:  # type: ignore[union-attr]
            yield chunk


class DatasetStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or default_upload_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._user_locks: dict[str, threading.Lock] = {}
        self.sweep_orphans()

    # -- layout ---------------------------------------------------------------
    def user_dir(self, user_id: str) -> Path:
        path = self.root / hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16]
        if not _is_within(path, self.root):
            raise DatasetStoreError(500, "Upload storage path check failed", "storage_error")
        return path

    def _dataset_dir(self, user_id: str, ds_id: str) -> Path:
        if not isinstance(ds_id, str) or not DATASET_ID_RE.match(ds_id):
            raise DatasetNotFound(ds_id)
        path = self.user_dir(user_id) / ds_id
        if not _is_within(path, self.root):
            raise DatasetNotFound(ds_id)
        return path

    @staticmethod
    def _original_name(record: DatasetRecord) -> str:
        return f"original{record.original_extension}"

    def file_paths(self, user_id: str, record: DatasetRecord) -> tuple[str | None, str | None]:
        """(analysis_path, model_path) for one of the user's records, after the root check."""
        base = self._dataset_dir(user_id, record.id)
        if record.kind == DatasetKind.TABLE:
            analysis_file = base / _ANALYSIS
            if _is_within(analysis_file, self.root) and analysis_file.exists():
                return str(analysis_file), None
        target = base / self._original_name(record)
        return (str(target) if _is_within(target, self.root) and target.exists() else None), None

    def sweep_orphans(self) -> None:
        """Remove .part files and manifest-less dataset dirs left by crashed uploads (older than an hour)."""
        cutoff = time.time() - _ORPHAN_AGE_S
        try:
            user_dirs = [p for p in self.root.iterdir() if p.is_dir()]
        except OSError:
            return
        for udir in user_dirs:
            for entry in udir.iterdir():
                try:
                    if entry.is_dir() and entry.name.endswith(".deleting"):
                        shutil.rmtree(entry, ignore_errors=True)
                        continue
                    if entry.stat().st_mtime > cutoff:
                        continue
                    if entry.is_dir() and not (entry / _MANIFEST).exists():
                        shutil.rmtree(entry, ignore_errors=True)
                    elif entry.is_file():
                        entry.unlink()
                    elif entry.is_dir():
                        for leftover in [*entry.glob("*.part"), *entry.glob("*.tmp")]:
                            leftover.unlink()
                except OSError as exc:
                    logger.debug("Orphan sweep skipped %s: %s", entry.name, exc)

    # -- quota ----------------------------------------------------------------
    # Only datasets the user can list (and so delete) count toward the quota: in-progress uploads, directories being
    # deleted and unreadable manifests do not, so a user can always free what is counted against them.
    @staticmethod
    def _dir_bytes(path: Path) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    def usage_bytes(self, user_id: str) -> int:
        return sum(self._dir_bytes(ds_dir) for ds_dir, _record in self._listed(user_id))

    def _committed_usage_bytes(self, user_id: str, own_dir: Path) -> int:
        """Listed datasets plus the upload being committed (whose manifest is not written yet)."""
        listed = [ds_dir for ds_dir, _record in self._listed(user_id) if ds_dir != own_dir]
        return sum(self._dir_bytes(d) for d in listed) + (self._dir_bytes(own_dir) if own_dir.is_dir() else 0)

    def _user_lock(self, user_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._user_locks.setdefault(self.user_dir(user_id).name, threading.Lock())

    # -- create ---------------------------------------------------------------
    async def create_from_stream(
        self,
        user_id: str,
        chunks: Chunks,
        filename: str,
        provenance: DatasetProvenanceIn,
    ) -> DatasetRecord:
        display_name = sanitize_display_name(filename)
        ext = extension_of(filename)
        kind = EXTENSION_KINDS.get(ext)
        if kind is None:
            raise DatasetStoreError(
                415,
                f"Unsupported file type '{ext or display_name}'. Upload table (.csv, .tsv, .xlsx, .json, .parquet), HDF5 (.h5, .hdf5), or MAT (.mat).",
                "unsupported_type",
            )
        if len(await asyncio.to_thread(self.list, user_id)) >= max_datasets():
            raise DatasetStoreError(507, f"Dataset limit reached ({max_datasets()} per user); delete one first.", "quota_exceeded")
        kind_cap = kind_cap_bytes(kind)
        remaining = total_cap_bytes() - await asyncio.to_thread(self.usage_bytes, user_id)

        ds_id = "ds_" + secrets.token_hex(6)
        ds_dir = self._dataset_dir(user_id, ds_id)
        ds_dir.mkdir(parents=True, exist_ok=False)
        part = ds_dir / _PART
        try:
            digest = hashlib.sha256()
            size = 0
            fh = await asyncio.to_thread(open, part, "wb")
            try:
                async for chunk in _iterate(chunks):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > kind_cap:
                        raise DatasetStoreError(
                            413, f"{kind.value} uploads are limited to {kind_cap // _MB} MB.", "too_large"
                        )
                    if size > remaining:
                        raise DatasetStoreError(
                            507, f"Upload storage quota ({total_cap_bytes() // _MB} MB per user) exceeded.", "quota_exceeded"
                        )
                    digest.update(chunk)
                    await asyncio.to_thread(fh.write, chunk)
            finally:
                await asyncio.to_thread(fh.close)
            if size == 0:
                raise DatasetStoreError(422, "The uploaded file is empty.", "empty_file")

            final = ds_dir / f"original{ext}"
            derived_sha: str | None = None
            try:
                if kind == DatasetKind.HDF5:
                    summary = await asyncio.to_thread(validate_hdf5, part)
                elif kind == DatasetKind.MAT:
                    summary = await asyncio.to_thread(validate_mat, part)
                elif kind == DatasetKind.TABLE:
                    out_h5ad = (ds_dir / _ANALYSIS) if ext in (".csv", ".tsv") else None
                    summary, derived_sha = await asyncio.to_thread(
                        validate_table, part, ext, provenance.table_orientation, out_h5ad
                    )
                else:
                    raise DatasetStoreError(415, f"Unsupported file type '{ext}'.", "unsupported_type")
            except ValidationFailure as exc:
                raise DatasetStoreError(422, exc.detail, exc.reason_code) from exc
            if kind == DatasetKind.TABLE and provenance.table_orientation is None and summary.table_orientation:
                provenance = provenance.model_copy(update={"table_orientation": summary.table_orientation})

            record = DatasetRecord(
                id=ds_id,
                kind=kind,
                display_name=display_name,
                original_extension=ext,
                size_bytes=size,
                sha256=digest.hexdigest(),
                derived_sha256=derived_sha,
                uploaded_at=datetime.now(UTC),
                provenance=provenance,
                validation=summary,
            )
            await asyncio.to_thread(self._commit, user_id, ds_dir, part, final, record)
            return record
        except BaseException:
            shutil.rmtree(ds_dir, ignore_errors=True)
            raise

    def _commit(self, user_id: str, ds_dir: Path, part: Path, final: Path, record: DatasetRecord) -> None:
        with self._user_lock(user_id):
            if len(self.list(user_id)) >= max_datasets():
                raise DatasetStoreError(507, f"Dataset limit reached ({max_datasets()} per user); delete one first.", "quota_exceeded")
            if self._committed_usage_bytes(user_id, ds_dir) > total_cap_bytes():
                raise DatasetStoreError(
                    507, f"Upload storage quota ({total_cap_bytes() // _MB} MB per user) exceeded.", "quota_exceeded"
                )
            os.replace(part, final)
            _write_json_atomic(ds_dir / _MANIFEST, record.model_dump(mode="json"))

    # -- read -----------------------------------------------------------------
    def _read_manifest(self, ds_dir: Path) -> DatasetRecord | None:
        try:
            with open(ds_dir / _MANIFEST, encoding="utf-8") as fh:
                return DatasetRecord.model_validate(json.load(fh))
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable dataset manifest in %s: %s", ds_dir.name, exc)
            return None

    def _listed(self, user_id: str) -> builtins.list[tuple[Path, DatasetRecord]]:
        """(directory, record) of every dataset whose manifest reads back, legacy kinds included."""
        udir = self.user_dir(user_id)
        if not udir.exists():
            return []
        out = []
        for entry in udir.iterdir():
            if entry.is_dir() and DATASET_ID_RE.match(entry.name) and (entry / _MANIFEST).exists():
                record = self._read_manifest(entry)
                if record is not None and record.id == entry.name:
                    out.append((entry, record))
        return out

    def list(self, user_id: str) -> builtins.list[DatasetRecord]:
        return sorted((r for _d, r in self._listed(user_id)), key=lambda r: r.uploaded_at, reverse=True)

    def get(self, user_id: str, ds_id: str) -> DatasetRecord:
        ds_dir = self._dataset_dir(user_id, ds_id)
        if not (ds_dir / _MANIFEST).exists():
            raise DatasetNotFound(ds_id)
        record = self._read_manifest(ds_dir)
        if record is None or record.id != ds_id:
            raise DatasetNotFound(ds_id)
        return record

    def resolve_for_user(self, user_id: str, ids: Iterable[str]) -> tuple[builtins.list[ResolvedAttachment], builtins.list[str]]:
        """Resolve ids owned by user_id; unknown and foreign ids produce the same error."""
        found: list[ResolvedAttachment] = []
        errors: list[str] = []
        for ds_id in ids:
            try:
                record = self.get(user_id, ds_id)
                if not record.analysable:
                    errors.append(
                        f"Attached dataset {record.id} is a legacy {record.legacy_kind or 'biomedical'} upload that "
                        "Tribos no longer analyses"
                    )
                    continue
                analysis_path, model_path = self.file_paths(user_id, record)
                if not (analysis_path or model_path):
                    raise DatasetNotFound(ds_id)
            except DatasetStoreError:
                errors.append(f"Attached dataset {str(ds_id)[:40]} not found")
                continue
            found.append(ResolvedAttachment(record=record, analysis_path=analysis_path, model_path=model_path))
        return found, errors

    # -- update / delete --------------------------------------------------------
    async def update_provenance(self, user_id: str, ds_id: str, provenance: DatasetProvenanceIn) -> DatasetRecord:
        snapshot = await asyncio.to_thread(self.get, user_id, ds_id)
        provenance = provenance.model_copy(update={"table_orientation": snapshot.provenance.table_orientation})
        return await asyncio.to_thread(self._write_provenance, user_id, ds_id, provenance)

    def _write_provenance(
        self, user_id: str, ds_id: str, provenance: DatasetProvenanceIn
    ) -> DatasetRecord:
        with self._user_lock(user_id):
            record = self.get(user_id, ds_id)
            previous = {
                "provenance": record.provenance.model_dump(mode="json"),
            }
            history = list(record.provenance_history) + [
                {"changed_at": datetime.now(UTC).isoformat(), "previous": previous}
            ]
            updated = record.model_copy(update={"provenance": provenance, "provenance_history": history[-50:]})
            updated = DatasetRecord.model_validate(updated.model_dump(mode="json"))
            _write_json_atomic(self._dataset_dir(user_id, ds_id) / _MANIFEST, updated.model_dump(mode="json"))
            return updated

    def delete(self, user_id: str, ds_id: str) -> None:
        self.get(user_id, ds_id)
        ds_dir = self._dataset_dir(user_id, ds_id)
        doomed = ds_dir.with_name(f"{ds_id}.{secrets.token_hex(3)}.deleting")
        try:
            os.replace(ds_dir, doomed)
        except PermissionError as exc:
            raise DatasetStoreError(409, "The dataset is in use by a running analysis; try again shortly.", "in_use") from exc
        shutil.rmtree(doomed, ignore_errors=True)


_STORE: DatasetStore | None = None
_STORE_LOCK = threading.Lock()


def get_dataset_store() -> DatasetStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = DatasetStore()
        return _STORE


def existing_dataset_store() -> DatasetStore | None:
    """The store if anything was ever uploaded (or it is already open); never creates the upload root."""
    if _STORE is not None or default_upload_root().exists():
        return get_dataset_store()
    return None


def reset_dataset_store() -> None:
    """Forget the singleton so the next call re-reads TRIBOS_UPLOAD_ROOT (tests)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = None
