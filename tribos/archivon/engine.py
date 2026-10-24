"""Archivon scholarly literature synthesis and reference intelligence engine.

Queries up to 6 scholarly sources in parallel (arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH Open,
NASA ADS), deduplicates works across sources by normalized DOI / arXiv ID / title hash, grades evidence
tiers, checks publication integrity, and ranks passages against the query.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Any

import httpx

from .clients import ADS_SKIPPED_NOTE, ArchivonClients
from .grading import (
    GRADING_POLICY_VERSION,
    grade_article,
    is_integrity_notice,
    is_preprint,
    summarize_grades,
)
from .identifiers import (
    extract_literature_ids,
    normalize_doi,
    normalize_literature_id,
    split_arxiv_version,
    strip_literature_ids,
)
from .integrity import (
    EXCLUDING_STATUSES,
    CrossrefBatchResult,
    CrossrefIntegrityClient,
    GradedArticle,
    article_integrity,
)

ALL_SOURCES: tuple[str, ...] = (
    "arxiv",
    "semantic_scholar",
    "openalex",
    "crossref",
    "zbmath",
    "ads",
)

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "what", "which", "how", "why", "when", "where",
    "are", "was", "were", "have", "has", "had", "can", "could", "should", "would", "about", "over", "under",
    "between", "find", "papers", "paper", "articles", "article", "literature", "search", "using", "show",
})


def _title_hash(title: str) -> str | None:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    if len(words) < 4:
        return None
    normalized = " ".join(words)
    return "title:" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _identity_keys(rec: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    doi = normalize_doi(rec.get("doi") or "")
    if doi and not doi.startswith("10.48550/arxiv."):
        keys.append(f"doi:{doi}")
    arxiv_raw = rec.get("arxiv_id") or ""
    if not arxiv_raw and doi.startswith("10.48550/arxiv."):
        arxiv_raw = doi.split("10.48550/arxiv.", 1)[1]
    if arxiv_raw:
        vless, _ = split_arxiv_version(str(arxiv_raw))
        if vless:
            keys.append(f"arxiv:{vless.lower()}")
    if rec.get("zbl_id"):
        keys.append(f"zbl:{str(rec['zbl_id']).strip().lower()}")
    if rec.get("ads_bibcode"):
        keys.append(f"ads:{str(rec['ads_bibcode']).strip()}")
    if rec.get("openalex_id"):
        keys.append(f"openalex:{str(rec['openalex_id']).strip().upper()}")
    thash = _title_hash(str(rec.get("title") or ""))
    if thash:
        keys.append(thash)
    return keys


def _merge_article_pair(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    # Prefer non-preprint journal venue over preprint
    if is_preprint(merged) and not is_preprint(secondary) and secondary.get("journal"):
        merged["journal"] = secondary["journal"]
    for field in (
        "doi",
        "arxiv_id",
        "arxiv_id_versioned",
        "zbl_id",
        "mr_id",
        "ads_bibcode",
        "openalex_id",
        "pmid",
        "s2_paper_id",
        "pdf_url",
        "url",
        "year",
        "published",
        "primary_category",
    ):
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]
    # Keep non-arXiv DOI if primary had 10.48550/arXiv
    if (
        str(merged.get("doi") or "").startswith("10.48550/arxiv")
        and secondary.get("doi")
        and not str(secondary["doi"]).startswith("10.48550/arxiv")
    ):
        merged["doi"] = secondary["doi"]

    # Keep longer summary/abstract
    sum1 = str(merged.get("summary") or merged.get("abstract") or "")
    sum2 = str(secondary.get("summary") or secondary.get("abstract") or "")
    if len(sum2) > len(sum1):
        merged["summary"] = sum2
        merged["abstract"] = sum2

    if not merged.get("authors") and secondary.get("authors"):
        merged["authors"] = secondary["authors"]
        merged["author_string"] = secondary.get("author_string") or ", ".join(secondary["authors"])

    if secondary.get("msc") and not merged.get("msc"):
        merged["msc"] = secondary["msc"]

    merged["citation_count"] = max(
        int(merged.get("citation_count") or 0),
        int(secondary.get("citation_count") or 0),
    )
    if secondary.get("is_retracted") or merged.get("is_retracted"):
        merged["is_retracted"] = True
    if secondary.get("updated_by") and not merged.get("updated_by"):
        merged["updated_by"] = secondary["updated_by"]

    sources_seen = list(dict.fromkeys([
        *(merged.get("sources") or [merged.get("source")]),
        *(secondary.get("sources") or [secondary.get("source")]),
    ]))
    merged["sources"] = [s for s in sources_seen if s]
    return merged


def deduplicate_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate article records across sources by normalized DOI, arXiv ID, Zbl ID, bibcode, or title hash."""
    deduped: list[dict[str, Any]] = []
    key_to_idx: dict[str, int] = {}

    for rec in articles:
        if not isinstance(rec, dict) or not (rec.get("title") or rec.get("zbl_id") or rec.get("arxiv_id") or rec.get("doi")):
            continue
        keys = _identity_keys(rec)
        existing_idx = next((key_to_idx[k] for k in keys if k in key_to_idx), None)
        if existing_idx is None:
            idx = len(deduped)
            copy_rec = dict(rec)
            copy_rec.setdefault("sources", [rec.get("source")] if rec.get("source") else [])
            deduped.append(copy_rec)
            for k in keys:
                key_to_idx[k] = idx
        else:
            merged = _merge_article_pair(deduped[existing_idx], rec)
            deduped[existing_idx] = merged
            for k in _identity_keys(merged):
                key_to_idx[k] = existing_idx
    return deduped


