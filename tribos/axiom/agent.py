"""
Verified mathematics agent: a bounded ReAct controller over the Axiom tools.

    parse problem -> propose typed action -> validate schema -> execute -> observe -> classify failure
          ^                                                                               |
          |       repair the failed step (trusted prefix kept) / switch strategy / escalate to the model
          +------------------------------------------------- independent verifier (verifier.py) -> stop

Built from the patterns in math_agent_research_recommendations.md:

- ReAct: every decision is conditioned on real observations; the controller owns steps, timeouts and stop rules.
- ToRA: each run is recorded as an interleaved decision / tool_call / observation / verification trajectory with
  per-step labels (written as JSONL when TRIBOS_MATH_TRAJECTORY_DIR is set) - SFT and evaluation data.
- THOR: failures are repaired locally (at most max_repairs per strategy, the paper caps self-correction at 4);
  verified facts survive a failed step; infrastructure failures are never charged to the policy.
- Toolformer: routing starts as explicit, logged rules (RulePolicy); the model policy is used only when the rules
  have no checked answer, so routing data accumulates for learning later.
- RAP: search is an escalation path. Strategies are tried in order and candidates are ranked by verification
  level, never by model confidence.

Execution success, semantic alignment and mathematical correctness are separate labels (StepLabels), and the final
status says exactly how far the answer was checked: verified | partially_verified | unverified | failed.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

import sympy as sp

from pydantic import BaseModel, Field, ValidationError

from . import analysis as A
from . import discrete as D
from . import engine as E
from .definitions import axiom_structured
from .problem import ProblemSpec, parse_problem
from .schemas import (
    AxiomCalculusInput,
    AxiomDsolveInput,
    AxiomInequalityInput,
    AxiomLinalgInput,
    AxiomNintegrateInput,
    AxiomNsolveInput,
    AxiomNumberTheoryInput,
    AxiomOptimizeInput,
    AxiomProbabilityInput,
    AxiomRecurrenceInput,
    AxiomSimplifyInput,
    AxiomSolveInput,
    AxiomStructuredInput,
    AxiomTangentInput,
    AxiomTransformInput,
    AxiomVectorCalculusInput,
    AxiomVerifyIdentityInput,
    CalculaStatisticsInput,
)
from .verifier import Verdict, alignment_failed, answers_problem, verify
from .verifier_ext import EXT_TOOLS, expected_call

logger = logging.getLogger(__name__)

# Tool catalogue -----------------------------------------------------------------------------------------------------

TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "axiom_solve": AxiomSolveInput,
    "axiom_nsolve": AxiomNsolveInput,
    "axiom_simplify": AxiomSimplifyInput,
    "axiom_calculus": AxiomCalculusInput,
    "axiom_dsolve": AxiomDsolveInput,
    "axiom_linalg": AxiomLinalgInput,
    "axiom_verify_identity": AxiomVerifyIdentityInput,
    "axiom_optimize": AxiomOptimizeInput,
    "axiom_inequality": AxiomInequalityInput,
    "axiom_tangent": AxiomTangentInput,
    "axiom_vector_calculus": AxiomVectorCalculusInput,
    "axiom_transform": AxiomTransformInput,
    "axiom_nintegrate": AxiomNintegrateInput,
    "axiom_number_theory": AxiomNumberTheoryInput,
    "axiom_recurrence": AxiomRecurrenceInput,
    "axiom_probability": AxiomProbabilityInput,
    "calcula_statistics": CalculaStatisticsInput,
    "axiom_structured": AxiomStructuredInput,
}
TOOL_FUNCS: dict[str, Callable[..., dict[str, Any]]] = {
    "axiom_solve": E.axiom_solve,
    "axiom_nsolve": E.axiom_nsolve,
    "axiom_simplify": E.axiom_simplify,
    "axiom_calculus": E.axiom_calculus,
    "axiom_dsolve": E.axiom_dsolve,
    "axiom_linalg": E.axiom_linalg,
    "axiom_verify_identity": E.axiom_verify_identity,
    "axiom_optimize": A.axiom_optimize,
    "axiom_inequality": A.axiom_inequality,
    "axiom_tangent": A.axiom_tangent,
    "axiom_vector_calculus": A.axiom_vector_calculus,
    "axiom_transform": A.axiom_transform,
    "axiom_nintegrate": A.axiom_nintegrate,
    "axiom_number_theory": D.axiom_number_theory,
    "axiom_recurrence": D.axiom_recurrence,
    "axiom_probability": D.axiom_probability,
    "calcula_statistics": D.calcula_statistics,
    "axiom_structured": axiom_structured,
}
TOOL_CARDS: dict[str, str] = {
    "axiom_solve": "exact roots of equations/systems. {equations: str | [str], variables?: str | [str], domain?: 'complex'|'real'}",
    "axiom_nsolve": "numeric real roots on an interval when no closed form exists. {equation: str, variable?: str, lower?: float, upper?: float, samples?: int}",
    "axiom_simplify": "simplify/factor/expand. {expression: str, assumptions?: {symbol: 'positive, real'}}",
    "axiom_calculus": "diff/integrate/limit/series/sum. {expression: str, operation: 'diff'|'integrate'|'limit'|'series'|'sum', variable?: str, order?: int, lower?: str, upper?: str, point?: str (limit point, '0+' / '0-' one-sided)}",
    "axiom_dsolve": "symbolic ODE solving. {equation: str (y'' + y = 0), func?: 'y(x)', ics?: {\"y(0)\": 1, \"y'(0)\": 0}}",
    "axiom_linalg": "exact linear algebra. {matrix: [[...]], operation: 'eigen'|'det'|'inv'|'rref'|'svd'|'nullspace'|'charpoly'|'solve', rhs?: [...]}",
    "axiom_verify_identity": "is lhs = rhs an identity? {lhs: str, rhs: str, assumptions?: {symbol: 'positive'}, num_points?: int}",
    "axiom_optimize": "global max/min of f(x) on an interval. {expression: str, variable?: 'x', lower?: str, upper?: str, lower_open?: bool, upper_open?: bool}",
    "axiom_inequality": "real solution set of one inequality. {inequality: 'x^2 - 4 > 0', variable?: str}",
    "axiom_tangent": "slope, tangent and normal line at x = a. {expression: str, point: str, variable?: 'x'}",
    "axiom_vector_calculus": "gradient/divergence/curl/laplacian/hessian/jacobian. {operation: str, expression?: scalar, components?: [str], variables?: ['x','y','z']}",
    "axiom_transform": "laplace / inverse_laplace / fourier transform. {expression: str, transform: 'laplace'|'inverse_laplace'|'fourier'}",
    "axiom_nintegrate": "numeric definite integral (no closed form). {expression: str, lower: str, upper: str, variable?: 'x'}",
    "axiom_number_theory": "integer arithmetic. {operation: 'factorize'|'isprime'|'gcd'|'lcm'|'divisors'|'totient'|'mod_pow'|'mod_inverse'|'crt'|'next_prime'|'diophantine', numbers: [int], modulus?: int | [int]}",
    "axiom_recurrence": "closed form of a recurrence. {recurrence: 'a(n) = a(n-1) + a(n-2)', initial: {'a(0)': 0, 'a(1)': 1}}",
    "axiom_probability": "distribution queries. {distribution: 'normal'|'binomial'|'poisson'|'exponential'|'uniform'|'geometric'|'bernoulli', parameters: [..], query: 'probability'|'mean'|'variance'|'std'|'pdf'|'cdf'|'quantile', lower?, upper?, lower_inclusive?, upper_inclusive?, value?}",
    "calcula_statistics": "statistics of inline data. {operation: 'describe'|'ttest_1samp'|'ttest_ind'|'ttest_rel'|'linregress'|'pearson'|'confidence_interval', data: [float], data2?: [float], mu0?: float, confidence?: float}",
    "axiom_structured": "questions that define their own functions, independent cases or a universal claim; a defined name is a function, never a factor. {definitions: [{name: 'T', parameter: 'n', domain: 'positive_integer'|'real'|..., branches: [{expression: 'n/2', condition: 'even'|'odd'|'otherwise'|'t < 0'|''}]}], tasks: [{id: 'T(4)', op: 'evaluate', expression: 'T(4)', bindings?: {n: 40}, factor?: bool} | {id, op: 'orbit', function: 'T', start: 1, mode: 'cycle'} | {id, op: 'claim', expression + predicate: 'prime'|'divisible'|..., or lhs + relation + rhs, variable: 'n', domain: 'nonnegative_integer'}]}",
}


class FailureClass(str, Enum):
    NONE = "none"
    SCHEMA_INVALID = "schema_invalid"  # unknown tool or arguments the schema rejects (never executed)
    MODEL_ACTION_ERROR = "model_action_error"  # executed, failed because of the arguments (parse error, bad op)
    SEMANTIC_MISMATCH = "semantic_mismatch"  # executed fine but computed something other than the problem asked
    LOCAL_CHECK_FAILED = "local_check_failed"  # aligned, but the result fails the independent check
    TOOL_CANNOT_SOLVE = "tool_cannot_solve"  # the engine has no method for this input: another strategy is needed
    NO_PROGRESS = "no_progress"  # the same action again
    INFRASTRUCTURE = "infrastructure"  # timeout, missing engine, budget: not evidence of a wrong action


REPAIRABLE = frozenset({
    FailureClass.SCHEMA_INVALID, FailureClass.MODEL_ACTION_ERROR, FailureClass.SEMANTIC_MISMATCH, FailureClass.NO_PROGRESS,
})


@dataclass
class StepLabels:
    """Separate evaluation labels per step (research recommendations, section 7.1)."""

    tool_schema_valid: bool = False
    execution_success: bool = False
    semantic_alignment: bool | None = None
    local_result_valid: bool | None = None
    progress_made: bool = False


@dataclass
class Step:
    index: int
    strategy: str
    policy: str
    tool: str
    arguments: dict[str, Any]
    rationale: str = ""
    strategy_name: str = ""
    status: Literal["ok", "error"] = "error"
    failure: FailureClass = FailureClass.NONE
    error: str = ""
    seconds: float = 0.0
    cached: bool = False
    output: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] | None = None
    labels: StepLabels = field(default_factory=StepLabels)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["failure"] = self.failure.value
        return d


@dataclass
class MathAgentConfig:
    max_steps: int = 12  # tool executions (cache hits are free)
    max_repairs: int = 4  # local repairs per strategy (THOR caps self-correction at 4)
    max_strategies: int = 6
    max_llm_steps: int = 6
    time_budget_s: float = 90.0
    tool_timeout_s: float = 30.0

    @classmethod
    def from_settings(cls) -> MathAgentConfig:
        from tribos.config.settings import get_int

        return cls(max_steps=int(get_int("TRIBOS_MATH_AGENT_MAX_STEPS")), max_repairs=int(get_int("TRIBOS_MATH_AGENT_MAX_REPAIRS")))


class MathAction(BaseModel):
    action: Literal["call_tool", "finalize", "give_up"] = "call_tool"
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    strategy: str = ""
    rationale: str = ""
    answer: str = ""


@dataclass
class Candidate:
    verdict: Verdict
    step: Step


_RANK = {"verified": 3, "partially_verified": 2, "unverified": 1, "refuted": 0}


@dataclass
class MathState:
    spec: ProblemSpec
    steps: list[Step] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # results of successful steps: the trusted prefix
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # feedback for the policy (why a strategy was abandoned)
    strategy: int = 0
    strategy_label: str = ""
    repairs: int = 0
    executions: int = 0
    infra_failures: int = 0
    strategy_switches: int = 0
    llm_calls: int = 0
    llm_mode: bool = False
    repair_attempts: int = 0
    repairs_succeeded: int = 0
    pending_repair: bool = False
    cache: dict[str, Any] = field(default_factory=dict)  # signature -> successful observation (deterministic tools)
    failed: set[str] = field(default_factory=set)
    started: float = field(default_factory=time.monotonic)

    def advance_strategy(self, reason: str) -> None:
        self.notes.append(f"strategy {self.strategy_label or self.strategy + 1} abandoned: {reason}")
        self.strategy += 1
        self.strategy_switches += 1
        self.repairs = 0
        self.strategy_label = ""
        self.pending_repair = False

    def ok_steps_in_strategy(self) -> list[Step]:
        return [s for s in self.steps if s.strategy == self.current_strategy_key and s.status == "ok"]

    @property
    def current_strategy_key(self) -> str:
        return f"{self.strategy}"

    def best(self) -> Candidate | None:
        live = [c for c in self.candidates if c.verdict.status != "refuted"]
        if not live:
            return None
        return max(live, key=lambda c: (_RANK[c.verdict.status], c.verdict.level, -c.step.index))


def signature(tool: str, args: dict[str, Any]) -> str:
    return tool + ":" + json.dumps(args, sort_keys=True, default=str)


# Executors ----------------------------------------------------------------------------------------------------------

Executor = Callable[[str, dict[str, Any]], Awaitable[Any]]  # (tool, arguments) -> ToolResult


def local_executor(timeout_s: float = 30.0) -> Executor:
    """Run the Axiom engine functions in-process (worker thread, bounded wait). Used by the axiom_solve_problem
    tool and tests; the agent phase executes through the run's budget-charged, traced tool registry instead."""

    async def run(tool: str, args: dict[str, Any]) -> Any:
        from tribos.tools.registry import ErrorType, ToolResult

        t0 = time.perf_counter()
        try:
            kwargs = TOOL_SCHEMAS[tool](**args).model_dump()
        except KeyError:
            return ToolResult(success=False, tool_name=tool, error=f"Unknown tool {tool!r}", error_type=ErrorType.NOT_FOUND)
        except ValidationError as exc:
            return ToolResult(success=False, tool_name=tool, error=f"Input validation error: {exc}", error_type=ErrorType.VALIDATION_ERROR)
        try:
            data = await asyncio.wait_for(asyncio.to_thread(TOOL_FUNCS[tool], **kwargs), timeout=timeout_s)
        except TimeoutError:
            return ToolResult(success=False, tool_name=tool, error=f"{tool} exceeded {timeout_s:.0f}s", error_type=ErrorType.TIMEOUT)
        except (ValueError, TypeError) as exc:
            return ToolResult(success=False, tool_name=tool, error=str(exc), error_type=ErrorType.VALIDATION_ERROR)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, tool_name=tool, error=f"{type(exc).__name__}: {exc}", error_type=ErrorType.INTERNAL_ERROR)
        return ToolResult(success=True, tool_name=tool, data=data, execution_time_seconds=time.perf_counter() - t0)

    return run


