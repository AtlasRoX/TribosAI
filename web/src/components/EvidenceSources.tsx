"use client";

import React, { useState } from "react";
import { AlertTriangle, BookOpen, ChevronRight, ExternalLink, Info } from "lucide-react";
import type { EvidenceGrade, GradedArticle, IntegrityNotice, LiteratureArtifact, StudyType } from "@/types/literature";
import { Card } from "@/components/agentic/ui";
import styles from "./EvidenceSources.module.css";

export interface EvidenceSourcesProps {
  data: LiteratureArtifact;
}

type StudyTypeKey = StudyType;

/** Group heading per study design / evidence tier. */
const GROUP: Record<string, string> = {
  formal_proof: "Formal & symbolic proofs",
  established_theory: "Established theory & standards",
  peer_reviewed: "Peer-reviewed articles",
  meta_analysis: "Meta-analyses",
  network_meta_analysis: "Network meta-analyses",
  systematic_review: "Systematic reviews",
  review: "Reviews & surveys",
  monograph: "Monographs & textbooks",
  verified_computation: "Verified computations",
  computational: "Computational studies",
  preprint: "Preprints",
  conference_abstract: "Conference proceedings & abstracts",
  editorial: "Editorials & notes",
  heuristic: "Heuristic & approximate analyses",
  unclassified: "Unclassified works",
};

/** Singular and plural for the header summary ("4 peer-reviewed, 2 preprints"). */
const COUNT_WORD: Record<string, [string, string]> = {
  formal_proof: ["formal proof", "formal proofs"],
  established_theory: ["reference", "references"],
  peer_reviewed: ["peer-reviewed", "peer-reviewed"],
  meta_analysis: ["meta-analysis", "meta-analyses"],
  network_meta_analysis: ["network meta-analysis", "network meta-analyses"],
  systematic_review: ["systematic review", "systematic reviews"],
  review: ["review", "reviews"],
  monograph: ["monograph", "monographs"],
  verified_computation: ["verified computation", "verified computations"],
  computational: ["computational", "computational"],
  preprint: ["preprint", "preprints"],
  conference_abstract: ["proceedings paper", "proceedings papers"],
  editorial: ["note", "notes"],
  heuristic: ["heuristic", "heuristics"],
  unclassified: ["unclassified", "unclassified"],
};

// Mirrors the 6-tier Tribos evidence hierarchy.
const TIER: Record<string, number> = {
  formal_proof: 1,
  established_theory: 2,
  meta_analysis: 2,
  systematic_review: 2,
  peer_reviewed: 3,
  network_meta_analysis: 3,
  review: 3,
  monograph: 3,
  verified_computation: 4,
  computational: 4,
  preprint: 5,
  conference_abstract: 5,
  editorial: 6,
  heuristic: 6,
  unclassified: 6,
};

const SOURCE_LABEL: Record<string, string> = {
  arxiv: "arXiv",
  s2: "Semantic Scholar",
  openalex: "OpenAlex",
  zbmath: "zbMATH Open",
  ads: "NASA ADS",
  europepmc: "EuropePMC",
  crossref_retraction_watch: "Retraction Watch (via Crossref)",
  crossref_publisher: "Publisher (via Crossref)",
};

const KIND_LABEL: Record<string, string> = {
  retraction: "Retraction",
  partial_retraction: "Partial retraction",
  withdrawal: "Withdrawal",
  removal: "Removal",
  expression_of_concern: "Expression of concern",
  correction: "Correction",
  erratum: "Erratum",
};

const ENTITIES: Record<string, string> = {
  "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&apos;": "'", "&amp;": "&", "&nbsp;": " ",
};

// Known inline markup only, so a decoded comparison ("p<0.001", "HR > 1") is never stripped as a tag.
const MARKUP = "(?:i|b|u|em|strong|sup|sub|inf|span|br|p|a|div|font|small|big|italic|bold|sc|underline|h[1-6]|ul|ol|li|mml:\\w+|math)";
const SUP_SUB_RE = /<\/?(?:sup|sub|inf)(?:\s[^<>]*)?\/?>/gi;
const MARKUP_RE = new RegExp(`</?${MARKUP}(?:\\s[^<>]*)?/?>`, "gi");

/** EuropePMC titles carry HTML entities and inline tags (<i>, <sup>); render them as plain text.
 *  Superscripts and subscripts become a space ("KRAS<sup>G12D</sup>" -> "KRAS G12D"), not a run-together word. */
