"""Pydantic input/output schemas for the Axiom symbolic mathematics package."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AxiomSimplifyInput(BaseModel):
    expression: str | list[str] | list[Any] | tuple[Any, ...] = Field(
        ...,
        description="Mathematical expression string or collection of expressions to simplify",
    )
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
        description="Solution domain: 'complex', 'real', 'integer', or 'positive_integer'",
    )

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, v: str) -> str:
        s = str(v or "complex").strip().lower()
        if s in ("real", "reals", "r"):
            return "real"
        if s in ("integer", "integers", "z"):
            return "integer"
        if s in ("positive_integer", "positive_integers", "natural", "n", "positive"):
            return "positive_integer"
        if s in ("complex", "c"):
            return "complex"
        return s

    @field_validator("variables")
    @classmethod
    def sanitize_variables(cls, v: str | list[str] | None) -> str | list[str] | None:
        if v is None:
            return None

        def _clean(item: str) -> str:
            raw = str(item).strip().strip("$")
            raw = re.split(r"\\in|>|<|>=|<=|=", raw)[0].strip()
            m = re.search(r"[A-Za-z_]\w*", raw)
            if not m:
                raise ValueError(f"Invalid variable identifier: {item!r}")
            return m.group(0)

        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return ", ".join(_clean(p) for p in parts)
        return [_clean(p) for p in v if str(p).strip()]


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
    assumptions: dict[str, str] | None = Field(
        default=None,
        description=(
            "Symbol domains, e.g. {'x': 'positive'}. Without them symbols are sampled over positive, negative and "
            "complex values, so identities valid only for positive reals (log(x*y) = log(x) + log(y)) are refuted"
        ),
    )


class AxiomLatexInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Mathematical expression or equation to convert to canonical SymPy and LaTeX")


class AxiomNsolveInput(BaseModel):
    equation: str = Field(..., min_length=1, max_length=4000, description="Univariate equation 'lhs = rhs' or expression (= 0), e.g. 'x = cos(x)'")
    variable: str | None = Field(default=None, max_length=64, description="Unknown; inferred when the equation has one free symbol")
    lower: float = Field(default=-10.0, description="Lower end of the real search interval")
    upper: float = Field(default=10.0, description="Upper end of the real search interval")
    samples: int = Field(default=400, ge=20, le=5000, description="Grid points of the sign-change scan")


class AxiomOptimizeInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Objective f(x), e.g. 'x^2 - 4x + 1'")
    variable: str = Field(default="x", min_length=1, max_length=64, description="Variable")
    lower: str | None = Field(default=None, description="Lower end of the interval (omit for -oo)")
    upper: str | None = Field(default=None, description="Upper end of the interval (omit for oo)")
    lower_open: bool = Field(default=False, description="Exclude the lower end (x > lower)")
    upper_open: bool = Field(default=False, description="Exclude the upper end (x < upper)")


class AxiomInequalityInput(BaseModel):
    inequality: str = Field(..., min_length=3, max_length=4000, description="One univariate inequality, e.g. 'x^2 - 4 > 0' or '(x-1)/(x+2) <= 0'")
    variable: str | None = Field(default=None, max_length=64, description="Variable; inferred when there is one")


class AxiomTangentInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Function f(x)")
    point: str = Field(..., min_length=1, max_length=200, description="x-coordinate a of the point of tangency")
    variable: str = Field(default="x", min_length=1, max_length=64, description="Variable")


class AxiomVectorCalculusInput(BaseModel):
    operation: Literal["gradient", "divergence", "curl", "laplacian", "hessian", "jacobian"] = Field(..., description="Operation")
    expression: str | None = Field(default=None, max_length=4000, description="Scalar field (gradient, laplacian, hessian)")
    components: list[str] | None = Field(default=None, max_length=6, description="Vector field components (divergence, curl, jacobian)")
    variables: list[str] | None = Field(default=None, max_length=6, description="Coordinates, default ['x', 'y', 'z']")


class AxiomTransformInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="f(t) for laplace, F(s) for inverse_laplace, f(x) for fourier")
    transform: Literal["laplace", "inverse_laplace", "fourier"] = Field(..., description="Transform")
    variable: str | None = Field(default=None, max_length=64, description="Input variable (t / s / x by default)")
    transform_variable: str | None = Field(default=None, max_length=64, description="Output variable (s / t / k by default)")


class AxiomNintegrateInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=4000, description="Integrand")
    lower: str = Field(..., description="Lower bound (may be -oo)")
    upper: str = Field(..., description="Upper bound (may be oo)")
    variable: str = Field(default="x", min_length=1, max_length=64, description="Integration variable")


class AxiomNumberTheoryInput(BaseModel):
    operation: Literal["factorize", "isprime", "gcd", "lcm", "divisors", "totient", "mod_pow", "mod_inverse", "crt", "next_prime", "diophantine"] = Field(..., description="Operation")
    numbers: list[int | str] = Field(..., min_length=1, max_length=20, description="Integers: [n], [a, b, ...], [base, exponent], residues for crt, [a, b, c] for a*x + b*y = c")
    modulus: int | str | list[int | str] | None = Field(default=None, description="Modulus (mod_pow, mod_inverse) or list of moduli (crt)")


class AxiomRecurrenceInput(BaseModel):
    recurrence: str = Field(..., min_length=3, max_length=2000, description="e.g. 'a(n) = a(n-1) + a(n-2)'")
    initial: dict[str, int | float | str] = Field(..., description="Initial values, e.g. {'a(0)': 0, 'a(1)': 1}")
    function: str = Field(default="a", min_length=1, max_length=32, description="Sequence name")
    variable: str = Field(default="n", min_length=1, max_length=32, description="Index variable")


class AxiomProbabilityInput(BaseModel):
    distribution: Literal["normal", "binomial", "poisson", "exponential", "uniform", "geometric", "bernoulli"] = Field(..., description="Distribution")
    parameters: list[int | float | str] = Field(..., min_length=1, max_length=3, description="normal [mu, sigma], binomial [n, p], poisson [lambda], exponential [rate], uniform [a, b], geometric [p], bernoulli [p]")
    query: Literal["probability", "mean", "variance", "std", "pdf", "cdf", "quantile"] = Field(..., description="Quantity")
    lower: int | float | str | None = Field(default=None, description="probability: lower bound of X")
    upper: int | float | str | None = Field(default=None, description="probability: upper bound of X")
    lower_inclusive: bool = Field(default=True, description="X >= lower (True) or X > lower")
    upper_inclusive: bool = Field(default=True, description="X <= upper (True) or X < upper")
    value: int | float | str | None = Field(default=None, description="pdf / cdf point, or the probability for quantile")


class CalculaStatisticsInput(BaseModel):
    operation: Literal["describe", "ttest_1samp", "ttest_ind", "ttest_rel", "linregress", "pearson", "confidence_interval"] = Field(..., description="Operation")
    data: list[float] = Field(..., min_length=2, max_length=100000, description="Sample (x values for regression/correlation)")
    data2: list[float] | None = Field(default=None, max_length=100000, description="Second sample, or y values")
    mu0: float = Field(default=0.0, description="Hypothesised mean for ttest_1samp")
    confidence: float = Field(default=0.95, gt=0, lt=1, description="Confidence level for confidence_interval")


class AxiomSolveProblemInput(BaseModel):
    problem: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="A complete mathematical question in words, LaTeX or plain math, e.g. 'Find all real x with x^3 = 2x + 1'",
    )


_Domain = str


class StructuredBranch(BaseModel):
    expression: str = Field(..., min_length=1, max_length=500, description="Formula in the parameter, e.g. 'n/2'")
    condition: str = Field(default="", max_length=120, description="'', 'otherwise', 'even', 'odd' or a relation such as 't < 0'")


class StructuredDefinition(BaseModel):
    name: str = Field(..., pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$", description="Function name, e.g. 'T'")
    parameter: str = Field(..., pattern=r"^[A-Za-z]$", description="Parameter, e.g. 'n'")
    domain: _Domain = Field(default="unspecified", description="Declared domain of the parameter")
    branches: list[StructuredBranch] = Field(..., min_length=1, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def _repair_parameter(cls, data: Any) -> Any:
        """A planner-written definition without "parameter" (audit I25): take it from a known alias, or from the one
        variable its formulas use; never guess between several. The domain is never filled in or widened here."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        domain = data.get("domain")
        if isinstance(domain, str):
            from .definitions import domain_from_words, is_valid_domain  # local: definitions imports sympy

            if not is_valid_domain(domain):
                mapped = domain_from_words(domain.replace("_", " "))
                if mapped and is_valid_domain(mapped):
                    data["domain"] = mapped
                else:
                    raise ValueError(f"invalid domain {domain!r}")
        # A single formula given without branches, or a branch whose formula is under another key ("formula",
        # "expr", "rule", "value"), is the same definition written differently; its condition is kept as given.
        if not data.get("branches"):
            single = next((data.pop(k) for k in ("expression", "formula", "expr", "rule") if isinstance(data.get(k), str)), None)
            if single:
                data["branches"] = [{"expression": single, "condition": ""}]
        if isinstance(data.get("branches"), list):
            data["branches"] = [
                {**b, "expression": next((b[k] for k in ("formula", "expr", "rule", "value") if isinstance(b.get(k), str)), "")}
                if isinstance(b, dict) and not b.get("expression") else b
                for b in data["branches"]
            ]
        if data.get("parameter"):
            return data
        for alias in ("variable", "var", "param", "argument", "arg"):
            if isinstance(data.get(alias), str) and data[alias].strip():
                data["parameter"] = data.pop(alias).strip()
                return data
        letters: set[str] = set()
        for b in data.get("branches") or []:
            text = str((b or {}).get("expression") or "") if isinstance(b, dict) else ""
            letters |= {m for m in re.findall(r"(?<![A-Za-z_])([A-Za-z])(?![A-Za-z_(])", text)}
        letters.discard(str(data.get("name") or ""))
        if len(letters) == 1:
            data["parameter"] = letters.pop()
            return data
        raise ValueError(f"definition {data.get('name')!r} gives no parameter and its formulas use "
                         f"{', '.join(sorted(letters)) or 'no variable'}; state the parameter")


