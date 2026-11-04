"""
Hypothesis -> in-silico experiment loop (feature 6, stage augment, order 40).

Techniques
- AI co-scientist (Gottweis et al. 2025, arXiv:2502.18864): Generation -> Reflection -> Ranking by an Elo
  tournament (every hypothesis starts at 1200, K = 32; pairwise judge) -> Evolution (the top hypothesis is refined
  once and enters the tournament as a new hypothesis).
- DiscoveryAgent (Roohani et al., ICLR 2025, arXiv:2405.17631): the generation prompt carries the research
  problem, the measurement definition (readout, metric, effect threshold), the results gathered so far and an
  exclusion list of perturbations already tested; the model returns a reflection, a short research plan and a
  batch of perturbations. Invalid or repeated perturbations are rejected, never silently changed.
- Robin (Ghareeb et al. 2025, arXiv:2505.13400): ranking with a pairwise LLM judge (Robin fits Bradley-Terry;
  Elo is the online approximation used here).

In-silico experiments
- Only when a dynamical system is in play (a Dynamis ODE preset the question names, e.g. "the damped oscillator",
  "the Lorenz system", with the simulation plan's duration and parameter values) and simulation is allowed: never
  when ctx.suppress_simulation is set, a simulation is forbidden, or the turn's source restriction excludes Dynamis.
- A hypothesis perturbs one system parameter by a factor (reduction < 1, elevation > 1, variation either way) and
  predicts the direction of change of one metric (final, peak, min, mean, range, overshoot) of one state
  variable. It is run as dynamis_parameter_scan from the parameter's value to the perturbed value (5 points), so
  the first point is the unperturbed baseline and the scan also shows whether the effect is monotonic.
- Effect: relative change of the metric, (perturbed - baseline) / |baseline| (a metric whose baseline and
  perturbed values are both below 1e-6 of the trajectory's scale has no change). Support = the predicted
  direction and |relative change| >= 0.05. At most 4 scans per run.
- Without a system (or with simulation switched off) hypotheses are ranked on the retrieved evidence only and are
  labelled untested; no experiment result is ever invented.

Without a model call the phase is deterministic: perturbations come from the system parameters the question names
(by symbol, "zeta", or by role, "damping"), the direction from the question's own claim ("increasing damping
reduces overshoot"), the readout from the state variables and metric words it uses. A question without a
simulatable system gets no deterministic hypotheses. Writes the artifact "hypotheses" and a
<hypothesis_experiments> evidence section.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from html import escape
from typing import Any

from ..agents.evidence_need import is_closed_computation
from .budget import BudgetExhausted
from .guardrails import SPOTLIGHT_RULE, neutralise, spotlight
from .llm import AgentLLMUnavailable
from .runtime import AgentPhase, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE = "hypothesis"
SCAN_TOOL = "dynamis_parameter_scan"

ELO_START = 1200.0
ELO_K = 32.0
REL_CHANGE_THRESHOLD = 0.05
NEGLIGIBLE_SCALE = 1e-6
SCAN_POINTS = 5
EPS_RELATIVE = 1e-9
MAX_HYPOTHESES = 6
MAX_EXPERIMENTS = 4
MAX_JUDGE_CALLS = 8
# Increase kinds raise the parameter (factor > 1), decrease kinds lower it (factor < 1); variation goes either way.
INCREASE_KINDS = ("elevation", "overexpression")
DECREASE_KINDS = ("reduction", "knockdown", "inhibition")
KINDS = (*DECREASE_KINDS, *INCREASE_KINDS, "variation")
DEFAULT_FACTORS = {"reduction": 0.5, "knockdown": 0.1, "inhibition": 0.1, "elevation": 2.0, "overexpression": 10.0,
                   "variation": 1.5}
METRICS = ("final", "peak", "min", "mean", "range", "overshoot")
# Hypotheses are predictions, not reports: they must not assert data the evidence does not contain.
GROUNDED_STATEMENT_RULE = (
    "Write each statement as a testable prediction (\"X will ...\", \"if X then Y\"), not a recommendation to "
    "evaluate something. Never assert experimental measurements or dataset parameters unless the evidence given here contains them. "
    "Any test you describe must prespecify the design, the readout parameter, the expected effect direction, and the decision rule that refutes the prediction."
)
TEXT_DUPLICATE_JACCARD = 0.8

_INTENT_RE = re.compile(
    # Not "predict" or "experiment": in physics and engineering those mean "compute" or "measure", not "hypothesise".
    # Not a named hypothesis or conjecture either ("the status of the Riemann Hypothesis"): a request to generate
    # them is HYPOTHESIS_REQUEST_RE (audit I35/I36).
    r"\bwhat (?:would|will|might) happen|\bwhat if\b|\bperturb|\bin[\s-]?silico\b|"
    r"\bcandidate (?:mechanism|explanation|cause)|\bwhich (?:parameter|component|mechanism)|"
    r"\b(?:does|do|would|will|could)\s+(?:increasing|decreasing|raising|lowering|reducing|doubling|halving)\b",
    re.I,
)
_READOUT_CUE_RE = re.compile(
    r"(?:happens?\s+to|effect\s+on|impact\s+on|influence\s+on|response\s+of|output\s+of|value\s+of|behaviou?r\s+of)"
    r"\s+(?:the\s+)?([\w\-\[\]().]+)",
    re.I,
)
_RAISE_RE = re.compile(r"\b(?:increas\w*|rais\w*|higher|larger|greater|more|doubl\w*|stronger|stiffer|heavier|longer)\b", re.I)
_LOWER_RE = re.compile(r"\b(?:decreas\w*|reduc\w*|lower\w*|smaller|less|fewer|halv\w*|weaker|softer|lighter|shorter)\b", re.I)
# Words for the effect a question claims, after the perturbation ("increasing damping reduces overshoot").
_EFFECT_DOWN_RE = re.compile(r"\b(?:reduc\w*|decreas\w*|lower\w*|suppress\w*|dampen\w*|shrink\w*|shorten\w*|diminish\w*|slow\w*)\b", re.I)
_EFFECT_UP_RE = re.compile(r"\b(?:increas\w*|rais\w*|amplif\w*|grow\w*|lengthen\w*|enlarg\w*|boost\w*|speed\w* up)\b", re.I)
_METRIC_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("overshoot", re.compile(r"\bovershoot\w*|\bundershoot\w*", re.I)),
    ("range", re.compile(r"\bamplitude\w*|\bswing\w*|\bexcursion\w*|\boscillation\w*|\bpeak[- ]to[- ]peak\b", re.I)),
    ("peak", re.compile(r"\bpeak\w*|\bmaxim\w*|\bhighest\b", re.I)),
    ("min", re.compile(r"\bminim\w*|\blowest\b|\btrough\w*", re.I)),
    ("mean", re.compile(r"\bmean\b|\baverage\w*", re.I)),
    ("final", re.compile(r"\bfinal\b|\bsteady[- ]state\b|\blong[- ]term\b|\bendpoint\b|\bend value\b|\bsettl\w*", re.I)),
)
# Role words a question uses for a parameter ("damping" for zeta); first match present in the system wins.
_PARAMETER_ROLES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\bdamping\b|\bdamping ratio\b|\bfriction\b", re.I), ("zeta", "c", "b", "gamma", "mu")),
    (re.compile(r"\b(?:natural |angular )?frequency\b|\bstiffness\b|\bspring constant\b", re.I), ("omega", "k")),
    (re.compile(r"\bnonlinearity\b|\bnonlinear damping\b", re.I), ("mu",)),
    (re.compile(r"\bresistance\b|\bresistor\b", re.I), ("R",)),
    (re.compile(r"\bcapacitance\b|\bcapacitor\b", re.I), ("C",)),
    (re.compile(r"\binductance\b|\binductor\b", re.I), ("L",)),
    (re.compile(r"\b(?:input|supply|source) voltage\b", re.I), ("V_in",)),
    (re.compile(r"\bpendulum length\b|\blength\b", re.I), ("L",)),
    (re.compile(r"\bgravit\w*\b", re.I), ("g",)),
    (re.compile(r"\btransmission\b|\binfection rate\b|\bcontact rate\b", re.I), ("beta",)),
    (re.compile(r"\brecovery rate\b", re.I), ("gamma_r",)),
    (re.compile(r"\bprandtl\b", re.I), ("sigma",)),
    (re.compile(r"\brayleigh\b", re.I), ("rho",)),
    (re.compile(r"\bpredation\b|\bpredator\b", re.I), ("beta", "delta")),
    (re.compile(r"\bprey growth\b|\bgrowth rate\b", re.I), ("alpha",)),
)
# Dynamis presets by the words a question uses for them, longest first; a short all-caps name matches case-sensitively.
_PRESET_ALIASES: tuple[tuple[str, str], ...] = (
    ("damped harmonic oscillator", "damped_oscillator"), ("mass-spring-damper", "damped_oscillator"),
    ("spring-mass-damper", "damped_oscillator"), ("mass spring damper", "damped_oscillator"),
    ("damped oscillator", "damped_oscillator"), ("damped spring", "damped_oscillator"),
    ("simple harmonic oscillator", "harmonic_oscillator"), ("harmonic oscillator", "harmonic_oscillator"),
    ("mass-spring", "harmonic_oscillator"), ("spring-mass", "harmonic_oscillator"),
    ("lotka-volterra", "lotka_volterra"), ("lotka volterra", "lotka_volterra"), ("predator-prey", "lotka_volterra"),
    ("predator prey", "lotka_volterra"), ("van der pol", "van_der_pol"), ("vanderpol", "van_der_pol"),
    ("lorenz", "lorenz"), ("pendulum", "pendulum"), ("rlc circuit", "rlc_circuit"), ("lcr circuit", "rlc_circuit"),
    ("rc circuit", "rc_circuit"), ("sir model", "sir"), ("epidemic model", "sir"), ("RLC", "rlc_circuit"),
    ("SIR", "sir"), ("RC", "rc_circuit"),
)


# -----------------------------------------------------------------------------
# Data structures
# -----------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str
    statement: str
    mechanism: str
    kind: str | None
    parameter: str | None  # the system parameter perturbed
    factor: float | None
    readout: str | None  # a state variable of the system
    prediction: str  # increase | decrease
    metric: str = "final"  # which summary of the readout's trajectory (METRICS)
    source: str = "deterministic"  # llm | deterministic | evolved
    prediction_basis: str = ""
    parent: str | None = None
    evidence_keys: list[str] = field(default_factory=list)
    evidence_score: float = 0.0
    status: str = "untested"  # untested | tested | failed
    note: str = ""
    result: dict[str, Any] | None = None
    elo: float = ELO_START
    rank: int = 0

    def perturbation(self) -> tuple[str, str, float]:
        return (str(self.parameter or ""), str(self.kind or ""), round(float(self.factor or 0.0), 6))

    def to_artifact(self) -> dict[str, Any]:
        result = self.result or {}
        return {
            "id": self.id,
            "statement": self.statement,
            "mechanism": self.mechanism,
            "intervention": {"kind": self.kind, "parameter": self.parameter, "factor": self.factor},
            "readout": self.readout,
            "metric": self.metric,
            "prediction": self.prediction,
            "prediction_basis": self.prediction_basis,
            "result": {
                "baseline": result.get("baseline"),
                "perturbed": result.get("perturbed"),
                "relative_change": result.get("relative_change"),
                "log2_fold_change": result.get("log2_fold_change"),
                "monotonic": result.get("monotonic"),
                "supports": result.get("supports") if self.status == "tested" else None,
                "result_key": result.get("result_key"),
            },
            "status": self.status,
            "note": self.note,
            "source": self.source,
            "parent": self.parent,
            "elo": round(self.elo, 1),
            "rank": self.rank,
            "evidence_keys": list(self.evidence_keys)[:10],
        }


@dataclass
class DynamisSystem:
    """A dynamical system Dynamis can integrate: the ODE right-hand sides, initial state, parameters and time span."""

    name: str  # the Dynamis preset key
    label: str
    rhs: dict[str, str]
    initial_state: dict[str, float]
    parameters: dict[str, float]
    t_span: tuple[float, float]
    source: str = "preset"

    @property
    def biomodel_id(self) -> str:
        """The system's id in the artifact (the field kept its pre-Dynamis name)."""
        return self.name

    @property
    def states(self) -> list[str]:
        return list(self.rhs)

    @staticmethod
    def _resolve(name: Any, names: list[str]) -> str | None:
        n = str(name or "").strip()
        if not n:
            return None
        if n in names:
            return n
        lower = [x for x in names if x.lower() == n.lower()]
        return lower[0] if len(lower) == 1 else None

    def resolve_parameter(self, name: Any) -> str | None:
        return self._resolve(name, list(self.parameters))

    def resolve_state(self, name: Any) -> str | None:
        return self._resolve(name, self.states)

    def equations_text(self) -> str:
        return "; ".join(f"d{k}/dt = {v}" for k, v in self.rhs.items())


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _data(res: Any) -> dict[str, Any]:
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) and getattr(res, "success", False) else {}


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def simulation_block_reason(ctx: Any) -> str:
    """Why no simulation may run this turn ("" when it may)."""
    if getattr(ctx, "suppress_simulation", False):
        return "simulation was switched off at the researcher's request"
    constraints = getattr(ctx, "simulation_constraints", None)
    if constraints is not None and getattr(constraints, "simulation_forbidden", False):
        return "simulation is forbidden for this turn"
    allowed = getattr(ctx, "source_allowed", None)
    if callable(allowed) and not (allowed("dynamis") or allowed("vivarix")):
        return getattr(ctx, "source_restriction_reason", "") or "the turn's source restriction excludes simulation"
    return ""


