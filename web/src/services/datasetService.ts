// Client for /api/datasets (UPLOADS, feature 8). Uploads use XMLHttpRequest for progress events;
// the browser sets the multipart boundary, so Content-Type is never set by hand.

import type { DatasetLimits, DatasetProvenance, DatasetRecord, DatasetSource, MessageAttachment, UploadKind } from "@/types/datasets";
import { ApiError, requestJson, type AuthHeaders } from "./apiClient.ts";

export type { AuthHeaders };

const MB = 1024 * 1024;

/**
 * The server's defaults (EXTENSION_KINDS and TRIBOS_UPLOAD_MAX_MB_* in tribos/datasets/store.py), used until
 * GET /api/datasets/limits answers, or when it fails. The server re-checks every upload.
 */
export const DEFAULT_DATASET_LIMITS: DatasetLimits = {
  extensions: {
    ".csv": "table",
    ".tsv": "table",
    ".xlsx": "table",
    ".parquet": "table",
    ".json": "table",
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".mat": "mat",
    ".pdf": "paper",
  },
  max_bytes: { table: 100 * MB, hdf5: 500 * MB, mat: 100 * MB, paper: 25 * MB },
};

const UPLOAD_KINDS: readonly UploadKind[] = ["table", "hdf5", "mat", "paper"];

/** A limits body as the server sent it, with anything malformed replaced by the defaults. */
export function normalizeDatasetLimits(body: unknown): DatasetLimits {
  const b = (body && typeof body === "object" ? body : {}) as { extensions?: unknown; max_bytes?: unknown };
  const extensions: Record<string, UploadKind> = {};
  if (b.extensions && typeof b.extensions === "object") {
    for (const [ext, kind] of Object.entries(b.extensions as Record<string, unknown>)) {
      if (/^\.[a-z0-9]{1,10}$/i.test(ext) && UPLOAD_KINDS.includes(kind as UploadKind)) extensions[ext.toLowerCase()] = kind as UploadKind;
    }
  }
  const caps = (b.max_bytes && typeof b.max_bytes === "object" ? b.max_bytes : {}) as Record<string, unknown>;
  const max_bytes = { ...DEFAULT_DATASET_LIMITS.max_bytes };
  for (const kind of UPLOAD_KINDS) {
    const v = caps[kind];
    if (typeof v === "number" && Number.isFinite(v) && v > 0) max_bytes[kind] = v;
  }
  return { extensions: Object.keys(extensions).length ? extensions : { ...DEFAULT_DATASET_LIMITS.extensions }, max_bytes };
}

/** The upload limits the server enforces; the static defaults when the call fails (older server, offline). */
export async function fetchDatasetLimits(backendUrl: string, authHeaders: AuthHeaders, signal?: AbortSignal): Promise<DatasetLimits> {
  try {
    return normalizeDatasetLimits(await requestJson<unknown>(`${backendUrl}/api/datasets/limits`, { headers: authHeaders(), signal }));
  } catch {
    return DEFAULT_DATASET_LIMITS;
  }
}

/** The `accept` attribute of the file picker. */
export function acceptAttr(limits: DatasetLimits = DEFAULT_DATASET_LIMITS): string {
  return Object.keys(limits.extensions).join(",");
}

/** ".csv, .tsv, .xlsx, …" for hints and errors. */
export function extensionList(limits: DatasetLimits = DEFAULT_DATASET_LIMITS): string {
  return Object.keys(limits.extensions).join(", ");
}

export const KIND_NAMES: Record<UploadKind, string> = { table: "Table", hdf5: "HDF5", mat: "MATLAB .mat", paper: "Paper (PDF)" };

export class DatasetApiError extends ApiError {
  reasonCode?: string;
  constructor(status: number, message: string, reasonCode?: string) {
    super(status, message);
    this.name = "DatasetApiError";
    this.reasonCode = reasonCode;
  }
}

