"""Verified mathematics agent: parser, independent verifier (false-accept gate), bounded controller, platform wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from tests.agentic_fakes import collect_events, make_agentic_orchestrator
from tribos.agentic import config as agent_config
from tribos.axiom.agent import (
    TOOL_FUNCS,
    TOOL_SCHEMAS,
    FailureClass,
    HybridPolicy,
    LLMPolicy,
    MathAction,
    MathAgentConfig,
    calibrated_confidence,
    classify,
    local_executor,
    solve_math_problem,
)
from tribos.axiom.engine import (
    axiom_calculus,
    axiom_linalg,
    axiom_nsolve,
    axiom_solve,
    axiom_verify_identity,
)
from tribos.axiom.math_eval import (
    ADVERSARIAL,
    BENCHMARK,
    HOLDOUT,
    HOLDOUT2,
    HOLDOUT3,
    grade,
    run_benchmark,
)
from tribos.axiom.problem import normalize_math_text, parse_problem
from tribos.axiom.verifier import verify
from tribos.tools.registry import ErrorType, ToolRegistry, ToolResult


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# Engine honesty: "verified" only when a second method agrees ------------------------------------------------------

def test_identity_sampling_covers_negative_and_complex_values():
    bad = axiom_verify_identity("sqrt(x^2)", "x")
    assert bad["equivalent"] is False and bad["evidence"] == "refuted"
    assert bad["holds_on_positive_reals"] is True
    assert axiom_verify_identity("sqrt(x^2)", "x", assumptions={"x": "positive"})["evidence"] == "symbolic"
    assert axiom_verify_identity("log(x*y)", "log(x) + log(y)")["equivalent"] is False
    assert axiom_verify_identity("log(x*y)", "log(x) + log(y)", assumptions={"x": "positive", "y": "positive"})["equivalent"] is True


def test_solve_reports_incomplete_periodic_solution_sets():
    res = axiom_solve("sin(x) = 0")
    assert res["verified"] is True  # every listed root satisfies the equation...
    assert res["complete"] is False  # ...but the list is not the solution set
    assert "ImageSet" in res["solution_set"]
    assert axiom_solve("x^3 - x = 0")["complete"] is True


def test_calculus_checks_are_real_not_rubber_stamps():
    assert axiom_calculus("x^2*y^3", "diff", "x")["verified"] is True  # multivariate: parameters pinned, then checked
    assert axiom_calculus("(1+1/x)^x", "limit", "x", point="oo")["verified"] is True
    assert axiom_calculus("1/x", "limit", "x", point="0+")["result"] == "oo"
    assert axiom_calculus("log(1+x)", "series", "x", point="0", order=5)["verified"] is True
    basel = axiom_calculus("1/k^2", "sum", "k", lower="1", upper="oo")
    assert basel["verified"] is True and "nsum" in basel["verification"]
    gauss = axiom_calculus("exp(-a*x^2)", "integrate", "x", lower="-oo", upper="oo")
    assert gauss["verified"] is True and "parameters pinned" in gauss["verification"]


def test_linalg_checks_and_parametric_solutions():
    assert axiom_linalg([["a", "b"], ["c", "d"]], "charpoly")["verified"] is True
    assert axiom_linalg([[1, 2, 3], [4, 5, 6], [7, 8, 10]], "svd")["verified"] is True
    assert axiom_linalg([[1, 2], [3, 4]], "det")["verified"] is True
    fam = axiom_linalg([[1, 2], [2, 4]], "solve", rhs=[3, 6])
    assert fam["verified"] is True and fam["free_parameters"]
    with pytest.raises(ValueError, match="inconsistent"):
        axiom_linalg([[1, 2], [2, 4]], "solve", rhs=[3, 7])


def test_nsolve_finds_roots_and_drops_poles():
    r = axiom_nsolve("x = cos(x)")
    assert len(r["roots"]) == 1 and abs(float(r["roots"][0]) - 0.7390851332151607) < 1e-12
    assert r["complete"] is None
    tan = axiom_nsolve("tan(x) = 0", lower=-4, upper=4)
    assert sorted(round(float(x), 6) for x in tan["roots"]) == [-3.141593, 0.0, 3.141593]  # no root reported at +-pi/2
    assert len(axiom_nsolve("x^2 = 0", lower=-1, upper=1.3)["roots"]) == 1  # tangent root without a sign change


# Parser -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("question", "kind", "expected"),
    [
        ("Find all real x such that x² − 5x + 6 = 0", "solve", {"expression": "x^2 - 5x + 6 = 0", "domain": "real"}),
        ("Find all x with x > 0 such that x^2 = 4", "solve", {"expression": "x^2 = 4", "assumptions": {"x": "positive"}}),
        ("Solve x^2 = -1 over the reals", "solve", {"domain": "real"}),
        ("Solve the system 2x + y = 7, x - y = 2 for x and y", "solve", {"equations": ["2x + y = 7", "x - y = 2"], "variables": ["x", "y"]}),
        ("What is the second derivative of sin(x)*x^2?", "differentiate", {"order": 2, "variable": "x"}),
        ("d/dt t^2 cos(t)", "differentiate", {"variable": "t"}),
        (r"$\int_0^{\pi} \sin x \, dx$", "integrate", {"expression": "sin(x)", "lower": "0", "upper": "pi"}),
        ("Compute the integral of exp(-x^2) dx from -infinity to infinity", "integrate", {"lower": "-oo", "upper": "oo"}),
        (r"\lim_{x \to \infty} (1 + 1/x)^x", "limit", {"point": "oo"}),
        ("limit of 1/x as x -> 0 from the right", "limit", {"point": "0+"}),
        ("Maclaurin series of log(1+x) up to x^5", "series", {"order": 6, "point": "0"}),
        ("sum 1/k^2 for k = 1 to infinity", "sum", {"variable": "k", "upper": "oo"}),
        ("Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "ode", {"ics": {"y(0)": "1", "y'(0)": "0"}, "func": "y(x)"}),
        ("Solve the differential equation dy/dx + 2y = 0, y(0) = 3", "ode", {"expression": "y' + 2y = 0"}),
        ("Find the eigenvalues of [[4, 1], [2, 3]]", "linalg", {"linalg_op": "eigen", "matrix": [["4", "1"], ["2", "3"]]}),
        ("Solve [[4,1],[2,3]] x = b with b = [9, 8]", "linalg", {"linalg_op": "solve", "rhs_vector": ["9", "8"]}),
        ("Prove that sin(2x) = 2 sin(x) cos(x)", "identity", {}),
        (r"Simplify \frac{x^2-1}{x-1}", "simplify", {}),
        ("Evaluate 2^10 + sqrt(16)", "evaluate", {}),
        # Instructions after the expression run past the 10-word trimming limit; sentences are tried on their own.
        (
            "Evaluate 3/4 + (5/6 × 12/5) − 2^3. Show every calculation step, follow the correct order of operations, "
            "simplify the exact fraction, and verify the final answer independently.",
            "evaluate",
            {"expression": "3/4 + (5/6 * 12/5) - 2^3"},
        ),
        ("Evaluate 3/4 + (5/6 Ã— 12/5) âˆ’ 2^3", "evaluate", {"expression": "3/4 + (5/6 * 12/5) - 2^3"}),  # mojibake
        ("What is the capital of France?", "unknown", {}),
        ("Explain how a transistor works", "unknown", {}),
        ("What is the identity of the supplier of batch = 4?", "unknown", {}),  # no "evaluate 4" / "identity 4"
    ],
)
def test_parser(question, kind, expected):
    spec = parse_problem(question)
    assert spec.text == question  # the verbatim question is always kept
    assert spec.kind == kind
    for key, value in expected.items():
        assert getattr(spec, key) == value, (key, getattr(spec, key))


@pytest.mark.parametrize(
    "question",
    [
        r"IMO 1960 Problem 2. Solve \frac{4x^2}{(1-\sqrt{2x+1})^2} < 2x+9.",
        "Exercise 3.4: Solve x^2 - 4 > 0",
        "Problem 5\nFind all real x with x^2 - 4 > 0",
    ],
)
def test_a_source_label_is_not_part_of_the_problem(question):
    spec = parse_problem(question)
    assert spec.kind == "inequality" and spec.variable == "x"
    assert spec.unaccounted == []  # "1960", "3.4" and "5" label the problem; they are not in it


def test_an_inequality_is_never_parsed_or_solved_as_an_equation():
    spec = parse_problem("solve Solve 4x^2/(1-sqrt(2x+1))^2 < 2x+9")
    assert spec.kind == "inequality"
    with pytest.raises(ValueError, match="inequality"):  # was TypeError: 'StrictLessThan' - 'Zero'
        axiom_solve("x^2 - 4 > 0")


def test_ode_in_prose_with_given_values_parses_to_the_numeric_problem():
    q = (
        "Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = 2 kg, "
        "c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s, x(0) = 0.1 m, and x'(0) = 0. Derive the analytical "
        "solution. Simulate the system over 0–20 s using a suitable numerical method."
    )
    spec = parse_problem(q)
    assert spec.kind == "ode" and spec.func == "x(t)"  # x(t), never x(x); "ωt" is omega*t
    assert spec.expression == "(2) x'' + (3) x' + (50) x = (10) cos((4) t)"  # prose dropped, values substituted
    assert spec.ics == {"x(0)": "0.1", "x'(0)": "0"}  # units are not part of a condition
    assert spec.unaccounted == []  # the 0–20 s span belongs to the simulation, not to the ODE


def test_latex_normalization():
    assert normalize_math_text(r"\frac{1}{\sqrt{x}} \cdot \pi") == "((1)/(sqrt(x))) * pi"
    assert normalize_math_text("sin x + cos 2x") == "sin(x) + cos(2x)"


# Verifier: the Phase 1 gate is a false-accept rate of zero on known-wrong candidates -------------------------------

# The adversarial suite lives in tribos.axiom.math_eval (also reported by its CLI).
WRONG_CANDIDATES = list(ADVERSARIAL)


def _engine_data(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return TOOL_FUNCS[tool](**TOOL_SCHEMAS[tool](**args).model_dump())


@pytest.mark.parametrize(("question", "tool", "args", "data"), WRONG_CANDIDATES)
def test_verifier_never_accepts_a_wrong_candidate(question, tool, args, data):
    verdict = verify(parse_problem(question), tool, args, data if data is not None else _engine_data(tool, args))
    assert verdict.status == "refuted", (verdict.status, [(c.name, c.passed, c.detail) for c in verdict.checks])


def test_verifier_false_accept_rate_is_zero():
    accepted = [
        q for q, tool, args, data in WRONG_CANDIDATES
        if verify(parse_problem(q), tool, args, data if data is not None else _engine_data(tool, args)).status in ("verified", "partially_verified")
    ]
    assert accepted == []


RIGHT_CANDIDATES = [
    ("Solve x^2 = 9", "axiom_solve", {"equations": "x^2 = 9", "variables": "x"}),
    ("Solve 2x^2 = 18", "axiom_solve", {"equations": "-x^2 + 9 = 0", "variables": "x"}),  # same equation, rescaled
    ("Differentiate sin(x)*x", "axiom_calculus", {"expression": "x*sin(x)", "operation": "diff", "variable": "x"}),
    ("Integrate x^2 from 0 to 1", "axiom_calculus", {"expression": "x^2", "operation": "integrate", "variable": "x", "lower": "0", "upper": "1"}),
    ("Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "axiom_dsolve", {"equation": "y'' + y = 0", "func": "y(x)", "ics": {"y(0)": "1", "y'(0)": "0"}}),
    ("Find the inverse of [[4, 1], [2, 3]]", "axiom_linalg", {"matrix": [[4, 1], [2, 3]], "operation": "inv"}),
    ("Is sqrt(x^2) = x for all x?", "axiom_verify_identity", {"lhs": "sqrt(x^2)", "rhs": "x"}),  # a checked disproof
]


@pytest.mark.parametrize(("question", "tool", "args"), RIGHT_CANDIDATES)
def test_verifier_accepts_correct_candidates(question, tool, args):
    verdict = verify(parse_problem(question), tool, args, _engine_data(tool, args))
    assert verdict.status == "verified", [(c.name, c.passed, c.detail) for c in verdict.checks]


def test_verifier_filters_roots_by_domain_and_constraints():
    spec = parse_problem("Find all x with x > 0 such that x^2 = 4")
    verdict = verify(spec, "axiom_solve", {"equations": "x^2 = 4", "variables": "x"}, _engine_data("axiom_solve", {"equations": "x^2 = 4", "variables": "x"}))
    assert verdict.status == "verified"
    assert verdict.answer["solutions"] == [{"x": "2"}]


# Controller -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("question", "status", "answer_part"),
    [
        ("Find all real x such that x^2 - 5x + 6 = 0", "verified", "x = 2; x = 3"),
        ("Solve x^2 = -1 over the reals", "verified", "no solutions"),
        ("Solve sin(x) = 0", "partially_verified", "ImageSet"),
        ("Solve x = cos(x)", "partially_verified", "0.73908513"),
        ("Integrate x^2 from 0 to 1", "verified", "1/3"),
        ("Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "verified", "cos(x)"),
        ("Is sqrt(x^2) = x for all x?", "verified", "NOT an identity"),
        ("What is the capital of France?", "failed", ""),
    ],
)
def test_rule_policy_end_to_end(question, status, answer_part):
    result = run(solve_math_problem(question))
    assert result.status == status
    assert answer_part in str(result.answer.get("text", ""))
    assert result.metrics["tool_executions"] <= 3  # partial answers do not trigger scans that cannot improve them


class FakeLLM:
    available = True

    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = list(actions)
        self.prompts: list[str] = []

    async def json(self, system: str, user: str, *, schema: Any = None, phase: str = "") -> Any:
        assert system.startswith("[phase:math_agent]")
        self.prompts.append(user)
        if not self.actions:
            return MathAction(action="give_up", rationale="script exhausted")
        return MathAction.model_validate(self.actions.pop(0))


def test_llm_policy_repairs_locally_and_is_checked_against_the_problem():
    llm = FakeLLM([
        {"tool": "axiom_solve", "arguments": {"equations": "x^^2 = 9"}, "strategy": "exact", "rationale": "typo"},
        {"tool": "axiom_solve", "arguments": {"equations": "x^2 = 8"}, "strategy": "exact", "rationale": "wrong problem"},
        {"tool": "axiom_solve", "arguments": {"equations": "x^2 = 9", "variables": "x"}, "strategy": "exact", "rationale": "fixed"},
    ])
    cfg = MathAgentConfig()
    result = run(solve_math_problem("Solve x^2 = 9", policy=LLMPolicy(llm, cfg), config=cfg))
    failures = [s.failure for s in result.state.steps]
    assert failures == [FailureClass.MODEL_ACTION_ERROR, FailureClass.SEMANTIC_MISMATCH, FailureClass.NONE]
    assert result.status == "verified" and result.answer["solutions"] == [{"x": "-3"}, {"x": "3"}]
    assert result.metrics["repair_attempts"] == 2 and result.metrics["repairs_succeeded"] == 1
    assert "SEMANTIC_MISMATCH" in llm.prompts[2]  # the model saw why its second call was rejected


def test_identical_failed_call_is_not_executed_again():
    bad = {"tool": "axiom_solve", "arguments": {"equations": "x^^2 = 9"}, "strategy": "exact"}
    cfg = MathAgentConfig(max_repairs=4)
    result = run(solve_math_problem("Solve x^2 = 9", policy=LLMPolicy(FakeLLM([bad, bad, bad]), cfg), config=cfg))
    assert [s.failure for s in result.state.steps] == [FailureClass.MODEL_ACTION_ERROR, FailureClass.NO_PROGRESS, FailureClass.NO_PROGRESS]
    assert result.state.executions == 1
    assert result.status == "failed"


def test_schema_invalid_actions_are_never_executed():
    cfg = MathAgentConfig()
    llm = FakeLLM([{"tool": "os_system", "arguments": {"cmd": "rm -rf /"}}, {"tool": "axiom_calculus", "arguments": {"expression": "x"}}])
    result = run(solve_math_problem("Differentiate x^2", policy=LLMPolicy(llm, cfg), config=cfg))
    assert [s.failure for s in result.state.steps] == [FailureClass.SCHEMA_INVALID, FailureClass.SCHEMA_INVALID]
    assert result.state.executions == 0


def test_infrastructure_failures_switch_strategy_without_charging_repairs():
    async def flaky(tool: str, args: dict[str, Any]) -> Any:
        if tool == "axiom_solve":
            return ToolResult(success=False, tool_name=tool, error="axiom_solve exceeded 30s", error_type=ErrorType.TIMEOUT)
        return await local_executor()(tool, args)

    result = run(solve_math_problem("Solve x^3 = 2", executor=flaky))
    assert result.state.steps[0].failure == FailureClass.INFRASTRUCTURE
    assert result.state.infra_failures == 1 and result.state.repair_attempts == 0
    assert result.status == "partially_verified"  # recovered through the numeric strategy
    assert abs(float(result.answer["solutions"][0]["x"]) - 2 ** (1 / 3)) < 1e-9


def test_budget_bounds_every_run():
    cfg = MathAgentConfig(max_steps=3, max_repairs=10)
    actions = [{"tool": "axiom_solve", "arguments": {"equations": f"x^2 = {i}^^"}, "strategy": "s"} for i in range(10)]
    result = run(solve_math_problem("Solve x^2 = 9", policy=LLMPolicy(FakeLLM(actions), cfg), config=cfg))
    assert result.state.executions == 3


def test_cached_calls_are_free_and_model_escalation_only_without_a_checked_answer():
    llm = FakeLLM([])
    result = run(solve_math_problem("Integrate x^2 from 0 to 1", policy=HybridPolicy(llm, MathAgentConfig())))
    assert result.status == "verified" and llm.prompts == []  # the rules solved it: zero model calls


def test_classify_failures():
    def res(et: ErrorType | None, err: str = "", **meta: Any) -> ToolResult:
        return ToolResult(success=et is None, tool_name="t", error=err or None, error_type=et, metadata=meta)

    assert classify(res(None)) == FailureClass.NONE
    assert classify(res(ErrorType.VALIDATION_ERROR, "Input validation error: field required")) == FailureClass.SCHEMA_INVALID
    assert classify(res(ErrorType.VALIDATION_ERROR, "Could not parse mathematical expression")) == FailureClass.MODEL_ACTION_ERROR
    assert classify(res(ErrorType.INTERNAL_ERROR, "NotImplementedError: could not solve")) == FailureClass.TOOL_CANNOT_SOLVE
    assert classify(res(ErrorType.TIMEOUT, "exceeded 30s")) == FailureClass.INFRASTRUCTURE
    assert classify(res(ErrorType.INTERNAL_ERROR, "boom", failure_class="infrastructure")) == FailureClass.INFRASTRUCTURE
    assert classify(res(ErrorType.INTERNAL_ERROR, "TypeError: bad operand")) == FailureClass.MODEL_ACTION_ERROR


def test_trajectory_is_recorded_as_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBOS_MATH_TRAJECTORY_DIR", str(tmp_path))
    result = run(solve_math_problem("Solve x^2 = 9"))
    files = list(tmp_path.glob("math-trajectories-*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["answer_status"] == result.status == "verified"
    assert [e["type"] for e in rec["trajectory"]] == ["decision", "tool_call", "observation", "verification"]
    assert rec["step_labels"][0] == {
        "tool_schema_valid": True, "execution_success": True, "semantic_alignment": True,
        "local_result_valid": True, "progress_made": True,
    }
    assert rec["engine_versions"]["sympy"]


# Platform wiring ----------------------------------------------------------------------------------------------------

def test_registry_exposes_the_agent_and_nsolve():
    from tribos.extensions import axiom as axiom_ext

    reg = ToolRegistry()
    axiom_ext.register_tools(reg)
    res = run(reg.execute("axiom_solve_problem", {"problem": "Find the eigenvalues of [[2, 0], [0, 3]]"}))
    assert res.success and res.data["status"] == "verified"
    assert res.metadata["verification_status"] == "verified"
    nres = run(reg.execute("axiom_nsolve", {"equation": "x*exp(x) = 3"}))
    assert nres.success and abs(float(nres.data["roots"][0]) - 1.0499088949640398) < 1e-9


def _real_axiom_tools() -> dict[str, Any]:
    return {name: (TOOL_SCHEMAS[name], lambda kw, f=TOOL_FUNCS[name]: f(**kw)) for name in TOOL_SCHEMAS}


def test_phase_puts_a_verified_answer_in_the_synthesis(monkeypatch, tmp_path):
    orch, calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path, extra_tools=_real_axiom_tools())
    res, events = run(collect_events(orch, query="Solve x^2 - 5x + 6 = 0", thread_id="math", framework=agent_config.AGENTIC))
    art = res.execution_artifacts["math_agent"]
    assert art["status"] == "verified" and art["answer"]["text"] == "x = 2; x = 3"
    assert "math_agent" in {p["phase"] for p in res.execution_artifacts["agent_run"]["phases"]}
    synthesis = "\n".join(llm.prompts("synthesis"))
    assert '<math_agent key="agent.math_agent.result" status="verified"' in synthesis
    assert "math_agent" not in llm.phases()  # deterministic rules: no model step was needed
    json.dumps(res.to_dict(), default=str)


def test_phase_rejects_a_tool_that_only_claims_verification(monkeypatch, tmp_path):
    # The default offline fake for axiom_solve returns {"result": "x**2", "verified": True}: a tool claiming success
    # without solutions. The independent verifier must not pass it on as verified evidence.
    orch, _calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path)
    res, _ = run(collect_events(orch, query="Solve x^2 - 5x + 6 = 0", thread_id="fake", framework=agent_config.AGENTIC))
    art = res.execution_artifacts.get("math_agent")
    assert art is not None and art["status"] != "verified"
    assert 'status="verified"' not in "\n".join(llm.prompts("synthesis"))


def test_phase_does_not_run_on_non_math_questions(monkeypatch, tmp_path):
    orch, _calls, _llm = make_agentic_orchestrator(monkeypatch, tmp_path)
    res, _ = run(collect_events(orch, query="What diseases is KRAS associated with?", thread_id="bio", framework=agent_config.AGENTIC))
    assert "math_agent" not in res.execution_artifacts


# Benchmark and calibration (tribos/axiom/math_eval.py) ------------------------------------------------------------

def test_benchmark_regression_gate():
    """Phase 1 gate on every set: no false accepts anywhere, accuracy floors, abstention on non-math questions."""
    for cases, floor in ((BENCHMARK, 0.98), (HOLDOUT, 0.95), (HOLDOUT2, 0.95), (HOLDOUT3, 0.9)):
        rep = run(run_benchmark(cases))
        assert rep["verified"]["false_accepts"] == [], rep["failures"]
        assert rep["verified"]["precision"] == 1.0
        assert rep["accuracy"] >= floor, rep["failures"]
        assert rep["non_math_abstention"] == 1.0
    assert rep["adversarial"]["false_accepts"] == 0, rep["adversarial"]["accepted"]


def test_calibrated_confidence_comes_from_the_held_out_fit():
    v = calibrated_confidence("verified")
    assert v is not None and v["p_correct"] >= 0.9 and 0 < v["lower_95"] <= v["p_correct"] and v["n"] >= 30
    assert "holdout" in v["fitted_on"]
    assert calibrated_confidence("failed") is None  # no answer, no probability
    result = run(solve_math_problem("Solve x^2 = 9")).to_dict()
    assert result["confidence"]["p_correct"] == v["p_correct"]


def test_grader_is_independent_of_the_verifier():
    case = next(c for c in BENCHMARK if c.id == "alg-01")
    assert grade(case, {"status": "verified", "answer": {"solutions": [{"x": "2"}, {"x": "3"}]}})[0] is True
    assert grade(case, {"status": "verified", "answer": {"solutions": [{"x": "2"}]}})[0] is False  # status is not evidence


@pytest.mark.parametrize(
    ("question", "status", "answer_part"),
    [
        ("Solve |x - 3| = 5", "verified", "x = -2; x = 8"),
        ("Compute 100!/98!", "verified", "9900"),
        (r"$\frac{d}{dx} \ln(x^2+1)$", "verified", "2*x/(x**2 + 1)"),
        ("Verify that (x + y)^2 = x^2 + 2xy + y^2", "verified", "is an identity"),
        ("Show that log(x*y) = log(x) + log(y) for positive x and y", "verified", "is an identity"),
        ("Factor x^2 - 5x + 6", "verified", "(x - 3)*(x - 2)"),
        ("Find the area under y = x^3 from 0 to 2", "verified", "4"),
        ("∫_0^1 x^2 dx", "verified", "1/3"),
        ("lim_{x->0} (e^x - 1)/x", "verified", "1"),
        ("limit of 1/x as x -> 0", "verified", "does not exist"),
        ("Solve dy/dt = -3y, y(0) = 5", "verified", "5*exp(-3*t)"),
        ("Differentiate exp(x^2) twice", "verified", "exp(x**2)"),
        ("Solve x^5 - x - 1 = 0 over the reals", "verified", "CRootOf"),
        ("Integrate exp(-a*x) from 0 to infinity", "verified", "1/a"),
        ("For which x is x^3 = 8?", "verified", "x = 2"),
        # parse fidelity: the question says more than the parse uses, so nothing may be "verified"
        ("Differentiate 1/(1 + x^2) three times", "verified", "(x**2 + 1)**3"),
        ("Find the slope of the tangent to y = x^2 at x = 3", "verified", "6"),
        ("Find the area between y = x and y = x^2", "unverified", ""),
        ("Find the inverse function of f(x) = 2x + 3", "unverified", ""),
    ],
)
def test_calibrated_parser_and_engine_cases(question, status, answer_part):
    result = run(solve_math_problem(question))
    assert result.status == status, (result.status, result.answer, result.verdict.uncertainty if result.verdict else None)
    assert answer_part in str(result.answer.get("text", ""))


def test_completeness_is_rederived_not_taken_from_the_tool():
    spec = parse_problem("Solve x^3 - x = 0")
    truncated = {"solutions": [{"x": "0"}, {"x": "1"}], "complete": True}  # claims complete, misses -1
    verdict = verify(spec, "axiom_solve", {"equations": "x^3 - x = 0", "variables": "x"}, truncated)
    assert verdict.status == "refuted"
    assert any(c.name == "solution list is complete" and c.passed is False for c in verdict.checks)


# Extended tools (analysis.py, discrete.py, verifier_ext.py) --------------------------------------------------------

NEW_TOOLS = (
    "axiom_optimize", "axiom_inequality", "axiom_tangent", "axiom_vector_calculus", "axiom_transform", "axiom_nintegrate",
    "axiom_number_theory", "axiom_recurrence", "axiom_probability", "calcula_statistics",
)


def test_every_new_tool_is_registered_and_in_the_agent_catalogue():
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    for name in NEW_TOOLS:
        assert reg.get_entry(name) is not None, name
        assert name in TOOL_SCHEMAS and name in TOOL_FUNCS, name


@pytest.mark.parametrize(
    ("query", "tool"),
    [
        ("find the maximum of f on [0,5]", "axiom_optimize"),
        ("solve x^2 - 4 > 0", "axiom_inequality"),
        ("slope of the tangent at x = 3", "axiom_tangent"),
        ("curl of the vector field", "axiom_vector_calculus"),
        ("Laplace transform of sin t", "axiom_transform"),
        ("is 97 prime", "axiom_number_theory"),
        ("fibonacci recurrence closed form", "axiom_recurrence"),
        ("P(X <= 1) normal distribution", "axiom_probability"),
        ("t test p value of my data", "calcula_statistics"),
        ("numerical integral of exp(-x^4)", "axiom_nintegrate"),
    ],
)
def test_planners_can_find_the_new_tools(query, tool):
    from tribos.agentic.tool_retrieval import retrieve_tools
    from tribos.tools.registry import get_tool_registry

    assert tool in [t.name for t in retrieve_tools(get_tool_registry(), query, k=3)]


def test_model_chosen_calls_on_unparsed_questions_cannot_self_verify():
    """With no parsed problem, a call compared with itself proves nothing: at most partially verified."""
    spec = parse_problem("tell me something interesting about this function")
    data = TOOL_FUNCS["axiom_optimize"](**TOOL_SCHEMAS["axiom_optimize"](expression="x^2 - 4x + 1", lower="0", upper="5").model_dump())
    verdict = verify(spec, "axiom_optimize", {"expression": "x^2 - 4x + 1", "lower": "0", "upper": "5"}, data)
    assert verdict.status == "partially_verified"


def test_unevaluated_results_are_never_answers():
    result = run(solve_math_problem("Integrate sin(x)/log(x) from 2 to 3"))
    assert result.status == "partially_verified" and "Integral" not in result.answer["text"]
    assert result.state.steps[-1].tool == "axiom_nintegrate"


def test_laplace_check_uses_the_convergence_half_plane():
    assert run(solve_math_problem("Laplace transform of exp(2t)")).status == "verified"  # F(s) = 1/(s - 2) needs s > 2


def test_phase_runs_new_tools_end_to_end(monkeypatch, tmp_path):
    orch, calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path, extra_tools=_real_axiom_tools())
    res, _ = run(collect_events(orch, query="Find the maximum of x^2 - 4x + 1 on the interval [0, 5]", thread_id="opt", framework=agent_config.AGENTIC))
    art = res.execution_artifacts["math_agent"]
    assert art["status"] == "verified" and art["answer"]["text"] == "maximum = 6 at x = 5"
    assert any(name == "axiom_optimize" for name, _ in calls)
