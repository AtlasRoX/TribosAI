// Client for the agentic platform routes: /api/frameworks, /api/agent/runs, /api/jobs and /api/projects
// (docs/plans/agentic-system.md §2 F13, F15, F16). Every call takes the backend URL and the page's
// authHeaders helper, like datasetService, so the bearer token is only ever sent to the committed URL.

import { ApiError, apiFetch, delay, errorStatus, readSseEvents, requestJson, type AuthHeaders, type SseFrame } from "./apiClient.ts";
import type {
  AgentOptions,
  AgentOptionsSettings,
  ApproveBody,
  CreateJobResponse,
  FactReviewStatus,
  FrameworksResponse,
  JobSummary,
  MemoryFact,
  NewFactInput,
  Project,
  ProjectActivityEvent,
  ProjectFile,
  ProjectInput,
  ProjectMember,
  ProjectPatchInput,
  ProjectRole,
  RunControlState,
} from "@/types/agentic";

export { readSseEvents };
export type { AuthHeaders };

/** Every API failure is an ApiError; the old name stays for existing `instanceof AgentApiError` checks. */
export { ApiError as AgentApiError };

const request = <T>(url: string, init: RequestInit): Promise<T> => requestJson<T>(url, init);

const json = (authHeaders: AuthHeaders) => authHeaders({ "Content-Type": "application/json" });
const enc = encodeURIComponent;

