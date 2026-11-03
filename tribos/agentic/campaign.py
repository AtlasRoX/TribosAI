"""
Long-running research projects ("campaigns"): one goal worked through a fixed sequence of stages, each stage one
background job (tribos.agentic.jobs), ending in a written report.

Pattern after AI-Scientist (Lu et al., 2024, arXiv:2408.06292) and Agent Laboratory (Schmidgall et al., 2025,
arXiv:2501.04227): literature review -> hypotheses -> experiments -> analysis -> write-up. Each stage is a full
orchestrator turn, so it gets the same tools, code execution, verification and citations as a chat question; the
stage prompt carries the goal and a bounded summary of every earlier stage.

Durability: a campaign is a JSON file. Each finished stage stores its answer and citations, so a campaign that
stops (server restart, failed stage, cancel) resumes at its first unfinished stage; finished stages are never
rerun. All stages share one thread id, so the stages read as one conversation in the chat history.

Running unattended:
- Ownership: the process driving a campaign records itself as `owner` (pid and process start time). Several
  server processes may share one store (two backends on one data dir); a campaign is driven by one owner at a
  time, claimed under a lock file, and only a campaign whose owner process is gone counts as interrupted.
- Auto-resume (`TRIBOS_CAMPAIGN_AUTO_RESUME`, on by default): at server start, campaigns interrupted by a stopped
  server continue on their own, at most MAX_AUTO_RESUMES times each (so a campaign that crashes the server
  cannot loop forever).
- Retries (`TRIBOS_CAMPAIGN_STAGE_RETRIES`, default 1): a failed stage is run again before the campaign stops.
- Queue (`TRIBOS_CAMPAIGN_MAX_ACTIVE`, default 1 per process): further campaigns wait as "queued" and start
  when a slot frees.

Location: `TRIBOS_CAMPAIGNS_DIR`, else `<jobs dir>/campaigns`.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .jobs import ACTIVE, JobError, JobManager, default_jobs_dir, get_job_manager

logger = logging.getLogger(__name__)

CAMPAIGN_ID_RE = re.compile(r"^cmp_[0-9a-f]{16}$")
STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "interrupted")
RUNNING = ("queued", "running")
MAX_GOAL_CHARS = 4000
MAX_AUTO_RESUMES = 3
_RETRY_BUSY_S = 20.0  # the user has too many jobs queued: try the stage again after this many seconds
_POLL_S = 15.0  # how often a driver checks its stage job, refreshes its heartbeat and looks for a cancel
_CLAIM_STALE_S = 30.0  # a claim lock file older than this was left by a crash


def _process_token() -> str:
    try:
        import psutil

        return f"{os.getpid()}:{round(psutil.Process().create_time(), 1)}"
    except Exception:  # noqa: BLE001
        return f"{os.getpid()}:0"


PROCESS_TOKEN = _process_token()


def owner_alive(owner: str | None) -> bool:
    """Whether the process recorded as a campaign's owner is still running (pid reuse ruled out by start time)."""
    if not owner:
        return False
    if owner == PROCESS_TOKEN:
        return True
    try:
        pid_s, _, ctime_s = owner.partition(":")
        import psutil

        proc = psutil.Process(int(pid_s))
        return float(ctime_s) == 0.0 or abs(proc.create_time() - float(ctime_s)) < 1.0
    except Exception:  # noqa: BLE001 - no such process, or psutil missing
        return False


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    prompt: str
    web_search: bool = True


STAGES: tuple[Stage, ...] = (
    Stage("review", "Literature review",
          "Stage 1 of 5 of a research project: the literature review. Do only this stage now; later stages run "
          "the computations and tests the goal asks for, so do not report them as missing.\n"
          "Survey what is known about the research goal: the main results, methods, open questions and the "
          "strongest sources. Separate what is proved from what is conjectured or heuristic, and cite every source."),
    Stage("hypotheses", "Hypotheses and plan",
          "Stage 2 of 5 of a research project: hypotheses and the test plan. Do only this stage now.\n"
          "Building on the literature review in your context, state two to four specific, testable hypotheses for "
          "the research goal. For each, give the exact test (which quantity to compute, with which method and "
          "parameters, or which statement to prove) and the result that would support or refute it."),
    Stage("experiments", "Experiments",
          "Stage 3 of 5 of a research project: the experiments. Run the tests now.\n"
          "Carry out the tests in the plan from your context for the research goal: write and run code for every "
          "computation, and attempt the proofs. Do not describe what could be done. Report exact numbers, "
          "parameters and code results, and say for each hypothesis whether the result supports, refutes or does "
          "not decide it."),
    Stage("analysis", "Analysis",
          "Stage 4 of 5 of a research project: critical analysis. Do only this stage now.\n"
          "Analyse the experimental results in your context for the research goal. Which hypotheses are "
          "supported, refuted or undecided? Check for errors, confounds and numerical artefacts, re-running a "
          "computation where a number looks doubtful. State the limitations and the most valuable next step."),
    Stage("report", "Report", web_search=False, prompt=(
          "Stage 5 of 5 of a research project: the report.")),
)
STAGE_KEYS = tuple(s.key for s in STAGES)


