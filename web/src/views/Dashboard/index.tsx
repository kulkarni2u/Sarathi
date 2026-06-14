import { useEffect, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import type { TaskDashboardRow } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";

/**
 * Dashboard — minimal M1 implementation.
 *
 * Loads GET /workspaces/{id}/task-dashboard for the active workspace and
 * renders a simple list of tasks. A later worker can replace this with the
 * full kanban board from docs/mockups/sarathi-webui-mockup.html (lanes by
 * status, chips, cards, etc) — the data fetch + loading/error/empty states
 * here are reusable as a starting point.
 */
export default function Dashboard() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [tasks, setTasks] = useState<TaskDashboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Dashboard</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · all projects · live
              service projection
            </p>
          </div>
        </div>
      </div>

      {serviceStatus === "offline" && !currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          No workspace data available while the service is offline.
        </div>
      )}

      {!currentWorkspaceId && serviceStatus !== "offline" && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspaces found yet."}
        </div>
      )}

      {currentWorkspaceId && loading && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          Loading task dashboard…
        </div>
      )}

      {currentWorkspaceId && !loading && error && (
        <div className="banner offline">⚠ Failed to load task dashboard: {error}</div>
      )}

      {currentWorkspaceId && !loading && !error && tasks && tasks.length === 0 && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          No tasks yet for this workspace.
        </div>
      )}

      {currentWorkspaceId && !loading && !error && tasks && tasks.length > 0 && (
        <div className="card2" style={{ overflow: "hidden" }}>
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Phase</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td>{(task.title as string) ?? task.id}</td>
                  <td>{(task.status as string) ?? "—"}</td>
                  <td>{(task.phase as string) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
