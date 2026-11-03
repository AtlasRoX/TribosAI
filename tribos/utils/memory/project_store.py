"""
Project memory store (feature 16): research projects and a bi-temporal fact graph, one SQLite file.

- Zep / Graphiti (Rasmussen et al. 2025, arXiv:2501.13956): each fact is an edge (subject, relation, object)
  with bi-temporal stamps: `valid_from`/`invalid_at` say when it held, `recorded_at` when it was ingested. A
  contradicting new fact invalidates the old one (invalid_at, superseded_by) instead of deleting it, so a
  project keeps the history of how its findings were revised.
- Mem0 (Chhikara et al. 2025, arXiv:2504.19413): extract, then decide ADD, UPDATE, INVALIDATE or NOOP against
  the existing facts. Here the decision is deterministic (see `upsert_facts`).
- HippoRAG (Gutierrez et al., NeurIPS 2024, arXiv:2405.14831): retrieval by Personalized PageRank over the fact
  graph (nodes = subjects and objects, edges = valid facts), seeded with the query's entities.
- Generative Agents (Park et al., UIST 2023, arXiv:2304.03442): the final ranking is recency x importance x
  relevance (each min-max normalised and summed with equal weights, as in the paper).
- MemGPT (Packer et al. 2023, arXiv:2310.08560): the top facts are paged into the prompt (working memory);
  everything else stays in this archival store and is reachable through the projects API.
- A-MEM (Xu et al., NeurIPS 2025, arXiv:2502.12110): facts that share an entity are linked notes; the graph
  walk is what follows those links.

Every read and write is scoped to one user. Ids: projects `prj_<16 alphanumerics>`, facts `fct_<16 hex>`.
Location: `TRIBOS_PROJECTS_DIR`, else next to the clinical memory store (`TRIBOS_MEMORY_DIR`, else
`<workspace>/.tribos_memory`); pytest runs without either use a temporary directory.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sqlite3
import string
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

PROJECT_ID_RE = re.compile(r"^prj_[A-Za-z0-9]{6,40}$")
FACT_ID_RE = re.compile(r"^fct_[0-9a-f]{16}$")

# Relations with one current object per subject: a new object contradicts the old one.
SINGLE_VALUED_RELATIONS = frozenset({"classification", "preferred_model"})
# Relations whose (subject, object) pair carries one current value: a new value contradicts the old one (a material's
# band gap, a constant's value; association_score_with is a legacy relation still found in older projects).
VALUED_RELATIONS = frozenset({"property", "physical_constant", "association_score_with"})

_BUSY_TIMEOUT_S = 5.0
_ALNUM = string.ascii_letters + string.digits
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}")
_STOP = {
    "the", "and", "for", "with", "what", "which", "how", "does", "is", "are", "of", "in", "on", "to", "a", "an",
    "about", "tell", "me", "be", "by", "or", "its", "it", "this", "that", "from", "as", "at", "do", "can",
}

MAX_TEXT = 500
DEFAULT_RECALL_K = 12
_RECENCY_DECAY_PER_HOUR = 0.995  # Generative Agents' exponential decay factor


class ProjectStoreError(ValueError):
    pass


class ProjectAccessError(ProjectStoreError):
    """The caller may not do this: 404 when they are not a member (the project's existence is never revealed), 403
    when their role is too low."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


ROLES = ("owner", "editor", "viewer")
REVIEW_STATUSES = ("pending", "approved", "rejected")
ACTIVITY_CAP = 1000  # events kept per project (the oldest are dropped)
MAX_INSTRUCTIONS = 8000


def new_project_id() -> str:
    return "prj_" + "".join(secrets.choice(_ALNUM) for _ in range(16))


def new_fact_id() -> str:
    return "fct_" + uuid.uuid4().hex[:16]


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOP}


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))


def _require_user(user_id: str | None) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ProjectStoreError("user_id is required")
    return user_id


@dataclass
class FactInput:
    subject: str
    relation: str
    object: str
    value: str | None = None
    confidence: float = 0.7
    verified: bool = False
    source: dict[str, Any] | None = None
    tags: list[str] | None = None
    valid_from: float | None = None

    def clean(self) -> FactInput:
        self.subject = str(self.subject or "").strip()[:MAX_TEXT]
        self.relation = re.sub(r"[^a-z0-9_]+", "_", str(self.relation or "").strip().lower())[:64].strip("_")
        self.object = str(self.object or "").strip()[:MAX_TEXT]
        self.value = None if self.value is None else str(self.value)[:64]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.tags = [str(t)[:40] for t in (self.tags or [])][:10]
        return self


