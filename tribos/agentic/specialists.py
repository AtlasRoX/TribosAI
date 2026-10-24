"""
Specialist agents for the multi-agent topologies (feature 4), plus the shared evidence helpers the loop phases
(gaps, counter-evidence, topologies) use.

A specialist is a named group of registry tools with a standard operating procedure written into its role
prompt (MetaGPT SOP-style roles, Hong et al., ICLR 2024, arXiv:2308.00352). Groups are built from the live
registry at run time, from each tool's domain, name prefix and tags, so tools that other packages register
(trials, drugs, structure, omics sources, ...) join the right specialist without a code change here:

- literature: archivon (arXiv, zbMATH, Crossref, OpenAlex, Semantic Scholar, NASA ADS), web search
- symbolic: axiom (SymPy computer algebra, equation solving, calculus, ODE dsolve, linear algebra, identity verification)
- numerical: dynamis (ODE simulation, equilibria & stability, parameter scans, optimization, parameter fitting, root finding)
- analysis: calcula / analysis (sandboxed scientific Python & dataset inspection)
- reference: physis (CODATA physical constants, Pint units, OEIS integer sequences, Materials Project, WolframAlpha, encyclopedia)

Each tool also passes the turn's hard policy: the source allowlist ("papers only"), web search on/off, simulation
bans, and sources the researcher switched off at plan approval. Conversable specialists that call
tools or hand off follow AutoGen (Wu et al., COLM 2024, arXiv:2308.08155).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .budget import BudgetExhausted
from .guardrails import spotlight
from .llm import AgentLLMUnavailable
from .plan_graph import excluded_by_question
from .tool_retrieval import tokenize, tool_card

logger = logging.getLogger(__name__)

LITERATURE_TOOL = "archivon_literature_search"
LEGACY_LITERATURE_TOOL = "lithoscribe_literature_synthesis"
WEB_TOOL = "websurfer_search"


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    label: str
    role: str  # SOP: what the specialist is for and how it works
    domains: frozenset[str]
    prefixes: tuple[str, ...]
    tags: frozenset[str]


SPECIALIST_SPECS: tuple[SpecialistSpec, ...] = (
    SpecialistSpec(
        name="literature",
        label="Literature specialist",
        role=(
            "Find mathematical, physical, and engineering papers, preprints, and (when allowed) web sources that answer "
            "the instruction. Procedure: 1) turn the instruction into a focused search query with the key theorems, "
            "equations, or physical systems; 2) call one search tool; 3) read the passages; 4) search again only for "
            "what is still missing; 5) finish with a summary that names the arXiv/DOI/zbMATH identifiers found and what they show."
        ),
        domains=frozenset({"archivon", "websurfer", "literature", "lithoscribe", "trials"}),
        prefixes=("archivon", "websurfer", "lithoscribe", "arxiv", "zbmath", "crossref", "openalex", "semantic_scholar", "ads", "europepmc", "pubmed"),
        tags=frozenset({"literature", "arxiv", "zbmath", "crossref", "openalex", "semantic_scholar", "ads",
                        "citations", "papers", "preprint", "preprints", "web", "europepmc", "paperqa2", "pubmed"}),
    ),
    SpecialistSpec(
        name="symbolic",
        label="Symbolic specialist",
        role=(
            "Perform exact symbolic mathematics using Axiom (SymPy): simplify expressions, solve algebraic or differential "
            "equations in closed form, compute derivatives/integrals/limits/series, perform exact linear algebra, and verify "
            "mathematical identities. Procedure: 1) write the exact symbolic expression and variables; 2) call the appropriate "
            "Axiom tool; 3) report exact symbolic results and LaTeX forms as returned, never approximated."
        ),
        domains=frozenset({"axiom", "symbolic", "math"}),
        prefixes=("axiom",),
        tags=frozenset({"symbolic", "sympy", "algebra", "calculus", "solve", "dsolve", "linalg", "proof",
                        "identity", "latex", "matrix", "equations", "polynomial"}),
    ),
    SpecialistSpec(
        name="numerical",
        label="Numerical specialist",
        role=(
            "Run numerical simulations and solvers with Dynamis (SciPy): integrate ODE systems, find equilibria and Jacobian "
            "eigenvalue stability, run parameter sweeps, optimize objective functions, fit model parameters to data, and find "
            "numerical roots. Procedure: 1) formulate the explicit equations, parameters, and initial/boundary conditions from "
            "the context; 2) run the one numerical computation requested; 3) report numerical values with tolerances and units."
        ),
        domains=frozenset({"dynamis", "numerical"}),
        prefixes=("dynamis",),
        tags=frozenset({"simulation", "ode", "pde", "equilibrium", "steady_state", "parameter_scan", "optimize",
                        "fit", "calibration", "root_find", "scipy", "dynamics", "kinetics", "bifurcation"}),
    ),
    SpecialistSpec(
        name="analysis",
        label="Analysis specialist",
        role=(
            "Inspect attached datasets and run verified scientific Python computations with Calcula: dataset summaries, "
            "statistical tests, array/matrix computations, and numerical cross-checks. Procedure: 1) inspect the dataset "
            "schema or formulate a self-contained verification script; 2) run the tool; 3) report exact computed numbers."
        ),
        domains=frozenset({"calcula", "analysis", "sandbox"}),
        prefixes=("calcula", "analysis"),
        tags=frozenset({"sandbox", "python", "dataset", "table", "hdf5", "mat", "computation", "statistics",
                        "dataframe", "plot", "scipy", "numpy"}),
    ),
    SpecialistSpec(
        name="reference",
        label="Reference specialist",
        role=(
            "Look up authoritative reference data with Physis: CODATA physical constants, Pint unit conversions and dimensional "
            "checks, OEIS integer sequences, Materials Project crystal/electronic properties, WolframAlpha, and mathematical "
            "encyclopedia definitions. Procedure: 1) identify the exact constant, unit, sequence, material, or concept; "
            "2) call the matching Physis lookup; 3) report values, uncertainties, units, and identifiers verbatim."
        ),
        domains=frozenset({"physis", "reference"}),
        prefixes=("physis", "codata", "pint", "oeis", "mp", "wolfram", "wikipedia"),
        tags=frozenset({"constants", "codata", "units", "pint", "oeis", "sequence", "materials", "crystal",
                        "wolfram", "encyclopedia", "wikipedia", "reference"}),
    ),
    SpecialistSpec(
        name="target",
        label="Target specialist",
        role=(
            "Characterise genes and targets: target-disease associations, pathways, knowledge-graph relations and "
            "variants. Procedure: 1) identify the gene/disease identifiers needed; 2) call the lookup that answers "
            "the instruction; 3) report the exact association score or pathway name as returned, never guessed."
        ),
        domains=frozenset({"synapta", "target", "disease_targets", "primekg", "variants"}),
        prefixes=("synapta", "opentargets", "primekg", "variant"),
        tags=frozenset({"target", "disease", "association", "pathway", "kegg", "primekg", "variant", "clinvar"}),
    ),
    SpecialistSpec(
        name="simulation",
        label="Simulation specialist",
        role=(
            "Simulate mechanistic biological models on Vivarix: time-course trajectories, steady states, and parameter "
            "scans. Procedure: 1) inspect the model's species and parameters; 2) simulate the experiment the researcher "
            "asked for; 3) report numerical endpoints and steady states with their units."
        ),
        domains=frozenset({"vivarix", "simulation"}),
        prefixes=("vivarix",),
        tags=frozenset({"simulation", "copasi", "biomodels", "ode", "steady_state", "scan"}),
    ),
    SpecialistSpec(
        name="omics",
        label="Omics specialist",
        role=(
            "Inspect single-cell datasets on Lumicell and query expression and genetic association screens. Procedure: "
            "1) check that the dataset is attached; 2) run quality control and clustering; 3) report top marker genes and "
            "expression levels."
        ),
        domains=frozenset({"lumicell", "omics"}),
        prefixes=("lumicell", "gtex", "gwas", "depmap", "string", "reactome"),
        tags=frozenset({"single_cell", "scanpy", "anndata", "clustering", "expression", "gwas", "ppi"}),
    ),
    SpecialistSpec(
        name="chemistry",
        label="Chemistry specialist",
        role=(
            "Retrieve drug profiles, mechanisms of action, approved indications and adverse events from ChEMBL and "
            "openFDA, and inspect 3D biomolecular structures. Procedure: 1) resolve the drug name or ChEMBL id; 2) query "
            "mechanism and adverse event profiles; 3) report clinical status and safety signals."
        ),
        domains=frozenset({"chembl", "openfda", "pubchem", "structure"}),
        prefixes=("chembl", "openfda", "pubchem", "structure"),
        tags=frozenset({"drug", "fda", "safety", "mechanism", "structure", "chembl", "pubchem"}),
    ),
)

SPECS_BY_NAME: dict[str, SpecialistSpec] = {s.name: s for s in SPECIALIST_SPECS}
_EXCLUDED_DOMAINS: frozenset[str] = frozenset()


def resolve_literature_tool(registry: Any, state: Any = None) -> str:
    """Return the active literature tool registered in `registry` (preferring archivon_literature_search)."""
    if state is not None and getattr(state, "tool_results", None):
        if any("lithoscribe" in str(k).lower() for k in state.tool_results):
            if hasattr(registry, "get_entry") and registry.get_entry(LEGACY_LITERATURE_TOOL) is not None:
                return LEGACY_LITERATURE_TOOL
    if hasattr(registry, "get_entry"):
        if registry.get_entry(LEGACY_LITERATURE_TOOL) is not None and registry.get_entry(LITERATURE_TOOL) is None:
            return LEGACY_LITERATURE_TOOL
        if registry.get_entry(LITERATURE_TOOL) is not None:
            return LITERATURE_TOOL
        if registry.get_entry(LEGACY_LITERATURE_TOOL) is not None:
            return LEGACY_LITERATURE_TOOL
    return LITERATURE_TOOL


def classify_tool(entry: Any) -> str | None:
    """The specialist a registry tool belongs to (domain 3 points, name prefix 2, each tag 1); None if no signal."""
    domain = (getattr(entry, "domain", "") or "").lower()
    if domain in _EXCLUDED_DOMAINS:
        return None
    name = (getattr(entry, "name", "") or "").lower()
    tags = {str(t).lower() for t in (getattr(entry, "tags", None) or [])}
    best, best_score = None, 0
    for spec in SPECIALIST_SPECS:
        score = 3 * (domain in spec.domains)
        score += 2 * any(name.startswith(p) for p in spec.prefixes)
        score += len(tags & spec.tags)
        if score > best_score:
            best, best_score = spec.name, score
    return best


def tool_source_key(entry: Any) -> str:
    """The source key a tool is gated by in ctx.source_allowlist / ctx.decisions."""
    name = (getattr(entry, "name", "") or "").lower()
    if name in (LITERATURE_TOOL, "archivon_paper_details", "archivon_recommend"):
        return "archivon"
    if name == LEGACY_LITERATURE_TOOL:
        return "lithoscribe"
    if name.startswith("websurfer"):
        return "websurfer"
    if name.startswith("analysis_"):
        return "calcula"
    return name.split("_", 1)[0] or (getattr(entry, "domain", "") or "").lower()


def _switched_off(ctx: Any, key: str) -> bool:
    decision = (getattr(ctx, "decisions", None) or {}).get(key)
    reason = str(getattr(decision, "reason", "") or "").lower()
    return decision is not None and not getattr(decision, "run", True) and reason.startswith("switched off")


def simulation_forbidden(ctx: Any) -> bool:
    constraints = getattr(ctx, "simulation_constraints", None)
    return bool(getattr(ctx, "suppress_simulation", False) or getattr(constraints, "simulation_forbidden", False))


def tool_allowed(ctx: Any, entry: Any) -> tuple[bool, str]:
    """(allowed, reason) for one tool under the turn's hard policy."""
    if entry is None:
        return False, "tool is not registered"
    domain = (getattr(entry, "domain", "") or "").lower()
    name = (getattr(entry, "name", "") or "").lower()
    if domain in _EXCLUDED_DOMAINS:
        return False, "sandboxed analysis runs only through the analyst phase"
    if name in ("calcula_run_python", "analysis_run_python") and (getattr(ctx, "extras", None) or {}).get("code_analysis_forbidden"):
        return False, "the researcher asked for no code execution"
    if (domain in ("dynamis", "vivarix") or name.startswith(("dynamis_simulate", "vivarix")) or classify_tool(entry) == "numerical") and simulation_forbidden(ctx):
        return False, "the researcher asked for no simulation"
    excluded = excluded_by_question(entry, ctx)
    if excluded:
        return False, excluded
    key = tool_source_key(entry)
    if key == "websurfer" and not getattr(ctx, "enable_web_search", True):
        return False, "web search is switched off"
    allowlist = getattr(ctx, "source_allowlist", None)
    if allowlist is not None and key not in allowlist:
        # Accept archivon <-> lithoscribe alias when source_allowlist uses either name
        if not ({key, "archivon", "lithoscribe"} <= {key} | set(allowlist) and key in ("archivon", "lithoscribe") and bool({"archivon", "lithoscribe"} & set(allowlist))):
            return False, getattr(ctx, "source_restriction_reason", "") or "excluded by the source restriction"
    if _switched_off(ctx, key):
        return False, "switched off by the researcher"
    return True, ""


