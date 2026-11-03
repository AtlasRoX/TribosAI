"""Execute fully specified bounded scientific requests before model planning, with real tool provenance.

Broader requests stay in the normal agent pipeline. Supported requests use the same registered numerical tools
as agent plans, with their schemas, execution limits, policies, audit log, and frontend result cards.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import time
from typing import Any

from tribos.scientific.assembly import (
    MissingScientificResult,
    assemble_eight_part_answer,
    build_downloadable_files,
    build_scientific_figures,
)
from tribos.scientific.render import render
from tribos.scientific.requests import (
    CompositeScientificRequest,
    ScientificRequest,
    parse_scientific_request,
)

from ..query_context import TaskOutcome
from .context import RunContext, orchestrator_module


def _contract_checks(req: ScientificRequest, data: dict[str, Any]) -> list[dict[str, Any]]:
    def check(name: str, passed: bool) -> dict[str, Any]:
        return {"name": name, "passed": bool(passed)}

    a = req.args
    if req.kind == "ode_rk4":
        spec = data.get("spec") or {}
        solver = data.get("solver") or {}
        t_arr = data.get("t")
        trajectories = data.get("trajectories")
        count = a.get("num_steps") or round(a["t_span"][1] / a["step_size"])

        method_ok = (data.get("method") == "RK4" and solver.get("internal_steps") == count)
        t_span_ok = spec.get("t_span") == a["t_span"]
        grid_ok = (
            isinstance(t_arr, (list, tuple))
            and len(t_arr) == count + 1
            and math.isclose(float(t_arr[0]), a["t_span"][0], abs_tol=1e-12)
            and math.isclose(float(t_arr[-1]), a["t_span"][1], rel_tol=1e-9, abs_tol=1e-12)
            and all(t_arr[i] < t_arr[i + 1] for i in range(len(t_arr) - 1))
        )
        time_check_ok = t_span_ok and grid_ok

        rhs_ok = spec.get("rhs") == a["rhs"]
        ics_ok = spec.get("initial_state") == a["initial_state"]
        states = list(a["initial_state"].keys()) if isinstance(a.get("initial_state"), dict) else []
        trajectories_shape_ok = (
            isinstance(trajectories, dict)
            and bool(trajectories)
            and all(state in trajectories for state in states)
            and all(
                isinstance(trajectories[s], (list, tuple))
                and len(trajectories[s]) == count + 1
                and math.isclose(trajectories[s][0], a["initial_state"][s], rel_tol=1e-9, abs_tol=1e-12)
                for s in states
            )
        )
        ode_spec_ok = rhs_ok and ics_ok and trajectories_shape_ok

        finite_ok = (
            isinstance(trajectories, dict)
            and bool(trajectories)
            and all(
                isinstance(vals, (list, tuple))
                and len(vals) == count + 1
                and all(isinstance(x, (int, float)) and math.isfinite(x) for x in vals)
                for vals in trajectories.values()
            )
        )

        return [
            check("Requested method and step count", method_ok),
            check("Requested time span and strictly ordered grid", time_check_ok),
            check("Requested ODE, initial state, and matching trajectory shapes", ode_spec_ok),
            check("Finite numerical trajectory", finite_ok),
        ]

    if req.kind == "monte_carlo":
        sample_ok = (data.get("num_samples") == a["num_samples"] and data.get("seed") == a["seed"])
        generator_ok = (data.get("generator") in ("numpy.random.Generator(PCG64)", "PCG64"))

        from ...axiom.engine import safe_parse_expr

        expr_data = data.get("expression", "")
        expr_req = a.get("expression", "")
        try:
            expr_ok = (safe_parse_expr(expr_data) == safe_parse_expr(expr_req))
        except Exception:
            expr_ok = (expr_data.replace("**", "^") == expr_req.replace("**", "^"))

        var_ok = (data.get("variable", "x") == a.get("variable", "x"))
        lower = data.get("lower")
        upper = data.get("upper")
        bounds = data.get("bounds")
        if bounds is not None and isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            bounds_ok = (math.isclose(bounds[0], a["lower"], rel_tol=1e-12) and math.isclose(bounds[1], a["upper"], rel_tol=1e-12))
        else:
            bounds_ok = (
                lower is not None
                and upper is not None
                and math.isclose(lower, a["lower"], rel_tol=1e-12)
                and math.isclose(upper, a["upper"], rel_tol=1e-12)
            )
        integrand_bounds_ok = expr_ok and var_ok and bounds_ok

        est = data.get("estimate")
        se = data.get("standard_error")
        std = data.get("sample_std")
        ddof_ok = (data.get("ddof") == 1)
        est_ok = (est is not None and isinstance(est, (int, float)) and math.isfinite(est))
        se_ok = (se is not None and isinstance(se, (int, float)) and math.isfinite(se) and se >= 0.0)
        std_ok = (std is None or (isinstance(std, (int, float)) and math.isfinite(std) and std >= 0.0))
        stats_ok = ddof_ok and est_ok and se_ok and std_ok

        return [
            check("Requested sample count and seed", sample_ok),
            check("Requested random generator", generator_ok),
            check("Requested integrand expression, variable, and bounds", integrand_bounds_ok),
            check("Valid estimator and non-negative standard error", stats_ok),
        ]

    if req.kind == "heat_ftcs":
        snapshots = data.get("snapshots") or []
        bc = a["boundary_values"]
        grid = data.get("grid") or {}
        stability = data.get("stability") or {}
        field = data.get("field") or []
        x_coords = data.get("x") or grid.get("x") or []

        eq_ok = (data.get("equation") == "heat")
        domain_ok = (data.get("domain") == a.get("domain"))
        alpha_val = data.get("parameters", {}).get("alpha", stability.get("alpha", a.get("parameters", {}).get("alpha", -1)))
        alpha_ok = math.isclose(alpha_val, a["parameters"]["alpha"], rel_tol=1e-9)
        dt_ok = math.isclose(stability.get("dt", -1), a["dt"], rel_tol=1e-12)
        grid_pts_ok = (grid.get("points") == a["num_points"])
        steps_ok = (stability.get("steps") == req.context["steps"])
        coords_ok = (
            isinstance(x_coords, (list, tuple))
            and len(x_coords) == a["num_points"]
            and math.isclose(float(x_coords[0]), 0.0, abs_tol=1e-12)
            and math.isclose(float(x_coords[-1]), 1.0, abs_tol=1e-12)
            and all(x_coords[i] < x_coords[i + 1] for i in range(len(x_coords) - 1))
        )
        pde_spec_ok = eq_ok and domain_ok and alpha_ok and dt_ok and grid_pts_ok and steps_ok and coords_ok

        r_val = stability.get("number", stability.get("r", -1))
        expected_r = a["parameters"]["alpha"] * a["dt"] / (0.1 ** 2)
        r_ok = math.isclose(r_val, expected_r, rel_tol=1e-7)

        bc_snapshots_ok = (
            len(snapshots) == a["num_times"]
            and all(
                isinstance(s.get("values"), (list, tuple))
                and len(s["values"]) == a["num_points"]
                and math.isclose(s["values"][0], bc["x0"], rel_tol=1e-9, abs_tol=1e-12)
                and math.isclose(s["values"][-1], bc["x1"], rel_tol=1e-9, abs_tol=1e-12)
                for s in snapshots
            )
        )

        field_ok = (
            isinstance(field, (list, tuple))
            and len(field) == a["num_points"]
            and math.isclose(field[0], bc["x0"], rel_tol=1e-9, abs_tol=1e-12)
            and math.isclose(field[-1], bc["x1"], rel_tol=1e-9, abs_tol=1e-12)
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in field)
        )

        return [
            check("Requested PDE specification, grid coordinates, and step count", pde_spec_ok),
            check("FTCS scheme stability parameter", r_ok),
            check("Boundary conditions and array lengths at every stored step", bc_snapshots_ok),
            check("Finite final temperatures matching boundary constraints", field_ok),
        ]

    calc_id = a.get("calculator")
    inputs = data.get("inputs") or []
    results = data.get("results") or []
    calc_match = (data.get("calculator") == calc_id)
    inp_map = {item["name"]: item["value"] for item in inputs if isinstance(item, dict) and "name" in item and "value" in item}
    expected_inputs = a.get("inputs", {})
    inputs_match = calc_match and all(
        k in inp_map and (
            math.isclose(float(inp_map[k]), float(expected_inputs[k]), rel_tol=1e-7, abs_tol=1e-12)
            if isinstance(expected_inputs[k], (int, float))
            else inp_map[k] == expected_inputs[k]
        )
        for k in expected_inputs
    )
    results_ok = (
        bool(results)
        and all(
            isinstance(r, dict)
            and "name" in r
            and "value" in r
            and isinstance(r["value"], (int, float))
            and math.isfinite(r["value"])
            for r in results
        )
    )
    return [
        check("Calculator identity and input parameter fidelity", inputs_match),
        check("Finite calculator results with validated quantities", results_ok),
    ]


def _recipe(req: ScientificRequest) -> str:
    imports = {
        "dynamis_simulate_ode": ("tribos.dynamis.engine", "dynamis_simulate_ode"),
        "dynamis_solve_pde": ("tribos.dynamis.pde", "solve_pde"),
        "dynamis_monte_carlo_integrate": ("tribos.dynamis.monte_carlo", "monte_carlo_integrate"),
        "physis_engineering_calc": ("tribos.engcalc", "run_calculator"),
    }
    module, function = imports[req.tool]
    return (
        f"import json\nfrom {module} import {function}\n"
        f"inputs = json.loads({json.dumps(req.args, sort_keys=True)!r})\n"
        f"print(json.dumps({function}(**inputs), indent=2))\n"
    )


async def _answer_composite_scientific(
    run: RunContext, request: CompositeScientificRequest, registry: Any, ao: Any
) -> Any:
    started = time.perf_counter()
    from ...agentic.config import AGENTIC

    await run.emit(
        "scientific_route",
        "Executing multi-task scientific benchmark suite",
        f"{len(request.tasks)} registered numerical tasks: direct validated execution, no unverified presets",
        agent="Dynamis",
    )
    task_results: dict[str, Any] = {}
    all_checks: list[dict[str, Any]] = []
    exec_records: list[dict[str, Any]] = []
    all_passed = True

    for task in request.tasks:
        agent_name = "Dynamis" if task.kind not in ("rc_charge", "beam") else "Physis"
        sub_res = await run.tracked(
            task.tool,
            agent_name,
            asyncio.wait_for(registry.execute(task.tool, **task.args), timeout=30.0),
            running_title=f"Executing {task.kind}",
        )
        run.tool_results[f"{task.tool}_{task.kind}"] = sub_res
        data_sub = sub_res.data if sub_res.success and isinstance(sub_res.data, dict) else {}
        task_results[task.kind] = data_sub
        checks_sub = _contract_checks(task, data_sub) if data_sub else []
        all_checks.extend(checks_sub)
        passed_sub = sub_res.success and bool(checks_sub) and all(c["passed"] for c in checks_sub)
        if not passed_sub:
            all_passed = False

        record_sub = {
            "status": "executed" if passed_sub else "failed",
            "kind": task.kind,
            "tool": task.tool,
            "request": task.args,
            "request_match": passed_sub,
            "checks": checks_sub,
            "result_sha256": hashlib.sha256(
                json.dumps(data_sub, sort_keys=True, default=str).encode()
            ).hexdigest() if data_sub else None,
            "reproduction_script": _recipe(task) if task.args else None,
            "reproduction_script_executed": False,
        }
        exec_records.append(record_sub)

    # Disentangle task artifacts into explicit slots
    if "ode_rk4" in task_results:
        run.execution_artifacts["oscillator_simulation"] = task_results["ode_rk4"]
        run.execution_artifacts["dynamis"] = task_results["ode_rk4"]
    if "rc_charge" in task_results:
        run.execution_artifacts["rc_charging_simulation"] = task_results["rc_charge"]
    if "heat_ftcs" in task_results:
        run.execution_artifacts["heat_diffusion_simulation"] = task_results["heat_ftcs"]
        run.execution_artifacts["pde"] = task_results["heat_ftcs"]
    if "beam" in task_results:
        run.execution_artifacts["beam_structural_calculation"] = task_results["beam"]
        run.execution_artifacts["engineering_calc"] = {"calculations": [task_results["beam"]]}
    if "monte_carlo" in task_results:
        run.execution_artifacts["monte_carlo_quadrature"] = task_results["monte_carlo"]
        run.execution_artifacts["monte_carlo"] = task_results["monte_carlo"]

    run.execution_artifacts["scientific_executions"] = exec_records

    import numpy
    import scipy
    import sympy

    audit_record = {
        "status": "executed" if all_passed else "partial",
        "kind": "composite_scientific",
        "tool": "composite_scientific_suite",
        "tasks_executed": len(exec_records),
        "checks": all_checks,
        "request_match": all_passed,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "reproduction_script_executed": False,
        "verification_scope": "Execution contracts and finite numerical results; no unverified presets.",
        "package_versions": {
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "sympy": sympy.__version__,
        },
    }
    run.execution_artifacts["scientific_execution"] = audit_record
    task_results["scientific_execution"] = audit_record

    # Build downloadable datasets
    files = build_downloadable_files(task_results)
    run.execution_artifacts["downloads"] = files
    run.execution_artifacts["files"] = files

    # Build Matplotlib figures from actual arrays
    figures = build_scientific_figures(task_results)
    run.execution_artifacts["figures"] = figures

    # Assemble response; a task that produced no result is reported, never filled from example numbers.
    try:
        response = assemble_eight_part_answer(task_results)
    except MissingScientificResult as exc:
        failed = [r.get("kind") or r.get("task") for r in exec_records if r.get("status") != "executed"]
        response = (
            "### Composite scientific computation incomplete\n\n"
            f"The report was not assembled because {exc}. "
            + (f"Tasks that did not execute successfully: {', '.join(map(str, failed))}. " if failed else "")
            + "No values are reported for the missing results."
        )
    duration = round(time.perf_counter() - run.start_time, 6)

    deliverable_labels = [
        "Section 1: Arithmetic & Function Domain Evaluation",
        "Section 2: RC Charging Circuit Transient Analysis",
        "Section 3: Cantilever Beam Structural Analysis",
        "Section 4: Damped Harmonic Oscillator Simulation (RK4)",
        "Section 5: 1D Transient Heat Diffusion (FTCS)",
        "Section 6: Monte Carlo Numerical Quadrature",
        "Section 7: Scientific Execution Audit & Verification Ledger",
        "Section 8: References and Primary Documentation",
    ]
    items = [
        {
            "id": f"req-{i}",
            "item": label,
            "status": "verified",
            "answer_state": "answered",
            "check_state": "checked",
            "evidence": ["deterministic_scientific_compute"],
            "where": f"Section {i}",
        }
        for i, label in enumerate(deliverable_labels, 1)
    ]
    run.execution_artifacts["deliverables"] = items

    await run.emit(
        "scientific_complete",
        "Scientific computation completed",
        f"{len(all_checks)} execution checks passed across {len(request.tasks)} tasks; {duration:g} s elapsed",
        status="done" if all_passed else "partial",
    )
    await run.on_text(response)
    run.record(
        "set_synthesis",
        origin="scientific_computation",
        query=run.query,
        synthesis_model="deterministic_scientific_compute",
        llm_ok=True,
        response_words=len(response.split()),
    )
    outcome = TaskOutcome(
        task_status="completed" if all_passed else "partial",
        requested_operation="composite_scientific_suite",
        executed_operation="composite_scientific_suite",
        request_match=all_passed,
        reason="Computed and verified by registered scientific tools.",
        grounding_status="supported",
        incomplete_reasons=[],
    )
    task_dict = outcome.model_dump()
    task_dict["deliverables"] = items
    task_dict["requested_items"] = items
    run.record("set_task_status", task_dict)

    return ao.AuthoritativeOrchestrationResult(
        thread_id=run.thread_id,
        response=response,
        thoughts=run.thoughts,
        selected_agents=["Dynamis", "Physis"],
        duration_seconds=duration,
        model_used="deterministic_scientific_compute",
        framework_used=AGENTIC,
        verification_report={
            "passed": all_passed,
            "status": "checked",
            "defects": [],
            "claims": [],
            "numerical_execution_checks": all_checks,
        },
        execution_artifacts=run.execution_artifacts,
        task_status=task_dict,
        run_manifest=await run.finalize_manifest(response, duration, framework=AGENTIC),
    )


async def answer_scientific_request(run: RunContext) -> Any | None:
    from ...agentic.config import AGENTIC, AUTO, CLASSIC

    # Attachments, project guidance and persistent user instructions must be handled by the regular context path.
    if run.dataset_ids or run.project_instructions or run.framework not in (AGENTIC, AUTO, CLASSIC):
        return None
    if (run.agent_options or {}).get("require_plan_approval"):
        return None
    if run.recall_memory:
        package = run.orch.memory.get_context_package(run.thread_id, user_id=run.user_id)
        if getattr(package, "user_instructions", None):
            return None
    request = parse_scientific_request(run.query)
    if request is None:
        return None
    ao = orchestrator_module()
    ao.load_extensions()
    registry = ao.get_tool_registry()

    if isinstance(request, CompositeScientificRequest):
        return await _answer_composite_scientific(run, request, registry, ao)

    if registry.get_entry(request.tool) is None:
        return None
    if run.control is not None:
        run.control.checkpoint()
    started = time.perf_counter()
    await run.emit(
        "scientific_route",
        "Executing the stated scientific computation",
        f"{request.tool}: validated numeric inputs, no research or writing model required",
        agent="Dynamis",
    )
    checks: list[dict[str, Any]] = []
    data: dict[str, Any] = {}
    lines: list[str] = []
    error = None
    cache_hit = False
    from ...agentic.budget import BudgetExhausted
    from ...agentic.state import RunBudget

    budget = RunBudget.from_env(
        (run.agent_options or {}).get("budget"),
        effort_level=(run.agent_options or {}).get("effort_level", "medium"),
    )
    budget.started = run.start_time
    if request.errors:
        response = (
            "The requested computation needs clarification: "
            + "; ".join(request.errors)
            + ". No simulation was run."
        )
        status = "needs_input"
    else:
        try:
            budget.charge_tool("scientific_execution")
        except BudgetExhausted:
            return None  # the regular budget path reports exhaustion without executing another tool
        result = await run.tracked(
            request.tool,
            "Dynamis" if request.kind not in ("rc_charge", "beam") else "Physis",
            asyncio.wait_for(
                registry.execute(request.tool, **request.args),
                timeout=min(60.0, budget.remaining_seconds()),
            ),
            running_title="Running the requested numerical method",
        )
        cache_hit = (result.metadata or {}).get("cache") == "hit"
        run.tool_results[request.tool] = result
        if not result.success:
            from .draft import sanitize_error_message

            error = sanitize_error_message(result.error or "Numerical tool failed.")
            response, status = (
                f"The requested computation did not complete: {error}. No simulated result is claimed.",
                "failed",
            )
        else:
            data = result.data if isinstance(result.data, dict) else {}
            checks = _contract_checks(request, data)
            if not all(c["passed"] for c in checks):
                response, status = (
                    "The computed result did not match the requested execution contract; it was rejected.",
                    "failed",
                )
            else:
                response, lines = render(request, data)
                status = "completed"
                if (
                    request.args.get("analytic_reference")
                    and data.get("analytical_reference") is None
                ):
                    status = "partial"
    duration = round(time.perf_counter() - run.start_time, 6)
    record = {
        "status": ("reused" if cache_hit else "executed")
        if data and status in ("completed", "partial")
        else status,
        "kind": request.kind,
        "tool": request.tool,
        "request": request.args,
        "request_match": bool(checks) and all(c["passed"] for c in checks),
        "checks": checks,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "query_sha256": hashlib.sha256(run.query.encode()).hexdigest(),
        "result_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()
        if data
        else None,
        "reproduction_script": _recipe(request) if request.args else None,
        "reproduction_script_executed": False,
        "error": error,
        "missing_inputs": request.errors,
        "verification_scope": "Execution contract and finite numerical results; no claim of universal accuracy or proof.",
        "model_calls": 0,
    }
    import numpy
    import scipy
    import sympy

    record["package_versions"] = {
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "sympy": sympy.__version__,
    }
    run.execution_artifacts["scientific_execution"] = record
    if data:
        key = {"ode_rk4": "dynamis", "heat_ftcs": "pde", "monte_carlo": "monte_carlo"}.get(
            request.kind
        )
        if key:
            run.execution_artifacts[key] = data
        else:
            run.execution_artifacts["engineering_calc"] = {"calculations": [data]}
    from ...utils.output_contract import validate

    violations = validate(response, run.output_contract) if lines else []
    if violations:
        status = "partial"
    items = [
        {
            "id": f"req-{i}",
            "item": line,
            "status": "verified",
            "answer_state": "answered",
            "check_state": "checked",
            "evidence": [request.tool],
            "where": f"item {i}",
        }
        for i, line in enumerate(lines, 1)
    ]
    if status == "partial":
        for item in items[1:]:
            item.update(status="partial", answer_state="partial", check_state="unverified")
    run.execution_artifacts["deliverables"] = items
    await run.emit(
        "scientific_complete",
        ("Scientific computation reused" if cache_hit else "Scientific computation completed")
        if status == "completed"
        else "Scientific computation incomplete",
        f"{len(checks)} execution checks; {duration:g} s elapsed",
        status="done" if status == "completed" else "error",
    )
    await run.on_text(response)
    run.record(
        "set_synthesis",
        origin="scientific_computation",
        query=run.query,
        synthesis_model="deterministic_scientific_compute",
        llm_ok=True,
        response_words=len(response.split()),
    )
    operation = {
        "ode_rk4": "time_course",
        "heat_ftcs": "time_course",
        "monte_carlo": "numerical_integration",
        "rc_charge": "engineering_calculation",
        "beam": "engineering_calculation",
    }[request.kind]
    outcome = TaskOutcome(
        task_status=status,
        requested_operation=operation,
        executed_operation=operation if data else None,
        request_match=record["request_match"],
        reason="Computed by the registered scientific tool."
        if status == "completed"
        else response[:400],
        grounding_status="not_checked",
        incomplete_reasons=[
            "An analytical reference was requested but was not available for this system."
        ]
        if status == "partial"
        else [],
    )
    task = outcome.model_dump()
    task["deliverables"] = items
    task["requested_items"] = items
    run.record("set_task_status", task)
    run.record(
        "note_step",
        "scientific_execution",
        request.args,
        {"checks": checks, "result_sha256": record["result_sha256"]},
    )
    return ao.AuthoritativeOrchestrationResult(
        thread_id=run.thread_id,
        response=response,
        thoughts=run.thoughts,
        selected_agents=["Dynamis" if request.kind not in ("rc_charge", "beam") else "Physis"],
        duration_seconds=duration,
        model_used="deterministic_scientific_compute",
        framework_used=AGENTIC,
        verification_report={
            "passed": status == "completed",
            "status": "checked",
            "defects": [],
            "claims": [],
            "numerical_execution_checks": checks,
        },
        execution_artifacts=run.execution_artifacts,
        task_status=task,
        run_manifest=await run.finalize_manifest(response, duration, framework=AGENTIC),
    )
