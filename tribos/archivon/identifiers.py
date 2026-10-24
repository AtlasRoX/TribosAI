"""Explicit literature identifiers (arXiv, DOI, zbMATH Zbl, MathSciNet MR, NASA ADS bibcode, OpenAlex, PMID, PMCID)
named in a question or text, normalized for exact lookup and citation grounding.
"""

from __future__ import annotations

import re

MAX_LITERATURE_IDS = 10

# arXiv: new-style YYMM.NNNN(N)(vN) or old-style archive/YYMMNNN(vN)
_ARXIV_PREFIX_RE = re.compile(
    r"(?:\barXiv\s*[:=]?\s*|https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/)"
    r"((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
    re.I,
)
_ARXIV_BARE_NEW_RE = re.compile(r"\b(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?)\b")
_ARXIV_BARE_OLD_RE = re.compile(
    r"\b((?:math|hep-th|hep-ph|hep-ex|hep-lat|astro-ph|cond-mat|gr-qc|quant-ph|nucl-th|nucl-ex|cs|physics|q-bio|q-fin|stat)/\d{7}(?:v\d+)?)\b",
    re.I,
)

# Crossref recommended DOI pattern
_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|(?:\bdoi\s*[:=]\s*))?(10\.\d{4,9}/[^\s\"'<>]+)",
    re.I,
)

# zbMATH: "Zbl 1456.11001", "Zbl 07543210", "zbMATH 1456.11001"
_ZBL_RE = re.compile(
    r"\b(?:Zbl\.?|zbMATH)\s*[:=#]?\s*(\d{4}\.\d{5}|\d{7,8})\b",
    re.I,
)

# MathSciNet: "MR1234567" or "MR 1234567"
_MR_RE = re.compile(r"\bMR\s*[:=#]?\s*(\d{6,8})\b", re.I)

# NASA ADS 19-character bibcode, e.g. "2016PhRvL.116f1102A" or "1998AJ....116.1009R"
_BIBCODE_RE = re.compile(
    r"\b((?:18|19|20)\d{2}[A-Za-z&\.]{5}[A-Za-z0-9\.]{9}[A-Z\.])\b"
)

# OpenAlex Work ID: "W2741809807" or "https://openalex.org/W2741809807"
_OPENALEX_RE = re.compile(
    r"(?:https?://openalex\.org/)?\b(W\d{7,12})\b"
)

# PubMed / PMC
_PMID_RE = re.compile(
    r"\b(?:PMID|PubMed\s*(?:ID|identifier)?)\s*[:#=]?\s*(\d{1,9})\b"
    r"|pubmed\.ncbi\.nlm\.nih\.gov/(\d{1,9})\b"
    r"|europepmc\.org/(?:abstract|article)/MED/(\d{1,9})\b",
    re.I,
)
_PMCID_RE = re.compile(r"\b(PMC\d{3,10})\b", re.I)


def split_arxiv_version(raw: str) -> tuple[str, str]:
    """Return (versionless_id, version_str) for an arXiv identifier."""
    cleaned = re.sub(
        r"^(?:arxiv\s*[:=]?\s*|https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/)",
        "",
        (raw or "").strip(),
        flags=re.I,
    )
    cleaned = re.sub(r"\.pdf$", "", cleaned, flags=re.I).strip()
    m = re.search(r"(v\d+)$", cleaned, re.I)
    version = m.group(1) if m else ""
    versionless = re.sub(r"v\d+$", "", cleaned, flags=re.I)
    return versionless, version


def normalize_doi(raw: str) -> str:
    """Normalize a DOI string by stripping URL/prefix and trailing punctuation, lowercased."""
    text = (raw or "").strip()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*[:=]?\s*)", "", text, flags=re.I).strip()
    text = text.rstrip(".,;:)]}>\"'")
    return text.lower()


