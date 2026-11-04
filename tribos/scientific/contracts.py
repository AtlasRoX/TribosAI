"""Typed specifications, scoped symbol environments, unit normalization, and requirement ledger.

Supports independent tasks with typed specifications, strict contracts, unit normalization with provenance,
symbol scope isolation, and a requirement ledger connecting tasks to results, checks, and delivered files.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from tribos.axiom.engine import safe_parse_expr
from tribos.physis.units import get_unit_registry


# ---------------------------------------------------------------------------------------------------------------------
# Unit Normalization with Provenance
# ---------------------------------------------------------------------------------------------------------------------

UNIT_CONVERSIONS = {
    # Length
    "mm": ("m", 1e-3),
    "cm": ("m", 1e-2),
    "m": ("m", 1.0),
    "km": ("m", 1e3),
    # Mass
    "g": ("kg", 1e-3),
    "mg": ("kg", 1e-6),
    "kg": ("kg", 1.0),
    # Time
    "ms": ("s", 1e-3),
    "s": ("s", 1.0),
    "sec": ("s", 1.0),
    "secs": ("s", 1.0),
    "seconds": ("s", 1.0),
    "second": ("s", 1.0),
    "min": ("s", 60.0),
    "minute": ("s", 60.0),
    "minutes": ("s", 60.0),
    "h": ("s", 3600.0),
    "hour": ("s", 3600.0),
    "hours": ("s", 3600.0),
    # Force
    "N": ("N", 1.0),
    "kN": ("N", 1e3),
    "MN": ("N", 1e6),
    # Pressure / Stress / Modulus
    "Pa": ("Pa", 1.0),
    "kPa": ("Pa", 1e3),
    "MPa": ("Pa", 1e6),
    "GPa": ("Pa", 1e9),
    # Electrical
    "V": ("V", 1.0),
    "mV": ("V", 1e-3),
    "kV": ("V", 1e3),
    "ohm": ("ohm", 1.0),
    "ohms": ("ohm", 1.0),
    "Ω": ("ohm", 1.0),
    "kohm": ("ohm", 1e3),
    "kΩ": ("ohm", 1e3),
    "Mohm": ("ohm", 1e6),
    "MΩ": ("ohm", 1e6),
    "F": ("F", 1.0),
    "mF": ("F", 1e-3),
    "uF": ("F", 1e-6),
    "μF": ("F", 1e-6),
    "µF": ("F", 1e-6),
    "nF": ("F", 1e-9),
    "pF": ("F", 1e-12),
}


def normalize_physical_quantity(raw_str: str, default_target: str = "") -> tuple[float, str, str]:
    """Normalize a physical quantity string like '2000 g' or '200 GPa' to base SI units with provenance.

    Returns:
        (normalized_value, unit, provenance_record)
    """
    s = raw_str.strip()
    m = re.match(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s*[×*]\s*10\s*\^\s*[+-]?\d+)?)\s*([A-Za-zΩμµ·\^/\-]+)?$", s)
    if not m:
        try:
            val = float(safe_parse_expr(s))
            return val, default_target, f"{s} -> {val} {default_target}".strip()
        except Exception:
            return 0.0, default_target, f"{s} (unparsed)"

    num_part = m[1].replace("×", "*")
    unit_part = (m[2] or default_target).strip()

    val = float(safe_parse_expr(num_part))
    if not unit_part:
        return val, "", f"{s} -> {val}"

    # Check direct conversion table
    if unit_part in UNIT_CONVERSIONS:
        target_unit, factor = UNIT_CONVERSIONS[unit_part]
        norm_val = val * factor
        provenance = f"{s} -> {norm_val:g} {target_unit}"
        return norm_val, target_unit, provenance

    # Fallback to pint registry
    try:
        ureg = get_unit_registry()
        clean_unit = unit_part.replace("Ω", "ohm").replace("μ", "u").replace("µ", "u").replace("·", "*")
        q = ureg.Quantity(val, clean_unit)
        base = q.to_base_units()
        norm_val = float(base.magnitude)
        target_unit = f"{base.units:~}"
        provenance = f"{s} -> {norm_val:g} {target_unit}"
        return norm_val, target_unit, provenance
    except Exception:
        return val, unit_part, f"{s} -> {val} {unit_part}"


# ---------------------------------------------------------------------------------------------------------------------
# Task Specification
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class TaskSpec:
    """Typed specification of an independent scientific or mathematical task.

    Ensures symbol isolation: variable names in scope do not collide across tasks.
    """
    task_id: str
    section_index: int
    title: str
    kind: str  # arithmetic, function_domain, rc_charge, beam, ode_rk4, heat_ftcs, monte_carlo, execution_audit
    equations: list[str] = field(default_factory=list)
    domains: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    original_inputs: dict[str, Any] = field(default_factory=dict)
    normalized_inputs: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    method: str | None = None
    precision: str = "float64"
    tolerances: dict[str, float] = field(default_factory=dict)
    random_generator: str | None = None
    random_seed: int | None = None
    requested_sections: list[str] = field(default_factory=list)
    requested_files: list[str] = field(default_factory=list)
    execution_restrictions: dict[str, Any] = field(default_factory=dict)
    required_evidence: str = "execution"  # exact, execution, sources, records

    # Scoped symbol namespace for this task
    scope: dict[str, Any] = field(default_factory=dict)

    def spec_hash(self) -> str:
        """Deterministic hash of this task's inputs, parameters, equations and method."""
        payload = {
            "task_id": self.task_id,
            "kind": self.kind,
            "equations": sorted(self.equations),
            "domains": self.domains,
            "normalized_inputs": {k: f"{v:.12g}" if isinstance(v, float) else str(v) for k, v in sorted(self.normalized_inputs.items())},
            "parameters": {k: f"{v:.12g}" if isinstance(v, float) else str(v) for k, v in sorted(self.parameters.items())},
            "method": self.method,
            "seed": self.random_seed,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------------------------
# Requirement Ledger
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class RequirementLedgerItem:
    """Tracking item for a single requested deliverable or section."""
    task_id: str
    section_index: int
    title: str
    kind: str
    status: str = "mentioned"  # mentioned, computed, checked, source_supported, delivered, complete
    result_id: str | None = None
    spec_hash: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    answer_location: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "section_index": self.section_index,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "result_id": self.result_id,
            "spec_hash": self.spec_hash,
            "checks": self.checks,
            "answer_location": self.answer_location,
            "files": self.files,
            "error": self.error,
            "provenance": self.provenance,
        }


