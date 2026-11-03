"""Tests for fixes from the Erdős–Straus evaluation audit.

Covers:
- Math checker: scope, domain bounds (n >= 2 not tested at n=1), tuple unpacking, and integer comparisons (x <= y <= z).
- Modular statements and cases: congruences retain scope and do not falsely bind variables.
- Infinite family identities and example triples validate with zero false contradictions.
- Tool verification integrity: unverified tool checks cannot be claimed as passed.
- Run state: complete answer with planner fallback yields 'completed_fallback'.
- Axiom solve: sanitizes malformed variables and normalizes domain strings.
- Project memory: bounds facts per turn and omits transient raw passage snippets.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


from tribos.axiom.engine import axiom_solve
from tribos.axiom.schemas import AxiomSolveInput
from tribos.agentic.project_memory import MAX_FACTS_PER_TURN, extract_facts
from tribos.agents.authoritative_orchestrator import AuthoritativeOrchestrator
from tribos.agents.orchestration.finalize import apply_deliverables
from tribos.agents.query_context import QueryContext
from tribos.tools.registry import ToolResult
from tribos.verify.math_claims import audit_answer
from tribos.verify.verifier import TribosVerifier


def test_erdos_straus_derivation_and_triples_validate_without_false_contradictions():
    md = r"""
### 1. Statement of the Conjecture
The Erdős–Straus conjecture asserts that for all integers $n \ge 2$, the equation
$$\frac{4}{n} = \frac{1}{x} + \frac{1}{y} + \frac{1}{z}$$
has a solution in positive integers $x \le y \le z$.

### 2. Infinite Families
**Even Integers:** For $n \equiv 0 \pmod 2$, we have $n = 2k$ with $k \ge 1$:
$$\frac{4}{2k} = \frac{1}{k} + \frac{1}{2k} + \frac{1}{2k}$$

**Residue Class $n \equiv 3 \pmod 4$:** For $n = 4k + 3$ with $k \ge 0$:
$$\frac{4}{4k+3} = \frac{1}{k+1} + \frac{1}{(k+1)(4k+3)}$$

### 3. Example Triples
- Case $n = 2$: $(x, y, z) = (1, 2, 2)$, $x \le y \le z$, with $\frac{4}{2} = \frac{1}{1} + \frac{1}{2} + \frac{1}{2}$.
- Case $n = 3$: $(x, y, z) = (1, 4, 12)$, $x \le y \le z$, with $\frac{4}{3} = \frac{1}{1} + \frac{1}{4} + \frac{1}{12}$.
- Case $n = 4$: $(x, y, z) = (2, 3, 6)$, $x \le y \le z$, with $\frac{4}{4} = \frac{1}{2} + \frac{1}{3} + \frac{1}{6}$.
- Case $n = 5$: $(x, y, z) = (2, 4, 20)$, $x \le y \le z$, with $\frac{4}{5} = \frac{1}{2} + \frac{1}{4} + \frac{1}{20}$.
- Case $n = 7$: $(x, y, z) = (2, 28, 28)$, $x \le y \le z$, with $\frac{4}{7} = \frac{1}{2} + \frac{1}{28} + \frac{1}{28}$.
"""
    audit = audit_answer(md, query="Erdos-Straus conjecture")
    failed_claims = [c for c in audit.claims if c.status == "failed"]
    assert len(failed_claims) == 0, f"Expected 0 failed claims, got {len(failed_claims)}: {[c.text for c in failed_claims]}"


def test_n_ge_2_not_tested_at_1():
    md = r"""
The condition holds for integers $n \ge 2$:
$$\frac{4}{n} \le 2$$
"""
    audit = audit_answer(md, query="Erdos-Straus bound")
    failed_claims = [c for c in audit.claims if c.status == "failed"]
    assert len(failed_claims) == 0, f"n >= 2 must not be contradicted at n=1: {[c.text for c in failed_claims]}"
    # n >= 2 should be recognized as a valid constraint
    n_claim = next((c for c in audit.claims if "n" in c.text and "ge" in c.text or ">=" in c.text), None)
    assert n_claim is not None
    assert n_claim.status in ("passed", "inconclusive")


def test_tuple_unpacking_and_integer_denominator_ordering():
    md = r"""
