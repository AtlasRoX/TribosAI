"""Safe parsing and evaluation of the fields a PDE problem is given.

An initial condition, a source term, a boundary value or an exact solution is written by the user or by a model, so
it is parsed through the allowlist parser (`tribos.axiom.engine.safe_parse_expr`) and never with `eval` or SymPy's
`parse_expr`. The parsed SymPy expression is then evaluated on the grid with `lambdify`.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp

from tribos.axiom.engine import safe_parse_expr


class ExpressionError(ValueError):
    """A field expression could not be parsed or evaluated."""


def parse_field(text: str, *, symbols: tuple[str, ...], parameters: dict[str, float] | None = None) -> sp.Expr:
    """Parse a field expression over `symbols`, with the numeric parameters substituted.

    Every free symbol that is neither a coordinate, t nor a known parameter is rejected, so a typo becomes a clear
    error instead of a silent zero.
    """
    cleaned = str(text if text is not None else "").strip()
    if not cleaned:
        raise ExpressionError("An empty expression was given.")
    local: dict[str, Any] = {name: sp.Symbol(name) for name in symbols}
    subs: dict[sp.Symbol, float] = {}
    for name, value in (parameters or {}).items():
        if name in symbols:
            continue
        local[str(name)] = sp.Symbol(str(name))
        subs[local[str(name)]] = float(value)
    try:
        expr = safe_parse_expr(cleaned, local_dict=local)
    except ValueError as exc:
        raise ExpressionError(f"Could not parse the expression {cleaned!r}: {exc}") from exc
    if not isinstance(expr, sp.Expr):
        raise ExpressionError(f"The expression {cleaned!r} is not a scalar field.")
    unknown = sorted(str(s) for s in expr.free_symbols - {sp.Symbol(s) for s in symbols} - set(subs))
    if unknown:
        raise ExpressionError(
            f"The expression {cleaned!r} uses unknown symbol(s) {unknown}; "
            f"only {', '.join(symbols)} and the given parameters are allowed."
        )
    return expr.subs(subs) if subs else expr


def _evaluate(expr: sp.Expr, values: dict[str, Any], shape: tuple[int, ...]) -> np.ndarray:
    names = sorted(str(s) for s in expr.free_symbols)
    try:
        function = sp.lambdify([sp.Symbol(n) for n in names], expr, modules=["numpy", {"pi": math.pi, "E": math.e}])
        with np.errstate(all="ignore"):
            result = np.asarray(function(*(values[n] for n in names)), dtype=float)
    except Exception as exc:  # noqa: BLE001
        raise ExpressionError(f"Could not evaluate {expr}: {exc}") from exc
    result = np.broadcast_to(result, shape).astype(float)
    if not np.all(np.isfinite(result)):
        raise ExpressionError(f"The expression {expr} is not finite everywhere on the grid.")
    return result


def evaluate_points(expr: sp.Expr, coordinates: dict[str, np.ndarray], *, t: float = 0.0,
                    symbols: tuple[str, ...] = ("x", "y", "t")) -> np.ndarray:
    """Evaluate a parsed field at given points (`{"x": xs, "y": ys}`, arrays of the same length)."""
    arrays = {k: np.asarray(v, dtype=float) for k, v in coordinates.items()}
    shape = np.broadcast_shapes(*(a.shape for a in arrays.values())) if arrays else (1,)
    values: dict[str, Any] = {name: arrays.get(name, np.zeros(shape)) for name in symbols if name != "t"}
    values["t"] = float(t)
    return _evaluate(expr, values, shape)


def evaluate_field(expr: sp.Expr, axes: tuple[np.ndarray, ...], *, t: float = 0.0) -> np.ndarray:
    """Evaluate a parsed field on the grid at time t; the result is indexed [x] or [x, y]."""
    meshes = np.meshgrid(*axes, indexing="ij")
    values: dict[str, Any] = dict(zip(("x", "y"), meshes, strict=False))
    values["t"] = float(t)
    return _evaluate(expr, values, meshes[0].shape)


__all__ = ["ExpressionError", "evaluate_field", "evaluate_points", "parse_field"]
