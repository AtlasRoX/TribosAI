"""Publication integrity status (retractions, withdrawals, expressions of concern, corrections/errata)
for Archivon scholarly records, combining Crossref ``updated-by`` (including Retraction Watch) and
OpenAlex ``is_retracted`` flags.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterable
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from ..utils.http_limits import get_limiter
from .grading import EvidenceGrade

logger = logging.getLogger(__name__)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
CROSSREF_TIMEOUT_S = 6.0
CROSSREF_PAGE_SIZE = 50

NoticeKind = Literal[
    "retraction",
    "partial_retraction",
    "withdrawal",
    "removal",
    "expression_of_concern",
    "correction",
    "erratum",
]
StatusName = Literal[
    "retracted",
    "withdrawn",
    "partially_retracted",
    "expression_of_concern",
    "corrected",
    "none",
    "unchecked",
]


class IntegrityNotice(BaseModel):
    kind: NoticeKind
    source: Literal["crossref_publisher", "crossref_retraction_watch", "openalex", "source_metadata"]
    notice_pmid: str | None = None
    notice_doi: str | None = None
    date: str | None = None
    reference: str | None = None
    record_id: str | None = None


class IntegrityStatus(BaseModel):
    status: StatusName = "unchecked"
    notices: list[IntegrityNotice] = Field(default_factory=list)
    sources_checked: list[Literal["crossref", "openalex", "source_metadata"]] = Field(default_factory=list)
    crossref_error: str | None = None


class GradedArticle(BaseModel):
    article_key: str
    source: str = ""
    pmid: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    zbl_id: str | None = None
    mr_id: str | None = None
    ads_bibcode: str | None = None
    openalex_id: str | None = None
    title: str = ""
    journal: str = ""
    year: str = ""
    grade: EvidenceGrade
    integrity: IntegrityStatus
    is_integrity_notice: bool = False
    excluded_reason: str | None = None


class CrossrefBatchResult(BaseModel):
    status: Literal["checked", "partial", "unavailable", "skipped", "disabled"]
    error: str | None = None
    found: set[str] = Field(default_factory=set)
    notices: dict[str, list[IntegrityNotice]] = Field(default_factory=dict)
    requested: int = 0
    unchecked: list[str] = Field(default_factory=list)

    def check_label(self) -> str:
        if self.status == "unavailable":
            return f"unavailable: {self.error or 'unknown error'}"
        if self.status == "partial":
            return f"unavailable for {len(self.unchecked)} of {self.requested} DOIs: {self.error or 'unknown error'}"
        if self.status == "skipped":
            return f"skipped: {self.error or 'no DOIs'}"
        return self.status

    def covers(self, doi: str | None) -> bool:
        key = (doi or "").strip().lower()
        return bool(key) and self.status in ("checked", "partial") and key not in self.unchecked


_CROSSREF_KINDS: dict[str, NoticeKind] = {
    "retraction": "retraction",
    "partial_retraction": "partial_retraction",
    "withdrawal": "withdrawal",
    "removal": "removal",
    "expression_of_concern": "expression_of_concern",
    "correction": "correction",
    "corrigendum": "correction",
    "erratum": "erratum",
}

_KIND_STATUS: dict[str, StatusName] = {
    "retraction": "retracted",
    "withdrawal": "withdrawn",
    "removal": "withdrawn",
    "partial_retraction": "partially_retracted",
    "expression_of_concern": "expression_of_concern",
    "correction": "corrected",
    "erratum": "corrected",
}

_STATUS_RANK: dict[str, int] = {
    "retracted": 5,
    "withdrawn": 5,
    "partially_retracted": 4,
    "expression_of_concern": 3,
    "corrected": 2,
    "none": 1,
    "unchecked": 0,
}

CAVEAT_STATUSES = frozenset({"partially_retracted", "expression_of_concern"})
EXCLUDING_STATUSES = frozenset({"retracted", "withdrawn"})


def _status_from_notices(notices: Iterable[IntegrityNotice]) -> StatusName:
    best: StatusName = "none"
    for n in notices:
        status = _KIND_STATUS.get(n.kind, "none")
        if _STATUS_RANK[status] > _STATUS_RANK[best]:
            best = status
    return best


def normalize_update_type(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def parse_crossref_updates(items: Iterable[dict[str, Any]]) -> dict[str, list[IntegrityNotice]]:
    """Crossref work items -> {lowercased DOI: notices from its updated-by entries}."""
    out: dict[str, list[IntegrityNotice]] = {}
    for item in items or []:
        if not isinstance(item, dict) or not item.get("DOI"):
            continue
        doi = str(item["DOI"]).lower()
        notices = out.setdefault(doi, [])
        updates = item.get("updated-by") or item.get("update-to") or item.get("updates") or []
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            kind = _CROSSREF_KINDS.get(normalize_update_type(upd.get("type")))
            if not kind:
                continue
            source: Literal["crossref_retraction_watch", "crossref_publisher"] = (
                "crossref_retraction_watch"
                if str(upd.get("source") or "").lower() == "retraction-watch"
                else "crossref_publisher"
            )
            notices.append(
                IntegrityNotice(
                    kind=kind,
                    source=source,
                    notice_doi=str(upd.get("DOI")).lower() if upd.get("DOI") else None,
                    date=(upd.get("updated") or {}).get("date-time") if isinstance(upd.get("updated"), dict) else None,
                    record_id=str(upd.get("record-id")) if upd.get("record-id") else None,
                )
            )
    return out


def article_integrity(article: dict[str, Any], crossref: CrossrefBatchResult | None = None) -> IntegrityStatus:
    """Compute integrity status from inline article fields (OpenAlex/Crossref) and optional Crossref batch result."""
    notices: list[IntegrityNotice] = []
    sources: list[Literal["crossref", "openalex", "source_metadata"]] = []

    if article.get("is_retracted") is True or article.get("retracted") is True:
        src: Literal["openalex", "source_metadata"] = (
            "openalex" if str(article.get("source") or "").lower() == "openalex" else "source_metadata"
        )
        sources.append(src)
        notices.append(IntegrityNotice(kind="retraction", source=src, reference="Marked retracted in source metadata"))
    elif str(article.get("source") or "").lower() == "openalex" and "is_retracted" in article:
        sources.append("openalex")

    inline_updates = article.get("updated_by") or article.get("updated-by")
    if isinstance(inline_updates, list) and article.get("doi"):
        parsed = parse_crossref_updates([{"DOI": article["doi"], "updated-by": inline_updates}])
        if "crossref" not in sources:
            sources.append("crossref")
        notices.extend(parsed.get(str(article["doi"]).lower(), []))

    error: str | None = None
    key = str(article.get("doi") or "").strip().lower()
    if crossref is not None and key:
        if crossref.status == "unavailable" or (crossref.status == "partial" and key in crossref.unchecked):
            error = crossref.error or "unavailable"
        elif crossref.covers(key) and key in crossref.found:
            if "crossref" not in sources:
                sources.append("crossref")
            notices.extend(crossref.notices.get(key, []))

    if not sources:
        return IntegrityStatus(status="unchecked", notices=notices, sources_checked=[], crossref_error=error)
    return IntegrityStatus(
        status=_status_from_notices(notices),
        notices=notices,
        sources_checked=sources,
        crossref_error=error,
    )


def merge_integrity(
    base: IntegrityStatus | None,
    crossref: CrossrefBatchResult | None,
    doi: str | None,
) -> IntegrityStatus:
    notices: list[IntegrityNotice] = list(base.notices) if base else []
    sources: list[Literal["crossref", "openalex", "source_metadata"]] = list(base.sources_checked) if base else []
    error: str | None = None
    key = (doi or "").strip().lower()
    if crossref is not None:
        if crossref.status == "unavailable" or (crossref.status == "partial" and key and key in crossref.unchecked):
            error = crossref.error or "unavailable"
        elif crossref.covers(key) and key in crossref.found:
            if "crossref" not in sources:
                sources.append("crossref")
            notices.extend(crossref.notices.get(key, []))
    if not sources:
        return IntegrityStatus(status="unchecked", notices=notices, sources_checked=[], crossref_error=error)
    return IntegrityStatus(
        status=_status_from_notices(notices),
        notices=notices,
        sources_checked=sources,
        crossref_error=error,
    )


class CrossrefIntegrityClient:
    """Batched Crossref filter request for DOI integrity checks."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = CROSSREF_TIMEOUT_S,
        mailto: str | None = None,
    ) -> None:
        self.transport = transport
        self.timeout_s = timeout_s
        contact = os.getenv("TRIBOS_CONTACT_EMAIL", "").strip() or os.getenv("TRIBOS_CROSSREF_MAILTO", "").strip()
        self.mailto = mailto if mailto is not None else contact

    def _user_agent(self) -> str:
        base = "Tribos-Archivon/1.0 (integrity check)"
        return f"{base} (mailto:{self.mailto})" if self.mailto else base

    async def async_check_dois(self, dois: Iterable[str | None]) -> CrossrefBatchResult:
        requested = list(dict.fromkeys(str(d).strip().lower() for d in dois if d and str(d).strip()))
        wanted = [d for d in requested if "," not in d]
        unsendable = [d for d in requested if "," in d]
        if not requested:
            return CrossrefBatchResult(status="skipped", error="no DOIs")
        pages = [wanted[i : i + CROSSREF_PAGE_SIZE] for i in range(0, len(wanted), CROSSREF_PAGE_SIZE)]
        results = await asyncio.gather(*(self._check_page(page) for page in pages))
        found: set[str] = set()
        notices: dict[str, list[IntegrityNotice]] = {}
        unchecked: list[str] = list(unsendable)
        errors: list[str] = []
        failed_pages = False
        for page, res in zip(pages, results, strict=False):
            if res.status == "checked":
                found |= res.found
                notices.update(res.notices)
            else:
                failed_pages = True
                unchecked.extend(page)
                errors.append(res.error or "unknown error")
        error = "; ".join(dict.fromkeys(errors)) or None
        if not pages or len(unchecked) == len(requested):
            return CrossrefBatchResult(
                status="unavailable",
                error=error,
                requested=len(requested),
                unchecked=unchecked,
            )
        return CrossrefBatchResult(
            status="partial" if failed_pages else "checked",
            error=error,
            found=found,
            notices=notices,
            requested=len(requested),
            unchecked=unchecked,
        )

    async def _check_page(self, wanted: list[str]) -> CrossrefBatchResult:
        params: dict[str, str] = {
            "filter": ",".join(f"doi:{d}" for d in wanted),
            "select": "DOI,updated-by,type,title",
            "rows": str(CROSSREF_PAGE_SIZE),
        }
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(self.timeout_s),
                headers={"User-Agent": self._user_agent(), "Accept": "application/json"},
            ) as client:
                async with get_limiter("crossref", 0.2):
                    resp = await client.get(CROSSREF_WORKS_URL, params=params)
        except httpx.TimeoutException:
            return CrossrefBatchResult(status="unavailable", error="timeout")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref integrity check failed: %s", exc)
            return CrossrefBatchResult(status="unavailable", error=type(exc).__name__)
        if resp.status_code != 200:
            return CrossrefBatchResult(status="unavailable", error=f"HTTP {resp.status_code}")
        try:
            payload = resp.json()
            items = payload["message"]["items"]
            if not isinstance(items, list):
                raise ValueError("items is not a list")
        except Exception:  # noqa: BLE001
            return CrossrefBatchResult(status="unavailable", error="invalid response")
        notices = parse_crossref_updates(items)
        return CrossrefBatchResult(status="checked", found=set(notices), notices=notices)


def notice_year(notice: dict[str, Any]) -> str | None:
    date = str(notice.get("date") or "")
    if re.match(r"^\d{4}", date):
        return date[:4]
    m = re.search(r"\b(19|20)\d{2}\b", str(notice.get("reference") or ""))
    return m.group(0) if m else None


def source_names(notices: Iterable[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for n in notices:
        label = {
            "openalex": "OpenAlex",
            "source_metadata": "Source metadata",
            "crossref_retraction_watch": "Crossref/Retraction Watch",
            "crossref_publisher": "Crossref (publisher)",
        }.get(str(n.get("source")))
        if label and label not in names:
            names.append(label)
    return names


__all__ = [
    "CAVEAT_STATUSES",
    "CROSSREF_PAGE_SIZE",
    "CROSSREF_TIMEOUT_S",
    "CROSSREF_WORKS_URL",
    "CrossrefBatchResult",
    "CrossrefIntegrityClient",
    "EXCLUDING_STATUSES",
    "GradedArticle",
    "IntegrityNotice",
    "IntegrityStatus",
    "NoticeKind",
    "StatusName",
    "article_integrity",
    "merge_integrity",
    "normalize_update_type",
    "notice_year",
    "parse_crossref_updates",
    "source_names",
]
