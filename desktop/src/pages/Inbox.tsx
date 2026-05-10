import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveTaskGate,
  getWorkspaceOperationalViews,
  listTaskDashboard,
  getSarathiApiConfig,
  type TaskDashboardItem,
} from "../apiClient";
import { approvalGates } from "../mockData";
import { Pill } from "../components/ui";

type InboxItemType = "gate" | "blocked";

interface InboxEntry {
  id: string;
  taskId: string;
  type: InboxItemType;
  title: string;
  description: string;
  detail: string;
  gateName?: string;
  phase: string;
  providerSummary: string;
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
    const providerSummary = task.providers.length > 0 ? task.providers.join(", ") : "Provider pending";
    if (task.approval_state === "prd_pending") {
      entries.push({
        id: `gate-${task.id}`,
        taskId: task.id,
        type: "gate",
        title: task.title,
        description: "Scope approval is required before Sarathi can lock planning and execution.",
        detail: "PRD/acceptance gate is waiting on a human decision.",
        gateName: task.next_gate ?? "PRD/AC",
        phase: task.phase,
        providerSummary,
        updatedAt: task.updated_at,
      });
      continue;
    }
    if (task.approval_state === "graph_pending" || task.approval_state === "approval_pending") {
      const gateName = task.next_gate ?? "Task graph";
      entries.push({
        id: `gate-${task.id}`,
        taskId: task.id,
        type: "gate",
        title: task.title,
        description: `${gateName} needs approval before execution can continue.`,
        detail: `${task.node_count} unit${task.node_count !== 1 ? "s" : ""} prepared for dispatch.`,
        gateName,
        phase: task.phase,
        providerSummary,
        updatedAt: task.updated_at,
      });
      continue;
    }
    if (task.blocked_count > 0) {
      entries.push({
        id: `blocked-${task.id}`,
        taskId: task.id,
        type: "blocked",
        title: task.title,
        description: `${task.blocked_count} unit${task.blocked_count !== 1 ? "s" : ""} blocked. Execution needs intervention or an upstream recovery.`,
        detail: task.next_gate ? `Next gate: ${task.next_gate}.` : "Waiting on dependency or provider progress.",
        phase: task.phase,
        providerSummary,
        updatedAt: task.updated_at,
      });
    }
  }
  return entries.sort((left, right) => {
    const severity = (entry: InboxEntry) => (entry.type === "gate" ? 0 : 1);
    const severityDiff = severity(left) - severity(right);
    if (severityDiff !== 0) return severityDiff;
    return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
  });
}

function mockEntries(): InboxEntry[] {
  const pending = approvalGates.filter((g) => g.status === "pending" || g.status === "waiting_human");
  return pending.map((g) => ({
    id: g.id,
    taskId: "SA-001",
    type: "gate" as const,
    title: "Implement Chat Orchestrator",
    description: "Task graph approval is waiting on a human decision.",
    detail: "4 units prepared for dispatch.",
    gateName: g.name,
    phase: "Plan",
    providerSummary: "Codex, Claude",
    updatedAt: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  }));
}

interface Props {
  workspaceId?: string | null;
  projectId?: string | null;
  liveTick?: number;
  setRoute?: (r: string) => void;
  setSelectedTaskId?: (id: string) => void;
}

export default function Inbox({ workspaceId, projectId, liveTick, setRoute, setSelectedTaskId }: Props) {
  const [entries, setEntries] = useState<InboxEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading attention queue.");

  const load = useCallback(async () => {
    const config = getSarathiApiConfig();
    if (!config) {
      setEntries(mockEntries());
      setStatus("Demo attention queue. Connect the local service for persisted workflow state.");
      setLoading(false);
      return;
    }
    if (!workspaceId) {
      setEntries([]);
      setStatus("Select a workspace to load approvals, blockers, and restart-ready work.");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [tasks, operations] = await Promise.all([
        listTaskDashboard(workspaceId, { projectId }),
        getWorkspaceOperationalViews(workspaceId),
      ]);
      const built = buildEntries(tasks);
      setEntries(built);
      const blocked = built.filter((entry) => entry.type === "blocked").length;
      const decisions = built.filter((entry) => entry.type === "gate").length;
      setStatus(
        `${decisions} decisions, ${blocked} blocked tasks, ${operations.usage.tasks.active} active task${operations.usage.tasks.active === 1 ? "" : "s"} in scope.`,
      );
    } catch {
      setEntries(mockEntries());
      setStatus("Attention queue load failed. Showing fallback queue.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, projectId]);

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
    return "BLOCKED";
  };

  const dotColor = (type: InboxItemType) => {
    if (type === "gate") return "var(--status-blue-fg)";
    if (type === "blocked") return "var(--status-amber-fg)";
    return "var(--status-red-fg)";
  };

  const summary = useMemo(() => {
    const decisions = entries.filter((entry) => entry.type === "gate").length;
    const blocked = entries.filter((entry) => entry.type === "blocked").length;
    return {
      decisions,
      blocked,
      total: entries.length,
    };
  }, [entries]);

  return (
    <div style={{ padding: "24px 28px", maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: 0 }}>Inbox</h1>
          <p style={{ margin: "6px 0 0", fontSize: "0.83rem", color: "var(--muted)" }}>
            Human attention queue for approvals, blockers, and execution interrupts.
          </p>
        </div>
        {entries.length > 0 && (
          <Pill tone="warning">{entries.length} item{entries.length !== 1 ? "s" : ""}</Pill>
        )}
      </div>

      <div style={{ borderBottom: "1px solid var(--border)", marginBottom: 8 }} />
      <p style={{ margin: "12px 0 18px", fontSize: "0.78rem", color: "var(--faint)" }}>{status}</p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {[
          { label: "Needs decision", value: summary.decisions, tone: "active" as const },
          { label: "Blocked now", value: summary.blocked, tone: "warning" as const },
          { label: projectId ? "Project scope" : "Workspace scope", value: summary.total, tone: "default" as const },
        ].map((item) => (
          <div
            key={item.label}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
              padding: "12px 14px",
              background: "var(--surface)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontSize: "0.73rem", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
                {item.label}
              </span>
              <Pill tone={item.tone}>{item.value}</Pill>
            </div>
          </div>
        ))}
      </div>

      {loading ? (
        <div className="loading-overlay">
          <div className="spinner" />
          Loading inbox…
        </div>
      ) : entries.length === 0 ? (
        <div className="empty-state" style={{ paddingTop: 64 }}>
          <div style={{ fontSize: "2rem", marginBottom: 12, color: "var(--faint)" }}>&#10003;</div>
          <p style={{ fontWeight: 500, color: "var(--muted)" }}>
            {workspaceId ? "Sarathi has no decisions waiting for you." : "No workspace selected."}
          </p>
          <p style={{ fontSize: "0.78rem", color: "var(--faint)", marginTop: 4 }}>
            {workspaceId
              ? "When tasks need approval or are blocked, they will appear here."
              : "Choose a workspace to load its operational queue."}
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
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                  <Pill tone={typeBadgeTone(entry.type)}>{typeLabel(entry.type)}</Pill>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    {entry.phase}
                  </span>
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
                <p style={{ margin: "0 0 10px", fontSize: "0.76rem", color: "var(--faint)" }}>
                  {entry.detail} Providers: {entry.providerSummary}.
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
