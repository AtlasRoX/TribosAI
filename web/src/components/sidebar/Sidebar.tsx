"use client";

// The ChatGPT-style sidebar: brand and collapse toggle (an icon rail with tooltips when collapsed), New chat, Search
// chats (the command palette), the Projects section (each expandable to its chats, shared ones marked), the history
// grouped by recency with pinned chats on top, and a profile menu that keeps every setting reachable. On a narrow
// screen it is a drawer with a focus trap, closed with Esc or the backdrop. Grouping lives in lib/sidebarData.ts.

import React, { useEffect, useMemo, useState } from "react";
import {
  Brain, ChevronDown, ChevronRight, FlaskConical, FolderPlus, MessageSquareText, Moon, PanelLeft, PanelLeftClose, Plus,
  Search, Settings, SquarePen,
} from "lucide-react";
import { groupThreads, safeColor, threadsIn } from "@/lib/sidebarData";
import { useFocusTrap } from "@/lib/useFocusTrap";
import type { InvestigationItem } from "@/services/localStorageService";
import type { Project } from "@/types/agentic";
import { ChatRow, type ChatRowHandlers } from "./ChatRow";
import { ResizeHandle } from "@/components/ResizeHandle";
import type { PanelWidth } from "@/hooks/usePanelWidth";
import styles from "./Sidebar.module.css";

export interface SidebarProps extends ChatRowHandlers {
  expanded: boolean;
  narrow: boolean;
  onToggle: () => void;
  onCloseDrawer: () => void;
  threads: InvestigationItem[];
  activeThreadId: string;
  streamingThreadId: string | null;
  projects: Project[];
  projectsAvailable: boolean;
  activeProjectId: string | null;
  onNewChat: () => void;
  onSearch: () => void;
  onNewProject: () => void;
  onOpenProject: (id: string) => void;
  onNewChatInProject: (id: string) => void;
  onOpenSettings: () => void;
  onOpenMemory: () => void;
  onToggleTheme: () => void;
  /** Opens the long-running research projects window; hidden when absent. */
  onOpenResearch?: () => void;
  /** The expanded sidebar's resizable width (hooks/usePanelWidth); fixed when absent. */
  panel?: PanelWidth;
}

function ProjectBadge({ project }: { project: Project }) {
  const color = safeColor(project.color);
  return (
    <span className={styles.projectIcon} style={{ background: `${color}22`, color }} aria-hidden="true">
      {project.icon || "📁"}
    </span>
  );
}

