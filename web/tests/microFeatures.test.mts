// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
// The pure logic behind the composer, answer and export micro-features.
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyTemplate, matchingCommands, slashQuery } from "../src/lib/slashCommands.ts";
import { expectedSeconds, formatDuration, median, remainingText } from "../src/lib/routeTiming.ts";
import { unitHints } from "../src/lib/unitHints.ts";
import { linkedValuesFrom, matchValue, rehypeMathBlocks, rehypeValueLinks } from "../src/lib/mathInteractions.ts";
import { inlineToLatex, markdownToLatex } from "../src/lib/markdownToLatex.ts";
import { crc32, makeZip } from "../src/lib/zip.ts";
import { answerSections, sectionSlug } from "../src/lib/sections.ts";
import { inUnits, rerunDefaults, rerunQuestion } from "../src/lib/oscillatorForms.ts";

test("slash commands: the token, its matches and the template cursor", () => {
  assert.equal(slashQuery("/sim"), "sim");
  assert.equal(slashQuery("/simulate the beam"), null); // a space ends the command
  assert.equal(slashQuery("simulate"), null);
  assert.deepEqual(matchingCommands("s").map((c) => c.name), ["solve", "simulate", "supervisor"]);
  const { text, cursor } = applyTemplate("Derive |, showing every step.");
  assert.equal(text, "Derive , showing every step.");
  assert.equal(cursor, 7);
});

test("timing: median of past runs, priors before three runs, and a readable estimate", () => {
  assert.equal(median([300, 100, 200]), 200);
  assert.equal(median([100, 200, 300, 400]), 250);
  assert.equal(expectedSeconds("Direct workflow", {}), 180);
  assert.equal(expectedSeconds("Direct workflow", { "Direct workflow": [60, 90, 120] }), 90);
  assert.equal(formatDuration(150), "3 min");
  assert.equal(remainingText(300, 60), "about 4 min left");
  assert.equal(remainingText(300, 295), "almost done");
  assert.equal(remainingText(300, 500), "taking longer than usual");
});

test("unit hints name the quantity, and a compound unit is not also read as its parts", () => {
  const hints = unitHints("with m = 2 kg, c = 3 N·s/m, k = 50 N/m, F0 = 10 N, ω = 4 rad/s");
  assert.deepEqual(hints.map((h) => h.unit), ["N·s/m", "N/m", "N", "rad/s"]);
  assert.equal(hints[0].quantity, "damping coefficient");
  assert.deepEqual(unitHints("Explain why the sky is blue."), []);
});

const VALUES = [
  { key: "param:steady_state_amplitude", value: 0.4622502, label: "Steady-state amplitude" },
  { key: "param:phase_lag", value: 33.690068, label: "Phase lag (degrees)" },
  { key: "energy:work_in", value: 104.1749, label: "Work in by forcing" },
];

test("a written number links to the computed value it states, within its own rounding", () => {
  assert.equal(matchValue("0.46225", VALUES)?.key, "param:steady_state_amplitude");
  assert.equal(matchValue("0.4623", VALUES)?.key, "param:steady_state_amplitude");
  assert.equal(matchValue("33.69", VALUES)?.key, "param:phase_lag");
  assert.equal(matchValue("104.175", VALUES)?.key, "energy:work_in");
  assert.equal(matchValue("0.47", VALUES), null); // a different number
  assert.equal(matchValue("4", VALUES), null); // a small integer is too common to mean a computed value
});

test("value links wrap prose numbers and inline math, never code", () => {
  const tree: any = {
    type: "root",
    children: [
      { type: "element", tagName: "p", children: [{ type: "text", value: "The amplitude is 0.46225 m; see 4 cases." }] },
      { type: "element", tagName: "code", children: [{ type: "text", value: "0.46225" }] },
      {
        type: "element",
        tagName: "span",
        properties: { className: ["katex"] },
        children: [{ type: "element", tagName: "annotation", children: [{ type: "text", value: "\\phi = 33.690^\\circ" }] }],
      },
    ],
  };
  rehypeValueLinks({ values: VALUES })(tree);
  const p = tree.children[0];
  assert.equal(p.children.length, 3);
  assert.equal(p.children[1].tagName, "mark");
  assert.equal(p.children[1].properties.dataValueKey, "param:steady_state_amplitude");
  assert.equal(tree.children[1].children[0].type, "text"); // code untouched
  assert.equal(tree.children[2].tagName, "mark"); // the inline formula as a whole
  assert.equal(tree.children[2].properties.dataValueKey, "param:phase_lag");
});

