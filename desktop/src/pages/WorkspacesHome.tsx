import { useState } from "react";
import { type WorkspaceRecord } from "../apiClient";

interface WorkspacesHomeProps {
  workspaces: WorkspaceRecord[];
  loading?: boolean;
  showCreate?: boolean;
  onCreateWorkspace?: (name: string, rootPath: string) => Promise<WorkspaceRecord> | WorkspaceRecord;
  onCloseCreate?: () => void;
  onOpenCreate?: () => void;
  onSelectWorkspace?: (workspace: WorkspaceRecord) => void;
  selectedWorkspaceId?: string | null;
}

export default function WorkspacesHome({
  workspaces,
  loading = false,
  showCreate = false,
  onCreateWorkspace,
  onCloseCreate,
  onOpenCreate,
  onSelectWorkspace,
  selectedWorkspaceId,
}: WorkspacesHomeProps) {
  const [createName, setCreateName] = useState("");
  const [createPath, setCreatePath] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createName.trim() || !createPath.trim() || !onCreateWorkspace) return;
    setCreating(true);
    setCreateError(null);
    try {
      const ws = await onCreateWorkspace(createName.trim(), createPath.trim());
      setCreateName("");
      setCreatePath("");
      if (onSelectWorkspace) onSelectWorkspace(ws);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create workspace");
    } finally {
      setCreating(false);
    }
  }

  function handleSelectWorkspace(ws: WorkspaceRecord) {
    if (onSelectWorkspace) onSelectWorkspace(ws);
  }

  const repoCount = (ws: WorkspaceRecord): string => {
    const count = typeof ws.metadata?.repo_count === "number"
      ? ws.metadata.repo_count
      : 1;
    return `${count} repo${count !== 1 ? "s" : ""}`;
  };

  const taskCount = (ws: WorkspaceRecord & { task_count?: number }): number =>
    ws.task_count ?? 0;
  const activeCount = (ws: WorkspaceRecord & { active_count?: number }): number =>
    ws.active_count ?? 0;
  const isActive = (ws: WorkspaceRecord & { active_count?: number }): boolean =>
    (ws.active_count ?? 0) > 0;
  const lastActivity = (ws: WorkspaceRecord): string => {
    if (ws.updated_at) {
      const date = new Date(ws.updated_at);
      const now = new Date();
      const diff = now.getTime() - date.getTime();
      const hours = Math.floor(diff / (1000 * 60 * 60));
      if (hours < 1) return "just now";
      if (hours < 24) return `${hours}h ago`;
      const days = Math.floor(hours / 24);
      if (days === 1) return "yesterday";
      return `${days} days ago`;
    }
    return "never";
  };

  return (
    <div className="workspaces-home">
      <header className="home-header">
        <div className="home-header-top">
          <div className="home-header-left">
            <span className="home-logo">Sarathi</span>
            <h1 className="home-title">Workspaces</h1>
          </div>
          {!showCreate && (
            <button
              className="home-create-btn"
              onClick={() => onOpenCreate?.()}
            >
              <span className="home-create-btn-icon">+</span>
              New workspace
            </button>
          )}
        </div>
        <p className="home-subtitle">
          Workspaces group related projects and tasks for orchestrating AI agent work.
        </p>
      </header>

      {loading && (
        <div className="home-loading">
          <span className="spinner" />
          <span>Loading workspaces…</span>
        </div>
      )}

      {!loading && workspaces.length === 0 && (
        <section className="home-empty">
          <h2>No workspace yet</h2>
          <p>Create your first workspace to begin orchestrating agent work.</p>
          {!showCreate ? (
            <button
              className="btn-primary"
              onClick={() => onOpenCreate?.()}
            >
              Create workspace
            </button>
          ) : null}
        </section>
      )}

      {!loading && workspaces.length > 0 && (
        <div className="workspace-list">
          <div className="workspace-list-header">
            <span className="ws-list-col-name">Workspace</span>
            <span className="ws-list-col-tasks">Tasks</span>
            <span className="ws-list-col-status">Status</span>
            <span className="ws-list-col-repos">Repos</span>
            <span className="ws-list-col-activity">Last active</span>
            <span className="ws-list-col-open" />
          </div>

          {workspaces.map((ws) => {
            const active = isActive(ws as WorkspaceRecord & { active_count?: number });
            const tasks = taskCount(ws as WorkspaceRecord & { task_count?: number });
            const active_ = activeCount(ws as WorkspaceRecord & { active_count?: number });
            const isSelected = ws.id === selectedWorkspaceId;
            return (
              <WorkspaceRow
                key={ws.id}
                name={ws.name}
                taskCount={tasks}
                activeCount={active_}
                repoLabel={repoCount(ws)}
                isActive={active}
                lastActivity={lastActivity(ws)}
                isSelected={isSelected}
                onClick={() => handleSelectWorkspace(ws)}
              />
            );
          })}
        </div>
      )}

      {showCreate && (
        <div className="workspace-create-panel">
          <form onSubmit={(e) => { void handleCreate(e); }} className="home-form">
            <h3 className="form-title">New workspace</h3>
            <div className="form-row">
              <input
                className="form-input"
                type="text"
                placeholder="Workspace name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                autoFocus
                disabled={creating}
              />
              <input
                className="form-input"
                type="text"
                placeholder="Root path (e.g. /Users/you/project)"
                value={createPath}
                onChange={(e) => setCreatePath(e.target.value)}
                disabled={creating}
              />
            </div>
            {createError && <div className="form-error">{createError}</div>}
            <div className="form-actions">
              <button
                className="btn-primary"
                type="submit"
                disabled={creating || !createName.trim() || !createPath.trim()}
              >
                {creating ? "Creating…" : "Create"}
              </button>
              <button
                className="btn-secondary"
                type="button"
                onClick={() => {
                  onCloseCreate?.();
                  setCreateError(null);
                  setCreateName("");
                  setCreatePath("");
                }}
                disabled={creating}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

interface WorkspaceRowProps {
  name: string;
  taskCount: number;
  activeCount: number;
  repoLabel: string;
  isActive: boolean;
  onClick: () => void;
  lastActivity?: string;
  isSelected?: boolean;
}

function WorkspaceRow({
  name,
  taskCount,
  activeCount,
  repoLabel,
  isActive,
  onClick,
  lastActivity,
  isSelected,
}: WorkspaceRowProps) {
  return (
    <button
      className={`workspace-row${isSelected ? " selected" : ""}`}
      onClick={onClick}
    >
      <span className="ws-list-col-name">
        <span className={`status-dot ${isActive ? "active" : ""}`} />
        <span className="ws-name-text">{name}</span>
      </span>
      <span className="ws-list-col-tasks">
        <span className="ws-meta-pill">{taskCount} task{taskCount !== 1 ? "s" : ""}</span>
      </span>
      <span className="ws-list-col-status">
        {activeCount > 0 ? (
          <span className="ws-meta-pill active">{activeCount} active</span>
        ) : (
          <span className="ws-meta-pill idle">idle</span>
        )}
      </span>
      <span className="ws-list-col-repos">
        <span className="ws-meta-text">{repoLabel}</span>
      </span>
      <span className="ws-list-col-activity">
        <span className="ws-meta-text">{lastActivity}</span>
      </span>
      <span className="ws-list-col-open">
        <span className="ws-open-chevron">→</span>
      </span>
    </button>
  );
}
