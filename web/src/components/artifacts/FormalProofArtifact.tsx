"use client";

// A Lean 4 proof check (T5): the status badge (formally verified only on a clean compile), the Lean statement next to
// the question so the reader can judge whether it is faithful, the Lean code with a copy button, and the compiler
// messages. Without Lean installed the card only says that the formal checker is unavailable.

import React from "react";
import { ShieldCheck } from "lucide-react";
import { Card, CopyButton, Disclosure, OpenCodeButton, Pill, Section, styles as ui } from "../agentic/ui";
import { compilerLines, formalBadge, formalData } from "./formalData";

export function FormalProofArtifact({ data }: { data: unknown }) {
  const d = formalData(data);
  if (!d) return null;
  const badge = formalBadge(d);
  const lines = compilerLines(d);
  return (
    <Card
      icon={<ShieldCheck style={{ width: 15, height: 15 }} />}
      title="Formal proof (Lean 4)"
      meta={<Pill tone={badge.tone}>{badge.text}</Pill>}
      label="Formal proof check"
      collapsible
      defaultOpen={d.status !== "unavailable"}
    >
      {d.status === "unavailable" ? (
        <p className={ui.note} style={{ marginTop: 0 }}>
          {d.error || "Lean is not installed on the server, so no formal check was run."} The answer&apos;s other checks are unchanged.
        </p>
      ) : (
        <>
          {d.statement && (
            <Section title="What Lean checked" hint="Compare this statement with the question: a proof of a different statement proves nothing about it">
              <pre className={ui.code}>{d.statement}</pre>
              {d.question && <p className={ui.note}>Question: {d.question}</p>}
            </Section>
          )}
          {d.error && d.status !== "verified" && <p className={ui.warnNote}>{d.error}</p>}
          {d.lean_code && (
            <Section title="Lean code" meta={d.repairs ? `${d.repairs} repair${d.repairs === 1 ? "" : "s"}` : undefined}>
              <div className={ui.codeWrap}>
                <OpenCodeButton title="Lean proof" files={[{ name: "Proof.lean", language: "lean", code: d.lean_code }]} label="Open" />
                <CopyButton text={d.lean_code} label="Copy Lean" />
                <pre className={ui.code}>{d.lean_code}</pre>
              </div>
            </Section>
          )}
          {lines.length > 0 && (
            <Disclosure summary={`Compiler output (${lines.length} message${lines.length === 1 ? "" : "s"})`}>
              <pre className={ui.code}>{lines.join("\n")}</pre>
            </Disclosure>
          )}
        </>
      )}
    </Card>
  );
}

export default FormalProofArtifact;
