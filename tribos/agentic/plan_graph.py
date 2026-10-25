"""
The planned tool DAG of the plan-and-execute phase: nodes, references between them, parsing from a model
reply, and validation against the registry and the turn's hard policy before anything runs.

Design after LLMCompiler (Kim et al., ICML 2024, arXiv:2312.04511): the planner emits numbered tasks
{id, tool, args, depends_on, purpose}; a task's arguments may name an earlier task's output with a
placeholder, and the task-fetching unit (executor.py) fills the placeholder when that task finishes. Planning
the whole chain up front with evidence variables is ReWOO (Xu et al. 2023, arXiv:2305.18323).

Reference syntax (the exact grammar the planner is told about)
--------------------------------------------------------------
    ref      := "$" node_id path | "${" node_id path "}"
    node_id  := a node id of this plan (or of an earlier round), e.g. n1; a bare number "$1" means "n1"
    path     := ( "." segment | "[" index "]" )*
    segment  := a dict key ([A-Za-z_][A-Za-z0-9_-]*), a list index (-?digits) or "*"

- The path starts at the node's ToolResult.data. A first segment "data" or "canonical_ids" addresses that
  ToolResult field explicitly ("$n1.data.results.0.id" and "$n1.results.0.id" are the same value).
- "*" maps the rest of the path over every item of a list ("$n1.results.*.id" is the list of ids).
- An argument whose whole string is one reference takes the referenced value with its JSON type (a dict,
  list, number or string). A reference inside a longer string is replaced by the value's text (a list is
  joined with ", ", a dict is JSON).
- "$name" where name is not a node id is ordinary text and left unchanged.
- A reference adds an implicit dependency on its node, as LLMCompiler infers dependencies from placeholders.

Validation (validate_plan) rejects a node, with a reason, when its tool is not registered, its arguments do
not match the tool's input schema (unknown names, wrong types, missing required fields; fields holding a
reference are checked again after resolution), it breaks the hard policy (no simulation tool when the user
forbade simulation; only allowlisted sources on a "papers only" turn; no web tool with web search off; no
source the researcher switched off), it repeats a call the pipeline or an earlier node already made, it is
part of a dependency cycle, it depends on a rejected or unknown node, or it falls beyond max_plan_nodes.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..tools.arg_repair import repair_arguments

logger = logging.getLogger(__name__)

NODE_STATUSES = ("pending", "running", "done", "error", "skipped")
# Arguments that would collide with AgentState.call_tool's own keyword parameters.
RESERVED_ARGS = frozenset({"phase", "purpose", "key", "store", "tool_name"})

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")
_SEG = r"(?:\.(?:[A-Za-z_][A-Za-z0-9_\-]*|-?\d+|\*)|\[(?:-?\d+|\*)\])"
_REF_RE = re.compile(
    r"\$\{(?P<bnode>[A-Za-z][A-Za-z0-9_]*|\d+)(?P<bpath>" + _SEG + r"*)\}"
    r"|\$(?P<node>[A-Za-z][A-Za-z0-9_]*|\d+)(?P<path>" + _SEG + r"*)"
)
_SEG_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*|-?\d+|\*)|\[(-?\d+|\*)\]")


class RefError(ValueError):
    """A reference could not be resolved against the finished node results."""


class PlanNode(BaseModel):
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    purpose: str = ""
    status: str = "pending"  # pending | running | done | error | skipped
    result_key: str | None = None
    error: str | None = None
    seconds: float | None = None
    round: int = 0  # 0 = first plan, 1.. = replans
    resolved_args: dict[str, Any] | None = None  # args with references filled in, set when the node runs
    adjusted: list[str] = Field(default_factory=list)  # argument repairs (tools.arg_repair), e.g. "size 100→50"
    # Orchestration controls, kept out of the tool's arguments: the node's own deadline (seconds), enforced by the
    # executor (and passed to the tool when its schema takes a timeout).
    timeout_s: float | None = None
    # A later node that did what this failed one was for (same tool and purpose): the failure is recovered history.
    recovered_by: str | None = None

    def call_args(self) -> dict[str, Any]:
        return self.resolved_args if self.resolved_args is not None else self.args

    def to_artifact(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "tool": self.tool,
            "args": _json_safe(self.args),
            "depends_on": list(self.depends_on),
            "purpose": self.purpose,
            "status": self.status,
            "result_key": self.result_key,
            "error": self.error,
            "seconds": self.seconds,
        }
        if self.resolved_args is not None and self.resolved_args != self.args:
            out["resolved_args"] = _json_safe(self.resolved_args)
        if self.adjusted:
            out["adjusted"] = list(self.adjusted)
        if self.timeout_s is not None:
            out["timeout_s"] = self.timeout_s
        if self.recovered_by:
            out["recovered_by"] = self.recovered_by
        return out


class PlanGraph(BaseModel):
    rationale: str = ""
    nodes: list[PlanNode] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list)  # [{"node", "reason"}]

    def get(self, node_id: str) -> PlanNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def ids(self) -> list[str]:
        return [n.id for n in self.nodes]

    def reject(self, node: Any, reason: str) -> None:
        nid = node.id if isinstance(node, PlanNode) else str(node)
        self.rejected.append({"node": nid, "reason": reason[:300]})
        self.nodes = [n for n in self.nodes if n.id != nid]


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def canonical(value: Any) -> str:
    """Canonical JSON of a call's arguments, for duplicate detection."""
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


