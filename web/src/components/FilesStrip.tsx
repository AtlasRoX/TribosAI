"use client";

// Files an answer produced because the question asked for them (a Word report, a Python script, a CSV, ...;
// tribos/files). Shown under the answer in every view: Open shows a text file in the side panel and anything else in
// a new tab; Download saves it. Requests carry the page's auth headers, so a plain link is not used.

import React, { useState } from "react";
import { Download, FileCode2, FileSpreadsheet, FileText, Image as ImageIcon, Loader2, PanelRightOpen } from "lucide-react";
import { openCode } from "@/lib/codePanel";
import type { AuthHeaders } from "@/services/apiClient";
import styles from "./FilesStrip.module.css";

export interface AnswerFile {
  id: string;
  name: string;
  kind: string;
  label: string;
  size: number;
  url: string;
  text?: string;
}

const LANGUAGE: Record<string, string> = { py: "python", md: "markdown", csv: "csv", json: "json" };

function KindIcon({ kind }: { kind: string }) {
  const s = { width: 16, height: 16 };
  if (kind === "py" || kind === "ipynb" || kind === "json") return <FileCode2 style={s} aria-hidden="true" />;
  if (kind === "csv" || kind === "xlsx") return <FileSpreadsheet style={s} aria-hidden="true" />;
  if (kind === "png") return <ImageIcon style={s} aria-hidden="true" />;
  return <FileText style={s} aria-hidden="true" />;
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function FilesStrip({ files, notes, backendUrl, authHeaders }: {
  files: AnswerFile[];
  notes?: string[];
  backendUrl: string;
  authHeaders: AuthHeaders;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const fetchBlob = async (f: AnswerFile, inline = false): Promise<Blob> => {
    const res = await fetch(`${backendUrl}${f.url}${inline ? "?inline=1" : ""}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.status === 404 ? "This file is no longer available." : `Download failed (${res.status}).`);
    return res.blob();
  };

  const download = async (f: AnswerFile) => {
    setBusy(f.id);
    setError("");
    try {
      const url = URL.createObjectURL(await fetchBlob(f));
      const a = document.createElement("a");
      a.href = url;
      a.download = f.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setBusy(null);
    }
  };

  const open = async (f: AnswerFile) => {
    if (f.text !== undefined && LANGUAGE[f.kind]) {
      openCode(f.label, [{ name: f.name, language: LANGUAGE[f.kind], code: f.text }]);
      return;
    }
    setBusy(f.id);
    setError("");
    try {
      const url = URL.createObjectURL(await fetchBlob(f, true));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the file.");
    } finally {
      setBusy(null);
    }
  };

  if (!files.length && !notes?.length) return null;
  return (
    <div className={styles.strip} aria-label="Files from this answer">
      {files.map((f) => (
        <div key={f.id} className={styles.file}>
          <span className={styles.icon}><KindIcon kind={f.kind} /></span>
          <span className={styles.meta}>
            <span className={styles.name} title={f.name}>{f.name}</span>
            <span className={styles.sub}>{f.label} · {size(f.size)}</span>
          </span>
          {/* Word documents cannot be shown by a browser; they are downloaded. */}
          {f.kind !== "docx" && f.kind !== "xlsx" && (
            <button type="button" className={styles.btn} onClick={() => void open(f)} disabled={busy === f.id}
              title={f.text !== undefined ? "Open in the side panel" : "Open in a new tab"} aria-label={`Open ${f.name}`}>
              <PanelRightOpen style={{ width: 14, height: 14 }} />
            </button>
          )}
          <button type="button" className={styles.btn} onClick={() => void download(f)} disabled={busy === f.id}
            title="Download" aria-label={`Download ${f.name}`}>
            {busy === f.id ? <Loader2 className={styles.spin} style={{ width: 14, height: 14 }} /> : <Download style={{ width: 14, height: 14 }} />}
          </button>
        </div>
      ))}
      {notes?.map((n) => <p key={n} className={styles.note}>{n}</p>)}
      {error && <p className={styles.error} role="alert">{error}</p>}
    </div>
  );
}

export default FilesStrip;
