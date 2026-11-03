from __future__ import annotations

import time

import pytest
from langchain_core.embeddings import FakeEmbeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tribos.agentic.mem0_adapter import (
    DurableMemoryQueue,
    Mem0Adapter,
    Mem0Provenance,
)


@pytest.fixture
def temp_mem0_dir(tmp_path):
    storage = tmp_path / "mem0_vault"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def fake_mem0_adapter(temp_mem0_dir):
    fake_emb = FakeEmbeddings(size=64)
    fake_llm = FakeListChatModel(responses=["OK"])
    return Mem0Adapter(
        storage_dir=temp_mem0_dir,
        custom_embedder=fake_emb,
        custom_llm=fake_llm,
    )


def test_mem0_sdk_initialization_and_persistent_cycle(fake_mem0_adapter):
    """
    Test persistent add, search, retrieve, update, and delete cycle using the actual mem0 SDK.
    """
    adapter = fake_mem0_adapter
    user_id = "user_alice"
    project_id = "prj_alpha"

    prov = Mem0Provenance(
        memory_type="user_preference",
        origin="user_prompt",
        verification_status="verified",
    )
    # 1. Add
    res = adapter.add(
        content="In project A, use SI units.",
        user_id=user_id,
        project_id=project_id,
        provenance=prov,
        infer=False,
    )
    assert "results" in res or "id" in res
    results = res.get("results", [res])
    memory_id = results[0]["id"]
    assert memory_id

    # 2. Retrieve / Get
    mem_item = adapter.get(memory_id, user_id=user_id, project_id=project_id)
    assert mem_item is not None
    assert "SI units" in (mem_item.get("memory") or str(mem_item))

    # 3. Search
    found = adapter.search(query="units", user_id=user_id, project_id=project_id)
    assert len(found) >= 1
    assert any(m["id"] == memory_id for m in found)

    # 4. Update
    adapter.update(
        memory_id, "In project A, always use standard SI units with full precision.",
        user_id=user_id, project_id=project_id,
    )
    updated_item = adapter.get(memory_id, user_id=user_id, project_id=project_id)
    assert "standard SI units" in (updated_item.get("memory") or str(updated_item))

    # 5. Delete
    deleted = adapter.delete(memory_id, user_id=user_id, project_id=project_id)
    assert deleted is True

    # Confirm deletion
    after_delete = adapter.get(memory_id, user_id=user_id, project_id=project_id)
    assert after_delete is None


def test_mem0_user_and_project_isolation(fake_mem0_adapter):
    """
    Strict isolation: User A cannot see User B's memories; Project A cannot see Project B's memories.
    Direct access to another user or project's memory ID raises PermissionError.
    """
    adapter = fake_mem0_adapter

    # User Alice in Project Alpha
    res_a = adapter.add(
        content="Alpha confidential parameter: clearance=4",
        user_id="user_alice",
        project_id="prj_alpha",
        infer=False,
    )
    mid_a = res_a.get("results", [res_a])[0]["id"]

    # User Bob in Project Beta
    res_b = adapter.add(
        content="Beta confidential parameter: clearance=9",
        user_id="user_bob",
        project_id="prj_beta",
        infer=False,
    )
    mid_b = res_b.get("results", [res_b])[0]["id"]

    # Alice searches for 'clearance' in Project Alpha: should only see Alpha
    alice_results = adapter.search("clearance", user_id="user_alice", project_id="prj_alpha")
    assert len(alice_results) == 1
    assert "Alpha" in alice_results[0]["memory"]
    assert "Beta" not in alice_results[0]["memory"]

    # Alice attempts to search Project Beta: returns empty
    alice_beta_results = adapter.search("clearance", user_id="user_alice", project_id="prj_beta")
    assert len(alice_beta_results) == 0

    # Bob searches for 'clearance' in Project Beta: should only see Beta
    bob_results = adapter.search("clearance", user_id="user_bob", project_id="prj_beta")
    assert len(bob_results) == 1
    assert "Beta" in bob_results[0]["memory"]
    assert "Alpha" not in bob_results[0]["memory"]

    # Cross-user get attempt raises PermissionError
    with pytest.raises(PermissionError):
        adapter.get(mid_b, user_id="user_alice", project_id="prj_alpha")

    # Cross-project get attempt raises PermissionError
    with pytest.raises(PermissionError):
        adapter.get(mid_a, user_id="user_alice", project_id="prj_beta")

    # Cross-user delete attempt raises PermissionError
    with pytest.raises(PermissionError):
        adapter.delete(mid_b, user_id="user_alice", project_id="prj_alpha")


