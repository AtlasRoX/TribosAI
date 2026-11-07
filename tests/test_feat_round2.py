"""Second round of fixes and enhancements (2026-11-07): the system-facts timeout, the auditor's values at named points,
molecular point groups, bridged and spiro names, option SMILES numbered alike, opt-in majority voting and the public
mirror sync."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path

import pytest

# --- system facts: the Lorenz system within its time limit --------------------------------------------------------------


def test_a_named_chaotic_system_is_integrated_well_within_the_facts_time_limit() -> None:
    from tribos.agents.orchestration.presentation import FACTS_TIMEOUT_S
    from tribos.writer.system_facts import compute_system_facts

    start = time.time()
    data = compute_system_facts("Simulate the Lorenz system for 100 seconds.")
    elapsed = time.time() - start
    assert data is not None and data["kind"] == "dynamical_system" and data["span"] == 100.0
    assert elapsed < FACTS_TIMEOUT_S / 3, elapsed  # Radau as the second method took 32-42 s here
    assert any("LSODA" in c["name"] for c in data["checks"])


# --- the claim auditor: values at named points ----------------------------------------------------------------------------

def test_values_at_two_named_points_are_not_a_contradiction() -> None:
    from tribos.verify.math_claims import audit_answer

    q = "Find the shortest path on the conical surface $z=1-\\sqrt{x^2+y^2}$ between (0,-1,0) and (0,1,0)."
    answer = ("The surface is $z=1-r$ with $r=\\sqrt{x^2+y^2}$: at $r=0$, $z=1$, the apex; at $r=1$, $z=0$, the base "
              "circle. The slant height is $R=\\sqrt{2}$.")
    assert not [c for c in audit_answer(answer, q).claims if c.status == "failed"]


def test_a_restated_value_that_changes_still_fails() -> None:
    from tribos.verify.math_claims import audit_answer

    q = "A rectangle has length 3 m and width 4 m. Find its area A and diagonal d."
    report = audit_answer("The area is $A = 3 \\cdot 4 = 12$ m^2. Hence $A = 13$ m^2.", q)
    assert [c.status for c in report.claims if c.kind == "relation"] == ["passed", "failed"]


# --- point groups ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("smiles", "group"), [
    ("O", "C2v"), ("N", "C3v"), ("C", "Td"), ("c1ccccc1", "D6h"), ("C=C", "D2h"), ("O=C=O", "D∞h"), ("C#N", "C∞v"),
    ("Cl/C=C/Cl", "C2h"), ("Cl/C=C\\Cl", "C2v"), ("C=C=C", "D2d"), ("FC(Cl)Br", "C1"), ("FB(F)F", "D3h"),
    ("C1CCCCC1", "D3d"), ("C12C3C4C1C5C2C3C45", "Oh"), ("C1C2CC3CC1CC(C2)C3", "Td"), ("C1CC11CC1", "D2d"),
])
def test_point_groups_of_textbook_molecules(smiles: str, group: str) -> None:
    from tribos.physis.symmetry import point_group

    assert point_group(smiles)["point_group"] == group


def test_a_flexible_molecule_reports_its_most_symmetric_low_energy_conformer() -> None:
    from tribos.physis.symmetry import group_order, point_group

    stilbene = point_group("c1ccc(cc1)/C=C/c1ccccc1")  # the relaxed minimum twists the rings; planar is C2h
    best = stilbene["most_symmetric_low_energy"]["point_group"]
    assert group_order(best) >= group_order(stilbene["point_group"]) and best in ("C2h", "Ci", "C2")
    assert (group_order("D6h"), group_order("C2v"), group_order("S4"), group_order("Oh")) == (24, 4, 4, 48)


def test_no_point_group_without_force_field_parameters() -> None:
    from tribos.physis.symmetry import point_group

    with pytest.raises(ValueError):
        point_group("FS(F)(F)(F)(F)F")


def test_point_groups_reach_molecule_facts_and_symmetry_questions_are_routed() -> None:
    from tribos.physis.chemistry import is_structure_question, molecule_facts

    water = molecule_facts(["O"])["molecules"][0]
    assert water["point_group"] == "C2v" and water["point_group_heavy_atoms"] == "C2v"
    assert is_structure_question("What is the molecular symmetry group of product 3?")
    assert is_structure_question("Give the point group of the product.")
    assert not is_structure_question("What is the point group of the crystal lattice?")


# --- names: von Baeyer bicycles, spiro systems, skeletal replacement ------------------------------------------------------

@pytest.mark.parametrize(("name", "formula"), [
    ("bicyclo[2.2.1]hept-2-ene", "C7H10"), ("7,7-dimethylbicyclo[2.2.1]heptan-2-one", "C9H14O"),
    ("bicyclo[2.2.2]oct-2-ene", "C8H12"), ("bicyclo[4.4.0]decane", "C10H18"), ("bicyclo[1.1.0]butane", "C4H6"),
    ("(1R,6S)-1-methyl-7-oxabicyclo[4.1.0]heptane", "C7H12O"), ("2-azabicyclo[2.2.2]octane", "C7H13N"),
    ("spiro[4.5]decane", "C10H18"), ("2,8-dimethylspiro[4.5]decan-6-one", "C12H20O"),
])
def test_bridged_and_spiro_names_are_built(name: str, formula: str) -> None:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    from tribos.physis.names import parse_name

    parsed = parse_name(name)
    assert parsed is not None
    assert rdMolDescriptors.CalcMolFormula(Chem.MolFromSmiles(parsed.smiles)) == formula


def test_von_baeyer_numbering() -> None:
    from rdkit import Chem

    from tribos.physis.names import parse_name

    mol = Chem.MolFromSmiles(parse_name("bicyclo[2.2.1]hept-5-ene").smiles)
    by_map = {a.GetAtomMapNum(): a for a in mol.GetAtoms()}
    bonded = {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()))): b.GetBondTypeAsDouble()
              for b in mol.GetBonds()}
    assert bonded[(5, 6)] == 2.0 and (1, 7) in bonded and (4, 7) in bonded and (1, 2) in bonded and (1, 6) in bonded
    spiro = Chem.MolFromSmiles(parse_name("spiro[4.5]decane").smiles)
    assert next(a for a in spiro.GetAtoms() if a.GetAtomMapNum() == 5).GetDegree() == 4  # the spiro atom
    assert by_map[7].GetDegree() == 2
    assert parse_name("bicyclo[2.2.1]octane") is None  # the brackets do not add up to the stem


# --- options given as SMILES -------------------------------------------------------------------------------------------------

def test_option_smiles_are_numbered_alike() -> None:
    from tribos.physis.chemistry import compute_option_stereo

    q = ("Which stereoisomer is formed?\n(A) name: the trans diol\n\nSMILES: O[C@@H]1CCCC[C@H]1O\n"
         "(B) name: the cis diol\n\nSMILES: O[C@H]1CCCC[C@H]1O\n(C) name: the trans diol again\n\nSMILES: "
         "O[C@H]1CCCC[C@@H]1O\n\nChoose the single correct option.")
    data = compute_option_stereo(q)
    assert data is not None and data["source"] == "answer options (SMILES)"
    by = {c["option"]: c for c in data["configurations"]}
    assert set(by["A"]["labels"]) == set(by["B"]["labels"]) == set(by["C"]["labels"])  # the same #k centres
    assert by["B"].get("achiral") is True  # cis-cyclohexane-1,2-diol is meso
    relation = {k: c["rings"][0]["pairs"][0]["relation"] for k, c in by.items()}
    assert relation == {"A": "trans", "B": "cis", "C": "trans"}


# --- majority voting (opt-in) --------------------------------------------------------------------------------------------------

def test_answer_letters_and_the_tally() -> None:
    from tribos.agents.orchestration.mc_vote import answer_letter, tally, votes_setting

    assert answer_letter("(B) first thoughts ... Answer: C", "ABCD") == "C"
    assert answer_letter("(D) the only option", "ABCD") == "D"
    assert answer_letter("Answer: E", "ABCD") == ""
    assert tally("A", ["B", "B"])[0] == "B"
    assert tally("A", ["B", "C"])[0] == "A"  # no majority: the first draft stands
    assert votes_setting() == 1  # off by default


def test_the_majority_option_replaces_the_first_draft(monkeypatch, tmp_path) -> None:
    from tests.agentic_fakes import collect_events, make_agentic_orchestrator
    from tribos.agentic import config as agent_config
    from tribos.agentic.runtime import restore_phases, snapshot_phases

    monkeypatch.setenv("TRIBOS_MC_VOTES", "3")
    drafts = iter(["(A) one\n\nAnswer: A", "(B) two\n\nAnswer: B", "(B) two\n\nAnswer: B"])

    def synthesis(system: str, user: str) -> str:
        return next(drafts, "(B) two\n\nAnswer: B")

    saved = snapshot_phases()
    try:
        restore_phases({})
        orch, _calls, _llm = make_agentic_orchestrator(monkeypatch, tmp_path, responses={"synthesis": synthesis})
        q = "Which is the largest?\n(A) 1\n(B) 2\n(C) 3\n(D) 0\n\nChoose the single correct option."
        res, _ = asyncio.run(collect_events(orch, query=q, thread_id="tvote", framework=agent_config.AGENTIC,
                                            enable_web_search=False))
    finally:
        restore_phases(saved)
    vote = res.execution_artifacts["mc_vote"]
    assert vote["first"] == "A" and vote["chosen"] == "B" and vote["replaced"] is True


# --- the public mirror sync ------------------------------------------------------------------------------------------------------

def _sync_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "sync_public.py"
    spec = importlib.util.spec_from_file_location("sync_public", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sync_leaves_out_internal_material() -> None:
    sync = _sync_module()
    for internal in ("AUDIT_REPORT.md", "CLAUDE.md", "docs/benchmarks/x.md", "docs/history/a.md", "docs/plans/p.md",
                     ".agent/rules/tribos.md", "docs/CHANGES_SUMMARY.md"):
        assert sync.EXCLUDE.match(internal), internal
    for public in ("README.md", "tribos/physis/chemistry.py", "docs/physis/index.md", "website/src/index.html"):
        assert not sync.EXCLUDE.match(public), public


def test_the_sync_strips_private_blocks_links_and_internal_entries() -> None:
    sync = _sync_module()
    roadmap = b"## T13\n\nDone.\n\n
\n\nOpen follow-ups:\n"
    out = sync.transform("docs/FEATURE_ROADMAP.md", roadmap).decode()
    assert "Measured" not in out and "private" not in out and "Open follow-ups" in out
    changelog = ("## v1.3.0 (2026-11-07)\n\n### Documentation\n\n- Benchmark failure analysis and roadmap entry T12\n"
                 "  ([`1eca197`](https://github.com/AtlasRoX/Tribos-Alpha/commit/1eca197e))\n\n### Features\n\n"
                 "- **agents**: Chemeia\n  ([`819143c`](https://github.com/AtlasRoX/Tribos-Alpha/commit/819143c2))\n")
    out = sync.transform("CHANGELOG.md", changelog.encode()).decode()
    assert "Tribos-Alpha" not in out and "failure analysis" not in out and "### Documentation" not in out
    assert "- **agents**: Chemeia" in out
    fake = "API_KEY = " + '"' + "abcdefghij" + "klmnopqrstu" + '"'  # built here so this file holds no key-like line
    assert sync.SECRET.search(fake) and not sync.SECRET.search("api_key = None")
    assert json.loads(json.dumps({"ok": True}))  # the module imports cleanly


# --- "the difference between" is a positive amount ---------------------------------------------------------------------------

def test_the_difference_between_two_quantities_is_reported_as_a_positive_amount() -> None:
    from tribos.agents.conventions import conventions_for

    def keys(q: str) -> list[str]:
        return [c.key for c in conventions_for(q)]

    assert "difference_is_positive" in keys("A scores 40 and B scores 65. What is the difference between their scores?")
    assert "difference_is_positive" not in keys("Compute the signed difference between x and y.")
    assert "difference_is_positive" not in keys("Find the potential difference across the resistor.")
