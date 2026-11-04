"""Tribos Physical & Industrial Engineering Substrate."""

from .cad.inspector import BoundingBox, GeometryInspector, GeometryProperties
from .cae.review import CAEGateResult, CAEReviewer
from .materials import MaterialRecord, get_material, list_materials
from .standards import StandardClause, check_asme_compliance, get_standard_clause

__all__ = [
    "BoundingBox",
    "CAEGateResult",
    "CAEReviewer",
    "GeometryInspector",
    "GeometryProperties",
    "MaterialRecord",
    "StandardClause",
    "check_asme_compliance",
    "get_material",
    "get_standard_clause",
    "list_materials",
]
