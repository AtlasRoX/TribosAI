"""Typical material properties for the engineering calculators.

These are representative room-temperature values from the standards and handbooks named in `source`, for
preliminary calculations. They are NOT design allowables: a design must use the minimum values of the governing
code or the supplier's certified data for the actual product form, thickness and temper.
"""

from __future__ import annotations

from typing import Any

MATERIALS_NOTE = (
    "Typical room-temperature properties for preliminary calculation, not design allowables: use the governing code's "
    "minimum values or certified supplier data for the actual product form, thickness and temper."
)

# Units: E in Pa, yield and ultimate strength in Pa, density in kg/m^3, k in W/(m*K), cte in 1/K.
_GPa, _MPa = 1e9, 1e6
MATERIALS: dict[str, dict[str, Any]] = {
    "s235": {
        "name": "Structural steel S235 (EN 10025-2)",
        "family": "steel",
        "E": 210 * _GPa, "nu": 0.30, "yield_strength": 235 * _MPa, "ultimate_strength": 360 * _MPa,
        "density": 7850.0, "k": 53.0, "cte": 12e-6,
        "source": "EN 10025-2 (fy, fu for t <= 16 mm); EN 1993-1-1 3.2.6 (E, nu, alpha); EN 1993-1-2 3.4.1.3 (k at 20 C)",
    },
    "s355": {
        "name": "Structural steel S355 (EN 10025-2)",
        "family": "steel",
        "E": 210 * _GPa, "nu": 0.30, "yield_strength": 355 * _MPa, "ultimate_strength": 470 * _MPa,
        "density": 7850.0, "k": 53.0, "cte": 12e-6,
        "source": "EN 10025-2 (fy, fu for t <= 16 mm); EN 1993-1-1 3.2.6 (E, nu, alpha); EN 1993-1-2 3.4.1.3 (k at 20 C)",
    },
    "a36": {
        "name": "Structural steel ASTM A36",
        "family": "steel",
        "E": 200 * _GPa, "nu": 0.26, "yield_strength": 250 * _MPa, "ultimate_strength": 400 * _MPa,
        "density": 7850.0, "k": 51.9, "cte": 11.7e-6,
        "source": "ASTM A36/A36M (minimum Fy, Fu); ASM Handbook Vol. 1 (E, nu, k, alpha)",
    },
    "ss304": {
        "name": "Stainless steel 304, annealed",
        "family": "stainless",
        "E": 193 * _GPa, "nu": 0.29, "yield_strength": 205 * _MPa, "ultimate_strength": 515 * _MPa,
        "density": 8000.0, "k": 16.2, "cte": 17.3e-6,
        "source": "ASTM A240 (minimum yield, tensile); ASM Handbook Vol. 1 (E, nu, k, alpha at 20-100 C)",
    },
    "ss316": {
        "name": "Stainless steel 316, annealed",
        "family": "stainless",
        "E": 193 * _GPa, "nu": 0.30, "yield_strength": 205 * _MPa, "ultimate_strength": 515 * _MPa,
        "density": 8000.0, "k": 16.3, "cte": 15.9e-6,
        "source": "ASTM A240 (minimum yield, tensile); ASM Handbook Vol. 1 (E, nu, k, alpha at 20-100 C)",
    },
    "al6061_t6": {
        "name": "Aluminium 6061-T6",
        "family": "aluminium",
        "E": 68.9 * _GPa, "nu": 0.33, "yield_strength": 276 * _MPa, "ultimate_strength": 310 * _MPa,
        "density": 2700.0, "k": 167.0, "cte": 23.6e-6,
        "source": "ASM Handbook Vol. 2, Properties of Wrought Aluminum Alloys (typical values)",
    },
    "al7075_t6": {
        "name": "Aluminium 7075-T6",
        "family": "aluminium",
        "E": 71.7 * _GPa, "nu": 0.33, "yield_strength": 503 * _MPa, "ultimate_strength": 572 * _MPa,
        "density": 2810.0, "k": 130.0, "cte": 23.6e-6,
        "source": "ASM Handbook Vol. 2, Properties of Wrought Aluminum Alloys (typical values)",
    },
    "ti6al4v": {
        "name": "Titanium Ti-6Al-4V (Grade 5), annealed",
        "family": "titanium",
        "E": 113.8 * _GPa, "nu": 0.342, "yield_strength": 880 * _MPa, "ultimate_strength": 950 * _MPa,
        "density": 4430.0, "k": 6.7, "cte": 8.6e-6,
        "source": "ASM Handbook Vol. 2, Properties of Titanium Alloys (typical values)",
    },
    "copper": {
        "name": "Copper C11000 (ETP), annealed",
        "family": "copper",
        "E": 115 * _GPa, "nu": 0.31, "yield_strength": 69 * _MPa, "ultimate_strength": 220 * _MPa,
        "density": 8890.0, "k": 388.0, "cte": 17.0e-6,
        "source": "ASM Handbook Vol. 2, Properties of Wrought Coppers (typical values)",
    },
    "concrete": {
        "name": "Normal-weight concrete C30/37",
        "family": "concrete",
        "E": 33 * _GPa, "nu": 0.20, "yield_strength": None, "ultimate_strength": 2.9 * _MPa,
        "compressive_strength": 30 * _MPa, "density": 2400.0, "k": 1.7, "cte": 10e-6,
        "source": "EN 1992-1-1 Table 3.1 (fck, fctm, Ecm), 3.1.3 (nu, alpha); k is a typical value (1.4-2.5)",
        "note": "Concrete has no yield strength; ultimate_strength is the mean tensile strength fctm.",
    },
    "peek": {
        "name": "PEEK, unfilled",
        "family": "polymer",
        "E": 3.6 * _GPa, "nu": 0.40, "yield_strength": 98 * _MPa, "ultimate_strength": 100 * _MPa,
        "density": 1300.0, "k": 0.29, "cte": 47e-6,
        "source": "Victrex PEEK 450G datasheet (typical values at 23 C, below Tg)",
    },
}

