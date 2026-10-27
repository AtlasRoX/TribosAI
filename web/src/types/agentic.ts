// Types for the agentic system (docs/plans/agentic-system.md §3 artifact contracts, §2 F13/F15/F16 routes).
// Every field is optional: cards must render whatever subset the backend sends.

// ---------------------------------------------------------------------------------------------------------------
// Frameworks
// ---------------------------------------------------------------------------------------------------------------

export type FrameworkId =
  | "auto"
  | "authoritative-react-compiler"
  | "agentic-plan-execute"
  | "multi-agent-supervisor"
  | "multi-agent-swarm"
  | "multi-agent-debate";

export interface FrameworkInfo {
  id: string;
  description?: string;
  agentic?: boolean;
}

export interface FrameworksResponse {
  default?: string;
  frameworks?: FrameworkInfo[];
}

// ---------------------------------------------------------------------------------------------------------------
// Effort Levels & Thinking Engine
// ---------------------------------------------------------------------------------------------------------------

export type EffortLevel = "low" | "medium" | "high" | "ultra";

export interface EffortProfileInfo {
  level: EffortLevel;
  name: string;
  tagline: string;
  description: string;
  reasoning_effort: string;
  thinking_budget_tokens: number;
  max_subqueries: number;
  max_passages: number;
  max_draft_rounds: number;
  max_tool_calls: number;
  max_llm_calls: number;
  max_seconds: number;
  enable_thinking: boolean;
  deliberation_depth: string;
  icon: string;
}

export interface EffortLevelsResponse {
  default: EffortLevel;
  levels: EffortProfileInfo[];
}

// ---------------------------------------------------------------------------------------------------------------
// Request options (ChatRequest.agent_options in app/backend/main.py)
// ---------------------------------------------------------------------------------------------------------------

export interface AgentBudgetOptions {
  max_tool_calls?: number; // 1..200
  max_llm_calls?: number; // 1..120
  max_tokens?: number; // 1000..2,000,000
  max_seconds?: number; // 0 (no limit)..7200
  max_draft_rounds?: number; // 0..5
}

export interface AgentOptions {
  require_plan_approval?: boolean;
  allow_clarification?: boolean;
  enable_counter_evidence?: boolean;
  enable_hypotheses?: boolean;
  enable_code_analysis?: boolean;
  effort_level?: EffortLevel;
  budget?: AgentBudgetOptions;
}

/** What the settings panel stores; `budgetEnabled` off means "use the server's limits". */
export interface AgentOptionsSettings {
  require_plan_approval: boolean;
  allow_clarification: boolean;
  enable_counter_evidence: boolean;
  enable_hypotheses: boolean;
  enable_code_analysis: boolean;
  effort_level: EffortLevel;
  budgetEnabled: boolean;
  budget: Required<Pick<AgentBudgetOptions, "max_tool_calls" | "max_llm_calls" | "max_seconds" | "max_draft_rounds">>;
}

// ---------------------------------------------------------------------------------------------------------------
// SSE events added by the agentic runtime
// ---------------------------------------------------------------------------------------------------------------

export interface RunControlEvent {
  type: "run_control";
  run_id: string;
  framework?: string;
  interactive?: boolean;
}

export interface ApprovalSource {
  key: string;
  label?: string;
  run?: boolean;
  reason?: string;
}

export interface ApprovalRequestEvent {
  type: "approval_request";
  run_id: string;
  approval_id: string;
  kind: "plan" | "dag" | string;
  payload?: { sources?: ApprovalSource[]; nodes?: PlanNode[]; [k: string]: any };
}

/** An approval request as held by the UI, with the time it arrived (for the 5-minute auto-continue note). */
export interface PendingApproval extends ApprovalRequestEvent {
  received_at: number;
}

// ---------------------------------------------------------------------------------------------------------------
// Run control routes (/api/agent/runs/{run_id})
// ---------------------------------------------------------------------------------------------------------------

export interface RunControlState {
  run_id: string;
  interactive?: boolean;
  cancelled?: boolean;
  pending?: { approval_id: string; kind: string; payload?: any; created?: number }[];
  decisions?: Record<string, any>[];
  queued_steering?: number;
}

export interface ApproveBody {
  approval_id: string;
  approved: boolean;
  payload?: Record<string, any>;
  message?: string;
}

// ---------------------------------------------------------------------------------------------------------------
// Jobs (F13)
// ---------------------------------------------------------------------------------------------------------------

export type JobStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted"
  | string;

