// Data shaping for the PDE result card (PdeArtifact.tsx), kept free of React so node tests can import it.
//
// The backend (tribos/dynamis/pde) sends the x (and y) grid once at the top level and one value array per
// snapshot: a list over x in 1D, a list of rows over x (each a list over y) in 2D.

export type PdeSnapshot = { t?: number | null; values?: unknown };

export type PdeLevel = {
  n?: number;
  h?: number;
  error?: number;
  difference_to_finer?: number;
  order?: number | null;
};

export type PdeData = {
  equation?: string;
  dimension?: number;
  steady?: boolean;
  method?: string;
  domain?: number[][];
  parameters?: Record<string, number>;
  boundary?: Record<string, string>;
  x?: number[];
  y?: number[];
  times?: number[];
  t_span?: number[];
  snapshots?: PdeSnapshot[];
  field?: unknown;
  range?: number[];
  stability?: {
    scheme?: string;
    name?: string | null;
    number?: number | null;
    limit?: number | null;
    status?: string;
    dt?: number | null;
    requested_dt?: number | null;
  } | null;
  convergence?: {
    levels?: PdeLevel[];
    order?: number | null;
    expected_order?: number;
    richardson_error?: number | null;
    relative_error?: number | null;
    converged?: boolean;
    reference?: string;
    note?: string;
  } | null;
  verification?: {
    exact_solution?: string;
    max_error?: number;
    relative_error?: number;
    agrees?: boolean;
  } | null;
  conservation?: {
    kind?: string;
    relative_drift?: number;
    tolerance?: number;
    conserved?: boolean;
    note?: string;
  } | null;
  probes?: { x?: number; y?: number; values?: number[] }[];
  warnings?: string[];
};

export type Frame1D = { t: number | null; values: number[] };
export type Frame2D = { t: number | null; rows: number[][] };
export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";
export type Badge = { tone: Tone; text: string; title?: string };

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function numbers(v: unknown): number[] {
  return Array.isArray(v) ? v.map((x) => (finite(x) ? x : NaN)) : [];
}

const EQUATION_NAMES: Record<string, string> = {
  heat: "Heat equation",
  wave: "Wave equation",
  poisson: "Poisson equation",
  advection_diffusion: "Advection-diffusion",
  fisher_kpp: "Fisher-KPP",
  burgers: "Viscous Burgers",
};

export function equationName(name: unknown): string {
  const key = typeof name === "string" ? name : "";
  return EQUATION_NAMES[key] ?? (key ? key.replace(/_/g, " ") : "PDE");
}

/** The 1D frames, each the same length as the x grid (frames that do not fit it are dropped). */
export function frames1D(d: PdeData): Frame1D[] {
  const n = numbers(d.x).length;
  return (Array.isArray(d.snapshots) ? d.snapshots : [])
    .map((s) => ({ t: finite(s?.t) ? s.t : null, values: numbers(s?.values) }))
    .filter((f) => n > 1 && f.values.length === n);
}

/** The 2D frames, each a grid of rows over x with one column per y value. */
export function frames2D(d: PdeData): Frame2D[] {
  const nx = numbers(d.x).length;
  const ny = numbers(d.y).length;
  return (Array.isArray(d.snapshots) ? d.snapshots : [])
    .map((s) => ({
      t: finite(s?.t) ? s.t : null,
      rows: Array.isArray(s?.values) ? (s.values as unknown[]).map(numbers) : [],
    }))
    .filter((f) => nx > 0 && f.rows.length === nx && f.rows.every((r) => r.length === ny));
}

/** The value range over every frame, so the axis and the colour scale stay fixed while the time slider moves. */
export function valueRange(values: Iterable<number>): { lo: number; hi: number } {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return { lo: 0, hi: 1 };
  if (lo === hi) {
    const pad = Math.abs(lo) > 0 ? Math.abs(lo) * 0.05 : 0.5;
    return { lo: lo - pad, hi: hi + pad };
  }
  return { lo, hi };
}

export function* allValues1D(frames: Frame1D[]): Generator<number> {
  for (const f of frames) yield* f.values;
}

export function* allValues2D(frames: Frame2D[]): Generator<number> {
  for (const f of frames) for (const r of f.rows) yield* r;
}

/** The colour step of a value on a ramp of `steps` colours (0 = lowest), or -1 for a missing value. */
export function colourLevel(v: number, lo: number, hi: number, steps: number): number {
  if (!Number.isFinite(v)) return -1;
  const t = (v - lo) / (hi - lo || 1);
  return Math.min(steps - 1, Math.max(0, Math.floor(t * steps)));
}

