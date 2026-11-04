"""Engineering Standards & Code Compliance Engine."""

from typing import Any

from ...memory.semantic import STANDARDS_CATALOG, StandardClause


def get_standard_clause(standard_id: str) -> StandardClause | None:
    return STANDARDS_CATALOG.get(standard_id)


def check_asme_compliance(
    params: dict[str, float], clause_id: str = "ASME_VIII_1_UG27_CYL"
) -> dict[str, Any]:
    clause = get_standard_clause(clause_id)
    if not clause:
        return {"compliant": None, "status": "not_evaluated", "error": f"Unknown standard clause '{clause_id}'",
                "known_clauses": sorted(STANDARDS_CATALOG)}
    return clause.evaluate_compliance(params)


__all__ = ["StandardClause", "check_asme_compliance", "get_standard_clause"]
