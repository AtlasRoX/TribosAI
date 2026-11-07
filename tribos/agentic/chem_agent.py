"""
Agent phase: Chemeia, the chemistry agent, on organic-chemistry questions.

A model that reasons well about a reaction still slips on what code can settle: a SMILES that is not the compound it
named, R/S labels for the right geometry, a count of NMR environments, which option a structure is. Chemeia separates
the two:

    model: work the chemistry -> every intermediate and the product as SMILES, the geometry, the chosen answer
    code:  parse and check every structure (RDKit) -> formulas, unsaturation, counts -> match the product to the
           answer options (option names built by tribos.physis.names, configurations by the CIP rules)
    model: one repair round when code finds an invalid structure, a product that matches no option, or a product
           that is a different option from the one chosen

The chemistry itself (which product forms) stays the model's reasoning; the evidence says exactly what code checked,
so a matched structure is never presented as a proved mechanism. Runs in the augment stage of every agentic framework.
"""

from __future__ import annotations

import logging
import re
from html import escape
from typing import Any

from pydantic import BaseModel, Field

from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE_KEY = "chem_agent"
AGENT_NAME = "Chemeia"
MAX_REPAIRS = 1

# A reaction or structure question about organic compounds: a reaction word and at least two organic names, or a
# question that already turns on a structure (tribos.physis.chemistry.is_structure_question).
_REACTION_RE = re.compile(
    r"\b(?:treated|heated|reacted|reacts?|reaction|refluxed|stirred|forming|formed|product|products|synthes\w+|"
    r"starting\s+material|reagents?|mechanism|rearrangement|cycloaddition|condensation|oxidation|reduction|"
    r"hydrolysis|elimination|substitution|addition|ozonolysis|hydrogenation|bromination|nitration|NMR|"
    r"mass\s+spectrum|IR\s+spectrum)\b", re.I)
_ORGANIC_NAME_RE = re.compile(
    r"\b\d+(?:,\d+)*-(?:[a-z]+-)*(?:di|tri|tetra)?(?:methyl|ethyl|propyl|butyl|isopropyl|tert-butyl|phenyl|bromo|"
    r"chloro|fluoro|iodo|nitro|amino|hydroxy|methoxy|oxo|vinyl)|\b(?:cyclo|bicyclo|spiro)\w+|"
    r"\b\w*(?:ane|ene|yne|anol|enol|anone|enone|anal|oate|oic|amine|amide|nitrile)\b|"
    r"\b(?:aldehyde|ketone|alcohol|ester|ether|amide|alkene|alkyne|anhydride|epoxide|acetone|toluene|benzene|"
    r"phenol|aniline|pyridine|acetic|benzaldehyde|cyclopentadiene|diene|dienophile|enolate|Grignard|carbocation|"
    r"acetate|benzoate|formate|cuprate|borane|borohydride|hydride|alkoxide|ethoxide|methoxide)\b|"
    r"\b\w+(?:magnesium|lithium)\b",
    re.I)
# Words that make "ane"/"ene" matches ordinary English or physics, not chemistry.
_NOT_ORGANIC = frozenset({"plane", "lane", "membrane", "arcane", "insane", "mundane", "scene", "gene", "genes",
                          "serene", "hygiene", "scheme", "terrane", "obscene", "convene", "intervene", "keyne",
                          "kerosene", "polythene", "germane", "humane", "profane", "urbane"})

SOLVE_SYSTEM = (
    "[phase:chem_agent] You are Chemeia, an organic chemistry specialist. Solve the question by working the "
    "chemistry step by step: the role of every reagent, the mechanism, each intermediate, then the compound the "
    "question asks about (the target: usually the final product, but a starting material, reagent or intermediate "
    "when that is what is asked; for a question about a property, the compound that has it) and the answer. Write "
    "every structure as a valid SMILES. Where the chemistry decides a configuration, write it: @ or @@ at each "
    "stereocentre, / and \\ for each double bond. Code will parse every structure, compute its formula and match your "
    "target against the answer options exactly, so a SMILES that is not the compound you mean fails its check. Name "
    "the decisive chemistry (regiochemistry, the endo rule, syn or anti addition, inversion, facial selectivity, "
    "conjugation) in key_reasoning.\n\n"
    "Reply with JSON only:\n"
    '{"steps": [{"label": "product 1", "name": "IUPAC name", "smiles": "SMILES", "reason": "one sentence"}], '
    '"target": {"role": "product", "name": "IUPAC name", "smiles": "SMILES", "geometry": "relative configuration '
    'in words, or empty"}, "answer": "the option letter you choose, or the value", "key_reasoning": "at most four '
    'sentences"}'
)


