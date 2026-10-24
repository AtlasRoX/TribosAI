"""Async HTTP clients for Archivon's 6 scholarly literature sources:
1. arXiv (Atom XML API)
2. Semantic Scholar (Graph v1 & Recommendations v1)
3. OpenAlex (Works REST API with inverted-abstract reconstruction)
4. Crossref (Works REST API with polite mailto pool)
5. zbMATH Open (Document search & lookup REST API)
6. NASA ADS (Search API gated on TRIBOS_ADS_API_TOKEN)
"""

from __future__ import annotations

import html
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from ..utils.http_limits import get_limiter
from .identifiers import normalize_doi, split_arxiv_version

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"
S2_RECOMMEND_URL = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
ZBMATH_SEARCH_URL = "https://api.zbmath.org/v1/document/_search"
ZBMATH_DOC_URL = "https://api.zbmath.org/v1/document"
ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"

ADS_SKIPPED_NOTE = "NASA ADS skipped (TRIBOS_ADS_API_TOKEN not set)"

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

_ARXIV_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "what", "which", "how", "why", "when", "where",
    "are", "was", "were", "have", "has", "had", "can", "could", "should", "would", "about", "over", "under",
    "between", "find", "papers", "paper", "articles", "article", "literature", "search",
})


def _contact_email() -> str:
    return (
        os.getenv("TRIBOS_CONTACT_EMAIL", "").strip()
        or os.getenv("TRIBOS_CROSSREF_MAILTO", "").strip()
    )


def _user_agent() -> str:
    email = _contact_email()
    base = "Tribos-Archivon/1.0"
    return f"{base} (mailto:{email})" if email else base


def _clean_jats(text: Any) -> str:
    """Strip JATS/HTML tags and collapse whitespace."""
    raw = html.unescape(str(text or ""))
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def build_arxiv_search_query(query: str, categories: list[str] | None = None) -> str:
    """Build an arXiv API `search_query` string joining plain terms with `AND` so spaces do not become OR."""
    q = (query or "").strip()
    base_q = ""
    if not q:
        base_q = "all:*"
    # Preserve explicit boolean queries or field-prefixed queries that already use AND/OR/ANDNOT
    elif re.search(r"\b(?:AND|OR|ANDNOT)\b", q) or re.search(r"\b(?:ti|au|abs|cat|co|jr|rn|id|all):", q):
        if " " in q and not re.search(r"\b(?:AND|OR|ANDNOT)\b", q) and '"' not in q:
            tokens = [t for t in q.split() if t]
            base_q = " AND ".join(tokens)
        else:
            base_q = q
    else:
        phrases = [m.group(1).strip() for m in re.finditer(r'"([^"]+)"', q) if m.group(1).strip()]
        remainder = re.sub(r'"[^"]+"', " ", q)
        words = [
            w for w in re.findall(r"[A-Za-z0-9_\-]+", remainder)
            if len(w) > 1 and w.lower() not in _ARXIV_STOPWORDS
        ]
        if not words and not phrases:
            words = [w for w in re.findall(r"[A-Za-z0-9_\-]+", remainder) if w]

        clauses: list[str] = [f'all:"{p}"' for p in phrases]
        clauses.extend(f"all:{w}" for w in words[:8])
        base_q = " AND ".join(clauses) if clauses else f"all:{q}"

    if categories:
        cat_terms = [f"cat:{c.strip()}" for c in categories if c and c.strip()]
        if cat_terms:
            cat_clause = " OR ".join(cat_terms)
            if len(cat_terms) > 1:
                cat_clause = f"({cat_clause})"
            if base_q and base_q != "all:*":
                return f"({base_q}) AND {cat_clause}"
            return cat_clause
    return base_q


