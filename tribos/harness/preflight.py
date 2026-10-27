"""Pre-flight Dimensional Homogeneity Gate for Tribos Harness.

Closes:
- F-06 / P0.6 / P3.2: Wires physis_units directly into solver tool dispatch
- Enforces fail-closed dimensional analysis before invoking numerical or FEA solvers
"""

from __future__ import annotations

import logging
from typing import Any

from ..physis.units import check_dimensional_homogeneity

logger = logging.getLogger(__name__)


class PreflightError(ValueError):
    """Raised when pre-flight validation fails before tool dispatch."""

    pass


class PreflightGate:
    """Pre-flight inspection gate for tool execution arguments."""

    @staticmethod
    def verify_equation_units(equation: str) -> dict[str, Any]:
        """Verify dimensional homogeneity for an equation 'lhs = rhs'.

        Fail-closed: if the dimensions do not match, returns homogeneous=False with dimensional details.
        """
        try:
            res = check_dimensional_homogeneity(equation)
            is_homo = bool(res.get("equation_homogeneous", res.get("compatible", False)))
            return {
                **res,
                "homogeneous": is_homo,
            }
        except Exception as exc:
            logger.warning("Pre-flight unit check failed on equation '%s': %s", equation, exc)
            return {
                "homogeneous": False,
                "error": str(exc),
                "equation": equation,
            }

    @classmethod
    def inspect_tool_call(cls, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Inspect tool arguments before execution.

        If an equation or formula is provided to a numerical/analytical solver,
        verifies that it is dimensionally homogeneous before solver execution.
        """
        eq = arguments.get("equation") or arguments.get("formula")
        if (
            eq
            and isinstance(eq, str)
            and "=" in eq
            and tool_name in ("dynamis_solve_ode", "dynamis_eval", "engcalc")
        ):
            res = cls.verify_equation_units(eq)
            if not res.get("homogeneous", True):
                reason = f"Dimensional mismatch in tool '{tool_name}' argument '{eq}': lhs={res.get('lhs_dim')} vs rhs={res.get('rhs_dim')}"
                return False, reason

        return True, "Pre-flight checks passed"
