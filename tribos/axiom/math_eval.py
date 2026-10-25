"""
Benchmark, grader and calibration for the verified mathematics agent (Stage 0 / Phase 1 gate of
math_agent_research_recommendations.md).

    python -m tribos.axiom.math_eval                     # run the benchmark, print the report
    python -m tribos.axiom.math_eval --json report.json  # also write the full per-case report
    python -m tribos.axiom.math_eval --write-calibration # refit tribos/axiom/calibration.json

- BENCHMARK: hand-checked problems stratified by domain, difficulty and phrasing (prose, LaTeX, Unicode), each with
  a gold answer. Grading compares against the gold answer only, never against the agent's own verifier, so the
  verifier itself is measured: its precision (no false accepts) and its recall (correct answers it could not
  verify), as the research recommends (rule-based verifiers trade recall for precision).
- ADVERSARIAL: known-wrong candidates (wrong equation, wrong root, wrong derivative, false identity, fake
  counterexample, ...) fed straight to the verifier; any acceptance is a false accept.
- Calibration: each final status maps to the empirical probability that an answer with that status is correct
  (Laplace-smoothed, with a Wilson 95% lower bound). ECE and Brier are reported cross-fitted (fit on one half,
  scored on the other), never in-sample. The agent reports these numbers as its confidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sympy as sp

from . import engine as E
from .problem import parse_problem

BENCHMARK_VERSION = "math-eval-v1"
CALIBRATION_PATH = Path(__file__).with_name("calibration.json")
STATUSES = ("verified", "partially_verified", "unverified", "failed")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    domain: str
    difficulty: str  # basic | intermediate | advanced
    gold: dict[str, Any]  # see grade()
    expect: str = "verified"  # the status an ideal agent reaches (partial for families / numeric roots)
    phrasing: str = "prose"  # prose | latex | unicode | terse


def _c(id_: str, q: str, domain: str, diff: str, gold: dict[str, Any], expect: str = "verified", phrasing: str = "prose") -> Case:
    return Case(id_, q, domain, diff, gold, expect, phrasing)


# gold kinds:
#   roots: list of values (one variable)    tuples: list of solution tuples, with "vars"
#   family: members / nonmembers of an infinite solution set
#   expr: value or expression equal to the answer        antiderivative: integrand (answer' must equal it)
#   series: exact polynomial                              ode: rhs (IVP) or ode+order (general solution)
#   matrix / vector / eigen / span / bool / none
BENCHMARK: tuple[Case, ...] = (
    # Algebra: polynomial and rational equations
    _c("alg-01", "Solve x^2 - 5x + 6 = 0", "algebra", "basic", {"roots": ["2", "3"]}, phrasing="terse"),
    _c("alg-02", "Find all real x such that x² − 5x + 6 = 0", "algebra", "basic", {"roots": ["2", "3"]}, phrasing="unicode"),
    _c("alg-03", "What are the roots of x^3 - 6x^2 + 11x - 6?", "algebra", "basic", {"roots": ["1", "2", "3"]}),
    _c("alg-04", "Solve 2x + 3 = 11", "algebra", "basic", {"roots": ["4"]}, phrasing="terse"),
    _c("alg-05", "Solve x^2 + 1 = 0", "algebra", "basic", {"roots": ["I", "-I"]}, phrasing="terse"),
    _c("alg-06", "Solve x^2 + 1 = 0 over the reals", "algebra", "basic", {"roots": []}),
    _c("alg-07", "Find all x with x > 0 such that x^2 = 4", "algebra", "basic", {"roots": ["2"]}),
    _c("alg-08", "Solve x^4 - 5x^2 + 4 = 0", "algebra", "intermediate", {"roots": ["1", "-1", "2", "-2"]}, phrasing="terse"),
    _c("alg-09", "Solve (x - 1)^2 = 0", "algebra", "basic", {"roots": ["1"]}, phrasing="terse"),
    _c("alg-10", "Solve sqrt(x) = 3", "algebra", "basic", {"roots": ["9"]}, phrasing="terse"),
    _c("alg-11", "Solve sqrt(x + 7) = x + 1", "algebra", "intermediate", {"roots": ["2"]}, phrasing="terse"),
    _c("alg-12", "Solve 1/x + 1/(x + 1) = 1", "algebra", "intermediate", {"roots": ["(1 + sqrt(5))/2", "(1 - sqrt(5))/2"]}, phrasing="terse"),
    _c("alg-13", "Solve |x - 3| = 5", "algebra", "intermediate", {"roots": ["-2", "8"]}, phrasing="terse"),
    _c("alg-14", "Find the real roots of x^3 - 2x - 5", "algebra", "advanced", {"roots": ["2.0945514815423265"]}),
    _c("alg-15", "Solve x^2 - 2*a*x + a^2 = 0 for x", "algebra", "intermediate", {"roots": ["a"]}),
    # Systems
    _c("sys-01", "Solve the system 2x + y = 7, x - y = 2 for x and y", "systems", "basic", {"tuples": [["3", "1"]], "vars": ["x", "y"]}),
    _c("sys-02", "Solve x + y + z = 6; x - y = 0; x + 2z = 7", "systems", "intermediate", {"tuples": [["5/3", "5/3", "8/3"]], "vars": ["x", "y", "z"]}, phrasing="terse"),
    _c("sys-03", "Solve x^2 + y^2 = 25 and x - y = 1", "systems", "intermediate", {"tuples": [["4", "3"], ["-3", "-4"]], "vars": ["x", "y"]}, phrasing="terse"),
    # Transcendental equations
    _c("tr-01", "Solve sin(x) = 0", "transcendental", "intermediate", {"family": {"members": ["0", "pi", "-pi", "5*pi"], "nonmembers": ["pi/2", "1"]}}, expect="partially_verified", phrasing="terse"),
    _c("tr-02", "Solve e^x = 5", "transcendental", "basic", {"roots": ["log(5)"], "complex_branches": True}, expect="partially_verified", phrasing="terse"),
    _c("tr-03", "Solve x = cos(x)", "transcendental", "advanced", {"roots": ["0.7390851332151607"]}, expect="partially_verified", phrasing="terse"),
    _c("tr-04", "Solve x*exp(x) = 3", "transcendental", "advanced", {"roots": ["1.0499088949640398"], "complex_branches": True}, expect="partially_verified", phrasing="terse"),
    _c("tr-05", "Solve log(x) = 2", "transcendental", "basic", {"roots": ["exp(2)"]}, phrasing="terse"),
    _c("tr-06", "Solve 2^x = 8 over the reals", "transcendental", "basic", {"roots": ["3"]}),
    _c("tr-07", "Solve tan(x) = 1", "transcendental", "intermediate", {"family": {"members": ["pi/4", "5*pi/4", "-3*pi/4"], "nonmembers": ["0", "pi/2"]}}, expect="partially_verified", phrasing="terse"),
    _c("tr-08", "Find all real solutions of exp(x) = x + 2", "transcendental", "advanced", {"roots": ["1.1461932206205825", "-1.8414056604369606"]}, expect="partially_verified"),
    # Differentiation
    _c("dif-01", "Differentiate x^3 * exp(x) with respect to x", "calculus", "basic", {"expr": "x**3*exp(x) + 3*x**2*exp(x)"}),
    _c("dif-02", "What is the derivative of sin(x)/x?", "calculus", "basic", {"expr": "(x*cos(x) - sin(x))/x**2"}),
    _c("dif-03", "Find the second derivative of x^4", "calculus", "basic", {"expr": "12*x**2"}),
    _c("dif-04", "d/dt t^2 cos(t)", "calculus", "basic", {"expr": "2*t*cos(t) - t**2*sin(t)", "vars": ["t"]}, phrasing="terse"),
    _c("dif-05", "Differentiate x^x", "calculus", "intermediate", {"expr": "x**x*(log(x) + 1)"}, phrasing="terse"),
    _c("dif-06", "Differentiate a*x^2 + b*x + c with respect to x", "calculus", "basic", {"expr": "2*a*x + b"}),
    _c("dif-07", r"$\frac{d}{dx} \ln(x^2+1)$", "calculus", "basic", {"expr": "2*x/(x**2 + 1)"}, phrasing="latex"),
    _c("dif-08", "What is the third derivative of sin(2x)?", "calculus", "intermediate", {"expr": "-8*cos(2*x)"}),
    # Integration
    _c("int-01", "Integrate x^2 from 0 to 1", "calculus", "basic", {"expr": "1/3"}),
    _c("int-02", "Find the antiderivative of 3x^2 + cos(x)", "calculus", "basic", {"antiderivative": "3*x**2 + cos(x)"}),
    _c("int-03", r"$\int_0^{\pi} \sin x \, dx$", "calculus", "basic", {"expr": "2"}, phrasing="latex"),
    _c("int-04", "Compute the integral of exp(-x^2) dx from -infinity to infinity", "calculus", "intermediate", {"expr": "sqrt(pi)"}),
    _c("int-05", "Integrate 1/(1 + x^2) from 0 to 1", "calculus", "basic", {"expr": "pi/4"}),
    _c("int-06", "Integrate x*exp(x) dx", "calculus", "intermediate", {"antiderivative": "x*exp(x)"}, phrasing="terse"),
    _c("int-07", "Integrate ln(x) from 1 to e", "calculus", "intermediate", {"expr": "1"}),
    _c("int-08", "∫ 1/x dx", "calculus", "basic", {"antiderivative": "1/x"}, phrasing="unicode"),
    _c("int-09", "Evaluate the integral of sin(x)^2 from 0 to 2*pi", "calculus", "intermediate", {"expr": "pi"}),
    _c("int-10", "Integrate exp(-a*x) from 0 to infinity", "calculus", "advanced", {"expr": "1/a", "params": {"a": "0.61"}}),
    _c("int-11", r"\int_{0}^{1} x e^{x} \, dx", "calculus", "intermediate", {"expr": "1"}, phrasing="latex"),
    # Limits
    _c("lim-01", "Find the limit of sin(x)/x as x approaches 0", "calculus", "basic", {"expr": "1"}),
    _c("lim-02", r"\lim_{x \to \infty} (1 + 1/x)^x", "calculus", "intermediate", {"expr": "E"}, phrasing="latex"),
    _c("lim-03", "limit of 1/x as x -> 0 from the right", "calculus", "basic", {"expr": "oo"}),
    _c("lim-04", "limit of (1 - cos(x))/x^2 as x -> 0", "calculus", "intermediate", {"expr": "1/2"}),
    _c("lim-05", "Find the limit of (x^2 - 4)/(x - 2) as x tends to 2", "calculus", "basic", {"expr": "4"}),
    _c("lim-06", "limit of x/(x + 1) as x -> oo", "calculus", "basic", {"expr": "1"}),
    _c("lim-07", "limit of 1/x as x -> 0", "calculus", "intermediate", {"dne": True}),
    # Series
    _c("ser-01", "Taylor series of exp(x) around 0 up to order 4", "calculus", "basic", {"series": "1 + x + x**2/2 + x**3/6 + x**4/24"}),
    _c("ser-02", "Maclaurin series of log(1+x) up to x^5", "calculus", "intermediate", {"series": "x - x**2/2 + x**3/3 - x**4/4 + x**5/5"}),
    _c("ser-03", "Taylor series of cos(x) about x = 0 to order 6", "calculus", "basic", {"series": "1 - x**2/2 + x**4/24 - x**6/720"}),
    _c("ser-04", "Expand sin(x) around pi up to order 3", "calculus", "intermediate", {"series": "-(x - pi) + (x - pi)**3/6"}),
    # Sums
    _c("sum-01", "Sum of k^2 for k from 1 to n", "calculus", "intermediate", {"expr": "n*(n + 1)*(2*n + 1)/6"}),
    _c("sum-02", "sum 1/k^2 for k = 1 to infinity", "calculus", "intermediate", {"expr": "pi**2/6"}, phrasing="terse"),
    _c("sum-03", "Find the sum of 1/2^k for k from 0 to infinity", "calculus", "basic", {"expr": "2"}),
    _c("sum-04", "Compute the sum of k for k = 1 to 100", "calculus", "basic", {"expr": "5050"}),
    # ODEs
    _c("ode-01", "Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "ode", "basic", {"ode": "cos(x)"}),
    _c("ode-02", "Solve the differential equation dy/dx + 2y = 0, y(0) = 3", "ode", "basic", {"ode": "3*exp(-2*x)"}),
    _c("ode-03", "Solve y' = y", "ode", "basic", {"ode_general": "y' - y", "order": 1}, phrasing="terse"),
    _c("ode-04", "Solve y'' - 3y' + 2y = 0", "ode", "intermediate", {"ode_general": "y'' - 3*y' + 2*y", "order": 2}, phrasing="terse"),
    _c("ode-05", "Solve y' + y = x with y(0) = 0", "ode", "intermediate", {"ode": "x - 1 + exp(-x)"}),
    # Linear algebra
    _c("la-01", "Find the eigenvalues of [[4, 1], [2, 3]]", "linalg", "basic", {"eigen": {"2": 1, "5": 1}}),
    _c("la-02", "determinant of [[1,2,3],[4,5,6],[7,8,10]]", "linalg", "basic", {"expr": "-3"}, phrasing="terse"),
    _c("la-03", "Find the inverse of [[4, 1], [2, 3]]", "linalg", "basic", {"matrix": [["3/10", "-1/10"], ["-1/5", "2/5"]]}),
    _c("la-04", "Solve [[4,1],[2,3]] x = b with b = [9, 8]", "linalg", "basic", {"vector": ["19/10", "7/5"]}),
    _c("la-05", "Find the rank of [[1,2,3],[2,4,6]]", "linalg", "basic", {"rref": [["1", "2", "3"], ["0", "0", "0"]]}),
    _c("la-06", "Find the null space of [[1,2],[2,4]]", "linalg", "intermediate", {"span": [["-2", "1"]]}),
    _c("la-07", "characteristic polynomial of [[2,1],[1,2]]", "linalg", "basic", {"expr": "lambda**2 - 4*lambda + 3", "vars": ["lambda"]}, phrasing="terse"),
    _c("la-08", "eigenvalues of [[a, b], [b, a]]", "linalg", "intermediate", {"eigen": {"a - b": 1, "a + b": 1}}, phrasing="terse"),
    _c("la-09", "det of [1 2; 3 4]", "linalg", "basic", {"expr": "-2"}, phrasing="terse"),
    # Identities
    _c("id-01", "Prove that sin(2x) = 2 sin(x) cos(x)", "identity", "basic", {"bool": True}),
    _c("id-02", "Is sqrt(x^2) = x for all x?", "identity", "intermediate", {"bool": False}),
    _c("id-03", "Verify that (x + y)^2 = x^2 + 2xy + y^2", "identity", "basic", {"bool": True}),
    _c("id-04", "Show that log(x*y) = log(x) + log(y) for positive x and y", "identity", "intermediate", {"bool": True}),
    _c("id-05", "Is (x+y)^2 = x^2 + y^2 an identity?", "identity", "basic", {"bool": False}),
    _c("id-06", "Prove that cos(x)^2 - sin(x)^2 = cos(2x)", "identity", "basic", {"bool": True}),
    _c("id-07", "Check whether tan(x) = sin(x)/cos(x)", "identity", "basic", {"bool": True}),
    # Simplification and evaluation
    _c("sim-01", "Simplify (x^2 - 1)/(x - 1)", "simplify", "basic", {"expr": "x + 1"}),
    _c("sim-02", r"Simplify \frac{x^2-1}{x-1}", "simplify", "basic", {"expr": "x + 1"}, phrasing="latex"),
    _c("sim-03", "Simplify sin(x)^2 + cos(x)^2", "simplify", "basic", {"expr": "1"}),
    _c("sim-04", "Factor x^2 - 5x + 6", "simplify", "basic", {"expr": "x**2 - 5*x + 6", "form": "factor"}),
    _c("sim-05", "Expand (x + 1)^3", "simplify", "basic", {"expr": "x**3 + 3*x**2 + 3*x + 1", "form": "expand"}),
    _c("ev-01", "Evaluate 2^10 + sqrt(16)", "evaluate", "basic", {"expr": "1028"}),
    _c("ev-02", "Compute 100!/98!", "evaluate", "basic", {"expr": "9900"}),
    _c("ev-03", "What is sin(pi/6) + cos(pi/3)?", "evaluate", "basic", {"expr": "1"}),
    _c("ev-04", "Calculate sqrt(2)*sqrt(8)", "evaluate", "basic", {"expr": "4"}),
    # Not mathematics: the agent must not claim an answer
    # Optimization
    _c("opt-01", "Find the maximum of x^2 - 4x + 1 on the interval [0, 5]", "optimization", "basic", {"extrema": {"maximum": "6"}}),
    _c("opt-02", "Find the minimum value of x^4 - 8x^2", "optimization", "intermediate", {"extrema": {"minimum": "-16"}}),
    _c("opt-03", "Find the absolute extrema of f(x) = x^3 - 3x on [-2, 3]", "optimization", "intermediate", {"extrema": {"maximum": "18", "minimum": "-2"}}),
    _c("opt-04", "Maximize x*exp(-x) for x >= 0", "optimization", "intermediate", {"extrema": {"maximum": "exp(-1)"}}),
    _c("opt-05", "Find the maximum of x^3 - 3x", "optimization", "intermediate", {"extrema": {"maximum": "unbounded"}}),
    # Inequalities
    _c("ineq-01", "Solve x^2 - 4 > 0", "inequality", "basic", {"set": "Union(Interval.open(-oo, -2), Interval.open(2, oo))"}, phrasing="terse"),
    _c("ineq-02", "For which x is (x - 1)/(x + 2) <= 0?", "inequality", "intermediate", {"set": "Interval.Lopen(-2, 1)"}),
    _c("ineq-03", "Solve |x - 3| < 2", "inequality", "basic", {"set": "Interval.open(1, 5)"}, phrasing="terse"),
    # Tangents
    _c("tan-01", "Find the slope of the tangent to y = x^2 at x = 3", "calculus", "basic", {"slope": "6"}),
    _c("tan-02", "Find the equation of the tangent line to y = ln(x) at x = 1", "calculus", "basic", {"slope": "1", "line": "x - 1"}),
    _c("tan-03", "What is the derivative of x^3 at x = 2?", "calculus", "basic", {"slope": "12"}),
    # Number theory
    _c("nt-01", "Find the prime factorization of 360", "number_theory", "basic", {"nt": {"2": 3, "3": 2, "5": 1}}),
    _c("nt-02", "Is 97 prime?", "number_theory", "basic", {"nt": True}),
    _c("nt-03", "Find the gcd of 84 and 126", "number_theory", "basic", {"nt": 42}),
    _c("nt-04", "What is the lcm of 4, 6 and 10?", "number_theory", "basic", {"nt": 60}),
    _c("nt-05", "Compute 3^100 mod 7", "number_theory", "intermediate", {"nt": 4}, phrasing="terse"),
    _c("nt-06", "Find the inverse of 17 modulo 31", "number_theory", "intermediate", {"nt": 11}),
    _c("nt-07", "Solve x ≡ 2 (mod 3), x ≡ 3 (mod 5), x ≡ 2 (mod 7)", "number_theory", "advanced", {"nt": {"modulus": 105, "x": 23}}, phrasing="unicode"),
    _c("nt-08", "Find all integer solutions of 12x + 18y = 30", "number_theory", "intermediate", {"nt": {"solve": [12, 18, 30]}}),
    _c("nt-09", "What is Euler's totient of 36?", "number_theory", "basic", {"nt": 12}),
    # Recurrences
    _c("rec-01", "Solve the recurrence a(n) = a(n-1) + a(n-2) with a(0) = 0, a(1) = 1", "recurrence", "intermediate", {"closed": "((1 + sqrt(5))**n - (1 - sqrt(5))**n)/(2**n*sqrt(5))"}),
    _c("rec-02", "Solve a_n = 3a_{n-1} + 2, a_0 = 1", "recurrence", "basic", {"closed": "2*3**n - 1"}, phrasing="latex"),
    # Transforms
    _c("lt-01", "Find the Laplace transform of t^2*exp(-t)", "transform", "basic", {"expr": "2/(s + 1)**3", "vars": ["s"]}),
    _c("lt-02", "Inverse Laplace transform of 1/(s^2 + 1)", "transform", "basic", {"expr": "sin(t)", "vars": ["t"]}, phrasing="terse"),
    _c("lt-03", "Fourier transform of exp(-pi*x^2)", "transform", "intermediate", {"expr": "exp(-pi*k**2)", "vars": ["k"]}, phrasing="terse"),
    # Vector calculus
    _c("vc-01", "Compute the gradient of x^2*y + z", "vector_calculus", "basic", {"vector": ["2*x*y", "x**2", "1"]}),
    _c("vc-02", "Find the divergence of [x*y, y*z, z*x]", "vector_calculus", "basic", {"expr": "x + y + z"}),
    _c("vc-03", "Find the curl of (-y, x, 0)", "vector_calculus", "basic", {"vector": ["0", "0", "2"]}),
    _c("vc-04", "Find the Laplacian of x^2 + y^2 + z^2", "vector_calculus", "basic", {"expr": "6"}),
    # Probability
    _c("pr-01", "If X ~ N(0, 1), find P(X <= 1)", "probability", "basic", {"number": "0.8413447460685429"}),
    _c("pr-02", "X is binomial with n = 10 and p = 0.3. What is the probability of at most 2 successes?", "probability", "intermediate", {"number": "0.3827827864"}),
    _c("pr-03", "What is the expected value of a Poisson(4) random variable?", "probability", "basic", {"number": "4"}),
    _c("pr-04", "For X ~ N(100, 15), find P(85 < X < 115)", "probability", "intermediate", {"number": "0.6826894921370859"}),
    # Statistics
    _c("st-01", "Find the mean and standard deviation of 2, 4, 4, 4, 5, 5, 7, 9", "statistics", "basic", {"stats": {"mean": 5, "std": 2.138089935299395}}),
    _c("st-02", "Run a t-test on [5.1, 4.9, 5.3, 5.0, 5.2] against mu = 5", "statistics", "intermediate", {"stats": {"t": 1.4142135623730951}}),
    _c("st-03", "Find the line of best fit for x = [1, 2, 3, 4] and y = [2.1, 3.9, 6.2, 7.8]", "statistics", "basic", {"stats": {"slope": 1.94, "intercept": 0.15}}),
    _c("st-04", "Find a 95% confidence interval for the mean of [10, 12, 11, 13, 12]", "statistics", "intermediate", {"stats": {"lower": 10.184285216, "upper": 13.015714784}}),
    # Percentages, numeric quadrature, word-number orders
    _c("pct-01", "What is 15% of 80?", "evaluate", "basic", {"expr": "12"}),
    _c("nq-01", "Integrate sin(x)/log(x) from 2 to 3", "calculus", "advanced", {"number": "0.674380603436754", "tol": 1e-9}, expect="partially_verified"),
    _c("dif-09", "Differentiate 1/(1 + x^2) three times", "calculus", "intermediate", {"expr": "-24*x*(x**2 - 1)/(x**2 + 1)**4"}),
    _c("no-01", "What is the capital of France?", "none", "basic", {"none": True}, expect="failed"),
    _c("no-02", "Explain how a transistor works", "none", "basic", {"none": True}, expect="failed"),
    _c("no-03", "What is the identity of the supplier of batch = 4?", "none", "basic", {"none": True}, expect="failed"),
)


# Held-out problems: written after the development set and never used to tune the parser, policy or verifier.
# Calibration is fitted on development + held-out; the held-out report is the honest generalisation estimate.
HOLDOUT: tuple[Case, ...] = (
    _c("h-alg-01", "Find the zeros of x^2 - 7x + 10", "algebra", "basic", {"roots": ["2", "5"]}),
    _c("h-alg-02", "Solve 3x - 7 = 2x + 5", "algebra", "basic", {"roots": ["12"]}, phrasing="terse"),
    _c("h-alg-03", "For which x is x^3 = 8?", "algebra", "intermediate", {"roots": ["2", "-1 + sqrt(3)*I", "-1 - sqrt(3)*I"]}),
    _c("h-alg-04", "Solve x^2 = 2x", "algebra", "basic", {"roots": ["0", "2"]}, phrasing="terse"),
    _c("h-alg-05", "Determine the real solutions of x^4 = 16", "algebra", "basic", {"roots": ["2", "-2"]}),
    _c("h-alg-06", "Solve (x + 2)/(x - 1) = 3", "algebra", "basic", {"roots": ["5/2"]}, phrasing="terse"),
    _c("h-alg-07", "Solve x^5 - x - 1 = 0 over the reals", "algebra", "advanced", {"roots": ["1.1673039782614187"]}),
    _c("h-sys-01", "Solve the equations 3a + 2b = 12 and a - b = -1", "systems", "basic", {"tuples": [["2", "3"]], "vars": ["a", "b"]}),
    _c("h-tr-01", "Solve cos(x) = 1/2", "transcendental", "intermediate", {"family": {"members": ["pi/3", "-pi/3", "5*pi/3"], "nonmembers": ["0", "pi"]}}, expect="partially_verified", phrasing="terse"),
    _c("h-tr-02", "Solve ln(x + 1) = 1", "transcendental", "basic", {"roots": ["E - 1"]}, phrasing="terse"),
    _c("h-dif-01", "Find the derivative of tan(x)", "calculus", "basic", {"expr": "1/cos(x)**2"}),
    _c("h-dif-02", "Differentiate exp(x^2) twice", "calculus", "intermediate", {"expr": "(4*x**2 + 2)*exp(x**2)"}),
    _c("h-dif-03", "What is d/dx of sqrt(x)?", "calculus", "basic", {"expr": "1/(2*sqrt(x))"}),
    _c("h-int-01", "Integrate sin(x)*cos(x) dx", "calculus", "basic", {"antiderivative": "sin(x)*cos(x)"}, phrasing="terse"),
    _c("h-int-02", "Find the area under y = x^3 from 0 to 2", "calculus", "basic", {"expr": "4"}),
    _c("h-int-03", "Evaluate the definite integral of 1/x from 1 to e^2", "calculus", "basic", {"expr": "2"}),
    _c("h-int-04", "∫_0^1 x^2 dx", "calculus", "basic", {"expr": "1/3"}, phrasing="unicode"),
    _c("h-lim-01", "lim_{x->0} (e^x - 1)/x", "calculus", "basic", {"expr": "1"}, phrasing="terse"),
    _c("h-lim-02", "Find the limit as x approaches infinity of (3x^2 + 1)/(x^2 - 5)", "calculus", "basic", {"expr": "3"}),
    _c("h-lim-03", "limit of x*sin(1/x) as x -> 0", "calculus", "intermediate", {"expr": "0"}),
    _c("h-ser-01", "Taylor expansion of 1/(1 - x) at 0 up to x^4", "calculus", "basic", {"series": "1 + x + x**2 + x**3 + x**4"}),
    _c("h-ser-02", "Compute the Maclaurin series of sin(x) to order 5", "calculus", "basic", {"series": "x - x**3/6 + x**5/120"}),
    _c("h-sum-01", "Sum of 1/(k*(k + 1)) for k from 1 to n", "calculus", "intermediate", {"expr": "n/(n + 1)"}),
    _c("h-sum-02", "Sum of (-1)^(k+1)/k for k = 1 to infinity", "calculus", "advanced", {"expr": "log(2)"}),
    _c("h-ode-01", "Solve y' = 2*x*y with y(0) = 1", "ode", "basic", {"ode": "exp(x**2)"}),
    _c("h-ode-02", "Solve y'' + 4y = 0, y(0) = 0, y'(0) = 2", "ode", "basic", {"ode": "sin(2*x)"}),
    _c("h-ode-03", "Solve dy/dt = -3y, y(0) = 5", "ode", "basic", {"ode": "5*exp(-3*t)", "var": "t"}),
    _c("h-la-01", "Find the eigenvalues of [[2, 0, 0], [0, 3, 4], [0, 4, 9]]", "linalg", "intermediate", {"eigen": {"1": 1, "2": 1, "11": 1}}),
    _c("h-la-02", "Compute the determinant of [[2, -1], [1, 3]]", "linalg", "basic", {"expr": "7"}),
    _c("h-la-03", "Invert the matrix [[1, 2], [3, 4]]", "linalg", "basic", {"matrix": [["-2", "1"], ["3/2", "-1/2"]]}),
    _c("h-la-04", "Solve [[2,1],[1,3]] x = b with b = [3, 5]", "linalg", "basic", {"vector": ["4/5", "7/5"]}),
    _c("h-id-01", "Prove that cosh(x)^2 - sinh(x)^2 = 1", "identity", "basic", {"bool": True}),
    _c("h-id-02", "Is sin(x + y) = sin(x) + sin(y)?", "identity", "basic", {"bool": False}),
    _c("h-id-03", "Verify that (a - b)(a + b) = a^2 - b^2", "identity", "basic", {"bool": True}),
    _c("h-id-04", "Show that exp(x + y) = exp(x)*exp(y)", "identity", "basic", {"bool": True}),
    _c("h-sim-01", "Simplify (x^3 - 1)/(x - 1)", "simplify", "basic", {"expr": "x**2 + x + 1"}),
    _c("h-sim-02", "Factor x^3 - 1", "simplify", "basic", {"expr": "x**3 - 1", "form": "factor"}),
    _c("h-ev-01", "Evaluate 3^4 - 2^5", "evaluate", "basic", {"expr": "49"}),
    _c("h-ev-02", "What is the value of sqrt(50) - sqrt(18)?", "evaluate", "basic", {"expr": "2*sqrt(2)"}),
    _c("h-no-01", "Who wrote Hamlet?", "none", "basic", {"none": True}, expect="failed"),
    _c("h-no-02", "Is the ideal gas law pV = nRT valid at high pressure?", "none", "basic", {"none": True}, expect="failed"),
)


# Second held-out set: written after every fix prompted by the development and first held-out sets, run once with the
# code frozen. Its first-run results are what calibration.json is fitted on (the generalisation estimate). It includes
# questions outside the parser's coverage, so abstention ("unverified" / "failed") is measured too.
HOLDOUT2: tuple[Case, ...] = (
    _c("h2-alg-01", "What values of x satisfy x^2 - x - 6 = 0?", "algebra", "basic", {"roots": ["3", "-2"]}),
    _c("h2-alg-02", "Solve 5x + 2 = 3x - 8", "algebra", "basic", {"roots": ["-5"]}, phrasing="terse"),
    _c("h2-alg-03", "Find real x such that 2^(x+1) = 32", "algebra", "basic", {"roots": ["4"]}),
    _c("h2-alg-04", "Solve x^3 - 3x^2 + 3x - 1 = 0", "algebra", "basic", {"roots": ["1"]}, phrasing="terse"),
    _c("h2-alg-05", "Solve x^4 + x^2 - 2 = 0", "algebra", "intermediate", {"roots": ["1", "-1", "sqrt(2)*I", "-sqrt(2)*I"]}, phrasing="terse"),
    _c("h2-alg-06", "Solve sqrt(2x + 3) = x", "algebra", "intermediate", {"roots": ["3"]}, phrasing="terse"),
    _c("h2-alg-07", "Solve |2x + 1| = 7", "algebra", "intermediate", {"roots": ["3", "-4"]}, phrasing="terse"),
    _c("h2-alg-08", "Solve x^3 + x - 3 = 0 over the reals", "algebra", "advanced", {"roots": ["1.2134116627622296"]}),
    _c("h2-sys-01", "Solve the system x + 2y = 5 and 3x - y = 1", "systems", "basic", {"tuples": [["1", "2"]], "vars": ["x", "y"]}),
    _c("h2-sys-02", "Solve x*y = 6 and x + y = 5", "systems", "intermediate", {"tuples": [["2", "3"], ["3", "2"]], "vars": ["x", "y"]}, phrasing="terse"),
    _c("h2-tr-01", "Solve sin(2x) = 1", "transcendental", "intermediate", {"family": {"members": ["pi/4", "5*pi/4", "-3*pi/4"], "nonmembers": ["pi/2", "0"]}}, expect="partially_verified", phrasing="terse"),
    _c("h2-tr-02", "Solve exp(2x) = 7 over the reals", "transcendental", "basic", {"roots": ["log(7)/2"]}),
    _c("h2-tr-03", "Solve x^x = 4", "transcendental", "advanced", {"roots": ["2"]}, expect="partially_verified", phrasing="terse"),
    _c("h2-dif-01", "Differentiate log(sin(x))", "calculus", "basic", {"expr": "cos(x)/sin(x)"}, phrasing="terse"),
    _c("h2-dif-02", "Find the derivative of x^2 * ln(x)", "calculus", "basic", {"expr": "2*x*log(x) + x"}),
    _c("h2-dif-03", "Compute the fourth derivative of x^5", "calculus", "basic", {"expr": "120*x"}),
    _c("h2-dif-04", "Differentiate 1/(1 + x^2) three times", "calculus", "intermediate", {"expr": "-24*x*(x**2 - 1)/(x**2 + 1)**4"}),
    _c("h2-int-01", "Integrate x^3 from -1 to 2", "calculus", "basic", {"expr": "15/4"}),
    _c("h2-int-02", "Find the indefinite integral of 1/(x^2 + 4)", "calculus", "intermediate", {"antiderivative": "1/(x**2 + 4)"}),
    _c("h2-int-03", "Integrate sqrt(x) from 0 to 4", "calculus", "basic", {"expr": "16/3"}),
    _c("h2-int-04", "Integrate exp(-x) from 0 to infinity", "calculus", "basic", {"expr": "1"}),
    _c("h2-int-05", "∫ x^2 e^x dx", "calculus", "intermediate", {"antiderivative": "x**2*exp(x)"}, phrasing="unicode"),
    _c("h2-int-06", "Integrate 1/x^2 from 1 to infinity", "calculus", "basic", {"expr": "1"}),
    _c("h2-int-07", "Integrate tan(x) dx", "calculus", "intermediate", {"antiderivative": "tan(x)"}, phrasing="terse"),
    _c("h2-lim-01", "Find the limit of sin(3x)/x as x approaches 0", "calculus", "basic", {"expr": "3"}),
    _c("h2-lim-02", "limit of (1 + 2/x)^x as x -> oo", "calculus", "intermediate", {"expr": "exp(2)"}),
    _c("h2-lim-03", "limit of x^2*exp(-x) as x -> infinity", "calculus", "basic", {"expr": "0"}),
    _c("h2-lim-04", "limit of (sqrt(x + 1) - 1)/x as x -> 0", "calculus", "intermediate", {"expr": "1/2"}),
    _c("h2-lim-05", "limit of abs(x)/x as x -> 0", "calculus", "intermediate", {"dne": True}),
    _c("h2-ser-01", "Taylor series of exp(2x) around 0 up to order 3", "calculus", "basic", {"series": "1 + 2*x + 2*x**2 + 4*x**3/3"}),
    _c("h2-ser-02", "Maclaurin series of 1/(1 + x) up to x^3", "calculus", "basic", {"series": "1 - x + x**2 - x**3"}),
    _c("h2-sum-01", "Sum of 2^k for k from 0 to n", "calculus", "intermediate", {"expr": "2**(n + 1) - 1"}),
    _c("h2-sum-02", "sum 1/k! for k = 0 to infinity", "calculus", "intermediate", {"expr": "E"}, phrasing="terse"),
    _c("h2-sum-03", "Compute the sum of k^3 for k = 1 to 10", "calculus", "basic", {"expr": "3025"}),
    _c("h2-ode-01", "Solve y' = -y/2 with y(0) = 4", "ode", "basic", {"ode": "4*exp(-x/2)"}),
    _c("h2-ode-02", "Solve y'' + y' - 2y = 0, y(0) = 1, y'(0) = 1", "ode", "intermediate", {"ode": "exp(x)"}),
    _c("h2-ode-03", "Solve y' = x^2", "ode", "basic", {"ode_general": "y' - x**2", "order": 1}, phrasing="terse"),
    _c("h2-la-01", "Find the eigenvalues of [[1, 2], [2, 1]]", "linalg", "basic", {"eigen": {"3": 1, "-1": 1}}),
    _c("h2-la-02", "determinant of [[a, b], [c, d]]", "linalg", "basic", {"expr": "a*d - b*c"}, phrasing="terse"),
    _c("h2-la-03", "Find the inverse of [[2, 0], [0, 5]]", "linalg", "basic", {"matrix": [["1/2", "0"], ["0", "1/5"]]}),
    _c("h2-la-04", "Find the null space of [[1, 1, 1]]", "linalg", "intermediate", {"span": [["-1", "1", "0"], ["-1", "0", "1"]]}),
    _c("h2-id-01", "Prove that sin(x)^2 = (1 - cos(2x))/2", "identity", "basic", {"bool": True}),
    _c("h2-id-02", "Is log(x^2) = 2 log(x)?", "identity", "intermediate", {"bool": False}),
    _c("h2-id-03", "Verify that 1 + tan(x)^2 = sec(x)^2", "identity", "basic", {"bool": True}),
    _c("h2-sim-01", "Simplify (x^2 + 2x + 1)/(x + 1)", "simplify", "basic", {"expr": "x + 1"}),
    _c("h2-sim-02", "Expand (2x - 3)^2", "simplify", "basic", {"expr": "4*x**2 - 12*x + 9", "form": "expand"}),
    _c("h2-ev-01", "Evaluate 2^0.5 * 2^1.5", "evaluate", "basic", {"expr": "4"}),
    _c("h2-ev-02", "What is cos(pi) + sin(pi/2)?", "evaluate", "basic", {"expr": "0"}),
    # outside the parser's coverage: the honest outcome is an abstention, not a confident wrong answer
    _c("h2-out-01", "Find the maximum of x^2 - 4x + 1 on the interval [0, 5]", "optimization", "intermediate", {"extrema": {"maximum": "6"}}),
    _c("h2-out-02", "What is 15% of 80?", "arithmetic", "basic", {"expr": "12"}),
    _c("h2-out-03", "Find the slope of the tangent to y = x^2 at x = 3", "calculus", "intermediate", {"slope": "6"}),
    _c("h2-no-01", "What year did the French Revolution start?", "none", "basic", {"none": True}, expect="failed"),
    _c("h2-no-02", "Calculate the GDP growth of France", "none", "basic", {"none": True}, expect="failed"),
)


# Third held-out set: written after the tool expansion (optimization, inequalities, tangents, number theory,
# recurrences, transforms, vector calculus, probability, statistics, quadrature), run once with the code frozen.
# calibration.json is fitted on its first run. Numeric gold values were computed with NumPy / SciPy / mpmath
# directly, not with the agent's tools.
HOLDOUT3: tuple[Case, ...] = (
    _c("h3-opt-01", "What is the largest value of 3x - x^3 on [0, 2]?", "optimization", "basic", {"extrema": {"maximum": "2"}}),
    _c("h3-opt-02", "Find the minimum of x + 1/x for x > 0", "optimization", "intermediate", {"extrema": {"minimum": "2"}}),
    _c("h3-opt-03", "Find the global minimum of (x - 3)^2 + 4", "optimization", "basic", {"extrema": {"minimum": "4"}}),
    _c("h3-opt-04", "Find the maximum and minimum of sin(x) + cos(x) on [0, pi]", "optimization", "intermediate", {"extrema": {"maximum": "sqrt(2)", "minimum": "-1"}}),
    _c("h3-ineq-01", "Solve 2x - 5 >= 3", "inequality", "basic", {"set": "Interval(4, oo)"}, phrasing="terse"),
    _c("h3-ineq-02", "Solve x^2 < 9", "inequality", "basic", {"set": "Interval.open(-3, 3)"}, phrasing="terse"),
    _c("h3-ineq-03", "For which x is x^3 - x > 0?", "inequality", "intermediate", {"set": "Union(Interval.open(-1, 0), Interval.open(1, oo))"}),
    _c("h3-tan-01", "Find the slope of the curve y = sin(x) at x = 0", "calculus", "basic", {"slope": "1"}),
    _c("h3-tan-02", "Find the tangent line to y = x^3 at x = 1", "calculus", "basic", {"slope": "3", "line": "3*x - 2"}),
    _c("h3-nt-01", "Find the greatest common divisor of 462 and 1071", "number_theory", "basic", {"nt": 21}),
    _c("h3-nt-02", "Is 221 a prime number?", "number_theory", "basic", {"nt": False}),
    _c("h3-nt-03", "Prime factorization of 1001", "number_theory", "basic", {"nt": {"7": 1, "11": 1, "13": 1}}, phrasing="terse"),
    _c("h3-nt-04", "What is 2^10 mod 1000?", "number_theory", "basic", {"nt": 24}),
    _c("h3-nt-05", "Find the least common multiple of 12 and 18", "number_theory", "basic", {"nt": 36}),
    _c("h3-nt-06", "What is the next prime after 1000?", "number_theory", "basic", {"nt": 1009}),
    _c("h3-rec-01", "Solve a(n) = 2a(n-1) with a(0) = 3", "recurrence", "basic", {"closed": "3*2**n"}, phrasing="terse"),
    _c("h3-rec-02", "Solve the recurrence a(n) = a(n-1) + 2 with a(0) = 1", "recurrence", "basic", {"closed": "2*n + 1"}),
    _c("h3-lt-01", "Laplace transform of exp(2t)", "transform", "basic", {"expr": "1/(s - 2)", "vars": ["s"]}, phrasing="terse"),
    _c("h3-lt-02", "Inverse Laplace transform of 1/(s + 3)", "transform", "basic", {"expr": "exp(-3*t)", "vars": ["t"]}, phrasing="terse"),
    _c("h3-lt-03", "Laplace transform of cos(2t)", "transform", "basic", {"expr": "s/(s**2 + 4)", "vars": ["s"]}, phrasing="terse"),
    _c("h3-vc-01", "Find the gradient of x*y*z", "vector_calculus", "basic", {"vector": ["y*z", "x*z", "x*y"]}),
    _c("h3-vc-02", "Compute the divergence of the field (x^2, y^2, z^2)", "vector_calculus", "basic", {"expr": "2*x + 2*y + 2*z"}),
    _c("h3-vc-03", "Find the curl of [y*z, x*z, x*y]", "vector_calculus", "intermediate", {"vector": ["0", "0", "0"]}),
    _c("h3-pr-01", "If X ~ Poisson(2), find P(X = 0)", "probability", "basic", {"number": "0.1353352832366127"}),
    _c("h3-pr-02", "X ~ Uniform(0, 10). What is P(X > 7)?", "probability", "basic", {"number": "0.3"}),
    _c("h3-pr-03", "Find the variance of a Binomial(20, 0.5) random variable", "probability", "basic", {"number": "5"}),
    _c("h3-pr-04", "For X ~ N(0, 1), what is P(-1.96 < X < 1.96)?", "probability", "intermediate", {"number": "0.950004209703559"}),
    _c("h3-st-01", "What is the median of 3, 1, 4, 1, 5, 9, 2, 6?", "statistics", "basic", {"stats": {"median": 3.5}}),
    _c("h3-st-02", "Find the correlation between [1, 2, 3, 4, 5] and [2, 4, 5, 4, 5]", "statistics", "basic", {"stats": {"r": 0.7745966692414834}}),
    _c("h3-st-03", "Compute the variance of the data [2, 4, 6, 8]", "statistics", "basic", {"stats": {"variance": 6.666666666666667}}),
    _c("h3-pct-01", "What is 20% of 250?", "evaluate", "basic", {"expr": "50"}),
    _c("h3-ev-01", "Calculate 7! / (3! * 4!)", "evaluate", "basic", {"expr": "35"}),
    _c("h3-nq-01", "Integrate exp(-x^2)*cos(x) from 0 to 1", "calculus", "advanced", {"number": "0.656174362731506829816681216301", "tol": 1e-9}, expect="partially_verified"),
    _c("h3-alg-01", "Solve 4x^2 - 12x + 9 = 0", "algebra", "basic", {"roots": ["3/2"]}, phrasing="terse"),
    _c("h3-alg-02", "Find the roots of x^3 - 8", "algebra", "basic", {"roots": ["2", "-1 + sqrt(3)*I", "-1 - sqrt(3)*I"]}),
    _c("h3-dif-01", "Differentiate cos(x)^2", "calculus", "basic", {"expr": "-2*sin(x)*cos(x)"}, phrasing="terse"),
    _c("h3-int-01", "Integrate 2x/(x^2 + 1) dx", "calculus", "basic", {"antiderivative": "2*x/(x**2 + 1)"}, phrasing="terse"),
    _c("h3-lim-01", "limit of (e^(2x) - 1)/x as x -> 0", "calculus", "basic", {"expr": "2"}),
    _c("h3-ser-01", "Taylor series of sqrt(1 + x) around 0 up to order 2", "calculus", "intermediate", {"series": "1 + x/2 - x**2/8"}),
    _c("h3-sum-01", "Sum of 1/3^k for k from 1 to infinity", "calculus", "basic", {"expr": "1/2"}),
    _c("h3-ode-01", "Solve y' = 3y with y(0) = 2", "ode", "basic", {"ode": "2*exp(3*x)"}),
    _c("h3-la-01", "Find the determinant of [[3, 1], [4, 2]]", "linalg", "basic", {"expr": "2"}),
    _c("h3-id-01", "Prove that tan(x)*cos(x) = sin(x)", "identity", "basic", {"bool": True}),
    _c("h3-id-02", "Is (a + b)^3 = a^3 + b^3?", "identity", "basic", {"bool": False}),
    _c("h3-sim-01", "Simplify (x^2 - 9)/(x + 3)", "simplify", "basic", {"expr": "x - 3"}),
    # outside coverage: an abstention is the honest outcome
    _c("h3-out-01", "Find the area between y = x and y = x^2", "calculus", "intermediate", {"expr": "1/6"}, expect="unverified"),
    _c("h3-out-02", "What is the probability of rolling two sixes with two dice?", "probability", "basic", {"expr": "1/36"}, expect="failed"),
    _c("h3-out-03", "Find the inverse function of f(x) = 2x + 3", "algebra", "basic", {"expr": "(x - 3)/2"}, expect="unverified"),
    _c("h3-no-01", "Who discovered penicillin?", "none", "basic", {"none": True}, expect="failed"),
    _c("h3-no-02", "Describe the mean free path of molecules in a gas", "none", "basic", {"none": True}, expect="failed"),
)


# Known-wrong candidates for the verifier (question, tool, args, data or None = run the engine on args)
ADVERSARIAL: tuple[tuple[str, str, dict[str, Any], dict[str, Any] | None], ...] = (
    ("Solve x^2 = 9", "axiom_solve", {"equations": "x^2 = 8", "variables": "x"}, None),
    ("Solve x^2 = 9", "axiom_solve", {"equations": "x^2 = 9", "variables": "x"}, {"solutions": [{"x": "3"}, {"x": "4"}], "complete": True}),
    ("Solve x^2 = 9", "axiom_solve", {"equations": "x^2 = 9", "variables": "x"}, {"solutions": [{"x": "3"}], "complete": True}),
    ("Find all real x with x^2 = 4", "axiom_solve", {"equations": "x^2 = 4", "variables": "x", "domain": "real"}, {"solutions": [{"x": "2"}], "complete": True}),
    ("Solve x^3 - x = 0", "axiom_solve", {"equations": "x^3 - x = 0", "variables": "x"}, {"solutions": [{"x": "0"}, {"x": "1"}], "complete": True}),
    ("Differentiate sin(x)*x", "axiom_calculus", {"expression": "sin(x)*x", "operation": "diff", "variable": "x"}, {"result": "cos(x)*x"}),
    ("Differentiate sin(x)*x", "axiom_calculus", {"expression": "sin(x)", "operation": "diff", "variable": "x"}, None),
    ("Find the second derivative of x^4", "axiom_calculus", {"expression": "x^4", "operation": "diff", "variable": "x", "order": 1}, None),
    ("Find the antiderivative of x*exp(x)", "axiom_calculus", {"expression": "x*exp(x)", "operation": "integrate", "variable": "x"}, {"result": "x*exp(x)"}),
    ("Integrate x^2 from 0 to 1", "axiom_calculus", {"expression": "x^2", "operation": "integrate", "variable": "x", "lower": "0", "upper": "1"}, {"result": "1/2"}),
    ("Integrate x^2 from 0 to 1", "axiom_calculus", {"expression": "x^2", "operation": "integrate", "variable": "x", "lower": "0", "upper": "2"}, None),
    ("Find the limit of sin(x)/x as x approaches 0", "axiom_calculus", {"expression": "sin(x)/x", "operation": "limit", "variable": "x", "point": "0"}, {"result": "0"}),
    ("limit of 1/x as x -> 0 from the right", "axiom_calculus", {"expression": "1/x", "operation": "limit", "variable": "x", "point": "0-"}, None),
    ("Taylor series of exp(x) around 0 up to order 4", "axiom_calculus", {"expression": "exp(x)", "operation": "series", "variable": "x", "point": "0", "order": 5}, {"result": "1 + x + x**2/2 + x**3/3 + x**4/24"}),
    ("Sum of k^2 for k from 1 to n", "axiom_calculus", {"expression": "k^2", "operation": "sum", "variable": "k", "lower": "1", "upper": "n"}, {"result": "n**3/3"}),
    ("sum 1/k^2 for k = 1 to infinity", "axiom_calculus", {"expression": "1/k^2", "operation": "sum", "variable": "k", "lower": "1", "upper": "oo"}, {"result": "pi**2/8"}),
    ("Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "axiom_dsolve", {"equation": "y'' + y = 0", "func": "y(x)", "ics": {"y(0)": "1", "y'(0)": "0"}}, {"rhs": "sin(x)"}),
    ("Solve y'' + y = 0 with y(0) = 1 and y'(0) = 0", "axiom_dsolve", {"equation": "y'' + y = 0", "func": "y(x)", "ics": {"y(0)": "1", "y'(0)": "0"}}, {"rhs": "exp(x)"}),
    ("Find the eigenvalues of [[4, 1], [2, 3]]", "axiom_linalg", {"matrix": [[4, 1], [2, 3]], "operation": "eigen"}, {"result": [{"eigenvalue": "5", "multiplicity": 1, "eigenvectors": [["1", "1"]]}, {"eigenvalue": "3", "multiplicity": 1, "eigenvectors": [["1", "-1"]]}]}),
    ("determinant of [[1,2],[3,4]]", "axiom_linalg", {"matrix": [[1, 2], [3, 4]], "operation": "det"}, {"result": "2"}),
    ("determinant of [[1,2],[3,4]]", "axiom_linalg", {"matrix": [[1, 2], [3, 5]], "operation": "det"}, None),
    ("Find the inverse of [[4, 1], [2, 3]]", "axiom_linalg", {"matrix": [[4, 1], [2, 3]], "operation": "inv"}, {"result": [["3/10", "1/10"], ["-1/5", "2/5"]]}),
    ("Prove that (x + y)^2 = x^2 + y^2", "axiom_verify_identity", {"lhs": "(x + y)^2", "rhs": "x^2 + y^2"}, {"equivalent": True}),
    ("Is sqrt(x^2) = x for all x?", "axiom_verify_identity", {"lhs": "sqrt(x^2)", "rhs": "x"}, {"equivalent": True}),
    ("Prove that sin(2x) = 2 sin(x) cos(x)", "axiom_verify_identity", {"lhs": "sin(2*x)", "rhs": "2*sin(x)*cos(x)"}, {"equivalent": False, "counterexample": {"x": 0.5}}),
    ("Simplify (x^2 - 1)/(x - 1)", "axiom_simplify", {"expression": "(x^2 - 1)/(x - 1)"}, {"simplified": "x - 1"}),
    ("Evaluate 2^10 + sqrt(16)", "axiom_simplify", {"expression": "2^10 + sqrt(16)"}, {"simplified": "1024"}),
    ("Find the maximum of x^2 - 4x + 1 on the interval [0, 5]", "axiom_optimize", {"expression": "x^2 - 4x + 1", "variable": "x", "lower": "0", "upper": "5"},
     {"maximum": {"value": "1", "numeric": 1.0, "at": ["0"], "attained": True}, "minimum": {"value": "-3", "numeric": -3.0, "at": ["2"], "attained": True}}),
    ("Find the maximum of x^2 - 4x + 1 on the interval [0, 5]", "axiom_optimize", {"expression": "x^2 - 4x + 1", "variable": "x", "lower": "0", "upper": "3"}, None),
    ("Find the maximum of x^3 - 3x", "axiom_optimize", {"expression": "x^3 - 3x", "variable": "x"},
     {"maximum": {"value": "2", "numeric": 2.0, "at": ["-1"], "attained": True}, "minimum": {"value": "-2", "numeric": -2.0, "at": ["1"], "attained": True}}),
    ("Solve x^2 - 4 > 0", "axiom_inequality", {"inequality": "x^2 - 4 > 0", "variable": "x"}, {"solution_set": "Interval.open(2, oo)"}),
    ("Solve x^2 - 4 > 0", "axiom_inequality", {"inequality": "x^2 - 4 >= 0", "variable": "x"}, None),
    ("Find the slope of the tangent to y = x^2 at x = 3", "axiom_tangent", {"expression": "x^2", "point": "3", "variable": "x"},
     {"slope": "9", "tangent_line": "y = 9*x - 18", "normal_line": "", "value": "9"}),
    ("Find the prime factorization of 360", "axiom_number_theory", {"operation": "factorize", "numbers": ["360"]}, {"result": {"2": 3, "3": 2, "7": 1}, "text": "2^3 * 3^2 * 7"}),
    ("Is 91 prime?", "axiom_number_theory", {"operation": "isprime", "numbers": ["91"]}, {"result": True, "text": "91 is prime"}),
    ("Find the gcd of 84 and 126", "axiom_number_theory", {"operation": "gcd", "numbers": ["84", "126"]}, {"result": 21, "text": "21"}),
    ("Solve the recurrence a(n) = a(n-1) + a(n-2) with a(0) = 0, a(1) = 1", "axiom_recurrence",
     {"recurrence": "a(n) = a(n-1) + a(n-2)", "initial": {"a(0)": "0", "a(1)": "1"}, "function": "a", "variable": "n"}, {"result": "2**n - 1"}),
    ("Find the Laplace transform of t^2*exp(-t)", "axiom_transform", {"expression": "t^2*exp(-t)", "transform": "laplace"}, {"result": "2/(s + 1)**2"}),
    ("Compute the gradient of x^2*y + z", "axiom_vector_calculus", {"operation": "gradient", "expression": "x^2*y + z", "variables": ["x", "y", "z"]}, {"result": ["2*x*y", "x**2", "0"]}),
    ("If X ~ N(0, 1), find P(X <= 1)", "axiom_probability", {"distribution": "normal", "parameters": ["0", "1"], "query": "probability", "upper": "1"}, {"result": "0.5", "numeric_value": 0.5}),
    ("Find the mean and standard deviation of 2, 4, 4, 4, 5, 5, 7, 9", "calcula_statistics",
     {"operation": "describe", "data": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]}, {"result": {"mean": 5.5, "median": 4.5, "variance": 4.5714285714, "std": 2.138}, "text": ""}),
    ("Integrate sin(x)/log(x) from 2 to 3", "axiom_nintegrate", {"expression": "sin(x)/log(x)", "lower": "2", "upper": "3"}, {"value": 0.7, "result": "0.7"}),
)


# Grading (against gold answers only) --------------------------------------------------------------------------------

def _val(text: Any, local: dict[str, Any] | None = None) -> sp.Expr:
    text = re.sub(r"\blambda\b", "lambda_", str(text))  # charpoly variable; "lambda" is a Python keyword
    return E.safe_parse_expr(text, local_dict={**(local or {}), "lambda_": sp.Symbol("lambda")})


def _equal(a: sp.Expr, b: sp.Expr, tol: float = 1e-9) -> bool:
    try:
        if a == b or sp.simplify(a - b) == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    syms = sorted((a.free_symbols | b.free_symbols), key=lambda s: s.name)
    points = [{s: sp.Rational(str(E._PARAM_VALUES[(i + k) % len(E._PARAM_VALUES)])) for i, s in enumerate(syms)} for k in range(3)] if syms else [{}]
    for pt in points:
        va, vb = E._num(a, pt), E._num(b, pt)
        if va is None or vb is None or abs(va - vb) > tol * max(1.0, abs(vb)):
            return False
    return True


def _roots_match(found: list[sp.Expr], gold: list[sp.Expr], tol: float = 1e-9) -> bool:
    left = list(found)
    for g in gold:
        hit = next((f for f in left if _equal(f, g, tol)), None)
        if hit is None:
            return False
        left.remove(hit)
    return not left


def grade(case: Case, out: dict[str, Any]) -> tuple[bool, str]:
    """Is the agent's answer correct? Judged on the gold answer only (never on the agent's own verifier)."""
    g, status, ans = case.gold, out.get("status"), out.get("answer") or {}
    if "none" in g:
        return status == "failed", "abstained" if status == "failed" else f"answered a non-math question ({status})"
    if status == "failed":
        return False, "no answer"
    try:
        if "dne" in g:
            text = str(ans.get("text", ""))
            ok = "does not exist" in text or (status != "verified" and any(t in text for t in ("zoo", "nan", "AccumBounds")))
            return ok, "limit does not exist" if ok else f"claimed verified limit {text!r}"
        if "roots" in g:
            sols = ans.get("solutions") or []
            var = next((k for s in sols for k in s), None)
            found = [_val(s[var]) for s in sols if var in s]
            ok = _roots_match(found, [_val(r) for r in g["roots"]], tol=1e-8)
            return ok, "" if ok else f"roots {[str(f) for f in found]} != {g['roots']}"
        if "tuples" in g:
            sols = ans.get("solutions") or []
            found = [tuple(_val(s[v]) for v in g["vars"]) for s in sols if all(v in s for v in g["vars"])]
            gold = [tuple(_val(x) for x in t) for t in g["tuples"]]
            left = list(found)
            for t in gold:
                hit = next((f for f in left if all(_equal(a, b) for a, b in zip(f, t, strict=True))), None)
                if hit is None:
                    return False, f"missing {t}"
                left.remove(hit)
            return not left, "" if not left else f"extra solutions {left}"
        if "family" in g:
            sset = ans.get("solution_set")
            if not sset:
                return False, "no general solution set reported"
            members = sp.sympify(sset)  # engine-generated set expression (ImageSet / Union), not user input
            ok = all(members.contains(_val(m)) == sp.true for m in g["family"]["members"]) and all(
                members.contains(_val(m)) != sp.true for m in g["family"]["nonmembers"]
            )
            return ok, "" if ok else f"solution set {sset} wrong"
        if "extrema" in g:
            for name, want in g["extrema"].items():
                got = (ans.get(name) or {})
                if want == "unbounded":
                    if not got.get("unbounded"):
                        return False, f"{name} should be unbounded, got {got.get('value')}"
                elif got.get("unbounded") or got.get("value") is None or not _equal(_val(got["value"]), _val(want)):
                    return False, f"{name} {got.get('value')} != {want}"
            return True, ""
        if "set" in g:
            got_set, want_set = sp.sympify(ans.get("solution_set")), sp.sympify(g["set"])  # engine/gold set expressions
            ok = got_set == want_set or sp.simplify(got_set.symmetric_difference(want_set)) is sp.S.EmptySet
            return ok, "" if ok else f"{got_set} != {want_set}"
        if "slope" in g:
            ok = _equal(_val(ans.get("slope")), _val(g["slope"]))
            if ok and "line" in g:
                ok = _equal(_val(str(ans.get("tangent_line")).split("=", 1)[1]), _val(g["line"]))
            return ok, "" if ok else f"slope {ans.get('slope')} / line {ans.get('tangent_line')} wrong"
        if "nt" in g:
            res = ans.get("result")
            want = g["nt"]
            if isinstance(want, dict) and "solve" in want:  # diophantine: check the family solves a*x + b*y = c
                a, b, c = want["solve"]
                ok = isinstance(res, dict) and all(a * (res["x0"] + res["step_x"] * t) + b * (res["y0"] + res["step_y"] * t) == c for t in (0, 1, 5))
            else:
                ok = json.dumps(res, sort_keys=True) == json.dumps(want, sort_keys=True)
            return ok, "" if ok else f"{res} != {want}"
        if "closed" in g:
            n = sp.Symbol("n")
            got = _val(str(ans.get("text", "")).split("=", 1)[1], {"n": n})
            want = _val(g["closed"], {"n": n})
            ok = all(_equal(got.subs(n, k), want.subs(n, k)) for k in range(8))
            return ok, "" if ok else f"{got} != {g['closed']}"
        if "number" in g:
            got = ans.get("value")
            ok = got is not None and abs(complex(got) - float(g["number"])) <= float(g.get("tol", 1e-9)) * max(1.0, abs(float(g["number"])))
            return ok, "" if ok else f"{got} != {g['number']}"
        if "stats" in g:
            res = ans.get("result") or {}
            bad = [k for k, v in g["stats"].items() if k not in res or abs(float(res[k]) - float(v)) > 1e-6 * max(1.0, abs(float(v)))]
            return not bad, "" if not bad else f"wrong {bad}: {res}"
        text = str(ans.get("text", ""))
        if "expr" in g:
            local = {v: sp.Symbol(v) for v in g.get("vars", [])}
            got = _val(text.split("=")[-1] if case.domain == "linalg" and "lambda =" in text else text, local)
            if "params" in g:
                pin = {sp.Symbol(k): sp.Rational(v) for k, v in g["params"].items()}
                got, want = got.subs(pin), _val(g["expr"]).subs(pin)
            else:
                want = _val(g["expr"], local)
            ok = _equal(got, want)
            if ok and g.get("form") == "factor":
                ok = isinstance(sp.factor(got), sp.Mul) and isinstance(got, sp.Mul)
            if ok and g.get("form") == "expand":
                ok = sp.expand(got) == got
            return ok, "" if ok else f"{text!r} != {g['expr']!r}"
        if "antiderivative" in g:
            x = sp.Symbol("x")
            ok = _equal(sp.diff(_val(text), x), _val(g["antiderivative"]))
            return ok, "" if ok else f"d/dx({text}) != {g['antiderivative']}"
        if "series" in g:
            ok = sp.expand(_val(text) - _val(g["series"])) == 0
            return ok, "" if ok else f"{text!r} != {g['series']!r}"
        if "ode" in g or "ode_general" in g:
            rhs_text = text.split("=", 1)[1] if "=" in text else text
            var = g.get("var", "x")
            y, x = sp.Function("y"), sp.Symbol(var)
            rhs = _val(rhs_text, {var: x})
            if "ode" in g:
                ok = _equal(rhs, _val(g["ode"], {var: x}))
                return ok, "" if ok else f"{rhs} != {g['ode']}"
            ode = E._normalize_ode_primes(g["ode_general"], "y", var)
            lhs = E.safe_parse_expr(ode, local_dict={var: x, "y": y})
            chk = sp.checkodesol(sp.Eq(lhs, 0), sp.Eq(y(x), rhs), func=y(x))
            constants = {s for s in rhs.free_symbols if s.name.startswith("C")}
            ok = bool(chk[0]) and len(constants) == g["order"]
            return ok, "" if ok else f"{rhs} is not the general solution"
        res = ans.get("result")
        if "eigen" in g:
            found = {str(sp.simplify(_val(item["eigenvalue"]))): int(item["multiplicity"]) for item in res or []}
            want = {str(sp.simplify(_val(k))): v for k, v in g["eigen"].items()}
            return found == want, "" if found == want else f"{found} != {want}"
        if "matrix" in g or "rref" in g:
            rows = res["rref"] if "rref" in g else res
            ok = sp.simplify(sp.Matrix([[_val(c) for c in r] for r in rows]) - sp.Matrix([[_val(c) for c in r] for r in g.get("matrix") or g["rref"]])) == sp.zeros(len(rows), len(rows[0]))
            return ok, "" if ok else f"{rows} wrong"
        if "vector" in g:
            ok = all(_equal(_val(a), _val(b)) for a, b in zip(res, g["vector"], strict=True))
            return ok, "" if ok else f"{res} != {g['vector']}"
        if "span" in g:
            A = sp.Matrix([[_val(c) for c in v] for v in res]).T
            B = sp.Matrix([[_val(c) for c in v] for v in g["span"]]).T
            ok = A.rank() == B.rank() == sp.Matrix.hstack(A, B).rank()
            return ok, "" if ok else f"span {res} != {g['span']}"
        if "bool" in g:
            ok = bool(ans.get("equivalent")) == g["bool"]
            return ok, "" if ok else f"equivalent={ans.get('equivalent')} expected {g['bool']}"
    except Exception as exc:  # noqa: BLE001 - an ungradable answer is wrong
        return False, f"grading error: {type(exc).__name__}: {str(exc)[:160]}"
    return False, "no gold comparison for this case"


# Statistics -------------------------------------------------------------------------------------------------------

def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def fit_calibration(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per status: P(correct | status), Laplace-smoothed (k + 1) / (n + 2), with a Wilson 95% lower bound."""
    out: dict[str, dict[str, Any]] = {}
    for status in STATUSES:
        sel = [r for r in rows if r["status"] == status and r["domain"] != "none"]
        k, n = sum(1 for r in sel if r["correct"]), len(sel)
        out[status] = {"n": n, "correct": k, "confidence": round((k + 1) / (n + 2), 4), "lower_95": round(wilson_lower(k, n), 4)}
    return out