class ChemStep(BaseModel):
    label: str = ""
    name: str = ""
    smiles: str = ""
    reason: str = ""


class ChemTarget(BaseModel):
    role: str = ""  # product, starting material, reagent, intermediate: the compound the question asks about
    name: str = ""
    smiles: str = ""
    geometry: str = ""


class ChemSolution(BaseModel):
    steps: list[ChemStep] = Field(default_factory=list)
    target: ChemTarget = Field(default_factory=ChemTarget)
    answer: str = ""
    key_reasoning: str = ""


def is_organic_question(text: str) -> bool:
    """An organic-chemistry question: a structure question, or a reaction word with two or more organic names."""
    from ..physis.chemistry import is_structure_question

    t = text or ""
    if is_structure_question(t):
        return True
    if not _REACTION_RE.search(t):
        return False
    names = {m.group(0).lower() for m in _ORGANIC_NAME_RE.finditer(t)} - _NOT_ORGANIC
    return len(names) >= 2


def _enabled(state: Any) -> bool:
    from ..config.settings import get_bool

    options = getattr(state, "options", None) or {}
    return bool(get_bool("TRIBOS_CHEM_AGENT")) and options.get("enable_chem_agent", True) is not False


def chem_agent_enabled() -> bool:
    from ..config.settings import get_bool

    return bool(get_bool("TRIBOS_CHEM_AGENT"))


# -- Code checks ---------------------------------------------------------------------------------------------------------
_OPTION_MARK_RE = re.compile(r"^\(?([A-Ha-h])[).:]\s*")
_OPTION_SMILES_RE = re.compile(r"SMILES\s*:\s*(\S+)", re.I)


def _canonical(smiles: str, isomeric: bool = True) -> tuple[str, str] | None:
    """(canonical SMILES, formula) with atom maps cleared, or None when the SMILES does not parse."""
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors

        from ..physis.chemistry import _parse
    except Exception:  # noqa: BLE001
        return None
    try:
        mol = _parse(smiles)
    except ValueError:
        return None
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    if not isomeric:
        Chem.RemoveStereochemistry(mol)
    return Chem.MolToSmiles(mol), rdMolDescriptors.CalcMolFormula(mol)


def _fully_specified(smiles: str) -> bool:
    """Every stereo element of the structure has its configuration written."""
    try:
        from rdkit import Chem

        from ..physis.chemistry import _parse
    except Exception:  # noqa: BLE001
        return False
    try:
        mol = _parse(smiles)
    except ValueError:
        return False
    infos = Chem.FindPotentialStereo(mol)
    return bool(infos) and all(i.specified == Chem.StereoSpecified.Specified for i in infos)


def option_structures(question: str) -> list[dict[str, Any]]:
    """Each answer option whose structure code can build: from its SMILES, or from its name (tribos.physis.names) with
    its stereodescriptors assigned. Options naming several compounds ("A = ..., B = ...") are left out."""
    from ..agents.question_text import is_choice_question, option_texts
    from ..physis.chemistry import assign_descriptors, parse_descriptors, _element_for_locant, _stereo_elements, _take_locants
    from ..physis.names import parse_name

    if not is_choice_question(question or ""):
        return []
    out: list[dict[str, Any]] = []
    for text in option_texts(question):
        mark = _OPTION_MARK_RE.match(text)
        if not mark:
            continue
        # The last option runs on to the end of the question ("... Choose the single correct option ..."): an option
        # is its first line, or its first block when the option itself spans lines (a name, then its SMILES).
        rest = text[mark.end():].strip()
        letter, body = mark.group(1).upper(), rest.split("\n")[0].strip()
        smiles = ""
        source = ""
        m = _OPTION_SMILES_RE.search(rest)
        if m:
            smiles, source = m.group(1).rstrip(".,;"), "smiles"
        elif "=" not in body and " " not in body.strip().rstrip(".") and len(body) <= 200:
            parsed = parse_name(body.rstrip("."))
            if parsed is not None:
                smiles, source = parsed.smiles, "name"
                if parsed.descriptors:
                    try:
                        from ..physis.chemistry import _cip, _parse
                        from rdkit import Chem

                        base = _parse(parsed.smiles)
                        labels = _take_locants(base, None)
                        Chem.RemoveStereochemistry(base)
                        elements = _stereo_elements(base)
                        wanted = {_element_for_locant(base, elements, labels, loc, letter_): letter_
                                  for loc, letter_ in parse_descriptors(parsed.descriptors)}
                        assigned = assign_descriptors(base, wanted)
                        smiles = Chem.MolToSmiles(_cip(assigned)) if assigned is not None else ""
                    except Exception:  # noqa: BLE001 - descriptors that cannot be assigned leave the option unbuilt
                        smiles = ""
        if not smiles:
            continue
        iso, flat = _canonical(smiles), _canonical(smiles, isomeric=False)
        if iso is None or flat is None:
            continue
        out.append({"option": letter, "source": source, "smiles": iso[0], "constitution": flat[0], "formula": iso[1],
                    "stereo": _fully_specified(iso[0])})
    return out


