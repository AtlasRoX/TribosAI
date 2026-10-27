"""
Query parsing and source routing for the orchestrator.

Three layers build the QueryContext:
1. Deterministic parsing: intents, BIOMD accession, duration, papers-only suppression, typed dataset path,
   variant mentions and candidate gene, drug and disease mentions.
2. Live normalization through the registry tool 'synapta_resolve_entities' under one latency budget. When the
   tool is missing, fails or times out, the offline lexicon is used instead (normalization 'offline_lexicon').
3. An optional model-assisted planner (TRIBOS_PLANNER=off|auto|always, default auto: only when nothing was
   recognised). It may add enum intents and mentions that occur verbatim in the question, never identifiers.
4. Scope (research|conversational|unclear): anything concrete in the question makes it research; otherwise the
   planner model's verdict, else a conservative offline heuristic. Only research runs any source.

Hard guards no planner overrides: suppress_simulation, a dataset path must be typed in the question,
attachments decide Lumicell/Vivarix, and a BIOMD accession plus simulation intent skips Synapta.
The resolver result never enters tool_results.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import math
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel

from .entity_lexicon import (
    ENGLISH_WORD_SYMBOLS,
    NON_GENE_ACRONYMS,
    defined_acronyms,
    family_members,
    find_offline_concepts,
    find_offline_constants,
    find_offline_equations,
    find_offline_materials,
    find_offline_quantities,
    find_offline_systems,
    is_gene_mention,
    lookup_symbol,
)
from .evidence_need import assess_evidence_need
from .query_context import (
    SIM_DURATION_MAX_SECONDS,
    SIM_DURATION_MIN_SECONDS,
    SIM_MAX_OVERRIDES,
    SIM_SCAN_MAX_POINTS,
    DatasetRef,
    EntityType,
    QueryContext,
    ResolvedEntity,
    SimulationConstraints,
    SimulationPlan,
    SourceDecision,
)
from .search_plan import QUESTION_TYPES, SearchPlan, build_search_plan, merge_llm_plan

logger = logging.getLogger(__name__)

RESOLVER_TOOL = "synapta_resolve_entities"

INTENTS = (
    "derive",
    "solve",
    "prove",
    "compute",
    "simulate",
    "design",
    "estimate",
    "explain",
    "literature",
    "data_analysis",
    "target_assessment",
    "clinical_trials",
    "simulation",
    "steady_state",
    "single_cell",
    "drug_mechanism",
    "variant_interpretation",
    "comparison",
    "safety",
)

PLANNER_LLM_TIMEOUT_S = 4.0  # how long routing waits for the planner model
# How long the literature and web searches wait (from the start of planning) for the model's search plan.
SEARCH_PLAN_WAIT_S = 6.0
MAX_TERMS, MAX_GENE_TOKENS, MAX_DRUG_CODES, MAX_RSIDS, MAX_HGVS = 120, 6, 4, 5, 3


def extract_primary_target(query: str) -> str | None:
    """Primary target/subject of the question from the offline lexicon, as a display string."""
    cands = extract_candidates(query)
    variants = parse_variants(query)
    attach_variant_genes(query, variants, cands.lexicon_genes)
    primary = choose_primary_gene(query, cands.lexicon_genes, variants)
    if primary is not None:
        return _primary_target_string(primary, variants)
    stem = _offline_stem_entities(query, procedural_spans(query))
    if stem:
        lead = next((e for e in stem if e.type in ("equation", "system", "concept", "material", "constant")), stem[0])
        return lead.label
    return None


# "papers only", "only the trials": the user restricts the turn to one kind of source (and so forbids simulation).
_ONLY_PATTERNS = [
    r"\b(?P<kind>papers?|literature|articles?|publications?|references?|citations?|trials?|studies)\s+only\b",
    r"\bonly\s+(?:the\s+)?(?P<kind>papers?|literature|articles?|publications?|references?|citations?|trials?|studies)\b",
    r"\b(?P<kind>literature|papers?)[\s\-]only\b",
]
# What a ban applies to. Bare "models" is an object only after an explicit run verb: "no good mouse models" is
# about the literature, not an instruction.
_SIM_OBJECT = (
    r"(?:simulat\w*|modell?ing|odes?|copasi|basico|kinetic\s+(?:simulat\w*|modell?ing|models?)|computations?|"
    r"computational\s+(?:analys[ie]s|work|models?|modell?ing|experiments?)|time[\s\-]*courses?|parameter\s+(?:scans?|sweeps?))"
)
_NEGATION = r"(?:do\s+not|don'?t|never|no\s+need\s+to)"
_RUN_VERB = r"(?:run|perform|execute|do|start|launch|use|carry\s+out|compute|attempt)"
# Phrases that explicitly forbid computational simulation ("papers only", "without running simulations").
NEGATIVE_SIMULATION_PATTERNS = [
    *_ONLY_PATTERNS,
    rf"\b{_NEGATION}\s+(?:simulat\w*|model)\b",
    rf"\b{_NEGATION}\s+{_RUN_VERB}\s+(?:\w+\s+){{0,3}}?(?:{_SIM_OBJECT}|models?)\b",
    rf"\b(?:without|skip(?:ping)?|avoid(?:ing)?|exclud\w+|no)\s+"
    rf"(?:(?:running|performing|doing|executing|any|the|a|new|further|more)\s+)*{_SIM_OBJECT}",
    # A ban list within one sentence: "No FDA sweep, simulation, omics or debate is needed".
    rf"\bno\s+(?:[\w\-/]+(?:,\s*|\s+(?:or|and|nor)\s+|\s+)){{1,8}}?{_SIM_OBJECT}"
    r"(?:(?:,\s*|\s+(?:or|and|nor)\s+)[\w\-/]+(?:\s+[\w\-/]+){0,2})*",
]
_ONLY_RES = [re.compile(p, re.I) for p in _ONLY_PATTERNS]
_BAN_RES = [re.compile(p, re.I) for p in NEGATIVE_SIMULATION_PATTERNS[len(_ONLY_PATTERNS):]]
# Words that turn "do not use a different model" into a ban on replacing results, not on computing them.
_REPLACEMENT_WORDS_RE = re.compile(
    r"\b(?:substitut\w*|replac\w*|invent\w*|fabricat\w*|fak(?:e|ed|ing)|swap\w*|different|another|other|default\w*|"
    r"example|synthetic|unrelated|fallback|unchanged|instead)\b",
    re.I,
)
_REPLACEMENT_RE = re.compile(
    rf"\b(?:{_NEGATION}|without)\s+(?:\w+\s+){{0,2}}?(?:substitut\w*|replac\w*|invent\w*|fabricat\w*|fak(?:e|ing)|"
    r"mak(?:e|ing)\s+up|swap\w*|fall(?:ing)?\s*back|default\w*)\b"
    rf"|\b{_NEGATION}\s+use\s+(?:[\w\-]+[\s,]+){{0,3}}?(?:different|another|other|default|example|synthetic|unrelated|fallback)\b",
    re.I,
)
_VALIDATE_PARAM_RE = re.compile(
    r"\b(?:validat\w*|verif\w*|check\w*|confirm\w*)\b[^.;!?]{0,60}\b(?:parameters?|overrides?|exists?)\b"
    r"|\bif\b[^.;!?]{0,60}\b(?:does\s*n[o']t\s+exist|not\s+exist|missing|absent|unknown|not\s+found)\b[^.;!?]{0,40}"
    r"\b(?:reject\w*|refus\w*|fail\w*|error|stop)\b",
    re.I,
)
_INVESTIGATION_SCOPE_RE = re.compile(
    r"\b(?:for\s+(?:the\s+rest\s+of\s+)?this\s+(?:investigation|thread|conversation)|from\s+now\s+on|"
    r"for\s+all\s+(?:future|subsequent|following)\s+\w+|keep\s+(?:these|the\s+(?:same|earlier|previous))\s+settings)\b",
    re.I,
)
_SINGLE_CELL_BAN_RE = re.compile(
    rf"\b(?:{_NEGATION}\s+(?:{_RUN_VERB}\s+)?|without\s+(?:running\s+|performing\s+)?|skip(?:ping)?\s+|no\s+)"
    r"(?:(?:any|the|a)\s+)?(?:\w+\s+(?:or|and|nor)\s+)?(?:simulations?\s+(?:or|and|nor)\s+)?single[\s\-]?cell",
    re.I,
)

# An explicit request to compute: a simulation verb, a model run, COPASI, or a parameter scan. Topic words alone
# ("steady state plasma concentration", "time course of tau pathology", "metabolic flux") are not requests.
_SIMULATION_INTENT_RE = re.compile(
    r"\b(?:simulat\w*|copasi|basico|parameter\s*(?:scans?|sweeps?)|"
    r"(?:run|integrate|solve|execute)\s+(?:the\s+|a\s+|an\s+|this\s+)?(?:[\w\-]+\s+){0,2}?"
    r"(?:models?|odes?|time[\s\-]*courses?)|kinetic\s+(?:simulations?|modell?ing)|"
    r"(?:compute|find|calculate|determine|solve\s+for)\s+(?:the\s+)?steady[\s\-]*states?\s+of\s+(?:the\s+)?(?:[\w\-]+\s+){0,3}?models?)\b",
    re.I,
)
BIOMODEL_ID_RE = re.compile(r"^(?:BIOMD|MODEL)\d{10}$")

BIOMODEL_TARGET_HINTS: dict[str, str] = {
    "BIOMD0000000010": "ERK2",
    "BIOMD0000000019": "HER2",
    "BIOMD0000000372": "INSULIN",
}


def _only_kind(query: str) -> str | None:
    """'papers' or 'trials' when the user restricted the turn to one kind of source."""
    for rx in _ONLY_RES:
        m = rx.search(query)
        if m:
            return "trials" if m.group("kind").lower().startswith("trial") else "papers"
    return None


# Analyses a researcher can switch off in words ("No FDA sweep, simulation, omics, hypothesis generation or debate is
# needed"). One detector serves every phase that would otherwise run them (hypothesis, debate escalation, the
# openFDA candidate sweep, omics tools); the simulation ban above stays the authority on simulation itself.
_EXCLUDABLE_MODULES: dict[str, re.Pattern[str]] = {
    "hypothesis": re.compile(r"\bhypothes(?:is|es|ize|ise)\b(?:[\s\-]+generation)?", re.I),
    "debate": re.compile(r"\b(?:multi[\s\-]?agent\s+)?(?:debates?|critics?)\b", re.I),
    "fda_sweep": re.compile(r"\b(?:open\s*fda|fda|regulatory)(?:\s+(?:sweeps?|searche?s?|lookups?|checks?|reviews?|candidates?))?\b", re.I),
    "omics": re.compile(r"\b(?:omics|multi[\s\-]?omics|gwas|gtex|depmap|transcriptom\w*|proteom\w*|expression\s+(?:atlas|profil\w+))\b", re.I),
    "simulation": re.compile(rf"{_SIM_OBJECT}", re.I),
    "single_cell": re.compile(r"\bsingle[\s\-]?cell\b|\bsc\s?rna", re.I),
}
_NEED_RE = re.compile(r"\b(?:is|are)?\s*(?:needed|required|necessary|wanted|warranted)\b|\bplease\b", re.I)
# Words that may sit between the items of an exclusion list without changing its meaning.
_LIST_FILLER_RE = re.compile(
    r"\b(?:or|and|nor|any|further|additional|extra|new|more|the|a|an|analys[ie]s|generation|step|steps|phase|work|"
    r"run|runs|tools?|is|are|needed|required|necessary|wanted|warranted|please)\b|[,/&+\s\-]",
    re.I,
)
_EXCLUSION_TRIGGERS = (
    # "No X, Y or Z is needed", "No debate."
    (re.compile(r"\bno\s+(?P<span>[^.;:?!\n]{1,200})", re.I), "no"),
    (re.compile(
        rf"\b{_NEGATION}\s+(?:run|perform|do|generate|use|include|conduct|start|launch|attempt|propose|create|produce|add|"
        r"carry\s+out|hold|trigger)\s+(?P<span>[^.;:?!\n]{1,120})", re.I), "head"),
    (re.compile(r"\b(?:without|skip(?:ping)?|exclud\w*|avoid(?:ing)?|omit(?:ting)?|no\s+need\s+(?:for|of))\s+(?P<span>[^.;:?!\n]{1,120})", re.I), "head"),
    (re.compile(r"(?P<span>[^.;:?!\n]{1,160}?)\s+(?:is|are)\s+not\s+(?:needed|required|necessary|wanted)", re.I), "tail"),
)


def _modules_in(text: str) -> set[str]:
    return {name for name, rx in _EXCLUDABLE_MODULES.items() if rx.search(text)}


def detect_excluded_modules(query: str) -> set[str]:
    """Analyses the question explicitly excludes: hypothesis, debate, fda_sweep, omics, simulation, single_cell.

    "No ..." counts only as an exclusion list ("No X, Y or Z is needed", "No debate."): a sentence such as "there is
    no evidence that this hypothesis holds" or "no FDA approval for adagrasib" names no exclusion. Verbs of refusal
    ("do not generate hypotheses", "skip the debate", "without omics") exclude what immediately follows them."""
    out: set[str] = set()
    for rx, mode in _EXCLUSION_TRIGGERS:
        for m in rx.finditer(query or ""):
            span = m.group("span")
            if mode == "no":
                need = _NEED_RE.search(span)
                items = span[: need.start()] if need else span
                rest = items
                for pattern in _EXCLUDABLE_MODULES.values():
                    rest = pattern.sub(" ", rest)
                # Only module names and list words: an exclusion list, not a sentence that happens to say "no".
                if _LIST_FILLER_RE.sub("", rest).strip() or not (need or not span[len(items):].strip()):
                    continue
                out |= _modules_in(items)
            elif mode == "head":
                out |= _modules_in(" ".join(span.split()[:5]))
            else:
                out |= _modules_in(" ".join(span.split()[-8:]))
    return out


def _simulation_ban(query: str) -> str | None:
    """The text of an operation ban ("do not run simulations"), ignoring bans on replacing results."""
    for rx in _BAN_RES:
        for m in rx.finditer(query):
            if _REPLACEMENT_WORDS_RE.search(m.group(0)):
                continue  # "do not use a different model", "do not substitute an unchanged simulation"
            return m.group(0)
    return None


# A word or phrase that puts what follows it out of scope: "without running simulations", "rather than a simulation".
_NEGATION_SCOPE_RE = re.compile(
    r"\b(?:without|rather\s+than|instead\s+of|not\s+by|other\s+than|apart\s+from|no|not|nor|neither|never)\s+"
    r"(?:[\w\-]+\s+){0,2}$",
    re.I,
)
# A negated or evaluative predicate after the mention: "running simulations does not establish ...".
_NEGATED_PREDICATE_RE = re.compile(
    r"\b(?:does|do|did|will|would|can|could|should|may|might|must|is|are|was|were)\s*(?:not\b|n't\b)"
    r"|\b(?:cannot|never|fails?\s+to|(?:is|are)\s+(?:insufficient|inadequate|irrelevant|unreliable))\b",
    re.I,
)
# A directive: an imperative at the start of the clause, or an explicit request.
_DIRECTIVE_RE = re.compile(
    r"^\W*(?:(?:please|also|then|now|first|next|finally|and|so)\W+)*"
    r"(?:simulate|run|integrate|solve|compute|calculate|determine|find|plot|perform|carry|execute|model|predict|"
    r"show|scan|sweep|use|do|make|give|provide|generate|create|estimate|evaluate|analy[sz]e|study|explore|"
    r"investigate|try|start|repeat|rerun|re-run)\b"
    r"|\b(?:please|can\s+you|could\s+you|would\s+you|will\s+you|i\s+(?:want|need|would\s+like|'d\s+like)|"
    r"we\s+(?:want|need)|help\s+me|let'?s|let\s+us)\b",
    re.I,
)
_CONDITIONAL_OPENER_RE = re.compile(r"\b(?:if|even\s+if|although|though|whether|unless|suppose|imagine)\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


def _requests_simulation(text: str) -> bool:
    """Whether the text asks for a simulation, as opposed to mentioning one.

    Each mention of a simulation term is read in its sentence. It is not a request when it sits in the scope of a
    negation ("without running simulations"), in quotation marks, inside a conditional clause ("if you simulate it,
    ..."), or in the subject of a negated predicate without a directive ("running simulations does not establish the
    claim"). Everything else, including declarative requests and fragments ("a 50 s simulation of the Lorenz
    system"), still counts, so a real request is never lost to this reading.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        for m in _SIMULATION_INTENT_RE.finditer(sentence):
            prefix, suffix = sentence[: m.start()], sentence[m.end():]
            if _NEGATION_SCOPE_RE.search(prefix):
                continue
            if prefix.count('"') % 2 == 1 or prefix.count("“") > prefix.count("”"):
                continue
            clause = re.split(r"[,;:]", prefix)[-1]
            if _CONDITIONAL_OPENER_RE.search(clause):
                continue
            if _NEGATED_PREDICATE_RE.search(suffix) and not _DIRECTIVE_RE.search(prefix + m.group(0)):
                continue
            return True
    return False


def detect_simulation_constraints(query: str) -> SimulationConstraints:
    """Scoped simulation instructions. Only a ban on running (or a papers-only restriction) forbids simulation;
    "do not substitute/invent/replace ..." forbids replacing results, and a conditional rejection requires
    validation, not abstention."""
    forbidden = _only_kind(query) is not None or _simulation_ban(query) is not None
    # "simulations" inside "do not run simulations" is not a request to simulate.
    unbanned = query
    for rx in (*_ONLY_RES, *_BAN_RES):
        unbanned = rx.sub(" ", unbanned)
    return SimulationConstraints(
        simulation_requested=bool(_requests_simulation(unbanned) or extract_biomodel_id(query)),
        simulation_forbidden=forbidden,
        replacement_forbidden=bool(_REPLACEMENT_RE.search(query)),
        reject_if_parameter_missing=bool(_VALIDATE_PARAM_RE.search(query)),
        scope="investigation" if _INVESTIGATION_SCOPE_RE.search(query) else "current_turn",
    )


def detect_simulation_suppression(query: str) -> bool:
    """Return True when the user explicitly asked not to run simulations."""
    return detect_simulation_constraints(query).simulation_forbidden


def _suppression_reason(query: str) -> str:
    kind = _only_kind(query)
    if kind is not None:
        return f"{kind} only requested"
    return "simulation excluded at your request"


def extract_dataset_path(query: str) -> str | None:
    """Extract a referenced single-cell dataset file (.h5ad / .zarr) the server is allowed to read."""
    m = re.search(r"[\w\-\./\\:]+\.(?:h5ad|zarr)\b", query, re.IGNORECASE)
    if not m:
        return None
    from tribos.datasets.paths import is_allowed_typed_path

    return m.group(0) if is_allowed_typed_path(m.group(0)) else None


_SC_TOPIC = (
    r"(?:single[\s\-]?cell|scrna(?:[\s\-]?seq)?|sc[\s\-]?rna(?:[\s\-]?seq)?|anndata|h5ad|leiden|louvain|umap|t[\s\-]?sne|"
    r"cell\s*clusters?|clusters?|clustering|marker\s*genes?|cell[\s\-]?type\s*annotation|transcriptom\w*|cells)"
)
_SC_TOPIC_RE = re.compile(rf"\b{_SC_TOPIC}\b", re.I)
# An analysis verb in the imperative/request sense, shortly before the single-cell object.
_SC_REQUEST_RE = re.compile(
    rf"\b(?:analy[sz]e|run|perform|carry\s+out|re-?cluster|cluster|annotate|normali[sz]e|compute|execute|apply)\b"
    rf"(?:\W+[\w\-]+){{0,4}}?\W+{_SC_TOPIC}\b",
    re.I,
)
# A reference to data the researcher holds: a single-cell file format, or "my/this/the uploaded ... dataset".
_SC_FILE_RE = re.compile(r"\b(?:h5ad|anndata|zarr|loom)\b", re.I)
_SC_DATASET_RE = re.compile(
    r"\b(?:my|our)\s+(?:[\w\-]+\s+){0,3}?(?:data(?:sets?)?|cells|samples?|matrix|counts?|files?|atlas)\b"
    r"|\b(?:this|the)\s+(?:uploaded|attached)\s+(?:[\w\-.]+\s+){0,2}?(?:data(?:sets?)?|files?|matrix|atlas)\b"
    r"|\b(?:uploaded|attached)\s+(?:[\w\-.]+\s+){0,2}?(?:data(?:sets?)?|files?|matrix|atlas)\b",
    re.I,
)
# Literature nouns: "what do single-cell studies report" asks about papers, not for an analysis.
_SC_LITERATURE_RE = re.compile(r"\b(?:studies|study|literature|papers?|publications?|articles?|reviews?|reports?)\b", re.I)


def has_single_cell_intent(query: str) -> bool:
    """An explicit request to analyse single-cell data (ORC-003), not a single-cell topic word.

    True for a single-cell file format (h5ad, AnnData, zarr, loom), for a single-cell topic together with a
    reference to the researcher's own data ("my dataset", "the uploaded file"), or for an analysis verb directly
    before a single-cell object ("perform single-cell clustering", "cluster the cells") in a question that is not
    about the literature. "What do single-cell transcriptomic studies report ..." and "Summarize the transcriptomic
    subtypes of ..." are literature questions."""
    text = query or ""
    if _SC_FILE_RE.search(text):
        return True
    if not _SC_TOPIC_RE.search(text):
        return False
    if _SC_DATASET_RE.search(text):
        return True
    return bool(_SC_REQUEST_RE.search(text)) and not _SC_LITERATURE_RE.search(text)


# Durations: complete, word-bounded units only ("10ms" is milliseconds, never minutes; "2 mM" is no duration).
DEFAULT_SIM_DURATION_S = 60.0
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_DURATION_PREFIX = r"\b(?:over|for|during|lasting|duration(?:\s+of|\s*[:=])?)\s*"
_DURATION_UNITS = r"milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|hr|h"
_UNSUPPORTED_UNITS = r"microseconds?|us|µs|nanoseconds?|ns|days?|d|weeks?|wks?|months?|years?|yrs?|y"
_DURATION_RE = re.compile(
    _DURATION_PREFIX + rf"(?P<value>{_NUMBER})\s*(?P<unit>{_DURATION_UNITS})(?![\w\-/])"
    rf"|(?P<value2>{_NUMBER})[\s\-]*(?P<unit2>milliseconds?|seconds?|minutes?|hours?)[\s\-]+"
    r"(?:long\s+)?(?:simulations?|time[\s\-]*courses?|runs?|integrations?)\b",
    re.I,
)
# A request for the steady state (equilibrium) itself. "Steady-state amplitude", "transient and steady-state components"
# or "the steady-state response" name part of a solution, not a request to compute an equilibrium.
_STEADY_STATE_REQUEST_RE = re.compile(
    r"\bsteady[\s\-]*states?\b(?![\s\-]*(?:amplitudes?|responses?|components?|solutions?|phases?|oscillations?|errors?|"
    r"terms?|parts?|behaviou?rs?|regimes?|periodic|motions?|vibrations?|displacements?|gains?|outputs?|values?\s+of\s+x))",
    re.I,
)
# A time span: "over 0–20 s", "from 0 to 20 s", "t ∈ [0, 20] s", "0 ≤ t ≤ 20 s". After over/for/during it must start at
# zero ("for 2–3 hours" is an approximate length, not a span); from/between/t= spans may start anywhere.
_DURATION_RANGE_RE = re.compile(
    rf"\b(?P<lead>over|for|during|from|between)\s+\[?\s*(?P<start>{_NUMBER})\s*(?:–|—|-|to|until|through|and|\.\.)\s*"
    rf"(?P<end>{_NUMBER})\s*\]?\s*(?P<unit>{_DURATION_UNITS})(?![\w\-/])"
    rf"|\bt\s*(?:=|∈|\bin\b)\s*\[?\s*(?P<start2>{_NUMBER})\s*(?:,|–|—|-|to|\.\.)\s*(?P<end2>{_NUMBER})\s*\]?\s*"
    rf"(?P<unit2>{_DURATION_UNITS})(?![\w\-/])"
    rf"|(?P<start3>{_NUMBER})\s*(?:≤|<=|<)\s*t\s*(?:≤|<=|<)\s*(?P<end3>{_NUMBER})\s*(?P<unit3>{_DURATION_UNITS})(?![\w\-/])",
    re.I,
)
_UNSUPPORTED_DURATION_RE = re.compile(_DURATION_PREFIX + rf"(?P<value>{_NUMBER})\s*(?P<unit>{_UNSUPPORTED_UNITS})(?![\w\-/])", re.I)
# A bare number after a duration word with no unit ("for 100.", "duration: 50").
_UNITLESS_DURATION_RE = re.compile(_DURATION_PREFIX + rf"(?P<value>{_NUMBER})\s*(?=$|[.,;:!?)])", re.I)
_UNIT_SECONDS = {
    "ms": 0.001, "msec": 0.001, "msecs": 0.001, "millisecond": 0.001, "milliseconds": 0.001,
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
}


class DurationParse(BaseModel):
    seconds: float = DEFAULT_SIM_DURATION_S
    explicit: bool = False
    text: str = ""
    error_code: str | None = None  # DURATION_INVALID|DURATION_UNIT_UNSUPPORTED|DURATION_CONFLICT
    message: str = ""


def parse_duration(query: str) -> DurationParse:
    """The requested simulation duration in seconds, or a typed error. Never clamps or substitutes a value."""
    unsupported = _UNSUPPORTED_DURATION_RE.search(query)
    if unsupported:
        return DurationParse(
            text=unsupported.group(0).strip(), error_code="DURATION_UNIT_UNSUPPORTED",
            message=f"'{unsupported.group(0).strip()}' uses an unsupported unit; use ms, s, min or h.",
        )
    found: list[tuple[float, str]] = []
    for m in _DURATION_RANGE_RE.finditer(query):
        for i in ("", "2", "3"):
            start, end, unit = m.group(f"start{i}"), m.group(f"end{i}"), m.group(f"unit{i}")
            if start is None:
                continue
            if i == "" and m.group("lead").lower() in ("over", "for", "during") and float(start) != 0:
                break
            try:
                seconds = (float(end) - float(start)) * _UNIT_SECONDS[unit.lower()]
            except (OverflowError, ValueError):
                seconds = float("inf")
            found.append((seconds, m.group(0).strip()))
    for m in _DURATION_RE.finditer(query):
        value, unit = (m.group("value"), m.group("unit")) if m.group("value") is not None else (m.group("value2"), m.group("unit2"))
        try:
            seconds = float(value) * _UNIT_SECONDS[unit.lower()]
        except (OverflowError, ValueError):
            seconds = float("inf")
        found.append((seconds, m.group(0).strip()))
    if not found:
        unitless = _UNITLESS_DURATION_RE.search(query)
        if unitless:
            return DurationParse(
                text=unitless.group(0).strip(), error_code="DURATION_UNIT_UNSUPPORTED",
                message=f"'{unitless.group(0).strip()}' has no time unit; specify ms, s, min or h.",
            )
        return DurationParse()
    distinct = {round(s, 9) for s, _ in found if math.isfinite(s)}
    if len(distinct) > 1:
        return DurationParse(
            text="; ".join(t for _, t in found), error_code="DURATION_CONFLICT",
            message="The question states more than one duration (" + ", ".join(t for _, t in found) + ").",
        )
    seconds, text = found[0]
    if not math.isfinite(seconds) or seconds <= 0:
        return DurationParse(
            seconds=seconds if math.isfinite(seconds) else 0.0, explicit=True, text=text, error_code="DURATION_INVALID",
            message=f"Duration '{text}' must be positive and finite.",
        )
    return DurationParse(seconds=seconds, explicit=True, text=text)


def parse_duration_seconds(query: str) -> float:
    """Simulation duration in seconds; 60 s when none is stated. Raises ValueError for an invalid duration."""
    parsed = parse_duration(query)
    if parsed.error_code:
        raise ValueError(parsed.message)
    return parsed.seconds


def extract_biomodel_id(query: str) -> str | None:
    bm_match = re.search(r"\b((?:BIOMD|MODEL)\d{10})\b", query, re.IGNORECASE)
    return bm_match.group(1).upper() if bm_match else None


# Parameter scans, overrides and requested species.
_PARAM_NAME = r"[A-Za-z_][\w\.\-\[\]]{0,63}"
_RESERVED_PARAM_NAMES = frozenset(
    "the a an of on in for model parameter parameters duration time points point values value from to and with using "
    "this that it its each all".split()
)
_SCAN_PARAM_RES = [
    re.compile(rf"\bparameter\s+(?:scan|sweep)\w*\s+(?:of|over|on|for|across)\s+(?:the\s+)?(?:parameter\s+)?['\"`]?(?P<name>{_PARAM_NAME})", re.I),
    re.compile(rf"\b(?:scan|sweep|vary|varying)\s+(?:the\s+)?(?:parameter\s+)?['\"`]?(?P<name>{_PARAM_NAME})['\"`]?\s+(?:from|between|over|across)\b", re.I),
    re.compile(rf"\b(?:scan|sweep)\w*\s+(?:of\s+)?(?:the\s+)?parameter\s+['\"`]?(?P<name>{_PARAM_NAME})", re.I),
]
_SCAN_RANGE_RE = re.compile(
    rf"\bfrom\s+(?P<a>{_NUMBER})\s*(?:to|through|-|–|until)\s*(?P<b>{_NUMBER})"
    rf"|\bbetween\s+(?P<c>{_NUMBER})\s+and\s+(?P<d>{_NUMBER})",
    re.I,
)
_SCAN_POINTS_RE = re.compile(r"\b(?P<n>\d{1,6})\s+(?:(?:evenly[\s\-]spaced|equally[\s\-]spaced|linear|log)\s+)?(?:points|values|steps|samples)\b", re.I)
_INTERVALS_RE = re.compile(r"\b(?P<n>\d{1,6})\s+(?:output\s+)?intervals\b", re.I)
_DICT_LITERAL_RE = re.compile(r"\{[^{}]{0,2000}\}")
_ASSIGN_OVERRIDE_RES = [
    re.compile(rf"\bparameter\s+['\"`]?(?P<name>{_PARAM_NAME})['\"`]?\s*(?:=|to|of)\s*(?P<value>{_NUMBER})(?![\w.])", re.I),
    re.compile(rf"\bset\s+(?:parameter\s+)?['\"`]?(?P<name>{_PARAM_NAME})['\"`]?\s+to\s+(?P<value>{_NUMBER})(?![\w.])", re.I),
]
_ALL_SPECIES_RE = re.compile(r"\b(?:all|every|each)\s+(?:(?:endpoint|final|model)\s+)?species\b|\bendpoint\s+species\b", re.I)
_SPECIES_LIST_RE = re.compile(r"\bspecies\s*(?::|=)?\s*(?P<list>[A-Za-z][\w\-]*(?:\s*(?:,|and)\s*[A-Za-z][\w\-]*){0,7})", re.I)
_MAX_LITERAL_CHARS = 2000


def _err(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def parse_parameter_overrides(query: str) -> tuple[dict[str, float], list[dict[str, str]]]:
    """Overrides from a dict literal ({'V1': 0.5}) or 'set V1 to 0.5'. Bounded ast.literal_eval, never eval;
    anything that is not a small {name: finite number} mapping is a validation error, never silently dropped."""
    overrides: dict[str, float] = {}
    errors: list[dict[str, str]] = []
    for m in _DICT_LITERAL_RE.finditer(query):
        text = m.group(0)
        if len(text) > _MAX_LITERAL_CHARS:
            errors.append(_err("OVERRIDES_INVALID", "The parameter override mapping is too long."))
            continue
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            errors.append(_err("OVERRIDES_INVALID", f"Could not read parameter overrides {text[:80]!r}; use {{'name': number}}."))
            continue
        if not isinstance(value, dict):
            errors.append(_err("OVERRIDES_INVALID", f"Parameter overrides {text[:80]!r} are not a name-to-number mapping."))
            continue
        for k, v in value.items():
            if not isinstance(k, str) or not re.fullmatch(_PARAM_NAME, k.strip()):
                errors.append(_err("OVERRIDES_INVALID", f"Parameter name {k!r} is not a valid model parameter name."))
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                errors.append(_err("OVERRIDES_INVALID", f"Value for {k!r} must be a finite number, got {v!r}."))
            else:
                overrides[k.strip()] = float(v)
    for rx in _ASSIGN_OVERRIDE_RES:
        for m in rx.finditer(query):
            name = m.group("name")
            if name.lower() in _RESERVED_PARAM_NAMES:
                continue
            try:
                val = float(m.group("value"))
            except (OverflowError, ValueError):
                val = float("inf")
            if not math.isfinite(val):
                errors.append(_err("OVERRIDES_INVALID", f"Value for {name!r} must be a finite number."))
            else:
                overrides.setdefault(name, val)
    if len(overrides) > SIM_MAX_OVERRIDES:
        errors.append(_err("OVERRIDES_INVALID", f"At most {SIM_MAX_OVERRIDES} parameter overrides are supported ({len(overrides)} given)."))
    return overrides, errors


def _scan_parameter(query: str) -> str | None:
    for rx in _SCAN_PARAM_RES:
        m = rx.search(query)
        if m and m.group("name").lower() not in _RESERVED_PARAM_NAMES and not BIOMODEL_ID_RE.match(m.group("name").upper()):
            return m.group("name").strip(".")
    return None


def _target_species(query: str) -> list[str]:
    if _ALL_SPECIES_RE.search(query):
        return ["*"]  # every species of the model
    out: list[str] = []
    for m in _SPECIES_LIST_RE.finditer(query):
        for tok in re.split(r"\s*(?:,|\band\b)\s*", m.group("list")):
            tok = tok.strip()
            # Model species are written like identifiers ("Mos-P", "Erk2-PP"), not ordinary words ("values").
            if tok and re.search(r"[A-Z0-9\-]", tok) and tok.lower() not in _RESERVED_PARAM_NAMES:
                out.append(tok)
    return list(dict.fromkeys(out))[:16]


def build_simulation_plan(query: str, *, biomodel_id: str | None, wants_steady_state: bool) -> SimulationPlan:
    """The exact simulation the user asked for. Problems become validation_errors; nothing is clamped."""
    errors: list[dict[str, str]] = []
    duration = parse_duration(query)
    if duration.error_code:
        errors.append(_err(duration.error_code, duration.message))
    elif duration.explicit and not (SIM_DURATION_MIN_SECONDS <= duration.seconds <= SIM_DURATION_MAX_SECONDS):
        errors.append(_err(
            "DURATION_OUT_OF_RANGE",
            f"Duration '{duration.text}' is {duration.seconds:g} s; the supported range is "
            f"{SIM_DURATION_MIN_SECONDS:g}-{SIM_DURATION_MAX_SECONDS:g} s.",
        ))
    overrides, override_errors = parse_parameter_overrides(query)
    errors.extend(override_errors)
    if biomodel_id is not None and not BIOMODEL_ID_RE.match(biomodel_id):
        errors.append(_err("MODEL_ID_INVALID", f"{biomodel_id} is not a BioModels accession."))
        biomodel_id = None

    intervals = 100
    im = _INTERVALS_RE.search(query)
    if im:
        intervals = int(im.group("n"))
        if not 1 <= intervals <= 10000:
            errors.append(_err("INTERVALS_OUT_OF_RANGE", f"{intervals} output intervals is outside 1-10000."))

    plan = SimulationPlan(
        action="time_course",
        biomodel_id=biomodel_id,
        duration_seconds=duration.seconds if math.isfinite(duration.seconds) else DEFAULT_SIM_DURATION_S,
        duration_explicit=duration.explicit,
        intervals=intervals,
        parameter_overrides=overrides,
        target_species=_target_species(query),
    )
    if re.search(r"\b(?:parameter\s*(?:scans?|sweeps?)|scan\s+(?:of\s+)?(?:the\s+)?parameter|sweep\s+(?:of\s+)?(?:the\s+)?parameter)\b", query, re.I):
        plan.action = "parameter_scan"
        plan.scan_parameter = _scan_parameter(query)
        if plan.scan_parameter is None:
            errors.append(_err("SCAN_INCOMPLETE", "A parameter scan needs the parameter to scan (e.g. 'parameter scan of V1')."))
        rm = _SCAN_RANGE_RE.search(query)
        if rm:
            a, b = (rm.group("a"), rm.group("b")) if rm.group("a") is not None else (rm.group("c"), rm.group("d"))
            try:
                start, end = float(a), float(b)
            except (OverflowError, ValueError):
                start = end = float("inf")
            if not (math.isfinite(start) and math.isfinite(end)) or start == end:
                errors.append(_err("SCAN_INVALID_RANGE", f"Scan range {a} to {b} must be two different finite values."))
            else:
                plan.scan_start, plan.scan_end = start, end
        pm = _SCAN_POINTS_RE.search(query)
        if pm:
            n = int(pm.group("n"))
            if n < 2:
                errors.append(_err("SCAN_INVALID_POINTS", "A scan needs at least 2 points (both endpoints)."))
            elif n > SIM_SCAN_MAX_POINTS:
                errors.append(_err("SCAN_TOO_MANY_POINTS", f"{n} scan points exceeds the limit of {SIM_SCAN_MAX_POINTS}."))
            else:
                plan.scan_points = n
    elif wants_steady_state and not re.search(r"\b(?:time[\s\-]*courses?|trajector\w*|over\s+time)\b", query, re.I):
        plan.action = "steady_state"
    plan.validation_errors = errors
    return plan


# =============================================================================
# Candidate mentions
# =============================================================================

_STOPWORDS = frozenset(
    """
    a an the of in on for with and or to by at from is are was were be been being does do did done what which who whom
    how why when where can could should would will may might must this that these those it its as vs versus than into
    about between after before during without not no any all my our their there here me i we you your please only also
    via per using use used among against toward towards whether if then so such more most less least very
    """.split()
)

# Words that describe how to run or report a request, never what it is about ("duration" is not a disease).
PROCEDURAL_WORDS = frozenset(
    """
    duration durations second seconds sec secs millisecond milliseconds ms minute minutes min mins hour hours hr hrs
    interval intervals point points step steps parameter parameters override overrides value values range ranges
    limit limits unit units result results simulate simulated simulating simulation simulations run runs running
    scan scans sweep sweeps endpoint endpoints readout readouts output outputs validate validation reject request
    substitute unchanged replace report reported paper papers literature exactly required input supported
    unsupported premise unverified invent approvals otherwise retrieve supporting state stated parsed
    """.split()
)
_PROCEDURAL_SPAN_RES = [
    _DICT_LITERAL_RE,
    _DURATION_RE,
    _UNSUPPORTED_DURATION_RE,
    _SCAN_RANGE_RE,
    re.compile(r"\b\d{1,6}\s+(?:points|values|steps|samples|intervals)\b", re.I),
]


def procedural_spans(query: str) -> list[tuple[int, int]]:
    """Spans of simulation arguments (durations, override mappings, scan ranges, the scanned or overridden
    parameter's name), excluded from entity lookup."""
    spans = [m.span() for rx in _PROCEDURAL_SPAN_RES for m in rx.finditer(query)]
    for rx in (*_SCAN_PARAM_RES, *_ASSIGN_OVERRIDE_RES):
        spans.extend(m.span("name") for m in rx.finditer(query))
    return spans


_CELL_LINES = frozenset(
    "A549 HCT116 HEK293 HEK293T H358 H1299 H460 H1975 HCC827 PC9 MCF7 U2OS K562 HL60 SW480 SW620 LNCAP VCAP "
    "PANC1 MIAPACA2 A375 SKBR3 BT474 T47D HT29 DLD1 CACO2 JURKAT THP1 COVID SARS".split()
)

# Letters in any script ("Sjogren" with an umlaut) and a possessive 's ("Alzheimer's disease"), which OpenTargets matches verbatim.
_WORD_RE = re.compile(r"[^\W_](?:(?:[^\W_]|-)*[^\W_])?(?:['\u2019]s(?![^\W_]))?")
_HYPHEN_HEAD_RE = re.compile(r"^([^\W_]{3,})-(?:induced|associated|related|mediated|treated|resistant|refractory)$", re.I)
# A trial acronym with its number followed within a few words by trial/study wording: "SOLO-1 phase 3 trial".
_TRIAL_NAME_RE = re.compile(
    r"[A-Z][A-Za-z]{2,}-?\d{1,4}[A-Z]?\b(?=[^.;]{0,40}\b(?:trial|study|cohort|phase\s*(?:\d|i{1,3}v?)))", re.IGNORECASE
)
_GENE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_\-])([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{1,4})?)(?![A-Za-z0-9_])")
_LEXICON_WORD_RE = re.compile(r"(?<![A-Za-z0-9_\-])([A-Za-z][A-Za-z0-9]{1,9}(?:-[A-Za-z0-9]{1,4})?)(?![A-Za-z0-9_])")
_CODE_RE = re.compile(r"(?<![A-Za-z0-9_\-])([A-Z]{1,5}-?\d{2,6})(?![A-Za-z0-9_])")
_ACCESSION_RE = re.compile(r"^(?:BIOMD\d+|NCT\d+|CHEMBL\d+|HGNC|MONDO|EFO|GSE\d+|GSM\d+|VCV\d+|EID\d+|PMID\d*|PMC\d+)$")
_INN_DRUG_RE = re.compile(
    r"(?<![A-Za-z0-9_\-])([A-Za-z][a-z]{2,}(?:mab|nib|rasib|parib|ciclib|lisib|zomib|platin|taxel|rubicin|tecan|"
    r"sertib|degib|vastatin|formin|glutide|limus|cept|tinib|rafenib|metinib))(?![A-Za-z0-9_])"
)


