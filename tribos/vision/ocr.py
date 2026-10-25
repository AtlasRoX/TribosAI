"""Indra OCR (https://github.com/datalab-to/indra): CPU text and math recognition through ONNX Runtime.

Loaded once per process (about 2 s, plus a one-time download of about 80 MB of models from Hugging Face). Two
workarounds for indra-ocr 1.1.x on Windows: its math metadata is read with the platform encoding (cp1252 cannot
decode it), and a cached text-only snapshot hides the math models, so they are fetched explicitly.
"""

from __future__ import annotations

import contextlib
import logging
import pathlib
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from ..config.settings import get_bool

logger = logging.getLogger(__name__)

# Images narrower than this are upscaled before recognition: small screenshots read far better at about 2x.
MIN_WIDTH = 1200
MAX_PIXELS = 40_000_000

_lock = threading.Lock()
_converter: Any = None
_converter_math: bool | None = None
_load_error: str | None = None


@dataclass
class OcrLine:
    text: str
    conf: float
    box: tuple[int, int, int, int]


@dataclass
class OcrResult:
    markdown: str
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = ""
    ms: float = 0.0

    @property
    def mean_conf(self) -> float:
        return sum(ln.conf for ln in self.lines) / len(self.lines) if self.lines else 0.0


def available() -> bool:
    try:
        import indra_ocr  # noqa: F401
    except ImportError:
        return False
    return True


@contextlib.contextmanager
def _utf8_text_reads() -> Generator[None]:
    """Path.read_text defaults to UTF-8 while the models load (indra-ocr reads its JSON with the platform codec)."""
    original = pathlib.Path.read_text

    def read_text(self: pathlib.Path, encoding: str | None = None, errors: str | None = None, **_kw: Any) -> str:
        return original(self, encoding=encoding or "utf-8", errors=errors)

    pathlib.Path.read_text = read_text  # type: ignore[method-assign]
    try:
        yield
    finally:
        pathlib.Path.read_text = original  # type: ignore[method-assign]


def _model_dir(math: bool) -> str | None:
    """A model folder holding the math models too when math is on (None: let indra-ocr resolve it)."""
    if not math:
        return None
    from huggingface_hub import snapshot_download
    from indra_ocr import models

    patterns = ["*.onnx", "meta.json", "lm.npz", "lm_*.npz", *models.MATH_FILES]
    for local_only in (True, False):
        try:
            path = snapshot_download(models.HF_REPO, revision=models.HF_REVISION, allow_patterns=patterns,
                                     local_files_only=local_only)
        except Exception:  # noqa: BLE001 - not cached yet (first pass) or no network (second)
            continue
        if all((pathlib.Path(path) / f).exists() for f in models.MATH_FILES):
            return path
    return None


def _load() -> Any:
    global _converter, _converter_math, _load_error
    math = bool(get_bool("TRIBOS_VISION_OCR_MATH"))
    with _lock:
        if _converter is not None and _converter_math == math:
            return _converter
        import indra_ocr

        started = time.time()
        with _utf8_text_reads():
            path = _model_dir(math)
            if math and path is None:
                logger.warning("Indra OCR math models unavailable; reading text only")
                math = False
            _converter = indra_ocr.load(path=path, threads=4, math=math)
        _converter_math = math
        _load_error = None
        logger.info("Indra OCR loaded in %.1fs (math=%s)", time.time() - started, math)
        return _converter


def read(image: Any) -> OcrResult:
    """OCR of one decoded image (a NumPy array, grayscale or BGR)."""
    import cv2
    import indra_ocr

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = 1.0
    h, w = gray.shape[:2]
    if w < MIN_WIDTH and w * h * 4 <= MAX_PIXELS:
        scale = 2.0
        gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    conv = _load()
    started = time.time()
    page = conv.ocr(gray)
    lines = [
        OcrLine(text=str(ln.text), conf=float(ln.conf), box=tuple(int(v / scale) for v in ln.box))  # type: ignore[arg-type]
        for ln in (getattr(page, "lines", None) or [])
    ]
    engine = f"Indra OCR {getattr(indra_ocr, '__version__', '')}".strip() + (" + math" if _converter_math else "")
    return OcrResult(markdown=str(getattr(page, "markdown", "") or ""), lines=lines, engine=engine,
                     ms=(time.time() - started) * 1000)


def status() -> dict[str, Any]:
    return {"available": available(), "loaded": _converter is not None, "math": bool(_converter_math),
            "error": _load_error}
