"use client";

// The drag handle on a resizable panel's edge. Drag it, or focus it and use the arrow keys (Shift for bigger steps,
// Home/End for the limits); double-click restores the default width. It sits on the panel's `edge`, inside the
// nearest positioned ancestor. While dragging, <html data-resizing> turns off width transitions and text selection.

import React, { useRef } from "react";
import type { PanelWidth } from "@/hooks/usePanelWidth";
import styles from "./ResizeHandle.module.css";

export interface ResizeHandleProps {
  /** The panel edge the handle sits on: "right" for a panel on the left (sidebar), "left" for one on the right. */
  edge: "left" | "right";
  panel: PanelWidth;
  label: string;
  className?: string;
}

const STEP = 16;
const BIG_STEP = 64;

export function ResizeHandle({ edge, panel, label, className }: ResizeHandleProps) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const clamp = (w: number) => Math.max(panel.min, Math.min(panel.max, w));

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, w: panel.width };
    document.documentElement.dataset.resizing = "true";
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    panel.setWidth(clamp(drag.current.w + (edge === "right" ? dx : -dx)));
  };
  const end = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    delete document.documentElement.dataset.resizing;
  };
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const grow = edge === "right" ? "ArrowRight" : "ArrowLeft";
    const shrink = edge === "right" ? "ArrowLeft" : "ArrowRight";
    let next: number | null = null;
    if (e.key === grow) next = panel.width + step;
    else if (e.key === shrink) next = panel.width - step;
    else if (e.key === "Home") next = panel.min;
    else if (e.key === "End") next = panel.max;
    if (next === null) return;
    e.preventDefault();
    panel.setWidth(clamp(next));
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={panel.width}
      aria-valuemin={panel.min}
      aria-valuemax={panel.max}
      tabIndex={0}
      title={`${label}: drag to resize, double-click to reset`}
      className={`${styles.handle} ${edge === "right" ? styles.right : styles.left} ${className ?? ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={panel.reset}
      onKeyDown={onKeyDown}
    />
  );
}

export default ResizeHandle;