def _context_chars() -> int:
    from ..config.settings import get_int

    return get_int("TRIBOS_CAMPAIGN_CONTEXT_CHARS")


def _stage_retries() -> int:
    from ..config.settings import get_int

    return get_int("TRIBOS_CAMPAIGN_STAGE_RETRIES")


def _max_active() -> int:
    from ..config.settings import get_int

    return get_int("TRIBOS_CAMPAIGN_MAX_ACTIVE")


def _auto_resume() -> bool:
    from ..config.settings import get_bool

    return get_bool("TRIBOS_CAMPAIGN_AUTO_RESUME")


def default_campaigns_dir() -> str:
    return os.getenv("TRIBOS_CAMPAIGNS_DIR") or os.path.join(default_jobs_dir(), "campaigns")


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    para = cut.rfind("\n\n")
    return (cut[:para] if para > limit // 2 else cut).rstrip() + "\n[... shortened ...]"


_QUESTION_RE = re.compile(r"(?i)\b(?:reply with|which (?:one|system|dataset|option)|could you (?:clarify|specify)|"
                          r"please (?:clarify|specify)|do you mean)\b")


def looks_like_question(text: str) -> bool:
    """A short reply that asks the user something (the clarification step) instead of answering."""
    text = (text or "").strip()
    return bool(text) and len(text) < 1500 and (bool(_QUESTION_RE.search(text)) or text.endswith("?"))


def base_key(stage: dict[str, Any]) -> str:
    """The stage kind (review, ..., report) of a stage record; a continued round's records are keyed `kind@round`."""
    return str(stage.get("base") or stage["key"]).split("@", 1)[0]


def stage_message(campaign: dict[str, Any], index: int) -> str:
    """The question sent to the orchestrator for stage `index`: the stage instruction, the goal and, in a continued
    round, the follow-up instruction. The earlier stages go to stage_context, never into the question."""
    record = campaign["stages"][index]
    stage = STAGES_BY_KEY[base_key(record)]
    parts = [stage.prompt, "", f"Research goal: {campaign['goal']}"]
    if int(record.get("round") or 1) > 1:
        parts += ["", f"This is round {record['round']} of the project; the earlier rounds are in your context. "
                      f"Follow-up instruction: {record.get('instruction') or 'go deeper where the evidence is weakest.'}"]
    return "\n".join(parts)


def stage_thread_id(campaign: dict[str, Any], record: dict[str, Any]) -> str:
    """The thread one stage runs in: the project's conversation id plus the stage key (experiments@2 -> experiments_2)."""
    return f"{campaign['thread_id']}__{str(record['key']).replace('@', '_')}"


def stage_context(campaign: dict[str, Any], index: int) -> str:
    """What the earlier stages found, for stage `index`. Sent as the `research_context` agent option, which the
    orchestrator puts in the system prompt as delimited background: inside the question, the planners and parsers
    would read an earlier stage's equations or examples as part of the request."""
    record = campaign["stages"][index]
    limit = _context_chars() * (2 if base_key(record) == "report" else 1)
    parts = []
    for s in campaign["stages"][:index]:
        if s.get("status") == "succeeded" and (s.get("response") or "").strip():
            parts += [f"## {s['title']}", _clip(s["response"], limit), ""]
    return "\n".join(parts).strip()


STAGES_BY_KEY = {s.key: s for s in STAGES}
CONTINUE_STAGES = ("experiments", "analysis", "report")
MAX_ROUNDS = 10


def _merge_citations(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for s in stages:
        cites = s.get("citations") or {}
        entries = cites.get("entries") if isinstance(cites, dict) else None  # CitationMap.model_dump()
        for c in (entries or {}).values() if isinstance(entries, dict) else []:
            if not isinstance(c, dict):
                continue
            key = str(c.get("key") or c.get("url") or c.get("title") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(c)
    return out


def report_markdown(campaign: dict[str, Any]) -> str:
    """The downloadable record: the report stage first, then every earlier stage in full, then the sources."""
    if campaign.get("mode") == "loop":
        thesis = campaign.get("thesis") or {}
        if thesis.get("status") == "succeeded" and thesis.get("markdown"):
            return str(thesis["markdown"])
        lines = [f"# {campaign.get('title') or 'Research project'}", "", f"Goal: {campaign['goal']}", "",
                 f"Status: {campaign['status']} · the thesis is not written yet.", ""]
        from .research.ledger import finding_line

        lines += [f"- {finding_line(f)}" for f in campaign.get("ledger") or []]
        return "\n".join(lines).rstrip() + "\n"
    stages = campaign.get("stages") or []
    report = next((s for s in reversed(stages) if base_key(s) == "report" and s.get("status") == "succeeded"), None)
    lines = [f"# {campaign.get('title') or 'Research project'}", "",
             f"Goal: {campaign['goal']}", "",
             f"Status: {campaign['status']} · {sum(s.get('status') == 'succeeded' for s in stages)} of {len(stages)} stages done", ""]
    if report:
        lines += [report.get("response", "").strip(), ""]
    rest = [s for s in stages if s is not report and s.get("status") == "succeeded"]
    if rest:
        lines += ["---", "", "## Appendix: stage records", ""]
        for i, s in enumerate(rest, 1):
            lines += [f"### A{i}. {s['title']}", "", (s.get("response") or "").strip(), ""]
    sources = _merge_citations(stages)
    if sources:
        lines += ["## Sources", ""]
        for i, c in enumerate(sources, 1):
            title = str(c.get("title") or c.get("key") or c.get("url") or "source").strip()
            url = str(c.get("url") or "").strip()
            meta = ", ".join(str(c[k]) for k in ("authors", "journal", "year") if c.get(k))
            ref = f"[{title}]({url})" if url else title
            lines.append(f"{i}. {ref}" + (f". {meta}" if meta else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class CampaignStore:
    """One JSON file per campaign; writes go through a temp file and a rename, so a crash never leaves half a file."""

    def __init__(self, storage_dir: str | None = None) -> None:
        self.storage_dir = os.path.abspath(storage_dir or default_campaigns_dir())
        os.makedirs(self.storage_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, campaign_id: str) -> str:
        if not CAMPAIGN_ID_RE.match(campaign_id or ""):
            raise KeyError(campaign_id)
        return os.path.join(self.storage_dir, f"{campaign_id}.json")

    def get(self, campaign_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        try:
            with open(self._path(campaign_id), encoding="utf-8") as fh:
                data = json.load(fh)
        except (KeyError, OSError, ValueError):
            return None
        if user_id is not None and data.get("user_id") != user_id:
            return None
        return data

    def save(self, campaign: dict[str, Any]) -> None:
        campaign["updated_at"] = time.time()
        path = self._path(campaign["campaign_id"])
        tmp = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(campaign, fh, ensure_ascii=False, default=str)
            os.replace(tmp, path)

    def list(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for name in os.listdir(self.storage_dir):
            if name.endswith(".json"):
                c = self.get(name[:-5], user_id)
                if c is not None:
                    out.append(c)
        out.sort(key=lambda c: c.get("created_at", 0), reverse=True)
        return out[:limit]

    def delete(self, campaign_id: str, user_id: str) -> bool:
        if self.get(campaign_id, user_id) is None:
            return False
        with contextlib.suppress(OSError):
            os.remove(self._path(campaign_id))
        # A research-loop project's figures live beside it; they go with the project.
        files = os.path.realpath(os.path.join(self.storage_dir, f"{campaign_id}_files"))
        if os.path.dirname(files) == os.path.realpath(self.storage_dir) and os.path.isdir(files):
            import shutil

            shutil.rmtree(files, ignore_errors=True)
        return True

    def all_ids(self) -> builtins.list[str]:
        return [n[:-5] for n in os.listdir(self.storage_dir) if n.endswith(".json") and CAMPAIGN_ID_RE.match(n[:-5])]

    def mark_interrupted(self) -> builtins.list[str]:
        """Campaigns left queued or running by a process that is gone become interrupted; returns their ids.
        A campaign another live process is driving is left alone."""
        out = []
        for cid in self.all_ids():
            c = self.get(cid)
            if c and c.get("status") in RUNNING and not owner_alive(c.get("owner")):
                c["status"], c["error"] = "interrupted", "The server stopped while the project was running."
                c["owner"] = None
                for s in c["stages"]:
                    if s.get("status") == "running":
                        s["status"] = "interrupted"
                self.save(c)
                out.append(cid)
        return out

    @contextlib.contextmanager
    def _claim_lock(self, campaign_id: str) -> Any:
        """A cross-process lock: a lock file created exclusively (atomic on POSIX and Windows)."""
        path = os.path.join(self.storage_dir, f"{campaign_id}.claim")
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                with contextlib.suppress(OSError):
                    if time.time() - os.path.getmtime(path) > _CLAIM_STALE_S:
                        os.remove(path)  # left by a crash inside the lock
                        continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"campaign {campaign_id} is locked") from None
                time.sleep(0.05)
        try:
            os.close(fd)
            yield
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)

    def claim(self, campaign_id: str) -> dict[str, Any] | None:
        """Make this process the campaign's owner; None when another live process already drives it."""
        try:
            with self._claim_lock(campaign_id):
                c = self.get(campaign_id)
                if c is None:
                    return None
                owner = c.get("owner")
                if owner and owner != PROCESS_TOKEN and owner_alive(owner) and c.get("status") in RUNNING:
                    return None
                c["owner"], c["heartbeat_at"] = PROCESS_TOKEN, time.time()
                self.save(c)
                return c
        except TimeoutError:
            return None


REPORT_SYSTEM = (
    "You write the final report of a research project from what its stages established. Write it as a short paper "
    "in Markdown with these sections: Abstract, Background, Hypotheses, Methods, Results, Discussion (including "
    "limitations), Conclusion, References. Use only what the stages established: keep every number exact, give the "
    "method and parameters behind each result, mark which hypotheses were supported, refuted or left undecided, and "
    "cite sources by their [n] from the list given. Do not claim more than the evidence shows: a computation or "
    "simulation is evidence, not a proof, and an open problem stays open unless a stage proved it. Where a stage "
    "failed or did not run a test, say so plainly. Use LaTeX ($...$) for mathematics and Markdown tables for "
    "numeric results.")


async def write_with_model(system: str, user: str, model: str | None) -> str:
    """One model call (the synthesis model unless the project chose one) for the report stage."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from ..utils.llm.llm_factory import DEFAULT_ORCHESTRATOR_MODEL, get_llm

    name = model or os.getenv("TRIBOS_SYNTHESIS_MODEL", "").strip() or DEFAULT_ORCHESTRATOR_MODEL
    llm = get_llm(model_name=name)
    reply = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = getattr(reply, "content", reply)
    if isinstance(content, list):
        content = "".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _title(goal: str) -> str:
    """A short name: the first sentence, cut at a clause or word boundary near 70 characters."""
    first = re.split(r"(?<=[.?!])\s|\n", goal.strip(), maxsplit=1)[0].strip()
    if len(first) <= 70:
        return first
    head = first[:70]
    for sep in (", where ", " where ", ", which ", "; ", ": ", ", ", " in its ", " of the "):
        cut = head.rfind(sep)
        if cut >= 30:
            return head[:cut].rstrip(" ,;:")
    return head[: head.rfind(" ")].rstrip(" ,;:") + "…"


def _live_research_model(campaign: dict[str, Any]) -> Any:
    from .research import LiveModel

    return LiveModel(campaign.get("model"))


class CampaignManager:
    def __init__(self, store: CampaignStore | None = None, jobs: JobManager | None = None) -> None:
        self.store = store or CampaignStore()
        self._jobs = jobs
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._slots: asyncio.Semaphore | None = None
        self._slots_loop: asyncio.AbstractEventLoop | None = None
        self.interrupted = self.store.mark_interrupted()
        self.recovered = len(self.interrupted)
        self.report_writer: Callable[[str, str, str | None], Awaitable[str]] = write_with_model
        # The research loop's model (tests install a fake): campaign -> object with async text() and json().
        self.research_model: Callable[[dict[str, Any]], Any] = _live_research_model

    @property
    def jobs(self) -> JobManager:
        return self._jobs or get_job_manager()

    def _slot(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._slots is None or self._slots_loop is not loop:
            self._slots, self._slots_loop = asyncio.Semaphore(_max_active()), loop
        return self._slots

    def create(self, user_id: str, goal: str, *, model: str | None = None, project_id: str | None = None,
               effort_level: str = "high", stages: builtins.list[str] | None = None,
               web_search: bool = True, mode: str = "stages") -> dict[str, Any]:
        goal = (goal or "").strip()
        if not goal:
            raise JobError("A research project needs a goal", 422)
        if len(goal) > MAX_GOAL_CHARS:
            raise JobError(f"The goal is longer than {MAX_GOAL_CHARS} characters", 422)
        if mode == "loop":
            # The adaptive research loop (tribos.agentic.research): review, charter, rounds until a conclusion, thesis.
            from .research import init_loop_state, rough_estimate

            cid = f"cmp_{uuid.uuid4().hex[:16]}"
            now = time.time()
            campaign: dict[str, Any] = {
                "campaign_id": cid, "user_id": user_id, "goal": goal, "title": _title(goal), "status": "queued",
                "mode": "loop", "model": model, "project_id": project_id, "effort_level": effort_level,
                "web_search": web_search, "thread_id": f"thread_{cid}", "created_at": now, "updated_at": now,
                "finished_at": None, "error": None, "current_stage": None, "owner": PROCESS_TOKEN, "heartbeat_at": now,
                "auto_resumes": 0, "note": None, "stages": [],
            }
            init_loop_state(campaign)
            campaign["estimate"] = rough_estimate(goal)
            self.store.save(campaign)
            return campaign
        keys = [k for k in STAGE_KEYS if not stages or k in stages]
        unknown = sorted(set(stages or []) - set(STAGE_KEYS))
        if unknown or not keys:
            raise JobError(f"Unknown stages {unknown}; choose from {list(STAGE_KEYS)}", 422)
        cid = f"cmp_{uuid.uuid4().hex[:16]}"
        now = time.time()
        campaign = {
            "campaign_id": cid, "user_id": user_id, "goal": goal, "title": _title(goal), "status": "queued",
            "model": model, "project_id": project_id, "effort_level": effort_level, "web_search": web_search,
            "thread_id": f"thread_{cid}", "created_at": now, "updated_at": now, "finished_at": None, "error": None,
            "current_stage": None, "owner": PROCESS_TOKEN, "heartbeat_at": now, "auto_resumes": 0, "note": None,
            "stages": [{"key": k, "title": STAGES_BY_KEY[k].title, "status": "pending", "job_id": None,
                        "started_at": None, "finished_at": None, "response": "", "citations": {}, "error": None,
                        "attempts": 0} for k in keys],
        }
        self.store.save(campaign)
        return campaign

    def start(self, campaign_id: str) -> None:
        task = self._tasks.get(campaign_id)
        if task is not None and not task.done():
            return
        self._tasks[campaign_id] = asyncio.get_running_loop().create_task(self._drive(campaign_id))

    def autostart(self) -> builtins.list[str]:
        """At server start: continue the campaigns a stopped server interrupted (TRIBOS_CAMPAIGN_AUTO_RESUME),
        each at most MAX_AUTO_RESUMES times. Call inside the running event loop. Returns the resumed ids."""
        if not _auto_resume():
            return []
        resumed = []
        for cid in self.interrupted:
            c = self.store.get(cid)
            if c is None or c.get("status") != "interrupted":
                continue
            if int(c.get("auto_resumes") or 0) >= MAX_AUTO_RESUMES:
                c["note"] = f"Not resumed automatically after {MAX_AUTO_RESUMES} restarts; press Resume to continue."
                self.store.save(c)
                continue
            self._reset_for_run(c)
            c["auto_resumes"] = int(c.get("auto_resumes") or 0) + 1
            c["note"] = "Resumed automatically after a server restart."
            self.store.save(c)
            self.start(cid)
            resumed.append(cid)
        self.interrupted = []
        if resumed:
            logger.info("Research projects resumed after restart: %s", ", ".join(resumed))
        return resumed

    async def submit(self, user_id: str, goal: str, **kwargs: Any) -> dict[str, Any]:
        campaign = self.create(user_id, goal, **kwargs)
        self.start(campaign["campaign_id"])
        return campaign

    def _request(self, campaign: dict[str, Any], index: int) -> dict[str, Any]:
        record = campaign["stages"][index]
        stage = STAGES_BY_KEY[base_key(record)]
        options: dict[str, Any] = {
            "effort_level": campaign.get("effort_level") or "high",
            # Nobody is there to answer a clarifying question in a background stage.
            "allow_clarification": False,
            "research_context": stage_context(campaign, index),
        }
        if stage.key == "experiments":
            options["codeact"] = "always"  # the experiments are run as code, never only described
        req = {"message": stage_message(campaign, index),
               "display_message": f"[Research project · {record['title']}] {campaign['title']}",
               # Each stage is its own thread: a shared thread's memory carried one stage's subject into the next
               # ("follow-up: subject lorenz from the previous question"). The stages' findings go in research_context.
               "thread_id": stage_thread_id(campaign, record), "model": campaign.get("model"),
               "enable_web_search": bool(campaign.get("web_search", True) and stage.web_search),
               "project_id": campaign.get("project_id"),
               "agent_options": options}
        return {k: v for k, v in req.items() if v is not None}

    def _cancelled_elsewhere(self, campaign: dict[str, Any]) -> bool:
        """A cancel made through another server process (or this one) shows up in the stored record."""
        fresh = self.store.get(campaign["campaign_id"])
        return fresh is None or fresh.get("status") == "cancelled"

    def _beat(self, campaign: dict[str, Any]) -> None:
        campaign["heartbeat_at"] = time.time()
        campaign["owner"] = PROCESS_TOKEN
        self.store.save(campaign)

    async def _run_stage(self, campaign: dict[str, Any], index: int) -> str:
        """Submit the stage job and wait for it; returns the stage's final status."""
        stage = campaign["stages"][index]
        uid = campaign["user_id"]
        while True:
            if self._cancelled_elsewhere(campaign):
                return "cancelled"
            try:
                job = await self.jobs.submit(uid, self._request(campaign, index), origin="campaign")
                break
            except JobError as exc:
                if exc.status_code != 429:
                    raise
                stage["error"] = "waiting for a free job slot"
                self._beat(campaign)
                await asyncio.sleep(_RETRY_BUSY_S)
        stage.update(status="running", job_id=job["job_id"], started_at=time.time(), finished_at=None, error=None,
                     attempts=int(stage.get("attempts") or 0) + 1)
        campaign.update(status="running", current_stage=stage["key"])
        self._beat(campaign)
        while True:
            row = await self.jobs.wait(job["job_id"], timeout=_POLL_S)
            if row is None:
                stage.update(status="failed", error="the stage job disappeared", finished_at=time.time())
                return "failed"
            if row["status"] not in ACTIVE:
                break
            if self._cancelled_elsewhere(campaign):
                with contextlib.suppress(Exception):
                    await self.jobs.cancel(job["job_id"], uid, reason="research project cancelled")
                stage.update(status="cancelled", finished_at=time.time())
                return "cancelled"
            self._beat(campaign)
        result = row.get("result") or {}
        status = row["status"]
        stage["finished_at"] = time.time()
        if status == "succeeded" and looks_like_question(str(result.get("response") or "")):
            stage.update(status="failed", error="the stage asked a question instead of doing the work")
        elif status == "succeeded" and str(result.get("response") or "").strip():
            stage.update(status="succeeded", response=result["response"], citations=result.get("citations") or {},
                         error=None)
        else:
            stage.update(status="failed" if status == "succeeded" else status,
                         error=row.get("error") or ("the stage produced no answer" if status == "succeeded" else status))
        self.store.save(campaign)
        return str(stage["status"])

    async def _run_report(self, campaign: dict[str, Any], index: int) -> str:
        """Write the report from the stages' findings with one model call. A research run would treat the request
        as a new question (searching, computing, compressing the answer); the report only has to write up what the
        stages established."""
        stage = campaign["stages"][index]
        stage.update(status="running", job_id=None, started_at=time.time(), finished_at=None, error=None,
                     attempts=int(stage.get("attempts") or 0) + 1)
        campaign.update(status="running", current_stage=stage["key"])
        self._beat(campaign)
        sources = _merge_citations(campaign["stages"][:index])
        refs = "\n".join(f"[{i}] {c.get('title') or c.get('key')} {c.get('url') or ''}".strip()
                         for i, c in enumerate(sources[:60], 1))
        record = campaign["stages"][index]
        follow = (f"\nThis report closes round {record['round']}; its follow-up instruction was: "
                  f"{record.get('instruction')}\n") if int(record.get("round") or 1) > 1 else ""
        user = (f"Research goal:\n{campaign['goal']}\n{follow}\nWhat the stages established:\n\n"
                f"{stage_context(campaign, index)}\n\nSources the stages cited:\n{refs or '(none)'}")
        try:
            text = await asyncio.wait_for(self.report_writer(REPORT_SYSTEM, user, campaign.get("model")), 600)
        except Exception as exc:  # noqa: BLE001
            stage.update(status="failed", error=f"the report could not be written ({type(exc).__name__})",
                         finished_at=time.time())
            self.store.save(campaign)
            return "failed"
        stage["finished_at"] = time.time()
        if text.strip():
            stage.update(status="succeeded", response=text.strip(),
                         citations={"entries": {str(c.get("key") or i): c for i, c in enumerate(sources)}})
        else:
            stage.update(status="failed", error="the report came back empty")
        self.store.save(campaign)
        return str(stage["status"])

    async def _wait_for_slot(self, campaign: dict[str, Any]) -> bool:
        """Queue behind the running campaigns of this process; False when the campaign was cancelled meanwhile."""
        slots = self._slot()
        while True:
            try:
                await asyncio.wait_for(slots.acquire(), timeout=_POLL_S)
                return True
            except TimeoutError:
                if self._cancelled_elsewhere(campaign):
                    return False
                campaign["note"] = "Queued: starts when the running research project finishes."
                self._beat(campaign)

    def _finish_cancelled(self, campaign_id: str, campaign: dict[str, Any], index: int) -> dict[str, Any]:
        fresh = self.store.get(campaign_id) or campaign
        if index < len(fresh["stages"]) and fresh["stages"][index].get("status") == "running":
            fresh["stages"][index]["status"] = "cancelled"
        fresh.update(status="cancelled", error=fresh.get("error") or "cancelled by the user")
        return fresh

    async def _drive(self, campaign_id: str) -> None:
        campaign = self.store.claim(campaign_id)
        if campaign is None or campaign.get("status") == "cancelled":
            return  # gone, cancelled, or another live server process is driving it
        if not await self._wait_for_slot(campaign):
            return
        try:
            campaign = self.store.get(campaign_id) or campaign
            if campaign.get("status") == "cancelled":
                return
            if str(campaign.get("note") or "").startswith("Queued"):
                campaign["note"] = None
            campaign.update(status="running", error=None, finished_at=None)
            self._beat(campaign)
            if campaign.get("mode") == "loop":
                campaign = await self._drive_loop(campaign)
            else:
                campaign = await self._drive_stages(campaign_id, campaign)
        except asyncio.CancelledError:
            fresh = self.store.get(campaign_id) or campaign
            if fresh.get("status") != "cancelled":
                fresh.update(status="interrupted", error="The server stopped while the project was running.")
            for s in fresh["stages"]:
                if s.get("status") == "running":
                    s["status"] = fresh["status"]
            fresh.update(finished_at=time.time(), owner=None)
            self.store.save(fresh)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Campaign %s failed", campaign_id, exc_info=True)
            campaign.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            self._slot().release()
        campaign.update(finished_at=time.time(), owner=None)
        self.store.save(campaign)

    async def _drive_stages(self, campaign_id: str, campaign: dict[str, Any]) -> dict[str, Any]:
        """The fixed five-stage pipeline (mode "stages")."""
        retries = _stage_retries()
        for i, stage in enumerate(campaign["stages"]):
            if stage.get("status") == "succeeded":
                continue
            stage["attempts"] = 0
            run_once = self._run_report if base_key(stage) == "report" else self._run_stage
            outcome = await run_once(campaign, i)
            while outcome == "failed" and int(stage.get("attempts") or 0) <= retries:
                stage["error"] = f"retrying after: {stage.get('error') or 'failure'}"
                self._beat(campaign)
                outcome = await run_once(campaign, i)
            if outcome == "succeeded":
                continue
            if outcome == "cancelled" or self._cancelled_elsewhere(campaign):
                campaign = self._finish_cancelled(campaign_id, campaign, i)
            else:
                campaign.update(status="failed", error=f"{stage['title']}: {stage.get('error') or outcome}")
            break
        else:
            campaign.update(status="succeeded", current_stage=None, error=None)
        return campaign

    async def _drive_loop(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """The adaptive research loop (mode "loop"); see tribos.agentic.research."""
        from .research import ResearchLoop

        await ResearchLoop(self, campaign, self.research_model(campaign)).run()
        if self._cancelled_elsewhere(campaign):
            return self._finish_cancelled(campaign["campaign_id"], campaign, len(campaign["stages"]))
        campaign.update(status="succeeded", current_stage=None, error=None)
        campaign["estimate"] = {"remaining_s": 0, "low_s": 0, "high_s": 0, "basis": "finished", "updated_at": time.time()}
        return campaign

    # Public lifecycle ---------------------------------------------------------------------------------------
    def get(self, campaign_id: str, user_id: str) -> dict[str, Any] | None:
        return self.store.get(campaign_id, user_id)

    def list(self, user_id: str, limit: int = 50) -> builtins.list[dict[str, Any]]:
        return self.store.list(user_id, limit)

    async def cancel(self, campaign_id: str, user_id: str) -> dict[str, Any] | None:
        campaign = self.store.get(campaign_id, user_id)
        if campaign is None:
            return None
        if campaign["status"] not in RUNNING:
            return campaign
        campaign.update(status="cancelled", error="cancelled by the user", finished_at=time.time(), note=None)
        for s in campaign["stages"]:
            if s.get("status") == "running":
                s["status"] = "cancelled"
                if s.get("job_id"):
                    with contextlib.suppress(Exception):
                        await self.jobs.cancel(s["job_id"], user_id, reason="research project cancelled")
        self.store.save(campaign)
        task = self._tasks.pop(campaign_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # A driver in another server process sees the stored status within one poll and stops its stage job.
        return self.store.get(campaign_id, user_id)

    @staticmethod
    def _reset_for_run(campaign: dict[str, Any]) -> None:
        for s in campaign["stages"]:
            if s.get("status") != "succeeded":
                s.update(status="pending", error=None, started_at=None, finished_at=None, job_id=None, attempts=0)
        if campaign.get("mode") == "loop":
            for t in (campaign.get("charter") or {}).get("tests") or []:
                if t.get("status") == "running":
                    t["status"] = "pending"
            if (campaign.get("thesis") or {}).get("status") == "failed":
                campaign["thesis"] = {"status": "pending"}
        campaign.update(status="queued", error=None, finished_at=None)

    async def resume(self, campaign_id: str, user_id: str) -> dict[str, Any] | None:
        campaign = self.store.get(campaign_id, user_id)
        if campaign is None:
            return None
        local = campaign_id in self._tasks and not self._tasks[campaign_id].done()
        if campaign["status"] in RUNNING and (local or owner_alive(campaign.get("owner"))):
            return campaign
        if campaign["status"] == "succeeded":
            raise JobError("This project already finished", 409)
        self._reset_for_run(campaign)
        campaign["note"] = None
        self.store.save(campaign)
        self.start(campaign_id)
        return campaign

    async def continue_(self, campaign_id: str, user_id: str, instruction: str,
                        stages: builtins.list[str] | None = None) -> dict[str, Any] | None:
        """Add a round to a finished, failed, cancelled or interrupted project: the chosen stages (default
        experiments -> analysis -> report) run again with a follow-up instruction and everything found so far."""
        campaign = self.store.get(campaign_id, user_id)
        if campaign is None:
            return None
        if campaign["status"] in RUNNING:
            raise JobError("This project is still running; continue it when it stops", 409)
        instruction = (instruction or "").strip()
        if not instruction:
            raise JobError("Say what the next round should do", 422)
        if len(instruction) > MAX_GOAL_CHARS:
            raise JobError(f"The instruction is longer than {MAX_GOAL_CHARS} characters", 422)
        if campaign.get("mode") == "loop":
            # The instruction becomes a deliverable; the loop plans tests for it, runs rounds until it is settled, and
            # writes the thesis again.
            if not campaign.get("charter"):
                raise JobError("This project has no plan yet; resume it first", 409)
            loop = campaign.setdefault("loop", {})
            loop.setdefault("instructions", []).append(instruction)
            loop.update(replan=True, stop_reason=None, phase="testing")
            campaign["thesis"] = {"status": "pending"}
            self._reset_for_run(campaign)
            campaign["note"] = None
            self.store.save(campaign)
            self.start(campaign_id)
            return campaign
        kinds = [k for k in STAGE_KEYS if k in (stages or CONTINUE_STAGES)]
        unknown = sorted(set(stages or []) - set(STAGE_KEYS))
        if unknown or not kinds:
            raise JobError(f"Unknown stages {unknown}; choose from {list(STAGE_KEYS)}", 422)
        rnd = max(int(s.get("round") or 1) for s in campaign["stages"]) + 1
        if rnd > MAX_ROUNDS:
            raise JobError(f"A project can have at most {MAX_ROUNDS} rounds; start a new project", 409)
        for k in kinds:
            campaign["stages"].append({
                "key": f"{k}@{rnd}", "base": k, "round": rnd, "instruction": instruction,
                "title": f"{STAGES_BY_KEY[k].title} (round {rnd})", "status": "pending", "job_id": None,
                "started_at": None, "finished_at": None, "response": "", "citations": {}, "error": None, "attempts": 0})
        self._reset_for_run(campaign)
        campaign.update(note=None, rounds=rnd)  # the round row shows its instruction
        self.store.save(campaign)
        self.start(campaign_id)
        return campaign

    async def delete(self, campaign_id: str, user_id: str) -> bool:
        campaign = self.store.get(campaign_id, user_id)
        if campaign is None:
            return False
        if campaign["status"] in RUNNING:
            await self.cancel(campaign_id, user_id)
        return self.store.delete(campaign_id, user_id)


_MANAGER: CampaignManager | None = None
_PINNED = False
_MANAGER_LOCK = threading.Lock()


def get_campaign_manager() -> CampaignManager:
    """Process-wide manager; a new one when the campaigns directory changes, unless one was installed with
    set_campaign_manager."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None and _PINNED:
            return _MANAGER
        path = os.path.abspath(default_campaigns_dir())
        if _MANAGER is None or _MANAGER.store.storage_dir != path:
            _MANAGER = CampaignManager(CampaignStore(path))
        return _MANAGER


def set_campaign_manager(manager: CampaignManager | None) -> None:
    """Install a manager (tests: injected jobs, store and report writer); None restores the default."""
    global _MANAGER, _PINNED
    with _MANAGER_LOCK:
        _MANAGER = manager
        _PINNED = manager is not None


def public_campaign(campaign: dict[str, Any], *, full: bool = True) -> dict[str, Any]:
    out = {k: v for k, v in campaign.items() if k != "user_id"}
    out["title"] = _title(str(out.get("goal") or "")) or out.get("title")  # projects stored before short titles
    if not full:
        out["stages"] = [{k: v for k, v in s.items() if k not in ("response", "citations")} for s in out["stages"]]
    if out.get("mode") == "loop":
        thesis = dict(out.get("thesis") or {})
        # The thesis text is served by /thesis; the polled record carries its status, outline and figures.
        thesis["chapters"] = [{"key": c.get("key"), "title": c.get("title")} for c in thesis.get("chapters") or []]
        thesis.pop("markdown", None)
        out["thesis"] = thesis
        if not full:
            charter = out.get("charter") or {}
            out["summary"] = {
                "deliverables": len(charter.get("deliverables") or []),
                "done": sum(1 for d in charter.get("deliverables") or [] if d.get("status") in ("done", "infeasible")),
                "tests": len(charter.get("tests") or []), "findings": len(out.get("ledger") or []),
                "rounds": len(out.get("rounds") or []), "phase": (out.get("loop") or {}).get("phase")}
            for k in ("charter", "ledger", "dashboard", "activity", "review", "rounds"):
                out.pop(k, None)
    return out


__all__ = [
    "CAMPAIGN_ID_RE",
    "STAGES",
    "STAGE_KEYS",
    "CampaignManager",
    "CampaignStore",
    "get_campaign_manager",
    "public_campaign",
    "report_markdown",
    "set_campaign_manager",
    "stage_message",
]
