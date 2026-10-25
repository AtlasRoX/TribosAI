"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Disclosure, fmt, styles as ui } from "./agentic/ui";
import styles from "./TrajectoryCharts.module.css";
import { pathIndices } from "@/lib/decimate";

interface TrajectoryChartsProps {
  /** Sample times, ascending. */
  t: number[];
  /** One series per state variable, sampled at `t`. */
  series: Record<string, number[]>;
  /** Unit of `t` for the axis and tooltip. */
  timeUnit?: string;
  /** Unit per series when the run states one (from the question's own values), e.g. {x: "m", v: "m/s"}. */
  units?: Record<string, string>;
}

const HEIGHT = 132;
const PAD = { top: 10, right: 12, bottom: 22, left: 48 };
const MAX_PATH_POINTS = 600; // the path is drawn from at most this many samples; the crosshair uses them all
const TABLE_ROWS = 41;

/** Round tick values covering [lo, hi] (the outer ticks bound the data): about `count` steps of 1, 2, 2.5 or 5 x 10^n. */
function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) return [lo];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  const end = Math.ceil(hi / step - 1e-9) * step;
  for (let v = Math.floor(lo / step + 1e-9) * step; v <= end + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}

function tickText(v: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1000 || a < 0.01) return v.toExponential(1).replace("e+", "e");
  return String(Number(v.toPrecision(3)));
}

/** Index of the sample nearest to time `x` (t ascending). */
function nearestIndex(t: number[], x: number): number {
  let lo = 0;
  let hi = t.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (t[mid] < x) lo = mid;
    else hi = mid;
  }
  return Math.abs(t[lo] - x) <= Math.abs(t[hi] - x) ? lo : hi;
}

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** The SVG with its computed colours and fonts written inline, so it looks the same outside the page. */
function standaloneSvg(svg: SVGSVGElement, title: string): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const source = svg.querySelectorAll("*");
  const target = clone.querySelectorAll("*");
  const props = ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline"];
  source.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const out = target[i] as SVGElement;
    for (const prop of props) out.style.setProperty(prop, cs.getPropertyValue(prop));
  });
  clone.querySelectorAll("rect").forEach((r) => {
    if (r.getAttribute("class")?.includes("hit")) r.remove(); // the invisible pointer target
  });
  const bg = getComputedStyle(svg.closest("figure") || svg).backgroundColor;
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("width", "100%");
  rect.setAttribute("height", "100%");
  rect.setAttribute("fill", bg && bg !== "rgba(0, 0, 0, 0)" ? bg : "#ffffff");
  clone.insertBefore(rect, clone.firstChild);
  const label = document.createElementNS("http://www.w3.org/2000/svg", "title");
  label.textContent = title;
  clone.insertBefore(label, clone.firstChild);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  return new XMLSerializer().serializeToString(clone);
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportChart(svg: SVGSVGElement | null, name: string, kind: "svg" | "png") {
  if (!svg) return;
  const markup = standaloneSvg(svg, `${name} over time`);
  const file = `trajectory-${name.replace(/[^A-Za-z0-9_-]+/g, "_")}`;
  if (kind === "svg") return saveBlob(new Blob([markup], { type: "image/svg+xml" }), `${file}.svg`);
  const img = new Image();
  const scale = 2;
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = svg.clientWidth * scale;
    canvas.height = svg.clientHeight * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    canvas.toBlob((b) => b && saveBlob(b, `${file}.png`), "image/png");
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(markup);
}