class ProjectStore:
    """Projects shared by their members, and each project's fact graph, in one SQLite file.

    A project has one owner and any number of editors and viewers. Every read needs membership (a non-member gets
    "not found"); writing facts, files, instructions or settings needs owner or editor; members and deletion are the
    owner's. Facts belong to the project: `user_id` on a fact records who wrote it. Each fact's review status
    (pending, approved, rejected) is in `fact_reviews`: facts written by runs start pending, facts added by hand
    start approved, and a rejected fact is invalidated. Every change goes to the project's activity log.
    """

    def __init__(self, storage_dir: str | None = None) -> None:
        self.storage_dir = storage_dir or default_projects_dir()
        os.makedirs(self.storage_dir, exist_ok=True)
        self.db_path = os.path.join(self.storage_dir, "projects.db")
        self._init_db()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with contextlib.closing(sqlite3.connect(self.db_path, timeout=_BUSY_TIMEOUT_S, check_same_thread=False)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_S * 1000)}")
            with conn:
                yield conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            with contextlib.suppress(sqlite3.DatabaseError):
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prj_user ON projects(user_id, updated_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    subject_norm TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object TEXT NOT NULL,
                    object_norm TEXT NOT NULL,
                    value TEXT,
                    valid_from REAL NOT NULL,
                    invalid_at REAL,
                    recorded_at REAL NOT NULL,
                    last_accessed REAL,
                    source_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    verified INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    superseded_by TEXT,
                    invalidation_reason TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_project ON facts(project_id, user_id, invalid_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_key ON facts(project_id, subject_norm, relation)")
            self._ensure_unique_current_facts(conn)
            self._migrate_sharing(conn)

    @staticmethod
    def _migrate_sharing(conn: sqlite3.Connection) -> None:
        """Upgrade a single-owner database in place: project settings columns, members (the owner becomes one),
        files, the activity log, and fact reviews (verified facts approved, all others pending)."""
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        for name in ("instructions", "icon", "color"):
            if name not in columns:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS members (project_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, "
            "added_at REAL NOT NULL, added_by TEXT NOT NULL, PRIMARY KEY (project_id, user_id))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_member_user ON members(user_id)")
        conn.execute(
            "INSERT OR IGNORE INTO members (project_id, user_id, role, added_at, added_by) "
            "SELECT id, user_id, 'owner', created_at, user_id FROM projects"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_files (project_id TEXT NOT NULL, dataset_id TEXT NOT NULL, "
            "owner_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '', size_bytes INTEGER, "
            "added_at REAL NOT NULL, added_by TEXT NOT NULL, PRIMARY KEY (project_id, dataset_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, "
            "at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL DEFAULT '', "
            "target_id TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '')"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_project ON activity(project_id, id)")
        # Review state lives beside the facts table (its columns are fixed): verified facts of an older database
        # count as approved, every other fact is pending until a member reviews it.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS fact_reviews (fact_id TEXT PRIMARY KEY, review_status TEXT NOT NULL, "
            "reviewed_by TEXT, reviewed_at REAL, review_note TEXT)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO fact_reviews (fact_id, review_status) "
            "SELECT id, CASE WHEN verified = 1 THEN 'approved' ELSE 'pending' END FROM facts"
        )

    @staticmethod
    def _ensure_unique_current_facts(conn: sqlite3.Connection) -> None:
        """At most one current fact per (project, user, subject, relation, object): a partial unique index on the
        facts that are still valid. Duplicates written before it existed (concurrent runs racing upsert_facts) are
        merged first: the best copy (verified, then most confident, then oldest) stays, the others are invalidated
        as superseded by it, so the index can be added to an existing database."""
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'uq_fact_current'").fetchone()
        if exists:
            return
        groups = conn.execute(
            "SELECT project_id, user_id, subject_norm, relation, object_norm FROM facts WHERE invalid_at IS NULL "
            "GROUP BY project_id, user_id, subject_norm, relation, object_norm HAVING COUNT(*) > 1"
        ).fetchall()
        now = time.time()
        for g in groups:
            rows = conn.execute(
                "SELECT id FROM facts WHERE invalid_at IS NULL AND project_id = ? AND user_id = ? AND subject_norm = ? "
                "AND relation = ? AND object_norm = ? ORDER BY verified DESC, confidence DESC, recorded_at ASC",
                tuple(g),
            ).fetchall()
            keeper = rows[0]["id"]
            for r in rows[1:]:
                ProjectStore._invalidate(conn, r["id"], now, keeper, f"duplicate of {keeper} (merged)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_current ON facts(project_id, user_id, subject_norm, relation, "
            "object_norm) WHERE invalid_at IS NULL"
        )

    # Access ----------------------------------------------------------------------------------------------------
    @staticmethod
    def _role(conn: sqlite3.Connection, project_id: str, user_id: str) -> str | None:
        if not PROJECT_ID_RE.match(project_id or "") or not user_id:
            return None
        row = conn.execute("SELECT role FROM members WHERE project_id = ? AND user_id = ?", (project_id, user_id)).fetchone()
        return row["role"] if row is not None else None

    def role(self, project_id: str | None, user_id: str | None) -> str | None:
        """The caller's role in the project ("owner", "editor", "viewer"), or None for a non-member."""
        if not project_id or not user_id:
            return None
        with self._connect() as conn:
            return self._role(conn, project_id, user_id)

    def _require(self, conn: sqlite3.Connection, project_id: str, user_id: str, *roles: str) -> str:
        """The caller's role, which must be one of `roles` (any member when none are given)."""
        _require_user(user_id)
        role = self._role(conn, project_id, user_id)
        if role is None:
            raise ProjectAccessError(404, "Project not found")
        if roles and role not in roles:
            raise ProjectAccessError(403, f"This needs the {' or '.join(roles)} role; you are a {role}.")
        return role

    def owns(self, project_id: str | None, user_id: str | None) -> bool:
        """Whether the user may write to the project (its owner or an editor)."""
        return self.role(project_id, user_id) in ("owner", "editor")

    def is_member(self, project_id: str | None, user_id: str | None) -> bool:
        return self.role(project_id, user_id) is not None

    @staticmethod
    def _log(conn: sqlite3.Connection, project_id: str, actor: str, action: str, target_type: str = "",
             target_id: str = "", summary: str = "") -> None:
        conn.execute(
            "INSERT INTO activity (project_id, at, actor, action, target_type, target_id, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, time.time(), actor, action, target_type, target_id, summary[:300]),
        )
        conn.execute(
            "DELETE FROM activity WHERE project_id = ? AND id NOT IN "
            "(SELECT id FROM activity WHERE project_id = ? ORDER BY id DESC LIMIT ?)",
            (project_id, project_id, ACTIVITY_CAP),
        )

    def log_event(self, project_id: str, actor: str, action: str, target_type: str = "", target_id: str = "",
                  summary: str = "") -> None:
        """Record an event that happened outside the store (a run that completed in the project)."""
        with self._connect() as conn:
            if self._role(conn, project_id, actor) is not None:
                self._log(conn, project_id, actor, action, target_type, target_id, summary)

    # Projects ------------------------------------------------------------------------------------------------
    def _project_dict(self, conn: sqlite3.Connection, row: sqlite3.Row, role: str) -> dict[str, Any]:
        pid = row["id"]
        facts = conn.execute(
            "SELECT SUM(CASE WHEN f.invalid_at IS NULL THEN 1 ELSE 0 END) AS v, "
            "SUM(CASE WHEN f.invalid_at IS NULL THEN 0 ELSE 1 END) AS i, "
            "SUM(CASE WHEN f.invalid_at IS NULL AND r.review_status = 'pending' THEN 1 ELSE 0 END) AS p "
            "FROM facts f LEFT JOIN fact_reviews r ON r.fact_id = f.id WHERE f.project_id = ?",
            (pid,),
        ).fetchone()
        members = conn.execute("SELECT COUNT(*) AS n FROM members WHERE project_id = ?", (pid,)).fetchone()["n"]
        files = conn.execute("SELECT COUNT(*) AS n FROM project_files WHERE project_id = ?", (pid,)).fetchone()["n"]
        valid, invalid = int(facts["v"] or 0), int(facts["i"] or 0)
        return {
            "id": pid,
            "name": row["name"],
            "description": row["description"],
            "instructions": row["instructions"],
            "icon": row["icon"],
            "color": row["color"],
            "owner_id": row["user_id"],
            "role": role,
            "member_count": int(members),
            "fact_count": valid,
            "invalid_fact_count": invalid,
            "pending_review_count": int(facts["p"] or 0),
            "file_count": int(files),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "facts": {"valid": valid, "invalidated": invalid},  # the earlier response shape, kept for old clients
        }

    def create_project(self, user_id: str, name: str, description: str = "", instructions: str = "", icon: str = "",
                       color: str = "") -> dict[str, Any]:
        user_id = _require_user(user_id)
        name = str(name or "").strip()[:200]
        if not name:
            raise ProjectStoreError("A project needs a name")
        now = time.time()
        pid = new_project_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, user_id, name, description, created_at, updated_at, instructions, icon, color) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, user_id, name, str(description or "")[:2000], now, now, str(instructions or "")[:MAX_INSTRUCTIONS],
                 str(icon or "")[:16], str(color or "")[:32]),
            )
            conn.execute("INSERT INTO members (project_id, user_id, role, added_at, added_by) VALUES (?, ?, 'owner', ?, ?)",
                         (pid, user_id, now, user_id))
            self._log(conn, pid, user_id, "project.created", "project", pid, name)
        return self.get_project(pid, user_id) or {}

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any] | None:
        user_id = _require_user(user_id)
        with self._connect() as conn:
            role = self._role(conn, project_id, user_id)
            if role is None:
                return None
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return self._project_dict(conn, row, role) if row is not None else None

    def list_projects(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Every project the user is a member of (owned and shared), most recently updated first."""
        user_id = _require_user(user_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT p.*, m.role AS member_role FROM projects p JOIN members m ON m.project_id = p.id "
                "WHERE m.user_id = ? ORDER BY p.updated_at DESC LIMIT ?",
                (user_id, max(1, min(500, limit))),
            ).fetchall()
            return [self._project_dict(conn, r, r["member_role"]) for r in rows]

    def update_project(self, project_id: str, user_id: str, name: str | None = None, description: str | None = None,
                       instructions: str | None = None, icon: str | None = None,
                       color: str | None = None) -> dict[str, Any] | None:
        """Change the project's settings (owner or editor). None for a non-member."""
        changes: dict[str, str] = {}
        if name is not None:
            name = str(name).strip()[:200]
            if not name:
                raise ProjectStoreError("A project needs a name")
            changes["name"] = name
        for key, value, cap in (("description", description, 2000), ("instructions", instructions, MAX_INSTRUCTIONS),
                                ("icon", icon, 16), ("color", color, 32)):
            if value is not None:
                changes[key] = str(value)[:cap]
        with self._connect() as conn:
            if self._role(conn, project_id, user_id) is None:
                return None
            self._require(conn, project_id, user_id, "owner", "editor")
            sets = ", ".join(["updated_at = ?", *(f"{k} = ?" for k in changes)])
            conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", (time.time(), *changes.values(), project_id))
            if changes:
                self._log(conn, project_id, user_id, "project.updated", "project", project_id, ", ".join(sorted(changes)))
        return self.get_project(project_id, user_id)

    def delete_project(self, project_id: str, user_id: str) -> bool:
        """Delete the project and everything in it (owner only). False for a non-member."""
        with self._connect() as conn:
            if self._role(conn, project_id, user_id) is None:
                return False
            self._require(conn, project_id, user_id, "owner")
            conn.execute("DELETE FROM fact_reviews WHERE fact_id IN (SELECT id FROM facts WHERE project_id = ?)",
                         (project_id,))
            for table, column in (("facts", "project_id"), ("members", "project_id"), ("project_files", "project_id"),
                                  ("activity", "project_id"), ("projects", "id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (project_id,))
        return True

    def touch_project(self, conn: sqlite3.Connection, project_id: str, user_id: str) -> None:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time(), project_id))

    # Members -------------------------------------------------------------------------------------------------
    def list_members(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require(conn, project_id, user_id)
            rows = conn.execute(
                "SELECT * FROM members WHERE project_id = ? ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 "
                "ELSE 2 END, added_at", (project_id,),
            ).fetchall()
        return [{"user_id": r["user_id"], "role": r["role"], "added_at": _iso(r["added_at"]), "added_by": r["added_by"]}
                for r in rows]

    def add_member(self, project_id: str, user_id: str, member_id: str, role: str) -> dict[str, Any]:
        member_id = str(member_id or "").strip()
        if role not in ("editor", "viewer"):
            raise ProjectStoreError("A member is an editor or a viewer (a project has one owner).")
        if not re.match(r"^[A-Za-z0-9_.@-]{1,128}$", member_id):
            raise ProjectStoreError("Not a valid user id.")
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner")
            if self._role(conn, project_id, member_id) is not None:
                raise ProjectStoreError(f"{member_id} is already a member.")
            now = time.time()
            conn.execute("INSERT INTO members (project_id, user_id, role, added_at, added_by) VALUES (?, ?, ?, ?, ?)",
                         (project_id, member_id, role, now, user_id))
            self._log(conn, project_id, user_id, "member.added", "member", member_id, role)
        return {"user_id": member_id, "role": role, "added_at": _iso(now), "added_by": user_id}

    def set_member_role(self, project_id: str, user_id: str, member_id: str, role: str) -> dict[str, Any]:
        if role not in ("editor", "viewer"):
            raise ProjectStoreError("A member is an editor or a viewer (a project has one owner).")
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner")
            current = self._role(conn, project_id, member_id)
            if current is None:
                raise ProjectAccessError(404, "Member not found")
            if current == "owner":
                raise ProjectStoreError("The owner's role cannot be changed.")
            conn.execute("UPDATE members SET role = ? WHERE project_id = ? AND user_id = ?", (role, project_id, member_id))
            self._log(conn, project_id, user_id, "member.role_changed", "member", member_id, f"{current} -> {role}")
        return next(m for m in self.list_members(project_id, user_id) if m["user_id"] == member_id)

    def remove_member(self, project_id: str, user_id: str, member_id: str) -> bool:
        """Remove a member: the owner may remove anyone but themself; any member may leave."""
        with self._connect() as conn:
            role = self._require(conn, project_id, user_id)
            if member_id != user_id and role != "owner":
                raise ProjectAccessError(403, "Only the owner can remove other members.")
            target = self._role(conn, project_id, member_id)
            if target is None:
                raise ProjectAccessError(404, "Member not found")
            if target == "owner":
                raise ProjectStoreError("The owner cannot leave or be removed; delete the project instead.")
            conn.execute("DELETE FROM members WHERE project_id = ? AND user_id = ?", (project_id, member_id))
            self._log(conn, project_id, user_id, "member.removed", "member", member_id,
                      "left" if member_id == user_id else "removed")
        return True

    # Files ---------------------------------------------------------------------------------------------------
    def list_files(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require(conn, project_id, user_id)
            rows = conn.execute("SELECT * FROM project_files WHERE project_id = ? ORDER BY added_at",
                                (project_id,)).fetchall()
        return [{"dataset_id": r["dataset_id"], "name": r["name"], "kind": r["kind"], "size_bytes": r["size_bytes"],
                 "added_at": _iso(r["added_at"]), "added_by": r["added_by"]} for r in rows]

    def add_file(self, project_id: str, user_id: str, dataset_id: str, name: str = "", kind: str = "",
                 size_bytes: int | None = None) -> dict[str, Any]:
        """Share one of the caller's datasets with the project (the API checks that the caller owns it)."""
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO project_files (project_id, dataset_id, owner_id, name, kind, size_bytes, "
                "added_at, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, dataset_id, user_id, str(name)[:200], str(kind)[:32], size_bytes, now, user_id),
            )
            self._log(conn, project_id, user_id, "file.added", "file", dataset_id, str(name)[:200])
            self.touch_project(conn, project_id, user_id)
        return {"dataset_id": dataset_id, "name": name, "kind": kind, "size_bytes": size_bytes, "added_at": _iso(now),
                "added_by": user_id}

    def remove_file(self, project_id: str, user_id: str, dataset_id: str) -> bool:
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            gone = conn.execute("DELETE FROM project_files WHERE project_id = ? AND dataset_id = ?",
                                (project_id, dataset_id)).rowcount
            if gone:
                self._log(conn, project_id, user_id, "file.removed", "file", dataset_id)
        return bool(gone)

    def run_context(self, project_id: str | None, user_id: str) -> dict[str, Any] | None:
        """What a run in the project gets: its name, instructions, and its files with their owners (only files whose
        owner is still a member). None when the user is not a member."""
        if not project_id:
            return None
        with self._connect() as conn:
            if self._role(conn, project_id, user_id) is None:
                return None
            row = conn.execute("SELECT name, instructions FROM projects WHERE id = ?", (project_id,)).fetchone()
            files = conn.execute(
                "SELECT f.dataset_id, f.owner_id FROM project_files f JOIN members m ON m.project_id = f.project_id "
                "AND m.user_id = f.owner_id WHERE f.project_id = ? ORDER BY f.added_at", (project_id,),
            ).fetchall()
        return {"name": row["name"], "instructions": row["instructions"] or "",
                "files": [(r["dataset_id"], r["owner_id"]) for r in files]}

    # Activity ------------------------------------------------------------------------------------------------
    def list_activity(self, project_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require(conn, project_id, user_id)
            rows = conn.execute("SELECT * FROM activity WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                                (project_id, max(1, min(500, limit)))).fetchall()
        return [{"id": r["id"], "at": _iso(r["at"]), "actor": r["actor"], "action": r["action"],
                 "target_type": r["target_type"], "target_id": r["target_id"], "summary": r["summary"]} for r in rows]

    # Facts ---------------------------------------------------------------------------------------------------
    _FACT_SELECT = (
        "SELECT f.*, r.review_status, r.reviewed_by, r.reviewed_at, r.review_note FROM facts f "
        "LEFT JOIN fact_reviews r ON r.fact_id = f.id"
    )

    @staticmethod
    def _fact_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            source = json.loads(row["source_json"] or "{}")
        except ValueError:
            source = {}
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except ValueError:
            tags = []
        keys = set(row.keys())
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "subject": row["subject"],
            "relation": row["relation"],
            "object": row["object"],
            "value": row["value"],
            "valid_from": _iso(row["valid_from"]),
            "invalid_at": _iso(row["invalid_at"]),
            "recorded_at": _iso(row["recorded_at"]),
            "source": source,
            "confidence": round(float(row["confidence"]), 3),
            "verified": bool(row["verified"]),
            "tags": tags,
            "superseded_by": row["superseded_by"],
            "invalidation_reason": row["invalidation_reason"],
            "written_by": row["user_id"],
            "review_status": (row["review_status"] if "review_status" in keys else None) or "pending",
            "reviewed_by": row["reviewed_by"] if "reviewed_by" in keys else None,
            "reviewed_at": _iso(row["reviewed_at"]) if "reviewed_at" in keys else None,
            "review_note": row["review_note"] if "review_note" in keys else None,
        }

    def get_fact(self, project_id: str, fact_id: str, user_id: str) -> dict[str, Any] | None:
        if not FACT_ID_RE.match(fact_id or "") or not self.is_member(project_id, user_id):
            return None
        with self._connect() as conn:
            row = conn.execute(f"{self._FACT_SELECT} WHERE f.id = ? AND f.project_id = ?", (fact_id, project_id)).fetchone()
        return self._fact_dict(row) if row is not None else None

    def list_facts(self, project_id: str, user_id: str, include_invalid: bool = False, limit: int = 200,
                   review_status: str | None = None) -> list[dict[str, Any]]:
        if not self.is_member(project_id, user_id):
            return []
        where = "" if include_invalid or review_status == "rejected" else " AND f.invalid_at IS NULL"
        args: list[Any] = [project_id]
        if review_status:
            where += " AND COALESCE(r.review_status, 'pending') = ?"
            args.append(review_status)
        with self._connect() as conn:
            rows = conn.execute(
                f"{self._FACT_SELECT} WHERE f.project_id = ?{where} ORDER BY f.recorded_at DESC LIMIT ?",
                (*args, max(1, min(2000, limit))),
            ).fetchall()
        return [self._fact_dict(r) for r in rows]

    def _insert(
        self, conn: sqlite3.Connection, project_id: str, user_id: str, f: FactInput, now: float, fid: str | None = None,
        review_status: str = "pending",
    ) -> str:
        fid = fid or new_fact_id()
        tags = list(f.tags or [])
        if not f.verified and "unverified" not in tags:
            tags.append("unverified")
        conn.execute(
            "INSERT INTO facts (id, project_id, user_id, subject, subject_norm, relation, object, object_norm, value, valid_from, "
            "invalid_at, recorded_at, last_accessed, source_json, confidence, verified, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?)",
            (
                fid, project_id, user_id, f.subject, norm(f.subject), f.relation, f.object, norm(f.object), f.value,
                f.valid_from or now, now, json.dumps(f.source or {}, default=str)[:4000], f.confidence, int(bool(f.verified)),
                json.dumps(tags),
            ),
        )
        approved = review_status == "approved"
        conn.execute(
            "INSERT OR REPLACE INTO fact_reviews (fact_id, review_status, reviewed_by, reviewed_at) VALUES (?, ?, ?, ?)",
            (fid, review_status, user_id if approved else None, now if approved else None),
        )
        return fid

    @staticmethod
    def _invalidate(conn: sqlite3.Connection, fact_id: str, now: float, superseded_by: str | None, reason: str) -> None:
        conn.execute(
            "UPDATE facts SET invalid_at = ?, superseded_by = ?, invalidation_reason = ? WHERE id = ? AND invalid_at IS NULL",
            (now, superseded_by, reason[:300], fact_id),
        )

    def upsert_facts(self, project_id: str, user_id: str, facts: Sequence[FactInput],
                     review_status: str = "pending") -> dict[str, Any]:
        """Mem0-style deterministic update of the fact graph with one batch of extracted facts.

        Per fact, against the currently valid facts of the project with the same subject and relation:
        - same object (and the same value, for valued relations): NOOP, or UPDATE when the new fact is verified
          and the stored one is not, or the new confidence is higher;
        - a single-valued relation with a different object, or a valued relation with a different value:
          INVALIDATE the old fact (Zep: invalid_at + superseded_by, never deleted), then ADD the new one;
        - otherwise ADD.
        Facts of one batch never invalidate each other (a drug with two mechanisms is two facts). New facts start
        with `review_status`: pending for the facts a run extracted, until a member approves or rejects them.
        """
        if not self.owns(project_id, user_id):
            raise ProjectStoreError("Project not found")
        now = time.time()
        ops: list[dict[str, Any]] = []
        batch_keys: dict[tuple[str, str], set[str]] = {}
        cleaned = [f.clean() for f in facts if f.subject and f.relation and f.object]
        cleaned = [f for f in cleaned if f.subject and f.relation and f.object]
        for f in cleaned:
            batch_keys.setdefault((norm(f.subject), f.relation), set()).add(norm(f.object))
        written = invalidated = 0
        with self._connect() as conn:
            # One writer at a time from the first read: two runs of one project would otherwise both read "no such
            # fact" and both add it, or each miss the other's contradiction (LOG-30).
            conn.execute("BEGIN IMMEDIATE")
            for f in cleaned:
                s_norm, o_norm = norm(f.subject), norm(f.object)
                existing = conn.execute(
                    "SELECT * FROM facts WHERE project_id = ? AND subject_norm = ? AND relation = ? AND invalid_at IS NULL",
                    (project_id, s_norm, f.relation),
                ).fetchall()
                same = [r for r in existing if r["object_norm"] == o_norm]
                if f.relation in VALUED_RELATIONS and same and f.value is not None:
                    differing = [r for r in same if r["value"] is not None and r["value"] != f.value]
                    if differing:
                        # The old value is invalidated before the new one is added (one current fact per key).
                        new_id = new_fact_id()
                        for r in differing:
                            self._invalidate(conn, r["id"], now, new_id, f"value changed from {r['value']} to {f.value}")
                        self._insert(conn, project_id, user_id, f, now, fid=new_id, review_status=review_status)
                        ops.append({"op": "INVALIDATE", "fact_id": new_id, "invalidated": [r["id"] for r in differing], "subject": f.subject, "relation": f.relation, "object": f.object})
                        ops.append({"op": "ADD", "fact_id": new_id, "subject": f.subject, "relation": f.relation, "object": f.object})
                        written += 1
                        invalidated += len(differing)
                        continue
                if same:
                    row = same[0]
                    better = (f.verified and not row["verified"]) or f.confidence > float(row["confidence"]) + 1e-6
                    if better:
                        tags = sorted(set(json.loads(row["tags_json"] or "[]")) - ({"unverified"} if f.verified else set()) | set(f.tags or []))
                        # An unverified write never replaces the provenance of a verified fact.
                        keep_source = bool(row["verified"]) and not f.verified
                        conn.execute(
                            "UPDATE facts SET confidence = ?, verified = ?, tags_json = ?, source_json = ?, value = COALESCE(?, value) WHERE id = ?",
                            (
                                max(f.confidence, float(row["confidence"])), int(bool(f.verified or row["verified"])), json.dumps(tags),
                                row["source_json"] if keep_source else json.dumps(f.source or {}, default=str)[:4000],
                                f.value, row["id"],
                            ),
                        )
                        ops.append({"op": "UPDATE", "fact_id": row["id"], "subject": f.subject, "relation": f.relation, "object": f.object})
                    else:
                        ops.append({"op": "NOOP", "fact_id": row["id"], "subject": f.subject, "relation": f.relation, "object": f.object})
                    continue
                contradicted: list[sqlite3.Row] = []
                if f.relation in SINGLE_VALUED_RELATIONS:
                    in_batch = batch_keys.get((s_norm, f.relation), set())
                    contradicted = [r for r in existing if r["object_norm"] not in in_batch and float(r["recorded_at"]) < now]
                    # An unverified automated run cannot invalidate an already verified fact.
                    if f.source and f.source.get("run_id") and not f.verified:
                        contradicted = [r for r in contradicted if not r["verified"]]
                new_id = self._insert(conn, project_id, user_id, f, now, review_status=review_status)
                for r in contradicted:
                    self._invalidate(conn, r["id"], now, new_id, f"contradicted by a newer {f.relation}: {f.object[:120]}")
                if contradicted:
                    ops.append({"op": "INVALIDATE", "fact_id": new_id, "invalidated": [r["id"] for r in contradicted], "subject": f.subject, "relation": f.relation, "object": f.object})
                    invalidated += len(contradicted)
                ops.append({"op": "ADD", "fact_id": new_id, "subject": f.subject, "relation": f.relation, "object": f.object})
                written += 1
            if cleaned:
                self.touch_project(conn, project_id, user_id)
            if written or invalidated:
                self._log(conn, project_id, user_id, "fact.added", "fact", "",
                          f"{written} fact(s) written, {invalidated} superseded")
        return {"written": written, "invalidated": invalidated, "ops": ops}

    def add_fact(self, project_id: str, user_id: str, subject: str, relation: str, object: str,  # noqa: A002
                 confidence: float = 0.9, note: str = "") -> dict[str, Any]:
        """A fact a member adds by hand: it starts approved (writing it is the review)."""
        f = FactInput(subject=subject, relation=relation, object=object, confidence=confidence, verified=False,
                      source={"origin": "added by a member"}).clean()
        if not (f.subject and f.relation and f.object):
            raise ProjectStoreError("A fact needs a subject, a relation and an object.")
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            conn.execute("BEGIN IMMEDIATE")
            dup = conn.execute(
                "SELECT id FROM facts WHERE project_id = ? AND subject_norm = ? AND relation = ? AND object_norm = ? "
                "AND invalid_at IS NULL", (project_id, norm(f.subject), f.relation, norm(f.object)),
            ).fetchone()
            if dup is not None:
                raise ProjectStoreError("The project already has this fact.")
            fid = self._insert(conn, project_id, user_id, f, time.time(), review_status="approved")
            if note:
                conn.execute("UPDATE fact_reviews SET review_note = ? WHERE fact_id = ?", (note[:300], fid))
            self._log(conn, project_id, user_id, "fact.added", "fact", fid, f"{f.subject} {f.relation} {f.object}")
            self.touch_project(conn, project_id, user_id)
        return self.get_fact(project_id, fid, user_id) or {}

    def review_fact(self, project_id: str, fact_id: str, user_id: str, decision: str,
                    note: str = "") -> dict[str, Any] | None:
        """Approve or reject a fact (owner or editor). Rejecting invalidates it, so recall never uses it."""
        if decision not in ("approve", "reject"):
            raise ProjectStoreError("The decision is approve or reject.")
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            row = conn.execute("SELECT id, invalid_at FROM facts WHERE id = ? AND project_id = ?",
                               (fact_id, project_id)).fetchone()
            if row is None:
                return None
            now = time.time()
            status = "approved" if decision == "approve" else "rejected"
            if status == "approved" and row["invalid_at"] is not None:
                raise ProjectStoreError("An invalidated fact cannot be approved.")
            conn.execute(
                "INSERT OR REPLACE INTO fact_reviews (fact_id, review_status, reviewed_by, reviewed_at, review_note) "
                "VALUES (?, ?, ?, ?, ?)", (fact_id, status, user_id, now, note[:300] or None),
            )
            if status == "rejected":
                self._invalidate(conn, fact_id, now, None, f"rejected in review{': ' + note[:200] if note else ''}")
            self._log(conn, project_id, user_id, f"fact.{status}", "fact", fact_id, note[:300])
        return self.get_fact(project_id, fact_id, user_id)

    def fact_history(self, project_id: str, fact_id: str, user_id: str) -> list[dict[str, Any]]:
        """Every version of a fact (edits and supersessions, linked by superseded_by), oldest first."""
        if self.get_fact(project_id, fact_id, user_id) is None:
            raise ProjectAccessError(404, "Fact not found")
        with self._connect() as conn:
            rows = {r["id"]: r for r in conn.execute(f"{self._FACT_SELECT} WHERE f.project_id = ?", (project_id,)).fetchall()}
        previous = {r["superseded_by"]: fid for fid, r in rows.items() if r["superseded_by"]}
        chain = [fact_id]
        while chain[0] in previous and previous[chain[0]] not in chain:
            chain.insert(0, previous[chain[0]])
        while rows[chain[-1]]["superseded_by"] in rows and rows[chain[-1]]["superseded_by"] not in chain:
            chain.append(rows[chain[-1]]["superseded_by"])
        return [self._fact_dict(rows[i]) for i in chain]

    def invalidate_fact(self, project_id: str, fact_id: str, user_id: str,
                        reason: str = "invalidated by the researcher") -> dict[str, Any] | None:
        if self.get_fact(project_id, fact_id, user_id) is None:
            return None
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            self._invalidate(conn, fact_id, time.time(), None, reason)
            self._log(conn, project_id, user_id, "fact.invalidated", "fact", fact_id, reason)
        return self.get_fact(project_id, fact_id, user_id)

    def edit_fact(
        self,
        project_id: str,
        fact_id: str,
        user_id: str,
        *,
        object: str | None = None,  # noqa: A002 - the fact's field name
        value: str | None = None,
        confidence: float | None = None,
        verified: bool | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Edit a fact. A changed object or value is a new version (old one invalidated, Zep-style)."""
        old = self.get_fact(project_id, fact_id, user_id)
        if old is None:
            return None
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
        if old["invalid_at"] is not None:
            raise ProjectStoreError("An invalidated fact cannot be edited")
        now = time.time()
        if (object is not None and object.strip() != old["object"]) or (value is not None and value != old["value"]):
            f = FactInput(
                subject=old["subject"],
                relation=old["relation"],
                object=object.strip() if object is not None else old["object"],
                value=value if value is not None else old["value"],
                confidence=confidence if confidence is not None else old["confidence"],
                verified=verified if verified is not None else old["verified"],
                source={**(old["source"] or {}), "edited_by": "researcher", "previous": fact_id},
                tags=[t for t in (tags if tags is not None else old["tags"]) if t != "unverified"] + ["edited"],
            ).clean()
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                new_id = new_fact_id()
                self._invalidate(conn, fact_id, now, new_id, "edited by the researcher")
                self._insert(conn, project_id, user_id, f, now, fid=new_id, review_status="approved")
                self._log(conn, project_id, user_id, "fact.edited", "fact", new_id, f"new version of {fact_id}")
                self.touch_project(conn, project_id, user_id)
            return self.get_fact(project_id, new_id, user_id)
        sets: list[str] = []
        args: list[Any] = []
        if confidence is not None:
            sets.append("confidence = ?")
            args.append(max(0.0, min(1.0, float(confidence))))
        if verified is not None:
            sets.append("verified = ?")
            args.append(int(bool(verified)))
        if tags is not None or verified is not None:
            # The "unverified" tag follows the verified flag: verifying a fact drops it, unverifying adds it.
            new_tags = [str(t)[:40] for t in (tags if tags is not None else old["tags"] or [])]
            is_verified = verified if verified is not None else bool(old["verified"])
            new_tags = [t for t in new_tags if t != "unverified"] + ([] if is_verified else ["unverified"])
            sets.append("tags_json = ?")
            args.append(json.dumps(list(dict.fromkeys(new_tags))[:10]))
        if sets:
            with self._connect() as conn:
                conn.execute(f"UPDATE facts SET {', '.join(sets)} WHERE id = ? AND project_id = ?",
                             (*args, fact_id, project_id))
                self._log(conn, project_id, user_id, "fact.edited", "fact", fact_id,
                          ", ".join(s.split(" ")[0] for s in sets))
                self.touch_project(conn, project_id, user_id)
        return self.get_fact(project_id, fact_id, user_id)

    def delete_fact(self, project_id: str, fact_id: str, user_id: str) -> bool:
        if self.get_fact(project_id, fact_id, user_id) is None:
            return False
        with self._connect() as conn:
            self._require(conn, project_id, user_id, "owner", "editor")
            conn.execute("DELETE FROM facts WHERE id = ? AND project_id = ?", (fact_id, project_id))
            conn.execute("DELETE FROM fact_reviews WHERE fact_id = ?", (fact_id,))
            self._log(conn, project_id, user_id, "fact.deleted", "fact", fact_id)
        return True

    # Retrieval -----------------------------------------------------------------------------------------------
    def recall(
        self,
        project_id: str,
        user_id: str,
        query: str = "",
        entities: Iterable[str] = (),
        k: int = DEFAULT_RECALL_K,
        touch: bool = True,
    ) -> list[dict[str, Any]]:
        """Top-k valid, non-rejected facts by Personalized PageRank relevance combined with recency and importance."""
        if not self.is_member(project_id, user_id):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                f"{self._FACT_SELECT} WHERE f.project_id = ? AND f.invalid_at IS NULL "
                "AND COALESCE(r.review_status, 'pending') != 'rejected'", (project_id,),
            ).fetchall()
        if not rows:
            return []
        ranked = rank_facts(rows, query, entities)
        top = ranked[: max(1, k)]
        if touch and top:
            now = time.time()
            with self._connect() as conn:
                conn.executemany("UPDATE facts SET last_accessed = ? WHERE id = ?", [(now, r["id"]) for r, _ in top])
        out = []
        for row, score in top:
            d = self._fact_dict(row)
            d["score"] = round(score, 4)
            out.append(d)
        return out


# ---------------------------------------------------------------------------------------------------------
# Ranking: HippoRAG Personalized PageRank + Generative Agents scoring
# ---------------------------------------------------------------------------------------------------------

def personalized_pagerank(
    edges: Sequence[tuple[str, str, float]],
    seeds: dict[str, float],
    damping: float = 0.85,
    iterations: int = 40,
    tol: float = 1e-8,
) -> dict[str, float]:
    """PPR over an undirected weighted graph; the restart distribution is the normalised seed weights.

    With no seed in the graph the restart distribution is uniform (plain PageRank)."""
    adj: dict[str, dict[str, float]] = {}
    for a, b, w in edges:
        if a == b:
            continue
        w = max(1e-6, float(w))
        adj.setdefault(a, {})[b] = adj.get(a, {}).get(b, 0.0) + w
        adj.setdefault(b, {})[a] = adj.get(b, {}).get(a, 0.0) + w
    nodes = list(adj)
    if not nodes:
        return {}
    restart = {n: float(seeds.get(n, 0.0)) for n in nodes}
    total = sum(restart.values())
    if total <= 0:
        restart = {n: 1.0 / len(nodes) for n in nodes}
    else:
        restart = {n: v / total for n, v in restart.items()}
    out_w = {n: sum(adj[n].values()) for n in nodes}
    rank = dict(restart)
    for _ in range(iterations):
        nxt = {n: (1.0 - damping) * restart[n] for n in nodes}
        for n in nodes:
            if out_w[n] <= 0:
                continue
            share = damping * rank[n] / out_w[n]
            for m, w in adj[n].items():
                nxt[m] += share * w
        delta = sum(abs(nxt[n] - rank[n]) for n in nodes)
        rank = nxt
        if delta < tol:
            break
    return rank


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 if hi > 0 else 0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_facts(rows: Sequence[Any], query: str, entities: Iterable[str] = ()) -> list[tuple[Any, float]]:
    """(row, score) sorted best first. Rows need subject/object/confidence/verified/recorded_at/last_accessed."""
    q_tokens = tokens(query)
    ent_norms = {norm(e) for e in entities if norm(e)}
    edges = [(norm(r["subject"]), norm(r["object"]), float(r["confidence"] or 0.5)) for r in rows]
    node_names = {n for a, b, _ in edges for n in (a, b)}
    seeds: dict[str, float] = {}
    for n in node_names:
        weight = 0.0
        if n in ent_norms:
            weight += 2.0
        elif any(e and (e in n or n in e) for e in ent_norms if len(e) >= 3 and len(n) >= 3):
            weight += 1.0
        overlap = len(tokens(n) & q_tokens)
        if overlap:
            weight += 0.5 * overlap
        if weight:
            seeds[n] = weight
    ppr = personalized_pagerank(edges, seeds)
    now = time.time()
    rel_raw, rec_raw, imp_raw = [], [], []
    for r in rows:
        s, o = norm(r["subject"]), norm(r["object"])
        lexical = len(tokens(f"{r['subject']} {r['relation'].replace('_', ' ')} {r['object']}") & q_tokens)
        rel_raw.append(ppr.get(s, 0.0) + ppr.get(o, 0.0) + (0.05 * lexical if seeds else 0.1 * lexical))
        last = float(r["last_accessed"] or r["recorded_at"] or now)
        hours = max(0.0, (now - last) / 3600.0)
        rec_raw.append(_RECENCY_DECAY_PER_HOUR ** hours)
        imp_raw.append(float(r["confidence"] or 0.0) + (0.25 if r["verified"] else 0.0))
    rel, rec, imp = _minmax(rel_raw), _minmax(rec_raw), _minmax(imp_raw)
    # Relevance gets weight 1 like the paper's equal weights; with seeds it dominates ties, without seeds it is flat.
    scored = [(row, rel[i] * (1.5 if seeds else 1.0) + rec[i] + imp[i]) for i, row in enumerate(rows)]
    scored.sort(key=lambda x: (x[1], float(x[0]["recorded_at"])), reverse=True)
    return scored


# ---------------------------------------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------------------------------------

def default_projects_dir() -> str:
    env = os.getenv("TRIBOS_PROJECTS_DIR")
    if env:
        return env
    mem = os.getenv("TRIBOS_MEMORY_DIR")
    if mem:
        return mem
    from ..paths import data_dir

    root = data_dir("memory")
    if root is not None:
        return str(root)
    if "PYTEST_CURRENT_TEST" in os.environ:
        return os.path.join(tempfile.gettempdir(), "tribos_projects_pytest")
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(workspace_root, ".tribos_memory")


_STORES: dict[str, ProjectStore] = {}
_STORES_LOCK = threading.Lock()


def get_project_store(storage_dir: str | None = None) -> ProjectStore:
    """Process-wide store per directory; the directory is re-read on each call (tests point it at tmp_path)."""
    path = os.path.abspath(storage_dir or default_projects_dir())
    with _STORES_LOCK:
        store = _STORES.get(path)
        if store is None:
            store = ProjectStore(path)
            _STORES[path] = store
        return store


__all__ = [
    "FACT_ID_RE",
    "PROJECT_ID_RE",
    "SINGLE_VALUED_RELATIONS",
    "VALUED_RELATIONS",
    "ACTIVITY_CAP",
    "REVIEW_STATUSES",
    "ROLES",
    "FactInput",
    "ProjectAccessError",
    "ProjectStore",
    "ProjectStoreError",
    "get_project_store",
    "personalized_pagerank",
    "rank_facts",
]
