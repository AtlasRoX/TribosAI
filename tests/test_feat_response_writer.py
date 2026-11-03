"""The response layer (tribos.writer): code-computed results, the user's outline, the presentation check, the guarded
copy editor, and the pipeline wiring that keeps internal ids and pipeline jargon out of answers."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from tests.test_audit_regressions import offline_orchestrator  # noqa: F401
from tribos.agents import authoritative_orchestrator as orch_module
from tribos.agents.prompts import build_synthesis_request, get_synthesis_system_prompt
from tribos.agents.stem_evidence import render_computed_results
from tribos.tools.registry import ToolResult
from tribos.writer.editor import accept_edit, unexplained_numbers
from tribos.writer.facts import compute_ode_facts, parse_ode_problem
from tribos.writer.lint import clean_presentation, presentation_issues
from tribos.writer.outline import task_outline

FORCED = """Solve the forced damped mass-spring system:

2x''(t) + 3x'(t) + 50x(t) = 10cos(4t)

Initial conditions: x(0)=0.1 m, x'(0)=0 m/s.

Tasks:
1. Derive the complete analytical solution x(t).
2. Separate transient and steady-state components.
3. Calculate natural frequency, damping ratio, and damped natural frequency.
4. Determine steady-state amplitude and phase shift.
5. Verify the solution by substitution into the original differential equation.
6. Compute x(t) for t=0,0.5,1,...,5 seconds.
7. Compare the analytical solution with a fourth-order Runge-Kutta numerical solution and report maximum absolute error.
8. Explain the physical meaning in simple language.

