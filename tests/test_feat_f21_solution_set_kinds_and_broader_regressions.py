"""
Tests for Feature F21: Preserve solution-set kinds and independent checks across broader regressions.

Covers:
- Solution sets with denominator exclusions: (x^2 - 16)/(x - 4) = x + 4 -> ℝ ∖ {4}, and (x^2 - 16)/(x - 4) = 8 -> ∅.
- Additional held-out rational pairs: (x^2 - 9)/(x - 3) = x + 3 -> ℝ ∖ {3}, and (x^2 - 9)/(x - 3) = 6 -> ∅.
- Real versus complex domain distinctions: x^2 + 4 = 0 -> ∅ over ℝ, {−2i, 2i} over ℂ.
- Radical equations with extraneous root rejection: sqrt(x + 2) = x -> {2}, sqrt(x + 6) = x -> {3}.
- Universal identities versus contradictions: (x - 3)^2 = x^2 - 6x + 9 -> ℝ, (x - 3)^2 = x^2 - 6x + 10 -> ∅.
- Rejection of forged or incomplete solution sets during independent verification.
- Writer failure deterministic fallback rendering into standard mathematical set notation.
"""

from __future__ import annotations

import pytest

from tribos.axiom.engine import axiom_solve
from tribos.axiom.problem import parse_problem
from tribos.axiom.verifier import verify
from tribos.utils.output_contract import conform, extract


def _rendered_set(question: str) -> str:
    spec = parse_problem(question)
    domain = "real" if "real" in question.lower() else "complex"
    var = spec.variable or "x"
    args = {"equations": spec.expression, "variables": var, "domain": domain}
    data = axiom_solve(**args)
    res = verify(spec, "axiom_solve", args, data)
    assert res.status == "verified", f"Verification failed: {res.checks}"

    # Verify set_text or pretty set formatting
    set_text = res.answer.get("set_text")
    if set_text:
        return set_text
    sol_set = res.answer.get("solution_set")
    if sol_set:
        return sol_set
    return res.answer.get("text", "")


@pytest.mark.parametrize(
    "question, expected",
    [
        # S03 / S04 style rational equations with excluded points
        ("Solve (x^2 - 16)/(x - 4) = x + 4 over the real numbers.", "ℝ ∖ {4}"),
        ("Solve (x^2 - 16)/(x - 4) = 8 over the real numbers.", "∅"),
        ("Solve (x^2 - 9)/(x - 3) = x + 3 over the real numbers.", "ℝ ∖ {3}"),
        ("Solve (x^2 - 9)/(x - 3) = 6 over the real numbers.", "∅"),
        # Real vs Complex domains
        ("Solve x^2 + 4 = 0 over the real numbers.", "∅"),
        ("Solve x^2 + 4 = 0 over the complex numbers.", "{−2i, 2i}"),
        # Extraneous roots in radical equations
        ("Solve sqrt(x + 2) = x over the real numbers.", "{2}"),
        ("Solve sqrt(x + 6) = x over the real numbers.", "{3}"),
        # Polynomial identities and contradictions
        ("Solve (x - 3)^2 = x^2 - 6x + 9 over the real numbers.", "ℝ"),
        ("Solve (x - 3)^2 = x^2 - 6x + 10 over the real numbers.", "∅"),
    ],
)
def test_f21_solution_set_kinds_across_domains(question: str, expected: str):
    rendered = _rendered_set(question)
    assert rendered == expected, f"Expected {expected}, got {rendered}"


def test_f21_infinite_sets_never_confused_with_no_solutions():
    for q, wrong_set in [
        ("Solve (x^2 - 16)/(x - 4) = x + 4 over the real numbers.", "Reals"),
        ("Solve (x - 3)^2 = x^2 - 6x + 9 over the real numbers.", "Union(Interval.open(-oo, 3), Interval.open(3, oo))"),
    ]:
        spec = parse_problem(q)
        args = {"equations": spec.expression, "variables": "x", "domain": "real"}
        data = axiom_solve(**args)
        good = verify(spec, "axiom_solve", args, data)
        assert good.status == "verified"
        assert "no solutions" not in good.answer["text"]
        # Falsified solution set must be rejected
        bad = verify(spec, "axiom_solve", args, dict(data, solution_set=wrong_set))
        assert bad.status != "verified"


def test_f21_writer_fallback_conform_preserves_single_line_set_notation():
    prompt = "Solve (x^2 - 1)/(x - 1) = x + 1 over the real numbers. Give the complete solution set on one line in set notation. Add nothing else."
    contract = extract(prompt)
    assert contract.active
    assert contract.exact_lines == 1

    # Deterministic fallback text
    raw_answer = "ℝ ∖ {1}"
    conformed = conform(raw_answer, contract)
    assert conformed == "ℝ ∖ {1}"

    # Empty set fallback
    empty_prompt = "Solve x^2 + 1 = 0 over the real numbers. Give the complete solution set on one line in set notation. Add nothing else."
    empty_contract = extract(empty_prompt)
    assert empty_contract.active
    assert empty_contract.exact_lines == 1
    empty_conformed = conform("∅", empty_contract)
    assert empty_conformed == "∅"
