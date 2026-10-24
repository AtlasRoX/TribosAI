// Literature grading and integrity types (owned by GRADING, feature 5). Additive changes only.

export type StudyType =
  | "formal_proof"
  | "established_theory"
  | "peer_reviewed"
  | "meta_analysis"
  | "systematic_review"
  | "review"
  | "monograph"
  | "verified_computation"
  | "computational"
  | "preprint"
  | "conference_abstract"
  | "editorial"
  | "heuristic"
  | "unclassified"
  | (string & {});

export interface EvidenceGrade {
  study_type: StudyType;
  label: string;
  tier: number;
  weight: number;
  basis: "source_metadata" | "msc_classification" | "text_heuristic" | "europepmc_pubtype" | "mesh_heading" | "none" | string;
  cues: string[];
  confidence: "high" | "medium" | "low";
  is_preprint: boolean;
  indexed_pub_types?: string[];
  indexed_design?: string | null;
  mixed_design?: boolean;
  design_note?: string;
}

export interface IntegrityNotice {
  kind: string;
  source: "europepmc" | "crossref_publisher" | "crossref_retraction_watch" | string;
  notice_pmid?: string | null;
  notice_doi?: string | null;
  date?: string | null;
  reference?: string | null;
  record_id?: string | null;
}

export interface IntegrityStatus {
  status: "retracted" | "withdrawn" | "expression_of_concern" | "corrected" | "none" | "unchecked";
  notices: IntegrityNotice[];
  sources_checked: string[];
  crossref_error?: string | null;
}

export interface GradedArticle {
  article_key: string;
  source: string;
  pmid?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  zbl_id?: string | null;
  mr_id?: string | null;
  bibcode?: string | null;
  openalex_id?: string | null;
  pmcid?: string | null;
  title: string;
  journal: string;
  year: string;
  grade: EvidenceGrade;
  integrity: IntegrityStatus;
  is_integrity_notice: boolean;
  excluded_reason?: string | null;
}

export interface LiteratureArtifact {
  graded_articles?: GradedArticle[];
  excluded_articles?: GradedArticle[];
  papers?: Record<string, any>[];
  articles?: Record<string, any>[];
  results?: Record<string, any>[];
  integrity_check?: Record<string, string>;
  grade_summary?: Record<string, number>;
  [k: string]: any;
}