@dataclass
class Candidates:
    terms: list[str] = field(default_factory=list)
    gene_tokens: list[str] = field(default_factory=list)
    drug_codes: list[str] = field(default_factory=list)
    rsids: list[str] = field(default_factory=list)
    transcripts_hgvs: list[str] = field(default_factory=list)
    lexicon_genes: list[ResolvedEntity] = field(default_factory=list)
    offline_drugs: list[ResolvedEntity] = field(default_factory=list)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _is_variant_shaped(token: str) -> bool:
    return bool(_PROTEIN_CHANGE_RE.fullmatch(token))


def _lexicon_entity(text: str, start: int, end: int, matched_on_override: str | None = None) -> ResolvedEntity | None:
    token = text[start:end]
    if not is_gene_mention(text, start, end):
        return None
    members = family_members(token)
    if members:
        return ResolvedEntity(
            type="gene", mention=token, span=(start, end), label=token.upper(), source="local_lexicon",
            matched_on="family", ambiguous_with=list(members), validated=False,
        )
    hit = lookup_symbol(token)
    if hit is None:
        return None
    symbol, matched_on = hit
    return ResolvedEntity(
        type="gene", mention=token, span=(start, end), label=symbol, source="local_lexicon",
        matched_on=matched_on_override or matched_on, validated=False,
    )


