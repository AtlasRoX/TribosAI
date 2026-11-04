"use client";

import React from "react";
import { Sigma } from "lucide-react";
import type { MathAgentArtifact as MathData, MathAgentStep, MathCheck } from "@/types/agentic";
import { MarkdownRenderer } from "../MarkdownRenderer";
import { Card, CopyButton, Disclosure, Pill, Section, arr, str, styles, type Tone } from "./ui";

const STATUS: Record<string, { label: string; tone: Tone; caveat?: string }> = {
  verified: { label: "Verified", tone: "ok" },
  partially_verified: {
    label: "Partially verified",
    tone: "warn",
    caveat: "Checked against the original problem, but part of the result is not established (see below).",
  },
  unverified: { label: "Unverified", tone: "warn", caveat: "No independent check confirmed this answer." },
  failed: { label: "No answer", tone: "bad", caveat: "No strategy produced a result that survived verification." },
  rejected: {
    label: "Rejected (out of domain)",
    tone: "bad",
    caveat: "Candidate witness was rejected as out of domain; historical attempt only.",
  },
  invalidated: {
    label: "Invalidated",
    tone: "bad",
    caveat: "Tool result was invalidated by revision or premise change.",
  },
};

const LEVEL_LABEL: Record<number, string> = { 0: "Execution", 1: "Matches the problem", 2: "Independent check" };
// How far the answer was checked, in words (the verifier's evidence levels 0-2).
const LEVEL_SUMMARY: Record<number, string> = {
  0: "executed only",
  1: "matches the stated problem",
  2: "independently checked",
};
const KIND_LABEL: Record<string, string> = { ode: "ODE", pde: "PDE", lin_system: "linear system", nonlinear_system: "nonlinear system" };

function checkTone(c: MathCheck): Tone {
  return c.passed === true ? "ok" : c.passed === false ? "bad" : "faint";
}

function stepTone(s: MathAgentStep): Tone {
  if (s.status === "ok" && s.failure === "none") return s.verdict?.status === "verified" ? "ok" : "info";
  return s.failure === "infrastructure" ? "faint" : "warn";
}

/**
 * Verified mathematics agent: the answer, how far it was checked against the original problem (alignment, then an
 * independent second method), what remains uncertain, and the bounded tool trajectory that produced it.
 */
