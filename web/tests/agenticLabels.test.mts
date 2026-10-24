// Run with: node --test web/tests/agenticLabels.test.mts   (Node 24 strips the TypeScript types)
import { test } from "node:test";
import assert from "node:assert/strict";
import * as labels from "../src/components/agentic/evidenceLabels.ts";
import * as cols from "../src/components/agentic/tableColumns.ts";

const { prettyEvidenceKey, evidenceDisplayNames } = labels;
const { visibleColumns, columnKind, isEmptyCell } = cols;

test("prettyEvidenceKey strips the agent phase prefix and names the tool", () => {
  assert.equal(prettyEvidenceKey("agent.gaps.4.archivon"), "Scholarly literature (gap search)");
  assert.equal(prettyEvidenceKey("agent.gaps.5.websurfer"), "web search (gap search)");
  assert.equal(prettyEvidenceKey("agent.plan_execute.2.axiom"), "SymPy symbolic engine (plan step)");
  assert.equal(prettyEvidenceKey("oeis"), "OEIS");
  assert.equal(prettyEvidenceKey("tool:arxiv"), "arXiv");
  assert.equal(prettyEvidenceKey("ARXIV:2309.17452"), "ARXIV:2309.17452");
  assert.equal(prettyEvidenceKey("agent.debate.3.some_tool"), "some tool (debate)");
});

test("evidenceDisplayNames prefers backend labels, falls back to keys and collapses duplicates", () => {
  assert.deepEqual(
    evidenceDisplayNames(["agent.gaps.4.archivon", "agent.gaps.5.websurfer"], ["arXiv (gap round 1)", "web search (gap round 1)"]),
    ["arXiv (gap round 1)", "web search (gap round 1)"]
  );
  assert.deepEqual(evidenceDisplayNames(["agent.gaps.4.archivon", "agent.gaps.9.archivon"]), ["Scholarly literature (gap search)"]);
  assert.deepEqual(evidenceDisplayNames(["oeis"], undefined), ["OEIS"]);
  assert.deepEqual(evidenceDisplayNames(null), []);
});

test("visibleColumns hides columns whose every value is empty or n/a", () => {
  const rows = [
    { entity: "Euler", formula: "e^(i*pi)+1=0", type: "n/a", score: 0.9 },
    { entity: "Euler", formula: "e^(i*x)", type: "N/A", score: null },
    { entity: "Fourier", formula: "int f(t)e^(-iwt)dt", type: "", score: 0.4 },
  ];
  assert.deepEqual(visibleColumns(rows), ["entity", "formula", "score"]);
  // Hidden columns do not use up the column cap.
  assert.deepEqual(visibleColumns([{ a: null, b: "x", c: "y" }], 2), ["b", "c"]);
  assert.equal(isEmptyCell("—"), true);
  assert.equal(isEmptyCell(0), false);
});

test("columnKind gives only long text a wrapping width", () => {
  const rows = [
    { symbol: "hbar", desc: "reduced Planck constant in quantum mechanics and atomic physics", n: 3 },
    { symbol: "c", desc: "speed of light in vacuum", n: 5 },
  ];
  assert.equal(columnKind(rows, "symbol"), "short");
  assert.equal(columnKind(rows, "desc"), "long");
  assert.equal(columnKind(rows, "n"), "num");
});
