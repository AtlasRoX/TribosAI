"""The PDE solvers: heat, wave, Poisson, advection-diffusion, Fisher-KPP and Burgers.

Every solver works on the full grid. A Dirichlet node holds its prescribed value; a Neumann edge uses a ghost node, so
the centred second difference stays second order there; a periodic axis wraps. The schemes:

- heat: Crank-Nicolson (default, unconditionally stable), explicit Euler (stability-checked) or the method of lines;
- wave: leapfrog with a second-order start, Courant-checked;
- Poisson: one sparse direct solve;
- advection-diffusion, Fisher-KPP and Burgers: the method of lines with `solve_ivp`, BDF when the system is stiff.

An explicit time step above the stability limit is either refused or reduced (the "adapt" policy, the default), and
the stability number of the step actually used is always reported.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import integrate, sparse
from scipy.sparse import linalg as sparse_linalg

from .grid import BoundaryData, Grid, dirichlet_mask, dirichlet_values, neumann_forcing

# The equations this package solves, and the dimensions each is solved in.
EQUATIONS: dict[str, tuple[int, ...]] = {
    "heat": (1, 2),
    "wave": (1, 2),
    "poisson": (1, 2),
    "advection_diffusion": (1,),
    "fisher_kpp": (1,),
    "burgers": (1,),
}

# The parameters of each equation and their defaults; the aliases a caller may write them as.
DEFAULT_PARAMETERS: dict[str, dict[str, float]] = {
    "heat": {"alpha": 1.0},
    "wave": {"c": 1.0},
    "poisson": {},
    "advection_diffusion": {"v": 1.0, "D": 0.01},
    "fisher_kpp": {"r": 1.0, "D": 0.01},
    "burgers": {"nu": 0.01},
}
PARAMETER_ALIASES: dict[str, dict[str, str]] = {
    "heat": {"D": "alpha", "k": "alpha", "kappa": "alpha", "diffusivity": "alpha"},
    "wave": {"speed": "c", "wave_speed": "c"},
    "advection_diffusion": {"u": "v", "velocity": "v", "c": "v", "diffusivity": "D", "kappa": "D", "nu": "D"},
    "fisher_kpp": {"growth": "r", "rate": "r", "diffusivity": "D", "kappa": "D"},
    "burgers": {"viscosity": "nu", "mu": "nu"},
}

# The schemes each equation accepts; the first one is the default.
METHODS: dict[str, tuple[str, ...]] = {
    "heat": ("crank_nicolson", "explicit", "bdf"),
    "wave": ("leapfrog",),
    "poisson": ("direct",),
    "advection_diffusion": ("auto", "bdf", "rk45"),
    "fisher_kpp": ("auto", "bdf", "rk45"),
    "burgers": ("auto", "bdf", "rk45"),
}
METHOD_ALIASES = {"cn": "crank_nicolson", "crank-nicolson": "crank_nicolson", "implicit": "crank_nicolson",
                  "euler": "explicit", "ftcs": "explicit", "central": "leapfrog", "mol": "auto", "sparse": "direct",
                  "rk": "rk45", "lsoda": "auto"}

MAX_TIME_STEPS = 2_000_000  # time steps of one stepping solve, over the whole span


class StabilityError(ValueError):
    """The requested time step violates the stability limit of the explicit scheme (and the policy is to refuse)."""


class ConvergenceError(RuntimeError):
    """The solve failed or ran past its time limit."""


def resolve_parameters(equation: str, parameters: dict[str, Any] | None) -> dict[str, float]:
    """The equation's parameters: the caller's values (under any alias) over the defaults, plus any extra ones."""
    aliases = PARAMETER_ALIASES.get(equation, {})
    out = dict(DEFAULT_PARAMETERS[equation])
    for name, value in (parameters or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter {name!r} must be a number, got {value!r}.") from exc
        if not math.isfinite(number):
            raise ValueError(f"Parameter {name!r} must be finite, got {value!r}.")
        out[aliases.get(str(name), str(name))] = number
    for name in ("alpha", "D", "nu"):
        if name in DEFAULT_PARAMETERS[equation] and out[name] <= 0.0:
            raise ValueError(f"The diffusion coefficient {name} must be positive, got {out[name]}.")
    if equation == "wave" and out["c"] <= 0.0:
        raise ValueError(f"The wave speed c must be positive, got {out['c']}.")
    return out


def resolve_method(equation: str, method: str | None) -> str:
    allowed = METHODS[equation]
    name = str(method or allowed[0]).strip().lower().replace(" ", "_")
    name = METHOD_ALIASES.get(name, name)
    if name not in allowed:
        raise ValueError(f"The {equation} equation is solved with {', '.join(allowed)}; {method!r} is not one of them.")
    return name


@dataclass
class Problem:
    """Everything a solver needs: the grid, the boundary data, the fields and the time span."""

    equation: str
    grid: Grid
    boundary: dict[str, str]
    data: BoundaryData
    parameters: dict[str, float]
    initial: np.ndarray
    velocity: np.ndarray
    source: Callable[[float], np.ndarray] | None
    source_time_dependent: bool
    times: np.ndarray
    method: str
    dt: float | None = None
    steps_per: int | None = None  # time steps per snapshot interval, set by the convergence study
    on_unstable: str = "adapt"
    deadline: float = math.inf
    notes: list[str] = field(default_factory=list)

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline:
            raise ConvergenceError("The PDE solve exceeded its time limit. Use a coarser grid or a shorter span.")

    def f(self, t: float) -> np.ndarray:
        return self.source(t) if self.source is not None else np.zeros(self.grid.shape)


# -- Operators ---------------------------------------------------------------------------------------------------


def _second_difference(n: int, h: float, periodic: bool, left: str, right: str) -> sparse.csr_matrix:
    """The 1D second difference on n nodes: periodic wrap, a Neumann ghost row, or a (later overwritten) Dirichlet row."""
    main = np.full(n, -2.0)
    upper = np.ones(n - 1)
    lower = np.ones(n - 1)
    if not periodic:
        if left == "neumann":
            upper[0] = 2.0
        if right == "neumann":
            lower[-1] = 2.0
    matrix = sparse.diags([lower, main, upper], [-1, 0, 1], shape=(n, n), format="lil")
    if periodic:
        matrix[0, n - 1] = 1.0
        matrix[n - 1, 0] = 1.0
    return (matrix.tocsr() / h**2).tocsr()


def laplacian(grid: Grid, boundary: dict[str, str]) -> sparse.csr_matrix:
    """The discrete Laplacian on the full grid (a Kronecker sum in 2D), rows ordered like `field.ravel()`."""
    ops = [
        _second_difference(n, h, p, boundary[f"{axis}0"], boundary[f"{axis}1"])
        for n, h, p, axis in zip(grid.shape, grid.spacing, grid.periodic, ("x", "y"), strict=False)
    ]
    if grid.dimension == 1:
        return ops[0]
    nx, ny = grid.shape
    return (sparse.kron(ops[0], sparse.identity(ny)) + sparse.kron(sparse.identity(nx), ops[1])).tocsr()


def _with_dirichlet_rows(matrix: sparse.spmatrix, mask: np.ndarray, diagonal: float) -> sparse.csc_matrix:
    """The matrix with every Dirichlet row replaced by `diagonal` on the diagonal (1 for u = g, 0 to drop the row)."""
    keep = sparse.diags((~mask.ravel()).astype(float))
    fixed = sparse.diags(mask.ravel().astype(float) * diagonal)
    return (keep @ matrix + fixed).tocsc()


def _steps(problem: Problem, dt_target: float) -> tuple[int, float]:
    """Steps per snapshot interval and the step, so each snapshot falls exactly on a step."""
    interval = float(problem.times[1] - problem.times[0]) if len(problem.times) > 1 else 0.0
    if interval <= 0.0:
        return 0, 0.0
    per = problem.steps_per or max(1, math.ceil(interval / dt_target - 1e-9))
    if per * (len(problem.times) - 1) > MAX_TIME_STEPS:
        raise ConvergenceError(
            f"The run needs {per * (len(problem.times) - 1):,} time steps, more than the {MAX_TIME_STEPS:,} allowed. "
            "Use a coarser grid, a shorter span or a smaller diffusivity."
        )
    return per, interval / per


def _explicit_step(problem: Problem, number: Callable[[float], float], limit: float, name: str, scheme: str,
                   default_dt: float) -> tuple[int, float, dict[str, Any]]:
    """The step of an explicit scheme: the caller's dt if stable, else refused or reduced to a stable one."""
    requested = problem.dt
    dt = float(requested) if requested else default_dt
    status = "stable"
    if problem.steps_per is None and number(dt) > limit + 1e-12:
        if problem.on_unstable == "refuse":
            raise StabilityError(
                f"The {scheme} scheme is unstable for dt = {dt:.4g}: the {name} is {number(dt):.4g}, above the stability "
                f"(CFL) limit {limit:g}. Use dt <= {limit / number(dt) * dt:.4g}, or let the solver adapt the step."
            )
        requested_dt = dt
        dt = 0.9 * limit / number(dt) * dt
        status = "adapted"
        problem.notes.append(
            f"The requested time step {requested_dt:.4g} violates the stability limit ({name} {number(requested_dt):.3g} > "
            f"{limit:g}); it was reduced to {dt:.4g}."
        )
    per, used = _steps(problem, dt)
    if number(used) > limit + 1e-12:
        raise StabilityError(f"The {scheme} step {used:.4g} is above the stability limit ({name} {number(used):.3g}).")
    report = {
        "scheme": scheme, "name": name, "number": float(number(used)) if used else 0.0, "limit": limit,
        "status": status, "dt": used, "requested_dt": requested, "steps": per * (len(problem.times) - 1),
        "steps_per_snapshot": per,
    }
    return per, used, report


