"""The adaptive research loop (tribos.agentic.research): charter validation, test runs with replication, the judge's
evidence rules, the stopping rule, the time estimate, the thesis and its number check, and memory isolation."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

import pytest

from tribos.agentic import campaign as cmod
from tribos.agentic import jobs as jobs_mod
from tribos.agentic.research import charter as ch
from tribos.agentic.research import judge as jd
from tribos.agentic.research.estimate import estimate, rough_estimate
from tribos.agentic.research.ledger import evidence_numbers, meets, unsupported_numbers

GOAL = ("Investigate sums of squares. (1) Compute S(N) = sum of k^2 for k <= N for N = 10, 100 and 1000. "
        "(2) Prove that S(N) = N(N+1)(2N+1)/6 for every natural number N.")

CODE = """Computing the sums exactly.
```python
S = {n: sum(k*k for k in range(1, n + 1)) for n in (10, 100, 1000)}
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.plot(list(S), list(S.values())); plt.title("S(N)"); plt.xlabel("N"); plt.ylabel("S(N)")
result = {"s_10": S[10], "s_100": S[100], "s_1000": S[1000],
          "series": {"S(N)": {"x": list(S), "y": list(S.values()), "x_label": "N", "y_label": "S(N)"}}}
print(result)
```"""


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.judge_rounds = 0

    async def text(self, system: str, user: Any, *, effort: str = "medium", max_tokens: int = 32000) -> str:
        if "persistent Python session" in system:
            self.calls.append("code")
            msgs = user if isinstance(user, list) else [("user", user)]
            if any(r == "user" and "Output of block" in m for r, m in msgs):
                return "FINAL ANSWER: S(10) = 385, S(100) = 338350 and S(1000) = 333833500, computed exactly."
            return CODE
        if "rigorous proof" in system:
            self.calls.append("proof")
            return "**Statement.** For every natural N, S(N) = N(N+1)(2N+1)/6.\n\n**Proof.** By induction on N. ∎"
        if "critical analyst" in system:
            self.calls.append("analysis")
            return "F1 gives S(10) = 385; the formula is proved in F2."
        if "chapter of a research thesis" in system:
            self.calls.append("chapter")
            if "Results" in user.split("Write the chapter")[-1][:40]:
                return "The computation gives S(1000) = 333833500 (F1) and also 4242.4242 which is invented."
            return "We study sums of squares; S(10) = 385 (F1)."
        raise AssertionError(f"unexpected text call: {system[:60]}")

    async def json(self, system: str, user: str, *, effort: str = "medium", max_tokens: int = 32000) -> Any:
        if "pre-registered study plan" in system:
            self.calls.append("charter")
            return {"summary": "Compute and prove.",
                    "deliverables": [{"id": "D1", "title": "Compute S(N) for N = 10, 100 and 1000",
                                      "acceptance": "exact values", "tier": "replicated"},
                                     {"id": "D2", "title": "Prove S(N) = N(N+1)(2N+1)/6 for every natural number N",
                                      "acceptance": "a proof", "tier": "formal"}],
                    "hypotheses": [{"id": "H1", "statement": "The closed form holds", "falsification": "any N where it fails"}],
                    "tests": [{"id": "T1", "title": "Exact sums", "kind": "compute", "objective": "compute S(N)",
                               "quantities": ["s_10", "s_100", "s_1000"], "serves": ["D1"], "hypotheses": ["H1"],
                               "cost": "s", "tier": "replicated"},
                              {"id": "T2", "title": "Closed form", "kind": "prove",
                               "objective": "For all n : Nat, 6 * S n = n*(n+1)*(2n+1)", "serves": ["D2"],
                               "hypotheses": ["H1"], "depends_on": ["T1"], "cost": "s", "tier": "formal"},
                              {"id": "T3", "title": "History of the formula", "kind": "literature",
                               "objective": "who first published the sum of squares formula", "serves": ["D1"],
                               "cost": "s", "tier": "sourced"}]}
        if "judge of a research project" in system:
            self.calls.append("judge")
            self.judge_rounds += 1
            by_test = {t: f for f, t in re.findall(r"\b(F\d+) \[[^\]]*\] test (T\d+)", user)}
            return {"deliverables": [{"id": "D1", "status": "done", "evidence": [by_test.get("T1", "")]},
                                     {"id": "D2", "status": "done", "evidence": [by_test.get("T2", "")]}],
                    "hypotheses": [{"id": "H1", "verdict": "supported", "evidence": [by_test.get("T2", "")]}],
                    "new_tests": [], "concluded": True, "headline": "The closed form holds and matches the sums."}
        raise AssertionError(f"unexpected json call: {system[:60]}")


def _result(text: str) -> dict[str, Any]:
    return {"response": text, "thread_id": "t", "task_status": {"task_status": "completed"},
            "citations": {"entries": {"DOI:10.1/x": {"key": "DOI:10.1/x", "title": "Faulhaber's formula",
                                                     "url": "https://doi.org/10.1/x", "year": "1631"}}}}


def test_a_project_loops_to_its_conclusion_and_writes_a_checked_thesis(tmp_path, monkeypatch):
    from tribos.verify.formal import prove as prove_mod

    async def fake_formal(statement, complete, **kw):
        return {"status": "verified", "title": "Formally verified (Lean)", "lean_code": "theorem t : True := trivial",
                "statement": "theorem t : True"}

    monkeypatch.setattr(prove_mod, "formalise_and_check", fake_formal)
    requests: list[dict[str, Any]] = []

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        requests.append(request)
        if request["message"].startswith("Stage 1"):
            return _result("The sum of squares formula N(N+1)(2N+1)/6 is classical [1].")
        return _result("Faulhaber (1631) gives the formula [1].")

    model = FakeModel()

    async def go():
        jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=2)
        m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
        m.research_model = lambda c: model
        c = await m.submit("alice", GOAL, mode="loop")
        deadline = time.monotonic() + 120
        while m.store.get(c["campaign_id"])["status"] in cmod.RUNNING and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        return m, m.store.get(c["campaign_id"])

    m, c = asyncio.run(go())
    assert c["status"] == "succeeded", c.get("error")
    assert c["loop"]["stop_reason"] == "concluded" and len(c["rounds"]) == 1
    # Background jobs never recall the user's other conversations.
    assert requests and all(r["recall_memory"] is False and r["persist_memory"] is False for r in requests)
    tiers = {f["test_id"]: f["tier"] for f in c["ledger"]}
    assert tiers == {"T1": "replicated", "T2": "formal", "T3": "sourced"}
    t1 = next(f for f in c["ledger"] if f["test_id"] == "T1")
    assert {q["name"]: q["value"] for q in t1["quantities"]} == {"s_10": 385, "s_100": 338350, "s_1000": 333833500}
    assert t1["series"] and t1["figures"]
    files = os.path.join(m.store.storage_dir, f"{c['campaign_id']}_files")
    assert os.path.exists(os.path.join(files, t1["figures"][0]["name"])) and os.path.exists(os.path.join(files, "design.svg"))
    assert [d["status"] for d in c["charter"]["deliverables"]] == ["done", "done"]
    assert c["charter"]["hypotheses"][0]["verdict"] == "supported"
    md = c["thesis"]["markdown"]
    for heading in ("## Abstract", "## 3 Hypotheses and research design", "## 5 Results", "## 6 Theorems and proofs",
                    "## References", "## Appendix A. Code and formal proofs"):
        assert heading in md
    assert "Lean-verified" in md and "```python" in md and "Faulhaber's formula" in md
    assert "4242.4242" in c["thesis"]["unverified"]  # invented number caught by the check
    assert c["dashboard"]["findings"] and any(b["type"] == "chart" for f in c["dashboard"]["findings"] for b in f["blocks"])
    assert c["estimate"]["remaining_s"] == 0
    listed = cmod.public_campaign(c, full=False)
    assert "ledger" not in listed and listed["summary"]["done"] == 2 and "markdown" not in listed["thesis"]


def test_the_charter_keeps_every_numbered_part_of_the_goal_and_breaks_cycles():
    raw = {"deliverables": [{"id": "X", "title": "something else"}],
           "tests": [{"id": "a", "title": "A", "serves": ["X"], "depends_on": ["b"]},
                     {"id": "b", "title": "B", "serves": ["X"], "depends_on": ["a"]}]}
    charter = ch.validate_charter(raw, GOAL)
    titles = [d["title"] for d in charter["deliverables"]]
    assert len(titles) == 3 and "Compute S(N)" in titles[1] and "Prove that" in titles[2]
    deps = {t["id"]: t["depends_on"] for t in charter["tests"]}
    assert not (deps["T1"] and deps["T2"])  # one edge of the cycle was dropped
    served = {d for t in charter["tests"] for d in t["serves"]}
    assert served == {"D1", "D2", "D3"}  # the goal's parts got tests of their own


def test_the_judge_cannot_mark_a_deliverable_done_without_strong_enough_evidence():
    camp = {"goal": "g", "charter": ch.validate_charter({"deliverables": [
        {"id": "D1", "title": "a", "tier": "replicated"}, {"id": "D2", "title": "b", "tier": "computed"},
        {"id": "D3", "title": "c"}]}, "g"),
        "ledger": [{"id": "F1", "test_id": "T1", "status": "passed", "tier": "computed"}]}
    out = jd.apply_judgement(camp, {"deliverables": [{"id": "D1", "status": "done", "evidence": ["F1"]},
                                                     {"id": "D2", "status": "done", "evidence": ["F1"]},
                                                     {"id": "D3", "status": "done", "evidence": ["F9"]}],
                                    "concluded": True})
    assert [d["status"] for d in out["deliverables"]] == ["partial", "done", "open"]
    assert out["concluded"] is False and out["model_concluded"] is True
    assert meets("formal", "sourced") and not meets("computed", "replicated")


def test_the_loop_stops_on_stagnation_and_on_its_ceilings():
    base = {"loop": {"started_at": time.time()}, "rounds": [{"progress": False}, {"progress": False}]}
    kw = {"max_rounds": 12, "max_hours": 8, "max_test_runs": 100, "stagnation": 2, "ready_tests": 3}
    assert jd.stop_reason(base, **kw) == "stagnated"
    assert jd.stop_reason({**base, "rounds": [{"progress": True}, {"progress": False}]}, **kw) is None
    assert jd.stop_reason({**base, "rounds": [{"progress": True, "concluded": True}]}, **kw) == "concluded"
    assert jd.stop_reason({**base, "rounds": [{"progress": True}] * 12}, **kw) == "round ceiling"
    assert jd.stop_reason({"loop": {"started_at": time.time() - 9 * 3600}, "rounds": [{"progress": True}]}, **kw) == "time ceiling"
    assert jd.stop_reason({**base, "rounds": [{"progress": True}]}, **{**kw, "ready_tests": 0}) == "nothing left to run"


def test_estimates_shrink_as_tests_finish_and_rough_estimates_scale_with_the_goal():
    charter = ch.validate_charter({"tests": [{"title": f"t{i}", "kind": "compute", "cost": "m"} for i in range(4)]}, GOAL)
    camp = {"status": "running", "charter": charter, "ledger": [], "loop": {}}
    first = estimate(camp, parallel=2)
    for t in charter["tests"][:3]:
        t["status"] = "passed"
    later = estimate(camp, parallel=2)
    assert later["remaining_s"] < first["remaining_s"] and first["low_s"] <= first["remaining_s"] <= first["high_s"]
    small, big = rough_estimate("Compute 2+2."), rough_estimate(GOAL + " Up to 10^7, with proofs.")
    assert big["remaining_s"] > small["remaining_s"] and big["rough"]


def test_the_number_check_accepts_rounded_evidence_and_rejects_invented_values():
    ev = evidence_numbers("mean 6.952 ln N", ledger=[{"quantities": [{"name": "m", "value": 3.14159265}]}])
    assert unsupported_numbers("about 3.1416 and 6.952; section 3; in 2019", ev) == []
    assert unsupported_numbers("a constant 2.71828", ev) == ["2.71828"]


def test_background_jobs_pass_the_memory_flags_to_the_orchestrator(monkeypatch):
    seen: dict[str, Any] = {}

    class Orch:
        async def execute_inquiry(self, **kw):
            seen.update(kw)

            class R:
                def to_dict(self):
                    return {"response": "ok"}
            return R()

    import tribos.agents.authoritative_orchestrator as ao

    monkeypatch.setattr(ao, "get_authoritative_orchestrator", lambda: Orch())
    control = type("C", (), {"interactive": False})()
    asyncio.run(jobs_mod.orchestrator_runner({"message": "q", "recall_memory": False, "persist_memory": False},
                                             user_id="u", event_callback=None, run_control=control))
    assert seen["recall_memory"] is False and seen["persist_memory"] is False


@pytest.mark.parametrize("flag", [True])
def test_a_chat_job_still_recalls_memory_by_default(monkeypatch, flag):
    seen: dict[str, Any] = {}

    class Orch:
        async def execute_inquiry(self, **kw):
            seen.update(kw)

            class R:
                def to_dict(self):
                    return {}
            return R()

    import tribos.agents.authoritative_orchestrator as ao

    monkeypatch.setattr(ao, "get_authoritative_orchestrator", lambda: Orch())
    control = type("C", (), {"interactive": False})()
    asyncio.run(jobs_mod.orchestrator_runner({"message": "q"}, user_id="u", event_callback=None, run_control=control))
    assert seen["recall_memory"] is flag and seen["persist_memory"] is flag


def test_an_empty_judgement_keeps_earlier_verdicts_and_evidence():
    camp = {"goal": "g", "charter": ch.validate_charter({
        "deliverables": [{"id": "D1", "title": "a", "tier": "computed"}],
        "hypotheses": [{"id": "H1", "statement": "s", "falsification": "f"}]}, "g"),
        "ledger": [{"id": "F1", "test_id": "T1", "status": "passed", "tier": "replicated"}]}
    jd.apply_judgement(camp, {"deliverables": [{"id": "D1", "status": "partial", "evidence": ["F1"], "note": "kept"}],
                              "hypotheses": [{"id": "H1", "verdict": "supported", "evidence": ["F1"], "note": "why"}]})
    jd.apply_judgement(camp, {})  # e.g. a judgement that came back empty
    h = camp["charter"]["hypotheses"][0]
    d = camp["charter"]["deliverables"][0]
    assert (h["verdict"], h["evidence"], h["note"]) == ("supported", ["F1"], "why")
    assert (d["status"], d["evidence"], d["note"]) == ("partial", ["F1"], "kept")


def test_an_unreachable_judge_pauses_the_project_and_resume_finishes_it(tmp_path, monkeypatch):
    from tribos.verify.formal import prove as prove_mod

    async def fake_formal(statement, complete, **kw):
        return {"status": "verified", "lean_code": "theorem t : True := trivial", "statement": "t"}

    monkeypatch.setattr(prove_mod, "formalise_and_check", fake_formal)

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        return _result("Classical [1].")

    class FlakyJudge(FakeModel):
        down = True

        async def json(self, system, user, **kw):
            if "judge of a research project" in system and self.down:
                raise ConnectionError("provider unreachable")
            return await super().json(system, user, **kw)

    model = FlakyJudge()

    async def go():
        jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=2)
        m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
        m.research_model = lambda c: model

        async def settle(cid):
            deadline = time.monotonic() + 120
            while m.store.get(cid)["status"] in cmod.RUNNING and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            return m.store.get(cid)

        c = await m.submit("alice", GOAL, mode="loop")
        paused = await settle(c["campaign_id"])
        model.down = False
        await m.resume(c["campaign_id"], "alice")
        return paused, await settle(c["campaign_id"])

    paused, done = asyncio.run(go())
    assert paused["status"] == "failed" and "Resume continues" in paused["error"]
    assert not paused["rounds"][0].get("finished_at") and paused["thesis"]["status"] == "pending"
    assert done["status"] == "succeeded" and done["loop"]["stop_reason"] == "concluded"
    assert len(done["rounds"]) == 1 and len({f["test_id"] for f in done["ledger"]}) == 3  # no test was run twice


def test_a_computation_for_a_replicated_deliverable_is_run_with_replication():
    charter = ch.validate_charter({
        "deliverables": [{"id": "D1", "title": "exact values", "tier": "replicated"},
                         {"id": "D2", "title": "an estimate", "tier": "computed"}],
        "tests": [{"id": "T1", "title": "census", "kind": "compute", "serves": ["D1"], "tier": "computed"},
                  {"id": "T2", "title": "rough fit", "kind": "estimate", "serves": ["D2"], "tier": "computed"}]}, "g")
    assert [t["tier"] for t in charter["tests"]] == ["replicated", "computed"]


def test_a_model_outage_never_blocks_a_test_and_resume_rearms_what_it_cut_off():
    from tribos.agentic.research.loop import is_provider_outage, rearm_after_outage

    assert is_provider_outage("APIConnectionError: Connection error.") and is_provider_outage("ReadTimeout: ")
    assert not is_provider_outage("ZeroDivisionError: division by zero") and not is_provider_outage(None)
    camp = {"loop": {"stop_reason": "nothing left to run"}, "charter": {"tests": [
        {"id": "T1", "kind": "compute", "status": "blocked", "last_error": "APIConnectionError: Connection error.",
         "attempts": 3, "finding_ids": ["F1"]},
        {"id": "T2", "kind": "compute", "status": "blocked", "last_error": "no `result` was set", "finding_ids": ["F2"]},
        {"id": "T3", "kind": "prove", "status": "passed", "finding_ids": ["F3"]},
        {"id": "T4", "kind": "prove", "status": "passed", "finding_ids": ["F4"]}]},
        "ledger": [{"id": "F1"}, {"id": "F2"},
                   {"id": "F3", "tier": "reasoned", "proof": {"lean_status": "failed", "lean_error": "ReadTimeout: "}},
                   {"id": "F4", "tier": "reasoned", "proof": {"lean_status": "failed", "lean_error": "type mismatch"}}]}
    assert rearm_after_outage(camp) == ["T1", "T3"]
    tests = {t["id"]: t for t in camp["charter"]["tests"]}
    assert tests["T1"]["status"] == "pending" and tests["T1"]["attempts"] == 0
    assert tests["T2"]["status"] == "blocked" and tests["T4"]["status"] == "passed"  # real failures stand
    assert camp["loop"]["stop_reason"] is None
    tests["T3"]["status"] = "passed"  # its formal retry was cut off again: one more attempt, then no more
    assert rearm_after_outage(camp) == ["T3"] and tests["T3"]["lean_retries"] == 2
    tests["T3"]["status"] = "passed"
    assert rearm_after_outage(camp) == []


def test_an_outage_during_a_test_pauses_the_project_instead_of_blocking(tmp_path, monkeypatch):
    from tribos.verify.formal import prove as prove_mod

    async def fake_formal(statement, complete, **kw):
        return {"status": "verified", "lean_code": "theorem t : True := trivial", "statement": "t"}

    monkeypatch.setattr(prove_mod, "formalise_and_check", fake_formal)

    async def runner(request, *, user_id, event_callback, run_control, api_key=None):
        return _result("Classical [1].")

    class FlakyCoder(FakeModel):
        down = True

        async def text(self, system, user, **kw):
            if "persistent Python session" in system and self.down:
                raise ConnectionError("APIConnectionError: Connection error.")
            return await super().text(system, user, **kw)

    model = FlakyCoder()

    async def go():
        jm = jobs_mod.JobManager(jobs_mod.JobStore(str(tmp_path / "jobs")), runner=runner, workers=2)
        m = cmod.CampaignManager(cmod.CampaignStore(str(tmp_path / "campaigns")), jobs=jm)
        m.research_model = lambda c: model

        async def settle(cid):
            deadline = time.monotonic() + 120
            while m.store.get(cid)["status"] in cmod.RUNNING and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            return m.store.get(cid)

        c = await m.submit("alice", GOAL, mode="loop")
        paused = await settle(c["campaign_id"])
        model.down = False
        await m.resume(c["campaign_id"], "alice")
        return paused, await settle(c["campaign_id"])

    paused, done = asyncio.run(go())
    assert paused["status"] == "failed" and "unreachable" in paused["error"]
    t1 = next(t for t in paused["charter"]["tests"] if t["id"] == "T1")
    assert t1["status"] == "pending" and t1["attempts"] == 0
    assert done["status"] == "succeeded" and done["loop"]["stop_reason"] == "concluded"


def test_the_time_ceiling_counts_active_time_not_time_spent_paused():
    from tribos.agentic.research.loop import active_seconds

    now = time.time()
    kw = {"max_rounds": 12, "max_hours": 8, "max_test_runs": 100, "stagnation": 2, "ready_tests": 3, "now": now}
    paused_overnight = {"loop": {"started_at": now - 20 * 3600, "active_s": 1800.0}, "rounds": [{"progress": True}]}
    assert jd.stop_reason(paused_overnight, **kw) is None
    long_running = {"loop": {"started_at": now - 20 * 3600, "active_s": 7 * 3600.0, "segment_started": now - 3600 * 1.5},
                    "rounds": [{"progress": True}]}
    assert jd.stop_reason(long_running, **kw) == "time ceiling"
    assert active_seconds({"active_s": 60.0, "segment_started": now - 30}, now=now) == 90.0


def test_imports_of_modules_missing_from_mathlib_are_removed_before_checking(tmp_path):
    from tribos.verify.formal.runner import drop_missing_imports

    lib = tmp_path / ".lake" / "packages" / "mathlib" / ".lake" / "build" / "lib" / "lean" / "Mathlib" / "Data" / "Nat"
    lib.mkdir(parents=True)
    (lib / "Basic.olean").write_bytes(b"")
    code = "import Mathlib.Tactic.Omega\nimport Mathlib.Data.Nat.Basic\ntheorem t : True := trivial\n"
    out, dropped = drop_missing_imports(code, str(tmp_path))
    assert dropped == ["Mathlib.Tactic.Omega"]
    assert "import Mathlib.Data.Nat.Basic" in out and "\nimport Mathlib.Tactic.Omega" not in "\n" + out
    assert drop_missing_imports(code, None) == (code, [])  # no project: nothing is touched


def test_a_comma_separated_list_is_several_numbers_and_thousands_separators_still_work():
    ev = evidence_numbers(ledger=[{"quantities": [{"name": "spots", "value": [27, 97, 871, 1000000]}]}])
    assert unsupported_numbers("spot checks at n = 27,97,871 and up to 1,000,000", ev) == []
    assert unsupported_numbers("a list 27,98", ev) == ["98"]


def test_round_durations_exclude_pauses_and_theorems_show_each_proof_once():
    from tribos.agentic.research.loop import round_seconds
    from tribos.agentic.research.thesis import _proofs_md, best_proofs

    t0 = 1_000_000.0
    camp = {"loop": {}, "stages": [{"key": "analysis@1", "started_at": t0 + 900, "finished_at": t0 + 1000}],
            "ledger": [{"round": 1, "finished_at": t0 + 300, "seconds": 300},           # before an overnight pause
                       {"round": 1, "finished_at": t0 + 600, "seconds": 400},           # overlaps the first
                       {"round": 1, "finished_at": t0 + 80_000, "seconds": 200}]}       # after the pause
    rnd = {"round": 1, "started_at": t0, "finished_at": t0 + 80_100}
    assert round_seconds(camp, rnd) == 600 + 100 + 200  # merged busy time; the pause and idle gaps are not counted
    assert round_seconds({"loop": {"active_s": 500.0}}, {"active_at_start": 200.0}) == 300.0

    ledger = [{"id": "F1", "test_id": "T1", "status": "failed", "tier": "none", "proof": {"statement": "x", "text": ""}},
              {"id": "F2", "test_id": "T1", "status": "passed", "tier": "reasoned",
               "proof": {"statement": "Prove that 1 + 1 = 2", "text": "Clear.", "lean_status": "failed"}},
              {"id": "F3", "test_id": "T1", "status": "passed", "tier": "formal",
               "proof": {"statement": "Prove that 1 + 1 = 2", "text": "Clear.", "lean_status": "verified",
                         "lean_code": "example : 1 + 1 = 2 := rfl"}},
              {"id": "F4", "test_id": "T2", "status": "failed", "tier": "none",
               "proof": {"statement": "y", "text": "", "lean_status": "failed"}}]
    assert [f["id"] for f in best_proofs({"ledger": ledger})] == ["F3"]
    md = _proofs_md({"ledger": ledger})
    assert md.count("**Theorem") == 1 and "(Lean-verified; finding F3). 1 + 1 = 2" in md
