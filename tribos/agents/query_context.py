"""
Per-inquiry routing context: what was parsed from the question, which sources should run and why,
and the datasets attached to it. Built by query_planner.build_query_context.

Supports Tribos STEM entity types (`concept`, `equation`, `quantity`, `constant`, `material`, `system`)
while preserving legacy fields and methods so all callers and tests remain compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from tribos.extensions.id_families import extract_family_ids, family_names

EntityType = Literal[
    "concept",
    "equation",
    "quantity",
    "constant",
    "material",
    "system",
    # Legacy types retained for backward compatibility
    "gene",
    "drug",
    "disease",
    "variant",
]


class ResolvedEntity(BaseModel):
    type: EntityType
    mention: str
    span: tuple[int, int] = (0, 0)
    label: str
    ids: dict[str, str] = Field(default_factory=dict)
    source: str = "query_text"
    matched_on: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    gene: str | None = None
    variant_kind: str | None = None
    protein_change: str | None = None
    validated: bool = False
    ambiguous_with: list[str] = Field(default_factory=list)

    @property
    def entity_type(self) -> EntityType:
        return self.type

    @property
    def canonical(self) -> str:
        return self.label or self.mention


class SourceDecision(BaseModel):
    run: bool
    reason: str = ""


SimulationAction = Literal["time_course", "steady_state", "parameter_scan"]
TaskStatus = Literal["completed", "partial", "needs_input", "failed", "cancelled"]

SIM_DURATION_MIN_SECONDS = 1.0
SIM_DURATION_MAX_SECONDS = 5000.0
SIM_SCAN_MAX_POINTS = 50
SIM_MAX_OVERRIDES = 20


class SimulationConstraints(BaseModel):
    """Scoped simulation instructions. Only simulation_forbidden suppresses execution."""

    simulation_requested: bool = False
    simulation_forbidden: bool = False
    replacement_forbidden: bool = False
    reject_if_parameter_missing: bool = False
    scope: Literal["current_turn", "investigation"] = "current_turn"


class SimulationPlan(BaseModel):
    """The exact simulation the user asked for. A plan with validation_errors is not executed."""

    action: SimulationAction = "time_course"
    biomodel_id: str | None = None
    system_name: str | None = None
    duration_seconds: float = 60.0
    duration_explicit: bool = False
    intervals: int = 100
    parameter_overrides: dict[str, float] = Field(default_factory=dict)
    scan_parameter: str | None = None
    scan_start: float | None = None
    scan_end: float | None = None
    scan_points: int | None = None
    target_species: list[str] = Field(default_factory=list)
    validation_errors: list[dict[str, str]] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.validation_errors


class TaskOutcome(BaseModel):
    """Whether the requested operation ran, kept separate from evidence grounding."""

    task_status: TaskStatus = "completed"
    requested_operation: str | None = None
    executed_operation: str | None = None
    request_match: bool = True
    reason: str = ""
    grounding_status: Literal["supported", "partial", "unsupported", "contradicted", "not_checked"] = "not_checked"
    incomplete_reasons: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


@dataclass
class DatasetRef:
    id: str  # ^ds_[0-9a-f]{12}$
    kind: Literal["table", "hdf5", "mat", "h5ad", "sbml"]
    display_name: str
    analysis_path: str | None = None  # server-only; never serialized to clients
    model_path: str | None = None  # server-only
    public_provenance: dict[str, Any] = field(default_factory=dict)
    dims: str | None = None
    # Legacy optional fields retained as no-ops for backward compatibility
    geo_accession: str | None = None
    geo_verified: bool = False
    pmids: list[str] = field(default_factory=list)
    sbml_model_id: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "display_name": self.display_name,
            "public_provenance": dict(self.public_provenance),
            "dims": self.dims,
            "geo_accession": self.geo_accession,
            "geo_verified": self.geo_verified,
            "pmids": list(self.pmids),
            "sbml_model_id": self.sbml_model_id,
        }


def _is_unresolved_planner_term(e: ResolvedEntity) -> bool:
    return not e.validated and e.matched_on == "planner"


# QueryContext.observed_identifiers() key for each ResolvedEntity.ids key.
_ENTITY_ID_FAMILIES = {
    "arxiv": "arxiv",
    "arxiv_id": "arxiv",
    "doi": "doi",
    "zbl": "zbl",
    "zbl_id": "zbl",
    "mr": "mr",
    "mr_id": "mr",
    "oeis": "oeis",
    "oeis_id": "oeis",
    "ads": "ads",
    "bibcode": "ads",
    "mp": "mp",
    "mp_id": "mp",
    "isbn": "isbn",
    "openalex": "openalex",
    "openalex_id": "openalex",
    "computation": "computation",
    # Legacy keys retained for compatibility
    "ensembl_id": "ensembl",
    "uniprot_id": "uniprot",
    "hgnc_id": "hgnc",
    "chembl_id": "chembl",
    "ontology_id": "ontology",
    "rsid": "rsid",
}


@dataclass
class QueryContext:
    raw_query: str
    clean_query: str
    user_id: str = "default_user"
    thread_id: str = ""
    entities: list[ResolvedEntity] = field(default_factory=list)
    intents: set[str] = field(default_factory=set)
    primary_target: str | None = None
    primary_gene: ResolvedEntity | None = None
    biomodel_id: str | None = None
    system_name: str | None = None
    sim_duration: float = 60.0
    suppress_simulation: bool = False
    is_simulation_intent: bool = False
    wants_steady_state: bool = False
    simulation_plan: SimulationPlan | None = None
    simulation_constraints: SimulationConstraints = field(default_factory=SimulationConstraints)
    source_allowlist: set[str] | None = None
    source_restriction_reason: str = ""
    dataset_path: str | None = None
    has_single_cell_intent: bool = False
    excluded_modules: set[str] = field(default_factory=set)
    attachments: list[DatasetRef] = field(default_factory=list)
    attachment_errors: list[str] = field(default_factory=list)
    enable_web_search: bool = True
    decisions: dict[str, SourceDecision] = field(default_factory=dict)
    planner: str = "deterministic"
    scope: str = "research"
    normalization: str = "skipped"
    source_status: dict[str, str] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)
    search_plan: Any | None = None
    planner_task: Any | None = field(default=None, repr=False, compare=False)
    planner_started: float = 0.0
    effort_level: str = "medium"

    # -- entity views --------------------------------------------------------
    def _of_type(self, kind: str) -> list[ResolvedEntity]:
        return [e for e in self.entities if e.type == kind]

    @property
    def concepts(self) -> list[ResolvedEntity]:
        return self._of_type("concept")

    @property
    def equations(self) -> list[ResolvedEntity]:
        return self._of_type("equation")

    @property
    def quantities(self) -> list[ResolvedEntity]:
        return self._of_type("quantity")

    @property
    def constants(self) -> list[ResolvedEntity]:
        return self._of_type("constant")

    @property
    def materials(self) -> list[ResolvedEntity]:
        return self._of_type("material")

    @property
    def systems(self) -> list[ResolvedEntity]:
        return self._of_type("system")

    # Legacy entity views retained for backward compatibility
    @property
    def genes(self) -> list[ResolvedEntity]:
        return self._of_type("gene")

    @property
    def drugs(self) -> list[ResolvedEntity]:
        return self._of_type("drug")

    @property
    def diseases(self) -> list[ResolvedEntity]:
        return self._of_type("disease")

    @property
    def variants(self) -> list[ResolvedEntity]:
        return self._of_type("variant")

    @property
    def primary_symbol(self) -> str | None:
        if self.primary_gene is not None:
            return self.primary_gene.label
        if self.primary_target:
            return self.primary_target
        for group in (self.concepts, self.equations, self.systems, self.materials, self.constants):
            if group:
                return group[0].label
        return None

    @property
    def primary_display(self) -> str | None:
        """Primary subject display string."""
        if self.primary_target is None and self.primary_gene is None:
            return self.primary_symbol
        if self.primary_target is None or self.primary_gene is None:
            return self.primary_target
        mention, label = self.primary_gene.mention, self.primary_gene.label
        if not mention or mention.upper() == label.upper():
            return self.primary_target
        rest = self.primary_target[len(label):] if self.primary_target.startswith(label) else ""
        return f"{label} ({mention}){rest}"

    @property
    def primary_ensembl_id(self) -> str | None:
        return self.primary_gene.ids.get("ensembl_id") if self.primary_gene is not None else None

    def primary_aliases(self) -> list[str]:
        if self.primary_gene is not None:
            aliases = list(self.primary_gene.aliases)
            mention = self.primary_gene.mention
            if mention and mention != self.primary_gene.label and mention not in aliases:
                aliases.append(mention)
            return aliases
        for group in (self.concepts, self.equations, self.systems, self.materials):
            if group:
                return list(group[0].aliases)
        return []

    # -- attachments ---------------------------------------------------------
    @property
    def dataset_attachment(self) -> DatasetRef | None:
        return next((a for a in self.attachments if a.kind in ("table", "hdf5", "mat", "h5ad")), None)

    @property
    def model_attachment(self) -> DatasetRef | None:
        return next((a for a in self.attachments if a.kind == "sbml"), None)

    @property
    def literature_ids(self) -> list[str]:
        """Explicit literature identifiers (arXiv, DOI, PMID, Zbl, MR, ADS) in the question."""
        raw = self.raw_query or self.clean_query or ""
        try:
            from ..archivon.identifiers import extract_literature_ids as _extract_arch
            ids = list(_extract_arch(raw))
        except Exception:  # noqa: BLE001
            ids = []
        fam = extract_family_ids(raw)
        for k in ("arxiv", "zbl", "mr", "ads", "openalex"):
            for v in sorted(fam.get(k, ())):
                if v not in ids:
                    ids.append(v)
        return ids

    def excludes(self, module: str) -> bool:
        return module in (self.excluded_modules or set())

    @property
    def analysis_dataset_path(self) -> str | None:
        att = self.dataset_attachment
        if att is not None and att.analysis_path:
            return att.analysis_path
        return self.dataset_path

    @property
    def single_cell_attachment(self) -> DatasetRef | None:
        return next((a for a in self.attachments if a.kind in ("hdf5", "mat", "table", "h5ad") and a.analysis_path), None)

    @property
    def single_cell_dataset_path(self) -> str | None:
        att = self.single_cell_attachment
        return att.analysis_path if att is not None else self.dataset_path

    # -- routing -------------------------------------------------------------
    def should_run(self, name: str) -> bool:
        return self.decisions.get(name, SourceDecision(run=False)).run and self.source_allowed(name)

    def source_allowed(self, name: str) -> bool:
        if self.source_allowlist is None:
            return True
        if name in self.source_allowlist:
            return True
        # Alias equivalence between legacy and new source keys
        if name == "archivon" and "lithoscribe" in self.source_allowlist:
            return True
        if name == "lithoscribe" and "archivon" in self.source_allowlist:
            return True
        if name == "dynamis" and "vivarix" in self.source_allowlist:
            return True
        if name == "vivarix" and "dynamis" in self.source_allowlist:
            return True
        return False

    def gate_decision(self, name: str, decision: SourceDecision) -> SourceDecision:
        if decision.run and not self.source_allowed(name):
            return SourceDecision(run=False, reason=self.source_restriction_reason or "excluded at your request")
        return decision

    def focus_terms(self) -> list[str]:
        """Core STEM terms (concepts, equations, systems, materials, constants) from the query."""
        terms: list[str] = []
        if self.primary_target:
            terms.append(self.primary_target)
            alias = self.primary_gene.mention if self.primary_gene is not None else ""
            if alias and alias.upper() != (self.primary_symbol or "").upper():
                terms.append(alias)
        for ent in (
            *self.concepts[:3],
            *self.equations[:2],
            *self.systems[:2],
            *self.materials[:2],
            *self.constants[:2],
            *self.drugs[:2],
            *self.diseases[:1],
        ):
            if ent.label and ent.label not in terms:
                terms.append(ent.label)
            if ent.mention and ent.mention not in terms:
                terms.append(ent.mention)
        return list(dict.fromkeys(terms))

    def web_query(self) -> str:
        terms = self.focus_terms()
        if terms:
            return " ".join(terms[:4])
        return self.clean_query[:200]

    def biomodel_search_term(self) -> str:
        if self.system_name:
            return self.system_name
        if self.systems:
            return self.systems[0].label
        if self.primary_gene is not None and self.primary_gene.mention and self.primary_gene.span != (0, 0):
            return self.primary_gene.mention
        return self.primary_target or self.clean_query

    def lumicell_target_gene(self) -> str | None:
        return self.primary_symbol if self.primary_target else None

    def plan_facts(self) -> list[str]:
        """Human-readable routing facts for the plan step."""
        facts: list[str] = []
        if self.primary_display:
            facts.append(f"Subject: {self.primary_display}")
        facts.extend(self._entity_facts())
        if not facts:
            facts.append("General STEM / analytical inquiry")
        if self.system_name:
            facts.append(f"Dynamical system: {self.system_name}")
        if self.biomodel_id:
            facts.append(f"Model: {self.biomodel_id}")
        model = self.model_attachment
        if model is not None:
            facts.append(f"Model: {model.display_name} (uploaded model)")
        followup = self.extras.get("resolved_followup")
        if isinstance(followup, dict) and followup.get("subject"):
            facts.append(f"Follow-up: subject {followup['subject']} from the previous question")
        plan = self.simulation_plan
        if self.suppress_simulation:
            facts.append("Simulation: skipped at your request")
        elif plan is not None and plan.validation_errors:
            facts.append(
                "Simulation: not run - "
                + "; ".join(e.get("message", e.get("code", "")) for e in plan.validation_errors[:3])
            )
        elif plan is not None and plan.action == "parameter_scan":
            rng = (
                f" from {plan.scan_start:g} to {plan.scan_end:g}"
                if plan.scan_start is not None and plan.scan_end is not None
                else ""
            )
            pts = f", {plan.scan_points} points" if plan.scan_points else ""
            facts.append(
                f"Simulation: parameter scan of {plan.scan_parameter}{rng}{pts}, {plan.duration_seconds:g}s per point"
            )
        elif self.is_simulation_intent:
            facts.append(
                f"Simulation: {self.sim_duration:g}s trajectory"
                + (" + equilibrium" if self.wants_steady_state else "")
            )
        if plan is not None and plan.parameter_overrides and not plan.validation_errors:
            facts.append(
                "Parameters: "
                + ", ".join(f"{k}={v:g}" for k, v in list(plan.parameter_overrides.items())[:5])
            )
        if self.source_allowlist is not None and self.source_restriction_reason:
            facts.append(f"Sources: {self.source_restriction_reason}")
        dataset = self.dataset_attachment
        if dataset is not None:
            facts.append(
                f"Dataset: {dataset.display_name} ({dataset.id}, uploaded{', ' + dataset.dims if dataset.dims else ''})"
            )
        elif self.dataset_path:
            facts.append(f"Dataset: {self.dataset_path}")
        facts.append("Web search: on" if self.enable_web_search else "Web search: off")
        return facts

    def _entity_facts(self) -> list[str]:
        def show(e: ResolvedEntity) -> str:
            return e.label if not e.mention or e.mention.lower() == e.label.lower() else f"{e.label} ({e.mention})"

        facts: list[str] = []
        if self.concepts:
            facts.append(
                ("Concepts: " if len(self.concepts) > 1 else "Concept: ")
                + ", ".join(show(c) for c in self.concepts[:3])
            )
        if self.equations:
            facts.append(
                ("Equations: " if len(self.equations) > 1 else "Equation: ")
                + ", ".join(show(eq) for eq in self.equations[:3])
            )
        if self.constants:
            facts.append(
                ("Constants: " if len(self.constants) > 1 else "Constant: ")
                + ", ".join(show(c) for c in self.constants[:3])
            )
        if self.quantities:
            facts.append(
                ("Quantities: " if len(self.quantities) > 1 else "Quantity: ")
                + ", ".join(q.label for q in self.quantities[:4])
            )
        if self.materials:
            facts.append(
                ("Materials: " if len(self.materials) > 1 else "Material: ")
                + ", ".join(show(m) for m in self.materials[:3])
            )
        if self.systems:
            facts.append(
                ("Systems: " if len(self.systems) > 1 else "System: ")
                + ", ".join(show(s) for s in self.systems[:2])
            )
        if self.drugs:
            facts.append(("Drugs: " if len(self.drugs) > 1 else "Drug: ") + ", ".join(show(d) for d in self.drugs[:3]))
        established = [d for d in self.diseases if not _is_unresolved_planner_term(d)]
        if established:
            facts.append("Disease: " + ", ".join(show(d) for d in established[:2]))
        if self.variants:
            facts.append(
                ("Variants: " if len(self.variants) > 1 else "Variant: ")
                + ", ".join(v.label for v in self.variants[:3])
            )
        return facts

    def to_step_extra(self) -> dict[str, Any]:
        return {
            "entities": [e.model_dump() for e in self.entities],
            "intents": sorted(self.intents),
            "sources": [{"name": k, "run": d.run, "reason": d.reason} for k, d in self.decisions.items()],
            "planner": self.planner,
            "scope": self.scope,
            "normalization": self.normalization,
            "latency_ms": round(sum(self.timings_ms.values()), 1),
        }

    def to_artifact(self) -> dict[str, Any]:
        """JSON-safe summary for the client: no server paths (typed paths are reduced to their basename)."""
        dataset_name = None
        if self.dataset_path:
            dataset_name = re.split(r"[\\/]", self.dataset_path)[-1]
        return {
            "primary_target": self.primary_target,
            "primary_symbol": self.primary_symbol,
            "biomodel_id": self.biomodel_id,
            "system_name": self.system_name,
            "sim_duration": self.sim_duration,
            "suppress_simulation": self.suppress_simulation,
            "is_simulation_intent": self.is_simulation_intent,
            "wants_steady_state": self.wants_steady_state,
            "dataset": dataset_name,
            "has_single_cell_intent": self.has_single_cell_intent,
            "enable_web_search": self.enable_web_search,
            "attachments": [a.to_public() for a in self.attachments],
            "attachment_errors": list(self.attachment_errors),
            "source_status": dict(self.source_status),
            "search_plan": self.search_plan.to_dict() if self.search_plan is not None else None,
            "simulation_plan": self.simulation_plan.model_dump() if self.simulation_plan is not None else None,
            "simulation_constraints": self.simulation_constraints.model_dump(),
            "source_allowlist": sorted(self.source_allowlist) if self.source_allowlist is not None else None,
            "resolved_followup": self.extras.get("resolved_followup"),
            **self.to_step_extra(),
        }

    def observed_identifiers(self) -> dict[str, set[str]]:
        """Identifiers this context legitimately knows about, merged into the verifier's observed sets."""
        out: dict[str, set[str]] = {name: set() for name in family_names()}
        for family in _ENTITY_ID_FAMILIES.values():
            out.setdefault(family, set())
        out.setdefault("dataset", set())
        out.setdefault("pmids", set())
        out.setdefault("dois", set())
        out.setdefault("biomodels", set())

        for e in self.entities:
            if not getattr(e, "validated", True):
                continue
            for id_key, family in _ENTITY_ID_FAMILIES.items():
                value = e.ids.get(id_key)
                if value:
                    out.setdefault(family, set()).add(str(value))
        for att in self.attachments:
            out["dataset"].add(att.id)
            if att.geo_verified and att.pmids:
                out["pmids"].update(str(p) for p in att.pmids if p)
        for fam, vals in extract_family_ids(self.raw_query or self.clean_query or "").items():
            out.setdefault(fam, set()).update(vals)
        return out
