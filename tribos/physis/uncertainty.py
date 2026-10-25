"""Uncertainty propagation for physical and engineering models.

Implements first-order GUM (linear Taylor expansion with partial derivatives) and
vectorized Monte Carlo propagation, unit handling with Pint, and NIST CODATA constant autofill.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp

from tribos.axiom.engine import safe_parse_expr
from tribos.physis.constants import _SYMBOL_TO_CODATA_KEY, search_constants
from tribos.physis.units import get_unit_registry

# Canonical SI-derived unit names, preferred when a compound unit has a named equivalent.
_NAMED_UNIT_PREFERENCE: tuple[str, ...] = (
    "meter", "second", "kilogram", "ampere", "kelvin", "mole", "candela",
    "newton", "pascal", "joule", "watt", "coulomb", "volt", "farad", "ohm", "henry",
    "hertz", "tesla", "weber", "siemens", "becquerel", "gray", "sievert", "lumen", "lux",
    "liter", "gram",
)


def _canonical_unit_name(unit: Any, ureg: Any) -> str:
    """The name of a unit when a named SI-derived equivalent exists ("joule"), else its expansion.

    Pint renders a compound unit as its factors ("kilogram * meter ** 2 / second ** 2"); a reader wants the
    name of the quantity. The name is only reported when it is unambiguous, so a unit without a single
    canonical name keeps its expansion.
    """
    try:
        dimensionality = ureg.Quantity(1.0, unit).to_base_units().dimensionality
    except Exception:  # noqa: BLE001
        return str(unit)

    matches: list[str] = []
    for name, definition in ureg._units.items():
        try:
            if ureg.Unit(name).dimensionality != dimensionality:
                continue
        except Exception:  # noqa: BLE001
            continue
        matches.append(name)

    if not matches:
        return str(unit)
    preferred = [m for m in _NAMED_UNIT_PREFERENCE if m in matches]
    if preferred:
        return preferred[0]
    # A single short ASCII candidate is safe to report; otherwise keep the expansion.
    short = [m for m in matches if m.isascii() and len(m) <= 12]
    return short[0] if len(short) == 1 else str(unit)


def _lookup_codata(symbol: str) -> dict[str, Any] | None:
    """Return the CODATA entry for a symbol (name, symbol or alias), or None when it is unknown."""
    try:
        found = search_constants(symbol, limit=1)
    except Exception:  # noqa: BLE001
        return None
    entries = found.get("constants") or []
    return entries[0] if entries else None


def format_uncertainty_result(
    value: float,
    std_uncertainty: float,
    unit: str = "",
    k: float = 2.0,
) -> str:
    """Format a result as value ± U with k=2, uncertainty to 2 significant figures and value rounded to match."""
    U = k * std_uncertainty
    if not math.isfinite(value) or not math.isfinite(U) or U <= 0.0:
        val_str = f"{value:.6g}"
        unc_str = f"{U:.2g}" if math.isfinite(U) else str(U)
        return f"{val_str} ± {unc_str} {unit}".strip()

    # Determine decimal places for 2 significant figures of U
    order = math.floor(math.log10(U))
    decimals = max(0, 1 - order)

    if -3 <= order <= 4:
        # Standard decimal format
        U_rounded = round(U, decimals)
        val_rounded = round(value, decimals)
        if decimals == 0:
            val_str = f"{int(val_rounded)}"
            unc_str = f"{int(U_rounded)}"
        else:
            val_str = f"{val_rounded:.{decimals}f}"
            unc_str = f"{U_rounded:.{decimals}f}"
        if unit:
            return f"({val_str} ± {unc_str}) {unit}"
        return f"{val_str} ± {unc_str}"
    else:
        # Scientific notation
        scale = 10.0**order
        U_scaled = round(U / scale, 1)
        val_scaled = round(value / scale, 1)
        base = f"({val_scaled:.1f} ± {U_scaled:.1f})e{order:+03d}"
        if unit:
            return f"{base} {unit}"
        return base


def propagate_uncertainty(
    expression: str,
    variables: dict[str, Any],
    correlations: list[dict[str, Any]] | dict[str, Any] | None = None,
    method: str = "both",
    n_samples: int = 50000,
    seed: int | None = None,
    confidence: float = 0.95,
    autofill_constants: bool = True,
) -> dict[str, Any]:
    """Propagate uncertainty through an expression using linear GUM, Monte Carlo, or both."""
    expr = safe_parse_expr(expression)
    free_syms = {str(s) for s in expr.free_symbols}

    # Normalize variables dict
    vars_clean: dict[str, dict[str, Any]] = {}
    for k, v in variables.items():
        if isinstance(v, (int, float)):
            vars_clean[k] = {"value": float(v), "uncertainty": 0.0, "unit": "", "distribution": "normal"}
        elif isinstance(v, dict):
            val = float(v.get("value", 0.0))
            unc = float(v.get("uncertainty", 0.0))
            unit_str = str(v.get("unit") or "")
            dist = str(v.get("distribution") or "normal").lower()
            vars_clean[k] = {"value": val, "uncertainty": unc, "unit": unit_str, "distribution": dist}

    # Autofill CODATA constants if requested
    autofilled: list[str] = []
    if autofill_constants:
        for sym_name in free_syms:
            if sym_name not in vars_clean and sym_name in _SYMBOL_TO_CODATA_KEY:
                const_data = _lookup_codata(sym_name)
                if const_data and "value" in const_data:
                    c_val = float(const_data["value"])
                    c_unc = float(const_data.get("uncertainty") or 0.0)
                    c_unit = str(const_data.get("unit") or "")
                    vars_clean[sym_name] = {
                        "value": c_val,
                        "uncertainty": c_unc,
                        "unit": c_unit,
                        "distribution": "normal",
                    }
                    autofilled.append(sym_name)

    missing = free_syms - set(vars_clean.keys())
    if missing:
        raise ValueError(f"Variables {sorted(missing)} in expression '{expression}' have no values or uncertainties.")

    # Unit analysis with Pint
    ureg = get_unit_registry()
    has_units = any(bool(v.get("unit")) for v in vars_clean.values())
    resulting_unit_str = ""
    unit_compatible = True
    if has_units:
        try:
            # Build pint quantities for nominal evaluation
            unit_env: dict[str, Any] = {}
            for k, v in vars_clean.items():
                u_str = v.get("unit", "")
                if u_str:
                    unit_env[k] = ureg.Quantity(v["value"], ureg.parse_units(u_str))
                else:
                    unit_env[k] = ureg.Quantity(v["value"])
            # Lambdify with pint-compatible functions
            sym_list = [sp.Symbol(k) for k in vars_clean.keys()]
            f_unit = sp.lambdify(sym_list, expr, modules=["numpy", {"pi": math.pi, "e": math.e}])
            nominal_q = f_unit(*(unit_env[k] for k in vars_clean.keys()))
            if isinstance(nominal_q, ureg.Quantity):
                resulting_unit_str = _canonical_unit_name(nominal_q.units, ureg)
        except Exception:
            unit_compatible = False
            resulting_unit_str = ""

    # 1. Linear Propagation (first-order GUM)
    nominal_vals = {sp.Symbol(k): vars_clean[k]["value"] for k in vars_clean}
    nominal_val_sympy = expr.subs(nominal_vals)
    nominal_val = float(nominal_val_sympy.evalf())

    # Build standard uncertainties (converting distributions if needed)
    std_uncs: dict[str, float] = {}
    for k, v in vars_clean.items():
        unc = v["uncertainty"]
        dist = v.get("distribution", "normal")
        if dist == "uniform":
            std_uncs[k] = unc / math.sqrt(3.0)
        else:
            std_uncs[k] = unc

    # Partial derivatives & sensitivity coefficients
    sensitivities: dict[str, float] = {}
    contributions: dict[str, float] = {}
    var_contributions: dict[str, float] = {}
    var_symbols = list(vars_clean.keys())

    for k in var_symbols:
        sym = sp.Symbol(k)
        deriv = sp.diff(expr, sym)
        deriv_val = float(deriv.subs(nominal_vals).evalf())
        sensitivities[k] = deriv_val
        u_k = std_uncs[k]
        contributions[k] = abs(deriv_val) * u_k
        var_contributions[k] = (deriv_val * u_k) ** 2

    # Process correlations
    corr_matrix: dict[tuple[str, str], float] = {}
    if isinstance(correlations, list):
        for c in correlations:
            v1 = c.get("var1") or c.get("x")
            v2 = c.get("var2") or c.get("y")
            r = float(c.get("r") or c.get("coefficient") or c.get("correlation", 0.0))
            if v1 and v2 and v1 in vars_clean and v2 in vars_clean:
                corr_matrix[(v1, v2)] = r
                corr_matrix[(v2, v1)] = r
    elif isinstance(correlations, dict):
        for pair_key, r_val in correlations.items():
            parts = str(pair_key).replace(":", ",").split(",")
            if len(parts) == 2:
                v1, v2 = parts[0].strip(), parts[1].strip()
                if v1 in vars_clean and v2 in vars_clean:
                    r = float(r_val)
                    corr_matrix[(v1, v2)] = r
                    corr_matrix[(v2, v1)] = r

    # Total variance: sum c_i^2 u_i^2 + 2 sum c_i c_j u_i u_j r_ij
    total_var = sum(var_contributions.values())
    for i in range(len(var_symbols)):
        for j in range(i + 1, len(var_symbols)):
            v1, v2 = var_symbols[i], var_symbols[j]
            r = corr_matrix.get((v1, v2), 0.0)
            if r != 0.0:
                c1, c2 = sensitivities[v1], sensitivities[v2]
                u1, u2 = std_uncs[v1], std_uncs[v2]
                total_var += 2.0 * c1 * c2 * u1 * u2 * r

    total_var = max(0.0, total_var)
    linear_std_unc = math.sqrt(total_var)
    linear_expanded_unc = 2.0 * linear_std_unc

    # Budget percentage
    budget = []
    uncorrelated_var_sum = sum(var_contributions.values()) or 1e-30
    for k in var_symbols:
        pct = (var_contributions[k] / uncorrelated_var_sum) * 100.0 if uncorrelated_var_sum > 0 else 0.0
        budget.append(
            {
                "variable": k,
                "value": vars_clean[k]["value"],
                "std_uncertainty": std_uncs[k],
                "unit": vars_clean[k].get("unit", ""),
                "distribution": vars_clean[k].get("distribution", "normal"),
                "sensitivity": sensitivities[k],
                "contribution": contributions[k],
                "variance_contribution": var_contributions[k],
                "percentage": round(pct, 2),
            }
        )

    linear_result = {
        "nominal_value": nominal_val,
        "standard_uncertainty": linear_std_unc,
        "expanded_uncertainty": linear_expanded_unc,
        "coverage_factor": 2.0,
        "sensitivities": sensitivities,
        "budget": budget,
    }

    # 2. Monte Carlo Propagation
    mc_result: dict[str, Any] | None = None
    warnings: list[str] = []

    if method in ("monte_carlo", "both"):
        rng = np.random.default_rng(seed)
        n = max(1000, min(n_samples, 500000))

        # Check if correlations exist
        has_correlations = len(corr_matrix) > 0
        if has_correlations and len(var_symbols) > 1:
            cov = np.zeros((len(var_symbols), len(var_symbols)))
            for i, v1 in enumerate(var_symbols):
                for j, v2 in enumerate(var_symbols):
                    if i == j:
                        cov[i, j] = 1.0
                    else:
                        cov[i, j] = corr_matrix.get((v1, v2), 0.0)
            try:
                L = np.linalg.cholesky(cov)
                z = rng.standard_normal((len(var_symbols), n))
                correlated_z = L @ z
            except np.linalg.LinAlgError:
                correlated_z = rng.standard_normal((len(var_symbols), n))
        else:
            correlated_z = rng.standard_normal((len(var_symbols), n))

        # Map to distributions
        sample_dict: dict[str, np.ndarray] = {}
        for idx, k in enumerate(var_symbols):
            v_info = vars_clean[k]
            mean_val = v_info["value"]
            dist = v_info.get("distribution", "normal")
            u_std = std_uncs[k]

            if dist == "uniform":
                half_w = u_std * math.sqrt(3.0)
                sample_dict[k] = rng.uniform(mean_val - half_w, mean_val + half_w, size=n)
            elif dist == "lognormal":
                if mean_val > 0 and u_std > 0:
                    s2 = math.log(1.0 + (u_std / mean_val) ** 2)
                    s = math.sqrt(s2)
                    m = math.log(mean_val) - 0.5 * s2
                    sample_dict[k] = np.exp(m + s * correlated_z[idx])
                else:
                    sample_dict[k] = mean_val + u_std * correlated_z[idx]
            else:  # normal
                sample_dict[k] = mean_val + u_std * correlated_z[idx]

        # Vectorized evaluation
        sym_list = [sp.Symbol(k) for k in var_symbols]
        f_eval = sp.lambdify(sym_list, expr, modules=["numpy", {"pi": math.pi, "e": math.e}])
        try:
            samples_y = f_eval(*(sample_dict[k] for k in var_symbols))
            if np.isscalar(samples_y):
                samples_y = np.full(n, float(samples_y))
            else:
                samples_y = np.asarray(samples_y, dtype=float)
            samples_y = samples_y[np.isfinite(samples_y)]
        except Exception as exc:
            samples_y = np.array([])
            warnings.append(f"Monte Carlo evaluation encountered an error: {exc}")

        if len(samples_y) > 10:
            mc_mean = float(np.mean(samples_y))
            mc_std = float(np.std(samples_y, ddof=1))
            alpha = (1.0 - confidence) / 2.0
            p_low = float(np.percentile(samples_y, alpha * 100))
            p_high = float(np.percentile(samples_y, (1.0 - alpha) * 100))

            # Skewness
            m3 = float(np.mean((samples_y - mc_mean) ** 3))
            mc_skew = float(m3 / (mc_std**3)) if mc_std > 1e-12 else 0.0

            # Histogram
            counts, bin_edges = np.histogram(samples_y, bins=25)
            hist_data = {
                "counts": [int(c) for c in counts],
                "bin_edges": [float(b) for b in bin_edges],
            }

            mc_result = {
                "mean": mc_mean,
                "std": mc_std,
                "interval_95": [p_low, p_high],
                "skewness": mc_skew,
                "n_samples": len(samples_y),
                "histogram": hist_data,
            }

            # Check nonlinearity
            if method == "both" and linear_std_unc > 1e-12:
                std_diff_pct = abs(mc_std - linear_std_unc) / linear_std_unc
                mean_diff_pct = abs(mc_mean - nominal_val) / linear_std_unc
                if std_diff_pct > 0.05 or mean_diff_pct > 0.1 or abs(mc_skew) > 0.25:
                    warnings.append(
                        f"Nonlinear propagation detected: first-order GUM (std={linear_std_unc:.4g}) and "
                        f"Monte Carlo (std={mc_std:.4g}, skewness={mc_skew:.2f}) disagree by {std_diff_pct * 100:.1f}%."
                    )

    # Primary values
    primary_val = nominal_val if method != "monte_carlo" else (mc_result["mean"] if mc_result else nominal_val)
    primary_unc = linear_std_unc if method != "monte_carlo" else (mc_result["std"] if mc_result else linear_std_unc)
    primary_exp = 2.0 * primary_unc

    formatted_str = format_uncertainty_result(primary_val, primary_unc, unit=resulting_unit_str, k=2.0)

    out: dict[str, Any] = {
        "expression": expression,
        "nominal_value": primary_val,
        "standard_uncertainty": primary_unc,
        "expanded_uncertainty": primary_exp,
        "coverage_factor": 2.0,
        "unit": resulting_unit_str,
        "unit_compatible": unit_compatible,
        "formatted": formatted_str,
        "method": method,
        "budget": budget,
        "linear": linear_result,
        "monte_carlo": mc_result,
        "warnings": warnings,
        "autofilled_constants": autofilled,
    }
    return out