/** Pulls a list out of either a bare array or an object wrapping it under one of `keys`. */
function listFrom<T>(body: unknown, keys: string[]): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object") {
    for (const k of keys) {
      const v = (body as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

// ---------------------------------------------------------------------------------------------------------------
// Frameworks and request options
// ---------------------------------------------------------------------------------------------------------------

export function fetchFrameworks(backendUrl: string, authHeaders: AuthHeaders, signal?: AbortSignal): Promise<FrameworksResponse> {
  return request<FrameworksResponse>(`${backendUrl}/api/frameworks`, { headers: authHeaders(), signal });
}

export function fetchEffortLevels(backendUrl: string, authHeaders: AuthHeaders, signal?: AbortSignal): Promise<import("@/types/agentic").EffortLevelsResponse> {
  return request<import("@/types/agentic").EffortLevelsResponse>(`${backendUrl}/api/effort-levels`, { headers: authHeaders(), signal });
}

export const EFFORT_LEVELS: {
  id: import("@/types/agentic").EffortLevel;
  name: string;
  tagline: string;
  description: string;
  icon: string;
  badge: string;
  color: string;
}[] = [
  {
    id: "low",
    name: "Fast",
    tagline: "Fast & Focused",
    description: "Minimal thinking overhead, 2 subqueries, 4 literature articles, 1 draft round. Best for quick lookups and fast facts.",
    icon: "Zap",
    badge: "⚡ Fast",
    color: "#10b981",
  },
  {
    id: "medium",
    name: "Balanced",
    tagline: "Standard Deliberation",
    description: "Balanced reasoning, 3 subqueries, 8 literature articles, 2 draft rounds. Recommended default for thorough scientific and engineering research.",
    icon: "Scale",
    badge: "⚖️ Balanced",
    color: "#06b6d4",
  },
  {
    id: "high",
    name: "Deep",
    tagline: "Deep Deliberation",
    description: "Multi-angle deliberation, 5 subqueries, 14 literature articles, 3 draft rounds. Recommended for complex multi-domain analysis.",
    icon: "Brain",
    badge: "🧠 Deep",
    color: "#8b5cf6",
  },
  {
    id: "ultra",
    name: "Ultra",
    tagline: "Exhaustive Frontier",
    description: "Exhaustive stress-testing, 8 subqueries, 25 literature articles, 5 draft rounds. Maximum rigor for deep derivations, simulations, and discovery hypotheses.",
    icon: "Rocket",
    badge: "🚀 Ultra",
    color: "#f59e0b",
  },
];

export const DEFAULT_AGENT_OPTIONS: AgentOptionsSettings = {
  require_plan_approval: false,
  allow_clarification: true,
  enable_counter_evidence: true,
  enable_hypotheses: true,
  enable_code_analysis: true,
  effort_level: "medium",
  budgetEnabled: false,
  budget: { max_tool_calls: 40, max_llm_calls: 30, max_seconds: 600, max_draft_rounds: 2 },
};

/** Ranges the backend validates (AgentBudgetOptions in app/backend/main.py). */
export const BUDGET_LIMITS = {
  max_tool_calls: { min: 1, max: 200, step: 1, label: "Tool calls" },
  max_llm_calls: { min: 1, max: 120, step: 1, label: "Model calls" },
  max_seconds: { min: 0, max: 7200, step: 10, label: "Wall-clock seconds (0 = no limit)" },
  max_draft_rounds: { min: 0, max: 5, step: 1, label: "Draft rounds" },
} as const;

const clamp = (v: unknown, lo: number, hi: number, fallback: number): number => {
  const n = typeof v === "number" && Number.isFinite(v) ? v : fallback;
  return Math.min(hi, Math.max(lo, Math.round(n)));
};

/** Settings read back from storage, with every field present and in range. */
export function normalizeAgentOptions(saved: unknown): AgentOptionsSettings {
  const s = (saved && typeof saved === "object" ? saved : {}) as Partial<AgentOptionsSettings>;
  const b = (s.budget && typeof s.budget === "object" ? s.budget : {}) as Partial<AgentOptionsSettings["budget"]>;
  const d = DEFAULT_AGENT_OPTIONS;
  const bool = (v: unknown, f: boolean) => (typeof v === "boolean" ? v : f);
  const validEfforts: import("@/types/agentic").EffortLevel[] = ["low", "medium", "high", "ultra"];
  const effort_level = validEfforts.includes(s.effort_level as any)
    ? (s.effort_level as import("@/types/agentic").EffortLevel)
    : d.effort_level;

  return {
    require_plan_approval: bool(s.require_plan_approval, d.require_plan_approval),
    allow_clarification: bool(s.allow_clarification, d.allow_clarification),
    enable_counter_evidence: bool(s.enable_counter_evidence, d.enable_counter_evidence),
    enable_hypotheses: bool(s.enable_hypotheses, d.enable_hypotheses),
    enable_code_analysis: bool(s.enable_code_analysis, d.enable_code_analysis),
    effort_level,
    budgetEnabled: bool(s.budgetEnabled, d.budgetEnabled),
    budget: {
      max_tool_calls: clamp(b.max_tool_calls, 1, 200, d.budget.max_tool_calls),
      max_llm_calls: clamp(b.max_llm_calls, 1, 120, d.budget.max_llm_calls),
      max_seconds: clamp(b.max_seconds, 0, 7200, d.budget.max_seconds),
      max_draft_rounds: clamp(b.max_draft_rounds, 0, 5, d.budget.max_draft_rounds),
    },
  };
}

/** The `agent_options` request field for the stored settings. */
export function toAgentOptions(s: AgentOptionsSettings): AgentOptions {
  const out: AgentOptions = {
    require_plan_approval: s.require_plan_approval,
    allow_clarification: s.allow_clarification,
    enable_counter_evidence: s.enable_counter_evidence,
    enable_code_analysis: s.enable_code_analysis,
    effort_level: s.effort_level || "medium",
  };
  // On means "when the question calls for them" (the server decides); only an explicit "off" is sent. Sending true
  // would force a hypothesis tournament on every question, a calculation included.
  if (!s.enable_hypotheses) out.enable_hypotheses = false;
  if (s.budgetEnabled) out.budget = { ...s.budget };
  return out;
}

// ---------------------------------------------------------------------------------------------------------------
// Run control (F15)
// ---------------------------------------------------------------------------------------------------------------

export function getRun(backendUrl: string, authHeaders: AuthHeaders, runId: string): Promise<RunControlState> {
  return request(`${backendUrl}/api/agent/runs/${enc(runId)}`, { headers: authHeaders() });
}

export function approveRun(backendUrl: string, authHeaders: AuthHeaders, runId: string, body: ApproveBody): Promise<unknown> {
  return request(`${backendUrl}/api/agent/runs/${enc(runId)}/approve`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify(body),
  });
}

export function steerRun(backendUrl: string, authHeaders: AuthHeaders, runId: string, message: string): Promise<unknown> {
  return request(`${backendUrl}/api/agent/runs/${enc(runId)}/steer`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify({ message }),
  });
}

