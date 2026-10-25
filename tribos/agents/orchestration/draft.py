"""Stage 4: the evidence summaries and scope notes, the synthesis prompt and the first, streamed draft."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ...agentic.budget import BudgetExhausted, RunDeadlineExceeded
from ...agentic.control import RunCancelled
from ..evidence_need import CLOSED_COMPUTATION_ANSWER_NOTE, is_closed_computation
from ..result_keys import (
    AXIOM,
    CALCULA,
    DYNAMIS,
    DYNAMIS_EQUILIBRIUM,
    DYNAMIS_SCAN,
    distinct_results,
)
from .context import RunContext, logger, orchestrator_module


class DraftBudgetStop(RuntimeError):
    """The run budget could not admit the first draft: the answer is the deterministic evidence summary."""


class EmptyDraftError(RuntimeError):
    """The model returned no answer text (only reasoning), even on the retry: the answer is the evidence summary."""


def first_draft_output_cap() -> int:
    """Output tokens (reasoning included) allocated to the first draft in agentic runs
    (TRIBOS_FIRST_DRAFT_MAX_OUTPUT_TOKENS, default 16000): it is admitted from the run budget and sent to the
    model as max_tokens, like every other agentic model call (audit F1)."""
    try:
        return max(256, int(os.getenv("TRIBOS_FIRST_DRAFT_MAX_OUTPUT_TOKENS", "") or 16_000))
    except ValueError:
        return 16_000


# A draft the provider cut off at max_tokens (finish reason "length") is continued, at most this many times, so an
# answer never ends mid-sentence.
MAX_DRAFT_CONTINUATIONS = 2
CONTINUE_PROMPT = (
    "Your answer above was cut off by the output limit. Continue it from exactly where it stopped: do not repeat "
    "anything already written, add no preamble or heading for the continuation, and start with the next characters "
    "of the cut-off sentence. Finish every remaining section the answer format calls for."
)


def join_continuation(text: str, more: str, window: int = 300) -> str:
    """text + more, without the overlap a model sometimes repeats at the start of a continuation."""
    tail = text[-window:]
    for n in range(min(len(tail), len(more)), 7, -1):
        if tail.endswith(more[:n]):
            return text + more[n:]
    return text + more


def fallback_reason(err: BaseException) -> str:
    """Why the written answer is missing, for a reader: never an empty message."""
    name = type(err).__name__
    if "Timeout" in name:
        return "the model provider did not respond in time (twice)"
    text = str(err).strip()
    return f"{name}: {text[:200]}" if text else name


def verification_fallback_markdown(rep: dict[str, Any] | None) -> str:
    """The computed parameters and numerical checks as a table, for an answer the model could not write."""
    if not isinstance(rep, dict):
        return ""
    rows = ["| Quantity | Value | Unit |", "|---|---:|---|"]
    for key, p in (rep.get("parameters") or {}).items():
        if not isinstance(p, dict) or "value" not in p:
            continue
        value = p["value"]
        shown = f"{value:.6g}" if isinstance(value, (int, float)) else str(value)
        if isinstance(p.get("degrees"), (int, float)):
            shown += f" ({p['degrees']:.4g}°)"
        rows.append(f"| {key.replace('_', ' ').capitalize()} | {shown} | {p.get('unit') or ''} |")
    conv = rep.get("convergence") or []
    checks = [f"ODE residual: max |r| = {rep.get('residual_max', 0):.3g}"]
    if conv:
        last = conv[-1]
        checks.append(f"RK4 at h = {last['h']} s: max error {last['max_error_x']:.3g}"
                      + (f", observed order {last['observed_order']:.2f}" if "observed_order" in last else ""))
    energy = rep.get("energy") or {}
    if "balance_residual" in energy:
        checks.append(f"Energy balance residual: {energy['balance_residual']:.3g} J")
    table = "\n".join(rows) if len(rows) > 2 else ""
    return (table + "\n\n" if table else "") + "\n".join(f"- {c}" for c in checks)


def retrieval_date() -> str:
    """Today's date in UTC (YYYY-MM-DD), from the server clock: what time-sensitive facts are dated "as of"."""
    return datetime.now(UTC).date().isoformat()