def _boundary_field(problem: Problem, t: float) -> np.ndarray:
    return dirichlet_values(problem.data, t, np.zeros(problem.grid.shape))


# -- Heat --------------------------------------------------------------------------------------------------------


def solve_heat(problem: Problem) -> dict[str, Any]:
    """u_t = alpha Laplacian(u) + f by Crank-Nicolson, explicit Euler or the method of lines."""
    if problem.method == "bdf":
        return _solve_method_of_lines(problem, lambda u, lap, _t: problem.parameters["alpha"] * lap)
    grid, alpha = problem.grid, problem.parameters["alpha"]
    lap = laplacian(grid, problem.boundary)
    mask = dirichlet_mask(grid, problem.boundary)
    inv_h2 = sum(1.0 / h**2 for h in grid.spacing)
    number = lambda dt: alpha * dt * inv_h2  # noqa: E731
    length = max(b - a for a, b in grid.domain)

    if problem.method == "explicit":
        per, dt, stability = _explicit_step(
            problem, number, 0.5, "diffusion number alpha*dt*sum(1/h^2)", "explicit Euler", 0.4 / (alpha * inv_h2)
        )
    else:
        # Crank-Nicolson is second order in time, so a step that shrinks with h keeps the time error at the order of
        # the space error; the scale h * L / alpha has the units of a time.
        per, dt = _steps(problem, problem.dt or 0.1 * min(grid.spacing) * length / alpha)
        stability = {
            "scheme": "Crank-Nicolson", "name": "diffusion number alpha*dt*sum(1/h^2)",
            "number": float(number(dt)) if dt else 0.0, "limit": None, "status": "unconditionally stable", "dt": dt,
            "requested_dt": problem.dt, "steps": per * (len(problem.times) - 1), "steps_per_snapshot": per,
        }
        identity = sparse.identity(grid.size, format="csr")
        lhs = sparse_linalg.splu(_with_dirichlet_rows(identity - 0.5 * dt * alpha * lap, mask, 1.0))
        rhs_matrix = _with_dirichlet_rows(identity + 0.5 * dt * alpha * lap, mask, 0.0).tocsr()

    u = problem.initial.copy()
    t = float(problem.times[0])
    u[mask] = _boundary_field(problem, t)[mask]
    forcing = (lambda s: alpha * neumann_forcing(problem.data, s) + problem.f(s))  # noqa: E731
    constant = not (problem.data.time_dependent or problem.source_time_dependent)
    g_now = forcing(t)
    snapshots = [u.copy()]
    for _ in range(len(problem.times) - 1):
        for _ in range(per):
            problem.check_deadline()
            g_next = g_now if constant else forcing(t + dt)
            if problem.method == "explicit":
                u = u + dt * (alpha * (lap @ u.ravel()).reshape(grid.shape) + g_now)
            else:
                rhs = (rhs_matrix @ u.ravel()).reshape(grid.shape) + 0.5 * dt * (g_now + g_next)
                # The Dirichlet rows of the system are u = g at the new time, which the neighbouring rows couple to.
                rhs[mask] = _boundary_field(problem, t + dt)[mask]
                u = lhs.solve(rhs.ravel()).reshape(grid.shape)
            t += dt
            g_now = g_next
            u[mask] = _boundary_field(problem, t)[mask]
        snapshots.append(u.copy())
    return {"snapshots": snapshots, "stability": stability, "expected_order": 2, "steps_per_snapshot": per,
            "time_scaling": 2 if problem.method == "explicit" else 1}