# The literature search is registered under its current name and a legacy alias that runs the same search.
LITERATURE_TOOLS = frozenset({"archivon_literature_search", "lithoscribe_literature_synthesis"})


def call_signature(tool: str, inputs: Any) -> tuple[str, str]:
    """The duplicate-detection key of a call. A literature search is one search whichever of its two names runs it,
    and is keyed by its query and sources only: asking again for fewer or more results of the same query finds
    the same papers."""
    if tool in LITERATURE_TOOLS and isinstance(inputs, dict):
        query = re.sub(r"\s+", " ", str(inputs.get("query") or "")).strip().lower()
        return "literature_search", canonical({"query": query, "sources": inputs.get("sources")})
    return tool, canonical(inputs)


def normalise_id(raw: Any) -> str:
    text = str(raw if raw is not None else "").strip().lstrip("$")
    if text.isdigit():
        return f"n{int(text)}"
    return text


# References ---------------------------------------------------------------------------------------------------
def _parse_path(path: str) -> list[Any]:
    segs: list[Any] = []
    for m in _SEG_RE.finditer(path or ""):
        seg = m.group(1) if m.group(1) is not None else m.group(2)
        if seg == "*":
            segs.append("*")
        elif re.fullmatch(r"-?\d+", seg):
            segs.append(int(seg))
        else:
            segs.append(seg)
    return segs


def _iter_refs(text: str, known: set[str] | None = None) -> Iterable[tuple[re.Match, str, list[Any]]]:
    for m in _REF_RE.finditer(text):
        node = normalise_id(m.group("bnode") or m.group("node"))
        if known is not None and node not in known:
            continue
        yield m, node, _parse_path(m.group("bpath") if m.group("bnode") else m.group("path") or "")


def refs_in(value: Any, known: set[str] | None = None) -> set[str]:
    """Node ids referenced anywhere in an argument value (only ids in `known` when given)."""
    out: set[str] = set()
    if isinstance(value, str):
        out.update(node for _m, node, _p in _iter_refs(value, known))
    elif isinstance(value, dict):
        for v in value.values():
            out |= refs_in(v, known)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= refs_in(v, known)
    return out


# Field names planners guess for a result they cannot see ("$n1.results", "$n1.items.0.name"), mapped to what the
# tools actually return. Only used when the guessed field is missing, so exact paths always win.
_COLLECTION_GUESSES = {"results", "result", "items", "records", "hits", "data", "entries", "list", "rows", "outputs"}
_FIELD_ALIASES = {
    "name": ("pref_name", "drug_name", "query_name", "label", "symbol", "title"),
    "drug": ("pref_name", "drug_name", "query_name"),
    "id": ("chembl_id", "id", "accession", "nct_id", "pmid", "ensembl_id"),
    "chembl": ("chembl_id",),
    "smiles": ("canonical_smiles", "smiles"),
}