def _ngrams(query: str) -> list[str]:
    # Typed identifiers (HGVS, rsIDs, accessions) are not names; blank them so their pieces ("NM") are not looked up.
    masked = query
    for s, e in sorted(procedural_spans(query), reverse=True):
        masked = masked[:s] + " " * (e - s) + masked[e:]
    masked = _RSID_RE.sub(" ", _HGVS_RE.sub(" ", masked))
    masked = re.sub(r"\b[A-Za-z]+_\w+|\b[A-Za-z]+:\d+\b", " ", masked)
    words = [w for w in _WORD_RE.findall(masked) if not _ACCESSION_RE.match(w.upper())]
    out: list[str] = []
    for n in (1, 2, 3, 4):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            first, last = (re.sub(r"['\u2019]s$", "", w.lower()) for w in (gram[0], gram[-1]))
            if first in _STOPWORDS or last in _STOPWORDS or gram[-1].isdigit() or gram[0].isdigit():
                continue
            if first in PROCEDURAL_WORDS or last in PROCEDURAL_WORDS:
                continue
            if n == 1 and (len(gram[0]) < 2 or re.fullmatch(r"rs\d+", first)):
                continue
            out.append(" ".join(gram))
            head = _HYPHEN_HEAD_RE.match(gram[0]) if n == 1 else None
            if head and head.group(1).lower() not in _STOPWORDS:
                out.append(head.group(1))  # "sepsis-induced", "cisplatin-resistant": the head is a name of its own
    return list(dict.fromkeys(out))[:MAX_TERMS]


