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
    model_expr: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Model expression in terms of independent_var and param_names (e.g. 'a * exp(-b * t) + c')",
    )
    independent_var: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Independent variable symbol name (e.g. 'x' or 't')",
    )
    param_names: list[str] = Field(
        ...,
        min_length=1,
        description="List of parameter names to fit (e.g. ['a', 'b', 'c'])",
    )
    x_data: list[float] = Field(
        ...,
        min_length=2,
        description="Observed independent variable values",
    )
    y_data: list[float] = Field(
        ...,
        min_length=2,
        description="Observed dependent variable values",
    )
    initial_guess: dict[str, float] | None = Field(
        default=None,
        description="Optional initial parameter guess dictionary (defaults to 1.0 per parameter)",
    )


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
