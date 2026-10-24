"""
Check browser-posted report content against the stored run manifest (PRV-001).

An export names a run id; when that run is in the caller's RunStore the report is labelled "server run store".
The body of the report (tables, citations, task status, verification, question) still arrives from the browser,
so every section that the stored manifest can confirm is compared with it here:

- answer text (sha256, in report_model), verification passed/score/defect count, simulation final values;
- computation rows (tool, step) against Calcula/sandbox digests;
- reference data rows (entity, symbol) against Physis digests;
- simulation rows (model, variable, final value) against Dynamis / Vivarix digests;
- citation identifiers (PMID, DOI, typed id, URL) against every identifier the run's tool outputs recorded;
- the task status (the stored one is used) and the question (the stored query is used).

Rows that do not match are marked in the table itself; mismatches become notices; sections the manifest cannot
confirm (plots, claim lists, retraction flags) are listed as "not checked".
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

NOT_IN_RUN = "not in stored run"


@dataclass
class CheckResult:
    notices: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    unmatched_citation_keys: set[str] = field(default_factory=set)
    bad_row_keys: set[str] = field(default_factory=set)
    mismatch: bool = False

    def mismatch_notice(self, text: str) -> None:
        self.mismatch = True
        self.notices.append(text)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _calls(manifest: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    return [
        c for c in manifest.get("tool_calls") or []
        if isinstance(c, dict) and c.get("success") and (not names or c.get("tool_name") in names)
    ]


def _digests(manifest: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    return [c.get("output_digest") or {} for c in _calls(manifest, *names) if isinstance(c.get("output_digest"), dict)]


def _norm_phase(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _text(value).upper())


def _num(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _same_number(a: Any, b: Any, rel: float = 1e-9) -> bool:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return False
    return abs(x - y) <= rel * max(1.0, abs(y))


# --- identifiers the run recorded -------------------------------------------------------------------------------

def _collect_strings(value: Any, out: set[str], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(str(k).strip().upper())
            _collect_strings(v, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_strings(v, out, depth + 1)
    elif isinstance(value, str) and value.strip():
        out.add(value.strip().upper())


def recorded_identifiers(manifest: dict[str, Any]) -> set[str]:
    """Every identifier-like string in the run's successful tool outputs (digests and canonical ids), upper-cased."""
    out: set[str] = set()
    for call in _calls(manifest):
        _collect_strings(call.get("output_digest") or {}, out)
        _collect_strings(call.get("canonical_ids") or {}, out)
    # A PMID is recorded bare; citations may carry "PMID:123".
    out |= {f"PMID:{v}" for v in list(out) if v.isdigit()}
    return out


def _citation_found(row: dict[str, Any], ids: set[str]) -> bool:
    candidates = []
    if _text(row.get("pmid")):
        candidates += [_text(row["pmid"]).upper(), f"PMID:{_text(row['pmid'])}".upper()]
    if _text(row.get("arxiv_id")) or _text(row.get("arxiv")):
        val = _text(row.get("arxiv_id") or row.get("arxiv")).upper()
        candidates += [val, f"ARXIV:{val}"]
    if _text(row.get("doi")):
        candidates.append(_text(row["doi"]).upper())
    if _text(row.get("id")):
        candidates.append(_text(row["id"]).upper())
    if _text(row.get("url")):
        candidates.append(_text(row["url"]).upper().rstrip("/"))
        candidates.append(_text(row["url"]).upper())
    return any(c in ids for c in candidates if c)


# --- per-section checks -----------------------------------------------------------------------------------------

def check_computations(art: Any, manifest: dict[str, Any]) -> tuple[set[str] | None, int]:
    """Check computation rows against Calcula/sandbox tool calls in the manifest."""
    if not art:
        return None, 0
    items = []
    if isinstance(art, list):
        items = [x for x in art if isinstance(x, dict)]
    elif isinstance(art, dict):
        for key in ("computations", "executions", "calculations", "steps", "items"):
            val = art.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                items = val
                break
        if not items and any(k in art for k in ("code", "result", "stdout", "status", "tool", "tool_name")):
            items = [art]

    calls = [
        c for c in manifest.get("tool_calls") or []
        if isinstance(c, dict) and any(
            str(c.get("tool_name", "")).startswith(p)
            for p in ("calcula", "analysis", "sandbox")
        )
    ]
    if not items or not calls:
        return None, 0

    recorded_tools = {_text(c.get("tool_name")).upper() for c in calls if c.get("success")}
    bad: set[str] = set()
    for it in items:
        tool = _text(it.get("tool") or it.get("tool_name") or it.get("step") or it.get("name") or "CALCULA_RUN_PYTHON")
        key = _text(it.get("tool") or it.get("tool_name") or it.get("step") or it.get("name") or "calculation")
        if tool.upper() not in recorded_tools and not any(tool.upper() in t or t in tool.upper() for t in recorded_tools):
            bad.add(key)
    return bad, len(items)


