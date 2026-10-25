"use client";

// Result cards of the newer features, rendered by MessageArtifacts after the core cards.
//
// Each feature owns its own component file under src/components/artifacts/ and adds ONE entry below: the
// execution_artifacts key its backend writes, and the component that renders it. MessageArtifacts renders every
// entry whose key is present, inside the same error boundary as the built-in cards, so a feature never has to edit
// MessageArtifacts itself.

import type React from "react";
import { EngineeringCalcArtifact } from "./EngineeringCalcArtifact";
import { PaperArtifact } from "./PaperArtifact";
import { PdeArtifact } from "./PdeArtifact";
import { UncertaintyArtifact } from "./UncertaintyArtifact";
import { FEATURE_ARTIFACT_KEYS } from "./artifactKeys";

export type FeatureArtifactProps = {
  /** The value of execution_artifacts[key] for this message. */
  data: unknown;
  /** Every execution artifact of the message, for cards that cross-reference another one. */
  artifacts: Record<string, unknown>;
};

export type FeatureArtifact = {
  /** The execution_artifacts key the backend writes (for example "pde"). */
  key: string;
  Component: React.ComponentType<FeatureArtifactProps>;
};

export const FEATURE_ARTIFACTS: FeatureArtifact[] = [
  // Feature entries (one line each), e.g. { key: "pde", Component: PdeArtifact },
  { key: "uncertainty", Component: UncertaintyArtifact },
  { key: "pde", Component: PdeArtifact },
  { key: "engineering_calc", Component: EngineeringCalcArtifact },
  { key: "paper_reproduction", Component: PaperArtifact },
];
