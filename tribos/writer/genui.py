"""
Generative UI for answers: a small typed spec of blocks the web client renders as native components.

Two sources produce blocks:

- build_answer_ui(facts): the results panel built from the code-computed results (tribos.writer.facts). Every
  number in it comes from the computation, so it needs no further check: key quantities as tiles (exact form and
  decimal, with units), the exact solution with its checks, a plot of the solution, and the requested values with
  the RK4 comparison.
- ```ui fenced blocks the writer may put inside the answer (stats, callout, steps, table). They are parsed and
  validated by sanitize_ui_blocks: an invalid block, or one carrying a number that is not in the evidence, is removed
  from the answer, so the interface never shows an unchecked value the prose could not.

The block types and their fields are the contract with web/src/lib/genui.ts; keep the two in step.
"""

from __future__ import annotations

import json
import re
from typing import Any

SPEC_VERSION = 1
WRITER_BLOCK_TYPES = frozenset({"stats", "callout", "steps", "table", "chart", "equation"})
MAX_CHART_SERIES = 4
MAX_CHART_POINTS = 200
CALLOUT_TONES = frozenset({"info", "insight", "warning", "ok"})
MAX_ITEMS = 12
MAX_TEXT = 600
_UI_FENCE_RE = re.compile(r"```ui[ \t]*\n(.*?)```", re.S)


_SHORT_LABELS = {"phase lag of the response behind the forcing": "phase lag (behind forcing)"}


def _stat(param: dict[str, Any]) -> dict[str, Any]:
    name = str(param.get("name", ""))
    out = {
        "label": _SHORT_LABELS.get(name, name)[:80],
        "value": str(param.get("value", "")),
        "unit": "" if param.get("unit") in (None, "dimensionless") else str(param.get("unit")),
        "exact_latex": str(param.get("exact_latex") or ""),
        "verified": True,
    }
    if param.get("value_degrees"):
        out["secondary"] = f"{param['value_degrees']}°"
    return out


def build_answer_ui(facts: dict[str, Any] | None) -> dict[str, Any] | None:
    """The results panel for code-computed results, or None when there is nothing checked to show."""
    if facts and facts.get("kind") == "number_theory_finite":
        return _number_ui(facts)
    if facts and facts.get("kind") == "nbody_gravity":
        return _nbody_ui(facts)
    if facts and facts.get("kind") == "polynomial_analysis":
        return _poly_ui(facts)
    if facts and facts.get("kind") == "polynomial_roots":
        return _roots_ui(facts)
    if facts and facts.get("kind") == "dynamical_system":
        return _system_ui(facts)
    if facts and facts.get("kind") == "pde_heat":
        return _pde_ui(facts)
    if facts and facts.get("kind") == "construction_search":
        return _construct_ui(facts)
    if facts and facts.get("kind") == "pde_poisson":
        return _poisson_ui(facts)
    if not facts or facts.get("kind") != "ode_initial_value_problem" or not facts.get("exact_solution_latex"):
        return None
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    if not checks or not all(c.get("passed") for c in checks):
        return None
    units = facts.get("units") or {}
    t_unit, x_unit = units.get("time") or "", units.get("solution") or ""
    dep, ind = facts.get("dependent", "x"), facts.get("independent", "t")
    blocks: list[dict[str, Any]] = []

    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    if params:
        order = ("natural frequency", "damping ratio", "damped natural frequency", "steady-state amplitude",
                 "phase lag of the response behind the forcing")
        ranked = sorted(params, key=lambda p: order.index(p["name"]) if p.get("name") in order else len(order))
        blocks.append({"type": "stats", "title": "Key quantities", "items": [_stat(p) for p in ranked][:MAX_ITEMS]})

    latex = facts["exact_solution_latex"]
    if facts.get("transient_latex") and facts.get("steady_state_latex"):
        # Two aligned lines (transient, then steady state): a long solution fits the panel instead of overflowing.
        # Each line is named under it, so the parts need no separate listing (web/src/lib/genui.ts equationLatex).
        latex = (rf"\begin{{aligned}} {dep}({ind}) &= \underbrace{{{facts['transient_latex']}}}_{{\text{{transient}}}} \\ "
                 rf"&\quad + \underbrace{{{facts['steady_state_latex']}}}_{{\text{{steady state}}}} \end{{aligned}}")
    blocks.append({
        "type": "equation",
        "title": "Exact solution",
        "latex": latex,
        "parts": [
            {"label": "Transient", "latex": facts["transient_latex"]} if facts.get("transient_latex") else None,
            {"label": "Steady state", "latex": facts["steady_state_latex"]} if facts.get("steady_state_latex") else None,
        ],
        "checks": [{"name": str(c.get("name")), "passed": bool(c.get("passed"))} for c in checks],
    })
    blocks[-1]["parts"] = [p for p in blocks[-1]["parts"] if p]

    curve = facts.get("curve") or {}
    if curve.get("t") and curve.get("x"):
        series = [{"name": f"{dep}({ind})", "points": list(zip(curve["t"], curve["x"], strict=False))}]
        if curve.get("steady"):
            series.append({"name": "steady state", "points": list(zip(curve["t"], curve["steady"], strict=False)),
                           "style": "dashed"})
        marks = [[float(r[ind]), float(r[dep])] for r in facts.get("table") or [] if ind in r and dep in r]
        blocks.append({
            "type": "chart",
            "title": f"{dep}({ind}) from the exact solution",
            "x": {"label": ind, "unit": t_unit},
            "y": {"label": dep, "unit": x_unit},
            "series": series,
            "marks": marks,
        })

    rk = facts.get("rk4") or {}
    rows = rk.get("at_points") or []
    if rows:
        blocks.append({
            "type": "table",
            "title": "Requested values and RK4 comparison",
            "columns": [
                {"key": ind, "label": ind, "unit": t_unit, "align": "right"},
                {"key": "reference", "label": f"exact {dep}", "unit": x_unit, "align": "right"},
                {"key": "rk4", "label": "RK4", "unit": x_unit, "align": "right"},
                {"key": "abs_error", "label": "|error|", "unit": x_unit, "align": "right"},
            ],
            "rows": [{k: str(r.get(k, "")) for k in (ind, "reference", "rk4", "abs_error")} for r in rows],
            "caption": (f"Classical RK4, step {rk.get('step')} {t_unit}".strip() + f"; maximum absolute error "
                        f"{rk.get('max_abs_error')} at {ind} = {rk.get('max_error_at')}"),
        })
    elif facts.get("table"):
        blocks.append({
            "type": "table",
            "title": "Requested values",
            "columns": [{"key": ind, "label": ind, "unit": t_unit, "align": "right"},
                        {"key": dep, "label": f"{dep}({ind})", "unit": x_unit, "align": "right"}],
            "rows": [{k: str(v) for k, v in r.items()} for r in facts["table"]],
        })
    blocks.extend(_analysis_blocks(facts, t_unit, x_unit))
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": blocks}


