/** Slash commands of the composer: templates for common requests and approach switches. */

export interface SlashCommand {
  name: string;
  hint: string;
  /** Text put in the composer; "|" marks where the cursor goes. */
  template?: string;
  /** An approach to select instead of (or as well as) a template. */
  framework?: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "derive", hint: "Derive a result step by step", template: "Derive |, showing every step." },
  { name: "solve", hint: "Solve an equation or ODE with its conditions", template: "Solve | with " },
  { name: "simulate", hint: "Simulate a stated system over a time window", template: "Simulate | over 0–10 s and report the peak values." },
  { name: "verify", hint: "Check a result numerically", template: "Verify numerically that |" },
  { name: "units", hint: "Check the units and dimensions of an equation", template: "Check the units of |" },
  { name: "compare", hint: "Compare two methods or designs", template: "Compare | and | for " },
  { name: "literature", hint: "Find published work on a topic", template: "Find recent literature on |, with citations." },
  { name: "explain", hint: "Explain a concept clearly", template: "Explain |" },
  { name: "auto", hint: "Let Auto choose the approach", framework: "auto" },
  { name: "plan", hint: "Use Plan & execute for this question", framework: "agentic-plan-execute" },
  { name: "debate", hint: "Have independent critics cross-examine the answer", framework: "multi-agent-debate" },
  { name: "supervisor", hint: "Delegate parts to domain specialists", framework: "multi-agent-supervisor" },
];

/** The slash token being typed ("/sim" → "sim"); null when the input is not a slash command. */
export function slashQuery(input: string): string | null {
  const m = /^\/([a-z]*)$/i.exec(input);
  return m ? m[1].toLowerCase() : null;
}

export function matchingCommands(query: string): SlashCommand[] {
  return SLASH_COMMANDS.filter((c) => c.name.startsWith(query));
}

/** Applies a template: the text without its "|" markers and the cursor position (the first marker). */
export function applyTemplate(template: string): { text: string; cursor: number } {
  const cursor = template.indexOf("|");
  return { text: template.replace(/\|/g, ""), cursor: cursor < 0 ? template.length : cursor };
}
