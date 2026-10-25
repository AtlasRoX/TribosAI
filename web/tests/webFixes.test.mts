// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
// Regression tests for the web fixes of the codebase audit (LOG-31..38, BRK-8, SUP-8, drafts cleanup).
import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeLegacyAgentName, normalizeThoughtAgents } from "../src/lib/legacyNames.ts";
import { DEFAULT_MODEL_ID, migrateSavedModel } from "../src/lib/modelMigration.ts";
import { jobQuestion } from "../src/lib/jobs.ts";
import { JobFailedError, patchFact, streamJobEvents } from "../src/services/agentService.ts";
import { LocalStorageService, migrateLegacyKeys } from "../src/services/localStorageService.ts";
import {
  DEFAULT_DATASET_LIMITS,
  acceptAttr,
  dimsOf,
  fetchDatasetLimits,
  kindForFile,
  normalizeDatasetLimits,
  precheckFile,
  sourceLabel,
} from "../src/services/datasetService.ts";

class MapStorage {
  map = new Map<string, string>();
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
    this.map.set(k, String(v));
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

/** Replaces fetch for one test; each call gets the next response from `responses`. */
async function withFetch(responses: (() => Response)[], run: (calls: { url: string; init: RequestInit }[]) => Promise<void>) {
  const orig = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    const next = responses[Math.min(calls.length - 1, responses.length - 1)];
    return next();
  }) as typeof fetch;
  try {
    await run(calls);
  } finally {
    globalThis.fetch = orig;
  }
}

const noAuth = (extra: Record<string, string> = {}) => extra;

// LOG-31 ------------------------------------------------------------------------------------------------------

test("LOG-31: legacy agent names are renamed in labels only, and the bare word Clinical is left alone", () => {
  assert.equal(normalizeLegacyAgentName("Clinical Orchestrator"), "Tribos Orchestrator");
  assert.equal(normalizeLegacyAgentName("Talk2BioModels"), "Dynamis");
  assert.equal(normalizeLegacyAgentName("Talk2Scholars"), "Archivon");
  assert.equal(normalizeLegacyAgentName("Clinical"), "Clinical");
  assert.equal(normalizeLegacyAgentName(undefined), "");
  const thoughts = normalizeThoughtAgents([
    { id: "1", agent: "Clinical Orchestrator", title: "Pre-clinical testing of the clinical rig", text: "Clinical data" },
    { id: "2", title: "No agent" },
  ]);
  assert.equal(thoughts[0].agent, "Tribos Orchestrator");
  assert.equal(thoughts[0].title, "Pre-clinical testing of the clinical rig");
  assert.equal(thoughts[0].text, "Clinical data");
  assert.equal(thoughts[1].agent, undefined);
});

test("LOG-31: saved messages keep their answer text when read back", () => {
  const localStorage = new MapStorage();
  (globalThis as any).window = { localStorage, sessionStorage: new MapStorage() };
  const svc = new LocalStorageService();
  svc.configure("http://localhost:8000", "token");
  const content = "Pre-clinical testing of the clinical rig passed.";
  svc.saveMessages("t1", [
    { id: "a", sender: "assistant", content, agent: "Clinical Orchestrator", timestamp: "", steps: [], thoughts: [], selected_agents: [] } as any,
  ]);
  const [m] = svc.getMessages("t1");
  assert.equal(m.content, content);
  assert.equal(m.agent, "Tribos Orchestrator");
});

// LOG-33 ------------------------------------------------------------------------------------------------------

test("LOG-33: only retired model ids are migrated; the current Ultra model and the default are kept", () => {
  assert.equal(migrateSavedModel("nvidia/nemotron-3-ultra-550b-a55b"), "nvidia/nemotron-3-ultra-550b-a55b");
  assert.equal(migrateSavedModel(DEFAULT_MODEL_ID), DEFAULT_MODEL_ID);
  assert.equal(migrateSavedModel("gpt-4o"), "gpt-4o");
  assert.equal(migrateSavedModel("nvidia/nemotron-3-super-120b-a12b"), DEFAULT_MODEL_ID);
  assert.equal(migrateSavedModel("nvidia/llama-3.1-nemotron-70b-instruct"), DEFAULT_MODEL_ID);
});