def extract_candidates(query: str) -> Candidates:
    """Mentions worth resolving, plus the offline lexicon reading of the genes."""
    cands = Candidates()
    # Simulation arguments ("parameter scan of V1", "{'K1': 2}") are not gene or drug names.
    variant_spans: list[tuple[int, int]] = procedural_spans(query)
    for v in parse_variants(query):
        if v.variant_kind in ("protein_change", "hgvs", "rsid"):
            variant_spans.append(v.span)
        elif v.variant_kind == "exon_event":
            # The words after the gene ("exon 20 ins") are not names: "ins" is not INS.
            variant_spans.append((v.span[0] + v.mention.lower().find("exon"), v.span[1]))

    lexicon: list[ResolvedEntity] = []
    for m in _LEXICON_WORD_RE.finditer(query):
        token = m.group(1)
        spans: list[tuple[int, int]] = [(m.start(1), m.end(1))]
        if "-" in token and lookup_symbol(token) is None and family_members(token) is None:
            head, tail = token.split("-", 1)
            spans = [(m.start(1), m.start(1) + len(head)), (m.end(1) - len(tail), m.end(1))]
        for s, e in spans:
            if any(_overlaps((s, e), vs) for vs in variant_spans):
                continue
            ent = _lexicon_entity(query, s, e)
            if ent is not None:
                lexicon.append(ent)
    cands.lexicon_genes = lexicon

    gene_tokens: list[str] = [g.mention for g in lexicon]
    # "homologous recombination repair-deficient (HRD)": an acronym the question defines as a biomarker or
    # endpoint is not looked up as a gene (HGNC lists HRD as an alias of TBCE).
    concept_acronyms = {k for k, kind in defined_acronyms(query).items() if kind == "concept"}
    for m in _GENE_TOKEN_RE.finditer(query):
        token = m.group(1)
        if m.end(1) < len(query) and query[m.end(1)] == "_" or _CODE_RE.fullmatch(token):
            continue
        if _TRIAL_NAME_RE.match(query, m.start(1)) and lookup_symbol(token.split("-")[0]) is None:
            continue  # "SOLO-1 phase 3 trial", "KEYNOTE-716 trial": a trial's name, not a gene

        parts = [(token, m.start(1), m.end(1))]
        if "-" in token and lookup_symbol(token) is None:
            head, tail = token.split("-", 1)
            parts = [(head, m.start(1), m.start(1) + len(head)), (tail, m.end(1) - len(tail), m.end(1))]
        for tok, s, e in parts:
            key = tok.upper()
            if (
                not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", tok)
                or key in NON_GENE_ACRONYMS
                or key in concept_acronyms
                or key in _CELL_LINES
                or _ACCESSION_RE.match(key)
                or _is_variant_shaped(tok)
                or any(_overlaps((s, e), vs) for vs in variant_spans)
                or re.fullmatch(r"[IVX]+", tok)
                or (re.fullmatch(r"[A-Z]{1,5}-?\d{3,6}", tok) and lookup_symbol(tok) is None)
                or (key in ENGLISH_WORD_SYMBOLS and not is_gene_mention(query, s, e))
            ):
                continue
            gene_tokens.append(tok)
    cands.gene_tokens = list(dict.fromkeys(gene_tokens))[:MAX_GENE_TOKENS]

    codes = []
    for m in _CODE_RE.finditer(query):
        tok = m.group(1)
        if tok.upper() in NON_GENE_ACRONYMS or re.sub(r"\W", "", tok.upper()) in _CELL_LINES or lookup_symbol(tok):
            continue
        if _ACCESSION_RE.match(tok.upper()) or tok.upper().startswith("COVID"):
            continue
        codes.append(tok)
    cands.drug_codes = list(dict.fromkeys(codes))[:MAX_DRUG_CODES]

    cands.rsids = list(dict.fromkeys(m.group(0).lower() for m in _RSID_RE.finditer(query)))[:MAX_RSIDS]
    cands.transcripts_hgvs = list(dict.fromkeys(m.group(0) for m in _HGVS_RE.finditer(query)))[:MAX_HGVS]
    cands.terms = _ngrams(query)

    for m in _INN_DRUG_RE.finditer(query):
        cands.offline_drugs.append(
            ResolvedEntity(
                type="drug", mention=m.group(1), span=(m.start(1), m.end(1)), label=m.group(1),
                source="query_text", matched_on="name_stem", validated=False,
            )
        )
    return cands


# =============================================================================
# Variants
# =============================================================================

_AA3 = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    "Ter": "*", "Sec": "U",
}
_AA1 = "ACDEFGHIKLMNPQRSTVWY"
_PROTEIN_CHANGE_RE = re.compile(rf"(?<![A-Za-z0-9_\.])([{_AA1}])(\d{{2,4}})([{_AA1}*X]|fs|del|dup|ins)(?![A-Za-z0-9_])")
_P3_RE = re.compile(r"\bp\.\(?([A-Z][a-z]{2})(\d{1,4})([A-Z][a-z]{2}|\*|fs|del|dup)\)?(?![A-Za-z0-9])")
_P1_RE = re.compile(rf"\bp\.\(?([{_AA1}])(\d{{1,4}})([{_AA1}*X]|fs|del|dup)\)?(?![A-Za-z0-9])")
_RSID_RE = re.compile(r"\brs\d{3,12}\b", re.I)
_HGVS_RE = re.compile(r"\bN[MCGRP]_\d+(?:\.\d+)?:[cgnpm]\.[A-Za-z0-9_>*+\-()]+[A-Za-z0-9)*>]")
_CDNA_RE = re.compile(r"\b(?:N[MCGRP]_\d+(?:\.\d+)?(?:\([A-Za-z0-9\-]+\))?:)?(c\.[0-9_+\-*]{1,24}(?:[ACGT]>[ACGT]|del[ACGT]*|dup[ACGT]*|ins[ACGT]+|delins[ACGT]+))\b")
_FUSION_PARTNERS = frozenset(
    "ALK ROS1 RET NTRK1 NTRK2 NTRK3 ABL1 ABL BRAF FGFR1 FGFR2 FGFR3 ERG ETV1 ETV4 ETV6 NRG1 MET PDGFRA PDGFRB JAK2 RARA "
    "KMT2A MLL RUNX1 RUNX1T1 BCR EWSR1 FLI1 PML NUTM1 MYB NFIB TFE3 PAX3 PAX7 PAX8 FOXO1 SS18 SSX1 SSX2 CIC DUX4 TMPRSS2".split()
)
_FUSION_RE = re.compile(r"(?<![A-Za-z0-9_\-])([A-Z][A-Z0-9]{1,9})(?:-|::|/)([A-Z][A-Z0-9]{1,9})(?![A-Za-z0-9_\-])")
_EXON_RE = re.compile(
    r"\b(?:([A-Za-z][A-Za-z0-9]{1,9})\s+)?exon\s+(\d{1,2})\s+(deletions?|del|insertions?|ins|skipping|duplications?|"
    r"mutations?|alterations?)\b",
    re.I,
)


def parse_variants(query: str) -> list[ResolvedEntity]:
    """Variant mentions typed in the question. They are unvalidated until a resolver confirms them."""
    found: list[ResolvedEntity] = []

    def add(ent: ResolvedEntity) -> None:
        if not any(_overlaps(ent.span, f.span) for f in found):
            found.append(ent)

    for m in _HGVS_RE.finditer(query):
        add(ResolvedEntity(type="variant", mention=m.group(0), span=m.span(), label=m.group(0), variant_kind="hgvs"))
    for m in _CDNA_RE.finditer(query):
        add(ResolvedEntity(type="variant", mention=m.group(1), span=m.span(1), label=m.group(1), variant_kind="hgvs"))
    for m in _RSID_RE.finditer(query):
        rs = m.group(0).lower()
        add(ResolvedEntity(type="variant", mention=m.group(0), span=m.span(), label=rs, ids={"rsid": rs}, variant_kind="rsid"))
    for m in _P3_RE.finditer(query):
        ref, pos, alt = m.group(1), m.group(2), m.group(3)
        if ref not in _AA3 or (len(alt) == 3 and alt not in _AA3):
            continue
        pc = f"{_AA3[ref]}{pos}{_AA3.get(alt, alt)}"
        add(ResolvedEntity(type="variant", mention=m.group(0), span=m.span(), label=pc, variant_kind="protein_change", protein_change=pc))
    for m in _P1_RE.finditer(query):
        pc = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        add(ResolvedEntity(type="variant", mention=m.group(0), span=m.span(), label=pc, variant_kind="protein_change", protein_change=pc))
    for m in _PROTEIN_CHANGE_RE.finditer(query):
        pc = m.group(0)
        add(ResolvedEntity(type="variant", mention=pc, span=m.span(), label=pc, variant_kind="protein_change", protein_change=pc))
    for m in _FUSION_RE.finditer(query):
        a, b = m.group(1), m.group(2)
        if lookup_symbol(m.group(0)) or a in NON_GENE_ACRONYMS or b in NON_GENE_ACRONYMS:
            continue
        if family_members(a) or family_members(b):
            continue  # "BRAF/MEK" names two drug targets, not a fusion
        if a not in _FUSION_PARTNERS and b not in _FUSION_PARTNERS:
            continue
        if "/" in m.group(0) and not (a in _FUSION_PARTNERS and b in _FUSION_PARTNERS):
            continue  # "EGFR/ALK" usually means "or"; only partner pairs such as BCR/ABL1 read as a fusion
        add(ResolvedEntity(type="variant", mention=m.group(0), span=m.span(), label=f"{a}-{b}", variant_kind="fusion"))
    for m in _EXON_RE.finditer(query):
        gene = m.group(1)
        start = m.start(0) if gene and (lookup_symbol(gene) or gene.isupper()) else m.start(0) + (len(gene) + 1 if gene else 0)
        while start < len(query) and query[start].isspace():
            start += 1
        mention = query[start:m.end(0)]
        event = m.group(3).lower()
        kind = "deletion" if event.startswith("del") else "insertion" if event.startswith("ins") else event.rstrip("s")
        add(ResolvedEntity(type="variant", mention=mention, span=(start, m.end(0)), label=f"exon {m.group(2)} {kind}", variant_kind="exon_event"))
    return sorted(found, key=lambda v: v.span[0])


def attach_variant_genes(query: str, variants: list[ResolvedEntity], genes: Sequence[ResolvedEntity]) -> None:
    """Attach the gene written right before each variant ('KRAS G12C', 'EGFR exon 19 deletion'), or the only gene."""
    usable = [g for g in genes if not g.ambiguous_with]
    for v in variants:
        if v.gene or v.variant_kind == "fusion":
            continue
        best = None
        for g in usable:
            if v.variant_kind == "exon_event" and g.span != (0, 0) and g.span[0] == v.span[0]:
                best = g  # the gene opens the exon mention ("EGFR exon 19 deletion")
                break
            if g.span == (0, 0) or g.span[1] > v.span[0]:
                continue
            gap = query[g.span[1]:v.span[0]]
            if re.fullmatch(r"[\s\-:(]{0,3}", gap) or (v.variant_kind == "exon_event" and len(gap.split()) <= 1 and len(gap) <= 3):
                best = g
        if best is None and v.variant_kind in ("protein_change", "exon_event") and len({g.label for g in usable}) == 1:
            best = usable[0]
        if best is not None:
            v.gene = best.label
            if v.variant_kind == "protein_change" and v.protein_change:
                v.label = f"{best.label} {v.protein_change}"
            elif v.variant_kind == "exon_event":
                v.label = f"{best.label} {v.label}"


# =============================================================================
# Primary gene
# =============================================================================

_INTERVENTION_RE = re.compile(
    r"^(?:inhibit\w*|blockade|block\w*|target(?:ing|ed)?|knock(?:out|down|ing)\w*|antagonis\w*|degrad\w*|silenc\w*|deplet\w*)$",
    re.I,
)
_INTERVENTION_BEFORE_RE = re.compile(
    r"(?:inhibit\w*|blockade|target(?:ing)?|knock(?:out|down|ing\s+out|ing\s+down)|antagonis\w*|degrad\w*|silenc\w*|deplet\w*)"
    r"(?:\s+(?:of|the|on))*\s*$",
    re.I,
)


def _normalized_gene(e: ResolvedEntity) -> bool:
    return e.type == "gene" and not e.ambiguous_with and e.source in ("HGNC", "OpenTargets", "local_lexicon")


