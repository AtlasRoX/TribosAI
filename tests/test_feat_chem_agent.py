"""The chemistry agent Chemeia (tribos/agentic/chem_agent.py): routing, code checks of a solution, the repair round, and
the evidence the writer receives. Questions are written for the tests, never copied from a benchmark."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.agentic_fakes import collect_events, make_agentic_orchestrator
from tribos.agentic import chem_agent as ca
from tribos.agentic import config as agent_config
from tribos.agentic.runtime import register_phase, restore_phases, snapshot_phases

HYDROBORATION = (
    "1-methylcyclohexene is treated with BH3 in THF, then with H2O2 and NaOH, forming product 1. What is product 1?\n"
    "(A) (1R,2R)-2-methylcyclohexan-1-ol\n(B) (1R,2S)-2-methylcyclohexan-1-ol\n(C) 1-methylcyclohexan-1-ol\n"
    "(D) 2-methylcyclohexan-1-one\n\nChoose the single correct option."
)
TRANS = "C[C@@H]1CCCC[C@H]1O"  # (1R,2R)-2-methylcyclohexan-1-ol: anti-Markovnikov, syn addition gives the trans pair


def _solution(smiles: str, answer: str, role: str = "product") -> ca.ChemSolution:
    return ca.ChemSolution.model_validate({
        "steps": [{"label": "alkylborane", "name": "trialkylborane", "smiles": "", "reason": "syn addition"}],
        "target": {"role": role, "name": "2-methylcyclohexan-1-ol", "smiles": smiles, "geometry": "OH trans to CH3"},
        "answer": answer, "key_reasoning": "anti-Markovnikov syn addition; oxidation with retention",
    })


@pytest.mark.parametrize("question", [
    HYDROBORATION,
    "Cyclohexanone is treated with LDA and then methyl iodide. How many 13C NMR signals does the product show?",
    "Ethyl acetate reacts with two equivalents of methylmagnesium bromide; what is the alcohol formed?",
])
def test_organic_questions_are_recognised(question: str) -> None:
    assert ca.is_organic_question(question)


@pytest.mark.parametrize("question", [
    "A block slides down an inclined plane; find the acceleration and the reaction force.",
    "What is the pH of 0.1 M HCl?",
    "Solve x^2 - 5x + 6 = 0.",
    "The nuclear reaction produces a neutron; find the Q value.",
])
def test_other_questions_are_not_sent_to_the_chemistry_agent(question: str) -> None:
    assert not ca.is_organic_question(question)


def test_option_structures_are_built_from_names_and_smiles() -> None:
    built = {o["option"]: o for o in ca.option_structures(HYDROBORATION)}
    assert set(built) == {"A", "B", "C", "D"}
    assert built["A"]["stereo"] and built["A"]["formula"] == "C7H14O" and built["D"]["formula"] == "C7H12O"
    smiles_q = ("Which structure is meant?\n(A) name: ethanol\n\nSMILES: CCO\n(B) name: methanol\n\nSMILES: CO\n"
                "(C) name: propan-1-ol\n\nSMILES: CCCO\n\nChoose one.")
    assert [(o["option"], o["source"]) for o in ca.option_structures(smiles_q)] == [("A", "smiles"), ("B", "smiles"),
                                                                                    ("C", "smiles")]


def test_a_target_that_is_the_chosen_option_is_matched() -> None:
    report = ca.check_solution(HYDROBORATION, _solution(TRANS, "A"))
    assert report["status"] == "matched" and report["match"]["exact"] == ["A"]
    assert report["target"]["formula"] == "C7H14O" and report["target"]["stereo_specified"]
    assert ca.repair_feedback(report, "A") == ""


def test_a_target_that_is_another_option_is_sent_back_for_repair() -> None:
    report = ca.check_solution(HYDROBORATION, _solution(TRANS, "B"))
    assert report["status"] == "mismatch"
    feedback = ca.repair_feedback(report, "B")
    assert "is option A by code" in feedback and "you answered B" in feedback


def test_unmatched_invalid_and_unconfigured_targets() -> None:
    unmatched = ca.check_solution(HYDROBORATION, _solution("CCCCCCCO", ""))
    assert unmatched["status"] == "unmatched" and "constitution of no option" in ca.repair_feedback(unmatched, "")
    invalid = ca.check_solution(HYDROBORATION, _solution("C1CC(", "A"))
    assert invalid["status"] == "invalid" and "not a valid SMILES" in ca.repair_feedback(invalid, "A")
    # Configuration not written: both trans and cis options share the constitution, code cannot decide between them.
    flat = ca.check_solution(HYDROBORATION, _solution("CC1CCCCC1O", "A"))
    assert flat["status"] == "constitution_matched" and flat["match"]["constitution"] == ["A", "B"]


def test_without_buildable_options_the_structures_are_still_checked() -> None:
    q = "Cyclohexanone is treated with LDA and then methyl iodide. How many 13C NMR signals does the product show?"
    report = ca.check_solution(q, _solution("CC1CCCCC1=O", "7"))
    assert report["status"] == "checked" and report["target"]["c_environments"] == 7


def test_evidence_says_what_code_checked() -> None:
    sol = _solution(TRANS, "A")
    xml = ca.evidence_xml(sol, ca.check_solution(HYDROBORATION, sol), repaired=False)
    assert '<chem_agent agent="Chemeia" status="matched"' in xml and 'exact="A"' in xml
    assert "not checked by code" in xml and '<target role="product"' in xml


@pytest.fixture
def chem_only():
    saved = snapshot_phases()
    from tribos.extensions import load_extensions

    load_extensions()
    restore_phases({})
    register_phase(ca.ChemAgentPhase())
    try:
        yield
    finally:
        restore_phases(saved)


def test_the_agent_repairs_a_mismatch_and_the_writer_gets_its_evidence(monkeypatch, tmp_path, chem_only) -> None:
    replies = iter([_solution(TRANS, "B").model_dump(), _solution(TRANS, "A").model_dump()])
    orch, _calls, llm = make_agentic_orchestrator(
        monkeypatch, tmp_path, responses={"chem_agent": lambda s, u: json.dumps(next(replies))})
    res, _ = asyncio.run(collect_events(orch, query=HYDROBORATION, thread_id="tchem", framework=agent_config.AGENTIC,
                                        enable_web_search=False))
    prompts = llm.prompts("chem_agent")
    assert len(prompts) == 2 and "is option A by code" in prompts[1]
    art = res.execution_artifacts["chem_agent"]
    assert art["status"] == "matched" and art["repaired"] is True and art["answer"] == "A"
    synthesis = " ".join(llm.prompts("synthesis"))
    assert '<chem_agent agent="Chemeia" status="matched"' in synthesis and "code matched its target" in synthesis


def test_the_agent_can_be_switched_off(monkeypatch, tmp_path, chem_only) -> None:
    monkeypatch.setenv("TRIBOS_CHEM_AGENT", "0")
    orch, _calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path)
    res, _ = asyncio.run(collect_events(orch, query=HYDROBORATION, thread_id="tchem2", framework=agent_config.AGENTIC,
                                        enable_web_search=False))
    assert "chem_agent" not in res.execution_artifacts and not llm.prompts("chem_agent")
