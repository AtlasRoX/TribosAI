"""The calculator framework: unit-validated inputs, material defaults, results, utilisation and uncertainty.

A calculator declares its inputs (`Param`, each with the SI unit the formulas use) and a pure `compute` function
over SI floats. `run` converts the caller's inputs with Pint (a bare number is taken in the parameter's unit), fills
material properties the caller did not give, runs the formulas, and, when inputs carry uncertainties, propagates them
to every result by first-order GUM (central differences on `compute`, so piecewise formulas work too), formatted
like the uncertainty tool (T3): value +/- U with k = 2.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tribos.physis.uncertainty import format_uncertainty_result
from tribos.physis.units import get_unit_registry

from .materials import MATERIALS_NOTE, find_material


@dataclass(frozen=True)
class Reference:
    source: str
    section: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "section": self.section}


@dataclass(frozen=True)
class Param:
    """One input. `unit` is the SI unit the formulas use ("1" for a dimensionless number)."""

    name: str
    unit: str
    description: str
    default: Any = None  # None: required (unless filled from the material)
    choices: tuple[str, ...] = ()  # a text input with these values
    material: str | None = None  # the material property that fills it ("E", "yield_strength", ...)
    positive: bool = True
    optional: bool = False  # may stay unset (the formulas handle None)

    @property
    def is_choice(self) -> bool:
        return bool(self.choices)


@dataclass
class Result:
    name: str
    label: str
    value: float
    unit: str
    display_unit: str | None = None  # a friendlier unit to show the value in (e.g. "MPa" for "Pa")


@dataclass
class Check:
    """A utilisation check (a limit state) or a validity check of the method's assumptions."""

    name: str
    ok: bool
    detail: str
    utilisation: float | None = None  # demand / capacity, where 1 is the limit


@dataclass
class Outcome:
    results: list[Result]
    checks: list[Check] = field(default_factory=list)  # limit states: the governing one sets the utilisation
    validity: list[Check] = field(default_factory=list)  # assumptions of the method
    formulas: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Calculator:
    id: str
    title: str
    summary: str
    reference: Reference
    params: tuple[Param, ...]
    compute: Callable[[dict[str, Any]], Outcome]
    assumptions: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "reference": self.reference.to_dict(),
            "inputs": [
                {
                    "name": p.name, "unit": p.unit, "description": p.description,
                    "required": p.default is None and p.material is None and not p.optional,
                    "default": p.default, "choices": list(p.choices) or None, "from_material": p.material,
                }
                for p in self.params
            ],
            "assumptions": list(self.assumptions),
        }


# -- Inputs ------------------------------------------------------------------------------------------------------

_MAX_TEXT = 120


def _normalise_unit_text(text: str) -> str:
    return text.replace("°C", "degC").replace("°F", "degF").replace("µ", "u").replace("μ", "u").replace("Ω", "ohm")


