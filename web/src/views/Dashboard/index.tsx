import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiClientError } from "../../api/client";
import type { TaskDashboardRow } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Dashboard.css";

/**
 * Dashboard — Kanban board of tasks across the active workspace.
 *
 * Loads GET /workspaces/{id}/task-dashboard (optionally filtered by
 * project_id) and groups rows into 5 lanes by `queue_state`:
 *   Intake/Planning <- intake, planning
 *   Active          <- ready, running
 *   Needs You       <- awaiting_approval, blocked, waiting_human, failed
 *   Review          <- under_review
 *   Done/Handoff    <- handoff_ready, done
 *
 * A board/list toggle and project filter chips (derived from the rows'
 * project_id) replicate docs/mockups/sarathi-webui-mockup.html's Dashboard
 * section.
 */

type LaneKey = "intake" | "active" | "needs_you" | "review" | "done";

interface Lane {
  key: LaneKey;
  label: string;
  color: string;
  queueStates: string[];
}

const LANES: Lane[] = [
  {
    key: "intake",
    label: "Intake / Planning",
    color: "var(--slate)",
    queueStates: ["intake", "planning"],
  },
  {
    key: "active",
    label: "Active",
    color: "var(--blue)",
    queueStates: ["ready", "running"],
  },
  {
    key: "needs_you",
    label: "Needs You",
    color: "var(--amber)",
    queueStates: ["awaiting_approval", "blocked", "waiting_human", "failed"],
  },
  {
    key: "review",
    label: "Review",
    color: "var(--purple)",
    queueStates: ["under_review"],
  },
  {
    key: "done",
    label: "Done / Handoff",
    color: "var(--green)",
    queueStates: ["handoff_ready", "done"],
  },
];

/** Map a row's queue_state to one of the 5 lanes. Unknown/missing states
 * fall back to Intake/Planning so nothing silently disappears from the
 * board. */
function laneForRow(row: TaskDashboardRow): LaneKey {
  const queueState = typeof row.queue_state === "string" ? row.queue_state : undefined;
  for (const lane of LANES) {
    if (queueState && lane.queueStates.includes(queueState)) return lane.key;
  }
  return "intake";
}

/** Status tag chip class, keyed by queue_state (falls back to phase/status). */
function tagClassForState(state: string | undefined): string {
  switch (state) {
    case "running":
    case "ready":
      return "tag t-run";
    case "intake":
    case "planning":
      return "tag t-plan";
    case "awaiting_approval":
    case "waiting_human":
    case "handoff_ready":
      return "tag t-need";
    case "blocked":
    case "failed":
      return "tag t-block";
    case "under_review":
      return "tag t-review";
    case "done":
      return "tag t-done";
    default:
      return "tag t-plan";
  }
}

/** Pretty-print a queue_state / status value, e.g. "under_review" -> "under review". */
function humanize(value: string | undefined): string {
  if (!value) return "—";
  return value.replace(/_/g, " ");
}

function stringField(row: TaskDashboardRow, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return undefined;
}

/** Best-effort AC coverage extraction. The task-dashboard projection doesn't
 * guarantee these fields; several plausible shapes are checked so the bar
 * renders if any backing data is present, and is omitted otherwise. */
function acCoverage(row: TaskDashboardRow): { covered: number; total: number } | null {
  const direct = row.ac_covered ?? row.acceptance_covered ?? row.ac_pass;
  const total = row.ac_total ?? row.acceptance_total ?? row.ac_count;
  if (typeof direct === "number" && typeof total === "number" && total > 0) {
    return { covered: direct, total };
  }
  const nested = row.acceptance_criteria ?? row.ac;
  if (nested && typeof nested === "object") {
    const n = nested as Record<string, unknown>;
    const c = n.covered ?? n.passed ?? n.met;
    const t = n.total ?? n.count;
    if (typeof c === "number" && typeof t === "number" && t > 0) {
      return { covered: c, total: t };
    }
  }
  return null;
}

function projectLabel(row: TaskDashboardRow): string {
  return (
    stringField(row, "project_label", "project_name", "project") ??
    (typeof row.project_id === "string" ? row.project_id : "unassigned")
  );
}

function providerLabel(row: TaskDashboardRow): string | undefined {
  return stringField(row, "provider", "provider_name", "harness");
}

function taskTitle(row: TaskDashboardRow): string {
  return stringField(row, "title", "name") ?? row.id;
}

