"""Evidence XML for the STEM computation tools (Dynamis, Physis, Calcula, Axiom) in the synthesis prompt.

Every successful computation reaches the synthesis model as data it can quote: the values a tool computed, how it
computed them and what it checked (SUP-9). Long arrays are decimated and numbers rounded to six significant
figures, so a 4,000-point trajectory costs a few hundred tokens. Every value is XML-escaped (ORC-010).
"""

from __future__ import annotations

import json
import math
from html import escape
from typing import Any

from .result_keys import (
    AXIOM,
    CALCULA,
    DYNAMIS,
    DYNAMIS_EQUILIBRIUM,
    DYNAMIS_PDE,
    DYNAMIS_SCAN,
    PHYSIS,
    STEM_RESULT_KEYS,
)

TRAJECTORY_SAMPLES = 21  # rows of a time course shown, first and last included
SCAN_ROWS = 25  # rows of a parameter scan shown
LIST_ITEMS = 10  # constants, materials, sequences or entries shown
TEXT_CHARS = 1500  # stdout, Wolfram text, encyclopedia extracts


def _attr(value: Any) -> str:
    return escape(str(value), quote=True)


def _text(value: Any, limit: int = TEXT_CHARS) -> str:
    s = str(value if value is not None else "")
    return escape(s if len(s) <= limit else s[:limit].rstrip() + " [...]", quote=False)


def num(value: Any) -> Any:
    """A number rounded to six significant figures (ints and non-numbers unchanged)."""
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if not math.isfinite(value):
        return str(value)
    return float(f"{value:.6g}")


