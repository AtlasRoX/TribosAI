"""Least-squares ODE calibration using Dynamis' safe integrator and local covariance diagnostics."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

TIME_COLUMNS = ("t", "time", "elapsed", "elapsed_time", "seconds", "time_s")
MAX_ROWS = 5000


def load_measurements(path: str) -> pd.DataFrame:
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix in (".csv", ".tsv"):
        frame = pd.read_csv(file, sep="\t" if suffix == ".tsv" else ",", nrows=MAX_ROWS + 1)
    elif suffix == ".xlsx":
        frame = pd.read_excel(file, nrows=MAX_ROWS + 1)
    elif suffix in (".h5", ".hdf5"):
        import h5py
        from tribos.datasets.validators import check_hdf5_structure

        with h5py.File(file, "r") as handle:
            check_hdf5_structure(handle)
            columns = {}
            def collect(name: str, item: Any) -> None:
                if isinstance(item, h5py.Dataset) and item.ndim in (1, 2) and item.size <= MAX_ROWS:
                    values = np.asarray(item).squeeze()
                    if values.ndim == 1 and values.dtype.kind in "fiu":
                        columns[name] = values
            handle.visititems(collect)
        frame = pd.DataFrame(columns)
    elif suffix == ".mat":
        import h5py
        from scipy.io import loadmat, whosmat

        if h5py.is_hdf5(file):
            # MATLAB 7.3 uses HDF5; read only numeric vectors through the same guarded path.
            with h5py.File(file, "r") as handle:
                from tribos.datasets.validators import check_hdf5_structure
                check_hdf5_structure(handle)
                columns = {name: np.asarray(item).squeeze() for name, item in handle.items()
                           if isinstance(item, h5py.Dataset) and item.size <= MAX_ROWS
                           and item.dtype.kind in "fiu" and 1 in item.shape}
            frame = pd.DataFrame(columns)
        else:
            names = [name for name, shape, kind in whosmat(file)
                     if math.prod(shape) <= MAX_ROWS and kind in ("double", "single", "int32", "int64")]
            values = loadmat(file, variable_names=names)
            frame = pd.DataFrame({n: np.asarray(values[n]).squeeze() for n in names
                                  if np.asarray(values[n]).squeeze().ndim == 1})
    elif suffix == ".json":
        frame = pd.read_json(file)
    elif suffix == ".parquet":
        frame = pd.read_parquet(file)
    else:
        raise ValueError("Measurements must be CSV, TSV, XLSX, HDF5 or MAT.")
    if len(frame) > MAX_ROWS or not 2 <= len(frame) or len(frame.columns) > 100:
        raise ValueError(f"Measurements need 2–{MAX_ROWS} rows and at most 100 columns.")
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def fit_ode(
    *, rhs: dict[str, str] | None, initial_state: dict[str, float] | None,
    parameters: dict[str, float] | None, model_name: str | None, param_names: list[str] | None,
    initial_guess: dict[str, float] | None, data: dict[str, Any] | None, data_path: str | None,
    time_column: str | None, column_mapping: dict[str, str] | None,
    bounds: dict[str, tuple[float, float]] | None, n_starts: int, loss: str,
    fit_initial_state: bool | list[str], seed: int, max_nfev: int, method: str,
) -> dict[str, Any]:
    from .engine import ODE_PRESETS, integrate_system

    preset = ODE_PRESETS.get(model_name or "", {})
    if model_name and not preset:
        raise ValueError(f"Unknown ODE preset {model_name!r}.")
    rhs = dict(rhs or preset.get("rhs") or {})
    initial = {**preset.get("initial_state", {}), **(initial_state or {})}
    params = {**preset.get("parameters", {}), **(parameters or {})}
    names = list(param_names or params)
    if not rhs or not names or len(names) > 12 or len(rhs) > 12 or len(set(names)) != len(names):
        raise ValueError("Provide an ODE and 1–12 distinct parameter names (at most 12 states).")
    if set(rhs) - set(initial):
        raise ValueError("Supply initial values for every state variable.")
    frame = load_measurements(data_path) if data_path else pd.DataFrame(data or {})
    if not 2 <= len(frame) <= MAX_ROWS:
        raise ValueError(f"Measurements need 2–{MAX_ROWS} time points.")
    time_column = time_column or next((str(c) for c in frame if str(c).lower() in TIME_COLUMNS), None)
    if time_column not in frame:
        raise ValueError("No time column was found; specify time_column.")
    times = np.asarray(frame[time_column], dtype=float)
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Measurement times must be finite and strictly increasing.")
    mapping = dict(column_mapping or {s: s for s in rhs if s in frame})
    if not mapping or set(mapping) - set(rhs) or any(c not in frame for c in mapping.values()):
        raise ValueError("Map at least one observed column to a known state variable.")
    observed = np.asarray([frame[c] for c in mapping.values()], dtype=float)
    if not np.isfinite(observed).all():
        raise ValueError("Measurements must be finite numbers, without missing values.")
    initial_names = list(rhs) if fit_initial_state is True else list(fit_initial_state or [])
    if set(initial_names) - set(rhs):
        raise ValueError("Unknown state in fit_initial_state.")
    labels = names + [f"initial:{n}" for n in initial_names]
    if observed.size <= len(labels):
        raise ValueError("More observed values than fitted parameters are required for confidence intervals.")
    guess = {**params, **{f"initial:{n}": initial[n] for n in initial_names}, **(initial_guess or {})}
    x0 = np.array([float(guess.get(n, 1)) for n in labels])
    lower = np.array([float((bounds or {}).get(n, (-np.inf, np.inf))[0]) for n in labels])
    upper = np.array([float((bounds or {}).get(n, (-np.inf, np.inf))[1]) for n in labels])
    if np.any(lower >= upper) or not np.isfinite(x0).all():
        raise ValueError("Bounds must have lower < upper; starting values must be finite.")
    x0 = np.clip(x0, lower + 1e-10, upper - 1e-10)
    span = (float(times[0]), float(times[-1]))
    indices = [list(rhs).index(s) for s in mapping]
    deadline = time.monotonic() + 45

    def predict(theta: np.ndarray) -> np.ndarray:
        if time.monotonic() > deadline:
            raise TimeoutError("ODE fitting exceeded its 45 second compute limit.")
        p = {**params, **dict(zip(names, theta[:len(names)], strict=True))}
        y0 = {**initial, **dict(zip(initial_names, theta[len(names):], strict=True))}
        return integrate_system(rhs, y0, span, p, method, times)[0].y[indices]

    predict(x0)  # Reject unsafe expressions and unresolved parameters before optimization.
    def residual(theta: np.ndarray) -> np.ndarray:
        try:
            return (predict(theta) - observed).ravel()
        except (RuntimeError, FloatingPointError, OverflowError):
            return np.full(observed.size, 1e15)

    rng = np.random.default_rng(seed)
    candidates = []
    for start in range(max(1, min(5, n_starts))):
        p0 = x0 if start == 0 else np.clip(x0 + rng.normal(size=len(x0))*np.maximum(abs(x0), 1)*0.5,
                                         lower + 1e-10, upper - 1e-10)
        candidates.append(least_squares(residual, p0, bounds=(lower, upper), loss=loss,
                                         max_nfev=min(400, max(5, max_nfev)), x_scale="jac"))
    best = min(candidates, key=lambda item: float(item.cost))
    predicted = predict(best.x)
    residuals = observed - predicted
    rss = float(np.sum(residuals**2))
    n, k = observed.size, len(labels)
    information = best.jac.T @ best.jac
    singular = np.linalg.matrix_rank(information) < k or np.linalg.cond(information) > 1e12
    covariance = (rss/(n-k))*np.linalg.pinv(information)
    errors = np.sqrt(np.maximum(0, np.diag(covariance)))
    denominator = np.outer(errors, errors)
    correlation = np.divide(covariance, denominator, out=np.eye(k), where=denominator > 0)
    warnings = ["Near-singular JᵀJ: parameters are not separately identifiable; confidence intervals unavailable."] if singular else []
    if loss != "linear":
        warnings.append("Robust-loss confidence intervals use a local Jacobian approximation.")
    ci: dict[str, list[float | None]] = {}
    estimates = []
    for i, name in enumerate(labels):
        low, high = (None, None) if singular else (float(best.x[i]-1.96*errors[i]), float(best.x[i]+1.96*errors[i]))
        ci[name] = [low, high]
        wide = 3.92*errors[i] > abs(best.x[i])
        if wide and not singular:
            warnings.append(f"{name}: the 95% CI is wider than the fitted value.")
        estimates.append({"name": name, "initial": float(x0[i]), "estimate": float(best.x[i]),
                          "std_error": None if singular else float(errors[i]), "ci_low": low, "ci_high": high,
                          "identifiability": "structurally_non_identifiable" if singular else
                          "practically_non_identifiable" if wide else "identifiable"})
        for j in range(i):
            if abs(correlation[i, j]) > 0.95:
                warnings.append(f"{name} and {labels[j]} are strongly correlated (|corr| > 0.95).")
    metrics, fits = {}, {}
    selected = np.unique(np.linspace(0, len(times)-1, min(200, len(times))).astype(int))
    for i, state in enumerate(mapping):
        total = float(np.sum((observed[i]-observed[i].mean())**2))
        error = float(np.sum(residuals[i]**2))
        metrics[state] = {"rss": error, "rmse": float(np.sqrt(error/len(times))),
                          "r_squared": 1-error/total if total > 0 else (1.0 if error == 0 else 0.0)}
        fits[state] = {"time": times[selected].tolist(), "observed": observed[i, selected].tolist(),
                       "simulated": predicted[i, selected].tolist(), "residuals": residuals[i, selected].tolist()}
    fitted = {name: float(best.x[i]) for i, name in enumerate(names)}
    y0 = {**initial, **{name: float(best.x[len(names)+i]) for i, name in enumerate(initial_names)}}
    sigma = max(rss/n, np.finfo(float).tiny)
    return {"model_name": model_name or "stated ODE", "backend": "scipy.least_squares", "status": "converged" if best.success else "partial",
            "parameters": fitted, "parameter_estimates": estimates,
            "std_errors": {n: None if singular else float(errors[i]) for i, n in enumerate(labels)},
            "confidence_intervals": ci, "covariance": None if singular else covariance.tolist(),
            "correlation_matrix": correlation.tolist(), "correlation_labels": labels,
            "identifiable": not singular and not any("wider" in w or "correlated" in w for w in warnings),
            "warnings": warnings, "ci_method": "local Jacobian, 95% normal approximation",
            "objective": {"rss": rss, "rmse": math.sqrt(rss/n), "n_points": n,
                          "aic": n*math.log(sigma)+2*k, "bic": n*math.log(sigma)+k*math.log(n)},
            "rmse": math.sqrt(rss/n), "metrics": metrics, "fit": fits,
            "column_mapping": mapping, "fitted_initial_state": y0,
            "spec": {"rhs": rhs, "parameters": {**params, **fitted}, "initial_state": y0,
                     "t_span": list(span), "method": method, "model_name": model_name},
            "converged": bool(best.success), "verified": False}
