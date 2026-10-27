"""
Tests for Feature F14: Preserve exact answer contracts and render mathematics cleanly.

Covers:
- S07: Extraction, validation, and conformance of exact/numbered item contracts.
- Warning banner and evidence limitations suppression under strict_form.
- Preamble/postamble trimming for exact items.
- S05: Polynomial proof heading extraction, prevention of literal ### in claims and UI notice.
- Proper identification of functions with compound arguments (e.g. P(1-z)).
- Exact line counts and visual wrapping preservation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tribos.utils.output_contract import (
    Contract,
    conform,
    extract,
    extract_items,
    validate,
    writer_rule,
)
from tribos.verify import math_claims
from tribos.verify.verifier import ClaimRecord, remove_flagged_sentences

# ---------------------------------------------------------------------------
# S07 Contract Tests: Exact Numbered Items
# ---------------------------------------------------------------------------


def test_s07_contract_extraction():
    q = "Provide exactly four numbered items explaining the synthesis steps. Add nothing else."
    c = extract(q)
    assert c.exact_items == 4
    assert c.numbered_items is True
    assert c.no_extra is True
    assert c.strict_form is True
    assert "exactly 4 numbered item(s)" in c.describe()

    # Semantic variants
    c2 = extract("Answer as 4 numbered items only.")
    assert c2.exact_items == 4
    assert c2.numbered_items is True
    assert c2.strict_form is True

    c3 = extract("In at most three items:")
    assert c3.max_items == 3
    assert c3.strict_form is True

    c4 = extract("List 5 items numbered 1 to 5.")
    assert c4.numbered_items is True


def test_s07_items_extraction_and_validation():
    contract = Contract(exact_items=4, numbered_items=True)

    valid_text = (
        "1. First step: prepare reagent.\n"
        "2. Second step: heat to 80°C.\n"
        "3. Third step: filter precipitate.\n"
        "4. Fourth step: recrystallize in ethanol."
    )
    assert validate(valid_text, contract) == []

    # Only 3 items -> violation
    three_items = (
        "1. First step.\n"
        "2. Second step.\n"
        "3. Third step."
    )
    violations = validate(three_items, contract)
    assert any("4 required" in v for v in violations)

    # Inconsistent numbering -> violation
    bullet_items = (
        "- First step.\n"
        "- Second step.\n"
        "- Third step.\n"
        "- Fourth step."
    )
    violations = validate(bullet_items, contract)
    assert any("numbered" in v for v in violations)


def test_s07_conformance_trims_preamble_postamble_and_banners():
    contract = extract("Give exactly four numbered items with the results:")
    assert contract.exact_items == 4
    assert contract.numbered_items is True
    assert contract.strict_form is True

    raw_response = (
        "> ⚠️ **Verification found errors**: 1 mathematical statement(s) in this answer do not hold.\n"
        "> P(z) = 0 is unverified\n\n"
        "Here are the four required results:\n\n"
        "1. Result alpha: $\\lambda_1 = 0.5$\n"
        "2. Result beta: $\\mu = 1.2$\n"
        "3. Result gamma: $\\sigma \\in [0, 1]$\n"
        "4. Result delta: $\\Omega = 42$\n\n"
        "In summary, all four steps have been computed.\n\n"
        "### Evidence limitations\n"
        "- P(z) could not be verified directly against empirical datasets."
    )

    conformed = conform(raw_response, contract)
    # Warning banner, preamble, summary postamble, and limitations header must be stripped
    assert "> ⚠️" not in conformed
    assert "Here are the four required results:" not in conformed
    assert "In summary" not in conformed
    assert "### Evidence limitations" not in conformed

    items = extract_items(conformed)
    assert len(items) == 4
    assert conformed.startswith("1. Result alpha:")
    assert conformed.endswith("4. Result delta: $\\Omega = 42$")

    # Final conformed response passes contract validation cleanly
    assert validate(conformed, contract) == []


def test_strict_form_suppresses_evidence_limitations_in_pruning():
    contract = Contract(exact_items=4, numbered_items=True)
    assert contract.strict_form is True

    @dataclass
    class DummyDefect:
        sentence: str = "This false sentence must be pruned."
        category: str = "CLAIM_CONTRADICTED"

    response = (
        "1. Item one.\n"
        "2. Item two. This false sentence must be pruned.\n"
        "3. Item three.\n"
        "4. Item four."
    )

    pruned, removed = remove_flagged_sentences(response, [DummyDefect()], contract=contract)
    assert len(removed) == 1
    assert "This false sentence must be pruned." not in pruned
    assert "### Evidence limitations" not in pruned
    assert "Item two." in pruned


def test_writer_rule_generates_strict_instruction():
    contract = extract("Provide exactly 4 numbered items.")
    rule = writer_rule(contract)
    assert "exactly 4 numbered item(s)" in rule
    assert "no headings, no Executive Summary" in rule


# ---------------------------------------------------------------------------
# S05 Math Claims & Rendering Tests: Proofs, Headings, and Display
# ---------------------------------------------------------------------------


def test_s05_heading_extraction_and_cleaning():
    proof_markdown = (
        "### Case 1: Polynomial symmetry and zeros\n\n"
        "Let $P(z) = (z - 1/3)(z - 2/3)$ for complex $z$.\n\n"
        "**Derivation:**\n"
        "$$\n"
        "\\begin{aligned}\n"
        "P(1-z) &= (1 - z - 1/3)(1 - z - 2/3) \\\\\n"
        "       &= (2/3 - z)(1/3 - z) \\\\\n"
        "       &= (z - 1/3)(z - 2/3) \\\\\n"
        "       &= P(z)\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "###Case 2: Roots and critical strip\n"
        "The roots are $z_1 = 1/3$ and $z_2 = 2/3$.\n"
        "Neither root satisfies $\\mathrm{Re}(z) = 1/2$.\n"
    )

    # Heading detection should clean ### and unspaced ###Case
    heading1 = math_claims._heading_before(proof_markdown, 50)
    assert heading1 == "Case 1: Polynomial symmetry and zeros"
    assert "###" not in heading1

    heading2 = math_claims._heading_before(proof_markdown, len(proof_markdown) - 20)
    assert heading2 == "Case 2: Roots and critical strip"
    assert "###" not in heading2

    # In-heading test
    assert math_claims._is_in_heading(proof_markdown, 10) is True  # inside line 1
    assert math_claims._is_in_heading(proof_markdown, proof_markdown.find("###Case 2") + 2) is True
    assert math_claims._is_in_heading(proof_markdown, proof_markdown.find("Let $P(z)")) is False


def test_s05_compound_argument_function_detection():
    doc = "Consider $P(1-z) = P(z)$ and $f(1+z) = f(z)$."
    funcs, var = math_claims._document_functions(doc, "P")
    assert "P" in funcs
    assert "f" in funcs
    assert var == "z"


def test_s05_claim_record_cleaning_no_hash_markers():
    @dataclass
    class DummyMathClaim:
        claim_id: str = "m1"
        kind: str = "relation"
        context: str = "### Case 1: Root Analysis"
        text: str = "### z_1 = 1/3"
        links: list[Any] = None
        status: str = "passed"
        detail: str = "verified by SymPy"

    mc = DummyMathClaim(links=[])
    clean_context = re.sub(r"^\s*#{1,6}\s*", "", mc.context).strip() if mc.context else ""
    clean_text = re.sub(r"^\s*#{1,6}\s*", "", mc.text).strip()
    claim_text = (f"{clean_context}: " if clean_context else "") + clean_text

    record = ClaimRecord(
        claim_id=f"math:{mc.claim_id}",
        claim_type="mathematical",
        claim_text=claim_text,
        evidence=[],
        status="supported",
        reason=mc.detail,
    )

    assert "###" not in record.claim_text
    assert record.claim_text == "Case 1: Root Analysis: z_1 = 1/3"


def test_multi_line_and_single_line_exact_contracts():
    c1 = extract("Give the answer on a single line.")
    assert c1.exact_lines == 1
    assert c1.strict_form is True
    assert validate("One line only", c1) == []
    assert len(validate("Line 1\nLine 2", c1)) == 1

    c2 = extract("Answer in exactly 2 lines.")
    assert c2.exact_lines == 2
    assert validate("Line 1\nLine 2", c2) == []
    assert len(validate("Line 1\nLine 2\nLine 3", c2)) == 1
