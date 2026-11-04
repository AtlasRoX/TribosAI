"""
Tests for feature F05: Normalize symbolic payload shapes and contain tuple failures.

Validates that:
- S02 tuple/container inputs to axiom_simplify and safe_parse_expr do not raise AttributeError.
- Bare comma-separated expressions, parenthesized tuples, and bracketed lists are normalized and processed element-wise.
- Python native collections (list[str], tuple[str, ...]) are accepted by schema and engine.
- Other symbolic tools (axiom_latex, axiom_verify_identity, axiom_calculus, axiom_solve) handle container shapes.
- Unsupported shapes (empty containers, dicts) produce typed, actionable UnsupportedShapeError without raw attribute crashes.
- Verification and classification layers properly contain shape failures without false passes.
"""

from __future__ import annotations

import pytest
import sympy as sp

from tribos.axiom.agent import classify, FailureClass
from tribos.axiom.engine import (
    axiom_calculus,
    axiom_latex,
    axiom_simplify,
    axiom_solve,
    axiom_verify_identity,
    safe_parse_expr,
)
from tribos.axiom.problem import ProblemSpec
from tribos.axiom.schemas import AxiomSimplifyInput
from tribos.axiom.shapes import UnsupportedShapeError
from tribos.axiom.verifier import verify
from tribos.tools.registry import ErrorType, ToolResult


def test_f05_s02_tuple_simplification_succeeds_without_attribute_error():
    """S02 reproduction: Evaluation of multi-point expressions in parenthesized tuple form."""
    expr_str = "(1**2-3*1+7, 2**2-3*2+7, 0**2-3*0+7, 5**2-3*5+7)"
    res = axiom_simplify(expr_str)
    assert res["simplified"] == "(5, 5, 7, 17)"
    assert res["free_symbols"] == []
    assert res["shape"] == "tuple"
    assert len(res["items"]) == 4


def test_f05_bare_comma_separated_tuple_simplification():
    """Bare comma-separated expressions evaluate element-wise without crashing."""
    expr_str = "1**2-3*1+7, 2**2-3*2+7, 0**2-3*0+7, 5**2-3*5+7"
    res = axiom_simplify(expr_str)
    assert res["simplified"] == "(5, 5, 7, 17)"
    assert res["free_symbols"] == []
    assert len(res["items"]) == 4


def test_f05_bracketed_list_simplification():
    """Bracketed list expressions preserve list container shape."""
    expr_str = "[1**2-3*1+7, 2**2-3*2+7, 0**2-3*0+7, 5**2-3*5+7]"
    res = axiom_simplify(expr_str)
    assert res["simplified"] == "[5, 5, 7, 17]"
    assert res["shape"] == "list"
    assert len(res["items"]) == 4


def test_f05_native_python_collections_in_axiom_simplify():
    """Passing Python list or tuple directly to axiom_simplify is supported and validated by schema."""
    inp = AxiomSimplifyInput(expression=["x**2 - 2*x + 1", "y**2 - 4"])
    res = axiom_simplify(inp.expression)
    assert "(x - 1)**2" in res["factored"]
    assert "(y - 2)*(y + 2)" in res["factored"]
    assert set(res["free_symbols"]) == {"x", "y"}


def test_f05_symbolic_tuple_with_variables_unions_free_symbols():
    """Symbolic tuples with multiple variables correctly extract and union all free symbols."""
    expr_str = "(n**2 - 3*n + 7, m**2 - 3*m + 7, k + 1)"
    res = axiom_simplify(expr_str)
    assert set(res["free_symbols"]) == {"k", "m", "n"}
    assert res["shape"] == "tuple"


def test_f05_safe_parse_expr_returns_sympy_container_with_free_symbols():
    """safe_parse_expr on comma expression returns sp.Tuple with .free_symbols, avoiding raw tuple errors."""
    parsed = safe_parse_expr("x, y, z")
    assert isinstance(parsed, sp.Tuple)
    assert hasattr(parsed, "free_symbols")
    assert parsed.free_symbols == {sp.Symbol("x"), sp.Symbol("y"), sp.Symbol("z")}


def test_f05_axiom_latex_handles_tuple_expressions():
    """axiom_latex formats tuple expressions and extracts free symbols without crashing."""
    res = axiom_latex("x**2, y**2")
    assert "x" in res["free_symbols"] and "y" in res["free_symbols"]
    assert "left(" in res["latex"] or "left[" in res["latex"]


def test_f05_axiom_verify_identity_handles_elementwise_containers():
    """axiom_verify_identity verifies element-wise vector/tuple identities."""
    lhs = "(x + 1)**2, y**2 - 1"
    rhs = "x**2 + 2*x + 1, (y - 1)*(y + 1)"
    res = axiom_verify_identity(lhs, rhs)
    assert res["equivalent"] is True
    assert res["evidence"] == "symbolic"

    # Mismatched length returns clean refutation, not an exception
    mismatch = axiom_verify_identity("(x, y)", "(x, y, z)")
    assert mismatch["equivalent"] is False
    assert mismatch["evidence"] == "refuted"
    assert "mismatch" in mismatch["counterexample"]["error"]


def test_f05_axiom_calculus_differentiates_vector_elementwise():
    """axiom_calculus differentiates vector tuples element-wise."""
    res = axiom_calculus("(x**2, sin(x), exp(x))", operation="diff", variable="x")
    assert "2*x" in res["result"]
    assert "cos(x)" in res["result"]
    assert "exp(x)" in res["result"]
    assert res["verified"] is True


def test_f05_axiom_solve_unpacks_tuple_equality():
    """axiom_solve unpacks tuple equality (x, y) = (2, 3) into scalar system."""
    res = axiom_solve("(x, y) = (2, 3)")
    assert res["solutions"] == [{"x": "2", "y": "3"}]


def test_f05_unsupported_shapes_raise_typed_error():
    """Unsupported shapes (dict, empty container) raise UnsupportedShapeError without AttributeError."""
    with pytest.raises(UnsupportedShapeError):
        axiom_simplify("()")

    with pytest.raises(UnsupportedShapeError):
        safe_parse_expr({"a": "x + 1"})


def test_f05_agent_failure_classification_contains_shape_error():
    """UnsupportedShapeError is classified as MODEL_ACTION_ERROR for clean agent recovery."""
    tr = ToolResult(
        success=False,
        tool_name="axiom_simplify",
        error="UnsupportedShapeError: Empty container cannot be simplified",
        error_type=ErrorType.VALIDATION_ERROR,
    )
    assert classify(tr) == FailureClass.MODEL_ACTION_ERROR


def test_f05_verifier_end_to_end_on_simplified_tuple():
    """Verifier handles simplified tuple outputs end-to-end."""
    spec = ProblemSpec(text="Simplify (x^2 - 1, x^2 - 4)", kind="simplify", expression="(x^2 - 1, x^2 - 4)")
    data = axiom_simplify("(x^2 - 1, x^2 - 4)")
    v = verify(spec, "axiom_simplify", {"expression": "(x^2 - 1, x^2 - 4)"}, data)
    assert v.status == "verified"
    assert v.sufficient
