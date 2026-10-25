"use client";

// One project: its header (icon, name, role, edit and delete), and tabs for its Chats, Instructions, Files, Memory,
// Members and Activity. Viewers see a read-only version; a part the server does not support is hidden with a notice.
// Deleting the project asks whether to keep its chats (moved out of the project) or delete them with it.

import React, { useState } from "react";
import { Pencil, Plus, Trash2, UserMinus, X } from "lucide-react";
import { useProjectResource } from "@/hooks/useProjectResource";
import { safeColor, threadsIn } from "@/lib/sidebarData";
import {
  addProjectFile, addProjectMember, getProjectActivity, listProjectFiles, listProjectMembers, removeProjectFile,
  removeProjectMember, updateProjectMemberRole,
} from "@/services/agentService";
import { type AuthHeaders, errorMessage } from "@/services/apiClient";
import { listDatasets } from "@/services/datasetService";
import type { InvestigationItem } from "@/services/localStorageService";
import type { Project, ProjectPatchInput } from "@/types/agentic";
import { ProjectMemoryTab } from "./ProjectMemoryTab";
import styles from "./Projects.module.css";

const TABS = ["Chats", "Instructions", "Files", "Memory", "Members", "Activity"] as const;
type Tab = (typeof TABS)[number];

export interface ProjectViewProps {
  project: Project;
  backendUrl: string;
  auth: AuthHeaders;
  currentUser?: string;
  threads: InvestigationItem[];
  onOpenChat: (inv: InvestigationItem) => void;
  onNewChat: () => void;
  onEdit: () => void;
  onUpdate: (patch: ProjectPatchInput) => Promise<unknown>;
  onDelete: (keepChats: boolean) => Promise<void>;
  onLeft: () => void;
  onClose: () => void;
}

function Unavailable({ what }: { what: string }) {
  return <p className={styles.notice}>This server does not support {what} yet.</p>;
}

function InstructionsTab({ project, canWrite, onUpdate }: Pick<ProjectViewProps, "project" | "onUpdate"> & { canWrite: boolean }) {
  const [text, setText] = useState(project.instructions ?? "");
  const [status, setStatus] = useState<string | null>(null);
  if (!canWrite) {
    return project.instructions ? <pre className={styles.pre}>{project.instructions}</pre> : <p className={styles.notice}>No instructions.</p>;
  }
  return (
    <form onSubmit={(e) => {
      e.preventDefault();
      onUpdate({ instructions: text }).then(() => setStatus("Saved."), (err) => setStatus(errorMessage(err, "Not saved.")));
    }}>
      <p className={styles.hint}>Added to every chat in this project, as guidance from its members.</p>
      <textarea className={styles.textarea} rows={8} maxLength={8000} value={text} onChange={(e) => setText(e.target.value)}
        aria-label="Project instructions" />
      <div className={styles.dialogButtons}>
        {status && <span className={styles.hint} role="status">{status}</span>}
        <button type="submit" className={styles.btnPrimary}>Save instructions</button>
      </div>
    </form>
  );
}

function FilesTab({ backendUrl, auth, projectId, canWrite }: { backendUrl: string; auth: AuthHeaders; projectId: string; canWrite: boolean }) {
  const files = useProjectResource(() => listProjectFiles(backendUrl, auth, projectId), `files|${projectId}`);
  const library = useProjectResource(() => (canWrite ? listDatasets(backendUrl, auth) : Promise.resolve([])), `lib|${canWrite}`);
  const [pick, setPick] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (files.unavailable) return <Unavailable what="project files" />;
  const shared = new Set((files.data ?? []).map((f) => f.dataset_id));
  const act = (fn: () => Promise<unknown>) => fn().then(() => { setError(null); return files.reload(); }, (err) => setError(errorMessage(err, "Not saved.")));
  return (
    <div>
      <p className={styles.hint}>Files here are attached to every chat in the project (other members read them, never change them).</p>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <ul className={styles.items}>
        {(files.data ?? []).map((f) => (
          <li key={f.dataset_id} className={styles.itemHead}>
            <span>{f.name || f.dataset_id}</span>
            <span className={styles.itemMeta}>{f.kind}{f.added_by ? ` · added by ${f.added_by}` : ""}</span>
            {canWrite && (
              <button type="button" className={styles.iconBtn} aria-label={`Remove ${f.name || f.dataset_id}`}
                onClick={() => void act(() => removeProjectFile(backendUrl, auth, projectId, f.dataset_id))}>
                <X style={{ width: 13, height: 13 }} />
              </button>
            )}
          </li>
        ))}
        {files.data && !files.data.length && <li className={styles.notice}>No files yet.</li>}
      </ul>
      {canWrite && (
        <form className={styles.toolbar} onSubmit={(e) => { e.preventDefault(); if (pick) void act(() => addProjectFile(backendUrl, auth, projectId, pick)); }}>
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Dataset from your library">
            <option value="">Add one of your uploads…</option>
            {(library.data ?? []).filter((d) => !shared.has(d.id)).map((d) => <option key={d.id} value={d.id}>{d.display_name}</option>)}
          </select>
          <button type="submit" className={styles.btn} disabled={!pick}><Plus style={{ width: 12, height: 12 }} /> Add</button>
        </form>
      )}
    </div>
  );
}

