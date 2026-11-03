// Pure logic of the simulation Explore panel (components/simulation): slider ranges, the debounced re-run that
// aborts the request in flight, and the shaping of simulate / bifurcation / vector-field responses for the charts.
// Free of React so node tests can import it.

export type SimSpec = {
  rhs?: Record<string, string>;
  parameters?: Record<string, number>;
  initial_state?: Record<string, number>;
  t_span?: number[];
  method?: string;
  step_size?: number;
  num_steps?: number;
  model_name?: string | null;
};

export type SliderRange = { min: number; max: number; log: boolean };

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/**
 * The default slider range of a parameter: 0 to 2x its value; a log scale over two decades either side when the value
 * is tiny or huge (1e-3, 1e4), where a linear slider would have no resolution; -1..1 around zero.
 */
export function inferRange(value: number): SliderRange {
  if (!finite(value) || value === 0) return { min: -1, max: 1, log: false };
  const a = Math.abs(value);
  if (value > 0 && (a < 1e-2 || a >= 1e3)) return { min: a / 100, max: a * 100, log: true };
  return value > 0 ? { min: 0, max: 2 * value, log: false } : { min: 2 * value, max: 0, log: false };
}

/** The slider position (0..1000) of a value, and back; log ranges map logarithmically. */
export const SLIDER_STEPS = 1000;

export function toSlider(value: number, r: SliderRange): number {
  const pos = r.log
    ? (Math.log(value) - Math.log(r.min)) / (Math.log(r.max) - Math.log(r.min))
    : (value - r.min) / (r.max - r.min || 1);
  return Math.round(Math.min(1, Math.max(0, finite(pos) ? pos : 0)) * SLIDER_STEPS);
}

export function fromSlider(pos: number, r: SliderRange): number {
  const f = Math.min(1, Math.max(0, pos / SLIDER_STEPS));
  const v = r.log ? Math.exp(Math.log(r.min) + f * (Math.log(r.max) - Math.log(r.min))) : r.min + f * (r.max - r.min);
  return Number(v.toPrecision(6));
}

/** A spec with the explored parameters, initial state and end time (the stored message is never touched). */
export function exploredSpec(base: SimSpec, parameters: Record<string, number>, initial: Record<string, number>, tEnd: number): SimSpec {
  const t0 = Array.isArray(base.t_span) && finite(base.t_span[0]) ? base.t_span[0] : 0;
  return {
    ...base,
    parameters: { ...(base.parameters ?? {}), ...parameters },
    initial_state: { ...(base.initial_state ?? {}), ...initial },
    t_span: [t0, tEnd > t0 ? tEnd : (base.t_span?.[1] ?? t0 + 1)],
    ...(base.method === "RK4" && typeof base.step_size === "number" && base.step_size > 0
      ? { num_steps: Math.round((tEnd - t0) / base.step_size) } : {}),
  };
}

type Timers = {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
};

/**
 * Debounces calls to `run` by `delay` ms and aborts the previous run's AbortSignal whenever a newer one starts, so
 * only the latest request's result is delivered (`onResult`), and a stale response never overwrites a newer one.
 */
export function createLatestRunner<A, R>(
  run: (args: A, signal: AbortSignal) => Promise<R>,
  handlers: { onResult: (r: R) => void; onError: (e: unknown) => void; onStart?: () => void },
  delay = 250,
  timers: Timers = { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) },
) {
  let timer: unknown = null;
  let controller: AbortController | null = null;
  let seq = 0;
  const cancel = () => {
    if (timer !== null) timers.clearTimeout(timer);
    timer = null;
    controller?.abort();
    controller = null;
  };
  return {
    schedule(args: A) {
      if (timer !== null) timers.clearTimeout(timer);
      timer = timers.setTimeout(() => {
        timer = null;
        controller?.abort();
        const mine = new AbortController();
        controller = mine;
        const id = ++seq;
        handlers.onStart?.();
        run(args, mine.signal).then(
          (r) => { if (id === seq && !mine.signal.aborted) handlers.onResult(r); },
          (e) => { if (id === seq && !mine.signal.aborted) handlers.onError(e); },
        );
      }, delay);
    },
    cancel,
  };
}

