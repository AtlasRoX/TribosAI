"""Generalisation of the answer audit beyond the captured oscillator (tribos.evals.math_claims_matrix).

The matrix is generated from oracle formulas for nine kinds of mathematics; it is kept apart from the regression
fixtures (tests/fixtures/math) so passing it is not a matter of tuning to the captured run.
"""

from __future__ import annotations

from tribos.evals.math_claims_matrix import build_cases, run_matrix


def test_no_correct_answer_is_flagged_and_corrupted_answers_are_caught():
    rows = run_matrix()
    assert len(rows) >= 9
    for capability, r in rows.items():
        assert r["false_alarms"] == 0, (capability, r["alarms"])
        assert r["claims_checked"] >= r["cases"], capability  # every correct answer has at least one checked claim
    caught = sum(r["caught"] for r in rows.values())
    corrupted = sum(r["corrupted"] for r in rows.values())
    assert corrupted >= 60 and caught / corrupted >= 0.95, [m for r in rows.values() for m in r["missed"]]


def test_the_matrix_covers_more_than_the_regression_problem():
    caps = {c.capability for c in build_cases()}
    assert {"first-order ODE", "algebra", "calculus", "linear algebra", "probability", "physics formulas"} <= caps
