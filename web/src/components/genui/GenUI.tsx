"use client";

// Renders generative-UI blocks (lib/genui.ts): the "Results at a glance" panel built from code-computed results, and
// the small ```ui blocks the writer may embed in the answer. Every number shown comes from the block; nothing is
// computed here except chart geometry.

import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import katex from "katex";
import { AlertTriangle, BadgeCheck, CheckCircle2, Info, Lightbulb, LineChart as LineIcon, Table2, XCircle } from "lucide-react";
import {
  directLabelYs,
  equationLatex,
  logTicks,
  extent,
  linePath,
  nearestIndex,
  niceTicks,
  type AnswerUi,
  type CalloutBlock,
  type ChecksBlock,
  type ChartBlock,
  type EquationBlock,
  type StatsBlock,
  type StepsBlock,
  type TableBlock,
  type UiBlock,
} from "@/lib/genui";
import { formatNumber } from "@/lib/numberFormat";
import styles from "./GenUI.module.css";

const MIN_TEX_SCALE = 0.5;

/** KaTeX that never scrolls: when the formula is wider than its box, its font is scaled down (to at most half) until
 * it fits, again whenever the box is resized or the math fonts finish loading. */
function Tex({ latex, display = false }: { latex: string; display?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const html = useMemo(() => {
    try {
      return katex.renderToString(latex, { throwOnError: false, displayMode: display, trust: false, strict: "ignore" });
    } catch {
      return null;
    }
  }, [latex, display]);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.fontSize = "";
      const avail = el.clientWidth;
      const need = el.scrollWidth;
      if (avail > 0 && need > avail + 1) {
        const base = parseFloat(getComputedStyle(el).fontSize);
        el.style.fontSize = `${(base * Math.max(MIN_TEX_SCALE, (avail - 2) / need)).toFixed(2)}px`;
      }
    };
    fit();
    let live = true;
    document.fonts?.ready.then(() => live && fit()).catch(() => undefined);
    if (typeof ResizeObserver === "undefined") {
      return () => {
        live = false;
      };
    }
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      fit();
    });
    observer.observe(el);
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [html]);
  if (!html) return <code>{latex}</code>;
  return <span ref={ref} className={display ? styles.texDisplay : styles.tex} dangerouslySetInnerHTML={{ __html: html }} />;
}

const unitLabel = (label: string, unit?: string) => (unit ? `${label} (${unit})` : label);

const SUP: Record<string, string> = { "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹" };
const superscript = (k: number) => String(Math.round(k)).replace(/[-0-9]/g, (ch) => SUP[ch] ?? ch);

// Stats ------------------------------------------------------------------------------------------------------------
function Stats({ block }: { block: StatsBlock }) {
  return (
    <section className={styles.block} aria-label={block.title || "Key quantities"}>
      {block.title && <h4 className={styles.blockTitle}>{block.title}</h4>}
      <div className={styles.tiles}>
        {block.items.map((it, i) => {
          const exact = it.exact_latex && it.exact_latex !== it.value ? it.exact_latex : "";
          return (
          <div key={`${it.label}-${i}`} className={styles.tile} style={{ "--i": i } as React.CSSProperties}>
            <div className={styles.tileLabel}>
              {it.label}
              {it.verified && <BadgeCheck className={styles.seal} aria-label="computed and checked" />}
            </div>
            {exact && (
              <div className={styles.tileExact}>
                <Tex latex={exact} />
              </div>
            )}
            <div className={styles.tileValue}>
              {exact ? <span className={styles.approx}>≈</span> : null}
              {it.value}
              {it.unit && <span className={styles.tileUnit}>{it.unit}</span>}
            </div>
            {(it.secondary || it.note) && <div className={styles.tileNote}>{[it.secondary, it.note].filter(Boolean).join(" · ")}</div>}
          </div>
          );
        })}
      </div>
    </section>
  );
}

