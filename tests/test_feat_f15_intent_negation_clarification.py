"""
Tests for Feature F15: Interpret task intent, negation and clarification requirements consistently.

Covers:
- B1/R1 (T01/T02): Collatz proof with negated simulation language does not become an ODE/simulation clarification.
- Positive fully-specified simulation control executes; underspecified simulation asks relevant question.
- P13 (T33): Short status lookup does not become hypothesis generation or debate.
- Positive hypothesis generation control correctly triggers hypothesis phase.
- P14 (T35/T36): Removed word limit stays revoked and is never classified as a literature-absence claim.
- Real absence, status, and mathematical negation statements are correctly distinguished.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tribos.agentic.clarify import detect_signals
from tribos.agentic.hypothesis import HypothesisPhase
from tribos.agentic.router import routing_signals, rule_decision
from tribos.agents import query_planner
from tribos.agents.evidence_need import assess_evidence_need
from tribos.agents.query_planner import detect_simulation_constraints
from tribos.utils.output_contract import extract
from tribos.verify.verifier import TribosVerifier, statement_role

# ---------------------------------------------------------------------------
# B1/R1 & T01/T02: Collatz Proof & Simulation Intent / Clarification Controls
# ---------------------------------------------------------------------------

COLLATZ_RULES = """Consider the Collatz process on positive integers:
- If n is even, replace it with n/2.
- If n is odd, replace it with 3n + 1.

Prove or disprove that this process eventually reaches 1 for every positive integer.
"""
T01 = COLLATZ_RULES + (
    "\nGive a rigorous mathematical justification. Checking examples, running simulations, or assuming that the "
    "sequence eventually decreases does not establish the claim for every positive integer."
)
T02 = COLLATZ_RULES + "\nGive a rigorous mathematical justification."


def test_f15_collatz_negated_simulation_is_not_simulation_request():
    negated_cases = [
        T01,
        "Running simulations does not establish the claim; give a proof that the map always reaches 1.",
        'A reviewer wrote "just simulate it", but I want a proof that every orbit reaches 1.',
        "Even if you simulate many starting values, that is not a proof. Prove the statement instead.",
        "Prove the identity without simulating anything.",
        "Simulations cannot settle this conjecture; explain its status.",
    ]
    for q in negated_cases:
        res = detect_simulation_constraints(q)
        assert res.simulation_requested is False, f"Failed for {q}"


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [T01, T02])
async def test_f15_proof_requests_generate_no_clarification_signals(question):
    ctx = await query_planner.build_query_context(
        query=question,
        clean_query=question,
        registry=None,
        enable_web_search=True,
        attachments=[],
        attachment_errors=[],
        user_id="u",
        thread_id="t",
        model_name="",
        api_key=None,
        budget_s=1.0,
    )
    assert ctx.is_simulation_intent is False
    assert not ctx.should_run("dynamis")
    assert detect_signals(ctx, question) == []
    assert ctx.evidence_need.skip_retrieval is True


def test_f15_positive_and_underspecified_simulation_controls():
    # Fully specified simulation
    full_sim = "Simulate the damped oscillator x'' + 0.5 x' + 4 x = 0 with x(0) = 1, x'(0) = 0 for 10 seconds."
    full_res = detect_simulation_constraints(full_sim)
    assert full_res.simulation_requested is True

    # Underspecified simulation
    underspec = "Simulate the damped oscillator x'' + 0.5 x' + 4 x = 0 for 10 seconds."
    under_res = detect_simulation_constraints(underspec)
    assert under_res.simulation_requested is True


# ---------------------------------------------------------------------------
# P13 & T33: Status Lookup vs Hypothesis Generation Controls
# ---------------------------------------------------------------------------


def test_f15_status_lookup_is_not_hypothesis_generation():
    status_lookups = [
        "What is the current accepted status of the Riemann Hypothesis? Check Clay Mathematics Institute's official website. Answer in one sentence and include the source URL.",
        "Current RH status from CMI, one sentence with source URL.",
        "What is the status of the Collatz conjecture?",
        "Is Goldbach's conjecture proved?",
        "Has the twin prime conjecture been proved?",
        "Explain the null hypothesis in a t-test.",
        "Critique this proposed proof method for the Collatz conjecture.",
    ]

    phase = HypothesisPhase()
    for q in status_lookups:
        sig = routing_signals(q, None)
        assert sig.hypothesis is False, f"Expected hypothesis=False for {q}"

        decision = rule_decision(q, None)
        assert decision.rule != "hypothesis_generation", f"Expected rule != hypothesis_generation for {q}"

        state = SimpleNamespace(
            ctx=SimpleNamespace(scope="research", excluded_modules=set()),
            options={},
            clean_query=q,
            query=q,
        )
        assert phase.applies(state) is False, f"HypothesisPhase should not apply to {q}"


def test_f15_positive_hypothesis_generation_controls():
    hypo_prompts = [
        "Propose new hypotheses for why bacterial biofilms tolerate antibiotics.",
        "Generate three testable conjectures about the gaps between consecutive primes.",
        "What hypotheses explain the anomalous precession of Mercury's perihelion?",
        "Develop testable hypotheses for the origin of fast radio bursts.",
    ]
    for q in hypo_prompts:
        sig = routing_signals(q, None)
        assert sig.hypothesis is True, f"Expected hypothesis=True for {q}"
        decision = rule_decision(q, None)
        assert decision.rule == "hypothesis_generation", f"Expected rule==hypothesis_generation for {q}"


# ---------------------------------------------------------------------------
# P14 & T35/T36: Removed Limits and Absence vs Status Statements
# ---------------------------------------------------------------------------


def test_f15_revoked_limits_stay_revoked():
    cases = [
        ("Provide enough detail to assess the mathematics. There is no 150-word limit.", {}),
        ("The 150-word limit no longer applies.", {}),
        ("You are not limited to 200 words.", {}),
        ("There is no word limit.", {}),
        ("Sin límite de 150 palabras. Explica la demostración.", {}),
        ('Classify the instruction "answer in at most 50 words" as formatting.', {}),
        (
            "Answer in at most 150 words. Later: remove the previous 150-word limit and write 220-250 words.",
            {"min_words": 220, "max_words": 250},
        ),
    ]
    for q, expected in cases:
        c = extract(q)
        got = {k: getattr(c, k) for k in ("max_words", "min_words", "exact_words", "exact_lines") if getattr(c, k) is not None}
        assert got == expected, f"Failed for {q}"
        if not expected and "limit" in q.lower():
            assert c.inactive, f"Expected inactive recording for {q}"


def test_f15_instruction_negation_not_treated_as_literature_absence():
    # "There is no 150-word limit" is an instruction, never an empirical absence claim
    role = statement_role("There is no 150-word limit.")
    assert role == "instruction"

    # Factual absence, status, and mathematical negation
    assert statement_role("There are no published studies of this alloy at 4 K.") is None
    assert TribosVerifier._classify_claim("There are no published studies of this alloy at 4 K.") == "absence"

    assert statement_role("No accepted proof of the Riemann Hypothesis is known.") is None
    assert TribosVerifier._classify_claim("No accepted proof of the Riemann Hypothesis is known.") == "status"

    assert statement_role("There is no real solution of x^2 + 1 = 0.") == "mathematical"


def test_f15_status_needs_source_derivation_does_not():
    status_need = assess_evidence_need("What is the status of the Collatz conjecture?")
    assert status_need.kind == "current"
    assert status_need.level == "required"

    math_need = assess_evidence_need("Prove that the sum of two odd integers is even.")
    assert math_need.kind == "self_contained"
    assert math_need.level == "none"
