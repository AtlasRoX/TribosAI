// Long-running research projects (GET/POST /api/campaigns): a goal worked through review -> hypotheses ->
// experiments -> analysis -> report, each stage one background job.

import { requestJson, apiFetch, jsonInit, type AuthHeaders } from "./apiClient.ts";

export type CampaignStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
export type StageStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";

export interface CampaignStage {
  key: string;
  title: string;
  status: StageStatus;
  job_id: string | null;
  started_at: number | null;
  finished_at: number | null;
  response?: string;
  error: string | null;
  attempts: number;
  /** Continued rounds: the stage kind (`experiments`), its round (2, 3, …) and the follow-up instruction. */
  base?: string;
  round?: number;
  instruction?: string;
}

export interface Campaign {
  campaign_id: string;
  goal: string;
  title: string;
  status: CampaignStatus;
  model: string | null;
  effort_level: string;
  thread_id: string;
  created_at: number;
  updated_at: number;
  finished_at: number | null;
  error: string | null;
  current_stage: string | null;
  /** "Queued: …", "Resumed automatically after a server restart.", … */
  note?: string | null;
  auto_resumes?: number;
  /** Classic projects: the number of rounds. Loop projects: the round records (see ResearchRound). */
  rounds?: number | ResearchRound[];
  stages: CampaignStage[];
  /** "loop": the adaptive research loop (charter, rounds until a conclusion, thesis); absent or "stages": classic. */
  mode?: "loop" | "stages";
  loop?: ResearchLoopState;
  review?: { status: string; response?: string; error?: string | null };
  charter?: ResearchCharter | null;
  ledger?: Finding[];
  thesis?: ThesisMeta;
  dashboard?: ResearchDashboard;
  estimate?: ResearchEstimate;
  activity?: { t: number; text: string; ref?: string | null }[];
  /** List view of a loop project (the full records are left out). */
  summary?: { deliverables: number; done: number; tests: number; findings: number; rounds: number; phase?: string };
}

export type Tier = "formal" | "certified" | "replicated" | "computed" | "sourced" | "reasoned" | "none";

export interface ResearchLoopState {
  phase: "review" | "charter" | "testing" | "judging" | "thesis" | "done" | string;
  stop_reason: string | null;
  instructions?: string[];
  test_runs?: number;
  started_at?: number;
  /** Seconds the loop has actually run (paused periods excluded). */
  active_s?: number;
}

export interface Deliverable { id: string; title: string; acceptance: string; tier: Tier; status: string; evidence: string[]; note?: string }
export interface Hypothesis { id: string; statement: string; falsification: string; verdict: string; evidence: string[]; note?: string }
export interface ResearchTest {
  id: string; title: string; kind: string; objective: string; method?: string; acceptance?: string; quantities: string[];
  serves: string[]; hypotheses: string[]; depends_on: string[]; cost: string; tier: Tier; status: string; attempts: number;
  round_added: number; last_error?: string | null; finding_ids: string[];
}
export interface ResearchCharter {
  summary: string; deliverables: Deliverable[]; hypotheses: Hypothesis[]; tests: ResearchTest[];
  revisions?: { round: number; added: string[]; reason: string }[];
}

export interface Finding {
  id: string; test_id: string; kind?: string; status: string; tier: Tier; round?: number; summary?: string;
  quantities?: { name: string; value: unknown }[];
  series?: { name: string; x: number[]; y: number[]; x_label?: string; y_label?: string }[];
  cells?: { code: string; stdout: string; status: string; error?: string; seconds?: number }[];
  figures?: { name: string; title?: string }[];
  checks?: { name: string; passed: boolean; detail?: string }[];
  replication?: { status: string; agree: number; disagree: number; missing: number; code?: string } | null;
  proof?: { statement: string; text?: string; lean_status?: string; lean_code?: string; lean_error?: string | null };
  error?: string | null; seconds?: number;
}

export interface ResearchRound {
  round: number; started_at?: number; finished_at?: number; seconds?: number; tests: string[]; analysis?: string;
  progress?: boolean; concluded?: boolean; headline?: string; added_tests?: string[];
}

export interface ThesisMeta {
  status: string; title?: string; chapters?: { key: string; title: string }[]; figures?: { n: number; file: string; caption: string }[];
  unverified?: string[]; references?: number; written_at?: number; error?: string;
}

export interface ResearchDashboard {
  version: number;
  project: unknown[];
  findings: { id: string; test_id: string; status: string; tier: Tier; tier_label: string; blocks: unknown[] }[];
}

export interface ResearchEstimate {
  remaining_s: number; low_s: number; high_s: number; basis: string; rough?: boolean; updated_at?: number;
  pending_tests?: number; open_deliverables?: number;
}

export interface NewCampaign {
  goal: string;
  model?: string;
  effort_level?: "low" | "medium" | "high";
  stages?: string[];
  enable_web_search?: boolean;
  mode?: "loop" | "stages";
}

export const STAGE_INFO: { key: string; title: string; hint: string }[] = [
  { key: "review", title: "Literature review", hint: "What is known, with sources" },
  { key: "hypotheses", title: "Hypotheses", hint: "Testable ideas and how to test them" },
  { key: "experiments", title: "Experiments", hint: "Compute, simulate or prove" },
  { key: "analysis", title: "Analysis", hint: "What the results do and don't show" },
  { key: "report", title: "Report", hint: "A short paper of the whole project" },
];

const enc = encodeURIComponent;

export function isActive(c: Pick<Campaign, "status">): boolean {
  return c.status === "queued" || c.status === "running";
}

