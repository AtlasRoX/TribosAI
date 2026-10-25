"use client";

import React, { useId, useState } from "react";
import { AlertTriangle, ChevronRight, CircleAlert, CircleCheck, CircleDashed, CircleX, Hourglass } from "lucide-react";
import { decodeEntities } from "@/lib/entities";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { emitUi } from "@/lib/uiEvents";
import { claimSummary, taskHeadline, verificationState } from "@/lib/verificationState";
import { unitsSummary } from "@/lib/unitsSummary";
import type { ClaimCheck, ClaimStatus, TaskOutcome, TaskStatus, VerificationReport } from "@/types/chat";

interface VerificationNoticeProps {
  report?: VerificationReport | null;
}

export { stripVerificationBanner } from "@/lib/verificationState";

const CLAIM_LABEL: Record<ClaimStatus, string> = {
  supported: "supported",
  contradicted: "contradicted",
  unsupported: "unsupported",
  not_checked: "not checked",
  inconclusive: "not checkable",
};

// Re-exported for existing importers; the implementation lives in a plain module.
export { decodeEntities };

function claimCounts(claims: ClaimCheck[]): Record<ClaimStatus, number> {
  const counts: Record<ClaimStatus, number> = { supported: 0, contradicted: 0, unsupported: 0, not_checked: 0, inconclusive: 0 };
  for (const c of claims) if (c.status in counts) counts[c.status] += 1;
  return counts;
}

/**
 * Evidence grounding for an answer: unverified claims, and the per-claim check when the verifier returns one.
 * This says whether statements match the retrieved sources, not whether the requested task ran (TaskStatusNotice).
 * Every answer gets an explicit state (UI-003): "not checked" (no report, or the placeholder report of direct replies),
 * "checked"/"verified" as a quiet line, or the warning below when claims failed.
 */
/**
 * A mathematical claim's text is "context: LaTeX" (or a table row with its own $...$): the LaTeX is typeset, so the
 * reader sees the statement as written in the answer rather than its source.
 */
function MathClaimText({ text }: { text: string }) {
  const i = text.indexOf(": ");
  const context = i > 0 ? text.slice(0, i) : "";
  const body = i > 0 ? text.slice(i + 2) : text;
  const content = body.includes("$") || body.includes("|") ? body : `$${body}$`;
  return (
    <span className="verify-claim-text">
      {context && <span>{context}: </span>}
      <MarkdownRenderer content={content} />
    </span>
  );
}

/** One checked claim: status, text, why, and the evidence keys it was matched to. */
function ClaimItem({ c }: { c: ClaimCheck }) {
  const miscited = c.cited_source_supported === false;
  return (
    <li data-status={c.status} data-miscited={miscited || undefined}>
      <span className="verify-claim-status">{miscited && c.status === "supported" ? "miscited" : CLAIM_LABEL[c.status] || c.status}</span>
      {c.claim_type === "mathematical" ? (
        <MathClaimText text={decodeEntities(c.claim_text)} />
      ) : (
        <span className="verify-claim-text">{decodeEntities(c.claim_text)}</span>
      )}
      {c.reason && <span className="verify-claim-reason">{decodeEntities(c.reason)}</span>}
      {miscited && <span className="verify-claim-reason">The cited source did not support this; another retrieved source did.</span>}
      {c.evidence?.length ? (
        <span className="verify-claim-reason">Evidence: {c.evidence.map((e) => e.source_key).filter(Boolean).join(", ")}</span>
      ) : null}
    </li>
  );
}

/**
 * Evidence grounding for an answer: unverified claims, and the per-claim check when the verifier returns one.
 * This says whether statements match the retrieved sources, not whether the requested task ran (TaskStatusNotice).
 * Every answer gets an explicit state (UI-003): "not checked" (no report, or the placeholder report of direct replies),
 * "checked"/"verified" as a quiet line, or the warning below when claims or citations failed. The warning opens by
 * default: claims that lack support or were miscited and every verifier finding are listed; supported claims sit in a
 * separate compact disclosure. A reader's own Hide/Review choice is kept.
 */
