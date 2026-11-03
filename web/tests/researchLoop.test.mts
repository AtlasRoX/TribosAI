// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { TIER_LABEL, formatDuration, loopProgress, type Campaign } from "../src/services/campaignService.ts";

const base = { campaign_id: "cmp_0000000000000000", goal: "g", title: "t", status: "running", model: null, effort_level: "high",
  thread_id: "th", created_at: 0, updated_at: 0, finished_at: null, error: null, current_stage: null, stages: [], mode: "loop" } as unknown as Campaign;

test("durations read as seconds, minutes or hours", () => {
  assert.equal(formatDuration(42), "42 s");
  assert.equal(formatDuration(12 * 60 + 20), "12 min");
  assert.equal(formatDuration(3600 + 5 * 60), "1 h 05 min");
});

test("loop progress counts settled deliverables from the charter, else from the list summary", () => {
  const full = { ...base, charter: { summary: "", hypotheses: [], tests: [], deliverables: [
    { id: "D1", status: "done" }, { id: "D2", status: "infeasible" }, { id: "D3", status: "partial" }] } } as unknown as Campaign;
  assert.deepEqual(loopProgress(full), { done: 2, total: 3 });
  const listed = { ...base, summary: { deliverables: 4, done: 1, tests: 6, findings: 3, rounds: 1 } } as Campaign;
  assert.deepEqual(loopProgress(listed), { done: 1, total: 4 });
});

test("every verification tier has a reader-facing label", () => {
  for (const tier of ["formal", "certified", "replicated", "computed", "sourced", "reasoned", "none"]) {
    assert.ok(TIER_LABEL[tier], tier);
  }
  assert.equal(TIER_LABEL.formal, "Lean-verified");
});
