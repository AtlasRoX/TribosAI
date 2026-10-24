"""Extension module registering Dynamis numerical simulation and optimization tools into the ToolRegistry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tribos.dynamis.engine import (
    dynamis_equilibrium,
    dynamis_fit_parameters,
    dynamis_optimize,
    dynamis_parameter_scan,
    dynamis_root_find,
    dynamis_simulate_ode,
)
from tribos.dynamis.schemas import (
    DynamisEquilibriumInput,
    DynamisFitParametersInput,
    DynamisOptimizeInput,
    DynamisParameterScanInput,
    DynamisRootFindInput,
    DynamisSimulateOdeInput,
)


def _wrap_executor(tool_name: str, fn: Callable[..., dict[str, Any]]) -> Callable[..., Any]:
    def _exec(**kwargs: Any) -> Any:
        from tribos.tools.registry import ErrorType, ToolResult

        try:
            data = fn(**kwargs)
            cid = str(data.get("canonical_id") or "")
            canonical_ids = {"computation_id": cid} if cid else {}
            return ToolResult(
                success=True,
                tool_name=tool_name,
                data=data,
                canonical_ids=canonical_ids,
                metadata={"engine": "scipy", "verified": bool(data.get("verified", True))},
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=str(exc),
                error_type=ErrorType.VALIDATION_ERROR,
            )
        except RuntimeError as exc:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=str(exc),
                error_type=getattr(ErrorType, "SIMULATION_FAILED", ErrorType.INTERNAL_ERROR),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"{type(exc).__name__}: {exc}",
                error_type=ErrorType.INTERNAL_ERROR,
            )

    _exec.__name__ = f"execute_{tool_name}"
    return _exec


def register_tools(registry: Any) -> None:
    """Register all 6 Dynamis numerical simulation and optimization tools in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    specs = [
        (
            "dynamis_simulate_ode",
            "Simulate a system of ordinary differential equations (ODEs) dx_i/dt = f_i(t, x; p) or a named physical preset over time using SciPy solve_ivp.",
            DynamisSimulateOdeInput,
            dynamis_simulate_ode,
            ["numerical", "ode", "simulation", "dynamics", "solve_ivp", "time_course", "scipy"],
        ),
        (
            "dynamis_equilibrium",
            "Find equilibrium fixed points f(x*) = 0 of a dynamical system, compute the Jacobian matrix and eigenvalues, and classify stability.",
            DynamisEquilibriumInput,
            dynamis_equilibrium,
            ["numerical", "equilibrium", "fixed_point", "jacobian", "stability", "eigenvalues", "bifurcation", "scipy"],
        ),
        (
            "dynamis_parameter_scan",
            "Sweep a model parameter across a range and record steady/final, peak, min, and mean state responses across trajectories.",
            DynamisParameterScanInput,
            dynamis_parameter_scan,
            ["numerical", "parameter_scan", "sensitivity", "sweep", "ode", "dynamics", "scipy"],
        ),
        (
            "dynamis_optimize",
            "Perform constrained or unconstrained numerical optimization (minimize or maximize an objective function) via SciPy optimize.minimize.",
            DynamisOptimizeInput,
            dynamis_optimize,
            ["numerical", "optimize", "minimize", "maximize", "constraints", "bounds", "scipy"],
        ),
        (
            "dynamis_fit_parameters",
            "Fit nonlinear model parameters to observed (x, y) data via nonlinear least squares, returning fitted values, standard errors, RMSE, and R^2.",
            DynamisFitParametersInput,
            dynamis_fit_parameters,
            ["numerical", "fit", "curve_fit", "least_squares", "regression", "calibration", "scipy"],
        ),
        (
            "dynamis_root_find",
            "Find numerical roots of nonlinear equations or systems of equations using SciPy optimize.root.",
            DynamisRootFindInput,
            dynamis_root_find,
            ["numerical", "root", "fsolve", "nonlinear", "equations", "scipy"],
        ),
    ]

    for name, desc, schema, fn, tags in specs:
        registry.register(
            ToolUniverseEntry(
                name=name,
                description=desc,
                domain="dynamis",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=schema,
                canonical_id_types=["computation_id"],
                timeout_seconds=60.0,
                tags=tags,
                is_async=False,
            ),
            executor=_wrap_executor(name, fn),
        )


__all__ = ["register_tools"]
