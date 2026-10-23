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
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from tribos.agents import authoritative_orchestrator as orch_module
from tribos.agents.authoritative_orchestrator import AuthoritativeOrchestrator
from tribos.tools import registry as registry_module
from tribos.tools.registry import (
    AdapterType,
    ToolRegistry,
    ToolResult,
    ToolUniverseEntry,
)
from tribos.utils.memory.research_memory import ResearchMemoryEngine

ExtraTools = Dict[str, Tuple[Type[BaseModel], Callable[[Dict[str, Any]], Any]]]
Calls = List[Tuple[str, Dict[str, Any]]]

_TOOL_SCHEMAS = {
    "vivarix_simulate_time_course": registry_module.VivarixSimInput,
    "vivarix_compute_steady_state": registry_module.VivarixSteadyStateInput,
    "vivarix_parameter_scan": registry_module.VivarixParamScanInput,
    "lithoscribe_literature_synthesis": registry_module.LithoscribeSynthesisInput,
    "websurfer_search": registry_module.WebSurferSearchInput,
}


def _fake_output(tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
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
        return {"ranked_passages": [{"pmid": "123456", "passage_text": "KRAS signaling in pancreatic cancer."}]}
    return {"results": []}


def _register(reg: ToolRegistry, name: str, schema: Type[BaseModel], executor: Callable[..., Any]) -> None:
    reg.register(
        ToolUniverseEntry(
            name=name,
            description=f"fake {name}",
            domain=name.split("_")[0],
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=schema,
            canonical_id_types=[],
            timeout_seconds=10.0,
            tags=[],
        ),
        executor=executor,
    )


def build_recording_registry(extra_tools: Optional[ExtraTools] = None) -> Tuple[ToolRegistry, Calls]:
    """Registry with the real input schemas and fake executors that record validated calls."""
    calls: Calls = []
    reg = ToolRegistry()
    for name, schema in _TOOL_SCHEMAS.items():
        def make_executor(tool_name: str):
            def executor(**kwargs: Any) -> Dict[str, Any]:
                calls.append((tool_name, kwargs))
                return _fake_output(tool_name, kwargs)
            return executor

        _register(reg, name, schema, make_executor(name))

    for name, (schema, fake) in (extra_tools or {}).items():
        def make_extra(tool_name: str, fn: Callable[[Dict[str, Any]], Any]):
            def executor(**kwargs: Any) -> Any:
                calls.append((tool_name, kwargs))
                return fn(kwargs)
            return executor

        _register(reg, name, schema, make_extra(name, fake))
    return reg, calls


def make_offline_orchestrator(monkeypatch, tmp_path, extra_tools: Optional[ExtraTools] = None) -> Tuple[AuthoritativeOrchestrator, Calls]:
    """The offline_orchestrator fixture as a function: recording registry, no LLM, memory under tmp_path."""
    reg, calls = build_recording_registry(extra_tools)
    monkeypatch.setattr(orch_module, "get_tool_registry", lambda: reg)
    monkeypatch.setenv("TRIBOS_RUNS_DIR", str(tmp_path / "runs"))

    def no_llm(*_args, **_kwargs):
        raise RuntimeError("LLM disabled in offline tests")

    monkeypatch.setattr(orch_module, "get_llm", no_llm)
    orch = AuthoritativeOrchestrator()
    orch.memory = ResearchMemoryEngine(storage_dir=str(tmp_path / "mem"))
    monkeypatch.setattr(orch.vivarix, "search_models", lambda *_a, **_k: [{"accession": "BIOMD0000000010"}])
    return orch, calls


def called(calls: Calls, tool_name: str) -> List[Dict[str, Any]]:
    return [kw for name, kw in calls if name == tool_name]


_called = called


class RecordingRegistry:
    """Stand-in for the async tool registry seen by evidence sources: ``await reg.execute(tool, **kwargs)``.

    Records each call (``calls``: tool names, ``kwargs``: their arguments, in call order) and the peak number of
    overlapping calls (``max_active``). ``handler(tool, kwargs)`` returns the ToolResult, directly or as an
    awaitable. ``delay`` holds each call open so concurrent calls overlap.
    """

    def __init__(self, handler: Callable[[str, Dict[str, Any]], Any], *, delay: float = 0.0) -> None:
        self.handler = handler
        self.delay = delay
        self.calls: List[str] = []
        self.kwargs: List[Dict[str, Any]] = []
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
