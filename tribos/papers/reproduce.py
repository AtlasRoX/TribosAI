"""Reproduce the stated results of a paper from its own equations and parameters.

For each stated result ("we obtain T = 1.42 s"):

- a closed-form claim is re-evaluated with SymPy from the paper's equation for that quantity and the paper's parameter
  values (all converted to SI base units with Pint);
- a claim about a state of an extracted ODE system at a time ("x(10) = 0.37") is re-run with Dynamis from the paper's
  initial conditions ("x(0) = 1") and parameters.

Each claim gets a status: "reproduced" (agrees within the stated precision, at least 0.5%), "differs" (both values and
the relative difference), or "not_reproducible" (which inputs or equations the paper does not give). Nothing is ever
guessed: a missing parameter is never filled with a default, so "reproduced" always means from the paper's own inputs.
"""

from __future__ import annotations

import math
import re
from typing import Any

import sympy as sp

from tribos.axiom.engine import safe_parse_expr

MIN_RELATIVE_TOLERANCE = 0.005
_CALL_RE = re.compile(r"^([A-Za-z]\w*)\(([^()]+)\)$")


def _si(value: float, unit: str) -> tuple[float, str | None]:
    """(value in SI base units, a note when the unit was not recognised)."""
    if not unit:
        return value, None
    try:
        from tribos.physis.units import get_unit_registry

        ureg = get_unit_registry()
        return float(ureg.Quantity(value, unit).to_base_units().magnitude), None
    except Exception:  # noqa: BLE001
        return value, f"unit {unit!r} was not recognised, so it was used as written"


def _stated_tolerance(value: float, text: str) -> float:
    """The relative tolerance a stated number allows: half a unit of its last digit, at least 0.5%."""
    m = re.search(r"=\s*[-+]?(\d*)\.?(\d*)", text)
    decimals = len(m.group(2)) if m else 0
    half_unit = 0.5 * 10 ** (-decimals)
    return max(MIN_RELATIVE_TOLERANCE, half_unit / abs(value)) if value else MIN_RELATIVE_TOLERANCE


def _compare(stated: float, computed: float, tolerance: float) -> tuple[str, float]:
    rel = abs(computed - stated) / abs(stated) if stated else abs(computed)
    return ("reproduced" if rel <= tolerance else "differs"), rel


