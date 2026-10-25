// Normalization of model-written Markdown and LaTeX before it is parsed (MarkdownRenderer).
// Models write math in every dialect (\[ \], \( \), $$ on content lines, bare \begin{aligned}, siunitx units) and
// use "$" for prices; this module turns all of it into the one form remark-math + KaTeX render reliably.
// Keep this module framework-free and erasable-TypeScript-only so `node --test` can import it.

const CODE_OPEN = "";
const CODE_CLOSE = "";
const CODE_TOKEN = /(\d+)/g;

/**
 * Code swapped for placeholders, so no rule below ever edits it: fenced blocks (an unclosed fence runs to the end,
 * as CommonMark renders it) and inline code spans. `restore` puts the original text back.
 */
function protectCode(text: string): { text: string; restore: (s: string) => string } {
  const saved: string[] = [];
  const keep = (raw: string) => `${CODE_OPEN}${saved.push(raw) - 1}${CODE_CLOSE}`;
  const out: string[] = [];
  let fence: { char: string; len: number; lines: string[] } | null = null;
  for (const line of text.split("\n")) {
    if (fence) {
      fence.lines.push(line);
      const close = /^\s*(`{3,}|~{3,})\s*$/.exec(line);
      if (close && close[1][0] === fence.char && close[1].length >= fence.len) {
        out.push(keep(fence.lines.join("\n")));
        fence = null;
      }
      continue;
    }
    const open = /^\s*(`{3,}|~{3,})/.exec(line);
    if (open && !(open[1][0] === "`" && line.slice(open[0].length).includes("`"))) {
      fence = { char: open[1][0], len: open[1].length, lines: [line] };
      continue;
    }
    out.push(line.replace(/(`+)(?!`)[^\n]*?[^`\n]\1(?!`)/g, keep));
  }
  if (fence) out.push(keep(fence.lines.join("\n")));
  return {
    text: out.join("\n"),
    restore: (s: string) => s.replace(CODE_TOKEN, (_m, i: string) => saved[Number(i)]),
  };
}

// Commands that models double-escape ("\\frac" for "\frac"); a real row break is followed by space, "[" or a newline.
const DOUBLED_COMMAND =
  /(?<!\\)\\\\(?=(?:frac|dfrac|tfrac|sqrt|times|cdot|div|pm|mp|text|mathrm|mathbf|mathit|mathbb|mathcal|operatorname|left|right|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|lambda|mu|nu|xi|pi|rho|sigma|tau|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Sigma|Phi|Psi|Omega|sum|prod|int|oint|partial|nabla|infty|approx|leq|geq|neq|equiv|propto|cdots|ldots|quad|qquad|boxed|hat|bar|vec|dot|ddot|tilde|overline|underline|log|ln|exp|sin|cos|tan)(?![A-Za-z]))/g;

// Unicode super/subscripts ("m/s²") have no KaTeX font metrics; inside math they become ^{2} / _{2}.
const SUPERSCRIPTS: Record<string, string> = { "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-", "ⁿ": "n" };
const SUBSCRIPTS: Record<string, string> = { "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9", "₊": "+", "₋": "-" };
const TEXT_COMMAND = /^\\(?:text|textrm|textbf|textit|textsf|texttt|textnormal|mbox)\s*\{/;

/**
 * Unicode scripts as ^{..}/_{..}. Text mode has no scripts, so inside \text{...} the group is closed around the
 * script and reopened: "\text{m/s²}" -> "\text{m/s}^{2}\text{}" ("$" would end the surrounding inline math).
 */
function asciiScripts(tex: string): string {
  if (!/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ₀₁₂₃₄₅₆₇₈₉₊₋]/.test(tex)) return tex;
  let out = "";
  let depth = 0;
  const textGroups: { depth: number; open: string }[] = [];
  for (let i = 0; i < tex.length; i++) {
    const ch = tex[i];
    const cmd = ch === "\\" ? TEXT_COMMAND.exec(tex.slice(i)) : null;
    if (cmd) {
      out += cmd[0];
      i += cmd[0].length - 1;
      textGroups.push({ depth: ++depth, open: cmd[0] });
    } else if (ch === "\\") {
      out += tex.slice(i, i + 2);
      i++;
    } else if (ch === "{") {
      depth++;
      out += ch;
    } else if (ch === "}") {
      if (textGroups[textGroups.length - 1]?.depth === depth) textGroups.pop();
      depth--;
      out += ch;
    } else if (SUPERSCRIPTS[ch] !== undefined || SUBSCRIPTS[ch] !== undefined) {
      const table = SUPERSCRIPTS[ch] !== undefined ? SUPERSCRIPTS : SUBSCRIPTS;
      let run = "";
      while (i < tex.length && table[tex[i]] !== undefined) run += table[tex[i++]];
      i--;
      const script = `${table === SUPERSCRIPTS ? "^" : "_"}{${run}}`;
      const group = textGroups[textGroups.length - 1];
      if (!group) out += script;
      else if (group.depth === depth) out += `}${script}${group.open}`;
      else out += run; // nested braces inside \text: plain characters
    } else {
      out += ch;
    }
  }
  return out;
}

/** Repairs inside one math span, for what KaTeX would otherwise reject. */
function tidyMathContent(tex: string): string {
  return asciiScripts(tex)
    .replace(DOUBLED_COMMAND, "\\")
    .replace(/\\label\s*\{[^{}]*\}/g, "")
    .replace(/�/g, "\\cdot ");
}

const FENCE_LINE = /^\s*(```|~~~)/;
// A line that is a bare LaTeX formula: only plain symbols before the first command ("v = \frac{d}{t}").
const BARE_LATEX_LINE = /^[A-Za-z0-9_'()\s,=+-]*\\(?:frac|sqrt|tag|sum|int|partial|times|cdot|omega|alpha|beta|gamma|zeta)/;
const BARE_ENV_OPEN = /^\s*\\begin\{(aligned|align\*?|equation\*?|gathered|gather\*?|split|cases|array|[pbBvV]?matrix|multline\*?)\}/;

/** Index of the next "$" not escaped and not part of "$$", from `from`; -1 when there is none. */
function nextSingleDollar(line: string, from: number): number {
  for (let j = from; j < line.length; j++) {
    if (line[j] === "\\") j++;
    else if (line[j] === "$") {
      if (line[j + 1] === "$") j++;
      else return j;
    }
  }
  return -1;
}

/**
 * Makes model-written display math parse the way it reads. remark-math only treats `$$` as a display block when the
 * fence stands on its own line, so `$$\begin{aligned}` ... `\end{aligned}$$` (and a whole-line `$$x$$`) are rewritten
 * with the fences on their own lines, a bare `\begin{aligned}` ... `\end{aligned}` (or one opened by a single `$`)
 * gets fences, and a bare formula line outside any math block is wrapped. Lines inside a math block or code fence are
 * never touched: wrapping a row of an aligned block splits the block and leaves an unclosed `$$` that turns the rest of
 * the answer into a KaTeX error. Blank lines inside a block are dropped (they would end it in a streamed block). A
 * block still open at the end is closed, or, while streaming, held back until its closing fence arrives.
 */
export function normalizeDisplayMath(text: string, { streaming = false }: { streaming?: boolean } = {}): string {
  const out: string[] = [];
  let inFence = false;
  let mathIndent: string | null = null; // set while inside a $$ block
  let mathClose = "$$"; // what ends it: "$$", or "$" for a block opened by `$\begin{...}`
  let envEnd: string | null = null; // set while inside a bare \begin{env} block
  let openedAt = -1; // index in `out` of the open block's fence

  const open = (indent: string) => {
    openedAt = out.length;
    out.push(`${indent}$$`);
  };

  const plainLine = (line: string) => {
    const indent = /^\s*/.exec(line)![0];
    const body = line.trim();
    const n = line.split("$$").length - 1;
    const singleEnv = /^\$(?!\$)\\begin\{/.test(body) && nextSingleDollar(body, 1) < 0;
    if (body.startsWith("|")) {
      out.push(line); // table rows keep their dollars as written
    } else if (singleEnv) {
      open(indent);
      out.push(`${indent}${body.slice(1)}`);
      mathIndent = indent;
      mathClose = "$";
    } else if (n % 2 === 1) {
      const at = line.lastIndexOf("$$");
      const before = line.slice(0, at).trimEnd();
      const after = line.slice(at + 2).trim();
      if (before.trim()) out.push(before);
      open(indent);
      if (after) out.push(`${indent}${after}`);
      mathIndent = indent;
      mathClose = "$$";
    } else if (n === 2 && /^\$\$[^$]+\$\$$/.test(body)) {
      out.push(`${indent}$$`, `${indent}${body.slice(2, -2).trim()}`, `${indent}$$`);
    } else if (n === 0 && BARE_ENV_OPEN.test(line) && !line.includes("$")) {
      envEnd = `\\end{${BARE_ENV_OPEN.exec(line)![1]}}`;
      out.push("");
      open("");
      out.push(body);
      if (body.includes(envEnd)) {
        out.push("$$", "");
        envEnd = null;
      }
    } else if (n === 0 && !line.includes("$") && BARE_LATEX_LINE.test(line) && !body.startsWith("#")) {
      out.push("", "$$", body, "$$", "");
    } else {
      out.push(line);
    }
  };

  for (const line of text.split("\n")) {
    const fence = mathIndent === null && envEnd === null && FENCE_LINE.test(line);
    if (fence) inFence = !inFence;
    if (inFence || fence) {
      out.push(line);
    } else if (envEnd !== null) {
      if (!line.trim()) continue;
      out.push(line.trim());
      if (line.includes(envEnd)) {
        out.push("$$", "");
        envEnd = null;
      }
    } else if (mathIndent !== null) {
      const at = mathClose === "$$" ? line.indexOf("$$") : nextSingleDollar(line, 0);
      if (at < 0) {
        if (line.trim()) out.push(line);
        continue;
      }
      const indent: string = mathIndent;
      if (line.slice(0, at).trim()) out.push(line.slice(0, at).trimEnd());
      out.push(`${indent}$$`);
      mathIndent = null;
      const rest = line.slice(at + mathClose.length).trim();
      if (rest) plainLine(`${indent}${rest}`);
    } else {
      plainLine(line);
    }
  }
  if (mathIndent !== null || envEnd !== null) {
    if (streaming) out.length = openedAt;
    else out.push(`${mathIndent ?? ""}$$`);
  }
  return out.join("\n");
}

// Inline-math content that is clearly a formula, even when written with spaces inside the dollars ("$ x^2 $").
const FORMULA_HINT = /\\[A-Za-z]|[\^_{}=]/;

/**
 * Inline `$...$` checked the way Pandoc does, since remark-math pairs any two dollars: the opening `$` is followed by
 * a non-space and the closing one preceded by a non-space and not followed by a digit (unless the content is clearly a
 * formula). A `$` that opens nothing ("$5 and $10", "US$") is escaped so it stays a dollar sign. While streaming, a
 * formula still being typed on the last line is held back instead of flashing as raw LaTeX.
 */
function inlineMath(line: string, holdBackOpen: boolean): string {
  let out = "";
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === "\\") {
      out += line.slice(i, i + 2);
      i += 2;
      continue;
    }
    if (ch !== "$") {
      out += ch;
      i++;
      continue;
    }
    if (line[i + 1] === "$") {
      const close = line.indexOf("$$", i + 2);
      if (close > i + 2) {
        out += `$$${tidyMathContent(line.slice(i + 2, close))}$$`;
        i = close + 2;
      } else {
        out += "\\$\\$";
        i += 2;
      }
      continue;
    }
    const close = nextSingleDollar(line, i + 1);
    const content = close < 0 ? "" : line.slice(i + 1, close);
    const formula = FORMULA_HINT.test(content);
    const padded = /^\s|\s$/.test(content);
    const priceAfter = /\d/.test(line[close + 1] ?? "");
    // "$2,000; US$": an amount followed by words, not a formula.
    const priceText = /^\d/.test(content) && /\s/.test(content) && /[A-Za-z]{2,}/.test(content);
    if (content.trim() && (formula || (!padded && !priceAfter && !priceText))) {
      out += `$${tidyMathContent(content.trim())}$`;
      i = close + 1;
      continue;
    }
    if (holdBackOpen && close < 0 && FORMULA_HINT.test(line.slice(i + 1))) return out.trimEnd();
    out += "\\$";
    i++;
  }
  return out;
}

/** Inline math checked and display-math content repaired, line by line (display blocks are `$$` fence lines here). */
function tidyMath(text: string, streaming: boolean): string {
  const lines = text.split("\n");
  let inDisplay = false;
  return lines
    .map((line, idx) => {
      if (line.trim() === "$$") {
        inDisplay = !inDisplay;
        return line;
      }
      if (inDisplay) return tidyMathContent(line);
      return inlineMath(line, streaming && idx === lines.length - 1);
    })
    .join("\n");
}

const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_DELIMITER_ROW = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** Tables start a block of their own: a blank line before the header row and after the last row. */
function separateTables(text: string): string {
  const lines = text.split("\n");
  const out: string[] = [];
  lines.forEach((line, i) => {
    const prev = out.length ? out[out.length - 1] : "";
    const startsTable = TABLE_ROW.test(line) && TABLE_DELIMITER_ROW.test(lines[i + 1] ?? "") && !TABLE_ROW.test(prev);
    if (startsTable && prev.trim()) out.push("");
    if (line.trim() && !TABLE_ROW.test(line) && TABLE_ROW.test(prev) && !/^\s*[-*+>\d]/.test(line)) out.push("");
    out.push(line);
  });
  return out.join("\n");
}

/** Pipes inside inline math in a table row would split the cell; `\vert` renders the same bar. */
function protectTablePipes(text: string): string {
  return text.replace(/^(\s*\|.*\|\s*)$/gm, (row) =>
    row.replace(/(?<!\\)\$([^$\n]+)\$/g, (_m, tex: string) => "$" + tex.replace(/(?<!\\)\|/g, "\\vert ") + "$")
  );
}

/**
 * Model-written Markdown made ready for react-markdown + remark-math + KaTeX. Code is never edited. With `streaming`,
 * math that is still being typed is held back so the live view never shows half a formula as a KaTeX error.
 */
export function preprocessMarkdown(raw: string, { streaming = false }: { streaming?: boolean } = {}): string {
  if (!raw) return "";
  const code = protectCode(raw.replace(/\r\n?/g, "\n"));
  let processed = code.text;

  // Legacy agent and project names read as the official Tribos designations.
  processed = processed
    .replace(/\bTalk2KnowledgeGraphs?\b/gi, "Physis")
    .replace(/\bTalk2BioModels?\b/gi, "Dynamis")
    .replace(/\bTalk2Cells?\b/gi, "Calcula")
    .replace(/\bTalk2Scholars?\b/gi, "Archivon")
    .replace(/\bSynapta\b/gi, "Physis")
    .replace(/\bVivarix\b/gi, "Dynamis")
    .replace(/\bLumicell\b/gi, "Calcula")
    .replace(/\bLithoscribe\b/gi, "Archivon")
    .replace(/\bTalk2AI[-_ ]?Agents[-_ ]?4[-_ ]?Pharma\b/gi, "Tribos")
    .replace(/\bAI[-_ ]?Agents[-_ ]?4[-_ ]?Pharma\b/gi, "Tribos");

  // Placeholder sections of agents that did not run ("No domain-specific findings were collected...").
  processed = processed.replace(
    /(?:^|\n)#{1,4}\s*[^#\n]*(?:Archivon|Axiom|Dynamis|Calcula|Physis|Synapta|Vivarix|Lumicell|Lithoscribe)[^\n]*\n+No domain-specific findings were collected[^\n]*\n*/gi,
    "\n"
  );
  // Naming-convention boilerplate footers.
  processed = processed.replace(/(?:^|\n)\*?_?All agent references follow the official naming convention[^\n]*\*?_?/gi, "");
  // Internal hypothesis-tier labels ("`[PREDICTION: PROPOSED HYPOTHESIS - MODERATE EVIDENCE]`") read as plain words.
  processed = processed.replace(
    /\[PREDICTION:\s*PROPOSED HYPOTHESIS\s*-\s*([^\]]+)\]/gi,
    (_m, tier: string) => `Hypothesis (${tier.trim().toLowerCase()})`
  );
  // Repetitive "Bottom line" headings become one "Executive Summary".
  processed = processed.replace(/(?:^|\n)(?:#{1,4}\s+|\*\*|\b)Bottom\s+line(?::|\*\*:?|\b)/gi, "\n\n### Executive Summary\n");

  // remarkHtmlBreaks turns exactly this tag into a hard break (all other HTML is dropped).
  processed = processed.replace(/<br\s*\/?>/gi, "<br />");
  // "###Heading" is a heading the model meant; CommonMark needs the space.
  processed = processed.replace(/^(\s{0,3}#{2,6})(?=[^\s#])/gm, "$1 ");
  processed = separateTables(processed);

  // LaTeX delimiters \[ \] and \( \) become $$ / $ ("\\[4pt]" is a row break, not an opener).
  processed = processed.replace(/(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]/g, (_m, inner: string) => `\n$$\n${inner.trim()}\n$$\n`);
  processed = processed.replace(/(?<!\\)\\\(([\s\S]*?)(?<!\\)\\\)/g, (_m, inner: string) => `$${inner.trim()}$`);
  // \tag is display-only in KaTeX; in inline math it becomes a trailing label.
  processed = processed.replace(/\$([^$\n]*?)\\tag\{([^}\n]+)\}([^$\n]*?)\$/g, "$$$1\\qquad \\text{($2)}$3$$");
  processed = protectTablePipes(processed);

  processed = normalizeDisplayMath(processed, { streaming });
  processed = tidyMath(processed, streaming);
  // A replacement character outside math is a dash lost to an encoding error ("spring�mass").
  processed = processed.replace(/�/g, "–");
  return code.restore(processed);
}

/**
 * Commands models use that KaTeX does not define: siunitx units, \degree, \abs/\norm, number sets, arg max/min.
 * Unknown units inside \si{...} still render as upright text through \mathrm.
 */
export const KATEX_MACROS: Record<string, string> = {
  "\\degree": "^{\\circ}",
  "\\celsius": "{^{\\circ}\\mathrm{C}}",
  "\\degreeCelsius": "{^{\\circ}\\mathrm{C}}",
  "\\ohm": "\\Omega",
  "\\micro": "\\mu",
  "\\SI": "#1\\,\\mathrm{#2}",
  "\\si": "\\mathrm{#1}",
  "\\unit": "\\mathrm{#1}",
  "\\num": "#1",
  "\\ang": "#1^{\\circ}",
  "\\per": "/",
  "\\squared": "^{2}",
  "\\cubed": "^{3}",
  "\\metre": "m",
  "\\meter": "m",
  "\\second": "s",
  "\\kilogram": "kg",
  "\\gram": "g",
  "\\newton": "N",
  "\\joule": "J",
  "\\watt": "W",
  "\\pascal": "Pa",
  "\\kelvin": "K",
  "\\hertz": "Hz",
  "\\volt": "V",
  "\\ampere": "A",
  "\\kilo": "k",
  "\\milli": "m",
  "\\centi": "c",
  "\\mega": "M",
  "\\giga": "G",
  "\\abs": "\\left|#1\\right|",
  "\\norm": "\\left\\|#1\\right\\|",
  "\\dd": "\\mathrm{d}",
  "\\argmax": "\\operatorname*{arg\\,max}",
  "\\argmin": "\\operatorname*{arg\\,min}",
  "\\sgn": "\\operatorname{sgn}",
  "\\Tr": "\\operatorname{Tr}",
  "\\Q": "\\mathbb{Q}",
};

/** rehype-katex options shared by the renderer and the tests: never throw, accept Unicode, no \href/\url trust. */
export const KATEX_OPTIONS = { throwOnError: false, strict: "ignore", trust: false, macros: KATEX_MACROS } as const;
