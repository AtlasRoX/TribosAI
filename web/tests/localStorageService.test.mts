// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
// Browser-storage quota handling (UI-008): the open investigation keeps its plots while older ones make room.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LocalStorageService, slimMessages } from "../src/services/localStorageService.ts";

/** localStorage with a character quota, throwing like a browser when a write would exceed it. */
class QuotaStorage {
  map = new Map<string, string>();
  limit: number;
  constructor(limit: number) {
    this.limit = limit;
  }
  get length() {
    return this.map.size;
  }
  key(i: number) {
    return Array.from(this.map.keys())[i] ?? null;
  }
  getItem(k: string) {
    return this.map.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    let used = 0;
    for (const [key, val] of this.map) if (key !== k) used += key.length + val.length;
    if (used + k.length + v.length > this.limit) throw new Error("QuotaExceededError");
    this.map.set(k, String(v));
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

const PLOT = "iVBOR" + "A".repeat(20_000);

function answer(id: string): any[] {
  return [
    { id: `${id}-q`, sender: "user", content: "question", timestamp: "2026-10-24T00:00:00Z" },
    {
      id: `${id}-a`,
      sender: "assistant",
      content: "answer",
      timestamp: "2026-10-24T00:00:00Z",
      run_manifest: { run_id: `run_${id}`, tool_calls: [{ inputs: "x".repeat(2_000) }] },
      execution_artifacts: {
        dynamis: { plot_base64_png: PLOT, summary: "ok" },
        derivation: { figures: [{ name: "f.png", png_base64: PLOT }], steps: ["a"] },
      },
    },
  ];
}

function setup(limit: number) {
  const localStorage = new QuotaStorage(limit);
  (globalThis as any).window = { localStorage, sessionStorage: new QuotaStorage(limit) };
  const svc = new LocalStorageService();
  svc.configure("http://localhost:8000", "token");
  return { svc, localStorage };
}

test("slimming with dropPlots removes every embedded image, not only the legacy artifact names", () => {
  const [, slim] = slimMessages(answer("t"), true) as any[];
  assert.equal(slim.execution_artifacts.dynamis.plot_base64_png, undefined);
  assert.equal(slim.execution_artifacts.dynamis.plot_dropped_for_storage, true);
  assert.equal(slim.execution_artifacts.derivation.figures[0].png_base64, undefined);
  assert.equal(slim.execution_artifacts.derivation.steps[0], "a");
  assert.deepEqual(slim.run_manifest, { run_id: "run_t" });
});

test("every save stores only the run id of the manifest (the full manifest is on the server)", () => {
  const { svc } = setup(1_000_000);
  const result = svc.saveMessages("t1", answer("t1"));
  assert.equal(result.level, "full");
  const [, saved] = svc.getMessages("t1") as any[];
  assert.deepEqual(saved.run_manifest, { run_id: "run_t1" });
  assert.equal(saved.execution_artifacts.dynamis.plot_base64_png, PLOT);
  assert.equal(saved.storage_slimmed, undefined);
});

test("when storage is full, older investigations lose their plots before the open one does", () => {
  const { svc } = setup(150_000);
  for (const id of ["old1", "old2", "old3"]) {
    svc.createNewThread(id);
    assert.equal(svc.saveMessages(svc.getActiveThreadId(), answer(id)).level, "full");
  }
  const notices: string[] = [];
  svc.subscribe((n) => notices.push(n.kind));
  const current = svc.createNewThread("current").id;
  const result = svc.saveMessages(current, answer("current"));

  assert.notEqual(result.level, "no_plots");
  assert.notEqual(result.level, "none");
  const [, saved] = svc.getMessages(current) as any[];
  assert.equal(saved.execution_artifacts.dynamis.plot_base64_png, PLOT);
  const oldest = svc.getInvestigations().find((i) => i.title === "old1")!;
  const [, oldSaved] = svc.getMessages(oldest.id) as any[];
  assert.equal(oldSaved.storage_slimmed, "plots");
  assert.ok(notices.includes("slimmed"));
});

test("a full browser never deletes another investigation's conversation to make room (audit I20)", () => {
  // Room for a few investigations; then a new one far larger than what slimming can free.
  const { svc, localStorage } = setup(120_000);
  const ids: string[] = [];
  for (const id of ["a", "b", "c", "d"]) {
    ids.push(svc.createNewThread(id).id);
    svc.saveMessages(svc.getActiveThreadId(), answer(id));
  }
  const textBefore = ids.map((id) => (svc.getMessages(id) as any[]).map((m) => m.content).join("|"));
  const notices: string[] = [];
  svc.subscribe((n) => notices.push(n.kind));
  const big = svc.createNewThread("big").id;
  const huge = [{ id: "q", sender: "user", content: "x".repeat(200_000), timestamp: "2026-10-24T00:00:00Z" }];
  const result = svc.saveMessages(big, huge as any);

  assert.equal(result.saved, false);
  assert.equal(result.level, "none");
  assert.deepEqual(result.prunedThreadIds, []);
  assert.ok(!notices.includes("pruned"));
  assert.ok(notices.includes("not_saved"));
  // Every earlier conversation's text is still stored, and no record claims its messages were removed.
  assert.deepEqual(ids.map((id) => (svc.getMessages(id) as any[]).map((m) => m.content).join("|")), textBefore);
  assert.ok(svc.getInvestigations().every((i) => !i.messagesPruned));
  assert.ok(localStorage.map.size > 0);
});