def _mentions(text: str, name: str) -> int | None:
    """Position of a whole-name mention in text, or None (case-insensitive from 3 characters; 'A' never matches 'a')."""
    if not name:
        return None
    m = re.search(rf"(?<![\w\-]){re.escape(name)}(?![\w\-])", text, re.I if len(name) >= 3 else 0)
    return m.start() if m else None


def preset_for(ctx: Any, question: str) -> str | None:
    """The Dynamis preset the question is about: named in its words (whole words, longest alias first, so "damped
    harmonic oscillator" is not the undamped one and "desired" is not SIR), else the planner's system name."""
    from ..dynamis import ODE_PRESETS

    text = question or ""
    for alias, key in _PRESET_ALIASES:
        flags = 0 if alias.isupper() else re.I
        if key in ODE_PRESETS and re.search(rf"(?<![\w\-]){re.escape(alias)}(?![\w\-])", text, flags):
            return key
    plan = getattr(ctx, "simulation_plan", None)
    names = [getattr(plan, "system_name", None), getattr(ctx, "system_name", None)]
    names += [getattr(e, "label", None) for e in list(getattr(ctx, "systems", None) or [])]
    for name in names:
        key = re.sub(r"[\s\-]+", "_", str(name or "").strip().lower())
        if key in ODE_PRESETS:
            return key
    return None


