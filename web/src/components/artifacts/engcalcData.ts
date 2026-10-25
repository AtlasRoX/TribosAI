// Data shaping for the engineering-calculation card (EngineeringCalcArtifact.tsx), free of React for node tests.
//
// The backend (tribos/engcalc) sends execution_artifacts.engineering_calc = {calculations: [...]}, one entry per
// physis_engineering_calc call of the turn.

export type EngInput = { name?: string; value?: unknown; unit?: string; source?: string; given_as?: string | null; uncertainty?: number | null };
export type EngResult = {
  name?: string;
  label?: string;
  value?: number;
  unit?: string;
  display_value?: number;
  display_unit?: string;
  uncertainty?: { formatted?: string; budget?: { variable?: string; percentage?: number }[] } | null;
};
export type EngCheck = { name?: string; ok?: boolean; detail?: string; utilisation?: number | null };
export type EngCalculation = {
  calculator?: string;
  title?: string;
  reference?: { source?: string; section?: string };
  material?: { id?: string; name?: string; source?: string; note?: string } | null;
  inputs?: EngInput[];
  results?: EngResult[];
  utilisation?: { value?: number; governing?: string; ok?: boolean; detail?: string } | null;
  checks?: EngCheck[];
  validity?: EngCheck[];
  formulas?: string[];
  assumptions?: string[];
  warnings?: string[];
  notes?: string[];
};

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function calculations(data: unknown): EngCalculation[] {
  const list = data && typeof data === "object" ? (data as { calculations?: unknown }).calculations : null;
  return Array.isArray(list)
    ? list.filter((c): c is EngCalculation => !!c && typeof c === "object" && Array.isArray((c as EngCalculation).results))
    : [];
}

const SUPERSCRIPT: Record<string, string> = { "2": "²", "3": "³", "4": "⁴", "-1": "⁻¹", "-2": "⁻²" };

/** "W/(m^2*K)" -> "W/(m²·K)", "degC" -> "°C", "1" -> "" (dimensionless). */
export function prettyUnit(unit: string | undefined): string {
  if (!unit || unit === "1") return "";
  return unit
    .replace(/degC/g, "°C")
    .replace(/degree/g, "°")
    .replace(/\^(-?\d)/g, (_, p: string) => SUPERSCRIPT[p] ?? `^${p}`)
    .replace(/\*/g, "·");
}

/** A number to `digits` significant figures, in plain or scientific notation as its size needs. */
export function sig(v: number, digits = 4): string {
  if (!finite(v)) return "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e-3 && a < 1e6) return String(Number(v.toPrecision(digits)));
  const [mantissa, exponent] = v.toExponential(digits - 1).split("e");
  return `${Number(mantissa)}×10${superscript(String(Number(exponent)))}`;
}

function superscript(text: string): string {
  const digits = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  return [...text].map((c) => (c === "-" ? "⁻" : (digits[Number(c)] ?? c))).join("");
}

/** The value of a result as shown: its display unit when one is given. */
export function shownResult(r: EngResult): { value: string; unit: string; uncertainty: string | null } {
  const useDisplay = finite(r.display_value) && !!r.display_unit;
  return {
    value: sig(useDisplay ? (r.display_value as number) : (r.value as number)),
    unit: prettyUnit(useDisplay ? r.display_unit : r.unit),
    uncertainty: r.uncertainty?.formatted ? r.uncertainty.formatted.replace(/degC/g, "°C") : null,
  };
}

export function shownInput(i: EngInput): string {
  if (Array.isArray(i.value)) return `${i.value.length} item${i.value.length === 1 ? "" : "s"}`;
  if (typeof i.value === "string") return i.value.replace(/_/g, " ");
  if (i.given_as) return i.given_as;
  return `${sig(i.value as number)} ${prettyUnit(i.unit)}`.trim();
}

export type UtilTone = "ok" | "warn" | "bad";

/** The tone of a utilisation: comfortable below 0.8, close to the limit up to 1, failing above it. */
export function utilisationTone(u: number | undefined | null, ok?: boolean): UtilTone {
  if (!finite(u)) return ok === false ? "bad" : "ok";
  if (u > 1 || ok === false) return "bad";
  return u > 0.8 ? "warn" : "ok";
}

export function citation(c: EngCalculation): string {
  const ref = c.reference ?? {};
  return [ref.source, ref.section].filter(Boolean).join(", ");
}