Requirements: Show intermediate calculations, preserve units, use LaTeX."""


def _x_exact(t: float) -> float:
    """Closed form derived by hand: x = e^{-3t/4}(C1 cos wd t + C2 sin wd t) + 5/13 cos 4t + 10/39 sin 4t."""
    wd = math.sqrt(391) / 4
    c1 = 0.1 - 5 / 13
    c2 = (0 + 0.75 * c1 - 4 * 10 / 39) / wd
    return math.exp(-0.75 * t) * (c1 * math.cos(wd * t) + c2 * math.sin(wd * t)) + 5 / 13 * math.cos(4 * t) + 10 / 39 * math.sin(4 * t)


# Computed results -----------------------------------------------------------------------------------------------------
def test_ode_problem_is_read_from_prime_notation():
    p = parse_ode_problem(FORCED)
    assert p is not None and p.order == 2 and p.dependent == "x" and p.independent == "t"
    assert [(k, float(v)) for k, _, v in p.ics] == [(0, 0.1), (1, 0.0)]
    assert p.points == [i * 0.5 for i in range(11)] and p.rk4 and p.t_unit == "s" and p.x_unit == "m"


def test_forced_oscillator_known_answers():
    d = compute_ode_facts(FORCED)
    assert all(c["passed"] for c in d["checks"]) and len(d["checks"]) == 2
    params = {p["name"]: p for p in d["parameters"]}
    assert float(params["natural frequency"]["value"]) == pytest.approx(5.0)
    assert float(params["damping ratio"]["value"]) == pytest.approx(0.15)
    assert float(params["damped natural frequency"]["value"]) == pytest.approx(math.sqrt(391) / 4, rel=1e-5)
    amp = 5 / math.sqrt((50 - 2 * 16) ** 2 + (3 * 4) ** 2)  # F0/m-form: 10/sqrt((k-m w^2)^2 + (c w)^2)
    assert float(params["steady-state amplitude"]["value"]) == pytest.approx(2 * amp, rel=1e-5)
    assert float(params["phase lag of the response behind the forcing"]["value_degrees"]) == pytest.approx(
        math.degrees(math.atan2(12, 18)), rel=1e-5)
    assert "e^{- \\frac{3 t}{4}}" in d["transient_latex"] and "\\frac{37" in d["transient_latex"]


def test_requested_values_and_rk4_comparison():
    d = compute_ode_facts(FORCED)
    for row in d["table"]:
        assert float(row["x"]) == pytest.approx(_x_exact(float(row["t"])), abs=1e-6)
    rk = d["rk4"]
    assert float(rk["max_abs_error"]) < 1e-9 and rk["compared_with"] == "exact solution" and not rk["step_was_given"]
    assert len(rk["at_points"]) == 11


def test_rk4_step_from_the_question_and_order_h4_convergence():
    base = "Solve y'(t) = -2y(t), y(0)=1. Compare with RK4 at t = 0, 1, 2 and report the error, step h = {}."
    e1 = float(compute_ode_facts(base.format(0.1))["rk4"]["max_abs_error"])
    e2 = float(compute_ode_facts(base.format(0.05))["rk4"]["max_abs_error"])
    assert 12 < e1 / e2 < 20  # fourth order: halving h divides the error by about 16


def test_nonlinear_equation_uses_a_reference_integration():
    d = compute_ode_facts("Solve x''(t) + sin(x(t)) = 0 with x(0)=1, x'(0)=0 and compare with RK4 at t = 0, 1, 2.")
    assert "exact_solution_latex" not in d
    assert d["rk4"]["compared_with"].startswith("DOP853") and float(d["rk4"]["max_abs_error"]) < 1e-8


@pytest.mark.parametrize("question", ["What is the derivative of x^2?", "Solve x^2 = 4", "Explain Newton's second law."])
def test_no_results_without_an_initial_value_problem(question):
    assert compute_ode_facts(question) is None


def test_missing_initial_conditions_give_no_particular_solution():
    d = compute_ode_facts("Solve x''(t) + 4x(t) = 0")
    assert d is not None and "exact_solution_latex" not in d and d["notes"]


def test_computed_results_render_for_the_writer():
    d = compute_ode_facts(FORCED)
    xml = "\n".join(render_computed_results(ToolResult(success=True, tool_name="computed_results", data=d)))
    assert xml.startswith("<computed_results") and "<rk4_comparison" in xml and "<values_at_requested_points" in xml
    assert 'name="damping ratio"' in xml and 'check passed="true"' in xml


# Outline --------------------------------------------------------------------------------------------------------------
def test_outline_is_the_users_numbering():
    items = task_outline(FORCED)
    assert [label for label, _ in items] == [str(i) for i in range(1, 9)]
    assert items[0][1].startswith("Derive the complete analytical solution")
    assert "Requirements" not in items[-1][1]


def test_outline_lettered_and_none():
    assert [b for _, b in task_outline("Find (a) the roots of x^2-4 and (b) the vertex.")] == ["the roots of x^2-4", "the vertex."]
    assert task_outline("Compute 2.5 + 3.1 and explain.") == []


# Presentation check -------------------------------------------------------------------------------------------------
BAD = """### Executive Summary
Established background: the verified mathematics agent returns the steady part. Confidence: moderate.

### [q1] Natural frequency
In evidence the value is 5. The agent output contains `axiom_dsolve` data and 5*cos(4*t)/13 + 10*sin(4*t)/39.
C1 = -0.284615384615385 (see q3).
"""

GOOD = """### Executive Summary
The natural frequency is $\\omega_n = 5$ rad/s and the damping ratio is $\\zeta = 0.15$. Confidence: high, both follow
exactly from the coefficients.

