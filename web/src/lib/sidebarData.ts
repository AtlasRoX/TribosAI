// Pure logic of the sidebar (components/sidebar): recency groups, pin order, search, project membership of chats,
// and the migration of stored threads. Free of React so node tests can import it.

export interface SidebarThread {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  pinned?: boolean;
  /** The project (prj_...) the chat belongs to; absent for a chat outside any project. */
  projectId?: string;
  preview?: string;
}

export interface ThreadGroup<T extends SidebarThread = SidebarThread> {
  key: string;
  label: string;
  items: T[];
}

const PROJECT_ID_RE = /^prj_[A-Za-z0-9]{6,40}$/;
const DAY_MS = 24 * 60 * 60 * 1000;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function stamp(t: SidebarThread): number {
  const ms = Date.parse(t.updatedAt || t.createdAt);
  return Number.isFinite(ms) ? ms : 0;
}

/**
 * The recency group of a time, by calendar day in the local time zone: "Today", "Yesterday", "Previous 7 days",
 * "Previous 30 days", then the month ("October", or "October 2025" outside the current year).
 */
export function recencyGroup(ms: number, now: Date = new Date()): { key: string; label: string } {
  if (!Number.isFinite(ms) || ms <= 0) return { key: "today", label: "Today" };
  const days = Math.round((startOfDay(now) - startOfDay(new Date(ms))) / DAY_MS);
  if (days <= 0) return { key: "today", label: "Today" };
  if (days === 1) return { key: "yesterday", label: "Yesterday" };
  if (days <= 7) return { key: "7d", label: "Previous 7 days" };
  if (days <= 30) return { key: "30d", label: "Previous 30 days" };
  const d = new Date(ms);
  const label = d.getFullYear() === now.getFullYear() ? MONTHS[d.getMonth()] : `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  return { key: `m-${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, label };
}

/** Threads newest first, pinned ones on top (in their own newest-first order). */
export function orderThreads<T extends SidebarThread>(threads: T[]): T[] {
  return [...threads].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || stamp(b) - stamp(a));
}

/** The history list: a "Pinned" group first, then the recency groups in time order (empty groups left out). */
export function groupThreads<T extends SidebarThread>(threads: T[], now: Date = new Date()): ThreadGroup<T>[] {
  const ordered = orderThreads(threads);
  const groups: ThreadGroup<T>[] = [];
  const pinned = ordered.filter((t) => t.pinned);
  if (pinned.length) groups.push({ key: "pinned", label: "Pinned", items: pinned });
  for (const t of ordered.filter((x) => !x.pinned)) {
    const g = recencyGroup(stamp(t), now);
    const last = groups[groups.length - 1];
    if (last && last.key === g.key) last.items.push(t);
    else groups.push({ ...g, items: [t] });
  }
  return groups;
}

/** Chats outside any project (the main history) or in one project. */
export function threadsIn<T extends SidebarThread>(threads: T[], projectId: string | null): T[] {
  return threads.filter((t) => (projectId ? t.projectId === projectId : !t.projectId));
}

/** Threads whose title or preview contains every word of the query (case-insensitive), in sidebar order. */
export function searchThreads<T extends SidebarThread>(threads: T[], query: string): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return orderThreads(threads);
  return orderThreads(threads).filter((t) => {
    const text = `${t.title} ${t.preview || ""}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}

/** The thread moved into a project (or out of every project with null); other threads unchanged. */
export function moveThread<T extends SidebarThread>(threads: T[], id: string, projectId: string | null): T[] {
  return threads.map((t) => {
    if (t.id !== id) return t;
    const next = { ...t };
    if (projectId && PROJECT_ID_RE.test(projectId)) next.projectId = projectId;
    else delete next.projectId;
    return next;
  });
}

/**
 * Threads as stored before projects existed load unchanged: a thread without projectId stays outside every project,
 * and a malformed projectId (not prj_...) is dropped rather than sent to the server.
 */
export function migrateThreads<T extends SidebarThread>(threads: T[]): T[] {
  return threads.map((t) => {
    if (t.projectId === undefined || PROJECT_ID_RE.test(String(t.projectId))) return t;
    const next = { ...t };
    delete next.projectId;
    return next;
  });
}

/** What happens to a deleted project's chats: kept (moved out of the project) or deleted with it. */
export function afterProjectDeleted<T extends SidebarThread>(threads: T[], projectId: string, keepChats: boolean): {
  kept: T[];
  deletedIds: string[];
} {
  if (!keepChats) {
    return {
      kept: threads.filter((t) => t.projectId !== projectId),
      deletedIds: threads.filter((t) => t.projectId === projectId).map((t) => t.id),
    };
  }
  const kept = threads.map((t) => {
    if (t.projectId !== projectId) return t;
    const next = { ...t };
    delete next.projectId;
    return next;
  });
  return { kept, deletedIds: [] };
}

export const PROJECT_EMOJIS = ["🧪", "⚙️", "📐", "🔬", "🌊", "🔥", "🧲", "🛰️", "🧮", "📈", "🏗️", "🔋"] as const;
export const PROJECT_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#dc2626", "#ea580c", "#ca8a04", "#16a34a", "#0d9488"] as const;

/** A project colour from the palette, or the first one for anything else (a stored colour is never used unchecked). */
export function safeColor(color: string | undefined | null): string {
  return color && /^#[0-9a-fA-F]{6}$/.test(color) ? color : PROJECT_COLORS[0];
}
