from __future__ import annotations

from pathlib import Path

import pytest

from tribos.verify.math_claims import audit_answer

FAMILY_QUERY = (
    "Let n be an integer with n ≥ 3 and n ≡ 3 (mod 4), and set k = (n - 3)/4. "
    "Define x = k + 1 and y = z = 2(k + 1)n. Show positivity, ordering, and the reciprocal identity. "
    "Give the triples for n = 3 and n = 7."
)


def test_actual_scoped_family_response_has_no_false_contradictions():
    md = (Path(__file__).parent / "fixtures/math/erdos_scoped_family.md").read_text()
    audit = audit_answer(md, FAMILY_QUERY)
    assert not audit.failed, [(c.text, c.detail) for c in audit.failed]


@pytest.mark.parametrize(
    "claim",
    [
        r"$1\,\mathrm{mm}^4 = 10^{-12}\,\mathrm{m}^4$",
        r"$E=200\,\mathrm{GPa}=200\times10^9\,\mathrm{Pa}=2.0\times10^{11}\,\mathrm{Pa}$",
        r"$c=20\times(1/1000)\,\mathrm m=0.02\,\mathrm m$",
    ],
)
def test_correct_si_conversions_are_not_contradicted(claim):
    assert not audit_answer(claim, "Calculate beam stress using SI units.").failed


def test_wrong_unit_scale_is_still_rejected():
    out = audit_answer(r"$1\,\mathrm{mm}=1\,\mathrm m$", "Check unit conversions.")
    assert out.failed


def test_audit_cache_covers_table_results_and_scope_prose():
    good = "| Quantity | Formula | Value | Unit |\n|---|---|---|---|\n| Force | $F = 2*3$ | 6 | N |"
    bad = good.replace("| 6 |", "| 9 |")
    assert not audit_answer(good).failed
    assert audit_answer(bad).failed
    assert not audit_answer(bad).reused or audit_answer(bad).failed


def test_returned_audit_cannot_mutate_the_cached_verdict():
    q = "Check an exact numerical equality."
    first = audit_answer("$123 + 2 = 125$", q)
    assert first.claims[0].status == "passed"
    first.claims[0].status = "failed"
    assert audit_answer("$123 + 2 = 125$", q).claims[0].status == "passed"
