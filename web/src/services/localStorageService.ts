/**
 * Tribos Local Storage Service
 * Persistence for investigations (threads), chat message histories and user preferences in the browser.
 *
 * Privacy (UI-007): conversations can hold research details, so history is
 * - namespaced by backend origin + a fingerprint of the access token, so another user (token) or another backend on
 *   the same browser never sees or deletes this history;
 * - kept where the user chose: on this device (localStorage), for this browser session only (sessionStorage), or not
 *   at all (memory of the open tab);
 * - pruned after a retention period (default 30 days) unless the user keeps it indefinitely.
 *
 * Quota (UI-008): when a thread does not fit, messages are slimmed and, as a last resort, an old thread's messages are
 * removed. Every such step is reported (return value + listeners) and marked on the data, never silent.
 *
 * Imports are relative (value imports with an explicit `.ts`), so `node --test` can load this module with a fake
 * `window`.
 */

import type { Message } from "../types/chat";
import type { AgentOptionsSettings } from "../types/agentic";
import { normalizeLegacyAgentName } from "../lib/legacyNames.ts";
import { afterProjectDeleted, migrateThreads, moveThread } from "../lib/sidebarData.ts";

export interface InvestigationItem {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  framework?: string;
  model?: string;
  messageCount: number;
  preview?: string;
  /** True when the user explicitly renamed this investigation manually */
  isCustomTitle?: boolean;
  /** Set when this thread's messages were removed to free browser storage (UI-008). */
  messagesPruned?: boolean;
  /** Pinned by the user: listed above the others. */
  pinned?: boolean;
  /** The research project (prj_...) the chat belongs to; its questions are sent with this project_id. */
  projectId?: string;
}

/** One match of a history search: the conversation, the message and a snippet around the match. */
export interface HistoryMatch {
  threadId: string;
  title: string;
  messageId: string;
  sender: "user" | "assistant";
  snippet: string;
}

export interface UserSettings {
  apiKey?: string;
  selectedModel?: string;
  selectedFramework?: string;
  isWebSearchEnabled?: boolean;
  theme?: "dark" | "light";
  /** Agentic request settings (agent_options); normalised on read by agentService.normalizeAgentOptions. */
  agentOptions?: AgentOptionsSettings;
  /** Selected research project (prj_...), sent as project_id with agentic requests. */
  projectId?: string;
}

/** Where conversation history is kept. */
export type HistoryMode = "device" | "session" | "off";

export interface HistoryPrefs {
  mode: HistoryMode;
  /** Investigations not updated for this many days are removed; 0 keeps them until cleared. */
  retentionDays: number;
}

export const DEFAULT_HISTORY_PREFS: HistoryPrefs = { mode: "device", retentionDays: 30 };

/** What a save did; anything but "full" lost data that the reader should be told about (UI-008). */
export interface SaveResult {
  saved: boolean;
  /** full: everything kept; slim: diagnostics (manifest, query context, source list) dropped; no_plots: plots and
   * citation passage text dropped too. */
  level: "full" | "slim" | "no_plots" | "none";
  /** Investigations whose saved messages were removed to make room. */
  prunedThreadIds: string[];
}

export interface StorageNotice {
  kind: "slimmed" | "pruned" | "not_saved" | "expired";
  message: string;
  threadIds: string[];
}

const STORAGE_KEYS = {
  INVESTIGATIONS: "tribos_investigations_v2",
  ACTIVE_THREAD: "tribos_active_thread_id_v2",
  THREAD_MESSAGES_PREFIX: "tribos_thread_messages_v2_",
  SETTINGS: "tribos_user_settings_v2",
  HISTORY_PREFS: "tribos_history_prefs_v1",
  DRAFT_PREFIX: "tribos_draft_v1_",
};

/** Key prefix of the release before the rename (phronesis -> tribos): "phronesis_*" and "phronesis-*" keys. */
const LEGACY_PREFIX = "phronesis";

/**
 * One-time rename migration (CI-6 / SUP-8): copies every "phronesis_*" / "phronesis-*" key (history, settings,
 * drafts, access token, backend URL, theme) to its "tribos_*" / "tribos-*" name, never overwriting a value the
 * current version already saved, then deletes the old key so it stops using quota. Returns the migrated new keys.
 * Storage that throws (private mode, blocked) is left alone.
 */
