"""Stage 0: read the question, recall memory, run the agentic pre-evidence phases and decide the sources."""

from __future__ import annotations

import json
import time
from typing import Any

from ...agentic import config as agent_config
from ...utils.memory.research_memory import MemoryContextPackage
from .. import query_planner
from ..query_context import SourceDecision, TaskOutcome
from .context import RunContext, logger, orchestrator_module


async def start(run: RunContext) -> Any | None:
    """Announce an agentic run and answer a greeting directly. Returns the result when the run ends here."""
    ao = orchestrator_module()
    if run.control is not None:
        # First event of an agentic run: the client needs the run id to approve, steer or cancel.
        await run.send(
            {"type": "run_control", "run_id": run.control.run_id, "framework": run.framework, "interactive": run.control.interactive}
        )

    # -------------------------------------------------------------
    # STAGE 0.1: CASUAL / GREETING INTENT (Ordinary Conversation)
    # -------------------------------------------------------------
    is_casual = any(p.match(run.query.strip()) for p in ao._CASUAL_RES)
    if is_casual:
        # A fixed introduction: nothing was reasoned about or looked up, so no activity is shown.
        resp = ao._INTRODUCTION
        duration = round(time.perf_counter() - run.start_time, 2)
        return ao.AuthoritativeOrchestrationResult(
            thread_id=run.thread_id,
            response=resp,
            thoughts=run.thoughts,
            steps=[],
            selected_agents=[],
            duration_seconds=duration,
            model_used=run.model_name,
            framework_used="conversational-direct",
            verification_report={"passed": True, "verification_score": 1.0, "defects": []},
            run_manifest=await run.finalize_manifest(resp, duration, framework="conversational-direct"),
            task_status=TaskOutcome(
                requested_operation="conversation", executed_operation="conversation", reason="Greeting answered."
            ).model_dump(),
        )

    # -------------------------------------------------------------
    # STAGE 0.12: KAPPA GATE GUARD: A SELF-REFERENTIAL STATEMENT HAS NO GROUNDING CONTEXT (K = 0)
    # -------------------------------------------------------------
    # "This statement is false" is answered here, before the planner, any source, tool or model call (context_gate.py).
    from ..context_gate import is_self_referential

    if is_self_referential(run.query):
        resp = ao.PARADOX_REPLY
        await run.emit("plan", "Read the question", text="Self-referential statement · context K = 0, nothing looked up")
        duration = round(time.perf_counter() - run.start_time, 2)
        return ao.AuthoritativeOrchestrationResult(
            thread_id=run.thread_id,
            response=resp,
            thoughts=run.thoughts,
            steps=[],
            selected_agents=[],
            duration_seconds=duration,
            model_used=run.model_name,
            framework_used="kappa-gate",
            verification_report={"passed": True, "verification_score": 1.0, "defects": []},
            run_manifest=await run.finalize_manifest(resp, duration, framework="kappa-gate"),
            task_status=TaskOutcome(
                requested_operation="conversation", executed_operation="conversation",
                reason="A self-referential statement: no grounding context (K = 0); nothing was looked up.",
            ).model_dump(),
        )

    # -------------------------------------------------------------
    # STAGE 0.15: OUTPUT CONTRACT; A PURE LITERAL-COPY REQUEST IS ANSWERED BY COPYING
    # -------------------------------------------------------------
    from ...utils import output_contract

    run.output_contract = contract = output_contract.extract(run.query)
    if contract.pure_copy and contract.literal is not None:
        # "Return exactly the following lines ...": the answer is the payload, LF-normalised. No query planning,
        # retrieval, solver, critique or factual grounding applies, so none runs, whatever the Search setting.
        resp = contract.literal
        violations = output_contract.validate(resp, contract)
        await run.emit("plan", "Returned the requested text exactly",
                       "Literal copy: no sources searched, no tools, no claims to check",
                       extra={"thread_id": run.thread_id, "output_contract": contract.to_dict()})
        duration = round(time.perf_counter() - run.start_time, 2)
        return ao.AuthoritativeOrchestrationResult(
            thread_id=run.thread_id,
            response=resp,
            thoughts=run.thoughts,
            steps=run.steps,
            selected_agents=[],
            duration_seconds=duration,
            model_used=run.model_name,
            framework_used="literal-direct",
            verification_report={"passed": not violations, "verification_score": 1.0 if not violations else 0.0,
                                 "defects": [], "status": "not_applicable", "claims": []},
            execution_artifacts={"output_contract": {**contract.to_dict(), "violations": violations}},
            run_manifest=await run.finalize_manifest(resp, duration, framework="literal-direct"),
            task_status=TaskOutcome(
                requested_operation="literal_copy", executed_operation="literal_copy",
                reason="The requested text was returned exactly; no research or claim checks apply.",
            ).model_dump(),
        )
    from .scientific import answer_scientific_request

    return await answer_scientific_request(run)