/** Skips a running evidence step ("search": the literature and web search); the answer uses what was gathered. */
export function skipRunStep(backendUrl: string, authHeaders: AuthHeaders, runId: string, what = "search"): Promise<unknown> {
  return request(`${backendUrl}/api/agent/runs/${enc(runId)}/skip`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify({ what }),
  });
}

export function cancelRun(backendUrl: string, authHeaders: AuthHeaders, runId: string): Promise<unknown> {
  return request(`${backendUrl}/api/agent/runs/${enc(runId)}/cancel`, { method: "POST", headers: authHeaders() });
}

// ---------------------------------------------------------------------------------------------------------------
// Background jobs (F13)
// ---------------------------------------------------------------------------------------------------------------

export function createJob(backendUrl: string, authHeaders: AuthHeaders, body: Record<string, unknown>): Promise<CreateJobResponse> {
  return request(`${backendUrl}/api/jobs`, { method: "POST", headers: json(authHeaders), body: JSON.stringify(body) });
}

export async function listJobs(backendUrl: string, authHeaders: AuthHeaders): Promise<JobSummary[]> {
  const body = await request<unknown>(`${backendUrl}/api/jobs`, { headers: authHeaders() });
  return listFrom<JobSummary>(body, ["jobs", "items"]).filter((j) => j && typeof j.job_id === "string");
}

export function getJob(backendUrl: string, authHeaders: AuthHeaders, jobId: string, signal?: AbortSignal): Promise<JobSummary> {
  return request(`${backendUrl}/api/jobs/${enc(jobId)}`, { headers: authHeaders(), signal });
}

export function cancelJob(backendUrl: string, authHeaders: AuthHeaders, jobId: string): Promise<unknown> {
  return request(`${backendUrl}/api/jobs/${enc(jobId)}/cancel`, { method: "POST", headers: authHeaders() });
}

export function resumeJob(backendUrl: string, authHeaders: AuthHeaders, jobId: string): Promise<unknown> {
  return request(`${backendUrl}/api/jobs/${enc(jobId)}/resume`, { method: "POST", headers: authHeaders() });
}

export function deleteJob(backendUrl: string, authHeaders: AuthHeaders, jobId: string): Promise<unknown> {
  return request(`${backendUrl}/api/jobs/${enc(jobId)}`, { method: "DELETE", headers: authHeaders() });
}

export interface JobStreamOptions {
  /** Reconnect attempts after a dropped or stalled connection (reset whenever new events arrive). */
  maxReconnects?: number;
  /** First reconnect delay; doubles per consecutive failure. */
  reconnectDelayMs?: number;
  /** Stall timeout per connection (see readSseEvents). */
  stallMs?: number;
}

/** The log sequence number of a job event: the SSE `id:` line, else the event's own `seq`. */
function seqOf(ev: unknown, frame: SseFrame): number | null {
  if (frame.id && /^\d+$/.test(frame.id)) return Number(frame.id);
  const seq = ev && typeof ev === "object" ? (ev as { seq?: unknown }).seq : undefined;
  return typeof seq === "number" && Number.isFinite(seq) ? seq : null;
}

/** Some logs wrap each event as {seq, event}; unwrap so callers see the chat event shape. */
function unwrapJobEvent(ev: unknown): unknown {
  if (ev && typeof ev === "object") {
    const e = ev as { type?: unknown; event?: unknown };
    if (!e.type && e.event && typeof e.event === "object") return e.event;
  }
  return ev;
}

/**
 * A background job's terminal "error" event: the server's reason the job failed or was cancelled, with the
 * request id to quote when it failed on the server (LOG-35).
 */
export class JobFailedError extends Error {
  requestId?: string;
  cancelled: boolean;
  constructor(detail: string, options: { requestId?: string; cancelled?: boolean } = {}) {
    super(detail);
    this.name = "JobFailedError";
    this.requestId = options.requestId;
    this.cancelled = !!options.cancelled;
  }
}

function jobFailedFrom(ev: Record<string, unknown>): JobFailedError {
  const requestId = typeof ev.request_id === "string" && ev.request_id ? ev.request_id : undefined;
  const cancelled = ev.cancelled === true;
  let detail = typeof ev.detail === "string" && ev.detail.trim() ? ev.detail.trim() : cancelled ? "The job was cancelled." : "The job failed on the server.";
  if (requestId && !detail.includes(requestId)) detail = `${detail} (request id ${requestId})`;
  return new JobFailedError(detail, { requestId, cancelled });
}

