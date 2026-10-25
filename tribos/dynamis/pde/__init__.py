"""The Dynamis PDE package: heat, wave, Poisson, advection-diffusion, Fisher-KPP and Burgers on rectangular domains.

`solve_pde` is the entry point. It parses the fields through the safe parser, runs the solver, and returns the field
with the verification that says whether it can be trusted: the mesh-convergence study (observed order, Richardson
error estimate, a converged flag), the comparison with the analytic solution when one is given, the conservation
check of mass or energy where the equation conserves one, and the stability number of the scheme.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from tribos.config.settings import get_float, get_int

from .expressions import ExpressionError, evaluate_field, parse_field
from .grid import AXIS_NAMES, BoundaryData, Grid, make_grid, normalise_boundary, periodic_axes
from .solvers import (
    EQUATIONS,
    METHODS,
    SOLVERS,
    ConvergenceError,
    Problem,
    StabilityError,
    resolve_method,
    resolve_parameters,
)
from .verification import analytic_comparison, conservation_report, convergence_table

OUTPUT_POINTS_1D = 401  # x points of a 1D snapshot in the result
OUTPUT_POINTS_2D = 80  # points per axis of a 2D snapshot in the result
MAX_SNAPSHOTS_2D = 11  # a 2D frame is up to 80x80 values, so fewer of them are kept
MIN_POINTS = 5


def _limits() -> dict[str, Any]:
    return {
        "grid_1d": int(get_int("TRIBOS_PDE_MAX_GRID_1D")),
        "grid_2d": int(get_int("TRIBOS_PDE_MAX_GRID_2D")),
        "seconds": float(get_float("TRIBOS_PDE_MAX_SECONDS")),
        "snapshots": int(get_int("TRIBOS_PDE_MAX_SNAPSHOTS")),
        "levels": int(get_int("TRIBOS_PDE_MAX_CONVERGENCE_LEVELS")),
    }


def _refine(n: int, periodic: bool) -> int:
    return 2 * n if periodic else 2 * (n - 1) + 1


def _coarsen(n: int, periodic: bool) -> int | None:
    """The nested coarser level, or None when n has none (an odd periodic count, an even bounded one)."""
    if periodic:
        return n // 2 if n % 2 == 0 else None
    return (n - 1) // 2 + 1 if (n - 1) % 2 == 0 else None


def _study_levels(n: int, periodic: bool, dimension: int, levels: int, cap: int) -> list[int]:
    """Nested point counts for the convergence study, the requested n among them.

    The study refines from n while the finer grid fits the cap and coarsens below n otherwise, so a request at the
    cap is still studied (on coarser grids) instead of being refused.
    """
    out = [n]
    while len(out) < levels and _refine(out[-1], periodic) ** dimension <= cap:
        out.append(_refine(out[-1], periodic))
    while len(out) < levels:
        coarser = _coarsen(out[0], periodic)
        if coarser is None or coarser < MIN_POINTS:
            break
        out.insert(0, coarser)
    return out


def _decimate(n: int, k: int) -> np.ndarray:
    return np.arange(n) if n <= k else np.unique(np.round(np.linspace(0, n - 1, k)).astype(int))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class _Setup:
    """The parsed inputs of one problem, from which a grid of any resolution can be built."""

    def __init__(self, *, equation: str, dimension: int, domain: tuple[tuple[float, float], ...],
                 parameters: dict[str, float], initial_condition: str | None, initial_velocity: str | None,
                 source: str | None, boundary: dict[str, str], boundary_values: dict[str, Any] | None,
                 exact_solution: str | None, times: np.ndarray, method: str, dt: float | None, on_unstable: str):
        self.equation, self.dimension, self.domain = equation, dimension, domain
        self.parameters, self.boundary, self.boundary_values = parameters, boundary, boundary_values
        self.times, self.method, self.dt, self.on_unstable = times, method, dt, on_unstable
        symbols = (*AXIS_NAMES[:dimension], "t")
        steady = equation == "poisson"

        def parse(text: str | None, what: str, default: str | None) -> Any:
            if text is None or not str(text).strip():
                return parse_field(default, symbols=symbols) if default is not None else None
            try:
                return parse_field(str(text), symbols=symbols, parameters=parameters)
            except ExpressionError as exc:
                raise ExpressionError(f"The {what}: {exc}") from exc

        if not steady and (initial_condition is None or not str(initial_condition).strip()):
            raise ValueError(f"The {equation} equation needs an initial condition u(x, 0) as an expression.")
        self.initial = parse(initial_condition, "initial condition", "0")
        self.velocity = parse(initial_velocity, "initial velocity", "0")
        self.source = parse(source, "source term", None)
        self.exact = parse(exact_solution, "exact solution", None)
        self.source_time_dependent = self.source is not None and _has_t(self.source)
        self.periodic = periodic_axes(boundary, dimension)

    def problem(self, n: int, deadline: float) -> Problem:
        grid = make_grid(self.domain, n, self.periodic)
        source = self.source

        def f(t: float) -> np.ndarray:
            return evaluate_field(source, grid.axes, t=t)

        cached = None if source is None or self.source_time_dependent else evaluate_field(source, grid.axes)
        return Problem(
            equation=self.equation, grid=grid, boundary=self.boundary,
            data=BoundaryData(grid, self.boundary, self.boundary_values, self.parameters), parameters=self.parameters,
            initial=evaluate_field(self.initial, grid.axes, t=float(self.times[0])),
            velocity=evaluate_field(self.velocity, grid.axes, t=float(self.times[0])),
            source=None if source is None else ((lambda _t: cached) if cached is not None else f),
            source_time_dependent=self.source_time_dependent, times=self.times, method=self.method, dt=self.dt,
            on_unstable=self.on_unstable, deadline=deadline,
        )

    def exact_on(self, grid: Grid, t: float) -> np.ndarray:
        return evaluate_field(self.exact, grid.axes, t=t)


def _has_t(expr: Any) -> bool:
    return "t" in {str(s) for s in expr.free_symbols}


def _conservation(setup: _Setup, problem: Problem, raw: dict[str, Any]) -> dict[str, Any] | None:
    """The conservation check, where the equation and its data conserve a quantity; None elsewhere."""
    closed = problem.data.homogeneous and all(k != "dirichlet" for k in setup.boundary.values())
    no_source = setup.source is None
    if setup.equation in ("heat", "advection_diffusion", "burgers") and closed and no_source:
        weights = problem.grid.weights()
        series = [float(np.sum(weights * s)) for s in raw["snapshots"]]
        tolerance = 1e-9 if setup.equation == "heat" and problem.method != "bdf" else 1e-6
        return conservation_report(
            "mass", series, tolerance,
            "With periodic or insulated edges and no source the integral of u is conserved; the scheme conserves its "
            "discrete integral exactly" + (", up to the integrator tolerance." if tolerance > 1e-9 else "."),
            scale=float(np.sum(weights * np.abs(raw["snapshots"][0]))),
        )
    if setup.equation == "wave" and problem.data.homogeneous and no_source and raw.get("energies"):
        return conservation_report(
            "energy", raw["energies"], 1e-8,
            "Leapfrog conserves its discrete energy exactly with homogeneous boundary data and no source, so the drift "
            "is round-off.",
        )
    return None


def _probes(probe_at: list[Any] | None, grid: Grid, snapshots: list[np.ndarray]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for position in probe_at or []:
        coords = list(position) if isinstance(position, (list, tuple)) else [position]
        if len(coords) != grid.dimension:
            raise ValueError(f"A probe in {grid.dimension}D needs {grid.dimension} coordinate(s), got {position!r}.")
        index = []
        for axis, value in enumerate(coords):
            lo, hi = grid.domain[axis]
            if not lo <= float(value) <= hi:
                raise ValueError(f"The probe {position!r} lies outside the domain.")
            index.append(int(np.argmin(np.abs(grid.axes[axis] - float(value)))))
        probe: dict[str, Any] = {"x": float(grid.axes[0][index[0]]), "values": [float(s[tuple(index)]) for s in snapshots]}
        if grid.dimension == 2:
            probe["y"] = float(grid.axes[1][index[1]])
        out.append(probe)
    return out


def solve_pde(
    equation: str,
    dimension: int | None = None,
    domain: Any = ((0.0, 1.0),),
    parameters: dict[str, Any] | None = None,
    initial_condition: str | None = None,
    initial_velocity: str | None = None,
    source: str | None = None,
    boundary: dict[str, Any] | str | None = None,
    boundary_values: dict[str, Any] | None = None,
    t_span: Any = (0.0, 1.0),
    num_points: int = 101,
    num_times: int = 21,
    method: str | None = None,
    dt: float | None = None,
    on_unstable: str = "adapt",
    exact_solution: str | None = None,
    probe_at: list[Any] | None = None,
    convergence_levels: int = 3,
) -> dict[str, Any]:
    """Solve a PDE on a rectangle and return the field with its verification (see the module docstring).

    The initial condition, initial velocity (wave), source and exact solution are expressions in x, y and t. A
    Dirichlet edge's value or a Neumann edge's outward normal derivative goes in `boundary_values` by edge name. An
    explicit step `dt` above the stability limit is reduced (`on_unstable="adapt"`) or refused ("refuse").
    """
    started = time.monotonic()
    limits = _limits()
    name = str(equation or "").strip().lower().replace("-", "_").replace(" ", "_")
    name = {"diffusion": "heat", "laplace": "poisson", "fisher": "fisher_kpp", "reaction_diffusion": "fisher_kpp",
            "advection": "advection_diffusion", "convection_diffusion": "advection_diffusion"}.get(name, name)
    if name not in EQUATIONS:
        raise ValueError(f"Unknown equation {equation!r}; expected one of {', '.join(EQUATIONS)}.")
    try:
        intervals = tuple((float(a), float(b)) for a, b in (domain or ((0.0, 1.0),)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"The domain must be one (low, high) interval per dimension, got {domain!r}.") from exc
    dim = int(dimension) if dimension is not None else len(intervals)
    if dim not in EQUATIONS[name]:
        raise ValueError(f"The {name} equation is solved in {' or '.join(f'{d}D' for d in EQUATIONS[name])}, not {dim}D.")
    if len(intervals) != dim:
        raise ValueError(f"A {dim}D domain needs {dim} interval(s), got {len(intervals)}.")
    points = int(num_points)
    cap = limits["grid_1d"] if dim == 1 else limits["grid_2d"]
    if points < MIN_POINTS:
        raise ValueError(f"A grid needs at least {MIN_POINTS} points per axis, got {points}.")
    if points**dim > cap:
        raise ValueError(f"A {dim}D grid of {points} points per axis has {points**dim} points, over the cap of {cap}.")
    policy = str(on_unstable or "adapt").strip().lower()
    if policy not in ("adapt", "refuse"):
        raise ValueError(f"on_unstable must be 'adapt' or 'refuse', got {on_unstable!r}.")
    if dt is not None and not (math.isfinite(float(dt)) and float(dt) > 0.0):
        raise ValueError(f"The time step dt must be positive, got {dt!r}.")

    resolved = resolve_parameters(name, parameters)
    scheme = resolve_method(name, method)
    edges = normalise_boundary(boundary, dim)
    if name == "poisson":
        times = np.array([0.0])
    else:
        t0, t1 = (float(v) for v in t_span)
        if not (math.isfinite(t0) and math.isfinite(t1)) or t1 <= t0:
            raise ValueError(f"The time span must be finite and increasing, got {tuple(t_span)!r}.")
        frames = min(max(2, int(num_times)), limits["snapshots"], MAX_SNAPSHOTS_2D if dim == 2 else limits["snapshots"])
        times = np.linspace(t0, t1, frames)
    setup = _Setup(
        equation=name, dimension=dim, domain=intervals, parameters=resolved, initial_condition=initial_condition,
        initial_velocity=initial_velocity, source=source, boundary=edges, boundary_values=boundary_values,
        exact_solution=exact_solution, times=times, method=scheme, dt=float(dt) if dt is not None else None,
        on_unstable=policy,
    )
    deadline = started + limits["seconds"]

    problem = setup.problem(points, deadline)
    raw = SOLVERS[name](problem)
    snapshots = [np.asarray(s, dtype=float) for s in raw["snapshots"]]
    grid = problem.grid
    warnings = list(problem.notes)

    # -- Convergence: the same problem on nested grids, the requested one among them --------------------------------
    counts = _study_levels(points, any(setup.periodic), dim, max(2, min(int(convergence_levels), limits["levels"])), cap)
    if any(setup.periodic) and not all(setup.periodic):
        # Mixed periodic and bounded axes refine differently; the counts are nested along the periodic rule only
        # when every axis follows it, so such a 2D problem is studied with its requested grid alone.
        counts = [points]
    fields: list[np.ndarray] = []
    level_grids: list[Grid] = []
    study_note = ""
    for n in counts:
        if n == points:
            fields.append(snapshots[-1])
            level_grids.append(grid)
            continue
        try:
            level = setup.problem(n, deadline)
            # The step shrinks with the mesh as the scheme's accuracy needs (h for leapfrog and Crank-Nicolson, h^2 for
            # explicit Euler), from the step the requested run used, so every level sees the same discretisation.
            if raw.get("steps_per_snapshot"):
                ratio = (level.grid.spacing[0] / grid.spacing[0]) ** int(raw.get("time_scaling", 1))
                level.steps_per = max(1, math.ceil(raw["steps_per_snapshot"] / ratio - 1e-9))
            fields.append(np.asarray(SOLVERS[name](level)["snapshots"][-1], dtype=float))
            level_grids.append(level.grid)
        except ConvergenceError as exc:
            study_note = f"The convergence study stopped at {len(fields)} level(s): {exc}"
            break
        except StabilityError as exc:
            study_note = f"A study level was skipped: {exc}"
            break
    if len(fields) >= 2:
        exact = [setup.exact_on(g, float(times[-1])) for g in level_grids] if setup.exact is not None else None
        convergence = convergence_table(
            [g.shape[0] for g in level_grids], [g.spacing[0] for g in level_grids], fields, exact,
            [g.shape[0] for g in level_grids].index(points), int(raw.get("expected_order", 2)),
        )
        if study_note:
            convergence["note"] = f"{convergence['note']} {study_note}".strip()
    else:
        convergence = {"levels": [], "order": None, "richardson_error": None, "converged": False,
                       "expected_order": int(raw.get("expected_order", 2)),
                       "note": study_note or "No nested grid fits the caps, so no convergence study was run."}

    verification = None
    if setup.exact is not None:
        exact_frames = [setup.exact_on(grid, float(t)) for t in times[: len(snapshots)]]
        verification = analytic_comparison(str(exact_solution), snapshots, exact_frames)
        if not verification["agrees"]:
            warnings.append(
                f"The solution differs from the given exact solution by {verification['relative_error']:.2%} of its size."
            )
    if not convergence.get("converged"):
        warnings.append("The mesh-convergence study does not show a converged solution; treat the field as unverified.")

    conservation = _conservation(setup, problem, raw)
    if conservation is not None and not conservation["conserved"]:
        warnings.append(f"The {conservation['kind']} drifted by {conservation['relative_drift']:.2e} (relative).")

    # -- Output: decimated snapshots and the reproducible spec ------------------------------------------------------
    keep = [_decimate(n, OUTPUT_POINTS_1D if dim == 1 else OUTPUT_POINTS_2D) for n in grid.shape]

    def shrink(field: np.ndarray) -> Any:
        return field[np.ix_(*keep)].tolist() if dim == 2 else field[keep[0]].tolist()

    result: dict[str, Any] = {
        "status": "ok",
        "equation": name,
        "dimension": dim,
        "domain": [list(i) for i in intervals],
        "parameters": resolved,
        "boundary": edges,
        "boundary_values": boundary_values or {},
        "method": scheme,
        "steady": name == "poisson",
        "t_span": [float(times[0]), float(times[-1])],
        "times": [float(t) for t in times[: len(snapshots)]],
        "grid": {"points": points, "spacing": list(grid.spacing), "shape": list(grid.shape),
                 "output_shape": [len(k) for k in keep], "periodic": list(setup.periodic)},
        "x": grid.axes[0][keep[0]].tolist(),
        "snapshots": [{"t": float(t), "values": shrink(s)} for t, s in zip(times, snapshots, strict=False)],
        "field": shrink(snapshots[-1]),
        "stability": raw.get("stability"),
        "convergence": convergence,
        "verification": verification,
        "conservation": conservation,
        "probes": _probes(probe_at, grid, snapshots),
        "range": [float(min(np.min(s) for s in snapshots)), float(max(np.max(s) for s in snapshots))],
        "warnings": warnings,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "spec": {
            "equation": name, "dimension": dim, "domain": [list(i) for i in intervals], "parameters": resolved,
            "initial_condition": initial_condition, "initial_velocity": initial_velocity, "source": source,
            "boundary": edges, "boundary_values": boundary_values or {}, "t_span": [float(times[0]), float(times[-1])],
            "num_points": points, "num_times": len(times), "method": scheme, "dt": setup.dt,
            "exact_solution": exact_solution,
        },
    }
    if dim == 2:
        result["y"] = grid.axes[1][keep[1]].tolist()
    return _jsonable(result)


__all__ = ["EQUATIONS", "METHODS", "ConvergenceError", "ExpressionError", "StabilityError", "solve_pde"]
