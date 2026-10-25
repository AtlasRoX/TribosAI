"""Portable nbformat-4 exports. Generating a notebook never executes the recorded program."""

from __future__ import annotations

import json
import re
from typing import Any

import sympy as sp

from tribos.axiom.engine import safe_parse_expr

from .report_model import ReportModel, citation_line


def _expr(text: Any) -> str:
    # Emit constructors from the parsed tree, never interpolate input as executable Python.
    return sp.srepr(safe_parse_expr(str(text)))


def _private(text: str) -> bool:
    return bool(re.search(
        r"(?i)(?:api[_-]?key|password|bearer\s|secret|[a-z]:[/\\]|/(?:home|users|srv|tmp|var)/)", text
    ))


def _ode(call: dict[str, Any], index: int, artifacts: dict[str, Any]) -> tuple[str, list[str]]:
    inputs = call.get("inputs") or {}
    output = call.get("output_digest") or {}
    artifact = artifacts.get("dynamis") or {}
    spec = output.get("spec") or artifact.get("spec") or inputs
    if not spec.get("rhs") and spec.get("model_name"):
        from tribos.dynamis.engine import ODE_PRESETS

        preset = ODE_PRESETS.get(spec["model_name"], {})
        spec = {**preset, **spec}
        for key in ("parameters", "initial_state"):
            spec[key] = {**preset.get(key, {}), **spec.get(key, {})}
    rhs, initial = spec.get("rhs"), spec.get("initial_state")
    if not rhs or not initial or not spec.get("t_span"):
        raise ValueError("the exact ODE specification was not recorded")
    names = list(rhs)
    parameters = spec.get("parameters") or {}
    symbols = [sp.Symbol(n) for n in names]
    local = {n: s for n, s in zip(names, symbols, strict=True)}
    local["t"] = sp.Symbol("t")
    for name, value in parameters.items():
        local[name] = float(value)
    exprs = [safe_parse_expr(rhs[n], local_dict=local) for n in names]
    if any(e.free_symbols - set(symbols) - {local["t"]} for e in exprs):
        raise ValueError("the ODE has unresolved parameters")
    span = [float(v) for v in spec["t_span"]]
    recorded_t = output.get("t") or artifact.get("t")
    grid = repr(recorded_t) if recorded_t else f"np.linspace({span[0]!r}, {span[1]!r}, 200)"
    var = f"ode_{index}"
    code = (
        "import numpy as np\nfrom scipy.integrate import solve_ivp\n"
        f"states_{index} = {names!r}\n"
        f"rhs_{index} = lambdify((Symbol('t'), {sp.srepr(sp.Tuple(*symbols))}), "
        f"{sp.srepr(sp.Tuple(*exprs))}, modules='numpy')\n"
        f"{var} = solve_ivp(lambda t, y: np.asarray(rhs_{index}(t, y), dtype=float).ravel(), "
        f"{span!r}, {[float(initial[n]) for n in names]!r}, t_eval={grid}, "
        f"method={spec.get('method', 'RK45')!r}, rtol=1e-8, atol=1e-10)\n"
        f"assert {var}.success, {var}.message\n"
        f"print(dict(zip(states_{index}, {var}.y[:, -1])))\n"
    )
    assertions = []
    summary = output.get("summary") or artifact.get("summary") or {}
    for i, name in enumerate(names):
        final = summary.get(name, {}).get("final")
        if final is not None:
            assertions.append(f"assert np.isclose({var}.y[{i}, -1], {float(final)!r}, rtol=1e-6, atol=1e-8)")
    return code, assertions