async def read_question(run: RunContext) -> Any | None:
    """Build the query context, recall memory and run the agentic pre-evidence phases.

    Returns the result when the run ends here (a clarification request or a non-research message)."""
    ao = orchestrator_module()
    orch = run.orch
    query, thread_id, user_id, model_name, api_key = run.query, run.thread_id, run.user_id, run.model_name, run.api_key
    recall_memory = run.recall_memory
    pending = run.pending
    emit = run.emit

    registry = ao.get_tool_registry()
    clean_query = query.strip().strip('"\'')
    prior_subj = orch.memory.get_active_subject(user_id, thread_id) if recall_memory else None
    run.registry, run.clean_query, run.resolved_query = registry, clean_query, clean_query
    try:
        ao.load_extensions()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Extensions failed to load: %s", exc)

    await emit("plan", "Reading the question", status="running")
    # Auto: the router's model call needs only the question, so it runs while the question is read (attachments,
    # entities, evidence need) instead of after it.
    _start_router_prefetch(run, clean_query)
    try:
        resolution = await ao.resolve_attachments(
            user_id, list(run.dataset_ids or []), clean_query, owners=run.dataset_owners
        )
        attachments, attachment_errors = list(resolution.attachments), list(resolution.errors)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Attachment resolution failed: %s", exc)
        attachments = []
        attachment_errors = [f"Attached dataset {i} not found" for i in (run.dataset_ids or [])]
    ctx = await ao.build_query_context(
        query=clean_query,
        clean_query=clean_query,
        registry=registry,
        enable_web_search=run.enable_web_search,
        attachments=attachments,
        attachment_errors=attachment_errors,
        user_id=user_id,
        thread_id=thread_id,
        model_name=model_name,
        api_key=api_key,
        prior_subject=prior_subj,
        llm_factory=lambda **kw: ao.get_llm(**kw),
    )
    pending["ctx"] = ctx
    run.ctx = ctx
    ctx.effort_level = (run.agent_options or {}).get("effort_level", "medium")

    # -------------------------------------------------------------
    # STAGE 0: RECALL FROM PERSISTENT MEMORY (Mem0 Principles)
    # -------------------------------------------------------------
    if recall_memory:
        memory_pkg = orch.memory.get_context_package(thread_id, user_id=user_id)
        historical_identifiers = orch.memory.get_verified_identifiers(thread_id, user_id=user_id)
    else:
        memory_pkg = MemoryContextPackage(thread_id=thread_id)
        historical_identifiers = {}
    memory_summary = memory_pkg.to_system_prompt_injection()
    if run.project_instructions.strip():
        # The project's instructions are user-authored guidance: delimited and spotlighted like any untrusted text, so
        # they shape the answer's focus and format but never override the system rules.
        from tribos.agentic.guardrails import spotlight

        memory_summary = (
            f"{memory_summary}\n\n<project_instructions note=\"guidance the project's members wrote for every answer in "
            "this project; follow it where it does not conflict with the rules above\">\n"
            f"{spotlight(run.project_instructions, 'project instructions', 8000)}\n</project_instructions>"
        ).strip()
    research_context = str((run.agent_options or {}).get("research_context") or "").strip()
    if research_context:
        # A research project's earlier stages (tribos.agentic.campaign): background for this stage, kept out of the
        # question so the planners and parsers, which read the question, never mistake it for the request.
        from tribos.agentic.guardrails import spotlight

        memory_summary = (
            f"{memory_summary}\n\n<earlier_research_stages note=\"what the earlier stages of this research project "
            "established; build on it, keep its numbers and citations, and do not redo finished work\">\n"
            f"{spotlight(research_context, 'earlier research stages', 24000)}\n</earlier_research_stages>"
        ).strip()
    run.memory_pkg, run.historical_identifiers, run.memory_summary = memory_pkg, historical_identifiers, memory_summary

    # -------------------------------------------------------------
    # STAGE 0.2: NOT A RESEARCH QUESTION (no source is searched for it)
    # -------------------------------------------------------------
    if ctx.scope != "research" and recall_memory:
        # In a thread with history a vague message ("why?", "and its safety?") is a follow-up; only
        # unmistakable small talk is answered directly there.
        has_history = bool(
            memory_pkg.verified_evidence or memory_pkg.active_hypotheses or memory_pkg.computed_artifacts
            or memory_pkg.user_instructions or orch.memory.get_conversation_history(thread_id, user_id=user_id)
        )
        if has_history:
            ctx.scope = "conversational" if query_planner.is_small_talk(clean_query) else "research"
            query_planner.decide_builtin_sources(ctx)
    # -------------------------------------------------------------
    # AUTO: choose the architecture for this question before the agent state is built
    # -------------------------------------------------------------
    if run.framework == agent_config.AUTO:
        await _choose_framework(run)
    # -------------------------------------------------------------
    # AGENTIC RUNTIME (agentic frameworks only): clarify, decompose, recall project memory
    # -------------------------------------------------------------
    stopped = await _agentic_preflight(run)
    if stopped is not None:
        return stopped

    if ctx.scope != "research":
        return await _answer_non_research(run)
    return None


