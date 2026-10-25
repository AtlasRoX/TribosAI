"use client";

// Uncertainty propagation: the propagated value, the contribution budget and the Monte Carlo histogram.
//
// The backend reports the result as value +/- U (k=2) plus a budget row per input (its standard uncertainty, the
// sensitivity coefficient and the share of the combined variance it explains) and, when the Monte Carlo ran, a
// histogram of the sampled output. The card draws the budget as bars so the dominant contributor is obvious.

import React from "react";
import { Sigma } from "lucide-react";
import { Card, Disclosure, Pill, Section, Stats, arr, fmt, isNum, str, styles } from "../agentic/ui";

export type UncertaintyBudgetEntry = {
  variable?: string;
  value?: number;
  std_uncertainty?: number;
  unit?: string;
  distribution?: string;
  sensitivity?: number;
  contribution?: number;
  variance_contribution?: number;
  percentage?: number;
};

export type UncertaintyArtifactData = {
  expression?: string;
  nominal_value?: number;
  standard_uncertainty?: number;
  expanded_uncertainty?: number;
  coverage_factor?: number;
  unit?: string;
  formatted?: string;
  method?: string;
  budget?: UncertaintyBudgetEntry[];
  linear?: Record<string, unknown>;
  monte_carlo?: {
    mean?: number;
    std?: number;
    interval_95?: number[];
    skewness?: number;
    n_samples?: number;
    histogram?: { counts?: number[]; bin_edges?: number[] };
  } | null;
  warnings?: string[];
  autofilled_constants?: string[];
};

const W = 280;
const H = 120;
const M = { l: 30, r: 8, t: 8, b: 20 };

/** The Monte Carlo histogram as an SVG path plus its bar tops, so the shape of the output is visible. */
function Histogram({ counts, binEdges }: { counts: number[]; binEdges: number[] }) {
  if (!counts.length || counts.length !== binEdges.length - 1) return null;
  const maxCount = Math.max(...counts);
  if (!(maxCount > 0)) return null;
  const lo = binEdges[0];
  const hi = binEdges[binEdges.length - 1];
  const span = hi - lo || 1;
  const x = (v: number) => M.l + ((v - lo) / span) * (W - M.l - M.r);
  const bw = (W - M.l - M.r) / counts.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monte Carlo histogram of the propagated output">
      <line className={styles.axis} x1={M.l} y1={H - M.b} x2={W - M.r} y2={H - M.b} />
      <line className={styles.axis} x1={M.l} y1={M.t} x2={M.l} y2={H - M.b} />
      {counts.map((c, i) => {
        const h = (c / maxCount) * (H - M.b - M.t);
        return (
          <rect
            key={i}
            className={styles.seriesObs}
            x={x(binEdges[i])}
            y={H - M.b - h}
            width={Math.max(0.5, bw - 1)}
            height={h}
            opacity={0.75}
          >
            <title>{`${fmt(binEdges[i], 4)} to ${fmt(binEdges[i + 1], 4)}: ${c} samples`}</title>
          </rect>
        );
      })}
      <text className={styles.axisText} x={M.l} y={H - 6}>
        {fmt(lo, 3)}
      </text>
      <text className={styles.axisText} x={W - M.r} y={H - 6} textAnchor="end">
        {fmt(hi, 3)}
      </text>
    </svg>
  );
}

