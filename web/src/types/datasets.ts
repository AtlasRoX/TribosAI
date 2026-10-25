// Dataset upload types (owned by UPLOADS, feature 8), mirroring tribos/datasets/models.py.

/** Kinds an upload can have (EXTENSION_KINDS in tribos/datasets/store.py). */
export type UploadKind = "table" | "hdf5" | "mat";

/**
 * A stored dataset's kind. "legacy" is a biomedical-release upload (h5ad or SBML) the server still lists and
 * counts against the quota but no longer analyses; its original kind is in `legacy_kind`.
 */
export type DatasetKind = UploadKind | "legacy";

/** Provenance sources offered for new uploads (DatasetSource in tribos/datasets/models.py). */
export type DatasetSource =
  | "experiment"
  | "simulation"
  | "benchmark"
  | "public_repository"
  | "literature"
  | "in_house"
  | "collaborator"
  | "other";

/** Sources of the biomedical release: shown on old records, never offered. */
export type LegacyDatasetSource = "geo" | "cellxgene" | "biomodels";

/** Provenance declared by the uploader. */
export interface DatasetProvenance {
  source: DatasetSource | LegacyDatasetSource;
  /** The engineering or science field the data comes from, e.g. "structural mechanics". */
  domain?: string | null;
  description?: string | null;
  attests_no_direct_identifiers: boolean;
  /** Column -> unit, e.g. {"stress": "MPa"}. */
  units?: Record<string, string>;
  // Fields of the biomedical release, present on old records only; the form neither shows nor sends them.
  geo_accession?: string | null;
  organism?: string | null;
  consent_status?: string;
  irb_protocol_id?: string | null;
  table_orientation?: string | null;
}

/** GET /api/datasets/limits: accepted extensions (with their kind) and the byte cap of each kind. */
export interface DatasetLimits {
  extensions: Record<string, UploadKind>;
  max_bytes: Record<UploadKind, number>;
}

export interface DatasetValidation {
  format: string;
  n_rows?: number | null;
  n_columns?: number | null;
  columns?: string[];
  dtypes?: Record<string, string>;
  /** HDF5 dataset paths or MAT variable names. */
  datasets?: string[];
  shapes?: Record<string, number[]>;
  units?: Record<string, string>;
  warnings: string[];
  // Biomedical-release fields (legacy records).
  n_obs?: number | null;
  n_vars?: number | null;
  n_species?: number | null;
}

export interface DatasetRecord {
  id: string;
  kind: DatasetKind;
  display_name: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  declared_by: "uploader";
  provenance: DatasetProvenance;
  validation: DatasetValidation;
  original_extension?: string;
  derived_sha256?: string | null;
  /** Server-formatted dimensions, e.g. "1,200 rows × 8 columns". */
  dims?: string | null;
  /** False for a legacy upload: listed and deletable, never analysed (see unsupported_reason). */
  analysable?: boolean;
  unsupported_reason?: string;
  legacy_kind?: string | null;
  provenance_history?: { changed_at: string; previous: Record<string, unknown> }[];
}

export interface MessageAttachment {
  id: string;
  kind: DatasetKind;
  display_name: string;
  dims?: string;
}

/** One entry of execution_artifacts.datasets, i.e. DatasetRef.to_public(); it never contains server paths. */
export interface DatasetPublic {
  id: string;
  kind: DatasetKind;
  display_name: string;
  public_provenance: Record<string, unknown>;
  dims?: string | null;
}
