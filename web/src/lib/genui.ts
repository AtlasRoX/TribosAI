// Generative UI: the typed block spec the backend sends (tribos/writer/genui.py) and the writer may embed in an answer
// as a ```ui fenced block. This module holds the types, the parser/validator and the chart geometry, in a plain .ts
// file so node tests can load it; the components live in components/genui/.
//
// Blocks: stats (key quantities), equation (exact solution with its checks), chart (line plot of computed series),
// table, callout and steps. Anything that does not match the shape is dropped, never rendered half-valid.

export const GENUI_SPEC_VERSION = 1;

export interface StatItem {
  label: string;
  value: string;
  unit?: string;
  exact_latex?: string;
  secondary?: string;
  note?: string;
  verified?: boolean;
}
export interface StatsBlock {
  type: "stats";
  title?: string | null;
  items: StatItem[];
}
export interface EquationBlock {
  type: "equation";
  title?: string | null;
  latex: string;
  parts: { label: string; latex: string }[];
  checks: { name: string; passed: boolean }[];
}
export interface ChartSeries {
  name: string;
  points: [number, number][];
  style?: "solid" | "dashed";
}
export interface ChartAxis {
  label: string;
  unit?: string;
  /** "log": base-10 axis (every value must be positive). */
  scale?: "linear" | "log";
}
export interface ChartMark {
  x: number;
  y: number;
  label?: string;
}
export interface ChartBlock {
  type: "chart";
  title?: string | null;
  x: ChartAxis;
  y: ChartAxis;
  series: ChartSeries[];
  marks: ChartMark[];
  /** Curves in the plane (orbits): points stay in time order, both axes share one scale, and every series has a
   *  point at each shared sample index. */
  parametric?: boolean;
}
export interface ChecksBlock {
  type: "checks";
  title?: string | null;
  caption?: string;
  items: { name: string; passed: boolean; detail?: string }[];
}
export interface TableColumn {
  key: string;
  label: string;
  unit?: string;
  align?: "left" | "right";
}
export interface TableBlock {
  type: "table";
  title?: string | null;
  columns: TableColumn[];
  rows: Record<string, string>[];
  caption?: string;
}
export type CalloutTone = "info" | "insight" | "warning" | "ok";
export interface CalloutBlock {
  type: "callout";
  tone: CalloutTone;
  title?: string | null;
  text: string;
}
export interface StepsBlock {
  type: "steps";
  title?: string | null;
  items: { title: string; latex: string; note: string }[];
}
export type UiBlock = StatsBlock | EquationBlock | ChartBlock | TableBlock | CalloutBlock | StepsBlock | ChecksBlock;
export interface AnswerUi {
  version: number;
  title: string;
  source: string;
  blocks: UiBlock[];
}

const TONES: readonly CalloutTone[] = ["info", "insight", "warning", "ok"];
const MAX_POINTS = 2000;

const str = (v: unknown, limit = 600): string => (typeof v === "string" || typeof v === "number" ? String(v).slice(0, limit) : "");
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const finitePair = (p: unknown): p is [number, number] =>
  Array.isArray(p) && p.length >= 2 && Number.isFinite(Number(p[0])) && Number.isFinite(Number(p[1]));

function pairs(v: unknown): [number, number][] {
  if (!Array.isArray(v)) return [];
  return v.filter(finitePair).slice(0, MAX_POINTS).map((p) => [Number(p[0]), Number(p[1])]);
}

/** A block reduced to the allowed shape, or null when it is not valid. Columns given as plain strings and rows given
 * as arrays (the writer's compact table form) are normalised to the keyed form. */