export async function listCampaigns(backendUrl: string, authHeaders: AuthHeaders): Promise<Campaign[]> {
  const body = await requestJson<{ campaigns?: Campaign[] }>(`${backendUrl}/api/campaigns`, { headers: authHeaders() });
  return Array.isArray(body?.campaigns) ? body.campaigns : [];
}

export function getCampaign(backendUrl: string, authHeaders: AuthHeaders, id: string, signal?: AbortSignal): Promise<Campaign> {
  return requestJson<Campaign>(`${backendUrl}/api/campaigns/${enc(id)}`, { headers: authHeaders(), signal });
}

export function createCampaign(backendUrl: string, authHeaders: AuthHeaders, body: NewCampaign): Promise<Campaign> {
  return requestJson<Campaign>(`${backendUrl}/api/campaigns`, jsonInit("POST", body, authHeaders));
}

export function cancelCampaign(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<Campaign> {
  return requestJson<Campaign>(`${backendUrl}/api/campaigns/${enc(id)}/cancel`, { method: "POST", headers: authHeaders() });
}

export function resumeCampaign(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<Campaign> {
  return requestJson<Campaign>(`${backendUrl}/api/campaigns/${enc(id)}/resume`, { method: "POST", headers: authHeaders() });
}

export function deleteCampaign(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<unknown> {
  return requestJson(`${backendUrl}/api/campaigns/${enc(id)}`, { method: "DELETE", headers: authHeaders() });
}

export async function fetchReport(backendUrl: string, authHeaders: AuthHeaders, id: string): Promise<string> {
  const res = await apiFetch(`${backendUrl}/api/campaigns/${enc(id)}/report`, { headers: authHeaders() });
  return res.text();
}

export function continueCampaign(
  backendUrl: string, authHeaders: AuthHeaders, id: string, instruction: string, stages?: string[],
): Promise<Campaign> {
  return requestJson<Campaign>(`${backendUrl}/api/campaigns/${enc(id)}/continue`,
    jsonInit("POST", { instruction, ...(stages?.length ? { stages } : {}) }, authHeaders));
}

export interface ActivityStep {
  id: string;
  title: string;
  status: string;
}

/**
 * The activity steps ("Searching PubMed", "Python cell 2: ok") a running stage's job reported after `after`; a step
 * re-emitted with the same id is an update. `lastSeq` is where the next call continues.
 */
export async function stageActivity(
  backendUrl: string, authHeaders: AuthHeaders, jobId: string, after = 0, signal?: AbortSignal,
): Promise<{ steps: ActivityStep[]; lastSeq: number }> {
  const body = await requestJson<{
    events?: { type?: string; data?: { id?: string; title?: string; status?: string } }[]; last_seq?: number;
  }>(`${backendUrl}/api/jobs/${enc(jobId)}/events?stream=false&after=${after}&limit=2000`, { headers: authHeaders(), signal });
  const steps: ActivityStep[] = [];
  for (const e of body?.events ?? []) {
    if (e?.type === "thought" && e.data?.title) {
      steps.push({ id: e.data.id || e.data.title, title: e.data.title, status: e.data.status || "done" });
    }
  }
  return { steps, lastSeq: typeof body?.last_seq === "number" ? body.last_seq : after };
}

export type ThesisFormat = "pdf" | "docx" | "md" | "html" | "bundle";

/** The research thesis in one format, as a Blob plus its download name. */
export async function fetchThesis(
  backendUrl: string, authHeaders: AuthHeaders, id: string, format: ThesisFormat,
): Promise<{ blob: Blob; filename: string }> {
  const res = await apiFetch(`${backendUrl}/api/campaigns/${enc(id)}/thesis?format=${format}`, { headers: authHeaders() });
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename="([^"]+)"/.exec(cd);
  return { blob: await res.blob(), filename: m ? m[1] : `${id}.${format === "bundle" ? "zip" : format}` };
}

/** A figure the project produced (fetched with the auth headers, shown through a blob URL). */
export async function fetchProjectFile(
  backendUrl: string, authHeaders: AuthHeaders, id: string, name: string, signal?: AbortSignal,
): Promise<Blob> {
  const res = await apiFetch(`${backendUrl}/api/campaigns/${enc(id)}/files/${enc(name)}`, { headers: authHeaders(), signal });
  return res.blob();
}

/** A rough duration for a goal before the project starts. */
export function estimateGoal(backendUrl: string, authHeaders: AuthHeaders, goal: string, signal?: AbortSignal): Promise<ResearchEstimate> {
  return requestJson<ResearchEstimate>(`${backendUrl}/api/campaigns/estimate`, jsonInit("POST", { goal }, authHeaders, { signal }));
}

/** Seconds as "45 s", "12 min", "1 h 05 min". */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** Deliverables settled (done or shown infeasible) of a loop project, from the full record or the list summary. */
export function loopProgress(c: Campaign): { done: number; total: number } {
  if (c.charter) {
    const ds = c.charter.deliverables;
    return { done: ds.filter((d) => d.status === "done" || d.status === "infeasible").length, total: ds.length };
  }
  return { done: c.summary?.done ?? 0, total: c.summary?.deliverables ?? 0 };
}

export const TIER_LABEL: Record<string, string> = {
  formal: "Lean-verified", certified: "Certified", replicated: "Replicated", computed: "Computed", sourced: "Sourced",
  reasoned: "Argued", none: "Unverified",
};

/** The stage kind of a stage record (a continued round's key is `kind@round`). */
export function stageBase(s: Pick<CampaignStage, "key" | "base">): string {
  return (s.base || s.key).split("@")[0];
}

/** Where a research project lives in the app: /research/<id>. */
export function researchPath(id?: string | null): string {
  return id ? `/research/${enc(id)}` : "/research";
}
