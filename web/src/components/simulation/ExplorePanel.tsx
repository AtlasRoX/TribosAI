"use client";

// The Explore panel of a simulation card: re-run the model with new parameters, initial conditions and end time.
//
// Every change is debounced (250 ms) and aborts the request in flight, so dragging a slider sends one request when
// the hand stops. The original run stays drawn faintly with a Reset button; the stored message is never changed.
// Tabs: the time course, the phase portrait (with an optional vector field) and a bifurcation sweep.

import React, { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { Section, fmt, styles as ui } from "../agentic/ui";
import { useApi } from "../ApiContext";
import { TrajectoryCharts } from "../TrajectoryCharts";
import { type SimSpec, type SliderRange, createLatestRunner, exploredSpec, fromSlider, inferRange, timeCourse, toSlider } from "@/lib/simulationExplore";
import { shownError, simulate } from "@/services/simulateService";
import { BifurcationTab } from "./BifurcationTab";
import { PhasePortrait } from "./PhasePortrait";
import styles from "./Simulation.module.css";

type Tab = "time" | "phase" | "bifurcation";

function ParameterRow({ name, value, range, onValue, onRange }: {
  name: string;
  value: number;
  range: SliderRange;
  onValue: (v: number) => void;
  onRange: (r: SliderRange) => void;
}) {
  return (
    <div className={styles.paramRow}>
      <label htmlFor={`p-${name}`} className={ui.mono}>{name}</label>
      <input
        id={`p-${name}`}
        type="range"
        min={0}
        max={1000}
        value={toSlider(value, range)}
        onChange={(e) => onValue(fromSlider(Number(e.target.value), range))}
        aria-valuetext={`${name} = ${fmt(value, 4)}`}
      />
      <input type="number" className={styles.num} value={value} step="any" aria-label={`${name} value`}
        onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onValue(e.target.valueAsNumber)} />
      <span className={styles.rangeInputs}>
        <input type="number" className={styles.num} value={range.min} step="any" aria-label={`${name} slider minimum`}
          onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onRange({ ...range, min: e.target.valueAsNumber })} />
        <input type="number" className={styles.num} value={range.max} step="any" aria-label={`${name} slider maximum`}
          onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onRange({ ...range, max: e.target.valueAsNumber })} />
        <label className={styles.logToggle}>
          <input type="checkbox" checked={range.log} disabled={range.min <= 0}
            onChange={(e) => onRange({ ...range, log: e.target.checked })} /> log
        </label>
      </span>
    </div>
  );
}

export function ExplorePanel({ spec, original }: { spec: SimSpec; original: unknown }) {
  const api = useApi();
  const baseParams = useMemo(() => spec.parameters ?? {}, [spec]);
  const baseInitial = useMemo(() => spec.initial_state ?? {}, [spec]);
  const baseEnd = Array.isArray(spec.t_span) ? spec.t_span[1] : 10;
  const [params, setParams] = useState<Record<string, number>>(baseParams);
  const [ranges, setRanges] = useState<Record<string, SliderRange>>(() =>
    Object.fromEntries(Object.entries(baseParams).map(([k, v]) => [k, inferRange(v)])));
  const [initial, setInitial] = useState<Record<string, number>>(baseInitial);
  const [tEnd, setTEnd] = useState<number>(baseEnd);
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("time");
  const [dirty, setDirty] = useState(false);

  const runner = useMemo(
    () => api && createLatestRunner<SimSpec, unknown>(
      (s, signal) => simulate(api, s, 400, signal),
      {
        onStart: () => setBusy(true),
        onResult: (r) => { setResult(r); setError(null); setBusy(false); },
        onError: (e) => { const m = shownError(e); if (m) setError(m); setBusy(false); },
      },
    ),
    [api],
  );
  useEffect(() => () => runner?.cancel(), [runner]);
  const current = useMemo(() => exploredSpec(spec, params, initial, tEnd), [spec, params, initial, tEnd]);
  useEffect(() => {
    if (dirty) runner?.schedule(current);
  }, [current, runner, dirty]);

  if (!api) return null;
  const edit = <T,>(fn: (v: T) => void) => (v: T) => { setDirty(true); fn(v); };
  const reset = () => {
    runner?.cancel();
    setDirty(false);
    setParams(baseParams);
    setInitial(baseInitial);
    setTEnd(baseEnd);
    setResult(null);
    setError(null);
    setBusy(false);
  };
  const originalCourse = timeCourse(original);
  const course = timeCourse(result) ?? originalCourse;
  const states = Object.keys(spec.rhs ?? baseInitial);

  return (
    <Section title="Explore" meta={busy ? "running…" : result ? "explored run" : "original run"}>
      <div className={styles.tabs} role="tablist" aria-label="Explore views">
        {(["time", "phase", "bifurcation"] as Tab[]).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? styles.tabOn : styles.tab}
            onClick={() => setTab(t)}>
            {t === "time" ? "Time course" : t === "phase" ? "Phase portrait" : "Bifurcation"}
          </button>
        ))}
        <button type="button" className={styles.reset} onClick={reset} disabled={!dirty && !result}>
          <RotateCcw style={{ width: 12, height: 12 }} aria-hidden="true" /> Reset
        </button>
      </div>

      {tab !== "bifurcation" && (
        <div className={styles.controls}>
          {Object.entries(params).map(([k, v]) => (
            <ParameterRow key={k} name={k} value={v} range={ranges[k] ?? inferRange(v)}
              onValue={edit((x: number) => setParams((p) => ({ ...p, [k]: x })))}
              onRange={(r) => setRanges((all) => ({ ...all, [k]: r.max > r.min ? r : all[k] }))} />
          ))}
          <div className={styles.icRow}>
            {states.map((s) => (
              <label key={s} className={styles.ic}>
                <span className={ui.mono}>{s}(0)</span>
                <input type="number" className={styles.num} step="any" value={initial[s] ?? 0}
                  onChange={(e) => Number.isFinite(e.target.valueAsNumber) && edit((x: number) => setInitial((p) => ({ ...p, [s]: x })))(e.target.valueAsNumber)} />
              </label>
            ))}
            <label className={styles.ic}>
              <span className={ui.mono}>t end</span>
              <input type="number" className={styles.num} step="any" value={tEnd}
                onChange={(e) => Number.isFinite(e.target.valueAsNumber) && edit(setTEnd)(e.target.valueAsNumber)} />
            </label>
          </div>
        </div>
      )}

      {error && <p className={ui.warnNote} role="status">{error}</p>}

      {tab === "time" && course && (
        <TrajectoryCharts t={course.t} series={course.series} overlay={result ? originalCourse : null} />
      )}
      {tab === "phase" && course && (
        <PhasePortrait api={api} spec={current} course={course} original={result ? originalCourse : null} states={states} />
      )}
      {tab === "bifurcation" && <BifurcationTab api={api} spec={current} />}
      {result != null && tab === "time" && <p className={ui.note}>The dashed line is the original run.</p>}
    </Section>
  );
}

export default ExplorePanel;
