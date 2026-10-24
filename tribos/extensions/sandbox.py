"""
Extension module for Calcula (sandboxed Python computation and dataset analysis).
Registers `calcula_run_python`, `calcula_describe_dataset`, and the legacy alias `analysis_run_python`.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from pydantic import BaseModel, Field, field_validator

TOOL_NAME = "analysis_run_python"
CALCULA_RUN_TOOL = "calcula_run_python"
CALCULA_DESCRIBE_TOOL = "calcula_describe_dataset"


class AnalysisRunInput(BaseModel):
    code: str = Field(..., min_length=1, max_length=20000, description="Python computation or analysis code; set `result` to the answer values")
    dataset_ids: list[str] = Field(default_factory=list, max_length=5, description="Optional attached dataset ids (ds_...) the code reads")
    timeout_s: int = Field(default=60, ge=5, le=110)

    @field_validator("dataset_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        from tribos.agentic.sandbox import DATASET_ID_RE

        bad = [v for v in value if not DATASET_ID_RE.match(str(v))]
        if bad:
            raise ValueError(f"dataset ids must look like ds_<12 hex>: {bad[:3]}")
        return value


class CalculaDescribeDatasetInput(BaseModel):
    dataset_id: str = Field(..., description="Attached dataset id (ds_<12 hex>) to inspect and summarize")

    @field_validator("dataset_id")
    @classmethod
    def _id(cls, value: str) -> str:
        from tribos.agentic.sandbox import DATASET_ID_RE

        if not DATASET_ID_RE.match(str(value)):
            raise ValueError(f"dataset_id must look like ds_<12 hex>: {value!r}")
        return str(value)


def _run_python_impl(tool_name: str, code: str, dataset_ids: list[str] | None = None, timeout_s: int = 60) -> Any:
    from tribos.agentic.sandbox import (
        current_scope,
        resolve_inputs,
        sandbox_enabled,
        sandbox_memory_mb,
        sandbox_timeout_s,
    )
    from tribos.agentic.sandbox.runner import run_code
    from tribos.tools.registry import ErrorType, ToolResult

    if not sandbox_enabled():
        return ToolResult(
            success=False,
            tool_name=tool_name,
            data={"status": "disabled"},
            error="Code execution is disabled on this server (set TRIBOS_SANDBOX=on to enable it).",
            error_type=ErrorType.VALIDATION_ERROR,
        )
    inputs, errors = resolve_inputs(current_scope(), dataset_ids or [])
    if errors:
        return ToolResult(
            success=False,
            tool_name=tool_name,
            data={"status": "error", "errors": errors},
            error="; ".join(errors)[:400],
            error_type=ErrorType.DATASET_REQUIRED,
        )
    report = run_code(
        code,
        {i.name: i.path for i in inputs},
        timeout_s=min(int(timeout_s), sandbox_timeout_s()),
        memory_mb=sandbox_memory_mb(),
    )
    report["inputs"] = [{"dataset_id": i.dataset_id, "name": i.name, "kind": i.kind} for i in inputs]
    digest = hashlib.sha256(f"{code}:{dataset_ids}".encode()).hexdigest()[:10]
    cid = f"comp:{tool_name}:{digest}"
    report["canonical_id"] = cid
    status = report.get("status")
    if status == "ok":
        cids = {"computation_id": cid}
        if inputs:
            cids["dataset_id"] = ",".join(i.dataset_id for i in inputs)
        return ToolResult(
            success=True,
            tool_name=tool_name,
            data=report,
            canonical_ids=cids,
            metadata={"sandbox": "subprocess"},
        )
    error_type = {
        "timeout": ErrorType.TIMEOUT,
        "policy_violation": ErrorType.VALIDATION_ERROR,
    }.get(str(status), ErrorType.INTERNAL_ERROR)
    detail = report.get("error") or status
    if report.get("violations"):
        detail = f"{detail}: " + "; ".join(report["violations"][:5])
    return ToolResult(success=False, tool_name=tool_name, data=report, error=str(detail)[:600], error_type=error_type)


def run_analysis(code: str, dataset_ids: list[str] | None = None, timeout_s: int = 60) -> Any:
    """Executor for analysis_run_python (and backward-compatible callers)."""
    return _run_python_impl(TOOL_NAME, code, dataset_ids or [], timeout_s)


def run_calcula_python(code: str, dataset_ids: list[str] | None = None, timeout_s: int = 60) -> Any:
    """Executor for calcula_run_python."""
    return _run_python_impl(CALCULA_RUN_TOOL, code, dataset_ids or [], timeout_s)


def _describe_resolved_file(inp: Any) -> dict[str, Any]:
    ext = os.path.splitext(inp.path)[1].lower()
    if inp.kind == "table" or ext in (".csv", ".tsv", ".xlsx", ".parquet", ".json"):
        import pandas as pd

        if ext == ".tsv" or inp.sep == "\t":
            df = pd.read_csv(inp.path, sep="\t")
        elif ext == ".xlsx":
            df = pd.read_excel(inp.path)
        elif ext == ".parquet":
            df = pd.read_parquet(inp.path)
        elif ext == ".json":
            df = pd.read_json(inp.path)
        else:
            df = pd.read_csv(inp.path)
        cols = [{"name": str(c), "dtype": str(t), "missing": int(df[c].isna().sum())} for c, t in list(df.dtypes.items())[:100]]
        numeric = df.select_dtypes(include="number")
        summary_stats: dict[str, Any] = {}
        if not numeric.empty:
            desc = numeric.describe().round(6)
            summary_stats = {str(col): {str(stat): float(val) for stat, val in desc[col].items() if pd.notna(val)} for col in list(numeric.columns)[:50]}
        return {
            "dataset_id": inp.dataset_id,
            "name": inp.name,
            "kind": "table",
            "n_rows": int(df.shape[0]),
            "n_columns": int(df.shape[1]),
            "columns": cols,
            "summary_statistics": summary_stats,
            "head": df.head(5).to_dict(orient="records"),
        }

    if inp.kind in ("hdf5", "h5ad") or ext in (".h5", ".hdf5", ".h5ad"):
        import h5py

        datasets_info: list[dict[str, Any]] = []
        with h5py.File(inp.path, "r") as f:
            def _visit(name: str, obj: Any) -> None:
                if isinstance(obj, h5py.Dataset) and len(datasets_info) < 100:
                    datasets_info.append({
                        "path": name,
                        "shape": [int(s) for s in obj.shape],
                        "dtype": str(obj.dtype),
                    })

            f.visititems(_visit)
            attrs = {str(k): str(v)[:200] for k, v in list(f.attrs.items())[:30]}
        return {
            "dataset_id": inp.dataset_id,
            "name": inp.name,
            "kind": "hdf5",
            "datasets": datasets_info,
            "attributes": attrs,
        }

    if inp.kind == "mat" or ext == ".mat":
        from scipy import io as spio

        info = spio.whosmat(inp.path)
        variables = [{"name": str(name), "shape": [int(s) for s in shape], "dtype": str(dtype)} for name, shape, dtype in info[:100]]
        return {
            "dataset_id": inp.dataset_id,
            "name": inp.name,
            "kind": "mat",
            "variables": variables,
        }

    raise ValueError(f"Unsupported dataset kind {inp.kind!r}")


def describe_dataset(dataset_id: str) -> Any:
    """Executor for calcula_describe_dataset."""
    from tribos.agentic.sandbox import current_scope, resolve_inputs, sandbox_enabled
    from tribos.tools.registry import ErrorType, ToolResult

    if not sandbox_enabled():
        return ToolResult(
            success=False,
            tool_name=CALCULA_DESCRIBE_TOOL,
            data={"status": "disabled"},
            error="Sandbox dataset inspection is disabled (set TRIBOS_SANDBOX=on to enable it).",
            error_type=ErrorType.VALIDATION_ERROR,
        )
    inputs, errors = resolve_inputs(current_scope(), [dataset_id])
    if errors or not inputs:
        return ToolResult(
            success=False,
            tool_name=CALCULA_DESCRIBE_TOOL,
            data={"status": "error", "errors": errors},
            error="; ".join(errors)[:400] if errors else f"Dataset {dataset_id} not available",
            error_type=ErrorType.DATASET_REQUIRED,
        )
    try:
        summary = _describe_resolved_file(inputs[0])
        cid = f"comp:{CALCULA_DESCRIBE_TOOL}:{inputs[0].dataset_id}"
        summary["canonical_id"] = cid
        return ToolResult(
            success=True,
            tool_name=CALCULA_DESCRIBE_TOOL,
            data=summary,
            canonical_ids={"dataset_id": inputs[0].dataset_id, "computation_id": cid},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            tool_name=CALCULA_DESCRIBE_TOOL,
            error=f"{type(exc).__name__}: {exc}",
            error_type=ErrorType.INTERNAL_ERROR,
        )


def register_tools(registry: Any) -> None:
    """Register Calcula tools (`calcula_run_python`, `calcula_describe_dataset`, and alias `analysis_run_python`)."""
    from tribos.agentic.sandbox import sandbox_enabled
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    if not sandbox_enabled():
        return

    run_desc = (
        "Run Python computation and data analysis code (numpy, scipy, sympy, mpmath, networkx, pint, pandas, "
        "statsmodels, scikit-learn, matplotlib, h5py) in an isolated subprocess sandbox with no network. "
        "Set `result` to the computed values; open matplotlib figures are returned as PNG."
    )
    run_tags = ["analysis", "computation", "statistics", "code", "sandbox", "sympy", "numpy", "scipy", "pandas", "codeact", "plot"]

    registry.register(
        ToolUniverseEntry(
            name=CALCULA_RUN_TOOL,
            description=run_desc,
            domain="analysis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=AnalysisRunInput,
            canonical_id_types=["dataset_id", "computation_id"],
            timeout_seconds=120.0,
            tags=run_tags,
        ),
        executor=run_calcula_python,
    )
    registry.register(
        ToolUniverseEntry(
            name=TOOL_NAME,
            description=run_desc,
            domain="analysis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=AnalysisRunInput,
            canonical_id_types=["dataset_id", "computation_id"],
            timeout_seconds=120.0,
            tags=run_tags,
        ),
        executor=run_analysis,
    )
    registry.register(
        ToolUniverseEntry(
            name=CALCULA_DESCRIBE_TOOL,
            description=(
                "Inspect an attached dataset (table CSV/TSV/XLSX/Parquet/JSON, HDF5 .h5/.hdf5, or MATLAB .mat) and "
                "return its schema, dimensions, column/variable types, and summary statistics."
            ),
            domain="analysis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=CalculaDescribeDatasetInput,
            canonical_id_types=["dataset_id", "computation_id"],
            timeout_seconds=30.0,
            tags=["analysis", "dataset", "schema", "describe", "table", "hdf5", "mat"],
        ),
        executor=describe_dataset,
    )


__all__ = [
    "AnalysisRunInput",
    "CALCULA_DESCRIBE_TOOL",
    "CALCULA_RUN_TOOL",
    "CalculaDescribeDatasetInput",
    "TOOL_NAME",
    "describe_dataset",
    "register_tools",
    "run_analysis",
    "run_calcula_python",
]
