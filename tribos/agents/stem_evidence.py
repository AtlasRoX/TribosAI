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
    CHEMISTRY,
    CODEACT,
    COMPUTED_RESULTS,
    DYNAMIS,
    DYNAMIS_EQUILIBRIUM,
    DYNAMIS_MONTE_CARLO,
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
            *([f"<fit_issues>{escape('; '.join(map(str, d['issues'])), quote=False)}</fit_issues>"] if d.get("issues") else []),
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
    if "num_samples" in d and "estimate" in d and "standard_error" in d:
        fields = {k: d.get(k) for k in ("expression", "variable", "lower", "upper", "num_samples", "seed", "generator",
                  "estimate", "sample_std", "standard_error", "ddof", "reference", "standard_errors_from_reference",
                  "sample_sha256", "numpy_version", "accuracy_note")}
        return [f'<monte_carlo tool="{_attr(tool)}" status="executed" note="these are sampled numerical results, not an antiderivative or exact proof">{_json(fields)}</monte_carlo>']
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
def render_engineering_calc(res: Any) -> list[str]:
    """One engineering calculation: the reference, the inputs as used, the results, the checks and the warnings."""
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "physis_engineering_calc")
    ref = d.get("reference") or {}
    util = d.get("utilisation") or {}
    out = [
        f'<engineering_calc tool="{_attr(tool)}" calculator="{_attr(d.get("calculator"))}" '
        f'reference="{_attr(ref.get("source") or "")}" section="{_attr(ref.get("section") or "")}">'
    ]
    if d.get("material"):
        m = d["material"]
        out.append(f'<material id="{_attr(m.get("id"))}" source="{_attr(m.get("source"))}">{_text(m.get("note"), 300)}</material>')
    for i in (d.get("inputs") or [])[:30]:
        if isinstance(i, dict):
            value = i.get("value")
            shown = _json(value) if isinstance(value, list) else num(value)
            out.append(
                f'<input name="{_attr(i.get("name"))}" value="{_attr(shown)}" unit="{_attr(i.get("unit") or "")}" '
                f'source="{_attr(i.get("source") or "")}"/>'
            )
    for r in (d.get("results") or [])[:30]:
        if isinstance(r, dict):
            shown = (f' display="{_attr(num(r.get("display_value")))} {_attr(r.get("display_unit"))}"'
                     if r.get("display_unit") else "")
            unc = r.get("uncertainty") if isinstance(r.get("uncertainty"), dict) else None
            out.append(
                f'<result name="{_attr(r.get("name"))}" label="{_attr(r.get("label"))}" value="{_attr(num(r.get("value")))}" '
                f'unit="{_attr(r.get("unit"))}"{shown}'
                + (f' with_uncertainty="{_attr(unc.get("formatted"))}"' if unc else "") + "/>"
            )
    for c in (d.get("checks") or [])[:10]:
        if isinstance(c, dict):
            out.append(f'<check name="{_attr(c.get("name"))}" ok="{str(bool(c.get("ok"))).lower()}" '
                       f'utilisation="{_attr(num(c.get("utilisation")))}">{_text(c.get("detail"), 300)}</check>')
    if util:
        out.append(f'<utilisation governing="{_attr(util.get("governing"))}" value="{_attr(num(util.get("value")))}" '
                   f'all_checks_ok="{str(bool(util.get("ok"))).lower()}"/>')
    for v in (d.get("validity") or [])[:10]:
        if isinstance(v, dict):
            out.append(f'<validity name="{_attr(v.get("name"))}" ok="{str(bool(v.get("ok"))).lower()}">'
                       f"{_text(v.get('detail'), 300)}</validity>")
    for f in (d.get("formulas") or [])[:12]:
        out.append(f"<formula>{_text(f, 200)}</formula>")
    for a in (d.get("assumptions") or [])[:6]:
        out.append(f"<assumption>{_text(a, 200)}</assumption>")
    for w in (d.get("warnings") or [])[:8]:
        out.append(f"<warning>{_text(w, 400)}</warning>")
    for n in (d.get("notes") or [])[:6]:
        out.append(f"<note>{_text(n, 400)}</note>")
    out.append("</engineering_calc>")
    return out


