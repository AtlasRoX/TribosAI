"""Session Memory: Tier 2 server-side conversation store and answer version tree.

Addresses:
- F-17: Server-side conversation sessions (moving chats from browser localStorage to project store)
- F-16: Answer versioning tree, design branching (Rev A / Rev B), and visual AST/line diffing
- Scoped user directives (current_turn, session, project_profile)
"""

from __future__ import annotations

import difflib
import json
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConversationTurn:
    id: str
    thread_id: str
    role: str  # user | assistant | system | tool
    content: str
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerRevision:
    id: str
    project_id: str
    version_number: int
    branch_name: str
    content: str
    summary: str
    created_at: float
    parent_id: str | None = None
    author: str = "agent"
    status: str = "draft"  # draft | reviewed | approved | rejected
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionMemory:
    """Server-side session manager and answer version tree."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".tribos_memory"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "session_memory.sqlite3")
        else:
            self.db_path = str(db_path)
        self._init_db()

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
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS answer_revisions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    branch_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    parent_id TEXT,
                    created_at REAL NOT NULL,
                    author TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS directives (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL, -- current_turn | session | project_profile
                    directive_text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_turns_thread ON turns(thread_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_revisions_proj ON answer_revisions(project_id, version_number);
                CREATE INDEX IF NOT EXISTS idx_directives_proj ON directives(project_id, scope, active);
                """
            )

    # Thread / Conversation Operations (F-17) --------------------------------------------------
    def create_thread(
        self, project_id: str, title: str, metadata: dict[str, Any] | None = None
    ) -> str:
        tid = f"thrd_{uuid.uuid4().hex[:16]}"
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO threads (id, project_id, title, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (tid, project_id, title, now, now, json.dumps(metadata or {})),
            )
        return tid

    def add_turn(
        self, thread_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> str:
        turn_id = f"turn_{uuid.uuid4().hex[:16]}"
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO turns (id, thread_id, role, content, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (turn_id, thread_id, role, content, now, json.dumps(metadata or {})),
            )
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        return turn_id

    def get_thread_turns(self, thread_id: str, limit: int = 50) -> list[ConversationTurn]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE thread_id = ? ORDER BY created_at ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
            return [
                ConversationTurn(
                    id=r["id"],
                    thread_id=r["thread_id"],
                    role=r["role"],
                    content=r["content"],
                    created_at=r["created_at"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]

    def list_project_threads(self, project_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "project_id": r["project_id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "metadata": json.loads(r["metadata_json"]),
                }
                for r in rows
            ]

    # Answer Versioning & Tree (F-16) ---------------------------------------------------------
    def create_revision(
        self,
        project_id: str,
        content: str,
        summary: str = "",
        branch_name: str = "main",
        parent_id: str | None = None,
        author: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> AnswerRevision:
        rev_id = f"rev_{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._get_conn() as conn:
            last = conn.execute(
                "SELECT MAX(version_number) FROM answer_revisions WHERE project_id = ? AND branch_name = ?",
                (project_id, branch_name),
            ).fetchone()[0]
            v_num = (last or 0) + 1
            rev = AnswerRevision(
                id=rev_id,
                project_id=project_id,
                version_number=v_num,
                branch_name=branch_name,
                content=content,
                summary=summary or f"Revision {v_num} on {branch_name}",
                created_at=now,
                parent_id=parent_id,
                author=author,
                status="draft",
                metadata=metadata or {},
            )
            conn.execute(
                """
                INSERT INTO answer_revisions (id, project_id, version_number, branch_name, content, summary, parent_id, created_at, author, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev.id,
                    rev.project_id,
                    rev.version_number,
                    rev.branch_name,
                    rev.content,
                    rev.summary,
                    rev.parent_id,
                    rev.created_at,
                    rev.author,
                    rev.status,
                    json.dumps(rev.metadata),
                ),
            )
            return rev

    def get_revision(self, revision_id: str) -> AnswerRevision | None:
        with self._get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM answer_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            if not r:
                return None
            return AnswerRevision(
                id=r["id"],
                project_id=r["project_id"],
                version_number=r["version_number"],
                branch_name=r["branch_name"],
                content=r["content"],
                summary=r["summary"],
                created_at=r["created_at"],
                parent_id=r["parent_id"],
                author=r["author"],
                status=r["status"],
                metadata=json.loads(r["metadata_json"]),
            )

    def list_revisions(
        self, project_id: str, branch_name: str | None = None
    ) -> list[AnswerRevision]:
        with self._get_conn() as conn:
            if branch_name:
                rows = conn.execute(
                    "SELECT * FROM answer_revisions WHERE project_id = ? AND branch_name = ? ORDER BY version_number ASC",
                    (project_id, branch_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM answer_revisions WHERE project_id = ? ORDER BY created_at ASC",
                    (project_id,),
                ).fetchall()
            return [
                AnswerRevision(
                    id=r["id"],
                    project_id=r["project_id"],
                    version_number=r["version_number"],
                    branch_name=r["branch_name"],
                    content=r["content"],
                    summary=r["summary"],
                    created_at=r["created_at"],
                    parent_id=r["parent_id"],
                    author=r["author"],
                    status=r["status"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]

    def diff_revisions(self, rev_id_a: str, rev_id_b: str) -> dict[str, Any]:
        """Compute visual line-by-line and semantic difference between two answer revisions."""
        rev_a = self.get_revision(rev_id_a)
        rev_b = self.get_revision(rev_id_b)
        if not rev_a or not rev_b:
            raise ValueError("One or both revisions not found")

        lines_a = rev_a.content.splitlines(keepends=True)
        lines_b = rev_b.content.splitlines(keepends=True)
        unified_diff = "".join(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=f"rev_{rev_a.version_number}",
                tofile=f"rev_{rev_b.version_number}",
            )
        )

        return {
            "rev_a": asdict(rev_a),
            "rev_b": asdict(rev_b),
            "unified_diff": unified_diff,
            "has_changes": unified_diff.strip() != "",
        }

    # Directives -------------------------------------------------------------------------------
    def add_directive(self, project_id: str, text: str, scope: str = "project_profile") -> str:
        d_id = f"dir_{uuid.uuid4().hex[:12]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO directives (id, project_id, scope, directive_text, created_at, active) VALUES (?, ?, ?, ?, ?, 1)",
                (d_id, project_id, scope, text.strip(), time.time()),
            )
        return d_id

    def get_active_directives(self, project_id: str, scope: str | None = None) -> list[str]:
        with self._get_conn() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT directive_text FROM directives WHERE project_id = ? AND scope = ? AND active = 1 ORDER BY created_at ASC",
                    (project_id, scope),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT directive_text FROM directives WHERE project_id = ? AND active = 1 ORDER BY created_at ASC",
                    (project_id,),
                ).fetchall()
            return [r[0] for r in rows]