ALIASES: dict[str, str] = {
    "s235jr": "s235", "s355jr": "s355", "s355j2": "s355", "astm a36": "a36", "a36 steel": "a36", "mild steel": "a36",
    "304": "ss304", "304 stainless": "ss304", "aisi 304": "ss304", "stainless 304": "ss304", "1.4301": "ss304",
    "316": "ss316", "316l": "ss316", "aisi 316": "ss316", "stainless 316": "ss316", "1.4401": "ss316",
    "6061": "al6061_t6", "6061-t6": "al6061_t6", "al 6061-t6": "al6061_t6", "aluminium 6061": "al6061_t6",
    "aluminum 6061": "al6061_t6", "7075": "al7075_t6", "7075-t6": "al7075_t6", "al 7075-t6": "al7075_t6",
    "aluminium 7075": "al7075_t6", "aluminum 7075": "al7075_t6", "ti-6al-4v": "ti6al4v", "ti64": "ti6al4v",
    "grade 5 titanium": "ti6al4v", "titanium": "ti6al4v", "cu": "copper", "c11000": "copper", "c30/37": "concrete",
}


def find_material(name: str) -> tuple[str, dict[str, Any]]:
    """The material id and its properties, by id, alias or name (case-insensitive); ValueError when unknown."""
    key = " ".join(str(name or "").strip().lower().replace("_", " ").split())
    for candidate in (key, key.replace(" ", "_"), key.replace(" ", "").replace("-", "_"), ALIASES.get(key, "")):
        if candidate in MATERIALS:
            return candidate, MATERIALS[candidate]
    for mid, props in MATERIALS.items():
        if key and key == props["name"].lower():
            return mid, props
    raise ValueError(f"Unknown material {name!r}; known materials: {', '.join(sorted(MATERIALS))}.")


def list_materials() -> list[dict[str, Any]]:
    return [{"id": mid, **props} for mid, props in MATERIALS.items()]


__all__ = ["MATERIALS", "MATERIALS_NOTE", "find_material", "list_materials"]