export function migrateLegacyKeys(storage: KV | null | undefined): string[] {
  const migrated: string[] = [];
  if (!storage) return migrated;
  try {
    const legacy: string[] = [];
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key && (key.startsWith(`${LEGACY_PREFIX}_`) || key.startsWith(`${LEGACY_PREFIX}-`) || key === `__${LEGACY_PREFIX}_storage_test__`)) {
        legacy.push(key);
      }
    }
    for (const oldKey of legacy) {
      try {
        const value = storage.getItem(oldKey);
        if (oldKey.startsWith(`${LEGACY_PREFIX}_`) || oldKey.startsWith(`${LEGACY_PREFIX}-`)) {
          const newKey = `tribos${oldKey.slice(LEGACY_PREFIX.length)}`;
          if (value !== null && storage.getItem(newKey) === null) {
            storage.setItem(newKey, value);
            migrated.push(newKey);
          }
        }
        storage.removeItem(oldKey);
      } catch {
        // A key that does not fit stays under its old name; the next load tries again.
      }
    }
  } catch {
    // storage unavailable
  }
  return migrated;
}

const LEGACY_DUMMY_IDS = new Set(["thread-kras", "thread-her2", "thread-insulin", "thread-nsclc"]);

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

/** The parts of `window` this service touches (tests install a fake window with just these). */
interface BrowserStorages {
  localStorage?: KV;
  sessionStorage?: KV;
}

/** Storage that lives only as long as this page ("don't keep history"). */
class MemoryStorage implements KV {
  private map = new Map<string, string>();
  get length() {
    return this.map.size;
  }
  key(i: number) {
    return Array.from(this.map.keys())[i] ?? null;
  }
  getItem(k: string) {
    return this.map.has(k) ? (this.map.get(k) as string) : null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, String(v));
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

/** FNV-1a 32-bit, hex: a non-reversible fingerprint, so the token itself never appears in a storage key. */
function fnv1a(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

/**
 * Namespace for one backend + identity. The backend's origin and a fingerprint of the bearer token: changing either
 * shows a different (initially empty) history instead of the previous user's.
 */
export function storageScope(backendUrl: string, authToken: string): string {
  let origin = String(backendUrl || "").trim();
  try {
    origin = new URL(origin).origin;
  } catch {
    // keep the raw string
  }
  return fnv1a(`${origin}|${authToken || ""}`);
}

/** Messages with citation passage text removed (ids, titles, URLs and highlights are kept). */
function stripCitationPassageText(messages: Message[]): Message[] {
  return messages.map((m) => {
    if (!m.citations || !m.citations.entries) return m;
    const entries = Object.fromEntries(
      Object.entries(m.citations.entries).map(([k, entry]) => [
        k,
        { ...entry, passages: (entry.passages || []).map((p) => ({ ...p, text: "" })) },
      ])
    );
    return { ...m, citations: { ...m.citations, entries, truncated: true } };
  });
}

/** Fields holding an embedded base64 image: simulation plots, Axiom/SageMath and sandbox figures. */
const IMAGE_KEYS = new Set(["plot_base64_png", "png_base64", "plot_png"]);

/** A copy without embedded images at any depth; each object that lost one is marked so its card can say so (UI-008). */
function withoutImages<T>(value: T): T {
  if (Array.isArray(value)) return value.map(withoutImages) as T;
  if (!value || typeof value !== "object") return value;
  let dropped = false;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    if (IMAGE_KEYS.has(k) && typeof v === "string") {
      dropped = true;
      continue;
    }
    out[k] = withoutImages(v);
  }
  if (dropped) out.plot_dropped_for_storage = true;
  return out as T;
}

/**
 * Messages reduced to what the thread view, re-run and export still need after a reload. The full run
 * manifest is stored server-side (re-run and export look it up by run_id); query_context and the source
 * list are diagnostic. With dropPlots, every embedded image and citation passage text go too.
 * Slimmed assistant messages carry `storage_slimmed` so the reloaded view can say what was dropped.
 */
export function slimMessages(messages: Message[], dropPlots = false): Message[] {
  const slim = messages.map((m) => {
    if (m.sender !== "assistant") return m;
    const { query_context: _qc, ...rest } = m;
    const out: Message = { ...compactMessage(rest as Message), storage_slimmed: dropPlots ? "plots" : "diagnostics" };
    if (m.execution_artifacts) {
      const { sources: _sources, ...artifacts } = m.execution_artifacts;
      out.execution_artifacts = dropPlots ? withoutImages(artifacts) : artifacts;
    }
    return out;
  });
  return dropPlots ? stripCitationPassageText(slim) : slim;
}

/**
 * What every save keeps of a message: the full run manifest lives on the server (re-run and export look it up by
 * run_id), so only its id is stored. Nothing the thread view shows is dropped, so no notice is needed.
 */
function compactMessage(m: Message): Message {
  if (!m.run_manifest || Object.keys(m.run_manifest).length <= 1) return m;
  return { ...m, run_manifest: { run_id: m.run_manifest.run_id } as Message["run_manifest"] };
}

function normalizePrefs(raw: unknown): HistoryPrefs {
  const p = raw && typeof raw === "object" ? (raw as Partial<HistoryPrefs>) : {};
  const mode: HistoryMode = p.mode === "session" || p.mode === "off" || p.mode === "device" ? p.mode : DEFAULT_HISTORY_PREFS.mode;
  const days = typeof p.retentionDays === "number" && Number.isFinite(p.retentionDays) && p.retentionDays >= 0
    ? Math.floor(p.retentionDays)
    : DEFAULT_HISTORY_PREFS.retentionDays;
  return { mode, retentionDays: days };
}

export class LocalStorageService {
  private scope = "";
  private memory = new MemoryStorage();
  private listeners = new Set<(n: StorageNotice) => void>();

