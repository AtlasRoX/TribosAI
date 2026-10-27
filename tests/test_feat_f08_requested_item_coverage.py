"""Tests for Feature F08: Make requested-item coverage and task status agree with actual work.

Covers:
- S05's four obligations (polynomial symmetry, roots, symmetry decision, RH limitation)
- S08/S09's two obligations (integer domain proof vs real inequality solved via tool), mapping tool to question 2
- S07's independent obligations (compute 2k+1, prove a>b, check i=0,1,2)
- Structured item IDs (req-1, req-2, ...)
- Separate tracking of answer_state, check_state, and status
- Hand proof addressed without machine verification is never called missing
- Direct workflow synchronization of sub-questions: no stale open state
- Literature retrieval distinguished from machine verification: supported_by_retrieval vs checked
"""

from __future__ import annotations

from tribos.agentic.state import AgentState, RunBudget, RunControl, SubQuestion
from tribos.agents.deliverables import assess, requested_items
from tribos.agents.orchestration.finalize import _sync_sub_questions, apply_deliverables


def test_f08_s05_four_obligations_extracted_and_structured_ids():
    """S05: Four-part polynomial task extracts structured items for all four obligations."""
    q = (
        "For P(z)=(z-1/3)(z-2/3), z complex: prove P(1-z)=P(z); find/check all zeros; "
        "decide whether symmetry forces zeros onto Re(z)=1/2; explain why this does not decide RH. "
        "Show derivations and separate proved conclusions from non-conclusions."
    )
    items = requested_items(q)
    assert len(items) >= 4, f"Expected at least 4 items, got: {items}"

    # IDs must be structured
    for i, it in enumerate(items, 1):
        assert it["id"] == f"req-{i}"

    item_texts = [it["item"] for it in items]
    assert any("P(1-z)=P(z)" in t for t in item_texts), "P(1-z)=P(z) must be extracted"
    assert any("zeros" in t for t in item_texts), "zeros must be extracted"
    assert any("symmetry" in t and ("1/2" in t or "forces" in t) for t in item_texts), "symmetry decision must be extracted"
    assert any("RH" in t or "decide" in t for t in item_texts), "RH limitation must be extracted"


def test_f08_s08_s09_two_obligations_and_domains_preserved():
    """S08/S09: Two independent inequality domains preserve integer vs real domains."""
    for var in ("m", "i"):
        q = (
            f"Two independent domains: prove/disprove 5{var}+4>2{var}+1 for every nonnegative integer {var}, "
            f"requiring any witness in-domain; solve same inequality over reals. Exactly two numbered items with algebra, "
            f"nothing else; no search or formal prover."
        )
        items = requested_items(q)
        assert len(items) == 2, f"Expected exactly 2 items for {var}, got: {items}"
        assert items[0]["id"] == "req-1"
        assert items[1]["id"] == "req-2"

        # Domain conditions preserved
        assert "integer" in items[0]["item"].lower() or f"5{var}+4>2{var}+1" in items[0]["item"]
        assert "reals" in items[1]["item"].lower() or "same inequality" in items[1]["item"]


def test_f08_s07_independent_items_extracted():
    """S07: Formula expressions with coefficients and coordinate list bindings are extracted."""
    q = (
        "Four independent items: k=1,k=3,k=6, compute 2k+1 in each; for nonnegative integer i, "
        "a(i)=16i+3,b(i)=9i+2, prove a>b and check i=0,1,2. Exactly four numbered items; no web search or formal prover."
    )
    items = requested_items(q)
    assert len(items) >= 3, f"Expected at least 3 items, got: {items}"
    item_texts = [it["item"] for it in items]
    assert any("2k+1" in t for t in item_texts)
    assert any("a>b" in t or "a(i)" in t for t in item_texts)
    assert any("0,1,2" in t or "i=0" in t for t in item_texts)


