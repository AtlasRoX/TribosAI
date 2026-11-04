"""
Shared offline fakes: a tool registry with the real input schemas and recording executors, and an
orchestrator wired to it with the LLM disabled and memory in a temporary directory.

Feature tests add their own tools with extra_tools={"tool_name": (InputSchema, fake)}, where fake(kwargs)
returns the tool's data dict or a ToolResult. Fakes must return trimmed real responses, never invented data.

Evidence-source tests that call ``registry.execute(tool, **kwargs)`` directly use RecordingRegistry (any
handler).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class SynaptaSearchInput(BaseModel):
    query: str
    size: int = Field(default=5, ge=1, le=25)


class SynaptaAssocInput(BaseModel):
    ensembl_id: str = Field(..., pattern=r"^ENSG\d{11}$")
    size: int = Field(default=10, ge=1, le=50)


class SynaptaKeggInput(BaseModel):
    target_symbol: str


class LumicellPipelineInput(BaseModel):
    dataset_path: str
    target_gene: str | None = None
    dataset_name: str | None = None
    max_pct_mt: float = 20.0
    n_neighbors: int | None = None
    resolution: float = 0.5


from tribos.agents import authoritative_orchestrator as orch_module
from tribos.agents.authoritative_orchestrator import AuthoritativeOrchestrator
from tribos.axiom.schemas import (
    AxiomCalculusInput,
    AxiomSimplifyInput,
    AxiomSolveInput,
)
from tribos.dynamis.schemas import DynamisParameterScanInput, DynamisSimulateOdeInput
from tribos.extensions.archivon import ArchivonLiteratureSearchInput
from tribos.extensions.physis import PhysisConstantsInput
from tribos.extensions.sandbox import AnalysisRunInput
from tribos.tools import registry as registry_module
from tribos.tools.registry import (
    AdapterType,
    ToolRegistry,
    ToolResult,
    ToolUniverseEntry,
)
from tribos.utils.memory.research_memory import ResearchMemoryEngine

ExtraTools = dict[str, tuple[type[BaseModel], Callable[[dict[str, Any]], Any]]]
Calls = list[tuple[str, dict[str, Any]]]

_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    # Tribos STEM tools
    "archivon_literature_search": ArchivonLiteratureSearchInput,
    "axiom_simplify": AxiomSimplifyInput,
    "axiom_solve": AxiomSolveInput,
    "axiom_calculus": AxiomCalculusInput,
    "dynamis_simulate_ode": DynamisSimulateOdeInput,
    "dynamis_parameter_scan": DynamisParameterScanInput,
    "physis_constants": PhysisConstantsInput,
    "calcula_run_python": AnalysisRunInput,
    "analysis_run_python": AnalysisRunInput,
    # Backward-compatible fallbacks
    "synapta_opentargets_search": SynaptaSearchInput,
    "synapta_opentargets_associations": SynaptaAssocInput,
    "synapta_kegg_pathways": SynaptaKeggInput,
    "lumicell_analyze_single_cell": LumicellPipelineInput,
    "vivarix_simulate_time_course": registry_module.VivarixSimInput,
    "vivarix_compute_steady_state": registry_module.VivarixSteadyStateInput,
    "vivarix_parameter_scan": registry_module.VivarixParamScanInput,
    "lithoscribe_literature_synthesis": registry_module.LithoscribeSynthesisInput,
    "websurfer_search": registry_module.WebSurferSearchInput,
}


def _fake_output(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "synapta_opentargets_search":
        return {"results": [{"id": "ENSG00000133703", "name": kwargs.get("query", "KRAS")}]}
    if tool_name == "synapta_opentargets_associations":
        return {"associations": [{"disease_name": "pancreatic carcinoma", "overall_association_score": 0.83}]}
    if tool_name == "synapta_kegg_pathways":
        return {"results": [{"id": "hsa04010", "description": "MAPK signaling pathway - Homo sapiens (human)"}]}
    if tool_name == "lumicell_analyze_single_cell":
        return {
            "dataset_path": kwargs.get("dataset_path", ""),
            "n_cells_post_qc": 100,
            "n_clusters": 2,
            "top_markers_by_cluster": {"0": [{"gene": "CD3E", "cluster": "0", "log_fold_change": 2.0, "p_adj": 0.001}]},
            "target_expression_summary": {},
        }
    if tool_name == "archivon_literature_search":
        q = str(kwargs.get("query", ""))
        pmid = "123456" if "KRAS" in q else None
        p_text = "KRAS signaling in pancreatic cancer." if "KRAS" in q else "Navier-Stokes solutions."
        rec = {"passage_text": p_text, "title": "Paper on " + (q or "Fluid Dynamics")}
        if pmid:
            rec["pmid"] = pmid
        else:
            rec["arxiv_id"] = "1706.03762"
        return {
            "ranked_passages": [rec],
            "total_found": 1,
            "key_findings": [p_text],
        }
    if tool_name in ("axiom_simplify", "axiom_solve", "axiom_calculus"):
        return {"result": "x**2", "latex": "x^2", "verified": True}
    if tool_name == "dynamis_simulate_ode":
        dur = float((kwargs.get("t_span") or (0.0, 120.0))[1]) if isinstance(kwargs.get("t_span"), (list, tuple)) else 120.0
        return {
            "verified": True,
            "canonical_id": "comp:dynamis_simulate_ode:test",
            "model_id": kwargs.get("model_name") or "BIOMD0000000010",
            "model_name": "Fake MAPK",
            "simulation_type": "TIME_COURSE",
            "duration": dur,
            "units": {"time": "s", "quantity": "nmol"},
            "initial_concentrations": {"Mos": 100.0, "Mos-P": 0.0},
            "final_concentrations": {"Mos": 34.13, "Mos-P": 65.87},
            "summary": {"x": {"initial": 1.0, "final": 0.5}},
            "trajectory": {"t": [0.0, 1.0], "x": [1.0, 0.5]},
        }
    if tool_name == "physis_constants":
        return {
            "count": 1,
            "constants": [
                {
                    "name": "speed of light in vacuum",
                    "symbol": "c",
                    "value": 299792458.0,
                    "uncertainty": 0.0,
                    "source": "NIST CODATA 2022",
                }
            ],
        }
    if tool_name in ("calcula_run_python", "analysis_run_python"):
        return {"output": "42\n", "figures": [], "success": True}
    if tool_name == "vivarix_simulate_time_course":
        return {
            "model_id": kwargs["biomodel_id"],
            "model_name": "Fake MAPK",
            "simulation_type": "TIME_COURSE",
            "duration": kwargs["duration"],
            "units": {"time": "s", "quantity": "nmol"},
            "initial_concentrations": {"Mos": 100.0, "Mos-P": 0.0},
            "final_concentrations": {"Mos": 34.13, "Mos-P": 65.87},
        }
    if tool_name == "vivarix_compute_steady_state":
        return {"model_id": kwargs["biomodel_id"], "simulation_type": "STEADY_STATE", "steady_state_concentrations": {"Mos": 30.0}}
    if tool_name == "vivarix_parameter_scan":
        n_steps = kwargs.get("num_steps", 5)
        start_v = kwargs.get("start_val", 0.1)
        end_v = kwargs.get("end_val", 1.0)
        p_name = kwargs.get("parameter_name", "V1")
        step_vals = [start_v + (end_v - start_v) * i / max(1, n_steps - 1) for i in range(n_steps)]
        return {
            "model_id": kwargs.get("biomodel_id", "BIOMD0000000010"),
            "resolved_parameter": p_name,
            "duration_seconds": kwargs.get("duration", 60.0),
            "total_points": n_steps,
            "successful_points": n_steps,
            "scan_results": [
                {
                    "parameter_value": round(v, 6),
                    "applied_value": round(v, 6),
                    "target_response": 10.0 + i,
                    "endpoint_species": {"Erk2-PP": 10.0 + i, "Mos": 34.13, "Mos-P": 65.87},
                }
                for i, v in enumerate(step_vals)
            ],
            "failed_points": [],
        }
    if tool_name == "lithoscribe_literature_synthesis":
        return {"ranked_passages": [{"pmid": "123456", "passage_text": "KRAS signaling in pancreatic cancer."}], "key_findings": ["KRAS signaling in pancreatic cancer."]}
    return {"results": []}


def _register(reg: ToolRegistry, name: str, schema: type[BaseModel], executor: Callable[..., Any]) -> None:
    desc = f"fake {name}"
    tags = []
    if name == "synapta_kegg_pathways":
        desc = "KEGG pathways that contain a gene symbol."
        tags = ["pathway", "kegg", "target"]
    elif name == "synapta_opentargets_search":
        desc = "Search Open Targets for a gene, target or disease."
        tags = ["target", "opentargets"]
    elif name == "synapta_opentargets_associations":
        desc = "Retrieve disease associations for a target."
        tags = ["target", "association"]
    elif name == "vivarix_simulate_time_course":
        tags = ["simulation", "copasi", "biomodels", "ode"]
    elif name == "vivarix_compute_steady_state":
        tags = ["simulation", "steady_state"]
    elif name == "vivarix_parameter_scan":
        tags = ["simulation", "scan"]
    elif name == "lumicell_analyze_single_cell":
        tags = ["single_cell", "scanpy", "anndata"]
    elif name == "lithoscribe_literature_synthesis":
        tags = ["literature", "europepmc", "citations"]
    elif name == "websurfer_search":
        tags = ["web", "search"]
    reg.register(
        ToolUniverseEntry(
            name=name,
            description=desc,
            domain=name.split("_")[0],
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=schema,
            canonical_id_types=[],
            timeout_seconds=10.0,
            tags=tags,
        ),
        executor=executor,
    )
def build_recording_registry(extra_tools: ExtraTools | None = None) -> tuple[ToolRegistry, Calls]:
    """Registry with the real input schemas and fake executors that record validated calls."""
    calls: Calls = []
    reg = ToolRegistry()
    for name, schema in _TOOL_SCHEMAS.items():
        def make_executor(tool_name: str):
            def executor(**kwargs: Any) -> dict[str, Any]:
                calls.append((tool_name, kwargs))
                return _fake_output(tool_name, kwargs)
            return executor

        _register(reg, name, schema, make_executor(name))

    for name, (schema, fake) in (extra_tools or {}).items():
        def make_extra(tool_name: str, fn: Callable[[dict[str, Any]], Any]):
            def executor(**kwargs: Any) -> Any:
                calls.append((tool_name, kwargs))
                return fn(kwargs)
            return executor

        _register(reg, name, schema, make_extra(name, fake))
    return reg, calls


def make_offline_orchestrator(monkeypatch, tmp_path, extra_tools: ExtraTools | None = None) -> tuple[AuthoritativeOrchestrator, Calls]:
    """The offline_orchestrator fixture as a function: recording registry, no LLM, memory under tmp_path."""
    reg, calls = build_recording_registry(extra_tools)
    monkeypatch.setattr(orch_module, "get_tool_registry", lambda: reg)
    monkeypatch.setenv("TRIBOS_RUNS_DIR", str(tmp_path / "runs"))

    def no_llm(*_args, **_kwargs):
        raise RuntimeError("LLM disabled in offline tests")

    monkeypatch.setattr(orch_module, "get_llm", no_llm)
    orch = AuthoritativeOrchestrator()
    orch.memory = ResearchMemoryEngine(storage_dir=str(tmp_path / "mem"))
    return orch, calls


def called(calls: Calls, tool_name: str) -> list[dict[str, Any]]:
    return [kw for name, kw in calls if name == tool_name]


_called = called


class RecordingRegistry:
    """Stand-in for the async tool registry seen by evidence sources: ``await reg.execute(tool, **kwargs)``.

    Records each call (``calls``: tool names, ``kwargs``: their arguments, in call order) and the peak number of
    overlapping calls (``max_active``). ``handler(tool, kwargs)`` returns the ToolResult, directly or as an
    awaitable. ``delay`` holds each call open so concurrent calls overlap.
    """

    def __init__(self, handler: Callable[[str, dict[str, Any]], Any], *, delay: float = 0.0) -> None:
        self.handler = handler
        self.delay = delay
        self.calls: list[str] = []
        self.kwargs: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def execute(self, tool: str, **kwargs: Any) -> ToolResult:
        self.calls.append(tool)
        self.kwargs.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            result = self.handler(tool, kwargs)
            return await result if inspect.isawaitable(result) else result
        finally:
            self.active -= 1
