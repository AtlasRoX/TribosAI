"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Archive, FileSpreadsheet, Grid3x3, Layers, LoaderCircle, X } from "lucide-react";
import styles from "./Datasets.module.css";
import type { DatasetLimits, DatasetProvenance, DatasetRecord, DatasetSource } from "@/types/datasets";
import {
  SOURCE_LABELS,
  formatBytes,
  isOfferedSource,
  kindForFile,
  patchProvenance,
  uploadDataset,
  type AuthHeaders,
  type UploadHandle,
} from "@/services/datasetService";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keeps Tab focus inside `ref` while active, focuses the first control, closes on Escape and restores focus. */
export function useFocusTrap(ref: React.RefObject<HTMLElement | null>, active: boolean, onEscape: () => void) {
  const escapeRef = useRef(onEscape);
  useEffect(() => {
    escapeRef.current = onEscape;
  });
  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>("[data-autofocus]") || node?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (!ref.current) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        escapeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [active, ref]);
}

export function KindIcon({ kind, size = 14 }: { kind: string; size?: number }) {
  const s = { width: size, height: size };
  if (kind === "table") return <FileSpreadsheet style={s} aria-hidden="true" />;
  if (kind === "hdf5") return <Layers style={s} aria-hidden="true" />;
  if (kind === "mat") return <Grid3x3 style={s} aria-hidden="true" />;
  // Legacy (biomedical-release) uploads and any kind this client does not know.
  return <Archive style={s} aria-hidden="true" />;
}

const KIND_LABELS: Record<string, string> = {
  table: "Table",
  hdf5: "HDF5 file",
  mat: "MATLAB .mat file",
  legacy: "Legacy upload (no longer analysed)",
};

/** The display label of any stored kind, including legacy and unknown values. */
export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export interface ProvenanceFormProps {
  mode: "upload" | "edit";
  file?: File | null;
  record?: DatasetRecord | null;
  backendUrl: string;
  authHeaders: AuthHeaders;
  /** Accepted extensions and size caps (GET /api/datasets/limits); the static defaults otherwise. */
  limits?: DatasetLimits;
  onClose: () => void;
  onSaved: (record: DatasetRecord) => void;
}

type Phase = "editing" | "uploading" | "validating" | "done";

/** Server validation warnings worth showing before the dataset is attached. */
function uploadNotes(record: DatasetRecord): string[] {
  return [...(record.validation?.warnings || [])];
}