def normalize_literature_id(raw: str) -> tuple[str, str | None]:
    """Return (kind, normalized_id) where kind is arxiv | doi | zbl | mr | bibcode | openalex | pmid | pmcid | invalid."""
    text = (raw or "").strip()
    if not text:
        return "invalid", None

    # DOI check first (before arXiv, though 10.48550/arXiv... is a DOI)
    doi_cand = normalize_doi(text)
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi_cand):
        return "doi", doi_cand

    # arXiv check
    arxiv_cand = re.sub(
        r"^(?:arxiv\s*[:=]?\s*|https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/)",
        "",
        text,
        flags=re.I,
    ).strip()
    arxiv_cand = re.sub(r"\.pdf$", "", arxiv_cand, flags=re.I)
    if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", arxiv_cand, re.I):
        versionless, _ = split_arxiv_version(arxiv_cand)
        return "arxiv", versionless

    # zbMATH check
    m = re.fullmatch(r"(?:(?:zbl\.?|zbmath)\s*[:=#]?\s*)?(\d{4}\.\d{5}|\d{7,8})", text, re.I)
    if m and (text.lower().startswith(("zbl", "zbmath")) or "." in m.group(1)):
        return "zbl", m.group(1)

    # MathSciNet MR check
    m = re.fullmatch(r"mr\s*[:=#]?\s*(\d{6,8})", text, re.I)
    if m:
        return "mr", f"MR{m.group(1)}"

    # OpenAlex check
    m = re.fullmatch(r"(?:https?://openalex\.org/)?(W\d{7,12})", text, re.I)
    if m:
        return "openalex", m.group(1).upper()

    # NASA ADS bibcode check (19 chars)
    if len(text) == 19 and _BIBCODE_RE.fullmatch(text):
        return "bibcode", text
    m = re.fullmatch(r"(?:bibcode\s*[:=]?\s*)((?:18|19|20)\d{2}[A-Za-z&\.]{5}[A-Za-z0-9\.]{9}[A-Z\.])", text, re.I)
    if m:
        return "bibcode", m.group(1)

    # PMID check
    m = re.fullmatch(r"(?:pmid\s*[:#=]?\s*)?(\d{1,9})", text, re.I)
    if m:
        return "pmid", m.group(1)

    # PMCID check
    m = re.fullmatch(r"(?:pmcid\s*[:#=]?\s*)?(PMC\d{3,10})", text, re.I)
    if m:
        return "pmcid", m.group(1).upper()

    return "invalid", None


def extract_typed_literature_ids(text: str) -> dict[str, list[str]]:
    """Extract all recognized scholarly identifiers from text, grouped by canonical type."""
    arxiv_list: list[str] = []
    doi_list: list[str] = []
    zbl_list: list[str] = []
    mr_list: list[str] = []
    ads_list: list[str] = []
    openalex_list: list[str] = []
    pmid_list: list[str] = []
    pmcid_list: list[str] = []

    result: dict[str, list[str]] = {
        "arxiv": arxiv_list,
        "arxiv_ids": arxiv_list,
        "doi": doi_list,
        "dois": doi_list,
        "zbl": zbl_list,
        "zbl_ids": zbl_list,
        "mr": mr_list,
        "mr_ids": mr_list,
        "ads": ads_list,
        "ads_bibcodes": ads_list,
        "openalex": openalex_list,
        "openalex_ids": openalex_list,
        "pmid": pmid_list,
        "pmids": pmid_list,
        "pmcid": pmcid_list,
        "pmcids": pmcid_list,
    }
    if not text:
        return result

    def _add(bucket: str, val: str) -> None:
        if val and val not in result[bucket]:
            result[bucket].append(val)

    for m in _ARXIV_PREFIX_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        _add("arxiv_ids", vless)
    for m in _ARXIV_BARE_NEW_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        _add("arxiv_ids", vless)
    for m in _ARXIV_BARE_OLD_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        _add("arxiv_ids", vless.lower())

    for m in _DOI_RE.finditer(text):
        doi = normalize_doi(m.group(1))
        if doi:
            _add("dois", doi)

    for m in _ZBL_RE.finditer(text):
        _add("zbl_ids", m.group(1))

    for m in _MR_RE.finditer(text):
        _add("mr_ids", f"MR{m.group(1)}")

    for m in _BIBCODE_RE.finditer(text):
        _add("ads_bibcodes", m.group(1))

    for m in _OPENALEX_RE.finditer(text):
        _add("openalex_ids", m.group(1).upper())

    for m in _PMID_RE.finditer(text):
        pmid = next((g for g in m.groups() if g), "")
        if pmid:
            _add("pmids", pmid)

    for m in _PMCID_RE.finditer(text):
        _add("pmcids", m.group(1).upper())

    return result


