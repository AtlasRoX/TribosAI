"use client";

// A solved partial differential equation: the field over time, and the checks that say whether it can be trusted.
//
// 1D fields draw as a line against x with a time slider (the initial state stays as a faint reference); 2D fields
// draw as a heatmap on the domain with a legend. The colours are the theme's --heatmap-* ramp, so the map follows
// the light and dark palettes. The axes and the colour scale cover every snapshot, so they stay fixed while the
// slider moves. Below: the badges (mesh convergence, analytic agreement, conservation, stability), the
// convergence table and the probes. The data shaping lives in pdeData.ts.

import React, { useId, useMemo, useState } from "react";
import { Waves } from "lucide-react";
import { Card, Disclosure, Pill, Section, Stats, fmt, isNum, styles } from "../agentic/ui";
import {
  type Frame1D,
  type Frame2D,
  type PdeData,
  allValues1D,
  allValues2D,
  boundarySummary,
  convergenceRows,
  equationName,
  frames1D,
  frames2D,
  heatRuns,
  pdeBadges,
  rampColours,
  valueRange,
} from "./pdeData";

const W = 340;
const H = 170;
const M = { l: 40, r: 10, t: 10, b: 24 };
const STEPS = 24;

function LinePlot({ xs, frame, initial, lo, hi }: { xs: number[]; frame: Frame1D; initial: Frame1D | null; lo: number; hi: number }) {
  const x0 = xs[0];
  const x1 = xs[xs.length - 1];
  const px = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const py = (v: number) => H - M.b - ((v - lo) / (hi - lo || 1)) * (H - M.b - M.t);
  const path = (values: number[]) =>
    values
      .map((v, i) => (Number.isFinite(v) ? `${i === 0 ? "M" : "L"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}` : ""))
      .join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`The field u(x) at t = ${fmt(frame.t, 4)}`}>
      <line className={styles.axis} x1={M.l} y1={H - M.b} x2={W - M.r} y2={H - M.b} />
      <line className={styles.axis} x1={M.l} y1={M.t} x2={M.l} y2={H - M.b} />
      {lo < 0 && hi > 0 && <line className={styles.axis} x1={M.l} y1={py(0)} x2={W - M.r} y2={py(0)} strokeDasharray="3 3" />}
      {initial && initial !== frame && <path className={styles.seriesSim} d={path(initial.values)} opacity={0.25} />}
      <path className={styles.seriesSim} d={path(frame.values)} />
      <text className={styles.axisText} x={M.l} y={H - 8}>{fmt(x0, 3)}</text>
      <text className={styles.axisText} x={(M.l + W - M.r) / 2} y={H - 8} textAnchor="middle">x</text>
      <text className={styles.axisText} x={W - M.r} y={H - 8} textAnchor="end">{fmt(x1, 3)}</text>
      <text className={styles.axisText} x={M.l - 4} y={M.t + 6} textAnchor="end">{fmt(hi, 3)}</text>
      <text className={styles.axisText} x={M.l - 4} y={H - M.b} textAnchor="end">{fmt(lo, 3)}</text>
    </svg>
  );
}

