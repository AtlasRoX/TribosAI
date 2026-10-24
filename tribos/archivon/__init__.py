"""Archivon — Mathematical, Physical & Engineering Literature Engine.

Provides unified retrieval, deduplication, evidence grading, and retraction/erratum
checking across arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH Open, and NASA ADS.
"""

from .clients import (
    ArchivonClients,
    build_arxiv_search_query,
    parse_arxiv_atom,
    reconstruct_openalex_abstract,
)
from .engine import (
    ALL_SOURCES,
    ArchivonEngine,
    deduplicate_articles,
    score_article_passage,
)
from .grading import (
    GRADING_POLICY_VERSION,
    EvidenceGrade,
    GradeBasis,
    StudyType,
    grade_article,
    is_integrity_notice,
    is_preprint,
    summarize_grades,
    summary_phrases,
)
from .identifiers import (
    extract_literature_ids,
    extract_typed_literature_ids,
    normalize_doi,
    normalize_literature_id,
    split_arxiv_version,
    strip_literature_ids,
)
from .integrity import (
    CrossrefBatchResult,
    CrossrefIntegrityClient,
    GradedArticle,
    IntegrityNotice,
    IntegrityStatus,
    article_integrity,
    merge_integrity,
    notice_year,
    parse_crossref_updates,
    source_names,
)

__all__ = [
    "ALL_SOURCES",
    "ArchivonClients",
    "ArchivonEngine",
    "CrossrefBatchResult",
    "CrossrefIntegrityClient",
    "EvidenceGrade",
    "GRADING_POLICY_VERSION",
    "GradeBasis",
    "GradedArticle",
    "IntegrityNotice",
    "IntegrityStatus",
    "StudyType",
    "article_integrity",
    "build_arxiv_search_query",
    "deduplicate_articles",
    "extract_literature_ids",
    "extract_typed_literature_ids",
    "grade_article",
    "is_integrity_notice",
    "is_preprint",
    "merge_integrity",
    "normalize_doi",
    "normalize_literature_id",
    "notice_year",
    "parse_arxiv_atom",
    "parse_crossref_updates",
    "reconstruct_openalex_abstract",
    "score_article_passage",
    "source_names",
    "split_arxiv_version",
    "strip_literature_ids",
    "summarize_grades",
    "summary_phrases",
]
