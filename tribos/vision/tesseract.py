"""Tesseract OCR: a second, independent text recognizer, read word by word with its confidence.

Tesseract reads plain words very reliably (confidence 90+ on printed text) and mathematics badly (quantifiers,
subscripts and relation symbols come out as garbage, with confidence near 0). That is exactly what the reader needs
from it: the words Tesseract reads with high confidence, and Indra OCR also read, are really in the image. They are
the ground truth that a vision transcription is checked against, so garbled OCR math never counts against a correct
LaTeX transcription.

The binary is called directly (no Python wrapper): TRIBOS_VISION_TESSERACT names it, or it is found on PATH, in a
Scoop install, or in the default Windows install folder. `off` disables it. Missing Tesseract is not an error; the
reader then falls back to Indra OCR alone.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import subprocess  # nosec B404 - runs the configured Tesseract binary with fixed arguments, never a shell
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config.settings import get_str

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0
MIN_WIDTH = 1200  # small screenshots read better at 2x, as for Indra OCR
CONFIDENT = 80.0  # words at or above this confidence are taken as read correctly


@dataclass
class TessWord:
    text: str
    conf: float


@dataclass
class TessResult:
    text: str
    words: list[TessWord] = field(default_factory=list)
    engine: str = ""
    ms: float = 0.0

    def confident_words(self, floor: float = CONFIDENT) -> list[str]:
        return [w.text for w in self.words if w.conf >= floor]


def _candidates() -> list[str]:
    home = Path.home()
    found = shutil.which("tesseract")
    return [p for p in (
        found,
        str(home / "scoop" / "apps" / "tesseract" / "current" / "tesseract.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tesseract-OCR", "tesseract.exe"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ) if p]


@lru_cache(maxsize=4)
def _resolve(configured: str) -> str | None:
    if configured.lower() == "off":
        return None
    for path in ([configured] if configured else _candidates()):
        if path and Path(path).is_file():
            return path
    return None


def binary() -> str | None:
    """The Tesseract executable to run, or None (not installed, or TRIBOS_VISION_TESSERACT=off)."""
    return _resolve(str(get_str("TRIBOS_VISION_TESSERACT") or "").strip())


@lru_cache(maxsize=4)
def _languages(exe: str) -> tuple[str, ...]:
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=TIMEOUT_S,  # nosec B603
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    lines = (out.stdout or "").splitlines()
    return tuple(ln.strip() for ln in lines[1:] if ln.strip())


@lru_cache(maxsize=4)
def _version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=TIMEOUT_S,  # nosec B603
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    first = ((out.stdout or out.stderr or "").splitlines() or [""])[0]
    return first.replace("tesseract", "").strip().split(".20")[0]  # "v5.5.3.20260724" -> "v5.5.3"


def language() -> str:
    return str(get_str("TRIBOS_VISION_TESSERACT_LANG") or "eng")


def available() -> bool:
    """Tesseract is installed and has the configured language's model."""
    exe = binary()
    if not exe:
        return False
    wanted = [lang for lang in language().split("+") if lang]
    have = _languages(exe)
    return bool(wanted) and all(lang in have for lang in wanted)


def parse_tsv(tsv: str) -> tuple[str, list[TessWord]]:
    """(text with one line per Tesseract line, words with confidences) from `tesseract ... tsv` output."""
    words: list[TessWord] = []
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1.0
        words.append(TessWord(text=text, conf=conf))
        key = (row.get("page_num") or "", row.get("block_num") or "", row.get("par_num") or "", row.get("line_num") or "")
        lines.setdefault(key, []).append(text)
    return "\n".join(" ".join(ws) for ws in lines.values()), words


def read(image: Any) -> TessResult | None:
    """Tesseract's reading of one decoded image (NumPy, grayscale or BGR); None when it is unavailable or fails."""
    exe = binary()
    if not exe or not available():
        return None
    import cv2

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if w < MIN_WIDTH:
        gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        return None
    started = time.time()
    try:
        out = subprocess.run(  # nosec B603 - fixed argument list, no shell
            [exe, "stdin", "stdout", "--psm", "3", "-l", language(), "tsv"],
            input=buf.tobytes(), capture_output=True, timeout=TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Tesseract failed: %s", exc)
        return None
    if out.returncode != 0:
        logger.warning("Tesseract exited with %s: %s", out.returncode, (out.stderr or b"")[:300].decode(errors="replace"))
        return None
    text, words = parse_tsv(out.stdout.decode("utf-8", errors="replace"))
    return TessResult(text=text, words=words, engine=f"Tesseract {_version(exe)}".strip(),
                      ms=(time.time() - started) * 1000)


def status() -> dict[str, Any]:
    exe = binary()
    return {"available": available(), "binary": bool(exe), "language": language(),
            "languages": list(_languages(exe)) if exe else []}
