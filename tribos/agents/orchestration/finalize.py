"""Stage 6: persistent memory consolidation, the task status and the assembled result."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ...export.report_model import strip_verification_banner
from .. import query_planner
from ..query_context import TaskOutcome
from ..result_keys import distinct_results
from .context import RunContext, logger, orchestrator_module


def turn_fully_supported(report: Any) -> bool:
    """Whether a turn's evidence may be stored as verified: the check passed AND no claim was left unsupported or
    contradicted. "passed" alone tolerates unsupported claims (score >= 0.8), which must not make the turn's tool
    evidence VERIFIED_EMPIRICAL in later answers."""
    if report is None or not getattr(report, "passed", False):
        return False
    coverage = getattr(report, "coverage", None)
    if isinstance(coverage, dict) and coverage and not coverage.get("evaluated"):
        return False  # nothing was checked: nothing may be stored as verified
    bad = {"unsupported", "contradicted"}
    for c in getattr(report, "claims", None) or []:
        status = c.get("status") if isinstance(c, dict) else getattr(c, "status", "")
        if str(status or "") in bad:
            return False
    for attr in ("unsupported_claims", "contradicted_claims"):
        value = getattr(report, attr, 0)
        n = len(value) if isinstance(value, (list, tuple, set)) else value
        if isinstance(n, (int, float)) and n > 0:
            return False
    return True


def _verification_counts(report: Any) -> dict[str, Any]:
    """The report fields session memory needs to decide what may be stored as verified."""
    out: dict[str, Any] = {"passed": bool(getattr(report, "passed", False))}
    for attr in ("fully_verified", "unsupported_claims", "contradicted_claims", "unchecked_claims", "coverage", "status"):
        value = getattr(report, attr, None)
        if value is not None:
            out[attr] = value
    # Statements the checks contradicted, with what was found: stored as refuted, never as reusable facts.
    audit = getattr(report, "math_audit", None) or {}
    out["contradicted_statements"] = [
        {"text": str(c.get("text") or "")[:300], "context": str(c.get("context") or "")[:120],
         "detail": str(c.get("detail") or "")[:300]}
        for c in (audit.get("claims") or []) if c.get("status") == "failed"
    ][:20]
    return out


async def enforce_output_contract(run: RunContext) -> None:
    """After the last revision: apply the content-preserving repairs of the user's requested form (LF newlines, an
    unwrapped JSON fence, the exact literal) and record what still violates it. The record reaches the task status, so
    a broken format is reported, never hidden."""
    contract = getattr(run, "output_contract", None)
    if contract is None or not contract.active or not run.candidate_response:
        return
    from ...utils import output_contract

    fixed = output_contract.conform(run.candidate_response, contract)
    if fixed != run.candidate_response:
        run.candidate_response = fixed
        await run.send({"type": "content_reset", "reason": "output_contract"})
        await run.send({"type": "content_delta", "delta": fixed})
    run.execution_artifacts["output_contract"] = {**contract.to_dict(),
                                                 "violations": output_contract.validate(fixed, contract)}


async def consolidate_memory(run: RunContext) -> None:
    """Write the turn's findings and its active subject to session memory (unless the run is not persisted)."""
    orch = run.orch
    persist_memory, ctx, user_id, thread_id, query = run.persist_memory, run.ctx, run.user_id, run.thread_id, run.query
    candidate_response, tool_results, verification_report = run.candidate_response, run.tool_results, run.verification_report
    emit = run.emit

    # -------------------------------------------------------------
    # STAGE 6: PERSISTENT MEMORY CONSOLIDATION (Mem0)
    # -------------------------------------------------------------
    if persist_memory:
        try:
            # The turn's subject under its own kind (system, equation, concept, material, quantity, constant): a
            # "gene" only when the question resolved a real gene entity, so a follow-up never turns "Lorenz" into one.
            active_subj = query_planner.active_subject(ctx)
            gene = getattr(ctx, "primary_gene", None)
            if gene is not None and getattr(gene, "type", None) == "gene" and ctx.primary_target:
                active_subj["gene"] = ctx.primary_target  # with its variant ("KRAS G12C"), as earlier turns stored it
            if active_subj:
                orch.memory.record_active_subject(user_id, thread_id, active_subj)
            consolidation = await orch.memory.consolidate_turn(
                thread_id=thread_id,
                query=query,
                # The stored excerpt is the answer itself: the verification banner is report metadata (kept in
                # `verification` and `is_turn_verified`), not a finding to recall as content.
                response=strip_verification_banner(candidate_response),
                tool_results={k: v.data for k, v in distinct_results(tool_results).items() if v.success},
                failure_lesson=verification_report.failure_lesson,
                is_turn_verified=turn_fully_supported(verification_report),
                verification=_verification_counts(verification_report),
                user_id=user_id,
                active_subject=active_subj if active_subj else None,
            )
            await emit(
                "memory",
                title="Saved findings to session memory",
                text=f"{consolidation['nodes_created']} memory node(s) written",
                extra={"thread_id": thread_id, "entities_updated": consolidation["entities_updated"]},
            )
        except Exception as mem_err:
            logger.warning("Memory consolidation error: %s", mem_err)


