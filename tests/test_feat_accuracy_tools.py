"""Accuracy tools (tribos.axiom.accuracy): rigorous interval proofs, precision loss, falsification, replication and
distribution checks, each against a known answer."""

from __future__ import annotations

import numpy as np

from tribos.axiom import accuracy as acc


def test_interval_arithmetic_proves_a_true_inequality_and_refutes_a_false_one():
    proved = acc.interval_verify("x**2 - 2*x + 2", {"x": [-10, 10]}, "positive")
    assert proved["status"] == "proved" and "certificate" in proved
    refuted = acc.interval_verify("x**2 - 2", {"x": [-3, 3]}, "positive")
    assert refuted["status"] == "refuted" and refuted["value_enclosure"][1] <= 0
    assert acc.interval_verify("x*y + 1", {"x": [0, 1], "y": [0, 1]}, "positive")["status"] == "proved"
    lo, hi = acc.interval_verify("sin(x) + 2", {"x": [0, 6.3]})["enclosure"]
    assert lo <= 1.0 + 1e-12 and hi >= 3.0 - 1e-12  # never narrower than the true range [1, 3]


def test_the_certificate_script_reruns_the_proof():
    cert = acc.interval_verify("x**2 + 1", {"x": [-2, 2]}, "positive")["certificate"]
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(cert, "certificate", "exec"), {})  # noqa: S102 - our own generated script
    assert "proved on" in out.getvalue()


def test_precision_check_catches_cancellation_and_passes_a_stable_value():
    bad = acc.precision_check("(1 - cos(x))/x**2", {"x": "1e-8"})
    assert bad["status"] == "cancellation" and bad["evaluations"][-1]["value"].startswith("0.49999999999999999")
    assert acc.precision_check("exp(x)", {"x": "1"})["status"] == "ok"


def test_counterexample_search_finds_eulers_polynomial_failure_and_enumerates_small_domains():
    found = acc.counterexample_search("isprime(n**2 + n + 41)", {"n": {"type": "integer", "min": 0, "max": 100}})
    assert found["status"] == "counterexample" and found["counterexample"] == {"n": 40}
    assert acc.counterexample_search("isprime(n**2 + n + 41)",
                                     {"n": {"type": "integer", "min": 0, "max": 39}})["status"] == "verified_exhaustively"
    assert acc.counterexample_search("x**2 + 1 > 2*x", {"x": {"type": "real", "min": -5, "max": 5}})["status"] == "counterexample"
    held = acc.counterexample_search("(x + 1)**2 == x**2 + 2*x + 1", {"x": {"type": "real", "min": -5, "max": 5}})
    assert held["status"] == "none_found" and "not a proof" in held["note"]


def test_results_are_compared_exactly_for_integers_and_with_tolerance_for_floats():
    assert acc.compare_results({"a": 3, "b": 1.0 + 1e-12}, {"a": 3, "b": 1.0})["status"] == "agree"
    diff = acc.compare_results({"a": 3, "m": [1, 2]}, {"a": 4, "m": [1, 2]})
    assert diff["status"] == "disagree" and diff["disagree"] == 1
    assert acc.compare_results({"a": 1}, {"b": 1})["missing"] == 2


def test_cross_validation_runs_both_implementations_in_the_sandbox():
    same = acc.cross_validate("result = {'s': sum(range(101))}", "result = {'s': 100 * 101 // 2}")
    assert same["status"] == "agree"
    wrong = acc.cross_validate("result = {'s': sum(range(101))}", "result = {'s': 100 * 100 // 2}")
    assert wrong["status"] == "disagree"


def test_distribution_tests_accept_a_normal_sample_and_reject_an_exponential_one():
    rng = np.random.default_rng(1)
    normal = acc.distribution_tests(list(rng.normal(size=2000)))
    assert normal["status"] == "consistent_with_normal" and len(normal["qq"]["sample"]) == 200
    lo, hi = normal["bootstrap"]["mean_ci"]
    assert lo < normal["mean"] < hi
    assert acc.distribution_tests(list(rng.exponential(size=2000)))["status"] == "normal_rejected"


def test_the_tools_are_registered():
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    for name in ("axiom_interval_verify", "axiom_precision_check", "axiom_counterexample_search",
                 "calcula_distribution_tests", "calcula_cross_validate"):
        assert reg.get_entry(name) is not None, name