def check_reference_data(art: Any, manifest: dict[str, Any]) -> tuple[set[str] | None, int]:
    """Check physical constants and reference properties against Physis tool calls in the manifest."""
    if not art:
        return None, 0
    items = []
    if isinstance(art, list):
        items = [x for x in art if isinstance(x, dict)]
    elif isinstance(art, dict):
        for key in ("constants", "materials", "sequences", "units", "properties", "items", "records", "data"):
            val = art.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                items = val
                break
        if not items and any(k in art for k in ("entity", "symbol", "name", "value")):
            items = [art]

    calls = [
        c for c in manifest.get("tool_calls") or []
        if isinstance(c, dict) and str(c.get("tool_name", "")).startswith("physis") and c.get("success")
    ]
    if not items or not calls:
        return None, 0

    ids = recorded_identifiers(manifest)
    bad: set[str] = set()
    for it in items:
        sym = _text(it.get("symbol") or it.get("id"))
        name = _text(it.get("name") or it.get("entity"))
        key = sym or name
        if not key:
            continue
        if sym.upper() not in ids and name.upper() not in ids:
            bad.add(key)
    return bad, len(items)


def check_simulations(art: Any, manifest: dict[str, Any]) -> tuple[set[str] | None, int]:
    """Check Dynamis / Vivarix ODE simulation values against manifest tool calls."""
    if not art:
        return None, 0
    calls = [
        c for c in manifest.get("tool_calls") or []
        if isinstance(c, dict) and c.get("success") and any(
            str(c.get("tool_name", "")).startswith(p) for p in ("dynamis", "vivarix")
        )
    ]
    if not calls:
        return None, 0

    recorded_final: dict[str, float] = {}
    for c in calls:
        digest = c.get("output_digest") or {}
        if isinstance(digest, dict):
            for k in ("final_concentrations", "final_state", "summary"):
                sub = digest.get(k)
                if isinstance(sub, dict):
                    for var, val in sub.items():
                        num = _num(val.get("final") if isinstance(val, dict) else val)
                        if num is not None:
                            recorded_final[str(var).upper()] = num

    posted: dict[str, Any] = {}
    if isinstance(art, dict):
        if isinstance(art.get("final_concentrations"), dict):
            posted.update(art["final_concentrations"])
        elif isinstance(art.get("summary"), dict):
            for var, val in art["summary"].items():
                if isinstance(val, dict):
                    posted[str(var)] = val.get("final")
        elif isinstance(art.get("fixed_point"), dict):
            posted.update(art["fixed_point"])
        elif isinstance(art.get("simulations"), list):
            for it in art["simulations"]:
                if isinstance(it, dict) and it.get("variable"):
                    posted[str(it["variable"])] = it.get("final")
    elif isinstance(art, list):
        for it in art:
            if isinstance(it, dict) and (it.get("variable") or it.get("model")):
                v = it.get("variable") or it.get("model")
                posted[str(v)] = it.get("final")

    if not posted or not recorded_final:
        return None, 0

    bad: set[str] = set()
    for var, val in posted.items():
        v_upper = str(var).upper()
        if v_upper not in recorded_final:
            bad.add(str(var))
        elif val is not None and not _same_number(val, recorded_final[v_upper]):
            bad.add(str(var))
    return bad, len(posted)


def _norm_question(text: str) -> str:
    return " ".join(_text(text).split()).strip("\"'“”‘’ ").casefold()


