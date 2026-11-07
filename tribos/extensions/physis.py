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
    from_unit: str = Field(
        default="",
        description="Source unit expression only (e.g. 'eV', 'kcal/mol', 'GPa', 'N * m'); never a value, variable or equation.",
    )
    to_unit: str | None = Field(default=None, description="Target unit expression (e.g. 'J', 'kJ/mol', 'Pa'). Omit to reduce to base SI units.")
    check_equation: str | None = Field(
        default=None,
        description=(
            "Optional 'lhs = rhs' written in UNITS ONLY, one unit expression per term, to verify dimensional "
            "homogeneity. Translate each term of the physical equation into its units; no variables, derivatives, "
            "numbers or primes. Example for m x'' + c x' + k x = F0 cos(wt): "
            "'kg * m/s^2 + (N*s/m) * (m/s) + (N/m) * m = N'."
        ),
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


class PhysisUncertaintyInput(BaseModel):
    expression: str = Field(..., min_length=1, description="Mathematical or physical expression to propagate uncertainty through, e.g. 'm * v^2 / 2' or 'exp(-k*t)'.")
    variables: dict[str, Any] = Field(..., description="Mapping of variable names to their values and uncertainties, e.g. {'m': {'value': 2.0, 'uncertainty': 0.1, 'unit': 'kg'}}.")
    correlations: list[dict[str, Any]] | dict[str, Any] | None = Field(default=None, description="Optional correlation coefficients between pairs of variables.")
    method: str = Field(default="both", description="Method to use: 'linear' (first-order GUM), 'monte_carlo' (sampling), or 'both'.")
    n_samples: int = Field(default=50000, ge=1000, le=500000, description="Number of Monte Carlo samples.")
    seed: int | None = Field(default=None, description="Random seed for reproducible Monte Carlo sampling.")
    confidence: float = Field(default=0.95, ge=0.5, le=0.999, description="Confidence level for coverage interval.")
    autofill_constants: bool = Field(default=True, description="Whether to automatically look up CODATA constants (e.g. c, G, h, k_B) if present in the expression.")



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
            error_type=ErrorType.UPSTREAM_API_ERROR,
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
            error_type=ErrorType.UPSTREAM_API_ERROR,
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
            error_type=ErrorType.UPSTREAM_API_ERROR,
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
            error_type=ErrorType.UPSTREAM_API_ERROR,
        )


def execute_physis_uncertainty(
    expression: str,
    variables: dict[str, Any],
    correlations: list[dict[str, Any]] | dict[str, Any] | None = None,
    method: str = "both",
    n_samples: int = 50000,
    seed: int | None = None,
    confidence: float = 0.95,
    autofill_constants: bool = True,
) -> Any:
    """Propagate measurement uncertainty through an expression (GUM linear and/or Monte Carlo)."""
    from tribos.physis.uncertainty import propagate_uncertainty
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = propagate_uncertainty(
            expression=expression,
            variables=variables,
            correlations=correlations,
            method=method,
            n_samples=n_samples,
            seed=seed,
            confidence=confidence,
            autofill_constants=autofill_constants,
        )
        return ToolResult(
            success=True,
            tool_name="physis_propagate_uncertainty",
            data=data,
            canonical_ids={},
            metadata={
                "method": method,
                "unit": data.get("unit", ""),
                "verified": True,
            },
        )
    except ValueError as exc:
        return ToolResult(
            success=False,
            tool_name="physis_propagate_uncertainty",
            error=str(exc),
            error_type=ErrorType.VALIDATION_ERROR,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name="physis_propagate_uncertainty",
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.INTERNAL_ERROR,
        )


