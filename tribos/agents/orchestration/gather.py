"""Stages 1-3: evidence sources, computational tools (Calcula, Dynamis, Physis, Archivon), execution artifacts and hypothesis
prioritization."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Coroutine
from typing import Any

from ...sources import EvidenceSource, SourceRunState
from ...tools.registry import ErrorType, ToolResult
from .. import query_planner
from ..result_keys import (
    ARCHIVON,
    AXIOM,
    CALCULA,
    DYNAMIS,
    DYNAMIS_EQUILIBRIUM,
    DYNAMIS_SCAN,
    is_alias_duplicate,
)
from .context import RunContext, logger, orchestrator_module

STATED_ODE_MAX_POINTS = 4001  # samples of a stated-ODE trajectory, at most
SKIP_POLL_S = 0.25

# Names a question uses for each Dynamis preset (tribos.dynamis.ODE_PRESETS), besides the preset key itself.
_PRESET_PHRASES: dict[str, tuple[str, ...]] = {
    "damped_oscillator": ("damped oscillator", "damped harmonic oscillator", "damped spring mass", "damped mass spring",
                          "damped spring-mass", "damped mass-spring"),
    "harmonic_oscillator": ("harmonic oscillator", "simple harmonic oscillator", "undamped oscillator",
                            "spring mass system", "mass spring system", "spring-mass system", "mass-spring system"),
    "lotka_volterra": ("lotka volterra", "lotka-volterra", "predator prey", "predator-prey"),
    "lorenz": ("lorenz", "lorenz attractor", "lorenz system", "lorenz equations"),
    "sir": ("sir model", "sir epidemic", "sir system", "sir equations", "epidemic model"),
    "van_der_pol": ("van der pol", "van der pol oscillator", "vanderpol"),
    "pendulum": ("pendulum", "simple pendulum", "nonlinear pendulum"),
    "rc_circuit": ("rc circuit",),
    "rlc_circuit": ("rlc circuit", "series rlc"),
}


def _preset_patterns() -> list[tuple[re.Pattern[str], str]]:
    from tribos.dynamis import ODE_PRESETS

    phrases: dict[str, str] = {}
    for key in ODE_PRESETS:
        phrases[key] = key
        phrases[key.replace("_", " ")] = key
        for phrase in _PRESET_PHRASES.get(key, ()):
            phrases[phrase] = key
    # Longest phrase first, so "damped harmonic oscillator" is never read as "harmonic oscillator".
    ordered = sorted(phrases.items(), key=lambda kv: -len(kv[0]))
    return [(re.compile(rf"(?<![\w-]){re.escape(p).replace(r'\ ', r'[\s_-]+')}(?![\w-])", re.I), k) for p, k in ordered]


def resolve_dynamis_preset(*texts: str | None) -> str | None:
    """The Dynamis preset a system name or question names, matched on whole words, longest name first (LOG-5).

    The texts are tried in order (the planned system name, the question's system entity, the question). None when
    nothing names a preset: then no preset runs, since simulating another system would answer another question."""
    patterns = _preset_patterns()
    for text in texts:
        if not text:
            continue
        for rx, key in patterns:
            if rx.search(text):
                return key
    return None


async def skippable(run: RunContext, what: str, name: str, coro: Coroutine[Any, Any, ToolResult]) -> ToolResult:
    """Run coro unless the user skips `what` (RunControl.request_skip) first: then it is cancelled and a result marked
    skipped_by_user stands in, which no failure count treats as a failed source."""
    task = asyncio.ensure_future(coro)
    control = run.control
    if control is None:
        return await task
    while not task.done():
        if control.is_skipped(what):
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - the cancelled search's outcome is discarded
                pass
            return ToolResult(success=False, tool_name=name, error="Skipped at the user's request",
                              metadata={"skipped_by_user": True})
        await asyncio.wait({task}, timeout=SKIP_POLL_S)
    return task.result()


async def run_evidence(run: RunContext) -> None:
    """Stage 1: the built-in evidence tools and the registered evidence sources, run concurrently."""
    ao = orchestrator_module()
    ctx, registry, pending, resolved_query = run.ctx, run.registry, run.pending, run.resolved_query
    steps, selected_agents, tool_results = run.steps, run.selected_agents, run.tool_results
    active_sources, tracked = run.active_sources, run.tracked

    # -------------------------------------------------------------
    # STAGE 1: PARALLEL EVIDENCE GATHERING (LLMCompiler Stage 1)
    # -------------------------------------------------------------
    stage1_tasks: list[Coroutine[Any, Any, Any]] = []
    task_names: list[str] = []

    # The search plan (deterministic, upgraded by the planner model when it arrives in time) drives both the
    # literature and the web search; it is resolved once and shared.
    search_plan_task: asyncio.Future[Any] | None = None
    if ctx.should_run("archivon") or ctx.should_run("lithoscribe") or ctx.should_run("websurfer"):
        search_plan_task = asyncio.ensure_future(query_planner.finalize_search_plan(ctx))
        pending["search_plan_task"] = search_plan_task
    else:
        query_planner.cancel_planner(ctx)

    # 1.2 Archivon Task (Scientific Literature Retrieval)
    if ctx.should_run("archivon") or ctx.should_run("lithoscribe"):
        async def run_archivon() -> ToolResult:
            steps.append({"agent": "Archivon", "role": "assistant", "action": "Scientific Literature Retrieval"})
            plan = await search_plan_task if search_plan_task is not None else None
            req = ao.literature_request(ctx, resolved_query, plan)
            tool_name = "archivon_literature_search" if registry.get_entry("archivon_literature_search") is not None else "lithoscribe_literature_synthesis"
            return await registry.execute(tool_name, **req)

        stage1_tasks.append(tracked("archivon", "Archivon", skippable(run, "search", "archivon", run_archivon())))
        task_names.append("archivon")
        selected_agents.append("Archivon")

    # 1.3 WebSurfer Task (if enabled)
    if ctx.should_run("websurfer"):
        async def run_websurfer() -> ToolResult:
            steps.append({"agent": "WebSurfer", "role": "assistant", "action": "Live Search"})
            web_query = ctx.web_query()
            if not ctx.is_simulation_intent and search_plan_task is not None:
                web_query = (await search_plan_task).web_query or web_query
            return await registry.execute("websurfer_search", query=web_query, max_results=3)

        stage1_tasks.append(tracked("websurfer", "WebSurfer", skippable(run, "search", "websurfer", run_websurfer())))
        task_names.append("websurfer")
        selected_agents.append("WebSurfer")

    # 1.4 Physis Task (Physical Constants / Units / Reference Data): a lookup needs named constants or materials; with
    # neither, searching the reference tables with the whole question only returns noise (unit checks run via the plan).
    # The materials lookup is an online database (Search off skips it); the constants tables are local.
    if ctx.should_run("physis") and (getattr(ctx, "constants", None)
                                     or (getattr(ctx, "materials", None) and getattr(ctx, "enable_web_search", True))):
        async def run_physis() -> ToolResult:
            steps.append({"agent": "Physis", "role": "assistant", "action": "Physical Reference & Constants Lookup"})
            if getattr(ctx, "constants", None):
                q = " ".join(c.label for c in ctx.constants[:3])
                return await registry.execute("physis_constants", query=q)
            elif getattr(ctx, "materials", None):
                q = " ".join(m.label for m in ctx.materials[:3])
                return await registry.execute("physis_materials", query=q)
            else:
                return await registry.execute("physis_constants", query=resolved_query)

        stage1_tasks.append(tracked("physis", "Physis", run_physis()))
        task_names.append("physis")
        selected_agents.append("Physis")

    # 1.5 Registered evidence sources
    source_state = SourceRunState(registry, ctx)
    for src in active_sources:
        async def run_source(s: EvidenceSource = src) -> ToolResult:
            steps.append({"agent": s.agent, "role": "assistant", "action": s.action})
            return await s.run(ctx, registry, source_state)

        try:
            running = src.running_title(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s running title failed: %s", src.key, exc)
            running = None
        stage1_tasks.append(
            tracked(
                src.key,
                src.agent,
                run_source(),
                running_title=running,
                describer=lambda r, s=src: s.describe(r, ctx),
            )
        )
        task_names.append(src.key)
        selected_agents.append(src.agent)

    stage1_results = await asyncio.gather(*stage1_tasks, return_exceptions=True)
    query_planner.cancel_planner(ctx)
    for name, res in zip(task_names, stage1_results, strict=False):
        if isinstance(res, Exception):
            tool_results[name] = ToolResult(
                success=False,
                tool_name=name,
                error=str(res),
                error_type=ErrorType.INTERNAL_ERROR,
            )
        else:
            tool_results[name] = res
    if ARCHIVON in tool_results and "lithoscribe" not in tool_results:
        tool_results["lithoscribe"] = tool_results[ARCHIVON]
    run.task_names = task_names


async def run_computations(run: RunContext) -> None:
    """Stage 2: computation (Axiom symbolic solve, Calcula sandboxed code or dataset inspection, Dynamis ODEs)."""
    orchestrator_module()
    orch = run.orch
    ctx, registry = run.ctx, run.registry
    steps, selected_agents, tool_results, title_ctx = run.steps, run.selected_agents, run.tool_results, run.title_ctx
    emit, record, tracked, notes = run.emit, run.record, run.tracked, run.gather_notes
    classic = run.agent_state is None

    # -------------------------------------------------------------
    # STAGE 2: COMPUTATIONAL MODELING & CALCULATION (Axiom, Calcula & Dynamis)
    # -------------------------------------------------------------
    stage2_tasks: list[Coroutine[Any, Any, Any]] = []
    stage2_names: list[str] = []

    # 2.1 Axiom: the verified math agent on a question it can parse (an equation, ODE, integral, limit, ...) (LOG-3).
    # Agentic frameworks route mathematics through their own math agent and planned tool calls instead.
    if classic and ctx.should_run(AXIOM) and registry.get_entry("axiom_solve_problem") is not None:
        from tribos.axiom.problem import parse_problem

        if parse_problem(ctx.clean_query).kind != "unknown":
            async def run_axiom() -> ToolResult:
                steps.append({"agent": "Axiom", "role": "assistant", "action": "Verified Symbolic Solution"})
                return await registry.execute("axiom_solve_problem", problem=ctx.clean_query[:4000])

            stage2_tasks.append(tracked(AXIOM, "Axiom", run_axiom()))
            stage2_names.append(AXIOM)
            selected_agents.append("Axiom")

    # 2.2 Calcula: sandboxed Python needs code to run. No stage plans code in the classic pipeline, so an attached
    # dataset is inspected (schema and summary statistics) and otherwise nothing runs: a placeholder script would
    # be reported as a computation that computed nothing (LOG-4).
    if ctx.should_run(CALCULA):
        code = getattr(ctx, "computation_code", None)
        dataset = getattr(ctx, "dataset_attachment", None)
        if code:
            async def run_calcula() -> ToolResult:
                steps.append({"agent": "Calcula", "role": "assistant", "action": "Sandboxed Python Computation"})
                ds_ids = [dataset.id] if dataset is not None else []
                name = "calcula_run_python" if registry.get_entry("calcula_run_python") is not None else "analysis_run_python"
                return await registry.execute(name, code=code, dataset_ids=ds_ids)

            calcula_task: Coroutine[Any, Any, Any] | None = tracked(CALCULA, "Calcula", run_calcula())
        elif dataset is not None and registry.get_entry("calcula_describe_dataset") is not None:
            async def run_calcula_describe() -> ToolResult:
                steps.append({"agent": "Calcula", "role": "assistant", "action": "Dataset Inspection"})
                return await registry.execute("calcula_describe_dataset", dataset_id=dataset.id)

            calcula_task = tracked(CALCULA, "Calcula", run_calcula_describe())
        else:
            calcula_task = None
            notes.append(
                "No sandboxed Python computation (Calcula) was run for this question; do not present any value as "
                "computed in a sandbox."
            )
        if calcula_task is not None:
            stage2_tasks.append(calcula_task)
            stage2_names.append(CALCULA)
            selected_agents.append("Calcula")

    # 2.3 Dynamis ODE simulation, equilibrium and parameter scan
    from tribos.dynamis import ODE_PRESETS

    sim_plan = orch._simulation_plan(ctx) if (ctx.should_run(DYNAMIS) or ctx.should_run("vivarix")) else None
    if sim_plan is not None and getattr(ctx.simulation_constraints, "simulation_forbidden", False):
        sim_plan = None
    requested_plan = sim_plan

    if sim_plan is not None:
        selected_agents.append("Dynamis")
        plan_errors = orch._plan_errors(sim_plan)
        if plan_errors:
            msg = "; ".join(str(e.get("message") or e.get("code")) for e in plan_errors)
            tool_name = "dynamis_parameter_scan" if sim_plan.action == "parameter_scan" else "dynamis_simulate_ode"
            tool_results[DYNAMIS] = ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Simulation request rejected before execution: {msg}",
                error_type=ErrorType.VALIDATION_ERROR,
                metadata={
                    "validation_code": plan_errors[0].get("code"),
                    "validation_errors": plan_errors,
                    "requested_operation": sim_plan.action,
                    "requested_duration_seconds": sim_plan.duration_seconds,
                },
            )
            tool_results["vivarix"] = tool_results[DYNAMIS]
            await emit("dynamis", "Simulation request rejected before running", msg[:300], status="error", agent="Dynamis")
            record("note_step", "simulation_validation", sim_plan.model_dump(), {"errors": plan_errors})
            sim_plan = None

    # A question that states its own ODE is simulated as stated (equation, given values, initial conditions); a named
    # preset with default parameters would be a different system. When the stated ODE cannot be converted, no preset
    # runs in its place (the planner can still simulate it), so a wrong system is never reported as the answer.
    stated: dict[str, Any] | None = None
    spec: Any = None
    if sim_plan is not None and sim_plan.action != "parameter_scan":
        from tribos.axiom.problem import parse_problem
        from tribos.dynamis.stated_ode import stated_ode_system

        spec = parse_problem(ctx.clean_query)
        if spec.kind == "ode" and spec.expression:
            stated = stated_ode_system(spec.expression, spec.func or "", spec.ics)
            if stated is None:
                await emit("dynamis", "Simulation left to the plan",
                           "the stated ODE could not be converted for direct integration", agent="Dynamis")
                sim_plan = None

    preset_key: str | None = None
    if sim_plan is not None and not stated:
        # The user's own words first (an entity's mention, the question), then the resolved labels: a lexicon label
        # can be coarser than the words ("damped oscillator" labelled harmonic_oscillator). A follow-up's system
        # ("Now simulate it for 50 s") comes from the previous turn as an entity and as ctx.system_name.
        systems = getattr(ctx, "systems", None) or []
        preset_key = resolve_dynamis_preset(
            sim_plan.system_name, *(e.mention for e in systems), ctx.clean_query,
            *(e.label for e in systems), getattr(ctx, "system_name", None),
        )
        if preset_key is None:
            # Nothing the question names is a system Dynamis can integrate: no simulation runs (never a stand-in).
            presets = ", ".join(k.replace("_", " ") for k in ODE_PRESETS)
            reason = (
                "BioModels/SBML simulation is not available in Tribos. " if sim_plan.biomodel_id else ""
            ) + (
                "No system Dynamis can simulate was identified in the question, so no simulation was run. State the "
                f"ODE system (for example dx/dt = -2*x, x(0) = 1) or name one of the presets: {presets}."
            )
            await emit("dynamis", "No simulation run: the system to simulate was not identified", reason[:300],
                       status="error", agent="Dynamis")
            if classic:
                key = DYNAMIS_SCAN if sim_plan.action == "parameter_scan" else DYNAMIS
                tool_results[key] = ToolResult(
                    success=False,
                    tool_name="dynamis_parameter_scan" if key == DYNAMIS_SCAN else "dynamis_simulate_ode",
                    error=reason,
                    error_type=ErrorType.VALIDATION_ERROR,
                    metadata={"reason_code": "MODEL_REQUIRED", "requested_operation": sim_plan.action},
                )
            else:
                notes.append(reason)
            sim_plan = None

    if sim_plan is not None:
        duration = float(sim_plan.duration_seconds or 10.0)
        intervals = max(5, min(1000, sim_plan.intervals or 100))
        if stated:
            # A stated ODE is reported as the answer: sample it densely (100 per second, at least 1001 points) so peaks,
            # minima and maxima are the trajectory's own, not clipped between coarse samples.
            intervals = max(intervals, min(STATED_ODE_MAX_POINTS, max(1001, round(100 * duration) + 1)))
        label = "stated_ode" if stated else str(preset_key)
        title_ctx["model"] = "the stated ODE" if stated else label
        title_ctx["scan_parameter"] = sim_plan.scan_parameter or "a parameter"
        system: dict[str, Any] = (
            {"rhs": stated["rhs"], "initial_state": stated["initial_state"], "parameters": None} if stated
            else dict(ODE_PRESETS[label])
        )

        if sim_plan.action == "parameter_scan":
            async def run_dynamis_scan() -> ToolResult:
                steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis Parameter Scan ({label})"})
                param = sim_plan.scan_parameter or list((system.get("parameters") or {}).keys())[0]
                s_range = (
                    float(sim_plan.scan_start if sim_plan.scan_start is not None else 0.1),
                    float(sim_plan.scan_end if sim_plan.scan_end is not None else 2.0),
                )
                return await registry.execute(
                    "dynamis_parameter_scan",
                    rhs=system["rhs"],
                    initial_state=system["initial_state"],
                    parameter=param,
                    scan_range=s_range,
                    num_points=max(2, min(50, sim_plan.scan_points or 10)),
                    t_span=(0.0, duration),
                    base_parameters=system.get("parameters"),
                )

            stage2_tasks.append(tracked(DYNAMIS_SCAN, "Dynamis", run_dynamis_scan()))
            stage2_names.append(DYNAMIS_SCAN)
        else:
            async def run_dynamis() -> ToolResult:
                steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis ODE Simulation ({label})"})
                if stated:
                    res = await registry.execute(
                        "dynamis_simulate_ode",
                        rhs=stated["rhs"],
                        initial_state=stated["initial_state"],
                        t_span=(0.0, duration),
                        num_points=intervals,
                    )
                    if res.success and isinstance(res.data, dict):
                        from tribos.dynamis.stated_ode import stated_units

                        units = stated_units(ctx.clean_query, spec.func or "", list(stated.get("state_names") or []))
                        if units:
                            res.data["units"] = units  # from the question's own values; the charts label axes with them
                    return res
                return await registry.execute(
                    "dynamis_simulate_ode", model_name=label, t_span=(0.0, duration), num_points=intervals
                )

            stage2_tasks.append(tracked(DYNAMIS, "Dynamis", run_dynamis()))
            stage2_names.append(DYNAMIS)

            if sim_plan.action == "steady_state":
                # The fixed point of the same system, from its initial state as the guess (BRK-3).
                async def run_dynamis_equilibrium() -> ToolResult:
                    steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis Equilibrium Root Finding ({label})"})
                    return await registry.execute(
                        "dynamis_equilibrium",
                        rhs=system["rhs"],
                        guess=system["initial_state"],
                        parameters=system.get("parameters"),
                    )

                stage2_tasks.append(tracked(DYNAMIS_EQUILIBRIUM, "Dynamis", run_dynamis_equilibrium()))
                stage2_names.append(DYNAMIS_EQUILIBRIUM)

    if stage2_tasks:
        stage2_results = await asyncio.gather(*stage2_tasks, return_exceptions=True)
        for name, res in zip(stage2_names, stage2_results, strict=False):
            if isinstance(res, Exception):
                res = ToolResult(success=False, tool_name=name, error=str(res), error_type=ErrorType.INTERNAL_ERROR)
            if name == AXIOM and not res.success:
                # An opportunistic symbolic attempt that found no answer is a gap to state, not a failed source.
                notes.append(f"Axiom could not solve the question symbolically ({(res.error or 'no answer')[:200]}); "
                             "no symbolic solution is in the evidence.")
                continue
            tool_results[name] = res
        if DYNAMIS in tool_results and "vivarix" not in tool_results:
            tool_results["vivarix"] = tool_results[DYNAMIS]
        if DYNAMIS_SCAN in tool_results and "vivarix_scan" not in tool_results:
            tool_results["vivarix_scan"] = tool_results[DYNAMIS_SCAN]
    run.requested_plan = requested_plan


def collect_artifacts(run: RunContext) -> None:
    """Execution artifacts from the tool results, the evidence sources and the registered artifact builders."""
    ao = orchestrator_module()
    ctx, tool_results, execution_artifacts = run.ctx, run.tool_results, run.execution_artifacts
    active_sources, merge_artifact = run.active_sources, run.merge_artifact

    def ok_data(key: str) -> dict[str, Any] | None:
        res = tool_results.get(key)
        return dict(res.data) if res is not None and res.success and isinstance(res.data, dict) and res.data else None

    # Collect execution artifacts ("vivarix" / "vivarix_scan" stay as aliases of the Dynamis artifacts for old readers)
    if (dyn := ok_data(DYNAMIS)) is not None:
        execution_artifacts[DYNAMIS] = dyn
        execution_artifacts["vivarix"] = dyn
    elif not is_alias_duplicate("vivarix", tool_results) and (viv := ok_data("vivarix")) is not None:
        execution_artifacts["vivarix"] = viv
    if (eq := ok_data(DYNAMIS_EQUILIBRIUM)) is not None:
        execution_artifacts.setdefault(DYNAMIS, {})["steady_state"] = eq
        execution_artifacts.setdefault("vivarix", execution_artifacts[DYNAMIS])
    if (scan := ok_data(DYNAMIS_SCAN)) is not None:
        execution_artifacts[DYNAMIS_SCAN] = scan
        execution_artifacts["vivarix_scan"] = scan
    for key in (CALCULA, "physis", AXIOM):
        if (data := ok_data(key)) is not None:
            execution_artifacts[key] = data

    successful_sources = [
        s for s in active_sources if tool_results.get(s.key) is not None and tool_results[s.key].success
    ]
    for src in successful_sources:
        try:
            art = src.artifact(tool_results[src.key])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source %s artifact failed: %s", src.key, exc)
            continue
        if art:
            merge_artifact(art[0], art[1])
    for builder in ao.get_artifact_builders():
        try:
            built = builder(tool_results, ctx) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Artifact builder failed: %s", exc)
            continue
        for key, value in built.items():
            merge_artifact(key, value)
    run.successful_sources = successful_sources


async def prioritize(run: RunContext) -> None:
    """Stage 3: evidence-weighted hypothesis prioritization (Discovery)."""
    ao = orchestrator_module()
    ctx, clean_query, tool_results, execution_artifacts = run.ctx, run.clean_query, run.tool_results, run.execution_artifacts
    emit = run.emit

    # -------------------------------------------------------------
    # STAGE 3: HYPOTHESIS PRIORITIZATION (DiscoveryAgent)
    # -------------------------------------------------------------
    # Target prioritization ranks molecular targets (OpenTargets associations, kinetic models, single-cell markers);
    # for a physics or engineering subject it would only invent a "regime hypothesis", so it does not run.
    molecular = bool(ctx.primary_gene is not None or ctx.genes or ctx.drugs or ctx.diseases)
    try:
        if not molecular:
            discovery_report = ao.DiscoveryHypothesisReport(
                inquiry=clean_query,
                primary_target=ctx.primary_target or "Unspecified",
                status="NOT_APPLICABLE",
                iterative_update_summary="The question names no molecular target; target prioritization does not apply.",
            )
        else:
            discovery_report = ao.DiscoveryEngine.prioritize_hypotheses(
                inquiry=clean_query,
                primary_target=ctx.primary_target,
                tool_results=tool_results,
                target_aliases=ctx.primary_aliases(),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hypothesis prioritization failed: %s", exc)
        discovery_report = ao.DiscoveryHypothesisReport(
            inquiry=clean_query,
            primary_target=ctx.primary_target or "Unspecified",
            status="INSUFFICIENT_EVIDENCE",
            iterative_update_summary=f"Prioritization unavailable ({type(exc).__name__}); no scores were generated.",
        )
    execution_artifacts["discovery"] = discovery_report.model_dump()

    if discovery_report.candidates:
        ranked = " · ".join(
            f"{c.target} ({c.composite_priority_score:.2f})" for c in discovery_report.candidates[:3]
        )
        await emit(
            "target_prioritization",
            title=(
                f"Ranked {len(discovery_report.candidates)} candidate "
                f"hypothes{'is' if len(discovery_report.candidates) == 1 else 'es'}"
            ),
            text=f"Evidence-weighted priority: {ranked}",
            agent="Discovery",
            extra={"top_candidate": discovery_report.candidates[0].target},
        )

    run.discovery_report = discovery_report