export interface JobSummary {
  job_id: string;
  run_id?: string;
  status?: JobStatus;
  created?: string | number;
  updated?: string | number;
  created_at?: string | number;
  updated_at?: string | number;
  /**
   * The stored request. `message` includes the transcriptions of attached images; `display_message` (newer servers)
   * is the text the user typed.
   */
  request?: { message?: string; display_message?: string; framework?: string; thread_id?: string; model?: string; [k: string]: unknown };
  message?: string;
  title?: string;
  error?: string;
  result?: any;
  [k: string]: any;
}

export interface CreateJobResponse {
  job_id: string;
  run_id?: string;
  /** True when the server already had a job for this client_request_id and returned it instead of a new one. */
  duplicate?: boolean;
}

// ---------------------------------------------------------------------------------------------------------------
// Projects (F16)
// ---------------------------------------------------------------------------------------------------------------

/** The caller's role in a project (contract C1). */
export type ProjectRole = "owner" | "editor" | "viewer";

/** A project as GET /api/projects returns it (contract C1); older servers send only id, name, description, counts. */
export interface Project {
  id: string;
  name: string;
  description?: string;
  /** Added to the context of every chat in the project. */
  instructions?: string;
  /** An emoji. */
  icon?: string;
  /** A CSS colour (#rrggbb). */
  color?: string;
  owner_id?: string;
  role?: ProjectRole;
  member_count?: number;
  fact_count?: number;
  invalid_fact_count?: number;
  pending_review_count?: number;
  file_count?: number;
  created_at?: string | number;
  updated_at?: string | number;
  created?: string | number;
  updated?: string | number;
  [k: string]: any;
}

/** POST /api/projects body; PATCH takes any subset. */
export interface ProjectInput {
  name: string;
  description?: string;
  instructions?: string;
  icon?: string;
  color?: string;
}

export type ProjectPatchInput = Partial<ProjectInput>;

export interface ProjectMember {
  user_id: string;
  role: ProjectRole;
  added_at?: string | number;
  added_by?: string;
}

export interface ProjectFile {
  dataset_id: string;
  name?: string;
  kind?: string;
  size_bytes?: number;
  added_at?: string | number;
  added_by?: string;
}

export type ProjectActivityAction =
  | "project.created"
  | "project.updated"
  | "member.added"
  | "member.removed"
  | "member.role_changed"
  | "file.added"
  | "file.removed"
  | "fact.added"
  | "fact.edited"
  | "fact.invalidated"
  | "fact.approved"
  | "fact.rejected"
  | "fact.deleted"
  | "run.completed";

export interface ProjectActivityEvent {
  id: string;
  at: string | number;
  actor?: string;
  action: ProjectActivityAction | string;
  target_type?: string;
  target_id?: string;
  summary?: string;
}

/** Review state of a project fact: facts written by runs start "pending". */
export type FactReviewStatus = "pending" | "approved" | "rejected";

export interface MemoryFact {
  id: string;
  subject?: string;
  relation?: string;
  object?: string;
  valid_from?: string | number | null;
  invalid_at?: string | number | null;
  recorded_at?: string | number | null;
  /** Where the fact came from: {tool, run_id, thread_id, ...} for a run, {origin, ...} for a member. */
  source?: string | Record<string, unknown>;
  confidence?: number;
  invalid?: boolean;
  value?: string | null;
  verified?: boolean;
  superseded_by?: string | null;
  invalidation_reason?: string | null;
  /** The member (or the run's user) who wrote the fact. */
  written_by?: string;
  tags?: string[];
  review_status?: FactReviewStatus;
  reviewed_by?: string | null;
  reviewed_at?: string | number | null;
  review_note?: string | null;
  [k: string]: any;
}

/** POST /api/projects/{id}/memory body. */
export interface NewFactInput {
  subject: string;
  relation: string;
  object: string;
  confidence?: number;
  note?: string;
}

// ---------------------------------------------------------------------------------------------------------------
// §3 artifacts
// ---------------------------------------------------------------------------------------------------------------

export interface SubQuestion {
  id?: string;
  text?: string;
  focus?: string;
  depends_on?: string[];
  status?: "pending" | "answered" | "partial" | "missing" | "open" | string;
  answer_state?: "open" | "answered" | "partial" | "missing" | string;
  check_state?: "checked" | "supported_by_retrieval" | "unverified" | "failed" | string;
  evidence_keys?: string[];
  evidence_labels?: string[];
  note?: string;
}

export interface AgentBudgetState {
  /** Backend budget.to_dict() uses unprefixed keys (tool_calls, llm_calls, tokens, seconds, draft_rounds, plan_nodes). */
  limits?: Record<string, number | null | undefined>;
  used?: { tool_calls?: number; llm_calls?: number; tokens_estimated?: number; seconds?: number; [k: string]: number | undefined };
  exhausted?: boolean;
  exhausted_reason?: string | null;
  by_phase?: Record<string, any>;
}

