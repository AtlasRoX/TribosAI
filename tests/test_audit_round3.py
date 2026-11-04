"""Audit round 3 (I24-I43, T21-T45): regressions through the production components.

The mathematics runs through parse_problem -> the verified mathematics agent -> the independent verifier; failure paths
run through AuthoritativeOrchestrator.execute_inquiry with every model call failing (the offline orchestrator) and the
real Axiom computations registered. Oracles are independent: exact values, sets and statuses stated by the audit.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.fakes import make_offline_orchestrator

CONTRACT = "Return exactly three lines, one result per input in the requested order. Add nothing else."
ONE_LINE = "Give the complete solution set on one line in set notation. Add nothing else."
T22 = f"Let g be a function on the positive integers with g(n) = n/2 if n is even and g(n) = 5n + 3 if n is odd. Evaluate g(3), g(8), g(11). {CONTRACT}"
T23 = f"Let h be defined only for positive integers by h(n) = n/2 if n is even and h(n) = 7n - 1 if n is odd. Evaluate h(0), h(1), h(6). {CONTRACT}"
T24 = f"Let q: {{1, 2, 3, ...}} → ℤ be defined by q(n) = n² + 4. Evaluate q(0), q(−2), q(3). {CONTRACT}"
T24_INT = f"Let q: ℤ → ℤ be defined by q(n) = n² + 4. Evaluate q(0), q(−2), q(3). {CONTRACT}"
T25 = f"Let T be defined on the positive integers by T(n) = n/2 for even n and T(n) = 3n + 1 for odd n. Evaluate T(40), T(41), T(42). {CONTRACT}"
T42 = ("Let P(s) = (s - 1/4)(s - 3/4), where s is complex.\n\nProve P(1-s) = P(s), find all its zeros, and determine "
       "whether reflection symmetry about Re(s)=1/2 alone forces every zero onto that line.\n\nGive the derivations and "
       "check the roots. Explain precisely what this establishes about a symmetry-only argument and what it does not "
       "establish about the Riemann zeta function.")
T34 = ("Make a serious, sustained attempt to prove or disprove the Riemann Hypothesis:\n\nEvery zero s of the analytically "
       "continued Riemann zeta function with 0 < Re(s) < 1 satisfies Re(s) = 1/2.\n\nBriefly acknowledge its accepted "
       "mathematical status, then devote the response to an actual mathematical investigation.\n\nProvide enough detail to "
       "assess the mathematics. There is no 150-word limit.")


def _math(question: str) -> dict[str, Any]:
    from tribos.axiom.agent import HybridPolicy, MathAgentConfig, local_executor, solve_math_problem
    from tribos.axiom.problem import parse_problem

    cfg = MathAgentConfig()
    run = asyncio.run(solve_math_problem(parse_problem(question), executor=local_executor(),
                                         policy=HybridPolicy(None, cfg), config=cfg))
    return run.to_dict()


def _rendered(question: str) -> str | None:
    from tribos.axiom.render import render_verified_answer
    from tribos.utils.output_contract import extract

    return render_verified_answer(question, _math(question), extract(question))


# I24 / I27 / T22-T25: domains, undefined inputs, ordered results, deterministic rendering --------------------------

@pytest.mark.parametrize("question, lines", [
    (T22, ["g(3) = 18", "g(8) = 4", "g(11) = 58"]),
    (T23, ["h(0) is undefined: 0 is not in the domain of h (positive integers)", "h(1) = 6", "h(6) = 3"]),
    (T24, ["q(0) is undefined: 0 is not in the domain of q (positive integers)",
           "q(-2) is undefined: -2 is not in the domain of q (positive integers)", "q(3) = 13"]),
    (T24_INT, ["q(0) = 4", "q(-2) = 8", "q(3) = 13"]),  # the domain-changing control
    (T25, ["T(40) = 20", "T(41) = 124", "T(42) = 21"]),
])
def test_t22_t25_verified_values_render_exactly_in_the_requested_lines(question, lines):
    assert _rendered(question) == "\n".join(lines)


def test_t25_inputs_are_independent_of_order():
    reordered = T25.replace("Evaluate T(40), T(41), T(42).", "Evaluate T(42), T(40), T(41).")
    assert _rendered(reordered) == "T(42) = 21\nT(40) = 20\nT(41) = 124"


def test_i24_a_payload_that_lost_the_domain_fails_against_the_question():
    from tribos.axiom.definitions import check_structured, run_structured

    forged = {"definitions": [{"name": "h", "parameter": "n", "domain": "integer",
                               "branches": [{"expression": "n/2", "condition": "even"}, {"expression": "7*n - 1", "condition": "odd"}]}],
              "tasks": [{"id": "h(0)", "op": "evaluate", "expression": "h(0)"}]}
    data = run_structured(forged["definitions"], forged["tasks"])
    assert data["results"][0]["value"] == "0"  # the forged payload computes the out-of-domain value
    checks = {name.split(":")[0]: passed for name, passed, *_ in check_structured(forged, data, T23)}
    assert checks["domain"] is False  # re-read from the question itself, so it cannot pass against itself


# I31 / I32 / T26-T31: solution sets ----------------------------------------------------------------------------------

@pytest.mark.parametrize("equation, expected", [
    ("Solve x^2 + 1 = 0 over the real numbers.", "∅"),
    ("Solve x^2 + 1 = 0 over the complex numbers.", "{−i, i}"),
    ("Solve (x^2 - 1)/(x - 1) = 2 over the real numbers.", "∅"),
    ("Solve (x^2 - 1)/(x - 1) = x + 1 over the real numbers.", "ℝ ∖ {1}"),
    ("Solve (x - 2)^2 = x^2 - 4x + 4 over the real numbers.", "ℝ"),
    ("Solve (x - 2)^2 = x^2 - 4x + 5 over the real numbers.", "∅"),
    ("Solve sqrt(x + 2) = x over the real numbers.", "{2}"),
])
def test_t26_t31_complete_solution_sets_in_set_notation(equation, expected):
    assert _rendered(f"{equation} {ONE_LINE}") == expected


def test_t29_t30_infinite_sets_are_never_no_solutions_and_wrong_sets_are_rejected():
    from tribos.axiom.engine import axiom_solve
    from tribos.axiom.problem import parse_problem
    from tribos.axiom.verifier import verify

    for question, wrong in (("Solve (x^2 - 1)/(x - 1) = x + 1 over the real numbers.", "Reals"),
                            ("Solve (x - 2)^2 = x^2 - 4x + 4 over the real numbers.",
                             "Union(Interval.open(-oo, 2), Interval.open(2, oo))")):
        spec = parse_problem(question)
        args = {"equations": spec.expression, "variables": "x", "domain": "real"}
        data = axiom_solve(**args)
        good = verify(spec, "axiom_solve", args, data)
        assert good.status == "verified" and "no solutions" not in good.answer["text"]
        assert verify(spec, "axiom_solve", args, dict(data, solution_set=wrong)).status != "verified"


# I27 / I28 / I43 / T37: writer failure -------------------------------------------------------------------------------

def _real_axiom_tools() -> dict[str, Any]:
    from tribos.axiom.definitions import axiom_structured
    from tribos.axiom.engine import axiom_solve
    from tribos.axiom.schemas import AxiomSolveInput, AxiomStructuredInput

    return {"axiom_structured": (AxiomStructuredInput, lambda kw: axiom_structured(**kw)),
            "axiom_solve": (AxiomSolveInput, lambda kw: axiom_solve(**kw))}


@pytest.mark.asyncio
@pytest.mark.parametrize("question, expected", [
    (T23, "h(0) is undefined: 0 is not in the domain of h (positive integers)\nh(1) = 6\nh(6) = 3"),
    (f"Solve x^2 + 1 = 0 over the real numbers. {ONE_LINE}", "∅"),
    (f"Solve (x^2 - 1)/(x - 1) = x + 1 over the real numbers. {ONE_LINE}", "ℝ ∖ {1}"),
])
async def test_t37_sufficient_validated_results_survive_a_failing_writer_in_the_requested_format(monkeypatch, tmp_path, question, expected):
    orch, _calls = make_offline_orchestrator(monkeypatch, tmp_path, extra_tools=_real_axiom_tools())  # every LLM call fails
    res = await orch.execute_inquiry(question, thread_id="t-r3", enable_web_search=False, framework="auto")
    assert res.response == expected
    assert res.task_status["task_status"] == "completed"
    assert res.task_status["requested_operation"] == "mathematical_answer"
    assert res.execution_artifacts["output_contract"]["violations"] == []


@pytest.mark.asyncio
async def test_t37_zero_results_is_an_honest_failed_run_without_a_prompt_echo_or_an_invented_cap(monkeypatch, tmp_path):
    orch, _calls = make_offline_orchestrator(monkeypatch, tmp_path)
    res = await orch.execute_inquiry(T34, thread_id="t-r3-fail", enable_web_search=False, framework="auto")
    assert res.task_status["task_status"] == "failed"
    assert "No answer could be produced" in res.response
    assert "Riemann" not in res.response and "sustained" not in res.response  # the request is not shown as results
    assert not (res.execution_artifacts.get("output_contract") or {}).get("max_words")  # "no 150-word limit"


# I29 / T35: negated, removed, replaced and quoted limits ---------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("Provide enough detail to assess the mathematics. There is no 150-word limit.", {}),
    ("The 150-word limit no longer applies.", {}),
    ("You are not limited to 200 words.", {}),
    ("There is no word limit.", {}),
    ("Sin límite de 150 palabras. Explica la demostración.", {}),
    ('Classify the instruction "answer in at most 50 words" as formatting.', {}),
    ("Answer in at most 150 words. Later: remove the previous 150-word limit and write 220-250 words.",
     {"min_words": 220, "max_words": 250}),
    ("Answer in at most 100 words. Actually, make it at most 200 words.", {"max_words": 200}),
    ("Answer in at most 150 words.", {"max_words": 150}),
    ("Don't use jargon and keep it under 50 words.", {"max_words": 50}),
    ("Give each case on one line.", {}),
])
def test_t35_only_imposed_limits_are_enforced(question, expected):
    from tribos.utils.output_contract import extract

    c = extract(question)
    got = {k: getattr(c, k) for k in ("max_words", "min_words", "exact_words", "exact_lines") if getattr(c, k) is not None}
    assert got == expected
    if not expected and "limit" in question.lower():
        assert c.inactive  # the removed limit is recorded as not imposed, with its reason


def test_t35_a_word_range_is_validated_on_both_sides():
    from tribos.utils.output_contract import extract, validate

    c = extract("Write between 220 and 250 words.")
    assert validate(" ".join(["w"] * 200), c) and validate(" ".join(["w"] * 260), c)
    assert validate(" ".join(["w"] * 230), c) == []


# I30 / T36: statement roles ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sentence, role, kind", [
    ("There is no 150-word limit.", "instruction", None),
    ("The writer failed: HTTP 500 / Failed to generate completions.", "error", None),
    ("There is no real solution of x^2 + 1 = 0.", "mathematical", None),
    ("No accepted proof of the Riemann Hypothesis is known.", None, "status"),
    ("There are no published studies of this alloy at 4 K.", None, "absence"),
    ("The cited paper does not mention fatigue.", None, "absence"),
])
def test_t36_only_applicable_statements_become_factual_claims(sentence, role, kind):
    from tribos.verify.verifier import TribosVerifier, statement_role

    assert statement_role(sentence) == role
    if role is None:
        assert TribosVerifier._classify_claim(sentence) == kind


def test_t36_an_echoed_instruction_is_not_a_claim_but_answer_prose_is():
    from tribos.verify.verifier import statement_role

    q = "Provide enough detail to assess the mathematics."
    assert statement_role("Provide enough detail to assess the mathematics.", q) == "instruction"
    assert statement_role("Use of the method was reported in 2019.", q) is None


# I33 / T39: formal statement correspondence --------------------------------------------------------------------------

@pytest.mark.parametrize("question, statement, bad", [
    (T34, "theorem riemann_hypothesis : False", True),
    ("Prove that for every natural number n, n + 0 = n.", "theorem t : True", True),
    ("Prove that for every natural number n, n + 0 = n.", "theorem t (n : Nat) (h : n + 0 = n) : n + 0 = n", True),
    ("Prove that 17 * 23 = 391.", "theorem t : 2 + 2 = 4", True),
    ("Prove that for every natural number n, n + 0 = n.", "theorem t (n : Nat) : n + 0 = n", False),
    ("Prove that 17 * 23 = 391.", "theorem t : 17 * 23 = 391", False),
    ("Show there is no natural number n with n + 1 = 0.", "theorem t (n : Nat) (h : n + 1 = 0) : False", False),
])
def test_t39_the_lean_statement_must_encode_the_question(question, statement, bad):
    from tribos.verify.formal.correspondence import statement_issues

    assert bool(statement_issues(question, statement, mathlib=False)) is bad


def test_t39_a_question_core_lean_cannot_state_is_reported_without_a_model_call(monkeypatch):
    from tribos.verify.formal import prove

    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    asked: list[str] = []

    async def complete(system: str, user: str) -> str:
        asked.append(user)
        return "```lean\ntheorem riemann_hypothesis : False := by\n  intro h\n  exact h\n```"

    art = asyncio.run(prove.formalise_and_check(T34, complete, mathlib=False))
    assert art["status"] == "not_formalizable" and art["statement"] == "" and asked == []


def test_t39_a_mismatched_statement_is_repaired_or_rejected_never_checked(monkeypatch):
    from tribos.verify.formal import prove

    monkeypatch.setattr(prove, "find_lean", lambda: {"argv": ["lean"], "cwd": None, "kind": "lean"})
    monkeypatch.setattr(prove, "check_lean", lambda code: {"status": "verified", "messages": []})
    monkeypatch.setattr(prove, "get_int", lambda name: 1)
    replies = iter(["```lean\ntheorem t : True := trivial\n```",
                    "```lean\ntheorem t (n : Nat) : n + 0 = n := by simp\n```"])

    async def complete(system: str, user: str) -> str:
        return next(replies)

    art = asyncio.run(prove.formalise_and_check("Prove that for every natural number n, n + 0 = n.", complete, mathlib=False))
    assert [a["status"] for a in art["attempts"]] == ["mismatch", "verified"]
    assert art["statement"] == "theorem t (n : Nat) : n + 0 = n"


# I35 / I36 / I38: requested operation and information need -----------------------------------------------------------

@pytest.mark.parametrize("question, generation", [
    ("Prove or disprove the Riemann Hypothesis. Acknowledge its accepted status.", False),
    ("What is the current accepted status of the Riemann Hypothesis? Include the source URL.", False),
    ("Is Goldbach's conjecture proved?", False),
    ("Explain the null hypothesis in a t-test.", False),
    ("Critique this proposed proof method for the Collatz conjecture.", False),
    ("Propose new hypotheses for why bacterial biofilms tolerate antibiotics.", True),
    ("Generate three testable conjectures about the gaps between consecutive primes.", True),
    ("What hypotheses explain the anomalous precession of Mercury's perihelion?", True),
])
def test_t32_t34_named_hypotheses_are_subjects_not_generation_requests(question, generation):
    from tribos.agentic.router import rule_decision, routing_signals

    assert routing_signals(question, None).hypothesis is generation
    assert (rule_decision(question, None).rule == "hypothesis_generation") is generation


@pytest.mark.parametrize("question, kind, level", [
    ("What is the status of the Collatz conjecture?", "current", "required"),
    ("Has the twin prime conjecture been proved?", "current", "required"),
    (T34, "current", "optional"),  # the status is one part; the mathematics itself stays self-contained
    ("Prove that the sum of two odd integers is even.", "self_contained", "none"),
])
def test_t38_status_needs_a_source_derivation_does_not(question, kind, level):
    from tribos.agents.evidence_need import assess_evidence_need

    need = assess_evidence_need(question)
    assert (need.kind, need.level) == (kind, level)


# I34 / T38: planner names and registry ---------------------------------------------------------------------------------

def test_t38_an_invented_tool_name_runs_under_the_registered_name_only_when_allowed():
    from tribos.agentic.plan_graph import PlanGraph, PlanNode, validate_plan
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    on = SimpleNamespace(enable_web_search=True, evidence_need=None, excluded_modules=set(), extras={}, decisions={},
                         source_allowlist=None)
    off = SimpleNamespace(**{**on.__dict__, "enable_web_search": False})
    for ctx, runs in ((on, True), (off, False)):
        graph = PlanGraph(nodes=[PlanNode(id="n1", tool="web_search", args={"query": "Riemann Hypothesis status"})])
        out = validate_plan(graph, reg, ctx)
        if runs:
            assert [n.tool for n in out.nodes] == ["websurfer_search"]
        else:
            assert not out.nodes and "Search is off" in out.rejected[0]["reason"]


# I37: critics ------------------------------------------------------------------------------------------------------------

def test_i37_additions_outside_a_fixed_form_are_not_revision_requests():
    from tribos.agentic.topologies import DebatePhase

    state = SimpleNamespace(query="What is the status of the Riemann Hypothesis? Answer in one sentence.")
    critiques = [{"severity": "medium", "issue": "Add a numerical verification of the first zeros"},
                 {"severity": "high", "issue": "The claim that it was proved in 2018 is wrong"}]
    assert [c["severity"] for c in DebatePhase._in_scope(state, critiques)] == ["high"]
    free = SimpleNamespace(query="Discuss the status of the Riemann Hypothesis.")
    assert len(DebatePhase._in_scope(free, critiques)) == 2


# I40 / T40: final-revision binding ---------------------------------------------------------------------------------------

def test_t40_counter_evidence_about_dropped_claims_becomes_history():
    from tribos.agentic.counter_evidence import reconcile_with_answer

    art = {"conflicts": [
        {"claim": "The distribution of prime numbers shows structured and random characteristics", "label": "contradicts"},
        {"claim": "The Riemann Hypothesis remains an unsolved Millennium Prize Problem", "label": "neutral"},
    ]}
    reconcile_with_answer(art, "The Riemann Hypothesis remains an unsolved Millennium Prize Problem (Clay Mathematics Institute).")
    assert [r["label"] for r in art["conflicts"]] == ["neutral"]
    assert art["history"][0]["label"] == "contradicts" and art["history_note"]


# I39 / T43: a link delivers a requested URL ------------------------------------------------------------------------------

def test_t43_a_link_in_the_answer_delivers_the_requested_source_url():
    from tribos.agents.deliverables import assess

    q = "What is the current accepted status of the Riemann Hypothesis? Answer in one sentence and include the source URL."
    linked = assess(q, "It remains unproven ([CMI](https://www.claymath.org/millennium/riemann-hypothesis/)).")
    assert {d["item"]: d["status"] for d in linked}["source URL"] == "addressed"
    assert {d["item"]: d["status"] for d in assess(q, "It remains unproven.")}["source URL"] == "missing"


# T42: bounded proof execution ---------------------------------------------------------------------------------------------

def test_t42_symmetry_identity_zeros_and_the_line_are_derived_and_checked():
    art = _math(T42)
    assert art["status"] == "verified"
    results = {r["op"]: r for r in art["answer"]["results"]}
    assert results["claim"]["status"] == "proved"
    zeros = results["zeros"]
    assert zeros["zeros"] == ["1/4", "3/4"] and zeros["complete"] and zeros["off_line"] == ["1/4", "3/4"]
    assert zeros["reflection_symmetric"] is True  # symmetric about Re(s) = 1/2, yet no zero on the line


def test_t42_a_forged_zero_list_fails_the_reconstruction():
    from tribos.axiom.definitions import check_structured, parse_structured, run_structured
    from tribos.axiom.problem import normalize_math_text

    params, _ = parse_structured(normalize_math_text(T42))
    data = run_structured(params["definitions"], params["tasks"])
    zeros = next(r for r in data["results"] if r["op"] == "zeros")
    zeros.update(zeros=["1/4", "1/2"], multiplicities=[1, 1])
    computation = next(p for name, p, *_ in check_structured(params, data, T42) if name.startswith("computation"))
    assert computation is False


# I26 / T45: bounded transient recovery -------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("statuses, final, attempts", [
    ([500, 500, 200], 200, 3),  # a burst of provider faults, then recovery
    ([400], 400, 1),  # a client error is not retried
    ([500, 500, 500, 500], 500, 3),  # bounded: at most TRIBOS_LLM_RETRY_ATTEMPTS attempts
])
async def test_t45_transient_provider_faults_are_retried_within_bounds(statuses, final, attempts):
    from tribos.utils.llm.provider_retry import RetryingAsyncTransport

    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(1)
        return httpx.Response(statuses[min(len(sent), len(statuses)) - 1], headers={"nvcf-reqid": f"r{len(sent)}"})

    transport = RetryingAsyncTransport(httpx.MockTransport(handler), attempts=3, deadline_s=5.0, base_delay_s=0.01)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await client.post("https://integrate.api.nvidia.com/v1/chat/completions", json={"m": 1})
    assert res.status_code == final and len(sent) == attempts


def test_t45_the_sdk_retry_is_off_where_the_transport_retries(monkeypatch):
    from tribos.utils.llm.llm_factory import get_llm

    monkeypatch.setenv("TRIBOS_ALLOWED_MODELS", "nvidia/nemotron-3.5-super-vl-120b-a12b")  # NVIDIA is off the catalog; the NIM path stays for operators who allow a model
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-not-a-real-key")
    llm = get_llm(model_name="nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert llm.max_retries == 0 and llm.http_async_client is not None


def test_t45_a_status_error_the_transport_retried_is_not_sent_again_by_the_stream_layer(monkeypatch):
    from tribos.utils.llm.llm_factory import get_llm
    from tribos.utils.llm.provider_retry import already_retried

    monkeypatch.setenv("TRIBOS_ALLOWED_MODELS", "nvidia/nemotron-3.5-super-vl-120b-a12b")  # NVIDIA is off the catalog; the NIM path stays for operators who allow a model
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-not-a-real-key")
    llm = get_llm(model_name="nvidia/nemotron-3.5-super-vl-120b-a12b")
    status_error = type("InternalServerError", (Exception,), {})()
    mid_stream = type("ReadError", (Exception,), {})()
    assert already_retried(llm, status_error) and not already_retried(llm, mid_stream)


# I25 / T38: a definition with a missing or renamed parameter -------------------------------------------------------------

def test_t38_a_missing_parameter_is_repaired_only_when_unambiguous_and_the_domain_is_kept():
    import pydantic

    from tribos.axiom.schemas import AxiomStructuredInput

    task = {"id": "q(3)", "op": "evaluate", "expression": "q(3)"}
    base = {"name": "q", "domain": "positive_integer", "branches": [{"expression": "n**2 + 4", "condition": ""}]}
    renamed = AxiomStructuredInput(definitions=[{**base, "variable": "n"}], tasks=[task])
    inferred = AxiomStructuredInput(definitions=[base], tasks=[task])
    for parsed in (renamed, inferred):
        d = parsed.definitions[0]
        assert d.parameter == "n" and d.domain == "positive_integer"
    with pytest.raises(pydantic.ValidationError, match="state the parameter"):
        AxiomStructuredInput(definitions=[{**base, "branches": [{"expression": "n**2 + m", "condition": ""}]}], tasks=[task])


# T41: a valid disproof, an invalid out-of-domain witness, and a correctly undefined input --------------------------------

def test_t41_an_out_of_domain_counterexample_is_not_a_disproof():
    from tribos.axiom.definitions import check_structured

    params = {"definitions": [{"name": "h", "parameter": "n", "domain": "positive_integer",
                               "branches": [{"expression": "n/2", "condition": "even"}, {"expression": "7*n - 1", "condition": "odd"}]}],
              "tasks": [{"id": "claim", "op": "claim", "lhs": "h(n)", "relation": ">", "rhs": "0", "variable": "n",
                         "domain": "positive_integer", "conditions": [], "statement": "h(n) > 0 for every positive integer n"}]}
    forged = {"results": [{"id": "claim", "op": "claim", "status": "disproved", "counterexample": "0", "detail": "h(0) = 0"}]}
    domain = next(p for name, p, *_ in check_structured(params, forged) if name.startswith("domain"))
    assert domain is False  # n = 0 lies outside the positive integers: no disproof
    undefined = _math(T23)
    assert undefined["status"] == "verified"  # "h(0) is undefined" is the correct, complete answer to that input


# I41 / T43: a sourced status claim is judged against the page it cites ---------------------------------------------------

def test_t43_a_status_claim_is_bound_to_the_cited_page_not_a_record_sharing_its_words():
    from tribos.verify.verifier import TribosVerifier, _Doc

    other = _Doc("DOI:10.5281/zenodo.1", "a proposed proof of the riemann hypothesis; the riemann hypothesis remains an open problem.", None, "")
    cmi = _Doc("web:claymath", "the riemann hypothesis is a millennium prize problem; it remains unsolved.", None, "",
               "https://www.claymath.org/millennium/riemann-hypothesis/")
    claim = "The Riemann Hypothesis remains unsolved: https://www.claymath.org/millennium/riemann-hypothesis"
    status, _reason, doc, _pos = TribosVerifier()._status_verdict(claim, [other, cmi])
    assert status == "supported" and doc is cmi
    silent = _Doc("web:claymath", "top_page: the clay mathematics institute funds research.", None, "", cmi.url)
    status, reason, doc, _pos = TribosVerifier()._status_verdict(claim, [other, silent])
    assert status == "unsupported" and doc is silent and "does not state" in reason  # never rescued by another record
    badge = _Doc("web:claymath", "top_page: riemann hypothesis. unsolved. the riemann hypothesis asserts that all "
                 "interesting solutions of the equation zeta(s) = 0 lie on a vertical line.", None, "", cmi.url)
    status, reason, doc, _pos = TribosVerifier()._status_verdict(claim, [other, badge])
    assert status == "supported" and doc is badge and '"unsolved"' in reason  # a page label, not a sentence
    snippet = _Doc("web:claymath", "results: riemann hypothesis - clay mathematics institute", None, "", cmi.url)
    status, reason, doc, _pos = TribosVerifier()._status_verdict(claim, [other, snippet])
    assert status == "not_checked" and "snippet" in reason  # a search hit is not the page


def test_t42_a_variable_named_s_is_not_read_as_seconds_in_pure_mathematics():
    from tribos.verify.math_claims import audit_answer

    q = "Let P(s) = (s - 1/4)(s - 3/4), where s is complex. Find all its zeros."
    audit = audit_answer("$$4s - 3 = 0 \;\Rightarrow\; s = \tfrac34$$", q)
    assert not [c for c in audit.claims if c.status == "failed"]  # found live: "4 s^-3" failed a correct step
    physical = audit_answer("The stone falls for $t = 4 s$, so $v = 9.8 \cdot 4 = 39.2$ m/s.",
                            "A stone falls from rest for 4 s. How fast is it moving, in m/s?")
    assert not [c for c in physical.claims if c.status == "failed"]  # units still read where quantities have them


def test_t34_points_under_discussion_are_not_bindings_but_real_errors_still_fail():
    from tribos.verify.math_claims import audit_answer

    q = "Prove or disprove: every zero s of zeta with 0 < Re(s) < 1 satisfies Re(s) = 1/2."
    md = ("The trivial zeros are $s=-2,-4,-6,\dots$ and the pole is at $s=1$. Write $s=\sigma+it$. "
          "The claim is $\forall s\in\mathbb C$: $\Re s=\tfrac12$. On the line $\sigma=1$ there are no zeros, "
          "and the first zeros lie below $t\approx 100$, with $t=0$ excluded.")
    assert not [c.text for c in audit_answer(md, q).claims if c.status == "failed"]  # found live in T34
    wrong = audit_answer(md + " Also $2 + 2 = 5$.", q)
    assert [c.text for c in wrong.claims if c.status == "failed"] == ["2+2=5"]


def test_t38_a_domain_spelled_differently_is_read_not_widened():
    import pydantic

    from tribos.axiom.schemas import AxiomStructuredInput

    task = [{"id": "q(3)", "op": "evaluate", "expression": "q(3)"}]
    branch = [{"expression": "n**2 + 4", "condition": ""}]
    for spelled in ("positive_integers", "positive integers", "Z+"):
        parsed = AxiomStructuredInput(definitions=[{"name": "q", "parameter": "n", "domain": spelled, "branches": branch}], tasks=task)
        assert parsed.definitions[0].domain == "positive_integer"
    with pytest.raises(pydantic.ValidationError):  # unreadable: rejected, never replaced by a wider domain
        AxiomStructuredInput(definitions=[{"name": "q", "parameter": "n", "domain": "primes", "branches": branch}], tasks=task)


def test_t38_a_task_without_an_id_is_labelled_by_its_own_expression():
    import pydantic

    from tribos.axiom.schemas import AxiomStructuredInput

    d = [{"name": "q", "parameter": "n", "domain": "positive_integer", "branches": [{"expression": "n**2 + 4", "condition": ""}]}]
    parsed = AxiomStructuredInput(definitions=d, tasks=[{"op": "evaluate", "expression": "q(3)"}])
    assert parsed.tasks[0].id == "q(3)"
    with pytest.raises(pydantic.ValidationError):
        AxiomStructuredInput(definitions=d, tasks=[{"op": "evaluate"}])  # nothing to label it by: rejected
