"use client";

// Construct mode (backend: tribos/agentic/construct.py): the best program the search found, the candidate it
// returns, and how it compares with the best known value. The program opens in the right-hand code panel. The
// numbers themselves are shown in the results panel above the answer.

import React from "react";
import { Shapes } from "lucide-react";
import { Card, CopyButton, OpenCodeButton, Pill, Section, styles as ui } from "../agentic/ui";

type Construction = { kind?: string; problem?: string; verdict?: string; best_program?: string; candidate?: unknown };

export function ConstructionArtifact({ data }: { data: unknown }) {
  const d = (data && typeof data === "object" ? data : null) as Construction | null;
  if (!d || d.kind !== "construction_search" || !d.best_program) return null;
  const candidate = JSON.stringify(d.candidate);
  const beats = (d.verdict ?? "").startsWith("beats");
  return (
    <Card
      icon={<Shapes style={{ width: 15, height: 15 }} />}
      title={`Construction search: ${d.problem ?? ""}`}
      meta={<Pill tone={beats ? "warn" : "ok"}>{beats ? "candidate record: needs confirmation" : "checked exactly"}</Pill>}
      label="Construction search"
      collapsible
      defaultOpen={false}
    >
      {d.verdict && <p className={ui.note} style={{ marginTop: 0 }}>{d.verdict}</p>}
      <Section title="Best program">
        <div className={ui.codeWrap}>
          <OpenCodeButton title={`Best program: ${d.problem ?? "construction"}`}
            files={[{ name: "construct.py", language: "python", code: d.best_program },
                    { name: "candidate.json", language: "json", code: candidate }]} />
          <pre className={ui.code}>{d.best_program.split("\n").slice(0, 12).join("\n")}{d.best_program.split("\n").length > 12 ? "\n…" : ""}</pre>
        </div>
      </Section>
      <Section title="Candidate">
        <div className={ui.codeWrap}>
          <CopyButton text={candidate} label="Copy" />
          <pre className={ui.code}>{candidate.length > 600 ? `${candidate.slice(0, 600)}…` : candidate}</pre>
        </div>
      </Section>
    </Card>
  );
}

export default ConstructionArtifact;