def render_calculator_list(res: Any) -> list[str]:
    """The calculator catalog: each calculator's inputs (name, unit, required) and reference, and the materials."""
    d = _data(res)
    out = ['<engineering_calculators note="call physis_engineering_calc with one of these">']
    for c in d.get("calculators") or []:
        if not isinstance(c, dict):
            continue
        inputs = "; ".join(
            f"{i.get('name')} [{i.get('unit') or 'choice'}]{'*' if i.get('required') else ''}"
            + (f" in {'/'.join(i['choices'])}" if i.get("choices") else "")
            for i in c.get("inputs") or [] if isinstance(i, dict)
        )
        out.append(f'<calculator id="{_attr(c.get("id"))}" title="{_attr(c.get("title"))}" '
                   f'reference="{_attr((c.get("reference") or {}).get("source"))}">{_text(inputs, 900)}</calculator>')
    mats = ", ".join(str(m.get("id")) for m in d.get("materials") or [] if isinstance(m, dict))
    out.append(f"<materials note=\"{_attr(d.get('materials_note') or '')}\">{_text(mats)}</materials>")
    out.append("</engineering_calculators>")
    return out


def render_paper(res: Any) -> list[str]:
    """An uploaded paper as read (metadata, equations, parameters) or as reproduced (one row per stated result)."""
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "archivon_read_paper")
    paper = d.get("paper") if isinstance(d.get("paper"), dict) else d
    out = [
        f'<uploaded_paper tool="{_attr(tool)}" dataset_id="{_attr(paper.get("dataset_id"))}" '
        f'title="{_attr(paper.get("title") or "")}" doi="{_attr(paper.get("doi") or "")}" '
        f'arxiv="{_attr(paper.get("arxiv_id") or "")}" pages="{_attr(paper.get("n_pages"))}" '
        'note="extracted from the uploaded PDF; cite claims by page, and report each reproduction status exactly">'
    ]
    for c in (d.get("claims") or [])[:30]:
        if not isinstance(c, dict):
            continue
        if "status" in c:
            out.append(
                f'<reproduction name="{_attr(c.get("name"))}" status="{_attr(c.get("status"))}" '
                f'stated="{_attr(num(c.get("stated")))} {_attr(c.get("unit") or "")}" '
                f'computed_si="{_attr(num(c.get("computed")))}" relative_difference="{_attr(num(c.get("relative_difference")))}" '
                f'missing="{_attr(", ".join(c.get("missing") or []))}" page="{_attr(c.get("page"))}">'
                f"{_text(c.get('equation') or c.get('reason') or '', 300)}</reproduction>"
            )
        else:
            out.append(f'<stated_result name="{_attr(c.get("name"))}" value="{_attr(num(c.get("value")))}" '
                       f'unit="{_attr(c.get("unit") or "")}" page="{_attr(c.get("page"))}">{_text(c.get("line"), 300)}'
                       "</stated_result>")
    for e in [*(d.get("odes") or []), *(d.get("equations") or [])][:30]:
        if isinstance(e, dict):
            lhs = f"d{e['state']}/dt" if e.get("state") else e.get("lhs")
            line = f"{lhs} = {e.get('rhs')}"
            out.append(f'<equation number="{_attr(e.get("number") or "")}" page="{_attr(e.get("page"))}">'
                       f"{_text(line, 300)}</equation>")
    for p in (d.get("parameters") or [])[:40]:
        if isinstance(p, dict):
            out.append(f'<parameter name="{_attr(p.get("name"))}" value="{_attr(p.get("as_written") or num(p.get("value")))}" '
                       f'page="{_attr(p.get("page"))}"/>')
    for s in (d.get("sections") or [])[:20]:
        if isinstance(s, dict):
            out.append(f'<section page="{_attr(s.get("page"))}">{_text(s.get("title"), 100)}</section>')
    for p in (d.get("text") or [])[:6]:
        if isinstance(p, dict) and p.get("text"):
            out.append(f'<page_text page="{_attr(p.get("page"))}">{_text(p.get("text"), 1200)}</page_text>')
    for n in (d.get("notes") or [])[:4]:
        out.append(f"<note>{_text(n, 300)}</note>")
    out.append("</uploaded_paper>")
    return out


