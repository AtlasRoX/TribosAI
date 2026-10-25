"use client";

// The sidebar's layout state: collapsed to its icon rail (remembered in this browser), and on narrow screens a drawer
// that opens over the conversation and closes with Esc.

import { useCallback, useEffect, useState } from "react";

const COLLAPSED_KEY = "tribos.sidebar.collapsed";
const NARROW_QUERY = "(max-width: 900px)";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function useSidebarState() {
  const [collapsed, setCollapsedState] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setCollapsedState(readCollapsed());
    const query = window.matchMedia(NARROW_QUERY);
    const sync = () => {
      setNarrow(query.matches);
      if (!query.matches) setDrawerOpen(false);
    };
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      // the preference is a convenience; a blocked store simply does not remember it
    }
  }, []);

  /** On a narrow screen the sidebar is a drawer; elsewhere it is open or collapsed to the rail. */
  const expanded = narrow ? drawerOpen : !collapsed;
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const toggle = useCallback(() => {
    if (narrow) setDrawerOpen((o) => !o);
    else setCollapsed(!collapsed);
  }, [narrow, collapsed, setCollapsed]);

  return { expanded, narrow, drawerOpen, collapsed, toggle, closeDrawer, setCollapsed };
}
