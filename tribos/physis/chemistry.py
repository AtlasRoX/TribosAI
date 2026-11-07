"""Cheminformatics for organic-chemistry questions: structure facts and stereodescriptors from SMILES (RDKit).

Two failure classes motivate it (docs/benchmarks/2026-11-06-failure-analysis.md, items 17 and 18): a model that has
the geometry of a product right still writes the wrong CIP descriptors, and it miscounts what a structure determines
exactly (formula, unsaturation, stereoisomers, distinct hydrogen environments). Both are mechanical given a structure,
so code answers them:

- `molecule_facts`: formula, masses, degree of unsaturation, stereocentres with CIP labels, chirality and meso forms,
  the number of stereoisomers of the constitution (enantiomer pairs and achiral forms), topologically distinct H and C
  environments, and how several structures relate (identical, enantiomers, diastereomers, constitutional isomers).
- `stereo_configurations`: translates descriptor sets such as "(1R,2S,3R)" into geometry. The atoms of a SMILES
  carry atom-map numbers equal to their IUPAC locants; each descriptor set is assigned with the CIP rules (new CIP
  labeler, pseudoasymmetric r/s included), the configuration is embedded in 3D, and for every ring the substituents of
  its stereocentres are listed by face, with cis/trans for each pair. A question's answer options then become
  statements about which groups sit on the same face, which is what the chemistry decides (endo/exo, syn/anti, cis
  addition).

RDKit is imported lazily, so importing this module (for the routing regex) costs nothing.
"""

from __future__ import annotations

import functools
import itertools
import re
from typing import Any

MAX_SMILES_CHARS = 600
MAX_MOLECULES = 8
MAX_HEAVY_ATOMS = 150
MAX_STEREOISOMERS = 1024
MAX_ENUMERATED_ELEMENTS = 10  # 2^10 configurations at most are enumerated and classified
MAX_SEARCH_ELEMENTS = 12  # descriptor search by brute force: 2^12 assignments at most
EMBED_SEED = 0x5EED

# A question about a structure that code can settle: stereodescriptors, stereoisomers, NMR environments, formulae.
# Not bare "chiral" (chiral fermions) or "stereo" (stereographic projection).
STRUCTURE_QUESTION_RE = re.compile(
    r"\b(?:SMILES|stereo(?:isomer|chem|cent|selectiv|specific|descriptor|genic)\w*|enantiomer\w*|diastereomer\w*|"
    r"diastereotopic|enantiotopic|epimer\w*|meso[\s-]+(?:compound|form|isomer)\w*|racemi[cz]\w*|achiral|"
    r"chiral(?:ity)?\s+(?:cent\w*|carbons?|atoms?|HPLC|column|compounds?|molecules?|auxiliar\w*|axis)|"
    r"optical(?:ly)?\s+(?:activ\w*|isomers?|rotation)|(?:1H|13C|proton|carbon)[\s-]*NMR|"
    r"chemically\s+(?:distinct|equivalent|different)|distinct\s+(?:hydrogen|carbon|proton)\w*|"
    r"molecular\s+formula|degrees?\s+of\s+unsaturation|(?:index|degrees?)\s+of\s+hydrogen\s+deficiency|"
    r"double[\s-]+bond\s+equivalents?|IUPAC\s+name|(?:cis|trans)[\s-]+isomers?|geometric(?:al)?\s+isomers?|"
    r"endo|exo|molecular\s+(?:symmetry|point\s+group)\w*|"
    r"(?:point|symmetry)\s+group\s+of\s+(?:the\s+)?(?:molecule|compound|product|ion|anion|cation)\w*)\b",
    re.IGNORECASE,
)
# A stereodescriptor set opening a chemical name, "(1S,2R)-", "(3aR,4S,7aS)-", "(R)-", "(2E,4Z)-", or an
# isomeric SMILES atom "[C@@H]". Case-sensitive: "(3s)" is a time.
_DESCRIPTOR_NAME_RE = re.compile(
    r"\((?:rel-)?(?:\d{1,3}[a-z]?'*[RSEZ]|[RSEZ])\*?(?:\s*,\s*\d{1,3}[a-z]?'*[RSEZrs]\*?)*\)-|\[[A-Z][a-z]?@{1,2}"
)


def is_structure_question(text: str) -> bool:
    """A question whose answer turns on a molecular structure that code can analyse."""
    t = text or ""
    return bool(STRUCTURE_QUESTION_RE.search(t) or _DESCRIPTOR_NAME_RE.search(t))


def _rdkit() -> Any:
    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:  # pragma: no cover - rdkit is a declared dependency
        raise RuntimeError("RDKit is not installed; structure analysis is unavailable") from exc
    RDLogger.DisableLog("rdApp.*")
    return Chem


def rdkit_version() -> str:
    try:
        from rdkit import rdBase

        return str(rdBase.rdkitVersion)
    except Exception:  # noqa: BLE001
        return "unknown"


def _parse(smiles: str) -> Any:
    Chem = _rdkit()
    s = str(smiles or "").strip()
    if not s:
        raise ValueError("empty SMILES")
    if len(s) > MAX_SMILES_CHARS:
        raise ValueError(f"SMILES longer than {MAX_SMILES_CHARS} characters")
    mol = Chem.MolFromSmiles(s)
    if mol is None:
        raise ValueError(f"not a valid SMILES (check valences, ring-closure digits and brackets): {s!r}")
    if mol.GetNumHeavyAtoms() > MAX_HEAVY_ATOMS:
        raise ValueError(f"molecule has more than {MAX_HEAVY_ATOMS} heavy atoms")
    # A bracket atom states its hydrogens, so "[C:4]" is a carbon with none: a radical. Models number atoms that way
    # meaning "carbon 4", which turned every stereocentre into a radical and every descriptor into an error. A mapped,
    # neutral atom written without hydrogens gets its normal valence back; the result says so.
    filled = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomMapNum() and atom.GetNumRadicalElectrons() and not atom.GetFormalCharge() and not atom.GetIsotope():
            atom.SetNumRadicalElectrons(0)
            atom.SetNoImplicit(False)
            filled += 1
    if filled:
        mol.UpdatePropertyCache(strict=False)
        Chem.SanitizeMol(mol)
        mol.SetIntProp(FILLED_H_PROP, filled)
    return mol