# -- Wave --------------------------------------------------------------------------------------------------------


def solve_wave(problem: Problem) -> dict[str, Any]:
    """u_tt = c^2 Laplacian(u) + f by leapfrog, with the discrete energy that the scheme conserves.

    The start uses the Taylor step u1 = u0 + dt v0 + dt^2/2 u_tt(0), so the scheme stays second order. The energy
    E = 1/2 |(u_{n+1} - u_n)/dt|^2 - c^2/2 <u_{n+1}, L u_n> (weighted by the quadrature weights) is the exact
    invariant of leapfrog with homogeneous boundary data and no source: its drift measures round-off only.
    """
    grid, c = problem.grid, problem.parameters["c"]
    lap = laplacian(grid, problem.boundary)
    mask = dirichlet_mask(grid, problem.boundary)
    inv_h = math.sqrt(sum(1.0 / h**2 for h in grid.spacing))
    per, dt, stability = _explicit_step(
        problem, lambda s: c * s * inv_h, 1.0, "Courant number c*dt*sqrt(sum(1/h^2))", "leapfrog", 0.5 / (c * inv_h)
    )
    weights = grid.weights()

    def accel(u: np.ndarray, t: float) -> np.ndarray:
        return c**2 * ((lap @ u.ravel()).reshape(grid.shape) + neumann_forcing(problem.data, t)) + problem.f(t)

    def energy(new: np.ndarray, old: np.ndarray) -> float:
        kinetic = 0.5 * float(np.sum(weights * ((new - old) / dt) ** 2))
        potential = -0.5 * c**2 * float(np.sum(weights * new * (lap @ old.ravel()).reshape(grid.shape)))
        return kinetic + potential

    t = float(problem.times[0])
    u = problem.initial.copy()
    u[mask] = _boundary_field(problem, t)[mask]
    snapshots = [u.copy()]
    energies: list[float] = []
    out = {"snapshots": snapshots, "stability": stability, "expected_order": 2, "energies": energies,
           "steps_per_snapshot": per, "time_scaling": 1}
    if per == 0:
        return out
    u_prev = u
    u = u_prev + dt * problem.velocity + 0.5 * dt**2 * accel(u_prev, t)
    t += dt
    u[mask] = _boundary_field(problem, t)[mask]
    energies.append(energy(u, u_prev))
    step = 1
    for _ in range(len(problem.times) - 1):
        while step < per * (len(snapshots)):
            problem.check_deadline()
            u_next = 2.0 * u - u_prev + dt**2 * accel(u, t)
            t += dt
            u_next[mask] = _boundary_field(problem, t)[mask]
            u_prev, u = u, u_next
            energies.append(energy(u, u_prev))
            step += 1
        snapshots.append(u.copy())
    return out


