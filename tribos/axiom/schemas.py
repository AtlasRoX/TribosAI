"""Pydantic input/output schemas for the Axiom symbolic mathematics package."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AxiomSimplifyInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Mathematical expression to simplify")
    assumptions: dict[str, str] | None = Field(
        default=None,
        description="Optional symbol assumptions mapping variable name to assumption flags (e.g. {'x': 'positive, real'})",
    )


class AxiomSolveInput(BaseModel):
    equations: str | list[str] = Field(
        ...,
        description="Single equation/expression string (e.g. 'x^2 - 4 = 0') or list of equation strings for a system",
    )
    variables: str | list[str] | None = Field(
        default=None,
        description="Variable(s) to solve for; inferred from free symbols when omitted",
    )
    domain: str = Field(
        default="complex",
        description="Solution domain: 'complex' (default) or 'real'",
    )


class AxiomCalculusInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Mathematical expression to operate on")
    operation: Literal["diff", "integrate", "limit", "series", "sum"] = Field(
        ...,
        description="Calculus operation: diff, integrate, limit, series, or sum",
    )
    variable: str = Field(default="x", min_length=1, max_length=64, description="Variable of differentiation/integration/limit/summation")
    order: int = Field(default=1, ge=1, le=20, description="Derivative order or series expansion order")
    lower: str | None = Field(default=None, description="Lower bound for definite integration or summation")
    upper: str | None = Field(default=None, description="Upper bound for definite integration or summation")
    point: str | None = Field(default=None, description="Evaluation point for limit or series expansion (e.g. '0', 'oo', 'pi')")


class AxiomDsolveInput(BaseModel):
    equation: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Ordinary differential equation (e.g. \"y''(x) + y(x) = 0\" or \"Derivative(y(x), x) + 2*y(x) = exp(-x)\")",
    )
    func: str = Field(default="y(x)", min_length=1, max_length=64, description="Unknown function with independent variable, e.g. 'y(x)'")
    ics: dict[str, float | int | str] | None = Field(
        default=None,
        description="Optional initial/boundary conditions, e.g. {'y(0)': 1, \"y'(0)\": 0}",
    )


class AxiomLinalgInput(BaseModel):
    matrix: list[list[float | int | str]] = Field(
        ...,
        min_length=1,
        description="2D matrix as a list of rows containing numbers or symbolic expressions",
    )
    operation: Literal["eigen", "det", "inv", "rref", "svd", "nullspace", "charpoly", "solve"] = Field(
        ...,
        description="Linear algebra operation to execute",
    )
    rhs: list[float | int | str] | None = Field(
        default=None,
        description="Right-hand side vector for operation='solve' (M * x = rhs)",
    )


class AxiomVerifyIdentityInput(BaseModel):
    lhs: str = Field(..., min_length=1, max_length=4000, description="Left-hand side expression")
    rhs: str = Field(..., min_length=1, max_length=4000, description="Right-hand side expression")
    variables: list[str] | None = Field(default=None, description="Variables to sample; inferred from free symbols when omitted")
    num_points: int = Field(default=8, ge=1, le=64, description="Number of random points for numerical cross-checking")


class AxiomLatexInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Mathematical expression or equation to convert to canonical SymPy and LaTeX")


__all__ = [
    "AxiomCalculusInput",
    "AxiomDsolveInput",
    "AxiomLatexInput",
    "AxiomLinalgInput",
    "AxiomSimplifyInput",
    "AxiomSolveInput",
    "AxiomVerifyIdentityInput",
]
