import assert from "node:assert/strict";
import test from "node:test";
import {
  type SidebarThread,
  afterProjectDeleted,
  groupThreads,
  migrateThreads,
  moveThread,
  orderThreads,
  recencyGroup,
  safeColor,
  searchThreads,
  threadsIn,
} from "../src/lib/sidebarData.ts";
import { FeatureUnavailableError, isFeatureMissing, listProjectMembers, listProjects, normalizeProject } from "../src/services/agentService.ts";
import { ApiError } from "../src/services/apiClient.ts";
import { LocalStorageService } from "../src/services/localStorageService.ts";

const at = (y: number, m: number, d: number, h = 12, min = 0) => new Date(y, m - 1, d, h, min);
const thread = (id: string, when: Date, extra: Partial<SidebarThread> = {}): SidebarThread => ({
  id, title: `chat ${id}`, createdAt: when.toISOString(), updatedAt: when.toISOString(), ...extra,
});

test("T10: recency groups follow calendar days, not 24-hour windows", () => {
  const now = at(2026, 10, 25, 0, 30); // just after midnight
  assert.equal(recencyGroup(at(2026, 10, 25, 0, 5).getTime(), now).label, "Today");
  assert.equal(recencyGroup(at(2026, 10, 24, 23, 59).getTime(), now).label, "Yesterday"); // 31 minutes ago
  assert.equal(recencyGroup(at(2026, 10, 18, 9).getTime(), now).label, "Previous 7 days");
  assert.equal(recencyGroup(at(2026, 10, 17, 9).getTime(), now).label, "Previous 30 days");
  assert.equal(recencyGroup(at(2026, 9, 25, 9).getTime(), now).label, "Previous 30 days");
  assert.equal(recencyGroup(at(2026, 8, 3).getTime(), now).label, "August");
  assert.equal(recencyGroup(at(2025, 12, 3).getTime(), now).label, "December 2025");
});

test("T10: history groups come in time order with pinned chats on top", () => {
  const now = at(2026, 10, 25, 15);
  const threads = [
    thread("old", at(2026, 3, 2)),
    thread("today2", at(2026, 10, 25, 14)),
    thread("pinnedOld", at(2026, 1, 5), { pinned: true }),
    thread("yesterday", at(2026, 10, 24, 9)),
    thread("today1", at(2026, 10, 25, 9)),
    thread("pinnedNew", at(2026, 10, 20), { pinned: true }),
  ];
  const groups = groupThreads(threads, now);
  assert.deepEqual(groups.map((g) => g.label), ["Pinned", "Today", "Yesterday", "March"]);
  assert.deepEqual(groups[0].items.map((t) => t.id), ["pinnedNew", "pinnedOld"]);
  assert.deepEqual(groups[1].items.map((t) => t.id), ["today2", "today1"]);
  assert.deepEqual(orderThreads(threads).map((t) => t.id).slice(0, 3), ["pinnedNew", "pinnedOld", "today2"]);
});

test("T10: chats move into and out of projects, and old threads migrate unchanged", () => {
  const threads = [thread("a", at(2026, 10, 1)), thread("b", at(2026, 10, 2), { projectId: "prj_abcdef123" })];
  const moved = moveThread(threads, "a", "prj_abcdef123");
  assert.equal(moved[0].projectId, "prj_abcdef123");
  assert.deepEqual(threadsIn(moved, "prj_abcdef123").map((t) => t.id), ["a", "b"]);
  assert.deepEqual(threadsIn(moved, null), []);
  const out = moveThread(moved, "b", null);
  assert.equal("projectId" in out[1], false);
  assert.equal(moveThread(threads, "a", "not-a-project")[0].projectId, undefined);
  // Stored threads without a projectId stay as they are; a malformed one is dropped.
  const legacy = [thread("x", at(2026, 1, 1)), thread("y", at(2026, 1, 1), { projectId: "../etc" })];
  const migrated = migrateThreads(legacy);
  assert.equal(migrated[0], legacy[0]);
  assert.equal(migrated[1].projectId, undefined);
});

