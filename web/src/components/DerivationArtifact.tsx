"use client";

import React from "react";
import { Sigma } from "lucide-react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { Card, CopyButton, Pill, Section, Stats, arr, fmt, isNum, str, styles as ui } from "./agentic/ui";

export interface DerivationStep {
  id?: string;
  tool?: string;
  operation?: string;
  description?: string;
  input?: string;
  input_latex?: string;
  output?: string;
  output_latex?: string;
  latex?: string;
  result?: unknown;
  verified?: boolean;
  residual?: number | null;
  status?: string;
}

export interface DerivationArtifactProps {
  data?: Record<string, any> | null;
}

function toMathBlock(latexOrExpr: unknown): string {
  const raw = str(latexOrExpr).trim();
  if (!raw) return "";
  if (raw.startsWith("$$") || raw.startsWith("$")) return raw;
  return `$$${raw}$$`;
}

/**
 * Axiom symbolic mathematics card: algebraic simplification, equation solving, symbolic calculus,
 * differential equations, exact linear algebra, and identity verification.
 */
export function DerivationArtifact({ data }: DerivationArtifactProps) {
  if (!data || typeof data !== "object") return null;

  const steps = arr<DerivationStep>(data.steps ?? data.operations ?? data.derivations ?? data.results);
  const mainLatex = str(data.result_latex ?? data.output_latex ?? data.latex);
  const mainOutput = str(data.result ?? data.output ?? data.expression ?? data.solution);
  const mainInput = str(data.input ?? data.query ?? data.equation ?? data.lhs);
  const operation = str(data.operation ?? data.tool ?? "symbolic derivation");
  const verified = typeof data.verified === "boolean" ? data.verified : typeof data.is_equal === "boolean" ? data.is_equal : null;
  const residual = isNum(data.residual ?? data.max_residual ?? data.spot_check_residual)
    ? Number(data.residual ?? data.max_residual ?? data.spot_check_residual)
    : null;
  const solutions = arr<any>(data.solutions ?? data.roots);

  if (!steps.length && !mainLatex && !mainOutput && !solutions.length) return null;

  const copyPayload = mainLatex || mainOutput || steps.map((s) => str(s.output_latex ?? s.latex ?? s.output ?? s.result)).filter(Boolean).join("\n");

  return (
    <Card
      icon={<Sigma style={{ width: 16, height: 16, color: "#a78bfa" }} />}
      title="Symbolic derivation (Axiom)"
      meta={[
        operation.replace(/^axiom_/, "").replace(/_/g, " "),
        steps.length ? `${steps.length} step${steps.length === 1 ? "" : "s"}` : null,
         "SymPy",
      ]
        .filter(Boolean)
        .join(" · ")}
      label="Symbolic derivation"
      collapsible
      actions={
        <>
          {verified !== null && (
            <Pill tone={verified ? "ok" : "warn"}>{verified ? "Verified symbolically" : "Unverified"}</Pill>
          )}
          {copyPayload ? <CopyButton text={copyPayload} label="Copy LaTeX" /> : null}
        </>
      }
    >
      <Stats
        items={[
          { label: "Engine", value: "SymPy" },
          ...(steps.length ? [{ label: "Steps", value: steps.length }] : []),
          ...(verified !== null ? [{ label: "Identity check", value: verified ? "Exact match" : "Did not simplify to 0" }] : []),
          ...(residual !== null ? [{ label: "Numeric spot-check residual", value: fmt(residual, 3) }] : []),
        ]}
      />

      {(mainLatex || mainOutput) && (
        <Section title="Result" meta={mainInput ? `Input: ${mainInput}` : undefined}>
          <MarkdownRenderer content={toMathBlock(mainLatex || mainOutput)} />
        </Section>
      )}

      {solutions.length > 0 && (
        <Section title="Solutions" meta={`${solutions.length} found`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Symbolic form</th>
                </tr>
              </thead>
              <tbody>
                {solutions.map((sol, idx) => (
                  <tr key={idx}>
                    <td className={ui.num}>{idx + 1}</td>
                    <td>
                      <MarkdownRenderer content={`$${str(sol)}$`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {steps.length > 0 && (
        <Section title="Derivation steps" meta={`${steps.length} operation${steps.length === 1 ? "" : "s"}`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Input</th>
                  <th scope="col">Symbolic result</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step, idx) => {
                  const stepOp = str(step.operation ?? step.tool ?? step.description ?? `Step ${idx + 1}`)
                    .replace(/^axiom_/, "")
                    .replace(/_/g, " ");
                  const inp = str(step.input_latex ?? step.input);
                  const out = str(step.output_latex ?? step.latex ?? step.output ?? step.result);
                  const ok = step.verified ?? (step.status ? step.status === "ok" : true);
                  return (
                    <tr key={step.id || idx}>
                      <td>{stepOp}</td>
                      <td>{inp ? <code>{inp}</code> : "—"}</td>
                      <td>{out ? <MarkdownRenderer content={`$${out}$`} /> : "—"}</td>
                      <td>
                        <Pill tone={ok ? "ok" : "warn"}>{ok ? "Verified" : str(step.status || "check")}</Pill>
                      </td>
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
