"use client";

import React, { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, RotateCcw, ShieldCheck } from "lucide-react";
import { emitUi } from "@/lib/uiEvents";
import { UNITS_KEY, inUnits, rerunDefaults, rerunQuestion, type RerunValues } from "@/lib/oscillatorForms";
import { Card, Disclosure, Pill, Section, arr, isNum, str, styles as ui } from "./agentic/ui";
import styles from "./OdeVerificationArtifact.module.css";

/** Readable names of the computed parameters, in report order. */
const PARAMETER_LABEL: Record<string, string> = {
  natural_frequency: "Natural frequency ωₙ",
  damping_ratio: "Damping ratio ζ",
  regime: "Regime",
  damped_frequency: "Damped frequency ω_d",
  decay_rate: "Decay rate σ",
  time_constant: "Time constant τ",
  forcing_amplitude: "Forcing amplitude F₀",
  forcing_frequency: "Forcing frequency ω",
  frequency_ratio: "Frequency ratio r",
  static_deflection: "Static deflection F₀/k",
  steady_state_amplitude: "Steady-state amplitude X",
  dynamic_amplification: "Dynamic amplification X/(F₀/k)",
  phase_lag: "Phase lag φ",
  mean_steady_power: "Mean steady-state power",
};

function useUnitSystem(): ["si" | "us", (s: "si" | "us") => void] {
  const [system, setSystem] = useState<"si" | "us">("si");
  useEffect(() => {
    try {
      if (window.localStorage.getItem(UNITS_KEY) === "us") setSystem("us");
    } catch {
      // SI by default
    }
  }, []);
  const choose = (next: "si" | "us") => {
    setSystem(next);
    try {
      window.localStorage.setItem(UNITS_KEY, next);
    } catch {
      // the choice holds for this page
    }
  };
  return [system, choose];
}

const RERUN_FIELDS: [keyof RerunValues, string, string][] = [
  ["m", "m", "kg"],
  ["c", "c", "N·s/m"],
  ["k", "k", "N/m"],
  ["F0", "F₀", "N"],
  ["w", "ω", "rad/s"],
  ["x0", "x(0)", "m"],
  ["v0", "x′(0)", "m/s"],
  ["T", "Window", "s"],
];

function RerunForm({ defaults, onClose }: { defaults: RerunValues; onClose: () => void }) {
  const [values, setValues] = useState(defaults);
  const valid = Object.values(values).every((v) => v.trim() !== "" && Number.isFinite(Number(v))) && Number(values.m) > 0 && Number(values.T) > 0;
  return (
    <form
      className={styles.rerun}
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        emitUi("tribos:ask", { text: rerunQuestion(values) });
        onClose();
      }}
    >
      <div className={styles.rerunGrid}>
        {RERUN_FIELDS.map(([key, label, unit]) => (
          <label key={key} className={styles.rerunField}>
            <span>
              {label} <span className={styles.alt}>{unit}</span>
            </span>
            <input
              inputMode="decimal"
              value={values[key]}
              onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
              aria-invalid={!Number.isFinite(Number(values[key])) || values[key].trim() === ""}
            />
          </label>
        ))}
      </div>
      <div className={styles.rerunActions}>
        <span className={styles.alt}>The question goes to the composer for you to review and send.</span>
        <button type="button" className={styles.btnGhost} onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className={styles.btn} disabled={!valid}>
          Draft the question
        </button>
      </div>
    </form>
  );
}

/** Six significant figures for tables of computed values; scientific notation for very small or large ones. */
function sig(v: unknown, digits = 6): string {
  if (!isNum(v)) return typeof v === "string" && v ? v : "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a < 1e-4 || a >= 1e6) return v.toExponential(2);
  return Number(v.toPrecision(digits)).toString();
}

/** A computed initial value: floating-point noise around zero (6.7e-16) reads as 0. */
function initialValue(v: unknown): string {
  return isNum(v) && Math.abs(v) < 1e-12 ? "0" : sig(v);
}

const GREEK: [RegExp, string][] = [
  [/\bomega_n\b/g, "ωₙ"],
  [/\bomega_d\b/g, "ω_d"],
  [/\bomega\b/g, "ω"],
  [/\bzeta\b/g, "ζ"],
  [/\bsigma\b/g, "σ"],
  [/\btau\b/g, "τ"],
  [/\bphi\b/g, "φ"],
  [/\bF0\b/g, "F₀"],
  [/\^2\b/g, "²"],
  [/\bsqrt\b/g, "√"],
];

/** The report's plain-text formula with Greek letters, subscripts and squares: "omega_n = sqrt(k/m)" -> "ωₙ = √(k/m)". */
function prettyFormula(text: string): string {
  return GREEK.reduce((acc, [re, to]) => acc.replace(re, to), text);
}

