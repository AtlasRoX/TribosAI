"""One final answer per response, found the same way for every system (benchmark fairness).

From the 2026-11-04 pilot: a prose answer "$10{,}000$ per day" was read as 0, "2 x 4 x 30 = 240 apples in 30 days" as
30 (the last number), while a boxed answer was read exactly; and an unboxed answer passed whenever the expected number
appeared anywhere in its working. Now the boxed value is used when present, otherwise the grader model's reading of
the stated final answer, checked strictly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tribos.evals import grading, scoring
from tribos.evals.runner import Evaluator, RunConfig
from tribos.evals.schema import AnswerExpect, EvalCase


@pytest.mark.parametrize("raw, value", [("10{,}000", 10000.0), ("10\\,000", 10000.0), ("1,234.5", 1234.5), ("240", 240.0)])
def test_latex_thousands_separators_parse(raw, value):
    assert scoring._parse_numeric_str(raw) == value
    assert scoring.extract_numeric_answer(f"\\boxed{{{raw}}}") == value


def _case(expected: float) -> EvalCase:
    return EvalCase(id="c", suite="gsm8k", query="q", answer=AnswerExpect(answer_type="numeric", numeric_answer=expected,
                                                                          numeric_tolerance=1e-3, verified=None))


def _score(monkeypatch, response: str, expected: float, extracted: str | None, previous: dict | None = None):
    calls: list[str] = []

    async def fake_extract(question, answer, **_kw):
        calls.append(answer)
        return extracted

    monkeypatch.setattr(grading, "extract_final_answer", fake_extract)
    ev = Evaluator(RunConfig(levels=["answer"]), orchestrator=object(), run_id="t")
    observed: dict[str, Any] = {"response": response, "query": "q"}
    checks, metrics = asyncio.run(ev._score_answer(_case(expected), observed, judge=False, previous=previous))
    numeric = next(c for c in checks if c.name == "answer.numeric")
    return numeric.passed, metrics, calls


def test_a_prose_answer_is_graded_on_its_stated_result_not_the_last_number(monkeypatch):
    ok, metrics, calls = _score(monkeypatch, "Marin and Nancy eat $2 \\times 4 \\times 30 = 240$ apples in 30 days.", 240, "240")
    assert ok and metrics["final_answer_source"] == "model" and metrics["final_answer"] == "240" and len(calls) == 1


def test_a_matching_number_in_the_working_does_not_rescue_a_wrong_final_answer(monkeypatch):
    # The expected 30 appears in the working, but the answer commits to 36.
    ok, metrics, _ = _score(monkeypatch, "8 + 16 + 6 = 30 if the sister is younger than Nani; taking the brother, the total is 36.",
                            30, "36")
    assert not ok and metrics["numeric_predicted"] == 36


def test_a_boxed_answer_is_used_as_is_without_asking_the_grader(monkeypatch):
    ok, metrics, calls = _score(monkeypatch, "Working... \\boxed{10{,}000}", 10000, "999")
    assert ok and metrics["final_answer_source"] == "boxed" and calls == []


def test_rescore_reuses_the_extracted_final_answer(monkeypatch):
    ok, metrics, calls = _score(monkeypatch, "They eat 240 apples.", 240, "1",
                                previous={"final_answer_source": "model", "final_answer": "240"})
    assert ok and calls == [] and metrics["final_answer"] == "240"


def test_without_a_grader_the_heuristic_is_used_and_labelled(monkeypatch):
    ok, metrics, _ = _score(monkeypatch, "The answer is 240.", 240, None)
    assert ok and metrics["final_answer_source"] == "heuristic"


@pytest.mark.parametrize("answer, reference", [
    (r"\frac14", r"\frac{1}{4}"), (r"\dfrac34", r"\frac{3}{4}"), (r"\frac1{x}", r"\frac{1}{x}"), (r"\sqrt2", r"\sqrt{2}"),
    ("Evelyn", r"\text{Evelyn}"), (r"\text{(C)}", r"\text{(C)}"), ("evelyn", r"\text{Evelyn}"),
])
def test_latex_shorthand_and_text_answers_are_equivalent(answer, reference):
    # From the pilot: Tribos's correct MATH-500 answers "\frac14" and "Evelyn" were graded wrong.
    assert scoring.symbolic_equivalent(answer, reference)


@pytest.mark.parametrize("answer, reference", [(r"\frac15", r"\frac{1}{4}"), ("Alice", r"\text{Evelyn}"), ("x", "X")])
def test_different_answers_stay_different(answer, reference):
    assert not scoring.symbolic_equivalent(answer, reference)


def test_numeric_answers_in_latex_shorthand_or_with_an_approximation_parse():
    # From the pilot (SciBench): Tribos's correct answers were read as "no number".
    assert scoring._parse_numeric_str(r"\frac16") == pytest.approx(1 / 6)
    assert scoring._parse_numeric_str(r"-\frac12") == -0.5
    assert scoring._parse_numeric_str(r"2\sqrt{2}\sin\left(\frac{\pi}{2\sqrt{2}}\right)\approx 2.534") == 2.534
