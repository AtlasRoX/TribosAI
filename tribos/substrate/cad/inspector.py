"""CAD geometry inspection for Tribos Substrate: ASCII STL meshes.

- Bounding box from the vertices.
- Surface area as the sum of the facet areas.
- Volume and centre of gravity by the divergence theorem (signed tetrahedra from the origin), reported only for a
  closed (watertight) mesh: for an open mesh they are undefined and are returned as None with the reason.
- Geometry diffing across revisions ("what changed between Rev A and Rev B").

Nothing is estimated or defaulted: text with no parsable facets is an error, never a stand-in part.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

Vec = tuple[float, float, float]

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_VERTEX = re.compile(rf"vertex\s+{_NUM}\s+{_NUM}\s+{_NUM}")


@dataclass
class BoundingBox:
    min_x_mm: float
    max_x_mm: float
    min_y_mm: float
    max_y_mm: float
    min_z_mm: float
    max_z_mm: float

    @property
    def length_mm(self) -> float:
        return abs(self.max_x_mm - self.min_x_mm)

    @property
    def width_mm(self) -> float:
        return abs(self.max_y_mm - self.min_y_mm)

    @property
    def height_mm(self) -> float:
        return abs(self.max_z_mm - self.min_z_mm)

    @property
    def bounding_volume_mm3(self) -> float:
        return self.length_mm * self.width_mm * self.height_mm


@dataclass
class GeometryProperties:
    file_name: str
    format: str  # stl
    bounding_box: BoundingBox
    surface_area_mm2: float
    volume_mm3: float | None  # None for an open mesh
    center_of_gravity_mm: tuple[float, float, float] | None
    material_density_kg_m3: float = 2700.0
    facet_count: int = 0
    watertight: bool = False
    note: str = ""

    @property
    def mass_kg(self) -> float | None:
        if self.volume_mm3 is None:
            return None
        return (self.volume_mm3 * 1e-9) * self.material_density_kg_m3  # mm^3 -> m^3

    def to_dict(self) -> dict[str, Any]:
        mass = self.mass_kg
        return {
            "file_name": self.file_name,
            "format": self.format,
            "bounding_box": asdict(self.bounding_box),
            "dimensions_mm": {
                "length": round(self.bounding_box.length_mm, 6),
                "width": round(self.bounding_box.width_mm, 6),
                "height": round(self.bounding_box.height_mm, 6),
            },
            "facet_count": self.facet_count,
            "watertight": self.watertight,
            "surface_area_mm2": self.surface_area_mm2,
            "volume_mm3": self.volume_mm3,
            "mass_kg": mass,
            "material_density_kg_m3": self.material_density_kg_m3,
            "center_of_gravity_mm": list(self.center_of_gravity_mm) if self.center_of_gravity_mm else None,
            "method": "facet areas; divergence-theorem volume and centroid (closed meshes only)",
            "note": self.note,
        }


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


class GeometryInspector:
    """Inspects ASCII STL meshes and diffs geometry across revisions."""

    @staticmethod
    def inspect_stl_ascii(
        content: str, file_name: str = "model.stl", density_kg_m3: float = 2700.0
    ) -> GeometryProperties:
        """Parse ASCII STL text (the file content itself, never a path) into exact mesh properties.

        Raises ValueError when no complete triangular facet can be parsed or the density is not positive."""
        if not math.isfinite(density_kg_m3) or density_kg_m3 <= 0:
            raise ValueError("material_density_kg_m3 must be a positive number.")
        vertices: list[Vec] = [
            (float(m.group(1)), float(m.group(2)), float(m.group(3))) for m in _VERTEX.finditer(content or "")
        ]
        if len(vertices) < 3 or len(vertices) % 3:
            raise ValueError(
                "No ASCII STL facets could be parsed (expected 'vertex x y z' lines in groups of three). Pass the "
                "STL text itself; file paths and binary STL are not read."
            )
        if not all(math.isfinite(c) for v in vertices for c in v):
            raise ValueError("The STL contains non-finite coordinates.")
        facets = [tuple(vertices[i:i + 3]) for i in range(0, len(vertices), 3)]

        area = 0.0
        volume6 = 0.0
        moment = [0.0, 0.0, 0.0]
        edges: Counter[tuple[Vec, Vec]] = Counter()
        for v0, v1, v2 in facets:
            area += 0.5 * _norm(_cross(_sub(v1, v0), _sub(v2, v0)))
            d = _dot(v0, _cross(v1, v2))  # 6 x signed volume of the tetrahedron (origin, v0, v1, v2)
            volume6 += d
            for k in range(3):
                moment[k] += d * (v0[k] + v1[k] + v2[k])
            for a, b in ((v0, v1), (v1, v2), (v2, v0)):
                edges[(a, b) if a <= b else (b, a)] += 1
        watertight = bool(edges) and all(n == 2 for n in edges.values())

        xs, ys, zs = zip(*vertices, strict=True)
        bbox = BoundingBox(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
        volume: float | None = None
        cog: tuple[float, float, float] | None = None
        note = ""
        if watertight and abs(volume6) > 0:
            volume = abs(volume6) / 6.0
            cog = (moment[0] / (4.0 * volume6), moment[1] / (4.0 * volume6), moment[2] / (4.0 * volume6))
        else:
            note = ("The mesh is not closed (some edges are not shared by exactly two facets), so volume, mass and "
                    "centre of gravity are undefined and not reported.")
        return GeometryProperties(
            file_name=file_name,
            format="stl",
            bounding_box=bbox,
            surface_area_mm2=area,
            volume_mm3=volume,
            center_of_gravity_mm=cog,
            material_density_kg_m3=density_kg_m3,
            facet_count=len(facets),
            watertight=watertight,
            note=note,
        )

    @classmethod
    def diff_geometries(
        cls, geom_a: GeometryProperties, geom_b: GeometryProperties
    ) -> dict[str, Any]:
        """Quantitative diff between Rev A and Rev B; volume, mass and centre-of-gravity deltas need closed meshes."""
        def delta(a: float | None, b: float | None) -> tuple[float | None, float | None]:
            if a is None or b is None:
                return None, None
            return b - a, ((b - a) / a * 100.0 if a else None)

        delta_vol, pct_vol = delta(geom_a.volume_mm3, geom_b.volume_mm3)
        delta_mass, pct_mass = delta(geom_a.mass_kg, geom_b.mass_kg)
        delta_area, pct_area = delta(geom_a.surface_area_mm2, geom_b.surface_area_mm2)
        delta_cog = (
            [b - a for a, b in zip(geom_a.center_of_gravity_mm, geom_b.center_of_gravity_mm, strict=True)]
            if geom_a.center_of_gravity_mm and geom_b.center_of_gravity_mm else None
        )
        changes = [abs(p) for p in (pct_vol, pct_mass, pct_area) if p is not None]
        return {
            "rev_a_file": geom_a.file_name,
            "rev_b_file": geom_b.file_name,
            "delta_volume_mm3": delta_vol,
            "pct_volume_change": pct_vol,
            "delta_mass_kg": delta_mass,
            "pct_mass_change": pct_mass,
            "delta_surface_area_mm2": delta_area,
            "pct_surface_area_change": pct_area,
            "delta_center_of_gravity_mm": delta_cog,
            "significant_change": any(p > 1.0 for p in changes),
            "summary": (
                f"Mass changed by {pct_mass:.4g}% ({geom_a.mass_kg:.6g} kg -> {geom_b.mass_kg:.6g} kg)"
                if pct_mass is not None and geom_a.mass_kg is not None and geom_b.mass_kg is not None
                else "Mass not compared: at least one mesh is not closed."
            ),
        }
