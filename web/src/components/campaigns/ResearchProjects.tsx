"use client";

// Research projects as a full view beside the sidebar, addressable at /research and /research/<research id>.
// Left: every project with a five-segment progress bar. Right: one project, with a stage stepper, the selected
// stage's output (or its live activity while it runs), and Continue for another round once it stops. Projects run as
// background jobs on the server, so this view only reads and polls; closing it changes nothing.

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, ArrowRight, Ban, Check, CheckCircle2, ChevronDown, Circle, Download, FlaskConical, Link2, Loader2,
  PauseCircle, Play, Plus, RotateCcw, Search, Square, Trash2, XCircle,
} from "lucide-react";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { IdChip } from "@/components/IdChip";
import { errorMessage, type AuthHeaders } from "@/services/apiClient";
import {
  STAGE_INFO, cancelCampaign, continueCampaign, createCampaign, deleteCampaign, estimateGoal, fetchReport, formatDuration,
  getCampaign, isActive, listCampaigns, loopProgress, researchPath, resumeCampaign, stageActivity, stageBase,
  type ActivityStep, type Campaign, type CampaignStage, type ResearchEstimate, type StageStatus,
} from "@/services/campaignService";
import { ResearchLab } from "./ResearchLab";
import { routeForId, type AppRoute } from "@/lib/appRoute";
import { ResizeHandle } from "@/components/ResizeHandle";
import { usePanelWidth } from "@/hooks/usePanelWidth";
import styles from "./ResearchProjects.module.css";

export interface ResearchViewProps {
  backendUrl: string;
  authHeaders: AuthHeaders;
  model?: string;
  /** The project shown (from the URL); null shows the new-project form. */
  projectId: string | null;
  onOpenProject: (id: string | null) => void;
  /** An "Open by ID" entry that is not a research project (a chat conversation id). */
  onOpenRoute: (route: AppRoute) => void;
  onClose: () => void;
}

const POLL_MS = 3000;
const LIST_POLL_MS = 10000;
const EXAMPLES = [
  { title: "Collatz stopping times", goal: "Compute the Collatz stopping time for every n up to 10^6, find the record holders, and test whether the mean grows like (2/ln(4/3)) ln N; say what the numerics can and cannot show." },
  { title: "Rayleigh–Bénard onset", goal: "Compute the critical Rayleigh number and wavenumber for convection onset with rigid-rigid and free-free boundaries, and compare with the classical values 1707.76 and 657.5." },
  { title: "No-three-in-line", goal: "Find good constructions for the no-three-in-line problem on n x n grids for n = 10 to 20 and compare each with the known maximum of 2n points." },
];

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued", running: "Running", succeeded: "Finished", failed: "Stopped on an error",
  cancelled: "Stopped", interrupted: "Interrupted",
};

function StageIcon({ status, size = 16 }: { status: StageStatus; size?: number }) {
  const s = { width: size, height: size };
  switch (status) {
    case "succeeded": return <CheckCircle2 style={s} aria-label="done" />;
    case "running": return <Loader2 style={s} className={styles.spin} aria-label="running" />;
    case "failed": return <XCircle style={s} aria-label="failed" />;
    case "cancelled": return <Ban style={s} aria-label="stopped" />;
    case "interrupted": return <PauseCircle style={s} aria-label="interrupted" />;
    default: return <Circle style={s} aria-label="waiting" />;
  }
}

function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function stageSeconds(s: CampaignStage, nowMs: number): number | null {
  if (!s.started_at) return null;
  if (s.finished_at) return s.finished_at - s.started_at;
  return s.status === "running" && nowMs ? nowMs / 1000 - s.started_at : null;
}