// LOG-37 ------------------------------------------------------------------------------------------------------

test("LOG-37: a job's question is its display_message, else its message", () => {
  assert.equal(jobQuestion({ request: { message: "q\n\n[image: x]", display_message: "q" } }), "q");
  assert.equal(jobQuestion({ request: { message: "q" } }), "q");
  assert.equal(jobQuestion({}), "");
});

// BRK-8 -------------------------------------------------------------------------------------------------------

test("BRK-8: invalidating a project fact sends the server's `invalidate` field", async () => {
  await withFetch([() => new Response("{}", { status: 200 })], async (calls) => {
    await patchFact("http://x", noAuth, "prj_abcdef", "f1", { invalidate: true, reason: "superseded" });
    assert.equal(calls[0].url, "http://x/api/projects/prj_abcdef/memory/f1");
    assert.equal(calls[0].init.method, "PATCH");
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), { invalidate: true, reason: "superseded" });
  });
});

// LOG-35 ------------------------------------------------------------------------------------------------------

test("LOG-35: a job's error event is terminal and carries the server's message and request id", async () => {
  const body = () =>
    new Response(
      sseBody([
        'id: 1\ndata: {"seq":1,"type":"thought","data":{"id":"s"}}\n\n',
        'id: 2\ndata: {"seq":2,"type":"error","detail":"The job failed on the server (request id abc123); details are in the server log.","request_id":"abc123"}\n\n',
      ]),
      { status: 200 }
    );
  await withFetch([body], async (calls) => {
    const seen: string[] = [];
    await assert.rejects(
      streamJobEvents("http://x", noAuth, "job_1", 0, (ev: any) => void seen.push(ev.type), undefined, { reconnectDelayMs: 1 }),
      (err: unknown) => err instanceof JobFailedError && err.requestId === "abc123" && /request id abc123/.test(err.message)
    );
    assert.deepEqual(seen, ["thought"]);
    assert.equal(calls.length, 1, "an error event is not treated as a dropped connection");
  });
});

test("LOG-35: a replayed error of an earlier attempt is ignored once a resume starts a new attempt", async () => {
  const body = () =>
    new Response(
      sseBody([
        'id: 1\ndata: {"seq":1,"type":"error","detail":"The server stopped."}\n\n',
        'id: 2\ndata: {"seq":2,"type":"job","status":"queued","resumed":true}\n\n',
        'id: 3\ndata: {"seq":3,"type":"done","result":{"response":"ok"}}\n\n',
      ]),
      { status: 200 }
    );
  await withFetch([body], async () => {
    const seen: string[] = [];
    await streamJobEvents("http://x", noAuth, "job_1", 0, (ev: any) => {
      seen.push(ev.type);
      return ev.type === "done";
    });
    assert.deepEqual(seen, ["job", "done"]);
  });
});

test("LOG-35: a cancelled job's error event is reported as cancelled", async () => {
  const body = () => new Response(sseBody(['id: 4\ndata: {"seq":4,"type":"error","detail":"The job was cancelled.","cancelled":true}\n\n']), { status: 200 });
  await withFetch([body], async () => {
    await assert.rejects(
      streamJobEvents("http://x", noAuth, "job_1", 3, () => false),
      (err: unknown) => err instanceof JobFailedError && err.cancelled
    );
  });
});

// LOG-32 ------------------------------------------------------------------------------------------------------