class PhysisFluidInput(BaseModel):
    fluid: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Fluid name, formula, CAS number or refrigerant number (e.g. 'Water', 'steam', 'CO2', 'Nitrogen', "
                    "'R134a', 'R-123', 'HCFC-22', 'Ammonia', 'Air').",
    )
    operation: str = Field(
        default="state",
        description="'state' (properties at T and P, or at T and a vapour quality), 'throttle' (isenthalpic Joule-"
                    "Thomson expansion from T, P to final_pressure: final temperature and temperature change), "
                    "'isentropic' (reversible adiabatic expansion or compression to final_pressure), or 'saturation' "
                    "(saturation pressure at T, or temperature at P, with latent heat).",
    )
    temperature: str | float | None = Field(
        default=None, description="Temperature with its unit ('50 degC', '323.15 K', '77 degF'); a bare number is kelvin.")
    pressure: str | float | None = Field(
        default=None, description="Pressure with its unit ('1.5 bar', '101.325 kPa', '2 atm', '30 psi'); a bare number is Pa.")
    final_pressure: str | float | None = Field(
        default=None, description="End pressure of a 'throttle' or 'isentropic' process, with its unit.")
    quality: float | None = Field(default=None, ge=0.0, le=1.0, description="Vapour quality 0..1 for a two-phase state.")
    outputs: list[str] | None = Field(
        default=None,
        description="Properties to report at the state: density, molar_density, molar_volume, cp, cp_molar, cv, "
                    "cv_molar, enthalpy, enthalpy_molar, entropy, entropy_molar, internal_energy, "
                    "compressibility_factor, speed_of_sound, viscosity, thermal_conductivity, joule_thomson, "
                    "isothermal_compressibility, expansion_coefficient, molar_mass, quality.",
    )


def execute_physis_fluid_properties(
    fluid: str,
    operation: str = "state",
    temperature: str | float | None = None,
    pressure: str | float | None = None,
    final_pressure: str | float | None = None,
    quality: float | None = None,
    outputs: list[str] | None = None,
) -> Any:
    from tribos.physis.fluids import fluid_properties
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = fluid_properties(fluid, operation, temperature, pressure, final_pressure, quality, outputs)
    except ValueError as exc:
        return ToolResult(success=False, tool_name="physis_fluid_properties", error=str(exc),
                          error_type=ErrorType.VALIDATION_ERROR)
    except Exception as exc:  # noqa: BLE001 - CoolProp raises plain exceptions for states outside an EOS's range
        return ToolResult(success=False, tool_name="physis_fluid_properties", error=f"{type(exc).__name__}: {exc}"[:500],
                          error_type=ErrorType.VALIDATION_ERROR)
    return ToolResult(
        success=True,
        tool_name="physis_fluid_properties",
        data=data,
        canonical_ids={},
        metadata={"engine": data["method"], "eos_reference": data["eos_reference"], "verified": True},
    )


_SMILES_HELP = (
    "Write each structure as SMILES. To name atoms by their IUPAC locants, give them atom-map numbers equal to the "
    "locants, e.g. 2,3-dimethylcyclohexan-1-ol as [CH:1]1(O)[CH:2](C)[CH:3](C)[CH2:4][CH2:5][CH2:6]1."
)
_LOCANTS_HELP = ('Atom-map number -> locant label for locants that are not plain numbers, e.g. {"31": "3a", '
                 '"71": "7a"}.')


class PhysisMoleculeInput(BaseModel):
    smiles: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="One to eight structures as SMILES (stereo marks @/@@ and bond marks / and \\ optional). "
                    + _SMILES_HELP,
    )
    names: list[str] | None = Field(default=None, description="A short name for each structure, in the same order "
                                                              "(e.g. the answer options 'A', 'B', or 'product 3').")
    locants: dict[str, str] | None = Field(default=None, description=_LOCANTS_HELP)


def execute_physis_molecule(smiles: list[str], names: list[str] | None = None,
                            locants: dict[str, str] | None = None) -> Any:
    from tribos.physis.chemistry import molecule_facts
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = molecule_facts(smiles, names, locants)
    except ValueError as exc:
        return ToolResult(success=False, tool_name="physis_molecule", error=str(exc), error_type=ErrorType.VALIDATION_ERROR)
    except Exception as exc:  # noqa: BLE001 - RDKit raises its own exception types for malformed structures
        return ToolResult(success=False, tool_name="physis_molecule", error=f"{type(exc).__name__}: {exc}"[:500],
                          error_type=ErrorType.VALIDATION_ERROR)
    return ToolResult(success=True, tool_name="physis_molecule", data=data, canonical_ids={},
                      metadata={"engine": data["method"], "verified": True})


