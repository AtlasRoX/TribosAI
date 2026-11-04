"""
Model access for the research loop: text and JSON calls with the right reasoning effort and room for the answer.

A reasoning model's hidden thinking counts against max_tokens. When it runs out, the provider returns an empty
reply labelled "stop" (the Q.7 lesson), so every call gets generous room and an empty reply is retried once at a
lower effort. Tests inject a fake with the same two methods (`text`, `json`).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)

Messages = list[tuple[str, str]]  # (role, text), role "user" or "assistant"
_LOWER = {"xhigh": "high", "high": "medium", "medium": "low", "low": "minimal", "minimal": "minimal"}


class ResearchModel(Protocol):
    async def text(self, system: str, user: str | Messages, *, effort: str = "medium",
                   max_tokens: int = 32000) -> str: ...

    async def json(self, system: str, user: str, *, effort: str = "medium", max_tokens: int = 32000) -> Any: ...


class EmptyReply(RuntimeError):
    pass


class LiveModel:
    """The configured chat model (the project's model, else the synthesis model, else the default)."""

    def __init__(self, model_name: str | None = None, api_key: str | None = None) -> None:
        from ...utils.llm.llm_factory import DEFAULT_ORCHESTRATOR_MODEL

        self.model_name = model_name or os.getenv("TRIBOS_SYNTHESIS_MODEL", "").strip() or DEFAULT_ORCHESTRATOR_MODEL
        self.api_key = api_key

    async def _once(self, system: str, user: str | Messages, effort: str, max_tokens: int) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from ...utils.llm.llm_factory import astream_with_reasoning, get_llm

        # A research call can think for minutes before its first byte (a proof, a formalisation): the read timeout
        # must allow that silence, or the call ends in ReadTimeout with nothing (seen on Lean formalisations).
        llm = get_llm(model_name=self.model_name, api_key=self.api_key, streaming=True, reasoning_effort=effort,
                      max_tokens=max_tokens, timeout=600)
        msgs: list[Any] = [SystemMessage(content=system)]
        if isinstance(user, str):
            msgs.append(HumanMessage(content=user))
        else:
            for role, content in user:
                msgs.append(AIMessage(content=content) if role == "assistant" else HumanMessage(content=content))
        text, _ = await astream_with_reasoning(llm, msgs, total_timeout=900)
        return (text or "").strip()

    async def _retrying(self, system: str, user: str | Messages, effort: str, max_tokens: int) -> str:
        """One call, retried on transient provider failures (dropped connection, timeout, rate limit, 5xx): a research
        project runs for an hour and must not lose a round's judgement to one network blip."""
        import asyncio

        delays = (5, 20, 60)
        for attempt in range(len(delays) + 1):
            try:
                return await self._once(system, user, effort, max_tokens)
            except Exception as exc:  # noqa: BLE001 - only transient failures are retried
                name = type(exc).__name__
                transient = any(k in name for k in ("Connection", "Timeout", "RateLimit", "InternalServer",
                                                    "ServiceUnavailable", "APIStatus", "ReadError", "RemoteProtocol"))
                if not transient or attempt == len(delays):
                    raise
                logger.warning("research model call failed (%s); retrying in %ss", name, delays[attempt])
                await asyncio.sleep(delays[attempt])
        raise RuntimeError("unreachable")

    async def text(self, system: str, user: str | Messages, *, effort: str = "medium", max_tokens: int = 32000) -> str:
        out = await self._retrying(system, user, effort, max_tokens)
        if out:
            return out
        lower = _LOWER.get(effort, "low")
        logger.warning("research model returned no text at effort %s; retrying at %s", effort, lower)
        out = await self._retrying(system, user, lower, max_tokens)
        if not out:
            raise EmptyReply("the model returned no text, twice")
        return out

    async def json(self, system: str, user: str, *, effort: str = "medium", max_tokens: int = 32000) -> Any:
        from ..llm import extract_json

        last: Exception | None = None
        prompt = user
        for _ in range(2):
            raw = await self.text(system, prompt, effort=effort, max_tokens=max_tokens)
            try:
                return extract_json(raw)
            except Exception as exc:  # noqa: BLE001 - one repair round, then give up
                last = exc
                prompt = (user + "\n\nYour previous reply was not valid JSON (" + str(exc)[:120] +
                          "). Reply with the JSON object only.")
        raise ValueError(f"no valid JSON from the model: {last}")


__all__ = ["EmptyReply", "LiveModel", "Messages", "ResearchModel"]