def render_formal_check(res: Any) -> list[str]:
    """A Lean 4 check: its status, the statement Lean checked, and the first error."""
    from tribos.agentic.formal_proof import evidence_xml

    return [evidence_xml(_data(res))]


def render_physis(res: Any) -> list[str]:
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "physis")
    out: list[str] = []
    if "calculator" in d and "results" in d:
        return render_engineering_calc(res)
    if "calculators" in d:
        return render_calculator_list(res)
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
    if d.get("validation") is not None:
        val = d["validation"]
        v_passed = str(val.get("passed", "")).lower()
        v_checks = val.get("checks") or []
        out.append(f'<validation passed="{_attr(v_passed)}">{_text(json.dumps(v_checks, default=str))}</validation>')
        body += 1
    if d.get("reproducibility_bundle") is not None:
        bundle = d["reproducibility_bundle"]
        if isinstance(bundle, dict):
            out.append(
                f'<reproducibility_bundle filename="{_attr(bundle.get("filename"))}" '
                f'sha256="{_attr(bundle.get("sha256"))}" />'
            )
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


def _render_number_facts(d: dict[str, Any]) -> list[str]:
    """Finite number-theory results (tribos.writer.number_facts), each computed twice by different methods."""
    out = ['<computed_results note="finite computations run by code for this question and verified a second way; '
           'use them as given and say they were computed; they are instances, not proofs: write that a range was '
           'verified, never that it was proved">']
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}" unit="{_attr(p.get("unit"))}"/>')
    for part in d.get("partitions") or []:
        pairs = ", ".join(f"{a}+{b}" for a, b in part.get("pairs") or [])
        out.append(f'<goldbach_partitions n="{_attr(part.get("n"))}">{_text(pairs, 1500)}</goldbach_partitions>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 240)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 700)}</note>")
    out.append("</computed_results>")
    return out


def _render_nbody_facts(d: dict[str, Any]) -> list[str]:
    """A gravitational N-body integration (tribos.writer.nbody_facts): equations, methods, measured drifts."""
    out = ['<computed_results note="this N-body system was integrated by code for this question with the methods '
           'listed; report these measured values as the simulation results, say which method gave each, and do not '
           'invent trajectories or values that are not here">',
           f"<equations_of_motion>{_text(d.get('equation_latex'), 400)}</equations_of_motion>",
           f'<setup bodies="{_attr(d.get("n_bodies"))}" G="{_attr(d.get("G"))}" masses="{_attr(d.get("masses"))}" '
           f'period="{_attr(d.get("period"))}" periods="{_attr(d.get("n_periods"))}" t_end="{_attr(d.get("t_end"))}"/>']
    for meth in d.get("methods") or []:
        tol = f' rtol="{meth["rtol"]}" atol="{meth["atol"]}"' if meth.get("rtol") else ""
        out.append(f'<method name="{_attr(meth.get("name"))}"{tol}/>')
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    for r in d.get("returns") or []:
        out.append(f'<return_after_period k="{r["period"]}" t="{r["t"]:.8g}" position_error="{r["position_error"]:.3e}" '
                   f'velocity_error="{r["velocity_error"]:.3e}" relative_energy_error="{r["rel_energy_error"]:.3e}"/>')
    for i, pos in enumerate(d.get("final_positions") or [], start=1):
        out.append(f'<final_position body="{i}" t="{_attr(d.get("t_end"))}">({", ".join(pos)})</final_position>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 240)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 900)}</note>")
    out.append("</computed_results>")
    return out


def _render_poly_facts(d: dict[str, Any]) -> list[str]:
    """A stated polynomial analysed in Python (tribos.writer.poly_facts): sampling, minimisation, exact checks and the
    Newton-polytope test, each with the library that ran it."""
    out = ['<computed_results note="Python code ran for this question (NumPy, SciPy, SymPy) and these are its outputs; '
           'report them as the code\'s outputs, naming the method of each. Sampling and minimisation are evidence for '
           'nonnegativity, not a proof; the Newton-polytope certificate, when present, is a proof">',
           f"<polynomial>{_text(d.get('polynomial_latex'), 400)}</polynomial>"]
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    if d.get("sos_decomposition"):
        out.append("<sos_decomposition exact=\"true\">" + _text(d["sos_decomposition"].get("latex"), 2000)
                   + "</sos_decomposition>")
    for m in d.get("minimisers") or []:
        out.append(f'<minimiser point="{_attr(m.get("point"))}" exact_value="{_attr(m.get("value"))}" '
                   f'gradient_zero="{_attr(str(bool(m.get("gradient_zero"))).lower())}"/>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 600)}</note>")
    out.append("</computed_results>")
    return out


def _render_roots_facts(d: dict[str, Any]) -> list[str]:
    """Real roots of a polynomial isolated in Python (tribos.writer.roots_facts): the exact Sturm count, the rational
    intervals with their endpoint signs, the decimals and their exact residuals."""
    out = ['<computed_results note="Python code ran for this question (SymPy exact rational arithmetic, mpmath) and '
           'these are its outputs; report them as the code\'s outputs. The Sturm count and the endpoint signs are exact '
           'and prove the count and the isolation">',
           f"<polynomial>{_text(d.get('polynomial_latex'), 400)}</polynomial>",
           "<sturm_sequence>" + " ; ".join(_text(s, 200) for s in d.get("sturm_latex") or []) + "</sturm_sequence>",
           f'<sign_changes at_minus_infinity="{_attr(d.get("signs_minus_inf"))}" '
           f'at_plus_infinity="{_attr(d.get("signs_plus_inf"))}" real_roots="{_attr(d.get("count"))}"/>']
    for r in d.get("roots") or []:
        out.append(f'<root value="{_attr(r["root"])}" interval="[{_attr(r["a"])}, {_attr(r["b"])}]" '
                   f'interval_decimal="[{_attr(r["a_decimal"])}, {_attr(r["b_decimal"])}]" '
                   f'sign_at_ends="{r["sign_a"]:+d},{r["sign_b"]:+d}" exact_residual_at_decimal="{_attr(r["residual"])}"/>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 600)}</note>")
    out.append("</computed_results>")
    return out


def _render_system_facts(d: dict[str, Any]) -> list[str]:
    """A stated or named ODE system integrated by code (tribos.writer.system_facts)."""
    out = ['<computed_results note="this system was integrated by code exactly as listed in <equations>; report these '
           'values as the simulation results, name the methods, and do not invent values that are not here">',
           "<equations>" + " ; ".join(_text(e, 300) for e in d.get("equations_latex") or []) + "</equations>",
           f'<setup system="{_attr(d.get("label"))}" initial="{_attr(d.get("initial"))}" span="{_attr(d.get("span"))}" '
           f'stiff="{_attr(str(bool(d.get("stiff"))).lower())}" chaotic="{_attr(str(bool(d.get("chaotic"))).lower())}"/>']
    out += [f'<method>{_attr(m)}</method>' for m in d.get("methods") or []]
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 900)}</note>")
    out.append("</computed_results>")
    return out


def _render_pde_facts(d: dict[str, Any]) -> list[str]:
    """The heat equation solved by code with a refinement study (tribos.writer.pde_facts)."""
    out = ['<computed_results note="this PDE was solved by code with the schemes and grids listed; report the measured '
           'errors and observed orders as computed, against the exact manufactured solution">',
           f"<problem>{_text(d.get('equation_latex'), 300)}</problem>",
           f"<exact_solution>{_text(d.get('exact_latex'), 300)}</exact_solution>"]
    for r in d.get("refinement") or []:
        out.append(f'<grid intervals="{r["n"]}" dx="{r["dx"]:.4g}" cn_error="{r["cn_error"]:.3e}" '
                   f'cn_order="{r.get("cn_order", float("nan")):.3f}" ftcs_error="{r["ftcs_error"]:.3e}" '
                   f'ftcs_order="{r.get("ftcs_order", float("nan")):.3f}"/>')
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    out.append("</computed_results>")
    return out


def _render_construct_facts(d: dict[str, Any]) -> list[str]:
    """Construct mode (tribos.agentic.construct): the best construction found, scored exactly, against the known."""
    out = ['<computed_results note="a construction found by evolving programs, each candidate checked exactly by the '
           'scorer; report the value and the comparison as given; a value beyond the best known is a candidate result '
           'needing independent confirmation, never a solved problem; finding a construction proves nothing about '
           'optimality">',
           f"<problem>{_text(d.get('problem'), 200)}: {_text(d.get('statement'), 600)}</problem>"]
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    out.append(f"<best_candidate>{_text(json.dumps(d.get('candidate'), default=str), 1500)}</best_candidate>")
    out.append(f"<best_program>{_text(d.get('best_program'), 2500)}</best_program>")
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    out.append("</computed_results>")
    return out


def _render_poisson_facts(d: dict[str, Any]) -> list[str]:
    """The 2-D Poisson problem solved by finite elements with a refinement study (tribos.writer.pde_facts)."""
    out = ['<computed_results note="this PDE was solved by code with the elements and meshes listed; report the measured '
           'errors and observed orders as computed, against the exact manufactured solution">',
           f"<problem>{_text(d.get('equation_latex'), 300)}</problem>",
           f"<exact_solution>{_text(d.get('exact_latex'), 300)}</exact_solution>"]
    for r in d.get("refinement") or []:
        out.append(f'<mesh cells_per_side="{r["n"]}" h="{r["h"]:.4g}" l2_error="{r["l2"]:.3e}" '
                   f'l2_order="{r.get("l2_order", float("nan")):.3f}" h1_error="{r["h1"]:.3e}" '
                   f'h1_order="{r.get("h1_order", float("nan")):.3f}"/>')
    for p in d.get("parameters") or []:
        out.append(f'<result name="{_attr(p.get("name"))}" value="{_attr(p.get("value"))}"/>')
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 300)}</check>')
    out.append("</computed_results>")
    return out


