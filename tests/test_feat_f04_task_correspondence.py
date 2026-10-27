"""
Tests for feature F04: Verify correspondence to the original task before certifying results.

Validates that:
- A wrong-problem certificate cannot receive an original-task Pass, even if two engines agree on the wrong intermediate problem.
- S10 injection of a simultaneous k=1,k=3,k=6 solver result on an independent calculation request is refuted.
- Out-of-domain witnesses (e.g. i = -1/7 on nonnegative integers) are rejected.
- Trivial tautologies (1=1, 2=2) are rejected from certifying coverage.
- Positive controls for equivalent factorizations and substituted identities (I10) pass via traceable mappings.
"""

from __future__ import annotations

from tribos.axiom.definitions import axiom_structured, check_structured
from tribos.axiom.problem import ProblemSpec, parse_problem
from tribos.axiom.verifier import verify
from tribos.tools.registry import ToolResult
from tribos.verify.result_record import build_result_record
from tribos.verify.verifier import TribosVerifier


def test_f04_s10_mismatched_solver_result_rejected():
    """S10 reproduction: An independent calculation request must reject a simultaneous conjunction solve result."""
    q = "Three independent calculations, k local to each: k=1,k=3,k=6, evaluate 2k+1. Exactly three numbered lines with substitution/result; nothing else; no search or formal prover."
    # Even if an intermediate spec was parsed/forced as a simultaneous solve system:
    spec = ProblemSpec(text=q, kind="solve", equations=["k = 1", "k = 3", "k = 6"])

    # Attempt to verify axiom_solve returning no solutions on this system
    verdict = verify(spec, "axiom_solve", {"equations": ["k = 1", "k = 3", "k = 6"]}, {"solutions": []})

    # The verifier MUST refute this, refusing to certify 'no solutions' as verified
    assert verdict.status == "refuted"
    assert not verdict.sufficient
    failed_checks = [c for c in verdict.checks if c.passed is False]
    assert any("correspondence" in c.name for c in failed_checks)
    assert any("independent" in c.detail or "evaluation" in c.detail for c in failed_checks)


def test_f04_result_record_marks_mismatched_solver_as_irrelevant():
    """At the integration boundary, mismatched solver results must be tagged irrelevant and omitted from expressions."""
    q = "Three independent calculations, k local to each: k=1,k=3,k=6, evaluate 2k+1."
    tr = {
        "axiom_solve": ToolResult(
            success=True,
            tool_name="axiom_solve",
            data={"solutions": [], "verified": True},
            metadata={"equations": ["k = 1", "k = 3", "k = 6"]},
        )
    }
    rec = build_result_record(q, tr)
    # The mismatched tool result must not become a valid expression
    assert len(rec.expressions) == 0
    # Provenance must mark it as irrelevant
    prov = next((p for p in rec.provenance if p.get("tool") == "axiom_solve"), None)
    assert prov is not None
    assert prov.get("status") == "irrelevant"
    assert "correspondence" in prov.get("reason", "").lower() or "independent" in prov.get("reason", "").lower()


def test_f04_verifier_response_rejects_false_no_solutions_claim():
    """If an answer reports 'no solutions' based on the mismatched simultaneous system, Verifier flags a critical defect."""
    q = "Three independent calculations, k local to each: k=1,k=3,k=6, evaluate 2k+1."
    resp = "The simultaneous system k=1, k=3, k=6 has no solutions."
    tr = {
        "axiom_solve": ToolResult(
            success=True,
            tool_name="axiom_solve",
            data={"solutions": [], "verified": True},
            metadata={"equations": ["k = 1", "k = 3", "k = 6"]},
        )
    }
    report = TribosVerifier().verify_response(q, resp, tr)
    assert report.passed is False
    assert not report.fully_verified
    assert any(d.category in ("COMPLETION", "TASK_CORRESPONDENCE") for d in report.defects)


