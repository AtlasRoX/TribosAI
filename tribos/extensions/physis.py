"""Extension module registering Physis physical constants, dimensional analysis, OEIS, and materials tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tribos.physis.engine import PhysisEngine

_DEFAULT_ENGINE: PhysisEngine | None = None


def get_physis_engine() -> PhysisEngine:
    """Return a shared PhysisEngine instance."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = PhysisEngine()
    return _DEFAULT_ENGINE


class PhysisConstantsInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Physical constant name, symbol, or keyword (e.g. 'Planck constant', 'c', 'hbar', 'Boltzmann', 'fine-structure').",
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of matching CODATA 2022 constants to return.")


class PhysisUnitsInput(BaseModel):
    value: float = Field(default=1.0, description="Numerical magnitude of the physical quantity.")
    from_unit: str = Field(default="", description="Source unit expression (e.g. 'eV', 'kcal/mol', 'GPa', 'N * m').")
    to_unit: str | None = Field(default=None, description="Target unit expression (e.g. 'J', 'kJ/mol', 'Pa'). Omit to reduce to base SI units.")
    check_equation: str | None = Field(
        default=None,
        description="Optional equation 'lhs = rhs' (e.g. 'kg * m / s^2 = N') to verify dimensional homogeneity.",
    )


class PhysisOeisInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="OEIS sequence query: A-number (e.g. 'A000045'), comma-separated initial terms (e.g. '1, 1, 2, 5, 14, 42'), or keyword.",
    )
    limit: int = Field(default=5, ge=1, le=25, description="Maximum number of integer sequences to return.")


class PhysisMaterialsInput(BaseModel):
    formula: str | None = Field(default=None, description="Chemical formula or material name (e.g. 'Si', 'GaAs', 'TiO2', 'Silicon').")
    material_id: str | None = Field(default=None, description="Materials Project ID (e.g. 'mp-149', 'mp-2534').")
    elements: list[str] | None = Field(default=None, description="List of required chemical elements (e.g. ['Ga', 'N']).")
    query: str | None = Field(default=None, description="General material search query.")
    limit: int = Field(default=5, ge=1, le=25, description="Maximum number of materials to return.")


class PhysisWolframInput(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language or symbolic query for Wolfram|Alpha LLM API.")


class PhysisEncyclopediaInput(BaseModel):
    query: str = Field(..., min_length=1, description="Mathematical theorem, physical concept, or engineering topic to look up on Wikipedia.")
    limit: int = Field(default=3, ge=1, le=10, description="Maximum number of encyclopedia entries to return.")


def _flatten_canonical_ids(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    cid = data.get("canonical_id")
    if isinstance(cid, str) and cid:
        out["canonical_id"] = cid
    raw = data.get("canonical_ids")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, str) and v:
                out[str(k)] = v
            elif isinstance(v, (list, tuple)) and v:
                joined = ",".join(str(item) for item in v if item)
                if joined:
                    out[str(k)] = joined
    return out


def execute_physis_constants(query: str, limit: int = 10) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = get_physis_engine().lookup_constants(query=query, limit=limit)
        return ToolResult(
            success=True,
            tool_name="physis_constants",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"source": "NIST CODATA 2022"},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_constants",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.INTERNAL_ERROR,
        )


def execute_physis_units(
    value: float = 1.0,
    from_unit: str = "",
    to_unit: str | None = None,
    check_equation: str | None = None,
) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = get_physis_engine().convert_units(
            value=value,
            from_unit=from_unit,
            to_unit=to_unit,
            check_equation=check_equation,
        )
        return ToolResult(
            success=True,
            tool_name="physis_units",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"engine": "pint", "compatible": bool(data.get("compatible", True))},
        )
    except ValueError as exc:
        return ToolResult(
            success=False,
            tool_name="physis_units",
            error=str(exc),
            error_type=ErrorType.VALIDATION_ERROR,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_units",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.INTERNAL_ERROR,
        )


async def execute_physis_oeis(query: str, limit: int = 5) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = await get_physis_engine().lookup_oeis(query=query, limit=limit)
        return ToolResult(
            success=True,
            tool_name="physis_oeis",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"source": "oeis"},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_oeis",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


