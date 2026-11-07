"""
Planner and joiner prompts for the plan-and-execute phase.

- The planner ([phase:plan_execute]) writes a DAG of tool calls in the LLMCompiler format (Kim et al.,
  ICML 2024, arXiv:2312.04511): numbered nodes {id, tool, args, depends_on, purpose} whose args may reference
  earlier outputs as "$n1.path". Its system prompt opens with the Plan-and-Solve trigger (Wang et al.,
  ACL 2023, arXiv:2305.04091). Planning everything up front is ReWOO (arXiv:2305.18323); with
  TRIBOS_AGENT_PLAN_MODE=react the same prompt asks for one next node at a time and sees each
  observation, the ReAct loop (Yao et al., ICLR 2023, arXiv:2210.03629).
- The planner sees only the tools retrieve_tools() picks for the question and its sub-questions, as
  schema-accurate tool cards (Gorilla, arXiv:2305.15334; ToolLLM's API retriever, arXiv:2307.16789), plus a
  compact summary of what the pipeline already found. Free text from tool outputs is spotlighted
  (guardrails.spotlight) so instructions inside retrieved content are never followed.
- The joiner ([phase:plan_join]) reads the node observations and decides "finish" or "replan" (LLMCompiler's
  joiner), naming what is still missing.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from .guardrails import SPOTLIGHT_RULE, neutralise, spotlight
from .plan_graph import PlanGraph, policy_violation
from .specialists import LEGACY_LITERATURE_TOOL, resolve_literature_tool
from .specialists import LITERATURE_TOOL as LITERATURE_TOOL
from .tool_retrieval import retrieve_tools, tool_card

logger = logging.getLogger(__name__)

PLAN_PHASE = "plan_execute"
JOIN_PHASE = "plan_join"

# Identifier fields worth showing the planner from a result's list items (the first two present per item).
_ID_FIELDS = (
    "id", "arxiv_id", "doi", "zbl_id", "mr_id", "bibcode", "openalex_id", "oeis_id", "mp_id", "material_id",
    "system", "equation", "expression", "name", "symbol", "title", "model_id", "accession",
)
_MAX_SUMMARY_RESULTS = 24

PLAN_SYSTEM = """[phase:plan_execute]
You are the planning agent of a mathematics, physics and engineering research assistant. Let's first understand the problem and devise a plan to solve the problem. Then, let's carry out the plan and solve the problem step by step.

The research pipeline has already run its standard searches; their results are summarised for you. Your job is to plan the FOLLOW-UP tool calls that would fill what is still missing for the question and its sub-questions, as a small DAG in the LLMCompiler format:
- Each node is {"id": "n1", "tool": "<tool name>", "args": {...}, "depends_on": ["..."], "purpose": "<why, one line; name the sub-question id if any>"}, optionally with "timeout_s": <seconds> for the node's deadline. "depends_on" and "timeout_s" belong on the node, never inside "args"; "args" holds only the tool's own arguments.
- To give a computation script earlier results, pass them as data in the script tool's "inputs" argument (e.g. "inputs": {"trajectory": "$n2.time_series"}); never paste data, arrays or tables into the code. Scripts must stay under 20,000 characters.
- Use ONLY the tools listed in <tools>, with EXACTLY the argument names and types of their cards. Required arguments must be present.
- An argument may use an earlier node's output: "$n1.solutions[0]" (path into that node's result data; list indexes are numbers, "[*]" maps over a list, e.g. "$n1.papers[*].arxiv_id"). Use only the paths listed in that tool's "returns"; never invent field names such as "results". A whole-string reference keeps the value's type. Referencing a node makes it a dependency.
- Nodes without dependencies between them run in parallel, so keep chains short and only add depends_on when a node truly needs another's output.
- Never repeat a call the pipeline already made with the same arguments, and do not plan a call whose answer is already in the pipeline results.
- A request for computed results (an error between two methods, residuals, step-size or grid convergence, an energy balance, a parameter study) is filled by a computation call such as sandboxed Python, never by a search. Plan it whenever the question asks for those numbers and no pipeline result already reports them. Keep each script short and focused (well under 300 lines).
- Every call computes the actual system or quantity the question states. Never call a tool on a placeholder, proxy, stand-in or made-up model (for example a guessed formula standing in for an energy integral, or a probe value): when no tool computes the real quantity directly, plan a sandboxed Python script that does, or leave it out.
- At most @MAX_NODES@ nodes. If the pipeline results already cover the question, return an empty node list.
- Respect the constraints listed in <constraints>; tools they forbid are not offered.
@MODE_RULE@
@SPOTLIGHT_RULE@