export interface AgentTraceRow {
  phase?: string;
  tool?: string;
  purpose?: string;
  success?: boolean;
  error_type?: string | null;
  seconds?: number;
}

export interface AgentPhaseRow {
  phase?: string;
  stage?: string;
  status?: string;
  seconds?: number;
}

export interface AgentRunArtifact {
  framework?: string;
  run_id?: string;
  sub_questions?: SubQuestion[];
  budget?: AgentBudgetState;
  trace?: AgentTraceRow[];
  decisions?: Record<string, any>[];
  steering?: (string | Record<string, any>)[];
  phases?: AgentPhaseRow[];
  draft_rounds?: number;
}

export interface PlanNode {
  id: string;
  tool?: string;
  args?: Record<string, any>;
  depends_on?: string[];
  purpose?: string;
  status?: "done" | "error" | "skipped" | "pending" | "running" | string;
  result_key?: string;
  error?: string;
  seconds?: number;
  run?: boolean;
}

export interface AgentPlanArtifact {
  planner?: "llm" | "none" | string;
  rationale?: string;
  replans?: number;
  nodes?: PlanNode[];
  rejected?: { node?: string | PlanNode; reason?: string }[];
}

export interface ClarificationArtifact {
  question?: string;
  options?: string[];
  reason?: string;
  signals?: string[];
}

export interface PlanApprovalArtifact {
  approval_id?: string;
  status?: "approved" | "edited" | "rejected" | "auto" | "timeout" | string;
  sources?: ApprovalSource[];
}

export interface Hypothesis {
  id?: string;
  statement?: string;
  mechanism?: string;
  intervention?: { kind?: string; parameter?: string; factor?: number };
  readout?: string;
  prediction?: "increase" | "decrease" | string;
  result?: {
    baseline?: number | null;
    perturbed?: number | null;
    /** (perturbed - baseline) / |baseline|. */
    relative_change?: number | null;
    /** The readout the change was measured on, e.g. "final value" or "peak". */
    metric?: string | null;
    monotonic?: boolean | null;
    /** Only when both values are positive. */
    log2_fold_change?: number | null;
    supports?: boolean | null;
  } | null;
  elo?: number;
  rank?: number;
  evidence_keys?: string[];
}

export interface HypothesesArtifact {
  target?: string;
  model_id?: string | null;
  method?: string;
  experiments_run?: number;
  /** Minimum |relative change| in the predicted direction for "supported" (e.g. 0.05 = 5 %). */
  threshold_relative_change?: number | null;
  hypotheses?: Hypothesis[];
  note?: string;
}

export interface EvidenceConflict {
  claim?: string;
  passage?: string;
  source_key?: string;
  pmid?: string | number | null;
  doi?: string | null;
  label?: "contradicts" | "supports" | "neutral" | string;
  likert?: number | null;
  score?: number | null;
}

export interface EvidenceConflictsArtifact {
  queries?: string[];
  claims_checked?: number;
  classifier?: "nli" | "llm" | "heuristic" | string;
  conflicts?: EvidenceConflict[];
  /** Rows about claims the final answer no longer makes (audit I40): history, not findings about the answer. */
  history?: EvidenceConflict[];
  history_note?: string;
}

export interface ClaimConfidenceRow {
  claim_id?: string;
  text?: string;
  confidence?: number;
  band?: "high" | "medium" | "low" | string;
  features?: Record<string, any>;
  nli_label?: string | null;
}

export interface ClaimConfidenceArtifact {
  answer_confidence?: number;
  method?: string;
  calibration?: { temperature?: number | null; conformal_threshold?: number | null; [k: string]: any };
  claims?: ClaimConfidenceRow[];
}

export interface SandboxTable {
  name?: string;
  columns?: string[];
  rows?: any[][] | Record<string, any>[];
}

/** One check of the mathematics agent's independent verifier (level 0 execution, 1 semantic alignment, 2 independent). */
export interface MathCheck {
  name: string;
  passed: boolean | null;
  level: number;
  detail?: string;
}

export interface MathAgentStep {
  index: number;
  tool: string;
  policy: string;
  strategy_name?: string;
  arguments?: Record<string, any>;
  rationale?: string;
  status: "ok" | "error";
  failure: string;
  error?: string;
  seconds?: number;
  cached?: boolean;
  output?: Record<string, any>;
  verdict?: { status: string; checks?: MathCheck[] } | null;
}

