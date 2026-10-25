"""Read one question image: Indra OCR first, then a vision-language model that corrects the draft against the image.

Engines run in this order and each is optional:
1. Indra OCR (local CPU). Always tried; its lines and confidences ground everything after it.
2. The vision model of TRIBOS_VISION_PROVIDER: `nim` (default; an NVIDIA NIM vision model, TRIBOS_VISION_MODEL) or
   `ollama` (a local model). `ocr` stops after step 1, so the image never leaves this machine.
3. If the NIM call fails and a local Ollama vision model is installed, that model; otherwise the OCR text stands.

The result names the engines that ran. Numbers in the vision model's transcription that OCR never read are listed in
`unconfirmed_numbers`: either OCR missed them or the model invented them, and the reader is asked to check them.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config.settings import get_bool, get_int
from . import ocr, vlm

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff", "application/pdf"}
PDF_TYPE = "application/pdf"
PDF_SCALE = 2.0  # render scale (144 dpi): small print stays legible for recognition
MAX_TEXT_CHARS = 8000
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


class ImageReadError(ValueError):
    """The upload is not a readable image (wrong type, too large, corrupt)."""


@dataclass
class ImageReading:
    id: str
    filename: str
    width: int
    height: int
    text: str  # the transcription to solve from: the vision model's, else the OCR markdown
    ocr_text: str = ""
    ocr_confidence: float | None = None
    # The reading steps that ran, in plain words ("text recognition", "vision check"); engine and model names stay in
    # the server log, never in what a reader sees.
    engines: list[str] = field(default_factory=list)
    vision_checked: bool = False
    unconfirmed_numbers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0
    pages: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode(data: bytes, content_type: str) -> Any:
    import cv2
    import numpy as np

    if content_type and (content_type.lower() not in ALLOWED_TYPES or content_type.lower() == PDF_TYPE):
        raise ImageReadError(f"Unsupported image type {content_type!r}; use PNG, JPEG, WebP, BMP or TIFF.")
    limit = int(get_int("TRIBOS_VISION_MAX_MB")) * 1024 * 1024
    if len(data) > limit:
        raise ImageReadError(f"The image is larger than {limit // (1024 * 1024)} MB.")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ImageReadError("The file could not be decoded as an image.")
    h, w = image.shape[:2]
    if w * h > ocr.MAX_PIXELS:
        f = (ocr.MAX_PIXELS / (w * h)) ** 0.5
        image = cv2.resize(image, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return image


def _png(image: Any, max_side: int = 1600) -> bytes:
    """The image as PNG for a vision model, its long side at most max_side (vision encoders tile larger inputs)."""
    import cv2

    h, w = image.shape[:2]
    if max(h, w) > max_side:
        f = max_side / max(h, w)
        image = cv2.resize(image, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ImageReadError("The image could not be re-encoded.")
    return buf.tobytes()


def unconfirmed_numbers(transcription: str, ocr_text: str) -> list[str]:
    """Numbers in the transcription that the OCR text does not contain (OCR spaces digits in LaTeX: "0 . 1")."""
    seen = set(_NUMBER_RE.findall(re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", ocr_text)))
    out: list[str] = []
    for n in _NUMBER_RE.findall(transcription):
        if n not in seen and n not in out:
            out.append(n)
    return out[:12]


def question_text(markdown: str) -> str:
    """OCR markdown as question text: layout headings ("## Problem 3. ...") become plain lines."""
    return re.sub(r"(?m)^#{1,6}\s+", "", markdown).strip()


def _strip_fences(text: str) -> str:
    m = re.fullmatch(r"\s*```(?:markdown|md|latex)?\s*\n(.*?)\n```\s*", text, re.DOTALL)
    return m.group(1) if m else text.strip()


def _pdf_pages(data: bytes) -> tuple[list[Any], int]:
    """(the first TRIBOS_VISION_MAX_PAGES pages as BGR images, the page count) of a PDF."""
    import numpy as np
    import pypdfium2 as pdfium

    limit = int(get_int("TRIBOS_VISION_MAX_PAGES"))
    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 - encrypted, damaged or not a PDF
        raise ImageReadError("The PDF could not be opened (it may be damaged or password-protected).") from exc
    try:
        total = len(doc)
        pages = []
        for i in range(min(total, limit)):
            bitmap = doc[i].render(scale=PDF_SCALE).to_pil().convert("RGB")
            pages.append(np.ascontiguousarray(np.asarray(bitmap)[:, :, ::-1]))
        return pages, total
    finally:
        doc.close()


async def read_image(data: bytes, content_type: str = "", filename: str = "image") -> ImageReading:
    """Read one image, or each page of a PDF, into question text (see the module docstring)."""
    if (content_type or "").lower() != PDF_TYPE:
        return await _read_decoded(_decode(data, content_type), data, filename)
    limit = int(get_int("TRIBOS_VISION_MAX_MB")) * 1024 * 1024
    if len(data) > limit:
        raise ImageReadError(f"The file is larger than {limit // (1024 * 1024)} MB.")
    started = time.time()
    pages, total = await asyncio.to_thread(_pdf_pages, data)
    if not pages:
        raise ImageReadError("The PDF has no pages.")
    readings = [await _read_decoded(img, data + bytes([i]), filename) for i, img in enumerate(pages)]
    first = readings[0]
    merged = ImageReading(id="img_" + hashlib.sha256(data).hexdigest()[:16], filename=first.filename,
                          width=first.width, height=first.height, text="", pages=len(pages))
    many = len(readings) > 1
    merged.text = "\n\n".join((f"**Page {i + 1}**\n\n" if many else "") + r.text for i, r in enumerate(readings) if r.text.strip())
    merged.ocr_text = "\n\n".join(r.ocr_text for r in readings if r.ocr_text)
    confidences = [r.ocr_confidence for r in readings if r.ocr_confidence is not None]
    merged.ocr_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None
    merged.engines = list(dict.fromkeys(e for r in readings for e in r.engines))
    merged.vision_checked = all(r.vision_checked for r in readings)
    merged.unconfirmed_numbers = list(dict.fromkeys(n for r in readings for n in r.unconfirmed_numbers))[:12]
    merged.warnings = list(dict.fromkeys(w for r in readings for w in r.warnings))
    if total > len(pages):
        merged.warnings.append(f"Only the first {len(pages)} of {total} pages were read.")
    merged.text = merged.text[: MAX_TEXT_CHARS * 2]
    merged.seconds = round(time.time() - started, 2)
    return merged


async def _read_decoded(image: Any, data: bytes, filename: str) -> ImageReading:
    started = time.time()
    h, w = image.shape[:2]
    reading = ImageReading(id="img_" + hashlib.sha256(data).hexdigest()[:16], filename=filename[:120] or "image",
                           width=int(w), height=int(h), text="")

    if ocr.available():
        try:
            result = await asyncio.to_thread(ocr.read, image)
            reading.ocr_text = question_text(result.markdown)
            reading.ocr_confidence = round(result.mean_conf, 3) if result.lines else None
            reading.engines.append("text recognition")
            logger.info("Image %s read by %s in %.0f ms", reading.id, result.engine, result.ms)
        except Exception as exc:  # noqa: BLE001 - the vision model can still read the image
            logger.warning("Indra OCR failed: %s", exc)
            reading.warnings.append("Text recognition failed on this image.")
    else:
        logger.warning("Text recognition unavailable: pip install indra-ocr")
        reading.warnings.append("Text recognition is not installed on the server.")

    png = _png(image)
    text = ""
    chosen = vlm.provider()

    async def run_local() -> str:
        model = await asyncio.to_thread(vlm.local_model)
        if not model:
            return ""
        try:
            out = _strip_fences(await vlm.transcribe_local(png, reading.ocr_text, model))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local vision model %s failed: %s", model, exc)
            reading.warnings.append("The vision check failed on this image.")
            return ""
        if out:
            reading.vision_checked = True
            reading.engines.append("vision check")
            logger.info("Image %s checked by local model %s", reading.id, model)
        return out

    if chosen == "nim":
        try:
            out, name = await vlm.transcribe_remote(png, reading.ocr_text)
            text = _strip_fences(out)
            if text:
                reading.vision_checked = True
                reading.engines.append("vision check")
                logger.info("Image %s checked by %s", reading.id, name)
        except Exception as exc:  # noqa: BLE001 - a local model or the OCR text can still answer
            logger.warning("NIM vision model failed: %s", exc)
            reading.warnings.append("The vision check could not be completed.")
        if not text:
            text = await run_local()
    elif chosen == "ollama":
        text = await run_local()
        if not text:
            logger.warning("No local vision model answered (is Ollama running with a vision model?)")
    if not reading.vision_checked:
        reading.warnings.append(
            "Only text recognition read this image: check formulas (derivative dots, primes, subscripts) before "
            "sending."
        )

    if text:
        reading.text = text[:MAX_TEXT_CHARS]
        if reading.ocr_text:
            reading.unconfirmed_numbers = unconfirmed_numbers(reading.text, reading.ocr_text)
    else:
        reading.text = reading.ocr_text[:MAX_TEXT_CHARS]
    if not reading.text.strip():
        reading.warnings.append("No text was found in the image.")
    reading.seconds = round(time.time() - started, 2)
    return reading


def vision_status() -> dict[str, Any]:
    """What can read images right now (for the UI and /api/vision/status)."""
    models = vlm.ollama_models()
    return {
        "enabled": bool(get_bool("TRIBOS_VISION")),
        "text_recognition": ocr.available(),
        "vision_check": vlm.provider() == "nim" or (vlm.provider() == "ollama" and bool(models and vlm.local_model())),
        "accepted_types": sorted(ALLOWED_TYPES),
        "max_mb": int(get_int("TRIBOS_VISION_MAX_MB")),
    }


def image_context_block(items: list[dict[str, Any]]) -> str:
    """The attached images' transcriptions as part of the question text the pipeline solves."""
    parts = []
    for i, item in enumerate(items, 1):
        text = str(item.get("text") or "").strip()[:MAX_TEXT_CHARS]
        if text:
            name = str(item.get("name") or f"image {i}")[:120]
            parts.append(f"Attached image {i} ({name}), transcribed:\n{text}")
    return "\n\n".join(parts)