_CANNOT_SOLVE_MARKERS = ("NotImplementedError", "could not solve", "No algorithms are implemented", "not implemented")
_MODEL_FAULT_EXC = ("TypeError", "AttributeError", "KeyError", "IndexError", "ZeroDivisionError", "PolynomialError",
                    "CoercionFailed", "SympifyError", "ShapeError", "NonSquareMatrixError", "SyntaxError", "UnsupportedShapeError")
_INFRA_EXC = ("MemoryError", "RecursionError", "OSError", "ConnectionError")


def classify(result: Any) -> FailureClass:
    """Failure class of one tool observation (execution level only; semantic checks come from the verifier)."""
    if getattr(result, "success", False):
        return FailureClass.NONE
    et = str(getattr(getattr(result, "error_type", None), "value", getattr(result, "error_type", "")) or "")
    err = str(getattr(result, "error", "") or "")
    meta = getattr(result, "metadata", None) or {}
    if meta.get("failure_class") == "infrastructure" or "budget exhausted" in err.lower():
        return FailureClass.INFRASTRUCTURE
    if et == "NOT_FOUND" or err.startswith("Input validation error"):
        return FailureClass.SCHEMA_INVALID
    if any(m in err for m in _CANNOT_SOLVE_MARKERS):
        return FailureClass.TOOL_CANNOT_SOLVE
    if et in ("TIMEOUT", "UPSTREAM_API_ERROR"):
        return FailureClass.INFRASTRUCTURE
    if et == "VALIDATION_ERROR":
        return FailureClass.MODEL_ACTION_ERROR
    if err.startswith(_INFRA_EXC):
        return FailureClass.INFRASTRUCTURE
    if err.startswith(_MODEL_FAULT_EXC):
        return FailureClass.MODEL_ACTION_ERROR
    return FailureClass.INFRASTRUCTURE