function MembersTab({ backendUrl, auth, project, currentUser, onLeft }: {
  backendUrl: string; auth: AuthHeaders; project: Project; currentUser?: string; onLeft: () => void;
}) {
  const members = useProjectResource(() => listProjectMembers(backendUrl, auth, project.id), `members|${project.id}`);
  const [user, setUser] = useState("");
  const [role, setRole] = useState<"editor" | "viewer">("viewer");
  const [error, setError] = useState<string | null>(null);
  if (members.unavailable) return <Unavailable what="project members" />;
  const owner = project.role === "owner";
  const act = (fn: () => Promise<unknown>) => fn().then(() => { setError(null); return members.reload(); }, (err) => setError(errorMessage(err, "Not saved.")));
  return (
    <div>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <ul className={styles.items}>
        {(members.data ?? []).map((m) => (
          <li key={m.user_id} className={styles.itemHead}>
            <span>{m.user_id}{m.user_id === currentUser ? " (you)" : ""}</span>
            {owner && m.role !== "owner" ? (
              <select value={m.role} aria-label={`Role of ${m.user_id}`}
                onChange={(e) => void act(() => updateProjectMemberRole(backendUrl, auth, project.id, m.user_id, e.target.value as "editor" | "viewer"))}>
                <option value="editor">editor</option>
                <option value="viewer">viewer</option>
              </select>
            ) : <span className={styles.itemMeta}>{m.role}</span>}
            {owner && m.role !== "owner" && (
              <button type="button" className={styles.iconBtn} aria-label={`Remove ${m.user_id}`}
                onClick={() => window.confirm(`Remove ${m.user_id} from the project?`) && void act(() => removeProjectMember(backendUrl, auth, project.id, m.user_id))}>
                <UserMinus style={{ width: 13, height: 13 }} />
              </button>
            )}
          </li>
        ))}
      </ul>
      {owner ? (
        <form className={styles.toolbar} onSubmit={(e) => {
          e.preventDefault();
          if (user.trim()) void act(() => addProjectMember(backendUrl, auth, project.id, user.trim(), role)).then(() => setUser(""));
        }}>
          <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="User id" aria-label="User id to add" />
          <select value={role} onChange={(e) => setRole(e.target.value as "editor" | "viewer")} aria-label="Role">
            <option value="viewer">viewer</option>
            <option value="editor">editor</option>
          </select>
          <button type="submit" className={styles.btn}><Plus style={{ width: 12, height: 12 }} /> Add member</button>
        </form>
      ) : currentUser ? (
        <button type="button" className={styles.btn} onClick={() => window.confirm("Leave this project?") &&
          removeProjectMember(backendUrl, auth, project.id, currentUser).then(onLeft, (err) => setError(errorMessage(err, "Could not leave.")))}>
          Leave project
        </button>
      ) : null}
    </div>
  );
}

function ActivityTab({ backendUrl, auth, projectId }: { backendUrl: string; auth: AuthHeaders; projectId: string }) {
  const events = useProjectResource(() => getProjectActivity(backendUrl, auth, projectId, 50), `activity|${projectId}`);
  if (events.unavailable) return <Unavailable what="the project activity log" />;
  return (
    <ul className={styles.items}>
      {(events.data ?? []).map((e) => (
        <li key={e.id} className={styles.item}>
          <span><strong>{e.actor}</strong> {e.action.replace(".", " ")}{e.summary ? `: ${e.summary}` : ""}</span>
          <div className={styles.itemMeta}>{String(e.at)}</div>
        </li>
      ))}
      {events.data && !events.data.length && <li className={styles.notice}>No activity yet.</li>}
    </ul>
  );
}