def render_computed_results(res: Any) -> list[str]:
    """Values computed by code for the question (tribos.writer.facts): exact, checked, ready to present."""
    d = _data(res)
    if d.get("kind") == "construction_search":
        return _render_construct_facts(d)
    if d.get("kind") == "pde_poisson":
        return _render_poisson_facts(d)
    if d.get("kind") == "pde_heat":
        return _render_pde_facts(d)
    if d.get("kind") == "dynamical_system":
        return _render_system_facts(d)
    if d.get("kind") == "polynomial_roots":
        return _render_roots_facts(d)
    if d.get("kind") == "polynomial_analysis":
        return _render_poly_facts(d)
    if d.get("kind") == "number_theory_finite":
        return _render_number_facts(d)
    if d.get("kind") == "nbody_gravity":
        return _render_nbody_facts(d)
    if d.get("kind") != "ode_initial_value_problem":
        return []
    units = d.get("units") or {}
    t_unit, x_unit = units.get("time") or "", units.get("solution") or ""
    dep, ind = d.get("dependent", "x"), d.get("independent", "t")
    out = [
        '<computed_results note="computed by code for this question; exact values checked as listed; use them as given, '
        'formatted for the reader, without naming how they were obtained">',
        f"<equation>{_text(d.get('equation_latex'), 600)}</equation>",
    ]
    for ic in d.get("initial_conditions") or []:
        prime = "'" * int(ic.get("order") or 0)
        condition = f"{dep}{prime}({ic.get('at')}) = {ic.get('value')}"
        out.append(f"<initial_condition>{_text(condition, 120)}</initial_condition>")
    for c in d.get("checks") or []:
        out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 200)}</check>')
    for key, label in (("exact_solution_latex", "exact_solution"), ("transient_latex", "transient_part"),
                       ("steady_state_latex", "steady_state_part")):
        if d.get(key):
            out.append(f"<{label} latex=\"true\">{_text(d[key], 1500)}</{label}>")
    for p in d.get("parameters") or []:
        extra = f' degrees="{_attr(p["value_degrees"])}"' if p.get("value_degrees") else ""
        out.append(
            f'<parameter name="{_attr(p.get("name"))}" formula="{_attr(p.get("symbol"))}" exact="{_attr(p.get("exact_latex"))}" '
            f'value="{_attr(p.get("value"))}" unit="{_attr(p.get("unit"))}"{extra}/>'
        )
    if d.get("table"):
        out.append(f'<values_at_requested_points {ind}_unit="{_attr(t_unit)}" {dep}_unit="{_attr(x_unit)}">'
                   + _json(d["table"]) + "</values_at_requested_points>")
    rk = d.get("rk4")
    if isinstance(rk, dict):
        step_note = "" if rk.get("step_was_given") else ' step_note="step not given in the question; chosen by the solver"'
        out.append(
            f'<rk4_comparison method="{_attr(rk.get("method"))}" step="{_attr(rk.get("step"))}"{step_note} '
            f'steps="{_attr(rk.get("steps"))}" compared_with="{_attr(rk.get("compared_with"))}" '
            f'max_abs_error="{_attr(rk.get("max_abs_error"))}" max_error_at="{_attr(rk.get("max_error_at"))}">'
            + _json(rk.get("at_points") or []) + "</rk4_comparison>"
        )
    physics = d.get("physics") or {}
    for c in physics.get("checks") or []:
        out.append(f'<physics_check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 200)}</physics_check>')
    for qn in physics.get("quantities") or []:
        exact = f' exact="{_attr(qn["exact_latex"])}"' if qn.get("exact_latex") else ""
        out.append(f'<derived_quantity name="{_attr(qn.get("name"))}"{exact} value="{_attr(qn.get("value"))}" '
                   f'unit="{_attr(qn.get("unit"))}"/>')
    conv = d.get("convergence")
    if isinstance(conv, dict):
        rich = conv.get("richardson_at_final_time") or {}
        out.append(
            f'<convergence_study observed_order="{_attr(conv.get("observed_order"))}" formal_order="4" '
            f'predicted_error_at_requested_step="{_attr(conv.get("predicted_error_at_requested_step"))}" '
            f'richardson="{_attr(rich.get("status"))}" gci_fine="{_attr(rich.get("gci_fine"))}">'
            + _json(conv.get("runs") or []) + "</convergence_study>")
        for c in conv.get("checks") or []:
            out.append(f'<check passed="{_attr(str(bool(c.get("passed"))).lower())}">{_text(c.get("name"), 200)}</check>')
    for n in d.get("notes") or []:
        out.append(f"<note>{_text(n, 300)}</note>")
    out.append("</computed_results>")
    return out


