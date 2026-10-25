"""Extension module registering the engineering calculators (tribos/engcalc) into the ToolRegistry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def _inputs_by_calculator() -> str:
    """Each calculator's input names, for the planner (the names the calculator accepts, aliases aside)."""
    try:
        from tribos.engcalc import CALCULATORS

        return "; ".join(f"{c.id}: {', '.join(p.name for p in c.params)}" for c in CALCULATORS.values())
    except Exception:  # noqa: BLE001 - the description is a hint; the calculator still reports its inputs on error
        return ""


class PhysisEngineeringCalcInput(BaseModel):
    calculator: str = Field(
        ...,
        min_length=1,
        description=(
            "One of: beam (deflection and bending stress; simply supported or cantilever, point load or UDL), "
            "column_buckling (Euler/Johnson), pressure_vessel (thin-wall hoop/longitudinal stress, ASME VIII-1 UG-27 "
            "thickness), shaft (torsion plus bending, von Mises), bolt_preload (preload and torque), fatigue (Basquin, "
            "Goodman/Gerber/Soderberg, Miner), pipe_pressure_drop (Darcy-Weisbach, Colebrook), heat_exchanger (LMTD, "
            "effectiveness-NTU), layered_wall (composite-wall conduction). physis_list_calculators lists the inputs."
        ),
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Input values by name. A bare number is in the input's SI unit; any unit may be written as a string "
            "('250 MPa', '12 mm', '5 kN/m') or as {value, unit, uncertainty} to propagate an uncertainty. Input names "
            "per calculator: " + _inputs_by_calculator()
        ),
    )
    material: str | None = Field(
        default=None,
        description=(
            "Optional material that fills E, nu, yield and ultimate strength, density, k and CTE: s235, s355, a36, "
            "ss304, ss316, al6061_t6, al7075_t6, ti6al4v, copper, concrete, peek (typical values, not allowables)."
        ),
    )


class PhysisListCalculatorsInput(BaseModel):
    calculator: str | None = Field(default=None, description="Describe only this calculator (all when omitted).")


def execute_engineering_calc(calculator: str, inputs: dict[str, Any] | None = None, material: str | None = None) -> Any:
    from tribos.engcalc import run_calculator
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = run_calculator(calculator, inputs or {}, material)
    except ValueError as exc:
        return ToolResult(success=False, tool_name="physis_engineering_calc", error=str(exc),
                          error_type=ErrorType.VALIDATION_ERROR)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, tool_name="physis_engineering_calc", error=f"{type(exc).__name__}: {exc}",
                          error_type=ErrorType.INTERNAL_ERROR)
    utilisation = data.get("utilisation") or {}
    return ToolResult(
        success=True,
        tool_name="physis_engineering_calc",
        data=data,
        canonical_ids={},
        metadata={"calculator": data["calculator"], "utilisation": utilisation.get("value"),
                  "checks_ok": utilisation.get("ok")},
    )


def execute_list_calculators(calculator: str | None = None) -> Any:
    from tribos.engcalc import get_calculator, list_calculators
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = list_calculators()
        if calculator:
            data["calculators"] = [get_calculator(calculator).describe()]
    except ValueError as exc:
        return ToolResult(success=False, tool_name="physis_list_calculators", error=str(exc),
                          error_type=ErrorType.VALIDATION_ERROR)
    return ToolResult(success=True, tool_name="physis_list_calculators", data=data, canonical_ids={})


def register_tools(registry: Any) -> None:
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="physis_engineering_calc",
            description=(
                "Engineering design calculation backed by a cited standard or textbook (Roark, Shigley, ASME VIII-1 "
                "UG-27, Incropera, Colebrook): beam deflection and bending stress, column buckling, thin-wall pressure "
                "vessel, shaft torsion and combined stress, bolt preload and torque, fatigue life and safety factor, "
                "pipe pressure drop, heat exchanger LMTD/NTU, layered-wall conduction. Unit-checked inputs, material "
                "data, safety factor and utilisation, validity limits and optional uncertainty propagation."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisEngineeringCalcInput,
            canonical_id_types=[],
            timeout_seconds=30.0,
            tags=["engineering", "design", "structural", "mechanical", "thermal", "fluid", "stress", "safety_factor",
                  "utilisation", "materials", "standards"],
            is_async=False,
        ),
        executor=execute_engineering_calc,
    )
    registry.register(
        ToolUniverseEntry(
            name="physis_list_calculators",
            description=(
                "List the engineering calculators (beam, column buckling, pressure vessel, shaft, bolt, fatigue, pipe "
                "pressure drop, heat exchanger, layered wall) with their inputs, units, defaults and references, and "
                "the built-in material table."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisListCalculatorsInput,
            canonical_id_types=[],
            timeout_seconds=10.0,
            tags=["engineering", "calculators", "materials", "catalog"],
            is_async=False,
        ),
        executor=execute_list_calculators,
    )


def _engineering_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Every successful calculation of the turn, latest last, for the browser's result card."""
    runs = [
        getattr(r, "data", None) for r in tool_results.values()
        if getattr(r, "success", False) and getattr(r, "tool_name", "") == "physis_engineering_calc"
    ]
    runs = [d for d in runs if isinstance(d, dict) and d.get("results")]
    return {"engineering_calc": {"calculations": runs}} if runs else {}


def register_hooks() -> None:
    from tribos.extensions import hooks

    hooks.register_artifact_builder("engineering_calc", _engineering_artifact)


register_hooks()

__all__ = [
    "PhysisEngineeringCalcInput",
    "PhysisListCalculatorsInput",
    "execute_engineering_calc",
    "execute_list_calculators",
    "register_hooks",
    "register_tools",
]
