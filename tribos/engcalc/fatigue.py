"""Fatigue: the Basquin S-N line, mean-stress criteria (Goodman, Gerber, Soderberg) and Miner's rule.

Stresses are in Pa. The S-N line runs from f S_ut at 10^3 cycles to S_e at 10^6 cycles (Shigley's construction), so
its life estimates hold between those two points.
"""

from __future__ import annotations

import math
from typing import Any

from .core import Calculator, Check, Outcome, Param, Reference, Result, to_si

CRITERIA = ("goodman", "gerber", "soderberg")


def _equivalent_reversed(sa: float, sm: float, sut: float, sy: float, criterion: str) -> float:
    """The completely reversed stress amplitude equivalent to (sa, sm) under the mean-stress criterion."""
    if sm <= 0.0:
        return sa  # a compressive mean stress is conservatively ignored
    if criterion == "gerber":
        ratio = 1.0 - (sm / sut) ** 2
    elif criterion == "soderberg":
        ratio = 1.0 - sm / sy
    else:
        ratio = 1.0 - sm / sut
    if ratio <= 0.0:
        raise ValueError(f"The mean stress {sm / 1e6:.4g} MPa reaches the {criterion} limit; the part fails statically.")
    return sa / ratio


def _safety_factor(sa: float, sm: float, se: float, sut: float, sy: float, criterion: str) -> float:
    """The infinite-life safety factor on the load line through (sm, sa) (Shigley Table 6-6 forms)."""
    sm = max(sm, 0.0)
    if criterion == "gerber":
        if sm == 0.0:
            return se / sa
        return 0.5 * (sut / sm) ** 2 * (sa / se) * (-1.0 + math.sqrt(1.0 + (2.0 * sm * se / (sut * sa)) ** 2))
    if criterion == "soderberg":
        return 1.0 / (sa / se + sm / sy)
    return 1.0 / (sa / se + sm / sut)


def fatigue(v: dict[str, Any]) -> Outcome:
    sut, sy = v["ultimate_strength"], v["yield_strength"]
    f, criterion = v["fatigue_strength_fraction"], v["criterion"]
    out = Outcome(results=[])
    se = v.get("endurance_limit")
    if se is None:
        family = v.get("material_family")
        if family not in (None, "steel", "stainless"):
            raise ValueError(f"A {family} alloy has no endurance limit: give endurance_limit as its fatigue strength at a "
                             "stated life (e.g. 5e8 cycles for aluminium).")
        se_prime = 0.5 * sut if sut <= 1400e6 else 700e6
        se = v["marin_factor"] * se_prime
        out.notes.append(f"S_e' = {'0.5 S_ut' if sut <= 1400e6 else '700 MPa'} (steels), times the Marin factor "
                         f"{v['marin_factor']:g}.")
        if v["marin_factor"] == 1.0:
            out.warnings.append("The endurance limit is the polished rotating-beam specimen value (Marin factor 1): "
                                "surface, size, loading, temperature and reliability factors usually lower it a lot.")
        if family is None:
            out.warnings.append("S_e' = 0.5 S_ut holds for steels only; give endurance_limit for other materials.")
    sa, sm = v["stress_amplitude"], v["mean_stress"] or 0.0
    a = (f * sut) ** 2 / se
    b = -math.log10(f * sut / se) / 3.0
    out.formulas += [
        "a = (f S_ut)^2 / S_e, b = -log10(f S_ut / S_e) / 3, S_f = a N^b (10^3 <= N <= 10^6)",
        {"goodman": "Goodman: 1/n = sigma_a / S_e + sigma_m / S_ut",
         "gerber": "Gerber: n = (S_ut/sigma_m)^2 sigma_a/(2 S_e) [-1 + sqrt(1 + (2 sigma_m S_e / (S_ut sigma_a))^2)]",
         "soderberg": "Soderberg: 1/n = sigma_a / S_e + sigma_m / S_y"}[criterion],
        "Langer first-cycle yield: n_y = S_y / (sigma_a + |sigma_m|)",
    ]
    out.results += [
        Result("endurance_limit", "Endurance limit S_e", se, "Pa", "MPa"),
        Result("basquin_a", "S-N coefficient a", a, "Pa", "MPa"),
        Result("basquin_b", "S-N exponent b", b, "1"),
    ]
    n_req = v["required_safety_factor"]
    sar = _equivalent_reversed(sa, sm, sut, sy, criterion)
    if sar < se:
        n_fat = _safety_factor(sa, sm, se, sut, sy, criterion)
        out.results.append(Result("fatigue_safety_factor", f"Infinite-life safety factor ({criterion})", n_fat, "1"))
        out.checks.append(Check("fatigue (infinite life)", n_fat >= n_req, f"n = {n_fat:.3g} against {n_req:.3g}",
                                utilisation=n_req / n_fat))
    else:
        life = (sar / a) ** (1.0 / b)
        out.results.append(Result("cycles_to_failure", "Cycles to failure", life, "1"))
        out.results.append(Result("equivalent_reversed_stress", "Equivalent reversed stress", sar, "Pa", "MPa"))
        out.formulas.append("N = (sigma_rev / a)^(1/b), sigma_rev = sigma_a / (1 - sigma_m / S_ut) (Goodman form)")
        out.validity.append(Check("S-N range", 1e3 <= life <= 1e6, f"N = {life:.3g}; the line holds for 10^3-10^6 cycles"))
        target = v.get("design_cycles")
        if target is not None:
            out.checks.append(Check("finite life", life >= target, f"N = {life:.3g} against {target:.3g} cycles",
                                    utilisation=target / life))
        else:
            out.warnings.append("The stress exceeds the endurance limit, so the life is finite; give design_cycles to check it.")
    n_y = sy / (sa + abs(sm))
    out.results.append(Result("yield_safety_factor", "First-cycle yield safety factor (Langer)", n_y, "1"))
    out.checks.append(Check("first-cycle yield", n_y >= 1.0, f"n_y = {n_y:.3g}", utilisation=1.0 / n_y))

    blocks = v.get("load_blocks") or []
    if blocks:
        damage = 0.0
        rows = []
        for k, block in enumerate(blocks):
            if not isinstance(block, dict) or "cycles" not in block or "stress_amplitude" not in block:
                raise ValueError("Each load block needs stress_amplitude and cycles (and optionally mean_stress).")
            ba = to_si(block["stress_amplitude"], "Pa", f"load_blocks[{k}].stress_amplitude")
            bm = to_si(block.get("mean_stress", 0.0), "Pa", f"load_blocks[{k}].mean_stress", positive=False)
            n = float(block["cycles"])
            bar = _equivalent_reversed(ba, bm, sut, sy, criterion)
            life = math.inf if bar < se else (bar / a) ** (1.0 / b)
            damage += 0.0 if math.isinf(life) else n / life
            rows.append((ba, n, life))
        out.results.append(Result("miner_damage", "Miner damage sum D", damage, "1"))
        out.formulas.append("Miner: D = sum n_i / N_i (blocks below S_e cause no damage); failure predicted at D = 1")
        out.checks.append(Check("cumulative damage (Miner)", damage < 1.0, f"D = {damage:.3g}", utilisation=damage))
        out.notes.append(f"{len(rows)} load block(s); {sum(1 for r in rows if math.isinf(r[2]))} below the endurance limit.")
        out.warnings.append("Miner's rule ignores load sequence; measured damage at failure scatters roughly 0.7-2.2.")
    return out


