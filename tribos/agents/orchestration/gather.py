"""Stages 1-3: evidence sources, computational tools (Calcula, Dynamis, Physis, Archivon), execution artifacts and hypothesis
prioritization."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from ...sources import EvidenceSource, SourceRunState
from ...tools.registry import ErrorType, ToolResult
from .. import query_planner
from .context import RunContext, logger, orchestrator_module


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

        stage1_tasks.append(tracked("archivon", "Archivon", run_archivon()))
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

        stage1_tasks.append(tracked("websurfer", "WebSurfer", run_websurfer()))
        task_names.append("websurfer")
        selected_agents.append("WebSurfer")

    # 1.4 Physis Task (Physical Constants / Units / Reference Data)
    if ctx.should_run("physis"):
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
    if "archivon" in tool_results and "lithoscribe" not in tool_results:
        tool_results["lithoscribe"] = tool_results["archivon"]
    run.task_names = task_names


async def run_computations(run: RunContext) -> None:
    """Stage 2: computational modeling and calculation (Calcula sandboxed compute, Dynamis ODE simulation)."""
    orchestrator_module()
    orch = run.orch
    ctx, registry = run.ctx, run.registry
    steps, selected_agents, tool_results, title_ctx = run.steps, run.selected_agents, run.tool_results, run.title_ctx
    emit, record, tracked = run.emit, run.record, run.tracked

    # -------------------------------------------------------------
    # STAGE 2: COMPUTATIONAL MODELING & CALCULATION (Calcula & Dynamis)
    # -------------------------------------------------------------
    stage2_tasks: list[Coroutine[Any, Any, Any]] = []
    stage2_names: list[str] = []

    # 2.1 Calcula PAL-style sandboxed scientific computation
    if ctx.should_run("calcula"):
        async def run_calcula() -> ToolResult:
            steps.append({"agent": "Calcula", "role": "assistant", "action": "Sandboxed Python Computation"})
            ds_ids = [ctx.dataset_attachment.id] if getattr(ctx, "dataset_attachment", None) is not None else []
            code = getattr(ctx, "computation_code", None)
            if not code:
                code = (
                    f"# PAL scientific computation for: {ctx.clean_query[:100]}\n"
                    "import numpy as np\n"
                    "import scipy\n"
                    "result = {'status': 'completed'}\n"
                )
            tool_name = "calcula_run_python" if registry.get_entry("calcula_run_python") is not None else "analysis_run_python"
            return await registry.execute(tool_name, code=code, dataset_ids=ds_ids)

        stage2_tasks.append(tracked("calcula", "Calcula", run_calcula()))
        stage2_names.append("calcula")
        selected_agents.append("Calcula")

    # 2.2 Dynamis ODE simulation and parameter scan
    from tribos.dynamis import ODE_PRESETS

    def _resolve_dynamis_preset(name_or_query: str) -> str:
        q = (name_or_query or "").lower()
        for p in ODE_PRESETS:
            if p in q or p.replace("_", " ") in q:
                return p
        if "damped" in q:
            return "damped_oscillator"
        if "oscillator" in q or "harmonic" in q:
            return "harmonic_oscillator"
        if "lotka" in q or "predator" in q or "prey" in q:
            return "lotka_volterra"
        if "lorenz" in q:
            return "lorenz"
        if "sir" in q or "epidemic" in q:
            return "sir"
        if "van der pol" in q or "vanderpol" in q:
            return "van_der_pol"
        if "pendulum" in q:
            return "pendulum"
        if "circuit" in q:
            return "rlc_circuit" if ("rlc" in q or "inductor" in q) else "rc_circuit"
        return "damped_oscillator"

    sim_plan = orch._simulation_plan(ctx) if (ctx.should_run("dynamis") or ctx.should_run("vivarix")) else None
    if sim_plan is not None and getattr(ctx.simulation_constraints, "simulation_forbidden", False):
        sim_plan = None
    requested_plan = sim_plan

    if sim_plan is not None:
        selected_agents.append("Dynamis")
        plan_errors = orch._plan_errors(sim_plan)
        if plan_errors:
            msg = "; ".join(str(e.get("message") or e.get("code")) for e in plan_errors)
            tool_name = "dynamis_parameter_scan" if sim_plan.action == "parameter_scan" else "dynamis_simulate_ode"
            tool_results["dynamis"] = ToolResult(
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
            tool_results["vivarix"] = tool_results["dynamis"]
            await emit("dynamis", "Simulation request rejected before running", msg[:300], status="error", agent="Dynamis")
            record("note_step", "simulation_validation", sim_plan.model_dump(), {"errors": plan_errors})
            sim_plan = None

    if sim_plan is not None:
        preset_key = _resolve_dynamis_preset(sim_plan.system_name or ctx.clean_query)
        duration = float(sim_plan.duration_seconds or 10.0)
        intervals = max(5, min(1000, sim_plan.intervals or 100))
        title_ctx["model"] = preset_key
        title_ctx["scan_parameter"] = sim_plan.scan_parameter or "a parameter"

        if sim_plan.action == "parameter_scan":
            async def run_dynamis_scan() -> ToolResult:
                steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis Parameter Scan ({preset_key})"})
                pdata = ODE_PRESETS.get(preset_key, ODE_PRESETS["harmonic_oscillator"])
                param = sim_plan.scan_parameter or list(pdata.get("parameters", {}).keys())[0]
                s_range = (
                    float(sim_plan.scan_start if sim_plan.scan_start is not None else 0.1),
                    float(sim_plan.scan_end if sim_plan.scan_end is not None else 2.0),
                )
                n_pts = max(2, min(50, sim_plan.scan_points or 10))
                if registry.get_entry("dynamis_parameter_scan") is not None:
                    res = await registry.execute(
                        "dynamis_parameter_scan",
                        rhs=pdata["rhs"],
                        initial_state=pdata["initial_state"],
                        parameter=param,
                        scan_range=s_range,
                        num_points=n_pts,
                        t_span=(0.0, duration),
                        base_parameters=pdata.get("parameters"),
                    )
                else:
                    res = await registry.execute(
                        "vivarix_parameter_scan",
                        biomodel_id=sim_plan.biomodel_id or "BIOMD0000000010",
                        parameter_name=param,
                        start_val=s_range[0],
                        end_val=s_range[1],
                        num_steps=n_pts,
                    )
                return res

            stage2_tasks.append(tracked("dynamis_scan", "Dynamis", run_dynamis_scan()))
            stage2_names.append("dynamis_scan")
        else:
            async def run_dynamis() -> ToolResult:
                steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis ODE Simulation ({preset_key})"})
                if registry.get_entry("dynamis_simulate_ode") is not None:
                    res = await registry.execute(
                        "dynamis_simulate_ode",
                        model_name=preset_key,
                        t_span=(0.0, duration),
                        num_points=intervals,
                    )
                else:
                    res = await registry.execute(
                        "vivarix_simulate_time_course",
                        biomodel_id=sim_plan.biomodel_id or "BIOMD0000000010",
                        duration=duration,
                        intervals=intervals,
                    )
                return res

            stage2_tasks.append(tracked("dynamis", "Dynamis", run_dynamis()))
            stage2_names.append("dynamis")

            if sim_plan.action == "steady_state":
                async def run_dynamis_steady_state() -> ToolResult:
                    steps.append({"agent": "Dynamis", "role": "assistant", "action": f"Dynamis Equilibrium Root Finding ({preset_key})"})
                    if registry.get_entry("dynamis_find_equilibrium") is not None:
                        res = await registry.execute(
                            "dynamis_find_equilibrium",
                            model_name=preset_key,
                        )
                    else:
                        res = await registry.execute(
                            "vivarix_compute_steady_state",
                            biomodel_id=sim_plan.biomodel_id or "BIOMD0000000010",
                        )
                    return res

                stage2_tasks.append(tracked("dynamis_steady", "Dynamis", run_dynamis_steady_state()))
                stage2_names.append("dynamis_steady")

    if stage2_tasks:
        stage2_results = await asyncio.gather(*stage2_tasks, return_exceptions=True)
        for name, res in zip(stage2_names, stage2_results, strict=False):
            if isinstance(res, Exception):
                tool_results[name] = ToolResult(
                    success=False,
                    tool_name=name,
                    error=str(res),
                    error_type=ErrorType.INTERNAL_ERROR,
                )
            else:
                tool_results[name] = res
        if "dynamis" in tool_results and "vivarix" not in tool_results:
            tool_results["vivarix"] = tool_results["dynamis"]
        if "dynamis_scan" in tool_results and "vivarix_scan" not in tool_results:
            tool_results["vivarix_scan"] = tool_results["dynamis_scan"]
    run.requested_plan = requested_plan


def collect_artifacts(run: RunContext) -> None:
    """Execution artifacts from the tool results, the evidence sources and the registered artifact builders."""
    ao = orchestrator_module()
    ctx, tool_results, execution_artifacts = run.ctx, run.tool_results, run.execution_artifacts
    active_sources, merge_artifact = run.active_sources, run.merge_artifact

    # Collect execution artifacts
    if tool_results.get("dynamis") and tool_results["dynamis"].success and tool_results["dynamis"].data:
        execution_artifacts["dynamis"] = dict(tool_results["dynamis"].data)
        execution_artifacts["vivarix"] = execution_artifacts["dynamis"]

    if tool_results.get("dynamis_steady") and tool_results["dynamis_steady"].data:
        execution_artifacts.setdefault("dynamis", {})["steady_state"] = dict(tool_results["dynamis_steady"].data)
        execution_artifacts.setdefault("vivarix", {})["steady_state"] = dict(tool_results["dynamis_steady"].data)
    elif tool_results.get("vivarix") and tool_results["vivarix"].success and tool_results["vivarix"].data:
        execution_artifacts["vivarix"] = dict(tool_results["vivarix"].data)

    if tool_results.get("dynamis_scan") and tool_results["dynamis_scan"].data:
        execution_artifacts["dynamis_scan"] = dict(tool_results["dynamis_scan"].data)
        execution_artifacts["vivarix_scan"] = execution_artifacts["dynamis_scan"]
    elif tool_results.get("vivarix_scan") and tool_results["vivarix_scan"].data:
        execution_artifacts["vivarix_scan"] = dict(tool_results["vivarix_scan"].data)

    if tool_results.get("calcula") and tool_results["calcula"].success and tool_results["calcula"].data:
        execution_artifacts["calcula"] = dict(tool_results["calcula"].data)

    if tool_results.get("physis") and tool_results["physis"].success and tool_results["physis"].data:
        execution_artifacts["physis"] = dict(tool_results["physis"].data)

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
    try:
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