def _rounded(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return num(value)


def _json(value: Any) -> str:
    return escape(json.dumps(_rounded(value), default=str), quote=False)


def decimate(n: int, k: int) -> list[int]:
    """At most k indices of 0..n-1, evenly spaced, the first and the last always included."""
    if n <= k:
        return list(range(n))
    if k <= 1:
        return [n - 1]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def _data(res: Any) -> dict[str, Any]:
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else {}


def _ok(res: Any) -> bool:
    return res is not None and bool(getattr(res, "success", False)) and bool(_data(res))


# -- Dynamis ----------------------------------------------------------------------------------------------------
def render_calibration(res: Any) -> list[str]:
    d = _data(res)
    fields = {k: d[k] for k in ("parameter_estimates", "confidence_intervals", "correlation_matrix", "correlation_labels",
                               "metrics", "objective", "warnings", "converged", "ci_method") if k in d}
    if not fields:
        return []
    return [f'<model_calibration tool="{_attr(getattr(res, "tool_name", ""))}" verified="false">',
            _json(fields), "</model_calibration>"]


def _dynamis_time_course(tool: str, d: dict[str, Any]) -> list[str]:
    states = [str(s) for s in (d.get("state_variables") or list((d.get("trajectories") or {}).keys())
                               or list((d.get("summary") or {}).keys()))]
    t_span = d.get("t_span") or (d.get("solver") or {}).get("t_span") or []
    times = d.get("t") or []
    trajectories = d.get("trajectories") or {}
    summary = d.get("summary") or {}
    extrema = d.get("extrema") or {}
    model = d.get("model_name") or d.get("model_id") or "stated ODE system"
    head = (
        f'<dynamis tool="{_attr(tool)}" model="{_attr(model)}" method="{_attr(d.get("method") or "")}"'
        + (f' t_start="{_attr(num(float(t_span[0])))}" t_end="{_attr(num(float(t_span[1])))}"' if len(t_span) == 2 else "")
        + (f' output_samples="{len(times)}"' if times else "")
        + f' verified="{_attr(str(bool(d.get("verified"))).lower())}">'
    )
    out = [head]
    if states:
        out.append(f"<state_variables>{escape(', '.join(states), quote=False)}</state_variables>")
    if d.get("parameters"):
        out.append(f"<parameters>{_json(d['parameters'])}</parameters>")
    if isinstance(d.get("units"), dict) and d["units"]:
        out.append(f"<units>{_json(d['units'])}</units>")
    initial = {s: v.get("initial") for s, v in summary.items() if isinstance(v, dict) and "initial" in v}
    final = {s: v.get("final") for s, v in summary.items() if isinstance(v, dict) and "final" in v}
    if initial:
        out.append(f"<initial_state>{_json(initial)}</initial_state>")
    if final:
        at = f' at_time="{_attr(num(float(t_span[1])))}"' if len(t_span) == 2 else ""
        out.append(f"<final_state{at}>{_json(final)}</final_state>")
    ranges: dict[str, dict[str, Any]] = {}
    for s, v in summary.items():
        if not isinstance(v, dict):
            continue
        e = extrema.get(s) if isinstance(extrema.get(s), dict) else {}
        ranges[s] = {
            "min": e.get("dense_min", v.get("min")), "t_min": e.get("t_dense_min", e.get("t_sampled_min")),
            "max": e.get("dense_max", v.get("max")), "t_max": e.get("t_dense_max", e.get("t_sampled_max")),
            "mean": v.get("mean"),
        }
        ranges[s] = {k: x for k, x in ranges[s].items() if x is not None}
    if any(ranges.values()):
        out.append(
            '<state_ranges note="min/max from the solver\'s dense output where available, mean over the output '
            f'samples">{_json(ranges)}</state_ranges>'
        )
    series = [trajectories.get(s) for s in states]
    if times and states and all(isinstance(x, list) and len(x) == len(times) for x in series):
        idx = decimate(len(times), TRAJECTORY_SAMPLES)
        rows = [[times[i], *(x[i] for x in series)] for i in idx]  # type: ignore[index]
        out.append(
            f'<trajectory_samples columns="{_attr(", ".join(["t", *states]))}" shown="{len(idx)}" of="{len(times)}">'
            f"{_json(rows)}</trajectory_samples>"
        )
    cons = d.get("conserved_check") or {}
    if isinstance(cons, dict) and cons.get("checked"):
        out.append(
            f'<conservation_check invariant="{_attr(cons.get("invariant"))}" initial="{_attr(num(cons.get("initial_value")))}" '
            f'final="{_attr(num(cons.get("final_value")))}" drift="{_attr(num(cons.get("drift")))}" '
            f'conserved="{_attr(str(bool(cons.get("conserved"))).lower())}"/>'
        )
    out.append("</dynamis>")
    return out


def _dynamis_equilibrium(tool: str, d: dict[str, Any]) -> list[str]:
    out = [
        f'<dynamis_equilibrium tool="{_attr(tool)}" stability="{_attr(d.get("stability") or "unknown")}" '
        f'converged="{_attr(str(bool(d.get("converged"))).lower())}" residual_norm="{_attr(num(d.get("residual_norm")))}">',
        f"<fixed_point>{_json(d.get('fixed_point') or {})}</fixed_point>",
    ]
    eig = [e.get("str") or e for e in (d.get("eigenvalues") or []) if e is not None]
    if eig:
        out.append(f"<eigenvalues>{_json(eig)}</eigenvalues>")
    if d.get("jacobian"):
        out.append(f"<jacobian>{_json(d['jacobian'])}</jacobian>")
    out.append("</dynamis_equilibrium>")
    return out


def _dynamis_scan(tool: str, d: dict[str, Any]) -> list[str]:
    rows = [r for r in (d.get("scan_results") or []) if isinstance(r, dict)]
    rng = d.get("scan_range") or []
    out = [
        f'<dynamis_scan tool="{_attr(tool)}" parameter="{_attr(d.get("parameter") or d.get("resolved_parameter") or "")}"'
        + (f' range="{_attr(num(rng[0]))} to {_attr(num(rng[1]))}"' if len(rng) == 2 else "")
        + f' points="{len(rows)}">'
    ]
    for i in decimate(len(rows), SCAN_ROWS):
        r = rows[i]
        value = r.get("parameter_value", r.get("applied_value"))
        fields = {k: r[k] for k in ("final_state", "peak_state", "min_state", "endpoint_species", "target_response") if k in r}
        out.append(f'<point value="{_attr(num(value))}">{_json(fields)}</point>')
    if len(rows) > SCAN_ROWS:
        out.append(f"<note>{len(rows) - len(decimate(len(rows), SCAN_ROWS))} intermediate points not shown.</note>")
    out.append("</dynamis_scan>")
    return out


def _dynamis_other(tool: str, d: dict[str, Any]) -> list[str]:
    """Fits, optimizations and root finds."""
    if "r_squared" in d or "std_errors" in d:
        return [
            f'<dynamis_fit tool="{_attr(tool)}" model="{_attr(d.get("model_expr"))}" r_squared="{_attr(num(d.get("r_squared")))}" '
            f'rmse="{_attr(num(d.get("rmse")))}">',
            f"<parameters>{_json(d.get('parameters') or {})}</parameters>",
            f"<standard_errors>{_json(d.get('std_errors') or {})}</standard_errors>",
            "</dynamis_fit>",
        ]
    if "optimal_point" in d:
        return [
            f'<dynamis_optimum tool="{_attr(tool)}" objective="{_attr(d.get("objective"))}" '
            f'goal="{"minimum" if d.get("minimize", True) else "maximum"}" value="{_attr(num(d.get("optimal_value")))}" '
            f'converged="{_attr(str(bool(d.get("converged"))).lower())}">{_json(d.get("optimal_point") or {})}</dynamis_optimum>'
        ]
    if "roots" in d:
        return [
            f'<dynamis_roots tool="{_attr(tool)}" residual_norm="{_attr(num(d.get("residual_norm")))}" '
            f'converged="{_attr(str(bool(d.get("converged"))).lower())}">{_json(d.get("roots") or {})}</dynamis_roots>'
        ]
    return []


def render_dynamis(res: Any) -> list[str]:
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "dynamis")
    if "parameter_estimates" in d:
        return render_calibration(res)
    if "fixed_point" in d:
        return _dynamis_equilibrium(tool, d)
    if "scan_results" in d:
        return _dynamis_scan(tool, d)
    if "snapshots" in d and "equation" in d and "convergence" in d:
        return render_pde(tool, d)
    if "trajectories" in d or "summary" in d or "state_variables" in d:
        return _dynamis_time_course(tool, d)
    return _dynamis_other(tool, d)


