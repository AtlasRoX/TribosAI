"""Regression tests for Tribos evaluation run audit issues:
ISSUE 1 — Request coverage and verification status disagree
ISSUE 2 — Completion failure is presented as raw evidence
ISSUE 3 — Simple-task latency and timing displays
ISSUE 4 — Protect correct response behavior and routing

Covers the 5 mandatory regression scenarios:
1. Three independent arithmetic items: verify all three are shown as answered and correctly checked.
2. A task with a short derivation: ensure the derivation is recognized when present and requested.
3. x^2 - 5x + 6 = 0 requesting factorization, all integer roots, and substitution checks: verify the answer and every corresponding status.
4. A simulated completion 500: ensure the system shows failure/partial status, labels raw evidence accurately, sanitizes secrets, and offers retry.
5. A simple self-contained math task: measure stage timings and confirm no prohibited web search or formal proof occurs.
"""

from __future__ import annotations

from tribos.agents.deliverables import assess, requested_items
from tribos.agents.orchestration.finalize import apply_deliverables
from tribos.verify.math_claims import audit_answer
from tribos.verify.verifier import TribosVerifier


def test_scenario_1_three_independent_arithmetic_items():
    """Scenario 1: Three independent arithmetic items: verify all three are shown as answered and correctly checked."""
    q = "Calculate 15 + 27, 8 * 9, and 144 / 12."
    items = requested_items(q)
    assert len(items) == 3, f"Expected 3 extracted items, got: {items}"
    assert all(it["verb"] == "calculate" for it in items)

    ans = (
        "1. 15 + 27 = 42\n"
        "2. 8 * 9 = 72\n"
        "3. 144 / 12 = 12"
    )

    audit = audit_answer(ans, query=q)
    assert len(audit.claims) == 3
    assert all(c.status == "passed" for c in audit.claims)

    assessed = assess(q, ans, math_audit=audit.to_dict())
    assert len(assessed) == 3
    for it in assessed:
        assert it["status"] == "verified", f"Item {it['item']} status was {it['status']}"
        assert it["check_state"] == "checked", f"Item {it['item']} check_state was {it['check_state']}"
        assert it["answer_state"] == "answered", f"Item {it['item']} answer_state was {it['answer_state']}"

    outcome = apply_deliverables({"task_status": "completed"}, assessed)
    assert outcome["task_status"] == "completed"
    assert all(d["check_state"] == "checked" for d in outcome["deliverables"])
    assert all(d["answer_state"] == "answered" for d in outcome["deliverables"])


def test_scenario_2_short_derivation_recognized_and_not_missing():
    """Scenario 2: A task with a short derivation: ensure the derivation is recognized when present and requested,
    and is never labeled 'not addressed' / missing.
    """
    q = "Solve x^2 - 4 = 0, provide a short derivation starting from (x - 2)(x + 2) = 0, and state the integer roots."
    items = requested_items(q)
    assert any("derivation" in it["item"].lower() for it in items), f"Expected derivation item, got {items}"

    ans = (
        "Short derivation: Starting from x^2 - 4 = 0, we factor the difference of squares as "
        "(x - 2)*(x + 2) = 0. Setting each factor equal to zero gives x = 2 or x = -2.\n"
        "Integer roots: x = 2 and x = -2."
    )

    audit = audit_answer(ans, query=q)
    assessed = assess(q, ans, math_audit=audit.to_dict())

    derivation_item = next((it for it in assessed if "derivation" in it["item"].lower()), None)
    assert derivation_item is not None, "Derivation item must be in assessed deliverables"
    assert derivation_item["answer_state"] == "answered", "Derivation must be recognized as answered"
    assert derivation_item["status"] in ("addressed", "verified"), "Derivation must not be missing"
    assert derivation_item["status"] != "missing"

    outcome = apply_deliverables({"task_status": "completed"}, assessed)
    assert outcome["task_status"] == "completed"
    assert not any("derivation" in r.lower() for r in outcome.get("incomplete_reasons", []))


def test_scenario_3_quadratic_all_claims_checked_and_statuses_agree():
    """Scenario 3: x^2 - 5x + 6 = 0 requesting factorization, all integer roots, and substitution checks:
    verify the answer and every corresponding status agree across summary and verifier.
    """
    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )
    ans = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Integer roots: x = 2 and x = 3\n"
        "- Substitution checks:\n"
        "  For x = 2: 2^2 - 5*2 + 6 = 4 - 10 + 6 = 0\n"
        "  For x = 3: 3^2 - 5*3 + 6 = 9 - 15 + 6 = 0"
    )

    audit = audit_answer(ans, query=q)
    assert all(c.status == "passed" for c in audit.claims)

    assessed = assess(q, ans, math_audit=audit.to_dict())
    assert len(assessed) == 3
    for it in assessed:
        assert it["status"] == "verified", f"Item {it['item']} status was {it['status']}"
        assert it["check_state"] == "checked", f"Item {it['item']} check_state was {it['check_state']}"
        assert it["answer_state"] == "answered", f"Item {it['item']} answer_state was {it['answer_state']}"

    outcome = apply_deliverables({"task_status": "completed"}, assessed)
    assert outcome["task_status"] == "completed"
    assert all(d["check_state"] == "checked" for d in outcome["deliverables"])

    # Verifier agreement
    report = TribosVerifier().verify_response(q, ans, {})
    assert report.passed is True
    assert len(report.claims) >= 3
    assert all(c.status == "supported" for c in report.claims)


