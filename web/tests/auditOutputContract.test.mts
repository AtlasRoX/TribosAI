// Run with: node --test web/tests/auditOutputContract.test.mts   (Node 24 strips the TypeScript types)
// Audit I17/T07/T09: the requested line structure survives rendering; the stored and copied text is never altered.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderableAnswer } from "../src/lib/assistantAnswer.ts";
import { stripVerificationBanner } from "../src/lib/verificationState.ts";

test("a literal two-line answer renders as two lines, not one CommonMark paragraph", () => {
  const out = renderableAnswer("ALPHA\nBETA", { output_contract: { literal: "ALPHA\nBETA", exact_lines: 2 } });
  assert.equal(out, "ALPHA  \nBETA"); // a Markdown hard break between the lines
});

test("plain-text lines keep their characters and indentation (no Markdown syntax applies)", () => {
  const text = "red\n  green *not bold*\n# not a heading\nআমি বাংলায় গান গাই";
  const out = renderableAnswer(text, { output_contract: { plain_text: true } });
  const lines = out.split("  \n");
  assert.equal(lines.length, 4);
  assert.equal(lines[1], "  green \\*not bold\\*");
  assert.equal(lines[2], "\\# not a heading");
  assert.equal(lines[3], "আমি বাংলায় গান গাই");
});

test("a line-count contract keeps Markdown and math but breaks every line", () => {
  const out = renderableAnswer("A: $1681 = 41^2$\nB: 1763 = 41 * 43", { output_contract: { exact_lines: 2 } });
  assert.equal(out, "A: $1681 = 41^2$  \nB: 1763 = 41 * 43");
});

test("answers without a contract are rendered exactly as before", () => {
  const md = "# Title\n\nSome *text*\nsoft wrapped";
  assert.equal(renderableAnswer(md, {}), md);
  assert.equal(renderableAnswer(md, undefined), md);
  assert.equal(renderableAnswer(md, { output_contract: { max_words: 40 } }), md);
});

test("copy and export use the answer without the server's verification banner", () => {
  const banner = "> ⚠️ **Verification found errors**: 1 statement does not hold.\n> n=41 failed\n\n";
  assert.equal(stripVerificationBanner(banner + "A: 1681\nB: 1763"), "A: 1681\nB: 1763");
});
