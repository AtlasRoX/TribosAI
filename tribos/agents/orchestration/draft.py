"""Stage 4: the evidence summaries and scope notes, the synthesis prompt and the first, streamed draft."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ...agentic.budget import BudgetExhausted, RunDeadlineExceeded
from ...agentic.control import RunCancelled
from ..evidence_need import (
    CLOSED_COMPUTATION_ANSWER_NOTE,
    PROOF_ATTEMPT_NOTE,
    is_closed_computation,
    is_self_contained,
)
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


def compute_draft_output_cap(closed_calc: bool, has_strict: bool, exact_items: int = 0) -> int:
    """Output tokens allocated to the first draft: the same ceiling for every question. A ceiling never makes the model
    write less (it stops when the answer is done); a lower one only cuts off the answers that needed more, which then
    cost continuation calls. A short answer is kept fast by the low reasoning effort a closed calculation or strict
    contract is drafted with, not by truncation."""
    del closed_calc, has_strict, exact_items  # kept in the signature: callers pass the question's shape
    return first_draft_output_cap()


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


def sanitize_error_message(err: BaseException | str) -> str:
    """Sanitize error messages for user-facing displays to strip internal URLs, keys, or stack traces."""
    msg = str(err or "").strip()
    msg = re.sub(r"\b(?:sk-[a-zA-Z0-9_\-]{8,}|bearer\s+[a-zA-Z0-9_\-\.]{8,}|key=[a-zA-Z0-9_\-]{8,})", "[REDACTED_KEY]", msg, flags=re.I)
    msg = re.sub(r"https?://[^\s/$.?#].[^\s]*", "[endpoint]", msg)
    msg = re.sub(r"[A-Za-z]:\\[\w\s\\.\-]+|/(?:home|usr|var|tmp|app)/[\w\s/.\-]+", "[path]", msg)
    return msg


def fallback_reason(err: BaseException) -> str:
    """Why the written answer is missing, for a reader: never an empty message."""
    name = type(err).__name__
    if "Timeout" in name:
        return "the model provider did not respond in time"
    if "InternalServerError" in name or "500" in str(err):
        return "the model service encountered an internal error (HTTP 500: Failed to generate completions)"
    if "RateLimit" in name or "429" in str(err):
        return "the model rate limit was reached"
    if "AuthenticationError" in name or "401" in str(err):
        return "model authentication failed"
    sanitized = sanitize_error_message(err)
    if sanitized:
        return f"{name}: {sanitized[:120]}"
    return name


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
        need = getattr(ctx, "evidence_need", None)
        if need is not None and need.level == "required":
            # A question that asks for sources while Search is off is answered without them, and says so.
            scope_notes.append(
                "Search was switched off for this turn, so no literature or web source was consulted although the "
                "question asks for sources: say so in one sentence, answer from established knowledge only, and do "
                "not cite or name specific papers, preprints or web pages.")
        else:
            scope_notes.append("Search was switched off for this turn: no literature or web source was consulted.")
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
    from ...verify.formal.prove import wants_proof

    if wants_proof(run.clean_query or run.query):
        # A proof request is worked as a proof attempt (proved / evidence / open), never answered as a bare calculation
        # or a bare status report.
        scope_notes.append(PROOF_ATTEMPT_NOTE)
    elif is_closed_computation(ctx):
        from ..prompts import answer_style

        note = CLOSED_COMPUTATION_ANSWER_NOTE
        if answer_style() == "concise":
            # The checks are shown beside the answer; a Verification section of checker names only repeats them.
            note = note.replace("(3) a short Verification section naming the independent checks that agree.",
                                "(3) no Verification section: the checks are shown beside the answer.")
        scope_notes.append(note)
    run.vivarix_summary, run.lumicell_summary = vivarix_summary, lumicell_summary
    run.lithoscribe_summary, run.synapta_summary = lithoscribe_summary, synapta_summary
    run.scope_notes = scope_notes


_PYTHON_TOOLS = ("calcula_run_python", "analysis_run_python", "calcula", "codeact")


def _python_outputs(tool_results: dict[str, Any] | None, agent_state: Any) -> str:
    """What sandboxed Python printed during the run (the planner's scripts, the CodeAct notebook), for an answer the
    writer could not write: these are computed results, and "no tool produced a result" was false when they ran."""
    results = dict(tool_results or {})
    if agent_state is not None:
        results.update(getattr(agent_state, "results", None) or {})
    blocks: list[str] = []
    for key, res in results.items():
        if res is None or not getattr(res, "success", False):
            continue
        name = str(getattr(res, "tool_name", "") or key)
        if name not in _PYTHON_TOOLS and not any(t in str(key) for t in _PYTHON_TOOLS):
            continue
        data = getattr(res, "data", None) or {}
        printed = ""
        if isinstance(data, dict):
            printed = str(data.get("stdout") or "").strip()
            if not printed and data.get("cells"):
                printed = "\n".join(str(c.get("stdout") or "").strip() for c in data["cells"] if isinstance(c, dict))
        if printed.strip():
            blocks.append("```text\n" + printed.strip()[:3000] + "\n```")
    return "\n\n".join(blocks[:4])


def _math_answer_verified(run: RunContext) -> bool:
    """The mathematics agent's answer to this run is verified (and not since invalidated)."""
    art = run.execution_artifacts.get("math_agent") if isinstance(run.execution_artifacts, dict) else None
    if not isinstance(art, dict) and run.agent_state is not None:
        art = (getattr(run.agent_state, "artifacts", None) or {}).get("math_agent")
    return isinstance(art, dict) and art.get("status") == "verified" and not art.get("invalidated")


def build_prompt(run: RunContext, feedback: list[str] | None = None, previous_draft: str = "") -> str:
    from ...files import requested_files as requested_kinds
    from ...files import writer_note
    from ...writer.outline import outline_text
    from ..prompts import answer_style

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
    gate_report: dict[str, Any] = {}
    evidence_block = ao.build_evidence_block(
        tool_results, discovery_report.to_markdown_summary(), query_context=ctx, extra_sections=extra_sections,
        query=run.clean_query or query or "", gate_report=gate_report,
    )
    if gate_report:
        run.pending["context_gate"] = gate_report
    return ao.build_synthesis_request(
        evidence_block=evidence_block,
        tool_status_block=ao.build_tool_status_block(
            tool_results, scope_notes + (agent_state.scope_notes if agent_state is not None else [])
        ),
        memory_summary=memory_summary,
        query=query,
        question_type=ctx.search_plan.question_type if ctx.search_plan is not None else "general",
        research_brief=brief,
        retrieval_date=retrieval_date(),  # UTC; dates approvals, trial status and FAERS counts
        answer_outline=outline_text(run.answer_outline),
        answer_style=answer_style(),
        requested_files=writer_note(requested_kinds(run.clean_query or query or "")),
    )


def _verified_render(run: RunContext) -> str | None:
    """The answer rendered from the math agent's verified result when it alone is the requested answer."""
    from ...axiom.render import render_verified_answer

    agent_state = run.agent_state
    art = (getattr(agent_state, "artifacts", None) or {}).get("math_agent") if agent_state is not None else None
    if art is None and getattr(run, "tool_results", None):
        for k in ("axiom_solve_problem", "axiom", "axiom_solve"):
            tr = run.tool_results.get(k)
            if tr is not None and tr.success and isinstance(tr.data, dict) and tr.data.get("status") == "verified":
                art = tr.data
                break
    if art is None and getattr(run, "execution_artifacts", None):
        artifacts = run.execution_artifacts
        if (
            "scientific_executions" in artifacts
            or "oscillator_simulation" in artifacts
            or "scientific_execution" in artifacts
        ):
            try:
                from ...scientific.assembly import assemble_eight_part_answer
                return assemble_eight_part_answer(artifacts)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Scientific assembly fallback skipped: %s", exc)
    try:
        return render_verified_answer(run.clean_query or run.query, art, getattr(run, "output_contract", None))
    except Exception as exc:  # noqa: BLE001 - the writer path remains
        logger.debug("Verified rendering skipped: %s", exc)
        return None


async def write_first_draft(run: RunContext) -> None:
    """Stream the first draft from the synthesis model; on a model error, show the raw evidence instead."""
    ao = orchestrator_module()
    orch = run.orch
    agent_state, tool_results, model_name, api_key = run.agent_state, run.tool_results, run.model_name, run.api_key
    emit, send, record, on_reasoning, on_text = run.emit, run.send, run.record, run.on_reasoning, run.on_text
    successful_sources, scope_notes = run.successful_sources, run.scope_notes
    vivarix_summary, lumicell_summary = run.vivarix_summary, run.lumicell_summary
    lithoscribe_summary, synapta_summary = run.lithoscribe_summary, run.synapta_summary

    if agent_state is not None:
        agent_state.bag.setdefault("steering", []).extend(agent_state.control.drain_steering())
    synthesis_prompt = build_prompt(run)
    gate = run.pending.get("context_gate")
    if gate and not gate.get("fallback"):
        withheld = gate.get("quarantined", 0) + gate.get("blocked", 0)
        await emit(
            "context_gate",
            title=f"Context gate: kept {gate.get('admitted', 0)} relevant statements, {gate.get('saved_pct', 0):.0f}% less text",
            text=(f"{gate.get('admitted', 0)} of {gate.get('sentences_in', 0)} sentences admitted (Lumo K >= 1); "
                  f"{withheld} withheld as unverified or contradicted"),
            status="done",
            extra={"context_gate": gate},
        )
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
    closed_calc = is_closed_computation(run.ctx)
    contract = getattr(run, "output_contract", None)
    has_strict = contract is not None and (contract.strict_form or contract.exact_items or contract.exact_lines or contract.exact_words)

    depth = effort_prof.get("deliberation_depth", "standard")
    if closed_calc:
        delib_text = (
            "\n[EFFORT LEVEL: TARGETED / CLOSED COMPUTATION]\n"
            "State the verified mathematical result directly and follow any formatting instructions precisely. "
            "Preserve the stated domains and units, perform required unit conversions, and omit unrequested literature or regimes."
        )
    else:
        delib_text = deliberation_prompts.get(depth, "")
    from ...skills import skills_prompt

    # Matching procedures (tribos/skills), before the effort instruction so that stays the last word on depth.
    system_prompt += skills_prompt(run.clean_query or run.query or "")
    if delib_text:
        system_prompt = f"{system_prompt}\n{delib_text}"
    from ...utils.output_contract import writer_rule

    system_prompt += writer_rule(getattr(run, "output_contract", None))  # last, so it overrides the report template above

    rendered = _verified_render(run)
    if rendered is not None:
        # The verified computation already is the whole requested answer in the requested form: it is the answer,
        # with no writer call (same payload whether or not a writer is healthy; no model time spent copying values).
        await emit("synthesis", title="Answer rendered from the verified computation",
                   text="the checked result is the requested answer in the requested form; no writer model was needed")
        await on_text(rendered)
        record("set_synthesis", system_prompt_sha256=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
               synthesis_prompt_sha256=hashlib.sha256(synthesis_prompt.encode("utf-8")).hexdigest(),
               scope_notes=list(scope_notes), llm_ok=True, fallback_error=None, response_words=len(rendered.split()),
               temperature=None, synthesis_model="verified_computation", synthesis_served_model=None)
        run.synthesis_prompt, run.system_prompt, run.synthesis_model = synthesis_prompt, system_prompt, "verified_computation"
        run.llm_ok, run.candidate_response, run.streamed_draft = True, rendered, rendered
        return

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

    want = compute_draft_output_cap(
        closed_calc=closed_calc,
        has_strict=has_strict,
        exact_items=(getattr(contract, "exact_items", 0) or 0),
    )
    effort_word =effort_prof.get("reasoning_effort")
    if not (closed_calc or has_strict) and (
        effort_word == "high" or (effort_word == "medium" and is_self_contained(getattr(run, "ctx", None)))
    ):
        # A reasoning model's thinking counts against max_tokens: at high effort a hard proof used all 16k thinking
        # and wrote nothing. At medium, a self-contained problem the writer solves itself does too (Q.7, rolling
        # discs: 28.9k reasoning tokens; the provider returned no text, labelled "stop"). Twice the room (still
        # admitted from the run budget) leaves space for the answer; an easy problem stops long before the cap.
        want *= 2
    finish = [""]  # the provider's finish reason of the latest draft call

    def on_finish(reason: str) -> None:
        finish[0] = reason

    try:
        llm_kwargs: dict[str, Any] = {"max_tokens": want}
        min_out = min(512 if closed_calc else 1024, want)
        if budget is not None:
            try:
                alloc = budget.admit(
                    "first_draft", len(system_prompt) + len(synthesis_prompt), want, min_output=min_out
                )
            except BudgetExhausted as exc:
                raise DraftBudgetStop(str(exc)) from exc
            llm_kwargs["max_tokens"] = alloc.output_cap
        reasoning_effort = "low" if (closed_calc or has_strict) else effort_prof.get("reasoning_effort")
        if closed_calc and _math_answer_verified(run):
            # The mathematics agent computed and checked the answer: the writer only presents it (10 s at "low" for a
            # two-line answer). Nothing is left to reason about.
            reasoning_effort = "minimal"
        llm = ao.get_llm(
            model_name=synthesis_model,
            api_key=api_key,
            streaming=True,
            reasoning_effort=reasoning_effort,
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
                from ...utils.llm.provider_retry import already_retried

                if attempt == 2 or type(exc).__name__ not in ao._TRANSIENT_STREAM_ERRORS or already_retried(llm, exc):
                    raise
                logger.warning("First draft failed (%s); retrying once without extended reasoning", type(exc).__name__)
                if streamed_chars[0]:
                    await send({"type": "content_reset", "reason": "retry"})
                    streamed_chars[0] = 0
                await emit("synthesis", title="Model error; writing the answer again", text=type(exc).__name__,
                           status="running")
                # A long silent reasoning pass is what times out (no bytes for minutes), so the retry answers directly.
                llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, streaming=True, reasoning_effort="minimal",
                                 **llm_kwargs)
                await asyncio.sleep(2.0)
        candidate_response = draft_text
        if alloc is not None:
            budget.settle(alloc, output_chars=len(draft_text or "") + len(draft_reasoning or ""))
            alloc = None
        if not (draft_text or "").strip():
            # A reasoning model can spend its whole output allocation thinking and return no answer text. Ask once more
            # with extended reasoning off (the answer text then gets the allocation); an empty draft is never kept.
            logger.warning("First draft returned no text (%d reasoning chars, finish=%r, max_tokens=%s, effort=%s); "
                           "retrying without extended reasoning", len(draft_reasoning or ""), finish[0],
                           llm_kwargs.get("max_tokens"), reasoning_effort)
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
            # One level less reasoning, not none: Q.7 (a rolling-discs problem) returned nothing at "medium" (its
            # thinking outgrew the 16k allocation) but answered in 49 s at "low"; "minimal" guesses at a hard problem.
            retry_effort = "minimal" if str(reasoning_effort or "").lower() in ("low", "minimal") else "low"
            llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, streaming=True, reasoning_effort=retry_effort,
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
                logger.warning("Retry draft returned no text either (finish=%r, max_tokens=%s)", finish[0],
                               retry_kwargs.get("max_tokens"))
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
        if candidate_response and getattr(run, "execution_artifacts", None):
            try:
                from ...scientific.assembly import check_and_repair_truncation
                candidate_response = check_and_repair_truncation(candidate_response, run.execution_artifacts)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Truncation repair skipped: %s", exc)
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
        reason = fallback_reason(err)
        fallback_error = reason
        logger.warning("LLM synthesis error: %s. Generating deterministic evidence fallback.", err)
        if isinstance(err, DraftBudgetStop):
            title = "Agent budget used up before the answer could be written (partial run)"
        elif isinstance(err, EmptyDraftError):
            title = "The model returned no answer text (partial run)"
        elif isinstance(err, RunDeadlineExceeded):
            title = "Run time budget ran out while writing (partial run)"
        else:
            title = "Synthesis failed: model unavailable (partial run)"
        await emit(
            "synthesis",
            title=title,
            text=sanitize_error_message(err)[:180],
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
        math_status = str((math_art or {}).get("status") or "")
        computed = (f"$${math_answer['latex']}$$" if math_answer.get("latex")
                    else str(math_answer.get("text") or "").strip())
        sections = [
            ("Computed result (Axiom)", f"{computed}\n\nStatus: {math_status.replace('_', ' ')}" if computed else ""),
            ("Numerical verification", verification_fallback_markdown(ode_art)),
            ("Computed results (Dynamis, Axiom, Physis, Calcula)", vivarix_summary),
            ("Literature passages (Archivon)", lithoscribe_summary),
            ("Target-disease associations", synapta_summary),
            ("Single-cell analysis", lumicell_summary),
            ("Computed in Python (sandbox)", _python_outputs(tool_results, agent_state)),
        ]
        body = "".join(f"#### {title_}\n{text_}\n\n" for title_, text_ in sections if (text_ or "").strip())
        contract = getattr(run, "output_contract", None)
        rendered_fallback = _verified_render(run)
        if rendered_fallback is not None:
            # The verified result alone is the complete requested answer: the run is complete without a writer.
            # The writer's failure stays recorded (fallback_error); the answer is attributed to the computation.
            candidate_response, llm_ok, synthesis_model = rendered_fallback, True, "verified_computation"
            await on_text(rendered_fallback)
        elif math_status == "verified" and math_answer.get("text") and contract is not None and contract.strict_form:
            # The user fixed the answer's form and the verified computation answers it: its checked text is the
            # answer (the task status reports that no model wrote it), not a report about the failed writer.
            candidate_response = str(math_answer["text"]).strip()
        elif body.strip() or plugin_sections:
            # Computed results exist: clearly label that the run is incomplete and raw results are preserved for diagnostics
            candidate_response = (
                f"> ⚠️ **Run Incomplete (Synthesis Error)**: The final answer could not be generated ({reason}). "
                "The computed results and evidence below are preserved for diagnostics only, not as a completed answer.\n\n"
                f"{body}{''.join(plugin_sections)}"
                "#### Evidence limitations\n"
                f"No written answer: {reason}. Check the results above against the question before "
                "relying on them."
            )
        else:
            # Nothing was computed: say which stages failed; the request is not presented as evidence or results.
            failed = sorted({str(getattr(r, "tool_name", "") or k) for k, r in (tool_results or {}).items()
                             if r is not None and not getattr(r, "success", False)})
            candidate_response = (
                f"> ⚠️ **Run Failed (Synthesis Error)**: No answer could be produced. The writing model failed ({reason})"
                + (f", and these tools returned no result: {', '.join(failed[:8])}" if failed else
                   ", and no tool produced a result for this question")
                + ". No mathematical or evidence result is available from this run; please try again."
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
        synthesis_served_model=getattr(llm, "model_name", None) if llm_ok and fallback_error is None else None,
    )
    run.synthesis_prompt, run.system_prompt, run.synthesis_model = synthesis_prompt, system_prompt, synthesis_model
    run.llm_ok, run.candidate_response, run.streamed_draft = llm_ok, candidate_response, streamed_draft