def _query_terms(query: str, extra_keywords: list[str] | None = None) -> list[str]:
    words = [
        w.lower()
        for w in re.findall(r"[A-Za-z0-9_\-]+", query or "")
        if len(w) > 2 and w.lower() not in _STOPWORDS
    ]
    for kw in extra_keywords or []:
        for w in re.findall(r"[A-Za-z0-9_\-]+", str(kw)):
            if len(w) > 2 and w.lower() not in _STOPWORDS:
                words.append(w.lower())
    return list(dict.fromkeys(words))


def score_article_passage(
    article: dict[str, Any],
    terms: list[str],
    grade_weight: float = 0.6,
) -> float:
    title = str(article.get("title") or "").lower()
    summary = str(article.get("summary") or article.get("abstract") or "").lower()
    combined = f"{title} {summary}"
    if not terms:
        term_score = 0.5
    else:
        hits = sum(1.0 + (0.5 if t in title else 0.0) for t in terms if t in combined)
        term_score = min(1.0, hits / max(1.0, len(terms)))
    citations = max(0, int(article.get("citation_count") or 0))
    cite_bonus = min(0.25, 0.05 * math.log10(1 + citations)) if citations > 0 else 0.0
    abstract_bonus = 0.1 if len(summary) >= 60 else 0.0
    return round(0.55 * term_score + 0.25 * grade_weight + cite_bonus + abstract_bonus, 4)


def _format_authors(authors: Any, fallback: str = "") -> str:
    if isinstance(authors, list):
        names = [str(a).strip() for a in authors if str(a).strip()]
        if not names:
            return fallback or "Unknown"
        return ", ".join(names[:6]) + (" et al." if len(names) > 6 else "")
    if isinstance(authors, str) and authors.strip():
        return authors.strip()
    return fallback or "Unknown"


def _citation_label(rec: dict[str, Any], authors_str: str) -> str:
    lead = authors_str.split(",")[0].strip() if authors_str else "Unknown"
    if " " in lead:
        lead = lead.split()[-1]
    year = str(rec.get("year") or "n.d.")
    if rec.get("arxiv_id"):
        ident = f"arXiv:{rec['arxiv_id']}"
    elif rec.get("doi"):
        ident = f"DOI:{rec['doi']}"
    elif rec.get("zbl_id"):
        ident = f"Zbl {rec['zbl_id']}"
    elif rec.get("ads_bibcode"):
        ident = f"ADS:{rec['ads_bibcode']}"
    elif rec.get("openalex_id"):
        ident = rec["openalex_id"]
    else:
        ident = str(rec.get("source") or "Archivon")
    return f"[{lead} et al., {year} | {ident}]"


