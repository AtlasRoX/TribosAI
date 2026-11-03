/**
 * Conversation history in IndexedDB behind the synchronous key-value interface the storage service already uses.
 *
 * localStorage holds about 5 MB per site, which a few dozen investigations with their verification reports, citation
 * records and plots fill ("could not be saved in this browser (storage is full)"). IndexedDB is allowed a share of the
 * disk instead. Reads and writes stay synchronous through an in-memory copy that is loaded once at startup
 * (`ready`); each write is then saved to IndexedDB in the background, batched per animation frame.
 *
 * On the first start, history keys still in localStorage move here and are removed there, freeing that space.
 */

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

const DB_NAME = "tribos-history";
const STORE = "kv";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export class IdbHistoryStore implements KV {
  private map = new Map<string, string>();
  private db: IDBDatabase | null = null;
  private pending = new Map<string, string | null>();
  private flushScheduled = false;
  readonly ready: Promise<boolean>;

  /**
   * @param legacy where history used to live (localStorage), moved here on first start
   * @param isHistoryKey which legacy keys are history (investigations, active thread, messages, drafts)
   * @param onWriteError told when a background save fails, so the reader learns it was not kept
   */
  private legacy: KV | null;
  private isHistoryKey: (key: string) => boolean;
  private onWriteError: (error: unknown) => void;

  constructor(legacy: KV | null, isHistoryKey: (key: string) => boolean, onWriteError: (error: unknown) => void = () => {}) {
    this.legacy = legacy;
    this.isHistoryKey = isHistoryKey;
    this.onWriteError = onWriteError;
    this.ready = this.open().catch(() => false);
  }

  private async open(): Promise<boolean> {
    if (typeof indexedDB === "undefined") return false;
    const openReq = indexedDB.open(DB_NAME, 1);
    openReq.onupgradeneeded = () => {
      if (!openReq.result.objectStoreNames.contains(STORE)) openReq.result.createObjectStore(STORE);
    };
    this.db = await request(openReq);
    const tx = this.db.transaction(STORE, "readonly");
    const store = tx.objectStore(STORE);
    const [keys, values] = await Promise.all([request(store.getAllKeys()), request(store.getAll())]);
    keys.forEach((k, i) => this.map.set(String(k), String(values[i])));
    this.adoptLegacy();
    return true;
  }

  /** History still in localStorage moves here (never overwriting a newer copy) and is removed there. */
  private adoptLegacy(): void {
    const legacy = this.legacy;
    if (!legacy) return;
    const keys: string[] = [];
    for (let i = 0; i < legacy.length; i++) {
      const k = legacy.key(i);
      if (k && this.isHistoryKey(k)) keys.push(k);
    }
    for (const k of keys) {
      const v = legacy.getItem(k);
      if (v !== null && !this.map.has(k)) this.setItem(k, v);
    }
    // Removed only once the copy is safely written, so a failed migration loses nothing.
    void this.flush().then((ok) => {
      if (!ok) return;
      for (const k of keys) {
        try {
          legacy.removeItem(k);
        } catch {
          // left in place: still readable there
        }
      }
    });
  }

  get length(): number {
    return this.map.size;
  }

  key(i: number): string | null {
    return Array.from(this.map.keys())[i] ?? null;
  }

  getItem(k: string): string | null {
    return this.map.has(k) ? (this.map.get(k) as string) : null;
  }

  setItem(k: string, v: string): void {
    const value = String(v);
    this.map.set(k, value);
    this.pending.set(k, value);
    this.schedule();
  }

  removeItem(k: string): void {
    this.map.delete(k);
    this.pending.set(k, null);
    this.schedule();
  }

  private schedule(): void {
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    const run = () => {
      this.flushScheduled = false;
      void this.flush();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
    else setTimeout(run, 0);
  }

  /** Writes every pending change in one transaction; false when IndexedDB is unavailable or the write failed. */
  flush(): Promise<boolean> {
    if (!this.db || !this.pending.size) return Promise.resolve(!!this.db);
    const batch = Array.from(this.pending.entries());
    this.pending.clear();
    return new Promise((resolve) => {
      try {
        const tx = this.db!.transaction(STORE, "readwrite");
        const store = tx.objectStore(STORE);
        for (const [k, v] of batch) {
          if (v === null) store.delete(k);
          else store.put(v, k);
        }
        tx.oncomplete = () => resolve(true);
        tx.onerror = tx.onabort = () => {
          this.onWriteError(tx.error);
          resolve(false);
        };
      } catch (e) {
        this.onWriteError(e);
        resolve(false);
      }
    });
  }
}