FATIGUE = Calculator(
    id="fatigue",
    title="Fatigue: S-N life, mean stress and Miner's rule",
    summary="Basquin S-N line, Goodman/Gerber/Soderberg mean-stress criteria and Miner cumulative damage.",
    reference=Reference("Shigley's Mechanical Engineering Design, 10th ed. (Budynas & Nisbett)",
                        "Sections 6-7, 6-8 (endurance limit, S-N line), 6-12 (fluctuating stress criteria) and 6-15 "
                        "(Miner's rule)"),
    params=(
        Param("stress_amplitude", "Pa", "Alternating stress amplitude sigma_a."),
        Param("mean_stress", "Pa", "Mean stress sigma_m.", default=0.0, positive=False),
        Param("ultimate_strength", "Pa", "Ultimate tensile strength S_ut.", material="ultimate_strength"),
        Param("yield_strength", "Pa", "Yield strength S_y.", material="yield_strength"),
        Param("endurance_limit", "Pa", "Endurance limit S_e (estimated as 0.5 S_ut for steels when omitted).",
              optional=True),
        Param("marin_factor", "1", "Product of the Marin factors k_a k_b k_c k_d k_e (for the estimated S_e).",
              default=1.0),
        Param("fatigue_strength_fraction", "1", "f: S-N strength at 10^3 cycles as a fraction of S_ut.", default=0.9),
        Param("criterion", "", "Mean-stress criterion.", default="goodman", choices=CRITERIA),
        Param("design_cycles", "1", "Required life in cycles (finite-life check).", optional=True),
        Param("load_blocks", "Pa", "Miner blocks: [{stress_amplitude, mean_stress?, cycles}].", optional=True),
        Param("material_family", "", "Material family (from the material).", material="family", optional=True,
              choices=("steel", "stainless", "aluminium", "titanium", "copper", "concrete", "polymer")),
        Param("required_safety_factor", "1", "Required fatigue safety factor.", default=1.5),
    ),
    compute=fatigue,
    assumptions=("Uniaxial, constant-amplitude stress at the critical point (blocks for Miner)", "Stresses include any "
                 "fatigue stress concentration K_f", "High-cycle fatigue: elastic nominal stresses"),
    keywords=("fatigue", "endurance", "s-n", "goodman", "gerber", "soderberg", "miner", "cycles", "alternating"),
)

CALCULATORS = (FATIGUE,)

__all__ = ["CALCULATORS", "FATIGUE"]
