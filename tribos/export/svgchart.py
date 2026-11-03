"""
Small, dependency-free SVG figures for research theses: line/scatter charts of ledger series, the research-design
graph (deliverables, hypotheses, tests, findings) and the loop timeline. The palette matches the web app's lab-notebook
theme; every chart has a title, labelled axes and a legend for more than one series.
"""

from __future__ import annotations

import math
from html import escape
from typing import Any

INK, MUTED, RULE, PAPER = "#1d2433", "#5d6475", "#e3e5ec", "#ffffff"
SERIES = ("#3949ab", "#0f6e6a", "#b4531f", "#8a3f87")  # Tribos indigo, teal, rust, plum: fixed order
STATUS = {"done": "#2f7d4f", "passed": "#2f7d4f", "supported": "#2f7d4f", "partial": "#b7791f", "disputed": "#b7791f",
          "open": "#8a93a0", "pending": "#8a93a0", "undecided": "#8a93a0", "untested": "#8a93a0", "running": "#3b5bab",
          "failed": "#b23b3b", "refuted": "#b23b3b", "blocked": "#b23b3b", "infeasible": "#6b4f8a"}
FONT = 'font-family="Google Sans, Segoe UI, Arial, sans-serif"'
MONO = 'font-family="Google Sans Code, Google Sans, Consolas, monospace"'


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + step * 1e-9 and len(out) < 12:
        out.append(round(v, 12))
        v += step
    return out


_SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        e = int(math.floor(math.log10(a)))
        m = v / 10 ** e
        return (f"{m:.3g}×" if abs(m - 1) > 1e-9 else ("−" if m < 0 else "")) + "10" + str(e).translate(_SUP)
    return f"{v:.4g}"


