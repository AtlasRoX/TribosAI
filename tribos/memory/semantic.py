"""Semantic & Procedural Memory: Tier 4 engineering knowledge, materials DB, and standards clauses.

Features:
- F-04: Temperature-dependent materials database (E(T), nu(T), rho, yield, ultimate, S-N fatigue curve)
- F-03: Machine-checkable engineering standards clauses (ASME Section VIII-1, API 650, Eurocodes)
- CODATA fundamental physical constants
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import scipy.constants as _sc

# Catalogue values are typical room-temperature handbook values, not certified design allowables.
REFERENCE_TEMP_RANGE_C = (15.0, 25.0)
MATERIAL_DATA_NOTE = (
    "Typical room-temperature values (15-25 C) for a common temper; not certified design allowables and not valid "
    "at other temperatures. Use the governing code's allowables or certified mill data for design."
)


@dataclass
class MaterialRecord:
    name: str
    category: str  # aluminum | steel | titanium | nickel_alloy | composite
    density_kg_m3: float
    poisson_ratio: float
    yield_strength_mpa: float
    ultimate_strength_mpa: float
    thermal_conductivity_w_mk: float
    thermal_expansion_1_k: float
    # Temperature-dependent modulus function: E(T_C) in GPa
    e_modulus_gpa_at_20c: float
    temp_coefficient_e: float = -0.0004  # fraction change per deg C
    # S-N curve: sigma_a = S_f_prime * (2N_f)^b (Basquin relation)
    fatigue_strength_coeff_mpa: float = 0.0
    fatigue_exponent: float = -0.085

    aliases: tuple[str, ...] = ()

    def at_reference_temperature(self, temp_celsius: float) -> bool:
        """The catalogue holds single-point room-temperature values only (REFERENCE_TEMP_RANGE_C)."""
        lo, hi = REFERENCE_TEMP_RANGE_C
        return math.isfinite(temp_celsius) and lo <= temp_celsius <= hi

    def e_at_temp(self, temp_celsius: float) -> float | None:
        """Young's modulus E in GPa, or None outside the room-temperature range the catalogue value applies to.

        No sourced elevated- or low-temperature data is held, so no derating curve is applied (an earlier generic
        linear derating was unsourced and grossly unconservative for precipitation-hardened alloys)."""
        return self.e_modulus_gpa_at_20c if self.at_reference_temperature(temp_celsius) else None

    def yield_at_temp(self, temp_celsius: float) -> float | None:
        """Yield strength in MPa, or None outside the room-temperature range (see e_at_temp)."""
        return self.yield_strength_mpa if self.at_reference_temperature(temp_celsius) else None

    def fatigue_life_cycles(self, stress_amplitude_mpa: float) -> float:
        """Estimate fatigue cycles N_f under cyclic stress amplitude using Basquin's equation."""
        if stress_amplitude_mpa <= 0:
            return float("inf")
        coeff = self.fatigue_strength_coeff_mpa or (self.ultimate_strength_mpa * 1.5)
        # sigma_a = coeff * (2*N_f)^b  =>  2*N_f = (sigma_a / coeff)^(1/b)
        ratio = stress_amplitude_mpa / coeff
        if ratio >= 1.0:
            return 1.0
        two_n = math.pow(ratio, 1.0 / self.fatigue_exponent)
        return two_n / 2.0