def _router_budget(run: RunContext) -> Any:
    """AGT-007: the run budget exists before routing, so the router's model calls are charged to it ("router" phase)
    and a tightened request budget limits them; _agentic_preflight reuses this budget."""
    if run.control is None:
        return None
    if run.pending.get("agent_budget") is None:
        ao = orchestrator_module()
        effort_level = (run.agent_options or {}).get("effort_level", "medium")
        run.pending["agent_budget"] = ao.RunBudget.from_env((run.agent_options or {}).get("budget"), effort_level=effort_level)
    return run.pending["agent_budget"]


def _start_router_prefetch(run: RunContext, question: str) -> None:
    """Start the router's features call for an Auto run, unless the question text alone already shows it is
    self-contained (the router then needs no model call, so starting one would only cost tokens)."""
    from ...agentic import router
    from ..evidence_need import assess_evidence_need

    run.pending["router_prefetch"] = None
    if run.framework != agent_config.AUTO or not router.semantic_enabled():
        return
    try:
        if assess_evidence_need(question).kind in ("closed_computation", "self_contained", "format"):
            return
    except Exception:  # noqa: BLE001 - when unsure, prefetch
        pass
    ao = orchestrator_module()
    task = router.start_semantic_reading(question, lambda **kw: ao.get_llm(**kw), run.model_name, run.api_key,
                                         budget=_router_budget(run))
    # A run that ends before routing (an error, a non-research reply) leaves the call to finish or fail quietly.
    task.add_done_callback(lambda t: t.cancelled() or t.exception())
    run.pending["router_prefetch"] = (question, task)


