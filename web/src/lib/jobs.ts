// Helpers for background jobs (GET /api/jobs records).

import type { JobSummary } from "@/types/agentic";

/**
 * The question as the user typed it: `display_message` (the text without image transcriptions), falling back to
 * `message` for jobs stored by servers that predate it (LOG-37). Compared against the thread's user messages so
 * reopening a job does not add a second question bubble.
 */
export function jobQuestion(job: Pick<JobSummary, "request">): string {
  const req = job.request;
  if (typeof req?.display_message === "string" && req.display_message) return req.display_message;
  return typeof req?.message === "string" ? req.message : "";
}
