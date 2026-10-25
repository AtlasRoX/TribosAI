"use client";

// An uploaded paper and the reproduction of its stated results: metadata with DOI or arXiv links, the extracted
// equations rendered with KaTeX, the parameter table, and one row per stated result (reproduced, differs, or not
// reproducible with the missing inputs), each with its page reference. The data shaping lives in paperData.ts.

import React, { useMemo } from "react";
import katex from "katex";
import { FileText } from "lucide-react";
import { Card, Disclosure, ExtLink, Pill, Section, fmt, styles as ui } from "../agentic/ui";
import {
  type PaperEquation,
  STATUS_LABEL,
  arxivUrl,
  claimDetail,
  countsLine,
  doiUrl,
  equationTex,
  pageRef,
  paperData,
  statusTone,
} from "./paperData";

function Equation({ e }: { e: PaperEquation }) {
  const { tex, converted } = equationTex(e);
  // KaTeX escapes its input and runs with trust off, so the rendered HTML carries no markup from the paper.
  const html = useMemo(
    () => (converted ? katex.renderToString(tex, { throwOnError: false, displayMode: false, trust: false }) : null),
    [tex, converted],
  );
  return (
    <tr>
      <td>{html ? <span dangerouslySetInnerHTML={{ __html: html }} /> : <span className={ui.mono}>{tex}</span>}</td>
      <td className={ui.num}>{e.number ? `(${e.number})` : ""}</td>
      <td className={ui.muted} title={e.line}>{pageRef(e)}</td>
    </tr>
  );
}

export function PaperArtifact({ data }: { data: unknown }) {
  const d = paperData(data);
  if (!d) return null;
  const p = d.paper ?? {};
  const equations = [...(d.odes ?? []), ...(d.equations ?? [])];
  const params = d.parameters ?? [];
  const claims = d.claims ?? [];
  const doi = doiUrl(p.doi);
  const arxiv = arxivUrl(p.arxiv_id);
  return (
    <Card
      icon={<FileText style={{ width: 15, height: 15 }} />}
      title={p.title || p.file || "Uploaded paper"}
      meta={claims.length ? countsLine(d.counts) || "no stated results checked" : `${p.n_pages ?? "?"} pages read`}
      label="Paper reproduction"
      collapsible
    >
      <p className={ui.note} style={{ marginTop: 0 }}>
        {p.authors ? `${p.authors}. ` : ""}
        {doi ? <ExtLink href={doi}>doi:{p.doi}</ExtLink> : null}
        {doi && arxiv ? " · " : null}
        {arxiv ? <ExtLink href={arxiv}>arXiv:{p.arxiv_id}</ExtLink> : null}
      </p>

      {claims.length > 0 && (
        <Section title="Stated results" hint="Each result recomputed from the paper's own equations and values">
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <thead>
                <tr>
                  <th scope="col">Result</th>
                  <th scope="col" className={ui.num}>Stated</th>
                  <th scope="col">Status</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Where</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c, i) => (
                  <tr key={`${c.name}-${i}`}>
                    <td className={ui.mono}>{c.name}</td>
                    <td className={ui.num}>{fmt(c.stated, 5)} {c.unit}</td>
                    <td><Pill tone={statusTone(c.status)}>{c.status ? STATUS_LABEL[c.status] : "unknown"}</Pill></td>
                    <td title={c.equation}>{claimDetail(c)}</td>
                    <td className={ui.muted} title={c.line}>{pageRef(c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.note && <p className={ui.note}>{d.note}</p>}
        </Section>
      )}

      {equations.length > 0 && (
        <Section title="Equations" meta={`${equations.length} found`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <tbody>
                {equations.slice(0, 40).map((e, i) => <Equation key={i} e={e} />)}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {params.length > 0 && (
        <Disclosure summary={`Parameters stated in the paper (${params.length})`}>
          <div className={ui.tableScroll}>
            <table className={ui.table}>
              <tbody>
                {params.map((q, i) => (
                  <tr key={`${q.name}-${i}`}>
                    <td className={ui.mono}>{q.name}</td>
                    <td className={ui.num}>{q.as_written ?? `${fmt(q.value, 5)} ${q.unit ?? ""}`}</td>
                    <td className={ui.muted}>{q.stated_result ? "stated result" : ""}</td>
                    <td className={ui.muted} title={q.line}>{pageRef(q)}</td>
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

export default PaperArtifact;
