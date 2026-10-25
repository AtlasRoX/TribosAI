// Citation helpers for the answer renderer (owned by CITATIONS, feature 4).
// Keep this module framework-free and erasable-TypeScript-only so `node --test` can import it.
// The identifier grammar mirrors tribos/extensions/id_families.py and tribos/agents/citations.py.

import type { CitationEntry, CitationMap, ClaimSupport } from "../types/citations";

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

/**
 * Cited identifiers across maths, physics, engineering, and scholarly sources.
 * Groups:
 *  1 ARXIV (arXiv:2309.17452, arXiv:2309.17452v1, arXiv:hep-th/9901001)
 *  2 DOI (10.xxxx/...)
 *  3 ZBL (Zbl 1234.56789, Zbl:1234.56789)
 *  4 MR (MR1234567, MR:1234567)
 *  5 OEIS (A000045, OEIS:A000045)
 *  6 ADS (19-char bibcode e.g. 2023ApJ...123..456A)
 *  7 MP (mp-149, MP:mp-149)
 *  8 ISBN (ISBN 978-..., ISBN-13: 978-...)
 *  9 OPENALEX (W2741809807, OpenAlex:W2741809807)
 * 10 PMID (PMID: 12345678)
 * 11 COMP (comp:axiom_solve:1)
 * 12 DATASET (ds_0123456789ab)
 * Global: reset lastIndex (or use matchAll) before reuse.
 */
export const CITE_PATTERN =
  /\b[Aa]r[Xx]iv:\s*(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z]{2})?\/\d{7}(?:v\d+)?)\b|(\b10\.\d{4,9}\/[-._;()\/:A-Za-z0-9]+\b)|\b[Zz]bl\s*:?\s*(\d{4}\.\d{5}|\d{7,8})\b|\b[Mm][Rr]\s*:?\s*(\d{6,8})\b|\b(?:[Oo][Ee][Ii][Ss]:\s*)?(A\d{6})\b|\b(?:[Aa][Dd][Ss]:\s*)?(\d{4}[A-Za-z&.\d]{14}[A-Z])\b|\b(?:[Mm][Pp]:\s*)?(mp-\d{1,8})\b|\b[Ii][Ss][Bb][Nn](?:-1[03])?:?\s*([0-9Xx-]{10,17})\b|\b(?:[Oo]pen[Aa]lex:\s*)?(W\d{7,12})\b|\b[Pp][Mm][Ii][Dd]:?\s*(\d{1,9})\b|\b[Cc][Oo][Mm][Pp]:([a-zA-Z0-9_:-]+)\b|\b(ds_[0-9a-fA-F]{12})\b/g;

const GROUP_PREFIX = [
  "",
  "ARXIV",
  "DOI",
  "ZBL",
  "MR",
  "OEIS",
  "ADS",
  "MP",
  "ISBN",
  "OPENALEX",
  "PMID",
  "COMP",
  "DATASET",
];

const ID_PATTERNS: Record<string, RegExp> = {
  ARXIV: /^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z]{2})?\/\d{7}(?:v\d+)?)$/i,
  DOI: /^10\.\d{4,9}\/[-._;()\/:a-z0-9]+$/,
  ZBL: /^(?:\d{4}\.\d{5}|\d{7,8})$/,
  MR: /^\d{6,8}$/,
  OEIS: /^A\d{6}$/,
  ADS: /^\d{4}[A-Za-z&.\d]{14}[A-Z]$/,
  MP: /^mp-\d{1,8}$/,
  ISBN: /^(?=[0-9X-]{10,17}$)(?:[0-9]+-?){9,13}[0-9X]$/,
  OPENALEX: /^W\d{7,12}$/,
  PMID: /^\d{1,9}$/,
  COMP: /^[a-zA-Z0-9_:-]+$/,
  DATASET: /^ds_[0-9a-f]{12}$/,
};