# -- Poisson -----------------------------------------------------------------------------------------------------


def solve_poisson(problem: Problem) -> dict[str, Any]:
    """-Laplacian(u) = f by one sparse direct solve.

    Dirichlet nodes take the identity row. Without any Dirichlet edge the solution is fixed only up to a constant:
    the data must then be compatible (the source integrates to the outward flux), and the zero-mean solution is
    returned, bordered with one Lagrange multiplier.
    """
    grid = problem.grid
    lap = laplacian(grid, problem.boundary)
    mask = dirichlet_mask(grid, problem.boundary)
    rhs = problem.f(0.0) + neumann_forcing(problem.data, 0.0)
    rhs[mask] = _boundary_field(problem, 0.0)[mask]
    matrix = _with_dirichlet_rows(-lap, mask, 1.0)
    notes: list[str] = []
    if not mask.any():
        weights = grid.weights().ravel()
        imbalance = float(weights @ rhs.ravel())
        scale = float(weights @ np.abs(rhs.ravel())) or 1.0
        if abs(imbalance) > 1e-6 * scale:
            raise ValueError(
                "The Poisson problem has no Dirichlet edge, so it needs compatible data: the source must integrate to "
                f"the outward flux through the boundary, but the imbalance is {imbalance:.4g}. Prescribe a value on "
                "at least one edge, or fix the data."
            )
        # The weighted operator is symmetric; bordering it with the weights pins the mean to zero.
        weighted = sparse.diags(weights) @ matrix
        bordered = sparse.bmat([[weighted, weights.reshape(-1, 1)], [weights.reshape(1, -1), None]], format="csc")
        solution = sparse_linalg.spsolve(bordered, np.append(weights * rhs.ravel(), 0.0))[:-1]
        notes.append("No edge prescribes a value, so the solution is unique only up to a constant; the zero-mean one is shown.")
    else:
        solution = sparse_linalg.spsolve(matrix, rhs.ravel())
    solution = np.asarray(solution, dtype=float)
    if not np.all(np.isfinite(solution)):
        raise ConvergenceError("The sparse Poisson solve did not produce a finite solution.")
    residual = float(np.max(np.abs(matrix @ solution - rhs.ravel()))) if mask.any() else None
    problem.notes.extend(notes)
    return {
        "snapshots": [solution.reshape(grid.shape)],
        "stability": {"scheme": "sparse direct solve (5-point Laplacian)" if grid.dimension == 2
                      else "sparse direct solve (3-point Laplacian)", "name": None, "number": None, "limit": None,
                      "status": "steady", "residual": residual},
        "expected_order": 2,
    }


