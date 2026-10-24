"""Extension module registering Axiom symbolic mathematics tools into the Tribos ToolRegistry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tribos.axiom.engine import (
    axiom_calculus,
    axiom_dsolve,
    axiom_latex,
    axiom_linalg,
    axiom_simplify,
    axiom_solve,
    axiom_verify_identity,
)
from tribos.axiom.schemas import (
    AxiomCalculusInput,
    AxiomDsolveInput,
    AxiomLatexInput,
    AxiomLinalgInput,
    AxiomSimplifyInput,
    AxiomSolveInput,
    AxiomVerifyIdentityInput,
)


def _wrap_executor(tool_name: str, fn: Callable[..., dict[str, Any]]) -> Callable[..., Any]:
    def _exec(**kwargs: Any) -> Any:
        from tribos.tools.registry import ErrorType, ToolResult

        try:
            data = fn(**kwargs)
            cid = str(data.get("canonical_id") or "")
            canonical_ids = {"computation_id": cid} if cid else {}
            return ToolResult(
                success=True,
                tool_name=tool_name,
                data=data,
                canonical_ids=canonical_ids,
                metadata={"engine": "sympy", "verified": bool(data.get("verified", True))},
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=str(exc),
                error_type=ErrorType.VALIDATION_ERROR,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"{type(exc).__name__}: {exc}",
                error_type=ErrorType.INTERNAL_ERROR,
            )

    _exec.__name__ = f"execute_{tool_name}"
    return _exec


def register_tools(registry: Any) -> None:
    """Register all 7 Axiom symbolic mathematics tools in the ToolRegistry."""
    from tribos.tools.registry import AdapterType, ToolUniverseEntry

    specs = [
        (
            "axiom_simplify",
            "Simplify, factor, expand, trig-simplify, and cancel a symbolic mathematical expression using SymPy.",
            AxiomSimplifyInput,
            axiom_simplify,
            ["symbolic", "simplify", "factor", "expand", "algebra", "sympy"],
        ),
        (
            "axiom_solve",
            "Solve algebraic or transcendental equations and systems of equations symbolically, verifying solutions by back-substitution.",
            AxiomSolveInput,
            axiom_solve,
            ["symbolic", "solve", "equations", "roots", "system", "algebra", "sympy"],
        ),
        (
            "axiom_calculus",
            "Perform symbolic differentiation, definite/indefinite integration (with mpmath numeric quadrature verification), limits, Taylor/Laurent series, and symbolic summations.",
            AxiomCalculusInput,
            axiom_calculus,
            ["symbolic", "calculus", "diff", "derivative", "integrate", "integral", "limit", "series", "sum", "sympy"],
        ),
        (
            "axiom_dsolve",
            "Solve ordinary differential equations (ODEs) symbolically with optional initial/boundary conditions and verify the solution via substitution.",
            AxiomDsolveInput,
            axiom_dsolve,
            ["symbolic", "ode", "dsolve", "differential_equation", "calculus", "sympy"],
        ),
        (
            "axiom_linalg",
            "Perform exact/symbolic linear algebra: eigenvalues/eigenvectors, determinant, inverse, RREF, SVD, nullspace, characteristic polynomial, and linear system solving.",
            AxiomLinalgInput,
            axiom_linalg,
            ["symbolic", "linalg", "matrix", "eigenvalues", "determinant", "inverse", "rref", "svd", "nullspace", "sympy"],
        ),
        (
            "axiom_verify_identity",
            "Verify mathematical identity equivalence (lhs == rhs) both symbolically via simplify(lhs - rhs) == 0 and numerically at random test points via mpmath.",
            AxiomVerifyIdentityInput,
            axiom_verify_identity,
            ["symbolic", "verify", "identity", "equivalence", "counterexample", "proof", "sympy"],
        ),
        (
            "axiom_latex",
            "Parse a mathematical expression or equation and return its canonical SymPy representation, LaTeX string, and free symbols.",
            AxiomLatexInput,
            axiom_latex,
            ["symbolic", "latex", "parse", "format", "sympy"],
        ),
    ]

    for name, desc, schema, fn, tags in specs:
        registry.register(
            ToolUniverseEntry(
                name=name,
                description=desc,
                domain="axiom",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=schema,
                canonical_id_types=["computation_id"],
                timeout_seconds=30.0,
                tags=tags,
                is_async=False,
            ),
            executor=_wrap_executor(name, fn),
        )


__all__ = ["register_tools"]
