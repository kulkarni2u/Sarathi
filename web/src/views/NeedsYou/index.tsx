import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiClientError } from "../../api/client";
import type { TaskDashboardRow } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./NeedsYou.css";

/**
 * Needs You — tasks awaiting operator approval/attention across the
 * workspace (the "amber" lane from the Dashboard board, surfaced as its own
 * view + sidebar nav item).
 * Route: /needs-you
 *
 * Data source: GET /workspaces/{id}/task-dashboard, filtered to rows whose
 * derived `queue_state` is one of:
 *   awaiting_approval | blocked | waiting_human | failed | handoff_ready
 *
 * The `/task-dashboard` projection doesn't expose a literal `queue_state`
 * field (that's computed for the Task Studio header instead) — it exposes
 * `approval_state`, `coordination_state`, and `handoff_state`. We derive an
 * equivalent `queue_state` here, mirroring the service's
 * `_task_studio_queue_state` precedence (handoff > failed > approval >
 * coordination), while also honoring a literal `queue_state` field if a
 * future projection adds one directly.
 */

const ATTENTION_STATES = new Set(["awaiting_approval", "blocked", "waiting_human", "failed", "handoff_ready"]);

type AttentionState = "awaiting_approval" | "blocked" | "waiting_human" | "failed" | "handoff_ready";

interface AttentionItem {
  task: TaskDashboardRow;
  queueState: AttentionState;
  reason: string;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/** Derive a queue_state for attention-filtering, mirroring the service's
 * `_task_studio_queue_state` precedence order as closely as possible from
 * the fields available on a /task-dashboard row. */
function deriveQueueState(task: TaskDashboardRow): string {
  const literal = asString(task.queue_state);
  if (literal) return literal;

  const handoffState = asString(task.handoff_state);
  if (handoffState && handoffState !== "none") return "handoff_ready";

  const approvalState = asString(task.approval_state);
  if (approvalState && ["approval_pending", "graph_pending", "prd_pending"].includes(approvalState)) {
    return "awaiting_approval";
  }

  const coordinationState = asString(task.coordination_state);
  if (coordinationState === "blocked") return "blocked";
  if (coordinationState === "waiting_human") return "waiting_human";

  const status = asString(task.status);
  if (status === "failed") return "failed";

  return coordinationState ?? status ?? "unknown";
}

/** Human-readable reason for why a task is in the attention list. */
function describeReason(task: TaskDashboardRow, queueState: string): string {
  switch (queueState) {
    case "awaiting_approval": {
      const gate = asString(task.next_gate);
      return gate ? `Awaiting approval — ${gate}` : "Awaiting approval";
    }
    case "handoff_ready":
      return "Handoff ready for review";
    case "blocked": {
      const blockedCount = typeof task.blocked_count === "number" ? task.blocked_count : undefined;
      return blockedCount ? `Blocked — ${blockedCount} node(s) stuck` : "Blocked";
    }
    case "waiting_human":
      return "Waiting on human input";
    case "failed":
      return "Failed — needs review";
    default:
      return "Needs attention";
  }
}

/** Tag styling reused from the dashboard's `.tag .t-*` variants
 * (defined in Dashboard.css, but the class names are shared conventions —
 * we define equivalents locally to avoid depending on another view's CSS). */
function queueStateLabel(queueState: string): string {
  switch (queueState) {
    case "awaiting_approval":
      return "awaiting approval";
    case "handoff_ready":
      return "handoff ready";
    case "blocked":
      return "blocked";
    case "waiting_human":
      return "waiting on human";
    case "failed":
      return "failed";
    default:
      return queueState;
  }
}

function queueStateVariant(queueState: string): string {
  switch (queueState) {
    case "awaiting_approval":
    case "handoff_ready":
      return "wn"; // amber
    case "blocked":
    case "failed":
      return "err"; // red
    case "waiting_human":
      return "wn";
    default:
      return "of";
  }
}

/** Render a relative age string from an ISO timestamp, e.g. "2h ago". */
function formatAge(updatedAt: string | undefined): string {
  if (!updatedAt) return "—";
  const then = Date.parse(updatedAt);
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  if (diffMs < 0) return "just now";
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function NeedsYou() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const navigate = useNavigate();

  const [tasks, setTasks] = useState<TaskDashboardRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setTasks(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .getTaskDashboard(currentWorkspaceId, undefined, controller.signal)
      .then((data) => setTasks(data.tasks ?? []))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setTasks([]);
        setError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId]);

  const items = useMemo<AttentionItem[]>(() => {
    if (!tasks) return [];
    const result: AttentionItem[] = [];
    for (const task of tasks) {
      const queueState = deriveQueueState(task);
      if (!ATTENTION_STATES.has(queueState)) continue;
      result.push({ task, queueState: queueState as AttentionState, reason: describeReason(task, queueState) });
    }
    // Most-recently-updated first, so the freshest items needing attention surface first.
    result.sort((a, b) => {
      const aTime = Date.parse(asString(a.task.updated_at) ?? "");
      const bTime = Date.parse(asString(b.task.updated_at) ?? "");
      const aValid = !Number.isNaN(aTime);
      const bValid = !Number.isNaN(bTime);
      if (aValid && bValid) return bTime - aTime;
      if (aValid) return -1;
      if (bValid) return 1;
      return 0;
    });
    return result;
  }, [tasks]);

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Needs you</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · tasks awaiting approval,
              blocked, or otherwise needing operator attention
            </p>
          </div>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — attention list may be stale or unavailable.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && loading && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          Loading attention items…
        </div>
      )}

      {currentWorkspaceId && !loading && error && (
        <div className="banner offline">⚠ Failed to load task dashboard: {error}</div>
      )}

      {currentWorkspaceId && !loading && !error && items.length === 0 && (
        <div className="card2 ny-empty">
          <span className="ny-empty-icon" aria-hidden="true">
            {"✅"}
          </span>
          Nothing needs your attention right now.
        </div>
      )}

      {currentWorkspaceId && !loading && !error && items.length > 0 && (
        <div className="ny-list">
          {items.map(({ task, queueState, reason }) => {
            const variant = queueStateVariant(queueState);
            return (
              <button
                key={task.id}
                className="ny-row"
                type="button"
                onClick={() => navigate(`/task/${encodeURIComponent(task.id)}`)}
              >
                <div className="ny-main">
                  <div className="ny-title">{asString(task.title) ?? task.id}</div>
                  <div className="ny-meta">
                    <span className={`st ${variant}`}>
                      <span className="d" />
                      {queueStateLabel(queueState)}
                    </span>
                    <span className="ny-reason">{reason}</span>
                  </div>
                </div>
                <span className="ny-age">{formatAge(asString(task.updated_at))}</span>
                <span className="btn ghost ny-action" title="Open in Task Studio">
                  Review →
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
