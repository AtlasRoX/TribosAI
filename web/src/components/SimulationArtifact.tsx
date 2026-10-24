"use client";

import React from "react";
import { Activity, Download } from "lucide-react";
import { Card, Disclosure, ExtLink, Pill, Section, Stats, arr, fmt, isNum, str, styles as ui } from "./agentic/ui";
import { changeText, checkSteadyState, largestChange } from "@/lib/simulationMath";
import styles from "./SimulationArtifact.module.css";

interface SimulationArtifactProps {
  data?: Record<string, any> | null;
  scan?: Record<string, any> | null;
}

const PNG_PREFIX = /^data:image\/png;base64,[A-Za-z0-9+/=\s]+$/;

function safePng(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (PNG_PREFIX.test(trimmed)) return trimmed;
  if (/^[A-Za-z0-9+/=\s]{32,}$/.test(trimmed)) return `data:image/png;base64,${trimmed.replace(/\s+/g, "")}`;
  return null;
}

function downloadName(raw: unknown): string {
  const clean = String(raw || "dynamis")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
  return `${clean || "dynamis"}-trajectory.png`;
}

/**
 * Dynamis numerical simulation card: ODE/BVP trajectories, state variables, fixed-point equilibria and Jacobian
 * eigenvalues, optimization results, and parameter sweeps.
 */
