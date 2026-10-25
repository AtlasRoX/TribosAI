"""Comprehensive offline unit tests for the Axiom symbolic mathematics package and registry tools."""

from __future__ import annotations

import asyncio
import math

import pytest

from tribos.axiom import (
    AxiomEngine,
    axiom_calculus,
    axiom_dsolve,
    axiom_latex,
    axiom_linalg,
    axiom_simplify,
    axiom_solve,
    axiom_verify_identity,
    safe_parse_expr,
)
from tribos.extensions import axiom as axiom_ext
from tribos.tools.registry import ToolRegistry


def test_safe_parse_implicit_multiplication_and_xor():
    expr = safe_parse_expr("2x + sin(x)^2 + cos(x)^2")
    assert str(expr) in ("2*x + sin(x)**2 + cos(x)**2", "sin(x)**2 + cos(x)**2 + 2*x")

    with pytest.raises(ValueError, match="forbidden"):
        safe_parse_expr("__import__('os')")


def test_axiom_simplify_and_assumptions():
    out = axiom_simplify("sin(x)^2 + cos(x)^2 + (x^2 - 1)/(x - 1)")
    assert out["simplified"] in ("x + 2", "2 + x")
    assert out["canonical_id"].startswith("comp:axiom_simplify:")
    assert "x" in out["free_symbols"]

    pos = axiom_simplify("sqrt(x^2)", assumptions={"x": "positive, real"})
    assert pos["simplified"] == "x"

    poly = axiom_simplify("x^2 - 5*x + 6")
    assert poly["factored"] == "(x - 3)*(x - 2)"


def test_axiom_solve_single_and_system():
    res = axiom_solve("x^2 - 5*x + 6 = 0", variables="x")
    roots = {s["x"] for s in res["solutions"]}
    assert roots == {"2", "3"}
    assert res["verified"] is True
    assert all(r == ["0"] for r in res["residuals"])
    assert res["canonical_id"].startswith("comp:axiom_solve:")

    sys_res = axiom_solve(["2*x + y = 7", "x - y = 2"], variables=["x", "y"])
    assert sys_res["verified"] is True
    assert sys_res["solutions"] == [{"x": "3", "y": "1"}]

    real_only = axiom_solve("x^2 + 1 = 0", variables="x", domain="real")
    assert real_only["solutions"] == []

    complex_all = axiom_solve("x^2 + 1 = 0", variables="x", domain="complex")
    assert len(complex_all["solutions"]) == 2
    assert complex_all["verified"] is True


def test_axiom_calculus_operations():
    # 1. Differentiation
    d_out = axiom_calculus("x^3 * exp(x)", operation="diff", variable="x", order=1)
    assert d_out["verified"] is True
    assert "exp(x)" in d_out["result"]

    # 2. Indefinite integration (verified by differentiating back)
    indef = axiom_calculus("3*x^2 + cos(x)", operation="integrate", variable="x")
    assert indef["verified"] is True
    assert "x**3" in indef["result"] and "sin(x)" in indef["result"]

    # 3. Definite integration (cross-checked via mpmath.quad)
    defin = axiom_calculus("sin(x)", operation="integrate", variable="x", lower="0", upper="pi")
    assert defin["result"] == "2"
    assert defin["verified"] is True
    assert defin["numeric_value"] == pytest.approx(2.0, rel=1e-9)

    gauss = axiom_calculus("exp(-x^2)", operation="integrate", variable="x", lower="-oo", upper="oo")
    assert gauss["result"] == "sqrt(pi)"
    assert gauss["verified"] is True
    assert gauss["numeric_value"] == pytest.approx(math.sqrt(math.pi), rel=1e-7)

    # 4. Limit
    lim = axiom_calculus("sin(x)/x", operation="limit", variable="x", point="0")
    assert lim["result"] == "1"
    assert lim["verified"] is True
    assert lim["numeric_value"] == pytest.approx(1.0)

    # 5. Series expansion
    ser = axiom_calculus("exp(x)", operation="series", variable="x", point="0", order=4)
    assert "x**3/6" in ser["result"] and "x**2/2" in ser["result"]
    assert ser["verified"] is True

    # 6. Symbolic summation
    s_out = axiom_calculus("k", operation="sum", variable="k", lower="1", upper="n")
    assert s_out["verified"] is True
    assert axiom_verify_identity(s_out["result"], "n*(n + 1)/2")["equivalent"] is True


