"""Engineering calculators backed by standards, textbooks and typical material data (Physis).

`run_calculator(calculator, inputs, material)` runs one calculator: inputs are unit-checked with Pint, material
properties fill what the caller did not give, and the result carries the formulas, the utilisation of every limit
state, the validity checks of the method's assumptions and the reference (with its section) the formulas follow.
`list_calculators()` describes them all.
"""

from __future__ import annotations

from typing import Any

from . import fatigue, structural, thermofluid
from .core import Calculator, run
from .materials import MATERIALS_NOTE, find_material, list_materials

CALCULATORS: dict[str, Calculator] = {
    c.id: c for c in (*structural.CALCULATORS, *fatigue.CALCULATORS, *thermofluid.CALCULATORS)
}
ALIASES = {
    "beam_deflection": "beam", "cantilever": "beam", "buckling": "column_buckling", "euler_buckling": "column_buckling",
    "column": "column_buckling", "thin_wall_pressure_vessel": "pressure_vessel", "pressure_vessel_thickness":
    "pressure_vessel", "shaft_torsion": "shaft", "torsion": "shaft", "bolt": "bolt_preload", "bolt_torque":
    "bolt_preload", "pipe_flow": "pipe_pressure_drop", "pressure_drop": "pipe_pressure_drop", "darcy_weisbach":
    "pipe_pressure_drop", "lmtd": "heat_exchanger", "ntu": "heat_exchanger", "composite_wall": "layered_wall",
    "wall_conduction": "layered_wall", "goodman": "fatigue", "miner": "fatigue",
}


def get_calculator(name: str) -> Calculator:
    key = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = ALIASES.get(key, key)
    if key not in CALCULATORS:
        raise ValueError(f"Unknown calculator {name!r}; the calculators are {', '.join(CALCULATORS)}.")
    return CALCULATORS[key]


def run_calculator(calculator: str, inputs: dict[str, Any] | None = None, material: str | None = None) -> dict[str, Any]:
    return run(get_calculator(calculator), inputs, material)


def list_calculators() -> dict[str, Any]:
    return {
        "calculators": [c.describe() for c in CALCULATORS.values()],
        "materials": [{k: m[k] for k in ("id", "name", "family", "source")} for m in list_materials()],
        "materials_note": MATERIALS_NOTE,
        "units_note": "A bare number is taken in the input's SI unit; any unit may be written, e.g. '250 MPa', '12 mm', "
                      "or {value, unit, uncertainty}.",
    }


__all__ = ["CALCULATORS", "find_material", "get_calculator", "list_calculators", "run_calculator"]
