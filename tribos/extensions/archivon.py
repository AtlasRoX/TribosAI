"""Extension module registering Archivon literature tools into the Tribos ToolRegistry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tribos.archivon.engine import ArchivonEngine

_DEFAULT_ENGINE: ArchivonEngine | None = None


def get_archivon_engine() -> ArchivonEngine:
    """Return the shared ArchivonEngine instance."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = ArchivonEngine()
    return _DEFAULT_ENGINE


class ArchivonLiteratureSearchInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Search query across mathematics, physics, and engineering literature.",
    )
    max_results: int = Field(
        default=15,
        ge=1,
        le=50,
        description="Maximum number of ranked passages/articles to return.",
    )
    sources: list[str] | None = Field(
        default=None,
        description="Optional subset of literature sources: arxiv, semantic_scholar, openalex, crossref, zbmath, ads.",
    )


class ArchivonPaperDetailsInput(BaseModel):
    identifier: str = Field(
        ...,
        min_length=1,
        description="Literature identifier (arXiv ID, DOI, Semantic Scholar ID, OpenAlex ID, Zbl ID, or ADS bibcode).",
    )


class ArchivonRecommendInput(BaseModel):
    paper_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Seed paper identifiers for Semantic Scholar recommendations (e.g. arXiv:1706.03762, DOI:..., or S2PaperId).",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Maximum number of recommended papers to return.",
    )


def _flatten_canonical_ids(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(v, str) and v:
            out[str(k)] = v
        elif isinstance(v, (list, tuple)) and v:
            joined = ",".join(str(item) for item in v if item)
            if joined:
                out[str(k)] = joined
    return out


async def execute_archivon_literature_search(
    query: str,
    max_results: int = 15,
    sources: list[str] | None = None,
) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        engine = get_archivon_engine()
        data = await engine.literature_search(query=query, max_results=max_results, sources=sources)
        return ToolResult(
            success=True,
            tool_name="archivon_literature_search",
            data=data,
            canonical_ids=_flatten_canonical_ids(data.get("canonical_ids")),
            metadata={"sources": (data.get("provenance") or {}).get("sources", [])},
        )
    except ValueError as exc:
        return ToolResult(
            success=False,
            tool_name="archivon_literature_search",
            error=str(exc),
            error_type=ErrorType.VALIDATION_ERROR,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="archivon_literature_search",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


async def execute_archivon_paper_details(identifier: str) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        engine = get_archivon_engine()
        data = await engine.get_paper_details(identifier=identifier)
        if not data.get("found", False):
            return ToolResult(
                success=False,
                tool_name="archivon_paper_details",
                data=data,
                error=str(data.get("error") or f"Paper not found: {identifier}"),
                error_type=ErrorType.NOT_FOUND,
            )
        return ToolResult(
            success=True,
            tool_name="archivon_paper_details",
            data=data,
            canonical_ids=_flatten_canonical_ids(data.get("canonical_ids")),
            metadata={"identifier": identifier},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="archivon_paper_details",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


async def execute_archivon_recommend(paper_ids: list[str], limit: int = 10) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        engine = get_archivon_engine()
        data = await engine.recommend_papers(paper_ids=paper_ids, limit=limit)
        return ToolResult(
            success=True,
            tool_name="archivon_recommend",
            data=data,
            canonical_ids=_flatten_canonical_ids(data.get("canonical_ids")),
            metadata={"seed_count": len(paper_ids)},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="archivon_recommend",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


def register_tools(registry: Any) -> None:
    """Register Archivon literature tools in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="archivon_literature_search",
            description=(
                "Search and synthesize peer-reviewed and preprint scientific literature across arXiv, "
                "Semantic Scholar, OpenAlex, Crossref, zbMATH Open, and NASA ADS with study-type grading "
                "and retraction/erratum verification."
            ),
            domain="archivon",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=ArchivonLiteratureSearchInput,
            canonical_id_types=["arxiv_id", "doi", "zbl_id", "bibcode", "s2_paper_id", "openalex_id"],
            timeout_seconds=30.0,
            tags=["literature", "arxiv", "semantic_scholar", "openalex", "crossref", "zbmath", "ads", "citations", "papers"],
            is_async=True,
        ),
        executor=execute_archivon_literature_search,
    )

    registry.register(
        ToolUniverseEntry(
            name="archivon_paper_details",
            description=(
                "Fetch detailed metadata, abstract, citations, and integrity status for a specific scientific paper "
                "by arXiv ID, DOI, Semantic Scholar ID, OpenAlex ID, Zbl ID, or ADS bibcode."
            ),
            domain="archivon",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=ArchivonPaperDetailsInput,
            canonical_id_types=["arxiv_id", "doi", "zbl_id", "bibcode", "s2_paper_id", "openalex_id"],
            timeout_seconds=20.0,
            tags=["literature", "paper", "details", "metadata", "arxiv", "doi", "citations"],
            is_async=True,
        ),
        executor=execute_archivon_paper_details,
    )

    registry.register(
        ToolUniverseEntry(
            name="archivon_recommend",
            description=(
                "Recommend related scientific papers given one or more seed paper identifiers (arXiv ID, DOI, or Semantic Scholar ID)."
            ),
            domain="archivon",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=ArchivonRecommendInput,
            canonical_id_types=["arxiv_id", "doi", "s2_paper_id"],
            timeout_seconds=20.0,
            tags=["literature", "recommend", "related_papers", "semantic_scholar", "citations"],
            is_async=True,
        ),
        executor=execute_archivon_recommend,
    )


__all__ = [
    "ArchivonLiteratureSearchInput",
    "ArchivonPaperDetailsInput",
    "ArchivonRecommendInput",
    "execute_archivon_literature_search",
    "execute_archivon_paper_details",
    "execute_archivon_recommend",
    "get_archivon_engine",
    "register_tools",
]
