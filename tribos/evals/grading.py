"""
Model-based grading, used only where a rule cannot decide:
- extract_label: which option (yes/no/maybe, or a multiple-choice option) a free-text answer commits to. The
  deterministic heuristics in scoring.py run first; the model is asked only when they cannot tell.
- judge: a rubric score (1-5) of an answer against the question and, when the case has one, a reference answer.

Both return None when no model is available, so a run never fails because grading could not be done.
The judge sees only the question, the reference and the answer, never the expected labels of other checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

LLMFactory = Callable[..., Any]

_EXTRACT_SYSTEM = (
    "You grade a research assistant's answer to a question with fixed options. Decide which single option the answer "
    "commits to. If it does not commit to any option, or says the evidence is insufficient, choose the "
    'insufficient option if one is listed, otherwise "none". Reply with JSON only: {"choice": "<option text exactly>"}'
)

_FINAL_SYSTEM = (
    "You read an answer to a question and report the single final answer it commits to: the value, expression or "
    "option it gives as its answer to the question, exactly as written (LaTeX allowed), without units. Not an "
    "intermediate value, not a restatement of given data. If the answer gives no final answer, reply with null. "
    'Reply with JSON only: {"final": "<final answer>"} or {"final": null}'
)

JUDGE_DIMENSIONS = ("correctness", "grounding", "completeness", "calibration", "clarity")
_JUDGE_SYSTEM = (
    "You are a senior physicist, mathematician, and research engineer grading an AI scientific assistant's answer. "
    "Score each dimension from 1 (poor) to 5 (excellent):\n"
    "- correctness: agreement with established physical laws, mathematical theorems, engineering formulas, and the reference answer when one is given\n"
    "- grounding: specific claims, equations, and numerical values are tied to cited sources or derived from first principles; no invented papers, numbers, or identifiers\n"
    "- completeness: covers what an expert in mathematics, physics, or engineering would consider essential for this question\n"
    "- calibration: certainty matches the mathematical proof or empirical evidence; approximations, boundary conditions, and limitations are stated without over-hedging\n"
    "- clarity: direct, well organised, dimensionally consistent, and appropriately concise\n"
    "Every identifier in <verified_sources> was checked against the retrieved literature and exists, even if it is "
    "newer than your knowledge; never call it fabricated. Judge grounding by whether claims are tied to those "
    "sources and accurately reflect them, and treat an identifier cited in the answer but absent from "
    "<verified_sources> as unsupported.\n"
    "Judge the answer as written; do not reward length. Reply with JSON only: "
    '{"correctness": n, "grounding": n, "completeness": n, "calibration": n, "clarity": n, "overall": n, '
    '"rationale": "<two sentences>"}'
)


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    return text[text.lower().rfind("</think>") + 8:] if "</think>" in text.lower() else text


def _first_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


async def _ask(llm_factory: LLMFactory | None, model_name: str | None, system: str, user: str, timeout_s: float) -> dict[str, Any] | None:
    if llm_factory is None:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        # The client's own request timeout (LLM_TIMEOUT, 60 s by default) would cut a slow judge off first.
        llm = llm_factory(model_name=model_name, streaming=False, timeout=timeout_s)
        reply = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]), timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        logger.info("Grader model unavailable: %s", exc)
        return None
    content = getattr(reply, "content", reply)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return _first_json(_strip_think(str(content)))


async def extract_final_answer(
    question: str, answer: str, *, llm_factory: LLMFactory | None, model_name: str | None = None, timeout_s: float = 60.0,
) -> str | None:
    """The final answer a response commits to, as written; None when it gives none or the grader is unavailable.

    Used identically for every system under test whose response has no \\boxed{} answer, so a prose answer ("They
    eat 2 x 4 x 30 = 240 apples") is graded on its stated result, neither on the last number written nor on any
    number that happens to match somewhere in the working.
    """
    obj = await _ask(llm_factory, model_name, _FINAL_SYSTEM,
                     f"<question>{question[:4000]}</question>\n<answer>\n{answer[:8000]}\n</answer>", timeout_s)
    final = (obj or {}).get("final")
    text = str(final).strip() if final is not None else ""
    return text[:400] or None


async def extract_label(
    question: str, answer: str, options: Sequence[str], *, llm_factory: LLMFactory | None, model_name: str | None = None,
    timeout_s: float = 60.0,
) -> str | None:
    """The option the answer commits to, matched back to the option list; None when undecidable."""
    # Lettered, in the order the question showed them, so an answer that names a letter ("Answer: B") can be read.
    listed = "\n".join(f"({chr(65 + k)}) {o}" for k, o in enumerate(options))
    obj = await _ask(llm_factory, model_name, _EXTRACT_SYSTEM,
                     f"<question>{question}</question>\n<options>\n{listed}\n</options>\n<answer>\n{answer[:6000]}\n</answer>", timeout_s)
    choice = str((obj or {}).get("choice") or "").strip().lower()
    if not choice or choice == "none":
        return None
    letter = re.fullmatch(r"\(?([a-z])\)?[.:]?(?:\s.*)?", choice)
    if letter and len(options) <= 26 and ord(letter.group(1)) - 97 < len(options) and (len(choice) <= 3 or choice[1] == ")"):
        return options[ord(letter.group(1)) - 97]
    for o in options:
        if choice == o.lower() or choice.strip(" .\"'") == o.lower():
            return o
    for o in options:  # tolerate a model that shortens or decorates the option
        if o.lower() in choice or choice in o.lower():
            return o
    return None


async def judge(
    question: str, answer: str, reference: str | None, *, llm_factory: LLMFactory | None, model_name: str | None = None,
    sources: Sequence[str] = (), timeout_s: float = 180.0,
) -> dict[str, Any] | None:
    """Rubric scores {dimension: 1-5, overall, rationale}, or None when no model answered with valid scores.
    sources: the answer's verified citations ("PMID:123 | title | journal year"), so recent papers are not
    mistaken for fabrications."""
    ref = f"<reference_answer>\n{reference}\n</reference_answer>\n" if reference else ""
    listed = "\n".join(f"- {s}" for s in list(sources)[:40]) or "(none)"
    obj = await _ask(llm_factory, model_name, _JUDGE_SYSTEM,
                     f"<question>{question}</question>\n{ref}<verified_sources>\n{listed}\n</verified_sources>\n"
                     f"<answer>\n{answer[:8000]}\n</answer>", timeout_s)
    if not obj:
        return None
    scores: dict[str, Any] = {}
    for dim in (*JUDGE_DIMENSIONS, "overall"):
        try:
            value = float(obj.get(dim))
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 5:
            scores[dim] = value
    if "overall" not in scores and all(d in scores for d in JUDGE_DIMENSIONS):
        scores["overall"] = round(sum(scores[d] for d in JUDGE_DIMENSIONS) / len(JUDGE_DIMENSIONS), 2)
    if "overall" not in scores:
        return None
    scores["rationale"] = str(obj.get("rationale") or "")[:600]
    return scores


__all__ = ["JUDGE_DIMENSIONS", "extract_label", "judge"]
