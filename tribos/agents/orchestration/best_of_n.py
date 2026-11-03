"""
Best-of-N drafting with the math auditor as the verifier (docs/plans/tribos-research-upgrade-plan.md 2.2).

When the first draft of a mathematical answer has a statement the auditor (tribos.verify.math_claims) finds false, and
no code module already computed the answer, a few alternative drafts are written in parallel from the same prompt and
audited the same way; the draft with the fewest failed and most passed statements is kept. Tool-integrated
verification of candidates outperforms a larger single model under the same compute (T1, arXiv 2504.04718), and
matched-compute studies favour this over critic debate.

It never runs for an answer that code computed (computed_results covers it), for a draft with no failed statement,
or when the run budget cannot admit the extra drafts.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .context import RunContext, logger, orchestrator_module

EXTRA_DRAFTS = {"low": 0, "medium": 2, "high": 2, "ultra": 4, "max": 4}
DRAFT_TIMEOUT_S = 240.0


def _score(audit: Any) -> tuple[int, int]:
    """(failed, -passed): lower is better."""
    claims = getattr(audit, "claims", None) or []
    failed = sum(1 for c in claims if getattr(c, "status", "") == "failed")
    passed = sum(1 for c in claims if getattr(c, "status", "") == "passed")
    return failed, -passed


async def best_of_n(run: RunContext) -> None:
    """Replace a first draft that has failed mathematical statements by the best of a few audited alternatives."""
    draft = run.candidate_response or ""
    if not draft.strip() or not run.llm_ok or not run.synthesis_prompt:
        return
    from ...verify.math_claims import audit_answer
    from .presentation import computations_cover_question

    if computations_cover_question(run.tool_results):
        return
    question = run.clean_query or run.resolved_query or run.query or ""
    try:
        first = await asyncio.to_thread(audit_answer, draft, question, run.tool_results)
    except Exception as exc:  # noqa: BLE001 - selection is an improvement, never a reason to fail the run
        logger.info("best-of-n: audit failed: %s", exc)
        return
    first_score = _score(first)
    if first_score[0] == 0:
        return  # no false statement: nothing to choose between
    effort = str((run.agent_options or {}).get("effort_level") or "medium")
    extra = EXTRA_DRAFTS.get(effort, 2)
    budget = getattr(run.agent_state, "budget", None) if run.agent_state is not None else None
    if extra <= 0 or (budget is not None and budget.max_llm_calls - budget.llm_calls < extra + 2):
        return
    ao = orchestrator_module()
    from langchain_core.messages import HumanMessage, SystemMessage

    # Generator-Verifier-Reviser (Aletheia): a draft with a few false statements is revised in place; only a draft the
    # revision cannot fix, or one with many false statements, is regenerated.
    revised: tuple[tuple[int, int], str] | None = None
    if first_score[0] <= MINOR_FAILURES:
        await run.emit("best_of_n", f"Revising {first_score[0]} false statement(s) in the draft", status="running")
        try:
            text = await revise(run, draft, first)
            audit = await asyncio.to_thread(audit_answer, text, question, run.tool_results) if text else None
            if audit is not None:
                revised = (_score(audit), text)
        except Exception as exc:  # noqa: BLE001
            logger.info("best-of-n: revision failed: %s", exc)
        if revised is not None and revised[0][0] == 0:
            await _keep(run, draft, first_score, [(first_score, draft), revised], revised, mode="revised")
            return

    await run.emit("best_of_n", f"Drafting {extra} alternatives: the first draft has "
                                f"{first_score[0]} false statement(s)", status="running")

    async def candidate() -> str:
        llm = ao.get_llm(model_name=run.synthesis_model, api_key=run.api_key, **ao._edit_llm_kwargs(run.synthesis_model))
        reply = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=run.system_prompt),
                                                    HumanMessage(content=run.synthesis_prompt)]), DRAFT_TIMEOUT_S)
        if budget is not None:
            budget.llm_calls += 1
        return str(getattr(reply, "content", "") or "").strip()

    texts = await asyncio.gather(*(candidate() for _ in range(extra)), return_exceptions=True)
    scored: list[tuple[tuple[int, int], str]] = [(first_score, draft)] + ([revised] if revised else [])
    for text in texts:
        if isinstance(text, str) and text:
            try:
                audit = await asyncio.to_thread(audit_answer, text, question, run.tool_results)
            except Exception:  # noqa: BLE001
                continue
            scored.append((_score(audit), text))
    await _keep(run, draft, first_score, scored, min(scored, key=lambda s: s[0]), mode="best_of_n")


MINOR_FAILURES = 2  # at most this many false statements: revise the draft before drafting alternatives

_REVISE_INSTRUCTION = """An exact checker found these statements in your draft false:
{failures}

Rewrite the complete answer. Correct exactly these statements and anything that depends on them; keep everything else (structure, citations, verified values) unchanged. Do not mention the checker or that the answer was revised."""


async def revise(run: RunContext, draft: str, audit: Any) -> str:
    """The draft with its failed statements corrected by the model (one call)."""
    from .llm_call import ask

    failures = "\n".join(f"- {c.text[:300]}" + (f" (checker: {c.detail[:200]})" if c.detail else "")
                         for c in (getattr(audit, "failed", None) or [])[:8])
    messages = [("user", run.synthesis_prompt), ("assistant", draft),
                ("user", _REVISE_INSTRUCTION.format(failures=failures))]
    return (await ask(run, run.system_prompt, messages, timeout_s=DRAFT_TIMEOUT_S, model=run.synthesis_model)).strip()


async def _keep(run: RunContext, draft: str, first_score: tuple[int, int], scored: list[tuple[tuple[int, int], str]],
                chosen: tuple[tuple[int, int], str], *, mode: str) -> None:
    best_score, best = chosen
    record = {"candidates": len(scored), "mode": mode, "first": {"failed": first_score[0], "passed": -first_score[1]},
              "kept": {"failed": best_score[0], "passed": -best_score[1]}, "replaced": best is not draft}
    run.execution_artifacts["best_of_n"] = record
    if best is draft:
        await run.emit("best_of_n", "Kept the first draft", f"{len(scored)} drafts audited; none had fewer false "
                                                           "statements", status="done")
        return
    run.candidate_response = best
    run.streamed_draft = best
    await run.send({"type": "content_reset", "reason": "best_of_n"})
    await run.send({"type": "content_delta", "delta": best})
    title = "Revised the false statements" if mode == "revised" else "Kept the most accurate of the drafts"
    await run.emit("best_of_n", title,
                   f"{len(scored)} drafts audited; false statements {first_score[0]} -> {best_score[0]}", status="done")


__all__ = ["best_of_n"]
