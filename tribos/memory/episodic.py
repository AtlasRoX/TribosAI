"""Episodic Memory: Tier 3 historical knowledge, bi-temporal fact graph, and reflexion lessons.

Features:
- Bi-temporal fact graph (valid_from, invalid_at, recorded_at, superseded_by)
- Cryptographic provenance binding (manifest_id, verifier_verdict, source_tool)
- Reflexion failure lessons (records non-convergence, singular peaks, Axiom refutations)
- Strict supersession instead of destructive deletes (retaining design evolution history)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EpisodicFact:
    id: str
    project_id: str
    subject: str
    relation: str
    object: str
    value: str | None
    unit: str | None
    valid_from: float
    invalid_at: float | None
    recorded_at: float
    superseded_by: str | None
    manifest_id: str | None
    verification_status: str  # verified_empirical | provisional | refuted
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)


@dataclass
class ReflexionLesson:
    id: str
    project_id: str
    task_kind: str  # e.g. "fea_mesh" | "ode_solve" | "symbolic_claim" | "boundary_condition"
    failed_action: str
    root_cause: str
    countermeasure: str
    created_at: float
    manifest_id: str | None = None


class EpisodicMemory:
    """Bi-temporal fact graph and operational lessons archive."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".tribos_memory"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "episodic_memory.sqlite3")
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
                CREATE TABLE IF NOT EXISTS episodic_facts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object TEXT NOT NULL,
                    value TEXT,
                    unit TEXT,
                    valid_from REAL NOT NULL,
                    invalid_at REAL,
                    recorded_at REAL NOT NULL,
                    superseded_by TEXT,
                    manifest_id TEXT,
                    verification_status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reflexion_lessons (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    failed_action TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    countermeasure TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    manifest_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_facts_proj_subj ON episodic_facts(project_id, subject);
                CREATE INDEX IF NOT EXISTS idx_facts_valid ON episodic_facts(project_id, invalid_at);
                CREATE INDEX IF NOT EXISTS idx_lessons_proj_kind ON reflexion_lessons(project_id, task_kind);
                """
            )

    def record_fact(
        self,
        project_id: str,
        subject: str,
        relation: str,
        object: str,
        value: str | None = None,
        unit: str | None = None,
        manifest_id: str | None = None,
        verification_status: str = "verified_empirical",
        confidence: float = 1.0,
        evidence: list[str] | None = None,
    ) -> EpisodicFact:
        """Record a fact, invalidating any directly contradicting active fact."""
        now = time.time()
        fact_id = f"fct_{uuid.uuid4().hex[:16]}"
        subj_clean = subject.strip().lower()
        rel_clean = relation.strip().lower()
        obj_clean = object.strip().lower()

        with self._get_conn() as conn:
            # Check for existing active fact with same subject and relation if it's single-valued
            existing = conn.execute(
                """
                SELECT id FROM episodic_facts
                WHERE project_id = ? AND subject = ? AND relation = ? AND invalid_at IS NULL
                """,
                (project_id, subj_clean, rel_clean),
            ).fetchall()

            for row in existing:
                conn.execute(
                    "UPDATE episodic_facts SET invalid_at = ?, superseded_by = ? WHERE id = ?",
                    (now, fact_id, row["id"]),
                )

            fact = EpisodicFact(
                id=fact_id,
                project_id=project_id,
                subject=subj_clean,
                relation=rel_clean,
                object=obj_clean,
                value=str(value) if value is not None else None,
                unit=unit,
                valid_from=now,
                invalid_at=None,
                recorded_at=now,
                superseded_by=None,
                manifest_id=manifest_id,
                verification_status=verification_status,
                confidence=confidence,
                evidence=evidence or [],
            )

            conn.execute(
                """
                INSERT INTO episodic_facts (id, project_id, subject, relation, object, value, unit, valid_from, invalid_at, recorded_at, superseded_by, manifest_id, verification_status, confidence, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.id,
                    fact.project_id,
                    fact.subject,
                    fact.relation,
                    fact.object,
                    fact.value,
                    fact.unit,
                    fact.valid_from,
                    fact.invalid_at,
                    fact.recorded_at,
                    fact.superseded_by,
                    fact.manifest_id,
                    fact.verification_status,
                    fact.confidence,
                    json.dumps(fact.evidence),
                ),
            )
            return fact

    def get_active_facts(self, project_id: str, subject: str | None = None) -> list[EpisodicFact]:
        """Fetch facts that are currently valid (invalid_at IS NULL)."""
        with self._get_conn() as conn:
            if subject:
                rows = conn.execute(
                    "SELECT * FROM episodic_facts WHERE project_id = ? AND subject = ? AND invalid_at IS NULL ORDER BY recorded_at DESC",
                    (project_id, subject.strip().lower()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM episodic_facts WHERE project_id = ? AND invalid_at IS NULL ORDER BY recorded_at DESC",
                    (project_id,),
                ).fetchall()
            return [
                EpisodicFact(
                    id=r["id"],
                    project_id=r["project_id"],
                    subject=r["subject"],
                    relation=r["relation"],
                    object=r["object"],
                    value=r["value"],
                    unit=r["unit"],
                    valid_from=r["valid_from"],
                    invalid_at=r["invalid_at"],
                    recorded_at=r["recorded_at"],
                    superseded_by=r["superseded_by"],
                    manifest_id=r["manifest_id"],
                    verification_status=r["verification_status"],
                    confidence=r["confidence"],
                    evidence=json.loads(r["evidence_json"]),
                )
                for r in rows
            ]

    def record_lesson(
        self,
        project_id: str,
        task_kind: str,
        failed_action: str,
        root_cause: str,
        countermeasure: str,
        manifest_id: str | None = None,
    ) -> ReflexionLesson:
        """Record an operational failure lesson so the planner avoids repeating it."""
        lesson_id = f"lsn_{uuid.uuid4().hex[:12]}"
        now = time.time()
        lesson = ReflexionLesson(
            id=lesson_id,
            project_id=project_id,
            task_kind=task_kind.strip().lower(),
            failed_action=failed_action.strip(),
            root_cause=root_cause.strip(),
            countermeasure=countermeasure.strip(),
            created_at=now,
            manifest_id=manifest_id,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO reflexion_lessons (id, project_id, task_kind, failed_action, root_cause, countermeasure, created_at, manifest_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson.id,
                    lesson.project_id,
                    lesson.task_kind,
                    lesson.failed_action,
                    lesson.root_cause,
                    lesson.countermeasure,
                    lesson.created_at,
                    lesson.manifest_id,
                ),
            )
        return lesson

    def get_lessons(
        self, project_id: str, task_kind: str | None = None, limit: int = 5
    ) -> list[ReflexionLesson]:
        with self._get_conn() as conn:
            if task_kind:
                rows = conn.execute(
                    "SELECT * FROM reflexion_lessons WHERE project_id = ? AND task_kind = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, task_kind.strip().lower(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reflexion_lessons WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            return [
                ReflexionLesson(
                    id=r["id"],
                    project_id=r["project_id"],
                    task_kind=r["task_kind"],
                    failed_action=r["failed_action"],
                    root_cause=r["root_cause"],
                    countermeasure=r["countermeasure"],
                    created_at=r["created_at"],
                    manifest_id=r["manifest_id"],
                )
                for r in rows
            ]