Reply with only a JSON object: {"rationale": "<one or two sentences>", "nodes": [ ... ]}"""

REACT_RULE = (
    "- This is step-by-step (ReAct) mode: return AT MOST ONE node, the single next action, after reading the "
    "observations of the previous steps. Return an empty node list when nothing more is needed."
)

JOIN_SYSTEM = """[phase:plan_join]
You are the joiner of a plan-and-execute research agent (LLMCompiler). You read the question, the sub-questions and the observations of the tool calls that were just run, and decide whether the evidence is now sufficient to write the answer ("finish") or whether a new plan of tool calls is needed ("replan"). Replan only when a specific, still-missing piece of evidence could be fetched with the available tools; a failed call that cannot succeed with other arguments is not a reason to replan.
@SPOTLIGHT_RULE@

Reply with only a JSON object: {"decision": "finish" | "replan", "reason": "<one sentence>", "missing": ["<what is missing>", ...]}"""


def _id_values(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return [str(item)[:60]] if isinstance(item, (str, int, float)) else []
    out = []
    for f in _ID_FIELDS:
        v = item.get(f)
        if v not in (None, "", [], {}):
            out.append(f"{f}={str(v)[:60]}")
        if len(out) >= 2:
            break
    return out


def summarise_result(res: Any) -> dict[str, Any]:
    """Compact summary of one ToolResult: success, error type, ids and the sizes of its list fields."""
    out: dict[str, Any] = {"tool": getattr(res, "tool_name", ""), "success": bool(getattr(res, "success", False))}
    if not out["success"]:
        et = getattr(res, "error_type", None)
        out["error_type"] = getattr(et, "value", et)
        out["error"] = str(getattr(res, "error", "") or "")[:160]
        return out
    ids = getattr(res, "canonical_ids", None) or {}
    if ids:
        out["ids"] = {str(k): str(v)[:60] for k, v in list(ids.items())[:4]}
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        fields: dict[str, Any] = {}
        for k, v in list(data.items())[:30]:
            if isinstance(v, list):
                sample = [s for item in v[:3] for s in _id_values(item)][:4]
                fields[k] = {"count": len(v), **({"first": sample} if sample else {})}
            elif isinstance(v, (str, int, float, bool)) and (k in _ID_FIELDS or k.endswith(("_id", "_name"))):
                fields[k] = str(v)[:80]
        if fields:
            out["data"] = fields
    elif isinstance(data, list):
        out["data"] = {"count": len(data)}
    return out


def pipeline_summary(tool_results: dict[str, Any], skip_prefix: str = "agent.plan_execute.") -> dict[str, Any]:
    """Which tool_results keys exist, which succeeded or failed, and the key ids each one found."""
    out: dict[str, Any] = {}
    for key, res in list(tool_results.items()):
        if skip_prefix and str(key).startswith(skip_prefix):
            continue
        try:
            out[str(key)] = summarise_result(res)
        except Exception as exc:  # noqa: BLE001
            out[str(key)] = {"success": False, "error": f"unreadable result ({type(exc).__name__})"}
        if len(out) >= _MAX_SUMMARY_RESULTS:
            break
    return out


def _file_label(name: Any) -> str:
    """An attached file's name for the planner prompt: plain filename characters only (it is user-supplied)."""
    return re.sub(r"[^\w .()\-]+", "", neutralise(str(name or "")))[:80].strip() or "unnamed"


