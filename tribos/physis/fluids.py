"""
Thermophysical properties of real fluids from reference equations of state (CoolProp).

CoolProp evaluates the reference Helmholtz-energy equation of state of each of its 130+ pure and pseudo-pure fluids
(water and steam, refrigerants, CO2, air, hydrocarbons, cryogens), the same formulations NIST REFPROP uses, with their
transport-property correlations. That replaces estimates from cubic or corresponding-states models: the Joule-Thomson
cooling of a refrigerant on throttling, a steam enthalpy, a saturation pressure or a compressibility factor comes from
the fluid's own published EOS, and the result names that reference.

Operations:
- state: properties at a state given by temperature and pressure (or saturation, with a vapour quality).
- throttle: an isenthalpic expansion (Joule-Thomson) from (T1, P1) to P2: T2, the temperature change and the mean
  Joule-Thomson coefficient.
- isentropic: a reversible adiabatic expansion or compression from (T1, P1) to P2: T2 and the enthalpy change.
- saturation: the saturation pressure at T (or temperature at P), the latent heat and both phases' densities.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

# Output name -> (CoolProp key, SI unit, description).
PROPERTIES: dict[str, tuple[str, str, str]] = {
    "density": ("Dmass", "kg/m^3", "mass density"),
    "molar_density": ("Dmolar", "mol/m^3", "molar density"),
    "molar_volume": ("Dmolar", "m^3/mol", "molar volume (1 / molar density)"),
    "cp": ("Cpmass", "J/(kg K)", "isobaric specific heat capacity"),
    "cp_molar": ("Cpmolar", "J/(mol K)", "isobaric molar heat capacity"),
    "cv": ("Cvmass", "J/(kg K)", "isochoric specific heat capacity"),
    "cv_molar": ("Cvmolar", "J/(mol K)", "isochoric molar heat capacity"),
    "enthalpy": ("Hmass", "J/kg", "specific enthalpy"),
    "enthalpy_molar": ("Hmolar", "J/mol", "molar enthalpy"),
    "entropy": ("Smass", "J/(kg K)", "specific entropy"),
    "entropy_molar": ("Smolar", "J/(mol K)", "molar entropy"),
    "internal_energy": ("Umass", "J/kg", "specific internal energy"),
    "compressibility_factor": ("Z", "1", "compressibility factor Z = pV/(nRT)"),
    "speed_of_sound": ("A", "m/s", "speed of sound"),
    "viscosity": ("V", "Pa s", "dynamic viscosity"),
    "thermal_conductivity": ("L", "W/(m K)", "thermal conductivity"),
    "joule_thomson": ("d(T)/d(P)|Hmass", "K/Pa", "Joule-Thomson coefficient (dT/dP at constant enthalpy)"),
    "isothermal_compressibility": ("isothermal_compressibility", "1/Pa", "isothermal compressibility"),
    "expansion_coefficient": ("isobaric_expansion_coefficient", "1/K", "isobaric expansion coefficient"),
    "molar_mass": ("M", "kg/mol", "molar mass"),
    "quality": ("Q", "1", "vapour quality (two-phase states only)"),
}
DEFAULT_OUTPUTS = ("density", "cp_molar", "cv_molar", "enthalpy_molar", "compressibility_factor", "joule_thomson")
OPERATIONS = ("state", "throttle", "isentropic", "saturation")

# Refrigerant designations in their usual spellings: "R-134a", "HFC-134a", "refrigerant 123", "HCFC 22".
_REFRIGERANT_RE = re.compile(r"^(?:r|refrigerant|hcfc|hfc|cfc|hfo|hc|fc)[\s\-_]*(\d{2,4}[a-z]{0,2}(?:\(e\))?)$", re.I)
_COMMON_NAMES = {
    "steam": "Water", "water": "Water", "ice": "Water", "air": "Air", "dryair": "Air",
    "carbondioxide": "CarbonDioxide", "co2": "CarbonDioxide", "nitrogen": "Nitrogen", "n2": "Nitrogen",
    "oxygen": "Oxygen", "o2": "Oxygen", "hydrogen": "Hydrogen", "h2": "Hydrogen", "helium": "Helium", "he": "Helium",
    "argon": "Argon", "ar": "Argon", "methane": "Methane", "naturalgas": "Methane", "ammonia": "Ammonia",
    "nh3": "Ammonia", "propane": "n-Propane", "butane": "n-Butane", "isobutane": "IsoButane",
    "carbonmonoxide": "CarbonMonoxide", "co": "CarbonMonoxide",
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@lru_cache(maxsize=1)
def _cp() -> Any:
    try:
        import CoolProp  # noqa: F401
        import CoolProp.CoolProp as CP
    except ImportError as exc:  # pragma: no cover - CoolProp is a pinned dependency
        raise RuntimeError("CoolProp is not installed: install the 'CoolProp' package to use fluid properties") from exc
    return CP


def coolprop_version() -> str:
    import CoolProp

    return str(getattr(CoolProp, "__version__", "unknown"))


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    CP = _cp()
    index: dict[str, str] = {}
    for fluid in CP.get_global_param_string("FluidsList").split(","):
        names = [fluid]
        for param in ("aliases", "CAS", "REFPROP_name"):
            try:
                names += [a for a in CP.get_fluid_param_string(fluid, param).split(",") if a.strip()]
            except Exception:  # noqa: BLE001 - not every fluid has every parameter
                continue
        for n in names:
            index.setdefault(_norm(n), fluid)
            index.setdefault(n.strip().lower(), fluid)
    return index


def resolve_fluid(name: str) -> str:
    """The CoolProp fluid for a name, formula, CAS number or refrigerant designation; ValueError when unknown."""
    raw = (name or "").strip()
    if not raw:
        raise ValueError("fluid: give a fluid name, formula, CAS number or refrigerant number (e.g. 'Water', 'R134a')")
    index = _alias_index()
    for key in (raw.lower(), _norm(raw)):
        if key in index:
            return index[key]
    m = _REFRIGERANT_RE.match(raw.replace(" ", "")) or _REFRIGERANT_RE.match(raw)
    if m:
        designation = "r" + m.group(1).lower()
        if _norm(designation) in index:
            return index[_norm(designation)]
    common = _COMMON_NAMES.get(_norm(raw))
    if common and _norm(common) in index:
        return index[_norm(common)]
    raise ValueError(f"fluid {raw!r} is not in CoolProp's catalogue; use its name, formula, CAS number or refrigerant "
                     "number (e.g. 'Water', 'CO2', 'R134a', 'R123')")


@lru_cache(maxsize=1)
def _ureg() -> Any:
    import pint

    return pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def to_si(value: Any, unit: str, what: str) -> float:
    """A temperature (K) or pressure (Pa) given as a number in SI or a string with its unit ("50 degC", "1.5 bar")."""
    if value is None or value == "":
        raise ValueError(f"{what} is required")
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip().replace("º", "°").replace("°C", " degC").replace("°F", " degF")
        if unit == "K":  # "50 C", "50 deg C" read as degrees Celsius
            text = re.sub(r"(?i)(?<=\d)\s*(?:deg\s*)?c\b", " degC", text)
        ureg = _ureg()
        try:
            q = ureg.Quantity(text)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{what}: cannot read {value!r} as a {unit} quantity") from exc
        out = float(q.magnitude) if q.dimensionless else float(q.to(unit).magnitude)
    if not math.isfinite(out):
        raise ValueError(f"{what} must be finite")
    if out <= 0:
        raise ValueError(f"{what} must be positive in {unit} (absolute), got {out:g}")
    return out


def _props(CP: Any, fluid: str, spec: tuple[str, float, str, float], outputs: list[str]) -> dict[str, Any]:
    k1, v1, k2, v2 = spec
    out: dict[str, Any] = {"phase": CP.PhaseSI(k1, v1, k2, v2, fluid)}
    for name in outputs:
        key, unit, desc = PROPERTIES[name]
        try:
            value = float(CP.PropsSI(key, k1, v1, k2, v2, fluid))
        except Exception as exc:  # noqa: BLE001 - a property undefined at this state (e.g. JT in two-phase)
            out[name] = {"value": None, "unit": unit, "description": desc, "error": str(exc)[:200]}
            continue
        if name == "molar_volume" and value:
            value = 1.0 / value
        entry: dict[str, Any] = {"value": value, "unit": unit, "description": desc}
        if name == "joule_thomson":
            entry["value_K_per_bar"] = value * 1e5
        if name == "quality" and not (0.0 <= value <= 1.0):
            entry = {"value": None, "unit": unit, "description": desc, "note": "single-phase state"}
        out[name] = entry
    return out


def fluid_properties(fluid: str, operation: str = "state", temperature: Any = None, pressure: Any = None,
                     final_pressure: Any = None, quality: float | None = None,
                     outputs: list[str] | None = None) -> dict[str, Any]:
    """Evaluate the reference EOS of a fluid (see the module docstring for the operations)."""
    CP = _cp()
    name = resolve_fluid(fluid)
    op = (operation or "state").strip().lower()
    if op not in OPERATIONS:
        raise ValueError(f"operation must be one of {', '.join(OPERATIONS)}")
    wanted = list(outputs or DEFAULT_OUTPUTS)
    unknown = [o for o in wanted if o not in PROPERTIES]
    if unknown:
        raise ValueError(f"unknown output(s) {unknown}; choose from {', '.join(PROPERTIES)}")
    data: dict[str, Any] = {
        "fluid": name, "operation": op,
        "method": f"CoolProp {coolprop_version()} reference equation of state",
        "eos_reference": CP.get_fluid_param_string(name, "BibTeX-EOS"),
        "critical_point": {"T_K": CP.PropsSI("Tcrit", name), "P_Pa": CP.PropsSI("pcrit", name)},
    }
    if op == "saturation":
        if temperature not in (None, ""):
            t = to_si(temperature, "K", "temperature")
            spec_l, spec_v = ("T", t, "Q", 0.0), ("T", t, "Q", 1.0)
            data["saturation_pressure_Pa"] = float(CP.PropsSI("P", "T", t, "Q", 0, name))
            data["inputs"] = {"T_K": t}
        elif pressure not in (None, ""):
            p = to_si(pressure, "Pa", "pressure")
            spec_l, spec_v = ("P", p, "Q", 0.0), ("P", p, "Q", 1.0)
            data["saturation_temperature_K"] = float(CP.PropsSI("T", "P", p, "Q", 0, name))
            data["inputs"] = {"P_Pa": p}
        else:
            raise ValueError("saturation needs a temperature or a pressure")
        h_l = float(CP.PropsSI("Hmolar", *spec_l, name))
        h_v = float(CP.PropsSI("Hmolar", *spec_v, name))
        data["latent_heat_molar_J_per_mol"] = h_v - h_l
        data["latent_heat_J_per_kg"] = float(CP.PropsSI("Hmass", *spec_v, name) - CP.PropsSI("Hmass", *spec_l, name))
        data["liquid_density_kg_m3"] = float(CP.PropsSI("Dmass", *spec_l, name))
        data["vapour_density_kg_m3"] = float(CP.PropsSI("Dmass", *spec_v, name))
        return data

    t1 = to_si(temperature, "K", "temperature")
    if quality is not None:
        q = float(quality)
        if not 0.0 <= q <= 1.0:
            raise ValueError("quality must be between 0 and 1")
        spec = ("T", t1, "Q", q)
        data["inputs"] = {"T_K": t1, "quality": q}
    else:
        p1 = to_si(pressure, "Pa", "pressure")
        spec = ("T", t1, "P", p1)
        data["inputs"] = {"T_K": t1, "P_Pa": p1}
    data["state"] = _props(CP, name, spec, wanted)
    if op == "state":
        return data
    if quality is not None:
        raise ValueError(f"{op} starts from a temperature and a pressure, not a quality")
    p2 = to_si(final_pressure, "Pa", "final_pressure")
    p1 = data["inputs"]["P_Pa"]
    held = "Hmass" if op == "throttle" else "Smass"
    held_value = float(CP.PropsSI(held, "T", t1, "P", p1, name))
    t2 = float(CP.PropsSI("T", held, held_value, "P", p2, name))
    h1 = float(CP.PropsSI("Hmolar", "T", t1, "P", p1, name))
    h2 = float(CP.PropsSI("Hmolar", held, held_value, "P", p2, name))
    data["inputs"]["P2_Pa"] = p2
    process: dict[str, Any] = {
        "kind": "isenthalpic (Joule-Thomson) expansion" if op == "throttle" else "isentropic (reversible adiabatic)",
        "T1_K": t1, "T2_K": t2, "delta_T_K": t2 - t1, "P1_Pa": p1, "P2_Pa": p2,
        "final_phase": CP.PhaseSI(held, held_value, "P", p2, name),
    }
    if op == "throttle":
        process["mean_joule_thomson_K_per_bar"] = (t2 - t1) / ((p2 - p1) / 1e5) if p2 != p1 else None
        process["note"] = ("The temperature change is intensive: it does not depend on the amount of fluid. The "
                           "result integrates the real EOS along the isenthalp, not a constant coefficient.")
    else:
        process["delta_h_molar_J_per_mol"] = h2 - h1
        process["delta_h_J_per_kg"] = float(CP.PropsSI("Hmass", held, held_value, "P", p2, name)
                                            - CP.PropsSI("Hmass", "T", t1, "P", p1, name))
    data["process"] = process
    return data


__all__ = ["DEFAULT_OUTPUTS", "OPERATIONS", "PROPERTIES", "coolprop_version", "fluid_properties", "resolve_fluid", "to_si"]
