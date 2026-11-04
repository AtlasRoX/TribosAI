"""GPQA is multiple choice: the options are shown, lettered and shuffled, and a letter answer is graded.

From the 2026-11-04 pilot: the loader sent only the question, so both systems answered free-form and the grader could
not match about a quarter of the answers to any option. Published GPQA results present the four options.
"""

from __future__ import annotations

import asyncio
from typing import Any

from tribos.evals import datasets, grading, scoring

ROWS = [
    {"Question": "Which particle mediates the electromagnetic force?", "Correct Answer": "photon",
     "Incorrect Answer 1": "gluon", "Incorrect Answer 2": "W boson", "Incorrect Answer 3": "graviton",
     "Record ID": f"rec{i}", "High-level domain": "Physics"}
    for i in range(12)
]


def _cases(monkeypatch) -> list:
    monkeypatch.setenv("HF_TOKEN", "test")
    monkeypatch.setattr(datasets, "_fetch_hf_rows", lambda *a, **k: ROWS)
    return datasets.load_gpqa()


def test_gpqa_questions_show_four_lettered_options_in_a_reproducible_shuffled_order(monkeypatch):
    cases = _cases(monkeypatch)
    for c in cases:
        assert "Answer choices:" in c.query and all(f"({x}) " in c.query for x in "ABCD")
        assert sorted(c.answer.options) == sorted(["photon", "gluon", "W boson", "graviton"])
        for k, option in enumerate(c.answer.options):
            assert f"({chr(65 + k)}) {option}" in c.query  # the letter order is the options order
    positions = {c.answer.options.index("photon") for c in cases}
    assert len(positions) > 1  # the correct answer is not always (A)
    assert [c.answer.options for c in _cases(monkeypatch)] == [c.answer.options for c in cases]  # reproducible


def test_a_letter_answer_selects_the_option_at_that_position():
    options = ["gluon", "photon", "W boson", "graviton"]
    assert scoring.heuristic_choice("... so the mediator is massless.\n\nAnswer: B", options) == "photon"
    assert scoring.heuristic_choice("Final: \\boxed{(D)}", options) == "graviton"
    assert scoring.heuristic_choice("I first thought (A), but the answer is (C).\nAnswer: (C)", options) == "W boson"
    assert scoring.heuristic_choice("Answer: photon", options) == "photon"  # the option text still works


def test_a_scaled_unit_answer_in_base_units_is_right_for_scibench():
    # From the pilot: "in 10^6" asked, 4.8 x 10^6 answered, graded wrong against 4.76.
    from tribos.evals.schema import AnswerExpect

    assert datasets._unit_scale("$10^6$") == 1e6 and datasets._unit_scale("$10^{-4} \\mathrm{~m}$") == 1e-4
    assert datasets._unit_scale("$\\mathrm{~kJ}$") is None
    expect = AnswerExpect(answer_type="numeric", numeric_answer=4.76, numeric_rel_tol=0.02, numeric_tolerance=1e-2,
                          numeric_scale=1e6, verified=None)
    for answer, ok in (("\\boxed{4.8\\times10^6}", True), ("\\boxed{4.76}", True), ("\\boxed{5.2\\times10^6}", False)):
        checks, _ = scoring.answer_checks(expect, {"response": answer})
        assert next(c for c in checks if c.name == "answer.numeric").passed is ok, answer


def test_the_model_grader_sees_lettered_options_and_may_reply_with_a_letter(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_ask(_factory, _model, _system, user, _timeout):
        seen["user"] = user
        return {"choice": "B"}

    monkeypatch.setattr(grading, "_ask", fake_ask)
    picked = asyncio.run(grading.extract_label("q", "the second one", ["gluon", "photon", "W boson"], llm_factory=None))
    assert picked == "photon" and "(A) gluon" in seen["user"] and "(B) photon" in seen["user"]