/**
 * Follows a job's event log: replays events after `after`, then follows live ones until done/error.
 * Events carry the chat stream's types. onEvent returns true to stop. Resolves when the stream ends.
 *
 * A dropped or stalled connection is reopened with `after=<last seen seq>`, so no event is replayed twice
 * and none is missed. An HTTP error (401, 404, ...) is final and thrown at once.
 *
 * "error" events are not passed to onEvent. The current attempt's error is terminal: it is thrown as a
 * JobFailedError carrying the server's message once the server ends the stream. A replayed error that a later
 * "queued" job event follows belongs to an earlier attempt of a resumed job and is ignored.
 */
export async function streamJobEvents(
  backendUrl: string,
  authHeaders: AuthHeaders,
  jobId: string,
  after: number,
  onEvent: (event: unknown) => boolean | void,
  signal?: AbortSignal,
  options: JobStreamOptions = {}
): Promise<void> {
  const maxReconnects = options.maxReconnects ?? 3;
  const baseDelay = options.reconnectDelayMs ?? 1000;
  let last = Math.max(0, Math.floor(after));
  let failures = 0;
  // The latest error event; cleared when a resume starts a new attempt. Kept across reconnects.
  let failed: JobFailedError | null = null;
  for (;;) {
    let progressed = false;
    let stopped = false;
    try {
      const res = await apiFetch(`${backendUrl}/api/jobs/${enc(jobId)}/events?after=${last}`, {
        headers: authHeaders({ Accept: "text/event-stream" }),
        signal,
      });
      if (!res.body) throw new ApiError(0, "The job event stream had no body.");
      await readSseEvents(
        res.body,
        (ev, frame) => {
          const seq = seqOf(ev, frame);
          if (seq !== null && seq > last) {
            last = seq;
            progressed = true;
          }
          const event = unwrapJobEvent(ev);
          const e = (event && typeof event === "object" ? event : {}) as Record<string, unknown>;
          if (e.type === "error") {
            failed = jobFailedFrom(e);
            return false;
          }
          if (e.type === "job" && e.status === "queued") failed = null;
          if (onEvent(event)) {
            stopped = true;
            return true;
          }
          return false;
        },
        { stallMs: options.stallMs }
      );
      if (failed && !stopped) throw failed;
      // A clean end with nothing new means the job is no longer active and its log is drained.
      if (stopped || !progressed) return;
      failures = 0;
    } catch (err) {
      if (err instanceof JobFailedError) throw err;
      if (signal?.aborted || stopped) throw err;
      if (err instanceof ApiError && err.status > 0) throw err;
      if (progressed) failures = 0;
      failures += 1;
      if (failures > maxReconnects) throw err;
    }
    await delay(baseDelay * 2 ** Math.max(0, failures - 1), signal);
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Projects and project memory (F16)
// ---------------------------------------------------------------------------------------------------------------

/**
 * A project route this server does not implement (contract C1 is newer than the server): FastAPI's own 404 for an
 * unknown path ({"detail": "Not Found"}), 405 for a method the path lacks, or 501. The UI hides that part with a
 * short notice instead of an error. A project-level 404 ("Project not found") is a real answer and stays an ApiError.
 */
export class FeatureUnavailableError extends ApiError {
  feature: string;
  constructor(feature: string, cause?: unknown) {
    super(errorStatus(cause) || 501, `This server does not support ${feature} yet.`, { cause });
    this.name = "FeatureUnavailableError";
    this.feature = feature;
  }
}

/** True for an error meaning "this route does not exist on the server" (see FeatureUnavailableError). */
export function isFeatureMissing(err: unknown): boolean {
  if (err instanceof FeatureUnavailableError) return true;
  const status = errorStatus(err);
  if (status === 405 || status === 501) return true;
  if (status !== 404) return false;
  const detail = err instanceof ApiError ? err.detail.trim() : "";
  return detail === "" || detail === "Not Found";
}

/** A project request whose missing route becomes a FeatureUnavailableError naming `feature`. */
async function projectRequest<T>(feature: string, url: string, init: RequestInit): Promise<T> {
  try {
    return await request<T>(url, init);
  } catch (err) {
    if (isFeatureMissing(err)) throw new FeatureUnavailableError(feature, err);
    throw err;
  }
}

const ROLES = new Set(["owner", "editor", "viewer"]);

/** Accepts `id` or `project_id` from the API; drops a role the client does not know. */
export function normalizeProject(raw: unknown): Project | null {
  if (!raw || typeof raw !== "object") return null;
  const p = raw as Record<string, unknown>;
  const id = typeof p.id === "string" ? p.id : typeof p.project_id === "string" ? p.project_id : "";
  if (!id) return null;
  const out = { ...p, id, name: typeof p.name === "string" && p.name ? p.name : id } as Project;
  if (out.role !== undefined && !ROLES.has(String(out.role))) delete out.role;
  return out;
}

function normalizeFact(raw: unknown): MemoryFact | null {
  if (!raw || typeof raw !== "object") return null;
  const f = raw as Record<string, unknown>;
  const id = typeof f.id === "string" || typeof f.id === "number" ? String(f.id) : typeof f.fact_id === "string" ? f.fact_id : "";
  return id ? ({ ...f, id } as MemoryFact) : null;
}

function normalizeMember(raw: unknown): ProjectMember | null {
  if (!raw || typeof raw !== "object") return null;
  const m = raw as Record<string, unknown>;
  if (typeof m.user_id !== "string" || !m.user_id) return null;
  return { ...m, user_id: m.user_id, role: ROLES.has(String(m.role)) ? (m.role as ProjectRole) : "viewer" } as ProjectMember;
}

function normalizeFile(raw: unknown): ProjectFile | null {
  if (!raw || typeof raw !== "object") return null;
  const f = raw as Record<string, unknown>;
  const id = typeof f.dataset_id === "string" ? f.dataset_id : typeof f.id === "string" ? f.id : "";
  return id ? ({ ...f, dataset_id: id } as ProjectFile) : null;
}

function normalizeEvent(raw: unknown, i: number): ProjectActivityEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.action !== "string" || !e.action) return null;
  const id = typeof e.id === "string" || typeof e.id === "number" ? String(e.id) : `ev_${i}`;
  return { ...e, id, action: e.action, at: (e.at as string | number) ?? "" } as ProjectActivityEvent;
}

