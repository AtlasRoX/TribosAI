"""
Identifier families checked generically by the verifier and harvested into memory.

A family's ids are 'observed' when they appear in a successful tool output, a retrieved passage,
canonical_ids (canonical_keys), verified memory, the query context, or the user's own question.
Cited ids that were never observed are CRITICAL IDENTIFIER defects, hedged or not.
This module imports nothing from tribos.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IdentifierFamily:
    name: str
    pattern: re.Pattern
    normalize: Callable[[str], str]
    label: str
    canonical_keys: tuple[str, ...]
    correction: str
    severity: str = "CRITICAL"


def _identity(s: str) -> str:
    return s.strip()


def _upper(s: str) -> str:
    return s.strip().upper()


def _lower(s: str) -> str:
    return s.strip().lower()


def _norm_arxiv(s: str) -> str:
    cleaned = re.sub(r"^arxiv:\s*", "", s.strip(), flags=re.IGNORECASE)
    return f"arXiv:{cleaned}"


def _norm_zbl(s: str) -> str:
    cleaned = re.sub(r"^zbl\s*:?\s*", "", s.strip(), flags=re.IGNORECASE)
    return f"Zbl {cleaned}"


def _norm_mr(s: str) -> str:
    cleaned = re.sub(r"^mr\s*:?\s*", "", s.strip(), flags=re.IGNORECASE)
    return f"MR{cleaned}"


def _norm_isbn(s: str) -> str:
    cleaned = re.sub(r"^isbn(?:-1[03])?:?\s*", "", s.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s-]", "", cleaned).upper()
    return f"ISBN:{cleaned}"


def _norm_comp(s: str) -> str:
    cleaned = re.sub(r"^comp:\s*", "", s.strip(), flags=re.IGNORECASE)
    return f"comp:{cleaned}"


def _ontology(s: str) -> str:
    return s.replace(":", "_")


def _strip_version(s: str) -> str:
    return s.split(".", 1)[0].upper()


def _compact_upper(s: str) -> str:
    return re.sub(r"[\s-]", "", s).upper()


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RE = re.compile(_UUID, re.IGNORECASE)


def _uuid_only(s: str) -> str:
    m = _UUID_RE.search(s)
    return m.group(0).lower() if m else s.lower()


FAMILIES: tuple[IdentifierFamily, ...] = (
    # STEM identifier families
    IdentifierFamily(
        name="arxiv",
        pattern=re.compile(r"\barXiv:\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE),
        normalize=_norm_arxiv,
        label="ARXIV",
        canonical_keys=("arxiv_ids", "arxiv_id", "arxiv"),
        correction="Cite only arXiv identifiers (arXiv:YYMM.NNNNN) that appear in the retrieved literature or passages.",
    ),
    IdentifierFamily(
        name="zbl",
        pattern=re.compile(r"\bZbl\s*\d{4}\.\d{5}\b", re.IGNORECASE),
        normalize=_norm_zbl,
        label="ZBL",
        canonical_keys=("zbl_ids", "zbl_id", "zbl"),
        correction="Cite only zbMATH Open identifiers (Zbl NNNN.NNNNN) returned by an executed literature lookup.",
    ),
    IdentifierFamily(
        name="mr",
        pattern=re.compile(r"\bMR\d{6,8}\b", re.IGNORECASE),
        normalize=_norm_mr,
        label="MR",
        canonical_keys=("mr_ids", "mr_id", "mr"),
        correction="Cite only MathSciNet Mathematical Reviews identifiers (MR######) present in the retrieved evidence.",
    ),
    IdentifierFamily(
        name="oeis",
        pattern=re.compile(r"\bA\d{6}\b"),
        normalize=_upper,
        label="OEIS",
        canonical_keys=("oeis_ids", "oeis_id", "a_numbers", "a_number"),
        correction="Cite only OEIS sequence A-numbers (A######) returned by Physis or present in the user's question.",
    ),
    IdentifierFamily(
        name="ads",
        pattern=re.compile(r"\b\d{4}[A-Za-z&.\d]{14}[A-Z]\b"),
        normalize=_identity,
        label="ADS",
        canonical_keys=("ads_bibcodes", "bibcodes", "bibcode", "ads_id"),
        correction="Cite only NASA ADS 19-character bibcodes returned by an executed literature search.",
    ),
    IdentifierFamily(
        name="mp",
        pattern=re.compile(r"\bmp-\d{1,8}\b", re.IGNORECASE),
        normalize=_lower,
        label="MP",
        canonical_keys=("mp_ids", "mp_id", "material_ids", "material_id"),
        correction="Cite only Materials Project identifiers (mp-...) returned by Physis in this investigation.",
    ),
    IdentifierFamily(
        name="isbn",
        pattern=re.compile(r"\bISBN(?:-1[03])?:?\s*[0-9Xx-]{10,17}\b", re.IGNORECASE),
        normalize=_norm_isbn,
        label="ISBN",
        canonical_keys=("isbns", "isbn"),
        correction="Cite only ISBN book identifiers present in the retrieved bibliographic evidence.",
    ),
    IdentifierFamily(
        name="openalex",
        pattern=re.compile(r"\bW\d{7,12}\b"),
        normalize=_upper,
        label="OPENALEX",
        canonical_keys=("openalex_ids", "openalex_id"),
        correction="Cite only OpenAlex work identifiers (W...) returned by an executed literature search.",
    ),
    IdentifierFamily(
        name="computation",
        pattern=re.compile(r"\bcomp:[a-zA-Z0-9_:-]+\b", re.IGNORECASE),
        normalize=_norm_comp,
        label="COMP",
        canonical_keys=("computation_ids", "computation_id", "comp_ids"),
        correction="Cite only computation identifiers (comp:...) produced by Axiom, Dynamis, or Calcula in this run.",
    ),
    IdentifierFamily(
        name="dataset",
        pattern=re.compile(r"\bds_[0-9a-f]{12}\b", re.IGNORECASE),
        normalize=_lower,
        label="DATASET",
        canonical_keys=("dataset_ids", "dataset_id"),
        correction="Refer only to uploaded dataset ids that were attached to this question.",
    ),
    # Legacy biomedical identifier families retained for compatibility
    IdentifierFamily(
        name="nct",
        pattern=re.compile(r"\bNCT\d{8}\b", re.IGNORECASE),
        normalize=_upper,
        label="NCT",
        canonical_keys=("nct_ids",),
        correction="Cite only ClinicalTrials.gov NCT numbers that appear in the retrieved registry records or passages.",
    ),
    IdentifierFamily(
        name="chembl",
        pattern=re.compile(r"\bCHEMBL\d{1,9}\b", re.IGNORECASE),
        normalize=_upper,
        label="CHEMBL",
        canonical_keys=("chembl_ids", "chembl_id"),
        correction="Cite only ChEMBL identifiers returned by an executed tool in this investigation.",
    ),
    IdentifierFamily(
        name="hgnc",
        pattern=re.compile(r"\bHGNC:\d{1,6}\b"),
        normalize=_identity,
        label="HGNC",
        canonical_keys=("hgnc_ids", "hgnc_id"),
        correction="Cite only HGNC identifiers resolved by an executed tool in this investigation.",
    ),
    IdentifierFamily(
        name="ontology",
        pattern=re.compile(r"\b(?:EFO|MONDO|Orphanet|HP|DOID)[_:]\d{4,9}\b"),
        normalize=_ontology,
        label="ONTOLOGY",
        canonical_keys=("ontology_ids", "efo_id"),
        correction="Cite only disease ontology identifiers (MONDO/EFO/Orphanet/HP/DOID) present in the evidence.",
    ),
    IdentifierFamily(
        name="rsid",
        pattern=re.compile(r"\brs\d{3,12}\b"),
        normalize=_lower,
        label="RSID",
        canonical_keys=("rsids",),
        correction="Cite only dbSNP rsIDs present in the evidence or the researcher's question.",
    ),
    IdentifierFamily(
        name="clinvar",
        pattern=re.compile(r"\bVCV\d{9}(?:\.\d+)?\b"),
        normalize=_strip_version,
        label="CLINVAR",
        canonical_keys=("clinvar_vcv",),
        correction="Cite only ClinVar VCV accessions returned by the variant lookup.",
    ),
    IdentifierFamily(
        name="civic",
        pattern=re.compile(r"\b(?:EID|AID)\d{1,6}\b"),
        normalize=_identity,
        label="CIVIC",
        canonical_keys=("civic_ids",),
        correction="Cite only CIViC evidence (EID) or assertion (AID) identifiers returned by the variant lookup.",
    ),
    IdentifierFamily(
        name="geo",
        pattern=re.compile(r"\bGS[EM]\d{1,9}\b"),
        normalize=_identity,
        label="GEO",
        canonical_keys=("geo_accessions",),
        correction="Cite only GEO accessions present in the evidence or confirmed for an attached dataset.",
    ),
    IdentifierFamily(
        name="drugbank",
        pattern=re.compile(r"\bDB\d{5}\b"),
        normalize=_upper,
        label="DRUGBANK",
        canonical_keys=("drugbank_ids", "drugbank_id"),
        correction="Cite only DrugBank identifiers returned by an executed tool (PrimeKG) in this investigation.",
    ),
    IdentifierFamily(
        name="fda_application",
        pattern=re.compile(r"\b(?:NDA|ANDA|BLA)[\s-]?\d{6}\b"),
        normalize=_compact_upper,
        label="FDA_APPLICATION",
        canonical_keys=("application_numbers",),
        correction="Cite only FDA application numbers (NDA/ANDA/BLA) shown on the retrieved openFDA label.",
    ),
    IdentifierFamily(
        name="dailymed_setid",
        pattern=re.compile(
            r"(?:\bset[\s_-]?id\b[\"'`*\s:=(]{0,6}|\bsetid=|\bDailyMed\b[^\n.]{0,60}?)" + _UUID, re.IGNORECASE
        ),
        normalize=_uuid_only,
        label="DAILYMED_SETID",
        canonical_keys=("set_ids",),
        correction="Cite only DailyMed label set ids returned by the openFDA label lookup.",
    ),
)

_BY_NAME: dict[str, IdentifierFamily] = {f.name: f for f in FAMILIES}


def family_names() -> list[str]:
    return [f.name for f in FAMILIES]


def get_family(name: str) -> IdentifierFamily:
    return _BY_NAME[name]


def extract_family_ids(text: str) -> dict[str, set[str]]:
    """Normalized ids of every family found in text (every family key is present)."""
    out: dict[str, set[str]] = {f.name: set() for f in FAMILIES}
    if not text:
        return out
    for fam in FAMILIES:
        for m in fam.pattern.finditer(text):
            out[fam.name].add(fam.normalize(m.group(0)))
    return out


def normalize_ids(name: str, ids: Any) -> set[str]:
    """Normalize ids of one family, splitting comma-separated strings and dropping blanks."""
    fam = _BY_NAME.get(name)
    out: set[str] = set()
    if ids is None:
        return out
    items = [ids] if isinstance(ids, str) else list(ids)
    for item in items:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                out.add(fam.normalize(part) if fam else part)
    return out
