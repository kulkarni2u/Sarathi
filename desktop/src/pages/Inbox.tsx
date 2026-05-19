import { useCallback, useEffect, useMemo, useState } from "react";
import {
  activeSavedViewFromReuseKit,
  approveTaskGate,
  filterInboxItemsBySavedView,
  getSarathiApiConfig,
  getWorkspaceOperationalViews,
  getWorkspaceReuseKit,
  type InboxQueueItem,
  type SavedViewSnapshot,
  type WorkspaceGovernanceSnapshot,
} from "../apiClient";
import { approvalGates } from "../mockData";
import { Pill } from "../components/ui";

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

function mockEntries(): InboxQueueItem[] {
  const pending = approvalGates.filter((gate) => gate.status === "pending" || gate.status === "waiting_human");
  return pending.map((gate) => ({
    id: gate.id,
    kind: "approval",
    workspace_id: "SARATHI-APP",
    task_id: "SA-001",
    title: "Implement Chat Orchestrator",
    summary: `Approval needed: ${gate.name}`,
    state: "awaiting_approval",
    next_action: "Open task",
    updated_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  }));
}

function itemTone(kind: InboxQueueItem["kind"]): "active" | "warning" | "blocked" | "healthy" | "draft" {
  if (kind === "approval" || kind === "checkpoint_ready") return "active";
  if (kind === "handoff_ready") return "healthy";
  if (kind === "blocked_task" || kind === "failed_review" || kind === "provider_failure") return "blocked";
  return "draft";
}

function itemLabel(kind: InboxQueueItem["kind"]): string {
  return kind.replace(/_/g, " ");
}

function kindDescription(item: InboxQueueItem): string {
  if (item.kind === "approval") return "Human approval is required before Sarathi can continue.";
  if (item.kind === "blocked_task") return "Execution is blocked and needs intervention before dispatch can continue.";
  if (item.kind === "failed_review") return "A review failed and the task needs another pass before handoff.";
  if (item.kind === "checkpoint_ready") return "Sarathi captured restart-ready context for a clean continuation.";
  if (item.kind === "handoff_ready") return "A governed handoff is ready for final review and delivery.";
  if (item.kind === "provider_failure") return "A provider failure interrupted the orchestration flow.";
  return item.summary;
}

function approvalGateName(summary: string): string {
  const prefix = "Approval needed:";
  if (summary.startsWith(prefix)) {
    return summary.slice(prefix.length).trim() || "Task graph";
  }
  return "Task graph";
}

interface Props {
  workspaceId?: string | null;
  projectId?: string | null;
  liveTick?: number;
  setRoute?: (r: string) => void;
  setSelectedTaskId?: (id: string) => void;
}

