"use client";

// Engineering calculations of a turn (tribos/engcalc): for each one the cited reference, the inputs as used (with
// where each came from), the results in readable units, a utilisation bar per limit state, the validity checks of the
// method and the warnings. Formulas and assumptions sit in a disclosure. The data shaping lives in engcalcData.ts.

import React from "react";
import { Calculator } from "lucide-react";
import { Bar, Card, Disclosure, Pill, Section, styles } from "../agentic/ui";
import {
  type EngCalculation,
  calculations,
  citation,
  shownInput,
  shownResult,
  sig,
  utilisationTone,
} from "./engcalcData";

function CalculationBody({ c }: { c: EngCalculation }) {
  const results = c.results ?? [];
  const inputs = c.inputs ?? [];
  const checks = (c.checks ?? []).filter((k) => typeof k?.utilisation === "number");
  const validity = c.validity ?? [];
  const warnings = (c.warnings ?? []).filter((w) => typeof w === "string" && w);
  return (
    <>
      <p className={styles.note} style={{ marginTop: 0 }}>
        Following {citation(c) || "the cited method"}
        {c.material?.name ? ` · material: ${c.material.name}` : ""}
      </p>

      <Section title="Results">
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <tbody>
              {results.map((r, i) => {
                const s = shownResult(r);
                return (
                  <tr key={r.name ?? i}>
                    <td>{r.label ?? r.name}</td>
                    <td className={styles.num}>
                      {s.uncertainty ?? `${s.value} ${s.unit}`.trim()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {checks.length > 0 && (
        <Section
          title="Utilisation"
          meta={c.utilisation?.governing ? `governing: ${c.utilisation.governing}` : undefined}
          hint="Demand over capacity, including the required safety factor; 1 is the limit"
        >
          {checks.map((k, i) => (
            <Bar
              key={k.name ?? i}
              label={k.name ?? "check"}
              value={k.utilisation as number}
              max={1}
              tone={utilisationTone(k.utilisation, k.ok)}
              display={sig(k.utilisation as number, 3)}
              title={k.detail}
            />
          ))}
        </Section>
      )}

      {(validity.length > 0 || warnings.length > 0) && (
        <Section title="Validity and warnings">
          {validity.length > 0 && (
            <div className={styles.chips}>
              {validity.map((v, i) => (
                <Pill key={v.name ?? i} tone={v.ok ? "ok" : "warn"} title={v.detail}>
                  {v.ok ? "✓" : "!"} {v.name}
                </Pill>
              ))}
            </div>
          )}
          {warnings.map((w) => (
            <p key={w} className={styles.warnNote}>{w}</p>
          ))}
        </Section>
      )}

      <Disclosure summary={`Inputs (${inputs.length}), formulas and assumptions`}>
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Input</th>
                <th scope="col" className={styles.num}>Value</th>
                <th scope="col">From</th>
              </tr>
            </thead>
            <tbody>
              {inputs.map((i, k) => (
                <tr key={i.name ?? k}>
                  <td className={styles.mono}>{i.name}</td>
                  <td className={styles.num}>{shownInput(i)}</td>
                  <td>{i.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(c.formulas ?? []).length > 0 && (
          <ul className={styles.list}>
            {(c.formulas ?? []).map((f) => (
              <li key={f} className={styles.mono}>{f}</li>
            ))}
          </ul>
        )}
        {[...(c.assumptions ?? []), ...(c.notes ?? [])].map((a) => (
          <p key={a} className={styles.note}>{a}</p>
        ))}
      </Disclosure>
    </>
  );
}

export function EngineeringCalcArtifact({ data }: { data: unknown }) {
  const list = calculations(data);
  if (!list.length) return null;
  return (
    <>
      {list.map((c, i) => {
        const u = c.utilisation;
        const tone = utilisationTone(u?.value, u?.ok);
        return (
          <Card
            key={`${c.calculator}-${i}`}
            icon={<Calculator style={{ width: 15, height: 15 }} />}
            title={c.title ?? c.calculator ?? "Engineering calculation"}
            meta={
              u && typeof u.value === "number" ? (
                <Pill tone={tone}>
                  {tone === "bad" ? "fails" : tone === "warn" ? "close to limit" : "passes"} · utilisation {sig(u.value, 3)}
                </Pill>
              ) : (
                "no limit state checked"
              )
            }
            label="Engineering calculation"
            collapsible
          >
            <CalculationBody c={c} />
          </Card>
        );
      })}
    </>
  );
}

export default EngineeringCalcArtifact;
