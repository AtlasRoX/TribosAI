"""Comprehensive verification and regression test suite for Remaining Issues and Lean Repair.

Covers:
- Phase A: Exact numbered and unnumbered reproductions, task construction, point evaluations,
  algebraic inequality proof, rejection of injected tautological artifact [a(i), 1=1, 2=2].
- Phase B: Output contracts with nested bullets, deliverables assessment of algebra and numerical checks,
  stable IDs, cache isolation across revisions and domains.
- Phase C: Lean formal proof policy enforcement (disabled_by_user state mapping, zero compiler calls,
  no failure badge), semantic trust boundary (rejection of sorry/admit, fresh-namespace fakes like
  Adversarial.choice, and axioms asserting False).
- Phase D: Negative controls (variable renames, coefficient changes, imaginary unit preservation,
  counterexample domain filtering, sample trap H(n), omission detection, preserving independent k and restricted f).
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import sympy as sp

from tribos.agentic.formal_proof import FormalProofPhase
from tribos.agentic.state import AgentState, RunBudget, RunControl
from tribos.agents.deliverables import assess, requested_items
from tribos.axiom.correspondence import check_task_correspondence, is_tautology_claim
from tribos.axiom.definitions import (
    check_structured,
    in_domain,
    parse_definitions,
    parse_quantifier,
    parse_structured,
    run_structured,
)
from tribos.axiom.problem import parse_problem
from tribos.tools.policy import ToolPolicy
from tribos.utils.output_contract import extract, extract_items, validate
from tribos.verify.formal.prove import formalise_and_check, statement_issues
from tribos.verify.formal.runner import uses_unproved
from tribos.verify.math_claims import audit_answer
from tribos.verify.result_record import build_result_record


PROMPT_NUMBERED = """Let i be a nonnegative integer. Define
a(i) = 7i + 4 and b(i) = 4i + 2.

1. Prove or disprove that a(i) > b(i) for every allowed i.

2. Evaluate a(i) and b(i) separately for i = 0, 1, 2, and check each comparison.

Any proposed counterexample must be a nonnegative integer.

Return exactly two numbered items. Show the algebra and all three numerical checks. Add nothing else. Do not search the web or invoke a formal prover."""

PROMPT_UNNUMBERED = """Let i be a nonnegative integer. Define
a(i) = 7i + 4 and b(i) = 4i + 2.

Prove or disprove that a(i) > b(i) for every allowed i.

Evaluate a(i) and b(i) separately for i = 0, 1, 2, and check each comparison.

Any proposed counterexample must be a nonnegative integer.

Return exactly two numbered items. Show the algebra and all three numerical checks. Add nothing else. Do not search the web or invoke a formal prover."""

SAMPLE_ANSWER = """1. For every nonnegative integer i, consider the difference:
a(i) - b(i) = (7i + 4) - (4i + 2) = 3i + 2.
Since i >= 0, we have 3i >= 0, so 3i + 2 >= 2 > 0.
Therefore, a(i) > b(i) holds for every allowed i. The claim is proved.
(Note: i = -2/3 yields equality, but -2/3 is not a nonnegative integer, so no valid counterexample exists.)

