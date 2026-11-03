"""Coverage of the rules-only (no model) mathematics path: prime / dot ODE notation, exact constants, evaluation of a
defined function, finite-interval equations and everyday binomial experiments, each verified independently, and the
false accept "Evaluate f(x) = ... at x = 2" -> "x = 0; x = f - 3" that must never return."""

from __future__ import annotations

import asyncio

import pytest

from tribos.axiom.agent import solve_problem_tool
from tribos.axiom.engine import axiom_solve
from tribos.axiom.problem import parse_problem


def _solve(question: str) -> dict:
    return asyncio.run(solve_problem_tool(question))


@pytest.mark.parametrize("question,expected_ics", [
    ("Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1, x'(0)=0", {"x(0)": "0.1", "x'(0)": "0"}),
    ("Solve the system:\n\n2x''(t) + 3x'(t) + 50x(t) = 10cos(4t)\n\nInitial conditions: x(0)=0.1 m, x'(0)=0 m/s.\n\n"
     "Tasks:\n1. Derive x(t).", {"x(0)": "0.1", "x'(0)": "0"}),
    ("Solve ẍ + 9x = 0 with x(0)=1, ẋ(0)=0", {"x(0)": "1", "x'(0)": "0"}),
    ("Solve ẍ + 9x = 0 with x(0)=1, ẋ(0)=0", {"x(0)": "1", "x'(0)": "0"}),
])
def test_ode_notations_are_read(question, expected_ics):
    spec = parse_problem(question)
    assert spec.kind == "ode" and spec.ics == expected_ics


def test_ode_constants_are_exact_and_verified_without_a_model():
    r = _solve("Solve 2x''(t) + 3x'(t) + 50x(t) = 10cos(4t) with x(0)=0.1, x'(0)=0")
    assert r["status"] == "verified"
    assert "37*cos(sqrt(391)*t/4)/130" in r["answer"]["text"] and "0.2846" not in r["answer"]["text"]
    assert _solve("Solve x'' + 0.3x' + 4x = 0 with x(0)=0.05, x'(0)=0")["status"] == "verified"


@pytest.mark.parametrize("question,answer", [
    ("Evaluate f(x) = x^2 + 3x at x = 2", "f(2) = 10"),
    ("Let f(x) = x^2 + 3x. Evaluate f(2).", "f(2) = 10"),
])
def test_evaluating_a_defined_function(question, answer):
    r = _solve(question)
    assert r["status"] == "verified" and r["answer"]["text"] == answer


def test_a_point_the_parse_ignores_blocks_verification():
    r = _solve("Solve x^2 + 3x = 10 at x = 2")
    assert r["status"] != "verified"


@pytest.mark.parametrize("question,solutions", [
    ("Solve sin(x) = 1/2 for x in [0, 2*pi]", ["pi/6", "5*pi/6"]),
    ("Solve cos(x)=0 for 0 <= x < 2*pi", ["pi/2", "3*pi/2"]),
    ("Solve tan(x) = 1 on (0, pi)", ["pi/4"]),
    ("Solve x^2 = 4 for x in [0, 5]", ["2"]),
])
def test_equations_on_a_finite_interval(question, solutions):
    r = _solve(question)
    assert r["status"] == "verified"
    assert [s["x"] for s in r["answer"]["solutions"]] == solutions


def test_interval_solver_respects_open_ends():
    assert [s["x"] for s in axiom_solve("sin(x) = 0", "x", "[0, pi]")["solutions"]] == ["0", "pi"]
    assert axiom_solve("sin(x) = 0", "x", "(0, pi)")["solutions"] == []


@pytest.mark.parametrize("question,value", [
    ("Find the probability of getting exactly 3 heads in 5 fair coin flips", 5 / 16),
    ("Flip a fair coin 10 times. What is the probability of at least 8 heads?", 56 / 1024),
    ("Roll a fair die 6 times. What is the probability of exactly 2 sixes?", 15 * (1 / 36) * (5 / 6) ** 4),
])
def test_everyday_binomial_experiments(question, value):
    r = _solve(question)
    assert r["status"] == "verified"
    assert float(r["answer"]["text"].split("≈")[-1]) == pytest.approx(value, rel=1e-6)
