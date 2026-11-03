"use client";

// The model's Python session for the question (backend: tribos/agentic/codeact.py): each cell the model wrote, whether
// it ran, its printed output, and the model's summary. "Open notebook" shows every cell in the right-hand code panel.

import React from "react";
import { Terminal } from "lucide-react";
import type { CodeFile } from "@/lib/codePanel";
import { Card, OpenCodeButton, Pill, Section, styles as ui } from "../agentic/ui";

type Cell = { code?: string; status?: string; stdout?: string; error?: string; seconds?: number };
type Session = { cells?: Cell[]; final?: string; stopped?: string; ok_cells?: number; steps?: number };

export function PythonSessionArtifact({ data }: { data: unknown }) {
  const d = (data && typeof data === "object" ? data : null) as Session | null;
  const cells = d?.cells ?? [];
  if (!d || !cells.length) return null;
  const files: CodeFile[] = cells.map((c, i) => ({
    name: `cell_${i + 1}.py`,
    language: "python",
    code: c.code ?? "",
    output: c.status === "ok" ? c.stdout ?? "" : `${c.status}: ${c.error ?? ""}`,
  }));
  const ok = d.ok_cells ?? cells.filter((c) => c.status === "ok").length;
  return (
    <Card
      icon={<Terminal style={{ width: 15, height: 15 }} />}
      title="Python session"
      meta={<Pill tone={ok === cells.length ? "ok" : "warn"}>{`${ok} of ${cells.length} cells ran`}</Pill>}
      label="Python session"
      collapsible
      defaultOpen={false}
    >
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <OpenCodeButton title="Python session" files={files} label="Open notebook" />
      </div>
      {cells.map((c, i) => (
        <Section key={i} title={`Cell ${i + 1}`} meta={c.status}>
          <div className={ui.codeWrap}>
            <OpenCodeButton title="Python session" files={files} active={i} />
            <pre className={ui.code}>{(c.code ?? "").split("\n").slice(0, 8).join("\n")}{(c.code ?? "").split("\n").length > 8 ? "\n…" : ""}</pre>
          </div>
          <pre className={ui.code}>{(c.status === "ok" ? c.stdout : c.error) || "(nothing printed)"}</pre>
        </Section>
      ))}
      {d.final && <p className={ui.note}>Session summary (the model&apos;s reading of the outputs): {d.final}</p>}
    </Card>
  );
}

export default PythonSessionArtifact;
