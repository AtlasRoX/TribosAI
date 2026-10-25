// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
// Model-written Markdown + LaTeX through the same pipeline as MarkdownRenderer: every dialect renders, nothing leaks.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { KATEX_OPTIONS, preprocessMarkdown } from "../src/lib/markdownNormalize.ts";
import { rehypeStripUnsafe, remarkHtmlBreaks } from "../src/lib/markdownSafety.ts";

function render(markdown: string, streaming = false): string {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown as any,
      {
        skipHtml: true,
        remarkPlugins: [remarkGfm, remarkMath, remarkHtmlBreaks],
        rehypePlugins: [[rehypeKatex, KATEX_OPTIONS], rehypeStripUnsafe],
      },
      preprocessMarkdown(markdown, { streaming })
    )
  );
}

const count = (html: string, re: RegExp) => (html.match(re) || []).length;
const displays = (html: string) => count(html, /class="katex-display"/g);
const inlines = (html: string) => count(html, /class="katex"/g) - displays(html);

function assertClean(html: string) {
  assert.doesNotMatch(html, /katex-error/, html);
  assert.doesNotMatch(html, /\$\$/, "no stray $$ left in the output");
}

test("LaTeX bracket delimiters render as display and inline math", () => {
  const html = render(String.raw`The force is \(F = ma\), so
\[
a = \frac{F}{m}
\]
follows.`);
  assertClean(html);
  assert.equal(displays(html), 1);
  assert.equal(inlines(html), 1);
});

test("aligned blocks in every form render, with prose after them as prose", () => {
  const html = render(String.raw`Step 1:
$$\begin{aligned}
x &= \frac{5\times 12}{6\times 5}\\
&= 2
\end{aligned}$$
Equivalently $x = 2$.

$\begin{aligned}
y &= 1\\[4pt]
z &= 2
\end{aligned}$

\begin{cases}
1 & x > 0 \\
0 & \text{otherwise}
\end{cases}

$$
\frac{a}{b}

= c
$$`);
  assertClean(html);
  assert.equal(displays(html), 4);
  assert.match(html, /<p>Equivalently <span class="katex">/);
});

test("prices stay dollar signs while real inline math renders", () => {
  const html = render("It costs $5 and $10 per unit, or between $1,000 and $2,000; US$ 3. With $x$ and $y^2$ it is $5$.");
  assertClean(html);
  assert.match(html, /\$5 and \$10 per unit/);
  assert.match(html, /between \$1,000 and \$2,000/);
  assert.equal(inlines(html), 3);
});

test("code is never rewritten: fences, inline spans and their dollars stay exactly as written", () => {
  const src = "Run `echo $HOME` first.\n\n```latex\n$$\\begin{aligned}\nx &= \\frac{1}{2}\n\\end{aligned}$$\n```\n\n~~~\nprice = $5\n~~~";
  const html = render(src);
  assert.doesNotMatch(html, /katex/);
  assert.match(html, /<code>echo \$HOME<\/code>/);
  assert.match(html, /\$\$\\begin\{aligned\}\nx &amp;= \\frac\{1\}\{2\}\n\\end\{aligned\}\$\$/);
  assert.match(html, /price = \$5/);
});

test("tables: math with pipes stays in its cell, a table right after a paragraph is still a table", () => {
  const html = render("Results:\n| Quantity | Value |\n|---|---|\n| Norm | $|x| = 3$ |\n| Price | $5 |\nAfter the table.");
  assertClean(html);
  assert.match(html, /<table>/);
  assert.equal(count(html, /<td>/g), 4);
  assert.match(html, /<td>\$5<\/td>/);
  assert.match(html, /<p>After the table.<\/p>/);
});

test("commands KaTeX lacks (siunitx, \\degree, \\abs) and double-escaped commands render", () => {
  const html = render(String.raw`$g = \SI{9.81}{m/s^2}$, $v = \si{\metre\per\second}$, $T = 20\degree$, $\abs{x}$, $\\frac{1}{2}$, $E = mc^2 \label{eq:1}$`);
  assertClean(html);
  assert.equal(inlines(html), 6);
  assert.match(html, /mfrac/);
});

test("Unicode superscripts and subscripts inside math render, in math and in \\text", () => {
  const html = render(String.raw`$g = 9.81\ \text{m/s²}$ and $x² + H₂O$` + "\n\n$$\nv = 3\\,\\text{m s⁻¹}\n$$");
  assertClean(html);
  assert.equal(count(html, /class="msupsub"/g) >= 4, true);
});

test("KaTeX's SVG and inline styles survive the sanitizer (square roots, boxed results)", () => {
  const html = render(String.raw`$$\boxed{\sqrt{x^2 + 1}}$$`);
  assertClean(html);
  assert.match(html, /<svg[^>]*viewBox/);
  assert.match(html, /<path d="M/);
  assert.match(html, /class="boxpad|class="fbox|border-style:solid/);
});

test("headings without a space, encoding damage and an unclosed final block are repaired", () => {
  const html = render("###Results\nspring\ufffdmass system\n\n$$\nx = 1");
  assertClean(html);
  assert.match(html, /<h3>Results<\/h3>/);
  assert.match(html, /spring\u2013mass/);
  assert.equal(displays(html), 1);
});

test("streaming: a formula still being typed is held back instead of flashing as an error", () => {
  const openBlock = render("Intro.\n\n$$\\begin{aligned}\nx &= \\frac{1", true);
  assert.doesNotMatch(openBlock, /katex/);
  assert.match(openBlock, /Intro\./);
  const openInline = render("So the value $\\frac{1}{", true);
  assert.doesNotMatch(openInline, /katex|frac/);
  assert.match(openInline, /So the value/);
  const done = render("So the value $\\frac{1}{2}$", true);
  assert.equal(inlines(done), 1);
});
