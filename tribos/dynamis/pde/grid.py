"""Rectangular grids and boundary conditions for the PDE solvers.

A grid is a uniform lattice on a rectangular domain, one axis per dimension. A bounded axis includes both end
points; a periodic axis leaves out its right end, which is the same point as the left one, so the ring has no
duplicated node. Boundary conditions are named per edge ("x0", "x1", "y0", "y1") and are one of:

- dirichlet: the value u = g is prescribed;
- neumann: the outward normal derivative du/dn = g is prescribed (0 is an insulated or reflecting edge);
- periodic: the field wraps around (both edges of the axis must be periodic).

A prescribed g is a number or an expression in x, y and t, parsed through the safe parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .expressions import evaluate_points, parse_field

# The edges of a domain, in the order they are used.
EDGE_NAMES: tuple[str, ...] = ("x0", "x1", "y0", "y1")
AXIS_NAMES: tuple[str, ...] = ("x", "y")
BOUNDARY_KINDS: tuple[str, ...] = ("dirichlet", "neumann", "periodic")


@dataclass(frozen=True)
class Grid:
    """A uniform rectangular grid: one coordinate array per axis, and whether each axis is periodic."""

    axes: tuple[np.ndarray, ...]
    periodic: tuple[bool, ...]
    domain: tuple[tuple[float, float], ...]

    @property
    def dimension(self) -> int:
        return len(self.axes)

    @property
    def shape(self) -> tuple[int, ...]:
        """The number of points per axis."""
        return tuple(len(a) for a in self.axes)

    @property
    def spacing(self) -> tuple[float, ...]:
        """The grid spacing per axis."""
        return tuple(float(a[1] - a[0]) for a in self.axes)

    @property
    def size(self) -> int:
        return int(np.prod(self.shape))

    def mesh(self) -> list[np.ndarray]:
        """The coordinate meshes, indexed [x, y]."""
        return list(np.meshgrid(*self.axes, indexing="ij"))

    def weights(self) -> np.ndarray:
        """Quadrature weights: the trapezoidal rule on a bounded axis and the rectangle rule on a periodic one.

        These are the weights under which the discrete Laplacian with Neumann ghost points is symmetric, so the mass
        and the energy they measure are the quantities the schemes conserve exactly.
        """
        out = np.ones(self.shape)
        for axis, (coords, periodic) in enumerate(zip(self.axes, self.periodic, strict=True)):
            w = np.full(len(coords), self.spacing[axis])
            if not periodic:
                w[0] *= 0.5
                w[-1] *= 0.5
            shape = [1] * self.dimension
            shape[axis] = len(coords)
            out = out * w.reshape(shape)
        return out


def make_grid(domain: tuple[tuple[float, float], ...], num_points: int, periodic: tuple[bool, ...]) -> Grid:
    """A uniform grid on `domain` with `num_points` points per axis (a periodic axis leaves out its right end)."""
    axes: list[np.ndarray] = []
    for axis, (lo, hi) in enumerate(domain):
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            raise ValueError(f"Domain interval {axis} must be a finite, increasing range, got ({lo}, {hi}).")
        axes.append(np.linspace(float(lo), float(hi), int(num_points), endpoint=not periodic[axis]))
    return Grid(axes=tuple(axes), periodic=tuple(bool(p) for p in periodic), domain=tuple(domain))


def normalise_boundary(boundary: dict[str, Any] | str | None, dimension: int) -> dict[str, str]:
    """The boundary kind of every edge of the domain; an edge the caller left out is Dirichlet.

    A single string applies to every edge. An axis key ("x": "periodic") applies to both edges of that axis. Only
    the edges of the dimension in play are kept, so a 1D problem cannot silently carry a "y0" condition.
    """
    names = EDGE_NAMES[: 2 * dimension]
    if isinstance(boundary, str):
        raw: dict[str, Any] = dict.fromkeys(names, boundary)
    else:
        raw = {}
        for key, value in (boundary or {}).items():
            key = str(key).strip().lower()
            if key in AXIS_NAMES:
                raw.setdefault(f"{key}0", value)
                raw.setdefault(f"{key}1", value)
            else:
                raw[key] = value
    unknown = sorted(set(raw) - set(EDGE_NAMES))
    if unknown:
        raise ValueError(f"Unknown boundary edge(s) {unknown}; the edges are {', '.join(names)}.")
    extra = sorted(set(raw) - set(names))
    if extra:
        raise ValueError(f"A {dimension}D domain has no edge(s) {extra}; its edges are {', '.join(names)}.")
    out: dict[str, str] = {}
    for name in names:
        kind = str(raw.get(name, "dirichlet")).strip().lower()
        if kind not in BOUNDARY_KINDS:
            raise ValueError(
                f"Unknown boundary condition {raw.get(name)!r} on edge {name!r}; expected one of {', '.join(BOUNDARY_KINDS)}."
            )
        out[name] = kind
    for axis in AXIS_NAMES[:dimension]:
        if (out[f"{axis}0"] == "periodic") != (out[f"{axis}1"] == "periodic"):
            raise ValueError(f"Edge {axis}0 or {axis}1 is periodic but the other is not; a periodic axis must close on itself.")
    return out


def periodic_axes(boundary: dict[str, str], dimension: int) -> tuple[bool, ...]:
    return tuple(boundary[f"{axis}0"] == "periodic" for axis in AXIS_NAMES[:dimension])


class BoundaryData:
    """The prescribed values g on the Dirichlet and Neumann edges, parsed once and evaluated at any time."""

    def __init__(self, grid: Grid, boundary: dict[str, str], values: dict[str, Any] | None, parameters: dict[str, float]):
        self.grid = grid
        self.boundary = boundary
        self._exprs: dict[str, Any] = {}
        self._numbers: dict[str, float] = {}
        symbols = (*AXIS_NAMES[: grid.dimension], "t")
        for edge, value in (values or {}).items():
            edge = str(edge).strip().lower()
            if edge not in boundary:
                raise ValueError(f"A boundary value was given for {edge!r}, which is not an edge of this domain.")
            if boundary[edge] == "periodic":
                raise ValueError(f"Edge {edge!r} is periodic and takes no boundary value.")
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self._numbers[edge] = float(value)
            else:
                self._exprs[edge] = parse_field(str(value), symbols=symbols, parameters=parameters)
        self.time_dependent = any("t" in {str(s) for s in e.free_symbols} for e in self._exprs.values())
        self.homogeneous = not self._exprs and all(v == 0.0 for v in self._numbers.values())

    def edge_points(self, edge: str) -> dict[str, np.ndarray]:
        """The coordinates of the grid nodes on one edge."""
        axes = self.grid.axes
        if self.grid.dimension == 1:
            return {"x": np.array([axes[0][0] if edge == "x0" else axes[0][-1]])}
        x, y = axes
        if edge in ("x0", "x1"):
            return {"x": np.full(len(y), x[0] if edge == "x0" else x[-1]), "y": y}
        return {"x": x, "y": np.full(len(x), y[0] if edge == "y0" else y[-1])}

    def values(self, edge: str, t: float) -> np.ndarray:
        """g along one edge at time t (zero when nothing was prescribed)."""
        points = self.edge_points(edge)
        length = len(next(iter(points.values())))
        if edge in self._exprs:
            symbols = (*AXIS_NAMES[: self.grid.dimension], "t")
            out = evaluate_points(self._exprs[edge], points, t=t, symbols=symbols)
            return np.broadcast_to(np.asarray(out, dtype=float), (length,)).copy()
        return np.full(length, self._numbers.get(edge, 0.0))


def edge_slice(edge: str, dimension: int) -> tuple[Any, ...]:
    """The index of an edge's nodes in a field indexed [x] or [x, y]."""
    axis = AXIS_NAMES.index(edge[0])
    index: list[Any] = [slice(None)] * dimension
    if dimension == 1:
        # A slice (not an int) keeps the 1D edge an array, so its length-1 value assigns without conversion.
        index[axis] = slice(0, 1) if edge.endswith("0") else slice(-1, None)
    else:
        index[axis] = 0 if edge.endswith("0") else -1
    return tuple(index)