// Equation ---------------------------------------------------------------------------------------------------------
function Equation({ block }: { block: EquationBlock }) {
  const allPassed = block.checks.length > 0 && block.checks.every((c) => c.passed);
  const { latex, split } = equationLatex(block);
  return (
    <section className={`${styles.block} ${styles.equation}`} aria-label={block.title || "Equation"}>
      <div className={styles.blockHead}>
        {block.title && <h4 className={styles.blockTitle}>{block.title}</h4>}
        {allPassed && (
          <span className={styles.badgeOk}>
            <BadgeCheck aria-hidden="true" /> Checked by substitution
          </span>
        )}
      </div>
      <div className={styles.eqMain}>
        <Tex latex={latex} display />
      </div>
      {/* The parts are named inside the two-line form; listed separately only when it could not be built. */}
      {!split && block.parts.length > 0 && (
        <dl className={styles.eqParts}>
          {block.parts.map((p) => (
            <div key={p.label} className={styles.eqPart}>
              <dt>{p.label}</dt>
              <dd>
                <Tex latex={p.latex} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {block.checks.length > 0 && (
        <ul className={styles.checks} aria-label="Checks">
          {block.checks.map((c) => (
            <li key={c.name} className={c.passed ? styles.checkOk : styles.checkFail}>
              {c.passed ? <CheckCircle2 aria-hidden="true" /> : <XCircle aria-hidden="true" />}
              <span>{c.name}</span>
              <span className="sr-only">{c.passed ? "passed" : "failed"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Chart ------------------------------------------------------------------------------------------------------------
const PAD = { top: 16, right: 92, bottom: 40, left: 58 };
const HEIGHT = 280;

function useWidth(ref: React.RefObject<HTMLElement | null>, fallback = 640): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width || 0);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

function Chart({ block }: { block: ChartBlock }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const width = useWidth(wrapRef);
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const titleId = useId();
  const narrow = width < 460;
  const pad = narrow ? { ...PAD, right: 16 } : PAD;
  const innerW = Math.max(120, width - pad.left - pad.right);
  const innerH = HEIGHT - pad.top - pad.bottom;

  // Geometry runs on plotted coordinates (log10 of the value on a log axis); readouts use the block's own values.
  const xLog = block.x.scale === "log";
  const yLog = block.y.scale === "log";
  const plotted = useMemo(
    () =>
      block.series.map((s) => ({
        ...s,
        points: s.points.map((p) => [xLog ? Math.log10(p[0]) : p[0], yLog ? Math.log10(p[1]) : p[1]] as [number, number]),
      })),
    [block.series, xLog, yLog],
  );
  const [x0, x1] = extent(plotted, 0);
  const [y0, y1] = extent(plotted, 1);
  // A parametric chart (an orbit) keeps one scale on both axes, centred, so its shape is not stretched.
  const parametric = block.parametric === true;
  const unit = Math.min(innerW / (x1 - x0 || 1), innerH / (y1 - y0 || 1));
  const offX = pad.left + (innerW - (x1 - x0) * unit) / 2;
  const offY = pad.top + (innerH + (y1 - y0) * unit) / 2;
  const sx = (v: number) => (parametric ? offX + (v - x0) * unit : pad.left + ((v - x0) / (x1 - x0 || 1)) * innerW);
  const sy = (v: number) => (parametric ? offY - (v - y0) * unit : pad.top + innerH - ((v - y0) / (y1 - y0 || 1)) * innerH);
  const xTicks = xLog ? logTicks(x0, x1) : niceTicks(x0, x1, narrow ? 4 : 7);
  const yTicks = yLog ? logTicks(y0, y1, 5) : niceTicks(y0, y1, 5);
  const tickText = (v: number, log: boolean) => (log ? `10${superscript(v)}` : formatNumber(v, 3));
  const mx = (v: number) => sx(xLog ? Math.log10(v) : v);
  const my = (v: number) => sy(yLog ? Math.log10(v) : v);
  const base = plotted[0].points;
  const raw = block.series[0].points;
  const multi = block.series.length > 1;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (parametric) {
      // The sample nearest the pointer on any orbit; every body is then shown at that same instant.
      const px = pad.left + ((e.clientX - rect.left) / rect.width) * innerW;
      const py = pad.top + ((e.clientY - rect.top) / rect.height) * innerH;
      let best = 0;
      let bestD = Infinity;
      for (const s of plotted) {
        s.points.forEach((p, k) => {
          const d = (sx(p[0]) - px) ** 2 + (sy(p[1]) - py) ** 2;
          if (d < bestD) {
            bestD = d;
            best = k;
          }
        });
      }
      setHover(best);
      return;
    }
    const xv = x0 + ((e.clientX - rect.left) / rect.width) * (x1 - x0);
    setHover(nearestIndex(base, xv));
  };
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const cur = hover ?? 0;
      setHover(Math.max(0, Math.min(base.length - 1, cur + (e.key === "ArrowRight" ? step : -step))));
    } else if (e.key === "Escape") setHover(null);
  };

  const hx = hover !== null ? base[hover]?.[0] : null;
  const fmtX = (v: number) => (xLog ? v.toExponential(2) : formatNumber(v, 4));
  const fmtY = (v: number) => (yLog ? v.toExponential(2) : formatNumber(v, 5));
  const tipLeft = hx !== null && hx !== undefined ? sx(hx) : 0;
  const tableRows = useMemo(() => {
    const n = raw.length;
    const want = Math.min(n, 21);
    return Array.from({ length: want }, (_, k) => Math.round((k * (n - 1)) / Math.max(1, want - 1)));
  }, [raw]);

  return (
    <section className={styles.block} aria-labelledby={titleId}>
      <div className={styles.blockHead}>
        <h4 id={titleId} className={styles.blockTitle}>
          {block.title || "Chart"}
        </h4>
        <div className={styles.toggle} role="group" aria-label="Chart view">
          <button type="button" aria-pressed={!asTable} onClick={() => setAsTable(false)} title="Chart">
            <LineIcon aria-hidden="true" />
            <span className="sr-only">Chart</span>
          </button>
          <button type="button" aria-pressed={asTable} onClick={() => setAsTable(true)} title="Table view">
            <Table2 aria-hidden="true" />
            <span className="sr-only">Table view</span>
          </button>
        </div>
      </div>
      {multi && (
        <ul className={styles.legend} aria-label="Legend">
          {block.series.map((s, i) => (
            <li key={s.name}>
              <svg width="22" height="8" aria-hidden="true">
                <line x1="1" y1="4" x2="21" y2="4" className={styles[`s${i + 1}`]} strokeDasharray={s.style === "dashed" ? "5 4" : undefined} />
              </svg>
              {s.name}
            </li>
          ))}
        </ul>
      )}
      {asTable ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.num}>{parametric ? "sample" : unitLabel(block.x.label, block.x.unit)}</th>
                {block.series.map((s) => (
                  <th key={s.name} className={styles.num}>
                    {parametric ? `${s.name} (${block.x.label}, ${block.y.label})` : unitLabel(s.name, block.y.unit)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((k) => (
                <tr key={k}>
                  <td className={styles.num}>{parametric ? k + 1 : fmtX(raw[k][0])}</td>
                  {block.series.map((s) => (
                    <td key={s.name} className={styles.num}>
                      {!s.points[k]
                        ? ""
                        : parametric
                          ? `(${formatNumber(s.points[k][0], 5)}, ${formatNumber(s.points[k][1], 5)})`
                          : fmtY(s.points[k][1])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={wrapRef} className={styles.chartWrap}>
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-labelledby={titleId}
            className={styles.chart}
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
          >
            <g className={styles.grid} aria-hidden="true">
              {yTicks.map((t) => (
                <line key={`gy${t}`} x1={pad.left} x2={pad.left + innerW} y1={sy(t)} y2={sy(t)} />
              ))}
            </g>
            {!yLog && y0 < 0 && y1 > 0 && <line className={styles.zero} x1={pad.left} x2={pad.left + innerW} y1={sy(0)} y2={sy(0)} aria-hidden="true" />}
            <g className={styles.axis} aria-hidden="true">
              {yTicks.map((t) => (
                <text key={`ty${t}`} x={pad.left - 8} y={sy(t)} textAnchor="end" dominantBaseline="middle">
                  {tickText(t, yLog)}
                </text>
              ))}
              {xTicks.map((t) => (
                <text key={`tx${t}`} x={sx(t)} y={pad.top + innerH + 18} textAnchor="middle">
                  {tickText(t, xLog)}
                </text>
              ))}
              <text x={pad.left + innerW / 2} y={HEIGHT - 4} textAnchor="middle" className={styles.axisTitle}>
                {unitLabel(block.x.label, block.x.unit)}
              </text>
              <text
                x={14}
                y={pad.top + innerH / 2}
                textAnchor="middle"
                transform={`rotate(-90 14 ${pad.top + innerH / 2})`}
                className={styles.axisTitle}
              >
                {unitLabel(block.y.label, block.y.unit)}
              </text>
            </g>
            {plotted.map((s, i) => (
              <path
                key={s.name}
                d={linePath(s.points, sx, sy)}
                className={`${styles.line} ${styles[`s${i + 1}`]}`}
                strokeDasharray={s.style === "dashed" ? "6 5" : undefined}
                style={{ "--i": i } as React.CSSProperties}
              />
            ))}
            {/* Direct labels only when every name fits in the right margin; the legend names the series otherwise. */}
            {!narrow && !parametric && block.series.every((s) => s.name.length * 6.6 + 16 <= pad.right) &&
              directLabelYs(plotted.map((s) => sy(s.points[s.points.length - 1][1])), pad.top, pad.top + innerH).map((y, i) => {
                const s = plotted[i];
                return (
                  <text key={`dl${s.name}`} x={sx(s.points[s.points.length - 1][0]) + 8} y={y} dominantBaseline="middle" className={styles.directLabel}>
                    <tspan className={styles[`dot${i + 1}`]}>● </tspan>
                    {s.name}
                  </text>
                );
              })}
            {block.marks.map((m) => (
              <g key={`m${m.x}-${m.label ?? ""}`}>
                <circle cx={mx(m.x)} cy={my(m.y)} r={4} className={styles.mark} />
                {m.label && (
                  <text x={mx(m.x)} y={my(m.y) - 10} textAnchor="middle" className={styles.markLabel}>
                    {m.label}
                  </text>
                )}
              </g>
            ))}
            {hx !== null && hx !== undefined && (
              <g aria-hidden="true">
                {!parametric && <line className={styles.crosshair} x1={sx(hx)} x2={sx(hx)} y1={pad.top} y2={pad.top + innerH} />}
                {plotted.map((s, i) =>
                  s.points[hover!] ? (
                    <circle key={`h${s.name}`} cx={sx(s.points[hover!][0])} cy={sy(s.points[hover!][1])} r={4.5} className={`${styles.hoverDot} ${styles[`s${i + 1}`]}`} />
                  ) : null,
                )}
              </g>
            )}
            <rect
              x={pad.left}
              y={pad.top}
              width={innerW}
              height={innerH}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
          {hover !== null && base[hover] && (
            <div
              className={styles.tooltip}
              role="status"
              style={{ left: Math.min(Math.max(tipLeft, 90), width - 90), top: pad.top }}
            >
              <div className={styles.tipHead}>
                {parametric ? `sample ${hover + 1} of ${base.length}` : `${block.x.label} = ${fmtX(raw[hover][0])} ${block.x.unit}`}
              </div>
              {block.series.map((s, i) =>
                s.points[hover] ? (
                  <div key={s.name} className={styles.tipRow}>
                    <span className={`${styles.swatch} ${styles[`bg${i + 1}`]}`} aria-hidden="true" />
                    <span>{s.name}</span>
                    <span className={styles.tipValue}>
                      {parametric
                        ? `(${formatNumber(s.points[hover][0], 4)}, ${formatNumber(s.points[hover][1], 4)})`
                        : `${fmtY(s.points[hover][1])} ${block.y.unit}`}
                    </span>
                  </div>
                ) : null,
              )}
            </div>
          )}
          <p className="sr-only">
            {block.series.map((s) => `${s.name}: ${s.points.length} points`).join("; ")}. Use the arrow keys to read values, or switch to
            the table view.
          </p>
        </div>
      )}
    </section>
  );
}

// Table ------------------------------------------------------------------------------------------------------------
function Table({ block }: { block: TableBlock }) {
  return (
    <section className={styles.block} aria-label={block.title || "Table"}>
      {block.title && <h4 className={styles.blockTitle}>{block.title}</h4>}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {block.columns.map((c) => (
                <th key={c.key} className={c.align === "right" ? styles.num : undefined}>
                  {unitLabel(c.label, c.unit)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r, i) => (
              <tr key={i}>
                {block.columns.map((c) => (
                  <td key={c.key} className={c.align === "right" ? styles.num : undefined}>
                    {r[c.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.caption && <p className={styles.caption}>{block.caption}</p>}
    </section>
  );
}

// Checks -----------------------------------------------------------------------------------------------------------
function Checks({ block }: { block: ChecksBlock }) {
  const passed = block.items.filter((c) => c.passed).length;
  return (
    <section className={styles.block} aria-label={block.title || "Checks"}>
      <div className={styles.blockHead}>
        {block.title && <h4 className={styles.blockTitle}>{block.title}</h4>}
        <span className={passed === block.items.length ? styles.badgeOk : styles.badgeWarn}>
          {passed === block.items.length ? <BadgeCheck aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
          {passed} of {block.items.length} passed
        </span>
      </div>
      <ul className={styles.checkList}>
        {block.items.map((c) => (
          <li key={c.name} className={c.passed ? styles.checkOk : styles.checkFail}>
            {c.passed ? <CheckCircle2 aria-hidden="true" /> : <XCircle aria-hidden="true" />}
            <span className={styles.checkName}>{c.name}</span>
            {c.detail && <span className={styles.checkDetail}>{c.detail.includes("\\") ? <Tex latex={c.detail} /> : c.detail}</span>}
            <span className="sr-only">{c.passed ? "passed" : "failed"}</span>
          </li>
        ))}
      </ul>
      {block.caption && <p className={styles.caption}>{block.caption}</p>}
    </section>
  );
}

// Callout & steps --------------------------------------------------------------------------------------------------
const TONE_ICON = { info: Info, insight: Lightbulb, warning: AlertTriangle, ok: CheckCircle2 } as const;

function Callout({ block }: { block: CalloutBlock }) {
  const Icon = TONE_ICON[block.tone];
  return (
    <aside className={`${styles.callout} ${styles[`tone_${block.tone}`]}`} role="note">
      <Icon aria-hidden="true" className={styles.calloutIcon} />
      <div>
        {block.title && <div className={styles.calloutTitle}>{block.title}</div>}
        <div className={styles.calloutText}>{block.text}</div>
      </div>
    </aside>
  );
}

function Steps({ block }: { block: StepsBlock }) {
  return (
    <section className={styles.block} aria-label={block.title || "Steps"}>
      {block.title && <h4 className={styles.blockTitle}>{block.title}</h4>}
      <ol className={styles.steps}>
        {block.items.map((it, i) => (
          <li key={i} style={{ "--i": i } as React.CSSProperties}>
            {it.title && <div className={styles.stepTitle}>{it.title}</div>}
            {it.latex && <Tex latex={it.latex} display />}
            {it.note && <div className={styles.stepNote}>{it.note}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function UiBlockView({ block }: { block: UiBlock }) {
  switch (block.type) {
    case "stats":
      return <Stats block={block} />;
    case "equation":
      return <Equation block={block} />;
    case "chart":
      return <Chart block={block} />;
    case "table":
      return <Table block={block} />;
    case "callout":
      return <Callout block={block} />;
    case "steps":
      return <Steps block={block} />;
    case "checks":
      return <Checks block={block} />;
  }
}

/** The "Results at a glance" panel above the answer. */
export function AnswerUiPanel({ ui, animate = true }: { ui: AnswerUi; animate?: boolean }) {
  const [open, setOpen] = useState(true);
  const bodyId = useId();
  return (
    <section className={`${styles.panel}${animate ? "" : ` ${styles.still}`}`} aria-label={ui.title}>
      <header className={styles.panelHead}>
        <button type="button" className={styles.panelToggle} aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((o) => !o)}>
          <span className={styles.panelTitle}>{ui.title}</span>
          {ui.source === "computed" && <span className={styles.panelSource}>computed by code · checked</span>}
          <span className={styles.chevron} aria-hidden="true" data-open={open} />
        </button>
      </header>
      {open && (
        <div id={bodyId} className={styles.panelBody}>
          {ui.blocks.map((b, i) => (
            <div key={i} className={styles.reveal} style={{ "--i": i } as React.CSSProperties}>
              <UiBlockView block={b} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** A writer's inline ```ui block inside the answer. */
export function InlineUiBlock({ block }: { block: UiBlock }) {
  return (
    <div className={styles.inline}>
      <UiBlockView block={block} />
    </div>
  );
}
