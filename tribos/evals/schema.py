"""
Evaluation cases and results.

A case is one question plus what a correct run must show, at up to three levels:
- plan: how the question is read and routed (scope, question type, entities, sources run or skipped);
- retrieval: which papers the literature search must find (gold arXiv IDs, DOIs, or PMIDs; any one is a hit);
- answer: what the final answer must and must not contain, numeric/symbolic accuracy, whether it must abstain,
  and a label for benchmark questions (yes/no/maybe, multiple choice, factoid, list, numeric, symbolic).
Execution contracts are checked separately from wording: the simulation plan the question was parsed into
(plan level), and the operation that actually ran, its arguments, the task status and the evidence ids (answer
level). Selecting an agent is not proof that the requested operation ran.
Every expectation is optional, so one case can be scored at any level it defines expectations for.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Level = Literal["plan", "retrieval", "answer"]
LEVELS: tuple = ("plan", "retrieval", "answer")


class PlanExpect(BaseModel):
    scope: Literal["research", "conversational", "unclear"] | None = None
    question_type: str | None = None
    primary_target: str | None = None  # "" means: no primary target
    entities: list[str] = Field(default_factory=list)  # labels or mentions that must be recognized
    not_entities: list[str] = Field(default_factory=list)  # must NOT be recognized
    run: list[str] = Field(default_factory=list)  # sources that must run ("archivon", "dynamis", "axiom", "physis", "calcula")
    skip: list[str] = Field(default_factory=list)  # sources that must not run ("dynamis")
    offline: bool = False  # the expectations hold without the live resolver or planner model (CI-safe)
    simulation: SimulationExpect | None = None  # the parsed SimulationPlan (checked offline: it is deterministic)


class SimulationExpect(BaseModel):
    """What query_context.SimulationPlan / SimulationConstraints must say for the question."""

    action: str | None = None  # time_course|steady_state|parameter_scan; "" means no simulation plan at all
    forbidden: bool | None = None  # simulation_constraints.simulation_forbidden
    duration_seconds: float | None = None
    scan_parameter: str | None = None
    scan_start: float | None = None
    scan_end: float | None = None
    scan_points: int | None = None
    overrides: list[str] = Field(default_factory=list)  # parameter names that must be kept in parameter_overrides
    validation_error: str | None = None  # a code that must be in validation_errors (e.g. DURATION_OUT_OF_RANGE)
    valid: bool | None = None  # True: no validation errors


class RetrievalExpect(BaseModel):
    gold_pmids: list[str] = Field(default_factory=list)  # any one retrieved counts as a hit
    gold_dois: list[str] = Field(default_factory=list)
    gold_arxiv_ids: list[str] = Field(default_factory=list)
    # Regexes on retrieved titles that also count as a hit: open retrieval has many right answers, so a case can
    # accept any paper of the right kind, not one identifier only.
    gold_title_patterns: list[str] = Field(default_factory=list)
    k: int = 8
    required: bool = True  # False: report recall, but a miss does not fail the case


class Fact(BaseModel):
    """A golden fact the answer must state (SAFE-style fact recall). Exactly one matcher is set:

    - pattern: a regex (case-insensitive), e.g. "A000045";
    - value (+ tolerance, optional ci [low, high]): a number, matched however it is written ("0.30", "0.3",
      "0·30", a unicode minus); with ci, an interval within `window` characters after the number must match too;
    - date: an ISO date, matched as 2014-12-19, December 19, 2014, Dec. 19, 2014, 19 December 2014 or 12/19/2014;
    - any_of: alternative facts, any one of which counts.
    context: a regex that must occur within `window` characters of the match.
    """

    id: str
    pattern: str | None = None
    value: float | None = None
    tolerance: float = 0.0
    ci: list[float] | None = None
    ci_tolerance: float | None = None  # default: tolerance
    date: str | None = None
    any_of: list[Fact] = Field(default_factory=list)
    context: str | None = None
    window: int = 200
    required: bool = True  # an optional fact is reported but does not count toward fact_recall
    note: str | None = None

    @model_validator(mode="after")
    def _one_matcher(self) -> Fact:
        set_ = [n for n in ("pattern", "value", "date") if getattr(self, n) is not None] + (["any_of"] if self.any_of else [])
        if len(set_) != 1:
            raise ValueError(f"fact {self.id}: set exactly one of pattern, value, date, any_of (got {set_ or 'none'})")
        if self.ci is not None and (self.value is None or len(self.ci) != 2):
            raise ValueError(f"fact {self.id}: ci needs a value and two bounds")
        if self.date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.date):
            raise ValueError(f"fact {self.id}: date must be YYYY-MM-DD")
        return self

    def regexes(self) -> list[str]:
        out = [p for p in (self.pattern, self.context) if p]
        for alt in self.any_of:
            out += alt.regexes()
        return out


class AnswerExpect(BaseModel):
    must_mention: list[str] = Field(default_factory=list)  # regexes, all must match (case-insensitive)
    must_not_mention: list[str] = Field(default_factory=list)  # regexes, none may match
    required_terms: list[str] = Field(default_factory=list)  # terms or synonyms that must be mentioned
    abstain: bool | None = None  # True: must say the evidence is missing; False: must not refuse
    agents_include: list[str] = Field(default_factory=list)  # e.g. "Dynamis", "Axiom", "Archivon", "Physis", "Calcula"
    agents_exclude: list[str] = Field(default_factory=list)
    framework: str | None = None  # the framework that must have been USED, e.g. "conversational-direct"
    verified: bool | None = True  # the verifier must pass (None: not checked)
    cite_gold: bool = False  # a gold identifier must be cited in the answer
    min_citations: int = 0
    # Deterministic mathematical / physical / engineering answer checks:
    numeric_answer: float | None = None  # expected numerical value (from \boxed{...} or final answer)
    numeric_tolerance: float = 1e-3  # absolute tolerance for numeric_answer
    numeric_rel_tol: float = 1e-2  # relative tolerance for numeric_answer
    # The question asks for the value in a power-of-ten unit ("in 10^6"); the same quantity written out in base units
    # (expected x numeric_scale, e.g. 4.8e6 for 4.76 in 10^6) is equally right.
    numeric_scale: float | None = None
    symbolic_answer: str | None = None  # expected symbolic/LaTeX expression (checked via SymPy simplify(a-b)==0 + spot checks)
    # Benchmark labels: graded from the free-text answer.
    label: str | None = None  # yes|no|maybe, or the correct option text
    options: list[str] = Field(default_factory=list)  # multiple choice: every option, correct one included
    exact: list[list[str]] = Field(default_factory=list)  # factoid/list: synonym groups that count as an answer
    answer_type: Literal["yesno", "choice", "factoid", "list", "summary", "numeric", "symbolic"] | None = None
    max_latency_s: float | None = None
    # Budgets: the run's estimated tokens, model calls and tool calls (agent budget, or the run manifest's tool calls).
    max_tokens: int | None = None
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None  # 0: no tool may run (greetings)
    execution: ExecutionExpect | None = None
    # Golden facts (fact_recall = required facts found / required facts). With min_fact_recall, one required check
    # "answer.fact_recall" decides and each fact is informational; otherwise each fact is a check of its own.
    facts: list[Fact] = Field(default_factory=list)
    min_fact_recall: float | None = None
    min_faithfulness: float | None = None  # verifier: supported / (supported + unsupported + contradicted)
    # Hard gates run on every answer (answer.citations_in_evidence, answer.no_internal_leak, answer.no_crash);
    # list a gate here to switch it off for this case.
    skip_gates: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_facts(cls, data: Any) -> Any:
        if isinstance(data, dict) and "facts" in data:
            raw = data["facts"]
            if isinstance(raw, list):
                coerced = []
                for i, f in enumerate(raw):
                    if isinstance(f, list):
                        alts = [Fact(id=f"alt_{j}", pattern=re.escape(str(p))) for j, p in enumerate(f)]
                        coerced.append(Fact(id=f"fact_{i}", any_of=alts))
                    else:
                        coerced.append(f)
                data["facts"] = coerced
        return data


class ExecutionExpect(BaseModel):
    """The run's execution contract, read from the result's task_status and the run manifest's tool calls."""

    task_status: str | None = None  # completed|partial|needs_input|failed|cancelled
    requested_operation: str | None = None
    executed_operation: str | None = None  # "" means nothing may have been executed
    request_match: bool | None = None
    tools_called: list[str] = Field(default_factory=list)  # tool names that must have been called
    tools_not_succeeded: list[str] = Field(default_factory=list)  # no successful call may exist (no substituted result)
    error_types: list[str] = Field(default_factory=list)  # typed errors that must be reported (tool call or task reason)
    scan_points: int | None = None  # dynamis_parameter_scan num_steps
    scan_bounds: list[float] = Field(default_factory=list)  # [start, end]
    scan_duration_s: float | None = None  # per point
    overrides_forwarded: list[str] = Field(default_factory=list)  # names every simulation call must receive
    evidence_ids: list[str] = Field(default_factory=list)  # ids that must be in the evidence (canonical ids, citations)
    prohibited_evidence_ids: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)  # execution_artifacts keys that must exist
    no_artifacts: list[str] = Field(default_factory=list)  # keys that must not exist