test("LOG-32: the upload pre-check follows the server's kinds (table, hdf5, mat, paper), not h5ad/SBML", () => {
  const file = (name: string, size = 10) => ({ name, size }) as File;
  for (const ok of ["a.csv", "a.TSV", "a.xlsx", "a.parquet", "a.json", "a.h5", "a.hdf5", "a.mat", "a.pdf"]) assert.equal(precheckFile(file(ok)), null, ok);
  for (const bad of ["a.h5ad", "a.xml", "a.sbml", "noext"]) assert.match(String(precheckFile(file(bad))), /Unsupported file type/, bad);
  assert.equal(kindForFile("x.h5"), "hdf5");
  assert.equal(kindForFile("x.mat"), "mat");
  assert.match(String(precheckFile(file("a.csv", 101 * 1024 * 1024))), /Table files are limited to 100 MB/);
  assert.equal(acceptAttr(), ".csv,.tsv,.xlsx,.parquet,.json,.h5,.hdf5,.mat,.pdf");
});

test("LOG-32: GET /api/datasets/limits replaces the defaults; a failure keeps them", async () => {
  const served = { extensions: { ".csv": "table", ".h5": "hdf5", ".h5ad": "anndata" }, max_bytes: { table: 5, hdf5: 7, mat: "x" } };
  await withFetch([() => new Response(JSON.stringify(served), { status: 200 })], async (calls) => {
    const limits = await fetchDatasetLimits("http://x", noAuth);
    assert.equal(calls[0].url, "http://x/api/datasets/limits");
    assert.deepEqual(limits.extensions, { ".csv": "table", ".h5": "hdf5" });
    assert.deepEqual(limits.max_bytes, { table: 5, hdf5: 7, mat: DEFAULT_DATASET_LIMITS.max_bytes.mat, paper: DEFAULT_DATASET_LIMITS.max_bytes.paper });
    assert.match(String(precheckFile({ name: "a.mat", size: 1 } as File, limits)), /Unsupported/);
  });
  await withFetch([() => new Response("{}", { status: 404 })], async () => {
    assert.deepEqual(await fetchDatasetLimits("http://x", noAuth), DEFAULT_DATASET_LIMITS);
  });
  assert.deepEqual(normalizeDatasetLimits(null), DEFAULT_DATASET_LIMITS);
});

test("LOG-32 / BRK-9: dimensions and sources use STEM wording; legacy values still display", () => {
  const rec = (validation: Record<string, unknown>, kind = "table") => ({ kind, validation: { warnings: [], ...validation } }) as any;
  assert.equal(dimsOf(rec({ n_rows: 1200, n_columns: 8 })), "1,200 rows × 8 columns");
  assert.equal(dimsOf(rec({ n_obs: 3, n_vars: 2 }, "legacy")), "3 rows × 2 columns");
  assert.equal(dimsOf(rec({ datasets: ["a", "b"] }, "mat")), "2 variables");
  assert.equal(sourceLabel("public_repository"), "Public repository");
  assert.equal(sourceLabel("geo"), "GEO");
  assert.equal(sourceLabel("something_new"), "something_new");
});

// SUP-8 -------------------------------------------------------------------------------------------------------

test("SUP-8: phronesis keys move to their tribos names once, never overwriting a current value", () => {
  const s = new MapStorage();
  s.setItem("phronesis_investigations_v2@abc", "[1]");
  s.setItem("phronesis_thread_messages_v2_abc__t1", "[]");
  s.setItem("phronesis_user_settings_v2", '{"selectedModel":"old"}');
  s.setItem("phronesis-auth-token", "tok");
  s.setItem("phronesis-backend-url", "http://h:8000");
  s.setItem("phronesis-theme", "light");
  s.setItem("tribos-theme", "dark");
  s.setItem("__phronesis_storage_test__", "1");
  s.setItem("unrelated", "x");
  const moved = migrateLegacyKeys(s);
  assert.deepEqual(moved.sort(), [
    "tribos-auth-token",
    "tribos-backend-url",
    "tribos_investigations_v2@abc",
    "tribos_thread_messages_v2_abc__t1",
    "tribos_user_settings_v2",
  ]);
  assert.equal(s.getItem("tribos-auth-token"), "tok");
  assert.equal(s.getItem("tribos-theme"), "dark", "an existing tribos value is kept");
  assert.equal(s.getItem("tribos_investigations_v2@abc"), "[1]");
  assert.deepEqual(
    Array.from(s.map.keys()).filter((k) => k.includes("phronesis")),
    [],
    "every old key is deleted"
  );
  assert.equal(s.getItem("unrelated"), "x");
  assert.deepEqual(migrateLegacyKeys(s), [], "a second run does nothing");
});

