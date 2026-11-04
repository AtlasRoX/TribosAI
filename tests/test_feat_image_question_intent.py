"""An attached image's transcription describes the problem; it never requests actions, and its options stay options."""

from __future__ import annotations

from tribos.agentic.decompose import is_single_proof_problem
from tribos.agents.evidence_need import assess_evidence_need
from tribos.agents.question_text import is_multiple_choice, typed_part
from tribos.agents.task_plan import build_task_plan
from tribos.files import requested_files

QUESTION = (
    "Solve the problem in the attached image, showing every step.\n\n"
    "Attached image 1 (image.png), transcribed:\n"
    "The distance travelled by the particle in four seconds is\n"
    "(a) $60\\ m$\n(b) $55\\ m$\n(c) $25\\ m$\n(d) $30\\ m$\n"
    "Figure: A velocity vs time graph. The plot starts at (0,0), rises linearly to (1,20), stays at 20 to t = 2."
)


def test_the_transcription_requests_nothing():
    assert typed_part(QUESTION) == "Solve the problem in the attached image, showing every step."
    assert requested_files(typed_part(QUESTION)) == []  # "image.png" is the attachment's name, not a request
    assert build_task_plan(QUESTION) == []  # "The plot starts at" describes the figure


def test_a_numeric_multiple_choice_question_is_one_self_contained_problem():
    assert is_multiple_choice(QUESTION) and is_single_proof_problem(QUESTION)
    need = assess_evidence_need(QUESTION)
    assert need.skip_retrieval and need.kind == "self_contained"
    assert not is_multiple_choice("Solve x^2 = 4 (a function of x)")


def test_an_open_question_the_router_judges_self_contained_runs_no_search():
    from types import SimpleNamespace

    from tribos.agents.evidence_need import EvidenceNeed
    from tribos.agents.orchestration import plan as plan_mod

    ctx = SimpleNamespace(evidence_need=EvidenceNeed("optional", "open", "may depend on published findings"),
                          scope="research", decisions={})
    calls: list[str] = []
    real = plan_mod.query_planner.decide_builtin_sources
    plan_mod.query_planner.decide_builtin_sources = lambda c: calls.append("decided")
    try:
        plan_mod._drop_unneeded_search(SimpleNamespace(ctx=ctx), SimpleNamespace(
            semantic={"used": True, "needs_outside_information": False}))
        assert ctx.evidence_need.skip_retrieval and calls == ["decided"]
        ctx.evidence_need = EvidenceNeed("optional", "open", "may depend on published findings")
        plan_mod._drop_unneeded_search(SimpleNamespace(ctx=ctx), SimpleNamespace(
            semantic={"used": True, "needs_outside_information": True}))
        assert not ctx.evidence_need.skip_retrieval  # outside facts needed: the search stays
        ctx.evidence_need = EvidenceNeed("required", "literature", "asks for sources")
        plan_mod._drop_unneeded_search(SimpleNamespace(ctx=ctx), SimpleNamespace(
            semantic={"used": True, "needs_outside_information": False}))
        assert not ctx.evidence_need.skip_retrieval  # an explicit request for sources is never overridden
    finally:
        plan_mod.query_planner.decide_builtin_sources = real


STATEMENTS_MCQ = (
    "Solve the problem in the attached image, showing every step.\n\n"
    "Attached image 1 (q7.png), transcribed:\n"
    "Q.7 Two thin circular discs of mass $m$ and $4m$, having radii of $a$ and $2a$, are rigidly fixed by a rod of "
    "length $l=\\sqrt{24}\\,a$ and set rolling without slipping with angular speed $\\omega$ about the rod. "
    "Which of the following statement(s) is(are) true?\n\n"
    "(A) The center of mass rotates about the $z$-axis with an angular speed of $\\omega/5$\n\n"
    "(B) The magnitude of angular momentum of center of mass about O is $81ma^2\\omega$\n\n"
    "(C) The magnitude of angular momentum about its center of mass is $17ma^2\\omega/2$\n\n"
    "(D) The magnitude of the $z$-component of $\\vec{L}$ is $55ma^2\\omega$\n\n"
    "Figure: A curved arrow labeled $\\omega$ indicates rotation about the rod axis."
)


def test_a_multiple_choice_problem_with_statement_options_is_one_self_contained_problem():
    need = assess_evidence_need(STATEMENTS_MCQ)
    assert need.skip_retrieval and need.kind == "self_contained"
    from tribos.agentic.decompose import complexity_signals

    signals = complexity_signals(STATEMENTS_MCQ)
    assert not {"several questions", "enumeration", "conjoined question clauses"} & set(signals)


def test_a_figure_label_is_not_drug_labelling():
    from tribos.agents.search_plan import classify_question

    assert classify_question("A curved arrow labeled omega shows the rotation.") != "regulatory"
    assert classify_question("What does the FDA label say about off-label use of the drug?") == "regulatory"


def test_latex_4m_is_a_multiple_of_the_variable_m_not_metres():
    from tribos.agents.entity_lexicon import find_offline_quantities

    assert find_offline_quantities("two discs of mass $m$ and $4m$") == []
    assert [h["label"] for h in find_offline_quantities("a rod 4 m long")] == ["4 m"]


def test_the_math_agent_skips_a_misread_problem_and_hides_an_unmatched_result():
    from types import SimpleNamespace

    from tribos.agentic.math_agent import _misread_problem, _unmatched
    from tribos.axiom.problem import parse_problem

    solve_a = SimpleNamespace(kind="solve", expression="A", equations=[], unaccounted=["24", "5", "2"])
    assert _misread_problem(solve_a, STATEMENTS_MCQ)  # the full Q.7 text parsed as "solve A"
    assert _misread_problem(SimpleNamespace(kind="solve", expression="A", equations=[], unaccounted=[]), "Solve A")
    assert not _misread_problem(parse_problem("Solve x^2 - 4 = 0"), "Solve x^2 - 4 = 0")
    check = lambda level, passed: SimpleNamespace(level=level, passed=passed)  # noqa: E731
    assert _unmatched(SimpleNamespace(verdict=SimpleNamespace(checks=[check(2, True), check(1, False)])))
    assert not _unmatched(SimpleNamespace(verdict=SimpleNamespace(checks=[check(2, True), check(1, True)])))