def render_pde(tool: str, d: dict[str, Any]) -> list[str]:
    """One solved PDE: the problem, the scheme and its stability number, the verification, and a decimated field.

    A 2D field of 80x80 values would cost thousands of tokens, so the final field is shown on a coarse sub-grid; the
    diagnostics that say whether it can be trusted (convergence, analytic error, conservation) are shown in full.
    """
    dimension = int(d.get("dimension") or 1)
    sub = lambda key: d.get(key) if isinstance(d.get(key), dict) else {}  # noqa: E731
    stability, convergence, verification, conservation = (
        sub("stability"), sub("convergence"), sub("verification"), sub("conservation"),
    )
    out = [
        f'<dynamis_pde tool="{_attr(tool)}" equation="{_attr(d.get("equation"))}" dimension="{dimension}" '
        f'method="{_attr(d.get("method") or "")}" steady="{str(bool(d.get("steady"))).lower()}">',
        f"<problem>{_json({k: d.get(k) for k in ('domain', 'parameters', 'boundary', 'boundary_values', 't_span')})}</problem>",
        f"<inputs>{_json({k: (d.get('spec') or {}).get(k) for k in ('initial_condition', 'initial_velocity', 'source')})}"
        "</inputs>",
        f"<grid>{_json(d.get('grid') or {})}</grid>",
    ]
    if stability:
        out.append(f"<stability>{_json(stability)}</stability>")
    for level in (convergence.get("levels") or [])[:6]:
        if isinstance(level, dict):
            out.append(f"<mesh_level>{_json(level)}</mesh_level>")
    out.append(
        f'<convergence observed_order="{_attr(num(convergence.get("order")))}" '
        f'expected_order="{_attr(convergence.get("expected_order"))}" '
        f'richardson_error="{_attr(num(convergence.get("richardson_error")))}" '
        f'converged="{str(bool(convergence.get("converged"))).lower()}" '
        f'reference="{_attr(convergence.get("reference") or "")}">{_text(convergence.get("note") or "", 400)}</convergence>'
    )
    if verification:
        out.append(
            f'<analytic_comparison exact_solution="{_attr(verification.get("exact_solution"))}" '
            f'max_error="{_attr(num(verification.get("max_error")))}" '
            f'relative_error="{_attr(num(verification.get("relative_error")))}" '
            f'agrees="{str(bool(verification.get("agrees"))).lower()}"/>'
        )
    else:
        out.append("<analytic_comparison>no analytic solution was given; none is claimed</analytic_comparison>")
    if conservation:
        out.append(
            f'<conservation_check quantity="{_attr(conservation.get("kind"))}" initial="{_attr(num(conservation.get("initial")))}" '
            f'final="{_attr(num(conservation.get("final")))}" relative_drift="{_attr(num(conservation.get("relative_drift")))}" '
            f'conserved="{str(bool(conservation.get("conserved"))).lower()}">{_text(conservation.get("note") or "", 300)}'
            "</conservation_check>"
        )
    xs, ys, field = d.get("x") or [], d.get("y") or [], d.get("field") or []
    if dimension == 1 and xs and len(field) == len(xs):
        idx = decimate(len(xs), TRAJECTORY_SAMPLES)
        out.append(
            f'<final_field t="{_attr(num((d.get("times") or [None])[-1]))}" columns="x, u" shown="{len(idx)}" '
            f'of="{len(xs)}">{_json([[xs[i], field[i]] for i in idx])}</final_field>'
        )
    elif dimension == 2 and xs and ys and field:
        xi, yi = decimate(len(xs), 9), decimate(len(ys), 9)
        out.append(
            f'<final_field t="{_attr(num((d.get("times") or [None])[-1]))}" layout="rows over x, columns over y" '
            f'x="{_attr(_json([xs[i] for i in xi]))}" y="{_attr(_json([ys[j] for j in yi]))}">'
            f"{_json([[field[i][j] for j in yi] for i in xi])}</final_field>"
        )
    if d.get("range"):
        out.append(f"<value_range>{_json(d['range'])}</value_range>")
    for probe in (d.get("probes") or [])[:6]:
        if isinstance(probe, dict):
            out.append(f"<probe>{_json(probe)}</probe>")
    for w in (d.get("warnings") or [])[:6]:
        out.append(f"<warning>{_text(w, 400)}</warning>")
    out.append("</dynamis_pde>")
    return out