def _number_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Finite number-theory results (tribos.writer.number_facts): values, their double checks, the Goldbach pairs and
    the Collatz orbit on a log scale, with the open-problem caveat."""
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    if not params or not checks:
        return None
    blocks: list[dict[str, Any]] = [{
        "type": "stats", "title": "Computed values",
        "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": str(p.get("unit") or ""),
                   "exact_latex": "", "verified": True} for p in params][:MAX_ITEMS],
    }]
    if facts.get("open_problems"):
        blocks.append({"type": "callout", "tone": "warning", "title": "Evidence, not proof",
                       "text": "; ".join(facts.get("notes") or [])[:MAX_TEXT]})
    blocks.append({"type": "checks", "title": "Independent checks",
                   "caption": "Each value computed twice by different methods (a sieve and sympy.isprime; direct "
                              "iteration and memoised recursion)",
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    orbit = facts.get("collatz_orbit") or {}
    values = orbit.get("values") or []
    if len(values) >= 3:
        blocks.append({
            "type": "chart", "title": f"Collatz orbit of {orbit.get('start')} (log scale)",
            "x": {"label": "step", "unit": ""}, "y": {"label": "value", "unit": "", "scale": "log"},
            "series": [{"name": f"orbit of {orbit.get('start')}", "points": [[i, v] for i, v in enumerate(values)]}],
            "marks": [[values.index(max(values)), max(values), f"peak {max(values)}"]],
        })
    for part in facts.get("partitions") or []:
        blocks.append({
            "type": "table", "title": f"Goldbach partitions of {part['n']} ({len(part['pairs'])})",
            "columns": [{"key": "p", "label": "p", "align": "right"}, {"key": "q", "label": "q", "align": "right"},
                        {"key": "sum", "label": "p + q", "align": "right"}],
            "rows": [{"p": str(a), "q": str(b), "sum": str(a + b)} for a, b in part["pairs"]],
        })
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": blocks}


def _pde_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """The heat equation solved by code (tribos.writer.pde_facts): the problem and exact solution, the numerical
    profile against it, the refinement table with observed orders, the convergence plot and the checks."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    rows = facts.get("refinement") or []
    prof = facts.get("profile") or {}
    if not params or not checks or not rows:
        return None
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": [
        {"type": "stats", "title": "Measured convergence",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": "", "exact_latex": "", "verified": True}
                   for p in params][:MAX_ITEMS]},
        {"type": "equation", "title": "Problem and exact (manufactured) solution",
         "latex": r"\begin{aligned}" + facts["equation_latex"] + r" \\ " + facts["exact_latex"] + r"\end{aligned}",
         "parts": [], "checks": []},
        {"type": "chart", "title": f"u(x, {facts['t_end']:g}): Crank-Nicolson against the exact solution",
         "x": {"label": "x", "unit": ""}, "y": {"label": "u", "unit": ""},
         "series": [{"name": "Crank-Nicolson", "points": [[x, v] for x, v in zip(prof["x"], prof["numeric"], strict=False)]},
                    {"name": "exact", "points": [[x, v] for x, v in zip(prof["x"], prof["exact"], strict=False)],
                     "style": "dashed"}], "marks": []},
        {"type": "chart", "title": "Error under refinement (log-log)",
         "x": {"label": "dx", "unit": "", "scale": "log"}, "y": {"label": "max error", "unit": "", "scale": "log"},
         "series": [{"name": "Crank-Nicolson", "points": [[r["dx"], r["cn_error"]] for r in rows]},
                    {"name": "FTCS", "points": [[r["dx"], r["ftcs_error"]] for r in rows]}], "marks": []},
        {"type": "table", "title": "Refinement study",
         "columns": [{"key": "n", "label": "intervals", "align": "right"}, {"key": "dx", "label": "dx", "align": "right"},
                     {"key": "cn", "label": "CN error", "align": "right"}, {"key": "cno", "label": "CN order", "align": "right"},
                     {"key": "ft", "label": "FTCS error", "align": "right"}, {"key": "fto", "label": "FTCS order", "align": "right"}],
         "rows": [{"n": str(r["n"]), "dx": f"{r['dx']:.4g}", "cn": f"{r['cn_error']:.3e}",
                   "cno": f"{r['cn_order']:.3f}" if "cn_order" in r else "",
                   "ft": f"{r['ftcs_error']:.3e}", "fto": f"{r['ftcs_order']:.3f}" if "ftcs_order" in r else ""} for r in rows]},
        {"type": "checks", "title": "Independent checks", "caption": "Run in Python: " + ", ".join(facts.get("methods") or []),
         "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]},
    ]}


