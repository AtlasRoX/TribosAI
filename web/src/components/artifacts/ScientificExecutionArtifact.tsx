"use client";

import React from "react";
import { FlaskConical, Download } from "lucide-react";
import { Card, Disclosure, Pill, Section, styles } from "../agentic/ui";
import type { FeatureArtifactProps } from "./registry";
import { executionLabel, scientificExecution } from "./scientificExecutionData";

function download(text: string, filename: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ScientificExecutionArtifact({ data, artifacts }: FeatureArtifactProps) {
  const record = scientificExecution(data);
  if (!record) return null;
  const complete = ["executed", "reused"].includes(record.status) && record.request_match;
  const resultKey = record.kind === "ode_rk4" ? "dynamis" : record.kind === "heat_ftcs" ? "pde" : record.kind === "monte_carlo" ? "monte_carlo" : "engineering_calc";
  const stem = record.kind.replace(/[^a-z0-9_]/gi, "_");
  return (
    <Card icon={<FlaskConical size={17} />} title="Scientific execution" label="Scientific execution details" collapsible
      meta={<Pill tone={complete ? "ok" : "warn"}>{executionLabel(record)}</Pill>}>
      <p className={styles.note}>{record.tool}{typeof record.elapsed_seconds === "number" ? ` · ${record.elapsed_seconds.toFixed(3)} s` : ""}</p>
      {record.verification_scope && <p className={styles.note}>{record.verification_scope}</p>}
      {record.error && <p className={styles.warnNote}>{record.error}</p>}
      <Section title="Execution checks">
        <ul>{record.checks.map((check) => <li key={check.name}>{check.passed ? "Pass" : "Fail"}: {check.name}</li>)}</ul>
      </Section>
      <div className={styles.chips}>
        <button type="button" className={styles.smallBtn} onClick={() => download(JSON.stringify({ execution: record, result: artifacts[resultKey] }, null, 2), `${stem}_execution.json`, "application/json")}>
          <Download size={13} aria-hidden /> Download inputs and results
        </button>
        {typeof record.reproduction_script === "string" && <button type="button" className={styles.smallBtn} onClick={() => download(record.reproduction_script as string, `${stem}_reproduce.py`, "text/x-python")}>
          <Download size={13} aria-hidden /> Download reproduction recipe
        </button>}
      </div>
      <Disclosure summary="Exact inputs and provenance">
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(record.request && Object.keys(record.request).length > 0 ? record.request : { tasks_executed: record.tasks_executed ?? 5, environment: record.package_versions }, null, 2)}</pre>
        {record.result_sha256 && <p className={styles.note} style={{ overflowWrap: "anywhere" }}>Result SHA-256: {record.result_sha256}</p>}
        {Boolean(record.package_versions && typeof record.package_versions === "object") && (
          <p className={styles.note}>
            Packages: {Object.entries(record.package_versions as Record<string, string>).map(([k, v]) => `${k} ${v}`).join(" · ")}
          </p>
        )}
        <p className={styles.note}>The recipe calls the same numerical tool. Its download is not a claim that the recipe itself was independently executed.</p>
      </Disclosure>
    </Card>
  );
}