def constraint_lines(ctx: Any, max_nodes: int) -> list[str]:
    lines = [f"plan at most {max_nodes} nodes"]
    if ctx is None:
        return lines
    if getattr(ctx, "suppress_simulation", False):
        lines.append("simulation was forbidden by the user: no simulation tools")
    allow = getattr(ctx, "source_allowlist", None)
    if allow is not None:
        lines.append(f"only these sources may be used: {', '.join(sorted(allow))} ({getattr(ctx, 'source_restriction_reason', '')})")
    if not getattr(ctx, "enable_web_search", True):
        lines.append("web search is switched off")
    need = getattr(ctx, "evidence_need", None)
    if need is not None and getattr(need, "skip_retrieval", False):
        lines.append(f"no literature or web search: {getattr(need, 'reason', '') or 'no outside evidence is needed'}")
    if getattr(ctx, "primary_symbol", None):
        lines.append(f"primary subject: {ctx.primary_symbol}")
    system = getattr(ctx, "system_name", None) or getattr(getattr(ctx, "simulation_plan", None), "system_name", None)
    if system:
        lines.append(f"dynamical system in play: {system}")
    ids = list(getattr(ctx, "literature_ids", None) or [])
    if ids:
        lines.append(
            f"the question names these papers: {', '.join(ids)}; fetch each one with archivon_paper_details "
            "identifier=<id> (an arXiv id, DOI or zbMATH id) rather than a free-text search; a failed lookup means "
            "not retrieved, not that the paper does not exist"
        )
    attachments = [a for a in getattr(ctx, "attachments", None) or [] if getattr(a, "id", None)]
    if attachments:
        # The files the researcher attached (or the project shares): a tool that reads one needs its dataset_id.
        shown = "; ".join(
            f"{a.id} ({getattr(a, 'kind', '') or 'dataset'}: {_file_label(getattr(a, 'display_name', ''))})"
            for a in attachments[:5]
        )
        lines.append(
            f"attached files: {shown}; pass the id as dataset_id to the tools that read them (a paper: "
            "archivon_read_paper, or archivon_reproduce_paper to check its stated results; a table, HDF5 or MAT file: "
            "calcula_describe_dataset or calcula_run_python)"
        )
    excluded = sorted(getattr(ctx, "excluded_modules", None) or set())
    if excluded:
        lines.append(f"the researcher excluded: {', '.join(m.replace('_', ' ') for m in excluded)}; plan no step for them")
    return lines


def select_tools(state: Any, sub_questions: Sequence[Any], k: int = 8, per_sub: int = 3, cap: int = 12) -> list[Any]:
    """Registry entries to show the planner: retrieval over the query and each sub-question, policy-filtered."""
    registry = state.registry
    try:
        entries = registry.list_tools()
    except Exception:  # noqa: BLE001
        return []
    excluded = [e.name for e in entries if policy_violation(e, state.ctx)]
    # The legacy literature alias runs the same search as archivon_literature_search: offer only one of them.
    lit_tool = resolve_literature_tool(registry)
    if lit_tool != LEGACY_LITERATURE_TOOL:
        excluded.append(LEGACY_LITERATURE_TOOL)
    picked: list[Any] = []

    def add(found: list[Any]) -> None:
        for e in found:
            if e not in picked and len(picked) < cap:
                picked.append(e)

    query = state.clean_query or state.query
    required = []
    if re.search(r"\bMonte[ -]Carlo\b", query, re.I):
        required.append("dynamis_monte_carlo_integrate")
    if re.search(r"\bFTCS\b|heat\s+equation|\bPDE\b", query, re.I):
        required.append("dynamis_solve_pde")
    if re.search(r"\bRK4\b|fourth[ -]order\s+Runge", query, re.I):
        required.append("dynamis_simulate_ode")
    from ..physis.chemistry import is_structure_question

    if is_structure_question(query):
        required.extend(["physis_stereo", "physis_molecule"])
    if (getattr(state, "tool_results", None) or {}).get("chemistry") is not None:
        # Code already built the options' structures from their names and translated their descriptors
        # (presentation.option_stereo); a model-written SMILES of the same compounds could only contradict it.
        excluded.append("physis_stereo")
    add([e for name in required if name not in excluded and (e := registry.get_entry(name)) is not None])

    # The literature tool is always offered, unless the policy rules it out (evidence_need.skip_retrieval, "no web"...).
    add(retrieve_tools(registry, state.clean_query or state.query, k=k, exclude=excluded, always=[lit_tool]))
    for sq in sub_questions:
        text = getattr(sq, "text", "") or ""
        focus = getattr(sq, "focus", "") or ""
        if text:
            add(retrieve_tools(registry, f"{text} {focus}", k=per_sub, exclude=excluded))
    return picked


def _sub_question_lines(sub_questions: Sequence[Any]) -> list[str]:
    lines = []
    for q in sub_questions:
        deps = f" (after {', '.join(q.depends_on)})" if getattr(q, "depends_on", None) else ""
        focus = f" [focus: {q.focus}]" if getattr(q, "focus", "") else ""
        lines.append(f"- {q.id}: {q.text}{focus}{deps}")
    return lines


def steering_messages(state: Any) -> list[str]:
    out = list(state.bag.get("steering") or [])
    try:
        out.extend(state.control.peek_steering())
    except Exception:  # noqa: BLE001
        pass
    return out