const REASON_MESSAGES: Record<string, string> = {
  not_hdf5: "Not an HDF5 file.",
  hdf5_unreadable: "The file is truncated or corrupt.",
  hdf5_empty: "The HDF5 file contains no datasets.",
  hdf5_too_complex: "The HDF5 file has too many objects to check.",
  hdf5_external_link: "The file contains external or virtual HDF5 links, which are not allowed.",
  mat_unreadable: "The MATLAB .mat file could not be parsed.",
  mat_empty: "The MATLAB .mat file contains no variables.",
  not_pdf: "Not a PDF file.",
  pdf_unreadable: "The PDF is truncated or corrupt.",
  pdf_encrypted: "The PDF is encrypted; remove the password and upload it again.",
  pdf_too_many_pages: "The PDF has more pages than the server reads.",
  matrix_too_large: "The table is too large to analyze.",
  table_unreadable: "The table could not be parsed.",
  non_numeric_values: "Every value in the table must be numeric.",
  non_finite_values: "The table contains empty, NaN or infinite values.",
  unsupported_format: "This file format is not supported.",
  unsupported_type: "This file type is not supported.",
  empty_file: "The file is empty.",
};

const STATUS_MESSAGES: Record<number, string> = {
  401: "Sign in again: the API token was rejected.",
  404: "Dataset not found.",
  409: "The dataset is in use by a running analysis; try again shortly.",
  411: "The upload was sent without a length; try again.",
  413: "The file is larger than the upload limit.",
  507: "Your upload storage is full; delete a dataset first.",
};

/** The 415 text, naming the accepted extensions. */
export function unsupportedTypeMessage(limits: DatasetLimits = DEFAULT_DATASET_LIMITS): string {
  return `Unsupported file type. Upload ${extensionList(limits)}.`;
}

function errorFrom(status: number, body: unknown): DatasetApiError {
  const b = (body && typeof body === "object" ? body : {}) as { detail?: unknown; reason_code?: string };
  const detail = typeof b.detail === "string" ? b.detail : undefined;
  const reason = b.reason_code;
  let message: string;
  if (status === 422) {
    const canned = reason ? REASON_MESSAGES[reason] : undefined;
    // The server's detail is specific (which column, which link); keep it next to the short reason.
    message = canned ? (detail && detail !== canned ? `${canned} ${detail}` : canned) : detail || "The file did not pass validation.";
  } else if (status === 413 || status === 507) {
    message = detail || STATUS_MESSAGES[status];
  } else if (status === 415) {
    message = unsupportedTypeMessage();
  } else {
    message = STATUS_MESSAGES[status] || detail || `Request failed (${status}).`;
  }
  return new DatasetApiError(status, message, reason);
}

function request<T>(url: string, init: RequestInit): Promise<T> {
  return requestJson<T>(url, init, { toError: errorFrom });
}

export function kindForFile(name: string, limits: DatasetLimits = DEFAULT_DATASET_LIMITS): UploadKind | null {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return null;
  return limits.extensions[name.slice(dot).toLowerCase()] ?? null;
}

/** Client-side pre-check before any network call; returns an error message or null. */
export function precheckFile(file: File, limits: DatasetLimits = DEFAULT_DATASET_LIMITS): string | null {
  const kind = kindForFile(file.name, limits);
  if (!kind) return unsupportedTypeMessage(limits);
  if (file.size === 0) return REASON_MESSAGES.empty_file;
  const cap = limits.max_bytes[kind];
  if (file.size > cap) return `${KIND_NAMES[kind]} files are limited to ${Math.round(cap / MB)} MB.`;
  return null;
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return "–";
  if (n < 1024) return `${n} B`;
  if (n < MB) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * MB) return `${(n / MB).toFixed(1)} MB`;
  return `${(n / (1024 * MB)).toFixed(2)} GB`;
}