def test_f08_s08_hand_proof_plus_tool_result_mapping():
    """S08: In the two-part inequality, real inequality maps to question 2, and hand proof is answered without machine verification."""
    q = (
        "Two independent domains: prove/disprove 5m+4>2m+1 for every nonnegative integer m, "
        "requiring any witness in-domain; solve same inequality over reals."
    )
    answer = r"""
1. For nonnegative integers m >= 0:
(5m + 4) - (2m + 1) = 3m + 3 = 3(m + 1).
Since m >= 0, m + 1 >= 1, so 3(m + 1) >= 3 > 0.
Thus 5m + 4 > 2m + 1 holds for all nonnegative integers m.

2. Over the reals:
5m + 4 > 2m + 1 <=> 3m > -3 <=> m > -1.
Solution set: (-1, \infty).
"""
    tool_results = {
        "axiom_inequality": {"success": True, "solution_set": "Interval.open(-1, oo)"}
    }

    assessed = assess(q, answer, tool_results=tool_results)
    assert len(assessed) == 2

    # Item 1: Hand proof is answered, unverified, NOT missing
    it1 = assessed[0]
    assert it1["answer_state"] == "answered"
    assert it1["check_state"] == "unverified"
    assert it1["status"] == "addressed"
    assert it1["where"] != ""

    # Item 2: Real inequality maps to tool result
    it2 = assessed[1]
    assert it2["answer_state"] == "answered"
    assert it2["check_state"] == "checked"
    assert it2["status"] == "verified"
    assert "axiom_inequality" in it2["evidence"]

    # Overall task status is completed (not partial or missing)
    outcome = apply_deliverables({"task_status": "completed", "reason": "Evidence gathered and synthesized."}, assessed)
    assert outcome["task_status"] == "completed"
    assert not outcome.get("incomplete_reasons")


def test_f08_sync_subquestions_in_direct_workflow():
    """Sub-questions in Direct workflow are synchronized so they are not left with stale 'open' status."""
    class DummyLLM:
        available = False

    class DummyContext:
        scope = "research"

    state = AgentState(
        query="dummy",
        clean_query="dummy",
        ctx=DummyContext(),
        registry=None,
        user_id="u1",
        thread_id="t1",
        model_name="m1",
        api_key=None,
        framework="direct",
        budget=RunBudget(),
        control=RunControl(user_id="u1", interactive=False),
        llm=DummyLLM(),
        tool_results={},
        emit=None,
        send=None,
        sub_questions=[
            SubQuestion(id="q1", text="prove/disprove 5m+4>2m+1 for nonnegative integer m"),
            SubQuestion(id="q2", text="solve same inequality over reals"),
        ],
    )

    items = [
        {"id": "req-1", "item": "5m+4>2m+1 for every nonnegative integer m", "verb": "prove", "status": "addressed",
         "answer_state": "answered", "check_state": "unverified", "evidence": []},
        {"id": "req-2", "item": "same inequality over reals", "verb": "solve", "status": "verified",
         "answer_state": "answered", "check_state": "checked", "evidence": ["axiom_inequality"]},
    ]

    _sync_sub_questions(state, items)

    assert len(state.sub_questions) == 2
    q1 = state.sub_questions[0]
    assert q1.status == "answered"
    assert q1.answer_state == "answered"
    assert q1.check_state == "unverified"

    q2 = state.sub_questions[1]
    assert q2.status == "answered"
    assert q2.answer_state == "answered"
    assert q2.check_state == "checked"
    assert "axiom_inequality" in q2.evidence_keys

    # Incomplete status check confirms 0 unresolved
    info = state.incomplete_status()
    assert not info.get("unresolved")
    assert not info.get("incomplete_reasons")


def test_f08_distinguish_retrieval_support_from_machine_check():
    """Literature retrieval sets check_state to supported_by_retrieval, not checked."""
    sq = SubQuestion(id="q1", text="Collatz descent")
    sq.add_evidence("europepmc_12345", "Europe PMC (Collatz)")
    sq.status = "answered"
    sq.answer_state = "answered"
    sq.check_state = "supported_by_retrieval"

    d = sq.to_dict()
    assert d["status"] == "answered"
    assert d["answer_state"] == "answered"
    assert d["check_state"] == "supported_by_retrieval"
    assert "europepmc_12345" in d["evidence_keys"]


def test_f08_actual_missing_section_is_marked_missing():
    """When a required section is genuinely omitted, it is correctly marked missing and incomplete."""
    q = "Calculate the steady-state amplitude. Explain the physical damping mechanism."
    # Answer provides amplitude, but completely omits physical damping
    answer = "The steady-state amplitude is X_0 = 12.5 mm."
    claims = [{"source_text": "X_0 = 12.5 mm", "status": "passed"}]
    assessed = assess(q, answer, math_audit={"claims": claims})

    by_item = {it["item"]: it for it in assessed}
    assert "steady-state amplitude" in by_item
    assert by_item["steady-state amplitude"]["status"] == "verified"

    assert "physical damping mechanism" in by_item
    assert by_item["physical damping mechanism"]["status"] == "missing"
    assert by_item["physical damping mechanism"]["answer_state"] == "missing"

    out = apply_deliverables({"task_status": "completed"}, assessed)
    # The missing prose item is recorded in deliverables
    assert any(it["status"] == "missing" for it in out["deliverables"])


