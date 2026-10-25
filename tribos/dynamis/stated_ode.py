"""The ODE a question states, as the first-order system Dynamis integrates.

A question such as "m x'' + c x' + kx = F0 cos(wt) with m = 2 kg, ..., x(0) = 0.1 m, x'(0) = 0" must be simulated as
written: a named preset ("damped_oscillator") with its default parameters and initial state is a different system.
The math parser (tribos.axiom.problem) already substitutes the given values; this module turns its equation into
{x: v, v: f(t, x, v)} and the initial state, or returns None when the equation cannot be simulated as stated.
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp

from ..axiom.engine import _normalize_ode_primes, safe_parse_equation, safe_parse_expr


def stated_ode_system(equation: str, func: str, ics: dict[str, Any]) -> dict[str, Any] | None:
    """{"rhs": {state: expr}, "initial_state": {state: value}, "state_names": [...]} for a first- or second-order
    explicit ODE in one unknown with numeric initial conditions at t = 0; None otherwise (never a guess)."""
    m = re.match(r"^\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s*\)\s*$", func or "")
    if not m or not equation:
        return None
    fname, var = m.group(1), m.group(2)
    t, unknown = sp.Symbol(var), sp.Function(fname)
    try:
        lhs, rhs, _ = safe_parse_equation(_normalize_ode_primes(equation, fname, var), local_dict={var: t, fname: unknown})
    except Exception:  # noqa: BLE001 - an equation the parser cannot read is simply not simulated as stated
        return None
    expr = sp.expand(lhs - rhs)
    y = unknown(t)
    orders = [d.derivative_count for d in expr.atoms(sp.Derivative) if d.expr == y]
    order = max(orders, default=0)
    if order not in (1, 2):
        return None
    rate = "v" if fname != "v" else f"{fname}_dot"
    x_s, v_s, top = sp.Symbol(fname), sp.Symbol(rate), sp.Symbol("__top__")
    if order == 2:
        expr = expr.subs(sp.Derivative(y, (t, 2)), top).subs(sp.Derivative(y, t), v_s).subs(y, x_s)
    else:
        expr = expr.subs(sp.Derivative(y, t), top).subs(y, x_s)
    if expr.has(sp.Derivative) or expr.has(unknown):
        return None
    solved = sp.solve(expr, top)
    if len(solved) != 1:
        return None
    states = [fname, rate] if order == 2 else [fname]
    rhs_map = {fname: rate, rate: str(solved[0])} if order == 2 else {fname: str(solved[0])}

    initial: dict[str, float] = {}
    for key, value in (ics or {}).items():
        ic = re.match(rf"^{re.escape(fname)}('*)\s*\(\s*([^)]+?)\s*\)$", str(key).strip())
        if not ic:
            continue
        try:
            at = float(safe_parse_expr(ic.group(2)))
            val = float(safe_parse_expr(str(value)))
        except Exception:  # noqa: BLE001
            return None
        if at != 0.0:
            return None  # conditions at another time would need a shifted integration window
        initial[states[len(ic.group(1))] if len(ic.group(1)) < len(states) else ""] = val
    initial.pop("", None)
    if set(initial) != set(states):
        return None  # without every initial condition the stated problem is not fully specified
    return {"rhs": rhs_map, "initial_state": initial, "state_names": states}


_TIME_UNITS = {"s": "s", "sec": "s", "second": "s", "seconds": "s", "ms": "ms", "min": "min", "minutes": "min",
               "h": "h", "hours": "h"}


def stated_units(question: str, func: str, states: list[str]) -> dict[str, str]:
    """Units the question itself gives: the unknown's from its initial value ("x(0) = 0.1 m"), time from the stated
    interval ("over 0-20 s"), and the rate's as their quotient. A unit the question does not state is left out."""
    from ..verify.latex_math import is_unit_word

    text = (question or "").replace("–", "-").replace("—", "-")
    fname = re.sub(r"\(.*$", "", func or "").strip()
    units: dict[str, str] = {}
    t_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(seconds?|sec|s|ms|min(?:utes)?|h(?:ours)?)\b", text)
    if t_match:
        units["t"] = _TIME_UNITS.get(t_match.group(1).lower(), "")
    if fname and states:
        x_match = re.search(rf"(?<![\w']){re.escape(fname)}\s*\(\s*0\s*\)\s*=\s*[-+]?\d*\.?\d+\s*([A-Za-zμ°]+(?:/[A-Za-z]+)?)", text)
        if x_match and is_unit_word(x_match.group(1)):
            units[states[0]] = x_match.group(1)
            if len(states) > 1 and units.get("t"):
                units[states[1]] = f"{x_match.group(1)}/{units['t']}"
    return {k: v for k, v in units.items() if v}


__all__ = ["stated_ode_system", "stated_units"]
