"""
Tests for permanent fixes to type error and container shape handling across symbolic and numerical engines.

Covers:
- axiom_nsolve rejects container equations and shape mismatches with UnsupportedShapeError (never raw TypeError).
- axiom_solve catches incompatible operand TypeErrors and raises clean UnsupportedShapeError.
- axiom_dsolve and axiom_recurrence reject container equations cleanly.
- dynamis_solve_system unpacks matching container shapes and rejects shape mismatches cleanly.
- axiom_latex extracts free symbols from collection equations without crash.
- Problem parser _try_parse rejects container-to-scalar shape mismatches as equation spans.
- Clause splitter correctly preserves nested parentheses when extracting multiple equations.
- RulePolicy avoids proposing numeric scans (axiom_nsolve) on container or multivariate equations.
"""

from __future__ import annotations

import pytest

from tribos.axiom.agent import RulePolicy, MathState, local_executor
from tribos.axiom.discrete import axiom_recurrence
from tribos.axiom.engine import (
    axiom_dsolve,
    axiom_latex,
    axiom_nsolve,
    axiom_solve,
)
from tribos.axiom.problem import parse_problem, _try_parse
from tribos.axiom.shapes import UnsupportedShapeError
from tribos.dynamis.engine import dynamis_root_find
from tribos.tools.registry import ErrorType


def test_axiom_nsolve_container_scalar_mismatch_raises_unsupported_shape_error():
    """Equations with container on one side and scalar on the other raise UnsupportedShapeError, not TypeError."""
    mismatched = [
        "(x, y) = 1",
        "x = (1, 2)",
        "x = 1, 2",
        "n = 4*k+3, (x, y, z)",
    ]
    for eq in mismatched:
        with pytest.raises(UnsupportedShapeError) as exc_info:
            axiom_nsolve(eq)
        assert "Shape mismatch in equation: cannot equate container to scalar" in str(exc_info.value)


def test_axiom_nsolve_both_containers_raises_unsupported_shape_error():
    """Equations equating two containers raise UnsupportedShapeError indicating nsolve needs scalar."""
    with pytest.raises(UnsupportedShapeError) as exc_info:
        axiom_nsolve("(x, y) = (1, 2)")
    assert "Operation 'nsolve' requires a scalar equation" in str(exc_info.value)


def test_axiom_solve_catches_operand_type_errors():
    """axiom_solve cleanly raises UnsupportedShapeError on shape mismatches."""
    with pytest.raises(UnsupportedShapeError):
        axiom_solve("n = 4*k+3, (x, y, z)")


def test_axiom_dsolve_rejects_container_equations():
    """axiom_dsolve rejects container equations with UnsupportedShapeError."""
    with pytest.raises(UnsupportedShapeError) as exc_info:
        axiom_dsolve("(y', y) = (x, 1)", func="y")
    assert "Operation 'dsolve' requires a scalar ODE" in str(exc_info.value)


def test_axiom_recurrence_rejects_container_equations():
    """axiom_recurrence rejects container recurrences with UnsupportedShapeError."""
    with pytest.raises(UnsupportedShapeError) as exc_info:
        axiom_recurrence("(a(n), a(n-1)) = (1, 2)", initial={"a(0)": 0})
    assert "Operation 'recurrence' requires a scalar equation" in str(exc_info.value)


def test_dynamis_solve_system_handles_containers_and_rejects_mismatch():
    """dynamis_root_find unpacks matching container shapes and raises ValueError on mismatch."""
    with pytest.raises(ValueError, match="Shape mismatch in equation"):
        dynamis_root_find(
            equations=["(x, y) = 1"],
            initial_guess={"x": 1.0, "y": 1.0},
        )


def test_axiom_latex_handles_tuple_equations():
    """axiom_latex extracts free symbols from container equations without crash."""
    res = axiom_latex("(x, y) = (2, 3)")
    assert set(res["free_symbols"]) == {"x", "y"}


def test_try_parse_rejects_container_scalar_mismatch():
    """_try_parse returns None for spans where container is equated to scalar."""
    assert _try_parse("n = 4k+3, (x, y, z)", equation=True) is None
    assert _try_parse("(x, y) = (1, 2)", equation=True) is not None
    assert _try_parse("x = 5", equation=True) is not None


def test_parse_problem_splits_clauses_with_nested_parens():
    """Problem parser preserves nested parentheses when extracting multiple equations."""
    text = "For n = 4k+3, (x, y, z) = (k+1, 2*(4*k+3)*(k+1), 2*(4*k+3)*(k+1))"
    spec = parse_problem(text)
    assert spec.kind == "solve"
    assert len(spec.equations) == 2
    assert "n = 4k+3" in spec.equations[0]
    assert "(x, y, z)" in spec.equations[1]


@pytest.mark.asyncio
async def test_rule_policy_avoids_nsolve_on_container_or_multivariate():
    """RulePolicy does not propose numeric scan on container or multivariate equations."""
    spec = parse_problem("(x, y) = (2, 3)")
    policy = RulePolicy()
    state = MathState(spec=spec)
    action = await policy.propose(state)
    assert action is not None
    assert action.tool == "axiom_solve"

    # Advance state to simulate failed exact solve
    state.advance_strategy("exact solve failed")
    action2 = await policy.propose(state)
    # Must NOT propose axiom_nsolve on tuple equation
    assert action2 is None or action2.tool != "axiom_nsolve"


@pytest.mark.asyncio
async def test_local_executor_maps_type_error_to_validation_error():
    """local_executor wraps TypeError in VALIDATION_ERROR rather than INTERNAL_ERROR."""
    executor = local_executor(30.0)
    res = await executor("axiom_nsolve", {"equation": "(x, y) = 1"})
    assert res.success is False
    assert res.error_type == ErrorType.VALIDATION_ERROR
    assert "Shape mismatch in equation: cannot equate container to scalar" in res.error