def render_tool_result(res: Any) -> list[str] | None:
    """The dedicated evidence of a tool whose result has its own renderer, or None (then generic JSON is used).

    The agentic phases key their results by phase ('agent.<phase>.<n>.<tool>'), so they look the renderer up by
    the tool's name here instead of by the classic result key.
    """
    render = TOOL_RENDERERS.get(str(getattr(res, "tool_name", "") or ""))
    if render is None or not _ok(res):
        return None
    return render(res) or None


def endpoint_vs_equilibrium(sim: Any, eq: Any, tolerance: float = 0.05) -> str:
    """Whether the time course ended at the computed fixed point, so convergence to it is never assumed."""
    final = {s: v.get("final") for s, v in (_data(sim).get("summary") or {}).items() if isinstance(v, dict)}
    point = _data(eq).get("fixed_point") or {}
    diffs = []
    for s, end in final.items():
        target = point.get(s)
        if isinstance(end, (int, float)) and isinstance(target, (int, float)):
            diffs.append((abs(end - target) / max(abs(target), abs(end), 1e-9), s))
    if not diffs:
        return ""
    worst, worst_s = max(diffs)
    if worst <= tolerance:
        return (f"<endpoint_vs_equilibrium>The time course ends at this fixed point: every state variable is within "
                f"{tolerance:.0%} of it.</endpoint_vs_equilibrium>")
    return (
        f"<endpoint_vs_equilibrium>The time course has not reached this fixed point by its end ({escape(str(worst_s))} "
        f"differs by {worst:.0%}). Do not say the trajectory converges to it; it may be unstable, another equilibrium, "
        "or need a longer simulation.</endpoint_vs_equilibrium>"
    )


