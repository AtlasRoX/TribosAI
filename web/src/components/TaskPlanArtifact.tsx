"use client";

import React from "react";
import { BadgeCheck, Check, CircleDashed, X } from "lucide-react";

import styles from "./TaskPlanArtifact.module.css";

interface PlanStep {
  id?: string;
  kind?: string;
  title?: string;
  tool?: string;
  status?: "planned" | "done" | "verified" | "failed" | "not_run" | string;
  detail?: string;
}

const STATUS: Record<string, { label: string; Icon: typeof Check; tone: string }> = {
  verified: { label: "verified", Icon: BadgeCheck, tone: styles.good },
  done: { label: "done", Icon: Check, tone: styles.good },
  failed: { label: "failed", Icon: X, tone: styles.bad },
  not_run: { label: "not run", Icon: CircleDashed, tone: styles.muted },
  planned: { label: "planned", Icon: CircleDashed, tone: styles.muted },
};

/** The parts of the question, the tool that did each, and how each ended (tribos.agents.task_plan). */
export function TaskPlanArtifact({ data }: { data: { steps?: PlanStep[] } }) {
  const steps = (data?.steps || []).filter((s) => s && s.title);
  if (steps.length < 2) return null;
  const finished = steps.filter((s) => s.status === "done" || s.status === "verified").length;
  return (
    <section className={styles.plan} aria-label="Plan">
      <header className={styles.head}>
        Plan <span className={styles.count}>{finished} of {steps.length} done</span>
      </header>
      <ol className={styles.list}>
        {steps.map((s, i) => {
          const st = STATUS[s.status || "planned"] ?? STATUS.planned;
          return (
            <li key={s.id || i} className={styles.step}>
              <st.Icon className={`${styles.icon} ${st.tone}`} aria-label={st.label} />
              <span className={styles.title}>{s.title}</span>
              <span className={styles.tool}>
                {s.tool}
                {s.detail ? ` · ${s.detail}` : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
