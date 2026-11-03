"""Regressions from a live run of the forced mass-spring question (run a4655dfc): correct statements flagged as
contradictions, a tabulated deliverable reported as missing, style requirements tracked as deliverables, an
unnecessary planner call, and planner replies lost to JSON escapes or truncation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tribos.agentic.llm import extract_json
from tribos.agentic.plan_execute import _rk4_computed_by_code, needs_specialised_tool
from tribos.agents.deliverables import assess, requested_items
from tribos.verify.math_claims import audit_answer
from tribos.verify.units_audit import audit_units
from tribos.verify.verifier import COMPUTED_CONFIDENCE_NOTE, reconcile_confidence_line

QUESTION = """Solve the forced damped mass-spring system:

2x''(t) + 3x'(t) + 50x(t) = 10cos(4t)

Initial conditions: x(0)=0.1 m, x'(0)=0 m/s.

Tasks:
1. Derive the complete analytical solution x(t).
6. Compute x(t) for t=0,0.5,1,...,5 seconds.
7. Compare the analytical solution with a fourth-order Runge-Kutta numerical solution and report maximum absolute error.

Requirements: Show intermediate calculations, preserve units, use LaTeX, state assumptions, and independently verify final results."""


# Correct statements are never contradicted ------------------------------------------------------------------------
@pytest.mark.parametrize("statement", [
    r"$$C_{1}=(0.1\,\text{m})-(5/13\,\text{m})=-37/130\,\text{m},$$",
    r"$$\omega_{n}=\sqrt{\frac{k}{m}}=\sqrt{\frac{50}{2}}=5\ \text{rad/s},$$",
    r"$$\zeta=\frac{c}{2\sqrt{mk}}=\frac{3}{2\sqrt{100}}=\frac{3}{20}=0.15\ \text{dimensionless},$$",
    r"$$x(0)=(-37/130\,\text{m})+(5/13\,\text{m})=1/10\,\text{m}=0.1\ \text{m},$$",
    r"$$x(0)=C_{1}+A=0.1\,\text{m},$$",
])
def test_correct_textbook_statements_are_not_contradicted(statement):
    answer = (
        "Assumptions: $m=2\\,\\text{kg}$, $c=3\\,\\text{N s/m}$, $k=50\\,\\text{N/m}$, $A=\\frac{5}{13}\\,\\text{m}$, "
        "$C_{1}=-\\frac{37}{130}\\,\\text{m}$.\n\n" + statement
    )
    audit = audit_answer(answer, query=QUESTION)
    assert not [c.text for c in audit.claims if c.status == "failed"]


def test_units_audit_still_catches_real_dimension_errors():
    report = audit_units("The force is F = 10 N and the mass m = 2 kg, so a = F/m = 5 kg")
    assert report["inconsistent"] and report["inconsistent"][0]["statement"] == "F/m = 5 kg"


def test_function_value_is_not_a_product():
    audit = audit_answer("With $x(0)=0.1$ and $x(t)=0.1\\cos t$ we have $x(0)=0.1$.", query="x(0)=0.1")
    assert not [c for c in audit.claims if c.status == "failed"]


# Coverage ---------------------------------------------------------------------------------------------------------
def test_style_requirements_are_not_deliverables():
    items = [i["item"] for i in requested_items(QUESTION)]
    assert "x(t) for t=0,0.5,1,...,5 seconds" in items
    assert not {"final results", "intermediate calculations", "preserve units", "use LaTeX", "assumptions"} & set(items)


def test_a_table_answers_a_point_evaluation():
    rows = "\n".join(f"| {t} | {0.1 * i:.4f} |" for i, t in enumerate(["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]))
    answer = "### 6. Compute x(t)\n\n| $t$ (s) | $x(t)$ (m) |\n|---:|---:|\n" + rows + "\n"
    status = {r["item"]: r["status"] for r in assess(QUESTION, answer)}
    assert status["x(t) for t=0,0.5,1,...,5 seconds"] != "missing"
    partial = "### 6.\n\n| $t$ | $x(t)$ |\n|---|---|\n| 0 | 0.1 |\n| 0.5 | 0.2 |\n"
    assert {r["item"]: r["status"] for r in assess(QUESTION, partial)}["x(t) for t=0,0.5,1,...,5 seconds"] == "missing"


# Planner ----------------------------------------------------------------------------------------------------------
def test_rk4_for_an_initial_value_problem_does_not_need_the_planner():
    assert _rk4_computed_by_code(QUESTION)
    registry = SimpleNamespace(get_entry=lambda name: object())
    state = SimpleNamespace(registry=registry, clean_query=QUESTION, query=QUESTION)
    assert needs_specialised_tool(state) is False
    without_ics = "Integrate y'' + y = 0 with RK4 and plot it."
    assert not _rk4_computed_by_code(without_ics)


def test_planner_json_with_latex_backslashes_parses():
    plan = extract_json(r'{"nodes": [{"tool": "axiom_dsolve", "args": {"note": "\omega_n=\sqrt{k/m}"}}]}')
    assert plan["nodes"][0]["args"]["note"] == "\\omega_n=\\sqrt{k/m}"


def test_truncated_planner_reply_keeps_its_complete_part():
    plan = extract_json('{"rationale": "r", "nodes": [{"id": "n1", "tool": "a"}, {"id": "n2", "tool": "b"}, {"id": "n3", "to')
    assert [n["id"] for n in plan["nodes"]][:2] == ["n1", "n2"]
    with pytest.raises(ValueError):
        extract_json("I cannot produce a plan for this.")


# Wording ----------------------------------------------------------------------------------------------------------
def test_confidence_note_is_plain_language():
    out = reconcile_confidence_line("Confidence: high (all checks passed).", "low")
    assert out.startswith("Confidence: low") and COMPUTED_CONFIDENCE_NOTE in out and "claim support" not in out
