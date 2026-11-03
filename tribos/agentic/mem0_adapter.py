"""
Actual Mem0 SDK memory adapter and durable background event processor.
Integrates `mem0ai` SDK with explicit persistent Qdrant vector storage,
strict user and project scope isolation, companion metadata tracking,
authoritative invalidation, and an outage-resilient durable event queue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid

# Disable PostHog telemetry in mem0 unless the operator chose otherwise (no process-wide override).
os.environ.setdefault("MEM0_TELEMETRY", "False")

logger = logging.getLogger(__name__)

MEM0_DEFAULT_COLLECTION = "tribos_memories"


@dataclass
class Mem0Provenance:
    memory_type: str = "user_preference"  # user_preference, project_fact, instruction, hypothesis, verified_result
    origin: str = "user"
    source_task_id: str | None = None
    source_run_id: str | None = None
    source_result_id: str | None = None
    verification_status: str = "unverified"  # verified, unverified, contradicted, invalidated
    recorded_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    valid_from: str | None = None
    invalid_at: str | None = None
    artifact_references: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Mem0Adapter:
    """
    Adapter around the actual mem0ai SDK with persistent storage, authoritative
    companion metadata for status/invalidation, and strict user/project scope isolation.
    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        embedder_provider: str | None = None,
        llm_provider: str | None = None,
        custom_embedder: Any = None,
        custom_llm: Any = None,
    ) -> None:
        from ..config.settings import get_bool, get_path, get_str

        self.enabled = get_bool("TRIBOS_MEM0_ENABLED")
        configured_dir = storage_dir or get_path("TRIBOS_MEM0_DIR")
        if not configured_dir:
            from ..config.settings import get_path as _gp

            base_data = _gp("TRIBOS_DATA_DIR") or (Path.cwd() / ".tribos_memory")
            configured_dir = Path(base_data) / "mem0"
        self.storage_dir = Path(configured_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.qdrant_dir = self.storage_dir / "qdrant"
        self.qdrant_dir.mkdir(parents=True, exist_ok=True)
        self.history_db = str(self.storage_dir / "history.db")
        self.companion_db = str(self.storage_dir / "companion.db")

        self.embedder_provider = embedder_provider or get_str("TRIBOS_MEM0_EMBEDDER_PROVIDER") or "mock"
        self.llm_provider = llm_provider or get_str("TRIBOS_MEM0_LLM_PROVIDER") or "mock"
        self._custom_embedder = custom_embedder
        self._custom_llm = custom_llm
        self._memory: Any = None
        self._lock = threading.Lock()
        self._is_available = True

        self._init_companion_db()

    def _init_companion_db(self) -> None:
        with sqlite3.connect(self.companion_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_companion (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'project_fact',
                    status TEXT NOT NULL DEFAULT 'active',
                    invalidation_reason TEXT,
                    invalidated_at REAL,
                    superseded_by TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_comp_owner ON memory_companion (user_id, project_id, status)")

    def _build_memory_instance(self) -> Any:
        os.environ.setdefault("MEM0_DIR", str(self.storage_dir))  # read by mem0 at import (config.json location)
        from mem0 import Memory

        cfg: dict[str, Any] = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(self.qdrant_dir),
                    "collection_name": MEM0_DEFAULT_COLLECTION,
                    "on_disk": True,
                },
            },
            "history_db_path": self.history_db,
        }

        # Embedder configuration
        if self._custom_embedder is not None:
            cfg["embedder"] = {
                "provider": "langchain",
                "config": {"model": self._custom_embedder},
            }
            if hasattr(self._custom_embedder, "size"):
                cfg["vector_store"]["config"]["embedding_model_dims"] = getattr(self._custom_embedder, "size")
        elif self.embedder_provider == "mock":
            from langchain_core.embeddings import FakeEmbeddings

            fake_emb = FakeEmbeddings(size=64)
            cfg["embedder"] = {"provider": "langchain", "config": {"model": fake_emb}}
            cfg["vector_store"]["config"]["embedding_model_dims"] = 64
        elif self.embedder_provider == "huggingface":
            cfg["embedder"] = {
                "provider": "huggingface",
                "config": {"model": "multi-qa-MiniLM-L6-cos-v1"},
            }
        else:
            cfg["embedder"] = {
                "provider": self.embedder_provider,
                "config": {},
            }

        # LLM configuration
        if self._custom_llm is not None:
            cfg["llm"] = {
                "provider": "langchain",
                "config": {"model": self._custom_llm},
            }
        elif self.llm_provider == "mock":
            from langchain_core.language_models.fake_chat_models import FakeListChatModel

            cfg["llm"] = {
                "provider": "langchain",
                "config": {"model": FakeListChatModel(responses=["OK"])},
            }
        else:
            cfg["llm"] = {
                "provider": self.llm_provider,
                "config": {},
            }

        # mem0 keeps an extra embedded Qdrant ("migrations_qdrant") under its own directory, ~/.mem0 by default.
        # Point it at this adapter's storage, so nothing is written to the user's home and two adapters with
        # different storage never contend for one Qdrant lock (AUDIT-012).
        import mem0.memory.main as _mem0_main

        _mem0_main.mem0_dir = str(self.storage_dir)
        return Memory.from_config(cfg)

    def get_memory(self) -> Any:
        with self._lock:
            if not self._is_available:
                raise RuntimeError("Mem0 memory service is currently unavailable.")
            if self._memory is None:
                self._memory = self._build_memory_instance()
            return self._memory

    def set_available(self, available: bool) -> None:
        """Simulate or control service availability (for outage testing)."""
        with self._lock:
            self._is_available = available

    def _require_scope(self, user_id: str, project_id: str) -> None:
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id must be a non-empty string")
        if not project_id or not str(project_id).strip():
            raise ValueError("project_id must be a non-empty string")

    def _get_companion_entry(self, memory_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.companion_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM memory_companion WHERE memory_id = ?", (memory_id,)).fetchone()
            return dict(row) if row else None

    def add(
        self,
        content: str | list[dict[str, Any]],
        user_id: str,
        project_id: str,
        provenance: Mem0Provenance | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> dict[str, Any]:
        """Store a new memory strictly scoped to authenticated user_id and project_id."""
        self._require_scope(user_id, project_id)
        mem = self.get_memory()
        meta = metadata.copy() if metadata else {}
        meta["project_id"] = str(project_id)
        if provenance:
            meta.update(provenance.to_dict())

        res = mem.add(
            content,
            user_id=str(user_id),
            metadata=meta,
            infer=infer,
        )

        # Record into companion database for authoritative state tracking
        now = time.time()
        created_items = res.get("results") if isinstance(res, dict) else (res if isinstance(res, list) else [])
        with sqlite3.connect(self.companion_db) as conn:
            for item in created_items:
                mid = item.get("id") or item.get("memory_id")
                if mid:
                    m_type = meta.get("memory_type", "project_fact")
                    conn.execute("""
                        INSERT OR REPLACE INTO memory_companion
                        (memory_id, user_id, project_id, memory_type, status, invalidation_reason, invalidated_at, superseded_by, created_at, updated_at, metadata_json)
                        VALUES (?, ?, ?, ?, 'active', NULL, NULL, NULL, ?, ?, ?)
                    """, (str(mid), str(user_id), str(project_id), m_type, now, now, json.dumps(meta, default=str)))

        return res

    def search(
        self,
        query: str,
        user_id: str,
        project_id: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        include_invalid: bool = False,
    ) -> list[dict[str, Any]]:
        """Search memories strictly scoped to user_id and project_id, filtering invalidated records."""
        self._require_scope(user_id, project_id)
        mem = self.get_memory()

        flt = filters.copy() if filters else {}
        flt["project_id"] = str(project_id)

        raw = mem.search(
            query=query,
            user_id=str(user_id),
            limit=limit * 2,
            filters=flt,
        )
        results = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])

        # Fetch companion states for invalidation and ownership check
        with sqlite3.connect(self.companion_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memory_companion WHERE user_id = ? AND project_id = ?",
                (str(user_id), str(project_id)),
            ).fetchall()
            companion_map = {r["memory_id"]: dict(r) for r in rows}

        out = []
        for r in results:
            r_meta = r.get("metadata") or {}
            # Strict ownership verification
            if r.get("user_id") != str(user_id) or r_meta.get("project_id") != str(project_id):
                continue

            mid = r.get("id") or r.get("memory_id")
            comp = companion_map.get(mid)
            if comp:
                if not include_invalid and comp["status"] != "active":
                    continue
                r["verification_status"] = comp["status"]
                r["invalidation_reason"] = comp["invalidation_reason"]
            elif not include_invalid and r_meta.get("verification_status") == "invalidated":
                continue

            out.append(r)
            if len(out) >= limit:
                break

        return out

    def get(self, memory_id: str, user_id: str, project_id: str, include_invalid: bool = False) -> dict[str, Any] | None:
        """Fetch memory with strict user and project ownership verification."""
        self._require_scope(user_id, project_id)
        comp = self._get_companion_entry(memory_id)
        if comp:
            if comp["user_id"] != str(user_id) or comp["project_id"] != str(project_id):
                raise PermissionError("Access denied: memory belongs to another user or project.")
            if not include_invalid and comp["status"] != "active":
                return None

        mem = self.get_memory()
        res = mem.get(memory_id)
        if not res:
            return None

        if comp:
            res["user_id"] = comp["user_id"]
            if not res.get("metadata"):
                res["metadata"] = {}
            res["metadata"]["project_id"] = comp["project_id"]
            res["companion_status"] = comp["status"]
            res["invalidation_reason"] = comp["invalidation_reason"]
            return res

        r_meta = res.get("metadata") or {}
        if res.get("user_id") != str(user_id) or r_meta.get("project_id") != str(project_id):
            raise PermissionError("Access denied: memory belongs to another user or project.")
        return res

    def get_all(
        self, user_id: str, project_id: str, limit: int = 100, include_invalid: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieve all memories for a user and project with invalidation filtering."""
        self._require_scope(user_id, project_id)
        mem = self.get_memory()
        filters = {"project_id": str(project_id)}
        raw = mem.get_all(user_id=str(user_id), filters=filters, limit=limit * 2)
        results = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])

        with sqlite3.connect(self.companion_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memory_companion WHERE user_id = ? AND project_id = ?",
                (str(user_id), str(project_id)),
            ).fetchall()
            companion_map = {r["memory_id"]: dict(r) for r in rows}

        out = []
        for r in results:
            r_meta = r.get("metadata") or {}
            if r.get("user_id") != str(user_id) or r_meta.get("project_id") != str(project_id):
                continue
            mid = r.get("id") or r.get("memory_id")
            comp = companion_map.get(mid)
            if comp and not include_invalid and comp["status"] != "active":
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def update(
        self, memory_id: str, data: str | dict[str, Any], user_id: str, project_id: str
    ) -> dict[str, Any]:
        """Update memory content with strict ownership verification."""
        self._require_scope(user_id, project_id)
        existing = self.get(memory_id, user_id=user_id, project_id=project_id, include_invalid=True)
        if not existing:
            raise PermissionError("Access denied or memory not found.")

        mem = self.get_memory()
        res = mem.update(memory_id, data)

        with sqlite3.connect(self.companion_db) as conn:
            conn.execute(
                "UPDATE memory_companion SET updated_at = ? WHERE memory_id = ?",
                (time.time(), str(memory_id)),
            )
        return res

    def delete(self, memory_id: str, user_id: str, project_id: str) -> bool:
        """Delete memory with strict ownership verification."""
        self._require_scope(user_id, project_id)
        existing = self.get(memory_id, user_id=user_id, project_id=project_id, include_invalid=True)
        if not existing:
            raise PermissionError("Access denied or memory not found.")

        mem = self.get_memory()
        res = mem.delete(memory_id)

        with sqlite3.connect(self.companion_db) as conn:
            conn.execute("DELETE FROM memory_companion WHERE memory_id = ?", (str(memory_id),))
        return bool(res)

    def history(self, memory_id: str, user_id: str, project_id: str) -> list[dict[str, Any]]:
        """Retrieve memory history with ownership verification."""
        self._require_scope(user_id, project_id)
        existing = self.get(memory_id, user_id=user_id, project_id=project_id, include_invalid=True)
        if not existing:
            raise PermissionError("Access denied or memory not found.")

        mem = self.get_memory()
        raw = mem.history(memory_id)
        return raw if isinstance(raw, list) else []

    def invalidate(
        self, memory_id: str, reason: str, user_id: str, project_id: str, superseded_by: str | None = None
    ) -> dict[str, Any]:
        """Authoritatively invalidate a memory in companion store and update Mem0 content."""
        self._require_scope(user_id, project_id)
        existing = self.get(memory_id, user_id=user_id, project_id=project_id, include_invalid=True)
        if not existing:
            raise PermissionError(f"Memory {memory_id} not found or access denied.")

        now = time.time()
        with sqlite3.connect(self.companion_db) as conn:
            conn.execute("""
                UPDATE memory_companion
                SET status = 'invalidated', invalidation_reason = ?, invalidated_at = ?, superseded_by = ?, updated_at = ?
                WHERE memory_id = ? AND user_id = ? AND project_id = ?
            """, (reason, now, superseded_by, now, str(memory_id), str(user_id), str(project_id)))

        text = existing.get("memory") or str(existing.get("data") or "")
        updated_text = f"[INVALIDATED: {reason}] {text}"
        try:
            mem = self.get_memory()
            mem.update(memory_id, updated_text)
        except Exception as exc:
            logger.warning("Mem0 text update during invalidation: %s", exc)

        return {
            "memory_id": memory_id,
            "status": "invalidated",
            "invalidation_reason": reason,
            "invalidated_at": now,
            "superseded_by": superseded_by,
        }


class DurableMemoryQueue:
    """
    Persistent SQLite queue for asynchronous, reliable Mem0 memory writes.
    Provides atomic transactional claims, lease-based concurrent consumer handling,
    deduplication, exponential backoff, restart recovery, and background processing.
    """

    ALLOWED_OPERATIONS = frozenset({"add", "update", "delete", "invalidate"})

    def __init__(self, db_path: str | Path, adapter: Mem0Adapter) -> None:
        self.db_path = str(db_path)
        self.adapter = adapter
        self._dispatcher_thread: threading.Thread | None = None
        self._dispatcher_stop = threading.Event()
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    lease_id TEXT,
                    lease_expires_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    next_retry_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_claim ON memory_events (state, next_retry_at, lease_expires_at)")

    def enqueue(
        self,
        user_id: str,
        project_id: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str:
        """Add an event to the queue with operation validation. Returns event_id."""
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id must be provided")
        if not project_id or not str(project_id).strip():
            raise ValueError("project_id must be provided")
        if operation not in self.ALLOWED_OPERATIONS:
            raise ValueError(f"Invalid operation '{operation}'. Must be one of {sorted(self.ALLOWED_OPERATIONS)}")

        payload_str = json.dumps(payload, sort_keys=True, default=str)
        if not idempotency_key:
            raw = f"{user_id}:{project_id}:{operation}:{payload_str}"
            event_id = f"ev_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"
        else:
            event_id = idempotency_key

        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO memory_events
                (event_id, user_id, project_id, operation, payload_json, state, attempts, error, lease_id, lease_expires_at, created_at, updated_at, next_retry_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, ?, ?, ?)
            """, (event_id, str(user_id), str(project_id), operation, payload_str, now, now, now))
        return event_id

    def claim_batch(self, max_batch: int = 10, lease_duration_s: float = 30.0) -> tuple[str, list[dict[str, Any]]]:
        """Atomically claim up to max_batch events using a transactional lease."""
        now = time.time()
        lease_id = uuid.uuid4().hex[:12]
        expires_at = now + lease_duration_s

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Claim rows atomically
            conn.execute("""
                UPDATE memory_events
                SET state = 'processing', lease_id = ?, lease_expires_at = ?, updated_at = ?
                WHERE event_id IN (
                    SELECT event_id FROM memory_events
                    WHERE (state = 'pending' AND next_retry_at <= ?)
                       OR (state = 'processing' AND lease_expires_at < ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                )
            """, (lease_id, expires_at, now, now, now, max_batch))

            rows = conn.execute("SELECT * FROM memory_events WHERE lease_id = ? AND state = 'processing'", (lease_id,)).fetchall()
            return lease_id, [dict(r) for r in rows]

    def process_pending(self, max_batch: int = 10) -> int:
        """Process pending events using atomic claims and error backoff."""
        lease_id, claimed = self.claim_batch(max_batch=max_batch)
        if not claimed:
            return 0

        processed = 0
        for r in claimed:
            event_id = r["event_id"]
            user_id = r["user_id"]
            project_id = r["project_id"]
            op = r["operation"]
            payload = json.loads(r["payload_json"])
            attempts = r["attempts"] + 1

            try:
                if op == "add":
                    prov_dict = payload.get("provenance")
                    prov = Mem0Provenance(**prov_dict) if prov_dict else None
                    self.adapter.add(
                        content=payload.get("content", ""),
                        user_id=user_id,
                        project_id=project_id,
                        provenance=prov,
                        metadata=payload.get("metadata"),
                        infer=payload.get("infer", False),
                    )
                elif op == "update":
                    self.adapter.update(
                        memory_id=payload["memory_id"],
                        data=payload["data"],
                        user_id=user_id,
                        project_id=project_id,
                    )
                elif op == "delete":
                    self.adapter.delete(
                        memory_id=payload["memory_id"],
                        user_id=user_id,
                        project_id=project_id,
                    )
                elif op == "invalidate":
                    self.adapter.invalidate(
                        memory_id=payload["memory_id"],
                        reason=payload.get("reason", "manual invalidation"),
                        user_id=user_id,
                        project_id=project_id,
                        superseded_by=payload.get("superseded_by"),
                    )

                # Mark delivered
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        UPDATE memory_events
                        SET state = 'delivered', attempts = ?, lease_id = NULL, lease_expires_at = NULL, updated_at = ?
                        WHERE event_id = ?
                    """, (attempts, time.time(), event_id))
                processed += 1
            except Exception as exc:
                logger.warning("Mem0 event %s dispatch error (attempt %d): %s", event_id, attempts, exc)
                delay = min(300.0, 2.0 ** attempts)
                new_state = "pending" if attempts < 5 else "failed"
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        UPDATE memory_events
                        SET state = ?, attempts = ?, error = ?, lease_id = NULL, lease_expires_at = NULL, updated_at = ?, next_retry_at = ?
                        WHERE event_id = ?
                    """, (new_state, attempts, str(exc)[:400], time.time(), time.time() + delay, event_id))

        return processed

    # Alias for process_pending
    dispatch_pending = process_pending

    def start_background_dispatcher(self, interval_s: float = 2.0) -> None:
        """Start lifecycle-managed background dispatcher thread."""
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            return
        self._dispatcher_stop.clear()

        def _run():
            while not self._dispatcher_stop.is_set():
                try:
                    self.process_pending(max_batch=10)
                except Exception as exc:
                    logger.debug("Background memory dispatcher loop: %s", exc)
                self._dispatcher_stop.wait(interval_s)

        self._dispatcher_thread = threading.Thread(target=_run, name="mem0-dispatcher", daemon=True)
        self._dispatcher_thread.start()

    def stop_background_dispatcher(self) -> None:
        """Stop background dispatcher thread."""
        self._dispatcher_stop.set()
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            self._dispatcher_thread.join(timeout=3.0)

    def list_events(self, user_id: str, project_id: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM memory_events WHERE user_id = ?"
        params: list[Any] = [user_id]
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY created_at DESC LIMIT 100"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]


_ADAPTER_INSTANCE: Mem0Adapter | None = None
_QUEUE_INSTANCE: DurableMemoryQueue | None = None


def get_mem0_adapter() -> Mem0Adapter:
    global _ADAPTER_INSTANCE
    if _ADAPTER_INSTANCE is None:
        _ADAPTER_INSTANCE = Mem0Adapter()
    return _ADAPTER_INSTANCE


def get_memory_queue() -> DurableMemoryQueue:
    global _QUEUE_INSTANCE
    if _QUEUE_INSTANCE is None:
        adapter = get_mem0_adapter()
        db_path = adapter.storage_dir / "memory_events.db"
        _QUEUE_INSTANCE = DurableMemoryQueue(db_path, adapter)
    return _QUEUE_INSTANCE
