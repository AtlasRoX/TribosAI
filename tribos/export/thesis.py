"""
Thesis exports for research projects: typeset HTML, PDF, DOCX, Markdown and a reproducibility bundle.

- HTML: the thesis Markdown rendered with KaTeX math, numbered figures (sandbox plots and SVG charts embedded as
  data URIs, so the file stands alone), tables, theorem/proof styling, code listings, a title page and a table of
  contents. Print CSS sets A4 pages.
- PDF: that HTML printed by headless Chromium (Playwright), with running header and page numbers; KaTeX renders
  from the vendored copy in assets/katex, so no network is needed. When Chromium is unavailable
  (TRIBOS_THESIS_PDF_ENGINE=fpdf, or no browser), fpdf2 writes a plainer PDF and says so on its first page.
- DOCX: python-docx through the report renderer's Markdown writer, with PNG figures inserted.
- bundle: a zip with thesis.md, the figures, every finding's code (.py) and Lean proofs (.lean), and ledger.json.
"""

from __future__ import annotations

import base64
import datetime as _dt
import functools
import html
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).parent / "assets" / "katex"
_IMG_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)\s*$", re.M)
_SAFE_FILE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


@functools.lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    from .markdown_blocks import _math_span

    md = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
    md.inline.ruler.before("escape", "math_span", _math_span)
    return md


def _data_uri(path: str) -> str | None:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    mime = "image/svg+xml" if path.endswith(".svg") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _font_faces() -> str:
    """Google Sans (text) and Google Sans Code (listings), embedded so the HTML and PDF need no font install."""
    return _font_css()


@functools.lru_cache(maxsize=1)
def _font_css() -> str:
    fonts = Path(__file__).parent / "fonts"
    faces = [("Google Sans", "GoogleSans-Regular.ttf", 400, "normal"), ("Google Sans", "GoogleSans-Italic.ttf", 400, "italic"),
             ("Google Sans", "GoogleSans-Medium.ttf", 500, "normal"), ("Google Sans", "GoogleSans-Bold.ttf", 700, "normal"),
             ("Google Sans", "GoogleSans-BoldItalic.ttf", 700, "italic"),
             ("Google Sans Code", "GoogleSansCode-Regular.ttf", 400, "normal"),
             ("Google Sans Code", "GoogleSansCode-Bold.ttf", 700, "normal")]
    out = []
    for family, name, weight, style in faces:
        path = fonts / name
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        out.append(f"@font-face {{ font-family: '{family}'; src: url(data:font/ttf;base64,{data}) format('truetype'); "
                   f"font-weight: {weight}; font-style: {style}; font-display: block; }}")
    return "\n".join(out)


@functools.lru_cache(maxsize=4)
def _brand_uri(name: str) -> str:
    return _data_uri(str(Path(__file__).parent / "assets" / name)) or ""


def _figure_html(alt: str, files_dir: str, name: str) -> str:
    """One numbered figure: SVG inline (so it is set in Google Sans), PNG embedded as a data URI."""
    path = os.path.join(files_dir, name)
    num, _, caption = alt.partition(". ")
    label = html.escape(num) if num.startswith("Figure") else ""
    cap = html.escape(caption if label else alt)
    if name.endswith(".svg") and os.path.exists(path):
        try:
            svg = Path(path).read_text(encoding="utf-8")
        except OSError:
            svg = ""
        svg = re.sub(r"<\?xml[^>]*>", "", svg)
        art = f'<div class="art svg">{svg}</div>' if svg.lstrip().startswith("<svg") else ""
    else:
        uri = _data_uri(path) if os.path.exists(path) else None
        art = f'<div class="art"><img src="{uri}" alt="{html.escape(alt)}"/></div>' if uri else ""
    if not art:
        return f'<p class="missing">[{html.escape(alt)}]</p>'
    return (f'<figure class="fig">{art}<figcaption>' + (f"<b>{label}.</b> " if label else "") + f"{cap}</figcaption></figure>")