For $n = 2$, $(x, y, z) = (1, 2, 2)$ with $x \le y \le z$.
"""
    audit = audit_answer(md, query="integer triple ordering")
    ordering_claim = next((c for c in audit.claims if "x" in c.text and "le" in c.text), None)
    assert ordering_claim is not None
    assert ordering_claim.status == "passed", f"x <= y <= z should pass for (1, 2, 2), got {ordering_claim.status}"


def test_unverified_tool_result_cannot_be_claimed_passed():
    verifier = TribosVerifier()
    tool_results: dict[str, Any] = {
        "axiom_calculus": ToolResult(
            success=False,
            tool_name="axiom_calculus",
            error="mpmath quadrature failed",
            data={"verified": False},
        ),
        "axiom_verify_identity": ToolResult(
            success=True,
            tool_name="axiom_verify_identity",
            data={"verified": True},
        ),
    }
    response_markdown = (
        "We checked both identities. Both checks passed and calculus verification succeeded with axiom_calculus."
    )
    report = verifier.verify_response(
        query="Verify Erdős–Straus identity",
        response_markdown=response_markdown,
        tool_results=tool_results,
    )
    contradicted = [
        d for d in report.defects
        if d.category == "CLAIM_CONTRADICTED" and "unverified or failed" in d.description
    ]
    assert len(contradicted) >= 1, "Verifier must flag defect when unverified tool check is claimed to have passed"


def test_task_outcome_completed_fallback_when_deliverables_met():
    orch = AuthoritativeOrchestrator()
    ctx = QueryContext(raw_query="Erdos-Straus evaluation", clean_query="Erdos-Straus evaluation")
    core_note = "Agent planner hit timeout; fallback pipeline produced answer."
    tool_results: dict[str, ToolResult] = {}
    outcome = orch._task_outcome(ctx, None, tool_results, None, llm_ok=True, core_phase_note=core_note)
    assert outcome.task_status == "completed_fallback"
    assert "fallback" in outcome.reason.lower()

    # Deliverables applied to completed_fallback maintain completed_fallback when all items addressed
    items = [
        {"item": "Identities for even n", "status": "addressed", "quantity": False},
        {"item": "Identities for n = 3 mod 4", "status": "addressed", "quantity": False},
        {"item": "Example triples", "status": "addressed", "quantity": False},
    ]
    status_dict = outcome.model_dump()
    final_status = apply_deliverables(status_dict, items)
    assert final_status["task_status"] == "completed_fallback"


def test_axiom_solve_sanitizes_variables_and_normalizes_domain():
    # Schema validation
    inp = AxiomSolveInput(
        equations="4/2 = 1/x + 1/y + 1/z",
        variables="x, y, z \\in \\mathbb{Z}^+",
        domain="positive_integers",
    )
    assert inp.variables == "x, y, z"
    assert inp.domain == "positive_integer"

    # Engine execution
    res = axiom_solve(
        equations="x^2 - 4 = 0",
        variables="x > 0",
        domain="positive_integers",
    )
    assert res["domain"] == "positive_integer"
    assert res["variables"] == ["x"]
    assert res["verified"] is True
    assert res["solutions"] == [{"x": "2"}]


def test_project_memory_caps_facts_and_omits_raw_search_snippets():
    assert MAX_FACTS_PER_TURN <= 10

    state = SimpleNamespace(
        ctx=SimpleNamespace(primary_display="Erdos-Straus"),
        query="Erdos-Straus conjecture",
        artifacts={},
        tool_results={
            "archivon_literature_search": ToolResult(
                success=True,
                tool_name="archivon_literature_search",
                data={
                    "ranked_passages": [
                        {"passage_text": f"Snippet passage {i} about modular identities"}
                        for i in range(25)
                    ]
                },
            )
        },
    )
    facts = extract_facts(state)
    # Raw passage chunks must not be persisted as project memory facts
    assert len(facts) == 0 or not any("Snippet passage" in f.object for f in facts)
    assert len(facts) <= MAX_FACTS_PER_TURN