function relTime(ts: number, nowMs: number): string {
  if (!nowMs) return "";
  const d = Math.max(0, nowMs / 1000 - ts);
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

function done(c: Campaign): number {
  return c.stages.filter((s) => s.status === "succeeded").length;
}

function currentStage(c: Campaign): CampaignStage | undefined {
  return c.stages.find((s) => s.status === "running") ?? c.stages.find((s) => s.status !== "succeeded");
}

/** The stage whose output to show first: the running one, else the newest report, else the newest finished one. */
function defaultStage(c: Campaign): string | null {
  const running = c.stages.find((s) => s.status === "running");
  if (running) return running.key;
  const reports = c.stages.filter((s) => stageBase(s) === "report" && s.status === "succeeded");
  if (reports.length) return reports[reports.length - 1].key;
  const finished = c.stages.filter((s) => s.status === "succeeded");
  return finished.length ? finished[finished.length - 1].key : c.stages[0]?.key ?? null;
}

function Progress({ c }: { c: Campaign }) {
  if (c.mode === "loop") {
    const { done: settled, total } = loopProgress(c);
    const pct = total ? Math.round((100 * settled) / total) : 0;
    return (
      <span className={styles.progress} aria-label={`${settled} of ${total} deliverables settled`}>
        <span className={`${styles.seg} ${styles.seg_succeeded}`} style={{ flex: `0 0 ${pct}%` }} />
        <span className={styles.seg} style={{ flex: 1 }} />
      </span>
    );
  }
  return (
    <span className={styles.progress} aria-label={`${done(c)} of ${c.stages.length} stages done`}>
      {c.stages.map((s) => <span key={s.key} className={`${styles.seg} ${styles[`seg_${s.status}`] ?? ""}`} />)}
    </span>
  );
}

export function ResearchProjects(props: ResearchViewProps) {
  const { backendUrl, authHeaders, model, projectId, onOpenProject, onOpenRoute, onClose } = props;
  const [items, setItems] = useState<Campaign[] | null>(null);
  const [detail, setDetail] = useState<Campaign | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  // Background polling failures are kept apart from action errors: they clear themselves when the server answers.
  const [pollError, setPollError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [goalOpen, setGoalOpen] = useState(false);
  const [activity, setActivity] = useState<ActivityStep[]>([]);
  const [pollKey, setPollKey] = useState(0);
  const [jump, setJump] = useState("");
  const [jumpError, setJumpError] = useState("");
  const [linkCopied, setLinkCopied] = useState(false);
  // New project
  const [goal, setGoal] = useState("");
  const [stages, setStages] = useState<string[]>(STAGE_INFO.map((s) => s.key));
  const [effort, setEffort] = useState<"medium" | "high">("high");
  const [web, setWeb] = useState(true);
  const [mode, setMode] = useState<"loop" | "stages">("loop");
  const [goalEstimate, setGoalEstimate] = useState<ResearchEstimate | null>(null);
  // Continue
  const [nextStep, setNextStep] = useState("");
  const listPanel = usePanelWidth("research-list", { initial: 300, min: 220, max: 520, maxViewport: 0.4 });
  const activityRef = useRef<{ job: string; seq: number; steps: Map<string, ActivityStep> }>({ job: "", seq: 0, steps: new Map() });

  useEffect(() => {
    if (mode !== "loop" || goal.trim().length < 12) { setGoalEstimate(null); return; }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      estimateGoal(backendUrl, authHeaders, goal.trim(), ctl.signal).then(setGoalEstimate).catch(() => undefined);
    }, 450);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [goal, mode, backendUrl, authHeaders]);

  const refreshList = useCallback(async () => {
    try {
      setItems(await listCampaigns(backendUrl, authHeaders));
      setPollError("");  // the server answers again: a connection error shown earlier is over
    } catch (err) {
      setPollError(errorMessage(err, "Could not load research projects."));
    }
  }, [backendUrl, authHeaders]);

  // The list, refreshed while any project is active.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stop = false;
    const tick = async () => {
      await refreshList();
      if (!stop) timer = setTimeout(tick, LIST_POLL_MS);
    };
    void tick();
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [refreshList]);

  // The open project, polled while active, with its running stage's activity.
  useEffect(() => {
    setDetail((d) => (d && d.campaign_id === projectId ? d : null));
    setMissing(false);
    if (!projectId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const tick = async () => {
      try {
        const c = await getCampaign(backendUrl, authHeaders, projectId, controller.signal);
        if (stop) return;
        setDetail(c);
        setNow(Date.now());
        setItems((list) => list?.map((x) => (x.campaign_id === c.campaign_id ? { ...x, ...c } : x)) ?? list);
        const running = c.stages.find((s) => s.status === "running" && s.job_id);
        if (running?.job_id) {
          const a = activityRef.current;
          if (a.job !== running.job_id) activityRef.current = { job: running.job_id, seq: 0, steps: new Map() };
          const res = await stageActivity(backendUrl, authHeaders, running.job_id, activityRef.current.seq, controller.signal).catch(() => null);
          if (res && !stop) {
            activityRef.current.seq = res.lastSeq;
            for (const st of res.steps) activityRef.current.steps.set(st.id, st);
            setActivity([...activityRef.current.steps.values()]);
          }
        }
        setPollError("");
        failures = 0;
        if (isActive(c)) timer = setTimeout(tick, POLL_MS);
      } catch (err) {
        if (stop || controller.signal.aborted) return;
        if ((err as { status?: number }).status === 404) { setMissing(true); return; }
        // A restart or a dropped connection: say so, and keep trying (backing off to 30 s) instead of going quiet.
        setPollError(errorMessage(err, "Could not load the project."));
        failures += 1;
        timer = setTimeout(tick, Math.min(30000, POLL_MS * 2 ** Math.min(failures, 4)));
      }
    };
    let failures = 0;
    void tick();
    return () => { stop = true; controller.abort(); if (timer) clearTimeout(timer); };
  }, [projectId, backendUrl, authHeaders, pollKey]);

  // Show the most useful stage when a project opens, and follow the run as it moves to the next stage.
  const runningKey = detail?.stages.find((s) => s.status === "running")?.key ?? null;
  useEffect(() => {
    if (detail) setSelected(defaultStage(detail));
  }, [detail?.campaign_id, runningKey, detail?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      after?.();
      await refreshList();
      setPollKey((k) => k + 1);
    } catch (err) {
      setError(errorMessage(err, "That did not work."));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!goal.trim() || busy || (mode === "stages" && !stages.length)) return;
    await act(async () => {
      const c = await createCampaign(backendUrl, authHeaders, {
        goal: goal.trim(), effort_level: effort, enable_web_search: web, mode,
        ...(mode === "stages" ? { stages: STAGE_INFO.map((s) => s.key).filter((k) => stages.includes(k)) } : {}),
        ...(model ? { model } : {}),
      });
      setGoal("");
      onOpenProject(c.campaign_id);
    });
  };

  const openJump = () => {
    const route = routeForId(jump);
    if (!route) { setJumpError("Paste a research ID (cmp_…), a conversation ID or a link."); return; }
    setJumpError("");
    setJump("");
    if (route.kind === "research") onOpenProject(route.id);
    else onOpenRoute(route);
  };

  const download = async (c: Campaign) => {
    try {
      const text = await fetchReport(backendUrl, authHeaders, c.campaign_id);
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${c.title.replace(/[^\w\- ]+/g, "").trim().slice(0, 60) || c.campaign_id}.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(errorMessage(err, "Could not download the report."));
    }
  };

  const copyLink = async (id: string) => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${researchPath(id)}`);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 1400);
    } catch {
      // clipboard blocked; the address bar holds the same link
    }
  };

  const rounds = useMemo(() => {
    const out = new Map<number, CampaignStage[]>();
    for (const s of detail?.stages ?? []) {
      const r = s.round ?? 1;
      out.set(r, [...(out.get(r) ?? []), s]);
    }
    return [...out.entries()];
  }, [detail]);

  const shown = detail?.stages.find((s) => s.key === selected) ?? null;
  const stageIndex = detail && shown ? detail.stages.indexOf(shown) : -1;
  const blocker = detail && stageIndex > 0 ? detail.stages.slice(0, stageIndex).find((s) => s.status !== "succeeded") : undefined;
  const elapsed = detail ? detail.stages.reduce((t, s) => t + (stageSeconds(s, now) ?? 0), 0) : 0;

  return (
    <div className={styles.view}>
      <header className={styles.topbar}>
        <button type="button" className={styles.back} onClick={onClose} title="Back to chat">
          <ArrowLeft style={{ width: 16, height: 16 }} />
        </button>
        <FlaskConical className={styles.brandIcon} aria-hidden="true" />
        <h1 className={styles.brand}>Research projects</h1>
        <form className={styles.jump} onSubmit={(e) => { e.preventDefault(); openJump(); }} role="search">
          <Search className={styles.jumpIcon} aria-hidden="true" />
          <input value={jump} onChange={(e) => { setJump(e.target.value); setJumpError(""); }}
            placeholder="Open by ID: cmp_…, a conversation ID or a link" aria-label="Open by research or conversation ID"
            className={styles.jumpInput} spellCheck={false} />
          {jump && <button type="submit" className={styles.jumpGo} aria-label="Open"><ArrowRight style={{ width: 14, height: 14 }} /></button>}
        </form>
        <button type="button" className={styles.btnPrimary} onClick={() => onOpenProject(null)}>
          <Plus style={{ width: 14, height: 14 }} /> <span>New project</span>
        </button>
      </header>
      {jumpError && <p className={styles.jumpError} role="alert">{jumpError}</p>}

      <div className={styles.body}>
        <div className={styles.listWrap} style={{ width: listPanel.width }}>
        <nav className={styles.list} aria-label="Research projects">
          {items === null && <p className={styles.muted}><Loader2 className={styles.spin} style={{ width: 14, height: 14 }} /> Loading…</p>}
          {items?.length === 0 && <p className={styles.muted}>No projects yet. Start one on the right.</p>}
          {items?.map((c) => {
            const active = c.campaign_id === projectId;
            const at = currentStage(c);
            return (
              <button key={c.campaign_id} type="button" onClick={() => onOpenProject(c.campaign_id)}
                className={`${styles.item} ${active ? styles.itemActive : ""}`} aria-current={active ? "page" : undefined}>
                <span className={styles.itemTitle}>{c.title}</span>
                <span className={styles.itemRow}>
                  <Progress c={c} />
                  <span className={`${styles.itemStatus} ${styles[`text_${c.status}`] ?? ""}`}>
                    {c.mode === "loop"
                      ? `${STATUS_LABEL[c.status] ?? c.status}${isActive(c) && c.summary?.phase ? ` · ${c.summary.phase}` : ""}`
                      : isActive(c) && at ? `${STATUS_LABEL[c.status]} · ${at.title}` : STATUS_LABEL[c.status] ?? c.status}
                  </span>
                </span>
                <span className={styles.itemMeta}>
                  <code>{c.campaign_id}</code>
                  <span>{relTime(c.created_at, now || c.updated_at * 1000)}</span>
                </span>
              </button>
            );
          })}
        </nav>
        <ResizeHandle edge="right" panel={listPanel} label="Project list width" />
        </div>

        <main className={styles.main}>
          {error && <p className={styles.error} role="alert">{error}</p>}
          {!error && pollError && <p className={styles.error} role="status">{pollError} Retrying…</p>}

          {!projectId && (
            <section className={styles.create} aria-labelledby="rp-new">
              <h2 id="rp-new" className={styles.createTitle}>What should Tribos investigate?</h2>
              <p className={styles.lede}>
                {mode === "loop"
                  ? "Tribos reviews the literature, writes a research plan (deliverables, hypotheses, tests), then runs rounds of experiments, proofs and checks until every deliverable is settled or progress stops, and writes a thesis with proofs, figures and the code behind every number. It runs in the background and resumes after a restart."
                  : "A project runs as a background job through five fixed stages, each a full research run with search, code, simulation and verification."}
              </p>
              <textarea className={styles.goal} rows={6} maxLength={4000} value={goal} autoFocus
                onChange={(e) => setGoal(e.target.value)} aria-label="Research goal"
                placeholder="State the question, what to compute or test, and what would count as a result."
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void start(); }} />
              <div className={styles.examples}>
                {EXAMPLES.map((ex) => (
                  <button key={ex.title} type="button" className={styles.example} onClick={() => setGoal(ex.goal)}>
                    {ex.title}
                  </button>
                ))}
              </div>
              <div className={styles.field}>
                <span className={styles.fieldLabel} id="rp-mode">Method</span>
                <div className={styles.segmented} role="radiogroup" aria-labelledby="rp-mode">
                  {([["loop", "Adaptive research loop"], ["stages", "Classic five stages"]] as const).map(([value, label]) => (
                    <button key={value} type="button" role="radio" aria-checked={mode === value} className={styles.segment}
                      onClick={() => setMode(value)}>
                      {label}
                    </button>
                  ))}
                </div>
                {mode === "loop" && goalEstimate && (
                  <span className={styles.muted} title={goalEstimate.basis}>
                    Estimated {formatDuration(goalEstimate.low_s)}–{formatDuration(goalEstimate.high_s)} (refined once the plan exists)
                  </span>
                )}
              </div>
              {mode === "stages" && <div className={styles.field}>
                <span className={styles.fieldLabel} id="rp-stages">Stages</span>
                <div className={styles.toggles} role="group" aria-labelledby="rp-stages">
                  {STAGE_INFO.map((s, i) => {
                    const on = stages.includes(s.key);
                    return (
                      <button key={s.key} type="button" aria-pressed={on} title={s.hint} className={styles.toggle}
                        onClick={() => setStages((cur) => (on ? cur.filter((k) => k !== s.key) : [...cur, s.key]))}>
                        <span className={styles.toggleNum}>{i + 1}</span>{s.title}
                      </button>
                    );
                  })}
                </div>
              </div>}
              <div className={styles.createFoot}>
                <div className={styles.field}>
                  <span className={styles.fieldLabel} id="rp-depth">Depth</span>
                  <div className={styles.segmented} role="radiogroup" aria-labelledby="rp-depth">
                    {([["high", "Thorough"], ["medium", "Faster"]] as const).map(([value, label]) => (
                      <button key={value} type="button" role="radio" aria-checked={effort === value} className={styles.segment}
                        onClick={() => setEffort(value)}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className={styles.field}>
                  <span className={styles.fieldLabel} id="rp-sources">Sources</span>
                  <button type="button" aria-pressed={web} aria-labelledby="rp-sources" className={styles.toggle}
                    onClick={() => setWeb((w) => !w)} title="Search papers and the web in the review and later stages">
                    {web ? "Literature search on" : "Literature search off"}
                  </button>
                </div>
                <button type="button" className={`${styles.btnPrimary} ${styles.push}`} disabled={!goal.trim() || (mode === "stages" && !stages.length) || busy} onClick={() => void start()}>
                  {busy ? <Loader2 className={styles.spin} style={{ width: 14, height: 14 }} /> : <Play style={{ width: 14, height: 14 }} />}
                  Start project
                </button>
              </div>
            </section>
          )}

          {projectId && missing && (
            <section className={styles.emptyState}>
              <h2>No research project with this ID</h2>
              <p><code>{projectId}</code> does not exist, or belongs to another account.</p>
              <button type="button" className={styles.btn} onClick={() => onOpenProject(null)}>Start a new project</button>
            </section>
          )}

          {projectId && !missing && !detail && <p className={styles.muted}><Loader2 className={styles.spin} style={{ width: 14, height: 14 }} /> Loading project…</p>}

          {detail && detail.mode === "loop" && (
            <ResearchLab
              c={detail} backendUrl={backendUrl} authHeaders={authHeaders} busy={busy} linkCopied={linkCopied}
              onCopyLink={() => void copyLink(detail.campaign_id)}
              onStop={() => void act(() => cancelCampaign(backendUrl, authHeaders, detail.campaign_id))}
              onResume={() => void act(() => resumeCampaign(backendUrl, authHeaders, detail.campaign_id))}
              onDelete={() => {
                if (window.confirm(`Delete "${detail.title}", its findings and its thesis?`)) {
                  void act(() => deleteCampaign(backendUrl, authHeaders, detail.campaign_id), () => onOpenProject(null));
                }
              }}
              onContinue={(instruction) => act(() => continueCampaign(backendUrl, authHeaders, detail.campaign_id, instruction))}
            />
          )}

          {detail && detail.mode !== "loop" && (
            <article className={styles.project}>
              <div className={styles.crumbs}>
                <span>Research</span><span aria-hidden="true">/</span>
                <IdChip label="Research ID" id={detail.campaign_id} />
                <button type="button" className={styles.linkBtn} onClick={() => void copyLink(detail.campaign_id)} title="Copy a link to this project">
                  {linkCopied ? <Check style={{ width: 12, height: 12 }} /> : <Link2 style={{ width: 12, height: 12 }} />}
                  {linkCopied ? "Link copied" : "Copy link"}
                </button>
              </div>

              <div className={styles.head}>
                <div className={styles.headText}>
                  <h2 className={styles.title}>{detail.title}</h2>
                  <p className={styles.meta}>
                    <span className={`${styles.pill} ${styles[`pill_${detail.status}`] ?? ""}`}>
                      {isActive(detail) && <span className={styles.pulse} aria-hidden="true" />}
                      {STATUS_LABEL[detail.status] ?? detail.status}
                    </span>
                    <span>{done(detail)} of {detail.stages.length} stages</span>
                    {elapsed > 0 && <span>{fmtDuration(elapsed)} of work</span>}
                    {typeof detail.rounds === "number" && detail.rounds > 1 && <span>round {detail.rounds}</span>}
                  </p>
                </div>
                <div className={styles.actions}>
                  {isActive(detail) ? (
                    <button type="button" className={styles.btn} disabled={busy}
                      onClick={() => void act(() => cancelCampaign(backendUrl, authHeaders, detail.campaign_id))}>
                      <Square style={{ width: 13, height: 13 }} /> Stop
                    </button>
                  ) : detail.status !== "succeeded" && (
                    <button type="button" className={styles.btn} disabled={busy}
                      onClick={() => void act(() => resumeCampaign(backendUrl, authHeaders, detail.campaign_id))}>
                      <RotateCcw style={{ width: 13, height: 13 }} /> Resume
                    </button>
                  )}
                  <button type="button" className={styles.btn} disabled={!done(detail)} onClick={() => void download(detail)}
                    title="The report and every stage as Markdown">
                    <Download style={{ width: 13, height: 13 }} /> Report
                  </button>
                  <button type="button" className={`${styles.btn} ${styles.iconOnly} ${styles.danger}`} disabled={busy}
                    title="Delete project" aria-label="Delete project"
                    onClick={() => {
                      if (window.confirm(`Delete "${detail.title}" and its stage records?`)) {
                        void act(() => deleteCampaign(backendUrl, authHeaders, detail.campaign_id), () => onOpenProject(null));
                      }
                    }}>
                    <Trash2 style={{ width: 14, height: 14 }} />
                  </button>
                </div>
              </div>

              <div className={`${styles.goalBox} ${goalOpen ? styles.goalOpen : ""}`}>
                <span className={styles.goalLabel}>Goal</span>
                <p className={styles.goalText}>{detail.goal}</p>
                {detail.goal.length > 180 && (
                  <button type="button" className={styles.more} onClick={() => setGoalOpen((o) => !o)} aria-expanded={goalOpen}>
                    {goalOpen ? "Show less" : "Show full goal"} <ChevronDown style={{ width: 13, height: 13 }} />
                  </button>
                )}
              </div>

              {((detail.note && !detail.note.startsWith("Round ")) || (detail.error && detail.status !== "succeeded")) && (
                <p className={`${styles.banner} ${detail.error && detail.status === "failed" ? styles.bannerBad : ""}`} role="status">
                  {detail.status === "failed" ? detail.error : detail.note}
                </p>
              )}

              {rounds.map(([round, list]) => (
                <div key={round} className={styles.round}>
                  {rounds.length > 1 && (
                    <p className={styles.roundLabel}>
                      {round === 1 ? "Round 1" : `Round ${round}`}
                      {round > 1 && list[0]?.instruction && <span> · {list[0].instruction}</span>}
                    </p>
                  )}
                  <ol className={styles.stepper}>
                    {list.map((s) => {
                      const secs = stageSeconds(s, now);
                      const isSel = s.key === selected;
                      return (
                        <li key={s.key} className={`${styles.step} ${styles[`step_${s.status}`] ?? ""} ${isSel ? styles.stepSel : ""}`}>
                          <button type="button" onClick={() => setSelected(s.key)} aria-pressed={isSel}
                            title={s.error && s.status !== "succeeded" ? s.error : s.title}>
                            <span className={styles.stepIcon}><StageIcon status={s.status} /></span>
                            <span className={styles.stepName}>{s.title.replace(/ \(round \d+\)$/, "")}</span>
                            <span className={styles.stepTime}>{secs !== null ? fmtDuration(secs) : s.status === "pending" ? "waiting" : ""}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ))}

              {shown && (
                <section className={styles.output} aria-label={shown.title}>
                  <header className={styles.outputHead}>
                    <h3>{shown.title}</h3>
                    {shown.status === "running" && <span className={styles.live}><span className={styles.pulse} /> live</span>}
                  </header>
                  {shown.status === "succeeded" && shown.response && <div className={styles.markdown}><MarkdownRenderer content={shown.response} /></div>}
                  {shown.status === "running" && (
                    <ul className={styles.activity}>
                      {activity.length === 0 && <li className={styles.muted}>Starting…</li>}
                      {activity.slice(-10).map((a) => (
                        <li key={a.id} className={styles[`act_${a.status}`] ?? ""}>
                          {a.status === "running" ? <Loader2 className={styles.spin} style={{ width: 13, height: 13 }} />
                            : a.status === "error" ? <XCircle style={{ width: 13, height: 13 }} />
                              : <Check style={{ width: 13, height: 13 }} />}
                          <span>{a.title}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {shown.status === "pending" && (
                    <p className={styles.muted}>
                      {blocker ? `Starts after ${blocker.title}${blocker.status === "running" ? " finishes" : ""}.` : "Waiting to start."}
                    </p>
                  )}
                  {["failed", "cancelled", "interrupted"].includes(shown.status) && (
                    <p className={styles.muted}>{shown.error || STATUS_LABEL[shown.status]}. {detail.status !== "succeeded" && !isActive(detail) && "Resume runs it again; finished stages are kept."}</p>
                  )}
                </section>
              )}

              {!isActive(detail) && (
                <section className={styles.continue} aria-labelledby="rp-continue">
                  <h3 id="rp-continue">Continue this project</h3>
                  <p className={styles.muted}>
                    Runs another round of experiments, analysis and report, building on everything found so far.
                  </p>
                  <textarea rows={3} className={styles.goal} value={nextStep} maxLength={4000}
                    onChange={(e) => setNextStep(e.target.value)} aria-label="What the next round should do"
                    placeholder="e.g. Push the computation to 10^8 and test the variance prediction as well." />
                  <button type="button" className={`${styles.btnPrimary} ${styles.push}`} disabled={!nextStep.trim() || busy}
                    onClick={() => void act(async () => {
                      await continueCampaign(backendUrl, authHeaders, detail.campaign_id, nextStep.trim());
                      setNextStep("");
                    })}>
                    {busy ? <Loader2 className={styles.spin} style={{ width: 15, height: 15 }} /> : <Play style={{ width: 15, height: 15 }} />}
                    Continue research
                  </button>
                </section>
              )}
            </article>
          )}
        </main>
      </div>
    </div>
  );
}

export default ResearchProjects;
