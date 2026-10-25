"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Route, Sigma } from "lucide-react";
import { expectedSeconds, formatDuration } from "@/lib/routeTiming";
import { unitHints } from "@/lib/unitHints";
import { matchingCommands, type SlashCommand } from "@/lib/slashCommands";

export { SLASH_COMMANDS, applyTemplate, matchingCommands, slashQuery, type SlashCommand } from "@/lib/slashCommands";
import { MarkdownRenderer } from "./MarkdownRenderer";
import styles from "./ComposerAssist.module.css";

// -- slash commands -----------------------------------------------------------------------------------------------------

export function SlashMenu({
  query,
  active,
  onPick,
  onHover,
}: {
  query: string;
  active: number;
  onPick: (c: SlashCommand) => void;
  onHover: (i: number) => void;
}) {
  const items = matchingCommands(query);
  if (!items.length) return null;
  return (
    <ul className={styles.menu} role="listbox" aria-label="Commands">
      {items.map((c, i) => (
        <li key={c.name} role="option" aria-selected={i === active}>
          <button
            type="button"
            className={styles.menuItem}
            data-active={i === active || undefined}
            onMouseDown={(e) => {
              e.preventDefault(); // keep focus in the composer
              onPick(c);
            }}
            onMouseEnter={() => onHover(i)}
          >
            <span className={styles.cmd}>/{c.name}</span>
            <span className={styles.cmdHint}>{c.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// -- approach preview -----------------------------------------------------------------------------------------------------

interface RoutePreview {
  label: string;
  reason: string;
}

/**
 * The approach Auto would take for the draft (POST /api/route/preview, deterministic and fast) and how long such
 * answers usually take here. Updates 700 ms after typing stops.
 */
export function RoutePreviewChip({
  text,
  enabled,
  backendUrl,
  authHeaders,
}: {
  text: string;
  enabled: boolean;
  backendUrl: string;
  authHeaders: (extra?: Record<string, string>) => Record<string, string>;
}) {
  // The preview remembers the text it was computed for: a chip for an earlier text is never shown (no stale label).
  const [preview, setPreview] = useState<(RoutePreview & { query: string }) | null>(null);
  const query = text.trim();
  const active = enabled && query.length >= 12 && !query.startsWith("/");
  const headersRef = useRef(authHeaders);
  useEffect(() => {
    headersRef.current = authHeaders;
  });
  useEffect(() => {
    if (!active) return;
    const ctrl = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(`${backendUrl}/api/route/preview`, {
          method: "POST",
          headers: headersRef.current({ "Content-Type": "application/json" }),
          body: JSON.stringify({ message: query.slice(0, 8000) }),
          signal: ctrl.signal,
        });
        const body = res.ok ? await res.json().catch(() => null) : null;
        setPreview(body?.label ? { query, label: String(body.label), reason: String(body.reason || "") } : null);
      } catch {
        // a preview is a hint; no chip when the server cannot answer
        if (!ctrl.signal.aborted) setPreview(null);
      }
    }, 700);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [active, query, backendUrl]);
  if (!active || !preview || preview.query !== query) return null;
  const eta = expectedSeconds(preview.label);
  return (
    <span className={styles.route} title={preview.reason} role="status">
      <Route style={{ width: 12, height: 12 }} aria-hidden="true" />
      <span>Auto → {preview.label}</span>
      {eta ? <span className={styles.faint}>· ~{formatDuration(eta)}</span> : null}
    </span>
  );
}

// -- units -----------------------------------------------------------------------------------------------------------

/** The quantities behind the units in the draft ("N·s/m · damping coefficient"), so a wrong unit is noticed early. */
export function UnitHintsRow({ text }: { text: string }) {
  const hints = useMemo(() => unitHints(text), [text]);
  if (!hints.length) return null;
  return (
    <span className={styles.units} aria-label="Units in your question">
      {hints.map((h) => (
        <span key={h.unit} className={styles.unit} title={`${h.unit} measures ${h.quantity}`}>
          <b>{h.unit}</b> {h.quantity}
        </span>
      ))}
    </span>
  );
}

// -- LaTeX insert ------------------------------------------------------------------------------------------------------

/** A formula editor with a live preview (Ctrl+M); Insert puts $…$ (or $$…$$) at the composer's cursor. */
export function LatexInsert({ onInsert, onClose }: { onInsert: (latex: string, display: boolean) => void; onClose: () => void }) {
  const [latex, setLatex] = useState("");
  const [display, setDisplay] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const insert = () => {
    if (latex.trim()) onInsert(latex.trim(), display);
    onClose();
  };
  return (
    <div className={styles.latex} role="dialog" aria-label="Insert a formula">
      <div className={styles.latexHead}>
        <Sigma style={{ width: 13, height: 13 }} aria-hidden="true" />
        <span>Insert a formula</span>
        <label className={styles.latexToggle}>
          <input type="checkbox" checked={display} onChange={(e) => setDisplay(e.target.checked)} /> Display (own line)
        </label>
      </div>
      <textarea
        ref={ref}
        className={styles.latexInput}
        value={latex}
        placeholder="m\ddot{x} + c\dot{x} + kx = F_0\cos(\omega t)"
        onChange={(e) => setLatex(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            insert();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
        rows={2}
        spellCheck={false}
        aria-label="LaTeX"
      />
      <div className={styles.latexPreview} aria-live="polite">
        {latex.trim() ? <MarkdownRenderer content={display ? `$$${latex}$$` : `$${latex}$`} /> : <span className={styles.faint}>Preview appears here</span>}
      </div>
      <div className={styles.latexActions}>
        <span className={styles.faint}>Ctrl+Enter to insert · Esc to close</span>
        <button type="button" className={styles.btnGhost} onClick={onClose}>
          Cancel
        </button>
        <button type="button" className={styles.btn} onClick={insert} disabled={!latex.trim()}>
          Insert
        </button>
      </div>
    </div>
  );
}
