"""Cheminformatics tools (physis_molecule, physis_stereo) and the routing of structure questions to them.

The expected values are textbook facts: cis-1,2-dimethylcyclohexane is the meso (1R,2S) form and the trans form is a
pair of enantiomers; tartaric acid has three stereoisomers and 2,3,4-trihydroxyglutaric acid four (two meso forms with
a pseudoasymmetric C3); toluene has four kinds of hydrogen and five kinds of carbon. Questions here are written for
the tests, never copied from a benchmark.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tribos.physis import chemistry as chem

DIMETHYLCYCLOHEXANE = "[CH3:7][CH:1]1[CH:2]([CH3:8])[CH2:3][CH2:4][CH2:5][CH2:6]1"
# 7-chloro-2,3-dimethylbicyclo[2.2.1]hept-5-ene, atoms numbered by their locants.
CHLORONORBORNENE = "[CH:1]12[CH:2](C)[CH:3](C)[CH:4]([CH:5]=[CH:6]1)[CH:7]2Cl"


def _config(result: dict, requested: str) -> dict:
    return next(c for c in result["configurations"] if c.get("requested") == requested)


def _ring_with(config: dict, *atoms: str) -> dict:
    return next(r for r in config["rings"] if set(atoms) <= set(r["ring"].split("-")))


def _face_of(ring: dict, text: str) -> str:
    return "a" if text in ring["face_a"] else "b" if text in ring["face_b"] else ""


# --- descriptors -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "expected"), [
    ("(3aR,4S,7aS,8r)", [("3a", "R"), ("4", "S"), ("7a", "S"), ("8", "r")]),
    ("1S,2R", [("1", "S"), ("2", "R")]),
    ("rel-(1R,2S)", [("1", "R"), ("2", "S")]),
    ("(2E,4Z)-hexa-2,4-diene", [("2", "E"), ("4", "Z")]),
    ("(R)-butan-2-ol", [("", "R")]),
    ("(1R,2S)-2-methylcyclohexan-1-ol", [("1", "R"), ("2", "S")]),
])
def test_descriptor_sets_are_parsed(text: str, expected: list) -> None:
    assert chem.parse_descriptors(text) == expected


def test_descriptor_text_without_descriptors_is_rejected() -> None:
    with pytest.raises(ValueError):
        chem.parse_descriptors("cyclohexanol")


# --- descriptors -> geometry -------------------------------------------------------------------------------------------

def test_cis_and_trans_dimethylcyclohexane() -> None:
    r = chem.stereo_configurations(DIMETHYLCYCLOHEXANE, ["(1R,2S)", "(1R,2R)", "(1S,2S)"])
    cis, trans, trans_mirror = (_config(r, d) for d in ("(1R,2S)", "(1R,2R)", "(1S,2S)"))
    assert [p["relation"] for p in cis["rings"][0]["pairs"]] == ["cis"]
    assert cis.get("achiral") is True
    assert [p["relation"] for p in trans["rings"][0]["pairs"]] == ["trans"]
    assert trans["enantiomer_of"] == [3] and trans_mirror["enantiomer_of"] == [2]
    assert trans["labels"] == {"1": "R", "2": "R"}


def test_bridged_bicycle_endo_exo_and_pseudoasymmetric_bridge() -> None:
    """The C2/C3 descriptors decide endo or exo; the pseudoasymmetric r/s of C7 decides which way Cl points."""
    sets = ["(1R,2R,3S,4S,7r)", "(1R,2R,3S,4S,7s)", "(1R,2S,3R,4S,7r)"]
    r = chem.stereo_configurations(CHLORONORBORNENE, sets)
    endo_r, endo_s, exo_r = (_config(r, d) for d in sets)
    for config in (endo_r, endo_s, exo_r):
        assert "error" not in config and config["descriptors"] == config["requested"]
    ring = _ring_with(endo_r, "1", "2", "3", "4", "7")
    # endo: the methyls share a face of the ring through C7 with the C5=C6 bridge
    assert _face_of(ring, "CH3 at 2") == _face_of(ring, "C5 at 4") == _face_of(ring, "CH3 at 3")
    exo_ring = _ring_with(exo_r, "1", "2", "3", "4", "7")
    assert _face_of(exo_ring, "CH3 at 2") != _face_of(exo_ring, "C5 at 4")
    # 7r and 7s put the chlorine on opposite sides of the alkene bridge
    ring_s = _ring_with(endo_s, "1", "2", "3", "4", "7")
    toward_alkene_r = _face_of(ring, "Cl at 7") == _face_of(ring, "C5 at 4")
    toward_alkene_s = _face_of(ring_s, "Cl at 7") == _face_of(ring_s, "C5 at 4")
    assert toward_alkene_r != toward_alkene_s


def test_letter_locants_and_distances() -> None:
    smiles = "[CH3:9][CH:1]1[CH:2]([CH3:10])[CH2:3][CH2:31]1"
    r = chem.stereo_configurations(smiles, ["(1R,2S)"], locants={"31": "3a"}, distance_pairs=[["9", "10"], ["9", "99"]])
    config = r["configurations"][0]
    assert "3a" in config["rings"][0]["ring"].split("-")
    assert config["distances"][0]["distance_angstrom"] == pytest.approx(3.0, abs=0.6)  # cis methyls on a cyclobutane
    assert "error" in config["distances"][1]


def test_double_bond_descriptors() -> None:
    r = chem.stereo_configurations("[CH3:1][CH:2]=[CH:3][CH3:4]", ["(2E)", "(2Z)"])
    assert _config(r, "(2E)")["labels"] == {"2=3": "E"}
    assert _config(r, "(2Z)")["labels"] == {"2=3": "Z"}


def test_isomeric_smiles_are_described_without_descriptor_sets() -> None:
    r = chem.stereo_configurations(["C[C@@H]1CCCC[C@H]1C", "C[C@@H]1CCCC[C@@H]1C"])
    first, second = r["configurations"]
    assert first["rings"][0]["pairs"][0]["relation"] != second["rings"][0]["pairs"][0]["relation"]


def test_numbered_atoms_written_without_hydrogens_are_not_radicals() -> None:
    """A planner wrote "[C:1]" for "carbon 1"; read literally, every stereocentre became a radical (live run, 2026-11-07)."""
    r = chem.stereo_configurations("[CH3:7][C:1]1[C:2]([CH3:8])[CH2:3][CH2:4][CH2:5][CH2:6]1", ["(1R,2S)"])
    assert chem.FILLED_H_NOTE in r["notes"]
    assert r["constitution"]["formula"] == "C8H16"
    assert r["configurations"][0]["rings"][0]["pairs"][0]["relation"] == "cis"
    facts = chem.molecule_facts(["O[C:1]1C=C[C:4](C)CC1"])["molecules"][0]
    assert facts["formula"] == "C7H12O" and facts["note"] == chem.FILLED_H_NOTE
    # a radical written without a map number is left as written
    assert chem.molecule_facts(["C[CH2]"])["molecules"][0]["formula"] == "C2H5"


def test_wrong_locants_and_impossible_sets_are_reported() -> None:
    r = chem.stereo_configurations(DIMETHYLCYCLOHEXANE, ["(1R,3S)", "(1R,2X)"])
    assert all("error" in c for c in r["configurations"])
    with pytest.raises(ValueError):
        chem.stereo_configurations("C1CC(", ["(1R)"])


# --- molecule facts ----------------------------------------------------------------------------------------------------

def test_stereoisomer_counts_with_meso_forms() -> None:
    facts = chem.molecule_facts(["OC(=O)C(O)C(O)C(=O)O", "OC(=O)C(O)C(O)C(O)C(=O)O"])
    tartaric, trihydroxyglutaric = (m["stereoisomers_of_constitution"] for m in facts["molecules"])
    assert (tartaric["total"], tartaric["enantiomer_pairs"], tartaric["achiral"]) == (3, 1, 1)
    assert (trihydroxyglutaric["total"], trihydroxyglutaric["enantiomer_pairs"], trihydroxyglutaric["achiral"]) == (4, 1, 2)


def test_meso_and_chiral_tartaric_acid() -> None:
    meso, chiral = chem.molecule_facts(["OC(=O)[C@H](O)[C@H](O)C(=O)O", "OC(=O)[C@@H](O)[C@H](O)C(=O)O"])["molecules"]
    assert meso["stereo"] == {"C[atom 4]": "R", "C[atom 6]": "S"}
    assert meso["chiral"] is False and meso.get("meso") is True
    assert chiral["chiral"] is True and "meso" not in chiral


def test_formula_unsaturation_and_environments() -> None:
    toluene, ethanol, benzene = chem.molecule_facts(["Cc1ccccc1", "CCO", "c1ccccc1"])["molecules"]
    assert toluene["formula"] == "C7H8" and toluene["degree_of_unsaturation"] == 4
    assert (toluene["h_environments"], toluene["c_environments"]) == (4, 5)
    assert (ethanol["h_environments"], ethanol["h_environments_on_carbon"], ethanol["c_environments"]) == (3, 2, 2)
    assert (benzene["h_environments"], benzene["c_environments"]) == (1, 1)
    assert benzene["molecular_weight"] == pytest.approx(78.114, abs=0.01)


@pytest.mark.parametrize(("a", "b", "relation"), [
    ("C[C@H](O)CC", "C[C@@H](O)CC", "enantiomers"),
    ("C/C=C/C", "C/C=C\\C", "diastereomers"),
    ("CCCCO", "CCOCC", "constitutional isomers"),
    ("OCC", "CCO", "identical"),
    ("CO", "CCO", "different compounds (different formulae)"),
])
def test_relations_between_structures(a: str, b: str, relation: str) -> None:
    assert chem.molecule_facts([a, b])["comparisons"][0]["relation"] == relation


def test_invalid_smiles_is_reported_per_molecule() -> None:
    facts = chem.molecule_facts(["CCO", "C1CC("])
    assert "error" in facts["molecules"][1] and facts["comparisons"] == []


# --- registry, routing and evidence -------------------------------------------------------------------------------------

def test_tools_run_through_the_registry() -> None:
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    res = asyncio.run(reg.execute("physis_stereo", smiles=[DIMETHYLCYCLOHEXANE], descriptor_sets=["(1R,2S)"]))
    assert res.success and res.data["configurations"][0]["rings"][0]["pairs"][0]["relation"] == "cis"
    res = asyncio.run(reg.execute("physis_molecule", smiles=["CCO"], names=["ethanol"]))
    assert res.success and res.data["molecules"][0]["formula"] == "C2H6O"
    bad = asyncio.run(reg.execute("physis_stereo", smiles=["not a smiles"], descriptor_sets=["(1R)"]))
    assert not bad.success


@pytest.mark.parametrize("question", [
    "Which stereoisomer of 2-methylcyclohexan-1-ol is formed? (A) (1R,2S)-2-methylcyclohexan-1-ol (B) (1R,2R)-2-methylcyclohexan-1-ol",
    "How many chemically distinct hydrogen atoms does 2-methylbutane have?",
    "How many peaks appear on a chiral HPLC column for the product mixture?",
    "Is the endo or exo adduct the major product of the cycloaddition?",
    "Give the molecular formula and the degree of unsaturation of limonene.",
    "Describe O=C(O)[C@@H](O)[C@H](O)C(=O)O.",
])
def test_structure_questions_are_recognised(question: str) -> None:
    assert chem.is_structure_question(question)


@pytest.mark.parametrize("question", [
    "Explain the chiral anomaly for massless fermions.",
    "Compute the stereographic projection of the unit sphere.",
    "The pulse lasts (3s) and repeats; find the duty cycle.",
    "What is the pH of 0.1 M acetic acid?",
    "Solve x^2 - 5x + 6 = 0.",
])
def test_other_questions_are_not_routed_to_chemistry(question: str) -> None:
    assert not chem.is_structure_question(question)


def test_structure_questions_plan_the_chemistry_tools() -> None:
    from tribos.agentic.plan_execute import needs_specialised_tool
    from tribos.agentic.planner import select_tools
    from tribos.tools.registry import get_tool_registry

    reg = get_tool_registry()
    q = "How many stereoisomers does 2,3-dibromobutane have, and which of them are meso?"
    state = SimpleNamespace(registry=reg, clean_query=q, query=q, ctx=None)
    assert needs_specialised_tool(state)
    offered = [e.name for e in select_tools(state, [])]
    assert "physis_stereo" in offered and "physis_molecule" in offered
    q2 = "What is the pH of 0.1 M acetic acid?"
    assert not needs_specialised_tool(SimpleNamespace(registry=reg, clean_query=q2, query=q2))


def test_chemistry_evidence_shows_faces_and_relations() -> None:
    from tribos.agents.stem_evidence import render_tool_result
    from tribos.tools.registry import ToolResult

    data = chem.stereo_configurations(DIMETHYLCYCLOHEXANE, ["(1R,2R)", "(1S,2S)"])
    text = "\n".join(render_tool_result(ToolResult(success=True, tool_name="physis_stereo", data=data)) or [])
    assert "<chemistry" in text and "face_a=" in text and "trans" in text and "enantiomer of configuration 2" in text
    facts = chem.molecule_facts(["CCO"], names=["ethanol"])
    text = "\n".join(render_tool_result(ToolResult(success=True, tool_name="physis_molecule", data=facts)) or [])
    assert 'name="ethanol"' in text and "C2H6O" in text


def test_stereodescriptor_options_get_the_writer_note() -> None:
    from tribos.agents.conventions import conventions_for

    q = ("Which product forms? (A) (1R,2S,3R)-1,2,3-trimethylcyclopentane (B) (1R,2R,3S)-1,2,3-trimethylcyclopentane "
         "(C) (1S,2S,3S)-1,2,3-trimethylcyclopentane (D) 1,1,2-trimethylcyclopentane")
    assert "stereodescriptor_options" in [c.key for c in conventions_for(q)]
    assert "stereodescriptor_options" not in [c.key for c in conventions_for("What is (R)-butan-2-ol's boiling point?")]


# --- evidence gate for choose-one questions ------------------------------------------------------------------------------

_OPTIONS = "\n(A) the first route\n(B) the second route\n(C) the third route\n(D) the fourth route"


def test_choice_question_words_narrate_the_item() -> None:
    from tribos.agents.evidence_need import assess_evidence_need

    q = "Preliminary studies show a ligand binds weakly. Which step is most important next?" + _OPTIONS
    assert assess_evidence_need(q).level == "none"
    q = "Measured spectra are typically noisy. Which filter preserves the peak heights best?" + _OPTIONS
    assert assess_evidence_need(q).level == "none"


def test_choice_question_can_still_ask_for_sources() -> None:
    from tribos.agents.evidence_need import assess_evidence_need

    assert assess_evidence_need("Cite papers on this: which route is preferred?" + _OPTIONS).level == "required"
    assert assess_evidence_need("According to the 2019 standard, which route is preferred?" + _OPTIONS).level == "required"
    # without options, narrating words still send the question to the literature
    assert assess_evidence_need("Preliminary studies show a ligand binds weakly. What should be done next?").level == "required"


# --- names -> structures, and the answer options' stereodescriptors before drafting ---------------------------------------

@pytest.mark.parametrize(("name", "formula", "descriptors"), [
    ("(1R,2S)-2-methylcyclohexan-1-ol", "C7H14O", "(1R,2S)"),
    ("3,3-dimethylcyclohex-1-enol", "C8H14O", ""),
    ("(1S,3R)-1,3-dichlorocyclopentane", "C5H8Cl2", "(1S,3R)"),
    ("4-tert-butylcyclohexan-1-one", "C10H18O", ""),
    ("(2E,4Z)-hexa-2,4-diene", "C6H10", "(2E,4Z)"),
    ("(2R,3S)-butane-2,3-diol", "C4H10O2", "(2R,3S)"),
    ("3-ethyl-2-methylpent-1-ene", "C8H16", ""),
    ("hexanal", "C6H12O", ""),
])
def test_simple_names_are_built_with_locants(name: str, formula: str, descriptors: str) -> None:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    from tribos.physis.names import parse_name

    parsed = parse_name(name)
    assert parsed is not None and parsed.descriptors == descriptors
    mol = Chem.MolFromSmiles(parsed.smiles)
    assert rdMolDescriptors.CalcMolFormula(mol) == formula
    assert sorted(a.GetAtomMapNum() for a in mol.GetAtoms() if a.GetAtomMapNum()) == list(range(1, parsed.parent_size + 1))


@pytest.mark.parametrize("name", [
    "7-oxabicyclo[4.1.0]heptane", "benzene", "dimethyl cyclohexane-1,2-dicarboxylate", "1-(prop-1-en-1-yl)cyclopentane",
    "2,2-dimethylcyclohexan-7-ol",  # locant outside the ring
    "2,3-methylbutane",  # multiplier missing
])
def test_names_outside_the_grammar_are_not_guessed(name: str) -> None:
    from tribos.physis.names import parse_name

    assert parse_name(name) is None


_STEREO_OPTIONS_QUESTION = (
    "Hydroboration-oxidation of 1-methylcyclohexene gives which product?\n"
    "(A) (1R,2R)-2-methylcyclohexan-1-ol\n(B) (1R,2S)-2-methylcyclohexan-1-ol\n"
    "(C) (1S,2S)-2-methylcyclohexan-1-ol\n(D) 1-methylcyclohexan-1-ol"
)


def test_options_with_descriptors_become_geometry_before_drafting() -> None:
    data = chem.compute_option_stereo(_STEREO_OPTIONS_QUESTION)
    assert data is not None and data["constitutions"][0]["options"] == ["A", "B", "C"]
    by_option = {c["option"]: c for c in data["configurations"]}
    assert set(by_option) == {"A", "B", "C"}
    relation = {k: c["rings"][0]["pairs"][0]["relation"] for k, c in by_option.items()}
    assert relation == {"A": "trans", "B": "cis", "C": "trans"}  # (1R,2R) and (1S,2S) are the trans pair
    assert by_option["A"]["enantiomer_of"] == ["option C"]


def test_option_stereo_needs_two_buildable_options() -> None:
    assert chem.compute_option_stereo("Which is chiral?\n(A) (R)-butan-2-ol\n(B) ethanol\n(C) methanol") is None
    assert chem.compute_option_stereo("Name (1R,2S)-2-methylcyclohexan-1-ol and (1R,2R)-2-methylcyclohexan-1-ol.") is None


def test_option_stereo_is_rendered_and_replaces_the_planned_stereo_tool() -> None:
    from tribos.agentic.planner import select_tools
    from tribos.agents.result_keys import CHEMISTRY
    from tribos.agents.stem_evidence import stem_evidence
    from tribos.tools.registry import ToolResult, get_tool_registry

    data = chem.compute_option_stereo(_STEREO_OPTIONS_QUESTION)
    results = {CHEMISTRY: ToolResult(success=True, tool_name="physis_stereo", data=data)}
    text = "\n".join(stem_evidence(results))
    assert 'options="A, B, C"' in text and "(B) (1R,2S)-2-methylcyclohexan-1-ol" in text and "enantiomer of option C" in text
    reg = get_tool_registry()
    state = SimpleNamespace(registry=reg, clean_query=_STEREO_OPTIONS_QUESTION, query=_STEREO_OPTIONS_QUESTION, ctx=None,
                            tool_results=results)
    offered = [e.name for e in select_tools(state, [])]
    assert "physis_stereo" not in offered and "physis_molecule" in offered


def test_bonds_between_numbered_atoms_expose_a_wrong_constitution() -> None:
    """A model-written SMILES with the right atoms and a wrong ring bond gives wrong faces; its bonds by locant show it."""
    right = chem.stereo_configurations(CHLORONORBORNENE, ["(1R,2R,3S,4S,7r)"])["constitution"]["numbered_atoms"]
    assert {"1-2", "2-3", "3-4", "4-5", "5=6", "1-6", "1-7", "4-7"} <= set(right["bonds"])
    assert right["consecutive_not_bonded"] == ["6/7"]  # the bridge begins at 7
    wrong = "[CH:1]12[CH:2](C)[CH:4](C)[CH:3]([CH:5]=[CH:6]1)[CH:7]2Cl"  # 3 and 4 swapped in the ring walk
    numbered = chem.stereo_configurations(wrong, ["(1R)"])["constitution"]["numbered_atoms"]
    assert "2-4" in numbered["bonds"] and "3/4" not in numbered["consecutive_not_bonded"]
    assert "4/5" in numbered["consecutive_not_bonded"]
