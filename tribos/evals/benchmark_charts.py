"""
Inline SVG charts for the benchmark report: no script, no external font or library, so the HTML stands alone and
prints the same in Chromium's PDF.

Conventions: one value axis per chart (no dual axes); Tribos and direct keep one categorical colour each in every
chart (blue and orange, a pair that passes the colour-vision-deficiency checks); text always uses the ink colours,
never a series colour; thin bars with 4 px rounded data ends; hairline gridlines; a legend on every chart with two
or more series; each mark has a <title> tooltip, and the report's tables hold every value the charts show.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

TRIBOS = "#2a78d6"
DIRECT = "#eb6834"
BOTH_RIGHT = "#6f6e69"  # concordant pairs are context, so they are grey; the discordant pairs carry the hues
BOTH_WRONG = "#d6d5ce"
INK = "#1b1b1a"
INK2 = "#4a4945"
MUTED = "#63625d"
GRID = "#e6e5df"
AXIS = "#b5b4ac"
SURFACE = "#ffffff"
FONT = "inherit"

W = 680  # viewBox width; the SVG scales to the column width


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


def text_width(s: str, size: float, weight: int = 400) -> float:
    """Approximate rendered width of s in Google Sans / a UI sans (for fitting labels, not for layout precision)."""
    w = 0.0
    for ch in s:
        if ch in "ijl.,:;|!'’ ":
            w += 0.28
        elif ch in "fIrt()[]-–":
            w += 0.36
        elif ch.isdigit() or ch in "%+−~":
            w += 0.57
        elif ch in "mwMW":
            w += 0.86
        elif ch.isupper():
            w += 0.66
        else:
            w += 0.54
    return w * size * (1.04 if weight >= 500 else 1.0)


def _text(x: float, y: float, s: str, *, size: float = 11, anchor: str = "start", weight: int = 400, fill: str = INK2,
          extra: str = "") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{_e(s)}</text>')


def _col_path(x: float, y_base: float, y_top: float, w: float, r: float = 4.0) -> str:
    """A vertical column with a rounded top (the data end) and a square base."""
    h = y_base - y_top
    if h <= 0:
        return ""
    r = min(r, h, w / 2)
    return (f"M{x:.2f},{y_base:.2f} L{x:.2f},{y_top + r:.2f} Q{x:.2f},{y_top:.2f} {x + r:.2f},{y_top:.2f} "
            f"L{x + w - r:.2f},{y_top:.2f} Q{x + w:.2f},{y_top:.2f} {x + w:.2f},{y_top + r:.2f} L{x + w:.2f},{y_base:.2f} Z")


def _bar_path(x0: float, x1: float, y: float, h: float, r: float = 4.0) -> str:
    """A horizontal bar with a rounded right end (the data end) and a square base on the left."""
    w = x1 - x0
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (f"M{x0:.2f},{y:.2f} L{x1 - r:.2f},{y:.2f} Q{x1:.2f},{y:.2f} {x1:.2f},{y + r:.2f} L{x1:.2f},{y + h - r:.2f} "
            f"Q{x1:.2f},{y + h:.2f} {x1 - r:.2f},{y + h:.2f} L{x0:.2f},{y + h:.2f} Z")


def _whisker_v(x: float, y_lo: float, y_hi: float, cap: float = 7.0, color: str = INK) -> str:
    return (f'<g stroke="{color}" stroke-width="1.3" stroke-linecap="round" fill="none">'
            f'<line x1="{x:.2f}" y1="{y_lo:.2f}" x2="{x:.2f}" y2="{y_hi:.2f}"/>'
            f'<line x1="{x - cap / 2:.2f}" y1="{y_lo:.2f}" x2="{x + cap / 2:.2f}" y2="{y_lo:.2f}"/>'
            f'<line x1="{x - cap / 2:.2f}" y1="{y_hi:.2f}" x2="{x + cap / 2:.2f}" y2="{y_hi:.2f}"/></g>')


def _whisker_h(y: float, x_lo: float, x_hi: float, cap: float = 7.0, color: str = INK) -> str:
    return (f'<g stroke="{color}" stroke-width="1.3" stroke-linecap="round" fill="none">'
            f'<line x1="{x_lo:.2f}" y1="{y:.2f}" x2="{x_hi:.2f}" y2="{y:.2f}"/>'
            f'<line x1="{x_lo:.2f}" y1="{y - cap / 2:.2f}" x2="{x_lo:.2f}" y2="{y + cap / 2:.2f}"/>'
            f'<line x1="{x_hi:.2f}" y1="{y - cap / 2:.2f}" x2="{x_hi:.2f}" y2="{y + cap / 2:.2f}"/></g>')


def _legend(items: Sequence[tuple[str, str, str]], x: float, y: float, size: float = 11) -> str:
    """One row of legend entries (kind: 'rect' swatch, 'dot', 'ring' or 'tick'), text in ink."""
    out = []
    for kind, color, label in items:
        if kind == "rect":
            out.append(f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="11" height="11" rx="2.5" fill="{color}"/>')
        elif kind == "dot":
            out.append(f'<circle cx="{x + 5.5:.1f}" cy="{y - 3.5:.1f}" r="5" fill="{color}"/>')
        elif kind == "ring":
            out.append(f'<circle cx="{x + 5.5:.1f}" cy="{y - 3.5:.1f}" r="4.2" fill="{SURFACE}" stroke="{color}" stroke-width="2"/>')
        elif kind == "tick":
            out.append(f'<rect x="{x + 4.5:.1f}" y="{y - 11:.1f}" width="2.5" height="15" rx="1" fill="{color}"/>')
        out.append(_text(x + 17, y, label, size=size, fill=INK2))
        x += 17 + text_width(label, size) + 18
    return "".join(out)


def _svg(height: float, body: str, label: str, desc: str = "") -> str:
    return (f'<svg class="chart" viewBox="0 0 {W} {height:.0f}" width="100%" role="img" aria-label="{_e(label)}" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="{FONT}"><title>{_e(label)}</title>'
            + (f"<desc>{_e(desc)}</desc>" if desc else "") + body + "</svg>")


def pct(v: float | None, digits: int = 0) -> str:
    return "–" if v is None else f"{v * 100:.{digits}f}%"


def nice_step(span: float, target: int = 5) -> float:
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if m * mag >= raw:
            return m * mag
    return 10.0 * mag


def fmt_seconds(s: float | None) -> str:
    if s is None:
        return "–"
    if s < 10:
        return f"{s:.1f} s"
    return f"{s:,.0f} s"


# ---------------------------------------------------------------------------------------------------------------
# Figure 1: accuracy by benchmark, grouped columns with 95% CI whiskers
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class AccuracyGroup:
    label: str
    note: str  # e.g. "n = 50"
    tribos: dict[str, Any] | None  # proportion dicts {k, n, rate, ci95}
    direct: dict[str, Any] | None
    pooled: bool = False


def accuracy_chart(groups: Sequence[AccuracyGroup]) -> str:
    H = 318
    left, right, top, bottom = 46, 10, 52, 48
    pw, ph = W - left - right, H - top - bottom

    def y(v: float) -> float:
        return top + (1 - v) * ph

    parts = [_legend([("rect", TRIBOS, "Tribos"), ("rect", DIRECT, "Direct (same model, no tools)")], left, 16)]
    # The whisker key: a small I-beam and its meaning.
    wx = left + 17 + text_width("Tribos", 11) + 18 + 17 + text_width("Direct (same model, no tools)", 11) + 22
    parts.append(_whisker_v(wx + 3, 17, 5, cap=6))
    parts.append(_text(wx + 12, 16, "95% confidence interval (Wilson)", fill=INK2))
    for t in range(0, 101, 20):
        yy = y(t / 100)
        parts.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{W - right}" y2="{yy:.2f}" stroke="{AXIS if t == 0 else GRID}" stroke-width="1"/>')
        parts.append(_text(left - 8, yy + 4, f"{t}%", size=10.5, anchor="end", fill=MUTED, extra=' class="tnum"'))
    n = max(1, len(groups))
    pitch = pw / n
    bw, gap = 24.0, 8.0
    for i, g in enumerate(groups):
        cx = left + pitch * (i + 0.5)
        if g.pooled and i > 0:
            sx = left + pitch * i
            parts.append(f'<line x1="{sx:.2f}" y1="{top - 6}" x2="{sx:.2f}" y2="{H - bottom + 36}" stroke="{GRID}" stroke-width="1"/>')
        for system, prop, x0 in (("Tribos", g.tribos, cx - gap / 2 - bw), ("Direct", g.direct, cx + gap / 2)):
            if not prop or not prop.get("n"):
                parts.append(_text(x0 + bw / 2, y(0) - 6, "–", size=11, anchor="middle", fill=MUTED))
                continue
            rate = float(prop["rate"])
            lo, hi = prop["ci95"]
            color = TRIBOS if system == "Tribos" else DIRECT
            tip = (f"{system} · {g.label}: {pct(rate, 1)} ({prop['k']}/{prop['n']}), "
                   f"95% CI {pct(lo, 1)}–{pct(hi, 1)}")
            path = _col_path(x0, y(0), y(rate), bw)
            mark = f'<path d="{path}" fill="{color}"/>' if path else ""
            # The hit area is the whole slot above the baseline, not only the painted column.
            parts.append(f'<g class="mark"><title>{_e(tip)}</title>'
                         f'<rect x="{x0 - 3:.1f}" y="{top - 20}" width="{bw + 6:.1f}" height="{ph + 20:.1f}" fill="transparent"/>'
                         f'{mark}{_whisker_v(x0 + bw / 2, y(lo), y(hi))}</g>')
            parts.append(_text(x0 + bw / 2, y(hi) - 7, pct(rate), size=11, anchor="middle", weight=500, fill=INK,
                               extra=' class="tnum"'))
        parts.append(_text(cx, H - bottom + 19, g.label, size=11.5, anchor="middle", weight=700 if g.pooled else 500, fill=INK))
        parts.append(_text(cx, H - bottom + 34, g.note, size=10, anchor="middle", fill=MUTED))
    return _svg(H, "".join(parts), "Accuracy by benchmark, Tribos and direct, with 95% confidence intervals",
                "Grouped columns: accuracy (share of problems answered correctly) per benchmark and pooled; whiskers are "
                "95% Wilson score intervals. Values are listed in the results table.")


# ---------------------------------------------------------------------------------------------------------------
# Figure 2: paired outcomes per benchmark (both right / only Tribos / only direct / both wrong)
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class PairedRow:
    label: str
    n: int
    both_right: int
    only_tribos: int
    only_direct: int
    both_wrong: int
    p_value: float | None
    pooled: bool = False


def fmt_p(p: float | None) -> str:
    if p is None:
        return "–"
    if p < 0.001:
        return "< 0.001"
    if p >= 0.995:
        return "1.00"
    return f"{p:.3f}" if p < 0.1 else f"{p:.2f}"


def paired_chart(rows: Sequence[PairedRow]) -> str:
    row_h, bar_h = 38, 24
    top, left_col, right_col = 42, 118, 132
    H = top + row_h * max(1, len(rows)) + 6
    x0, x1 = left_col, W - right_col
    segs = (("both_right", BOTH_RIGHT, "#ffffff", "Both right"), ("only_tribos", TRIBOS, "#ffffff", "Only Tribos right"),
            ("only_direct", DIRECT, INK, "Only direct right"), ("both_wrong", BOTH_WRONG, INK, "Both wrong"))
    parts = [_legend([("rect", c, lab) for _, c, _, lab in segs], 0, 16)]
    for i, r in enumerate(rows):
        yt = top + i * row_h
        yc = yt + bar_h / 2
        if r.pooled and i > 0:
            parts.append(f'<line x1="0" y1="{yt - 7:.1f}" x2="{W}" y2="{yt - 7:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(0, yc - 1, r.label, size=11.5, weight=700 if r.pooled else 500, fill=INK))
        parts.append(_text(0, yc + 12, f"{r.n} pairs", size=10, fill=MUTED))
        if r.n <= 0:
            parts.append(_text(x0, yc + 4, "no paired problems", size=10.5, fill=MUTED))
            continue
        span = x1 - x0
        x = x0
        for key, fill, label_ink, name in segs:
            count = getattr(r, key)
            if count <= 0:
                continue
            w = span * count / r.n
            # A 2 px surface gap between parts: each block gives up 1 px on each inner side.
            bx0 = x + (1 if x > x0 else 0)
            bx1 = x + w - (1 if x + w < x1 - 0.01 else 0)
            tip = f"{r.label} · {name}: {count} of {r.n} ({pct(count / r.n, 0)})"
            parts.append(f'<g class="mark"><title>{_e(tip)}</title><rect x="{bx0:.2f}" y="{yt:.2f}" width="{max(0.5, bx1 - bx0):.2f}" '
                         f'height="{bar_h}" rx="3" fill="{fill}"/></g>')
            lab = str(count)
            if text_width(lab, 10.5, 500) + 10 <= bx1 - bx0:
                parts.append(_text(bx0 + 5, yc + 4, lab, size=10.5, weight=500, fill=label_ink, extra=' class="tnum" pointer-events="none"'))
            x += w
        net = r.only_tribos - r.only_direct
        net_txt = "net 0" if net == 0 else f"net {net:+d}".replace("-", "−")
        parts.append(_text(x1 + 10, yc - 1, net_txt, size=11.5, weight=500, fill=INK, extra=' class="tnum"'))
        parts.append(_text(x1 + 10, yc + 12, f"McNemar p {fmt_p(r.p_value)}", size=10, fill=MUTED, extra=' class="tnum"'))
    return _svg(H, "".join(parts), "Paired outcomes per benchmark: both right, only Tribos right, only direct right, both wrong",
                "Each bar splits the paired problems of one benchmark by which system answered correctly. "
                "'net' is only-Tribos minus only-direct; p is the exact McNemar test on those discordant pairs.")


# ---------------------------------------------------------------------------------------------------------------
# Figure 3: verified precision (Tribos), against accuracy on unverified answers and direct's accuracy
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class VerifiedRow:
    label: str
    precision: dict[str, Any] | None  # accuracy among answers Tribos marked verified
    unverified: dict[str, Any] | None  # accuracy among the other Tribos answers
    coverage: dict[str, Any] | None  # share of answers marked verified
    direct_accuracy: float | None
    pooled: bool = False


def verified_chart(rows: Sequence[VerifiedRow]) -> str:
    block = 50
    top, left_col = 46, 214
    H = top + block * max(1, len(rows)) + 26
    x0, x1 = left_col, W - 44  # 44 px for the value labels right of the whiskers

    def x(v: float) -> float:
        return x0 + v * (x1 - x0)

    parts = [_legend([("dot", TRIBOS, "Tribos, answers it marked verified"), ("ring", TRIBOS, "Tribos, other answers"),
                      ("tick", DIRECT, "Direct, all answers")], 0, 16)]
    y_end = top + block * len(rows) - 4
    for t in range(0, 101, 20):
        xx = x(t / 100)
        parts.append(f'<line x1="{xx:.2f}" y1="{top - 8}" x2="{xx:.2f}" y2="{y_end:.2f}" stroke="{AXIS if t == 0 else GRID}" stroke-width="1"/>')
        parts.append(_text(xx, y_end + 16, f"{t}%", size=10.5, anchor="middle", fill=MUTED, extra=' class="tnum"'))
    for i, r in enumerate(rows):
        yt = top + i * block
        y1, y2 = yt + 12, yt + 31
        if r.pooled and i > 0:
            parts.append(f'<line x1="0" y1="{yt - 4:.1f}" x2="{W}" y2="{yt - 4:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(0, y1 + 4, r.label, size=11.5, weight=700 if r.pooled else 500, fill=INK))
        nv = (r.precision or {}).get("n") or 0
        nu = (r.unverified or {}).get("n") or 0
        cov = (r.coverage or {}).get("rate")
        share = f" ({pct(cov)})" if cov is not None else ""
        parts.append(_text(x0 - 10, y1 + 4, f"verified · {nv}{share}", size=10, anchor="end", fill=MUTED, extra=' class="tnum"'))
        parts.append(_text(x0 - 10, y2 + 4, f"other · {nu}", size=10, anchor="end", fill=MUTED, extra=' class="tnum"'))
        xd = x(r.direct_accuracy) if r.direct_accuracy is not None else None
        if xd is not None:
            parts.append(f'<g class="mark"><title>{_e(f"Direct · {r.label}: {pct(r.direct_accuracy, 1)} correct on the same problems")}</title>'
                         f'<rect x="{xd - 1.25:.2f}" y="{yt + 3:.1f}" width="2.5" height="{block - 12}" rx="1" fill="{DIRECT}"/></g>')
        for prop, yy, filled, name in ((r.precision, y1, True, "verified"), (r.unverified, y2, False, "other answers")):
            if not prop or not prop.get("n"):
                parts.append(_text(x0 + 4, yy + 4, "none verified" if filled else "none", size=10, fill=MUTED))
                continue
            lo, hi = prop["ci95"]
            rate = float(prop["rate"])
            tip = f"Tribos · {r.label} · {name}: {pct(rate, 1)} correct ({prop['k']}/{prop['n']}), 95% CI {pct(lo, 1)}–{pct(hi, 1)}"
            dot = (f'<circle cx="{x(rate):.2f}" cy="{yy:.2f}" r="5.5" fill="{TRIBOS}" stroke="{SURFACE}" stroke-width="2"/>' if filled
                   else f'<circle cx="{x(rate):.2f}" cy="{yy:.2f}" r="4.6" fill="{SURFACE}" stroke="{TRIBOS}" stroke-width="2"/>')
            parts.append(f'<g class="mark"><title>{_e(tip)}</title>'
                         f'<rect x="{x(lo) - 6:.1f}" y="{yy - 9:.1f}" width="{x(hi) - x(lo) + 12:.1f}" height="18" fill="transparent"/>'
                         f'{_whisker_h(yy, x(lo), x(hi), cap=6, color=INK2)}{dot}</g>')
            # The value sits right of the whisker unless the direct tick is there: then left of it, or past the tick.
            label = pct(rate)
            lw = text_width(label, 10.5, 500)
            lx, anchor = x(hi) + 7, "start"
            if xd is not None and lx - 4 <= xd <= lx + lw + 4:
                if x(lo) - 7 - lw >= x0 + 2:
                    lx, anchor = x(lo) - 7, "end"
                else:
                    lx = xd + 6
            parts.append(_text(lx, yy + 4, label, size=10.5, anchor=anchor, weight=500, fill=INK, extra=' class="tnum"'))
    return _svg(H, "".join(parts), "Accuracy of answers Tribos marked verified, compared with its other answers and with direct",
                "For each benchmark: accuracy among the answers the Tribos verifier passed (filled dot) and among the rest "
                "(ring), with 95% Wilson intervals; the orange tick is the direct baseline's accuracy on the same problems.")


# ---------------------------------------------------------------------------------------------------------------
# Figure 4: latency per benchmark, median bars with a p95 whisker
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class LatencyRow:
    label: str
    tribos: dict[str, Any] | None  # {"median_s", "p95_s", "n"}
    direct: dict[str, Any] | None
    pooled: bool = False


def latency_chart(rows: Sequence[LatencyRow]) -> str:
    bar_h, inner, block = 12, 6, 48
    top, left_col, right_col = 44, 118, 150
    H = top + block * max(1, len(rows)) + 24
    x0, x1 = left_col, W - right_col
    vmax = 0.0
    for r in rows:
        for s in (r.tribos, r.direct):
            for k in ("median_s", "p95_s"):
                if s and s.get(k) is not None:
                    vmax = max(vmax, float(s[k]))
    step = nice_step(vmax or 1.0)
    top_val = step * max(1, math.ceil((vmax or 1.0) / step))

    def x(v: float) -> float:
        return x0 + (x1 - x0) * v / top_val

    parts = [_legend([("rect", TRIBOS, "Tribos"), ("rect", DIRECT, "Direct")], 0, 16)]
    lx = 17 + text_width("Tribos", 11) + 18 + 17 + text_width("Direct", 11) + 22
    parts.append(_whisker_h(10, lx, lx + 14, cap=6, color=INK2))
    parts.append(_text(lx + 22, 14, "bar: median · whisker to the 95th percentile", fill=INK2))
    y_end = top + block * len(rows) - 6
    t = 0.0
    while t <= top_val + 1e-9:
        xx = x(t)
        parts.append(f'<line x1="{xx:.2f}" y1="{top - 8}" x2="{xx:.2f}" y2="{y_end:.2f}" stroke="{AXIS if t == 0 else GRID}" stroke-width="1"/>')
        parts.append(_text(xx, y_end + 16, f"{t:,.0f} s" if step >= 1 else f"{t:.1f} s", size=10.5, anchor="middle", fill=MUTED,
                           extra=' class="tnum"'))
        t += step
    for i, r in enumerate(rows):
        yt = top + i * block
        if r.pooled and i > 0:
            parts.append(f'<line x1="0" y1="{yt - 6:.1f}" x2="{W}" y2="{yt - 6:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_text(0, yt + bar_h + 2, r.label, size=11.5, weight=700 if r.pooled else 500, fill=INK))
        for j, (name, s, color) in enumerate((("Tribos", r.tribos, TRIBOS), ("Direct", r.direct, DIRECT))):
            yy = yt + j * (bar_h + inner)
            if not s or s.get("median_s") is None:
                parts.append(_text(x0 + 4, yy + bar_h - 2, "not recorded", size=10, fill=MUTED))
                continue
            med = float(s["median_s"])
            p95 = float(s["p95_s"]) if s.get("p95_s") is not None else med
            tip = f"{name} · {r.label}: median {fmt_seconds(med)}, p95 {fmt_seconds(p95)} (n = {s.get('n')})"
            path = _bar_path(x0, x(med), yy, bar_h)
            wh = _whisker_h(yy + bar_h / 2, x(med), x(p95), cap=7, color=INK2) if p95 > med else ""
            parts.append(f'<g class="mark"><title>{_e(tip)}</title>'
                         f'<rect x="{x0}" y="{yy - 1:.1f}" width="{max(x(p95) - x0, 8) + 6:.1f}" height="{bar_h + 2}" fill="transparent"/>'
                         + (f'<path d="{path}" fill="{color}"/>' if path else "") + f"{wh}</g>")
            parts.append(_text(max(x(p95), x(med)) + 8, yy + bar_h - 2.5, f"{fmt_seconds(med)} · p95 {fmt_seconds(p95)}",
                               size=10.5, fill=INK2, extra=' class="tnum"'))
    return _svg(H, "".join(parts), "Latency per problem by benchmark: median and 95th percentile, Tribos and direct",
                "Horizontal bars: median seconds per problem; whiskers extend to the 95th percentile.")


__all__ = ["AccuracyGroup", "DIRECT", "LatencyRow", "PairedRow", "TRIBOS", "VerifiedRow", "accuracy_chart", "fmt_p",
           "fmt_seconds", "latency_chart", "paired_chart", "pct", "verified_chart"]