def check_solution(question: str, solution: ChemSolution, options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What code can check of a solution: every structure parses (formula, unsaturation), the product's counts, and
    which answer option the product is."""
    from ..physis.chemistry import molecule_facts

    report: dict[str, Any] = {"steps": [], "invalid": [], "target": {}, "options": [], "match": {}}
    for step in solution.steps[:12]:
        entry: dict[str, Any] = {"label": step.label, "name": step.name, "smiles": step.smiles}
        canon = _canonical(step.smiles) if step.smiles else None
        if step.smiles and canon is None:
            report["invalid"].append(f"{step.label or 'a step'}: '{step.smiles}' is not a valid SMILES")
        elif canon is not None:
            entry["formula"] = canon[1]
        report["steps"].append(entry)
    product = solution.target
    canon = _canonical(product.smiles) if product.smiles else None
    if not product.smiles:
        report["invalid"].append("no SMILES for the target compound")
    elif canon is None:
        report["invalid"].append(f"target: '{product.smiles}' is not a valid SMILES")
    else:
        facts = molecule_facts([product.smiles], [product.name or "target"])["molecules"][0]
        report["target"] = {
            "role": product.role, "name": product.name, "smiles": canon[0], "formula": canon[1], "geometry": product.geometry,
            "stereo_specified": _fully_specified(canon[0]),
            **{k: facts.get(k) for k in ("degree_of_unsaturation", "stereo", "chiral", "meso", "h_environments",
                                         "h_environments_on_carbon", "c_environments", "stereoisomers_of_constitution")
               if facts.get(k) is not None},
        }
    options = option_structures(question) if options is None else options
    report["options"] = [{k: o[k] for k in ("option", "source", "formula", "smiles")} for o in options]
    if canon is not None and options:
        flat = _canonical(product.smiles, isomeric=False)
        constitution = [o["option"] for o in options if flat is not None and o["constitution"] == flat[0]]
        exact = [o["option"] for o in options if o["smiles"] == canon[0]]
        same_formula = [o["option"] for o in options if o["formula"] == canon[1]]
        report["match"] = {"constitution": constitution, "exact": exact, "same_formula": same_formula}
    report["status"] = _status(report, solution.answer)
    return report


def _letter(answer: str) -> str:
    m = re.match(r"^\s*\(?([A-Ha-h])\)?(?:[\s.):]|$)", answer or "")
    return m.group(1).upper() if m else ""


def _status(report: dict[str, Any], answer: str) -> str:
    if report["invalid"]:
        return "invalid"
    match = report.get("match") or {}
    if not report.get("options"):
        return "checked"  # structures valid; no option structure to compare with
    chosen = _letter(answer)
    exact, constitution = match.get("exact") or [], match.get("constitution") or []
    if exact:
        return "matched" if chosen in exact else "mismatch"
    if constitution:
        if chosen and chosen not in constitution:
            return "mismatch"
        return "matched" if len(constitution) == 1 else "constitution_matched"
    if chosen and any(o["option"] == chosen for o in report["options"]):
        return "mismatch"  # the chosen option was built and is not the target
    return "unmatched"


def repair_feedback(report: dict[str, Any], answer: str) -> str:
    """What code found wrong, for the one repair round; "" when nothing needs repairing."""
    status = report.get("status")
    lines: list[str] = []
    if status == "invalid":
        lines.extend(report["invalid"])
        lines.append("Write each of these as a valid SMILES of the compound you mean.")
    elif status == "mismatch":
        match = report.get("match") or {}
        found = match.get("exact") or match.get("constitution") or []
        product = report.get("target") or {}
        lines.append(
            f"Your target SMILES ({product.get('formula')}) is option {', '.join(found)} by code"
            if found else f"Your target SMILES ({product.get('formula')}) is not the structure of option {_letter(answer)}")
        lines.append(f"but you answered {_letter(answer) or answer}. One of the two is wrong: re-check the step that "
                     "decides it and make the target SMILES and the answer agree.")
    elif status == "unmatched":
        product = report.get("target") or {}
        built = "; ".join(f"{o['option']}: {o['formula']}" for o in report.get("options") or [])
        lines.append(f"Your target ({product.get('formula')}) has the constitution of no option that code could build "
                     f"({built}). Re-check each step: a reagent role, a count of carbons, or a SMILES that is not the "
                     "compound you named.")
    return "\n".join(lines)


# -- Evidence ------------------------------------------------------------------------------------------------------------
def _esc(value: Any, limit: int = 400) -> str:
    text = str(value if value is not None else "")
    return escape(text[:limit] + ("..." if len(text) > limit else ""), quote=True)


def evidence_xml(solution: ChemSolution, report: dict[str, Any], repaired: bool) -> str:
    match = report.get("match") or {}
    product = report.get("target") or {}
    lines = [f'<chem_agent agent="{AGENT_NAME}" status="{_esc(report.get("status"))}" answer="{_esc(solution.answer, 80)}" '
             f'repaired="{str(repaired).lower()}" checked_by="RDKit: structures parsed, formulas, counts and option '
             f'matching; the chemistry (which compounds form) is the agent\'s reasoning, not checked by code">']
    for step in report.get("steps") or []:
        lines.append(f'<step label="{_esc(step.get("label"), 60)}" name="{_esc(step.get("name"), 160)}" '
                     f'smiles="{_esc(step.get("smiles"), 300)}" formula="{_esc(step.get("formula", "invalid"), 40)}"/>')
    if product:
        facts = {k: product[k] for k in ("degree_of_unsaturation", "chiral", "meso", "h_environments",
                                         "h_environments_on_carbon", "c_environments") if k in product}
        iso = product.get("stereoisomers_of_constitution") or {}
        lines.append(
            f'<target role="{_esc(product.get("role"), 40)}" name="{_esc(product.get("name"), 160)}" '
            f'smiles="{_esc(product.get("smiles"), 300)}" '
            f'formula="{_esc(product.get("formula"), 40)}" geometry="{_esc(product.get("geometry"), 200)}" '
            f'configuration_written="{str(bool(product.get("stereo_specified"))).lower()}" '
            f'stereo="{_esc(product.get("stereo"), 300)}" facts="{_esc(facts, 300)}" '
            f'stereoisomers_of_constitution="{_esc(iso, 200)}"/>')
    for o in report.get("options") or []:
        lines.append(f'<option letter="{_esc(o["option"], 4)}" built_from="{_esc(o["source"], 10)}" '
                     f'formula="{_esc(o["formula"], 40)}" smiles="{_esc(o["smiles"], 300)}"/>')
    if match:
        lines.append(f'<option_match exact="{_esc(", ".join(match.get("exact") or []) or "none")}" '
                     f'same_constitution="{_esc(", ".join(match.get("constitution") or []) or "none")}" '
                     f'same_formula="{_esc(", ".join(match.get("same_formula") or []) or "none")}"/>')
    for problem in report.get("invalid") or []:
        lines.append(f"<invalid>{_esc(problem, 300)}</invalid>")
    if solution.key_reasoning:
        lines.append(f"<key_reasoning>{_esc(solution.key_reasoning, 1200)}</key_reasoning>")
    lines.append("</chem_agent>")
    return "\n".join(lines)


def brief_note(report: dict[str, Any], answer: str) -> str:
    status = report.get("status")
    match = report.get("match") or {}
    if status == "matched":
        found = ", ".join(match.get("exact") or match.get("constitution") or [])
        return (f"The chemistry agent Chemeia worked the reaction (see <chem_agent>), and code matched its target's "
                f"structure to option {found}. Code checked the structures, not the chemistry: read its steps and "
                "key_reasoning. If you agree, answer with that option; if a step is chemically wrong, name the step and "
                "correct it.")
    if status == "constitution_matched":
        return (f"The chemistry agent Chemeia's target compound (see <chem_agent>) has the constitution of options "
                f"{', '.join(match.get('constitution') or [])}; code did not decide between them. Decide the "
                "configuration from the mechanism and match it to those options with the <chemistry> ring faces when "
                "present.")
    if status == "checked":
        return ("The chemistry agent Chemeia worked the reaction (see <chem_agent>); its structures are valid and the "
                "listed formulas and counts were computed by code. Use those values rather than counting by hand.")
    if status == "invalid":
        return ("The chemistry agent's structures did not pass code checks (see <chem_agent>): do not rely on its "
                "answer; work the chemistry yourself.")
    return ("The chemistry agent's target structure and its answer disagree with code's option matching (see <chem_agent>): do "
            "not rely on its answer; work the chemistry yourself and state which step decides it.")


# -- Phase ---------------------------------------------------------------------------------------------------------------
class ChemAgentPhase(AgentPhase):
    key = PHASE_KEY
    stage = "augment"
    order = 30
    frameworks = None
    needs_llm = True

    def applies(self, state: AgentState) -> bool:
        if not _enabled(state):
            return False
        try:
            import rdkit  # noqa: F401
        except ImportError:  # pragma: no cover - rdkit is a declared dependency
            return False
        return is_organic_question(state.clean_query or state.query)

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        question = state.clean_query or state.query
        await state.step("agent_chem", "Working the chemistry and checking each structure", status="running",
                         agent=AGENT_NAME)
        from .llm import AgentLLMUnavailable, BudgetExhausted

        options = option_structures(question)
        user = f"<question>\n{question}\n</question>"
        solution: ChemSolution | None = None
        report: dict[str, Any] = {}
        repaired = False
        for attempt in range(MAX_REPAIRS + 1):
            try:
                reply: ChemSolution = await state.llm.json(SOLVE_SYSTEM, user, schema=ChemSolution, phase=PHASE_KEY)
            except (AgentLLMUnavailable, BudgetExhausted, ValueError) as exc:
                logger.info("Chemistry agent: no usable reply (%s)", exc)
                break
            solution = reply
            report = check_solution(question, reply, options)
            feedback = repair_feedback(report, reply.answer)
            if not feedback or attempt == MAX_REPAIRS:
                break
            repaired = True
            await state.step("agent_chem_repair", "Repairing the solution code rejected", feedback[:300],
                             status="done", agent=AGENT_NAME)
            user = (f"<question>\n{question}\n</question>\n\n<your_previous_solution>\n"
                    f"{reply.model_dump_json()[:6000]}\n</your_previous_solution>\n\n<code_check>\n{feedback}\n"
                    "</code_check>\n\nReply with the corrected JSON only.")
        if solution is None:
            state.mark_phase(PHASE_KEY, "fallback", "the chemistry agent produced no usable solution")
            await state.step("agent_chem", "No chemistry solution", status="error", agent=AGENT_NAME)
            return None
        art = {"status": report.get("status"), "answer": solution.answer, "repaired": repaired,
               "solution": solution.model_dump(), "report": report}
        state.artifacts[PHASE_KEY] = art
        state.evidence_sections.append(evidence_xml(solution, report, repaired))
        note = brief_note(report, solution.answer)
        (state.brief_notes if report.get("status") in ("matched", "constitution_matched", "checked")
         else state.scope_notes).append(note)
        ok = report.get("status") in ("matched", "constitution_matched", "checked")
        state.mark_phase(PHASE_KEY, "ok" if ok else "fallback", "" if ok else str(report.get("status")))
        await state.step("agent_chem", f"Chemistry: {str(report.get('status')).replace('_', ' ')}"
                         + (f", answer {solution.answer}" if solution.answer else ""),
                         (report.get("target") or {}).get("formula", ""), status="done" if ok else "error",
                         agent=AGENT_NAME)
        return PhaseOutcome(artifacts={PHASE_KEY: art})


register_phase(ChemAgentPhase())


__all__ = ["ChemSolution", "check_solution", "chem_agent_enabled", "is_organic_question", "option_structures",
           "repair_feedback"]