# -- Physis -----------------------------------------------------------------------------------------------------
def render_physis(res: Any) -> list[str]:
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "physis")
    out: list[str] = []
    if "constants" in d:
        out.append(f'<physis tool="{_attr(tool)}" query="{_attr(d.get("query") or "")}" matches="{_attr(d.get("count", len(d["constants"])))}">')
        for c in (d.get("constants") or [])[:LIST_ITEMS]:
            if isinstance(c, dict):
                out.append(
                    f'<constant name="{_attr(c.get("name"))}" symbol="{_attr(c.get("symbol") or "")}" '
                    f'value="{_attr(c.get("value"))}" uncertainty="{_attr(c.get("uncertainty"))}" '
                    f'unit="{_attr(c.get("unit") or "")}" source="{_attr(c.get("source") or "")}"/>'
                )
    elif "converted_value" in d or "equation_homogeneous" in d:
        out.append(f'<physis tool="{_attr(tool)}">')
        if d.get("input_unit"):
            out.append(
                f'<unit_conversion from="{_attr(d.get("input_value"))} {_attr(d.get("input_unit"))}" '
                f'to="{_attr(num(d.get("converted_value")))} {_attr(d.get("converted_unit"))}" '
                f'base_si="{_attr(num(d.get("base_si_value")))} {_attr(d.get("base_si_unit"))}" '
                f'dimensionality="{_attr(d.get("dimensionality") or "")}" compatible="{_attr(str(bool(d.get("compatible", True))).lower())}"/>'
            )
        check = d.get("equation_check") if isinstance(d.get("equation_check"), dict) else d
        if "equation_homogeneous" in check:
            out.append(
                f'<dimensional_check equation="{_attr(check.get("equation") or "")}" '
                f'homogeneous="{_attr(str(bool(check.get("equation_homogeneous"))).lower())}">'
                f"{_text(check.get('dimensionality') or '')}</dimensional_check>"
            )
        if d.get("error"):
            out.append(f"<error>{_text(d['error'], 300)}</error>")
    elif "materials" in d:
        out.append(f'<physis tool="{_attr(tool)}" source="{_attr(d.get("source") or "")}">')
        for m in (d.get("materials") or [])[:LIST_ITEMS]:
            if isinstance(m, dict):
                props = {k: v for k, v in m.items() if k not in ("elements", "source") and v not in (None, "", [])}
                out.append(f'<material id="{_attr(m.get("material_id") or "")}">{_json(props)}</material>')
        if d.get("note"):
            out.append(f"<note>{_text(d['note'], 300)}</note>")
    elif "sequences" in d:
        out.append(f'<physis tool="{_attr(tool)}" source="OEIS">')
        for s in (d.get("sequences") or [])[:LIST_ITEMS]:
            if isinstance(s, dict):
                out.append(f"<sequence>{_json(s)}</sequence>")
    elif "entries" in d:
        out.append(f'<physis tool="{_attr(tool)}" source="Wikipedia">')
        for e in (d.get("entries") or [])[:LIST_ITEMS]:
            if isinstance(e, dict):
                out.append(f'<entry title="{_attr(e.get("title") or e.get("key") or "")}">'
                           f"{_text(e.get('extract') or e.get('summary') or e.get('description') or '', 600)}</entry>")
    elif "result" in d and not d.get("skipped"):
        out.append(f'<physis tool="{_attr(tool)}" source="Wolfram|Alpha">')
        out.append(f"<result>{_text(d.get('result'))}</result>")
    elif "nominal_value" in d and "standard_uncertainty" in d:
        out.append(f'<physis tool="{_attr(tool)}" method="{_attr(d.get("method") or "both")}">')
        out.append(
            f'<uncertainty_result nominal_value="{_attr(num(d.get("nominal_value")))}" '
            f'standard_uncertainty="{_attr(num(d.get("standard_uncertainty")))}" '
            f'expanded_uncertainty="{_attr(num(d.get("expanded_uncertainty")))}" '
            f'coverage_factor="{_attr(num(d.get("coverage_factor") or 2.0))}" '
            f'unit="{_attr(d.get("unit") or "")}">{_text(d.get("formatted") or "", 120)}</uncertainty_result>'
        )
        for b in (d.get("budget") or [])[:LIST_ITEMS]:
            if isinstance(b, dict):
                out.append(
                    f'<uncertainty_contribution variable="{_attr(b.get("variable"))}" '
                    f'value="{_attr(num(b.get("value")))}" std_uncertainty="{_attr(num(b.get("std_uncertainty")))}" '
                    f'unit="{_attr(b.get("unit") or "")}" sensitivity="{_attr(num(b.get("sensitivity")))}" '
                    f'percentage="{_attr(num(b.get("percentage")))}"/>'
                )
        mc = d.get("monte_carlo")
        if isinstance(mc, dict) and mc.get("mean") is not None:
            out.append(
                f'<monte_carlo mean="{_attr(num(mc.get("mean")))}" std="{_attr(num(mc.get("std")))}" '
                f'skewness="{_attr(num(mc.get("skewness")))}" n_samples="{_attr(mc.get("n_samples") or 0)}"/>'
            )
        for w in (d.get("warnings") or [])[:5]:
            out.append(f"<warning>{_text(w, 300)}</warning>")
    else:
        return []
    out.append("</physis>")
    return out