  // ==========================================
  // STORAGE SELECTION, SCOPE AND RETENTION
  // ==========================================

  private win(): BrowserStorages | null {
    return typeof window === "undefined" ? null : (window as unknown as BrowserStorages);
  }

  /** localStorage, for settings and the history preference (never conversation content). */
  private device(): KV | null {
    const w = this.win();
    try {
      return w && w.localStorage ? (w.localStorage as KV) : null;
    } catch {
      return null;
    }
  }

  /** Where conversation history goes under the current preference. */
  private store(): KV | null {
    const mode = this.getHistoryPrefs().mode;
    if (mode === "off") return this.memory;
    const w = this.win();
    try {
      if (!w) return null;
      return (mode === "session" ? w.sessionStorage : w.localStorage) ?? null;
    } catch {
      return null;
    }
  }

  private isAvailable(): boolean {
    const s = this.store();
    if (!s) return false;
    try {
      const testKey = "__tribos_storage_test__";
      s.setItem(testKey, "1");
      s.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  }

  private k(base: string): string {
    return this.scope ? `${base}@${this.scope}` : base;
  }

  private msgKey(threadId: string): string {
    return `${STORAGE_KEYS.THREAD_MESSAGES_PREFIX}${this.scope ? `${this.scope}__` : ""}${threadId}`;
  }

  private draftKey(threadId: string): string {
    return this.k(`${STORAGE_KEYS.DRAFT_PREFIX}${threadId}`);
  }

  /** Runs the phronesis -> tribos key migration on device and session storage (call once, before reading). */
  public migrateLegacyStorage(): string[] {
    const w = this.win();
    if (!w) return [];
    const out: string[] = [];
    for (const name of ["localStorage", "sessionStorage"] as const) {
      try {
        out.push(...migrateLegacyKeys(w[name] as KV | undefined));
      } catch {
        // storage unavailable
      }
    }
    return out;
  }

  /** Listen for slimming / pruning / expiry notices; returns an unsubscribe function. */
  public subscribe(listener: (n: StorageNotice) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(n: StorageNotice): void {
    for (const l of this.listeners) {
      try {
        l(n);
      } catch {
        // a listener's failure never breaks persistence
      }
    }
  }

  public getHistoryPrefs(): HistoryPrefs {
    const d = this.device();
    try {
      const raw = d?.getItem(STORAGE_KEYS.HISTORY_PREFS);
      return normalizePrefs(raw ? JSON.parse(raw) : null);
    } catch {
      return { ...DEFAULT_HISTORY_PREFS };
    }
  }

  /**
   * Changes where history is kept / how long. Moving away from "device" removes this scope's history from the
   * device after copying it to the new place (session storage or this tab's memory), so nothing stays behind.
   */
  public setHistoryPrefs(next: Partial<HistoryPrefs>): HistoryPrefs {
    const before = this.getHistoryPrefs();
    const prefs = normalizePrefs({ ...before, ...next });
    const from = this.store();
    const ids = this.getInvestigations().map((i) => i.id);
    const snapshot = {
      list: from?.getItem(this.k(STORAGE_KEYS.INVESTIGATIONS)) ?? null,
      active: from?.getItem(this.k(STORAGE_KEYS.ACTIVE_THREAD)) ?? null,
      // Unsent drafts move with their conversations, so nothing typed stays behind on the device.
      msgs: ids.flatMap((id) => [
        [this.msgKey(id), from?.getItem(this.msgKey(id)) ?? null] as const,
        [this.draftKey(id), from?.getItem(this.draftKey(id)) ?? null] as const,
      ]),
    };
    try {
      this.device()?.setItem(STORAGE_KEYS.HISTORY_PREFS, JSON.stringify(prefs));
    } catch {
      return before;
    }
    if (prefs.mode !== before.mode) {
      const to = this.store();
      if (from && to && from !== to) {
        try {
          if (snapshot.list !== null) to.setItem(this.k(STORAGE_KEYS.INVESTIGATIONS), snapshot.list);
          if (snapshot.active !== null) to.setItem(this.k(STORAGE_KEYS.ACTIVE_THREAD), snapshot.active);
          for (const [key, val] of snapshot.msgs) if (val !== null) to.setItem(key, val);
        } catch {
          // the open conversation stays in memory either way
        }
        from.removeItem(this.k(STORAGE_KEYS.INVESTIGATIONS));
        from.removeItem(this.k(STORAGE_KEYS.ACTIVE_THREAD));
        for (const [key] of snapshot.msgs) from.removeItem(key);
      }
    }
    if (prefs.retentionDays !== before.retentionDays) this.pruneExpired();
    return prefs;
  }

  /**
   * Selects the history namespace for this backend + token (call before reading history, and again when either
   * changes). History written by older versions without a namespace is adopted once by the first scope that loads
   * it, so upgrading keeps the user's investigations. Expired investigations are pruned.
   */
  public configure(backendUrl: string, authToken: string): void {
    this.scope = storageScope(backendUrl, authToken);
    this.adoptLegacyHistory();
    this.pruneExpired();
  }

  public getScope(): string {
    return this.scope;
  }

  private adoptLegacyHistory(): void {
    const s = this.store();
    if (!s || !this.scope) return;
    try {
      const legacy = s.getItem(STORAGE_KEYS.INVESTIGATIONS);
      if (legacy === null || s.getItem(this.k(STORAGE_KEYS.INVESTIGATIONS)) !== null) return;
      const list = JSON.parse(legacy);
      s.setItem(this.k(STORAGE_KEYS.INVESTIGATIONS), legacy);
      const active = s.getItem(STORAGE_KEYS.ACTIVE_THREAD);
      if (active !== null) s.setItem(this.k(STORAGE_KEYS.ACTIVE_THREAD), active);
      for (const inv of Array.isArray(list) ? list : []) {
        if (!inv || typeof inv.id !== "string") continue;
        const oldKey = `${STORAGE_KEYS.THREAD_MESSAGES_PREFIX}${inv.id}`;
        const msgs = s.getItem(oldKey);
        if (msgs !== null) s.setItem(this.msgKey(inv.id), msgs);
        s.removeItem(oldKey);
      }
      s.removeItem(STORAGE_KEYS.INVESTIGATIONS);
      s.removeItem(STORAGE_KEYS.ACTIVE_THREAD);
    } catch (e) {
      console.warn("TribosLocalStorage: could not adopt history saved by an older version", e);
    }
  }

  /** Removes investigations not updated within the retention period; returns the removed ids. */
  public pruneExpired(now: number = Date.now()): string[] {
    const { retentionDays } = this.getHistoryPrefs();
    if (!retentionDays) return [];
    const cutoff = now - retentionDays * 86_400_000;
    const list = this.getInvestigations();
    const expired = list.filter((i) => {
      const t = new Date(i.updatedAt || i.createdAt).getTime();
      return Number.isFinite(t) && t < cutoff;
    });
    if (!expired.length) return [];
    for (const inv of expired) this.deleteInvestigation(inv.id);
    const ids = expired.map((i) => i.id);
    this.notify({
      kind: "expired",
      message: `${ids.length} investigation${ids.length === 1 ? "" : "s"} older than ${retentionDays} days ${ids.length === 1 ? "was" : "were"} removed from this browser.`,
      threadIds: ids,
    });
    return ids;
  }

  // ==========================================
  // INVESTIGATIONS (THREADS)
  // ==========================================

  public getInvestigations(): InvestigationItem[] {
    if (!this.isAvailable()) return [];
    try {
      const raw = this.store()!.getItem(this.k(STORAGE_KEYS.INVESTIGATIONS));
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Filter out legacy dummy threads that have 0 messages
        // Threads stored before projects existed load unchanged (no projectId: outside every project).
        const valid = migrateThreads(
          parsed.filter((inv) => !LEGACY_DUMMY_IDS.has(inv.id) || (inv.messageCount && inv.messageCount > 0))
        );
        return valid.sort(
          (a, b) =>
            Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) ||
            new Date(b.updatedAt || b.createdAt).getTime() - new Date(a.updatedAt || a.createdAt).getTime()
        );
      }
      return [];
    } catch (e) {
      console.warn("TribosLocalStorage: failed to get investigations", e);
      return [];
    }
  }

