import { test } from "node:test";
import assert from "node:assert/strict";
import { extent, linePath, nearestIndex, niceTicks, normalizeBlock, parseAnswerUi, parseUiFence } from "../src/lib/genui.ts";

const panel = {
  version: 1,
  title: "Results at a glance",
  source: "computed",
  blocks: [
    { type: "stats", title: "Key quantities", items: [{ label: "natural frequency", value: "5", unit: "rad/s", exact_latex: "5", verified: true }] },
    { type: "equation", latex: "x(t)=e^{-t}", parts: [{ label: "Transient", latex: "e^{-t}" }], checks: [{ name: "ODE", passed: true }] },
    { type: "chart", x: { label: "t", unit: "s" }, y: { label: "x", unit: "m" }, series: [{ name: "x(t)", points: [[0, 0.1], [1, 0.2], [2, Number.NaN]] }], marks: [[1, 0.2]] },
    { type: "bogus" },
  ],
};

test("genui: the panel keeps valid blocks and drops unknown ones", () => {
  const ui = parseAnswerUi(panel);
  assert.ok(ui);
  assert.deepEqual(ui.blocks.map((b) => b.type), ["stats", "equation", "chart"]);
  const chart = ui.blocks[2];
  assert.equal(chart.type === "chart" && chart.series[0].points.length, 2, "non-finite points are dropped");
  assert.equal(parseAnswerUi({ ...panel, version: 2 }), null, "an unknown spec version is not rendered");
  assert.equal(parseAnswerUi(null), null);
});

test("genui: writer fences parse, compact tables normalise, bad JSON stays code", () => {
  const t = parseUiFence('{"type":"table","columns":["t (s)","x (m)"],"rows":[["0.5","0.0123"],["1","-0.04"]]}');
  assert.ok(t && t.type === "table");
  assert.deepEqual(t.rows[0], { "0": "0.5", "1": "0.0123" });
  assert.equal(t.columns[1].align, "right", "numeric columns are right-aligned");
  assert.equal(parseUiFence("{not json"), null);
  assert.equal(parseUiFence('{"type":"callout","tone":"loud","text":"hi"}')?.type, "callout");
  assert.equal(normalizeBlock({ type: "callout", text: "" }), null);
});

test("genui: chart geometry", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(-0.1, 0.1, 4), [-0.1, -0.05, 0, 0.05, 0.1]);
  const pts: [number, number][] = [[0, 0], [1, 1], [2, 4], [3, 9]];
  assert.equal(nearestIndex(pts, 1.4), 1);
  assert.equal(nearestIndex(pts, 1.6), 2);
  assert.equal(nearestIndex(pts, 99), 3);
  const [lo, hi] = extent([{ name: "a", points: pts }], 1);
  assert.ok(lo < 0 && hi > 9, "the y range is padded");
  assert.equal(linePath([[0, 0], [1, 1]], (v) => v * 10, (v) => 100 - v), "M0.00,100.00L10.00,99.00");
});

test("genui: end-of-line labels never overlap and stay in the plot", async () => {
  const { directLabelYs } = await import("../src/lib/genui.ts");
  const ys = directLabelYs([100, 102], 10, 200);
  assert.ok(Math.abs(ys[0] - ys[1]) >= 15);
  const low = directLabelYs([199, 200, 200], 10, 200);
  assert.ok(Math.max(...low) <= 200 && Math.min(...low) >= 10);
  assert.deepEqual(directLabelYs([50, 150], 10, 200), [50, 150], "separated labels stay where their lines end");
});

test("genui: checks blocks, log axes and labelled marks", async () => {
  const { normalizeBlock, logTicks } = await import("../src/lib/genui.ts");
  const checks = normalizeBlock({ type: "checks", title: "Independent checks", items: [{ name: "energy balance", passed: true, detail: "residual 1e-15" }, { name: "" }] });
  assert.ok(checks && checks.type === "checks" && checks.items.length === 1 && checks.items[0].passed);
  const chart = normalizeBlock({
    type: "chart",
    x: { label: "h", scale: "log" },
    y: { label: "err", scale: "log" },
    series: [{ name: "e", points: [[0.05, 5.6e-5], [0.0125, 2.2e-7], [0.025, 3.5e-6], [0, 1]] }],
    marks: [[4, 0.46, "forcing"], [-1, 2]],
  });
  assert.ok(chart && chart.type === "chart");
  assert.deepEqual(chart.series[0].points.map((p) => p[0]), [0.0125, 0.025, 0.05], "non-positive values leave a log axis; x is sorted");
  assert.deepEqual(chart.marks, [{ x: 4, y: 0.46, label: "forcing" }]);
  assert.deepEqual(logTicks(-7.2, -3.9), [-7, -6, -5, -4]);
  assert.equal(logTicks(-20, 0, 6).length <= 6, true);
});

test("genui: a one-line exact solution is rebuilt on two labelled lines; a two-line one is kept", async () => {
  const { equationLatex } = await import("../src/lib/genui.ts");
  const parts = [
    { label: "Transient", latex: String.raw`e^{-t}\cos t` },
    { label: "Steady state", latex: String.raw`\sin 2t` },
  ];
  const old = equationLatex({ type: "equation", latex: String.raw`x(t) = e^{-t}\cos t + \sin 2t`, parts, checks: [] });
  assert.equal(old.split, true);
  assert.equal(
    old.latex,
    String.raw`\begin{aligned} x(t) &= \underbrace{e^{-t}\cos t}_{\text{transient}} ` +
      "\\\\" +
      String.raw` &\quad + \underbrace{\sin 2t}_{\text{steady state}} \end{aligned}`,
  );
  const kept = String.raw`\begin{aligned} x &= 1 \end{aligned}`;
  assert.deepEqual(equationLatex({ type: "equation", latex: kept, parts, checks: [] }), { latex: kept, split: false });
  assert.equal(equationLatex({ type: "equation", latex: "x = 1", parts: [], checks: [] }).split, false);
});