def render_codeact(res: Any) -> list[str]:
    """The model's Python notebook for the question: printed values are computed; its summary is not checked."""
    d = _data(res)
    out = ['<python_session note="cells the model wrote and the sandbox ran for this question; printed outputs are '
           'computed values you may use; the session summary is the model\'s own reading, not a proof; numerical '
           'exploration is evidence, not proof">']
    for n, c in enumerate(d.get("cells") or [], 1):
        body = c.get("stdout") if c.get("status") == "ok" else c.get("error")
        out.append(f'<cell n="{n}" status="{_attr(c.get("status"))}"><code>{_text(c.get("code"), 1500)}</code>'
                   f"<output>{_text(body, 1500)}</output></cell>")
    if d.get("final"):
        out.append(f"<session_summary>{_text(d['final'], 2500)}</session_summary>")
    out.append("</python_session>")
    return out


_RENDERERS = {
    CODEACT: render_codeact,
    COMPUTED_RESULTS: render_computed_results,
    CHEMISTRY: lambda res: render_chemistry(res),  # defined below, with the per-tool renderers
    DYNAMIS: render_dynamis,
    DYNAMIS_EQUILIBRIUM: render_dynamis,
    DYNAMIS_SCAN: render_dynamis,
    DYNAMIS_PDE: render_dynamis,
    DYNAMIS_MONTE_CARLO: render_dynamis,
    AXIOM: render_axiom,
    PHYSIS: render_physis,
    CALCULA: render_calcula,
}


