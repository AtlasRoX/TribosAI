"""
The research loop: review -> charter -> rounds (tests in parallel -> analysis -> judge) until the project reaches its
conclusion, stops making progress, or hits a safety ceiling -> thesis.

The loop is a state machine over the stored campaign record, so a project resumed after a restart (or a crash, or a
Stop and Resume) continues where it was: a finished review, charter, test or round is never redone. Each test retries
with its error up to TRIBOS_RESEARCH_TEST_RETRIES times inside its round; after that it is blocked, and the judge may
plan a different test for the gap.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

from .charter import CHARTER_SYSTEM, add_tests, goal_items, validate_charter
from .dashboard import build_dashboard
from .estimate import estimate, measured
from .judge import (
    ANALYSIS_SYSTEM,
    JUDGE_SYSTEM,
    apply_judgement,
    made_progress,
    progress_snapshot,
    round_context,
    stop_reason,
)
from .ledger import ledger_text, next_id
from .model import ResearchModel
from .runner import run_compute, run_literature, run_prove
from .thesis import write_thesis

logger = logging.getLogger("tribos.research")

REVIEW_PROMPT = (
    "Stage 1 of a research project: the literature review. Do only this stage now; later stages run the computations "
    "and proofs the goal asks for, so do not report them as missing.\n"
    "Survey what is known about the research goal: the main results, methods, open questions and the strongest "
    "sources. Separate what is proved from what is conjectured or heuristic, give exact statements and constants, "
    "and cite every source.")
ACTIVE_TEST = ("pending", "retry", "running")
EFFORTS = {"high": {"plan": "medium", "code": "medium", "write": "medium"},
           "medium": {"plan": "medium", "code": "low", "write": "medium"},
           "low": {"plan": "low", "code": "low", "write": "low"}}


def _settings() -> dict[str, Any]:
    from ...config.settings import get_bool, get_int

    return {"max_rounds": get_int("TRIBOS_RESEARCH_MAX_ROUNDS"), "max_hours": float(get_int("TRIBOS_RESEARCH_MAX_HOURS")),
            "max_test_runs": get_int("TRIBOS_RESEARCH_MAX_TEST_RUNS"), "parallel": get_int("TRIBOS_RESEARCH_PARALLEL_TESTS"),
            "steps": get_int("TRIBOS_RESEARCH_CODEACT_STEPS"), "retries": get_int("TRIBOS_RESEARCH_TEST_RETRIES"),
            "stagnation": get_int("TRIBOS_RESEARCH_STAGNATION_ROUNDS"), "cross_check": get_bool("TRIBOS_RESEARCH_CROSS_CHECK"),
            "timeout": get_int("TRIBOS_RESEARCH_SANDBOX_TIMEOUT_S")}


_OUTAGE_RE = re.compile(r"APIConnectionError|Connection error|ConnectError|ConnectTimeout|ReadTimeout|"
                        r"RemoteProtocolError|RateLimit|ServiceUnavailable|InternalServerError|EmptyReply|"
                        r"model service was unreachable", re.I)


def active_seconds(loop: dict[str, Any], now: float | None = None) -> float:
    """Seconds the loop has actually been running: earlier segments plus the current one."""
    now = now or time.time()
    current = now - float(loop["segment_started"]) if loop.get("segment_started") else 0.0
    return float(loop.get("active_s") or 0.0) + max(0.0, current)


def is_provider_outage(error: Any) -> bool:
    """A failure caused by the model service (unreachable, timed out, overloaded), not by the research itself."""
    return bool(error) and bool(_OUTAGE_RE.search(str(error)))


def _lean_retries(t: dict[str, Any]) -> int:
    return int(t.get("lean_retries") or (1 if t.get("lean_retried") else 0))


def _formal_check_cut_off(proof: dict[str, Any]) -> bool:
    """The Lean check said nothing about the proof: the model service failed, or Lean could not load its library."""
    return proof.get("lean_status") == "unavailable" or is_provider_outage(proof.get("lean_error"))


def rearm_after_outage(campaign: dict[str, Any]) -> list[str]:
    """On resume: tests blocked only by a model-service outage run again, and a proof whose Lean check was cut off
    by one gets one more formal attempt (its written proof stays in the ledger). Returns the re-armed test ids."""
    charter = campaign.get("charter") or {}
    findings = {f["id"]: f for f in campaign.get("ledger") or []}
    rearmed = []
    for t in charter.get("tests") or []:
        last = findings.get((t.get("finding_ids") or [None])[-1]) or {}
        if t.get("status") == "blocked" and is_provider_outage(t.get("last_error")):
            t.update(status="pending", attempts=0)
            rearmed.append(t["id"])
        elif (t.get("kind") == "prove" and t.get("status") == "passed" and last.get("tier") != "formal"
              and _formal_check_cut_off(last.get("proof") or {}) and _lean_retries(t) < 2):
            t.update(status="pending", lean_retries=_lean_retries(t) + 1)
            rearmed.append(t["id"])
    if rearmed:
        campaign.setdefault("loop", {})["stop_reason"] = None
    return rearmed


def init_loop_state(campaign: dict[str, Any]) -> None:
    campaign.setdefault("loop", {"phase": "review", "stop_reason": None, "instructions": [], "test_runs": 0,
                                 "started_at": time.time(), "replan": False})
    campaign.setdefault("review", {"status": "pending", "response": "", "citations": {}, "error": None})
    campaign.setdefault("charter", None)
    campaign.setdefault("ledger", [])
    campaign.setdefault("rounds", [])
    campaign.setdefault("thesis", {"status": "pending"})
    campaign.setdefault("activity", [])
    campaign.setdefault("stages", [])


class ResearchLoop:
    def __init__(self, manager: Any, campaign: dict[str, Any], model: ResearchModel) -> None:
        self.m = manager
        self.c = campaign
        self.model = model
        self.cfg = _settings()
        self.effort = EFFORTS.get(str(campaign.get("effort_level") or "high"), EFFORTS["high"])
        self.files_dir = os.path.join(manager.store.storage_dir, f"{campaign['campaign_id']}_files")
        self._last_save = 0.0
        self._history: dict[tuple, float] | None = None

    # -- bookkeeping -------------------------------------------------------------------------------------------
    def save(self, *, force: bool = True) -> None:
        now = time.time()
        if not force and now - self._last_save < 2.0:
            return
        self._last_save = now
        if self.c.get("charter"):
            self.c["estimate"] = estimate(self.c, history=self.history(), parallel=self.cfg["parallel"], now=now)
        else:
            self.c["estimate"] = estimate(self.c, now=now)
        self.m._beat(self.c)

    def history(self) -> dict[tuple, float]:
        if self._history is None:
            ledgers, tests = [], []
            try:
                for cid in self.m.store.all_ids()[:200]:
                    other = self.m.store.get(cid)
                    if other and other.get("charter") and other["campaign_id"] != self.c["campaign_id"]:
                        ledgers.append(other.get("ledger") or [])
                        tests.append({t["id"]: t for t in other["charter"]["tests"]})
            except Exception:  # noqa: BLE001 - the estimate falls back to priors
                pass
            self._history = measured(ledgers, tests)
        return self._history

    def activity(self, text: str, ref: str | None = None) -> None:
        log = self.c.setdefault("activity", [])
        log.append({"t": time.time(), "text": text[:300], "ref": ref})
        del log[:-80]
        self.save(force=False)

    def stage(self, key: str, title: str, base: str, round_no: int | None = None) -> dict[str, Any]:
        rec = next((s for s in self.c["stages"] if s["key"] == key), None)
        if rec is None:
            rec = {"key": key, "title": title, "base": base, "round": round_no, "status": "pending", "job_id": None,
                   "started_at": None, "finished_at": None, "response": "", "citations": {}, "error": None, "attempts": 0}
            self.c["stages"].append(rec)
        return rec

    def start_stage(self, rec: dict[str, Any], phase: str) -> None:
        rec.update(status="running", started_at=time.time(), finished_at=None, error=None)
        self.c["loop"]["phase"] = phase
        self.c["current_stage"] = rec["key"]
        self.save()

    def end_stage(self, rec: dict[str, Any], status: str, error: str | None = None) -> None:
        rec.update(status=status, finished_at=time.time(), error=error)
        self.save()

    def cancelled(self) -> bool:
        return self.m._cancelled_elsewhere(self.c)

    async def job(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run one orchestrator job and wait for it: {"status", "result", "error", "job_id"}."""
        from ..jobs import ACTIVE, JobError

        uid = self.c["user_id"]
        while True:
            if self.cancelled():
                return {"status": "cancelled", "result": None, "error": "cancelled"}
            try:
                job = await self.m.jobs.submit(uid, request, origin="campaign")
                break
            except JobError as exc:
                if exc.status_code != 429:
                    return {"status": "failed", "result": None, "error": str(exc)}
                await asyncio.sleep(10)
        while True:
            row = await self.m.jobs.wait(job["job_id"], timeout=15.0)
            if row is None:
                return {"status": "failed", "result": None, "error": "the job disappeared", "job_id": job["job_id"]}
            if row["status"] not in ACTIVE:
                return {"status": row["status"], "result": row.get("result") or {}, "error": row.get("error"),
                        "job_id": job["job_id"]}
            if self.cancelled():
                try:
                    await self.m.jobs.cancel(job["job_id"], uid, reason="research project cancelled")
                except Exception:  # noqa: BLE001
                    pass
                return {"status": "cancelled", "result": None, "error": "cancelled", "job_id": job["job_id"]}
            self.save(force=False)

    def base_request(self, *, web: bool) -> dict[str, Any]:
        req = {"thread_id": f"{self.c['thread_id']}__r{len(self.c.get('rounds') or [])}_{int(time.time() * 1000) % 10**8}",
               "model": self.c.get("model"), "enable_web_search": bool(web and self.c.get("web_search", True)),
               "project_id": self.c.get("project_id"), "recall_memory": False, "persist_memory": False,
               "agent_options": {"effort_level": self.c.get("effort_level") or "high", "allow_clarification": False}}
        return {k: v for k, v in req.items() if v is not None}

    # -- phases ------------------------------------------------------------------------------------------------
    async def review(self) -> None:
        rev = self.c["review"]
        if rev.get("status") == "succeeded":
            return
        rec = self.stage("review", "Literature review", "review")
        self.start_stage(rec, "review")
        self.activity("Reviewing the literature")
        req = self.base_request(web=True)
        req["message"] = f"{REVIEW_PROMPT}\n\nResearch goal: {self.c['goal']}"
        req["display_message"] = f"[Research project · Literature review] {self.c['title']}"
        out = {"status": "failed", "error": "not run"}
        for _ in range(2):
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            out = await self.job(req)
            rec["job_id"] = out.get("job_id")
            if out["status"] in ("succeeded", "cancelled"):
                break
        text = str((out.get("result") or {}).get("response") or "")
        if out["status"] == "succeeded" and text.strip():
            rev.update(status="succeeded", response=text, citations=(out.get("result") or {}).get("citations") or {})
            rec["response"] = text
            self.end_stage(rec, "succeeded")
        elif out["status"] == "cancelled":
            raise asyncio.CancelledError
        else:
            # The project goes on without a review: the charter is planned from the goal alone, and the thesis says so.
            rev.update(status="failed", error=str(out.get("error") or "no answer")[:300])
            self.end_stage(rec, "failed", rev["error"])
            self.activity("The literature review failed; planning from the goal alone")

    async def plan(self) -> None:
        if self.c.get("charter"):
            return
        rec = self.stage("charter", "Research plan", "charter")
        self.start_stage(rec, "charter")
        self.activity("Writing the research plan: deliverables, hypotheses and tests")
        user = (f"Research goal:\n{self.c['goal']}\n\nNumbered parts of the goal: "
                f"{'; '.join(goal_items(self.c['goal'])) or '(none)'}\n\nLiterature review:\n"
                f"{str(self.c['review'].get('response') or '(no review available)')[:16000]}")
        raw: Any = {}
        for attempt in range(2):
            try:
                raw = await self.model.json(CHARTER_SYSTEM, user, effort=self.effort["plan"])
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("research.charter attempt %s failed: %s", attempt + 1, exc)
        self.c["charter"] = validate_charter(raw, self.c["goal"])
        ch = self.c["charter"]
        rec["response"] = ch.get("summary") or ""
        self.end_stage(rec, "succeeded")
        self.activity(f"Plan: {len(ch['deliverables'])} deliverables, {len(ch['hypotheses'])} hypotheses, "
                      f"{len(ch['tests'])} tests")

    def ready_tests(self) -> list[dict[str, Any]]:
        tests = self.c["charter"]["tests"]
        status = {t["id"]: t["status"] for t in tests}
        ready = []
        for t in tests:
            if t["status"] not in ("pending", "retry"):
                continue
            deps = t.get("depends_on") or []
            if any(status.get(d) in ("blocked", "failed") for d in deps):
                t.update(status="blocked", last_error="a test it depends on was blocked")
                continue
            if all(status.get(d) in ("passed", "disputed") for d in deps):
                ready.append(t)
        return ready

    def test_context(self, t: dict[str, Any]) -> str:
        ids = set()
        for f in self.c["ledger"]:
            ft = next((x for x in self.c["charter"]["tests"] if x["id"] == f.get("test_id")), None)
            if f.get("status") in ("passed", "disputed") and ft and (
                    ft["id"] in (t.get("depends_on") or []) or set(ft["serves"]) & set(t["serves"])):
                ids.add(f["id"])
        return ledger_text(self.c["ledger"], ids=sorted(ids), limit_chars=6000) if ids else ""

    async def run_test(self, t: dict[str, Any], round_no: int) -> None:
        rec = self.stage(f"{t['id']}@{round_no}", f"{t['id']} · {t['title']}", "test", round_no)
        t.update(status="running", started_at=time.time())
        self.start_stage(rec, "testing")
        self.c["loop"]["phase"] = "testing"
        finding: dict[str, Any] = {}
        for attempt in range(self.cfg["retries"] + 1):
            if self.cancelled():
                raise asyncio.CancelledError
            t["attempts"] = int(t.get("attempts") or 0) + 1
            self.c["loop"]["test_runs"] = int(self.c["loop"].get("test_runs") or 0) + 1
            fid = next_id(self.c["ledger"])
            self.c["ledger"].append({"id": fid, "test_id": t["id"], "status": "running", "round": round_no,
                                     "tier": "none", "summary": "", "quantities": [], "series": []})
            placeholder = self.c["ledger"][-1]
            self.activity(f"{t['id']} started ({t['kind']}){' — retry ' + str(attempt) if attempt else ''}: {t['title']}",
                          t["id"])

            async def progress(msg: str) -> None:
                self.activity(msg, t["id"])

            try:
                if t["kind"] == "prove":
                    finding = await run_prove(self.model, t, goal=self.c["goal"], context=self.test_context(t),
                                              finding_id=fid, effort=self.effort["write"], on_progress=progress)
                elif t["kind"] == "literature":
                    finding = await run_literature(self.job, t, goal=self.c["goal"], context=self.test_context(t),
                                                   finding_id=fid, request=self.base_request(web=True))
                else:
                    finding = await run_compute(self.model, t, goal=self.c["goal"], context=self.test_context(t),
                                                finding_id=fid, files_dir=self.files_dir, steps=self.cfg["steps"],
                                                effort=self.effort["code"], timeout_s=self.cfg["timeout"],
                                                cross_check=self.cfg["cross_check"], on_progress=progress)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a crashed test is a failed attempt
                logger.warning("research.test %s crashed: %s", t["id"], exc, exc_info=True)
                finding = {"id": fid, "test_id": t["id"], "kind": t["kind"], "status": "failed", "tier": "none",
                           "summary": "", "quantities": [], "series": [], "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            finding.update(round=round_no, attempt=attempt + 1, finished_at=time.time())
            placeholder.clear()
            placeholder.update(finding)
            t.setdefault("finding_ids", []).append(fid)
            logger.info("research.test %s %s %s tier=%s %.0fs", self.c["campaign_id"], t["id"], finding["status"],
                        finding.get("tier"), finding.get("seconds") or 0)
            if finding["status"] in ("passed", "disputed", "refuted"):
                break
            if is_provider_outage(finding.get("error")):
                # The model service was unreachable (through the model's own retries): the test says nothing about
                # the research. It does not use up its retries or get blocked; the project pauses and Resume reruns it.
                t.update(status="pending", last_error=str(finding.get("error"))[:600])
                t["attempts"] = max(0, int(t.get("attempts") or 1) - 1)
                self.end_stage(rec, "failed", "the model service was unreachable")
                raise RuntimeError(f"{t['id']} could not run: the model service was unreachable "
                                   f"({str(finding.get('error'))[:120]}). Resume continues from this test.")
            t["last_error"] = str(finding.get("error") or "failed")[:600]
            self.activity(f"{t['id']} failed: {t['last_error'][:160]}", t["id"])
            self.save()
        st = finding.get("status")
        t["status"] = {"passed": "passed", "disputed": "disputed", "refuted": "passed"}.get(st, "blocked")
        self.end_stage(rec, "succeeded" if t["status"] != "blocked" else "failed",
                       None if t["status"] != "blocked" else t.get("last_error"))
        rec["response"] = str(finding.get("summary") or "")[:2000]
        self.activity(f"{t['id']} {t['status']} ({finding.get('tier')})", t["id"])

    async def judge(self, rnd: dict[str, Any]) -> None:
        r = rnd["round"]
        rec = self.stage(f"analysis@{r}", f"Analysis and judgement (round {r})", "judge", r)
        self.start_stage(rec, "judging")
        before = progress_snapshot(self.c)
        context = round_context(self.c)
        try:
            rnd["analysis"] = await self.model.text(ANALYSIS_SYSTEM, context, effort=self.effort["plan"], max_tokens=24000)
        except Exception as exc:  # noqa: BLE001
            rnd["analysis"] = f"(The analysis could not be written: {type(exc).__name__}.)"
        self.activity(f"Round {r}: judging what is established")
        try:
            raw = await self.model.json(JUDGE_SYSTEM, f"{context}\n\nCritical analysis of this round:\n{rnd['analysis']}",
                                        effort=self.effort["plan"])
        except Exception as exc:  # noqa: BLE001
            # The model stayed unreachable through its retries. Judging nothing would read as "no progress" and could
            # end the project early; the round stays open instead, and Resume judges it again.
            logger.warning("research.judge failed: %s", exc)
            rnd.pop("analysis", None)
            self.end_stage(rec, "failed", f"the judge could not be reached ({type(exc).__name__})")
            raise RuntimeError(f"Round {r} could not be judged: the model was unreachable ({type(exc).__name__}). "
                               "Resume continues from this round.") from exc
        accepted = apply_judgement(self.c, raw)
        added = add_tests(self.c["charter"], accepted["new_tests"], r + 1, "judge: gaps and discrepancies")
        after = progress_snapshot(self.c)
        rnd.update(judgement={k: v for k, v in accepted.items() if k != "new_tests"}, added_tests=added,
                   progress=made_progress(before, after), concluded=accepted["concluded"],
                   headline=accepted["headline"], finished_at=time.time())
        rnd["seconds"] = rnd["finished_at"] - float(rnd.get("started_at") or rnd["finished_at"])
        rec["response"] = rnd["analysis"]
        self.end_stage(rec, "succeeded")
        self.c["dashboard"] = build_dashboard(self.c)
        logger.info("research.round %s r=%s progress=%s concluded=%s added=%s", self.c["campaign_id"], r,
                    rnd["progress"], rnd["concluded"], added)
        self.activity(f"Round {r} judged: {'conclusion reached' if rnd['concluded'] else 'progress' if rnd['progress'] else 'no progress'}"
                      + (f"; {len(added)} new test(s) planned" if added else ""))

    async def replan(self) -> None:
        """A follow-up instruction: it becomes a deliverable, and the judge plans tests for it."""
        loop = self.c["loop"]
        instr = (loop.get("instructions") or [""])[-1]
        ch = self.c["charter"]
        did = f"D{len(ch['deliverables']) + 1}"
        ch["deliverables"].append({"id": did, "title": instr[:200], "acceptance": instr[:800], "tier": "replicated",
                                   "status": "open", "evidence": [], "note": "added by a follow-up instruction"})
        try:
            raw = await self.model.json(JUDGE_SYSTEM, round_context(self.c) + f"\n\nPlan tests for the new deliverable {did}.",
                                        effort=self.effort["plan"])
            proposed = [t for t in (raw.get("new_tests") if isinstance(raw, dict) else []) or [] if isinstance(t, dict)]
        except Exception:  # noqa: BLE001
            proposed = []
        added = add_tests(ch, proposed, len(self.c["rounds"]) + 1, f"follow-up: {instr[:200]}")
        if not added:
            add_tests(ch, [{"title": instr[:100], "kind": "compute", "objective": instr, "serves": [did],
                            "tier": "replicated"}], len(self.c["rounds"]) + 1, "follow-up")
        loop["replan"] = False
        self.save()

    async def rounds(self) -> None:
        cfg = self.cfg
        loop = self.c["loop"]
        if loop.get("replan"):
            await self.replan()
        while True:
            if self.cancelled():
                raise asyncio.CancelledError
            rnd = self.c["rounds"][-1] if self.c["rounds"] and not self.c["rounds"][-1].get("finished_at") else None
            if rnd is None:
                ready = self.ready_tests()
                reason = stop_reason(self.c, max_rounds=cfg["max_rounds"], max_hours=cfg["max_hours"],
                                     max_test_runs=cfg["max_test_runs"], stagnation=cfg["stagnation"],
                                     ready_tests=len(ready))
                if self.c["rounds"] and reason:
                    loop["stop_reason"] = reason
                    self.activity(f"Stopping: {reason}")
                    return
                if not ready:
                    loop["stop_reason"] = "nothing left to run"
                    return
                rnd = {"round": len(self.c["rounds"]) + 1, "started_at": time.time(), "tests": [t["id"] for t in ready]}
                self.c["rounds"].append(rnd)
                self.activity(f"Round {rnd['round']}: running {len(ready)} test(s)")
                self.save()
            await self.run_round_tests(rnd)
            await self.judge(rnd)
            self.save()

    async def run_round_tests(self, rnd: dict[str, Any]) -> None:
        """Run the round's tests over the dependency graph: at most TRIBOS_RESEARCH_PARALLEL_TESTS at once, and a
        test whose dependencies pass during the round starts in the same round."""
        tests = {t["id"]: t for t in self.c["charter"]["tests"]}
        for i in rnd["tests"]:
            if tests.get(i) and tests[i]["status"] == "running":
                tests[i]["status"] = "pending"  # interrupted mid-run: run it again
        sem = asyncio.Semaphore(self.cfg["parallel"])
        active: dict[str, asyncio.Task[None]] = {}
        started: set[str] = set()

        async def go(t: dict[str, Any]) -> None:
            async with sem:
                await self.run_test(t, rnd["round"])

        try:
            while True:
                for t in self.ready_tests():
                    if t["id"] in started:
                        continue
                    if t["id"] not in rnd["tests"]:
                        rnd["tests"].append(t["id"])
                    started.add(t["id"])
                    active[t["id"]] = asyncio.create_task(go(t))
                if not active:
                    return
                done, _ = await asyncio.wait(active.values(), return_when=asyncio.FIRST_COMPLETED)
                for tid in [k for k, task in active.items() if task in done]:
                    active.pop(tid).result()  # re-raises a cancellation or an unexpected error
        finally:
            for task in active.values():
                task.cancel()

    async def thesis(self) -> None:
        if (self.c.get("thesis") or {}).get("status") == "succeeded":
            return
        rec = self.stage("thesis", "Thesis", "thesis")
        self.start_stage(rec, "thesis")
        self.c["loop"]["phase"] = "thesis"
        self.activity("Writing the thesis")
        last: Exception | None = None
        for _ in range(2):
            try:
                self.c["thesis"] = await write_thesis(self.model, self.c, self.files_dir, effort=self.effort["write"])
                rec["response"] = (self.c["thesis"]["chapters"][0]["markdown"] if self.c["thesis"].get("chapters") else "")
                self.end_stage(rec, "succeeded")
                self.activity("Thesis written")
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                logger.warning("research.thesis failed: %s", exc, exc_info=True)
        self.c["thesis"] = {"status": "failed", "error": f"{type(last).__name__}: {str(last)[:300]}"}
        self.end_stage(rec, "failed", self.c["thesis"]["error"])
        raise RuntimeError(f"the thesis could not be written ({type(last).__name__})")

    async def run(self) -> None:
        init_loop_state(self.c)
        self.c["loop"].setdefault("started_at", time.time())
        for f in self.c["ledger"]:
            if f.get("status") == "running":  # left by a stop or restart mid-test; the test runs again
                f.update(status="interrupted", error="the server stopped during this run")
        rearm_after_outage(self.c)
        loop = self.c["loop"]
        # Active time only: a project paused overnight (an outage, a Stop) must not reach the time ceiling while idle.
        loop["segment_started"] = time.time()
        try:
            await self.review()
            await self.plan()
            if not loop.get("stop_reason"):
                await self.rounds()
            self.c["dashboard"] = build_dashboard(self.c)
            await self.thesis()
            loop["phase"] = "done"
        finally:
            loop["active_s"] = active_seconds(loop)
            loop.pop("segment_started", None)
            self.save()


__all__ = ["ResearchLoop", "init_loop_state"]
