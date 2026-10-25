"use client";

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { type Components, type Options as MarkdownOptions } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy, ExternalLink, Terminal } from "lucide-react";
import { CitationRef } from "@/components/CitationRef";
import { rehypeCitations, rehypeIdentifierLinkGuard } from "@/lib/citations";
import { KATEX_OPTIONS, preprocessMarkdown } from "@/lib/markdownNormalize";
import { rehypeMathBlocks, rehypeValueLinks, type LinkedValue } from "@/lib/mathInteractions";
import { emitUi } from "@/lib/uiEvents";
import { sectionSlug } from "@/lib/sections";
import {
  linkWebMarkers,
  rehypeStripUnsafe,
  remarkHtmlBreaks,
  remarkSoftBreaks,
  safeUrlTransform,
  splitStreamingBlocks,
  stabilizeStreamingTail,
} from "@/lib/markdownSafety";
import type { CitationMap } from "@/types/citations";

interface MarkdownRendererProps {
  content: string;
  /** Identifiers cited in the answer, linked to their sources; omitted while streaming. */
  citations?: CitationMap;
  /** Live text: finished blocks are memoized so each new token re-parses only the last block. */
  streaming?: boolean;
  /** Computed values the answer may quote: matching numbers become links to where they were computed. */
  linkedValues?: LinkedValue[];
  /** A finished answer: section headings offer "Improve this section" (a targeted follow-up). */
  sectionActions?: boolean;
}

function headingText(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(headingText).join("");
  if (React.isValidElement(children)) return headingText((children.props as { children?: React.ReactNode }).children);
  return "";
}

/** A section heading: anchored for the contents bar; with actions, a short note asks for a revision of this section. */
function SectionHeading({ level, actions, children }: { level: 2 | 3; actions: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const title = headingText(children).trim();
  const Tag = level === 2 ? "h2" : "h3";
  const send = () => {
    const text = note.trim();
    if (!text) return;
    emitUi("tribos:ask", {
      text: `Revise only the section "${title}" of your previous answer: ${text}. Keep every other section as it is, and recheck any number the change affects.`,
      send: true,
    });
    setOpen(false);
    setNote("");
  };
  return (
    <>
      <Tag data-section={sectionSlug(title)} className={actions ? "section-heading" : undefined}>
        {children}
        {actions && (
          <button
            type="button"
            className="section-improve"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            title="Something wrong or missing here? Ask for a revision of this section only"
          >
            Improve this section
          </button>
        )}
      </Tag>
      {actions && open && (
        <form
          className="section-feedback"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={`What should change in "${title.slice(0, 40)}"? e.g. "the phase sign is wrong"`}
            aria-label={`Feedback on the section ${title}`}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          />
          <button type="submit" disabled={!note.trim()}>
            Revise
          </button>
        </form>
      )}
    </>
  );
}

/** A display equation with a copy menu: the LaTeX source, or MathML that Word turns into an equation on paste. */
function MathBlock({ latex, children }: { latex: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState<"" | "latex" | "word">("");
  const copy = async (kind: "latex" | "word") => {
    const text = kind === "latex" ? latex : ref.current?.querySelector("math")?.outerHTML || latex;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      window.setTimeout(() => setCopied(""), 1500);
    } catch {
      // clipboard unavailable (insecure context): nothing to report beyond the unchanged label
    }
  };
  return (
    <div className="math-block" ref={ref}>
      {children}
      {latex && (
        <span className="math-copy" role="group" aria-label="Copy this equation">
          <button type="button" onClick={() => void copy("latex")} title="Copy the LaTeX source">
            {copied === "latex" ? "Copied" : "LaTeX"}
          </button>
          <button type="button" onClick={() => void copy("word")} title="Copy as MathML; paste into Word for an editable equation">
            {copied === "word" ? "Copied" : "Word"}
          </button>
        </span>
      )}
    </div>
  );
}

/** A number the run computed: a click scrolls to and highlights the card row that holds it. */
function ValueLink({ valueKey, title, children }: { valueKey: string; title?: string; children: React.ReactNode }) {
  const show = (from: HTMLElement) => {
    const scope = from.closest("[data-message-id]") ?? document;
    const find = () => scope.querySelector<HTMLElement>(`[data-value-key="${CSS.escape(valueKey)}"]`);
    const flash = (el: HTMLElement) => {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("value-flash");
      void el.offsetWidth; // restart the animation on a repeated click
      el.classList.add("value-flash");
    };
    const target = find();
    if (target) return flash(target);
    // The card is collapsed: open the cards, then point at the row once it renders.
    window.dispatchEvent(new CustomEvent("tribos:cards", { detail: { open: true } }));
    window.setTimeout(() => {
      const later = find();
      if (later) flash(later);
    }, 120);
  };
  return (
    <mark
      className="value-link"
      title={title}
      role="button"
      tabIndex={0}
      onClick={(e) => show(e.currentTarget)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          show(e.currentTarget);
        }
      }}
    >
      {children}
    </mark>
  );
}

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