export function Sidebar(props: SidebarProps) {
  const { expanded, narrow, threads, projects, activeThreadId, streamingThreadId } = props;
  const [openProjects, setOpenProjects] = useState<Record<string, boolean>>({});
  const [profileOpen, setProfileOpen] = useState(false);
  const trapRef = useFocusTrap<HTMLElement>(narrow && expanded);
  // "Today" is decided on the client after mount (the threads load from browser storage then, and a clock read during
  // prerendering would freeze the build time into the page).
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => setNow(new Date()), [threads]);
  const groups = useMemo(() => (now ? groupThreads(threadsIn(threads, null), now) : []), [threads, now]);
  const railThreads = useMemo(() => {
    const mainThreads = threadsIn(threads, null);
    const pinned = mainThreads.filter((t) => t.pinned);
    const active = mainThreads.find((t) => t.id === activeThreadId && !t.pinned);
    const items = [...pinned];
    if (active && !items.some((t) => t.id === active.id)) {
      items.push(active);
    }
    for (const t of mainThreads) {
      if (items.length >= 5) break;
      if (!items.some((x) => x.id === t.id)) {
        items.push(t);
      }
    }
    return items;
  }, [threads, activeThreadId]);
  const rail = !expanded && !narrow;
  if (narrow && !expanded) return null;

  const rowProps = (inv: InvestigationItem, indent = false) => ({
    inv, indent, projects, active: activeThreadId === inv.id, running: streamingThreadId === inv.id,
  });
  const select = (fn: () => void) => () => {
    fn();
    if (narrow) props.onCloseDrawer();
  };
  const handlers: ChatRowHandlers = { ...props, onSelect: (inv) => select(() => props.onSelect(inv))() };

  const aside = (
    <aside ref={trapRef} className={`${styles.sidebar} ${rail ? styles.rail : ""} ${narrow ? styles.drawer : ""}`}
      style={props.panel && !rail && !narrow ? { width: props.panel.width, minWidth: props.panel.width } : undefined}
      aria-label="Conversations and projects" role={narrow ? "dialog" : undefined} aria-modal={narrow || undefined}>
      <div className={styles.head}>
        {rail ? (
          <button type="button" className={styles.iconBtn} onClick={props.onToggle} title="Expand sidebar" aria-label="Expand sidebar">
            <PanelLeft style={{ width: 18, height: 18 }} />
          </button>
        ) : (
          <>
            <img src="/tribos/logo-wordmark.png" alt="Tribos" className={`${styles.brand} tribos-tight-logo`} />
            <button type="button" className={styles.iconBtn} onClick={narrow ? props.onCloseDrawer : props.onToggle}
              title={narrow ? "Close sidebar" : "Collapse sidebar"} aria-label={narrow ? "Close sidebar" : "Collapse sidebar"}>
              <PanelLeftClose style={{ width: 18, height: 18 }} />
            </button>
          </>
        )}
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.action} onClick={select(props.onNewChat)} title="New chat (Ctrl+N)" aria-label="New chat">
          <SquarePen style={{ width: 15, height: 15 }} />
          {!rail && <>New chat <span className={styles.kbd}>⌘N</span></>}
        </button>
        <button type="button" className={styles.action} onClick={select(props.onSearch)} title="Search chats (Ctrl+K)" aria-label="Search chats">
          <Search style={{ width: 15, height: 15 }} />
          {!rail && <>Search chats <span className={styles.kbd}>⌘K</span></>}
        </button>
        {props.onOpenResearch && (
          <button type="button" className={styles.action} onClick={select(props.onOpenResearch)}
            title="Research projects: long runs from review to report" aria-label="Research projects">
            <FlaskConical style={{ width: 15, height: 15 }} />
            {!rail && <>Research projects</>}
          </button>
        )}
        {rail && props.projectsAvailable && (
          <button type="button" className={styles.action} onClick={props.onNewProject} title="New project" aria-label="New project">
            <FolderPlus style={{ width: 15, height: 15 }} />
          </button>
        )}
      </div>

      <nav className={styles.scroll} aria-label="Chats">
        {rail ? (
          <div className={styles.list} style={{ alignItems: "center" }}>
            {projects.map((p) => (
              <button key={p.id} type="button" className={styles.action} onClick={() => props.onOpenProject(p.id)}
                title={p.name} aria-label={`Project ${p.name}`}>
                <ProjectBadge project={p} />
              </button>
            ))}
            {railThreads.map((inv) => (
              <button key={inv.id} type="button"
                className={`${styles.action} ${activeThreadId === inv.id ? styles.actionActive : ""}`}
                onClick={() => props.onSelect(inv)}
                title={`${inv.title}${inv.pinned ? " (Pinned)" : ""}`}
                aria-label={inv.title}
                aria-current={activeThreadId === inv.id ? "page" : undefined}>
                <MessageSquareText style={{ width: 15, height: 15 }} />
              </button>
            ))}
            {threadsIn(threads, null).length > railThreads.length && (
              <button type="button" className={styles.action} onClick={props.onToggle}
                title={`+${threadsIn(threads, null).length - railThreads.length} more chats (Expand sidebar)`}
                aria-label="Expand sidebar to view all chats"
                style={{ fontSize: 11, color: "var(--text-faint)", fontWeight: 600 }}>
                +{threadsIn(threads, null).length - railThreads.length}
              </button>
            )}
          </div>
        ) : (
          <>
            {props.projectsAvailable && (
              <section aria-label="Projects">
                <div className={styles.sectionHead}>
                  <span>Projects</span>
                  <button type="button" className={styles.iconBtn} style={{ width: 22, height: 22 }}
                    onClick={props.onNewProject} title="New project" aria-label="New project">
                    <Plus style={{ width: 13, height: 13 }} />
                  </button>
                </div>
                <div className={styles.list}>
                  {projects.map((p) => {
                    const open = openProjects[p.id] ?? props.activeProjectId === p.id;
                    const chats = threadsIn(threads, p.id);
                    return (
                      <div key={p.id}>
                        <div className={`${styles.row} ${props.activeProjectId === p.id ? styles.rowActive : ""}`}>
                          <button type="button" className={styles.rowMain} onClick={select(() => props.onOpenProject(p.id))} title={p.name}>
                            <ProjectBadge project={p} />
                            <span className={styles.rowTitle}>{p.name}</span>
                            {p.role && p.role !== "owner" && <span className={styles.shared} title={`Shared with you as ${p.role}`}>shared</span>}
                          </button>
                          <button type="button" className={`${styles.iconBtn} ${styles.rowMenuBtn} ${styles.rowMenuBtnOpen}`}
                            style={{ width: 24, height: 24 }} aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} chats of ${p.name}`}
                            onClick={() => setOpenProjects((o) => ({ ...o, [p.id]: !open }))}>
                            {open ? <ChevronDown style={{ width: 13, height: 13 }} /> : <ChevronRight style={{ width: 13, height: 13 }} />}
                          </button>
                        </div>
                        {open && (
                          <div className={styles.list}>
                            {chats.map((inv) => <ChatRow key={inv.id} {...rowProps(inv, true)} handlers={handlers} />)}
                            {p.role !== "viewer" && (
                              <button type="button" className={`${styles.action} ${styles.indent}`} style={{ paddingLeft: 30, fontSize: 12.5 }}
                                onClick={select(() => props.onNewChatInProject(p.id))}>
                                <Plus style={{ width: 12, height: 12 }} /> New chat in {p.name}
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {!projects.length && <div className={styles.empty}>Group chats, files and reviewed memory in a project.</div>}
                </div>
              </section>
            )}
            {groups.map((g) => (
              <section key={g.key} aria-label={g.label}>
                <div className={styles.sectionHead}>{g.label}</div>
                <div className={styles.list}>
                  {g.items.map((inv) => <ChatRow key={inv.id} {...rowProps(inv)} handlers={handlers} />)}
                </div>
              </section>
            ))}
            {!groups.length && <div className={styles.empty}>No chats yet.</div>}
          </>
        )}
      </nav>

      <div className={styles.foot}>
        <button type="button" className={rail ? styles.avatar : styles.action} onClick={() => setProfileOpen((o) => !o)}
          aria-haspopup="menu" aria-expanded={profileOpen} aria-label="Profile and settings" title={rail ? "Profile and settings" : undefined}
          style={rail ? { border: "none", cursor: "pointer" } : undefined}>
          {rail ? "TR" : (<><span className={styles.avatar}>TR</span> Tribos R&amp;D <Settings style={{ width: 15, height: 15, marginLeft: "auto", opacity: 0.7 }} /></>)}
        </button>
        {profileOpen && (
          <div className={`${styles.menu} ${styles.menuUp}`} role="menu" style={rail ? { left: 6, right: "auto", minWidth: 190 } : undefined}>
            <button type="button" role="menuitem" className={styles.menuItem} onClick={() => { setProfileOpen(false); props.onOpenSettings(); }}>
              <Settings style={{ width: 13, height: 13 }} /> Settings
            </button>
            <button type="button" role="menuitem" className={styles.menuItem} onClick={() => { setProfileOpen(false); props.onOpenMemory(); }}>
              <Brain style={{ width: 13, height: 13 }} /> Memory vault
            </button>
            <button type="button" role="menuitem" className={styles.menuItem} onClick={() => { setProfileOpen(false); props.onToggleTheme(); }}>
              <Moon style={{ width: 13, height: 13 }} /> Toggle light / dark
            </button>
          </div>
        )}
      </div>
    </aside>
  );

  if (narrow) {
    return (
      <>
        <button type="button" className={styles.backdrop} aria-label="Close sidebar" onClick={props.onCloseDrawer} />
        {aside}
      </>
    );
  }
  // The handle sits outside the aside, whose overflow would clip it.
  return (
    <div className={styles.frame}>
      {aside}
      {props.panel && !rail && <ResizeHandle edge="right" panel={props.panel} label="Sidebar width" className={styles.frameHandle} />}
    </div>
  );
}

export default Sidebar;
