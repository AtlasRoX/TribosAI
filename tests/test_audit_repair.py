"""Audit repair regressions (docs/AUDIT_REPAIR_REPORT.md, issues I01-I23, acceptance tests T01-T20).

Every test drives the production component the defect lived in: the query understanding, the problem parser, the
Axiom agent and its verifier, the answer checker, the output contract, the orchestrator (offline registry, no model),
the tool-execution policy layer and the literature engine (mocked HTTP only)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.fakes import called, make_offline_orchestrator

COLLATZ_RULES = """Start with any positive integer n. Repeatedly apply these rules:

- If n is even, replace it with n/2.
- If n is odd, replace it with 3n + 1.

Prove or disprove that this process eventually reaches 1 for every positive integer.
"""
T01 = COLLATZ_RULES + (
    "\nGive a rigorous mathematical justification. Checking examples, running simulations, or assuming that the "
    "sequence eventually decreases does not establish the claim for every positive integer.")
T02 = COLLATZ_RULES + "\nGive a rigorous mathematical justification."
T03 = """Define T(n) = n/2 for even positive integers and T(n) = 3n + 1 for odd positive integers.

Compute T(1), T(2), and T(4).

Then write the cycle starting at 1, with each arrow representing exactly one application of T.

Answer in at most 40 words."""
T04 = """Let f: R -> R be defined by f(x) = x^2 + 1.

1. Compute f(2).
2. Prove that f(x) - x^2 = 1 for every real x.

Answer in at most 50 words."""
T04_UNICODE = "Let f: ℝ → ℝ be defined by f(x) = x² + 1.\n\n1. Compute f(2).\n2. Prove that f(x) − x² = 1 for every real x."
T05 = "Prove that n^2 + n + 41 is prime for every nonnegative integer n.\n\nGive a rigorous proof in at most 80 words."
T06 = """Evaluate n^2 + n + 41 in two independent cases:

Case A: n = 40.
Case B: n = 41.

Keep each assignment local to its case.

