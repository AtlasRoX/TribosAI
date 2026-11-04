"use client";

// The research lab: the generative view of a research-loop project (mode "loop"). Everything on it is generated from
// the project's own state: the loop orbit from its rounds, the plan board from its charter, the findings wall from its
// ledger (each finding's values, charts and checks as generative-UI blocks), the proofs from its prove tests, and the
// thesis reader from the written thesis. Nothing here computes a result; it only lays out what the server recorded.

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, BookOpen, Check, ChevronDown, Code2, Download, FileText, FlaskConical, Link2, Loader2, Play, RotateCcw,
  ScrollText, Sigma, Square, Trash2, X,
} from "lucide-react";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { UiBlockView } from "@/components/genui/GenUI";
import { normalizeBlock, type UiBlock } from "@/lib/genui";
import { errorMessage, type AuthHeaders } from "@/services/apiClient";
import {
  TIER_LABEL, fetchProjectFile, fetchThesis, formatDuration, isActive, loopProgress, type Campaign, type Finding,
  type ResearchRound, type ResearchTest, type ThesisFormat,
} from "@/services/campaignService";
import styles from "./ResearchLab.module.css";

export interface ResearchLabProps {
  c: Campaign;
  backendUrl: string;
  authHeaders: AuthHeaders;
  busy: boolean;
  linkCopied: boolean;
  onStop: () => void;
  onResume: () => void;
  onDelete: () => void;
  onCopyLink: () => void;
  onContinue: (instruction: string) => Promise<void>;
}

type Tab = "overview" | "findings" | "proofs" | "thesis" | "literature" | "activity";

const PHASE: Record<string, string> = {
  review: "Reading the literature", charter: "Writing the research plan", testing: "Running experiments",
  judging: "Judging the evidence", thesis: "Writing the thesis", done: "Finished",
};
const STOP: Record<string, string> = {
  concluded: "Conclusion reached: every deliverable is settled.",
  stagnated: "Stopped: recent rounds made no progress.",
  "nothing left to run": "Stopped: nothing further could be run.",
  "round ceiling": "Stopped at the round ceiling.",
  "time ceiling": "Stopped at the time ceiling.",
  "test-run ceiling": "Stopped at the test-run ceiling.",
};
const STATUS_TEXT: Record<string, string> = {
  queued: "Queued", running: "Running", succeeded: "Finished", failed: "Stopped on an error", cancelled: "Stopped",
  interrupted: "Interrupted",
};

function roundsOf(c: Campaign): ResearchRound[] {
  return Array.isArray(c.rounds) ? c.rounds : [];
}

function tierClass(tier?: string): string {
  return styles[`tier_${tier || "none"}`] ?? "";
}

function TierSeal({ tier }: { tier?: string }) {
  return <span className={`${styles.seal} ${tierClass(tier)}`}>{TIER_LABEL[tier || "none"] ?? tier}</span>;
}

function fmtValue(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(10)));
  if (Array.isArray(v)) return v.slice(0, 8).map(fmtValue).join(", ") + (v.length > 8 ? " …" : "");
  if (v && typeof v === "object") return Object.entries(v as Record<string, unknown>).slice(0, 4).map(([k, x]) => `${k}: ${fmtValue(x)}`).join("; ");
  return String(v ?? "");
}

// Loop orbit -----------------------------------------------------------------------------------------------------

