"""Registry of pluggable EvidenceSources (see base.py). Features register theirs from tribos.extensions.*."""

from __future__ import annotations

from typing import Optional

from .base import CitationRecord, EvidenceSource, SourceRunState, share_source_run

_SOURCES: dict[str, EvidenceSource] = {}


def register_source(src: EvidenceSource) -> None:
    """Register (or replace) a source keyed by src.key."""
    if not src.key:
        raise ValueError("EvidenceSource.key must be set")
    share_source_run(src)  # one run per inquiry, shared with dependents (SourceRunState.source_result)
    _SOURCES[src.key] = src


def get_registered_source(key: str) -> EvidenceSource | None:
    """The registered source with this key (extensions are not loaded here), or None."""
    return _SOURCES.get(key)


def unregister_source(key: str) -> None:
    _SOURCES.pop(key, None)


def get_sources() -> list[EvidenceSource]:
    """All registered sources sorted by (order, key); loads the feature extensions first."""
    from ..extensions import load_extensions

    load_extensions()
    return sorted(_SOURCES.values(), key=lambda s: (s.order, s.key))


__all__ = [
    "CitationRecord",
    "EvidenceSource",
    "SourceRunState",
    "get_registered_source",
    "get_sources",
    "register_source",
    "unregister_source",
]
