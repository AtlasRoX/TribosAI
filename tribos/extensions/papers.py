"""Extension module registering the paper tools: read an attached PDF and reproduce its stated results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

PAGE_TEXT_CHARS = 3000  # text kept per page in the tool result
MAX_TEXT_PAGES = 40


class ArchivonReadPaperInput(BaseModel):
    dataset_id: str = Field(..., pattern=r"^ds_[0-9a-f]{12}$", description="The attached paper's dataset id (ds_...).")


class ArchivonReproducePaperInput(BaseModel):
    dataset_id: str = Field(..., pattern=r"^ds_[0-9a-f]{12}$", description="The attached paper's dataset id (ds_...).")
    targets: list[str] | None = Field(
        default=None, max_length=50, description="Names of the stated results to check (all when omitted), e.g. ['T']."
    )


def _paper_path(tool: str, dataset_id: str) -> tuple[str | None, dict[str, Any] | None, Any]:
    """(path, record info, error result) for an attached paper of the current run."""
    from tribos.agentic.sandbox import current_scope
    from tribos.datasets.store import existing_dataset_store
    from tribos.tools.registry import ErrorType, ToolResult

    def fail(msg: str) -> tuple[None, None, Any]:
        return None, None, ToolResult(success=False, tool_name=tool, error=msg, error_type=ErrorType.DATASET_REQUIRED)

    scope = current_scope()
    if scope is None or dataset_id not in scope.dataset_ids:
        return fail(f"Paper {dataset_id} is not attached to this question; attach the PDF to read it.")
    store = existing_dataset_store()
    if store is None:
        return fail(f"Paper {dataset_id} not found.")
    resolved, errors = store.resolve_for_user(scope.owner_of(dataset_id), [dataset_id])
    if errors or not resolved:
        return fail("; ".join(errors) or f"Paper {dataset_id} not found.")
    att = resolved[0]
    if att.record.kind.value != "paper" or not att.analysis_path:
        return fail(f"Dataset {dataset_id} is not a paper (PDF).")
    return att.analysis_path, {"dataset_id": att.record.id, "file": att.record.display_name}, None


def _read(dataset_id: str) -> tuple[dict[str, Any] | None, Any]:
    from tribos.papers import extract_paper
    from tribos.tools.registry import ErrorType, ToolResult

    path, info, error = _paper_path("archivon_read_paper", dataset_id)
    if error is not None:
        return None, error
    try:
        data = extract_paper(path)
    except Exception as exc:  # noqa: BLE001
        return None, ToolResult(success=False, tool_name="archivon_read_paper", error=f"The PDF could not be read "
                                f"({type(exc).__name__}).", error_type=ErrorType.VALIDATION_ERROR)
    data["text"] = [{"page": p["page"], "text": p["text"][:PAGE_TEXT_CHARS], "ocr": p["ocr"]}
                    for p in data["text"][:MAX_TEXT_PAGES]]
    return {**(info or {}), **data}, None


def execute_read_paper(dataset_id: str) -> Any:
    from tribos.tools.registry import ToolResult

    data, error = _read(dataset_id)
    if error is not None:
        return error
    return ToolResult(success=True, tool_name="archivon_read_paper", data=data,
                      canonical_ids={"doi": data["doi"]} if data and data.get("doi") else {})


def execute_reproduce_paper(dataset_id: str, targets: list[str] | None = None) -> Any:
    from tribos.papers import reproduce_paper
    from tribos.tools.registry import ErrorType, ToolResult

    data, error = _read(dataset_id)
    if error is not None:
        return ToolResult(success=False, tool_name="archivon_reproduce_paper", error=error.error, error_type=error.error_type)
    try:
        result = reproduce_paper(data or {}, targets)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, tool_name="archivon_reproduce_paper", error=f"{type(exc).__name__}: {exc}",
                          error_type=ErrorType.INTERNAL_ERROR)
    paper = {k: (data or {}).get(k) for k in ("dataset_id", "file", "title", "authors", "doi", "arxiv_id", "n_pages")}
    out = {"paper": paper, "equations": (data or {}).get("equations") or [], "odes": (data or {}).get("odes") or [],
           **result}
    return ToolResult(success=True, tool_name="archivon_reproduce_paper", data=out,
                      metadata={"counts": result["counts"]}, canonical_ids={})


def register_tools(registry: Any) -> None:
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="archivon_read_paper",
            description=(
                "Read an uploaded paper (PDF attached to the question): title, authors, DOI or arXiv id, sections, "
                "numbered equations (as SymPy where possible), ODE systems, parameter values and stated numeric results, "
                "each with its page number and the verbatim source line."
            ),
            domain="archivon",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=ArchivonReadPaperInput,
            timeout_seconds=60.0,
            tags=["paper", "pdf", "uploads", "user_data", "extraction", "equations"],
            is_async=False,
        ),
        executor=execute_read_paper,
    )
    registry.register(
        ToolUniverseEntry(
            name="archivon_reproduce_paper",
            description=(
                "Reproduce the stated results of an uploaded paper (PDF) from its own equations and parameters: "
                "re-evaluate closed-form claims with SymPy and re-run its ODE systems with Dynamis. Each claim is "
                "reproduced, differs (with both values) or not reproducible (listing the missing inputs)."
            ),
            domain="archivon",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=ArchivonReproducePaperInput,
            timeout_seconds=90.0,
            tags=["paper", "pdf", "uploads", "user_data", "reproduction", "verification", "simulation"],
            is_async=False,
        ),
        executor=execute_reproduce_paper,
    )


def _paper_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The latest reproduction of an attached paper, or else its latest reading, for the result card."""
    reproduced = read = None
    for result in tool_results.values():
        data = getattr(result, "data", None)
        if not getattr(result, "success", False) or not isinstance(data, dict):
            continue
        if getattr(result, "tool_name", "") == "archivon_reproduce_paper":
            reproduced = data
        elif getattr(result, "tool_name", "") == "archivon_read_paper":
            read = data
    if reproduced is not None:
        return {"paper_reproduction": reproduced}
    if read is not None:
        paper = {k: read.get(k) for k in ("dataset_id", "file", "title", "authors", "doi", "arxiv_id", "n_pages")}
        return {"paper_reproduction": {"paper": paper, "equations": read.get("equations"), "odes": read.get("odes"),
                                       "parameters": read.get("parameters"), "stated_results": read.get("claims")}}
    return {}


def register_hooks() -> None:
    from tribos.extensions import hooks

    hooks.register_artifact_builder("paper_reproduction", _paper_artifact)


register_hooks()

__all__ = ["execute_read_paper", "execute_reproduce_paper", "register_hooks", "register_tools"]