/** The CSS colour of each step: a mix of the two neighbouring theme ramp stops (--heatmap-0 .. --heatmap-5). */
export function rampColours(steps: number, stops = 6): string[] {
  return Array.from({ length: steps }, (_, k) => {
    const p = (steps === 1 ? 0 : k / (steps - 1)) * (stops - 1);
    const i = Math.min(stops - 2, Math.floor(p));
    const share = Math.round((1 - (p - i)) * 100);
    return `color-mix(in oklab, var(--heatmap-${i}) ${share}%, var(--heatmap-${i + 1}))`;
  });
}

/**
 * Runs of equal colour along each row of a 2D frame (column = x index, row = y index), so an 80x80 field draws as
 * a few hundred rectangles instead of 6,400.
 */
export function heatRuns(
  rows: number[][],
  lo: number,
  hi: number,
  steps: number,
): { xi: number; yj: number; span: number; level: number }[] {
  const out: { xi: number; yj: number; span: number; level: number }[] = [];
  const nx = rows.length;
  const ny = nx ? rows[0].length : 0;
  for (let j = 0; j < ny; j += 1) {
    let start = 0;
    let level = colourLevel(rows[0][j], lo, hi, steps);
    for (let i = 1; i <= nx; i += 1) {
      const next = i < nx ? colourLevel(rows[i][j], lo, hi, steps) : NaN;
      if (next !== level) {
        if (level >= 0) out.push({ xi: start, yj: j, span: i - start, level });
        start = i;
        level = next;
      }
    }
  }
  return out;
}

/** The convergence table: one row per mesh level, with the error (or the difference to the next finer level). */
export function convergenceRows(d: PdeData): { n: number | null; h: number | null; error: number | null; order: number | null }[] {
  const levels = Array.isArray(d.convergence?.levels) ? d.convergence.levels : [];
  return levels.map((l) => ({
    n: finite(l?.n) ? l.n : null,
    h: finite(l?.h) ? l.h : null,
    error: finite(l?.error) ? l.error : finite(l?.difference_to_finer) ? l.difference_to_finer : null,
    order: finite(l?.order) ? l.order : null,
  }));
}

function sig(v: number, digits = 2): string {
  return Number(v.toPrecision(digits)).toString();
}

/** The badges that say whether the solution can be trusted: convergence, analytic agreement, conservation, stability. */
export function pdeBadges(d: PdeData): Badge[] {
  const out: Badge[] = [];
  const c = d.convergence;
  if (c) {
    const order = finite(c.order) ? ` (order ${sig(c.order)}${finite(c.expected_order) ? ` of ${c.expected_order}` : ""})` : "";
    out.push(
      c.converged
        ? { tone: "ok", text: `Mesh-converged${order}`, title: c.note || undefined }
        : { tone: "warn", text: `Not shown converged${order}`, title: c.note || "Treat the field as unverified." },
    );
  }
  const v = d.verification;
  if (v && finite(v.relative_error)) {
    out.push({
      tone: v.agrees ? "ok" : "bad",
      text: v.agrees ? `Matches analytic (${sig(v.relative_error * 100)}%)` : `Differs from analytic (${sig(v.relative_error * 100)}%)`,
      title: v.exact_solution ? `u = ${v.exact_solution}` : undefined,
    });
  }
  const k = d.conservation;
  if (k && finite(k.relative_drift)) {
    out.push({
      tone: k.conserved ? "ok" : "warn",
      text: `${k.kind === "energy" ? "Energy" : "Mass"} ${k.conserved ? "conserved" : "drifts"} (${sig(k.relative_drift)})`,
      title: k.note || undefined,
    });
  }
  const s = d.stability;
  if (s?.status) {
    const number = finite(s.number) ? ` ${sig(s.number)}${finite(s.limit) ? ` ≤ ${s.limit}` : ""}` : "";
    const tone: Tone = s.status === "adapted" ? "warn" : "info";
    const text =
      s.status === "adapted"
        ? `Step adapted to dt ${finite(s.dt) ? sig(s.dt, 3) : "?"}${number ? ` (${number.trim()})` : ""}`
        : s.status === "stable"
          ? `Stable (${(s.name || "stability number").split(" ")[0]}${number})`
          : s.status;
    out.push({ tone, text, title: s.name ? `${s.scheme}: ${s.name}` : s.scheme });
  }
  return out;
}

/** "x0: dirichlet, x1: dirichlet" collapsed to "dirichlet" when every edge is the same. */
export function boundarySummary(boundary: Record<string, string> | undefined): string {
  const entries = Object.entries(boundary ?? {});
  if (!entries.length) return "";
  const kinds = new Set(entries.map(([, k]) => k));
  return kinds.size === 1 ? `${entries[0][1]} edges` : entries.map(([e, k]) => `${e} ${k}`).join(", ");
}
