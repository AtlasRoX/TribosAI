"""The evidence-need gate: self-contained calculations skip literature and web search, everything else keeps them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tribos.agentic.confidence import computation_confidence
from tribos.agentic.specialists import tool_allowed
from tribos.agents.evidence_need import assess_evidence_need, is_closed_computation
from tribos.agents.query_context import QueryContext
from tribos.agents.query_planner import decide_builtin_sources

ORIGINAL = (
    "Evaluate 3/4 + (5/6 × 12/5) − 2^3. Show every calculation step, follow the correct order of operations, "
    "simplify the exact fraction, and verify the final answer independently."
)


@pytest.mark.parametrize(
    "question",
    [
        ORIGINAL,
        "What is 2+3?",
        "Find the maximum of x^2 - 4x + 1 on the interval [0, 5]",
        "Solve x^2 - 5x + 6 = 0",
        "Integrate x*sin(x) from 0 to pi",
        "Prove that sin(2x) = 2 sin(x) cos(x)",
        "Find the remainder of 2^2024 divided by 7",  # a number, not a date
        "Find the standard deviation of 2, 4, 4, 4, 5, 5, 7, 9",  # "standard" here is statistics, not a code
        "Differentiate e^(3x) cos(x) with respect to x",
    ],
)
def test_self_contained_calculations_need_no_outside_evidence(question):
    need = assess_evidence_need(question)
    assert (need.level, need.kind) == ("none", "closed_computation"), need
    assert need.skip_retrieval


@pytest.mark.parametrize(
    ("question", "level", "kind"),
    [
        ("Evaluate 3/4 + 2 - 8 and cite papers on the order of operations", "required", "literature"),
        ("Review the literature on turbulence closure models", "required", "literature"),
        ("What are the latest advances in solid-state batteries?", "required", "current"),
        ("What was the record wind speed measured in 2024?", "required", "current"),  # dated beats measured
        ("Find the current through a 5 ohm resistor and the measured voltage drop", "optional", "empirical"),
        ("What is the yield strength of 6061-T6 aluminium?", "optional", "empirical"),
        # Not provably self-contained (physical quantities with units, a real substance): retrieval runs as before.
        ("Derive the terminal velocity of a steel ball (radius r = 10 mm, density rho = 7850 kg/m^3) in water", "optional", "open"),
        ("What mechanisms make bacterial biofilms tolerant to antibiotics?", "optional", "open"),
    ],
)
def test_questions_that_can_depend_on_outside_evidence_keep_retrieval(question, level, kind):
    need = assess_evidence_need(question)
    assert (need.level, need.kind) == (level, kind), need
    assert not need.skip_retrieval


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        # Audit I04: retrieval follows an identified information need, not the availability of search.
        ("Explain how a transistor works", "established_knowledge"),
        ("Evaluate pi^2/6 numerically to 10 digits", "self_contained"),  # "10" is a precision, not an input
        ("Show that the sum of two odd integers is even.", "self_contained"),
        ("Prove or disprove that this process eventually reaches 1 for every positive integer.", "self_contained"),
        ("A tank holds 120 L and drains at 4 L/min. How long until it is empty? Answer in at most 20 words.", "self_contained"),
        ("Return exactly the following two lines as plain text. Preserve the newline and add nothing else:\n\nALPHA\nBETA", "format"),
        ("Evaluate n^2 + n + 41 in two independent cases:\n\nCase A: n = 40.\nCase B: n = 41.", "closed_computation"),
    ],
)
def test_self_contained_requests_retrieve_nothing(question, kind):
    need = assess_evidence_need(question)
    assert need.kind == kind, need
    assert need.skip_retrieval


def test_a_named_material_or_constant_is_never_closed():
    ctx = SimpleNamespace(materials=[SimpleNamespace(label="steel")])
    assert assess_evidence_need("Evaluate 2 + 3", ctx).kind == "empirical"


def _ctx(question: str, web: bool = True) -> QueryContext:
    ctx = QueryContext(raw_query=question, clean_query=question, enable_web_search=web)
    ctx.evidence_need = assess_evidence_need(question, ctx)
    decide_builtin_sources(ctx)
    return ctx


def test_routing_skips_literature_and_web_for_a_calculation_and_says_why():
    ctx = _ctx(ORIGINAL)
    assert is_closed_computation(ctx)
    for name in ("archivon", "websurfer", "lithoscribe"):
        assert ctx.decisions[name].run is False
        assert "self-contained calculation" in ctx.decisions[name].reason
    assert ctx.decisions["axiom"].run is True


OPEN_QUESTION = "What mechanisms make bacterial biofilms tolerant to antibiotics?"


def test_routing_keeps_literature_and_web_for_an_open_question():
    ctx = _ctx(OPEN_QUESTION)
    assert ctx.decisions["archivon"].run is True
    assert ctx.decisions["websurfer"].run is True
    # Search off covers every external retrieval, the scholarly literature as well as the web (audit T08).
    off = _ctx(OPEN_QUESTION, web=False)
    assert off.decisions["websurfer"].run is False and off.decisions["archivon"].run is False
    assert "Search is off" in off.decisions["archivon"].reason


def test_agentic_phases_cannot_call_retrieval_tools_for_a_calculation():
    closed, open_ = _ctx(ORIGINAL), _ctx(OPEN_QUESTION)
    for name in ("archivon_literature_search", "websurfer_search", "lithoscribe_literature_synthesis"):
        entry = SimpleNamespace(name=name, domain="")
        allowed, reason = tool_allowed(closed, entry)
        assert not allowed and "self-contained" in reason
        assert tool_allowed(open_, entry)[0]
    assert tool_allowed(closed, SimpleNamespace(name="axiom_simplify", domain="axiom"))[0]


def test_a_verified_calculation_is_scored_by_its_measured_accuracy_not_literature_support():
    art = computation_confidence({
        "status": "verified",
        "confidence": {"p_correct": 0.9778, "lower_95": 0.918, "n": 43, "fitted_on": "math-eval-v1"},
        "verification": {"checks": [{"name": "independent re-evaluation", "passed": True, "level": 1}]},
    })
    # The measured precision is the agent's final expression's, never a probability for the whole written answer.
    assert art["answer_confidence"] is None
    comp = art["component_confidence"]
    assert comp["p_correct"] == 0.9778 and comp["n"] == 43 and "final answer expression" in comp["scope"]
    assert "does not cover the written derivation" in art["calibration"]["note"]
    assert art["method"] == "computational_verification"
    assert art["claims"] == [] and art["basis"] == ["independent re-evaluation"]
    # No calibration: no number is made up from the status.
    assert computation_confidence({"status": "verified"})["answer_confidence"] is None
