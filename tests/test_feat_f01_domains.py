"""Feature tests for F01: Domain preservation, domain restriction enforcement, and counterexample validation."""

from __future__ import annotations

import pydantic
import pytest

from tribos.axiom.definitions import (
    check_structured,
    run_structured,
)
from tribos.axiom.problem import ProblemSpec, parse_problem
from tribos.axiom.schemas import StructuredDefinition, StructuredTask
from tribos.axiom.verifier import _verify_identity


# S01: Restricted function r on {2, 3, 4, ...} ------------------------------------------------------------------------

def test_s01_restricted_domain_oracle():
    """r(n) = n^2 - 3n + 7 on {2, 3, 4, ...} evaluates r(1) and r(0) as undefined, r(2)=5, r(5)=17."""
    q = "Let r have domain {2, 3, 4, ...}, with r(n) = n^2 - 3*n + 7. Evaluate r(1), r(2), r(0), r(5)."
    spec = parse_problem(q)
    assert spec.kind == "structured"
    assert spec.unaccounted == []
    assert len(spec.params["definitions"]) == 1
    defn = spec.params["definitions"][0]
    assert defn["name"] == "r"
    assert defn["parameter"] == "n"
    assert defn["domain"] == "integer_ge_2"

    res = run_structured(spec.params["definitions"], spec.params["tasks"])
    by_id = {r["id"]: r for r in res["results"]}

    assert by_id["r(1)"]["status"] == "undefined"
    assert "not in the domain" in by_id["r(1)"]["error"]
    assert by_id["r(0)"]["status"] == "undefined"
    assert "not in the domain" in by_id["r(0)"]["error"]
    assert by_id["r(2)"]["status"] == "computed"
    assert by_id["r(2)"]["value"] == "5"
    assert by_id["r(5)"]["status"] == "computed"
    assert by_id["r(5)"]["value"] == "17"

    checks = {name.split(":")[0]: passed for name, passed, *_ in check_structured(spec.params, res, q)}
    assert checks["interpretation"] is True
    assert checks["domain"] is True
    assert checks["computation"] is True
    assert checks["coverage"] is True


def test_s01_unrestricted_control():
    """Without the domain restriction, r evaluates cleanly at 1, 2, 0, 5."""
    q = "Let r(n) = n^2 - 3*n + 7. Evaluate r(1), r(2), r(0), r(5)."
    spec = parse_problem(q)
    assert spec.kind == "structured"
    assert spec.params["definitions"][0]["domain"] == "unspecified"
    res = run_structured(spec.params["definitions"], spec.params["tasks"])
    by_id = {r["id"]: r for r in res["results"]}
    assert by_id["r(1)"]["value"] == "5"
    assert by_id["r(2)"]["value"] == "5"
    assert by_id["r(0)"]["value"] == "7"
    assert by_id["r(5)"]["value"] == "17"


def test_s01_forged_payload_detection():
    """A forged payload that widened the domain to integer and computed r(1)=5, r(0)=7 fails domain check."""
    q = "Let r have domain {2, 3, 4, ...}, with r(n) = n^2 - 3*n + 7. Evaluate r(1), r(2), r(0), r(5)."
    spec = parse_problem(q)
    forged = {
        "definitions": [{"name": "r", "parameter": "n", "domain": "integer", "branches": [{"expression": "n**2 - 3*n + 7", "condition": ""}]}],
        "tasks": spec.params["tasks"],
        "results": [
            {"id": "r(1)", "op": "evaluate", "status": "computed", "value": "5", "applications": [{"function": "r", "argument": "1", "branch": 0, "value": "5"}]},
            {"id": "r(2)", "op": "evaluate", "status": "computed", "value": "5", "applications": [{"function": "r", "argument": "2", "branch": 0, "value": "5"}]},
            {"id": "r(0)", "op": "evaluate", "status": "computed", "value": "7", "applications": [{"function": "r", "argument": "0", "branch": 0, "value": "7"}]},
            {"id": "r(5)", "op": "evaluate", "status": "computed", "value": "17", "applications": [{"function": "r", "argument": "5", "branch": 0, "value": "17"}]},
        ],
    }
    checks = {name.split(":")[0]: (passed, detail) for name, passed, _, detail in check_structured(spec.params, forged, q)}
    assert checks["domain"][0] is False
    assert "integers >= 2" in checks["domain"][1]


