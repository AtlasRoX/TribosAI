"""Materials & Physical Properties."""

from typing import Any

from ...memory.semantic import MATERIAL_DATA_NOTE, MATERIALS_CATALOG, MaterialRecord, find_material


def get_material(name_or_key: str) -> MaterialRecord | None:
    """Exact catalogue key, full name or alias only: an ambiguous or unknown name returns None, never a guess."""
    return find_material(name_or_key)


def list_materials() -> list[str]:
    return [m.name for m in MATERIALS_CATALOG.values()]


def material_properties(mat: MaterialRecord, temperature_celsius: float) -> dict[str, Any]:
    """The catalogue properties at a temperature. Strength and modulus are None outside the room-temperature range
    the values apply to, with the limitation stated, instead of an unsourced extrapolation."""
    at_ref = mat.at_reference_temperature(temperature_celsius)
    out: dict[str, Any] = {
        "name": mat.name,
        "category": mat.category,
        "density_kg_m3": mat.density_kg_m3,
        "poisson_ratio": mat.poisson_ratio,
        "yield_strength_mpa": mat.yield_at_temp(temperature_celsius),
        "ultimate_strength_mpa": mat.ultimate_strength_mpa if at_ref else None,
        "e_modulus_gpa": mat.e_at_temp(temperature_celsius),
        "thermal_conductivity_w_mk": mat.thermal_conductivity_w_mk,
        "thermal_expansion_1_k": mat.thermal_expansion_1_k,
        "temperature_celsius": temperature_celsius,
        "data_note": MATERIAL_DATA_NOTE,
    }
    if not at_ref:
        out["limitation"] = (
            f"No sourced property data at {temperature_celsius:g} C: strength and modulus are not reported. "
            "Elevated- and low-temperature properties depend strongly on alloy and temper; use code allowables "
            "(e.g. ASME II-D) or certified data."
        )
    return out


__all__ = ["MaterialRecord", "get_material", "list_materials", "material_properties"]