def parse_arxiv_atom(xml_text: str) -> list[dict[str, Any]]:
    """Parse arXiv Atom XML response into normalized article dicts."""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("arXiv Atom XML parse failed: %s", exc)
        return []

    records: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        raw_id = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
        if not raw_id:
            continue
        # Skip arXiv API error pseudo-entries
        title_raw = _clean_jats(entry.findtext(f"{_ATOM_NS}title") or "")
        if title_raw.lower() == "error" and "arxiv.org/api/errors" in raw_id:
            continue

        versionless, version = split_arxiv_version(raw_id)
        versioned = f"{versionless}{version}" if version else versionless
        summary = _clean_jats(entry.findtext(f"{_ATOM_NS}summary") or "")
        published = (entry.findtext(f"{_ATOM_NS}published") or "").strip()
        year = published[:4] if len(published) >= 4 and published[:4].isdigit() else ""

        authors: list[str] = []
        for author_el in entry.findall(f"{_ATOM_NS}author"):
            name = (author_el.findtext(f"{_ATOM_NS}name") or "").strip()
            if name:
                authors.append(name)

        pdf_url: str | None = None
        abs_url = f"https://arxiv.org/abs/{versionless}"
        for link_el in entry.findall(f"{_ATOM_NS}link"):
            href = (link_el.attrib.get("href") or "").strip()
            title_attr = (link_el.attrib.get("title") or "").lower()
            link_type = (link_el.attrib.get("type") or "").lower()
            rel = (link_el.attrib.get("rel") or "").lower()
            if title_attr == "pdf" or link_type == "application/pdf":
                pdf_url = href
            elif rel == "alternate" and href:
                abs_url = href
        if not pdf_url and versionless:
            pdf_url = f"https://arxiv.org/pdf/{versioned or versionless}.pdf"

        prim_cat_el = entry.find(f"{_ARXIV_NS}primary_category")
        primary_category = (prim_cat_el.attrib.get("term") if prim_cat_el is not None else None) or ""
        categories = [
            c.attrib.get("term", "")
            for c in entry.findall(f"{_ATOM_NS}category")
            if c.attrib.get("term")
        ]
        if not primary_category and categories:
            primary_category = categories[0]

        doi_raw = (entry.findtext(f"{_ARXIV_NS}doi") or "").strip()
        doi = normalize_doi(doi_raw) if doi_raw else None
        journal_ref = _clean_jats(entry.findtext(f"{_ARXIV_NS}journal_ref") or "")

        records.append({
            "source": "arxiv",
            "arxiv_id": versionless,
            "arxiv_version": version,
            "arxiv_id_versioned": versioned,
            "doi": doi,
            "title": title_raw,
            "summary": summary,
            "abstract": summary,
            "published": published,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "pdf_url": pdf_url,
            "url": abs_url,
            "primary_category": primary_category,
            "categories": categories,
            "journal": journal_ref or (f"arXiv:{primary_category}" if primary_category else "arXiv"),
            "citation_count": 0,
        })
    return records


def reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Reconstruct plain abstract text from OpenAlex `abstract_inverted_index`."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for idx in idxs:
            if isinstance(idx, int) and idx >= 0:
                positions.append((idx, str(word)))
    if not positions:
        return ""
    positions.sort(key=lambda item: item[0])
    return _clean_jats(" ".join(word for _, word in positions))


