"""Reproducible crude Monte Carlo quadrature with an explicit random generator and sample count."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import sympy as sp

from tribos.axiom.engine import safe_parse_expr


def monte_carlo_integrate(
    expression: str,
    lower: float,
    upper: float,
    num_samples: int,
    seed: int,
    variable: str = "x",
    reference: float | None = None,
    generator: str = "PCG64",
) -> dict[str, Any]:
    if not variable.isidentifier() or variable.startswith("_"):
        raise ValueError("A single named integration variable is required.")
    if generator.upper() != "PCG64":
        raise ValueError("This sampler supports PCG64 only; another generator was not substituted.")
    if not 2 <= num_samples <= 2_000_000 or isinstance(num_samples, bool):
        raise ValueError("num_samples must be between 2 and 2,000,000.")
    if not 0 <= seed < 2**64 or isinstance(seed, bool):
        raise ValueError("seed must be an integer in [0, 2^64).")
    if not all(math.isfinite(v) for v in (lower, upper)) or upper <= lower:
        raise ValueError("Finite increasing integration bounds are required.")
    if reference is not None and not math.isfinite(reference):
        raise ValueError("The supplied reference must be finite.")
    x = sp.Symbol(variable)
    expr = safe_parse_expr(expression, local_dict={variable: x})
    if expr.free_symbols - {x} or expr.has(sp.Integral, sp.Derivative):
        raise ValueError("The integrand must be a scalar function of the stated variable only.")
    fn = sp.lambdify(x, expr, modules="numpy")
    rng = np.random.Generator(np.random.PCG64(seed))
    samples = rng.uniform(lower, upper, size=num_samples)
    values = np.asarray(fn(samples))
    if np.iscomplexobj(values):
        raise ValueError("The Monte Carlo integrand must be real on the sampled interval.")
    values = np.broadcast_to(values, samples.shape).astype(np.float64) * (upper - lower)
    if not np.isfinite(values).all():
        raise ValueError(
            "The integrand produced non-finite sample values; no estimate is reported."
        )
    estimate = float(values.mean())
    sample_std = float(values.std(ddof=1))
    se = sample_std / math.sqrt(num_samples)
    z_score = (
        (abs(estimate - reference) / se if se > 0 else (0.0 if estimate == reference else None))
        if reference is not None
        else None
    )
    return {
        "status": "completed",
        "method": "crude Monte Carlo",
        "expression": str(expr),
        "variable": variable,
        "lower": lower,
        "upper": upper,
        "num_samples": num_samples,
        "seed": seed,
        "generator": "numpy.random.Generator(PCG64)",
        "numpy_version": np.__version__,
        "dtype": "float64",
        "estimate": estimate,
        "sample_std": sample_std,
        "standard_error": se,
        "ddof": 1,
        "reference": reference,
        "standard_errors_from_reference": z_score,
        "sample_sha256": hashlib.sha256(samples.tobytes()).hexdigest(),
        "checks": {"finite_samples": True, "sample_count": len(samples) == num_samples},
        "accuracy_note": "The standard error estimates sampling uncertainty; it does not certify an exact integral.",
    }