export function VerificationNotice({ report }: VerificationNoticeProps) {
  const [manual, setManual] = useState<boolean | null>(null);
  const listId = useId();
  const state = verificationState(report);
  const units = unitsSummary(report?.units);
  if (state.kind !== "problems" || !report) {
    const Icon = state.kind === "not_checked" || state.kind === "not_evaluated" ? CircleDashed : CircleCheck;
    if (state.kind === "not_checked" || state.kind === "not_evaluated") {
      return (
        <div className="task-status verify-state" data-verification={state.kind} role="status">
          <Icon style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden={true} />
          <span>{state.text}{units && ` · ${units}`}</span>
        </div>
      );
    }
    // A checked answer: the line opens the Verification tab under this answer (what was checked, how confident).
    return (
      <button
        type="button"
        className="task-status verify-state verify-state-link"
        data-verification={state.kind}
        title="Show what was checked"
        onClick={(e) => {
          const messageId = e.currentTarget.closest("[data-message-id]")?.getAttribute("data-message-id") || undefined;
          emitUi("tribos:evidence-tab", { tab: "verification", messageId });
        }}
      >
        <Icon style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden={true} />
        <span>{state.text}{units && ` · ${units}`}</span>
        <ChevronRight style={{ width: 12, height: 12, flexShrink: 0, opacity: 0.6 }} aria-hidden={true} />
      </button>
    );
  }
  const allClaims: ClaimCheck[] = Array.isArray(report.claims) ? report.claims : [];
  // Statements about the run itself ("the lookup failed") are checked against its tool log, not against papers.
  const operational = allClaims.filter((c) => c.claim_type === "operational");
  const claims = allClaims.filter((c) => c.claim_type !== "operational");
  const defects: any[] = report.defects || [];
  const counts = claimCounts(claims);
  // The per-claim summary already gives the share; the score is only shown when there are no claim checks.
  const score = !claims.length && typeof report.verification_score === "number" ? `grounding ${report.verification_score.toFixed(2)}` : null;
  // Contradicted statements first (wrong values), then unsupported ones; claims the checks could not decide are listed
  // apart, since "not checkable" is not a finding against the answer.
  const rank = (c: ClaimCheck) => (c.status === "contradicted" ? 0 : c.status === "unsupported" ? 1 : 2);
  const flagged = claims
    .filter((c) => (c.status !== "supported" && c.status !== "inconclusive") || c.cited_source_supported === false)
    .sort((a, b) => rank(a) - rank(b));
  const inconclusive = claims.filter((c) => c.status === "inconclusive");
  const supported = claims.filter((c) => c.status === "supported" && c.cited_source_supported !== false);

  let summary: string;
  let note = "";
  if (claims.length) {
    ({ summary, note } = claimSummary(counts, claims.length, defects.length));
  } else if (defects.length > 0) {
    summary = `${defects.length} verifier finding${defects.length === 1 ? "" : "s"}: parts of this answer could not be verified against the evidence`;
  } else {
    summary = "Parts of this answer could not be verified against the evidence";
  }
  const expandable = claims.length > 0 || defects.length > 0 || operational.length > 0;
  const open = expandable && (manual ?? true);

  return (
    <div className="verify-notice" role="note" data-severity={counts.contradicted ? "bad" : "warn"}>
      <button
        type="button"
        className="verify-toggle"
        aria-expanded={expandable ? open : undefined}
        aria-controls={expandable ? listId : undefined}
        onClick={() => expandable && setManual(!open)}
        disabled={!expandable}
      >
        <AlertTriangle style={{ width: 14, height: 14, flexShrink: 0 }} aria-hidden="true" />
        <span className="verify-summary">{summary}</span>
        {score && <span className="verify-score" title="Share of checked statements matched to evidence; not a probability that the answer is correct">{score}</span>}
        {expandable && (
          <span className="verify-action">
            {open ? "Hide" : "Review"}
            <ChevronRight className="verify-chevron" style={{ width: 13, height: 13 }} aria-hidden="true" />
          </span>
        )}
      </button>
      {note && <div className="verify-claim-reason" style={{ display: "block", padding: "0 12px 8px" }}>{note}</div>}
      {units && <div className="verify-claim-reason" style={{ display: "block", padding: "0 12px 8px" }}>{units}</div>}
      {open && (
        <div id={listId}>
          {flagged.length > 0 && (
            <ul className="verify-claims" aria-label="Claims that lack support or were miscited">
              {flagged.map((c) => (
                <ClaimItem key={c.claim_id} c={c} />
              ))}
            </ul>
          )}
          {defects.length > 0 && (
            <ul className="verify-list" aria-label="Verifier findings">
              {defects.map((d, i) => (
                <li key={i}>{d.description || d.claim}</li>
              ))}
            </ul>
          )}
          {operational.length > 0 && (
            <details className="verify-supported" style={{ padding: "0 12px 8px" }}>
              <summary className="verify-claim-reason" style={{ display: "list-item", cursor: "pointer" }}>
                {operational.length} statement{operational.length === 1 ? "" : "s"} about this run, checked against its tool log
                rather than sources
              </summary>
              <ul className="verify-claims">
                {operational.map((c) => (
                  <ClaimItem key={c.claim_id} c={c} />
                ))}
              </ul>
            </details>
          )}
          {inconclusive.length > 0 && (
            <details className="verify-supported" style={{ padding: "0 12px 8px" }}>
              <summary className="verify-claim-reason" style={{ display: "list-item", cursor: "pointer" }}>
                {inconclusive.length} statement{inconclusive.length === 1 ? "" : "s"} the checks could not decide
              </summary>
              <ul className="verify-claims">
                {inconclusive.map((c) => (
                  <ClaimItem key={c.claim_id} c={c} />
                ))}
              </ul>
            </details>
          )}
          {supported.length > 0 && (
            <details className="verify-supported" style={{ padding: "0 12px 8px" }}>
              <summary className="verify-claim-reason" style={{ display: "list-item", cursor: "pointer" }}>
                {supported.length} supported claim{supported.length === 1 ? "" : "s"}
              </summary>
              <ul className="verify-claims">
                {supported.map((c) => (
                  <ClaimItem key={c.claim_id} c={c} />
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

const TASK_LABEL: Record<TaskStatus, string> = {
  completed: "Requested operation completed",
  partial: "Requested operation partly completed",
  needs_input: "More input needed",
  failed: "Requested operation did not run",
  cancelled: "Cancelled",
};

const TASK_ICON: Record<TaskStatus, React.ComponentType<{ style?: React.CSSProperties; "aria-hidden"?: boolean }>> = {
  completed: CircleCheck,
  partial: CircleDashed,
  needs_input: Hourglass,
  failed: CircleX,
  cancelled: CircleAlert,
};

function opName(op?: string | null): string {
  return op ? op.replace(/_/g, " ") : "";
}

/** "Evidence synthesis partly completed" rather than a generic title over a bare operation name. */
function taskTitle(status: TaskStatus, op: string): string {
  const Op = op ? op.charAt(0).toUpperCase() + op.slice(1) : "";
  if (Op && status === "partial") return `${Op} partly completed`;
  if (Op && status === "failed") return `${Op} did not run`;
  if (Op && status === "cancelled") return `${Op} cancelled`;
  return TASK_LABEL[status] || status;
}

const DELIVERABLE_LABEL: Record<string, string> = {
  verified: "checked",
  addressed: "answered, not checked",
  failed_check: "value contradicted by the checks",
  missing: "not addressed",
};

/** Recovered attempts (history), unresolved failures (with their effect) and the requested items, under the status. */
function TaskDetails({ outcome }: { outcome: TaskOutcome }) {
  const recovered = outcome.recovered_failures || [];
  const unresolved = outcome.unresolved_failures || [];
  const items = outcome.deliverables || [];
  if (!recovered.length && !unresolved.length && !items.length) return null;
  const count = (s: string) => items.filter((i) => i.status === s).length;
  const parts = [
    count("verified") && `${count("verified")} checked`,
    count("addressed") && `${count("addressed")} answered, not checked`,
    count("failed_check") && `${count("failed_check")} contradicted`,
    count("missing") && `${count("missing")} not addressed`,
  ].filter(Boolean);
  return (
    <div className="task-status-reason" style={{ display: "block", marginTop: 4 }}>
      {unresolved.length > 0 && (
        <ul style={{ margin: "2px 0", paddingLeft: 18 }} aria-label="Failed steps">
          {unresolved.map((f, i) => (
            <li key={i}>
              {f.step} failed{f.error ? ` (${f.error})` : ""}: {f.effect}
            </li>
          ))}
        </ul>
      )}
      {recovered.length > 0 && (
        <div>
          {recovered.length} failed attempt{recovered.length === 1 ? " was" : "s were"} recovered by a retry (
          {recovered.map((r) => `${r.step} → ${r.recovered_by}`).join("; ")}).
        </div>
      )}
      {items.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer" }}>
            Requested items: {parts.join(" · ")}
          </summary>
          <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
            {items.map((d, i) => (
              <li key={i} data-status={d.status}>
                {d.item}: {DELIVERABLE_LABEL[d.status] || d.status}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Whether the operation the user asked for actually ran (audit F02); shown apart from evidence grounding. */
export function TaskStatusNotice({ outcome }: { outcome?: TaskOutcome | null }) {
  const headline = taskHeadline(outcome);
  if (!outcome || !headline) return null;
  const status = headline.status as TaskStatus;
  const mismatch = outcome.request_match === false;
  const Icon = TASK_ICON[status] || CircleAlert;
  const operations =
    outcome.requested_operation || outcome.executed_operation
      ? mismatch
        ? `Requested ${opName(outcome.requested_operation) || "an operation"}; ran ${opName(outcome.executed_operation) || "nothing"}.`
        : opName(outcome.requested_operation || outcome.executed_operation)
      : "";

  if (status === "completed" && !mismatch) {
    return (
      <div className="task-status" data-status="completed" role="status">
        <Icon style={{ width: 13, height: 13, flexShrink: 0 }} aria-hidden={true} />
        <div style={{ minWidth: 0 }}>
          <span>{TASK_LABEL.completed}</span>
          {operations && <span className="task-status-op">{operations}</span>}
          <TaskDetails outcome={outcome} />
        </div>
      </div>
    );
  }

  if (headline.partial) {
    // A run that stopped early is a partial answer even when one operation inside it (a time course) completed.
    return (
      <div className="task-status task-status-alert" data-status="partial" role="note">
        <Icon style={{ width: 14, height: 14, flexShrink: 0 }} aria-hidden={true} />
        <div style={{ minWidth: 0 }}>
          <span className="task-status-title">{headline.title}</span>
          {outcome.reason && <span className="task-status-reason"> — {outcome.reason}</span>}
          {headline.reasons.length > 0 && (
            <ul className="task-status-reason" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {headline.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {headline.unresolved.length > 0 && (
            <div className="task-status-reason">
              Not fully answered:
              <ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>
                {headline.unresolved.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          {/* What actually ran, never the requested operation's name (a partial run did not complete it, audit I43);
              the reason usually names it already ("Time course computed."). */}
          {opName(outcome.executed_operation) &&
            !String(outcome.reason || "").toLowerCase().includes(opName(outcome.executed_operation).toLowerCase()) && (
              <div className="task-status-op">Ran: {opName(outcome.executed_operation)}</div>
            )}
          <TaskDetails outcome={outcome} />
        </div>
      </div>
    );
  }

  const title = mismatch ? (status === "completed" ? TASK_LABEL.failed : TASK_LABEL[status] || status) : taskTitle(status, operations);
  return (
    <div className="task-status task-status-alert" data-status={status} role="note">
      <Icon style={{ width: 14, height: 14, flexShrink: 0 }} aria-hidden={true} />
      <div style={{ minWidth: 0 }}>
        <span className="task-status-title">{title}</span>
        {mismatch && operations && <div className="task-status-op">{operations}</div>}
        {outcome.reason &&
          (mismatch && operations ? (
            <div className="task-status-reason">{outcome.reason}</div>
          ) : (
            <span className="task-status-reason"> — {outcome.reason}</span>
          ))}
      </div>
    </div>
  );
}