export function ProjectView(props: ProjectViewProps) {
  const { project, backendUrl, auth } = props;
  const [tab, setTab] = useState<Tab>("Chats");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const canWrite = project.role !== "viewer";
  const chats = threadsIn(props.threads, project.id);
  const color = safeColor(project.color);

  return (
    <section className={styles.view} aria-label={`Project ${project.name}`}>
      <header className={styles.viewHead}>
        <span className={styles.bigIcon} style={{ background: `${color}22`, color }} aria-hidden="true">{project.icon || "📁"}</span>
        <div style={{ minWidth: 0 }}>
          <h1 className={styles.viewTitle}>{project.name}</h1>
          <div className={styles.itemMeta}>
            {project.role ?? "owner"}{project.role === "viewer" ? " · read-only" : ""}
            {project.member_count ? ` · ${project.member_count} member${project.member_count === 1 ? "" : "s"}` : ""}
            {project.pending_review_count ? ` · ${project.pending_review_count} fact${project.pending_review_count === 1 ? "" : "s"} to review` : ""}
          </div>
        </div>
        <div className={styles.headButtons}>
          {canWrite && <button type="button" className={styles.btn} onClick={props.onEdit}><Pencil style={{ width: 12, height: 12 }} /> Edit</button>}
          {project.role === "owner" && (
            <button type="button" className={`${styles.btn} ${styles.danger}`} onClick={() => setConfirmDelete(true)}>
              <Trash2 style={{ width: 12, height: 12 }} /> Delete
            </button>
          )}
          <button type="button" className={styles.iconBtn} onClick={props.onClose} aria-label="Close project"><X style={{ width: 15, height: 15 }} /></button>
        </div>
      </header>
      {confirmDelete && (
        <div className={styles.confirm} role="alertdialog" aria-label="Delete project">
          <p>Delete <strong>{project.name}</strong> with its memory, files list and members? Its {chats.length} chat{chats.length === 1 ? "" : "s"} on this device:</p>
          <div className={styles.dialogButtons}>
            <button type="button" className={styles.btn} onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button type="button" className={styles.btn} onClick={() => void props.onDelete(true)}>Delete project, keep chats</button>
            <button type="button" className={`${styles.btnPrimary} ${styles.danger}`} onClick={() => void props.onDelete(false)}>Delete project and chats</button>
          </div>
        </div>
      )}
      {project.description && <p className={styles.hint}>{project.description}</p>}
      <div className={styles.tabs} role="tablist" aria-label="Project sections">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? styles.tabOn : styles.tab} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={tab}>
        {tab === "Chats" && (
          <div>
            {canWrite && <button type="button" className={styles.btnPrimary} onClick={props.onNewChat}><Plus style={{ width: 12, height: 12 }} /> New chat in this project</button>}
            <ul className={styles.items}>
              {chats.map((inv) => (
                <li key={inv.id}>
                  <button type="button" className={styles.chatLink} onClick={() => props.onOpenChat(inv)}>
                    <span>{inv.title}</span>
                    <span className={styles.itemMeta}>{inv.preview}</span>
                  </button>
                </li>
              ))}
              {!chats.length && <li className={styles.notice}>No chats in this project on this device yet.</li>}
            </ul>
          </div>
        )}
        {tab === "Instructions" && <InstructionsTab project={project} canWrite={canWrite} onUpdate={props.onUpdate} />}
        {tab === "Files" && <FilesTab backendUrl={backendUrl} auth={auth} projectId={project.id} canWrite={canWrite} />}
        {tab === "Memory" && <ProjectMemoryTab backendUrl={backendUrl} auth={auth} projectId={project.id} canWrite={canWrite} />}
        {tab === "Members" && <MembersTab backendUrl={backendUrl} auth={auth} project={project} currentUser={props.currentUser} onLeft={props.onLeft} />}
        {tab === "Activity" && <ActivityTab backendUrl={backendUrl} auth={auth} projectId={project.id} />}
      </div>
    </section>
  );
}

export default ProjectView;