def dynamis_system(ctx: Any, question: str | None = None) -> DynamisSystem | None:
    """The dynamical system this turn is about, as Dynamis inputs: the preset's equations with the simulation plan's
    duration and parameter values, and values the question gives ("zeta = 0.3"). None when no preset fits."""
    from ..dynamis import ODE_PRESETS

    text = question if question is not None else (getattr(ctx, "clean_query", None) or getattr(ctx, "raw_query", "") or "")
    key = preset_for(ctx, text)
    if key is None:
        return None
    preset = ODE_PRESETS[key]
    params = {str(k): float(v) for k, v in (preset.get("parameters") or {}).items()}
    plan = getattr(ctx, "simulation_plan", None)
    for name, value in dict(getattr(plan, "parameter_overrides", None) or {}).items():
        if name in params and _num(value) is not None:
            params[name] = float(value)
    for name in list(params):
        m = re.search(rf"(?<![\w\-]){re.escape(name)}\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
        if m:
            params[name] = float(m.group(1))
    t0, t1 = (float(x) for x in preset.get("t_span") or (0.0, 10.0))
    duration = _num(getattr(plan, "duration_seconds", None))
    if plan is not None and getattr(plan, "duration_explicit", False) and duration and duration > 0:
        t0, t1 = 0.0, float(duration)
    return DynamisSystem(
        name=key, label=key.replace("_", " "), rhs=dict(preset["rhs"]), initial_state=dict(preset["initial_state"]),
        parameters=params, t_span=(t0, t1),
    )


def model_in_play(ctx: Any, tool_results: dict[str, Any] | None = None) -> DynamisSystem | None:
    """The dynamical system this turn's hypotheses can be tested on (tool_results is accepted for the old signature)."""
    return dynamis_system(ctx)


def expected_score(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


def elo_update(ra: float, rb: float, score_a: float, k: float = ELO_K) -> tuple[float, float]:
    """Elo ratings after one match; score_a is 1 (A wins), 0.5 (draw) or 0 (B wins)."""
    ea = expected_score(ra, rb)
    return ra + k * (score_a - ea), rb + k * ((1.0 - score_a) - (1.0 - ea))


def log2_fold_change(baseline: float, perturbed: float) -> tuple[float, float]:
    """(log2FC, eps): zeros are guarded with eps = 1e-9 x max(|baseline|, |perturbed|) (or 1e-300 when both are 0)."""
    b, p = max(0.0, float(baseline)), max(0.0, float(perturbed))
    eps = max(EPS_RELATIVE * max(b, p), 1e-300)
    return math.log2((p + eps) / (b + eps)), eps


def factor_fits_kind(kind: str, factor: float) -> bool:
    """An increase kind raises the parameter (factor > 1), a decrease kind lowers it (< 1); variation is free."""
    if kind in INCREASE_KINDS:
        return factor > 1.0
    if kind in DECREASE_KINDS:
        return factor < 1.0
    return True


def metric_value(point: dict[str, Any], state: str, metric: str, initial: float | None) -> float | None:
    """One metric of a state variable from a parameter-scan point (final/peak/min/mean states)."""
    final = _num((point.get("final_state") or {}).get(state))
    peak = _num((point.get("peak_state") or {}).get(state))
    low = _num((point.get("min_state") or {}).get(state))
    if metric == "final":
        return final
    if metric == "peak":
        return peak
    if metric == "min":
        return low
    if metric == "mean":
        return _num((point.get("mean_state") or {}).get(state))
    if metric == "range":
        return None if peak is None or low is None else peak - low
    if metric == "overshoot":
        # The excursion past the settled value on the side away from the start: above it for a rising step
        # response, below it for a system released above it.
        if final is None or peak is None or low is None:
            return None
        rising = initial is None or initial <= final
        return max(0.0, peak - final) if rising else max(0.0, final - low)
    return None


def relative_change(baseline: float, perturbed: float, scale: float) -> float:
    """(perturbed - baseline) / |baseline|; 0 when both are negligible against the trajectory's scale."""
    floor = NEGLIGIBLE_SCALE * max(abs(scale), 1e-300)
    if abs(baseline) < floor and abs(perturbed) < floor:
        return 0.0
    return (perturbed - baseline) / max(abs(baseline), floor)


def _norm(value: Any) -> str:
    return re.sub(r"[\W_]+", " ", str(value or "").lower()).strip()


def _word_jaccard(a: str, b: str) -> float:
    wa, wb = set(_norm(a).split()), set(_norm(b).split())
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def is_near_duplicate(h: Hypothesis, kept: Hypothesis) -> bool:
    """True when `h` repeats `kept` as an untested hypothesis: the same intervention target, direction and readout,
    or nearly the same text. Tested hypotheses carry their own measured result (a dose-response child shares its
    parent's parameter), so they are never merged."""
    if h.status != "untested" or kept.status != "untested":
        return False
    target, kept_target = _norm(h.parameter), _norm(kept.parameter)
    if target and kept_target and target != kept_target:
        return False  # different parameters are different hypotheses, however alike the wording
    same_intervention = bool(target and h.kind) and h.kind == kept.kind and target == kept_target
    if same_intervention and h.prediction == kept.prediction and _norm(h.readout) == _norm(kept.readout):
        return True
    return _word_jaccard(h.statement, kept.statement) >= TEXT_DUPLICATE_JACCARD


def dedupe_ranked(ranked: list[Hypothesis], rejected: list[dict[str, str]]) -> list[Hypothesis]:
    """`ranked` (best first) without near-duplicates; each dropped one is noted in `rejected`."""
    out: list[Hypothesis] = []
    for h in ranked:
        dup = next((k for k in out if is_near_duplicate(h, k)), None)
        if dup is None:
            out.append(h)
        else:
            rejected.append({"hypothesis": h.statement[:200], "reason": f"near-duplicate of {dup.id}"})
    return out


def _question_metric(question: str) -> str:
    found = sorted((m.start(), metric) for metric, rx in _METRIC_CUES if (m := rx.search(question)))
    return found[0][1] if found else "final"


def _named_parameters(question: str, system: DynamisSystem) -> list[tuple[int, int, str, str]]:
    """(start, end, parameter, how it was named) for each system parameter the question names, first mention first."""
    found: dict[str, tuple[int, int, str]] = {}
    for name in system.parameters:
        pos = _mentions(question, name)
        if pos is not None and len(name) >= 2:  # one-letter names ("c", "g") only by role, not as words
            found[name] = (pos, pos + len(name), "named in the question")
    for rx, candidates in _PARAMETER_ROLES:
        m = rx.search(question)
        if not m:
            continue
        name = next((c for c in candidates if c in system.parameters), None)
        if name is not None and name not in found:
            found[name] = (m.start(), m.end(), f"the question's '{m.group(0)}'")
    return sorted((pos, end, name, why) for name, (pos, end, why) in found.items())


_PASSIVE_RE = re.compile(r"\s*(?:is|are|was|were|gets?|being)\s+(\w+)", re.I)


def _perturbation_kind(question: str, start: int, end: int) -> str:
    """How the question changes a parameter: the nearest raise/lower word just before its mention ("increasing
    damping"), else a passive form just after it ("zeta is doubled"); variation when it says neither."""
    before = question[max(0, start - 40): start]
    hits = [(m.end(), "elevation") for m in _RAISE_RE.finditer(before)]
    hits += [(m.end(), "reduction") for m in _LOWER_RE.finditer(before)]
    if hits:
        return max(hits)[1]
    m = _PASSIVE_RE.match(question, end)
    if m and _RAISE_RE.fullmatch(m.group(1)):
        return "elevation"
    if m and _LOWER_RE.fullmatch(m.group(1)):
        return "reduction"
    return "variation"


def _claimed_direction(question: str, end: int) -> str | None:
    """The effect direction the question claims after the parameter's mention ("damping reduces overshoot"), if
    it states one; a passive form describing the parameter itself ("zeta is increased") is not the effect."""
    m = _PASSIVE_RE.match(question, end)
    tail = question[m.end() if m else end:]
    down, up = _EFFECT_DOWN_RE.search(tail), _EFFECT_UP_RE.search(tail)
    hits = sorted((x.start(), d) for x, d in ((down, "decrease"), (up, "increase")) if x)
    return hits[0][1] if hits else None


# -----------------------------------------------------------------------------
# The phase
# -----------------------------------------------------------------------------

class HypothesisPhase(AgentPhase):
    key = PHASE
    stage = "augment"
    order = 40
    frameworks = None  # every agentic framework

    def applies(self, state: AgentState) -> bool:
        ctx = state.ctx
        option = state.options.get("enable_hypotheses")
        if option is False or getattr(ctx, "scope", "research") != "research":
            return False
        if "hypothesis" in (getattr(ctx, "excluded_modules", None) or set()):
            return False  # "No ... hypothesis generation ... is needed": the question's own words win
        if is_closed_computation(ctx):
            return False  # a calculation has an answer to check, not hypotheses to rank, even with the option on
        from ..agents.orchestration.presentation import facts_cover_question

        if facts_cover_question(getattr(state, "tool_results", None) or {}):
            # Solved exactly by code with every check passing: "explain why" asks for the mechanism of a known
            # solution, not for hypotheses to rank and simulate (about a minute of model calls).
            return False
        if option is True:
            return True
        # A named system alone ("simulate the Lorenz system") asks for a simulation, not for hypotheses.
        from .router import HYPOTHESIS_REQUEST_RE  # local: the router module registers its own phase on import

        question = state.clean_query or state.query or ""
        return bool(HYPOTHESIS_REQUEST_RE.search(question) or _INTENT_RE.search(question))

    async def run(self, state: AgentState) -> None:
        ctx = state.ctx
        question = state.clean_query or state.query
        # Opened as running so the activity step carries the phase's duration (it can take several model calls).
        await state.step("agent_hypothesis", "Forming and ranking hypotheses", "", status="running", agent="Discovery")
        system = dynamis_system(ctx, question)
        block = simulation_block_reason(ctx)
        notes: list[str] = []
        artifact: dict[str, Any] = {
            "target": getattr(ctx, "primary_display", None) or getattr(ctx, "primary_target", None),
            "model_id": system.name if system else None,
            "method": "elo-tournament",
            "elo": {"start": ELO_START, "k": ELO_K},
            "threshold_relative_change": REL_CHANGE_THRESHOLD,
            "experiments_run": 0,
            "simulation": "no_model" if system is None else ("blocked" if block else "allowed"),
        }
        if system is not None:
            artifact["system"] = {"name": system.name, "equations": system.rhs, "parameters": system.parameters,
                                  "t_span": list(system.t_span)}
        if system is not None and block:
            notes.append(f"No in-silico experiment was run: {block}.")
            state.scope_notes.append(f"Hypotheses were not tested in silico because {block}; they are labelled untested.")

        llm_meta: dict[str, Any] = {}
        hypotheses, rejected = await self._generate(state, question, system, llm_meta)
        artifact["generator"] = llm_meta.get("generator", "deterministic")
        if llm_meta.get("reflection"):
            artifact["reflection"] = llm_meta["reflection"]
        if llm_meta.get("research_plan"):
            artifact["research_plan"] = llm_meta["research_plan"]
        if not hypotheses:
            # A dynamical system is needed only for an in-silico test, never for a hypothesis or conjecture itself
            # (a conjecture about primes has no parameters to perturb), audit I36.
            artifact.update(hypotheses=[], rejected=rejected[:10], note=(
                "No hypothesis was proposed from the question and the evidence." if system is None else
                "No testable hypothesis could be formed from the question and the system's parameters."))
            state.artifacts["hypotheses"] = artifact
            await state.step("agent_hypothesis", "No hypotheses formed", artifact["note"], agent="Discovery")
            return

        self._score_evidence(state, hypotheses)
        experiments = 0
        registry = state.registry
        can_test = system is not None and not block and registry is not None and registry.get_entry(SCAN_TOOL) is not None
        if system is not None and not block and not can_test:
            notes.append("The Dynamis parameter-scan tool is not available, so no hypothesis was tested.")
        tested_set = set()
        if can_test:
            for h in hypotheses:
                if experiments >= MAX_EXPERIMENTS - 1:  # one run is kept for the evolved hypothesis
                    break
                if h.kind is None or h.parameter is None or h.perturbation() in tested_set:
                    continue
                tested_set.add(h.perturbation())
                experiments += await self._experiment(state, system, h)  # type: ignore[arg-type]
        for h in hypotheses:
            if h.status == "untested" and not h.note:
                h.note = "untested: " + (block if block else "no simulatable system was in play" if system is None else
                                         "not run (experiment budget or no validated perturbation)")

        judge_meta: dict[str, Any] = {"llm": 0, "deterministic": 0, "matches": []}
        await self._tournament(state, question, hypotheses, judge_meta)

        top = max(hypotheses, key=lambda h: (h.elo, self._det_score(h)))
        evolved = await self._evolve(state, question, top, hypotheses, system, tested_set)
        if evolved is not None:
            self._score_evidence(state, [evolved])
            if can_test and experiments < MAX_EXPERIMENTS and evolved.perturbation() not in tested_set:
                tested_set.add(evolved.perturbation())
                experiments += await self._experiment(state, system, evolved)  # type: ignore[arg-type]
            if evolved.status == "untested" and not evolved.note:
                evolved.note = "untested: " + (block or ("no simulatable system was in play" if system is None else "experiment budget used"))
            others = list(hypotheses)
            hypotheses.append(evolved)
            for other in others:
                await self._match(state, question, evolved, other, judge_meta)

        ranked = sorted(hypotheses, key=lambda h: (-h.elo, -self._det_score(h), h.id))
        ranked = dedupe_ranked(ranked, rejected)
        for i, h in enumerate(ranked, 1):
            h.rank = i

        if system is None:
            notes.append("No simulatable dynamical system was in play, so these hypotheses are ranked on the retrieved "
                         "evidence only; none was tested in silico.")
        judges = [k for k in ("llm", "deterministic") if judge_meta[k]]
        artifact.update(
            experiments_run=experiments,
            effect_rule="relative change of the metric, perturbed vs the unperturbed first scan point",
            judge="mixed" if len(judges) > 1 else (judges[0] if judges else "none"),
            hypotheses=[h.to_artifact() for h in ranked][:MAX_HYPOTHESES + 1],
            rejected=rejected[:10],
            matches=judge_meta["matches"][:20],
            note=" ".join(notes) or (
                f"{experiments} parameter scan(s) of {system.label if system else 'the system'} from the unperturbed "
                f"value to the perturbed one; support means the predicted direction with |relative change| >= "
                f"{REL_CHANGE_THRESHOLD}. In-silico results are model predictions, not experimental evidence."
            ),
        )
        state.artifacts["hypotheses"] = artifact
        self._publish(state, artifact, ranked, system)
        tested = sum(1 for h in ranked if h.status == "tested")
        supported = sum(1 for h in ranked if h.status == "tested" and (h.result or {}).get("supports"))
        await state.step(
            "agent_hypothesis",
            f"Ranked {len(ranked)} hypotheses" + (f"; {tested} tested in silico, {supported} supported" if tested else ""),
            "; ".join(f"#{h.rank} {_clip(h.statement, 90)}" for h in ranked[:3]),
            agent="Discovery",
        )

    # -- generation -----------------------------------------------------------------------------------------
    def _choose_readout(self, state: AgentState, question: str, system: DynamisSystem) -> str:
        for m in _READOUT_CUE_RE.finditer(question):
            r = system.resolve_state(m.group(1).strip(".,;:?)"))
            if r:
                return r
        named = sorted((pos, s) for s in system.states if len(s) >= 2 and (pos := _mentions(question, s)) is not None)
        if named:
            return named[0][1]
        # The state variable that moved most in the pipeline's own simulation of this system, else the first.
        summary = _data(state.tool_results.get("dynamis")).get("summary") or {}
        best, best_change = None, -1.0
        for s in system.states:
            row = summary.get(s) if isinstance(summary, dict) else None
            lo, hi = (_num(row.get("min")), _num(row.get("max"))) if isinstance(row, dict) else (None, None)
            if lo is not None and hi is not None and hi - lo > best_change:
                best, best_change = s, hi - lo
        return best or system.states[0]

    async def _generate(
        self, state: AgentState, question: str, system: DynamisSystem | None, meta: dict[str, Any]
    ) -> tuple[list[Hypothesis], list[dict[str, str]]]:
        rejected: list[dict[str, str]] = []
        hyps: list[Hypothesis] = []
        if state.llm.available:
            try:
                hyps = await self._llm_generate(state, question, system, rejected, meta)
            except (AgentLLMUnavailable, BudgetExhausted, ValueError) as exc:
                logger.info("Hypothesis generation model call failed: %s", exc)
                rejected.append({"hypothesis": "model generation", "reason": str(exc)[:160]})
        if hyps:
            meta["generator"] = "llm"
        elif system is not None:
            hyps = self._deterministic_hypotheses(state, question, system)
            meta["generator"] = "deterministic"
        for i, h in enumerate(hyps, 1):
            h.id = f"H{i}"
        return hyps[:MAX_HYPOTHESES], rejected

    def _deterministic_hypotheses(self, state: AgentState, question: str, system: DynamisSystem) -> list[Hypothesis]:
        """One hypothesis per system parameter the question names (at most 3): the perturbation direction from the
        question's wording near it, the predicted effect from the claim it makes, else a stated default prior."""
        readout = self._choose_readout(state, question, system)
        metric = _question_metric(question)
        out: list[Hypothesis] = []
        for start, end, name, why in _named_parameters(question, system)[: MAX_EXPERIMENTS - 1]:
            kind = _perturbation_kind(question, start, end)
            factor = DEFAULT_FACTORS[kind]
            claimed = _claimed_direction(question, end)
            if claimed is not None:
                prediction, basis = claimed, "the effect the question claims"
            else:
                prediction, basis = "increase", "default prior (the question states no direction); the scan decides"
            verb = {"elevation": "Raising", "reduction": "Lowering"}.get(kind, "Changing")
            out.append(Hypothesis(
                id="",
                statement=f"{verb} {name} (x{factor:g}) will {prediction} the {metric} of {readout} in the {system.label}.",
                mechanism=f"{name} is a parameter of the {system.label} ({system.equations_text()}); {why}.",
                kind=kind, parameter=name, factor=factor, readout=readout, prediction=prediction, metric=metric,
                source="deterministic", prediction_basis=basis,
            ))
        return out

    async def _llm_generate(
        self, state: AgentState, question: str, system: DynamisSystem | None,
        rejected: list[dict[str, str]], meta: dict[str, Any],
    ) -> list[Hypothesis]:
        system_prompt = (
            "[phase:hypothesis_generate] You are the Generation and Reflection agent of an AI co-scientist. Propose "
            "mechanistic hypotheses that a simulation of the engineering or physical ODE system can test. "
            + SPOTLIGHT_RULE
            + " Reply with JSON only: {\"reflection\": str, \"research_plan\": str (at most 5 sentences), "
            "\"hypotheses\": [{\"statement\", \"mechanism\", \"intervention\": {\"kind\": \"reduction|elevation|variation\", "
            "\"parameter\": <exact system parameter name>, \"factor\": number}, \"readout\": <exact state variable name>, "
            f"\"metric\": \"{'|'.join(METRICS)}\", \"prediction\": \"increase|decrease\"}}]}} with at most 4 hypotheses. "
            "Reduction lowers the parameter (factor < 1, e.g. 0.5), elevation raises it (factor > 1, e.g. 2), "
            "variation changes it either way. Use only names from the system; do not repeat a perturbation from the "
            "exclusion list. " + GROUNDED_STATEMENT_RULE
        )
        lines = [f"Research question: {neutralise(question)[:1200]}"]
        if system is not None:
            lines.append(f"System: {system.label}")
            lines.append(f"Equations: {system.equations_text()}")
            lines.append("State variables: " + ", ".join(system.states))
            lines.append("Parameters: " + ", ".join(f"{k}={v:g}" for k, v in system.parameters.items()))
            lines.append(f"Time span: {system.t_span[0]:g} to {system.t_span[1]:g}")
            lines.append(
                "Measurement: the metric of the readout's trajectory, perturbed vs unperturbed (a parameter scan from "
                f"the current value to the perturbed one); support = predicted direction with |relative change| >= {REL_CHANGE_THRESHOLD}."
            )
        else:
            lines.append("No simulatable system is available: hypotheses will be ranked on the evidence only and stay untested.")
        lines.append("Exclusion list (already tested): none")
        lines.append("Evidence gathered so far:\n" + self._evidence_digest(state))
        reply = await state.llm.json(system_prompt, "\n".join(lines), phase=PHASE)
        if not isinstance(reply, dict):
            raise ValueError("hypothesis generation reply was not a JSON object")
        meta["reflection"] = neutralise(str(reply.get("reflection") or ""))[:800]
        meta["research_plan"] = neutralise(str(reply.get("research_plan") or ""))[:800]
        out: list[Hypothesis] = []
        seen = set()
        for raw in (reply.get("hypotheses") or [])[:MAX_HYPOTHESES]:
            h, reason = self._validate(raw, system, source="llm")
            if h is None:
                rejected.append({"hypothesis": str((raw or {}).get("statement") if isinstance(raw, dict) else raw)[:200], "reason": reason})
                continue
            if h.perturbation() in seen and h.kind:
                rejected.append({"hypothesis": h.statement[:200], "reason": "repeats a perturbation already proposed"})
                continue
            seen.add(h.perturbation())
            out.append(h)
        return out

    def _validate(self, raw: Any, system: DynamisSystem | None, source: str) -> tuple[Hypothesis | None, str]:
        """Reflection step: a hypothesis is kept only if its parameter and readout exist in the system."""
        if not isinstance(raw, dict):
            return None, "not an object"
        statement = neutralise(str(raw.get("statement") or "")).strip()[:400]
        prediction = str(raw.get("prediction") or "").strip().lower()
        if not statement or prediction not in ("increase", "decrease"):
            return None, "missing statement or prediction (increase|decrease)"
        iv = raw.get("intervention") if isinstance(raw.get("intervention"), dict) else {}
        kind = str(iv.get("kind") or "").strip().lower() or None
        if kind is not None and kind not in KINDS:
            return None, f"unknown intervention kind '{kind}'"
        param, readout = iv.get("parameter"), raw.get("readout")
        factor = _num(iv.get("factor"))
        metric = str(raw.get("metric") or "final").strip().lower()
        if metric not in METRICS:
            return None, f"unknown metric '{metric[:30]}' (use one of {', '.join(METRICS)})"
        mechanism = neutralise(str(raw.get("mechanism") or "")).strip()[:400]
        if system is None:
            return Hypothesis(id="", statement=statement, mechanism=mechanism, kind=kind, parameter=str(param)[:120] if param else None,
                              factor=factor, readout=str(readout)[:120] if readout else None, prediction=prediction,
                              metric=metric, source=source, prediction_basis="model proposal"), ""
        if kind is None:
            return None, "no intervention kind"
        p_name = system.resolve_parameter(param)
        if p_name is None:
            return None, f"'{str(param)[:60]}' is not a parameter of the {system.label} ({', '.join(system.parameters)})"
        r_name = system.resolve_state(readout)
        if r_name is None:
            return None, f"readout '{str(readout)[:60]}' is not a state variable of the {system.label}"
        if factor is None or factor <= 0 or abs(factor - 1.0) < 1e-9:
            factor = DEFAULT_FACTORS[kind]
        factor = min(1e3, max(1e-3, factor))
        if not factor_fits_kind(kind, factor):
            factor = DEFAULT_FACTORS[kind]
        return Hypothesis(id="", statement=statement, mechanism=mechanism, kind=kind, parameter=p_name, factor=factor,
                          readout=r_name, prediction=prediction, metric=metric, source=source,
                          prediction_basis="model proposal"), ""

    @staticmethod
    def _evidence_digest(state: AgentState) -> str:
        from .specialists import evidence_digest

        try:
            digest, _keys = evidence_digest(state, max_items=8, chars=240)
        except Exception as exc:  # noqa: BLE001 - the digest is context, not a requirement
            logger.debug("Hypothesis evidence digest failed: %s", exc)
            return spotlight("none", "pipeline_results", 100)
        return digest[:3000]

    def _score_evidence(self, state: AgentState, hyps: list[Hypothesis]) -> None:
        """Literature and web results that name a hypothesis's parameter count as its evidence."""
        texts: dict[str, str] = {}
        for key, res in list(state.tool_results.items()):
            tool = str(getattr(res, "tool_name", "") or "")
            if not any(t in f"{key} {tool}".lower() for t in ("archivon", "lithoscribe", "literature", "websurfer")):
                continue
            data = _data(res)
            if data:
                texts[key] = json.dumps(data, default=str).lower()
        for h in hyps:
            name = str(h.parameter or "").lower()
            if len(name) < 3:
                continue
            hits = [k for k, t in texts.items() if re.search(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", t)]
            for k in hits:
                if k not in h.evidence_keys:
                    h.evidence_keys.append(k)
            h.evidence_score = max(h.evidence_score, min(1.0, len(hits) / 3.0))

    # -- experiments ----------------------------------------------------------------------------------------
    async def _experiment(self, state: AgentState, system: DynamisSystem, h: Hypothesis) -> int:
        """Scan the parameter from its value to the perturbed value; returns 1 when a scan was attempted."""
        base_value = system.parameters.get(str(h.parameter))
        if base_value is None or not math.isfinite(base_value) or base_value == 0:
            h.note = f"untested: the system value of {h.parameter} is {base_value!r}, so a fold perturbation is undefined"
            return 0
        if h.readout not in system.rhs:
            h.note = f"untested: {h.readout} is not a state variable of the {system.label}"
            return 0
        value = float(base_value) * float(h.factor or 1.0)
        res = await state.call_tool(
            SCAN_TOOL, phase=PHASE, store=False,
            purpose=f"in-silico test of {h.id}: {h.kind} of {h.parameter} (x{h.factor:g}) in the {system.label}",
            rhs=dict(system.rhs), initial_state=dict(system.initial_state), parameter=str(h.parameter),
            scan_range=(float(base_value), value), num_points=SCAN_POINTS, t_span=tuple(system.t_span),
            base_parameters=dict(system.parameters),
        )
        key = state.add_result(state.next_key(PHASE, SCAN_TOOL), res, phase=PHASE, purpose=f"hypothesis {h.id} parameter scan", render=False)
        points = [p for p in _data(res).get("scan_results") or [] if isinstance(p, dict) and _num(p.get("parameter_value")) is not None]
        if len(points) < 2:
            h.status = "failed"
            h.note = "untested: the parameter scan failed (" + str(getattr(res, "error", "") or "no scan points")[:160] + ")"
            h.result = {"result_key": key}
            return 1
        ordered = sorted(points, key=lambda p: abs(float(p["parameter_value"]) - base_value))  # baseline first
        readout = str(h.readout)
        initial = _num(system.initial_state.get(readout))
        series = [metric_value(p, readout, h.metric, initial) for p in ordered]
        base, perturbed = series[0], series[-1]
        if base is None or perturbed is None:
            h.status = "failed"
            h.note = f"untested: the scan has no {h.metric} of {h.readout}"
            h.result = {"result_key": key}
            return 1
        extremes = [_num((p.get(f) or {}).get(readout)) for p in ordered for f in ("peak_state", "min_state")]
        scale = max([abs(x) for x in extremes if x is not None] or [1.0])
        rel = relative_change(base, perturbed, scale)
        steps = [b - a for a, b in zip(series, series[1:], strict=False) if a is not None and b is not None]
        monotonic = bool(steps) and (all(s >= 0 for s in steps) or all(s <= 0 for s in steps))
        direction = "increase" if rel > 0 else "decrease"
        supports = bool(abs(rel) >= REL_CHANGE_THRESHOLD and direction == h.prediction)
        h.status = "tested"
        h.result = {
            "baseline": float(f"{base:.6g}"),
            "perturbed": float(f"{perturbed:.6g}"),
            "relative_change": round(rel, 4),
            "log2_fold_change": round(log2_fold_change(base, perturbed)[0], 4) if base > 0 and perturbed > 0 else None,
            "monotonic": monotonic,
            "supports": supports,
            "result_key": key,
            "parameter_values": [float(f"{float(p['parameter_value']):.6g}") for p in ordered],
            "metric_values": [None if v is None else float(f"{v:.6g}") for v in series],
            "override": {str(h.parameter): float(f"{value:.6g}")},
        }
        h.evidence_keys = [key] + [k for k in h.evidence_keys if k != key]
        if not supports:
            h.note = (
                f"refuted in silico: |relative change| {abs(rel):.3f} is below {REL_CHANGE_THRESHOLD}" if abs(rel) < REL_CHANGE_THRESHOLD
                else f"refuted in silico: the {h.metric} of {h.readout} moved in the opposite direction ({direction})"
            )
        else:
            h.note = "supported in silico (model prediction, not experimental evidence)"
        return 1

    # -- ranking --------------------------------------------------------------------------------------------
    @staticmethod
    def _det_score(h: Hypothesis) -> float:
        effect = min(abs(_num((h.result or {}).get("relative_change")) or 0.0), 1.0)
        if h.status == "tested":
            if (h.result or {}).get("supports"):
                return 2.0 + effect + 0.05 * h.evidence_score
            return 0.5 * effect
        return 1.0 + 0.5 * min(1.0, h.evidence_score)

    async def _judge(self, state: AgentState, question: str, a: Hypothesis, b: Hypothesis, meta: dict[str, Any]) -> tuple[float, str, str]:
        """(score for a, judge, reason): pairwise model judge when available, else effect size and evidence."""
        if state.llm.available and meta["llm"] < MAX_JUDGE_CALLS:
            system = (
                "[phase:hypothesis_judge] You are the Ranking agent of an AI co-scientist running an Elo tournament. "
                "Compare hypotheses A and B for the research question: prefer the one better supported by its in-silico "
                "result and the evidence, then mechanistic plausibility and testability. An untested hypothesis has no "
                "result; never treat it as confirmed. "
                + SPOTLIGHT_RULE
                + " Reply with JSON only: {\"winner\": \"A\"|\"B\", \"reason\": str}."
            )
            user = "\n".join(
                [
                    f"Research question: {neutralise(question)[:800]}",
                    "A: " + json.dumps(self._judge_view(a), default=str),
                    "B: " + json.dumps(self._judge_view(b), default=str),
                ]
            )
            try:
                reply = await state.llm.json(system, user, phase=PHASE, retries=0)
                winner = str((reply or {}).get("winner") or "").strip().upper() if isinstance(reply, dict) else ""
                if winner in ("A", "B"):
                    meta["llm"] += 1
                    return (1.0 if winner == "A" else 0.0), "llm", neutralise(str(reply.get("reason") or ""))[:200]
            except (AgentLLMUnavailable, BudgetExhausted, ValueError) as exc:
                logger.info("Hypothesis judge call failed: %s", exc)
        meta["deterministic"] += 1
        sa, sb = self._det_score(a), self._det_score(b)
        if abs(sa - sb) < 1e-9:
            return 0.5, "deterministic", "equal effect size and evidence"
        return (1.0 if sa > sb else 0.0), "deterministic", "larger supported effect / more evidence"

    @staticmethod
    def _judge_view(h: Hypothesis) -> dict[str, Any]:
        view = h.to_artifact()
        return {k: view[k] for k in ("statement", "mechanism", "intervention", "readout", "metric", "prediction",
                                      "status", "result", "note")}

    async def _match(self, state: AgentState, question: str, a: Hypothesis, b: Hypothesis, meta: dict[str, Any]) -> None:
        score, judge, reason = await self._judge(state, question, a, b, meta)
        a.elo, b.elo = elo_update(a.elo, b.elo, score)
        meta["matches"].append(
            {"a": a.id, "b": b.id, "winner": a.id if score == 1.0 else b.id if score == 0.0 else "draw", "judge": judge, "reason": reason}
        )

    async def _tournament(self, state: AgentState, question: str, hyps: list[Hypothesis], meta: dict[str, Any]) -> None:
        for i in range(len(hyps)):
            for j in range(i + 1, len(hyps)):
                await self._match(state, question, hyps[i], hyps[j], meta)

    # -- evolution ------------------------------------------------------------------------------------------
    async def _evolve(
        self, state: AgentState, question: str, top: Hypothesis, hyps: list[Hypothesis], system: DynamisSystem | None,
        tested: set,
    ) -> Hypothesis | None:
        if top.kind is None or top.parameter is None:
            return None
        excluded = {h.perturbation() for h in hyps} | set(tested)
        child: Hypothesis | None = None
        if state.llm.available:
            prompt = (
                "[phase:hypothesis_evolve] You are the Evolution agent of an AI co-scientist. Refine the top-ranked "
                "hypothesis once in light of its in-silico result. Reply with JSON only: {\"hypothesis\": {\"statement\", "
                "\"mechanism\", \"intervention\": {\"kind\", \"parameter\", \"factor\"}, \"readout\", \"metric\", "
                "\"prediction\"}}. Do not repeat a perturbation from the exclusion list. "
                + GROUNDED_STATEMENT_RULE
            )
            user = "\n".join(
                [
                    f"Research question: {neutralise(question)[:800]}",
                    "Top hypothesis: " + json.dumps(self._judge_view(top), default=str),
                    "Exclusion list: " + json.dumps(sorted(list(p) for p in excluded)),
                ]
            )
            try:
                reply = await state.llm.json(prompt, user, phase=PHASE, retries=0)
                raw = reply.get("hypothesis") if isinstance(reply, dict) else None
                child, _reason = self._validate(raw, system, source="evolved")
            except (AgentLLMUnavailable, BudgetExhausted, ValueError) as exc:
                logger.info("Hypothesis evolution call failed: %s", exc)
        if child is None or child.perturbation() in excluded:
            child = self._deterministic_evolution(top)
        if child is None or child.perturbation() in excluded:
            return None
        child.id = f"H{len(hyps) + 1}"
        child.parent = top.id
        child.source = "evolved"
        return child

    @staticmethod
    def _deterministic_evolution(top: Hypothesis) -> Hypothesis | None:
        result = top.result or {}
        rel = _num(result.get("relative_change"))
        factor = float(top.factor or DEFAULT_FACTORS.get(str(top.kind), 0.5))
        kind, prediction = str(top.kind), top.prediction
        if top.status == "tested" and result.get("supports"):
            factor, why = math.sqrt(factor), "dose-response check: does a partial perturbation still move the readout?"
        elif top.status == "tested" and rel is not None and abs(rel) >= REL_CHANGE_THRESHOLD:
            kind = "elevation" if kind in DECREASE_KINDS else "reduction" if kind in INCREASE_KINDS else kind
            factor = DEFAULT_FACTORS[kind] if kind in DEFAULT_FACTORS else 1.0 / factor
            prediction = "decrease" if rel > 0 else "increase"
            why = "revised direction: the opposite perturbation should reverse the measured effect"
        elif top.status == "tested":
            factor = min(1e3, max(1e-3, factor * factor))
            why = "stronger perturbation: is the readout insensitive or was the perturbation too weak?"
        else:
            return None
        return Hypothesis(
            id="",
            statement=f"{kind.capitalize()} of {top.parameter} (x{factor:.3g}) will {prediction} the {top.metric} of {top.readout}.",
            mechanism=f"Refinement of {top.id}: {why}",
            kind=kind, parameter=top.parameter, factor=round(factor, 6), readout=top.readout, prediction=prediction,
            metric=top.metric, source="evolved", prediction_basis=why,
        )

    # -- output ---------------------------------------------------------------------------------------------
    def _publish(self, state: AgentState, artifact: dict[str, Any], ranked: list[Hypothesis], system: DynamisSystem | None) -> None:
        from ..tools.registry import ToolResult

        summary = {k: v for k, v in artifact.items() if k not in ("matches", "rejected")}
        state.add_result(
            "agent.hypothesis.summary",
            ToolResult(success=True, tool_name="hypothesis_experiments", data=summary, metadata={"adapter": "AGENT"}),
            phase=PHASE,
            purpose="ranked hypotheses and in-silico experiment results",
            render=False,
        )

        def attr(v: Any) -> str:
            return escape("" if v is None else str(v), quote=True)

        lines = [
            f'<hypothesis_experiments model="{attr(system.label if system else "none")}" method="elo-tournament" '
            f'threshold_relative_change="{REL_CHANGE_THRESHOLD}" effect_rule="(perturbed - baseline) / |baseline| of the metric" '
            f'experiments_run="{artifact.get("experiments_run", 0)}" result_key="agent.hypothesis.summary" '
            f'note="in-silico results are model predictions, not experimental evidence; untested hypotheses have no result">'
        ]
        for h in ranked:
            r = h.result or {}
            fields = {
                "id": h.id, "rank": h.rank, "elo": round(h.elo, 1), "status": h.status,
                "intervention": h.kind, "parameter": h.parameter, "factor": h.factor, "readout": h.readout,
                "metric": h.metric, "prediction": h.prediction,
            }
            if h.status == "tested":
                fields.update(
                    baseline=r.get("baseline"), perturbed=r.get("perturbed"), relative_change=r.get("relative_change"),
                    monotonic="true" if r.get("monotonic") else "false",
                    supports="true" if r.get("supports") else "false", result_key=r.get("result_key"),
                )
            rendered = " ".join(f'{k}="{attr(v)}"' for k, v in fields.items() if v is not None)
            body = escape(h.statement, quote=False) + (f" [{escape(h.note, quote=False)}]" if h.note else "")
            lines.append(f"<hypothesis {rendered}>{body}</hypothesis>")
        lines.append("</hypothesis_experiments>")
        state.evidence_sections.append("\n".join(lines))
        state.brief_notes.append(
            "Hypotheses: present the ranked hypotheses from <hypothesis_experiments>. For a tested one, give the "
            "baseline and perturbed value of its metric and the relative change as listed and call it an in-silico model "
            "prediction; say 'untested' for any hypothesis without a result."
        )


register_phase(HypothesisPhase())