# -- Method of lines ---------------------------------------------------------------------------------------------


def _solve_method_of_lines(
    problem: Problem,
    rate: Callable[[np.ndarray, np.ndarray, float], np.ndarray],
    *,
    spectral_radius: float | None = None,
    scheme_note: str = "",
    expected_order: int = 2,
) -> dict[str, Any]:
    """Integrate u_t = rate(u, Laplacian(u) + Neumann term, t) + f on the free (non-Dirichlet) nodes with solve_ivp.

    "auto" picks BDF when the system is stiff (the explicit stable step would be far smaller than the span) and
    RK45 otherwise. The Jacobian is sparse with the Laplacian's pattern, which BDF uses to stay cheap.
    """
    grid = problem.grid
    lap = laplacian(grid, problem.boundary)
    mask = dirichlet_mask(grid, problem.boundary)
    free = ~mask.ravel()
    span = float(problem.times[-1] - problem.times[0])
    rho = spectral_radius if spectral_radius is not None else 4.0 * max(
        problem.parameters.get("alpha", 0.0), problem.parameters.get("D", 0.0), problem.parameters.get("nu", 0.0)
    ) * sum(1.0 / h**2 for h in grid.spacing)
    method = problem.method
    if method in ("auto", "bdf"):
        method = "bdf" if problem.method == "bdf" or rho * span > 500.0 else "rk45"

    def full(t: float, y: np.ndarray) -> np.ndarray:
        u = _boundary_field(problem, t).ravel()
        u[free] = y
        return u.reshape(grid.shape)

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        problem.check_deadline()
        u = full(t, y)
        lap_u = (lap @ u.ravel()).reshape(grid.shape) + neumann_forcing(problem.data, t)
        return (rate(u, lap_u, t) + problem.f(t)).ravel()[free]

    t0 = float(problem.times[0])
    u0 = problem.initial.copy()
    u0[mask] = _boundary_field(problem, t0)[mask]
    if span <= 0.0:
        return {"snapshots": [u0], "stability": {"scheme": "method of lines", "status": "no time span"},
                "expected_order": expected_order}
    pattern = (abs(lap) + sparse.identity(grid.size)).tocsr()[free][:, free]
    scale = max(1.0, float(np.max(np.abs(u0))))
    kwargs: dict[str, Any] = {"rtol": 1e-8, "atol": 1e-10 * scale}
    if method == "bdf":
        kwargs["jac_sparsity"] = pattern
    try:
        solution = integrate.solve_ivp(rhs, (t0, float(problem.times[-1])), u0.ravel()[free],
                                       method="BDF" if method == "bdf" else "RK45", t_eval=problem.times, **kwargs)
    except ConvergenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConvergenceError(f"The method-of-lines integration failed: {exc}") from exc
    if not solution.success or solution.y.shape[1] != len(problem.times):
        raise ConvergenceError(f"The method-of-lines integration failed: {solution.message}")
    snapshots = [full(float(t), solution.y[:, i]) for i, t in enumerate(problem.times)]
    stability = {
        "scheme": f"method of lines, {'BDF (stiff)' if method == 'bdf' else 'RK45 (adaptive)'}{scheme_note}",
        "name": "stiffness rho*T (explicit spectral radius times span)", "number": float(rho * span), "limit": None,
        "status": "adaptive integrator", "rhs_evaluations": int(solution.nfev),
    }
    return {"snapshots": snapshots, "stability": stability, "expected_order": expected_order}