# Standard Curated Material Catalog
MATERIALS_CATALOG: dict[str, MaterialRecord] = {
    "al6061_t6": MaterialRecord(
        name="Aluminum 6061-T6",
        category="aluminum",
        density_kg_m3=2700.0,
        poisson_ratio=0.33,
        yield_strength_mpa=276.0,
        ultimate_strength_mpa=310.0,
        thermal_conductivity_w_mk=167.0,
        thermal_expansion_1_k=23.2e-6,
        e_modulus_gpa_at_20c=68.9,
        temp_coefficient_e=-0.0005,
        fatigue_strength_coeff_mpa=450.0,
        fatigue_exponent=-0.10,
        aliases=("6061-t6", "aluminium 6061-t6", "al 6061-t6", "aa6061-t6"),
    ),
    "steel_4140": MaterialRecord(
        name="AISI 4140 Alloy Steel (Quenched & Tempered)",
        category="steel",
        density_kg_m3=7850.0,
        poisson_ratio=0.29,
        yield_strength_mpa=655.0,
        ultimate_strength_mpa=850.0,
        thermal_conductivity_w_mk=42.6,
        thermal_expansion_1_k=12.2e-6,
        e_modulus_gpa_at_20c=205.0,
        temp_coefficient_e=-0.0003,
        fatigue_strength_coeff_mpa=1250.0,
        fatigue_exponent=-0.08,
        aliases=("4140", "aisi 4140", "4140 q&t"),
    ),
    "ti_6al_4v": MaterialRecord(
        name="Titanium Grade 5 (Ti-6Al-4V)",
        category="titanium",
        density_kg_m3=4430.0,
        poisson_ratio=0.34,
        yield_strength_mpa=880.0,
        ultimate_strength_mpa=950.0,
        thermal_conductivity_w_mk=6.7,
        thermal_expansion_1_k=8.6e-6,
        e_modulus_gpa_at_20c=113.8,
        temp_coefficient_e=-0.0004,
        fatigue_strength_coeff_mpa=1400.0,
        fatigue_exponent=-0.09,
        aliases=("ti-6al-4v", "ti64", "titanium grade 5"),
    ),
    "ss316l": MaterialRecord(
        name="Stainless Steel 316L",
        category="steel",
        density_kg_m3=8000.0,
        poisson_ratio=0.30,
        yield_strength_mpa=290.0,
        ultimate_strength_mpa=580.0,
        thermal_conductivity_w_mk=16.3,
        thermal_expansion_1_k=16.0e-6,
        e_modulus_gpa_at_20c=193.0,
        temp_coefficient_e=-0.00035,
        fatigue_strength_coeff_mpa=890.0,
        fatigue_exponent=-0.085,
        aliases=("316l", "ss 316l", "stainless steel 316l"),
    ),
    "inconel_718": MaterialRecord(
        name="Inconel 718 Nickel Superalloy",
        category="nickel_alloy",
        density_kg_m3=8190.0,
        poisson_ratio=0.29,
        yield_strength_mpa=1100.0,
        ultimate_strength_mpa=1375.0,
        thermal_conductivity_w_mk=11.4,
        thermal_expansion_1_k=13.0e-6,
        e_modulus_gpa_at_20c=200.0,
        temp_coefficient_e=-0.00025,
        fatigue_strength_coeff_mpa=1900.0,
        fatigue_exponent=-0.075,
        aliases=("inconel 718", "in718", "alloy 718"),
    ),
}


@dataclass
class StandardClause:
    standard_id: str  # e.g. "ASME_VIII_1_UG27"
    title: str
    clause_ref: str
    description: str
    required_inputs: list[str]
    formula_latex: str

    def evaluate_compliance(self, params: dict[str, float]) -> dict[str, Any]:
        """Evaluate a UG-27 internal-pressure thickness check (inside radius R, Section VIII Div 1).

        `compliant` is True or False only when the clause was actually evaluated within its applicability limits;
        it is None (with `status` "not_evaluated" or "outside_applicability") otherwise, so an unimplemented clause
        or an invalid input can never read as a pass. `corrosion_allowance_mm`, when given, is subtracted from the
        actual wall before the comparison.
        """
        evaluator = _UG27_EVALUATORS.get(self.standard_id)
        if evaluator is None:
            return _not_evaluated(self.clause_ref, f"No evaluator is implemented for clause '{self.standard_id}'.")
        problem = _ug27_inputs(params)
        if isinstance(problem, str):
            return _not_evaluated(self.clause_ref, problem)
        return evaluator(self.clause_ref, *problem)