class StructuredTask(BaseModel):
    id: str = Field(..., min_length=1, max_length=80, description="Label from the question: 'T(4)', 'Case A', 'claim'")
    op: Literal["evaluate", "orbit", "claim", "reaches", "zeros"]

    @model_validator(mode="before")
    @classmethod
    def _repair_id(cls, data: Any) -> Any:
        """A planner-written task without "id" (seen live): its own expression or statement labels it ("q(3)"),
        which is what the question calls it; nothing else about the task changes."""
        if isinstance(data, dict) and not data.get("id"):
            label = next((str(data[k]).strip() for k in ("expression", "statement", "function") if data.get(k)), "")
            if label:
                data = {**data, "id": label[:80] if data.get("op") != "zeros" else f"zeros of {label}"[:80]}
        return data
    expression: str | None = Field(default=None, max_length=1000, description="evaluate / predicate claims: the expression")
    bindings: dict[str, int | float | str] | None = Field(default=None, description="evaluate: case-local values, e.g. {'n': 40}")
    factor: bool = Field(default=False, description="evaluate: also give the prime factorization")
    function: str | None = Field(default=None, max_length=16, description="orbit: the function to iterate")
    start: int | str | None = Field(default=None, description="orbit: start value")
    target: int | str | None = Field(default=None, description="reaches: the value every orbit is claimed to reach")
    mode: Literal["cycle", "steps", "until_repeat"] | None = None
    steps: int | None = Field(default=None, ge=1, le=1000)
    lhs: str | None = Field(default=None, max_length=1000)
    relation: Literal["=", "<", "<=", ">", ">=", "!="] | None = None
    rhs: str | None = Field(default=None, max_length=1000)
    predicate: Literal["prime", "composite", "even", "odd", "positive", "negative", "nonnegative", "nonzero", "integer",
                       "perfect_square", "divisible"] | None = None
    divisor: str | None = Field(default=None, max_length=100)
    variable: str | None = Field(default=None, pattern=r"^[A-Za-z]$")
    domain: _Domain | None = None

    @field_validator("domain", mode="before")
    @classmethod
    def _validate_task_domain(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            from .definitions import domain_from_words, is_valid_domain

            if is_valid_domain(v):
                return v
            mapped = domain_from_words(v.replace("_", " "))
            if mapped and is_valid_domain(mapped):
                return mapped
            raise ValueError(f"invalid domain {v!r}")
        return v
    conditions: list[str] = Field(default_factory=list, max_length=4)
    statement: str | None = Field(default=None, max_length=1000)
    line: str | None = Field(default=None, max_length=40, description="zeros: c of a line Re(v) = c the zeros are compared with")


class AxiomStructuredInput(BaseModel):
    """Function definitions with branches and domains, and tasks on them (values, orbits, case-local evaluation,
    universal claims)."""

    definitions: list[StructuredDefinition] = Field(default_factory=list, max_length=8)
    tasks: list[StructuredTask] = Field(..., min_length=1, max_length=24)


class AxiomSageMathInput(BaseModel):
    code: str = Field(..., min_length=1, max_length=60000, description="SageMath / Python mathematical computation or derivation code")
    timeout_s: int = Field(default=60, ge=5, le=180, description="Execution timeout cutoff in seconds")


__all__ = [
    "AxiomInequalityInput",
    "AxiomNintegrateInput",
    "AxiomNumberTheoryInput",
    "AxiomOptimizeInput",
    "AxiomProbabilityInput",
    "AxiomRecurrenceInput",
    "AxiomTangentInput",
    "AxiomTransformInput",
    "AxiomVectorCalculusInput",
    "CalculaStatisticsInput",
    "AxiomCalculusInput",
    "AxiomDsolveInput",
    "AxiomLatexInput",
    "AxiomLinalgInput",
    "AxiomNsolveInput",
    "AxiomSageMathInput",
    "AxiomSimplifyInput",
    "AxiomSolveInput",
    "AxiomSolveProblemInput",
    "AxiomStructuredInput",
    "AxiomVerifyIdentityInput",
    "StructuredDefinition",
    "StructuredTask",
]


# Accuracy tools (tribos.axiom.accuracy) ------------------------------------------------------------------------

class AxiomIntervalVerifyInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=2000, description="f, e.g. 'x**2 - 2*x + 2' or 'sin(x) + x*y'")
    bounds: dict[str, list[float]] = Field(..., description="Range of every variable, e.g. {'x': [0, 1], 'y': [-2, 2]}")
    claim: Literal["enclose", "positive", "nonnegative", "negative", "nonpositive"] = Field(
        default="enclose", description="enclose: rigorous range of f; or prove f > 0, f >= 0, f < 0, f <= 0 on the box")


class AxiomPrecisionCheckInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=2000, description="f, e.g. '(1 - cos(x))/x**2'")
    values: dict[str, str | int | float] = Field(default_factory=dict, description="Value of every variable, exact as text, e.g. {'x': '1e-8'}")
    digits: list[int] | None = Field(default=None, max_length=6, description="Working precisions in significant digits (default 15, 30, 60, 120)")


class AxiomCounterexampleInput(BaseModel):
    claim: str = Field(..., min_length=3, max_length=2000, description="'lhs <op> rhs' (op: <, <=, >, >=, ==, !=) or isprime(expr), is_integer(expr), is_square(expr)")
    domain: dict[str, dict[str, Any]] = Field(..., description="Per variable: {'type': 'integer'|'real', 'min': .., 'max': ..}")
    samples: int = Field(default=4000, ge=10, le=20000, description="Points to test (a finite integer domain this small is searched exhaustively)")
    seed: int = Field(default=0, description="Random seed (reproducible)")


class CalculaCrossValidateInput(BaseModel):
    code_a: str = Field(..., min_length=1, max_length=40000, description="First implementation; must set `result` (a dict of named values)")
    code_b: str = Field(..., min_length=1, max_length=40000, description="Second, independently written implementation; sets the same `result` keys")
    rtol: float = Field(default=1e-9, ge=0, le=1, description="Relative tolerance for floats (integers must match exactly)")
    atol: float = Field(default=1e-12, ge=0, description="Absolute tolerance for floats")
    keys: list[str] | None = Field(default=None, max_length=200, description="Only compare these quantities")


class CalculaDistributionTestsInput(BaseModel):
    data: list[float] = Field(..., min_length=8, max_length=200000, description="The sample")
    alpha: float = Field(default=0.05, gt=0, lt=0.5, description="Significance level")
    bootstrap: int = Field(default=2000, ge=200, le=20000, description="Bootstrap resamples for confidence intervals")
    seed: int = Field(default=0, description="Random seed (reproducible)")