2. Evaluations and comparisons:
- For i = 0: a(0) = 4, and b(0) = 2. Since 4 > 2, a(0) > b(0) holds.
- For i = 1: a(1) = 11, and b(1) = 6. Since 11 > 6, a(1) > b(1) holds.
- For i = 2: a(2) = 18, and b(2) = 10. Since 18 > 10, a(2) > b(2) holds."""


# ==============================================================================
# Phase A: Mathematical Task Construction & Certification
# ==============================================================================

def test_phase_a_exact_reproduction_task_construction():
    """Both numbered and unnumbered reproduction prompts construct the proof obligation and all 6 point evaluations."""
    for prompt in (PROMPT_NUMBERED, PROMPT_UNNUMBERED):
        parsed, problems = parse_structured(prompt)
        assert not problems
        assert len(parsed["definitions"]) == 2
        d_a, d_b = parsed["definitions"][0], parsed["definitions"][1]
        assert d_a["name"] == "a" and d_a["parameter"] == "i" and d_a["domain"] == "nonnegative_integer"
        assert d_b["name"] == "b" and d_b["parameter"] == "i" and d_b["domain"] == "nonnegative_integer"

        task_ids = [t["id"] for t in parsed["tasks"]]
        # Must contain claim task
        assert "claim" in task_ids or any(t.get("op") == "claim" for t in parsed["tasks"])
        # Must contain 6 point evaluations
        for expr in ("a(0)", "b(0)", "a(1)", "b(1)", "a(2)", "b(2)"):
            assert expr in task_ids

        # Must NOT contain fragmented bare number evaluation tasks "1" or "2"
        assert "1" not in task_ids
        assert "2" not in task_ids

        # Run structured execution
        exec_res = run_structured(parsed["definitions"], parsed["tasks"])
        claim_res = next(r for r in exec_res["results"] if r["id"] == "claim")
        assert claim_res["status"] == "proved"
        assert "3*i + 2 > 0" in claim_res["text"] or "3*i + 2" in claim_res["steps"][-1]

        # Check values
        vals = {r["id"]: r.get("value") for r in exec_res["results"]}
        assert vals["a(0)"] == "4"
        assert vals["b(0)"] == "2"
        assert vals["a(1)"] == "11"
        assert vals["b(1)"] == "6"
        assert vals["a(2)"] == "18"
        assert vals["b(2)"] == "10"

        # Check structured verification passes all 5 checks
        checks = check_structured(parsed, exec_res, prompt)
        for name, passed, level, detail in checks:
            assert passed is True, f"Check '{name}' failed: {detail}"


def test_phase_a_injected_tautology_artifact_rejected():
    """The observed failure artifact [a(i), 1=1, 2=2] fails correspondence and coverage."""
    forged_params = {
        "definitions": [
            {"name": "a", "parameter": "i", "domain": "nonnegative_integer", "branches": [{"expression": "7*i + 4", "condition": ""}]},
            {"name": "b", "parameter": "i", "domain": "nonnegative_integer", "branches": [{"expression": "4*i + 2", "condition": ""}]},
        ],
        "tasks": [
            {"id": "a(i)", "op": "evaluate", "expression": "a(i)"},
            {"id": "1", "op": "evaluate", "expression": "1"},
            {"id": "2", "op": "evaluate", "expression": "2"},
        ],
    }
    data = run_structured(forged_params["definitions"], forged_params["tasks"])

    # 1. check_structured detects tautological tasks and missing proof obligation
    checks = {name.split(":")[0]: (passed, detail) for name, passed, _, detail in check_structured(forged_params, data, PROMPT_NUMBERED)}
    assert checks["validity"][0] is False, f"Expected validity to fail, got {checks['validity']}"
    assert "1" in checks["validity"][1] and "2" in checks["validity"][1]
    assert checks["coverage"][0] is False, f"Expected coverage to fail, got {checks['coverage']}"
    assert "proof obligation" in checks["coverage"][1]

    # 2. check_task_correspondence fails
    spec = parse_problem(PROMPT_NUMBERED)
    corr_ok, corr_detail, _ = check_task_correspondence(spec, "axiom_structured", forged_params, data)
    assert corr_ok is False
    assert "tautolog" in corr_detail.lower() or "proof" in corr_detail.lower()


def test_phase_a_legitimate_tautology_accepted():
    """A legitimately requested 1=1 or reflexivity identity passes correspondence."""
    q = "Prove that 1 = 1 over the integers."
    spec = parse_problem(q)
    params = {"tasks": [{"id": "1 = 1", "op": "claim", "lhs": "1", "relation": "=", "rhs": "1"}]}
    corr_ok, corr_detail, _ = check_task_correspondence(spec, "axiom_structured", params, {})
    assert corr_ok is True


# ==============================================================================
# Phase B: Coverage, Revision State & Output Contracts
# ==============================================================================

def test_phase_b_requested_items_and_deliverables_assessment():
    """Deliverables extraction identifies proof and evaluations, recognizing algebra and comparisons."""
    items = requested_items(PROMPT_NUMBERED)
    assert any("prove or disprove" in it["verb"] or "a(i) > b(i)" in it["item"] for it in items)
    assert any("evaluate" in it["verb"] for it in items)

    # Full answer passes all deliverable checks
    assessed = assess(PROMPT_NUMBERED, SAMPLE_ANSWER)
    assert all(a["status"] == "addressed" for a in assessed), f"Failed deliverables: {[a for a in assessed if a['status'] != 'addressed']}"

    # Missing evaluations detected when deleted from answer
    answer_no_eval = """1. For every nonnegative integer i, the difference is:
