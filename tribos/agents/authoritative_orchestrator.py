"""
Authoritative Engineering & Scientific Multi-Agent Orchestrator for Tribos.
Implements:
- Biomni (2025) & ReAct (2022) unified multi-specialist coordination
- LLMCompiler (2023) dependency-aware DAG scheduling with bounded concurrency
- PaperQA2 (2024) grounded literature synthesis via Lithoscribe
- COPASI / BASICO executable kinetic ODE modeling via Vivarix
- CellAgent (2024) single-cell transcriptomics analytics via Lumicell
- Reflexion (2023) deterministic verification and bounded correction
- Mem0 (2025) isolated persistent memory with true BM25 retrieval
- DiscoveryAgent (2024) evidence-backed hypothesis prioritization
"""

from __future__ import annotations

# The inquiry stages live in tribos/agents/orchestration/. They look up the functions imported here through
# this module at call time, so these names stay the patch points tests use (get_llm, get_tool_registry,
# build_citation_map, ...) and stay importable from here; `noqa: F401` marks the ones only the stages use.
import asyncio
import contextlib
import hashlib  # noqa: F401
import json  # noqa: F401
import logging
import os
import re
import time
import uuid  # noqa: F401
from collections import defaultdict  # noqa: F401
from collections.abc import Callable, Coroutine  # noqa: F401
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: F401
from pydantic import BaseModel, Field

from ..agentic import config as agent_config
from ..agentic.budget import RunBudget  # noqa: F401
from ..agentic.control import RunCancelled, RunControl, create_control, release_control
from ..agentic.evidence import render_agent_evidence  # noqa: F401
from ..agentic.guardrails import SPOTLIGHT_RULE  # noqa: F401
from ..agentic.llm import AgentLLM  # noqa: F401
from ..agentic.runtime import AgenticRuntime  # noqa: F401
from ..agentic.state import AgentState  # noqa: F401
from ..datasets.attach import resolve_attachments  # noqa: F401
from ..datasets.provenance import (  # noqa: F401
    postprocess_lumicell_result,
    postprocess_vivarix_result,
)
from ..extensions import load_extensions  # noqa: F401
from ..extensions.hooks import (  # noqa: F401
    get_artifact_builders,
    get_scope_note_providers,
    get_step_augmenters,
)
from ..provenance.run_manifest import RunRecorder, activate_recorder, reset_recorder
from ..sources import EvidenceSource, SourceRunState, get_sources  # noqa: F401
from ..sources.names import INTERNAL_ONLY_KEYS
from ..sources.names import public_name as source_public_name
from ..tools.registry import ErrorType, ToolRegistry, ToolResult, get_tool_registry
from ..utils.llm.llm_factory import (  # noqa: F401
    DEFAULT_ORCHESTRATOR_MODEL,
    astream_with_reasoning,
    get_llm,
    stream_timeout,
)
from ..utils.memory import get_research_memory_engine
from ..utils.memory.research_memory import MemoryContextPackage  # noqa: F401
from ..utils.text import fold_typography
from ..verify.verifier import TribosVerifier, VerificationReport  # noqa: F401
from . import query_planner
from .citations import build_citation_map  # noqa: F401
from .discovery import DiscoveryEngine, DiscoveryHypothesisReport  # noqa: F401
from .orchestration import agent_rounds
from .orchestration import draft as draft_stage
from .orchestration import finalize as finalize_stage
from .orchestration import gather as gather_stage
from .orchestration import plan as plan_stage
from .orchestration import presentation as presentation_stage
from .orchestration import verify as verify_stage
from .orchestration.context import RunContext
from .prompts import (
    CORRECTION_SYSTEM_PROMPT,  # noqa: F401
    build_correction_request,  # noqa: F401
    build_evidence_block,  # noqa: F401
    build_synthesis_request,  # noqa: F401
    build_tool_status_block,  # noqa: F401
    get_synthesis_system_prompt,  # noqa: F401
)
from .query_context import (
    SIM_DURATION_MAX_SECONDS,
    SIM_DURATION_MIN_SECONDS,
    SIM_SCAN_MAX_POINTS,
    SimulationPlan,
    SourceDecision,  # noqa: F401
    TaskOutcome,
    TaskStatus,
)
from .query_planner import build_query_context  # noqa: F401
from .result_keys import (
    AXIOM,
    CALCULA,
    DYNAMIS,
    DYNAMIS_EQUILIBRIUM,
    DYNAMIS_SCAN,
    PHYSIS,
    distinct_results,
)

logger = logging.getLogger(__name__)


class OrchestrationStep(BaseModel):
    agent: str
    role: str = "assistant"
    action: str | None = None
    duration_seconds: float = 0.0


