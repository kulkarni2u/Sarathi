import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useWorkspace } from "../context/WorkspaceContext";
import type { Workspace } from "../api/types";

// Icons are inlined (stroke="currentColor") to match the mockup's lightweight
// SVG style without pulling in an icon library dependency.

function DashboardIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="3" width="7" height="9" rx="2" />
      <rect x="14" y="3" width="7" height="5" rx="2" />
      <rect x="14" y="12" width="7" height="9" rx="2" />
      <rect x="3" y="16" width="7" height="5" rx="2" />
    </svg>
  );
}

function NeedsYouIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8" />
      <path d="M10 21a2 2 0 0 0 4 0" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 5v4h4" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

function AgentsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <rect x="4" y="4" width="16" height="16" rx="4" />
      <circle cx="9.5" cy="10" r="1.3" />
      <circle cx="14.5" cy="10" r="1.3" />
      <path d="M9 15c1 1 5 1 6 0" />
    </svg>
  );
}

function WikiIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function UsageIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <path d="M8 16l3-4 3 2 5-7" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 13a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 0 1-4 0v-.2A1.7 1.7 0 0 0 6 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H2a2 2 0 0 1 0-4h.2A1.7 1.7 0 0 0 4 6l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 3V2.8a2 2 0 0 1 4 0V3a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 10h.2a2 2 0 0 1 0 4H21a1.7 1.7 0 0 0-1.6 1z" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4-4" />
    </svg>
  );
}

/** Maps a workspace's `health` field to the dot color used in the switcher menu. */
function healthDotColor(health: string | undefined): string {
  switch (health) {
    case "healthy":
    case "ok":
      return "var(--green)";
    case "degraded":
    case "warn":
      return "var(--amber)";
    case "offline":
    case "error":
      return "var(--red)";
    default:
      return "var(--faint)"; // "setup" / unknown
  }
}

// Placeholder "pinned projects" until a later worker wires this to real
// project data (e.g. from /workspaces/{id}/projects).
const PINNED_PROJECTS: { name: string; gradient: string }[] = [
  { name: "checkout-revamp", gradient: "linear-gradient(135deg,#5b8def,#9b7ff0)" },
  { name: "fraud-engine", gradient: "linear-gradient(135deg,#e0742a,#f0a93b)" },
  { name: "platform-infra", gradient: "linear-gradient(135deg,#3fb27f,#5b8def)" },
];

export function Sidebar() {
  const { workspaces, currentWorkspace, currentWorkspaceId, setCurrentWorkspaceId, serviceStatus } = useWorkspace();
  const [menuOpen, setMenuOpen] = useState(false);

  const presenceLabel =
    serviceStatus === "online"
      ? "Connected · Live"
      : serviceStatus === "degraded"
        ? "Degraded · Limited"
        : serviceStatus === "offline"
          ? "Service offline"
          : "Connecting…";

  const presenceClass =
    serviceStatus === "online" ? "" : serviceStatus === "offline" ? "offline" : "degraded";

  return (
    <aside className="sidebar">
      {/* ---- workspace switcher ---- */}
      <div className="org-wrap">
        <div className="org">
          <div className="ava" />
          <div className="nm">{currentWorkspace?.name ?? currentWorkspace?.id ?? "No workspace"}</div>
          <button className="ic" title="Switch workspace" onClick={() => setMenuOpen((open) => !open)}>
            ▾
          </button>
          <button className="ic" title="Collapse">
            ⬚
          </button>
        </div>
        {menuOpen && (
          <div className="org-menu open">
            {workspaces.map((ws: Workspace) => (
              <button
                key={ws.id}
                className="om"
                onClick={() => {
                  setCurrentWorkspaceId(ws.id);
                  setMenuOpen(false);
                }}
              >
                <span className="d" style={{ background: healthDotColor(ws.health as string | undefined) }} />
                {ws.name ?? ws.id}
                <small>{(ws.health as string | undefined) ?? "unknown"}</small>
              </button>
            ))}
            {workspaces.length === 0 && (
              <div className="om" style={{ color: "var(--faint)" }}>
                No workspaces yet
              </div>
            )}
            <button className="om new">+ New workspace</button>
            <NavLink to="/workspace" className="om" style={{ color: "var(--muted)" }} onClick={() => setMenuOpen(false)}>
              ⚙ Manage workspace…
            </NavLink>
          </div>
        )}
      </div>

      {/* ---- search (non-functional placeholder for M1) ---- */}
      <div className="search">
        <SearchIcon />
        <input placeholder="Search anything…" />
        <kbd>/</kbd>
      </div>

      {/* ---- grouped navigation ---- */}
      <nav>
        <div className="nl">Workspace</div>
        <NavLink to="/" className={({ isActive }) => `ni${isActive ? " active" : ""}`} end>
          <DashboardIcon />
          Dashboard
        </NavLink>
        <NavLink to="/needs-you" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <NeedsYouIcon />
          Needs you
        </NavLink>
        <NavLink to="/history" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <HistoryIcon />
          History
        </NavLink>
        <NavLink to="/agents" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <AgentsIcon />
          Agents
        </NavLink>

        <div className="nl">Knowledge</div>
        <NavLink to="/wiki" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <WikiIcon />
          Wiki
        </NavLink>
        <NavLink to="/usage" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <UsageIcon />
          Usage Stats
        </NavLink>

        <div className="nl">System</div>
        <NavLink to="/settings" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <SettingsIcon />
          Settings
        </NavLink>

        <div className="nl">Pinned projects</div>
        {PINNED_PROJECTS.map((project) => (
          <div className="pin" key={project.name}>
            <span className="dot" style={{ background: project.gradient }} />
            {project.name}
          </div>
        ))}
      </nav>

      {/* ---- connection presence ---- */}
      <div className={`presence ${presenceClass}`.trim()}>
        <span className="dot" />
        {presenceLabel}
      </div>

      {/* ---- footer ---- */}
      <div className="sfoot">
        <div className="ava" />
        <div className="who">
          <b>operator</b>
          <span>{currentWorkspaceId ? currentWorkspace?.name ?? currentWorkspaceId : "no workspace"}</span>
        </div>
        <span className="pill">LOCAL</span>
        <button className="more">⋯</button>
      </div>
    </aside>
  );
}