  private saveInvestigationsList(list: InvestigationItem[]): void {
    if (!this.isAvailable()) return;
    const key = this.k(STORAGE_KEYS.INVESTIGATIONS);
    if (this.trySetItem(key, list)) return;
    // Make room from reconstructible caches only (never another investigation's messages), then retry once.
    for (const other of this.olderThreads("")) {
      this.slimStoredThread(other);
      if (this.trySetItem(key, list)) return;
    }
    if (!this.trySetItem(key, list)) {
      this.notify({ kind: "not_saved", message: "The investigation list could not be saved in this browser.", threadIds: [] });
    }
  }

  public saveInvestigation(item: InvestigationItem): void {
    const list = this.getInvestigations();
    const existingIndex = list.findIndex((i) => i.id === item.id);
    if (existingIndex >= 0) {
      list[existingIndex] = { ...list[existingIndex], ...item, updatedAt: new Date().toISOString() };
    } else {
      list.unshift({ ...item, createdAt: item.createdAt || new Date().toISOString(), updatedAt: new Date().toISOString() });
    }
    this.saveInvestigationsList(list);
  }

  public renameInvestigation(id: string, newTitle: string): void {
    const list = this.getInvestigations();
    const target = list.find((i) => i.id === id);
    if (target) {
      target.title = newTitle.trim();
      target.isCustomTitle = true;
      target.updatedAt = new Date().toISOString();
      this.saveInvestigationsList(list);
    }
  }

