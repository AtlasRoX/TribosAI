"""Feature tests for F02: Isolate independent cases and local variable bindings."""

from __future__ import annotations

from tribos.axiom.definitions import (
    axiom_structured,
    check_structured,
)
from tribos.axiom.engine import axiom_solve
from tribos.axiom.problem import parse_problem
from tribos.verify.math_claims import audit_answer
from tribos.verify.result_record import build_result_record

S10_PROMPT = "Three independent calculations, k local to each: k=1, k=3, k=6, evaluate 2k+1."
SIMULTANEOUS_PROMPT = "Solve the system k=1 and k=3"


def test_s10_independent_k_calculations_parsed_as_structured():
    spec = parse_problem(S10_PROMPT)
    assert spec.kind == "structured", f"Expected structured problem, got {spec.kind}"
    tasks = spec.params.get("tasks", [])
    assert len(tasks) == 3, f"Expected 3 independent tasks, got {len(tasks)}"
    assert [t["bindings"] for t in tasks] == [{"k": "1"}, {"k": "3"}, {"k": "6"}]
    assert all(t["expression"] == "2k+1" for t in tasks)


def test_s10_independent_k_calculations_execution_and_checking():
    spec = parse_problem(S10_PROMPT)
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    assert res.get("status") != "error"
    results = res.get("results", [])
    assert len(results) == 3
    assert [r["value"] for r in results] == ["3", "7", "13"]

    verdict = check_structured(spec.params, res, S10_PROMPT)
    passed_names = [c[0] for c in verdict if c[1] is True]
    assert "computation: every value recomputed by exact rational arithmetic" in passed_names
    assert "coverage: every requested item has a result" in passed_names
    failed_checks = [c for c in verdict if c[1] is False]
    assert not failed_checks, f"Unexpected check failures: {failed_checks}"


def test_simultaneous_system_contrast():
    spec = parse_problem(SIMULTANEOUS_PROMPT)
    assert spec.kind == "solve", f"Expected solve kind for simultaneous system, got {spec.kind}"
    assert "k=1" in spec.equations and "k=3" in spec.equations
    res = axiom_solve(spec.equations, variables=["k"])
    assert res.get("solutions") == [], f"Expected no solutions for inconsistent simultaneous system, got {res}"


def test_reversed_item_order():
    prompt = "Three independent calculations, k local to each: k=6, k=3, k=1, evaluate 2k+1."
    spec = parse_problem(prompt)
    assert spec.kind == "structured"
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    results = res.get("results", [])
    assert [r["value"] for r in results] == ["13", "7", "3"]


def test_renamed_variable():
    prompt = "Three independent calculations, m local to each: m=1, m=3, m=6, evaluate 2m+1."
    spec = parse_problem(prompt)
    assert spec.kind == "structured"
    tasks = spec.params.get("tasks", [])
    assert [t["bindings"] for t in tasks] == [{"m": "1"}, {"m": "3"}, {"m": "6"}]
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    results = res.get("results", [])
    assert [r["value"] for r in results] == ["3", "7", "13"]


def test_repeated_identical_expressions_with_different_values():
    prompt = "Case 1: x = 2. Case 2: x = 5. Evaluate x^2 - 3."
    spec = parse_problem(prompt)
    assert spec.kind == "structured"
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    results = res.get("results", [])
    assert len(results) == 2
    assert [r["value"] for r in results] == ["1", "22"]


def test_inline_independent_substitutions():
    prompt = "Evaluate 2k+1 for k=1, k=3, and k=6 independently."
    spec = parse_problem(prompt)
    assert spec.kind == "structured"
    tasks = spec.params.get("tasks", [])
    assert len(tasks) == 3
    assert [t["bindings"] for t in tasks] == [{"k": "1"}, {"k": "3"}, {"k": "6"}]
    res = axiom_structured(definitions=spec.params["definitions"], tasks=spec.params["tasks"])
    assert [r["value"] for r in res.get("results", [])] == ["3", "7", "13"]


def test_math_claims_independent_examples_i09():
    """Historical issue I09: A valid example at n=40 is followed by a separate valid example at n=41.
    The verifier must not label n=41 contradicted or evaluate it using 40."""
    response = """
    Example 1:
    Let $n = 40$.
    Then $n^2 + n + 41 = 40^2 + 40 + 41 = 1681$.

    Example 2:
    Let $n = 41$.
    Then $n^2 + n + 41 = 41^2 + 41 + 41 = 1763$.
    """
    record = build_result_record("Investigate n^2 + n + 41 for integer n.", tool_results={})
    audit = audit_answer(response, record=record)
    counts = audit.counts()
    assert counts["failed"] == 0, f"Expected 0 failed claims, got {counts['failed']}: {[c.detail for c in audit.claims if c.status == 'failed']}"
    assert counts["passed"] >= 2, f"Expected at least 2 passed relations, got {counts}"


def test_math_claims_independent_k_calculations_s06_s07():
    """S06/S07: Independent evaluation of k=1, k=3, k=6 must not evaluate k=3 or k=6 with k bound to 1."""
    response = """
    1. For $k = 1$:
    $2k + 1 = 2(1) + 1 = 3$.

    2. For $k = 3$:
    $2k + 1 = 2(3) + 1 = 7$.

    3. For $k = 6$:
    $2k + 1 = 2(6) + 1 = 13$.
    """
    record = build_result_record(S10_PROMPT, tool_results={})
    audit = audit_answer(response, record=record)
    counts = audit.counts()
    assert counts["failed"] == 0, f"Expected 0 failed claims, got {counts['failed']}: {[c.detail for c in audit.claims if c.status == 'failed']}"
    assert counts["passed"] >= 3, f"Expected at least 3 passed relations, got {counts}"


def test_checker_diagnostic_identifies_case_and_substitutions():
    """If an evaluation in a specific case fails, the diagnostic must identify the case and substitutions."""
    response = """
    Case 1:
    $k = 3$.
    $2k + 1 = 8$.
    """
    record = build_result_record(S10_PROMPT, tool_results={})
    audit = audit_answer(response, record=record)
    failed = [c for c in audit.claims if c.status == "failed"]
    assert len(failed) >= 1
    detail = failed[0].links[0].detail
    assert "k=3" in detail or "Case" in detail, f"Expected case or substitution in diagnostic detail, got: {detail}"


def test_no_cross_run_or_cache_leakage():
    """Interleaved execution of independent cases across separate queries causes no state leakage."""
    spec_a = parse_problem("Three independent calculations, k local to each: k=1, k=2, evaluate k^2.")
    spec_b = parse_problem("Three independent calculations, k local to each: k=10, k=20, evaluate k^2.")

    res_a = axiom_structured(definitions=spec_a.params["definitions"], tasks=spec_a.params["tasks"])
    res_b = axiom_structured(definitions=spec_b.params["definitions"], tasks=spec_b.params["tasks"])
    res_a2 = axiom_structured(definitions=spec_a.params["definitions"], tasks=spec_a.params["tasks"])

    assert [r["value"] for r in res_a["results"]] == ["1", "4"]
    assert [r["value"] for r in res_b["results"]] == ["100", "400"]
    assert [r["value"] for r in res_a2["results"]] == ["1", "4"]
