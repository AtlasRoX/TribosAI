// Data shaping for the Lean proof card (FormalProofArtifact.tsx), free of React so node tests can import it.

export type FormalData = {
  status?: "verified" | "failed" | "timeout" | "unavailable" | "mismatch" | "not_formalizable" | "disabled" | "disabled_by_user" | "not_applicable" | "running" | "cancelled";
  title?: string;
  question?: string;
  statement?: string;
  lean_code?: string;
  error?: string | null;
  output?: string;
  messages?: { line?: number; column?: number; severity?: string; message?: string }[];
  attempts?: { attempt?: number; status?: string; error?: string | null }[];
  repairs?: number;
};

export function formalData(data: unknown): FormalData | null {
  return data && typeof data === "object" && typeof (data as FormalData).status === "string" ? (data as FormalData) : null;
}

/** The badge: only a clean Lean compile is "formally verified (Lean)". */
export function formalBadge(d: FormalData): { tone: "ok" | "bad" | "neutral"; text: string } {
  if (d.status === "verified") return { tone: "ok", text: "formally verified (Lean)" };
  if (d.status === "disabled" || d.status === "disabled_by_user") return { tone: "neutral", text: "Skipped: disabled by user" };
  if (d.status === "not_applicable") return { tone: "neutral", text: "not applicable" };
  if (d.status === "cancelled") return { tone: "neutral", text: "cancelled" };
  if (d.status === "running") return { tone: "neutral", text: "running" };
  if (d.status === "unavailable") return { tone: "neutral", text: "formal checker unavailable" };
  // Not a failed proof: the question cannot be stated without Mathlib, so nothing was checked (audit I33).
  if (d.status === "not_formalizable") return { tone: "neutral", text: "not formalisable without Mathlib" };
  if (d.status === "mismatch") return { tone: "bad", text: "statement does not match the question" };
  return { tone: "bad", text: d.status === "timeout" ? "formalisation failed (timeout)" : "formalisation failed" };
}

/** The compiler messages as "line:col severity: message" lines, errors first. */
export function compilerLines(d: FormalData): string[] {
  const rank = (s?: string) => (s === "error" ? 0 : s === "warning" ? 1 : 2);
  return [...(d.messages ?? [])]
    .sort((a, b) => rank(a.severity) - rank(b.severity))
    .map((m) => `${m.line ?? "?"}:${m.column ?? "?"} ${m.severity ?? "info"}: ${m.message ?? ""}`);
}
