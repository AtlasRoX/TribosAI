"use client";

import React, { useMemo, useState } from "react";
import { Check, Code2, Copy, Download } from "lucide-react";

import styles from "./PlotArtifact.module.css";

interface PlotFigure {
  name?: string;
  png_base64?: string;
  axes?: { title?: string; xlabel?: string; ylabel?: string }[];
}

export interface PlotData {
  code?: string;
  stdout?: string;
  figures?: PlotFigure[];
  seconds?: number;
}

const ICON = { width: 14, height: 14 } as const;

function figureLabel(fig: PlotFigure, i: number): string {
  const title = fig.axes?.map((a) => a.title).find(Boolean);
  return title || `Figure ${i + 1}`;
}

/** "name = value" lines the plotting script printed: the numbers a reader checks against the figure. */
function printedValues(stdout: string | undefined): string[] {
  return (stdout || "")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && l.length <= 160)
    .slice(0, 8);
}

function download(b64: string, name: string) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A plot drawn for the question (matplotlib in the sandbox): the figure, its printed values, and its code. */
export function PlotArtifact({ data }: { data: PlotData }) {
  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const figures = useMemo(
    () => (data.figures || []).filter((f) => f.png_base64).map((f) => ({ ...f, b64: String(f.png_base64).replace(/\s+/g, "") })),
    [data.figures]
  );
  const values = printedValues(data.stdout);
  if (!figures.length) return null;

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(data.code || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <figure className={styles.plot}>
      {figures.map((f, i) => (
        // eslint-disable-next-line @next/next/no-img-element -- an inline data: URL; next/image cannot optimise it
        <img
          key={f.name || i}
          className={styles.image}
          src={`data:image/png;base64,${f.b64}`}
          alt={figureLabel(f, i)}
          loading="lazy"
        />
      ))}
      <figcaption className={styles.bar}>
        {values.length > 0 && (
          <span className={styles.values} title="Values the plotting script printed">
            {values.join(" · ")}
          </span>
        )}
        <span className={styles.actions}>
          {data.code && (
            <button type="button" className="msg-action-btn" onClick={() => setShowCode((v) => !v)} aria-expanded={showCode}>
              <Code2 style={ICON} aria-hidden="true" /> {showCode ? "Hide code" : "Show code"}
            </button>
          )}
          {data.code && (
            <button type="button" className="msg-action-btn msg-icon-btn" onClick={copyCode} aria-label={copied ? "Code copied" : "Copy code"} title={copied ? "Code copied" : "Copy code"}>
              {copied ? <Check style={{ ...ICON, color: "var(--nvidia-green)" }} /> : <Copy style={ICON} />}
            </button>
          )}
          <button
            type="button"
            className="msg-action-btn msg-icon-btn"
            onClick={() => figures.forEach((f, i) => download(f.b64, f.name || `plot_${i + 1}.png`))}
            aria-label="Download PNG"
            title="Download PNG"
          >
            <Download style={ICON} />
          </button>
        </span>
      </figcaption>
      {showCode && data.code && (
        <pre className={styles.code}>
          <code>{data.code}</code>
        </pre>
      )}
    </figure>
  );
}