/** The result card for a propagated uncertainty. */
export function UncertaintyArtifact({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const d = data as UncertaintyArtifactData;
  const budget = arr<UncertaintyBudgetEntry>(d.budget).filter((b) => b && typeof b === "object");
  const mc = d.monte_carlo && typeof d.monte_carlo === "object" ? d.monte_carlo : null;
  const warnings = arr<string>(d.warnings).filter((w) => typeof w === "string" && w);
  const constants = arr<string>(d.autofilled_constants).filter((c) => typeof c === "string" && c);
  const unit = str(d.unit);
  const k = isNum(d.coverage_factor) ? d.coverage_factor : 2;
  const method = str(d.method) || "both";
  const interval = mc && Array.isArray(mc.interval_95) ? mc.interval_95 : [];

  const headline = str(d.formatted) || `${fmt(d.nominal_value, 6)} ± ${fmt(d.expanded_uncertainty, 3)} ${unit}`.trim();
  const stats = [
    { label: "Value", value: fmt(d.nominal_value, 6), sub: unit || undefined },
    { label: `U (k=${k})`, value: fmt(d.expanded_uncertainty, 3), sub: unit || undefined },
    { label: "Standard uncertainty", value: fmt(d.standard_uncertainty, 3), sub: unit || undefined },
    mc && isNum(mc.mean) ? { label: "MC mean", value: fmt(mc.mean, 6) } : null,
    mc && isNum(mc.std) ? { label: "MC std", value: fmt(mc.std, 3) } : null,
    mc && isNum(mc.skewness) ? { label: "Skewness", value: fmt(mc.skewness, 3) } : null,
    mc && isNum(mc.n_samples) ? { label: "Samples", value: String(mc.n_samples) } : null,
  ].filter((x): x is { label: string; value: string; sub?: string } => x != null);

  // The dominant contributor drives the tone of the bar chart: one input above 80% is worth flagging.
  const maxPct = budget.reduce((m, b) => (isNum(b.percentage) ? Math.max(m, b.percentage) : m), 0);

  return (
    <Card
      icon={<Sigma style={{ width: 15, height: 15 }} />}
      title="Uncertainty propagation"
      meta={`${method === "both" ? "linear + Monte Carlo" : method} · ${headline}`}
      label="Propagated uncertainty"
      collapsible
      defaultOpen={false}
    >
      {stats.length > 0 && (
        <Section title="Result" meta={str(d.expression) || undefined}>
          <Stats items={stats} />
        </Section>
      )}

      {constants.length > 0 && (
        <Section title="Constants filled in" hint="CODATA values and their uncertainties were used for these symbols">
          <p className={styles.note}>{constants.join(", ")}</p>
        </Section>
      )}

      {budget.length > 0 && (
        <Section
          title="Contribution budget"
          meta={`${budget.length} input${budget.length === 1 ? "" : "s"}`}
          hint="Share of the combined variance explained by each input"
        >
          <div>
            {budget.map((b, i) => {
              const p = isNum(b.percentage) ? b.percentage : 0;
              const tone = maxPct > 80 && p >= maxPct - 1e-9 ? "warn" : "info";
              return (
                <div key={b.variable || i}>
                  <div className={styles.barRow}>
                    <span className={styles.barLabel}>{str(b.variable) || "—"}</span>
                    <span className={styles.barTrack}>
                      <span
                        className={`${styles.barFill} ${tone === "warn" ? styles.barFillWarn : ""}`}
                        style={{ width: `${Math.max(0, Math.min(100, p))}%` }}
                      />
                    </span>
                    <span className={styles.barValue}>{`${fmt(p, 1)}%`}</span>
                  </div>
                </div>
              );
            })}
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Input</th>
                  <th scope="col" className={styles.num}>
                    Value
                  </th>
                  <th scope="col" className={styles.num}>
                    Standard uncertainty
                  </th>
                  <th scope="col" className={styles.num}>
                    Sensitivity
                  </th>
                  <th scope="col" className={styles.num}>
                    Share
                  </th>
                </tr>
              </thead>
              <tbody>
                {budget.map((b, i) => (
                  <tr key={b.variable || i}>
                    <td className={styles.mono}>{str(b.variable) || "—"}</td>
                    <td className={styles.num}>
                      {fmt(b.value, 4)}
                      {b.unit ? ` ${b.unit}` : ""}
                    </td>
                    <td className={styles.num}>{fmt(b.std_uncertainty, 4)}</td>
                    <td className={styles.num}>{fmt(b.sensitivity, 4)}</td>
                    <td className={styles.num}>{isNum(b.percentage) ? `${fmt(b.percentage, 1)}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {mc && isNum(mc.mean) && (
        <Section
          title="Monte Carlo"
          meta={interval.length === 2 ? `95% interval [${fmt(interval[0], 4)}, ${fmt(interval[1], 4)}]` : undefined}
          hint="Distribution of the propagated output over the sampled inputs"
        >
          {mc.histogram && (
            <div className={styles.plainChart}>
              <Histogram counts={arr<number>(mc.histogram.counts)} binEdges={arr<number>(mc.histogram.bin_edges)} />
            </div>
          )}
          {method === "both" && isNum(d.standard_uncertainty) && isNum(mc.std) && (
            <p className={styles.note}>
              First-order GUM standard uncertainty {fmt(d.standard_uncertainty, 3)} versus Monte Carlo {fmt(mc.std, 3)}.
            </p>
          )}
        </Section>
      )}

      {warnings.length > 0 && (
        <Section title="Warnings">
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>
                <Pill tone="warn">warning</Pill> {w}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Disclosure summary="How to read this">
        <p className={styles.note} style={{ marginTop: 0 }}>
          The linear method is the first-order GUM expansion: it multiplies each input&apos;s standard uncertainty by the
          partial derivative of the formula and combines the results in quadrature. It is accurate for small
          uncertainties and symmetric for a linear formula. The Monte Carlo method samples the inputs and evaluates the
          formula directly, so it captures curvature and asymmetry. When the two disagree, the formula is not linear over
          the uncertainty range and the Monte Carlo result is the more trustworthy one.
        </p>
      </Disclosure>
    </Card>
  );
}

export default UncertaintyArtifact;
