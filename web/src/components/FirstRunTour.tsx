"use client";

import React, { useCallback, useEffect, useLayoutEffect, useState } from "react";

const KEY = "tribos_tour_v1";

interface Step {
  selector: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    selector: ".composer textarea",
    title: "Ask in plain words or LaTeX",
    body: "Type / for commands like /derive or /simulate, Ctrl+M to insert a formula, and ↑ to edit your last question.",
  },
  {
    selector: 'button[aria-label="Add an image of the question"]',
    title: "Questions from images",
    body: "Paste a screenshot, drop a photo anywhere, or pick a file. You review the text read from it before sending.",
  },
  {
    selector: ".composer",
    title: "Auto picks the approach",
    body: "As you type, the chip under the box shows the approach Auto will take and roughly how long it takes.",
  },
  {
    selector: "main",
    title: "Everything from the keyboard",
    body: "Ctrl+K opens commands and searches every conversation, equations included. [ and ] collapse or expand the result cards.",
  },
];

/** A four-step introduction on the first visit; skippable, shown once per browser. */
export function FirstRunTour() {
  const [step, setStep] = useState<number | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    let seen = true;
    try {
      seen = window.localStorage.getItem(KEY) === "done";
    } catch {
      // storage blocked: no tour rather than one on every visit
    }
    if (seen) return;
    const t = window.setTimeout(() => setStep(0), 1500);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    // "Show the tour" from the command palette works even after it was dismissed.
    const restart = () => setStep(0);
    window.addEventListener("tribos:tour", restart);
    return () => window.removeEventListener("tribos:tour", restart);
  }, []);

  const finish = useCallback(() => {
    setStep(null);
    try {
      window.localStorage.setItem(KEY, "done");
    } catch {
      // nothing to remember it in
    }
  }, []);

  useLayoutEffect(() => {
    if (step === null) return;
    const measure = () => {
      const el = document.querySelector(STEPS[step].selector);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [step]);

  useEffect(() => {
    if (step === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
      if (e.key === "ArrowRight" || e.key === "Enter") setStep((s) => (s === null ? s : s + 1 >= STEPS.length ? (finish(), null) : s + 1));
      if (e.key === "ArrowLeft") setStep((s) => (s ? s - 1 : s));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, finish]);

  if (step === null) return null;
  const s = STEPS[step];
  const big = rect && rect.height > window.innerHeight * 0.5;
  const below = rect ? rect.top < window.innerHeight / 2 && !big : true;
  const cardStyle: React.CSSProperties = rect && !big
    ? {
        left: Math.min(Math.max(16, rect.left), window.innerWidth - 336),
        top: below ? rect.bottom + 12 : undefined,
        bottom: below ? undefined : window.innerHeight - rect.top + 12,
      }
    : { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };

  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-label={`Tour step ${step + 1} of ${STEPS.length}`}>
      {rect && !big && (
        <div
          className="tour-spot"
          style={{ left: rect.left - 6, top: rect.top - 6, width: rect.width + 12, height: rect.height + 12 }}
        />
      )}
      {(!rect || big) && <div className="tour-dim" />}
      <div className="tour-card" style={cardStyle}>
        <div className="tour-step">
          {step + 1} of {STEPS.length}
        </div>
        <div className="tour-title">{s.title}</div>
        <p className="tour-body">{s.body}</p>
        <div className="tour-actions">
          <button type="button" className="tour-skip" onClick={finish}>
            Skip
          </button>
          {step > 0 && (
            <button type="button" className="tour-skip" onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          <button
            type="button"
            className="tour-next"
            autoFocus
            onClick={() => (step + 1 >= STEPS.length ? finish() : setStep(step + 1))}
          >
            {step + 1 >= STEPS.length ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