test("SUP-8: storage that throws is left alone", () => {
  const broken = {
    get length(): number {
      throw new Error("SecurityError");
    },
  } as any;
  assert.deepEqual(migrateLegacyKeys(broken), []);
  assert.deepEqual(migrateLegacyKeys(null), []);
});

test("SUP-8: the service migrates device and session storage", () => {
  const localStorage = new MapStorage();
  const sessionStorage = new MapStorage();
  localStorage.setItem("phronesis_user_settings_v2", '{"selectedModel":"gpt-4o"}');
  sessionStorage.setItem("phronesis-auth-token", "tok");
  (globalThis as any).window = { localStorage, sessionStorage };
  const svc = new LocalStorageService();
  svc.migrateLegacyStorage();
  assert.equal(svc.getSettings().selectedModel, "gpt-4o");
  assert.equal(sessionStorage.getItem("tribos-auth-token"), "tok");
  assert.equal(sessionStorage.getItem("phronesis-auth-token"), null);
});

// Drafts ------------------------------------------------------------------------------------------------------

function draftKeys(s: MapStorage): string[] {
  return Array.from(s.map.keys()).filter((k) => k.startsWith("tribos_draft_v1_"));
}

test("drafts: deleting a conversation removes its unsent draft", () => {
  const localStorage = new MapStorage();
  (globalThis as any).window = { localStorage, sessionStorage: new MapStorage() };
  const svc = new LocalStorageService();
  svc.configure("http://localhost:8000", "token");
  const inv = svc.createNewThread("A");
  svc.saveDraft(inv.id, "half-typed question");
  assert.equal(svc.getDraft(inv.id), "half-typed question");
  svc.deleteInvestigation(inv.id);
  assert.equal(svc.getDraft(inv.id), "");
  assert.deepEqual(draftKeys(localStorage), []);
});

test("drafts: an expired conversation's draft is pruned with it", () => {
  const localStorage = new MapStorage();
  (globalThis as any).window = { localStorage, sessionStorage: new MapStorage() };
  const svc = new LocalStorageService();
  svc.configure("http://localhost:8000", "token");
  const inv = svc.createNewThread("Old");
  svc.saveDraft(inv.id, "draft");
  const removed = svc.pruneExpired(Date.now() + 40 * 86_400_000);
  assert.deepEqual(removed, [inv.id]);
  assert.deepEqual(draftKeys(localStorage), []);
});

test("drafts: changing where history is kept moves drafts along, leaving none on the device", () => {
  const localStorage = new MapStorage();
  const sessionStorage = new MapStorage();
  (globalThis as any).window = { localStorage, sessionStorage };
  const svc = new LocalStorageService();
  svc.configure("http://localhost:8000", "token");
  const inv = svc.createNewThread("A");
  svc.saveDraft(inv.id, "keep me");
  svc.setHistoryPrefs({ mode: "session" });
  assert.deepEqual(draftKeys(localStorage), []);
  assert.equal(draftKeys(sessionStorage).length, 1);
  assert.equal(svc.getDraft(inv.id), "keep me");
});

// Polish: MarkdownRenderer's [web] marker replacement ------------------------------------------------------------

test("[web] markers become a link with $& and parentheses kept literal", async () => {
  const { linkWebMarkers } = await import("../src/lib/markdownSafety.ts");
  const out = linkWebMarkers("See [web] and [web search].", "Price $& [list]", "https://e.org/a_(b) c");
  const link = String.raw`[Price $& \[list\]](https://e.org/a_%28b%29%20c)`;
  assert.equal(out, `See ${link} and ${link}.`);
});