  public updateInvestigationTitle(id: string, newTitle: string, isCustom = false): boolean {
    const list = this.getInvestigations();
    const target = list.find((i) => i.id === id);
    if (!target) return false;
    if (target.isCustomTitle && !isCustom) return false;
    const cleanTitle = newTitle.trim();
    if (!cleanTitle) return false;
    target.title = cleanTitle;
    if (isCustom) target.isCustomTitle = true;
    target.updatedAt = new Date().toISOString();
    this.saveInvestigationsList(list);
    return true;
  }

  /** Pins or unpins a conversation (pinned ones are listed first); the order of the rest is unchanged. */
  public setPinned(id: string, pinned: boolean): void {
    const list = this.getInvestigations();
    const target = list.find((i) => i.id === id);
    if (!target) return;
    target.pinned = pinned || undefined;
    this.saveInvestigationsList(list);
  }

  /** Moves a conversation into a project, or out of every project with null. */
  public setThreadProject(id: string, projectId: string | null): void {
    this.saveInvestigationsList(moveThread(this.getInvestigations(), id, projectId));
  }

  /** After a project is deleted: its chats move out of it (keepChats) or are deleted with it. */
  public removeProject(projectId: string, keepChats: boolean): void {
    const { kept, deletedIds } = afterProjectDeleted(this.getInvestigations(), projectId, keepChats);
    this.saveInvestigationsList(kept);
    for (const id of deletedIds) {
      try {
        this.store()!.removeItem(this.msgKey(id));
        this.store()!.removeItem(this.draftKey(id));
      } catch {
        // ignore
      }
    }
  }