def choose_primary_gene(query: str, genes: Sequence[ResolvedEntity], variants: Sequence[ResolvedEntity]) -> ResolvedEntity | None:
    """A gene next to an intervention word first, then one carrying a variant, then the first mention."""
    usable = sorted((g for g in genes if _normalized_gene(g)), key=lambda g: (g.span == (0, 0), g.span[0]))
    if not usable:
        return None
    variant_spans = [v.span for v in variants]
    for g in usable:
        if g.span == (0, 0):
            continue
        after = query[g.span[1]:]
        for vs in variant_spans:
            if vs[0] >= g.span[1] and re.fullmatch(r"[\s\-:(]{0,3}", query[g.span[1]:vs[0]]):
                after = query[vs[1]:]
                break
        words_after = re.findall(r"[A-Za-z][\w\-]*", after)[:2]
        if any(_INTERVENTION_RE.match(w) for w in words_after[:1]) or (
            len(words_after) == 2 and words_after[0].lower() in ("protein", "kinase", "phosphatase") and _INTERVENTION_RE.match(words_after[1])
        ):
            return g
        if _INTERVENTION_BEFORE_RE.search(query[: g.span[0]]):
            return g
    with_variant = {v.gene for v in variants if v.gene}
    for g in usable:
        if g.label in with_variant:
            return g
    return usable[0]


def _primary_variant(primary: ResolvedEntity, variants: Sequence[ResolvedEntity]) -> ResolvedEntity | None:
    return next((v for v in variants if v.gene == primary.label and v.protein_change), None)


def _primary_target_string(primary: ResolvedEntity, variants: Sequence[ResolvedEntity]) -> str:
    v = _primary_variant(primary, variants)
    return f"{primary.label} {v.protein_change}" if v is not None else primary.label


# =============================================================================
# Intents
# =============================================================================

_INTENT_PATTERNS: dict[str, re.Pattern] = {
    "derive": re.compile(r"\b(derive|derivation|show\s+that|from\s+first\s+principles|starting\s+from)\b", re.I),
    "solve": re.compile(r"\b(solve|find\s+the\s+(?:roots?|solutions?|eigenvalues?|general\s+solution)|integrate|differentiate|evaluate)\b", re.I),
    "prove": re.compile(r"\b(prove|proof|disprove|counterexample|is\s+it\s+true\s+that|lemma|theorem|corollary)\b", re.I),
    "compute": re.compile(r"\b(calculate|compute|numerical\s+value|how\s+much|what\s+is\s+the\s+value|convert|in\s+si\s+units)\b", re.I),
    "simulate": re.compile(r"\b(simulate|time[\s\-]*course|trajectory|phase\s+portrait|bifurcation|integrate\s+from|ivp|bvp|fem|fvm)\b", re.I),
    "design": re.compile(r"\b(design|size|select\s+a|safety\s+factor|buckling|stress|deflection|transfer\s+function|bode|pid|heat\s+exchanger)\b", re.I),
    "estimate": re.compile(r"\b(estimate|order\s+of\s+magnitude|fermi|back\s+of\s+the\s+envelope|approximate|scaling)\b", re.I),
    "explain": re.compile(r"\b(explain|what\s+is|intuition|physical\s+meaning|why\s+does|compare)\b", re.I),
    "literature": re.compile(r"\b(papers?|literature|articles?|publications?|reviews?|studies|study|evidence|pmids?|arxiv|doi|cite|citations?|survey|references?)\b", re.I),
    "data_analysis": re.compile(r"\b(fit|regression|spectrum|fft|psd|dataset|csv|hdf5|parquet|uncertainty)\b", re.I),
    "clinical_trials": re.compile(r"\b(trials?|phase\s*(?:[1-4]|i{1,3}v?|iv)\b|nct\d{8}|enrol\w*|cohorts?|registry)", re.I),
    "drug_mechanism": re.compile(r"\b(mechanism\s+of\s+action|moa|inhibitors?|agonists?|antagonists?|drugs?|compounds?|binding|ic50|selectivity)\b", re.I),
    "variant_interpretation": re.compile(r"\b(variants?|mutations?|mutant|pathogenic\w*|vus|clinvar|germline|somatic|allele\s+frequency)\b", re.I),
    "comparison": re.compile(r"\b(compare[ds]?|comparison|versus|vs\.?|difference\s+between|better\s+than|head[\s\-]to[\s\-]head)\b", re.I),
    "safety": re.compile(r"\b(adverse\s+events?|toxicit\w*|safety|side[\s\-]effects?|faers|black\s+box|contraindicat\w*|warnings?)\b", re.I),
    "target_assessment": re.compile(r"\b(druggab\w*|target\s+(?:assessment|validation)|tractab\w*|essentiality|associations?)\b", re.I),
}


def _deterministic_intents(ctx: QueryContext, query: str) -> set:
    intents = {name for name, pat in _INTENT_PATTERNS.items() if pat.search(query)}
    if ctx.is_simulation_intent:
        intents.add("simulation")
    if ctx.wants_steady_state:
        intents.add("steady_state")
    if ctx.has_single_cell_intent:
        intents.add("single_cell")
    if ctx.variants:
        intents.add("variant_interpretation")
    if ctx.drugs and re.search(r"\b(mechanism|how\s+does|works?|acts?)\b", query, re.I):
        intents.add("drug_mechanism")
    if ctx.primary_gene is not None:
        intents.add("target_assessment")
    return intents


# =============================================================================
# Live resolution and the model-assisted planner
# =============================================================================