### 1. Natural frequency
$$\\omega_n = \\sqrt{50/2} = 5\\ \\mathrm{rad/s}$$
"""


def test_lint_flags_internal_ids_jargon_raw_math_and_precision():
    kinds = {i.kind for i in presentation_issues(BAD)}
    assert {"internal_id", "label", "jargon", "raw_math", "precision"} <= kinds


def test_lint_passes_a_well_written_answer():
    assert presentation_issues(GOOD, [("1", "Natural frequency")]) == []


def test_lint_checks_the_users_outline_and_order():
    outline = [("1", "Natural frequency"), ("2", "Damping ratio")]
    issues = presentation_issues(GOOD, outline)
    assert any(i.kind == "outline" and "2. Damping ratio" in i.excerpt for i in issues)
    swapped = "### 2. Damping\ntext\n\n### 1. Frequency\ntext\n"
    assert any("order" in i.detail for i in presentation_issues(swapped, outline))


def test_clean_presentation_removes_ids_and_tags_only():
    cleaned = clean_presentation(BAD)
    assert "[q1]" not in cleaned and "(see q3)" not in cleaned and "### Natural frequency" in cleaned
    assert "The verified mathematics agent" in cleaned  # jargon is left to the editor, not cut mid-sentence
    table = "| t | x |\n|---|---|\n| 0 | 0.1 |"
    assert clean_presentation(table) == table


# Editor guard -------------------------------------------------------------------------------------------------------
def test_editor_may_round_but_not_invent_numbers():
    draft = "C1 = -0.284615384615385 and the amplitude is 0.46225 m; omega = 4."
    assert unexplained_numbers("C1 ≈ -0.2846 and amplitude 0.4623 m", draft) == []
    assert unexplained_numbers("the amplitude is 0.51 m", draft) == ["0.51"]


def test_editor_must_keep_citations():
    draft = "As shown in arXiv:2312.04511 and https://doi.org/10.1103/PhysRev.47.777, x = 5."
    ok, why = accept_edit("q", draft, "As shown, x = 5. " + "More text here to keep length. " * 3, None)
    assert not ok and "citations" in why


# Prompts ------------------------------------------------------------------------------------------------------------
def test_writer_prompt_has_no_internal_heading_examples_and_asks_for_the_users_numbering():
    p = get_synthesis_system_prompt()
    assert "[q1]" not in p and "pipeline in which" not in p
    assert "reuse the user's numbering" in p and "never q1, q2, req-3" in p
    req = build_synthesis_request("<evidence/>", "<tool_status/>", "", "q", answer_outline="1. Derive x(t)")
    assert "<answer_outline" in req and "1. Derive x(t)" in req


def test_research_brief_never_shows_ids():
    from tribos.agentic.state import AgentState

    state = AgentState.__new__(AgentState)
    state.sub_questions = [SimpleNamespace(id="q1", text="natural frequency", status="open")]
    state.bag, state.brief_notes = {}, []
    brief = AgentState.research_brief(state)
    assert "q1" not in brief and "natural frequency" in brief


# Pipeline -------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pipeline_computes_results_and_edits_a_badly_presented_draft(offline_orchestrator, monkeypatch):  # noqa: F811
    orch, _calls = offline_orchestrator
    prompts: list[str] = []
    draft = (
        "### Executive Summary\nEstablished background: the verified mathematics agent gives the result in evidence. "
        "Confidence: moderate.\n\n### [q1] Natural frequency\nThe value is 5 rad/s and 5*cos(4*t)/13 appears in evidence.\n"
    )
    edited = (
        "### Executive Summary\nThe natural frequency is 5 rad/s and the damping ratio is 0.15. Confidence: high, "
        "the solution satisfies the equation identically.\n\n### 1. Analytical solution\n$$x(t)$$ as computed.\n\n"
        "### 3. Natural frequency\n$\\omega_n = 5$ rad/s, $\\zeta = 0.15$.\n"
    )

    class FakeLLM:
        async def astream(self, messages):
            prompts.append(str(messages[-1].content))
            yield SimpleNamespace(content=draft, additional_kwargs={})

        async def ainvoke(self, messages):
            prompts.append(str(messages[-1].content))
            return SimpleNamespace(content=edited)

    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: FakeLLM())
    events: list[dict[str, Any]] = []

    async def cb(ev: dict[str, Any]) -> None:
        events.append(ev)

    res = await orch.execute_inquiry(FORCED, thread_id="t-writer", enable_web_search=False, event_callback=cb)
    synthesis = next(p for p in prompts if "<user_query" in p and "<evidence>" in p)
    assert "<computed_results" in synthesis and "<answer_outline" in synthesis
    assert any("<presentation_issues>" in p for p in prompts)
    assert "[q1]" not in res.response and "in evidence" not in res.response
    assert any(e.get("type") == "content_reset" and e.get("reason") == "presentation" for e in events)


def test_numpy_is_not_shadowed():
    assert np.isclose(_x_exact(0.0), 0.1)
