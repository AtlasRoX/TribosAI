"use client";

import React from "react";
import type { ExecutionArtifacts, TaskOutcome } from "@/types/chat";
import { artifactDisclosure } from "@/lib/artifactDisclosure";
import { DerivationArtifact } from "@/components/DerivationArtifact";
import { ArtifactRenderFallback, ErrorBoundary } from "@/components/ErrorBoundary";
import { EvidenceSources } from "@/components/EvidenceSources";
import { LiteratureArtifact } from "@/components/LiteratureArtifact";
import { ReferenceDataArtifact } from "@/components/ReferenceDataArtifact";
import { SimulationArtifact } from "@/components/SimulationArtifact";
import { AgentDialogueArtifact } from "@/components/agentic/AgentDialogueArtifact";
import { AgentRunPanel } from "@/components/agentic/AgentRunPanel";
import { CalibrationArtifact } from "@/components/agentic/CalibrationArtifact";
import { ClaimConfidenceArtifact } from "@/components/agentic/ClaimConfidenceArtifact";
import { EvidenceConflictsArtifact } from "@/components/agentic/EvidenceConflictsArtifact";
import { HypothesesArtifact } from "@/components/agentic/HypothesesArtifact";
import { PlanGraphArtifact } from "@/components/agentic/PlanGraphArtifact";
import { PlanApprovalArtifact, ProjectMemoryArtifact } from "@/components/agentic/ProjectMemoryArtifact";
import { SandboxAnalysisArtifact } from "@/components/agentic/SandboxAnalysisArtifact";
import { CardDisclosureContext } from "@/components/agentic/ui";

/**
 * Each card has its own boundary, so one faulty artifact never takes down the conversation or its sibling cards; a
 * card that throws is replaced by a visible "could not be displayed" note with the raw data (UI-006, UI-001).
 */
function ArtifactBoundary({
  name,
  data,
  open,
  children,
}: {
  name: string;
  data?: unknown;
  /** Default open state from the disclosure policy (lib/artifactDisclosure). */
  open?: boolean;
  children: React.ReactNode;
}) {
  return (
    <ErrorBoundary name={`Artifact "${name}"`} resetKey={data} fallback={<ArtifactRenderFallback label={name.replace(/_/g, " ")} data={data} />}>
      <CardDisclosureContext.Provider value={open}>{children}</CardDisclosureContext.Provider>
    </ErrorBoundary>
  );
}

/**
 * Structured result cards shown under an answer: decisions first, then symbolic derivations, physical reference data,
 * scholarly literature, numerical simulations, sandboxed computations, trust checks, and the run itself.
 */
export function MessageArtifacts({
  artifacts,
  question,
  taskStatus,
}: {
  artifacts?: ExecutionArtifacts;
  question?: string | null;
  taskStatus?: TaskOutcome | null;
}) {
  if (!artifacts) return null;
  const open = artifactDisclosure({ question, taskStatus, artifacts });
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

  return (
    <>
      {/* Needs the reader's decision */}
      {artifacts.plan_approval && (
        <ArtifactBoundary name="plan_approval" open={open["plan_approval"]} data={artifacts.plan_approval}>
          <PlanApprovalArtifact data={artifacts.plan_approval} />
        </ArtifactBoundary>
      )}
      {/* Symbolic derivations, physical constants & reference data, and scholarly literature */}
      {derivationData && (
        <ArtifactBoundary name={derivationKey} open={open[derivationKey]} data={derivationData}>
          <DerivationArtifact data={derivationData} />
        </ArtifactBoundary>
      )}
      {referenceData && (
        <ArtifactBoundary name={referenceKey} open={open[referenceKey]} data={referenceData}>
          <ReferenceDataArtifact data={referenceData} />
        </ArtifactBoundary>
      )}
      {hasGradedLiterature && artifacts.literature && (
        <ArtifactBoundary name="literature" open={open["literature"]} data={artifacts.literature}>
          <EvidenceSources data={artifacts.literature} />
        </ArtifactBoundary>
      )}
      {archivonData && (
        <ArtifactBoundary name="archivon" open={open["archivon"] ?? open["literature"]} data={archivonData}>
          <LiteratureArtifact data={archivonData} />
        </ArtifactBoundary>
      )}
      {/* Numerical simulation, sandboxed computation, and model calibration */}
      {(simData || simScan) && (
        <ArtifactBoundary name={simKey} open={open[simKey]} data={simData ?? simScan}>
          <SimulationArtifact data={simData} scan={simScan} />
        </ArtifactBoundary>
      )}
      {artifacts.sandbox_analysis && (
        <ArtifactBoundary name="sandbox_analysis" open={open["sandbox_analysis"]} data={artifacts.sandbox_analysis}>
          <SandboxAnalysisArtifact data={artifacts.sandbox_analysis} />
        </ArtifactBoundary>
      )}
      {artifacts.model_calibration && (
        <ArtifactBoundary name="model_calibration" open={open["model_calibration"]} data={artifacts.model_calibration}>
          <CalibrationArtifact data={artifacts.model_calibration} />
        </ArtifactBoundary>
      )}
      {artifacts.hypotheses && (
        <ArtifactBoundary name="hypotheses" open={open["hypotheses"]} data={artifacts.hypotheses}>
          <HypothesesArtifact data={artifacts.hypotheses} />
        </ArtifactBoundary>
      )}
      {/* How far the answer can be trusted */}
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
      {/* How the agent worked */}
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
  );
}