def _axiom(call: dict[str, Any], index: int) -> tuple[str, list[str]]:
    inputs, output = call.get("inputs") or {}, call.get("output_digest") or {}
    tool = call["tool_name"]
    expression = inputs.get("expression") or output.get("expression")
    var = f"symbolic_{index}"
    if tool in ("axiom_simplify", "axiom_latex"):
        code = f"{var} = simplify({_expr(expression)})\nprint({var})\n"
        expected = output.get("simplified") or output.get("sympy")
    elif tool == "axiom_calculus":
        operation = inputs.get("operation", output.get("operation"))
        variable = f"Symbol({str(inputs.get('variable', output.get('variable', 'x')))!r})"
        expr = _expr(expression)
        if operation == "diff":
            calculation = f"diff({expr}, {variable}, {int(inputs.get('order', 1))})"
        elif operation in ("integrate", "sum"):
            target = variable
            if inputs.get("lower") is not None and inputs.get("upper") is not None:
                target = f"({variable}, {_expr(inputs['lower'])}, {_expr(inputs['upper'])})"
            calculation = f"{'summation' if operation == 'sum' else 'integrate'}({expr}, {target})"
        elif operation == "limit":
            calculation = f"limit({expr}, {variable}, {_expr(inputs.get('point', 0))})"
        elif operation == "series":
            calculation = f"series({expr}, {variable}, {_expr(inputs.get('point', 0))}, n={int(inputs.get('order', 6))}).removeO()"
        else:
            raise ValueError("this symbolic operation is not supported by the portable exporter")
        code = f"{var} = {calculation}\nprint({var})\n"
        expected = output.get("result")
    elif tool == "axiom_solve":
        equations = inputs.get("equations")
        equations = [equations] if isinstance(equations, str) else equations
        from tribos.axiom.engine import safe_parse_equation

        residuals = [sp.srepr(a - b) for a, b, _ in (safe_parse_equation(e) for e in equations)]
        variables = inputs.get("variables") or output.get("variables")
        variables = [variables] if isinstance(variables, str) else variables
        syms = ", ".join(f"Symbol({v!r})" for v in variables)
        code = f"{var} = solve([{', '.join(residuals)}], [{syms}], dict=True)\nprint({var})\n"
        return code, [f"assert all(simplify(e.subs(s)) == 0 for s in {var} for e in [{', '.join(residuals)}])"]
    else:
        raise ValueError("this symbolic tool is not supported by the portable exporter")
    checks = [f"assert simplify({var} - ({_expr(expected)})) == 0"] if expected is not None else []
    return code, checks


def render_notebook(report: ReportModel) -> bytes:
    cells: list[dict[str, Any]] = []

    def cell(kind: str, source: str) -> None:
        item: dict[str, Any] = {"id": f"tribos-{len(cells) + 1}", "cell_type": kind, "metadata": {},
                                "source": source.splitlines(keepends=True)}
        if kind == "code":
            item.update(execution_count=None, outputs=[])
        cells.append(item)

    cell("markdown", f"# {report.title}\n\nRun: {report.run_id or 'not recorded'}\n\n"
         f"Provenance: {report.provenance}. Review recorded code before running it.\n")
    cell("markdown", "## Question\n\n" + report.question)
    cell("markdown", "## Answer\n\n" + report.answer_markdown)
    cell("code", "from sympy import *\nimport numpy as np\n")
    checks: list[str] = []
    plots: list[str] = []
    for index, call in enumerate((report.manifest or {}).get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        tool = call.get("tool_name", "unknown")
        cell("markdown", f"## Recorded call {index + 1}: {tool}\n")
        try:
            if call.get("success") is False:
                raise ValueError("the recorded call failed")
            if tool == "dynamis_simulate_ode":
                code, assertions = _ode(call, index, report.artifacts)
                plots += [f"plt.figure()\nplt.plot(ode_{index}.t, ode_{index}.y.T)\n"
                          f"plt.legend(states_{index})\nplt.xlabel('t')\nplt.show()\n"]
            elif tool.startswith("axiom_"):
                code, assertions = _axiom(call, index)
            elif tool in ("calcula_run_python", "sandbox_run_python", "analysis_run_python"):
                code = (call.get("inputs") or {}).get("code", "")
                if not code or _private(code):
                    raise ValueError("the program is missing or contains private paths or credentials")
                assertions = []
            elif tool.startswith("physis_") and (call.get("output_digest") or {}).get("constants"):
                constants = call["output_digest"]
                code, assertions = f"constants_{index} = {constants!r}\nprint(constants_{index})\n", []
            else:
                raise ValueError("no portable replay is available for this call")
            if _private(code):
                raise ValueError("the replay contains private paths or credentials")
            cell("code", code)
            checks += assertions
        except (ValueError, TypeError, KeyError, AttributeError):
            cell("markdown", "Replay unavailable: the recorded inputs are incomplete, private, or unsupported. "
                 "No result was guessed.\n")
    cell("code", "import matplotlib.pyplot as plt\n" + ("\n".join(plots) or "# No recorded trajectory to plot.\n"))
    cell("markdown", "## References\n\n" + ("\n".join(citation_line(c) for c in report.citations) or "None recorded."))
    cell("code", "import sys\nfrom importlib.metadata import version\nprint(sys.version)\n"
         "for package in ('numpy', 'scipy', 'sympy', 'matplotlib'):\n    print(package, version(package))\n")
    cell("code", "# Compare reruns with recorded values.\n" + ("\n".join(checks) or "# No recorded comparable results.\n"))
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }, "cells": cells}, indent=2, ensure_ascii=False).encode("utf-8")