class PhysisStereoInput(BaseModel):
    smiles: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="With descriptor_sets: one SMILES of the constitution (stereo marks not needed) whose atoms carry "
                    "atom-map numbers equal to their IUPAC locants, so that '5S' means the atom mapped :5; every locant "
                    "in the descriptor sets needs a numbered atom, and the constitution must match the named "
                    "compound (check the returned formula and bonds). Write the ring atoms in locant order "
                    "(1, 2, 3, 3a, 4, ... 7a) so that each written bond joins consecutive locants, then close the "
                    "fusion bond and add bridge atoms between the bridgeheads the name gives ('4,7-methano': atom 8 "
                    "bonded to 4 and 7). Without "
                    "descriptor_sets: isomeric SMILES whose configurations are to be described. " + _SMILES_HELP,
    )
    descriptor_sets: list[str] | None = Field(
        default=None,
        max_length=12,
        description="Stereodescriptor sets to translate, one per configuration, e.g. the answer options "
                    "['(1R,2S,3R)', '(1R,2R,3S)'] or whole names '(1R,2S)-2-methylcyclohexan-1-ol'. Lower-case "
                    "r/s (pseudoasymmetric) and E/Z are accepted. Options with a different constitution need their "
                    "own call.",
    )
    locants: dict[str, str] | None = Field(default=None, description=_LOCANTS_HELP)
    distance_pairs: list[list[str]] | None = Field(
        default=None, description='Optional locant pairs whose 3D distance (angstrom) to report in each configuration, '
                                  'e.g. [["9", "5"]] for a substituent atom mapped :9 and ring atom :5.')


def execute_physis_stereo(smiles: list[str], descriptor_sets: list[str] | None = None,
                          locants: dict[str, str] | None = None, distance_pairs: list[list[str]] | None = None) -> Any:
    from tribos.physis.chemistry import stereo_configurations
    from tribos.tools.registry import ErrorType, ToolResult

    try:
        data = stereo_configurations(smiles, descriptor_sets, locants, distance_pairs)
    except ValueError as exc:
        return ToolResult(success=False, tool_name="physis_stereo", error=str(exc), error_type=ErrorType.VALIDATION_ERROR)
    except Exception as exc:  # noqa: BLE001 - RDKit raises its own exception types for malformed structures
        return ToolResult(success=False, tool_name="physis_stereo", error=f"{type(exc).__name__}: {exc}"[:500],
                          error_type=ErrorType.VALIDATION_ERROR)
    return ToolResult(success=True, tool_name="physis_stereo", data=data, canonical_ids={},
                      metadata={"engine": data["method"], "verified": True})