  /** The unsent text of a conversation's composer ("" when none). */
  public getDraft(threadId: string): string {
    if (!this.isAvailable() || !threadId) return "";
    try {
      return this.store()!.getItem(this.draftKey(threadId)) || "";
    } catch {
      return "";
    }
  }

  /** Keeps (or, when empty, clears) the unsent text of a conversation's composer. */
  public saveDraft(threadId: string, text: string): void {
    if (!this.isAvailable() || !threadId) return;
    const key = this.draftKey(threadId);
    try {
      if (text.trim()) this.store()!.setItem(key, text.slice(0, 20000));
      else this.store()!.removeItem(key);
    } catch {
      // a draft is a convenience; a full store simply does not keep it
    }
  }

  /** Searches the saved conversations' messages (case-insensitive, LaTeX included), newest conversations first. */
  public searchHistory(query: string, limit = 30): HistoryMatch[] {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    const out: HistoryMatch[] = [];
    for (const inv of this.getInvestigations()) {
      if (inv.title.toLowerCase().includes(q)) {
        out.push({ threadId: inv.id, title: inv.title, messageId: "", sender: "user", snippet: inv.preview || inv.title });
      }
      for (const m of this.getMessages(inv.id)) {
        const text = String(m.content || "");
        const at = text.toLowerCase().indexOf(q);
        if (at < 0) continue;
        const start = Math.max(0, at - 50);
        const snippet = (start ? "…" : "") + text.slice(start, at + q.length + 70).replace(/\s+/g, " ") + "…";
        out.push({ threadId: inv.id, title: inv.title, messageId: m.id, sender: m.sender, snippet });
        if (out.length >= limit) return out;
      }
    }
    return out;
  }

  public deleteInvestigation(id: string): void {
    if (!this.isAvailable()) return;
    const list = this.getInvestigations().filter((i) => i.id !== id);
    this.saveInvestigationsList(list);
    try {
      this.store()!.removeItem(this.msgKey(id));
      // The conversation's unsent draft goes with it (deleted or expired).
      this.store()!.removeItem(this.draftKey(id));
    } catch {
      // ignore
    }
  }

  public createNewThread(
    title: string = "New Investigation",
    framework?: string,
    model?: string,
    projectId?: string | null
  ): InvestigationItem {
    const now = new Date().toISOString();
    const newId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
    const newItem: InvestigationItem = {
      id: newId,
      title,
      createdAt: now,
      updatedAt: now,
      framework,
      model,
      messageCount: 0,
      preview: "New investigation session",
      ...(projectId ? { projectId } : {}),
    };

    const list = this.getInvestigations();
    list.unshift(newItem);
    this.saveInvestigationsList(list);
    this.setActiveThreadId(newId);
    this.saveMessages(newId, []);

    return newItem;
  }

  // ==========================================
  // ACTIVE THREAD ID
  // ==========================================

  public getActiveThreadId(): string {
    const fallbackId = `session_${Date.now()}`;
    if (!this.isAvailable()) return fallbackId;
    try {
      const active = this.store()!.getItem(this.k(STORAGE_KEYS.ACTIVE_THREAD));
      if (active && !LEGACY_DUMMY_IDS.has(active)) return active;
      const list = this.getInvestigations();
      if (list.length > 0 && list[0]?.id && !LEGACY_DUMMY_IDS.has(list[0].id)) {
        return list[0].id;
      }
      return fallbackId;
    } catch {
      return fallbackId;
    }
  }

  public setActiveThreadId(id: string): void {
    if (!this.isAvailable()) return;
    try {
      this.store()!.setItem(this.k(STORAGE_KEYS.ACTIVE_THREAD), id);
    } catch {
      // ignore
    }
  }

  // ==========================================
  // MESSAGES PERSISTENCE
  // ==========================================

