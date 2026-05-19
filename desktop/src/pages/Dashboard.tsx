import { useState, useEffect, useCallback, useMemo } from "react";
import {
  activeSavedViewFromReuseKit,
  getSarathiApiConfig,
  getWorkspaceReuseKit,
  listTaskDashboard,
  createTaskDraft,
  filterTaskDashboardItemsBySavedView,
  type TaskDashboardItem,
  type SavedViewSnapshot,
} from "../apiClient";
import { tasks } from "../mockData";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function getStatusPillClass(status: string): string {
  if (status === "in_progress") return "status-pill active";
  if (status === "done") return "status-pill done";
  return "status-pill pending";
}

function getStatusLabel(status: string): string {
  if (status === "in_progress") return "Active";
  if (status === "done") return "Done";
  return "Pending";
}

function queueLabel(task: TaskDashboardItem): string {
  if (task.handoff_state === "ready") return "Handoff ready";
  if (task.review_needed_count > 0) return "Needs review";
  if (task.approval_state !== "approved" && task.approval_state !== "none") return "Awaiting approval";
  if (task.blocked_count > 0) return "Blocked";
  if (task.checkpoint_state !== "none") return "Checkpoint ready";
  if (task.status === "in_progress") return "Running";
  if (task.status === "done") return "Done";
  return "Ready";
}

function queueTone(task: TaskDashboardItem): string {
  if (task.blocked_count > 0 || task.review_needed_count > 0) return "warning";
  if (task.approval_state !== "approved" && task.approval_state !== "none") return "warning";
  if (task.handoff_state === "ready" || task.checkpoint_state !== "none") return "active";
  if (task.status === "done") return "done";
  if (task.status === "in_progress") return "active";
  return "pending";
}

function nextCue(task: TaskDashboardItem): string {
  if (task.handoff_state === "ready") return "Review handoff";
  if (task.review_needed_count > 0) return "Re-open review";
  if (task.approval_state !== "approved" && task.next_gate) return `Approve ${task.next_gate}`;
  if (task.blocked_count > 0) return "Resolve blocker";
  if (task.checkpoint_state !== "none") return "Resume from checkpoint";
  if (task.status === "in_progress") return "Monitor execution";
  return "Open task";
}

function mockTasksToDashboardItems(): TaskDashboardItem[] {
  return tasks.map((t) => ({
    id: t.id,
    workspace_id: "SARATHI-APP",
    title: t.title,
    status: t.status === "in_progress" ? "in_progress"
      : t.status === "complete" ? "done"
      : "prd_pending",
    phase: t.phase,
    approval_state: t.reviewState,
    graph_state: "ready",
    next_gate: t.status === "waiting_human" ? "approval required" : null,
    node_count: t.progress > 0 ? Math.ceil(t.progress / 25) : 1,
    blocked_count: 0,
    review_needed_count: 0,
    checkpoint_state: "none",
    handoff_state: "none",
    roles: ["Pravaha"],
    providers: ["Codex"],
    updated_at: new Date(Date.now() - 5 * 60000).toISOString(),
  }));
}

type FilterTab = "all" | "active" | "blocked" | "done";

interface DashboardProps {
  workspaceId?: string | null;
  projectId?: string | null;
  projectName?: string | null;
  tasks?: TaskDashboardItem[] | null;
  createRequestedAt?: number;
  setSelectedTaskId?: (id: string) => void;
  setRoute?: (r: string) => void;
  liveTick?: number;
  onTasksLoaded?: (items: TaskDashboardItem[]) => void;
  onTaskCreated?: (item: TaskDashboardItem) => void;
}