class OrchestrationThought(BaseModel):
    stage: str
    title: str
    text: str
    elapsed_seconds: float = 0.0
    agent: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AuthoritativeOrchestrationResult(BaseModel):
    thread_id: str
    response: str
    thoughts: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    selected_agents: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    model_used: str = DEFAULT_ORCHESTRATOR_MODEL
    framework_used: str = "authoritative-react-compiler"
    verification_report: dict[str, Any] | None = None
    execution_artifacts: dict[str, Any] = Field(default_factory=dict)
    citations: dict[str, Any] = Field(default_factory=dict)
    run_manifest: dict[str, Any] | None = None
    query_context: dict[str, Any] | None = None
    task_status: dict[str, Any] | None = None  # query_context.TaskOutcome; separate from verification

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _make_recorder(**kwargs: Any) -> RunRecorder | None:
    try:
        return RunRecorder(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Run recorder unavailable: %s", exc)
        return None


# Lenticular-bracket citation markers some models emit: 【PMID: 123】, 【42310679】, 【clinical_trials】.
_CITE_MARKER_RE = re.compile(r"\s?【([^】\n]{0,160})】")
_MARKER_ID_RE = re.compile(
    r"\b(?:PMID:?\s*\d{1,9}|10\.\d{4,9}/\S+|NCT\d{8}|CHEMBL\d{1,9}|BIOMD\d{10}|VCV\d{9}|rs\d{3,12}|[EA]ID\d{1,6}|GS[EM]\d{1,9}|ENSG\d{11}|DB\d{5})",
    re.IGNORECASE,
)

# Greetings tolerate stretched or misspelled forms ('heelooo', 'hiii', 'heyy') so they never reach the tools.
_GREETING = (
    r"(?:h+e+l+o+w*|h+a+l+o+|h+i+y*a*|h+e+y+a*|y+o+|s+u+p+|h+o+l+a+|h+o+w+d+y+|greetings|"
    r"good\s*(?:morning|afternoon|evening|day)|help)"
)
_CAPABILITY = (
    r"(?:who\s+are\s+you|what\s+are\s+you|what\s+(?:can|do)\s+you\s+do|how\s+can\s+you\s+help|"
    r"what\s+(?:are\s+your\s+capabilities|is\s+this(?:\s+app)?)|introduce\s+yourself|tell\s+me\s+about\s+yourself)"
    r"(?:\s+(?:(?:for|to)\s+)?(?:m+e+|u+s+))?(?:\s+(?:here|exactly|then))?"
)
_CASUAL_RES = [
    re.compile(rf"^{_GREETING}(?:\s+(?:there|all|everyone|team|tribos))?[\s\.\?!,~:)]*$", re.I),
    # Greeting plus small talk only: anything after it ("Hi, how are you? What are the phase 3 results for
    # sotorasib", "Hello, help me evaluate EGFR") is a real question and goes to the planner.
    re.compile(
        rf"^{_GREETING}[\s,!\.]+(?:{_CAPABILITY}|how\s+are\s+(?:you|u)(?:\s+doing)?(?:\s+today)?|help(?:\s+me)?)[\s\.\?!,~:)]*$",
        re.I,
    ),
    re.compile(rf"^(?:so\s+|and\s+|ok\s+|okay\s+)?{_CAPABILITY}[\s\.\?!,~:)]*$", re.I),
]


_INTRODUCTION = (
    "Hello! I am **Tribos**, your verified Engineering, Mathematics & Scientific R&D AI assistant.\n\n"
    "I provide publication-grade scientific research, computer algebra, and simulation capabilities:\n"
    "- **📚 Archivon**: Grounded literature synthesis across arXiv, Crossref, Semantic Scholar, OpenAlex, and zbMATH Open\n"
    "- **📐 Axiom**: Computer algebra and symbolic mathematics with SymPy: equation solving, calculus, ODE dsolve, linear algebra, and identity proofs\n"
    "- **⚙️ Dynamis**: Numerical ODE simulation, parameter scans, fixed-point stability, optimization, and curve fitting with SciPy\n"
    "- **💻 Calcula**: Sandboxed scientific Python computation and dataset analysis (NumPy, SciPy, SymPy, Pandas, Pint, Matplotlib)\n"
    "- **🔬 Physis**: Physical constants (CODATA 2022), Pint unit conversions and dimensional checks, OEIS integer sequences, Materials Project, and WolframAlpha\n"
    "- **🔍 Reflexion Verifier**: Mathematical and citation auditing preventing ungrounded claims\n\n"
    "Answers carry clickable citations and can be exported as a DOCX or PDF report with a run manifest, "
    "then re-run to compare.\n\n"
    "To get started, please ask a question about mathematics, physics, engineering, or scientific computing!"
)

_EXAMPLE_QUESTIONS = (
    "- *Solve the differential equation dy/dx + 2*y = exp(-x) with y(0) = 1.*\n"
    "- *Simulate the harmonic oscillator for 20 seconds.*\n"
    "- *What is the fine-structure constant and its CODATA 2022 uncertainty?*"
)
_THANKS_RE = re.compile(r"\b(?:thanks?|thx|ty|cheers|appreciate)\b", re.I)
_FAREWELL_RE = re.compile(r"\b(?:bye|goodbye|see\s+(?:you|ya)|good\s*night)\b", re.I)


# The Lumo Admission Gate's answer to a self-referential query (agents/context_gate.py): it has no grounding context (K = 0).
PARADOX_REPLY = (
    "This statement refers only to itself, so no fact can confirm or refute it: under the Lumo Admission Gate it has context "
    "K = 0 (neither true nor false), and nothing was looked up or computed. Ask about the claim it is meant to "
    "test, or about the paradox itself (for example \"Why is the liar paradox neither true nor false?\")."
)


def _non_research_reply(query: str, scope: str) -> str:
    """A fixed reply for a message that is not a research question. Nothing is looked up, so nothing is claimed."""
    if scope == "paradox":
        return PARADOX_REPLY
    if scope == "conversational":
        if _THANKS_RE.search(query):
            return "You're welcome! Ask me about an equation, simulation, physical constant, proof or dataset whenever you're ready."
        if _FAREWELL_RE.search(query):
            return "Goodbye! Your conversation stays here when you come back."
        return _INTRODUCTION
    shown = " ".join(query.split())
    shown = shown if len(shown) <= 80 else shown[:77] + "..."
    shown = re.sub(r"([\\`*_\[\]<>])", r"\\\1", shown)
    return (
        f"I couldn't find a scientific or engineering question in “{shown}”, so I didn't search any sources.\n\n"
        "Ask about an equation, a physical constant, a dynamical system, a mathematical proof or computation, or attach a dataset. "
        f"For example:\n{_EXAMPLE_QUESTIONS}"
    )


_TRANSIENT_STREAM_ERRORS = ("ReadError", "RemoteProtocolError", "APIConnectionError", "ConnectError", "ReadTimeout",
                            "APITimeoutError", "InternalServerError")


async def stream_buffered_with_retry(llm: Any, messages: list[Any], parts: list[str], *, on_reasoning: Any = None,
                                     attempts: int = 2, before_retry: Callable[[int], None] | None = None,
                                     timeout_s: float | None = None) -> tuple[str, str]:
    """A buffered (not shown live) completion, retried once from scratch when the connection drops mid-stream
    ("ReadError"): the buffer is cleared, so nothing partial or duplicated is kept.

    before_retry(attempt) runs before each retry: a retry is another provider call, so an agentic caller settles
    the dropped call and admits the retry there (it raises BudgetExhausted when the retry cannot be afforded).
    timeout_s bounds each stream by the run's remaining time (None: STREAM_TOTAL_TIMEOUT); the retry's pause and
    attempt never extend past it."""
    t_end = None if timeout_s is None else time.perf_counter() + max(0.0, timeout_s)
    for i in range(attempts):
        parts.clear()

        async def buffer(delta: str) -> None:
            parts.append(delta)

        kwargs: dict[str, Any] = {}
        if t_end is not None:
            kwargs["total_timeout"] = stream_timeout(max(0.0, t_end - time.perf_counter()))
        try:
            return await astream_with_reasoning(llm, messages, on_reasoning=on_reasoning, on_text=buffer, **kwargs)
        except Exception as exc:  # noqa: BLE001
            from ..utils.llm.provider_retry import already_retried

            if i + 1 >= attempts or type(exc).__name__ not in _TRANSIENT_STREAM_ERRORS or already_retried(llm, exc):
                raise  # a status error the transport already retried is not sent again here (audit I26)
            if t_end is not None and t_end - time.perf_counter() <= 2.0:
                raise  # no time left in the run for a second attempt
            if before_retry is not None:
                before_retry(i + 1)
            logger.warning("Model stream dropped (%s); retrying once", type(exc).__name__)
            await asyncio.sleep(2.0)
    return "", ""


def _edit_llm_kwargs(model_name: str) -> dict[str, Any]:
    """Rewrites and revisions edit an existing draft: the model's long reasoning pass adds minutes (a revision hit
    the 600 s stream cap) without improving an edit. The first draft keeps its reasoning."""
    from ..agentic.llm import agent_model_kwargs

    return agent_model_kwargs(model_name)


LONG_QUERY_CHARS = 240
# What each kind of question is looking for in the literature, added to the subject terms.
_QUERY_TYPE_TERMS = {
    "derivation": "analytical solution", "proof": "proof", "numerical": "numerical method",
    "modelling": "model", "design_sizing": "design", "conceptual": "theory", "literature_review": "review",
}


def literature_subject(clean_query: str) -> str:
    """The question without what only says how to answer: output-format instructions ("answer in at most 40 words",
    "exactly two lines"), output-instruction sentences, and case assignments ("Case A: n = 40"). Searching those words
    finds papers that share them ("independent cases" -> court cases), not papers on the subject."""
    from ..agentic.decompose import strip_output_instructions
    from ..utils.output_contract import mask_instructions

    text, _removed = strip_output_instructions(mask_instructions(clean_query or ""))
    text = re.sub(r"(?i)\b(?:case\s+)?[A-Z0-9]{1,3}\s*[:)]\s*[A-Za-z]\w*\s*=\s*[-+]?\d[\d./]*\.?", " ", text)
    text = re.sub(r"(?i)\b(?:keep\s+each\s+\w+\s+local[^.]*|give\s+a\s+rigorous\s+[^.]*)\.?", " ", text)
    return re.sub(r"\s+", " ", text).strip() or (clean_query or "").strip()


def literature_query(ctx: Any, clean_query: str, plan: Any = None) -> str:
    """The literature search text. A short question is searched by its subject as written; a long one (a whole
    worked problem with its given values and instructions) by its subject terms, since keyword search over a paragraph
    of instructions returns off-topic papers."""
    subject = literature_subject(clean_query)
    if len(subject) <= LONG_QUERY_CHARS:
        return subject
    terms = list(ctx.focus_terms()[:3]) if hasattr(ctx, "focus_terms") else []
    kind = str(getattr(plan, "question_type", None) or getattr(getattr(ctx, "search_plan", None), "question_type", "") or "")
    hint = _QUERY_TYPE_TERMS.get(kind)
    if terms and hint:
        terms.append(hint)
    if terms:
        return " ".join(dict.fromkeys(terms))
    # The planned keyword query, else the first sentence without its list number ("1. How many primes ...": the first
    # "sentence" of a numbered task list is "1.", which searched the literature for the digit 1).
    web = str(getattr(plan if plan is not None else getattr(ctx, "search_plan", None), "web_query", "") or "").strip()
    if web:
        return " ".join(dict.fromkeys([web, *([hint] if hint else [])]))
    subject = re.sub(r"(?:^|(?<=[.?!:]\s))\(?\d{1,2}[.)]\s+", "", subject)
    first_sentence = re.split(r"(?<=[.?!])\s+", subject, maxsplit=1)[0]
    return first_sentence[:LONG_QUERY_CHARS]


def literature_request(ctx: Any, clean_query: str, plan: Any = None) -> dict[str, Any]:
    """Arguments of the Archivon call for a question (shared with the evaluation harness, so both search alike)."""
    from ..agentic.config import get_effort_profile

    effort_level = getattr(ctx, "effort_level", None) or "medium"
    profile = get_effort_profile(effort_level)
    max_articles = profile.get("max_passages", 8)

    req: dict[str, Any] = {
        "query": literature_query(ctx, clean_query, plan),
        "max_results": max_articles,
        "max_articles": max_articles,
    }
    # The planned scholarly searches and ranking words (Archivon runs up to two of the queries besides `query`).
    search_plan = plan if plan is not None else getattr(ctx, "search_plan", None)
    if search_plan is not None:
        try:
            queries = search_plan.scholarly_queries()
            keywords = search_plan.keywords()
        except Exception as exc:  # noqa: BLE001 - a malformed plan never blocks the search itself
            logger.debug("Search plan unusable for the literature request: %s", exc)
            queries, keywords = [], []
        if queries:
            req["search_queries"] = queries[:10]
        if keywords:
            req["keywords"] = keywords[:30]
    # Identifiers the question names (arXiv, DOI, zbMATH, ...) are fetched first, whatever the ranking.
    pinned = _question_identifiers(ctx)
    if pinned:
        req["pinned_ids"] = pinned[:20]
    return req


def _question_identifiers(ctx: Any) -> list[str]:
    """"arXiv:2312.04511", "DOI:10.1103/physrevlett.1", "Zbl 1234.56789": literature identifiers written in the question."""
    text = str(getattr(ctx, "clean_query", "") or "")
    out = [f"arXiv:{m.group(1)}" for m in _ARXIV_ID_RE.finditer(text)]
    out += [f"DOI:{m.group(0).rstrip('.,;)')}" for m in _DOI_RE.finditer(text)]
    out += [f"Zbl {m.group(1)}" for m in _ZBL_RE.finditer(text)]
    return list(dict.fromkeys(out))


_ARXIV_ID_RE = re.compile(r"\barxiv\s*:?\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
_ZBL_RE = re.compile(r"\bZbl\s*:?\s*(\d{4}\.\d{5})", re.IGNORECASE)


def _show_reasoning() -> bool:
    """Raw model reasoning is kept server-side unless TRIBOS_SHOW_REASONING is set: it is not checked by the verifier."""
    return os.getenv("TRIBOS_SHOW_REASONING", "").strip().lower() in ("1", "true", "yes", "on")


def _cite_marker(m: re.Match[str]) -> str:
    """Keep the identifiers of a bracket marker as a plain parenthetical citation; drop markers naming evidence tags."""
    inner = m.group(1).strip()
    ids = [i.group(0) for i in _MARKER_ID_RE.finditer(inner)]
    if not ids and re.fullmatch(r"\d{6,9}", inner):
        ids = [f"PMID: {inner}"]  # a bare PMID-length number inside a marker
    if not ids:
        return ""
    ids = ["PMID: " + re.sub(r"\D", "", i) if i.upper().startswith("PMID") else i for i in ids]
    return f" ({'; '.join(dict.fromkeys(ids))})"


# Internal source keys the model sometimes copies into the answer as a parenthetical "citation": their public
# names (from the shared SOURCE_REGISTRY), or None to drop the parenthetical (it names a pipeline step, not a source
# the reader can check). Only these keys are rewritten; other source keys in parentheses are left as written.
_INTERNAL_SOURCE_KEYS = (
    "archivon", "dynamis", "physis", "axiom", "calcula", "websurfer", "lithoscribe", "vivarix",
    "structure_intel", "structintel", "clinical_trials", "clinicaltrials", "synapta", "lumicell", "disease_targets",
)
_INTERNAL_SOURCE_NAMES: dict[str, str | None] = {
    **{k: source_public_name(k) for k in _INTERNAL_SOURCE_KEYS},
    **dict.fromkeys(INTERNAL_ONLY_KEYS),
}
# Evidence attribute keys and how a value reads in prose ("total_reports = 1454" -> "1,454 FAERS reports").
_FIELD_PROSE = {
    "total_reports": "{} FAERS reports",
    "serious_reports": "{} serious reports",
    "reports_listing_death": "{} reports listing death",
    "application_number": "application number {}",
    "overall_score": "overall score {}",
}
_FIELD_VALUE_RE = re.compile(
    r"\b(" + "|".join(_FIELD_PROSE) + r")\b(?:\s*[=:]\s*|\s+)((?:[A-Z]{1,4})?\d+(?:[.,]\d+)*)\b"
)
_FIELD_BARE_RE = re.compile(r"\b(" + "|".join(_FIELD_PROSE) + r"|structure_intel|clinical_trials)\b")
_PAREN_RE = re.compile(r"[ \t]*\(([^()\n]{1,80})\)")
# Internal evidence keys of agent steps ("agent.plan_execute.4.structure", "agent.gaps.9-12 lithoscribe"): with
# their parentheses or brackets, a lead-in like "evidence:", and list separators, they are removed from the answer.
_STEP_KEY = (
    r"agent\.[a-z_]+(?:\.[\w-]+)+"
    r"(?:\s+(?:archivon|dynamis|physis|axiom|calcula|lithoscribe|synapta|vivarix|lumicell|chembl|openfda|primekg|"
    r"structure|websurfer|dgidb|pharos|"
    r"bindingdb|pubtator|synlethdb|clinical_trials|trials|variants|gwas|gtex|string_ppi|reactome|pubchem))?"
)
_STEP_KEY_RE = re.compile(
    rf"[ \t]*[(\[](?:(?:evidence|source|see)\s*:?\s*)?{_STEP_KEY}(?:\s*[,;]\s*{_STEP_KEY})*[)\]]"
    rf"|(?:\b(?:evidence|source)\s*:\s*)?\b{_STEP_KEY}(?:\s*[,;]\s*{_STEP_KEY})*",
    re.IGNORECASE,
)
# "the Discovery evidence-weighted ranking", "Discovery ranking": an internal component named in prose.
_BIODISCOVERY_RE = re.compile(r"\b(?:the\s+)?Discovery(?:'s)?(?:\s+(?:evidence-weighted\s+)?(?:ranking|score))?(?![\w-])", re.IGNORECASE)
# A bracketed tag that is not a Markdown link or checkbox: "[Synapta]", "[Lithoscribe; PMID: 1]".
_BRACKET_RE = re.compile(r"[ \t]*\[([^\[\]\n]{2,80})\](?!\()")
_SNAKE_KEY_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
# Typographic spaces and hyphens the model writes ("et al.", "on‑target"): shown as plain characters so the
# answer reads the same everywhere and a flagged claim's sentence can be found again in it (claim removal). The table
# is shared with the verifier (tribos.utils.text.fold_typography), so both sides fold the same characters.


def normalize_typography(text: str) -> str:
    return fold_typography(text) if text else text


# Code, URLs and Markdown link targets are left exactly as written.
_PROTECTED_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://[^\s)>\]]+|\]\([^)\s]*\)", re.S)


def _field_prose(m: re.Match[str]) -> str:
    value = m.group(2)
    if value.isdigit() and len(value) > 3:
        value = f"{int(value):,}"
    return _FIELD_PROSE[m.group(1)].format(value)


def _public_paren(m: re.Match[str]) -> str:
    """A parenthetical naming internal source keys, rewritten with public names (or dropped); others unchanged."""
    items = [i.strip() for i in re.split(r"[;,]", m.group(1))]
    keys = [re.sub(r"[\s\-]+", "_", i.lower()) for i in items]
    # A bare snake_case token ("hypothesis_experiments", "tool_status") is an evidence key, never prose.
    snake = [bool(_SNAKE_KEY_RE.fullmatch(i)) for i in items]
    if not any(k in _INTERNAL_SOURCE_NAMES for k in keys) and not any(snake):
        return m.group(0)
    kept = [
        _INTERNAL_SOURCE_NAMES[k] if k in _INTERNAL_SOURCE_NAMES else ("" if is_key else i)
        for i, k, is_key in zip(items, keys, snake, strict=False)
    ]
    kept = list(dict.fromkeys(k for k in kept if k))
    lead = m.group(0)[: m.start(1) - m.start(0) - 1]
    return f"{lead}({'; '.join(kept)})" if kept else ""


def _bare_key(m: re.Match[str]) -> str:
    key = m.group(1)
    return _INTERNAL_SOURCE_NAMES.get(key) or key.replace("_", " ")


# Data field names and enum values of the SynLethDB/DGIdb druggable-partner evidence ("druggable_partners",
# "fda_status = not_checked", "interaction_class: untyped") the model sometimes copies into prose: a safety net
# behind the evidence wording, so the reader sees plain words. Applied before the parenthetical rules, so
# "(fda_status = not_checked)" keeps its parentheses as "(FDA status not checked)".
_FDA_STATUS_PROSE = {
    "not_checked": "FDA status not checked",
    "approved": "FDA-approved",
    "not_approved": "not FDA-approved",
    "error": "FDA status lookup failed",
    "unknown": "FDA status unknown",
    "not_found": "no FDA approval record found",
}
_INTERACTION_CLASS_PROSE = {
    "inhibits": "inhibitor-type interaction",
    "other": "interaction of another type",
    "untyped": "interaction type not specified",
}
_DRUGGABLE_PARTNER_DATA = "SynLethDB/DGIdb druggable-partner data"
_DATA_FIELD_RULES: tuple[tuple[re.Pattern[str], Any], ...] = (
    (
        re.compile(r"\bfda_status\s*(?:=|:|is)\s*[\"'“”]?([a-z_]+)[\"'“”]?", re.IGNORECASE),
        lambda m: _FDA_STATUS_PROSE.get(m.group(1).lower(), f"FDA status {m.group(1).replace('_', ' ')}"),
    ),
    (
        re.compile(r"\binteraction_class\s*(?:=|:|is)\s*[\"'“”]?([a-z_]+)[\"'“”]?", re.IGNORECASE),
        lambda m: _INTERACTION_CLASS_PROSE.get(m.group(1).lower(), f"interaction type {m.group(1).replace('_', ' ')}"),
    ),
    # "druggable_partners table", "the druggable_partners list": the data, named by its sources.
    (re.compile(r"\bdruggable_partners?(?:\s+(?:table|list|data|field|rows?|section|array|entries|output))?\b", re.IGNORECASE),
     lambda m: _DRUGGABLE_PARTNER_DATA),
    (re.compile(r"\bdruggable_lookup\b", re.IGNORECASE), lambda m: "druggable-partner lookup"),
    (re.compile(r"\bpartners_not_checked\b", re.IGNORECASE), lambda m: "partners not checked"),
    (re.compile(r"\bfda_status\b", re.IGNORECASE), lambda m: "FDA status"),
    (re.compile(r"\binteraction_class\b", re.IGNORECASE), lambda m: "interaction type"),
    (re.compile(r"\bnot_checked\b", re.IGNORECASE), lambda m: "not checked"),
    # "an untyped DGIdb interaction" / "untyped interactions": the interaction type is simply not given.
    (re.compile(r"\b(an?\s+)?untyped\s+((?:DGIdb\s+)?)(drug[- ]gene\s+)?interactions?\b", re.IGNORECASE),
     lambda m: (("a " if m.group(2) or m.group(3) else "an ") if m.group(1) else "")
     + f"{m.group(2) or ''}{m.group(3) or ''}{m.group(0).rsplit(None, 1)[-1]} of unspecified type"),
    (re.compile(r"\((?:class\s*[:=]?\s*)?untyped\)", re.IGNORECASE), lambda m: "(type not specified)"),
)


def _clean_data_fields(segment: str) -> str:
    for pattern, repl in _DATA_FIELD_RULES:
        segment = pattern.sub(repl, segment)
    return segment


# The tags the evidence block wraps documents in (agentic/evidence.py, agentic/guardrails.py spotlight,
# agentic/analyst.py, agentic/math_agent.py, agents/prompts.py). A model sometimes copies them into the answer, raw, entity-escaped
# ("&lt;untrusted_data source=...&gt;") or in a code span; they are markup for the model, never prose.
_EVIDENCE_TAGS = (
    "agent_evidence", "untrusted_data", "tool_output", "document", "sandbox_analysis",
    "math_agent", "math_problem", "math_answer", "math_answer_latex", "math_checks", "math_check", "math_uncertainty", "math_steps",
)
_EVIDENCE_TAG_RE = re.compile(
    r"`?(?:<|&lt;|&#60;|&#x3c;)\s*/?\s*(?:" + "|".join(_EVIDENCE_TAGS) + r")\b"
    r"(?:\s+[a-z_][\w\-]*\s*=\s*(?:\"[^\"<>\n]*\"|'[^'<>\n]*'|&quot;.*?&quot;|[^\s<>&`]+))*"
    r"\s*/?\s*(?:>|&gt;|&#62;|&#x3e;)`?",
    re.IGNORECASE,
)
# A pointer to one of the evidence block's own sections: "(see `<literature_limitations>`)", "`<tool_status>`".
# Only snake_case tag names: those are the prompt's internal sections, never prose or real markup.
_INTERNAL_TAG_REF_RE = re.compile(
    r"\s*\((?:see|in|per|from|cf\.?)\s+`?(?:<|&lt;)/?[a-z]+(?:_[a-z]+)+(?:>|&gt;)`?\)"
    r"|`(?:<|&lt;)/?[a-z]+(?:_[a-z]+)+(?:>|&gt;)`"
)
# An attribute the model copied without its tag ("key=\"\"", "pmid=\"\" doi=\"\"") says nothing.
_EMPTY_ATTR_RE = re.compile(r"(?<![\w\-])(?:key|pmid|doi|tool|phase|purpose|source)\s*=\s*(?:\"\"|''|&quot;&quot;)", re.IGNORECASE)


def strip_evidence_markup(text: str) -> str:
    """The answer without the evidence block's tags (the prose inside them is kept), references to the evidence
    block's own sections ("(see `<literature_limitations>`)") or empty copied attributes."""
    if not text or not (
        any(t in text.lower() for t in (*_EVIDENCE_TAGS, '=""', "=''", "=&quot;&quot;")) or _INTERNAL_TAG_REF_RE.search(text)
    ):
        return text
    out = _INTERNAL_TAG_REF_RE.sub("", text)
    out = _EVIDENCE_TAG_RE.sub("", out)
    out = _EMPTY_ATTR_RE.sub("", out)
    out = re.sub(r"[ \t]{2,}(?=\S)", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def clean_internal_keys(text: str) -> str:
    """Rewrite evidence field names and internal source keys the model copied into the answer as plain prose.

    "total_reports = 1454" becomes "1,454 FAERS reports", "(clinical_trials)" becomes "(ClinicalTrials.gov)" and
    "(tool_status note)" is removed. Code spans, URLs and link targets are untouched; identifiers (NCT, PMID,
    CHEMBL) never match the patterns.
    """
    if not text:
        return text

    def clean(segment: str) -> str:
        segment = _FIELD_VALUE_RE.sub(_field_prose, segment)
        segment = _PAREN_RE.sub(_public_paren, segment)
        segment = _BRACKET_RE.sub(_public_paren, segment)  # "[Synapta]" citation-style tags
        segment = _BIODISCOVERY_RE.sub("the evidence-weighted ranking", segment)
        segment, removed = _STEP_KEY_RE.subn("", segment)  # "(agent.gaps.9.lithoscribe)", "evidence: agent.swarm.2.chembl"
        if removed:
            segment = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", segment)  # the gap a removed key left (not "  \n" breaks)
        return _FIELD_BARE_RE.sub(_bare_key, segment)

    out: list[str] = []
    pos = 0
    for m in _PROTECTED_RE.finditer(text):
        out.append(clean(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(clean(text[pos:]))
    return "".join(out)


class AuthoritativeOrchestrator:
    """
    Authoritative Orchestrator coordinating Archivon, WebSurfer, Physis, Axiom, Calcula and Dynamis with genuine
    tool execution and verification.
    """

    def __init__(self) -> None:
        try:
            from ..dynamis.engine import DynamisEngine
            self.dynamis = DynamisEngine()
        except ImportError:
            self.dynamis = None
        self.verifier = TribosVerifier()
        self.memory = get_research_memory_engine()

    @property
    def registry(self) -> ToolRegistry:
        return get_tool_registry()

    # Query parsing lives in query_planner; these wrappers keep the historical entry points.
    @staticmethod
    def _extract_primary_target(query: str) -> str | None:
        return query_planner.extract_primary_target(query)

    _NEGATIVE_SIMULATION_PATTERNS = query_planner.NEGATIVE_SIMULATION_PATTERNS

    @classmethod
    def _detect_simulation_suppression(cls, query: str) -> bool:
        """Return True when the user explicitly asked not to run simulations."""
        return query_planner.detect_simulation_suppression(query)

    @staticmethod
    def _extract_dataset_path(query: str) -> str | None:
        """Extract a referenced single-cell dataset file (.h5ad / .zarr) from the query."""
        return query_planner.extract_dataset_path(query)

    @staticmethod
    def _has_single_cell_intent(query: str) -> bool:
        return query_planner.has_single_cell_intent(query)

    @staticmethod
    def _sanitize_agent_names(text: str) -> str:
        """Strip internal platform names and enforce official designations."""
        # Only internal agent identifiers: bare words such as "S2" (spike S2 subunit) or "SCP" are science.
        # ORC-005: organisation and product names (OpenAI, NVIDIA, LangGraph) are never rewritten: they occur in
        # the literature ("GPT-4 from OpenAI", "NVIDIA BioNeMo"), and rewriting them falsifies cited statements.
        # Provider non-disclosure is the system prompt's job, not a filter over scientific prose.
        replacements = [
            ("t2kg_agent", "Synapta"),
            ("t2kg", "Synapta"),
            ("t2b_agent", "Vivarix"),
            ("t2b", "Vivarix"),
            ("scp_agent", "Lumicell"),
            ("s2_agent", "Lithoscribe"),
            ("t2s_agent", "Lithoscribe"),
        ]
        out = text
        for old, new in replacements:
            out = re.sub(rf"\b{old}\b", new, out, flags=re.IGNORECASE)

        # Strip robotic compliance disclaimers
        out = re.sub(r"(?im)^\s*All agent references follow the official naming convention:.*$", "", out)
        out = re.sub(r"(?im)^\s*Note: All agent references adhere to.*$", "", out)
        out = _CITE_MARKER_RE.sub(_cite_marker, out)
        return out.strip()

    @classmethod
    def _sanitize_answer(cls, text: str) -> str:
        """Answer text: internal names stripped, copied evidence keys rewritten as plain prose and the evidence
        block's own markup (<agent_evidence>, <untrusted_data>, <tool_output>, ...) removed."""
        return clean_internal_keys(cls._sanitize_agent_names(strip_evidence_markup(normalize_typography(text))))

    # Progress labels for each tool step while it runs; the finished label comes from _describe_tool_result.
    _RUNNING_TITLES = {
        "synapta": "Looking up {target} in OpenTargets and KEGG",
        "archivon": "Searching arXiv, Crossref, and OpenAlex",
        "lithoscribe": "Searching scientific literature",
        "websurfer": "Searching the web",
        "dynamis": "Simulating ODE model in Dynamis",
        "dynamis_simulate_ode": "Simulating ODE model in Dynamis",
        "dynamis_parameter_scan": "Scanning parameter in Dynamis",
        "dynamis_equilibrium": "Finding equilibrium points in Dynamis",
        "dynamis_scan": "Scanning parameter in Dynamis",
        "vivarix": "Simulating {model}",
        "vivarix_steady_state": "Solving for steady state",
        "vivarix_scan": "Scanning parameter",
        "calcula": "Running sandboxed scientific computation",
        "calcula_run_python": "Running sandboxed scientific computation",
        "physis": "Looking up physical reference data",
        "axiom": "Computing symbolic derivation in Axiom",
        "lumicell": "Analyzing {dataset}",
    }

    @staticmethod
    def _describe_tool_result(name: str, res: ToolResult, ctx: dict[str, Any]) -> tuple[str, str]:
        """Summarize what a tool actually returned, as (title, detail) for the activity timeline."""
        if not res.success:
            err_type = getattr(res.error_type, "value", res.error_type) or "ERROR"
            labels = {
                "synapta": f"OpenTargets/KEGG lookup for {ctx.get('target')} failed",
                "archivon": "Literature search failed",
                "lithoscribe": "Literature search failed",
                "websurfer": "Web search failed",
                "dynamis": f"Simulation of {ctx.get('model')} failed",
                "dynamis_simulate_ode": "ODE simulation failed",
                "dynamis_parameter_scan": "Parameter scan failed",
                "dynamis_scan": f"Parameter scan of {ctx.get('model')} failed",
                "dynamis_equilibrium": "Equilibrium solve failed",
                "vivarix": f"Simulation of {ctx.get('model')} failed",
                "vivarix_steady_state": "Steady-state solve failed",
                "vivarix_scan": f"Parameter scan of {ctx.get('model')} failed",
                "calcula": "Calculation failed",
                "calcula_run_python": "Sandboxed computation failed",
                "physis": "Reference lookup failed",
                "axiom": "Derivation failed",
                "lumicell": f"Analysis of {ctx.get('dataset')} failed",
            }
            return labels.get(name, f"{name} failed"), f"{err_type}: {(res.error or '')[:240]}"

        data: dict[str, Any] = res.data if isinstance(res.data, dict) else {}
        parts: list[str] = []
        if name == "synapta":
            coverage = data.get("coverage") or {}
            status = coverage.get("status")
            title = (
                f"Looked up {ctx.get('target')} in OpenTargets and KEGG"
                + (" (partial)" if status == "partial" else " (nothing found)" if status == "success_empty" else "")
            )
            if res.canonical_ids.get("ensembl_id"):
                parts.append(res.canonical_ids["ensembl_id"])
            assocs = data.get("associations") or []
            parts.append(f"{len(assocs)} disease association{'s' if len(assocs) != 1 else ''}")
            parts.append(f"{len(data.get('pathways') or [])} KEGG pathways")
            if assocs and assocs[0].get("disease_name"):
                parts.append(f"top: {assocs[0]['disease_name']}")
            failed = [k for k, v in (coverage.get("sources") or {}).items() if isinstance(v, dict) and v.get("status") == "error"]
            if failed:
                parts.append(f"failed: {', '.join(failed)}")
        elif name in ("archivon", "lithoscribe"):
            passages = data.get("ranked_passages") or data.get("passages") or []
            title = f"Found {len(passages)} relevant literature passage{'s' if len(passages) != 1 else ''}"
            labels = [
                str(p.get("citation") or p.get("citation_label") or (f"PMID {p['pmid']}" if p.get("pmid") else (f"arXiv:{p['arxiv_id']}" if p.get("arxiv_id") else "")))
                for p in passages[:3]
                if isinstance(p, dict)
            ]
            labels = list(dict.fromkeys(label for label in labels if label))
            if labels:
                parts.append("; ".join(labels))
        elif name == "websurfer":
            results = data.get("results") or []
            title = f"Found {len(results)} web result{'s' if len(results) != 1 else ''}"
            titles = [str(r.get("title")) for r in results[:3] if isinstance(r, dict) and r.get("title")]
            if titles:
                parts.append("; ".join(titles))
        elif name in ("dynamis", "dynamis_simulate_ode", "vivarix"):
            title = f"Simulated {data.get('model_name') or data.get('model_id') or ctx.get('model') or 'model'}"
            if data.get("model_name"):
                parts.append(str(data["model_name"]))
            if data.get("species_list"):
                parts.append(f"{len(data.get('species_list'))} species")
            units = data.get('units')
            time_unit = units.get('time', 's') if isinstance(units, dict) else 's'
            if data.get('duration'):
                parts.append(f"t = {data.get('duration')}{time_unit}")
            elif data.get('t_span'):
                parts.append(f"t = {data.get('t_span')}")
            if data.get("verified"):
                parts.append("verified numerical solution")
        elif name in (DYNAMIS_EQUILIBRIUM, "vivarix_steady_state"):
            title = f"Equilibrium: {str(data.get('stability') or data.get('steady_state_status') or 'computed').replace('_', ' ')}"
            if data.get("fixed_point"):
                parts.append(", ".join(f"{k} = {v:.4g}" if isinstance(v, (int, float)) else f"{k} = {v}"
                                       for k, v in list(data["fixed_point"].items())[:4]))
            if data.get("converged") is False:
                parts.append("did not converge")
        elif name in (DYNAMIS_SCAN, "dynamis_parameter_scan", "vivarix_scan"):
            n_ok = int(data.get("successful_points") or len(data.get("scan_results") or []) or 0)
            n_all = int(data.get("total_points") or len(data.get("scan_results") or []) or 0)
            title = f"Scanned {data.get('resolved_parameter') or data.get('parameter') or data.get('parameter_name') or 'parameter'} over {n_all} point{'s' if n_all != 1 else ''}"
            req = data.get("requested")
            req_d = req if isinstance(req, dict) else {}
            if req_d.get("start") is not None and req_d.get("end") is not None:
                parts.append(f"{req_d.get('start')} → {req_d.get('end')} ({req_d.get('spacing', 'linear')})")
            if data.get("duration_seconds"):
                parts.append(f"t = {data.get('duration_seconds')} s per point")
            parts.append(f"{n_ok} succeeded" + (f", {n_all - n_ok} failed" if n_all - n_ok else ""))
        elif name in (CALCULA, "calcula_run_python"):
            if "n_rows" in data or "datasets" in data or "variables" in data:
                title = f"Inspected dataset {data.get('name') or data.get('dataset_id') or ''}".strip()
            else:
                title = "Executed sandboxed scientific computation"
            shown = data.get("result") if data.get("result") is not None else (data.get("stdout") or data.get("output"))
            if shown is not None and str(shown).strip():
                parts.append(str(shown)[:100].strip())
        elif name in (PHYSIS, "physis_constants"):
            title = "Looked up physical reference data"
            if data.get("constants"):
                parts.append(f"{len(data['constants'])} constants retrieved")
            elif data.get("materials"):
                parts.append(f"{len(data['materials'])} materials retrieved")
        elif name == AXIOM:
            status = str(data.get("status") or "computed").replace("_", " ")
            title = f"Solved symbolically ({status})"
            answer = data.get("answer") if isinstance(data.get("answer"), dict) else {}
            if answer.get("text"):
                parts.append(str(answer["text"])[:120])
        elif name == "lumicell":
            title = f"Analyzed {data.get('dataset_name') or ctx.get('dataset')}"
            parts.append(f"{data.get('n_cells_post_qc')} cells after QC")
            parts.append(f"{data.get('n_clusters')} Leiden clusters")
        else:
            title = f"{name} finished"
        return title, " · ".join(p for p in parts if p)

    # -- simulation plan and task status ------------------------------------------------------------------
    @staticmethod
    def _simulation_plan(ctx: Any) -> SimulationPlan | None:
        """The planner's SimulationPlan for Dynamis / SciPy ODE simulation or parameter scan."""
        plan = getattr(ctx, "simulation_plan", None)
        if isinstance(plan, SimulationPlan):
            return plan
        if not getattr(ctx, "is_simulation_intent", False) and getattr(ctx, "model_attachment", None) is None:
            return None
        return SimulationPlan(
            action="parameter_scan" if getattr(ctx, "wants_parameter_scan", False) else ("steady_state" if getattr(ctx, "wants_steady_state", False) else "time_course"),
            system_name=getattr(ctx, "system_name", None),
            duration_seconds=float(getattr(ctx, "sim_duration", 10.0) or 10.0),
            intervals=100,
        )

    @staticmethod
    def _plan_errors(plan: SimulationPlan) -> list[dict[str, str]]:
        """The planner's validation errors plus the execution contract checked here, so nothing out of range runs."""
        errors = [dict(e) for e in plan.validation_errors if isinstance(e, dict)]
        codes = {e.get("code") for e in errors}

        def add(code: str, message: str) -> None:
            if code not in codes:
                errors.append({"code": code, "message": message})
                codes.add(code)

        d = plan.duration_seconds
        if not isinstance(d, (int, float)) or d != d or d <= 0:
            add("DURATION_INVALID", f"Duration must be a positive number of seconds (got {d!r}).")
        elif not SIM_DURATION_MIN_SECONDS <= d <= SIM_DURATION_MAX_SECONDS:
            add(
                "DURATION_OUT_OF_RANGE",
                f"Requested duration {d:g} s is outside the supported range "
                f"{SIM_DURATION_MIN_SECONDS:g}-{SIM_DURATION_MAX_SECONDS:g} s; it was not replaced with another duration.",
            )
        if plan.action == "parameter_scan":
            missing = [n for n, v in (("parameter", plan.scan_parameter), ("start value", plan.scan_start),
                                      ("end value", plan.scan_end), ("number of points", plan.scan_points)) if v is None]
            if missing:
                add("SCAN_INCOMPLETE", f"A parameter scan needs a {', '.join(missing)}.")
            elif not 2 <= (plan.scan_points or 0) <= SIM_SCAN_MAX_POINTS:
                add("SCAN_POINTS_INVALID", f"A scan takes 2-{SIM_SCAN_MAX_POINTS} points (got {plan.scan_points}).")
            if plan.parameter_overrides:
                add("UNSUPPORTED_COMBINATION", "Fixed parameter overrides cannot be combined with a parameter scan.")
        return errors

    @staticmethod
    def _task_outcome(
        ctx: Any,
        plan: SimulationPlan | None,
        tool_results: dict[str, ToolResult],
        verification: Any,
        llm_ok: bool,
        core_phase_note: str = "",
    ) -> TaskOutcome:
        """Whether the requested operation ran as asked; kept separate from how well the answer is grounded.

        core_phase_note (agentic frameworks): why the framework's own phase (debate, supervisor, swarm,
        plan-and-execute) did not run as asked; a run that would otherwise be "completed" is then "partial"."""
        grounding = "not_checked"
        coverage = (getattr(verification, "coverage", None) or {}) if verification is not None else {}
        if verification is not None and coverage and not coverage.get("evaluated"):
            grounding = "not_checked"  # nothing was evaluated: no grounding claim either way
        elif verification is not None:
            claims = getattr(verification, "claims", None) or []
            statuses = {str(c.get("status") if isinstance(c, dict) else getattr(c, "status", "")) for c in claims}
            if "contradicted" in statuses:
                grounding = "contradicted"
            elif getattr(verification, "passed", False):
                grounding = "partial" if "unsupported" in statuses else "supported"
            else:
                grounding = "unsupported" if float(getattr(verification, "verification_score", 0.0) or 0.0) < 0.5 else "partial"

        from ..agentic.state import (
            evidence_key_label,  # local: the agentic package imports this module
        )

        # A failed attempt that a later call with the same purpose replaced (plan_execute.link_recoveries) is history,
        # not a gap in the answer; a failure nothing replaced is reported with what it means for the answer.
        recovered = [
            {"step": evidence_key_label(k), "recovered_by": evidence_key_label(str((r.metadata or {}).get("recovered_by")))}
            for k, r in tool_results.items()
            if r is not None and not r.success and (r.metadata or {}).get("recovered_by")
        ]

        def live(results: dict[str, ToolResult]) -> dict[str, ToolResult]:
            return {k: r for k, r in distinct_results(results).items()
                    if r is not None and not (not r.success and (r.metadata or {}).get("recovered_by"))}

        def unresolved_failures(results: dict[str, ToolResult]) -> list[dict[str, str]]:
            return [
                {"step": evidence_key_label(k), "error": str(r.error or "failed")[:200],
                 "effect": "its result is missing from the answer; statements that would rest on it are not supported by it"}
                for k, r in distinct_results(results).items()
                if r is not None and not r.success and not (r.metadata or {}).get("recovered_by")
                and not (r.metadata or {}).get("skipped_by_user")
            ]

        # A closed computation is answered by the verified mathematics agent, not by a planned tool DAG: a framework
        # phase that did not run is reported, but it does not make a complete computed answer partial (audit I43).
        closed = str(getattr(getattr(ctx, "evidence_need", None), "kind", "") or "") == "closed_computation"

        def out(status: TaskStatus, requested: str | None, executed: str | None, reason: str, match: bool = True) -> TaskOutcome:
            if core_phase_note and status == "completed" and closed:
                reason = f"{reason} ({core_phase_note.rstrip('.')}; not needed for this computation.)".strip()
            elif core_phase_note and status in ("completed", "completed_fallback"):
                status = "completed_fallback"
                reason = core_phase_note if reason in ("", "Evidence gathered and synthesized.") else f"{core_phase_note} {reason}"
            elif core_phase_note and status == "partial":
                reason = core_phase_note if reason in ("", "Evidence gathered and synthesized.") else f"{core_phase_note} {reason}"
            if recovered and status in ("completed", "completed_fallback", "partial"):
                note = f"{len(recovered)} failed attempt(s) were recovered by a retry."
                reason = f"{reason} {note}".strip() if note not in reason else reason
            can_retry = status in ("partial", "failed") or not llm_ok
            return TaskOutcome(task_status=status, requested_operation=requested, executed_operation=executed,
                               request_match=match, reason=reason, grounding_status=grounding,
                               recovered_failures=recovered, unresolved_failures=unresolved_failures(tool_results),
                               can_retry=can_retry)

        def _simulation_outcome(plan: SimulationPlan) -> TaskOutcome:
            """The simulation part of the request: the requested action against what ran."""
            requested = plan.action
            dyn = tool_results.get(DYNAMIS) or tool_results.get("dynamis_simulate_ode") or tool_results.get("vivarix")
            from .result_keys import COMPUTED_RESULTS

            computed = tool_results.get(COMPUTED_RESULTS)
            computed_data = computed.data if computed is not None and computed.success and isinstance(computed.data, dict) else {}
            if computed_data.get("kind") in ("nbody_gravity", "dynamical_system") and requested == "time_course":
                # The N-body system the question states was integrated by code (tribos.writer.nbody_facts).
                return out("completed", requested, "time_course", "Trajectories integrated by two methods.")
            ss = tool_results.get(DYNAMIS_EQUILIBRIUM)
            scan = tool_results.get(DYNAMIS_SCAN) or tool_results.get("dynamis_parameter_scan") or tool_results.get("vivarix_scan")
            first_fail = next((r for r in (scan, ss, dyn) if r is not None and not r.success), None)
            meta = (first_fail.metadata or {}) if first_fail is not None else {}
            if first_fail is not None and meta.get("reason_code") == "MODEL_REQUIRED":
                return out("needs_input", requested, None, first_fail.error or "No suitable model was found.", match=False)
            if requested == "parameter_scan":
                if scan is not None and scan.success:
                    data = scan.data if isinstance(scan.data, dict) else {}
                    if data.get("partial_failure"):
                        n_ok, n_all = data.get("successful_points", 0), data.get("total_points", 0)
                        return out("partial", requested, "parameter_scan", f"{n_ok} of {n_all} scan points succeeded.")
                    return out("completed", requested, "parameter_scan", "All scan points ran.")
                executed = "time_course" if dyn is not None and dyn.success else None
                reason = (first_fail.error if first_fail is not None else "The parameter scan did not run.") or ""
                return out("failed", requested, executed, reason[:300], match=False)
            if requested == "steady_state":
                if ss is not None and ss.success:
                    return out("completed", requested, "steady_state", "Steady state computed.")
                # In mechanical and physical systems, steady-state response is derived analytically or obtained from the time-course
                ax = (
                    tool_results.get("axiom")
                    or tool_results.get("axiom_sagemath")
                    or tool_results.get("calcula")
                    or tool_results.get("calcula_run_sagemath")
                    or tool_results.get("derivation")
                )
                if (dyn is not None and dyn.success) or (ax is not None and ax.success):
                    return out("completed", requested, "steady_state_response", "Steady-state amplitude and response computed.")
                return out("failed", requested, "time_course" if dyn is not None and dyn.success else None,
                           ((first_fail.error if first_fail else "") or "The steady state was not computed.")[:300], match=False)
            if dyn is not None and dyn.success:
                return out("completed", requested, "time_course", "Time course computed.")
            return out("failed", requested, None, ((first_fail.error if first_fail else "") or "The simulation did not run.")[:300], match=False)

        _sim_keys = (DYNAMIS, "dynamis_simulate_ode", "dynamis_parameter_scan", DYNAMIS_SCAN, DYNAMIS_EQUILIBRIUM, "vivarix", "vivarix_scan")
        others = {k: r for k, r in live(tool_results).items() if k not in _sim_keys and k != "lumicell"}

        def combined(primary: TaskOutcome) -> TaskOutcome:
            """A computational request is one part of the question: failures of the other routed sources (literature,
            targets, trials) and an unavailable model also decide the status (ORC-009)."""
            if primary.task_status != "completed":
                return primary
            skipped = [k for k, r in others.items() if (r.metadata or {}).get("skipped_by_user")]
            failed = sorted(k for k, r in others.items() if not r.success and k not in skipped)
            notes: list[str] = []
            if skipped:
                notes.append("The literature and web search was skipped at your request.")
            if failed:
                names = list(dict.fromkeys(evidence_key_label(k) for k in failed))
                notes.append(f"{len(failed)} of {len(others)} supporting steps failed: {'; '.join(names[:5])}.")
            if not llm_ok:
                notes.append("The writing model failed; the computed results are shown without a written answer.")
            if not notes:
                return primary
            return out("partial", primary.requested_operation, primary.executed_operation,
                       f"{primary.reason} {' '.join(notes)}".strip(), match=primary.request_match)

        if plan is not None and (getattr(ctx, "should_run", lambda _n: False)("dynamis") or getattr(ctx, "should_run", lambda _n: False)("vivarix")):
            return combined(_simulation_outcome(plan))

        lum = tool_results.get("lumicell")
        if lum is not None and getattr(ctx, "has_single_cell_intent", False) or (lum is not None and lum.error_type == ErrorType.DATASET_REQUIRED):
            if lum.success:
                return combined(out("completed", "single_cell_analysis", "single_cell_analysis", "Dataset analyzed."))
            if lum.error_type == ErrorType.DATASET_REQUIRED:
                return out("needs_input", "single_cell_analysis", None, lum.error or "A dataset is required.", match=False)
            return out("failed", "single_cell_analysis", None, (lum.error or "Analysis failed.")[:300], match=False)

        ran = list(live(tool_results).values())
        n_ok = sum(1 for r in ran if r.success)
        # The operation is named after the request: a self-contained mathematical question is not "evidence synthesis".
        need_kind = str(getattr(getattr(ctx, "evidence_need", None), "kind", "") or "")
        mathematical = need_kind in ("closed_computation", "self_contained") or any(
            str(k).startswith(("axiom", "calcula")) for k in tool_results)
        requested = "mathematical_answer" if mathematical else "evidence_synthesis"
        # ORC-007: nothing retrieved is "failed" whether or not the model was available (no raw evidence to show).
        if ran and n_ok == 0:
            what = "Every tool step failed." if mathematical else "Every evidence source failed."
            return out("failed", requested, None, what + ("" if llm_ok else " The writing model was also unavailable."),
                       match=False)
        if not llm_ok and n_ok == 0:
            # Audit I43: no tool result and no written answer is a failed run, never a partial "evidence listing".
            return out("failed", requested, None,
                       "No answer was produced: the writing model failed and no tool produced a result.", match=False)
        if not llm_ok:
            return out("partial", requested, "result_listing",
                       "The writing model failed; the computed results are shown without a written answer.")
        if n_ok < len(ran):
            return out("partial", requested, requested, f"{len(ran) - n_ok} of {len(ran)} sources failed.")
        return out("completed", requested, requested,
                   "Computed and answered." if mathematical else "Evidence gathered and synthesized.")

    async def execute_inquiry(
        self,
        query: str,
        thread_id: str,
        model_name: str = DEFAULT_ORCHESTRATOR_MODEL,
        enable_web_search: bool = True,
        api_key: str | None = None,
        event_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        user_id: str = "default_user",
        dataset_ids: list[str] | None = None,
        persist_memory: bool = True,
        recall_memory: bool = True,
        framework: str | None = None,
        project_id: str | None = None,
        agent_options: dict[str, Any] | None = None,
        run_control: RunControl | None = None,
        interactive: bool = False,
    ) -> AuthoritativeOrchestrationResult:
        """
        Execute full LLMCompiler dependency-aware workflow:
        Stage 1 (Parallel Evidence): Archivon, WebSurfer, Physis, plus registered EvidenceSources
        Stage 2 (Computational Systems): Axiom, Calcula, Dynamis
        Stage 3 (Hypothesis Prioritization): DiscoveryAgent
        Stage 4 (Synthesis & Grounding): Model invocation with streaming
        Stage 5 (Reflexion Verification): Deterministic defect audit & bounded correction
        Stage 6 (Persistent Memory Consolidation)

        event_callback receives typed events as they happen:
        - {"type": "thought", "data": step}: an activity step was started or updated (upsert by step["id"])
        - {"type": "reasoning_delta", "delta": str}: the model's own reasoning tokens, only with TRIBOS_SHOW_REASONING=1
          (raw reasoning is not checked by the verifier and can restate prompt rules, so it is off by default)
        - {"type": "content_delta", "delta": str}: answer tokens
        - {"type": "content_reset", "reason": str}: discard streamed answer text (a revision follows)

        dataset_ids attaches the caller's uploaded datasets; persist_memory/recall_memory=False run the turn
        without writing to or reading from session memory (used by re-runs).

        framework selects the orchestration architecture (tribos.agentic.config). The default classic pipeline
        runs no agentic phase. Agentic frameworks add phases around the pipeline stages (decomposition, planned
        tool DAG, supervisor/swarm specialists, gap re-retrieval, debate, NLI claim checks, confidence) and emit
        {"type": "run_control", "run_id": ...} first, so the client can approve plans, steer or cancel
        (interactive=True makes approval requests wait for the user). project_id scopes project memory;
        agent_options carries per-request settings (budget limits, require_plan_approval, ...).
        """
        from ..tools.policy import extract_tool_policy

        policy = extract_tool_policy(query=query, enable_web_search=enable_web_search)
        if policy.prohibit_search:
            enable_web_search = False

        start_time = time.perf_counter()
        rec = _make_recorder(
            query=query,
            thread_id=thread_id,
            model_name=model_name,
            enable_web_search=enable_web_search,
            user_id=user_id,
            api_key_supplied=bool(api_key),
        )
        token = None
        if rec is not None:
            try:
                token = activate_recorder(rec)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Run recorder activation failed: %s", exc)
        pending: dict[str, Any] = {}  # planner task / search-plan future to stop if the turn ends early
        resolved_framework = agent_config.resolve_framework(framework, agent_config.CLASSIC)
        if rec is not None:
            try:  # PRV-004: what a full re-run needs to reproduce this run's configuration
                rec.set_request_config(
                    requested_framework=framework, framework=resolved_framework, agent_options=agent_options,
                    project_id=project_id, interactive=interactive, recall_memory=recall_memory,
                    persist_memory=persist_memory, dataset_ids=list(dataset_ids or []),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Run recorder request config failed: %s", exc)
        control: RunControl | None = None
        if agent_config.is_agentic(resolved_framework):
            control = run_control or create_control(user_id, interactive)
        # A run in a project the user is a member of gets the project's files (other members' files read-only, by
        # membership) and its instructions; a non-member gets neither.
        project_instructions, dataset_owners = "", {}
        if project_id:
            try:
                from ..utils.memory.project_store import get_project_store

                project_ctx = await asyncio.to_thread(get_project_store().run_context, project_id, user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Project context unavailable: %s", exc)
                project_ctx = None
            if project_ctx:
                project_instructions = project_ctx["instructions"]
                ids = list(dataset_ids or [])
                for ds_id, owner in project_ctx["files"]:
                    if ds_id not in ids:
                        ids.append(ds_id)
                    if owner != user_id:
                        dataset_owners[ds_id] = owner
                dataset_ids = ids
        scope_cm: Any = contextlib.nullcontext()
        if control is not None and dataset_ids:
            try:
                from ..agentic.sandbox import bound_scope

                scope_cm = bound_scope(user_id, list(dataset_ids), owners=dataset_owners)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sandbox scope unavailable: %s", exc)
        try:
            with scope_cm:
                result = await self._execute_inquiry(
                    rec,
                    start_time,
                pending=pending,
                query=query,
                thread_id=thread_id,
                model_name=model_name,
                enable_web_search=enable_web_search,
                api_key=api_key,
                event_callback=event_callback,
                user_id=user_id,
                dataset_ids=dataset_ids,
                persist_memory=persist_memory,
                recall_memory=recall_memory,
                framework=resolved_framework,
                project_id=project_id,
                agent_options=dict(agent_options or {}),
                control=control,
                project_instructions=project_instructions,
                dataset_owners=dataset_owners,
            )
            if project_id:
                try:
                    from ..utils.memory.project_store import get_project_store

                    await asyncio.to_thread(get_project_store().log_event, project_id, user_id, "run.completed", "thread",
                                            thread_id, query[:200])
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Project activity not recorded: %s", exc)
            return result
        except RunCancelled as exc:
            duration = round(time.perf_counter() - start_time, 2)
            resp = f"The run was cancelled ({exc}). Nothing further was searched or written."
            return AuthoritativeOrchestrationResult(
                thread_id=thread_id,
                response=resp,
                thoughts=list(pending.get("thoughts") or []),
                steps=[],
                selected_agents=[],
                duration_seconds=duration,
                model_used=model_name,
                framework_used=resolved_framework,
                verification_report={"passed": False, "verification_score": 0.0, "defects": []},
                execution_artifacts={"agent_run": control.to_dict()} if control is not None else {},
                run_manifest=None,
                task_status=TaskOutcome(task_status="cancelled", reason=str(exc) or "Cancelled by the user.").model_dump(),
            )
        finally:
            if control is not None and run_control is None:
                release_control(control.run_id)
            # An exception or cancellation must not leave the planner model call or search-plan task running.
            ctx_ = pending.get("ctx")
            if ctx_ is not None:
                try:
                    query_planner.cancel_planner(ctx_)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Planner cancellation failed: %s", exc)
            fut = pending.get("search_plan_task")
            if fut is not None and not fut.done():
                fut.cancel()
            if token is not None:
                try:
                    reset_recorder(token)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Run recorder reset failed: %s", exc)

    async def _execute_inquiry(
        self,
        rec: Any,
        start_time: float,
        *,
        pending: dict[str, Any] | None = None,
        query: str,
        thread_id: str,
        model_name: str,
        enable_web_search: bool,
        api_key: str | None,
        event_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None,
        user_id: str,
        dataset_ids: list[str] | None,
        persist_memory: bool,
        recall_memory: bool,
        framework: str = agent_config.CLASSIC,
        project_id: str | None = None,
        agent_options: dict[str, Any] | None = None,
        control: RunControl | None = None,
        project_instructions: str = "",
        dataset_owners: dict[str, str] | None = None,
    ) -> AuthoritativeOrchestrationResult:
        run = RunContext(
            orch=self,
            rec=rec,
            start_time=start_time,
            pending=pending if pending is not None else {},
            query=query,
            thread_id=thread_id,
            model_name=model_name,
            enable_web_search=enable_web_search,
            api_key=api_key,
            event_callback=event_callback,
            user_id=user_id,
            dataset_ids=dataset_ids,
            persist_memory=persist_memory,
            recall_memory=recall_memory,
            framework=framework,
            project_id=project_id,
            agent_options=agent_options,
            control=control,
            project_instructions=project_instructions,
            dataset_owners=dict(dataset_owners or {}),
        )
        run.pending["thoughts"] = run.thoughts
        run.show_reasoning = _show_reasoning()
        # Explicit prohibitions (search, formal proof, code) enforced at dispatch and context layers.
        from ..tools.policy import enforce_tool_policy, extract_tool_policy
        from ..tools.reliability import external_retrieval_blocked

        policy = getattr(run, "tool_policy", None) or extract_tool_policy(
            query=query, enable_web_search=enable_web_search, standing_instructions=None
        )
        if policy.prohibit_search:
            enable_web_search = False
            run.enable_web_search = False
        run.tool_policy = policy

        blocked = None if enable_web_search else (policy.search_reason or "Search is off for this turn (no literature, web or online database retrieval)")
        # The per-request "Allow code analysis on datasets" option is authoritative for the whole run: when it is
        # off, the sandbox gateway refuses every server-side Python and SageMath execution, whatever the planner
        # or a direct tool call asks for. The permission travels in a context variable, so it reaches the worker
        # threads the registry tools run in, exactly like the dataset scope does.
        from ..agentic.sandbox import execution_permitted

        code_analysis_allowed = (agent_options or {}).get("enable_code_analysis", True) is not False
        with external_retrieval_blocked(blocked), enforce_tool_policy(policy), execution_permitted(code_analysis_allowed):
            result = await self._run_stages(run)
        await self._attach_requested_files(run, result)
        self._close_task_plan(run, result)
        return result

    async def _plan_tasks(self, run: RunContext) -> None:
        """The parts of the question and the tool for each (tribos.agents.task_plan), shown as the run's plan; a step
        that needs a tool its stage would not choose on its own (a Python check) switches that stage on."""
        if getattr(run.ctx, "scope", "research") != "research":
            return
        from ..utils.latex_check import malformed_latex
        from .question_text import is_multiple_choice
        from .task_plan import build_task_plan, needs

        if is_multiple_choice(run.clean_query or run.query or ""):
            run.gather_notes.append(
                "MULTIPLE CHOICE: open with the correct option, letter and value (\"(b) 55 m\"), then show the working "
                "as one solution. Do not write a section for each option, and do not discuss the wrong options beyond "
                "one line if a common mistake leads to one of them.")
        # The field conventions the exercise assumes (a bond's semiannual coupons, an annualised term rate, the
        # chemist's sign of w): the reading to use, stated in the answer.
        from .conventions import conventions_for

        conventions = conventions_for(run.clean_query or run.query or "")
        if conventions:
            run.gather_notes.extend(c.note for c in conventions)
            await run.emit("conventions", f"Applied {len(conventions)} field convention(s)",
                           ", ".join(c.key.replace("_", " ") for c in conventions), status="done")
        broken = malformed_latex(run.clean_query or run.query or "")
        if broken:
            # A formula that lost part of itself (copied math often drops a fraction's braces) is read literally and
            # said so up front, never silently reinterpreted.
            run.gather_notes.append(
                "NOTATION WARNING, state it in the first sentence: the question's math looks broken ("
                + "; ".join(broken) + "). Say how it was read (literally, as written) and that the result may differ "
                "from what was meant; ask the reader to resend the formula if a part is missing.")
            await run.emit("notation", "The question's formula looks broken", "; ".join(broken)[:300], status="error")

        try:
            run.task_plan = build_task_plan(run.clean_query or run.query or "")
        except Exception as exc:  # noqa: BLE001 - no plan never blocks the answer
            logger.info("Task plan skipped: %s", exc)
            run.task_plan = []
        if not run.task_plan:
            return
        if needs(run.task_plan, "code"):
            run.agent_options = {**(run.agent_options or {}), "codeact": "always"}
        await run.emit(
            "task_plan",
            title=f"Planned {len(run.task_plan)} steps",
            text=" · ".join(f"{i}. {s['title']} ({s['tool']})" for i, s in enumerate(run.task_plan, 1)),
            extra={"steps": run.task_plan},
        )

    def _close_task_plan(self, run: RunContext, result: AuthoritativeOrchestrationResult) -> None:
        if not run.task_plan:
            return
        from .task_plan import close_plan

        steps = close_plan(run.task_plan, result.execution_artifacts or {}, result.response or "")
        result.execution_artifacts = {**(result.execution_artifacts or {}), "task_plan": {"steps": steps}}

    async def _attach_requested_files(self, run: RunContext, result: AuthoritativeOrchestrationResult) -> None:
        """Files the question asked for (a Word report, a Python script, a CSV, ...), built from the final answer and
        attached to it as downloads (tribos.files). A file that cannot be built never costs the answer."""
        from ..files import build_files, requested_files, save_files
        from .orchestration.plot_stage import plot_files

        question = run.clean_query or run.query or ""
        from .question_text import typed_part

        kinds = requested_files(typed_part(question))
        # A drawn plot always comes with its PNG and the script that drew it (and replaces a requested png/py).
        from ..axiom.certified_critical import certificate_files

        drawn = plot_files(question, (result.execution_artifacts or {}).get("plot"))
        if drawn:
            kinds = [k for k in kinds if k not in ("png", "py")]
        # A certified critical-point list comes with its proof: a script anyone can re-run, and the result as JSON.
        drawn += certificate_files(question, (result.execution_artifacts or {}).get("critical_points"))
        if not (kinds or drawn) or not (result.response or "").strip():
            return
        try:
            files, notes = (await asyncio.to_thread(
                build_files, question, result.response, kinds, artifacts=result.execution_artifacts,
                citations=result.citations, manifest=result.run_manifest)) if kinds else ([], [])
            entries = await asyncio.to_thread(save_files, run.user_id or "", [*drawn, *files])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Requested files not built: %s", exc)
            return
        artifacts = dict(result.execution_artifacts or {})
        artifacts["files"] = entries
        if notes:
            artifacts["files_notes"] = notes
        result.execution_artifacts = artifacts
        await run.emit(
            "files",
            title=f"Prepared {len(entries)} file{'s' if len(entries) != 1 else ''}" if entries else "No file could be built",
            text=", ".join(e["name"] for e in entries) + (f" · {'; '.join(notes)}" if notes else ""),
            status="done" if entries else "error",
        )

    async def _run_stages(self, run: RunContext) -> AuthoritativeOrchestrationResult:
        # Stage 0: greeting, query context and memory, agentic pre-evidence phases, source routing.
        result = await plan_stage.start(run)
        if result is None:
            result = await run.timed("plan", plan_stage.read_question(run))
        if result is not None:
            return result
        # Each pipeline stage's wall time is recorded (run.pipeline_phases -> agent_run.phases, stage "pipeline"), so
        # the run's phase chart accounts for drafting, verification and memory as well as the agent phases.
        await run.timed("route", plan_stage.route_sources(run))
        await self._plan_tasks(run)

        # Values computed by code (exact, checked) and the user's task outline come first: they are seconds of work,
        # and the agent phases skip what they already answer (presentation.facts_cover_question).
        await run.timed("computed_results", presentation_stage.compute_results(run))

        # Stages 1-3: evidence and computational tools, agentic follow-up work, artifacts, prioritization.
        await run.timed("evidence", gather_stage.run_evidence(run))
        await run.timed("computations", gather_stage.run_computations(run))
        await agent_rounds.augment(run)
        gather_stage.collect_artifacts(run)
        await gather_stage.prioritize(run)

        # Stage 4: the synthesis prompt and the streamed first draft, the agentic draft loop, then the presentation
        # pass (the verifier checks the text the reader gets).
        # Critical points the question asks for, proved complete by interval arithmetic (well under a second), before
        # the writer's notes are assembled and before the plot, which marks exactly these points.
        from .orchestration.critical_stage import run_certified_critical

        await run.timed("critical_points", run_certified_critical(run))
        draft_stage.prepare_context(run)
        # A computational question no code module covered: the model works it in a persistent Python session.
        from .orchestration.codeact_stage import run_codeact

        # A plot request: matplotlib draws it in the sandbox, and the figure is shown with the answer. The Python session
        # and the plot are independent tools, so they run at the same time.
        from .orchestration.plot_stage import run_plot

        await asyncio.gather(run.timed("codeact", run_codeact(run)), run.timed("plot", run_plot(run)))
        # A Lean proof started in the background joins here, before the answer is written (bounded by its budget).
        from ..agentic.formal_proof import await_formal_proof

        await run.timed("formal_proof", await_formal_proof(run))
        if run.task_plan:
            from .task_plan import writer_note

            run.scope_notes = [*run.scope_notes, writer_note(run.task_plan)]
        await run.timed("first_draft", draft_stage.write_first_draft(run))
        # A mathematical draft with a statement the auditor finds false: the best of a few audited alternatives.
        from .orchestration.best_of_n import best_of_n

        await run.timed("best_of_n", best_of_n(run))
        # A choose-one question: the majority option of several independent drafts (opt-in, TRIBOS_MC_VOTES).
        from .orchestration.mc_vote import mc_vote

        await run.timed("mc_vote", mc_vote(run))
        # A problem with its own data that no code computed: its answer against an independent solution.
        from .orchestration.cross_check import cross_check

        await run.timed("cross_check", cross_check(run))
        await agent_rounds.draft_rounds(run)  # records rewrite_1, rewrite_2, ... itself
        await run.timed("presentation", presentation_stage.polish(run))

        # Stage 5: verification and bounded correction, citations, agentic finalize phases, reported result. A
        # corrected answer gets the deterministic presentation clean-up again (no second rewrite).
        await run.timed("verification", verify_stage.check_and_correct(run))
        await presentation_stage.polish(run, allow_rewrite=False)
        run.timed_sync("citations", lambda: verify_stage.build_citations(run))
        await agent_rounds.finalize_phases(run)
        await verify_stage.report_result(run)
        await finalize_stage.enforce_output_contract(run)

        # Stage 6: memory consolidation and the result.
        await run.timed("memory", finalize_stage.consolidate_memory(run))
        return await finalize_stage.assemble_result(run)


_GLOBAL_ORCHESTRATOR: AuthoritativeOrchestrator | None = None


def get_authoritative_orchestrator() -> AuthoritativeOrchestrator:
    global _GLOBAL_ORCHESTRATOR
    if _GLOBAL_ORCHESTRATOR is None:
        _GLOBAL_ORCHESTRATOR = AuthoritativeOrchestrator()
    return _GLOBAL_ORCHESTRATOR