def check_report(
    manifest: dict[str, Any],
    *,
    artifacts: dict[str, Any],
    citation_rows: Iterable[dict[str, Any]],
    posted_task: Any,
    posted_question: str,
    verification: Any,
) -> CheckResult:
    """Compare the browser-posted sections with the stored manifest; see the module docstring."""
    out = CheckResult()

    # Question: the stored query is authoritative.
    stored_query = _text(manifest.get("query"))
    if stored_query and posted_question.strip() and _norm_question(posted_question) != _norm_question(stored_query):
        out.mismatch_notice("The submitted question differs from the stored run's question; the stored question is shown.")
    if stored_query:
        out.checked.append("question")

    # Task status: the stored outcome is authoritative.
    stored_task = manifest.get("task_status") if isinstance(manifest.get("task_status"), dict) else {}
    if stored_task and isinstance(posted_task, dict) and posted_task:
        keys = ("task_status", "requested_operation", "executed_operation", "request_match")
        if any(posted_task.get(k) != stored_task.get(k) for k in keys if k in posted_task or k in stored_task):
            out.mismatch_notice("The submitted task status differs from the stored run; the stored task status is shown.")
    if stored_task:
        out.checked.append("task status")
    elif isinstance(posted_task, dict) and posted_task:
        out.unchecked.append("task status")

    # Verification: defect count (score and pass are compared in report_model._stored_run_mismatches).
    final = (manifest.get("verification") or {}).get("final") or {}
    if verification is not None and final:
        out.checked.append("verification score and defect count")
        n_defects = final.get("n_defects")
        if isinstance(n_defects, int) and len(getattr(verification, "defects", []) or []) != n_defects:
            out.mismatch_notice(
                f"The verification report lists {len(verification.defects)} defect(s); the stored run recorded {n_defects}."
            )
        if getattr(verification, "claims", None):
            out.unchecked.append("claim list")

    # Tables.
    for label, (bad, n) in (
        ("computations", check_computations(artifacts.get("calcula") or artifacts.get("sandbox"), manifest)),
        ("reference data", check_reference_data(artifacts.get("physis") or artifacts.get("reference_data"), manifest)),
        ("simulations", check_simulations(artifacts.get("dynamis") or artifacts.get("simulation") or artifacts.get("vivarix"), manifest)),
    ):
        if bad is None:
            continue
        out.checked.append(label)
        out.bad_row_keys |= {b.upper() for b in bad if b}
        if bad:
            shown = ", ".join(sorted(b for b in bad if b)[:8])
            out.mismatch_notice(
                f"{len(bad)} of {n} {label} row(s) do not match this run's recorded tool outputs ({shown}); they are marked "
                f"'{NOT_IN_RUN}'."
            )
    has_tables = {
        "computations": bool(artifacts.get("calcula") or artifacts.get("sandbox")),
        "reference data": bool(artifacts.get("physis") or artifacts.get("reference_data")),
        "simulations": bool(artifacts.get("dynamis") or artifacts.get("simulation")),
    }
    for label, present in has_tables.items():
        if present and label not in out.checked:
            out.unchecked.append(label)
    comp = artifacts.get("calcula") or artifacts.get("sandbox") or {}
    if isinstance(comp, dict) and comp.get("figures"):
        out.unchecked.append("computation plots")
    sim = artifacts.get("dynamis") or artifacts.get("simulation") or artifacts.get("vivarix") or {}
    if isinstance(sim, dict) and sim.get("plot_base64_png"):
        out.unchecked.append("simulation plot")
    if isinstance(sim, dict) and (sim.get("initial_concentrations") or sim.get("steady_state")):
        out.unchecked.append("initial and steady-state simulation values")

    # Citations.
    rows = list(citation_rows)
    if rows:
        ids = recorded_identifiers(manifest)
        from .report_model import source_key

        missing = {source_key(r) for r in rows if not _citation_found(r, ids)}
        missing.discard("")
        out.unmatched_citation_keys = missing
        out.checked.append("citation identifiers")
        if missing:
            out.mismatch_notice(
                f"{len(missing)} of {len(rows)} source(s) were not returned by this run's recorded tool calls; they are "
                f"marked '{NOT_IN_RUN}'."
            )
        out.unchecked.append("citation retraction and verification flags")
    out.unchecked = list(dict.fromkeys(out.unchecked))
    return out


def mark_rows(tables: list[Any], bad_keys: set[str]) -> None:
    """Append the not-in-run marker to the first cell of each table row whose key is in bad_keys."""
    for table in tables:
        for row in getattr(table, "rows", []) or []:
            if not row:
                continue
            cells = [_text(cell).upper() for cell in row[:2]]
            if any(_cell_matches(cell, key) for cell in cells if cell for key in bad_keys):
                row[0] = f"{row[0]} ({NOT_IN_RUN})"


def _cell_matches(cell: str, key: str) -> bool:
    if cell == key:
        return True
    return cell.endswith("…") and len(cell) > 1 and key.startswith(cell[:-1])