export default function Dashboard({
  workspaceId,
  projectId,
  projectName,
  tasks: controlledTasks,
  createRequestedAt = 0,
  setSelectedTaskId,
  setRoute,
  liveTick = 0,
  onTasksLoaded,
  onTaskCreated,
}: DashboardProps) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const controlled = Array.isArray(controlledTasks);
  const [items, setItems] = useState<TaskDashboardItem[]>(controlled ? controlledTasks : []);
  const [loading, setLoading] = useState(!controlled);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [newPrompt, setNewPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [activeSavedView, setActiveSavedView] = useState<SavedViewSnapshot | null>(null);

  const guidanceCopy = apiConfigured
    ? "Describe what you want to build. Sarathi will ask what it needs, then create the task."
    : "Describe what you want to build. When the service is offline, Sarathi will fall back to a local draft.";

  const loadTasks = useCallback(async () => {
    if (controlled) {
      setItems(controlledTasks ?? []);
      setLoading(false);
      onTasksLoaded?.(controlledTasks ?? []);
      return;
    }
    if (!apiConfigured || !workspaceId) {
      const fallback = mockTasksToDashboardItems();
      setItems(fallback);
      setLoading(false);
      onTasksLoaded?.(fallback);
      return;
    }
    setLoading(true);
    try {
      const [list, reuseKit] = await Promise.all([
        listTaskDashboard(workspaceId, { projectId }),
        getWorkspaceReuseKit(workspaceId),
      ]);
      const savedView = activeSavedViewFromReuseKit(reuseKit);
      const filtered = filterTaskDashboardItemsBySavedView(list, savedView);
      setActiveSavedView(savedView);
      setItems(filtered);
      onTasksLoaded?.(filtered);
    } catch {
      setItems([]);
      onTasksLoaded?.([]);
      setActiveSavedView(null);
    } finally {
      setLoading(false);
    }
  }, [apiConfigured, workspaceId, projectId, controlled, controlledTasks, onTasksLoaded]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks, liveTick]);

  useEffect(() => {
    if (createRequestedAt > 0) {
      setShowNew(true);
    }
  }, [createRequestedAt]);

  const insertCreatedItem = useCallback(
    (item: TaskDashboardItem) => {
      const nextItems = [item, ...items.filter((candidate) => candidate.id !== item.id)];
      setItems(nextItems);
      onTasksLoaded?.(nextItems);
      onTaskCreated?.(item);
      if (setSelectedTaskId) setSelectedTaskId(item.id);
      if (setRoute) setRoute("project");
    },
    [items, onTaskCreated, onTasksLoaded, setRoute, setSelectedTaskId],
  );

  async function handleCreateTask(e: React.FormEvent) {
    e.preventDefault();
    if (!newPrompt.trim()) return;
    if (!workspaceId) {
      setCreateError("No workspace selected");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const result = await createTaskDraft(workspaceId, newPrompt.trim(), undefined, {
        workspaceId,
        projectId: projectId ?? undefined,
      });
      const task = result.task;
      const newItem: TaskDashboardItem = {
        id: task.id,
        workspace_id: task.workspace_id,
        title: task.title,
        status: "prd_pending",
        phase: task.metadata?.phase ?? "Draft",
        approval_state: "pending",
        graph_state: "none",
        next_gate: "prd approval",
        node_count: 0,
        blocked_count: 0,
        review_needed_count: 0,
        checkpoint_state: "none",
        handoff_state: "none",
        roles: [],
        providers: [],
        updated_at: task.updated_at,
      };
      insertCreatedItem(newItem);
      setShowNew(false);
      setNewPrompt("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setCreating(false);
    }
  }

  const visible = useMemo(() => {
    let filtered = items;
    if (filter === "active") filtered = filtered.filter((t) => t.status === "in_progress");
    else if (filter === "blocked") filtered = filtered.filter((t) => t.blocked_count > 0);
    else if (filter === "done") filtered = filtered.filter((t) => t.status === "done");
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      filtered = filtered.filter((t) => t.title.toLowerCase().includes(q));
    }
    return filtered;
  }, [items, filter, search]);

  const hasProject = Boolean(projectId);
  const summary = useMemo(() => ({
    active: items.filter((task) => task.status === "in_progress").length,
    approvals: items.filter((task) => task.approval_state !== "approved" && task.approval_state !== "none").length,
    checkpoints: items.filter((task) => task.checkpoint_state !== "none").length,
    handoffs: items.filter((task) => task.handoff_state === "ready").length,
  }), [items]);
  const emptyMessage = hasProject
    ? "No tasks yet."
    : "No projects yet.";
  const emptyAction = hasProject
    ? "Create one"
    : "Create one";

  return (
    <div className="dashboard-page">
      <div className="dashboard-header">
        {projectName && (
          <span className="dashboard-eyebrow">{projectName}</span>
        )}
        <h2 className="dashboard-title">Dashboard</h2>
        <p className="dashboard-subtitle">
          {apiConfigured
            ? "Describe what you want to build. Sarathi will ask what it needs, then create the task."
            : "Describe what you want to build. When the service is offline, Sarathi will fall back to a local draft."}
        </p>
        {activeSavedView ? (
          <p className="dashboard-subtitle" style={{ marginTop: 8 }}>
            Active saved view: <strong>{activeSavedView.name}</strong>. {activeSavedView.description}
          </p>
        ) : null}
      </div>

      <div className="task-composer">
        <div className="composer-guidance">
          <span className="guidance-main">
            Describe what you want to build
          </span>
          <span className="guidance-hint">
            Sarathi will ask questions if needed, then create the task
          </span>
        </div>
        {showNew && (
          <form className="composer-form" onSubmit={(e) => { void handleCreateTask(e); }}>
            <textarea
              className="composer-input"
              placeholder="Describe the task or feature…"
              value={newPrompt}
              onChange={(e) => setNewPrompt(e.target.value)}
              autoFocus
              disabled={creating}
              rows={2}
            />
            {createError && (
              <div className="composer-error">{createError}</div>
            )}
            <div className="composer-actions">
              <button
                type="submit"
                className="btn-primary"
                disabled={creating || !newPrompt.trim()}
              >
                {creating ? "Creating…" : "Create"}
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setShowNew(false);
                  setCreateError(null);
                  setNewPrompt("");
                }}
                disabled={creating}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
        {!showNew && (
          <div className="prompt-chips">
            <button
              className="prompt-chip"
              onClick={() => setShowNew(true)}
            >
              + New task
            </button>
          </div>
        )}
      </div>

      <div className="filter-bar">
        <div className="filter-tabs">
          {(["all", "active", "blocked", "done"] as FilterTab[]).map((tab) => (
            <button
              key={tab}
              className={`filter-tab ${filter === tab ? "active" : ""}`}
              onClick={() => setFilter(tab)}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
        <div className="search-wrapper">
          <span className="search-icon">&#128269;</span>
          <input
            className="search-input"
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
          marginBottom: 18,
        }}
      >
        {[
          { label: "Running", value: summary.active },
          { label: "Awaiting approval", value: summary.approvals },
          { label: "Checkpoint ready", value: summary.checkpoints },
          { label: "Handoff ready", value: summary.handoffs },
        ].map((item) => (
          <div
            key={item.label}
            style={{
              border: "1px solid var(--border)",
              background: "var(--surface)",
              borderRadius: "var(--radius)",
              padding: "12px 14px",
            }}
          >
            <div style={{ fontSize: "0.74rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--muted)" }}>
              {item.label}
            </div>
            <div style={{ marginTop: 8, fontSize: "1.35rem", fontWeight: 700 }}>{item.value}</div>
          </div>
        ))}
      </div>

      <div className="task-list">
        {loading && (
          <p className="loading-text">Loading tasks…</p>
        )}
        {!loading && visible.length === 0 && (
          <div className="empty-state">
            {emptyMessage}{" "}
            <button
              className="inline-link"
              onClick={() => setShowNew(true)}
            >
              {emptyAction}
            </button>
          </div>
        )}
        {visible.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onClick={() => {
              if (setSelectedTaskId) setSelectedTaskId(task.id);
              if (setRoute) setRoute("project");
            }}
          />
        ))}
      </div>
    </div>
  );
}

