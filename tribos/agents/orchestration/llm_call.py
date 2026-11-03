"""
One plain model call from a pipeline stage: the run's synthesis model, its API key, the run budget charged.

Used by the stages that hold a conversation with the model outside drafting: the code-writing loop (codeact),
construct mode, the proof loop and the reviser.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from .context import RunContext, orchestrator_module

DEFAULT_TIMEOUT_S = 240.0


def stage_model(run: RunContext) -> str:
    return os.getenv("TRIBOS_SYNTHESIS_MODEL", "").strip() or run.synthesis_model or run.model_name


def budget_admits(run: RunContext, calls: int) -> bool:
    """False when the run budget cannot admit `calls` more model calls (no budget: always admitted)."""
    budget = getattr(run.agent_state, "budget", None) if run.agent_state is not None else None
    return budget is None or budget.max_llm_calls - budget.llm_calls >= calls


def _content(reply: Any) -> str:
    content = getattr(reply, "content", reply)
    if isinstance(content, list):  # content blocks
        content = "".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)
    return str(content or "").strip()


async def ask(run: RunContext, system: str, messages: list[tuple[str, str]] | str, *,
              timeout_s: float = DEFAULT_TIMEOUT_S, model: str | None = None) -> str:
    """The model's reply to `messages` ([(role, text)] with role "user" or "assistant", or one user text)."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    ao = orchestrator_module()
    name = model or stage_model(run)
    llm = ao.get_llm(model_name=name, api_key=run.api_key, **ao._edit_llm_kwargs(name))
    turns = [("user", messages)] if isinstance(messages, str) else messages
    chat: list[Any] = [SystemMessage(content=system)]
    chat += [AIMessage(content=t) if role == "assistant" else HumanMessage(content=t) for role, t in turns]
    reply = await asyncio.wait_for(llm.ainvoke(chat), timeout_s)
    budget = getattr(run.agent_state, "budget", None) if run.agent_state is not None else None
    if budget is not None:
        budget.llm_calls += 1
    return _content(reply)


__all__ = ["ask", "budget_admits", "stage_model"]
