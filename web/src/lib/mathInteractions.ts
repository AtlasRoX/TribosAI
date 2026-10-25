/**
 * Interactive math in rendered answers:
 * - rehypeMathBlocks wraps each display equation in <div class="math-block" data-latex="…"> so it can offer
 *   "Copy LaTeX" and "Copy for Word" (the LaTeX source comes from KaTeX's MathML annotation).
 * - rehypeValueLinks marks numbers that equal a computed value (a verified parameter, an energy term) as
 *   <mark class="value-link" data-value-key="…">, so a click shows where the number was computed.
 */

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

export interface LinkedValue {
  /** Where the value lives ("param:steady_state_amplitude"); cards mark that element with data-value-key. */
  key: string;
  value: number;
  /** What the value is, for the tooltip ("Steady-state amplitude X"). */
  label: string;
}

function classes(node: HastNode): string[] {
  const c = node.properties?.className;
  return Array.isArray(c) ? c.map(String) : typeof c === "string" ? c.split(/\s+/) : [];
}

function textOf(node: HastNode): string {
  if (node.type === "text") return node.value || "";
  return (node.children || []).map(textOf).join("");
}

function findAnnotation(node: HastNode): string | null {
  if (node.type === "element" && node.tagName === "annotation") return textOf(node);
  for (const child of node.children || []) {
    const found = findAnnotation(child);
    if (found !== null) return found;
  }
  return null;
}

export function rehypeMathBlocks() {
  const visit = (node: HastNode) => {
    const kids = node.children || [];
    for (let i = 0; i < kids.length; i++) {
      const child = kids[i];
      if (child.type === "element" && classes(child).includes("katex-display")) {
        kids[i] = {
          type: "element",
          tagName: "div",
          properties: { className: ["math-block"], dataLatex: findAnnotation(child) ?? "" },
          children: [child],
        };
      } else {
        visit(child);
      }
    }
  };
  return (tree: HastNode) => visit(tree);
}

// A number as written in prose or LaTeX: 0.46225, -1.198, 104.175, 1.2e-6 (not a digit of a word like "x2").
const NUMBER_RE = /(?<![\w.])[-−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.]*\d)/g;

/** The linked value a written number stands for: equal within 0.2% (or the number's own rounding), and specific
 * enough to mean it (a decimal, or an integer of 10 or more; "2" or "4" alone would match too much). */
export function matchValue(written: string, values: LinkedValue[]): LinkedValue | null {
  const clean = written.replace("−", "-");
  const n = Number(clean);
  if (!Number.isFinite(n)) return null;
  const decimals = clean.includes(".") ? clean.split(".")[1].replace(/[eE].*/, "").length : 0;
  if (!decimals && Math.abs(n) < 10) return null;
  const rounding = decimals ? 0.5 * 10 ** -decimals : 0.5;
  let best: LinkedValue | null = null;
  let bestErr = Infinity;
  for (const v of values) {
    const err = Math.abs(n - v.value);
    const tol = Math.max(rounding * 1.01, Math.abs(v.value) * 0.002);
    if (err <= tol && err < bestErr && v.value !== 0) {
      best = v;
      bestErr = err;
    }
  }
  return best;
}

function mark(value: LinkedValue, children: HastNode[]): HastNode {
  return {
    type: "element",
    tagName: "mark",
    properties: { className: ["value-link"], dataValueKey: value.key, title: `${value.label}: show where it was computed` },
    children,
  };
}

const SKIP_TAGS = new Set(["code", "pre", "a", "mark", "button", "th"]);

export function rehypeValueLinks(options: { values?: LinkedValue[] } = {}) {
  const values = options.values || [];
  const visit = (node: HastNode) => {
    const kids = node.children || [];
    for (let i = 0; i < kids.length; i++) {
      const child = kids[i];
      if (child.type === "element") {
        if (SKIP_TAGS.has(child.tagName || "")) continue;
        const cls = classes(child);
        if (cls.includes("katex")) {
          // Inline math: the whole formula links to the first value its LaTeX source states.
          const tex = findAnnotation(child) || "";
          const hit = (tex.match(NUMBER_RE) || []).map((n) => matchValue(n, values)).find(Boolean);
          if (hit) kids[i] = mark(hit, [child]);
          continue;
        }
        if (cls.includes("math-block")) continue;
        visit(child);
        continue;
      }
      if (child.type !== "text" || !child.value) continue;
      const text = child.value;
      const parts: HastNode[] = [];
      let last = 0;
      for (const m of text.matchAll(NUMBER_RE)) {
        const hit = matchValue(m[0], values);
        if (!hit || m.index === undefined) continue;
        if (m.index > last) parts.push({ type: "text", value: text.slice(last, m.index) });
        parts.push(mark(hit, [{ type: "text", value: m[0] }]));
        last = m.index + m[0].length;
      }
      if (!parts.length) continue;
      if (last < text.length) parts.push({ type: "text", value: text.slice(last) });
      kids.splice(i, 1, ...parts);
      i += parts.length - 1;
    }
  };
  return (tree: HastNode) => {
    if (values.length) visit(tree);
  };
}

const PARAMETER_LABELS: Record<string, string> = {
  natural_frequency: "Natural frequency",
  damping_ratio: "Damping ratio",
  damped_frequency: "Damped frequency",
  decay_rate: "Decay rate",
  time_constant: "Time constant",
  frequency_ratio: "Frequency ratio",
  static_deflection: "Static deflection",
  steady_state_amplitude: "Steady-state amplitude",
  dynamic_amplification: "Dynamic amplification",
  phase_lag: "Phase lag",
  mean_steady_power: "Mean steady-state power",
};

/** The values a run computed that an answer may quote: verified parameters (and the phase in degrees) and the
 * energy-balance terms. */
export function linkedValuesFrom(artifacts: Record<string, any> | null | undefined): LinkedValue[] {
  const rep = artifacts?.ode_verification;
  if (!rep || typeof rep !== "object") return [];
  const out: LinkedValue[] = [];
  for (const [key, p] of Object.entries((rep.parameters || {}) as Record<string, any>)) {
    if (!p || typeof p.value !== "number" || !PARAMETER_LABELS[key]) continue;
    out.push({ key: `param:${key}`, value: p.value, label: PARAMETER_LABELS[key] });
    if (typeof p.degrees === "number") out.push({ key: `param:${key}`, value: p.degrees, label: `${PARAMETER_LABELS[key]} (degrees)` });
  }
  const energy = rep.energy || {};
  const terms: [string, string][] = [["E0", "Initial energy"], ["ET", "Final energy"], ["work_in", "Work in by forcing"], ["work_damping", "Energy dissipated by damping"]];
  for (const [k, label] of terms) {
    if (typeof energy[k] === "number") out.push({ key: `energy:${k}`, value: energy[k], label });
  }
  return out;
}