_OUTPUT_KEYS = (
    "solutions", "roots", "residuals", "complete", "solution_set", "simplified", "factored", "result", "numeric_value",
    "solution", "rhs", "equivalent", "evidence", "counterexample", "eigenvalues", "determinant", "free_parameters",
    "verified", "verification", "interval", "latex",
)


def compact_output(data: Any, limit: int = 700) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"value": str(data)[:limit]}
    out: dict[str, Any] = {}
    for k in _OUTPUT_KEYS:
        v = data.get(k)
        # An array is "empty" by its size; comparing it with [] or {} is ambiguous in NumPy.
        empty = v is None or (hasattr(v, "size") and not isinstance(v, (str, bytes)) and getattr(v, "size", 1) == 0) \
            or (isinstance(v, (str, list, dict, tuple)) and not v)
        if k in data and not empty:
            text = json.dumps(v, default=str)
            out[k] = v if len(text) <= limit else text[:limit] + "..."
    return out


# Policies -----------------------------------------------------------------------------------------------------------

class Policy(Protocol):
    name: str

    @property
    def can_repair(self) -> bool: ...

    async def propose(self, state: MathState) -> MathAction | None: ...


Builder = Callable[[MathState, dict[str, Any]], MathAction | None]
_CANNOT_COMPLETE = frozenset({"numeric scan", "wide numeric scan", "numeric quadrature"})  # strategies whose answers are never "verified"


