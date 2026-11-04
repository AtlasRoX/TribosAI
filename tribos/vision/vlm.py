"""Vision-language transcription of a question image: the cloud vision model, or a local model through Ollama.

The model gets the image and the OCR drafts. The drafts ground it (the words and numbers OCR read with high
confidence) and the image corrects what OCR loses: quantifiers and relation symbols, dots for time derivatives,
primes, subscripts, fraction bars, matrices, and the content of figures.

For the cross-check (reader.py) the same model also reads the image blind, settles the differences between two
readings by looking again (`review_remote`), and re-reads an image whose transcription left out words
(`repair_remote`).
"""

from __future__ import annotations

import asyncio
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

TRANSCRIBE_PROMPT = """Transcribe all text in this image exactly, as Markdown with LaTeX math ($...$ inline, $$...$$ display).
- Every line in reading order (headings, questions, sub-parts, options); never skip, merge or shorten.
- Copy words, numbers, units and conditions exactly; do not solve, rephrase, correct or add anything.
- Keep notation: dots (\\dot{x}), primes (x'), subscripts, superscripts, Greek letters, fractions, matrices.
- Write each symbol as the LaTeX command for what is printed: quantifiers \\forall \\exists, membership \\in \\notin,
  relations \\neq \\equiv \\leq \\geq \\approx \\sim, congruences \\pmod{m}, sets \\{a_n\\} \\subseteq \\cup \\cap, and
  number sets \\mathbb{N} \\mathbb{Z} \\mathbb{Q} \\mathbb{R} \\mathbb{C} with any ^* or ^+ printed on them.
- Indices exactly as printed: letters stay letters (a_i, a_j, a_k are never a_1, a_3, a_x), and every subscript or
  superscript stays attached to its symbol. Keep printed brackets, such as the parentheses in (\\forall) or (mod m).
- Only if there is a figure, diagram, graph or table: end with "Figure:" describing exactly what it shows.
- Write [unreadable] for anything you cannot read.
Reply with the transcription only.
"""

DRAFT_NOTE = """OCR engines read the same image. Their words and plain numbers are usually right; their mathematics is often wrong: \\forall read as V, \\exists as 3, \\in as e, c or €, \\neq as x, z or #, \\equiv as =, \\mathbb{{N}} as N or IT, subscripts as digits or punctuation (a_i as a1, a; or ai), set braces as parentheses. Use the drafts to check words and numbers; read every symbol, index and bracket from the image itself.

<ocr_draft>
{draft}
</ocr_draft>
"""

REVIEW_PROMPT = """Two careful readers transcribed this image as Markdown with LaTeX math, and they disagree in places. Look at the image and write the one correct transcription in the same format.

Where they differ (normalised tokens, each with a few tokens of context):
{differences}

<reader_1>
{first}
</reader_1>

<reader_2>
{second}
</reader_2>
{words}
At each difference, read the image itself: a quantifier (\\forall, \\exists), a relation (\\in, \\neq, \\equiv, =), an index (i, j, k, n or a digit), a prime, a dot, a bracket. Where the readers agree, keep their text. Do not solve, rephrase or add anything.
Reply with the transcription only.
"""

REPAIR_NOTE = """A previous transcription of this image left out text that OCR read in it, including these words: {missing}. Transcribe the whole image again, every line from the first to the last.

<previous_transcription>
{previous}
</previous_transcription>
"""


def combined_draft(layout: str, words: str) -> str:
    """The OCR drafts for the prompt: Indra's (layout and LaTeX math) and Tesseract's (plain words)."""
    layout, words = (layout or "").strip(), (words or "").strip()
    if layout and words:
        return (f"Reading 1 (layout and math):\n{layout[:5000]}\n\n"
                f"Reading 2 (words only; its mathematics is garbled):\n{words[:3000]}")
    return layout or words


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
    return TRANSCRIBE_PROMPT + ("\n" + DRAFT_NOTE.format(draft=draft[:8000]) if draft.strip() else "")


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
    """remote | ollama | ocr (TRIBOS_VISION_PROVIDER; "nim", its older name, means remote)."""
    value = str(get_str("TRIBOS_VISION_PROVIDER") or "remote")
    return "remote" if value == "nim" else value


def nim_model() -> str:
    from ..utils.llm.llm_factory import DEFAULT_ORCHESTRATOR_MODEL

    return str(get_str("TRIBOS_VISION_MODEL") or DEFAULT_ORCHESTRATOR_MODEL)