function Chart({
  name,
  t,
  y,
  timeUnit,
  unit,
  hover,
  setHover,
}: {
  name: string;
  t: number[];
  y: number[];
  timeUnit: string;
  unit?: string;
  /** The sample under the crosshair, shared by every chart of the run so x and v are read at the same time. */
  hover: number | null;
  setHover: React.Dispatch<React.SetStateAction<number | null>>;
}) {
  const [ref, width] = useWidth();
  const svgRef = useRef<SVGSVGElement>(null);
  const t0 = t[0];
  const t1 = t[t.length - 1];
  const finite = y.filter(Number.isFinite);
  const yMin = Math.min(...finite);
  const yMax = Math.max(...finite);
  // An outer tick bounds the axis only when it adds at most 15% of the data range ("0.5" over 0.49, not "4" over 2.05);
  // otherwise the axis hugs the data with a small margin and keeps the inner ticks.
  const yTicks = useMemo(() => {
    const ticks = niceTicks(yMin, yMax);
    const slack = 0.15 * (yMax - yMin || Math.abs(yMax) || 1);
    return ticks.filter((v) => v >= yMin - slack && v <= yMax + slack);
  }, [yMin, yMax]);
  const margin = 0.04 * (yMax - yMin || Math.abs(yMax) || 1);
  const lo = Math.min(yMin - margin, yTicks[0] ?? yMin);
  const hi = Math.max(yMax + margin, yTicks[yTicks.length - 1] ?? yMax);
  const xTicks = useMemo(() => niceTicks(t0, t1, 5), [t0, t1]);

  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const sx = useCallback((v: number) => PAD.left + ((v - t0) / (t1 - t0 || 1)) * plotW, [t0, t1, plotW]);
  const sy = useCallback((v: number) => PAD.top + (1 - (v - lo) / (hi - lo || 1)) * plotH, [lo, hi, plotH]);

  const path = useMemo(() => {
    if (!plotW) return "";
    let d = "";
    for (const i of pathIndices(y, MAX_PATH_POINTS)) {
      d += `${d ? "L" : "M"}${sx(t[i]).toFixed(1)},${sy(y[i]).toFixed(1)}`;
    }
    return d;
  }, [t, y, sx, sy, plotW]);

  const onPointer = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = t0 + ((e.clientX - box.left) / (box.width || 1)) * (t1 - t0);
    setHover(nearestIndex(t, x));
  };
  const onKey = (e: React.KeyboardEvent) => {
    const step = Math.max(1, Math.round(t.length / 50));
    const at = hover ?? 0;
    const next = { ArrowRight: at + step, ArrowLeft: at - step, Home: 0, End: t.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    setHover(Math.min(t.length - 1, Math.max(0, next)));
  };

  const hx = hover !== null ? sx(t[hover]) : 0;
  const hy = hover !== null ? sy(y[hover]) : 0;
  const tipLeft = hover !== null && hx > width - 130;

  return (
    <figure className={styles.chart}>
      <figcaption className={styles.title}>
        <span className={styles.key} aria-hidden="true" />
        {name}
        {unit ? ` (${unit})` : ""}
        <span className={styles.range}>
          {tickText(yMin)} to {tickText(yMax)}{unit ? ` ${unit}` : ""} · sampled
        </span>
        <span className={styles.exports}>
          <button type="button" onClick={() => exportChart(svgRef.current, name, "svg")} title={`Save the ${name} chart as SVG`}>
            SVG
          </button>
          <button type="button" onClick={() => exportChart(svgRef.current, name, "png")} title={`Save the ${name} chart as PNG`}>
            PNG
          </button>
        </span>
      </figcaption>
      <div
        ref={ref}
        className={styles.plotWrap}
        tabIndex={0}
        role="img"
        aria-label={`${name} over time from ${tickText(t0)} to ${tickText(t1)} ${timeUnit}, between ${tickText(yMin)} and ${tickText(yMax)}. Use the arrow keys to read values.`}
        onKeyDown={onKey}
        onFocus={() => setHover((h) => h ?? 0)}
        onBlur={() => setHover(null)}
      >
        {width > 0 && (
          <svg ref={svgRef} width={width} height={HEIGHT} className={styles.svg} aria-hidden="true">
            {yTicks.map((v) => (
              <g key={`y${v}`}>
                <line x1={PAD.left} x2={width - PAD.right} y1={sy(v)} y2={sy(v)} className={v === 0 ? styles.zero : styles.grid} />
                <text x={PAD.left - 6} y={sy(v)} className={styles.tickY}>
                  {tickText(v)}
                </text>
              </g>
            ))}
            {xTicks.map((v) => (
              <text key={`x${v}`} x={sx(v)} y={HEIGHT - 6} className={styles.tickX}>
                {tickText(v)}
              </text>
            ))}
            <path d={path} className={styles.line} />
            {hover !== null && (
              <g>
                <line x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + plotH} className={styles.crosshair} />
                <circle cx={hx} cy={hy} r={4} className={styles.marker} />
              </g>
            )}
            <rect
              x={PAD.left}
              y={PAD.top}
              width={plotW}
              height={plotH}
              className={styles.hit}
              onPointerMove={onPointer}
              onPointerDown={onPointer}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
        )}
        {hover !== null && (
          <div className={styles.tooltip} style={{ left: tipLeft ? hx - 8 : hx + 8, top: PAD.top, transform: tipLeft ? "translateX(-100%)" : undefined }}>
            <div>
              t = <strong>{fmt(t[hover], 4)}</strong> {timeUnit}
            </div>
            <div>
              {name} = <strong>{fmt(y[hover], 5)}</strong>{unit ? ` ${unit}` : ""}
            </div>
          </div>
        )}
      </div>
    </figure>
  );
}

/**
 * Simulated trajectories as small multiples: one line chart per state variable, each on its own y-axis (state
 * variables carry different units, so they never share an axis). A crosshair snaps to the nearest sample, arrow keys
 * read values from the keyboard, and the sampled values are available as a table.
 */
export function TrajectoryCharts({ t, series, timeUnit = "s", units = {} }: TrajectoryChartsProps) {
  const [hover, setHover] = useState<number | null>(null);
  const names = Object.keys(series).filter((k) => Array.isArray(series[k]) && series[k].length === t.length);
  if (t.length < 2 || !names.length) return null;
  const stride = Math.max(1, Math.ceil(t.length / (TABLE_ROWS - 1)));
  const rows = t.map((_, i) => i).filter((i) => i % stride === 0 || i === t.length - 1);
  return (
    <div className={styles.root}>
      <div className={styles.grid2}>
        {names.map((n) => (
          <Chart key={n} name={n} t={t} y={series[n]} timeUnit={timeUnit} unit={units[n]} hover={hover} setHover={setHover} />
        ))}
      </div>
      <Disclosure summary={`Data table (${rows.length} of ${t.length} samples)`}>
        <div className={ui.tableScroll}>
          <table className={ui.table}>
            <thead>
              <tr>
                <th scope="col" className={ui.num}>t ({timeUnit})</th>
                {names.map((n) => (
                  <th key={n} scope="col" className={ui.num}>{n}{units[n] ? ` (${units[n]})` : ""}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i}>
                  <td className={ui.num}>{fmt(t[i], 4)}</td>
                  {names.map((n) => (
                    <td key={n} className={ui.num}>{fmt(series[n][i], 5)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </div>
  );
}