# S07: Inequality claim a(i) > b(i) on nonnegative integers ----------------------------------------------------------

def test_s07_inequality_algebraic_proof():
    """a(i) = 16i + 3, b(i) = 9i + 2 on nonnegative integers: a(i) - b(i) = 7i + 1 > 0 proved algebraically."""
    q = "Let a(i) = 16i + 3 and b(i) = 9i + 2. Is a(i) > b(i) for all nonnegative integers i?"
    spec = parse_problem(q)
    assert spec.kind == "structured"
    assert len(spec.params["tasks"]) == 1
    task = spec.params["tasks"][0]
    assert task["op"] == "claim"
    assert task["variable"] == "i"
    assert task["domain"] == "nonnegative_integer"

    res = run_structured(spec.params["definitions"], spec.params["tasks"])
    assert res["results"][0]["status"] == "proved"
    assert "7*i + 1 > 0" in res["results"][0]["text"]

    checks = {name.split(":")[0]: passed for name, passed, *_ in check_structured(spec.params, res, q)}
    assert checks["domain"] is True
    assert checks["computation"] is True


def test_s07_rejects_non_integer_witness():
    """Submitting forged witness i = -1/7 (root of 7i + 1 = 0) is rejected by domain and computation checks."""
    q = "Let a(i) = 16i + 3 and b(i) = 9i + 2. Is a(i) > b(i) for all nonnegative integers i?"
    spec = parse_problem(q)
    forged = {
        "definitions": spec.params["definitions"],
        "tasks": spec.params["tasks"],
        "results": [{
            "id": "claim", "op": "claim", "status": "disproved", "counterexample": "-1/7",
            "detail": "a(-1/7) = 5/7, b(-1/7) = 5/7",
        }],
    }
    checks = {name.split(":")[0]: (passed, detail) for name, passed, _, detail in check_structured(spec.params, forged, q)}
    assert checks["domain"][0] is False
    assert "outside nonnegative integers" in checks["domain"][1]
    assert checks["computation"][0] is False
    assert "outside domain nonnegative integers" in checks["computation"][1]


def test_s07_rejects_negative_integer_witness():
    """Submitting forged witness i = -1 is rejected because -1 is not a nonnegative integer."""
    q = "Let a(i) = 16i + 3 and b(i) = 9i + 2. Is a(i) > b(i) for all nonnegative integers i?"
    spec = parse_problem(q)
    forged = {
        "definitions": spec.params["definitions"],
        "tasks": spec.params["tasks"],
        "results": [{
            "id": "claim", "op": "claim", "status": "disproved", "counterexample": "-1",
            "detail": "a(-1) = -13, b(-1) = -7",
        }],
    }
    checks = {name.split(":")[0]: (passed, detail) for name, passed, _, detail in check_structured(spec.params, forged, q)}
    assert checks["domain"][0] is False
    assert checks["computation"][0] is False


def test_s07_disproved_over_all_integers():
    """Over all integers, the claim a(i) > b(i) is legitimately disproved with valid witness i = -1."""
    q = "Let a(i) = 16i + 3 and b(i) = 9i + 2. Is a(i) > b(i) for all integers i?"
    spec = parse_problem(q)
    res = run_structured(spec.params["definitions"], spec.params["tasks"])
    assert res["results"][0]["status"] == "disproved"
    assert res["results"][0]["counterexample"] == "-1"
    checks = {name.split(":")[0]: passed for name, passed, *_ in check_structured(spec.params, res, q)}
    assert checks["domain"] is True
    assert checks["computation"] is True


# Held-out domain specifications --------------------------------------------------------------------------------------