export function normalizeBlock(raw: unknown): UiBlock | null {
  if (!isObj(raw)) return null;
  const title = str(raw.title, 120) || null;
  switch (raw.type) {
    case "stats": {
      const items = (Array.isArray(raw.items) ? raw.items : [])
        .filter(isObj)
        .map((it) => ({
          label: str(it.label, 80),
          value: str(it.value, 60),
          unit: str(it.unit, 30),
          exact_latex: str(it.exact_latex, 300),
          secondary: str(it.secondary, 40),
          note: str(it.note, 160),
          verified: it.verified === true,
        }))
        .filter((it) => it.label && it.value)
        .slice(0, 12);
      return items.length ? { type: "stats", title, items } : null;
    }
    case "equation": {
      const latex = str(raw.latex, 2000);
      if (!latex) return null;
      const parts = (Array.isArray(raw.parts) ? raw.parts : [])
        .filter(isObj)
        .map((p) => ({ label: str(p.label, 60), latex: str(p.latex, 2000) }))
        .filter((p) => p.label && p.latex);
      const checks = (Array.isArray(raw.checks) ? raw.checks : [])
        .filter(isObj)
        .map((c) => ({ name: str(c.name, 120), passed: c.passed === true }))
        .filter((c) => c.name);
      return { type: "equation", title, latex, parts, checks };
    }
    case "chart": {
      const axis = (a: unknown, fallback: string): ChartAxis =>
        isObj(a)
          ? { label: str(a.label, 40) || fallback, unit: str(a.unit, 20), scale: a.scale === "log" ? "log" : "linear" }
          : { label: fallback, unit: "", scale: "linear" };
      const x = axis(raw.x, "x");
      const y = axis(raw.y, "y");
      // A log axis takes positive values only; points are kept in increasing x for the hover search, except on a
      // parametric chart (an orbit), whose points are in time order.
      const parametric = raw.parametric === true && x.scale !== "log" && y.scale !== "log";
      const onAxes = (p: [number, number]) => (x.scale !== "log" || p[0] > 0) && (y.scale !== "log" || p[1] > 0);
      const series = (Array.isArray(raw.series) ? raw.series : [])
        .filter(isObj)
        .map((s): ChartSeries => ({
          name: str(s.name, 60) || "series",
          points: parametric ? pairs(s.points).filter(onAxes) : pairs(s.points).filter(onAxes).sort((a, b) => a[0] - b[0]),
          style: s.style === "dashed" ? "dashed" : "solid",
        }))
        .filter((s) => s.points.length >= 2)
        .slice(0, 4);
      if (!series.length) return null;
      const marks: ChartMark[] = (Array.isArray(raw.marks) ? raw.marks : [])
        .filter(finitePair)
        .map((m) => ({ x: Number(m[0]), y: Number(m[1]), label: str((m as unknown[])[2], 30) || undefined }))
        .filter((m) => onAxes([m.x, m.y]))
        .slice(0, 40);
      return parametric ? { type: "chart", title, x, y, series, marks, parametric } : { type: "chart", title, x, y, series, marks };
    }
    case "table": {
      const rawCols = Array.isArray(raw.columns) ? raw.columns.slice(0, 8) : [];
      const columns: TableColumn[] = rawCols
        .map((c, i): TableColumn | null => {
          if (typeof c === "string") return c.trim() ? { key: String(i), label: c.slice(0, 60), align: "left" } : null;
          if (!isObj(c) || !str(c.label, 60)) return null;
          return { key: str(c.key, 60) || String(i), label: str(c.label, 60), unit: str(c.unit, 20), align: c.align === "right" ? "right" : "left" };
        })
        .filter((c): c is TableColumn => c !== null);
      if (!columns.length) return null;
      const rows = (Array.isArray(raw.rows) ? raw.rows : [])
        .slice(0, 60)
        .map((r): Record<string, string> | null => {
          if (Array.isArray(r)) {
            if (r.length !== columns.length) return null;
            return Object.fromEntries(columns.map((c, i) => [c.key, str(r[i], 80)]));
          }
          return isObj(r) ? Object.fromEntries(columns.map((c) => [c.key, str(r[c.key], 80)])) : null;
        })
        .filter((r): r is Record<string, string> => r !== null);
      if (!rows.length) return null;
      // A column of numbers reads right-aligned.
      for (const c of columns) {
        if (c.align === "left" && rows.every((r) => r[c.key] === "" || Number.isFinite(Number(r[c.key])))) c.align = "right";
      }
      return { type: "table", title, columns, rows, caption: str(raw.caption, 300) };
    }
    case "checks": {
      const items = (Array.isArray(raw.items) ? raw.items : [])
        .filter(isObj)
        .map((c) => ({ name: str(c.name, 240), passed: c.passed === true, detail: str(c.detail, 200) }))
        .filter((c) => c.name)
        .slice(0, 16);
      return items.length ? { type: "checks", title, caption: str(raw.caption, 300), items } : null;
    }
    case "callout": {
      const text = str(raw.text, 1000);
      if (!text) return null;
      const tone = TONES.includes(raw.tone as CalloutTone) ? (raw.tone as CalloutTone) : "info";
      return { type: "callout", tone, title, text };
    }
    case "steps": {
      const items = (Array.isArray(raw.items) ? raw.items : [])
        .filter(isObj)
        .map((it) => ({ title: str(it.title, 160), latex: str(it.latex, 400), note: str(it.note, 300) }))
        .filter((it) => it.title || it.latex)
        .slice(0, 12);
      return items.length ? { type: "steps", title, items } : null;
    }
    default:
      return null;
  }
}

