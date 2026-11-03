"""The keys the classic pipeline stores its tool results under (``run.tool_results``), in one place.

The gather stage writes them; the evidence block, the task status, the activity timeline and the artifacts read
them. Legacy alias keys (``lithoscribe``, ``vivarix``, ``vivarix_scan``) point at the same ToolResult objects as
their canonical keys so older readers keep working; anything that counts sources or results goes through
:func:`distinct_results`, so one run is never counted twice (LOG-29).
"""

from __future__ import annotations

from typing import Any

ARCHIVON = "archivon"
WEBSURFER = "websurfer"
PHYSIS = "physis"
CALCULA = "calcula"
AXIOM = "axiom"
DYNAMIS = "dynamis"  # time course (dynamis_simulate_ode)
DYNAMIS_SCAN = "dynamis_scan"  # parameter scan (dynamis_parameter_scan)
DYNAMIS_EQUILIBRIUM = "dynamis_equilibrium"  # fixed point and stability (dynamis_equilibrium)
DYNAMIS_PDE = "dynamis_pde"  # a solved partial differential equation (dynamis_solve_pde)
DYNAMIS_MONTE_CARLO = "dynamis_monte_carlo"  # reproducible sampled quadrature
COMPUTED_RESULTS = "computed_results"  # values computed by code for the question (tribos.writer.facts)
CODEACT = "codeact"  # the model's Python notebook for the question (tribos.agentic.codeact)

# Legacy key -> the canonical key whose result it repeats.
ALIAS_KEYS: dict[str, str] = {
    "lithoscribe": ARCHIVON,
    "vivarix": DYNAMIS,
    "vivarix_scan": DYNAMIS_SCAN,
}

# The STEM computation results the evidence block renders, in prompt order.
STEM_RESULT_KEYS = (COMPUTED_RESULTS, DYNAMIS, DYNAMIS_EQUILIBRIUM, DYNAMIS_SCAN, DYNAMIS_PDE, DYNAMIS_MONTE_CARLO, AXIOM, PHYSIS, CALCULA,
                    CODEACT)


def is_alias_duplicate(key: str, tool_results: dict[str, Any]) -> bool:
    """True when `key` is a legacy alias holding the very same result as its canonical key."""
    canonical = ALIAS_KEYS.get(key)
    return (
        canonical is not None and key in tool_results and canonical in tool_results
        and tool_results[key] is tool_results[canonical]
    )


def distinct_results(tool_results: dict[str, Any]) -> dict[str, Any]:
    """tool_results without alias keys that repeat a canonical key's result (counting, consolidation)."""
    return {k: v for k, v in tool_results.items() if not is_alias_duplicate(k, tool_results)}


__all__ = [
    "ALIAS_KEYS",
    "ARCHIVON",
    "AXIOM",
    "CALCULA",
    "DYNAMIS",
    "COMPUTED_RESULTS",
    "DYNAMIS_EQUILIBRIUM",
    "DYNAMIS_PDE",
    "DYNAMIS_MONTE_CARLO",
    "DYNAMIS_SCAN",
    "PHYSIS",
    "STEM_RESULT_KEYS",
    "WEBSURFER",
    "distinct_results",
    "is_alias_duplicate",
]