def simulation_requested(ctx: Any, tool_results: dict[str, Any] | None = None) -> bool:
    """Whether this turn asked for (or already ran) a dynamical simulation; never when simulation is forbidden."""
    if simulation_forbidden(ctx):
        return False
    intents = set(getattr(ctx, "intents", None) or ())
    if "simulate" in intents or "simulation" in intents or "steady_state" in intents:
        return True
    if getattr(ctx, "is_simulation_intent", False) or getattr(ctx, "simulation_plan", None) is not None:
        return True
    if getattr(ctx, "biomodel_id", None) or getattr(ctx, "model_attachment", None) is not None:
        return True
    return any(str(k).startswith(("dynamis", "vivarix")) for k in (tool_results or {}))


def single_cell_requested(ctx: Any, tool_results: dict[str, Any] | None = None) -> bool:
    """Legacy helper retained for compatibility: whether dataset/single-cell analysis was requested."""
    if (getattr(ctx, "extras", None) or {}).get("single_cell_forbidden"):
        return False
    return bool(getattr(ctx, "has_single_cell_intent", False)) or any(str(k).startswith(("calcula", "lumicell")) for k in (tool_results or {}))


def not_requested_modules(ctx: Any, tool_results: dict[str, Any] | None = None) -> list[str]:
    """Analyses the researcher did not ask for and that did not run: never a gap, never a limitation."""
    out: list[str] = []
    if not simulation_requested(ctx, tool_results):
        out.append("numerical ODE simulation")
    return out