def _field_alias(value: dict[str, Any], seg: str) -> str | None:
    """The real field a guessed name most plausibly means, or None when nothing fits unambiguously."""
    low = seg.lower()
    if low in _COLLECTION_GUESSES:
        lists = [k for k, v in value.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if len(lists) == 1:
            return lists[0]
        return None
    for cand in _FIELD_ALIASES.get(low, ()):
        if cand in value and value[cand] not in (None, "", []):
            return cand
    return None


def _navigate(value: Any, segs: Sequence[Any], where: str) -> Any:
    for i, seg in enumerate(segs):
        if seg == "*":
            if not isinstance(value, list):
                raise RefError(f"{where}: '*' needs a list")
            out = []
            for item in value:
                try:
                    out.append(_navigate(item, segs[i + 1:], where))
                except RefError:
                    continue
            return out
        if isinstance(value, dict):
            if seg in value:
                value = value[seg]
            elif str(seg) in value:
                value = value[str(seg)]
            elif (alias := _field_alias(value, str(seg))) is not None:
                value = value[alias]
            else:
                raise RefError(f"{where}: no field '{seg}'")
        elif isinstance(value, list):
            if not isinstance(seg, int):
                raise RefError(f"{where}: '{seg}' is not a list index")
            try:
                value = value[seg]
            except IndexError as exc:
                raise RefError(f"{where}: index {seg} out of range ({len(value)} items)") from exc
        else:
            raise RefError(f"{where}: cannot read '{seg}' of a {type(value).__name__}")
    return value


def lookup(results: dict[str, Any], node: str, segs: Sequence[Any]) -> Any:
    """The value a reference names: path into the node's ToolResult.data (or an explicit ToolResult field)."""
    if node not in results:
        raise RefError(f"${node} has no result")
    res = results[node]
    where = f"${node}"
    segs = list(segs)
    if segs and segs[0] in ("data", "canonical_ids") and hasattr(res, segs[0]):
        root = getattr(res, segs[0])
        segs = segs[1:]
    else:
        root = getattr(res, "data", res) if hasattr(res, "data") else res
    value = _navigate(root, segs, where)
    if value is None or value == "" or (isinstance(value, (list, dict)) and not value):
        # An empty list or string is no input either (e.g. no drugs were found): the step is skipped, not run
        # with [] and rejected by the tool's schema.
        raise RefError(f"{where}: value is empty")
    return value


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def resolve_args(value: Any, results: dict[str, Any], known: set[str] | None = None) -> Any:
    """A deep copy of value with every reference to a node in `results` (or `known`) substituted."""
    known = set(known) if known is not None else set(results)
    if isinstance(value, str):
        matches = list(_iter_refs(value, known))
        if not matches:
            return value
        if len(matches) == 1 and matches[0][0].span() == (0, len(value)):
            _m, node, segs = matches[0]
            return copy.deepcopy(lookup(results, node, segs))
        out, last = [], 0
        for m, node, segs in matches:
            out.append(value[last:m.start()])
            out.append(_as_text(lookup(results, node, segs)))
            last = m.end()
        out.append(value[last:])
        return "".join(out)
    if isinstance(value, dict):
        return {k: resolve_args(v, results, known) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_args(v, results, known) for v in value]
    return copy.deepcopy(value)


# Parsing ------------------------------------------------------------------------------------------------------
def _first(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def parse_plan(value: Any, *, round_no: int = 0, taken_ids: set[str] | None = None) -> PlanGraph:
    """A PlanGraph from a planner reply ({"rationale", "nodes"|"tasks"|"plan"} or a bare list of nodes).

    Malformed entries are listed in `rejected`. Ids are normalised ("1" -> "n1"). In a replan, a new node
    whose id is already used by an earlier round (`taken_ids`) is renamed "r<round>_<id>"; references and
    depends_on entries naming that id keep pointing at the earlier round's node, which is the one the
    planner was shown.
    """
    taken = set(taken_ids or ())
    graph = PlanGraph()
    if isinstance(value, dict):
        graph.rationale = str(_first(value, "rationale", "reasoning", "thought") or "")[:1200]
        raw_nodes = _first(value, "nodes", "tasks", "plan", "steps")
    else:
        raw_nodes = value
    if raw_nodes is None:
        return graph
    if not isinstance(raw_nodes, list):
        graph.rejected.append({"node": "?", "reason": "the plan's nodes were not a list"})
        return graph

    staged: list[tuple[PlanNode, str]] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_nodes, 1):
        if not isinstance(raw, dict):
            graph.rejected.append({"node": f"#{i}", "reason": "node is not an object"})
            continue
        orig = normalise_id(_first(raw, "id", "node", "task_id") or f"n{i}")
        tool = str(_first(raw, "tool", "tool_name", "name", "function") or "").strip()
        args = _first(raw, "args", "arguments", "input", "parameters")
        deps = _first(raw, "depends_on", "deps", "dependencies", "dependency") or []
        if not _ID_RE.match(orig):
            graph.rejected.append({"node": orig[:40] or f"#{i}", "reason": "invalid node id"})
            continue
        if orig in seen:
            graph.rejected.append({"node": orig, "reason": "duplicate node id in the plan"})
            continue
        seen.add(orig)
        if not tool:
            graph.rejected.append({"node": orig, "reason": "node names no tool"})
            continue
        if args is None:
            args = {}
        if not isinstance(args, dict):
            graph.rejected.append({"node": orig, "reason": "args must be an object"})
            continue
        if isinstance(deps, (str, int)):
            deps = [deps]
        if not isinstance(deps, list):
            deps = []
        nested = args.get("depends_on") if isinstance(args.get("depends_on"), (list, str)) else None
        if nested is not None:
            # A node-level field written inside args by mistake: it orders the plan, it is not a tool argument.
            args = {k: v for k, v in args.items() if k != "depends_on"}
            deps = [*deps, *([nested] if isinstance(nested, str) else nested)]
        nid = orig
        if nid in taken:
            nid = f"r{round_no}_{orig}"
            k = 2
            while nid in taken or nid in seen:
                nid = f"r{round_no}_{orig}_{k}"
                k += 1
        taken.add(nid)
        node = PlanNode(
            id=nid,
            tool=tool,
            args=args,
            depends_on=[normalise_id(d) for d in deps if str(d).strip()],
            purpose=str(_first(raw, "purpose", "description", "why") or "")[:240],
            round=round_no,
            timeout_s=_as_seconds(_first(raw, "timeout_s", "timeout", "timeout_seconds")),
        )
        staged.append((node, orig))

    for node, _orig in staged:
        graph.nodes.append(node)
    return graph


# Policy -------------------------------------------------------------------------------------------------------
# The pipeline source (ctx.decisions / ctx.source_allowlist key) each tool's evidence counts as, where it differs
# from the tool's registry domain.
TOOL_SOURCES: dict[str, str] = {
    "lithoscribe_literature_synthesis": "lithoscribe",
    "websurfer_search": "websurfer",
}
# Registry domains whose decision key has another name ("analysis" tools are gated by the "calcula" decision).
_DOMAIN_SOURCES: dict[str, str] = {"analysis": "calcula"}


def tool_source(entry: Any) -> str:
    name = str(getattr(entry, "name", entry) or "")
    if name in TOOL_SOURCES:
        return TOOL_SOURCES[name]
    if name.startswith("vivarix") or "calibrat" in name:
        return "vivarix"
    domain = str(getattr(entry, "domain", "") or name.split("_", 1)[0]).lower()
    return _DOMAIN_SOURCES.get(domain, domain)


# Tool capabilities (SUP-3) -----------------------------------------------------------------------------------
# What a tool does, read from its registry entry (domain, name and tags) rather than from one regex per caller:
# plan approval asks before EXPENSIVE work, the "no simulation" ban removes SIMULATION tools, and the "no code
# execution" request removes EXECUTES_CODE tools. A registry tag with the capability's name always adds it.
EXECUTES_CODE = "executes_code"
SIMULATION = "simulation"
EXPENSIVE = "expensive"
CAPABILITIES = (EXECUTES_CODE, SIMULATION, EXPENSIVE)
# Dynamis (numerical ODE simulation, equilibria, scans, fitting, optimisation, root finding) and its Vivarix aliases:
# every one of them is a numerical model run, so a "no simulation" question runs none of them.
SIMULATION_DOMAINS = frozenset({"dynamis", "vivarix"})
_CODE_DOMAINS = frozenset({"analysis", "calcula", "sandbox"})
# Simulation work long enough to need approval: integrations, sweeps, fits, calibrations and optimisations. A single
# equilibrium or root solve is cheap.
_HEAVY_SIMULATION_RE = re.compile(r"simulat|scan|sweep|fit|calibrat|optimi[sz]")


def tool_capabilities(tool: Any, entry: Any = None) -> frozenset[str]:
    """The capability set of a tool, given its registry entry or name (with the entry, when known, as `entry`)."""
    entry = entry if entry is not None else (None if isinstance(tool, str) else tool)
    name = str(getattr(entry, "name", None) or getattr(tool, "name", tool) or "").lower()
    domain = str(getattr(entry, "domain", "") or name.split("_", 1)[0]).lower()
    tags = {str(t).lower() for t in (getattr(entry, "tags", None) or [])}
    caps = {c for c in CAPABILITIES if c in tags and c != SIMULATION}  # "simulation" is also a search tag
    if (domain in _CODE_DOMAINS and "run_" in name) or name.endswith("run_python") or "sagemath" in name:
        caps.add(EXECUTES_CODE)
    if domain in SIMULATION_DOMAINS or name.startswith(("dynamis_", "vivarix_")) or "calibrat" in name or "simulat" in name:
        caps.add(SIMULATION)
    if EXECUTES_CODE in caps or name.startswith("vivarix_") or (SIMULATION in caps and _HEAVY_SIMULATION_RE.search(name)):
        caps.add(EXPENSIVE)
    return frozenset(caps)


def is_simulation_tool(tool: Any, entry: Any = None) -> bool:
    return SIMULATION in tool_capabilities(tool, entry)


def executes_code(tool: Any, entry: Any = None) -> bool:
    return EXECUTES_CODE in tool_capabilities(tool, entry)


def is_expensive_tool(tool: Any, entry: Any = None) -> bool:
    """Tools that need the researcher's approval on an interactive run: code execution (sandboxed Python, SageMath)
    and long numerical runs (ODE integrations, parameter scans, fits, calibrations, optimisations)."""
    return EXPENSIVE in tool_capabilities(tool, entry)


def simulation_banned(ctx: Any) -> bool:
    constraints = getattr(ctx, "simulation_constraints", None)
    return bool(getattr(ctx, "suppress_simulation", False) or getattr(constraints, "simulation_forbidden", False))


# Sources a "no outside evidence needed" decision (ctx.evidence_need.skip_retrieval) rules out.
RETRIEVAL_SOURCES = frozenset({"archivon", "lithoscribe", "websurfer"})


def single_cell_dataset_path(ctx: Any) -> str | None:
    """The AnnData file Lumicell may read this turn: the researcher's attached .h5ad or a typed path that already
    passed is_allowed_typed_path. None when neither exists; a path written by the model is never used."""
    for att in getattr(ctx, "attachments", None) or []:
        if getattr(att, "kind", "") == "h5ad" and getattr(att, "analysis_path", None):
            return str(att.analysis_path)
    typed = getattr(ctx, "dataset_path", None)
    return typed if isinstance(typed, str) and typed.strip() else None


def excluded_by_question(entry: Any, ctx: Any) -> str | None:
    """Why the question's own exclusions ("No simulation or hypothesis generation is needed") rule this tool out, or
    None."""
    excluded = getattr(ctx, "excluded_modules", None) or set()
    if "simulation" in excluded and is_simulation_tool(entry, None if isinstance(entry, str) else entry):
        return "simulation was excluded at your request"
    return None


def policy_violation(entry: Any, ctx: Any) -> str | None:
    """Why the turn's hard policy forbids this tool, or None."""
    if ctx is None:
        return None
    tool_entry = None if isinstance(entry, str) else entry
    if is_simulation_tool(entry, tool_entry) and simulation_banned(ctx):
        return "simulation was forbidden for this question"
    if executes_code(entry, tool_entry) and (getattr(ctx, "extras", None) or {}).get("code_analysis_forbidden"):
        return "the researcher asked for no code execution"
    source = tool_source(entry)
    from ..agents.evidence_need import external_retrieval_block

    blocked = external_retrieval_block(ctx, tool_entry if tool_entry is not None else entry)
    if blocked:
        return blocked
    need = getattr(ctx, "evidence_need", None)
    if source in RETRIEVAL_SOURCES and need is not None and getattr(need, "skip_retrieval", False):
        return str(getattr(need, "reason", "") or "no outside evidence is needed for this question")
    allow = getattr(ctx, "source_allowlist", None)
    if allow is not None and source not in allow:
        reason = getattr(ctx, "source_restriction_reason", "") or "restricted sources"
        return f"source '{source}' is outside this turn's restriction ({reason})"
    if source == "websurfer" and not getattr(ctx, "enable_web_search", True):
        return "web search is switched off"
    if source == "lumicell" and (getattr(ctx, "extras", {}) or {}).get("single_cell_forbidden"):
        return "single-cell analysis was excluded at your request"
    if source == "lumicell" and not single_cell_dataset_path(ctx):
        return "no single-cell dataset (.h5ad) is attached"
    excluded = excluded_by_question(entry, ctx)
    if excluded:
        return excluded
    decision = (getattr(ctx, "decisions", {}) or {}).get(source)
    if decision is not None and not getattr(decision, "run", True) and "switched off" in str(getattr(decision, "reason", "")):
        return f"source '{source}' was switched off by the researcher"
    return None


# Schema checks ------------------------------------------------------------------------------------------------
def schema_problem(entry: Any, args: dict[str, Any], ref_fields: set[str]) -> str | None:
    """A validation problem with args against the tool's input schema, ignoring fields that hold references."""
    schema = getattr(entry, "input_schema", None)
    if schema is None:
        return None
    fields = getattr(schema, "model_fields", {}) or {}
    extra_ok = str((getattr(schema, "model_config", {}) or {}).get("extra", "")) == "allow"
    unknown = [k for k in args if k not in fields]
    if unknown and not extra_ok:
        return f"unknown argument(s) {', '.join(sorted(unknown)[:5])}; the tool takes {', '.join(fields) or 'none'}"
    plain = {k: v for k, v in args.items() if k not in ref_fields}
    try:
        schema.model_validate(plain)
    except ValidationError as exc:
        errs = [e for e in exc.errors() if not (e.get("loc") and str(e["loc"][0]) in ref_fields)]
        if errs:
            first = errs[0]
            loc = ".".join(str(x) for x in first.get("loc", ())) or "args"
            return f"argument {loc}: {first.get('msg', 'invalid')}"
    except Exception as exc:  # noqa: BLE001
        return f"arguments could not be checked: {exc}"
    return None


def validated_inputs(entry: Any, args: dict[str, Any]) -> dict[str, Any] | None:
    """The tool's validated kwargs (as the registry records them), or None when they do not validate."""
    schema = getattr(entry, "input_schema", None)
    if schema is None:
        return dict(args)
    try:
        return _json_safe(schema.model_validate(args).model_dump())
    except Exception:  # noqa: BLE001
        logger.debug("Arguments do not validate as given; trying the repaired ones", exc_info=True)
    # The registry repairs trivially fixable arguments before running the tool; the call it makes is this one.
    repaired = repair_arguments(schema, args)
    if repaired is None:
        return None
    try:
        return _json_safe(schema.model_validate(repaired[0]).model_dump())
    except Exception:  # noqa: BLE001
        logger.debug("Repaired arguments do not validate either", exc_info=True)
        return None


# Cycles -------------------------------------------------------------------------------------------------------
def topological_order(nodes: Sequence[PlanNode], external: set[str] | None = None) -> tuple[list[str], set[str]]:
    """(order, cyclic): Kahn's algorithm over in-plan dependencies; ids left over sit on or behind a cycle."""
    external = external or set()
    ids = {n.id for n in nodes}
    indeg = {n.id: 0 for n in nodes}
    children: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for d in n.depends_on:
            if d in ids and d not in external:
                indeg[n.id] += 1
                children[d].append(n.id)
    queue = [n.id for n in nodes if indeg[n.id] == 0]
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for c in children[cur]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    return order, ids - set(order)


def _cycle_members(nodes: Sequence[PlanNode], leftover: set[str]) -> set[str]:
    """The leftover ids that lie on a cycle (the rest only depend on one)."""
    deps = {n.id: [d for d in n.depends_on if d in leftover] for n in nodes if n.id in leftover}
    on_cycle: set[str] = set()
    for start in leftover:
        stack, seen = list(deps.get(start, [])), set()
        while stack:
            cur = stack.pop()
            if cur == start:
                on_cycle.add(start)
                break
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(deps.get(cur, []))
    return on_cycle


# Validation ---------------------------------------------------------------------------------------------------
# Deadline fields a planner writes; they control how the step runs, so they are never dropped as unknown arguments.
TIMEOUT_KEYS = ("timeout_s", "timeout", "timeout_seconds", "time_limit", "time_limit_s", "deadline_s", "max_seconds")


def _as_seconds(value: Any) -> float | None:
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return None
    return secs if 0 < secs <= 3600 else None


def move_orchestration_args(node: PlanNode, entry: Any) -> None:
    """Move deadline fields the planner wrote into a tool's args out of them: they become the node's deadline, and are
    passed to the tool's own timeout argument when its schema has one ("timeout_seconds" -> "timeout_s"). Every move
    is recorded in `node.adjusted`, so nothing that affects execution is removed silently."""
    schema = getattr(entry, "input_schema", None)
    fields = getattr(schema, "model_fields", {}) or {}
    tool_timeout = next((f for f in ("timeout_s", "timeout", "timeout_seconds") if f in fields), None)
    for key in [k for k in node.args if k in TIMEOUT_KEYS and k not in fields]:
        raw = node.args.pop(key)
        secs = _as_seconds(raw)
        if secs is None:
            node.adjusted.append(f"ignored {key}={str(raw)[:20]!r} (not a number of seconds)")
            continue
        if node.timeout_s is None:
            node.timeout_s = secs
        if tool_timeout and tool_timeout not in node.args:
            annotation = str(getattr(fields[tool_timeout], "annotation", ""))
            node.args[tool_timeout] = int(round(secs)) if "int" in annotation else secs
            node.adjusted.append(f"{key} → {tool_timeout}")
        else:
            node.adjusted.append(f"{key} applied as the step deadline ({secs:g} s)")


# Capability words in an unregistered tool name -> the registered tool that provides that capability.
_CAPABILITY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(?:web|google|bing|internet|browse|browser|online|url|site)"), "websurfer_search"),
    (re.compile(r"(?i)(?:literature|papers?|arxiv|scholar|semantic|pubmed|crossref|publications?|citations?)"),
     "archivon_literature_search"),
)


