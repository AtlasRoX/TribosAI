"""Stage 5: Reflexion verification and bounded correction, deterministic claim removal, the citation map and the
reported verification result."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...agentic.budget import BudgetExhausted, estimate_tokens  # noqa: F401
from ...agentic.control import RunCancelled
from ...utils.output_contract import writer_rule
from ...verify.verifier import VerificationReport
from .context import RunContext, logger, orchestrator_module


def reconcile_math_artifacts_with_answer(run: RunContext) -> None:
    """Make mathematical tool results and artifacts agree with the final revised text.

    If the revised text explicitly rejects a candidate witness / counterexample, or proves the universal theorem
    instead of accepting the refutation, the tool result and artifact are invalidated and marked as historical
    attempts so they cannot certify the corrected answer.
    """
    import re

    resp = (run.candidate_response or "").lower()
    art = run.execution_artifacts.get("math_agent")
    if not isinstance(art, dict) and run.agent_state is not None:
        art = (getattr(run.agent_state, "artifacts", None) or {}).get("math_agent")
    if not isinstance(art, dict):
        return

    # Check for candidate witness in art
    results = ((art.get("answer") or {}).get("results") or []) + (art.get("results") or [])
    ces: list[str] = [str(r.get("counterexample")) for r in results if isinstance(r, dict) and r.get("counterexample") is not None]
    if art.get("counterexample") is not None:
        ces.append(str(art.get("counterexample")))

    rejected_in_text = False
    rejection_reason = ""
    for ce in ces:
        ce_clean = ce.strip("{}'\" ")
        if ce_clean and (
            ("reject" in resp and ce_clean in resp)
            or ("outside" in resp and ce_clean in resp)
            or ("not in" in resp and ce_clean in resp)
            or ("invalid" in resp and ce_clean in resp)
        ):
            rejected_in_text = True
            rejection_reason = f"Candidate witness {ce} rejected in revised answer as out of domain"
            break

    # Also check if text proves the universal inequality / statement contrary to tool's disproof
    if not rejected_in_text and art.get("status") in ("verified", "partially_verified") and any(r.get("status") == "disproved" for r in results if isinstance(r, dict)):
        if re.search(r"\b(?:for\s+every|for\s+all)\b.*>.*(?:holds|true|established)", resp) or ">= 1 > 0" in resp or ">= 1" in resp:
            rejected_in_text = True
            rejection_reason = "Final answer established the universal claim and rejected candidate refutation"

    if rejected_in_text:
        art["status"] = "rejected"
        art["invalidated"] = True
        art["historical"] = True
        art["invalidation_reason"] = rejection_reason
        art["caveat"] = f"Candidate witness rejected: {rejection_reason}"
        if "confidence" in art:
            art["confidence"] = None
        for c in (art.get("verification") or {}).get("checks") or []:
            if "domain" in c.get("name", ""):
                c["passed"] = False
                c["detail"] = rejection_reason

        # Invalidate in tool_results as well
        for key, res in list(run.tool_results.items()):
            if "math_agent" in key or getattr(res, "tool_name", "") == "axiom_solve_problem":
                res.success = False
                res.error = rejection_reason
                if res.metadata is None:
                    res.metadata = {}
                res.metadata["invalidated"] = True
                res.metadata["historical"] = True
                res.metadata["verification_status"] = "rejected"

        if run.agent_state is not None:
            run.agent_state.artifacts["math_agent"] = art
        run.execution_artifacts["math_agent"] = art


def prefer_primary_reports(text: str, tool_results: dict[str, Any]) -> str:
    """The answer with a named result's retrieved primary paper cited where only a review was cited for its figures."""
    from ...verify import verifier as verifier_mod

    try:
        out, changes = verifier_mod.prefer_primary_reports(text, tool_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Primary-report citation step failed: %s", exc)
        return text
    for c in changes:
        subject = c.get("subject") or c.get("trial")
        logger.info("Cited %s's primary report %s next to review %s", subject, c["primary"], c["review"])
    return out


def computed_confidence_band(run: RunContext) -> str | None:
    """The band of the computed answer confidence (agentic confidence phase), or None when it did not run."""
    art = run.execution_artifacts.get("claim_confidence")
    if not isinstance(art, dict) and run.agent_state is not None:
        art = (getattr(run.agent_state, "artifacts", None) or {}).get("claim_confidence")
    ac = art.get("answer_confidence") if isinstance(art, dict) else None
    if not isinstance(ac, (int, float)):
        return None
    from ...agentic.confidence import band

    return band(float(ac))


async def reconcile_confidence(run: RunContext) -> None:
    """Make the answer's stated confidence level agree with the computed answer confidence; the corrected text
    replaces the streamed one. Without a computed confidence (classic pipeline) the answer is left as written."""
    from ...verify import verifier as verifier_mod

    computed = computed_confidence_band(run)
    if computed is None or not run.candidate_response:
        return
    contract = getattr(run, "output_contract", None)
    if contract is not None and contract.strict_form:
        return  # the user fixed the answer's form: no confidence line is added to or rewritten in it
    art = run.execution_artifacts.get("claim_confidence")
    if not isinstance(art, dict) and run.agent_state is not None:
        art = (getattr(run.agent_state, "artifacts", None) or {}).get("claim_confidence")
    verified = isinstance(art, dict) and art.get("method") == "computational_verification"
    note = "(verified by independent computation)" if verified else verifier_mod.COMPUTED_CONFIDENCE_NOTE
    reconciled = verifier_mod.reconcile_confidence_line(run.candidate_response, computed, note)
    if reconciled == run.candidate_response:
        return
    run.candidate_response = reconciled
    await run.send({"type": "content_reset", "reason": "cleanup"})
    await run.send({"type": "content_delta", "delta": reconciled})
    build_citations(run)  # the citation map covers the answer as shown


def defect_lines(report: VerificationReport) -> str:
    from ...verify import verifier as verifier_mod

    # Human labels ("Contradicted by a source: ...") in step text; categories stay in the structured defects.
    return "; ".join(verifier_mod.defect_display(d, 160) for d in report.defects[:4])


async def check_and_correct(run: RunContext) -> None:
    """Check the draft against the evidence; revise it once if it fails, then remove what is still contradicted."""
    ao = orchestrator_module()
    orch = run.orch
    agent_state, ctx, query, api_key = run.agent_state, run.ctx, run.query, run.api_key
    tool_results, successful_sources, historical_identifiers = run.tool_results, run.successful_sources, run.historical_identifiers
    emit, send, record, on_reasoning, before_verification = run.emit, run.send, run.record, run.on_reasoning, run.before_verification
    reasoning_parts, synthesis_model, system_prompt, synthesis_prompt = (
        run.reasoning_parts, run.synthesis_model, run.system_prompt, run.synthesis_prompt
    )
    candidate_response, streamed_draft = run.candidate_response, run.streamed_draft
    entailment_judge = agent_state.bag.get("entailment_judge") if agent_state is not None else None

    # Display labels, claim tally, entity decoding.
    from ...verify import verifier as verifier_mod

    # HTML entities from abstracts ("&lt;0.001") are decoded before the answer is checked and shown.
    # The sanitized text replaces the streamed draft too, so the client, the verifier and the claims see one text.
    unescaped_draft = prefer_primary_reports(verifier_mod.unescape_entities(candidate_response), tool_results)
    if unescaped_draft != candidate_response or candidate_response.strip() != streamed_draft.strip():
        candidate_response = unescaped_draft
        await send({"type": "content_reset", "reason": "cleanup"})
        await send({"type": "content_delta", "delta": candidate_response})

    run.candidate_response = candidate_response
    reconcile_math_artifacts_with_answer(run)
    await before_verification(candidate_response)

    # -------------------------------------------------------------
    # STAGE 5: REFLEXION VERIFICATION & BOUNDED CORRECTION
    # -------------------------------------------------------------
    await emit("verification", title="Checking claims against the evidence", status="running", agent="Verifier")

    context_identifiers: dict[str, set[str]] = {}

    def merge_ids(ids: Any) -> None:
        for fam, values in (ids or {}).items():
            context_identifiers.setdefault(str(fam), set()).update(str(v) for v in (values or []) if v)

    try:
        merge_ids(ctx.observed_identifiers())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query context identifiers failed: %s", exc)
    for src in successful_sources:
        try:
            merge_ids(src.allowed_identifiers(tool_results[src.key]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s allowed identifiers failed: %s", src.key, exc)

    verification_report = orch.verifier.verify_response(
        query=query,
        response_markdown=candidate_response,
        tool_results=tool_results,
        historical_identifiers=dict(historical_identifiers),  # type: ignore[arg-type]  # set[str] ⊂ Iterable[str]
        context_identifiers=dict(context_identifiers),  # type: ignore[arg-type]
        query_context=ctx,
        entailment_judge=entailment_judge,
    )
    first_pass = {
        "passed": verification_report.passed,
        "score": verification_report.verification_score,
        "n_defects": len(verification_report.defects),
    }
    correction_attempted = False
    correction_error: str | None = None

    # Bounded Correction Loop (Max 1 retry if critical/major defect)
    if not verification_report.passed:
        await emit(
            "verification",
            title=(
                f"Found {len(verification_report.defects)} problem(s) to fix "
                f"(score {verification_report.verification_score:.2f})"
            ),
            text=defect_lines(verification_report),
            status="error",
            agent="Verifier",
            extra={"defects": [d.model_dump() for d in verification_report.defects]},
        )
        feedback_prompt = verification_report.to_feedback_prompt()
        correction_messages = [
            SystemMessage(content=f"{system_prompt}\n\n{ao.CORRECTION_SYSTEM_PROMPT}{writer_rule(getattr(run, 'output_contract', None))}"),
            HumanMessage(content=ao.build_correction_request(synthesis_prompt, candidate_response, feedback_prompt)),
        ]
        # Agentic runs charge the revision to the run budget (it may use the finalization reserve). When even that
        # cannot fit it, the revision is skipped: the deterministic removal below still runs, with no model call.
        # The revision is admitted with an exact output allocation that is sent to the model; one that could only be
        # cut off (less output than the draft it rewrites) is not started (audit F3).
        revision_alloc: Any = None
        skip_reason = ""
        if agent_state is not None:
            from .agent_rounds import generation_allocation

            prompt_chars = sum(len(str(m.content)) for m in correction_messages)
            revision_alloc, skip_reason = generation_allocation(
                agent_state.budget, "revision", prompt_chars, len(candidate_response)
            )
        if skip_reason:
            await emit(
                "revision",
                title="Skipped the revision: the agent budget is used up",
                text=f"{skip_reason[:200]}. Contradicted statements are still removed and the rest is reported as checked.",
                status="error",
            )
        else:
            await emit("revision", title="Revising the answer to fix them", status="running")
            correction_attempted = True
        if not skip_reason:
            budget = agent_state.budget if agent_state is not None else None
            holder: dict[str, Any] = {"alloc": revision_alloc}
            revised_parts: list[str] = []
            try:
                llm_kwargs = dict(ao._edit_llm_kwargs(synthesis_model))
                if revision_alloc is not None:
                    llm_kwargs["max_tokens"] = revision_alloc.output_cap
                llm = ao.get_llm(model_name=synthesis_model, api_key=api_key, **llm_kwargs)
                if reasoning_parts:
                    await on_reasoning("\n\n---\n\n")

                def before_retry(_attempt: int) -> None:
                    if budget is None or holder["alloc"] is None:
                        return  # classic runs are not ledgered
                    budget.settle(holder["alloc"], output_chars=len("".join(revised_parts)), failed=True)
                    from .agent_rounds import generation_allocation

                    retry, why = generation_allocation(budget, "revision", prompt_chars, len(candidate_response))
                    if retry is None or retry.output_cap < revision_alloc.output_cap:
                        if retry is not None:
                            budget.settle(retry, failed=True)
                        raise BudgetExhausted(why or "no budget left to retry the revision")
                    holder["alloc"] = retry

                # The revision is buffered: the client keeps the first draft until the revision is known to be better.
                corrected_text, corrected_reasoning = await run.watched(
                    "revision",
                    ao.stream_buffered_with_retry(
                        llm, correction_messages, revised_parts, on_reasoning=on_reasoning, before_retry=before_retry,
                        timeout_s=budget.remaining_seconds() if budget is not None and budget.time_limited else None,
                    ),
                )
                if holder["alloc"] is not None and budget is not None:
                    budget.settle(
                        holder["alloc"],
                        output_chars=len(corrected_text or "".join(revised_parts)) + len(corrected_reasoning or ""),
                    )
                # The correction request escapes the draft, so the model may echo entities ("&lt;0.001"): decode them.
                revised = prefer_primary_reports(
                    verifier_mod.unescape_entities(orch._sanitize_answer(corrected_text or "".join(revised_parts))), tool_results
                )
                await before_verification(revised)
                revised_report = orch.verifier.verify_response(
                    query=query,
                    response_markdown=revised,
                    tool_results=tool_results,
                    historical_identifiers=dict(historical_identifiers),  # type: ignore[arg-type]
                    context_identifiers=dict(context_identifiers),  # type: ignore[arg-type]
                    query_context=ctx,
                    entailment_judge=entailment_judge,
                )
                # An empty draft has nothing to flag and so can outscore any real answer; it never wins over one.
                draft_empty = len((candidate_response or "").split()) < 20
                revised_text = revised.strip()
                original_text = (candidate_response or "").strip()
                text_changed = revised_text != original_text
                score_improved = revised_report.verification_score > verification_report.verification_score
                fewer_defects = len(revised_report.defects) < len(verification_report.defects)
                provenance_improved = score_improved or fewer_defects

                if revised_text and (
                    draft_empty
                    or revised_report.passed
                    or revised_report.verification_score >= verification_report.verification_score
                ):
                    if not text_changed and not provenance_improved:
                        # Zero textual change and no provenance improvement: terminate unproductive repair loop
                        await emit(
                            "revision",
                            title="Revision produced no change; keeping the first draft",
                            text="No textual or verification improvement was produced in the revision round.",
                            status="done",
                        )
                    else:
                        candidate_response, verification_report = revised, revised_report
                        run.candidate_response = candidate_response
                        reconcile_math_artifacts_with_answer(run)
                        await send({"type": "content_reset", "reason": "revision"})
                        await send({"type": "content_delta", "delta": candidate_response})
                        if not text_changed and provenance_improved:
                            await emit(
                                "revision",
                                title="Revised claim provenance",
                                text="Zero textual change; claim provenance and verification grounding improved.",
                                status="done",
                            )
                        else:
                            await emit("revision", title="Revised the answer", status="done")
                else:
                    await emit(
                        "revision",
                        title="Revision was not better; keeping the first draft",
                        text=f"revised score {revised_report.verification_score:.2f} vs draft {verification_report.verification_score:.2f}",
                        status="error",
                    )
            except BaseException as corr_err:
                if holder["alloc"] is not None and budget is not None:
                    # Failed, cancelled or deadline: the prompt stays charged, the unused allocation is released.
                    budget.settle(holder["alloc"], output_chars=len("".join(revised_parts)), failed=True)
                if isinstance(corr_err, RunCancelled) or not isinstance(corr_err, Exception):
                    raise
                correction_error = f"{type(corr_err).__name__}: {str(corr_err)[:240]}"
                logger.warning("Correction attempt failed: %s", corr_err)
                await emit(
                    "revision",
                    title="Revision failed; keeping the first draft",
                    text=f"{type(corr_err).__name__}: {str(corr_err)[:240]}",
                    status="error",
                )

    # A contradicted claim or a figure from another population must not survive correction: remove its sentence
    # deterministically, note the removal under "Evidence limitations", and check the result again.
    flagged = verifier_mod.removable_defects(verification_report)
    if flagged:
        pruned, removed = verifier_mod.remove_flagged_sentences(
            candidate_response, flagged, contract=getattr(run, "output_contract", None)
        )
        if removed and pruned.strip():
            try:
                await before_verification(pruned)
                pruned_report = orch.verifier.verify_response(
                    query=query,
                    response_markdown=pruned,
                    tool_results=tool_results,
                    historical_identifiers=dict(historical_identifiers),  # type: ignore[arg-type]
                    context_identifiers=dict(context_identifiers),  # type: ignore[arg-type]
                    query_context=ctx,
                    entailment_judge=entailment_judge,
                )
            except Exception as prune_err:  # noqa: BLE001
                logger.warning("Re-check after removing flagged claims failed: %s", prune_err)
            else:
                candidate_response, verification_report = pruned, pruned_report
                run.candidate_response = candidate_response
                reconcile_math_artifacts_with_answer(run)
                await send({"type": "content_reset", "reason": "cleanup"})
                await send({"type": "content_delta", "delta": candidate_response})
                await emit(
                    "claim_removal",
                    title=f"Removed {len(removed)} statement(s) the evidence does not back",
                    text="; ".join(verifier_mod.defect_display(d, 140) for d in removed[:4]),
                    agent="Verifier",
                    extra={"removed": [d.model_dump() for d in removed]},
                )
    record(
        "set_verification",
        first_pass=first_pass,
        final={
            "passed": verification_report.passed,
            "score": verification_report.verification_score,
            "n_defects": len(verification_report.defects),
        },
        correction_attempted=correction_attempted,
        correction_error=correction_error,
    )
    run.entailment_judge, run.context_identifiers = entailment_judge, context_identifiers
    run.verification_report, run.candidate_response = verification_report, candidate_response


def build_citations(run: RunContext) -> None:
    """Citation map over the answer as shown (before the verification banner is prepended)."""
    ao = orchestrator_module()
    ctx, tool_results, successful_sources, historical_identifiers = (
        run.ctx, run.tool_results, run.successful_sources, run.historical_identifiers
    )
    candidate_response, verification_report = run.candidate_response, run.verification_report

    source_citations: dict[str, list[Any]] = {}
    for src in successful_sources:
        try:
            source_citations[src.key] = list(src.citations(tool_results[src.key]) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s citations failed: %s", src.key, exc)
    try:
        citation_map = ao.build_citation_map(
            candidate_response,
            tool_results,
            verification_report,
            dict(historical_identifiers),  # type: ignore[arg-type]
            ctx,
            source_citations,
        ) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Citation map failed: %s", exc)
        citation_map = {}
    run.citation_map = citation_map


async def report_result(run: RunContext) -> None:
    """Report the final verification result; an answer that did not pass gets the verification notice on top."""
    from ...verify import verifier as verifier_mod

    await reconcile_confidence(run)
    thought_index, emit = run.thought_index, run.emit
    verification_report, candidate_response = run.verification_report, run.candidate_response

    # A first-pass result updates the "verification" step; a re-check after revision gets its own step.
    result_step = (
        "verification_result" if ("revision" in thought_index or "claim_removal" in thought_index) else "verification"
    )
    coverage = dict(getattr(verification_report, "coverage", None) or {})
    if verification_report.passed and coverage.get("evaluated", 0) == 0:
        # Nothing in the answer could be checked: say so; a defect-free score over zero claims is not a result.
        await emit(
            result_step,
            title="No claims could be checked",
            text=(
                f"{coverage.get('extracted', 0)} statement(s) found, none decidable by the checks; cited identifiers "
                "match the tool outputs."
                if coverage.get("extracted")
                else "The answer has no claims the checks can evaluate; cited identifiers match the tool outputs."
            ),
            agent="Verifier",
            extra={"passed": True, "fully_verified": False, "status": "not_evaluated", "coverage": coverage},
        )
    elif verification_report.passed:
        # Say what was actually checked; "Verified" only when every material claim was checked and supported.
        fully = bool(verification_report.fully_verified and verification_report.claims)
        await emit(
            result_step,
            title=(
                f"{'Verified' if fully else 'Checked'}: {coverage.get('passed', 0)} of "
                f"{coverage.get('extracted', len(verification_report.claims))} claim(s) checked and supported"
            ),
            text=verifier_mod.claim_tally(verification_report),
            agent="Verifier",
            extra={
                "verification_score": verification_report.verification_score,
                "passed": True,
                "fully_verified": fully,
                "status": verification_report.status,
                "coverage": coverage,
            },
        )
    else:
        failed_n = coverage.get("failed", 0)
        await emit(
            result_step,
            title=(
                f"{failed_n} claim(s) contradicted by the checks" if failed_n
                else f"{len(verification_report.defects)} problem(s) remain"
            ) + (f" · {coverage.get('passed', 0)} of {coverage.get('extracted', 0)} supported" if coverage.get("extracted") else ""),
            text=defect_lines(verification_report),
            status="error",
            agent="Verifier",
            extra={"verification_score": verification_report.verification_score, "passed": False,
                   "status": verification_report.status, "coverage": coverage},
        )
        # Explicitly mark synthesis as unverified with honest scientific warning banner. When the user fixed the
        # answer's form (exact text, line count, JSON, short word limit) the notice stays in the verification report
        # and the UI's notice; it is never written into the answer itself.
        math_failed = [d for d in verification_report.defects if d.category == "MATH_CONSISTENCY"]
        contract = getattr(run, "output_contract", None)
        if contract is not None and contract.strict_form:
            run.candidate_response = candidate_response
            return
        if math_failed:
            warning_header = (
                f"> ⚠️ **Verification found errors**: {len(math_failed)} mathematical statement(s) in this answer do not "
                "hold when re-evaluated with the question's values and the computed results. Treat the flagged values "
                "as wrong; the computed results in the cards below are the checked ones.\n"
                f"> {'; '.join(verifier_mod.defect_display(d, 220) for d in math_failed[:3])}\n\n"
            )
        else:
            warning_header = (
                f"> ⚠️ **Scientific Verification Notice**: This synthesized assessment contains claims that could not be fully verified against empirical tool artifacts (Verification Score: {verification_report.verification_score:.2f} / 1.00).\n"
                f"> **Unverified Findings**: {'; '.join(verifier_mod.defect_display(d, 200) for d in verification_report.defects[:3])}\n\n"
            )
        candidate_response = warning_header + candidate_response
    run.candidate_response = candidate_response
