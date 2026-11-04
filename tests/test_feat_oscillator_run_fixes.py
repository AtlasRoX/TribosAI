"""Fixes from the uncertain damped-oscillator run: prose before a stated ODE, an uncertain parameter's nominal value,
placeholder tool calls, and the follow-up plan's approval gate."""

from __future__ import annotations

from tribos.agentic.plan_graph import parse_plan
from tribos.axiom.problem import parse_problem
from tribos.dynamis.stated_ode import stated_ode_system

STATED = ("A damped oscillator obeys x'' + c x' + k x = 0 with x(0) = 1, x'(0) = 0, k = 4, and an uncertain damping "
          "c ~ Normal(0.4, 0.05)")


def test_capitalised_prose_is_not_part_of_the_ode_and_the_mean_is_the_nominal_value():
    s = parse_problem(STATED)
    assert s.kind == "ode" and s.expression == "x'' + (0.4) x' + (4) x = 0"
    assert s.params["given_values"] == {"k": "4", "c": "0.4"} and "c nominal" in s.assumptions
    system = stated_ode_system(s.expression, s.func, s.ics)
    assert system is not None and system["initial_state"] == {"x": 1.0, "v": 0.0}


def test_a_placeholder_call_is_dropped_from_the_plan():
    g = parse_plan({"nodes": [
        {"id": "n1", "tool": "dynamis_optimize", "args": {}, "purpose": "Q3 placeholder constrained optimum probe"},
        {"id": "n2", "tool": "physis_propagate_uncertainty", "args": {}, "purpose": "proxy model of E(c)"},
        {"id": "n3", "tool": "calcula_run_python", "args": {}, "purpose": "Q2 dissipated energy integral"},
    ]})
    assert [n.id for n in g.nodes] == ["n3"] and {r["node"] for r in g.rejected} == {"n1", "n2"}
