// Status labels for the symbolic derivation card (AUDIT-006). A math-agent step's status "ok" means the tool ran, not
// that its result was checked, so only an explicit boolean `verified` (on the step or on its tool output) may say
// "Verified"; anything else says "Ran" or "Not checked". The run's own status (verified / partially_verified /
// unverified / failed) is shown in the card header.

export type StatusTone = "ok" | "info" | "warn" | "bad" | "neutral";

export interface StatusLabel {
  label: string;
  tone: StatusTone;
}

const RUN_STATUS: Record<string, StatusLabel> = {
  verified: { label: "Verified", tone: "ok" },
  partially_verified: { label: "Partially verified", tone: "warn" },
  unverified: { label: "Unverified", tone: "warn" },
  refuted: { label: "Refuted", tone: "bad" },
  failed: { label: "Failed", tone: "bad" },
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** The run-level status of an Axiom payload, or null when the payload states none. */
export function derivationRunStatus(data: unknown): StatusLabel | null {
  const d = record(data);
  if (!d) return null;
  const status = String(d.status ?? record(d.verification)?.status ?? "").toLowerCase();
  if (status && RUN_STATUS[status]) return RUN_STATUS[status];
  const flag = typeof d.verified === "boolean" ? d.verified : typeof d.is_equal === "boolean" ? d.is_equal : null;
  if (flag === null) return null;
  return flag ? { label: "Verified symbolically", tone: "ok" } : { label: "Unverified", tone: "warn" };
}

/** One step's check label: explicit verification only; a step that merely ran is "Ran". */
export function derivationStepStatus(step: unknown): StatusLabel {
  const s = record(step) ?? {};
  const explicit = typeof s.verified === "boolean" ? s.verified : record(s.output)?.verified;
  if (explicit === true) return { label: "Verified", tone: "ok" };
  if (explicit === false) return { label: "Not verified", tone: "warn" };
  const status = typeof s.status === "string" ? s.status.toLowerCase() : "";
  if (status === "ok") return { label: "Ran", tone: "neutral" };
  if (status) return { label: status, tone: "warn" };
  return { label: "Not checked", tone: "neutral" };
}
