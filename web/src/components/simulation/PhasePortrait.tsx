"use client";

// The phase portrait of two state variables: the explored trajectory (the original run faint underneath), the start
// point, and on request the vector field (dx/dt, dy/dt) on a grid over the plotted window.

import React, { useEffect, useMemo, useState } from "react";
import { fmt, styles as ui } from "../agentic/ui";
import { type SimSpec, arrows, phasePath } from "@/lib/simulationExplore";
import { type SimulateApi, shownError, vectorField } from "@/services/simulateService";
import styles from "./Simulation.module.css";

const W = 320;
const H = 240;
const M = 30;

export function PhasePortrait({ api, spec, course, original, states }: {
  api: SimulateApi;
  spec: SimSpec;
  course: { series: Record<string, number[]> };
  original: { series: Record<string, number[]> } | null;
  states: string[];
}) {
  const [xv, setX] = useState(states[0] ?? "");
  const [yv, setY] = useState(states[1] ?? states[0] ?? "");
  const [showField, setShowField] = useState(false);
  const [field, setField] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const path = useMemo(() => phasePath(course, xv, yv), [course, xv, yv]);
  const ref = useMemo(() => (original ? phasePath(original, xv, yv) : []), [original, xv, yv]);
  const box = useMemo(() => {
    const all = [...path, ...ref];
    if (!all.length) return null;
    const xs = all.map((p) => p[0]);
    const ys = all.map((p) => p[1]);
    const pad = (lo: number, hi: number): [number, number] => {
      const d = (hi - lo) * 0.08 || 1;
      return [lo - d, hi + d];
    };
    return { x: pad(Math.min(...xs), Math.max(...xs)), y: pad(Math.min(...ys), Math.max(...ys)) };
  }, [path, ref]);

  useEffect(() => {
    if (!showField || !box || xv === yv) return;
    const controller = new AbortController();
    vectorField(api, { spec, x_var: xv, y_var: yv, x_range: box.x, y_range: box.y, n: 15 }, controller.signal).then(
      (f) => {
        setField(f);
        setError(null);
      },
      (e) => {
        const m = shownError(e);
        if (m) setError(m);
      },
    );
    return () => controller.abort();
  }, [api, spec, xv, yv, box, showField]);

  if (states.length < 2) return <p className={ui.note}>A phase portrait needs at least two state variables.</p>;
  if (!box) return null;
  const sx = (v: number) => M + ((v - box.x[0]) / (box.x[1] - box.x[0])) * (W - 2 * M);
  const sy = (v: number) => H - M - ((v - box.y[0]) / (box.y[1] - box.y[0])) * (H - 2 * M);
  const d = (pts: [number, number][]) => pts.map(([a, b], i) => `${i ? "L" : "M"}${sx(a).toFixed(1)},${sy(b).toFixed(1)}`).join("");
  return (
    <div>
      <div className={styles.icRow}>
        <label className={styles.ic}>
          x
          <select value={xv} onChange={(e) => setX(e.target.value)}>
            {states.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className={styles.ic}>
          y
          <select value={yv} onChange={(e) => setY(e.target.value)}>
            {states.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className={styles.logToggle}>
          <input type="checkbox" checked={showField} onChange={(e) => setShowField(e.target.checked)} /> vector field
        </label>
      </div>
      {error && <p className={ui.warnNote}>{error}</p>}
      <div className={ui.plainChart}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Phase portrait of ${yv} against ${xv}`}>
          <rect x={M} y={M} width={W - 2 * M} height={H - 2 * M} fill="none" className={ui.axis} />
          {showField &&
            arrows(field).map(([x, y, dx, dy], i) => (
              <line key={i} x1={sx(x)} y1={sy(y)} x2={sx(x + dx)} y2={sy(y + dy)} className={styles.arrow} />
            ))}
          {ref.length > 1 && <path d={d(ref)} className={ui.seriesSim} opacity={0.25} strokeDasharray="4 3" />}
          {path.length > 1 && <path d={d(path)} className={ui.seriesSim} />}
          {path[0] && <circle cx={sx(path[0][0])} cy={sy(path[0][1])} r={3} className={styles.start} />}
          <text className={ui.axisText} x={W / 2} y={H - 8} textAnchor="middle">{xv}</text>
          <text className={ui.axisText} x={10} y={H / 2} textAnchor="middle" transform={`rotate(-90 10 ${H / 2})`}>{yv}</text>
          <text className={ui.axisText} x={M} y={H - 18}>{fmt(box.x[0], 3)}</text>
          <text className={ui.axisText} x={W - M} y={H - 18} textAnchor="end">{fmt(box.x[1], 3)}</text>
          <text className={ui.axisText} x={M - 3} y={M + 8} textAnchor="end">{fmt(box.y[1], 3)}</text>
          <text className={ui.axisText} x={M - 3} y={H - M} textAnchor="end">{fmt(box.y[0], 3)}</text>
        </svg>
      </div>
    </div>
  );
}
