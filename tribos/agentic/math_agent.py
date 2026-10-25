"""
Agent phase: the verified mathematics agent (tribos/axiom/agent.py) on mathematical questions.

Runs in the augment stage of every agentic framework when the question parses as a concrete mathematical task
(an equation to solve, a derivative, integral, limit, series, sum, ODE, matrix operation or identity). The rules
policy handles the parsed task deterministically at no model cost; the planning model is used only when the rules
reach no checked answer. Every tool call goes through the run's budget-charged, traced registry.

The synthesis receives the answer with its verification status: a verified result is to be reported as the
result; a partially verified one with its stated gaps; anything else may not be presented as verified.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from ..agents.evidence_need import is_closed_computation
from ..axiom.agent import HybridPolicy, MathAgentConfig, MathState, Step, solve_math_problem
from ..axiom.problem import has_math_intent, parse_problem
from .runtime import AgentPhase, PhaseOutcome, register_phase
from .state import AgentState

logger = logging.getLogger(__name__)

PHASE_KEY = "math_agent"
RESULT_KEY = "agent.math_agent.result"
AGENT_NAME = "Axiom"

_STATUS_TITLE = {
    "verified": "Verified answer",
    "partially_verified": "Partially verified answer",
    "unverified": "Unverified answer",
    "failed": "No verified answer",
}


def _enabled(state: AgentState) -> bool:
    from ..config.settings import get_bool

    return bool(get_bool("TRIBOS_MATH_AGENT")) and state.options.get("enable_math_agent", True) is not False


def math_agent_available(state: Any) -> bool:
    """Whether the verified mathematics agent can run this turn (switched on, Axiom tools registered)."""
    registry = getattr(state, "registry", None)
    return _enabled(state) and registry is not None and registry.get_entry("axiom_solve") is not None


def _evidence_xml(art: dict[str, Any]) -> str:
    def esc(value: Any, limit: int = 2000) -> str:
        text = str(value if value is not None else "")
        return escape(text if len(text) <= limit else text[:limit] + "...", quote=False)

    ver = art.get("verification") or {}
    problem = art.get("problem") or {}
    # The benchmark rate is measured on verified answers only: it is never attached to an answer that is not verified.
    conf = (art.get("confidence") or {}) if art.get("status") == "verified" else {}
    conf_attr = (
        f'benchmark_precision="{conf["p_correct"]}" calibration_n="{conf["n"]}" '
        'precision_scope="this final answer expression only, not the written explanation" '
        if conf else ""
    )
    out = [
        f'<math_agent key="{RESULT_KEY}" status="{escape(str(art.get("status")), quote=True)}" {conf_attr}'
        f'kind="{escape(str(problem.get("kind", "")), quote=True)}" '
        'note="computed with SymPy/mpmath by the verified mathematics agent; the verifier re-checked the answer '
        'against the original problem statement. Quote the answer exactly; report the verification status honestly">'
    ]
    out.append(f"<math_problem>{esc(problem.get('text'), 1500)}</math_problem>")
    answer = art.get("answer") or {}
    if answer.get("text"):
        out.append(f"<math_answer>{esc(answer['text'], 3000)}</math_answer>")
    if answer.get("latex"):
        out.append(f"<math_answer_latex>{esc(answer['latex'], 3000)}</math_answer_latex>")
    checks = [c for c in ver.get("checks") or [] if c.get("level", 0) >= 1]
    if checks:
        out.append("<math_checks>")
        for c in checks:
            passed = {True: "passed", False: "failed", None: "not run"}[c.get("passed")]
            out.append(f'<math_check level="{c.get("level")}" result="{passed}">{esc(c.get("name"), 200)}'
                       f'{": " + esc(c.get("detail"), 400) if c.get("detail") else ""}</math_check>')
        out.append("</math_checks>")
    # The derivation of a structured answer, generated from the exact computation (which branch applies and why,
    # the substitution, each term, the factorization, the counterexample): every line is already checked.
    derivation = [f"[{r.get('id')}] {s}" for r in answer.get("results") or [] if isinstance(r, dict)
                  for s in r.get("steps") or []]
    if derivation:
        out.append("<math_derivation note=\"checked steps, generated from the exact computation; use them as the "
                   "worked solution, in this order, without changing a value\">" + esc("\n".join(derivation[:60]), 6000)
                   + "</math_derivation>")
    for u in (art.get("uncertainty") or [])[:6]:
        out.append(f"<math_uncertainty>{esc(u, 600)}</math_uncertainty>")
    steps = art.get("steps") or []
    if steps:
        lines = [
            f"#{s['index']} {s['tool']} [{s.get('strategy_name') or s['policy']}] -> "
            f"{s['status']}{'' if s['failure'] == 'none' else ' (' + s['failure'] + ')'}"
            for s in steps[:12]
        ]
        out.append("<math_steps>" + esc("\n".join(lines), 2500) + "</math_steps>")
    out.append("</math_agent>")
    return "\n".join(out)


class MathAgentPhase(AgentPhase):
    key = PHASE_KEY
    stage = "augment"
    order = 40
    frameworks = None
    needs_llm = False

    def applies(self, state: AgentState) -> bool:
        if not math_agent_available(state):
            return False
        query = state.clean_query or state.query
        # A closed computation ("What is 2+3?") is mathematics even without a keyword such as "solve".
        if not has_math_intent(query) and not is_closed_computation(state.ctx):
            return False
        spec = parse_problem(query)
        state.bag["math_problem_spec"] = spec
        return spec.parsed

    async def run(self, state: AgentState) -> PhaseOutcome | None:
        spec = state.bag.get("math_problem_spec") or parse_problem(state.clean_query or state.query)
        cfg = MathAgentConfig.from_settings()
        cfg.time_budget_s = max(10.0, min(cfg.time_budget_s, state.budget.remaining_seconds())) if state.budget.time_limited else cfg.time_budget_s
        await state.step("agent_math", f"Solving the {spec.kind} problem with verified tools", status="running", agent=AGENT_NAME)

        async def execute(tool: str, args: dict[str, Any]) -> Any:
            return await state.call_tool(tool, phase=PHASE_KEY, purpose=f"math agent: {tool}", store=False, **args)

        async def on_step(step: Step, st: MathState) -> None:
            verdict = (step.verdict or {}).get("status")
            text = step.error if step.status == "error" else str(step.output.get("result") or step.output.get("solutions") or step.output.get("simplified") or "")[:240]
            title = f"{step.tool} ({st.strategy_label or step.policy})" + (f": {verdict.replace('_', ' ')}" if verdict else "")
            await state.step(f"agent_math_{step.index}", title, text[:300], status="done" if step.status == "ok" and step.failure.value == "none" else "error", agent=AGENT_NAME)

        llm = state.llm if state.llm.available else None
        run = await solve_math_problem(spec, executor=execute, policy=HybridPolicy(llm, cfg), config=cfg, on_step=on_step)
        art = run.to_dict()
        state.artifacts["math_agent"] = art

        from ..tools.registry import ErrorType, ToolResult

        ok = run.status != "failed"
        state.add_result(
            RESULT_KEY,
            ToolResult(
                success=ok,
                tool_name="axiom_solve_problem",
                data={k: art[k] for k in ("status", "answer", "verification", "uncertainty", "metrics")},
                error=None if ok else "; ".join(art["uncertainty"][:2]) or "no verified answer",
                error_type=None if ok else ErrorType.SIMULATION_FAILED,
                metadata={"engine": "sympy", "verification_status": run.status},
            ),
            phase=PHASE_KEY,
            purpose=f"verified mathematics agent ({spec.kind})",
            render=False,
        )
        if run.status in ("verified", "partially_verified"):
            state.evidence_sections.append(_evidence_xml(art))
        answer = str(run.answer.get("text") or "")
        from ..utils.output_contract import extract as extract_contract

        if run.status == "verified" and extract_contract(state.query).strict_form:
            # The user fixed the answer's form (lines, words, plain text): the checked values go into that form; the
            # checks are shown by the interface, not written as report sections.
            state.brief_notes.append(
                "The verified mathematics agent solved the question (see <math_agent>). State its values exactly, in "
                "the user's requested format and nothing more; within a word limit, compress the checked steps in "
                "<math_derivation> (e.g. 'T(1) = 3*1 + 1 = 4') rather than dropping the reasoning; never re-derive a "
                "number in the text.")
        elif run.status == "verified":
            passed = [c.name for c in run.verdict.checks if c.passed and c.level >= 1] if run.verdict else []
            state.brief_notes.append(
                "The verified mathematics agent solved the question (see <math_agent>). Give its answer exactly as the "
                "Result, derive it step by step"
                + (" using the checked steps in <math_derivation> in order (each line states which definition or branch "
                   "applies and why, then the exact arithmetic), so every step of the worked solution is one the "
                   "checker confirmed" if any((r or {}).get("steps") for r in run.answer.get("results") or []) else "")
                + ", and in the Verification section name the independent checks that "
                f"passed ({'; '.join(passed)[:300]})."
                + (f" The agent's verified answers were correct in {art['confidence']['p_correct']:.0%} of held-out "
                   f"benchmark problems (n={art['confidence']['n']}); if you mention it, say it applies to the agent's "
                   "final answer expression only, never to the whole answer or to values you derive from it." if art.get("confidence") else "")
                + " Every other quantity you state must be one the evidence computed (for example a <parameter> in "
                  "<ode_verification>), copied exactly; never re-derive a number in the text."
            )
        elif run.status == "partially_verified":
            state.brief_notes.append(
                "The mathematics agent's answer (see <math_agent>) is only partially verified. Report it, and state "
                f"plainly what is not established: {'; '.join(art['uncertainty'][:3])[:500]}."
            )
        else:
            state.scope_notes.append(
                "The mathematics agent found no verified answer; do not present any computed value as verified, and say "
                "which parts of the derivation are unchecked."
            )
        state.mark_phase(PHASE_KEY, "ok" if ok else "fallback", "" if ok else "no checked answer")
        m = run.metrics
        # A long answer is cut with a visible ellipsis, so "... + 5*c" never reads as a term of the result.
        shown = answer if len(answer) <= 120 else answer[:119].rstrip() + "…"
        title = f"{_STATUS_TITLE[run.status]}" + (f": {shown}" if answer else "")
        await state.step(
            "agent_math", title,
            f"{m['tool_executions']} tool call(s), {m['strategy_switches']} strategy switch(es), {m['llm_calls']} model step(s), {m['seconds']:.2f}s",
            status="done" if ok else "error", agent=AGENT_NAME,
        )
        return PhaseOutcome(artifacts={"math_agent": art})


register_phase(MathAgentPhase())