export default function Inbox({ workspaceId, projectId, liveTick, setRoute, setSelectedTaskId }: Props) {
  const [entries, setEntries] = useState<InboxQueueItem[]>([]);
  const [governance, setGovernance] = useState<WorkspaceGovernanceSnapshot | null>(null);
  const [activeSavedView, setActiveSavedView] = useState<SavedViewSnapshot | null>(null);
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
      const [operations, reuseKit] = await Promise.all([
        getWorkspaceOperationalViews(workspaceId),
        getWorkspaceReuseKit(workspaceId),
      ]);
      const scopedEntries = projectId
        ? operations.inbox.filter((entry) => entry.project_id === projectId)
        : operations.inbox;
      const savedView = activeSavedViewFromReuseKit(reuseKit);
      const filteredEntries = filterInboxItemsBySavedView(scopedEntries, savedView);
      setActiveSavedView(savedView);
      setEntries(filteredEntries);
      setGovernance(operations.governance);
      const blocked = filteredEntries.filter((entry) => entry.kind === "blocked_task" || entry.kind === "failed_review").length;
      const decisions = filteredEntries.filter((entry) => entry.kind === "approval").length;
      setStatus(
        `${decisions} decisions, ${blocked} blocked tasks, ${operations.usage.tasks.active} active task${operations.usage.tasks.active === 1 ? "" : "s"} in scope.`,
      );
    } catch {
      setEntries(mockEntries());
      setStatus("Attention queue load failed. Showing fallback queue.");
      setActiveSavedView(null);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, projectId]);

  useEffect(() => {
    void load();
  }, [load, liveTick]);

  async function handleApprove(entry: InboxQueueItem) {
    if (!entry.task_id) return;
    setApprovingId(entry.id);
    try {
      await approveTaskGate(entry.task_id, approvalGateName(entry.summary), "approved");
      await load();
    } catch {
      // ignore — refresh anyway
      await load();
    } finally {
      setApprovingId(null);
    }
  }

  function handleViewProject(entry: InboxQueueItem) {
    if (entry.task_id && setSelectedTaskId) setSelectedTaskId(entry.task_id);
    if (setRoute) setRoute("project");
  }

  const summary = useMemo(() => {
    const decisions = entries.filter((entry) => entry.kind === "approval").length;
    const blocked = entries.filter((entry) => entry.kind === "blocked_task" || entry.kind === "failed_review").length;
    return {
      decisions,
      blocked,
      checkpoints: entries.filter((entry) => entry.kind === "checkpoint_ready").length,
      total: entries.length,
      overrides: governance?.override_history?.length ?? 0,
      repoActions: governance?.repository_action_governance?.pending_count ?? 0,
    };
  }, [entries, governance]);

  return (
    <div style={{ padding: "20px 24px", maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.2rem" }}>Inbox</h1>
          <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
            Decisions, blockers, and restart-ready work in one quieter attention queue.
          </p>
          {activeSavedView && (
            <p style={{ margin: "4px 0 0", fontSize: "0.76rem", color: "var(--faint)" }}>
              {activeSavedView.name} · {activeSavedView.description}
            </p>
          )}
        </div>
        {entries.length > 0 && (
          <span className="pill-mini warning">{entries.length}</span>
        )}
      </div>

      <p style={{ margin: "0 0 12px", fontSize: "0.76rem", color: "var(--muted)" }}>{status}</p>

      <div className="metrics-compact">
        {[
          { label: "Decisions", value: summary.decisions, tone: summary.decisions > 0 ? "warning" : "muted" },
          { label: "Blocked", value: summary.blocked, tone: summary.blocked > 0 ? "blocked" : "muted" },
          { label: "Checkpoints", value: summary.checkpoints, tone: summary.checkpoints > 0 ? "healthy" : "muted" },
          { label: "Overrides", value: summary.overrides, tone: summary.overrides > 0 ? "warning" : "muted" },
          { label: "Repo actions", value: summary.repoActions, tone: summary.repoActions > 0 ? "active" : "muted" },
          { label: projectId ? "Project scope" : "Workspace scope", value: summary.total, tone: "active" },
        ].map((item) => (
          <div key={item.label} className={`metric-compact`}>
            <div className="metric-compact-label">{item.label}</div>
            <div className={`metric-compact-value ${item.tone}`}>{item.value}</div>
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
            {workspaceId ? "No approvals, blockers, failed reviews, or restart-ready work are waiting on you." : "No workspace selected."}
          </p>
          <p style={{ fontSize: "0.78rem", color: "var(--faint)", marginTop: 4 }}>
            {workspaceId
              ? "When Sarathi needs a decision or restart action, it will land here."
              : "Choose a workspace to load its operational queue."}
          </p>
        </div>
      ) : (
        <div>
          {entries.map((entry) => (
            <div key={entry.id} className="inbox-item">
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background:
                    entry.kind === "handoff_ready" ? "var(--status-green-fg)"
                      : entry.kind === "approval" || entry.kind === "checkpoint_ready" ? "var(--status-blue-fg)"
                      : "var(--status-red-fg)",
                  marginTop: 5,
                  flexShrink: 0,
                }}
              />

              <div className="inbox-item-body">
                <div className="inbox-item-header">
                  <span className={`pill-mini ${itemTone(entry.kind)}`}>{itemLabel(entry.kind)}</span>
                  <span style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    {entry.state.replace(/_/g, " ")}
                  </span>
                  <span
                    style={{
                      fontSize: "0.85rem",
                      fontWeight: 500,
                      color: "var(--ink)",
                    }}
                  >
                    {entry.title}
                  </span>
                  <span style={{ fontSize: "0.7rem", color: "var(--faint)" }}>
                    {relativeTime(entry.updated_at)}
                  </span>
                </div>

                <p className="inbox-item-summary">{kindDescription(entry)}</p>
                <p className="inbox-item-meta">{entry.summary}</p>

                <div className="actions" style={{ marginTop: 6 }}>
                  {entry.kind === "approval" && entry.task_id && (
                    <button
                      className="primary"
                      style={{ height: 24, padding: "0 10px", fontSize: "0.72rem" }}
                      disabled={approvingId === entry.id}
                      onClick={() => void handleApprove(entry)}
                    >
                      {approvingId === entry.id ? "Approving…" : "Approve"}
                    </button>
                  )}
                  <button
                    style={{ height: 24, padding: "0 10px", fontSize: "0.72rem" }}
                    onClick={() => handleViewProject(entry)}
                  >
                    Open
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
