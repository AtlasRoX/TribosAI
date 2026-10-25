"""Extension module registering Axiom symbolic mathematics tools into the Tribos ToolRegistry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tribos.axiom.analysis import (
    axiom_inequality,
    axiom_nintegrate,
    axiom_optimize,
    axiom_tangent,
    axiom_transform,
    axiom_vector_calculus,
)
from tribos.axiom.discrete import (
    axiom_number_theory,
    axiom_probability,
    axiom_recurrence,
    calcula_statistics,
)
from tribos.axiom.definitions import axiom_structured
from tribos.axiom.engine import (
    axiom_calculus,
    axiom_dsolve,
    axiom_latex,
    axiom_linalg,
    axiom_nsolve,
    axiom_simplify,
    axiom_solve,
    axiom_verify_identity,
)
from tribos.axiom.sagemath import run_sagemath_code
from tribos.axiom.schemas import (
    AxiomCalculusInput,
    AxiomDsolveInput,
    AxiomInequalityInput,
    AxiomLatexInput,
    AxiomLinalgInput,
    AxiomNintegrateInput,
    AxiomNsolveInput,
    AxiomNumberTheoryInput,
    AxiomOptimizeInput,
    AxiomProbabilityInput,
    AxiomRecurrenceInput,
    AxiomSageMathInput,
    AxiomSimplifyInput,
    AxiomSolveInput,
    AxiomSolveProblemInput,
    AxiomStructuredInput,
    AxiomTangentInput,
    AxiomTransformInput,
    AxiomVectorCalculusInput,
    AxiomVerifyIdentityInput,
    CalculaStatisticsInput,
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


def _wrap_async_executor(tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    async def _exec(**kwargs: Any) -> Any:
        from tribos.tools.registry import ErrorType, ToolResult

        try:
            data = await fn(**kwargs)
        except ValueError as exc:
            return ToolResult(success=False, tool_name=tool_name, error=str(exc), error_type=ErrorType.VALIDATION_ERROR)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, tool_name=tool_name, error=f"{type(exc).__name__}: {exc}", error_type=ErrorType.INTERNAL_ERROR)
        status = str(data.get("status") or "")
        return ToolResult(
            success=status != "failed",
            tool_name=tool_name,
            data=data,
            error=None if status != "failed" else "; ".join((data.get("uncertainty") or ["no strategy produced an answer"])[:3]),
            error_type=None if status != "failed" else ErrorType.SIMULATION_FAILED,
            metadata={"engine": "sympy", "verified": status == "verified", "verification_status": status},
        )

    _exec.__name__ = f"execute_{tool_name}"
    return _exec


def _wrap_sagemath_executor(tool_name: str) -> Callable[..., Any]:
    def _exec(code: str, timeout_s: int = 60, **kwargs: Any) -> Any:
        from tribos.tools.registry import ErrorType, ToolResult

        try:
            res = run_sagemath_code(code, timeout_s=timeout_s)
            cid = str(res.get("canonical_id") or "")
            canonical_ids = {"computation_id": cid} if cid else {}
            if res.get("status") == "ok":
                figures = list(res.get("figures") or [])
                return ToolResult(
                    success=True,
                    tool_name=tool_name,
                    data=res,
                    canonical_ids=canonical_ids,
                    metadata={"engine": "sagemath", "mode": res.get("mode", "local"), "figures": figures},
                )
            error_msg = str(res.get("error") or "SageMath execution failed")
            failure = str(res.get("failure_class") or "infrastructure")
            # A fault in the submitted code is a validation error of the action; anything else is the environment.
            error_type = {
                "timeout": ErrorType.TIMEOUT,
                "model_code_error": ErrorType.VALIDATION_ERROR,
            }.get(failure, ErrorType.INTERNAL_ERROR)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                data=res,
                error=error_msg,
                error_type=error_type,
                metadata={"engine": "sagemath", "failure_class": failure},
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
    """Register all Axiom symbolic mathematics and SageMath tools in the ToolRegistry."""
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
            "Solve algebraic or transcendental equations and systems of equations symbolically, verifying solutions by back-substitution and reporting whether the list is the complete solution set (solveset cross-check for periodic families).",
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
            "Verify mathematical identity equivalence (lhs == rhs) symbolically and at random positive, negative and complex test points (pass assumptions such as {'x': 'positive'} to restrict the domain); returns the evidence level and any counterexample.",
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
        (
            "axiom_nsolve",
            "Numeric fallback for transcendental equations without a closed form (x = cos(x), x*exp(x) = 3): scans an interval for every real root, refines each with mpmath.findroot and keeps only residual-checked roots; completeness is reported as unknown.",
            AxiomNsolveInput,
            axiom_nsolve,
            ["numeric", "fallback", "interval", "scan", "findroot", "refines", "residual", "nsolve", "mpmath"],
        ),
        (
            "axiom_optimize",
            "Global maximum and minimum of a function on an interval (critical points, endpoints, limits at open ends and poles, unboundedness), each extremum checked by dense sampling of the function.",
            AxiomOptimizeInput,
            axiom_optimize,
            ["optimize", "maximum", "minimum", "extrema", "critical", "global", "interval"],
        ),
        (
            "axiom_inequality",
            "Inequality solver: the real solution set of a single-variable inequality (polynomial, rational, absolute value) as intervals, checked by sampling points inside and outside the set.",
            AxiomInequalityInput,
            axiom_inequality,
            ["inequality", "intervals", "less", "greater", "solution_set", "sign"],
        ),
        (
            "axiom_tangent",
            "Tangent line, normal line and slope of y = f(x) at a point x = a, with the slope checked against a numerical derivative.",
            AxiomTangentInput,
            axiom_tangent,
            ["tangent", "slope", "normal", "line", "point", "derivative"],
        ),
        (
            "axiom_vector_calculus",
            "Vector calculus in Cartesian coordinates: gradient, divergence, curl, Laplacian, Hessian and Jacobian of scalar or vector fields, every partial derivative checked by finite differences.",
            AxiomVectorCalculusInput,
            axiom_vector_calculus,
            ["vector", "gradient", "divergence", "curl", "laplacian", "hessian", "jacobian", "field"],
        ),
        (
            "axiom_transform",
            "Laplace transform, inverse Laplace transform and Fourier transform in closed form, checked numerically against the defining transform integral (signals, control, circuits).",
            AxiomTransformInput,
            axiom_transform,
            ["laplace", "inverse_laplace", "fourier", "transform", "frequency", "signals", "control"],
        ),
        (
            "axiom_nintegrate",
            "Numerical definite integration (quadrature) for integrals with no closed form, e.g. exp(-x^4) from 0 to oo, by two independent rules (tanh-sinh, Gauss-Legendre) with an error estimate.",
            AxiomNintegrateInput,
            axiom_nintegrate,
            ["quadrature", "numerical_integration", "definite", "nintegrate", "mpmath"],
        ),
        (
            "axiom_number_theory",
            "Number theory on exact integers: prime factorization, primality, gcd, lcm, divisors, Euler totient, modular power and inverse, Chinese remainder theorem, next prime, linear Diophantine equations.",
            AxiomNumberTheoryInput,
            axiom_number_theory,
            ["number_theory", "prime", "factorization", "gcd", "lcm", "modular", "modulo", "totient", "crt", "diophantine"],
        ),
        (
            "axiom_recurrence",
            "Recurrence relation solver: closed form of a linear recurrence such as a(n) = a(n-1) + a(n-2) with initial terms (Fibonacci-type sequences), checked against direct iteration.",
            AxiomRecurrenceInput,
            axiom_recurrence,
            ["recurrence", "rsolve", "sequence", "fibonacci", "difference_equation", "closed_form"],
        ),
        (
            "axiom_structured",
            "Questions that define their own functions (branches such as n/2 for even n, declared domains), evaluate an expression in independent cases with case-local values, iterate a function to a cycle, or state a universal claim; a defined name is applied, never multiplied. Interpretation, domain, computation and coverage are checked separately.",
            AxiomStructuredInput,
            axiom_structured,
            ["function", "definition", "piecewise", "cases", "counterexample", "claim", "orbit", "cycle", "domain"],
        ),
        (
            "axiom_probability",
            "Probability distributions: exact probabilities, CDF, PDF/PMF, mean, variance, standard deviation and quantiles of normal, binomial, Poisson, exponential, uniform, geometric and Bernoulli variables, cross-checked with SciPy.",
            AxiomProbabilityInput,
            axiom_probability,
            ["probability", "distribution", "normal", "binomial", "poisson", "exponential", "expected_value", "variance", "quantile"],
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

    registry.register(
        ToolUniverseEntry(
            name="calcula_statistics",
            description=(
                "Statistics on inline numbers: descriptive summary (mean, median, standard deviation), one-sample, Welch "
                "and paired t-tests, linear regression, Pearson correlation and t confidence intervals, recomputed from "
                "textbook formulas and checked against SciPy."
            ),
            domain="analysis",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=CalculaStatisticsInput,
            canonical_id_types=["computation_id"],
            timeout_seconds=30.0,
            tags=["statistics", "ttest", "regression", "correlation", "confidence_interval", "mean", "standard_deviation"],
            is_async=False,
        ),
        executor=_wrap_executor("calcula_statistics", calcula_statistics),
    )

    # The verified mathematics agent as one tool: parse -> rule-routed tool loop -> independent verifier
    from tribos.axiom.agent import solve_problem_tool

    registry.register(
        ToolUniverseEntry(
            name="axiom_solve_problem",
            description=(
                "Solve a complete math problem end to end (equations, calculus, limits, series, sums, ODEs, linear "
                "algebra, identities) with a bounded tool loop and an independent verifier that re-checks the answer "
                "against the original problem. Returns the answer, status verified | partially_verified | unverified | "
                "failed, the checks that passed and what remains uncertain."
            ),
            domain="axiom",
            adapter_type=AdapterType.LOCAL_COMPUTE,
            input_schema=AxiomSolveProblemInput,
            canonical_id_types=["computation_id"],
            timeout_seconds=120.0,
            tags=["math", "agent", "complete", "question", "end_to_end", "bounded", "loop", "independent", "verifier", "verified"],
            is_async=True,
        ),
        executor=_wrap_async_executor("axiom_solve_problem", solve_problem_tool),
    )

    # Register SageMath tools
    sage_desc = (
        "Execute high-performance Python / SageMath code in a dedicated SageMath environment (supporting algebraic "
        "geometry, number theory, exact calculus, symbolic physics, and combinatorics). Returns stdout, stderr, and canonical id."
    )
    sage_tags = ["sagemath", "sage", "symbolic", "math", "algebra", "calculus", "physics", "computation"]
    for s_name in ("axiom_sagemath", "calcula_run_sagemath"):
        registry.register(
            ToolUniverseEntry(
                name=s_name,
                description=sage_desc,
                domain="axiom" if s_name.startswith("axiom") else "analysis",
                adapter_type=AdapterType.LOCAL_COMPUTE,
                input_schema=AxiomSageMathInput,
                canonical_id_types=["computation_id"],
                timeout_seconds=120.0,
                tags=sage_tags,
                is_async=False,
            ),
            executor=_wrap_sagemath_executor(s_name),
        )


__all__ = ["register_tools"]
