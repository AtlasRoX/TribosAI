"use client";

import React from "react";
import { Download, FileCode2, FileSpreadsheet } from "lucide-react";
import type { ExecutionArtifacts } from "@/types/chat";
import styles from "./ReproductionFiles.module.css";

interface FileItem {
  name: string;
  description: string;
  meta: string;
  mime: string;
  icon: React.ReactNode;
  content: string;
}

function sizeText(text: string): string {
  const bytes = new Blob([text]).size;
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}

export function trajectoryCsv(data: Record<string, any>): string | null {
  const t = Array.isArray(data?.t) ? (data.t as number[]) : null;
  const series = data?.trajectories && typeof data.trajectories === "object" ? (data.trajectories as Record<string, number[]>) : null;
  if (!t || !series) return null;
  const names = Object.keys(series).filter((k) => Array.isArray(series[k]) && series[k].length === t.length);
  if (!names.length) return null;
  const rows = t.map((ti, i) => [ti, ...names.map((n) => series[n][i])].join(","));
  return [["t", ...names].join(","), ...rows].join("\n") + "\n";
}

function download(item: FileItem) {
  const url = URL.createObjectURL(new Blob([item.content], { type: item.mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = item.name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Files that reproduce the answer's computed results: the standalone verification script (RK4 convergence and energy
 * balance) and the simulated trajectory as CSV. Built in the browser from the run's artifacts; nothing is uploaded.
 */
export function ReproductionFiles({ artifacts }: { artifacts: ExecutionArtifacts }) {
  const items: FileItem[] = [];
  const seenNames = new Set<string>();

  const script = artifacts.ode_verification?.script;
  if (typeof script === "string" && script.trim()) {
    items.push({
      name: "verify_solution.py",
      description: "Recomputes the RK4 convergence table and the energy balance",
      meta: `Python · NumPy · ${script.trimEnd().split("\n").length} lines · ${sizeText(script)}`,
      mime: "text/x-python",
      icon: <FileCode2 style={{ width: 16, height: 16 }} aria-hidden="true" />,
      content: script,
    });
    seenNames.add("verify_solution.py");
  }

  // Direct downloadable artifacts (CSV / JSON / Python / datasets)
  const rawDownloads = (artifacts as Record<string, unknown>).downloads ?? (artifacts as Record<string, unknown>).files;
  if (Array.isArray(rawDownloads)) {
    for (const f of rawDownloads) {
      if (f && typeof f === "object" && typeof f.name === "string" && typeof f.content === "string") {
        if (!seenNames.has(f.name)) {
          const isCsv = f.name.endsWith(".csv");
          items.push({
            name: f.name,
            description: typeof f.description === "string" ? f.description : "Downloaded reproduction artifact",
            meta: typeof f.meta === "string" ? f.meta : sizeText(f.content),
            mime: typeof f.mime === "string" ? f.mime : isCsv ? "text/csv" : "application/json",
            icon: isCsv ? (
              <FileSpreadsheet style={{ width: 16, height: 16 }} aria-hidden="true" />
            ) : (
              <FileCode2 style={{ width: 16, height: 16 }} aria-hidden="true" />
            ),
            content: f.content,
          });
          seenNames.add(f.name);
        }
      }
    }
  }

  const sim = (artifacts as Record<string, unknown>).oscillator_simulation ?? artifacts.dynamis ?? artifacts.vivarix;
  const csv = sim && typeof sim === "object" ? trajectoryCsv(sim as Record<string, unknown>) : null;
  if (csv && !seenNames.has("trajectory.csv") && !seenNames.has("oscillator_rk4_trajectory.csv")) {
    items.push({
      name: "trajectory.csv",
      description: "Simulated state variables over time",
      meta: `CSV · ${(csv.trimEnd().split("\n").length - 1).toLocaleString()} rows · ${sizeText(csv)}`,
      mime: "text/csv",
      icon: <FileSpreadsheet style={{ width: 16, height: 16 }} aria-hidden="true" />,
      content: csv,
    });
    seenNames.add("trajectory.csv");
  }
  if (!items.length) return null;
  return (
    <section className={styles.files} aria-label="Reproducible files">
      <div className={styles.heading}>
        Files <span className={styles.count}>{items.length}</span>
        <span className={styles.hint}>Reproduce the computed results locally</span>
      </div>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.name}>
            <button type="button" className={styles.file} onClick={() => download(item)} title={`Download ${item.name}`}>
              <span className={styles.icon}>{item.icon}</span>
              <span className={styles.text}>
                <span className={styles.name}>{item.name}</span>
                <span className={styles.desc}>{item.description}</span>
                <span className={styles.meta}>{item.meta}</span>
              </span>
              <Download className={styles.dl} style={{ width: 15, height: 15 }} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
