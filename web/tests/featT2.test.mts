import assert from "node:assert/strict";
import test from "node:test";
import { FEATURE_ARTIFACT_KEYS } from "../src/components/artifacts/artifactKeys.ts";
import {
  allValues1D,
  allValues2D,
  boundarySummary,
  colourLevel,
  convergenceRows,
  equationName,
  frames1D,
  frames2D,
  heatRuns,
  pdeBadges,
  rampColours,
  valueRange,
} from "../src/components/artifacts/pdeData.ts";

test("T2: the pde card is registered under its own key", () => {
  assert.ok(FEATURE_ARTIFACT_KEYS.includes("pde"));
  assert.equal(new Set(FEATURE_ARTIFACT_KEYS).size, FEATURE_ARTIFACT_KEYS.length);
});

test("T2: 1D frames keep only snapshots that fit the x grid", () => {
  const frames = frames1D({
    x: [0, 0.5, 1],
    snapshots: [{ t: 0, values: [0, 1, 0] }, { t: 0.1, values: [0, 0.5] }, { t: 0.2, values: [0, 0.25, 0] }, { values: "x" }],
  });
  assert.deepEqual(frames.map((f) => f.t), [0, 0.2]);
});

test("T2: 2D frames are rows over x with one value per y", () => {
  const d = { dimension: 2, x: [0, 1], y: [0, 0.5, 1], snapshots: [{ t: 0, values: [[1, 2, 3], [4, 5, 6]] }, { t: 1, values: [[1, 2], [3, 4]] }] };
  const frames = frames2D(d);
  assert.equal(frames.length, 1);
  assert.deepEqual(valueRange(allValues2D(frames)), { lo: 1, hi: 6 });
});

test("T2: the value range spans every frame and survives constant or missing data", () => {
  const frames = frames1D({ x: [0, 1], snapshots: [{ t: 0, values: [0, 2] }, { t: 1, values: [-1, 1] }] });
  assert.deepEqual(valueRange(allValues1D(frames)), { lo: -1, hi: 2 });
  assert.deepEqual(valueRange([3, 3]), { lo: 2.85, hi: 3.15 });
  assert.deepEqual(valueRange([NaN]), { lo: 0, hi: 1 });
});

test("T2: colour levels clamp to the ramp and runs merge equal neighbours", () => {
  assert.equal(colourLevel(0, 0, 1, 24), 0);
  assert.equal(colourLevel(1, 0, 1, 24), 23);
  assert.equal(colourLevel(2, 0, 1, 24), 23);
  assert.equal(colourLevel(NaN, 0, 1, 24), -1);
  // Column-major rows (x index outer): along y = 0 the values are 0, 0, 1 -> two runs.
  const runs = heatRuns([[0, 1], [0, 1], [1, NaN]], 0, 1, 2);
  assert.deepEqual(runs, [
    { xi: 0, yj: 0, span: 2, level: 0 },
    { xi: 2, yj: 0, span: 1, level: 1 },
    { xi: 0, yj: 1, span: 2, level: 1 },
  ]);
  const colours = rampColours(24);
  assert.equal(colours.length, 24);
  assert.match(colours[0], /var\(--heatmap-0\) 100%/);
  assert.match(colours[23], /var\(--heatmap-4\) 0%, var\(--heatmap-5\)/);
});

test("T2: the convergence table falls back to the change to the finer grid", () => {
  const rows = convergenceRows({
    convergence: { levels: [{ n: 21, h: 0.05, difference_to_finer: 1e-3 }, { n: 41, h: 0.025, difference_to_finer: 2.5e-4, order: 2 }, { n: 81, h: 0.0125 }] },
  });
  assert.deepEqual(rows.map((r) => r.error), [1e-3, 2.5e-4, null]);
  assert.deepEqual(rows.map((r) => r.order), [null, 2, null]);
});

test("T2: the badges report every check honestly", () => {
  const badges = pdeBadges({
    convergence: { converged: false, order: 0.4, expected_order: 2, note: "not smooth" },
    verification: { exact_solution: "sin(pi*x)", relative_error: 0.2, agrees: false },
    conservation: { kind: "energy", relative_drift: 1e-14, conserved: true },
    stability: { status: "adapted", dt: 0.0036, number: 0.89, limit: 1, name: "Courant number c*dt/h", scheme: "leapfrog" },
  });
  assert.deepEqual(badges.map((b) => b.tone), ["warn", "bad", "ok", "warn"]);
  assert.equal(badges[0].text, "Not shown converged (order 0.4 of 2)");
  assert.equal(badges[1].text, "Differs from analytic (20%)");
  assert.equal(badges[2].text, "Energy conserved (1e-14)");
  assert.match(badges[3].text, /^Step adapted to dt 0.0036/);
  const stable = pdeBadges({ stability: { status: "stable", number: 0.36, limit: 0.5, name: "diffusion number alpha*dt" } });
  assert.equal(stable[0].text, "Stable (diffusion 0.36 ≤ 0.5)");
  assert.deepEqual(pdeBadges({}), []);
});

test("T2: names and boundary summaries read naturally", () => {
  assert.equal(equationName("fisher_kpp"), "Fisher-KPP");
  assert.equal(equationName("new_thing"), "new thing");
  assert.equal(boundarySummary({ x0: "periodic", x1: "periodic" }), "periodic edges");
  assert.equal(boundarySummary({ x0: "dirichlet", x1: "neumann" }), "x0 dirichlet, x1 neumann");
});
