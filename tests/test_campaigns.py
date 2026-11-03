"""Long-running research projects (tribos.agentic.campaign): stages run as jobs, carry earlier stages forward,
resume at the first unfinished stage, survive a restart as interrupted, and produce a Markdown report."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from tribos.agentic import campaign as cmod
from tribos.agentic import jobs as jobs_mod

CITE = {"entries": {"DOI:10.1/x": {"key": "DOI:10.1/x", "title": "A paper", "url": "https://doi.org/10.1/x",
                                   "year": "2024"}}}


def _result(text: str) -> dict[str, Any]:
    return {"response": text, "thread_id": "t", "task_status": {"task_status": "completed"}, "citations": CITE}


REPORTS: list[tuple[str, str]] = []


async def fake_writer(system: str, user: str, model: str | None) -> str:
    REPORTS.append((system, user))
    return f"# Report {len(REPORTS)}\n\nWritten from the stages."


def _manager(tmp_path, runner) -> cmod.CampaignManager:
    jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=1)
    m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
    m.report_writer = fake_writer
    return m


async def _finish(m: cmod.CampaignManager, cid: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        c = m.store.get(cid)
        if c["status"] not in cmod.RUNNING or time.monotonic() > deadline:
            return c
        await asyncio.sleep(0.02)


def test_stages_run_in_order_and_each_sees_the_earlier_ones(tmp_path):
    seen: list[dict[str, Any]] = []
    REPORTS.clear()

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        seen.append(request)
        n = len(seen)
        return _result(f"STAGE{n} finding: value {n * 7}")

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "Is the Collatz stopping time bounded for n < 10^6? Explore numerically.")
        return m, await _finish(m, c["campaign_id"])

    m, c = asyncio.run(go())
    assert c["status"] == "succeeded" and [s["status"] for s in c["stages"]] == ["succeeded"] * 5
    assert len(seen) == 4  # review, hypotheses, experiments, analysis run as research jobs; the report is written
    # each stage in its own thread, so one stage's remembered subject never leaks into the next
    assert [r["thread_id"] for r in seen] == [f"{c['thread_id']}__{k}" for k in ("review", "hypotheses", "experiments", "analysis")]
    assert seen[2]["agent_options"]["codeact"] == "always" and "codeact" not in seen[1]["agent_options"]
    assert "Stage 1" in seen[0]["message"] and "Research goal: Is the Collatz" in seen[0]["message"]
    # Earlier stages travel as background context, never inside the question the parsers read.
    assert "STAGE1 finding" not in seen[1]["message"]
    assert "STAGE1 finding" in seen[1]["agent_options"]["research_context"]
    assert "STAGE3 finding" in seen[3]["agent_options"]["research_context"]
    assert seen[0]["agent_options"] == {"effort_level": "high", "allow_clarification": False, "research_context": ""}
    assert all("simulat" not in r["message"].split("Research goal:")[0].lower() for r in seen)
    system, user = REPORTS[0]
    assert "Abstract" in system and "STAGE4 finding" in user and "[1] A paper https://doi.org/10.1/x" in user
    report = cmod.report_markdown(c)
    assert report.index("# Report 1") < report.index("## Appendix") < report.index("STAGE1")
    assert "1. [A paper](https://doi.org/10.1/x). 2024" in report and report.count("A paper") == 1


def test_a_clarifying_question_is_not_accepted_as_a_stage_result(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_STAGE_RETRIES", "1")
    replies = iter(["Which dynamical system should I simulate?\n\n1. Lorenz\n\nReply with a number.",
                    "The review: Terras proved almost all n drop below n."])

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        return _result(next(replies))

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "Collatz", stages=["review"])
        return await _finish(m, c["campaign_id"])

    c = asyncio.run(go())
    assert c["status"] == "succeeded" and c["stages"][0]["attempts"] == 2
    assert c["stages"][0]["response"].startswith("The review")
    assert cmod.looks_like_question("Could you clarify which dataset?")
    assert not cmod.looks_like_question("Terras (1976) proved that almost all n have finite stopping time.")


def test_a_failed_stage_stops_and_resume_reruns_only_unfinished_stages(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_STAGE_RETRIES", "0")
    calls: list[str] = []
    fail = {"on": True}

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        stage = request["message"].split(":", 1)[0]
        calls.append(stage)
        if "Stage 3" in stage and fail["on"]:
            raise RuntimeError("sandbox down")
        return _result(f"done {stage}")

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "Test a conjecture about prime gaps")
        first = await _finish(m, c["campaign_id"])
        fail["on"] = False
        await m.resume(c["campaign_id"], "alice")
        return first, await _finish(m, c["campaign_id"])

    first, final = asyncio.run(go())
    assert first["status"] == "failed" and first["error"].startswith("Experiments:")
    assert [s["status"] for s in first["stages"]] == ["succeeded", "succeeded", "failed", "pending", "pending"]
    assert final["status"] == "succeeded"
    assert calls.count("Stage 1 of 5 of a research project") == 1 and calls.count("Stage 3 of 5 of a research project") == 2


def test_cancel_stops_the_running_stage_job(tmp_path):
    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        while not run_control.cancelled:
            await asyncio.sleep(0.01)
        return {**_result("stopped"), "task_status": {"task_status": "cancelled"}}

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "Long study")
        for _ in range(200):
            if m.store.get(c["campaign_id"])["stages"][0]["job_id"]:
                break
            await asyncio.sleep(0.01)
        out = await m.cancel(c["campaign_id"], "alice")
        job = m.jobs.store.get(out["stages"][0]["job_id"])
        await asyncio.sleep(0.1)
        return out, m.jobs.store.get(job["job_id"])

    out, job = asyncio.run(go())
    assert out["status"] == "cancelled" and out["stages"][0]["status"] == "cancelled"
    assert job["status"] in ("cancelled", "running")  # the job stops within its cancel grace


def test_restart_marks_running_projects_interrupted(tmp_path):
    store = cmod.CampaignStore(str(tmp_path / "campaigns"))
    m = cmod.CampaignManager(store)
    c = m.create("alice", "goal")
    live = m.create("alice", "driven by this live process")
    c["status"], c["stages"][0]["status"], c["owner"] = "running", "running", DEAD_OWNER
    live["status"] = "running"
    store.save(c)
    store.save(live)
    again = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")))
    got = again.get(c["campaign_id"], "alice")
    assert again.recovered == 1 and got["status"] == "interrupted" and got["stages"][0]["status"] == "interrupted"
    assert again.get(live["campaign_id"], "alice")["status"] == "running"  # its owner is alive: left alone
    assert again.get(c["campaign_id"], "bob") is None


DEAD_OWNER = "999999:1.0"


def test_a_failed_stage_is_retried_automatically(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_STAGE_RETRIES", "1")
    attempts = {"n": 0}

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        if "Stage 2" in request["message"]:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("flaky tool")
        return _result("ok")

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "goal", stages=["review", "hypotheses"])
        return await _finish(m, c["campaign_id"])

    c = asyncio.run(go())
    assert c["status"] == "succeeded" and c["stages"][1]["attempts"] == 2 and c["stages"][1]["error"] is None


def test_projects_queue_and_start_when_a_slot_frees(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_MAX_ACTIVE", "1")
    monkeypatch.setattr(cmod, "_POLL_S", 0.05)
    gate = {"open": False}
    order: list[str] = []

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        order.append(request["message"].rsplit("Research goal: ", 1)[1].split("\n", 1)[0])
        while not gate["open"]:
            await asyncio.sleep(0.01)
        return _result("ok")

    async def go():
        jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=2)
        m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
        a = await m.submit("alice", "first", stages=["review"])
        b = await m.submit("alice", "second", stages=["review"])
        await asyncio.sleep(0.4)
        waiting = m.store.get(b["campaign_id"])
        gate["open"] = True
        return waiting, await _finish(m, a["campaign_id"]), await _finish(m, b["campaign_id"])

    waiting, a, b = asyncio.run(go())
    assert waiting["status"] == "queued" and waiting["note"].startswith("Queued")
    assert a["status"] == b["status"] == "succeeded" and order == ["first", "second"]
    assert b["note"] is None


def test_interrupted_projects_resume_automatically_at_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_AUTO_RESUME", "1")
    seen: list[str] = []

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        seen.append(request["message"].split(":", 1)[0])
        return _result("done")

    store = cmod.CampaignStore(str(tmp_path / "campaigns"))
    creator = cmod.CampaignManager(store)  # the "previous process"
    c = creator.create("alice", "goal", stages=["review", "hypotheses"])
    c["stages"][0].update(status="succeeded", response="REVIEW TEXT")
    c["stages"][1]["status"] = "running"
    c.update(status="running", owner=DEAD_OWNER)
    store.save(c)
    capped = creator.create("alice", "crashes the server", stages=["review"])
    capped.update(status="running", owner=DEAD_OWNER, auto_resumes=cmod.MAX_AUTO_RESUMES)
    store.save(capped)

    async def go():
        m = _manager(tmp_path, runner)  # a fresh process: marks both interrupted
        resumed = m.autostart()
        return resumed, await _finish(m, c["campaign_id"]), m.store.get(capped["campaign_id"])

    resumed, done, left = asyncio.run(go())
    assert resumed == [c["campaign_id"]]
    assert done["status"] == "succeeded" and done["auto_resumes"] == 1 and done["note"].startswith("Resumed")
    assert seen == ["Stage 2 of 5 of a research project"]  # the finished review was not rerun
    assert left["status"] == "interrupted" and "press Resume" in left["note"]


def test_auto_resume_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_CAMPAIGN_AUTO_RESUME", "0")
    store = cmod.CampaignStore(str(tmp_path / "campaigns"))
    c = cmod.CampaignManager(store).create("alice", "goal")
    c.update(status="running", owner=DEAD_OWNER)
    store.save(c)
    m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")))
    assert m.autostart() == [] and m.store.get(c["campaign_id"])["status"] == "interrupted"


def test_continue_adds_a_round_that_builds_on_everything_so_far(tmp_path):
    seen: list[dict[str, Any]] = []
    REPORTS.clear()

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        seen.append(request)
        return _result(f"answer {len(seen)}")

    async def go():
        m = _manager(tmp_path, runner)
        c = await m.submit("alice", "Probe prime gaps", stages=["review", "report"])
        await _finish(m, c["campaign_id"])
        with pytest.raises(jobs_mod.JobError):
            await m.continue_(c["campaign_id"], "alice", "   ")
        await m.continue_(c["campaign_id"], "alice", "Push the computation to 10^9")
        return await _finish(m, c["campaign_id"])

    c = asyncio.run(go())
    assert c["status"] == "succeeded" and c["rounds"] == 2
    assert [s["key"] for s in c["stages"]] == ["review", "report", "experiments@2", "analysis@2", "report@2"]
    assert c["stages"][2]["title"] == "Experiments (round 2)"
    exp = seen[1]  # review, then round 2's experiments
    assert "round 2" in exp["message"] and "Push the computation to 10^9" in exp["message"]
    assert "answer 1" in exp["agent_options"]["research_context"] and "Report 1" in exp["agent_options"]["research_context"]
    assert "Push the computation to 10^9" in REPORTS[1][1]
    report = cmod.report_markdown(c)
    assert report.index("# Report 2") < report.index("## Appendix") < report.index("# Report 1")  # newest leads


def test_resume_clears_the_timing_of_stages_that_will_run_again(tmp_path):
    m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "c")))
    c = m.create("alice", "goal", stages=["review", "hypotheses"])
    c["stages"][0].update(status="succeeded", started_at=1.0, finished_at=2.0)
    c["stages"][1].update(status="interrupted", started_at=3.0, job_id="job_x", attempts=1)
    cmod.CampaignManager._reset_for_run(c)
    assert c["stages"][0]["started_at"] == 1.0
    assert c["stages"][1] == {**c["stages"][1], "status": "pending", "started_at": None, "job_id": None, "attempts": 0}


def test_titles_are_short_names():
    long = ("Investigate the stopping time of the Collatz map in its shortcut form T(n) = n/2 for even n and (3n+1)/2 "
            "for odd n, where the stopping time s(n) is the number of steps.")
    assert cmod._title(long) == "Investigate the stopping time of the Collatz map"
    assert cmod._title("Study Ramsey numbers R(5,5)") == "Study Ramsey numbers R(5,5)"


def test_only_one_live_process_drives_a_project(tmp_path):
    import os

    import psutil

    store = cmod.CampaignStore(str(tmp_path / "campaigns"))
    c = cmod.CampaignManager(store).create("alice", "goal")
    parent = psutil.Process(os.getppid())
    c.update(status="running", owner=f"{parent.pid}:{round(parent.create_time(), 1)}")  # another live process
    store.save(c)
    assert cmod.owner_alive(c["owner"]) and store.claim(c["campaign_id"]) is None
    c["owner"] = DEAD_OWNER
    store.save(c)
    claimed = store.claim(c["campaign_id"])
    assert claimed is not None and claimed["owner"] == cmod.PROCESS_TOKEN
    assert not any(n.endswith(".claim") for n in os.listdir(store.storage_dir))


def test_create_validates_goal_and_stages(tmp_path):
    m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "c")))
    with pytest.raises(jobs_mod.JobError):
        m.create("alice", "   ")
    with pytest.raises(jobs_mod.JobError):
        m.create("alice", "goal", stages=["nonsense"])
    c = m.create("alice", "goal", stages=["experiments", "report"])
    assert [s["key"] for s in c["stages"]] == ["experiments", "report"]


def test_campaign_api_end_to_end(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        return _result("answer for " + request["message"].split(":", 1)[0])

    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob")
    jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=1)
    jobs_mod.set_job_manager(jm)
    manager = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
    manager.report_writer = fake_writer
    cmod.set_campaign_manager(manager)
    alice, bob = {"Authorization": "Bearer alice-token"}, {"Authorization": "Bearer bob-token"}
    try:
        with TestClient(backend_main.app) as api:
            r = api.post("/api/campaigns", json={"goal": "Study Ramsey numbers R(5,5)", "stages": ["review", "report"]},
                         headers=alice)
            assert r.status_code == 201, r.text
            cid = r.json()["campaign_id"]
            deadline = time.time() + 10
            while (c := api.get(f"/api/campaigns/{cid}", headers=alice).json())["status"] in cmod.RUNNING:
                assert time.time() < deadline
                time.sleep(0.05)
            assert c["status"] == "succeeded" and "user_id" not in c
            assert api.get(f"/api/campaigns/{cid}", headers=bob).status_code == 404
            listed = api.get("/api/campaigns", headers=alice).json()
            assert listed["campaigns"][0]["campaign_id"] == cid and "response" not in listed["campaigns"][0]["stages"][0]
            rep = api.get(f"/api/campaigns/{cid}/report", headers=alice)
            assert rep.status_code == 200 and rep.headers["content-type"].startswith("text/markdown")
            assert "# Study Ramsey numbers R(5,5)" in rep.text and "attachment" in rep.headers["content-disposition"]
            assert api.post(f"/api/campaigns/{cid}/resume", headers=alice).status_code == 409
            assert api.post("/api/campaigns", json={"goal": "x", "effort_level": "extreme"}, headers=alice).status_code == 422
            assert api.delete(f"/api/campaigns/{cid}", headers=alice).json()["deleted"] is True
            assert api.get("/api/campaigns/cmp_nothere", headers=alice).status_code == 404
    finally:
        jobs_mod.set_job_manager(None)
        cmod.set_campaign_manager(None)
