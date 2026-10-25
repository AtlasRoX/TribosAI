/** The verification card's unit systems and the question that restates a solved oscillator with new values. */

// US customary equivalents of the SI units the report uses (factor from SI).
const US_UNITS: Record<string, [string, number]> = {
  m: ["in", 39.37007874],
  N: ["lbf", 0.2248089431],
  J: ["ft·lbf", 0.7375621493],
  W: ["ft·lbf/s", 0.7375621493],
};
export const UNITS_KEY = "tribos_units_v1";

/** A value in the chosen unit system: [value, unit]; units without a US equivalent (s, rad/s) are unchanged. */
export function inUnits(value: unknown, unit: string, system: "si" | "us"): [unknown, string] {
  if (system === "si" || typeof value !== "number" || !US_UNITS[unit]) return [value, unit];
  const [u, f] = US_UNITS[unit];
  return [value * f, u];
}

export interface RerunValues {
  m: string;
  c: string;
  k: string;
  F0: string;
  w: string;
  x0: string;
  v0: string;
  T: string;
}

/** The solved problem's inputs, when it is a harmonically forced mass-spring-damper (the form can restate it). */
export function rerunDefaults(data: Record<string, any>): RerunValues | null {
  const e = data.energy || {};
  const p = data.parameters || {};
  const init = data.initial_state || {};
  const states = Object.keys(init);
  if (![e.m, e.c, e.k].every((v) => typeof v === "number") || states.length < 2) return null;
  const F0 = p.forcing_amplitude?.value;
  const w = p.forcing_frequency?.value;
  if (typeof F0 !== "number" || typeof w !== "number") return null;
  const n = (v: number) => String(Number(v.toPrecision(6)));
  return {
    m: n(e.m), c: n(e.c), k: n(e.k), F0: n(F0), w: n(w),
    x0: n(Number(init[states[0]]) || 0), v0: n(Number(init[states[1]]) || 0), T: n(Number(data.t_end) || 10),
  };
}

export function rerunQuestion(v: RerunValues): string {
  return (
    `Investigate a forced damped mass–spring system governed by m x'' + c x' + kx = F0 cos(ωt), with m = ${v.m} kg, ` +
    `c = ${v.c} N·s/m, k = ${v.k} N/m, F0 = ${v.F0} N, ω = ${v.w} rad/s, x(0) = ${v.x0} m, and x'(0) = ${v.v0}. ` +
    "Derive the analytical solution, including transient and steady-state components. Calculate the natural " +
    "frequency, damping ratio, damped natural frequency, steady-state amplitude, and phase. " +
    `Simulate the system over 0–${v.T} s and verify the solution numerically: residual, RK4 step-size convergence ` +
    "and energy balance."
  );
}