def register_tools(registry: Any) -> None:
    """Register the Physis physical/mathematical reference tools in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="physis_fluid_properties",
            description=(
                "Thermophysical properties of real fluids (water/steam, refrigerants such as R134a or R123, CO2, air, "
                "nitrogen, ammonia, hydrocarbons; 130+ fluids) from their reference equations of state via CoolProp: "
                "density, heat capacities, enthalpy, entropy, compressibility factor, speed of sound, viscosity, "
                "thermal conductivity and the Joule-Thomson coefficient at a temperature and pressure; the final "
                "temperature of a throttling (isenthalpic, Joule-Thomson) or isentropic expansion; saturation "
                "pressure or temperature and latent heat."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisFluidInput,
            canonical_id_types=[],
            timeout_seconds=20.0,
            tags=["thermodynamics", "fluids", "coolprop", "equation_of_state", "refrigerant", "steam", "joule_thomson",
                  "enthalpy", "entropy", "saturation", "thermophysical_properties"],
            is_async=False,
        ),
        executor=execute_physis_fluid_properties,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_molecule",
            description=(
                "Exact structure facts for organic molecules given as SMILES (RDKit): molecular formula, molecular "
                "weight and monoisotopic mass, degree of unsaturation, stereocentres and double bonds with CIP "
                "R/S/E/Z labels, whether the molecule is chiral or meso, the number of stereoisomers of the "
                "constitution (enantiomer pairs and achiral forms, e.g. peaks on chiral and achiral HPLC), the number "
                "of chemically distinct hydrogen and carbon environments (1H and 13C NMR signal counts), the molecular point group (Schoenflies, of the relaxed 3D conformer and of the most symmetric low-energy one), and whether "
                "two structures are identical, enantiomers, diastereomers or constitutional isomers."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisMoleculeInput,
            canonical_id_types=[],
            timeout_seconds=30.0,
            tags=["chemistry", "organic_chemistry", "smiles", "molecular_formula", "stereochemistry", "nmr",
                  "stereoisomers", "chirality", "rdkit"],
            is_async=False,
        ),
        executor=execute_physis_molecule,
    )

    registry.register(
        ToolUniverseEntry(
            name="physis_stereo",
            description=(
                "Translate stereodescriptors into 3D geometry (RDKit CIP labeler and 3D embedding): give the "
                "constitution as SMILES with atom-map numbers equal to the IUPAC locants and the descriptor sets of "
                "the candidate structures (e.g. answer options '(1R,2S,3R)', '(2R,3S,4r)'); for each it "
                "returns which substituents lie on the same face of every ring (cis/trans, syn/anti, endo/exo) and "
                "whether two sets are the same compound or enantiomers. Use it to pick the option whose descriptors "
                "match the geometry a reaction gives (cis addition, the endo rule, facial selectivity) instead of "
                "assigning R/S by hand."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisStereoInput,
            canonical_id_types=[],
            timeout_seconds=30.0,
            tags=["chemistry", "organic_chemistry", "stereochemistry", "cip", "stereodescriptors", "endo", "exo",
                  "cis", "trans", "diels_alder", "rdkit"],
            is_async=False,
        ),
        executor=execute_physis_stereo,
    )

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

    registry.register(
        ToolUniverseEntry(
            name="physis_propagate_uncertainty",
            description=(
                "Propagate measurement uncertainty through a formula: first-order GUM (linear) with sensitivity "
                "coefficients and a contribution budget, vectorised Monte Carlo with a coverage interval, optional "
                "correlated inputs and optional CODATA constant autofill. Reports the result as value +/- U (k=2)."
            ),
            domain="physis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=PhysisUncertaintyInput,
            canonical_id_types=[],
            timeout_seconds=30.0,
            tags=["uncertainty", "error_propagation", "gum", "monte_carlo", "tolerance", "measurement", "statistics"],
            is_async=False,
        ),
        executor=execute_physis_uncertainty,
    )


def _uncertainty_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The propagated uncertainty of the last successful uncertainty run, for the browser's result card."""
    for result in reversed(list(tool_results.values())):
        if getattr(result, "success", False) and getattr(result, "tool_name", "") == "physis_propagate_uncertainty":
            data = getattr(result, "data", {}) or {}
            if data.get("nominal_value") is not None:
                return {"uncertainty": data}
    return {}


def register_hooks() -> None:
    """Register the Physis hooks (idempotent)."""
    from tribos.extensions import hooks

    hooks.register_artifact_builder("uncertainty", _uncertainty_artifact)


register_hooks()


__all__ = [
    "PhysisConstantsInput",
    "PhysisEncyclopediaInput",
    "PhysisMaterialsInput",
    "PhysisOeisInput",
    "PhysisUncertaintyInput",
    "PhysisUnitsInput",
    "PhysisWolframInput",
    "execute_physis_constants",
    "execute_physis_encyclopedia",
    "execute_physis_materials",
    "execute_physis_oeis",
    "execute_physis_uncertainty",
    "execute_physis_units",
    "execute_physis_wolfram",
    "get_physis_engine",
    "register_hooks",
    "register_tools",
]
