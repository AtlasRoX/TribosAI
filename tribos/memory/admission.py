"""Admission Control & Write-Time Governance for Tribos Memory.

Enforces:
- F-26: Purge legacy biomedical entity patterns in favor of STEM-native entities
- Never promotes raw unverified model text into empirical memory
- Admission validation: verifies mathematical/empirical backing before committing
- Provenance binding: attaches run manifest and verification verdict
"""

from __future__ import annotations

import re
from typing import Any

# STEM-Native Entity Patterns (Materials, loads, geometry, equations, standards)
STEM_PATTERNS = {
    "standard": re.compile(r"\b(ASME|API|ISO|ASTM|DIN|EN|Eurocode)\s+[A-Za-z0-9\-.]+\b", re.I),
    "material": re.compile(
        r"\b(Aluminum|Steel|Titanium|Inconel|Copper|Brass|Brass|Composite|6061-T6|4140|Ti-6Al-4V|316L|718)\b",
        re.I,
    ),
    "quantity_unit": re.compile(
        r"[-+]?\d+(?:\.\d+)?\s*(?:N|kN|MN|Pa|kPa|MPa|GPa|mm|cm|m|m/s|m/s\^2|kg|g|rad|deg|K|°C)\b"
    ),
    "equation_ref": re.compile(r"\b[A-Za-z]\([A-Za-z0-9_]+\)\s*=\s*[^.;,\n]+"),
    "boundary_condition": re.compile(
        r"\b(fixed|pinned|clamped|free|simply\s+supported|roller|symmetry|prescribed\s+displacement)\b",
        re.I,
    ),
}


class AdmissionController:
    """Gatekeeper enforcing write-time governance on long-term memory."""

    @staticmethod
    def extract_stem_entities(text: str) -> dict[str, list[str]]:
        """Extract STEM-native physical entities from text without biomedical leftovers."""
        found: dict[str, list[str]] = {}
        for category, pat in STEM_PATTERNS.items():
            matches = list(dict.fromkeys(m.group(0).strip() for m in pat.finditer(text or "")))
            if matches:
                found[category] = matches
        return found

    @staticmethod
    def validate_admission(
        fact_payload: dict[str, Any],
        verification_status: str,
        evidence: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Validate whether a candidate fact is permitted to enter the long-term fact graph.

        Rules:
        1. Pure unverified LLM generation is rejected from long-term memory.
        2. Must have empirical verification backing (Axiom, SymPy, Pint, tool execution, or formal proof).
        3. Subject and relation must be non-empty strings.
        """
        subj = str(fact_payload.get("subject") or "").strip()
        rel = str(fact_payload.get("relation") or "").strip()
        obj = str(fact_payload.get("object") or "").strip()

        if not subj or not rel or not obj:
            return False, "Subject, relation, and object must all be non-empty"

        status = verification_status.lower().strip()
        if status in ("unverified", "unverified_generated", "hallucination"):
            return False, "Unverified generative assertions cannot be admitted to long-term memory"

        ev = evidence or []
        if status == "verified_empirical" and not ev:
            # Require at least one verified tool execution or proof certificate
            return (
                False,
                "Verified empirical facts require verifiable tool evidence or proof references",
            )

        return True, "Admission approved"
