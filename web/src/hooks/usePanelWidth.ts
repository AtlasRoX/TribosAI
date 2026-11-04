"use client";

// A resizable panel's width in pixels, remembered per panel in this browser (tribos.width.<id>). The first render uses
// `initial`, so server and client markup match; the saved width is applied after mount. The upper bound also keeps
// the panel within `maxViewport` of the window, so a width saved on a large screen never swallows a small one.

import { useCallback, useEffect, useState } from "react";

export interface PanelWidthOptions {
  initial: number;
  min: number;
  max: number;
  /** Largest share of the window the panel may take (default 0.75). */
  maxViewport?: number;
}

export interface PanelWidth {
  width: number;
  min: number;
  max: number;
  setWidth: (px: number) => void;
  reset: () => void;
}

const key = (id: string) => `tribos.width.${id}`;

export function usePanelWidth(id: string, { initial, min, max, maxViewport = 0.75 }: PanelWidthOptions): PanelWidth {
  const [width, setRaw] = useState(initial);
  const [limit, setLimit] = useState(max);

  useEffect(() => {
    const fit = () => setLimit(Math.max(min, Math.min(max, Math.floor(window.innerWidth * maxViewport))));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [min, max, maxViewport]);

  useEffect(() => {
    try {
      const saved = Number(window.localStorage.getItem(key(id)));
      if (Number.isFinite(saved) && saved > 0) setRaw(saved);
    } catch {
      // storage blocked: the default width
    }
  }, [id]);

  const setWidth = useCallback((px: number) => {
    const next = Math.round(px);
    setRaw(next);
    try {
      window.localStorage.setItem(key(id), String(next));
    } catch {
      // the width is a convenience
    }
  }, [id]);

  const reset = useCallback(() => {
    setRaw(initial);
    try {
      window.localStorage.removeItem(key(id));
    } catch {
      // nothing saved
    }
  }, [id, initial]);

  return { width: Math.max(min, Math.min(limit, width)), min, max: limit, setWidth, reset };
}