/** Modal collecting uploader-declared provenance, then uploading (or PATCHing) with inline server reasons. */
export function ProvenanceForm({ mode, file, record, backendUrl, authHeaders, limits, onClose, onSaved }: ProvenanceFormProps) {
  const initial = record?.provenance;
  const kind: string | null = record?.kind ?? (file ? kindForFile(file.name, limits) : null);
  // A biomedical-release source (GEO, CELLxGENE, BioModels) is not offered; editing such a record picks a current one.
  const [source, setSource] = useState<DatasetSource>(
    isOfferedSource(initial?.source) ? initial.source : initial?.source ? "public_repository" : "experiment"
  );
  const [domain, setDomain] = useState(initial?.domain ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [attest, setAttest] = useState(mode === "edit" ? Boolean(initial?.attests_no_direct_identifiers) : false);
  const [phase, setPhase] = useState<Phase>("editing");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<DatasetRecord | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const uploadRef = useRef<UploadHandle | null>(null);
  const ids = useId();

  const busy = phase === "uploading" || phase === "validating";
  const locked = phase !== "editing";
  const close = () => {
    uploadRef.current?.abort();
    onClose();
  };
  useFocusTrap(dialogRef, true, () => {
    if (!busy) close();
  });

  const canSubmit = attest && !busy && (mode === "edit" || Boolean(file && kind));

  const provenance = (): DatasetProvenance => ({
    source,
    domain: domain.trim() || null,
    description: description.trim() || null,
    attests_no_direct_identifiers: attest,
    // Column units declared earlier are kept; the form does not edit them.
    ...(initial?.units && Object.keys(initial.units).length ? { units: initial.units } : {}),
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    // The modal is portaled, but React still bubbles submit to the composer form around the attach button.
    e.stopPropagation();
    if (!canSubmit) return;
    setError(null);
    try {
      let result: DatasetRecord;
      if (mode === "edit" && record) {
        setPhase("validating");
        result = await patchProvenance(backendUrl, authHeaders, record.id, provenance());
      } else {
        setPhase("uploading");
        setProgress(0);
        const handle = uploadDataset(backendUrl, authHeaders, file as File, provenance(), (f) => {
          setProgress(f);
          if (f >= 1) setPhase("validating");
        });
        uploadRef.current = handle;
        result = await handle.promise;
      }
      uploadRef.current = null;
      // Validation warnings (e.g. a possible identifier column) are shown before the dataset is attached.
      if (mode === "upload" && uploadNotes(result).length) {
        setSaved(result);
        setPhase("done");
      } else {
        onSaved(result);
      }
    } catch (err) {
      uploadRef.current = null;
      setPhase("editing");
      setError(err instanceof Error ? err.message : "The upload failed.");
    }
  };

  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className={styles.overlay}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby={`${ids}-title`}>
        <div className={styles.dialogHead}>
          <div style={{ minWidth: 0 }}>
            <h2 id={`${ids}-title`} className={styles.dialogTitle}>
              {mode === "edit" ? "Edit provenance" : "Dataset provenance"}
            </h2>
            <p className={styles.dialogSub}>
              Provenance is declared by you and shown to the model as uploader-declared; it is not verified.
            </p>
          </div>
          <button type="button" className={styles.iconButton} onClick={close} aria-label="Close" disabled={phase === "validating"}>
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>

        <form className={styles.form} onSubmit={submit} noValidate>
          <div className={styles.fileSummary}>
            {kind && <KindIcon kind={kind} size={16} />}
            <strong>{record?.display_name || file?.name}</strong>
            <span className={styles.hint}>
              {[kind ? kindLabel(kind) : null, file ? formatBytes(file.size) : record ? formatBytes(record.size_bytes) : null]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </div>

          <fieldset className={styles.field} disabled={locked}>
            <legend className={styles.label}>Source</legend>
            <div className={styles.segmented}>
              {(Object.keys(SOURCE_LABELS) as DatasetSource[]).map((s) => (
                <button key={s} type="button" className={styles.segment} aria-pressed={source === s} onClick={() => setSource(s)}>
                  {SOURCE_LABELS[s]}
                </button>
              ))}
            </div>
          </fieldset>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${ids}-domain`}>
              Field
            </label>
            <input
              id={`${ids}-domain`}
              className={styles.input}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="Structural mechanics, fluid dynamics, control…"
              maxLength={120}
              disabled={locked}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${ids}-desc`}>
              Description
            </label>
            <textarea
              id={`${ids}-desc`}
              className={styles.textarea}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={4000}
              placeholder="Instrument, test conditions, units, processing steps…"
              disabled={locked}
            />
          </div>

          <label className={styles.checkbox}>
            <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} disabled={locked} required />
            <span>I confirm this file contains no personal data that identifies anyone (names, contact details, ID numbers).</span>
          </label>

          {phase === "uploading" && (
            <div>
              <div className={styles.progress} role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
                <div className={styles.progressBar} style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <div className={styles.status} style={{ marginTop: 6 }}>
                Uploading… {Math.round(progress * 100)}%
              </div>
            </div>
          )}
          {phase === "validating" && (
            <div className={styles.status} role="status">
              <LoaderCircle className={styles.spin} style={{ width: 14, height: 14 }} aria-hidden="true" />
              {mode === "edit" ? "Saving…" : "Validating the file on the server…"}
            </div>
          )}
          {error && (
            <div className={styles.error} role="alert">
              {error}
            </div>
          )}
          {phase === "done" && saved && (
            <div role="status">
              <div className={styles.status}>Uploaded as {saved.id}. The server noted:</div>
              <ul className={styles.warnings}>
                {uploadNotes(saved).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <div className={styles.actions}>
            {phase === "done" && saved ? (
              <button type="button" className={styles.buttonPrimary} onClick={() => onSaved(saved)} autoFocus>
                Attach
              </button>
            ) : (
              <>
                <button type="button" className={styles.button} onClick={close} disabled={phase === "validating"}>
                  Cancel
                </button>
                <button type="submit" className={styles.buttonPrimary} disabled={!canSubmit}>
                  {mode === "edit" ? "Save provenance" : "Upload"}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
