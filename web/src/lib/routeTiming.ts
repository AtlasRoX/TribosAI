/** How long answers take per approach, learned from this browser's own runs (median of the last 20). */

const KEY = "tribos_route_timing_v1";
const KEEP = 20;
// Before any run of an approach is recorded: typical durations in seconds.
const PRIORS: Record<string, number> = {
  "Direct workflow": 180,
  "Plan & execute": 360,
  Supervisor: 420,
  Swarm: 420,
  Debate: 480,
};

type Store = Record<string, number[]>;

function read(): Store {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(KEY) : null;
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

export function recordDuration(label: string, seconds: number): void {
  if (!label || !Number.isFinite(seconds) || seconds <= 0) return;
  const store = read();
  store[label] = [...(store[label] || []), Math.round(seconds)].slice(-KEEP);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    // timing is a hint; a full store just keeps the priors
  }
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Expected seconds for an approach: this browser's median once it has 3 runs, else the prior. */
export function expectedSeconds(label: string, store: Store = read()): number | null {
  const runs = store[label] || [];
  return runs.length >= 3 ? median(runs) : PRIORS[label] ?? null;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(5, Math.round(seconds / 5) * 5)} s`;
  const m = Math.round(seconds / 60);
  return `${m} min`;
}

/** "about 2 min left" from the expected total and the time already spent; null once past the estimate. */
export function remainingText(expected: number | null, elapsed: number): string | null {
  if (!expected) return null;
  const left = expected - elapsed;
  if (left <= 15) return elapsed > expected * 1.5 ? "taking longer than usual" : "almost done";
  return `about ${formatDuration(left)} left`;
}
