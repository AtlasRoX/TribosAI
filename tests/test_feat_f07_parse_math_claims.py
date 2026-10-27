from __future__ import annotations

import sympy as sp

from tribos.verify.latex_math import ParseContext, parse_latex
from tribos.verify.math_claims import (
    INCONCLUSIVE,
    PASSED,
    audit_answer,
    claim_defects,
)


def test_boxed_numerals_and_formulas():
    # Boxed numerals
    ctx = ParseContext()
    assert parse_latex(r"\boxed{13}", ctx) == 13
    assert parse_latex(r"\boxed{\frac{1}{2}}", ctx) == sp.Rational(1, 2)

    # Boxed arithmetic inside answer
    md_pass = r"The final value is $\boxed{2 + 2} = 4$."
    audit_pass = audit_answer(md_pass)
    assert audit_pass.counts()["failed"] == 0
    assert audit_pass.counts()["passed"] >= 1

    md_fail = r"The final value is $\boxed{2 + 2} = 5$."
    audit_fail = audit_answer(md_fail)
    assert audit_fail.counts()["failed"] == 1


def test_pmod_and_modular_arithmetic():
    # pmod parsing
    assert parse_latex(r"17 \pmod{4}") == 1
    assert parse_latex(r"17 \bmod 4") == 1

    # Congruences in answer
    md_true = r"$$17 \equiv 1 \pmod{4}$$"
    audit_true = audit_answer(md_true)
    assert audit_true.counts()["failed"] == 0
    assert audit_true.counts()["passed"] == 1

    md_false = r"$$18 \equiv 1 \pmod{4}$$"
    audit_false = audit_answer(md_false)
    assert audit_false.counts()["failed"] == 1
    assert "modulo 4" in audit_false.failed[0].detail or "18" in audit_false.failed[0].detail


def test_quantifiers_and_domains():
    md = r"$$\forall n > 1, \quad n^2 > n$$"
    audit = audit_answer(md, query="Let n be an integer.")
    assert audit.counts()["failed"] == 0
    assert len(audit.claims) >= 1
    claim = audit.claims[0]
    assert claim.status == PASSED
    assert len(claim.quantifiers) >= 1
    assert "\\forall" in claim.quantifiers[0]
    assert len(claim.assumptions) >= 1
    assert "n" in claim.assumptions[0]

    # Trailing quantifier in parentheses
    md_trailing = r"$$n^3 \ge n \quad (\forall n \ge 1)$$"
    audit_tr = audit_answer(md_trailing, query="Let n be a positive integer.")
    assert audit_tr.counts()["failed"] == 0
    assert len(audit_tr.claims) >= 1
    assert len(audit_tr.claims[0].quantifiers) >= 1

    # False quantified claim
    md_bad = r"$$\forall x > 0, \quad x < 0$$"
    audit_bad = audit_answer(md_bad, query="Let x be real.")
    assert audit_bad.counts()["failed"] >= 1


def test_aligned_derivations_and_corruption_detection():
    # S05-style polynomial aligned derivation
    md_good = r"""
$$P(z) = 1 - z$$

$$\begin{aligned}
P(1-z) &= 1 - (1-z) \\
&= z
\end{aligned}$$
"""
    audit_good = audit_answer(md_good, query="Consider polynomial P(z) = 1 - z.")
    assert audit_good.counts()["failed"] == 0
    assert audit_good.counts()["passed"] >= 1

    # Corrupted aligned derivation (error in line 2)
    md_corrupted = r"""
$$\begin{aligned}
1 + 2 &= 3 \\
&= 9999
\end{aligned}$$
"""
    audit_corrupted = audit_answer(md_corrupted)
    assert audit_corrupted.counts()["failed"] >= 1
    assert any("9999" in c.detail for c in audit_corrupted.failed)


def test_function_iterates():
    # Collatz map S06-style definition
    from tribos.verify.result_record import ResultRecord

    record = ResultRecord(
        problem={
            "definitions": [
                {
                    "name": "T",
                    "parameter": "n",
                    "branches": [
                        {"condition": "even", "expression": "n / 2"},
                        {"condition": "odd", "expression": "(3*n + 1) / 2"},
                    ],
                }
            ],
            "variable": "n",
        }
    )

    # T(1) = 2, T(2) = 1, so T^2(1) = 1
    md_iter = r"We compute $T^2(1) = 1$ and $T(T(1)) = 1$."
    audit_iter = audit_answer(md_iter, query="Compute Collatz iterate", record=record)
    assert audit_iter.counts()["failed"] == 0
    assert audit_iter.counts()["passed"] >= 2

    # False iterate calculation
    md_bad_iter = r"We compute $T^2(1) = 99$."
    audit_bad_iter = audit_answer(md_bad_iter, query="Compute Collatz iterate", record=record)
    assert audit_bad_iter.counts()["failed"] >= 1