/** Fields of a project body that servers older than contract C1 refuse (422, extra="forbid"). */
const NEWER_PROJECT_FIELDS = ["instructions", "icon", "color"] as const;

function definedFields<T extends object>(obj: T): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as Partial<T>;
}

export async function listProjects(backendUrl: string, authHeaders: AuthHeaders): Promise<Project[]> {
  const body = await request<unknown>(`${backendUrl}/api/projects`, { headers: authHeaders() });
  return listFrom<unknown>(body, ["projects", "items"]).map(normalizeProject).filter((p): p is Project => p !== null);
}

/**
 * Creates a project. A server older than contract C1 refuses icon/colour/instructions with 422; the project is then
 * created with its name and description only and comes back marked `appearance_local` (the caller keeps the icon and
 * colour in the browser). The legacy (name, description) signature still works.
 */
export async function createProject(
  backendUrl: string,
  authHeaders: AuthHeaders,
  input: ProjectInput | string,
  description = ""
): Promise<Project> {
  const full: ProjectInput = typeof input === "string" ? { name: input, description } : input;
  const body = definedFields({ ...full, description: full.description ?? "" });
  const post = async (b: object) => {
    const res = await request<{ project?: unknown } | null>(`${backendUrl}/api/projects`, {
      method: "POST",
      headers: json(authHeaders),
      body: JSON.stringify(b),
    });
    const p = normalizeProject(res?.project ?? res);
    if (!p) throw new ApiError(0, "The server did not return the new project.");
    return p;
  };
  try {
    return await post(body);
  } catch (err) {
    const newer = NEWER_PROJECT_FIELDS.filter((k) => body[k] !== undefined && body[k] !== "");
    if (errorStatus(err) !== 422 || !newer.length) throw err;
    const p = await post({ name: body.name, description: body.description ?? "" });
    return { ...p, icon: p.icon ?? full.icon, color: p.color ?? full.color, appearance_local: true };
  }
}

export async function getProject(backendUrl: string, authHeaders: AuthHeaders, projectId: string): Promise<Project | null> {
  const body = await request<{ project?: unknown } | null>(`${backendUrl}/api/projects/${enc(projectId)}`, { headers: authHeaders() });
  return normalizeProject(body?.project ?? body);
}