function hastText(node: HastNode): string {
  if (node.type === "text") return node.value || "";
  return (node.children || []).map(hastText).join("");
}

function hastFind(node: HastNode, tag: string): HastNode[] {
  const out: HastNode[] = [];
  for (const child of node.children || []) {
    if (child.type !== "element") continue;
    if (child.tagName === tag) out.push(child);
    if (child.tagName !== "table") out.push(...hastFind(child, tag));
  }
  return out;
}

/**
 * Label every cell with its column header, and mark tables whose cells hold paragraphs.
 * Those are unreadable squeezed into narrow columns, so they render as stacked rows instead.
 */
function rehypeReadableTables() {
  const annotate = (table: HastNode) => {
    const headers = hastFind(table, "th").map((th) => hastText(th).trim());
    const lengths: number[] = [];
    for (const tr of hastFind(table, "tr")) {
      hastFind(tr, "td").forEach((td, i) => {
        const length = hastText(td).trim().length;
        // Short values (rank, score, tier) sit side by side when the table is stacked.
        td.properties = { ...td.properties, dataLabel: headers[i] || "", ...(length <= 40 ? { dataShort: "" } : {}) };
        lengths.push(length);
      });
    }
    if (!lengths.length) return;
    const longest = Math.max(...lengths);
    const average = lengths.reduce((a, b) => a + b, 0) / lengths.length;
    if (headers.length >= 4 && (longest > 120 || average > 50)) {
      table.properties = { ...table.properties, dataLayout: "stacked" };
    } else if (headers.length >= 6) {
      table.properties = { ...table.properties, dataLayout: "dense" };
    }
  };
  const visit = (node: HastNode) => {
    if (node.type === "element" && node.tagName === "table") annotate(node);
    (node.children || []).forEach(visit);
  };
  return (tree: HastNode) => visit(tree);
}

/**
 * A table in a horizontally scrollable box. When columns are hidden off either edge, a shadow on that edge says so,
 * so a cut-off last column is never mistaken for the end of the table.
 */
function ScrollableTable({ layout, children }: { layout?: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);
  useEffect(() => {
    update();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, [update]);
  const variant = layout === "stacked" ? " is-stacked" : layout === "dense" ? " is-dense" : "";
  return (
    <div
      className="table-scroll"
      data-scroll-left={edges.left ? "" : undefined}
      data-scroll-right={edges.right ? "" : undefined}
    >
      <div
        ref={ref}
        className={`table-container${variant}`}
        onScroll={update}
        tabIndex={edges.left || edges.right ? 0 : undefined}
        role={edges.left || edges.right ? "region" : undefined}
        aria-label={edges.left || edges.right ? "Scrollable table" : undefined}
      >
        <table>{children}</table>
      </div>
    </div>
  );
}

/** Smallest scale a display equation is shrunk to before it scrolls instead: below this it is hard to read. */
const MIN_EQUATION_SCALE = 0.72;

/**
 * Fits display equations to the column: one a little too wide is scaled down (to MIN_EQUATION_SCALE at most), so a
 * long derivation line reads without a scrollbar; only a still wider one scrolls. Refitted when the column resizes.
 */
function useFitDisplayMath(ref: React.RefObject<HTMLDivElement | null>, content: string) {
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const fit = () => {
      root.querySelectorAll<HTMLElement>(".katex-display").forEach((box) => {
        const math = box.firstElementChild as HTMLElement | null;
        if (!math) return;
        math.style.fontSize = "";
        const available = box.clientWidth;
        const needed = math.scrollWidth;
        if (!available || needed <= available) return;
        const scale = Math.max(MIN_EQUATION_SCALE, (available - 2) / needed);
        math.style.fontSize = `${(parseFloat(getComputedStyle(math).fontSize) * scale).toFixed(2)}px`;
      });
    };
    fit();
    let live = true;
    // KaTeX fonts load after the first paint and change every equation's width.
    document.fonts?.ready.then(() => live && fit()).catch(() => undefined);
    if (typeof ResizeObserver === "undefined") return () => { live = false; };
    let width = root.clientWidth;
    const observer = new ResizeObserver(() => {
      if (root.clientWidth === width) return;
      width = root.clientWidth;
      fit();
    });
    observer.observe(root);
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [ref, content]);
}

