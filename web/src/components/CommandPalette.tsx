"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, FolderOpen, MessageSquare, Search } from "lucide-react";
import type { HistoryMatch, InvestigationItem } from "@/services/localStorageService";
import styles from "./CommandPalette.module.css";

export interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  /** Extra words the filter matches ("dark light mode" for the theme toggle). */
  keywords?: string;
  shortcut?: string;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  actions: PaletteAction[];
  investigations: InvestigationItem[];
  /** History search over the saved conversations (localStorageService.searchHistory). */
  search: (query: string) => HistoryMatch[];
  onOpenThread: (threadId: string, messageId?: string) => void;
  /** Projects to search by name (the sidebar's "Search chats" also finds projects). */
  projects?: { id: string; name: string; icon?: string }[];
  onOpenProject?: (projectId: string) => void;
}

type Row =
  | { kind: "action"; key: string; action: PaletteAction }
  | { kind: "project"; key: string; project: { id: string; name: string; icon?: string } }
  | { kind: "thread"; key: string; inv: InvestigationItem }
  | { kind: "match"; key: string; match: HistoryMatch };

function matches(text: string, query: string): boolean {
  const q = query.toLowerCase().split(/\s+/).filter(Boolean);
  const t = text.toLowerCase();
  return q.every((w) => t.includes(w));
}

/**
 * Ctrl+K: one box for every action (new investigation, theme, approach, cards, tour), the conversations by title,
 * and a search inside every saved message, equations included. Arrow keys move, Enter runs, Esc closes.
 */
export function CommandPalette({ open, onClose, actions, investigations, search, onOpenThread, projects = [], onOpenProject }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  const rows = useMemo<Row[]>(() => {
    const q = query.trim();
    const acts = actions.filter((a) => !q || matches(`${a.label} ${a.hint || ""} ${a.keywords || ""}`, q));
    const threads = q ? investigations.filter((i) => matches(i.title, q)).slice(0, 6) : investigations.slice(0, 5);
    const found = q.length >= 2 ? search(q).filter((m) => m.messageId).slice(0, 12) : [];
    const projectRows = q && onOpenProject ? projects.filter((p) => matches(p.name, q)).slice(0, 5) : [];
    return [
      ...acts.map((a) => ({ kind: "action" as const, key: `a:${a.id}`, action: a })),
      ...projectRows.map((p) => ({ kind: "project" as const, key: `p:${p.id}`, project: p })),
      ...threads.map((inv) => ({ kind: "thread" as const, key: `t:${inv.id}`, inv })),
      ...found.map((m, i) => ({ kind: "match" as const, key: `m:${m.threadId}:${m.messageId}:${i}`, match: m })),
    ];
  }, [query, actions, investigations, search, projects, onOpenProject]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const runRow = (row: Row | undefined) => {
    if (!row) return;
    onClose();
    if (row.kind === "action") row.action.run();
    else if (row.kind === "project") onOpenProject?.(row.project.id);
    else if (row.kind === "thread") onOpenThread(row.inv.id);
    else onOpenThread(row.match.threadId, row.match.messageId);
  };

  const heading = (i: number): string | null => {
    const kind = rows[i].kind;
    if (i > 0 && rows[i - 1].kind === kind) return null;
    return kind === "action" ? "Actions" : kind === "project" ? "Projects" : kind === "thread" ? "Conversations" : "In your messages";
  };

  return (
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        className={styles.palette}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className={styles.inputRow}>
          <Search style={{ width: 15, height: 15 }} aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(rows.length - 1, a + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(0, a - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                runRow(rows[active]);
              } else if (e.key === "Escape") {
                e.preventDefault();
                onClose();
              }
            }}
            placeholder="Type a command, or search conversations and equations…"
            aria-label="Search commands and conversations"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={rows[active] ? `palette-${active}` : undefined}
          />
          <kbd className={styles.kbd}>Esc</kbd>
        </div>
        <ul ref={listRef} id="palette-list" className={styles.list} role="listbox">
          {rows.length === 0 && <li className={styles.empty}>Nothing matches “{query}”.</li>}
          {rows.map((row, i) => (
            <React.Fragment key={row.key}>
              {heading(i) && <li className={styles.group} role="presentation">{heading(i)}</li>}
              <li
                id={`palette-${i}`}
                data-index={i}
                role="option"
                aria-selected={i === active}
                className={styles.row}
                data-active={i === active || undefined}
                onMouseMove={() => setActive(i)}
                onClick={() => runRow(row)}
              >
                {row.kind === "action" && (
                  <>
                    <span className={styles.label}>{row.action.label}</span>
                    {row.action.hint && <span className={styles.hint}>{row.action.hint}</span>}
                    {row.action.shortcut && <kbd className={styles.kbd}>{row.action.shortcut}</kbd>}
                  </>
                )}
                {row.kind === "project" && (
                  <>
                    <FolderOpen style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden="true" />
                    <span className={styles.label}>{row.project.icon ? `${row.project.icon} ` : ""}{row.project.name}</span>
                  </>
                )}
                {row.kind === "thread" && (
                  <>
                    <MessageSquare style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden="true" />
                    <span className={styles.label}>{row.inv.title}</span>
                    {row.inv.pinned && <span className={styles.hint}>pinned</span>}
                  </>
                )}
                {row.kind === "match" && (
                  <span className={styles.match}>
                    <span className={styles.matchTitle}>
                      {row.match.title} · {row.match.sender === "user" ? "your question" : "answer"}
                    </span>
                    <span className={styles.snippet}>{row.match.snippet}</span>
                  </span>
                )}
                {i === active && <CornerDownLeft className={styles.enter} style={{ width: 12, height: 12 }} aria-hidden="true" />}
              </li>
            </React.Fragment>
          ))}
        </ul>
      </div>
    </div>
  );
}
