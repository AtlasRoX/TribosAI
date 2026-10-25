"""Archivon scholarly literature synthesis and reference intelligence engine.

Queries up to 6 scholarly sources in parallel (arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH Open,
NASA ADS), deduplicates works across sources by normalized DOI / arXiv ID / title hash, grades evidence
tiers, checks publication integrity, and ranks passages against the query.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from typing import Any

import httpx

from .clients import ArchivonClients, SourceError
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

logger = logging.getLogger(__name__)

MAX_PINNED = 8  # requested identifiers fetched per search
PINNED_CONCURRENCY = 4  # identifier lookups in flight at once
MAX_EXTRA_QUERIES = 2  # planned queries (search_queries) run besides the topical query
MAX_RECOMMEND_SEEDS = 5
# arXiv allows one request every three seconds, so it runs the topical query only; the planned extra queries go to
# the other sources.
_SINGLE_QUERY_SOURCES = frozenset({"arxiv"})
# Field-prefixed Lucene syntax (EuropePMC's TITLE_ABS:"x", PUB_YEAR:[..]) that none of the Archivon sources parse.
_LUCENE_FIELD_RE = re.compile(r"\b[A-Z][A-Z_]{2,}:")

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
    return "title:" + hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


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


def _planned_queries(
    topical: str, search_queries: list[Any] | None, year_from: int | None
) -> list[tuple[str, int | None]]:
    """[(query text, earliest year)]: the topical query first, then up to MAX_EXTRA_QUERIES distinct planned queries
    (plain strings, or {"query", "from_year"} items as SearchPlan.scholarly_queries builds them). Lucene-syntax
    queries are skipped: no Archivon source understands them."""
    out: list[tuple[str, int | None]] = [(topical, year_from)]
    seen = {" ".join(topical.lower().split())}
    for item in search_queries or []:
        if len(out) > MAX_EXTRA_QUERIES:
            break
        if isinstance(item, str):
            text, from_year = item, None
        elif isinstance(item, dict):
            text, from_year = str(item.get("query") or ""), item.get("from_year")
        else:
            continue
        text = " ".join(text.split())[:300]
        key = text.lower()
        if not text or key in seen or _LUCENE_FIELD_RE.search(text):
            continue
        seen.add(key)
        try:
            q_year = int(from_year) if from_year is not None else None
        except (TypeError, ValueError):
            q_year = None
        if year_from and (q_year is None or q_year < year_from):
            q_year = year_from
        out.append((text, q_year))
    return out


def _canonical_ids(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"arxiv_ids": [], "dois": [], "zbl_ids": [], "ads_bibcodes": [], "openalex_ids": []}
    for rec in records:
        for bucket, value in (("arxiv_ids", rec.get("arxiv_id")), ("dois", rec.get("doi")), ("zbl_ids", rec.get("zbl_id")),
                              ("ads_bibcodes", rec.get("ads_bibcode")), ("openalex_ids", rec.get("openalex_id"))):
            s = str(value or "").strip()
            if s and s not in out[bucket]:
                out[bucket].append(s)
    return out


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


# Qualifiers that name a different model than the plain one: a paper on the quantum, fractional or nonlinear
# variant of a system does not support statements about the classical linear system the question states. A title
# with such a qualifier the query does not use is demoted (its terms still match, its subject does not).
MODEL_VARIANT_TERMS = (
    "quantum", "fractional", "nonlinear", "non-linear", "stochastic", "random", "relativistic", "nonlocal", "non-local",
    "time-dependent", "time-varying", "variable mass", "variable-mass", "coulomb", "dry friction", "duffing", "chaotic",
    "chaos", "lindblad", "bohm", "hidden-variable", "mittag-leffler", "inverted", "delay", "delayed", "discrete",
    "lattice", "fuzzy", "market", "markets", "economic", "financial", "network of", "biological", "neural",
    "higher-order", "parametric", "magnetic", "plasma", "optical", "thermal",
)
RELEVANCE_FLOOR = 0.3  # fraction of query terms a work must match to be kept (pinned works always are)


def model_variant_penalty(article: dict[str, Any], query_text: str) -> tuple[float, list[str]]:
    """(multiplier, qualifiers) for title qualifiers naming a model variant the query does not mention."""
    title = str(article.get("title") or "").lower()
    query = (query_text or "").lower()
    found = [q for q in MODEL_VARIANT_TERMS if re.search(rf"(?<![a-z]){re.escape(q)}(?![a-z])", title)
             and not re.search(rf"(?<![a-z]){re.escape(q)}(?![a-z])", query)]
    return (max(0.25, 0.55 ** len(found)) if found else 1.0), found


def term_coverage(article: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 1.0
    combined = f"{article.get('title') or ''} {article.get('summary') or article.get('abstract') or ''}".lower()
    return sum(1 for t in terms if t in combined) / len(terms)


def score_article_passage(
    article: dict[str, Any],
    terms: list[str],
    grade_weight: float = 0.6,
    query_text: str = "",
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
    penalty, _found = model_variant_penalty(article, query_text or " ".join(terms))
    return round((0.55 * term_score + 0.25 * grade_weight + cite_bonus + abstract_bonus) * penalty, 4)


def _format_authors(authors: Any, fallback: str = "") -> str:
    if isinstance(authors, list):
        names = [str(a).strip() for a in authors if str(a).strip()]
        if not names:
            return fallback or "Unknown"
        return ", ".join(names[:6]) + (" et al." if len(names) > 6 else "")
    if isinstance(authors, str) and authors.strip():
        return authors.strip()
    return fallback or "Unknown"


# Record types that are not scholarly works (Crossref / OpenAlex): datasets, figures and supplements ("component"),
# front matter and reviews of a paper.
_NON_WORK_TYPES = frozenset({"dataset", "component", "paratext", "peer-review", "grant", "database"})
# DOIs of parts of an article (eLife "elife.12613.018", PLOS figures ".g001") and of data repositories (ESA, HydroShare,
# figshare, Dryad, Harvard Dataverse, GBIF).
_NON_WORK_DOI_RE = re.compile(
    r"^10\.7554/elife\.\d+\.\d{3}$|^10\.1371/journal\.\w+\.\d+\.[gts]\d{3}$|"
    r"^10\.(?:5270|4211|6084|5061|7910|15468)/",
    re.I,
)
# A title that is only an identifier ("S1-X-SPEDE-2-EDR-EP-MONITORING", "GIO-C-NMS-4-86P"): a data product, not a paper.
_IDENTIFIER_TITLE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.\-]{5,}$")
MAX_TITLE_CHARS = 300


def is_scholarly_work(rec: dict[str, Any]) -> bool:
    """Whether a search record is a paper, preprint, book or chapter rather than a dataset, figure or data product."""
    if str(rec.get("type") or "").strip().lower() in _NON_WORK_TYPES:
        return False
    if _NON_WORK_DOI_RE.search(str(rec.get("doi") or "").strip()):
        return False
    return not _IDENTIFIER_TITLE_RE.match(str(rec.get("title") or "").strip())


def clip_title(title: Any) -> str:
    """A title as a title: some sources put a whole article body in the field."""
    text = " ".join(str(title or "").split())
    return text if len(text) <= MAX_TITLE_CHARS else text[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] + "…"


def _citation_label(rec: dict[str, Any], authors_str: str) -> str:
    lead = authors_str.split(",")[0].strip() if authors_str else ""
    if " " in lead:
        lead = lead.split()[-1]
    # Sources send a missing year as None, "None" or "", and a missing author as "Unknown": leave them out of the
    # label rather than printing "[Unknown et al., None | ...]".
    year_raw = str(rec.get("year") or "").strip()
    year = year_raw if re.fullmatch(r"\d{4}", year_raw) else ""
    if lead.lower() in ("", "unknown", "none", "null", "anonymous"):
        lead = ""
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
    head = ", ".join(part for part in (f"{lead} et al." if lead else "", year) if part)
    return f"[{head} | {ident}]" if head else f"[{ident}]"


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
        search_queries: list[Any] | None = None,
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
        limitations: list[str] = []
        raw_records: list[dict[str, Any]] = []

        # 1. Pinned / explicit identifiers, fetched concurrently (arXiv ids in one id_list request)
        pinned, missing = await self._fetch_pinned(explicit_ids[:MAX_PINNED])
        raw_records.extend({**rec, "_pinned": True} for rec in pinned)
        if missing:
            limitations.append(f"requested identifier(s) not found: {', '.join(missing)}")
        if len(explicit_ids) > MAX_PINNED:
            limitations.append(
                f"{len(explicit_ids) - MAX_PINNED} requested identifier(s) beyond the first {MAX_PINNED} were not fetched"
            )

        # 2. Fan the topical query and up to MAX_EXTRA_QUERIES planned queries out across the requested sources
        queries = _planned_queries(topical_q, search_queries, year_from)
        tasks: list[tuple[str, int, asyncio.Future[Any]]] = []
        for qi, (q_text, q_year) in enumerate(queries):
            for src in requested_sources:
                if qi and src in _SINGLE_QUERY_SOURCES:
                    continue
                search = self._search_source(src, q_text, per_source_limit, q_year)
                tasks.append((src, qi, asyncio.ensure_future(search)))

        status: dict[str, dict[str, Any]] = {src: {"source": src, "status": "error", "count": 0} for src in requested_sources}
        answered: dict[str, int] = dict.fromkeys(requested_sources, 0)
        errors: dict[str, list[SourceError]] = {src: [] for src in requested_sources}
        results = await asyncio.gather(*(t for _, _, t in tasks), return_exceptions=True) if tasks else []
        for (src, qi, _), res in zip(tasks, results, strict=False):
            if isinstance(res, BaseException):
                if not isinstance(res, Exception):
                    raise res  # cancellation and other control flow propagate
                errors[src].append(res if isinstance(res, SourceError)
                                   else SourceError(src, "error", f"{type(res).__name__}: {res}"[:300]))
                continue
            items, note = res
            if note and "skipped" in note.lower():
                status[src]["status"] = "skipped"
                if note not in limitations:
                    limitations.append(note)
                continue
            if note and note not in limitations:
                limitations.append(note)
            answered[src] += 1
            q_year = queries[qi][1]
            for item in items or []:
                if q_year and str(item.get("year") or "").isdigit() and int(str(item["year"])) < q_year:
                    continue
                raw_records.append(item)
                status[src]["count"] += 1
        for src, st in status.items():
            if st["status"] == "skipped":
                continue
            failed = errors[src]
            if answered[src]:
                st["status"] = "ok" if st["count"] else "empty"
                if failed:
                    st["failed_queries"] = len(failed)
                    limitations.append(f"{src}: {len(failed)} of {len(failed) + answered[src]} queries failed "
                                       f"({failed[0].error_type})")
            elif failed:
                st["error_type"], st["error"] = failed[0].error_type, failed[0].message
                limitations.append(f"{src} search failed ({failed[0].error_type}): {failed[0].message}")
        sources_queried = [s for s, st in status.items() if st["status"] in ("ok", "empty")]
        sources_skipped = [s for s, st in status.items() if st["status"] == "skipped"]
        sources_failed = [s for s, st in status.items() if st["status"] == "error"]
        partial = bool(sources_failed) or any(st.get("failed_queries") for st in status.values())
        # Every source that was asked failed: an outage, not "no literature on this topic".
        all_failed = bool(sources_failed) and not sources_queried
        queries_run = [queries[qi][0] for qi in sorted({qi for _, qi, _ in tasks})]

        # Filter by year_from if specified
        if year_from:
            filtered_by_year: list[dict[str, Any]] = []
            for r in raw_records:
                y_str = str(r.get("year") or "")
                if y_str.isdigit() and int(y_str) < int(year_from):
                    continue
                filtered_by_year.append(r)
            raw_records = filtered_by_year

        # Only scholarly works reach the evidence; a record requested by identifier stays whatever its type.
        raw_records = [r for r in raw_records if r.get("_pinned") or is_scholarly_work(r)]
        for r in raw_records:
            r["_pinned_keep"] = bool(r.pop("_pinned", False))
            r["title"] = clip_title(r.get("title"))
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
            score = score_article_passage(rec, terms, grade_weight=grade.weight, query_text=topical_q)
            included_records.append((score, rec, grade, integrity))

        included_records.sort(key=lambda item: item[0], reverse=True)
        # A relevance floor: works matching too few of the query's terms are left out (requested identifiers stay); at
        # least three works remain when any were found, so a sparse topic still returns its best matches.
        kept = [r for r in included_records
                if r[1].get("_pinned_keep") or term_coverage(r[1], terms) >= RELEVANCE_FLOOR]
        below_floor = len(included_records) - len(kept)
        if len(kept) < 3:
            kept = included_records[: max(3, len(kept))]
            below_floor = len(included_records) - len(kept)
        if below_floor:
            limitations.append(f"{below_floor} retrieved work(s) matched too few of the query terms and were left out")
        # Works about another variant of the model (quantum, fractional, nonlinear, ...) than the query states are left
        # out when at least three works on the stated model remain; they are named in the limitations, not hidden.
        on_model = [r for r in kept if r[1].get("_pinned_keep") or not model_variant_penalty(r[1], topical_q)[1]]
        if len(on_model) >= 3 and len(on_model) < len(kept):
            variants = sorted({v for r in kept for v in model_variant_penalty(r[1], topical_q)[1]})
            limitations.append(
                f"{len(kept) - len(on_model)} work(s) on other model variants ({', '.join(variants[:6])}) were left out"
            )
            kept = on_model
        top_records = kept[: max(1, max_articles)]

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
            passage_id = "arch_" + hashlib.sha1(pid_seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
            citation = _citation_label(rec, authors_str)

            year_raw = str(rec.get("year") or "").strip()
            _variant_penalty, variant_terms = model_variant_penalty(rec, topical_q)
            passage_dict: dict[str, Any] = {
                "passage_id": passage_id,
                "title": str(rec.get("title") or ""),
                "passage_text": passage_text,
                "authors": authors_str,
                "year": year_raw if year_raw[:4].isdigit() else "",
                "model_variant": variant_terms,
                "term_coverage": round(term_coverage(rec, terms), 3),
                "document_type": grade.document_type,
                "publication_status": grade.publication_status,
                "peer_review": grade.peer_review,
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
        source_status = [status[src] for src in requested_sources]

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
                "sources_failed": sources_failed,
                "source_status": source_status,
                "explicit_ids": explicit_ids,
                "total_raw_records": len(raw_records),
                "total_deduped_records": len(deduped),
            },
            "integrity_check": {
                "crossref": crossref_batch.check_label() if crossref_batch is not None else "not_run",
            },
            "limitations": limitations,
            "evidence_sufficiency": "SUFFICIENT" if ranked_passages else "INSUFFICIENT",
            # Per-source outcome (ok / empty / skipped / error with error_type): a failed source makes the result
            # partial, so the tool cache never replays it; every source failing is an upstream failure.
            "source_status": source_status,
            "sources_failed": sources_failed,
            "partial": partial,
            "all_sources_failed": all_failed,
            "upstream_failed": all_failed,
            "provenance": {
                "grading_policy_version": GRADING_POLICY_VERSION,
                "sources_queried": sources_queried,
                "sources_skipped": sources_skipped,
                "skipped_sources": sources_skipped,
                "sources_failed": sources_failed,
            },
        }

    async def _search_source(
        self, src: str, query: str, limit: int, year_from: int | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """(records, note) from one source; a failed search raises (SourceError from the clients)."""
        c = self.clients
        if src == "arxiv":
            return await c.search_arxiv(query, max_results=limit), None
        if src == "semantic_scholar":
            return await c.search_semantic_scholar(query, limit=limit, year_from=year_from)
        if src == "openalex":
            return await c.search_openalex(query, limit=limit, year_from=year_from), None
        if src == "crossref":
            return await c.search_crossref(query, rows=limit, year_from=year_from), None
        if src == "zbmath":
            return await c.search_zbmath(query, results_per_page=limit), None
        if src == "ads":
            return await c.search_ads(query, rows=limit)
        return [], None

    async def _fetch_pinned(self, identifiers: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """(records, identifiers not found) for requested identifiers. arXiv ids go to arXiv in one id_list request
        (ids it does not return are looked up on Semantic Scholar); the others are fetched concurrently, at most
        PINNED_CONCURRENCY at a time, so a handful of DOIs fits the tool's timeout (LOG-9)."""
        arxiv_ids: list[str] = []
        others: list[str] = []
        for ident in identifiers:
            kind, norm_id = normalize_literature_id(ident)
            if kind == "arxiv" and norm_id:
                arxiv_ids.append(split_arxiv_version(norm_id)[0])
            else:
                others.append(ident)
        gate = asyncio.Semaphore(PINNED_CONCURRENCY)

        async def bounded(make: Any) -> dict[str, Any] | None:
            async with gate:
                try:
                    return await make()
                except Exception as exc:  # noqa: BLE001 - a lookup that fails is a missing identifier
                    logger.warning("Pinned identifier lookup failed: %s: %s", type(exc).__name__, exc)
                    return None

        async def arxiv_batch() -> tuple[list[dict[str, Any]], list[str]]:
            if not arxiv_ids:
                return [], []
            try:
                recs = await self.clients.search_arxiv("", max_results=len(arxiv_ids), id_list=arxiv_ids)
            except SourceError as exc:
                logger.warning("arXiv id_list lookup failed: %s", exc)
                recs = []
            got = {split_arxiv_version(str(r.get("arxiv_id") or ""))[0].lower() for r in recs}
            rest = [i for i in arxiv_ids if i.lower() not in got]
            s2 = await asyncio.gather(*(
                bounded(lambda i=i: self.clients.fetch_semantic_scholar_paper(f"ARXIV:{i}")) for i in rest
            ))
            return [*recs, *(r for r in s2 if r)], [i for i, r in zip(rest, s2, strict=False) if not r]

        batch, singles = await asyncio.gather(
            arxiv_batch(),
            asyncio.gather(*(bounded(lambda i=i: self._fetch_single_record(i)) for i in others)),
        )
        records, missing = batch
        records = [*records, *(r for r in singles if r)]
        missing = [*missing, *(i for i, r in zip(others, singles, strict=False) if not r)]
        return records, missing

    async def _fetch_single_record(self, identifier: str) -> dict[str, Any] | None:
        kind, norm_id = normalize_literature_id(identifier)
        target = norm_id or identifier.strip()

        if kind == "arxiv":
            try:
                recs = await self.clients.search_arxiv(target, max_results=1, id_list=[target])
            except SourceError as exc:
                logger.warning("arXiv lookup of %s failed: %s", target, exc)
                recs = []
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
            try:
                recs, _ = await self.clients.search_ads(f"bibcode:{target}", rows=1)
            except SourceError as exc:
                logger.warning("NASA ADS lookup of %s failed: %s", target, exc)
                return None
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
        kind, norm_id = normalize_literature_id(identifier)
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
        kind, norm_id = normalize_literature_id(identifier)
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
                try:
                    oa_hits = await self.clients.search_openalex(str(seed["title"]), limit=limit + 1)
                except SourceError as exc:
                    limitations.append(str(exc))
                    oa_hits = []
                seed_title_norm = str(seed["title"]).strip().lower()
                recs = [r for r in oa_hits if str(r.get("title") or "").strip().lower() != seed_title_norm][:limit]

        recommendations = [self._recommendation(rec) for rec in deduplicate_articles(recs)[: max(1, min(20, limit))]]
        return {
            "seed_identifier": identifier,
            "seed_identifiers": [identifier],
            "normalized_id": norm_id or identifier,
            "count": len(recommendations),
            "recommendations": recommendations,
            "canonical_ids": _canonical_ids(recommendations),
            "limitations": limitations,
            # Semantic Scholar failed (rate limit, HTTP error) and the fallback found nothing: no answer, not "none".
            "upstream_failed": bool(note) and not recommendations,
        }

    @staticmethod
    def _recommendation(rec: dict[str, Any]) -> dict[str, Any]:
        return {
            **rec,
            "paper_id": rec.get("s2_paper_id") or rec.get("paper_id"),
            "doi": normalize_doi(rec.get("doi") or "") or None,
            "arxiv_id": str(rec["arxiv_id"]).strip() if rec.get("arxiv_id") else None,
            "openalex_id": str(rec["openalex_id"]).strip() if rec.get("openalex_id") else None,
            "grade_label": grade_article(rec).label,
        }

    async def recommend_papers(self, seed_identifiers: Any, limit: int = 5) -> dict[str, Any]:
        """Recommend related papers for one or more seed identifiers (at most MAX_RECOMMEND_SEEDS): each seed's
        recommendations are merged round-robin, deduplicated across seeds, and the seeds themselves left out."""
        raw = seed_identifiers if isinstance(seed_identifiers, (list, tuple)) else [seed_identifiers]
        seeds = list(dict.fromkeys(str(s).strip() for s in raw if str(s or "").strip()))[:MAX_RECOMMEND_SEEDS]
        if len(seeds) <= 1:
            return await self.recommend(seeds[0] if seeds else "", limit=limit)
        results = await asyncio.gather(*(self.recommend(s, limit=limit) for s in seeds), return_exceptions=True)
        limitations: list[str] = []
        lists: list[list[dict[str, Any]]] = []
        failed = 0
        for seed, res in zip(seeds, results, strict=False):
            if isinstance(res, BaseException):
                if not isinstance(res, Exception):
                    raise res
                failed += 1
                limitations.append(f"recommendations for {seed} failed: {type(res).__name__}")
                continue
            failed += bool(res.get("upstream_failed"))
            limitations.extend(f"{seed}: {n}" for n in res.get("limitations") or [])
            lists.append(list(res.get("recommendations") or []))
        merged = [lst[i] for i in range(max((len(lst) for lst in lists), default=0)) for lst in lists if i < len(lst)]
        seed_keys = {f"{kind}:{(norm or '').lower()}" for kind, norm in (normalize_literature_id(s) for s in seeds) if norm}
        merged = [r for r in merged if not ({f"doi:{str(r.get('doi') or '').lower()}",
                                             f"arxiv:{str(r.get('arxiv_id') or '').lower()}"} & seed_keys)]
        recommendations = deduplicate_articles(merged)[: max(1, min(20, limit))]
        return {
            "seed_identifier": seeds[0],
            "seed_identifiers": seeds,
            "normalized_id": normalize_literature_id(seeds[0])[1] or seeds[0],
            "count": len(recommendations),
            "recommendations": recommendations,
            "canonical_ids": _canonical_ids(recommendations),
            "limitations": limitations,
            "upstream_failed": failed == len(seeds) and not recommendations,
        }

    get_paper_details = paper_details


__all__ = [
    "ALL_SOURCES",
    "ArchivonEngine",
    "deduplicate_articles",
    "score_article_passage",
]