const REMARK_PLUGINS: NonNullable<MarkdownOptions["remarkPlugins"]> = [remarkGfm, remarkMath, remarkHtmlBreaks, remarkSoftBreaks];
const REHYPE_KATEX_PLUGIN: [typeof rehypeKatex, typeof KATEX_OPTIONS] = [rehypeKatex, KATEX_OPTIONS];
const MATH_BLOCK_KEY = "math-block";

function useMarkdownComponents(citations?: CitationMap, sectionActions = false): Components {
  return useMemo<Components>(
    () => ({
      h2({ children }) {
        return (
          <SectionHeading level={2} actions={sectionActions}>
            {children}
          </SectionHeading>
        );
      },
      h3({ children }) {
        return (
          <SectionHeading level={3} actions={false}>
            {children}
          </SectionHeading>
        );
      },
      // `node` is the hast element react-markdown passes along; it must not reach the DOM as an attribute.
      code({ className, children, node: _node, ...props }) {
        const match = /language-(\w+)/.exec(className || "");
        const isInline = !match && !String(children).includes("\n");

        if (isInline) {
          return (
            <code className="inline-code" {...props}>
              {children}
            </code>
          );
        }

        const codeText = String(children).replace(/\n$/, "");
        const language = match ? match[1] : "code";

        return <CodeBlock language={language} code={codeText} />;
      },
      div({ children, className, node: _node, ...props }) {
        const latex = (props as Record<string, unknown>)["data-latex"];
        if (typeof className === "string" && className.split(" ").includes(MATH_BLOCK_KEY)) {
          return <MathBlock latex={typeof latex === "string" ? latex : ""}>{children}</MathBlock>;
        }
        return (
          <div className={className} {...props}>
            {children}
          </div>
        );
      },
      mark({ children, className, node: _node, ...props }) {
        const key = (props as Record<string, unknown>)["data-value-key"];
        if (typeof className === "string" && className.includes("value-link") && typeof key === "string") {
          return (
            <ValueLink valueKey={key} title={typeof props.title === "string" ? props.title : undefined}>
              {children}
            </ValueLink>
          );
        }
        return <mark className={className}>{children}</mark>;
      },
      table({ children, ...props }) {
        const layout = (props as Record<string, unknown>)["data-layout"];
        return <ScrollableTable layout={typeof layout === "string" ? layout : undefined}>{children}</ScrollableTable>;
      },
      a({ href, children, ...props }) {
        const citeKey = (props as Record<string, unknown>)["data-cite-key"];
        if (typeof citeKey === "string" && citations) {
          return (
            <CitationRef
              citeKey={citeKey}
              occurrence={Number((props as Record<string, unknown>)["data-cite-occurrence"]) || 0}
              map={citations}
              href={href}
            >
              {children}
            </CitationRef>
          );
        }
        if (!href) return <>{children}</>;
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="external-link"
          >
            {children}
            <ExternalLink style={{ width: 11, height: 11, display: "inline", marginLeft: 3 }} />
          </a>
        );
      },
    }),
    [citations, sectionActions]
  );
}

const STREAMING_REHYPE_PLUGINS: NonNullable<MarkdownOptions["rehypePlugins"]> = [
  REHYPE_KATEX_PLUGIN,
  rehypeMathBlocks,
  rehypeStripUnsafe,
  rehypeIdentifierLinkGuard,
  rehypeReadableTables,
];

