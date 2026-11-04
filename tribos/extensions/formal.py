"""Extension module registering the optional Lean 4 checker (tribos/verify/formal) as the axiom_formal_check tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AxiomFormalCheckInput(BaseModel):
    lean_code: str = Field(..., min_length=1, max_length=50_000, description="A complete Lean 4 file: theorem and proof.")


def execute_formal_check(lean_code: str) -> Any:
    from tribos.tools.policy import active_tool_policy
    from tribos.tools.registry import ErrorType, ToolResult
    from tribos.verify.formal import check_lean, lean_statement

    pol = active_tool_policy()
    if pol is not None and pol.prohibit_formal:
        return ToolResult(
            success=False,
            tool_name="axiom_formal_check",
            error=pol.formal_reason or "Formal prover disabled by user request.",
            error_type=ErrorType.VALIDATION_ERROR,
            metadata={"skipped_by_policy": "disabled_by_user", "failure_class": "policy"},
        )

    result = check_lean(lean_code)
    data = {**result, "lean_code": lean_code, "statement": lean_statement(lean_code)}
    if result["status"] == "unavailable":
        return ToolResult(success=False, tool_name="axiom_formal_check", data=data, error=result.get("error"),
                          error_type=ErrorType.VALIDATION_ERROR)
    return ToolResult(success=True, tool_name="axiom_formal_check", data=data, canonical_ids={},
                      metadata={"formal_status": result["status"]})


def register_tools(registry: Any) -> None:
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    registry.register(
        ToolUniverseEntry(
            name="axiom_formal_check",
            description=(
                "Check a Lean 4 proof with the Lean compiler (optional: only when Lean is installed). Reports "
                "'formally verified (Lean)' only for a clean compile without sorry, admit or new axioms; otherwise the "
                "compiler errors. Executes the Lean toolchain."
            ),
            domain="axiom",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=AxiomFormalCheckInput,
            timeout_seconds=180.0,
            tags=["proof", "lean", "formal_verification", "theorem", "executes_code"],
            is_async=False,
        ),
        executor=execute_formal_check,
    )


def _formal_artifact(tool_results: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The latest Lean check of the turn (the agentic phase writes its own richer artifact)."""
    latest = None
    for result in tool_results.values():
        if getattr(result, "tool_name", "") == "axiom_formal_check" and isinstance(getattr(result, "data", None), dict):
            latest = result.data
    return {"formal_proof": latest} if latest else {}


def register_hooks() -> None:
    from tribos.extensions import hooks

    hooks.register_artifact_builder("formal_proof", _formal_artifact)


register_hooks()

__all__ = ["AxiomFormalCheckInput", "execute_formal_check", "register_hooks", "register_tools"]
