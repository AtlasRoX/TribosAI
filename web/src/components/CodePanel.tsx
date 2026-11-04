"use client";

/**
 * The right-hand code panel (like Claude's artifact view): opens beside the chat, which narrows to make room.
 * Tabs for several files (a Python session's cells, a Lean file and its lemmas), line numbers, copy, download,
 * Esc or the close button to dismiss. State lives in lib/codePanel.ts.
 */
import { Check, Copy, Download, FileCode2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { closeCode, extensionFor, selectFile, useCodePanel } from "@/lib/codePanel";

import { ResizeHandle } from "@/components/ResizeHandle";
import { usePanelWidth } from "@/hooks/usePanelWidth";
import styles from "./CodePanel.module.css";

export function CodePanel() {
  const { open, title, files, active } = useCodePanel();
  const panel = usePanelWidth("code-panel", { initial: 640, min: 360, max: 1200, maxViewport: 0.7 });
  const [copied, setCopied] = useState(false);
  const file = files[active];

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeCode();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => setCopied(false), [active, files]);

  const lines = useMemo(() => (file ? file.code.replace(/\n$/, "").split("\n") : []), [file]);

  const copy = async () => {
    if (!file) return;
    try {
      await navigator.clipboard.writeText(file.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable: nothing to do */
    }
  };

  const download = () => {
    if (!file) return;
    const name = /\.\w+$/.test(file.name) ? file.name : `${file.name}.${extensionFor(file.language)}`;
    const url = URL.createObjectURL(new Blob([file.code], { type: "text/plain;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name.replace(/[^\w.-]+/g, "_") });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside className={`${styles.panel} ${open ? styles.open : ""}`} aria-hidden={!open} aria-label="Code panel"
      style={open ? { width: panel.width } : undefined}>
      {open && file && <ResizeHandle edge="left" panel={panel} label="Code panel width" />}
      {open && file && (
        <div className={styles.inner} style={{ width: panel.width }}>
          <header className={styles.header}>
            <FileCode2 className={styles.titleIcon} aria-hidden />
            <div className={styles.titleText} title={title}>{title}</div>
            <button type="button" className={styles.iconBtn} onClick={copy} title="Copy">
              {copied ? <Check className={styles.ok} /> : <Copy />}
            </button>
            <button type="button" className={styles.iconBtn} onClick={download} title="Download">
              <Download />
            </button>
            <button type="button" className={styles.iconBtn} onClick={closeCode} title="Close (Esc)">
              <X />
            </button>
          </header>
          {files.length > 1 && (
            <nav className={styles.tabs} role="tablist">
              {files.map((f, i) => (
                <button key={`${f.name}-${i}`} type="button" role="tab" aria-selected={i === active}
                  className={`${styles.tab} ${i === active ? styles.tabActive : ""}`} onClick={() => selectFile(i)}>
                  {f.name}
                </button>
              ))}
            </nav>
          )}
          <div className={styles.meta}>
            <span>{file.language}</span>
            <span>{lines.length} line{lines.length === 1 ? "" : "s"}</span>
          </div>
          <div className={styles.body}>
            <pre className={styles.code}>
              {lines.map((line, i) => (
                <div key={i} className={styles.line}>
                  <span className={styles.lineNo} aria-hidden>{i + 1}</span>
                  <code>{line || " "}</code>
                </div>
              ))}
            </pre>
            {file.output !== undefined && (
              <section className={styles.output}>
                <div className={styles.outputLabel}>Output</div>
                <pre>{file.output || "(nothing printed)"}</pre>
              </section>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
