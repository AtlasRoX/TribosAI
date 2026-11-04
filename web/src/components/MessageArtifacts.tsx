"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { onUi } from "@/lib/uiEvents";
import { BookOpen, ChevronDown, Cpu, FlaskConical, ShieldCheck } from "lucide-react";
import type { ExecutionArtifacts, TaskOutcome } from "@/types/chat";
import { artifactAttention } from "@/lib/artifactDisclosure";
import { DerivationArtifact } from "@/components/DerivationArtifact";
import { ArtifactRenderFallback, ErrorBoundary } from "@/components/ErrorBoundary";
import { EvidenceSources } from "@/components/EvidenceSources";
import { LiteratureArtifact } from "@/components/LiteratureArtifact";
import { ReferenceDataArtifact } from "@/components/ReferenceDataArtifact";
import { ReproductionFiles } from "@/components/ReproductionFiles";
import { OdeVerificationArtifact } from "@/components/OdeVerificationArtifact";
import { SimulationArtifact } from "@/components/SimulationArtifact";
import { AgentDialogueArtifact } from "@/components/agentic/AgentDialogueArtifact";
import { AgentRunPanel } from "@/components/agentic/AgentRunPanel";
import { CalibrationArtifact } from "@/components/agentic/CalibrationArtifact";
import { ClaimConfidenceArtifact } from "@/components/agentic/ClaimConfidenceArtifact";
import { EvidenceConflictsArtifact } from "@/components/agentic/EvidenceConflictsArtifact";
import { HypothesesArtifact } from "@/components/agentic/HypothesesArtifact";
import { MathAgentArtifact } from "@/components/agentic/MathAgentArtifact";
import { PlanGraphArtifact } from "@/components/agentic/PlanGraphArtifact";
import { PlanApprovalArtifact, ProjectMemoryArtifact } from "@/components/agentic/ProjectMemoryArtifact";
import { SandboxAnalysisArtifact } from "@/components/agentic/SandboxAnalysisArtifact";
import { CardAttentionContext, CardDisclosureContext } from "@/components/agentic/ui";
import { FEATURE_ARTIFACTS } from "@/components/artifacts/registry";
import { PlotArtifact, type PlotData } from "@/components/PlotArtifact";
import { TaskPlanArtifact } from "@/components/TaskPlanArtifact";
import styles from "./MessageArtifacts.module.css";

/** Why a card needs a look (artifactAttention), by artifact key; absent when it carries no warning. */
const AttentionContext = React.createContext<Record<string, string>>({});

function ArtifactBoundary({
  name,
  data,
  open,
  children,
}: {
  name: string;
  data?: unknown;
  open?: boolean;
  children: React.ReactNode;
}) {
  const attention = React.useContext(AttentionContext);
  return (
    <ErrorBoundary name={`Artifact "${name}"`} resetKey={data} fallback={<ArtifactRenderFallback label={name.replace(/_/g, " ")} data={data} />}>
      <CardAttentionContext.Provider value={attention[name] || ""}>
        <CardDisclosureContext.Provider value={open}>{children}</CardDisclosureContext.Provider>
      </CardAttentionContext.Provider>
    </ErrorBoundary>
  );
}

/** Result cards that show the answer itself (simulations, fields, distributions): kept in the clean answer view. */
const VISUAL_RESULT_KEYS = new Set(["scientific_execution", "monte_carlo", "pde", "uncertainty"]);