def _not_evaluated(clause: str, reason: str, status: str = "not_evaluated") -> dict[str, Any]:
    return {"compliant": None, "status": status, "clause": clause, "reason": reason, "required_thickness_mm": None}


def _ug27_inputs(params: dict[str, float]) -> tuple[float, float, float, float, float] | str:
    """(P, R, S, E, t_net) or the reason the inputs cannot be evaluated."""
    try:
        p = float(params["pressure_mpa"])
        r = float(params["radius_mm"])
        s = float(params["allowable_stress_mpa"])
        e = float(params.get("joint_efficiency", 1.0))
        t = float(params["wall_thickness_mm"]) - float(params.get("corrosion_allowance_mm") or 0.0)
    except (KeyError, TypeError, ValueError) as exc:
        return f"Missing or non-numeric input: {exc}"
    if not all(math.isfinite(v) for v in (p, r, s, e, t)):
        return "Inputs must be finite numbers."
    if p <= 0 or r <= 0 or s <= 0:
        return "pressure_mpa, radius_mm and allowable_stress_mpa must be positive (UG-27 covers internal pressure)."
    if not 0 < e <= 1:
        return "joint_efficiency must be in (0, 1]."
    if t <= 0:
        return "The wall thickness (net of corrosion allowance) must be positive."
    return p, r, s, e, t


def _ug27_result(clause: str, t_req: float, t: float, checks: list[str]) -> dict[str, Any]:
    ok = t >= t_req
    return {
        "compliant": ok,
        "status": "evaluated",
        "required_thickness_mm": round(t_req, 3),
        "actual_thickness_mm": t,
        "margin_mm": round(t - t_req, 3),
        "clause": clause,
        "checks": checks,
        "reason": f"Thickness satisfies {clause}" if ok else f"Thickness {t} mm below required {round(t_req, 3)} mm",
    }


def _ug27_cylinder(clause: str, p: float, r: float, s: float, e: float, t: float) -> dict[str, Any]:
    """UG-27(c)(1) circumferential stress, t = PR/(SE - 0.6P), valid for t <= R/2 and P <= 0.385 SE; and
    UG-27(c)(2) longitudinal stress, t = PR/(2SE + 0.4P), valid for t <= R/2 and P <= 1.25 SE. The larger governs."""
    if p > 0.385 * s * e:
        return _not_evaluated(clause, f"P = {p} MPa exceeds 0.385 S E = {0.385 * s * e:.4g} MPa: UG-27(c)(1) does "
                              "not apply; use Mandatory Appendix 1-2.", "outside_applicability")
    t_circ = p * r / (s * e - 0.6 * p)
    t_long = p * r / (2.0 * s * e + 0.4 * p)
    t_req = max(t_circ, t_long)
    if t_req > r / 2.0 or t > r / 2.0:
        return _not_evaluated(clause, "Thick shell (t > R/2): UG-27(c) does not apply; use Mandatory Appendix 1-2.",
                              "outside_applicability")
    return _ug27_result(clause, t_req, t, [f"circumferential (c)(1): t = {t_circ:.4g} mm",
                                          f"longitudinal (c)(2): t = {t_long:.4g} mm"])


def _ug27_sphere(clause: str, p: float, r: float, s: float, e: float, t: float) -> dict[str, Any]:
    """UG-27(d): t = PR/(2SE - 0.2P), valid for t <= 0.356 R and P <= 0.665 SE."""
    if p > 0.665 * s * e:
        return _not_evaluated(clause, f"P = {p} MPa exceeds 0.665 S E = {0.665 * s * e:.4g} MPa: UG-27(d) does not "
                              "apply; use Mandatory Appendix 1-3.", "outside_applicability")
    t_req = p * r / (2.0 * s * e - 0.2 * p)
    if t_req > 0.356 * r or t > 0.356 * r:
        return _not_evaluated(clause, "Thick sphere (t > 0.356 R): UG-27(d) does not apply; use Mandatory Appendix "
                              "1-3.", "outside_applicability")
    return _ug27_result(clause, t_req, t, [f"sphere (d): t = {t_req:.4g} mm"])