def _drop_unneeded_search(run: RunContext, decision: Any) -> None:
    """The question only "may" need outside evidence (no request for sources, nothing dated or measured) and the
    router's model judged that it does not: switch the literature and web search off before they run. Searches on such
    questions returned forum posts and unrelated papers, and their evidence-gap rounds cost tens of seconds."""
    from ..evidence_need import EvidenceNeed

    need = getattr(run.ctx, "evidence_need", None)
    semantic = getattr(decision, "semantic", None) or {}
    if need is None or not semantic.get("used"):
        return
    if need.kind == "established_knowledge" and semantic.get("needs_outside_information") is True:
        # The word-level guess "a conceptual question, no search" was wrong: "the maximum takeoff weight of a Boeing
        # 747-8" is a specific product's figure the model judged to need a source.
        run.ctx.evidence_need = EvidenceNeed(
            "optional", "web_fact", "the answer is a specific real-world fact (a product, place, person or measured "
            "value) that a source should confirm", "router judgement")
        query_planner.decide_builtin_sources(run.ctx)
        from ..query_context import SourceDecision

        # A product's specification or a place's figure is on the web, not in arXiv or Crossref: the scholarly search
        # made 30+ requests for one aircraft weight.
        for key in ("archivon", "lithoscribe"):
            if key in run.ctx.decisions:
                run.ctx.decisions[key] = SourceDecision(
                    run=False, reason="a specific real-world fact: answered from the web, not the scholarly literature")
        return
    if need.level != "optional" or need.kind != "open" or semantic.get("needs_outside_information", True):
        return
    run.ctx.evidence_need = EvidenceNeed(
        "none", "open", "no outside evidence needed: the question is answered from its own content and standard "
        "knowledge; ask for sources to search the literature", "router judgement")
    query_planner.decide_builtin_sources(run.ctx)


async def _choose_framework(run: RunContext) -> None:
    """Auto: route the question to one agentic framework and say why (docs/agentic/auto-routing.md)."""
    from ...agentic import router

    ao = orchestrator_module()
    research = run.ctx.scope == "research"
    if research:
        await run.emit("route", "Choosing the approach", status="running", agent="Router")
    budget = _router_budget(run)
    prefetch = run.pending.pop("router_prefetch", None)
    prefetched = None
    if prefetch is not None:
        question, task = prefetch
        # A follow-up resolved against the thread ("and its safety?") is a different question from the one sent early.
        if research and question == run.resolved_query:
            prefetched = task
        else:
            task.cancel()
    decision = await router.choose_framework(
        run.resolved_query,
        run.ctx,
        llm_factory=(lambda **kw: ao.get_llm(**kw)) if research else None,
        model_name=run.model_name,
        api_key=run.api_key,
        budget=budget,
        prefetched=prefetched,
    )
    run.framework = decision.framework
    run.routing = decision.to_artifact()
    _drop_unneeded_search(run, decision)
    if research:
        await run.emit("route", f"Chose {decision.display_label}", decision.reason, agent="Router",
                       extra={"framework": decision.framework, "rule": decision.rule})


