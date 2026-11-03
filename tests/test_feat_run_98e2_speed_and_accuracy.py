"""Regressions from live run 98e25d78 of the forced mass-spring question: "At t = 0" bound t = 0 for the rest of the
answer (5 correct formulas reported as contradicted), the researcher's numbered tasks re-split by a model call, and
the mathematics agent repeating (about a minute, four model calls) what the code-computed results already check."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tribos.agentic.decompose import DecomposePhase
from tribos.agentic.math_agent import MathAgentPhase
from tribos.agents.orchestration.presentation import facts_cover_question
from tribos.agents.result_keys import COMPUTED_RESULTS
from tribos.tools.registry import ToolResult
from tribos.verify.math_claims import _independent_variables, audit_answer
from tribos.writer.facts import compute_ode_facts

QUESTION = """Solve the forced damped mass-spring system:

2x''(t) + 3x'(t) + 50x(t) = 10cos(4t)

Initial conditions: x(0)=0.1 m, x'(0)=0 m/s.

Tasks:
1. Derive the complete analytical solution x(t).
2. Separate transient and steady-state components.
6. Compute x(t) for t=0,0.5,1,...,5 seconds.
7. Compare the analytical solution with a fourth-order Runge-Kutta numerical solution and report maximum absolute error."""

ANSWER = r"""Seek $x_p=A\cos 4t+B\sin 4t$, so

$$\begin{aligned}\dot{x}_p&=-4A\sin 4t+4B\cos 4t\\ \ddot{x}_p&=-16A\cos 4t-16B\sin 4t.\end{aligned}$$

Apply $x(0)=0.1\,$m, $\dot{x}(0)=0\,$m/s. At $t=0$:

$$x(0)=C_2+\frac{5}{13}=0.1\,.$$

Differentiating and setting $t=0$, the second condition fixes $C_1$.

$$x(t)=e^{-3t/4}\left(C_2\cos\frac{\sqrt{391}\,t}{4}+C_1\sin\frac{\sqrt{391}\,t}{4}\right)+\frac{5\cos 4t}{13}+\frac{10\sin 4t}{39}\,.$$

$$x_{tr}(t)=e^{-3t/4}\left(C_2\cos\frac{\sqrt{391}\,t}{4}+C_1\sin\frac{\sqrt{391}\,t}{4}\right)$$

$$x_{ss}(t)=\frac{10 \sin 4t}{39} + \frac{5 \cos 4t}{13}$$

$x(t)=x_{tr}(t)+x_{ss}(t)$.
"""


def _tool_results() -> dict[str, ToolResult]:
    return {COMPUTED_RESULTS: ToolResult(success=True, tool_name=COMPUTED_RESULTS, data=compute_ode_facts(QUESTION))}


# Accuracy: a point evaluation is not a definition ------------------------------------------------------------------
def test_point_evaluation_does_not_bind_the_independent_variable():
    assert "t" in _independent_variables(ANSWER, QUESTION)
    failed = [c.text for c in audit_answer(ANSWER, query=QUESTION).claims if c.status == "failed"]
    assert failed == []


def test_a_wrong_formula_is_still_caught():
    wrong = ANSWER.replace(r"C_2+\frac{5}{13}=0.1", r"0.3+\frac{5}{13}=0.9")  # 0.3 + 5/13 = 0.685, not 0.9
    assert any(c.status == "failed" for c in audit_answer(wrong, query=QUESTION).claims)


# Speed: numbered tasks need no decomposition call -----------------------------------------------------------------
def test_numbered_tasks_become_sub_questions_without_a_model_call():
    calls = []

    async def json(*_a, **_k):
        calls.append(1)
        raise AssertionError("no model call expected")

    async def step(*_a, **_k):
        return None

    state = SimpleNamespace(
        clean_query=QUESTION, query=QUESTION, ctx=SimpleNamespace(scope="research", effort_level="medium"),
        effort_level="medium", llm=SimpleNamespace(available=True, json=json), sub_questions=[], bag={}, step=step,
    )
    asyncio.run(DecomposePhase().run(state))
    assert not calls and state.bag["decomposition"]["method"] == "user_tasks"
    assert [q.text for q in state.sub_questions][:2] == ["Derive the complete analytical solution x(t).",
                                                         "Separate transient and steady-state components."]
    assert len(state.sub_questions) == 4


# Speed: no mathematics-agent run for a problem solved and checked by code --------------------------------------------
def test_checked_code_results_cover_the_question():
    assert facts_cover_question(_tool_results())
    assert not facts_cover_question({})
    partial = compute_ode_facts("Solve x''(t) + sin(x(t)) = 0 with x(0)=1, x'(0)=0 and compare with RK4 at t = 0, 1.")
    assert not facts_cover_question({COMPUTED_RESULTS: ToolResult(success=True, tool_name=COMPUTED_RESULTS, data=partial)})


def test_math_agent_is_skipped_when_code_already_solved_it():
    registry = SimpleNamespace(get_entry=lambda name: object())
    state = SimpleNamespace(registry=registry, options={}, clean_query=QUESTION, query=QUESTION,
                            ctx=None, tool_results=_tool_results(), bag={})
    assert MathAgentPhase().applies(state) is False and "solved and checked by code" in state.bag["math_agent_skipped"]
    state.tool_results = {}
    assert MathAgentPhase().applies(state) is True


# Run 49402b71: a deliberately skipped planner is not a fallback; code-verified results get computational confidence
def test_planner_not_needed_is_not_reported_as_a_fallback():
    from tribos.agentic.state import core_phase_note

    core = {"phase": "plan_execute", "label": "Plan & execute", "status": "not_needed", "reason": "self-contained"}
    assert core_phase_note(core) == ""
    assert "did not run" in core_phase_note({**core, "status": "not_run"})


def test_code_verified_results_use_computational_confidence():
    from tribos.agentic.confidence import code_computation_confidence, compute_claim_confidence

    tool_results = _tool_results()
    art = code_computation_confidence(tool_results[COMPUTED_RESULTS].data)
    assert art["method"] == "computational_verification" and art["answer_confidence"] is None
    assert any("substitution" in b for b in art["basis"]) and any("RK4" in b for b in art["basis"])

    state = SimpleNamespace(artifacts={}, tool_results=tool_results, ctx=None, verification=None, bag={})
    out = asyncio.run(compute_claim_confidence(state))
    assert out["method"] == "computational_verification"


def test_rk4_and_table_deliverables_are_checked_against_computed_results():
    from tribos.agents.deliverables import assess

    data = _tool_results()[COMPUTED_RESULTS].data
    rows = "\n".join(f"| {r['t']} | {r['x']} |" for r in data["table"])
    answer = ("### 6. Compute x(t)\n\n| $t$ (s) | $x(t)$ (m) |\n|---:|---:|\n" + rows + "\n\n"
              "### 7. Compare with a fourth-order Runge-Kutta numerical solution\nA classical fourth-order Runge-Kutta "
              f"numerical solution was compared with the analytical one. The maximum absolute error is ${data['rk4']['max_abs_error'].replace('e-', r'\times 10^{-')}}}$ m.\n")
    items = {r["item"]: r for r in assess(QUESTION, answer, None, tool_results=_tool_results())}
    assert items["x(t) for t=0,0.5,1,...,5 seconds"]["check_state"] == "checked"
    rk4 = [r for k, r in items.items() if "Runge" in k or "error" in k]
    assert rk4 and all(r["check_state"] == "checked" for r in rk4)
