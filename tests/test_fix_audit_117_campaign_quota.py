"""AUDIT-117: a per-user quota on queued + running research projects (TRIBOS_CAMPAIGN_MAX_PER_USER, default 3).

Projects run one at a time per process (TRIBOS_CAMPAIGN_MAX_ACTIVE) and each one holds hours of model and sandbox
time, so without a per-user cap one user could fill the research queue for everyone. Submitting, resuming or
continuing a project past the cap is refused with 429 before anything is written; another user is unaffected, and
finished, failed, cancelled, interrupted or stale (owner process gone) projects do not count."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from tribos.agentic import campaign as cmod
from tribos.agentic import jobs as jobs_mod

DEAD_OWNER = "999999:1.0"


def _result(text: str) -> dict[str, Any]:
    return {"response": text, "thread_id": "t", "task_status": {"task_status": "completed"}, "citations": {}}


async def fake_writer(system: str, user: str, model: str | None) -> str:
    return "# Report\n\nWritten from the stages."


def _gated_runner(gate: dict[str, bool]):
    """A stage job that holds its project in "running" until the test opens the gate (or the job is cancelled)."""

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        while not gate["open"]:
            if run_control.cancelled:
                return {**_result("stopped"), "task_status": {"task_status": "cancelled"}}
            await asyncio.sleep(0.01)
        return _result("ok")

    return runner


def _manager(tmp_path, runner) -> cmod.CampaignManager:
    jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=2)
    m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
    m.report_writer = fake_writer
    return m


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("TRIBOS_CAMPAIGN_MAX_PER_USER", raising=False)  # the default, 3
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_ACTIVE", "1")
    monkeypatch.setattr(cmod, "_POLL_S", 0.05)


async def _settle(m: cmod.CampaignManager, ids: list[str], timeout: float = 20.0) -> dict[str, dict[str, Any]]:
    """Wait until none of these projects is queued or running; returns their final records."""
    deadline = time.monotonic() + timeout
    while True:
        rows = {cid: m.store.get(cid) for cid in ids}
        if all(r["status"] not in cmod.RUNNING for r in rows.values()):
            return rows
        assert time.monotonic() < deadline, {cid: r["status"] for cid, r in rows.items()}
        await asyncio.sleep(0.02)


def _finished(m: cmod.CampaignManager, user_id: str, goal: str, status: str, **extra: Any) -> dict[str, Any]:
    """A stored project that already stopped with `status` (no driver, no owner)."""
    c = m.create(user_id, goal, stages=["review"])
    c.update(status=status, owner=None, finished_at=time.time(), **extra)
    m.store.save(c)
    return c


def test_the_setting_defaults_to_three_and_is_clamped(monkeypatch):
    assert cmod._max_per_user() == 3
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_PER_USER", "0")
    assert cmod._max_per_user() == 1
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_PER_USER", "500")
    assert cmod._max_per_user() == 50
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_PER_USER", "7")
    assert cmod._max_per_user() == 7


def test_the_fourth_project_of_one_user_is_refused_before_anything_is_written(tmp_path):
    gate = {"open": False}

    async def go():
        m = _manager(tmp_path, _gated_runner(gate))
        mine = [(await m.submit("alice", f"Study {i}", stages=["review"]))["campaign_id"] for i in range(3)]
        assert m.active_count("alice") == 3  # one running, two queued behind it
        stored = sorted(m.store.all_ids())
        with pytest.raises(jobs_mod.JobError) as refused:
            await m.submit("alice", "Study 4", stages=["review"])
        assert sorted(m.store.all_ids()) == stored  # nothing was written for the refused project
        assert len(m.list("alice")) == 3
        bob = await m.submit("bob", "Bob's study", stages=["review"])  # alice's quota is hers alone
        assert bob["status"] == "queued" and m.active_count("bob") == 1
        gate["open"] = True
        final = await _settle(m, [*mine, bob["campaign_id"]])
        # Finished projects free their places: alice can queue three more.
        assert m.active_count("alice") == 0
        more = [(await m.submit("alice", f"Next {i}", stages=["review"]))["campaign_id"] for i in range(3)]
        await _settle(m, more)
        return refused.value, final

    refused, final = asyncio.run(go())
    assert refused.status_code == 429
    assert "3 research projects queued or running" in str(refused)
    assert all(r["status"] == "succeeded" for r in final.values())


def test_finished_cancelled_and_stale_projects_do_not_count(tmp_path):
    gate = {"open": False}

    async def go():
        m = _manager(tmp_path, _gated_runner(gate))
        for status in ("succeeded", "failed", "cancelled", "interrupted"):
            _finished(m, "alice", f"Earlier project that {status}", status)
        # Left "running" by a server process that is gone: it holds no slot.
        stale = m.create("alice", "Left behind by a crashed server", stages=["review"])
        stale.update(status="running", owner=DEAD_OWNER)
        m.store.save(stale)
        assert m.active_count("alice") == 0
        live = [(await m.submit("alice", f"Live {i}", stages=["review"]))["campaign_id"] for i in range(3)]
        with pytest.raises(jobs_mod.JobError) as refused:
            await m.submit("alice", "One too many", stages=["review"])
        # Cancelling a queued project frees its place at once.
        cancelled = await m.cancel(live[2], "alice")
        assert cancelled["status"] == "cancelled" and m.active_count("alice") == 2
        again = await m.submit("alice", "After a cancel", stages=["review"])
        gate["open"] = True
        final = await _settle(m, [*live, again["campaign_id"]])
        return refused.value, final, live

    refused, final, live = asyncio.run(go())
    assert refused.status_code == 429
    assert final[live[2]]["status"] == "cancelled"
    assert sum(r["status"] == "succeeded" for r in final.values()) == 3


def test_resume_and_continue_are_refused_at_the_quota_without_touching_the_project(tmp_path):
    gate = {"open": False}

    async def go():
        m = _manager(tmp_path, _gated_runner(gate))
        stopped = _finished(m, "alice", "A project the user cancelled", "cancelled", error="cancelled by the user")
        done = _finished(m, "alice", "A finished project", "succeeded")
        done["stages"][0].update(status="succeeded", response="REVIEW")
        m.store.save(done)
        loop = _finished(m, "alice", "A finished research-loop project", "succeeded", mode="loop",
                         charter={"tests": [{"id": "T1", "status": "done"}]}, loop={"phase": "done"})
        before = {c["campaign_id"]: m.store.get(c["campaign_id"]) for c in (stopped, done, loop)}
        live = [(await m.submit("alice", f"Live {i}", stages=["review"]))["campaign_id"] for i in range(3)]
        errors = []
        for call in (lambda: m.resume(stopped["campaign_id"], "alice"),
                     lambda: m.continue_(done["campaign_id"], "alice", "Push the computation further"),
                     lambda: m.continue_(loop["campaign_id"], "alice", "Also check the n = 7 case")):
            with pytest.raises(jobs_mod.JobError) as refused:
                await call()
            errors.append(refused.value)
        after = {cid: m.store.get(cid) for cid in before}
        # Once one of the live projects stops, the cancelled one can be resumed.
        await m.cancel(live[0], "alice")
        resumed = await m.resume(stopped["campaign_id"], "alice")
        gate["open"] = True
        final = await _settle(m, [*live, stopped["campaign_id"]])
        return errors, before, after, resumed, final

    errors, before, after, resumed, final = asyncio.run(go())
    assert [e.status_code for e in errors] == [429, 429, 429]
    assert after == before  # the refused resume / continue wrote nothing
    assert resumed["status"] == "queued"
    assert final[resumed["campaign_id"]]["status"] == "succeeded"


def test_a_lower_limit_from_the_setting_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_PER_USER", "1")
    gate = {"open": False}

    async def go():
        m = _manager(tmp_path, _gated_runner(gate))
        first = await m.submit("alice", "Only one at a time", stages=["review"])
        with pytest.raises(jobs_mod.JobError) as refused:
            await m.submit("alice", "A second one", stages=["review"])
        gate["open"] = True
        await _settle(m, [first["campaign_id"]])
        return refused.value

    refused = asyncio.run(go())
    assert refused.status_code == 429 and "1 research project queued" in str(refused)


def test_the_api_answers_429_for_the_fourth_project_and_other_users_are_unaffected(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main

    gate = {"open": False}
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=_gated_runner(gate), workers=2)
    jobs_mod.set_job_manager(jm)
    manager = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
    manager.report_writer = fake_writer
    cmod.set_campaign_manager(manager)
    alice, bob = {"Authorization": "Bearer alice-token"}, {"Authorization": "Bearer bob-token"}

    def post(goal: str, headers: dict[str, str]):
        return api.post("/api/campaigns", json={"goal": goal, "stages": ["review"]}, headers=headers)

    try:
        with TestClient(backend_main.app) as api:
            ids = []
            for i in range(3):
                r = post(f"Alice study {i}", alice)
                assert r.status_code == 201, r.text
                ids.append(r.json()["campaign_id"])
            r = post("Alice study 4", alice)
            assert r.status_code == 429, r.text
            assert "3 research projects queued or running" in r.json()["detail"]
            assert len(api.get("/api/campaigns", headers=alice).json()["campaigns"]) == 3
            r = post("Bob study", bob)
            assert r.status_code == 201, r.text
            ids.append(r.json()["campaign_id"])
            # Cancelling one frees a place for alice.
            assert api.post(f"/api/campaigns/{ids[2]}/cancel", headers=alice).json()["status"] == "cancelled"
            r = post("Alice study 5", alice)
            assert r.status_code == 201, r.text
            ids.append(r.json()["campaign_id"])
            gate["open"] = True
            deadline = time.time() + 20
            while any(manager.store.get(cid)["status"] in cmod.RUNNING for cid in ids):
                assert time.time() < deadline
                time.sleep(0.05)
    finally:
        gate["open"] = True
        jobs_mod.set_job_manager(None)
        cmod.set_campaign_manager(None)
