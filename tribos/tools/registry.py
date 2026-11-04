"""
Tool Registry for Tribos (mathematics, physics and engineering tools), inspired by ToolUniverse (2025).
Provides a searchable, validated, and resilient tool registry with canonical entity identifiers,
strict timeouts, typed error states, and health monitoring.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AdapterType(str, Enum):
    DIRECT_REST = "DIRECT_REST"
    DIRECT_GRAPHQL = "DIRECT_GRAPHQL"
    LOCAL_COMPUTE = "LOCAL_COMPUTE"
    REMOTE_MCP = "REMOTE_MCP"


class ErrorType(str, Enum):
    TIMEOUT = "TIMEOUT"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    NOT_FOUND = "NOT_FOUND"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    UPSTREAM_API_ERROR = "UPSTREAM_API_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATASET_REQUIRED = "DATASET_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolResult(BaseModel):
    """Standardized output model for every tool execution."""
    success: bool = Field(..., description="Whether tool execution completed successfully without defect")
    tool_name: str = Field(..., description="Name of the executed tool")
    data: Any = Field(default=None, description="Structured output payload or execution artifact")
    canonical_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Canonical identifiers resolved (e.g. computation_id, doi, arxiv_id, zbl_id, nist_constant, mp_id)",
    )
    error: str | None = Field(default=None, description="Human-readable error description if failed")
    error_type: ErrorType | None = Field(default=None, description="Typed failure classification")
    execution_time_seconds: float = Field(default=0.0, description="Measured wall-clock execution duration")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metadata: adapter type, cache status, solver diagnostics, provenance",
    )

    def to_summary(self) -> str:
        """Return concise string summary for LLM context or logs."""
        if not self.success:
            return f"[{self.tool_name} FAILED ({self.error_type})]: {self.error}"
        id_str = ", ".join(f"{k}={v}" for k, v in self.canonical_ids.items()) if self.canonical_ids else "None"
        return f"[{self.tool_name} SUCCESS ({self.execution_time_seconds:.2f}s)]: IDs: ({id_str})"


class ToolUniverseEntry(BaseModel):
    """Registry entry metadata for a tool."""
    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Detailed description of tool capabilities")
    domain: str = Field(
        ...,
        description="Specialist agent domain: archivon | axiom | dynamis | physis | analysis (Calcula) | websurfer | "
        "lithoscribe / vivarix (legacy aliases) | general",
    )
    adapter_type: AdapterType = Field(..., description="Direct API adapter vs Local engine vs MCP")
    input_schema: type[BaseModel] = Field(..., description="Pydantic input schema class")
    output_schema: type[BaseModel] | None = Field(default=None, description="Expected structured output schema")
    canonical_id_types: list[str] = Field(default_factory=list, description="IDs handled, e.g. ['ensembl_id', 'uniprot_id']")
    timeout_seconds: float = Field(default=30.0, description="Per-execution timeout cutoff")
    tags: list[str] = Field(default_factory=list, description="Searchable functional tags")
    # True: the executor returns an awaitable (e.g. a lambda wrapping an async client call) and runs on the event
    # loop; False: it is synchronous and runs in a worker thread; None: detected from the callable.
    is_async: bool | None = Field(default=None, description="Executor returns an awaitable")


# Native solvers (COPASI, Scanpy) run in their own bounded pool: a call that outlives its timeout cannot be
# interrupted, so it must not be able to exhaust the default executor that everything else shares.
_NATIVE_POOL: ThreadPoolExecutor | None = None


def _native_pool() -> ThreadPoolExecutor:
    global _NATIVE_POOL
    if _NATIVE_POOL is None:
        workers = max(1, int(os.getenv("TRIBOS_NATIVE_WORKERS", "4") or 4))
        _NATIVE_POOL = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tribos-native")
    return _NATIVE_POOL


_NETWORK_POOL: ThreadPoolExecutor | None = None


def _network_pool() -> ThreadPoolExecutor:
    """The bounded pool for synchronous networked tools (REST, GraphQL, MCP). A call that times out keeps its thread
    until the socket gives up; a dedicated pool keeps such threads from exhausting asyncio's default executor."""
    global _NETWORK_POOL
    if _NETWORK_POOL is None:
        try:
            workers = int(os.getenv("TRIBOS_NETWORK_WORKERS", "16") or 16)
        except ValueError:
            workers = 16
        _NETWORK_POOL = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="tribos-net")
    return _NETWORK_POOL