export function MessageArtifacts({
  artifacts,
  question,
  taskStatus,
  visualOnly = false,
}: {
  artifacts?: ExecutionArtifacts;
  question?: string | null;
  taskStatus?: TaskOutcome | null;
  /** The clean answer view: only the interactive results (a simulation, a field, a distribution); no evidence,
   *  verification, solver or trace cards. */
  visualOnly?: boolean;
}) {
  const [chosenTab, setChosenTab] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(false); // supporting evidence starts closed: the answer comes first
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const deckRef = useRef<HTMLElement>(null);
  const deckId = useId();
  // "Checked: ..." under the answer opens this deck's Verification tab.
  useEffect(
    () =>
      onUi("tribos:evidence-tab", ({ tab, messageId }) => {
        const mine = deckRef.current?.closest("[data-message-id]")?.getAttribute("data-message-id");
        if (!deckRef.current || (messageId && mine !== messageId)) return;
        setChosenTab(tab);
        setInspectorOpen(true);
        requestAnimationFrame(() => deckRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      }),
    []
  );
  if (!artifacts) return null;
  // Every card starts collapsed so the written answer is what the reader sees first; a card that holds a warning
  // (contradiction, low support, failed or unfinished work) says "needs a look" in its header instead of opening.
  const attention = artifactAttention({ question, taskStatus, artifacts });
  const open: Record<string, boolean> = Object.fromEntries(Object.keys(artifacts).map((key) => [key, false]));

  const derivationData = artifacts.derivation ?? artifacts.axiom;
  const derivationKey = artifacts.derivation ? "derivation" : "axiom";
  const referenceData = artifacts.reference_data ?? artifacts.physis;
  const referenceKey = artifacts.reference_data ? "reference_data" : "physis";
  const simData = artifacts.dynamis ?? artifacts.vivarix;
  const simScan = artifacts.dynamis_scan ?? artifacts.vivarix_scan;
  const simKey = artifacts.dynamis ? "dynamis" : artifacts.vivarix ? "vivarix" : artifacts.dynamis_scan ? "dynamis_scan" : "vivarix_scan";

  const hasGradedLiterature = Boolean(
    artifacts.literature &&
      ((Array.isArray(artifacts.literature.graded_articles) && artifacts.literature.graded_articles.length > 0) ||
        (Array.isArray(artifacts.literature.excluded_articles) && artifacts.literature.excluded_articles.length > 0))
  );
  const archivonData = artifacts.archivon ?? (!hasGradedLiterature ? artifacts.literature : undefined);

  // Group secondary/inspection items to prevent vertical card sprawl
  const hasLiterature = Boolean((hasGradedLiterature && artifacts.literature) || archivonData);
  const hasHypotheses = Boolean(artifacts.hypotheses);
  const hasVerification = Boolean(artifacts.claim_confidence || artifacts.evidence_conflicts);
  const hasDiagnostics = Boolean(
    artifacts.agent_run || artifacts.agent_plan || artifacts.agent_dialogue || artifacts.project_memory || artifacts.plan_approval
  );

  const secondarySections: Array<{
    id: "literature" | "hypotheses" | "verification" | "diagnostics";
    label: string;
    icon: React.ReactNode;
    badge?: string | number;
  }> = [];

  if (hasLiterature) {
    const totalArticles =
      (artifacts.literature?.graded_articles?.length ?? 0) +
      (artifacts.literature?.excluded_articles?.length ?? 0) ||
      artifacts.literature?.passages?.length ||
      artifacts.archivon?.passages?.length;
    secondarySections.push({
      id: "literature",
      label: "Literature",
      icon: <BookOpen style={{ width: 14, height: 14 }} aria-hidden="true" />,
      badge: totalArticles ? String(totalArticles) : undefined,
    });
  }
  if (hasHypotheses) {
    const hypCount = artifacts.hypotheses?.hypotheses?.length;
    secondarySections.push({
      id: "hypotheses",
      label: "Hypotheses",
      icon: <FlaskConical style={{ width: 14, height: 14 }} aria-hidden="true" />,
      badge: hypCount ? String(hypCount) : undefined,
    });
  }
  if (hasVerification) {
    // A probability is shown only when the claim-confidence model produced one for the whole answer; a computed
    // answer shows how many of its written statements the checks confirmed instead (never the agent's benchmark
    // precision, which describes its final expression only).
    const score = artifacts.claim_confidence?.answer_confidence;
    const checks = (artifacts.claim_confidence as { statement_checks?: { extracted?: number; passed?: number } } | undefined)
      ?.statement_checks;
    secondarySections.push({
      id: "verification",
      label: "Verification",
      icon: <ShieldCheck style={{ width: 14, height: 14 }} aria-hidden="true" />,
      badge:
        typeof score === "number"
          ? `${Math.round(score * 100)}%`
          : checks?.extracted
            ? `${checks.passed ?? 0}/${checks.extracted}`
            : undefined,
    });
  }
  if (hasDiagnostics) {
    secondarySections.push({
      id: "diagnostics",
      label: "Plan & trace",
      icon: <Cpu style={{ width: 14, height: 14 }} aria-hidden="true" />,
    });
  }

  // The reader's tab while it exists; otherwise the first section.
  const activeTab = secondarySections.some((s) => s.id === chosenTab) ? chosenTab : secondarySections[0]?.id;
  const focusTab = (index: number) => {
    const next = (index + secondarySections.length) % secondarySections.length;
    setChosenTab(secondarySections[next].id);
    tabRefs.current[next]?.focus();
  };
  const onTabKey = (e: React.KeyboardEvent, index: number) => {
    const moves: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: secondarySections.length - 1 };
    if (e.key in moves) {
      e.preventDefault();
      focusTab(moves[e.key]);
    }
  };

  return (
    <AttentionContext.Provider value={attention}>
      {/* 0. The plan of a multi-part question (its parts, tools and outcomes), then a plot it asked for: both shown in
          full, in the clean view too */}
      {(artifacts as Record<string, unknown>).task_plan ? (
        <ErrorBoundary name="Task plan" resetKey={(artifacts as Record<string, unknown>).task_plan}>
          <TaskPlanArtifact data={(artifacts as Record<string, unknown>).task_plan as { steps?: [] }} />
        </ErrorBoundary>
      ) : null}
      {(artifacts as Record<string, unknown>).plot ? (
        <ErrorBoundary name="Plot" resetKey={(artifacts as Record<string, unknown>).plot}>
          <PlotArtifact data={(artifacts as Record<string, unknown>).plot as PlotData} />
        </ErrorBoundary>
      ) : null}
      {/* 1. Direct core analytical and physical results (a plan approval is a record of the run: Plan & trace) */}
      {!visualOnly && artifacts.math_agent && (
        <ArtifactBoundary name="math_agent" open={open["math_agent"]} data={artifacts.math_agent}>
          <MathAgentArtifact data={artifacts.math_agent} />
        </ArtifactBoundary>
      )}
      {!visualOnly && artifacts.ode_verification && (
        <ArtifactBoundary name="ode_verification" open={open["ode_verification"]} data={artifacts.ode_verification}>
          <OdeVerificationArtifact data={artifacts.ode_verification} />
        </ArtifactBoundary>
      )}
      {!visualOnly && derivationData && (
        <ArtifactBoundary name={derivationKey} open={open[derivationKey]} data={derivationData}>
          <DerivationArtifact data={derivationData} />
        </ArtifactBoundary>
      )}
      {!visualOnly && referenceData && (
        <ArtifactBoundary name={referenceKey} open={open[referenceKey]} data={referenceData}>
          <ReferenceDataArtifact data={referenceData} />
        </ArtifactBoundary>
      )}
      {(simData || simScan) && (
        <ArtifactBoundary name={simKey} open={open[simKey]} data={simData ?? simScan}>
          <SimulationArtifact data={simData} scan={simScan} />
        </ArtifactBoundary>
      )}
      {!visualOnly && artifacts.sandbox_analysis && (
        <ArtifactBoundary name="sandbox_analysis" open={open["sandbox_analysis"]} data={artifacts.sandbox_analysis}>
          <SandboxAnalysisArtifact data={artifacts.sandbox_analysis} />
        </ArtifactBoundary>
      )}
      {!visualOnly && artifacts.model_calibration && (
        <ArtifactBoundary name="model_calibration" open={open["model_calibration"]} data={artifacts.model_calibration}>
          <CalibrationArtifact data={artifacts.model_calibration} />
        </ArtifactBoundary>
      )}
      {FEATURE_ARTIFACTS.map(({ key, Component }) => {
        if (visualOnly && !VISUAL_RESULT_KEYS.has(key)) return null;
        const data = (artifacts as Record<string, unknown>)[key];
        return data ? (
          <ArtifactBoundary key={key} name={key} open={open[key]} data={data}>
            <Component data={data} artifacts={artifacts as Record<string, unknown>} />
          </ArtifactBoundary>
        ) : null;
      })}

      {!visualOnly && <ReproductionFiles artifacts={artifacts} />}

      {/* 3. Supporting evidence: a tab row over the cards, so secondary detail never sprawls down the page */}
      {!visualOnly && secondarySections.length > 0 && (
        <section ref={deckRef} className={styles.deck} aria-label="Supporting evidence">
          <div className={styles.bar}>
            <span className={styles.heading}>Evidence</span>
            <div className={styles.tabs} role="tablist" aria-label="Supporting evidence sections">
              {secondarySections.map((sec, index) => {
                const isActive = activeTab === sec.id;
                return (
                  <button
                    key={sec.id}
                    ref={(el) => {
                      tabRefs.current[index] = el;
                    }}
                    type="button"
                    role="tab"
                    id={`${deckId}-tab-${sec.id}`}
                    aria-selected={isActive}
                    aria-controls={`${deckId}-panel`}
                    tabIndex={isActive ? 0 : -1}
                    className={`${styles.tab} ${isActive ? styles.tabActive : ""}`}
                    onClick={() => {
                      setChosenTab(sec.id);
                      setInspectorOpen(true);
                    }}
                    onKeyDown={(e) => onTabKey(e, index)}
                  >
                    {sec.icon}
                    <span>{sec.label}</span>
                    {sec.badge && <span className={styles.count}>{sec.badge}</span>}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className={styles.toggle}
              onClick={() => setInspectorOpen((prev) => !prev)}
              aria-expanded={inspectorOpen}
              aria-controls={`${deckId}-panel`}
            >
              {inspectorOpen ? "Hide" : "Show"}
              <ChevronDown
                className={`${styles.chev} ${inspectorOpen ? styles.chevOpen : ""}`}
                style={{ width: 14, height: 14 }}
                aria-hidden="true"
              />
            </button>
          </div>

          {inspectorOpen && (
            <div id={`${deckId}-panel`} role="tabpanel" aria-labelledby={`${deckId}-tab-${activeTab}`} className={styles.panel}>
              {activeTab === "literature" && (
                <>
                  {hasGradedLiterature && artifacts.literature && (
                    <ArtifactBoundary name="literature" open={open["literature"]} data={artifacts.literature}>
                      <EvidenceSources data={artifacts.literature} />
                    </ArtifactBoundary>
                  )}
                  {archivonData && (
                    <ArtifactBoundary name="archivon" open={open["archivon"]} data={archivonData}>
                      <LiteratureArtifact data={archivonData} />
                    </ArtifactBoundary>
                  )}
                </>
              )}

              {activeTab === "hypotheses" && artifacts.hypotheses && (
                <ArtifactBoundary name="hypotheses" open={open["hypotheses"]} data={artifacts.hypotheses}>
                  <HypothesesArtifact data={artifacts.hypotheses} />
                </ArtifactBoundary>
              )}

              {activeTab === "verification" && (
                <>
                  {artifacts.evidence_conflicts && (
                    <ArtifactBoundary name="evidence_conflicts" open={open["evidence_conflicts"]} data={artifacts.evidence_conflicts}>
                      <EvidenceConflictsArtifact data={artifacts.evidence_conflicts} />
                    </ArtifactBoundary>
                  )}
                  {artifacts.claim_confidence && (
                    <ArtifactBoundary name="claim_confidence" open={open["claim_confidence"]} data={artifacts.claim_confidence}>
                      <ClaimConfidenceArtifact data={artifacts.claim_confidence} />
                    </ArtifactBoundary>
                  )}
                </>
              )}

              {activeTab === "diagnostics" && (
                <>
                  {artifacts.plan_approval && (
                    <ArtifactBoundary name="plan_approval" open={false} data={artifacts.plan_approval}>
                      <PlanApprovalArtifact data={artifacts.plan_approval} />
                    </ArtifactBoundary>
                  )}
                  {artifacts.agent_run && (
                    <ArtifactBoundary name="agent_run" open={open["agent_run"]} data={artifacts.agent_run}>
                      <AgentRunPanel data={artifacts.agent_run} routing={artifacts.framework_routing} />
                    </ArtifactBoundary>
                  )}
                  {artifacts.agent_plan && (
                    <ArtifactBoundary name="agent_plan" open={open["agent_plan"]} data={artifacts.agent_plan}>
                      <PlanGraphArtifact data={artifacts.agent_plan} />
                    </ArtifactBoundary>
                  )}
                  {artifacts.agent_dialogue && (
                    <ArtifactBoundary name="agent_dialogue" open={open["agent_dialogue"]} data={artifacts.agent_dialogue}>
                      <AgentDialogueArtifact data={artifacts.agent_dialogue} />
                    </ArtifactBoundary>
                  )}
                  {artifacts.project_memory && (
                    <ArtifactBoundary name="project_memory" open={open["project_memory"]} data={artifacts.project_memory}>
                      <ProjectMemoryArtifact data={artifacts.project_memory} />
                    </ArtifactBoundary>
                  )}
                </>
              )}
            </div>
          )}
        </section>
      )}
    </AttentionContext.Provider>
  );
}
