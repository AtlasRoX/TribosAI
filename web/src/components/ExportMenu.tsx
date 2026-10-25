"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Archive, Check, ChevronDown, ClipboardCopy, Download, FileCode2, FileText, FileType, Loader2, Sigma } from "lucide-react";

import styles from "@/components/Export.module.css";
import { exportMessage } from "@/services/exportService";
import type { Message } from "@/types/chat";
import type { ExportFormat } from "@/types/runs";
import { latexDocument, markdownToLatex } from "@/lib/markdownToLatex";
import { makeZip } from "@/lib/zip";
import { trajectoryCsv } from "@/components/ReproductionFiles";

export interface ExportMenuProps {
  message: Message;
  question: string;
  backendUrl: string;
  authHeaders: (extra?: Record<string, string>) => Record<string, string>;
  disabled?: boolean;
}

type ServerKey = Exclude<ExportFormat, "bundle">;
type ClientKey = "copy-md" | "copy-rich" | "copy-latex" | "zip";
type ItemKey = ServerKey | ClientKey;

// The reproducibility bundle stays available from the API (POST /api/export/bundle) for scripted use. The copy and
// zip items run in the browser: nothing is uploaded.
const ITEMS: { key: ItemKey; label: string; hint?: string; Icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "pdf", label: "PDF", hint: ".pdf", Icon: FileType },
  { key: "docx", label: "Word document", hint: ".docx", Icon: FileText },
  { key: "md", label: "Markdown", hint: ".md", Icon: FileCode2 },
  { key: "zip", label: "Everything", hint: ".zip", Icon: Archive },
  { key: "copy-md", label: "Copy as Markdown", Icon: ClipboardCopy },
  { key: "copy-rich", label: "Copy for Word or Docs", Icon: ClipboardCopy },
  { key: "copy-latex", label: "Copy as LaTeX", Icon: Sigma },
];
const SERVER_KEYS: ItemKey[] = ["pdf", "docx", "md"];

function save(data: BlobPart, type: string, name: string) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function fileStem(question: string): string {
  return (question || "tribos-answer").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "tribos-answer";
}

/** The answer as rendered (KaTeX carries MathML, which Word turns into equations) for a rich-text paste. */
function renderedHtml(messageId: string): string | null {
  const root = document.querySelector(`[data-message-id="${CSS.escape(messageId)}"] .markdown-content`);
  if (!root) return null;
  const clone = root.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(".katex-html, .math-copy, button").forEach((el) => el.remove()); // keep the MathML only
  return `<html><body>${clone.innerHTML}</body></html>`;
}

async function runClient(key: ClientKey, message: Message, question: string): Promise<void> {
  const md = message.content || "";
  if (key === "copy-md") return navigator.clipboard.writeText(md);
  if (key === "copy-latex") return navigator.clipboard.writeText(markdownToLatex(md));
  if (key === "copy-rich") {
    const html = renderedHtml(message.id);
    if (html && typeof ClipboardItem !== "undefined") {
      await navigator.clipboard.write([
        new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([md], { type: "text/plain" }) }),
      ]);
      return;
    }
    return navigator.clipboard.writeText(md);
  }
  // zip: the report (Markdown and LaTeX), the question, the reproduction script, the trajectory and the run's data.
  const arts = (message.execution_artifacts || {}) as Record<string, any>;
  const stem = fileStem(question);
  const files: { name: string; content: string }[] = [
    { name: "question.txt", content: question + "\n" },
    { name: "answer.md", content: md },
    { name: "answer.tex", content: latexDocument(question || "Tribos answer", markdownToLatex(md)) },
  ];
  const script = arts.ode_verification?.script;
  if (typeof script === "string" && script.trim()) files.push({ name: "verify_solution.py", content: script });
  const sim = arts.dynamis ?? arts.vivarix;
  const csv = sim ? trajectoryCsv(sim) : null;
  if (csv) files.push({ name: "trajectory.csv", content: csv });
  const data = {
    question,
    framework: message.framework_used,
    routing: arts.framework_routing ?? null,
    verification: message.verification_report ?? null,
    ode_verification: arts.ode_verification ? { ...arts.ode_verification, script: undefined } : null,
    math: arts.math_agent ?? null,
    citations: message.citations ?? null,
  };
  files.push({ name: "run.json", content: JSON.stringify(data, null, 2) });
  const zip = makeZip(files.map((f) => ({ name: `${stem}/${f.name}`, content: f.content })));
  save(zip as BlobPart, "application/zip", `${stem}.zip`);
}

/** "Export" action: a small menu that downloads the answer as a report rendered by the backend. */
export function ExportMenu({ message, question, backendUrl, authHeaders, disabled = false }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ItemKey | null>(null);
  const [errors, setErrors] = useState<Partial<Record<ItemKey, string>>>({});
  const [done, setDone] = useState<ItemKey | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  const close = useCallback((focusTrigger = false) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onPointer);
    const first = itemRefs.current.find((el) => el && !el.disabled);
    first?.focus();
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open, close]);

  const run = async (key: ItemKey) => {
    if (busy) return;
    setBusy(key);
    setErrors((prev) => ({ ...prev, [key]: undefined }));
    try {
      if (SERVER_KEYS.includes(key)) {
        await exportMessage(key as ServerKey, { question, message }, backendUrl, authHeaders());
      } else {
        await runClient(key as ClientKey, message, question);
        setDone(key);
        window.setTimeout(() => setDone((d) => (d === key ? null : d)), 1600);
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : "Export failed";
      setErrors((prev) => ({ ...prev, [key]: text }));
    } finally {
      setBusy(null);
    }
  };

  const onMenuKeyDown = (e: React.KeyboardEvent) => {
    const items = itemRefs.current.filter((el): el is HTMLButtonElement => !!el && !el.disabled);
    const idx = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(idx + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(idx - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      items[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      items[items.length - 1]?.focus();
    } else if (e.key === "Tab") {
      close();
    }
  };

  return (
    <div className={styles.menuWrap} ref={wrapRef}>
      <button
        ref={triggerRef}
        type="button"
        className="msg-action-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        title={disabled ? "Nothing to export for this message" : "Export this answer"}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Download style={{ width: 13, height: 13 }} aria-hidden="true" /> Export
        <ChevronDown className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label="Export answer" className={styles.menu} onKeyDown={onMenuKeyDown}>
          {ITEMS.map(({ key, label, hint, Icon }, i) => (
            <React.Fragment key={key}>
              <button
                ref={(el) => {
                  itemRefs.current[i] = el;
                }}
                type="button"
                role="menuitem"
                className={styles.menuItem}
                disabled={busy !== null && busy !== key}
                aria-busy={busy === key}
                onClick={() => run(key)}
              >
                {busy === key ? (
                  <Loader2 className={`${styles.menuIcon} ${styles.spin}`} aria-hidden="true" />
                ) : done === key ? (
                  <Check className={styles.menuIcon} aria-hidden="true" />
                ) : (
                  <Icon className={styles.menuIcon} aria-hidden="true" />
                )}
                <span>{done === key ? (key === "zip" ? "Downloaded" : "Copied") : label}</span>
                {hint && <span className={styles.menuHint}>{hint}</span>}
              </button>
              {errors[key] && (
                <div className={styles.menuError} role="alert">
                  {errors[key]}
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
