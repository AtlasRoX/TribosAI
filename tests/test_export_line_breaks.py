"""Exports keep the answer's lines and never carry the verification banner (audit I17: "ALPHA\nBETA" exported as
"ALPHA BETA"; the "Verification found errors" banner survived exports)."""

from __future__ import annotations

import io

import docx
import pypdf

BANNER = ("> ⚠️ **Verification found errors**: 1 mathematical statement(s) in this answer do not hold.\n"
          "> n=41 failed\n\n")
ANSWER = "A: 1681 = 41 * 41\nB: 1763 = 41 * 43\n\nThe second paragraph."


def _report(content: str):
    from tribos.export import build_report_model

    return build_report_model("Evaluate n^2 + n + 41 for n = 40 and n = 41.", {"content": content, "agent": "Tribos"})


def test_docx_keeps_written_lines_as_line_breaks():
    from tribos.export import render_docx

    doc = docx.Document(io.BytesIO(render_docx(_report(BANNER + ANSWER))))
    para = next(p for p in doc.paragraphs if "1681" in p.text)
    assert para.text == "A: 1681 = 41 * 41\nB: 1763 = 41 * 43"  # python-docx reads <w:br/> as "\n"
    assert para._p.xpath(".//w:br")
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "Verification found errors" not in texts and "The second paragraph." in texts


def test_pdf_keeps_written_lines_on_separate_lines():
    from tribos.export import render_pdf

    data = render_pdf(_report(BANNER + "ALPHA\nBETA\n\n" + ANSWER))
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    lines = [ln.strip() for ln in text.splitlines()]
    assert "ALPHA" in lines and "BETA" in lines and "ALPHA BETA" not in text
    assert "A: 1681 = 41 * 41" in lines and "B: 1763 = 41 * 43" in lines
    assert "Verification found errors" not in text


def test_markdown_export_keeps_the_text_and_drops_the_banner():
    from tribos.export import render_markdown

    md = render_markdown(_report(BANNER + ANSWER)).decode("utf-8")
    assert "A: 1681 = 41 * 41\nB: 1763 = 41 * 43" in md and "Verification found errors" not in md