class ArchivonClients:
    """HTTP client suite for arXiv, Semantic Scholar, OpenAlex, Crossref, zbMATH Open, and NASA ADS."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 15.0,
        ads_api_token: str | None = None,
    ) -> None:
        self.transport = transport
        self.timeout_s = timeout_s
        self.ads_api_token = ads_api_token

    def _client(self, extra_headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(self.timeout_s),
            headers=headers,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # 1. arXiv
    # ------------------------------------------------------------------
    async def search_arxiv(
        self,
        query: str,
        max_results: int = 8,
        id_list: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"max_results": str(max(1, min(50, max_results)))}
        if id_list:
            params["id_list"] = ",".join(split_arxiv_version(i)[0] for i in id_list if i)
        else:
            params["search_query"] = build_arxiv_search_query(query, categories=categories)
            params["sortBy"] = "relevance"
            params["sortOrder"] = "descending"

        try:
            async with self._client({"Accept": "application/atom+xml, application/xml, text/xml"}) as client:
                async with get_limiter("arxiv", 0.05 if self.transport else 3.0):
                    resp = await client.get(ARXIV_API_URL, params=params)
            if resp.status_code != 200:
                logger.warning("arXiv returned HTTP %s", resp.status_code)
                return []
            return parse_arxiv_atom(resp.text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 2. Semantic Scholar
    # ------------------------------------------------------------------
    def _s2_headers(self) -> dict[str, str]:
        key = os.getenv("TRIBOS_S2_API_KEY", "").strip()
        return {"x-api-key": key} if key else {}

    @staticmethod
    def _parse_s2_paper(item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title = _clean_jats(item.get("title") or "")
        if not title:
            return None
        ext_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
        doi = normalize_doi(ext_ids.get("DOI") or item.get("doi") or "") or None
        arxiv_raw = ext_ids.get("ArXiv") or item.get("arxiv_id") or ""
        arxiv_id = split_arxiv_version(str(arxiv_raw))[0] if arxiv_raw else None
        pmid = str(ext_ids.get("PubMed") or "").strip() or None
        authors_raw = item.get("authors") or []
        authors = [
            str(a.get("name")).strip()
            for a in authors_raw
            if isinstance(a, dict) and a.get("name")
        ]
        summary = _clean_jats(item.get("abstract") or item.get("tldr", {}).get("text") if isinstance(item.get("tldr"), dict) else item.get("abstract") or "")
        year = str(item.get("year") or "") if item.get("year") else ""
        venue = _clean_jats(item.get("venue") or (item.get("journal") or {}).get("name") if isinstance(item.get("journal"), dict) else item.get("venue") or "")
        oa_pdf = item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else {}
        pdf_url = oa_pdf.get("url")
        paper_id = str(item.get("paperId") or "").strip() or None
        url = str(item.get("url") or "").strip() or (f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else "")
        return {
            "source": "semantic_scholar",
            "paper_id": paper_id,
            "s2_paper_id": paper_id,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "pmid": pmid,
            "title": title,
            "summary": summary,
            "abstract": summary,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "journal": venue,
            "citation_count": int(item.get("citationCount") or 0),
            "pdf_url": pdf_url,
            "url": url,
        }

    async def search_semantic_scholar(
        self,
        query: str,
        limit: int = 8,
        year_from: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {
            "query": query,
            "limit": str(max(1, min(50, limit))),
            "fields": "paperId,externalIds,title,abstract,year,authors,venue,journal,citationCount,url,openAccessPdf",
        }
        if year_from:
            params["year"] = f"{int(year_from)}-"
        try:
            async with self._client(self._s2_headers()) as client:
                async with get_limiter("semantic_scholar", 0.05 if self.transport else 1.0):
                    resp = await client.get(S2_SEARCH_URL, params=params)
            if resp.status_code == 429:
                return [], "Semantic Scholar rate-limited (HTTP 429; set TRIBOS_S2_API_KEY for dedicated quota)"
            if resp.status_code != 200:
                return [], f"Semantic Scholar HTTP {resp.status_code}"
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else []
            out = [r for item in (data or []) if (r := self._parse_s2_paper(item)) is not None]
            return out, None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic Scholar search failed: %s", exc)
            return [], f"Semantic Scholar error: {type(exc).__name__}"

    async def fetch_semantic_scholar_paper(self, paper_identifier: str) -> dict[str, Any] | None:
        fields = "paperId,externalIds,title,abstract,year,authors,venue,journal,citationCount,referenceCount,url,openAccessPdf"
        url = f"{S2_PAPER_URL}/{quote(paper_identifier, safe=':/')}"
        try:
            async with self._client(self._s2_headers()) as client:
                resp = await client.get(url, params={"fields": fields})
            if resp.status_code != 200:
                return None
            return self._parse_s2_paper(resp.json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic Scholar paper details failed: %s", exc)
            return None

    async def recommend_semantic_scholar(self, paper_identifier: str, limit: int = 5) -> tuple[list[dict[str, Any]], str | None]:
        fields = "paperId,externalIds,title,abstract,year,authors,venue,citationCount,url,openAccessPdf"
        url = f"{S2_RECOMMEND_URL}/{quote(paper_identifier, safe=':/')}"
        try:
            async with self._client(self._s2_headers()) as client:
                resp = await client.get(url, params={"fields": fields, "limit": str(max(1, min(20, limit)))})
            if resp.status_code == 429:
                return [], "Semantic Scholar recommendations rate-limited (HTTP 429)"
            if resp.status_code != 200:
                return [], f"Semantic Scholar recommendations HTTP {resp.status_code}"
            payload = resp.json()
            items = payload.get("recommendedPapers") if isinstance(payload, dict) else []
            out = [r for item in (items or []) if (r := self._parse_s2_paper(item)) is not None]
            return out, None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic Scholar recommend failed: %s", exc)
            return [], f"Semantic Scholar error: {type(exc).__name__}"

    # ------------------------------------------------------------------
    # 3. OpenAlex
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_openalex_work(item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title = _clean_jats(item.get("title") or item.get("display_name") or "")
        if not title:
            return None
        raw_id = str(item.get("id") or "").strip()
        openalex_id = raw_id.rsplit("/", 1)[-1] if raw_id else None
        doi = normalize_doi(item.get("doi") or "") or None
        ids_dict = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        pmid_raw = str(ids_dict.get("pmid") or "").strip()
        pmid = pmid_raw.rsplit("/", 1)[-1] if pmid_raw else None

        arxiv_id: str | None = None
        if doi and doi.startswith("10.48550/arxiv."):
            arxiv_id = split_arxiv_version(doi.split("10.48550/arxiv.", 1)[1])[0]

        summary = _clean_jats(item.get("abstract") or "") or reconstruct_openalex_abstract(
            item.get("abstract_inverted_index")
        )
        year = str(item.get("publication_year") or "") if item.get("publication_year") else ""

        authors: list[str] = []
        for auth in item.get("authorships") or []:
            if isinstance(auth, dict):
                author_obj = auth.get("author") if isinstance(auth.get("author"), dict) else {}
                name = str(author_obj.get("display_name") or auth.get("raw_author_name") or "").strip()
                if name:
                    authors.append(name)

        prim_loc = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        src_obj = prim_loc.get("source") if isinstance(prim_loc.get("source"), dict) else {}
        journal = _clean_jats(src_obj.get("display_name") or "")
        url = str(prim_loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else raw_id) or "")
        pdf_url = prim_loc.get("pdf_url")

        return {
            "source": "openalex",
            "openalex_id": openalex_id,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "pmid": pmid,
            "title": title,
            "summary": summary,
            "abstract": summary,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "journal": journal,
            "citation_count": int(item.get("cited_by_count") or 0),
            "is_retracted": bool(item.get("is_retracted", False)),
            "type": str(item.get("type") or ""),
            "pdf_url": pdf_url,
            "url": url,
        }

    async def search_openalex(
        self,
        query: str,
        limit: int = 8,
        year_from: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "search": query,
            "per-page": str(max(1, min(50, limit))),
            "select": "id,doi,ids,title,display_name,publication_year,cited_by_count,authorships,primary_location,abstract_inverted_index,is_retracted,type",
        }
        api_key = os.getenv("TRIBOS_OPENALEX_API_KEY", "").strip()
        if api_key:
            params["api_key"] = api_key
        email = _contact_email()
        if email:
            params["mailto"] = email
        if year_from:
            params["filter"] = f"from_publication_date:{int(year_from)}-01-01"

        try:
            async with self._client() as client:
                async with get_limiter("openalex", 0.05 if self.transport else 0.2):
                    resp = await client.get(OPENALEX_WORKS_URL, params=params)
            if resp.status_code != 200:
                logger.warning("OpenAlex returned HTTP %s", resp.status_code)
                return []
            payload = resp.json()
            results = payload.get("results") if isinstance(payload, dict) else []
            return [r for item in (results or []) if (r := self._parse_openalex_work(item)) is not None]
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAlex search failed: %s", exc)
            return []

    async def fetch_openalex_work(self, identifier: str) -> dict[str, Any] | None:
        params: dict[str, str] = {}
        api_key = os.getenv("TRIBOS_OPENALEX_API_KEY", "").strip()
        if api_key:
            params["api_key"] = api_key
        email = _contact_email()
        if email:
            params["mailto"] = email
        url = f"{OPENALEX_WORKS_URL}/{quote(identifier, safe=':/')}"
        try:
            async with self._client() as client:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            return self._parse_openalex_work(resp.json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAlex fetch failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 4. Crossref
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_crossref_item(item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        titles = item.get("title") or []
        title_raw = titles[0] if isinstance(titles, list) and titles else (titles if isinstance(titles, str) else "")
        title = _clean_jats(title_raw)
        if not title:
            return None
        doi = normalize_doi(item.get("DOI") or "") or None
        summary = _clean_jats(item.get("abstract") or "")

        year = ""
        for date_field in ("published-print", "published-online", "issued", "created"):
            date_obj = item.get(date_field)
            if isinstance(date_obj, dict):
                parts = date_obj.get("date-parts")
                if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                    year = str(parts[0][0])
                    break

        authors: list[str] = []
        for a in item.get("author") or []:
            if isinstance(a, dict):
                given = str(a.get("given") or "").strip()
                family = str(a.get("family") or a.get("name") or "").strip()
                full = f"{given} {family}".strip()
                if full:
                    authors.append(full)

        containers = item.get("container-title") or []
        journal = _clean_jats(containers[0] if isinstance(containers, list) and containers else "")
        url = str(item.get("URL") or (f"https://doi.org/{doi}" if doi else ""))

        return {
            "source": "crossref",
            "doi": doi,
            "title": title,
            "summary": summary,
            "abstract": summary,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "journal": journal,
            "citation_count": int(item.get("is-referenced-by-count") or 0),
            "type": str(item.get("type") or ""),
            "updated_by": item.get("updated-by") or [],
            "url": url,
        }

    async def search_crossref(
        self,
        query: str,
        rows: int = 8,
        year_from: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "query": query,
            "rows": str(max(1, min(50, rows))),
        }
        email = _contact_email()
        if email:
            params["mailto"] = email
        if year_from:
            params["filter"] = f"from-pub-date:{int(year_from)}"

        try:
            async with self._client() as client:
                async with get_limiter("crossref", 0.05 if self.transport else 0.25):
                    resp = await client.get(CROSSREF_WORKS_URL, params=params)
            if resp.status_code != 200:
                logger.warning("Crossref returned HTTP %s", resp.status_code)
                return []
            payload = resp.json()
            items = ((payload.get("message") or {}).get("items")) if isinstance(payload, dict) else []
            return [r for item in (items or []) if (r := self._parse_crossref_item(item)) is not None]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref search failed: %s", exc)
            return []

    async def fetch_crossref_doi(self, doi: str) -> dict[str, Any] | None:
        clean = normalize_doi(doi)
        if not clean:
            return None
        params: dict[str, str] = {}
        email = _contact_email()
        if email:
            params["mailto"] = email
        url = f"{CROSSREF_WORKS_URL}/{quote(clean, safe='/')}"
        try:
            async with self._client() as client:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            msg = payload.get("message") if isinstance(payload, dict) else None
            return self._parse_crossref_item(msg) if isinstance(msg, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref DOI fetch failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 5. zbMATH Open
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_zbmath_item(item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        zbl_id = str(item.get("zbl_id") or item.get("identifier") or item.get("id") or "").strip()
        title_obj = item.get("title")
        if isinstance(title_obj, dict):
            title_raw = title_obj.get("title") or title_obj.get("formatted") or ""
        else:
            title_raw = str(title_obj or "")
        title = _clean_jats(title_raw)
        if not title and not zbl_id:
            return None

        year = str(item.get("year") or "").strip()
        authors: list[str] = []
        for a in item.get("authors") or []:
            if isinstance(a, dict) and a.get("name"):
                authors.append(str(a["name"]).strip())
            elif isinstance(a, str) and a.strip():
                authors.append(a.strip())

        msc: list[str] = []
        for m in item.get("msc") or []:
            if isinstance(m, dict) and m.get("code"):
                msc.append(str(m["code"]).strip())
            elif isinstance(m, str) and m.strip():
                msc.append(m.strip())

        doi: str | None = None
        arxiv_id: str | None = None
        for link in item.get("links") or []:
            if isinstance(link, dict):
                ltype = str(link.get("type") or "").lower()
                ident = str(link.get("identifier") or link.get("url") or "").strip()
                if ltype == "doi" and ident:
                    doi = normalize_doi(ident) or doi
                elif ltype == "arxiv" and ident:
                    arxiv_id = split_arxiv_version(ident)[0]

        reviews: list[str] = []
        for ed in item.get("editorial_contributions") or []:
            if isinstance(ed, dict) and ed.get("text"):
                reviews.append(_clean_jats(ed["text"]))
        summary = " ".join(reviews).strip() or _clean_jats(item.get("abstract") or "")

        source_info = item.get("source")
        if isinstance(source_info, dict):
            series = source_info.get("series") or []
            journal = _clean_jats(
                (series[0].get("short_title") or series[0].get("title"))
                if isinstance(series, list) and series and isinstance(series[0], dict)
                else (source_info.get("source") or "zbMATH")
            )
        else:
            journal = _clean_jats(source_info or "zbMATH")

        url = str(item.get("zbmath_url") or (f"https://zbmath.org/?q=an:{zbl_id}" if zbl_id else ""))

        return {
            "source": "zbmath",
            "zbl_id": zbl_id or None,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "abstract": summary,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "journal": journal,
            "msc": msc,
            "citation_count": 0,
            "url": url,
        }

    async def search_zbmath(self, query: str, results_per_page: int = 8) -> list[dict[str, Any]]:
        params = {
            "search_string": query,
            "results_per_page": str(max(1, min(50, results_per_page))),
        }
        try:
            async with self._client() as client:
                async with get_limiter("zbmath", 0.05 if self.transport else 0.5):
                    resp = await client.get(ZBMATH_SEARCH_URL, params=params)
            if resp.status_code != 200:
                logger.warning("zbMATH returned HTTP %s", resp.status_code)
                return []
            payload = resp.json()
            items = payload.get("result") if isinstance(payload, dict) else []
            return [r for item in (items or []) if (r := self._parse_zbmath_item(item)) is not None]
        except Exception as exc:  # noqa: BLE001
            logger.warning("zbMATH search failed: %s", exc)
            return []

    async def fetch_zbmath_document(self, zbl_id: str) -> dict[str, Any] | None:
        clean = re.sub(r"^(?:zbl\.?|zbmath)\s*[:=#]?\s*", "", (zbl_id or "").strip(), flags=re.I)
        if not clean:
            return None
        try:
            async with self._client() as client:
                resp = await client.get(f"{ZBMATH_DOC_URL}/{quote(clean)}")
            if resp.status_code != 200:
                return None
            payload = resp.json()
            item = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else payload
            return self._parse_zbmath_item(item) if isinstance(item, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("zbMATH document lookup failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 6. NASA ADS
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_ads_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(doc, dict):
            return None
        bibcode = str(doc.get("bibcode") or "").strip()
        titles = doc.get("title") or []
        title_raw = titles[0] if isinstance(titles, list) and titles else (titles if isinstance(titles, str) else "")
        title = _clean_jats(title_raw)
        if not title and not bibcode:
            return None

        dois = doc.get("doi") or []
        doi_raw = dois[0] if isinstance(dois, list) and dois else (dois if isinstance(dois, str) else "")
        doi = normalize_doi(doi_raw) or None

        arxiv_id: str | None = None
        for ident in doc.get("identifier") or []:
            ident_str = str(ident)
            if ident_str.lower().startswith("arxiv:"):
                arxiv_id = split_arxiv_version(ident_str)[0]
                break

        authors = [str(a).strip() for a in (doc.get("author") or []) if str(a).strip()]
        summary = _clean_jats(doc.get("abstract") or "")
        year = str(doc.get("year") or "").strip()
        journal = _clean_jats(doc.get("pub") or "NASA ADS")
        url = f"https://ui.adsabs.harvard.edu/abs/{quote(bibcode)}/abstract" if bibcode else ""

        return {
            "source": "ads",
            "ads_bibcode": bibcode or None,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "abstract": summary,
            "year": year,
            "authors": authors,
            "author_string": ", ".join(authors),
            "journal": journal,
            "citation_count": int(doc.get("citation_count") or 0),
            "url": url,
        }

    async def search_ads(
        self,
        query: str,
        rows: int = 8,
    ) -> tuple[list[dict[str, Any]], str | None]:
        token = (self.ads_api_token or os.getenv("TRIBOS_ADS_API_TOKEN", "")).strip()
        if not token:
            return [], ADS_SKIPPED_NOTE
        params = {
            "q": query,
            "fl": "bibcode,title,author,year,pub,abstract,doi,identifier,citation_count",
            "rows": str(max(1, min(50, rows))),
        }
        try:
            async with self._client({"Authorization": f"Bearer {token}"}) as client:
                async with get_limiter("nasa_ads", 0.05 if self.transport else 0.2):
                    resp = await client.get(ADS_SEARCH_URL, params=params)
            if resp.status_code != 200:
                return [], f"NASA ADS HTTP {resp.status_code}"
            payload = resp.json()
            docs = ((payload.get("response") or {}).get("docs")) if isinstance(payload, dict) else []
            out = [r for d in (docs or []) if (r := self._parse_ads_doc(d)) is not None]
            return out, None
        except Exception as exc:  # noqa: BLE001
            logger.warning("NASA ADS search failed: %s", exc)
            return [], f"NASA ADS error: {type(exc).__name__}"


__all__ = [
    "ADS_SEARCH_URL",
    "ADS_SKIPPED_NOTE",
    "ARXIV_API_URL",
    "ArchivonClients",
    "CROSSREF_WORKS_URL",
    "OPENALEX_WORKS_URL",
    "S2_PAPER_URL",
    "S2_RECOMMEND_URL",
    "S2_SEARCH_URL",
    "ZBMATH_DOC_URL",
    "ZBMATH_SEARCH_URL",
    "build_arxiv_search_query",
    "parse_arxiv_atom",
    "reconstruct_openalex_abstract",
]
