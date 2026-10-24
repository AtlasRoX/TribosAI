"""Physis — Physical Constants, Dimensional Analysis & Reference Data Engine."""

from .clients import (
    BUILTIN_MATERIALS,
    PhysisClients,
    normalize_oeis_response,
    search_builtin_materials,
)
from .constants import (
    parse_nist_allascii,
    parse_nist_ascii_value,
    search_constants,
)
from .engine import PhysisEngine
from .units import (
    check_dimensional_homogeneity,
    convert_units,
    get_unit_registry,
)

__all__ = [
    "BUILTIN_MATERIALS",
    "PhysisClients",
    "PhysisEngine",
    "check_dimensional_homogeneity",
    "convert_units",
    "get_unit_registry",
    "normalize_oeis_response",
    "parse_nist_allascii",
    "parse_nist_ascii_value",
    "search_builtin_materials",
    "search_constants",
]