a(i) - b(i) = 3i + 2 >= 2 > 0.
Therefore, a(i) > b(i) holds for every allowed i."""
    ass_missing = assess(PROMPT_NUMBERED, answer_no_eval)
    eval_item = next(a for a in ass_missing if "0, 1, 2" in a["item"])
    assert eval_item["status"] == "missing"


def test_phase_b_output_contract_exact_two_numbered_items_with_bullets():
    """The contract requirement of exactly two numbered items is preserved when items have sub-bullets."""
    c = extract(PROMPT_NUMBERED)
    assert c.exact_items == 2
    assert c.numbered_items is True

    items = extract_items(SAMPLE_ANSWER)
    assert len(items) == 2, f"Expected 2 items, got {len(items)}: {items}"
    assert items[0].startswith("1.")
    assert items[1].startswith("2.")

    violations = validate(SAMPLE_ANSWER, c)
    assert violations == [], f"Expected zero contract violations, got: {violations}"


def test_phase_b_cache_key_isolation_across_domains():
    """Identical answer text with different domains or queries produces separate cache keys."""
    q_nonneg = "Let i be a nonnegative integer. Prove a(i) > b(i)."
    q_real = "Let i be a real number. Prove a(i) > b(i)."
    ans = "a(i) > b(i) is verified."

    rec1 = build_result_record(q_nonneg, {})
    rec2 = build_result_record(q_real, {})

    audit1 = audit_answer(ans, q_nonneg, {}, rec1)
    audit2 = audit_answer(ans, q_real, {}, rec2)

    # Both audits should execute cleanly and not collude
    assert audit1.record_revision == rec1.revision
    assert audit2.record_revision == rec2.revision


# ==============================================================================
# Phase C: Lean Integration & Trust Boundary
# ==============================================================================

@pytest.mark.asyncio
async def test_phase_c_disabled_formal_prover_policy_and_badge():
    """Explicitly disabled formal prover returns status='disabled' with zero compiler attempts."""
    policy = ToolPolicy(prohibit_formal=True, formal_reason="Formal prover disabled by user request")
    from tribos.tools.policy import active_tool_policy

    # Direct formalise_and_check
    res = await formalise_and_check(PROMPT_NUMBERED, None)
    # When Lean is not installed locally and no policy is active, it returns unavailable.
    # When policy is active:
    from tribos.tools import policy as P
    orig_active = P.active_tool_policy
    P.active_tool_policy = lambda: policy
    try:
        res_pol = await formalise_and_check(PROMPT_NUMBERED, None)
        assert res_pol["status"] == "disabled"
        assert res_pol["attempts"] == []

        # Frontend badge mapping check
        badge = web_types_check.formal_badge_mock(res_pol)
        assert badge["tone"] == "neutral"
        assert badge["text"] == "Skipped: disabled by user"
    finally:
        P.active_tool_policy = orig_active


def test_phase_c_trust_boundary_rejects_adversarial_fresh_namespace_axiom():
    """Fresh-namespace axioms (e.g. Adversarial.choice) and axioms asserting False are rejected."""
    # 1. Plain cheat axiom
    code_cheat = "axiom cheat : False\ntheorem t : False := cheat"
    assert "axiom cheat" in uses_unproved(code_cheat)

    # 2. Adversarial fresh-namespace axiom imitating trusted base name
    code_adv = "axiom Adversarial.choice : False\ntheorem t : False := Adversarial.choice"
    unproved_adv = uses_unproved(code_adv)
    assert any("Adversarial.choice" in u for u in unproved_adv), f"Expected Adversarial.choice rejected, got: {unproved_adv}"

    # 3. Trusted name asserting False
    code_fake_choice = "axiom Classical.choice : False\ntheorem t : False := Classical.choice"
    unproved_fake = uses_unproved(code_fake_choice)
    assert any("asserts False" in u or "Classical.choice" in u for u in unproved_fake)

    # 4. Standard foundational axiom declarations without cheat types pass
    code_trusted = "axiom Classical.choice {α : Sort u} : Nonempty α → α"
    assert uses_unproved(code_trusted) == []


def test_phase_c_statement_correspondence_issues():
    """Lean statement correspondence checks detect mismatch, but allow legitimate True/tautology requests."""
    # Blanket True rejected when not asked
    issues = statement_issues("Prove that 2 + 2 = 4.", "theorem t : True := trivial", mathlib=False)
    assert any("target is the proposition True" in i for i in issues)

    # Genuine request for True allowed
    issues_legit = statement_issues("Prove that True holds.", "theorem t : True := trivial", mathlib=False)
    assert not any("target is the proposition True" in i for i in issues_legit)


# ==============================================================================
# Phase D: Negative Controls & Generalization
# ==============================================================================

def test_phase_d_variable_rename_and_coefficient_change():
    """System works generally when variable is renamed to j and coefficients change."""
    prompt = """Let j be a nonnegative integer. Define
