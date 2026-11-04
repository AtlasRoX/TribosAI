"""
The findings ledger: every test run's outcome, with the numbers it produced, the code that produced them, its
figures, and how strongly it is verified.

Verification tiers, strongest first:
  formal      a Lean proof that compiled with no sorry/admit/axiom
  certified   exact integer results, reproduced exactly by a separately written re-implementation
  replicated  a separately written re-implementation (different algorithm; a second model when
              TRIBOS_RESEARCH_REPLICATION_MODEL is set) agrees on every reported quantity
  computed    ran once in the sandbox
  sourced     a published source states it (with a citation)
  reasoned    an argument only
"""

from __future__ import annotations

import base64
import math
import os
import re
from typing import Any

TIER_RANK = {"formal": 6, "certified": 5, "replicated": 4, "computed": 3, "sourced": 2, "reasoned": 1, "none": 0}
TIER_LABEL = {"formal": "Lean-verified", "certified": "Certified", "replicated": "Replicated", "computed": "Computed",
              "sourced": "Sourced", "reasoned": "Argued", "none": "Unverified"}
MAX_FIGURES_PER_FINDING = 4
# A comma is a thousands separator only in groups of three digits ("1,000,000"); "27,97,871" is a list of three numbers.
# A grouped number may be followed by a comma of the prose ("n = 837,799, as computed"), not by another digit group.
_NUMBER_RE = re.compile(r"(?:(?<![\w.,])-?\d{1,3}(?:,\d{3})+(?!\d|,\d)|(?<![\w.])-?\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")


def rank(tier: str | None) -> int:
    return TIER_RANK.get(str(tier or "none"), 0)


def meets(tier: str | None, required: str | None) -> bool:
    """A finding's tier satisfies a required tier. Sourced and reasoned are separate kinds of evidence: a computation
    meets "sourced" only when it is at least replicated; a proof (formal) meets every requirement."""
    t, r = str(tier or "none"), str(required or "computed")
    if t == "formal":
        return True
    if r in ("sourced", "reasoned"):
        return rank(t) >= rank(r)
    return rank(t) >= rank(r)


def next_id(ledger: list[dict[str, Any]]) -> str:
    return f"F{len(ledger) + 1}"


def _short(value: Any) -> str:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return f"{value:.10g}"
    return str(value)