def _cross_fitted(rows: list[dict[str, Any]]) -> dict[str, float]:
    """ECE and Brier of the status -> confidence map, each half scored with the map fitted on the other half."""
    from tribos.agentic.calibration_stats import brier, ece

    scored = [r for r in rows if r["domain"] != "none"]
    halves = [[r for i, r in enumerate(scored) if i % 2 == h] for h in (0, 1)]
    probs, labels = [], []
    for h in (0, 1):
        cal = fit_calibration(halves[1 - h])
        for r in halves[h]:
            probs.append(cal[r["status"]]["confidence"])
            labels.append(1 if r["correct"] else 0)
    return {"ece": round(float(ece(probs, labels, bins=10)), 4), "brier": round(float(brier(probs, labels)), 4), "n": len(labels)}


def adversarial_report() -> dict[str, Any]:
    from .agent import TOOL_FUNCS, TOOL_SCHEMAS
    from .verifier import verify

    accepted = []
    for question, tool, args, data in ADVERSARIAL:
        if data is None:
            data = TOOL_FUNCS[tool](**TOOL_SCHEMAS[tool](**args).model_dump())
        verdict = verify(parse_problem(question), tool, args, data)
        if verdict.status in ("verified", "partially_verified"):
            accepted.append({"question": question, "tool": tool, "status": verdict.status})
    return {"n": len(ADVERSARIAL), "false_accepts": len(accepted), "false_accept_rate": round(len(accepted) / len(ADVERSARIAL), 4), "accepted": accepted}