  public getMessages(threadId: string): Message[] {
    if (!this.isAvailable() || !threadId) return [];
    try {
      const raw = this.store()!.getItem(this.msgKey(threadId));
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.map((m: Message) => ({ ...m, agent: normalizeLegacyAgentName(m.agent) || "Tribos Orchestrator" }));
    } catch (e) {
      console.warn(`TribosLocalStorage: failed to get messages for ${threadId}`, e);
      return [];
    }
  }

  public saveMessages(threadId: string, messages: Message[], autoGenerateTitle?: string): SaveResult {
    const none: SaveResult = { saved: false, level: "none", prunedThreadIds: [] };
    if (!this.isAvailable() || !threadId) return none;
    const key = this.msgKey(threadId);
    const full = messages.map(compactMessage);
    // The open investigation is the one the reader is looking at, so space is made elsewhere first: older
    // investigations give up their reconstructible caches (plots, citation passage text), then this one does. The
    // conversation text of an investigation is never deleted to make room (audit I20): a save that still does not fit
    // is reported as not saved, and every earlier investigation stays as it was.
    let level: SaveResult["level"] = this.trySetItem(key, full) ? "full" : "none";
    if (level === "none") {
      const slim = slimMessages(messages);
      level = this.trySetItem(key, slim) ? "slim" : "none";
      for (const other of level === "none" ? this.olderThreads(threadId) : []) {
        this.slimStoredThread(other);
        if (this.trySetItem(key, slim)) {
          level = "slim";
          break;
        }
      }
    }
    if (level === "none" && this.trySetItem(key, slimMessages(messages, true))) level = "no_plots";
    const result: SaveResult = { saved: level !== "none", level, prunedThreadIds: [] };
    if (level === "none") {
      this.notify({
        kind: "not_saved",
        message: "This investigation could not be saved in this browser (storage is full). It stays on screen until you reload.",
        threadIds: [threadId],
      });
      return result;
    }
    if (level === "no_plots") {
      this.notify({
        kind: "slimmed",
        message: "Browser storage is nearly full: plots and citation passages of this investigation were not saved, so they will be missing after a reload.",
        threadIds: [threadId],
      });
    }
    try {
      // Update investigation record
      const list = this.getInvestigations();
      const existing = list.find((i) => i.id === threadId);

      const lastMsg = messages[messages.length - 1];
      const preview = lastMsg
        ? typeof lastMsg.content === "string"
          ? lastMsg.content.slice(0, 80).replace(/\n/g, " ") + (lastMsg.content.length > 80 ? "..." : "")
          : "Message logged"
        : "No messages yet";

      const isGenericTitle = (t: string) => {
        const lower = t.toLowerCase().trim();
        return (
          lower === "new investigation" ||
          lower.startsWith("new investigation") ||
          lower === "investigation" ||
          lower === "new clinical investigation" ||
          lower.startsWith("new clinical investigation") ||
          lower === "clinical investigation" ||
          lower.startsWith("new conversation") ||
          lower.startsWith("new inquiry") ||
          lower.startsWith("untitled") ||
          lower.startsWith("session_") ||
          lower.startsWith("thread-")
        );
      };

      if (existing) {
        existing.messageCount = messages.length;
        existing.preview = preview;
        existing.updatedAt = new Date().toISOString();
        existing.messagesPruned = false;
        if (autoGenerateTitle && !existing.isCustomTitle && (isGenericTitle(existing.title) || messages.length <= 2)) {
          existing.title = autoGenerateTitle;
        }
        this.saveInvestigationsList(list);
      } else {
        // Auto-create thread record
        const title =
          autoGenerateTitle ||
          (messages[0]?.content
            ? messages[0].content.slice(0, 42).replace(/\n/g, " ")
            : "Investigation");

        const newItem: InvestigationItem = {
          id: threadId,
          title,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          messageCount: messages.length,
          preview,
          isCustomTitle: false,
        };
        list.unshift(newItem);
        this.saveInvestigationsList(list);
      }
    } catch (e) {
      console.warn(`TribosLocalStorage: failed to update the investigation record for ${threadId}`, e);
    }
    return result;
  }

