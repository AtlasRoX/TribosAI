"""Where requested files live: one folder per file under `<TRIBOS_FILES_DIR>` (default `<data>/files`), owned by the
user who asked. Files older than TRIBOS_FILES_TTL_DAYS (default 30) are removed when the store opens."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

FILE_ID_RE = re.compile(r"^f_[0-9a-f]{20}$")
MAX_FILE_BYTES = 25 * 1024 * 1024


def default_files_dir() -> str:
    env = os.getenv("TRIBOS_FILES_DIR")
    if env:
        return env
    from ..utils.paths import data_dir

    data = data_dir("files")
    if data is not None:
        return str(data)
    if "PYTEST_CURRENT_TEST" in os.environ:
        return os.path.join(tempfile.gettempdir(), "tribos_files_pytest")
    return str(Path(__file__).resolve().parents[2] / "data" / "files")


def _owner(user_id: str) -> str:
    return hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:24]


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(name or "file")).strip(".-")
    return name[:120] or "file"


class FileStore:
    def __init__(self, root: str | None = None, ttl_days: float | None = None) -> None:
        self.root = Path(root or default_files_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        try:
            ttl = float(os.getenv("TRIBOS_FILES_TTL_DAYS") or 30) if ttl_days is None else ttl_days
        except ValueError:
            ttl = 30.0
        if ttl > 0:
            self.purge(ttl)

    def save(self, user_id: str, name: str, data: bytes, media_type: str) -> dict[str, Any]:
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        file_id = f"f_{uuid.uuid4().hex[:20]}"
        folder = self.root / file_id
        with self._lock:
            folder.mkdir(parents=True)
            safe = _safe_name(name)
            (folder / safe).write_bytes(data)
            meta = {"id": file_id, "name": safe, "media_type": media_type, "size": len(data), "owner": _owner(user_id),
                    "created_at": time.time()}
            (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def load(self, user_id: str, file_id: str) -> tuple[Path, dict[str, Any]] | None:
        """(path, metadata) of a file the user owns, else None (another user's file is "not found")."""
        if not FILE_ID_RE.match(file_id or ""):
            return None
        folder = self.root / file_id
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if meta.get("owner") != _owner(user_id):
            return None
        path = folder / meta["name"]
        return (path, meta) if path.is_file() else None

    def purge(self, ttl_days: float) -> int:
        cutoff = time.time() - ttl_days * 86400
        removed = 0
        for folder in self.root.glob("f_*"):
            try:
                if folder.stat().st_mtime < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed


_STORE: FileStore | None = None
_STORE_LOCK = threading.Lock()


def get_file_store() -> FileStore:
    global _STORE
    with _STORE_LOCK:
        root = str(Path(default_files_dir()).resolve())
        if _STORE is None or str(_STORE.root) != root:
            _STORE = FileStore(root)
        return _STORE


__all__ = ["FILE_ID_RE", "FileStore", "default_files_dir", "get_file_store"]