def _quantity(param: Param, raw: Any) -> tuple[float, float | None, str]:
    """(value in the parameter's SI unit, its standard uncertainty in that unit or None, the input as written).

    A bare number (or a string without a unit) is taken in the parameter's own unit.
    """
    ureg = get_unit_registry()
    target = ureg.dimensionless if param.unit == "1" else ureg.parse_units(param.unit)
    expected = ureg.Quantity(1, target).dimensionality
    uncertainty_raw: Any = None
    unit_text = ""
    if isinstance(raw, dict):
        value_raw = raw.get("value")
        unit_text = _normalise_unit_text(str(raw.get("unit") or "").strip())
        uncertainty_raw = raw.get("uncertainty")
    else:
        value_raw = raw
    shown = value_raw.strip() if isinstance(value_raw, str) else f"{value_raw} {unit_text}".strip()

    def convert(number: Any, text: str) -> float:
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            q = ureg.Quantity(float(number), ureg.parse_units(text) if text else target)
        elif isinstance(number, str) and 0 < len(number.strip()) <= _MAX_TEXT:
            body = _normalise_unit_text(number.strip())
            q = ureg.Quantity(float(body), ureg.parse_units(text)) if text else ureg.Quantity(body)
            if q.unitless:
                q = ureg.Quantity(float(q.magnitude), target)
        else:
            raise ValueError(f"Input {param.name!r} must be a number, a quantity such as '250 MPa' or {{value, unit}}, "
                             f"got {number!r}.")
        if q.dimensionality != expected:
            raise ValueError(
                f"Input {param.name!r} = {shown} has the dimensions {q.dimensionality}, but it needs {expected} "
                f"(for example {param.unit})."
            )
        out = float(q.to(target).magnitude)
        if not math.isfinite(out):
            raise ValueError(f"Input {param.name!r} must be finite.")
        return out

    try:
        value = convert(value_raw, unit_text)
        uncertainty = None
        if uncertainty_raw not in (None, "", 0, 0.0):
            if param.unit == "degC":
                # An uncertainty is a temperature difference: a bare number or one in K or degC is that difference.
                uncertainty = abs(float(uncertainty_raw))
            else:
                uncertainty = abs(convert(uncertainty_raw, unit_text))
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001  (Pint's own parse and dimensionality errors)
        raise ValueError(f"Could not read input {param.name!r} = {raw!r}: {exc}") from exc
    return value, uncertainty, shown


def to_si(raw: Any, unit: str, name: str, *, positive: bool = True) -> float:
    """One quantity (a number in `unit`, a string such as '5 mm', or {value, unit}) in `unit`, for list inputs."""
    value, _u, shown = _quantity(Param(name=name, unit=unit, description=name), raw)
    if positive and value <= 0.0:
        raise ValueError(f"{name} must be positive, got {shown}.")
    return value


# Names a model or a person often writes for an input; each applies only where the calculator has that input.
INPUT_ALIASES: dict[str, str] = {
    "L": "length", "l": "length", "span": "length", "P": "point_load", "F_point": "point_load", "load_value": "point_load",
    "w": "distributed_load", "q": "distributed_load", "udl": "distributed_load", "a": "load_position",
    "b": "width", "h": "height", "depth": "height", "d": "diameter", "D": "diameter", "outer_diameter": "diameter",
    "di": "inner_diameter", "d_i": "inner_diameter", "E": "elastic_modulus", "youngs_modulus": "elastic_modulus",
    "modulus": "elastic_modulus", "I": "second_moment_of_area", "moment_of_inertia": "second_moment_of_area",
    "c": "extreme_fibre_distance", "A": "area", "T": "torque", "M": "bending_moment", "K": "effective_length_factor",
    "Sy": "yield_strength", "S_y": "yield_strength", "fy": "yield_strength", "Sut": "ultimate_strength",
    "S_ut": "ultimate_strength", "Se": "endurance_limit", "S_e": "endurance_limit", "nu": "poisson_ratio",
    "G": "shear_modulus", "t": "thickness", "wall_thickness": "thickness", "p": "pressure", "S": "allowable_stress",
    "joint_factor": "joint_efficiency", "sigma_a": "stress_amplitude", "sigma_m": "mean_stress",
    "alternating_stress": "stress_amplitude", "Q": "flow_rate", "V": "velocity", "rho": "density", "mu": "viscosity",
    "epsilon": "roughness", "eps": "roughness", "U": "overall_coefficient", "configuration": "support",
    "support_type": "support", "boundary": "support", "load_type": "load", "loading": "load",
    "safety_factor": "required_safety_factor", "n": "required_safety_factor",
    # Names model planners send (seen in live runs): the beam's support and load case, a lower-case modulus, and the
    # plain-English names of common inputs.
    "beam_type": "support", "support_condition": "support", "supports": "support", "end_condition": "support",
    "boundary_condition": "support", "boundary_conditions": "support", "load_case": "load", "load_kind": "load",
    "loading_type": "load", "load_configuration": "load", "e": "elastic_modulus", "young_modulus": "elastic_modulus",
    "elastic_modulus_e": "elastic_modulus", "span_length": "length", "beam_length": "length", "F": "point_load",
    "force": "point_load", "point_force": "point_load", "concentrated_load": "point_load", "load_magnitude": "point_load",
    "breadth": "width", "section_width": "width", "section_height": "height", "section_depth": "height",
    "dia": "diameter", "outside_diameter": "diameter", "inside_diameter": "inner_diameter", "id": "inner_diameter",
    "od": "diameter", "yield_stress": "yield_strength", "yield": "yield_strength", "factor_of_safety": "required_safety_factor",
    "fos": "required_safety_factor", "sf": "required_safety_factor", "deflection_limit": "deflection_limit_ratio",
}
# An alias that names a close relative when the calculator lacks the input itself (a vessel's "diameter" is its
# inner diameter in the thin-wall formula).
_FALLBACK_TARGETS: dict[str, str] = {"diameter": "inner_diameter"}


def _alias_target(key: str, known: set[str]) -> str:
    target = INPUT_ALIASES.get(key) or INPUT_ALIASES.get(key.lower(), key)
    if target not in known and key.lower() in known:
        target = key.lower()
    if target not in known and _FALLBACK_TARGETS.get(target) in known:
        target = _FALLBACK_TARGETS[target]
    return target


def _split_unit_suffix(key: str, known: set[str], choice_params: set[str]) -> tuple[str, str] | None:
    """An input name with its unit written in (span_m, P_kN, E_GPa, flow_rate_m3_per_s) as (input, unit), trying every
    split from the right; None when no suffix is a unit or the rest names no numeric input of this calculator."""
    parts = key.split("_")
    for i in range(len(parts) - 1, 0, -1):
        base, unit = "_".join(parts[:i]), "_".join(parts[i:])
        unit = re.sub(r"^in_", "", unit)
        unit = re.sub(r"_?per_?", "/", unit)
        unit = re.sub(r"(?<=[A-Za-z])([23])(?![0-9])", r"^\1", unit)  # m3 -> m^3, s2 -> s^2
        target = base if base in known else _alias_target(base, known)
        if target not in known or target in choice_params:
            continue
        try:
            get_unit_registry().parse_units(_normalise_unit_text(unit))
        except Exception:  # noqa: BLE001 - not a unit: try the next split
            continue
        return target, unit
    return None
# Words for a choice that mean one of its values.
CHOICE_ALIASES: dict[str, dict[str, str]] = {
    "support": {"cantilevered": "cantilever", "fixed_free": "cantilever", "simply": "simply_supported",
                "pinned_pinned": "simply_supported", "simple": "simply_supported", "simply_supported_beam": "simply_supported"},
    "load": {"point_load": "point", "end_point_load": "point", "end_load": "point", "tip_load": "point",
             "tip_point_load": "point", "concentrated": "point", "concentrated_load": "point", "uniform": "udl",
             "uniform_load": "udl", "distributed": "udl", "uniformly_distributed": "udl",
             "uniformly_distributed_load": "udl"},
}


def _canonical_inputs(calc: Calculator, inputs: dict[str, Any]) -> dict[str, Any]:
    """The inputs keyed by the calculator's own names: an alias maps to its input when the calculator has it and the
    input was not also given under its own name."""
    known = {p.name for p in calc.params}
    choice_params = {p.name for p in calc.params if p.is_choice}
    inputs = dict(inputs)
    # A magnitude sent as the load case ({"load": "12 kN", "load_type": "point"}): the number is the point load (or the
    # distributed load for a force per length), and the case comes from the other key.
    if "load" in choice_params and _is_quantity(inputs.get("load")):
        magnitude = inputs.pop("load")
        per_length = isinstance(magnitude, str) and "/" in magnitude
        dest = "distributed_load" if per_length and "distributed_load" in known else "point_load"
        if dest in known and dest not in inputs:
            inputs[dest] = magnitude
        else:
            inputs["load"] = magnitude  # nowhere to move it: left for the normal validation error
    out: dict[str, Any] = {}
    for key, value in inputs.items():
        target = key if key in known else _alias_target(key, known)
        if target not in known:
            split = _split_unit_suffix(key, known, choice_params)
            if split is not None:
                target, unit = split
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = f"{value} {unit}"  # the unit in the name applies to a bare number
        if target in known and target != key and target in inputs:
            target = key  # the input is also given under its own name; the alias is left as an unknown input
        out[target] = value
    return out


def _is_quantity(value: Any) -> bool:
    """A number, or a string that starts with one ("12 kN", "5e3"): a magnitude rather than a choice word."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and bool(re.match(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\b", value))


def _example_inputs(calc: Calculator) -> str:
    """A short example call in the calculator's own names: {"length": "<value> m", "support": "simply_supported"}."""
    parts = []
    for p in calc.params[:4]:
        value = p.choices[0] if p.is_choice else f"<value> {p.unit}".strip()
        parts.append(f'"{p.name}": "{value}"')
    return "{" + ", ".join(parts) + ", ...}"


def _resolve_inputs(calc: Calculator, inputs: dict[str, Any], material: str | None) -> tuple[dict[str, Any], dict[str, float], list[dict[str, Any]], dict[str, Any] | None]:
    inputs = _canonical_inputs(calc, inputs)
    known = {p.name for p in calc.params}
    unknown = sorted(set(inputs) - known)
    if unknown:
        raise ValueError(
            f"Unknown input(s) {unknown} for the {calc.id} calculator; its inputs are "
            + ", ".join(f"{p.name} [{p.unit or '/'.join(p.choices)}]" for p in calc.params) + ". "
            + "Retry with these exact names; a value may carry its unit as a string, for example "
            + _example_inputs(calc) + "."
        )
    mat_props: dict[str, Any] | None = None
    mat_id = None
    if material:
        mat_id, mat_props = find_material(material)
    values: dict[str, Any] = {}
    uncertainties: dict[str, float] = {}
    table: list[dict[str, Any]] = []
    missing: list[str] = []
    for p in calc.params:
        raw = inputs.get(p.name)
        source = "given"
        if raw is None and p.material and mat_props is not None and mat_props.get(p.material) is not None:
            raw, source = mat_props[p.material], f"material {mat_id}"
        if raw is None and p.default is not None:
            raw, source = p.default, "default"
        if raw is None:
            if p.optional:
                values[p.name] = None
                continue
            missing.append(p.name)
            continue
        if p.is_choice:
            choice = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
            choice = CHOICE_ALIASES.get(p.name, {}).get(choice, choice)
            if choice not in p.choices:
                # Safe normalization of unambiguous descriptions
                if p.name == "load":
                    if "point" in choice or "tip" in choice or "concentrat" in choice:
                        choice = "point"
                    elif "udl" in choice or "distribut" in choice or "uniform" in choice:
                        choice = "udl"
                elif p.name == "support":
                    if "cantilever" in choice or "fixed" in choice:
                        choice = "cantilever"
                    elif "simply" in choice or "pin" in choice:
                        choice = "simply_supported"
            if choice not in p.choices:
                raise ValueError(f"Input {p.name!r} must be one of {', '.join(p.choices)}, got {raw!r}.")
            values[p.name] = choice
            table.append({"name": p.name, "value": choice, "unit": "", "source": source, "description": p.description})
            continue
        if isinstance(raw, list):
            values[p.name] = raw  # a list input (layers, load blocks) is validated by the calculator
            table.append({"name": p.name, "value": raw, "unit": p.unit, "source": source, "description": p.description})
            continue
        value, unc, shown = _quantity(p, raw)
        if p.positive and value <= 0.0:
            raise ValueError(f"Input {p.name!r} must be positive, got {shown}.")
        values[p.name] = value
        if unc:
            uncertainties[p.name] = unc
        table.append({
            "name": p.name, "value": value, "unit": p.unit, "source": source, "given_as": shown if source == "given" else None,
            "uncertainty": unc, "description": p.description,
        })
    if missing:
        hint = "" if material else " (some can come from a material, e.g. material='s355')"
        raise ValueError(f"The {calc.id} calculator needs input(s) {', '.join(missing)}{hint}.")
    material_info = None
    if mat_props is not None:
        material_info = {"id": mat_id, "name": mat_props["name"], "source": mat_props["source"], "note": MATERIALS_NOTE}
    return values, uncertainties, table, material_info


# -- Uncertainty -------------------------------------------------------------------------------------------------


def _propagate(calc: Calculator, values: dict[str, Any], uncertainties: dict[str, float], base: Outcome) -> dict[str, Any]:
    """First-order GUM for every result: u_y^2 = sum (dy/dx_i u_i)^2, the derivatives by central differences."""
    out: dict[str, Any] = {}
    nominal = {r.name: r.value for r in base.results}
    sensitivities: dict[str, dict[str, float]] = {name: {} for name in nominal}
    for var, u in uncertainties.items():
        x = values[var]
        step = max(abs(x) * 1e-6, u * 1e-3)
        shifted = []
        for sign in (1.0, -1.0):
            trial = dict(values)
            trial[var] = x + sign * step
            try:
                shifted.append({r.name: r.value for r in calc.compute(trial).results})
            except (ValueError, ZeroDivisionError, ArithmeticError):
                shifted.append({})
        for name in nominal:
            hi, lo = shifted[0].get(name), shifted[1].get(name)
            if hi is not None and lo is not None:
                sensitivities[name][var] = (hi - lo) / (2.0 * step)
    for r in base.results:
        terms = {v: (sensitivities[r.name].get(v, 0.0) * u) ** 2 for v, u in uncertainties.items()}
        variance = sum(terms.values())
        std = math.sqrt(variance)
        if std == 0.0:
            continue
        out[r.name] = {
            "standard_uncertainty": std,
            "expanded_uncertainty": 2.0 * std,
            "coverage_factor": 2.0,
            "formatted": format_uncertainty_result(r.value, std, r.unit if r.unit != "1" else ""),
            "budget": [
                {"variable": v, "sensitivity": sensitivities[r.name].get(v, 0.0), "std_uncertainty": uncertainties[v],
                 "percentage": 100.0 * t / variance}
                for v, t in sorted(terms.items(), key=lambda kv: -kv[1])
            ],
        }
    return out


# -- Running -----------------------------------------------------------------------------------------------------


def _display(result: Result) -> dict[str, Any]:
    out: dict[str, Any] = {"name": result.name, "label": result.label, "value": result.value, "unit": result.unit}
    if result.display_unit and result.display_unit != result.unit:
        ureg = get_unit_registry()
        out["display_value"] = float(ureg.Quantity(result.value, result.unit).to(result.display_unit).magnitude)
        out["display_unit"] = result.display_unit
    return out


def run(calc: Calculator, inputs: dict[str, Any] | None, material: str | None = None) -> dict[str, Any]:
    values, uncertainties, table, material_info = _resolve_inputs(calc, dict(inputs or {}), material)
    outcome = calc.compute(dict(values))
    for r in outcome.results:
        if not math.isfinite(r.value):
            raise ValueError(f"The {calc.id} calculation gave a non-finite {r.name}; check the inputs.")
    results = [_display(r) for r in outcome.results]
    if uncertainties:
        propagated = _propagate(calc, values, uncertainties, outcome)
        for row in results:
            if row["name"] in propagated:
                row["uncertainty"] = propagated[row["name"]]
                if "display_unit" in row and row["value"]:
                    # The display unit is a linear rescaling (MPa, mm, kN...), so the uncertainty scales the same way.
                    scale = row["display_value"] / row["value"]
                    row["uncertainty"]["formatted"] = format_uncertainty_result(
                        row["display_value"], row["uncertainty"]["standard_uncertainty"] * scale, row["display_unit"]
                    )
        outcome.notes.append(
            "Uncertainties are propagated to first order (GUM, sensitivity coefficients by central differences) with "
            "the inputs taken as independent; U is the expanded uncertainty with k = 2."
        )
    governing = max((c for c in outcome.checks if c.utilisation is not None), key=lambda c: c.utilisation or 0.0, default=None)
    utilisation = None
    if governing is not None:
        utilisation = {
            "value": governing.utilisation,
            "governing": governing.name,
            "ok": all(c.ok for c in outcome.checks),
            "detail": governing.detail,
        }
    warnings = list(outcome.warnings)
    for v in outcome.validity:
        if not v.ok:
            warnings.append(f"Outside the method's validity: {v.detail}")
    for c in outcome.checks:
        if not c.ok:
            warnings.append(f"Check failed - {c.name}: {c.detail}")
    if material_info and "material" in {t["source"].split(" ")[0] for t in table}:
        warnings.append(MATERIALS_NOTE)
    return {
        "status": "ok",
        "calculator": calc.id,
        "title": calc.title,
        "reference": calc.reference.to_dict(),
        "material": material_info,
        "inputs": table,
        "results": results,
        "utilisation": utilisation,
        "checks": [c.__dict__ for c in outcome.checks],
        "validity": [c.__dict__ for c in outcome.validity],
        "formulas": outcome.formulas,
        "assumptions": list(calc.assumptions),
        "warnings": warnings,
        "notes": outcome.notes,
    }


__all__ = ["Calculator", "Check", "Outcome", "Param", "Reference", "Result", "run", "to_si"]
