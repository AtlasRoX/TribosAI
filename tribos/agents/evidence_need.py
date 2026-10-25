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


def _domain_entities(ctx: Any) -> list[str]:
    if ctx is None:
        return []
    found: list[str] = []
    for attr in _DOMAIN_ENTITY_ATTRS:
        for ent in getattr(ctx, attr, None) or []:
            found.append(str(getattr(ent, "label", None) or getattr(ent, "mention", None) or ent))
    return found


def assess_evidence_need(query: str, ctx: Any = None) -> EvidenceNeed:
    """The evidence need of one question (see the module docstring). `ctx` (a QueryContext) adds its resolved
    domain entities; without it only the text decides."""
    text = str(query or "")
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
        return EvidenceNeed("optional", "empirical", "the question names real materials, systems or constants", entities[0])
    from ..axiom.problem import parse_problem  # local: sympy is heavy and only needed here

    try:
        spec = parse_problem(text)
    except Exception:  # noqa: BLE001 - an unparseable question simply is not provably self-contained
        spec = None
    if spec is not None and spec.parsed and not spec.unaccounted:
        return EvidenceNeed("none", "closed_computation", CLOSED_REASON, f"{spec.kind}: {spec.expression or ''}".strip())
    return EvidenceNeed("optional", "open", "not provably self-contained", "")


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


def is_closed_computation(ctx: Any) -> bool:
    need = getattr(ctx, "evidence_need", None)
    return bool(need is not None and need.kind == "closed_computation")


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