test("display equations get a wrapper that carries their LaTeX source", () => {
  const tree: any = {
    type: "root",
    children: [
      {
        type: "element",
        tagName: "span",
        properties: { className: ["katex-display"] },
        children: [{ type: "element", tagName: "annotation", children: [{ type: "text", value: "x = 1" }] }],
      },
    ],
  };
  rehypeMathBlocks()(tree);
  assert.equal(tree.children[0].tagName, "div");
  assert.deepEqual(tree.children[0].properties, { className: ["math-block"], dataLatex: "x = 1" });
});

test("linked values come from the verification report: parameters, degrees and energy terms", () => {
  const values = linkedValuesFrom({
    ode_verification: {
      parameters: { phase_lag: { value: 0.588, degrees: 33.69 }, regime: { value: "underdamped" } },
      energy: { work_in: 104.17 },
    },
  });
  assert.deepEqual(values.map((v) => [v.key, v.value]), [["param:phase_lag", 0.588], ["param:phase_lag", 33.69], ["energy:work_in", 104.17]]);
  assert.deepEqual(linkedValuesFrom({}), []);
});

test("Markdown becomes LaTeX: headings, emphasis, lists, tables; math passes through", () => {
  assert.equal(inlineToLatex("**X** = $x_1$ and 50% of `k_x`"), "\\textbf{X} = $x_1$ and 50\\% of \\texttt{k\\_x}");
  const tex = markdownToLatex(
    "## 1. Results\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n$$\nx = 1\n$$\n"
  );
  assert.match(tex, /\\subsection\{Results\}/);
  assert.match(tex, /\\begin\{itemize\}\n {2}\\item one\n {2}\\item two\n\\end\{itemize\}/);
  assert.match(tex, /\\begin\{tabular\}\{ll\}/);
  assert.match(tex, /\\\[\nx = 1\n\\\]/);
});

test("the zip writer: a correct CRC-32 and a readable archive", () => {
  assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926); // the standard check value
  const zip = makeZip([{ name: "a.txt", content: "hello" }, { name: "dir/b.csv", content: "t,x\n0,1\n" }], new Date(2026, 9, 25, 12, 0, 0));
  const view = new DataView(zip.buffer);
  assert.equal(view.getUint32(0, true), 0x04034b50); // first local header
  const end = zip.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054b50); // end of central directory
  assert.equal(view.getUint16(end + 10, true), 2); // two entries
  const name = new TextDecoder().decode(zip.slice(30, 35));
  assert.equal(name, "a.txt");
  assert.equal(new TextDecoder().decode(zip.slice(35, 40)), "hello");
});

test("sections: slugs and the second-level headings outside code", () => {
  assert.equal(sectionSlug("1. Analytical **Solution**"), "1-analytical-solution");
  assert.deepEqual(
    answerSections("## A\ntext\n```\n## not a heading\n```\n## B\n### sub").map((s) => s.title),
    ["A", "B"]
  );
});

test("units: SI to US customary, and the re-run question restates the problem with new values", () => {
  const [v, u] = inUnits(0.46225, "m", "us");
  assert.equal(u, "in");
  assert.ok(Math.abs((v as number) - 18.199) < 1e-3);
  assert.deepEqual(inUnits(5, "rad/s", "us"), [5, "rad/s"]);
  assert.deepEqual(inUnits(2, "m", "si"), [2, "m"]);
  const defaults = rerunDefaults({
    energy: { m: 2, c: 3, k: 50 },
    parameters: { forcing_amplitude: { value: 10 }, forcing_frequency: { value: 4 } },
    initial_state: { x: 0.1, v: 0 },
    t_end: 20,
  });
  assert.ok(defaults);
  const q = rerunQuestion({ ...defaults!, c: "5" });
  assert.match(q, /m = 2 kg, c = 5 N·s\/m, k = 50 N\/m, F0 = 10 N, ω = 4 rad\/s, x\(0\) = 0\.1 m, and x'\(0\) = 0/);
  assert.match(q, /over 0–20 s/);
  assert.equal(rerunDefaults({ energy: {} }), null);
});