def capability_alias(name: str, registry: Any, ctx: Any) -> tuple[str | None, str | None]:
    """(registered tool, why this turn forbids it or None) for an unregistered name that asks for a known capability
    ("web_search" -> websurfer_search); (None, None) when no registered tool provides it."""
    words = re.sub(r"[_\-.]+", " ", str(name or ""))
    for rx, target in _CAPABILITY_ALIASES:
        entry = registry.get_entry(target) if registry is not None and rx.search(words) else None
        if entry is not None:
            return target, policy_violation(entry, ctx)
    return None, None


def validate_plan(
    graph: PlanGraph,
    registry: Any,
    ctx: Any = None,
    *,
    max_nodes: int = 12,
    prior_calls: Iterable[tuple[str, dict[str, Any]]] | None = None,
    external_ids: set[str] | None = None,
) -> PlanGraph:
    """Drop every node that may not run (see the module docstring); keeps the rest in dependency order.

    prior_calls: (tool_name, validated inputs) of calls already made this turn (pipeline and earlier nodes).
    external_ids: ids of finished nodes from earlier rounds that this plan may depend on and reference.
    """
    external = set(external_ids or ())
    seen_calls: set[tuple[str, str]] = {call_signature(t, a) for t, a in (prior_calls or [])}

    def all_known() -> set[str]:
        return set(graph.ids()) | external

    # 1. Per-node checks: tool, policy, arguments, references, duplicates.
    for node in list(graph.nodes):
        entry = registry.get_entry(node.tool) if registry is not None else None
        if entry is None:
            # Audit I34: an invented name ("web_search") for a registered capability runs under the registered name
            # only when this turn allows that capability; otherwise the rejection says which policy forbids it.
            target, blocked = capability_alias(node.tool, registry, ctx)
            if target is None:
                graph.reject(node, f"tool '{node.tool}' is not registered (no registered tool provides it)")
                continue
            if blocked:
                graph.reject(node, f"tool '{node.tool}' is not registered; the registered '{target}' is not allowed "
                                   f"this turn: {blocked}")
                continue
            node.adjusted.append(f"tool '{node.tool}' → registered '{target}'")
            node.tool, entry = target, registry.get_entry(target)
        violation = policy_violation(entry, ctx)
        if violation:
            graph.reject(node, f"policy: {violation}")
            continue
        clash = sorted(RESERVED_ARGS & set(node.args))
        if clash:
            graph.reject(node, f"argument name(s) {', '.join(clash)} are reserved")
            continue
        known = all_known()
        referenced = refs_in(node.args, known)
        if node.id in referenced or node.id in node.depends_on:
            graph.reject(node, "node depends on itself")
            continue
        for r in sorted(referenced):
            if r not in node.depends_on:
                node.depends_on.append(r)  # LLMCompiler: a placeholder is a dependency
        unknown = [d for d in node.depends_on if d not in known]
        if unknown:
            graph.reject(node, f"depends on unknown node(s) {', '.join(unknown)}")
            continue
        move_orchestration_args(node, entry)
        ref_fields = {k for k, v in node.args.items() if refs_in(v, known)}
        problem = schema_problem(entry, node.args, ref_fields)
        if problem:
            # One conservative repair (limits clamped to their bounds, over-long lists cut, {"name": ..} objects
            # where a string is expected, unknown arguments dropped) before the node is rejected.
            fixed = repair_arguments(getattr(entry, "input_schema", None), node.args, drop_unknown=True,
                                     ignore_fields=ref_fields)
            if fixed is not None and schema_problem(entry, fixed[0], ref_fields) is None:
                node.args, node.adjusted = fixed[0], [*node.adjusted, *fixed[1]]
                problem = None
        if problem:
            graph.reject(node, f"schema: {problem}")
            continue
        if not ref_fields:
            inputs = validated_inputs(entry, node.args)
            sig = call_signature(node.tool, inputs if inputs is not None else node.args)
            if sig in seen_calls:
                graph.reject(node, "an identical call was already made this turn")
                continue
            seen_calls.add(sig)

    # 2. Cycles.
    order, leftover = topological_order(graph.nodes, external)
    if leftover:
        cyclic = _cycle_members(graph.nodes, leftover)
        for nid in sorted(cyclic):
            graph.reject(nid, "dependency cycle")

    # 3. Dependents of rejected nodes (repeat until stable).
    changed = True
    while changed:
        changed = False
        alive = all_known()
        for node in list(graph.nodes):
            missing = [d for d in node.depends_on if d not in alive]
            if missing:
                graph.reject(node, f"depends on rejected node(s) {', '.join(missing)}")
                changed = True

    # 4. Order and cap.
    order, _left = topological_order(graph.nodes, external)
    by_id = {n.id: n for n in graph.nodes}
    ordered = [by_id[i] for i in order if i in by_id]
    cap = max(0, int(max_nodes))
    for node in ordered[cap:]:
        graph.rejected.append({"node": node.id, "reason": f"plan node cap of {cap} reached"})
    graph.nodes = ordered[:cap]
    return graph