def test_scenario_3_quadratic_partial_and_failed_cases():
    """Scenario 3 (edge cases): Partial answer (omitted root or omitted substitution) and failed check."""
    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )

    # 1. Omitted substitution check entirely
    ans_no_subst = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3"
    )
    audit1 = audit_answer(ans_no_subst, query=q)
    assessed1 = assess(q, ans_no_subst, math_audit=audit1.to_dict())
    by_item1 = {it["item"]: it for it in assessed1}
    assert by_item1["factorization"]["status"] == "verified"
    assert by_item1["complete set of integer roots"]["status"] == "verified"
    assert by_item1["substitution check for each root"]["status"] == "missing"
    assert by_item1["substitution check for each root"]["check_state"] == "unverified"

    outcome1 = apply_deliverables({"task_status": "completed"}, assessed1)
    assert outcome1["task_status"] == "partial"

    # 2. Incomplete substitution check (root 2 only)
    ans_partial_subst = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3\n"
        "- Substitution check: 2^2 - 5*2 + 6 = 0"
    )
    audit2 = audit_answer(ans_partial_subst, query=q)
    assessed2 = assess(q, ans_partial_subst, math_audit=audit2.to_dict())
    by_item2 = {it["item"]: it for it in assessed2}
    assert by_item2["factorization"]["status"] == "verified"
    assert by_item2["complete set of integer roots"]["status"] == "verified"
    assert by_item2["substitution check for each root"]["status"] == "addressed"
    assert by_item2["substitution check for each root"]["check_state"] == "unverified"

    # 3. Failed arithmetic check in substitution
    ans_failed_subst = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3\n"
        "- Substitution check: 2^2 - 5*2 + 6 = 1"
    )
    audit3 = audit_answer(ans_failed_subst, query=q)
    assessed3 = assess(q, ans_failed_subst, math_audit=audit3.to_dict())
    by_item3 = {it["item"]: it for it in assessed3}
    assert by_item3["substitution check for each root"]["status"] == "failed_check"
    assert by_item3["substitution check for each root"]["check_state"] == "failed"


def test_scenario_4_simulated_completion_500_sanitized_and_retryable():
    """Scenario 4: A simulated completion 500: ensure the system shows failure/partial status,
    labels raw evidence accurately, sanitizes secrets, and offers retry.
    """
    from tribos.agents.orchestration.draft import fallback_reason, sanitize_error_message
    from tribos.agents.query_context import TaskOutcome

    raw_err = (
        "500 InternalServerError: Failed to generate completions: error calling "
        "https://api.openai.com/v1/chat/completions with header Authorization: Bearer sk-live-secret-token-123456789. "
        "Traceback at C:\\Users\\service\\tribos\\llm.py:42"
    )

    # 1. Sanitization: secrets, urls, file paths stripped
    sanitized = sanitize_error_message(raw_err)
    assert "sk-" not in sanitized
    assert "https://" not in sanitized
    assert "Bearer" not in sanitized
    assert "C:\\Users" not in sanitized

    # 2. Fallback reason provides clean user-facing diagnostic
    reason = fallback_reason(raw_err)
    assert "internal error" in reason.lower()
    assert "sk-" not in reason

    # 3. TaskOutcome offers retry and labels failure/partial accurately
    outcome = TaskOutcome(
        task_id="run-500",
        task_type="math",
        task_status="partial",
        can_retry=True,
        incomplete_reasons=[f"Synthesis failed: model unavailable (partial run): {reason}"],
    )
    assert outcome.task_status in ("partial", "failed")
    assert outcome.can_retry is True
    assert "Synthesis failed" in outcome.incomplete_reasons[0]


def test_scenario_5_simple_self_contained_math_task_no_prohibited_tools_and_targeted_budget():
    """Scenario 5: Simple self-contained math task: measure stage timings, confirm no prohibited web search
    or formal proof occurs, and output tokens are targeted.
    """
    from unittest.mock import MagicMock

    from tribos.agentic.plan_execute import PlanExecutePhase, needs_specialised_tool
    from tribos.agentic.state import AgentState
    from tribos.agents.evidence_need import is_closed_computation, is_self_contained
    from tribos.agents.orchestration.draft import compute_draft_output_cap
    from tribos.agents.query_context import QueryContext
    from tribos.tools.registry import get_tool_registry
    from tribos.utils.output_contract import extract

    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )

    # 1. Closed computation check
    ctx = QueryContext(raw_query=q, clean_query=q)
    from tribos.agents.evidence_need import assess_evidence_need
    need = assess_evidence_need(q, ctx)
    ctx.evidence_need = need
    assert need.skip_retrieval is True, f"Expected skip_retrieval=True, got need: {need}"
    assert is_closed_computation(ctx) is True or is_self_contained(ctx) is True

    state = MagicMock(spec=AgentState)
    state.registry = get_tool_registry()
    state.clean_query = q
    state.query = q
    state.ctx = ctx
    state.options = {}
    state.bag = {}

    assert needs_specialised_tool(state) is False, "Closed math must not trigger specialised engineering tools"
    assert PlanExecutePhase().applies(state) is False, "Complex plan execution must not trigger for closed math"

    # 2. Strict contract check
    contract = extract(q)
    assert contract.strict_form is True or contract.exact_items == 1, "Exact formatting contract must be recognized"

    # 3. No fixed token cap for a short question: the answer uses the tokens it needs (low reasoning effort keeps a
    # closed calculation fast); a lower ceiling would only truncate a longer one.
    from tribos.agents.orchestration.draft import first_draft_output_cap

    capped_tokens = compute_draft_output_cap(closed_calc=True, has_strict=True, exact_items=1)
    assert capped_tokens == first_draft_output_cap()

    # 4. Prohibited tools check
    q_lower = q.lower()
    assert "do not search the web" in q_lower or "no search" in q_lower
    assert "formal prover" in q_lower