def _act(tool: str, strategy: str, rationale: str, **args: Any) -> MathAction:
    return MathAction(tool=tool, arguments={k: v for k, v in args.items() if v is not None}, strategy=strategy, rationale=rationale)


def _rule_strategies(spec: ProblemSpec) -> list[tuple[str, list[Builder]]]:
    """Explicit routing table: an ordered strategy ladder per task kind (logged, so it can be learned later)."""
    k, ex, var = spec.kind, spec.expression, spec.variable
    asm = spec.assumptions or None

    def simplify_first(name: str, tool_args: Callable[[str], MathAction], use: str = "simplified") -> tuple[str, list[Builder]]:
        return name, [
            lambda st, prev: _act("axiom_simplify", name, "rewrite the expression into a simpler equivalent form first", expression=ex, assumptions=asm),
            lambda st, prev: tool_args(str(prev.get(use) or prev.get("simplified") or ex)),
        ]

    if k == "solve" and spec.equations:
        return [("exact system solve", [lambda st, prev: _act(
            "axiom_solve", "exact system solve", "solve the system exactly and back-substitute",
            equations=spec.equations, variables=spec.variables or None, domain=spec.domain)])]
    if k == "solve":
        positive = "positive" in (spec.assumptions.get(var or "", "") if var else "")
        strategies: list[tuple[str, list[Builder]]] = [("exact solve", [lambda st, prev: _act(
            "axiom_solve", "exact solve", "solve exactly; every root is back-substituted", equations=ex, variables=var, domain=spec.domain)])]
        can_numeric = False
        if ex and isinstance(ex, str):
            try:
                lhs, rhs, _ = E.safe_parse_equation(ex)
                if not (isinstance(lhs, (sp.Tuple, tuple, list)) or isinstance(rhs, (sp.Tuple, tuple, list))):
                    f = lhs - rhs
                    free = f.free_symbols
                    if var:
                        can_numeric = not bool(free - {sp.Symbol(var)})
                    else:
                        can_numeric = len(free) == 1
            except Exception:
                can_numeric = False
        if can_numeric:
            strategies.append(("numeric scan", [lambda st, prev: _act(
                "axiom_nsolve", "numeric scan", "no usable closed form: locate real roots numerically",
                equation=ex, variable=var, lower=0.0 if positive else -10.0, upper=10.0, samples=800)]))
            strategies.append(("wide numeric scan", [lambda st, prev: _act(
                "axiom_nsolve", "wide numeric scan", "widen the numeric search interval",
                equation=ex, variable=var, lower=0.0 if positive else -1000.0, upper=1000.0, samples=5000)]))
        return strategies
    if k in ("simplify", "evaluate"):
        return [("simplify", [lambda st, prev: _act("axiom_simplify", "simplify", "simplify symbolically", expression=ex, assumptions=asm)])]
    if k in ("differentiate", "integrate", "limit", "series", "sum"):
        op = {"differentiate": "diff", "integrate": "integrate", "limit": "limit", "series": "series", "sum": "sum"}[k]

        def calc(expr: str, name: str) -> MathAction:
            order = spec.order if k in ("differentiate", "series") else None
            return _act("axiom_calculus", name, f"{op} with the engine's own numerical cross-check", expression=expr,
                        operation=op, variable=var or "x", order=order, lower=spec.lower, upper=spec.upper, point=spec.point)

        out: list[tuple[str, list[Builder]]] = [(f"direct {op}", [lambda st, prev: calc(ex or "", f"direct {op}")])]
        if k in ("integrate", "limit", "differentiate"):
            out.append(simplify_first(f"simplify, then {op}", lambda e: calc(e, f"simplify, then {op}")))
        if k == "integrate":
            out.append(simplify_first("expand, then integrate", lambda e: calc(e, "expand, then integrate"), use="expanded"))
            if spec.lower is not None and spec.upper is not None:
                out.append(("numeric quadrature", [lambda st, prev: _act(
                    "axiom_nintegrate", "numeric quadrature", "no closed form: integrate numerically with two quadrature rules",
                    expression=ex, lower=spec.lower, upper=spec.upper, variable=var or "x")]))
        return out
    if k in EXT_TOOLS:
        call = expected_call(spec)
        if call is None:
            return []
        tool, args = call
        name = tool.replace("axiom_", "").replace("calcula_", "").replace("_", " ")
        return [(name, [lambda st, prev: MathAction(tool=tool, arguments=args, strategy=name, rationale=f"{name} with its independent check")])]
    if k == "ode":
        return [("dsolve", [lambda st, prev: _act("axiom_dsolve", "dsolve", "solve the ODE symbolically with its conditions",
                                                  equation=ex, func=spec.func or "y(x)", ics=spec.ics or None)])]
    if k == "linalg":
        return [("exact linear algebra", [lambda st, prev: _act("axiom_linalg", "exact linear algebra", f"exact {spec.linalg_op}",
                                                                matrix=spec.matrix, operation=spec.linalg_op, rhs=spec.rhs_vector)])]
    if k == "identity" and ex:
        lhs, rhs = (p.strip() for p in ex.replace("==", "=").split("=", 1))
        return [("identity check", [lambda st, prev: _act("axiom_verify_identity", "identity check",
                                                          "symbolic proof attempt plus sampling over the whole domain",
                                                          lhs=lhs, rhs=rhs, assumptions=asm, num_points=12)])]
    return []