def drop_nodes(graph: PlanGraph, ids: Iterable[str], reason: str) -> list[str]:
    """Remove nodes (and, transitively, every node depending on them); returns the removed ids."""
    removed: list[str] = []
    targets = {i for i in ids if graph.get(i) is not None}
    for nid in sorted(targets):
        graph.reject(nid, reason)
        removed.append(nid)
    changed = bool(removed)
    while changed:
        changed = False
        gone = set(removed)
        for node in list(graph.nodes):
            hit = [d for d in node.depends_on if d in gone]
            if hit:
                graph.reject(node, f"depends on dropped node(s) {', '.join(hit)}")
                removed.append(node.id)
                changed = True
    return removed


__all__ = [
    "CAPABILITIES",
    "EXECUTES_CODE",
    "EXPENSIVE",
    "LITERATURE_TOOLS",
    "NODE_STATUSES",
    "SIMULATION",
    "drop_nodes",
    "PlanGraph",
    "PlanNode",
    "RefError",
    "TOOL_SOURCES",
    "call_signature",
    "canonical",
    "executes_code",
    "is_expensive_tool",
    "is_simulation_tool",
    "simulation_banned",
    "tool_capabilities",
    "lookup",
    "normalise_id",
    "parse_plan",
    "policy_violation",
    "refs_in",
    "resolve_args",
    "schema_problem",
    "tool_source",
    "topological_order",
    "validate_plan",
    "validated_inputs",
]
