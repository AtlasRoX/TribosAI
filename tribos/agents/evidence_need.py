"""Does a question need outside evidence? The gate in front of literature and web search.

Retrieval helps when the answer depends on facts outside the question: published results, measured values, standards,
the current state of something. It hurts self-contained questions. Irrelevant passages distract the model (Shi et al.,
ICML 2023, "Large Language Models Can Be Easily Distracted by Irrelevant Context"), invite citations a claim checker
then rejects, and cost model calls; for a closed-form problem the evidence that matters is an independent computation
(PAL, ToRA), not a paper.

Learned "no retrieval needed" classifiers are weak (Adaptive-RAG, NAACL 2024: 30.5% accuracy on that class), so this
gate is deterministic and conservative, in the spirit of UAR (Findings of EMNLP 2024): explicit intent wins, and
retrieval is skipped only when the question is confidently self-contained. When unsure, retrieval runs as before.

- required: the question asks for literature, sources or citations, or depends on time ("latest", "as of 2026").
- optional: anything else that is not provably self-contained (empirical values, named materials or systems, open
  questions); retrieval runs.
- none: a computation the math parser fully captures (every number in the question is part of the parsed problem),
  with no request for sources and no empirical, time-sensitive or domain-entity signal. The verified mathematics
  agent answers it; literature, web search, hypotheses, counter-evidence and gap searches are skipped.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

Level = Literal["none", "optional", "required"]

# Explicit requests for sources: the reader wants the answer tied to published work.
_LITERATURE_RE = re.compile(
    r"\b(?:papers?|literature|publications?|preprints?|journals?|bibliograph\w*|citations?|cite[sd]?|citing|"
    # Not "voltage source", "heat source" or "reference frame": only sources and references as citations.
    r"references|(?:with|give|list|add|include|cite)\s+(?:a\s+|the\s+)?(?:sources?|references?)|"
    r"(?:primary|credible|reliable|academic)\s+sources?|"
    r"arxiv|dois?|zbmath|survey|state[\s-]of[\s-]the[\s-]art|prior\s+work|related\s+work|"
    r"recent\s+(?:work|advances|research|results|developments|progress|studies)|published|reported\s+(?:in|by)|"
    r"according\s+to|studies|study\s+(?:shows?|found|reports?)|historical(?:ly)?|history\s+of|"
    r"who\s+(?:first|discovered|proved|introduced|invented))\b",
    re.IGNORECASE,
)
# Answers that change with time.
_TIME_RE = re.compile(
    # A year only in a dated phrase: "2^2024 mod 7" is arithmetic, "as of 2025" is not.
    r"\b(?:latest|newest|recent(?:ly)?|currently|nowadays|today|this\s+(?:year|month|week)|news|"
    r"world\s+record|market\s+prices?|(?:in|since|as\s+of|during|until)\s+(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
# Values that come from measurement, tables or standards rather than from the question.
_EMPIRICAL_RE = re.compile(
    # Not "standard deviation", "an experiment tosses a coin" or "the data set 1, 2, 3": statistics and probability
    # problems carry their data in the question.
    r"\b(?:measured|measurements?|experimental(?:ly)?\s+(?:data|values?|results?)|empirical(?:ly)?|"
    r"typical(?:ly)?|in\s+practice|real[\s-]world|datasheets?|manufacturers?|commercial(?:ly)?|benchmarks?|"
    r"(?:design|engineering|industry|international|safety|building)\s+(?:standards?|codes?)|"
    r"code\s+(?:of\s+practice|requirements?)|ASME|ASTM|ISO\s*\d+|IEC|Eurocode|NFPA|"
    r"material\s+properties|properties\s+of|yield\s+strength|tensile\s+strength|thermal\s+conductivity|"
    r"viscosity|density\s+of|modulus\s+of|coefficient\s+of\s+(?:friction|drag|restitution|thermal))\b",
    re.IGNORECASE,
)
# Entity kinds whose facts live outside the question.
_DOMAIN_ENTITY_ATTRS = ("materials", "constants", "systems", "genes", "drugs", "diseases", "variants")


@dataclass(frozen=True)
class EvidenceNeed:
    level: Level
    kind: str  # closed_computation | literature | current | empirical | open
    reason: str
    signal: str = ""  # the words or parse result that decided it (logged, shown in the plan)

    @property
    def skip_retrieval(self) -> bool:
        return self.level == "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CLOSED_REASON = "self-contained calculation: solved and checked by computation, no outside evidence needed"


def _match(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(0) if m else ""


def _domain_entities(ctx: Any) -> list[tuple[str, str]]:
    """(kind, label) of the resolved domain entities."""
    if ctx is None:
        return []
    found: list[tuple[str, str]] = []
    for attr in _DOMAIN_ENTITY_ATTRS:
        for ent in getattr(ctx, attr, None) or []:
            found.append((attr, str(getattr(ent, "label", None) or getattr(ent, "mention", None) or ent)))
    return found


# A statement to prove about mathematical objects ("show that the sum of two odd integers is even").
_PROOF_RE = re.compile(r"\b(?:prove|show|verify|demonstrate|establish|disprove)\s+(?:or\s+disprove\s+)?that\b", re.I)
_MATH_OBJECT_RE = re.compile(
    r"\b(?:integers?|primes?|polynomials?|functions?|matri(?:x|ces)|vectors?|sets?|groups?|rings?|graphs?|sequences?|"
    r"series|triangles?|circles?|divisible|odd|even|rational|irrational|real\s+numbers?|complex\s+numbers?|derivatives?|"
    r"integrals?|inequalit(?:y|ies)|equations?|roots?|digits?|numbers?)\b", re.I)
# A quantity the question gives: a number with a unit ("120 L", "4 L/min", "3.2 kg").
_GIVEN_QUANTITY_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s*([A-Za-zµΩ°][A-Za-z/^0-9·*]{0,10})")
_ASKS_VALUE_RE = re.compile(
    r"\b(?:how\s+(?:long|much|many|far|fast|big|high|large|often)|calculate|compute|find|determine|work\s+out|"
    r"what\s+(?:is|are|was|will\s+be)\s+the\s+(?:value|total|time|speed|rate|area|volume|mass|cost|force|energy|power|"
    r"pressure|current|voltage|resistance|distance|probability|percentage))\b", re.I)


def _given_quantities(text: str) -> int:
    from ..verify.latex_math import is_unit_word

    return sum(1 for m in _GIVEN_QUANTITY_RE.finditer(text) if is_unit_word(m.group(1).split("/")[0]))


FORMAT_REASON = "the request is to return given text exactly; no outside evidence applies"
SELF_CONTAINED_REASON = ("mathematics stated in the question (a proof, derivation or calculation from its own "
                         "definitions): answered by reasoning and checked computation, no outside evidence needed; ask "
                         "for sources to search the literature")
MODEL_REASON = ("a model stated in the question, to be simulated or solved: the computation answers it, no outside "
                "evidence needed; ask for sources to search the literature")
GIVEN_DATA_REASON = "a calculation from the values the question gives: no outside evidence needed"
ESTABLISHED_REASON = ("a conceptual question about established knowledge: no search needed; ask for sources or recent "
                      "work to search the literature")
# Written mathematics: an equation, a power, a function application, LaTeX or math symbols.
_MATH_NOTATION_RE = re.compile(r"[=^∫∑√≤≥≠]|\\(?:frac|int|sum|sqrt)|\b[A-Za-z]\s*\(\s*[A-Za-z0-9]\s*\)|\d\s*[a-z]\b")


def assess_evidence_need(query: str, ctx: Any = None) -> EvidenceNeed:
    """The evidence need of one question (see the module docstring). `ctx` (a QueryContext) adds its resolved
    domain entities; without it only the text decides.

    Retrieval follows an identified information need, not the availability of search (adaptive retrieval: outside
    sources help with specific, long-tail or current facts and can mislead on what is established). Format
    instructions ("answer in at most 40 words") never decide the need."""
    from ..utils.output_contract import extract, mask_instructions

    contract = extract(str(query or ""))
    if contract.pure_copy:
        return EvidenceNeed("none", "format", FORMAT_REASON, "literal copy")
    text = mask_instructions(str(query or ""))
    lit = _match(_LITERATURE_RE, text)
    if lit:
        return EvidenceNeed("required", "literature", "the question asks for published sources", lit)
    when = _match(_TIME_RE, text)
    if when:
        return EvidenceNeed("required", "current", "the answer depends on recent or dated information", when)
    empirical = _match(_EMPIRICAL_RE, text)
    if empirical:
        return EvidenceNeed("optional", "empirical", "the answer uses measured or tabulated values", empirical)
    entities = _domain_entities(ctx)
    if entities:
        models_only = all(kind == "systems" for kind, _ in entities)
        if models_only and (getattr(ctx, "is_simulation_intent", False) or _MATH_NOTATION_RE.search(text)):
            # A model the question states and asks to simulate or solve ("the damped oscillator x'' + 0.5x' + 4x = 0"):
            # the computation answers it; papers about oscillators in general are not evidence for this run.
            return EvidenceNeed("none", "self_contained", MODEL_REASON, entities[0][1])
        return EvidenceNeed("optional", "empirical", "the question names real materials, systems or constants", entities[0][1])
    from ..axiom.problem import parse_problem  # local: sympy is heavy and only needed here

    try:
        spec = parse_problem(text)
    except Exception:  # noqa: BLE001 - an unparseable question simply is not provably self-contained
        spec = None
    if spec is not None and spec.parsed and not spec.unaccounted:
        return EvidenceNeed("none", "closed_computation", CLOSED_REASON, f"{spec.kind}: {spec.expression or ''}".strip())
    from ..axiom.problem import has_math_intent
    from .search_plan import classify_question

    qtype = classify_question(text)
    if _ASKS_VALUE_RE.search(text) and _given_quantities(text) >= 2:
        # A calculation from values the question supplies ("a 120 L tank drains at 4 L/min; how long ...").
        return EvidenceNeed("none", "self_contained", GIVEN_DATA_REASON, "given quantities")
    proof = bool(_PROOF_RE.search(text) and _MATH_OBJECT_RE.search(text))
    # A derivation over physical quantities with units ("a steel ball ... in water") may need reference values the
    # question does not give, so only unit-free mathematics counts as self-contained here.
    unit_free = _given_quantities(text) == 0
    if proof or qtype == "proof" or (unit_free and (qtype == "derivation" or (has_math_intent(text) and _MATH_NOTATION_RE.search(text)))):
        # A proof, derivation or calculation about objects the question itself defines (no named real-world system,
        # material or dataset, no request for sources): papers matching its generic words ("case", "integer",
        # "function") are noise, never evidence.
        return EvidenceNeed("none", "self_contained", SELF_CONTAINED_REASON, qtype)
    if qtype == "conceptual":
        return EvidenceNeed("none", "established_knowledge", ESTABLISHED_REASON, qtype)
    return EvidenceNeed("optional", "open", "the answer may depend on published findings", qtype)


# A request whose answer is a number the run computes ("simulate", "report the maximum absolute error", "step-size
# convergence", "energy balance"), not a fact found in a source.
_COMPUTATION_REQUEST_RE = re.compile(
    r"\b(?:simulat|comput|calculat|compar|residual|converg|step[\s-]?size|absolute\s+error|relative\s+error|"
    r"numerical(?:ly)?\b|derive|derivation|solve|verify\s+(?:the\s+)?units|dimensional|energy\s+balance|plot)\w*",
    re.IGNORECASE,
)
_SOURCE_REQUEST_RE = re.compile(r"\b(?:references?|literature|papers?|sources?|cite|citations?|published|studies|review)\b",
                                re.IGNORECASE)


def is_computation_request(text: str) -> bool:
    """A sub-question answered by computing (a literature or web search cannot produce its result) and not also asking
    for sources. Gap searches and the escalation to a critic debate leave these to the computation tools."""
    return bool(_COMPUTATION_REQUEST_RE.search(text or "")) and not _SOURCE_REQUEST_RE.search(text or "")


_NETWORKED_ADAPTERS = frozenset({"DIRECT_REST", "DIRECT_GRAPHQL", "REMOTE_MCP"})


def is_external_retrieval(entry: Any) -> bool:
    """A tool that fetches from a service outside Tribos (scholarly APIs, web search, encyclopedia and online database
    lookups): its registry adapter is networked. A bare name is looked up in the registry."""
    if isinstance(entry, str):
        try:
            from ..tools.registry import get_tool_registry

            entry = get_tool_registry().get_entry(entry) or entry
        except Exception:  # noqa: BLE001
            return False
    adapter = getattr(entry, "adapter_type", None)
    return str(getattr(adapter, "value", adapter) or "") in _NETWORKED_ADAPTERS


def external_retrieval_block(ctx: Any, entry: Any) -> str | None:
    """Why a networked tool may not run this turn, or None: Search is off (every external retrieval, literature
    included), or the question needs no outside evidence (a self-contained calculation, proof or copy)."""
    if ctx is None or not is_external_retrieval(entry):
        return None
    if not getattr(ctx, "enable_web_search", True):
        return "Search is off for this turn"
    need = getattr(ctx, "evidence_need", None)
    if need is not None and need.skip_retrieval:
        return str(need.reason or "no outside evidence is needed for this question")
    return None


def is_closed_computation(ctx: Any) -> bool:
    need = getattr(ctx, "evidence_need", None)
    return bool(need is not None and need.kind == "closed_computation")


def is_self_contained(ctx: Any) -> bool:
    """No outside evidence applies: a closed computation, mathematics from the question's own definitions, a copy."""
    need = getattr(ctx, "evidence_need", None)
    return bool(need is not None and need.kind in ("closed_computation", "self_contained", "format"))


# The answer shape for a self-contained calculation (added to the synthesis request): the general format rules
# (regimes, dimensionless numbers, evidence limitations, suggested experiments) do not apply to it.
CLOSED_COMPUTATION_ANSWER_NOTE = (
    "ANSWER SHAPE: this is a self-contained calculation. No literature or web search was run because none is needed; "
    "do not cite papers or web pages and do not mention that no literature was searched. Write: (1) the result first, "
    "exact and, where useful, as a decimal; (2) the working, one step per line, in the order the question asks for; "
    "(3) a short Verification section naming the independent checks that agree. Leave out governing regimes, "
    "dimensionless numbers, physical units the question does not use, 'Evidence limitations', hypotheses and "
    "'Suggested next experiments'. The confidence line rests on the computational verification."
)


__all__ = [
    "CLOSED_COMPUTATION_ANSWER_NOTE",
    "CLOSED_REASON",
    "EvidenceNeed",
    "assess_evidence_need",
    "is_closed_computation",
]