def test_axiom_dsolve_general_and_ivp():
    ode = axiom_dsolve("y''(x) + y(x) = 0", func="y(x)")
    assert ode["verified"] is True
    assert "sin(x)" in ode["rhs"] or "cos(x)" in ode["rhs"]

    ivp = axiom_dsolve("y'(x) + 2*y(x) = 0", func="y(x)", ics={"y(0)": 3})
    assert ivp["verified"] is True
    assert ivp["rhs"] == "3*exp(-2*x)"


def test_axiom_linalg_operations():
    mat = [[4, 1], [2, 3]]

    det_res = axiom_linalg(mat, operation="det")
    assert det_res["result"] == "10"
    assert det_res["trace"] == "7"
    assert det_res["rank"] == 2
    assert det_res["verified"] is True

    inv_res = axiom_linalg(mat, operation="inv")
    assert inv_res["verified"] is True
    assert inv_res["result"] == [["3/10", "-1/10"], ["-1/5", "2/5"]]

    eig_res = axiom_linalg(mat, operation="eigen")
    assert eig_res["verified"] is True
    assert eig_res["eigenvalues"] == {"5": 1, "2": 1}

    solve_res = axiom_linalg(mat, operation="solve", rhs=[9, 8])
    assert solve_res["verified"] is True
    assert solve_res["result"] == ["19/10", "7/5"]

    rref_res = axiom_linalg([[1, 2, 3], [2, 4, 6]], operation="rref")
    assert rref_res["verified"] is True
    assert rref_res["rank"] == 1

    ns_res = axiom_linalg([[1, 2], [2, 4]], operation="nullspace")
    assert ns_res["verified"] is True
    assert len(ns_res["result"]) == 1

    cp_res = axiom_linalg(mat, operation="charpoly")
    assert cp_res["verified"] is True
    assert "lambda**2 - 7*lambda + 10" in cp_res["result"]

    svd_res = axiom_linalg([[3, 0], [0, 4]], operation="svd")
    assert svd_res["verified"] is True
    assert set(svd_res["result"]["singular_values"]) == {"3", "4"}


def test_axiom_verify_identity_and_counterexample():
    ok = axiom_verify_identity("sin(2*x)", "2*sin(x)*cos(x)")
    assert ok["equivalent"] is True
    assert ok["symbolic_zero"] is True
    assert ok["counterexample"] is None
    assert ok["max_numeric_error"] < 1e-12

    bad = axiom_verify_identity("(x + y)^2", "x^2 + y^2")
    assert bad["equivalent"] is False
    assert bad["symbolic_zero"] is False
    assert bad["counterexample"] is not None
    assert set(bad["counterexample"].keys()) == {"x", "y"}


def test_axiom_latex_and_registry_integration():
    ltx = axiom_latex("int_a^b + alpha*x^2 = 0")
    assert "alpha" in ltx["latex"]
    assert ltx["canonical_id"].startswith("comp:axiom_latex:")
    assert AxiomEngine.latex("x^2")["sympy"] == "x**2"

    reg = ToolRegistry()
    axiom_ext.register_tools(reg)
    names = {t.name for t in reg.list_tools(domain="axiom")}
    assert names == {
        "axiom_simplify",
        "axiom_solve",
        "axiom_calculus",
        "axiom_dsolve",
        "axiom_linalg",
        "axiom_verify_identity",
        "axiom_latex",
        "axiom_nsolve",
        "axiom_solve_problem",
        "axiom_sagemath",
        "axiom_optimize",
        "axiom_inequality",
        "axiom_tangent",
        "axiom_vector_calculus",
        "axiom_transform",
        "axiom_nintegrate",
        "axiom_number_theory",
        "axiom_recurrence",
        "axiom_probability",
    }

    res = asyncio.run(reg.execute("axiom_simplify", {"expression": "(x^2 - y^2)/(x - y)"}))
    assert res.success, res.error
    assert res.data["simplified"] in ("x + y", "y + x")
    assert res.canonical_ids["computation_id"].startswith("comp:axiom_simplify:")
