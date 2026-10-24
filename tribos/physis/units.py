"""Dimensional Analysis & Unit Conversion Engine powered by Pint."""

from __future__ import annotations

import hashlib
from typing import Any

import pint

_UREG: pint.UnitRegistry | None = None


def get_unit_registry() -> pint.UnitRegistry:
    """Return a shared Pint UnitRegistry instance."""
    global _UREG
    if _UREG is None:
        _UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
    return _UREG


def _canonical_unit_id(payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"pint_{digest}"


def check_dimensional_homogeneity(equation: str) -> dict[str, Any]:
    """Check whether both sides of an equation ('lhs = rhs') have identical physical dimensions."""
    ureg = get_unit_registry()
    raw = (equation or "").strip()
    if "==" in raw:
        parts = raw.split("==", 1)
    elif "=" in raw:
        parts = raw.split("=", 1)
    else:
        raise ValueError("check_equation must contain '=' separating left-hand and right-hand expressions.")

    lhs_str, rhs_str = parts[0].strip(), parts[1].strip()
    if not lhs_str or not rhs_str:
        raise ValueError("Both left-hand and right-hand expressions must be non-empty.")

    lhs_q = ureg.Quantity(lhs_str) if any(ch.isdigit() for ch in lhs_str[:2]) else 1.0 * ureg.parse_expression(lhs_str)
    rhs_q = ureg.Quantity(rhs_str) if any(ch.isdigit() for ch in rhs_str[:2]) else 1.0 * ureg.parse_expression(rhs_str)

    lhs_base = lhs_q.to_base_units()
    rhs_base = rhs_q.to_base_units()
    lhs_dim = str(lhs_base.dimensionality)
    rhs_dim = str(rhs_base.dimensionality)
    homogeneous = lhs_base.dimensionality == rhs_base.dimensionality

    return {
        "equation": raw,
        "lhs": lhs_str,
        "rhs": rhs_str,
        "lhs_base_si_unit": f"{lhs_base.units:~P}",
        "rhs_base_si_unit": f"{rhs_base.units:~P}",
        "lhs_dimensionality": lhs_dim,
        "rhs_dimensionality": rhs_dim,
        "dimensionality": lhs_dim if homogeneous else f"{lhs_dim} != {rhs_dim}",
        "compatible": homogeneous,
        "equation_homogeneous": homogeneous,
        "canonical_id": _canonical_unit_id(f"eq:{lhs_str}={rhs_str}"),
    }


def convert_units(
    value: float = 1.0,
    from_unit: str = "",
    to_unit: str | None = None,
    check_equation: str | None = None,
) -> dict[str, Any]:
    """Convert a physical quantity between units, reduce to base SI units, or check dimensional homogeneity."""
    if check_equation and check_equation.strip():
        eq_res = check_dimensional_homogeneity(check_equation)
        if not from_unit:
            return {
                "input_value": float(value),
                "input_unit": "",
                "converted_value": float(value),
                "converted_unit": "",
                "base_si_value": float(value),
                "base_si_unit": eq_res["lhs_base_si_unit"],
                "latex": "",
                **eq_res,
            }

    ureg = get_unit_registry()
    src_unit_str = (from_unit or "").strip()
    if not src_unit_str:
        raise ValueError("Either 'from_unit' or 'check_equation' must be provided.")

    try:
        qty = ureg.Quantity(float(value), src_unit_str)
    except (pint.UndefinedUnitError, pint.DefinitionSyntaxError) as exc:
        raise ValueError(f"Undefined or invalid source unit '{src_unit_str}': {exc}") from exc

    base_qty = qty.to_base_units()
    base_val = float(base_qty.magnitude)
    base_unit = f"{base_qty.units:~P}" or "dimensionless"
    dim_str = str(base_qty.dimensionality)

    compatible = True
    error_msg: str | None = None
    if to_unit and to_unit.strip():
        target_str = to_unit.strip()
        try:
            target_qty = qty.to(target_str)
            conv_val = float(target_qty.magnitude)
            conv_unit = f"{target_qty.units:~P}" or target_str
            latex_str = f"{target_qty:~L}"
        except pint.DimensionalityError as exc:
            compatible = False
            conv_val = base_val
            conv_unit = base_unit
            latex_str = f"{base_qty:~L}"
            error_msg = str(exc)
        except (pint.UndefinedUnitError, pint.DefinitionSyntaxError) as exc:
            raise ValueError(f"Undefined or invalid target unit '{target_str}': {exc}") from exc
    else:
        conv_val = base_val
        conv_unit = base_unit
        latex_str = f"{base_qty:~L}"

    result: dict[str, Any] = {
        "input_value": float(value),
        "input_unit": src_unit_str,
        "converted_value": conv_val,
        "converted_unit": conv_unit,
        "base_si_value": base_val,
        "base_si_unit": base_unit,
        "dimensionality": dim_str,
        "compatible": compatible,
        "latex": latex_str,
        "canonical_id": _canonical_unit_id(f"{value}:{src_unit_str}->{to_unit or 'SI'}"),
    }
    if error_msg:
        result["error"] = error_msg
    if check_equation and check_equation.strip():
        eq_res = check_dimensional_homogeneity(check_equation)
        result["equation_check"] = eq_res
        result["equation_homogeneous"] = eq_res["equation_homogeneous"]
    return result


__all__ = [
    "check_dimensional_homogeneity",
    "convert_units",
    "get_unit_registry",
]
