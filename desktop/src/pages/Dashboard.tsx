import { useState, useEffect, useCallback } from "react";
import {
  getSarathiApiConfig,
  listTaskDashboard,
  createTaskDraft,
  type TaskDashboardItem,
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
    roles: ["Pravaha"],
    providers: ["Codex"],
    updated_at: new Date(Date.now() - 5 * 60000).toISOString(),
  }));
}

type FilterTab = "all" | "active" | "blocked" | "done";

interface DashboardProps {
  workspaceId?: string | null;
  setSelectedTaskId?: (id: string) => void;
  setRoute?: (r: string) => void;
  liveTick?: number;
}

export default function Dashboard({
  workspaceId,
  setSelectedTaskId,
  setRoute,
  liveTick = 0,
}: DashboardProps) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [items, setItems] = useState<TaskDashboardItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [newPrompt, setNewPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    if (!apiConfigured || !workspaceId) {
      setItems(mockTasksToDashboardItems());
      return;
    }
    setLoading(true);
    try {
      const list = await listTaskDashboard(workspaceId);
      setItems(list.length > 0 ? list : mockTasksToDashboardItems());
    } catch {
      setItems(mockTasksToDashboardItems());
    } finally {
      setLoading(false);
    }
  }, [apiConfigured, workspaceId]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks, liveTick]);

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
      const result = await createTaskDraft(workspaceId, newPrompt.trim());
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
        roles: [],
        providers: [],
        updated_at: task.updated_at,
      };
      setItems((prev) => [newItem, ...prev]);
      setShowNew(false);
      setNewPrompt("");
      if (setSelectedTaskId) setSelectedTaskId(task.id);
      if (setRoute) setRoute("project");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setCreating(false);
    }
  }

  function applyFilter(list: TaskDashboardItem[]): TaskDashboardItem[] {
    let filtered = list;
    if (filter === "active") filtered = filtered.filter((t) => t.status === "in_progress");
    else if (filter === "blocked") filtered = filtered.filter((t) => t.blocked_count > 0);
    else if (filter === "done") filtered = filtered.filter((t) => t.status === "done");
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      filtered = filtered.filter((t) => t.title.toLowerCase().includes(q));
    }
    return filtered;
  }

  const visible = applyFilter(items);

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>Dashboard</h2>
        <button
          style={styles.newBtn}
          onClick={() => setShowNew((v) => !v)}
        >
          + New project
        </button>
      </div>

      {/* New project form */}
      {showNew && (
        <form onSubmit={(e) => { void handleCreateTask(e); }} style={styles.newForm}>
          <input
            style={styles.input}
            type="text"
            placeholder="Describe the task or feature…"
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            autoFocus
            disabled={creating}
          />
          {createError && (
            <div style={styles.errorText}>{createError}</div>
          )}
          <div style={styles.formActions}>
            <button
              type="submit"
              style={{ ...styles.btn, ...styles.btnPrimary }}
              disabled={creating || !newPrompt.trim()}
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              style={styles.btn}
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

      {/* Divider */}
      <div style={styles.divider} />

      {/* Filter bar */}
      <div style={styles.filterBar}>
        <div style={styles.tabs}>
          {(["all", "active", "blocked", "done"] as FilterTab[]).map((tab) => (
            <button
              key={tab}
              style={{
                ...styles.tab,
                ...(filter === tab ? styles.tabActive : {}),
              }}
              onClick={() => setFilter(tab)}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
        <div style={styles.searchWrapper}>
          <span style={styles.searchIcon}>&#128269;</span>
          <input
            style={styles.searchInput}
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Task list */}
      <div style={styles.list}>
        {loading && (
          <p style={styles.loadingText}>Loading tasks…</p>
        )}
        {!loading && visible.length === 0 && (
          <div style={styles.emptyState}>
            No projects yet.{" "}
            <button
              style={styles.inlineLink}
              onClick={() => setShowNew(true)}
            >
              Create one
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
  if (blockedCount > 0) return { symbol: "⏸", color: "var(--s-amber)" };
  if (status === "in_progress") return { symbol: "●", color: "var(--s-green)" };
  if (status === "done") return { symbol: "✓", color: "var(--s-accent)" };
  return { symbol: "○", color: "var(--s-faint)" };
}

function TaskCard({
  task,
  onClick,
}: {
  task: TaskDashboardItem;
  onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const dot = statusDot(task.status, task.blocked_count);
  const providerLine = task.providers.length > 0 ? task.providers.join(" · ") : null;
  const phaseLine = task.phase ? `${task.phase} phase` : null;

  return (
    <button
      style={{
        ...styles.taskCard,
        ...(hovered ? styles.taskCardHover : {}),
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
    >
      <div style={styles.taskRow}>
        <span style={{ ...styles.statusDot, color: dot.color }}>{dot.symbol}</span>
        <span style={styles.taskTitle}>{task.title}</span>
      </div>

      {(providerLine || phaseLine) && (
        <div style={styles.taskSub}>
          {providerLine && <span>{providerLine}</span>}
          {providerLine && phaseLine && <span style={styles.sep}>·</span>}
          {phaseLine && <span>{phaseLine}</span>}
        </div>
      )}

      <div style={styles.taskMeta}>
        {task.node_count > 0 && (
          <span>
            {task.node_count} unit{task.node_count !== 1 ? "s" : ""}
            {task.blocked_count > 0 && (
              <span style={styles.blockedBadge}> · {task.blocked_count} blocked</span>
            )}
          </span>
        )}
        {task.next_gate && (
          <span style={styles.gateBadge}>&#9888; gate pending</span>
        )}
        <span style={styles.timestamp}>{relativeTime(task.updated_at)}</span>
      </div>
    </button>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    padding: "20px 24px",
    boxSizing: "border-box",
    overflow: "auto",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    color: "var(--s-ink)",
    margin: 0,
  },
  newBtn: {
    background: "var(--s-accent)",
    color: "#fff",
    border: "none",
    borderRadius: "var(--s-radius-sm)",
    padding: "6px 12px",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
    font: "inherit",
  },
  newForm: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    marginBottom: 12,
    padding: "12px",
    background: "var(--s-surface)",
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius)",
  },
  input: {
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius-sm)",
    padding: "7px 10px",
    fontSize: 13,
    color: "var(--s-ink)",
    background: "var(--s-canvas)",
    outline: "none",
    width: "100%",
    boxSizing: "border-box",
    font: "inherit",
  },
  errorText: {
    color: "var(--s-red)",
    fontSize: 12,
  },
  formActions: {
    display: "flex",
    gap: 6,
  },
  btn: {
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius-sm)",
    padding: "5px 12px",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
    background: "var(--s-surface)",
    color: "var(--s-ink)",
    font: "inherit",
  },
  btnPrimary: {
    background: "var(--s-accent)",
    color: "#fff",
    border: "none",
  },
  divider: {
    height: 1,
    background: "var(--s-border)",
    marginBottom: 12,
  },
  filterBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
    gap: 8,
  },
  tabs: {
    display: "flex",
    gap: 4,
  },
  tab: {
    border: "none",
    background: "none",
    borderRadius: "var(--s-radius-sm)",
    padding: "5px 10px",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
    color: "var(--s-muted)",
    font: "inherit",
  },
  tabActive: {
    background: "var(--s-accent-bg)",
    color: "var(--s-accent)",
  },
  searchWrapper: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius-sm)",
    padding: "4px 8px",
    background: "var(--s-surface)",
  },
  searchIcon: {
    fontSize: 13,
    color: "var(--s-faint)",
  },
  searchInput: {
    border: "none",
    outline: "none",
    fontSize: 13,
    color: "var(--s-ink)",
    background: "transparent",
    width: 140,
    font: "inherit",
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  loadingText: {
    fontSize: 13,
    color: "var(--s-muted)",
  },
  emptyState: {
    fontSize: 13,
    color: "var(--s-muted)",
    padding: "24px 0",
    textAlign: "center",
  },
  inlineLink: {
    background: "none",
    border: "none",
    color: "var(--s-accent)",
    cursor: "pointer",
    fontSize: "inherit",
    padding: 0,
    textDecoration: "underline",
    font: "inherit",
  },
  taskCard: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    padding: "12px 16px",
    background: "var(--s-surface)",
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius)",
    cursor: "pointer",
    textAlign: "left",
    width: "100%",
    boxSizing: "border-box",
    transition: "box-shadow 0.15s ease",
    font: "inherit",
    color: "inherit",
    outline: "none",
  },
  taskCardHover: {
    boxShadow: "var(--s-shadow)",
  },
  taskRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  statusDot: {
    fontSize: 14,
    lineHeight: 1,
    flexShrink: 0,
  },
  taskTitle: {
    fontWeight: 600,
    fontSize: 14,
    color: "var(--s-ink)",
  },
  taskSub: {
    fontSize: 12,
    color: "var(--s-muted)",
    paddingLeft: 22,
    display: "flex",
    gap: 6,
    alignItems: "center",
  },
  sep: {
    color: "var(--s-faint)",
  },
  taskMeta: {
    fontSize: 12,
    color: "var(--s-muted)",
    paddingLeft: 22,
    display: "flex",
    gap: 8,
    alignItems: "center",
    flexWrap: "wrap",
  },
  blockedBadge: {
    color: "var(--s-amber)",
    fontWeight: 500,
  },
  gateBadge: {
    background: "var(--s-amber-bg)",
    color: "var(--s-amber)",
    fontSize: 11,
    fontWeight: 600,
    borderRadius: 4,
    padding: "2px 6px",
  },
  timestamp: {
    color: "var(--s-faint)",
    marginLeft: "auto",
  },
};