/** Verified mathematics agent run (tribos/axiom/agent.py). */
export interface MathAgentArtifact {
  status: "verified" | "partially_verified" | "unverified" | "failed";
  answer?: { text?: string; latex?: string; [k: string]: any };
  verification?: { status: string; level: number; checks?: MathCheck[]; uncertainty?: string[] } | null;
  uncertainty?: string[];
  /** Empirical P(correct | status) on the held-out benchmark; absent when no answer was given. */
  confidence?: { p_correct: number; lower_95: number; n: number; fitted_on?: string } | null;
  problem?: { text?: string; kind?: string; [k: string]: any };
  steps?: MathAgentStep[];
  metrics?: Record<string, any>;
}

export interface SandboxAnalysisArtifact {
  status?: "ok" | "error" | "disabled" | string;
  iterations?: number;
  code?: string;
  stdout?: string;
  result?: any;
  error?: string | null;
  dataset?: string | Record<string, any> | null;
  figures?: { name?: string; png_base64?: string }[];
  tables?: SandboxTable[];
  policy?: { timeout_s?: number; network?: string; isolation?: string; [k: string]: any };
}

export type Identifiability = "identifiable" | "practically_non_identifiable" | "structurally_non_identifiable" | string;

export interface CalibrationParameter {
  name?: string;
  initial?: number | null;
  estimate?: number | null;
  std_error?: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  identifiability?: Identifiability;
}

export interface ModelCalibrationArtifact {
  model_id?: string;
  dataset?: string | Record<string, any> | null;
  backend?: string;
  status?: string;
  warnings?: string[];
  reason?: string;
  ci_method?: string;
  correlation_matrix?: number[][];
  correlation_labels?: string[];
  objective?: { chi2?: number | null; rmse?: number | null; n_points?: number | null; rss?: number; aic?: number; bic?: number };
  metrics?: Record<string, { rss: number; rmse: number; r_squared: number }>;
  parameters?: CalibrationParameter[];
  profiles?: Record<string, { value?: number; chi2?: number }[]>;
  fit?: Record<string, { time?: number[]; observed?: (number | null)[]; simulated?: (number | null)[] }>;
}

export interface ProjectMemoryArtifact {
  project_id?: string;
  recalled?: MemoryFact[];
  written?: number;
  invalidated?: number;
}

export interface AgentDialogueTurn {
  agent?: string;
  action?: string;
  tool?: string | null;
  summary?: string;
  round?: number;
}

export interface AgentDialogueArtifact {
  topology?: string;
  turns?: AgentDialogueTurn[];
}

/** The agentic keys added to ExecutionArtifacts. */
/** Auto routing: which architecture was chosen for the question and why (tribos/agentic/router.py). */
export interface FrameworkRoutingArtifact {
  requested: "auto";
  chosen: FrameworkId;
  label?: string;
  /** The scored approach: "direct" runs the plan-and-execute framework without its planner. */
  approach?: string;
  rule?: string;
  reason?: string;
  signals?: Record<string, unknown>;
  candidates?: FrameworkId[];
  tie_break?: "none" | "llm" | "llm_failed";
  /** Probability of the chosen architecture (softmax over the scores). */
  confidence?: number;
  probabilities?: Partial<Record<FrameworkId | "direct", number>>;
  /** The factors behind the chosen score, strongest first (weight = contribution to the score). */
  factors?: { factor: string; label: string; weight: number }[];
  features?: Record<string, number>;
  semantic?: { used: boolean; samples?: number; valid_samples?: number; question_kind?: string | null };
  /** Score nudges from past outcomes on similar questions. */
  learned?: Partial<Record<FrameworkId, { delta: number; runs: number; quality: number }>>;
  guardrail?: string | null;
  bucket?: string;
  escalation?: { to: FrameworkId; triggers: string[]; status: "escalated" | "skipped"; reason?: string } | null;
  /** The scores are heuristic suitability, not calibrated probabilities. */
  scores_note?: string;
  /** Extra cost of the chosen architecture (Debate: critic rounds and rewrites). */
  cost_note?: string;
}

export interface AgenticArtifacts {
  agent_run?: AgentRunArtifact;
  framework_routing?: FrameworkRoutingArtifact;
  agent_plan?: AgentPlanArtifact;
  clarification?: ClarificationArtifact;
  plan_approval?: PlanApprovalArtifact;
  hypotheses?: HypothesesArtifact;
  evidence_conflicts?: EvidenceConflictsArtifact;
  claim_confidence?: ClaimConfidenceArtifact;
  sandbox_analysis?: SandboxAnalysisArtifact;
  math_agent?: MathAgentArtifact;
  model_calibration?: ModelCalibrationArtifact;
  project_memory?: ProjectMemoryArtifact;
  agent_dialogue?: AgentDialogueArtifact;
}
