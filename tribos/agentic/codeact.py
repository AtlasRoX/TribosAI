"""
Code-as-action problem solving (docs/plans/tribos-harness-landscape.md item 5; OpenHands CodeAct, NeMo-Skills
tool-integrated reasoning).

The model works the problem in a persistent Python session: each reply is a short piece of reasoning and one Python
cell; the cell runs in the sandbox (tribos.agentic.sandbox.session) and its output is the next observation. It stops
with "FINAL ANSWER:" or at the step limit. What the cells printed is computed; the model's final summary is not
itself checked, and the evidence renderer says so.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .sandbox.session import PythonSession

CODE_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S | re.I)
FINAL_RE = re.compile(r"FINAL ANSWER:\s*(.*)", re.S | re.I)
OBS_CHARS = 2500

SYSTEM = """You solve the user's problem by working in a persistent Python session, like a careful mathematician with a notebook.

Each reply: one or two sentences of reasoning, then exactly ONE ```python``` block. The block runs; you see its printed output next turn. Variables, functions and imports persist between blocks.
- Print every value you rely on. Prefer exact arithmetic (sympy, fractions.Fraction, integers) over floats; when you use floats, say so.
- Check results a second, independent way before relying on them (substitute back, a different method, a brute-force count on small cases).
- Seed any randomness. Keep each block short and fast (seconds). No network, no file writes outside the working directory.
- Exploring examples or testing a conjecture numerically is evidence, never proof: say so.
- If a block fails, read the error and fix that block; do not repeat it unchanged.

When the printed results answer the question, reply with no code block and start with "FINAL ANSWER:", then state the results, which were checked and how, and what remains unproved."""


async def solve(question: str, ask: Callable[[str, list[tuple[str, str]]], Awaitable[str]], *, max_steps: int = 6,
                context: str = "", on_cell: Callable[[int, dict[str, Any]], Awaitable[None]] | None = None,
                session: PythonSession | None = None) -> dict[str, Any]:
    """Work `question` in a Python session. `ask(system, messages)` returns the model's next reply."""
    session = session or PythonSession()
    opening = f"Problem:\n{question.strip()}"
    if context.strip():
        opening += f"\n\nAlready established (from other tools):\n{context.strip()[:4000]}"
    messages: list[tuple[str, str]] = [("user", opening)]
    final, stopped = "", "step limit"
    for step in range(1, max_steps + 1):
        reply = await ask(SYSTEM, messages)
        messages.append(("assistant", reply))
        code = CODE_RE.search(reply)
        if code is None:
            m = FINAL_RE.search(reply)
            final, stopped = (m.group(1) if m else reply).strip(), "final answer"
            break
        cell = await asyncio.to_thread(session.run, code.group(1))
        if on_cell is not None:
            await on_cell(step, cell.to_dict())
        if cell.status == "ok":
            observation = f"Output of block {step}:\n{cell.stdout[:OBS_CHARS] or '(nothing printed)'}"
        else:
            observation = f"Block {step} failed ({cell.status}):\n{cell.error[:OBS_CHARS]}"
        if step == max_steps - 1:
            observation += "\n\nOne reply left: give the FINAL ANSWER now."
        messages.append(("user", observation))
    cells = [c.to_dict() for c in session.history]
    return {"question": question[:2000], "cells": cells, "final": final, "stopped": stopped,
            "steps": len(cells), "ok_cells": sum(1 for c in cells if c["status"] == "ok")}


__all__ = ["SYSTEM", "solve"]