def _must_propagate(exc: BaseException) -> bool:
    """Run-level control exceptions (cancellation, budget) are never turned into a failed ToolResult."""
    try:
        from ..agentic.budget import BudgetExhausted
        from ..agentic.control import RunCancelled
    except Exception:  # noqa: BLE001
        return False
    return isinstance(exc, (RunCancelled, BudgetExhausted))


def _is_async_callable(fn: Callable[..., Any]) -> bool:
    target = fn
    while isinstance(target, functools.partial):
        target = target.func
    return inspect.iscoroutinefunction(target) or (callable(target) and inspect.iscoroutinefunction(target.__call__))


async def _await_maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class ToolRegistry:
    """
    Searchable Tool Registry managing all tools across Tribos.
    Validates inputs, injects timeouts, enforces structured errors, and tracks health.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolUniverseEntry] = {}
        self._executors: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        entry: ToolUniverseEntry,
        executor: Callable[..., Any],
    ) -> None:
        """Register a tool and its executable function."""
        self._tools[entry.name] = entry
        self._executors[entry.name] = executor
        logger.debug("Registered tool in ToolUniverse: %s (%s)", entry.name, entry.domain)

    def get_entry(self, name: str) -> ToolUniverseEntry | None:
        return self._tools.get(name)

    def get_executor(self, name: str) -> Callable[..., Any] | None:
        return self._executors.get(name)

    def list_tools(self, domain: str | None = None) -> list[ToolUniverseEntry]:
        """List registered tools, optionally filtered by agent domain."""
        if domain:
            return [t for t in self._tools.values() if t.domain.lower() == domain.lower()]
        return list(self._tools.values())

    def search_tools(self, query: str, domain: str | None = None) -> list[ToolUniverseEntry]:
        """Search registered tools by keyword match across name, description, and tags."""
        q = query.lower()
        candidates = self.list_tools(domain)
        matched = []
        for c in candidates:
            score = 0
            if q in c.name.lower():
                score += 3
            if any(q in t.lower() for t in c.tags):
                score += 2
            if q in c.description.lower():
                score += 1
            if score > 0:
                matched.append((score, c))
        matched.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in matched]

    async def execute(self, tool_name: str, *args: Any, **kwargs: Any) -> ToolResult:
        """
        Execute tool with input validation, timeout enforcement, and typed ToolResult output.
        Every call, whatever its outcome, is reported to the active run recorder.
        """
        if args and isinstance(args[0], dict):
            kwargs = {**args[0], **kwargs}
        started_at = datetime.now(UTC).isoformat()
        t0 = time.perf_counter()
        trace: dict[str, Any] = {}
        res: ToolResult | None = None
        raw_kwargs = dict(kwargs)
        # Arguments that fail the schema only for a trivially fixable reason (a limit above its bound, too many
        # list items, {"name": ...} where a string is expected) are repaired once; the original error stands
        # when the repair does not validate. The adjustment is recorded on the result.
        # Model-generated calls (agents, plans) pass repair_arguments=True; programmatic callers get strict validation.
        adjusted: list[str] = []
        entry = self._tools.get(tool_name)
        if kwargs.pop("_repair_arguments", False) and entry is not None:
            from .arg_repair import repair_arguments

            repaired = repair_arguments(entry.input_schema, kwargs)
            if repaired is not None:
                kwargs, adjusted = repaired
                logger.info("Repaired arguments for %s: %s", tool_name, "; ".join(adjusted))
        raw_kwargs.pop("_repair_arguments", None)
        try:
            from .reliability import execute_with_policies

            res = await execute_with_policies(
                self, tool_name, kwargs, lambda: self._execute_inner(tool_name, kwargs, trace), trace=trace
            )
            if res is None:
                logger.error("Tool %s returned no result; reporting an internal error", tool_name)
                res = ToolResult(
                    success=False,
                    tool_name=tool_name,
                    error="Tool execution returned no result",
                    error_type=ErrorType.INTERNAL_ERROR,
                    execution_time_seconds=time.perf_counter() - t0,
                    metadata={"registry": "ToolUniverse"},
                )
            if adjusted and isinstance(res, ToolResult):
                res = res.model_copy(update={"metadata": {**(res.metadata or {}), "arguments_adjusted": list(adjusted)}})
        except Exception as exc:  # noqa: BLE001
            if _must_propagate(exc):
                raise
            logger.error("Tool %s failed outside its executor: %s", tool_name, exc, exc_info=True)
            res = ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"{type(exc).__name__}: {exc}",
                error_type=ErrorType.INTERNAL_ERROR,
                execution_time_seconds=time.perf_counter() - t0,
                metadata={"registry": "ToolUniverse"},
            )
        finally:
            try:
                from ..provenance.run_manifest import record_tool_call

                record_tool_call(
                    tool_name=tool_name,
                    entry=trace.get("entry"),
                    inputs=trace.get("validated_kwargs"),
                    raw_inputs=raw_kwargs,
                    result=res,
                    started_at=started_at,
                    elapsed_seconds=time.perf_counter() - t0,
                )
            except Exception:  # noqa: BLE001
                # Provenance must never fail a tool call, but a lost record is worth knowing about.
                logger.warning("Could not record the %s tool call in the run manifest", tool_name, exc_info=True)
        assert res is not None  # set on every path that reaches here (control exceptions propagate instead)
        return res

    async def _execute_inner(self, tool_name: str, kwargs: dict[str, Any], trace: dict[str, Any]) -> ToolResult:
        entry = self._tools.get(tool_name)
        executor = self._executors.get(tool_name)
        trace["entry"] = entry

        if not entry or not executor:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Tool '{tool_name}' is not registered in ToolUniverse",
                error_type=ErrorType.NOT_FOUND,
                metadata={"registry": "ToolUniverse"},
            )

        # 1. Validate inputs via Pydantic schema
        try:
            validated_input = entry.input_schema(**kwargs)
            validated_kwargs = validated_input.model_dump()
            trace["validated_kwargs"] = validated_kwargs
        except Exception as val_err:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Input validation error: {val_err}",
                error_type=ErrorType.VALIDATION_ERROR,
                metadata={"adapter": entry.adapter_type.value},
            )

        # 2. Execute with bounded timeout
        start_t = time.perf_counter()
        try:
            is_async = entry.is_async if entry.is_async is not None else _is_async_callable(executor)
            if is_async:
                raw_out = await asyncio.wait_for(
                    _await_maybe(executor(**validated_kwargs)),
                    timeout=entry.timeout_seconds,
                )
            else:
                # Synchronous executors (COPASI/BASICO, Scanpy) run in a worker thread so they neither block
                # the event loop nor escape the timeout; on cancellation the awaiting task returns promptly
                # while the native solver call finishes in the background (it cannot be interrupted mid-call).
                # LOCAL_COMPUTE tools use their own bounded pool so stuck solvers cannot starve other tools.
                deadline = time.perf_counter() + entry.timeout_seconds
                if entry.adapter_type == AdapterType.LOCAL_COMPUTE:
                    call = functools.partial(contextvars.copy_context().run, executor, **validated_kwargs)
                    pending = asyncio.get_running_loop().run_in_executor(_native_pool(), call)
                else:
                    # Networked sync tools get their own bounded pool: a timed-out call's thread keeps running until
                    # its socket gives up, and must not exhaust the loop's default executor.
                    call = functools.partial(contextvars.copy_context().run, executor, **validated_kwargs)
                    pending = asyncio.get_running_loop().run_in_executor(_network_pool(), call)
                call_res = await asyncio.wait_for(pending, timeout=entry.timeout_seconds)
                if inspect.isawaitable(call_res):
                    raw_out = await asyncio.wait_for(
                        call_res,
                        timeout=max(0.001, deadline - time.perf_counter()),
                    )
                else:
                    raw_out = call_res

            elapsed = time.perf_counter() - start_t

            # If executor already returned ToolResult, merge metadata
            if isinstance(raw_out, ToolResult):
                raw_out.execution_time_seconds = elapsed
                raw_out.metadata["adapter"] = entry.adapter_type.value
                if entry.output_schema and raw_out.success and raw_out.data is not None:
                    try:
                        if isinstance(raw_out.data, dict):
                            entry.output_schema.model_validate(raw_out.data)
                    except Exception as out_err:
                        raw_out.success = False
                        raw_out.error = f"Output validation failed: {out_err}"
                        raw_out.error_type = ErrorType.VALIDATION_ERROR
                return raw_out

            # ORC-001: an executor that follows the error-as-data convention (BioContext client) reports a
            # transport failure as a dict with upstream_failed=True. That is a failed call, not "nothing found":
            # it must be retried, counted by the breaker, never cached, and shown as an unavailable source.
            if isinstance(raw_out, dict) and raw_out.get("upstream_failed") is True:
                try:
                    failed_type = ErrorType(str(raw_out.get("error_type") or "UPSTREAM_API_ERROR"))
                except ValueError:
                    failed_type = ErrorType.UPSTREAM_API_ERROR
                return ToolResult(
                    success=False,
                    tool_name=tool_name,
                    data=raw_out,
                    error=str(raw_out.get("error") or "upstream request failed"),
                    error_type=failed_type,
                    execution_time_seconds=elapsed,
                    metadata={"adapter": entry.adapter_type.value},
                )

            # Extract any canonical IDs in data if dict
            canonical_ids: dict[str, str] = {}
            if isinstance(raw_out, dict):
                for id_key in ("ensembl_id", "uniprot_id", "biomodel_id", "efo_id", "pmid", "doi", "chembl_id"):
                    if id_key in raw_out and raw_out[id_key]:
                        canonical_ids[id_key] = str(raw_out[id_key])

            res = ToolResult(
                success=True,
                tool_name=tool_name,
                data=raw_out,
                canonical_ids=canonical_ids,
                execution_time_seconds=elapsed,
                metadata={"adapter": entry.adapter_type.value},
            )

            if entry.output_schema and res.data is not None:
                try:
                    if isinstance(res.data, dict):
                        entry.output_schema.model_validate(res.data)
                except Exception as out_err:
                    res.success = False
                    res.error = f"Output validation failed: {out_err}"
                    res.error_type = ErrorType.VALIDATION_ERROR

            return res

        except TimeoutError:
            elapsed = time.perf_counter() - start_t
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Tool execution exceeded timeout cutoff of {entry.timeout_seconds}s",
                error_type=ErrorType.TIMEOUT,
                execution_time_seconds=elapsed,
                metadata={"adapter": entry.adapter_type.value},
            )
        except Exception as exec_err:
            elapsed = time.perf_counter() - start_t
            logger.error("Error executing %s: %s", tool_name, exec_err, exc_info=True)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=str(exec_err),
                error_type=ErrorType.INTERNAL_ERROR,
                execution_time_seconds=elapsed,
                metadata={"adapter": entry.adapter_type.value},
            )


# -----------------------------------------------------------------------------
# STANDARD TOOL INPUT SCHEMAS & REGISTRATION
# -----------------------------------------------------------------------------

# A BioModels accession, or the dataset id of an uploaded SBML model (never a path or free text).
VIVARIX_MODEL_ID = r"^(?:BIOMD\d{10}|MODEL\d{10}|ds_[0-9a-f]{12})$"


class VivarixSimInput(BaseModel):
    biomodel_id: str = Field(default="BIOMD0000000010", pattern=VIVARIX_MODEL_ID)
    duration: float = Field(default=60.0, ge=1.0, le=5000.0, description="seconds")
    intervals: int = Field(default=40, ge=5, le=500)
    parameter_overrides: dict[str, float] | None = Field(default=None, max_length=20)
    sbml_path: str | None = None
    model_label: str | None = None
    model_provenance: dict[str, Any] | None = None


class VivarixSteadyStateInput(BaseModel):
    biomodel_id: str = Field(default="BIOMD0000000010", pattern=VIVARIX_MODEL_ID)
    sbml_path: str | None = None
    model_label: str | None = None
    model_provenance: dict[str, Any] | None = None
    parameter_overrides: dict[str, float] | None = Field(default=None, max_length=20)


class VivarixParamScanInput(BaseModel):
    biomodel_id: str = Field(default="BIOMD0000000010", pattern=VIVARIX_MODEL_ID)
    parameter_name: str = Field(default="V1", min_length=1, max_length=200)
    start_val: float = Field(default=1.0, allow_inf_nan=False)
    end_val: float = Field(default=10.0, allow_inf_nan=False)
    num_steps: int = Field(default=5, ge=2, le=50, description="points, both endpoints included")
    target_species: str | None = Field(default="Erk2-PP")
    duration: float = Field(default=60.0, ge=1.0, le=5000.0, description="seconds per point")
    intervals: int = Field(default=100, ge=5, le=500)
    spacing: Literal["linear", "log"] = "linear"
    report_all_species: bool = False
    sbml_path: str | None = None
    model_label: str | None = None
    model_provenance: dict[str, Any] | None = None


class LithoscribeSynthesisInput(BaseModel):
    query: str
    max_articles: int = Field(default=8, ge=1, le=50)
    check_integrity: bool = True
    # Planned EuropePMC searches ({"query", "sort", "tier", "label"}); when absent the query is decomposed.
    search_queries: list[dict[str, Any]] | None = None
    keywords: list[str] | None = None  # words that rank retrieved passages
    pinned_ids: list[str] | None = Field(
        default=None,
        max_length=10,
        description=(
            "Exact identifiers to fetch first (PMID like '39369609', PMCID like 'PMC1234567', or DOI); use this, "
            "not a free-text 'PMID ...' query, to retrieve a named paper. Identifiers in the query are also fetched."
        ),
    )


class WebSurferSearchInput(BaseModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=20)


class SubstrateMaterialInput(BaseModel):
    material_name: str = Field(..., description="Name or designation of material, e.g. Al6061-T6, Steel 4140, Ti-6Al-4V")
    temperature_celsius: float = Field(default=20.0, description="Temperature in Celsius for temperature-dependent properties")


class SubstrateStandardsInput(BaseModel):
    clause_id: str = Field(default="ASME_VIII_1_UG27_CYL", description="Standard clause identifier")
    pressure_mpa: float = Field(..., description="Internal or external design pressure in MPa")
    radius_mm: float = Field(..., description="Vessel inside radius in mm")
    allowable_stress_mpa: float = Field(..., description="Maximum allowable stress in MPa")
    wall_thickness_mm: float = Field(..., description="Actual or proposed shell wall thickness in mm")
    joint_efficiency: float = Field(default=1.0, description="Weld joint efficiency factor E (0.0 to 1.0)")


class SubstrateGeometryInput(BaseModel):
    stl_content: str = Field(..., min_length=1, description="ASCII STL text (the file content itself; paths are not read)")
    file_name: str = Field(default="model.stl", description="Filename of 3D CAD/STL model")
    material_density_kg_m3: float = Field(default=2700.0, description="Density of material in kg/m^3 for mass calculation")


class SubstrateCAEInput(BaseModel):
    applied_load_n: float = Field(..., description="Total applied load in Newtons")
    reaction_force_n: float = Field(..., description="Sum of reaction forces in Newtons")
    coarse_stress_mpa: float = Field(..., description="Peak stress from coarse mesh in MPa")
    fine_stress_mpa: float = Field(..., description="Peak stress from refined mesh in MPa")
    yield_strength_mpa: float = Field(..., description="Material yield strength in MPa")
    analytical_stress_mpa: float = Field(..., description="Stress from classical analytical formula in MPa")
    stress_gradient_ratio: float | None = Field(
        default=None, description="Peak-to-nominal stress gradient ratio for the singularity screen; omit if unknown"
    )


def _alias_system(model_label: str | None, sbml_path: str | None) -> tuple[dict[str, Any] | None, str]:
    """The Dynamis preset a legacy vivarix_* call names (its model_label), or why there is none.

    These aliases once ran BioModels/SBML models in COPASI. Tribos has no SBML engine, so only a call naming a
    Dynamis preset ("lorenz", "damped oscillator") is simulated; a BioModels id, an SBML file or nothing is a
    validation error, never a stand-in system reported as the requested model (LOG-2)."""
    from tribos.dynamis import ODE_PRESETS

    from ..agents.orchestration.gather import resolve_dynamis_preset

    if sbml_path:
        return None, "SBML model simulation is not available in Tribos."
    key = resolve_dynamis_preset(model_label) if model_label else None
    if key is None:
        presets = ", ".join(k.replace("_", " ") for k in ODE_PRESETS)
        return None, (
            "BioModels/SBML simulation is not available in Tribos, and no Dynamis system was named. Use "
            f"dynamis_simulate_ode with the ODE right-hand sides, or name one of the presets ({presets}) as model_label."
        )
    return {"name": key, **ODE_PRESETS[key]}, ""


def _alias_rejection(tool_name: str, reason: str) -> ToolResult:
    return ToolResult(
        success=False,
        tool_name=tool_name,
        error=reason,
        error_type=ErrorType.VALIDATION_ERROR,
        metadata={"reason_code": "MODEL_REQUIRED", "alias_of": "dynamis"},
    )


def _alias_result(res: Any, tool_name: str, system: dict[str, Any]) -> Any:
    if isinstance(res, ToolResult):
        res.metadata = {**(res.metadata or {}), "alias_of": res.tool_name, "dynamis_system": system["name"]}
        res.tool_name = tool_name
    return res


def _vivarix_sim_alias(dyn_exec: Callable[..., Any]) -> Callable[..., Any]:
    def run(duration: float = 60.0, intervals: int = 40, parameter_overrides: dict[str, float] | None = None,
            sbml_path: str | None = None, model_label: str | None = None, **_kw: Any) -> Any:
        system, reason = _alias_system(model_label, sbml_path)
        if system is None:
            return _alias_rejection("vivarix_simulate_time_course", reason)
        res = dyn_exec(model_name=system["name"], t_span=(0.0, float(duration)), num_points=int(intervals) + 1,
                       parameters=parameter_overrides or None)
        return _alias_result(res, "vivarix_simulate_time_course", system)

    return run


def _vivarix_scan_alias(dyn_scan_exec: Callable[..., Any]) -> Callable[..., Any]:
    def run(parameter_name: str = "", start_val: float = 1.0, end_val: float = 10.0, num_steps: int = 5,
            duration: float = 60.0, intervals: int = 100, sbml_path: str | None = None, model_label: str | None = None,
            **_kw: Any) -> Any:
        system, reason = _alias_system(model_label, sbml_path)
        if system is None:
            return _alias_rejection("vivarix_parameter_scan", reason)
        if parameter_name not in (system.get("parameters") or {}):
            return _alias_rejection(
                "vivarix_parameter_scan",
                f"{parameter_name!r} is not a parameter of the {system['name'].replace('_', ' ')} system "
                f"(parameters: {', '.join(system.get('parameters') or {}) or 'none'}).",
            )
        res = dyn_scan_exec(
            rhs=system["rhs"], initial_state=system["initial_state"], parameter=parameter_name,
            scan_range=(float(start_val), float(end_val)), num_points=int(num_steps), t_span=(0.0, float(duration)),
            base_parameters=system.get("parameters"),
        )
        return _alias_result(res, "vivarix_parameter_scan", system)

    return run


def _vivarix_steady_alias(dyn_eq_exec: Callable[..., Any]) -> Callable[..., Any]:
    def run(parameter_overrides: dict[str, float] | None = None, sbml_path: str | None = None,
            model_label: str | None = None, **_kw: Any) -> Any:
        system, reason = _alias_system(model_label, sbml_path)
        if system is None:
            return _alias_rejection("vivarix_compute_steady_state", reason)
        params = {**(system.get("parameters") or {}), **(parameter_overrides or {})}
        res = dyn_eq_exec(rhs=system["rhs"], guess=system["initial_state"], parameters=params or None)
        return _alias_result(res, "vivarix_compute_steady_state", system)

    return run


def register_default_tools(registry: ToolRegistry) -> None:
    """Register all builtin STEM tools and extensions into the ToolUniverse registry."""
    from ..tools.web_search import FreeWebSearchClient

    web_search = FreeWebSearchClient()

    # WebSurfer Live Web Search
    registry.register(
        ToolUniverseEntry(
            name="websurfer_search",
            description="Perform live asynchronous web search and article retrieval.",
            domain="websurfer",
            adapter_type=AdapterType.DIRECT_REST,
            input_schema=WebSurferSearchInput,
            canonical_id_types=["url"],
            timeout_seconds=20.0,
            tags=["web", "search", "live_verification"],
            is_async=True,
        ),
        executor=lambda query, max_results=3: web_search.search_and_surf(query, max_results=max_results),
    )

    # Feature extensions register their own tools (Archivon, Axiom, Dynamis, Physis, Calcula, etc.)
    from ..extensions import load_extensions, register_extension_tools

    load_extensions()
    register_extension_tools(registry)

    # Backward compatibility aliases pointing to Archivon and Dynamis
    if registry.get_entry("archivon_literature_search") is not None and registry.get_entry("lithoscribe_literature_synthesis") is None:
        arch_exec = registry.get_executor("archivon_literature_search")
        registry.register(
            ToolUniverseEntry(
                name="lithoscribe_literature_synthesis",
                description="Backward-compatible alias for Archivon literature search.",
                domain="lithoscribe",
                adapter_type=AdapterType.DIRECT_REST,
                input_schema=LithoscribeSynthesisInput,
                canonical_id_types=["arxiv_id", "doi", "pmid"],
                timeout_seconds=40.0,
                tags=["literature", "citations", "papers"],
                is_async=True,
            ),
            executor=lambda **kwargs: arch_exec(**kwargs) if arch_exec else None,
        )

    # Legacy vivarix_* names run a named Dynamis preset (model_label) or are rejected; see _alias_system.
    dyn_exec = registry.get_executor("dynamis_simulate_ode")
    if dyn_exec is not None and registry.get_entry("vivarix_simulate_time_course") is None:
        registry.register(
            ToolUniverseEntry(
                name="vivarix_simulate_time_course",
                description=(
                    "Backward-compatible alias for Dynamis ODE simulation of a named preset (model_label); BioModels "
                    "and SBML models are not available."
                ),
                domain="vivarix",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=VivarixSimInput,
                canonical_id_types=["computation_id"],
                timeout_seconds=45.0,
                tags=["simulation", "ode", "kinetics"],
            ),
            executor=_vivarix_sim_alias(dyn_exec),
        )

    dyn_scan_exec = registry.get_executor("dynamis_parameter_scan")
    if dyn_scan_exec is not None and registry.get_entry("vivarix_parameter_scan") is None:
        registry.register(
            ToolUniverseEntry(
                name="vivarix_parameter_scan",
                description="Backward-compatible alias for a Dynamis parameter scan of a named preset (model_label).",
                domain="vivarix",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=VivarixParamScanInput,
                canonical_id_types=["computation_id"],
                timeout_seconds=120.0,
                tags=["parameter_scan", "sensitivity"],
            ),
            executor=_vivarix_scan_alias(dyn_scan_exec),
        )

    dyn_eq_exec = registry.get_executor("dynamis_equilibrium")
    if dyn_eq_exec is not None and registry.get_entry("vivarix_compute_steady_state") is None:
        registry.register(
            ToolUniverseEntry(
                name="vivarix_compute_steady_state",
                description="Backward-compatible alias for the Dynamis equilibrium solver on a named preset (model_label).",
                domain="vivarix",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=VivarixSteadyStateInput,
                canonical_id_types=["computation_id"],
                timeout_seconds=30.0,
                tags=["steady_state", "equilibrium"],
            ),
            executor=_vivarix_steady_alias(dyn_eq_exec),
        )



    # Substrate engineering tools: Materials, Standards, CAD Geometry, CAE five-gate screen (F-01..F-04)
    if registry.get_entry("substrate_material_lookup") is None:
        def _exec_mat(material_name: str, temperature_celsius: float = 20.0, **kwargs: Any) -> dict[str, Any]:
            from ..substrate.materials import get_material, list_materials, material_properties
            mat = get_material(material_name)
            if not mat:
                return {"found": False, "error": f"Material '{material_name}' is not an exact catalogue name or alias",
                        "available": list_materials()}
            return {"found": True, **material_properties(mat, temperature_celsius)}

        registry.register(
            ToolUniverseEntry(
                name="substrate_material_lookup",
                description=(
                    "Look up typical room-temperature (15-25 C) mechanical and thermal properties of five catalogued "
                    "alloys (Al 6061-T6, AISI 4140, Ti-6Al-4V, 316L, Inconel 718). Not design allowables; no data at "
                    "other temperatures."
                ),
                domain="substrate",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=SubstrateMaterialInput,
                timeout_seconds=10.0,
                tags=["material", "properties", "mechanics", "thermal"],
            ),
            executor=_exec_mat,
        )

    if registry.get_entry("substrate_standards_check") is None:
        def _exec_std(clause_id: str = "ASME_VIII_1_UG27_CYL", **kwargs: Any) -> dict[str, Any]:
            from ..substrate.standards import check_asme_compliance
            return check_asme_compliance(kwargs, clause_id=clause_id)

        registry.register(
            ToolUniverseEntry(
                name="substrate_standards_check",
                description=(
                    "ASME Section VIII Div 1 UG-27 minimum thickness under internal pressure for cylindrical "
                    "(ASME_VIII_1_UG27_CYL, (c)(1) and (c)(2)) and spherical (ASME_VIII_1_UG27_SPH, (d)) shells, "
                    "within the clause's applicability limits; other clauses are reported as not evaluated."
                ),
                domain="substrate",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=SubstrateStandardsInput,
                timeout_seconds=10.0,
                tags=["standards", "asme", "compliance", "pressure_vessel"],
            ),
            executor=_exec_std,
        )

    if registry.get_entry("substrate_geometry_inspect") is None:
        def _exec_cad(stl_content: str = "", file_name: str = "model.stl", material_density_kg_m3: float = 2700.0, **kwargs: Any) -> dict[str, Any]:
            from ..substrate.cad.inspector import GeometryInspector
            try:
                geom = GeometryInspector.inspect_stl_ascii(stl_content, file_name=file_name, density_kg_m3=material_density_kg_m3)
            except ValueError as exc:
                return {"status": "error", "error": str(exc)}
            return {"status": "ok", **geom.to_dict()}

        registry.register(
            ToolUniverseEntry(
                name="substrate_geometry_inspect",
                description=(
                    "Inspect an ASCII STL mesh given as text: bounding box and facet surface area; volume, mass and "
                    "centre of gravity by the divergence theorem when the mesh is closed (None otherwise)."
                ),
                domain="substrate",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=SubstrateGeometryInput,
                timeout_seconds=15.0,
                tags=["cad", "geometry", "3d", "mass_properties"],
            ),
            executor=_exec_cad,
        )

    if registry.get_entry("substrate_cae_review") is None:
        def _exec_cae(**kwargs: Any) -> dict[str, Any]:
            from ..substrate.cae.review import CAEReviewer
            return CAEReviewer.run_full_cae_audit(
                applied_load_n=float(kwargs.get("applied_load_n", 0.0)),
                reaction_force_n=float(kwargs.get("reaction_force_n", 0.0)),
                coarse_stress_mpa=float(kwargs.get("coarse_stress_mpa", 0.0)),
                fine_stress_mpa=float(kwargs.get("fine_stress_mpa", 0.0)),
                yield_strength_mpa=float(kwargs.get("yield_strength_mpa", 0.0)),
                analytical_stress_mpa=float(kwargs.get("analytical_stress_mpa", 0.0)),
                stress_gradient_ratio=(None if kwargs.get("stress_gradient_ratio") is None
                                       else float(kwargs["stress_gradient_ratio"])),
            )

        registry.register(
            ToolUniverseEntry(
                name="substrate_cae_review",
                description=(
                    "Screen FEA/CAE summary values against five gates: reaction equilibrium, mesh convergence, "
                    "linear-elastic validity, singularity screen, hand-calculation cross-check."
                ),
                domain="substrate",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=SubstrateCAEInput,
                timeout_seconds=15.0,
                tags=["cae", "fea", "simulation_verification", "mesh_convergence"],
            ),
            executor=_exec_cae,
        )

    # External MCP tool servers the operator configured (TRIBOS_MCP_CLIENT_SERVERS).
    try:
        from .mcp_client import register_mcp_tools

        register_mcp_tools(registry)
    except Exception as exc:  # noqa: BLE001 - a bad MCP configuration never blocks the built-in tools
        logger.warning("MCP client tools not registered: %s", exc)

# Global singleton instance
_GLOBAL_REGISTRY: ToolRegistry | None = None
_REGISTRY_COMPLETE = False
_REGISTRY_LAST_ATTEMPT = 0.0
_REGISTRY_RETRY_SECONDS = 60.0


def get_tool_registry() -> ToolRegistry:
    """
    Return the global ToolUniverse registry singleton with default tools registered.
    If registration failed part-way (e.g. an optional dependency was briefly unavailable), it is retried on a
    later call, at most once per minute, instead of serving a half-populated registry for the process lifetime.
    """
    global _GLOBAL_REGISTRY, _REGISTRY_COMPLETE, _REGISTRY_LAST_ATTEMPT
    if _GLOBAL_REGISTRY is not None and (_REGISTRY_COMPLETE or time.monotonic() - _REGISTRY_LAST_ATTEMPT < _REGISTRY_RETRY_SECONDS):
        return _GLOBAL_REGISTRY
    _REGISTRY_LAST_ATTEMPT = time.monotonic()
    candidate = ToolRegistry()
    try:
        register_default_tools(candidate)
        _REGISTRY_COMPLETE = True
    except Exception as e:
        logger.warning("Failed to register default tools (will retry): %s", e)
        if _GLOBAL_REGISTRY is not None and len(_GLOBAL_REGISTRY.list_tools()) >= len(candidate.list_tools()):
            return _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = candidate
    return _GLOBAL_REGISTRY

