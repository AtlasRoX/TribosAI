"""
The plot stage: a question that asks for a plot gets one, drawn by matplotlib in the sandbox.

One model call writes a single script from the templates below (a function, a contour or surface, a phase portrait, an
ODE solution, a histogram, a bar chart, a parametric or polar curve), the sandbox runs it and captures the figures, and
a failed script gets one repair attempt with its error. The figure is shown with the answer (artifact "plot"), the PNG
and the script are attached as downloadable files, and the writer is told to describe the figure rather than redraw it.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .context import RunContext, logger

ARTIFACT = "plot"
MAX_ATTEMPTS = 2
# "= nan", "error: inf", "-inf" printed by the script: a value of the figure's computation that blew up.
_NONFINITE_RE = re.compile(r"(?:=|:)\s*[-+]?(?:nan|inf(?:inity)?)\b", re.I)

# "plot", "graph of", "chart", "visualize", "contour", "heatmap" ...; not "graph theory" or "a bipartite graph".
PLOT_REQUEST_RE = re.compile(
    r"\b(?:plot(?:s|ted|ting)?|chart|visuali[sz]e|visuali[sz]ation|contour(?:\s+plot|\s+map|s)?|heat\s?map|"
    r"histogram|scatter(?:\s+plot)?|phase\s+portrait|vector\s+field|surface\s+plot|sketch\s+the\s+graph|"
    r"graph\s+(?:of|the|it|f|y|x|this|these|both)|draw\s+(?:the\s+)?(?:graph|curve|plot))\b",
    re.I,
)

SYSTEM = """You write ONE Python script that draws exactly the plot the user asks for, with matplotlib.

Rules:
- Use only numpy, scipy, matplotlib (and mpl_toolkits for 3-D). No input(), no files, no network, no plt.show(), no savefig.
- Start with: import numpy as np; import matplotlib.pyplot as plt. Use fig, ax = plt.subplots(figsize=(7, 4.5)) (two
  related views: plt.subplots(1, 2, figsize=(11, 4.2))). One figure unless the user asks for more.
- Use exactly the function, ranges, parameters and points the user gives. Choose a sensible range only when none is
  given, and say which in the title.
- Evaluate the function exactly as written, every term. Never simplify it, drop a term, or replace part of it with a
  constant. If the notation is broken or ambiguous (for example "\\frac6" with no numerator), implement the most literal
  reading, put "(as written)" in the title, and print "assumption = ..." saying how you read it.
- Compute every reported number from the function in the script (values, gradients, Hessians, tangent lines,
  directional derivatives), never from the question's text. When the question states a value to check ("verify that
  f(2,5) = 11"), print the computed one in the same form ("f(2, 5) = <computed>"), even when it disagrees.
- PDEs: use a stable method (Crank-Nicolson, the method of lines with scipy solve_ivp, or the exact solution when
  the question gives it). An explicit scheme only with its stability limit met (heat equation: alpha*dt/dx^2 <= 0.4).
  Every printed value must be finite.
- Critical points, roots and extrema: search the whole stated domain (a grid of starting points plus a root finder),
  keep only points where the gradient is ~0, de-duplicate them, and print "critical points = none in the domain" when
  there are none. Never invent or pick points to have something to mark.
- Label every axis (with units when the question has them), give a short title, add ax.grid(alpha=0.3), a legend when
  there is more than one curve, and fig.tight_layout() at the end.
- Mark every point the user names: a marker (ax.plot(x0, y0, "o", ms=7, zorder=5)) plus ax.annotate with its value.
- Print the key numbers a reader would check (a value at a marked point, a maximum, a root, a final state), one per
  line as "name = value". Keep it fast (a few seconds) and seed any randomness.
Reply with only the ```python``` block.

Templates (adapt; do not copy blindly):
1. Function of one variable:
   x = np.linspace(a, b, 600); y = f(x); ax.plot(x, y, lw=2, label="f(x)")
2. Function of two variables, contours (a level through a point: levels including f(x0, y0)):
   x = np.linspace(x1, x2, 300); y = np.linspace(y1, y2, 300); X, Y = np.meshgrid(x, y); Z = f(X, Y)
   cf = ax.contourf(X, Y, Z, levels=30, cmap="viridis"); fig.colorbar(cf, ax=ax, label="f(x, y)")
   cs = ax.contour(X, Y, Z, levels=[c], colors="white", linewidths=1.5); ax.clabel(cs, fmt="f = %g")
3. Surface: fig = plt.figure(figsize=(7, 5)); ax = fig.add_subplot(projection="3d"); ax.plot_surface(X, Y, Z, cmap="viridis")
4. ODE solution: from scipy.integrate import solve_ivp
   sol = solve_ivp(rhs, (t0, t1), y0, t_eval=np.linspace(t0, t1, 1000), rtol=1e-8, atol=1e-10); ax.plot(sol.t, sol.y[0])
   (a second-order ODE becomes a first-order system; plot the phase portrait on a second axis when it helps)