function Heatmap({ xs, ys, frame, lo, hi }: { xs: number[]; ys: number[]; frame: Frame2D; lo: number; hi: number }) {
  const colours = useMemo(() => rampColours(STEPS), []);
  const runs = useMemo(() => heatRuns(frame.rows, lo, hi, STEPS), [frame, lo, hi]);
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const plotW = W - M.l - M.r;
  const plotH = H - M.b - M.t;
  const cw = plotW / xs.length;
  const ch = plotH / ys.length;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - box.left) / box.width) * W;
    const sy = ((e.clientY - box.top) / box.height) * H;
    const i = Math.floor((sx - M.l) / cw);
    const j = Math.floor((H - M.b - sy) / ch);
    setHover(i >= 0 && i < xs.length && j >= 0 && j < ys.length ? { i, j } : null);
  };
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`Heatmap of u(x, y) at t = ${fmt(frame.t, 4)}, from ${fmt(lo, 3)} to ${fmt(hi, 3)}`}
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {runs.map((r) => (
        <rect
          key={`${r.yj}-${r.xi}`}
          x={M.l + r.xi * cw}
          y={H - M.b - (r.yj + 1) * ch}
          width={r.span * cw + 0.4}
          height={ch + 0.4}
          style={{ fill: colours[r.level] }}
        />
      ))}
      <rect x={M.l} y={M.t} width={plotW} height={plotH} fill="none" className={styles.axis} />
      {hover && (
        <rect x={M.l + hover.i * cw} y={H - M.b - (hover.j + 1) * ch} width={cw} height={ch} fill="none" stroke="currentColor" />
      )}
      <text className={styles.axisText} x={M.l} y={H - 8}>{fmt(xs[0], 3)}</text>
      <text className={styles.axisText} x={(M.l + W - M.r) / 2} y={H - 8} textAnchor="middle">
        {hover ? `x ${fmt(xs[hover.i], 3)}, y ${fmt(ys[hover.j], 3)}: u = ${fmt(frame.rows[hover.i]?.[hover.j], 4)}` : "x"}
      </text>
      <text className={styles.axisText} x={W - M.r} y={H - 8} textAnchor="end">{fmt(xs[xs.length - 1], 3)}</text>
      <text className={styles.axisText} x={M.l - 4} y={M.t + 6} textAnchor="end">{fmt(ys[ys.length - 1], 3)}</text>
      <text className={styles.axisText} x={M.l - 4} y={H - M.b} textAnchor="end">{fmt(ys[0], 3)}</text>
      <text className={styles.axisText} x={M.l - 4} y={(M.t + H - M.b) / 2} textAnchor="end">y</text>
    </svg>
  );
}

function Legend({ lo, hi }: { lo: number; hi: number }) {
  const id = `pde-ramp-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox={`0 0 ${W} 26`} role="img" aria-label={`Colour scale from ${fmt(lo, 3)} to ${fmt(hi, 3)}`}>
      <defs>
        <linearGradient id={id}>
          {[0, 1, 2, 3, 4, 5].map((k) => (
            <stop key={k} offset={`${k * 20}%`} style={{ stopColor: `var(--heatmap-${k})` }} />
          ))}
        </linearGradient>
      </defs>
      <rect x={M.l} y={2} width={W - M.l - M.r} height={8} rx={2} fill={`url(#${id})`} />
      <text className={styles.axisText} x={M.l} y={22}>{fmt(lo, 3)}</text>
      <text className={styles.axisText} x={W - M.r} y={22} textAnchor="end">{fmt(hi, 3)}</text>
    </svg>
  );
}