FILLED_H_PROP = "tribos_filled_hydrogens"
FILLED_H_NOTE = ("numbered atoms written without hydrogens ([C:4]) were read with their normal hydrogens ([CH:4]), "
                 "not as radicals")


# -- Descriptors ---------------------------------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"(\d{1,3}[a-z]?'*)?([RSrsEZ])\*?")
_GROUP_RE = re.compile(r"\(([^()]*)\)")


def _parse_token_list(body: str) -> list[tuple[str, str]] | None:
    body = re.sub(r"^\s*rel-?\s*", "", body.strip())
    if not body:
        return None
    out: list[tuple[str, str]] = []
    for token in body.split(","):
        m = _TOKEN_RE.fullmatch(token.strip())
        if not m:
            return None
        out.append((m.group(1) or "", m.group(2)))
    return out


def parse_descriptors(text: str) -> list[tuple[str, str]]:
    """[(locant, label)] from "(3aR,4S,7aS,8r)", "1S,2R", "(R)" or a whole name such as
    "(1R,2S)-2-methylcyclohexan-1-ol". A label without a locant has locant ""."""
    t = str(text or "").strip()
    direct = _parse_token_list(t.strip("()"))
    if direct is not None:
        return direct
    found: list[tuple[str, str]] = []
    for body in _GROUP_RE.findall(t):
        tokens = _parse_token_list(body)
        if tokens:
            found.extend(tokens)
    if not found:
        raise ValueError(f"no stereodescriptors found in {t[:80]!r}; give them as '(1S,4R)' or '1S,4R'")
    seen: dict[str, str] = {}
    for loc, label in found:
        if loc and seen.get(loc, label) != label:
            raise ValueError(f"locant {loc} has two descriptors in {t[:80]!r}")
        seen[loc] = label
    return found


# -- Atom labels ---------------------------------------------------------------------------------------------------
def _take_locants(mol: Any, locants: dict[str, str] | None) -> dict[int, str]:
    """Atom index -> locant label from the atom-map numbers (cleared afterwards, so they never affect symmetry)."""
    names = {str(k).strip(): str(v).strip() for k, v in (locants or {}).items()}
    out: dict[int, str] = {}
    used: dict[str, int] = {}
    for atom in mol.GetAtoms():
        n = atom.GetAtomMapNum()
        if not n:
            continue
        label = names.get(str(n), str(n))
        if label in used:
            raise ValueError(f"locant {label} is given to two atoms")
        used[label] = atom.GetIdx()
        out[atom.GetIdx()] = label
        atom.SetAtomMapNum(0)
    return out


def _group(atom: Any) -> str:
    """'CH3', 'OH', 'F', 'C(=O)' for an unnumbered substituent atom."""
    sym = atom.GetSymbol()
    h = atom.GetTotalNumHs()
    text = sym + ("H" + (str(h) if h > 1 else "") if h else "")
    if sym == "C" and any(b.GetBondTypeAsDouble() == 2.0 and b.GetOtherAtom(atom).GetSymbol() == "O" for b in atom.GetBonds()):
        text = "C(=O)"
    return text


def _atom_name(atom: Any, labels: dict[int, str]) -> str:
    loc = labels.get(atom.GetIdx())
    return f"{atom.GetSymbol()}{loc}" if loc else _group(atom)


def _centre_name(idx: int, mol: Any, labels: dict[int, str]) -> str:
    return labels.get(idx) or f"{mol.GetAtomWithIdx(idx).GetSymbol()}[atom {idx + 1}]"


# -- Stereo elements and CIP labels ----------------------------------------------------------------------------------
def _stereo_elements(mol: Any) -> list[tuple[str, int]]:
    """('atom', atom index) for tetrahedral centres and ('bond', bond index) for stereogenic double bonds."""
    Chem = _rdkit()
    out: list[tuple[str, int]] = []
    for info in Chem.FindPotentialStereo(Chem.Mol(mol)):
        if info.type == Chem.StereoType.Atom_Tetrahedral:
            out.append(("atom", int(info.centeredOn)))
        elif info.type == Chem.StereoType.Bond_Double:
            out.append(("bond", int(info.centeredOn)))
    return out


def _cip(mol: Any, perceive: bool = True) -> Any:
    """A copy with CIP labels. `perceive` first runs RDKit's stereo perception, which drops marks on atoms that are
    not stereogenic; configurations set by `_apply` skip it, because it also clears a cis/trans set on a double bond."""
    Chem = _rdkit()
    from rdkit.Chem import rdCIPLabeler

    m = Chem.Mol(mol)
    if perceive:
        Chem.AssignStereochemistry(m, cleanIt=True, force=True)
    rdCIPLabeler.AssignCIPLabels(m)
    return m


def _label_of(mol: Any, element: tuple[str, int]) -> str:
    kind, idx = element
    obj = mol.GetAtomWithIdx(idx) if kind == "atom" else mol.GetBondWithIdx(idx)
    return obj.GetProp("_CIPCode") if obj.HasProp("_CIPCode") else ""


