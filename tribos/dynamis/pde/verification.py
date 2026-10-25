"""Verification of a PDE solution: the mesh-convergence study, the conservation checks and the analytic comparison.

The convergence study solves the same problem on nested grids (each level halves the spacing, so every coarse node
is also a fine node) and compares the levels at their shared nodes, so no interpolation error enters the estimate.
With an analytic solution the error of each level is measured directly; without one, the difference between two
neighbouring levels estimates it. With e(h) = C h^p:

- the observed order is p = log2(e_k / e_{k+1}) (or the same for the differences between levels);
- the Richardson estimate of the error of a level is its difference to the next finer level divided by 1 - 2^-p.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# A difference this small relative to the size of the field is round-off: the scheme is exact for the data.
ROUND_OFF = 1e-11
# The relative error estimate below which a solution counts as converged on its grid.
CONVERGED_RELATIVE_ERROR = 1e-2


def restrict(fine: np.ndarray, coarse_shape: tuple[int, ...]) -> np.ndarray:
    """The values of a field on a nested coarser grid: every second node along each axis."""
    out = np.asarray(fine, dtype=float)
    for axis, n in enumerate(coarse_shape):
        index = [slice(None)] * out.ndim
        index[axis] = slice(None, None, 2)
        out = out[tuple(index)]
        if out.shape[axis] != n:
            raise ValueError(f"The grids are not nested: axis {axis} has {out.shape[axis]} shared nodes, expected {n}.")
    return out


def _order(coarse: float, fine: float) -> float | None:
    if coarse <= 0.0 or fine <= 0.0 or not (math.isfinite(coarse) and math.isfinite(fine)):
        return None
    return math.log2(coarse / fine)


def convergence_table(
    points: list[int],
    spacings: list[float],
    fields: list[np.ndarray],
    exact: list[np.ndarray] | None,
    reported_level: int,
    expected_order: int,
) -> dict[str, Any]:
    """The convergence study of solutions on nested grids (coarsest first), for the reported level."""
    scale = max(float(np.max(np.abs(f))) for f in fields) or 1.0
    differences = [
        float(np.max(np.abs(fields[k] - restrict(fields[k + 1], fields[k].shape)))) for k in range(len(fields) - 1)
    ]
    errors = [float(np.max(np.abs(f - e))) for f, e in zip(fields, exact, strict=True)] if exact else None
    measure = errors if errors is not None else differences
    rows: list[dict[str, Any]] = []
    for k, (n, h) in enumerate(zip(points, spacings, strict=True)):
        row: dict[str, Any] = {"n": n, "h": h, "level": k}
        if errors is not None:
            row["error"] = errors[k]
        if k < len(differences):
            row["difference_to_finer"] = differences[k]
        if k >= 1 and k - 1 < len(measure) and k < len(measure):
            row["order"] = _order(measure[k - 1], measure[k])
        rows.append(row)

    at_round_off = max(measure) <= ROUND_OFF * scale if measure else False
    order = None if at_round_off or len(measure) < 2 else _order(measure[-2], measure[-1])
    note = ""
    if at_round_off:
        note = "The levels agree to round-off: the scheme is exact for this data."
    elif order is None:
        note = "The error did not decrease under refinement, so no order of convergence can be stated."

    # The Richardson estimate of the reported level's error, from its difference to a neighbouring level.
    estimate: float | None = None
    if at_round_off:
        estimate = max(measure)
    elif order is not None and order > 0.0:
        factor = 2.0**order
        if reported_level < len(differences):
            estimate = differences[reported_level] / (1.0 - 1.0 / factor)
        else:
            estimate = differences[-1] / (factor - 1.0)
    relative = None if estimate is None else estimate / scale
    converged = bool(at_round_off or (order is not None and order > 0.5 and relative is not None
                                      and relative <= CONVERGED_RELATIVE_ERROR))
    if order is not None and order < 0.75 * expected_order and not note:
        note = (f"The observed order {order:.2f} is below the scheme's order {expected_order}: the grids may not yet be in "
                "the asymptotic range, or the data is not smooth.")
    return {
        "levels": rows,
        "order": order,
        "expected_order": expected_order,
        "richardson_error": estimate,
        "relative_error": relative,
        "converged": converged,
        "reference": "analytic solution" if errors is not None else "next finer grid",
        "reported_level": reported_level,
        "note": note,
    }


def conservation_report(kind: str, series: list[float], tolerance: float, note: str,
                        scale: float | None = None) -> dict[str, Any]:
    """How much a conserved quantity drifted: the largest change from its first value, relative to its size.

    A signed integral can be zero (a sine over a whole period), so the caller may pass the size of the field (the
    integral of |u|) as the scale instead.
    """
    values = [float(v) for v in series]
    initial = values[0]
    drift = max(abs(v - initial) for v in values)
    scale = max([abs(v) for v in values] + [abs(float(scale or 0.0))]) or 1.0
    relative = drift / scale
    return {
        "kind": kind,
        "initial": initial,
        "final": values[-1],
        "drift": drift,
        "relative_drift": relative,
        "tolerance": tolerance,
        "conserved": bool(relative <= tolerance),
        "note": note,
    }


def analytic_comparison(expression: str, fields: list[np.ndarray], exact: list[np.ndarray]) -> dict[str, Any]:
    """The error of the solution against the analytic one, over every snapshot."""
    errors = [float(np.max(np.abs(f - e))) for f, e in zip(fields, exact, strict=True)]
    scale = max(float(np.max(np.abs(e))) for e in exact) or 1.0
    worst = max(errors)
    return {
        "exact_solution": expression,
        "max_error": worst,
        "final_error": errors[-1],
        "relative_error": worst / scale,
        "agrees": bool(worst / scale <= CONVERGED_RELATIVE_ERROR),
    }


__all__ = ["analytic_comparison", "conservation_report", "convergence_table", "restrict"]
