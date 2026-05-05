import { useEffect, useState, useCallback } from "react";
import {
  approveTaskGate,
  listTaskDashboard,
  getSarathiApiConfig,
  type TaskDashboardItem,
} from "../apiClient";
import { approvalGates } from "../mockData";
import { Pill } from "../components/ui";

type InboxItemType = "gate" | "blocked" | "rate_limited";

interface InboxEntry {
  id: string;
  taskId: string;
  type: InboxItemType;
  title: string;
  description: string;
  gateName?: string;
  updatedAt: string;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function buildEntries(tasks: TaskDashboardItem[]): InboxEntry[] {
  const entries: InboxEntry[] = [];
  for (const task of tasks) {
    if (task.approval_state.includes("pending")) {
      entries.push({
        id: `gate-${task.id}`,
        taskId: task.id,
        type: "gate",
        title: task.title,
        description: `Task graph: ${task.node_count} unit${task.node_count !== 1 ? "s" : ""}. Approve to dispatch.`,
        gateName: task.next_gate ?? "Task graph",
        updatedAt: task.updated_at,
      });
    } else if (task.blocked_count > 0) {
      entries.push({
        id: `blocked-${task.id}`,
        taskId: task.id,
        type: "blocked",
        title: task.title,
        description: `${task.blocked_count} unit${task.blocked_count !== 1 ? "s" : ""} blocked. Provider may be offline.`,
        updatedAt: task.updated_at,
      });
    }
  }
  return entries;
}

function mockEntries(): InboxEntry[] {
  const pending = approvalGates.filter((g) => g.status === "pending" || g.status === "waiting_human");
  return pending.map((g) => ({
    id: g.id,
    taskId: "SA-001",
    type: "gate" as const,
    title: "Implement Chat Orchestrator",
    description: "Task graph: 4 units. Approve to dispatch.",
    gateName: g.name,
    updatedAt: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  }));
}

interface Props {
  workspaceId?: string | null;
  liveTick?: number;
  setRoute?: (r: string) => void;
  setSelectedTaskId?: (id: string) => void;
}

export default function Inbox({ workspaceId, liveTick, setRoute, setSelectedTaskId }: Props) {
  const [entries, setEntries] = useState<InboxEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const config = getSarathiApiConfig();
    if (!config || !workspaceId) {
      setEntries(mockEntries());
      setLoading(false);
      return;
    }
    try {
      const tasks = await listTaskDashboard(workspaceId);
      const built = buildEntries(tasks);
      // Also add a demo rate-limit item if nothing else is present
      setEntries(built);
    } catch {
      setEntries(mockEntries());
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load, liveTick]);

  async function handleApprove(entry: InboxEntry) {
    setApprovingId(entry.id);
    try {
      await approveTaskGate(entry.taskId, entry.gateName ?? "Task graph", "approved");
      await load();
    } catch {
      // ignore — refresh anyway
      await load();
    } finally {
      setApprovingId(null);
    }
  }

  function handleViewProject(entry: InboxEntry) {
    if (setSelectedTaskId) setSelectedTaskId(entry.taskId);
    if (setRoute) setRoute("project");
  }

  const typeBadgeTone = (type: InboxItemType) => {
    if (type === "gate") return "active";
    if (type === "blocked") return "warning";
    return "warning";
  };

  const typeLabel = (type: InboxItemType) => {
    if (type === "gate") return "GATE";
    if (type === "blocked") return "BLOCKED";
    return "RATE LIMIT";
  };

  const dotColor = (type: InboxItemType) => {
    if (type === "gate") return "var(--status-blue-fg)";
    if (type === "blocked") return "var(--status-amber-fg)";
    return "var(--status-red-fg)";
  };

  return (
    <div style={{ padding: "24px 28px", maxWidth: 760 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>Inbox</h1>
        {entries.length > 0 && (
          <Pill tone="warning">{entries.length} item{entries.length !== 1 ? "s" : ""}</Pill>
        )}
      </div>

      {/* Divider */}
      <div style={{ borderBottom: "1px solid var(--border)", marginBottom: 8 }} />

      {loading ? (
        <div className="loading-overlay">
          <div className="spinner" />
          Loading inbox…
        </div>
      ) : entries.length === 0 ? (
        <div className="empty-state" style={{ paddingTop: 64 }}>
          <div style={{ fontSize: "2rem", marginBottom: 12, color: "var(--faint)" }}>&#10003;</div>
          <p style={{ fontWeight: 500, color: "var(--muted)" }}>Sarathi has no decisions waiting for you.</p>
          <p style={{ fontSize: "0.78rem", color: "var(--faint)", marginTop: 4 }}>
            When tasks need approval or are blocked, they will appear here.
          </p>
        </div>
      ) : (
        <div>
          {entries.map((entry) => (
            <div
              key={entry.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
                padding: "14px 0",
                borderBottom: "1px solid var(--border)",
              }}
            >
              {/* Indicator dot */}
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: dotColor(entry.type),
                  marginTop: 5,
                  flexShrink: 0,
                }}
              />

              {/* Body */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <Pill tone={typeBadgeTone(entry.type)}>{typeLabel(entry.type)}</Pill>
                  <span
                    style={{
                      fontSize: "0.855rem",
                      fontWeight: 500,
                      color: "var(--ink)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {entry.title}
                  </span>
                  <span style={{ fontSize: "0.75rem", color: "var(--faint)", flexShrink: 0 }}>
                    {relativeTime(entry.updatedAt)}
                  </span>
                </div>

                <p
                  style={{
                    margin: "0 0 10px",
                    fontSize: "0.8rem",
                    color: "var(--muted)",
                    lineHeight: 1.5,
                  }}
                >
                  {entry.description}
                </p>

                <div className="actions">
                  {entry.type === "gate" && (
                    <button
                      className="primary"
                      style={{ height: 30, padding: "0 12px", fontSize: "0.8rem" }}
                      disabled={approvingId === entry.id}
                      onClick={() => void handleApprove(entry)}
                    >
                      {approvingId === entry.id ? "Approving…" : "Approve"}
                    </button>
                  )}
                  <button
                    style={{ height: 30, padding: "0 12px", fontSize: "0.8rem" }}
                    onClick={() => handleViewProject(entry)}
                  >
                    View project
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