Answer in exactly two lines, giving the value and a factorization for each case."""
T06_REVERSED_RENAMED = T06.replace("Case A: n = 40.\nCase B: n = 41.", "Case B: m = 41.\nCase A: m = 40.").replace(
    "n^2 + n + 41", "m^2 + m + 41")
T07 = "Return exactly the following two lines as plain text. Preserve the newline and add nothing else:\n\nALPHA\nBETA"

EXTERNAL_TOOLS = {"archivon_literature_search", "archivon_paper_details", "archivon_recommend",
                  "lithoscribe_literature_synthesis", "websurfer_search", "physis_encyclopedia", "physis_materials",
                  "physis_oeis", "physis_wolfram"}


def _solve(question: str) -> dict[str, Any]:
    from tribos.axiom.agent import HybridPolicy, MathAgentConfig, local_executor, solve_math_problem

    cfg = MathAgentConfig()
    run = asyncio.run(solve_math_problem(question, executor=local_executor(), policy=HybridPolicy(None, cfg), config=cfg))
    return run.to_dict()


def _results(art: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in art["answer"]["results"]}


# I01 / I02 / T01 / T02 / T11: intent, negation, clarification ------------------------------------------------------

@pytest.mark.parametrize("question", [
    T01,
    "Running simulations does not establish the claim; give a proof that the map always reaches 1.",
    'A reviewer wrote "just simulate it", but I want a proof that every orbit reaches 1.',
    "Even if you simulate many starting values, that is not a proof. Prove the statement instead.",
    "Prove the identity without simulating anything.",
    "Simulations cannot settle this conjecture; explain its status.",
])
def test_negated_quoted_or_hypothetical_simulation_is_not_a_request(question):
    from tribos.agents.query_planner import detect_simulation_constraints

    assert detect_simulation_constraints(question).simulation_requested is False


@pytest.mark.parametrize("question", [
    "Simulate the damped oscillator x'' + 0.5 x' + 4 x = 0 with x(0) = 1, x'(0) = 0 for 10 seconds.",
    "Please run a simulation of the Lorenz system for 50 s.",
    "Can you simulate a predator-prey model for 100 days?",
])
def test_real_simulation_requests_are_still_recognised(question):
    from tribos.agents.query_planner import detect_simulation_constraints

    assert detect_simulation_constraints(question).simulation_requested is True


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [T01, T02])
async def test_proof_requests_need_no_simulation_clarification_or_literature(question):
    from tribos.agentic.clarify import detect_signals
    from tribos.agents import query_planner

    ctx = await query_planner.build_query_context(
        query=question, clean_query=question, registry=None, enable_web_search=True, attachments=[],
        attachment_errors=[], user_id="u", thread_id="t", model_name="", api_key=None, budget_s=1.0)
    assert ctx.is_simulation_intent is False
    assert not ctx.should_run("dynamis")
    assert detect_signals(ctx, question) == []
    # Mathematics from the question's own definitions: no literature or web search (I04).
    assert ctx.evidence_need.skip_retrieval and not ctx.decisions["archivon"].run


@pytest.mark.asyncio
async def test_fully_specified_simulation_runs_and_missing_initial_condition_asks_once():
    from tribos.agentic.clarify import detect_signals
    from tribos.agents import query_planner

    async def ctx_for(q):
        return await query_planner.build_query_context(
            query=q, clean_query=q, registry=None, enable_web_search=True, attachments=[], attachment_errors=[],
            user_id="u", thread_id="t", model_name="", api_key=None, budget_s=1.0)

    full = "Simulate x'' + 0.5 x' + 4 x = 0 with x(0) = 1, x'(0) = 0 for 10 seconds."
    ctx = await ctx_for(full)
    assert ctx.is_simulation_intent and ctx.should_run("dynamis") and detect_signals(ctx, full) == []
    partial = "Simulate x'' + 0.5 x' + 4 x = 0 with x(0) = 1 for 10 seconds."
    signals = detect_signals(await ctx_for(partial), partial)
    assert [s["signal"] for s in signals] == ["simulation_missing_initial_conditions"]
    assert "x'(0)" in signals[0]["question"] and "x(0)" not in signals[0]["question"].replace("x'(0)", "")


# I07 / I08 / I10 / I11 / I12 / T03-T06 / T10: structured mathematics -------------------------------------------------

def test_t03_function_values_and_cycle_are_verified():
    art = _solve(T03)
    assert art["status"] == "verified"
    res = _results(art)
    assert (res["T(1)"]["value"], res["T(2)"]["value"], res["T(4)"]["value"]) == ("4", "1", "2")
    assert res["cycle from 1"]["sequence"] == ["1", "4", "2", "1"]
    assert art["problem"]["kind"] == "structured" and "unaccounted" not in art["problem"]  # "40" words is no input
    checks = {c["name"].split(":")[0]: c["passed"] for c in art["verification"]["checks"]}
    assert checks["interpretation"] and checks["domain"] and checks["computation"] and checks["coverage"]


@pytest.mark.parametrize("question", [T04, T04_UNICODE])
def test_t04_value_and_identity_from_the_definition(question):
    art = _solve(question)
    assert art["status"] == "verified"
    res = _results(art)
    assert res["f(2)"]["value"] == "5"
    assert res["claim"]["status"] == "proved" and "(x^2 + 1) - x^2 = 1" in res["claim"]["text"]


def test_t05_false_universal_claim_is_disproved_with_a_checked_counterexample():
    art = _solve(T05)
    claim = _results(art)["claim"]
    assert art["status"] == "verified"
    assert claim["status"] == "disproved" and claim["counterexample"] == "40"
    assert "1681 = 41^2" in claim["text"]


@pytest.mark.parametrize("question, first, second", [
    (T06, ("Case A", "1681", "41^2"), ("Case B", "1763", "41 * 43")),
    (T06_REVERSED_RENAMED, ("Case B", "1763", "41 * 43"), ("Case A", "1681", "41^2")),
])
def test_t06_each_case_is_evaluated_with_its_own_binding(question, first, second):
    art = _solve(question)
    assert art["status"] == "verified"
    results = art["answer"]["results"]
    assert [(r["id"], r["value"], r["factorization"]) for r in results] == [first, second]


@pytest.mark.parametrize("question, expected", [
    ("Let g(t) = 2t - 3 if t < 0, and g(t) = t^2 otherwise. Compute g(-2), g(0) and g(3).",
     {"g(-2)": "-7", "g(0)": "0", "g(3)": "9"}),
    ("Let q(x) = x^2 - 1. Find q(q(2)).", {"q(q(2))": "8"}),
    ("Let h(x) = 3x + 2. Compute h(4) and 3*4 + 2.", {"h(4)": "14", "3*4+2": "14"}),
    ("Define S(k) = k/2 for even k and S(k) = 3k + 1 for odd k. Compute S(6) and S(-3).", {"S(6)": "3", "S(-3)": "-8"}),
])
def test_t10_branches_application_and_multiplication_generalise(question, expected):
    art = _solve(question)
    assert art["status"] == "verified"
    assert {k: v["value"] for k, v in _results(art).items()} == expected


def test_t10_an_argument_outside_the_domain_is_undefined_not_computed():
    art = _solve("Define g(n) = n - 1 for positive integers n. Compute g(1) and g(0).")
    res = _results(art)
    assert res["g(1)"]["value"] == "0"
    assert res["g(0)"]["status"] == "undefined" and "not in the domain" in res["g(0)"]["error"]
    assert art["status"] == "verified"  # "undefined" is the correct answer, confirmed by the domain check


@pytest.mark.parametrize("question, status", [
    ("Prove that x/x = 1 for every real x.", "disproved"),       # undefined at x = 0
    ("Prove that x/x = 1 for every real x != 0.", "proved"),
    ("Prove that n^3 - n is divisible by 6 for every integer n.", "proved"),  # residues modulo 6
    ("Prove that 2^n > n^2 for every positive integer n.", "disproved"),
])
def test_t10_domain_sensitive_and_universal_claims(question, status):
    art = _solve(question)
    claim = _results(art)["claim"]
    assert claim["status"] == status, claim
    assert art["status"] == "verified"


def test_t15_the_observed_wrong_interpretation_fails_interpretation_not_mathematics():
    from tribos.axiom import engine as E
    from tribos.axiom.definitions import check_structured, parse_structured
    from tribos.axiom.problem import ProblemSpec, normalize_math_text, parse_problem
    from tribos.axiom.verifier import verify

    # The faulty parse that was observed: T read as a number, T*n = n/2 and T*n = 3n + 1 solved as a system.
    wrong = ProblemSpec(text=T03, kind="solve", equations=["T*n = n/2", "T*n = 3*n + 1"])
    args = {"equations": wrong.equations}
    data = E.axiom_solve(**args)
    verdict = verify(wrong, "axiom_solve", args, data)
    assert verdict.status == "refuted"  # never an answer
    failed = [c.name for c in verdict.checks if c.passed is False]
    assert any(name.startswith("interpretation") for name in failed)
    assert "interpretation failed" in verdict.uncertainty[0] and "says nothing" in verdict.uncertainty[0]

    # An out-of-domain witness (-2/5 for a function on the positive integers) fails the domain check.
    params, _ = parse_structured(normalize_math_text(T03))
    forged = {"results": [{"id": "cycle from 1", "op": "orbit", "sequence": ["-2/5", "4", "2", "1"], "closed": True}]}
    domain = next(c for c in check_structured(params, forged) if c[0].startswith("domain"))
    assert domain[1] is False and "-2/5" in domain[3]

    # A question the structured reading cannot represent is rejected, not solved as a different problem.
    spec = parse_problem("Let T(n) = n/2 for even n and T(n) = 3n+1 for odd n. Solve T(n) = 5.")
    assert spec.kind == "unknown" and spec.unaccounted == ["function T"]


def test_t15_format_numerals_are_not_mathematical_inputs():
    from tribos.axiom.problem import parse_problem

    for q in (T03, T04, T05, T06):
        assert parse_problem(q).unaccounted == [], q
    # A single-formula definition used in another task is substituted, with the step recorded.
    spec = parse_problem("Let f(x) = x^2 + 1. Find the derivative of f(x).")
    assert spec.kind == "differentiate" and spec.expression == "(x**2 + 1)"
    assert any("substituted the definition" in a for a in spec.ambiguities)


# I09 / I13 / T16: the answer checker keeps each case's bindings ------------------------------------------------------

@pytest.mark.parametrize("answer", [
    "Case A: $n = 40$, so $n^2 + n + 41 = 1681 = 41^2$.\n\nCase B: $n = 41$, so $n^2 + n + 41 = 1763 = 41 \\cdot 43$.",
    "Case B: $n = 41$, so $n^2 + n + 41 = 1763$.\n\nCase A: $n = 40$, so $n^2 + n + 41 = 1681$.",
    "A: 1681 = 41 * 41\nB: 1763 = 41 * 43",
])
def test_case_local_bindings_never_contradict_each_other(answer):
    from tribos.verify.math_claims import audit_answer

    audit = audit_answer(answer, T06)
    assert audit.claims and all(c.status == "passed" for c in audit.claims), [(c.text, c.detail) for c in audit.claims]


def test_checker_still_catches_a_wrong_value_in_one_case_and_wrong_branch():
    from tribos.verify.math_claims import audit_answer

    bad = audit_answer("A: 1681 = 41 * 41\nB: 1763 = 41 * 41", T06)
    assert [c.status for c in bad.claims] == ["passed", "failed"]
    wrong_branch = audit_answer("T(1) = 1/2", T03)
    assert wrong_branch.claims[0].status == "failed" and "evaluates to 4" in wrong_branch.claims[0].detail
    checked = audit_answer("$f(2) = 2^2 + 1 = 5$ and $f(x) - x^2 = x^2 + 1 - x^2 = 1$.", T04)
    assert [c.status for c in checked.claims] == ["passed", "passed"]


def test_separate_conversations_with_the_same_expression_do_not_share_bindings():
    from tribos.verify.math_claims import audit_answer

    q1, q2 = "Evaluate n^2 + 1 for n = 3.", "Evaluate n^2 + 1 for n = 5."
    assert [c.status for c in audit_answer("$n^2 + 1 = 10$", q1).claims] == ["passed"]
    assert [c.status for c in audit_answer("$n^2 + 1 = 26$", q2).claims] == ["passed"]
    # n = 3 from the first conversation never leaks into the second: 10 is not accepted for n = 5 (the checker
    # leaves a false relation over the question's variable undecided, as a possible equation, never "passed").
    assert [c.status for c in audit_answer("$n^2 + 1 = 10$", q2).claims] != ["passed"]


def test_cases_run_in_parallel_keep_their_own_results():
    from tribos.axiom.agent import HybridPolicy, MathAgentConfig, local_executor, solve_math_problem

    async def both():
        cfg = MathAgentConfig()
        return await asyncio.gather(*(solve_math_problem(q, executor=local_executor(), policy=HybridPolicy(None, cfg), config=cfg)
                                      for q in (T06, T06_REVERSED_RENAMED, T06)))

    a, b, c = asyncio.run(both())
    assert a.answer["text"] == c.answer["text"] != b.answer["text"]
    assert {r["value"] for r in b.answer["results"]} == {"1681", "1763"}


# I17 / I18 / T07 / T09: output contracts ----------------------------------------------------------------------------

@pytest.mark.parametrize("question, payload", [
    (T07, "ALPHA\nBETA"),
    ("Output exactly these three lines, nothing else:\n\nred\n  green\nblue", "red\n  green\nblue"),
    ("Reply with exactly the following text and add nothing else:\n\nআমি বাংলায় গান গাই\nসুপ্রভাত", "আমি বাংলায় গান গাই\nসুপ্রভাত"),
    ("Copy the text below exactly:\n\nfoo bar\nbaz\n\nDo not add anything else.", "foo bar\nbaz"),
])
def test_literal_payloads_are_extracted_exactly(question, payload):
    from tribos.utils.output_contract import conform, extract, validate

    c = extract(question)
    assert c.literal == payload and c.pure_copy
    assert validate(payload, c) == []
    assert validate(payload.replace("\n", " "), c)  # a collapsed newline is a violation
    assert conform("\r\n" + payload.replace("\n", "\r\n") + "\n", c) == payload


def test_contract_limits_and_json_only():
    from tribos.utils.output_contract import conform, extract, validate

    c = extract(T06)
    assert c.exact_lines == 2 and c.strict_form
    assert validate("A: 1681 = 41 * 41\nB: 1763 = 41 * 43", c) == []
    assert validate("A: 1681\nB: 1763\n\n**Verification**: both checked", c)
    assert extract(T03).max_words == 40 and validate(" ".join(["w"] * 41), extract(T03))
    j = extract("Return only valid JSON with keys a and b where a=1 and b=2.")
    assert j.json_only and conform('```json\n{"a": 1, "b": 2}\n```', j) == '{"a": 1, "b": 2}'


@pytest.mark.asyncio
async def test_t07_literal_copy_runs_nothing_and_returns_the_exact_payload(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry(T07, thread_id="t-literal", enable_web_search=True)
    assert res.response == "ALPHA\nBETA"
    assert calls == []  # no literature, web, solver or any other tool
    assert res.framework_used == "literal-direct"
    assert res.execution_artifacts["output_contract"]["violations"] == []
    assert res.task_status["requested_operation"] == "literal_copy"
    assert not res.verification_report.get("defects")


# I04 / I06 / T08 / T18: retrieval only for an information need; Search off everywhere ---------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("question", [T03, T05, T06, T01])
async def test_self_contained_requests_make_no_external_retrieval_with_search_on(monkeypatch, tmp_path, question):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    await orch.execute_inquiry(question, thread_id="t-self", enable_web_search=True)
    assert not {name for name, _ in calls} & EXTERNAL_TOOLS


@pytest.mark.asyncio
async def test_search_off_blocks_literature_as_well_as_web(monkeypatch, tmp_path):
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry("What mechanisms make bacterial biofilms tolerant to antibiotics? Cite papers.",
                                     thread_id="t-off", enable_web_search=False)
    assert not {name for name, _ in calls} & EXTERNAL_TOOLS
    assert res.query_context["decisions"]["archivon"]["run"] is False if "decisions" in (res.query_context or {}) else True
    on_orch, on_calls = make_offline_orchestrator(monkeypatch, tmp_path / "on")
    await on_orch.execute_inquiry("What mechanisms make bacterial biofilms tolerant to antibiotics? Cite papers.",
                                  thread_id="t-on", enable_web_search=True)
    assert called(on_calls, "archivon_literature_search") or called(on_calls, "lithoscribe_literature_synthesis")


@pytest.mark.asyncio
async def test_search_off_is_enforced_at_the_tool_layer_for_every_networked_tool():
    from tribos.tools.registry import AdapterType
    from tribos.tools.reliability import execute_with_policies, external_retrieval_blocked

    ran: list[str] = []

    async def call():
        ran.append("called")
        return SimpleNamespace(success=True)

    registry = SimpleNamespace(get_entry=lambda name: SimpleNamespace(name=name, adapter_type=AdapterType.DIRECT_REST,
                                                                      timeout_seconds=5.0, input_schema=None))
    with external_retrieval_blocked("Search is off for this turn"):
        res = await execute_with_policies(registry, "archivon_recommend", {"query": "x"}, call)
    assert ran == [] and res.success is False and res.metadata["skipped_by_policy"] == "search_off"
    local = SimpleNamespace(get_entry=lambda name: SimpleNamespace(name=name, adapter_type=AdapterType.LOCAL_COMPUTE))
    with external_retrieval_blocked("Search is off for this turn"):
        await execute_with_policies(local, "axiom_simplify", {"expression": "x"}, call)
    assert ran == ["called"]  # local computation is never blocked


def test_literature_search_text_is_the_subject_not_the_instructions():
    from tribos.agents.authoritative_orchestrator import literature_subject

    subject = literature_subject("How does strain change graphene's thermal conductivity? Answer in at most 30 words.")
    assert "30" not in subject and "words" not in subject and "graphene" in subject
    assert "Case" not in literature_subject("Compare drag models. Case A: v = 3. Case B: v = 5.")


@pytest.mark.asyncio
async def test_unrelated_keyword_matches_are_dropped_not_padded_to_three():
    from tribos.archivon import ArchivonClients, ArchivonEngine, CrossrefIntegrityClient

    court = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/court", "title":
             "National Federation of Independent Business v. Sebelius: two independent cases", "publication_year": 2013,
             "cited_by_count": 50, "type": "article", "abstract_inverted_index": {"court": [0], "cases": [1]}}
    biofilm = {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.1/bio", "title":
               "Antibiotic tolerance mechanisms of bacterial biofilms", "publication_year": 2020, "cited_by_count": 900,
               "type": "article", "abstract_inverted_index": {"biofilms": [0], "tolerance": [1], "antibiotic": [2]}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.openalex.org/works" in str(request.url):
            return httpx.Response(200, json={"results": [court, biofilm]})
        if "api.crossref.org" in str(request.url):
            return httpx.Response(200, json={"message": {"items": []}})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    engine = ArchivonEngine(clients=ArchivonClients(transport=transport), integrity_client=CrossrefIntegrityClient(transport=transport))
    res = await engine.literature_search("bacterial biofilm antibiotic tolerance mechanisms", max_results=8)
    titles = [a["title"] for a in res["graded_articles"]]
    assert titles == ["Antibiotic tolerance mechanisms of bacterial biofilms"]
    generic = await engine.literature_search("two independent cases", max_results=8)
    assert generic["graded_articles"] == [] and generic["total_found"] == 0


# I03 / I05 / I14 / I19: truthful reasons, bounded escalation, task-aware graders, honest confidence ------------------

def _ctx(question: str):
    from tribos.agents.evidence_need import assess_evidence_need
    from tribos.agents.query_context import QueryContext
    from tribos.agents.query_planner import decide_builtin_sources

    ctx = QueryContext(raw_query=question, clean_query=question, enable_web_search=True)
    ctx.evidence_need = assess_evidence_need(question, ctx)
    decide_builtin_sources(ctx)
    return ctx


def test_computation_skip_reason_is_truthful():
    reason = _ctx(T06).decisions["calcula"].reason
    assert "no numerical computation requested" not in reason and "Axiom" in reason


def test_a_self_contained_task_is_not_escalated_on_route_uncertainty_alone():
    from tribos.agentic.router import escalation_triggers

    state = SimpleNamespace(ctx=_ctx(T06), bag={"routing": {"confidence": 0.2}}, artifacts={}, sub_questions=[],
                            core_phase_status=lambda: {"status": "ok"})
    assert escalation_triggers(state) == []
    open_state = SimpleNamespace(ctx=_ctx("What mechanisms make bacterial biofilms tolerant to antibiotics?"),
                                 bag={"routing": {"confidence": 0.2}}, artifacts={}, sub_questions=[],
                                 core_phase_status=lambda: {"status": "ok"})
    assert any("uncertain route" in t for t in escalation_triggers(open_state))


def test_completion_graders_respect_the_task():
    from tribos.agents.deliverables import assess
    from tribos.verify.verifier import TribosVerifier

    report = TribosVerifier().verify_response(T06, "A: 1681 = 41 * 41\nB: 1763 = 41 * 43", {}, query_context=_ctx(T06))
    assert not [d for d in report.defects if d.category == "COMPLETION"], report.defects
    items = assess("Prove or disprove that n^2+n+41 is prime for every n >= 0. Determine whether the claim is proved.",
                   "False: at n = 40 the value is 1681 = 41^2.")
    assert [i["status"] for i in items] == ["addressed"]


def test_benchmark_precision_is_never_attached_to_an_unverified_answer():
    from tribos.agentic.math_agent import _evidence_xml

    conf = {"p_correct": 0.25, "n": 2}
    assert "benchmark_precision" not in _evidence_xml({"status": "unverified", "confidence": conf, "answer": {}, "problem": {}})
    assert "benchmark_precision" in _evidence_xml({"status": "verified", "confidence": conf, "answer": {}, "problem": {}})


# Mathematical reasoning steps: generated from the exact computation, every line checkable ----------------------------

def test_structured_results_carry_exact_derivation_steps():
    t03 = _results(_solve(T03))
    assert t03["cycle from 1"]["steps"][:3] == ["1 is odd, so T(1) = 3*1 + 1 = 4", "4 is even, so T(4) = 4/2 = 2",
                                                "2 is even, so T(2) = 2/2 = 1"]
    t06 = _results(_solve(T06))
    assert t06["Case B"]["steps"] == ["With n = 41: n^2 + n + 41 = 41^2 + 41 + 41 = 1681 + 41 + 41 = 1763",
                                      "1763 = 41 * 43, where 41, 43 are prime"]
    t05 = _results(_solve(T05))["claim"]["steps"]
    assert t05[0] == "With n = 40: n^2 + n + 41 = 40^2 + 40 + 41 = 1600 + 40 + 41 = 1681"
    assert "one counterexample refutes the universal statement" in t05[-1]
    piecewise = _results(_solve("Let g(t) = 2t - 3 if t < 0, and g(t) = t^2 otherwise. Compute g(0) and g(-2)."))
    assert piecewise["g(0)"]["steps"] == ["0 < 0 is false, so the remaining branch applies, so g(0) = 0^2 = 0"]
    assert piecewise["g(-2)"]["steps"] == ["-2 < 0, so g(-2) = 2*(-2) - 3 = -7"]


def test_the_writer_receives_the_checked_derivation():
    from tribos.agentic.math_agent import _evidence_xml

    xml = _evidence_xml(_solve(T06))
    assert "<math_derivation" in xml and "1600 + 40 + 41 = 1681" in xml


def test_a_disproof_delivers_a_requested_proof_of_a_false_claim():
    from tribos.agents.deliverables import assess

    items = assess(T05, "False. At n = 40, n^2 + n + 41 = 1681 = 41^2, which is composite; n = 40 is a counterexample.")
    assert items and all(i["status"] == "addressed" for i in items), items


# I23 / T19: the optional formal checker -------------------------------------------------------------------------------

def _real_lean() -> bool:
    from tribos.verify.formal.runner import find_lean

    found = find_lean()
    return bool(found) and not str(found["argv"][-1]).endswith(".py")


@pytest.mark.skipif(not _real_lean(), reason="no Lean installation configured (TRIBOS_LEAN_PATH or lean on PATH)")
def test_a_real_lean_installation_checks_proofs_and_never_accepts_sorry():
    from tribos.verify.formal.runner import check_lean, clear_cache

    clear_cache()
    assert check_lean("theorem odd_add_odd (a b : Nat) (ha : a % 2 = 1) (hb : b % 2 = 1) : (a + b) % 2 = 0 := by omega")["status"] == "verified"
    assert check_lean("theorem wrong : 2 + 2 = 5 := rfl")["status"] == "failed"
    assert check_lean("theorem gap (n : Nat) : n + 0 = n := by sorry")["status"] != "verified"


def test_core_lean_formalisations_use_core_names_without_changing_the_statement():
    from tribos.verify.formal.prove import CORE_LEAN_ENV, core_notation

    code = "import Mathlib\ntheorem s (m n : ℕ) (k : ℤ) : m + n = n + m := by omega"
    assert core_notation(code) == "theorem s (m n : Nat) (k : Int) : m + n = n + m := by omega"
    assert "omega" in CORE_LEAN_ENV and "ring" in CORE_LEAN_ENV  # usable vs unavailable tactics are both named


@pytest.mark.skipif(not _real_lean(), reason="no Lean installation configured (TRIBOS_LEAN_PATH or lean on PATH)")
def test_real_lean_accepts_mathlib_notation_after_the_core_rewrite_and_reports_utf8():
    from tribos.verify.formal.prove import core_notation
    from tribos.verify.formal.runner import check_lean, clear_cache

    clear_cache()
    code = "import Mathlib\ntheorem s (m n : ℕ) (hm : m % 2 = 1) (hn : n % 2 = 1) : (m + n) % 2 = 0 := by omega"
    assert check_lean(core_notation(code))["status"] == "verified"
    failed = check_lean("theorem t (m : Nat) : m + 1 = m := by simp")
    assert failed["status"] == "failed" and "⊢" in failed["error"]