def test_mem0_provenance_and_authoritative_invalidation(fake_mem0_adapter):
    """
    Provenance tracking and authoritative invalidation filtering from search and get.
    """
    adapter = fake_mem0_adapter
    prov = Mem0Provenance(
        memory_type="validated_result",
        origin="rk4_oscillator",
        source_task_id="task_ode_12",
        source_run_id="run_99",
        verification_status="verified",
        artifact_references=["oscillator_trajectory.csv", "figure_1.png"],
    )
    res = adapter.add(
        content="Oscillator steady state endpoint x=-0.026613 m.",
        user_id="user_c",
        project_id="prj_gamma",
        provenance=prov,
        infer=False,
    )
    results = res.get("results", [res])
    mid = results[0]["id"]

    # Initial search returns it
    active_search = adapter.search("Oscillator", user_id="user_c", project_id="prj_gamma")
    assert any(m["id"] == mid for m in active_search)

    # Invalidate memory with reason
    inv_res = adapter.invalidate(
        mid,
        reason="New analytical benchmark superseded initial tolerance.",
        user_id="user_c",
        project_id="prj_gamma",
    )
    assert inv_res["status"] == "invalidated"
    assert "superseded" in inv_res["invalidation_reason"]

    # Active search MUST filter out invalidated memories
    filtered_search = adapter.search("Oscillator", user_id="user_c", project_id="prj_gamma", include_invalid=False)
    assert not any(m["id"] == mid for m in filtered_search)

    # Active get returns None
    assert adapter.get(mid, user_id="user_c", project_id="prj_gamma", include_invalid=False) is None

    # Explicit include_invalid=True retrieves it with invalidation metadata
    inv_item = adapter.get(mid, user_id="user_c", project_id="prj_gamma", include_invalid=True)
    assert inv_item is not None
    assert inv_item.get("companion_status") == "invalidated"
    assert "superseded" in inv_item.get("invalidation_reason", "")


def test_durable_memory_queue_and_outage_recovery(fake_mem0_adapter, temp_mem0_dir):
    """
    Durable background queue survives Mem0 outage, retries automatically,
    deduplicates identical pending events, enforces operation validation,
    and supports atomic leases and background dispatching.
    """
    adapter = fake_mem0_adapter
    q_db = temp_mem0_dir / "events.db"
    queue = DurableMemoryQueue(q_db, adapter)

    # 1. Reject invalid operations
    with pytest.raises(ValueError):
        queue.enqueue(
            user_id="user_d",
            project_id="prj_delta",
            operation="unsupported_op",
            payload={"content": "test"},
        )

    # 2. Enqueue event while adapter is available
    ev_id1 = queue.enqueue(
        user_id="user_d",
        project_id="prj_delta",
        operation="add",
        payload={"content": "Project constraint: max temperature 120 C", "infer": False},
    )
    assert ev_id1.startswith("ev_")

    # Duplicate enqueue with same content is deduplicated (idempotent)
    ev_id1_dup = queue.enqueue(
        user_id="user_d",
        project_id="prj_delta",
        operation="add",
        payload={"content": "Project constraint: max temperature 120 C", "infer": False},
    )
    assert ev_id1 == ev_id1_dup

    # Process queue -> should be delivered
    count = queue.process_pending()
    assert count == 1
    events = queue.list_events("user_d", "prj_delta")
    assert len(events) == 1
    assert events[0]["state"] == "delivered"

    # 3. Simulate Mem0 Outage
    adapter.set_available(False)

    ev_id2 = queue.enqueue(
        user_id="user_d",
        project_id="prj_delta",
        operation="add",
        payload={"content": "Second constraint: max pressure 10 bar", "infer": False},
    )

    # Process during outage: does NOT crash caller, event remains pending with retry delay
    failed_count = queue.process_pending()
    assert failed_count == 0
    ev2_record = next(e for e in queue.list_events("user_d", "prj_delta") if e["event_id"] == ev_id2)
    assert ev2_record["state"] == "pending"
    assert ev2_record["attempts"] >= 1

    # 4. Restore Mem0 availability and recover
    adapter.set_available(True)
    import sqlite3
    with sqlite3.connect(str(q_db)) as conn:
        conn.execute("UPDATE memory_events SET next_retry_at = 0 WHERE event_id = ?", (ev_id2,))

    recovered_count = queue.process_pending()
    assert recovered_count == 1
    ev2_recovered = next(e for e in queue.list_events("user_d", "prj_delta") if e["event_id"] == ev_id2)
    assert ev2_recovered["state"] == "delivered"

    # 5. Background dispatcher lifecycle test
    queue.start_background_dispatcher(interval_s=0.05)
    ev_id3 = queue.enqueue(
        user_id="user_d",
        project_id="prj_delta",
        operation="add",
        payload={"content": "Third constraint: voltage 24V", "infer": False},
    )
    time.sleep(0.3)
    ev3_record = next(e for e in queue.list_events("user_d", "prj_delta") if e["event_id"] == ev_id3)
    assert ev3_record["state"] == "delivered"
    queue.stop_background_dispatcher()


async def _noop_emit(*_a, **_k):
    return None

async def _noop_send(_ev):
    return None