def output_budget(draft: str) -> int:
    """Output tokens for a transcription: room for the draft rewritten in LaTeX, plus a figure description.

    LaTeX is longer than garbled OCR ("ieN*" becomes "i\\in\\mathbb{N}^*"), so the draft counts twice. A blind reading
    (no draft) gets the full budget: its length is unknown, and a cut-off transcription loses its last lines.
    """
    if not draft.strip():
        return 4096
    return max(1536, min(4096, 2 * len(draft) + 768))


# One client per (model, output budget, event loop): get_llm opens a new HTTP client each time, so every image paid a
# fresh TLS connection to NIM (the first read of a process took 3.4 s, later ones about 1.1 s). Keyed by the loop
# object, since an async HTTP client cannot be shared across event loops (tests run one loop each).
_CLIENTS: dict[tuple[str, int, Any], Any] = {}
MAX_CLIENTS = 16


def _client(name: str, budget: int) -> Any:
    from ..utils.llm.llm_factory import get_llm

    key = (name, budget, asyncio.get_running_loop())
    llm = _CLIENTS.get(key)
    if llm is None:
        if len(_CLIENTS) >= MAX_CLIENTS:
            _CLIENTS.clear()
        llm = get_llm(model_name=name, temperature=0.0, max_tokens=budget, reasoning_effort="minimal",
                      timeout=float(get_int("TRIBOS_VISION_TIMEOUT_S")))
        _CLIENTS[key] = llm
    return llm


class TruncatedReply(RuntimeError):
    """The model stopped at its output limit: the transcription is missing its end."""


async def _ask(image_png: bytes, prompt: str, budget: int, model_name: str | None = None) -> tuple[str, str]:
    from langchain_core.messages import HumanMessage

    name = model_name or nim_model()
    # Thinking off (reasoning_effort="minimal"): transcription is copying, not reasoning. With thinking on, the model
    # spent 75 s and its whole 4096-token budget reasoning and returned nothing; with it off the same image took 1 s.
    # Budgets are rounded up to 1024 so a handful of clients cover every draft length.
    rounded = -(-budget // 1024) * 1024
    llm = _client(name, rounded)
    url = "data:image/png;base64," + base64.b64encode(image_png).decode()
    msg = HumanMessage(content=[{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}])
    reply = await llm.ainvoke([msg])
    content: Any = getattr(reply, "content", "")
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
    meta = getattr(reply, "response_metadata", None)
    if isinstance(meta, dict) and meta.get("finish_reason") == "length":
        raise TruncatedReply(f"{name} stopped at its {rounded}-token output limit")
    # A reasoning model may prefix its answer with a <think> block.
    return re.sub(r"(?s)^\s*<think>.*?</think>\s*", "", str(content)).strip(), name


async def transcribe_remote(image_png: bytes, draft: str, model_name: str | None = None) -> tuple[str, str]:
    """(text, model) from the cloud vision model (TRIBOS_VISION_MODEL; it must be in the allowed model list).

    An empty draft is a blind reading of the image alone; a draft (OCR, or a PDF text layer) grounds the words.
    """
    return await _ask(image_png, _prompt(draft), output_budget(draft), model_name)


async def review_remote(image_png: bytes, first: str, second: str, differences: list[tuple[str, str]],
                        words: list[str] | None = None, model_name: str | None = None) -> tuple[str, str]:
    """(text, model): one transcription from two readings that disagree, decided by looking at the image again."""
    listed = "\n".join(f"{i}. reader 1: {a}\n   reader 2: {b}" for i, (a, b) in enumerate(differences[:16], 1))
    sure = ("\nWords that both OCR engines read in the image (each must appear): " + ", ".join(words[:120]) + "\n"
            if words else "")
    prompt = REVIEW_PROMPT.format(differences=listed, first=first[:6000], second=second[:6000], words=sure)
    budget = max(1536, min(4096, int(1.3 * max(len(first), len(second))) + 768))
    return await _ask(image_png, prompt, budget, model_name)


async def repair_remote(image_png: bytes, previous: str, missing: list[str], draft: str,
                        model_name: str | None = None) -> tuple[str, str]:
    """(text, model): the image read again after a transcription that left out words OCR read."""
    prompt = _prompt(draft) + "\n" + REPAIR_NOTE.format(missing=", ".join(missing[:40]), previous=previous[:6000])
    return await _ask(image_png, prompt, 4096, model_name)