const VALID_URL = /^https?:\/\/[A-Za-z0-9.-]+(?::\d{1,5})?(?:[/?#][^\s<>"'`]*)?$/i;

/** URL identity used for keys: no fragment, no trailing slash (same rule as the backend). */
export function normalizeUrl(url: string): string {
  return url.trim().split("#", 1)[0].replace(/\/+$/, "");
}

/** Canonical "PREFIX:id" key for a raw id, or null when it does not validate. */
export function makeKey(prefix: string, rawId: string): string | null {
  const upperPrefix = String(prefix ?? "").trim().toUpperCase();
  let value = String(rawId ?? "").trim();
  if (!value) return null;
  if (upperPrefix === "URL") return VALID_URL.test(value) ? `URL:${normalizeUrl(value)}` : null;
  if (upperPrefix === "DOI") {
    value = value
      .replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "")
      .replace(/[.,;)]+$/, "")
      .toLowerCase();
  } else if (upperPrefix === "ARXIV") {
    // Version suffix dropped, as tribos/sources/keys.py does: arXiv:2309.17452v2 and arXiv:2309.17452 are one paper.
    value = value.replace(/^arxiv:\s*/i, "").replace(/[.,;)]+$/, "").replace(/v\d+$/i, "");
  } else if (upperPrefix === "ZBL") {
    value = value.replace(/^zbl\s*:?\s*/i, "");
  } else if (upperPrefix === "MR") {
    value = value.replace(/^mr\s*:?\s*/i, "");
  } else if (upperPrefix === "OEIS") {
    value = value.replace(/^oeis:\s*/i, "").toUpperCase();
  } else if (upperPrefix === "ADS") {
    value = value.replace(/^ads:\s*/i, "");
  } else if (upperPrefix === "MP") {
    value = value.replace(/^mp:\s*/i, "").toLowerCase();
  } else if (upperPrefix === "ISBN") {
    value = value.replace(/^isbn(?:-1[03])?:?\s*/i, "").replace(/[.,;)]+$/, "").toUpperCase();
  } else if (upperPrefix === "OPENALEX") {
    value = value.replace(/^openalex:\s*/i, "").toUpperCase();
  } else if (upperPrefix === "PMID") {
    value = value.replace(/^pmid:?\s*/i, "");
  } else if (upperPrefix === "COMP") {
    value = value.replace(/^comp:\s*/i, "").replace(/[.,;)]+$/, "");
  } else if (upperPrefix === "DATASET") {
    value = value.replace(/^dataset:\s*/i, "").toLowerCase();
  }
  const pattern = ID_PATTERNS[upperPrefix];
  return pattern && pattern.test(value) ? `${upperPrefix}:${value}` : null;
}

/** Canonical link-out URL for a validated citation key. */
export function urlForKey(key: string): string | null {
  const i = key.indexOf(":");
  if (i <= 0) return null;
  const prefix = key.slice(0, i).toUpperCase();
  const value = key.slice(i + 1);
  if (!value) return null;
  switch (prefix) {
    case "ARXIV":
      return `https://arxiv.org/abs/${value.replace(/^arxiv:\s*/i, "")}`;
    case "DOI":
      return `https://doi.org/${value}`;
    case "ZBL":
      return `https://zbmath.org/?q=an:${value.replace(/^zbl\s*:?\s*/i, "")}`;
    case "MR":
      return `https://mathscinet.ams.org/mathscinet-getitem?mr=${value.replace(/^mr\s*:?\s*/i, "")}`;
    case "OEIS":
      return `https://oeis.org/${value}`;
    case "ADS":
      return `https://ui.adsabs.harvard.edu/abs/${value}`;
    case "MP":
      return `https://next-gen.materialsproject.org/materials/${value}`;
    case "ISBN":
      return `https://search.worldcat.org/search?q=bn:${value.replace(/^isbn:\s*/i, "")}`;
    case "OPENALEX":
      return `https://openalex.org/${value}`;
    case "PMID":
      return `https://pubmed.ncbi.nlm.nih.gov/${value}/`;
    case "COMP":
      return `#comp-${value.replace(/^comp:\s*/i, "")}`;
    case "DATASET":
      return `#dataset-${value}`;
    case "URL":
      return value;
    default:
      return null;
  }
}

function keyFromMatch(m: RegExpExecArray | RegExpMatchArray): string | null {
  for (let g = 1; g < GROUP_PREFIX.length; g++) {
    const value = m[g];
    if (value === undefined) continue;
    if (g === 2) return makeKey("DOI", value.replace(/[.,;)]+$/, ""));
    return makeKey(GROUP_PREFIX[g], value);
  }
  return null;
}