def _construct_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Construct mode (tribos.agentic.construct): the best value against the known one, the search history and the
    exact re-scoring check."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    hist = [h for h in facts.get("history") or [] if h.get("best") is not None]
    if not params or not checks:
        return None
    blocks: list[dict[str, Any]] = [
        {"type": "stats", "title": facts.get("problem") or "Construction search",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"])[:160], "unit": "", "exact_latex": "",
                    "verified": bool(p.get("verified"))} for p in params][:MAX_ITEMS]},
        {"type": "callout", "tone": "info", "title": "Compared with the literature", "text": str(facts.get("verdict") or "")},
    ]
    if len(hist) > 1:
        blocks.append({"type": "chart", "title": "Best value found as programs were written",
                       "x": {"label": "program", "unit": ""}, "y": {"label": "best value", "unit": ""},
                       "series": [{"name": "best so far", "points": [[h["program"], h["best"]] for h in hist]}],
                       "marks": []})
    blocks.append({"type": "checks", "title": "Checks", "caption": "Run in Python: " + ", ".join(facts.get("methods") or []),
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": blocks}


def _poisson_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """The 2-D Poisson problem solved by finite elements (tribos.writer.pde_facts): convergence under refinement."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    rows = facts.get("refinement") or []
    if not params or not checks or not rows:
        return None
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": [
        {"type": "stats", "title": "Measured convergence",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": "", "exact_latex": "", "verified": True}
                   for p in params][:MAX_ITEMS]},
        {"type": "equation", "title": "Problem and exact (manufactured) solution",
         "latex": r"\begin{aligned}" + facts["equation_latex"] + r" \\ " + facts["exact_latex"] + r"\end{aligned}",
         "parts": [], "checks": []},
        {"type": "chart", "title": "Error under mesh refinement (log-log)",
         "x": {"label": "h", "unit": "", "scale": "log"}, "y": {"label": "error", "unit": "", "scale": "log"},
         "series": [{"name": "L2 error", "points": [[r["h"], r["l2"]] for r in rows]},
                    {"name": "H1 seminorm error", "points": [[r["h"], r["h1"]] for r in rows]}], "marks": []},
        {"type": "table", "title": "Refinement study",
         "columns": [{"key": "n", "label": "cells per side", "align": "right"}, {"key": "h", "label": "h", "align": "right"},
                     {"key": "l2", "label": "L2 error", "align": "right"}, {"key": "o2", "label": "L2 order", "align": "right"},
                     {"key": "h1", "label": "H1 error", "align": "right"}, {"key": "o1", "label": "H1 order", "align": "right"}],
         "rows": [{"n": str(r["n"]), "h": f"{r['h']:.4g}", "l2": f"{r['l2']:.3e}",
                   "o2": f"{r['l2_order']:.3f}" if "l2_order" in r else "", "h1": f"{r['h1']:.3e}",
                   "o1": f"{r['h1_order']:.3f}" if "h1_order" in r else ""} for r in rows]},
        {"type": "checks", "title": "Independent checks", "caption": "Run in Python: " + ", ".join(facts.get("methods") or []),
         "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]},
    ]}


def _system_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """A stated ODE system integrated by code (tribos.writer.system_facts): the equations as integrated, the final
    state, the time series, a phase portrait of the first two states, and the agreement and invariant checks."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    series = facts.get("series") or {}
    states = list(facts.get("states") or [])
    if not params or not checks or not series.get("t"):
        return None
    log_t = bool(facts.get("log_time"))
    t = series["t"]
    blocks: list[dict[str, Any]] = [
        {"type": "stats", "title": f"{facts.get('label', 'System')}: values at t = {facts.get('span'):g}",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": "", "exact_latex": "", "verified": True}
                   for p in params][:MAX_ITEMS]},
        {"type": "equation", "title": "Equations integrated (as stated)",
         "latex": r"\begin{aligned}" + r" \\ ".join(e.replace(" = ", " &= ", 1) for e in facts.get("equations_latex") or [])
                  + r"\end{aligned}", "parts": [], "checks": []},
        {"type": "chart", "title": "Time series" + (" (log time)" if log_t else ""),
         "x": {"label": "t", "unit": "", "scale": "log" if log_t else "linear"}, "y": {"label": "value", "unit": ""},
         "series": [{"name": s, "points": [[tt, v] for tt, v in zip(t, series[s], strict=False) if not log_t or tt > 0]}
                    for s in states[:4]], "marks": []},
    ]
    if len(states) >= 2:
        a, b = states[0], states[1]
        blocks.append({"type": "chart", "title": f"Phase portrait ({a}, {b})", "parametric": True,
                       "x": {"label": a, "unit": ""}, "y": {"label": b, "unit": ""},
                       "series": [{"name": "trajectory", "points": [[x, y] for x, y in zip(series[a], series[b], strict=False)]}],
                       "marks": [[series[a][0], series[b][0], "start"]]})
    if facts.get("notes"):
        blocks.append({"type": "callout", "tone": "info", "title": "How it was integrated",
                       "text": " ".join(facts["notes"])[:1000]})
    blocks.append({"type": "checks", "title": "Independent checks",
                   "caption": "Two tolerances and a second method; conserved quantities found symbolically",
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    return {"version": SPEC_VERSION, "title": "Simulation results", "source": "computed", "blocks": blocks}


def _roots_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Real roots isolated in Python (tribos.writer.roots_facts): the count and roots, the Sturm sequence, a plot with
    the roots marked, the certified intervals and residuals, and the checks."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    if not params or not checks:
        return None
    sturm = facts.get("sturm_latex") or []
    sign = lambda s: "+" if s > 0 else ("−" if s < 0 else "0")  # noqa: E731
    blocks: list[dict[str, Any]] = [
        {"type": "stats", "title": "Python outputs",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": "", "exact_latex": "",
                    "verified": True} for p in params if p.get("value")][:MAX_ITEMS]},
        {"type": "equation", "title": "Sturm sequence (exact rational arithmetic)",
         "latex": r"\begin{aligned}" + r" \\ ".join(f"p_{{{i}}} &= {s}" for i, s in enumerate(sturm)) + r"\end{aligned}",
         "parts": [], "checks": []},
        {"type": "table", "title": "Sign changes",
         "columns": [{"key": "at", "label": "at", "align": "left"},
                     *[{"key": f"p{i}", "label": f"p{i}", "align": "right"} for i in range(len(sturm))],
                     {"key": "v", "label": "changes", "align": "right"}],
         "rows": [{"at": "−∞", **{f"p{i}": sign(s) for i, s in enumerate(facts.get("signs_minus_inf") or [])},
                   "v": str(sum(1 for a, b in zip(facts["signs_minus_inf"], facts["signs_minus_inf"][1:], strict=False) if a * b < 0))},
                  {"at": "+∞", **{f"p{i}": sign(s) for i, s in enumerate(facts.get("signs_plus_inf") or [])},
                   "v": str(sum(1 for a, b in zip(facts["signs_plus_inf"], facts["signs_plus_inf"][1:], strict=False) if a * b < 0))}]},
    ]
    curve = facts.get("curve") or {}
    if curve.get("t"):
        blocks.append({
            "type": "chart", "title": f"{facts.get('name')}({facts.get('variable')}) with its real roots",
            "x": {"label": str(facts.get("variable")), "unit": ""}, "y": {"label": str(facts.get("name")), "unit": ""},
            "series": [{"name": str(facts.get("polynomial_latex", "")).split(" = ")[0] or "p",
                        "points": [[t, y] for t, y in zip(curve["t"], curve["y"], strict=False)]}],
            "marks": [[r, 0.0, f"r{i + 1}"] for i, r in enumerate(curve.get("roots") or [])],
        })
    blocks.append({
        "type": "table", "title": f"Certified isolating intervals (width ≤ {facts.get('width')})",
        "columns": [{"key": "r", "label": f"root ({facts.get('digits')} digits)", "align": "right"},
                    {"key": "i", "label": "rational interval", "align": "left"},
                    {"key": "s", "label": "sign of p at ends", "align": "left"},
                    {"key": "res", "label": "exact residual", "align": "right"}],
        "rows": [{"r": r["root"], "i": f"[{r['a']}, {r['b']}]", "s": f"{sign(r['sign_a'])} / {sign(r['sign_b'])}",
                  "res": r["residual"]} for r in facts.get("roots") or []],
    })
    blocks.append({"type": "checks", "title": "Independent checks",
                   "caption": "Run in Python: " + ", ".join(facts.get("methods") or []),
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": blocks}


def _poly_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """A stated polynomial analysed in Python (tribos.writer.poly_facts): what the code found, the polynomial, a
    slice through the minimisers, the exact checks, the half Newton polytope and the sum-of-squares certificate."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    if not params or not checks:
        return None
    blocks: list[dict[str, Any]] = [
        {"type": "stats", "title": "Python outputs",
         "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": "", "exact_latex": "",
                    "verified": True} for p in params][:MAX_ITEMS]},
        {"type": "equation", "title": "Polynomial", "latex": str(facts.get("polynomial_latex") or ""), "parts": [],
         "checks": []},
    ]
    sl = facts.get("slice") or {}
    if sl.get("t"):
        blocks.append({
            "type": "chart", "title": f"Values along the diagonal, {sl.get('label')}",
            "x": {"label": "t", "unit": ""}, "y": {"label": str(sl.get("label")), "unit": ""},
            "series": [{"name": str(sl.get("label")), "points": [[t, v] for t, v in zip(sl["t"], sl["diagonal"], strict=False)]}],
            "marks": [[1.0, 0.0, "t = 1"], [-1.0, 0.0, "t = -1"]] if facts.get("minimisers") else [],
        })
    mins = facts.get("minimisers") or []
    if mins:
        blocks.append({
            "type": "table", "title": "Minimisers, checked exactly (SymPy)",
            "columns": [{"key": "p", "label": "point", "align": "left"}, {"key": "v", "label": "exact value", "align": "right"},
                        {"key": "g", "label": "gradient zero", "align": "left"}],
            "rows": [{"p": m["point"], "v": m["value"], "g": "yes" if m["gradient_zero"] else "no"} for m in mins],
        })
    half = facts.get("half_polytope") or []
    if half:
        blocks.append({
            "type": "table", "title": "Half Newton polytope: monomials a square root can use",
            "columns": [{"key": "e", "label": "exponent", "align": "left"}, {"key": "m", "label": "monomial", "align": "left"}],
            "rows": [{"e": str(tuple(e)), "m": " ".join(f"{v}^{k}" if k > 1 else v for v, k in
                                                          zip(facts.get("variables") or [], e, strict=False) if k) or "1"}
                     for e in half],
        })
    decomposition = facts.get("sos_decomposition")
    if decomposition:
        blocks.append({"type": "equation", "title": "Exact sum-of-squares certificate (checked symbolically)",
                       "latex": f"{facts.get('name')} = {decomposition['latex']}", "parts": [], "checks": []})
    cert = facts.get("certificate")
    blocks.append({"type": "callout", "tone": "ok" if (cert or decomposition) else "info",
                   "title": ("Not a sum of squares: certificate" if cert else "A sum of squares: exact certificate"
                             if decomposition else "Sampling is evidence, not proof"),
                   "text": " ".join(facts.get("notes") or [])[:1000]})
    blocks.append({"type": "checks", "title": "Independent checks",
                   "caption": "Run in Python: " + ", ".join(facts.get("methods") or []),
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    return {"version": SPEC_VERSION, "title": "Results at a glance", "source": "computed", "blocks": blocks}


def _nbody_ui(facts: dict[str, Any]) -> dict[str, Any] | None:
    """A gravitational N-body integration (tribos.writer.nbody_facts): the measured drifts, the equations of motion,
    the orbits in the plane, the energy error of each method over time, the effect of the rounded initial
    conditions, the return error after each period and the checks."""
    params = [p for p in facts.get("parameters") or [] if isinstance(p, dict)]
    checks = [c for c in facts.get("checks") or [] if isinstance(c, dict)]
    if not params or not checks:
        return None
    blocks: list[dict[str, Any]] = [{
        "type": "stats", "title": "Measured over the run",
        "items": [{"label": str(p["name"])[:80], "value": str(p["value"]), "unit": str(p.get("unit") or ""),
                   "exact_latex": "", "verified": True} for p in params][:MAX_ITEMS],
    }, {
        "type": "equation", "title": "Equations of motion", "latex": str(facts.get("equation_latex") or ""),
        "parts": [], "checks": [],
    }]
    paths = facts.get("trajectories") or []
    if paths and all(len(p) >= 3 for p in paths):
        blocks.append({
            "type": "chart", "title": "Orbits in the plane (DOP853, rtol 1e-13)", "parametric": True,
            "x": {"label": "x", "unit": ""}, "y": {"label": "y", "unit": ""},
            "series": [{"name": f"body {i + 1}", "points": p} for i, p in enumerate(paths)],
            "marks": [[p[0][0], p[0][1], f"start {i + 1}"] for i, p in enumerate(paths)],
        })
    energy = facts.get("energy_error") or {}
    if energy.get("t"):
        blocks.append({
            "type": "chart", "title": "Relative energy error |E - E0| / |E0|",
            "x": {"label": "t", "unit": ""}, "y": {"label": "|ΔE/E0|", "unit": "", "scale": "log"},
            "series": [{"name": name, "points": [[t, v] for t, v in zip(energy["t"], values, strict=False)]}
                       for name, values in energy.items() if name != "t"],
            "marks": [],
        })
    div = facts.get("divergence") or {}
    if div.get("t") and any(v > 1e-16 for v in div.get("values") or []):
        blocks.append({
            "type": "chart", "title": "Deviation caused by rounding the initial conditions",
            "x": {"label": "t", "unit": ""}, "y": {"label": "max |Δr|", "unit": "", "scale": "log"},
            "series": [{"name": "rounded vs perturbed start", "points": [[t, v] for t, v in zip(div["t"], div["values"], strict=False)]}],
            "marks": [],
        })
    returns = facts.get("returns") or []
    if returns:
        blocks.append({
            "type": "table", "title": "Return to the starting configuration after each period",
            "columns": [{"key": "k", "label": "period", "align": "right"},
                        {"key": "t", "label": "t", "align": "right"},
                        {"key": "pos", "label": "max |r(t) - r(0)|", "align": "right"},
                        {"key": "vel", "label": "max |v(t) - v(0)|", "align": "right"},
                        {"key": "e", "label": "|ΔE/E0|", "align": "right"}],
            "rows": [{"k": str(r["period"]), "t": f"{r['t']:.8g}", "pos": f"{r['position_error']:.3e}",
                      "vel": f"{r['velocity_error']:.3e}", "e": f"{r['rel_energy_error']:.2e}"} for r in returns],
        })
    if facts.get("notes"):
        blocks.append({"type": "callout", "tone": "insight", "title": "What sets the return error",
                       "text": " ".join(facts["notes"])[:1000]})
    blocks.append({"type": "checks", "title": "Independent checks",
                   "caption": "Two tolerances of an adaptive 8th-order Runge-Kutta method and a 4th-order symplectic "
                              "integrator, with energy, angular momentum and centre of mass tracked throughout",
                   "items": [{"name": str(c["name"]), "passed": bool(c.get("passed")), "detail": ""} for c in checks]})
    return {"version": SPEC_VERSION, "title": "Simulation results", "source": "computed", "blocks": blocks}


def _analysis_blocks(facts: dict[str, Any], t_unit: str, x_unit: str) -> list[dict[str, Any]]:
    """Independent verification (physics consistency, convergence study) and the response characteristics."""
    physics = facts.get("physics") or {}
    conv = facts.get("convergence") or {}
    blocks: list[dict[str, Any]] = []
    items = [{"name": str(c.get("name")), "passed": bool(c.get("passed")), "detail": str(c.get("detail") or "")}
             for c in [*(physics.get("checks") or []), *(conv.get("checks") or [])] if isinstance(c, dict)]
    if items:
        blocks.append({"type": "checks", "title": "Independent checks",
                       "caption": "Physics consistency (energy balance, stability, limiting cases) and a convergence "
                                  "study of the numerical solution", "items": items})

    resp = facts.get("frequency_response") or {}
    if resp.get("omega") and resp.get("amplitude"):
        rate = resp.get("unit_rate") or ""
        blocks.append({
            "type": "chart",
            "title": "Frequency response: steady-state amplitude against forcing frequency",
            "x": {"label": "ω", "unit": rate},
            "y": {"label": "X", "unit": resp.get("unit_amplitude") or x_unit},
            "series": [{"name": "amplitude X(ω)", "points": list(zip(resp["omega"], resp["amplitude"], strict=False))}],
            "marks": [list(m) for m in resp.get("marks") or []],
        })

    quantities = [q for q in physics.get("quantities") or [] if isinstance(q, dict)]
    if quantities:
        blocks.append({"type": "stats", "title": "Response characteristics",
                       "items": [{**_stat(q), "verified": True} for q in quantities][:MAX_ITEMS]})

    runs = [r for r in conv.get("runs") or [] if isinstance(r, dict)]
    if runs and all("max_error" in r for r in runs):
        pts = [[float(r["step"]), float(r["max_error"])] for r in runs]
        h_f, e_f = pts[-1]
        ref = [[h, e_f * (h / h_f) ** 4] for h, _ in pts]
        blocks.append({
            "type": "chart",
            "title": f"Convergence: maximum error against step (observed order {conv.get('observed_order')})",
            "x": {"label": "step h", "unit": t_unit, "scale": "log"},
            "y": {"label": "max |error|", "unit": x_unit, "scale": "log"},
            "series": [{"name": "RK4 error", "points": pts},
                       {"name": "slope 4 reference", "points": ref, "style": "dashed"}],
            "marks": [],
        })
    if runs:
        rich = conv.get("richardson_at_final_time") or {}
        caption = f"Richardson at {facts.get('independent', 't')} = {rich.get('time')}: {rich.get('status')}"
        if rich.get("gci_fine"):
            caption += f"; GCI (fine) {rich['gci_fine']}"
        if conv.get("predicted_error_at_requested_step"):
            caption += f"; predicted error at the requested step {conv['predicted_error_at_requested_step']}"
        has_err = all("max_error" in r for r in runs)
        blocks.append({
            "type": "table",
            "title": "Convergence study (RK4, halved steps)",
            "columns": [{"key": "step", "label": "step h", "unit": t_unit, "align": "right"},
                        {"key": "steps", "label": "steps", "align": "right"},
                        {"key": "final_value", "label": f"{facts.get('dependent', 'x')} at end", "unit": x_unit,
                         "align": "right"},
                        *([{"key": "max_error", "label": "max |error|", "unit": x_unit, "align": "right"}] if has_err else [])],
            "rows": [{k: str(r.get(k, "")) for k in ("step", "steps", "final_value", "max_error")} for r in runs],
            "caption": caption,
        })
    return blocks


# Writer blocks ---------------------------------------------------------------------------------------------------
def _text(value: Any, limit: int = MAX_TEXT) -> str | None:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) and str(value).strip() else None


def validate_ui_block(block: Any) -> dict[str, Any] | None:
    """A writer-emitted block reduced to the allowed shape, or None when it is not a valid block."""
    if not isinstance(block, dict) or block.get("type") not in WRITER_BLOCK_TYPES:
        return None
    kind = block["type"]
    title = _text(block.get("title"), 120)
    if kind == "callout":
        text = _text(block.get("text"))
        if not text:
            return None
        tone = block.get("tone") if block.get("tone") in CALLOUT_TONES else "info"
        return {"type": "callout", "tone": tone, "title": title, "text": text}
    if kind == "stats":
        items = []
        for it in (block.get("items") or [])[:MAX_ITEMS]:
            if isinstance(it, dict) and _text(it.get("label"), 80) and _text(it.get("value"), 60):
                items.append({"label": _text(it["label"], 80), "value": _text(it["value"], 60),
                              "unit": _text(it.get("unit"), 30) or "", "note": _text(it.get("note"), 160) or ""})
        return {"type": "stats", "title": title, "items": items} if items else None
    if kind == "steps":
        items = []
        for it in (block.get("items") or [])[:MAX_ITEMS]:
            if isinstance(it, dict) and (_text(it.get("title"), 160) or _text(it.get("latex"), 400)):
                items.append({"title": _text(it.get("title"), 160) or "", "latex": _text(it.get("latex"), 400) or "",
                              "note": _text(it.get("note"), 300) or ""})
        return {"type": "steps", "title": title, "items": items} if items else None
    if kind == "table":
        cols = [c for c in (block.get("columns") or [])[:8] if _text(c, 60)]
        rows = []
        for r in (block.get("rows") or [])[:40]:
            if isinstance(r, list) and len(r) == len(cols):
                rows.append([_text(c, 80) or "" for c in r])
        if not cols or not rows:
            return None
        return {"type": "table", "title": title, "columns": [str(c)[:60] for c in cols], "rows": rows}
    if kind == "equation":
        latex = _text(block.get("latex"), 600)
        if not latex:
            return None
        parts = [{"label": _text(p.get("label"), 80) or "", "latex": _text(p.get("latex"), 400) or ""}
                 for p in (block.get("parts") or [])[:MAX_ITEMS] if isinstance(p, dict) and _text(p.get("latex"), 400)]
        # A writer cannot claim checks: only computed results carry passed checks.
        return {"type": "equation", "title": title, "latex": latex, "parts": parts, "checks": []}
    if kind == "chart":
        def axis(a: Any) -> dict[str, str]:
            a = a if isinstance(a, dict) else {}
            return {"label": _text(a.get("label"), 60) or "", "unit": _text(a.get("unit"), 30) or ""}

        series = []
        for s in (block.get("series") or [])[:MAX_CHART_SERIES]:
            if not isinstance(s, dict):
                continue
            pts = []
            for pt in (s.get("points") or [])[:MAX_CHART_POINTS]:
                if isinstance(pt, (list, tuple)) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt):
                    pts.append([float(pt[0]), float(pt[1])])
            if len(pts) >= 2:
                series.append({"name": _text(s.get("name"), 60) or "series", "points": pts})
        if not series:
            return None
        return {"type": "chart", "title": title, "x": axis(block.get("x")), "y": axis(block.get("y")),
                "series": series, "marks": []}
    return None


def ui_block_text(block: dict[str, Any]) -> str:
    """Every string of a block, for the number check against the evidence."""
    return json.dumps(block, ensure_ascii=False)


def _panel_repeats(block: dict[str, Any], panel: dict[str, Any] | None) -> str | None:
    """Why a writer block only repeats the results panel shown above the answer (its stats, its caution), else None.
    The reader saw the same values a screen earlier; a second card of them is length without information."""
    if not panel:
        return None
    blocks = [b for b in panel.get("blocks") or [] if isinstance(b, dict)]
    if block["type"] == "callout" and any(b.get("type") == "callout" for b in blocks):
        return "a callout repeated the results panel's note"
    if block["type"] == "stats":
        shown = {_digits(str(it.get("value"))) for b in blocks if b.get("type") == "stats" for it in b.get("items") or []}
        values = [_digits(str(it.get("value"))) for it in block.get("items") or []]
        if values and all(v and v in shown for v in values):
            return "a stats block repeated values the results panel shows"
    return None


def _digits(value: str) -> str:
    return re.sub(r"[^\d.\-]", "", value.replace(",", ""))


def sanitize_ui_blocks(answer: str, evidence_text: str, panel: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """The answer with each ```ui block normalised (valid JSON of an allowed type whose numbers are all in the
    answer's prose or the evidence) or removed; the reasons for each removal. With `panel` (the results panel shown
    above the answer), a block that only repeats it is removed too."""
    from .editor import unexplained_numbers

    removed: list[str] = []
    prose = _UI_FENCE_RE.sub(" ", answer or "")

    def repl(m: re.Match[str]) -> str:
        try:
            block = validate_ui_block(json.loads(m.group(1)))
        except (ValueError, TypeError):
            removed.append("a ui block was not valid JSON")
            return ""
        if block is None:
            removed.append("a ui block had an unsupported type or shape")
            return ""
        extra = unexplained_numbers(ui_block_text(block), prose, evidence_text)
        if extra:
            removed.append(f"a {block['type']} block carried numbers not in the evidence: {', '.join(extra[:4])}")
            return ""
        repeat = _panel_repeats(block, panel)
        if repeat:
            removed.append(repeat)
            return ""
        return "```ui\n" + json.dumps(block, ensure_ascii=False) + "\n```"

    return _UI_FENCE_RE.sub(repl, answer or ""), removed


__all__ = ["SPEC_VERSION", "build_answer_ui", "sanitize_ui_blocks", "validate_ui_block"]
