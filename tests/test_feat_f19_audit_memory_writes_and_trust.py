"""
Tests for Feature F19: Audit memory writes and prevent unverified results becoming trusted knowledge.

Covers:
- Strict separation between verified facts and tentative assertions/errors.
- Turns with contradicted or unsupported claims are marked unverified (verified=False).
- Existing verified facts cannot be overwritten or downgraded by later unverified writes.
- Invalidation and rejection: rejected facts are never recalled.
- Recalled prompt blocks clearly warn that unverified facts are leads, never evidence.
"""

from __future__ import annotations

from types import SimpleNamespace

from tribos.agentic.project_memory import _verified, format_memory_block
from tribos.utils.memory.project_store import FactInput, ProjectStore


def test_f19_turn_with_contradicted_or_unsupported_claims_is_unverified():
    # Case 1: Answer passed with unsupported claims -> unverified
    state_unsupported = SimpleNamespace(
        verification={"passed": True, "unsupported_claims": 1, "contradicted_claims": 0, "unchecked_claims": 0}
    )
    assert _verified(state_unsupported) is False

    # Case 2: Answer with contradicted claims -> unverified
    state_contradicted = SimpleNamespace(
        verification={"passed": False, "unsupported_claims": 0, "contradicted_claims": 1, "unchecked_claims": 0}
    )
    assert _verified(state_contradicted) is False

    # Case 3: Fully verified turn without defects -> verified
    state_clean = SimpleNamespace(
        verification={
            "passed": True,
            "fully_verified": True,
            "unsupported_claims": 0,
            "contradicted_claims": 0,
            "unchecked_claims": 0,
        }
    )
    assert _verified(state_clean) is True


def test_f19_unverified_write_cannot_overwrite_verified_provenance(tmp_path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "Collatz Investigation")["id"]

    # Turn 1: Verified mathematical identity
    store.upsert_facts(
        pid,
        "alice",
        [FactInput("T", "cycle_at_1", "1 -> 4 -> 2 -> 1", verified=True, confidence=0.8, source={"run_id": "verified-run"})],
    )

    # Turn 2: Unverified run attempts to update same fact with higher confidence and unverified source
    store.upsert_facts(
        pid,
        "alice",
        [FactInput("T", "cycle_at_1", "1 -> 4 -> 2 -> 1", verified=False, confidence=0.95, source={"run_id": "bad-run"})],
    )

    # The verified fact and its provenance must survive intact
    recalled = store.recall(pid, "alice", "Collatz cycle")[0]
    assert recalled["verified"] is True
    assert recalled["object"] == "1 -> 4 -> 2 -> 1"
    assert recalled["source"]["run_id"] == "verified-run"

    # Turn 3: Single-valued relation cannot be invalidated by an unverified write
    store.upsert_facts(
        pid,
        "alice",
        [FactInput("T", "classification", "verified_loop", verified=True, source={"run_id": "verified-run-2"})],
    )
    store.upsert_facts(
        pid,
        "alice",
        [FactInput("T", "classification", "divergent", verified=False, source={"run_id": "bad-run-2"})],
    )
    recalled_cls = [f for f in store.recall(pid, "alice", "classification") if f["relation"] == "classification"]
    assert any(f["object"] == "verified_loop" and f["verified"] is True for f in recalled_cls)


def test_f19_rejected_or_invalidated_facts_excluded_from_recall(tmp_path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "Math Lab")["id"]

    # Record two facts
    res = store.upsert_facts(
        pid,
        "alice",
        [
            FactInput("P(z)", "symmetry", "P(1-z) = P(z)", verified=True),
            FactInput("P(z)", "zeros_on_line", "Re(z) = 1/2", verified=False),
        ],
    )
    ops = res["ops"]
    bad_fid = next(o["fact_id"] for o in ops if o["object"] == "Re(z) = 1/2")

    # Reject the false conclusion
    store.review_fact(pid, bad_fid, "alice", "reject", "Counterexample found: zeros are 1/3 and 2/3")

    # Only valid non-rejected facts are recalled
    recalled = store.recall(pid, "alice", "P(z)")
    assert len(recalled) == 1
    assert recalled[0]["object"] == "P(1-z) = P(z)"
    assert not any(f["object"] == "Re(z) = 1/2" for f in recalled)


def test_f19_memory_prompt_block_explicitly_labels_unverified_leads():
    project = {"name": "Riemann Investigation"}
    facts = [
        {"subject": "RH", "relation": "status", "object": "unsolved", "value": None, "verified": True, "recorded_at": "2026-10-27"},
        {"subject": "Candidate_Ansatz", "relation": "zero_count", "object": "100%", "value": None, "verified": False, "recorded_at": "2026-10-27"},
    ]
    block = format_memory_block(project, facts)
    assert "[verified" in block
    assert "[unverified" in block
    assert "an unverified fact is a lead to check, never evidence" in block