5. Phase portrait / vector field: ax.streamplot(X, Y, U, V, density=1.2, color="0.4") plus trajectories with solve_ivp
6. Histogram / distribution: rng = np.random.default_rng(0); ax.hist(data, bins=40, density=True, alpha=0.7)
7. Bar chart: ax.bar(labels, values); ax.bar_label(ax.containers[0], fmt="%g")
8. Parametric / polar: ax.plot(x(t), y(t)); ax.set_aspect("equal") / fig, ax = plt.subplots(subplot_kw={"projection": "polar"})"""


def wants_plot(run: RunContext) -> bool:
    from ...agentic.sandbox import execution_permitted_now, sandbox_enabled

    if getattr(run.ctx, "scope", "research") != "research":
        return False
    from ..question_text import typed_part

    # "The plot starts at (0, 0)" in an attached figure's description is not a request to plot.
    if not PLOT_REQUEST_RE.search(typed_part(run.clean_query or run.query or "")):
        return False
    if not sandbox_enabled() or not execution_permitted_now():
        return False
    # A figure another stage already drew answers the request (a dataset analysis, a CodeAct notebook that plotted).
    analysis = run.execution_artifacts.get("sandbox_analysis")
    return not (isinstance(analysis, dict) and analysis.get("figures"))


def _script(reply: str) -> str:
    m = re.search(r"```(?:python|py)?[ \t]*\n(.*?)```", reply or "", re.S | re.I)
    code = (m.group(1) if m else reply or "").strip()
    # The sandbox captures open figures itself; a show() or savefig() would only fail or duplicate.
    return re.sub(r"^\s*plt\.(?:show|savefig)\(.*\)\s*$", "", code, flags=re.M).strip()


def _context(run: RunContext) -> str:
    """Computed facts the figure must agree with (proved critical points, the mathematics agent's verified value)."""
    from .critical_stage import plot_hint

    return plot_hint(run) + _math_context(run)


def _math_context(run: RunContext) -> str:
    art = run.execution_artifacts.get("math_agent")
    if isinstance(art, dict) and art.get("status") == "verified":
        answer = art.get("answer") or {}
        text = str(answer.get("summary") or answer.get("text") or "")[:600]
        if text:
            return f"\n\nAlready computed and verified (the plot must agree): {text}"
    return ""


async def run_plot(run: RunContext) -> None:
    from ...agentic.sandbox.gateway import execute
    from .llm_call import ask, budget_admits

    if not wants_plot(run) or not budget_admits(run, MAX_ATTEMPTS):
        return
    await run.emit("plot", "Drawing the plot", "matplotlib in the sandbox", status="running")
    question = (run.clean_query or run.query or "").strip()
    messages: list[tuple[str, str]] = [("user", f"Plot request:\n{question[:3000]}{_context(run)}")]
    report: dict[str, Any] = {}
    code = ""
    for _attempt in range(MAX_ATTEMPTS):
        try:
            reply = await ask(run, SYSTEM, messages, timeout_s=120.0)
        except Exception as exc:  # noqa: BLE001 - no plot never blocks the answer
            logger.info("plot stage: model call failed: %s", exc)
            break
        code = _script(reply)
        if not code:
            break
        report = await asyncio.to_thread(execute, code)
        nonfinite = _NONFINITE_RE.search(str(report.get("stdout") or ""))
        if report.get("status") == "ok" and report.get("figures") and not nonfinite:
            break
        if report.get("status") == "ok" and report.get("figures") and nonfinite:
            # A figure of a blown-up computation (an unstable explicit PDE scheme printed "max error = nan") is
            # worse than none: it is repaired, and if the repair still prints nan the figure is not shown.
            error = (f"The script printed a non-finite value ({nonfinite.group(0).strip()}): the computation blew up. "
                     "Use a stable method (Crank-Nicolson, scipy solve_ivp on the method of lines, or the exact "
                     "solution), and check that every printed value is finite.")
        else:
            error = str(report.get("error") or report.get("stderr") or "the script drew no figure")[:1500]
        if report.get("violations"):
            error += "\n" + "; ".join(str(v) for v in report["violations"])[:500]
        messages += [("assistant", reply), ("user", f"The script failed:\n{error}\nReply with the corrected script.")]
    figures = [f for f in (report.get("figures") or []) if isinstance(f, dict) and f.get("png_base64")]
    if figures and _NONFINITE_RE.search(str(report.get("stdout") or "")):
        figures = []  # still blown up after the repair: no figure rather than a wrong one
        report = {**report, "error": "the computation behind the figure produced non-finite values (nan or inf)"}
    if not figures:
        await run.emit("plot", "Could not draw the plot", str(report.get("error") or "no figure")[:200], status="error")
        return
    run.execution_artifacts[ARTIFACT] = {
        "code": code,
        "stdout": str(report.get("stdout") or "")[:4000],
        "figures": [{"name": f.get("name"), "png_base64": f.get("png_base64"), "axes": f.get("axes") or []}
                    for f in figures],
        "seconds": report.get("seconds"),
    }
    printed = str(report.get("stdout") or "").strip()
    note = ("A figure answering the plot request was drawn by code and is shown with the answer (do not describe "
            "code, do not draw ASCII plots or chart blocks, do not say you cannot plot). Say in one or two sentences "
            "what the figure shows")
    notes = [note + (f"; the script printed:\n{printed[:800]}" if printed else ".")]
    mismatches = stated_value_mismatches(question, printed)
    if mismatches:
        run.execution_artifacts[ARTIFACT]["mismatches"] = mismatches
        listed = "; ".join(f"the question states {m['stated']}, the function as written gives {m['computed']}"
                           for m in mismatches)
        notes.append("VALUE CHECK FAILED, state this first, before anything else: " + listed + ". Do not adjust the "
                     "numbers to match; say the function as written does not satisfy the stated value and that the "
                     "question may have lost part of the formula (for example a fraction's numerator).")
        await run.emit("plot", "A stated value does not match the function", listed[:300], status="error")
    run.scope_notes = [*(getattr(run, "scope_notes", None) or []), *notes]
    await run.emit("plot", f"Drew {len(figures)} figure{'s' if len(figures) != 1 else ''}",
                   f"{report.get('seconds') or 0:.1f} s in the sandbox", status="done")


# "f(2,5) = 11", "g(0) = -3.5": a value the question states for its function at a point.
_POINT_VALUE_RE = re.compile(
    r"(?<![A-Za-z\\])([A-Za-z])\s*\(\s*(-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)*)\s*\)\s*=\s*(-?\d+(?:\.\d+)?(?:e-?\d+)?)",
)


def _point_values(text: str) -> dict[tuple[str, tuple[float, ...]], float]:
    out: dict[tuple[str, tuple[float, ...]], float] = {}
    for name, args, value in _POINT_VALUE_RE.findall(text or ""):
        try:
            out[(name, tuple(float(a) for a in args.split(",")))] = float(value)
        except ValueError:
            continue
    return out


def stated_value_mismatches(question: str, printed: str) -> list[dict[str, str]]:
    """Values the question states ("verify that f(2,5) = 11") that the plotted function, as computed by the script,
    does not give ("f(2, 5) = 8"): a broken or mistyped formula shows up here instead of in a silently wrong plot."""
    stated, computed = _point_values(question), _point_values(printed)
    out = []
    for key, want in stated.items():
        got = computed.get(key)
        if got is not None and abs(got - want) > 1e-6 * max(1.0, abs(want)):
            args = ", ".join(f"{a:g}" for a in key[1])
            out.append({"stated": f"{key[0]}({args}) = {want:g}", "computed": f"{key[0]}({args}) = {got:g}"})
    return out


def plot_files(question: str, plot: Any) -> list[tuple[str, str, bytes]]:
    """[(kind, filename, bytes)] for a drawn plot: each figure as PNG, and the script as a runnable .py file."""
    import base64

    from ...files import _slug

    if not isinstance(plot, dict) or not plot.get("figures"):
        return []
    base = _slug((question or "plot").split("\n", 1)[0])
    out: list[tuple[str, str, bytes]] = []
    figures = plot["figures"]
    for i, fig in enumerate(figures, 1):
        try:
            data = base64.b64decode(str(fig.get("png_base64") or ""))
        except (ValueError, TypeError):
            continue
        out.append(("png", f"{base}_plot{'' if len(figures) == 1 else f'_{i}'}.png", data))
    code = str(plot.get("code") or "").strip()
    if code:
        import textwrap

        from ...utils.plain_math import plain_math

        # The question as plain-text comments: raw LaTeX in a docstring ("\frac" holds the escape "\f") breaks Python.
        asked = textwrap.wrap(plain_math(question or "")[:400], 100) or ["(no question text)"]
        header = ("# Draws the plot for:\n" + "".join(f"#   {line}\n" for line in asked)
                  + "# Run: python this_file.py  (needs numpy, scipy and matplotlib)\n\n")
        out.append(("py", f"{base}_plot.py", (header + code + "\n\nplt.show()\n").encode("utf-8")))
    return out


__all__ = ["ARTIFACT", "PLOT_REQUEST_RE", "plot_files", "run_plot", "wants_plot"]
