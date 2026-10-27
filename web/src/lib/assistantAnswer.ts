// What an assistant message says when the backend result has no answer text (UI-009). Framework-free so `node --test`
// can import it. "No answer" is a failure state, never a fabricated "Evaluation completed." success line.
import type { TaskOutcome } from "../types/chat";

/** The output contract the backend extracted from the question (execution_artifacts.output_contract). */
export interface OutputContractView {
  literal?: string;
  plain_text?: boolean;
  json_only?: boolean;
  exact_lines?: number;
  max_lines?: number;
  exact_items?: number;
  max_items?: number;
  numbered_items?: boolean;
  preserve_whitespace?: boolean;
  violations?: string[];
}

export function outputContractOf(artifacts: unknown): OutputContractView | null {
  const c = (artifacts as { output_contract?: unknown } | null | undefined)?.output_contract;
  return c && typeof c === "object" ? (c as OutputContractView) : null;
}

// Characters Markdown would read as syntax in a plain-text line.
const MD_SPECIAL = /[\\`*_{}[\]()#+\-.!|<>~$]/g;

function literalLine(line: string): string {
  const indent = line.match(/^[ \t]*/)?.[0] ?? "";
  const body = line.slice(indent.length).replace(MD_SPECIAL, (ch) => `\\${ch}`);
  // Leading spaces are kept as non-breaking spaces (indentation is part of the requested text).
  return indent.replace(/\t/g, "    ").replace(/ /g, " ") + body;
}

/**
 * The answer as Markdown that renders the line structure the user asked for. CommonMark joins two lines separated by
 * a single newline into one paragraph ("ALPHA\nBETA" shows as "ALPHA BETA"), so:
 * - literal, plain-text and JSON-only answers are rendered line by line as text (no Markdown syntax applies, the
 *   indentation is kept), each line ending in a hard break;
 * - answers with a line count ("exactly two lines") keep Markdown (math still renders) with each newline a hard break.
 * Other answers are unchanged. The stored and copied text is never altered; this is display only.
 */
export function renderableAnswer(content: string, artifacts: unknown): string {
  const contract = outputContractOf(artifacts);
  if (!contract || !content) return content;
  const text = content.replace(/\r\n?/g, "\n");
  if (contract.literal != null || contract.plain_text || contract.json_only) {
    return text
      .split("\n\n")
      .map((para) => para.split("\n").map(literalLine).join("  \n"))
      .join("\n\n");
  }
  if ((contract.exact_lines || contract.max_lines) && !/```|\$\$/.test(text)) {
    return text.replace(/([^\n])\n(?=[^\n])/g, "$1  \n");
  }
  return content;
}

export const EMPTY_ANSWER_TEXT =
  "No answer was returned for this question. The run may have failed or been cut off before it wrote one; try asking again.";

export interface ResolvedAnswer {
  content: string;
  /** True when the result carried no answer text. */
  empty: boolean;
  task_status?: TaskOutcome;
}

/**
 * The answer text and task outcome of a chat result. A null result, or one whose `response` is empty, becomes an
 * explicit "no answer" message with `task_status: failed` (or the backend's own non-completed outcome, if it sent one).
 */
export function resolveAnswer(
  res: { response?: unknown; task_status?: TaskOutcome | null } | null | undefined
): ResolvedAnswer {
  const text = typeof res?.response === "string" ? res.response : "";
  const outcome = res?.task_status || undefined;
  if (text.trim()) return { content: text, empty: false, task_status: outcome };
  const keep = outcome && outcome.task_status !== "completed" ? outcome : undefined;
  return {
    content: EMPTY_ANSWER_TEXT,
    empty: true,
    task_status: keep || {
      ...(outcome || {}),
      task_status: "failed",
      reason: "The server returned no answer text.",
    },
  };
}