def observations(graph_nodes: Sequence[Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    """What each executed node returned, for the joiner and the next planning round."""
    out = []
    for n in graph_nodes:
        row: dict[str, Any] = {"id": n.id, "tool": n.tool, "purpose": n.purpose, "status": n.status}
        if n.status == "done" and n.id in results:
            row["result"] = summarise_result(results[n.id])
        elif n.error:
            row["error"] = n.error[:200]
        out.append(row)
    return out


def build_plan_prompt(
    state: Any,
    *,
    tools: Sequence[Any],
    max_nodes: int,
    mode: str = "dag",
    previous: list[dict[str, Any]] | None = None,
    missing: list[str] | None = None,
) -> tuple:
    system = (
        PLAN_SYSTEM.replace("@MAX_NODES@", str(max_nodes))
        .replace("@MODE_RULE@", REACT_RULE if mode == "react" else "")
        .replace("@SPOTLIGHT_RULE@", SPOTLIGHT_RULE)
    )
    from ..agents.prompts import utc_date_line

    cards = [tool_card(e) for e in tools]
    parts = [utc_date_line(), f"<question>{state.clean_query or state.query}</question>"]
    if state.sub_questions:
        parts.append("<sub_questions>\n" + "\n".join(_sub_question_lines(state.sub_questions)) + "\n</sub_questions>")
    parts.append("<constraints>\n" + "\n".join(f"- {c}" for c in constraint_lines(state.ctx, max_nodes)) + "\n</constraints>")
    summary = pipeline_summary(state.tool_results)
    parts.append(
        "<pipeline_results note=\"key -> what the pipeline's own searches returned\">\n"
        + spotlight(json.dumps(summary, ensure_ascii=False, default=str), "pipeline_results", 6000)
        + "\n</pipeline_results>"
    )
    if previous:
        parts.append(
            "<previous_steps note=\"tool calls already run by this plan; reference their ids, and give new nodes "
            f"ids from n{len(previous) + 1} on\">\n"
            + spotlight(json.dumps(previous, ensure_ascii=False, default=str), "plan_observations", 5000)
            + "\n</previous_steps>"
        )
    if missing:
        parts.append("<still_missing>\n" + "\n".join(f"- {m}" for m in missing[:6]) + "\n</still_missing>")
    steer = steering_messages(state)
    if steer:
        parts.append("<researcher_instructions>\n" + "\n".join(f"- {m}" for m in steer[-6:]) + "\n</researcher_instructions>")
    parts.append("<tools>\n" + json.dumps(cards, ensure_ascii=False, default=str) + "\n</tools>")
    parts.append("Write the plan now as JSON.")
    return system, "\n\n".join(parts)


def build_join_prompt(state: Any, graph: PlanGraph, results: dict[str, Any], all_nodes: Sequence[Any]) -> tuple:
    system = JOIN_SYSTEM.replace("@SPOTLIGHT_RULE@", SPOTLIGHT_RULE)
    parts = [f"<question>{state.clean_query or state.query}</question>"]
    if state.sub_questions:
        parts.append("<sub_questions>\n" + "\n".join(_sub_question_lines(state.sub_questions)) + "\n</sub_questions>")
    if graph.rationale:
        parts.append(f"<plan_rationale>{spotlight(graph.rationale, 'planner', 600)}</plan_rationale>")
    parts.append(
        "<observations>\n"
        + spotlight(json.dumps(observations(all_nodes, results), ensure_ascii=False, default=str), "plan_observations", 6000)
        + "\n</observations>"
    )
    parts.append(
        "<pipeline_results>\n"
        + spotlight(json.dumps(pipeline_summary(state.tool_results), ensure_ascii=False, default=str), "pipeline_results", 3000)
        + "\n</pipeline_results>"
    )
    parts.append("Decide now as JSON.")
    return system, "\n\n".join(parts)


def parse_join(value: Any) -> dict[str, Any]:
    """{"decision": "finish"|"replan", "reason", "missing"}; anything unreadable means finish."""
    if not isinstance(value, dict):
        return {"decision": "finish", "reason": "joiner reply unreadable", "missing": []}
    decision = str(value.get("decision") or "finish").strip().lower()
    if decision not in ("finish", "replan"):
        decision = "finish"
    missing = value.get("missing") or []
    if isinstance(missing, str):
        missing = [missing]
    return {
        "decision": decision,
        "reason": str(value.get("reason") or "")[:300],
        "missing": [str(m)[:200] for m in missing if str(m).strip()][:6] if isinstance(missing, list) else [],
    }


__all__ = [
    "JOIN_PHASE",
    "JOIN_SYSTEM",
    "LITERATURE_TOOL",
    "PLAN_PHASE",
    "PLAN_SYSTEM",
    "build_join_prompt",
    "build_plan_prompt",
    "constraint_lines",
    "observations",
    "parse_join",
    "pipeline_summary",
    "select_tools",
    "summarise_result",
]
