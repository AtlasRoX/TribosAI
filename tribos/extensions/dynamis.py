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
    DynamisMonteCarloInput,
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
                metadata={"engine": "numpy/scipy", "verified": bool(data.get("verified", False))},
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
    from tribos.dynamis.monte_carlo import monte_carlo_integrate

    specs = [
        (
            "dynamis_monte_carlo_integrate",
            "Execute crude Monte Carlo quadrature of a scalar integrand on a finite interval using exactly the "
            "requested sample count and NumPy Generator(PCG64(seed)). Returns the estimate, sample-based standard "
            "error (ddof=1), reference discrepancy in standard errors, and reproducibility metadata. "
            "Use for Monte Carlo requests, not symbolic integration.",
            DynamisMonteCarloInput,
            monte_carlo_integrate,
            ["numerical", "monte_carlo", "sampling", "quadrature", "reproducible", "numpy"],
        ),
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
            "Fit ODE models (e.g. damped oscillator or logistic growth) to attached CSV/XLSX/HDF5/MAT measurements, or fit algebraic curves. Supports column mapping, bounds, robust loss and multi-start; reports 95% confidence intervals, correlations, identifiability warnings, residuals, RSS, RMSE, R², AIC and BIC.",
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
        from .calibration import run_ode_fit_tool

        registry.register(
            ToolUniverseEntry(
                name=name,
                description=desc,
                domain="dynamis",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=schema,
                canonical_id_types=["computation_id"],
                timeout_seconds=60.0,
                tags=tags + (["user_data"] if name == "dynamis_fit_parameters" else []),
                is_async=False,
            ),
            executor=run_ode_fit_tool if name == "dynamis_fit_parameters" else _wrap_executor(name, fn),
        )


def _monte_carlo_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    for result in reversed(list(tool_results.values())):
        if getattr(result, "success", False) and getattr(result, "tool_name", "") == "dynamis_monte_carlo_integrate":
            return {"monte_carlo": result.data}
    return {}


from tribos.extensions.hooks import register_artifact_builder

register_artifact_builder("monte_carlo", _monte_carlo_artifact)

__all__ = ["register_tools"]
