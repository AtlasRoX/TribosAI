"""
The research dashboard: generative-UI blocks (the web/src/lib/genui.ts contract) built from the ledger, so every
number shown is one a test produced. Per finding: its key values as stat tiles, each data series as a chart, and its
verification checks. Project level: the headline, deliverables as a checklist, hypotheses as a table.
"""

from __future__ import annotations

import math
from typing import Any

from .ledger import TIER_LABEL, rank


def _value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.8g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_value(x) for x in v[:6]) + (" …" if len(v) > 6 else "")
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_value(x)}" for k, x in list(v.items())[:4])
    return str(v)[:80]


def finding_blocks(f: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    verified = rank(f.get("tier")) >= rank("replicated")
    scalars = [q for q in f.get("quantities") or [] if isinstance(q.get("value"), (int, float, str))
               and not isinstance(q.get("value"), bool)][:8]
    if scalars:
        blocks.append({"type": "stats", "title": None, "items": [
            {"label": q["name"].replace("_", " ")[:60], "value": _value(q["value"]), "verified": verified}
            for q in scalars]})
    for s in (f.get("series") or [])[:2]:
        pts = [[float(x), float(y)] for x, y in zip(s["x"], s["y"], strict=False)
               if math.isfinite(float(x)) and math.isfinite(float(y))]
        if len(pts) < 2:
            continue
        blocks.append({"type": "chart", "title": s.get("name"),
                       "x": {"label": s.get("x_label") or "x", "scale": "log" if s.get("log_x") else "linear"},
                       "y": {"label": s.get("y_label") or "y", "scale": "log" if s.get("log_y") else "linear"},
                       "series": [{"name": s.get("name") or "data", "points": pts[:400]}], "marks": []})
    others = [q for q in f.get("quantities") or [] if q not in scalars][:12]
    if others:
        blocks.append({"type": "table", "title": None,
                       "columns": [{"key": "name", "label": "Quantity"}, {"key": "value", "label": "Value"}],
                       "rows": [{"name": q["name"].replace("_", " "), "value": _value(q["value"])} for q in others]})
    if f.get("checks"):
        blocks.append({"type": "checks", "title": None, "items": [
            {"name": c["name"], "passed": bool(c.get("passed")), "detail": str(c.get("detail") or "")[:200]}
            for c in f["checks"][:6]]})
    return blocks


def build_dashboard(campaign: dict[str, Any]) -> dict[str, Any]:
    charter = campaign.get("charter") or {}
    rounds = campaign.get("rounds") or []
    headline = next((r.get("headline") for r in reversed(rounds) if r.get("headline")), "")
    project: list[dict[str, Any]] = []
    if headline:
        project.append({"type": "callout", "tone": "insight", "title": "Where the research stands", "text": headline})
    if charter.get("deliverables"):
        project.append({"type": "checks", "title": "Deliverables", "items": [
            {"name": f"{d['id']} · {d['title']}"[:120], "passed": d.get("status") == "done",
             "detail": (d.get("status") or "open") + (f" — {d['note']}" if d.get("note") else "")
                       + (f" (evidence: {', '.join(d.get('evidence') or [])})" if d.get("evidence") else "")}
            for d in charter["deliverables"]]})
    if charter.get("hypotheses"):
        project.append({"type": "table", "title": "Hypotheses",
                        "columns": [{"key": "id", "label": ""}, {"key": "statement", "label": "Hypothesis"},
                                    {"key": "verdict", "label": "Verdict"}, {"key": "evidence", "label": "Evidence"}],
                        "rows": [{"id": h["id"], "statement": h["statement"][:200], "verdict": h.get("verdict") or "",
                                  "evidence": ", ".join(h.get("evidence") or [])} for h in charter["hypotheses"]]})
    findings = []
    for f in campaign.get("ledger") or []:
        findings.append({"id": f["id"], "test_id": f.get("test_id"), "status": f.get("status"),
                         "tier": f.get("tier"), "tier_label": TIER_LABEL.get(f.get("tier") or "none"),
                         "blocks": finding_blocks(f)})
    return {"version": 1, "project": project, "findings": findings}


__all__ = ["build_dashboard", "finding_blocks"]
