"""Fixed-step integration: the requested RK4 grid is the solver grid, not interpolated output."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

MAX_FIXED_STEPS = 9999


def rk4_integrate(
    rhs: Callable[[float, np.ndarray], np.ndarray],
    initial: list[float],
    t_span: tuple[float, float],
    *,
    step_size: float | None = None,
    num_steps: int | None = None,
) -> Any:
    start, end = map(float, t_span)
    if not all(map(math.isfinite, (start, end))) or end <= start:
        raise ValueError("RK4 needs a finite increasing time span.")
    if step_size is None and num_steps is None:
        raise ValueError(
            "Fixed-step RK4 needs step_size or num_steps; an output-sample count is not a step count."
        )
    if step_size is not None:
        if not math.isfinite(step_size) or step_size <= 0:
            raise ValueError("RK4 step_size must be positive and finite.")
        count = (end - start) / step_size
        if not math.isclose(count, round(count), rel_tol=1e-10, abs_tol=1e-9):
            raise ValueError(
                "The time span must contain an integer number of the requested RK4 steps."
            )
        if num_steps is not None and num_steps != round(count):
            raise ValueError(
                "RK4 step_size, num_steps and t_span disagree; no value was substituted."
            )
        num_steps = round(count)
    if (
        isinstance(num_steps, bool)
        or not isinstance(num_steps, int)
        or not 1 <= num_steps <= MAX_FIXED_STEPS
    ):
        raise ValueError(f"RK4 num_steps must be an integer from 1 to {MAX_FIXED_STEPS}.")
    h = (end - start) / num_steps
    times = np.linspace(start, end, num_steps + 1, dtype=np.float64)
    values = np.empty((len(initial), len(times)), dtype=np.float64)
    values[:, 0] = initial
    if not np.isfinite(values[:, 0]).all():
        raise ValueError("RK4 initial values must be finite.")
    for i in range(num_steps):
        t, y = float(times[i]), values[:, i]
        k1 = np.asarray(rhs(t, y), dtype=np.float64)
        k2 = np.asarray(rhs(t + h / 2, y + h * k1 / 2), dtype=np.float64)
        k3 = np.asarray(rhs(t + h / 2, y + h * k2 / 2), dtype=np.float64)
        k4 = np.asarray(rhs(t + h, y + h * k3), dtype=np.float64)
        values[:, i + 1] = y + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6
        if not np.isfinite(values[:, i + 1]).all():
            raise RuntimeError(f"RK4 produced a non-finite state at step {i + 1}.")
    return SimpleNamespace(
        t=times,
        y=values,
        sol=None,
        success=True,
        nfev=4 * num_steps,
        message="Completed the requested fixed-step RK4 grid.",
    )


def linear_endpoint_reference(
    expressions: list[Any],
    symbols: list[Any],
    initial: list[float],
    t_span: tuple[float, float],
) -> dict[str, Any] | None:
    """Independent matrix-exponential reference for autonomous affine linear systems; never approximate a nonlinear one."""
    import sympy as sp
    from scipy.linalg import expm

    vector = sp.Matrix(expressions)
    matrix = vector.jacobian(symbols)
    offset = sp.simplify(vector - matrix * sp.Matrix(symbols))
    if matrix.free_symbols or offset.free_symbols:
        return None
    a, b = np.asarray(matrix, dtype=float), np.asarray(offset, dtype=float).ravel()
    augmented = np.zeros((len(initial) + 1, len(initial) + 1), dtype=np.float64)
    augmented[:-1, :-1], augmented[:-1, -1] = a, b
    endpoint = (expm(augmented * (t_span[1] - t_span[0])) @ np.r_[initial, 1.0])[:-1]
    if not np.isfinite(endpoint).all():
        return None
    return {
        "method": "analytical matrix exponential evaluated with scipy.linalg.expm",
        "formula": "[Y(t), 1] = exp(B*(t-t0)) @ [Y(t0), 1]",
        "augmented_matrix": augmented.tolist(),
        "initial_state": initial,
        "endpoint": {str(s): float(v) for s, v in zip(symbols, endpoint, strict=True)},
        "dtype": "float64",
        "note": "A separate analytical reference evaluated in floating point, not an exact-number proof.",
    }
