/**
 * An answer's Markdown as a LaTeX document body: headings, emphasis, inline code, lists, GFM tables, block quotes and
 * links. Math ($…$, $$…$$) is already LaTeX and passes through unchanged; text outside math is escaped.
 */

const SECTION = ["section", "subsection", "subsubsection", "paragraph", "subparagraph", "subparagraph"];

function escapeText(text: string): string {
  return text
    .replace(/\\/g, "\\textbackslash{}")
    .replace(/([#%&_{}])/g, "\\$1")
    .replace(/\^/g, "\\textasciicircum{}")
    .replace(/~/g, "\\textasciitilde{}");
}

/** Inline Markdown to LaTeX, leaving $…$ math untouched. */
export function inlineToLatex(line: string): string {
  const parts = line.split(/(\$\$[^$]+\$\$|\$[^$\n]+\$)/g);
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part; // math
      let out = escapeText(part);
      out = out.replace(/\*\*([^*]+)\*\*/g, "\\textbf{$1}");
      out = out.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1\\emph{$2}");
      out = out.replace(/`([^`]+)`/g, "\\texttt{$1}");
      out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, (_m, text, url) => `\\href{${String(url).replace(/\\_/g, "_")}}{${text}}`);
      return out;
    })
    .join("");
}

function tableToLatex(rows: string[]): string {
  const cells = rows
    .filter((r, i) => !(i === 1 && /^\s*\|?\s*:?-{2,}/.test(r)))
    .map((r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inlineToLatex(c.trim())));
  const cols = Math.max(...cells.map((c) => c.length));
  const body = cells.map((c, i) => c.join(" & ") + " \\\\" + (i === 0 ? " \\hline" : "")).join("\n");
  return `\\begin{tabular}{${"l".repeat(cols)}}\n\\hline\n${body}\n\\hline\n\\end{tabular}`;
}

export function markdownToLatex(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let list: "itemize" | "enumerate" | null = null;
  let inMath = false;
  let inCode = false;
  const closeList = () => {
    if (list) out.push(`\\end{${list}}`);
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^```/.test(line)) {
      closeList();
      out.push(inCode ? "\\end{verbatim}" : "\\begin{verbatim}");
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      out.push(line);
      continue;
    }
    if (line.trim() === "$$") {
      closeList();
      out.push(inMath ? "\\]" : "\\[");
      inMath = !inMath;
      continue;
    }
    if (inMath) {
      out.push(line);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      closeList();
      const title = inlineToLatex(heading[2].replace(/^\d+(\.\d+)*\.?\s+/, ""));
      out.push(`\\${SECTION[heading[1].length - 1]}{${title}}`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      closeList();
      const rows = [line];
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) rows.push(lines[++i]);
      out.push(tableToLatex(rows));
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const kind = bullet ? "itemize" : "enumerate";
      if (list !== kind) {
        closeList();
        out.push(`\\begin{${kind}}`);
        list = kind;
      }
      out.push(`  \\item ${inlineToLatex((bullet || numbered)![1])}`);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      closeList();
      out.push(`\\begin{quote}${inlineToLatex(line.replace(/^\s*>\s?/, ""))}\\end{quote}`);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      closeList();
      out.push("\\medskip\\hrule\\medskip");
      continue;
    }
    if (!line.trim()) {
      closeList();
      out.push("");
      continue;
    }
    closeList();
    out.push(inlineToLatex(line));
  }
  closeList();
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

/** A complete, compilable document around the body. */
export function latexDocument(title: string, body: string): string {
  return [
    "\\documentclass[11pt]{article}",
    "\\usepackage[utf8]{inputenc}",
    "\\usepackage{amsmath,amssymb,booktabs,hyperref}",
    `\\title{${escapeText(title.slice(0, 200))}}`,
    "\\date{}",
    "\\begin{document}",
    "\\maketitle",
    body,
    "\\end{document}",
    "",
  ].join("\n");
}