def named_tool_allowed(state: Any, tool_name: str) -> bool:
    if not hasattr(state.registry, "get_entry"):
        return False
    entry = state.registry.get_entry(tool_name)
    if entry is None and tool_name == LITERATURE_TOOL:
        entry = state.registry.get_entry(LEGACY_LITERATURE_TOOL)
    return tool_allowed(state.ctx, entry)[0]


@dataclass
class Specialist:
    spec: SpecialistSpec
    tools: list[Any]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def label(self) -> str:
        return self.spec.label

    def tool_names(self) -> list[str]:
        return [e.name for e in self.tools]

    def get(self, tool_name: str) -> Any | None:
        return next((e for e in self.tools if e.name == tool_name), None)

    def cards(self) -> list[dict[str, Any]]:
        return [tool_card(e) for e in self.tools]


def build_specialists(state: Any) -> dict[str, Specialist]:
    """Specialists with at least one allowed tool, in SPECIALIST_SPECS order (built from the live registry)."""
    groups: dict[str, list[Any]] = {s.name: [] for s in SPECIALIST_SPECS}
    for entry in state.registry.list_tools():
        group = classify_tool(entry)
        if group is None or not tool_allowed(state.ctx, entry)[0]:
            continue
        groups[group].append(entry)
    if simulation_forbidden(state.ctx):
        groups["numerical"] = []
        groups["simulation"] = []
    return {name: Specialist(SPECS_BY_NAME[name], tools) for name, tools in groups.items() if tools}