async def _agentic_preflight(run: RunContext) -> Any | None:
    ao = orchestrator_module()
    control, agent_options, framework = run.control, run.agent_options, run.framework
    ctx, model_name, api_key = run.ctx, run.model_name, run.api_key
    run.agent_rt = None
    run.agent_state = None
    if control is not None:
        effort_level = (agent_options or {}).get("effort_level", "medium")
        budget = run.pending.pop("agent_budget", None) or ao.RunBudget.from_env((agent_options or {}).get("budget"), effort_level=effort_level)
        if run.start_time:
            budget.started = run.start_time
        agent_state = ao.AgentState(
            query=run.query,
            clean_query=run.resolved_query,
            ctx=ctx,
            registry=run.registry,
            user_id=run.user_id,
            thread_id=run.thread_id,
            model_name=model_name,
            api_key=api_key,
            framework=framework,
            budget=budget,
            control=control,
            llm=ao.AgentLLM(lambda **kw: ao.get_llm(**kw), agent_config.agent_model(model_name), api_key, budget),
            tool_results=run.tool_results,
            emit=run.emit,
            send=run.send,
            project_id=run.project_id,
            options=dict(agent_options or {}),
            memory_summary=run.memory_summary,
            start_time=run.start_time,
            tool_policy=getattr(run, "tool_policy", None) or getattr(ctx, "tool_policy", None),
        )
        if run.routing is not None:
            agent_state.bag["routing"] = run.routing  # the same dict: escalation is recorded on the run's routing
        agent_rt = ao.AgenticRuntime(agent_state)
        run.agent_state, run.agent_rt = agent_state, agent_rt
        ctx.extras["agentic"] = {"framework": framework, "run_id": control.run_id}
        # The per-request "Allow code analysis on datasets" option is authoritative: when it is off, the planner
        # and the specialists exclude every code-executing tool, and the sandbox gateway refuses the run itself.
        ctx.extras["code_analysis_forbidden"] = (agent_options or {}).get("enable_code_analysis", True) is False
        pre = await agent_rt.run_stage("before_evidence")
        if pre.stop_response:
            query_planner.cancel_planner(ctx)
            run.record("set_routing", ctx)
            duration = round(time.perf_counter() - run.start_time, 2)
            stop_artifacts = {**agent_state.artifacts, **pre.artifacts, "agent_run": agent_state.summary()}
            if run.routing is not None:
                stop_artifacts["framework_routing"] = run.routing
            return ao.AuthoritativeOrchestrationResult(
                thread_id=run.thread_id,
                response=pre.stop_response,
                thoughts=run.thoughts,
                steps=[],
                selected_agents=[],
                duration_seconds=duration,
                model_used=model_name,
                framework_used=framework,
                verification_report={"passed": True, "verification_score": 1.0, "defects": []},
                execution_artifacts=json.loads(json.dumps(stop_artifacts, default=str)),
                run_manifest=await run.finalize_manifest(pre.stop_response, duration, framework=framework),
                query_context=ctx.to_artifact(),
                task_status=pre.stop_task_status
                or TaskOutcome(task_status="needs_input", reason="The question needs clarification.").model_dump(),
            )
        if agent_state.project_memory:
            run.memory_summary = f"{run.memory_summary}\n\n{agent_state.project_memory}".strip()
    return None


async def _answer_non_research(run: RunContext) -> Any:
    ao = orchestrator_module()
    ctx, thread_id = run.ctx, run.thread_id
    query_planner.cancel_planner(ctx)
    run.record("set_routing", ctx)
    resp = ao._non_research_reply(run.clean_query, ctx.scope)
    await run.emit(
        "plan",
        title="Read the question",
        text="Not a research question · no sources searched"
        if ctx.scope == "conversational"
        else "Self-referential statement · context K = 0, nothing looked up"
        if ctx.scope == "paradox"
        else "No scientific or engineering topic found · no sources searched",
        extra={"thread_id": thread_id, **ctx.to_step_extra()},
    )
    duration = round(time.perf_counter() - run.start_time, 2)
    return ao.AuthoritativeOrchestrationResult(
        thread_id=thread_id,
        response=resp,
        thoughts=run.thoughts,
        steps=[],
        selected_agents=[],
        duration_seconds=duration,
        model_used=run.model_name,
        framework_used="conversational-direct",
        verification_report={"passed": True, "verification_score": 1.0, "defects": []},
        run_manifest=await run.finalize_manifest(resp, duration, framework="conversational-direct"),
        query_context=ctx.to_artifact(),
        task_status=TaskOutcome(
            task_status="completed" if ctx.scope in ("conversational", "paradox") else "needs_input",
            requested_operation="conversation" if ctx.scope == "conversational" else None,
            executed_operation="conversation" if ctx.scope == "conversational" else None,
            request_match=ctx.scope == "conversational",
            reason="Not a research question; no sources were searched."
            if ctx.scope == "conversational"
            else "A self-referential statement: no grounding context (K = 0), nothing was looked up."
            if ctx.scope == "paradox"
            else "No scientific or engineering topic was found in the question.",
        ).model_dump(),
    )