def _apply(mol: Any, states: dict[tuple[str, int], int]) -> Any:
    Chem = _rdkit()
    rw = Chem.RWMol(mol)
    for (kind, idx), state in states.items():
        if kind == "atom":
            rw.GetAtomWithIdx(idx).SetChiralTag(
                Chem.ChiralType.CHI_TETRAHEDRAL_CW if state == 0 else Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
        else:
            bond = rw.GetBondWithIdx(idx)
            a, b = bond.GetBeginAtom(), bond.GetEndAtom()
            na = next((n.GetIdx() for n in a.GetNeighbors() if n.GetIdx() != b.GetIdx()), None)
            nb = next((n.GetIdx() for n in b.GetNeighbors() if n.GetIdx() != a.GetIdx()), None)
            if na is None or nb is None:
                continue
            bond.SetStereoAtoms(na, nb)
            bond.SetStereo(Chem.BondStereo.STEREOCIS if state == 0 else Chem.BondStereo.STEREOTRANS)
    return _cip(rw.GetMol(), perceive=False)


def _element_for_locant(mol: Any, elements: list[tuple[str, int]], labels: dict[int, str], loc: str,
                        letter: str) -> tuple[str, int]:
    by_label = {v: k for k, v in labels.items()}
    if letter in "EZ":
        bonds = [e for e in elements if e[0] == "bond"]
        if not loc:
            if len(bonds) == 1:
                return bonds[0]
            raise ValueError(f"'{letter}' has no locant and the structure has {len(bonds)} stereogenic double bonds")
        if loc not in by_label:
            raise ValueError(_missing_locant(loc, labels))
        idx = by_label[loc]
        hits = [e for e in bonds if idx in (mol.GetBondWithIdx(e[1]).GetBeginAtomIdx(), mol.GetBondWithIdx(e[1]).GetEndAtomIdx())]
        if len(hits) > 1:  # "2E" is the double bond from C2 to C3: prefer the partner with the next locant
            nxt = [e for e in hits if any(labels.get(i, "") == _next_locant(loc) for i in (
                mol.GetBondWithIdx(e[1]).GetBeginAtomIdx(), mol.GetBondWithIdx(e[1]).GetEndAtomIdx()))]
            hits = nxt or hits[:1]
        if not hits:
            raise ValueError(f"the atom with locant {loc} is not on a stereogenic double bond in this SMILES")
        return hits[0]
    atoms = [e for e in elements if e[0] == "atom"]
    if not loc:
        if len(atoms) == 1:
            return atoms[0]
        raise ValueError(f"'{letter}' has no locant and the structure has {len(atoms)} stereocentres")
    if loc not in by_label:
        raise ValueError(_missing_locant(loc, labels))
    element = ("atom", by_label[loc])
    if element not in atoms:
        raise ValueError(f"the atom with locant {loc} is not a stereocentre in this SMILES; check the structure "
                         "(constitution) and the locant numbering")
    return element


def _missing_locant(loc: str, labels: dict[int, str]) -> str:
    if not labels:
        return (f"locant {loc} is not on any atom: the SMILES has no atom-map numbers. Number each stereocentre with "
                f"its locant, e.g. [CH:{loc if loc.isdigit() else 1}], and name letter locants in `locants`")
    return (f"locant {loc} is not on any atom (numbered: {', '.join(sorted(labels.values(), key=_locant_key))}); "
            "number it in the SMILES, or name a letter locant in `locants`")


def _next_locant(loc: str) -> str:
    m = re.match(r"(\d+)", loc)
    return str(int(m.group(1)) + 1) if m else ""


def assign_descriptors(mol: Any, wanted: dict[tuple[str, int], str]) -> Any | None:
    """The molecule with the given CIP labels on the given stereo elements, or None if no configuration has them.
    Labels can depend on one another (pseudoasymmetric centres, rule-4/5 ties), so mismatches are flipped until
    stable and an exhaustive search follows when that does not settle."""
    targets = list(wanted)
    states = {e: 0 for e in targets}
    seen: set[tuple[int, ...]] = set()
    for _ in range(3 * len(targets) + 2):
        key = tuple(states[e] for e in targets)
        if key in seen:
            break
        seen.add(key)
        m = _apply(mol, states)
        wrong = [e for e in targets if _label_of(m, e) != wanted[e]]
        if not wrong:
            return m
        for e in wrong:
            states[e] ^= 1
    if len(targets) > MAX_SEARCH_ELEMENTS:
        return None
    for combo in itertools.product((0, 1), repeat=len(targets)):
        m = _apply(mol, dict(zip(targets, combo)))
        if all(_label_of(m, e) == wanted[e] for e in targets):
            return m
    return None


def _labels_dict(m: Any, elements: list[tuple[str, int]], labels: dict[int, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, idx in elements:
        code = _label_of(m, (kind, idx)) or "unspecified"
        if kind == "atom":
            out[_centre_name(idx, m, labels)] = code
        else:
            bond = m.GetBondWithIdx(idx)
            a, b = (_centre_name(i, m, labels) for i in (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
            out[f"{a}={b}"] = code
    return out


def _descriptor_text(m: Any, elements: list[tuple[str, int]], labels: dict[int, str]) -> str:
    parts = []
    for kind, idx in elements:
        code = _label_of(m, (kind, idx))
        if not code:
            continue
        if kind == "atom":
            loc = labels.get(idx)
        else:
            bond = m.GetBondWithIdx(idx)
            locs = [labels.get(i) for i in (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())]
            loc = min((x for x in locs if x), key=_locant_key, default=None)
        parts.append((loc or f"{m.GetAtomWithIdx(idx).GetSymbol()}[atom {idx + 1}]", code))
    parts.sort(key=lambda p: _locant_key(p[0]))
    return "(" + ",".join(f"{loc}{code}" for loc, code in parts) + ")" if parts else ""


def _locant_key(loc: str) -> tuple[int, str]:
    m = re.match(r"(\d+)(.*)", loc or "")
    return (int(m.group(1)), m.group(2)) if m else (10**6, loc or "")


# -- 3D geometry -------------------------------------------------------------------------------------------------------
def _embed(m: Any) -> Any | None:
    """A 3D conformer with hydrogens that keeps the assigned configuration, or None."""
    Chem = _rdkit()
    from rdkit.Chem import AllChem

    mh = Chem.AddHs(m)
    params = AllChem.ETKDGv3()
    params.randomSeed = EMBED_SEED
    if AllChem.EmbedMolecule(mh, params) != 0:
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mh, params) != 0:
            return None
    try:
        AllChem.MMFFOptimizeMolecule(mh, maxIters=500)
    except Exception:  # noqa: BLE001 - an unoptimised ETKDG geometry still has the right configuration
        pass
    return mh


def _geometry_keeps_labels(mh: Any, m: Any, elements: list[tuple[str, int]]) -> bool:
    Chem = _rdkit()
    from rdkit.Chem import rdCIPLabeler

    check = Chem.Mol(mh)
    Chem.AssignStereochemistryFrom3D(check)
    rdCIPLabeler.AssignCIPLabels(check)
    return all(_label_of(check, e) == _label_of(m, e) for e in elements if _label_of(m, e))


def ring_faces(m: Any, mh: Any, labels: dict[int, str]) -> list[dict[str, Any]]:
    """For each ring holding two or more stereocentres: the heavy substituents of those centres that point to each
    face of the ring's mean plane, and cis/trans for every pair of centres with one heavy substituent each."""
    import numpy as np

    Chem = _rdkit()
    pos = mh.GetConformer().GetPositions()
    centres = {a.GetIdx() for a in m.GetAtoms() if a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED}
    out: list[dict[str, Any]] = []
    for ring in m.GetRingInfo().AtomRings():
        in_ring = [i for i in ring if i in centres]
        if len(in_ring) < 2:
            continue
        ring_set = set(ring)
        pts = pos[list(ring)]
        centre = pts.mean(axis=0)
        normal = np.linalg.svd(pts - centre)[2][2]
        face_a: list[str] = []
        face_b: list[str] = []
        single: dict[int, tuple[str, int]] = {}
        for i in in_ring:
            subs = [n for n in m.GetAtomWithIdx(i).GetNeighbors() if n.GetIdx() not in ring_set]
            for n in subs:
                side = 1 if float(np.dot(normal, pos[n.GetIdx()] - pos[i])) > 0 else -1
                text = f"{_atom_name(n, labels)} at {_centre_name(i, m, labels)}"
                (face_a if side > 0 else face_b).append(text)
                if len(subs) == 1:
                    single[i] = (text, side)
        pairs = [
            {"a": single[i][0], "b": single[j][0], "relation": "cis" if single[i][1] == single[j][1] else "trans"}
            for i, j in itertools.combinations(sorted(single, key=lambda k: _locant_key(labels.get(k, ""))), 2)
        ]
        out.append({
            "ring": "-".join(_centre_name(i, m, labels) if i in labels else m.GetAtomWithIdx(i).GetSymbol() for i in ring),
            "size": len(ring),
            "face_a": face_a,
            "face_b": face_b,
            "pairs": pairs[:30],
        })
    return out


def _distances(mh: Any, labels: dict[int, str], pairs: list[list[str]] | None) -> list[dict[str, Any]]:
    import numpy as np

    if not pairs:
        return []
    by_label = {v: k for k, v in labels.items()}
    pos = mh.GetConformer().GetPositions()
    out: list[dict[str, Any]] = []
    for pair in pairs[:20]:
        if len(pair) != 2:
            continue
        a, b = (str(x).strip() for x in pair)
        if a not in by_label or b not in by_label:
            out.append({"a": a, "b": b, "error": "locant not found on any atom"})
            continue
        d = float(np.linalg.norm(pos[by_label[a]] - pos[by_label[b]]))
        out.append({"a": a, "b": b, "distance_angstrom": round(d, 2)})
    return out


# -- Public: stereodescriptors -> geometry -----------------------------------------------------------------------------
def stereo_configurations(
    smiles: str | list[str],
    descriptor_sets: list[str] | None = None,
    locants: dict[str, str] | None = None,
    distance_pairs: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Each descriptor set (applied to the first SMILES's constitution), and each further SMILES that already carries
    its stereochemistry, as CIP labels plus ring-face geometry."""
    Chem = _rdkit()
    smiles_list = [smiles] if isinstance(smiles, str) else list(smiles or [])
    if not smiles_list:
        raise ValueError("give at least one SMILES")
    if len(smiles_list) + len(descriptor_sets or []) > 2 * MAX_MOLECULES:
        raise ValueError(f"at most {2 * MAX_MOLECULES} configurations per call")
    configurations: list[dict[str, Any]] = []
    notes: list[str] = []

    def describe(m: Any, labels: dict[int, str], source: str, requested: str = "") -> dict[str, Any]:
        elements = _stereo_elements(m)
        item: dict[str, Any] = {
            "source": source,
            "smiles": Chem.MolToSmiles(m),
            "descriptors": _descriptor_text(m, elements, labels),
            "labels": _labels_dict(m, elements, labels),
        }
        if requested:
            item["requested"] = requested
        unspecified = [k for k, v in item["labels"].items() if v == "unspecified"]
        if unspecified:
            item["unspecified"] = unspecified
        mh = _embed(m)
        if mh is None:
            item["geometry"] = "unavailable: no 3D embedding found for this configuration"
            return item
        if not _geometry_keeps_labels(mh, m, elements):
            item["geometry"] = "unavailable: the embedded geometry did not keep the configuration"
            return item
        item["rings"] = ring_faces(m, mh, labels)
        dist = _distances(mh, labels, distance_pairs)
        if dist:
            item["distances"] = dist
        return item

    first = _parse(smiles_list[0])
    if first.HasProp(FILLED_H_PROP):
        notes.append(FILLED_H_NOTE)
    first_labels = _take_locants(first, locants)
    base = Chem.Mol(first)
    Chem.RemoveStereochemistry(base)
    elements = _stereo_elements(base)
    constitution = {
        "smiles": Chem.MolToSmiles(base),
        "formula": _formula(base),
        "stereo_elements": [
            (_centre_name(i, base, first_labels) if k == "atom" else "=".join(
                _centre_name(x, base, first_labels) for x in (base.GetBondWithIdx(i).GetBeginAtomIdx(),
                                                             base.GetBondWithIdx(i).GetEndAtomIdx())))
            for k, i in elements
        ],
    }
    if first_labels:
        # A model-written SMILES can have the right atoms and the wrong bonds (a fused ring closed between the wrong
        # locants), and then every face is wrong. Listing the bonds by locant lets the reader check them against the
        # name: in fused and chain names, consecutive peripheral locants are bonded.
        constitution["numbered_atoms"] = numbered_atoms(base, first_labels)
    unnumbered = [n for n in constitution["stereo_elements"] if "[atom " in n]
    if unnumbered and descriptor_sets:
        notes.append(f"stereocentres without a locant (left unspecified): {', '.join(unnumbered[:8])}")
    for text in (descriptor_sets or [])[: 2 * MAX_MOLECULES]:
        try:
            wanted: dict[tuple[str, int], str] = {}
            for loc, letter in parse_descriptors(text):
                element = _element_for_locant(base, elements, first_labels, loc, letter)
                wanted[element] = letter
            m = assign_descriptors(base, wanted)
            if m is None:
                configurations.append({"requested": text, "error": "no configuration of this constitution has these "
                                       "descriptors; check the structure and locants"})
                continue
            configurations.append(describe(m, first_labels, "descriptors", text))
        except ValueError as exc:
            configurations.append({"requested": text, "error": str(exc)})
    stereo_inputs = smiles_list if not descriptor_sets else smiles_list[1:]
    for idx, s in enumerate(stereo_inputs[:MAX_MOLECULES]):
        try:
            mol = _parse(s)
            if mol.HasProp(FILLED_H_PROP) and FILLED_H_NOTE not in notes:
                notes.append(FILLED_H_NOTE)
            labels = _take_locants(mol, locants)
            configurations.append(describe(_cip(mol), labels, f"smiles {idx + 1}"))
        except ValueError as exc:
            configurations.append({"requested": s, "error": str(exc)})
    _relate_configurations(configurations)
    return {
        "method": f"RDKit {rdkit_version()}: CIP labels by the new CIP labeler (pseudoasymmetric r/s included); "
                  "3D geometry by ETKDG embedding with MMFF relaxation",
        "constitution": constitution,
        "configurations": configurations,
        "notes": notes,
        "how_to_read": ("Faces are the two sides of each ring's mean plane. Substituents listed on the same face are cis "
                        "(syn) with respect to that ring; on opposite faces, trans (anti). In a bridged bicycle, a "
                        "substituent on the same face of the ring through both bridgeheads as the other bridge is "
                        "endo to that bridge."),
    }


def numbered_atoms(mol: Any, labels: dict[int, str]) -> dict[str, Any]:
    """The bonds between numbered atoms ("3a-4") and the consecutive locant pairs that are not bonded."""
    bonds = []
    for bond in mol.GetBonds():
        a, b = labels.get(bond.GetBeginAtomIdx()), labels.get(bond.GetEndAtomIdx())
        if a and b:
            lo, hi = sorted((a, b), key=_locant_key)
            bonds.append(f"{lo}{'=' if bond.GetBondTypeAsDouble() == 2.0 else '-'}{hi}")
    bonds.sort(key=lambda s: tuple(_locant_key(x) for x in re.split(r"[-=]", s)))
    order = sorted(labels.items(), key=lambda kv: _locant_key(kv[1]))

    def consecutive(a: str, b: str) -> bool:  # "3"/"3a", "3a"/"4", "4"/"5"; not "4"/"7", where atoms are unnumbered
        (na, sa), (nb, sb) = _locant_key(a), _locant_key(b)
        return bool((na == nb and not sa and sb) or (nb == na + 1 and not sb))

    unbonded = [f"{x[1]}/{y[1]}" for x, y in zip(order, order[1:])
                if consecutive(x[1], y[1]) and mol.GetBondBetweenAtoms(x[0], y[0]) is None]
    return {"bonds": bonds, "consecutive_not_bonded": unbonded}


def _relate_configurations(configs: list[dict[str, Any]]) -> None:
    """Mark configurations that are the same compound or mirror images of one another."""
    Chem = _rdkit()
    keys: list[tuple[str, str] | None] = []
    for c in configs:
        s = c.get("smiles")
        if not s:
            keys.append(None)
            continue
        mol = Chem.MolFromSmiles(s)
        keys.append((Chem.MolToSmiles(mol), Chem.MolToSmiles(_mirror(mol))))
    for i, c in enumerate(configs):
        key = keys[i]
        if key is None:
            continue
        others = [(j + 1, k) for j, k in enumerate(keys) if j != i and k is not None]
        same = [n for n, k in others if k[0] == key[0]]
        mirror = [n for n, k in others if k[0] == key[1] and key[0] != key[1]]
        if same:
            c["same_compound_as"] = same
        if mirror:
            c["enantiomer_of"] = mirror
        if key[0] == key[1] and any(v in ("R", "S") for v in (c.get("labels") or {}).values()):
            c["achiral"] = True


# -- Public: molecule facts --------------------------------------------------------------------------------------------
def _formula(mol: Any) -> str:
    from rdkit.Chem import rdMolDescriptors

    return rdMolDescriptors.CalcMolFormula(mol)


def _mirror(mol: Any) -> Any:
    Chem = _rdkit()
    m = Chem.RWMol(mol)
    for atom in m.GetAtoms():
        tag = atom.GetChiralTag()
        if tag == Chem.ChiralType.CHI_TETRAHEDRAL_CW:
            atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
        elif tag == Chem.ChiralType.CHI_TETRAHEDRAL_CCW:
            atom.SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CW)
    out = m.GetMol()
    Chem.AssignStereochemistry(out, cleanIt=True, force=True)
    return out


def _unsaturation(mol: Any) -> float:
    Chem = _rdkit()
    counts: dict[str, int] = {}
    hydrogens = 0
    for atom in Chem.AddHs(mol).GetAtoms():
        sym = atom.GetSymbol()
        if sym == "H":
            hydrogens += 1
        else:
            counts[sym] = counts.get(sym, 0) + 1
    carbons = counts.get("C", 0) + counts.get("Si", 0)
    nitrogens = counts.get("N", 0) + counts.get("P", 0)
    halogens = sum(counts.get(x, 0) for x in ("F", "Cl", "Br", "I"))
    return carbons - (hydrogens + halogens) / 2 + nitrogens / 2 + 1


def _environments(mol: Any) -> dict[str, Any]:
    """Topologically distinct H and C environments (graph symmetry classes, configuration included)."""
    Chem = _rdkit()
    mh = Chem.AddHs(mol)
    ranks = list(Chem.CanonicalRankAtoms(mh, breakTies=False, includeChirality=True))
    h_classes: dict[int, int] = {}
    h_on_carbon: dict[int, int] = {}
    c_classes: dict[int, int] = {}
    for atom in mh.GetAtoms():
        r = ranks[atom.GetIdx()]
        if atom.GetAtomicNum() == 1:
            h_classes[r] = h_classes.get(r, 0) + 1
            if any(n.GetAtomicNum() == 6 for n in atom.GetNeighbors()):
                h_on_carbon[r] = h_on_carbon.get(r, 0) + 1
        elif atom.GetAtomicNum() == 6:
            c_classes[r] = c_classes.get(r, 0) + 1
    return {
        "h_environments": len(h_classes),
        "h_environment_sizes": sorted(h_classes.values(), reverse=True),
        "h_environments_on_carbon": len(h_on_carbon),
        "c_environments": len(c_classes),
        "c_environment_sizes": sorted(c_classes.values(), reverse=True),
    }


def _stereoisomer_count(mol: Any) -> dict[str, Any]:
    """Stereoisomers of the constitution: total, enantiomer pairs and achiral (meso) forms."""
    Chem = _rdkit()
    base = Chem.Mol(mol)
    Chem.RemoveStereochemistry(base)
    return dict(_count_stereoisomers(Chem.MolToSmiles(base)))


@functools.lru_cache(maxsize=64)
def _count_stereoisomers(flat_smiles: str) -> dict[str, Any]:
    Chem = _rdkit()
    from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions

    base = Chem.MolFromSmiles(flat_smiles)
    elements = _stereo_elements(base)
    if not elements:
        return {"total": 1, "enantiomer_pairs": 0, "achiral": 1, "stereo_elements": 0}
    if len(elements) > MAX_ENUMERATED_ELEMENTS:
        return {"total": None, "upper_bound": 2 ** len(elements), "stereo_elements": len(elements)}
    # Embedding rejects configurations a ring cannot adopt (a trans-bridged bicycle); it is costly, so only small
    # sets are checked and the result says whether it was.
    checked = len(elements) <= 6 and base.GetNumHeavyAtoms() <= 60
    opts = StereoEnumerationOptions(onlyUnassigned=True, unique=True, maxIsomers=MAX_STEREOISOMERS,
                                    tryEmbedding=checked)
    keys: set[str] = set()
    mirrors: dict[str, str] = {}
    for iso in EnumerateStereoisomers(base, options=opts):
        key = Chem.MolToSmiles(iso)
        keys.add(key)
        mirrors[key] = Chem.MolToSmiles(_mirror(iso))
    achiral = sum(1 for k in keys if mirrors[k] == k)
    return {
        "total": len(keys),
        "enantiomer_pairs": (len(keys) - achiral) // 2,
        "achiral": achiral,
        "stereo_elements": len(elements),
        "capped": len(keys) >= MAX_STEREOISOMERS,
        "geometry_checked": checked,
    }


def molecule_facts(smiles: list[str], names: list[str] | None = None, locants: dict[str, str] | None = None) -> dict[str, Any]:
    """Structure facts for each SMILES and the relation between every pair of them."""
    Chem = _rdkit()
    from rdkit.Chem import Descriptors, rdMolDescriptors

    items = [s for s in (smiles or []) if str(s or "").strip()]
    if not items:
        raise ValueError("give at least one SMILES")
    if len(items) > MAX_MOLECULES:
        raise ValueError(f"at most {MAX_MOLECULES} molecules per call")
    names = list(names or [])
    molecules: list[dict[str, Any]] = []
    parsed: list[Any] = []
    for i, s in enumerate(items):
        name = names[i] if i < len(names) and names[i] else f"molecule {i + 1}"
        try:
            mol = _parse(s)
        except ValueError as exc:
            molecules.append({"name": name, "input": s, "error": str(exc)})
            parsed.append(None)
            continue
        labels = _take_locants(mol, locants)
        mol = _cip(mol)
        elements = _stereo_elements(mol)
        stereo = _labels_dict(mol, elements, labels)
        specified = [v for v in stereo.values() if v != "unspecified"]
        mirror_same = Chem.MolToSmiles(_mirror(mol)) == Chem.MolToSmiles(mol)
        has_centres = any(v in ("R", "S") for v in specified)
        item: dict[str, Any] = {
            "name": name,
            "input": s,
            "smiles": Chem.MolToSmiles(mol),
            "formula": _formula(mol),
            "molecular_weight": round(Descriptors.MolWt(mol), 3),
            "monoisotopic_mass": round(Descriptors.ExactMolWt(mol), 4),
            "formal_charge": Chem.GetFormalCharge(mol),
            "heavy_atoms": mol.GetNumHeavyAtoms(),
            "rings": rdMolDescriptors.CalcNumRings(mol),
            "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
            "degree_of_unsaturation": _unsaturation(mol),
            "stereo": stereo,
            "stereoisomers_of_constitution": _stereoisomer_count(mol),
            **_environments(mol),
            **_symmetry(s),
        }
        if len(specified) == len(stereo) and stereo:
            item["chiral"] = not mirror_same
            if has_centres and mirror_same:
                item["meso"] = True
        elif not stereo:
            item["chiral"] = False
        if mol.HasProp(FILLED_H_PROP):
            item["note"] = FILLED_H_NOTE
        molecules.append(item)
        parsed.append(mol)
    comparisons = []
    for i, j in itertools.combinations(range(len(parsed)), 2):
        a, b = parsed[i], parsed[j]
        if a is None or b is None:
            continue
        comparisons.append({"a": molecules[i]["name"], "b": molecules[j]["name"], "relation": _relation(a, b)})
    return {
        "method": f"RDKit {rdkit_version()}: CIP labels by the new CIP labeler; environments are graph-symmetry "
                  "classes (diastereotopic CH2 protons next to a stereocentre count as one class here but can give "
                  "separate NMR signals)",
        "molecules": molecules,
        "comparisons": comparisons[:28],
    }


def _symmetry(smiles: str) -> dict[str, Any]:
    """The point group of the structure's relaxed conformer (tribos.physis.symmetry), or why there is none."""
    from .symmetry import point_group

    try:
        pg = point_group(smiles)
    except (ValueError, RuntimeError) as exc:
        return {"point_group": f"unavailable: {str(exc)[:120]}"}
    return {"point_group": pg["point_group"], "point_group_heavy_atoms": pg["heavy_atom_framework"],
            "point_group_most_symmetric_low_energy": pg["most_symmetric_low_energy"]}


def _relation(a: Any, b: Any) -> str:
    Chem = _rdkit()
    if Chem.MolToSmiles(a) == Chem.MolToSmiles(b):
        return "identical"
    flat_a, flat_b = Chem.Mol(a), Chem.Mol(b)
    Chem.RemoveStereochemistry(flat_a)
    Chem.RemoveStereochemistry(flat_b)
    if Chem.MolToSmiles(flat_a) == Chem.MolToSmiles(flat_b):
        if Chem.MolToSmiles(_mirror(a)) == Chem.MolToSmiles(b):
            return "enantiomers"
        stereo_a = {k: v for k, v in _labels_dict(a, _stereo_elements(a), {}).items()}
        stereo_b = {k: v for k, v in _labels_dict(b, _stereo_elements(b), {}).items()}
        if "unspecified" in stereo_a.values() or "unspecified" in stereo_b.values():
            return "same constitution (configuration not fully specified)"
        return "diastereomers"
    if _formula(a) == _formula(b):
        return "constitutional isomers"
    return "different compounds (different formulae)"


# -- Public: answer options named with stereodescriptors ----------------------------------------------------------------
_OPTION_MARK_RE = re.compile(r"^\(?([A-Ha-h])[).:]\s*")
_OPTION_NAME_RE = re.compile(
    r"(?:\((?:rel-)?\d{1,3}[a-z]?'*[RSEZ]\*?(?:\s*,\s*\d{1,3}[a-z]?'*[RSEZrs]\*?)*\)|\([RSEZ]\))-[A-Za-z0-9,()\[\]'\-]+")


_OPTION_SMILES_RE = re.compile(r"SMILES\s*:\s*(\S+)", re.I)


def _number_by_constitution(smiles: str) -> str:
    """The SMILES with every heavy atom numbered by its canonical rank in the stereo-free constitution: options that are
    stereoisomers of one another number the same atom alike, whatever order their SMILES were written in."""
    Chem = _rdkit()
    mol = _parse(smiles)
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    flat = Chem.Mol(mol)
    Chem.RemoveStereochemistry(flat)
    ranks = list(Chem.CanonicalRankAtoms(flat, breakTies=True))
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(ranks[atom.GetIdx()] + 1)
    return Chem.MolToSmiles(mol)


def _smiles_option_stereo(options: list[tuple[str, str]]) -> dict[str, Any] | None:
    """Answer options given as SMILES: each configuration described with one atom numbering per constitution (#k), so
    the faces of different options can be compared atom by atom."""
    Chem = _rdkit()
    groups: dict[str, list[tuple[str, str]]] = {}
    for letter, smiles in options:
        try:
            flat = _parse(smiles)
        except ValueError:
            continue
        Chem.RemoveStereochemistry(flat)
        groups.setdefault(Chem.MolToSmiles(flat), []).append((letter, smiles))
    configurations: list[dict[str, Any]] = []
    constitutions: list[dict[str, Any]] = []
    for flat_smiles, members in groups.items():
        numbered = [_number_by_constitution(s) for _, s in members]
        locants = {str(n): f"#{n}" for n in range(1, 400)}
        result = stereo_configurations(numbered, None, locants)
        constitutions.append({**result["constitution"], "options": [letter for letter, _ in members],
                              "numbering": "#k is the k-th atom in the canonical order of this constitution: the same "
                                           "number is the same atom in every option"})
        for (letter, smiles), config in zip(members, result["configurations"]):
            for key in ("same_compound_as", "enantiomer_of", "achiral"):
                config.pop(key, None)
            config["requested"] = f"({letter}) {smiles}"
            config["option"] = letter
            configurations.append(config)
    if len(configurations) < 2:
        return None
    _relate_configurations(configurations)
    for config in configurations:
        for key in ("same_compound_as", "enantiomer_of"):
            if config.get(key):
                config[key] = [f"option {configurations[j - 1]['option']}" for j in config[key]]
        labels = config.get("labels") or {}
        config["descriptors"] = ", ".join(f"{k}{v}" for k, v in labels.items() if v != "unspecified")
    differing = _differing_centres(configurations)
    return {
        "method": f"RDKit {rdkit_version()}: the options' SMILES, numbered by their shared constitution; CIP labels by "
                  "the new CIP labeler; geometry embedded in 3D (ETKDG, MMFF)",
        "source": "answer options (SMILES)",
        "constitutions": constitutions,
        "configurations": configurations,
        "notes": ([f"stereocentres whose label differs between options: {', '.join(differing)}"] if differing else []),
        "how_to_read": ("Atoms are numbered #k alike in every option. Faces are the two sides of each ring's mean plane; "
                        "substituents on the same face are cis (syn) with respect to that ring. Compare the options "
                        "at the centres whose labels differ."),
    }


def _differing_centres(configurations: list[dict[str, Any]]) -> list[str]:
    keys = sorted({k for c in configurations for k in (c.get("labels") or {})}, key=_locant_key)
    out = []
    for k in keys:
        values = {(c.get("labels") or {}).get(k) for c in configurations if c.get("labels")}
        if len(values) > 1:
            out.append(k)
    return out


def compute_option_stereo(question: str) -> dict[str, Any] | None:
    """For a choose-one question whose options are named with stereodescriptor sets: each option's structure built
    from its name (tribos.physis.names), its descriptors assigned, and its geometry as ring faces. Options with the same
    constitution are compared with one another (same compound, enantiomers). None when fewer than two options can be
    built: fused, bridged or hetero ring names are left to the planned tool call."""
    from ..agents.question_text import is_choice_question, option_texts
    from .names import parse_name

    if not is_choice_question(question or ""):
        return None
    entries: list[tuple[str, str, Any]] = []
    smiles_entries: list[tuple[str, str]] = []
    for text in option_texts(question):
        mark = _OPTION_MARK_RE.match(text)
        letter = mark.group(1).upper() if mark else "?"
        body = text[mark.end():] if mark else text
        given = _OPTION_SMILES_RE.search(body)
        if given:
            smiles_entries.append((letter, given.group(1).rstrip(".,;")))
        if "=" in body.split("\n")[0]:  # "A = ..., B = ...": an option naming several compounds
            continue
        names = _OPTION_NAME_RE.findall(body)
        if len(names) != 1:
            continue
        name = names[0].rstrip(".,;")
        parsed = parse_name(name)
        if parsed is not None and parsed.descriptors:
            entries.append((letter, name, parsed))
    if len(entries) < 2:
        return _smiles_option_stereo(smiles_entries) if len(smiles_entries) >= 2 else None
    groups: dict[str, list[tuple[str, str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry[2].smiles, []).append(entry)
    configurations: list[dict[str, Any]] = []
    constitutions: list[dict[str, Any]] = []
    notes: list[str] = []
    for smiles, members in groups.items():
        result = stereo_configurations(smiles, [p.descriptors for _, _, p in members])
        constitutions.append({**result["constitution"], "options": [letter for letter, _, _ in members]})
        for (letter, name, _), config in zip(members, result["configurations"]):
            for key in ("same_compound_as", "enantiomer_of", "achiral"):
                config.pop(key, None)
            config["requested"] = f"({letter}) {name}"
            config["option"] = letter
            configurations.append(config)
        notes.extend(n for n in result["notes"] if n not in notes)
    _relate_configurations(configurations)
    for config in configurations:
        for key in ("same_compound_as", "enantiomer_of"):
            if config.get(key):
                config[key] = [f"option {configurations[j - 1]['option']}" for j in config[key]]
    if not any(c.get("labels") for c in configurations):
        return None
    return {
        "method": f"RDKit {rdkit_version()}: each option's structure built from its name, its descriptors assigned by "
                  "the CIP rules (new CIP labeler) and its geometry embedded in 3D (ETKDG, MMFF)",
        "source": "answer options",
        "constitutions": constitutions,
        "configurations": configurations,
        "notes": notes,
        "how_to_read": ("Faces are the two sides of each ring's mean plane. Substituents listed on the same face are cis "
                        "(syn) with respect to that ring; on opposite faces, trans (anti). Decide which geometry the "
                        "reaction gives, then pick the option whose faces show it."),
    }


__all__ = [
    "STRUCTURE_QUESTION_RE",
    "assign_descriptors",
    "compute_option_stereo",
    "is_structure_question",
    "molecule_facts",
    "parse_descriptors",
    "ring_faces",
    "stereo_configurations",
]
