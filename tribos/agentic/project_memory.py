"""
Project memory phases (feature 16): recall before the evidence search, consolidation after verification.

A research project spans many threads. Its memory is a bi-temporal fact graph (tribos/utils/memory/
project_store.py) built from verified tool results, following:
- Zep / Graphiti (arXiv:2501.13956): bi-temporal facts; contradictions invalidate, never delete.
- Mem0 (arXiv:2504.19413): extract, then ADD / UPDATE / INVALIDATE / NOOP (deterministic here).
- HippoRAG (NeurIPS 2024, arXiv:2405.14831): Personalized PageRank from the question's entities for recall.
- Generative Agents (UIST 2023, arXiv:2304.03442): recency x importance x relevance ranking.
- MemGPT (arXiv:2310.08560): the 12 recalled facts are the working memory paged into the prompt; the archive
  stays in the store and the projects API.
- A-MEM (NeurIPS 2025, arXiv:2502.12110): facts sharing an entity are linked notes in the graph.

Phases:
- `project_memory` (before_evidence, order 20): only when `state.project_id` is set and owned by the user.
  Writes `state.project_memory` (a text block the orchestrator appends to the memory summary) and the
  artifact `project_memory.recalled`.
- `project_memory_consolidate` (finalize, order 50): extracts facts deterministically from `state.tool_results`
  (symbolic results, equilibria and simulated end states of a named system, CODATA constants, unit
  conversions, material properties, literature findings), the `hypotheses` artifact and the researcher's lasting instructions
  (`classify_instructions`, investigation or profile scope). Facts are `verified` only when the turn's
  verification passed; otherwise they are tagged `unverified`. Artifact `project_memory.written/invalidated`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..utils.memory.project_store import FactInput, ProjectStore, get_project_store
from ..utils.memory.research_memory import classify_instructions, turn_fully_verified
from .guardrails import neutralise
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

RECALL_K = 12
MAX_FACTS_PER_TURN = 60


def _store() -> ProjectStore:
    return get_project_store()


def query_entities(state: AgentState) -> list[str]:
    """Entity strings for the PPR seeds: the resolved concepts, equations, systems, constants and materials and the
    question's subject."""
    ctx = state.ctx
    out: list[str] = []
    for e in list(getattr(ctx, "entities", None) or []):
        for value in (getattr(e, "label", None), getattr(e, "mention", None)):
            if value:
                out.append(str(value))
    for value in (_topic(ctx), getattr(ctx, "system_name", None)):
        if value:
            out.append(str(value))
    return list(dict.fromkeys(out))


def _fmt_fact(f: dict[str, Any]) -> str:
    rel = str(f["relation"]).replace("_", " ")
    value = f" ({f['value']})" if f.get("value") else ""
    flags = "verified" if f.get("verified") else "unverified"
    when = (f.get("recorded_at") or "")[:10]
    src = f.get("source") or {}
    origin = src.get("tool") or src.get("origin") or ""
    return neutralise(f"- {f['subject']} {rel} {f['object']}{value} [{flags}, {when}{', ' + str(origin) if origin else ''}]")


