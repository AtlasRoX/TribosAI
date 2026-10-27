"""Materials & Physical Properties."""

from ...memory.semantic import MATERIALS_CATALOG, MaterialRecord


def get_material(name_or_key: str) -> MaterialRecord | None:
    key = name_or_key.strip().lower().replace("-", "_").replace(" ", "_")
    if key in MATERIALS_CATALOG:
        return MATERIALS_CATALOG[key]
    for mat in MATERIALS_CATALOG.values():
        if key in mat.name.lower().replace("-", "_").replace(" ", "_"):
            return mat
    return None


def list_materials() -> list[str]:
    return [m.name for m in MATERIALS_CATALOG.values()]


__all__ = ["MaterialRecord", "get_material", "list_materials"]