const StreamingBlock = memo(function StreamingBlock({ text }: { text: string }) {
  const components = useMarkdownComponents();
  return (
    <ReactMarkdown
      skipHtml
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={STREAMING_REHYPE_PLUGINS}
      urlTransform={safeUrlTransform}
      components={components}
    >
      {text}
    </ReactMarkdown>
  );
});

/**
 * Streaming view: finished blocks are memoized (each new token re-parses only the last block), and the
 * still-growing last block is stabilized so half-typed tables, markers and emphasis don't make the layout jump.
 */
function StreamingMarkdown({ content }: { content: string }) {
  const blocks = useMemo(() => {
    const parts = splitStreamingBlocks(content);
    if (parts.length) parts[parts.length - 1] = stabilizeStreamingTail(parts[parts.length - 1]);
    return parts;
  }, [content]);
  return (
    <div className="markdown-content">
      {blocks.map((block, i) => (block ? <StreamingBlock key={i} text={block} /> : null))}
    </div>
  );
}

function MarkdownRendererImpl({ content, citations, streaming = false, linkedValues, sectionActions = false }: MarkdownRendererProps) {
  // A stable key for the values, so a new array with the same numbers does not re-parse the answer.
  const valuesKey = JSON.stringify(linkedValues || []);
  const cleanedContent = useMemo(() => {
    let text = preprocessMarkdown(content, { streaming });
    if (citations?.entries) {
      const urlEntries = Object.values(citations.entries).filter((e) => e && e.type === "url" && e.url);
      if (urlEntries.length > 0) {
        const primary = urlEntries[0];
        const title = primary.title || "Web Source";
        text = linkWebMarkers(text, title, String(primary.url));
      }
    }
    return text;
  }, [content, citations, streaming]);
  // Raw HTML is never rendered (skipHtml + rehypeStripUnsafe); trusted transforms run after the strip.
  const rehypePlugins = useMemo<NonNullable<MarkdownOptions["rehypePlugins"]>>(
    () => [
      REHYPE_KATEX_PLUGIN,
      rehypeMathBlocks,
      rehypeStripUnsafe,
      // Links whose text names an identifier but point elsewhere show their real destination (UI-018).
      [rehypeIdentifierLinkGuard, { map: citations }] as [typeof rehypeIdentifierLinkGuard, { map?: CitationMap }],
      ...(citations && (Object.keys(citations.entries || {}).length || citations.unverified?.length)
        ? [[rehypeCitations, { map: citations }] as [typeof rehypeCitations, { map: CitationMap }]]
        : []),
      rehypeReadableTables,
      [rehypeValueLinks, { values: JSON.parse(valuesKey) as LinkedValue[] }] as [typeof rehypeValueLinks, { values: LinkedValue[] }],
    ],
    [citations, valuesKey]
  );
  const components = useMarkdownComponents(citations, sectionActions && !streaming);
  const contentRef = useRef<HTMLDivElement>(null);
  useFitDisplayMath(contentRef, streaming ? "" : cleanedContent);
  const rendered = useMemo(
    () =>
      streaming ? null : (
        <div className="markdown-content" ref={contentRef}>
          <ReactMarkdown
            skipHtml
            remarkPlugins={REMARK_PLUGINS}
            rehypePlugins={rehypePlugins}
            urlTransform={safeUrlTransform}
            components={components}
          >
            {cleanedContent}
          </ReactMarkdown>
        </div>
      ),
    [streaming, cleanedContent, rehypePlugins, components]
  );

  if (streaming) return <StreamingMarkdown content={cleanedContent} />;
  return rendered;
}

/** Memoized: a parent re-render with the same text (and citations) never re-parses the Markdown. */
export const MarkdownRenderer = memo(MarkdownRendererImpl);

interface CodeBlockProps {
  language: string;
  code: string;
}

function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy code:", err);
    }
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <div className="code-block-lang">
          <Terminal style={{ width: 12, height: 12, color: "var(--domain-t2kg)" }} />
          <span>{language}</span>
        </div>
        <button
          onClick={handleCopy}
          className="code-copy-btn"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check style={{ width: 12, height: 12, color: "var(--nvidia-green)" }} />
              <span style={{ color: "var(--nvidia-green)" }}>Copied!</span>
            </>
          ) : (
            <>
              <Copy style={{ width: 12, height: 12 }} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
