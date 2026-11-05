// Agent labels of the biomedical release (saved history, replayed job logs) shown under their Tribos names.
//
// Only agent *labels* (Message.agent, ThoughtStep.agent) go through this. Answer text, step titles and step text
// never do: a word like "pre-clinical" in an answer is content, and rewriting it would also break the export's
// check that the saved answer matches the verified run (LOG-31).

const LEGACY_AGENT_NAMES: [RegExp, string][] = [
  [/\bClinical Orchestrator\b/gi, "Tribos Orchestrator"],
  [/\bTalk2KnowledgeGraphs?\b/gi, "Axiom"],
  [/\bTalk2BioModels?\b/gi, "Dynamis"],
  [/\bTalk2Cells?\b/gi, "Calcula"],
  [/\bTalk2Scholars?\b/gi, "Archivon"],
  [/\bTalk2AI[-_ ]?Agents[-_ ]?4[-_ ]?Pharma\b/gi, "Tribos"],
  [/\bAI[-_ ]?Agents[-_ ]?4[-_ ]?Pharma\b/gi, "Tribos"],
];

/** An agent label with the biomedical release's agent names replaced by the current ones. */
export function normalizeLegacyAgentName(label: string | null | undefined): string {
  if (!label) return "";
  return LEGACY_AGENT_NAMES.reduce((text, [re, name]) => text.replace(re, name), label);
}

/** Thoughts with their agent labels normalised; titles and text are left exactly as the server sent them. */
export function normalizeThoughtAgents<T extends { agent?: string | null }>(thoughts: T[]): T[] {
  return thoughts.map((th) => (th.agent ? { ...th, agent: normalizeLegacyAgentName(th.agent) } : th));
}

// Tool names that runs recorded before the STEM release carry (the re-run diff shows them). The keys stay so stored
// runs still render: an alias the server still runs is shown under the engine that serves it now
// (tribos/tools/registry.py registers the vivarix_* and lithoscribe_* aliases), and a tool that no longer exists
// reads as retired.
const LEGACY_TOOL_LABELS: Record<string, string> = {
  vivarix_simulate_time_course: "Dynamis time course",
  vivarix_compute_steady_state: "Dynamis steady state",
  vivarix_parameter_scan: "Dynamis parameter scan",
  lithoscribe_literature_synthesis: "Archivon literature search",
  synapta_opentargets_search: "Retired tool (Open Targets search)",
  synapta_opentargets_associations: "Retired tool (Open Targets associations)",
  synapta_kegg_pathways: "Retired tool (KEGG pathways)",
  lumicell_analyze_single_cell: "Retired tool (single-cell analysis)",
  websurfer_search: "WebSurfer search",
};

/** The display label of a recorded tool name; current tool names are shown as recorded. */
export function legacyToolLabel(toolName: string): string {
  return Object.prototype.hasOwnProperty.call(LEGACY_TOOL_LABELS, toolName) ? LEGACY_TOOL_LABELS[toolName] : toolName;
}