def test_f04_i07_scalar_multiplication_of_function_refuted():
    """I07: Defined functions treated as scalar multiplication must be refuted as an interpretation failure."""
    q = "Let f(x) = x^2 + 1. Simplify f(x) - x^2."
    spec = parse_problem(q)
    # Tool call simplifies f*x - x^2 (multiplying f by x)
    v = verify(spec, "axiom_simplify", {"expression": "f*x - x^2"}, {"simplified": "x*(f - x)"})
    assert v.status == "refuted"
    assert not v.sufficient
    assert any("function" in c.name or "function" in c.detail for c in v.checks if c.passed is False)


def test_f04_s07_out_of_domain_counterexample_rejected():
    """S07 / I08: A candidate counterexample outside the declared domain (e.g. i = -1/7 on nonnegative integers) is rejected."""
    q = "Four independent items: k=1,k=3,k=6, compute 2k+1 in each; for nonnegative integer i, a(i)=16i+3,b(i)=9i+2, prove a>b and check i=0,1,2."
    spec = parse_problem(q)
    assert spec.domain == "nonnegative_integer"

    # Suppose a tool result reported that the claim fails with counterexample i = -1/7
    data = {
        "results": [
            {
                "id": "claim",
                "op": "claim",
                "status": "disproved",
                "counterexample": "-1/7",
                "text": "Fails at i = -1/7",
            }
        ]
    }
    v = verify(spec, "axiom_structured", spec.params, data)
    assert v.status == "refuted"
    assert not v.sufficient
    # Domain check must flag that -1/7 is outside nonnegative integers
    failed = [c for c in v.checks if c.passed is False]
    assert any("outside" in c.detail and "-1/7" in c.detail for c in failed)


def test_f04_tautological_claims_rejected():
    """Trivial tautologies like 1=1 or 2=2 from malformed inputs cannot certify problem coverage."""
    tasks = [
        {"id": "task_1", "op": "claim", "lhs": "1", "rhs": "1"},
        {"id": "task_2", "op": "claim", "lhs": "2", "rhs": "2"},
    ]
    data = {
        "results": [
            {"id": "task_1", "status": "proved"},
            {"id": "task_2", "status": "proved"},
        ]
    }
    checks = check_structured({"definitions": [], "tasks": tasks}, data, "Some problem text")
    taut_check = next((c for c in checks if "tautological" in c[0]), None)
    assert taut_check is not None
    assert taut_check[1] is False  # passed is False


def test_f04_positive_control_equivalent_factorization():
    """Requirement 4: Valid transformed calculations (e.g. factored form) pass via traceable mapping."""
    q = "Solve x^2 - 5*x + 6 = 0"
    spec = ProblemSpec(text=q, kind="solve", expression="x^2 - 5*x + 6 = 0", variable="x")
    # Tool solves (x - 2)*(x - 3) = 0
    v = verify(
        spec,
        "axiom_solve",
        {"equation": "(x - 2)*(x - 3) = 0", "variables": "x"},
        {"solutions": [{"x": "2"}, {"x": "3"}]},
    )
    assert v.status == "verified"
    assert v.sufficient


def test_f04_positive_control_substituted_identity():
    """Requirement 4 & I10: Substituted identity (x^2 + 1 - x^2 = 1 for f(x)=x^2+1) passes alignment."""
    q = "Let f(x) = x^2 + 1. Prove that f(x) - x^2 = 1."
    spec = parse_problem(q)
    # Tool evaluates lhs="x^2 + 1 - x^2", rhs="1"
    v = verify(
        spec,
        "axiom_verify_identity",
        {"lhs": "x^2 + 1 - x^2", "rhs": "1"},
        {"equivalent": True},
    )
    assert v.status == "verified"
    assert v.sufficient


def test_f04_positive_control_s10_correct_casewise_results():
    """S10 positive control: axiom_structured evaluating 2k+1 at k=1,3,6 produces verified case-wise values 3, 7, 13."""
    q = "Three independent calculations, k local to each: k=1,k=3,k=6, evaluate 2k+1. Exactly three numbered lines with substitution/result; nothing else; no search or formal prover."
    spec = parse_problem(q)
    assert spec.kind == "structured"
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    v = verify(spec, "axiom_structured", spec.params, res)
    assert v.status == "verified"
    assert v.sufficient
    values = [r["value"] for r in res["results"]]
    assert values == ["3", "7", "13"]
