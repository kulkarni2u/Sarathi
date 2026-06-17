import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import { useWorkspace } from "../../context/WorkspaceContext";
import type {
  AnyRecord,
  LifecycleEvent,
  OperationalViewsData,
  TaskDashboardRow,
} from "../../api/types";
import "./History.css";

/**
 * History — phase transitions and governance events for the active workspace.
 * Route: /history
 *
 * Data source: GET /workspaces/{id}/operational-views (`history` array of
 * lifecycle events + `projects`/task titles for lookups), falling back to
 * GET /events?workspace_id=... if the operational-views projection is
 * unavailable.
 */

type OutcomeTone = "run" | "plan" | "need" | "block" | "review" | "done";

interface OutcomeTag {
  label: string;
  tone: OutcomeTone;
}

interface HistoryRow {
  id: string;
  time: string;
  taskLabel: string;
  transition: string;
  outcome: OutcomeTag;
  iteration: number | null;
  decisions: string;
}

const FILTERS = ["All", "Approvals", "Failures"] as const;
type Filter = (typeof FILTERS)[number];

export default function History() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [data, setData] = useState<OperationalViewsData | null>(null);
  const [events, setEvents] = useState<LifecycleEvent[] | null>(null);
  const [tasks, setTasks] = useState<TaskDashboardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [filter, setFilter] = useState<Filter>("All");

  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
      setEvents(null);
      setTasks([]);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const views = await api.getWorkspaceOperationalViews(currentWorkspaceId!, controller.signal);
        if (cancelled) return;
        setData(views);
        setEvents(null);
      } catch (viewsErr) {
        if (cancelled) return;
        // Fall back to the raw events feed if the operational-views
        // projection isn't available.
        try {
          const ev = await api.getEvents({ workspaceId: currentWorkspaceId! }, controller.signal);
          if (cancelled) return;
          setEvents(ev.events ?? []);
          setData(null);
        } catch (eventsErr) {
          if (cancelled) return;
          setError(eventsErr instanceof Error ? eventsErr : new Error(String(eventsErr)));
          setData(null);
          setEvents(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }

      // Best-effort: task titles for the "Task" column (operational-views
      // doesn't expose a flat task list with titles).
      try {
        const dashboard = await api.getTaskDashboard(currentWorkspaceId!, undefined, controller.signal);
        if (!cancelled) setTasks(dashboard.tasks ?? []);
      } catch {
        if (!cancelled) setTasks([]);
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentWorkspaceId]);

  const taskTitleById = useMemo(() => {
    const map = new Map<string, string>();

    // Diagrams in operational-views carry `task_id` + `title` for
    // dependency graphs, review loops, and handoffs.
    if (data) {
      const diagrams = asArray(data["diagrams"]) ?? [];
      for (const diagram of diagrams) {
        const id = stringField(diagram, "task_id");
        const title = stringField(diagram, "title");
        if (id && title) map.set(id, title.replace(/^(Review loop|Handoff):\s*/i, ""));
      }
    }

    // Task dashboard rows give canonical titles, and take precedence.
    for (const t of tasks) {
      const id = stringField(t, "id");
      const title = stringField(t, "title") ?? stringField(t, "name");
      if (id && title) map.set(id, title);
    }

    return map;
  }, [data, tasks]);

  const rows = useMemo<HistoryRow[]>(() => {
    const rawEvents = data ? (asArray(data["history"]) ?? []) : events ?? [];
    return rawEvents
      .slice()
      .reverse() // most recent first
      .map((evt) => toHistoryRow(evt, taskTitleById));
  }, [data, events, taskTitleById]);

  const filteredRows = useMemo(() => {
    if (filter === "All") return rows;
    if (filter === "Approvals") {
      return rows.filter((r) => r.outcome.tone === "need" || /approv/i.test(r.decisions));
    }
    // Failures
    return rows.filter((r) => r.outcome.tone === "block");
  }, [rows, filter]);

  const offline = serviceStatus === "offline";

  return (
    <div>
      <div className="ph">
        <div className="row">
          <div>
            <h1>History</h1>
            <p>
              Phase transitions and governance events
              {currentWorkspace?.name ? ` · ${currentWorkspace.name}` : ""}
            </p>
          </div>
          <div className="grow" />
          <div className="seg hist-seg">
            {FILTERS.map((f) => (
              <button key={f} className={f === filter ? "on" : ""} onClick={() => setFilter(f)}>
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {offline && (
        <div className="banner offline">
          Service is offline — history events can't be loaded right now.
        </div>
      )}

      {!offline && error && (
        <div className="banner warn">
          Couldn't load history ({error.message}). Showing what's available.
        </div>
      )}

      {!currentWorkspaceId ? (
        <div className="card2 hist-card">
          <div className="hist-empty">No workspace selected yet.</div>
        </div>
      ) : loading ? (
        <div className="card2 hist-card">
          <div className="hist-loading">Loading history…</div>
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="card2 hist-card">
          <div className="hist-empty">
            {rows.length === 0
              ? "No phase transitions or governance events recorded yet."
              : "No events match this filter."}
          </div>
        </div>
      ) : (
        <div className="card2 hist-card">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Task</th>
                <th>Transition</th>
                <th>Outcome</th>
                <th>Iter</th>
                <th>Key decisions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr key={row.id}>
                  <td className="hist-num">{row.time}</td>
                  <td>{row.taskLabel}</td>
                  <td>{row.transition}</td>
                  <td>
                    <span className={`tag t-${row.outcome.tone}`}>
                      <span className="d" />
                      {row.outcome.label}
                    </span>
                  </td>
                  <td className="hist-num">{row.iteration ?? "—"}</td>
                  <td className="hist-decisions">{row.decisions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function asArray(value: unknown): AnyRecord[] | null {
  return Array.isArray(value) ? (value as AnyRecord[]) : null;
}

function stringField(record: AnyRecord, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

function toHistoryRow(evt: LifecycleEvent, taskTitleById: Map<string, string>): HistoryRow {
  const eventType = (evt["event_type"] as string | undefined) ?? "event";
  const payload = (evt["payload"] as AnyRecord | undefined) ?? {};
  const taskId = (evt["task_id"] as string | undefined) ?? undefined;
  const taskLabel = taskId
    ? taskTitleById.get(taskId) ?? `Task ${taskId.slice(0, 8)}`
    : "Workspace";

  const transition = transitionForEvent(eventType, payload);
  const outcome = outcomeForEvent(eventType, payload);
  const iteration = iterationForEvent(payload);
  const decisions = decisionsForEvent(eventType, payload);
  const time = formatTime((evt["created_at"] as string | undefined) ?? null);

  return {
    id: (evt["id"] as string | undefined) ?? `${eventType}-${time}-${Math.random()}`,
    time,
    taskLabel,
    transition,
    outcome,
    iteration,
    decisions,
  };
}

/** Map a lifecycle event_type to a human PHASE → PHASE transition label. */
function transitionForEvent(eventType: string, payload: AnyRecord): string {
  const phase = typeof payload["phase"] === "string" ? (payload["phase"] as string) : undefined;
  switch (eventType) {
    case "task.draft_created":
    case "task.created":
    case "task.chat_created":
      return "— → PLAN";
    case "task.graph_draft_created":
      return "PLAN → BUILD";
    case "task.auto_schedule":
    case "subtask.scheduled":
      return "PLAN → BUILD";
    case "subtask.dispatched":
    case "context.compiled":
      return phase ? `${phase.toUpperCase()} · dispatch` : "BUILD";
    case "subtask.transitioned":
      return "BUILD → VERIFY";
    case "subtask.unblocked":
      return "BUILD";
    case "evidence.created":
      return "BUILD → VERIFY";
    case "review.completed":
    case "review.rejected":
      return "VERIFY → REVIEW";
    case "approval.requested":
      return "REVIEW · gate";
    case "approval.recorded":
      return "REVIEW → BUILD";
    case "handoff.created":
      return "REVIEW → LEARN";
    case "repository_action.approved":
      return "LEARN · merge";
    case "task.checkpoint_restarted":
      return "LEARN → PLAN";
    case "proposal.accepted":
    case "proposal.rejected":
    case "learning.accepted":
      return "LEARN · proposal";
    case "workspace.governance_updated":
    case "workspace.reuse_updated":
      return "Governance";
    case "workspace.created":
    case "workspace.repository.attached":
    case "workspace.repository.initialized":
      return "Workspace setup";
    case "provider.health_checked":
      return "Agents · health check";
    case "message.created":
      return "Conversation";
    default:
      return eventType.replace(/[._]/g, " ");
  }
}

/** Map a lifecycle event_type/payload to an outcome tag (chip). */
function outcomeForEvent(eventType: string, payload: AnyRecord): OutcomeTag {
  const status = typeof payload["status"] === "string" ? (payload["status"] as string) : undefined;

  switch (eventType) {
    case "review.rejected":
    case "approval.recorded":
      if (status === "rejected") return { label: "fail", tone: "block" };
      return { label: "pass", tone: "done" };
    case "review.completed":
      return status === "approved" || status === "passed"
        ? { label: "pass", tone: "done" }
        : { label: "review", tone: "review" };
    case "approval.requested":
      return { label: "gate", tone: "need" };
    case "subtask.dispatched":
      if (status === "failed") return { label: "fail", tone: "block" };
      if (status === "completed") return { label: "done", tone: "done" };
      return { label: "running", tone: "run" };
    case "subtask.transitioned":
    case "context.compiled":
    case "subtask.scheduled":
      return { label: "running", tone: "run" };
    case "subtask.unblocked":
      return { label: "unblocked", tone: "plan" };
    case "handoff.created":
      return { label: "ready", tone: "review" };
    case "repository_action.approved":
      return { label: "merged", tone: "done" };
    case "proposal.rejected":
      return { label: "rejected", tone: "block" };
    case "proposal.accepted":
    case "learning.accepted":
      return { label: "accepted", tone: "done" };
    case "task.created":
    case "task.draft_created":
    case "task.chat_created":
    case "task.graph_draft_created":
    case "task.auto_schedule":
      return { label: "plan", tone: "plan" };
    case "workspace.governance_updated":
      return { label: "updated", tone: "review" };
    case "provider.health_checked": {
      const health = typeof payload["health"] === "string" ? (payload["health"] as string) : undefined;
      if (health === "online") return { label: "ready", tone: "done" };
      if (health === "offline") return { label: "offline", tone: "block" };
      return { label: "checked", tone: "plan" };
    }
    default:
      if (status === "failed" || status === "blocked" || status === "rejected") {
        return { label: status, tone: "block" };
      }
      if (status === "approved" || status === "completed" || status === "done" || status === "passed") {
        return { label: status, tone: "done" };
      }
      if (status === "pending" || status === "requested") {
        return { label: status, tone: "need" };
      }
      return { label: "event", tone: "plan" };
  }
}

function iterationForEvent(payload: AnyRecord): number | null {
  for (const key of ["iteration", "attempt", "iteration_count", "loop_count"]) {
    const value = payload[key];
    if (typeof value === "number") return value;
  }
  return null;
}

/** Build a short "key decisions" summary string from the event payload. */
function decisionsForEvent(eventType: string, payload: AnyRecord): string {
  const parts: string[] = [];

  switch (eventType) {
    case "subtask.dispatched": {
      if (payload["provider"]) parts.push(`Dispatched to ${payload["provider"]}`);
      if (payload["status"]) parts.push(`status: ${payload["status"]}`);
      break;
    }
    case "context.compiled": {
      if (payload["role"]) parts.push(`Role ${payload["role"]}`);
      if (payload["provider"]) parts.push(`→ ${payload["provider"]}`);
      if (typeof payload["estimated_tokens"] === "number") {
        parts.push(`~${formatCompact(payload["estimated_tokens"] as number)} tokens`);
      }
      break;
    }
    case "approval.requested": {
      if (payload["name"]) parts.push(`Approval requested: ${payload["name"]}`);
      break;
    }
    case "approval.recorded": {
      if (payload["name"]) parts.push(`${payload["name"]}`);
      if (payload["status"]) parts.push(`→ ${payload["status"]}`);
      break;
    }
    case "review.completed":
    case "review.rejected": {
      if (payload["review_type"]) parts.push(`${payload["review_type"]} review`);
      if (payload["status"]) parts.push(payload["status"] as string);
      if (payload["summary"]) parts.push(String(payload["summary"]));
      break;
    }
    case "handoff.created": {
      parts.push("Handoff created for human review");
      break;
    }
    case "repository_action.approved": {
      if (payload["action"]) parts.push(`Repository action: ${payload["action"]}`);
      break;
    }
    case "provider.health_checked": {
      if (payload["object_id"]) parts.push(`${payload["object_id"]}`);
      if (payload["health"]) parts.push(`health: ${payload["health"]}`);
      if (payload["auth"]) parts.push(`auth: ${payload["auth"]}`);
      break;
    }
    case "proposal.accepted":
    case "proposal.rejected":
    case "learning.accepted": {
      if (payload["title"]) parts.push(String(payload["title"]));
      break;
    }
    case "workspace.governance_updated": {
      parts.push("Governance/policy posture updated");
      break;
    }
    case "task.graph_draft_created": {
      parts.push("Task graph drafted");
      break;
    }
    case "task.draft_created":
    case "task.created":
    case "task.chat_created": {
      if (payload["agent"]) parts.push(`Routed to ${payload["agent"]}`);
      break;
    }
    default:
      break;
  }

  if (parts.length === 0) {
    // Generic fallback: surface a couple of scalar payload fields.
    for (const [key, value] of Object.entries(payload)) {
      if (parts.length >= 2) break;
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
        parts.push(`${key}: ${value}`);
      }
    }
  }

  return parts.length > 0 ? parts.join(" · ") : "—";
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;

  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";

  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays >= 0 && diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}
