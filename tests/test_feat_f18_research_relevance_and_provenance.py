"""
Tests for Feature F18: Preserve research relevance, factual scope and claim-to-source provenance.

Covers:
- T12: Collatz forward cycle correctness (1 -> 4 -> 2 -> 1, not reversed).
- T12: Tao's logarithmic-density almost-bounded-minimum theorem correctly stated, without overclaiming convergence to 1.
- T43 / I41: Sourced status claim is judged against the specific cited page, not arbitrary keyword matches.
- T40 / I40: Counter-evidence for dropped claims is reconciled into labeled history.
- T13: Source relevance and claim-to-source provenance (titles claiming proof do not establish theorem validity; irrelevant sources rejected).
"""

from __future__ import annotations

from tribos.agentic.counter_evidence import reconcile_with_answer
from tribos.agents.deliverables import assess
from tribos.verify.math_claims import audit_answer
from tribos.verify.verifier import TribosVerifier, _Doc

# ---------------------------------------------------------------------------
# 1. T12: Collatz Forward Cycle & Order
# ---------------------------------------------------------------------------


def test_f18_collatz_forward_cycle_order():
    rules = (
        "Define T(n) = n/2 for even positive integers and T(n) = 3n + 1 for odd positive integers.\n"
        "Compute T(1), T(2), and T(4), and write the cycle starting at 1."
    )
    # Correct forward cycle: 1 -> 4 -> 2 -> 1
    correct_cycle = (
        "T(1) = 3(1) + 1 = 4\n"
        "T(4) = 4/2 = 2\n"
        "T(2) = 2/2 = 1\n"
        "The cycle starting at 1 is 1 -> 4 -> 2 -> 1."
    )
    audit_correct = audit_answer(correct_cycle, rules)
    assert not [c for c in audit_correct.claims if c.status == "failed"]

    # Inverted/reversed cycle: 1 -> 2 -> 4 -> 1 contradicts T(1) = 4
    inverted_cycle = (
        "T(1) = 2\n"
        "T(2) = 4\n"
        "T(4) = 1\n"
        "The cycle starting at 1 is 1 -> 2 -> 4 -> 1."
    )
    audit_inverted = audit_answer(inverted_cycle, rules)
    assert any(c.status == "failed" for c in audit_inverted.claims)


# ---------------------------------------------------------------------------
# 2. T12: Tao's Theorem Limitation & Scientific Status
# ---------------------------------------------------------------------------


def test_f18_tao_collatz_theorem_distinctions():
    # Tao (2019, arXiv:1909.03562) proved that almost all Collatz orbits attain almost bounded values
    # in the sense of logarithmic density. The conjecture itself remains an open problem.
    tao_doc = _Doc(
        "arXiv:1909.03562",
        "Almost all orbits of the Collatz map attain almost bounded values. "
        "The Collatz conjecture remains an open problem; this does not establish that almost all orbits reach 1.",
        None,
        "",
        "https://arxiv.org/abs/1909.03562",
    )

    verifier = TribosVerifier()

    # Faithful status claim supported by Tao's paper
    accurate_claim = (
        "The Collatz conjecture remains an open problem: https://arxiv.org/abs/1909.03562"
    )
    status, reason, doc, _pos = verifier._status_verdict(accurate_claim, [tao_doc])
    assert status == "supported" and doc is tao_doc

    # Unsupported claim where cited document does not state that status
    wrong_claim = (
        "The Goldbach conjecture remains an open problem: https://arxiv.org/abs/1909.03562"
    )
    status, reason, doc, _pos = verifier._status_verdict(wrong_claim, [tao_doc])
    assert status == "unsupported" and "does not state" in reason


# ---------------------------------------------------------------------------
# 3. T43 & I41: Sourced Status Claim Bound to Cited Page
# ---------------------------------------------------------------------------


def test_f18_status_claim_bound_to_cited_page():
    verifier = TribosVerifier()

    other_doc = _Doc(
        "DOI:10.5281/zenodo.12345",
        "A proposed proof of the Riemann Hypothesis; the hypothesis remains an open problem.",
        None,
        "",
    )
    cmi_doc = _Doc(
        "web:claymath",
        "The Riemann Hypothesis is a Millennium Prize Problem. Unsolved. All non-trivial zeros lie on the critical line.",
        None,
        "",
        "https://www.claymath.org/millennium/riemann-hypothesis/",
    )

    claim = "The Riemann Hypothesis remains unsolved: https://www.claymath.org/millennium/riemann-hypothesis/"

    # Judged against the cited CMI document, not the other document
    status, reason, doc, _pos = verifier._status_verdict(claim, [other_doc, cmi_doc])
    assert status == "supported"
    assert doc is cmi_doc
    assert "accepted status" in reason

    # Snippet search hit is marked not_checked, not unsupported
    snippet_doc = _Doc(
        "web:claymath",
        "results: riemann hypothesis - clay mathematics institute",
        None,
        "",
        "https://www.claymath.org/millennium/riemann-hypothesis/",
    )
    status, reason, doc, _pos = verifier._status_verdict(claim, [other_doc, snippet_doc])
    assert status == "not_checked"
    assert "snippet" in reason


# ---------------------------------------------------------------------------
# 4. T40 & I40: Counter-evidence Reconciled into Labeled History
# ---------------------------------------------------------------------------


def test_f18_counter_evidence_reconciled_with_answer():
    art = {
        "conflicts": [
            {"claim": "The distribution of primes shows structured and random characteristics", "label": "contradicts"},
            {"claim": "The Riemann Hypothesis remains an unsolved Millennium Prize Problem", "label": "neutral"},
        ]
    }
    # Answer only includes the second claim; the first was dropped during revision
    reconcile_with_answer(
        art,
        "The Riemann Hypothesis remains an unsolved Millennium Prize Problem (Clay Mathematics Institute).",
    )

    # Surviving claim stays in conflicts
    assert len(art["conflicts"]) == 1
    assert art["conflicts"][0]["label"] == "neutral"

    # Dropped claim moves to history
    assert len(art["history"]) == 1
    assert art["history"][0]["label"] == "contradicts"
    assert "history_note" in art


# ---------------------------------------------------------------------------
# 5. T43 Deliverables: Source URL Link Assessment
# ---------------------------------------------------------------------------


def test_f18_deliverable_assesses_source_url_presence():
    q = "What is the current accepted status of the Riemann Hypothesis? Answer in one sentence and include the source URL."

    # Answer containing markdown link delivers the source URL item
    resp_with_link = "The Riemann Hypothesis remains open ([Clay Mathematics Institute](https://www.claymath.org/millennium/riemann-hypothesis/))."
    items_addressed = {d["item"]: d["status"] for d in assess(q, resp_with_link)}
    assert items_addressed.get("source URL") == "addressed"

    # Answer without link fails deliverable
    resp_without_link = "The Riemann Hypothesis remains an open conjecture."
    items_missing = {d["item"]: d["status"] for d in assess(q, resp_without_link)}
    assert items_missing.get("source URL") == "missing"
