"use client";

// One conversation in the sidebar: select it, or open its "…" menu to rename it inline, pin it, move it to a project,
// export it or delete it (after a confirmation). The menu closes on Esc or an outside click.

import React, { useEffect, useRef, useState } from "react";
import { Download, Edit2, FolderInput, FolderMinus, MoreHorizontal, Pin, PinOff, Trash2 } from "lucide-react";
import type { InvestigationItem } from "@/services/localStorageService";
import type { Project } from "@/types/agentic";
import styles from "./Sidebar.module.css";

export interface ChatRowHandlers {
  onSelect: (inv: InvestigationItem) => void;
  onRename: (id: string, title: string) => void;
  onTogglePin: (inv: InvestigationItem) => void;
  onMove: (id: string, projectId: string | null) => void;
  onExport: (inv: InvestigationItem) => void;
  onDelete: (id: string) => void;
}

export function ChatRow({ inv, active, running, projects, indent, handlers }: {
  inv: InvestigationItem;
  active: boolean;
  running: boolean;
  projects: Project[];
  indent?: boolean;
  handlers: ChatRowHandlers;
}) {
  const [menu, setMenu] = useState(false);
  const [moving, setMoving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(inv.title);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setMenu(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const close = () => {
    setMenu(false);
    setMoving(false);
  };
  const save = () => {
    if (title.trim() && title.trim() !== inv.title) handlers.onRename(inv.id, title.trim());
    setEditing(false);
  };
  const writable = projects.filter((p) => p.role !== "viewer");

  return (
    <div ref={boxRef} className={`${styles.row} ${active ? styles.rowActive : ""} ${indent ? styles.indent : ""}`}>
      {editing ? (
        <input
          className={styles.renameInput}
          value={title}
          autoFocus
          aria-label="Conversation title"
          onChange={(e) => setTitle(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") {
              setTitle(inv.title);
              setEditing(false);
            }
          }}
        />
      ) : (
        <button type="button" className={styles.rowMain} onClick={() => handlers.onSelect(inv)} title={inv.title}
          aria-current={active ? "page" : undefined}>
          {inv.pinned && <Pin style={{ width: 11, height: 11, opacity: 0.7, flexShrink: 0 }} aria-label="Pinned" />}
          <span className={styles.rowTitle}>{inv.title}{running ? " · running" : ""}</span>
        </button>
      )}
      {!editing && (
        <button type="button" className={`${styles.iconBtn} ${styles.rowMenuBtn} ${menu ? styles.rowMenuBtnOpen : ""}`}
          style={{ width: 26, height: 26 }} onClick={() => setMenu((m) => !m)} aria-label={`Options for ${inv.title}`}
          aria-haspopup="menu" aria-expanded={menu}>
          <MoreHorizontal style={{ width: 14, height: 14 }} />
        </button>
      )}
      {menu && (
        <div className={styles.menu} role="menu">
          {moving ? (
            <>
              <div className={styles.menuLabel}>Move to project</div>
              {writable.map((p) => (
                <button key={p.id} type="button" role="menuitem" className={styles.menuItem}
                  disabled={p.id === inv.projectId} onClick={() => { handlers.onMove(inv.id, p.id); close(); }}>
                  <span aria-hidden="true">{p.icon || "📁"}</span> {p.name}
                </button>
              ))}
              {!writable.length && <div className={styles.empty}>No project you can add chats to.</div>}
              {inv.projectId && (
                <button type="button" role="menuitem" className={styles.menuItem}
                  onClick={() => { handlers.onMove(inv.id, null); close(); }}>
                  <FolderMinus style={{ width: 12, height: 12 }} /> Remove from project
                </button>
              )}
            </>
          ) : (
            <>
              <button type="button" role="menuitem" className={styles.menuItem}
                onClick={() => { setTitle(inv.title); setEditing(true); close(); }}>
                <Edit2 style={{ width: 12, height: 12 }} /> Rename
              </button>
              <button type="button" role="menuitem" className={styles.menuItem}
                onClick={() => { handlers.onTogglePin(inv); close(); }}>
                {inv.pinned ? <PinOff style={{ width: 12, height: 12 }} /> : <Pin style={{ width: 12, height: 12 }} />}
                {inv.pinned ? "Unpin" : "Pin"}
              </button>
              {projects.length > 0 && (
                <button type="button" role="menuitem" className={styles.menuItem} onClick={() => setMoving(true)}>
                  <FolderInput style={{ width: 12, height: 12 }} /> Move to project
                </button>
              )}
              <button type="button" role="menuitem" className={styles.menuItem}
                onClick={() => { handlers.onExport(inv); close(); }}>
                <Download style={{ width: 12, height: 12 }} /> Export
              </button>
              <button type="button" role="menuitem" className={`${styles.menuItem} ${styles.menuDanger}`}
                onClick={() => { close(); handlers.onDelete(inv.id); }}>
                <Trash2 style={{ width: 12, height: 12 }} /> Delete
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
