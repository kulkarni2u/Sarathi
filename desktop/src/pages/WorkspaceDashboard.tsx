import { useEffect, useMemo, useRef, useState } from "react";
import {
  getWorkspaceOperationalViews,
  getWorkspaceReuseKit,
  updateWorkspace,
  type BrainstormSession,
  type OperationalViewsSnapshot,
  type WorkspaceReuseKitSnapshot,
  type WorkspaceProjectRecord,
  type WorkspaceRecord,
} from "../apiClient";

interface WorkspaceDashboardProps {
  workspace: WorkspaceRecord;
  projects: WorkspaceProjectRecord[];
  focusedSavedViewId?: string | null;
  createRequestedAt?: number;
  onCreateProject: (name: string, description: string) => Promise<void> | void;
  onOpenProject: (projectId: string) => void;
  onStartBrainstorm?: (starter: string | { title: string; prompt?: string; metadata?: BrainstormSession["metadata"] }) => void;
  onOpenInbox?: () => void;
  onOpenSavedView?: (route: "dashboard" | "inbox" | "settings") => void;
}

function customSavedViewDefinitions(savedViews: WorkspaceReuseKitSnapshot["saved_views"]) {
  return savedViews
    .filter((view) => view.origin === "custom")
    .map((view) => ({
      id: view.id,
      name: view.name,
      role: view.role,
      route: view.route,
      description: view.description,
      metric_label: view.metric_label,
      filters: view.filters,
    }));
}

function projectMatchesSavedViewFilters(
  project: Pick<
    OperationalViewsSnapshot["projects"][number],
    "blocked_count" | "handoff_ready_count" | "checkpoint_ready_count" | "approval_pending_count"
  >,
  filters: Record<string, unknown>,
) {
  if (filters.project_state === "blocked") return project.blocked_count > 0;
  if (filters.task_state === "handoff_ready") return project.handoff_ready_count > 0;
  if (filters.task_state === "checkpoint_ready") return project.checkpoint_ready_count > 0;
  if (filters.task_state === "approval_pending" || filters.kind === "approval") return project.approval_pending_count > 0;
  return true;
}

