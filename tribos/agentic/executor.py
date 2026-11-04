"""
Task-fetching unit and executor for a planned tool DAG (LLMCompiler, Kim et al., ICML 2024, arXiv:2312.04511).

Each node is dispatched as soon as every node it depends on has finished successfully; ready nodes run
concurrently on the event loop (bounded by TRIBOS_AGENT_PLAN_CONCURRENCY, default 4), each through
AgentState.call_tool so it is checkpointed, budget-charged, traced, stored under an agent.plan_execute.* key
and labelled with its purpose for the evidence block. References ("$n1.results.0.id", see plan_graph) are
filled in from the finished nodes' ToolResult.data just before a node runs. A node that references the output
of a failed or skipped node is skipped, and so are its own dependents; a dependency it does not reference only
orders it, so it runs once that node has finished either way. No model is involved here: as in LLMCompiler and
ReWOO (arXiv:2305.18323), observations go back to the planner only through the joiner (plan_execute.py).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Iterable
from typing import Any

from ..tools.arg_repair import adjustment_text
from .config import env_int
from .control import RunCancelled
from .plan_graph import (
    PlanGraph,
    PlanNode,
    RefError,
    canonical,
    refs_in,
    resolve_args,
    schema_problem,
    validated_inputs,
)

logger = logging.getLogger(__name__)

# Tool prefixes and the agent a reader knows them by (legacy names included: lithoscribe -> Archivon, vivarix -> Dynamis).
_TOOL_AGENTS = {
    "archivon": "Archivon", "lithoscribe": "Archivon", "axiom": "Axiom", "dynamis": "Dynamis", "vivarix": "Dynamis",
    "calcula": "Calcula", "analysis": "Calcula", "physis": "Physis", "websurfer": "Web search",
}


def tool_display_name(tool: str) -> str:
    """'lithoscribe_literature_synthesis' -> 'Archivon · literature synthesis'; unknown tools read as words."""
    prefix, _, rest = (tool or "").partition("_")
    agent = _TOOL_AGENTS.get(prefix.lower())
    if agent is None:
        return (tool or "tool").replace("_", " ")
    return f"{agent} · {rest.replace('_', ' ')}" if rest else agent

PHASE = "plan_execute"


def _explain_problem(problem: str, args: dict[str, Any]) -> str:
    """A schema problem in terms the planner can act on (an over-long script says how long it is and what to do)."""
    for key, value in args.items():
        if isinstance(value, str) and key in problem and "at most" in problem:
            hint = " Pass earlier results through `inputs` instead of pasting data into the code." if key == "code" else ""
            return f"{problem} (it is {len(value)} characters).{hint}"
    return problem


def _concurrency() -> int:
    return env_int("TRIBOS_AGENT_PLAN_CONCURRENCY", 4, 1, 16)


def _short_args(args: dict[str, Any], limit: int = 160) -> str:
    text = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class PlanExecutor:
    """Runs one PlanGraph round; `results` maps finished node ids (all rounds) to their ToolResult."""

    def __init__(
        self,
        state: Any,
        *,
        phase: str = PHASE,
        results: dict[str, Any] | None = None,
        failed: set[str] | None = None,
        prior_calls: Iterable[tuple[str, dict[str, Any]]] | None = None,
        concurrency: int | None = None,
    ) -> None:
        self.state = state
        self.phase = phase
        self.results: dict[str, Any] = results if results is not None else {}
        self.failed: set[str] = failed if failed is not None else set()
        self.seen_calls: set[tuple[str, str]] = {(t, canonical(a)) for t, a in (prior_calls or [])}
        self.concurrency = max(1, int(concurrency or _concurrency()))
        self.dispatch_log: list[str] = []  # node ids in dispatch order (tests and the artifact use it)
        self.finish_log: list[str] = []
        self.known_ids: set[str] = set(self.results) | set(self.failed)

    async def _node_step(self, node: PlanNode, status: str, text: str) -> None:
        title = tool_display_name(node.tool) + (f": {node.purpose}" if node.purpose else "")
        await self.state.step(
            f"agent_node_{node.id}",
            title[:160],
            text,
            status=status,
            agent="Planner",
            node_id=node.id,
            tool=node.tool,
            depends_on=list(node.depends_on),
        )

    async def _skip(self, node: PlanNode, reason: str) -> None:
        node.status = "skipped"
        node.error = reason[:300]
        self.failed.add(node.id)
        await self._node_step(node, "skipped", reason)

    def _resolve(self, node: PlanNode) -> Any:
        """Resolved arguments. A reference that came back empty, or an argument the planner left blank for the run to
        fill (plan_graph fill_from_run), has no stand-in: RefError, so the node is skipped rather than run with an
        invented value."""
        args = resolve_args(node.args, self.results, known=self.known_ids)
        blank = [k for k in getattr(node, "fill_from_run", []) or [] if not isinstance(args, dict) or k not in args]
        if blank:
            raise RefError(f"the planner left {', '.join(blank)} blank and no earlier step supplies it")
        return self._wire_script_inputs(node, args)

    def _wire_script_inputs(self, node: PlanNode, args: Any) -> Any:
        """A script that reads `inputs` but was given none gets the results of the steps it depends on.

        Live run: "q4: disjoint rational intervals" read inputs['roots'] from the root-finding step, but the planner
        passed no `inputs` argument, so the script stopped with NameError: name 'inputs' is not defined. The upstream
        scripts' `result` values are merged in (keyed by their own names, and by step id), which is what such code
        expects."""
        if node.tool not in ("calcula_run_python", "analysis_run_python") or not isinstance(args, dict):
            return args
        if args.get("inputs") or not re.search(r"\binputs\b", str(args.get("code") or "")):
            return args
        wired: dict[str, Any] = {}
        for dep in node.depends_on:
            res = self.results.get(dep)
            data = getattr(res, "data", None) if res is not None else None
            value = data.get("result") if isinstance(data, dict) else None
            if value is None:
                continue
            wired[dep] = value
            if isinstance(value, dict):
                for key, item in value.items():
                    wired.setdefault(str(key), item)
        return {**args, "inputs": wired} if wired else args

    async def _run_node(self, node: PlanNode) -> None:
        t0 = time.perf_counter()
        state = self.state
        try:
            args = self._resolve(node)
        except RefError as exc:
            # The step it builds on returned nothing usable: nothing failed, the step just has no input, so it is
            # skipped rather than shown as an error.
            node.status, node.error = "skipped", f"skipped: an earlier step gave it no input ({exc})"
            node.seconds = round(time.perf_counter() - t0, 3)
            return
        node.resolved_args = args if isinstance(args, dict) else dict(node.args)
        call_args = node.resolved_args
        entry = state.registry.get_entry(node.tool) if state.registry is not None else None
        inputs = validated_inputs(entry, call_args) if entry is not None else None
        if entry is not None and inputs is None:
            # The arguments as they will be sent (references filled in) do not fit the tool's schema, even after the
            # registry's own repairs: nothing is dispatched, and the planner sees why in the joiner's observations.
            problem = schema_problem(entry, call_args, set()) or "the arguments do not match the tool's schema"
            node.status, node.error = "error", f"rejected before dispatch: {_explain_problem(problem, call_args)}"[:300]
            node.seconds = round(time.perf_counter() - t0, 3)
            return
        if inputs is not None:
            sig = (node.tool, canonical(inputs))
            if sig in self.seen_calls:
                node.status, node.error = "skipped", "an identical call was already made this turn"
                node.seconds = round(time.perf_counter() - t0, 3)
                return
            self.seen_calls.add(sig)
        key = state.next_key(self.phase, node.tool)
        call = state.call_tool(node.tool, phase=self.phase, purpose=node.purpose or f"plan node {node.id}", key=key, **call_args)
        if node.timeout_s:
            # The node's own deadline. A tool that enforces a timeout argument itself gets a little grace so its own
            # timeout reports first; any other tool is stopped at the deadline.
            grace = 5.0 if any(k in call_args for k in ("timeout_s", "timeout", "timeout_seconds")) else 0.0
            try:
                res = await asyncio.wait_for(call, timeout=float(node.timeout_s) + grace)
            except TimeoutError:
                node.result_key = key
                node.status, node.error = "error", f"timed out after the step deadline of {node.timeout_s:g} s"
                node.seconds = round(time.perf_counter() - t0, 3)
                return
        else:
            res = await call
        node.result_key = key
        node.seconds = round(time.perf_counter() - t0, 3)
        adjusted = (getattr(res, "metadata", None) or {}).get("arguments_adjusted") or []
        if isinstance(adjusted, list):
            node.adjusted = list(dict.fromkeys([*node.adjusted, *(str(a) for a in adjusted)]))
        if getattr(res, "success", False):
            node.status = "done"
            self.results[node.id] = res
        else:
            node.status = "error"
            node.error = str(getattr(res, "error", "") or "tool call failed")[:300]

    async def run(self, graph: PlanGraph) -> PlanGraph:
        pending: dict[str, PlanNode] = {n.id: n for n in graph.nodes if n.status == "pending"}
        self.known_ids = set(self.results) | set(self.failed) | set(graph.ids())
        order = {n.id: i for i, n in enumerate(graph.nodes)}
        running: dict[asyncio.Task[None], PlanNode] = {}
        state = self.state
        try:
            while pending or running:
                # Skip every pending node that uses the output of a failed or skipped node (transitively). A dependency
                # the node does not reference only orders it ("solve the problem, then check the inequality"): the node
                # runs once that dependency has finished, whatever its outcome, since it needs nothing from it.
                changed = True
                while changed:
                    changed = False
                    for nid, node in list(pending.items()):
                        needed = refs_in(node.args, self.known_ids)
                        bad = [d for d in node.depends_on if d in self.failed and d in needed]
                        if bad:
                            del pending[nid]
                            await self._skip(node, f"skipped: dependency {', '.join(bad)} did not succeed")
                            changed = True

                ready = sorted(
                    (n for n in pending.values() if all(d in self.results or d in self.failed for d in n.depends_on)),
                    key=lambda n: order.get(n.id, 0),
                )
                for node in ready:
                    if len(running) >= self.concurrency:
                        break
                    state.control.checkpoint()
                    if state.budget.exhausted():
                        for nid, rest in list(pending.items()):
                            del pending[nid]
                            await self._skip(rest, f"skipped: {state.budget.exhausted_reason or 'agent budget used up'}")
                        break
                    del pending[node.id]
                    node.status = "running"
                    self.dispatch_log.append(node.id)
                    await self._node_step(node, "running", _short_args(node.args))  # planned args, refs shown as written
                    running[asyncio.ensure_future(self._run_node(node))] = node

                if not running:
                    # Nothing can start: whatever is left waits on a node that will never finish.
                    for nid, rest in list(pending.items()):
                        del pending[nid]
                        await self._skip(rest, "skipped: its dependencies could not run")
                    break

                done, _ = await asyncio.wait(list(running), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node = running.pop(task)
                    exc = task.exception()
                    if isinstance(exc, RunCancelled):
                        raise exc
                    if exc is not None:
                        node.status, node.error = "error", f"{type(exc).__name__}: {str(exc)[:200]}"
                        logger.warning("Plan node %s failed: %s", node.id, exc)
                    if node.status != "done":
                        self.failed.add(node.id)
                    self.finish_log.append(node.id)
                    adjusted = f" · {adjustment_text(node.adjusted)}" if node.adjusted else ""
                    if node.status == "done":
                        await self._node_step(node, "done", f"done in {node.seconds or 0:.1f}s{adjusted}")
                    elif node.status == "skipped":
                        await self._node_step(node, "skipped", node.error or "skipped")
                    else:
                        await self._node_step(node, "error", (node.error or "failed") + adjusted)
        finally:
            for task in running:
                task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)
        return graph


async def execute_plan(state: Any, graph: PlanGraph, **kwargs: Any) -> PlanExecutor:
    """Run graph's pending nodes; returns the executor (its results, failures and dispatch order)."""
    ex = PlanExecutor(state, **kwargs)
    await ex.run(graph)
    return ex


__all__ = ["PHASE", "PlanExecutor", "execute_plan"]