function sci(v: unknown): string {
  if (!isNum(v)) return "—";
  return v === 0 ? "0" : v.toExponential(2);
}

/** One check tile: a quiet frame, with pass/attention shown by the icon beside the label. */
function Check({ ok, label, children }: { ok: boolean; label: string; children: React.ReactNode }) {
  const Icon = ok ? CircleCheck : CircleAlert;
  return (
    <div className={styles.check} data-ok={ok || undefined}>
      <span className={styles.checkLabel}>
        <Icon className={styles.checkIcon} style={{ width: 12, height: 12 }} aria-label={ok ? "Passed" : "Needs attention"} />
        {label}
      </span>
      <span className={styles.checkValue}>{children}</span>
    </div>
  );
}

/**
 * The deterministic numerical check of an analytical ODE solution: the standard parameters computed from the stated
 * coefficients, the residual and initial conditions, a fixed-step RK4 step-size study against the analytical solution,
 * the energy balance, and whether the attached reproduction script ran in the sandbox.
 */
export function OdeVerificationArtifact({ data }: { data?: Record<string, any> | null }) {
  if (!data || typeof data !== "object") return null;
  return <OdeVerificationCard data={data} />;
}

function OdeVerificationCard({ data }: { data: Record<string, any> }) {
  const params = data.parameters && typeof data.parameters === "object" ? (data.parameters as Record<string, any>) : {};
  const paramRows = Object.entries(params).filter(([, p]) => p && typeof p === "object" && "value" in p);
  const ics = arr<Record<string, any>>(data.initial_conditions);
  const conv = arr<Record<string, any>>(data.convergence);
  const samples = arr<Record<string, any>>(data.samples);
  const energy = data.energy && typeof data.energy === "object" ? (data.energy as Record<string, any>) : null;
  const run = data.script_run && typeof data.script_run === "object" ? (data.script_run as Record<string, any>) : null;
  const hasV = conv.some((r) => isNum(r.max_error_v));
  const residual = isNum(data.residual_max) ? data.residual_max : null;
  const residualOk = residual !== null && residual < 1e-6;
  const icOk = ics.length > 0 && ics.every((c) => isNum(c.stated) && isNum(c.analytical) && Math.abs(c.stated - c.analytical) < 1e-9);
  const orders = conv.map((r) => r.observed_order).filter(isNum);
  const lastOrder = orders.length ? orders[orders.length - 1] : null;
  const allOk = residualOk && icOk && (lastOrder === null || Math.abs(lastOrder - 4) < 0.3);
  const span = isNum(data.t_end) ? `0–${sig(data.t_end)} s` : "";
  const [system, setSystem] = useUnitSystem();
  const [rerunOpen, setRerunOpen] = useState(false);
  const defaults = rerunDefaults(data);
  const shown = (value: unknown, unit: string) => inUnits(value, unit, system);

  return (
    <Card
      icon={<ShieldCheck style={{ width: 16, height: 16, color: "var(--nvidia-green)" }} />}
      title="Numerical verification"
      meta={["Analytical solution vs. fixed-step RK4", span].filter(Boolean).join(" · ")}
      label="Numerical verification"
      collapsible
      actions={
        <>
          <span className={styles.units} role="group" aria-label="Unit system">
            <button type="button" aria-pressed={system === "si"} onClick={() => setSystem("si")}>
              SI
            </button>
            <button type="button" aria-pressed={system === "us"} onClick={() => setSystem("us")}>
              US
            </button>
          </span>
          <Pill tone={allOk ? "ok" : "warn"} title="Residual below 1e-6, initial conditions exact, RK4 converging at order 4">
            {allOk ? "All checks pass" : "Check the details"}
          </Pill>
        </>
      }
    >
      <div className={styles.checks}>
        <Check ok={residualOk} label="ODE residual">
          {str(data.residual_symbolic) === "0" ? "0 (symbolic)" : `max |r| = ${sci(residual)}`}
        </Check>
        <Check ok={icOk} label="Initial conditions">
          {ics.map((c) => `${str(c.condition)} = ${initialValue(c.analytical)}`).join(", ") || "—"}
        </Check>
        {lastOrder !== null && (
          <Check ok={Math.abs(lastOrder - 4) < 0.3} label="RK4 observed order">
            {lastOrder.toFixed(2)} (expected 4)
          </Check>
        )}
        {energy && isNum(energy.balance_residual) && (
          <Check ok={Math.abs(energy.balance_residual) < 1e-3} label="Energy balance residual">
            {sci(energy.balance_residual)} J
          </Check>
        )}
      </div>

      {paramRows.length > 0 && (
        <Section title="Characteristic parameters" meta="computed from the stated coefficients">
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Quantity</th>
                  <th scope="col">Formula</th>
                  <th scope="col" className={ui.num}>Value</th>
                  <th scope="col">Unit</th>
                </tr>
              </thead>
              <tbody>
                {paramRows.map(([key, p]) => (
                  <tr key={key} data-value-key={`param:${key}`}>
                    <td>{PARAMETER_LABEL[key] ?? key.replace(/_/g, " ")}</td>
                    <td className={styles.formula}>{prettyFormula(str(p.formula))}</td>
                    <td className={ui.num}>
                      {sig(shown(p.value, str(p.unit))[0])}
                      {isNum(p.degrees) ? <span className={styles.alt}> ({sig(p.degrees, 5)}°)</span> : null}
                    </td>
                    <td className={styles.unit}>{shown(p.value, str(p.unit))[1] || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {conv.length > 0 && (
        <Section title="Step-size convergence" meta={str(data.method) || "RK4"}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col" className={ui.num}>Step h (s)</th>
                  <th scope="col" className={ui.num}>Steps</th>
                  <th scope="col" className={ui.num}>Max |error| in x</th>
                  {hasV && <th scope="col" className={ui.num}>Max |error| in v</th>}
                  <th scope="col" className={ui.num}>Observed order</th>
                </tr>
              </thead>
              <tbody>
                {conv.map((r, i) => (
                  <tr key={i}>
                    <td className={ui.num}>{sig(r.h)}</td>
                    <td className={ui.num}>{isNum(r.steps) ? r.steps.toLocaleString() : "—"}</td>
                    <td className={ui.num}>{sci(r.max_error_x)}</td>
                    {hasV && <td className={ui.num}>{sci(r.max_error_v)}</td>}
                    <td className={ui.num}>{isNum(r.observed_order) ? r.observed_order.toFixed(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {samples.length > 0 && (
            <Disclosure summary={`Analytical vs. numerical at ${samples.length} times`}>
              <div className={ui.tableScroll}>
                <table className={ui.table}>
                  <thead>
                    <tr>
                      <th scope="col" className={ui.num}>t (s)</th>
                      <th scope="col" className={ui.num}>Analytical</th>
                      <th scope="col" className={ui.num}>RK4</th>
                      <th scope="col" className={ui.num}>|Error|</th>
                    </tr>
                  </thead>
                  <tbody>
                    {samples.map((s, i) => (
                      <tr key={i}>
                        <td className={ui.num}>{sig(s.t)}</td>
                        <td className={ui.num}>{sig(s.analytical)}</td>
                        <td className={ui.num}>{sig(s.numerical)}</td>
                        <td className={ui.num}>{sci(s.error)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Disclosure>
          )}
        </Section>
      )}

      {energy && (
        <Section title="Energy balance" meta="E(T) − E(0) = W_in − W_damping">
          <dl className={styles.energy}>
            <div data-value-key="energy:E0">
              <dt>E(0)</dt>
              <dd>{sig(shown(energy.E0, "J")[0])} {shown(energy.E0, "J")[1]}</dd>
            </div>
            <div data-value-key="energy:ET">
              <dt>E(T)</dt>
              <dd>{sig(shown(energy.ET, "J")[0])} {shown(energy.ET, "J")[1]}</dd>
            </div>
            <div data-value-key="energy:work_in">
              <dt>Work in by forcing</dt>
              <dd>{sig(shown(energy.work_in, "J")[0])} {shown(energy.work_in, "J")[1]}</dd>
            </div>
            <div data-value-key="energy:work_damping">
              <dt>Dissipated by damping</dt>
              <dd>{sig(shown(energy.work_damping, "J")[0])} {shown(energy.work_damping, "J")[1]}</dd>
            </div>
            <div>
              <dt>Residual</dt>
              <dd>{sci(shown(energy.balance_residual, "J")[0])} {shown(energy.balance_residual, "J")[1]}</dd>
            </div>
          </dl>
        </Section>
      )}

      {defaults && (
        <Section title="Try other values" meta="restates this problem with your numbers">
          {rerunOpen ? (
            <RerunForm defaults={defaults} onClose={() => setRerunOpen(false)} />
          ) : (
            <button type="button" className={styles.btnGhost} onClick={() => setRerunOpen(true)}>
              <RotateCcw style={{ width: 12, height: 12 }} aria-hidden="true" /> Re-run with different parameters
            </button>
          )}
        </Section>
      )}

      {run && (
        <Section
          title="Reproduction"
          meta={
            <Pill tone={run.executed ? "ok" : "warn"}>{run.executed ? "Script ran in the sandbox" : "Script not run"}</Pill>
          }
        >
          {run.executed && str(run.stdout) ? (
            <Disclosure summary="Script output">
              <pre className={styles.output}>{str(run.stdout)}</pre>
            </Disclosure>
          ) : (
            <p className={ui.note}>{str(run.error) || "The script was not run."} Download it from Files to run it locally.</p>
          )}
        </Section>
      )}
    </Card>
  );
}
