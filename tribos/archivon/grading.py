"""Per-article evidence-tier grading for Archivon scholarly literature.

Classifies mathematical, physical, and engineering works into evidence tiers:
1. Formal proof / theorem (`formal_proof`) or Monograph / standard (`monograph_standard`)
2. Journal article (`peer_reviewed`; the key is historical: a journal venue, peer review not verified) or Survey / review
3. Conference proceedings (`conference`) or Book chapter (`book_chapter`)
4. Preprint (`preprint`, e.g., arXiv without journal publication)
5. Technical report (`technical_report`)
6. Unclassified (`unclassified`)
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

GRADING_POLICY_VERSION = "archivon-grading/2026-10-25"

# Registry work types (Crossref and OpenAlex `type`) decide the document type before any heuristic: a DOI is a
# registration, not a venue, so a chapter of a book is never a journal article because it has a DOI.
_CHAPTER_TYPES = {"book-chapter", "book-section", "book-part", "reference-entry", "chapter", "book-track"}
_BOOK_TYPES = {"book", "monograph", "edited-book", "reference-book", "book-set", "book-series", "standard"}
_PROCEEDINGS_TYPES = {"proceedings-article", "proceedings", "conference-paper", "proceedings-series"}
_REPORT_TYPES = {"report", "report-component", "dissertation", "thesis"}
_JOURNAL_TYPES = {"journal-article", "article", "review", "letter", "editorial"}


class StudyType(str, Enum):
    FORMAL_PROOF = "formal_proof"
    THEOREM_PROOF = "theorem_proof"
    EXPERIMENTAL_MEASUREMENT = "experimental_measurement"
    NUMERICAL_SIMULATION = "numerical_simulation"
    MONOGRAPH_STANDARD = "monograph_standard"
    BOOK_CHAPTER = "book_chapter"
    PEER_REVIEWED = "peer_reviewed"
    REVIEW = "review"
    CONFERENCE = "conference"
    PREPRINT = "preprint"
    TECHNICAL_REPORT = "technical_report"
    UNCLASSIFIED = "unclassified"


class GradeBasis(str, Enum):
    SOURCE_METADATA = "source_metadata"
    ZB_MATH = "zbmath_msc"
    JOURNAL_VENUE = "journal_venue"
    HEURISTIC = "text_heuristic"
    NONE = "none"


STUDY_TYPE_POLICY: dict[StudyType, tuple[int, float]] = {
    StudyType.FORMAL_PROOF: (1, 1.0),
    StudyType.THEOREM_PROOF: (1, 1.0),
    StudyType.EXPERIMENTAL_MEASUREMENT: (2, 0.95),
    StudyType.NUMERICAL_SIMULATION: (2, 0.9),
    StudyType.MONOGRAPH_STANDARD: (1, 0.95),
    StudyType.BOOK_CHAPTER: (3, 0.8),
    StudyType.PEER_REVIEWED: (2, 0.9),
    StudyType.REVIEW: (2, 0.85),
    StudyType.CONFERENCE: (3, 0.75),
    StudyType.PREPRINT: (4, 0.6),
    StudyType.TECHNICAL_REPORT: (5, 0.45),
    StudyType.UNCLASSIFIED: (6, 0.3),
}

STUDY_TYPE_LABELS: dict[StudyType, tuple[str, str, str]] = {
    StudyType.FORMAL_PROOF: ("Formal proof / theorem", "formal proof", "formal proofs"),
    StudyType.THEOREM_PROOF: ("Theorem / proof", "theorem proof", "theorem proofs"),
    StudyType.EXPERIMENTAL_MEASUREMENT: ("Experimental measurement", "experimental measurement", "experimental measurements"),
    StudyType.NUMERICAL_SIMULATION: ("Numerical simulation", "numerical simulation", "numerical simulations"),
    StudyType.MONOGRAPH_STANDARD: ("Monograph / standard", "monograph/standard", "monographs/standards"),
    StudyType.BOOK_CHAPTER: ("Book chapter", "book chapter", "book chapters"),
    StudyType.PEER_REVIEWED: ("Journal article", "journal article", "journal articles"),
    StudyType.REVIEW: ("Survey / review", "review", "reviews"),
    StudyType.CONFERENCE: ("Conference proceedings", "conference paper", "conference papers"),
    StudyType.PREPRINT: ("Preprint", "preprint", "preprints"),
    StudyType.TECHNICAL_REPORT: ("Technical report", "technical report", "technical reports"),
    StudyType.UNCLASSIFIED: ("Unclassified", "unclassified", "unclassified"),
}

NOTICE_PUBTYPES = frozenset({
    "retraction of publication",
    "retraction notice",
    "retraction",
    "expression of concern",
    "expression-of-concern",
    "published erratum",
    "erratum",
    "correction",
})

_PROOF_RE = re.compile(
    r"\b(?:theorem|proof\s+of|lemma|corollary|conjecture|formal\s+verification|lean\s*4|coq|isabelle)\b",
    re.I,
)
_EXP_RE = re.compile(
    r"\b(?:experimental|experiment|experiments|measurement|measurements|detector|detectors|observational|observation|observatory|collider|spectroscopy|microscopy)\b",
    re.I,
)
_SIM_RE = re.compile(
    r"\b(?:numerical\s+simulation|numerical\s+simulations|simulations|simulation|finite[\s\-]element|monte\s+carlo|in\s+silico|molecular\s+dynamics|computational\s+fluid\s+dynamics|cfd|lattice\s+qcd|agent[\s\-]based\s+model)\b",
    re.I,
)
_REVIEW_RE = re.compile(
    r"\b(?:survey\s+of|a\s+survey|review\s+of|a\s+review|state\s+of\s+the\s+art|colloquium|tutorial)\b",
    re.I,
)
_STANDARD_RE = re.compile(
    r"\b(?:IEEE\s+Std|ISO/IEC|ASME|ASTM|NIST\s+SP|CODATA\s+recommended|monograph|handbook)\b",
    re.I,
)
_CONF_RE = re.compile(
    r"\b(?:proceedings|conference|symposium|workshop|neurips|icml|iclr|cvpr|stoc|focs|soda|acm\s+sig)\b",
    re.I,
)


class EvidenceGrade(BaseModel):
    study_type: StudyType
    label: str
    tier: int
    weight: float
    basis: GradeBasis
    cues: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    is_preprint: bool = False
    indexed_pub_types: list[str] = Field(default_factory=list)
    inferred_design: str | None = None
    inferred_cue: str | None = None
    mixed_design: bool = False
    design_note: str = ""
    indexed_design: str | None = None
    # Kept apart: what the document is, whether it is published, what is known about review, where the metadata came from.
    document_type: str = "unknown"  # journal article | book chapter | book | conference paper | preprint | report | unknown
    publication_status: str = "unknown"  # published | preprint | unknown
    peer_review: str = "unknown"  # "journal venue (review not verified)" | "not peer reviewed" | "unknown"
    metadata_source: str = ""  # crossref | openalex | arxiv | zbmath | ...


def _plain(text: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def make_grade(
    study_type: StudyType,
    basis: GradeBasis,
    cues: Iterable[str],
    confidence: Literal["high", "medium", "low"] = "medium",
    is_preprint: bool = False,
) -> EvidenceGrade:
    tier, weight = STUDY_TYPE_POLICY[study_type]
    return EvidenceGrade(
        study_type=study_type,
        label=STUDY_TYPE_LABELS[study_type][0],
        tier=tier,
        weight=weight,
        basis=basis,
        cues=list(cues),
        confidence=confidence,
        is_preprint=is_preprint,
    )


def is_preprint(article: dict[str, Any]) -> bool:
    source = str(article.get("source") or "").lower()
    journal = str(article.get("journal") or article.get("venue") or "").lower()
    doi = str(article.get("doi") or "").lower()
    pub_type = str(article.get("type") or article.get("pub_type") or "").lower()
    if pub_type in ("posted-content", "preprint"):
        return True
    if doi.startswith("10.48550/arxiv"):
        return not bool(journal and "arxiv" not in journal)
    if source == "arxiv":
        # If it has a non-arXiv journal and non-arXiv DOI, it was published in a journal
        if journal and "arxiv" not in journal and doi and not doi.startswith("10.48550/arxiv"):
            return False
        return True
    return "arxiv" in journal or "preprint" in journal


def is_integrity_notice(article: dict[str, Any]) -> bool:
    title = _plain(article.get("title")).lower()
    if title.startswith(("retraction:", "retracted:", "withdrawal:", "erratum:", "corrigendum:", "expression of concern:")):
        return True
    pub_type = str(article.get("type") or article.get("pub_type") or "").lower()
    return pub_type in NOTICE_PUBTYPES


def grade_article(article: dict[str, Any]) -> EvidenceGrade:
    """Classify an article into an EvidenceGrade, with its document type, publication status and review status."""
    grade = _grade(article)
    pub_type = str(article.get("type") or article.get("pub_type") or "").strip().lower()
    st = grade.study_type
    if pub_type in _CHAPTER_TYPES:
        doc = "book chapter"
    elif pub_type in _BOOK_TYPES or st == StudyType.MONOGRAPH_STANDARD:
        doc = "book"
    elif pub_type in _PROCEEDINGS_TYPES or st == StudyType.CONFERENCE:
        doc = "conference paper"
    elif grade.is_preprint or st == StudyType.PREPRINT:
        doc = "preprint"
    elif pub_type in _REPORT_TYPES or st == StudyType.TECHNICAL_REPORT:
        doc = "report"
    elif pub_type in _JOURNAL_TYPES or (st in (StudyType.PEER_REVIEWED, StudyType.REVIEW) and article.get("journal")):
        doc = "journal article"
    else:
        doc = "unknown"
    grade.document_type = doc
    grade.publication_status = "preprint" if doc == "preprint" else ("published" if doc != "unknown" else "unknown")
    grade.peer_review = (
        "not peer reviewed" if doc == "preprint"
        else "journal venue (review not verified)" if doc == "journal article"
        else "unknown"
    )
    grade.metadata_source = str(article.get("source") or "")
    return grade


def _grade(article: dict[str, Any]) -> EvidenceGrade:
    """The tier-bearing study type from the registry work type, venue, zbMATH MSC, DOI, and text cues."""
    title = _plain(article.get("title"))
    abstract = _plain(article.get("summary") or article.get("abstract") or article.get("passage_text"))
    journal = _plain(article.get("journal") or article.get("venue"))
    source = str(article.get("source") or "").lower()
    msc = article.get("msc") or []
    doi = str(article.get("doi") or "").lower()
    preprint_flag = is_preprint(article)

    combined = f"{title} {abstract}"
    work_type = str(article.get("type") or article.get("pub_type") or "").strip().lower()

    # 0. The registry's work type, when given, is the document type.
    if work_type in _CHAPTER_TYPES:
        return make_grade(StudyType.BOOK_CHAPTER, GradeBasis.SOURCE_METADATA, [f"type: {work_type}", journal or doi],
                          confidence="high", is_preprint=False)
    if work_type in _BOOK_TYPES:
        return make_grade(StudyType.MONOGRAPH_STANDARD, GradeBasis.SOURCE_METADATA, [f"type: {work_type}", journal or doi],
                          confidence="high", is_preprint=False)
    if work_type in _PROCEEDINGS_TYPES:
        return make_grade(StudyType.CONFERENCE, GradeBasis.SOURCE_METADATA, [f"type: {work_type}", journal or doi],
                          confidence="high", is_preprint=preprint_flag)
    if work_type in _REPORT_TYPES:
        return make_grade(StudyType.TECHNICAL_REPORT, GradeBasis.SOURCE_METADATA, [f"type: {work_type}"],
                          confidence="high", is_preprint=False)

    # 1. zbMATH or explicit mathematical proof/theorem
    if source == "zbmath" or msc or article.get("zbl_id"):
        if _PROOF_RE.search(combined) or msc:
            cues = [f"MSC: {msc[0]}"] if msc else ["zbMATH indexed"]
            return make_grade(
                StudyType.THEOREM_PROOF,
                GradeBasis.ZB_MATH,
                cues,
                confidence="high",
                is_preprint=preprint_flag,
            )

    # 2. Standards & monographs
    if _STANDARD_RE.search(f"{title} {journal}") or str(article.get("type") or "").lower() in ("book", "monograph", "standard"):
        return make_grade(
            StudyType.MONOGRAPH_STANDARD,
            GradeBasis.SOURCE_METADATA,
            [journal or "monograph/standard"],
            confidence="high",
            is_preprint=False,
        )

    # 3. Formal proof / theorem in peer-reviewed or preprint paper
    m_proof = _PROOF_RE.search(title) or _PROOF_RE.search(abstract)
    if m_proof and not preprint_flag and (doi or journal):
        return make_grade(
            StudyType.THEOREM_PROOF,
            GradeBasis.HEURISTIC,
            [f'proof cue: "{m_proof.group(0)}"', journal or doi],
            confidence="high" if (doi and journal) else "medium",
            is_preprint=False,
        )

    # 4. Experimental measurement
    m_exp = _EXP_RE.search(title) or _EXP_RE.search(abstract)
    if m_exp and not preprint_flag and (doi or journal):
        return make_grade(
            StudyType.EXPERIMENTAL_MEASUREMENT,
            GradeBasis.HEURISTIC,
            [f'experimental cue: "{m_exp.group(0)}"', journal or doi],
            confidence="high" if (doi and journal) else "medium",
            is_preprint=False,
        )

    # 5. Numerical simulation
    m_sim = _SIM_RE.search(title) or _SIM_RE.search(abstract)
    if m_sim and not preprint_flag and (doi or journal):
        return make_grade(
            StudyType.NUMERICAL_SIMULATION,
            GradeBasis.HEURISTIC,
            [f'simulation cue: "{m_sim.group(0)}"', journal or doi],
            confidence="high" if (doi and journal) else "medium",
            is_preprint=False,
        )

    # 6. Survey / review
    m_rev = _REVIEW_RE.search(title)
    if m_rev or "review" in journal.lower():
        return make_grade(
            StudyType.REVIEW,
            GradeBasis.JOURNAL_VENUE if "review" in journal.lower() else GradeBasis.HEURISTIC,
            [journal or f'title: "{m_rev.group(0) if m_rev else "review"}"'],
            confidence="high" if "review" in journal.lower() else "medium",
            is_preprint=preprint_flag,
        )

    # 5. Conference proceedings
    pub_type = str(article.get("type") or article.get("pub_type") or "").lower()
    if "proceedings" in pub_type or "conference" in pub_type or _CONF_RE.search(journal):
        return make_grade(
            StudyType.CONFERENCE,
            GradeBasis.JOURNAL_VENUE,
            [journal or pub_type],
            confidence="high",
            is_preprint=preprint_flag,
        )

    # 6. Journal article: a journal venue (from the record), not a DOI alone. A DOI with no venue and no work type is
    # a registered work of unknown type (below).
    if not preprint_flag and journal and "arxiv" not in journal.lower() and (work_type in _JOURNAL_TYPES or not work_type):
        return make_grade(
            StudyType.PEER_REVIEWED,
            GradeBasis.JOURNAL_VENUE,
            [journal],
            confidence="high" if work_type in _JOURNAL_TYPES else "medium",
            is_preprint=False,
        )

    # 7. Preprint (arXiv, etc.)
    if preprint_flag or article.get("arxiv_id"):
        cues = [f"arXiv:{article['arxiv_id']}"] if article.get("arxiv_id") else [source or "preprint"]
        if m_proof:
            cues.append(f'proof cue: "{m_proof.group(0)}"')
        return make_grade(
            StudyType.PREPRINT,
            GradeBasis.SOURCE_METADATA,
            cues,
            confidence="high",
            is_preprint=True,
        )

    return make_grade(
        StudyType.UNCLASSIFIED,
        GradeBasis.NONE,
        [],
        confidence="low",
        is_preprint=False,
    )


def summarize_grades(grades: Iterable[EvidenceGrade]) -> dict[str, int]:
    counts: dict[str, int] = {}
    total = 0
    for g in grades:
        key = g.study_type.value if isinstance(g.study_type, StudyType) else str(g.study_type)
        counts[key] = counts.get(key, 0) + 1
        total += 1
    counts["total"] = total
    return counts


def summary_phrases(grade_summary: dict[str, int], *args: Any, **kwargs: Any) -> list[str]:
    phrases: list[str] = []
    ordered = sorted(
        [(k, v) for k, v in grade_summary.items() if k != "total"],
        key=lambda kv: STUDY_TYPE_POLICY.get(
            StudyType(kv[0]) if kv[0] in StudyType._value2member_map_ else StudyType.UNCLASSIFIED,
            (99, 0.0),
        )[0],
    )
    for st_name, count in ordered:
        if count <= 0:
            continue
        if st_name in StudyType._value2member_map_:
            st = StudyType(st_name)
            _, sing, plur = STUDY_TYPE_LABELS[st]
            phrases.append(f"{count} {sing if count == 1 else plur}")
        else:
            phrases.append(f"{count} {st_name.replace('_', ' ')}")
    return phrases


def basis_phrase(grade: dict[str, Any]) -> str:
    basis = str(grade.get("basis") or "")
    if basis in (GradeBasis.SOURCE_METADATA.value, "pubtype", "source_metadata"):
        return "source metadata"
    if basis == GradeBasis.ZB_MATH.value:
        return "zbMATH"
    if basis == GradeBasis.JOURNAL_VENUE.value:
        return "journal venue"
    if basis == GradeBasis.HEURISTIC.value:
        return "text heuristic"
    return "unclassified"


__all__ = [
    "EvidenceGrade",
    "GRADING_POLICY_VERSION",
    "GradeBasis",
    "NOTICE_PUBTYPES",
    "STUDY_TYPE_LABELS",
    "STUDY_TYPE_POLICY",
    "StudyType",
    "basis_phrase",
    "grade_article",
    "is_integrity_notice",
    "is_preprint",
    "make_grade",
    "summarize_grades",
    "summary_phrases",
]
