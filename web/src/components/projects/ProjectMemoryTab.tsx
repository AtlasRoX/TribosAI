"use client";

// The project's memory: search, a review filter, approve or reject each fact with a note, edit, invalidate or delete,
// add a fact by hand, and a history drawer per fact (its versions, oldest first). Viewers read only.

import React, { useState } from "react";
import { Check, History, Plus, Search, Trash2, X } from "lucide-react";
import { useProjectResource } from "@/hooks/useProjectResource";
import { addFact, deleteFact, getFactHistory, getProjectMemory, patchFact, reviewFact } from "@/services/agentService";
import { type AuthHeaders, errorMessage } from "@/services/apiClient";
import type { FactReviewStatus, MemoryFact } from "@/types/agentic";
import styles from "./Projects.module.css";
import { ResizeHandle } from "@/components/ResizeHandle";
import { usePanelWidth } from "@/hooks/usePanelWidth";

const FILTERS: (FactReviewStatus | "all")[] = ["all", "pending", "approved", "rejected"];

function factLine(f: MemoryFact): string {
  return `${f.subject ?? ""} ${String(f.relation ?? "").replace(/_/g, " ")} ${f.object ?? ""}${f.value ? ` (${f.value})` : ""}`.trim();
}

export function ProjectMemoryTab({ backendUrl, auth, projectId, canWrite }: {
  backendUrl: string;
  auth: AuthHeaders;
  projectId: string;
  canWrite: boolean;
}) {
  const panelWidth = usePanelWidth("fact-history", { initial: 360, min: 280, max: 800 });
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [filter, setFilter] = useState<FactReviewStatus | "all">("all");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<{ id: string; object: string } | null>(null);
  const [history, setHistory] = useState<{ id: string; versions: MemoryFact[] } | null>(null);
  const [draft, setDraft] = useState({ subject: "", relation: "", object: "" });
  const [error, setError] = useState<string | null>(null);
  const facts = useProjectResource(
    () => getProjectMemory(backendUrl, auth, projectId, applied, {
      reviewStatus: filter === "all" ? undefined : filter, includeInvalid: filter === "rejected", limit: 200,
    }),
    `${projectId}|${applied}|${filter}`,
  );
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
      await facts.reload();
    } catch (err) {
      setError(errorMessage(err, "The change was not saved."));
    }
  };

  return (
    <div>
      <form className={styles.toolbar} onSubmit={(e) => { e.preventDefault(); setApplied(query); }}>
        <span className={styles.searchBox}>
          <Search style={{ width: 13, height: 13 }} aria-hidden="true" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search memory" aria-label="Search memory" />
        </span>
        <select value={filter} onChange={(e) => setFilter(e.target.value as FactReviewStatus | "all")} aria-label="Review filter">
          {FILTERS.map((f) => <option key={f} value={f}>{f === "all" ? "All facts" : f}</option>)}
        </select>
      </form>
      {error && <p className={styles.error} role="alert">{error}</p>}
      {facts.unavailable && <p className={styles.notice}>This server does not support project memory review yet.</p>}
      {facts.error && <p className={styles.error}>{facts.error}</p>}
      {canWrite && (
        <form className={styles.addFact} onSubmit={(e) => {
          e.preventDefault();
          void act(() => addFact(backendUrl, auth, projectId, draft)).then(() => setDraft({ subject: "", relation: "", object: "" }));
        }}>
          <input placeholder="Subject" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} aria-label="Subject" required />
          <input placeholder="Relation" value={draft.relation} onChange={(e) => setDraft({ ...draft, relation: e.target.value })} aria-label="Relation" required />
          <input placeholder="Object" value={draft.object} onChange={(e) => setDraft({ ...draft, object: e.target.value })} aria-label="Object" required />
          <button type="submit" className={styles.btn}><Plus style={{ width: 12, height: 12 }} /> Add fact</button>
        </form>
      )}
      <ul className={styles.items}>
        {(facts.data ?? []).map((f) => (
          <li key={f.id} className={styles.item}>
            <div className={styles.itemHead}>
              <span className={`${styles.status} ${styles[`status_${f.review_status ?? "pending"}`] ?? ""}`}>{f.review_status ?? "pending"}</span>
              {editing?.id === f.id ? (
                <input className={styles.inline} value={editing.object} autoFocus aria-label="New object"
                  onChange={(e) => setEditing({ id: f.id, object: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setEditing(null);
                    if (e.key === "Enter") void act(() => patchFact(backendUrl, auth, projectId, f.id, { object: editing.object })).then(() => setEditing(null));
                  }} />
              ) : (
                <span className={f.invalid_at ? styles.struck : undefined}>{factLine(f)}</span>
              )}
              <button type="button" className={styles.iconBtn} title="History" aria-label={`History of ${factLine(f)}`}
                onClick={() => void getFactHistory(backendUrl, auth, projectId, f.id).then(
                  (versions) => setHistory({ id: f.id, versions }), (err) => setError(errorMessage(err, "No history.")))}>
                <History style={{ width: 13, height: 13 }} />
              </button>
            </div>
            <div className={styles.itemMeta}>
              {f.written_by ? `by ${f.written_by}` : ""}{f.reviewed_by ? ` · reviewed by ${f.reviewed_by}` : ""}
              {f.review_note ? ` · “${f.review_note}”` : ""}{f.invalid_at ? " · invalidated" : ""}
            </div>
            {canWrite && !f.invalid_at && (
              <div className={styles.itemActions}>
                <input className={styles.inline} placeholder="Review note" value={notes[f.id] ?? ""} aria-label="Review note"
                  onChange={(e) => setNotes({ ...notes, [f.id]: e.target.value })} />
                <button type="button" className={styles.btn} onClick={() => void act(() => reviewFact(backendUrl, auth, projectId, f.id, "approve", notes[f.id]))}>
                  <Check style={{ width: 12, height: 12 }} /> Approve
                </button>
                <button type="button" className={styles.btn} onClick={() => void act(() => reviewFact(backendUrl, auth, projectId, f.id, "reject", notes[f.id]))}>
                  <X style={{ width: 12, height: 12 }} /> Reject
                </button>
                <button type="button" className={styles.btn} onClick={() => setEditing({ id: f.id, object: String(f.object ?? "") })}>Edit</button>
                <button type="button" className={styles.btn} onClick={() => void act(() => patchFact(backendUrl, auth, projectId, f.id, { invalidate: true, reason: notes[f.id] || undefined }))}>
                  Invalidate
                </button>
                <button type="button" className={`${styles.btn} ${styles.danger}`} aria-label="Delete fact"
                  onClick={() => window.confirm("Delete this fact and its review? Invalidating keeps it in the history.") && void act(() => deleteFact(backendUrl, auth, projectId, f.id))}>
                  <Trash2 style={{ width: 12, height: 12 }} />
                </button>
              </div>
            )}
          </li>
        ))}
        {facts.data && !facts.data.length && <li className={styles.notice}>No facts{filter !== "all" ? ` ${filter}` : ""} yet.</li>}
      </ul>
      {history && (
        <aside className={styles.drawer} aria-label="Fact history" style={{ width: panelWidth.width }}>
          <ResizeHandle edge="left" panel={panelWidth} label="Fact history width" />
          <div className={styles.itemHead}>
            <strong>History</strong>
            <button type="button" className={styles.iconBtn} onClick={() => setHistory(null)} aria-label="Close history"><X style={{ width: 13, height: 13 }} /></button>
          </div>
          <ol className={styles.items}>
            {history.versions.map((v) => (
              <li key={v.id} className={styles.item}>
                <span className={v.invalid_at ? styles.struck : undefined}>{factLine(v)}</span>
                <div className={styles.itemMeta}>{String(v.recorded_at ?? "")}{v.invalidation_reason ? ` · ${v.invalidation_reason}` : ""}</div>
              </li>
            ))}
          </ol>
        </aside>
      )}
    </div>
  );
}