def render_chemistry(res: Any) -> list[str]:
    """physis_molecule / physis_stereo: structure facts and, per configuration, the ring faces of its substituents."""
    d, tool = _data(res), str(getattr(res, "tool_name", "") or "physis_molecule")
    out = [f'<chemistry tool="{_attr(tool)}" method="{_attr(d.get("method") or "RDKit")}">']
    for m in (d.get("molecules") or [])[:LIST_ITEMS]:
        if not isinstance(m, dict):
            continue
        if m.get("error"):
            out.append(f'<molecule name="{_attr(m.get("name"))}" error="{_attr(m["error"])}"/>')
            continue
        iso = m.get("stereoisomers_of_constitution") or {}
        facts = {k: m.get(k) for k in ("smiles", "formula", "molecular_weight", "monoisotopic_mass",
                                       "degree_of_unsaturation", "formal_charge", "rings", "aromatic_rings", "stereo",
                                       "chiral", "meso", "h_environments", "h_environments_on_carbon",
                                       "h_environment_sizes", "c_environments", "c_environment_sizes", "point_group",
                                       "point_group_heavy_atoms", "point_group_most_symmetric_low_energy", "note")
                 if m.get(k) not in (None, "", [], {})}
        facts["stereoisomers_of_constitution"] = iso
        out.append(f'<molecule name="{_attr(m.get("name"))}">{_json(facts)}</molecule>')
    for c in (d.get("comparisons") or [])[:LIST_ITEMS]:
        if isinstance(c, dict):
            out.append(f'<relation a="{_attr(c.get("a"))}" b="{_attr(c.get("b"))}">{_text(c.get("relation"), 80)}</relation>')
    if d.get("source"):
        out.append(f"<source>{_text(d['source'], 120)}</source>")
    constitutions = d.get("constitutions") or ([d["constitution"]] if isinstance(d.get("constitution"), dict) else [])
    for constitution in constitutions[:8]:
        if not isinstance(constitution, dict):
            continue
        options = f' options="{_attr(", ".join(constitution["options"]))}"' if constitution.get("options") else ""
        out.append(f'<constitution{options} smiles="{_attr(constitution.get("smiles"))}" '
                   f'formula="{_attr(constitution.get("formula"))}" '
                   f'stereo_elements="{_attr(", ".join(constitution.get("stereo_elements") or []))}"/>')
        numbered = constitution.get("numbered_atoms")
        if isinstance(numbered, dict) and not constitution.get("options"):
            # A model-written constitution: its bonds are checked against the name before its faces are trusted.
            gaps = ", ".join(numbered.get("consecutive_not_bonded") or []) or "none"
            out.append(f'<bonds_by_locant consecutive_not_bonded="{_attr(gaps)}">'
                       f'{_text(", ".join(numbered.get("bonds") or []), 600)}</bonds_by_locant>')
            out.append("<note>This structure was written by a model. Check these bonds against the name (fusion "
                       "atoms such as 3a-7a, bridges such as 4-8-7) before using the faces below; with a wrong bond "
                       "every face is wrong. Consecutive locants are bonded except where a bridge begins.</note>")
    for i, c in enumerate((d.get("configurations") or [])[:16], start=1):
        if not isinstance(c, dict):
            continue
        head = f'<configuration n="{i}" requested="{_attr(c.get("requested") or c.get("source") or "")}"'
        if c.get("error"):
            out.append(f'{head} error="{_attr(c["error"])}"/>')
            continue
        out.append(f'{head} descriptors="{_attr(c.get("descriptors"))}" smiles="{_attr(c.get("smiles"))}">')
        for key, label in (("same_compound_as", "same compound as"), ("enantiomer_of", "enantiomer of")):
            if c.get(key):
                refs = ", ".join(f"configuration {x}" if isinstance(x, int) else str(x) for x in c[key])
                out.append(f"<note>{label} {_text(refs, 120)}</note>")
        if c.get("achiral"):
            out.append("<note>achiral (meso): identical to its mirror image</note>")
        if c.get("unspecified"):
            out.append(f"<note>left unspecified: {_text(', '.join(c['unspecified']), 200)}</note>")
        if c.get("geometry"):
            out.append(f"<note>{_text(c['geometry'], 200)}</note>")
        for ring in (c.get("rings") or [])[:8]:
            if not isinstance(ring, dict):
                continue
            out.append(f'<ring atoms="{_attr(ring.get("ring"))}" face_a="{_attr("; ".join(ring.get("face_a") or []))}" '
                       f'face_b="{_attr("; ".join(ring.get("face_b") or []))}"/>')
            pairs = [f"{p.get('a')} / {p.get('b')}: {p.get('relation')}" for p in (ring.get("pairs") or [])[:15]]
            if pairs:
                out.append(f"<pairs>{_text('; '.join(pairs), 1200)}</pairs>")
        for dist in (c.get("distances") or [])[:10]:
            if isinstance(dist, dict):
                out.append(f'<distance a="{_attr(dist.get("a"))}" b="{_attr(dist.get("b"))}">'
                           f'{_attr(dist.get("distance_angstrom", dist.get("error", "")))}</distance>')
        out.append("</configuration>")
    for note in (d.get("notes") or [])[:4]:
        out.append(f"<note>{_text(note, 300)}</note>")
    if d.get("how_to_read"):
        out.append(f"<how_to_read>{_text(d['how_to_read'], 500)}</how_to_read>")
    out.append("</chemistry>")
    return out


# Tools rendered by their own renderer wherever their result appears (see render_tool_result).
TOOL_RENDERERS = {
    "physis_molecule": render_chemistry,
    "physis_stereo": render_chemistry,
    "calcula_run_python": render_calcula,
    "analysis_run_python": render_calcula,
    "dynamis_monte_carlo_integrate": render_dynamis,
    "dynamis_solve_pde": render_dynamis,
    "dynamis_fit_parameters": render_dynamis,
    "physis_propagate_uncertainty": render_physis,
    "physis_engineering_calc": render_engineering_calc,
    "physis_list_calculators": render_calculator_list,
    "archivon_read_paper": render_paper,
    "archivon_reproduce_paper": render_paper,
    "axiom_formal_check": render_formal_check,
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
    "render_computed_results",
    "render_dynamis",
    "render_engineering_calc",
    "render_paper",
    "render_pde",
    "render_physis",
    "render_tool_result",
    "stem_evidence",
]
