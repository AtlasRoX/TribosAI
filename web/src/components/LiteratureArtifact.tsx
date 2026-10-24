"use client";

import React from "react";
import { BookOpen } from "lucide-react";
import { EVIDENCE_TIER_LABELS, sourceName } from "./agentic/evidenceLabels";
import { Card, Disclosure, ExtLink, Pill, Section, Stats, arr, fmt, isNum, str, styles as ui } from "./agentic/ui";

export interface LiteratureArtifactProps {
  data?: Record<string, any> | null;
}

function paperUrl(item: Record<string, any>): string | null {
  if (typeof item.url === "string" && /^https?:\/\//i.test(item.url)) return item.url;
  const arxiv = str(item.arxiv_id ?? item.arxiv).replace(/^arxiv:\s*/i, "");
  if (arxiv) return `https://arxiv.org/abs/${arxiv}`;
  const doi = str(item.doi).replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "");
  if (doi) return `https://doi.org/${doi}`;
  const zbl = str(item.zbl_id ?? item.zbl).replace(/^zbl\s*:?\s*/i, "");
  if (zbl) return `https://zbmath.org/?q=an:${zbl}`;
  const bibcode = str(item.bibcode ?? item.ads_id);
  if (bibcode) return `https://ui.adsabs.harvard.edu/abs/${bibcode}`;
  const openalex = str(item.openalex_id);
  if (/^W\d+$/i.test(openalex)) return `https://openalex.org/${openalex.toUpperCase()}`;
  const pmid = str(item.pmid);
  if (/^\d+$/.test(pmid)) return `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
  return null;
}

function primaryId(item: Record<string, any>): string {
  if (item.arxiv_id || item.arxiv) return `arXiv:${str(item.arxiv_id ?? item.arxiv).replace(/^arxiv:\s*/i, "")}`;
  if (item.zbl_id || item.zbl) return `Zbl ${str(item.zbl_id ?? item.zbl).replace(/^zbl\s*:?\s*/i, "")}`;
  if (item.mr_id || item.mr) return `MR${str(item.mr_id ?? item.mr).replace(/^mr\s*:?\s*/i, "")}`;
  if (item.bibcode) return str(item.bibcode);
  if (item.doi) return `DOI:${str(item.doi)}`;
  if (item.openalex_id) return str(item.openalex_id);
  if (item.pmid) return `PMID:${str(item.pmid)}`;
  return str(item.article_key ?? item.id ?? "—");
}

/**
 * Archivon scholarly literature card: preprints and peer-reviewed works from arXiv, Semantic Scholar, OpenAlex,
 * zbMATH Open, Crossref, and NASA ADS, including evidence grading and retraction/integrity checks.
 */
export function LiteratureArtifact({ data }: LiteratureArtifactProps) {
  if (!data || typeof data !== "object") return null;

  const papers = arr<Record<string, any>>(
    data.papers ?? data.articles ?? data.graded_articles ?? data.results ?? data.items
  );
  const excluded = arr<Record<string, any>>(data.excluded_articles);

  if (!papers.length && !excluded.length) return null;

  const sources = Array.from(
    new Set(papers.map((p) => str(p.source || p.provider)).filter(Boolean).map((s) => sourceName(s)))
  );

  return (
    <Card
      icon={<BookOpen style={{ width: 16, height: 16, color: "#60a5fa" }} />}
      title="Scholarly literature & preprints (Archivon)"
      meta={[
        `${papers.length} work${papers.length === 1 ? "" : "s"}`,
        sources.length ? sources.slice(0, 4).join(", ") : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      label="Scholarly literature and preprints"
      collapsible
    >
      <Stats
        items={[
          { label: "Works retrieved", value: papers.length },
          ...(sources.length ? [{ label: "Sources", value: sources.length, sub: `(${sources.slice(0, 3).join(", ")})` }] : []),
          ...(excluded.length ? [{ label: "Integrity exclusions", value: excluded.length }] : []),
        ]}
      />

      {papers.length > 0 && (
        <Section title="Retrieved works" meta={`${papers.length} indexed`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Identifier</th>
                  <th scope="col">Title & venue</th>
                  <th scope="col">Source</th>
                  <th scope="col" className={ui.num}>Year</th>
                  <th scope="col">Tier / classification</th>
                </tr>
              </thead>
              <tbody>
                {papers.slice(0, 25).map((item, idx) => {
                  const idLabel = primaryId(item);
                  const href = paperUrl(item);
                  const tierRaw = str(item.grade?.label ?? item.evidence_tier ?? item.tier ?? item.study_type);
                  const tierLabel = EVIDENCE_TIER_LABELS[tierRaw] || tierRaw || (item.grade?.is_preprint ? "Preprint" : "Scholarly work");
                  const mscOrCats = arr<string>(item.msc ?? item.categories ?? item.subjects).slice(0, 3).join(", ");
                  const venue = str(item.journal ?? item.venue);
                  return (
                    <tr key={`${idLabel}-${idx}`}>
                      <td>{href ? <ExtLink href={href}>{idLabel}</ExtLink> : <code>{idLabel}</code>}</td>
                      <td>
                        <div><strong>{str(item.title || "Untitled")}</strong></div>
                        {(venue || mscOrCats) && (
                          <div className={ui.muted}>
                            {[venue, mscOrCats ? `MSC/Subj: ${mscOrCats}` : ""].filter(Boolean).join(" · ")}
                          </div>
                        )}
                      </td>
                      <td>{item.source ? sourceName(str(item.source)) : "—"}</td>
                      <td className={ui.num}>{str(item.year || "—")}</td>
                      <td>
                        <Pill tone={item.grade?.is_preprint || tierRaw === "preprint" ? "info" : "ok"}>
                          {tierLabel}
                        </Pill>
                        {isNum(item.citation_count ?? item.citations) && (
                          <span className={ui.muted}> · {fmt(item.citation_count ?? item.citations, 0)} cites</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {excluded.length > 0 && (
        <Disclosure summary={`Excluded works (${excluded.length} retracted or withdrawn)`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Identifier</th>
                  <th scope="col">Title</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {excluded.map((ex, idx) => (
                  <tr key={idx}>
                    <td><code>{primaryId(ex)}</code></td>
                    <td>{str(ex.title || "—")}</td>
                    <td><Pill tone="bad">{str(ex.excluded_reason ?? ex.integrity?.status ?? "retracted")}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      )}
    </Card>
  );
}