export function SimulationArtifact({ data, scan }: SimulationArtifactProps) {
  if (!data && !scan) return null;

  const modelId = str(data?.model_id ?? data?.system ?? data?.name);
  const modelUrl =
    modelId && /^BIOMD\d{10}$/i.test(modelId) ? `https://www.ebi.ac.uk/biomodels/${modelId.toUpperCase()}` : null;
  const backend = str(data?.backend ?? data?.method) || "SciPy";
  const duration = isNum(data?.duration)
    ? data.duration
    : Array.isArray(data?.time_span) && data.time_span.length === 2 && isNum(data.time_span[1]) && isNum(data.time_span[0])
      ? data.time_span[1] - data.time_span[0]
      : null;
  const steps = isNum(data?.steps) ? data.steps : isNum(data?.n_points) ? data.n_points : null;
  const status = str(data?.steady_state_status ?? data?.status);
  const plot = safePng(data?.plot_base64 ?? data?.figure_base64);
  const scanPlot = safePng(scan?.plot_base64 ?? scan?.figure_base64);

  const initials =
    data?.initial_concentrations && typeof data.initial_concentrations === "object"
      ? (data.initial_concentrations as Record<string, any>)
      : data?.initial_state && typeof data.initial_state === "object"
        ? (data.initial_state as Record<string, any>)
        : {};
  const finals =
    data?.final_concentrations && typeof data.final_concentrations === "object"
      ? (data.final_concentrations as Record<string, any>)
      : data?.final_state && typeof data.final_state === "object"
        ? (data.final_state as Record<string, any>)
        : {};
  const steady =
    data?.steady_state && typeof data.steady_state === "object"
      ? (data.steady_state as Record<string, any>)
      : data?.equilibrium && typeof data.equilibrium === "object"
        ? (data.equilibrium as Record<string, any>)
        : {};
  const overrides =
    data?.parameter_overrides && typeof data.parameter_overrides === "object"
      ? (data.parameter_overrides as Record<string, any>)
      : data?.parameters && typeof data.parameters === "object"
        ? (data.parameters as Record<string, any>)
        : {};

  const speciesList = arr<string>(data?.species_tracked ?? data?.state_variables ?? data?.variables).filter(Boolean);
  const species = speciesList.length
    ? speciesList
    : Array.from(new Set([...Object.keys(initials), ...Object.keys(finals), ...Object.keys(steady)]));
  const hasSteady = species.some((sp) => isNum(steady[sp]));

  const equilibria = arr<Record<string, any>>(data?.equilibria ?? data?.fixed_points);
  const eigenvalues = arr<any>(data?.eigenvalues ?? data?.jacobian_eigenvalues);
  const optimization = data?.optimization && typeof data.optimization === "object" ? (data.optimization as Record<string, any>) : null;

  const ssCheck = hasSteady ? checkSteadyState(species, finals, steady, initials) : null;
  const ssReached = ssCheck?.status === "reached";
  const ssUnknown = ssCheck?.status === "unknown";
  const largest = largestChange(species, initials, finals);

  const overrideKeys = Object.keys(overrides);
  const scanRows = arr<Record<string, any>>(scan?.results);
  const scanParam = str(scan?.parameter);
  const scanSpecies = species.filter((sp) => scanRows.some((r) => isNum(r?.final?.[sp])));

  if (
    !species.length &&
    !plot &&
    !scanPlot &&
    !scanRows.length &&
    !overrideKeys.length &&
    !equilibria.length &&
    !eigenvalues.length &&
    !optimization
  ) {
    return null;
  }

  const metaParts: React.ReactNode[] = [];
  if (modelId) {
    metaParts.push(
      modelUrl ? (
        <ExtLink key="model" href={modelUrl}>
          {modelId}
        </ExtLink>
      ) : (
        modelId
      )
    );
  }
  metaParts.push(backend);
  if (duration !== null) metaParts.push(`${fmt(duration)} s${steps !== null ? ` · ${steps} steps` : ""}`);
  const meta = metaParts.reduce<React.ReactNode[]>((acc, part, i) => (i === 0 ? [part] : [...acc, " · ", part]), []);

  return (
    <Card
      icon={<Activity className={styles.icon} style={{ width: 16, height: 16 }} />}
      title="Numerical simulation & dynamical analysis"
      meta={meta}
      label="Numerical simulation and dynamical analysis"
      collapsible
      actions={
        <>
          {data?.stability ? (
            <Pill tone={String(data.stability).toLowerCase().includes("unstable") ? "warn" : "ok"}>
              {str(data.stability)}
            </Pill>
          ) : null}
          {status ? (
            <Pill tone={status.toLowerCase().includes("found") || status.toLowerCase() === "ok" ? "ok" : "neutral"}>
              {status}
            </Pill>
          ) : null}
          {plot ? (
            <a href={plot} download={downloadName(modelId)} className={ui.btn}>
              <Download style={{ width: 12, height: 12 }} aria-hidden="true" />
              Save plot
            </a>
          ) : null}
        </>
      }
    >
      <Stats
        items={[
          { label: "State variables", value: species.length || "—" },
          ...(duration !== null
            ? [
                {
                  label: "Integration window",
                  value: `${fmt(duration)} s`,
                  sub: steps !== null ? `(${steps} steps)` : undefined,
                },
              ]
            : []),
          ...(ssCheck
            ? [
                {
                  label: "Equilibrium",
                  value: ssReached ? "Reached" : ssUnknown ? "Incomplete" : "Not reached",
                  sub: ssReached
                    ? `at ${fmt(duration)} s`
                    : ssUnknown
                      ? `(${ssCheck.unmatched.length} missing)`
                      : `(${ssCheck.notReached.length} still changing)`,
                  title: ssReached
                    ? "Every state variable is within 5% of its equilibrium value at the end of the run"
                    : ssUnknown
                      ? `Missing end or equilibrium value for: ${ssCheck.unmatched.join(", ")}`
                      : `Not yet at equilibrium: ${ssCheck.notReached.slice(0, 6).join(", ")}`,
                },
              ]
            : []),
          ...(largest
            ? [
                {
                  label: "Largest change",
                  value: largest.species,
                  sub: `(${changeText(initials[largest.species], finals[largest.species], largest.floor)})`,
                  title: "Ranked by change relative to start, with a floor of 0.1% of the largest state magnitude",
                },
              ]
            : []),
        ]}
      />

      {plot && (
        <Section title="Trajectory" meta={duration !== null ? `0–${fmt(duration)} s` : undefined}>
          {/* eslint-disable-next-line @next/next/no-img-element -- data: URL from the solver */}
          <img
            src={plot}
            alt={`Trajectory for ${modelId || "dynamical system"}`}
            className={styles.plot}
          />
        </Section>
      )}

      {species.length > 0 && (
        <Section
          title="State variables"
          meta={
            <span className={styles.sectionMeta}>
              {ssCheck && (
                <Pill tone={ssReached ? "ok" : "warn"}>
                  {ssReached ? "At equilibrium" : ssUnknown ? "Equilibrium incomplete" : "Still changing"}
                </Pill>
              )}
              <span>{species.length} tracked</span>
            </span>
          }
          caveat={
            ssCheck && !ssReached
              ? ssUnknown
                ? `End or equilibrium values were not reported for ${ssCheck.unmatched.slice(0, 4).join(", ")}${ssCheck.unmatched.length > 4 ? ` and ${ssCheck.unmatched.length - 4} more` : ""}, so convergence could not be checked across all variables.`
                : `${ssCheck.notReached.slice(0, 4).join(", ")}${ssCheck.notReached.length > 4 ? ` and ${ssCheck.notReached.length - 4} more` : ""} had not reached the solver's equilibrium by ${fmt(duration)} s.`
              : undefined
          }
        >
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Variable</th>
                  <th scope="col" className={ui.num}>Initial</th>
                  <th scope="col" className={ui.num}>Final{duration !== null ? ` (${fmt(duration)} s)` : ""}</th>
                  {hasSteady && <th scope="col" className={ui.num}>Equilibrium</th>}
                  <th scope="col" className={ui.num}>Change</th>
                </tr>
              </thead>
              <tbody>
                {species.map((sp) => {
                  const s = initials[sp];
                  const e = finals[sp];
                  const ss = steady[sp];
                  return (
                    <tr key={sp}>
                      <td>
                        <span className={styles.species} title={sp}>
                          {sp}
                        </span>
                      </td>
                      <td className={ui.num}>{fmt(s, 4)}</td>
                      <td className={ui.num}>{fmt(e, 4)}</td>
                      {hasSteady && <td className={`${ui.num} ${styles.muted}`}>{fmt(ss, 4)}</td>}
                      <td className={ui.num}>{changeText(s, e, largest?.floor)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {(equilibria.length > 0 || eigenvalues.length > 0) && (
        <Section
          title="Equilibrium & stability analysis"
          meta={eigenvalues.length > 0 ? `${eigenvalues.length} eigenvalue${eigenvalues.length === 1 ? "" : "s"}` : undefined}
        >
          {eigenvalues.length > 0 && (
            <p className={ui.note}>
              Jacobian eigenvalues: <code>{eigenvalues.map((ev) => str(ev)).join(", ")}</code>
            </p>
          )}
          {equilibria.length > 0 && (
            <div className={ui.tableScroll}>
              <table className={ui.table}>
                <thead>
                  <tr>
                    <th scope="col">Fixed point</th>
                    <th scope="col">Stability</th>
                    <th scope="col">Eigenvalues</th>
                  </tr>
                </thead>
                <tbody>
                  {equilibria.map((eq, i) => (
                    <tr key={i}>
                      <td><code>{str(eq.point ?? eq.state ?? eq.coordinates ?? eq)}</code></td>
                      <td>{str(eq.stability ?? eq.classification ?? "—")}</td>
                      <td><code>{Array.isArray(eq.eigenvalues) ? eq.eigenvalues.map(str).join(", ") : str(eq.eigenvalues ?? "—")}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {optimization && (
        <Section title="Optimization / curve fit" meta={str(optimization.method || "") || undefined}>
          <Stats
            items={[
              ...(optimization.optimal_value !== undefined ? [{ label: "Objective value", value: fmt(optimization.optimal_value, 5) }] : []),
              ...(optimization.converged !== undefined ? [{ label: "Converged", value: optimization.converged ? "Yes" : "No" }] : []),
              ...(optimization.iterations !== undefined ? [{ label: "Iterations", value: fmt(optimization.iterations, 0) }] : []),
            ]}
          />
        </Section>
      )}

      {overrideKeys.length > 0 && (
        <Section
          title="Parameters"
          meta={`${overrideKeys.length} set`}
          caveat="Model parameter values applied for this simulation run."
        >
          <ul className={styles.overrides}>
            {overrideKeys.map((name) => {
              const entry = overrides[name];
              const isObj = entry && typeof entry === "object";
              return (
                <li key={name} className={styles.override}>
                  <span className={styles.name}>{name}</span>
                  <span className={styles.values}>
                    {isObj && "old" in entry ? (
                      <>
                        {fmt(entry?.old, 4)} → <strong>{fmt(entry?.new, 4)}</strong>
                      </>
                    ) : (
                      <strong>{fmt(entry, 4)}</strong>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {(scanPlot || scanRows.length > 0) && (
        <Section
          title={scanParam ? `Parameter sweep: ${scanParam}` : "Parameter sweep"}
          meta={scanRows.length ? `${scanRows.length} values` : undefined}
        >
          {scanPlot && (
            /* eslint-disable-next-line @next/next/no-img-element -- data: URL from the solver */
            <img
              src={scanPlot}
              alt={`Parameter sweep over ${scanParam || "parameter"}`}
              className={styles.plot}
            />
          )}
          {scanRows.length > 0 && (
            <Disclosure summary={`Sweep table (${scanRows.length} rows)`} defaultOpen={!scanPlot}>
              <div className={ui.tableScroll}>
                <table className={ui.table}>
                  <thead>
                    <tr>
                      <th scope="col">{scanParam || "Value"}</th>
                      {scanSpecies.map((sp) => (
                        <th key={sp} scope="col" className={ui.num}>
                          {sp}
                        </th>
                      ))}
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanRows.map((row, idx) => (
                      <tr key={idx}>
                        <td className={ui.num}>{fmt(row?.value, 4)}</td>
                        {scanSpecies.map((sp) => (
                          <td key={sp} className={ui.num}>
                            {fmt(row?.final?.[sp], 4)}
                          </td>
                        ))}
                        <td className={row?.status === "ok" ? styles.muted : styles.failed}>{str(row?.status) || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Disclosure>
          )}
        </Section>
      )}
    </Card>
  );
}
