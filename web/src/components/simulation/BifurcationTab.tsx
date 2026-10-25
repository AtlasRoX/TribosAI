"use client";

// A bifurcation (orbit) diagram: sweep one parameter, and for each value plot the distinct maxima of an observable
// after the transient. One point per value is a period-1 orbit, two a period-2 orbit, a cloud chaos; an equilibrium
// shows as its settled level. The sweep runs on request (it is the costly call), and a newer run aborts the older.

import React, { useEffect, useRef, useState } from "react";
import { fmt, styles as ui } from "../agentic/ui";
import { type SimSpec, bifurcationScatter, firstDoubling } from "@/lib/simulationExplore";
import { type SimulateApi, bifurcation, shownError } from "@/services/simulateService";
import styles from "./Simulation.module.css";

const W = 340;
const H = 220;
const M = 34;

export function BifurcationTab({ api, spec }: { api: SimulateApi; spec: SimSpec }) {
  const params = Object.entries(spec.parameters ?? {});
  const states = Object.keys(spec.rhs ?? spec.initial_state ?? {});
  const [parameter, setParameter] = useState(params[0]?.[0] ?? "");
  const base = spec.parameters?.[parameter] ?? 1;
  const [start, setStart] = useState(base ? base / 2 : 0);
  const [stop, setStop] = useState(base ? base * 2 : 1);
  const [steps, setSteps] = useState(60);
  const [observable, setObservable] = useState(states[0] ?? "");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  if (!params.length) return <p className={ui.note}>This model has no parameter to sweep.</p>;
  const run = () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setBusy(true);
    setError(null);
    bifurcation(api, { spec, parameter, start, stop, steps, observable, transient_fraction: 0.5 }, mine.signal).then(
      (r) => {
        if (mine.signal.aborted) return;
        setResult(r);
        setBusy(false);
      },
      (e) => {
        if (mine.signal.aborted) return;
        setError(shownError(e));
        setBusy(false);
      },
    );
  };
  const pts = bifurcationScatter(result);
  const doubling = firstDoubling(result);
  const ys = pts.map((p) => p.y);
  const lo = ys.length ? Math.min(...ys) : 0;
  const hi = ys.length ? Math.max(...ys) : 1;
  const sx = (p: number) => M + ((p - start) / (stop - start || 1)) * (W - 2 * M);
  const sy = (y: number) => H - M - ((y - lo) / (hi - lo || 1)) * (H - 2 * M);
  const truncated = !!(result && typeof result === "object" && (result as { truncated?: boolean }).truncated);
  const num = (set: (v: number) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    if (Number.isFinite(e.target.valueAsNumber)) set(e.target.valueAsNumber);
  };
  return (
    <div>
      <div className={styles.icRow}>
        <label className={styles.ic}>
          parameter
          <select value={parameter} onChange={(e) => setParameter(e.target.value)}>
            {params.map(([k]) => <option key={k}>{k}</option>)}
          </select>
        </label>
        <label className={styles.ic}>from <input type="number" className={styles.num} step="any" value={start} onChange={num(setStart)} /></label>
        <label className={styles.ic}>to <input type="number" className={styles.num} step="any" value={stop} onChange={num(setStop)} /></label>
        <label className={styles.ic}>
          steps <input type="number" className={styles.num} min={2} max={200} value={steps} onChange={num((v) => setSteps(Math.max(2, Math.min(200, Math.round(v)))))} />
        </label>
        <label className={styles.ic}>
          observable
          <select value={observable} onChange={(e) => setObservable(e.target.value)}>
            {states.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <button type="button" className={styles.reset} onClick={run} disabled={busy || stop === start}>
          {busy ? "Sweeping…" : "Run sweep"}
        </button>
      </div>
      {error && <p className={ui.warnNote} role="status">{error}</p>}
      {pts.length > 0 && (
        <div className={ui.plainChart}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Bifurcation diagram: maxima of ${observable} against ${parameter}`}>
            <rect x={M} y={M} width={W - 2 * M} height={H - 2 * M} fill="none" className={ui.axis} />
            {pts.map((p, i) => (
              <circle key={i} cx={sx(p.p)} cy={sy(p.y)} r={p.kind === "steady" ? 1.6 : 1.2} className={p.kind === "steady" ? styles.steady : styles.dot} />
            ))}
            {doubling != null && <line x1={sx(doubling)} x2={sx(doubling)} y1={M} y2={H - M} className={ui.thresholdLine} />}
            <text className={ui.axisText} x={W / 2} y={H - 8} textAnchor="middle">{parameter}</text>
            <text className={ui.axisText} x={M} y={H - 18}>{fmt(start, 3)}</text>
            <text className={ui.axisText} x={W - M} y={H - 18} textAnchor="end">{fmt(stop, 3)}</text>
            <text className={ui.axisText} x={M - 3} y={M + 8} textAnchor="end">{fmt(hi, 3)}</text>
            <text className={ui.axisText} x={M - 3} y={H - M} textAnchor="end">{fmt(lo, 3)}</text>
          </svg>
        </div>
      )}
      {result != null && (
        <p className={ui.note}>
          Maxima of {observable} after the transient.{" "}
          {doubling != null
            ? `More than one maximum first at ${parameter} ≈ ${fmt(doubling, 4)} (dashed line).`
            : "One maximum (or an equilibrium) throughout."}
          {truncated ? " The sweep hit the time limit, so it stops early." : ""}
        </p>
      )}
    </div>
  );
}
