"""Structures from systematic names of substituted rings and chains, with every parent atom numbered by its locant.

Models transcribe names into SMILES unreliably: in live runs a planner dropped substituents ("[C:4]" for a carbon
that carries a methyl) and left out the locant numbers, so the stereodescriptor translation (tribos.physis.chemistry)
never ran. The names of answer options are usually simple substitutive names, so code builds them instead:

    (1S,4R,5S,6S)-4,5,6-trimethylcyclohex-2-en-1-ol, 2,2,4,5-tetramethylcyclohexan-1-ol,
    1,2-dibromo-4,4-dimethylcyclopentanol, 5-isopropyl-3,4-dimethylocta-1,6-diene, but-2-ene

A parent chain or carbocycle (C1-C12, with -ene/-yne locants), principal suffixes -ol, -one, -amine, -thiol and
-al, and prefix substituents (alkyl, halo, hydroxy, alkoxy, nitro, amino, oxo, ...). Anything else (fused or bridged
ring systems, heterocycles, parenthesised substituents, esters) returns None: the caller falls back to a
model-written SMILES rather than to a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_STEMS = {"meth": 1, "eth": 2, "prop": 3, "but": 4, "pent": 5, "hex": 6, "hept": 7, "oct": 8, "non": 9, "dec": 10,
          "undec": 11, "dodec": 12}
_MULTIPLIERS = {"": 1, "di": 2, "tri": 3, "tetra": 4, "penta": 5, "hexa": 6}
# Prefix substituent -> (fragment SMILES, bond order to the parent atom).
_SUBSTITUENTS: dict[str, tuple[str, int]] = {
    "methyl": ("C", 1), "ethyl": ("CC", 1), "propyl": ("CCC", 1), "isopropyl": ("C(C)C", 1),
    "butyl": ("CCCC", 1), "isobutyl": ("CC(C)C", 1), "sec-butyl": ("C(C)CC", 1), "tert-butyl": ("C(C)(C)C", 1),
    "pentyl": ("CCCCC", 1), "hexyl": ("CCCCCC", 1), "vinyl": ("C=C", 1), "ethenyl": ("C=C", 1),
    "ethynyl": ("C#C", 1), "allyl": ("CC=C", 1), "phenyl": ("c1ccccc1", 1), "benzyl": ("Cc1ccccc1", 1),
    "fluoro": ("F", 1), "chloro": ("Cl", 1), "bromo": ("Br", 1), "iodo": ("I", 1), "hydroxy": ("O", 1),
    "methoxy": ("OC", 1), "ethoxy": ("OCC", 1), "nitro": ("[N+](=O)[O-]", 1), "amino": ("N", 1),
    "cyano": ("C#N", 1), "oxo": ("O", 2), "methylidene": ("C", 2), "methylene": ("C", 2), "acetyl": ("C(C)=O", 1),
    "mercapto": ("S", 1), "sulfanyl": ("S", 1),
}
_SUFFIXES: dict[str, tuple[str, int]] = {"ol": ("O", 1), "one": ("O", 2), "amine": ("N", 1), "thiol": ("S", 1),
                                         "al": ("O", 2)}

_DESCRIPTOR_PREFIX_RE = re.compile(r"^\s*(?:\((?:rel-)?[0-9a-zA-Z',*\s]+\)|rel|\(\s*[±+-]\s*\))\s*-\s*")
_PARENT_RE = re.compile(
    r"(?P<cyclo>cyclo)?(?P<stem>dodec|undec|meth|eth|prop|but|pent|hex|hept|oct|non|dec)(?P<a>a)?"
    r"(?:-(?P<unloc>\d+(?:,\d+)*)-(?P<unmult>di|tri)?(?P<un>en|yn)|(?P<ane>an))e?"
    r"(?:-?(?:(?P<sloc>\d+(?:,\d+)*)-)?(?P<smult>di|tri)?(?P<suffix>ol|one|amine|thiol|al))?$"
)
_PREFIX_RE = re.compile(
    r"(?P<loc>\d+(?:,\d+)*)-(?P<mult>di|tri|tetra|penta|hexa)?(?P<sub>" +
    "|".join(sorted((re.escape(k) for k in _SUBSTITUENTS), key=len, reverse=True)) + r")-?"
)


@dataclass(frozen=True)
class ParsedName:
    smiles: str  # parent atoms carry atom-map numbers equal to their locants
    descriptors: str  # "(1S,4R)" or ""
    parent_size: int
    ring: bool


def _split_descriptors(name: str) -> tuple[str, str]:
    text = name.strip()
    m = _DESCRIPTOR_PREFIX_RE.match(text)
    if not m:
        return "", text
    head = m.group(0).strip().rstrip("-").strip()
    return (head if head.startswith("(") and any(c.isdigit() or c in "RSEZrs" for c in head) else ""), text[m.end():]


def parse_name(name: str) -> ParsedName | None:
    """The locant-numbered structure of a simple substitutive name, or None when the name is outside the grammar."""
    try:
        from rdkit import Chem
    except ImportError:  # pragma: no cover - rdkit is a declared dependency
        return None
    descriptors, body = _split_descriptors(str(name or ""))
    body = body.strip().lower().replace(" ", "")
    if not body or len(body) > 160:
        return None
    # The parent is the first split whose tail is a parent name and whose head reads entirely as prefixes.
    parent = None
    attachments: list[tuple[int, str, int]] = []  # (locant, fragment, bond order)
    for start in range(len(body)):
        m = _PARENT_RE.match(body, start)
        if m and m.end() == len(body):
            found = _prefixes(body[:start].rstrip("-"))
            if found is not None:
                parent, attachments = m, found
                break
    if parent is None:
        return None
    size = _STEMS[parent.group("stem")]
    ring = bool(parent.group("cyclo"))
    if ring and size < 3:
        return None
    if parent.group("suffix"):
        mult = _MULTIPLIERS[parent.group("smult") or ""]
        locs = [int(x) for x in parent.group("sloc").split(",")] if parent.group("sloc") else (
            [1] if mult == 1 else ([1, size] if not ring and mult == 2 and parent.group("suffix") == "al" else []))
        if len(locs) != mult:
            return None
        frag, order = _SUFFIXES[parent.group("suffix")]
        attachments.extend((loc, frag, order) for loc in locs)
    multiple = [int(x) for x in parent.group("unloc").split(",")] if parent.group("unloc") else []
    if multiple and len(multiple) != _MULTIPLIERS[parent.group("unmult") or ""]:
        return None
    bond_order = 3 if parent.group("un") == "yn" else 2
    if any(not 1 <= loc <= size for loc, _, _ in attachments) or any(not 1 <= loc <= size for loc in multiple):
        return None
    try:
        smiles = _assemble(Chem, size, ring, multiple, bond_order, attachments)
    except Exception:  # noqa: BLE001 - an impossible valence means the name is outside the grammar or wrong
        return None
    return ParsedName(smiles=smiles, descriptors=descriptors, parent_size=size, ring=ring) if smiles else None


def _prefixes(prefix: str) -> list[tuple[int, str, int]] | None:
    """(locant, fragment, bond order) for "4,5,6-trimethyl", "2-bromo-4,4-dimethyl"; None unless all of it reads."""
    out: list[tuple[int, str, int]] = []
    pos = 0
    while pos < len(prefix):
        m = _PREFIX_RE.match(prefix, pos)
        if not m:
            return None
        locs = [int(x) for x in m.group("loc").split(",")]
        if len(locs) != _MULTIPLIERS[m.group("mult") or ""]:
            return None
        frag, order = _SUBSTITUENTS[m.group("sub")]
        out.extend((loc, frag, order) for loc in locs)
        pos = m.end()
    return out


def _assemble(Chem: Any, size: int, ring: bool, multiple: list[int], order: int,
              attachments: list[tuple[int, str, int]]) -> str | None:
    rw = Chem.RWMol()
    for loc in range(1, size + 1):
        atom = Chem.Atom(6)
        atom.SetAtomMapNum(loc)
        rw.AddAtom(atom)
    bond = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
    pairs = [(i, i + 1) for i in range(1, size)] + ([(size, 1)] if ring else [])
    for a, b in pairs:
        rw.AddBond(a - 1, b - 1, bond[order] if a in multiple else Chem.BondType.SINGLE)
    for loc, frag, frag_order in attachments:
        piece = Chem.MolFromSmiles(frag)
        if piece is None:
            return None
        offset = rw.GetNumAtoms()
        for atom in piece.GetAtoms():
            rw.AddAtom(atom)
        for b in piece.GetBonds():
            rw.AddBond(b.GetBeginAtomIdx() + offset, b.GetEndAtomIdx() + offset, b.GetBondType())
        rw.AddBond(loc - 1, offset, bond[frag_order])
    mol = rw.GetMol()
    Chem.SanitizeMol(mol)
    return Chem.MolToSmiles(mol)


__all__ = ["ParsedName", "parse_name"]