/**
 * PATCH /api/projects/{id} (owner or editor). On a server older than contract C1, icon and colour fall back to the
 * browser (the result is marked `appearance_local`) and instructions raise FeatureUnavailableError.
 */
export async function patchProject(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  patch: ProjectPatchInput
): Promise<Project | null> {
  const body = definedFields(patch);
  const send = async (b: object) => {
    const res = await request<{ project?: unknown } | null>(`${backendUrl}/api/projects/${enc(projectId)}`, {
      method: "PATCH",
      headers: json(authHeaders),
      body: JSON.stringify(b),
    });
    return normalizeProject(res?.project ?? res);
  };
  try {
    return await send(body);
  } catch (err) {
    const newer = NEWER_PROJECT_FIELDS.filter((k) => body[k] !== undefined);
    if (errorStatus(err) !== 422 || !newer.length) throw err;
    if (body.instructions !== undefined) throw new FeatureUnavailableError("project instructions", err);
    const legacy = definedFields({ name: body.name, description: body.description });
    const p = Object.keys(legacy).length ? await send(legacy) : null;
    return {
      ...(p ?? { id: projectId, name: body.name ?? projectId }),
      icon: body.icon ?? p?.icon,
      color: body.color ?? p?.color,
      appearance_local: true,
    };
  }
}

export function deleteProject(backendUrl: string, authHeaders: AuthHeaders, projectId: string): Promise<unknown> {
  return request(`${backendUrl}/api/projects/${enc(projectId)}`, { method: "DELETE", headers: authHeaders() });
}

// Members (the owner manages them; a member may remove themself to leave)

export async function listProjectMembers(backendUrl: string, authHeaders: AuthHeaders, projectId: string): Promise<ProjectMember[]> {
  const body = await projectRequest<unknown>("project members", `${backendUrl}/api/projects/${enc(projectId)}/members`, {
    headers: authHeaders(),
  });
  return listFrom<unknown>(body, ["members", "items"]).map(normalizeMember).filter((m): m is ProjectMember => m !== null);
}

export function addProjectMember(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  userId: string,
  role: Exclude<ProjectRole, "owner">
): Promise<unknown> {
  return projectRequest("project members", `${backendUrl}/api/projects/${enc(projectId)}/members`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify({ user_id: userId, role }),
  });
}

export function updateProjectMemberRole(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  userId: string,
  role: Exclude<ProjectRole, "owner">
): Promise<unknown> {
  return projectRequest("project members", `${backendUrl}/api/projects/${enc(projectId)}/members/${enc(userId)}`, {
    method: "PATCH",
    headers: json(authHeaders),
    body: JSON.stringify({ role }),
  });
}

