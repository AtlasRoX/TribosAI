"""Read an uploaded paper (PDF): its text per page, metadata, sections and the maths it states.

Every extracted item keeps its page number and the verbatim source line, so a reader can check each one against
the paper. The maths is found line by line:

- equations "name = expression" (numbered when the line ends in "(n)"), converted to SymPy through the safe parser
  (or the LaTeX converter for lines with backslashes) where possible;
- ODEs "dx/dt = ...", "x' = ..." or "\\dot{x} = ...";
- parameter values "k = 200 N/m" (a number, optionally with a unit);
- stated results "we obtain T = 1.42 s" (a number after a result phrase).

Pages with almost no text are read with OCR when the vision module has it, and marked as such.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_PAGES_READ = 300
_NEAR_EMPTY_CHARS = 40

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>,;]+[^\s\"<>,;.)])", re.I)
ARXIV_RE = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
SECTION_RE = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z][A-Za-z ,\-]{1,60})|"
    r"(Abstract|Introduction|Background|Methods?|Model|Results|Discussion|Conclusions?|Acknowledge?ments|References|"
    r"Appendix(?: [A-Z])?))\s*$"
)
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*(?:[eE][-+]?\d+|[x×]\s*10\^?\{?[-+−]?\d+\}?))?"
ODE_RE = re.compile(
    r"^\s*(?:d\s*([A-Za-z]\w*)\s*/\s*dt|([A-Za-z]\w*)\s*'|\\dot\{([A-Za-z]\w*)\}|([A-Za-z]\w*)_t)\s*=\s*(.+?)\s*"
    r"(?:\((\d+)\))?\s*[,.;]?\s*$"
)
EQUATION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*(?:\([^()]*\))?)\s*=\s*(.+?)\s*(?:\((\d+)\))?\s*[,.;]?\s*$")
# A value is a number not followed by an operator: "T = 2*pi*sqrt(m/k)" and "f = 1/T" are equations, not values.
ASSIGNMENT_RE = re.compile(
    rf"(?<![\w.])([A-Za-z][A-Za-z0-9_]*(?:\([^()=]*\))?)\s*=\s*({_NUMBER})(?!\s*[*/^+\-]\s*[A-Za-z(])"
    r"\s*([A-Za-zµμΩ°][A-Za-zµμΩ°/^*·\-0-9]*|1/[A-Za-z][A-Za-z0-9^]*)?"
)
CLAIM_CUE_RE = re.compile(
    r"\b(we (?:obtain|find|get|measure|compute|calculate|report)|(?:is|was) found to be|yields?|gives?|results? in|"
    r"equals?|(?:is|are) (?:approximately|about)|we have|leads? to)\b",
    re.I,
)


def _num(text: str) -> float | None:
    t = text.replace("−", "-").replace(" ", "")
    m = re.match(r"^([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:[x×]10\^?\{?([-+]?\d+)\}?)?$", t)
    if m:
        base = float(m.group(1))
        return base * 10 ** int(m.group(2)) if m.group(2) else base
    try:
        return float(t)
    except ValueError:
        return None


def _unit(text: str) -> str:
    unit = (text or "").strip().strip(".,;:")
    if not unit or unit in ("-", "*", "^"):
        return ""
    return unit.replace("·", "*").replace("µ", "u").replace("μ", "u").replace("°C", "degC").replace("Ω", "ohm")


def _sympy_of(expression: str) -> tuple[str | None, str | None]:
    """(SymPy text, LaTeX) of the expression, parsed by the safe parser (LaTeX through the verifier's converter)."""
    text = expression.strip().rstrip(".,;")
    try:
        if "\\" in text:
            from tribos.verify.latex_math import parse_latex

            expr = parse_latex(text)
        else:
            from tribos.axiom.engine import safe_parse_expr

            expr = safe_parse_expr(text.replace("^", "**").replace("·", "*").replace("×", "*").replace("−", "-"))
        if expr is None:
            return None, None
        import sympy as sp

        return str(expr), sp.latex(expr)
    except Exception:  # noqa: BLE001 - an unparseable line is kept verbatim, never guessed at
        return None, None


def _page_texts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages[:MAX_PAGES_READ], start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("Page %d text extraction failed: %s", index, exc)
            text = ""
        pages.append({"page": index, "text": text, "ocr": False})
    info = {
        "title": str(meta.get("/Title") or "").strip() or None,
        "author": str(meta.get("/Author") or "").strip() or None,
        "n_pages": len(reader.pages),
    }
    return pages, info


def _ocr_near_empty(path: Path, pages: list[dict[str, Any]]) -> list[str]:
    """OCR the pages with (almost) no text layer, when the vision module can; notes on what happened."""
    empty = [p for p in pages if len(p["text"].strip()) < _NEAR_EMPTY_CHARS]
    if not empty:
        return []
    try:
        from tribos.vision import ocr

        if not ocr.available():
            return [f"{len(empty)} page(s) have no text layer and OCR is not installed, so they were not read."]
        from tribos.vision.reader import _pdf_pages

        images = _pdf_pages(path.read_bytes())[0]
        for p in empty:
            if p["page"] - 1 < len(images):
                p["text"] = ocr.read(images[p["page"] - 1]).markdown or ""
                p["ocr"] = True
        return [f"{len(empty)} page(s) were read with OCR; check their values against the PDF."]
    except Exception as exc:  # noqa: BLE001
        return [f"{len(empty)} page(s) have no text layer; OCR failed ({type(exc).__name__})."]


def _clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def extract_paper(path: str | Path) -> dict[str, Any]:
    """The paper's metadata, pages, sections, equations, ODEs, parameters and stated results (see the module doc)."""
    pdf = Path(path)
    pages, info = _page_texts(pdf)
    notes = _ocr_near_empty(pdf, pages)
    first_lines = _clean_lines(pages[0]["text"]) if pages else []
    title = info["title"] or (first_lines[0] if first_lines else None)
    authors = info["author"]
    if not authors and len(first_lines) > 1 and re.search(r"[A-Z][a-z]+ [A-Z]", first_lines[1]) and len(first_lines[1]) < 200:
        authors = first_lines[1]
    full_text = "\n".join(p["text"] for p in pages)
    doi = DOI_RE.search(full_text)
    arxiv = ARXIV_RE.search(full_text)

    sections: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    odes: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for p in pages:
        for line in _clean_lines(p["text"]):
            source = {"page": p["page"], "line": line[:400], **({"ocr": True} if p["ocr"] else {})}
            sec = SECTION_RE.match(line)
            if sec and len(line) < 70 and "=" not in line:
                sections.append({"number": sec.group(1), "title": (sec.group(2) or sec.group(3) or "").strip(), **source})
                continue
            ode = ODE_RE.match(line)
            if ode:
                state = next(g for g in ode.groups()[:4] if g)
                rhs = ode.group(5)
                sympy_text, latex = _sympy_of(rhs)
                odes.append({"state": state, "rhs": rhs, "sympy": sympy_text, "latex": latex, "number": ode.group(6),
                             **source})
                continue
            cue = CLAIM_CUE_RE.search(line)
            for m in ASSIGNMENT_RE.finditer(line):
                value = _num(m.group(2))
                if value is None:
                    continue
                item = {"name": m.group(1), "value": value, "unit": _unit(m.group(3)), "text": m.group(0).strip(), **source}
                # A number after a result phrase is a stated result; any other "name = number" is a parameter.
                (claims if cue and cue.start() < m.start() else parameters).append(item)
            eq = EQUATION_RE.match(line)
            if eq and not ASSIGNMENT_RE.fullmatch(line.strip().rstrip(".,;")):
                rhs = eq.group(2)
                if re.search(r"[A-Za-z]", rhs) and len(rhs) <= 300 and not cue:
                    sympy_text, latex = _sympy_of(rhs)
                    equations.append({"lhs": eq.group(1), "rhs": rhs, "sympy": sympy_text, "latex": latex,
                                      "number": eq.group(3), **source})
    return {
        "title": title,
        "authors": authors,
        "doi": doi.group(1) if doi else None,
        "arxiv_id": arxiv.group(1) if arxiv else None,
        "n_pages": info["n_pages"],
        "pages_read": len(pages),
        "pages": [{"page": p["page"], "chars": len(p["text"]), "ocr": p["ocr"]} for p in pages],
        "sections": sections,
        "equations": equations,
        "odes": odes,
        "parameters": parameters,
        "claims": claims,
        "notes": notes,
        "text": pages,
    }


__all__ = ["extract_paper"]
