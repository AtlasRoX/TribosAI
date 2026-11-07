"""Molecular point groups (Schoenflies) from a structure's 3D geometry.

A question such as "what is the molecular symmetry group of product 3?" is decided by the structure, but read off by
eye it is easy to miss an inversion centre or a perpendicular C2 axis. Here the structure is embedded in 3D (several
ETKDG conformers relaxed with MMFF, or UFF when MMFF has no parameters; the lowest energy is kept), centred on its centre
of mass, and every candidate symmetry element is tested against the atoms:

- candidate axes: the principal axes of inertia, the directions to each atom, the midpoints of pairs of equivalent
  atoms and the normals of planes through the centre and two atoms;
- a proper axis C_n (n = 2..8) or a mirror plane is accepted when it maps every atom onto an atom of the same element
  within the tolerance (0.3 angstrom by default);
- the group follows the standard decision chart: linear (C_inf_v, D_inf_h), cubic and icosahedral groups (T, Td, Th,
  O, Oh, I, Ih), D_nh / D_nd / D_n, C_nh / C_nv / S_2n / C_n, and C_s / C_i / C_1.

The group of the heavy-atom framework is reported as well: textbook answers often idealise freely rotating methyl
groups, which the all-atom geometry of one conformer does not.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np

TOLERANCE = 0.3  # angstrom
_ANGLE_TOL = 0.05  # radians, for deduplicating directions
_MAX_ORDER = 8


def _rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    a = axis / np.linalg.norm(axis)
    c, s = np.cos(angle), np.sin(angle)
    x, y, z = a
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def _reflection(normal: np.ndarray) -> np.ndarray:
    n = normal / np.linalg.norm(normal)
    return np.eye(3) - 2.0 * np.outer(n, n)


class _Molecule:
    def __init__(self, coords: np.ndarray, elements: list[str], masses: np.ndarray, tol: float) -> None:
        centre = (masses[:, None] * coords).sum(axis=0) / masses.sum()
        self.x = coords - centre
        self.elements = elements
        self.masses = masses
        self.tol = tol
        self._groups = {e: np.where(np.array(elements) == e)[0] for e in set(elements)}

    def is_symmetry(self, op: np.ndarray) -> bool:
        y = self.x @ op.T
        for idx in self._groups.values():
            pts, img = self.x[idx], y[idx]
            d = np.linalg.norm(img[:, None, :] - pts[None, :, :], axis=2)
            if not np.all(d.min(axis=1) < self.tol):
                return False
        return True

    def candidate_directions(self) -> list[np.ndarray]:
        dirs: list[np.ndarray] = []
        inertia = sum(m * (np.dot(r, r) * np.eye(3) - np.outer(r, r)) for m, r in zip(self.masses, self.x))
        _, vecs = np.linalg.eigh(inertia)
        dirs.extend(vecs.T)
        far = [i for i in range(len(self.x)) if np.linalg.norm(self.x[i]) > self.tol]
        dirs.extend(self.x[i] for i in far)
        for idx in self._groups.values():
            members = [i for i in idx if i in set(far)]
            for i, j in itertools.combinations(members[:40], 2):
                if abs(np.linalg.norm(self.x[i]) - np.linalg.norm(self.x[j])) < self.tol:
                    dirs.append(self.x[i] + self.x[j])  # midpoint: a C2 axis or a mirror normal's partner
                    dirs.append(self.x[i] - self.x[j])  # the normal of a mirror plane swapping i and j
        for i, j in itertools.combinations(far[:30], 2):
            dirs.append(np.cross(self.x[i], self.x[j]))
        out: list[np.ndarray] = []
        for d in dirs:
            n = np.linalg.norm(d)
            if n < 1e-6:
                continue
            u = d / n
            if all(abs(abs(float(np.dot(u, v))) - 1.0) > 1 - np.cos(_ANGLE_TOL) for v in out):
                out.append(u)
        return out

    def axis_order(self, axis: np.ndarray) -> int:
        # Every power of C_n must hold: a 51.4 degree turn maps a hexagon onto itself within 0.21 angstrom, but its
        # square (102.9 against 120 degrees) does not, so benzene has no C7.
        for n in range(_MAX_ORDER, 1, -1):
            if all(self.is_symmetry(_rotation(axis, 2 * np.pi * k / n)) for k in range(1, n // 2 + 1)):
                return n
        return 1

    def has_mirror(self, normal: np.ndarray) -> bool:
        return self.is_symmetry(_reflection(normal))

    def has_improper(self, axis: np.ndarray, n: int) -> bool:
        return self.is_symmetry(_reflection(axis) @ _rotation(axis, 2 * np.pi / n))


_MERGE_COS = float(np.cos(np.radians(10.0)))


def _merge(found: list[tuple[np.ndarray, int]]) -> list[tuple[np.ndarray, int]]:
    """One entry per symmetry element: directions within 10 degrees are the same axis or plane normal, found from
    several candidates of a relaxed (not exactly symmetric) geometry. Distinct elements of a real group are farther
    apart (cubic axes 54.7 degrees, the C2 axes of D6h 30 degrees). The highest order found is kept."""
    out: list[tuple[np.ndarray, int]] = []
    for u, n in sorted(found, key=lambda t: -t[1]):
        if all(abs(float(np.dot(u, v))) < _MERGE_COS for v, _ in out):
            out.append((u, n))
    return out


def _is_linear(m: _Molecule) -> bool:
    if len(m.x) < 3:
        return True
    _, s, vt = np.linalg.svd(m.x - m.x.mean(axis=0))
    return bool(s[1] < m.tol and s[2] < m.tol)


def classify(coords: np.ndarray, elements: list[str], masses: np.ndarray, tol: float = TOLERANCE) -> dict[str, Any]:
    """The Schoenflies point group of a geometry, with the symmetry elements found."""
    m = _Molecule(np.asarray(coords, float), list(elements), np.asarray(masses, float), tol)
    inversion = m.is_symmetry(-np.eye(3))
    if _is_linear(m):
        return {"point_group": "D∞h" if inversion else "C∞v", "elements": ["C∞"] + (["i"] if inversion else [])}
    dirs = m.candidate_directions()
    axes = _merge([(u, m.axis_order(u)) for u in dirs if True])
    axes = [(u, n) for u, n in axes if n >= 2]
    mirrors = [u for u, _ in _merge([(u, 1) for u in dirs if m.has_mirror(u)])]
    elements = (["i"] if inversion else []) + [f"C{n}" for _, n in axes] + ["σ"] * len(mirrors)
    summary = {"proper_axes": sorted((n for _, n in axes), reverse=True), "mirror_planes": len(mirrors),
               "inversion": inversion}
    high = [(u, n) for u, n in axes if n >= 3]
    if len(high) >= 2:
        orders = {n for _, n in high}
        if 5 in orders:
            group = "Ih" if inversion else "I"
        elif 4 in orders:
            group = "Oh" if inversion else "O"
        else:
            group = "Th" if inversion else ("Td" if mirrors else "T")
        return {"point_group": group, **summary}
    if not axes:
        group = "Cs" if mirrors else ("Ci" if inversion else "C1")
        return {"point_group": group, **summary}
    n = max(k for _, k in axes)
    main = next(u for u, k in axes if k == n)
    if n == 2:
        # Of several C2 axes, the principal one is any; D2 groups have three.
        pass
    perpendicular_c2 = [u for u, k in axes if k >= 2 and abs(float(np.dot(u, main))) < 0.1]
    sigma_h = m.has_mirror(main)
    sigma_v = [u for u in mirrors if abs(float(np.dot(u, main))) < 0.1]
    if len(perpendicular_c2) >= n:
        if sigma_h:
            group = f"D{n}h"
        elif len(sigma_v) >= n:
            group = f"D{n}d"
        else:
            group = f"D{n}"
    elif sigma_h:
        group = f"C{n}h"
    elif len(sigma_v) >= n:
        group = f"C{n}v"
    elif m.has_improper(main, 2 * n):
        group = f"S{2 * n}"
    else:
        group = f"C{n}"
    return {"point_group": group, **summary}


def _conformer(mol: Any, conformers: int = 12, seed: int = 0x5EED) -> tuple[Any, list[tuple[int, float]], str] | None:
    """The molecule with hydrogens, embedded and relaxed: (conformer id, energy above the minimum) from the lowest up,
    and the force field used."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mh = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    ids = list(AllChem.EmbedMultipleConfs(mh, numConfs=conformers, params=params))
    if not ids:
        params.useRandomCoords = True
        ids = list(AllChem.EmbedMultipleConfs(mh, numConfs=conformers, params=params))
    if not ids:
        return None
    if AllChem.MMFFHasAllMoleculeParams(mh):
        field = "MMFF94"
        results = AllChem.MMFFOptimizeMoleculeConfs(mh, maxIters=2000)
    elif AllChem.UFFHasAllMoleculeParams(mh):
        field = "UFF"
        results = AllChem.UFFOptimizeMoleculeConfs(mh, maxIters=2000)
    else:
        # An unrelaxed embedding of, say, hexavalent sulphur is not its real shape: no group rather than a wrong one.
        raise ValueError("no force-field parameters for this structure's atoms (e.g. hypervalent main-group "
                         "centres): its geometry, and so its point group, cannot be computed here")
    energies = [e for _, e in results]
    order = sorted(range(len(ids)), key=lambda k: energies[k])
    window = [(ids[k], energies[k] - energies[order[0]]) for k in order]
    return mh, window, field