test("T10: deleting a project keeps or deletes its chats", () => {
  const threads = [thread("a", at(2026, 10, 1), { projectId: "prj_abcdef123" }), thread("b", at(2026, 10, 2))];
  const keep = afterProjectDeleted(threads, "prj_abcdef123", true);
  assert.deepEqual(keep.deletedIds, []);
  assert.equal(keep.kept[0].projectId, undefined);
  const drop = afterProjectDeleted(threads, "prj_abcdef123", false);
  assert.deepEqual(drop.deletedIds, ["a"]);
  assert.deepEqual(drop.kept.map((t) => t.id), ["b"]);
});

test("T10: the storage service stores project chats and removes a project's chats", () => {
  const store = new Map<string, string>();
  const ls = {
    get length() { return store.size; },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
  };
  (globalThis as unknown as { window: unknown }).window = { localStorage: ls, sessionStorage: ls };
  const svc = new LocalStorageService();
  const inProject = svc.createNewThread("Beam", "auto", "m", "prj_abcdef123");
  const outside = svc.createNewThread("Other");
  assert.equal(svc.getInvestigations().find((i) => i.id === inProject.id)?.projectId, "prj_abcdef123");
  svc.setThreadProject(outside.id, "prj_abcdef123");
  svc.removeProject("prj_abcdef123", false);
  assert.deepEqual(svc.getInvestigations().map((i) => i.id), []);
});

test("T10: search matches every word of titles and previews", () => {
  const threads = [
    thread("a", at(2026, 10, 1), { title: "Cantilever beam deflection" }),
    thread("b", at(2026, 10, 2), { title: "Pipe flow", preview: "pressure drop in a steel pipe" }),
    thread("c", at(2026, 10, 3), { title: "Beam buckling" }),
  ];
  assert.deepEqual(searchThreads(threads, "beam").map((t) => t.id), ["c", "a"]);
  assert.deepEqual(searchThreads(threads, "STEEL pressure").map((t) => t.id), ["b"]);
  assert.deepEqual(searchThreads(threads, "  ").map((t) => t.id), ["c", "b", "a"]);
});

async function withFetch(response: () => Response, run: () => Promise<void>) {
  const orig = globalThis.fetch;
  globalThis.fetch = (async () => response()) as typeof fetch;
  try {
    await run();
  } finally {
    globalThis.fetch = orig;
  }
}

const noAuth = (extra: Record<string, string> = {}) => extra;

test("T10: a missing route hides the feature, a missing project is a real error", async () => {
  await withFetch(() => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }), async () => {
    await assert.rejects(listProjectMembers("http://x", noAuth, "prj_abcdef123"), (err: unknown) => {
      assert.ok(err instanceof FeatureUnavailableError);
      return isFeatureMissing(err);
    });
  });
  await withFetch(() => new Response(JSON.stringify({ detail: "Project not found" }), { status: 404 }), async () => {
    await assert.rejects(listProjectMembers("http://x", noAuth, "prj_abcdef123"), (err: unknown) => {
      assert.ok(err instanceof ApiError && !(err instanceof FeatureUnavailableError));
      return !isFeatureMissing(err);
    });
  });
  await withFetch(() => new Response(JSON.stringify({ detail: "This needs the owner role" }), { status: 403 }), async () => {
    await assert.rejects(listProjectMembers("http://x", noAuth, "prj_abcdef123"), (err: unknown) => (err as ApiError).status === 403);
  });
  assert.equal(isFeatureMissing(new ApiError(405, "x")), true);
});

test("T10: projects are read from the contract shape", async () => {
  const body = { projects: [{ id: "prj_abcdef123", name: "Lab", role: "viewer", owner_id: "alice", member_count: 2 }, { name: "no id" }] };
  await withFetch(() => new Response(JSON.stringify(body), { status: 200 }), async () => {
    const projects = await listProjects("http://x", noAuth);
    assert.equal(projects.length, 1);
    assert.equal(projects[0].role, "viewer");
  });
  assert.equal(normalizeProject({ id: "prj_x123456", role: "admin" })?.role, undefined);
  assert.equal(safeColor("#16a34a"), "#16a34a");
  assert.equal(safeColor("red; background: url(x)"), "#2563eb");
});