# -- Calcula ----------------------------------------------------------------------------------------------------
def render_calcula(res: Any) -> list[str]:
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "calcula")
    out = [f'<calcula tool="{_attr(tool)}" status="{_attr(d.get("status") or "ok")}">']
    body = 0
    if d.get("result") is not None:
        out.append(f"<result>{_text(json.dumps(_rounded(d['result']), default=str))}</result>")
        body += 1
    stdout = d.get("stdout") or d.get("output")
    if stdout:
        out.append(f"<stdout>{_text(stdout)}</stdout>")
        body += 1
    for t in (d.get("tables") or [])[:3]:
        if isinstance(t, dict):
            out.append(
                f'<table name="{_attr(t.get("name"))}" rows="{_attr(t.get("n_rows"))}" columns="{_attr(", ".join(map(str, t.get("columns") or [])))}">'
                f"{_json((t.get('rows') or [])[:10])}</table>"
            )
            body += 1
    figures = [f.get("name") for f in (d.get("figures") or []) if isinstance(f, dict)]
    if figures:
        out.append(f'<figures count="{len(figures)}">{escape(", ".join(map(str, figures)), quote=False)}</figures>')
        body += 1
    if not body:
        return []
    out.append("</calcula>")
    return out


# -- Axiom ------------------------------------------------------------------------------------------------------
def render_axiom(res: Any) -> list[str]:
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "axiom")
    answer = d.get("answer") if isinstance(d.get("answer"), dict) else {}
    verification = d.get("verification") if isinstance(d.get("verification"), dict) else {}
    if answer:
        problem = d.get("problem") if isinstance(d.get("problem"), dict) else {}
        out = [
            f'<axiom tool="{_attr(tool)}" status="{_attr(d.get("status") or "")}" '
            f'verification_level="{_attr(verification.get("level", ""))}">',
            f'<problem kind="{_attr(problem.get("kind") or "")}">{_text(problem.get("expression") or problem.get("text") or "", 600)}</problem>',
            f'<answer latex="{_attr(answer.get("latex") or "")}">{_text(answer.get("text") or "", 1200)}</answer>',
        ]
        for c in (verification.get("checks") or [])[:8]:
            if isinstance(c, dict):
                out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 200)}</check>')
        for u in (d.get("uncertainty") or [])[:5]:
            out.append(f"<uncertainty>{_text(u, 300)}</uncertainty>")
        out.append("</axiom>")
        return out
    # A single symbolic tool (axiom_solve, axiom_dsolve, axiom_calculus, ...): its result fields.
    fields = {k: d[k] for k in ("solutions", "solution", "result", "rhs", "latex", "verified", "complete") if k in d}
    if not fields:
        return []
    return [f'<axiom tool="{_attr(tool)}">{_json(fields)}</axiom>']


_RENDERERS = {
    DYNAMIS: render_dynamis,
    DYNAMIS_EQUILIBRIUM: render_dynamis,
    DYNAMIS_SCAN: render_dynamis,
    DYNAMIS_PDE: render_dynamis,
    AXIOM: render_axiom,
    PHYSIS: render_physis,
    CALCULA: render_calcula,
}


# Tools rendered by their own renderer wherever their result appears (see render_tool_result).
TOOL_RENDERERS = {
    "dynamis_solve_pde": render_dynamis,
}


def stem_evidence(tool_results: dict[str, Any]) -> list[str]:
    """The evidence XML of every successful STEM computation result in tool_results, in STEM_RESULT_KEYS order."""
    out: list[str] = []
    seen: set[int] = set()
    for key in STEM_RESULT_KEYS:
        render, res = _RENDERERS[key], tool_results.get(key)
        if not _ok(res) or id(res) in seen:
            continue
        seen.add(id(res))
        out.extend(render(res))
        if key == DYNAMIS_EQUILIBRIUM and _ok(tool_results.get(DYNAMIS)):
            note = endpoint_vs_equilibrium(tool_results[DYNAMIS], res)
            if note:
                out.append(note)
    return out


__all__ = [
    "decimate",
    "endpoint_vs_equilibrium",
    "num",
    "render_axiom",
    "render_calcula",
    "render_dynamis",
    "render_pde",
    "render_physis",
    "render_tool_result",
    "stem_evidence",
]
