"""
Files a question asks for ("as a Word report", "give me the Python script", "a CSV of the values"), built from the
final answer and attached to it as downloads.

Kinds and what each is built from:
- docx, pdf, md, ipynb: the whole answer, through the report exporter (tribos.export), citations included;
- py:   the answer's Python code blocks, else the code Tribos actually ran (the CodeAct cells that succeeded);
- csv:  the answer's Markdown tables (one file per table);
- xlsx: the answer's Markdown tables (one sheet per table);
- json: the computed results, else the answer's tables as records;
- png:  the answer's chart blocks (generative UI), drawn with matplotlib.

The writer is told which files were asked for (`writer_note`), so the answer carries what they need (a complete
script, the values as tables) instead of saying files cannot be made. A kind with nothing to build from is reported,
never invented. Files are stored per user (`store`) and served by GET /api/files/{id}.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

from .store import FileStore, get_file_store

KIND_LABELS = {
    "docx": "Word document", "pdf": "PDF", "md": "Markdown file", "ipynb": "Jupyter notebook", "py": "Python script",
    "csv": "CSV file", "xlsx": "Excel workbook", "json": "JSON file", "png": "PNG image",
}
MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8", "ipynb": "application/x-ipynb+json", "py": "text/x-python; charset=utf-8",
    "csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json", "png": "image/png",
}
TEXT_KINDS = {"md", "py", "csv", "json"}

_REQUEST_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("docx", re.compile(r"\b(?:docx|word\s+(?:doc(?:ument)?|file|report|format)|ms\s*word|in\s+word)\b", re.I)),
    ("pdf", re.compile(r"\bpdf\b", re.I)),
    ("md", re.compile(r"\b(?:markdown|\.md)\b", re.I)),
    ("ipynb", re.compile(r"\b(?:jupyter|ipynb|notebook)\b", re.I)),
    ("py", re.compile(r"\b(?:python\s+(?:code|script|file|program|implementation)|\.py\b|(?:code|script)\s+file|"
                      r"(?:give|write|send|provide|share)\s+(?:me\s+)?(?:the\s+)?(?:python\s+)?(?:code|script))", re.I)),
    ("csv", re.compile(r"\bcsv\b", re.I)),
    ("xlsx", re.compile(r"\b(?:excel|xlsx|spreadsheet|workbook)\b", re.I)),
    ("json", re.compile(r"\bjson\b", re.I)),
    ("png", re.compile(r"\b(?:png|(?:plot|chart|graph|figure)\s+(?:as\s+an?\s+)?(?:image|picture|file)|"
                       r"(?:image|picture)\s+of\s+the\s+(?:plot|chart|graph))\b", re.I)),
]
# "a downloadable report", "as a file": a report document when no format is named.
_GENERIC_FILE_RE = re.compile(r"\b(?:downloadable|as\s+a\s+(?:file|document)|download(?:\s+link)?)\b", re.I)


def requested_files(question: str) -> list[str]:
    """The file kinds a question asks for, in a stable order."""
    q = question or ""
    kinds = [kind for kind, pattern in _REQUEST_PATTERNS if pattern.search(q)]
    if not kinds and _GENERIC_FILE_RE.search(q):
        kinds = ["docx"]
    return kinds


def writer_note(kinds: list[str]) -> str:
    """The instruction that tells the writer which files will be built from its answer."""
    if not kinds:
        return ""
    names = ", ".join(KIND_LABELS[k] for k in kinds)
    needs = []
    if "py" in kinds or "ipynb" in kinds:
        needs.append("the complete, runnable code in one ```python block (imports included)")
    if {"csv", "xlsx", "json"} & set(kinds):
        needs.append("the values as Markdown tables with a header row and units in the headers")
    if "png" in kinds:
        needs.append('the plotted data as a ```ui chart block (its points from the computed results)')
    need_text = ("; it needs " + " and ".join(needs)) if needs else ""
    return (f'<requested_files note="built automatically from your answer and attached as downloads">The researcher '
            f"asked for: {names}{need_text}. Write that content into the answer itself; never say that files cannot "
            "be created or attached, and do not invent download links.</requested_files>\n\n")


# ------------------------------------------------------------------------------------------------- answer parts
_CODE_RE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S | re.I)
_UI_RE = re.compile(r"```ui\s*\n(.*?)```", re.S)


def python_code(answer: str, artifacts: dict[str, Any]) -> str:
    blocks = [b.strip() for b in _CODE_RE.findall(answer or "") if b.strip()]
    if blocks:
        return "\n\n\n".join(blocks) + "\n"
    cells = ((artifacts or {}).get("codeact") or {}).get("cells") or []
    ran = [str(c.get("code") or "").strip() for c in cells if isinstance(c, dict) and c.get("status") == "ok"]
    return ("\n\n\n".join(c for c in ran if c) + "\n") if any(ran) else ""


def _cell_text(cell: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda m: m.group(1) or m.group(2), cell.strip())
    return re.sub(r"`([^`]*)`", r"\1", text).strip()


def markdown_tables(answer: str) -> list[list[list[str]]]:
    """Every Markdown table in the answer as rows of cells (the header row first, the separator row dropped)."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in (answer or "").splitlines() + [""]:
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [_cell_text(c) for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                continue  # the |---|---| separator
            current.append(cells)
        elif current:
            if len(current) >= 2:
                tables.append(current)
            current = []
    return tables


def chart_blocks(answer: str, artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for raw in _UI_RE.findall(answer or ""):
        try:
            block = json.loads(raw)
        except ValueError:
            continue
        if isinstance(block, dict) and block.get("type") == "chart":
            out.append(block)
    panel = (artifacts or {}).get("answer_ui") or {}
    for block in panel.get("blocks") or [] if isinstance(panel, dict) else []:
        if isinstance(block, dict) and block.get("type") == "chart":
            out.append(block)
    return out


# ------------------------------------------------------------------------------------------------- builders
def _csv(table: list[list[str]]) -> bytes:
    import csv

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(table)
    return buf.getvalue().encode("utf-8-sig")  # the BOM makes Excel read the units' symbols correctly


def _xlsx(tables: list[list[list[str]]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.remove(wb.active)
    for i, table in enumerate(tables, 1):
        ws = wb.create_sheet(f"Table {i}")
        for r, row in enumerate(table, 1):
            for c, value in enumerate(row, 1):
                number = re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value.replace(",", ""))
                ws.cell(row=r, column=c, value=float(value.replace(",", "")) if number else value)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(48, max(10, *(len(str(c.value or "")) + 2 for c in col)))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _png(block: dict[str, Any]) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    for s in block.get("series") or []:
        pts = [p for p in s.get("points") or [] if isinstance(p, (list, tuple)) and len(p) == 2]
        if len(pts) >= 2:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], label=str(s.get("name") or ""))

    def label(axis: Any) -> str:
        axis = axis if isinstance(axis, dict) else {}
        unit = f" [{axis.get('unit')}]" if axis.get("unit") else ""
        return f"{axis.get('label') or ''}{unit}"

    ax.set_xlabel(label(block.get("x")))
    ax.set_ylabel(label(block.get("y")))
    if block.get("title"):
        ax.set_title(str(block["title"]))
    if len(block.get("series") or []) > 1:
        ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _report(kind: str, question: str, answer: str, artifacts: dict[str, Any], citations: dict[str, Any] | None,
            manifest: dict[str, Any] | None) -> bytes:
    from .. import export as exporter
    from ..export import build_report_model

    report = build_report_model(question, {"content": answer, "execution_artifacts": artifacts or {},
                                           "citations": citations or {}, "run_manifest": manifest or {}})
    render = {"docx": exporter.render_docx, "pdf": exporter.render_pdf, "md": exporter.render_markdown,
              "ipynb": exporter.render_notebook}[kind]
    return render(report)


def _slug(text: str) -> str:
    from ..utils.plain_math import plain_math

    # LaTeX commands are not words of the name: "\frac{x^2}{6}" would give "frac-x-2-6".
    plain = re.sub(r"\\[A-Za-z]+", " ", plain_math(text or ""))
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return slug[:40].rstrip("-") or "tribos"


def build_files(question: str, answer: str, kinds: list[str], *, artifacts: dict[str, Any] | None = None,
                citations: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None
                ) -> tuple[list[tuple[str, str, bytes]], list[str]]:
    """([(kind, filename, bytes)], [why a requested kind was not built])."""
    artifacts = artifacts or {}
    base = _slug(question.split("\n", 1)[0])
    files: list[tuple[str, str, bytes]] = []
    notes: list[str] = []
    tables = markdown_tables(answer)
    for kind in kinds:
        try:
            if kind in ("docx", "pdf", "md", "ipynb"):
                files.append((kind, f"{base}.{kind}", _report(kind, question, answer, artifacts, citations, manifest)))
            elif kind == "py":
                code = python_code(answer, artifacts)
                if code:
                    files.append((kind, f"{base}.py", code.encode("utf-8")))
                else:
                    notes.append("Python script: the answer has no Python code")
            elif kind == "csv":
                if not tables:
                    notes.append("CSV: the answer has no table")
                for i, table in enumerate(tables, 1):
                    suffix = f"-{i}" if len(tables) > 1 else ""
                    files.append((kind, f"{base}{suffix}.csv", _csv(table)))
            elif kind == "xlsx":
                if tables:
                    files.append((kind, f"{base}.xlsx", _xlsx(tables)))
                else:
                    notes.append("Excel: the answer has no table")
            elif kind == "json":
                computed = artifacts.get("computed_results")
                data: Any = computed if computed else [
                    [dict(zip(t[0], row, strict=False)) for row in t[1:]] for t in tables]
                if data:
                    files.append((kind, f"{base}.json", json.dumps(data, indent=2, ensure_ascii=False,
                                                                     default=str).encode("utf-8")))
                else:
                    notes.append("JSON: no computed results or tables to export")
            elif kind == "png":
                charts = chart_blocks(answer, artifacts)
                if not charts:
                    notes.append("PNG: the answer has no chart")
                for i, block in enumerate(charts[:4], 1):
                    suffix = f"-{i}" if len(charts) > 1 else ""
                    files.append((kind, f"{base}{suffix}.png", _png(block)))
        except Exception as exc:  # noqa: BLE001 - one failed file never costs the answer
            notes.append(f"{KIND_LABELS.get(kind, kind)} could not be built ({type(exc).__name__})")
    return files, notes


def save_files(user_id: str, files: list[tuple[str, str, bytes]], store: FileStore | None = None) -> list[dict[str, Any]]:
    """Store built files for the user; returns the entries the answer carries (id, name, kind, size, text preview)."""
    store = store or get_file_store()
    out = []
    for kind, name, data in files:
        meta = store.save(user_id, name, data, MEDIA_TYPES[kind])
        entry = {"id": meta["id"], "name": name, "kind": kind, "label": KIND_LABELS[kind], "size": len(data),
                 "url": f"/api/files/{meta['id']}"}
        if kind in TEXT_KINDS and len(data) <= 200_000:
            entry["text"] = data.decode("utf-8-sig", errors="replace")
        out.append(entry)
    return out


__all__ = ["KIND_LABELS", "MEDIA_TYPES", "build_files", "markdown_tables", "python_code", "requested_files",
           "save_files", "writer_note"]