# A rewrite edits the previous draft rather than writing a new answer: unchanged sections stay verbatim, so a round
# costs the changed claims, not a whole new ~2,000-word answer, and verified text is not reworded for nothing.
REVISION_INSTRUCTION = (
    "Revise the previous draft to address this critique; keep what is supported. Change only the sentences, table "
    "rows or sections that the new evidence or the critique affects; copy every other part of the previous draft "
    "verbatim (same headings, wording, order and citations). If nothing needs to change, return the previous draft "
    "unchanged:"
)


def _ok_data(tool_results: dict[str, Any], key: str) -> dict[str, Any] | None:
    res = tool_results.get(key)
    return res.data if res is not None and res.success and isinstance(res.data, dict) and res.data else None


def computation_summary(tool_results: dict[str, Any]) -> str:
    """Markdown lines with what the STEM computations returned (Dynamis, Axiom, Physis, Calcula), as computed.

    Shown when the model could not write the answer, so every value is the tool's own; nothing is interpreted."""
    from ..stem_evidence import num

    lines: list[str] = []
    sim = _ok_data(tool_results, DYNAMIS)
    if sim is not None:
        summary = sim.get("summary") or {}
        final = {s: num(v.get("final")) for s, v in summary.items() if isinstance(v, dict) and "final" in v}
        lines.append(
            f"- **System**: {sim.get('model_name') or 'stated ODE system'} · method {sim.get('method') or 'unknown'} · "
            f"t = {sim.get('t_span')}"
        )
        if final:
            lines.append(f"- **Final state**: {json.dumps(final)}")
    eq = _ok_data(tool_results, DYNAMIS_EQUILIBRIUM)
    if eq is not None:
        point = {k: num(v) for k, v in (eq.get("fixed_point") or {}).items()}
        eig = [e.get("str") for e in (eq.get("eigenvalues") or []) if isinstance(e, dict)]
        lines.append(f"- **Fixed point** ({eq.get('stability', 'unknown')}): {json.dumps(point)}; eigenvalues {', '.join(eig)}")
    elif sim is not None:
        lines.append("- **Equilibrium**: not computed; the final state is the end of the time course, not a steady state.")
    scan = _ok_data(tool_results, DYNAMIS_SCAN)
    if scan is not None:
        rows = [r for r in (scan.get("scan_results") or []) if isinstance(r, dict)]
        lines.append(f"- **Parameter scan** of {scan.get('parameter')} over {scan.get('scan_range')} ({len(rows)} points):")
        lines.extend(
            f"  - {scan.get('parameter')} = {num(r.get('parameter_value'))}: final state "
            f"{json.dumps({k: num(v) for k, v in (r.get('final_state') or {}).items()})}"
            for r in rows[:20]
        )
    ax = _ok_data(tool_results, AXIOM)
    if ax is not None and isinstance(ax.get("answer"), dict) and ax["answer"].get("text"):
        lines.append(f"- **Symbolic solution (Axiom, {str(ax.get('status') or '').replace('_', ' ')})**: {ax['answer']['text']}")
    phys = _ok_data(tool_results, "physis")
    for c in ((phys or {}).get("constants") or [])[:5]:
        if isinstance(c, dict):
            lines.append(f"- **{c.get('name')}**: {c.get('value')} {c.get('unit') or ''} (uncertainty {c.get('uncertainty')}; "
                         f"{c.get('source') or 'source not stated'})")
    calc = _ok_data(tool_results, CALCULA)
    if calc is not None and (calc.get("result") is not None or calc.get("stdout")):
        shown = calc.get("result") if calc.get("result") is not None else calc.get("stdout")
        lines.append(f"- **Sandboxed computation (Calcula)**: {str(shown)[:400]}")
    return "\n".join(lines) + ("\n" if lines else "")


