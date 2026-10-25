"""Reproducibility bundle: a zip of the report in every format plus the manifest (owned by EXPORT, feature 9)."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from .report_model import ReportModel, report_markdown

logger = logging.getLogger(__name__)


def _answer_markdown(report: ReportModel) -> str:
    return f"# {report.question or 'Question'}\n\n{report.answer_markdown}\n"


def _reproduce_md(report: ReportModel, manifest: dict[str, Any] | None, notes: list[str]) -> str:
    run_id = report.run_id or "<run_id>"
    lines = [
        "# Reproducing this run",
        "",
        "`manifest.json` lists every tool call Tribos made for this answer: the validated inputs, the output",
        "sha256 (volatile fields such as plots and timings removed), and key output fields, plus dataset hashes",
        "and upstream data-source versions that were current at the time. What a re-run repeats:",
        "",
        "- Simulations (Dynamis): the same system (preset or right-hand sides), parameters, initial state, time span",
        "  and integrator with its tolerances (rtol, atol), listed per call under Reproducibility in the report.",
        "- Symbolic results (Axiom): the same expressions and assumptions; they are exact and replay identically.",
        "- Sandboxed code (Calcula): the same program, identified by the sha256 of its source in the report; it",
        "  runs again in the sandbox with the same inputs and any attached dataset (by hash).",
        "- Reference data (Physis): physical constants come from the CODATA release the run used (shown in the",
        "  report); a newer release can move a constant within its stated uncertainty.",
        "- Literature (Archivon): the retrieved arXiv, DOI, zbMATH and MR identifiers are replayed as exact lookups;",
        "  a new preprint version or a withdrawn paper shows up as drift, never silently.",
        "",
        "## Re-run against the stored run",
        "",
        "If this server still holds the run, replay the recorded tool calls (no LLM) and compare:",
        "",
        "```bash",
        f'curl -X POST "$TRIBOS_API/api/runs/{run_id}/rerun" \\',
        '  -H "Authorization: Bearer $TRIBOS_TOKEN" -H "Content-Type: application/json" \\',
        "  -d '{\"mode\": \"tools\"}'",
        "```",
        "",
        'Use `{"mode": "full"}` to re-run the whole inquiry, including synthesis and verification, in an isolated',
        "thread that neither reads nor writes session memory. The answer text is then compared as a diff.",
        "",
        "## Re-run from this bundle",
        "",
        "Any Tribos server can replay the manifest itself (only registered tools are accepted, and the result",
        "is labelled as client supplied):",
        "",
        "```bash",
        "jq '{mode: \"tools\", manifest: .}' manifest.json > rerun_request.json",
        'curl -X POST "$TRIBOS_API/api/runs/rerun" \\',
        '  -H "Authorization: Bearer $TRIBOS_TOKEN" -H "Content-Type: application/json" \\',
        "  --data @rerun_request.json",
        "```",
        "",
        "## Reading the result",
        "",
        "- `identical`: every tool output hash matches.",
        "- `drifted`: only upstream evidence changed (new literature, a new preprint version, a new CODATA or data",
        "  release) or numbers moved within the verifier's 5% tolerance (for example a different BLAS or solver build).",
        "- `changed`: a tool's status changed or a computed value moved by more than 5%.",
        "",
        "LLM output is not deterministic, so a full re-run can word the answer differently even when every tool",
        "output is identical.",
    ]
    if manifest is None:
        lines += ["", "This answer carried no run manifest, so it cannot be replayed."]
    if notes:
        lines += ["", "## Notes on this bundle", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def render_bundle(report: ReportModel) -> bytes:
    from .docx_renderer import render_docx
    from .pdf_renderer import render_pdf

    notes: list[str] = []
    files: dict[str, bytes] = {}
    for name, fn in (("report.pdf", render_pdf), ("report.docx", render_docx)):
        try:
            files[name] = fn(report)
        except ImportError as exc:
            notes.append(f"{name} was skipped: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bundle renderer %s failed: %s", name, exc)
            notes.append(f"{name} could not be rendered ({type(exc).__name__}).")
    files["report.md"] = report_markdown(report, plot_path="simulation.png" if report.plot_png else None).encode("utf-8")
    files["answer.md"] = _answer_markdown(report).encode("utf-8")
    manifest = report.manifest
    if manifest:
        from tribos.provenance.run_manifest import client_view

        files["manifest.json"] = json.dumps(client_view(manifest), indent=2, ensure_ascii=False).encode("utf-8")
    files["sources.json"] = json.dumps([c.model_dump() for c in report.citations], indent=2, ensure_ascii=False).encode("utf-8")
    if report.result_record:
        # The computed results the answer was checked against, with the verification stamp (same revision as the cards).
        files["result_record.json"] = json.dumps(report.result_record, indent=2, ensure_ascii=False).encode("utf-8")
    if report.plot_png:
        files["simulation.png"] = report.plot_png
    files["REPRODUCE.md"] = _reproduce_md(report, manifest, notes).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()