def extract_literature_ids(text: str, limit: int = MAX_LITERATURE_IDS) -> list[str]:
    """Identifiers the text names explicitly, normalized, in order of appearance:
    arXiv IDs, DOIs, Zbl IDs, MR IDs, ADS bibcodes, OpenAlex IDs, PMIDs, and PMCIDs.
    """
    if not text:
        return []
    found: list[tuple[int, str]] = []

    for m in _ARXIV_PREFIX_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        found.append((m.start(), f"arXiv:{vless}"))
    for m in _ARXIV_BARE_NEW_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        found.append((m.start(), f"arXiv:{vless}"))
    for m in _ARXIV_BARE_OLD_RE.finditer(text):
        vless, _ = split_arxiv_version(m.group(1))
        found.append((m.start(), f"arXiv:{vless.lower()}"))
    for m in _DOI_RE.finditer(text):
        doi = normalize_doi(m.group(1))
        if doi:
            found.append((m.start(), doi))
    for m in _ZBL_RE.finditer(text):
        found.append((m.start(), f"Zbl {m.group(1)}"))
    for m in _MR_RE.finditer(text):
        found.append((m.start(), f"MR{m.group(1)}"))
    for m in _BIBCODE_RE.finditer(text):
        found.append((m.start(), m.group(1)))
    for m in _OPENALEX_RE.finditer(text):
        found.append((m.start(), m.group(1).upper()))
    for m in _PMID_RE.finditer(text):
        pmid = next((g for g in m.groups() if g), "")
        if pmid:
            found.append((m.start(), pmid))
    for m in _PMCID_RE.finditer(text):
        found.append((m.start(), m.group(1).upper()))

    out: list[str] = []
    for _pos, ident in sorted(found, key=lambda x: x[0]):
        # Avoid adding bare new-style arXiv ID if already captured with prefix or inside a 10.48550/arXiv DOI
        if ident not in out:
            out.append(ident)
    return out[:limit]


def strip_literature_ids(text: str) -> str:
    """Return text with explicit scholarly identifiers removed for topical search."""
    if not text:
        return ""
    cleaned = _ARXIV_PREFIX_RE.sub(" ", text)
    cleaned = _ARXIV_BARE_NEW_RE.sub(" ", cleaned)
    cleaned = _ARXIV_BARE_OLD_RE.sub(" ", cleaned)
    cleaned = _DOI_RE.sub(" ", cleaned)
    cleaned = _ZBL_RE.sub(" ", cleaned)
    cleaned = _MR_RE.sub(" ", cleaned)
    cleaned = _BIBCODE_RE.sub(" ", cleaned)
    cleaned = _OPENALEX_RE.sub(" ", cleaned)
    cleaned = _PMID_RE.sub(" ", cleaned)
    cleaned = _PMCID_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def europepmc_exact_query(normalized: str, kind: str) -> str | None:
    """Legacy helper for exact query construction."""
    if kind == "pmid":
        return f"EXT_ID:{normalized} AND SRC:MED"
    if kind == "pmcid":
        return f"PMCID:{normalized}"
    if kind == "doi":
        return f'DOI:"{normalized}"'
    return None


__all__ = [
    "MAX_LITERATURE_IDS",
    "europepmc_exact_query",
    "extract_literature_ids",
    "extract_typed_literature_ids",
    "normalize_doi",
    "normalize_literature_id",
    "split_arxiv_version",
    "strip_literature_ids",
]