def test_finite_set_domain():
    """A function defined on a finite set {1, 2, 5} cannot be evaluated at out-of-set numbers."""
    defs = [{"name": "f", "parameter": "x", "domain": "finite_set:{1,2,5}", "branches": [{"expression": "2*x + 1", "condition": ""}]}]
    tasks = [
        {"id": "f(1)", "op": "evaluate", "expression": "f(1)"},
        {"id": "f(2)", "op": "evaluate", "expression": "f(2)"},
        {"id": "f(3)", "op": "evaluate", "expression": "f(3)"},
        {"id": "f(5)", "op": "evaluate", "expression": "f(5)"},
    ]
    res = run_structured(defs, tasks)
    by_id = {r["id"]: r for r in res["results"]}
    assert by_id["f(1)"]["value"] == "3"
    assert by_id["f(2)"]["value"] == "5"
    assert by_id["f(3)"]["status"] == "undefined"
    assert by_id["f(5)"]["value"] == "11"


def test_strict_interval_domain():
    """A function defined on (0, 1] is undefined at the open endpoint 0."""
    defs = [{"name": "g", "parameter": "x", "domain": "interval:(0,1]", "branches": [{"expression": "1/x", "condition": ""}]}]
    tasks = [
        {"id": "g(1)", "op": "evaluate", "expression": "g(1)"},
        {"id": "g(1/2)", "op": "evaluate", "expression": "g(1/2)"},
        {"id": "g(0)", "op": "evaluate", "expression": "g(0)"},
        {"id": "g(2)", "op": "evaluate", "expression": "g(2)"},
    ]
    res = run_structured(defs, tasks)
    by_id = {r["id"]: r for r in res["results"]}
    assert by_id["g(1)"]["value"] == "1"
    assert by_id["g(1/2)"]["value"] == "2"
    assert by_id["g(0)"]["status"] == "undefined"
    assert by_id["g(2)"]["status"] == "undefined"


def test_real_exclusion_domain():
    """A function defined on reals excluding {4} evaluates at 2 but is undefined at 4."""
    defs = [{"name": "h", "parameter": "x", "domain": "real_excluding:{4}", "branches": [{"expression": "x + 4", "condition": ""}]}]
    tasks = [
        {"id": "h(2)", "op": "evaluate", "expression": "h(2)"},
        {"id": "h(4)", "op": "evaluate", "expression": "h(4)"},
    ]
    res = run_structured(defs, tasks)
    by_id = {r["id"]: r for r in res["results"]}
    assert by_id["h(2)"]["value"] == "6"
    assert by_id["h(4)"]["status"] == "undefined"


# Verifier identity counterexample validation -------------------------------------------------------------------------

def test_verify_identity_rejects_out_of_assumption_counterexample():
    """Identity verifier rejects counterexample violating assumptions."""
    spec = ProblemSpec(
        text="Prove log(x*y) = log(x) + log(y) for positive real x, y",
        domain="real",
        assumptions={"x": "positive", "y": "positive"},
        expression="log(x*y) = log(x) + log(y)",
    )
    # A negative counterexample x=-1, y=-2 violates positive assumption
    data_bad_ce = {"equivalent": False, "counterexample": {"x": -1, "y": -2}}
    verdict = _verify_identity(spec, {"lhs": "log(x*y)", "rhs": "log(x) + log(y)"}, data_bad_ce)
    assert verdict.status == "refuted"
    dom_check = next(c for c in verdict.checks if c.name == "counterexample in problem domain")
    assert dom_check.passed is False


# Schema validation ---------------------------------------------------------------------------------------------------

def test_schemas_accepts_valid_custom_domains():
    """StructuredDefinition and StructuredTask accept custom domains."""
    d = StructuredDefinition(
        name="r", parameter="n", domain="integer_ge_2",
        branches=[{"expression": "n^2 - 3*n + 7", "condition": ""}],
    )
    assert d.domain == "integer_ge_2"

    t = StructuredTask(id="claim", op="claim", domain="integer_ge_2", variable="n")
    assert t.domain == "integer_ge_2"


def test_schemas_rejects_invalid_domains():
    """StructuredDefinition and StructuredTask reject unparseable domains."""
    with pytest.raises(pydantic.ValidationError):
        StructuredDefinition(
            name="r", parameter="n", domain="primes",
            branches=[{"expression": "n", "condition": ""}],
        )
    with pytest.raises(pydantic.ValidationError):
        StructuredTask(id="claim", op="claim", domain="primes", variable="n")