export function PdeArtifact({ data }: { data: unknown }) {
  const d = useMemo(() => (data && typeof data === "object" ? data : {}) as PdeData, [data]);
  const is2d = d.dimension === 2;
  const xs = Array.isArray(d.x) ? d.x : [];
  const ys = Array.isArray(d.y) ? d.y : [];
  const f1 = useMemo(() => (is2d ? [] : frames1D(d)), [d, is2d]);
  const f2 = useMemo(() => (is2d ? frames2D(d) : []), [d, is2d]);
  const count = is2d ? f2.length : f1.length;
  const [index, setIndex] = useState<number | null>(null);
  const range = useMemo(() => (is2d ? valueRange(allValues2D(f2)) : valueRange(allValues1D(f1))), [is2d, f1, f2]);
  if (!count) return null;

  const at = Math.min(index ?? count - 1, count - 1);
  const frame = is2d ? f2[at] : f1[at];
  const badges = pdeBadges(d);
  const rows = convergenceRows(d);
  const c = d.convergence;
  const warnings = (Array.isArray(d.warnings) ? d.warnings : []).filter((w) => typeof w === "string" && w);
  const probes = Array.isArray(d.probes) ? d.probes : [];
  const parameters = Object.entries(d.parameters ?? {}).filter(([, v]) => isNum(v));
  const errorLabel = c?.reference === "analytic solution" ? "Error vs analytic" : "Change to finer grid";

  return (
    <Card
      icon={<Waves style={{ width: 15, height: 15 }} />}
      title={`${equationName(d.equation)} · ${is2d ? "2D" : "1D"}`}
      meta={
        <>
          {d.stability?.scheme || d.method || "finite differences"}
          {boundarySummary(d.boundary) ? ` · ${boundarySummary(d.boundary)}` : ""}
        </>
      }
      label="Solved partial differential equation"
      collapsible
    >
      <Section title="Checks">
        <div className={styles.chips}>
          {badges.map((b) => (
            <Pill key={b.text} tone={b.tone} title={b.title}>
              {b.text}
            </Pill>
          ))}
        </div>
      </Section>

      <Section
        title={d.steady ? "Steady field" : "Field"}
        meta={!d.steady && frame.t != null ? `t = ${fmt(frame.t, 4)}` : undefined}
      >
        <div className={styles.plainChart}>
          {is2d ? (
            <>
              <Heatmap xs={xs} ys={ys} frame={frame as Frame2D} lo={range.lo} hi={range.hi} />
              <Legend lo={range.lo} hi={range.hi} />
            </>
          ) : (
            <LinePlot xs={xs} frame={frame as Frame1D} initial={f1[0] ?? null} lo={range.lo} hi={range.hi} />
          )}
        </div>
        {count > 1 && (
          <div className={styles.sliderRow}>
            <label htmlFor="pde-time">Snapshot {at + 1} of {count}</label>
            <input
              id="pde-time"
              type="range"
              min={0}
              max={count - 1}
              step={1}
              value={at}
              onChange={(e) => setIndex(Number(e.target.value))}
              aria-valuetext={`t = ${fmt(frame.t, 4)}`}
            />
            <span className={styles.mono}>{fmt(frame.t, 3)}</span>
          </div>
        )}
        {!is2d && count > 1 && <p className={styles.note}>The faint line is the initial state.</p>}
      </Section>

      {rows.length > 0 && (
        <Section title="Mesh convergence" meta={c?.reference ? `against the ${c.reference}` : undefined}>
          <Stats
            items={[
              { label: "Observed order", value: isNum(c?.order) ? fmt(c.order, 3) : "—", sub: isNum(c?.expected_order) ? `scheme: ${c.expected_order}` : undefined },
              { label: "Richardson error", value: isNum(c?.richardson_error) ? fmt(c.richardson_error, 3) : "—" },
              { label: "Relative", value: isNum(c?.relative_error) ? fmt(c.relative_error, 2) : "—" },
            ]}
          />
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col" className={styles.num}>Points</th>
                  <th scope="col" className={styles.num}>h</th>
                  <th scope="col" className={styles.num}>{errorLabel}</th>
                  <th scope="col" className={styles.num}>Order</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className={styles.num}>{r.n ?? "—"}</td>
                    <td className={styles.num}>{r.h != null ? fmt(r.h, 3) : "—"}</td>
                    <td className={styles.num}>{r.error != null ? fmt(r.error, 3) : "—"}</td>
                    <td className={styles.num}>{r.order != null ? fmt(r.order, 3) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {c?.note && <p className={styles.note}>{c.note}</p>}
        </Section>
      )}

      {probes.length > 0 && (
        <Section title="Probes">
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Point</th>
                  <th scope="col" className={styles.num}>At t = {fmt(frame.t, 3)}</th>
                  <th scope="col" className={styles.num}>Final</th>
                </tr>
              </thead>
              <tbody>
                {probes.map((p, i) => (
                  <tr key={i}>
                    <td className={styles.mono}>
                      {fmt(p.x, 3)}
                      {isNum(p.y) ? `, ${fmt(p.y, 3)}` : ""}
                    </td>
                    <td className={styles.num}>{fmt(p.values?.[at], 4)}</td>
                    <td className={styles.num}>{fmt(p.values?.[(p.values?.length ?? 1) - 1], 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {warnings.length > 0 && (
        <Section title="Warnings">
          {warnings.map((w) => (
            <p key={w} className={styles.warnNote}>{w}</p>
          ))}
        </Section>
      )}

      <Disclosure summary="Problem and how to read the checks">
        {parameters.length > 0 && (
          <p className={styles.note} style={{ marginTop: 0 }}>
            Parameters: {parameters.map(([k, v]) => `${k} = ${fmt(v, 4)}`).join(", ")}.
          </p>
        )}
        <p className={styles.note}>
          The convergence study solves the same problem on nested grids, each halving the spacing. The observed order
          is how fast the error falls (2 means four times smaller per halving); the Richardson error estimates the
          error left on the shown grid. Without an analytic solution the error is the change to the next finer grid,
          so &quot;converged&quot; means the grid no longer changes the answer, not that the model is right. The
          stability number is the scheme&apos;s Courant or diffusion number for the step used.
        </p>
      </Disclosure>
    </Card>
  );
}

export default PdeArtifact;