@dataclass
class RequirementLedger:
    """One requirement ledger to connect requested work to actual results, checks, answer locations, and files."""
    items: list[RequirementLedgerItem] = field(default_factory=list)

    def add_spec(self, spec: TaskSpec) -> RequirementLedgerItem:
        item = RequirementLedgerItem(
            task_id=spec.task_id,
            section_index=spec.section_index,
            title=spec.title,
            kind=spec.kind,
            status="mentioned",
            spec_hash=spec.spec_hash(),
            provenance=dict(spec.provenance),
        )
        self.items.append(item)
        return item

    def get(self, task_id: str) -> RequirementLedgerItem | None:
        for it in self.items:
            if it.task_id == task_id:
                return it
        return None

    def mark_computed(self, task_id: str, result_id: str) -> None:
        it = self.get(task_id)
        if it:
            it.status = "computed"
            it.result_id = result_id

    def mark_checked(self, task_id: str, checks: list[dict[str, Any]]) -> None:
        it = self.get(task_id)
        if it:
            it.checks = checks
            if all(c.get("passed", False) for c in checks):
                it.status = "checked"
            else:
                it.status = "failed_checks"

    def mark_delivered(self, task_id: str, location: str, files: list[dict[str, Any]] | None = None) -> None:
        it = self.get(task_id)
        if it:
            it.answer_location = location
            if files:
                it.files.extend(files)
            if it.status in ("checked", "source_supported"):
                it.status = "complete"
            else:
                it.status = "delivered"

    def summary_counts(self) -> dict[str, int]:
        counts = {
            "mentioned": 0,
            "computed": 0,
            "checked": 0,
            "source_supported": 0,
            "delivered": 0,
            "complete": 0,
            "total": len(self.items),
        }
        for it in self.items:
            counts[it.status] = counts.get(it.status, 0) + 1
        return counts

    def is_complete(self) -> bool:
        if not self.items:
            return False
        return all(it.status == "complete" for it in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "counts": self.summary_counts(),
            "is_complete": self.is_complete(),
        }