async def execute_physis_materials(
    formula: str | None = None,
    material_id: str | None = None,
    elements: list[str] | None = None,
    query: str | None = None,
    limit: int = 5,
) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = await get_physis_engine().lookup_materials(
            formula=formula,
            material_id=material_id,
            elements=elements,
            query=query,
            limit=limit,
        )
        return ToolResult(
            success=True,
            tool_name="physis_materials",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"source": data.get("source", "materials_project")},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_materials",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


async def execute_physis_wolfram(query: str) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = await get_physis_engine().query_wolfram(query=query)
        return ToolResult(
            success=True,
            tool_name="physis_wolfram",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"source": "wolfram_alpha", "skipped": bool(data.get("skipped", False))},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_wolfram",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


async def execute_physis_encyclopedia(query: str, limit: int = 3) -> Any:
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = await get_physis_engine().lookup_encyclopedia(query=query, limit=limit)
        return ToolResult(
            success=True,
            tool_name="physis_encyclopedia",
            data=data,
            canonical_ids=_flatten_canonical_ids(data),
            metadata={"source": "wikipedia"},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_encyclopedia",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.UPSTREAM_ERROR,
        )


def register_tools(registry: Any) -> None:
    """Register all 6 Physis physical/mathematical reference tools in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="physis_constants",
            description="Look up exact NIST CODATA 2022 physical constants, symbols, units, and uncertainties (via scipy.constants).",
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisConstantsInput,
            canonical_id_types=["nist_constant"],
            timeout_seconds=10.0,
            tags=["physics", "constants", "codata", "nist", "fundamental_constants", "scipy"],
            is_async=False,
        ),
        executor=execute_physis_constants,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_units",
            description="Convert physical quantities between units, reduce expressions to base SI units, and verify dimensional homogeneity across equations using Pint.",
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisUnitsInput,
            canonical_id_types=["unit_conversion"],
            timeout_seconds=10.0,
            tags=["physics", "units", "dimensions", "dimensional_analysis", "si", "pint", "conversion"],
            is_async=False,
        ),
        executor=execute_physis_units,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_oeis",
            description="Query the On-Line Encyclopedia of Integer Sequences (OEIS) by A-number, sequence terms, or mathematical keyword.",
            domain="physis",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=PhysisOeisInput,
            canonical_id_types=["oeis_id"],
            timeout_seconds=15.0,
            tags=["mathematics", "oeis", "sequences", "integer_sequences", "combinatorics", "number_theory"],
            is_async=True,
        ),
        executor=execute_physis_oeis,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_materials",
            description="Look up crystalline, electronic, mechanical, and thermal properties of materials via the Materials Project API v2 and built-in engineering reference tables.",
            domain="physis",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=PhysisMaterialsInput,
            canonical_id_types=["mp_id"],
            timeout_seconds=15.0,
            tags=["materials", "materials_project", "band_gap", "density", "crystal", "engineering", "semiconductors"],
            is_async=True,
        ),
        executor=execute_physis_materials,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_wolfram",
            description="Query the Wolfram|Alpha LLM API for external mathematical, physical, or engineering facts when TRIBOS_WOLFRAM_APPID is configured.",
            domain="physis",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=PhysisWolframInput,
            canonical_id_types=[],
            timeout_seconds=20.0,
            tags=["wolfram", "reference", "computation", "facts"],
            is_async=True,
        ),
        executor=execute_physis_wolfram,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_encyclopedia",
            description="Search Wikipedia REST API for definitions, theorems, and encyclopedia summaries of mathematical, physical, and engineering concepts.",
            domain="physis",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=PhysisEncyclopediaInput,
            canonical_id_types=[],
            timeout_seconds=15.0,
            tags=["wikipedia", "encyclopedia", "definitions", "theorems", "concepts"],
            is_async=True,
        ),
        executor=execute_physis_encyclopedia,
    )


__all__ = [
    "PhysisConstantsInput",
    "PhysisEncyclopediaInput",
    "PhysisMaterialsInput",
    "PhysisOeisInput",
    "PhysisUnitsInput",
    "PhysisWolframInput",
    "execute_physis_constants",
    "execute_physis_encyclopedia",
    "execute_physis_materials",
    "execute_physis_oeis",
    "execute_physis_units",
    "execute_physis_wolfram",
    "get_physis_engine",
    "register_tools",
]
