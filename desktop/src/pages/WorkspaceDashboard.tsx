import { useEffect, useRef, useState } from "react";
import { type WorkspaceRecord, type WorkspaceProjectRecord, listWorkspaceRepositories } from "../apiClient";

interface WorkspaceDashboardProps {
  workspace: WorkspaceRecord;
  projects: WorkspaceProjectRecord[];
  createRequestedAt?: number;
  onCreateProject: (name: string, description: string) => Promise<void> | void;
  onOpenProject: (projectId: string) => void;
}

export default function WorkspaceDashboard({
  workspace,
  projects,
  createRequestedAt = 0,
  onCreateProject,
  onOpenProject,
}: WorkspaceDashboardProps) {
  const [showCreate, setShowCreate] = useState(projects.length === 0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameInputRef = useRef<HTMLInputElement | null>(null);
  const createFormRef = useRef<HTMLDivElement | null>(null);
  const repoCount = Number((workspace.metadata as Record<string, unknown>)["repo_count"] ?? 0);
  const workspaceStatus = (workspace.metadata as Record<string, unknown>)["status"] as string | undefined;
  const isLive = workspaceStatus === "live";
  const bootstrapReady = repoCount > 0;

  useEffect(() => {
    if (projects.length === 0) {
      setShowCreate(true);
    }
  }, [projects.length]);

  useEffect(() => {
    if (createRequestedAt > 0) {
      setShowCreate(true);
    }
  }, [createRequestedAt]);

  useEffect(() => {
    if (!showCreate) return;
    createFormRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    window.setTimeout(() => {
      nameInputRef.current?.focus();
      nameInputRef.current?.select();
    }, 40);
  }, [showCreate, createRequestedAt]);

  function openCreateForm() {
    setShowCreate(true);
    setError(null);
  }

  async function handleCreateProject() {
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();
    if (!trimmedName) return;
    setCreating(true);
    setError(null);
    try {
      await onCreateProject(trimmedName, trimmedDescription);
      setName("");
      setDescription("");
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="workspace-dashboard">
      <header className="dashboard-header">
        <div className="dashboard-badge">Workspace</div>
        <h1 className="dashboard-title">{workspace.name}</h1>
        <p className="dashboard-desc">
          A workspace groups related projects and their task orchestrations.
        </p>
        <div className="dashboard-status">
          <span className={`status-pill ${isLive ? "healthy" : ""}`}>
            {isLive ? "live" : "initializing"}
          </span>
          <span className={`status-pill ${bootstrapReady ? "healthy" : ""}`}>
            {bootstrapReady ? `${repoCount} repo${repoCount !== 1 ? "s" : ""} attached` : "no repos"}
          </span>
          <span className="status-pill">
            {projects.length} project{projects.length === 1 ? "" : "s"}
          </span>
          <button className="btn-primary" onClick={() => openCreateForm()}>
            + Create project
          </button>
        </div>
      </header>

      <section className="dashboard-projects">
        <h2 className="section-title">
          Projects
          <span className="section-badge">{projects.length > 0 ? "live" : "empty"}</span>
        </h2>
        
        {projects.length === 0 ? (
          <div className="empty-card">
            <h3>No projects yet</h3>
            <p>Create a project to start organizing tasks and orchestration.</p>
            <button className="btn-primary" onClick={() => openCreateForm()}>
              Create first project
            </button>
          </div>
        ) : (
          <div className="project-grid">
            {projects.map((project) => (
              <button
                key={project.id}
                className="project-card"
                onClick={() => onOpenProject(project.id)}
              >
                <div className="project-header">
                  <h3 className="project-name">{project.name}</h3>
                  <span className={`task-badge ${project.task_count > 0 ? "active" : ""}`}>
                    {project.task_count} task{project.task_count === 1 ? "" : "s"}
                  </span>
                </div>
                <p className="project-desc">
                  {project.description || "No description yet."}
                </p>
                <div className="project-meta">
                  Updated {new Date(project.updated_at).toLocaleDateString()}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="dashboard-create">
        <h2 className="section-title">Create project</h2>
        <p className="create-guide">
          Keep project names simple and outcome-oriented. Sarathi uses the project scope 
          to keep tasks and dashboards organized.
        </p>
        
        {showCreate ? (
          <div className="create-form" ref={createFormRef}>
            <input
              className="form-input"
              aria-label="Project name"
              placeholder="Project name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              ref={nameInputRef}
            />
            <input
              className="form-input"
              aria-label="Project description"
              placeholder="Project description (optional)"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            {error && <div className="form-error">{error}</div>}
            <div className="form-actions">
              <button 
                className="btn-primary" 
                onClick={() => void handleCreateProject()} 
                disabled={creating || !name.trim()}
              >
                {creating ? "Creating…" : "Create project"}
              </button>
              <button
                className="btn-secondary"
                onClick={() => {
                  setShowCreate(false);
                  setName("");
                  setDescription("");
                  setError(null);
                }}
                disabled={creating}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="create-ready">
            <strong>Ready when you are.</strong>
            <p>Use the button above to add a project to this workspace.</p>
          </div>
        )}
      </section>
    </div>
  );
}
