"""
Tests for Feature F20: Protect saved conversations under quota and write failures.

Covers:
- Backend persistence of run manifests via RunStore: atomic writes, isolation, and recovery.
- Simulated disk full / quota write failure cleans up temporary files without corrupting existing records.
- RunStore retention and fair eviction: user quotas are respected without corrupting canonical history.
- Multi-user isolation: user A's write operations or pruning never delete or overwrite user B's records.
- ProjectStore transactional integrity: SQLite atomic commits prevent half-committed facts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tribos.provenance.run_store import RunStore, RunStoreError
from tribos.utils.memory.project_store import FactInput, ProjectStore


def test_f20_run_store_atomic_save_and_recovery(tmp_path: Path):
    store = RunStore(tmp_path)
    user_id = "test_user_01"
    run_id = "a" * 32
    manifest = {"run_id": run_id, "task": "Prove Collatz conjecture", "status": "completed"}

    # Successful atomic save
    saved_path = store.save(user_id, manifest, response="Proof investigation complete.")
    assert saved_path.is_file()

    # Load returns stored manifest without internal response text
    loaded = store.load(user_id, run_id)
    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["task"] == "Prove Collatz conjecture"
    assert "_response_text" not in loaded

    # Response is loaded cleanly via dedicated accessor
    loaded_resp = store.load_response(user_id, run_id)
    assert loaded_resp == "Proof investigation complete."


def test_f20_run_store_failed_write_cleans_up_and_preserves_existing(tmp_path: Path):
    store = RunStore(tmp_path)
    user_id = "test_user_02"
    run_id_1 = "1" * 32
    run_id_2 = "2" * 32

    # Save run 1 successfully
    store.save(user_id, {"run_id": run_id_1, "answer": "Original answer"}, response="Canonical text 1")

    # Inject failure during save of run 2 (e.g. disk quota exhaustion or permission error)
    with patch("json.dump", side_effect=OSError("Disk quota exceeded (ENOSPC)")):
        with pytest.raises(OSError, match="Disk quota"):
            store.save(user_id, {"run_id": run_id_2, "answer": "Failed answer"})

    # Verify no dangling temporary files remain in the user's directory
    user_dir = tmp_path / user_id
    tmp_files = list(user_dir.glob(".tmp-*"))
    assert len(tmp_files) == 0, f"Found leaked temp files: {tmp_files}"

    # Verify existing run 1 was not corrupted or deleted
    intact = store.load(user_id, run_id_1)
    assert intact is not None
    assert intact["answer"] == "Original answer"
    assert store.load_response(user_id, run_id_1) == "Canonical text 1"


def test_f20_run_store_prune_fairness_and_user_isolation(tmp_path: Path):
    store = RunStore(tmp_path)
    user_a = "alice"
    user_b = "bob"

    # Alice creates 5 runs
    for i in range(5):
        rid = f"a{i:031x}"
        store.save(user_a, {"run_id": rid, "index": i})

    # Bob creates 2 runs
    for i in range(2):
        rid = f"b{i:031x}"
        store.save(user_b, {"run_id": rid, "index": i})

    # Prune with per-user limit of 3
    pruned_count = store.prune(keep=10, keep_per_user=3)
    assert pruned_count == 2  # Alice had 5 -> trimmed 2 oldest

    # Alice still has 3 newest runs
    alice_runs = [store.load(user_a, f"a{i:031x}") for i in range(5)]
    alice_surviving = [r for r in alice_runs if r is not None]
    assert len(alice_surviving) == 3

    # Bob still has both runs intact (Bob was not pruned)
    bob_runs = [store.load(user_b, f"b{i:031x}") for i in range(2)]
    bob_surviving = [r for r in bob_runs if r is not None]
    assert len(bob_surviving) == 2


def test_f20_run_store_invalid_user_or_run_id_rejected():
    store = RunStore()
    # load returns None on invalid run id or invalid user id
    assert store.load("alice", "not-a-valid-run-id") is None
    assert store.load("../../../etc/passwd", "a" * 32) is None

    # save strictly rejects invalid run id or user id with RunStoreError
    with pytest.raises(RunStoreError, match="invalid run id"):
        store.save("alice", {"run_id": "not-a-valid-run-id"})

    with pytest.raises(RunStoreError, match="invalid user id"):
        store.save("../../../etc/passwd", {"run_id": "a" * 32})


def test_f20_project_store_transactional_durability(tmp_path: Path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "Durability Lab")["id"]

    # Initial valid fact
    store.upsert_facts(pid, "alice", [FactInput("X", "property", "P1", value="1.0", verified=True)])
    recalled_1 = store.recall(pid, "alice", "X")
    assert len(recalled_1) == 1
    assert recalled_1[0]["value"] == "1.0"

    # Verify that invalid facts (missing fields) are rejected before database alteration
    res = store.upsert_facts(pid, "alice", [FactInput("", "", "")])
    assert res["written"] == 0
    assert res["invalidated"] == 0

    # Stored knowledge remains fully intact
    recalled_2 = store.recall(pid, "alice", "X")
    assert len(recalled_2) == 1
    assert recalled_2[0]["value"] == "1.0"
