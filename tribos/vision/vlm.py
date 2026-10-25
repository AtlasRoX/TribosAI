"""Vision-language transcription of a question image: an NVIDIA NIM vision model, or a local model through Ollama.

The model gets the image and the OCR draft. The draft grounds it (the words and numbers OCR read with high
confidence) and the image corrects what OCR loses: dots for time derivatives, primes, subscripts, fraction bars,
matrices, and the content of figures.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from ..config.settings import get_int, get_str

logger = logging.getLogger(__name__)

# Ollama model families that accept images, best first for reading mathematics.
VISION_FAMILIES = ("qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "gemma3", "llama3.2-vision", "minicpm-v", "granite3.2-vision",
                   "llava")

TRANSCRIBE_PROMPT = """Transcribe the question in this image exactly, as Markdown with LaTeX math ($...$ inline, $$...$$ for display equations).

Rules:
- Copy every word, number, unit, variable and condition exactly as printed. Do not solve, simplify, rephrase or add anything.
- Keep derivative notation as written: dots (\\dot{x}, \\ddot{x}), primes (x'), d/dt. Keep subscripts, superscripts, Greek letters, fractions and matrices.
- If the image has a figure, diagram, graph or table, add a final section "Figure:" describing exactly what it shows (labels, values, axes, arrows, connections) without interpreting it.
- If something is unreadable, write [unreadable] in its place instead of guessing.
Reply with the transcription only.
"""

DRAFT_NOTE = """An OCR engine read this draft from the same image. Words and numbers in it are usually right; its math is often wrong (missing dots, primes, subscripts, fraction structure). Use it as a reference and correct it from the image:

<ocr_draft>
{draft}
</ocr_draft>
"""


def _ollama_url() -> str:
    return str(get_str("TRIBOS_VISION_OLLAMA_URL")).rstrip("/")


def ollama_models(timeout: float = 2.0) -> list[str]:
    """Names of the models the local Ollama server has; [] when it is not running."""
    try:
        res = httpx.get(f"{_ollama_url()}/api/tags", timeout=timeout)
        res.raise_for_status()
        return [str(m.get("name") or m.get("model") or "") for m in res.json().get("models") or []]
    except Exception:  # noqa: BLE001 - Ollama not installed or not running
        return []


def local_model() -> str | None:
    """The configured Ollama vision model, else the first installed model of a vision family (best family first)."""
    names = ollama_models()
    wanted = get_str("TRIBOS_VISION_OLLAMA_MODEL")
    if wanted:
        return wanted if any(n == wanted or n.split(":")[0] == wanted for n in names) else None
    for family in VISION_FAMILIES:
        for name in names:
            if name.lower().startswith(family):
                return name
    return None


def _prompt(draft: str) -> str:
    return TRANSCRIBE_PROMPT + ("\n" + DRAFT_NOTE.format(draft=draft[:6000]) if draft.strip() else "")


async def transcribe_local(image_png: bytes, draft: str, model: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192},
        "messages": [{"role": "user", "content": _prompt(draft), "images": [base64.b64encode(image_png).decode()]}],
    }
    async with httpx.AsyncClient(timeout=float(get_int("TRIBOS_VISION_TIMEOUT_S"))) as client:
        res = await client.post(f"{_ollama_url()}/api/chat", json=payload)
        res.raise_for_status()
        return str((res.json().get("message") or {}).get("content") or "").strip()


def provider() -> str:
    """nim | ollama | ocr (TRIBOS_VISION_PROVIDER)."""
    return str(get_str("TRIBOS_VISION_PROVIDER") or "nim")


def nim_model() -> str:
    from ..utils.llm.llm_factory import DEFAULT_ORCHESTRATOR_MODEL

    return str(get_str("TRIBOS_VISION_MODEL") or DEFAULT_ORCHESTRATOR_MODEL)


async def transcribe_remote(image_png: bytes, draft: str, model_name: str | None = None) -> tuple[str, str]:
    """(text, model) from an NVIDIA NIM vision model (TRIBOS_VISION_MODEL; it must be in the allowed model list)."""
    from langchain_core.messages import HumanMessage

    from ..utils.llm.llm_factory import get_llm

    name = model_name or nim_model()
    llm = get_llm(model_name=name, temperature=0.0, max_tokens=4096, timeout=float(get_int("TRIBOS_VISION_TIMEOUT_S")))
    url = "data:image/png;base64," + base64.b64encode(image_png).decode()
    msg = HumanMessage(content=[{"type": "text", "text": _prompt(draft)}, {"type": "image_url", "image_url": {"url": url}}])
    reply = await llm.ainvoke([msg])
    content: Any = getattr(reply, "content", "")
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
    # A reasoning model may prefix its answer with a <think> block.
    return re.sub(r"(?s)^\s*<think>.*?</think>\s*", "", str(content)).strip(), name