export function removeProjectMember(backendUrl: string, authHeaders: AuthHeaders, projectId: string, userId: string): Promise<unknown> {
  return projectRequest("project members", `${backendUrl}/api/projects/${enc(projectId)}/members/${enc(userId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// Files (datasets of the caller's library, attached to every run in the project)

export async function listProjectFiles(backendUrl: string, authHeaders: AuthHeaders, projectId: string): Promise<ProjectFile[]> {
  const body = await projectRequest<unknown>("project files", `${backendUrl}/api/projects/${enc(projectId)}/files`, {
    headers: authHeaders(),
  });
  return listFrom<unknown>(body, ["files", "items"]).map(normalizeFile).filter((f): f is ProjectFile => f !== null);
}

export function addProjectFile(backendUrl: string, authHeaders: AuthHeaders, projectId: string, datasetId: string): Promise<unknown> {
  return projectRequest("project files", `${backendUrl}/api/projects/${enc(projectId)}/files`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}

export function removeProjectFile(backendUrl: string, authHeaders: AuthHeaders, projectId: string, datasetId: string): Promise<unknown> {
  return projectRequest("project files", `${backendUrl}/api/projects/${enc(projectId)}/files/${enc(datasetId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// Memory (facts and their review)

export interface ProjectMemoryOptions {
  reviewStatus?: FactReviewStatus;
  includeInvalid?: boolean;
  limit?: number;
}

export async function getProjectMemory(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  query = "",
  options: ProjectMemoryOptions = {}
): Promise<MemoryFact[]> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("query", query.trim());
  if (options.reviewStatus) params.set("review_status", options.reviewStatus);
  if (options.includeInvalid) params.set("include_invalid", "true");
  if (options.limit) params.set("limit", String(options.limit));
  const q = params.toString() ? `?${params}` : "";
  const body = await request<unknown>(`${backendUrl}/api/projects/${enc(projectId)}/memory${q}`, { headers: authHeaders() });
  const facts = listFrom<unknown>(body, ["facts", "items", "memory", "recalled"])
    .map(normalizeFact)
    .filter((f): f is MemoryFact => f !== null);
  // A server without the review filter ignores it: drop the facts whose explicit status differs.
  return options.reviewStatus ? facts.filter((f) => !f.review_status || f.review_status === options.reviewStatus) : facts;
}

export async function addFact(backendUrl: string, authHeaders: AuthHeaders, projectId: string, fact: NewFactInput): Promise<MemoryFact | null> {
  const body = await projectRequest<unknown>("adding facts", `${backendUrl}/api/projects/${enc(projectId)}/memory`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify(definedFields(fact)),
  });
  return normalizeFact((body as { fact?: unknown } | null)?.fact ?? body);
}

/** Approve (verified by the reviewer) or reject (invalidated) a fact; owner or editor. */
export async function reviewFact(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  factId: string,
  decision: "approve" | "reject",
  note?: string
): Promise<MemoryFact | null> {
  const body = await projectRequest<unknown>("fact review", `${backendUrl}/api/projects/${enc(projectId)}/memory/${enc(factId)}/review`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify(definedFields({ decision, note: note?.trim() || undefined })),
  });
  return normalizeFact((body as { fact?: unknown } | null)?.fact ?? body);
}

/** Every version of a fact, oldest first. */
export async function getFactHistory(backendUrl: string, authHeaders: AuthHeaders, projectId: string, factId: string): Promise<MemoryFact[]> {
  const body = await projectRequest<unknown>("fact history", `${backendUrl}/api/projects/${enc(projectId)}/memory/${enc(factId)}/history`, {
    headers: authHeaders(),
  });
  return listFrom<unknown>(body, ["versions", "history", "items"]).map(normalizeFact).filter((f): f is MemoryFact => f !== null);
}

/** PATCH /api/projects/{id}/memory/{fact_id}; the server rejects unknown fields. */
export interface FactPatch {
  invalidate?: boolean;
  reason?: string;
  object?: string;
  confidence?: number;
}

export function patchFact(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  factId: string,
  // The server field is `invalidate` (FactPatch in app/backend/routers/projects.py), with an optional reason (BRK-8).
  patch: FactPatch
): Promise<unknown> {
  return request(`${backendUrl}/api/projects/${enc(projectId)}/memory/${enc(factId)}`, {
    method: "PATCH",
    headers: json(authHeaders),
    body: JSON.stringify(patch),
  });
}

export function deleteFact(backendUrl: string, authHeaders: AuthHeaders, projectId: string, factId: string): Promise<unknown> {
  return request(`${backendUrl}/api/projects/${enc(projectId)}/memory/${enc(factId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// Activity

export async function getProjectActivity(
  backendUrl: string,
  authHeaders: AuthHeaders,
  projectId: string,
  limit = 50
): Promise<ProjectActivityEvent[]> {
  const body = await projectRequest<unknown>("project activity", `${backendUrl}/api/projects/${enc(projectId)}/activity?limit=${limit}`, {
    headers: authHeaders(),
  });
  return listFrom<unknown>(body, ["events", "items", "activity"])
    .map(normalizeEvent)
    .filter((e): e is ProjectActivityEvent => e !== null);
}

export interface TitleResponse {
  title: string;
  method: "ai" | "heuristic";
}

/**
 * Asks the backend for a short conversation title (a model call, or its heuristic when the model fails).
 * The caller keeps the instant local title when this request fails.
 */
export function fetchConversationTitle(
  backendUrl: string,
  authHeaders: AuthHeaders,
  message: string,
  model?: string,
  apiKey?: string,
  signal?: AbortSignal
): Promise<TitleResponse> {
  return request<TitleResponse>(`${backendUrl}/api/chat/title`, {
    method: "POST",
    headers: json(authHeaders),
    body: JSON.stringify({
      message,
      model: model || undefined,
      api_key: apiKey || undefined,
    }),
    signal,
  });
}