class ArchivonEngine:
    """Multi-source scholarly literature search, paper details, and recommendation engine."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 15.0,
        check_integrity: bool = True,
        clients: ArchivonClients | None = None,
        integrity_client: CrossrefIntegrityClient | None = None,
    ) -> None:
        self.transport = transport or (clients.transport if clients else None)
        self.timeout_s = timeout_s
        self.check_integrity = check_integrity
        self.clients = clients or ArchivonClients(transport=self.transport, timeout_s=timeout_s)
        self.integrity_client = integrity_client or CrossrefIntegrityClient(transport=self.transport, timeout_s=min(6.0, timeout_s))

    async def literature_search(
        self,
        query: str,
        max_articles: int = 8,
        sources: list[str] | None = None,
        year_from: int | None = None,
        keywords: list[str] | None = None,
        pinned_ids: list[str] | None = None,
        search_queries: list[dict[str, Any]] | None = None,
        check_integrity: bool | None = None,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        if max_results is not None:
            max_articles = max_results
        clean_q = (query or "").strip()
        explicit_ids = list(dict.fromkeys([*(pinned_ids or []), *extract_literature_ids(clean_q)]))
        topical_q = strip_literature_ids(clean_q) or clean_q

        requested_sources = [
            s.strip().lower()
            for s in (sources or list(ALL_SOURCES))
            if s and s.strip().lower() in ALL_SOURCES
        ]
        if not requested_sources:
            requested_sources = list(ALL_SOURCES)

        per_source_limit = max(3, min(15, max_articles))
        sources_queried: list[str] = []
        sources_skipped: list[str] = []
        limitations: list[str] = []
        raw_records: list[dict[str, Any]] = []

        # 1. Fetch pinned / explicit identifiers first
        for ident in explicit_ids[:5]:
            detail = await self._fetch_single_record(ident)
            if detail:
                raw_records.append(detail)

        # 2. Fan out across requested sources in parallel
        tasks: list[ tuple[str, asyncio.Task[Any]] ] = []
        for src in requested_sources:
            if src == "arxiv":
                tasks.append((src, asyncio.ensure_future(self.clients.search_arxiv(topical_q, max_results=per_source_limit))))
            elif src == "semantic_scholar":
                tasks.append((src, asyncio.ensure_future(self.clients.search_semantic_scholar(topical_q, limit=per_source_limit, year_from=year_from))))
            elif src == "openalex":
                tasks.append((src, asyncio.ensure_future(self.clients.search_openalex(topical_q, limit=per_source_limit, year_from=year_from))))
            elif src == "crossref":
                tasks.append((src, asyncio.ensure_future(self.clients.search_crossref(topical_q, rows=per_source_limit, year_from=year_from))))
            elif src == "zbmath":
                tasks.append((src, asyncio.ensure_future(self.clients.search_zbmath(topical_q, results_per_page=per_source_limit))))
            elif src == "ads":
                tasks.append((src, asyncio.ensure_future(self.clients.search_ads(topical_q, rows=per_source_limit))))

        if tasks:
            results = await asyncio.gather(*(t for _, t in tasks), return_exceptions=True)
            for (src, _), res in zip(tasks, results, strict=False):
                if isinstance(res, Exception):
                    limitations.append(f"{src} search failed: {type(res).__name__}")
                    continue
                if src in ("semantic_scholar", "ads"):
                    items, note = res
                    if note:
                        if "skipped" in note.lower():
                            sources_skipped.append(src)
                            limitations.append(note)
                        else:
                            limitations.append(note)
                            sources_queried.append(src)
                    else:
                        sources_queried.append(src)
                    raw_records.extend(items or [])
                else:
                    sources_queried.append(src)
                    raw_records.extend(res or [])

        # Filter by year_from if specified
        if year_from:
            filtered_by_year: list[dict[str, Any]] = []
            for r in raw_records:
                y_str = str(r.get("year") or "")
                if y_str.isdigit() and int(y_str) < int(year_from):
                    continue
                filtered_by_year.append(r)
            raw_records = filtered_by_year

        deduped = deduplicate_articles(raw_records)

        # Optional Crossref batch integrity check when requested
        do_integrity = self.check_integrity if check_integrity is None else check_integrity
        crossref_batch: CrossrefBatchResult | None = None
        if do_integrity:
            dois_to_check = [r.get("doi") for r in deduped if r.get("doi")]
            if dois_to_check:
                crossref_batch = await self.integrity_client.async_check_dois(dois_to_check)

        terms = _query_terms(topical_q, keywords)
        graded_articles: list[dict[str, Any]] = []
        excluded_articles: list[dict[str, Any]] = []
        included_records: list[tuple[float, dict[str, Any], Any, Any]] = []

        for idx, rec in enumerate(deduped):
            grade = grade_article(rec)
            integrity = article_integrity(rec, crossref_batch)
            notice_flag = is_integrity_notice(rec)
            art_key = (
                f"doi:{rec['doi']}" if rec.get("doi")
                else (f"arxiv:{rec['arxiv_id']}" if rec.get("arxiv_id") else f"art:{idx}")
            )
            excluded_reason: str | None = None
            if notice_flag:
                excluded_reason = "integrity_notice"
            elif integrity.status in EXCLUDING_STATUSES:
                excluded_reason = integrity.status

            graded_obj = GradedArticle(
                article_key=art_key,
                source=str(rec.get("source") or ""),
                pmid=str(rec["pmid"]) if rec.get("pmid") else None,
                doi=str(rec["doi"]) if rec.get("doi") else None,
                arxiv_id=str(rec["arxiv_id"]) if rec.get("arxiv_id") else None,
                zbl_id=str(rec["zbl_id"]) if rec.get("zbl_id") else None,
                mr_id=str(rec["mr_id"]) if rec.get("mr_id") else None,
                ads_bibcode=str(rec["ads_bibcode"]) if rec.get("ads_bibcode") else None,
                openalex_id=str(rec["openalex_id"]) if rec.get("openalex_id") else None,
                title=str(rec.get("title") or ""),
                journal=str(rec.get("journal") or ""),
                year=str(rec.get("year") or ""),
                grade=grade,
                integrity=integrity,
                is_integrity_notice=notice_flag,
                excluded_reason=excluded_reason,
            )
            if excluded_reason:
                excluded_articles.append(graded_obj.model_dump())
                continue

            graded_articles.append(graded_obj.model_dump())
            score = score_article_passage(rec, terms, grade_weight=grade.weight)
            included_records.append((score, rec, grade, integrity))

        included_records.sort(key=lambda item: item[0], reverse=True)
        top_records = included_records[: max(1, max_articles)]

        ranked_passages: list[dict[str, Any]] = []
        articles_out: list[dict[str, Any]] = []
        canonical_ids: dict[str, list[str]] = {
            "arxiv_ids": [],
            "dois": [],
            "zbl_ids": [],
            "ads_bibcodes": [],
            "openalex_ids": [],
        }

        def _add_cid(bucket: str, val: Any | None) -> None:
            if val:
                s = str(val).strip()
                if s and s not in canonical_ids[bucket]:
                    canonical_ids[bucket].append(s)

        for rank_idx, (score, rec, grade, integrity) in enumerate(top_records, 1):
            authors_str = _format_authors(rec.get("authors"), str(rec.get("author_string") or ""))
            passage_text = str(rec.get("summary") or rec.get("abstract") or rec.get("title") or "").strip()
            doi = normalize_doi(rec.get("doi") or "") or None
            arxiv_id = str(rec["arxiv_id"]).strip() if rec.get("arxiv_id") else None
            zbl_id = str(rec["zbl_id"]).strip() if rec.get("zbl_id") else None
            mr_id = str(rec["mr_id"]).strip() if rec.get("mr_id") else None
            ads_bibcode = str(rec["ads_bibcode"]).strip() if rec.get("ads_bibcode") else None
            openalex_id = str(rec["openalex_id"]).strip() if rec.get("openalex_id") else None
            pmid = str(rec["pmid"]).strip() if rec.get("pmid") else None

            _add_cid("arxiv_ids", arxiv_id)
            _add_cid("dois", doi)
            _add_cid("zbl_ids", zbl_id)
            _add_cid("ads_bibcodes", ads_bibcode)
            _add_cid("openalex_ids", openalex_id)

            url = str(rec.get("url") or "")
            if not url:
                if arxiv_id:
                    url = f"https://arxiv.org/abs/{arxiv_id}"
                elif doi:
                    url = f"https://doi.org/{doi}"
                elif zbl_id:
                    url = f"https://zbmath.org/?q=an:{zbl_id}"
                elif ads_bibcode:
                    url = f"https://ui.adsabs.harvard.edu/abs/{ads_bibcode}/abstract"

            pid_seed = f"{doi or arxiv_id or zbl_id or ads_bibcode or openalex_id or rec.get('title')}:{rank_idx}"
            passage_id = "arch_" + hashlib.sha1(pid_seed.encode("utf-8")).hexdigest()[:12]
            citation = _citation_label(rec, authors_str)

            passage_dict: dict[str, Any] = {
                "passage_id": passage_id,
                "title": str(rec.get("title") or ""),
                "passage_text": passage_text,
                "authors": authors_str,
                "year": str(rec.get("year") or ""),
                "journal": str(rec.get("journal") or ""),
                "doi": doi,
                "arxiv_id": arxiv_id,
                "zbl_id": zbl_id,
                "mr_id": mr_id,
                "ads_bibcode": ads_bibcode,
                "bibcode": ads_bibcode,
                "openalex_id": openalex_id,
                "pmid": pmid,
                "url": url,
                "pdf_url": rec.get("pdf_url"),
                "source": str(rec.get("source") or "archivon"),
                "sources": rec.get("sources") or [rec.get("source")],
                "citation_count": int(rec.get("citation_count") or 0),
                "grade_label": grade.label,
                "score": score,
                "relevance_score": score,
                "section": "Abstract",
                "citation": citation,
                "evidence_grade": grade.model_dump(),
                "integrity_status": integrity.status,
                "retracted": True if integrity.status in EXCLUDING_STATUSES else (False if integrity.status != "unchecked" else None),
            }
            ranked_passages.append(passage_dict)

            articles_out.append({
                "title": passage_dict["title"],
                "authors": rec.get("authors") if isinstance(rec.get("authors"), list) else [authors_str],
                "author_string": authors_str,
                "year": passage_dict["year"],
                "journal": passage_dict["journal"],
                "summary": passage_text,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "arxiv_id_versioned": rec.get("arxiv_id_versioned"),
                "zbl_id": zbl_id,
                "mr_id": mr_id,
                "ads_bibcode": ads_bibcode,
                "bibcode": ads_bibcode,
                "openalex_id": openalex_id,
                "pmid": pmid,
                "msc": rec.get("msc") or [],
                "primary_category": rec.get("primary_category") or "",
                "url": url,
                "pdf_url": rec.get("pdf_url"),
                "source": passage_dict["source"],
                "sources": passage_dict["sources"],
                "citation_count": passage_dict["citation_count"],
                "grade_label": grade.label,
                "score": score,
            })

        grade_summary = summarize_grades(g for _, _, g, _ in top_records)
        queries_run = [q.get("query", topical_q) for q in (search_queries or []) if isinstance(q, dict)] or [topical_q]

        return {
            "query": clean_q,
            "total_found": len(articles_out),
            "passages": ranked_passages,
            "ranked_passages": ranked_passages,
            "articles": articles_out,
            "graded_articles": graded_articles,
            "excluded_articles": excluded_articles,
            "grade_summary": grade_summary,
            "canonical_ids": canonical_ids,
            "retrieval": {
                "queries": queries_run,
                "sources_queried": sources_queried,
                "sources_skipped": sources_skipped,
                "explicit_ids": explicit_ids,
                "total_raw_records": len(raw_records),
                "total_deduped_records": len(deduped),
            },
            "integrity_check": {
                "crossref": crossref_batch.check_label() if crossref_batch is not None else "not_run",
            },
            "limitations": limitations,
            "evidence_sufficiency": "SUFFICIENT" if ranked_passages else "INSUFFICIENT",
            "provenance": {
                "grading_policy_version": GRADING_POLICY_VERSION,
                "sources_queried": sources_queried,
                "sources_skipped": sources_skipped,
                "skipped_sources": sources_skipped,
            },
        }

    async def _fetch_single_record(self, identifier: str) -> dict[str, Any] | None:
        norm_id, kind = normalize_literature_id(identifier)
        target = norm_id or identifier.strip()

        if kind == "arxiv":
            recs = await self.clients.search_arxiv(target, max_results=1, id_list=[target])
            if recs:
                return recs[0]
            s2 = await self.clients.fetch_semantic_scholar_paper(f"ARXIV:{target}")
            return s2

        if kind == "doi":
            cr_task = asyncio.ensure_future(self.clients.fetch_crossref_doi(target))
            oa_task = asyncio.ensure_future(self.clients.fetch_openalex_work(f"https://doi.org/{target}"))
            s2_task = asyncio.ensure_future(self.clients.fetch_semantic_scholar_paper(f"DOI:{target}"))
            results = await asyncio.gather(cr_task, oa_task, s2_task, return_exceptions=True)
            valid = [r for r in results if isinstance(r, dict) and r]
            if not valid:
                return None
            dedup = deduplicate_articles(valid)
            return dedup[0] if dedup else valid[0]

        if kind == "zbl":
            return await self.clients.fetch_zbmath_document(target)

        if kind == "openalex":
            return await self.clients.fetch_openalex_work(target)

        if kind == "bibcode":
            recs, _ = await self.clients.search_ads(f"bibcode:{target}", rows=1)
            return recs[0] if recs else None

        if kind == "pmid":
            s2 = await self.clients.fetch_semantic_scholar_paper(f"PMID:{target}")
            if s2:
                return s2
            return await self.clients.fetch_openalex_work(f"pmid:{target}")

        # Fallback: try Semantic Scholar paper ID or arXiv/DOI search
        return await self.clients.fetch_semantic_scholar_paper(target)

    async def paper_details(self, identifier: str) -> dict[str, Any]:
        """Look up detailed metadata for a paper by arXiv ID, DOI, Zbl ID, OpenAlex W-ID, ADS bibcode, or S2 ID."""
        norm_id, kind = normalize_literature_id(identifier)
        rec = await self._fetch_single_record(identifier)
        if not rec:
            return {
                "found": False,
                "identifier": identifier,
                "normalized_id": norm_id,
                "id_kind": kind,
                "paper": None,
                "canonical_ids": {
                    "arxiv_ids": [],
                    "dois": [],
                    "zbl_ids": [],
                    "ads_bibcodes": [],
                    "openalex_ids": [],
                },
            }
        grade = grade_article(rec)
        integrity = article_integrity(rec)
        authors_str = _format_authors(rec.get("authors"), str(rec.get("author_string") or ""))
        doi = normalize_doi(rec.get("doi") or "") or None
        arxiv_id = str(rec["arxiv_id"]).strip() if rec.get("arxiv_id") else None
        zbl_id = str(rec["zbl_id"]).strip() if rec.get("zbl_id") else None
        ads_bibcode = str(rec["ads_bibcode"]).strip() if rec.get("ads_bibcode") else None
        openalex_id = str(rec["openalex_id"]).strip() if rec.get("openalex_id") else None

        canonical_ids = {
            "arxiv_ids": [arxiv_id] if arxiv_id else [],
            "dois": [doi] if doi else [],
            "zbl_ids": [zbl_id] if zbl_id else [],
            "ads_bibcodes": [ads_bibcode] if ads_bibcode else [],
            "openalex_ids": [openalex_id] if openalex_id else [],
        }
        paper = {
            **rec,
            "author_string": authors_str,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "zbl_id": zbl_id,
            "ads_bibcode": ads_bibcode,
            "openalex_id": openalex_id,
            "grade_label": grade.label,
            "evidence_grade": grade.model_dump(),
            "integrity_status": integrity.status,
        }
        return {
            "found": True,
            "identifier": identifier,
            "normalized_id": norm_id or identifier,
            "id_kind": kind,
            "paper": paper,
            "ranked_passages": [
                {
                    "passage_id": f"arch_detail_{(doi or arxiv_id or zbl_id or openalex_id or '0')[:12]}",
                    "title": str(rec.get("title") or ""),
                    "passage_text": str(rec.get("summary") or rec.get("abstract") or rec.get("title") or ""),
                    "authors": authors_str,
                    "year": str(rec.get("year") or ""),
                    "journal": str(rec.get("journal") or ""),
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "zbl_id": zbl_id,
                    "mr_id": rec.get("mr_id"),
                    "ads_bibcode": ads_bibcode,
                    "openalex_id": openalex_id,
                    "pmid": rec.get("pmid"),
                    "url": str(rec.get("url") or ""),
                    "source": str(rec.get("source") or "archivon"),
                    "citation_count": int(rec.get("citation_count") or 0),
                    "grade_label": grade.label,
                    "score": 1.0,
                }
            ],
            "canonical_ids": canonical_ids,
        }

    async def recommend(self, identifier: str, limit: int = 5) -> dict[str, Any]:
        """Recommend related papers for a seed paper identifier via Semantic Scholar Recommendations API
        (with OpenAlex/arXiv topical fallback if S2 recommendations are unavailable).
        """
        norm_id, kind = normalize_literature_id(identifier)
        if kind == "arxiv":
            s2_query_id = f"ARXIV:{norm_id}"
        elif kind == "doi":
            s2_query_id = f"DOI:{norm_id}"
        elif kind == "pmid":
            s2_query_id = f"PMID:{norm_id}"
        else:
            s2_query_id = identifier.strip()

        recs, note = await self.clients.recommend_semantic_scholar(s2_query_id, limit=limit)
        limitations: list[str] = []
        if note:
            limitations.append(note)

        # Fallback to OpenAlex related search if S2 returned nothing
        if not recs:
            seed = await self._fetch_single_record(identifier)
            if seed and seed.get("title"):
                oa_hits = await self.clients.search_openalex(str(seed["title"]), limit=limit + 1)
                seed_title_norm = str(seed["title"]).strip().lower()
                recs = [r for r in oa_hits if str(r.get("title") or "").strip().lower() != seed_title_norm][:limit]

        deduped = deduplicate_articles(recs)[: max(1, min(20, limit))]
        canonical_ids: dict[str, list[str]] = {
            "arxiv_ids": [],
            "dois": [],
            "zbl_ids": [],
            "ads_bibcodes": [],
            "openalex_ids": [],
        }
        recommendations: list[dict[str, Any]] = []
        for rec in deduped:
            grade = grade_article(rec)
            doi = normalize_doi(rec.get("doi") or "") or None
            arxiv_id = str(rec["arxiv_id"]).strip() if rec.get("arxiv_id") else None
            openalex_id = str(rec["openalex_id"]).strip() if rec.get("openalex_id") else None
            if arxiv_id and arxiv_id not in canonical_ids["arxiv_ids"]:
                canonical_ids["arxiv_ids"].append(arxiv_id)
            if doi and doi not in canonical_ids["dois"]:
                canonical_ids["dois"].append(doi)
            if openalex_id and openalex_id not in canonical_ids["openalex_ids"]:
                canonical_ids["openalex_ids"].append(openalex_id)
            recommendations.append({
                **rec,
                "paper_id": rec.get("s2_paper_id") or rec.get("paper_id"),
                "doi": doi,
                "arxiv_id": arxiv_id,
                "openalex_id": openalex_id,
                "grade_label": grade.label,
            })

        return {
            "seed_identifier": identifier,
            "normalized_id": norm_id or identifier,
            "count": len(recommendations),
            "recommendations": recommendations,
            "canonical_ids": canonical_ids,
            "limitations": limitations,
            "ads_skipped_note": ADS_SKIPPED_NOTE if False else None,
        }

    async def recommend_papers(self, seed_identifiers: Any, limit: int = 5) -> dict[str, Any]:
        """Recommend related papers for one or more seed identifiers."""
        if isinstance(seed_identifiers, list) and seed_identifiers:
            seed = str(seed_identifiers[0])
        else:
            seed = str(seed_identifiers or "")
        return await self.recommend(seed, limit=limit)

    get_paper_details = paper_details


__all__ = [
    "ALL_SOURCES",
    "ArchivonEngine",
    "deduplicate_articles",
    "score_article_passage",
]