class EvalCase(BaseModel):
    id: str
    suite: str
    query: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    setup: list[str] = Field(default_factory=list)  # earlier turns in the same thread (memory/follow-up cases)
    enable_web_search: bool = True
    # How the answer level runs the question (passed to execute_inquiry, or to POST /api/chat with --via).
    framework: str | None = None  # requested orchestration framework (e.g. "multi-agent-supervisor"); --framework overrides
    agent_options: dict[str, Any] = Field(default_factory=dict)  # e.g. {"budget": {"max_llm_calls": 30}}
    dataset_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    timeout_s: float | None = None  # per-case timeout (slow agentic frameworks); default: --timeout
    plan: PlanExpect | None = None
    retrieval: RetrievalExpect | None = None
    answer: AnswerExpect | None = None
    reference: str | None = None  # an expert answer for the judge
    source: str = "curated"
    notes: str | None = None

    @model_validator(mode="after")
    def _patterns_compile(self) -> EvalCase:
        """Every regex must compile and hold no control characters (a lost backslash turns \\b into a backspace)."""
        patterns = [*(self.answer.must_mention if self.answer else []), *(self.answer.must_not_mention if self.answer else []),
                    *(self.retrieval.gold_title_patterns if self.retrieval else []),
                    *(p for f in (self.answer.facts if self.answer else []) for p in f.regexes())]
        for p in patterns:
            if any(ord(ch) < 32 for ch in p):
                raise ValueError(f"{self.id}: pattern {p!r} contains a control character (check backslash escaping)")
            try:
                re.compile(p)
            except re.error as exc:
                raise ValueError(f"{self.id}: invalid regex {p!r}: {exc}") from exc
        return self

    def levels(self) -> list[str]:
        return [lvl for lvl in LEVELS if getattr(self, lvl) is not None]


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    required: bool = True  # an optional check is reported but never fails the case


class CaseResult(BaseModel):
    case_id: str
    suite: str
    category: str
    level: str
    query: str
    passed: bool = False
    checks: list[Check] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    latency_s: float | None = None
    error: str | None = None
    skipped: str | None = None  # why the case has nothing to score at this level
    observed: dict[str, Any] = Field(default_factory=dict)  # what the run produced (plan, pmids, answer, ...)

    def finalize(self) -> CaseResult:
        self.passed = self.error is None and self.skipped is None and all(c.passed for c in self.checks if c.required)
        return self


PlanExpect.model_rebuild()
Fact.model_rebuild()
AnswerExpect.model_rebuild()

__all__ = [
    "AnswerExpect", "CaseResult", "Check", "EvalCase", "ExecutionExpect", "Fact", "LEVELS", "Level", "PlanExpect", "RetrievalExpect",
    "SimulationExpect",
]
