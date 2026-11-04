"use client";

import React from "react";
import { Sigma } from "lucide-react";
import { Card, styles } from "../agentic/ui";
import type { FeatureArtifactProps } from "./registry";

export function MonteCarloArtifact({ data }: FeatureArtifactProps) {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  if (record.status !== "completed" || typeof record.estimate !== "number") return null;
  const rows = [
    ["Estimate", record.estimate], ["Sample-based standard error", record.standard_error],
    ["Samples", record.num_samples], ["Seed", record.seed], ["Generator", record.generator],
    ["Reference", record.reference], ["Discrepancy / SE", record.standard_errors_from_reference],
  ];
  return <Card title="Monte Carlo quadrature" label="Monte Carlo computation" icon={<Sigma size={17} />} collapsible>
    <div className={styles.tableScroll}><table className={styles.table}><tbody>
      {rows.filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => <tr key={String(key)}>
        <th scope="row">{String(key)}</th><td>{String(value)}</td>
      </tr>)}
    </tbody></table></div>
    <p className={styles.note}>The standard error estimates sampling uncertainty; it does not certify an exact integral.</p>
  </Card>;
}