def _render_chapter(markdown: str, files_dir: str) -> str:
    # Figures are swapped for placeholders so the Markdown parser (raw HTML off) never sees HTML.
    figs: list[str] = []

    def keep(m: re.Match[str]) -> str:
        src = m.group("src").strip()
        name = src.split("/", 1)[1] if src.startswith("files/") else ""
        figs.append(_figure_html(m.group("alt"), files_dir, name) if _SAFE_FILE.match(name or "")
                    else f'<p class="missing">[{html.escape(m.group("alt"))}]</p>')
        return f"\n\nTRIBOSFIGURE{len(figs) - 1}\n\n"

    body = _parser().render(_IMG_RE.sub(keep, markdown or ""))
    for i, f in enumerate(figs):
        body = body.replace(f"<p>TRIBOSFIGURE{i}</p>", f)
    # Theorem statements and proofs written by the thesis assembler get theorem styling.
    body = re.sub(r"<p><strong>(Theorem \d+)</strong> \(([^)]*)\)\.?", lambda m: (
        f'<p class="thm"><span class="thm-label">{m.group(1)}</span><span class="thm-tier'
        f'{" lean" if "Lean-verified" in m.group(2) else ""}">{m.group(2)}</span><br>'), body)
    body = body.replace("<p><strong>Proof.</strong>", '<p class="proof"><em>Proof.</em>')
    body = re.sub(r"<table>", '<div class="table"><table>', body)
    body = body.replace("</table>", "</table></div>")
    return body


