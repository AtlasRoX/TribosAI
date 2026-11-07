"""
Plan-and-execute phase (feature 1): after the pipeline's own Stage 1 and 2 results exist, a planner model
writes a DAG of follow-up tool calls, the DAG is validated, optionally approved by the researcher, run in
parallel, and a joiner decides whether to finish or replan.

- LLMCompiler (Kim et al., ICML 2024, arXiv:2312.04511): planner -> task-fetching unit -> executor -> joiner,
  at most budget.max_replans replans (TRIBOS_AGENT_MAX_REPLANS).
- ReWOO (Xu et al. 2023, arXiv:2305.18323): one up-front plan is the default; the joiner is only consulted
  when a replan is allowed.
- Plan-and-Solve (Wang et al., ACL 2023, arXiv:2305.04091): the planner's trigger sentence.
- ReAct (Yao et al., ICLR 2023, arXiv:2210.03629): TRIBOS_AGENT_PLAN_MODE=react plans one node at a time
  and observes each result (at most TRIBOS_AGENT_REACT_STEPS steps, default 4).
- Human in the loop (Magentic-UI action guards, arXiv:2507.22358): on an interactive run, nodes that call
  expensive tools (simulation, scans, calibration, code execution, docking) wait for an approval of kind
  "dag"; the researcher may drop nodes by id.

Settings: TRIBOS_AGENT_PLAN=off|auto|on (off disables the phase), TRIBOS_AGENT_PLAN_MODE=dag|react,
TRIBOS_AGENT_PLAN_CONCURRENCY (executor.py), TRIBOS_AGENT_APPROVAL_TIMEOUT (seconds, default 300).
Writes execution_artifacts["agent_plan"] and steps "agent_plan" and "agent_node_<id>".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ..agents.evidence_need import is_closed_computation, is_self_contained
from .budget import BudgetExhausted
from .config import AGENTIC, DEBATE, DIRECT_ROUTES, MATH_DIRECT_ROUTES, env_flag, env_float, env_int
from .executor import PlanExecutor
from .llm import AgentLLMUnavailable
from .math_agent import math_agent_available
from .plan_graph import (
    PlanGraph,
    PlanNode,
    drop_nodes,
    is_expensive_tool,
    parse_plan,
    validate_plan,
    validated_inputs,
)
from .planner import (
    JOIN_PHASE,
    PLAN_PHASE,
    build_join_prompt,
    build_plan_prompt,
    observations,
    parse_join,
    select_tools,
)
from .runtime import AgentPhase, PhaseOutcome, register_phase

logger = logging.getLogger(__name__)


def plan_mode() -> str:
    mode = (os.getenv("TRIBOS_AGENT_PLAN_MODE", "") or "dag").strip().lower()
    return mode if mode in ("dag", "react") else "dag"


def prior_calls(state: Any, nodes: list[PlanNode] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """(tool, validated inputs) of every call made this turn: the run recorder's log when one is active, plus
    the plan's own executed nodes (so a run without a recorder still never repeats a node)."""
    out: list[tuple[str, dict[str, Any]]] = []
    try:
        from ..provenance.run_manifest import current_recorder

        rec = current_recorder()
        for c in list(getattr(rec, "_calls", None) or []):
            inputs = getattr(c, "inputs", None)
            if inputs:
                out.append((str(c.tool_name), dict(inputs)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Run recorder calls unavailable: %s", exc)
    for n in nodes or []:
        if n.status in ("done", "error"):
            entry = state.registry.get_entry(n.tool) if state.registry is not None else None
            inputs = validated_inputs(entry, n.call_args()) if entry is not None else None
            if inputs is not None:
                out.append((n.tool, inputs))
    return out


def _purpose_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def link_recoveries(nodes: list[PlanNode], tool_results: dict[str, Any]) -> list[dict[str, str]]:
    """Mark each failed node that a later successful node of the same tool and purpose replaced (typically the
    replanned call): `node.recovered_by`, and `metadata["recovered_by"]` on the failed result, so the task status
    reports the failure as recovered history instead of a missing piece of the answer."""
    links: list[dict[str, str]] = []
    for i, node in enumerate(nodes):
        if node.status != "error" or node.recovered_by:
            continue
        words = _purpose_words(node.purpose)
        for later in nodes[i + 1:]:
            if later.status != "done" or later.tool != node.tool:
                continue
            other = _purpose_words(later.purpose)
            same = not words or not other or len(words & other) / min(len(words), len(other)) >= 0.5
            if not same:
                continue
            node.recovered_by = later.id
            res = tool_results.get(node.result_key) if node.result_key else None
            if res is not None:
                try:
                    res.metadata = {**(getattr(res, "metadata", None) or {}), "recovered_by": later.result_key or later.id}
                except Exception:  # noqa: BLE001 - an immutable result keeps its status; the node link remains
                    logger.debug("Could not mark %s as recovered", node.result_key)
            links.append({"step": node.id, "recovered_by": later.id, "tool": node.tool})
            break
    return links


def _dropped_ids(payload: dict[str, Any], graph: PlanGraph) -> set[str]:
    """Node ids an edited approval payload removes: {"drop": [...]}, {"keep": [...]}, or an edited "nodes"
    list (entries with run/approved false or drop true are removed; ids missing from the list are removed)."""
    ids = set(graph.ids())
    drop: set[str] = set()
    for key in ("drop", "dropped", "remove", "drop_nodes"):
        val = payload.get(key)
        if isinstance(val, (list, tuple, set)):
            drop |= {str(v) for v in val}
        elif isinstance(val, str):
            drop.add(val)
    keep = payload.get("keep")
    if isinstance(keep, (list, tuple)):
        drop |= ids - {str(v) for v in keep}
    nodes = payload.get("nodes")
    if isinstance(nodes, list) and nodes:
        listed: set[str] = set()
        for n in nodes:
            if isinstance(n, dict) and n.get("id") is not None:
                nid = str(n["id"])
                listed.add(nid)
                if n.get("run") is False or n.get("approved") is False or n.get("drop") is True:
                    drop.add(nid)
            elif isinstance(n, str):
                listed.add(n)
        drop |= ids - listed
    return drop & ids


async def request_dag_approval(state: Any, graph: PlanGraph, round_no: int) -> dict[str, Any] | None:
    """Ask the researcher to approve the nodes before they run; returns the approval record or None."""
    control = state.control
    registry = getattr(state, "registry", None)
    expensive = [
        n.id for n in graph.nodes
        if is_expensive_tool(n.tool, registry.get_entry(n.tool) if hasattr(registry, "get_entry") else None)
    ]
    # A run a human was attached to still asks (RunControl refuses at once when nobody is watching), so a job whose
    # watcher left never runs expensive nodes unasked (AGT-005).
    needs = getattr(control, "needs_human_decision", None)
    if not graph.nodes or not (bool(needs) if needs is not None else getattr(control, "interactive", False)):
        return None
    if not expensive and not state.options.get("require_plan_approval"):
        return None
    from ..config.settings import get_bool

    if not state.options.get("require_plan_approval") and not get_bool("TRIBOS_APPROVE_EXPENSIVE"):
        # Expensive tool calls ask first only when TRIBOS_APPROVE_EXPENSIVE is on (as the plan approval phase does):
        # the follow-up plan waited 2 minutes for a click before running a few seconds of simulation.
        return None
    payload = {
        "round": round_no,
        "nodes": [{**n.to_artifact(), "run": True, "expensive": n.id in expensive} for n in graph.nodes],
        "expensive": expensive,
        "edit": "set run: false on a node to drop it (its dependents are dropped too), or return {'drop': [node ids]}",
    }
    timeout = env_float("TRIBOS_AGENT_APPROVAL_TIMEOUT", 300.0, 5.0, 3600.0)
    announced: dict[str, Any] = {}

    async def announce(approval_id: str) -> None:
        announced["approval_id"] = approval_id
        await state.send(
            {"type": "approval_request", "run_id": control.run_id, "approval_id": approval_id, "kind": "dag", "payload": payload}
        )
        await state.step(
            "agent_plan_approval",
            "Waiting for your approval of the planned tool calls",
            f"{len(graph.nodes)} planned · {len(expensive)} expensive ({', '.join(expensive)})" if expensive else f"{len(graph.nodes)} planned",
            status="running",
            agent="Planner",
            approval_id=approval_id,
        )

    decision = await control.request_approval("dag", payload, timeout_seconds=timeout, announce=announce)
    approval_id = announced.get("approval_id")
    drop: set[str] = _dropped_ids(decision.payload, graph) if isinstance(decision.payload, dict) else set()
    if not decision.approved:
        drop |= set(expensive) if expensive else set(graph.ids())
        # timeout / unattended / error refuse too (fail closed); the status says which.
        status = decision.source if decision.source in ("timeout", "unattended", "error") else "rejected"
    elif drop:
        status = "edited"
    else:
        status = {"auto": "auto", "timeout": "timeout"}.get(decision.source, "approved")
    reason = (
        "dropped by the researcher" if decision.approved
        else "rejected by the researcher" if status == "rejected"
        else f"not approved ({status}); withheld"
    )
    removed = drop_nodes(graph, drop, reason)
    await state.step(
        "agent_plan_approval",
        f"Plan {status}",
        f"dropped {', '.join(removed)}" if removed else (decision.message or ""),
        status="done",
        agent="Planner",
    )
    return {"approval_id": approval_id, "status": status, "dropped": removed, "message": decision.message[:300]}



# Tools that compute what the mathematics agent cannot: a numerical PDE solve with its mesh study, a cited engineering
# calculation, a propagated uncertainty, an uploaded paper's reproduction. A question that needs one is planned even
# when it parses as a closed computation, or the symbolic answer would stand in for the requested numerical check.
SPECIALISED_TOOLS = frozenset({
    "dynamis_solve_pde", "dynamis_monte_carlo_integrate", "physis_engineering_calc", "physis_propagate_uncertainty", "archivon_read_paper",
    "archivon_reproduce_paper", "physis_fluid_properties", "physis_molecule", "physis_stereo",
})


def _rk4_computed_by_code(query: str) -> bool:
    """An initial-value problem whose RK4 comparison the response layer computes deterministically
    (tribos.writer.facts, before drafting): no planned Dynamis call is needed for it."""
    try:
        from ..writer.facts import parse_ode_problem

        prob = parse_ode_problem(query)
    except Exception:  # noqa: BLE001 - a routing hint only
        return False
    return prob is not None and prob.rk4 and len(prob.ics) == prob.order


def needs_specialised_tool(state: Any) -> bool:
    """Whether tool retrieval ranks one of SPECIALISED_TOOLS among the top three for the question."""
    registry = getattr(state, "registry", None)
    if registry is None:
        return False
    query = state.clean_query or state.query
    from ..agents.query_planner import PYTHON_REQUEST_RE

    if PYTHON_REQUEST_RE.search(query) and registry.get_entry("calcula_run_python") is not None:
        # "Run real Python and report its outputs": only the tool plan writes and runs code, so it is not skipped.
        return True
    # An explicit numerical method takes precedence over a symbolic parser's ability to read a formula.
    if (re.search(r"\bMonte[ -]Carlo\b", query, re.I) and registry.get_entry("dynamis_monte_carlo_integrate") is not None):
        return True
    if (re.search(r"\b(?:FTCS|finite[ -]difference|PDE)\b|heat\s+equation", query, re.I)
            and registry.get_entry("dynamis_solve_pde") is not None):
        return True
    if (re.search(r"\bRK4\b|fourth[ -]order\s+Runge", query, re.I) and registry.get_entry("dynamis_simulate_ode") is not None
            and not _rk4_computed_by_code(query)):
        return True
    if registry.get_entry("physis_stereo") is not None:
        from ..physis.chemistry import is_structure_question
        from .chem_agent import chem_agent_enabled

        # Stereodescriptors, stereoisomer counts and NMR environments are exact given a structure; written by hand,
        # the CIP labels were wrong even when the geometry was right (benchmark failure analysis, items 17-18). The
        # chemistry agent (chem_agent.py) checks its own structures with the same code, so the plan is only needed
        # when it is off.
        if is_structure_question(query) and not chem_agent_enabled():
            return True
    try:
        from .tool_retrieval import retrieve_tools

        top = retrieve_tools(registry, state.clean_query or state.query, k=3)
    except Exception:  # noqa: BLE001 - retrieval is a routing hint; without it the default rules apply
        return False
    hits = [getattr(e, "name", "") for e in top if getattr(e, "name", "") in SPECIALISED_TOOLS and registry.get_entry(e.name) is not None]
    if not re.search(r"\bMonte[ -]Carlo\b|sampling|stochastic", query, re.I):
        hits = [name for name in hits if name != "dynamis_monte_carlo_integrate"]
    if not re.search(r"\b(?:papers?|articles?|preprints?|publications?|arXiv|doi)\b|10\.\d{4,}/", query, re.I):
        # Reading or reproducing a paper needs a paper: "verify ... and has it been proven?" ranks the reproduction
        # tool by its words ("verify", "results") without naming one.
        hits = [name for name in hits if name not in ("archivon_read_paper", "archivon_reproduce_paper")]
    if not hits:
        return False
    if hits == ["physis_engineering_calc"]:
        # "physis_engineering_calc" contains "safety factor utilisation", which lexically matches the bare word "factor"
        # in polynomial factoring problems. Guard against this false positive when there are no engineering terms.
        query_lower = (state.clean_query or state.query or "").lower()
        eng_keywords = (
            "beam", "cantilever", "deflection", "bending", "stress", "buckling", "euler", "johnson",
            "pressure vessel", "hoop stress", "shaft", "torsion", "von mises", "bolt", "preload", "torque",
            "fatigue", "goodman", "pipe", "pressure drop", "colebrook", "heat exchanger", "lmtd", "ntu",
            "conduction", "insulation", "safety factor", "utilisation", "utilization"
        )
        if not any(k in query_lower for k in eng_keywords):
            return False
    if hits == ["physis_fluid_properties"]:
        # Words such as "pressure" or "density" alone do not make a question about a real fluid's equation of state.
        if not _FLUID_QUESTION_RE.search(state.clean_query or state.query or ""):
            return False
    return True


# A question about a real fluid's state: a named fluid or refrigerant with a process or property that needs its EOS.
_FLUID_QUESTION_RE = re.compile(
    r"\b(?:joule[\s-]*thomson|throttl\w*|isenthalp\w*|refrigerant\w*|R-?\d{2,4}[a-z]?\b|steam\b|"
    r"saturat\w+\s+(?:pressure|temperature|vapou?r|liquid)|latent\s+heat|compressibility\s+factor|"
    r"thermophysical|real[\s-]gas|equation\s+of\s+state|coolprop)", re.I)

class PlanExecutePhase(AgentPhase):
    key = "plan_execute"
    stage = "augment"
    order = 10
    frameworks = (AGENTIC, DEBATE)
    needs_llm = True

    def applies(self, state: Any) -> bool:
        if env_flag("TRIBOS_AGENT_PLAN", "auto") == "off":
            return False
        if state.options.get("enable_plan") is False:
            return False
        specialised = needs_specialised_tool(state)
        from ..agents.orchestration.presentation import computations_cover_question

        # Code that covers the question (a solved PDE, an integrated system) also covers a specialised tool request
        # and a request to run Python: the computed results are Python's outputs.
        if computations_cover_question(getattr(state, "tool_results", None) or {}):
            # Code computed and checked every requested value; the evidence stage already searched for the rest.
            state.bag.setdefault("not_needed_phases", {})[self.key] = (
                "the requested computations were run and checked by code; no tool plan needed")
            return False
        if (
            (is_closed_computation(state.ctx) or (is_self_contained(state.ctx) and getattr(getattr(state.ctx, "evidence_need", None), "level", "") == "none"))
            and math_agent_available(state)
            and not specialised
        ):
            # The verified mathematics agent (or the code-computed results) solves and checks it; a tool plan would
            # only repeat that. Recorded so the run is not reported as a fallback.
            state.bag.setdefault("not_needed_phases", {})[self.key] = (
                "a self-contained computation, solved and checked without a tool plan")
            return False
        rule = (state.bag.get("routing") or {}).get("rule")
        if rule in DIRECT_ROUTES and (rule not in MATH_DIRECT_ROUTES or math_agent_available(state)) and not specialised:
            # Auto chose the direct workflow (config.DIRECT_ROUTES); the two math-problem routes rely on the
            # mathematics agent, so without it the planner still runs.
            return False
        return getattr(state.ctx, "scope", "research") == "research"

    async def run(self, state: Any) -> PhaseOutcome | None:
        mode = plan_mode()
        budget = state.budget
        artifact: dict[str, Any] = {"planner": "llm", "mode": mode, "rationale": "", "replans": 0, "nodes": [], "rejected": []}
        all_nodes: list[PlanNode] = []
        results: dict[str, Any] = {}
        failed: set[str] = set()
        joins: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        await state.step("agent_plan", "Planning follow-up tool calls", "", status="running", agent="Planner")
        try:
            tools = select_tools(state, state.sub_questions)
            artifact["tools_offered"] = [e.name for e in tools]
            react_steps = env_int("TRIBOS_AGENT_REACT_STEPS", 4, 1, 12)
            round_no = 0
            missing: list[str] | None = None
            while True:
                state.control.checkpoint()
                room = budget.max_plan_nodes - len(all_nodes)
                if room <= 0 or budget.exhausted():
                    break
                cap = 1 if mode == "react" else room
                system, user = build_plan_prompt(
                    state,
                    tools=tools,
                    max_nodes=cap,
                    mode=mode,
                    previous=observations(all_nodes, results) if all_nodes else None,
                    missing=missing,
                )
                try:
                    reply = await state.llm.json(system, user, phase=PLAN_PHASE)
                except ValueError as exc:
                    if round_no == 0:
                        artifact["planner"] = "none"
                        artifact["status"] = "planner_unusable"
                    artifact["error"] = f"planner reply unusable: {str(exc)[:200]}"
                    break
                except BudgetExhausted as exc:
                    if round_no == 0:
                        artifact["planner"] = "none"
                        artifact["status"] = "budget"
                    artifact["error"] = str(exc)[:200]
                    break
                except AgentLLMUnavailable as exc:
                    if round_no == 0:
                        artifact["planner"] = "none"
                        artifact["status"] = "planner_failed"
                    artifact["error"] = f"model call failed: {str(exc)[:180]}"
                    break
                graph = parse_plan(reply, round_no=round_no, taken_ids={n.id for n in all_nodes})
                if round_no == 0 or (graph.rationale and not artifact["rationale"]):
                    artifact["rationale"] = graph.rationale
                validate_plan(
                    graph,
                    state.registry,
                    state.ctx,
                    max_nodes=cap,
                    prior_calls=prior_calls(state, all_nodes),
                    external_ids=set(results),
                )
                artifact["rejected"].extend(graph.rejected)
                graph.rejected = []
                if graph.nodes:
                    approval = await request_dag_approval(state, graph, round_no)
                    if approval is not None:
                        approvals.append(approval)
                        artifact["rejected"].extend(graph.rejected)
                        graph.rejected = []
                if not graph.nodes:
                    break
                all_nodes.extend(graph.nodes)
                await state.step(
                    "agent_plan",
                    "Running planned tool calls",
                    f"{len(all_nodes)} node(s) · {len(artifact['rejected'])} rejected",
                    status="running",
                    agent="Planner",
                    nodes=[n.to_artifact() for n in all_nodes][:50],
                )
                executor = PlanExecutor(state, results=results, failed=failed, prior_calls=prior_calls(state, all_nodes))
                await executor.run(graph)

                if mode == "react":
                    round_no += 1
                    if round_no >= react_steps:
                        break
                    continue
                if artifact["replans"] >= budget.max_replans or budget.exhausted():
                    break
                try:
                    jsys, juser = build_join_prompt(state, graph, results, all_nodes)
                    join = parse_join(await state.llm.json(jsys, juser, phase=JOIN_PHASE))
                except (ValueError, BudgetExhausted, AgentLLMUnavailable) as exc:
                    join = {"decision": "finish", "reason": f"joiner unavailable: {str(exc)[:160]}", "missing": []}
                joins.append(join)
                if join["decision"] != "replan":
                    break
                missing = join["missing"] or [join["reason"]]
                artifact["replans"] += 1
                round_no += 1
        except BaseException as exc:
            # Anything that escapes (cancellation, a time-budget stop, an unexpected error) is still recorded, so the
            # plan card never shows an empty plan without saying why.
            artifact.setdefault("error", f"{type(exc).__name__}: {str(exc)[:180]}" if str(exc) else type(exc).__name__)
            artifact.setdefault("status", "planner_failed" if not all_nodes else "interrupted")
            raise
        finally:
            artifact.setdefault("status", "ok")
            recovered = link_recoveries(all_nodes, state.tool_results)
            if recovered:
                artifact["recovered"] = recovered
            artifact["nodes"] = [n.to_artifact() for n in all_nodes][:50]
            artifact["rejected"] = artifact["rejected"][:50]
            if joins:
                artifact["joins"] = joins
            if approvals:
                artifact["approval"] = approvals[-1] if len(approvals) == 1 else approvals
            state.artifacts["agent_plan"] = artifact
            state.bag["agent_plan_results"] = {n.id: n.result_key for n in all_nodes if n.result_key}
        done = sum(1 for n in all_nodes if n.status == "done")
        failed_n = sum(1 for n in all_nodes if n.status == "error" and not n.recovered_by)
        recovered_n = sum(1 for n in all_nodes if n.status == "error" and n.recovered_by)
        skipped = sum(1 for n in all_nodes if n.status == "skipped")
        text = f"{done} done · {failed_n} failed · {skipped} skipped · {len(artifact['rejected'])} rejected"
        if recovered_n:
            text += f" · {recovered_n} failed attempt(s) recovered by a retry"
        if artifact["replans"]:
            text += f" · {artifact['replans']} replan(s)"
        planner_failed = artifact.get("status") in ("planner_failed", "planner_unusable", "budget")
        if not all_nodes:
            rejected = artifact.get("rejected") or []
            if rejected and not artifact.get("error"):
                # Audit I34: a plan whose calls were all rejected is not a plan that needed none.
                reasons = list(dict.fromkeys(str(r.get("reason") or "") for r in rejected if isinstance(r, dict)))
                text = f"No planned call ran: {len(rejected)} rejected ({'; '.join(reasons[:3])[:400]})"
            else:
                text = artifact.get("error") or ("no follow-up calls needed" if artifact["planner"] == "llm" else "no plan")
        if planner_failed:
            reason = {"planner_failed": "model call failed", "planner_unusable": "the planner reply was unusable",
                      "budget": "the agent budget ran out"}[artifact["status"]]
            state.mark_phase(self.key, "budget" if artifact["status"] == "budget" else
                             ("llm_unavailable" if artifact["status"] == "planner_failed" else "error"), reason)
            await state.step("agent_plan", "The planner did not run",
                             f"{reason[:1].upper()}{reason[1:]}; the pipeline's own evidence was used.",
                             status="error", agent="Planner")
            return None
        await state.step("agent_plan", "Planned follow-up tool calls", text, status="done", agent="Planner")
        return None


register_phase(PlanExecutePhase())

__all__ = ["PlanExecutePhase", "plan_mode", "prior_calls", "request_dag_approval"]
