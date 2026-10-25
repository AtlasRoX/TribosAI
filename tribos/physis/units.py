"""Dimensional Analysis & Unit Conversion Engine powered by Pint."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pint

PHYSICAL_VAR_SUBS = [
    (re.compile(r"\bcos\s*\([^)]*\)", re.I), "1"),
    (re.compile(r"\bsin\s*\([^)]*\)", re.I), "1"),
    (re.compile(r"\bexp\s*\([^)]*\)", re.I), "1"),
    (re.compile(r"x\'\'", re.I), "(m/s**2)"),
    (re.compile(r"x\'", re.I), "(m/s)"),
    (re.compile(r"\bm\s*\*", re.I), "kg * "),
    (re.compile(r"\bc\s*\*", re.I), "(N*s/m) * "),
    (re.compile(r"\bk\s*\*", re.I), "(N/m) * "),
    (re.compile(r"\bx\b", re.I), "m"),
    (re.compile(r"\bF0\b", re.I), "N"),
    (re.compile(r"\bF\b", re.I), "N"),
]


def _parse_side_expression(ureg: pint.UnitRegistry, s_expr: str) -> pint.Quantity:
    s = s_expr.strip()
    try:
        if any(ch.isdigit() for ch in s[:2]):
            return ureg.Quantity(s)
        return 1.0 * ureg.parse_expression(s)
    except Exception:
        # Fall back to physical ODE variable substitutions
        subbed = s
        for pat, sub in PHYSICAL_VAR_SUBS:
            subbed = pat.sub(sub, subbed)
        try:
            return 1.0 * ureg.parse_expression(subbed)
        except Exception as exc:
            raise ValueError(f"Could not parse unit expression {s_expr!r}: {exc}") from exc

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
    # "F = m*a": Pint would read the variables as units (farad, annum) and report a false mismatch.
    symbolic = [side for side in (lhs_str, rhs_str) if _is_symbolic_term(side)]
    if symbolic:
        raise ValueError(_variables_message(raw, symbolic))

    lhs_q = _parse_side_expression(ureg, lhs_str)
    rhs_q = _parse_side_expression(ureg, rhs_str)

    lhs_base = lhs_q.to_base_units()
    rhs_base = rhs_q.to_base_units()
    lhs_dim = str(lhs_base.dimensionality)
    rhs_dim = str(rhs_base.dimensionality)
    homogeneous = lhs_base.dimensionality == rhs_base.dimensionality

    return {
        "equation": raw,
        "lhs": lhs_str,
        "rhs": rhs_str,
        "lhs_base_si_unit": f"{lhs_base.units:~}",
        "rhs_base_si_unit": f"{rhs_base.units:~}",
        "lhs_dimensionality": lhs_dim,
        "rhs_dimensionality": rhs_dim,
        "dimensionality": lhs_dim if homogeneous else f"{lhs_dim} != {rhs_dim}",
        "compatible": homogeneous,
        "equation_homogeneous": homogeneous,
        "canonical_id": _canonical_unit_id(f"eq:{lhs_str}={rhs_str}"),
    }


# One-letter SI unit symbols; any other lone letter in a part ("c x'", "k x") is a physical variable, not a unit.
_SI_LETTERS = frozenset("m s g K A N J W V C F H T L".split())
_FUNCTION_RE = re.compile(r"\b(?:sin|cos|tan|exp|log|ln|sqrt|sinh|cosh|tanh)\s*\(", re.I)


def _is_symbolic_term(part: str) -> bool:
    """A term written with variables ("c x'", "k x", "F0 cos(omega t)") rather than units. Pint would read some of
    these as units (c = speed of light, k = Boltzmann constant), so they are recognised before parsing."""
    if "'" in part or _FUNCTION_RE.search(part):
        return True
    for token in re.findall(r"[A-Za-z_]+\d*", part):
        if re.search(r"[A-Za-z]\d+$", token):  # "F0", "x1": a symbol with an index, not a unit
            return True
        if len(token) == 1 and token not in _SI_LETTERS:
            return True
    return False


def _variables_message(equation: str, terms: list[str]) -> str:
    return (f"{equation.strip()!r} is written with variables ({', '.join(repr(t) for t in terms[:3])}), not units, so "
            "its dimensions cannot be checked: Pint would read single letters as units (F as farad, a as annum). "
            "Write each side in units, e.g. 'N = kg*m/s^2'.")


def check_equation_set(text: str) -> dict[str, Any]:
    """Several unit equations at once, as models write a dimensional check: 'a = b; c = d' or a chain 'a = b = c' (each
    neighbouring pair is checked). A part that is not a unit expression (a term written before its units, such as
    "c x' = (N*s/m) * (m/s)") is skipped; the result is homogeneous only when every checked pair is."""
    ureg = get_unit_registry()
    checks: list[dict[str, Any]] = []
    symbolic: list[str] = []
    for segment in re.split(r"[;\n]+", text or ""):
        units: list[str] = []
        for part in (p.strip() for p in re.split(r"==?", segment)):
            if part and _is_symbolic_term(part):
                symbolic.append(part)
                continue
            if not part:
                continue
            try:
                _parse_side_expression(ureg, part)
            except Exception:  # noqa: BLE001 - not a unit expression: skipped, never fatal for the other pairs
                continue
            units.append(part)
        checks.extend(check_dimensional_homogeneity(f"{a} = {b}") for a, b in zip(units, units[1:], strict=False))
    if not checks:
        if symbolic:
            raise ValueError(_variables_message(text, symbolic))
        raise ValueError("check_equation has no 'lhs = rhs' pair written in units (e.g. 'kg * m/s^2 = N').")
    ok = all(c["equation_homogeneous"] for c in checks)
    bad = [c["equation"] for c in checks if not c["equation_homogeneous"]]
    return {
        **checks[0],
        "equation": (text or "").strip(),
        "checks": checks,
        "dimensionality": checks[0]["dimensionality"] if ok else "not homogeneous: " + "; ".join(bad),
        "compatible": ok,
        "equation_homogeneous": ok,
        "canonical_id": _canonical_unit_id(f"eqset:{(text or '').strip()}"),
    }


def _check_equations(text: str) -> dict[str, Any]:
    """One 'lhs = rhs', or a set / chain of them."""
    return check_equation_set(text) if (";" in text or "\n" in text or text.count("=") > 1) else check_dimensional_homogeneity(text)


def convert_units(
    value: float = 1.0,
    from_unit: str = "",
    to_unit: str | None = None,
    check_equation: str | None = None,
) -> dict[str, Any]:
    """Convert a physical quantity between units, reduce to base SI units, or check dimensional homogeneity."""
    # If an equation containing '=' was passed as from_unit or check_equation
    equation_input = (check_equation or "").strip()
    if not equation_input and from_unit and ("=" in from_unit or "==" in from_unit):
        equation_input = from_unit.strip()
        from_unit = ""

    if equation_input:
        eq_res = _check_equations(equation_input)
        if not from_unit:
            return {
                "input_value": float(value),
                "input_unit": "",
                "converted_value": float(value),
                "converted_unit": "",
                "base_si_value": float(value),
                "base_si_unit": eq_res.get("lhs_base_si_unit", ""),
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
    base_unit = f"{base_qty.units:~}" or "dimensionless"
    dim_str = str(base_qty.dimensionality)

    compatible = True
    error_msg: str | None = None
    if to_unit and to_unit.strip():
        target_str = to_unit.strip()
        try:
            target_qty = qty.to(target_str)
            conv_val = float(target_qty.magnitude)
            conv_unit = f"{target_qty.units:~}" or target_str
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
        eq_res = _check_equations(check_equation)
        result["equation_check"] = eq_res
        result["equation_homogeneous"] = eq_res["equation_homogeneous"]
    return result


__all__ = [
    "PHYSICAL_VAR_SUBS",
    "check_dimensional_homogeneity",
    "check_equation_set",
    "convert_units",
    "get_unit_registry",
]
