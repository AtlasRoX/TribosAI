export interface ExecutionCheck {
  name: string;
  passed: boolean;
}

export interface ScientificExecution {
  status: string;
  tool: string;
  kind: string;
  request: Record<string, unknown>;
  checks: ExecutionCheck[];
  request_match: boolean;
  elapsed_seconds?: number;
  result_sha256?: string;
  reproduction_script?: string;
  reproduction_script_executed?: boolean;
  verification_scope?: string;
  error?: string;
  [key: string]: unknown;
}

export function scientificExecution(data: unknown): ScientificExecution | null {
  if (!data || typeof data !== "object") return null;
  const raw = data as Record<string, unknown>;
  if (typeof raw.status !== "string" || typeof raw.tool !== "string") return null;
  const checks = (Array.isArray(raw.checks) ? raw.checks : []).filter(
    (v): v is ExecutionCheck => Boolean(v && typeof v === "object" && typeof v.name === "string" && typeof v.passed === "boolean")
  );
  return {
    ...raw,
    status: raw.status,
    tool: raw.tool,
    kind: typeof raw.kind === "string" ? raw.kind : "scientific_computation",
    request: raw.request && typeof raw.request === "object" ? raw.request as Record<string, unknown> : {},
    checks,
    request_match: raw.request_match === true,
  } as ScientificExecution;
}

export function executionLabel(record: ScientificExecution): string {
  if (record.status === "reused") return "Reused computed result";
  if (record.status === "executed") return record.request_match ? "Executed · request matched" : "Executed · request mismatch";
  return record.status === "needs_input" ? "Input required" : "Execution incomplete";
}
