"""
The thesis: a research project's final report, written chapter by chapter from the charter and the ledger.

Model-written chapters (abstract, introduction, background, methods, results discussion, discussion, conclusion)
each get their own call, so no single call has to hold the whole report (an overlong reasoning pass returns
nothing). Everything that must be exact is assembled from the ledger, not written by the model: the research-design
tables and diagram, the results tables, the figures (sandbox plots and charts of the ledger series), the theorems and
proofs with their verification level, the references, the code appendix and the run record.

Every number in a model-written chapter is checked against the evidence (ledger values, the review, the goal);
a chapter with unsupported numbers gets one repair call, and any number still unsupported is listed in the thesis.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import re
from typing import Any

from .charter import charter_text
from .judge import STOP_TEXT
from .ledger import TIER_LABEL, evidence_numbers, ledger_text, unsupported_numbers
from .model import ResearchModel

logger = logging.getLogger(__name__)

WRITER_SYSTEM = """You write one chapter of a research thesis in Markdown, in the clear, precise style of a good mathematics or physics thesis.

Rules:
- Use only the evidence given (the plan, the findings ledger, the literature review). Every number you state must appear in that evidence exactly as given (you may round, stating "about"). Cite findings as (F3) and sources as [n] from the reference list.
- Separate what is proved, what is computed (and how strongly verified: Lean-verified, certified, replicated, computed), what the literature states, and what is conjectured or heuristic. A computation is evidence, not a proof. An open problem stays open.
- Mathematics in LaTeX ($...$ inline, $$...$$ display). Refer to tables and figures by the numbers given.
- Do not write the chapter heading; start with the body. Do not add a references list. No meta-commentary about the writing."""

CHAPTERS = [
    ("abstract", "Abstract", 220, "The abstract: the question, the approach, the main results with their key numbers and "
                                  "verification level, and the conclusion, in one paragraph."),
    ("introduction", "Introduction", 600, "Motivation, the precise research questions (one per deliverable), the "
                                          "contributions of this project, and an outline of the thesis."),
    ("background", "Background and related work", 900, "What is known: definitions, the main theorems (proved vs "
                                                       "conjectured) and methods from the literature review, with "
                                                       "citations [n]."),
    ("methods", "Methods", 700, "How each test was carried out: algorithms, parameters, exact versus floating-point "
                                "arithmetic, the independent re-implementation check, the formal proof attempts, and "
                                "the verification levels used."),
    ("results", "Results", 900, "The results deliverable by deliverable, with exact numbers, references to the tables "
                                "and figures listed, and for each hypothesis whether it is supported, refuted or "
                                "undecided, and why."),
    ("discussion", "Discussion", 600, "Interpretation, comparison with the literature and the heuristics, threats to "
                                      "validity (numerical artefacts, finite ranges, model assumptions), and what the "
                                      "numerics can and cannot show."),
    ("conclusion", "Conclusion", 350, "The answer to each research question, the open problems that remain, and the "
                                      "most valuable next steps."),
]


def _refs(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    from ..campaign import _merge_citations

    records = [{"citations": (campaign.get("review") or {}).get("citations") or {}}]
    records += [{"citations": f.get("citations") or {}} for f in campaign.get("ledger") or []]
    return _merge_citations(records)


def _q(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_q(v) for v in value[:12])
        return f"[{inner}{', …' if len(value) > 12 else ''}]"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_q(v)}" for k, v in list(value.items())[:10])
    return str(value)


def figures_and_tables(campaign: dict[str, Any], files_dir: str) -> tuple[list[dict], list[dict]]:
    """Numbered figures (sandbox plots, charts of series, the design diagram, the loop timeline) and tables."""
    from ...export.svgchart import design_diagram, line_chart, timeline

    os.makedirs(files_dir, exist_ok=True)
    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    design = design_diagram(campaign["charter"], campaign.get("ledger") or [])
    if design:
        with open(os.path.join(files_dir, "design.svg"), "w", encoding="utf-8") as fh:
            fh.write(design)
        figures.append({"file": "design.svg", "caption": "Research design: deliverables, the tests that settle them, "
                                                         "and the hypotheses they bear on (colour: status).",
                        "finding": None})
    for f in campaign.get("ledger") or []:
        if f.get("status") not in ("passed", "disputed"):
            continue
        seen_hashes: set[str] = set()
        for fig in f.get("figures") or []:
            try:
                import hashlib

                with open(os.path.join(files_dir, fig["name"]), "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                continue
            if digest in seen_hashes:
                continue  # the same plot captured twice (a replayed cell)
            seen_hashes.add(digest)
            cap = fig.get("title") or f"Plot produced by test {f['test_id']}"
            figures.append({"file": fig["name"], "caption": f"{cap} (finding {f['id']}, {TIER_LABEL.get(f.get('tier'), '')}).",
                            "finding": f["id"]})
        if f.get("series") and not f.get("figures"):  # the experiment's own plot already shows its data
            svg = line_chart(f["series"], title=f.get("series")[0].get("name") or "")
            if svg:
                name = f"{f['id']}_chart.svg"
                with open(os.path.join(files_dir, name), "w", encoding="utf-8") as fh:
                    fh.write(svg)
                figures.append({"file": name, "caption": f"Data of finding {f['id']} (test {f['test_id']}): "
                                                         + ", ".join(s["name"] for s in f["series"][:4]) + ".",
                                "finding": f["id"]})
        if f.get("quantities"):
            pairs = [q for q in f["quantities"] if isinstance(q["value"], list) and len(q["value"]) >= 5
                     and all(isinstance(v, list) and len(v) == len(q["value"][0]) for v in q["value"])]
            plain = [q for q in f["quantities"] if q not in pairs]
            if plain:
                tables.append({"finding": f["id"], "caption": f"Values computed by test {f['test_id']} (finding "
                                                              f"{f['id']}, {TIER_LABEL.get(f.get('tier'), '')}).",
                               "rows": [(q["name"].replace("_", " "), _q(q["value"])) for q in plain[:30]]})
            for q in pairs:
                # A table of pairs (record holders and their values) is printed in full, one row per entry.
                width = len(q["value"][0])
                tables.append({"finding": f["id"], "caption": f"{q['name'].replace('_', ' ').capitalize()} "
                                                              f"({len(q['value'])} rows; finding {f['id']}, "
                                                              f"{TIER_LABEL.get(f.get('tier'), '')}).",
                               "header": ["#"] + [f"column {i + 1}" for i in range(width)],
                               "rows": [(str(i + 1), *[_q(x) for x in row]) for i, row in enumerate(q["value"][:300])]})
    tl = timeline(campaign.get("rounds") or [])
    if tl:
        with open(os.path.join(files_dir, "timeline.svg"), "w", encoding="utf-8") as fh:
            fh.write(tl)
        figures.append({"file": "timeline.svg", "caption": "The research loop: rounds, their length and whether they "
                                                           "made progress.", "finding": None})
    for i, fig in enumerate(figures, 1):
        fig["n"] = i
    for i, t in enumerate(tables, 1):
        t["n"] = i
    return figures, tables


def _context(campaign: dict[str, Any], refs: list[dict[str, Any]], figures: list[dict], tables: list[dict]) -> str:
    review = str((campaign.get("review") or {}).get("response") or "")
    analyses = [r.get("analysis") or "" for r in campaign.get("rounds") or []]
    loop = campaign.get("loop") or {}
    parts = [f"Research goal:\n{campaign['goal']}", "", charter_text(campaign["charter"]), "",
             "Findings ledger:", ledger_text(campaign.get("ledger") or [], limit_chars=30000), "",
             f"How the project ended: {STOP_TEXT.get(loop.get('stop_reason') or '', loop.get('stop_reason') or '')}",
             "", "Latest critical analysis:", (analyses[-1] if analyses else "(none)")[:5000], "",
             "Literature review (stage 1):", review[:14000], "",
             "Tables available: " + "; ".join(f"Table {t['n']}: {t['caption']}" for t in tables),
             "Figures available: " + "; ".join(f"Figure {f['n']}: {f['caption']}" for f in figures), "",
             "References:\n" + "\n".join(f"[{i}] {c.get('title') or c.get('key')}" for i, c in enumerate(refs[:80], 1))]
    return "\n".join(parts)


async def _chapter(model: ResearchModel, key: str, title: str, words: int, brief: str, context: str,
                   evidence: set[str], effort: str) -> dict[str, Any]:
    user = f"{context}\n\nWrite the chapter \"{title}\" (about {words} words). {brief}"
    try:
        text = await model.text(WRITER_SYSTEM, user, effort=effort, max_tokens=32000)
    except Exception as exc:  # noqa: BLE001 - one chapter failing never loses the thesis
        logger.warning("thesis chapter %s failed: %s", key, exc)
        return {"key": key, "title": title, "markdown": f"*This chapter could not be written ({type(exc).__name__}).*",
                "unverified": []}
    bad = unsupported_numbers(text, evidence)
    if bad:
        fix = (f"{user}\n\nYour draft:\n{text}\n\nThese numbers are not in the evidence: {', '.join(bad)}. Rewrite the "
               "chapter so that every number is one the evidence states (or remove it). Reply with the chapter only.")
        try:
            text2 = await model.text(WRITER_SYSTEM, fix, effort=effort, max_tokens=32000)
            if text2.strip():
                text, bad = text2, unsupported_numbers(text2, evidence)
        except Exception as exc:  # noqa: BLE001
            logger.info("thesis repair of %s failed: %s", key, exc)
    return {"key": key, "title": title, "markdown": text.strip(), "unverified": bad}


def _cell(text: Any) -> str:
    """Text safe inside a Markdown table cell: no pipes, no line breaks."""
    return str(text if text is not None else "").replace("|", "∣").replace("\n", " ").strip()


def _design_md(campaign: dict[str, Any], figures: list[dict]) -> str:
    ch = campaign["charter"]
    lines = [ch.get("summary") or "", "", "**Deliverables.**", "", "| | Deliverable | Done when | Required level | Status |",
             "|---|---|---|---|---|"]
    lines += [f"| {d['id']} | {_cell(d['title'])} | {_cell(d['acceptance'])} | {TIER_LABEL.get(d['tier'], d['tier'])} | "
              f"{d['status']} |" for d in ch["deliverables"]]
    if ch["hypotheses"]:
        lines += ["", "**Hypotheses.**", "", "| | Hypothesis | Refuted if | Verdict |", "|---|---|---|---|"]
        lines += [f"| {h['id']} | {_cell(h['statement'])} | {_cell(h['falsification'])} | **{h['verdict']}** |"
                  for h in ch["hypotheses"]]
    lines += ["", "**Tests.**", "", "| | Test | Kind | Serves | Status |", "|---|---|---|---|---|"]
    lines += [f"| {t['id']} | {_cell(t['title'])} | {t['kind']} | {', '.join(t['serves'] + t['hypotheses']) or '–'} | {t['status']} |"
              for t in ch["tests"]]
    design = next((f for f in figures if f["file"] == "design.svg"), None)
    if design:
        lines += ["", f"![Figure {design['n']}. {design['caption']}](files/design.svg)"]
    return "\n".join(lines)


def _results_md(tables: list[dict], figures: list[dict]) -> str:
    out = []
    for t in tables:
        header = t.get("header") or ["Quantity", "Value"]
        out += ["", f"*Table {t['n']}. {t['caption']}*", "", "| " + " | ".join(header) + " |",
                "|" + "---|" * len(header)]
        out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in t["rows"]]
    for f in figures:
        if f["finding"]:
            out += ["", f"![Figure {f['n']}. {f['caption']}](files/{f['file']})"]
    return "\n".join(out)


_PROVE_PREFIX_RE = re.compile(r"^\s*(?:prove|show|establish)\s+(?:that\s+)?", re.I)


def _statement(text: str) -> str:
    """A theorem's statement without the test's instruction verb ("Prove that ..." -> "...")."""
    s = _PROVE_PREFIX_RE.sub("", (text or "").strip(), count=1)
    return s[:1].upper() + s[1:] if s else s


def best_proofs(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    """One finding per prove test: its strongest attempt (Lean-verified first, then the latest written proof).
    Attempts that produced no proof (a failed or cut-off run) are not theorems."""
    from .ledger import rank

    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for f in campaign.get("ledger") or []:
        p = f.get("proof") or {}
        if not p or f.get("status") not in ("passed", "refuted") or not (p.get("text") or p.get("lean_code")):
            continue
        tid = str(f.get("test_id"))
        if tid not in best:
            order.append(tid)
            best[tid] = f
        elif rank(f.get("tier")) >= rank(best[tid].get("tier")):
            best[tid] = f
    return [best[t] for t in order]


def _proofs_md(campaign: dict[str, Any]) -> str:
    proofs = best_proofs(campaign)
    if not proofs:
        return "No statement in this project reached a written or formal proof."
    out = []
    for i, f in enumerate(proofs, 1):
        p = f["proof"]
        if p.get("lean_status") == "verified":
            level = "Lean-verified"
        else:
            lean = {"failed": "Lean check failed", "unavailable": "Lean check unavailable"}.get(
                str(p.get("lean_status") or ""), "not checked in Lean")
            level = f"written proof; {lean}"
        out += [f"**Theorem {i}** ({level}; finding {f['id']}). {_statement(p['statement'])}", ""]
        if p.get("text"):
            out += [p["text"].strip(), ""]
        if p.get("lean_code"):
            out += [f"The Lean 4 proof is given in Appendix A (A.{f['id']}).", ""]
        out.append("")
    return "\n".join(out)


LISTING_LINES = 45


def _listing(code: str, limit: int = LISTING_LINES) -> str:
    lines = code.strip().splitlines()
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:limit] + [f"# … {len(lines) - limit} more lines in the reproducibility bundle"])


def _appendix_code(campaign: dict[str, Any]) -> str:
    out = ["The core of the code behind every computed value, as run in the Tribos sandbox. The complete code of every "
           "finding and of its independent re-implementation, the Lean sources and the findings ledger are in the "
           "reproducibility bundle (export: Bundle)."]
    for f in campaign.get("ledger") or []:
        if f.get("status") not in ("passed", "disputed"):
            continue
        cells = [c["code"] for c in f.get("cells") or [] if c.get("status") == "ok"]
        lean = (f.get("proof") or {}).get("lean_code")
        if not cells and not lean:
            continue
        out += ["", f"### A.{f['id']} — test {f['test_id']} ({TIER_LABEL.get(f.get('tier'), '')})", ""]
        if cells:
            # The last cell holds the computation that set the result; earlier cells are exploration.
            out += ["```python", _listing(cells[-1] if len(cells[-1]) > 200 else "\n\n".join(cells)), "```"]
        if (f.get("replication") or {}).get("code"):
            rep = f["replication"]
            out += ["", f"Independently re-implemented: {rep.get('agree', 0)} quantities agree, "
                        f"{max(0, int(rep.get('disagree') or 0) - int(rep.get('missing') or 0))} differ "
                        "(full code in the bundle)."]
        if lean:
            out += ["", "```lean", lean.strip()[:12000], "```"]
    return "\n".join(out)


def _appendix_runs(campaign: dict[str, Any]) -> str:
    loop = campaign.get("loop") or {}
    rows = ["| Round | Tests | Progress | Concluded | Duration |", "|---|---|---|---|---|"]
    for r in campaign.get("rounds") or []:
        rows.append(f"| {r.get('round')} | {', '.join(r.get('tests') or []) or '–'} | {'yes' if r.get('progress') else 'no'} "
                    f"| {'yes' if r.get('concluded') else 'no'} | {int(float(r.get('seconds') or 0) // 60)} min |")
    ledger_rows = ["| Finding | Test | Status | Verification | Seconds |", "|---|---|---|---|---|"]
    ledger_rows += [f"| {f['id']} | {f['test_id']} | {f['status']} | {TIER_LABEL.get(f.get('tier'), '')} | {f.get('seconds') or ''} |"
                    for f in campaign.get("ledger") or []]
    return "\n".join([f"Stop reason: {STOP_TEXT.get(loop.get('stop_reason') or '', loop.get('stop_reason') or 'n/a')}",
                      "", *rows, "", *ledger_rows, "",
                      f"Model: {campaign.get('model') or 'default'}. Research ID: `{campaign['campaign_id']}`."])


def _references_md(refs: list[dict[str, Any]]) -> str:
    if not refs:
        return "No published sources were cited."
    out = []
    for i, c in enumerate(refs[:80], 1):
        title = str(c.get("title") or c.get("key") or c.get("url") or "source").strip()
        meta = ", ".join(str(c[k]) for k in ("authors", "journal", "year") if c.get(k))
        url = str(c.get("url") or "").strip()
        out.append(f"[{i}] {title}" + (f". {meta}" if meta else "") + (f". <{url}>" if url else ""))
    return "\n\n".join(out)


async def write_thesis(model: ResearchModel, campaign: dict[str, Any], files_dir: str, *, effort: str = "medium",
                       parallel: int = 3) -> dict[str, Any]:
    refs = _refs(campaign)
    figures, tables = figures_and_tables(campaign, files_dir)
    context = _context(campaign, refs, figures, tables)
    review = str((campaign.get("review") or {}).get("response") or "")
    evidence = evidence_numbers(campaign["goal"], review, charter_text(campaign["charter"]),
                                *[r.get("analysis") or "" for r in campaign.get("rounds") or []],
                                ledger=campaign.get("ledger") or [])
    for t in tables:
        for row in t["rows"]:
            evidence |= evidence_numbers(*[str(c) for c in row])
    sem = asyncio.Semaphore(max(1, parallel))

    async def one(spec: tuple) -> dict[str, Any]:
        async with sem:
            return await _chapter(model, *spec, context=context, evidence=evidence, effort=effort)

    written = await asyncio.gather(*(one(c) for c in CHAPTERS))
    by = {c["key"]: c for c in written}
    title = campaign.get("title") or "Research project"
    when = _dt.datetime.fromtimestamp(campaign.get("created_at") or 0, tz=_dt.UTC).strftime("%d %B %Y")
    chapters = [
        {"key": "abstract", "title": "Abstract", "markdown": by["abstract"]["markdown"]},
        {"key": "introduction", "title": "1 Introduction", "markdown": by["introduction"]["markdown"]},
        {"key": "background", "title": "2 Background and related work", "markdown": by["background"]["markdown"]},
        {"key": "design", "title": "3 Hypotheses and research design", "markdown": _design_md(campaign, figures)},
        {"key": "methods", "title": "4 Methods", "markdown": by["methods"]["markdown"]},
        {"key": "results", "title": "5 Results", "markdown": by["results"]["markdown"] + "\n" + _results_md(tables, figures)},
        {"key": "proofs", "title": "6 Theorems and proofs", "markdown": _proofs_md(campaign)},
        {"key": "discussion", "title": "7 Discussion", "markdown": by["discussion"]["markdown"]},
        {"key": "conclusion", "title": "8 Conclusion", "markdown": by["conclusion"]["markdown"]},
        {"key": "references", "title": "References", "markdown": _references_md(refs)},
        {"key": "appendix_code", "title": "Appendix A. Code and formal proofs", "markdown": _appendix_code(campaign)},
        {"key": "appendix_runs", "title": "Appendix B. Run record", "markdown": _appendix_runs(campaign)},
    ]
    unverified = sorted({n for c in written for n in c.get("unverified") or []})
    if unverified:
        chapters[-1]["markdown"] += ("\n\nNumbers in the text that the automatic check could not match to the evidence: "
                                     + ", ".join(unverified[:40]) + ".")
    tl = next((f for f in figures if f["file"] == "timeline.svg"), None)
    if tl is not None:
        chapters[-1]["markdown"] += f"\n\n![Figure {tl['n']}. {tl['caption']}](files/timeline.svg)"
    md = [f"# {title}", "", f"*A research thesis produced by Tribos · {when} · Research ID `{campaign['campaign_id']}`*", ""]
    for c in chapters:
        md += [f"## {c['title']}", "", c["markdown"].strip(), ""]
    return {"status": "succeeded", "title": title, "markdown": "\n".join(md).strip() + "\n", "chapters": chapters,
            "figures": figures, "tables": [{"n": t["n"], "caption": t["caption"]} for t in tables],
            "references": len(refs), "unverified": unverified, "written_at": _dt.datetime.now(_dt.UTC).timestamp()}


__all__ = ["CHAPTERS", "figures_and_tables", "write_thesis"]
