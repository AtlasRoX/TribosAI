"""Extension module registering the Dynamis PDE solver into the ToolRegistry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DynamisSolvePdeInput(BaseModel):
    equation: str = Field(
        ...,
        min_length=1,
        description=(
            "The PDE: 'heat' (u_t = alpha Laplacian(u) + f, 1D/2D), 'wave' (u_tt = c^2 Laplacian(u) + f, 1D/2D), "
            "'poisson' (-Laplacian(u) = f, steady, 1D/2D; f = 0 is Laplace), 'advection_diffusion' "
            "(u_t + v u_x = D u_xx + f, 1D), 'fisher_kpp' (u_t = D u_xx + r u (1 - u), 1D) or 'burgers' "
            "(u_t + u u_x = nu u_xx, 1D)."
        ),
    )
    domain: list[list[float]] = Field(
        default=[[0.0, 1.0]],
        min_length=1,
        max_length=2,
        description="One [low, high] interval per dimension: [[0, 1]] for a line, [[0, 1], [0, 2]] for a rectangle.",
    )
    dimension: int | None = Field(default=None, ge=1, le=2, description="1 or 2; inferred from the domain when omitted.")
    parameters: dict[str, float] | None = Field(
        default=None,
        description=(
            "alpha for heat, c for wave, v and D for advection-diffusion, r and D for Fisher-KPP, nu for Burgers. "
            "Any other name may be used inside the expressions."
        ),
    )
    initial_condition: str | None = Field(
        default=None, max_length=2000, description="u(x, y, 0) as an expression, e.g. 'sin(pi*x)'. Required unless poisson."
    )
    initial_velocity: str | None = Field(default=None, max_length=2000, description="u_t(x, y, 0) for the wave equation.")
    source: str | None = Field(default=None, max_length=2000, description="The source f(x, y, t); for poisson, f(x, y).")
    boundary: dict[str, str] | str | None = Field(
        default=None,
        description=(
            "Per edge 'x0', 'x1', 'y0', 'y1' (or per axis 'x', 'y', or one string for all): 'dirichlet' (default), "
            "'neumann' or 'periodic'."
        ),
    )
    boundary_values: dict[str, float | str] | None = Field(
        default=None,
        description=(
            "Per edge: the value u for a Dirichlet edge, or the outward normal derivative du/dn for a Neumann edge, as "
            "a number or an expression in x, y and t. Omitted edges take 0."
        ),
    )
    t_span: list[float] = Field(default=[0.0, 1.0], min_length=2, max_length=2, description="[t0, t_end].")
    num_points: int = Field(default=101, ge=5, le=20000, description="Grid points per axis (2D grids are capped at 80x80).")
    num_times: int = Field(default=21, ge=2, le=200, description="Snapshots returned across the time span.")
    method: str | None = Field(
        default=None,
        description=(
            "heat: 'crank_nicolson' (default), 'explicit' or 'bdf'; wave: 'leapfrog'; advection-diffusion, Fisher-KPP, "
            "Burgers: 'auto' (BDF when stiff), 'bdf' or 'rk45'."
        ),
    )
    dt: float | None = Field(default=None, gt=0, description="Time step of an explicit or Crank-Nicolson scheme.")
    on_unstable: str = Field(
        default="adapt", description="When dt breaks the stability (CFL) limit: 'adapt' (reduce it) or 'refuse'."
    )
    exact_solution: str | None = Field(
        default=None, max_length=2000, description="A known analytic solution u(x, y, t), to measure the error against."
    )
    probe_at: list[float | list[float]] | None = Field(
        default=None, max_length=20, description="Points whose value over time is reported: x in 1D, [x, y] in 2D."
    )
    convergence_levels: int = Field(default=3, ge=2, le=4, description="Nested grids of the mesh-convergence study.")


def execute_pde_tool(**kwargs: Any) -> Any:
    """Solve one PDE and return the field with its verification."""
    from tribos.dynamis.pde import solve_pde
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = solve_pde(**kwargs)
        return ToolResult(
            success=True,
            tool_name="dynamis_solve_pde",
            data=data,
            canonical_ids={},
            metadata={
                "engine": "numpy/scipy",
                "equation": data.get("equation"),
                "converged": bool((data.get("convergence") or {}).get("converged")),
            },
        )
    except ValueError as exc:
        return ToolResult(
            success=False,
            tool_name="dynamis_solve_pde",
            error=str(exc),
            error_type=ErrorType.VALIDATION_ERROR,
        )
    except RuntimeError as exc:
        return ToolResult(
            success=False,
            tool_name="dynamis_solve_pde",
            error=str(exc),
            error_type=getattr(ErrorType, "SIMULATION_FAILED", ErrorType.INTERNAL_ERROR),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="dynamis_solve_pde",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.INTERNAL_ERROR,
        )


def register_tools(registry: Any) -> None:
    """Register the PDE solver in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="dynamis_solve_pde",
            description=(
                "Solve a partial differential equation on a rectangular domain: heat/diffusion, wave, Poisson/Laplace, "
                "advection-diffusion, Fisher-KPP reaction-diffusion or viscous Burgers, in 1D or 2D with Dirichlet, "
                "Neumann or periodic boundaries; initial conditions and sources are expressions in x, y, t. Reports a "
                "mesh-convergence study (observed order, Richardson error, converged flag), the stability (CFL) number, "
                "conservation of mass or energy, and the error against an analytic solution when one is given."
            ),
            domain="dynamis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=DynamisSolvePdeInput,
            canonical_id_types=[],
            timeout_seconds=60.0,
            tags=[
                "numerical", "pde", "partial_differential_equation", "heat", "diffusion", "wave", "poisson",
                "laplace", "advection", "burgers", "fisher_kpp", "finite_difference", "scipy", "numpy", "expensive",
            ],
            is_async=False,
        ),
        executor=execute_pde_tool,
    )


def _pde_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The field of the last successful PDE solve, for the browser's result card."""
    for result in reversed(list(tool_results.values())):
        if getattr(result, "success", False) and getattr(result, "tool_name", "") == "dynamis_solve_pde":
            data = getattr(result, "data", {}) or {}
            if data.get("snapshots") and data.get("convergence") is not None:
                return {"pde": data}
    return {}


def register_hooks() -> None:
    """Register the PDE hooks (idempotent)."""
    from tribos.extensions import hooks

    hooks.register_artifact_builder("pde", _pde_artifact)


register_hooks()


__all__ = ["DynamisSolvePdeInput", "execute_pde_tool", "register_hooks", "register_tools"]
