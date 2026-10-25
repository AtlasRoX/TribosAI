// Run with: node --test web/tests/lineBreaks.test.mts   (Node 24 strips the TypeScript types)
// A written newline is a line break on screen and in the LaTeX export, as in the DOCX/PDF exports (audit I17).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { remarkHtmlBreaks, remarkSoftBreaks } from "../src/lib/markdownSafety.ts";
import { markdownToLatex } from "../src/lib/markdownToLatex.ts";

function render(markdown: string): string {
  return renderToStaticMarkup(
    createElement(ReactMarkdown as any, {
      skipHtml: true,
      remarkPlugins: [remarkGfm, remarkMath, remarkHtmlBreaks, remarkSoftBreaks],
      rehypePlugins: [rehypeKatex],
    }, markdown),
  );
}

test("two written lines render as two lines, not one joined paragraph", () => {
  const html = render("ALPHA\nBETA");
  assert.match(html, /ALPHA<br\/?>\s*BETA/);
});

test("paragraphs, lists, code and display math are unchanged", () => {
  const html = render("First paragraph.\n\nSecond paragraph.\n\n- a\n- b\n\n```\nx = 1\ny = 2\n```\n\n$$\na = b\n$$");
  assert.equal((html.match(/<p>/g) || []).length, 2);
  assert.match(html, /<li>a<\/li>/);
  assert.match(html, /<code>x = 1\ny = 2\n<\/code>/); // code keeps its newlines and gets no <br>
  assert.match(html, /katex-display/);
});

test("inline math on consecutive lines keeps both lines", () => {
  const html = render("A: $1681 = 41^2$\nB: $1763 = 41 \\cdot 43$");
  assert.match(html, /<br\/?>/);
  assert.equal((html.match(/class="katex"/g) || []).length, 2);
});

test("the LaTeX export breaks consecutive prose lines and leaves paragraphs alone", () => {
  const tex = markdownToLatex("ALPHA\nBETA\n\nNext paragraph.\n\n- item one\n- item two");
  assert.match(tex, /ALPHA \\\\\nBETA/);
  assert.doesNotMatch(tex, /BETA \\\\/);
  assert.doesNotMatch(tex, /item one \\\\/);
});