def test_headings_are_not_asserted_as_facts():
    # A heading naming a line or equation: ### Re(z) = 1/2
    md = r"""
# Analysis of Zeta Function

### Re(z) = 1/2

On the critical line, we observe symmetrical behavior.
"""
    audit = audit_answer(md, query="Discuss the critical line.")
    # Heading should not be evaluated as a global identity on all z
    assert audit.counts()["failed"] == 0
    headings = [c for c in audit.claims if c.kind == "heading"]
    assert len(headings) >= 1
    assert headings[0].status == INCONCLUSIVE
    assert "heading" in headings[0].detail.lower()


def test_refuted_claims_are_not_flagged_as_verifier_errors():
    # Explicit refutation of false statement
    md_refuted = r"We refute the false claim that $1 + 1 = 3$."
    audit_refuted = audit_answer(md_refuted)
    # The refutation of 1+1=3 should be confirmed (PASSED), NOT a verifier failure
    assert audit_refuted.counts()["failed"] == 0
    refuted_claims = [c for c in audit_refuted.claims if c.kind == "refuted"]
    assert len(refuted_claims) >= 1
    assert refuted_claims[0].status == PASSED
    assert "refutation confirmed" in refuted_claims[0].detail.lower()

    # Refuting a TRUE statement is an actual error
    md_bad_refutation = r"We refute the false assertion that $1 + 1 = 2$."
    audit_bad_ref = audit_answer(md_bad_refutation)
    assert audit_bad_ref.counts()["failed"] >= 1
    assert any("asserted to be false" in c.detail for c in audit_bad_ref.failed)

    # Genuine calculation error without refutation cue MUST fail
    md_genuine_err = r"Therefore, $2 + 2 = 5$."
    audit_err = audit_answer(md_genuine_err)
    assert audit_err.counts()["failed"] >= 1
    defects = claim_defects(audit_err)
    assert len(defects) >= 1
    assert defects[0]["category"] == "MATH_CONSISTENCY"


def test_inequalities_numeric_and_symbolic():
    # Numeric inequalities
    audit1 = audit_answer(r"Clearly $3 > 2$ and $5 \ge 5$ and $4 \le 10$.")
    assert audit1.counts()["failed"] == 0
    assert audit1.counts()["passed"] >= 3

    audit2 = audit_answer(r"We have $2 > 5$.")
    assert audit2.counts()["failed"] >= 1

    audit3 = audit_answer(r"We have $3 \ne 3$.")
    assert audit3.counts()["failed"] >= 1

    # S07-style inequality: 7i + 1 >= 1 > 0 for nonnegative integer i
    from tribos.verify.result_record import ResultRecord
    record = ResultRecord(problem={"domain": "nonnegative_integer", "variable": "i", "unknowns": ["i"]})
    md_ineq = r"$$7i + 1 \ge 1 > 0$$"
    audit_ineq = audit_answer(md_ineq, query="Let i be a nonnegative integer.", record=record)
    assert audit_ineq.counts()["failed"] == 0
    assert audit_ineq.counts()["passed"] >= 1


def test_deduplication_preserves_distinct_scopes():
    # Repeated in same section
    md_dups = r"""
$$x = 5$$

$$x = 5$$
"""
    audit_dups = audit_answer(md_dups)
    # The duplicate in the same scope should not produce duplicate entries
    claim_texts = [c.text for c in audit_dups.claims]
    assert claim_texts.count("x=5") <= 1

    # Across different cases, scopes are preserved
    from tribos.verify.result_record import ResultRecord
    record = ResultRecord(
        problem={
            "cases": [
                {"id": "Case 1", "bindings": {"n": "1"}},
                {"id": "Case 2", "bindings": {"n": "2"}},
            ]
        }
    )
    md_cases = r"""
### Case 1
$$y + 1 = 11$$

### Case 2
$$y + 1 = 11$$
"""
    audit_cases = audit_answer(md_cases, record=record)
    # Both cases should have their claims preserved with their respective case_id or context
    assert len(audit_cases.claims) >= 2
    assert audit_cases.claims[0].case_id == "Case 1" or "Case 1" in audit_cases.claims[0].context
    assert audit_cases.claims[1].case_id == "Case 2" or "Case 2" in audit_cases.claims[1].context
