"""
Offline fakes for agentic tests: a scripted chat model routed by phase marker, and an orchestrator wired to
the recording registry with that model.

Contract: every agentic phase's system prompt starts with "[phase:<key>]" (e.g. "[phase:plan_execute]").
Calls without a marker are the answer synthesis (or the Reflexion correction, which contains
"<audit_defects>" in the user turn). A responder value is a string or fn(system, user) -> str.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from tests.fakes import ExtraTools, make_offline_orchestrator
from tribos.agents import authoritative_orchestrator as orch_module

Responder = str | Callable[[str, str], str]

_PHASE_RE = re.compile(r"^\s*\[phase:([a-z0-9_]+)\]")

DEFAULT_SYNTHESIS = (
    "## Result\n\n$x = 2$\n\n## Derivation\n\nDerived from equation.\n\n## Verification\n\nVerified by computation.\n\n## References\n\n[Vaswani et al., 2017 | arXiv:1706.03762]"
)


def phase_of(system: str, user: str = "") -> str:
    m = _PHASE_RE.match(system or "")
    if m:
        return m.group(1)
    if "<audit_defects>" in (user or ""):
        return "correction"
    return "synthesis"


class ScriptedLLM:
    """Chat model stand-in: ainvoke only, so astream_with_reasoning uses its ainvoke fallback."""

    def __init__(self, responses: dict[str, Responder], default_synthesis: str = DEFAULT_SYNTHESIS) -> None:
        self.responses = dict(responses)
        self.default_synthesis = default_synthesis
        self.calls: list[tuple[str, str, str]] = []  # (phase, system, user)
        self.temperature = 0.0

    def respond(self, system: str, user: str) -> str:
        phase = phase_of(system, user)
        self.calls.append((phase, system, user))
        value = self.responses.get(phase)
        if value is None:
            if phase in ("synthesis", "correction"):
                return self.default_synthesis
            return "{}"
        return value(system, user) if callable(value) else value

    async def ainvoke(self, messages: Any, *args: Any, **kwargs: Any) -> AIMessage:
        system = str(getattr(messages[0], "content", "")) if messages else ""
        user = str(getattr(messages[-1], "content", "")) if messages else ""
        return AIMessage(content=self.respond(system, user))

    def phases(self) -> list[str]:
        return [c[0] for c in self.calls]

    def prompts(self, phase: str) -> list[str]:
        return [c[2] for c in self.calls if c[0] == phase]


def make_agentic_orchestrator(
    monkeypatch: Any,
    tmp_path: Any,
    responses: dict[str, Responder] | None = None,
    extra_tools: ExtraTools | None = None,
    default_synthesis: str = DEFAULT_SYNTHESIS,
) -> tuple[Any, list[tuple[str, dict[str, Any]]], ScriptedLLM]:
    """Offline orchestrator whose model is a ScriptedLLM (use framework='agentic-plan-execute' etc.)."""
    orch, calls = make_offline_orchestrator(monkeypatch, tmp_path, extra_tools=extra_tools)
    llm = ScriptedLLM(responses or {}, default_synthesis=default_synthesis)
    monkeypatch.setattr(orch_module, "get_llm", lambda *a, **k: llm)
    monkeypatch.setenv("TRIBOS_PLANNER", "off")  # the query planner model stays out of agentic tests
    return orch, calls, llm


async def collect_events(orch: Any, **kwargs: Any) -> tuple[Any, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []

    async def cb(ev: dict[str, Any]) -> None:
        events.append(ev)

    res = await orch.execute_inquiry(event_callback=cb, **kwargs)
    return res, events
