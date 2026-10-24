"use client";

import React from "react";
import { Atom } from "lucide-react";
import { Card, ExtLink, Pill, Section, Stats, arr, fmt, isNum, str, styles as ui } from "./agentic/ui";

export interface ReferenceDataArtifactProps {
  data?: Record<string, any> | null;
}

/**
 * Physis reference data card: NIST CODATA 2022 physical constants, Pint unit conversions and dimensional analysis,
 * OEIS integer sequences, and Materials Project material properties.
 */
export function ReferenceDataArtifact({ data }: ReferenceDataArtifactProps) {
  if (!data || typeof data !== "object") return null;

  const constants = arr<Record<string, any>>(
    data.constants ?? (data.constant ? [data.constant] : data.codata ? [data.codata] : [])
  );
  const conversions = arr<Record<string, any>>(
    data.conversions ?? data.dimensions ?? (data.conversion ? [data.conversion] : [])
  );
  const sequences = arr<Record<string, any>>(
    data.sequences ?? data.oeis ?? (data.sequence ? [data.sequence] : [])
  );
  const materials = arr<Record<string, any>>(
    data.materials ?? (data.material ? [data.material] : [])
  );

  // Also support a flat single-record payload from physis_constant / physis_convert / physis_oeis / physis_material
  if (!constants.length && (data.codata_key || (data.value !== undefined && data.unit && data.uncertainty !== undefined))) {
    constants.push(data);
  }
  if (!conversions.length && (data.from_unit || data.to_unit || data.dimensionality || data.dimensionally_consistent !== undefined)) {
    conversions.push(data);
  }
  if (!sequences.length && (data.oeis_id || /^A\d{6}$/i.test(str(data.id)))) {
    sequences.push(data);
  }
  if (!materials.length && (data.mp_id || /^mp-\d+$/i.test(str(data.id ?? data.material_id)))) {
    materials.push(data);
  }

  if (!constants.length && !conversions.length && !sequences.length && !materials.length) return null;

  const metaParts: string[] = [];
  if (constants.length) metaParts.push(`${constants.length} CODATA constant${constants.length === 1 ? "" : "s"}`);
  if (conversions.length) metaParts.push(`${conversions.length} dimensional check${conversions.length === 1 ? "" : "s"}`);
  if (sequences.length) metaParts.push(`${sequences.length} OEIS sequence${sequences.length === 1 ? "" : "s"}`);
  if (materials.length) metaParts.push(`${materials.length} material${materials.length === 1 ? "" : "s"}`);

  return (
    <Card
      icon={<Atom style={{ width: 16, height: 16, color: "#2dd4bf" }} />}
      title="Physical constants, units & reference data (Physis)"
      meta={metaParts.join(" · ") || "CODATA 2022 · Pint · OEIS"}
      label="Physical constants, units and reference data"
      collapsible
    >
      <Stats
        items={[
          ...(constants.length ? [{ label: "CODATA 2022 constants", value: constants.length }] : []),
          ...(conversions.length ? [{ label: "Unit / dimension checks", value: conversions.length }] : []),
          ...(sequences.length ? [{ label: "OEIS sequences", value: sequences.length }] : []),
          ...(materials.length ? [{ label: "Materials", value: materials.length }] : []),
        ]}
      />

      {constants.length > 0 && (
        <Section title="NIST CODATA 2022 physical constants" meta={`${constants.length} retrieved`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Quantity</th>
                  <th scope="col" className={ui.num}>Value</th>
                  <th scope="col">Unit</th>
                  <th scope="col" className={ui.num}>Uncertainty</th>
                </tr>
              </thead>
              <tbody>
                {constants.map((c, idx) => (
                  <tr key={str(c.name ?? c.key ?? idx)}>
                    <td>{str(c.name ?? c.key ?? c.symbol ?? "Constant")}</td>
                    <td className={ui.num}>
                      <code>{isNum(c.value) ? c.value.toExponential(6) : str(c.value ?? "—")}</code>
                    </td>
                    <td><code>{str(c.unit ?? "—")}</code></td>
                    <td className={ui.num}>
                      {c.uncertainty === 0
                        ? "exact"
                        : isNum(c.uncertainty)
                          ? c.uncertainty.toExponential(2)
                          : str(c.uncertainty ?? "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {conversions.length > 0 && (
        <Section title="Unit conversion & dimensional analysis (Pint)">
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Input</th>
                  <th scope="col">Converted / SI base</th>
                  <th scope="col">Dimensionality</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {conversions.map((conv, idx) => {
                  const consistent = conv.dimensionally_consistent ?? conv.consistent ?? conv.valid;
                  return (
                    <tr key={idx}>
                      <td><code>{str(conv.input ?? conv.expression ?? conv.from ?? "—")}</code></td>
                      <td>
                        <code>
                          {conv.converted !== undefined
                            ? `${fmt(conv.converted, 6)} ${str(conv.to_unit ?? conv.unit ?? "")}`.trim()
                            : str(conv.result ?? conv.si_form ?? "—")}
                        </code>
                      </td>
                      <td><code>{str(conv.dimensionality ?? conv.dimensions ?? "—")}</code></td>
                      <td>
                        <Pill tone={consistent === false ? "bad" : "ok"}>
                          {consistent === false ? "Mismatch" : "Consistent"}
                        </Pill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {sequences.length > 0 && (
        <Section title="OEIS integer sequences" meta={`${sequences.length} matched`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">A-number</th>
                  <th scope="col">Name</th>
                  <th scope="col">Initial terms</th>
                </tr>
              </thead>
              <tbody>
                {sequences.map((seq, idx) => {
                  const id = str(seq.id ?? seq.oeis_id ?? seq.number).toUpperCase();
                  const href = /^A\d{6}$/.test(id) ? `https://oeis.org/${id}` : null;
                  const terms = Array.isArray(seq.terms ?? seq.data)
                    ? (seq.terms ?? seq.data).slice(0, 10).join(", ")
                    : str(seq.terms ?? seq.data ?? "—");
                  return (
                    <tr key={id || idx}>
                      <td>{href ? <ExtLink href={href}>{id}</ExtLink> : id || "—"}</td>
                      <td>{str(seq.name ?? seq.title ?? "—")}</td>
                      <td><code>{terms}</code></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {materials.length > 0 && (
        <Section title="Materials Project properties" meta={`${materials.length} entry`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Formula</th>
                  <th scope="col">Crystal system</th>
                  <th scope="col" className={ui.num}>Band gap (eV)</th>
                  <th scope="col" className={ui.num}>Formation energy (eV/atom)</th>
                </tr>
              </thead>
              <tbody>
                {materials.map((mat, idx) => {
                  const id = str(mat.material_id ?? mat.mp_id ?? mat.id).toLowerCase();
                  const href = /^mp-\d+$/.test(id) ? `https://next-gen.materialsproject.org/materials/${id}` : null;
                  return (
                    <tr key={id || idx}>
                      <td>{href ? <ExtLink href={href}>{id}</ExtLink> : id || "—"}</td>
                      <td><strong>{str(mat.formula_pretty ?? mat.formula ?? "—")}</strong></td>
                      <td>{str(mat.crystal_system ?? mat.symmetry?.crystal_system ?? "—")}</td>
                      <td className={ui.num}>{fmt(mat.band_gap, 3)}</td>
                      <td className={ui.num}>{fmt(mat.formation_energy_per_atom, 3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </Card>
  );
}