def format_memory_block(project: dict[str, Any], facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""
    name = neutralise(str(project.get("name", "")))[:120]
    lines = [
        f'<project_memory project="{name}">',
        "Facts recorded in earlier turns of this research project (background only: cite the current evidence, "
        "and say so when it disagrees with a recorded fact). Each line says whether its turn was verified; an "
        "unverified fact is a lead to check, never evidence:",
        *(_fmt_fact(f) for f in facts),
        "</project_memory>",
    ]
    return "\n".join(lines)


def _public(f: dict[str, Any]) -> dict[str, Any]:
    return {k: f.get(k) for k in ("id", "subject", "relation", "object", "value", "valid_from", "source", "confidence", "verified")}


# ---------------------------------------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------------------------------------

def _data(result: Any) -> tuple[bool, Any, str]:
    if result is None:
        return False, None, ""
    if isinstance(result, dict) and "success" not in result:
        return True, result, ""
    success = bool(getattr(result, "success", result.get("success") if isinstance(result, dict) else False))
    data = getattr(result, "data", result.get("data") if isinstance(result, dict) else None)
    tool = str(getattr(result, "tool_name", result.get("tool_name", "") if isinstance(result, dict) else "") or "")
    return success, data, tool


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _topic(ctx: Any) -> str | None:
    """The question's subject (a named system, equation, concept or material), for facts that need one."""
    for name in ("primary_display", "primary_target", "system_name", "primary_symbol"):
        value = getattr(ctx, name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _fmt_value(value: Any, unit: Any = None) -> str:
    num = _num(value)
    text = f"{num:.6g}" if num is not None else str(value)
    return f"{text} {unit}".strip() if unit else text


def _symbolic(data: dict[str, Any], topic: str | None) -> list[FactInput]:
    """An Axiom answer (axiom_solve_problem's answer text, or another tool's result), with its verification status."""
    answer = data.get("answer") if isinstance(data.get("answer"), dict) else {}
    text = answer.get("text") or data.get("result") or data.get("latex")
    if not text:
        return []
    status = str(data.get("status") or (data.get("verification") or {}).get("status") or "") or None
    subject = topic or str(data.get("problem") or data.get("expression") or data.get("equation") or "symbolic computation")
    return [FactInput(subject=subject[:200], relation="symbolic_result", object=str(text)[:300], value=status,
                      confidence=0.95 if status == "verified" else 0.75, tags=["symbolic"])]


def _dynamics(data: dict[str, Any], topic: str | None) -> list[FactInput]:
    """An equilibrium with its stability, or a simulated end state over the integration interval."""
    subject = topic or str(data.get("model_name") or "dynamical system")
    point = data.get("fixed_point")
    if isinstance(point, dict) and point:
        obj = ", ".join(f"{k}={_fmt_value(v)}" for k, v in list(point.items())[:8])
        return [FactInput(subject=subject, relation="equilibrium", object=obj, value=str(data.get("stability") or "") or None,
                          confidence=0.9 if data.get("converged", True) else 0.6, tags=["numerical"])]
    summary = data.get("summary")
    if isinstance(summary, dict) and summary:
        finals = {k: v.get("final") for k, v in summary.items() if isinstance(v, dict) and v.get("final") is not None}
        if finals:
            span = data.get("t_span") or []
            when = f"t = {_fmt_value(span[-1])}" if span else None
            obj = ", ".join(f"{k}={_fmt_value(v)}" for k, v in list(finals.items())[:8])
            return [FactInput(subject=subject, relation="simulated_final_state", object=obj, value=when,
                              confidence=0.9 if data.get("verified", True) else 0.6, tags=["numerical"])]
    return []


def _constants(data: dict[str, Any]) -> list[FactInput]:
    out: list[FactInput] = []
    for c in (data.get("constants") or [])[:5]:
        if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
            out.append(FactInput(subject=str(c["name"]), relation="physical_constant",
                                 object=str(c.get("symbol") or c["name"]), value=_fmt_value(c["value"], c.get("unit")),
                                 confidence=1.0, tags=["constant"]))
    return out


def _conversion(data: dict[str, Any]) -> list[FactInput]:
    if data.get("converted_value") is None or not data.get("input_unit"):
        return []
    return [FactInput(subject=_fmt_value(data.get("input_value"), data["input_unit"]), relation="converts_to",
                      object=_fmt_value(data["converted_value"], data.get("converted_unit")), confidence=0.95,
                      tags=["units"])]


_MATERIAL_PROPERTIES = (("band_gap", "band gap", "eV"), ("density", "density", "g/cm^3"),
                        ("youngs_modulus_gpa", "Young's modulus", "GPa"), ("yield_strength_mpa", "yield strength", "MPa"),
                        ("thermal_conductivity_w_mk", "thermal conductivity", "W/(m K)"))


def _materials(data: dict[str, Any]) -> list[FactInput]:
    out: list[FactInput] = []
    for m in (data.get("materials") or [])[:3]:
        if not isinstance(m, dict) or not (m.get("formula_pretty") or m.get("name")):
            continue
        subject = str(m.get("formula_pretty") or m.get("name"))
        for field, label, unit in _MATERIAL_PROPERTIES:
            if _num(m.get(field)) is not None:
                out.append(FactInput(subject=subject, relation="property", object=label, value=_fmt_value(m[field], unit),
                                     confidence=0.85, tags=["material", str(m.get("source") or "")]))
    return out


def _hypotheses(artifact: Any) -> list[FactInput]:
    if not isinstance(artifact, dict):
        return []
    subject = str(artifact.get("target") or artifact.get("model_id") or "").strip()
    out: list[FactInput] = []
    for h in (artifact.get("hypotheses") or [])[:5]:
        if not isinstance(h, dict) or not h.get("statement"):
            continue
        supports = (h.get("result") or {}).get("supports") if isinstance(h.get("result"), dict) else None
        relation = "hypothesis_supported" if supports is True else "hypothesis_not_supported" if supports is False else "hypothesis_untested"
        value = None
        result = h.get("result") if isinstance(h.get("result"), dict) else {}
        rel, lfc = _num(result.get("relative_change")), _num(result.get("log2_fold_change"))
        if rel is not None:
            value = f"relative change {rel:+.3f}"
        elif lfc is not None:
            value = f"log2FC {lfc:.2f}"
        out.append(
            FactInput(subject=subject or "hypothesis", relation=relation, object=str(h["statement"]), value=value, confidence=0.6, tags=["hypothesis"])
        )
    return out


def extract_facts(state: AgentState) -> list[FactInput]:
    """Facts from this turn's tool results, artifacts and lasting instructions (deterministic)."""
    topic = _topic(state.ctx)
    facts: list[FactInput] = []
    seen: set[int] = set()  # the pipeline stores some results under two keys ("dynamis" and its "vivarix" alias)
    for key, result in list(state.tool_results.items()):
        ok, data, tool = _data(result)
        if not ok or not isinstance(data, dict) or id(result) in seen:
            continue
        seen.add(id(result))
        name = f"{key} {tool}".lower()
        src = {"tool": key}
        found: list[FactInput] = []
        if "physis_constants" in name or data.get("constants"):
            found = _constants(data)
        elif "physis_units" in name or "converted_value" in data:
            found = _conversion(data)
        elif "physis_materials" in name or isinstance(data.get("materials"), list):
            found = _materials(data)
        elif "axiom" in name or "symbolic" in name:
            found = _symbolic(data, topic)
        elif "dynamis" in name or "vivarix" in name:
            found = _dynamics(data, topic)
        elif ("lithoscribe" in name or "archivon" in name or "literature" in name) and data.get("ranked_passages"):
            for p in (data.get("ranked_passages") or [])[:5]:
                text = p.get("passage_text") or p.get("text") or "" if isinstance(p, dict) else ""
                if text:
                    found.append(FactInput(
                        subject=topic or "literature",
                        relation="literature_finding",
                        object=text[:120],
                        confidence=0.75,
                        tags=["literature"],
                    ))
        for f in found:
            f.source = {**src, **(f.source or {})}
        facts.extend(found)
    for f in _hypotheses(state.artifacts.get("hypotheses")):
        f.source = {"tool": "hypotheses"}
        facts.append(f)
    for text, scope in classify_instructions(state.query or ""):
        if scope in ("investigation", "profile"):
            facts.append(FactInput(subject="researcher", relation="instructs", object=neutralise(text), confidence=1.0, source={"origin": "user_instruction", "scope": scope}, tags=["instruction"]))
    return facts[:MAX_FACTS_PER_TURN]


def _verified(state: AgentState) -> bool:
    """A turn's facts are verified only when its answer passed with no unsupported, contradicted or unchecked claim:
    "passed" alone tolerates unsupported claims, which must not turn into verified project facts."""
    v = state.verification
    if v is None:
        return False
    report = v if isinstance(v, dict) else (v.model_dump() if hasattr(v, "model_dump") else {
        k: getattr(v, k, None) for k in ("passed", "fully_verified", "unsupported_claims", "contradicted_claims", "unchecked_claims")
    })
    return turn_fully_verified(bool(report.get("passed")), {k: val for k, val in report.items() if val is not None})


# ---------------------------------------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------------------------------------

class ProjectRecallPhase(AgentPhase):
    key = "project_memory"
    stage = "before_evidence"
    order = 20

    def applies(self, state: AgentState) -> bool:
        return bool(state.project_id)

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        store = _store()
        project = await asyncio.to_thread(store.get_project, state.project_id or "", state.user_id)
        if project is None:
            state.scope_notes.append("The selected research project was not found; project memory was not used.")
            state.bag["project_owned"] = False
            return None
        state.bag["project_owned"] = True
        facts = await asyncio.to_thread(store.recall, project["id"], state.user_id, state.clean_query, query_entities(state), RECALL_K)
        state.project_memory = format_memory_block(project, facts)
        artifact = {"project_id": project["id"], "project_name": project["name"], "recalled": [_public(f) for f in facts], "written": 0, "invalidated": 0}
        state.artifacts["project_memory"] = {**(state.artifacts.get("project_memory") or {}), **artifact}
        await state.step(
            "agent_project_memory",
            f"Recalled {len(facts)} fact(s) from project {project['name'][:60]}" if facts else f"No recorded facts yet in project {project['name'][:60]}",
            "; ".join(f"{f['subject']} {f['relation'].replace('_', ' ')} {f['object']}"[:120] for f in facts[:3]),
            agent="Project memory",
        )
        return None


class ProjectConsolidatePhase(AgentPhase):
    key = "project_memory_consolidate"
    stage = "finalize"
    order = 50

    def applies(self, state: AgentState) -> bool:
        return bool(state.project_id) and state.bag.get("project_owned") is not False

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        store = _store()
        if not await asyncio.to_thread(store.owns, state.project_id, state.user_id):
            return None
        verified = _verified(state)
        facts = extract_facts(state)
        base_source = {"thread_id": state.thread_id, "run_id": state.control.run_id}
        for f in facts:
            f.source = {**base_source, **(f.source or {})}
            f.verified = verified
        result = await asyncio.to_thread(store.upsert_facts, state.project_id or "", state.user_id, facts) if facts else {"written": 0, "invalidated": 0, "ops": []}
        art = dict(state.artifacts.get("project_memory") or {"project_id": state.project_id, "recalled": []})
        art.update({"project_id": state.project_id, "written": result["written"], "invalidated": result["invalidated"], "verified": verified})
        art["operations"] = {op: sum(1 for o in result["ops"] if o["op"] == op) for op in ("ADD", "UPDATE", "INVALIDATE", "NOOP")}
        state.artifacts["project_memory"] = art
        if facts:
            await state.step(
                "agent_project_memory_write",
                f"Saved {result['written']} fact(s) to the project" + (f", {result['invalidated']} superseded" if result["invalidated"] else ""),
                "verified turn" if verified else "unverified turn: facts tagged unverified",
                agent="Project memory",
            )
        return None


register_phase(ProjectRecallPhase())
register_phase(ProjectConsolidatePhase())

__all__ = ["ProjectConsolidatePhase", "ProjectRecallPhase", "extract_facts", "format_memory_block", "query_entities"]
