"use client";

import React from "react";
import { Lightbulb } from "lucide-react";
import type { Hypothesis, HypothesesArtifact as HypothesesData } from "@/types/agentic";
import { evidenceDisplayNames } from "./evidenceLabels";
import { Card, ChipList, Disclosure, Pill, Section, arr, fmt, isNum, str, styles } from "./ui";

/** Readable evidence names ("synlethdb" -> "SynLethDB"): evidence_labels when the backend sends them. */
function hypothesisEvidence(h: Hypothesis & { evidence_labels?: string[] }): string[] {
  return evidenceDisplayNames(h.evidence_keys, h.evidence_labels);
}

function intervention(h: Hypothesis): string {
  const iv = h.intervention;
  if (!iv || typeof iv !== "object") return "";
  return [str(iv.kind), iv.parameter ? str(iv.parameter) : "", isNum(iv.factor) ? `×${fmt(iv.factor, 3)}` : ""].filter(Boolean).join(" ");
}

function prediction(h: Hypothesis): string {
  if (!h.prediction) return "";
  const arrow = h.prediction === "increase" ? "↑" : h.prediction === "decrease" ? "↓" : "";
  return [h.readout, arrow, h.prediction].filter(Boolean).join(" ");
}

function tested(h: Hypothesis): boolean {
  const r = h.result;
  return Boolean(r && typeof r === "object" && (isNum(r.relative_change) || isNum(r.log2_fold_change) || r.supports != null));
}

/** "≥ 5 %" for the support threshold (the server's threshold_relative_change), or "" when it did not send one. */
function thresholdText(threshold: number | null | undefined): string {
  return isNum(threshold) ? `≥ ${fmt(threshold * 100, 1)} %` : "";
}

/** "+12.5 %" for a relative change. */
function percent(change: number): string {
  return `${change > 0 ? "+" : ""}${fmt(change * 100, 1)} %`;
}

/** The in-silico verdict; untested hypotheses get no chip (the card meta says whether anything was tested). */
function SupportBadge({ h, threshold }: { h: Hypothesis; threshold?: number | null }) {
  if (!tested(h)) return null;
  const r = h.result!;
  const t = thresholdText(threshold);
  if (r.supports === true)
    return (
      <Pill tone="ok" title={`Effect in the predicted direction${t ? ` with a relative change ${t}` : ""}`}>
        supported
      </Pill>
    );
  if (r.supports === false) return <Pill tone="bad" title="Effect absent or opposite to the prediction">not supported</Pill>;
  return <Pill tone="neutral">inconclusive</Pill>;
}

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function HypothesisItem({ h, rank, threshold }: { h: Hypothesis; rank: number; threshold?: number | null }) {
  const iv = intervention(h);
  const pred = prediction(h);
  const evidence = hypothesisEvidence(h);
  const keys = arr<string>(h.evidence_keys);
  const lfc = h.result?.log2_fold_change;
  const rel = h.result?.relative_change;
  const metric = h.result?.metric;
  const values = `baseline ${fmt(h.result?.baseline)} → perturbed ${fmt(h.result?.perturbed)}`;
  return (
    <li className={`${styles.divItem} ${styles.hypItem}`}>
      <span className={styles.hypRank}>{rank}</span>
      <div style={{ minWidth: 0 }}>
        <span className={styles.itemHead}>{h.statement || "(no statement)"}</span>
        {h.mechanism && <span className={styles.itemSub}>{h.mechanism}</span>}
        <div className={styles.itemMeta}>
          <SupportBadge h={h} threshold={threshold} />
          {iv && (
            <span>
              intervention <span className={styles.mono}>{iv}</span>
            </span>
          )}
          {pred && <span>predicts {pred}</span>}
          {isNum(rel) && (
            <span title={`Relative change of the readout${metric ? ` (${metric})` : ""}, perturbed vs baseline: ${values}`}>
              {metric ? `${metric} ` : ""}
              {percent(rel)}
            </span>
          )}
          {isNum(lfc) && (
            <span title={`log2 fold-change of the readout, perturbed vs baseline: ${values}`}>log2FC {fmt(lfc, 2)}</span>
          )}
          {isNum(h.elo) && <span title="Elo rating from the pairwise tournament">Elo {Math.round(h.elo)}</span>}
        </div>
        {evidence.length > 0 && (
          <div className={styles.itemMeta} title={keys.join(", ")}>
            <ChipList items={evidence.map((name) => ({ key: name, label: name }))} limit={4} />
          </div>
        )}
      </div>
    </li>
  );
}

/** Ranked hypotheses (AI co-scientist Elo tournament) with any in-silico perturbation results. */
export function HypothesesArtifact({ data }: { data: HypothesesData }) {
  if (!data || typeof data !== "object") return null;
  const items = arr<Hypothesis>(data.hypotheses)
    .filter((h) => h && typeof h === "object")
    .slice()
    .sort((a, b) => (isNum(a.rank) ? a.rank : 1e9) - (isNum(b.rank) ? b.rank : 1e9) || (b.elo ?? 0) - (a.elo ?? 0));
  const experiments = isNum(data.experiments_run) ? data.experiments_run : 0;
  const testedItems = items.filter(tested);
  const supported = testedItems.filter((h) => h.result?.supports === true).length;
  const top = items[0]?.statement;
  const method = data.method === "elo-tournament" ? "Elo tournament" : data.method || "";

  const meta = [
    `${items.length} hypothes${items.length === 1 ? "is" : "es"}`,
    top ? `top: ${clip(top, 90)}` : "",
    testedItems.length ? `${supported} of ${testedItems.length} supported in silico` : data.model_id ? "none tested in silico" : "no simulation model",
  ]
    .filter(Boolean)
    .join(" · ");

  const about = [
    data.target ? `Target ${data.target}.` : "",
    method ? `Ranked by ${method}.` : "",
    data.model_id ? `Simulation model ${data.model_id}; ${experiments} in-silico experiment${experiments === 1 ? "" : "s"} run.` : "No simulation model was available.",
    data.model_id
      ? `Supported means the simulated effect had the predicted direction${
          thresholdText(data.threshold_relative_change) ? ` with a relative change ${thresholdText(data.threshold_relative_change)}` : ""
        }. In-silico results are model predictions, not experimental evidence.`
      : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Card
      icon={<Lightbulb style={{ width: 15, height: 15 }} />}
      title={`Ranked hypotheses${data.target ? ` · ${data.target}` : ""}`}
      meta={meta}
      label="Ranked hypotheses"
      collapsible
      defaultOpen={false}
    >
      {items.length === 0 ? (
        <p className={styles.muted}>No hypotheses were generated.</p>
      ) : (
        <Section title="Ranked" meta={method || undefined}>
          <ol className={styles.divList}>
            {items.map((h, i) => (
              <HypothesisItem key={h.id || i} h={h} rank={isNum(h.rank) ? h.rank : i + 1} threshold={data.threshold_relative_change} />
            ))}
          </ol>
        </Section>
      )}
      {data.note ? (
        <p className={styles.note}>{data.note}</p>
      ) : (
        !data.model_id &&
        items.length > 0 && <p className={styles.note}>Ranked from the literature and target evidence only; none was tested in silico.</p>
      )}
      <Disclosure summary="How these are ranked and tested">
        <p className={styles.note} style={{ marginTop: 0 }}>
          {about}
        </p>
      </Disclosure>
    </Card>
  );
}