export default function WorkspaceDashboard({
  workspace,
  projects,
  focusedSavedViewId = null,
  createRequestedAt = 0,
  onCreateProject,
  onOpenProject,
  onStartBrainstorm,
  onOpenInbox,
  onOpenSavedView,
}: WorkspaceDashboardProps) {
  const [showCreate, setShowCreate] = useState(projects.length === 0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [operations, setOperations] = useState<OperationalViewsSnapshot | null>(null);
  const [reuseKit, setReuseKit] = useState<WorkspaceReuseKitSnapshot | null>(null);
  const [activeSavedViewId, setActiveSavedViewId] = useState("all-projects");
  const [savingViewId, setSavingViewId] = useState<string | null>(null);
  const [showSaveViewForm, setShowSaveViewForm] = useState(false);
  const [saveViewName, setSaveViewName] = useState("");
  const [saveViewRole, setSaveViewRole] = useState("team");
  const [saveViewDescription, setSaveViewDescription] = useState("");
  const [savingCustomView, setSavingCustomView] = useState(false);
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

  async function refreshReuseSurface() {
    const [nextOperations, nextReuseKit] = await Promise.all([
      getWorkspaceOperationalViews(workspace.id),
      getWorkspaceReuseKit(workspace.id),
    ]);
    setOperations(nextOperations);
    setReuseKit(nextReuseKit);
    setActiveSavedViewId(focusedSavedViewId || nextReuseKit.active_saved_view_id || "all-projects");
  }

  useEffect(() => {
    let cancelled = false;
    async function loadOperations() {
      try {
        const [nextOperations, nextReuseKit] = await Promise.all([
          getWorkspaceOperationalViews(workspace.id),
          getWorkspaceReuseKit(workspace.id),
        ]);
        if (!cancelled) {
          setOperations(nextOperations);
          setReuseKit(nextReuseKit);
          setActiveSavedViewId(focusedSavedViewId || nextReuseKit.active_saved_view_id || "all-projects");
        }
      } catch {
        if (!cancelled) {
          setOperations(null);
          setReuseKit(null);
          setActiveSavedViewId("all-projects");
        }
      }
    }
    void loadOperations();
    return () => {
      cancelled = true;
    };
  }, [workspace.id, projects.length, focusedSavedViewId]);

  useEffect(() => {
    if (!focusedSavedViewId) return;
    setActiveSavedViewId(focusedSavedViewId);
  }, [focusedSavedViewId]);

  function openCreateForm() {
    setShowCreate(true);
    setError(null);
  }

  function applyTemplateToProjectForm(template: WorkspaceReuseKitSnapshot["templates"][number]) {
    setShowCreate(true);
    setName(template.name);
    setDescription(template.summary);
    setError(null);
  }

  function starterPromptForTemplate(template: WorkspaceReuseKitSnapshot["templates"][number]): string {
    return [
      `Use the ${template.name} workflow template for workspace ${workspace.name}.`,
      template.summary,
      `Recommended repository action posture: ${template.recommended_repository_action_mode}.`,
      `Recommended approval posture: ${template.recommended_auto_approve_mode}.`,
      template.suggested_provider_priority.length > 0
        ? `Preferred provider order: ${template.suggested_provider_priority.join(", ")}.`
        : "",
    ]
      .filter(Boolean)
      .join(" ");
  }

  function starterPromptForPlaybook(playbook: WorkspaceReuseKitSnapshot["playbooks"][number]): string {
    return [
      `Use the learned playbook "${playbook.name}" for workspace ${workspace.name}.`,
      playbook.summary,
      playbook.recommended_template_id
        ? `Start from template ${playbook.recommended_template_id}.`
        : "",
      playbook.provenance.task_id
        ? `Anchor the approach to task ${playbook.provenance.task_id} and reuse only what remains broadly applicable.`
        : "",
      playbook.provenance.evidence_refs && playbook.provenance.evidence_refs.length > 0
        ? `Consider evidence refs: ${playbook.provenance.evidence_refs.join(", ")}.`
        : "",
    ]
      .filter(Boolean)
      .join(" ");
  }

  async function selectSavedView(viewId: string) {
    setActiveSavedViewId(viewId);
    setSavingViewId(viewId);
    try {
      await updateWorkspace(workspace.id, {
        ...(workspace.metadata ?? {}),
        reuse_preferences: {
          active_saved_view_id: viewId,
          custom_saved_views: customSavedViewDefinitions(reuseKit?.saved_views ?? []),
        },
      });
      await refreshReuseSurface();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to persist saved view");
    } finally {
      setSavingViewId(null);
    }
  }

  async function startTemplateBrainstorm(template: WorkspaceReuseKitSnapshot["templates"][number]) {
    const recommendedViewId = template.recommended_view_ids[0] ?? null;
    if (recommendedViewId) {
      await selectSavedView(recommendedViewId);
    }
    onStartBrainstorm?.({
      title: template.starter_title,
      prompt: starterPromptForTemplate(template),
      metadata: {
        reuse_source: { kind: "workflow_template", id: template.id, name: template.name },
        workflow_template_id: template.id,
        recommended_view_ids: template.recommended_view_ids,
        recommended_repository_action_mode: template.recommended_repository_action_mode,
        recommended_auto_approve_mode: template.recommended_auto_approve_mode,
        suggested_provider_priority: template.suggested_provider_priority,
      },
    });
  }

  async function startPlaybookBrainstorm(playbook: WorkspaceReuseKitSnapshot["playbooks"][number]) {
    const recommendedViewId = playbook.recommended_view_ids[0] ?? null;
    if (recommendedViewId) {
      await selectSavedView(recommendedViewId);
    }
    onStartBrainstorm?.({
      title: `Playbook: ${playbook.name}`,
      prompt: starterPromptForPlaybook(playbook),
      metadata: {
        reuse_source: { kind: "learning_playbook", id: playbook.id, name: playbook.name },
        learning_playbook_id: playbook.id,
        workflow_template_id: playbook.recommended_template_id ?? undefined,
        recommended_view_ids: playbook.recommended_view_ids,
      },
    });
  }

  function openSaveViewForm() {
    const sourceView = (reuseKit?.saved_views ?? []).find((view) => view.id === activeSavedViewId);
    setSaveViewName(sourceView ? `${sourceView.name} team view` : "Team workspace view");
    setSaveViewDescription(sourceView?.description ?? "Reusable saved view for this workspace.");
    setSaveViewRole(sourceView?.role ?? "team");
    setShowSaveViewForm(true);
    setError(null);
  }

  async function saveCurrentViewAsCustom() {
    const sourceView = (reuseKit?.saved_views ?? []).find((view) => view.id === activeSavedViewId);
    if (!sourceView || !saveViewName.trim()) return;
    setSavingCustomView(true);
    setError(null);
    const customViews = [
      ...customSavedViewDefinitions(reuseKit?.saved_views ?? []).filter((view) => view.id !== sourceView.id),
      {
        id: `custom-view-${Date.now()}`,
        name: saveViewName.trim(),
        role: saveViewRole.trim() || "team",
        route: sourceView.route,
        description: saveViewDescription.trim() || sourceView.description,
        metric_label: sourceView.metric_label,
        filters: sourceView.filters,
      },
    ];
    try {
      await updateWorkspace(workspace.id, {
        ...(workspace.metadata ?? {}),
        reuse_preferences: {
          active_saved_view_id: customViews[customViews.length - 1].id,
          custom_saved_views: customViews,
        },
      });
      setShowSaveViewForm(false);
      await refreshReuseSurface();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save custom view");
    } finally {
      setSavingCustomView(false);
    }
  }

  async function deleteCustomView(viewId: string) {
    const nextCustomViews = customSavedViewDefinitions(reuseKit?.saved_views ?? []).filter((view) => view.id !== viewId);
    const nextActiveViewId = activeSavedViewId === viewId ? "all-projects" : activeSavedViewId;
    setSavingViewId(viewId);
    setError(null);
    try {
      await updateWorkspace(workspace.id, {
        ...(workspace.metadata ?? {}),
        reuse_preferences: {
          active_saved_view_id: nextActiveViewId,
          custom_saved_views: nextCustomViews,
        },
      });
      await refreshReuseSurface();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete custom view");
    } finally {
      setSavingViewId(null);
    }
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

  const projectSummaries = useMemo(() => {
    const summaries = new Map((operations?.projects ?? []).map((project) => [project.id, project]));
    return projects.map((project) => summaries.get(project.id) ?? {
      ...project,
      review_needed_count: 0,
      approval_pending_count: 0,
      checkpoint_ready_count: 0,
      handoff_ready_count: 0,
    });
  }, [operations?.projects, projects]);

  const attentionSummary = useMemo(() => {
    if (operations) {
      return {
        approvals: operations.summary.approvals_pending,
        checkpoints: operations.summary.checkpoint_ready_count,
        handoffs: operations.summary.handoff_ready_count,
        blockedProjects: operations.projects.filter((project) => project.blocked_count > 0).length,
        inboxItems: operations.inbox.length,
        nextItem: operations.inbox[0] ?? null,
      };
    }
    return {
      approvals: 0,
      checkpoints: 0,
      handoffs: 0,
      blockedProjects: projects.filter((project) => project.blocked_count > 0).length,
      inboxItems: 0,
      nextItem: null,
    };
  }, [operations, projects]);

  const templateCards = reuseKit?.templates ?? [];
  const savedViews = reuseKit?.saved_views ?? [];
  const playbooks = reuseKit?.playbooks ?? [];
  const activeSavedView = savedViews.find((view) => view.id === activeSavedViewId) ?? null;
  const filteredProjectSummaries = useMemo(() => {
    const filters = activeSavedView?.filters ?? {};
    return projectSummaries.filter((project) => projectMatchesSavedViewFilters(project, filters));
  }, [activeSavedView, projectSummaries]);

  return (
    <div className="workspace-dashboard">
      <header className="dashboard-header">
        <div className="dashboard-badge">Workspace</div>
        <h1 className="dashboard-title">{workspace.name}</h1>
        <div className="dashboard-status">
          <span className={`pill-mini ${isLive ? "healthy" : ""}`}>
            {isLive ? "live" : "initializing"}
          </span>
          <span className={`pill-mini ${bootstrapReady ? "healthy" : ""}`}>
            {bootstrapReady ? `${repoCount} repo${repoCount !== 1 ? "s" : ""}` : "no repos"}
          </span>
          <span className="pill-mini">
            {projects.length} project{projects.length === 1 ? "" : "s"}
          </span>
          {attentionSummary.inboxItems > 0 && onOpenInbox ? (
            <button className="btn-secondary" onClick={onOpenInbox}>
              Inbox
            </button>
          ) : null}
          <button className="btn-primary" onClick={() => openCreateForm()}>
            + New
          </button>
        </div>
      </header>

      <section className="metrics-compact">
        {[
          { label: "Approvals", value: attentionSummary.approvals, tone: attentionSummary.approvals > 0 ? "warning" : "muted" },
          { label: "Checkpoints", value: attentionSummary.checkpoints, tone: attentionSummary.checkpoints > 0 ? "healthy" : "muted" },
          { label: "Handoffs", value: attentionSummary.handoffs, tone: attentionSummary.handoffs > 0 ? "active" : "muted" },
          { label: "Blocked", value: attentionSummary.blockedProjects, tone: attentionSummary.blockedProjects > 0 ? "blocked" : "muted" },
        ].map((item) => (
          <div key={item.label} className={`metric-compact`}>
            <div className="metric-compact-label">{item.label}</div>
            <div className={`metric-compact-value ${item.tone}`}>{item.value}</div>
          </div>
        ))}
      </section>

      {templateCards.length > 0 && (
        <section className="dashboard-projects" style={{ marginBottom: 16 }}>
          <div className="section-header">
            <h2 className="section-title">Workflow templates</h2>
          </div>
          <p className="dashboard-section-summary">
            Start from a known delivery posture instead of re-deciding repository policy, approvals, and provider routing every time.
          </p>
          <div className="dashboard-card-grid">
            {templateCards.map((template) => (
              <div
                key={template.id}
                className="card-compact"
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 6 }}>
                  <span className="card-compact-title">{template.name}</span>
                  <span className="pill-mini">{template.complexity}</span>
                </div>
                <p className="card-compact-desc" style={{ margin: 0 }}>{template.summary}</p>
                <div className="dashboard-card-meta">
                  <span>{template.category}</span>
                  <span>Repo posture: {template.recommended_repository_action_mode.replace(/_/g, " ")}</span>
                </div>
                <div className="dashboard-card-actions" style={{ marginTop: 8 }}>
                  <button className="btn-secondary" style={{ height: 26, fontSize: "0.72rem" }} onClick={() => applyTemplateToProjectForm(template)}>
                    Use
                  </button>
                  {onStartBrainstorm ? (
                    <button className="btn-secondary" style={{ height: 26, fontSize: "0.72rem" }} onClick={() => void startTemplateBrainstorm(template)}>
                      Launch template
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {savedViews.length > 0 && (
        <section className="dashboard-projects" style={{ marginBottom: 16 }}>
          <div className="section-header">
            <h2 className="section-title">Saved views</h2>
            {activeSavedView && (
              <button className="btn-secondary" style={{ height: 24, fontSize: "0.7rem" }} onClick={() => openSaveViewForm()}>
                Save current view
              </button>
            )}
          </div>
          <p className="dashboard-section-summary">
            Keep the workspace in a role-shaped posture so operators, reviewers, and PMs land on the right queue without extra setup.
          </p>
        {showSaveViewForm ? (
          <div className="create-form" style={{ marginBottom: 12 }}>
            <input
              className="form-input"
              aria-label="Saved view name"
              placeholder="Saved view name"
              value={saveViewName}
              onChange={(event) => setSaveViewName(event.target.value)}
            />
            <input
              className="form-input"
              aria-label="Saved view role"
              placeholder="Saved view role"
              value={saveViewRole}
              onChange={(event) => setSaveViewRole(event.target.value)}
            />
            <input
              className="form-input"
              aria-label="Saved view description"
              placeholder="Saved view description"
              value={saveViewDescription}
              onChange={(event) => setSaveViewDescription(event.target.value)}
            />
            <div className="form-actions">
              <button className="btn-primary" disabled={savingCustomView || !saveViewName.trim()} onClick={() => void saveCurrentViewAsCustom()}>
                {savingCustomView ? "Saving…" : "Save view"}
              </button>
              <button
                className="btn-secondary"
                onClick={() => setShowSaveViewForm(false)}
                disabled={savingCustomView}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
        <div className="dashboard-card-grid">
            {savedViews.map((view) => (
              <button
                key={view.id}
                className="project-card"
                onClick={() => {
                  void selectSavedView(view.id);
                  if (view.route === "inbox") {
                    onOpenInbox?.();
                    return;
                  }
                  if (view.route === "settings") {
                    onOpenSavedView?.("settings");
                  }
                }}
                style={{
                  textAlign: "left",
                  padding: "12px",
                  borderColor: activeSavedViewId === view.id ? "var(--accent)" : undefined,
                }}
              >
                <div className="project-header" style={{ marginBottom: 4 }}>
                  <h3 className="project-name" style={{ fontSize: "0.85rem" }}>{view.name}</h3>
                  <span className={`pill-mini ${view.count > 0 ? "active" : ""}`}>
                    {savingViewId === view.id ? "…" : view.count}
                  </span>
                </div>
                <p className="project-desc" style={{ fontSize: "0.74rem", margin: 0 }}>{view.description}</p>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginTop: 8 }}>
                  <span className="pill-mini">{view.origin === "custom" ? view.role.replace(/_/g, " ") : view.role.replace(/_/g, " ")}</span>
                  {view.origin === "custom" && (
                    <button
                      className="btn-secondary"
                      type="button"
                      style={{ height: 20, fontSize: "0.65rem", padding: "0 6px" }}
                      onClick={(event) => {
                        event.stopPropagation();
                        void deleteCustomView(view.id);
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="dashboard-projects" style={{ marginBottom: 16 }}>
        <div className="section-header">
          <h2 className="section-title">Learned playbooks</h2>
        </div>
        <p className="dashboard-section-summary">
          Promote accepted learnings into reusable operating patterns with visible origin, not just one-off notes.
        </p>
        {playbooks.length > 0 ? (
          <div className="dashboard-card-grid">
            {playbooks.map((playbook) => (
              <div key={playbook.id} className="card-compact">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 6 }}>
                  <span className="card-compact-title">{playbook.name}</span>
                  <span className="pill-mini healthy">{playbook.source.replace(/_/g, " ")}</span>
                </div>
                <p className="card-compact-desc" style={{ margin: 0 }}>{playbook.summary}</p>
                <div className="dashboard-card-meta">
                  <span>Template: {playbook.recommended_template_id ?? "feature-delivery"}</span>
                  <span>Source: {playbook.provenance.source_file ?? "workspace learnings"}</span>
                </div>
                {onStartBrainstorm && (
                  <button
                    className="btn-secondary"
                    style={{ height: 26, fontSize: "0.72rem", marginTop: 8 }}
                    onClick={() => void startPlaybookBrainstorm(playbook)}
                  >
                    Use
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-card">
            <h3>No learned playbooks yet</h3>
            <p>Accepted learnings will appear here once the workspace has proven reusable delivery patterns.</p>
          </div>
        )}
      </section>

      {attentionSummary.nextItem && (
        <section className="dashboard-projects" style={{ marginBottom: 16 }}>
          <div className="section-header">
            <h2 className="section-title">Next action</h2>
            <span className="pill-mini">{attentionSummary.nextItem.kind.replace(/_/g, " ")}</span>
          </div>
          <p className="dashboard-section-summary">
            One visible interruption matters more than ten competing alerts. Sarathi keeps the next governed action up front here.
          </p>
          <div className="card-compact">
            <div className="summary-row-primary">{attentionSummary.nextItem.title}</div>
            <div className="summary-row-secondary">{attentionSummary.nextItem.summary}</div>
            {onOpenInbox && (
              <button className="btn-secondary" style={{ height: 24, fontSize: "0.72rem", marginTop: 8 }} onClick={onOpenInbox}>
                Review queue
              </button>
            )}
          </div>
        </section>
      )}

      <section className="dashboard-projects">
        <div className="section-header">
          <h2 className="section-title">Projects</h2>
          {activeSavedView && (
            <span className="section-badge">{activeSavedView.name}</span>
          )}
        </div>
        <p className="dashboard-section-summary">
          Project cards stay compact and operational: enough signal to route attention quickly, with the saved view already filtering the noise down.
        </p>
        
        {projects.length === 0 ? (
          <div className="empty-card">
            <h3>No projects yet</h3>
            <p>Create a project to start organizing tasks and orchestration.</p>
            <button className="btn-primary" onClick={() => openCreateForm()}>
              Create first project
            </button>
          </div>
        ) : filteredProjectSummaries.length === 0 ? (
          <div className="empty-card">
            <h3>No projects match this view</h3>
            <p>The current saved view has no matching projects yet. Try another view or return to all projects.</p>
          </div>
        ) : (
          <div className="project-grid">
            {filteredProjectSummaries.map((project) => (
              <button
                key={project.id}
                className="project-card"
                onClick={() => onOpenProject(project.id)}
                style={{ padding: "12px" }}
              >
                <div className="project-header">
                  <h3 className="project-name" style={{ fontSize: "0.88rem" }}>{project.name}</h3>
                  <span className={`pill-mini ${project.blocked_count > 0 ? "warning" : project.task_count > 0 ? "active" : ""}`}>
                    {project.task_count}
                  </span>
                </div>
                <p className="project-desc" style={{ fontSize: "0.74rem", marginTop: 4 }}>
                  {project.description || "No description yet."}
                </p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                  {project.blocked_count > 0 && <span className="pill-mini warning">{project.blocked_count} blocked</span>}
                  {project.handoff_ready_count > 0 && <span className="pill-mini healthy">{project.handoff_ready_count} handoff</span>}
                </div>
                <div className="project-meta" style={{ fontSize: "0.68rem" }}>
                  {new Date(project.updated_at).toLocaleDateString()}
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
            {templateCards.length > 0 ? (
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Start from template
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {templateCards.slice(0, 3).map((template) => (
                    <button
                      key={template.id}
                      className="btn-secondary"
                      type="button"
                      onClick={() => applyTemplateToProjectForm(template)}
                    >
                      {template.name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
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