function codePoint(m: string, n: number): string {
  return Number.isInteger(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : m;
}

function plainText(value: string | null | undefined): string {
  const decoded = String(value ?? "")
    .replace(/&(?:lt|gt|quot|#39|apos|amp|nbsp);/g, (m) => ENTITIES[m] ?? m)
    .replace(/&#(\d{1,7});/g, (m, n: string) => codePoint(m, Number(n)))
    .replace(/&#x([0-9a-f]{1,6});/gi, (m, n: string) => codePoint(m, parseInt(n, 16)));
  return decoded
    .replace(SUP_SUB_RE, " ")
    .replace(MARKUP_RE, "")
    .replace(/[\u2010\u2011]/g, "-") // (non-breaking) hyphens some fonts draw as a gap
    .replace(/\s+/g, " ")
    .replace(/ (?=[,.;:)\]]|-\S)/g, "") // "KRAS<sup>G12C</sup>-mutated" -> "KRAS G12C-mutated", not "G12C -mutated"
    .replace(/([(\[]) /g, "$1")
    .trim();
}

/** "Lancet (London, England)" -> "Lancet": drop NLM's place/year qualifier. */
function journalName(value: string | null | undefined): string {
  return plainText(value).replace(/\s*\([^()]*\)\s*$/, "");
}

/** Short names for the design a record was indexed as, when its reported analysis differs. */
const INDEXED_AS: Record<string, string> = {
  peer_reviewed: "peer-reviewed article",
  meta_analysis: "meta-analysis",
  systematic_review: "systematic review",
  review: "review",
  preprint: "preprint",
};

function tierOf(grade?: EvidenceGrade): number {
  return grade?.tier ?? TIER[(grade?.study_type ?? "unclassified") as StudyTypeKey] ?? 6;
}

function articleUrl(a: GradedArticle): string | null {
  if (a.arxiv_id) return `https://arxiv.org/abs/${a.arxiv_id.replace(/^arxiv:\s*/i, "")}`;
  if (a.doi) return `https://doi.org/${a.doi}`;
  if (a.zbl_id) return `https://zbmath.org/?q=an:${a.zbl_id.replace(/^zbl\s*:?\s*/i, "")}`;
  if (a.bibcode) return `https://ui.adsabs.harvard.edu/abs/${a.bibcode}`;
  if (a.openalex_id) return `https://openalex.org/${a.openalex_id}`;
  if (a.pmid) return `https://pubmed.ncbi.nlm.nih.gov/${a.pmid}/`;
  const [source, id] = (a.article_key || "").split(":");
  if (source?.toUpperCase() === "ARXIV" && id) return `https://arxiv.org/abs/${id}`;
  return source && id ? `https://europepmc.org/article/${source}/${id}` : null;
}

function basisHint(grade: EvidenceGrade): string {
  const cues = (grade.cues || []).join(", ");
  switch (grade.basis) {
    case "europepmc_pubtype":
      return `Classified from EuropePMC publication type: ${cues}`;
    case "mesh_heading":
      return `Classified from MeSH headings: ${cues}`;
    case "text_heuristic": {
      if (grade.indexed_design) return grade.design_note || `Graded by the reported analysis (${cues}), not the indexed publication type`;
      const m = /^(title|abstract): (.*)$/.exec(grade.cues?.[0] ?? "");
      return m ? `Inferred from ${m[1]} text: ${m[2]} (low confidence)` : `Inferred from text: ${cues} (low confidence)`;
    }
    default:
      return "No study design found in the publication metadata";
  }
}

function noticeYear(n: IntegrityNotice): string | null {
  if (n.date && /^\d{4}/.test(n.date)) return n.date.slice(0, 4);
  const m = /\b(19|20)\d{2}\b/.exec(n.reference ?? "");
  return m ? m[0] : null;
}

function sourcesOf(notices: IntegrityNotice[]): string {
  return Array.from(new Set(notices.map((n) => SOURCE_LABEL[n.source] ?? n.source))).join(", ");
}

/** The operative notice: the most recent one of the kind that caused the exclusion. */
function leadNotice(a: GradedArticle): IntegrityNotice | null {
  const notices = a.integrity?.notices ?? [];
  const wanted = a.integrity?.status === "withdrawn" ? ["withdrawal", "removal"] : ["retraction"];
  const relevant = notices.filter((n) => wanted.includes(n.kind));
  const pool = relevant.length ? relevant : notices;
  return [...pool].sort((x, y) => (noticeYear(y) ?? "").localeCompare(noticeYear(x) ?? ""))[0] ?? null;
}

function noticeSummary(n: IntegrityNotice): string {
  const kind = KIND_LABEL[n.kind] ?? n.kind;
  // EuropePMC references read 'Lancet. 2010 Feb 6;...'; the publication-type fallback has no journal.
  const fromCitation = n.source === "europepmc" && !!n.reference && (!!n.notice_pmid || !!n.notice_doi);
  const journal = fromCitation ? (n.reference ?? "").split(".")[0].trim() : "";
  const year = noticeYear(n);
  return [journal ? `${kind} in ${journal}` : kind, year].filter(Boolean).join(" ");
}

function noticeUrl(n: IntegrityNotice | null): string | null {
  if (!n) return null;
  if (n.notice_doi) return `https://doi.org/${n.notice_doi}`;
  if (n.notice_pmid) return `https://europepmc.org/article/MED/${n.notice_pmid}`;
  return null;
}

function checkLine(check: Record<string, string>): { text: string; warn: boolean } {
  const crossref = check?.crossref ?? "";
  if (crossref === "checked") return { text: "EuropePMC + Crossref checked", warn: false };
  if (crossref.startsWith("unavailable")) return { text: "Crossref check unavailable, EuropePMC only", warn: true };
  if (crossref === "disabled") return { text: "EuropePMC checked · Crossref check off", warn: false };
  if (crossref.startsWith("skipped")) return { text: "EuropePMC checked · no DOIs for Crossref", warn: false };
  return { text: check?.europepmc ? "EuropePMC checked" : "Integrity unchecked", warn: !check?.europepmc };
}

const UNGRADED: EvidenceGrade = {
  study_type: "unclassified",
  label: "Unclassified",
  tier: 6,
  weight: 0,
  basis: "none",
  cues: [],
  confidence: "low",
  is_preprint: false,
};

function ArticleRow({ article }: { article: GradedArticle }) {
  const [open, setOpen] = useState(false);
  const grade = article.grade ?? UNGRADED;
  const hint = basisHint(grade);
  const url = articleUrl(article);
  const title = plainText(article.title).replace(/\.$/, "") || "Untitled record";
  const status = article.integrity?.status ?? "unchecked";
  const concern = (article.integrity?.notices ?? []).filter((n) => n.kind === "expression_of_concern");
  const inferred = grade.confidence === "low" && grade.study_type !== "unclassified";
  // The record is indexed as one design (an RCT) but reports another (an indirect comparison of trials).
  const indexedAs = grade.indexed_design ? INDEXED_AS[grade.indexed_design] || grade.indexed_design.replace(/_/g, " ") : "";
  const meta = [journalName(article.journal), article.year, article.pmid ? `PMID ${article.pmid}` : article.doi ? `DOI ${article.doi}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className={styles.row}>
      {url ? (
        <a className={styles.rowTitle} href={url} target="_blank" rel="noopener noreferrer">
          {title}
          <ExternalLink className={styles.extIcon} aria-hidden="true" style={{ width: 11, height: 11 }} />
          <span className={styles.srOnly}> (opens in a new tab)</span>
        </a>
      ) : (
        <span className={styles.rowTitle}>{title}</span>
      )}
      <div className={styles.rowMeta}>
        {meta && <span>{meta}</span>}
        {inferred && (
          <span className={styles.flag} data-kind="muted">
            design inferred
          </span>
        )}
        {indexedAs && (
          <span className={styles.flag} data-kind="muted" title={grade.design_note || undefined}>
            indexed as {indexedAs}
          </span>
        )}
        {grade.is_preprint && (
          <span className={styles.flag} data-kind="preprint">
            Preprint
          </span>
        )}
        {status === "expression_of_concern" && (
          <span
            className={styles.flag}
            data-kind="concern"
            title={concern.map((n) => `${noticeSummary(n)} (${SOURCE_LABEL[n.source] ?? n.source})`).join("; ")}
          >
            <AlertTriangle aria-hidden="true" style={{ width: 11, height: 11 }} />
            Expression of concern
          </span>
        )}
        {status === "corrected" && (
          <span className={styles.flag} data-kind="muted">
            Corrected
          </span>
        )}
        {status === "unchecked" && (
          <span className={styles.flag} data-kind="muted">
            Integrity unchecked
          </span>
        )}
        <button
          type="button"
          className={styles.whyBtn}
          aria-expanded={open}
          aria-label="How this study design was graded"
          title={hint}
          onClick={() => setOpen(!open)}
        >
          <Info aria-hidden="true" style={{ width: 12, height: 12 }} />
        </button>
      </div>
      {open && <div className={styles.hint}>{hint}</div>}
    </li>
  );
}

function ExcludedSection({ articles }: { articles: GradedArticle[] }) {
  const [open, setOpen] = useState(false);
  const removed = articles.filter((a) => a.excluded_reason !== "integrity_notice");
  const notices = articles.length - removed.length;
  const retractedOnly = removed.every((a) => a.excluded_reason === "retracted");
  const label = removed.length
    ? `${removed.length} ${retractedOnly ? "retracted" : "retracted or withdrawn"} article${removed.length === 1 ? "" : "s"} excluded from this answer`
    : `${notices} integrity notice${notices === 1 ? "" : "s"} excluded (not evidence)`;

  return (
    <div className={styles.excluded}>
      <button type="button" className={styles.excludedToggle} aria-expanded={open} onClick={() => setOpen(!open)}>
        <AlertTriangle aria-hidden="true" style={{ width: 14, height: 14, flexShrink: 0 }} />
        <span>{label}</span>
        <ChevronRight className={styles.chevron} aria-hidden="true" style={{ width: 14, height: 14 }} />
      </button>
      {open && (
        <ul className={styles.excludedList}>
          {articles.map((a) => {
            const isNotice = a.excluded_reason === "integrity_notice";
            const lead = isNotice ? null : leadNotice(a);
            const link = noticeUrl(lead);
            const sources = sourcesOf(a.integrity?.notices ?? []);
            return (
              <li key={a.article_key || a.title} className={styles.excludedItem}>
                <div className={styles.excludedHead}>
                  <span className={styles.retracted} data-kind={isNotice ? "notice" : a.excluded_reason ?? "retracted"}>
                    {isNotice ? "Notice" : a.excluded_reason === "withdrawn" ? "Withdrawn" : "Retracted"}
                  </span>
                  <span className={styles.excludedTitle}>{plainText(a.title) || "Untitled record"}</span>
                </div>
                <div className={styles.rowMeta}>
                  {isNotice ? (
                    <span>Integrity notice ({a.year || "n.d."}), not evidence</span>
                  ) : (
                    <span>
                      {[lead ? noticeSummary(lead) : null, sources ? `sources: ${sources}` : null].filter(Boolean).join(" · ")}
                    </span>
                  )}
                  {link && (
                    <a className={styles.noticeLink} href={link} target="_blank" rel="noopener noreferrer">
                      Notice
                      <ExternalLink aria-hidden="true" style={{ width: 11, height: 11 }} />
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Graded literature evidence (study design and integrity per article) and the works excluded from the answer. */
export function EvidenceSources({ data }: EvidenceSourcesProps) {
  const graded = [...(data?.graded_articles ?? [])].sort((a, b) => tierOf(a.grade) - tierOf(b.grade));
  const excluded = data?.excluded_articles ?? [];
  if (!graded.length && !excluded.length) return null;

  const check = checkLine(data?.integrity_check ?? {});

  // Articles grouped by design, strongest tier first, so the design is named once per group instead of per row.
  const groups: { type: StudyTypeKey; tier: number; items: GradedArticle[] }[] = [];
  for (const a of graded) {
    const type = ((a.grade?.study_type as StudyTypeKey) in GROUP ? a.grade?.study_type : "unclassified") as StudyTypeKey;
    const g = groups.find((x) => x.type === type);
    if (g) g.items.push(a);
    else groups.push({ type, tier: tierOf(a.grade), items: [a] });
  }
  const designs = groups.map((g) => `${g.items.length} ${COUNT_WORD[g.type][g.items.length === 1 ? 0 : 1]}`).join(", ");

  return (
    <Card
      icon={<BookOpen style={{ width: 15, height: 15 }} />}
      title="Literature evidence"
      label="Literature evidence"
      collapsible
      defaultOpen={false}
      meta={
        <>
          {`${graded.length} article${graded.length === 1 ? "" : "s"}`}
          {designs && ` · ${designs}`}
          {" · "}
          <span className={check.warn ? styles.metaWarn : undefined}>{check.text}</span>
          {excluded.length > 0 && <span className={styles.metaBad}>{` · ${excluded.length} excluded`}</span>}
        </>
      }
    >
      {groups.map((g) => (
        <section key={g.type} className={styles.group} aria-label={GROUP[g.type]}>
          <div className={styles.groupHead} data-tier={g.tier}>
            <span className={styles.groupDot} aria-hidden="true" />
            <span>{GROUP[g.type]}</span>
            <span className={styles.groupCount}>{g.items.length}</span>
          </div>
          <ul className={styles.list}>
            {g.items.map((a) => (
              <ArticleRow key={a.article_key || a.title} article={a} />
            ))}
          </ul>
        </section>
      ))}

      {excluded.length > 0 && <ExcludedSection articles={excluded} />}
    </Card>
  );
}
