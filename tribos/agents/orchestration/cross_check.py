"""
Independent cross-check of a problem's answer (answer-level self-consistency with adjudication).

The auditor behind best-of-N catches false statements. It cannot catch a draft whose every statement holds for the
wrong model of the problem: "each ball stays in the air for 4 x 0.9 s" is followed by correct arithmetic. For a problem
that carries its own data (a self-contained calculation, a multiple-choice or yes/no question) and that no code module
computed, a second solution is worked from the question alone, without the draft. When its final answer agrees with the
draft's, nothing changes. When it disagrees, one adjudication call re-derives the disputed step against both solutions
and decides; a draft whose result loses is rewritten with the adjudicated result.

Agreement between independently sampled solutions is the strongest cheap signal of a single answer's correctness
(self-consistency, Wang et al., ICLR 2023), and comparing against an independent solution avoids the self-confirmation
of asking a model to critique its own reasoning (Huang et al., ICLR 2024). Cost: one short model call per checked
problem, two more only on disagreement.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .context import RunContext, logger

SOLVE_TIMEOUT_S = 180.0
_SOLVER_SYSTEM = (
    "You are a meticulous expert in mathematics, physics, chemistry, engineering, computer science and finance. You "
    "solve exam problems exactly as their author intends, using the standard conventions of the field.")
_SOLVE_PROMPT = """Solve this problem independently.

{question}
{conventions}
Before computing, state in one line what each given quantity means physically or mathematically, and model the situation from that (for example, which time interval a duration covers, what is counted, which sign convention applies). Answer the question its author intends: a true/false statement of a textbook property is judged in that property's standard sense, not refuted by a technicality of domains or notation. Keep the working short and exact.

End with exactly one line:
FINAL: <only the final answer: a number with its unit, an expression, a list, yes or no, or the option letter>"""

_ADJUDICATE_PROMPT = """Two solutions of the problem below reach different final answers.

PROBLEM:
{question}
{conventions}
SOLUTION A:
{a}

SOLUTION B:
{b}

