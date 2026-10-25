"""Pydantic input/output schemas for the Dynamis numerics, ODE simulation, and optimization package."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DynamisSimulateOdeInput(BaseModel):
    rhs: dict[str, str] | None = Field(
        default=None,
        description="System of ODE right-hand sides mapping state variable name to dx_i/dt expression (e.g. {'x': 'v', 'v': '-k*x'})",
    )
    initial_state: dict[str, float] | None = Field(
        default=None,
        description="Initial state values at t_span[0], e.g. {'x': 1.0, 'v': 0.0}",
    )
    t_span: tuple[float, float] = Field(
        default=(0.0, 10.0),
        description="Integration time interval (t0, tf)",
    )
    parameters: dict[str, float] | None = Field(
        default=None,
        description="Parameter dictionary mapping parameter names to numeric values",
    )
    method: str = Field(
        default="RK45",
        description="SciPy solve_ivp integration method: RK45, RK23, DOP853, Radau, BDF, or LSODA",
    )
    num_points: int = Field(
        default=200,
        ge=2,
        le=10000,
        description="Number of time evaluation points across t_span",
    )
    model_name: str | None = Field(
        default=None,
        description="Optional built-in preset name (harmonic_oscillator, damped_oscillator, lorenz, lotka_volterra, van_der_pol, sir, pendulum, rc_circuit, rlc_circuit)",
    )


class DynamisEquilibriumInput(BaseModel):
    rhs: dict[str, str] = Field(
        ...,
        description="System of ODE right-hand sides mapping variable name to dx_i/dt expression",
    )
    guess: dict[str, float] = Field(
        ...,
        description="Initial guess for fixed point state variables",
    )
    parameters: dict[str, float] | None = Field(
        default=None,
        description="Optional numeric parameter values",
    )


class DynamisParameterScanInput(BaseModel):
    rhs: dict[str, str] = Field(
        ...,
        description="System of ODE right-hand sides mapping state variable name to dx_i/dt expression",
    )
    initial_state: dict[str, float] = Field(
        ...,
        description="Initial values for all state variables",
    )
    parameter: str = Field(
        ...,
        min_length=1,
        description="Name of the parameter to sweep",
    )
    scan_range: tuple[float, float] = Field(
        ...,
        description="(min_val, max_val) range for the parameter sweep",
    )
    num_points: int = Field(
        default=10,
        ge=2,
        le=200,
        description="Number of parameter values to evaluate",
    )
    t_span: tuple[float, float] = Field(
        default=(0.0, 10.0),
        description="Integration time interval (t0, tf) for each parameter value",
    )
    base_parameters: dict[str, float] | None = Field(
        default=None,
        description="Base numeric values for all other parameters in the ODE system",
    )


class DynamisOptimizeInput(BaseModel):
    objective: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Objective function expression to minimize or maximize (e.g. '(x - 2)^2 + (y + 3)^2')",
    )
    variables: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered list of decision variable names",
    )
    bounds: dict[str, tuple[float | None, float | None]] | None = Field(
        default=None,
        description="Optional box bounds per variable: {'x': (lower, upper)}",
    )
    initial_guess: dict[str, float] | None = Field(
        default=None,
        description="Optional starting point for optimization; defaults to 0.0 (clamped into bounds)",
    )
    constraints: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional constraints list, each {'type': 'eq'|'ineq', 'expr': '...'}",
    )
    minimize: bool = Field(
        default=True,
        description="True to minimize the objective, False to maximize",
    )


class DynamisFitParametersInput(BaseModel):
    model_expr: str | None = Field(default=None, max_length=4000, description="Algebraic curve expression; omit for ODE fitting")
    independent_var: str = "t"
    param_names: list[str] | None = Field(default=None, max_length=12, description="Parameters to estimate; defaults to the preset's parameters")
    x_data: list[float] | None = Field(default=None, max_length=5000)
    y_data: list[float] | None = Field(default=None, max_length=5000)
    initial_guess: dict[str, float] | None = None
    rhs: dict[str, str] | None = Field(default=None, max_length=12)
    initial_state: dict[str, float] | None = None
    parameters: dict[str, float] | None = None
    model_name: str | None = Field(default=None, description="Known ODE preset, e.g. damped_oscillator")
    data: dict[str, list[float]] | None = Field(default=None, max_length=100)
    data_path: str | None = Field(default=None, max_length=1024, description="Server-resolved attached measurement file; never a model-invented path")
    time_column: str | None = None
    column_mapping: dict[str, str] | None = Field(default=None, description="Observed state variable -> dataset column")
    bounds: dict[str, tuple[float, float]] | None = None
    n_starts: int = Field(default=1, ge=1, le=5)
    loss: str = Field(default="linear", pattern="^(linear|soft_l1|huber|cauchy|arctan)$")
    fit_initial_state: bool | list[str] = False
    seed: int = 0
    max_nfev: int = Field(default=200, ge=5, le=400)
    method: str = "RK45"


class DynamisRootFindInput(BaseModel):
    equations: str | list[str] = Field(
        ...,
        description="Nonlinear equation or list of equations to find roots for (e.g. ['x^2 + y^2 - 5', 'x - y - 1'])",
    )
    initial_guess: dict[str, float] = Field(
        ...,
        description="Initial numeric guess mapping variable names to starting values",
    )
    parameters: dict[str, float] | None = Field(
        default=None,
        description="Optional fixed parameter values",
    )


__all__ = [
    "DynamisEquilibriumInput",
    "DynamisFitParametersInput",
    "DynamisOptimizeInput",
    "DynamisParameterScanInput",
    "DynamisRootFindInput",
    "DynamisSimulateOdeInput",
]