def _gradient_1d(u: np.ndarray, problem: Problem, t: float, upwind_speed: float | None = None) -> np.ndarray:
    """du/dx on a 1D grid: centred, or first-order upwind for the given sign of the speed.

    At a Neumann edge the derivative is the prescribed one (the outward derivative is -du/dx on the left edge).
    """
    h = problem.grid.spacing[0]
    if problem.grid.periodic[0]:
        left, right = np.roll(u, 1), np.roll(u, -1)
    else:
        left = np.concatenate(([u[0]], u[:-1]))
        right = np.concatenate((u[1:], [u[-1]]))
    if upwind_speed is None:
        du = (right - left) / (2.0 * h)
    elif upwind_speed >= 0.0:
        du = (u - left) / h
    else:
        du = (right - u) / h
    if not problem.grid.periodic[0]:
        for edge, index, sign in (("x0", 0, -1.0), ("x1", -1, 1.0)):
            if problem.boundary[edge] == "neumann":
                du[index] = sign * float(problem.data.values(edge, t)[0])
    return du


def solve_advection_diffusion(problem: Problem) -> dict[str, Any]:
    """u_t + v u_x = D u_xx + f by the method of lines.

    Centred advection is second order but oscillates when the cell Peclet number |v| h / D exceeds 2; there the
    first-order upwind difference is used instead, and the result says so.
    """
    v, d = problem.parameters["v"], problem.parameters["D"]
    h = problem.grid.spacing[0]
    peclet = abs(v) * h / d
    upwind = peclet > 2.0
    if upwind:
        problem.notes.append(
            f"The cell Peclet number |v| h / D = {peclet:.3g} exceeds 2, so the advection term uses first-order upwind "
            "differences (centred ones would oscillate); expect first-order convergence and some numerical diffusion."
        )

    def rate(u: np.ndarray, lap_u: np.ndarray, t: float) -> np.ndarray:
        return d * lap_u - v * _gradient_1d(u, problem, t, v if upwind else None)

    out = _solve_method_of_lines(
        problem, rate, spectral_radius=4.0 * d / h**2 + abs(v) / h,
        scheme_note=", upwind advection" if upwind else ", centred advection", expected_order=1 if upwind else 2,
    )
    out["stability"]["cell_peclet"] = float(peclet)
    return out


