// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathIndices } from "../src/lib/decimate.ts";

test("a long oscillation keeps every peak and trough when thinned for drawing", () => {
  const t = Array.from({ length: 2001 }, (_, i) => i * 0.01);
  const y = t.map((ti) => 0.46225 * Math.cos(4 * ti - 0.588));
  const idx = pathIndices(y, 600);
  assert.ok(idx.length <= 602, `${idx.length} points`);
  const drawn = idx.map((i) => y[i]);
  assert.equal(Math.max(...drawn), Math.max(...y));
  assert.equal(Math.min(...drawn), Math.min(...y));
  assert.equal(idx[0], 0);
  assert.equal(idx[idx.length - 1], 2000);
  assert.deepEqual([...idx].sort((a, b) => a - b), idx); // time order
});

test("a short series is drawn through every finite sample", () => {
  assert.deepEqual(pathIndices([1, Number.NaN, 3], 600), [0, 2]);
});