def dirichlet_mask(grid: Grid, boundary: dict[str, str]) -> np.ndarray:
    """True at every node on a Dirichlet edge (corners included)."""
    mask = np.zeros(grid.shape, dtype=bool)
    for edge, kind in boundary.items():
        if kind == "dirichlet":
            mask[edge_slice(edge, grid.dimension)] = True
    return mask


def dirichlet_values(data: BoundaryData, t: float, out: np.ndarray) -> np.ndarray:
    """Write the Dirichlet values at time t into `out` (a field indexed like the grid) and return it."""
    for edge, kind in data.boundary.items():
        if kind == "dirichlet":
            out[edge_slice(edge, data.grid.dimension)] = data.values(edge, t)
    return out


def neumann_forcing(data: BoundaryData, t: float) -> np.ndarray:
    """The term the Neumann data adds to the discrete Laplacian, 2 g / h at every node of a Neumann edge.

    With a ghost node u_ghost = u_inner + 2 h g the centred second difference at the edge is
    (2 u_inner - 2 u_edge) / h^2 + 2 g / h: the first part is in the operator, this is the second.
    """
    out = np.zeros(data.grid.shape)
    for edge, kind in data.boundary.items():
        if kind == "neumann":
            h = data.grid.spacing[AXIS_NAMES.index(edge[0])]
            out[edge_slice(edge, data.grid.dimension)] += 2.0 * data.values(edge, t) / h
    return out


__all__ = [
    "AXIS_NAMES",
    "BOUNDARY_KINDS",
    "EDGE_NAMES",
    "BoundaryData",
    "Grid",
    "dirichlet_mask",
    "dirichlet_values",
    "edge_slice",
    "make_grid",
    "neumann_forcing",
    "normalise_boundary",
    "periodic_axes",
]
