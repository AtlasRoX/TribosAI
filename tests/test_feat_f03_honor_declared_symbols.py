from __future__ import annotations

import sympy as sp
from tribos.axiom.analysis import axiom_inequality
from tribos.axiom.definitions import axiom_structured, check_structured
from tribos.axiom.problem import parse_problem
from tribos.verify.latex_math import ParseContext, parse_latex
from tribos.verify.math_claims import audit_answer
from tribos.verify.result_record import build_result_record


def test_f03_reproduction_index_i_declared_nonnegative_integer():
    """F03 Reproduction: S06/S07 Declare i a nonnegative integer; a(i)=16i+3, b(i)=9i+2.
    Prove a>b and evaluate at i=0,1,2.
    Expected: Difference 7i+1>=1; checks (3,2),(19,11),(35,20). i is not evaluated as 0+1i."""
    q = "Declare i a nonnegative integer; a(i)=16i+3, b(i)=9i+2. Prove a>b and evaluate at i=0,1,2."
    spec = parse_problem(q)
    assert spec.kind == "structured"
    assert spec.domain == "nonnegative_integer"
    assert spec.assumptions.get("i") == "nonnegative_integer"

    tasks = spec.params["tasks"]
    defs = spec.params["definitions"]
    res = axiom_structured(definitions=defs, tasks=tasks)

    # Claim proved
    claim_res = next(r for r in res["results"] if r["id"] == "claim")
    assert claim_res["status"] == "proved"
    assert "7*i + 1" in claim_res["text"] or "7*i + 1" in str(claim_res.get("steps", []))

    # Checks at 0, 1, 2
    a0 = next(r for r in res["results"] if r["id"] == "a(0)")
    b0 = next(r for r in res["results"] if r["id"] == "b(0)")
    assert a0["value"] == "3" and b0["value"] == "2"

    a1 = next(r for r in res["results"] if r["id"] == "a(1)")
    b1 = next(r for r in res["results"] if r["id"] == "b(1)")
    assert a1["value"] == "19" and b1["value"] == "11"

    a2 = next(r for r in res["results"] if r["id"] == "a(2)")
    b2 = next(r for r in res["results"] if r["id"] == "b(2)")
    assert a2["value"] == "35" and b2["value"] == "20"

    checks = check_structured(spec.params, res)
    assert all(c[1] for c in checks), f"Verification checks failed: {checks}"


def test_f03_reproduction_index_j_variant():
    """Repeat with symbol j to confirm index variable independence."""
    q = "Declare j a nonnegative integer; a(j)=16j+3, b(j)=9j+2. Prove a>b and evaluate at j=0,1,2."
    spec = parse_problem(q)
    assert spec.kind == "structured"
    assert spec.domain == "nonnegative_integer"
    assert spec.assumptions.get("j") == "nonnegative_integer"

    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    claim_res = next(r for r in res["results"] if r["id"] == "claim")
    assert claim_res["status"] == "proved"

    a0 = next(r for r in res["results"] if r["id"] == "a(0)")
    b0 = next(r for r in res["results"] if r["id"] == "b(0)")
    assert a0["value"] == "3" and b0["value"] == "2"

    a1 = next(r for r in res["results"] if r["id"] == "a(1)")
    b1 = next(r for r in res["results"] if r["id"] == "b(1)")
    assert a1["value"] == "19" and b1["value"] == "11"

    a2 = next(r for r in res["results"] if r["id"] == "a(2)")
    b2 = next(r for r in res["results"] if r["id"] == "b(2)")
    assert a2["value"] == "35" and b2["value"] == "20"


def test_f03_math_claims_audit_does_not_evaluate_i_as_imaginary_unit():
    """Verifier must not evaluate i as 0+1i and contradict evaluations i=0, 1, 2."""
    q = "Declare i a nonnegative integer; a(i)=16i+3, b(i)=9i+2. Prove a>b and evaluate at i=0,1,2."
    response = r"""
    We have $a(i) = 16i + 3$ and $b(i) = 9i + 2$ for nonnegative integer $i$.
    The difference is $a(i) - b(i) = (16i + 3) - (9i + 2) = 7i + 1$.
    Since $i \ge 0$, $7i + 1 \ge 1$, so $a(i) > b(i)$.

    Evaluations:
    For $i = 0$: $a(0) = 3$, $b(0) = 2$.
    For $i = 1$: $a(1) = 19$, $b(1) = 11$.
    For $i = 2$: $a(2) = 35$, $b(2) = 20$.
    """
    record = build_result_record(q, tool_results={})
    assert "i" not in record.parameters, f"Variable i should not be a fixed parameter: {record.parameters}"

    audit = audit_answer(response, q, record=record)
    counts = audit.counts()
    assert counts["failed"] == 0, f"Expected 0 failed claims, got: {[c.detail for c in audit.claims if c.status == 'failed']}"
    assert counts["passed"] >= 7, f"Expected at least 7 passed claims, got {counts}"


def test_f03_genuine_imaginary_unit_retains_support():
    """In explicit complex tasks, i is recognized as the imaginary unit with i^2 = -1."""
    response = r"""
    We know that $i^2 = -1$.
    Then $(2 + 3i)(4 - 5i) = 8 - 10i + 12i - 15(-1) = 23 + 2i$.
    """
    audit = audit_answer(response, "Calculate (2+3i)(4-5i)")
    counts = audit.counts()
    assert counts["failed"] == 0, f"Failed: {[c.detail for c in audit.claims if c.status == 'failed']}"
    assert counts["passed"] >= 2, f"Passed: {counts['passed']}"


def test_f03_explicit_imaginary_unit_definition():
    """When i is explicitly declared as the imaginary unit, i^2 = -1 is supported."""
    ctx = ParseContext(imaginary_i=True)
    expr = parse_latex("i^2", ctx)
    assert sp.simplify(expr) == -1


def test_f03_declared_symbol_shadows_in_parse_context():
    """A declared local variable in ParseContext shadows imaginary constant alias."""
    ctx_declared = ParseContext(symbols={"i"}, imaginary_i=True)
    expr = parse_latex("16i + 3", ctx_declared)
    assert not expr.has(sp.I)
    assert expr.has(sp.Symbol("i"))

    ctx_var = ParseContext(variable="i", imaginary_i=True)
    expr_var = parse_latex("i", ctx_var)
    assert not expr_var.has(sp.I)
    assert expr_var == sp.Symbol("i")

    expr_j = parse_latex("16j + 3")
    assert not expr_j.has(sp.I)
    assert expr_j.has(sp.Symbol("j"))


def test_f03_s09_inequality_control():
    """S09 control: solving an inequality in i with axiom_inequality works correctly."""
    res = axiom_inequality("16*i + 3 > 9*i + 2", "i")
    assert res["variable"] == "i"
    assert res["verified"] is True
    # 7i + 1 > 0 -> i > -1/7
    assert res["intervals"][0]["lower"] == "-1/7"
