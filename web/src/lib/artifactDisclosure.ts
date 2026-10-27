// Which result cards open by default under an answer. Deterministic: the question text, the task outcome and each
// artifact's own state decide; no model call and no network. Framework-free so `node --test` can import it.
//
// The rule of thumb: evidence the question asked for, warnings (low support, contradictions, failures) and unfinished
// work open; routine diagnostics (agent dialogue, project memory, artifacts nobody asked for) stay compact. A reader's
// own open/close choice always wins over this policy (see Card in components/agentic/ui.tsx).

type Data = Record<string, any> | null | undefined;

export interface DisclosureInput {
  /** The user's question this answer responds to. */
  question?: string | null;
  /** The answer's task outcome (task_status, incomplete_reasons, unresolved). */
  taskStatus?: { task_status?: string; incomplete_reasons?: unknown; unresolved?: unknown } | null;
  artifacts?: Record<string, any> | null;
}

/** Domain artifacts open only when the question asks for that kind of evidence or analysis. */
const TOPICS: Record<string, RegExp> = {
  derivation:
    /\b(?:deriv\w*|prove|proof|simplif\w*|solve|symbolic\w*|integrat\w*|differentiat\w*|taylor|series|eigenval\w*|eigenvec\w*|jacobian|laplace|fourier|dsolve|sympy|closed[\s-]?form|exact)\b/i,
  dynamis:
    /\b(?:simulat\w*|trajector\w*|time[\s-]?courses?|steady[\s-]?states?|equilibri\w*|odes?|daes?|bvps?|phase\s+portrait|bifurcat\w*|stability|parameter\s+(?:scans?|sweeps?)|rk45|radau|bdf|lsoda|scipy)\b/i,
  reference_data:
    /\b(?:constants?|codata|nist|units?|conver(?:t|sion)|dimension\w*|oeis|sequences?|materials?\s+project|band\s*gap|crystal\s+structure|mp-\d+|a\d{6})\b/i,
  literature:
    /\b(?:papers?|preprints?|literature|citations?|arxiv|zbmath|mathscinet|openalex|semantic\s+scholar|ads|bibliography|references?|survey|review\s+of)\b/i,
  hypotheses: /\b(?:hypothes[ie]s|hypothesi[sz]\w*|conjectur\w*|testable|propose\s+(?:a|two|three|new|novel))\b/i,
};
TOPICS.axiom = TOPICS.derivation;
TOPICS.dynamis_scan = TOPICS.dynamis;
TOPICS.vivarix = TOPICS.dynamis;
TOPICS.vivarix_scan = TOPICS.dynamis;
TOPICS.physis = TOPICS.reference_data;
TOPICS.archivon = TOPICS.literature;

/** Words naming each topic inside an exclusion clause ("No numerical simulation or literature search is needed"). */
const EXCLUSION_WORDS: Record<string, RegExp> = {
  derivation: /\b(?:symbolic\w*|derivation|proof|sympy)\b/i,
  dynamis: /\b(?:simulat\w*|trajector\w*|time[\s-]?courses?|numerical\s+integration|model(?:l?ing)?)\b/i,
  reference_data: /\b(?:constants?|codata|unit\s+conversion|oeis|materials?\s+project)\b/i,
  literature: /\b(?:literature|papers?|preprints?|arxiv|citations?)\b/i,
  hypotheses: /\b(?:hypothes[ie]s|hypothesi[sz]\w*|conjectur\w*)\b/i,
};
EXCLUSION_WORDS.axiom = EXCLUSION_WORDS.derivation;
EXCLUSION_WORDS.dynamis_scan = EXCLUSION_WORDS.dynamis;
EXCLUSION_WORDS.vivarix = EXCLUSION_WORDS.dynamis;
EXCLUSION_WORDS.vivarix_scan = EXCLUSION_WORDS.dynamis;
EXCLUSION_WORDS.physis = EXCLUSION_WORDS.reference_data;
EXCLUSION_WORDS.archivon = EXCLUSION_WORDS.literature;

const NEEDED = /\b(?:needed|required|necessary|wanted|requested)\b/i;

/**
 * The parts of the question that exclude work: sentences or clauses such as "No simulation or literature search
 * needed.", "without running simulations", "do not run a debate", "Simulation is not needed". A plain "no" in other
 * wording ("if no exact lookup works") is only an exclusion when it opens a sentence or the clause says "needed".
 */