def _resolver_enabled(registry: Any) -> bool:
    if os.getenv("TRIBOS_RESOLVER_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        return registry is not None and registry.get_entry(RESOLVER_TOOL) is not None
    except Exception:  # noqa: BLE001
        return False


async def _resolve_live(registry: Any, query: str, cands: Candidates, budget_s: float) -> dict[str, Any] | None:
    try:
        res = await asyncio.wait_for(
            registry.execute(
                RESOLVER_TOOL,
                query=query,
                terms=cands.terms,
                gene_tokens=cands.gene_tokens,
                drug_codes=cands.drug_codes,
                rsids=cands.rsids,
                transcripts_hgvs=cands.transcripts_hgvs,
                # The resolver returns what it has just inside the budget; a call with no upstream answer fails
                # and the offline lexicon is used below.
                deadline_s=min(11.0, max(0.5, budget_s - 0.3)),
            ),
            timeout=max(0.01, budget_s),
        )
    except TimeoutError:
        logger.info("Entity resolution exceeded the %.2fs budget; using the offline lexicon", budget_s)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.info("Entity resolution failed: %s", exc)
        return None
    if not getattr(res, "success", False) or not isinstance(getattr(res, "data", None), dict):
        return None
    return res.data


def _entities_from(data: dict[str, Any], query: str) -> list[ResolvedEntity]:
    out: list[ResolvedEntity] = []
    for raw in data.get("entities") or []:
        try:
            ent = ResolvedEntity.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        s, e = ent.span
        if not (0 <= s < e <= len(query)) or query[s:e] != ent.mention:
            # Mentions must be literal text of the question; re-anchor or drop.
            idx = query.find(ent.mention)
            if not ent.mention or idx < 0:
                continue
            ent.span = (idx, idx + len(ent.mention))
        out.append(ent)
    return out


def planner_mode() -> str:
    mode = os.getenv("TRIBOS_PLANNER", "auto").strip().lower()
    return mode if mode in ("off", "auto", "always") else "auto"


SCOPES = ("research", "conversational", "unclear")

# The question types the planner model is offered: the STEM ones (search_plan.QUESTION_TYPES also keeps legacy
# clinical types, which merge_llm_plan still accepts, but which no STEM question should be routed as).
PLANNER_QUESTION_TYPES = tuple(
    t for t in QUESTION_TYPES
    if t in ("proof", "derivation", "numerical", "design_sizing", "modelling", "conceptual", "literature_review",
             "methods", "statistics", "comparison", "general")
)

_PLANNER_SYSTEM = (
    "You read one message sent to Tribos, a scientific research assistant for mathematics, physics, engineering, "
    "and computational science, and return a routing plan as JSON only, with no prose:\n"
    '{"scope": "research|conversational|unclear", "intents": [...], '
    '"entities": [{"text": "...", "type": "concept|equation|quantity|constant|material|system|gene|drug|disease"}], '
    '"question_type": "...", "concepts": [["central topic", "synonym"], ["second concept", "synonym"]], "web_query": "..."}\n'
    "scope: research when the message asks about any mathematical, physical, engineering, computational, or scientific "
    "topic (a theorem, equation, physical system, material, numerical method, dataset, or field), even a broad one; "
    "conversational for a greeting, thanks, farewell, small talk, or a question about the assistant itself; "
    "unclear for gibberish, a typo-only message, or words with no evident scientific meaning.\n"
    f"Allowed intents: {', '.join(INTENTS)}.\n"
    f"question_type: one of {', '.join(PLANNER_QUESTION_TYPES)}.\n"
    "concepts: the 1-3 technical concepts the question is about, central topic first, for a scholarly search. Each "
    'group lists the term as written plus up to 3 standard synonyms or abbreviations (["Navier-Stokes equations", '
    '"incompressible Navier-Stokes"]). Take concepts only from the question: never add a candidate answer the '
    "question does not name.\n"
    "web_query: a concise search-engine query for the question.\n"
    "Copy each entity text exactly as it is written in the question. Never output identifiers, accessions or file paths."
)

# Messages that are clearly not research questions; used without a planner model and to accept its verdict
# in a thread that already has history (where a vague message is usually a follow-up).
_CONVERSATIONAL_RE = re.compile(
    r"^(?:(?:and\s+)?(?:hi|hello|hey|who\s+are\s+you|what\s+can\s+you\s+(?:do|help(?:\s+me)?(?:\s+with)?)(?:[\s\w]*)|what\s+are\s+your\s+(?:official\s+)?(?:agent\s+)?tools|"
    r"ok(?:ay)?|cool|great|nice|perfect|awesome|got\s+it|thanks?(?:\s+you)?|thx|ty|cheers|"
    r"(?:good)?\s*bye|see\s+(?:you|ya)|good\s*night|lol|haha+|test(?:ing)?|how\s+are\s+you(?:\s+doing)?)"
    r"(?:\s+(?:so\s+much|a\s+lot|again|very\s+much|for\s+(?:the|your)\s+help|bro|man|mate|buddy|for\s+mee?))*[\s\.\?!,~:)]*)+$",
    re.I,
)
_BIOMED_VOCAB_RE = re.compile(
    r"\b(?:theorem\w*|lemma\w*|corollar\w*|proof\w*|prove|manifold\w*|hilbert|banach|sobolev|lie\s+group\w*|"
    r"eigenval\w*|eigenvec\w*|spectrum|spectral|fourier|laplace|greens?\s+function|dirac|schr[oö]dinger|"
    r"navier[\s\-]stokes|maxwell\w*|boltzmann|hamilton\w*|lagrang\w*|noether|poisson|helmholtz|wave\s+equation|"
    r"heat\s+equation|odes?|pdes?|sdes?|integrals?|derivatives?|differenti\w*|converg\w*|diverg\w*|asymptot\w*|"
    r"perturb\w*|bifurcat\w*|lyapunov|lorenz|van\s+der\s+pol|duffing|pendulum|oscillator\w*|quantum|relativ\w*|"
    r"thermodynam\w*|entrop\w*|enthalp\w*|viscosit\w*|reynolds|mach|prandtl|nusselt|rayleigh|turbulen\w*|"
    r"elastic\w*|plastic\w*|stress|strain|buckl\w*|cantilever|beam\w*|truss\w*|torsion|fatigue|fracture|"
    r"kalman|nyquist|bode|pid|transfer\s+function|controllab\w*|observab\w*|convex|simplex|gradient\s+descent|"
    r"runge[\s\-]kutta|finite\s+element\w*|finite\s+volume\w*|monte\s+carlo|markov|homolog\w*|cohomolog\w*|"
    r"topolog\w*|homotop\w*|galois|riemann\w*|cauchy|gauss\w*|euler|bernoulli|bessel|legendre|hermite|chebyshev|"
    r"laguerre|hypergeometric|zeta|prime\w*|diophantine|modular|elliptic|stochastic|ito|martingale|brownian|"
    r"carnot|otto|rankine|brayton|stefan[\s\-]boltzmann|planck\w*|compton|de\s+broglie|bohr|rutherford|fermi|"
    r"bose[\s\-]einstein|pauli|heisenberg|klein[\s\-]gordon|yukawa|feynman|casimir|lorentz|minkowski|schwarzschild|"
    r"kerr|friedmann|christoffel|ricci|bianchi|geodesic\w*|curvatur\w*|tensor\w*|spinor\w*|symplectic|"
    r"dna|rna|mrna|sirna|crispr|pcr|genes?|genom\w*|protein\w*|cells?|cellular|tumou?r\w*|cancer\w*|oncolog\w*|"
    r"diseases?|drugs?|therap\w*|pathways?|enzym\w*|receptors?|antibod\w*|vaccin\w*|vir(?:us|al)\w*|bacteri\w*|"
    r"immun\w*|mutat\w*|clinical|patients?|dos(?:e|ing)\w*|syndrom\w*|infect\w*|metabol\w*|kinases?|inhibit\w*)\b"
    r"|\\(?:frac|int|sum|prod|sqrt|partial|nabla|infty|alpha|beta|gamma|delta|epsilon|lambda|omega|sigma|theta|phi|psi)\b",
    re.I,
)


def _is_junk_word(word: str) -> bool:
    """Keyboard noise or a stretched interjection: a letter typed three times running, or no vowel at all."""
    w = word.lower()
    return bool(re.search(r"([a-z])\1\1", w)) or not re.search(r"[aeiouy]", w)


def is_small_talk(query: str) -> bool:
    """Thanks, farewells, 'ok', 'how are you': never a research question, even mid-thread."""
    return bool(_CONVERSATIONAL_RE.match(query.strip()))


def heuristic_scope(query: str, cands: Candidates, intents: set[str]) -> str:
    """Scope without a planner model. Conservative: anything that might be a research question is research."""
    if is_small_talk(query):
        return "conversational"
    words = [w for w in _WORD_RE.findall(query) if not w.isdigit()]
    if not words:
        return "unclear"
    if intents or cands.gene_tokens or cands.drug_codes or cands.rsids or cands.transcripts_hgvs:
        return "research"
    if _BIOMED_VOCAB_RE.search(query):
        return "research"
    if len(words) <= 3 and all(_is_junk_word(w) for w in words):
        return "unclear"
    return "research"


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    if "</think>" in text.lower():
        text = text[text.lower().rfind("</think>") + len("</think>"):]
    return re.sub(r"<think>.*$", "", text, flags=re.S | re.I)


def _first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


async def plan_with_llm(
    query: str,
    llm_factory: Callable[..., Any] | None,
    *,
    model_name: str,
    api_key: str | None,
    timeout_s: float,
) -> dict[str, Any] | None:
    """Ask the model for intents and mentions. Returns the sanitized plan, or None when the model is unavailable."""
    if llm_factory is None:
        return None
    try:
        llm = llm_factory(model_name=model_name, api_key=api_key, streaming=False, timeout=max(1.0, timeout_s))
    except Exception as exc:  # noqa: BLE001
        logger.info("Planner model unavailable: %s", exc)
        return None
    ainvoke = getattr(llm, "ainvoke", None)
    if not callable(ainvoke):
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        call_coro = cast(Awaitable[Any], ainvoke([SystemMessage(content=_PLANNER_SYSTEM), HumanMessage(content=query)]))
        reply = await asyncio.wait_for(call_coro, timeout=max(0.01, timeout_s))
    except TimeoutError:
        logger.info("Planner model exceeded %.2fs", timeout_s)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.info("Planner model call failed: %s", exc)
        return None
    obj = _first_json_object(_strip_think(_content_text(getattr(reply, "content", reply))))
    if obj is None:
        return None
    intents = [i for i in (obj.get("intents") or []) if isinstance(i, str) and i in INTENTS]
    mentions: list[tuple[str, str]] = []
    for item in (obj.get("entities") or [])[:8]:
        if not isinstance(item, dict):
            continue
        text, kind = item.get("text"), item.get("type")
        if (
            isinstance(text, str)
            and kind in (
                "concept", "equation", "quantity", "constant", "material", "system",
                "mass", "damping", "stiffness", "force", "frequency", "displacement",
                "velocity", "acceleration", "pressure", "energy", "power", "time", "length",
                "gene", "drug", "disease",
            )
            and text.strip()
            and text in query
        ):
            mentions.append((text, kind))
    scope = obj.get("scope")
    return {
        "intents": intents,
        "entities": mentions,
        "scope": scope if scope in SCOPES else None,
        # Validated against the question when merged into the search plan (search_plan.merge_llm_plan).
        "search": {k: obj.get(k) for k in ("question_type", "concepts", "web_query")},
    }


def _llm_entities(query: str, mentions: Sequence[tuple[str, str]], existing: Sequence[ResolvedEntity]) -> list[ResolvedEntity]:
    out: list[ResolvedEntity] = []
    procedural = procedural_spans(query)
    for text, kind in mentions:
        idx = query.find(text)
        span = (idx, idx + len(text))
        if any(_overlaps(span, e.span) for e in [*existing, *out]):
            continue
        words = [w.lower() for w in _WORD_RE.findall(text)]
        if not words or all(w in PROCEDURAL_WORDS or w in _STOPWORDS for w in words):
            continue  # "duration", "parameter values": how to run the request, not what it is about
        if any(_overlaps(span, p) for p in procedural):
            continue
        ent = _lexicon_entity(query, *span, matched_on_override=None) if kind == "gene" else None
        if ent is None:
            ent = ResolvedEntity(type=cast(EntityType, kind), mention=text, span=span, label=text, source="query_text", matched_on="planner", validated=False)
        out.append(ent)
    return out


# =============================================================================
# Routing
# =============================================================================

def decide_builtin_sources(ctx: QueryContext) -> None:
    """Record run/skip decisions (with reasons) for the built-in agents."""
    if ctx.scope != "research":
        for name in ("archivon", "websurfer", "axiom", "calcula", "physis", "dynamis"):
            ctx.decisions[name] = SourceDecision(run=False, reason="not a research question")
        return

    # Literature and web search only when the answer can depend on outside evidence (agents.evidence_need).
    need = ctx.evidence_need
    pol = getattr(ctx, "tool_policy", None)
    if pol is not None and pol.prohibit_search:
        s_reason = pol.search_reason or "Search disabled by user request"
        ctx.decisions["archivon"] = SourceDecision(run=False, reason=s_reason)
        ctx.decisions["websurfer"] = SourceDecision(run=False, reason=s_reason)
    elif need is not None and need.skip_retrieval:
        ctx.decisions["archivon"] = SourceDecision(run=False, reason=need.reason)
        ctx.decisions["websurfer"] = SourceDecision(run=False, reason=need.reason)
    elif not ctx.enable_web_search:
        # Search off covers every external retrieval: the scholarly literature APIs as well as web search.
        ctx.decisions["archivon"] = SourceDecision(run=False, reason="Search is off: no literature search")
        ctx.decisions["websurfer"] = SourceDecision(run=False, reason="Search is off: no web search")
    else:
        ctx.decisions["archivon"] = SourceDecision(run=True, reason=need.reason if need is not None else "")
        ctx.decisions["websurfer"] = SourceDecision(run=True, reason="")
    wants_axiom = bool(
        {"derive", "solve", "prove"} & set(ctx.intents)
        or (need is not None and need.kind == "closed_computation")
        or ctx.equations
        or ctx.concepts
        or re.search(r"\\(?:frac|int|sum|prod|sqrt|partial|nabla)|=", ctx.clean_query)
    )
    ctx.decisions["axiom"] = SourceDecision(
        run=wants_axiom, reason="symbolic reasoning requested" if (wants_axiom and pol and pol.prohibit_formal) else ("symbolic/formal reasoning requested" if wants_axiom else "no symbolic derivation requested")
    )
    if pol is not None and pol.prohibit_formal:
        ctx.decisions["formal_proof"] = SourceDecision(run=False, reason=pol.formal_reason or "formal prover disabled by user")
    wants_calcula = bool(
        {"compute", "estimate", "data_analysis"} & set(ctx.intents)
        or ctx.quantities
        or ctx.constants
        or ctx.dataset_attachment is not None
    )
    if wants_calcula:
        calcula_reason = "numerical computation requested"
    elif need is not None and need.kind in ("closed_computation", "self_contained"):
        # The computation is requested; it runs in the verified mathematics agent (Axiom), which checks it exactly.
        calcula_reason = "exact computation runs in the verified mathematics agent (Axiom)"
    else:
        calcula_reason = "no numerical data analysis requested"
    ctx.decisions["calcula"] = SourceDecision(run=wants_calcula, reason=calcula_reason)
    wants_physis = bool(
        {"design"} & set(ctx.intents)
        or ctx.materials
        or ctx.constants
    )
    ctx.decisions["physis"] = SourceDecision(
        run=wants_physis, reason="physical/engineering domain analysis requested" if wants_physis else "no domain analysis requested"
    )
    plan = ctx.simulation_plan
    if ctx.is_simulation_intent and plan is not None and plan.validation_errors:
        # Rejected before any computation: the orchestrator reports plan.validation_errors, never a substitute run.
        reason = "request rejected: " + "; ".join(e.get("message", "") for e in plan.validation_errors[:2])
        ctx.decisions["dynamis"] = SourceDecision(run=False, reason=reason)
    elif ctx.is_simulation_intent:
        reason = _simulation_reason(plan)
        ctx.decisions["dynamis"] = SourceDecision(run=True, reason=reason)
    else:
        reason = _suppression_reason(ctx.clean_query) if ctx.suppress_simulation else "no simulation requested"
        ctx.decisions["dynamis"] = SourceDecision(run=False, reason=reason)

    # Legacy compatibility aliases for internal code querying ctx.decisions
    ctx.decisions["lithoscribe"] = ctx.decisions["archivon"]
    ctx.decisions["vivarix"] = ctx.decisions["dynamis"]
    for name in list(ctx.decisions):
        ctx.decisions[name] = ctx.gate_decision(name, ctx.decisions[name])


def _simulation_reason(plan: SimulationPlan | None) -> str:
    if plan is None:
        return ""
    if plan.action == "parameter_scan":
        return f"parameter scan of {plan.scan_parameter}"
    return "steady state requested" if plan.action == "steady_state" else f"{plan.duration_seconds:g}s time course"


# The sources a "papers only" or "trials only" turn may run: Tribos has no trial registry, so both mean the
# literature search.
_ALLOWLISTS = {"papers": {"lithoscribe", "archivon"}, "trials": {"lithoscribe", "archivon"}}


def apply_simulation_request(ctx: QueryContext, query: str, *, model_known: bool = False) -> None:
    """Fill the scoped constraints, simulation intent and the typed SimulationPlan from the question.
    model_known: a follow-up ("run it again for 200 s") refers to the previous turn's model."""
    constraints = detect_simulation_constraints(query)
    ctx.simulation_constraints = constraints
    ctx.suppress_simulation = constraints.simulation_forbidden
    ctx.is_simulation_intent = not ctx.suppress_simulation and (
        constraints.simulation_requested or ctx.model_attachment is not None or model_known
    )
    ctx.wants_steady_state = ctx.is_simulation_intent and bool(_STEADY_STATE_REQUEST_RE.search(query))
    ctx.simulation_plan = None
    ctx.sim_duration = DEFAULT_SIM_DURATION_S
    if ctx.is_simulation_intent:
        constraints.simulation_requested = True
        ctx.simulation_plan = build_simulation_plan(query, biomodel_id=ctx.biomodel_id, wants_steady_state=ctx.wants_steady_state)
        if math.isfinite(ctx.simulation_plan.duration_seconds):
            ctx.sim_duration = ctx.simulation_plan.duration_seconds
    kind = _only_kind(query)
    if kind is not None:
        ctx.source_allowlist = set(_ALLOWLISTS[kind])
        ctx.source_restriction_reason = f"{kind} only requested"
    if _SINGLE_CELL_BAN_RE.search(query):
        ctx.extras["single_cell_forbidden"] = True
    ctx.excluded_modules = detect_excluded_modules(query)
    if "single_cell" in ctx.excluded_modules:
        ctx.extras["single_cell_forbidden"] = True


def apply_standing_instructions(ctx: QueryContext, query: str, instructions: list[str] | None) -> None:
    """Apply the routing constraints of persisted, explicitly scoped instructions to this turn (ORC-011).

    "From now on, papers only." given in an earlier turn restricts the sources of later turns, as typed in the
    current question would. The current question wins where it speaks for itself: its own "X only" restriction,
    an explicit simulation request (which a standing "papers only" / "do not simulate" no longer blocks), or an
    attached dataset (which a standing single-cell ban no longer blocks). What was applied is recorded in
    ctx.extras["standing_constraints"] and shown as a plan fact."""
    texts = [t for t in (instructions or []) if isinstance(t, str) and t.strip()]
    if not texts:
        return
    current = detect_simulation_constraints(query)
    current_only = _only_kind(query)
    applied: list[dict[str, str]] = []
    for text in texts:
        kind = _only_kind(text)
        if kind is not None and current_only is None and ctx.source_allowlist is None and not current.simulation_requested:
            ctx.source_allowlist = set(_ALLOWLISTS[kind])
            ctx.source_restriction_reason = f"{kind} only requested (standing instruction)"
            applied.append({"instruction": text[:300], "constraint": f"{kind}_only"})
        banned = kind is not None or _simulation_ban(text) is not None
        if banned and not current.simulation_requested and not ctx.suppress_simulation:
            ctx.suppress_simulation = True
            ctx.is_simulation_intent = False
            ctx.wants_steady_state = False
            ctx.simulation_plan = None
            ctx.simulation_constraints.simulation_forbidden = True
            applied.append({"instruction": text[:300], "constraint": "no_simulation"})
        if (
            _SINGLE_CELL_BAN_RE.search(text)
            and ctx.dataset_attachment is None
            and not ctx.dataset_path
            and not ctx.extras.get("single_cell_forbidden")
        ):
            ctx.extras["single_cell_forbidden"] = True
            applied.append({"instruction": text[:300], "constraint": "no_single_cell"})
    if applied:
        ctx.extras["standing_constraints"] = applied


def _merge(primary: list[ResolvedEntity], fallback: list[ResolvedEntity]) -> list[ResolvedEntity]:
    out = list(primary)
    for e in fallback:
        if not any(_overlaps(e.span, p.span) for p in out if p.span != (0, 0)):
            out.append(e)
    return out


def _offline_stem_entities(query: str, covered_spans: Sequence[tuple[int, int]]) -> list[ResolvedEntity]:
    """Offline STEM entities (equations, systems, materials, constants, concepts, quantities) from entity_lexicon."""
    out: list[ResolvedEntity] = []
    taken: list[tuple[int, int]] = [s for s in covered_spans if s != (0, 0)]

    def push(kind: EntityType, items: Sequence[Any], source: str) -> None:
        for item in items:
            item_metadata: dict[str, Any] = {}
            item_ids: dict[str, str] = {}
            ambiguous_with: list[str] = []
            if isinstance(item, dict):
                mention = str(item.get("mention") or item.get("canonical") or item.get("key") or "")
                label = str(item.get("label") or item.get("canonical") or item.get("key") or mention)
                span = item.get("span")
                if span is None:
                    idx = query.lower().find(mention.lower())
                    span = (idx, idx + len(mention)) if idx >= 0 else (0, len(query))
                phys = item.get("physical_type")
                if phys:
                    item_ids["physical_type"] = str(phys)
                if item.get("display_name"):
                    item_metadata["display_name"] = str(item["display_name"])  # shown to the reader; label stays the id
                for k in ("value", "units", "param_name", "physical_type", "ambiguous", "ambiguous_with"):
                    if k in item and item[k] is not None:
                        item_metadata[k] = item[k]
                if item.get("ambiguous_with"):
                    ambiguous_with = list(item["ambiguous_with"])
            elif isinstance(item, (list, tuple)) and len(item) == 3:
                mention, label, span = item
            else:
                continue

            if any(_overlaps(span, s) for s in taken):
                continue
            taken.append(span)
            out.append(
                ResolvedEntity(
                    type=kind,
                    mention=mention,
                    span=span,
                    label=label,
                    ids=item_ids,
                    source=source,
                    matched_on="name",
                    validated=True,
                    metadata=item_metadata,
                    ambiguous_with=ambiguous_with,
                )
            )

    push("equation", find_offline_equations(query), "local_lexicon")
    push("system", find_offline_systems(query), "local_lexicon")
    push("material", find_offline_materials(query), "local_lexicon")
    push("constant", find_offline_constants(query), "codata_2022")
    push("concept", find_offline_concepts(query), "local_lexicon")
    push("quantity", find_offline_quantities(query), "pint")
    return sorted(out, key=lambda e: e.span[0])


# A disease term that names a whole class ("cancer", "solid tumors") rather than a disease. Kept when it is the only
# disease; dropped next to a specific one of its family ("ovarian cancer", "melanoma"), whose tools it would only
# dilute (a PrimeKG profile of "cancer", trials for "cancer").
_ONCO_GENERIC = frozenset(
    "cancer|cancers|tumor|tumors|tumour|tumours|neoplasm|neoplasms|carcinoma|carcinomas|malignancy|malignancies|"
    "solid tumor|solid tumors|solid tumour|solid tumours|malignant tumor|malignant tumors|malignant neoplasm|"
    "malignant neoplasms|human cancer|human cancers".split("|")
)
_ANY_GENERIC = frozenset({"disease", "diseases", "disorder", "disorders", "illness", "illnesses"})
_ONCO_WORD_RE = re.compile(
    r"\b(?:cancers?|tumou?rs?|neoplasms?|neoplastic|malignan\w*|carcinomas?|adenocarcinomas?|sarcomas?|lymphomas?|"
    r"leuka?emias?|myelomas?|melanomas?|gliomas?|glioblastomas?|blastomas?|mesotheliomas?|\w+blastomas?|\w+carcinomas?|"
    r"\w+sarcomas?|nsclc|sclc|pdac|hcc|crc|aml|cml|cll|mds|hgsoc|tnbc|gbm|luad|lusc)\b",
    re.I,
)


def _disease_phrase(text: str | None) -> str:
    words: list[str] = re.findall(r"[a-z0-9]+", (text or "").lower())
    return " ".join(words)


def _generic_family(e: ResolvedEntity) -> str | None:
    """'onco' or 'any' when every name of the entity (mention and label) is a class term, else None."""
    names = [p for p in (_disease_phrase(e.mention), _disease_phrase(e.label)) if p]
    if not names:
        return None
    if all(p in _ONCO_GENERIC for p in names):
        return "onco"
    if all(p in _ANY_GENERIC or p in _ONCO_GENERIC for p in names):
        return "any"
    return None


def drop_generic_diseases(diseases: list[ResolvedEntity]) -> list[ResolvedEntity]:
    """The diseases without a class term ("cancer", "tumor", "disease") when a specific disease of its family is also
    named ("ovarian cancer" or "melanoma" for "cancer"; any specific disease for "disease"). A lone class term stays."""
    families = [_generic_family(e) for e in diseases]
    specific = [e for e, fam in zip(diseases, families, strict=False) if fam is None]
    if not specific:
        return list(diseases)
    onco_specific = any(_ONCO_WORD_RE.search(f"{e.mention} {e.label}") for e in specific)
    return [e for e, fam in zip(diseases, families, strict=False) if fam is None or (fam == "onco" and not onco_specific)]


def drop_generic_disease_names(names: list[str]) -> list[str]:
    """drop_generic_diseases for plain condition strings (['cancer', 'ovarian cancer'] -> ['ovarian cancer'])."""
    ents = [ResolvedEntity(type="disease", mention=n, label=n) for n in names]
    kept = {id(e) for e in drop_generic_diseases(ents)}
    return [n for n, e in zip(names, ents, strict=False) if id(e) in kept]


def _apply_resolution(
    ctx: QueryContext, query: str, cands: Candidates, variants: list[ResolvedEntity], data: dict[str, Any] | None
) -> tuple[list[ResolvedEntity], list[ResolvedEntity], list[ResolvedEntity]]:
    """Return (genes, drugs, diseases) and enrich variants in place."""
    if data is None:
        return list(cands.lexicon_genes), list(cands.offline_drugs), []
    resolved = _entities_from(data, query)
    ctx.source_status.update({str(k): str(v) for k, v in (data.get("source_status") or {}).items()})
    ctx.extras["resolver_timings_ms"] = {
        str(k): float(v) for k, v in (data.get("timings_ms") or {}).items() if isinstance(v, (int, float))
    }
    genes = [e for e in resolved if e.type == "gene"]
    drugs = [e for e in resolved if e.type == "drug"]
    diseases = [e for e in resolved if e.type == "disease"]
    # A protein's common name inside an exact disease or phenotype name ("insulin resistance") is not a gene mention.
    named = [d.span for d in diseases if d.matched_on == "name" and d.span != (0, 0)]
    lexicon = [
        g for g in cands.lexicon_genes
        if g.mention == g.mention.upper() or not any(s != g.span and s[0] <= g.span[0] and g.span[1] <= s[1] for s in named)
    ]
    genes = _merge(genes, lexicon)
    if ctx.source_status.get("opentargets") != "ok":
        drugs = _merge(drugs, cands.offline_drugs)
    by_mention = {e.mention: e for e in resolved if e.type == "variant"}
    for v in variants:
        r = by_mention.get(v.mention)
        if r is None:
            continue
        v.validated, v.source, v.matched_on = r.validated, r.source, r.matched_on
        v.ids = dict(r.ids) if r.validated else {}
        if r.gene:
            v.gene = r.gene
    statuses = set(ctx.source_status.values())
    ctx.normalization = "resolved" if statuses <= {"ok"} else "partial"
    return genes, drugs, diseases


def _fold_defined_acronyms(query: str, entities: list[ResolvedEntity]) -> list[ResolvedEntity]:
    """An acronym the question defines in parentheses right after a resolved name ("idiopathic pulmonary fibrosis
    (IPF)") is that entity's alias, not a separate entity looked up on its own (IPF -> "platelet quantity")."""
    out = list(entities)
    for full in entities:
        if full.span == (0, 0) or " " not in full.mention:
            continue
        m = re.match(r"\s*\(\s*([A-Za-z][A-Za-z0-9\-]{1,9})\s*\)", query[full.span[1]:])
        if not m:
            continue
        acronym = m.group(1)
        initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", full.mention)).upper()
        if not (acronym.isupper() or acronym.upper() == initials):
            continue
        out = [e for e in out if e is full or e.mention.upper() != acronym.upper()]
        if acronym not in full.aliases:
            full.aliases.append(acronym)
    return out


def _mention_span(query: str, mention: str) -> tuple[int, int]:
    start = query.lower().find(mention.lower())
    return (start, start + len(mention)) if start >= 0 else (0, 0)


def _parser_variants(query: str) -> list[ResolvedEntity]:
    """Variants from the variant-intelligence parser (3-letter, cDNA and VCV forms), unvalidated."""
    mentions: list[Any] = []
    out: list[ResolvedEntity] = []
    for m in mentions:
        if m.protein_change:
            kind, label = "protein_change", m.protein_change
        elif m.rsid:
            kind, label = "rsid", m.rsid
        elif m.hgvs or m.cdna_change:
            kind, label = "hgvs", m.hgvs or m.cdna_change
        else:
            continue
        out.append(
            ResolvedEntity(
                type="variant",
                mention=m.raw,
                span=_mention_span(query, m.raw),
                label=label or m.raw,
                ids={"rsid": m.rsid} if m.rsid else {},
                gene=m.gene,
                variant_kind=kind,
                protein_change=m.protein_change,
            )
        )
    return out


_CURATED_DRUGS = frozenset({
    "tagrisso", "keytruda", "opdivo", "herceptin", "avastin", "humira", "lumakras",
    "krazati", "tarceva", "iressa", "xalkori", "gleevec", "glivec", "aspirin", "metformin",
    "pembrolizumab", "osimertinib", "sotorasib", "adagrasib"
})
_CURATED_DRUG_RE = re.compile(r"\b(" + "|".join(sorted(_CURATED_DRUGS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _parser_drugs(query: str) -> list[ResolvedEntity]:
    """Drug names from INN stems and the curated list, unvalidated; ChEMBL resolves them exactly later."""
    mentions: list[str] = []
    for m in _CURATED_DRUG_RE.finditer(query):
        mentions.append(m.group(1).lower())
    for m in _INN_DRUG_RE.finditer(query):
        mentions.append(m.group(1).lower())
    mentions = list(dict.fromkeys(mentions))
    return [
        ResolvedEntity(type="drug", mention=m, span=_mention_span(query, m), label=m, matched_on="drug_name_pattern")
        for m in mentions
    ]


async def build_query_context(
    *,
    query: str,
    clean_query: str,
    registry: Any,
    enable_web_search: bool,
    attachments: list[DatasetRef],
    attachment_errors: list[str],
    user_id: str,
    thread_id: str,
    model_name: str,
    api_key: str | None,
    llm_factory: Callable[..., Any] | None = None,
    budget_s: float = 3.5,
    prior_subject: dict[str, str] | None = None,
    standing_instructions: list[str] | None = None,
) -> QueryContext:
    """Parse and normalize the question into a QueryContext within budget_s (plus the planner model's own cap).

    prior_subject is the previous turn's active_subject(ctx) in the same investigation; a follow-up that names
    no subject of its own ("What about its safety?") is resolved to it before any retrieval.
    standing_instructions are the instructions the researcher scoped to the investigation or profile ("From now
    on, papers only."); their routing constraints apply to this turn unless the question overrides them (ORC-011)."""
    holder: list[QueryContext] = []
    try:
        return await _build_query_context(
            query=query, clean_query=clean_query, registry=registry, enable_web_search=enable_web_search,
            attachments=attachments, attachment_errors=attachment_errors, user_id=user_id, thread_id=thread_id,
            model_name=model_name, api_key=api_key, llm_factory=llm_factory, budget_s=budget_s,
            prior_subject=prior_subject, standing_instructions=standing_instructions, holder=holder,
        )
    except BaseException:
        if holder:
            cancel_planner(holder[0])  # nobody will await the planner call of a context that failed to build
        raise


async def _build_query_context(
    *,
    query: str,
    clean_query: str,
    registry: Any,
    enable_web_search: bool,
    attachments: list[DatasetRef],
    attachment_errors: list[str],
    user_id: str,
    thread_id: str,
    model_name: str,
    api_key: str | None,
    llm_factory: Callable[..., Any] | None,
    budget_s: float,
    prior_subject: dict[str, str] | None,
    holder: list[QueryContext],
    standing_instructions: list[str] | None = None,
) -> QueryContext:
    t0 = time.perf_counter()
    env_budget = os.getenv("TRIBOS_NORMALIZER_BUDGET_S")
    if env_budget and budget_s == 3.5:
        try:
            budget_s = max(0.1, float(env_budget))
        except ValueError:
            pass
    from ..tools.policy import active_tool_policy, extract_tool_policy

    tool_policy = active_tool_policy() or extract_tool_policy(
        clean_query, enable_web_search=enable_web_search, standing_instructions=standing_instructions
    )
    if tool_policy.prohibit_search:
        enable_web_search = False

    ctx = QueryContext(
        raw_query=query,
        clean_query=clean_query,
        user_id=user_id,
        thread_id=thread_id,
        attachments=list(attachments or []),
        attachment_errors=list(attachment_errors or []),
        enable_web_search=enable_web_search,
        tool_policy=tool_policy,
    )
    holder.append(ctx)
    ctx.biomodel_id = extract_biomodel_id(clean_query)
    apply_simulation_request(ctx, clean_query)
    path = extract_dataset_path(clean_query)
    ctx.dataset_path = path if path and path in query else None
    ctx.has_single_cell_intent = (
        bool(ctx.dataset_path) or has_single_cell_intent(clean_query) or ctx.dataset_attachment is not None
    )

    cands = extract_candidates(clean_query)
    variants = parse_variants(clean_query)
    ctx.timings_ms["parse"] = round((time.perf_counter() - t0) * 1000, 1)

    # The planner model starts now, alongside entity resolution. Its search plan helps every question; routing
    # waits for it only when nothing was recognised (or with TRIBOS_PLANNER=always).
    mode = planner_mode()
    if mode != "off" and llm_factory is not None:
        ctx.planner_started = time.perf_counter()
        ctx.planner_task = asyncio.ensure_future(
            plan_with_llm(clean_query, llm_factory, model_name=model_name, api_key=api_key, timeout_s=search_plan_wait_s())
        )

    data: dict[str, Any] | None = None
    if _resolver_enabled(registry) and (cands.terms or cands.gene_tokens or cands.rsids or cands.transcripts_hgvs):
        t1 = time.perf_counter()
        data = await _resolve_live(registry, clean_query, cands, budget_s)
        ctx.timings_ms["resolver"] = round((time.perf_counter() - t1) * 1000, 1)
    genes, drugs, diseases = _apply_resolution(ctx, clean_query, cands, variants, data)
    genes, drugs, diseases = (_fold_defined_acronyms(clean_query, group) for group in (genes, drugs, diseases))
    if data is None:
        ctx.normalization = "offline_lexicon"
    stem_entities = _offline_stem_entities(
        clean_query,
        [*(e.span for e in [*genes, *drugs, *diseases, *variants]), *procedural_spans(clean_query)],
    )

    nothing_found = not (
        genes or drugs or diseases or variants or stem_entities or ctx.biomodel_id or ctx.dataset_path or ctx.attachments
    )
    planner_scope: str | None = None
    plan: dict[str, Any] | None = None
    if mode == "always" or (mode == "auto" and nothing_found):
        t2 = time.perf_counter()
        if ctx.planner_task is not None:
            try:
                # shield: a routing timeout leaves the call running for the search plan.
                plan = await asyncio.wait_for(
                    asyncio.shield(ctx.planner_task), timeout=max(0.01, min(PLANNER_LLM_TIMEOUT_S, budget_s))
                )
            except TimeoutError:
                logger.info("Planner model missed the routing budget; routing without it")
            except Exception as exc:  # noqa: BLE001
                logger.info("Planner model call failed: %s", exc)
        ctx.timings_ms["planner_llm"] = round((time.perf_counter() - t2) * 1000, 1)
        if plan is None:
            ctx.planner = "llm_unavailable"
        else:
            ctx.planner = "llm"
            planner_scope = plan.get("scope")
            ctx.intents.update(plan["intents"])
            for ent in _llm_entities(clean_query, plan["entities"], [*genes, *drugs, *diseases, *variants, *stem_entities]):
                if ent.type in ("gene", "drug", "disease"):
                    {"gene": genes, "drug": drugs, "disease": diseases}[ent.type].append(ent)
                else:
                    stem_entities.append(ent)

    if not variants:
        variants = _parser_variants(clean_query)
    if not drugs:
        drugs = _parser_drugs(clean_query)

    attach_variant_genes(clean_query, variants, genes)
    # A variant typed twice ("BCR-ABL1 ... BCR::ABL1") is one entity; the first mention is kept.
    unique: dict[tuple[str | None, str], ResolvedEntity] = {}
    for v in variants:
        unique.setdefault((v.variant_kind, v.label), v)
    variants = list(unique.values())
    followup_gene = _apply_followup(ctx, clean_query, prior_subject, genes, drugs, diseases, variants, stem_entities)
    diseases = drop_generic_diseases(diseases)
    primary = choose_primary_gene(clean_query, genes, variants) or followup_gene
    if primary is None and ctx.biomodel_id and ctx.biomodel_id in BIOMODEL_TARGET_HINTS:
        hint = BIOMODEL_TARGET_HINTS[ctx.biomodel_id]
        symbol = (lookup_symbol(hint) or (hint, "symbol"))[0]
        primary = ResolvedEntity(
            type="gene", mention=hint, label=symbol, source="local_lexicon", matched_on="biomodel_hint", validated=False
        )
        genes.append(primary)
    ctx.primary_gene = primary
    if primary is not None:
        ctx.primary_target = _primary_target_string(primary, variants)
    else:
        # A given value ("m = 2 kg", "k = 50 N/m") is never the subject: without a named system, equation, concept,
        # material or constant the question has no subject.
        lead_stem = next(
            (e for e in stem_entities if e.type in ("equation", "system", "concept", "material", "constant")), None
        )
        ctx.primary_target = (
            ((lead_stem.metadata or {}).get("display_name") or lead_stem.label) if lead_stem is not None else None
        )
    sys_ent = next((e for e in stem_entities if e.type == "system"), None)
    if sys_ent is not None and not ctx.system_name:
        ctx.system_name = sys_ent.label
    apply_standing_instructions(ctx, clean_query, standing_instructions)

    ordered = sorted(genes, key=lambda e: (e.span == (0, 0), e.span[0]))
    ctx.entities = [
        *ordered,
        *sorted(drugs, key=lambda e: e.span[0]),
        *sorted(diseases, key=lambda e: e.span[0]),
        *variants,
        *sorted(stem_entities, key=lambda e: (e.span == (0, 0), e.span[0])),
    ]
    ctx.intents.update(_deterministic_intents(ctx, clean_query))
    ctx.scope = _decide_scope(ctx, clean_query, cands, planner_scope)
    ctx.evidence_need = assess_evidence_need(clean_query, ctx)
    decide_builtin_sources(ctx)
    # Format instructions ("answer in at most 40 words", "exactly two lines") are masked: never search concepts.
    from ..utils.output_contract import mask_instructions

    ctx.search_plan = build_search_plan(ctx, mask_instructions(clean_query))
    if plan is not None:
        ctx.search_plan = merge_llm_plan(ctx.search_plan, plan.get("search"), clean_query)
    return ctx


# A follow-up that points back at the previous subject instead of naming one.
_FOLLOWUP_RE = re.compile(
    r"\b(?:it|its|it's|they|them|their|these|those|the\s+same(?:\s+(?:drug|gene|target|model|disease|equation|system|material|concept|theorem))?|"
    r"(?:the|this|that)\s+(?:drug|gene|target|protein|model|compound|disease|agent|inhibitor|one|mutation|variant|"
    r"alteration|condition|cancer|tumou?r|equation|system|material|concept|theorem|oscillator|pendulum|alloy|fluid))\b"
    r"|^\s*(?:and|also|what\s+about|how\s+about)\b",
    re.I,
)
# Which part of the previous subject a typed referent points to (ORC-004); a generic "it/its/they" points to all.
_REFERENT_KIND_RES = {
    "drug": re.compile(r"\b(?:the|this|that)\s+(?:drug|compound|agent|inhibitor)\b|\bthe\s+same\s+drug\b", re.I),
    "gene": re.compile(r"\b(?:the|this|that)\s+(?:gene|target|protein|mutation|variant|alteration)\b|\bthe\s+same\s+(?:gene|target)\b", re.I),
    "disease": re.compile(r"\b(?:the|this|that)\s+(?:disease|condition|cancer|tumou?r)\b|\bthe\s+same\s+disease\b", re.I),
    "biomodel_id": re.compile(r"\b(?:the|this|that)\s+model\b|\bthe\s+same\s+model\b", re.I),
    "equation": re.compile(r"\b(?:the|this|that)\s+(?:equation|formula|pde|ode)\b|\bthe\s+same\s+equation\b", re.I),
    "system": re.compile(r"\b(?:the|this|that)\s+(?:system|oscillator|pendulum)\b|\bthe\s+same\s+system\b", re.I),
    "material": re.compile(r"\b(?:the|this|that)\s+(?:material|alloy|fluid)\b|\bthe\s+same\s+material\b", re.I),
    "concept": re.compile(r"\b(?:the|this|that)\s+(?:concept|theorem|lemma|identity)\b|\bthe\s+same\s+(?:concept|theorem)\b", re.I),
}
_GENERIC_REFERENT_RE = re.compile(
    r"\b(?:it|its|it's|they|them|their|these|those|the\s+same|(?:the|this|that)\s+one)\b(?!\s+(?:drug|gene|target|model|disease|equation|system|material|concept|theorem))"
    r"|^\s*(?:and|also|what\s+about|how\s+about)\b",
    re.I,
)
# "Is it true that ...", "it is known that ...": an expletive "it", not a reference to anything.
_EXPLETIVE_IT_RE = re.compile(r"\b(?:is|was|isn'?t|wasn'?t)\s+it\s+(?:true|possible|likely|known|the\s+case)\b|\bit\s+(?:is|was|seems|appears)\s+(?:true|possible|likely|known|reported|unclear)\b", re.I)
_FOLLOWUP_RUN_RE = re.compile(r"\b(?:run|re-?run|simulat\w*|repeat|scan|sweep)\b", re.I)
# The subject kinds a follow-up can point back to; the STEM kinds match research_memory.SUBJECT_KEYS.
_STEM_SUBJECT_KEYS = ("concept", "equation", "system", "material", "quantity", "constant")
_SUBJECT_KEYS = (*_STEM_SUBJECT_KEYS, "gene", "drug", "disease", "biomodel_id")


def active_subject(ctx: QueryContext) -> dict[str, str]:
    """This turn's subject ({concept, equation, system, material, quantity, constant, gene, drug, disease,
    biomodel_id}), to store and pass as the next turn's prior_subject. "gene" is set only for a resolved gene
    entity: primary_symbol falls back to a STEM subject's label, which is no gene (LOG-27)."""
    out: dict[str, str] = {}
    for key, group in (("concept", ctx.concepts), ("equation", ctx.equations), ("material", ctx.materials),
                       ("quantity", ctx.quantities), ("constant", ctx.constants)):
        if group:
            out[key] = group[0].label or group[0].mention
    if ctx.systems:
        out["system"] = ctx.systems[0].label or ctx.systems[0].mention
    elif ctx.system_name:
        out["system"] = ctx.system_name
    if ctx.primary_gene is not None and ctx.primary_gene.type == "gene":
        out["gene"] = ctx.primary_gene.label
    if ctx.drugs:
        out["drug"] = ctx.drugs[0].label or ctx.drugs[0].mention
    established = [d for d in ctx.diseases if not (not d.validated and d.matched_on == "planner")]
    if established:
        out["disease"] = established[0].label or established[0].mention
    if ctx.biomodel_id:
        out["biomodel_id"] = ctx.biomodel_id
    return out


def _apply_followup(
    ctx: QueryContext,
    query: str,
    prior: dict[str, str] | None,
    genes: list[ResolvedEntity],
    drugs: list[ResolvedEntity],
    diseases: list[ResolvedEntity],
    variants: list[ResolvedEntity],
    stem_entities: list[ResolvedEntity] | None = None,
) -> ResolvedEntity | None:
    """Resolve 'What about its safety?' or 'Solve it for x=0' to the previous subject. A question naming its own subject keeps it."""
    if not prior or not isinstance(prior, dict):
        return None
    prior = {k: v.strip() for k, v in prior.items() if k in _SUBJECT_KEYS and isinstance(v, str) and v.strip()}
    # A disease in the question is context ("its safety in pancreatic cancer"), not a subject of its own (ORC-004).
    own_subject = (
        bool(genes) or bool(drugs) or bool(variants) or bool(stem_entities) or bool(ctx.biomodel_id) or bool(ctx.attachments)
    )
    text = _EXPLETIVE_IT_RE.sub(" ", query)  # "Is it true that ..." refers to nothing
    specific_drug_referent = bool(_REFERENT_KIND_RES["drug"].search(text))
    specific_gene_referent = bool(_REFERENT_KIND_RES["gene"].search(text))
    # If the question already has its own subject (e.g. genes, drugs, variants) and does NOT explicitly ask for
    # a specific typed referent from the prior turn ('the drug', 'this compound'), do not carry over prior subject.
    if not prior or (own_subject and not ((specific_drug_referent and not drugs) or (specific_gene_referent and not genes))) or not _FOLLOWUP_RE.search(text):
        return None
    # The referent's kind decides which part of the previous subject is meant: "this mutation" is the gene, not the
    # drug; a generic "it/its/they" (or "what about ...") refers to the whole previous subject.
    kinds = {k for k, rx in _REFERENT_KIND_RES.items() if rx.search(text)}
    if not kinds or _GENERIC_REFERENT_RE.search(text):
        kinds |= set(_SUBJECT_KEYS)
    used: dict[str, str] = {}
    gene_entity: ResolvedEntity | None = None
    if prior.get("gene") and "gene" in kinds:
        mention = prior["gene"].split()[0]  # older turns stored "KRAS G12C"; the symbol is the first token
        hit = lookup_symbol(mention)
        symbol = hit[0] if hit else mention
        gene_entity = ResolvedEntity(
            type="gene", mention=mention, label=symbol, source="local_lexicon" if hit else "memory",
            matched_on="followup", validated=False,
        )
        genes.append(gene_entity)
        used["gene"] = prior["gene"]
    if prior.get("drug") and "drug" in kinds:
        drugs.append(ResolvedEntity(type="drug", mention=prior["drug"], label=prior["drug"], source="memory", matched_on="followup"))
        used["drug"] = prior["drug"]
    if prior.get("disease") and "disease" in kinds and not diseases:
        diseases.append(ResolvedEntity(type="disease", mention=prior["disease"], label=prior["disease"], source="memory", matched_on="followup"))
        used["disease"] = prior["disease"]
    if stem_entities is not None:
        for stem_key in ("equation", "system", "material", "concept", "quantity", "constant"):
            if prior.get(stem_key) and stem_key in kinds:
                stem_entities.append(
                    ResolvedEntity(
                        type=cast(EntityType, stem_key),
                        mention=prior[stem_key],
                        label=prior[stem_key],
                        source="memory",
                        matched_on="followup",
                    )
                )
                used[stem_key] = prior[stem_key]
    if (
        prior.get("biomodel_id") and "biomodel_id" in kinds
        and BIOMODEL_ID_RE.match(prior["biomodel_id"].upper()) and _FOLLOWUP_RUN_RE.search(query)
    ):
        ctx.biomodel_id = prior["biomodel_id"].upper()
        apply_simulation_request(ctx, query, model_known=True)
        used["biomodel_id"] = ctx.biomodel_id
    if not used:
        return None
    subject = (
        used.get("drug") or used.get("gene") or used.get("equation") or used.get("system")
        or used.get("material") or used.get("concept") or used.get("quantity") or used.get("constant")
        or used.get("disease") or used.get("biomodel_id", "")
    )
    if "gene" in kinds and "drug" not in kinds:
        subject = used.get("gene") or subject
    ctx.extras["resolved_followup"] = {
        "subject": subject,
        "prior_subject": dict(prior),
        "used": dict(used),
        "query": f"{query} [subject: {', '.join(dict.fromkeys(used.values()))}]",
    }
    return gene_entity


def search_plan_wait_s() -> float:
    try:
        return max(0.0, float(os.getenv("TRIBOS_SEARCH_PLAN_WAIT_S", SEARCH_PLAN_WAIT_S)))
    except ValueError:
        return SEARCH_PLAN_WAIT_S


async def finalize_search_plan(ctx: QueryContext) -> SearchPlan:
    """The search plan, upgraded with the planner model's when it arrives within the search wait; never raises."""
    plan = ctx.search_plan or build_search_plan(ctx, ctx.clean_query)
    task = ctx.planner_task
    if task is None or plan.source == "llm":
        return plan
    remaining = search_plan_wait_s() - (time.perf_counter() - ctx.planner_started)
    try:
        raw = task.result() if task.done() else await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, remaining))
    except TimeoutError:
        logger.info("Planner model missed the search-plan wait; searching with the deterministic plan")
        return plan
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise  # the turn itself was cancelled (client disconnected): stop, don't keep searching
        logger.info("Planner model call was cancelled; searching with the deterministic plan")
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.info("Planner model unavailable for the search plan: %s", type(exc).__name__)
        return plan
    if isinstance(raw, dict):
        ctx.search_plan = plan = merge_llm_plan(plan, raw.get("search"), ctx.clean_query)
    return plan


def cancel_planner(ctx: QueryContext) -> None:
    """Stop a planner call nobody will wait for (the turn ended, or no search needs it)."""
    task = ctx.planner_task
    if task is not None and not task.done():
        task.cancel()


def _decide_scope(ctx: QueryContext, query: str, cands: Candidates, planner_scope: str | None) -> str:
    """Anything concrete in the question makes it research; otherwise the planner's verdict, else the heuristic."""
    concrete = (
        ctx.entities or ctx.biomodel_id or ctx.dataset_path or ctx.attachments
        or ctx.is_simulation_intent or ctx.has_single_cell_intent
    )
    if concrete:
        return "research"
    if planner_scope is not None:
        return planner_scope
    return heuristic_scope(query, cands, set(ctx.intents))


__all__ = [
    "BIOMODEL_TARGET_HINTS",
    "INTENTS",
    "NEGATIVE_SIMULATION_PATTERNS",
    "PROCEDURAL_WORDS",
    "RESOLVER_TOOL",
    "SCOPES",
    "DurationParse",
    "active_subject",
    "apply_simulation_request",
    "attach_variant_genes",
    "build_query_context",
    "build_simulation_plan",
    "choose_primary_gene",
    "decide_builtin_sources",
    "detect_simulation_constraints",
    "detect_simulation_suppression",
    "parse_duration",
    "parse_parameter_overrides",
    "procedural_spans",
    "extract_biomodel_id",
    "extract_candidates",
    "extract_dataset_path",
    "extract_primary_target",
    "finalize_search_plan",
    "cancel_planner",
    "has_single_cell_intent",
    "heuristic_scope",
    "is_small_talk",
    "parse_duration_seconds",
    "parse_variants",
    "plan_with_llm",
    "planner_mode",
]