def team_specialists(state: Any) -> dict[str, Specialist]:
    """The specialists a supervisor or swarm works with."""
    team = build_specialists(state)
    if simulation_forbidden(state.ctx):
        team.pop("numerical", None)
        team.pop("simulation", None)
    return team


# Model access --------------------------------------------------------------------------------------------------
def _note_ask(state: Any, phase: str, kind: str) -> None:
    bag = getattr(state, "bag", None)
    if isinstance(bag, dict):
        bag.setdefault("_ask_outcomes", {})[phase] = kind


def last_ask_outcome(state: Any, phase: str) -> str:
    """How the last ask_json call of a phase ended: ok | unavailable | llm_failed | budget | unusable | ""."""
    bag = getattr(state, "bag", None)
    return str(((bag or {}).get("_ask_outcomes") or {}).get(phase, "")) if isinstance(bag, dict) else ""


def model_failing(state: Any, phase: str) -> bool:
    """True when the last model call of the phase failed outright (no reply at all), so further calls would most
    likely fail the same way and only burn the time budget."""
    return last_ask_outcome(state, phase) in ("unavailable", "llm_failed", "budget")


async def ask_json(state: Any, system: str, user: str, *, phase: str, schema: type[BaseModel] | None = None) -> Any:
    """A parsed model reply, or None when the model is unavailable, the budget is used up or the reply is not JSON.

    The outcome is noted per phase (last_ask_outcome) so callers can tell a failed call from an unusable reply."""
    if not state.llm.available:
        _note_ask(state, phase, "unavailable")
        return None
    try:
        reply = await state.llm.json(system, user, schema=schema, phase=phase)
    except AgentLLMUnavailable as exc:
        logger.info("Agent model call for %s failed: %s", phase, exc)
        _note_ask(state, phase, "llm_failed")
        return None
    except BudgetExhausted as exc:
        logger.info("Agent model call for %s stopped: %s", phase, exc)
        _note_ask(state, phase, "budget")
        return None
    except ValueError as exc:
        logger.info("Agent model call for %s gave no usable reply: %s", phase, exc)
        _note_ask(state, phase, "unusable")
        return None
    _note_ask(state, phase, "ok")
    return reply


