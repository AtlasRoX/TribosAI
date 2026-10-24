"""Records for uploaded datasets and models. Nothing here ever carries a server path."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DATASET_ID_RE = re.compile(r"^ds_[0-9a-f]{12}$")


class DatasetKind(str, Enum):
    TABLE = "table"
    HDF5 = "hdf5"
    MAT = "mat"


class ConsentStatus(str, Enum):
    PUBLIC_DEIDENTIFIED = "public_deidentified"
    IRB_APPROVED = "irb_approved"
    CONSENT_NO_IRB = "consent_obtained_no_irb"
    NOT_HUMAN_SUBJECTS = "not_human_subjects"
    UNKNOWN = "unknown"


class DatasetSource(str, Enum):
    IN_HOUSE = "in_house"
    COLLABORATOR = "collaborator"
    EXPERIMENT = "experiment"
    SIMULATION = "simulation"
    BENCHMARK = "benchmark"
    PUBLIC_REPOSITORY = "public_repository"
    LITERATURE = "literature"
    GEO = "geo"
    CELLXGENE = "cellxgene"
    BIOMODELS = "biomodels"
    OTHER = "other"


class DatasetProvenanceIn(BaseModel):
    """Provenance declared by the uploader."""

    source: DatasetSource = DatasetSource.IN_HOUSE
    geo_accession: str | None = Field(None, pattern=r"^GSE\d{1,9}$")
    organism: str | None = Field(None, max_length=120)
    consent_status: ConsentStatus = ConsentStatus.NOT_HUMAN_SUBJECTS
    irb_protocol_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9._\-/ ]*$")
    description: str | None = Field(None, max_length=4000)
    attests_no_direct_identifiers: bool = True
    table_orientation: Literal["cells_by_genes", "genes_by_cells"] | None = None
    matrix_layer: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    input_scale: Literal["raw_counts", "normalized", "log1p"] | None = None
    domain: str | None = Field(None, max_length=120)
    units: dict[str, str] = Field(default_factory=dict)

    @field_validator("geo_accession", "organism", "irb_protocol_id", "description", "matrix_layer", "input_scale", "domain", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("geo_accession", mode="before")
    @classmethod
    def _upper_accession(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("attests_no_direct_identifiers")
    @classmethod
    def _must_attest(cls, value: bool) -> bool:
        return bool(value)


GEO_VERIFICATION_SCOPE = "accession_exists"
GEO_STATUS_LABELS = {
    "verified": "GEO accession exists (link to this file declared by the uploader, not verified)",
    "not_found": "GEO accession not found",
    "lookup_failed": "GEO lookup failed",
    "not_requested": None,
}


class GeoVerification(BaseModel):
    status: Literal["verified", "not_found", "lookup_failed", "not_requested"] = "not_requested"
    verification_scope: Literal["accession_exists"] = GEO_VERIFICATION_SCOPE
    accession: str | None = None
    title: str | None = None
    taxon: str | None = None
    n_samples: int | None = None
    pdat: str | None = None
    pubmedids: list[str] = Field(default_factory=list)
    bioproject: str | None = None
    samples: list[str] = Field(default_factory=list)
    organism_matches: bool | None = None
    checked_at: datetime | None = None
    error: str | None = None


class ValidationSummary(BaseModel):
    format: str
    n_obs: int | None = None
    n_vars: int | None = None
    n_rows: int | None = None
    n_columns: int | None = None
    columns: list[str] = Field(default_factory=list)
    dtypes: dict[str, str] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)
    shapes: dict[str, list[int]] = Field(default_factory=dict)
    x_encoding: str | None = None
    obs_columns: list[str] = Field(default_factory=list)
    uns_hints: dict[str, str] = Field(default_factory=dict)
    sbml_level: int | None = None
    sbml_version: int | None = None
    sbml_model_id: str | None = None
    sbml_model_name: str | None = None
    n_species: int | None = None
    n_reaction_parameters: int | None = None
    units: dict[str, str] = Field(default_factory=dict)
    table_orientation: Literal["cells_by_genes", "genes_by_cells"] | None = None
    warnings: list[str] = Field(default_factory=list)


class DatasetRecord(BaseModel):
    """One upload as stored in manifest.json. Storage paths are derived by the store, never recorded here."""

    id: str
    kind: DatasetKind
    display_name: str
    original_extension: str
    size_bytes: int
    sha256: str
    derived_sha256: str | None = None
    uploaded_at: datetime
    declared_by: Literal["uploader"] = "uploader"
    provenance: DatasetProvenanceIn
    geo_verification: GeoVerification = Field(default_factory=GeoVerification)
    validation: ValidationSummary
    provenance_history: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not DATASET_ID_RE.match(value):
            raise ValueError("invalid dataset id")
        return value

    @property
    def geo_verified(self) -> bool:
        return self.geo_verification.status == "verified"

    @property
    def geo_declared_pmids(self) -> list[str]:
        geo = self.geo_verification or GeoVerification()
        if not self.geo_verified or geo.organism_matches is False:
            return []
        return list(geo.pubmedids)

    def dims(self) -> str | None:
        v = self.validation

        if v.n_obs is not None and v.n_vars is not None:
            return f"{v.n_obs:,} cells × {v.n_vars:,} genes"
        if v.n_rows is not None and v.n_columns is not None:
            return f"{v.n_rows:,} rows × {v.n_columns:,} columns"
        if v.datasets:
            return f"{len(v.datasets)} dataset(s)"
        return None

    def public_provenance(self) -> dict[str, Any]:
        """The provenance that may reach the evidence block, the verifier and the client (no paths, no free text)."""
        geo = self.geo_verification or GeoVerification()
        out: dict[str, Any] = {
            "id": self.id,
            "display_name": self.display_name,
            "kind": self.kind.value,
            "sha256": self.sha256,
            "source": self.provenance.source.value,
            "geo_accession": self.provenance.geo_accession,
            "geo_verified": self.geo_verified,
            "geo_status": geo.status,
            "geo_accession_exists": self.geo_verified,
            "geo_verification_scope": geo.verification_scope,
            "geo_status_label": GEO_STATUS_LABELS.get(geo.status) if self.provenance.geo_accession else None,
            "geo_link": "declared_by_uploader" if self.provenance.geo_accession else None,
            "organism": self.provenance.organism,
            "consent_status": self.provenance.consent_status.value,
            "uploaded_at": self.uploaded_at.isoformat(),
            "declared_by": self.declared_by,
            "sbml_model_id": self.validation.sbml_model_id,
            "matrix_layer": self.provenance.matrix_layer,
            "input_scale": self.provenance.input_scale,
        }
        if self.geo_verified:
            out["geo_title"] = geo.title
            out["geo_taxon"] = geo.taxon
            out["geo_pubmedids"] = self.geo_declared_pmids
            out["geo_pmids_role"] = "declared_source"
            out["geo_organism_matches"] = geo.organism_matches
        return out

    def to_api(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["dims"] = self.dims()
        return data


class ResolvedAttachment(BaseModel):
    """A record plus its server-side file locations; only the store creates these, for the record's owner."""

    record: DatasetRecord
    analysis_path: str | None = None
    model_path: str | None = None

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def display_name(self) -> str:
        return self.record.display_name

    @property
    def kind(self) -> DatasetKind:
        return self.record.kind

    def public_provenance(self) -> dict[str, Any]:
        return self.record.public_provenance()