def point_group(smiles: str, tol: float = TOLERANCE) -> dict[str, Any]:
    """Point group of a structure's lowest-energy conformer, and of its heavy-atom framework."""
    from rdkit import Chem

    from .chemistry import _parse

    mol = _parse(smiles)
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    built = _conformer(mol)
    if built is None:
        raise ValueError("no 3D geometry could be embedded for this structure")
    mh, window, field = built
    elements = [a.GetSymbol() for a in mh.GetAtoms()]
    masses = np.array([a.GetMass() for a in mh.GetAtoms()])
    heavy = [i for i, e in enumerate(elements) if e != "H"]

    def groups(conf_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        pos = mh.GetConformer(conf_id).GetPositions()
        full = classify(pos, elements, masses, tol)
        frame = classify(pos[heavy], [elements[i] for i in heavy], masses[heavy], tol) if len(heavy) >= 2 else full
        return full, frame

    full, frame = groups(window[0][0])
    # Low-energy conformers can be more symmetric than the minimum (a relaxed geometry is rarely exact); the most
    # symmetric one within the window is reported beside it.
    best = (group_order(full["point_group"]), full["point_group"], 0.0)
    for conf_id, de in window[1:]:
        if de > SYMMETRIC_WINDOW_KCAL:
            break
        alt, _ = groups(conf_id)
        if group_order(alt["point_group"]) > best[0]:
            best = (group_order(alt["point_group"]), alt["point_group"], de)
    return {
        "smiles": Chem.MolToSmiles(mol),
        "point_group": full["point_group"],
        "heavy_atom_framework": frame["point_group"],
        "most_symmetric_low_energy": {"point_group": best[1], "kcal_per_mol_above_minimum": round(best[2], 2)},
        "proper_axes": full.get("proper_axes", []),
        "mirror_planes": full.get("mirror_planes", 0),
        "inversion_centre": bool(full.get("inversion", False)),
        "geometry": f"lowest-energy of up to 12 ETKDG conformers relaxed with {field}",
        "tolerance_angstrom": tol,
        "note": ("The group is that of one relaxed conformer. A flexible molecule can be drawn in more symmetric "
                 "idealised conformations (planar, eclipsed); textbook answers usually take the most symmetric "
                 "reasonable one."),
    }


SYMMETRIC_WINDOW_KCAL = 1.5


def group_order(group: str) -> int:
    """The number of operations of a point group (infinite groups count as 10**6)."""
    fixed = {"C1": 1, "Cs": 2, "Ci": 2, "T": 12, "Td": 24, "Th": 24, "O": 24, "Oh": 48, "I": 60, "Ih": 120}
    if group in fixed:
        return fixed[group]
    if "∞" in group:
        return 10**6
    import re as _re

    m = _re.fullmatch(r"([CDS])(\d+)([hvd]?)", group)
    if not m:
        return 1
    kind, n, suffix = m.group(1), int(m.group(2)), m.group(3)
    if kind == "S":
        return n
    if kind == "C":
        return n * (2 if suffix else 1)
    return 2 * n * (2 if suffix else 1)


__all__ = ["classify", "group_order", "point_group"]
