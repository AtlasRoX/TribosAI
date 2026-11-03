"use client";

import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Library, Paperclip, Upload } from "lucide-react";
import type { DatasetLimits, MessageAttachment } from "@/types/datasets";
import { DatasetLibrary } from "@/components/DatasetLibrary";
import { ProvenanceForm } from "@/components/ProvenanceForm";
import {
  DEFAULT_DATASET_LIMITS,
  acceptAttr,
  extensionList,
  fetchDatasetLimits,
  kindForFile,
  precheckFile,
  toAttachment,
  uploadDataset,
  type AuthHeaders,
} from "@/services/datasetService";
import styles from "./Datasets.module.css";

export interface ComposerAttachButtonProps {
  attached: MessageAttachment[];
  onAttach: (a: MessageAttachment) => void;
  /** A library delete or provenance edit of a dataset; attached chips are dropped or refreshed. */
  onDeleted?: (id: string) => void;
  onUpdated?: (a: MessageAttachment) => void;
  backendUrl: string;
  authHeaders: (extra?: Record<string, string>) => Record<string, string>;
  disabled?: boolean;
}

const MAX_ATTACHED = 5;

/** Composer pill to upload a dataset/model with provenance, or attach one from the library. */
export function ComposerAttachButton({
  attached,
  onAttach,
  onDeleted,
  onUpdated,
  backendUrl,
  authHeaders,
  disabled,
}: ComposerAttachButtonProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A PDF uploading without the provenance form: "Uploading notes.pdf… 40%".
  const [uploading, setUploading] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const full = attached.length >= MAX_ATTACHED;
  const headers: AuthHeaders = (extra) => authHeaders(extra);
  // The server's accepted extensions and size caps; the built-in defaults until (or unless) it answers.
  const [limits, setLimits] = useState<DatasetLimits>(DEFAULT_DATASET_LIMITS);
  const headersRef = useRef(authHeaders);
  useEffect(() => {
    headersRef.current = authHeaders;
  });
  useEffect(() => {
    const controller = new AbortController();
    void fetchDatasetLimits(backendUrl, (extra) => headersRef.current(extra), controller.signal).then((l) => {
      if (!controller.signal.aborted) setLimits(l);
    });
    return () => controller.abort();
  }, [backendUrl]);

  useEffect(() => {
    if (!menuOpen && !notice) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setNotice(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setNotice(null);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, notice]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  // Arrow keys move between the enabled menu items (WAI-ARIA menu pattern).
  const moveFocus = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'));
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  };

  const pickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const problem = precheckFile(file, limits);
    if (problem) {
      setNotice(`${file.name}: ${problem}`);
      return;
    }
    // A PDF is a document to read (the paper reader takes up to 40 pages), not measured data: it needs no provenance
    // form. It is recorded as literature, without the no-personal-data attestation (nobody confirmed it); the library
    // can add provenance later. Data files still open the form, where provenance matters.
    if (kindForFile(file.name, limits) === "paper") {
      setUploading(`Uploading ${file.name}…`);
      const handle = uploadDataset(backendUrl, headers, file,
        { source: "literature", domain: null, description: null, attests_no_direct_identifiers: false },
        (f) => setUploading(f < 1 ? `Uploading ${file.name}… ${Math.round(f * 100)}%` : `Reading ${file.name}…`));
      handle.promise
        .then((record) => onAttach(toAttachment(record)))
        .catch((err: unknown) => setNotice(`${file.name}: ${err instanceof Error ? err.message : "the upload failed"}`))
        .finally(() => setUploading(null));
      return;
    }
    setPendingFile(file);
  };

  return (
    <div className={styles.attach} ref={rootRef}>
      <button
        type="button"
        className="composer-pill"
        onClick={() => {
          setNotice(null);
          setMenuOpen((o) => !o);
        }}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label={attached.length ? `Attach a dataset (${attached.length} attached)` : "Attach a dataset"}
        title={`Attach a dataset (${extensionList(limits)})`}
        data-active={attached.length > 0 ? "true" : undefined}
        style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
      >
        <Paperclip style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden="true" />
        <span className="composer-pill-label">{attached.length ? `${attached.length} attached` : "Attach"}</span>
      </button>

      {menuOpen && (
        <div className={styles.menu} role="menu" aria-label="Attach" onKeyDown={moveFocus}>
          <button
            type="button"
            role="menuitem"
            className={styles.menuItem}
            disabled={full}
            autoFocus={!full}
            onClick={() => {
              setMenuOpen(false);
              inputRef.current?.click();
            }}
          >
            <Upload style={{ width: 14, height: 14 }} aria-hidden="true" />
            Upload file…
          </button>
          <button
            type="button"
            role="menuitem"
            className={styles.menuItem}
            autoFocus={full}
            onClick={() => {
              setMenuOpen(false);
              setLibraryOpen(true);
            }}
          >
            <Library style={{ width: 14, height: 14 }} aria-hidden="true" />
            From library…
          </button>
          <div className={styles.menuHint}>
            {full ? `Up to ${MAX_ATTACHED} datasets per question.` : extensionList(limits)}
          </div>
        </div>
      )}

      {uploading && !menuOpen && (
        <div className={styles.notice} role="status">
          {uploading}
        </div>
      )}
      {notice && !menuOpen && !uploading && (
        <div className={styles.notice} role="alert">
          {notice}
        </div>
      )}

      <input ref={inputRef} type="file" accept={acceptAttr(limits)} className={styles.hiddenInput} onChange={pickFile} tabIndex={-1} aria-hidden="true" />

      {pendingFile && (
        <ProvenanceForm
          mode="upload"
          file={pendingFile}
          limits={limits}
          backendUrl={backendUrl}
          authHeaders={headers}
          onClose={() => setPendingFile(null)}
          onSaved={(record) => {
            setPendingFile(null);
            onAttach(toAttachment(record));
          }}
        />
      )}

      {libraryOpen && (
        <DatasetLibrary
          backendUrl={backendUrl}
          authHeaders={headers}
          attachedIds={attached.map((a) => a.id)}
          attachDisabled={full}
          limits={limits}
          onAttach={(record) => onAttach(toAttachment(record))}
          onDeleted={onDeleted}
          onUpdated={onUpdated ? (record) => onUpdated(toAttachment(record)) : undefined}
          onClose={() => setLibraryOpen(false)}
        />
      )}
    </div>
  );
}