function statusDot(status: string, blockedCount: number): { symbol: string; color: string } {
  if (blockedCount > 0) return { symbol: "⏸", color: "var(--amber)" };
  if (status === "in_progress") return { symbol: "●", color: "var(--green)" };
  if (status === "done") return { symbol: "✓", color: "var(--accent)" };
  return { symbol: "○", color: "var(--faint)" };
}

function TaskCard({
  task,
  onClick,
}: {
  task: TaskDashboardItem;
  onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const phaseLine = task.phase ? `${task.phase} phase` : null;
  const providerLine = task.providers.length > 0 ? task.providers.join(" · ") : null;
  const isBlocked = task.blocked_count > 0;
  const queue = queueLabel(task);
  const cue = nextCue(task);

  return (
    <button
      className={`task-card ${hovered ? "hovered" : ""} ${isBlocked ? "blocked" : ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
    >
      <div className="task-header">
        {isBlocked && <span className="blocked-badge">Blocked</span>}
        <span className={getStatusPillClass(task.status)}>
          {getStatusLabel(task.status)}
        </span>
        <span className={`status-pill ${queueTone(task)}`}>{queue}</span>
        {phaseLine && <span className="phase-pill">{phaseLine}</span>}
        <span className="task-timestamp">{relativeTime(task.updated_at)}</span>
      </div>

      <span className="task-title">{task.title}</span>

      <div className="task-meta">
        {task.node_count > 0 && (
          <span className="meta-item">
            {task.node_count} unit{task.node_count !== 1 ? "s" : ""}
            {task.blocked_count > 0 && (
              <span className="meta-item blocked"> · {task.blocked_count} blocked</span>
            )}
          </span>
        )}
        {task.next_gate && (
          <span className="meta-item gate">&#9888; gate pending</span>
        )}
        {task.review_needed_count > 0 && (
          <span className="meta-item gate">{task.review_needed_count} review need{task.review_needed_count === 1 ? "s" : ""}</span>
        )}
        {task.checkpoint_state !== "none" && (
          <span className="meta-item">checkpoint {task.checkpoint_state}</span>
        )}
        {task.handoff_state !== "none" && (
          <span className="meta-item">handoff {task.handoff_state}</span>
        )}
        {providerLine && <span className="meta-item">{providerLine}</span>}
      </div>

      <div className="task-meta">
        <span className="meta-item">Next: {cue}</span>
      </div>
    </button>
  );
}