def quantities_from_result(result: Any, wanted: list[str] | None = None, limit: int = 40) -> tuple[list[dict], list[dict]]:
    """(quantities, series) from a sandbox `result`: scalars become named quantities; {"x": [...], "y": [...]} dicts
    (under result["series"] or anywhere at the top level) become chart series; short numeric lists become quantities
    holding the list."""
    quantities: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    if not isinstance(result, dict):
        if isinstance(result, (int, float, str)) and str(result).strip():
            quantities.append({"name": "result", "value": result})
        return quantities, series

    def add_series(name: str, s: dict[str, Any]) -> None:
        x, y = s.get("x"), s.get("y")
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and len(x) >= 2:
            pts = [(float(a), float(b)) for a, b in zip(x, y, strict=True)
                   if isinstance(a, (int, float)) and isinstance(b, (int, float))
                   and math.isfinite(float(a)) and math.isfinite(float(b))]
            if len(pts) >= 2:
                step = max(1, len(pts) // 400)
                series.append({"name": str(s.get("name") or name)[:80], "x": [p[0] for p in pts[::step]],
                               "y": [p[1] for p in pts[::step]], "x_label": str(s.get("x_label") or "x")[:60],
                               "y_label": str(s.get("y_label") or name)[:60], "log_x": bool(s.get("log_x")),
                               "log_y": bool(s.get("log_y"))})

    for name, s in (result.get("series") or {}).items() if isinstance(result.get("series"), dict) else []:
        if isinstance(s, dict):
            add_series(str(name), s)
    for key, value in result.items():
        if key == "series" or len(quantities) >= limit:
            continue
        if isinstance(value, dict) and "x" in value and "y" in value:
            add_series(str(key), value)
        elif isinstance(value, bool):
            quantities.append({"name": str(key), "value": value})
        elif isinstance(value, (int, float, str)):
            quantities.append({"name": str(key), "value": value})
        elif isinstance(value, list) and 0 < len(value) <= 300 and all(
                isinstance(v, (int, float, str)) or (isinstance(v, (list, tuple)) and len(v) <= 4
                                                     and all(isinstance(x, (int, float, str)) for x in v))
                for v in value):
            # Short tables of values or pairs ((n, s(n)) record holders) are results in their own right.
            quantities.append({"name": str(key), "value": [list(v) if isinstance(v, tuple) else v for v in value]})
        elif isinstance(value, dict) and all(isinstance(v, (int, float, str)) for v in value.values()) and len(value) <= 30:
            quantities.append({"name": str(key), "value": value})
    if wanted:
        order = {w: i for i, w in enumerate(wanted)}
        quantities.sort(key=lambda q: order.get(q["name"], len(order)))
    return quantities, series


def save_figures(files_dir: str, finding_id: str, figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write a cell's PNG figures next to the campaign (files_dir/<finding>_<n>.png); returns their records."""
    out = []
    os.makedirs(files_dir, exist_ok=True)
    for i, fig in enumerate(figures[:MAX_FIGURES_PER_FINDING], 1):
        data = fig.get("png_base64")
        if not data:
            continue
        name = f"{finding_id}_fig{i}.png"
        try:
            with open(os.path.join(files_dir, name), "wb") as fh:
                fh.write(base64.b64decode(data))
        except (OSError, ValueError):
            continue
        axes = (fig.get("axes") or [{}])[0] if fig.get("axes") else {}
        out.append({"name": name, "title": str(axes.get("title") or "")[:160],
                    "xlabel": str(axes.get("xlabel") or "")[:80], "ylabel": str(axes.get("ylabel") or "")[:80]})
    return out


def finding_line(f: dict[str, Any], *, numbers: int = 12) -> str:
    def shown(v: Any) -> str:
        # Lists are shown whole (up to a size the judge can read), so a complete table is never mistaken for a cut one.
        return (str(v) if len(str(v)) <= 2500 else str(v)[:2500] + f" … ({len(v)} items)") if isinstance(v, list)             else _short(v)[:200]

    qs = "; ".join(f"{q['name']} = {shown(q['value'])}" for q in (f.get("quantities") or [])[:numbers])
    proof = f.get("proof") or {}
    extra = f" Lean: {proof.get('lean_status')}." if proof.get("lean_status") else ""
    return (f"{f['id']} [{f['status']}, {TIER_LABEL.get(f.get('tier') or 'none')}] test {f.get('test_id')} "
            f"(round {f.get('round')}): {str(f.get('summary') or '')[:600]}" + (f" Values: {qs}." if qs else "") + extra)


def ledger_text(ledger: list[dict[str, Any]], *, limit_chars: int = 24000, ids: list[str] | None = None) -> str:
    rows = [f for f in ledger if not ids or f["id"] in ids]
    text = "\n".join(finding_line(f) for f in rows)
    return text if len(text) <= limit_chars else text[-limit_chars:]


def evidence_numbers(*texts: str, ledger: list[dict[str, Any]] | None = None) -> set[str]:
    """Every number the evidence states, in normalised forms (for checking a written report)."""
    nums: set[str] = set()

    def add(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.update(_forms(float(v)))
        elif isinstance(v, (list, tuple)):
            for x in v[:500]:
                add(x)
        elif isinstance(v, dict):
            for x in list(v.values())[:500]:
                add(x)
        elif isinstance(v, str):
            for m in _NUMBER_RE.findall(v):
                add_text(m)

    def add_text(m: str) -> None:
        try:
            nums.update(_forms(float(m.replace(",", ""))))
        except ValueError:
            pass

    for f in ledger or []:
        for q in f.get("quantities") or []:
            add(q.get("value"))
        add(f.get("summary") or "")
        for s in f.get("series") or []:
            add(s.get("y")[:200])
            add(s.get("x")[:200])
        for c in f.get("checks") or []:
            add(str(c.get("detail") or ""))
    for t in texts:
        add(t or "")
    return nums


def _forms(v: float) -> set[str]:
    if not math.isfinite(v):
        return {str(v)}
    out = {f"{v:.{d}g}" for d in range(2, 13)}
    out.add(repr(v))
    if v == int(v) and abs(v) < 1e18:
        out.add(str(int(v)))
    return out


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD_RE = re.compile(r"[A-Za-z]+")
_NAME_STOP = frozenset({"the", "and", "for", "with", "from", "value", "values", "number", "numbers", "count", "result",
                        "results", "total", "per", "all", "are", "was", "were", "this", "that", "which", "its"})


def _name_words(name: Any) -> set[str]:
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or "")).replace("_", " ").replace("-", " ")
    return {w.lower() for w in _WORD_RE.findall(parts) if len(w) >= 3} - _NAME_STOP


def _named_in(words: set[str], sentence_words: set[str]) -> bool:
    """A quantity's name words appear in the sentence ("max" in "maximum", "stopping" in "stopping")."""
    return any(s == w or s.startswith(w) or (len(s) >= 4 and w.startswith(s)) for w in words for s in sentence_words)


def misattributed_numbers(text: str, ledger: list[dict[str, Any]] | None) -> list[str]:
    """Numbers attached to the wrong quantity (audit AUDIT-104).

    The presence check (unsupported_numbers) accepts a number that appears anywhere in the evidence, so "the maximum
    stopping time is 837,799, attained at n = 329" passed with the two values swapped. Here a number is flagged when
    it is the value of a ledger quantity that its sentence does not name, while the sentence names another quantity
    with a different value. Deliberately conservative: a sentence naming no quantity is not judged.
    """
    quantities: list[tuple[str, set[str], set[str]]] = []
    for f in ledger or []:
        for q in f.get("quantities") or []:
            v = q.get("value")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                continue
            words = _name_words(q.get("name"))
            if words:
                quantities.append((str(q.get("name")), words, _forms(float(v))))
    if len(quantities) < 2:
        return []
    body = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(body):
        words = {w.lower() for w in _WORD_RE.findall(sentence) if len(w) >= 3} - _NAME_STOP
        named = [q for q in quantities if _named_in(q[1], words)]
        if not named:
            continue
        for m in _NUMBER_RE.findall(sentence):
            raw = m.replace(",", "")
            try:
                v = float(raw)
            except ValueError:
                continue
            if v == int(v) and (abs(v) <= 20 or 1900 <= v <= 2100):
                continue
            digits = len(re.sub(r"[^0-9]", "", raw.split("e")[0].split("E")[0]).lstrip("0")) or 1
            key = f"{v:.{min(12, max(2, digits))}g}"
            owners = [q for q in quantities if key in q[2] or raw in q[2]]
            if not owners or any(q in named for q in owners):
                continue
            others = [q for q in named if q not in owners]
            if others:
                out.append(f"{m} (the value of {owners[0][0]}, in a sentence about {others[0][0]})")
    return list(dict.fromkeys(out))[:20]


def unsupported_numbers(text: str, evidence: set[str]) -> list[str]:
    """Numbers in `text` that no evidence states, at any rounding from 2 to 12 significant digits. Small integers,
    years and section numbers are exempt."""
    bad = []
    body = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    body = re.sub(r"\]\([^)]*\)", "]", body)  # link targets and image paths
    for m in _NUMBER_RE.findall(body):
        raw = m.replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        if v == int(v) and (abs(v) <= 20 or 1900 <= v <= 2100):
            continue
        digits = len(re.sub(r"[^0-9]", "", raw.split("e")[0].split("E")[0]).lstrip("0")) or 1
        if f"{v:.{min(12, max(2, digits))}g}" in evidence or raw in evidence:
            continue
        if any(f"{v:.{d}g}" in evidence for d in range(2, min(12, digits) + 1)) and digits <= 3:
            continue
        bad.append(m)
    return list(dict.fromkeys(bad))[:40]


__all__ = ["TIER_LABEL", "TIER_RANK", "evidence_numbers", "finding_line", "ledger_text", "meets", "next_id",
           "quantities_from_result", "rank", "save_figures", "unsupported_numbers"]