CSS = """
@page { size: A4; margin: 24mm 0 20mm 0; }
@page cover { margin: 0; }
:root { --navy: #181e48; --ink: #1d2433; --muted: #5d6475; --faint: #8a90a0; --rule: #e3e5ec; --tint: #f3f4f9;
        --accent: #3949ab; --lean: #5b3fa8; --replicated: #0f6e6a; --certified: #1d6fa5; --computed: #4b5563;
        --sourced: #b4531f; --reasoned: #8a90a0; }
* { box-sizing: border-box; }
html, body { background: #fff; }
body { font-family: 'Google Sans', 'Segoe UI', system-ui, sans-serif; color: var(--ink); font-size: 10.2pt;
       line-height: 1.6; margin: 0; -webkit-font-smoothing: antialiased; font-feature-settings: "tnum" 0; }
.page { padding: 0 22mm; }
h2.chapter { break-before: page; margin: 0 0 7mm; padding: 0; font-weight: 500; font-size: 22pt; color: var(--navy);
             letter-spacing: -0.01em; line-height: 1.15; }
h2.chapter .num { display: block; font-size: 9pt; letter-spacing: .18em; text-transform: uppercase; color: var(--accent);
                  font-weight: 500; margin-bottom: 3mm; }
h2.chapter::after { content: ""; display: block; width: 18mm; height: 2.2px; background: var(--accent); margin-top: 5mm; }
h3, h4 { font-weight: 500; color: var(--navy); margin: 7mm 0 2mm; font-size: 12.5pt; }
p { margin: 0 0 3.2mm; }
strong { font-weight: 700; color: var(--navy); }
a { color: var(--accent); text-decoration: none; }
ul, ol { padding-left: 6mm; margin: 0 0 3.2mm; }
li { margin-bottom: 1.2mm; }
.table { margin: 4mm 0 6mm; break-inside: avoid; border: 1px solid var(--rule); border-radius: 3mm; overflow: hidden; }
table { border-collapse: collapse; width: 100%; font-size: 8.8pt; line-height: 1.45; }
thead th { background: var(--navy); color: #fff; text-align: left; font-weight: 500; letter-spacing: .02em;
           padding: 2.2mm 3mm; font-size: 8.4pt; }
td { padding: 2mm 3mm; border-top: 1px solid var(--rule); vertical-align: top; font-variant-numeric: tabular-nums; }
tbody tr:nth-child(even) td { background: #fafbfd; }
code { font-family: 'Google Sans Code', Consolas, monospace; font-size: 8.4pt; background: var(--tint); padding: .2mm 1.2mm;
       border-radius: 1.2mm; color: var(--navy); }
pre { background: #f7f8fc; border: 1px solid var(--rule); border-left: 3px solid var(--accent); border-radius: 0 2mm 2mm 0;
      padding: 3.5mm 4mm; font-size: 7.6pt; line-height: 1.45; white-space: pre-wrap; word-break: break-word; margin: 3mm 0 5mm; }
pre code { background: none; padding: 0; font-size: inherit; color: var(--ink); }
figure.fig { margin: 5mm 0 7mm; break-inside: avoid; }
figure.fig .art { border: 1px solid var(--rule); border-radius: 3mm; padding: 4mm; background: #fff; text-align: center; }
figure.fig .art img { max-width: 100%; max-height: 115mm; }
figure.fig .art.svg svg { width: 100%; height: auto; max-height: 125mm; }
figcaption { font-size: 8.6pt; color: var(--muted); margin-top: 2.4mm; line-height: 1.5; }
figcaption b { color: var(--navy); font-weight: 500; }
p.thm { background: var(--tint); border-left: 3px solid var(--accent); border-radius: 0 2.5mm 2.5mm 0; padding: 3.5mm 4.5mm;
        margin: 6mm 0 3mm; break-inside: avoid; }
.thm-label { font-weight: 700; color: var(--navy); margin-right: 2.5mm; }
.thm-tier { font-size: 7.6pt; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); border: 1px solid var(--rule);
            border-radius: 99px; padding: .4mm 2.4mm; background: #fff; }
.thm-tier.lean { color: #fff; background: var(--lean); border-color: var(--lean); }
p.proof em { font-weight: 500; color: var(--navy); }
blockquote { margin: 4mm 0; padding: 1mm 5mm; border-left: 3px solid var(--rule); color: var(--muted); }
.missing { color: var(--faint); font-style: italic; }
.katex { font-size: 1.04em; }
.katex-display { margin: 3mm 0; overflow: hidden; }

/* Cover ------------------------------------------------------------------------------------------------------ */
.cover { page: cover; height: 297mm; position: relative; overflow: hidden; background: var(--navy); color: #fff;
         padding: 26mm 22mm 22mm; display: flex; flex-direction: column; }
.cover .brand { display: flex; align-items: center; gap: 4mm; }
.cover .brand img.mark { height: 13mm; filter: brightness(0) invert(1); }
.cover .brand img.word { height: 8mm; filter: brightness(0) invert(1); }
.cover .rings { position: absolute; right: -42mm; top: 46mm; width: 170mm; height: 170mm; opacity: .16; }
.cover .kicker { margin-top: 52mm; font-size: 9pt; letter-spacing: .22em; text-transform: uppercase; color: #aab4ff; }
.cover h1 { font-size: 31pt; line-height: 1.12; font-weight: 500; margin: 5mm 0 7mm; max-width: 150mm; letter-spacing: -0.015em; }
.cover .goal { font-size: 10.6pt; line-height: 1.6; color: #d7dbf5; max-width: 140mm; border-left: 2px solid #6f7ad6;
               padding-left: 5mm; }
.cover .facts { margin-top: auto; display: grid; grid-template-columns: repeat(4, 1fr); gap: 4mm; }
.cover .fact { border-top: 1px solid rgba(255,255,255,.28); padding-top: 3mm; }
.cover .fact b { display: block; font-size: 17pt; font-weight: 500; }
.cover .fact span { font-size: 8pt; color: #b9c0ee; letter-spacing: .04em; }
.cover .foot { margin-top: 10mm; display: flex; justify-content: space-between; font-size: 8pt; color: #b9c0ee; }
.cover .foot code { background: rgba(255,255,255,.1); color: #fff; }

/* Contents ---------------------------------------------------------------------------------------------------- */
.toc { break-before: page; }
.toc h2 { font-size: 22pt; font-weight: 500; color: var(--navy); margin: 0 0 8mm; }
.toc ol { list-style: none; padding: 0; margin: 0; counter-reset: none; }
.toc li { display: flex; align-items: baseline; gap: 4mm; padding: 2.6mm 0; border-bottom: 1px solid var(--rule); font-size: 11pt; margin: 0; }
.toc li .n { width: 10mm; color: var(--accent); font-weight: 500; font-size: 9.5pt; }
.toc li a { color: var(--ink); }
.toc .note { margin-top: 10mm; font-size: 8.8pt; color: var(--muted); max-width: 130mm; }

/* At a glance -------------------------------------------------------------------------------------------------- */
.glance { margin-top: 12mm; }
.glance h2 { font-size: 22pt; font-weight: 500; color: var(--navy); margin: 0 0 2mm; }
.glance .headline { font-size: 12pt; color: var(--ink); margin: 0 0 7mm; line-height: 1.5; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3.5mm; margin-bottom: 7mm; }
.tile { border: 1px solid var(--rule); border-radius: 3mm; padding: 3.5mm 4mm; break-inside: avoid; }
.tile .k { font-size: 7.8pt; color: var(--muted); letter-spacing: .03em; }
.tile .v { font-size: 14pt; font-weight: 500; color: var(--navy); margin-top: 1mm; word-break: break-all; line-height: 1.25; }
.tile .t { font-size: 7.2pt; margin-top: 1.5mm; display: inline-block; border-radius: 99px; padding: .3mm 2.2mm; color: #fff; }
.t.formal { background: var(--lean); } .t.replicated { background: var(--replicated); } .t.certified { background: var(--certified); }
.t.computed { background: var(--computed); } .t.sourced { background: var(--sourced); } .t.reasoned, .t.none { background: var(--reasoned); }
.checklist { list-style: none; padding: 0; margin: 0 0 6mm; }
.checklist li { display: flex; gap: 3mm; padding: 2.2mm 0; border-bottom: 1px solid var(--rule); font-size: 9.6pt; }
.checklist .s { flex: 0 0 22mm; font-size: 7.6pt; text-transform: uppercase; letter-spacing: .06em; font-weight: 500; padding-top: .6mm; }
.s.done, .s.supported { color: var(--replicated); } .s.partial, .s.undecided { color: #b7791f; }
.s.open, .s.untested { color: var(--faint); } .s.refuted, .s.infeasible { color: #b23b3b; }
.glance h3 { font-size: 10pt; letter-spacing: .14em; text-transform: uppercase; color: var(--accent); margin: 6mm 0 2mm; font-weight: 500; }
@media screen { body { background: #eef0f6; } .page, .cover { max-width: 210mm; margin: 0 auto; background: #fff; }
                .page { padding: 16mm 22mm; } .cover { height: auto; min-height: 297mm; } h2.chapter { margin-top: 14mm; } }
"""

