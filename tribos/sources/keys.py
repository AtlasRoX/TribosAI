"""One evidence-key format for every module that names a source document.

Citations, the NLI audit, the verifier, the debate critique and the confidence model all compare keys such as
``ARXIV:2312.04511`` or ``DOI:10.1103/physrev.47.777``. They must agree on spelling, so every key is built and
normalised here: the prefix is upper-case, a DOI is lower-case, an arXiv id loses its ``arxiv.org/abs/`` URL
form and its version suffix, and whitespace or surrounding brackets are dropped.
"""

from __future__ import annotations

import re
from typing import Any

# Prefixes for scholarly identifiers, in the order a passage's own key is chosen (most specific first).
SCHOLARLY_PREFIXES = ("ARXIV", "DOI", "ZBL", "MR", "ADS", "OPENALEX", "PMID")
# Prefixes for non-scholarly evidence: a passage without an identifier, a tool result, a web page.
LOCAL_PREFIXES = ("PASSAGE", "TOOL", "URL")

_PREFIX_ALIASES = {
    "ARXIV": "ARXIV",
    "ARX": "ARXIV",
    "DOI": "DOI",
    "ZBL": "ZBL",
    "ZBMATH": "ZBL",
    "MR": "MR",
    "ADS": "ADS",
    "BIBCODE": "ADS",
    "OPENALEX": "OPENALEX",
    "PMID": "PMID",
    "PASSAGE": "PASSAGE",
    "TOOL": "TOOL",
    "URL": "URL",
}
_KEY_RE = re.compile(r"^([A-Za-z]+)\s*:\s*(.+)$", re.DOTALL)
_ARXIV_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
# New-style (2312.04511, optional version) and old-style (math.AG/0601001, hep-th/9901001) arXiv identifiers.
_ARXIV_ID_RE = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$", re.IGNORECASE)
_DOI_URL_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
# Prefixes whose value keeps its case: a tool name, a passage id, a URL path.
_CASE_KEPT = {"TOOL", "PASSAGE", "URL"}
# Local prefixes are written in lower case by the verifier ("passage:<id>", "tool:<name>").
_LOWER_PREFIX = {"PASSAGE": "passage", "TOOL": "tool", "URL": "URL"}


def _clean_value(prefix: str, value: str) -> str:
    v = value.strip().strip("[]()").strip()
    if prefix == "ARXIV":
        v = re.sub(r"(?i)^arxiv:\s*", "", _ARXIV_URL_RE.sub("", v))
        return _ARXIV_VERSION_RE.sub("", v.removesuffix(".pdf"))  # case kept: old-style ids are math.AG/0601001
    if prefix == "DOI":
        return _DOI_URL_RE.sub("", v).lower()
    if prefix == "MR":
        return re.sub(r"(?i)^mr\s*", "", re.sub(r"\s+", "", v))  # "MR1234567" and "1234567" are the same review
    if prefix == "ZBL":
        return re.sub(r"(?i)^zbl\s*:?", "", re.sub(r"\s+", "", v))  # "Zbl 1234.56789" is ZBL:1234.56789
    if prefix in _CASE_KEPT:
        return v
    # OpenAlex ids are case-insensitive (W2741809807); an ADS bibcode keeps its case, which its URL needs.
    return re.sub(r"\s+", "", v).upper() if prefix == "OPENALEX" else re.sub(r"\s+", "", v)


def make_key(prefix: str, value: Any) -> str:
    """``PREFIX:value`` in the canonical spelling; an unknown prefix is upper-cased and kept."""
    canon = _PREFIX_ALIASES.get(prefix.strip().upper(), prefix.strip().upper())
    head = _LOWER_PREFIX.get(canon, canon)
    return f"{head}:{_clean_value(canon, str(value))}"


def normalize_evidence_key(key: str) -> str:
    """The canonical spelling of an evidence key, or the stripped input when it has no ``PREFIX:`` form.

    ``[arXiv:2312.04511v2]`` -> ``ARXIV:2312.04511``; ``doi: 10.1000/ABC`` -> ``DOI:10.1000/abc``;
    ``Zbl:1234.5678`` -> ``ZBL:1234.5678``; ``passage:p3`` stays ``passage:p3``."""
    k = (key or "").strip().strip("[]").strip()
    if not k:
        return ""
    if _ARXIV_URL_RE.match(k):
        return make_key("ARXIV", k)
    if _DOI_URL_RE.match(k):
        return make_key("DOI", k)
    m = _KEY_RE.match(k)
    if not m or m.group(1).upper() not in _PREFIX_ALIASES:
        return k
    return make_key(m.group(1), m.group(2))


def passage_keys(p: dict[str, Any]) -> list[str]:
    """Every canonical key a passage is known by (arXiv id, DOI, zbMATH, MR, ADS, OpenAlex, PMID), most specific
    first. Two passages are the same document when their key lists intersect."""
    keys: list[str] = []

    def add(prefix: str, value: Any) -> None:
        if value:
            key = make_key(prefix, value)
            if key not in keys:
                keys.append(key)

    add("ARXIV", p.get("arxiv_id") or p.get("arxiv"))
    add("DOI", p.get("doi"))
    add("ZBL", p.get("zbl") or p.get("zbl_id") or p.get("zbmath_id"))
    add("MR", p.get("mr") or p.get("mr_id"))
    add("ADS", p.get("ads") or p.get("bibcode") or p.get("ads_bibcode"))
    add("OPENALEX", p.get("openalex_id"))
    add("PMID", p.get("pmid"))
    pid = str(p.get("paper_id") or "").strip()
    if pid:
        # A bare paper_id is an arXiv id only when it looks like one; a Semantic Scholar hash is not a key.
        key = normalize_evidence_key(pid) if ":" in pid else make_key("ARXIV", pid) if _ARXIV_ID_RE.match(pid) else ""
        if key and key not in keys:
            keys.append(key)
    return keys


def passage_source_key(p: dict[str, Any], fallback: str = "") -> str:
    """The single key a passage is cited by: its most specific scholarly identifier, else ``fallback``."""
    keys = passage_keys(p)
    return keys[0] if keys else fallback


def same_document(a: str | dict[str, Any], b: str | dict[str, Any]) -> bool:
    """True when two keys (or passages) name the same document under any of their identifiers."""

    def as_set(x: str | dict[str, Any]) -> set[str]:
        return set(passage_keys(x)) if isinstance(x, dict) else {normalize_evidence_key(x)}

    sa, sb = as_set(a), as_set(b)
    return bool(sa and sb and sa & sb)


__all__ = [
    "LOCAL_PREFIXES",
    "SCHOLARLY_PREFIXES",
    "make_key",
    "normalize_evidence_key",
    "passage_keys",
    "passage_source_key",
    "same_document",
]