class RulePolicy:
    """Deterministic routing: walks the strategy ladder for the parsed task kind. Cannot repair arguments (it would
    only repeat itself), so a failed step moves straight to the next strategy."""

    name = "rules"
    can_repair = False

    def __init__(self) -> None:
        self._strategies: list[tuple[str, list[Builder]]] | None = None

    def exhausted(self, state: MathState) -> bool:
        return state.strategy >= len(self._ladder(state))

    def _ladder(self, state: MathState) -> list[tuple[str, list[Builder]]]:
        if self._strategies is None:
            self._strategies = _rule_strategies(state.spec) if state.spec.parsed else []
        return self._strategies

    async def propose(self, state: MathState) -> MathAction | None:
        ladder = self._ladder(state)
        if state.spec.unaccounted and state.candidates:
            return None  # every rule strategy encodes the same incomplete parse: another one cannot do better
        while state.strategy < len(ladder):
            name, builders = ladder[state.strategy]
            best = state.best()
            if name in _CANNOT_COMPLETE and best is not None and best.verdict.status == "partially_verified":
                # A numeric scan can never prove completeness, so it cannot upgrade a partially verified answer.
                state.strategy += 1
                continue
            done = state.ok_steps_in_strategy()
            if len(done) < len(builders):
                prev = state.cache.get(signature(done[-1].tool, done[-1].arguments), None) if done else None
                prev_data = getattr(prev, "data", None) or {}
                action = builders[len(done)](state, prev_data if isinstance(prev_data, dict) else {})
                if action is not None:
                    state.strategy_label = name
                    return action
            state.advance_strategy("strategy finished without a verified answer")
        return None


_LLM_SYSTEM = """[phase:math_agent] You are the policy of a verified mathematics agent. Each turn choose ONE next action and reply with JSON only.

Tools (use exactly these argument names):
{cards}

Rules:
- Encode exactly the problem as stated: the same equation, expression, bounds, variable, domain and conditions. Never change the problem to make it easier.
- Never invent tool results; base every decision on the observations shown.
- Expression syntax: * for multiplication, ^ or ** for powers, sqrt(), exp(), log(), pi, oo; equations as "lhs = rhs".
- After a failed step repair only that step (fix the arguments), or switch tool/strategy when the approach cannot work. Never repeat an identical failed call.
- SEMANTIC_MISMATCH means the call computed something other than the problem: re-encode the original problem.
- If exact solving fails or times out, use axiom_nsolve on a sensible interval.
- For multi-step problems compute intermediate results first, then call the tool whose result answers the question.
- When the observations contain the answer (ideally verifier status "verified"), reply with action "finalize" and state it.

Reply format: {{"action": "call_tool" | "finalize" | "give_up", "tool": "<tool>", "arguments": {{...}}, "strategy": "<short label>", "rationale": "<one sentence>", "answer": "<final answer, finalize only>"}}"""


def _state_prompt(state: MathState, cfg: MathAgentConfig) -> str:
    spec = state.spec
    lines = [f"Problem (verbatim): {spec.text}"]
    if spec.parsed:
        parsed = {k: v for k, v in spec.to_dict().items() if v not in (None, [], {}, "") and k not in ("text", "ambiguities")}
        lines.append(f"Parsed problem: {json.dumps(parsed, default=str)}")
    if spec.ambiguities:
        lines.append("Parser assumptions: " + "; ".join(spec.ambiguities))
    if state.facts:
        lines.append("Established results:\n" + "\n".join(f"- {f}" for f in state.facts[-8:]))
    if state.steps:
        lines.append("Steps so far (most recent last):")
        for s in state.steps[-6:]:
            obs = json.dumps(s.output, default=str)[:500] if s.status == "ok" else s.error[:400]
            verdict = ""
            if s.verdict:
                bad = [c["name"] for c in s.verdict.get("checks", []) if c.get("passed") is False]
                verdict = f" | verifier: {s.verdict['status']}" + (f" (failed: {', '.join(bad)})" if bad else "")
            lines.append(f"  #{s.index} {s.tool}({json.dumps(s.arguments, default=str)[:300]}) -> {s.status.upper()}"
                         f"{'' if s.failure == FailureClass.NONE else ' [' + s.failure.value.upper() + ']'}: {obs}{verdict}")
    if state.notes:
        lines.append("Notes: " + " | ".join(state.notes[-4:]))
    lines.append(f"Budget: {max(0, cfg.max_steps - state.executions)} tool calls, repairs used in this strategy {state.repairs}/{cfg.max_repairs}.")
    lines.append("Next action (JSON only):")
    return "\n".join(lines)


class LLMPolicy:
    """The planning model as the policy (any AgentLLM: budget-charged, JSON-validated)."""

    name = "llm"
    can_repair = True

    def __init__(self, llm: Any, cfg: MathAgentConfig, phase: str = "math_agent") -> None:
        self.llm, self.cfg, self.phase = llm, cfg, phase
        self.system = _LLM_SYSTEM.format(cards="\n".join(f"- {k}: {v}" for k, v in TOOL_CARDS.items()))
        self.unavailable_reason = ""

    async def propose(self, state: MathState) -> MathAction | None:
        if state.llm_calls >= self.cfg.max_llm_steps:
            return None
        state.llm_calls += 1
        try:
            return await self.llm.json(self.system, _state_prompt(state, self.cfg), schema=MathAction, phase=self.phase)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - unavailable model, malformed JSON, exhausted budget
            self.unavailable_reason = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.info("Math agent model step failed: %s", self.unavailable_reason)
            if type(exc).__name__ == "RunCancelled":
                raise
            return None