_RINGS = ("<svg class='rings' viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'>"
          + "".join(f"<circle cx='100' cy='100' r='{r}' fill='none' stroke='#fff' stroke-width='{w}'/>"
                    for r, w in ((96, .6), (78, .9), (60, 1.2), (42, 1.5), (24, 1.8)))
          + "<circle cx='100' cy='4' r='3' fill='#aab4ff'/><circle cx='178' cy='100' r='2.4' fill='#aab4ff'/>"
          + "<circle cx='58' cy='100' r='2' fill='#aab4ff'/></svg>")


def _tier_counts(campaign: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in campaign.get("ledger") or []:
        if f.get("status") == "passed":
            counts[f.get("tier") or "none"] = counts.get(f.get("tier") or "none", 0) + 1
    return counts


def _duration(campaign: dict[str, Any]) -> str:
    """Active research time (time paused is not research); older records fall back to start to finish."""
    loop = campaign.get("loop") or {}
    if loop.get("active_s"):
        seconds = float(loop["active_s"])
    else:
        start = float(loop.get("started_at") or campaign.get("created_at") or 0)
        seconds = float(campaign.get("finished_at") or (campaign.get("thesis") or {}).get("written_at") or start) - start
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"


def _glance_html(campaign: dict[str, Any]) -> str:
    from ..agentic.research.ledger import TIER_LABEL, rank

    charter = campaign.get("charter") or {}
    rounds = campaign.get("rounds") or []
    headline = next((r.get("headline") for r in reversed(rounds) if r.get("headline")), "")
    tiles = []
    for f in sorted(campaign.get("ledger") or [], key=lambda f: -rank(f.get("tier"))):
        if f.get("status") != "passed":
            continue
        for q in f.get("quantities") or []:
            v = q.get("value")
            if isinstance(v, bool) or not isinstance(v, (int, float, str)) or len(str(v)) > 28:
                continue
            shown = f"{v:.8g}" if isinstance(v, float) else str(v)
            tier = f.get("tier") or "none"
            tiles.append(f'<div class="tile"><div class="k">{html.escape(q["name"].replace("_", " "))} · {f["id"]}</div>'
                         f'<div class="v">{html.escape(shown)}</div><span class="t {tier}">{TIER_LABEL.get(tier, tier)}</span></div>')
            if len(tiles) >= 9:
                break
        if len(tiles) >= 9:
            break
    deliver = "".join(f'<li><span class="s {d.get("status", "open")}">{html.escape(d.get("status", "open"))}</span>'
                      f'<span><b>{d["id"]}</b> {html.escape(d["title"])}'
                      + (f' <span style="color:var(--muted)">— {html.escape(d["note"])}</span>' if d.get("note") else "")
                      + "</span></li>" for d in charter.get("deliverables") or [])
    hyps = "".join(f'<li><span class="s {h.get("verdict", "untested")}">{html.escape(h.get("verdict", "untested"))}</span>'
                   f'<span><b>{h["id"]}</b> {html.escape(h["statement"])}</span></li>' for h in charter.get("hypotheses") or [])
    return ('<section class="glance" id="glance"><h2>At a glance</h2>'
            + (f'<p class="headline">{html.escape(headline)}</p>' if headline else "")
            + (f'<h3>Key results</h3><div class="tiles">{"".join(tiles)}</div>' if tiles else "")
            + (f'<h3>Deliverables</h3><ul class="checklist">{deliver}</ul>' if deliver else "")
            + (f'<h3>Hypotheses</h3><ul class="checklist">{hyps}</ul>' if hyps else "") + "</section>")


def thesis_html(campaign: dict[str, Any], files_dir: str, *, katex_href: str | None = None,
                note: str = "") -> str:
    """The standalone thesis HTML. katex_href: base URL of the KaTeX assets (default: the vendored copy on disk)."""
    from ..agentic.research.judge import STOP_TEXT

    thesis = campaign.get("thesis") or {}
    chapters = thesis.get("chapters") or []
    base = katex_href or ASSETS.as_uri()
    title = html.escape(thesis.get("title") or campaign.get("title") or "Research project")
    when = _dt.datetime.fromtimestamp(float(campaign.get("created_at") or 0), tz=_dt.UTC).strftime("%d %B %Y")
    charter = campaign.get("charter") or {}
    n_del = len(charter.get("deliverables") or [])
    done = sum(1 for d in charter.get("deliverables") or [] if d.get("status") in ("done", "infeasible"))
    counts = _tier_counts(campaign)
    verified = counts.get("formal", 0) + counts.get("certified", 0) + counts.get("replicated", 0)
    stop = STOP_TEXT.get((campaign.get("loop") or {}).get("stop_reason") or "", "")
    facts = [(f"{done}/{n_del}", "deliverables settled"), (str(len(campaign.get("rounds") or [])), "research rounds"),
             (str(verified), "verified findings"), (_duration(campaign), "of research")]
    facts_html = "".join(f'<div class="fact"><b>{html.escape(v)}</b><span>{html.escape(k)}</span></div>' for v, k in facts)
    toc_items = []
    for i, c in enumerate(chapters):
        num = re.match(r"^(\d+) ", c["title"])
        app = re.match(r"^Appendix ([A-Z])\. ", c["title"])
        toc_items.append((num.group(1) if num else (app.group(1) if app else ""),
                          re.sub(r"^(\d+ |Appendix [A-Z]\. )", "", c["title"]), f"ch-{i}"))
        if c.get("key") == "abstract":
            toc_items.append(("", "At a glance", "glance"))
    toc = "".join(f'<li><span class="n">{html.escape(n)}</span><a href="#{a}">{html.escape(t)}</a></li>' for n, t, a in toc_items)
    body = []
    for i, c in enumerate(chapters):
        m = re.match(r"^(\d+) (.*)$", c["title"])
        app = re.match(r"^Appendix ([A-Z])\. (.*)$", c["title"])
        kicker = f"Chapter {m.group(1)}" if m else (f"Appendix {app.group(1)}" if app else "")
        name = m.group(2) if m else (app.group(2) if app else c["title"])
        body.append(f'<h2 class="chapter" id="ch-{i}">' + (f'<span class="num">{kicker}</span>' if kicker else "")
                    + f'{html.escape(name)}</h2>' + _render_chapter(c["markdown"], files_dir))
        if c.get("key") == "abstract":
            body.append(_glance_html(campaign))
    mark, word = _brand_uri("tribos-mark.png"), _brand_uri("tribos-wordmark.png")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{base}/katex.min.css">
<style>{_font_faces()}
{CSS}</style>
<script defer src="{base}/katex.min.js"></script>
<script defer src="{base}/auto-render.min.js"></script>
<script>
window.__mathDone = false;
document.addEventListener("DOMContentLoaded", function () {{
  try {{
    renderMathInElement(document.body, {{delimiters: [{{left: "$$", right: "$$", display: true}},
      {{left: "$", right: "$", display: false}}], throwOnError: false, ignoredTags: ["script", "noscript", "style",
      "textarea", "pre", "code", "svg"]}});
  }} catch (e) {{ console.error(e); }}
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(function () {{ window.__mathDone = true; }});
}});
</script></head>
<body>
<section class="cover">
  {_RINGS}
  <div class="brand"><img class="mark" src="{mark}" alt=""><img class="word" src="{word}" alt="Tribos"></div>
  <div class="kicker">Research thesis</div>
  <h1>{title}</h1>
  <div class="goal">{html.escape(campaign.get('goal') or '')}</div>
  <div class="facts">{facts_html}</div>
  <div class="foot"><span>{when} · Research ID <code>{html.escape(campaign.get('campaign_id') or '')}</code></span>
  <span>{html.escape(stop)}{(' · ' + html.escape(note)) if note else ''}</span></div>
</section>
<div class="page">
<nav class="toc"><h2>Contents</h2><ol>{toc}</ol>
<p class="note">Every value in this thesis comes from code run in the Tribos sandbox (Appendix A) or from a cited source,
and carries its verification level: Lean-verified, certified, replicated (two independent implementations agree),
computed, sourced or argued.</p></nav>
{''.join(body)}
</div></body></html>"""


def _chromium_pdf(html_text: str, title: str, rid: str = "") -> bytes:
    """The cover is printed without the running header and footer; the body with them; then the two are joined."""
    """Print the HTML with headless Chromium (sync Playwright; call from a worker thread)."""
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="tribos_thesis_") as tmp:
        path = Path(tmp) / "thesis.html"
        path.write_text(html_text, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(path.as_uri(), wait_until="load")
                page.wait_for_function("window.__mathDone === true", timeout=30000)
                mark = _brand_uri("tribos-mark.png")
                header = (f"<div style='font-size:7.5px;width:100%;padding:0 22mm;color:#8a90a0;display:flex;"
                          f"justify-content:space-between;align-items:center;font-family:Segoe UI,Arial,sans-serif;'>"
                          f"<span style='display:flex;align-items:center;gap:6px'><img src='{mark}' style='height:9px'>"
                          f"<b style='color:#181e48;letter-spacing:.08em'>TRIBOS</b></span>"
                          f"<span>{html.escape(title[:90])}</span></div>")
                footer = ("<div style='font-size:7.5px;width:100%;padding:0 22mm;color:#8a90a0;display:flex;"
                          "justify-content:space-between;font-family:Segoe UI,Arial,sans-serif;'>"
                          f"<span>Research thesis · {html.escape(rid)}</span>"
                          "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>")
                page.add_style_tag(content=".page { display: none !important; }")
                cover = page.pdf(format="A4", print_background=True, prefer_css_page_size=True, page_ranges="1")
                page.goto(path.as_uri(), wait_until="load")
                page.wait_for_function("window.__mathDone === true", timeout=30000)
                page.add_style_tag(content=".cover { display: none !important; }")
                body = page.pdf(format="A4", print_background=True, display_header_footer=True,
                                header_template=header, footer_template=footer, prefer_css_page_size=True)
                return _join_pdfs(cover, body)
            finally:
                browser.close()


def _join_pdfs(*parts: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        for page in PdfReader(io.BytesIO(part)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _fpdf_pdf(campaign: dict[str, Any], files_dir: str) -> bytes:
    """A plainer PDF without a browser: headings, paragraphs, tables and PNG figures; LaTeX shown as written."""
    from fpdf import FPDF

    from .markdown_blocks import dejavu_font_dir

    thesis = campaign.get("thesis") or {}
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, 18)
    font_dir = dejavu_font_dir()
    family = "Helvetica"
    if font_dir:
        pdf.add_font("DejaVu", "", os.path.join(font_dir, "DejaVuSans.ttf"))
        pdf.add_font("DejaVu", "B", os.path.join(font_dir, "DejaVuSans-Bold.ttf"))
        pdf.add_font("DejaVu", "I", os.path.join(font_dir, "DejaVuSans-Oblique.ttf"))
        family = "DejaVu"
    pdf.add_page()
    pdf.set_font(family, "B", 20)
    pdf.multi_cell(0, 10, thesis.get("title") or campaign.get("title") or "Research project", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, "", 10)
    pdf.multi_cell(0, 5, campaign.get("goal") or "", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font(family, "I", 8)
    pdf.multi_cell(0, 4, "Plain rendering (the typeset PDF needs Chromium); mathematics appears as LaTeX source.", new_x="LMARGIN", new_y="NEXT")
    for c in thesis.get("chapters") or []:
        pdf.add_page()
        pdf.set_font(family, "B", 15)
        pdf.multi_cell(0, 8, c["title"], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        md = c["markdown"]
        pngs = [m.group("src").split("/", 1)[-1] for m in _IMG_RE.finditer(md) if m.group("src").endswith(".png")]
        text = _IMG_RE.sub("", md)
        body = _parser().render(text)
        body = re.sub(r"<(/?)(h[1-6])>", r"<\1b>", body)
        pdf.set_font(family, "", 9.5)
        try:
            pdf.write_html(body, font_family=family)
        except Exception:  # noqa: BLE001 - fall back to plain text for HTML fpdf2 cannot lay out
            pdf.multi_cell(0, 5, re.sub(r"<[^>]+>", "", body), new_x="LMARGIN", new_y="NEXT")
        for name in pngs:
            p = os.path.join(files_dir, name)
            if _SAFE_FILE.match(name) and os.path.exists(p):
                pdf.ln(2)
                pdf.image(p, w=pdf.epw * 0.85)
    return bytes(pdf.output())


def thesis_pdf(campaign: dict[str, Any], files_dir: str) -> tuple[bytes, str]:
    """(pdf bytes, engine used)."""
    from ..config.settings import get_str

    engine = (get_str("TRIBOS_THESIS_PDF_ENGINE") or "auto").lower()
    if engine in ("auto", "chromium"):
        try:
            title = (campaign.get("thesis") or {}).get("title") or campaign.get("title") or ""
            return _chromium_pdf(thesis_html(campaign, files_dir), title, campaign.get("campaign_id") or ""), "chromium"
        except Exception as exc:  # noqa: BLE001 - no browser here: the fallback still delivers a PDF
            logger.warning("Thesis PDF via Chromium failed (%s); using the fpdf2 fallback", exc)
            if engine == "chromium":
                raise
    return _fpdf_pdf(campaign, files_dir), "fpdf"


def thesis_docx(campaign: dict[str, Any], files_dir: str) -> bytes:
    from docx import Document
    from docx.shared import Inches, Pt

    from .docx_renderer import add_markdown

    thesis = campaign.get("thesis") or {}
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(10.5)
    doc.add_heading(thesis.get("title") or campaign.get("title") or "Research project", level=0)
    doc.add_paragraph().add_run(campaign.get("goal") or "").italic = True
    doc.add_paragraph(f"Research ID {campaign.get('campaign_id')}")
    for c in thesis.get("chapters") or []:
        doc.add_page_break()
        doc.add_heading(c["title"], level=1)
        md = c["markdown"]
        pos = 0
        for m in _IMG_RE.finditer(md):
            add_markdown(doc, md[pos:m.start()], base_level=2)
            name = m.group("src").split("/", 1)[-1]
            path = os.path.join(files_dir, name)
            if name.endswith(".png") and _SAFE_FILE.match(name) and os.path.exists(path):
                doc.add_picture(path, width=Inches(5.8))
            doc.add_paragraph().add_run(m.group("alt")).italic = True
            pos = m.end()
        add_markdown(doc, md[pos:], base_level=2)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def thesis_bundle(campaign: dict[str, Any], files_dir: str) -> bytes:
    thesis = campaign.get("thesis") or {}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("thesis.md", thesis.get("markdown") or "")
        if os.path.isdir(files_dir):
            for name in sorted(os.listdir(files_dir)):
                if _SAFE_FILE.match(name):
                    z.write(os.path.join(files_dir, name), f"files/{name}")
        for f in campaign.get("ledger") or []:
            code = "\n\n".join(c["code"] for c in f.get("cells") or [] if c.get("status") == "ok")
            if code:
                z.writestr(f"code/{f['id']}_{f['test_id']}.py", f"# Finding {f['id']} (test {f['test_id']})\n\n{code}\n")
            if (f.get("replication") or {}).get("code"):
                z.writestr(f"code/{f['id']}_{f['test_id']}_replication.py", f["replication"]["code"] + "\n")
            lean = (f.get("proof") or {}).get("lean_code")
            if lean:
                z.writestr(f"proofs/{f['id']}_{f['test_id']}.lean", lean + "\n")
        slim = [{k: v for k, v in f.items() if k not in ("cells",)} for f in campaign.get("ledger") or []]
        z.writestr("ledger.json", json.dumps({"goal": campaign.get("goal"), "charter": campaign.get("charter"),
                                              "findings": slim, "rounds": campaign.get("rounds")},
                                             indent=2, ensure_ascii=False, default=str))
        z.writestr("README.md", "# Reproducing this thesis\n\nEach file in `code/` reproduces the values of one finding "
                                "(run with Python 3.12 and numpy, scipy, sympy, mpmath, matplotlib). `proofs/` holds "
                                "Lean 4 proofs that compiled. `ledger.json` lists every finding with its verification "
                                "level.\n")
    return out.getvalue()


__all__ = ["thesis_bundle", "thesis_docx", "thesis_html", "thesis_pdf"]