function formatUpdatedAt(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type ViewMode = "board" | "list";

export default function Dashboard() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskDashboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("board");
  const [projectFilter, setProjectFilter] = useState<string | null>(null);

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

  // Reset the project filter if it no longer matches any loaded project.
  useEffect(() => {
    if (!projectFilter || !tasks) return;
    if (!tasks.some((task) => task.project_id === projectFilter)) {
      setProjectFilter(null);
    }
  }, [tasks, projectFilter]);

  const projectIds = useMemo(() => {
    if (!tasks) return [];
    const ids = new Set<string>();
    for (const task of tasks) {
      if (typeof task.project_id === "string" && task.project_id) ids.add(task.project_id);
    }
    return Array.from(ids).sort();
  }, [tasks]);

  const visibleTasks = useMemo(() => {
    if (!tasks) return [];
    if (!projectFilter) return tasks;
    return tasks.filter((task) => task.project_id === projectFilter);
  }, [tasks, projectFilter]);

  const lanes = useMemo(() => {
    const grouped = new Map<LaneKey, TaskDashboardRow[]>(LANES.map((lane) => [lane.key, []]));
    for (const task of visibleTasks) {
      grouped.get(laneForRow(task))?.push(task);
    }
    return grouped;
  }, [visibleTasks]);

  const offline = serviceStatus === "offline";
  const degraded = serviceStatus === "degraded";

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Dashboard</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} ·{" "}
              {projectFilter ?? "all projects"} ·{" "}
              {offline ? "offline" : degraded ? "degraded service projection" : "live service projection"}
            </p>
          </div>
          <div className="grow" />
          <div className="seg">
            <button className={viewMode === "board" ? "on" : ""} onClick={() => setViewMode("board")}>
              Board
            </button>
            <button className={viewMode === "list" ? "on" : ""} onClick={() => setViewMode("list")}>
              List
            </button>
          </div>
          <button className="btn primary" type="button">
            ＋ New project
          </button>
        </div>
      </div>

      {offline && (
        <div className="banner offline">
          ⚠ Service is offline — showing the last known dashboard data, if any.
        </div>
      )}
      {!offline && degraded && (
        <div className="banner warn">⚠ Service is degraded — dashboard data may be stale.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2 dash-empty">
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspaces found yet."}
        </div>
      )}

      {currentWorkspaceId && (
        <>
          <div className="dash-chips">
            <span
              className={`dash-chip ${projectFilter === null ? "on" : ""}`}
              onClick={() => setProjectFilter(null)}
            >
              All projects
            </span>
            {projectIds.map((projectId) => (
              <span
                key={projectId}
                className={`dash-chip ${projectFilter === projectId ? "on" : ""}`}
                onClick={() => setProjectFilter(projectId)}
              >
                {projectId}
              </span>
            ))}
          </div>

          {loading && <div className="card2 dash-empty">Loading task dashboard…</div>}

          {!loading && error && (
            <div className="banner offline">⚠ Failed to load task dashboard: {error}</div>
          )}

          {!loading && !error && tasks && tasks.length === 0 && (
            <div className="card2 dash-empty">No tasks yet for this workspace.</div>
          )}

          {!loading && !error && tasks && tasks.length > 0 && visibleTasks.length === 0 && (
            <div className="card2 dash-empty">No tasks for this project filter.</div>
          )}

          {!loading && !error && tasks && visibleTasks.length > 0 && viewMode === "board" && (
            <div className="board">
              {LANES.map((lane) => {
                const laneTasks = lanes.get(lane.key) ?? [];
                return (
                  <div className="lane" key={lane.key}>
                    <div className="lh">
                      <span className="ic" style={{ background: lane.color }} />
                      <b>{lane.label}</b>
                      <span className="ct">{laneTasks.length}</span>
                    </div>
                    <div className="lb">
                      {laneTasks.length === 0 && <div className="lb-empty">No tasks</div>}
                      {laneTasks.map((task) => {
                        const queueState = stringField(task, "queue_state");
                        const provider = providerLabel(task);
                        const ac = acCoverage(task);
                        return (
                          <button
                            key={task.id}
                            className="kc"
                            type="button"
                            onClick={() => navigate(`/task/${task.id}`)}
                          >
                            <div className="pj">{projectLabel(task)}</div>
                            <div className="tt">{taskTitle(task)}</div>
                            <div className="r">
                              <span className={tagClassForState(queueState)}>
                                <span className="d" />
                                {humanize(queueState ?? stringField(task, "status"))}
                              </span>
                              {stringField(task, "phase") && (
                                <span className="tag ph">{(stringField(task, "phase") ?? "").toUpperCase()}</span>
                              )}
                            </div>
                            <div className="mt">
                              {provider ?? "—"}
                              {ac && (
                                <span className="ac">
                                  AC {ac.covered}/{ac.total}
                                  <span className="bar">
                                    <i
                                      style={{
                                        width: `${ac.total > 0 ? Math.round((ac.covered / ac.total) * 100) : 0}%`,
                                      }}
                                    />
                                  </span>
                                </span>
                              )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {!loading && !error && tasks && visibleTasks.length > 0 && viewMode === "list" && (
            <div className="card2 dash-list">
              <table>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Project</th>
                    <th>Lane</th>
                    <th>Status</th>
                    <th>Phase</th>
                    <th>Provider</th>
                    <th>AC coverage</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleTasks.map((task) => {
                    const lane = LANES.find((l) => l.key === laneForRow(task));
                    const queueState = stringField(task, "queue_state");
                    const ac = acCoverage(task);
                    return (
                      <tr key={task.id} onClick={() => navigate(`/task/${task.id}`)}>
                        <td>{taskTitle(task)}</td>
                        <td>{projectLabel(task)}</td>
                        <td>{lane?.label ?? "—"}</td>
                        <td>
                          <span className={tagClassForState(queueState)}>
                            <span className="d" />
                            {humanize(queueState ?? stringField(task, "status"))}
                          </span>
                        </td>
                        <td>{stringField(task, "phase") ?? "—"}</td>
                        <td>{providerLabel(task) ?? "—"}</td>
                        <td>
                          {ac ? (
                            <span className="ac-inline">
                              {ac.covered}/{ac.total}
                              <span className="bar">
                                <i
                                  style={{
                                    width: `${ac.total > 0 ? Math.round((ac.covered / ac.total) * 100) : 0}%`,
                                  }}
                                />
                              </span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{formatUpdatedAt(task.updated_at) ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
