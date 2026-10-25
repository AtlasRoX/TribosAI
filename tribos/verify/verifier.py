"""
STEM answer verifier and Reflexion self-correction support.

Checks an answer against what this run actually observed (Reflexion, Shinn et al., 2023), deterministically first:
- Identifiers: cited arXiv, DOI, zbMATH, MR, ADS, OpenAlex and PMID keys, and every registered identifier family,
  must appear in a tool output, a retrieved passage, verified memory of earlier turns or the question. Keys are
  compared in the tribos.sources.keys spelling, so "arXiv:2312.04511v2" grounds in a passage with arxiv_id 2312.04511.
- Literature claims: a sentence that cites a source, or reports a measured figure, is grounded in one retrieved
  passage or tool record: its figures with the same unit, its key terms, and no statement of the opposite.
- Mathematics: the answer's equations, derivation steps and result tables are re-evaluated (tribos.verify.math_claims).
- Simulations: a value given for a simulated state variable must lie on the computed trajectory (or match its final,
  initial or extreme value when the answer says which), and a time-course result is never called an equilibrium
  unless the fixed point was computed.
- Registered feature checks (tribos.extensions) add their own defects. Every defect lowers the score, and the
  structured report drives one bounded correction pass.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections.abc import Callable, Iterable
from enum import Enum
from typing import Any, NamedTuple

from pydantic import BaseModel, Field

from ..extensions.hooks import (
    VerificationContext,
    apply_serialization_filters,
    get_evidence_doc_providers,
    get_identifier_vetoes,
    get_verification_checks,
)
from ..extensions.id_families import FAMILIES, extract_family_ids, normalize_ids
from ..sources.keys import SCHOLARLY_PREFIXES, make_key, passage_keys, passage_source_key
from ..tools.registry import ToolResult
from ..utils.source_authority import URL_FIELDS, record_url

# sentence_spans lives in utils.text and is re-exported here (citations, the orchestrator and tests import it).
from ..utils.text import (  # noqa: F401
    _TABLE_LINE_RE,
    TYPOGRAPHY_FOLD,
    find_folded,
    fold_typography,
    sentence_spans,
)

logger = logging.getLogger(__name__)


def _pmid_in_passage(pmid: str, passage: str) -> bool:
    """A PMID named as such in passage text ('PMID: 123', 'pubmed/123'); a bare number such as a year is not one."""
    return bool(re.search(rf"(?:pmid|pubmed(?:\.ncbi\.nlm\.nih\.gov)?)\W{{0,4}}{re.escape(pmid)}(?!\d)", passage))


def _doi_in_passage(doi: str, passage: str) -> bool:
    """The whole DOI in passage text, not only the start of a longer DOI."""
    return bool(re.search(rf"(?<![\w./]){re.escape(doi.lower())}(?![\w/]|\.\w)", passage))


class DefectSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Contradiction, unobserved citation, cited figure missing from its source, wrong computed value
    MAJOR = "MAJOR"        # Modelling distinction violation (time course vs equilibrium), figure bound to the wrong case
    MINOR = "MINOR"        # Vague phrasing, ungrounded minor detail, uncited measurement not found in the evidence


class DefectItem(BaseModel):
    # IDENTIFIER | CITATION | NUMERICAL | UNSUPPORTED_CLAIM | CLAIM_CONTRADICTED | MATH_CONSISTENCY |
    # COMPLETION | INTEGRITY | MODELING_DISTINCTION | ... (see DEFECT_LABELS)
    category: str
    severity: DefectSeverity
    description: str
    suggested_correction: str
    claim: str | None = None
    # The answer sentence (or table row) exactly as written, for claim-audit defects; lets a caller remove it.
    sentence: str | None = None


class ClaimEvidence(BaseModel):
    source_key: str
    passage: str = ""  # excerpt the judgment rests on, for reviewers
    passage_id: str | None = None


class ClaimRecord(BaseModel):
    """One audited answer claim. status: supported | contradicted | unsupported | not_checked | inconclusive
    (inconclusive: a mathematical statement the deterministic checks could not decide)."""

    claim_id: str
    # empirical (a figure from a source or a measurement) | cited (a statement attributed to a cited source) |
    # computational | absence | operational (a tool or lookup outcome) | mathematical
    claim_type: str
    claim_text: str
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    status: str
    reason: str = ""
    # For a claim that cites a source whose retrieved text was checked: False when the support comes from a different
    # document than the one cited (the cited source did not back it). None when nothing was cited or the cited text
    # was not retrieved.
    cited_source_supported: bool | None = None


class VerificationReport(BaseModel):
    passed: bool
    verification_score: float  # 0.0 to 1.0; not a probability of correctness
    defects: list[DefectItem] = Field(default_factory=list)
    verified_identifiers: list[str] = Field(default_factory=list)
    numerical_checks_passed: int = 0
    numerical_checks_failed: int = 0
    failure_lesson: str | None = None
    # Sentences the claim audit grounded in a source: {"sentence", "evidence_key", "passage_id"}
    claim_support: list[dict[str, Any]] = Field(default_factory=list)
    # Identifiers excluded by registered vetoes (e.g. retracted articles), as "PMID:<id>", "DOI:<doi>", "<LABEL>:<id>"
    vetoed_identifiers: list[str] = Field(default_factory=list)
    # Claim-level audit: every material claim with its evidence and status
    claims: list[ClaimRecord] = Field(default_factory=list)
    contradicted_claims: int = 0
    unsupported_claims: int = 0
    unchecked_claims: int = 0
    inconclusive_claims: int = 0
    # passed, and every material claim was checked and supported; only then may an answer be labeled verified
    fully_verified: bool = False
    # How much of the answer was checked, kept apart from how well it scored: extracted, evaluated (decided either
    # way), passed, failed, unsupported, inconclusive. Zero evaluated claims is "not evaluated", never a pass.
    coverage: dict[str, int] = Field(default_factory=dict)
    # verified (every claim checked and supported) | checked (evaluated claims hold, some not checkable) |
    # failed | not_evaluated (nothing in the answer could be checked)
    status: str = "not_evaluated"
    # The deterministic audit of the answer's mathematical statements (tribos.verify.math_claims)
    math_audit: dict[str, Any] | None = None
    units: dict[str, Any] = Field(default_factory=dict)
    # The answer text this report describes (sha256 prefix) and the result record revision it was checked against
    answer_hash: str = ""
    record_revision: str = ""

    def to_feedback_prompt(self) -> str:
        """Generate structured Reflexion feedback prompt to guide bounded LLM correction."""
        lines = [
            "REFLEXION VERIFICATION AUDIT FAILED:",
            f"Overall Score: {self.verification_score:.2f} / 1.00 (Status: UNVERIFIED - DEFECTS PRESENT)",
            "Identified Specific Defects to Fix:",
        ]
        for idx, d in enumerate(self.defects, 1):
            lines.append(f"{idx}. [{d.severity.value}] {d.category}: {d.description}")
            lines.append(f"   Required Fix: {d.suggested_correction}")
        if self.failure_lesson:
            lines.append(f"Historical Failure Lesson: {self.failure_lesson}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evidence keys
# ---------------------------------------------------------------------------
# A literature passage's own key is its most specific scholarly identifier (tribos.sources.keys.passage_source_key, so
# the NLI audit and the verifier key passages identically); its other identifiers are kept as aliases.
# Identifier families that name a scholarly document, with their evidence-key prefix.
_FAMILY_PREFIX = {"arxiv": "ARXIV", "zbl": "ZBL", "mr": "MR", "ads": "ADS", "openalex": "OPENALEX"}
# The scheme name some sources keep in the value ("Zbl 1234.56789", "MR1234567", "arXiv:2312.04511").
_SCHEME_IN_VALUE = {
    "ARXIV": re.compile(r"^arxiv\s*:\s*", re.IGNORECASE),
    "ZBL": re.compile(r"^(?:zbl|zbmath)\.?\s*:?\s*", re.IGNORECASE),
    "MR": re.compile(r"^mr\s*:?\s*", re.IGNORECASE),
}


def scholarly_key(prefix: str, value: Any) -> str:
    """The canonical evidence key of a scholarly identifier, with a scheme name inside the value removed:
    ("MR", "MR1234567") -> "MR:1234567", ("ZBL", "Zbl 1234.56789") -> "ZBL:1234.56789"."""
    canon = make_key(prefix, "x").split(":", 1)[0]
    v = str(value or "").strip()
    pat = _SCHEME_IN_VALUE.get(canon)
    return make_key(canon, pat.sub("", v) if pat else v)


def literature_keys(p: dict[str, Any]) -> list[str]:
    """Every canonical key of a literature record, its passage_source_key first."""
    keys: list[str] = []
    first = passage_source_key(p)
    for raw in ([first] if first else []) + passage_keys(p):
        prefix, _, value = raw.partition(":")
        key = scholarly_key(prefix, value)
        if key not in keys:
            keys.append(key)
    return keys


def _is_literature_key(key: str) -> bool:
    return key.split(":", 1)[0] in SCHOLARLY_PREFIXES or key.startswith("passage:")


def _key_display(key: str) -> str:
    """How an answer writes a key: "PMID: 123", "arXiv:2312.04511", "DOI: 10.1103/x", "Zbl 1234.56789"."""
    prefix, _, value = key.partition(":")
    return {"PMID": f"PMID: {value}", "ARXIV": f"arXiv:{value}", "DOI": f"DOI: {value}", "ZBL": f"Zbl {value}",
            "MR": f"MR{value}"}.get(prefix, key)


# Source keys in answer text: PMID, arXiv (new and old style), DOI, zbMATH and MathSciNet numbers.
_CITED_KEY_RE = re.compile(
    r"\bPMID:?\s*(?P<pmid>\d{1,9})\b"
    r"|\barXiv:\s*(?P<arxiv>\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)"
    r"|(?P<doi>\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)"
    r"|\bZbl\.?\s*(?P<zbl>\d{4}\.\d{5})\b"
    r"|\bMR\s?(?P<mr>\d{6,8})\b",
    re.IGNORECASE,
)


def cited_keys(text: str) -> set[str]:
    """Canonical keys of the sources a text cites ("ARXIV:2312.04511", "DOI:10.1103/x", "PMID:123")."""
    keys: set[str] = set()
    for m in _CITED_KEY_RE.finditer(text or ""):
        if m.group("pmid"):
            keys.add(make_key("PMID", m.group("pmid")))
        elif m.group("arxiv"):
            keys.add(make_key("ARXIV", m.group("arxiv")))
        elif m.group("doi"):
            keys.add(make_key("DOI", m.group("doi").rstrip(".,;)")))
        elif m.group("zbl"):
            keys.add(make_key("ZBL", m.group("zbl")))
        elif m.group("mr"):
            keys.add(make_key("MR", m.group("mr")))
    return keys


# ---------------------------------------------------------------------------
# Sentence classes
# ---------------------------------------------------------------------------
# Negation and limitation markers. Registered feature checks receive this as VerificationContext.hedge_pattern
# and the equilibrium-wording check uses it; the built-in claim audit does NOT skip sentences that merely
# contain a negation (see _UNCERTAINTY_PATTERN).
_HEDGE_PATTERN = re.compile(
    r"\b(?:no|not|none|never|without|lack(?:s|ing)?|absent|absence|unavailable|insufficient|unverified|"
    r"unobserved|unknown|cannot|could\s+not|did\s+not|were\s+not|was\s+not|is\s+not|are\s+not|"
    r"hypothetical|fabricat\w*|unsupported)\b|n't\b",
    re.IGNORECASE,
)
# A proposed experiment ("Run a parameter sweep and record the equilibrium ...") is not a claim about results.
_SUGGESTION_PATTERN = re.compile(
    r"^[\s\-*•\d.)]*(?:(?:for (?:each|every)|then|next|first|finally|subsequently)\b[^.]{0,80}?\b)?"
    r"(?:run|perform|compute|record|measure|simulate|consider|test|validate|assess|repeat|extend|"
    r"compare|quantify|use|apply)\b|\b(?:would|could|should|suggest\w*|recommend\w*|next experiments?|in future)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "were", "was", "from", "have", "has", "had", "been", "into",
    "their", "which", "these", "those", "than", "then", "also", "such", "among", "between", "after", "before",
    "during", "within", "across", "over", "under", "about", "when", "where", "while", "both", "more", "most",
    "study", "studies", "paper", "papers", "work", "article", "authors", "result", "results", "data", "evidence",
    "value", "values", "shown", "showed", "shows", "show", "reported", "reports", "found", "obtained", "using",
    "used", "given", "approximately", "measured", "observed", "demonstrated", "significant", "statistically",
    "experiment", "experiments", "experimental", "experimentally", "approach", "method", "methods", "analysis",
}

# A sentence that reports a measurement or an observation rather than a derivation.
_EMPIRICAL_CUE_RE = re.compile(
    r"\b(?:measur(?:ed|es|ing|ements?)|experiment(?:s|al|ally)?|observ(?:ed|ations?|ational)|empirical(?:ly)?|"
    r"laboratory|reported\s+(?:a|an|the|values?|that)|data\s+(?:show|shows|indicate|indicates|give|gives)|"
    r"statistically\s+significant|benchmark(?:s|ed)?)\b",
    re.IGNORECASE,
)
# A claim that a value was measured cannot rest on a simulation or a symbolic computation: those are predictions.
_EXPERIMENTAL_CLAIM_RE = re.compile(
    r"\b(?:measur(?:ed|ements?)|experimental(?:ly)?|empirically|laboratory|experiments?\s+(?:show|showed|found|find|"
    r"report|reported|measured|gave|give|yield|yielded|confirm\w*))\b",
    re.IGNORECASE,
)
_COMPUTED_WORDING_RE = re.compile(
    r"\b(?:simulat\w*|comput\w*|numerical(?:ly)?|predict\w*|calculat\w*|model(?:s|led|ed|ling|ing)?)\b", re.IGNORECASE
)
# Tool sources that compute rather than observe (matched against "tool:<name>" evidence keys).
_COMPUTATIONAL_SOURCE_KEYS = ("dynamis", "vivarix", "simulat", "axiom", "calcula", "sandbox", "solver",
                              "ode_verification", "math_agent")


def is_experimental_claim(text: str) -> bool:
    """The sentence says a value was measured and does not say it was computed."""
    return bool(_EXPERIMENTAL_CLAIM_RE.search(text or "") and not _COMPUTED_WORDING_RE.search(text or ""))


def _key_has(key: str, names: tuple[str, ...]) -> bool:
    k = (key or "").lower()
    return k.startswith("tool:") and any(n in k for n in names)


def is_computational_doc(doc: _Doc) -> bool:
    return _key_has(doc.key, _COMPUTATIONAL_SOURCE_KEYS)


# A judge reason that names a concrete scope error (which case, condition, regime, parameter or unit a figure belongs
# to), as opposed to an inconclusive "the excerpt does not clearly say".
_RELATION_SCOPE_RE = re.compile(
    r"\b(?:denominators?|sub-?sets?|samples?|cases?|conditions?|regimes?|parameters?|configurations?|"
    r"boundary\s+conditions?|units?|quantit(?:y|ies)|variables?|time\s*points?|temperatures?|pressures?|"
    r"energ(?:y|ies)|frequenc(?:y|ies)|materials?|systems?|phases?|modes?|orders?)\b",
    re.IGNORECASE,
)
_RELATION_ERROR_RE = re.compile(
    r"\b(?:mismatch\w*|wrong|incorrect\w*|instead|rather\s+than|refers?\s+to|belongs?\s+to|actually|swapp?\w*|"
    r"mislabel\w*|misattribut\w*|whole|entire|parent|not\s+the)\b", re.IGNORECASE)


def judge_relation_error(verdict: dict[str, Any]) -> str | None:
    """The judge's concrete scope error (wrong case, condition, regime, parameter or unit), or None for an
    inconclusive verdict. A structured ``relation_error`` field is taken as is."""
    explicit = verdict.get("relation_error") or verdict.get("error_type")
    reason = str(verdict.get("reason") or "")
    if explicit:
        return f"{explicit}: {reason}" if reason else str(explicit)
    if _RELATION_SCOPE_RE.search(reason) and _RELATION_ERROR_RE.search(reason):
        return reason
    return None


# A sentence reporting what a tool or lookup did in this run ("the search for arXiv:X failed", "the correction text was
# not retrieved"): a fact about the run, grounded in its tool outcomes, never in a scientific citation.
_OPERATIONAL_RE = re.compile(
    r"\b(?:search(?:es)?|look[\s\-]?ups?|retrieval|quer(?:y|ies)|fetch(?:es)?|requests?|downloads?|tool\s+calls?|api\s+calls?|"
    r"database\s+calls?)\b[^.;]{0,90}?\b(?:fail(?:ed|s|ure)?|timed?\s*out|errored|returned\s+(?:no|nothing|zero|an?\s+error)|"
    r"did\s+not\s+return|found\s+no(?:thing)?|was\s+unsuccessful|were\s+unsuccessful|w(?:as|ere)\s+(?:not\s+)?skipped)\b|"
    r"\b(?:could|can)\s*not\s+be\s+(?:retrieved|fetched|downloaded|accessed|looked\s+up)\b|"
    r"\b(?:was|were|is|are)\s+not\s+(?:retrieved|fetched|downloaded|accessible)\b|"
    # Correction handling is a run outcome too: "the notice was retrieved ... so corrected content was not applied".
    r"\bcorrect(?:ed|ion)\s+(?:content|text|values?|results?)\s+(?:was|were|is|are)\s+(?:not\s+)?applied\b|"
    r"\bno\s+corrected\s+(?:content|text|values?|results?)\s+(?:was|were)\s+applied\b|"
    # Record linkage the exact lookup reports: "a correction (erratum) exists for X (linked erratum Y)".
    r"\b(?:corrections?|errat(?:um|a)|corrigend(?:um|a))\b[^.;]{0,60}?\b(?:exists?|is\s+linked|was\s+linked|linked)\b",
    re.IGNORECASE,
)


# A line that only locates evidence: "Source: abstract of arXiv:2312.04511; URL: ...", "*Sources:* ...".
_SOURCE_LOCATION_RE = re.compile(
    r"^\s*[*_]{0,2}(?:sources?|supporting\s+source(?:\s+location)?s?|source\s+location|references?|authoritative\s+references?|context|literature\s+context)[*_]{0,2}\s*:"
    # "*All figures are taken verbatim from the abstract of arXiv:X.*": where the numbers come from, no new fact.
    r"|^\s*[*_]{0,2}(?:all\s+)?(?:figures|values|numbers|results|data)\s+(?:are|were)\s+(?:taken|extracted|quoted|"
    r"transcribed)\s+(?:verbatim\s+|directly\s+)?from\b"
    # "Context (nonlinear/extensions, less directly applicable): ...": reference applicability note, not a testable fact
    r"|^\s*[*_]{0,2}(?:context|note|applicability|comparison)\s*\([^)]*\)\s*:"
    # "**Article:** https://arxiv.org/abs/2312.04511 ...", "Erratum notice: DOI 10.x (...)": a label pointing at a record.
    r"|^\s*[*_]{0,2}[A-Za-z][\w /\-]{0,30}[*_]{0,2}\s*:[*_]{0,2}\s*"
    r"(?:<?https?://|PMID:?\s*\d|DOI:?\s*10\.|arXiv:\s*\d|Zbl\.?\s*\d|MR\s?\d{6})",
    re.IGNORECASE,
)


def is_operational_claim(text: str) -> bool:
    return bool(_OPERATIONAL_RE.search(text or ""))


# Header words of a simulation output table ("| Variable | Initial | Final |"). A table without them (a discovery
# table "| Material | Year |") holds no state values, so its bare numbers are not simulation claims.
_SIM_TABLE_HEADER_RE = re.compile(
    r"state|variable|initial|final|steady|equilibri|value|simulat|time|\bt\b|model|trajector|solution|numeric|"
    r"computed|amplitude|position|velocity|displacement|angle|population",
    re.IGNORECASE,
)


def in_non_simulation_table(text: str, pos: int, names: Iterable[str] = ()) -> bool:
    """The position sits in a markdown table row whose header names no simulation quantity (nor any of `names`)."""
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    line = text[ls: le if le >= 0 else len(text)]
    if not line.lstrip().startswith("|"):
        return False
    header, start = line, ls
    while start > 0:
        prev_start = text.rfind("\n", 0, start - 1) + 1
        prev = text[prev_start: start - 1]
        if not prev.lstrip().startswith("|"):
            break
        header, start = prev, prev_start
    if _SIM_TABLE_HEADER_RE.search(header):
        return False
    return not any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", header) for n in names if n)


def article_unions(docs: list[_Doc]) -> list[_Doc]:
    """One extra document per article (scholarly key) with several retrieved passages: their joined text. A paper's
    figures are often spread over its abstract and a results chunk; each passage alone lacks some of them."""
    by_key: dict[str, list[_Doc]] = {}
    for d in docs:
        if d.key.split(":", 1)[0] in SCHOLARLY_PREFIXES:
            by_key.setdefault(d.key, []).append(d)
    out: list[_Doc] = []
    for key, parts in by_key.items():
        texts = list(dict.fromkeys(p.text for p in parts))
        if len(texts) > 1:
            out.append(_Doc(key, "\n".join(texts), None, "article", None, parts[0].aliases))
    return out


# Explicit uncertainty statements report a limit of this run; they are not checked as findings. A sentence that
# merely contains "no"/"not" ("a gap of 1.1 eV with no defect states") is still a factual claim.
_UNCERTAINTY_PATTERN = re.compile(
    r"\b(?:unverified|uncertain|unclear|hypothetical|speculative|remains?\s+unknown|is\s+unknown|"
    r"(?:could|can)\s*not\s+(?:be\s+)?(?:verif|confirm|determin|establish|retriev|find|locat|identif|assess)\w*|"
    r"unable\s+to\s+(?:verif|confirm|determin|establish|retriev|find|locat|identif|assess)\w*|"
    r"insufficient\s+(?:evidence|data)|"
    r"evidence\s+(?:is|was|remains)\s+(?:unavailable|insufficient|limited|lacking)|"
    r"(?:not|never)\s+(?:been\s+)?(?:retrieved|returned|located)\b|"
    r"(?:was|were|is|are|been)\s+(?:not\s+)?(?:found|identified)\s+in\s+(?:this|the\s+current|the\s+present)\s+(?:run|search|investigation|evidence)|"
    r"no\s+(?:matching|supporting|relevant|retrieved|posted)\s+(?:records?|sources?|passages?|evidence|data|publications?|papers?|results?)|"
    r"no\b[^.;]{0,80}?\b(?:was|were|is|are|could\s+be)\s+(?:retrieved|returned|located|available|found|identified)\b|"
    r"not\s+(?:been\s+)?found\b(?!\s+to\b)|"
    r"premise\s+(?:is|remains)\s+(?:unverified|unsupported)|"
    r"(?:do|did|will)\s+not\s+(?:invent|fabricate|speculate)|"
    r"not\s+(?:run|performed|executed|computed|simulated)\b|was\s+not\s+(?:run|performed|executed))",
    re.IGNORECASE,
)

# Statements that a source, or the literature, lacks something ("the cited paper does not derive the bound").
_ABSENCE_PATTERN = re.compile(
    r"\b(?:does|do|did)\s+not\s+(?P<v1>mention|discuss|describe|report|address|identify|explain|investigate|examine|"
    r"characteri[sz]e|provide|include|reference|name|elucidate|propose|show)\b|"
    r"\b(?:doesn't|don't|didn't)\s+(?P<v2>mention|discuss|describe|report|address|identify|explain|investigate|examine|"
    r"provide|include|reference|name|elucidate|propose|show)\b|"
    r"\b(?:is|are|was|were)\s+(?:not|never)\s+(?P<v3>mentioned|discussed|described|reported|addressed|identified|"
    r"explained|investigated|examined|characteri[sz]ed|referenced|named|elucidated)\b|"
    r"\bwithout\s+(?P<v4>explaining|describing|identifying|reporting|mentioning|addressing|elucidating|investigating|"
    r"proposing|characteri[sz]ing)\b|"
    r"\b(?:makes?|made)\s+no\s+(?P<v5>mention)\b|\bno\s+(?P<v6>mention)\s+(?:of|is\s+made\s+of)\b|"
    r"\b(?:there\s+(?:is|are)\s+no|no\s+(?:published\s+)?(?:studies|reports?|literature|publications?|data)\s+"
    r"(?:have|has|exist|exists|report|reports|describe|describes|show|shows))(?P<v7>)",
    re.IGNORECASE,
)
_MENTION_VERBS = re.compile(r"^(?:mention\w*|discuss\w*|referenc\w*|nam\w*|includ\w*)$", re.IGNORECASE)
_MECHANISM_OBJECT = re.compile(r"\b(?:mechanis\w*|how|why|drivers?|basis|explanation|causes?|origins?)\b", re.IGNORECASE)
_MECHANISM_CUES = re.compile(
    r"\b(?:mechanis\w*|mediat\w*|interact\w*|coupl(?:ed|ing|es)|driv(?:e|es|en|ing)|leads?\s+to|results?\s+in|"
    r"arises?\s+from|due\s+to|caused\s+by|governed\s+by|explained\s+by|through\s+(?:the\s+)?\w+|via|"
    r"increased\s+(?:\w+\s+){0,2}(?:rate|density|pressure|temperature|energy|field)|"
    r"decreased\s+(?:\w+\s+){0,2}(?:rate|density|pressure|temperature|energy|field))\b",
    re.IGNORECASE,
)
# An absence statement scoped to what this run retrieved ("not mentioned in the retrieved abstract") is checkable.
_SCOPED_ABSENCE = re.compile(
    r"\b(?:in|from|within)\s+(?:the|this|these|its)\s+(?:retrieved|available|returned)\b|"
    r"\bin\s+(?:the|its|this)\s+(?:abstract|excerpt|passage)s?\b|\bin\s+this\s+(?:run|search)\b|"
    r"\bretrieved\s+(?:text|passages?|excerpts?|abstracts?)\b",
    re.IGNORECASE,
)
_LITERATURE_REFERENT = re.compile(
    r"\b(?:cited|retrieved|returned)\s+(?:records?|papers?|articles?|passages?|sources?|literature|studies|publications?|reviews?|preprints?)\b",
    re.IGNORECASE,
)
_FUNCTION_WORDS = {
    "the", "a", "an", "any", "its", "their", "this", "that", "these", "those", "of", "in", "on", "for", "to", "with",
    "and", "or", "by", "at", "from", "as", "is", "are", "was", "were", "be", "been", "it", "they", "specific",
    "explicit", "clear", "clearly", "detailed", "direct", "directly", "further", "additional", "underlying",
    "about", "regarding", "whether", "which", "what", "whatsoever", "evidence", "data",
}

# ---------------------------------------------------------------------------
# Figures: numbers with physical units, intervals, p-values
# ---------------------------------------------------------------------------
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
# A number: sign, digits, decimals, a concise uncertainty "(15)", and a power of ten ("× 10^-11", "×10⁻¹¹", "e-11").
_NUM = (
    r"[+−\-]?\d+(?:\.\d+)?(?:\(\d{1,3}\))?"
    r"(?:\s*(?:[x×]|\\times)\s*10\s*(?:\^\s*\{?\s*[-−+]?\d+\s*\}?|[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)|[eE][-+−]?\d+)?"
)
_UNIT_SYM = (
    r"(?:da|[kMGTPpnµμucm])?(?:eV|Hz|Pa|Wb|Bq|Gy|Sv|mol|cd|lm|lx|bar|atm|rad|sr|Da|Wh|cal|Å|Ω|ohm|pc|ly|AU|au|"
    r"g|m|s|A|K|N|J|W|C|V|F|T|H|S|L)"
)
_UNIT_EXP = r"(?:\^\s*\{?\s*[-−]?\d\s*\}?|⁻?[¹²³])?"
_UNIT_SPACED_EXP = r"(?:\^\s*\{?\s*[-−]?\d\s*\}?|⁻[¹²³])"
_UNIT_WORD = (
    r"(?i:percent|per\s+cent|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|yrs?|kelvin|"
    r"degrees?\s+(?:celsius|fahrenheit)|degrees?)"
)
_UNIT = (
    "(?:" + _UNIT_WORD + r"|%|°[CF]?|dB|rpm|ppm|ppb|" + _UNIT_SYM + _UNIT_EXP
    + r"(?:\s*[/·⋅*]\s*\(?" + _UNIT_SYM + _UNIT_EXP + r"\)?|\s+" + _UNIT_SYM + _UNIT_SPACED_EXP + ")*)"
)
_UNIT_END = r"(?![A-Za-z0-9µμΩ])"
_QTY_PATTERN = r"(?<![\w.^/])(" + _NUM + r")\s*(" + _UNIT + ")" + _UNIT_END
_QTY_RE = re.compile(_QTY_PATTERN)  # answer text keeps its case: "mK" and "MK" differ
_QTY_RE_CI = re.compile(_QTY_PATTERN, re.IGNORECASE)  # evidence text is lower-cased
_NUM_PARTS_RE = re.compile(
    r"([+\-]?)(\d+)(?:\.(\d+))?(?:\(\d{1,3}\))?"
    r"(?:\s*(?:[x×]|\\times)\s*10\s*\^?\s*\{?\s*([+\-]?\d+)\s*\}?|[eE]([+\-]?\d+))?"
)
# A label before a number ("Fig. 2 C", "Table 3 S", "case 2 A") names a panel, not a quantity.
_LABEL_BEFORE_RE = re.compile(
    r"\b(?:fig(?:ure)?s?|panels?|tables?|eqs?|equations?|sections?|chapters?|steps?|cases?|parts?|types?|classes?|"
    r"groups?|rows?|columns?|items?|no|ref)\.?\s*$",
    re.IGNORECASE,
)

_UNIT_WORD_KEYS: dict[str, tuple[str, float]] = {
    "percent": ("%", 1.0), "per cent": ("%", 1.0),
    "second": ("s", 1.0), "seconds": ("s", 1.0), "sec": ("s", 1.0), "secs": ("s", 1.0),
    "minute": ("s", 60.0), "minutes": ("s", 60.0), "min": ("s", 60.0), "mins": ("s", 60.0),
    "hour": ("s", 3600.0), "hours": ("s", 3600.0), "hr": ("s", 3600.0), "hrs": ("s", 3600.0), "h": ("s", 3600.0),
    "day": ("s", 86400.0), "days": ("s", 86400.0), "week": ("s", 604800.0), "weeks": ("s", 604800.0),
    "month": ("month", 1.0), "months": ("month", 1.0),
    "year": ("year", 1.0), "years": ("year", 1.0), "yr": ("year", 1.0), "yrs": ("year", 1.0),
    "kelvin": ("k", 1.0), "degree": ("°", 1.0), "degrees": ("°", 1.0),
    "degree celsius": ("°c", 1.0), "degrees celsius": ("°c", 1.0),
    "degree fahrenheit": ("°f", 1.0), "degrees fahrenheit": ("°f", 1.0),
}
_PLAIN_UNITS = frozenset({
    "ev", "hz", "pa", "wb", "bq", "gy", "sv", "mol", "cd", "lm", "lx", "bar", "atm", "rad", "sr", "da", "wh", "cal",
    "å", "ω", "ohm", "pc", "ly", "au", "g", "m", "s", "a", "k", "n", "j", "w", "c", "v", "f", "t", "l",
})
_OTHER_UNITS = frozenset({"%", "°", "°c", "°f", "db", "rpm", "ppm", "ppb"})
# SI prefixes that stay unambiguous once text is lower-cased ("m" may be milli or mega, so "mev" is compared as is).
_PREFIX_SCALE = {"k": 1e3, "g": 1e9, "t": 1e12, "p": 1e-12, "n": 1e-9, "µ": 1e-6, "μ": 1e-6, "u": 1e-6, "c": 1e-2}
# Case-sensitive SI prefixes for answer text, where the case is known.
_CASED_PREFIX_SCALE = {**{k: v for k, v in _PREFIX_SCALE.items() if k not in ("g", "t")},
                       "G": 1e9, "T": 1e12, "M": 1e6, "m": 1e-3, "P": 1e15}


def _compound_unit_key(u: str) -> str:
    """'m/s', 'm s^-1' and 'm·s⁻¹' -> 'm·s^-1' (prefixed tokens are kept as written)."""
    u = u.replace("⋅", "·").replace("*", "·")
    powers: dict[str, int] = {}
    for slash, token, exp in re.findall(r"(/)?\s*\(?\s*([a-zµμåω°%]+)\s*\^?\s*\{?\s*(-?\d)?\s*\}?\s*\)?", u):
        e = int(exp) if exp else 1
        powers[token] = powers.get(token, 0) + (-e if slash else e)
    return "·".join(t if e == 1 else f"{t}^{e}" for t, e in powers.items() if e)


def unit_key(raw: str) -> tuple[str, float]:
    """(comparable unit, scale to it) for a unit as written: 'keV' -> ('ev', 1e3), 'minutes' -> ('s', 60),
    'mm' -> ('mm', 1) (milli or mega cannot be told apart once lower-cased), 'm/s' -> ('m·s^-1', 1)."""
    u = re.sub(r"\s+", " ", str(raw or "").strip().lower().translate(_SUPERSCRIPT))
    if u in _UNIT_WORD_KEYS:
        return _UNIT_WORD_KEYS[u]
    if u in _PLAIN_UNITS or u in _OTHER_UNITS:
        return u, 1.0
    if re.search(r"[/·⋅* ^]|\d", u):
        return _compound_unit_key(u), 1.0
    if u.startswith("da") and u[2:] in _PLAIN_UNITS:
        return u[2:], 10.0
    if u[:1] in _PREFIX_SCALE and u[1:] in _PLAIN_UNITS:
        return u[1:], _PREFIX_SCALE[u[:1]]
    return u, 1.0


def cased_unit_key(raw: str) -> tuple[str, float]:
    """unit_key for text whose case is known (the answer): 'mm' -> ('m', 1e-3), 'MW' -> ('w', 1e6)."""
    u = str(raw or "").strip()
    if u[:1] in _CASED_PREFIX_SCALE and u[1:].lower() in _PLAIN_UNITS and u.lower() not in _PLAIN_UNITS:
        return u[1:].lower(), _CASED_PREFIX_SCALE[u[:1]]
    return unit_key(u)


def number_parts(raw: str) -> tuple[float, float] | None:
    """(value, one unit in the last stated place) of a written number: '6.674 × 10^-11' -> (6.674e-11, 1e-14)."""
    s = str(raw or "").replace("−", "-").translate(_SUPERSCRIPT).strip()
    m = _NUM_PARTS_RE.match(s)
    if not m:
        return None
    sign, whole, frac, e1, e2 = m.groups()
    exp = int(e1 or e2 or 0)
    try:
        value = float(f"{sign}{whole}.{frac or '0'}") * (10.0 ** exp)
    except (OverflowError, ValueError):
        return None
    return value, 10.0 ** (exp - len(frac or ""))


def _values_match(a: float, a_ulp: float, b: float, b_ulp: float) -> bool:
    """Equal to the precision of the less precise of the two figures."""
    tol = 0.55 * max(a_ulp or 0.0, b_ulp or 0.0) + 1e-12 * max(abs(a), abs(b))
    return abs(a - b) <= tol


# "92 (95% CI 90-94) K" -> "92 K (95% CI 90-94)"; "10 vs 12 K" -> "10 K vs 12 K"; "92 ± 2 K" -> "92 K ± 2 K": the unit is
# written once for values that an interval, an uncertainty or a comparator separates from it.
_UNIT_AFTER_PAREN_RE = re.compile(
    r"(?<![\w.])(" + _NUM + r")(\s*\([^()]{1,60}\))\s*(" + _UNIT + ")" + _UNIT_END, re.IGNORECASE
)
_UNIT_AFTER_PAIR_RE = re.compile(
    r"(?<![\w.])(" + _NUM + r")(\s*(?:vs\.?|versus|and|or|to)\s*|\s*[–—]\s*|-)(" + _NUM + r")\s*(" + _UNIT + ")" + _UNIT_END,
    re.IGNORECASE,
)
_UNIT_AFTER_PM_RE = re.compile(
    r"(?<![\w.])(" + _NUM + r")(\s*(?:±|\+/-|\+-)\s*)(" + _NUM + r")\s*(" + _UNIT + ")" + _UNIT_END, re.IGNORECASE
)
# "10.2 (7.6-16.3) and 6.0 months (4.2-11.0)": after the second value got its unit, the first (separated from it by its
# own interval) gets the same one.
_UNIT_AFTER_PAREN_PAIR_RE = re.compile(
    r"(?<![\w.])(" + _NUM + r")(\s*\([^()]{1,60}\)\s*(?:,|vs\.?|versus|and|or)\s*" + _NUM + r"\s*(" + _UNIT + "))"
    + _UNIT_END,
    re.IGNORECASE,
)


def attach_units(text: str) -> str:
    """`text` with a unit repeated next to each value it belongs to (see the patterns above)."""
    text = _UNIT_AFTER_PAREN_RE.sub(lambda m: f"{m.group(1)} {m.group(3)}{m.group(2)}", text)
    text = _UNIT_AFTER_PAREN_PAIR_RE.sub(lambda m: f"{m.group(1)} {m.group(3)}{m.group(2)}", text)
    text = _UNIT_AFTER_PM_RE.sub(lambda m: f"{m.group(1)} {m.group(4)}{m.group(2)}{m.group(3)} {m.group(4)}", text)
    return _UNIT_AFTER_PAIR_RE.sub(lambda m: f"{m.group(1)} {m.group(4)}{m.group(2)}{m.group(3)} {m.group(4)}", text)


_CI_RE = re.compile(
    r"\b(?:\d{2}\s*%\s*)?(?:ci|confidence\s+intervals?)\s*(?:of|was|=|:|,)?\s*\[?\(?\s*(\d+(?:\.\d+)?)\s*(?:-|–|—|to|,)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_P_RE = re.compile(r"\bp\s*(?:-?\s*value)?\s*([<>=≤≥]|<=|>=)\s*(\d*\.?\d+(?:\s*[x×]\s*10\s*[-−]\s*\d+|e-?\d+)?)", re.IGNORECASE)

# Predicates whose polarity can be compared between a claim and a passage. Verb forms only, so nouns such as
# "the increase" are not read as statements.
_PREDICATE_GROUPS: tuple[tuple[str, re.Pattern], ...] = (
    ("improve", re.compile(r"\b(?:improv(?:e|es|ed|ing|ement|ements)|prolong(?:s|ed|ing)?|extend(?:s|ed|ing)?|"
                           r"superior|outperform(?:s|ed)?)\b", re.IGNORECASE)),
    ("increase", re.compile(r"\b(?:increas(?:e|es|ed|ing)|elevat(?:e|es|ed|ing)|enhanc(?:e|es|ed|ing)|amplif(?:y|ies|ied))\b",
                            re.IGNORECASE)),
    ("decrease", re.compile(r"\b(?:reduc(?:e|es|ed|ing|tion)|decreas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
                            r"suppress(?:es|ed|ing)?|damp(?:s|ed|ens|ened)?|attenuat(?:e|es|ed|ing))\b", re.IGNORECASE)),
    ("associate", re.compile(r"\b(?:associated|correlated|predicted|predicts|linked)\b", re.IGNORECASE)),
    ("achieve", re.compile(r"\b(?:met|meet|meets|achiev(?:e|es|ed|ing)|reach(?:es|ed)?)\b", re.IGNORECASE)),
    ("significant", re.compile(r"\bsignificant(?:ly)?\b", re.IGNORECASE)),
    ("converge", re.compile(r"\bconverg(?:e|es|ed|ing)\b", re.IGNORECASE)),
    ("conserve", re.compile(r"\bconserv(?:e|es|ed|ing)\b", re.IGNORECASE)),
    ("exceed", re.compile(r"\bexceed(?:s|ed|ing)?\b", re.IGNORECASE)),
)
_NEGATOR = re.compile(
    r"\b(?:not|no|never|neither|nor|without|fail(?:s|ed)?\s+to|unable\s+to|lack(?:s|ed)?\s+(?:of\s+)?|absence\s+of)\b|n't\b",
    re.IGNORECASE,
)

MAX_CLAIM_RECORDS = 160  # literature claims plus the answer's mathematical statements
MAX_JUDGE_CALLS = 12
# Reason prefix for a figure whose case, condition or regime the source assigns differently.
RELATION_MISMATCH_PREFIX = "numeric relation mismatch:"


class _Doc(NamedTuple):
    key: str  # 'ARXIV:<id>', 'DOI:<doi>', 'PMID:<id>', 'passage:<id>', 'tool:<name>'
    text: str  # lowercased
    passage_id: str | None
    section: str
    # The record's own address (final URL after redirects, else canonical/requested), never a link quoted in its text.
    url: str | None = None
    # The document's other keys (a passage with an arXiv id and a DOI is cited by either).
    aliases: tuple[str, ...] = ()


def _doc_keys(doc: _Doc) -> set[str]:
    return {doc.key, *doc.aliases}


def _cites(doc: _Doc, cited: set[str]) -> bool:
    return bool(cited) and bool(_doc_keys(doc) & cited)


def _cited_key_of(doc: _Doc, cited: set[str]) -> str:
    """The key the answer used for this document, else its own key."""
    return next((k for k in (doc.key, *doc.aliases) if k in cited), doc.key)


def _fold_thousands(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)


def _leaf_text(value: Any, depth: int = 0) -> str:
    if isinstance(value, dict):
        if depth > 3:
            return ""
        return "; ".join(
            f"{k}: {t}" for k, v in value.items() if k != "plot_base64_png" and (t := _leaf_text(v, depth + 1))
        )
    if isinstance(value, (list, tuple)):
        return "; ".join(t for v in list(value)[:50] if (t := _leaf_text(v, depth + 1)))
    if value is None:
        return ""
    return str(value)[:2000]


# Fields that name a tool record (a constant, a material, a sequence), for the focused documents of its sections.
_RECORD_NAME_FIELDS = ("name", "title", "symbol", "query_name", "formula", "id")


def _record_items(data: Any, max_records: int = 200) -> list[tuple[str, dict[str, Any] | None]]:
    """(lowercased document, the record it came from) per tool record (each item of a list of dicts), per nested
    section of a record, per nested page with its own URL (a web search's fetched top page), plus one for the scalar
    fields; a claim must be grounded in a single record rather than in terms scattered across a whole output."""
    if not isinstance(data, dict):
        text = _leaf_text(data)
        return [(text.lower(), None)] if text else []
    docs: list[tuple[str, dict[str, Any] | None]] = []
    header: dict[str, Any] = {}
    for k, v in data.items():
        if k == "plot_base64_png":
            continue
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v[:max_records]:
                text = _leaf_text(item)
                if text:
                    docs.append((f"{k}: {text}".lower(), item))
                # A nested section of a record (a material's "properties", a constant's "uncertainty") also gets its own
                # focused document: in the flattened record it sits behind other fields, past what a judge reads.
                name = next((str(item.get(f)) for f in _RECORD_NAME_FIELDS if isinstance(item.get(f), str) and item.get(f)), "")
                for sub_key, sub in item.items():
                    if isinstance(sub, dict) and sub:
                        sub_text = _leaf_text(sub)
                        if sub_text:
                            # The section keeps its parent's address.
                            inherited = {f: item[f] for f in (*URL_FIELDS, "redirects") if f in item}
                            docs.append((f"{k} {name} {sub_key}: {sub_text}".lower(), {**inherited, **sub}))
        elif isinstance(v, dict) and any(isinstance(x, list) for x in v.values()):
            docs.extend((f"{k}: {d}", rec) for d, rec in _record_items(v, max_records))
        elif isinstance(v, dict) and record_url(v) and not v.get("error"):
            # A page fetched in its own right (websurfer's top_page): its own document, judged by its own address.
            text = _leaf_text(v)
            if text:
                docs.append((f"{k}: {text}".lower(), v))
        else:
            header[k] = v
    text = _leaf_text(header)
    if text:
        docs.insert(0, (text.lower(), header))
    return docs


def _record_documents(data: Any, max_records: int = 200) -> list[str]:
    return [text for text, _rec in _record_items(data, max_records)]


def _walk_records(value: Any, depth: int = 0) -> Iterable[dict[str, Any]]:
    """Every dict in a tool output (bounded depth), for harvesting the scholarly ids its records carry."""
    if depth > 5:
        return
    if isinstance(value, dict):
        yield value
        for k, v in value.items():
            if k != "plot_base64_png":
                yield from _walk_records(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in list(value)[:300]:
            yield from _walk_records(v, depth + 1)


# A claim that names its source ("CODATA gives…", "the simulation shows…", "OEIS lists…") is checked against that
# source's output first; otherwise the first document sharing two terms is judged, and a true statement about
# another source is marked unsupported.
_SOURCE_NAME_KEYS: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = (
    (re.compile(r"\bcodata\b|\bnist\b|\bphysical\s+constants?\b", re.I), ("physis", "constant")),
    (re.compile(r"\boeis\b|\bA\d{6}\b", re.I), ("physis", "oeis")),
    (re.compile(r"\bmaterials\s+project\b|\bmp-\d+\b", re.I), ("physis", "material")),
    (re.compile(r"\b(?:simulation|simulated|ode\s+solver|integrat(?:ion|or)|runge|rk45|dynamis|trajector(?:y|ies))\b", re.I),
     ("dynamis", "simulat", "vivarix")),
    (re.compile(r"\b(?:symbolic(?:ally)?|sympy|axiom|computer\s+algebra|closed[\s\-]form)\b", re.I), ("axiom",)),
    (re.compile(r"\b(?:sandbox|calcula|code\s+analysis|attached\s+dataset|uploaded\s+data|dataset\s+analysis)\b", re.I),
     ("calcula", "sandbox", "analyst", "dataset")),
)


def names_a_source(text: str) -> bool:
    return any(pat.search(text or "") for pat, _keys in _SOURCE_NAME_KEYS)


# Record identifiers a claim can state and a tool record carries verbatim: ISO dates, Materials Project ids, OEIS
# A-numbers.
_ID_TOKEN_RE = re.compile(r"\b((?:19|20)\d{2}-\d{2}-\d{2})\b|\b(mp-\d{1,8})\b|\b(A\d{6})\b", re.I)


def claim_id_tokens(text: str) -> list[str]:
    """Record identifiers and ISO dates a claim states ("mp-149", "A000045", "2019-05-20"), as records spell them."""
    return list(dict.fromkeys(next(g for g in m.groups() if g).lower() for m in _ID_TOKEN_RE.finditer(text or "")))


def judge_window(doc_text: str, claim: str, size: int = 1500) -> str:
    """The part of a long record the semantic judge should read: around the claim's first figure or identifier found
    in it, else key salient terms, else the head."""
    if len(doc_text) <= size:
        return doc_text
    probes = claim_id_tokens(claim) + [m.group(0) for m in re.finditer(r"\d+\.\d+", claim or "")]
    for p in probes:
        i = doc_text.find(p)
        if i >= 0:
            start = max(0, i - size // 3)
            return doc_text[start:start + size]
    terms = [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{3,}", claim.lower()) if w not in _STOPWORDS]
    for t in sorted(terms, key=len, reverse=True):
        i = doc_text.find(t)
        if i >= 0:
            start = max(0, i - size // 3)
            return doc_text[start:start + size]
    return doc_text[:size]


_ID_GENERIC_TERMS = {"date", "first", "record", "entry", "identifier", "sequence", "material", "materials", "project",
                     "oeis", "lists", "listed", "database"}


def _tool_docs_naming(cited: set[str], docs: list[_Doc]) -> list[_Doc]:
    """Tool records that carry a cited identifier themselves (a record listing the paper it comes from): when the
    paper's text was not retrieved, the record that cites it is the evidence."""
    ids = [str(c).split(":", 1)[-1].strip().lower() for c in cited if str(c).split(":", 1)[-1].strip()]
    if not ids:
        return []
    return [d for d in docs if d.key.startswith("tool:") and any(re.search(rf"(?<![\d.]){re.escape(i)}(?!\d)", d.text) for i in ids)]


def prefer_named_sources(text: str, docs: list[_Doc]) -> list[_Doc]:
    """docs with those from the sources the claim names moved to the front (stable otherwise)."""
    wanted = [k for pat, keys in _SOURCE_NAME_KEYS if pat.search(text or "") for k in keys]
    if not wanted:
        return docs
    first = [d for d in docs if d.key.startswith("tool:") and any(k in d.key.lower() for k in wanted)]
    return first + [d for d in docs if d not in first] if first else docs


# ---------------------------------------------------------------------------
# Primary paper next to a review
# ---------------------------------------------------------------------------
_REVIEW_STUDY_TYPES = {"review", "systematic_review", "editorial"}
# Archivon grades (tribos.archivon.grading.StudyType) of papers that report their own result.
_PRIMARY_STUDY_TYPES = {"experimental_measurement", "numerical_simulation", "peer_reviewed", "theorem_proof",
                        "formal_proof", "conference", "preprint", "technical_report"}
# A named result in an answer sentence: an event or object designation, a collaboration or a named system
# ("GW150914", "LIGO", "SN 1987A" -> "SN", "YBCO", "Kepler-22b").
_NAMED_RESULT_RE = re.compile(r"(?<![\w-])([A-Z][A-Za-z]*\d+[A-Za-z0-9]*|[A-Z]{3,}[a-z]?|[A-Z][a-z]+-\d+[a-z]?)(?![\w-])")
_NOT_RESULT_NAMES = {"DOI", "PMID", "URL", "ISBN", "CODATA", "NIST", "SI", "RMS", "ODE", "PDE", "FFT", "CPU", "GPU"}


def _name_pattern(name: str) -> re.Pattern:
    """'GW150914' as a record may spell it: 'GW150914', 'GW 150914', 'gw-150914' (case-insensitive, whole token)."""
    m = re.match(r"^([A-Za-z]+)[\s\-]?(\d.*)$", name)
    body = rf"{re.escape(m.group(1))}[\s\-]?{re.escape(m.group(2))}" if m else re.escape(name)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


def _literature_records(tool_results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Citation key -> {"text" (title + every retrieved passage, lowercased), "study_type", "keys", "passage"} for the
    retrieved literature, in ranking order."""
    out: dict[str, dict[str, Any]] = {}
    for res in (tool_results or {}).values():
        data = getattr(res, "data", None) if getattr(res, "success", False) else None
        if not isinstance(data, dict) or not isinstance(data.get("ranked_passages"), list):
            continue
        for p in data["ranked_passages"]:
            keys = literature_keys(p) if isinstance(p, dict) else []
            if not keys:
                continue
            rec = out.setdefault(keys[0], {"parts": [], "study_type": "", "keys": set(keys), "passage": p})
            title = str(p.get("title") or "")
            if title and title not in rec["parts"]:
                rec["parts"].insert(0, title)
            rec["parts"].append(str(p.get("passage_text") or ""))
            grade = p.get("evidence_grade") if isinstance(p.get("evidence_grade"), dict) else {}
            rec["study_type"] = rec["study_type"] or str(grade.get("study_type") or "").lower()
    for rec in out.values():
        rec["text"] = _fold_thousands(fold_typography(" ".join(rec.pop("parts"))).lower())
    return out


def prefer_primary_reports(text: str, tool_results: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """The answer with a result's primary paper cited next to a review that is cited for the result's figures.

    A sentence qualifies when it cites a retrieved review (and not the primary paper) and states figures; the primary
    paper is a retrieved paper graded as reporting its own result (measurement, simulation, proof, journal article,
    preprint) that contains every figure of the sentence and either names the sentence's named result ("GW150914") or,
    without one, shares at least three key terms with it. Its key is inserted before the review's, which stays as the
    secondary source. Returns (text, [{"subject", "trial" (same value, for older callers), "primary", "review"}])."""
    if not text or not _CITED_KEY_RE.search(text):
        return text, []
    records = _literature_records(tool_results)
    if not records:
        return text, []
    by_alias = {k: key for key, rec in records.items() for k in rec["keys"]}
    edits: list[tuple[int, int, str]] = []
    changes: list[dict[str, str]] = []
    for s, e in sentence_spans(text):
        sentence = text[s:e]
        cited = [(m, k) for m in _CITED_KEY_RE.finditer(sentence) for k in cited_keys(m.group(0))]
        if not cited:
            continue
        cited_records = {by_alias[k] for _m, k in cited if k in by_alias}
        review = next(((m, by_alias[k]) for m, k in cited if k in by_alias
                       and records[by_alias[k]]["study_type"] in _REVIEW_STUDY_TYPES), None)
        if review is None:
            continue
        stripped = _CITED_KEY_RE.sub(" ", sentence)
        names = [n for n in dict.fromkeys(_NAMED_RESULT_RE.findall(stripped)) if n.upper() not in _NOT_RESULT_NAMES]
        figure_text = stripped
        for name in names:
            figure_text = figure_text.replace(name, " ")
        figures = bare_numbers(_fold_thousands(figure_text))
        if not figures:
            continue
        terms = TribosVerifier._salient_terms(figure_text)
        primary = None
        for key, rec in records.items():
            if key in cited_records or rec["study_type"] not in _PRIMARY_STUDY_TYPES:
                continue
            if names:
                if not any(_name_pattern(n).search(rec["text"]) for n in names):
                    continue
            elif len(terms & TribosVerifier._salient_terms(rec["text"])) < 3:
                continue
            doc_numbers = {float(dm.group(1)) for dm in _DOC_NUMBER_RE.finditer(rec["text"]) if not dm.group(2) and not dm.group(3)}
            if all(f in doc_numbers for f in figures):
                primary = (key, rec)
                break
        if primary is None:
            continue
        m, review_key = review
        level = ""
        after = sentence[m.end():]
        close = after.find(")")
        if close >= 0 and re.match(r"\s*;\s*[^;()]*\b(?:review|survey)\b", after[:close], re.IGNORECASE):
            try:
                from ..agents.prompts import evidence_level

                level = evidence_level(primary[1]["passage"])
            except Exception:  # noqa: BLE001
                level = ""
            level = "" if level in ("", "unclassified") else level
        insert = f"{_key_display(primary[0])}; {level + '; ' if level else ''}"
        edits.append((s + m.start(), s + m.start(), insert))
        subject = names[0] if names else "the result"
        changes.append({"subject": subject, "trial": subject, "primary": primary[0], "review": review_key})
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text, changes


# Older name, still called by the orchestrator's verify stage.
prefer_primary_trial_reports = prefer_primary_reports


def _fold(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def _tokens(text: str) -> set[str]:
    """Word tokens with a light plural fold, for word-boundary term matching."""
    return {_fold(w) for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text.lower())}


class _Metric(NamedTuple):
    kind: str  # qty (a value with a unit) | ci | p
    value: float
    unit: str  # comparable unit (see unit_key); the comparison operator for p
    label: str
    scale: float = 1.0  # value * scale is in `unit`
    ulp: float = 0.0  # one unit in the last stated place


_METRIC_KEYWORDS = {
    "ci": re.compile(r"\bci\b|confidence|\([^\)]*[-–—to][^\)]*\)|\[[^\]]*[-–—to][^\]]*\]", re.IGNORECASE),
    "p": re.compile(r"\bp\s*(?:-?\s*value)?\s*(?:=|<|>|≤|≥)", re.IGNORECASE),
}
_STRUCTURED_KEYWORDS = {
    "ci": re.compile(r"\bci\b|confidence|lower|upper|\([^\)]*[-–—to][^\)]*\)|\[[^\]]*[-–—to][^\]]*\]", re.IGNORECASE),
    "p": re.compile(r"\bp(?:[\s_\-]*value)?\b", re.IGNORECASE),
}
_DOC_NUMBER_RE = re.compile(r"(?<![\w.])(\d*\.?\d+)(?:\s*[x×]\s*10\s*[-−]\s*(\d+)|e-?(\d+))?(?![\d])", re.IGNORECASE)


def _p_value(raw: str) -> float:
    m = re.match(r"(\d*\.?\d+)(?:\s*[x×]\s*10\s*[-−]\s*(\d+)|e-?(\d+))?", raw.strip(), re.IGNORECASE)
    if not m:
        return float("nan")
    exp = m.group(2) or m.group(3)
    return float(m.group(1)) * (10 ** -int(exp) if exp else 1)


# ---------------------------------------------------------------------------
# Display text and markdown-aware sentence handling
# ---------------------------------------------------------------------------
def truncate_words(text: Any, limit: int = 240, ellipsis: str = "…") -> str:
    """`text` cut to at most `limit` characters on a word boundary, with an ellipsis when anything was cut.
    Display only: never use the result as a lookup key."""
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    room = max(1, limit - len(ellipsis))
    cut = s[:room]
    if s[room:room + 1] not in ("", " ") and " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:([{-–—") + ellipsis


_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,15});")


def unescape_entities(text: Any) -> str:
    """HTML entities decoded ("&lt;0.001" -> "<0.001", "&amp;" -> "&"), except a '<' or '>' that would then open
    or close a tag ("&lt;script" stays escaped), so decoding never turns text into markup."""
    s = str(text or "")
    if "&" not in s:
        return s

    def repl(m: re.Match[str]) -> str:
        decoded = html.unescape(m.group(0))
        nxt = s[m.end():m.end() + 1]
        if decoded == "<" and (nxt.isalpha() or nxt in "/!?"):
            return m.group(0)
        if decoded == ">" and s[max(0, m.start() - 1):m.start()].isalpha():
            return m.group(0)
        return decoded

    return _ENTITY_RE.sub(repl, s)


_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|\-]+\|?\s*$")
_HEADING_LINE_RE = re.compile(r"^\s*#{1,6}\s")
_RULE_LINE_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_BOLD_LABEL_LINE_RE = re.compile(r"^\s*(?:[-*+•]\s+)?(\*\*|__)[^*_\n]{1,160}\1\s*:?\s*$")
_LINE_MARKER_RE = re.compile(r"^\s*(?:>\s*)*(?:(?:[-*+•]|\d{1,3}[.)])\s+)?")
_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")
# Identifiers inside a table cell: literature keys, Materials Project ids, OEIS A-numbers.
_ROW_ID_RE = re.compile(
    r"\bPMID:?\s*\d{1,9}\b|\barXiv:\s*\S+|\b10\.\d{4,9}/\S+|\bZbl\.?\s*\d{4}\.\d{5}\b|\bMR\s?\d{6,8}\b|"
    r"\bmp-\d{1,8}\b|\bA\d{6}\b",
    re.IGNORECASE,
)
# Calendar dates ("19 Dec 2014", "March 27, 2017", "2014-12-19"): the day of month is not a figure.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_CALENDAR_DATE_RE = re.compile(
    rf"\b\d{{1,2}}\s+{_MONTH}\s+\d{{4}}\b|\b{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b",
    re.IGNORECASE,
)
_ROW_NUMBER_RE = re.compile(r"(?<![\w/])[<>≤≥=~]?\s*\d+(?:[.,]\d+)?(?![\w/])")
# A passage sentence that itself denies or hedges ("no data on the bound", "the origin remains unclear").
_PASSAGE_NEGATION_RE = re.compile(
    r"\b(?:no|not|none|neither|nor|without|lack(?:s|ed|ing)?|absence\s+of|unclear|uncertain|unknown|"
    r"remains?\s+(?:unknown|unclear|to\s+be)|insufficient|unexplored|undetermined)\b|n't\b",
    re.IGNORECASE,
)
_BARE_DECIMAL_RE = re.compile(r"(?<![\w.])(\d+\.\d+|\d{2,})(?![\w.]|\.\d)")


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_EMPHASIS_RE.sub("", c).strip() for c in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEPARATOR_RE.match(line)) and "-" in line and "|" in line


def _row_claim(cells: list[str], headers: list[str], first: str) -> str | None:
    """A claim sentence for a table data row with a figure: "<first cell> — <labels>: <header> <value>; ...",
    keeping identifiers from the row; None when the row has no number."""
    labels: list[str] = []
    figures: list[str] = []
    ids: list[str] = []
    for i, cell in enumerate(cells[1:], 1):
        if not cell or cell in ("-", "—", "–", "NA", "N/A", "n/a"):
            continue
        found_ids = [m.group(0).rstrip(".,;)") for m in _ROW_ID_RE.finditer(cell)]
        rest = re.sub(r"\(\s*\)|\[\s*\]", " ", _ROW_ID_RE.sub(" ", cell)).strip(" ;,")
        for fid in found_ids:
            if fid.lower() not in first.lower() and fid not in ids:
                ids.append(fid)
        if not rest:
            continue
        if _ROW_NUMBER_RE.search(rest):
            header = headers[i] if i < len(headers) else ""
            if header and header.lower() not in rest.lower():
                figures.append(f"{header} {rest}")
            else:
                figures.append(rest)
        else:
            labels.append(rest)
    if not figures:
        return None
    body = "; ".join(figures)
    if labels:
        body = f"{', '.join(labels)}: {body}"
    text = f"{first} — {body}" if first else body
    if ids:
        text += f" ({', '.join(ids)})"
    return text


def markdown_claim_units(text: str) -> list[tuple[str, str, bool]]:
    """(raw sentence, claim text, from_table) for the checkable sentences of a markdown answer. Headings, rules,
    bold label lines, code blocks, table header and separator rows, and table rows without a figure are skipped;
    list and blockquote markers are stripped; a table data row becomes one sentence that carries its row context
    (the last non-empty first-column value, e.g. the material, and the column headers). The raw sentence is the
    answer text exactly as sentence_spans cuts it, so claim_support lines up with the citation map."""
    units: list[tuple[str, str, bool]] = []
    lines = text.split("\n")
    headers: list[str] = []
    first_value = ""
    in_table = False
    in_code = False
    in_limitations = False
    offset = 0
    line_offsets: list[int] = []
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1
    spans = sentence_spans(text)
    span_idx = 0
    for li, line in enumerate(lines):
        lstart, lend = line_offsets[li], line_offsets[li] + len(line)
        line_spans: list[tuple[int, int]] = []
        while span_idx < len(spans) and spans[span_idx][0] < lend + 1:
            if spans[span_idx][0] >= lstart:
                line_spans.append(spans[span_idx])
            span_idx += 1
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            if not stripped:
                in_table = False
            continue
        if _TABLE_LINE_RE.match(line):
            if _is_table_separator(line):
                continue
            nxt = lines[li + 1] if li + 1 < len(lines) else ""
            if not in_table or _is_table_separator(nxt):
                in_table = True
                first_value = ""
                headers = _table_cells(line)
                if _is_table_separator(nxt):
                    continue  # header row
                headers = []
            cells = _table_cells(line)
            if cells and cells[0]:
                first_value = cells[0]
            claim = _row_claim(cells, headers, first_value)
            if claim:
                units.append((stripped, claim, True))
            continue
        in_table = False
        if _HEADING_LINE_RE.match(line) or _BOLD_LABEL_LINE_RE.match(line):
            # "Evidence limitations" states limits of the run (and quotes removed claims); "What would change this
            # conclusion" and "Suggested next experiments" are proposals and pending work. None of them are findings.
            in_limitations = bool(_LIMITATIONS_HEADING_RE.match(line) or _NON_FINDING_SECTION_RE.match(line))
            continue
        if in_limitations or _RULE_LINE_RE.match(line) or _CONFIDENCE_LINE_RE.search(line):
            continue
        for s, e in line_spans:
            raw = text[s:e].strip()
            claim = raw
            if s == lstart or not text[lstart:s].strip():
                claim = _LINE_MARKER_RE.sub("", claim, count=1)
            claim = _EMPHASIS_RE.sub("", claim).strip()
            if claim and re.search(r"[A-Za-z]", claim):
                units.append((raw, claim, False))
    return units


def bare_numbers(text: str) -> list[float]:
    """Decimal figures (and numbers of two or more digits) in a table-derived claim, minus identifiers and years."""
    cleaned = _CALENDAR_DATE_RE.sub(" ", _ROW_ID_RE.sub(" ", text))
    cleaned = re.sub(
        r"\b\d{2}\s*%\s*(?:ci|confidence\s+intervals?)\b|"
        r"\b(?:phase|grade|stage|cycle|arm|cohort|part|fig(?:ure)?|table|eq(?:uation)?|section|chapter|step|case|run|order)"
        r"\.?\s*[0-9IVX]+[ab]?(?:\s*/\s*[0-9IVX]+)?\b",
        " ", cleaned, flags=re.IGNORECASE,
    )
    out: list[float] = []
    for m in _BARE_DECIMAL_RE.finditer(cleaned):
        raw = m.group(1)
        if "." not in raw and 1900 <= int(raw) <= 2100:
            continue
        value = float(raw)
        if value not in out:
            out.append(value)
    return out


DEFECT_LABELS: dict[str, str] = {
    "MATH_CONSISTENCY": "Mathematical statement does not hold",
    "COMPUTATION": "Differs from the computed value",
    "CLAIM_CONTRADICTED": "Contradicted by a source",
    "UNSUPPORTED_CLAIM": "Not found in the evidence",
    "CLAIM_SUPPORT": "Not supported by the cited source",
    "CITATION_MISMATCH": "Supported by a different source than the one cited",
    "NUMERIC_RELATION_MISMATCH": "Figure belongs to a different parameter, regime or condition",
    "ABSENCE_OVERREACH": "Absence statement goes beyond the evidence",
    "CITATION": "Citation not found in the retrieved sources",
    "RETRACTED_CITATION": "Retracted source cited",
    "IDENTIFIER": "Identifier not returned by any tool",
    "NUMERICAL": "Number does not match the evidence",  # simulation and registered numeric checks use it
        "MODELING_DISTINCTION": "Time-course value described as an equilibrium",
    "COMPLETION": "Answer incomplete",
    "INTEGRITY": "Integrity issue",
}


def defect_label(category: str) -> str:
    """Human label for a defect category (the category itself stays in the structured data)."""
    return DEFECT_LABELS.get(str(category or ""), str(category or "Issue").replace("_", " ").capitalize())


def defect_display(defect: Any, limit: int = 160) -> str:
    """One user-facing line for a defect: "<label>: <claim>", cut on a word boundary."""
    category = str(getattr(defect, "category", "") or (defect.get("category") if isinstance(defect, dict) else "") or "")
    claim = getattr(defect, "claim", None) if not isinstance(defect, dict) else defect.get("claim")
    description = getattr(defect, "description", "") if not isinstance(defect, dict) else defect.get("description", "")
    body = unescape_entities(claim or description or "")
    body = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+", "", body)  # a bullet's list marker is not part of the claim
    return f"{defect_label(category)}: {truncate_words(body, limit)}"


def claim_tally(report: Any) -> str:
    """'N claims checked: S supported, C contradicted, U not checked' (plus unsupported when any)."""
    claims = list(getattr(report, "claims", None) or [])
    counts = {"supported": 0, "contradicted": 0, "unsupported": 0, "not_checked": 0, "inconclusive": 0}
    for c in claims:
        status = getattr(c, "status", None) or (c.get("status") if isinstance(c, dict) else None)
        if status in counts:
            counts[status] += 1
    parts = [f"{counts['supported']} supported", f"{counts['contradicted']} contradicted"]
    if counts["unsupported"]:
        parts.append(f"{counts['unsupported']} unsupported")
    parts.append(f"{counts['not_checked'] + counts['inconclusive']} not checked")
    n = len(claims)
    return f"{n} claim{'' if n == 1 else 's'} checked: " + ", ".join(parts)


REMOVABLE_DEFECTS = ("CLAIM_CONTRADICTED",)
# Proposals and method steps: "A pipeline would (1) define…", "this step would need to be performed", "Query arXiv
# for…", "we recommend…". Checked only when they also cite a source or report a figure.
_PROPOSAL_PATTERN = re.compile(
    r"\b(?:would|could|should)\s+(?:\(?\d+[.)]\s*)?(?:need\s+to\s+|have\s+to\s+|also\s+|then\s+|first\s+)?(?:be\s+)?[a-z]+"
    r"|^\s*(?:[-*]\s+|\d+[.)]\s+)?(?:optionally,?\s+|then,?\s+|next,?\s+|finally,?\s+)?(?:perform|query|run|use|screen|test|"
    r"validate|link|rank|prioriti[sz]e|filter|integrate|assess|evaluate|consider|identify|map|compile|cross-reference|"
    r"mine|search|retrieve|pull|extract|check|apply|combine|compute|select|exclude|include|confirm|obtain|collect)\b"
    r"|\b(?:we|i)\s+(?:propose|recommend|suggest)\b"
    # The pipeline or strategy the answer proposes ("A practical pipeline … begins with …").
    r"|^\s*(?:[-*]\s+|\d+[.)]\s+)?(?:a|the|this|our)\s+(?:practical\s+|proposed\s+|step-by-step\s+|suggested\s+)?"
    r"(?:screening\s+|validation\s+|simulation\s+|measurement\s+)?(?:pipeline|workflow|strategy|framework|approach)\b"
    # Hypotheses ("H1: the damping ratio will …"): predictions to be tested, not findings.
    r"|^\s*(?:[-*]\s+)?(?:\*\*)?H\d+(?:\*\*)?\s*[:.)]"
    r"|\bwill\s+(?:show|demonstrate|reduce|increase|decrease|improve|predict|associate|suppress|enhance|converge|exceed)\b",
    re.IGNORECASE,
)
_DISCLOSED_GAP_RE = re.compile(
    r"\bestablished\s+background\b"
    r"|\b(?:not|no(?:t)?\s+(?:been\s+)?|never)\s*(?:present|retrieved|found|available|reported|included|listed|captured)\s+"
    r"(?:in|by|from|within)\s+(?:the\s+)?(?:retrieved|available|current|returned)\s+(?:evidence|data|sources?|results?|records?)"
    r"|\bin\s+the\s+retrieved\s+(?:evidence|data|records?)\b.{0,40}$"
    r"|\b(?:were|was)\s+not\s+retrieved\b",
    re.IGNORECASE,
)
_NON_FINDING_SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*)\s*(?:what\s+(?:\w+\s+){0,3}(?:would|could|might)\s+change|suggested\s+next\s+(?:experiments?|steps)|"
    r"next\s+(?:experiments?|steps)|future\s+(?:directions|work|studies))\b",
    re.IGNORECASE,
)
# The answer's own rating lines ("Confidence: moderate (...)", "*Evidence level:* label") rate the evidence; they are
# not factual claims to audit.
_CONFIDENCE_LINE_RE = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:\*\*|\*|_)?\s*(?:(?:overall\s+)?confidence|evidence\s+level)\s*(?:\*\*|\*|_)?\s*[:\-–]",
    re.IGNORECASE,
)
_LIMITATIONS_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)\s*evidence\s+limitations?\b.*$", re.IGNORECASE | re.MULTILINE)
# The level of the answer's own confidence rating ("**Confidence:** high (...)", "Overall confidence: moderate").
_EMPH = r"(?:\*\*|__|\*|_)?"
_CONFIDENCE_LEVEL_RE = re.compile(
    rf"(?<![\w-]){_EMPH}(?:overall\s+)?confidence(?:\s+level)?{_EMPH}\s*[:\-–—]\s*{_EMPH}\s*"
    r"(?P<level>(?:very\s+)?(?:high|moderate|medium|low)(?:\s*(?:[-–/]\s*(?:to\s*[-–]?\s*)?|to\s+)(?:high|moderate|medium|low))?)\b"
    rf"(?P<close>{_EMPH})",
    re.IGNORECASE,
)
_LEVEL_WORDS = {"high": "high", "moderate": "moderate", "medium": "moderate", "low": "low"}
COMPUTED_CONFIDENCE_NOTE = "(computed from claim support)"
# Words that say how to answer, not what the question is about (the task-completion check ignores them).
_ANSWER_INSTRUCTION_WORDS = frozenset(
    """
    show every each step steps working calculation calculations follow correct explain explanation simplify
    simplified verify verified verification independent independently final answer answers please provide give
    detailed detail clear clearly exact exactly result results evaluate compute calculate find determine using check
    confirm write state include brief briefly full fully method approach shown
    """.split()
)


def reconcile_confidence_line(text: str, computed_band: str | None, note_text: str = COMPUTED_CONFIDENCE_NOTE) -> str:
    """The answer with its stated confidence level ("Confidence: high (...)") set to the computed band (high,
    medium -> "moderate", low) when they differ, keeping the model's reason and adding "(computed from claim
    support)", or `note_text`). Only the first rating (the bottom line's) is reconciled; without a computed band, or when the
    levels agree, the text is unchanged."""
    target = _LEVEL_WORDS.get(str(computed_band or "").strip().lower())
    if not text or target is None:
        return text
    for m in _CONFIDENCE_LEVEL_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        # The rating starts its line (after list or quote markers) or follows a finished sentence.
        if prefix.strip(" \t>-*+") and not re.search(r"[.!?)]\s+$", prefix):
            continue
        stated = {_LEVEL_WORDS[w.lower()] for w in re.findall(r"high|moderate|medium|low", m.group("level"), re.IGNORECASE)}
        if stated == {target}:
            return text
        word = target.capitalize() if m.group("level")[:1].isupper() else target
        end = m.end()
        # The note goes after the model's parenthetical reason when one follows the level, else after the level.
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end
        note_at = end
        rest = text[end:line_end]
        lead = re.match(r"\s*\(", rest)
        if lead:
            depth = 0
            for i in range(lead.end() - 1, len(rest)):
                depth += {"(": 1, ")": -1}.get(rest[i], 0)
                if depth == 0:
                    note_at = end + i + 1
                    break
        note = "" if note_text in text[end:line_end] else f" {note_text}"
        return text[:m.start("level")] + word + text[m.end("level"):note_at] + note + text[note_at:]
    return text


def _norm_ws(text: str) -> str:
    return " ".join(str(text or "").split())


def removable_defects(report: Any) -> list[Any]:
    """Claim-audit defects whose sentence must not stay in the answer: contradicted claims that carry the answer
    sentence they came from."""
    return [
        d for d in (getattr(report, "defects", None) or [])
        if getattr(d, "category", "") in REMOVABLE_DEFECTS and getattr(d, "sentence", None)
    ]


def _limitation_line(defect: Any) -> str:
    claim = truncate_words(unescape_entities(getattr(defect, "claim", "") or getattr(defect, "sentence", "")), 140)
    return f'- Removed "{claim}" because a retrieved source contradicts it.'


def remove_flagged_sentences(response: str, defects: Iterable[Any]) -> tuple[str, list[Any]]:
    """The answer without the sentences (or table rows) of the given defects, plus one line per removal under an
    "Evidence limitations" heading (created when missing). Returns (new text, defects actually removed)."""
    text = response
    removed: list[Any] = []
    seen: set[str] = set()
    for d in defects:
        sentence = str(getattr(d, "sentence", "") or "").strip()
        key = _norm_ws(sentence)
        if not sentence or key in seen:
            continue
        # The verifier quotes sentences from typography-folded text and the answer may still hold the original
        # characters, so the two are compared folded and the match is mapped back to the answer's positions.
        idx, end = find_folded(text, sentence)
        if idx < 0:
            logger.warning("Flagged sentence not found in the answer; it was not removed: %r", sentence[:160])
            continue
        seen.add(key)
        line_start = text.rfind("\n", 0, idx) + 1
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end
        line = text[line_start:line_end]
        rest = (line[: idx - line_start] + line[end - line_start:])
        if _TABLE_LINE_RE.match(line) or not _LINE_MARKER_RE.sub("", rest, count=1).strip():
            # A table row, or a line holding nothing else: drop the whole line.
            cut_end = line_end + 1 if line_end < len(text) else line_end
            text = text[:line_start] + text[cut_end:]
        else:
            after = end
            while after < len(text) and text[after] in " \t":
                after += 1
            text = text[:idx] + text[after:]
        removed.append(d)
    if not removed:
        return response, []
    lines = [_limitation_line(d) for d in removed]
    m = _LIMITATIONS_HEADING_RE.search(text)
    if m:
        insert_at = m.end()
        text = text[:insert_at] + "\n" + "\n".join(lines) + text[insert_at:]
    else:
        text = text.rstrip() + "\n\n### Evidence limitations\n" + "\n".join(lines) + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, removed


# ---------------------------------------------------------------------------
# Simulation outputs (Dynamis) and reference constants (Physis)
# ---------------------------------------------------------------------------
class _SimVariable(NamedTuple):
    source: str  # tool result key
    name: str
    initial: float | None
    final: float | None
    lo: float | None  # smallest value on the trajectory (dense output when recorded)
    hi: float | None
    mean: float | None
    unit: str  # the unit the tool stated for this variable ("" when none)
    fixed_point: bool  # an equilibrium value rather than a trajectory


def _num_or_none(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def simulation_variables(tool_results: dict[str, Any]) -> tuple[list[_SimVariable], bool, bool, float | None]:
    """(state variables of every simulated trajectory and fixed point, a time course ran, a fixed point was computed,
    the final time of the time course) from the structured Dynamis outputs."""
    out: list[_SimVariable] = []
    time_course = equilibrium = False
    t_final: float | None = None
    for key, res in (tool_results or {}).items():
        if res is None or not getattr(res, "success", False) or not isinstance(getattr(res, "data", None), dict):
            continue
        data = res.data
        units = data.get("units") if isinstance(data.get("units"), dict) else {}
        fixed = data.get("fixed_point")
        if isinstance(fixed, dict) and fixed:
            equilibrium = True
            for name, v in list(fixed.items())[:40]:
                val = _num_or_none(v)
                if val is not None:
                    out.append(_SimVariable(str(key), str(name), None, val, val, val, val, str(units.get(name) or ""), True))
        summary = data.get("summary")
        if not (isinstance(summary, dict) and summary and all(isinstance(s, dict) for s in summary.values())):
            continue
        time_course = True
        solver = data.get("solver") if isinstance(data.get("solver"), dict) else {}
        span = data.get("t_span") or solver.get("t_span")
        if isinstance(span, (list, tuple)) and len(span) == 2 and _num_or_none(span[1]) is not None:
            t_final = float(span[1])
        extrema = data.get("extrema") if isinstance(data.get("extrema"), dict) else {}
        for name, s in list(summary.items())[:40]:
            ext = extrema.get(name) if isinstance(extrema.get(name), dict) else {}
            lows = [x for x in (_num_or_none(s.get("min")), _num_or_none(ext.get("dense_min"))) if x is not None]
            highs = [x for x in (_num_or_none(s.get("max")), _num_or_none(ext.get("dense_max"))) if x is not None]
            out.append(_SimVariable(
                str(key), str(name), _num_or_none(s.get("initial")), _num_or_none(s.get("final")),
                min(lows) if lows else None, max(highs) if highs else None, _num_or_none(s.get("mean")),
                str(units.get(name) or ""), False,
            ))
    return out, time_course, equilibrium, t_final


# What the answer says a value is: the run's final, initial, extreme or mean value, or an equilibrium.
_VALUE_ROLE_RES: tuple[tuple[str, re.Pattern], ...] = (
    ("equilibrium", re.compile(r"\b(?:steady[\s\-]*state|equilibri(?:um|a)|fixed\s+point)\b", re.IGNORECASE)),
    ("final", re.compile(r"\b(?:final(?:ly)?|at\s+the\s+end|end\s+of|ends?\b|ended|settles?\s+(?:at|to)|after\s+the\s+run)\b", re.IGNORECASE)),
    ("initial", re.compile(r"\b(?:initial(?:ly)?|starts?\s+(?:at|from)|starting|at\s+t\s*=\s*0\b)", re.IGNORECASE)),
    ("max", re.compile(r"\b(?:peak|peaks|maximum|max|highest|largest)\b", re.IGNORECASE)),
    ("min", re.compile(r"\b(?:minimum|min|lowest|smallest|trough)\b", re.IGNORECASE)),
    ("mean", re.compile(r"\b(?:mean|average|averaged)\b", re.IGNORECASE)),
)
# Between a state variable's name and its value: punctuation, markup and words that attach the value ("x reached
# 0.42", "| x | 0.42 |", "x(10) ≈ **0.42**").
_STATE_VALUE_GAP = re.compile(
    r"^[\s*_`|:=≈~()\[\]$]*(?:(?:reached|reaches|reach|was|is|of|at|to|final|value|ends?|ended|settles?|equals?|"
    r"approximately|about|roughly|peaks?|falls?|rises?|drops?)\s*[\s*_`|:=≈~()$]*)*$",
    re.IGNORECASE,
)
_STATE_NUMBER_RE = re.compile(
    r"(?<![\w.])((?:(?<=[\s(|:=*$])|^)[-−])?(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(\s*(?:%|×|x\b|fold\b|times\b))?(\s*" + _UNIT + _UNIT_END + ")?"
)


def _state_name_pattern(name: str) -> re.Pattern:
    """A state variable's name as a whole token: '-' and '+' are part of names, so 'x' never matches inside 'x-dot';
    a one- or two-character name ('x', 'S', 'I') keeps its case."""
    flags = 0 if len(name) <= 2 else re.IGNORECASE
    return re.compile(rf"(?<![\w\-+'.]){re.escape(name)}(?![\w\-+']|\)[\w\-+])", flags)


class TribosVerifier:
    """
    STEM verifier applying deterministic rules and evidence cross-referencing.
    Requires external evidence or deterministic computational outputs for factual and quantitative assertions.
    """

    # Permitted numerical tolerance against simulator outputs: 5.0% relative error, or 1% of the trajectory's scale
    RELATIVE_NUMERICAL_TOLERANCE = 0.05
    SCALE_NUMERICAL_TOLERANCE = 0.01

    # A sentence is considered grounded in a passage when it shares this many distinctive terms
    MIN_SHARED_CLAIM_TERMS = 2

    @staticmethod
    def _extract_identifiers(text: str) -> dict[str, list[str]]:
        """PMIDs and DOIs named in a text (the other scholarly ids are identifier families, see id_families)."""
        return {
            "pmids": sorted(set(re.findall(r"\bPMID:?\s*(\d{1,9})\b", text, re.IGNORECASE))),
            "dois": sorted({d.rstrip(".,;)") for d in re.findall(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", text)}),
        }

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Sentences and lines of `text` (see sentence_spans: abbreviations such as "et al." do not end a sentence
        and a table row stays whole). Not markdown-aware: claim checking uses markdown_claim_units."""
        return [text[s:e].strip() for s, e in sentence_spans(text)]

    # Models often typeset with Unicode hyphens ("x‑dot", U+2011), minus signs, and narrow/no-break
    # spaces. Fold them to ASCII before matching so "x‑dot = 0.4" is never read as a claim about "x".
    # The table is shared with the orchestrator (tribos.utils.text), so a flagged sentence can be found again.
    _TYPOGRAPHY_FOLD = TYPOGRAPHY_FOLD

    @classmethod
    def _normalize_typography(cls, text: str) -> str:
        return fold_typography(text)

    @staticmethod
    def _salient_terms(text: str) -> set[str]:
        return {
            w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text.lower())
            if w not in _STOPWORDS and not re.fullmatch(r"[\d.\-]+", w)
        }

    def verify_response(
        self,
        query: str,
        response_markdown: str,
        tool_results: dict[str, ToolResult],
        historical_identifiers: dict[str, Iterable[str]] | None = None,
        context_identifiers: dict[str, Iterable[str]] | None = None,
        query_context: Any = None,
        entailment_judge: Callable[[str, list[dict[str, str]]], dict[str, Any] | None] | None = None,
    ) -> VerificationReport:
        """
        Audit candidate response against observed tool evidence, numerical outputs, and identifiers.
        Missing evidence, unobserved citations, and material numerical errors strictly prevent verification.
        `historical_identifiers` holds identifiers from VERIFIED_EMPIRICAL memory of earlier turns in the thread.
        `context_identifiers` holds identifiers the query context and evidence sources legitimately know about
        (resolved entities, attached datasets, plugin allow-lists), keyed by legacy key or id family name.
        `entailment_judge(claim_text, [{"source_key", "passage"}]) -> {"status", "reason"}` is an optional second
        pass for semantic support; it can only downgrade a deterministic verdict (or confirm an unsupported
        cited claim). Identifier and numeric checks stay deterministic.
        """
        try:
            from ..extensions import load_extensions

            load_extensions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extensions unavailable for verification: %s", exc)

        response_markdown = self._normalize_typography(response_markdown)
        tool_results = tool_results or {}
        defects: list[DefectItem] = []
        verified_ids: list[str] = []
        claim_support: list[dict[str, Any]] = []

        # Observed identifiers strictly from successful tool executions
        observed_pmids: set[str] = set()
        observed_dois: set[str] = set()
        observed_keys: set[str] = set()  # canonical scholarly keys (tribos.sources.keys) of every retrieved record
        observed_family: dict[str, set[str]] = {f.name: set() for f in FAMILIES}
        observed_passages: list[str] = []
        passage_docs: list[tuple[str, str, str | None]] = []  # (evidence_key, lowercased text, passage_id)
        evidence_documents: list[str] = []  # lowercased passages + serialized tool outputs for registered checks
        evidence_keys: list[str] = []  # parallel to evidence_documents: 'tool:<name>', 'ARXIV:<id>', 'DOI:<doi>', ...
        evidence_doc_passage_ids: list[str | None] = []
        # Structured documents for the built-in claim audit: passages with their section, provider documents and
        # one document per tool record, never a whole serialized tool output.
        grounding: list[_Doc] = []
        doc_providers = get_evidence_doc_providers()

        # What tools did in this run, for sentences about the run itself (a failed or empty lookup).
        tool_events = self._tool_events(tool_results)
        for t_name, t_res in tool_results.items():
            if not t_res or not t_res.success:
                continue
            data = apply_serialization_filters(t_name, t_res.data)

            # Literature passages and the scholarly ids every record of this output carries
            has_passages = isinstance(data, dict) and "ranked_passages" in data
            tool_passages: list[tuple[str, str, str | None]] = []
            tool_grounding: list[_Doc] = []
            for rec in _walk_records(data):
                observed_keys.update(literature_keys(rec))
            if has_passages:
                for p in data["ranked_passages"] or []:
                    if not isinstance(p, dict):
                        continue
                    keys = literature_keys(p)
                    if p.get("pmid"):
                        observed_pmids.add(str(p["pmid"]))
                    if p.get("doi"):
                        observed_dois.add(str(p["doi"]))
                    if not p.get("passage_text"):
                        continue
                    # Folded like the answer ("10·2 K" -> "10.2 K") so figures compare equal.
                    text = fold_typography(str(p["passage_text"])).lower()
                    observed_passages.append(text)
                    pid = str(p["passage_id"]) if p.get("passage_id") else None
                    key = keys[0] if keys else (f"passage:{pid}" if pid else f"tool:{t_name}")
                    tool_passages.append((key, text, pid))
                    title = fold_typography(str(p.get("title") or "")).lower()
                    tool_grounding.append(_Doc(key, f"{title}. {text}" if title else text, pid, str(p.get("section") or ""),
                                               None, tuple(keys[1:])))
            if isinstance(data, dict):
                # A correction notice the exact lookup retrieved is a retrieved record, cited by its own id.
                for entry in (data.get("retrieval") or {}).get("pinned") or []:
                    for c in (entry.get("corrections") or []) if isinstance(entry, dict) else []:
                        if isinstance(c, dict) and c.get("retrieved") and re.fullmatch(r"\d{1,9}", str(c.get("id") or "")):
                            observed_pmids.add(str(c["id"]))
            for pmid_key in ("pmids", "declared_source_pmids"):
                for p in str(t_res.canonical_ids.get(pmid_key) or "").split(","):
                    if p.strip():
                        observed_pmids.add(p.strip())
            for d in str(t_res.canonical_ids.get("dois") or "").split(","):
                if d.strip():
                    observed_dois.add(d.strip())
            for fam in FAMILIES:
                for ck in fam.canonical_keys:
                    if t_res.canonical_ids.get(ck):
                        observed_family[fam.name] |= normalize_ids(fam.name, t_res.canonical_ids[ck])

            # A registered provider may replace this tool's default evidence documents with finer-grained ones.
            provided: list[tuple[str, str]] | None = None
            for provider in doc_providers:
                try:
                    out = provider(t_name, t_res)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Evidence doc provider failed for %s: %s", t_name, exc)
                    continue
                if isinstance(out, list):
                    provided = out
                    break

            # Any identifier present anywhere in a successful tool output counts as observed
            serialized = ""
            if data:
                try:
                    serialized = json.dumps(data, default=str)
                except (TypeError, ValueError):
                    serialized = str(data)
                serialized = re.sub(r'"plot_base64_png":\s*"[^"]*"', "", serialized)
                observed_dois.update(self._extract_identifiers(serialized)["dois"])
                for name, found in extract_family_ids(serialized).items():
                    observed_family[name] |= found

            if provided is not None:
                # Provided documents replace this tool's whole-tool doc or passages for claim grounding;
                # the passages still count for the identifier checks below.
                for key, doc in provided:
                    evidence_documents.append(str(doc).lower())
                    evidence_keys.append(str(key))
                    evidence_doc_passage_ids.append(None)
                    grounding.append(_Doc(str(key), fold_typography(str(doc)).lower(), None, ""))
            else:
                passage_docs.extend(tool_passages)
                grounding.extend(tool_grounding)
                if serialized and not has_passages:
                    # Registered checks still receive the whole serialization; the claim audit uses records.
                    evidence_documents.append(serialized.lower())
                    evidence_keys.append(f"tool:{t_name}")
                    evidence_doc_passage_ids.append(None)
                    grounding.extend(
                        _Doc(f"tool:{t_name}", fold_typography(chunk), None, "", record_url(rec))
                        for chunk, rec in _record_items(data)
                    )

        for key, text, pid in passage_docs:
            evidence_documents.append(text)
            evidence_keys.append(key)
            evidence_doc_passage_ids.append(pid)

        # Identifiers verified in earlier turns of this thread (VERIFIED_EMPIRICAL memory only)
        historical = {k: set(v) for k, v in (historical_identifiers or {}).items()}
        observed_pmids |= historical.get("pmids", set())
        observed_dois |= historical.get("dois", set())

        # Identifiers the query context and evidence sources legitimately know about
        context: dict[str, set[str]] = {}
        for k, v in (context_identifiers or {}).items():
            context[k] = normalize_ids(k, v) if k in observed_family else {str(x) for x in (v or []) if x}
        observed_pmids |= context.get("pmids", set())
        observed_dois |= context.get("dois", set())

        query_family_ids = extract_family_ids(self._normalize_typography(query or ""))
        for fam in FAMILIES:
            observed_family[fam.name] |= normalize_ids(fam.name, historical.get(fam.name, set()))
            observed_family[fam.name] |= context.get(fam.name, set())
            observed_family[fam.name] |= query_family_ids[fam.name]
        for fam_name, prefix in _FAMILY_PREFIX.items():
            observed_keys |= {scholarly_key(prefix, fid) for fid in observed_family.get(fam_name, set())}
        observed_keys |= {make_key("PMID", p) for p in observed_pmids} | {make_key("DOI", d) for d in observed_dois}

        # Registered vetoes (e.g. retracted articles) override every other source of trust.
        vetoed: dict[str, dict[str, str]] = {}
        for veto in get_identifier_vetoes():
            try:
                result = veto(tool_results) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Identifier veto failed: %s", exc)
                continue
            for fam_name, ids in result.items():
                bucket = vetoed.setdefault(fam_name, {})
                for vid, reason in (ids or {}).items():
                    norm = str(vid).lower() if fam_name == "dois" else next(iter(normalize_ids(fam_name, [vid])), str(vid))
                    bucket.setdefault(norm, str(reason))
        vetoed_labels = {f.name: f.label for f in FAMILIES}
        vetoed_identifiers = sorted(
            f"{'PMID' if k == 'pmids' else 'DOI' if k == 'dois' else vetoed_labels.get(k, k.upper())}:{vid}"
            for k, ids in vetoed.items()
            for vid in ids
        )

        def retracted_defect(display: str, reason: str) -> DefectItem:
            return DefectItem(
                category="RETRACTED_CITATION",
                severity=DefectSeverity.CRITICAL,
                description=reason,
                suggested_correction=(
                    "Remove the citation and any claim that depends on it; you may state that a retrieved article "
                    "was excluded because it was retracted."
                ),
                claim=display,
            )

        observed_dois_lower = {d.lower() for d in observed_dois}
        extracted_ids = self._extract_identifiers(response_markdown)
        cited_family = {k: sorted(v) for k, v in extract_family_ids(response_markdown).items()}
        resp_lower = response_markdown.lower()

        # -------------------------------------------------------------
        # 1. IDENTIFIER GROUNDING (No Whitelisting: Must be Observed)
        # -------------------------------------------------------------
        # Cited DOIs must be present in the retrieved records or passages
        for doi in extracted_ids["dois"]:
            if doi.lower() in vetoed.get("dois", {}):
                defects.append(retracted_defect(f"DOI {doi}", vetoed["dois"][doi.lower()]))
            elif (doi.lower() in observed_dois_lower or make_key("DOI", doi) in observed_keys
                  or any(_doi_in_passage(doi, p) for p in observed_passages)):
                verified_ids.append(f"DOI:{doi}")
            else:
                defects.append(
                    DefectItem(
                        category="CITATION",
                        severity=DefectSeverity.CRITICAL,
                        description=f"DOI '{doi}' cited in text was not observed in any retrieved literature record or passage.",
                        suggested_correction="Remove the unobserved DOI or cite only DOIs returned by the literature search (Archivon).",
                        claim=f"DOI {doi}",
                    )
                )

        # Cited PMIDs must be present in the retrieved records or passages
        for pmid in extracted_ids["pmids"]:
            if pmid in vetoed.get("pmids", {}):
                defects.append(retracted_defect(f"PMID {pmid}", vetoed["pmids"][pmid]))
            elif pmid in observed_pmids or any(_pmid_in_passage(pmid, p) for p in observed_passages):
                verified_ids.append(f"PMID:{pmid}")
            else:
                defects.append(
                    DefectItem(
                        category="CITATION",
                        severity=DefectSeverity.CRITICAL,
                        description=f"PMID '{pmid}' cited in text does not correspond to any retrieved literature record.",
                        suggested_correction="Cite only PMIDs present in the retrieved literature.",
                        claim=f"PMID {pmid}",
                    )
                )

        # Identifier families (arXiv, zbMATH, MR, ADS, OEIS, Materials Project, ISBN, dataset and computation ids).
        # Checked whether or not the sentence is hedged: naming an unobserved id is itself the defect. A scholarly id
        # is compared by its canonical key, so "arXiv:2312.04511v2" grounds in a record with arxiv_id 2312.04511.
        for fam in FAMILIES:
            prefix = _FAMILY_PREFIX.get(fam.name)
            for fid in cited_family.get(fam.name, []):
                key = scholarly_key(prefix, fid) if prefix else ""
                if fid in vetoed.get(fam.name, {}):
                    defects.append(retracted_defect(fid, vetoed[fam.name][fid]))
                elif fid in observed_family[fam.name] or (key and key in observed_keys):
                    verified_ids.append(key or f"{fam.label}:{fid}")
                else:
                    defects.append(
                        DefectItem(
                            category="IDENTIFIER",
                            severity=DefectSeverity(fam.severity),
                            description=(
                                f"{fam.label} identifier '{fid}' was cited but was not returned by any executed tool, "
                                f"retrieved passage, or your question."
                            ),
                            suggested_correction=fam.correction,
                            claim=fid,
                        )
                    )

        # -------------------------------------------------------------
        # 2. LITERATURE AND MEASUREMENT CLAIMS (sentence-level grounding)
        # -------------------------------------------------------------
        claims: list[ClaimRecord] = []
        claim_defects, claim_support = self._audit_claims(
            response_markdown, grounding, claims, entailment_judge, tool_events=tool_events,
        )
        defects.extend(claim_defects)

        # -------------------------------------------------------------
        # 2b. MATHEMATICAL STATEMENTS (deterministic: tribos.verify.math_claims)
        # -------------------------------------------------------------
        # The answer's own equations, derivation steps and result tables are re-evaluated with the question's values
        # and the tools' structured outputs; a computed result restated wrongly is contradicted here.
        math_audit = None
        try:
            from . import math_claims as math_claims_mod

            math_audit = math_claims_mod.audit_answer(response_markdown, query, tool_results)
        except Exception as exc:  # noqa: BLE001 - the rest of the verification stands without it
            logger.warning("Mathematical statement audit failed: %s", exc)
        if math_audit is not None:
            status_map = {"passed": "supported", "failed": "contradicted", "unsupported": "unsupported",
                          "inconclusive": "inconclusive"}
            for mc in math_audit.claims:
                sources = list(dict.fromkeys(lk.source for lk in mc.links)) or ["answer"]
                claims.append(ClaimRecord(
                    claim_id=f"math:{mc.claim_id}",
                    claim_type="mathematical" if mc.kind != "grounding" else "computational",
                    claim_text=(f"{mc.context}: " if mc.context else "") + mc.text,
                    evidence=[ClaimEvidence(source_key=s, passage=mc.detail[:400]) for s in sources[:3]],
                    status=status_map.get(mc.status, "inconclusive"),
                    reason=mc.detail[:400],
                ))
            for item in math_claims_mod.claim_defects(math_audit):
                defects.append(DefectItem(
                    category=item["category"], severity=DefectSeverity(item["severity"]),
                    description=item["description"], suggested_correction=item["suggested_correction"],
                    claim=item["claim"],
                ))
        failed_math = [re.sub(r"\s+", " ", c.source_text) for c in (math_audit.failed if math_audit is not None else [])]

        # Disallow forbidden vendor platform leaks
        for forbidden in ["langgraph", "openai", "nvidia"]:
            if re.search(rf"\b{forbidden}\b", resp_lower):
                defects.append(
                    DefectItem(
                        category="INTEGRITY",
                        severity=DefectSeverity.CRITICAL,
                        description=f"Response mentions internal provider or framework name '{forbidden}'.",
                        suggested_correction="Use the Tribos agent names (Archivon, Axiom, Dynamis, Physis, Calcula, WebSurfer).",
                    )
                )

        # -------------------------------------------------------------
        # 3. NUMERICAL CONSISTENCY: simulated state variables (Dynamis)
        # -------------------------------------------------------------
        num_passed, num_failed = self._check_simulation_values(response_markdown, tool_results, claims, defects, failed_math)
        self._check_equilibrium_wording(response_markdown, tool_results, defects)

        # -------------------------------------------------------------
        # 4. TASK COMPLETION & EMPTY EVIDENCE PENALTY
        # -------------------------------------------------------------
        # If all tools failed or were empty, the response must not present findings as if they were checked
        non_empty_tools = [res for res in tool_results.values() if res and res.success and res.data]
        # Which completion checks apply depends on the task (audit I14): a self-contained calculation, proof or copy
        # needs no outside evidence, so "no tool returned evidence" is not a defect there; and an answer whose form the
        # user fixed (two lines, 40 words, plain text) cannot repeat the question's words, so word overlap says nothing.
        from ..utils.output_contract import extract as extract_contract

        need = getattr(query_context, "evidence_need", None) if query_context is not None else None
        self_contained = bool(need is not None and getattr(need, "skip_retrieval", False))
        strict_form = extract_contract(query or "").strict_form
        if not non_empty_tools and not self_contained:
            # Response must state that evidence is unavailable
            if "unavailable" not in resp_lower and "insufficient" not in resp_lower and "no data" not in resp_lower:
                defects.append(
                    DefectItem(
                        category="COMPLETION",
                        severity=DefectSeverity.CRITICAL,
                        description="All tool executions yielded no data, but response presents findings without stating that evidence was unavailable.",
                        suggested_correction="Explicitly report that the tools returned no data and state the limitation clearly.",
                    )
                )

        # The question's subject: its content words and its numbers (for mathematics the numbers are the subject).
        # Words that only say how to answer ("show every step, verify the final answer") are not the subject.
        from ..utils.output_contract import mask_instructions

        subject_query = mask_instructions(query or "")
        query_words = [
            w.lower() for w in re.split(r"\W+", subject_query) if len(w) > 3 and w.lower() not in _ANSWER_INSTRUCTION_WORDS
        ]
        query_numbers = set(re.findall(r"\d+(?:\.\d+)?", subject_query))
        matched = sum(1 for w in query_words if w in resp_lower) + sum(1 for n in query_numbers if n in resp_lower)
        subject_size = len(query_words) + len(query_numbers)
        if subject_size and matched / subject_size < 0.25 and not self_contained and not strict_form:
            defects.append(
                DefectItem(
                    category="COMPLETION",
                    severity=DefectSeverity.MAJOR,
                    description="Response does not appear to address the primary focus of the user inquiry.",
                    suggested_correction=f"Directly address the user query: '{query}'.",
                )
            )

        # -------------------------------------------------------------
        # 4b. REGISTERED FEATURE CHECKS (ODE parameters, evidence grades, dataset consent, ...)
        # -------------------------------------------------------------
        checks = get_verification_checks()
        if checks:
            observed_all: dict[str, set[str]] = {
                "pmids": set(observed_pmids),
                "dois": set(observed_dois),
                "keys": set(observed_keys),
                **{k: set(v) for k, v in observed_family.items()},
            }
            vctx = VerificationContext(
                query=query,
                response=response_markdown,
                sentences=self._split_sentences(response_markdown),
                table_rows=self._table_rows(response_markdown),
                tool_results=tool_results,
                evidence_documents=list(evidence_documents),
                evidence_keys=list(evidence_keys),
                observed=observed_all,
                cited={**{k: list(v) for k, v in extracted_ids.items()}, **cited_family},
                historical=historical,
                context_identifiers=context,
                vetoed=vetoed,
                query_context=query_context,
                hedge_pattern=_HEDGE_PATTERN,
            )
            # One claim is flagged once per category: a registered check's more specific defect replaces the
            # generic sentence-grounding one, and two registered checks never both count it.
            flagged: set[tuple[str, str]] = set()
            builtin = {(d.category, d.claim): d for d in defects if d.claim}
            for check_key, check in checks:
                try:
                    found = check(vctx) or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Verification check %s failed: %s", check_key, exc)
                    continue
                for item in found:
                    defect = self._defect_from_dict(item)
                    if defect is None:
                        continue
                    claim = defect.claim
                    # A sentence the mathematical audit already contradicted is not penalised twice.
                    norm = re.sub(r"\s+", " ", claim or "")
                    if defect.category == "COMPUTATION" and any(t and t in norm for t in failed_math):
                        continue
                    if claim:
                        key = (defect.category, claim)
                        if key in flagged:
                            continue
                        flagged.add(key)
                        generic = builtin.pop(key, None)
                        if generic is not None and generic.severity == defect.severity:
                            defects.remove(generic)
                    defects.append(defect)

        # -------------------------------------------------------------
        # 5. RIGOROUS VERIFICATION SCORE COMPUTATION
        # -------------------------------------------------------------
        base_score = 1.0
        critical_count = 0
        for d in defects:
            if d.severity == DefectSeverity.CRITICAL:
                base_score -= 0.55  # Critical defect immediately pulls score below passing threshold
                critical_count += 1
            elif d.severity == DefectSeverity.MAJOR:
                base_score -= 0.25
            elif d.severity == DefectSeverity.MINOR:
                base_score -= 0.10

        final_score = max(0.0, min(1.0, base_score))
        contradicted = sum(1 for c in claims if c.status == "contradicted")
        unsupported = sum(1 for c in claims if c.status == "unsupported")
        unchecked = sum(1 for c in claims if c.status == "not_checked")
        inconclusive = sum(1 for c in claims if c.status == "inconclusive")
        passed = (final_score >= 0.80) and (critical_count == 0) and contradicted == 0
        # Coverage: run-status statements are checked against the tool log, not evidence; they are not counted.
        material = [c for c in claims if c.claim_type != "operational"]
        supported = sum(1 for c in material if c.status == "supported")
        evaluated = sum(1 for c in material if c.status in ("supported", "contradicted", "unsupported"))
        coverage = {
            "extracted": len(material),
            "evaluated": evaluated,
            "passed": supported,
            "failed": sum(1 for c in material if c.status == "contradicted"),
            "unsupported": sum(1 for c in material if c.status == "unsupported"),
            "inconclusive": sum(1 for c in material if c.status in ("inconclusive", "not_checked")),
        }
        fully = passed and not (contradicted or unsupported or unchecked or inconclusive)
        if evaluated == 0:
            report_status = "failed" if not passed else "not_evaluated"
        elif not passed or contradicted:
            report_status = "failed"
        elif fully:
            report_status = "verified"
        else:
            report_status = "checked"

        lesson = None
        if not passed:
            top_defect = defects[0] if defects else None
            if top_defect:
                lesson = f"Reflexion Defect [{top_defect.category}]: {top_defect.description}"

        return VerificationReport(
            passed=passed,
            verification_score=round(final_score, 2),
            defects=defects,
            verified_identifiers=list(dict.fromkeys(verified_ids)),
            numerical_checks_passed=num_passed,
            numerical_checks_failed=num_failed,
            failure_lesson=lesson,
            claim_support=claim_support,
            vetoed_identifiers=vetoed_identifiers,
            claims=claims[:MAX_CLAIM_RECORDS],
            contradicted_claims=contradicted,
            unsupported_claims=unsupported,
            unchecked_claims=unchecked,
            inconclusive_claims=inconclusive,
            fully_verified=bool(fully and evaluated),
            coverage=coverage,
            status=report_status,
            math_audit=math_audit.to_dict() if math_audit is not None else None,
            units=math_audit.units if math_audit is not None else {},
            answer_hash=hashlib.sha256((response_markdown or "").encode("utf-8")).hexdigest()[:16],
            record_revision=math_audit.record_revision if math_audit is not None else "",
        )

    @staticmethod
    def _tool_events(tool_results: dict[str, Any]) -> list[tuple[str, str]]:
        """(tool key, lowercased outcome) for failed calls, error payloads and exact-identifier lookups."""
        events: list[tuple[str, str]] = []
        for t_name, t_res in (tool_results or {}).items():
            if t_res is not None and not t_res.success:
                events.append((str(t_name), f"{t_name} {getattr(t_res, 'tool_name', '') or ''}: {t_res.error or 'failed'}".lower()))
            elif t_res is not None and isinstance(t_res.data, dict) and t_res.data.get("error"):
                events.append((str(t_name), f"{t_name}: {t_res.data.get('error')}".lower()))
            if t_res is not None and t_res.success and isinstance(t_res.data, dict):
                # Exact-identifier lookups and their linked corrections are outcomes of this run too: what was
                # retrieved, what was not, and that corrected content is never applied automatically.
                for entry in (t_res.data.get("retrieval") or {}).get("pinned") or []:
                    if not isinstance(entry, dict):
                        continue
                    ident = str(entry.get("normalized") or entry.get("id") or "")
                    events.append((str(t_name), f"{t_name}: exact lookup of {ident}: {entry.get('status')}".lower()))
                    for c in entry.get("corrections") or []:
                        if not isinstance(c, dict):
                            continue
                        cid = str(c.get("id") or "")
                        state = (
                            f"retrieved; {'text available' if c.get('content_available') else 'no abstract or text'}"
                            if c.get("retrieved") else "not retrieved"
                        )
                        event = (
                            f"{t_name}: {c.get('type') or 'correction'} {cid} for {ident}: correction notice {state}; "
                            "corrected content not applied"
                        )
                        events.append((str(t_name), event.lower()))
        return events

    # ------------------------------------------------------------------
    # Simulations and reference constants
    # ------------------------------------------------------------------
    def _check_simulation_values(
        self, text: str, tool_results: dict[str, Any], claims: list[ClaimRecord], defects: list[DefectItem],
        failed_math: list[str],
    ) -> tuple[int, int]:
        """Values the answer gives for a simulated state variable against the computed trajectory: the stated role's
        value (final, initial, peak, minimum, mean, equilibrium) when the answer names one, else the trajectory's
        range. A unit with an SI prefix is only compared when the tool stated the variable's unit."""
        variables, _time_course, equilibrium, t_final = simulation_variables(tool_results)
        if not variables:
            return 0, 0
        names = list(dict.fromkeys(v.name for v in variables))
        patterns = {n: _state_name_pattern(n) for n in names}
        passed = failed = 0
        reported: set[tuple[str, float]] = set()
        code_spans = [(m.start(), m.end()) for m in re.finditer(r"```.*?```", text, re.S)]
        for name in names:
            mine = [v for v in variables if v.name == name]
            others = [p for n, p in patterns.items() if n != name]
            for m in patterns[name].finditer(text):
                if any(s <= m.start() < e for s, e in code_spans):
                    continue
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start: line_end if line_end >= 0 else len(text)]
                if any(t and t in re.sub(r"\s+", " ", line) for t in failed_math):
                    continue  # the mathematical audit already judged this line
                rest = text[m.end(): line_end if line_end >= 0 else len(text)][:120]
                arg = re.match(r"\s*\(([^()]{0,20})\)", rest)
                at_final = False
                if arg:
                    at = number_parts(arg.group(1).strip().lstrip("t= "))
                    at_final = bool(t_final is not None and at is not None and abs(at[0] - t_final) <= 1e-9 * max(1.0, t_final))
                    rest = rest[arg.end():]
                cut = len(rest)
                for pat in others:
                    om = pat.search(rest)
                    if om:
                        cut = min(cut, om.start())
                segment = rest[:cut]
                nm = next((x for x in _STATE_NUMBER_RE.finditer(segment) if _STATE_VALUE_GAP.match(segment[: x.start()])), None)
                if nm is None:
                    continue
                sign, num_str, relative, unit_raw = nm.group(1), nm.group(2), nm.group(3), (nm.group(4) or "").strip()
                if relative:
                    continue  # percentages, fold changes and ratios are not state values
                if not unit_raw and in_non_simulation_table(text, m.start(), names):
                    continue  # "| Silicon | 1954 |" in a discovery table is a year, not a state value
                parts = number_parts(num_str)
                if parts is None:
                    continue
                value, ulp = parts
                if sign:
                    value = -value
                declared = next((v.unit for v in mine if v.unit), "")
                if unit_raw:
                    u, scale = cased_unit_key(unit_raw)
                    if declared:
                        du, dscale = cased_unit_key(declared)
                        if du != u:
                            continue
                        value, ulp = value * scale / dscale, ulp * scale / dscale
                    elif scale != 1.0 or u in ("s", "%", "month", "year"):
                        continue  # a prefixed or time unit for a variable whose unit the tool did not state
                context = text[max(line_start, m.start() - 60): m.end() + (nm.end() if nm else 0) + 40]
                role = "final" if at_final else next((r for r, pat in _VALUE_ROLE_RES if pat.search(context)), "range")
                verdict = self._state_verdict(mine, value, ulp, role, equilibrium)
                raw = f"{name}: {nm.group(0).strip()}"
                source = f"tool:{mine[0].source}"
                if verdict is None:
                    passed += 1
                    self._add_claim(claims, "computational", raw, "supported", "matches the simulation output", source)
                    continue
                failed += 1
                self._add_claim(claims, "computational", raw, "contradicted", verdict, source)
                if (name, round(value, 9)) in reported:
                    continue
                reported.add((name, round(value, 9)))
                defects.append(DefectItem(
                    category="NUMERICAL",
                    severity=DefectSeverity.CRITICAL,
                    description=f"Value for state variable '{name}' given as '{nm.group(0).strip()}' does not match the simulation: {verdict}.",
                    suggested_correction=f"Restate {name} from the simulation output (Dynamis) with its role (final, peak, equilibrium) and unit.",
                    claim=raw,
                ))
        return passed, failed

    def _state_verdict(self, runs: list[_SimVariable], value: float, ulp: float, role: str, equilibrium: bool) -> str | None:
        """None when the value matches one of the runs of this variable for the stated role, else why it does not."""
        reasons: list[str] = []
        for v in runs:
            if v.fixed_point and role not in ("equilibrium", "range", "final"):
                continue
            scale = max(abs(x) for x in (v.lo, v.hi, v.final, v.initial, 1e-12) if x is not None)
            tol = max(self.SCALE_NUMERICAL_TOLERANCE * scale, 0.55 * ulp)
            if role == "equilibrium" and equilibrium and not v.fixed_point:
                continue  # an equilibrium value is compared with the computed fixed point
            target = {"final": v.final, "initial": v.initial, "max": v.hi, "min": v.lo, "mean": v.mean,
                      "equilibrium": v.final}.get(role)
            if target is not None and not (role == "equilibrium" and not v.fixed_point and equilibrium):
                if abs(value - target) <= max(tol, self.RELATIVE_NUMERICAL_TOLERANCE * abs(target)):
                    return None
                label = "fixed point" if v.fixed_point else role if role != "equilibrium" else "final"
                reasons.append(f"the computed {label} value is {target:.4g}")
                continue
            if v.lo is not None and v.hi is not None:
                if v.lo - tol <= value <= v.hi + tol:
                    return None
                reasons.append(f"the computed trajectory stays within [{v.lo:.4g}, {v.hi:.4g}]")
        return "; ".join(dict.fromkeys(reasons)) if reasons else None

    def _check_equilibrium_wording(self, text: str, tool_results: dict[str, Any], defects: list[DefectItem]) -> None:
        """A time-course simulation without a computed fixed point gives values at the end of the run, not an
        equilibrium. A forced or periodic steady state (an amplitude, a limit cycle) is not a fixed point either."""
        variables, time_course, equilibrium, _t = simulation_variables(tool_results)
        if not time_course or equilibrium:
            return
        names = list(dict.fromkeys(v.name for v in variables))
        patterns = [_state_name_pattern(n) for n in names]
        for sentence in self._split_sentences(text):
            if (
                re.search(r"steady[\s\-]*state|equilibri(?:um|a)|fixed\s+point", sentence, re.IGNORECASE)
                and re.search(r"\d", sentence)
                and any(p.search(sentence) for p in patterns)
                and not re.search(r"amplitude|response|oscillat\w*|periodic|limit\s+cycle|forced|driven|phase\s+lag", sentence, re.IGNORECASE)
                and not _HEDGE_PATTERN.search(sentence)
                and not _SUGGESTION_PATTERN.search(sentence)
            ):
                defects.append(
                    DefectItem(
                        category="MODELING_DISTINCTION",
                        severity=DefectSeverity.MAJOR,
                        description="Response describes values at the end of a time-course simulation as an equilibrium without computing the fixed point.",
                        suggested_correction="Describe the values as the state at the end of the simulated interval, or compute the fixed point (Dynamis equilibrium) before calling it an equilibrium.",
                        claim=truncate_words(sentence, 240),
                    )
                )
                return

    @staticmethod
    def _table_rows(text: str) -> list[str]:
        """Markdown table rows (header and body), excluding |---|---| separator rows."""
        rows = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") and not (re.fullmatch(r"[\s|:\-]+", stripped) and "-" in stripped):
                rows.append(stripped)
        return rows

    @staticmethod
    def _defect_from_dict(item: Any) -> DefectItem | None:
        if isinstance(item, DefectItem):
            return item
        if not isinstance(item, dict):
            return None
        try:
            severity = DefectSeverity(str(item.get("severity", "MAJOR")).upper())
        except ValueError:
            severity = DefectSeverity.MAJOR
        return DefectItem(
            category=str(item.get("category") or "CLAIM"),
            severity=severity,
            description=str(item.get("description") or ""),
            suggested_correction=str(item.get("suggested_correction") or ""),
            claim=item.get("claim"),
        )

    # ------------------------------------------------------------------
    # Claim-level audit
    # ------------------------------------------------------------------
    @staticmethod
    def _add_claim(
        claims: list[ClaimRecord],
        claim_type: str,
        text: str,
        status: str,
        reason: str,
        source_key: str | None = None,
        passage: str = "",
        passage_id: str | None = None,
        extra_evidence: list[ClaimEvidence] | None = None,
        cited_source_supported: bool | None = None,
    ) -> ClaimRecord:
        ev: list[ClaimEvidence] = []
        if source_key:
            ev.append(ClaimEvidence(source_key=source_key, passage=truncate_words(passage, 300), passage_id=passage_id))
        if extra_evidence:
            seen_keys = {source_key} if source_key else set()
            for ee in extra_evidence:
                if ee.source_key and ee.source_key not in seen_keys:
                    seen_keys.add(ee.source_key)
                    ev.append(ee)
        record = ClaimRecord(
            claim_id=f"c{len(claims) + 1}",
            claim_type=claim_type,
            claim_text=truncate_words(text, 240),
            status=status,
            reason=reason,
            evidence=ev,
            cited_source_supported=cited_source_supported,
        )
        claims.append(record)
        return record

    @staticmethod
    def _excerpt(doc: _Doc | None, pos: int | None = None) -> str:
        if doc is None:
            return ""
        if pos is None or pos < 0:
            return doc.text[:300]
        return doc.text[max(0, pos - 140): pos + 160]

    @classmethod
    def _assertive_text(cls, sentence: str) -> str | None:
        """The sentence minus clauses that only state uncertainty; None when nothing checkable remains."""
        if _DISCLOSED_GAP_RE.search(sentence) and not _CITED_KEY_RE.search(sentence):
            # "… (established background), but the value was not present in the retrieved evidence": the answer
            # discloses what the evidence lacks or labels background knowledge as the rules require. Not a finding.
            return None
        if _PROPOSAL_PATTERN.search(sentence) and not cls._claim_metrics(sentence) and not _CITED_KEY_RE.search(sentence):
            return None  # a proposed step or recommendation ("the pipeline would…", "Query X for…"), not a finding
        if not _UNCERTAINTY_PATTERN.search(sentence):
            return sentence
        clauses = re.split(
            r";|,\s*(?=(?:although|but|while|whereas|however|though)\b)|\s(?=(?:although|whereas|though)\b)", sentence
        )
        kept = [c.strip() for c in clauses if c.strip() and not _UNCERTAINTY_PATTERN.search(c)]
        if not kept:
            return None
        joined = " ".join(kept)
        if cls._claim_metrics(joined) or _ABSENCE_PATTERN.search(joined) or _EMPIRICAL_CUE_RE.search(joined):
            return joined
        return None

    @classmethod
    def _classify_claim(cls, text: str, from_table: bool = False) -> str | None:
        """absence | empirical (a figure from a cited source, a measurement, a named source or a record id) |
        cited (a statement attributed to a cited source) | None (nothing to check here)."""
        if _ABSENCE_PATTERN.search(text):
            return "absence"
        cited = bool(_CITED_KEY_RE.search(text))
        figures = bool(cls._claim_metrics(text)) or (from_table and bool(bare_numbers(text)))
        if figures and (cited or _EMPIRICAL_CUE_RE.search(text) or claim_id_tokens(text) or names_a_source(text)):
            return "empirical"
        if cited and len(re.findall(r"[A-Za-z]{3,}", _CITED_KEY_RE.sub(" ", text))) >= 5:
            return "cited"
        return None

    @staticmethod
    def _cited_keys(text: str) -> set[str]:
        return cited_keys(text)

    @staticmethod
    def _derived(text: str, start: int) -> bool:
        """The figure at `start` ends a derivation ("T = 2π√(L/g) = 2.006 s"): the answer computed it, the source
        did not state it."""
        before = text[max(0, start - 120):start]
        eq = re.search(r"[=≈]\s*$", before)
        if not eq:
            return False
        lead = re.split(r"[,;:]\s|\.\s", before[: eq.start()])[-1]
        return bool(re.search(r"[√/*^()π×]|\\[a-z]+|[=≈]", lead))

    @classmethod
    def _claim_metrics(cls, text: str) -> list[_Metric]:
        """Quantitative figures in a claim: values with units (and percentages), confidence intervals, p-values.
        Panel labels ("Fig. 2 C") and the results of the answer's own derivations are not figures from a source."""
        t = attach_units(_fold_thousands(text))
        t = _ROW_ID_RE.sub(lambda m: " " * len(m.group(0)), t)
        out: list[_Metric] = []
        ci_spans: list[tuple[int, int]] = []
        for m in _CI_RE.finditer(t):
            ci_spans.append(m.span())
            out.append(_Metric("ci", float(m.group(1)), "", m.group(1)))
            out.append(_Metric("ci", float(m.group(2)), "", m.group(2)))
        for m in _P_RE.finditer(t):
            out.append(_Metric("p", _p_value(m.group(2)), m.group(1), m.group(0).strip()))
        for m in _QTY_RE.finditer(t):
            if any(s <= m.start() < e for s, e in ci_spans):
                continue
            if re.match(r"\s*(?:ci\b|confidence)", t[m.end(): m.end() + 20], re.IGNORECASE):
                continue  # "95% CI" is a confidence level, not a result
            if _LABEL_BEFORE_RE.search(t[max(0, m.start() - 14):m.start()]) or cls._derived(t, m.start()):
                continue
            parts = number_parts(m.group(1))
            if parts is None:
                continue
            unit, scale = unit_key(m.group(2))
            out.append(_Metric("qty", parts[0], unit, m.group(0).strip(), scale, parts[1]))
        return out

    @classmethod
    def _matches_number(cls, claim_val: float, claim_label: str, doc_val: float, is_pct: bool = False) -> bool:
        if claim_val == doc_val or abs(claim_val - doc_val) <= 1e-9:
            return True
        if (claim_val < 0) != (doc_val < 0) and not is_pct:
            return False
        val_str = f"{claim_val:g}"
        val_m = re.search(rf"\b{re.escape(val_str)}(?:\.(\d+))?\b", str(claim_label or ""))
        if val_m and val_m.group(1):
            d = len(val_m.group(1))
        elif "." in val_str:
            d = len(val_str.split(".")[1])
        else:
            num_m = re.search(r"\d+\.(\d+)", str(claim_label or ""))
            d = len(num_m.group(1)) if num_m else 0
        if round(doc_val, d) == claim_val or abs(doc_val - claim_val) <= 0.55 * (10 ** -d):
            return True
        doc_str = str(doc_val)
        doc_d = len(doc_str.split(".")[1]) if "." in doc_str else 0
        if round(claim_val, doc_d) == doc_val:
            return True
        if is_pct and 0.0 < abs(doc_val) <= 1.0:
            pct_doc = doc_val * 100.0
            if round(pct_doc, d) == claim_val or abs(pct_doc - claim_val) <= 0.55 * (10 ** -d):
                return True
        return False

    @classmethod
    def _matches_metric_value(cls, metric: _Metric, doc_val: float, dm: Any, doc_text: str) -> bool:
        if metric.kind != "p":
            return cls._matches_number(metric.value, metric.label, doc_val)
        claim_op = metric.unit or "="
        pre_window = doc_text[max(0, dm.start() - 60): dm.start()]
        op_m = re.search(r"\bp\s*(?:-?\s*value)?\s*([<>=≤≥]|<=|>=)?\s*$", pre_window, re.IGNORECASE)
        doc_op = op_m.group(1) if op_m and op_m.group(1) else "="
        if claim_op in ("<", "<=", "≤"):
            if doc_op in ("<", "<=", "≤", "=", "=="):
                return doc_val <= metric.value or cls._matches_number(metric.value, metric.label, doc_val)
            return False
        if claim_op in (">", ">=", "≥"):
            if doc_op in (">", ">=", "≥", "=", "=="):
                return doc_val >= metric.value or cls._matches_number(metric.value, metric.label, doc_val)
            return False
        return cls._matches_number(metric.value, metric.label, doc_val)

    @staticmethod
    def _unit_in_window(metric: _Metric, window: str) -> bool:
        raw_unit = metric.label.split(None, 1)[1] if " " in metric.label else re.sub(r"^[\d.+\-−eE×x^{}()\s]+", "", metric.label)
        names = {metric.unit, raw_unit.lower().strip()} | {w for w, (k, _s) in _UNIT_WORD_KEYS.items() if k == metric.unit}
        return any(n and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", window) for n in names)

    @classmethod
    def _qty_in_doc(cls, metric: _Metric, doc_text: str, structured: bool) -> bool:
        """The value appears in the document with the same unit (SI prefixes converted where unambiguous). Structured
        records keep value and unit in separate fields, so there the value only needs its unit nearby."""
        target, target_ulp = metric.value * metric.scale, metric.ulp * metric.scale
        for dm in _QTY_RE_CI.finditer(doc_text):
            unit, scale = unit_key(dm.group(2))
            if unit != metric.unit:
                continue
            parts = number_parts(dm.group(1))
            if parts and _values_match(target, target_ulp, parts[0] * scale, parts[1] * scale):
                return True
        if metric.unit == "%":
            # A proportion given as a fraction ("an efficiency of 0.42").
            for dm in _DOC_NUMBER_RE.finditer(doc_text):
                v = float(dm.group(1))
                if not dm.group(2) and not dm.group(3) and 0.0 < abs(v) <= 1.0 and _values_match(metric.value, metric.ulp, v * 100.0, 0.0):
                    return True
        if structured:
            for dm in _DOC_NUMBER_RE.finditer(doc_text):
                parts = number_parts(dm.group(0))
                if parts is None or not _values_match(metric.value, metric.ulp, parts[0], parts[1]):
                    continue
                if cls._unit_in_window(metric, doc_text[max(0, dm.start() - 300): dm.end() + 300]):
                    return True
        return False

    @classmethod
    def _metric_in_doc(cls, metric: _Metric, doc_text: str, structured: bool = False) -> bool:
        """The figure appears in the document: a value with its unit, or an interval bound / p-value next to its
        keyword (within a whole record window for structured tool records)."""
        if metric.kind == "qty":
            return cls._qty_in_doc(metric, doc_text, structured)
        windows = [(_METRIC_KEYWORDS, 60, 30)] + ([(_STRUCTURED_KEYWORDS, 1200, 300)] if structured else [])
        for keywords, before, after in windows:
            keyword = keywords.get(metric.kind)
            for dm in _DOC_NUMBER_RE.finditer(doc_text):
                val = _p_value(dm.group(0)) if metric.kind == "p" else float(dm.group(1))
                if not cls._matches_metric_value(metric, val, dm, doc_text):
                    continue
                if keyword is None or keyword.search(doc_text[max(0, dm.start() - before): dm.end() + after]):
                    return True
        return False

    @staticmethod
    def _polarity(text: str) -> list[tuple[str, set[str], bool, int]]:
        """(predicate group, object terms, negated, position) for each comparable predicate in the text."""
        out: list[tuple[str, set[str], bool, int]] = []
        for group, pat in _PREDICATE_GROUPS:
            for m in pat.finditer(text):
                before = text[max(0, m.start() - 60): m.start()]
                brk = list(re.finditer(r"[;,.]|\b(?:but|whereas|while|however|although)\b", before, re.IGNORECASE))
                if brk:
                    before = before[brk[-1].end():]
                negated = bool(_NEGATOR.search(" ".join(before.split()[-6:])))
                after = text[m.end(): m.end() + 90]
                stop = re.search(r"[;,.]|\b(?:but|whereas|while|however|although)\b", after, re.IGNORECASE)
                if stop:
                    after = after[: stop.start()]
                words = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", after.lower())[:8]
                objects = {
                    _fold(w) for w in words
                    if w not in _FUNCTION_WORDS and w not in {"compared", "versus", "than", "case", "cases", "sample", "samples", "group"}
                }
                if objects:
                    out.append((group, objects, negated, m.start()))
        return out

    @classmethod
    def _polarity_conflict(
        cls, claim_polarity: list[tuple[str, set[str], bool, int]], doc_text: str
    ) -> tuple[str, int] | None:
        """(reason, position in doc) when the document states the opposite of a claim predicate and never the same."""
        if not claim_polarity:
            return None
        doc_polarity = cls._polarity(doc_text)
        for group, objects, negated, _ in claim_polarity:
            same = False
            opposite: int | None = None
            for d_group, d_objects, d_negated, d_pos in doc_polarity:
                if d_group != group or not (objects & d_objects):
                    continue
                if d_negated == negated:
                    same = True
                elif opposite is None:
                    opposite = d_pos
            if opposite is not None and not same:
                what = " ".join(sorted(objects)[:4])
                if negated:
                    return f"the source reports a positive '{group}' finding for {what}, which the claim denies", opposite
                return f"the source states that '{group}' did not hold for {what} (opposite negation)", opposite
        return None

    def _empirical_verdict(
        self, text: str, cited: set[str], docs: list[_Doc], table: bool = False, split: bool = True
    ) -> tuple[str, str, _Doc | None]:
        """(status, reason, supporting document) for a claim reporting figures. A supporting document must contain
        every record identifier the claim states, every figure with the same unit, share at least
        MIN_SHARED_CLAIM_TERMS distinctive terms with the claim, and must not state the opposite."""
        if not docs:
            return "unsupported", "no literature passages or tool outputs were retrieved", None
        parts = [p.strip() for p in re.split(r";\s+", text) if p.strip()]
        if table and split and len(parts) > 1:
            # A comparison-table row can join cells from different sources (a measured value from a paper, a reference
            # value from Physis). The whole row is checked first; only when no single source backs it is each cell
            # with a figure or identifier checked on its own, carrying the row subject.
            whole = self._empirical_verdict(text, cited, docs, table=True, split=False)
            if whole[0] == "supported":
                return whole
            subject = text.split(" — ", 1)[0] if " — " in text else ""
            results = []
            for i, part in enumerate(parts):
                cell = part if i == 0 or not subject or part.startswith(subject) else f"{subject} — {part}"
                if self._claim_metrics(cell) or claim_id_tokens(cell) or bare_numbers(cell):
                    results.append(self._empirical_verdict(cell, cited, docs, table=True, split=False))
            if results and all(r[0] == "supported" for r in results):
                return results[0]
            return whole
        if len(parts) > 1 and sum(1 for p in parts if claim_id_tokens(p)) > 1:
            # One row about several records ("Si mp-149, 1.1 eV; Ge mp-32, 0.67 eV"): each part must be backed by its
            # own record. The record-free lead-in goes with the first part.
            results = [self._empirical_verdict(p, cited, docs, table) for p in parts if claim_id_tokens(p)]
            bad = next((r for r in results if r[0] != "supported"), None)
            return bad if bad is not None else results[0]
        s_lower = _fold_thousands(text.lower())
        metrics = self._claim_metrics(text)
        # A table-derived claim's figures are bare numbers ("0.571 (0.421-0.774)"): each must appear in the doc.
        bare = bare_numbers(_fold_thousands(text)) if table else []
        terms = {_fold(t) for t in self._salient_terms(re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", _CITED_KEY_RE.sub(" ", s_lower)))}
        if not terms and not metrics and not bare:
            return "not_checked", "the claim has no distinctive terms or figures to check against the evidence", None
        needed = min(self.MIN_SHARED_CLAIM_TERMS, len(terms))
        polarity = self._polarity(s_lower)
        # Documents the claim cites come first.
        ordered = [d for d in docs if _cites(d, cited)] + [d for d in docs if not _cites(d, cited)] if cited else list(docs)
        ordered = prefer_named_sources(text, ordered)
        ordered, ineligible_reason = self._eligible_docs(text, ordered)
        if not ordered:
            return "unsupported", ineligible_reason, None

        # The reason names the closest miss: a document with the identifiers but not the figures beats one without them.
        best_reason, best_rank = "no passage or record shares the claim's subject", 0
        contradiction: tuple[_Doc, str] | None = None
        id_tokens = claim_id_tokens(text)
        if len(id_tokens) > 1 and not any(all(t in re.sub(r"\s+", "", d.text) for t in id_tokens) for d in ordered):
            # "silicon (mp-149) and germanium (mp-32)": each id sits in its own record. Supported when every
            # identifier is in a record that also shares a term with the claim (the material).
            backing: list[_Doc] = []
            for tok in id_tokens:
                # The words just before the identifier name its subject ("germanium (mp-32)").
                at = s_lower.find(tok)
                near = {_fold(t) for t in self._salient_terms(s_lower[max(0, at - 70):at + 10])} - _ID_GENERIC_TERMS
                if not near:
                    break
                hit = next((d for d in ordered if tok in re.sub(r"\s+", "", d.text) and near & _tokens(d.text)), None)
                if hit is None:
                    break
                backing.append(hit)
            if len(backing) == len(id_tokens) and len({d.text for d in backing}) > 1:
                return "supported", "", backing[0]
        for doc in ordered:
            doc_text = attach_units(_fold_thousands(doc.text))
            if id_tokens and not all(t in re.sub(r"\s+", "", doc_text) for t in id_tokens):
                # "mp-149 has a band gap of 0.61 eV" is about one record: never support it from another material's.
                if best_rank == 0:
                    best_reason = f"record identifier(s) {', '.join(id_tokens)} not found in the evidence"
                continue
            # Each record identifier the claim states and this record contains counts as a shared term; identifiers
            # only add to a shared term (the subject): another record with the same numbers never counts.
            shared = len(terms & _tokens(doc_text))
            if (id_tokens and terms and shared == 0) or shared + len(id_tokens) < needed:
                continue
            conflict = self._polarity_conflict(polarity, doc_text)
            if conflict is not None:
                if contradiction is None:
                    contradiction = (doc, conflict[0])
                continue
            structured = not _is_literature_key(doc.key)
            missing = [m for m in metrics if not self._metric_in_doc(m, doc_text, structured)]
            if bare:
                doc_numbers = {float(dm.group(1)) for dm in _DOC_NUMBER_RE.finditer(doc_text) if not dm.group(2) and not dm.group(3)}
                listed = {m.value for m in metrics}
                missing += [
                    _Metric("num", v, "", f"{v:g}") for v in bare
                    if not any(self._matches_number(v, f"{v:g}", dn) for dn in doc_numbers)
                    and not any(self._matches_number(v, f"{v:g}", lv) for lv in listed)
                ]
            if missing:
                labels = ", ".join(dict.fromkeys(m.label for m in missing))
                if best_rank < 3:
                    best_reason = (
                        f"reported figure(s) {labels} not found with the same unit in a passage or record "
                        "discussing the same subject"
                    )
                    best_rank = 2
                continue
            return "supported", "", doc
        if contradiction is not None:
            return "contradicted", contradiction[1], contradiction[0]
        return "unsupported", best_reason, None

    @staticmethod
    def _eligible_docs(text: str, docs: list[_Doc]) -> tuple[list[_Doc], str]:
        """(documents that may support this claim, reason when none may). A claim that a value was measured cannot
        rest on a simulation or a symbolic computation: those outputs are predictions, not observations."""
        if is_experimental_claim(text):
            return (
                [d for d in docs if not is_computational_doc(d)],
                "no experimental source (literature, reference data or an attached dataset) in the evidence; "
                "simulation and computation outputs are predictions, not measurements",
            )
        return list(docs), ""

    def _cited_verdict(self, text: str, cited: set[str], docs: list[_Doc]) -> tuple[str, str, _Doc | None]:
        cited_docs = [d for d in docs if _cites(d, cited)] or _tool_docs_naming(cited, docs)
        if not cited_docs:
            return "not_checked", "the cited source's text was not retrieved in this run", None
        s_lower = text.lower()
        terms = {_fold(t) for t in self._salient_terms(_CITED_KEY_RE.sub(" ", s_lower))}
        needed = min(self.MIN_SHARED_CLAIM_TERMS, len(terms))
        polarity = self._polarity(s_lower)
        contradiction: tuple[_Doc, str] | None = None
        for doc in cited_docs:
            conflict = self._polarity_conflict(polarity, doc.text)
            if conflict is not None:
                contradiction = contradiction or (doc, conflict[0])
                continue
            if len(terms & _tokens(doc.text)) >= needed:
                return "supported", "", doc
        if contradiction is not None:
            return "contradicted", contradiction[1], contradiction[0]
        return "unsupported", "the cited passage does not discuss the claim's key terms", cited_docs[0]

    @staticmethod
    def _absence_hit(words: list[str], doc_text: str) -> tuple[str, int] | None:
        """(sentence, position) of the first doc sentence holding every word that is not itself negated or
        hedged ("the origin of X remains unknown" does not show that the source discusses X)."""
        folded = [_fold(w) for w in words]
        for s, e in sentence_spans(doc_text):
            sentence = doc_text[s:e]
            toks = _tokens(sentence)
            if all(w in toks for w in folded) and not _PASSAGE_NEGATION_RE.search(sentence):
                return sentence.strip(), s
        return None

    def _absence_verdict(
        self, text: str, cited: set[str], lit_docs: list[_Doc], docs: list[_Doc]
    ) -> tuple[str, str, _Doc | None, int | None]:
        m = _ABSENCE_PATTERN.search(text)
        if m is None:
            return "not_checked", "no absence statement found", None, None
        verb = next((g for g in m.groups() if g), "")
        literature_wide = m.group("v7") is not None
        obj_text = text[m.end(): m.end() + 120]
        stop = re.search(r"[.;:()\[,]|\b(?:but|and|although|while|whereas|because|since)\b", obj_text, re.IGNORECASE)
        if stop:
            obj_text = obj_text[: stop.start()]
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", obj_text.lower()) if w not in _FUNCTION_WORDS][:6]
        referent = bool(_LITERATURE_REFERENT.search(text))
        wide_reason = "a literature-wide absence cannot be established from one search; say that it was not retrieved in this run"

        if cited:
            targets = [d for d in docs if _cites(d, cited)]
        elif referent or literature_wide:
            targets = list(lit_docs)
        else:
            targets = lit_docs if len({d.key for d in lit_docs}) == 1 else []
        if not targets:
            if literature_wide:
                return "unsupported", wide_reason, None, None
            if cited:
                return "not_checked", "the cited source's text was not retrieved in this run", None, None
            return "not_checked", "no retrieved passage identifies the source this statement is about", None, None

        informative = [d for d in targets if "method" not in d.section.lower()]
        if _MECHANISM_OBJECT.search(obj_text):
            for d in informative:
                found = list(_MECHANISM_CUES.finditer(d.text))
                cues = list(dict.fromkeys(c.group(0).lower().split()[0] for c in found))
                if len(cues) >= 2:
                    return "contradicted", f"the retrieved passage describes a mechanism ({', '.join(cues[:4])})", d, found[0].start()
        elif words:
            scattered: _Doc | None = None
            for d in targets:
                toks = _tokens(d.text)
                if not all(_fold(w) in toks for w in words):
                    continue
                hit = self._absence_hit(words, d.text)
                if hit is None:
                    # The words occur, but never together in one plain (un-negated, un-hedged) sentence.
                    scattered = scattered or d
                    continue
                sentence, pos = hit
                quote = truncate_words(sentence, 180)
                if _MENTION_VERBS.match(verb or "") or literature_wide:
                    return "contradicted", f'the retrieved passage says: "{quote}"', d, pos
                return "unsupported", f'the retrieved passage discusses it: "{quote}"', d, pos
            if scattered is not None:
                return (
                    "not_checked",
                    "the retrieved passage uses these words, but not together in one plain statement, so the absence "
                    "can be neither confirmed nor refuted",
                    scattered,
                    None,
                )
        if literature_wide:
            return "unsupported", wide_reason, targets[0], None
        if not informative:
            return (
                "unsupported",
                "only a Methods excerpt of the source was retrieved, so an article-wide absence cannot be established",
                targets[0],
                None,
            )
        if referent or _SCOPED_ABSENCE.search(text):
            return "supported", "not present in the retrieved text", targets[0], None
        return (
            "unsupported",
            "absence asserted for the whole source from a retrieved excerpt; state that it was not found in the retrieved text",
            targets[0],
            None,
        )

    def _operational_claim(self, claims: list[ClaimRecord], text: str, events: list[tuple[str, str]]) -> None:
        """Record a sentence about the run (a lookup failed, a record was not retrieved) against the run's tool
        outcomes: supported by the matching failed or empty tool call (evidence key "trace:<tool>"), else not checked.
        It never takes a scientific citation as support and never enters the citation map."""
        low = text.lower()
        ids = {g.lower() for m in _CITED_KEY_RE.finditer(text) for g in m.groups() if g}
        terms = {_fold(t) for t in self._salient_terms(_CITED_KEY_RE.sub(" ", low))} - {"search", "retriev", "fail", "run"}
        for name, event in events:
            if (ids and any(i in event for i in ids)) or (not ids and terms & _tokens(event)):
                self._add_claim(claims, "operational", text, "supported", "operational status: matches this run's tool outcome",
                                f"trace:{name}", event)
                return
        self._add_claim(
            claims, "operational", text, "not_checked",
            "operational status: a statement about this run, not a scientific claim; no matching tool outcome was recorded",
        )

    def _audit_claims(
        self,
        response: str,
        docs: list[_Doc],
        claims: list[ClaimRecord],
        judge: Callable[[str, list[dict[str, str]]], dict[str, Any] | None] | None = None,
        tool_events: list[tuple[str, str]] | None = None,
    ) -> tuple[list[DefectItem], list[dict[str, Any]]]:
        """Classify, check and record each material claim; return (defects, claim_support)."""
        defects: list[DefectItem] = []
        support: list[dict[str, Any]] = []
        lit_docs = [d for d in docs if _is_literature_key(d.key)]
        # Figure checks may read a whole article (its passages joined), not only one passage of it.
        figure_docs = docs + article_unions(docs)
        judge_calls = 0
        for sentence, unit_text, from_table in markdown_claim_units(response):
            plain = unescape_entities(unit_text)
            if _SOURCE_LOCATION_RE.match(plain):
                # "Source: abstract of arXiv:X; URL: ..." says where evidence is, it asserts nothing; its identifiers
                # are still checked by the identifier audit.
                continue
            if is_operational_claim(plain):
                # Before the hedge filter: "could not be retrieved" reports the run, it is not a hedge.
                self._operational_claim(claims, plain.strip(), tool_events or [])
                continue
            text = self._assertive_text(plain)
            if text is None:
                continue
            kind = self._classify_claim(text, from_table)
            if kind is None:
                continue
            cited = self._cited_keys(sentence) | self._cited_keys(text)
            pos: int | None = None
            if kind == "absence":
                status, reason, doc, pos = self._absence_verdict(text, cited, lit_docs, docs)
            elif kind == "empirical":
                status, reason, doc = self._empirical_verdict(text, cited, figure_docs, table=from_table)
            else:
                status, reason, doc = self._cited_verdict(text, cited, docs)

            judgeable = status == "supported" or (kind == "cited" and status == "unsupported")
            if judge is not None and judge_calls < MAX_JUDGE_CALLS and judgeable:
                passages = [doc] if doc is not None else [d for d in docs if _cites(d, cited)][:3]
                if passages:
                    judge_calls += 1
                    try:
                        verdict = judge(text, [{"source_key": d.key, "passage": judge_window(d.text, text)} for d in passages]) or {}
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Entailment judge failed: %s", exc)
                        verdict = {}
                    j_status = str(verdict.get("status") or "")
                    j_reason = str(verdict.get("reason") or "")
                    # Figures and identifiers already matched exactly in the record: an inconclusive judge (it reads a
                    # window of a long record) does not overturn that; a contradiction only lowers it to unsupported.
                    figures_matched = status == "supported" and kind == "empirical" and (
                        bool(self._claim_metrics(text)) or bool(claim_id_tokens(text)) or (from_table and bool(bare_numbers(text)))
                    )
                    relation_error = judge_relation_error(verdict) if j_status in ("unsupported", "contradicted") else None
                    if relation_error and figures_matched:
                        # The numbers occur in the record, but the judge names which case or condition they belong
                        # to: matching numbers do not establish which parameter, regime or case owns them.
                        status, reason = "unsupported", f"{RELATION_MISMATCH_PREFIX} semantic check: {relation_error}"
                    elif j_status == "contradicted" and figures_matched:
                        status, reason = "unsupported", f"semantic check disagrees although the figures match: {j_reason}"
                    elif j_status == "contradicted":
                        status, reason = "contradicted", f"semantic check: {j_reason or 'the passage contradicts the claim'}"
                    elif j_status == "unsupported" and status == "supported" and not figures_matched:
                        status, reason = "unsupported", f"semantic check: {j_reason or 'the passage does not entail the claim'}"
                    elif j_status == "supported" and kind == "cited" and status == "unsupported":
                        status, reason = "supported", f"semantic check: {j_reason}" if j_reason else "semantic check"

            extra_docs: list[_Doc] = []
            if from_table and status == "supported":
                parts = [p.strip() for p in re.split(r";\s+", text) if p.strip()]
                if len(parts) > 1:
                    subject = text.split(" — ", 1)[0] if " — " in text else ""
                    for part in parts:
                        cell = part if not subject or part.startswith(subject) else f"{subject} — {part}"
                        if self._claim_metrics(cell) or claim_id_tokens(cell) or bare_numbers(cell):
                            st, _, cd = self._empirical_verdict(cell, cited, figure_docs, table=True, split=False)
                            if st == "supported" and cd is not None and cd not in extra_docs:
                                if doc is None or cd.key != doc.key:
                                    extra_docs.append(cd)

            # A claim citing a retrieved paper that is backed only by another document: true elsewhere, but the
            # attached citation does not support it. Recorded, never silently re-attributed.
            cited_ok: bool | None = None
            cited_mismatch: str | None = None
            if kind == "empirical" and status == "supported" and doc is not None and any(_cites(d, cited) for d in docs):
                cited_ok = _cites(doc, cited) or any(_cites(ed, cited) for ed in extra_docs)
                if not cited_ok:
                    cited_mismatch = f"supported by {doc.key}, not by the cited {', '.join(sorted(cited))}"
                    reason = "; ".join(r for r in (reason, cited_mismatch) if r)

            excerpt = self._excerpt(doc, pos)
            extra_evidence = [
                ClaimEvidence(source_key=_cited_key_of(ed, cited), passage=truncate_words(self._excerpt(ed), 300), passage_id=ed.passage_id)
                for ed in extra_docs
            ] if extra_docs else None
            self._add_claim(
                claims, kind, text, status, reason, _cited_key_of(doc, cited) if doc else None, excerpt,
                doc.passage_id if doc else None, extra_evidence=extra_evidence, cited_source_supported=cited_ok
            )
            claim = truncate_words(text, 240)
            if status == "supported":
                if cited_mismatch:
                    defects.append(
                        DefectItem(
                            category="CITATION_MISMATCH",
                            severity=DefectSeverity.MINOR,
                            description=f"The cited source does not support this claim; it is {cited_mismatch}.",
                            suggested_correction=f"Cite {doc.key if doc else 'the supporting source'} for this statement, or remove the citation that does not support it.",
                            claim=claim,
                            sentence=sentence,
                        )
                    )
                # claim_support keeps the raw answer sentence (cut at 240 chars) so the citation map can match it.
                # Cited statements grounded in their own cited source count too (the citation chip's highlight).
                if kind == "empirical" or (kind == "cited" and doc is not None and _cites(doc, cited)):
                    if doc is not None:
                        support.append({"sentence": sentence[:240], "evidence_key": _cited_key_of(doc, cited), "passage_id": doc.passage_id})
                    for ed in extra_docs:
                        support.append({"sentence": sentence[:240], "evidence_key": _cited_key_of(ed, cited), "passage_id": ed.passage_id})
            elif status == "contradicted":
                source = doc.key if doc is not None else "the retrieved evidence"
                defects.append(
                    DefectItem(
                        category="CLAIM_CONTRADICTED",
                        severity=DefectSeverity.CRITICAL,
                        description=f'Claim is contradicted by {source}: {reason}. Source excerpt: "{truncate_words(excerpt, 220)}"',
                        suggested_correction="Correct the statement so it matches what the cited source says, or remove it.",
                        claim=claim,
                        sentence=sentence,
                    )
                )
            elif status == "unsupported" and kind == "empirical" and reason.startswith(RELATION_MISMATCH_PREFIX):
                defects.append(
                    DefectItem(
                        category="NUMERIC_RELATION_MISMATCH",
                        severity=DefectSeverity.MAJOR,
                        description=f"The figures occur in the source but belong to another case or condition ({reason[len(RELATION_MISMATCH_PREFIX):].strip()}).",
                        suggested_correction=(
                            "Give each figure with the parameter values, regime, conditions and unit the source assigns "
                            "it to, or mark the requested case's value as unavailable."
                        ),
                        claim=claim,
                        sentence=sentence,
                    )
                )
            elif status == "unsupported" and kind == "empirical":
                defects.append(
                    DefectItem(
                        category="UNSUPPORTED_CLAIM",
                        # A figure attributed to a cited source that does not show it is a fabrication risk; an uncited
                        # measurement not found in this run's evidence is a gap to disclose.
                        severity=DefectSeverity.CRITICAL if cited else DefectSeverity.MINOR,
                        description=f"Quantitative claim is not supported by any retrieved passage or tool output ({reason}).",
                        suggested_correction=(
                            "Restate the figure exactly as a retrieved source gives it, with its unit and citation; "
                            "otherwise remove it or mark it as established background not checked in this run."
                        ),
                        claim=claim,
                        sentence=sentence,
                    )
                )
            elif status == "unsupported" and kind == "absence":
                defects.append(
                    DefectItem(
                        category="ABSENCE_OVERREACH",
                        severity=DefectSeverity.MINOR,
                        description=f"Absence statement is not established by the retrieved evidence ({reason}).",
                        suggested_correction="Say that it was not found in the retrieved text of this run instead of asserting that the source or the literature lacks it.",
                        claim=claim,
                        sentence=sentence,
                    )
                )
            elif status == "unsupported":
                defects.append(
                    DefectItem(
                        category="CLAIM_SUPPORT",
                        severity=DefectSeverity.MINOR,
                        description=f"Statement attributed to a cited source is not supported by its retrieved passage ({reason}).",
                        suggested_correction="Restate the finding as the cited passage reports it, or qualify it as not confirmed by the retrieved text.",
                        claim=claim,
                        sentence=sentence,
                    )
                )
        return defects, support