_UG27_EVALUATORS = {"ASME_VIII_1_UG27_CYL": _ug27_cylinder, "ASME_VIII_1_UG27_SPH": _ug27_sphere}


STANDARDS_CATALOG: dict[str, StandardClause] = {
    "ASME_VIII_1_UG27_CYL": StandardClause(
        standard_id="ASME_VIII_1_UG27_CYL",
        title="ASME Section VIII Div 1 UG-27(c) Cylindrical Shells Under Internal Pressure",
        clause_ref="ASME BPVC VIII-1 UG-27(c)",
        description="Minimum required thickness of cylindrical shells under internal design pressure.",
        required_inputs=[
            "pressure_mpa",
            "radius_mm",
            "allowable_stress_mpa",
            "joint_efficiency",
            "wall_thickness_mm",
        ],
        formula_latex=r"t = \max\left(\frac{P R}{S E - 0.6 P}, \frac{P R}{2 S E + 0.4 P}\right)",
    ),
    "ASME_VIII_1_UG27_SPH": StandardClause(
        standard_id="ASME_VIII_1_UG27_SPH",
        title="ASME Section VIII Div 1 UG-27(d) Spherical Shells Under Internal Pressure",
        clause_ref="ASME BPVC VIII-1 UG-27(d)",
        description="Minimum required thickness of spherical shells under internal design pressure.",
        required_inputs=[
            "pressure_mpa",
            "radius_mm",
            "allowable_stress_mpa",
            "joint_efficiency",
            "wall_thickness_mm",
        ],
        formula_latex=r"t = \frac{P \cdot R}{2 S \cdot E - 0.2 P}",
    ),
}

# CODATA fundamental physical constants, read from scipy.constants (the same source as tribos.physis) so the two
# never diverge; standard gravity is a defined conventional value.
CODATA_CONSTANTS: dict[str, tuple[float, str]] = {
    "speed_of_light": (_sc.c, "m/s"),
    "planck_constant": (_sc.h, "J*s"),
    "gravitational_constant": (_sc.G, "m^3/(kg*s^2)"),
    "standard_gravity": (_sc.g, "m/s^2"),
    "boltzmann_constant": (_sc.k, "J/K"),
    "elementary_charge": (_sc.e, "C"),
    "avogadro_constant": (_sc.N_A, "1/mol"),
    "gas_constant": (_sc.R, "J/(mol*K)"),
}


def _norm_material(text: str) -> str:
    return " ".join(text.strip().lower().replace("_", " ").replace("-", " ").split())


def find_material(name_or_key: str) -> MaterialRecord | None:
    """Exact catalogue key, full name or alias (case, '-', '_' and spacing ignored); never a substring guess."""
    q = _norm_material(name_or_key or "")
    if not q:
        return None
    for key, mat in MATERIALS_CATALOG.items():
        if q in {_norm_material(key), _norm_material(mat.name), *(_norm_material(a) for a in mat.aliases)}:
            return mat
    return None


class SemanticMemory:
    """Query interface for materials, standards, and physical constants."""

    def get_material(self, name_or_key: str) -> MaterialRecord | None:
        return find_material(name_or_key)

    def list_materials(self) -> list[str]:
        return [m.name for m in MATERIALS_CATALOG.values()]

    def get_standard_clause(self, standard_id: str) -> StandardClause | None:
        return STANDARDS_CATALOG.get(standard_id)

    def get_constant(self, name: str) -> tuple[float, str] | None:
        return CODATA_CONSTANTS.get(name.lower().strip().replace(" ", "_"))