export function dimsOf(record: DatasetRecord): string | undefined {
  if (record.dims) return record.dims;
  const v: Partial<DatasetRecord["validation"]> = record.validation || {};
  const rows = v.n_rows ?? v.n_obs;
  const cols = v.n_columns ?? v.n_vars;
  if (rows != null && cols != null) return `${rows.toLocaleString()} rows × ${cols.toLocaleString()} columns`;
  const n = v.datasets?.length ?? 0;
  if (record.kind === "paper" && v.n_pages != null) return `${v.n_pages} page${v.n_pages === 1 ? "" : "s"}`;
  if (n) return `${n} ${record.kind === "mat" ? "variable" : "dataset"}${n === 1 ? "" : "s"}`;
  return undefined;
}

/** False for a legacy (biomedical-release) upload the server lists but no longer analyses. */
export function isAnalysable(record: Pick<DatasetRecord, "kind" | "analysable">): boolean {
  return record.analysable !== false && record.kind !== "legacy";
}

export function toAttachment(record: DatasetRecord): MessageAttachment {
  return { id: record.id, kind: record.kind, display_name: record.display_name, dims: dimsOf(record) };
}

export function listDatasets(backendUrl: string, authHeaders: AuthHeaders): Promise<DatasetRecord[]> {
  return request<{ datasets: DatasetRecord[] }>(`${backendUrl}/api/datasets`, { headers: authHeaders() }).then(
    (r) => r.datasets || [],
  );
}

export function getDataset(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<DatasetRecord> {
  return request<DatasetRecord>(`${backendUrl}/api/datasets/${encodeURIComponent(id)}`, { headers: authHeaders() });
}

export function patchProvenance(
  backendUrl: string,
  authHeaders: AuthHeaders,
  id: string,
  provenance: DatasetProvenance,
): Promise<DatasetRecord> {
  return request<DatasetRecord>(`${backendUrl}/api/datasets/${encodeURIComponent(id)}/provenance`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(provenance),
  });
}

export function deleteDataset(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`${backendUrl}/api/datasets/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

export interface UploadHandle {
  promise: Promise<DatasetRecord>;
  abort: () => void;
}

/** Upload with progress (0-1 for the bytes sent; the server then validates before answering). */
export function uploadDataset(
  backendUrl: string,
  authHeaders: AuthHeaders,
  file: File,
  provenance: DatasetProvenance,
  onProgress?: (fraction: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<DatasetRecord>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("provenance", JSON.stringify(provenance));
    xhr.open("POST", `${backendUrl}/api/datasets`);
    for (const [k, v] of Object.entries(authHeaders())) {
      if (k.toLowerCase() !== "content-type") xhr.setRequestHeader(k, v);
    }
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300 && xhr.response) resolve(xhr.response as DatasetRecord);
      else reject(errorFrom(xhr.status, xhr.response));
    };
    xhr.onerror = () => reject(new DatasetApiError(0, "The upload failed: the backend is unreachable."));
    xhr.onabort = () => reject(new DatasetApiError(0, "Upload cancelled."));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

/** Sources offered for an upload, in display order. */
export const SOURCE_LABELS: Record<DatasetSource, string> = {
  experiment: "Experiment",
  simulation: "Simulation",
  benchmark: "Benchmark",
  public_repository: "Public repository",
  literature: "Literature",
  in_house: "In-house",
  collaborator: "Collaborator",
  other: "Other",
};

/** Sources of the biomedical release, shown on old records only. */
const LEGACY_SOURCE_LABELS: Record<string, string> = { geo: "GEO", cellxgene: "CELLxGENE", biomodels: "BioModels" };

/** The label of any stored source, including legacy and unknown values. */
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "–";
  return SOURCE_LABELS[source as DatasetSource] ?? LEGACY_SOURCE_LABELS[source] ?? source;
}

/** True for a source the form offers (anything else is a legacy value). */
export function isOfferedSource(source: unknown): source is DatasetSource {
  return typeof source === "string" && source in SOURCE_LABELS;
}
