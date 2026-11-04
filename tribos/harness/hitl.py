"""Artifact-Level Human-in-the-Loop (HITL) Sign-Off Harness for Tribos.

Closes:
- F-19 / P2.6: Artifact and claim-level sign-off workflow
- Records certified engineer digital signatures, rework requests, and peer-review annotations
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArtifactReview:
    id: str
    artifact_id: str
    project_id: str
    reviewer_id: str
    action: str  # approved | rejected | rework_requested | annotated
    comments: str
    created_at: float
    signature_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactHITLManager:
    """Manages human-in-the-loop review at the specific artifact and claim level."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".tribos_memory"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "hitl_reviews.sqlite3")
        else:
            self.db_path = str(db_path)
        self._key_path = Path(self.db_path).with_name("hitl_signing.key")
        self._init_db()

    def _signing_key(self) -> bytes:
        """A per-installation HMAC key kept beside the database (created once, owner-readable only)."""
        try:
            return self._key_path.read_bytes()
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(key)
            return key
        except FileExistsError:  # pragma: no cover - lost a creation race
            return self._key_path.read_bytes()

    def _signature(self, rev: ArtifactReview) -> str:
        """HMAC-SHA256 over every field of the review, including the signed artifact content hash, so a stored
        review cannot be edited or forged without the server key."""
        payload = json.dumps(
            {
                "id": rev.id,
                "artifact_id": rev.artifact_id,
                "project_id": rev.project_id,
                "reviewer_id": rev.reviewer_id,
                "action": rev.action,
                "comments": rev.comments,
                "created_at": rev.created_at,
                "content_sha256": (rev.metadata or {}).get("content_sha256"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hmac.new(self._signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_signature(self, rev: ArtifactReview) -> bool:
        return hmac.compare_digest(self._signature(rev), rev.signature_hash)

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifact_reviews (
                    id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    comments TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    signature_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_rev_art ON artifact_reviews(artifact_id);
                CREATE INDEX IF NOT EXISTS idx_rev_proj ON artifact_reviews(project_id);
                """
            )

    def sign_off_artifact(
        self,
        artifact_id: str,
        project_id: str,
        reviewer_id: str,
        action: str,  # approved | rejected | rework_requested | annotated
        comments: str = "",
        metadata: dict[str, Any] | None = None,
        content_sha256: str | None = None,
    ) -> ArtifactReview:
        """Record a sign-off or rework request. `content_sha256` binds the review to the exact artifact content
        that was reviewed; without it the review names the artifact id only (recorded as unbound)."""
        review_id = f"hitl_{uuid.uuid4().hex[:12]}"
        now = time.time()
        meta = dict(metadata or {})
        meta["content_sha256"] = content_sha256
        meta["content_bound"] = bool(content_sha256)

        rev = ArtifactReview(
            id=review_id,
            artifact_id=artifact_id,
            project_id=project_id,
            reviewer_id=reviewer_id,
            action=action,
            comments=comments,
            created_at=now,
            signature_hash="",
            metadata=meta,
        )
        rev.signature_hash = self._signature(rev)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO artifact_reviews (id, artifact_id, project_id, reviewer_id, action, comments, created_at, signature_hash, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev.id,
                    rev.artifact_id,
                    rev.project_id,
                    rev.reviewer_id,
                    rev.action,
                    rev.comments,
                    rev.created_at,
                    rev.signature_hash,
                    json.dumps(rev.metadata),
                ),
            )
        return rev

    def list_artifact_reviews(self, artifact_id: str) -> list[ArtifactReview]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM artifact_reviews WHERE artifact_id = ? ORDER BY created_at ASC",
                (artifact_id,),
            ).fetchall()
            return [
                ArtifactReview(
                    id=r["id"],
                    artifact_id=r["artifact_id"],
                    project_id=r["project_id"],
                    reviewer_id=r["reviewer_id"],
                    action=r["action"],
                    comments=r["comments"],
                    created_at=r["created_at"],
                    signature_hash=r["signature_hash"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]