class HybridPolicy:
    """Rules first (free, deterministic, logged); the model only when the rules found no checked answer."""

    name = "hybrid"

    def __init__(self, llm: Any | None = None, cfg: MathAgentConfig | None = None) -> None:
        self.cfg = cfg or MathAgentConfig()
        self.rules = RulePolicy()
        self.llm = LLMPolicy(llm, self.cfg) if llm is not None and getattr(llm, "available", True) else None
        self._in_llm_mode = False

    @property
    def can_repair(self) -> bool:
        return self._in_llm_mode

    async def propose(self, state: MathState) -> MathAction | None:
        if not self._in_llm_mode:
            action = await self.rules.propose(state)
            if action is not None:
                return action
            best = state.best()
            if best is not None and best.verdict.status in ("verified", "partially_verified"):
                return None  # the model cannot do better than a checked answer with these tools
            if self.llm is None:
                return None
            self._in_llm_mode = state.llm_mode = True
            state.notes.append("deterministic strategies produced no checked answer; the model now chooses the steps")
            if state.spec.unaccounted:
                # The parse misses part of the question: the model reads the verbatim text, and its calls are checked
                # against their own arguments instead of a parse known to be incomplete.
                state.notes.append("the parser could not account for " + ", ".join(state.spec.unaccounted) + "; encode the verbatim question")
                state.spec = ProblemSpec(text=state.spec.text, domain=state.spec.domain, assumptions=state.spec.assumptions)
        assert self.llm is not None
        return await self.llm.propose(state)


# Controller ---------------------------------------------------------------------------------------------------------

StepCallback = Callable[[Step, MathState], Awaitable[None]]


@dataclass
class MathRun:
    status: Literal["verified", "partially_verified", "unverified", "failed"]
    answer: dict[str, Any]
    verdict: Verdict | None
    state: MathState
    seconds: float
    trajectory: dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> dict[str, Any]:
        st = self.state
        failed = [s for s in st.steps if s.status == "error" or s.failure != FailureClass.NONE]
        return {
            "steps": len(st.steps),
            "tool_executions": st.executions,
            "cache_hits": sum(1 for s in st.steps if s.cached),
            "failed_steps": len(failed),
            "failures_by_class": {fc.value: sum(1 for s in failed if s.failure == fc) for fc in FailureClass if any(s.failure == fc for s in failed)},
            "repair_attempts": st.repair_attempts,
            "repairs_succeeded": st.repairs_succeeded,
            "strategy_switches": st.strategy_switches,
            "infrastructure_failures": st.infra_failures,
            "llm_calls": st.llm_calls,
            "seconds": round(self.seconds, 3),
        }

    def to_dict(self, *, trajectory: bool = False) -> dict[str, Any]:
        out = {
            "status": self.status,
            "answer": self.answer,
            "verification": self.verdict.to_dict() if self.verdict else None,
            "uncertainty": (self.verdict.uncertainty if self.verdict else []) + self.state.spec.ambiguities,
            "confidence": calibrated_confidence(self.status),
            "problem": {k: v for k, v in self.state.spec.to_dict().items() if v not in (None, [], {}, "")},
            "steps": [s.to_dict() for s in self.state.steps],
            "metrics": self.metrics,
        }
        if trajectory:
            out["trajectory"] = self.trajectory
        return out


async def solve_math_problem(
    problem: str | ProblemSpec,
    *,
    executor: Executor | None = None,
    policy: Policy | None = None,
    config: MathAgentConfig | None = None,
    on_step: StepCallback | None = None,
) -> MathRun:
    """Run the bounded agent loop on one problem and return the best-supported answer with its evidence."""
    cfg = config or MathAgentConfig()
    spec = problem if isinstance(problem, ProblemSpec) else parse_problem(problem)
    run_tool = executor or local_executor(cfg.tool_timeout_s)
    pol: Policy = policy or HybridPolicy(None, cfg)
    state = MathState(spec=spec)
    deadline = state.started + cfg.time_budget_s
    final_text = ""

    while state.executions < cfg.max_steps and time.monotonic() < deadline and state.strategy < cfg.max_strategies:
        action = await pol.propose(state)
        if action is None or action.action == "give_up":
            if action is not None:
                state.notes.append(f"policy gave up: {action.rationale[:200]}")
            break
        if action.action == "finalize":
            final_text = action.answer.strip()
            break
        if action.strategy and action.strategy != state.strategy_label and state.llm_mode:
            if state.strategy_label:  # the model chose a different approach: a new strategy with a fresh repair budget
                state.advance_strategy(f"model switched to {action.strategy!r}")
            state.strategy_label = action.strategy
        step = await _run_step(state, action, run_tool, pol, cfg)
        state.steps.append(step)
        if on_step is not None:
            try:
                await on_step(step, state)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ == "RunCancelled":
                    raise
                logger.debug("math agent step callback failed: %s", exc)
        if "budget exhausted" in step.error.lower():
            break
        best = state.best()
        if best is not None and best.verdict.sufficient:
            break

    best = state.best()
    seconds = time.monotonic() - state.started
    if best is not None:
        run = MathRun(best.verdict.status, best.verdict.answer, best.verdict, state, seconds)  # type: ignore[arg-type]
    elif final_text:
        unverified = Verdict("unverified", 0, [], ["the final answer was stated by the model without a checked tool result"], {"text": final_text})
        run = MathRun("unverified", {"text": final_text}, unverified, state, seconds)
    else:
        reasons = state.notes[-3:] or ["no strategy produced a result"]
        run = MathRun("failed", {}, Verdict("unverified", -1, [], reasons, {}), state, seconds)
    run.trajectory = trajectory_record(run)
    record_trajectory(run.trajectory)
    return run


