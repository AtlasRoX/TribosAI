// Citation map types (owned by CITATIONS, feature 4). Additive changes only.

export type CiteType =
  | "arxiv"
  | "doi"
  | "zbl"
  | "mr"
  | "oeis"
  | "ads"
  | "mp"
  | "isbn"
  | "openalex"
  | "pmid"
  | "comp"
  | "dataset"
  | "url";

export interface CitationPassage {
  passage_id?: string | null;
  text: string;
  section?: string | null;
  has_full_text?: boolean;
  kind: "literature" | "tool_output" | "web_snippet" | "mention";
  highlight?: string | null;
}

export interface CitationEntry {
  key: string;
  id: string;
  type: CiteType;
  title?: string | null;
  url: string;
  source_agent: string;
  source_tool: string;
  authors?: string | null;
  journal?: string | null;
  year?: string | null;
  pmcid?: string | null;
  pub_types?: string[];
  evidence_level?: string | null;
  /** Who published a web source: standards_body | reference_database | preprint_server | literature | web. */
  source_authority?: string | null;
  retracted?: boolean | null;
  retraction_notice?: string | null;
  passages: CitationPassage[];
  verified: boolean;
  note?: string | null;
}

export interface ClaimSupport {
  key: string;
  occurrence: number;
  sentence: string;
  passage_id?: string | null;
  highlight?: string | null;
  shared_terms: string[];
  grounded_by_verifier: boolean;
  /** Client-only: set by supportFor when this support belongs to another mention of the same source (UI-017). */
  fallback?: boolean;
}

export interface CitationMap {
  version: number;
  entries: Record<string, CitationEntry>;
  aliases: Record<string, string>;
  supports: ClaimSupport[];
  unverified: string[];
  truncated?: boolean;
}
