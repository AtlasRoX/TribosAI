"""Measure what Tribos sends to and gets from the model for a few typical questions.

Every chat-model call made while a question runs is counted: its input (characters of every message, and the
provider's prompt-token count when it reports one) and its output (characters and completion tokens, reasoning
included). Run it before and after a change to see what the change saves:

    python scripts/measure_tokens.py --effort medium --out before.json
    python scripts/measure_tokens.py --effort medium --out after.json --compare before.json

Characters are counted for every call; token counts only where the provider reports usage (non-streamed calls).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUESTIONS = [
    ("fact", "What is the boiling point of water at 2 atm?"),
    ("literature", "How does CRISPR-Cas9 cause off-target edits, and how are they reduced?"),
    ("math", "Solve x^2 - 5x + 6 = 0."),
]


class Meter:
    """Counts every request to the model provider at the HTTP layer, so no client path (streamed, sync, retried) is
    missed: request count, characters of message text sent, and the provider's usage where the reply reports it."""

    HOSTS = ("api.meta.ai",)

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _message_chars(body: bytes) -> tuple[int, int | None]:
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return len(body or b""), None
        total = 0
        for m in data.get("messages") or []:
            c = m.get("content")
            if isinstance(c, list):
                total += sum(len(str(p.get("text", ""))) for p in c if isinstance(p, dict))
            else:
                total += len(str(c or ""))
        return total, data.get("max_tokens") or data.get("max_completion_tokens")

    def install(self) -> None:
        import httpx

        meter = self
        orig_async, orig_sync = httpx.AsyncClient.send, httpx.Client.send

        def record(request: Any, response: Any) -> None:
            chars, cap = meter._message_chars(request.content)
            usage = {}
            if response is not None and "application/json" in response.headers.get("content-type", ""):
                try:
                    usage = (json.loads(response.content).get("usage") or {}) if response.is_closed or True else {}
                except Exception:  # noqa: BLE001 - a streamed body is not read here
                    usage = {}
            meter.calls.append({"in_chars": chars, "max_tokens": cap, "status": getattr(response, "status_code", None),
                                "in_tokens": usage.get("prompt_tokens"), "out_tokens": usage.get("completion_tokens")})

        async def asend(self, request, *a, **k):  # type: ignore[no-untyped-def]
            response = await orig_async(self, request, *a, **k)
            if any(h in str(request.url) for h in meter.HOSTS):
                if not k.get("stream"):
                    await response.aread()
                record(request, response)
            return response

        def send(self, request, *a, **k):  # type: ignore[no-untyped-def]
            response = orig_sync(self, request, *a, **k)
            if any(h in str(request.url) for h in meter.HOSTS):
                if not k.get("stream"):
                    response.read()
                record(request, response)
            return response

        httpx.AsyncClient.send = asend  # type: ignore[method-assign]
        httpx.Client.send = send  # type: ignore[method-assign]


async def run_one(meter: Meter, question: str, effort: str) -> dict[str, Any]:
    from tribos.agents.authoritative_orchestrator import get_authoritative_orchestrator

    before = len(meter.calls)
    t0 = time.time()
    res = await get_authoritative_orchestrator().execute_inquiry(
        query=question, thread_id=f"measure_{uuid.uuid4().hex[:8]}", model_name="muse-spark-1.3",
        enable_web_search=True, user_id="measure", agent_options={"effort_level": effort, "allow_clarification": False},
    )
    calls = meter.calls[before:]
    return {
        "seconds": round(time.time() - t0, 1),
        "llm_calls": len(calls),
        "in_chars": sum(c["in_chars"] for c in calls),
        "in_tokens_reported": sum(c["in_tokens"] or 0 for c in calls),
        "out_tokens_reported": sum(c["out_tokens"] or 0 for c in calls),
        "answer_chars": len(res.response or ""),
        "answer_words": len((res.response or "").split()),
        "largest_call_in_chars": max((c["in_chars"] for c in calls), default=0),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare")
    ap.add_argument("--only", nargs="*", help="question labels to run (fact, literature, math)")
    args = ap.parse_args()
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    meter = Meter()
    meter.install()
    results = {}
    for label, q in QUESTIONS:
        if args.only and label not in args.only:
            continue
        results[label] = await run_one(meter, q, args.effort)
        print(label, json.dumps(results[label]), flush=True)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        for label, r in results.items():
            b = base.get(label)
            if not b:
                continue
            for key in ("in_chars", "largest_call_in_chars", "answer_words", "llm_calls", "seconds"):
                old, new = b[key], r[key]
                change = f"{(new - old) / old * 100:+.0f}%" if old else "n/a"
                print(f"{label:11} {key:14} {old:>9} -> {new:>9}  {change}")


if __name__ == "__main__":
    asyncio.run(main())
