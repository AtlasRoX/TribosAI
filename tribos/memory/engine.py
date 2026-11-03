"""Unified Cognitive Memory Engine for Tribos (TribosMemoryEngine).

Integrates the 4 Cognitive Memory Tiers:
- Tier 1: Working Memory (active goals, scratchpad, inter-specialist variable cache)
- Tier 2: Session Memory (server-side threads, answer version tree, design branching)
- Tier 3: Episodic Memory (bi-temporal fact graph, cryptographic manifests, reflexion lessons)
- Tier 4: Semantic Memory (materials property catalog, ASME/ISO standards clauses, CODATA constants)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .admission import AdmissionController
from .episodic import EpisodicFact, EpisodicMemory, ReflexionLesson
from .retrieval import HybridRetriever
from .semantic import MaterialRecord, SemanticMemory
from .session import AnswerRevision, ConversationTurn, SessionMemory
from .working import WorkingMemory


class TribosMemoryEngine:
    """Unified Cognitive Memory Engine orchestrating all memory tiers."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            self.base_dir = Path.home() / ".tribos_memory"
        else:
            self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Initialize persistent tiers
        self.session = SessionMemory(self.base_dir / "sessions.sqlite3")
        self.episodic = EpisodicMemory(self.base_dir / "episodic.sqlite3")
        self.semantic = SemanticMemory()
        self.admission = AdmissionController()
        self.retriever = HybridRetriever()

    # Working Memory Factory ------------------------------------------------------------------
    def create_working_memory(self, query: str) -> WorkingMemory:
        """Create a fresh in-flight working memory instance for an agentic run."""
        return WorkingMemory(query=query)

    # Session & Conversation Operations (F-17) ------------------------------------------------
    def create_thread(
        self, project_id: str, title: str, metadata: dict[str, Any] | None = None
    ) -> str:
        return self.session.create_thread(project_id, title, metadata)

    def add_turn(
        self, thread_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> str:
        return self.session.add_turn(thread_id, role, content, metadata)

    def get_thread_project(self, thread_id: str) -> str | None:
        return self.session.get_thread_project(thread_id)

    def get_thread_turns(self, thread_id: str, limit: int = 50) -> list[ConversationTurn]:
        return self.session.get_thread_turns(thread_id, limit)

    def list_project_threads(self, project_id: str) -> list[dict[str, Any]]:
        return self.session.list_project_threads(project_id)

    # Answer Versioning & Tree (F-16) ---------------------------------------------------------
    def create_answer_revision(
        self,
        project_id: str,
        content: str,
        summary: str = "",
        branch_name: str = "main",
        parent_id: str | None = None,
        author: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> AnswerRevision:
        return self.session.create_revision(
            project_id=project_id,
            content=content,
            summary=summary,
            branch_name=branch_name,
            parent_id=parent_id,
            author=author,
            metadata=metadata,
        )

    def get_answer_revision(self, revision_id: str) -> AnswerRevision | None:
        return self.session.get_revision(revision_id)

    def list_answer_revisions(
        self, project_id: str, branch_name: str | None = None
    ) -> list[AnswerRevision]:
        return self.session.list_revisions(project_id, branch_name)

    def diff_answer_revisions(self, rev_id_a: str, rev_id_b: str) -> dict[str, Any]:
        return self.session.diff_revisions(rev_id_a, rev_id_b)

    # Episodic Fact Operations ----------------------------------------------------------------
    def commit_fact(
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
        """Validate through admission control and commit to bi-temporal fact graph."""
        payload = {"subject": subject, "relation": relation, "object": object, "value": value}
        ok, reason = self.admission.validate_admission(payload, verification_status, evidence)
        if not ok:
            raise ValueError(f"Memory Admission Rejected: {reason}")

        return self.episodic.record_fact(
            project_id=project_id,
            subject=subject,
            relation=relation,
            object=object,
            value=value,
            unit=unit,
            manifest_id=manifest_id,
            verification_status=verification_status,
            confidence=confidence,
            evidence=evidence,
        )

    def get_active_facts(self, project_id: str, subject: str | None = None) -> list[EpisodicFact]:
        return self.episodic.get_active_facts(project_id, subject)

    def recall_facts(
        self, project_id: str, query: str, top_k: int = 10
    ) -> list[tuple[EpisodicFact, float]]:
        active = self.episodic.get_active_facts(project_id)
        return self.retriever.rank_facts(query, active, top_k=top_k)

    # Reflexion & Lessons ----------------------------------------------------------------------
    def record_reflexion(
        self,
        project_id: str,
        task_kind: str,
        failed_action: str,
        root_cause: str,
        countermeasure: str,
        manifest_id: str | None = None,
    ) -> ReflexionLesson:
        return self.episodic.record_lesson(
            project_id=project_id,
            task_kind=task_kind,
            failed_action=failed_action,
            root_cause=root_cause,
            countermeasure=countermeasure,
            manifest_id=manifest_id,
        )

    def get_reflexions(
        self, project_id: str, task_kind: str | None = None, limit: int = 5
    ) -> list[ReflexionLesson]:
        return self.episodic.get_lessons(project_id, task_kind, limit=limit)

    # Semantic Knowledge -----------------------------------------------------------------------
    def get_material(self, name_or_key: str) -> MaterialRecord | None:
        return self.semantic.get_material(name_or_key)

    def evaluate_standard_clause(self, clause_id: str, params: dict[str, float]) -> dict[str, Any]:
        clause = self.semantic.get_standard_clause(clause_id)
        if not clause:
            return {"compliant": False, "error": f"Unknown standard clause '{clause_id}'"}
        return clause.evaluate_compliance(params)


_DEFAULT_ENGINE: TribosMemoryEngine | None = None


def get_memory_engine() -> TribosMemoryEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = TribosMemoryEngine()
    return _DEFAULT_ENGINE