# Evidence helpers ----------------------------------------------------------------------------------------------
def iter_passages(tool_results: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """(result key, passage) for every passage of every successful literature-shaped result."""
    for key, res in list(tool_results.items()):
        data = getattr(res, "data", None)
        if not getattr(res, "success", False) or not isinstance(data, dict):
            continue
        items = data.get("ranked_passages") or data.get("passages") or []
        if not items and isinstance(data.get("papers"), list):
            items = [
                {
                    **p,
                    "passage_text": p.get("passage_text") or p.get("abstract") or p.get("snippet") or p.get("title") or "",
                }
                for p in data["papers"]
                if isinstance(p, dict)
            ]
        for p in items:
            if isinstance(p, dict):
                yield key, p


def passage_source_key(p: dict[str, Any], fallback: str = "") -> str:
    """The verifier's source key for a passage: ARXIV:<id>, DOI:<doi>, ZBL:<id>, MR:<id>, PMID:<n> or the result key."""
    if p.get("arxiv_id") or p.get("arxiv"):
        return f"ARXIV:{p.get('arxiv_id') or p.get('arxiv')}"
    if p.get("pmid"):
        return f"PMID:{p['pmid']}"
    if p.get("zbl") or p.get("zbmath_id"):
        return f"ZBL:{p.get('zbl') or p.get('zbmath_id')}"
    if p.get("mr") or p.get("mr_id"):
        return f"MR:{p.get('mr') or p.get('mr_id')}"
    if p.get("ads") or p.get("bibcode"):
        return f"ADS:{p.get('ads') or p.get('bibcode')}"
    if p.get("doi"):
        return f"DOI:{str(p['doi']).lower()}"
    if p.get("paper_id"):
        pid = str(p["paper_id"])
        return pid if ":" in pid else f"ARXIV:{pid}"
    return fallback


def passage_identity(p: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", str(p.get("passage_text") or p.get("abstract") or p.get("snippet") or "")).strip().lower()
    digest = hashlib.sha1(text[:400].encode("utf-8")).hexdigest()[:16]
    if p.get("arxiv_id") or p.get("arxiv"):
        ident = f"arxiv:{str(p.get('arxiv_id') or p.get('arxiv')).lower()}"
    elif p.get("pmid"):
        ident = f"pmid:{p['pmid']}"
    elif p.get("zbl") or p.get("zbmath_id"):
        ident = f"zbl:{str(p.get('zbl') or p.get('zbmath_id')).lower()}"
    elif p.get("doi"):
        ident = f"doi:{str(p['doi']).lower()}"
    elif p.get("paper_id"):
        ident = f"paper:{str(p['paper_id']).lower()}"
    else:
        ident = ""
    return f"{ident}|{digest}"


def seen_passages(tool_results: dict[str, Any]) -> set[str]:
    return {passage_identity(p) for _k, p in iter_passages(tool_results)}


def seen_urls(tool_results: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for res in list(tool_results.values()):
        data = getattr(res, "data", None)
        if getattr(res, "success", False) and isinstance(data, dict) and str(getattr(res, "tool_name", "")).startswith("websurfer"):
            urls.update(str(r.get("url")) for r in data.get("results") or [] if isinstance(r, dict) and r.get("url"))
    return urls


def compact(data: Any, limit: int = 600) -> str:
    try:
        text = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    return text if len(text) <= limit else text[:limit] + " ...(truncated)"


def evidence_text(tool_results: dict[str, Any], limit_per_result: int = 4000) -> str:
    """Lower-cased text of every successful result (passages, web snippets, compact JSON) for coverage checks."""
    parts: list[str] = []
    for res in list(tool_results.values()):
        if not getattr(res, "success", False):
            continue
        data = getattr(res, "data", None)
        if isinstance(data, dict) and isinstance(data.get("ranked_passages"), list):
            parts.extend(str(p.get("passage_text") or "") for p in data["ranked_passages"] if isinstance(p, dict))
        else:
            parts.append(compact(data, limit_per_result))
    return " ".join(parts).lower()


def stems(text: str) -> set[str]:
    """Crude prefix stems (first 6 characters) of the content words, so 'diseases'/'disease' and
    'associated'/'association' match."""
    return {t[:6] for t in tokenize(text) if len(t) > 2}


def evidence_digest(state: Any, max_items: int = 14, chars: int = 280) -> tuple[str, list[str]]:
    """A spotlighted digest of the gathered evidence for a critic or supervisor, and the evidence keys it names."""
    lines: list[str] = []
    keys: list[str] = []
    seen: set[str] = set()
    for rkey, p in iter_passages(state.tool_results):
        skey = passage_source_key(p, rkey)
        if skey in seen:
            continue
        seen.add(skey)
        text = re.sub(r"\s+", " ", str(p.get("passage_text") or ""))[:chars]
        setting = p.get("grade_label") or p.get("experimental_setting") or ""
        lines.append(f"[{skey}] ({setting}) {text}" if setting else f"[{skey}] {text}")
        keys.append(skey)
        if p.get("pmid"):
            keys.append(f"PMID:{p['pmid']}")
        if p.get("arxiv_id") or p.get("arxiv"):
            keys.append(f"ARXIV:{p.get('arxiv_id') or p.get('arxiv')}")
        if p.get("doi"):
            keys.append(f"DOI:{p['doi']}")
        if len(lines) >= max_items:
            break
    for rkey, res in list(state.tool_results.items()):
        if len(lines) >= max_items + 6:
            break
        data = getattr(res, "data", None)
        if not getattr(res, "success", False) or (isinstance(data, dict) and "ranked_passages" in data):
            continue
        lines.append(f"[{rkey}] {compact(data, chars)}")
        keys.append(rkey)
    return spotlight("\n".join(lines) or "(no evidence gathered)", "gathered evidence", 9000), keys


def _filtered_result(res: Any, data: dict[str, Any]) -> Any:
    try:
        return res.model_copy(update={"data": data})
    except AttributeError:  # not a pydantic ToolResult
        res.data = data
        return res


async def fetch_new_literature(
    state: Any,
    *,
    phase: str,
    query: str,
    purpose: str,
    seen: set[str],
    keywords: list[str] | None = None,
    max_articles: int = 5,
    render: bool = True,
    keep: Callable[[dict[str, Any]], bool] | None = None,
    stats: dict[str, Any] | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Run the literature tool and keep only passages not already in the evidence (and, with keep, only those it
    accepts: off-topic passages are never stored).

    Returns (stored result key or None, kept passages). `seen` is updated with the new passages' identities. stats,
    when given, receives the search outcome: status ok | empty | error, returned, new, kept, and incomplete when the
    engine skipped or cut searches for time.
    """
    lit_tool = resolve_literature_tool(getattr(state, "registry", None), state)
    kwargs: dict[str, Any] = {"query": query[:300], "max_articles": max_articles}
    if keywords:
        kwargs["keywords"] = [k for k in keywords if k][:8]
    res = await state.call_tool(lit_tool, phase=phase, purpose=purpose, store=False, **kwargs)
    data = getattr(res, "data", None)
    st = stats if stats is not None else {}
    if not getattr(res, "success", False) or not isinstance(data, dict):
        error_type = str(getattr(getattr(res, "error_type", None), "value", getattr(res, "error_type", "")) or "")
        st["status"] = "empty" if error_type == "NOT_FOUND" else "error"
        return None, []
    raw_passages = data.get("ranked_passages") or data.get("passages") or []
    if not raw_passages and isinstance(data.get("papers"), list):
        raw_passages = [
            {**p, "passage_text": p.get("passage_text") or p.get("abstract") or p.get("snippet") or p.get("title") or ""}
            for p in data["papers"]
            if isinstance(p, dict)
        ]
    returned = [p for p in raw_passages if isinstance(p, dict) and str(p.get("passage_text") or "").strip()]
    new: list[dict[str, Any]] = []
    for p in returned:
        ident = passage_identity(p)
        if ident in seen:
            continue
        seen.add(ident)
        new.append(p)
    kept = [p for p in new if keep is None or keep(p)]
    st.update({"status": "ok", "returned": len(returned), "new": len(new), "kept": len(kept)})
    queries = (data.get("retrieval") or {}).get("queries") or []
    if any("time budget" in str(q.get("error") or "") or "deadline" in str(q.get("error") or "") for q in queries if isinstance(q, dict)):
        st["incomplete"] = True
    new = kept
    if not new:
        return None, []
    key = state.add_result(
        state.next_key(phase, lit_tool),
        _filtered_result(res, {**data, "ranked_passages": new}),
        phase=phase,
        purpose=purpose,
        render=render,
    )
    return key, new


async def fetch_new_web(
    state: Any, *, phase: str, query: str, purpose: str, seen: set[str], max_results: int = 3,
    keep: Callable[[dict[str, Any]], bool] | None = None, stats: dict[str, Any] | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Run web search and keep only results whose URL is new (and, with keep, that it accepts); stats as in
    fetch_new_literature."""
    res = await state.call_tool(WEB_TOOL, phase=phase, purpose=purpose, store=False, query=query[:300], max_results=max_results)
    data = getattr(res, "data", None)
    st = stats if stats is not None else {}
    if not getattr(res, "success", False) or not isinstance(data, dict):
        st["status"] = "error"
        return None, []
    returned = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("url")]
    fresh = [r for r in returned if str(r["url"]) not in seen]
    seen.update(str(r["url"]) for r in fresh)
    new = [r for r in fresh if keep is None or keep(r)]
    st.update({"status": "ok" if returned else "empty", "returned": len(returned), "new": len(fresh), "kept": len(new)})
    if not new:
        return None, []
    key = state.add_result(
        state.next_key(phase, WEB_TOOL), _filtered_result(res, {**data, "results": new}), phase=phase, purpose=purpose
    )
    return key, new


def query_entities(ctx: Any) -> dict[str, list[str]]:
    """Concepts, equations, materials, constants, systems, and symbols from the question context."""
    concepts: list[str] = []
    if getattr(ctx, "primary_concept", None):
        concepts.append(str(ctx.primary_concept))
    if getattr(ctx, "primary_symbol", None):
        concepts.append(str(ctx.primary_symbol))
    for e in list(getattr(ctx, "concepts", None) or getattr(ctx, "genes", None) or []):
        concepts.append(getattr(e, "label", "") or getattr(e, "mention", "") or str(e))
    equations = [getattr(e, "mention", "") or getattr(e, "label", "") or str(e) for e in list(getattr(ctx, "equations", None) or [])]
    materials = [getattr(e, "mention", "") or getattr(e, "label", "") or str(e) for e in list(getattr(ctx, "materials", None) or getattr(ctx, "drugs", None) or [])]
    systems = [getattr(e, "mention", "") or getattr(e, "label", "") or str(e) for e in list(getattr(ctx, "systems", None) or getattr(ctx, "diseases", None) or [])]
    constants = [getattr(e, "mention", "") or getattr(e, "label", "") or str(e) for e in list(getattr(ctx, "constants", None) or [])]
    quantities = [getattr(e, "mention", "") or getattr(e, "label", "") or str(e) for e in list(getattr(ctx, "quantities", None) or [])]
    for e in list(getattr(ctx, "entities", None) or []):
        etype = str(getattr(e, "type", "")).lower()
        name = getattr(e, "label", "") or getattr(e, "mention", "")
        if not name:
            continue
        if etype in ("concept", "theorem", "symbol", "gene"):
            concepts.append(name)
        elif etype in ("equation", "expression", "formula"):
            equations.append(name)
        elif etype in ("material", "compound", "drug"):
            materials.append(name)
        elif etype in ("system", "model", "disease"):
            systems.append(name)
        elif etype == "constant":
            constants.append(name)
        elif etype == "quantity":
            quantities.append(name)
        else:
            concepts.append(name)
    clean = lambda xs: list(dict.fromkeys(x.strip() for x in xs if x and x.strip()))  # noqa: E731
    c_concepts = clean(concepts)
    c_materials = clean(materials)
    c_systems = clean(systems)
    c_equations = clean(equations)
    c_constants = clean(constants)
    c_quantities = clean(quantities)
    return {
        "concepts": c_concepts,
        "equations": c_equations,
        "materials": c_materials,
        "systems": c_systems,
        "constants": c_constants,
        "quantities": c_quantities,
        "all": clean([*c_concepts, *c_equations, *c_materials, *c_systems, *c_constants, *c_quantities]),
        # Legacy aliases so existing callers continue to work seamlessly
        "genes": c_concepts,
        "drugs": c_materials or c_equations,
        "diseases": c_systems,
    }


__all__ = [
    "LEGACY_LITERATURE_TOOL",
    "LITERATURE_TOOL",
    "SPECIALIST_SPECS",
    "WEB_TOOL",
    "Specialist",
    "SpecialistSpec",
    "ask_json",
    "build_specialists",
    "classify_tool",
    "compact",
    "evidence_digest",
    "evidence_text",
    "fetch_new_literature",
    "last_ask_outcome",
    "model_failing",
    "not_requested_modules",
    "fetch_new_web",
    "iter_passages",
    "named_tool_allowed",
    "passage_identity",
    "passage_source_key",
    "query_entities",
    "resolve_literature_tool",
    "seen_passages",
    "seen_urls",
    "simulation_forbidden",
    "simulation_requested",
    "single_cell_requested",
    "stems",
    "team_specialists",
    "tool_allowed",
    "tool_source_key",
]