def solve_fisher_kpp(problem: Problem) -> dict[str, Any]:
    """Fisher-KPP u_t = D u_xx + r u (1 - u) + f by the method of lines (BDF when stiff)."""
    r, d = problem.parameters["r"], problem.parameters["D"]
    h = problem.grid.spacing[0]
    return _solve_method_of_lines(
        problem, lambda u, lap_u, _t: d * lap_u + r * u * (1.0 - u), spectral_radius=4.0 * d / h**2 + abs(r),
    )


def solve_burgers(problem: Problem) -> dict[str, Any]:
    """Viscous Burgers u_t + (u^2/2)_x = nu u_xx + f by the method of lines, in conservative form.

    The flux difference is centred while the cell Reynolds number max|u| h / nu is at most 2, and the Rusanov
    (local Lax-Friedrichs) flux above that, which is first order but cannot oscillate. Both are conservative, so the
    mass is conserved exactly on a periodic domain.
    """
    nu = problem.parameters["nu"]
    grid = problem.grid
    h = grid.spacing[0]
    speed = float(np.max(np.abs(problem.initial))) if problem.initial.size else 0.0
    reynolds = speed * h / nu
    rusanov = reynolds > 2.0
    if rusanov:
        problem.notes.append(
            f"The cell Reynolds number max|u| h / nu = {reynolds:.3g} exceeds 2, so the flux is the first-order Rusanov "
            "flux (centred fluxes would oscillate); expect first-order convergence."
        )

    def ghosts(u: np.ndarray, t: float) -> np.ndarray:
        if grid.periodic[0]:
            return np.concatenate(([u[-1]], u, [u[0]]))
        left = u[1] + 2.0 * h * float(problem.data.values("x0", t)[0]) if problem.boundary["x0"] == "neumann" else u[0]
        right = u[-2] + 2.0 * h * float(problem.data.values("x1", t)[0]) if problem.boundary["x1"] == "neumann" else u[-1]
        return np.concatenate(([left], u, [right]))

    def rate(u: np.ndarray, lap_u: np.ndarray, t: float) -> np.ndarray:
        ext = ghosts(u, t)
        flux = 0.5 * ext**2
        if rusanov:
            a = np.maximum(np.abs(ext[:-1]), np.abs(ext[1:]))
            face = 0.5 * (flux[:-1] + flux[1:]) - 0.5 * a * (ext[1:] - ext[:-1])
        else:
            face = 0.5 * (flux[:-1] + flux[1:])
        return nu * lap_u - (face[1:] - face[:-1]) / h

    out = _solve_method_of_lines(
        problem, rate, spectral_radius=4.0 * nu / h**2 + 2.0 * speed / h,
        scheme_note=", Rusanov flux" if rusanov else ", centred conservative flux", expected_order=1 if rusanov else 2,
    )
    out["stability"]["cell_reynolds"] = float(reynolds)
    return out


SOLVERS: dict[str, Callable[[Problem], dict[str, Any]]] = {
    "heat": solve_heat,
    "wave": solve_wave,
    "poisson": solve_poisson,
    "advection_diffusion": solve_advection_diffusion,
    "fisher_kpp": solve_fisher_kpp,
    "burgers": solve_burgers,
}


__all__ = [
    "DEFAULT_PARAMETERS",
    "EQUATIONS",
    "METHODS",
    "SOLVERS",
    "ConvergenceError",
    "Problem",
    "StabilityError",
    "laplacian",
    "resolve_method",
    "resolve_parameters",
]