def line_chart(series: list[dict[str, Any]], *, title: str = "", width: int = 640, height: int = 360) -> str:
    """Series: [{name, x, y, x_label, y_label, log_x, log_y}] (at most 4 drawn)."""
    series = [s for s in series if len(s.get("x") or []) >= 2][:4]
    if not series:
        return ""
    log_x = all(s.get("log_x") for s in series) and all(min(s["x"]) > 0 for s in series)
    log_y = all(s.get("log_y") for s in series) and all(min(s["y"]) > 0 for s in series)
    tx = (lambda v: math.log10(v)) if log_x else (lambda v: v)
    ty = (lambda v: math.log10(v)) if log_y else (lambda v: v)
    xs = [tx(v) for s in series for v in s["x"]]
    ys = [ty(v) for s in series for v in s["y"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 == x0:
        x1 = x0 + 1
    pad = (y1 - y0) * 0.08 or 1
    y0, y1 = y0 - pad, y1 + pad
    left, right, top, bottom = 70, 24, 44 if title else 20, 52
    pw, ph = width - left - right, height - top - bottom
    sx = lambda v: left + (tx(v) - x0) / (x1 - x0) * pw  # noqa: E731
    sy = lambda v: top + ph - (ty(v) - y0) / (y1 - y0) * ph  # noqa: E731
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='{width}' height='{height}' "
           f"role='img' aria-label='{escape(title or 'chart', quote=True)}'>",
           f"<rect width='{width}' height='{height}' fill='{PAPER}'/>"]
    if title:
        out.append(f"<text x='{left}' y='24' {FONT} font-size='15' font-weight='600' fill='{INK}'>{escape(title)}</text>")
    for t in _ticks(y0, y1):
        y = top + ph - (t - y0) / (y1 - y0) * ph
        label = _fmt(10 ** t) if log_y else _fmt(t)
        out.append(f"<line x1='{left}' x2='{left + pw}' y1='{y:.1f}' y2='{y:.1f}' stroke='{RULE}' stroke-width='1'/>")
        out.append(f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end' {MONO} font-size='11' fill='{MUTED}'>{label}</text>")
    for t in _ticks(x0, x1):
        x = left + (t - x0) / (x1 - x0) * pw
        label = _fmt(10 ** t) if log_x else _fmt(t)
        out.append(f"<text x='{x:.1f}' y='{top + ph + 18}' text-anchor='middle' {MONO} font-size='11' fill='{MUTED}'>{label}</text>")
    out.append(f"<line x1='{left}' x2='{left + pw}' y1='{top + ph}' y2='{top + ph}' stroke='{INK}' stroke-width='1.2'/>")
    xl = escape(str(series[0].get("x_label") or "x"))
    yl = escape(str(series[0].get("y_label") or "y"))
    out.append(f"<text x='{left + pw / 2}' y='{height - 10}' text-anchor='middle' {FONT} font-size='12' fill='{INK}'>{xl}"
               f"{' (log scale)' if log_x else ''}</text>")
    out.append(f"<text transform='translate(16 {top + ph / 2}) rotate(-90)' text-anchor='middle' {FONT} font-size='12' "
               f"fill='{INK}'>{yl}{' (log scale)' if log_y else ''}</text>")
    for i, s in enumerate(series):
        color = SERIES[i % len(SERIES)]
        pts = [(sx(a), sy(b)) for a, b in zip(s["x"], s["y"], strict=False)
               if (a > 0 or not log_x) and (b > 0 or not log_y)]
        if len(pts) <= 40:
            for x, y in pts:
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.2' fill='{color}' stroke='{PAPER}' stroke-width='1.5'/>")
        if len(pts) >= 2:
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            out.append(f"<path d='{d}' fill='none' stroke='{color}' stroke-width='2' stroke-linejoin='round'/>")
    if len(series) > 1:
        lx = left + 8
        for i, s in enumerate(series):
            y = top + 10 + i * 16
            out.append(f"<rect x='{lx}' y='{y - 7}' width='14' height='4' rx='2' fill='{SERIES[i % len(SERIES)]}'/>")
            out.append(f"<text x='{lx + 20}' y='{y}' {FONT} font-size='11' fill='{INK}'>{escape(str(s.get('name'))[:40])}</text>")
    out.append("</svg>")
    return "".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines[:2] or [""]


def design_diagram(charter: dict[str, Any], ledger: list[dict[str, Any]], *, width: int = 720) -> str:
    """Columns: deliverables <- tests -> hypotheses, with each test's best finding status; edges from the charter."""
    ds, hs, ts = charter.get("deliverables") or [], charter.get("hypotheses") or [], charter.get("tests") or []
    if not ts:
        return ""
    row_h, top = 54, 50
    rows = max(len(ds), len(ts), len(hs), 1)
    height = top + rows * row_h + 16
    box_w = 206
    cols = {"D": 12, "T": width / 2 - box_w / 2, "H": width - box_w - 12}
    pos: dict[str, tuple[float, float]] = {}
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='{width}' height='{height}' "
           f"role='img' aria-label='Research design'>", f"<rect width='{width}' height='{height}' fill='{PAPER}'/>"]
    for label, x in (("Deliverables", cols["D"]), ("Tests", cols["T"]), ("Hypotheses", cols["H"])):
        out.append(f"<text x='{x}' y='30' {FONT} font-size='14' font-weight='600' fill='{INK}'>{label}</text>")
    best = {}
    for f in ledger:
        best.setdefault(f.get("test_id"), f)
        if f.get("status") == "passed":
            best[f.get("test_id")] = f

    def node(key: str, x: float, i: int, ident: str, text: str, status: str) -> None:
        y = top + i * row_h
        pos[key] = (x, y)
        color = STATUS.get(status, "#8a93a0")
        out.append(f"<rect x='{x}' y='{y}' width='{box_w}' height='44' rx='6' fill='#ffffff' stroke='{RULE}'/>")
        out.append(f"<rect x='{x}' y='{y}' width='5' height='44' rx='2' fill='{color}'/>")
        lines = _wrap(f"{ident} · {text}", 30)
        for j, ln in enumerate(lines):
            out.append(f"<text x='{x + 12}' y='{y + 18 + j * 15}' {FONT} font-size='12.5' fill='{INK}'>{escape(ln)}</text>")

    edges = []
    for i, d in enumerate(ds):
        node(d["id"], cols["D"], i, d["id"], d["title"], d.get("status", "open"))
    for i, t in enumerate(ts):
        f = best.get(t["id"])
        node(t["id"], cols["T"], i, t["id"], t["title"], (f or {}).get("status") or t.get("status", "pending"))
        edges += [(t["id"], d, "D") for d in t.get("serves") or []] + [(t["id"], h, "H") for h in t.get("hypotheses") or []]
    for i, h in enumerate(hs):
        node(h["id"], cols["H"], i, h["id"], h["statement"], h.get("verdict", "untested"))
    paths = []
    for a, b, side in edges:
        if a not in pos or b not in pos:
            continue
        (ax, ay), (bx, by) = pos[a], pos[b]
        if side == "D":
            x1, y1, x2, y2 = ax, ay + 22, bx + box_w, by + 22
        else:
            x1, y1, x2, y2 = ax + box_w, ay + 22, bx, by + 22
        mid = (x1 + x2) / 2
        paths.append(f"<path d='M{x1:.0f},{y1:.0f} C{mid:.0f},{y1:.0f} {mid:.0f},{y2:.0f} {x2:.0f},{y2:.0f}' "
                     f"fill='none' stroke='{MUTED}' stroke-opacity='0.45' stroke-width='1.2'/>")
    out[2:2] = paths
    out.append("</svg>")
    return "".join(out)


def timeline(rounds: list[dict[str, Any]], *, width: int = 720) -> str:
    """One bar per round, its length proportional to the round's duration, labelled with its tests and progress."""
    if not rounds:
        return ""
    row_h, top, left, label_w = 30, 42, 86, 210
    height = top + len(rounds) * row_h + 14
    span = width - left - label_w
    longest = max(max(1.0, float(r.get("seconds") or 1)) for r in rounds)
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='{width}' height='{height}' "
           f"role='img' aria-label='Research loop timeline'>", f"<rect width='{width}' height='{height}' fill='{PAPER}'/>",
           f"<text x='16' y='24' {FONT} font-size='14' font-weight='600' fill='{INK}'>Research loop</text>"]
    for i, r in enumerate(rounds):
        y = top + i * row_h
        secs = max(1.0, float(r.get("seconds") or 1))
        w = max(6.0, span * secs / longest)
        color = SERIES[0] if r.get("progress") else "#8a93a0"
        if r.get("concluded"):
            color = "#2f7d4f"
        mins = int(secs // 60)
        label = (f"{len(r.get('tests') or [])} test(s) · {mins} min · "
                 + ("concluded" if r.get("concluded") else "progress" if r.get("progress") else "no progress"))
        out.append(f"<text x='16' y='{y + 15}' {FONT} font-size='12' fill='{INK}'>Round {r.get('round')}</text>")
        out.append(f"<rect x='{left}' y='{y + 3}' width='{w:.1f}' height='16' rx='4' fill='{color}' fill-opacity='0.9'/>")
        out.append(f"<text x='{left + w + 8:.1f}' y='{y + 15}' {FONT} font-size='11' fill='{MUTED}'>{escape(label)}</text>")
    out.append("</svg>")
    return "".join(out)


__all__ = ["design_diagram", "line_chart", "timeline"]
