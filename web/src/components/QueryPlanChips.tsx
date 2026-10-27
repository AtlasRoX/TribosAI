"use client";

import type { QueryEntity, QueryPlanExtra, SourceDecision } from "@/types/queryPlan";
import styles from "./QueryPlanChips.module.css";

export interface QueryPlanChipsProps {
  plan: QueryPlanExtra;
}

const SOURCE_NAMES: Record<string, string> = {
  archivon: "Archivon",
  axiom: "Axiom",
  dynamis: "Dynamis",
  calcula: "Calcula",
  physis: "Physis",
  websurfer: "WebSurfer",
  arxiv: "arXiv",
  s2: "Semantic Scholar",
  semantic_scholar: "Semantic Scholar",
  openalex: "OpenAlex",
  zbmath: "zbMATH",
  crossref: "Crossref",
  ads: "NASA ADS",
  oeis: "OEIS",
  codata: "CODATA",
  materials_project: "Materials Project",
  wolfram: "Wolfram|Alpha",
  wikipedia: "Wikipedia",
};

// Decisions that only say a plugin is not installed or not relevant are routing noise, not a choice.
const HIDDEN_REASONS = new Set([
  "tool not available",
  "not applicable",
  "not a research question",
  "no simulation requested",
  "no dataset",
  "no gene named",
  "gene family is ambiguous",
]);

const LEGACY_IGNORED_KEYS = new Set(["vivarix", "lumicell", "synapta", "lithoscribe"]);

const ID_ORDER = ["wikidata_id", "arxiv_id", "doi", "oeis_id", "mp_id", "codata_key", "msc_code", "zbl_id", "mr_id"];

const MATCH_LABELS: Record<string, string> = {
  symbol: "symbol",
  alias_symbol: "alias",
  alias: "alias",
  name: "name",
  synonym: "synonym",
  formula: "formula",
  constant: "CODATA constant",
  unit: "SI unit",
  msc: "MSC class",
  oeis_hint: "OEIS sequence",
  dynamis_hint: "dynamical system",
};

const KIND_LABELS: Record<string, string> = {
  ambiguous: "Ambiguous",
  mass: "Mass",
  damping: "Damping",
  stiffness: "Stiffness",
  force: "Force",
  frequency: "Frequency",
  displacement: "Displacement",
  velocity: "Velocity",
  acceleration: "Acceleration",
  pressure: "Pressure",
  energy: "Energy",
  power: "Power",
  time: "Time",
  length: "Length",
  constant: "Constant",
  material: "Material",
  system: "System",
  equation: "Equation",
  concept: "Concept",
  quantity: "Quantity",
  gene: "Gene",
  drug: "Compound",
  disease: "Disease",
  variant: "Variant",
};

function sourceName(key: string): string {
  return SOURCE_NAMES[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function entityText(e: QueryEntity): string {
  if (e.ambiguous_with && e.ambiguous_with.length > 0) {
    return `${e.mention} → ambiguous: ${e.ambiguous_with.slice(0, 4).join(", ")}${e.ambiguous_with.length > 4 ? ", …" : ""}`;
  }
  const label = e.label || e.mention || "";
  const same = !e.mention || e.mention.toLowerCase() === label.toLowerCase();
  return same ? label : `${e.mention} → ${label}`;
}

function entityDescription(e: QueryEntity): string {
  const ids = ID_ORDER.map((k) => e.ids?.[k]).filter((v): v is string => Boolean(v));
  const parts: string[] = [`${e.type}: ${entityText(e)}`];
  if (e.unit) parts.push(`unit ${e.unit}`);
  if (e.formula) parts.push(e.formula);
  parts.push(...ids);
  const via = e.matched_on ? MATCH_LABELS[e.matched_on] ?? e.matched_on.replace(/_/g, " ") : "";
  if (e.source === "local_lexicon") parts.push("offline lexicon, not verified");
  else if (e.source === "query_text") parts.push("as written, not verified");
  else parts.push(`via ${e.source}${via ? ` ${via}` : ""}`);
  if (!e.validated && e.source !== "local_lexicon" && e.source !== "query_text") parts.push("not verified");
  return parts.join(" · ");
}

function routingLine(sources: SourceDecision[]): string {
  const filtered = sources.filter((s) => !LEGACY_IGNORED_KEYS.has(s.name.toLowerCase()));
  const run = filtered.filter((s) => s.run).map((s) => sourceName(s.name));
  const skipped = filtered
    .filter((s) => !s.run && !HIDDEN_REASONS.has(s.reason))
    .map((s) => `${sourceName(s.name)}${s.reason ? ` (${s.reason})` : ""}`);
  const parts: string[] = [];
  if (run.length) parts.push(`Will run: ${run.join(", ")}`);
  if (skipped.length) parts.push(`Skipped: ${skipped.join(", ")}`);
  return parts.join(" · ");
}

/** Resolved entities and source routing under the plan step of the thinking timeline. */
export function QueryPlanChips({ plan }: QueryPlanChipsProps) {
  const entities = Array.isArray(plan?.entities) ? plan.entities : [];
  const sources = Array.isArray(plan?.sources) ? plan.sources : [];
  const routing = routingLine(sources);
  const notes: string[] = [];
  if (plan?.planner === "llm") notes.push("Planner: model-assisted");
  if (plan?.normalization === "offline_lexicon" && entities.length > 0) notes.push("Offline: names not verified");
  else if (plan?.normalization === "partial" && entities.length > 0) notes.push("Partial: some name sources unavailable");
  if (entities.length === 0 && !routing && notes.length === 0) return null;

  return (
    <div className={styles.plan}>
      {entities.length > 0 && (
        <ul className={styles.chips} aria-label="Recognized entities">
          {entities.map((e, i) => {
            const description = entityDescription(e);
            const chipType = e.ids?.physical_type || e.type;
            return (
              <li
                key={`${e.type}-${e.mention}-${i}`}
                className={styles.chip}
                data-type={chipType}
                data-validated={e.validated ? "true" : "false"}
                title={description}
                aria-label={description}
              >
                <span className={styles.marker} aria-hidden="true" />
                <span className={styles.kind} aria-hidden="true">
                  {KIND_LABELS[chipType] ?? chipType}
                </span>
                <span className={styles.text}>{entityText(e)}</span>
              </li>
            );
          })}
        </ul>
      )}
      {(routing || notes.length > 0) && (
        <div className={styles.routing}>{[routing, ...notes].filter(Boolean).join(" · ")}</div>
      )}
    </div>
  );
}