function LoopOrbit({ c }: { c: Campaign }) {
  const rounds = roundsOf(c);
  const tests = c.charter?.tests ?? [];
  const phase = c.loop?.phase ?? "review";
  const live = isActive(c);
  const size = 236;
  const cx = size / 2;
  const rings = Math.max(1, rounds.length);
  const radius = (i: number) => 34 + ((i + 1) * (cx - 46)) / Math.max(rings, 3);
  const testRound = (t: ResearchTest) => rounds.findIndex((r) => r.tests.includes(t.id));
  const progress = loopProgress(c);
  return (
    <figure className={styles.orbit} aria-label={`Research loop: ${rounds.length} round(s), ${PHASE[phase] ?? phase}`}>
      <svg viewBox={`0 0 ${size} ${size}`} role="img">
        <circle cx={cx} cy={cx} r={cx - 6} className={styles.orbitHalo} />
        {Array.from({ length: rings }, (_, i) => {
          const r = rounds[i];
          const current = live && i === rounds.length - 1 && !r?.finished_at;
          return (
            <circle key={i} cx={cx} cy={cx} r={radius(i)}
              className={`${styles.ring} ${r?.progress ? styles.ringProgress : ""} ${current ? styles.ringLive : ""} ${r?.concluded ? styles.ringConcluded : ""}`} />
          );
        })}
        {tests.map((t, j) => {
          const ri = testRound(t);
          if (ri < 0) return null;
          const inRound = rounds[ri].tests;
          const k = inRound.indexOf(t.id);
          const a = -Math.PI / 2 + (2 * Math.PI * k) / Math.max(inRound.length, 1) + ri * 0.35;
          const r = radius(ri);
          return (
            <circle key={t.id + j} cx={cx + r * Math.cos(a)} cy={cx + r * Math.sin(a)} r={5.2}
              className={`${styles.planet} ${styles[`p_${t.status}`] ?? ""}`}>
              <title>{`${t.id} · ${t.title} — ${t.status}`}</title>
            </circle>
          );
        })}
        <text x={cx} y={cx - 6} textAnchor="middle" className={styles.orbitBig}>{progress.done}/{progress.total || "–"}</text>
        <text x={cx} y={cx + 13} textAnchor="middle" className={styles.orbitSmall}>settled</text>
      </svg>
      <figcaption>
        {live && <span className={styles.pulseDot} aria-hidden="true" />}
        {c.loop?.stop_reason ? (STOP[c.loop.stop_reason] ?? c.loop.stop_reason) : (PHASE[phase] ?? phase)}
        {rounds.length > 0 && ` · round ${rounds.length}`}
      </figcaption>
    </figure>
  );
}

function EstimateMeter({ c }: { c: Campaign }) {
  const e = c.estimate;
  if (!e) return null;
  if (!isActive(c)) {
    // Active research time: hours the project sat paused are not research.
    const start = c.loop?.started_at ?? c.created_at;
    const active = c.loop?.active_s ?? (c.finished_at ?? c.updated_at) - start;
    return <div className={styles.estimate}><span className={styles.estBig}>{formatDuration(active)}</span><span>of research</span></div>;
  }
  const span = Math.max(1, e.high_s);
  return (
    <div className={styles.estimate} title={e.basis}>
      <span className={styles.estBig}>≈ {formatDuration(e.remaining_s)}</span>
      <span>left · {formatDuration(e.low_s)}–{formatDuration(e.high_s)}</span>
      <span className={styles.estBar} aria-hidden="true">
        <span style={{ left: `${(100 * e.low_s) / span}%`, right: 0 }} className={styles.estBand} />
        <span style={{ left: `${(100 * e.remaining_s) / span}%` }} className={styles.estMark} />
      </span>
      <span className={styles.estBasis}>{e.basis}</span>
    </div>
  );
}

// Images served by the API (sent with the auth headers, shown through blob URLs) ------------------------------------

function ProjectImage({ backendUrl, authHeaders, id, name, alt }: { backendUrl: string; authHeaders: AuthHeaders; id: string; name: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const ctl = new AbortController();
    let made: string | null = null;
    fetchProjectFile(backendUrl, authHeaders, id, name, ctl.signal)
      .then((b) => { made = URL.createObjectURL(b); setUrl(made); })
      .catch(() => { if (!ctl.signal.aborted) setFailed(true); });
    return () => { ctl.abort(); if (made) URL.revokeObjectURL(made); };
  }, [backendUrl, authHeaders, id, name]);
  if (failed) return <span className={styles.muted}>[{alt}]</span>;
  if (!url) return <span className={styles.imgWait} aria-label="loading figure" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className={styles.figureImg} loading="lazy" />;
}

// Overview -----------------------------------------------------------------------------------------------------------

function blocksOf(raw: unknown[] | undefined): UiBlock[] {
  return (raw ?? []).map((b) => normalizeBlock(b)).filter((b): b is UiBlock => b !== null);
}

