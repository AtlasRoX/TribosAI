"""
Interactive re-runs of a Dynamis ODE simulation: the inputs ("spec") a result card explores with sliders, a bifurcation
(orbit) diagram over one parameter, and the vector field of a 2D system or a 2D projection.

Expressions only ever go through the Dynamis engine's allowlist parser (tribos.axiom.engine.safe_parse_expr): the
time course is the engine's own dynamis_simulate_ode, and the sweep and vector-field helpers compile the same RHS the
same way. Every entry point validates the spec and enforces hard caps on its work (states, points, sweep steps, grid
size); the sweep and vector field also stop cooperatively at a deadline (time.monotonic()) so an API timeout really
ends the computation instead of leaving it running.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import sympy as sp
from scipy import integrate

from tribos.axiom.engine import safe_parse_expr
from tribos.dynamis.engine import ODE_PRESETS, dynamis_simulate_ode

MAX_STATES = 12
MAX_PARAMETERS = 64
MAX_EXPR_CHARS = 500
MAX_NUM_POINTS = 2000
MAX_BIFURCATION_STEPS = 200
MAX_VECTOR_FIELD_N = 25
MAX_EXTREMA_PER_VALUE = 64
MAX_ABS_VALUE = 1e15
MAX_DURATION = 1e6
METHODS = ("RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA")
# A batched sweep integrates several parameter values as one system; its post-transient samples are capped at about
# this many floats in memory, and each value is sampled at most BIFURCATION_SAMPLES times.
_SWEEP_FLOAT_BUDGET = 4_000_000
BIFURCATION_SAMPLES = 4000
_MAX_RHS_EVALS = 400_000  # per batch: an integration that needs more is stopped (stiff or blowing up)

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class SpecError(ValueError):
    """The spec or request is invalid; the message is safe to show to the user."""


class DeadlineExceeded(RuntimeError):
    """The computation passed its deadline."""


# ---------------------------------------------------------------------------------------------------------------
# Spec resolution and validation
# ---------------------------------------------------------------------------------------------------------------


def _finite(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SpecError(f"{what} must be a number.") from None
    if not math.isfinite(out) or abs(out) > MAX_ABS_VALUE:
        raise SpecError(f"{what} must be a finite number with magnitude at most {MAX_ABS_VALUE:g}.")
    return out


def _name(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not _NAME_RE.match(text):
        raise SpecError(f"{what} {value!r} is not a valid name (letters, digits and _; at most 64 characters).")
    return text


def _number_map(raw: Any, what: str, limit: int) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise SpecError(f"{what} must be an object of name -> number.")
    if len(raw) > limit:
        raise SpecError(f"{what} has {len(raw)} entries; at most {limit} are allowed.")
    return {_name(k, f"{what} name"): _finite(v, f"{what}[{k!r}]") for k, v in raw.items()}


def preset_spec(model_name: str) -> dict[str, Any]:
    """The full spec of an ODE preset (ODE_PRESETS) by name, case-insensitive."""
    key = str(model_name or "").strip().lower()
    if key not in ODE_PRESETS:
        raise SpecError(f"Unknown ODE preset {model_name!r}. Available presets: {', '.join(sorted(ODE_PRESETS))}.")
    preset = ODE_PRESETS[key]
    return {
        "rhs": dict(preset["rhs"]),
        "parameters": {k: float(v) for k, v in (preset.get("parameters") or {}).items()},
        "initial_state": {k: float(v) for k, v in preset["initial_state"].items()},
        "t_span": [float(preset.get("t_span", (0.0, 10.0))[0]), float(preset.get("t_span", (0.0, 10.0))[1])],
        "method": "RK45",
        "model_name": key,
    }


def resolve_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """A validated, complete spec {rhs, parameters, initial_state, t_span, method, model_name}.

    A model_name without an rhs is resolved from ODE_PRESETS (results stored before the spec was recorded carry only
    the preset name); given fields override the preset's. Initial values of variables that are not states are dropped.
    """
    if not isinstance(spec, Mapping):
        raise SpecError("The simulation spec must be an object.")
    model_name = spec.get("model_name")
    model_name = str(model_name).strip() if model_name not in (None, "") else None
    base: dict[str, Any] = {}
    if model_name and (model_name.lower() in ODE_PRESETS or not spec.get("rhs")):
        # A preset supplies every field not given; a name without an rhs must be a preset. With its own rhs, an
        # unknown name is only the model's label.
        base = preset_spec(model_name)
        model_name = base["model_name"]
    elif model_name:
        model_name = model_name[:64]

    rhs_raw = spec.get("rhs") or base.get("rhs")
    if not rhs_raw:
        raise SpecError("The spec needs an rhs (state -> derivative expression) or a known model_name.")
    if not isinstance(rhs_raw, Mapping):
        raise SpecError("rhs must be an object of state variable -> derivative expression.")
    if len(rhs_raw) > MAX_STATES:
        raise SpecError(f"The system has {len(rhs_raw)} state variables; at most {MAX_STATES} are allowed here.")
    rhs: dict[str, str] = {}
    for key, expr in rhs_raw.items():
        name = _name(key, "State variable")
        if not isinstance(expr, str | int | float) or isinstance(expr, bool):
            raise SpecError(f"The derivative of {name!r} must be an expression string.")
        text = str(expr).strip()
        if not text or len(text) > MAX_EXPR_CHARS:
            raise SpecError(f"The derivative of {name!r} must be 1 to {MAX_EXPR_CHARS} characters.")
        rhs[name] = text

    parameters = dict(base.get("parameters") or {})
    parameters.update(_number_map(spec.get("parameters"), "parameters", MAX_PARAMETERS))
    initial = dict(base.get("initial_state") or {})
    initial.update(_number_map(spec.get("initial_state"), "initial_state", MAX_STATES * 4))
    missing = [n for n in rhs if n not in initial]
    if missing:
        raise SpecError(f"initial_state is missing a value for {', '.join(missing)}.")
    initial = {n: initial[n] for n in rhs}

    span_raw = spec.get("t_span") or base.get("t_span") or [0.0, 10.0]
    if not isinstance(span_raw, list | tuple) or len(span_raw) != 2:
        raise SpecError("t_span must be [start, end].")
    t0, t1 = _finite(span_raw[0], "t_span start"), _finite(span_raw[1], "t_span end")
    if t1 <= t0:
        raise SpecError(f"t_span end ({t1:g}) must be greater than its start ({t0:g}).")
    if t1 - t0 > MAX_DURATION:
        raise SpecError(f"The time span may be at most {MAX_DURATION:g} long.")

    method = str(spec.get("method") or base.get("method") or "RK45").strip()
    match = next((m for m in (*METHODS, "RK4") if m.lower() == method.lower()), None)
    if match is None:
        raise SpecError(f"Unknown integration method {method!r}; use one of {', '.join(METHODS)}.")
    fixed: dict[str, Any] = {}
    if match == "RK4":
        if spec.get("step_size") is None and spec.get("num_steps") is None:
            raise SpecError("Fixed-step RK4 needs the original step_size or num_steps; it was not replaced by RK45.")
        if spec.get("step_size") is not None:
            h = _finite(spec["step_size"], "step_size")
            if h <= 0:
                raise SpecError("step_size must be positive.")
            fixed["step_size"] = h
        if spec.get("num_steps") is not None:
            count = spec["num_steps"]
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 9999:
                raise SpecError("num_steps must be an integer from 1 to 9999.")
            fixed["num_steps"] = count
    return {
        "rhs": rhs,
        "parameters": parameters,
        "initial_state": initial,
        "t_span": [t0, t1],
        "method": match,
        "model_name": model_name,
        **fixed,
    }


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise DeadlineExceeded("The computation passed its time limit.")


def _clean(value: Any) -> Any:
    """JSON-safe copy: non-finite floats become None (the API's JSON encoder refuses NaN and infinity)."""
    if isinstance(value, float | np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple | np.ndarray):
        return [_clean(v) for v in value]
    return value


def _clean_result(result: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = _clean(result)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Time course (the engine's own simulation)
# ---------------------------------------------------------------------------------------------------------------


def simulate(spec: Mapping[str, Any], num_points: int = 400, deadline: float | None = None) -> dict[str, Any]:
    """dynamis_simulate_ode for a spec, with the resolved spec attached as result["spec"]."""
    resolved = resolve_spec(spec)
    n_pts = int(num_points)
    if not 2 <= n_pts <= MAX_NUM_POINTS:
        raise SpecError(f"num_points must be between 2 and {MAX_NUM_POINTS}.")
    _check_deadline(deadline)
    name = resolved["model_name"]
    # The preset name is passed only when the RHS is the preset's own, so its conservation check (invariant) applies;
    # t_span goes in as a list, which the engine never mistakes for its "default span, use the preset's" tuple.
    same_model = bool(name) and ODE_PRESETS.get(name, {}).get("rhs") == resolved["rhs"]
    result = dynamis_simulate_ode(
        rhs=dict(resolved["rhs"]),
        initial_state=dict(resolved["initial_state"]),
        t_span=list(resolved["t_span"]),  # type: ignore[arg-type]
        parameters=dict(resolved["parameters"]),
        method=resolved["method"],
        num_points=n_pts,
        model_name=name if same_model else None,
        **{k: resolved[k] for k in ("step_size", "num_steps") if k in resolved},
    )
    result["model_name"] = name
    result["spec"] = resolved
    return _clean_result(result)


# ---------------------------------------------------------------------------------------------------------------
# Compiled RHS shared by the sweep and the vector field
# ---------------------------------------------------------------------------------------------------------------


def _compile_rhs(
    rhs: Mapping[str, str], parameters: Mapping[str, float], free: tuple[str, ...] = ()
) -> Callable[..., np.ndarray]:
    """f(t, Y, *free_values) -> dY with Y of shape (n_states, ...), vectorised over the trailing axes.

    Parameters named in `free` stay symbols (the swept parameter); every other symbol must be a state, a parameter or
    t. Expressions are parsed by the engine's allowlist parser.
    """
    state_names = list(rhs)
    t_sym = sp.Symbol("t")
    state_syms = [sp.Symbol(n) for n in state_names]
    env: dict[str, Any] = {"t": t_sym, **dict(zip(state_names, state_syms, strict=True))}
    free_syms = [sp.Symbol(n) for n in free]
    subs: dict[sp.Symbol, float] = {}
    for pname, pval in parameters.items():
        sym = sp.Symbol(pname)
        env[pname] = sym
        if pname not in free:
            subs[sym] = float(pval)
    allowed = {t_sym, *state_syms, *free_syms}
    exprs = []
    for name in state_names:
        expr = safe_parse_expr(rhs[name], local_dict=env)
        if subs:
            expr = expr.subs(subs)
        unresolved = expr.free_symbols - allowed
        if unresolved:
            raise SpecError(f"Unresolved parameter(s) in the derivative of {name!r}: {sorted(map(str, unresolved))}")
        exprs.append(expr)
    fn = sp.lambdify((t_sym, state_syms, *free_syms), exprs, modules="numpy")

    def f(t: float, y: np.ndarray, *free_values: Any) -> np.ndarray:
        with np.errstate(all="ignore"):
            vals = fn(t, y, *free_values)
        shape = np.shape(y)[1:]
        return np.stack([np.broadcast_to(np.asarray(v, dtype=float), shape) for v in vals])

    return f


# ---------------------------------------------------------------------------------------------------------------
# Bifurcation (orbit) diagram
# ---------------------------------------------------------------------------------------------------------------


def local_extrema(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local maxima and minima of a sampled series, each refined by a parabola through it and its neighbours."""
    y = np.asarray(y, dtype=float)
    if y.size < 3:
        return np.empty(0), np.empty(0)
    a, b, c = y[:-2], y[1:-1], y[2:]
    out = []
    for mask in ((b > a) & (b >= c), (b < a) & (b <= c)):
        idx = np.nonzero(mask)[0]
        aa, bb, cc = a[idx], b[idx], c[idx]
        denom = aa - 2 * bb + cc
        with np.errstate(divide="ignore", invalid="ignore"):
            refined = np.where(np.abs(denom) > 1e-300, bb - (aa - cc) ** 2 / (8 * denom), bb)
        out.append(refined[np.isfinite(refined)])
    return out[0], out[1]


def distinct_levels(values: np.ndarray, tol: float, cap: int = MAX_EXTREMA_PER_VALUE) -> list[float]:
    """The distinct levels among `values` (sorted; neighbours closer than tol merge into their mean), at most `cap`
    of them (evenly thinned beyond that)."""
    vals = np.sort(np.asarray(values, dtype=float))
    if vals.size == 0:
        return []
    groups: list[list[float]] = [[float(vals[0])]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(float(v))
        else:
            groups.append([float(v)])
    levels = [float(np.mean(g)) for g in groups]
    if len(levels) > cap:
        keep = np.unique(np.linspace(0, len(levels) - 1, cap).round().astype(int))
        levels = [levels[i] for i in keep]
    return levels


def _orbit_point(value: float, series: np.ndarray, status: str = "ok") -> dict[str, Any]:
    finite = series[np.isfinite(series)]
    if status != "ok" or finite.size < 3:
        return {"value": float(value), "maxima": [], "minima": [], "final": None, "n_maxima": 0,
                "status": status if status != "ok" else "failed"}
    lo, hi = float(np.min(finite)), float(np.max(finite))
    final = float(finite[-1])
    scale = max(abs(lo), abs(hi), 1e-12)
    if hi - lo <= 1e-7 * max(1.0, scale):
        # Settled on an equilibrium: no oscillation to report, the level itself is the branch.
        return {"value": float(value), "maxima": [], "minima": [], "final": final, "n_maxima": 0, "status": "ok",
                "steady": True}
    maxima, minima = local_extrema(finite)
    tol = max(1e-9 * scale, 1e-4 * (hi - lo))
    return {
        "value": float(value),
        "maxima": distinct_levels(maxima, tol),
        "minima": distinct_levels(minima, tol),
        "final": final,
        "n_maxima": int(maxima.size),
        "status": "ok",
        "steady": False,
    }


def bifurcation(
    spec: Mapping[str, Any],
    parameter: str,
    start: float,
    stop: float,
    steps: int = 100,
    observable: str | None = None,
    transient_fraction: float = 0.5,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Orbit diagram: for each of `steps` values of `parameter` in [start, stop], integrate the system over t_span from
    the spec's initial state, drop the first transient_fraction of the span, and record the distinct local maxima and
    minima of `observable` (a state variable). One distinct maximum is a period-1 orbit, two a period-2 orbit, many a
    chaotic or quasi-periodic one; none means the run settled on an equilibrium ("final" is that level).

    Values are integrated in batches as one vectorised system (much faster than one solve per value); a batch that
    fails is retried value by value so one diverging value does not lose its neighbours. Past the deadline the sweep
    stops and returns the values done so far with truncated=True.
    """
    started = time.monotonic()
    resolved = resolve_spec(spec)
    if resolved["method"] == "RK4":
        raise SpecError("The bifurcation sweep uses adaptive integration; select that method explicitly for exploration. The original fixed-step result was not changed.")
    param = _name(parameter, "Parameter")
    if param not in resolved["parameters"]:
        raise SpecError(f"{param!r} is not a parameter of this model ({', '.join(resolved['parameters']) or 'none'}).")
    p0, p1 = _finite(start, "start"), _finite(stop, "stop")
    if p0 == p1:
        raise SpecError("start and stop must differ.")
    n_steps = int(steps)
    if not 2 <= n_steps <= MAX_BIFURCATION_STEPS:
        raise SpecError(f"steps must be between 2 and {MAX_BIFURCATION_STEPS}.")
    states = list(resolved["rhs"])
    obs = _name(observable, "Observable") if observable else states[0]
    if obs not in states:
        raise SpecError(f"The observable {obs!r} is not a state variable ({', '.join(states)}).")
    frac = float(transient_fraction)
    if not 0.0 <= frac <= 0.95:
        raise SpecError("transient_fraction must be between 0 and 0.95.")

    f = _compile_rhs(resolved["rhs"], resolved["parameters"], free=(param,))
    t0, t1 = resolved["t_span"]
    t_cut = t0 + frac * (t1 - t0)
    n_states = len(states)
    obs_idx = states.index(obs)
    samples = BIFURCATION_SAMPLES
    batch = max(1, min(n_steps, _SWEEP_FLOAT_BUDGET // (samples * n_states)))
    t_eval = np.linspace(t_cut, t1, samples)
    y0 = np.array([resolved["initial_state"][s] for s in states], dtype=float)
    values = np.linspace(p0, p1, n_steps)
    method = resolved["method"]

    def integrate_values(pvals: np.ndarray) -> np.ndarray | None:
        """Observable samples of shape (len(pvals), samples), or None when the integration failed."""
        m = len(pvals)
        evals = [0]

        def rhs_fn(t: float, yflat: np.ndarray) -> np.ndarray:
            evals[0] += 1
            if evals[0] % 64 == 0:
                _check_deadline(deadline)
            if evals[0] > _MAX_RHS_EVALS:
                raise RuntimeError("too many right-hand-side evaluations")
            return f(t, yflat.reshape(n_states, m), pvals).ravel()

        try:
            sol = integrate.solve_ivp(rhs_fn, (t0, t1), np.repeat(y0, m), method=method, t_eval=t_eval,
                                      rtol=1e-6, atol=1e-9)
        except DeadlineExceeded:
            raise
        except Exception:  # noqa: BLE001 - a failing integration is reported per value, not raised
            return None
        if not sol.success or sol.y.shape[1] != samples:
            return None
        ys = sol.y.reshape(n_states, m, samples)[obs_idx]
        return ys if np.all(np.isfinite(ys)) else None

    points: list[dict[str, Any]] = []
    truncated = False
    try:
        for i in range(0, n_steps, batch):
            _check_deadline(deadline)
            chunk = values[i:i + batch]
            ys = integrate_values(chunk)
            if ys is not None:
                points.extend(_orbit_point(v, ys[j]) for j, v in enumerate(chunk))
                continue
            for v in chunk:
                _check_deadline(deadline)
                one = integrate_values(np.array([v]))
                points.append(_orbit_point(v, one[0]) if one is not None else _orbit_point(v, np.empty(0), "failed"))
    except DeadlineExceeded:
        truncated = True

    return _clean_result({
        "parameter": param,
        "observable": obs,
        "values": [p["value"] for p in points],
        "points": points,
        "start": p0,
        "stop": p1,
        "steps": n_steps,
        "transient_fraction": frac,
        "window": [t_cut, t1],
        "samples_per_value": samples,
        "method": method,
        "truncated": truncated,
        "elapsed_s": round(time.monotonic() - started, 3),
        "spec": resolved,
        "note": "Each value starts from the spec's initial state; extrema are taken after the transient and merged "
                "when closer than 1e-4 of the observable's range.",
    })


# ---------------------------------------------------------------------------------------------------------------
# Vector field
# ---------------------------------------------------------------------------------------------------------------


def vector_field(
    spec: Mapping[str, Any],
    x_var: str,
    y_var: str,
    x_range: tuple[float, float] | list[float],
    y_range: tuple[float, float] | list[float],
    n: int = 15,
    t: float | None = None,
    fixed: Mapping[str, float] | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """(dx/dt, dy/dt) on an n x n grid of the (x_var, y_var) plane. For a system with more than two states this is a
    projection: the other states are held at `fixed` (default: the spec's initial state), and t at `t` (default: the
    start of t_span) for a non-autonomous system. u[j][i], v[j][i] belong to the point (x[i], y[j])."""
    resolved = resolve_spec(spec)
    states = list(resolved["rhs"])
    xv, yv = _name(x_var, "x_var"), _name(y_var, "y_var")
    for v in (xv, yv):
        if v not in states:
            raise SpecError(f"{v!r} is not a state variable ({', '.join(states)}).")
    if xv == yv:
        raise SpecError("x_var and y_var must be different state variables.")
    size = int(n)
    if not 2 <= size <= MAX_VECTOR_FIELD_N:
        raise SpecError(f"n must be between 2 and {MAX_VECTOR_FIELD_N}.")
    ranges = []
    for rng, what in ((x_range, "x_range"), (y_range, "y_range")):
        if not isinstance(rng, list | tuple) or len(rng) != 2:
            raise SpecError(f"{what} must be [min, max].")
        lo, hi = _finite(rng[0], f"{what} min"), _finite(rng[1], f"{what} max")
        if hi <= lo:
            raise SpecError(f"{what} max must be greater than its min.")
        ranges.append((lo, hi))
    held = dict(resolved["initial_state"])
    held.update({k: v for k, v in _number_map(fixed, "fixed", MAX_STATES).items() if k in held})
    t_at = _finite(t, "t") if t is not None else resolved["t_span"][0]
    _check_deadline(deadline)

    f = _compile_rhs(resolved["rhs"], resolved["parameters"])
    xs = np.linspace(*ranges[0], size)
    ys = np.linspace(*ranges[1], size)
    gx, gy = np.meshgrid(xs, ys)  # rows follow y, columns follow x
    grid = np.stack([gx if s == xv else gy if s == yv else np.full_like(gx, held[s]) for s in states])
    d = f(t_at, grid)
    u, v = d[states.index(xv)], d[states.index(yv)]
    mag = np.hypot(u, v)
    return _clean_result({
        "x_var": xv,
        "y_var": yv,
        "x": xs.tolist(),
        "y": ys.tolist(),
        "u": u.tolist(),
        "v": v.tolist(),
        "n": size,
        "t": t_at,
        "held": {k: val for k, val in held.items() if k not in (xv, yv)},
        "projection": len(states) > 2,
        "max_magnitude": float(np.nanmax(mag)) if np.any(np.isfinite(mag)) else None,
    })


__all__ = [
    "DeadlineExceeded",
    "MAX_BIFURCATION_STEPS",
    "MAX_NUM_POINTS",
    "MAX_VECTOR_FIELD_N",
    "SpecError",
    "bifurcation",
    "distinct_levels",
    "local_extrema",
    "preset_spec",
    "resolve_spec",
    "simulate",
    "vector_field",
]
