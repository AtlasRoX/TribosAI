"use client";

// A labelled identifier ("Conversation ID", "Research ID") that copies itself on click, for quoting a chat or a
// research project in a bug report, an API call (GET /api/campaigns/{id}) or a note.

import React, { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import styles from "./IdChip.module.css";

export function IdChip({ label, id, className }: { label: string; id: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
    } catch {
      // Clipboard blocked (insecure origin): select-and-copy by hand still works on the visible text.
    }
  };

  return (
    <button type="button" className={`${styles.chip} ${className ?? ""}`} onClick={() => void copy()}
      title={`${label}: ${id} (click to copy)`} aria-label={`Copy ${label} ${id}`}>
      <span className={styles.label}>{label}</span>
      <code className={styles.id}>{id}</code>
      {copied
        ? <Check className={styles.icon} aria-hidden="true" />
        : <Copy className={styles.icon} aria-hidden="true" />}
      <span className={styles.live} aria-live="polite">{copied ? "Copied" : ""}</span>
    </button>
  );
}

export default IdChip;