async def route_sources(run: RunContext) -> None:
    """Decide which registered evidence sources run, report the plan and (agentic) wait for its approval."""
    ao = orchestrator_module()
    ctx, registry, memory_pkg, thread_id = run.ctx, run.registry, run.memory_pkg, run.thread_id
    emit = run.emit

    run.record("set_routing", ctx)
    run.record(
        "set_memory_context",
        n_evidence=len(memory_pkg.verified_evidence),
        n_instructions=len(memory_pkg.user_instructions),
        memory_summary=run.memory_summary,
    )

    # Registered evidence sources: skipped silently when their tools are not registered.
    try:
        all_sources = [s for s in ao.get_sources() if s.stage == 1]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Evidence sources unavailable: %s", exc)
        all_sources = []
    evaluated_sources: list[Any] = []
    active_sources: list[Any] = []
    for src in all_sources:
        if any(registry.get_entry(t) is None for t in src.required_tools):
            ctx.decisions[src.key] = SourceDecision(run=False, reason="tool not available")
            continue
        try:
            decision = src.should_run(ctx)
            if not isinstance(decision, SourceDecision):
                decision = SourceDecision(run=bool(decision))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s routing failed: %s", src.key, exc)
            decision = SourceDecision(run=False, reason=f"routing error: {type(exc).__name__}")
        # ORC-002: the turn's source restriction ("papers only", "trials only") is enforced here for every
        # registered source, not left to each source's own should_run.
        allowed = ctx.source_allowed(src.key) or ctx.source_allowed(getattr(src, "agent", "").lower())
        if decision.run and not allowed:
            decision = SourceDecision(run=False, reason=ctx.source_restriction_reason or "excluded at your request")
        ctx.decisions[src.key] = decision
        evaluated_sources.append(src)
        if decision.run:
            active_sources.append(src)

    # Report what was actually parsed from the question and recalled, so routing is inspectable.
    plan_facts: list[str] = list(ctx.plan_facts())
    for src in active_sources:
        try:
            fact = src.plan_fact(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s plan fact failed: %s", src.key, exc)
            fact = None
        if fact:
            plan_facts.append(fact)
    if memory_pkg.verified_evidence or memory_pkg.user_instructions:
        plan_facts.append(
            f"Recalled {len(memory_pkg.verified_evidence)} evidence item(s) and "
            f"{len(memory_pkg.user_instructions)} instruction(s) from this session"
        )
    if ctx.attachments or ctx.attachment_errors:
        used = [f"{a.display_name}" + (f" ({a.dims})" if a.dims else "") for a in ctx.attachments]
        if ctx.attachment_errors:
            n_err = len(ctx.attachment_errors)
            title = ctx.attachment_errors[0] if n_err == 1 else f"{n_err} attached datasets not found"
            detail = ctx.attachment_errors[1:] + ([f"Using {', '.join(used)}"] if used else [])
            await emit("attachments", title, " · ".join(detail), status="error")
        else:
            n = len(ctx.attachments)
            await emit("attachments", f"Using {n} uploaded dataset{'s' if n != 1 else ''}: {', '.join(used)}")
    await emit(
        "plan",
        title="Read the question",
        text=" · ".join(plan_facts),
        extra={"thread_id": thread_id, "memory_nodes_active": len(memory_pkg.verified_evidence), **ctx.to_step_extra()},
    )

    if run.agent_rt is not None:
        await run.agent_rt.run_stage("approve")
        # Plan approval may have switched sources off.
        active_sources = [s for s in active_sources if ctx.decisions.get(s.key, SourceDecision(run=True)).run]

    run.evaluated_sources, run.active_sources = evaluated_sources, active_sources
    title_ctx: dict[str, Any] = {
        "target": ctx.primary_display,
        "model": ctx.biomodel_id or (ctx.model_attachment.display_name if ctx.model_attachment else None),
        "dataset": ctx.dataset_attachment.display_name if ctx.dataset_attachment else ctx.dataset_path,
    }
    run.title_ctx = title_ctx
