"""CAE / FEA result screening: five numerical gates on summary values a user or agent supplies.

1. Reaction-force equilibrium (|reaction| vs |applied| within 1 %)
2. Mesh convergence under h-refinement (peak-stress change <= 5 %)
3. Linear-elastic validity (peak von Mises <= yield strength)
4. Stress-singularity screen (gradient ratio <= 3; needs the ratio, never assumed)
5. Hand-calculation cross-check (FEA vs classical formula within 15 %)

A gate whose inputs cannot decide it (zero or negative reference values, a missing ratio) is "not evaluable", never a
pass, and the audit is verified only when every gate was evaluated and passed. These gates screen supplied summary
numbers; they are not a substitute for reviewing the model itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class CAEGateResult:
    gate_number: int
    gate_name: str
    passed: bool | None  # None: not evaluable from the inputs given
    observed_value: Any
    tolerance_threshold: Any
    detail: str


def _finite(*values: float | None) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


def _not_evaluable(number: int, name: str, threshold: str, detail: str) -> CAEGateResult:
    return CAEGateResult(number, name, None, None, threshold, f"Not evaluable: {detail}")


class CAEReviewer:
    """Screens FEA/CAE summary results against five numerical gates."""

    @staticmethod
    def verify_reaction_equilibrium(
        applied_force_n: float,
        reaction_force_n: float,
        tolerance_pct: float = 1.0,
    ) -> CAEGateResult:
        """Gate 1: the total reaction balances the total applied load."""
        name, threshold = "reaction_force_equilibrium", f"<= {tolerance_pct}%"
        if not _finite(applied_force_n, reaction_force_n) or applied_force_n == 0:
            return _not_evaluable(1, name, threshold, "the applied load must be a finite, nonzero force.")
        diff = abs(abs(applied_force_n) - abs(reaction_force_n))
        pct_diff = diff / abs(applied_force_n) * 100.0
        return CAEGateResult(
            gate_number=1,
            gate_name=name,
            passed=pct_diff <= tolerance_pct,
            observed_value=f"{pct_diff:.3g}% residual",
            tolerance_threshold=threshold,
            detail=f"Applied: {applied_force_n} N, Reaction: {reaction_force_n} N (residual {diff:.4g} N)",
        )

    @staticmethod
    def verify_mesh_convergence(
        coarse_stress_mpa: float,
        fine_stress_mpa: float,
        max_delta_pct: float = 5.0,
    ) -> CAEGateResult:
        """Gate 2: peak stress changes little between the coarse and the refined mesh."""
        name, threshold = "mesh_convergence_study", f"<= {max_delta_pct}%"
        if not _finite(coarse_stress_mpa, fine_stress_mpa) or coarse_stress_mpa <= 0 or fine_stress_mpa <= 0:
            return _not_evaluable(2, name, threshold, "both peak (von Mises) stresses must be positive and finite.")
        pct_delta = abs(fine_stress_mpa - coarse_stress_mpa) / fine_stress_mpa * 100.0
        return CAEGateResult(
            gate_number=2,
            gate_name=name,
            passed=pct_delta <= max_delta_pct,
            observed_value=f"{pct_delta:.3g}% delta",
            tolerance_threshold=threshold,
            detail=f"Coarse mesh: {coarse_stress_mpa} MPa -> Fine mesh: {fine_stress_mpa} MPa",
        )

    @staticmethod
    def verify_linear_elastic_validity(
        max_von_mises_mpa: float,
        yield_strength_mpa: float,
    ) -> CAEGateResult:
        """Gate 3: a linear-elastic result is only valid below yield."""
        name, threshold = "linear_elastic_validity", f"<= {yield_strength_mpa} MPa (Yield)"
        if not _finite(max_von_mises_mpa, yield_strength_mpa) or max_von_mises_mpa <= 0 or yield_strength_mpa <= 0:
            return _not_evaluable(3, name, threshold, "peak von Mises stress and yield strength must be positive.")
        passed = max_von_mises_mpa <= yield_strength_mpa
        return CAEGateResult(
            gate_number=3,
            gate_name=name,
            passed=passed,
            observed_value=f"Yield margin factor {yield_strength_mpa / max_von_mises_mpa:.3g} (Peak {max_von_mises_mpa} MPa)",
            tolerance_threshold=threshold,
            detail="Stress within elastic limit"
            if passed
            else f"Plastic yielding: peak {max_von_mises_mpa} MPa > yield {yield_strength_mpa} MPa",
        )

    @staticmethod
    def verify_singularity_screen(
        stress_gradient_ratio: float | None,
        max_ratio: float = 3.0,
    ) -> CAEGateResult:
        """Gate 4: screen for unphysical stress spikes at re-entrant corners or point loads."""
        name, threshold = "singularity_screening", f"<= {max_ratio}"
        if stress_gradient_ratio is None or not _finite(stress_gradient_ratio) or stress_gradient_ratio <= 0:
            return _not_evaluable(4, name, threshold, "no positive stress-gradient ratio was supplied.")
        passed = stress_gradient_ratio <= max_ratio
        return CAEGateResult(
            gate_number=4,
            gate_name=name,
            passed=passed,
            observed_value=f"Gradient ratio {stress_gradient_ratio:.3g}",
            tolerance_threshold=threshold,
            detail="Stress gradient smooth" if passed else "Possible mesh singularity at a sharp boundary",
        )

    @staticmethod
    def verify_hand_calc_cross_check(
        fea_stress_mpa: float,
        analytical_stress_mpa: float,
        max_deviation_pct: float = 15.0,
    ) -> CAEGateResult:
        """Gate 5: FEA agrees with a classical beam/shell formula."""
        name, threshold = "hand_calculation_cross_check", f"<= {max_deviation_pct}%"
        if not _finite(fea_stress_mpa, analytical_stress_mpa) or analytical_stress_mpa == 0:
            return _not_evaluable(5, name, threshold, "the analytical stress must be a finite, nonzero value.")
        pct_dev = abs(fea_stress_mpa - analytical_stress_mpa) / abs(analytical_stress_mpa) * 100.0
        return CAEGateResult(
            gate_number=5,
            gate_name=name,
            passed=pct_dev <= max_deviation_pct,
            observed_value=f"{pct_dev:.3g}% deviation",
            tolerance_threshold=threshold,
            detail=f"FEA: {fea_stress_mpa} MPa vs Classical Formula: {analytical_stress_mpa} MPa",
        )

    @classmethod
    def run_full_cae_audit(
        cls,
        applied_load_n: float,
        reaction_force_n: float,
        coarse_stress_mpa: float,
        fine_stress_mpa: float,
        yield_strength_mpa: float,
        analytical_stress_mpa: float,
        stress_gradient_ratio: float | None = None,
    ) -> dict[str, Any]:
        """Run the five gates; verified only when all five were evaluated and passed."""
        gates = [
            cls.verify_reaction_equilibrium(applied_load_n, reaction_force_n),
            cls.verify_mesh_convergence(coarse_stress_mpa, fine_stress_mpa),
            cls.verify_linear_elastic_validity(fine_stress_mpa, yield_strength_mpa),
            cls.verify_singularity_screen(stress_gradient_ratio),
            cls.verify_hand_calc_cross_check(fine_stress_mpa, analytical_stress_mpa),
        ]
        evaluated = [g for g in gates if g.passed is not None]
        passed = [g for g in evaluated if g.passed]
        failed = [g for g in evaluated if not g.passed]
        all_passed = len(passed) == len(gates)
        if all_passed:
            verdict = f"All {len(gates)} screening gates passed"
        elif failed:
            verdict = f"{len(failed)} of {len(gates)} gates failed: " + ", ".join(g.gate_name for g in failed)
        else:
            verdict = (f"Incomplete: {len(gates) - len(evaluated)} of {len(gates)} gates could not be evaluated from "
                       "the inputs given")
        return {
            "cae_verified": all_passed,
            "gates_passed": len(passed),
            "gates_failed": len(failed),
            "gates_not_evaluated": len(gates) - len(evaluated),
            "total_gates": len(gates),
            "gates": [
                {
                    "gate": g.gate_number,
                    "name": g.gate_name,
                    "passed": g.passed,
                    "observed": g.observed_value,
                    "tolerance": g.tolerance_threshold,
                    "detail": g.detail,
                }
                for g in gates
            ],
            "verdict": verdict,
            "scope": "Screens supplied summary values only; it does not inspect the FEA model.",
        }
