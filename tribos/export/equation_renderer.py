"""LaTeX equation renderer using matplotlib.mathtext (owned by EXPORT, feature 9)."""

from __future__ import annotations

import base64
import functools
import html
import io
import re

import matplotlib

# Use headless Agg backend
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.mathtext import math_to_image

# Matches block math $$...$$ and inline math $...$
# Disallows space right after opening $ or right before closing $ for inline math to prevent matching currency
MATH_TOKEN_RE = re.compile(r"(\$\$[\s\S]+?\$\$|\$(?!\s)(?:\\\$|[^\$\n])+?(?<!\s)\$)")


def _clean_latex(latex_str: str) -> str:
    """Strip bounding dollar delimiters and fix common mathtext differences."""
    clean = (latex_str or "").strip()
    if clean.startswith("$$") and clean.endswith("$$") and len(clean) >= 4:
        clean = clean[2:-2].strip()
    elif clean.startswith("$") and clean.endswith("$") and len(clean) >= 2:
        clean = clean[1:-1].strip()

    # Common LaTeX macros not recognized by mathtext or with different syntax
    clean = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", clean)
    clean = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", clean)
    clean = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", clean)
    return clean


@functools.lru_cache(maxsize=256)
def render_latex_to_png(latex_str: str, dpi: int = 180) -> bytes:
    """Render a LaTeX equation into PNG bytes with a transparent background and tight bounding box."""
    clean = _clean_latex(latex_str)
    if not clean:
        return b""

    buf = io.BytesIO()
    try:
        math_to_image(f"${clean}$", buf, dpi=dpi, format="png")
        return buf.getvalue()
    except Exception:
        # Fallback 1: render via plt.figure text
        try:
            fig = plt.figure(figsize=(0.01, 0.01))
            fig.text(0, 0, f"${clean}$", fontsize=11)
            fallback_buf = io.BytesIO()
            fig.savefig(fallback_buf, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.02)
            plt.close(fig)
            return fallback_buf.getvalue()
        except Exception:
            # Fallback 2: render clean string as text
            try:
                fig = plt.figure(figsize=(0.01, 0.01))
                fig.text(0, 0, clean, fontsize=10)
                text_buf = io.BytesIO()
                fig.savefig(text_buf, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.02)
                plt.close(fig)
                return text_buf.getvalue()
            except Exception:
                return b""


def render_latex_to_data_uri(latex_str: str, dpi: int = 180) -> str:
    """Render a LaTeX equation into a base64 data URI string."""
    png = render_latex_to_png(latex_str, dpi=dpi)
    if not png:
        return ""
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"


def replace_equations_in_html(html_text: str, dpi: int = 180) -> str:
    """Replace $...$ and $$...$$ equations in HTML with inline/block <img> tags with data URIs."""
    from PIL import Image

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        is_block = raw.startswith("$$")
        eq_text = html.unescape(raw)
        png = render_latex_to_png(eq_text, dpi=dpi)
        if not png:
            return raw
        try:
            with Image.open(io.BytesIO(png)) as img:
                w_px, h_px = img.size
            # Convert px at dpi to mm (25.4 mm per inch) for fpdf2 write_html
            w_mm = max(1.0, w_px * 25.4 / float(dpi))
            h_mm = max(1.0, h_px * 25.4 / float(dpi))
            b64 = base64.b64encode(png).decode("ascii")
            img_tag = f'<img src="data:image/png;base64,{b64}" width="{w_mm:.1f}" height="{h_mm:.1f}">'
            if is_block:
                return f'</p><p align="center">{img_tag}</p><p>'
            return img_tag
        except Exception:
            return raw

    return MATH_TOKEN_RE.sub(repl, html_text)
