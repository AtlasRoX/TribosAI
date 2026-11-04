"""
Response stages around the draft (tribos.writer):

- compute_results (before drafting): the user's task outline, and values computed by code for an initial-value
  problem (exact solution with checks, oscillator parameters, values at requested points, RK4 comparison), added as the
  "computed_results" tool result so the writer, the verifier and the manifest all see them.
- polish (after drafting, and again after a correction): deterministic removal of internal ids and background tags,
  then, when presentation issues remain, one copy-editor rewrite whose output is accepted only if it adds no number,
  identifier or link and loses no citation. The final text replaces the streamed one.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ...tools.registry import ToolResult
from ...writer.editor import EDITOR_SYSTEM_PROMPT, accept_edit, build_editor_request, guard_view
from ...writer.facts import compute_ode_facts
from ...writer.genui import build_answer_ui, sanitize_ui_blocks
from ...writer.lint import clean_presentation, presentation_issues
from ...writer.nbody_facts import compute_nbody_facts
from ...writer.number_facts import compute_number_facts
from ...writer.outline import outline_text, task_outline
from ...writer.pde_facts import compute_pde_facts
from ...writer.poly_facts import compute_poly_facts
from ...writer.roots_facts import compute_roots_facts
from ...writer.system_facts import compute_system_facts
from ..result_keys import COMPUTED_RESULTS
from .context import RunContext, orchestrator_module

logger = logging.getLogger(__name__)

FACTS_TIMEOUT_S = 45.0
EDITOR_TIMEOUT_S = 180.0
# Issue kinds that need a rewrite; ids and background tags are removed deterministically.
_REWRITE_KINDS = frozenset({"jargon", "raw_math", "outline", "precision"})
_DETERMINISTIC_MODELS = frozenset({"verified_computation", ""})


def facts_cover_question(tool_results: dict[str, Any]) -> bool:
    """Whether the code-computed results already answer the question's mathematics with checks: an exact solution
    that satisfied the equation and every initial condition, plus each requested table and RK4 comparison. The
    mathematics agent would only repeat that work (four model calls, about a minute)."""
    res = tool_results.get(COMPUTED_RESULTS)
    data = res.data if res is not None and getattr(res, "success", False) and isinstance(res.data, dict) else None
    if not data or not data.get("exact_solution_latex"):
        return False
    checks = data.get("checks") or []
    if len(checks) < 2 or not all(c.get("passed") for c in checks):
        return False
    requested = data.get("requested") or {}
    if requested.get("points") and not data.get("table"):
        return False
    return not (requested.get("rk4") and not data.get("rk4"))


def computations_cover_question(tool_results: dict[str, Any]) -> bool:
    """Whether code already computed and checked the question's computations: the solved initial-value problem of
    facts_cover_question, or finite number-theory results each verified a second way (tribos.writer.number_facts).
    The mathematics agent, the symbolic solver and a tool plan would only compute them again; the question's other
    parts (the status of an open problem) are still searched and checked against sources."""
    if facts_cover_question(tool_results):
        return True
    res = tool_results.get(COMPUTED_RESULTS)
    data = res.data if res is not None and getattr(res, "success", False) and isinstance(res.data, dict) else None
    if not data or data.get("kind") not in ("number_theory_finite", "nbody_gravity", "polynomial_analysis", "polynomial_roots",
                                            "dynamical_system", "pde_heat", "pde_poisson", "construction_search") \
            or not data.get("parameters"):
        return False
    checks = data.get("checks") or []
    return bool(checks) and all(c.get("passed") for c in checks)


def _question(run: RunContext) -> str:
    return run.clean_query or run.resolved_query or run.query or ""


async def compute_results(run: RunContext) -> None:
    """The user's outline and the code-computed results for the question, before the first draft."""
    question = _question(run)
    run.answer_outline = task_outline(question)
    try:
        # A gravitational N-body problem stated in full is integrated by code (tribos.writer.nbody_facts).
        data = await asyncio.wait_for(asyncio.to_thread(compute_nbody_facts, question), FACTS_TIMEOUT_S)
        if not data:
            # The 1-D heat equation with a manufactured (sine) solution: two schemes and a grid refinement study.
            data = await asyncio.wait_for(asyncio.to_thread(compute_pde_facts, question), FACTS_TIMEOUT_S)
        if not data:
            # Two or more stated (or named) first-order equations: integrated by two methods, invariants checked.
            data = await asyncio.wait_for(asyncio.to_thread(compute_system_facts, question), FACTS_TIMEOUT_S)
        if not data:
            data = await asyncio.wait_for(asyncio.to_thread(compute_ode_facts, question), FACTS_TIMEOUT_S)
        if not data:
            # Finite number theory (Collatz orbits, Goldbach partitions, prime counts), run and verified by code.
            data = await asyncio.wait_for(asyncio.to_thread(compute_number_facts, question), FACTS_TIMEOUT_S)
        if not data:
            # The real roots of a stated polynomial: exact Sturm count, rational isolating intervals, residuals.
            data = await asyncio.wait_for(asyncio.to_thread(compute_roots_facts, question), FACTS_TIMEOUT_S)
        if not data:
            # A stated real polynomial (nonnegativity, minimum, sums of squares): sampled, minimised, checked exactly.
            data = await asyncio.wait_for(asyncio.to_thread(compute_poly_facts, question), FACTS_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a missing fact never blocks the answer
        logger.info("Computed results skipped: %s", exc)
        return
    if not data:
        # A construction problem with an exact scorer (Golomb rulers, cap sets, ...): evolutionary program search.
        from .construct_stage import run_construct

        data = await run_construct(run, question)
    if not data or not (data.get("exact_solution_latex") or data.get("parameters") or data.get("rk4")):
        return
    run.tool_results[COMPUTED_RESULTS] = ToolResult(success=True, tool_name=COMPUTED_RESULTS, data=data)
    run.execution_artifacts[COMPUTED_RESULTS] = data
    ui = build_answer_ui(data)
    if ui is not None:
        run.execution_artifacts["answer_ui"] = ui  # the results panel the client renders above the answer
        # Sent now, before drafting: the panel is on screen before the answer text, so nothing shifts later.
        await run.send({"type": "answer_ui", "ui": ui})
    parts = []
    if data.get("exact_solution_latex"):
        parts.append("exact solution checked by substitution")
    if data.get("table"):
        parts.append(f"{len(data['table'])} requested values")
    if data.get("rk4"):
        parts.append(f"RK4 comparison (max error {data['rk4'].get('max_abs_error')})")
    if data.get("kind") == "number_theory_finite":
        checks = data.get("checks") or []
        parts.append(f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} finite computations verified twice")
    if data.get("kind") == "pde_heat":
        checks = data.get("checks") or []
        parts.append(f"heat equation solved on five grids by two schemes; "
                     f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} convergence checks passed")
    if data.get("kind") == "dynamical_system":
        checks = data.get("checks") or []
        parts.append(f"{len(data.get('states') or [])}-variable system integrated by two methods"
                     f"{' (stiff solvers)' if data.get('stiff') else ''}; "
                     f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} checks passed")
    if data.get("kind") == "polynomial_roots":
        checks = data.get("checks") or []
        parts.append(f"{data.get('count')} real roots isolated exactly in Python (Sturm sequence, rational intervals); "
                     f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} checks passed")
    if data.get("kind") == "polynomial_analysis":
        checks = data.get("checks") or []
        parts.append(f"polynomial sampled, minimised and checked exactly in Python; "
                     f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} checks passed")
    if data.get("kind") == "nbody_gravity":
        checks = data.get("checks") or []
        span = f"{data['n_periods']} periods" if data.get("n_periods") else f"t = {data.get('t_end')}"
        parts.append(f"{data['n_bodies']} bodies integrated over {span} by two methods; "
                     f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} conservation and agreement checks passed")
    if data.get("kind") == "construction_search":
        parts.append(f"{data['problem']}: {len(data.get('history') or [])} programs scored exactly; {data['verdict']}")
    if data.get("kind") == "pde_poisson":
        parts.append(f"Poisson problem solved by finite elements on {len(data.get('refinement') or [])} meshes; "
                     f"observed order {data.get('observed_order')}")
    await run.emit("computed_results", title="Computed the requested values exactly", text=" · ".join(parts))


async def polish(run: RunContext, *, allow_rewrite: bool = True) -> None:
    """Make the answer read as an answer: deterministic clean-up, then at most one guarded copy-edit."""
    draft = run.candidate_response or ""
    if not draft.strip():
        return
    question = _question(run)
    outline = run.answer_outline or task_outline(question)
    contract = getattr(run, "output_contract", None)
    strict_form = bool(getattr(contract, "strict_form", False))
    text = clean_presentation(draft, question)
    # ```ui blocks the writer added: kept only when valid and every number in them is in the evidence.
    computed_res = run.tool_results.get(COMPUTED_RESULTS)
    evidence = " ".join([question, json.dumps(guard_view(computed_res.data if computed_res is not None else None),
                                              default=str)])
    text, ui_removed = sanitize_ui_blocks(text, evidence, run.execution_artifacts.get("answer_ui"))
    issues = [] if strict_form else presentation_issues(text, outline)
    record: dict[str, Any] = {"cleaned": text != draft, "issues_before": len(issues), "rewrite": "not needed",
                              "ui_blocks_removed": ui_removed}
    rewrite_issues = [i for i in issues if i.kind in _REWRITE_KINDS]
    if rewrite_issues and allow_rewrite and run.synthesis_model not in _DETERMINISTIC_MODELS:
        edited, why = await _copy_edit(run, question, text, rewrite_issues, outline)
        if edited is not None:
            after = presentation_issues(edited, outline)
            if len(after) < len(issues):
                text, record["rewrite"], record["issues_after"] = edited, "accepted", len(after)
            else:
                record["rewrite"] = f"rejected: no improvement ({len(after)} issues)"
        else:
            record["rewrite"] = f"skipped: {why}"
    elif rewrite_issues:
        record["rewrite"] = "skipped: deterministic answer or rewrite not allowed"
    run.presentation = {**run.presentation, **record}
    if text != draft:
        run.candidate_response = text
        run.streamed_draft = text
        await run.send({"type": "content_reset", "reason": "presentation"})
        await run.send({"type": "content_delta", "delta": text})


async def _copy_edit(run: RunContext, question: str, draft: str, issues: list[Any],
                     outline: list[tuple[str, str]]) -> tuple[str | None, str]:
    ao = orchestrator_module()
    computed_res = run.tool_results.get(COMPUTED_RESULTS)
    computed = computed_res.data if computed_res is not None and computed_res.success else None
    request = build_editor_request(question, draft, issues, outline_text(outline), computed)
    budget = getattr(run.agent_state, "budget", None) if run.agent_state is not None else None
    alloc = None
    if budget is not None:
        from .agent_rounds import generation_allocation

        alloc, why = generation_allocation(budget, "presentation", len(EDITOR_SYSTEM_PROMPT) + len(request), len(draft))
        if alloc is None:
            return None, why or "no budget for the copy edit"
    from langchain_core.messages import HumanMessage, SystemMessage

    await run.emit("presentation", title="Editing the answer for the reader", status="running")
    edited = ""
    try:
        llm_kwargs = dict(ao._edit_llm_kwargs(run.synthesis_model))
        if alloc is not None:
            llm_kwargs["max_tokens"] = alloc.output_cap
        llm = ao.get_llm(model_name=run.synthesis_model, api_key=run.api_key, **llm_kwargs)
        reply = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=EDITOR_SYSTEM_PROMPT), HumanMessage(content=request)]), EDITOR_TIMEOUT_S
        )
        edited = str(getattr(reply, "content", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - the cleaned draft stands
        await run.emit("presentation", title="Kept the answer as written (the edit failed)", status="done")
        return None, f"the editor call failed ({type(exc).__name__})"
    finally:
        if alloc is not None and budget is not None:
            budget.settle(alloc, output_chars=len(edited) or None)
    ok, why = accept_edit(question, draft, edited, computed)
    await run.emit("presentation", title="Edited the answer for the reader" if ok else "Kept the answer as written",
                   text="" if ok else why[:200], status="done")
    return (edited, "") if ok else (None, why)


__all__ = ["compute_results", "computations_cover_question", "facts_cover_question", "polish"]
