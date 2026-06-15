import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useWorkspace } from "../context/WorkspaceContext";
import { api } from "../api/client";
import { FormModal } from "./FormModal";
import type { Project, Workspace } from "../api/types";

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

function KnowledgeIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 5a2 2 0 0 1 2-2h6v18H6a2 2 0 0 1-2-2z" />
      <path d="M20 5a2 2 0 0 0-2-2h-6v18h6a2 2 0 0 0 2-2z" />
    </svg>
  );
}

function ProposalsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}

function SkillsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M12 2l2.4 5.4L20 8.2l-4 4 1 5.8-5-2.8-5 2.8 1-5.8-4-4 5.6-.8z" />
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

// Gradient swatches cycled for each project's pin dot, matching the
// mockup's varied color treatment for the (formerly hardcoded) pinned list.
const PROJECT_DOT_GRADIENTS = [
  "linear-gradient(135deg,#5b8def,#9b7ff0)",
  "linear-gradient(135deg,#e0742a,#f0a93b)",
  "linear-gradient(135deg,#3fb27f,#5b8def)",
  "linear-gradient(135deg,#c44ad0,#5b8def)",
  "linear-gradient(135deg,#f0a93b,#e0742a)",
];

function projectDotGradient(index: number): string {
  return PROJECT_DOT_GRADIENTS[index % PROJECT_DOT_GRADIENTS.length];
}

/** Best-effort human-readable name for a project payload of unknown shape. */
function projectName(project: Project, index: number): string {
  return project.name ?? project.id ?? `project-${index + 1}`;
}

export function Sidebar() {
  const { workspaces, currentWorkspace, currentWorkspaceId, setCurrentWorkspaceId, serviceStatus, refresh } =
    useWorkspace();
  const [menuOpen, setMenuOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [showNewWorkspace, setShowNewWorkspace] = useState(false);
  const navigate = useNavigate();

  // Load the active workspace's projects for the "Pinned projects" list.
  // Re-fetches whenever the current workspace changes, or when the workspace
  // list is refreshed (e.g. after creating a project) — `workspaces` gets a
  // new array reference on each context refresh.
  useEffect(() => {
    if (!currentWorkspaceId) {
      setProjects([]);
      setProjectsLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setProjectsLoading(true);
    api
      .getProjects(currentWorkspaceId, controller.signal)
      .then((data) => {
        if (cancelled) return;
        setProjects(data.projects ?? []);
      })
      .catch(() => {
        if (cancelled) return;
        setProjects([]);
      })
      .finally(() => {
        if (!cancelled) setProjectsLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentWorkspaceId, workspaces]);

  function openProject(project: Project) {
    if (project.id) {
      navigate(`/?project_id=${encodeURIComponent(project.id)}`);
    } else {
      navigate("/");
    }
  }

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
            <button
              className="om new"
              onClick={() => {
                setMenuOpen(false);
                setShowNewWorkspace(true);
              }}
            >
              + New workspace
            </button>
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
        <NavLink to="/knowledge" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <KnowledgeIcon />
          Knowledge Center
        </NavLink>
        <NavLink to="/wiki" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <WikiIcon />
          Wiki
        </NavLink>
        <NavLink to="/proposals" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <ProposalsIcon />
          Proposals
        </NavLink>
        <NavLink to="/skills" className={({ isActive }) => `ni${isActive ? " active" : ""}`}>
          <SkillsIcon />
          Skills
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
        {projects.map((project, index) => (
          <div
            className="pin"
            key={project.id ?? project.name ?? index}
            role="button"
            tabIndex={0}
            onClick={() => openProject(project)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openProject(project);
              }
            }}
          >
            <span className="dot" style={{ background: projectDotGradient(index) }} />
            {projectName(project, index)}
          </div>
        ))}
        {!projectsLoading && projects.length === 0 && (
          <div className="pin" style={{ color: "var(--faint)", cursor: "default" }}>
            No projects
          </div>
        )}
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

      {showNewWorkspace && (
        <FormModal
          title="New workspace"
          submitLabel="Create workspace"
          fields={[
            { name: "name", label: "Name", required: true, placeholder: "My workspace" },
            {
              name: "root_path",
              label: "Root path",
              required: true,
              placeholder: "/path/to/project",
              hint: "Absolute path to the workspace's root directory.",
            },
          ]}
          onSubmit={async (values) => {
            const { workspace } = await api.createWorkspace({
              name: values.name,
              root_path: values.root_path,
            });
            if (typeof workspace?.id === "string") setCurrentWorkspaceId(workspace.id);
            refresh();
          }}
          onClose={() => setShowNewWorkspace(false)}
        />
      )}
    </aside>
  );
}