# Runner -----------------------------------------------------------------------------------------------------------

async def run_benchmark(cases: tuple[Case, ...] = BENCHMARK) -> dict[str, Any]:
    from .agent import MathAgentConfig, solve_math_problem

    rows: list[dict[str, Any]] = []
    for case in cases:
        t0 = time.perf_counter()
        run = await solve_math_problem(case.question, config=MathAgentConfig())
        out = run.to_dict()
        correct, why = grade(case, out)
        rows.append({
            **{k: v for k, v in asdict(case).items() if k != "gold"},
            "status": out["status"],
            "correct": correct,
            "why": why,
            "answer": str(out["answer"].get("text", ""))[:200],
            "parsed_kind": out["problem"].get("kind", "unknown"),
            "tool_calls": out["metrics"]["tool_executions"],
            "seconds": round(time.perf_counter() - t0, 4),
        })
    return summarize(rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    math_rows = [r for r in rows if r["domain"] != "none"]
    n = len(math_rows)
    verified = [r for r in math_rows if r["status"] == "verified"]
    correct = [r for r in math_rows if r["correct"]]
    by_status = fit_calibration(rows)
    for d in by_status.values():
        d["precision"] = round(d["correct"] / d["n"], 4) if d["n"] else None
    secs = sorted(r["seconds"] for r in rows)

    def group(key: str) -> dict[str, dict[str, Any]]:
        acc: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in math_rows:
            acc[r[key]].append(r)
        return {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 4),
                    "verified": sum(x["status"] == "verified" for x in v)} for k, v in sorted(acc.items())}

    no_math = [r for r in rows if r["domain"] == "none"]
    return {
        "benchmark": BENCHMARK_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "engine_versions": {"sympy": sp.__version__},
        "n": n,
        "accuracy": round(len(correct) / n, 4) if n else 0.0,
        "status_match_rate": round(sum(r["status"] == r["expect"] for r in math_rows) / n, 4) if n else 0.0,
        "verified": {
            "coverage": round(len(verified) / n, 4) if n else 0.0,
            "precision": round(sum(r["correct"] for r in verified) / len(verified), 4) if verified else None,
            "false_accepts": [r["id"] for r in verified if not r["correct"]],
            # correct answers the verifier could not fully confirm, excluding cases where "partial" is the right status
            "false_rejects": [r["id"] for r in math_rows if r["correct"] and r["status"] != "verified" and r["expect"] == "verified"],
        },
        "by_status": by_status,
        "calibration_cross_fitted": _cross_fitted(rows),
        "by_domain": group("domain"),
        "by_difficulty": group("difficulty"),
        "by_phrasing": group("phrasing"),
        "non_math_abstention": round(sum(r["status"] == "failed" for r in no_math) / len(no_math), 4) if no_math else None,
        "efficiency": {
            "mean_tool_calls": round(statistics.mean(r["tool_calls"] for r in rows), 3) if rows else 0,
            "p50_seconds": secs[len(secs) // 2] if secs else 0,
            "p95_seconds": secs[min(len(secs) - 1, int(0.95 * len(secs)))] if secs else 0,
            "total_seconds": round(sum(secs), 3),
        },
        "adversarial": adversarial_report(),
        "failures": [{k: r[k] for k in ("id", "question", "status", "expect", "answer", "why")} for r in rows if not r["correct"] or r["status"] != r["expect"]],
        "rows": rows,
    }


def write_calibration(report: dict[str, Any], path: Path = CALIBRATION_PATH, fitted_on: str = "") -> dict[str, Any]:
    payload = {
        "benchmark": report["benchmark"],
        "fitted_on": fitted_on or "benchmark run",
        "fitted_at": report["created_at"],
        "n": report["n"],
        "statuses": {s: {k: v for k, v in d.items() if k in ("n", "correct", "confidence", "lower_95")} for s, d in report["by_status"].items()},
        "cross_fitted": report["calibration_cross_fitted"],
        "accuracy": report["accuracy"],
        "verified_precision": report["verified"]["precision"],
        "verified_coverage": report["verified"]["coverage"],
        "note": "P(answer correct | final status), Laplace-smoothed (k + 1) / (n + 2) with a Wilson 95% lower bound. "
                "Fit only on a held-out set run once with the code frozen; refit after changing the parser, policy or verifier.",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def format_report(rep: dict[str, Any], label: str = "", failures: bool = True) -> str:
    v, adv, cal, eff = rep["verified"], rep["adversarial"], rep["calibration_cross_fitted"], rep["efficiency"]
    lines = [
        f"{rep['benchmark']}{' ' + label if label else ''}: {rep['n']} problems",
        f"  accuracy            {rep['accuracy']:.1%}    status as expected {rep['status_match_rate']:.1%}",
        f"  verified coverage   {v['coverage']:.1%}    verified precision {v['precision'] if v['precision'] is None else format(v['precision'], '.1%')}",
        f"  false accepts       {len(v['false_accepts'])} {v['false_accepts']}",
        f"  false rejects       {len(v['false_rejects'])} {v['false_rejects']}",
        f"  adversarial         {adv['false_accepts']}/{adv['n']} wrong candidates accepted",
        f"  calibration (x-fit) ECE {cal['ece']:.4f}  Brier {cal['brier']:.4f}",
        f"  non-math abstention {rep['non_math_abstention']}",
        f"  efficiency          {eff['mean_tool_calls']} tool calls/problem, p50 {eff['p50_seconds']}s, p95 {eff['p95_seconds']}s, total {eff['total_seconds']}s",
        "  P(correct | status):",
    ]
    for s, d in rep["by_status"].items():
        lines.append(f"    {s:19} n={d['n']:3}  precision={d['precision']}  confidence={d['confidence']}  lower95={d['lower_95']}")
    lines.append("  by domain: " + ", ".join(f"{k} {d['accuracy']:.0%} ({d['n']})" for k, d in rep["by_domain"].items()))
    lines.append("  by phrasing: " + ", ".join(f"{k} {d['accuracy']:.0%} ({d['n']})" for k, d in rep["by_phrasing"].items()))
    for f in rep["failures"] if failures else []:
        lines.append(f"  ! {f['id']:7} [{f['status']} / expected {f['expect']}] {f['question'][:60]!r} -> {f['answer'][:60]!r} {f['why'][:120]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--write-calibration", action="store_true", help=f"refit {CALIBRATION_PATH.name} on development + held-out")
    ap.add_argument("--set", choices=("dev", "holdout", "holdout2", "holdout3", "all"), default="all", help="which problems to run")
    args = ap.parse_args(argv)
    if args.set == "all":
        dev, held = asyncio.run(run_benchmark(BENCHMARK)), asyncio.run(run_benchmark(HOLDOUT))
        print(format_report(dev, "development"))
        print()
        print(format_report(held, "held-out"))
        rep = summarize(dev["rows"] + held["rows"])
        print()
        print(format_report(rep, "combined", failures=False))
        rep["development"], rep["holdout"] = {k: v for k, v in dev.items() if k != "rows"}, {k: v for k, v in held.items() if k != "rows"}
    else:
        rep = asyncio.run(run_benchmark({"dev": BENCHMARK, "holdout": HOLDOUT, "holdout2": HOLDOUT2, "holdout3": HOLDOUT3}[args.set]))
        print(format_report(rep, args.set))
    if args.json:
        args.json.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    if args.write_calibration:
        write_calibration(rep, fitted_on=f"{args.set} set, first run with the code frozen" if args.set.startswith("holdout") else f"{args.set} set")
        print(f"wrote {CALIBRATION_PATH}")
    gate_ok = not rep["verified"]["false_accepts"] and rep["adversarial"]["false_accepts"] == 0
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ADVERSARIAL", "BENCHMARK", "HOLDOUT", "HOLDOUT2", "HOLDOUT3", "Case", "fit_calibration", "grade", "run_benchmark", "summarize", "wilson_lower", "write_calibration"]
