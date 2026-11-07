"""
Self-consistency for choose-one questions (opt-in: TRIBOS_MC_VOTES, the number of drafts that vote).

The same question answered twice can pick different options (run-to-run variation on GPQA items, 2026-11-07). Majority
voting over independent drafts (Wang et al., "Self-Consistency Improves Chain of Thought Reasoning", ICLR 2023) is a
different mechanism from the independent cross-check, which adjudicated one disagreement and, measured, overturned
right answers (cross_check.py): here no draft is judged, the most frequent option wins, and a tie keeps the first
draft.

Off by default (1 vote): it multiplies the drafting cost by the number of votes. Set 3 or 5 to use it.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any

from .context import RunContext, logger, orchestrator_module

DRAFT_TIMEOUT_S = 240.0
_ANSWER_RE = re.compile(r"(?i)\banswer\s*[:\-]?\s*\**\s*\(?([A-H])\)?(?![A-Za-z])")
_LEAD_RE = re.compile(r"^\s*(?:#+\s*)?\**\s*\(([A-H])\)")


def answer_letter(text: str, letters: str) -> str:
    """The option a draft chooses: its last "Answer: X", else the option it opens with, else ""."""
    found = [m.group(1).upper() for m in _ANSWER_RE.finditer(text or "")]
    found = [x for x in found if x in letters]
    if found:
        return found[-1]
    m = _LEAD_RE.match(text or "")
    return m.group(1).upper() if m and m.group(1).upper() in letters else ""


def votes_setting() -> int:
    from ...config.settings import get_int

    try:
        return max(1, int(get_int("TRIBOS_MC_VOTES")))
    except Exception:  # noqa: BLE001
        return 1


def tally(first: str, others: list[str]) -> tuple[str, Counter[str]]:
    """The winning option: the most frequent; on a tie with the first draft's option, the first draft's."""
    counts = Counter([first] + [x for x in others if x])
    best = max(counts.values())
    winners = [k for k, v in counts.items() if v == best]
    return (first if first in winners else sorted(winners)[0]), counts


async def mc_vote(run: RunContext) -> None:
    """Replace the draft by one choosing the majority option of `TRIBOS_MC_VOTES` independent drafts."""
    k = votes_setting()
    draft = run.candidate_response or ""
    if k <= 1 or not draft.strip() or not run.llm_ok or not run.synthesis_prompt:
        return
    from ..question_text import is_choice_question, option_texts

    question = run.clean_query or run.resolved_query or run.query or ""
    if not is_choice_question(question):
        return
    letters = "".join(chr(ord("A") + i) for i in range(len(option_texts(question))))
    first = answer_letter(draft, letters)
    if not first:
        return
    budget = getattr(run.agent_state, "budget", None) if run.agent_state is not None else None
    if budget is not None and budget.max_llm_calls - budget.llm_calls < k + 1:
        return
    ao = orchestrator_module()
    from langchain_core.messages import HumanMessage, SystemMessage

    await run.emit("mc_vote", f"Drafting {k - 1} more answers to vote on the option", status="running")

    async def candidate() -> str:
        llm = ao.get_llm(model_name=run.synthesis_model, api_key=run.api_key, **ao._edit_llm_kwargs(run.synthesis_model))
        reply = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=run.system_prompt),
                                                    HumanMessage(content=run.synthesis_prompt)]), DRAFT_TIMEOUT_S)
        if budget is not None:
            budget.llm_calls += 1
        return str(getattr(reply, "content", "") or "").strip()

    results = await asyncio.gather(*(candidate() for _ in range(k - 1)), return_exceptions=True)
    texts = [t for t in results if isinstance(t, str) and t]
    for t in results:
        if isinstance(t, BaseException):
            logger.info("mc-vote: a draft failed: %s", t)
    chosen, counts = tally(first, [answer_letter(t, letters) for t in texts])
    record: dict[str, Any] = {"votes": dict(counts), "drafts": 1 + len(texts), "first": first, "chosen": chosen,
                              "replaced": chosen != first}
    run.execution_artifacts["mc_vote"] = record
    if chosen == first:
        await run.emit("mc_vote", f"Kept option {first}", f"votes {dict(counts)}", status="done")
        return
    replacement = next(t for t in texts if answer_letter(t, letters) == chosen)
    run.candidate_response = replacement
    run.streamed_draft = replacement
    await run.send({"type": "content_reset", "reason": "mc_vote"})
    await run.send({"type": "content_delta", "delta": replacement})
    await run.emit("mc_vote", f"Majority chose option {chosen} over the first draft's {first}", f"votes {dict(counts)}",
                   status="done")


__all__ = ["answer_letter", "mc_vote", "tally", "votes_setting"]