async def _run_step(state: MathState, action: MathAction, run_tool: Executor, pol: Policy, cfg: MathAgentConfig) -> Step:
    tool = str(action.tool or "")
    args = dict(action.arguments or {})
    step = Step(
        index=len(state.steps), strategy=state.current_strategy_key, policy=pol.name if not state.llm_mode else "llm",
        tool=tool, arguments=args, rationale=action.rationale[:300], strategy_name=state.strategy_label,
    )
    if isinstance(pol, HybridPolicy) and not state.llm_mode:
        step.policy = "rules"

    def fail(fc: FailureClass, error: str) -> Step:
        step.failure, step.error, step.status = fc, error[:600], "error"
        _after_failure(state, step, pol, cfg)
        return step

    schema = TOOL_SCHEMAS.get(tool)
    if schema is None:
        return fail(FailureClass.SCHEMA_INVALID, f"unknown tool {tool!r}; allowed: {', '.join(TOOL_SCHEMAS)}")
    try:
        schema(**args)
    except ValidationError as exc:
        return fail(FailureClass.SCHEMA_INVALID, f"Input validation error: {exc}")
    step.labels.tool_schema_valid = True

    sig = signature(tool, args)
    if sig in state.failed:
        return fail(FailureClass.NO_PROGRESS, "this exact call already failed; change the arguments or the approach")
    cached = state.cache.get(sig)
    t0 = time.perf_counter()
    if cached is not None:
        result, step.cached = cached, True
    else:
        state.executions += 1
        try:
            result = await run_tool(tool, args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ in ("RunCancelled", "BudgetExhausted"):
                raise
            from tribos.tools.registry import ErrorType, ToolResult

            result = ToolResult(success=False, tool_name=tool, error=f"{type(exc).__name__}: {exc}", error_type=ErrorType.INTERNAL_ERROR)
    step.seconds = round(time.perf_counter() - t0, 4)

    fc = classify(result)
    if fc != FailureClass.NONE:
        state.failed.add(sig)
        return fail(fc, str(getattr(result, "error", "") or "tool failed"))
    data = getattr(result, "data", None)
    data = data if isinstance(data, dict) else {"value": data}
    state.cache[sig] = result
    step.status = "ok"
    step.labels.execution_success = True
    step.output = compact_output(data)

    if not answers_problem(state.spec, tool, args):
        if state.pending_repair:
            state.repairs_succeeded += 1
            state.pending_repair = False
        state.facts.append(f"{tool}({_short(args)}) -> {_short(step.output)}")
        step.labels.progress_made = bool(step.output)
        return step

    try:
        verdict = await asyncio.wait_for(asyncio.to_thread(verify, state.spec, tool, args, data), timeout=cfg.tool_timeout_s)
    except TimeoutError:
        verdict = Verdict("unverified", 0, [], ["the independent verifier timed out"], {"text": _short(step.output)})
    step.verdict = verdict.to_dict()
    aligned = [c.passed for c in verdict.checks if c.level == 1]
    step.labels.semantic_alignment = aligned[0] if aligned else None
    independent = [c.passed for c in verdict.checks if c.level == 2 and c.passed is not None]
    step.labels.local_result_valid = all(independent) if independent else None

    if verdict.status == "refuted":
        state.failed.add(sig)  # a rejected result is a failed call: the cache must never serve it again
    if alignment_failed(verdict):
        bad = next(c for c in verdict.checks if c.level == 1 and c.passed is False)
        step.failure, step.error = FailureClass.SEMANTIC_MISMATCH, f"{bad.name}: {bad.detail}"[:600]
        _after_failure(state, step, pol, cfg)
        return step
    if verdict.status == "refuted":
        bad = next((c for c in verdict.checks if c.passed is False), None)
        step.failure = FailureClass.LOCAL_CHECK_FAILED
        step.error = f"{bad.name}: {bad.detail}"[:600] if bad else "the independent check failed"
        _after_failure(state, step, pol, cfg)
        return step

    step.labels.progress_made = True
    if state.pending_repair:
        state.repairs_succeeded += 1
        state.pending_repair = False
    state.candidates.append(Candidate(verdict, step))
    state.facts.append(f"candidate answer ({verdict.status}): {verdict.answer.get('text', '')[:300]}")
    if not verdict.sufficient:
        state.advance_strategy(f"answer only {verdict.status.replace('_', ' ')}: {'; '.join(verdict.uncertainty[:2])}")
    return step


def _after_failure(state: MathState, step: Step, pol: Policy, cfg: MathAgentConfig) -> None:
    """Escalation ladder after a failed step: repair locally while the policy can and the repair budget lasts,
    otherwise switch strategy. Infrastructure failures are not charged as repairs."""
    if step.failure == FailureClass.INFRASTRUCTURE:
        state.infra_failures += 1
        state.advance_strategy(f"infrastructure failure ({step.error[:120]})")
        return
    if step.failure in (FailureClass.TOOL_CANNOT_SOLVE, FailureClass.LOCAL_CHECK_FAILED):
        state.advance_strategy(f"{step.failure.value}: {step.error[:160]}")
        return
    state.repairs += 1
    if not pol.can_repair or state.repairs > cfg.max_repairs:
        state.advance_strategy(f"{step.failure.value} after {state.repairs} attempt(s): {step.error[:160]}")
    else:
        state.repair_attempts += 1
        state.pending_repair = True


def _short(value: Any, limit: int = 200) -> str:
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "..."


# Calibration --------------------------------------------------------------------------------------------------------

# The code a calibration describes: the parser, the policy and the verifier (AUDIT-013). A calibration file whose
# code_sha256 does not match these sources describes different code and is not used.
CALIBRATED_SOURCES = ("problem.py", "agent.py", "verifier.py", "verifier_ext.py", "engine.py", "safe_expr.py")


@functools.lru_cache(maxsize=1)
def calibrated_code_sha256() -> str:
    h = hashlib.sha256()
    for name in CALIBRATED_SOURCES:
        path = Path(__file__).with_name(name)
        h.update(name.encode("utf-8") + b"\x00")
        h.update(path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else b"<missing>")
    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def _calibration() -> dict[str, Any]:
    try:
        return json.loads(Path(__file__).with_name("calibration.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clear_calibration_cache() -> None:
    """Clear the cached calibration.json for testing or runtime reloads."""
    _calibration.cache_clear()


def calibrated_confidence(status: str, cal: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Empirical P(answer correct | status) from the held-out benchmark (tribos/axiom/math_eval.py).

    Applies strictly to the verified final answer expression only. Returns None when no answer was given,
    status is not verified, or sample size is below statistical significance threshold: unverified,
    rejected, invalidated or tiny-sample statuses never function as confidence badges.
    """
    if status != "verified":
        return None
    from_file = cal is None
    if cal is None:
        cal = _calibration()
    if (from_file or "code_sha256" in cal) and cal.get("code_sha256") != calibrated_code_sha256():
        return None  # fitted on other code (or of unknown code): stale
    entry = (cal.get("statuses") or {}).get(status)
    if not entry or not entry.get("n") or entry.get("n", 0) < 10:
        return None
    return {
        "p_correct": entry["confidence"],
        "lower_95": entry["lower_95"],
        "n": entry["n"],
        "benchmark": cal.get("benchmark", "math-eval-v1"),
        "split": cal.get("fitted_on", ""),
        "fitted_at": cal.get("fitted_at"),
        "fitted_on": f"{cal.get('benchmark', '')}: {cal.get('fitted_on', '')}".strip(": "),
        "scope": "final_expression_only",
        "is_probability": False,
        "limitations": (
            "Held-out benchmark of single problems; applies strictly to the final expression, "
            "not the surrounding written derivation or current-answer probability."
        ),
    }


# Trajectories ---------------------------------------------------------------------------------------------------

def trajectory_record(run: MathRun) -> dict[str, Any]:
    """ToRA-style interleaved record (decision / tool_call / observation / verification) with step labels."""
    import mpmath
    import sympy

    st = run.state
    events: list[dict[str, Any]] = []
    for s in st.steps:
        events.append({"type": "decision", "content": s.rationale, "strategy": s.strategy, "policy": s.policy})
        events.append({"type": "tool_call", "tool": s.tool, "arguments": s.arguments})
        events.append({
            "type": "observation",
            "content": s.output if s.status == "ok" else s.error,
            "execution_status": "success" if s.labels.execution_success else "error",
            "failure_class": s.failure.value,
            "cached": s.cached,
            "seconds": s.seconds,
        })
        if s.verdict:
            events.append({
                "type": "verification",
                "status": s.verdict["status"],
                "checks": [{k: c[k] for k in ("name", "passed", "level")} for c in s.verdict["checks"]],
            })
    passed = [c.name for c in (run.verdict.checks if run.verdict else []) if c.passed]
    return {
        "problem_id": hashlib.sha256(st.spec.text.encode("utf-8")).hexdigest()[:16],
        "problem": st.spec.text,
        "domain": st.spec.kind,
        "parsed": {k: v for k, v in st.spec.to_dict().items() if v not in (None, [], {}, "") and k != "text"},
        "trajectory": events,
        "step_labels": [asdict(s.labels) for s in st.steps],
        "final_answer": run.answer.get("text", ""),
        "answer_status": run.status,
        "verification_evidence": passed,
        "uncertainty": run.verdict.uncertainty if run.verdict else [],
        "metrics": run.metrics,
        "source": "tribos_math_agent",
        "engine_versions": {"sympy": sympy.__version__, "mpmath": mpmath.__version__},
        "split": "unassigned",
        "created_at": datetime.now(UTC).isoformat(),
    }


_WRITE_LOCK = threading.Lock()


def record_trajectory(record: dict[str, Any]) -> None:
    """Append one trajectory to <TRIBOS_MATH_TRAJECTORY_DIR>/math-trajectories-YYYYMMDD.jsonl (off when unset)."""
    try:
        from tribos.config.settings import get_path

        root = get_path("TRIBOS_MATH_TRAJECTORY_DIR")
        if root is None:
            return
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"math-trajectories-{datetime.now(UTC):%Y%m%d}.jsonl"
        line = json.dumps(record, default=str, ensure_ascii=False)
        with _WRITE_LOCK, path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never fail a run
        logger.warning("Could not record math trajectory: %s", exc)


async def solve_problem_tool(problem: str) -> dict[str, Any]:
    """Executor of the axiom_solve_problem registry tool: deterministic rules + verifier, no model calls."""
    run = await solve_math_problem(problem, config=MathAgentConfig.from_settings())
    return run.to_dict()


__all__ = [
    "FailureClass",
    "HybridPolicy",
    "LLMPolicy",
    "MathAction",
    "MathAgentConfig",
    "MathRun",
    "MathState",
    "RulePolicy",
    "Step",
    "StepLabels",
    "TOOL_CARDS",
    "TOOL_SCHEMAS",
    "calibrated_confidence",
    "classify",
    "clear_calibration_cache",
    "local_executor",
    "record_trajectory",
    "solve_math_problem",
    "solve_problem_tool",
    "trajectory_record",
]