  /** Other saved investigations, oldest first (the active one and `keep` excluded). */
  private olderThreads(keep: string): InvestigationItem[] {
    const activeId = this.getActiveThreadId();
    return this.getInvestigations()
      .filter((i) => i.id !== keep && i.id !== activeId && !i.messagesPruned)
      .reverse();
  }

  /** Rewrites an older investigation's saved messages without plots and passage text, and says so (UI-008). */
  private slimStoredThread(inv: InvestigationItem): void {
    try {
      const raw = this.store()!.getItem(this.msgKey(inv.id));
      const msgs = raw ? JSON.parse(raw) : null;
      if (!Array.isArray(msgs)) return;
      const slim = JSON.stringify(slimMessages(msgs, true));
      if (slim.length >= raw!.length) return;
      this.store()!.setItem(this.msgKey(inv.id), slim);
      this.notify({
        kind: "slimmed",
        message: `Browser storage was full: plots and citation passages of the older investigation "${inv.title}" were removed to make room.`,
        threadIds: [inv.id],
      });
    } catch {
      // left exactly as it was: a failed rewrite never loses the stored investigation
    }
  }

  private trySetItem(key: string, value: unknown): boolean {
    try {
      this.store()!.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  }

  // ==========================================
  // USER PREFERENCES / SETTINGS (device storage; no conversation content)
  // ==========================================

  public getSettings(): UserSettings {
    const d = this.device();
    if (!d) return {};
    try {
      const raw = d.getItem(STORAGE_KEYS.SETTINGS);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  public saveSettings(settings: Partial<UserSettings>): void {
    const d = this.device();
    if (!d) return;
    try {
      const current = this.getSettings();
      const updated = { ...current, ...settings };
      d.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(updated));
    } catch {
      // ignore
    }
  }

  // ==========================================
  // STATS & QUOTA MANAGEMENT
  // ==========================================

  public getStorageUsage(): {
    usedKb: number;
    threadCount: number;
    messageCount: number;
    isQuotaHealthy: boolean;
  } {
    if (!this.isAvailable()) {
      return { usedKb: 0, threadCount: 0, messageCount: 0, isQuotaHealthy: true };
    }
    try {
      const s = this.store()!;
      let totalBytes = 0;
      let msgCount = 0;
      const invs = this.getInvestigations();
      const prefix = `${STORAGE_KEYS.THREAD_MESSAGES_PREFIX}${this.scope ? `${this.scope}__` : ""}`;

      for (let i = 0; i < s.length; i++) {
        const key = s.key(i);
        if (key && key.startsWith("tribos_")) {
          const val = s.getItem(key) || "";
          totalBytes += (key.length + val.length) * 2; // UTF-16 approximation
          if (key.startsWith(prefix)) {
            try {
              const msgs = JSON.parse(val);
              if (Array.isArray(msgs)) msgCount += msgs.length;
            } catch {
              // ignore
            }
          }
        }
      }

      const usedKb = Math.round((totalBytes / 1024) * 10) / 10;
      return {
        usedKb,
        threadCount: invs.length,
        messageCount: msgCount,
        isQuotaHealthy: usedKb < 4500, // standard localStorage limit ~5MB
      };
    } catch {
      return { usedKb: 0, threadCount: 0, messageCount: 0, isQuotaHealthy: true };
    }
  }

  /** Removes every saved conversation of every user/backend from this browser (device, session and tab memory). */
  public clearAllLocalData(): void {
    const w = this.win();
    const stores: KV[] = [this.memory];
    try {
      if (w?.localStorage) stores.push(w.localStorage);
      if (w?.sessionStorage) stores.push(w.sessionStorage);
    } catch {
      // storage unavailable
    }
    for (const s of stores) {
      try {
        const keysToRemove: string[] = [];
        for (let i = 0; i < s.length; i++) {
          const key = s.key(i);
          // Preferences (where/how long to keep history, model choice) are not conversation data.
          if (key && key.startsWith("tribos_") && key !== STORAGE_KEYS.HISTORY_PREFS && key !== STORAGE_KEYS.SETTINGS) {
            keysToRemove.push(key);
          }
        }
        keysToRemove.forEach((k) => s.removeItem(k));
      } catch (e) {
        console.error("Failed to clear browser storage", e);
      }
    }
  }
}

export const localStorageService = new LocalStorageService();