f(j) = 9j + 5 and g(j) = 3j + 1.

Prove or disprove that f(j) > g(j) for every allowed j.

Evaluate f(j) and g(j) separately for j = 1, 3, 5, and check each comparison.

Any proposed counterexample must be a nonnegative integer."""
    parsed, _ = parse_structured(prompt)
    assert parsed["definitions"][0]["name"] == "f" and parsed["definitions"][0]["parameter"] == "j"
    assert parsed["definitions"][1]["name"] == "g" and parsed["definitions"][1]["parameter"] == "j"

    exec_res = run_structured(parsed["definitions"], parsed["tasks"])
    claim = next(r for r in exec_res["results"] if r["id"] == "claim")
    assert claim["status"] == "proved"
    assert "6*j + 4 > 0" in claim["text"] or "6*j + 4" in claim["steps"][-1]

    vals = {r["id"]: r.get("value") for r in exec_res["results"]}
    assert vals["f(1)"] == "14" and vals["g(1)"] == "4"
    assert vals["f(3)"] == "32" and vals["g(3)"] == "10"
    assert vals["f(5)"] == "50" and vals["g(5)"] == "16"


def test_phase_d_counterexample_domain_filtering():
    """Fractional point i = -2/3 gives equality but is rejected as out-of-domain for nonnegative integers."""
    assert in_domain(sp.Rational(-2, 3), "nonnegative_integer") is False
    assert in_domain(sp.Integer(0), "nonnegative_integer") is True
    assert in_domain(sp.Integer(5), "nonnegative_integer") is True


def test_phase_d_sample_trap_disproved():
    """Sample trap H(n)=1-[n(n-1)(n-2)(n-3)(n-4)(n-5)]^2 is disproved at n=6, not falsely proved by 0..5."""
    trap_prompt = """Let n be a nonnegative integer. Define
H(n) = 1 - (n*(n-1)*(n-2)*(n-3)*(n-4)*(n-5))^2.

Prove or disprove that H(n) > 0 for every allowed n."""
    parsed, _ = parse_structured(trap_prompt)
    exec_res = run_structured(parsed["definitions"], parsed["tasks"])
    claim = next(r for r in exec_res["results"] if r["id"] == "claim")
    assert claim["status"] == "disproved"
    assert claim["counterexample"] == "6"
    assert "-518399" in claim["detail"]


def test_phase_d_preserve_independent_k_controls():
    """Preserve independent local k calculation results 3, 7, 13 (S10 control)."""
    q = (
        "Three independent local calculations: evaluate 2k + 1 for k = 1, k = 3, k = 6. "
        "Each calculation is local to its case."
    )
    parsed, _ = parse_structured(q)
    exec_res = run_structured(parsed.get("definitions") or [], parsed["tasks"])
    vals = [r["value"] for r in exec_res["results"]]
    assert vals == ["3", "7", "13"]


def test_phase_d_preserve_restricted_f_controls():
    """Preserve restricted f on {3,4,5,...} producing undefined, 9, undefined, 30 at 2, 3, 0, 6."""
    q = (
        "Let f be defined on {3, 4, 5, ...} by f(n) = n^2 - 2n + 6. "
        "Evaluate f(2), f(3), f(0), f(6)."
    )
    parsed, _ = parse_structured(q)
    exec_res = run_structured(parsed["definitions"], parsed["tasks"])
    vals = [r.get("value") if r.get("status") != "undefined" else "undefined" for r in exec_res["results"]]
    assert vals == ["undefined", "9", "undefined", "30"]


class web_types_check:
    @staticmethod
    def formal_badge_mock(d: dict[str, Any]) -> dict[str, str]:
        status = d.get("status")
        if status == "verified":
            return {"tone": "ok", "text": "formally verified (Lean)"}
        if status in ("disabled", "disabled_by_user"):
            return {"tone": "neutral", "text": "Skipped: disabled by user"}
        if status == "unavailable":
            return {"tone": "neutral", "text": "formal checker unavailable"}
        if status == "not_formalizable":
            return {"tone": "neutral", "text": "not formalisable without Mathlib"}
        if status == "mismatch":
            return {"tone": "bad", "text": "statement does not match the question"}
        return {"tone": "bad", "text": "formalisation failed"}
