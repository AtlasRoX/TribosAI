// Query plan (plan step extra) types (owned by ENTITIES, feature 3). Additive changes only.

export type QueryEntityType =
  | "concept"
  | "equation"
  | "quantity"
  | "constant"
  | "material"
  | "system"
  | (string & {});

export interface QueryEntity {
  type: QueryEntityType;
  mention: string;
  label: string;
  ids: Record<string, string>;
  source: string;
  matched_on?: string | null;
  unit?: string | null;
  value?: string | number | null;
  formula?: string | null;
  validated: boolean;
  ambiguous_with?: string[];
  span?: [number, number];
  aliases?: string[];
}

export interface SourceDecision {
  name: string;
  run: boolean;
  reason: string;
}

export interface QueryPlanExtra {
  entities: QueryEntity[];
  intents: string[];
  sources: SourceDecision[];
  planner: "deterministic" | "llm" | "llm_unavailable";
  normalization: "resolved" | "partial" | "offline_lexicon" | "skipped";
  latency_ms: number;
}