def test_f08_reproduction_solve_factorization_roots_subst_checks():
    """Reproduction: Solving quadratic with factorization, complete roots, and substitution checks.
    When all 3 claims are checked and supported, the requested item must be 'verified' / 'checked',
    not 'answered, not checked', ensuring summary, item row, and verification panel agree.
    """
    from tribos.verify.math_claims import audit_answer
    from tribos.verify.verifier import TribosVerifier

    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )
    answer = (
        "1. Factorization, roots, and substitution check:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3\n"
        "- Substitution checks:\n"
        "  For x = 2: 2^2 - 5*2 + 6 = 0\n"
        "  For x = 3: 3^2 - 5*3 + 6 = 0"
    )

    audit = audit_answer(answer, query=q)
    assert len(audit.claims) == 3
    assert all(c.status == "passed" for c in audit.claims)

    assessed = assess(q, answer, math_audit=audit.to_dict())
    assert len(assessed) == 1
    it = assessed[0]
    assert it["item"] == "x^2 - 5x + 6 = 0"
    assert it["status"] == "verified"
    assert it["check_state"] == "checked"
    assert it["answer_state"] == "answered"
    assert it["where"] != ""

    # Task status reflects verified deliverable
    outcome = apply_deliverables({"task_status": "completed"}, assessed)
    assert outcome["task_status"] == "completed"
    assert outcome["deliverables"][0]["status"] == "verified"

    # End-to-end verifier agreement
    report = TribosVerifier().verify_response(q, answer, {})
    assert report.passed is True
    assert report.fully_verified is True
    assert len(report.claims) == 3
    assert all(c.status == "supported" for c in report.claims)


def test_f08_partial_answer_omitted_substitution_check():
    """Partial answer case 1: When required substitution checks are omitted,
    the requested item must NOT be marked checked; it must remain unverified/addressed.
    """
    from tribos.verify.math_claims import audit_answer

    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )
    # Factorization and roots provided, but substitution checks omitted
    answer = (
        "1. Factorization and integer roots:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3"
    )

    audit = audit_answer(answer, query=q)
    assessed = assess(q, answer, math_audit=audit.to_dict())
    assert len(assessed) == 1
    it = assessed[0]
    assert it["status"] == "addressed"
    assert it["check_state"] == "unverified"
    assert it["answer_state"] == "answered"


def test_f08_partial_answer_incomplete_roots():
    """Partial answer case 2: When complete roots are requested but only a subset is provided,
    the item is marked unverified/addressed.
    """
    from tribos.verify.math_claims import audit_answer

    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )
    # Only root x = 2 is provided; x = 3 is missing
    answer = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Integer root: x = 2\n"
        "- Substitution check: 2^2 - 5*2 + 6 = 0"
    )

    audit = audit_answer(answer, query=q)
    assessed = assess(q, answer, math_audit=audit.to_dict())
    assert len(assessed) == 1
    it = assessed[0]
    assert it["status"] == "addressed"
    assert it["check_state"] == "unverified"


def test_f08_contradicted_answer_failing_substitution_check():
    """Contradicted case: When an arithmetic claim in substitution fails,
    the item must be marked 'failed_check' and task status becomes partial.
    """
    from tribos.verify.math_claims import audit_answer

    q = (
        "For integer x, solve x^2 - 5x + 6 = 0. Return exactly one numbered item containing a "
        "factorization, the complete set of integer roots, and a substitution check for each root. "
        "Do not search the web or invoke a formal prover."
    )
    # The substitution check for x = 2 has a false equality: 2^2 - 5*2 + 6 = 1 = 0
    answer = (
        "1. Solution:\n"
        "- Factorization: x^2 - 5*x + 6 = (x - 2)*(x - 3)\n"
        "- Complete set of integer roots: x = 2 and x = 3\n"
        "- Substitution checks:\n"
        "  For x = 2: 2^2 - 5*2 + 6 = 1 = 0\n"
        "  For x = 3: 3^2 - 5*3 + 6 = 0"
    )

    audit = audit_answer(answer, query=q)
    assert any(c.status == "failed" for c in audit.claims)

    assessed = assess(q, answer, math_audit=audit.to_dict())
    assert len(assessed) == 1
    it = assessed[0]
    assert it["status"] == "failed_check"
    assert it["check_state"] == "failed"

    outcome = apply_deliverables({"task_status": "completed"}, assessed)
    assert outcome["task_status"] == "partial"
    assert any("contradict" in r.lower() for r in outcome["incomplete_reasons"])