export function MathAgentArtifact({ data }: { data?: MathData | null }) {
  if (!data || typeof data !== "object") return null;
  const isInvalidated = Boolean(data.invalidated || data.status === "rejected" || data.status === "invalidated");
  const isHistorical = Boolean(data.historical || isInvalidated);
  const status = isInvalidated
    ? (data.status === "rejected" ? STATUS.rejected : STATUS.invalidated)
    : (STATUS[data.status] ?? STATUS.unverified);
  const answer = data.answer ?? {};
  const latex = str(answer.latex);
  const text = str(answer.text);
  const checks = arr<MathCheck>(data.verification?.checks).filter((c) => c && c.level >= 1);
  const uncertainty = arr<string>(data.uncertainty);
  const steps = arr<MathAgentStep>(data.steps);
  const m = data.metrics ?? {};
  const kind = str(data.problem?.kind);
  const conf = data.confidence;
  const calls = m.tool_executions ?? steps.length;
  const level = Math.max(0, data.verification?.level ?? 0);
  const showLatex = Boolean(latex) && !text.includes("NOT an identity");

  return (
    <Card
      icon={<Sigma style={{ width: 16, height: 16, color: "#a78bfa" }} />}
      title={
        isInvalidated
          ? (data.status === "rejected" ? "Rejected candidate result (Axiom)" : "Invalidated mathematics candidate (Axiom)")
          : isHistorical
          ? "Historical mathematics attempt (Axiom)"
          : data.status === "verified"
          ? "Verified mathematics (Axiom agent)"
          : "Mathematics agent (Axiom)"
      }
      meta={[
        kind && kind !== "unknown" ? KIND_LABEL[kind] ?? kind.replace(/_/g, " ") : null,
        `${calls} tool call${calls === 1 ? "" : "s"}`,
        m.strategy_switches ? `${m.strategy_switches} strategy switch${m.strategy_switches === 1 ? "" : "es"}` : null,
        m.repair_attempts ? `${m.repairs_succeeded ?? 0}/${m.repair_attempts} repairs` : null,
        typeof m.seconds === "number" ? `${m.seconds.toFixed(2)} s` : null,
        "SymPy · mpmath",
      ]
        .filter(Boolean)
        .join(" · ")}
      label="Verified mathematics"
      collapsible
      actions={
        <>
          <Pill tone={status.tone} title="Status from the independent verifier, not from the model">
            {status.label}
          </Pill>
          {conf && typeof conf.p_correct === "number" && typeof conf.n === "number" && conf.n >= 10 && data.status === "verified" && !isInvalidated && !isHistorical ? ( /* a benchmark rate of verified answers says nothing about an unverified or tiny-sample one */
            <Pill
              tone="faint"
              title={
                `This answer expression only: ${Math.round(conf.p_correct * 100)}% of the agent's verified answers were ` +
                `correct on a held-out benchmark of single problems (n=${conf.n}, 95% lower bound ` +
                `${Math.round(conf.lower_95 * 100)}%${conf.fitted_on ? `; ${conf.fitted_on}` : ""}). It does not cover ` +
                "the written derivation or other values in the answer, which are checked one by one."
              }
            >
              {`Benchmark precision ${Math.round(conf.p_correct * 100)}% (n=${conf.n})`}
            </Pill>
          ) : null}
          {latex || text ? <CopyButton text={latex || text} label={latex ? "Copy LaTeX" : "Copy"} /> : null}
        </>
      }
    >
      {(latex || text) && (
        <Section title="Answer" caveat={status.caveat}>
          {showLatex ? <MarkdownRenderer content={`$$${latex}$$`} /> : null}
          {text && !showLatex && (
            <p className={styles.mono} style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{text}</p>
          )}
          {text && showLatex && (
            <Disclosure summary="Plain-text form">
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <p className={styles.mono} style={{ margin: 0, flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{text}</p>
                <CopyButton text={text} />
              </div>
            </Disclosure>
          )}
        </Section>
      )}
      {!latex && !text && status.caveat ? <p className={styles.note}>{status.caveat}</p> : null}

      {checks.length > 0 && (
        <Section title="Verification" meta={LEVEL_SUMMARY[level] ?? `level ${level}`}>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
            {checks.map((c, i) => {
              const passed = (isInvalidated && str(c.name).toLowerCase().includes("domain")) ? false : c.passed;
              return (
                <li key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <Pill tone={checkTone({ ...c, passed })}>{passed === true ? "Pass" : passed === false ? "Fail" : "Not run"}</Pill>
                  <span>{str(c.name).charAt(0).toUpperCase() + str(c.name).slice(1)}</span>
                  <span className={styles.muted} style={{ fontSize: "0.8em" }}>
                    {LEVEL_LABEL[c.level] ?? `Level ${c.level}`}
                    {(isInvalidated && str(c.name).toLowerCase().includes("domain") && data.invalidation_reason)
                      ? ` — ${data.invalidation_reason}`
                      : c.detail ? ` — ${str(c.detail)}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {uncertainty.length > 0 && (
        <Section title="Not established">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {uncertainty.map((u, i) => (
              <li key={i} className={styles.note} style={{ margin: "2px 0" }}>
                {u}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {steps.length > 0 && (
        <Disclosure summary={`Solver steps (${steps.length})`}>
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Tool</th>
                  <th scope="col">Strategy</th>
                  <th scope="col">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((s) => (
                  <tr key={s.index}>
                    <td className={styles.num}>{s.index + 1}</td>
                    <td className={styles.mono}>{str(s.tool).replace(/^axiom_/, "")}</td>
                    <td>
                      {str(s.strategy_name) || "—"}
                      <span className={styles.muted} style={{ fontSize: "0.8em" }}> · {str(s.policy)}</span>
                    </td>
                    <td>
                      <Pill tone={stepTone(s)}>
                        {s.status === "ok" && s.failure === "none"
                          ? str(s.verdict?.status || "ok").replace(/_/g, " ")
                          : str(s.failure).replace(/_/g, " ")}
                      </Pill>
                      {s.error ? (
                        <div className={styles.muted} style={{ fontSize: "0.8em", marginTop: 2, wordBreak: "break-word" }}>
                          {str(s.error).slice(0, 220)}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      )}
    </Card>
  );
}