def prepare_context(run: RunContext) -> None:
    """Plain-text tool summaries (used by the no-model fallback) and the scope notes passed to the model."""
    ao = orchestrator_module()
    orch = run.orch
    ctx, tool_results, requested_plan = run.ctx, run.tool_results, run.requested_plan
    evaluated_sources = run.evaluated_sources

    # -------------------------------------------------------------
    # STAGE 4: EVIDENCE SYNTHESIS (PaperQA2 Grounded Context)
    # -------------------------------------------------------------
    # Prepare structured context from empirical tool executions: the computed values, for the no-model fallback.
    vivarix_summary = computation_summary(tool_results)

    lumicell_summary = ""
    if tool_results.get("lumicell") and tool_results["lumicell"].success and isinstance(tool_results["lumicell"].data, dict):
        l_data = tool_results["lumicell"].data
        lumicell_summary = (
            f"- **Single-Cell Atlas**: {l_data.get('n_cells_post_qc')} cells across {l_data.get('n_clusters')} Leiden clusters\n"
            f"- **Top Marker Genes per Cluster**: {json.dumps({k: [m['gene'] for m in v[:3]] for k, v in l_data.get('top_markers_by_cluster', {}).items()})}\n"
            f"- **Target Expression**: {json.dumps(l_data.get('target_expression_summary', {}))}\n"
        )

    lithoscribe_summary = ""
    if tool_results.get("lithoscribe") and tool_results["lithoscribe"].success and isinstance(tool_results["lithoscribe"].data, dict):
        lit_data = tool_results["lithoscribe"].data
        top_psgs = lit_data.get("ranked_passages", [])[:4]
        passages_text = []
        for p in top_psgs:
            setting = p.get("grade_label") or p.get("experimental_setting") or "unclassified"
            passages_text.append(f"- **{p.get('citation') or p.get('citation_label') or 'Passage'}** ({setting}): {p.get('passage_text', '')[:200]}")
        lithoscribe_summary = "\n".join(passages_text)

    synapta_summary = ""
    if tool_results.get("synapta") and tool_results["synapta"].success and isinstance(tool_results["synapta"].data, dict):
        s_data = tool_results["synapta"].data
        assocs = s_data.get("associations", [])[:3]
        assoc_str = ", ".join(f"{a.get('disease_name')} (score: {a.get('overall_association_score')})" for a in assocs) if assocs else "Target-disease network evaluated"
        synapta_summary = f"- **Associated Diseases**: {assoc_str}"
        pathways = s_data.get("pathways", []) or []
        if pathways:
            pw_str = ", ".join(f"{p.get('description', p.get('id'))} ({p.get('id')})" for p in pathways[:5])
            synapta_summary += f"\n- **KEGG Pathway Memberships**: {pw_str}"

    scope_notes: list[str] = []
    # A simulation that was not requested is simply not part of this answer: no note, so it is never listed as a
    # limitation. An explicit "no simulation" constraint is passed on so the answer respects it silently.
    if ctx.suppress_simulation:
        scope_notes.append(
            "The researcher asked not to run simulations, so none was run; do not discuss simulation and do not "
            "list it as a limitation."
        )
    if not ctx.enable_web_search:
        scope_notes.append("Live web search was disabled for this turn.")
    # What the gather stages did not run (no Calcula code, no identifiable system, no symbolic solution).
    scope_notes.extend(n for n in dict.fromkeys(run.gather_notes) if n)
    # Pre-synthesis check: the artifact must match the request, or the answer must say it does not.
    pre_outcome = orch._task_outcome(ctx, requested_plan, tool_results, None, True)
    if requested_plan is not None and pre_outcome.task_status in ("failed", "needs_input", "partial"):
        scope_notes.append(
            f"TASK STATUS ({pre_outcome.task_status.upper()}): the researcher requested a "
            f"{requested_plan.action.replace('_', ' ')}"
            + (f" but a {pre_outcome.executed_operation.replace('_', ' ')} ran" if pre_outcome.executed_operation
               and pre_outcome.executed_operation != requested_plan.action else "")
            + f". {pre_outcome.reason} Do not present any other computation as the requested result, do not "
            "substitute another model, duration or parameter, and state plainly what was not done and why."
        )
    for src in evaluated_sources:
        try:
            scope_notes.extend(n for n in (src.scope_notes(ctx, tool_results.get(src.key)) or []) if n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s scope notes failed: %s", src.key, exc)
    for provider in ao.get_scope_note_providers():
        try:
            scope_notes.extend(n for n in (provider(ctx, tool_results) or []) if n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scope note provider failed: %s", exc)
    if is_closed_computation(ctx):
        scope_notes.append(CLOSED_COMPUTATION_ANSWER_NOTE)
    run.vivarix_summary, run.lumicell_summary = vivarix_summary, lumicell_summary
    run.lithoscribe_summary, run.synapta_summary = lithoscribe_summary, synapta_summary
    run.scope_notes = scope_notes


def build_prompt(run: RunContext, feedback: list[str] | None = None, previous_draft: str = "") -> str:
    """The synthesis request; agentic runs add the research brief, the critique to address and the previous draft."""
    ao = orchestrator_module()
    agent_state, tool_results, discovery_report, ctx = run.agent_state, run.tool_results, run.discovery_report, run.ctx
    scope_notes, memory_summary, query = run.scope_notes, run.memory_summary, run.query
    extra_sections: list[str] = []
    brief = ""
    if agent_state is not None:
        extra_sections = ao.render_agent_evidence(tool_results, agent_state.evidence_labels, agent_state.evidence_sections)
        brief = agent_state.research_brief()
        if feedback:
            brief += f"\n{REVISION_INSTRUCTION}\n" + "\n".join(f"- {f}" for f in feedback)
        if previous_draft:
            brief += f"\n<previous_draft>\n{previous_draft[:12000]}\n</previous_draft>"
    return ao.build_synthesis_request(
        evidence_block=ao.build_evidence_block(
            tool_results, discovery_report.to_markdown_summary(), query_context=ctx, extra_sections=extra_sections
        ),
        tool_status_block=ao.build_tool_status_block(
            tool_results, scope_notes + (agent_state.scope_notes if agent_state is not None else [])
        ),
        memory_summary=memory_summary,
        query=query,
        question_type=ctx.search_plan.question_type if ctx.search_plan is not None else "general",
        research_brief=brief,
        retrieval_date=retrieval_date(),  # UTC; dates approvals, trial status and FAERS counts
    )


async def write_first_draft(run: RunContext) -> None:
    """Stream the first draft from the synthesis model; on a model error, show the raw evidence instead."""
    ao = orchestrator_module()
    orch = run.orch
    agent_state, tool_results, model_name, api_key = run.agent_state, run.tool_results, run.model_name, run.api_key
    emit, send, record, on_reasoning, on_text = run.emit, run.send, run.record, run.on_reasoning, run.on_text
    successful_sources, clean_query, scope_notes = run.successful_sources, run.clean_query, run.scope_notes
    vivarix_summary, lumicell_summary = run.vivarix_summary, run.lumicell_summary
    lithoscribe_summary, synapta_summary = run.lithoscribe_summary, run.synapta_summary

    if agent_state is not None:
        agent_state.bag.setdefault("steering", []).extend(agent_state.control.drain_steering())
    synthesis_prompt = build_prompt(run)
    system_prompt = ao.get_synthesis_system_prompt()
    if agent_state is not None:
        system_prompt = f"{system_prompt}\n\n{ao.SPOTLIGHT_RULE}"

    effort_level = getattr(run.ctx, "effort_level", None) or (run.agent_options or {}).get("effort_level", "medium")
    from ...agentic.config import get_effort_profile
    effort_prof = get_effort_profile(effort_level)

    # Keyed by the effort profile's deliberation_depth (tribos/agentic/config.py EFFORT_PROFILES).
    deliberation_prompts = {
        "minimal": "\n[EFFORT LEVEL: LOW / FAST]\nPrioritize a direct, concise answer without lengthy internal deliberation. Give the governing result, its value with units, and the one assumption it rests on.",
        "standard": "\n[EFFORT LEVEL: MEDIUM / BALANCED]\nConduct standard scientific and engineering reasoning. Balance depth with clarity: state the governing equations and assumptions, show the key steps, and note the validity regime and main caveats.",
        "deep": "\n[EFFORT LEVEL: HIGH / DEEP THINKING]\nEngage in deep, multi-angle deliberation. Check every derivation step and its assumptions, verify dimensional consistency and limiting cases, compare alternative models or regimes, and weigh numerical results (method, step size, convergence) against analytical ones before concluding.",
        "exhaustive": "\n[EFFORT LEVEL: ULTRA / EXHAUSTIVE THINKING]\nEngage in exhaustive, maximal-rigor deliberation. Systematically interrogate every modelling assumption, boundary and initial condition, limiting and edge case, numerical error source (discretization, conditioning, convergence, tolerances), uncertainty propagation and significant figures, and any discordant literature or tool result; stress-test the conclusion against alternative models and regimes.",
    }
    depth = effort_prof.get("deliberation_depth", "standard")
    delib_text = deliberation_prompts.get(depth, "")
    if delib_text:
        system_prompt = f"{system_prompt}\n{delib_text}"

    distinct = distinct_results(tool_results)  # an alias key ("lithoscribe", "vivarix") is not another source
    n_ok = sum(1 for r in distinct.values() if r.success)
    sources_text = f"{n_ok} of {len(distinct)} sources returned evidence"
    await emit(
        "synthesis",
        title="Reasoning over the evidence",
        text=sources_text,
        status="running",
        extra={"model": model_name, "effort_level": effort_level},
    )

    candidate_response = ""
    llm_ok = True
    fallback_error: str | None = None
    llm: Any = None
    # The answer can be written by a larger model than the one that routes and plans (TRIBOS_SYNTHESIS_MODEL).
    synthesis_model = os.getenv("TRIBOS_SYNTHESIS_MODEL", "").strip() or model_name
    # Agentic runs admit the first draft from the run budget like every other model call (audit F1): it is charged,
    # sent its exact output allocation, reconciled afterwards, and never started when the budget cannot admit it.
    # The classic pipeline has no run budget: its draft stays unledgered (budget.py documents this).
    budget = getattr(agent_state, "budget", None) if agent_state is not None else None
    alloc = None
    draft_text = ""
    draft_reasoning = ""
    streamed_chars = [0]  # what reached the client before a failure: charged when the call is settled as failed

    async def counted_text(delta: str) -> None:
        streamed_chars[0] += len(delta or "")
        await on_text(delta)

    want = first_draft_output_cap()
    finish = [""]  # the provider's finish reason of the latest draft call

    def on_finish(reason: str) -> None:
        finish[0] = reason

    try:
        llm_kwargs: dict[str, Any] = {}
        if budget is not None:
            try:
                alloc = budget.admit(
                    "first_draft", len(system_prompt) + len(synthesis_prompt), want, min_output=min(1024, want)
                )
            except BudgetExhausted as exc:
                raise DraftBudgetStop(str(exc)) from exc
            llm_kwargs["max_tokens"] = alloc.output_cap
        llm = ao.get_llm(
            model_name=synthesis_model,
            api_key=api_key,
            streaming=True,
            reasoning_effort=effort_prof.get("reasoning_effort"),
            **llm_kwargs,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=synthesis_prompt),
        ]
        stream_kwargs: dict[str, Any] = {}
        if budget is not None and budget.time_limited:
            stream_kwargs["total_timeout"] = ao.stream_timeout(budget.remaining_seconds())
        for attempt in (1, 2):
            try:
                draft_text, draft_reasoning = await run.watched(
                    "synthesis",
                    ao.astream_with_reasoning(llm, messages, on_reasoning=on_reasoning, on_text=counted_text, on_finish=on_finish,
                                             **stream_kwargs),
                )
                break
            except Exception as exc:  # noqa: BLE001
                # A transient provider failure (HTTP 500, dropped connection) gets one more attempt before the answer
                # falls back to the raw evidence; anything already shown is cleared first, so nothing is duplicated.
                if attempt == 2 or type(exc).__name__ not in ao._TRANSIENT_STREAM_ERRORS:
                    raise
                logger.warning("First draft failed (%s); retrying once without extended reasoning", type(exc).__name__)
                if streamed_chars[0]:
                    await send({"type": "content_reset", "reason": "retry"})
                    streamed_chars[0] = 0
                await emit("synthesis", title="Model error; writing the answer again", text=type(exc).__name__,
                           status="running")
                # A long silent reasoning pass is what times out (no bytes for minutes), so the retry answers directly.
                llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, streaming=True, reasoning_effort="low",
                                 **llm_kwargs)
                await asyncio.sleep(2.0)
        candidate_response = draft_text
        if alloc is not None:
            budget.settle(alloc, output_chars=len(draft_text or "") + len(draft_reasoning or ""))
            alloc = None
        if not (draft_text or "").strip():
            # A reasoning model can spend its whole output allocation thinking and return no answer text. Ask once more
            # with extended reasoning off (the answer text then gets the allocation); an empty draft is never kept.
            logger.warning("First draft returned no text (%d reasoning chars); retrying without extended reasoning",
                           len(draft_reasoning or ""))
            await emit("synthesis", title="Writing the answer again: the first attempt returned no text",
                       text=f"{len(draft_reasoning or '')} characters of reasoning, no answer text", status="running")
            retry_kwargs: dict[str, Any] = {}
            if budget is not None:
                try:
                    alloc = budget.admit(
                        "first_draft", len(system_prompt) + len(synthesis_prompt), want, min_output=min(1024, want)
                    )
                except BudgetExhausted as exc:
                    raise DraftBudgetStop(str(exc)) from exc
                retry_kwargs["max_tokens"] = alloc.output_cap
            llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, streaming=True, reasoning_effort="low",
                             **retry_kwargs)
            draft_text, retry_reasoning = await run.watched(
                "synthesis",
                ao.astream_with_reasoning(llm, messages, on_reasoning=on_reasoning, on_text=counted_text, on_finish=on_finish,
                                             **stream_kwargs),
            )
            if alloc is not None:
                budget.settle(alloc, output_chars=len(draft_text or "") + len(retry_reasoning or ""))
                alloc = None
            candidate_response = draft_text
            if not (draft_text or "").strip():
                raise EmptyDraftError("the model returned reasoning but no answer text, twice")
        for _ in range(MAX_DRAFT_CONTINUATIONS):
            if finish[0] != "length" or not candidate_response.strip():
                break
            logger.warning("First draft hit the output limit after %d words; continuing it", len(candidate_response.split()))
            await emit("synthesis", title="Continuing the answer: it reached the output limit",
                       text=f"{len(candidate_response.split())} words so far", status="running")
            finish[0] = ""
            cont_kwargs: dict[str, Any] = {}
            if budget is not None:
                try:
                    alloc = budget.admit("first_draft", len(system_prompt) + len(synthesis_prompt) + len(candidate_response),
                                         want, min_output=min(1024, want))
                except BudgetExhausted:
                    break  # the cut-off draft stands; the budget cannot pay for more
                cont_kwargs["max_tokens"] = alloc.output_cap
            llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, streaming=True, reasoning_effort="low",
                             **cont_kwargs)
            cont_messages = [*messages, AIMessage(content=candidate_response), HumanMessage(content=CONTINUE_PROMPT)]
            more, more_reasoning = await run.watched(
                "synthesis",
                ao.astream_with_reasoning(llm, cont_messages, on_reasoning=on_reasoning, on_text=counted_text,
                                          on_finish=on_finish, **stream_kwargs),
            )
            if alloc is not None:
                budget.settle(alloc, output_chars=len(more or "") + len(more_reasoning or ""))
                alloc = None
            if not (more or "").strip():
                break
            candidate_response = join_continuation(candidate_response, more)
        await emit(
            "synthesis",
            title="Reasoned over the evidence and wrote the answer",
            text=f"{sources_text} · {len(candidate_response.split())} words",
        )
    except BaseException as err:
        if alloc is not None:
            # Cancelled, failed or deadline: the prompt stays charged, the unused allocation is released.
            budget.settle(alloc, output_chars=streamed_chars[0] or None, failed=True)
        if isinstance(err, RunCancelled) or not isinstance(err, Exception):
            raise
        llm_ok = False
        fallback_error = f"{type(err).__name__}: {str(err)[:240]}"
        logger.warning("LLM synthesis error: %s. Generating deterministic evidence fallback.", err)
        if isinstance(err, DraftBudgetStop):
            title = "Agent budget used up before the answer could be written; showing the gathered evidence"
        elif isinstance(err, EmptyDraftError):
            title = "The model returned no answer text; showing the computed results and evidence"
        elif isinstance(err, RunDeadlineExceeded):
            title = "Run time budget ran out while writing; showing the gathered evidence"
        else:
            title = "Model unavailable; showing the raw evidence instead"
        await emit(
            "synthesis",
            title=title,
            text=f"{type(err).__name__}: {str(err)[:240]}",
            status="error",
        )
        await send({"type": "content_reset", "reason": "model_error"})
        plugin_sections = []
        for src in successful_sources:
            try:
                md = src.fallback_markdown(tool_results[src.key])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Source %s fallback markdown failed: %s", src.key, exc)
                continue
            if md and md.strip():
                plugin_sections.append(md.strip() + "\n\n")
        # Deterministic, evidence-backed fallback without fake conclusions: only the sections that hold results.
        math_art = (getattr(agent_state, "artifacts", None) or {}).get("math_agent") if agent_state is not None else None
        math_answer = (math_art or {}).get("answer") or {}
        ode_art = (getattr(agent_state, "artifacts", None) or {}).get("ode_verification") if agent_state is not None else None
        sections = [
            ("Computed result (Axiom)", f"$${math_answer['latex']}$$\n\nStatus: {(math_art or {}).get('status', '').replace('_', ' ')}"
             if math_answer.get("latex") else ""),
            ("Numerical verification", verification_fallback_markdown(ode_art)),
            ("Computed results (Dynamis, Axiom, Physis, Calcula)", vivarix_summary),
            ("Literature passages (Archivon)", lithoscribe_summary),
            ("Target-disease associations", synapta_summary),
            ("Single-cell analysis", lumicell_summary),
        ]
        body = "".join(f"#### {title_}\n{text_}\n\n" for title_, text_ in sections if (text_ or "").strip())
        candidate_response = (
            f"### Results gathered for: {clean_query}\n\n"
            "The written answer could not be produced, so these are the tool results as computed, without "
            "interpretation.\n\n"
            f"{body}{''.join(plugin_sections)}"
            "#### Evidence limitations\n"
            f"No written answer: {fallback_reason(err)}. Check the results above against the question before relying "
            "on them."
        )

    # What the client has on screen: the streamed draft (or, after a model error, nothing it must replace).
    raw_draft = candidate_response
    candidate_response = orch._sanitize_answer(candidate_response)
    streamed_draft = raw_draft if llm_ok else candidate_response
    record(
        "set_synthesis",
        system_prompt_sha256=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        synthesis_prompt_sha256=hashlib.sha256(synthesis_prompt.encode("utf-8")).hexdigest(),
        scope_notes=list(scope_notes),
        llm_ok=llm_ok,
        fallback_error=fallback_error,
        response_words=len(candidate_response.split()),
        temperature=getattr(llm, "temperature", None) if llm_ok else None,
        # PRV-002: the model asked to write the answer and the one whose client actually served it.
        synthesis_model=synthesis_model,
        synthesis_served_model=getattr(llm, "model_name", None) if llm_ok else None,
    )
    run.synthesis_prompt, run.system_prompt, run.synthesis_model = synthesis_prompt, system_prompt, synthesis_model
    run.llm_ok, run.candidate_response, run.streamed_draft = llm_ok, candidate_response, streamed_draft