export function exclusionClauses(question: string): string[] {
  const out: string[] = [];
  const sentences = question.split(/(?<=[.!?;])\s+|\n+/);
  for (const raw of sentences) {
    const s = raw.trim();
    if (!s) continue;
    if (/^no\s+/i.test(s) && !/^no\s+(?:more\s+than|later\s+than|fewer\s+than)\b/i.test(s)) {
      out.push(s);
      continue;
    }
    const noNeeded = s.match(/\bno\s+[^.;:!?]*$/i);
    if (noNeeded && NEEDED.test(noNeeded[0])) out.push(noNeeded[0]);
    const without = s.match(/\b(?:without|skip(?:ping)?|exclud(?:e|ing)|avoid(?:ing)?)\s+[^.;:!?,]*/gi);
    if (without) out.push(...without);
    const dont = s.match(/\b(?:do\s+not|don'?t|never|no\s+need\s+to)\s+(?:run|perform|do|include|use|need|start|launch|add)\s+[^.;:!?]*/gi);
    if (dont) out.push(...dont);
    const notNeeded = s.match(/[^.;:!?]*\b(?:is|are)\s+not\s+(?:needed|required|necessary|wanted)\b/gi);
    if (notNeeded) out.push(...notNeeded);
  }
  return out;
}

/** Whether the question asks for this artifact's kind of evidence and does not explicitly exclude it. */
export function questionRequests(key: string, question: string | null | undefined): boolean {
  const q = (question || "").trim();
  const topic = TOPICS[key];
  if (!q || !topic) return false;
  const clauses = exclusionClauses(q);
  const words = EXCLUSION_WORDS[key];
  if (words && clauses.some((c) => words.test(c))) return false;
  let rest = q;
  for (const c of clauses) rest = rest.split(c).join(" ");
  return topic.test(rest);
}

function failed(data: Data): boolean {
  if (!data || typeof data !== "object") return false;
  if (data.success === false) return true;
  const status = String(data.status || data.task_status || "").toLowerCase();
  if (/(?:^|_)(?:error|failed|failure)$/.test(status)) return true;
  return typeof data.error === "string" && data.error.trim().length > 0;
}

function list(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

/** Partial answers, unanswered sub-questions, failed calls or phases, and a used-up budget. */
export function runNeedsAttention(run: Data, taskStatus?: DisclosureInput["taskStatus"]): boolean {
  if (taskStatus) {
    if (taskStatus.task_status && taskStatus.task_status !== "completed") return true;
    if (list(taskStatus.incomplete_reasons).length || list(taskStatus.unresolved).length) return true;
  }
  if (!run || typeof run !== "object") return false;
  if (run.budget?.exhausted) return true;
  if (list(run.sub_questions).some((q) => q && q.status && !["answered", "done", "verified"].includes(String(q.status)))) return true;
  if (list(run.trace).some((t) => t && t.success === false)) return true;
  return list(run.phases).some((p) => p && /^(?:error|budget|timeout|llm_unavailable|cancelled)$/.test(String(p.status || "")));
}

export function planNeedsAttention(plan: Data): boolean {
  if (!plan || typeof plan !== "object") return false;
  if (list(plan.rejected).length) return true;
  if (plan.planner === "none" || /fail|unusable|budget/.test(String(plan.status || ""))) return true;
  return list(plan.nodes).some((n) => n && String(n.status || "") === "error");
}

/** Claim-support scores: a low-support claim, or overall support below 0.6 (support scores, not truth probabilities). */
export function lowSupport(conf: Data): boolean {
  if (!conf || typeof conf !== "object") return false;
  if (typeof conf.answer_confidence === "number" && conf.answer_confidence < 0.6) return true;
  if (typeof conf.supported_fraction === "number" && conf.supported_fraction < 0.6) return true;
  return list(conf.claims).some((c) => c && (c.band === "low" || (typeof c.confidence === "number" && c.confidence < 0.5)));
}

/** Counter-evidence: a contradicting passage, or a heuristic-only classification that deserves a second look. */
export function conflictsNeedAttention(conflicts: Data): boolean {
  if (!conflicts || typeof conflicts !== "object") return false;
  if (list(conflicts.conflicts).some((c) => c && String(c.label || "") === "contradicts")) return true;
  return String(conflicts.classifier || "") === "heuristic" && list(conflicts.conflicts).length > 0;
}

/** Default open state for every artifact present in `artifacts`, keyed like ExecutionArtifacts. */
export function artifactDisclosure(input: DisclosureInput): Record<string, boolean> {
  const arts = input.artifacts || {};
  const q = input.question || "";
  const out: Record<string, boolean> = {};
  for (const [key, data] of Object.entries(arts)) {
    if (data === null || data === undefined) continue;
    switch (key) {
      case "plan_approval":
      case "sandbox_analysis":
      case "math_agent":
      case "ode_verification": // produced only when the question asks for numerical checks
      case "model_calibration":
        out[key] = true;
        break;
      case "evidence_conflicts":
        out[key] = conflictsNeedAttention(data);
        break;
      case "claim_confidence":
        out[key] = lowSupport(data);
        break;
      case "agent_run":
        out[key] = runNeedsAttention(data, input.taskStatus);
        break;
      case "agent_plan":
        out[key] = planNeedsAttention(data);
        break;
      case "agent_dialogue":
      case "project_memory":
        out[key] = false;
        break;
      default:
        if (TOPICS[key]) out[key] = failed(data) || questionRequests(key, q);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------------------------------
// Attention: why a collapsed card says "needs a look" (audit I42). Unlike the disclosure policy above (what would be
// worth opening for this question), a card is flagged only for an actual warning, and the reason is shown with it.

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Why a run summary needs a look, or "" (a partial or failed task, open sub-questions, failed calls or phases). */
export function runAttentionReason(run: Data, taskStatus?: DisclosureInput["taskStatus"]): string {
  if (taskStatus) {
    const reasons = list(taskStatus.incomplete_reasons).map(String).filter(Boolean);
    if (reasons.length) return reasons[0];
    if (taskStatus.task_status && taskStatus.task_status !== "completed") {
      return `The task is ${String(taskStatus.task_status).replace(/_/g, " ")}`;
    }
    const unresolved = list(taskStatus.unresolved).length;
    if (unresolved) return `${plural(unresolved, "part")} of the question not fully answered`;
  }
  if (!run || typeof run !== "object") return "";
  if (run.budget?.exhausted) return "The agent budget ran out";
  const open = list(run.sub_questions).filter((q) => q && q.status && !["answered", "done", "verified"].includes(String(q.status))).length;
  if (open) return `${plural(open, "sub-question")} not answered by a tool-backed step`;
  const failedCalls = list(run.trace).filter((t) => t && t.success === false).length;
  if (failedCalls) return `${plural(failedCalls, "tool call")} failed`;
  const phases = list(run.phases).filter((p) => p && /^(?:error|budget|timeout|llm_unavailable|cancelled)$/.test(String(p.status || "")));
  if (phases.length) return `Phase ${String(phases[0].label || phases[0].key || "")} ${String(phases[0].status).replace(/_/g, " ")}`.replace(/\s+/g, " ");
  return "";
}

/** The warning each card carries, keyed like ExecutionArtifacts; a card without a key has nothing to flag. */
export function artifactAttention(input: DisclosureInput): Record<string, string> {
  const arts = input.artifacts || {};
  const out: Record<string, string> = {};
  for (const [key, data] of Object.entries(arts)) {
    if (data === null || data === undefined || typeof data !== "object") continue;
    let reason = "";
    switch (key) {
      case "math_agent": {
        const status = String((data as Record<string, unknown>).status || "");
        if (["failed", "unverified", "partially_verified"].includes(status)) reason = `The mathematics is ${status.replace(/_/g, " ")}`;
        break;
      }
      case "formal_proof": {
        const status = String((data as Record<string, unknown>).status || "");
        if (["failed", "timeout", "mismatch"].includes(status)) reason = String((data as Record<string, unknown>).error || `Lean: ${status}`).slice(0, 200);
        break;
      }
      case "evidence_conflicts":
        if (list((data as Data)?.conflicts).some((c) => c && String(c.label || "") === "contradicts")) {
          reason = "A retrieved passage contradicts a claim";
        } else if (conflictsNeedAttention(data as Data)) {
          reason = "Counter-evidence was classified by a heuristic, not a model check";
        }
        break;
      case "claim_confidence":
        if (lowSupport(data as Data)) reason = "Some claims have low support in the retrieved evidence (a support score, not a truth probability)";
        break;
      case "agent_run":
        reason = runAttentionReason(data as Data, input.taskStatus);
        break;
      case "agent_plan": {
        const plan = data as Record<string, unknown>;
        const rejected = list(plan.rejected).length;
        if (rejected) reason = `${plural(rejected, "planned call")} rejected`;
        else if (plan.planner === "none" || /fail|unusable|budget/.test(String(plan.status || ""))) reason = "The planner did not run";
        else if (list(plan.nodes).some((n) => n && String(n.status || "") === "error")) reason = "A planned call failed";
        break;
      }
      default:
        if (failed(data as Data)) {
          const err = (data as Record<string, unknown>).error;
          reason = typeof err === "string" && err.trim() ? `This step failed: ${err.trim().slice(0, 160)}` : "This step failed";
        }
    }
    if (reason) out[key] = reason;
  }
  return out;
}