/** The results panel from execution_artifacts.answer_ui, or null. */
export function parseAnswerUi(raw: unknown): AnswerUi | null {
  if (!isObj(raw) || Number(raw.version) !== GENUI_SPEC_VERSION || !Array.isArray(raw.blocks)) return null;
  const blocks = raw.blocks.map(normalizeBlock).filter((b): b is UiBlock => b !== null);
  if (!blocks.length) return null;
  return { version: GENUI_SPEC_VERSION, title: str(raw.title, 120) || "Results", source: str(raw.source, 40), blocks };
}

/** A ```ui fenced block's JSON text as a block, or null (the fence is then shown as plain code). */
export function parseUiFence(text: string): UiBlock | null {
  try {
    return normalizeBlock(JSON.parse(text));
  } catch {
    return null;
  }
}

/** The exact solution on two aligned lines, each part named under it, when the block carries the transient and
 * steady-state parts and its own LaTeX is one line (answers saved before the backend sent the two-line form).
 * `split` says the parts are already shown inside the formula. */
export function equationLatex(block: EquationBlock): { latex: string; split: boolean } {
  if (block.latex.includes(String.raw`\begin{aligned}`)) {
    return { latex: block.latex, split: block.latex.includes(String.raw`\underbrace`) };
  }
  const tr = block.parts.find((p) => /transient/i.test(p.label));
  const ss = block.parts.find((p) => /steady/i.test(p.label));
  const eq = block.latex.indexOf("=");
  if (!tr || !ss || eq <= 0) return { latex: block.latex, split: false };
  const lhs = block.latex.slice(0, eq).trim();
  return {
    latex:
      String.raw`\begin{aligned} ` +
      `${lhs} &= ` +
      String.raw`\underbrace{` +
      tr.latex +
      String.raw`}_{\text{transient}} \\ &\quad + \underbrace{` +
      ss.latex +
      String.raw`}_{\text{steady state}} \end{aligned}`,
    split: true,
  };
}

// Chart geometry ---------------------------------------------------------------------------------------------------

/** About `count` round tick values covering [lo, hi] (1, 2, 2.5 or 5 times a power of ten). */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi === lo) return [lo];
  const span = hi - lo;
  const raw = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.ceil(lo / step - 1e-9) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  return out;
}

/** The [min, max] of all series values, padded by 6% so lines never touch the frame. */
export function extent(series: ChartSeries[], axis: 0 | 1, pad = 0.06): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) for (const p of s.points) {
    lo = Math.min(lo, p[axis]);
    hi = Math.max(hi, p[axis]);
  }
  if (!Number.isFinite(lo)) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  const d = (hi - lo) * pad;
  return axis === 0 ? [lo, hi] : [lo - d, hi + d];
}

/** Index of the point whose x is nearest `x` in an x-sorted list (binary search). */
export function nearestIndex(points: [number, number][], x: number): number {
  if (!points.length) return -1;
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] < x) lo = mid;
    else hi = mid;
  }
  return Math.abs(points[lo][0] - x) <= Math.abs(points[hi][0] - x) ? lo : hi;
}

/** End-of-line label positions: each at its line's end, pushed apart to at least `gap` px and kept inside
 * [top, bottom], in the input order. */
export function directLabelYs(ys: number[], top: number, bottom: number, gap = 15): number[] {
  const order = ys.map((y, i) => ({ y: Math.min(Math.max(y, top), bottom), i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < order.length; k++) order[k].y = Math.max(order[k].y, order[k - 1].y + gap);
  const overflow = order.length ? order[order.length - 1].y - bottom : 0;
  if (overflow > 0) for (const o of order) o.y -= overflow;
  for (let k = order.length - 2; k >= 0; k--) order[k].y = Math.min(order[k].y, order[k + 1].y - gap);
  const out = new Array<number>(ys.length);
  for (const o of order) out[o.i] = o.y;
  return out;
}

/** Ticks of a base-10 log axis over [lo, hi] given in log10 units: the integer exponents inside it (at most `max`). */
export function logTicks(lo: number, hi: number, max = 6): number[] {
  const first = Math.ceil(lo - 1e-9);
  const last = Math.floor(hi + 1e-9);
  const all: number[] = [];
  for (let k = first; k <= last; k++) all.push(k);
  if (all.length <= max) return all;
  const stride = Math.ceil(all.length / max);
  return all.filter((k) => (k - first) % stride === 0);
}

/** An SVG path through the points under the given scales. */
export function linePath(points: [number, number][], sx: (v: number) => number, sy: (v: number) => number): string {
  return points.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join("");
}