/** Key for the first identifier in `text` ("arXiv:2309.17452" -> "ARXIV:2309.17452", DOIs lowercased, trailing .,;) dropped). */
export function toCiteKey(text: string): string | null {
  const re = new RegExp(CITE_PATTERN.source);
  const m = re.exec(String(text ?? ""));
  return m ? keyFromMatch(m) : null;
}

const HREF_PATTERNS: Array<[RegExp, string]> = [
  [/^https?:\/\/(?:export\.)?arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z]{2})?\/\d{7}(?:v\d+)?)(?:\.pdf)?\/?(?:[?#].*)?$/i, "ARXIV"],
  [/^https?:\/\/(?:dx\.)?doi\.org\/(10\.[^?#]+)$/i, "DOI"],
  [/^https?:\/\/(?:www\.)?zbmath\.org\/\?q=an%3A(\d{4}\.\d{5}|\d{7,8})(?:[&#].*)?$/i, "ZBL"],
  [/^https?:\/\/(?:www\.)?zbmath\.org\/\?q=an:(\d{4}\.\d{5}|\d{7,8})(?:[&#].*)?$/i, "ZBL"],
  [/^https?:\/\/mathscinet\.ams\.org\/mathscinet-getitem\?mr=(?:MR)?(\d{6,8})(?:[&#].*)?$/i, "MR"],
  [/^https?:\/\/(?:www\.)?oeis\.org\/(A\d{6})\/?(?:[?#].*)?$/i, "OEIS"],
  [/^https?:\/\/ui\.adsabs\.harvard\.edu\/abs\/(\d{4}[A-Za-z&.\d]{14}[A-Z])(?:\/abstract)?\/?(?:[?#].*)?$/i, "ADS"],
  [/^https?:\/\/(?:next-gen\.)?materialsproject\.org\/materials\/(mp-\d{1,8})\/?(?:[?#].*)?$/i, "MP"],
  [/^https?:\/\/(?:www\.)?search\.worldcat\.org\/search\?q=bn(?::|%3A)([0-9Xx-]{10,17})(?:[&#].*)?$/i, "ISBN"],
  [/^https?:\/\/(?:www\.)?openalex\.org\/(?:works\/)?(W\d{7,12})\/?(?:[?#].*)?$/i, "OPENALEX"],
  [/^https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/(\d{1,9})\/?(?:[?#].*)?$/i, "PMID"],
];

/** Key for an answer link: a database link-out maps to its identifier, any other http(s) link to "URL:". */
export function hrefToKey(href: unknown): string | null {
  const value = typeof href === "string" ? href.trim() : "";
  if (!value) return null;
  for (const [pattern, prefix] of HREF_PATTERNS) {
    const m = pattern.exec(value);
    if (m) {
      let id = m[1];
      if (prefix === "DOI" || prefix === "ADS") {
        try {
          id = decodeURIComponent(id);
        } catch {
          return null;
        }
      }
      return makeKey(prefix, id);
    }
  }
  return makeKey("URL", value);
}

export function resolveKey(map: CitationMap, key: string): string {
  const direct = (map.aliases && map.aliases[key]) || key;
  if (map.entries && map.entries[direct]) return direct;
  // Normalize alternate backend prefix forms (e.g. ARXIV:arXiv:2309.17452 or COMP:comp:axiom_solve:1)
  if (map.entries) {
    const idx = direct.indexOf(":");
    if (idx > 0) {
      const prefix = direct.slice(0, idx);
      const val = direct.slice(idx + 1);
      const alternates = [
        prefix === "ARXIV" ? `ARXIV:arXiv:${val}` : "",
        prefix === "ZBL" ? `ZBL:Zbl ${val}` : "",
        prefix === "MR" ? `MR:MR${val}` : "",
        prefix === "ISBN" ? `ISBN:ISBN:${val}` : "",
        prefix === "COMP" ? `COMP:comp:${val}` : "",
      ].filter(Boolean);
      for (const alt of alternates) {
        if (map.entries[alt]) return alt;
      }
    }
  }
  return direct;
}

export function entryFor(map: CitationMap, key: string): CitationEntry | undefined {
  return map.entries ? map.entries[resolveKey(map, key)] : undefined;
}

/**
 * The claim support for this occurrence. When client and server occurrence counts drifted there is no exact match;
 * the key's best other support is then returned flagged `fallback: true`, so the popover says it belongs to another
 * mention of the source and never presents it as this sentence's verifier match (UI-017).
 */
export function supportFor(map: CitationMap, key: string, occurrence: number): ClaimSupport | null {
  const resolved = resolveKey(map, key);
  const all = (map.supports || []).filter((s) => s.key === resolved);
  const exact = all.find((s) => s.occurrence === occurrence);
  if (exact) return exact;
  const other = all.find((s) => s.grounded_by_verifier) || all.find((s) => s.highlight) || all[0] || null;
  return other ? { ...other, fallback: true } : null;
}

/** http(s) links only; anything else is not rendered as an external link-out. */
export function safeHref(url: unknown): string | undefined {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim()) ? url.trim() : undefined;
}

/** Safe href for a citation chip (allows http(s) external links and local #comp- / #dataset- anchors). */
function safeChipHref(entry: CitationEntry): string | undefined {
  const ext = safeHref(entry.url);
  if (ext) return ext;
  if (typeof entry.url === "string" && /^#[A-Za-z0-9_.:-]+$/.test(entry.url.trim())) {
    return entry.url.trim();
  }
  if (entry.type === "comp" || entry.type === "dataset") {
    return `#${entry.type}-${entry.id}`;
  }
  return undefined;
}

function hastText(node: HastNode): string {
  if (node.type === "text") return node.value || "";
  return (node.children || []).map(hastText).join("");
}

/** "ARXIV:2309.17452" -> "ARXIV 2309.17452"; "URL:https://evil.example/x" -> "evil.example". */
function describeKey(key: string): string {
  if (key.startsWith("URL:")) {
    const m = /^URL:https?:\/\/([^/?#:]+)/i.exec(key);
    return m ? m[1].toLowerCase() : "another site";
  }
  const i = key.indexOf(":");
  return i > 0 ? `${key.slice(0, i)} ${key.slice(i + 1)}` : key;
}

/**
 * rehype plugin (run after rehypeStripUnsafe, before rehypeCitations) for links whose visible text names an
 * identifier (UI-018). Link text is never scanned for citations, so `[arXiv:2309.17452](https://evil.example/x)` would
 * read as the arXiv record while opening any page. When the identifier in the text is not what the href points to,
 * a visible "(links to …)" suffix names the real destination. `map` (optional) resolves aliases (DOI -> ARXIV).
 */
export function rehypeIdentifierLinkGuard(options?: { map?: CitationMap }) {
  const map = options && options.map;
  const canon = (key: string) => (map ? resolveKey(map, key) : key);
  const visit = (node: HastNode) => {
    for (const child of node.children || []) {
      if (child.type !== "element") continue;
      if (child.tagName === "a") {
        const href = child.properties ? child.properties.href : undefined;
        const textKey = toCiteKey(hastText(child));
        if (!textKey || typeof href !== "string" || !href) continue;
        const hrefKey = hrefToKey(href);
        if (hrefKey && canon(hrefKey) === canon(textKey)) continue;
        // Relative / unrecognised hrefs have no key: name the destination as given.
        const where = hrefKey ? describeKey(hrefKey) : href.slice(0, 60);
        child.properties = { ...child.properties, dataLinkMismatch: "", title: `Opens ${href}` };
        child.children = [
          ...(child.children || []),
          { type: "element", tagName: "span", properties: { className: ["link-destination"] }, children: [{ type: "text", value: ` (links to ${where})` }] },
        ];
        continue;
      }
      visit(child);
    }
  };
  return (tree: unknown) => {
    if (tree) visit(tree as HastNode);
  };
}

const SKIP_TAGS = new Set(["code", "pre", "a", "kbd", "samp", "script", "style", "math", "svg"]);
const UNVERIFIED_STYLE =
  "text-decoration-line:underline;text-decoration-style:dotted;text-underline-offset:3px;cursor:help";

function isKatexElement(node: HastNode): boolean {
  const raw = node.properties?.className ?? node.properties?.class;
  const classes = Array.isArray(raw) ? raw.map(String) : typeof raw === "string" ? raw.split(/\s+/) : [];
  return classes.some((c) => c === "katex" || c === "katex-display" || c === "katex-mathml" || c === "katex-html");
}

/**
 * rehype plugin (run after rehypeStripUnsafe) that wraps cited identifiers in anchors carrying the hast properties
 * dataCiteKey / dataCiteOccurrence (rendered as data-cite-key / data-cite-occurrence). Only keys present in
 * map.entries are linked; ids the verifier rejected get a dotted underline and no link. Text inside
 * code/pre/a/kbd/samp/script/style/math/svg/katex is never touched. Existing links whose href is a known entry are
 * annotated in place, and occurrences are counted per key in document order.
 */
export function rehypeCitations(options: { map: CitationMap }) {
  const map = options && options.map;
  return (tree: unknown) => {
    if (!map || !map.entries || !tree) return;
    const counts = new Map<string, number>();
    const unverified = new Set(map.unverified || []);
    const next = (key: string) => {
      const n = counts.get(key) || 0;
      counts.set(key, n + 1);
      return n;
    };

    const splitText = (value: string): HastNode[] => {
      const out: HastNode[] = [];
      let last = 0;
      for (const m of value.matchAll(CITE_PATTERN)) {
        const raw = keyFromMatch(m);
        if (!raw) continue;
        const key = resolveKey(map, raw);
        const occurrence = next(key);
        const start = m.index ?? 0;
        const entry = map.entries[key];
        let node: HastNode | null = null;
        const chipHref = entry ? safeChipHref(entry) : undefined;
        if (entry && chipHref) {
          node = {
            type: "element",
            tagName: "a",
            properties: {
              href: chipHref,
              className: ["cite-ref"],
              dataCiteKey: key,
              dataCiteOccurrence: String(occurrence),
            },
            children: [{ type: "text", value: m[0] }],
          };
        } else if (unverified.has(key) || unverified.has(raw)) {
          node = {
            type: "element",
            tagName: "span",
            // Covers ids never observed and retracted ids the Verifier vetoed; the notice above the answer says which.
            // The note is also real (visually hidden) text, so screen-reader and touch users get it, not only a hover title (UI-019).
            properties: { className: ["cite-unverified"], title: "Not verified against the retrieved evidence", style: UNVERIFIED_STYLE },
            children: [
              { type: "text", value: m[0] },
              { type: "element", tagName: "span", properties: { className: ["sr-only"] }, children: [{ type: "text", value: " (not verified against the retrieved evidence)" }] },
            ],
          };
        }
        if (!node) continue;
        if (start > last) out.push({ type: "text", value: value.slice(last, start) });
        out.push(node);
        last = start + m[0].length;
      }
      if (!out.length) return [{ type: "text", value }];
      if (last < value.length) out.push({ type: "text", value: value.slice(last) });
      return out;
    };

    const annotateLink = (el: HastNode) => {
      const props = el.properties || {};
      const raw = hrefToKey(props.href);
      if (!raw) return;
      const key = resolveKey(map, raw);
      const occurrence = next(key);
      if (!map.entries[key]) return;
      const existing = props.className;
      const classes = Array.isArray(existing) ? existing.map(String) : typeof existing === "string" ? existing.split(/\s+/) : [];
      el.properties = {
        ...props,
        className: [...classes.filter(Boolean), "cite-ref"],
        dataCiteKey: key,
        dataCiteOccurrence: String(occurrence),
      };
    };

    const walk = (node: HastNode) => {
      const children = node.children;
      if (!children || !children.length) return;
      const out: HastNode[] = [];
      for (const child of children) {
        if (child.type === "text" && typeof child.value === "string") {
          out.push(...splitText(child.value));
          continue;
        }
        if (child.type === "element") {
          if (child.tagName === "a") annotateLink(child);
          else if (!SKIP_TAGS.has(child.tagName || "") && !isKatexElement(child)) walk(child);
        } else if (child.type === "root") {
          walk(child);
        }
        out.push(child);
      }
      node.children = out;
    };

    walk(tree as HastNode);
  };
}