async def _record_routing_outcome(run: RunContext, task_status: dict[str, Any]) -> None:
    """Feed the router's outcome history (tribos/agentic/router_store.py) from every agentic research run."""
    agent_state = run.agent_state
    if agent_state is None or run.ctx is None or run.ctx.scope != "research":
        return
    try:
        from ...agentic import router

        core = agent_state.core_phase_status() or {}
        claims = (run.execution_artifacts or {}).get("claim_confidence") or {}
        await asyncio.to_thread(
            router.record_outcome,
            query=run.resolved_query or run.query,
            ctx=run.ctx,
            framework=agent_state.framework,
            routing=run.routing,
            verification_score=getattr(run.verification_report, "verification_score", None),
            answer_confidence=claims.get("answer_confidence") if isinstance(claims, dict) else None,
            task_status=str(task_status.get("task_status") or ""),
            core_status=str(core.get("status") or "ok"),
            llm_calls=agent_state.budget.llm_calls,
            llm_limit=agent_state.budget.max_llm_calls,
        )
    except Exception as exc:  # noqa: BLE001 - learning must never break a turn
        logger.info("Routing outcome not recorded: %s", exc)


def apply_incomplete_status(task_status: dict[str, Any], agent_state: Any) -> dict[str, Any]:
    """Add `incomplete_reasons` and `unresolved` (lists, always present) to the task status, and make a run that
    stopped early or left sub-questions unanswered "partial" even when its computation (a time course) completed:
    the request is the whole brief, not its simulation step."""
    status: dict[str, Any] = dict(task_status)
    reasons: list[str] = []
    unresolved: list[str] = []
    if agent_state is not None:
        try:
            info = agent_state.incomplete_status()
            reasons, unresolved = list(info.get("incomplete_reasons") or []), list(info.get("unresolved") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Incomplete-status check failed: %s", exc)
    status["incomplete_reasons"] = reasons
    status["unresolved"] = unresolved
    if (reasons or unresolved) and status.get("task_status") in ("completed", "partial"):
        status["task_status"] = "partial"
        parts = list(reasons)
        if unresolved:
            parts.append(f"{len(unresolved)} sub-question(s) not fully answered.")
        lead = " ".join(parts)
        reason = str(status.get("reason") or "")
        status["reason"] = lead if reason in ("", "Evidence gathered and synthesized.") or lead in reason else f"{lead} {reason}"
    return status


def _sync_sub_questions(agent_state: Any, items: list[dict[str, Any]], tool_results: dict[str, Any] | None = None) -> None:
    """Synchronize agent_state.sub_questions with assessed deliverables and tool results so items are not left open."""
    if agent_state is None:
        return
    subs = getattr(agent_state, "sub_questions", None)
    if not subs and len(items) > 1:
        from ...agentic.state import SubQuestion

        new_subs: list[SubQuestion] = []
        for it in items:
            sq = SubQuestion(
                id=it.get("id") or f"q{len(new_subs)+1}",
                text=it.get("item", ""),
                status="answered" if it.get("status") in ("verified", "addressed") else it.get("status", "open"),
                answer_state=it.get("answer_state", "answered" if it.get("status") != "missing" else "missing"),
                check_state=it.get("check_state", "unverified"),
            )
            for ev in it.get("evidence") or []:
                sq.add_evidence(ev, ev.replace("_", " ").title())
            new_subs.append(sq)
        agent_state.sub_questions = new_subs
        return

    if not subs:
        return

    for idx, sq in enumerate(subs):
        match = None
        sq_text = str(sq.text or "").lower()
        for it in items:
            it_text = str(it.get("item") or "").lower()
            if it_text in sq_text or sq_text in it_text:
                match = it
                break
        if match is None and idx < len(items):
            match = items[idx]

        if match is not None:
            it_status = match.get("status", "addressed")
            sq.answer_state = match.get("answer_state", "answered" if it_status != "missing" else "missing")
            sq.check_state = match.get("check_state", "unverified")
            if it_status in ("verified", "addressed"):
                sq.status = "answered"
            elif it_status == "failed_check":
                sq.status = "partial"
                sq.note = "contradicted by claim check"
            elif it_status == "missing":
                sq.status = "missing"
                sq.note = "not addressed in answer"

            for ev in match.get("evidence") or []:
                sq.add_evidence(ev, ev.replace("_", " ").title())


def apply_deliverables(task_status: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Completeness from the requested deliverables: a requested quantity the answer leaves out, or states with a
    value the checks contradict, makes the answer partial with that reason; requests for prose are listed only."""
    status = dict(task_status)
    status["deliverables"] = items
    missing = [i["item"] for i in items if i.get("status") == "missing" and i.get("quantity")]
    failed = [i["item"] for i in items if i.get("status") == "failed_check"]
    reasons = list(status.get("incomplete_reasons") or [])
    if missing:
        reasons.append(f"Not addressed: {', '.join(missing[:6])}.")
    if failed:
        reasons.append(f"Stated with values the checks contradict: {', '.join(failed[:6])}.")
    status["incomplete_reasons"] = reasons
    if (missing or failed) and status.get("task_status") == "completed":
        status["task_status"] = "partial"
        lead = " ".join(reasons)
        reason = str(status.get("reason") or "")
        status["reason"] = lead if reason in ("", "Evidence gathered and synthesized.") else f"{lead} {reason}"
    return status


# Wall time per kind of work, from the pipeline stages and agent phases (phase key -> kind). Planned tool calls
# (plan_execute) include the planner's own model calls; they are counted as execution.
_STAGE_KIND = {
    "route": "planning", "decompose": "planning", "clarify": "planning", "router": "planning",
    "evidence": "retrieval", "gaps": "retrieval", "counter_evidence": "retrieval",
    "computations": "execution", "plan_execute": "execution", "math_agent": "execution",
    "ode_verification": "execution", "specialists": "execution", "analyst": "execution",
    "first_draft": "drafting", "verification": "verification", "nli": "verification", "critique": "verification",
    "confidence": "verification", "memory": "memory",
}


def stage_seconds(phases: list[dict[str, Any]]) -> dict[str, float]:
    """Seconds spent planning, retrieving, executing tools, drafting (first draft and rewrites) and verifying.

    Only non-overlapping parts are summed: the pipeline stages, plus the agent phases that run between them (augment,
    after_draft, finalize). Before-evidence phases run inside the "route" stage and are not added again."""
    out: dict[str, float] = {}
    for p in phases:
        if p.get("stage") not in ("pipeline", "augment", "after_draft", "finalize"):
            continue
        name = str(p.get("phase") or "")
        kind = "drafting" if name.startswith("rewrite_") else _STAGE_KIND.get(name, "other")
        try:
            out[kind] = round(out.get(kind, 0.0) + float(p.get("seconds") or 0.0), 2)
        except (TypeError, ValueError):
            continue
    return out


def merge_pipeline_phases(run: RunContext) -> None:
    """Put the pipeline stages' wall times next to the agent phases in the agent_run artifact (run order), and
    refresh its budget snapshot so it includes the verifier revision and the finalize phases."""
    art = (run.execution_artifacts or {}).get("agent_run")
    if not isinstance(art, dict) or run.agent_state is None:
        return
    try:
        phases = [p for p in art.get("phases") or [] if isinstance(p, dict) and p.get("stage") != "pipeline"]
        merged = phases + [dict(p) for p in run.pipeline_phases]
        if all("at" in p for p in merged):
            merged.sort(key=lambda p: float(p.get("at") or 0.0))
        art["phases"] = merged
        art["stage_seconds"] = stage_seconds(merged)
        art["budget"] = run.agent_state.budget.to_dict()
        art["sub_questions"] = [q.to_dict() for q in run.agent_state.sub_questions]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pipeline phase timing merge failed: %s", exc)


async def assemble_result(run: RunContext) -> Any:
    """Close the open steps and build the AuthoritativeOrchestrationResult."""
    ao = orchestrator_module()
    orch = run.orch
    ctx, agent_state, requested_plan, tool_results = run.ctx, run.agent_state, run.requested_plan, run.tool_results
    verification_report, llm_ok, candidate_response = run.verification_report, run.llm_ok, run.candidate_response
    thread_id, model_name, framework, start_time = run.thread_id, run.model_name, run.framework, run.start_time
    thoughts, reasoning_parts, show_reasoning, steps = run.thoughts, run.reasoning_parts, run.show_reasoning, run.steps
    selected_agents, execution_artifacts, citation_map = run.selected_agents, run.execution_artifacts, run.citation_map
    record, close_open_steps, finalize_manifest = run.record, run.close_open_steps, run.finalize_manifest

    total_duration = round(time.perf_counter() - start_time, 2)
    try:
        query_context_artifact = ctx.to_artifact()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query context summary failed: %s", exc)
        query_context_artifact = None
    try:
        core_note = agent_state.core_phase_note() if agent_state is not None else ""
        outcome = orch._task_outcome(ctx, requested_plan, tool_results, verification_report, llm_ok, core_note)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Task outcome failed: %s", exc)
        outcome = TaskOutcome(task_status="partial", reason=f"Task status unavailable ({type(exc).__name__}).")
    task_status = apply_incomplete_status(outcome.model_dump(), agent_state)
    # The typed record of what the run computed, stamped with the answer text and the record revision the final
    # verification checked; cards, exports and the stored run read this one record.
    try:
        from ...verify.result_record import build_result_record

        record_obj = build_result_record(run.resolved_query or run.query, tool_results)
        checked = getattr(verification_report, "record_revision", "") or ""
        record_obj.verification = {
            "status": getattr(verification_report, "status", ""),
            "coverage": getattr(verification_report, "coverage", {}) or {},
            "answer_hash": getattr(verification_report, "answer_hash", ""),
            "checked_revision": checked,
            "current": not checked or checked == record_obj.revision,
        }
        execution_artifacts["result_record"] = record_obj.to_dict()
    except Exception as exc:  # noqa: BLE001 - the record is additive
        logger.warning("Result record failed: %s", exc)
    if ctx is not None and getattr(ctx, "scope", "research") == "research" and llm_ok:
        try:
            from ..deliverables import assess as assess_deliverables

            items = assess_deliverables(
                run.resolved_query or run.query,
                candidate_response,
                getattr(verification_report, "math_audit", None),
                tool_results=tool_results,
            )
            if getattr(run, "synthesis_model", "") == "verified_computation":
                # The answer is the checked computation in the requested form ("∅", "h(1) = 6"): every requested
                # item is delivered by it, which word overlap with the question cannot see (audit I27/I43).
                items = [{**it, "status": "verified", "answer_state": "answered", "check_state": "checked",
                          "where": "the verified computation, rendered in the requested form"}
                         for it in items]
            task_status = apply_deliverables(task_status, items)
            _sync_sub_questions(agent_state, items, tool_results)
        except Exception as exc:  # noqa: BLE001 - completeness notes are additive
            logger.warning("Deliverable assessment failed: %s", exc)
    violations = ((execution_artifacts or {}).get("output_contract") or {}).get("violations") or []
    if violations:
        task_status["incomplete_reasons"] = [*task_status.get("incomplete_reasons", []),
                                             f"Requested format not met: {'; '.join(violations)}."]
        if task_status.get("task_status") == "completed":
            task_status["task_status"] = "partial"
    merge_pipeline_phases(run)
    record("note_step", "task_status", {}, task_status)
    await close_open_steps()
    await _record_routing_outcome(run, task_status)

    return ao.AuthoritativeOrchestrationResult(
        thread_id=thread_id,
        response=candidate_response,
        thoughts=thoughts,
        reasoning=orch._sanitize_agent_names("".join(reasoning_parts)) if show_reasoning else "",
        steps=steps,
        selected_agents=list(dict.fromkeys(selected_agents)),
        duration_seconds=total_duration,
        model_used=model_name,
        framework_used=framework,
        verification_report=verification_report.model_dump(),
        execution_artifacts=execution_artifacts,
        citations=citation_map,
        run_manifest=await finalize_manifest(candidate_response, total_duration, framework=framework),
        query_context=query_context_artifact,
        task_status=task_status,
    )