/** The time course of a simulate response as chart series: {t, series} (only series sampled at every t). */
export function timeCourse(result: unknown): { t: number[]; series: Record<string, number[]> } | null {
  const r = result && typeof result === "object" ? (result as { t?: unknown; trajectories?: unknown }) : {};
  const t = Array.isArray(r.t) ? r.t.filter(finite) : [];
  const traj = r.trajectories && typeof r.trajectories === "object" ? (r.trajectories as Record<string, unknown>) : {};
  const series: Record<string, number[]> = {};
  for (const [k, v] of Object.entries(traj)) {
    if (Array.isArray(v) && v.length === t.length) series[k] = v.map((x) => (finite(x) ? x : NaN));
  }
  return t.length > 1 && Object.keys(series).length ? { t, series } : null;
}

/** The (x, y) path of two states of a time course: the phase portrait. */
export function phasePath(course: { series: Record<string, number[]> } | null, x: string, y: string): [number, number][] {
  const xs = course?.series[x];
  const ys = course?.series[y];
  if (!xs || !ys) return [];
  return xs.map((v, i) => [v, ys[i]] as [number, number]).filter(([a, b]) => finite(a) && finite(b));
}

export type OrbitPoint = { value?: number; maxima?: number[]; minima?: number[]; final?: number | null; steady?: boolean; status?: string };

/** Scatter points of an orbit diagram: every distinct maximum per parameter value (the settled level when steady). */
export function bifurcationScatter(result: unknown): { p: number; y: number; kind: "max" | "steady" }[] {
  const points = result && typeof result === "object" ? (result as { points?: unknown }).points : null;
  const out: { p: number; y: number; kind: "max" | "steady" }[] = [];
  for (const pt of Array.isArray(points) ? (points as OrbitPoint[]) : []) {
    if (!finite(pt?.value)) continue;
    if (pt.steady && finite(pt.final)) out.push({ p: pt.value, y: pt.final, kind: "steady" });
    for (const m of pt.maxima ?? []) if (finite(m)) out.push({ p: pt.value, y: m, kind: "max" });
  }
  return out;
}

/** The parameter value where the orbit first shows more than one distinct maximum (a period doubling), or null. */
export function firstDoubling(result: unknown): number | null {
  const points = result && typeof result === "object" ? (result as { points?: unknown }).points : null;
  for (const pt of Array.isArray(points) ? (points as OrbitPoint[]) : []) {
    if (finite(pt?.value) && (pt.maxima?.length ?? 0) > 1) return pt.value;
  }
  return null;
}

/** Vector-field arrows scaled to the grid cell: [x, y, dx, dy] per grid point, the longest one cell long. */
export function arrows(field: unknown): [number, number, number, number][] {
  const f = field && typeof field === "object" ? (field as { x?: number[]; y?: number[]; u?: number[][]; v?: number[][] }) : {};
  const xs = f.x ?? [];
  const ys = f.y ?? [];
  if (xs.length < 2 || ys.length < 2) return [];
  const cell = Math.min((xs[xs.length - 1] - xs[0]) / (xs.length - 1), (ys[ys.length - 1] - ys[0]) / (ys.length - 1));
  let maxMag = 0;
  ys.forEach((_, j) => xs.forEach((_, i) => {
    const m = Math.hypot(f.u?.[j]?.[i] ?? 0, f.v?.[j]?.[i] ?? 0);
    if (finite(m)) maxMag = Math.max(maxMag, m);
  }));
  if (!(maxMag > 0)) return [];
  const out: [number, number, number, number][] = [];
  ys.forEach((y, j) => xs.forEach((x, i) => {
    const u = f.u?.[j]?.[i];
    const v = f.v?.[j]?.[i];
    if (finite(u) && finite(v)) out.push([x, y, (u / maxMag) * cell * 0.9, (v / maxMag) * cell * 0.9]);
  }));
  return out;
}