@pytest.mark.asyncio
async def test_consolidation_and_recall_phases_with_mem0(fake_mem0_adapter, monkeypatch):
    """
    Direct verification of Section 1:
    Run the actual consolidation phase and demonstrate that it creates a durable event,
    delivers it to Mem0, and recalls the memory in a new session within the same project.
    """
    from types import SimpleNamespace

    import tribos.agentic.mem0_adapter as mem0_mod
    from tribos.agentic.budget import RunBudget
    from tribos.agentic.control import RunControl
    from tribos.agentic.llm import AgentLLM
    from tribos.agentic.project_memory import ProjectConsolidatePhase, ProjectRecallPhase
    from tribos.agentic.state import AgentState
    from tribos.tools.registry import ToolResult
    from tribos.utils.memory.project_store import get_project_store

    # Patch get_mem0_adapter and get_memory_queue to use test fixture
    monkeypatch.setattr(mem0_mod, "get_mem0_adapter", lambda: fake_mem0_adapter)
    q = DurableMemoryQueue(db_path=fake_mem0_adapter.storage_dir / 'events.db', adapter=fake_mem0_adapter)
    monkeypatch.setattr(mem0_mod, "get_memory_queue", lambda: q)
# Patched via mem0_mod

    store = get_project_store()
    user_id = "user_e2e"
    project_id = store.create_project(user_id, "Project E2E")["id"]

    # 1. State with a scientific result
    ctx = SimpleNamespace(
        scope="research", genes=[], drugs=[], diseases=[], variants=[], entities=[], attachments=[],
        primary_target="oscillator", primary_symbol="oscillator", biomodel_id=None,
        model_attachment=None, is_simulation_intent=False,
    )
    budget = RunBudget.from_env(None)
    tool_res = ToolResult(
        success=True,
        tool_name="physis_constants",
        data={"constants": [{"name": "damping_ratio", "value": 0.15, "unit": "dimensionless"}]},
    )


    state = AgentState(
        query="What is the damping ratio for the oscillator?",
        clean_query="What is the damping ratio for the oscillator?",
        ctx=ctx,
        registry=None,
        user_id=user_id,
        project_id=project_id,
        thread_id="t_session_1",
        model_name="m",
        api_key=None,
        framework="agentic",
        budget=budget,
        control=RunControl(user_id, interactive=False),
        llm=AgentLLM(None, "m", None, budget),
        tool_results={"physis_constants": tool_res},
        emit=_noop_emit,
        send=_noop_send,
    )
    state.verification = {"passed": True}

    # Run consolidation phase
    consolidate_phase = ProjectConsolidatePhase()
    assert consolidate_phase.applies(state) is True
    await consolidate_phase.run(state)

    # Verify durable event enqueued and delivered
    mem0_status = state.artifacts["project_memory"]["mem0_status"]
    assert mem0_status["enqueued"] >= 1
    assert mem0_status["delivered"] >= 1
    assert mem0_status["error"] is None

    # Verify durable event record in queue
    events = q.list_events(user_id, project_id)
    assert len(events) >= 1
    assert any(e["state"] == "delivered" for e in events)

    # 2. Fresh session in the same project -> recall
    ctx2 = SimpleNamespace(
        scope="research", genes=[], drugs=[], diseases=[], variants=[],
        entities=[SimpleNamespace(label="damping_ratio", mention="damping")],
        attachments=[], primary_target="oscillator", primary_symbol="oscillator",
        biomodel_id=None, model_attachment=None, is_simulation_intent=False,
    )
    state_session2 = AgentState(
        query="Recall the damping ratio for this project.",
        clean_query="Recall the damping ratio for this project.",
        ctx=ctx2,
        registry=None,
        user_id=user_id,
        project_id=project_id,
        thread_id="t_session_2",  # New session
        model_name="m",
        api_key=None,
        framework="agentic",
        budget=budget,
        control=RunControl(user_id, interactive=False),
        llm=AgentLLM(None, "m", None, budget),
        tool_results={},
        emit=_noop_emit,
        send=_noop_send,
    )

    recall_phase = ProjectRecallPhase()
    assert recall_phase.applies(state_session2) is True
    await recall_phase.run(state_session2)

    # Verify recall in session 2 contains recalled facts
    assert "damping" in state_session2.project_memory
    assert len(state_session2.artifacts["project_memory"]["recalled"]) >= 1

    # 3. Stranger / different user isolation check
    state_stranger = AgentState(
        query="Recall damping",
        clean_query="Recall damping",
        ctx=ctx2,
        registry=None,
        user_id="user_stranger",
        project_id=project_id,
        thread_id="t_session_stranger",
        model_name="m",
        api_key=None,
        framework="agentic",
        budget=budget,
        control=RunControl("user_stranger", interactive=False),
        llm=AgentLLM(None, "m", None, budget),
        tool_results={},
        emit=_noop_emit,
        send=_noop_send,
    )
    await recall_phase.run(state_stranger)
    assert state_stranger.project_memory == ""  # Zero recalled for stranger