def _parameter_table(extracted: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """name -> {value (SI), source}; the first statement of a name wins (a later one is usually a result)."""
    table: dict[str, dict[str, Any]] = {}
    for p in extracted.get("parameters") or []:
        name = str(p.get("name"))
        if name in table:
            continue
        si, note = _si(float(p["value"]), str(p.get("unit") or ""))
        table[name] = {"value": si, "page": p.get("page"), "line": p.get("line"), "note": note,
                       "as_written": f"{p['value']:g} {p.get('unit') or ''}".strip()}
    return table


def _closed_form(claim: dict[str, Any], extracted: dict[str, Any], params: dict[str, dict[str, Any]]) -> dict[str, Any]:
    name = str(claim["name"])
    candidates = [e for e in extracted.get("equations") or [] if e.get("lhs") == name and e.get("sympy")]
    if not candidates:
        return {"status": "not_reproducible", "reason": f"the paper gives no equation for {name}", "missing": []}
    eq = candidates[0]
    expr = safe_parse_expr(str(eq["sympy"]))
    symbols = sorted(str(s) for s in expr.free_symbols)
    missing = [s for s in symbols if s not in params]
    base = {"equation": f"{name} = {eq['rhs']}", "equation_page": eq.get("page"), "equation_line": eq.get("line")}
    if missing:
        return {**base, "status": "not_reproducible", "missing": missing,
                "reason": f"the paper states no value for {', '.join(missing)}"}
    value = float(expr.subs({sp.Symbol(s): params[s]["value"] for s in symbols}).evalf())
    return {**base, "computed": value, "inputs": {s: params[s] for s in symbols}}


def _ode(claim: dict[str, Any], extracted: dict[str, Any], params: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    call = _CALL_RE.match(str(claim["name"]))
    odes = [o for o in extracted.get("odes") or [] if o.get("sympy")]
    states = [o["state"] for o in odes]
    if not call or call.group(1) not in states:
        return None
    try:
        t_end = float(call.group(2))
    except ValueError:
        return {"status": "not_reproducible", "reason": f"the time {call.group(2)!r} is not a number", "missing": []}
    rhs = {o["state"]: o["sympy"] for o in odes}
    initial_keys: dict[str, str] = {}
    missing: list[str] = []
    for s in states:
        key = next((k for k in (f"{s}(0)", f"{s}0", f"{s}_0") if k in params), None)
        if key is None:
            missing.append(f"{s}(0)")
        else:
            initial_keys[s] = key
    names = set().union(*(safe_parse_expr(r).free_symbols for r in rhs.values()))
    needed = sorted(str(n) for n in names if str(n) not in states and str(n) != "t")
    missing += [n for n in needed if n not in params]
    base = {"equation": "; ".join(f"d{s}/dt = {o['rhs']}" for s, o in zip(states, odes, strict=True)),
            "equation_page": odes[0].get("page"), "method": "Dynamis (solve_ivp)"}
    if missing:
        return {**base, "status": "not_reproducible", "missing": missing,
                "reason": f"the paper states no value for {', '.join(missing)}"}
    from tribos.dynamis.engine import dynamis_simulate_ode

    # t_span as a list: the engine reads a tuple as "the default span" (see tribos/dynamis/interactive.py).
    run = dynamis_simulate_ode(rhs=rhs, initial_state={s: params[k]["value"] for s, k in initial_keys.items()},
                               t_span=[0.0, t_end], parameters={n: params[n]["value"] for n in needed},  # type: ignore[arg-type]
                               num_points=200)
    final = (run.get("summary") or {}).get(call.group(1), {}).get("final")
    if final is None or not math.isfinite(final):
        return {**base, "status": "not_reproducible", "missing": [], "reason": "the integration did not finish"}
    inputs = {n: params[n] for n in [*needed, *initial_keys.values()]}
    return {**base, "computed": float(final), "inputs": inputs}


def reproduce_paper(extracted: dict[str, Any], targets: list[str] | None = None) -> dict[str, Any]:
    params = _parameter_table(extracted)
    # A result the paper states (T = 0.314 s) may be the input of a later equation (f = 1/T): it is still the paper's
    # own value, and it is labelled as a stated result.
    for c in extracted.get("claims") or []:
        if str(c["name"]) not in params and "(" not in str(c["name"]):
            si, note = _si(float(c["value"]), str(c.get("unit") or ""))
            params[str(c["name"])] = {"value": si, "page": c.get("page"), "line": c.get("line"), "note": note,
                                      "as_written": f"{c['value']:g} {c.get('unit') or ''}".strip(),
                                      "stated_result": True}
    wanted = {t.strip() for t in targets or [] if t and t.strip()}
    results: list[dict[str, Any]] = []
    for claim in extracted.get("claims") or []:
        if wanted and claim["name"] not in wanted and claim["name"].split("(")[0] not in wanted:
            continue
        stated_si, unit_note = _si(float(claim["value"]), str(claim.get("unit") or ""))
        outcome = _ode(claim, extracted, params) or _closed_form(claim, extracted, params)
        row: dict[str, Any] = {
            "name": claim["name"], "stated": claim["value"], "unit": claim.get("unit") or "", "stated_si": stated_si,
            "page": claim.get("page"), "line": claim.get("line"), **outcome,
        }
        if "computed" in outcome:
            tol = _stated_tolerance(float(claim["value"]), str(claim.get("text") or ""))
            row["status"], row["relative_difference"] = _compare(stated_si, outcome["computed"], tol)
            row["tolerance"] = tol
        notes = [n for n in [unit_note, *(i.get("note") for i in (outcome.get("inputs") or {}).values() if isinstance(i, dict))] if n]
        if notes:
            row["notes"] = notes
        results.append(row)
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("reproduced", "differs", "not_reproducible")}
    return {
        "claims": results,
        "counts": counts,
        "parameters": [{"name": k, **v} for k, v in params.items()],
        "note": "Values are compared in SI base units; only the paper's own equations and parameter values are used, "
                "so a claim whose inputs the paper does not state is reported as not reproducible, never guessed.",
    }


__all__ = ["reproduce_paper"]