function Overview({ c, onFinding }: { c: Campaign; onFinding: (id: string) => void }) {
  const ch = c.charter;
  const rounds = roundsOf(c);
  const headline = [...rounds].reverse().find((r) => r.headline)?.headline;
  if (!ch) {
    return (
      <div className={styles.emptyNote}>
        <FlaskConical aria-hidden="true" />
        <p>{c.loop?.phase === "review" ? "Reading the literature first. The research plan (deliverables, hypotheses and tests) appears here next." : "Writing the research plan…"}</p>
      </div>
    );
  }
  const tests = ch.tests;
  return (
    <div className={styles.overview}>
      {headline && <p className={styles.headline}><span>Where it stands</span>{headline}</p>}
      {ch.summary && <p className={styles.summary}>{ch.summary}</p>}
      <section aria-labelledby="lab-deliverables">
        <h3 id="lab-deliverables" className={styles.sectionTitle}>Deliverables</h3>
        <ol className={styles.deliverables}>
          {ch.deliverables.map((d) => (
            <li key={d.id} className={`${styles.deliverable} ${styles[`d_${d.status}`] ?? ""}`}>
              <span className={styles.stamp}>{d.status}</span>
              <div>
                <p className={styles.dTitle}><b>{d.id}</b> {d.title}</p>
                <p className={styles.dWhen}>Done when: {d.acceptance}</p>
                {d.note && <p className={styles.dNote}>{d.note}</p>}
                <div className={styles.chips}>
                  <span className={`${styles.chip} ${tierClass(d.tier)}`}>needs {TIER_LABEL[d.tier] ?? d.tier}</span>
                  {d.evidence.map((e) => <button key={e} type="button" className={styles.chipBtn} onClick={() => onFinding(e)}>{e}</button>)}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>
      {ch.hypotheses.length > 0 && (
        <section aria-labelledby="lab-hyp">
          <h3 id="lab-hyp" className={styles.sectionTitle}>Hypotheses</h3>
          <div className={styles.hypGrid}>
            {ch.hypotheses.map((h) => (
              <article key={h.id} className={`${styles.hyp} ${styles[`v_${h.verdict}`] ?? ""}`}>
                <header><b>{h.id}</b><span className={styles.verdict}>{h.verdict}</span></header>
                <p>{h.statement}</p>
                <p className={styles.dWhen}>Refuted if: {h.falsification}</p>
                {h.evidence.length > 0 && (
                  <div className={styles.chips}>{h.evidence.map((e) => <button key={e} type="button" className={styles.chipBtn} onClick={() => onFinding(e)}>{e}</button>)}</div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}
      <section aria-labelledby="lab-tests">
        <h3 id="lab-tests" className={styles.sectionTitle}>Tests <span className={styles.count}>{tests.length}</span></h3>
        <ul className={styles.tests}>
          {tests.map((t) => (
            <li key={t.id} className={styles[`t_${t.status}`] ?? ""}>
              <span className={styles.tStatus} aria-label={t.status}>
                {t.status === "running" ? <Loader2 className={styles.spin} /> : t.status === "passed" ? <Check /> : t.status === "blocked" ? <X /> : <span className={styles.dotSm} />}
              </span>
              <span className={styles.tId}>{t.id}</span>
              <span className={styles.tKind}>{t.kind}</span>
              <span className={styles.tTitle} title={t.objective}>{t.title}</span>
              <span className={styles.tServes}>{[...t.serves, ...t.hypotheses].join(" ")}</span>
              {t.finding_ids.slice(-1).map((f) => <button key={f} type="button" className={styles.chipBtn} onClick={() => onFinding(f)}>{f}</button>)}
            </li>
          ))}
        </ul>
      </section>
      {rounds.length > 0 && (
        <section aria-labelledby="lab-rounds">
          <h3 id="lab-rounds" className={styles.sectionTitle}>Rounds</h3>
          <ol className={styles.roundsList}>
            {rounds.map((r) => (
              <li key={r.round}>
                <details>
                  <summary>
                    <b>Round {r.round}</b> · {r.tests.length} test(s) · {r.finished_at ? (r.concluded ? "conclusion reached" : r.progress ? "progress" : "no progress") : "running"}
                    {r.seconds ? ` · ${formatDuration(r.seconds)}` : ""}
                  </summary>
                  {r.analysis && <div className={styles.analysis}><MarkdownRenderer content={r.analysis} /></div>}
                </details>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

// Findings -----------------------------------------------------------------------------------------------------------

function FindingCard({ f, c, test, blocks, focus, backendUrl, authHeaders }: {
  f: Finding; c: Campaign; test?: ResearchTest; blocks: UiBlock[]; focus: boolean; backendUrl: string; authHeaders: AuthHeaders;
}) {
  const ref = useRef<HTMLElement>(null);
  const [codeOpen, setCodeOpen] = useState(false);
  useEffect(() => { if (focus) ref.current?.scrollIntoView({ behavior: "smooth", block: "center" }); }, [focus]);
  const okCells = (f.cells ?? []).filter((x) => x.status === "ok");
  return (
    <article ref={ref} id={`finding-${f.id}`} className={`${styles.card} ${styles[`f_${f.status}`] ?? ""} ${focus ? styles.cardFocus : ""}`}>
      <span className={styles.pin} aria-hidden="true" />
      <header className={styles.cardHead}>
        <span className={styles.fid}>{f.id}</span>
        <span className={styles.cardTitle}>{test?.title ?? f.test_id}</span>
        <TierSeal tier={f.tier} />
      </header>
      <p className={styles.cardMeta}>{f.test_id} · {test?.kind ?? f.kind} · {f.status}{f.round ? ` · round ${f.round}` : ""}{f.seconds ? ` · ${formatDuration(f.seconds)}` : ""}</p>
      {f.status === "running" ? (
        <p className={styles.muted}><Loader2 className={styles.spin} /> running…</p>
      ) : (
        <>
          {blocks.map((b, i) => <div key={i} className={styles.block}><UiBlockView block={b} /></div>)}
          {(f.figures ?? []).map((fig) => (
            <figure key={fig.name} className={styles.figure}>
              <ProjectImage backendUrl={backendUrl} authHeaders={authHeaders} id={c.campaign_id} name={fig.name} alt={fig.title || fig.name} />
              {fig.title && <figcaption>{fig.title}</figcaption>}
            </figure>
          ))}
          {f.summary && (
            <details className={styles.summaryBox}>
              <summary>What the run concluded</summary>
              <MarkdownRenderer content={f.summary} />
            </details>
          )}
          {f.error && f.status !== "passed" && <p className={styles.error}>{f.error}</p>}
          {okCells.length > 0 && (
            <div className={styles.codeDrawer}>
              <button type="button" onClick={() => setCodeOpen((o) => !o)} aria-expanded={codeOpen}>
                <Code2 aria-hidden="true" /> Code ({okCells.length} cell{okCells.length === 1 ? "" : "s"}){f.replication?.code ? " + separate re-implementation" : ""}
                <ChevronDown className={codeOpen ? styles.rot : ""} aria-hidden="true" />
              </button>
              {codeOpen && (
                <>
                  {okCells.map((cell, i) => (
                    <div key={i} className={styles.cell}>
                      <pre><code>{cell.code}</code></pre>
                      {cell.stdout && <pre className={styles.stdout}>{cell.stdout.slice(0, 3000)}</pre>}
                    </div>
                  ))}
                  {f.replication?.code && (
                    <div className={styles.cell}>
                      <p className={styles.replLabel}>Independent re-implementation ({f.replication.status}: {f.replication.agree} agree, {f.replication.disagree} differ)</p>
                      <pre><code>{f.replication.code}</code></pre>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
    </article>
  );
}

function Findings({ c, focus, backendUrl, authHeaders }: { c: Campaign; focus: string | null; backendUrl: string; authHeaders: AuthHeaders }) {
  const ledger = (c.ledger ?? []).filter((f) => !f.proof);
  const tests = new Map((c.charter?.tests ?? []).map((t) => [t.id, t]));
  const blocks = new Map((c.dashboard?.findings ?? []).map((d) => [d.id, blocksOf(d.blocks)]));
  if (!ledger.length) return <div className={styles.emptyNote}><FlaskConical aria-hidden="true" /><p>No findings yet. Each experiment pins its results here as it finishes.</p></div>;
  return (
    <div className={styles.wall}>
      {[...ledger].reverse().map((f) => (
        <FindingCard key={f.id} f={f} c={c} test={tests.get(f.test_id)} blocks={blocks.get(f.id) ?? []} focus={focus === f.id}
          backendUrl={backendUrl} authHeaders={authHeaders} />
      ))}
    </div>
  );
}

const TIER_RANK: Record<string, number> = { formal: 6, certified: 5, replicated: 4, computed: 3, sourced: 2, reasoned: 1 };

/** One theorem per prove test, as in the thesis: its strongest attempt (Lean-verified first, then the latest written
 *  proof). Attempts that produced no proof (a failed or cut-off run) are not theorems. */
export function bestProofs(ledger: Finding[]): Finding[] {
  const best = new Map<string, Finding>();
  for (const f of ledger) {
    const p = f.proof;
    if (!p || !["passed", "refuted"].includes(f.status) || !(p.text || p.lean_code)) continue;
    const cur = best.get(f.test_id);
    if (!cur || (TIER_RANK[f.tier] ?? 0) >= (TIER_RANK[cur.tier] ?? 0)) best.set(f.test_id, f);
  }
  return [...best.values()];
}

function Proofs({ c }: { c: Campaign }) {
  const proofs = bestProofs(c.ledger ?? []);
  if (!proofs.length) return <div className={styles.emptyNote}><Sigma aria-hidden="true" /><p>No proofs yet. Statements the plan marks for proof are written out and checked in Lean 4 here.</p></div>;
  return (
    <div className={styles.proofs}>
      {proofs.map((f, i) => (
        <article key={f.id} className={`${styles.theorem} ${f.proof?.lean_status === "verified" ? styles.lean : ""}`}>
          <header>
            <span className={styles.thmLabel}>Theorem {i + 1}</span>
            <TierSeal tier={f.tier} />
            <span className={styles.cardMeta}>{f.id} · {f.test_id} · Lean: {f.proof?.lean_status ?? "not run"}</span>
          </header>
          <div className={styles.statement}><MarkdownRenderer content={f.proof?.statement ?? ""} /></div>
          {f.proof?.text && <details open className={styles.proofText}><summary>Proof</summary><MarkdownRenderer content={f.proof.text} /></details>}
          {f.proof?.lean_code && <details className={styles.leanCode}><summary>Lean 4 source</summary><pre><code>{f.proof.lean_code}</code></pre></details>}
          {f.proof?.lean_error && <p className={styles.dNote}>Lean: {f.proof.lean_error}</p>}
        </article>
      ))}
    </div>
  );
}

// Thesis -------------------------------------------------------------------------------------------------------------

const IMG_LINE = /^!\[([^\]]*)\]\(files\/([A-Za-z0-9_.-]+)\)\s*$/;

function ThesisReader({ c, backendUrl, authHeaders }: { c: Campaign; backendUrl: string; authHeaders: AuthHeaders }) {
  const [md, setMd] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<ThesisFormat | null>(null);
  const ready = c.thesis?.status === "succeeded";
  useEffect(() => {
    if (!ready) return;
    let stop = false;
    fetchThesis(backendUrl, authHeaders, c.campaign_id, "md")
      .then(({ blob }) => blob.text()).then((t) => { if (!stop) setMd(t); })
      .catch((err) => { if (!stop) setError(errorMessage(err, "Could not load the thesis.")); });
    return () => { stop = true; };
  }, [ready, backendUrl, authHeaders, c.campaign_id, c.thesis?.written_at]);
  const download = async (format: ThesisFormat) => {
    setBusy(format);
    setError("");
    try {
      const { blob, filename } = await fetchThesis(backendUrl, authHeaders, c.campaign_id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (err) {
      setError(errorMessage(err, "The export failed."));
    } finally {
      setBusy(null);
    }
  };
  const sections = useMemo(() => {
    if (!md) return [];
    const parts = md.split(/\n(?=## )/);
    return parts.map((p, i) => ({ id: `th-${i}`, title: (p.match(/^## (.*)$/m)?.[1] ?? "").trim(), body: p }));
  }, [md]);
  if (!ready) {
    return (
      <div className={styles.emptyNote}>
        <ScrollText aria-hidden="true" />
        <p>{c.thesis?.status === "failed" ? `The thesis could not be written: ${c.thesis.error ?? ""}. Resume the project to try again.` :
          "The thesis is written when the loop reaches its conclusion (or stops): abstract, background, design, methods, results with tables and figures, theorems and proofs, discussion, conclusion, references and the code appendix."}</p>
      </div>
    );
  }
  const formats: { f: ThesisFormat; label: string }[] = [
    { f: "pdf", label: "PDF" }, { f: "docx", label: "Word" }, { f: "md", label: "Markdown" }, { f: "html", label: "HTML" }, { f: "bundle", label: "Reproducibility bundle" },
  ];
  return (
    <div className={styles.thesis}>
      <aside className={styles.toc} aria-label="Thesis contents">
        <p className={styles.tocTitle}>Contents</p>
        <ol>{sections.filter((s) => s.title).map((s) => <li key={s.id}><a href={`#${s.id}`}>{s.title}</a></li>)}</ol>
        <div className={styles.exports}>
          {formats.map(({ f, label }) => (
            <button key={f} type="button" onClick={() => void download(f)} disabled={busy !== null} className={f === "pdf" ? styles.exportMain : styles.exportBtn}>
              {busy === f ? <Loader2 className={styles.spin} /> : f === "pdf" ? <Download /> : <FileText />} {label}
            </button>
          ))}
        </div>
        {(c.thesis?.unverified?.length ?? 0) > 0 && (
          <p className={styles.dNote}>Numbers the automatic check could not match to the evidence: {c.thesis?.unverified?.join(", ")}</p>
        )}
        {error && <p className={styles.error}>{error}</p>}
      </aside>
      <article className={styles.paper}>
        {!md && !error && <p className={styles.muted}><Loader2 className={styles.spin} /> Loading the thesis…</p>}
        {sections.map((s) => (
          <section key={s.id} id={s.id} className={styles.paperSection}>
            {s.body.split("\n").reduce<{ text: string[]; out: React.ReactNode[] }>((acc, line, i, all) => {
              const m = IMG_LINE.exec(line);
              if (m || i === all.length - 1) {
                if (!m) acc.text.push(line);
                if (acc.text.join("").trim()) acc.out.push(<MarkdownRenderer key={`t${i}`} content={acc.text.join("\n")} />);
                acc.text = [];
                if (m) acc.out.push(
                  <figure key={`f${i}`} className={styles.figure}>
                    <ProjectImage backendUrl={backendUrl} authHeaders={authHeaders} id={c.campaign_id} name={m[2]} alt={m[1]} />
                    <figcaption>{m[1]}</figcaption>
                  </figure>,
                );
              } else {
                acc.text.push(line);
              }
              return acc;
            }, { text: [], out: [] }).out}
          </section>
        ))}
      </article>
    </div>
  );
}

// The lab ------------------------------------------------------------------------------------------------------------

export function ResearchLab(props: ResearchLabProps) {
  const { c, backendUrl, authHeaders, busy, linkCopied, onStop, onResume, onDelete, onCopyLink, onContinue } = props;
  const [tab, setTab] = useState<Tab>("overview");
  const [focus, setFocus] = useState<string | null>(null);
  const [goalOpen, setGoalOpen] = useState(false);
  const [next, setNext] = useState("");
  const thesisReady = c.thesis?.status === "succeeded";
  const prevThesis = useRef(thesisReady);
  useEffect(() => {
    if (thesisReady && !prevThesis.current) setTab("thesis");
    prevThesis.current = thesisReady;
  }, [thesisReady]);
  const ledger = c.ledger ?? [];
  const nFindings = ledger.filter((f) => !f.proof).length;
  const nProofs = bestProofs(ledger).length;
  const goFinding = (id: string) => {
    const f = ledger.find((x) => x.id === id);
    setTab(f?.proof ? "proofs" : "findings");
    setFocus(id);
  };
  const projectBlocks = blocksOf(c.dashboard?.project).filter((b) => b.type !== "checks" && b.type !== "table");
  const tabs: { key: Tab; label: string; icon: React.ReactNode; badge?: number | string }[] = [
    { key: "overview", label: "Plan & progress", icon: <FlaskConical /> },
    { key: "findings", label: "Findings", icon: <Sigma />, badge: nFindings || undefined },
    { key: "proofs", label: "Proofs", icon: <BookOpen />, badge: nProofs || undefined },
    { key: "thesis", label: "Thesis", icon: <ScrollText />, badge: thesisReady ? "ready" : undefined },
    { key: "literature", label: "Literature", icon: <FileText /> },
    { key: "activity", label: "Activity", icon: <Activity /> },
  ];
  return (
    <article className={styles.lab}>
      <header className={styles.hero}>
        <div className={styles.heroText}>
          <p className={styles.kicker}>
            Research project · <code>{c.campaign_id}</code>
            <button type="button" className={styles.linkBtn} onClick={onCopyLink}>
              {linkCopied ? <Check /> : <Link2 />} {linkCopied ? "Copied" : "Copy link"}
            </button>
          </p>
          <h2 className={styles.title}>{c.title}</h2>
          <p className={`${styles.goal} ${goalOpen ? styles.goalOpen : ""}`}>{c.goal}</p>
          {c.goal.length > 220 && (
            <button type="button" className={styles.more} onClick={() => setGoalOpen((o) => !o)} aria-expanded={goalOpen}>
              {goalOpen ? "Less" : "Full goal"} <ChevronDown className={goalOpen ? styles.rot : ""} />
            </button>
          )}
          <div className={styles.statusRow}>
            <span className={`${styles.status} ${styles[`s_${c.status}`] ?? ""}`}>
              {isActive(c) && <span className={styles.pulseDot} aria-hidden="true" />}{STATUS_TEXT[c.status] ?? c.status}
            </span>
            <EstimateMeter c={c} />
          </div>
          {projectBlocks.map((b, i) => <div key={i} className={styles.block}><UiBlockView block={b} /></div>)}
          {c.status === "failed" && c.error && <p className={styles.error}>{c.error}</p>}
          {c.note && <p className={styles.note}>{c.note}</p>}
          <div className={styles.actions}>
            {isActive(c) ? (
              <button type="button" className={styles.btn} disabled={busy} onClick={onStop}><Square /> Stop</button>
            ) : c.status !== "succeeded" && (
              <button type="button" className={styles.btn} disabled={busy} onClick={onResume}><RotateCcw /> Resume</button>
            )}
            {thesisReady && <button type="button" className={styles.btnPrimary} onClick={() => setTab("thesis")}><ScrollText /> Read the thesis</button>}
            <button type="button" className={`${styles.btn} ${styles.danger}`} disabled={busy} onClick={onDelete} aria-label="Delete project" title="Delete project"><Trash2 /></button>
          </div>
        </div>
        <LoopOrbit c={c} />
      </header>

      <nav className={styles.tabs} role="tablist" aria-label="Project views">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={styles.tab} onClick={() => setTab(t.key)}>
            {t.icon}<span>{t.label}</span>{t.badge !== undefined && <span className={styles.badge}>{t.badge}</span>}
          </button>
        ))}
      </nav>

      <div className={styles.panel} role="tabpanel">
        {tab === "overview" && <Overview c={c} onFinding={goFinding} />}
        {tab === "findings" && <Findings c={c} focus={focus} backendUrl={backendUrl} authHeaders={authHeaders} />}
        {tab === "proofs" && <Proofs c={c} />}
        {tab === "thesis" && <ThesisReader c={c} backendUrl={backendUrl} authHeaders={authHeaders} />}
        {tab === "literature" && (
          c.review?.response ? <div className={styles.paper}><MarkdownRenderer content={c.review.response} /></div>
            : <div className={styles.emptyNote}><BookOpen aria-hidden="true" /><p>{c.review?.status === "failed" ? `The literature review failed (${c.review.error ?? "no answer"}); the plan was made from the goal alone.` : "The literature review is running."}</p></div>
        )}
        {tab === "activity" && (
          <ol className={styles.activity}>
            {[...(c.activity ?? [])].reverse().map((a, i) => (
              <li key={`${a.t}-${i}`}>
                <time>{new Date(a.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                {a.ref && <span className={styles.ref}>{a.ref}</span>}
                <span>{a.text}</span>
              </li>
            ))}
            {!(c.activity ?? []).length && <li className={styles.muted}>Starting…</li>}
          </ol>
        )}
      </div>

      {!isActive(c) && c.charter && (
        <section className={styles.continue} aria-labelledby="lab-continue">
          <h3 id="lab-continue">Push the research further</h3>
          <p className={styles.muted}>Your instruction becomes a new deliverable; the loop plans tests for it, runs rounds until it is settled, and rewrites the thesis.</p>
          <textarea rows={3} value={next} maxLength={4000} onChange={(e) => setNext(e.target.value)} aria-label="Follow-up instruction"
            placeholder="e.g. Extend the computation to 10^7 and test whether the variance grows like ln N." />
          <button type="button" className={styles.btnPrimary} disabled={!next.trim() || busy}
            onClick={() => void onContinue(next.trim()).then(() => setNext(""))}>
            {busy ? <Loader2 className={styles.spin} /> : <Play />} Continue research
          </button>
        </section>
      )}
    </article>
  );
}

export default ResearchLab;
