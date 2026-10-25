import assert from "node:assert/strict";
import test from "node:test";
import { inlineToLatex, latexDocument, markdownToLatex } from "../src/lib/markdownToLatex.ts";
import { everythingArchive, exportFilename } from "../src/services/exportService.ts";
import type { Message } from "../src/types/chat.ts";

test("T8: literal backslashes and special characters produce valid LaTeX text", () => {
  const result = inlineToLatex(String.raw`path\name 10% & x_y #1`);
  assert.ok(result.includes(String.raw`\textbackslash{}`));
  assert.ok(!result.includes(String.raw`\textbackslash\{`));
  for (const token of [String.raw`\%`, String.raw`\&`, String.raw`\_`, String.raw`\#`]) assert.ok(result.includes(token));
});

test("T8: Everything contains each report format and keeps the reproduction files", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => new Response(String(input));
  try {
    const bytes = await everythingArchive({ question: "q", message: { content: "a" } as Message }, "http://localhost", {},
      [{ name: "answer.tex", content: "LaTeX" }, { name: "trajectory.csv", content: "t,x\n0,1" }]);
    const view = new DataView(bytes.buffer);
    const names: string[] = [];
    let at = 0;
    while (view.getUint32(at, true) === 0x04034b50) {
      const length = view.getUint16(at + 26, true);
      names.push(new TextDecoder().decode(bytes.slice(at + 30, at + 30 + length)));
      at += 30 + length + view.getUint32(at + 18, true);
    }
    assert.deepEqual(names, ["report.pdf", "report.docx", "report.ipynb", "report.md", "report.json", "answer.tex", "trajectory.csv"]);
    globalThis.fetch = async () => new Response("failed", { status: 500 });
    await assert.rejects(everythingArchive({ question: "q", message: {} as Message }, "http://localhost", {}));
  } finally { globalThis.fetch = original; }
});

test("T8: tables preserve math and pad ragged rows; notebook filenames are correct", () => {
  const body = markdownToLatex("| A | B |\n|---|---|\n| $x_1$ | 10% |\n| short |");
  assert.ok(body.includes(String.raw`\begin{tabular}{ll}`));
  assert.ok(body.includes("$x_1$"));
  assert.ok(body.includes(String.raw`short &  \\`));
  assert.ok(latexDocument("A & B", body).includes(String.raw`\title{A \& B}`));
  assert.ok(latexDocument("α ± 2°", body).includes(String.raw`\DeclareUnicodeCharacter{03B1}{\ensuremath{\alpha}}`));
  assert.ok(exportFilename("ipynb", "Decay").endsWith(".ipynb"));
});