Find the step where they diverge. Re-derive that step yourself from the problem statement (what each quantity means, the model of the situation, the field's conventions, the arithmetic) and decide which final answer is correct; it may be neither.

Solution A stands unless you identify a concrete error in it: an arithmetic or algebra mistake, a misread or misused given quantity, a wrong model of the situation, or a broken convention of the field. A different interpretation is not an error: the reading the exercise's author intends wins, and a textbook property stated as true/false is judged in its standard sense, not refuted by a technicality of domains or notation. Name the error in A in one sentence before choosing B or NEITHER.

End with exactly two lines:
WINNER: A, B or NEITHER
FINAL: <only the correct final answer>"""

_REWRITE_INSTRUCTION = """An independent re-derivation found that the correct final answer is {final}, not the result of your draft. The reason:
{reason}

Rewrite the complete answer with the corrected reasoning and the result {final}, in the same structure and format, opening with the result. Do not mention a re-derivation, a second solution or that the answer was revised."""

_FINAL_RE = re.compile(r"^\s*\**FINAL\**\s*:\s*(.+?)\s*$", re.I | re.M)
_WINNER_RE = re.compile(r"^\s*\**WINNER\**\s*:\s*\**\s*(A|B|NEITHER)\b", re.I | re.M)
_SCI_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:\\times|×|x|\*)\s*10\s*\^\s*\{?\s*(-?\d+)\s*\}?")
_NUM_RE = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_OPTION_RE = re.compile(r"^\s*\(?([A-Ja-j])\)?(?:[.)]|\s|$)")
_DRAFT_OPTION_RES = (
    # "Answer: C", "the answer is (b)": the letter is a capital, or a lower-case one in parentheses, never the article
    # in "the answer is a function".
    re.compile(r"\b(?i:answer)\s*(?:(?i:is))?\s*[:\-]?\s*\**(?:\(([a-jA-J])\)|([A-J]))\**(?![A-Za-z])"),
    re.compile(r"^\W*\(([a-jA-J])\)()"),
    re.compile(r"\b(?i:option)\s+(?:\(([a-jA-J])\)|([A-J]))(?![A-Za-z])"),
)
_YES = {"yes", "true", "correct"}
_NO = {"no", "false", "incorrect"}
REL_TOL = 0.005  # agreement within half a percent: rounding to three figures, never sqrt(50) against sqrt(51)
_HEAD_CHARS = 900


def _clean(text: str) -> str:
    return (text or "").replace("{,}", "").replace("\\,", "").replace("−", "-").replace("$", " ")


def _numbers(text: str) -> list[float]:
    """Every number in the text, "2.55 \\times 10^{3}" read as 2550."""
    t = _clean(text)
    out: list[float] = []
    for m in _SCI_RE.finditer(t):
        try:
            out.append(float(m.group(1)) * 10 ** int(m.group(2)))
        except (ValueError, OverflowError):
            continue
    t = _SCI_RE.sub(" ", t)
    for m in _NUM_RE.finditer(t.replace(",", "")):
        try:
            out.append(float(m.group(0).replace("−", "-")))
        except ValueError:
            continue
    return [v for v in out if math.isfinite(v)]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-9)


def final_answer(text: str) -> str:
    matches = _FINAL_RE.findall(text or "")
    return matches[-1].strip().strip("*").strip() if matches else ""


def _final_value(final: str) -> float | None:
    """The value of a final answer that is one number or a closed-form number ("13.2 m/s", "71/12", "$2.92", a
    LaTeX fraction or root), units dropped; None for anything else (a list, a formula with variables, words)."""
    from ...verify.latex_math import parse_latex

    t = _clean(final).replace("%", " ").strip()
    t = re.sub(r"^\\boxed\{(.*)\}$", r"\1", t).strip()
    t = re.sub(r"^(?:[A-Za-z_][\w']*(?:\([^)]*\))?\s*=\s*|≈\s*|~\s*|approx(?:imately)?\s+)", "", t).strip()
    tokens = t.split()
    for end in range(len(tokens), 0, -1):
        chunk = " ".join(tokens[:end])
        try:
            expr = parse_latex(chunk)
        except Exception:  # noqa: BLE001 - not an expression: try a shorter prefix
            continue
        if getattr(expr, "is_number", False):
            try:
                value = float(expr.evalf())
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None
    return None


def _number_list(text: str) -> list[float] | None:
    m = re.match(r"^\s*[\[(]\s*([-−\d.,\s]+?)\s*[\])]\s*$", _clean(text))
    if not m:
        return None
    items = [x for x in re.split(r"\s*,\s*", m.group(1)) if x]
    try:
        values = [float(x.replace("−", "-")) for x in items]
    except ValueError:
        return None
    return values if len(values) >= 2 else None


def _draft_values(head: str) -> list[float]:
    """The numbers in the draft's opening, with fractions written as a/b or as a LaTeX fraction also read as values,
    and each inline formula ("$\\sqrt{51}$", "$2\\sqrt2\\sin(\\pi/4)$") and each side of its equations evaluated."""
    from ...verify.latex_math import parse_latex

    values = _numbers(head)
    for m in re.finditer(r"\$\$?([^$]{1,200})\$\$?", head or ""):
        for side in re.split(r"=|\\approx|≈", m.group(1)):
            side = re.sub(r"\\(?:[,;:!]|quad|qquad)", " ", side).strip()
            if not side or not re.search(r"\\|\^|/|\(", side):
                continue  # plain numbers are read above
            try:
                expr = parse_latex(side)
                if getattr(expr, "is_number", False):
                    v = float(expr.evalf())
                    if math.isfinite(v):
                        values.append(v)
            except Exception:  # noqa: BLE001 - a formula that does not evaluate is simply not a value
                continue
    t = _clean(head)
    for m in re.finditer(r"(-?)\\[dt]?frac\{(\d+)\}\{(\d+)\}|(-?\d+)\s*/\s*(\d+)(?![\d.])", t):
        try:
            if m.group(2):
                v = float(m.group(2)) / float(m.group(3)) * (-1 if m.group(1) else 1)
            else:
                v = float(m.group(4)) / float(m.group(5))
            values.append(v)
        except (ValueError, ZeroDivisionError):
            continue
    return values


def _kind(final: str, multiple_choice: bool) -> str:
    word = re.sub(r"[^a-z]", "", final.lower())
    if word in _YES or word in _NO:
        return "yes_no"
    if multiple_choice and _OPTION_RE.match(final) and len(re.sub(r"[\W_]", "", final)) <= 2:
        return "option"
    if _number_list(final) is not None:
        return "list"
    if _final_value(final) is not None:
        return "number"
    return "other"


def _draft_option(draft: str) -> str:
    """The option the draft commits to: its last "Answer: X", else the option it opens with, else "option X"."""
    for i, rx in enumerate(_DRAFT_OPTION_RES):
        found = ["".join(g) for g in rx.findall(draft or "")]
        if found:
            return (found[-1] if i == 0 else found[0]).upper()
    return ""


def _draft_yes_no(draft: str) -> str:
    words = re.findall(r"[A-Za-z]+", (draft or "")[:200].lower())
    for w in words[:12]:
        if w in _YES:
            return "yes"
        if w in _NO:
            return "no"
    return ""


def agrees(final: str, draft: str, *, multiple_choice: bool) -> bool | None:
    """Whether the draft states the final answer: True, False, or None when the two cannot be compared."""
    kind = _kind(final, multiple_choice)
    if kind == "option":
        mine = _draft_option(draft)
        return (mine == re.sub(r"[\W_]", "", final).upper()[:1]) if mine else None
    if kind == "yes_no":
        mine = _draft_yes_no(draft)
        want = "yes" if re.sub(r"[^a-z]", "", final.lower()) in _YES else "no"
        return (mine == want) if mine else None
    if kind == "list":
        want = _number_list(final) or []
        found = [_number_list(m.group(0)) for m in re.finditer(r"[\[(][-−\d.,\s]+[\])]", _clean(draft[:_HEAD_CHARS]))]
        found = [f for f in found if f]
        if not found:
            return None
        return any(len(f) == len(want) and all(_close(a, b) for a, b in zip(f, want, strict=True)) for f in found)
    if kind == "number":
        value = _final_value(final)
        head = _draft_values((draft or "")[:_HEAD_CHARS])
        if value is None or not head:
            return None
        # A percentage may be written as a fraction ("15.5%" vs "0.155 of the original"), and a value with a unit in
        # another prefix of it ("-1.53 kJ" vs "-1.53 x 10^3 J").
        alts = {value, value / 100.0} if "%" in final else {value}
        if re.search(r"[A-Za-zµΩ°]", re.sub(r"\\[A-Za-z]+", "", final)):
            alts |= {v * f for v in alts for f in (1e3, 1e-3)}
        return any(_close(v, h) for v in alts for h in head)
    return None


def _applies(run: RunContext) -> str:
    """Why the cross-check runs ("" when it does not)."""
    from ...config.settings import get_bool
    from ...verify.formal.prove import wants_proof
    from ..evidence_need import is_closed_problem, is_self_contained
    from ..question_text import is_choice_question
    from .presentation import computations_cover_question

    if not get_bool("TRIBOS_CROSS_CHECK"):
        return ""
    if not run.llm_ok or not (run.candidate_response or "").strip():
        return ""
    if str((run.agent_options or {}).get("effort_level") or "medium") == "low":
        return ""
    question = run.clean_query or run.resolved_query or run.query or ""
    if wants_proof(question) or computations_cover_question(run.tool_results):
        return ""
    if is_choice_question(question):
        return "multiple choice"
    if is_self_contained(run.ctx):
        return "self-contained problem"
    if is_closed_problem(question):
        return "exercise with its own data"
    return ""


async def cross_check(run: RunContext) -> None:
    """Check the draft's final answer against an independent solution; adjudicate and rewrite on disagreement."""
    why = _applies(run)
    if not why:
        return
    from ..conventions import convention_notes
    from ..question_text import is_choice_question
    from .llm_call import ask, budget_admits

    if not budget_admits(run, 3):
        return
    question = run.clean_query or run.resolved_query or run.query or ""
    mc = is_choice_question(question)
    notes = convention_notes(question)
    conventions = ("\nConventions to use:\n" + "\n".join(f"- {n}" for n in notes) + "\n") if notes else ""
    draft = run.candidate_response or ""
    record: dict[str, Any] = {"reason": why}
    run.execution_artifacts["cross_check"] = record
    await run.emit("cross_check", "Solving the problem independently to check the answer", why, status="running")
    try:
        second = await ask(run, _SOLVER_SYSTEM, _SOLVE_PROMPT.format(question=question, conventions=conventions),
                           timeout_s=SOLVE_TIMEOUT_S, model=run.synthesis_model)
    except Exception as exc:  # noqa: BLE001 - a check that cannot run never costs the answer
        logger.info("cross-check: independent solve failed: %s", exc)
        record["status"] = "error"
        await run.emit("cross_check", "Independent check unavailable", str(exc)[:200], status="error")
        return
    final = final_answer(second)
    verdict = agrees(final, draft, multiple_choice=mc) if final else None
    record.update({"independent_final": final[:200], "agrees": verdict})
    if verdict is not False:
        record["status"] = "agreed" if verdict else "not_comparable"
        title = "The independent solution agrees" if verdict else "Independent solution not comparable"
        await run.emit("cross_check", title, final[:200], status="done")
        return

    await run.emit("cross_check", "The independent solution disagrees: adjudicating", final[:200], status="running")
    try:
        verdict_text = await ask(run, _SOLVER_SYSTEM, _ADJUDICATE_PROMPT.format(
            question=question, conventions=conventions, a=draft[:7000], b=second[:5000]),
            timeout_s=SOLVE_TIMEOUT_S, model=run.synthesis_model)
    except Exception as exc:  # noqa: BLE001
        logger.info("cross-check: adjudication failed: %s", exc)
        record["status"] = "error"
        await run.emit("cross_check", "Adjudication unavailable; the draft is kept", str(exc)[:200], status="error")
        return
    decided = final_answer(verdict_text)
    winner = (_WINNER_RE.findall(verdict_text) or [""])[-1].upper()
    record.update({"adjudicated_final": decided[:200], "winner": winner})
    keeps_draft = bool(decided) and agrees(decided, draft, multiple_choice=mc) is not False
    if not decided or winner == "A" or keeps_draft:
        record["status"] = "draft_kept"
        await run.emit("cross_check", "Adjudication kept the draft's answer", decided[:200], status="done")
        return

    reason = re.sub(r"(?im)^\s*\**(?:WINNER|FINAL)\**\s*:.*$", "", verdict_text).strip()[-3000:]
    try:
        text = await ask(run, run.system_prompt, [
            ("user", run.synthesis_prompt), ("assistant", draft),
            ("user", _REWRITE_INSTRUCTION.format(final=decided, reason=reason))], model=run.synthesis_model)
    except Exception as exc:  # noqa: BLE001
        logger.info("cross-check: rewrite failed: %s", exc)
        record["status"] = "error"
        await run.emit("cross_check", "Rewrite unavailable; the draft is kept", str(exc)[:200], status="error")
        return
    text = (text or "").strip()
    if not text or agrees(decided, text, multiple_choice=mc) is False:
        record["status"] = "rewrite_rejected"
        await run.emit("cross_check", "The rewrite did not state the adjudicated answer; the draft is kept",
                       decided[:200], status="error")
        return
    record["status"] = "corrected"
    run.candidate_response = text
    run.streamed_draft = text
    await run.send({"type": "content_reset", "reason": "cross_check"})
    await run.send({"type": "content_delta", "delta": text})
    await run.emit("cross_check", "Corrected the answer after an independent check", f"now {decided[:200]}",
                   status="done")


__all__ = ["agrees", "cross_check", "final_answer"]
