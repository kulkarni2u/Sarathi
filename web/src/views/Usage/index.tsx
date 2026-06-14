import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { AnyRecord, DogfoodAcceptanceData, TaskDashboardRow } from "../../api/types";
import "./Usage.css";

/**
 * Usage Stats — HarnessOutcome-style quality signals (pass rate, blast
 * radius, latency, tokens, policy proposals).
 * Route: /usage
 *
 * Primary data source: GET /workspaces/{id}/dogfood-acceptance
 * (api.getUsageStats), which wraps the operational-views `usage` projection
 * plus dogfood acceptance `checks`.
 *
 * NOTE: there is no dedicated HarnessOutcome endpoint yet (see the TODO on
 * `getUsageStats` in src/api/client.ts), so several of the mockup's stat
 * cards (blast radius, latency) have no backing data. Those are rendered
 * with an explicit "not yet available" placeholder rather than invented
 * numbers. "Policy proposals" is supplemented with a best-effort fetch of
 * GET /workspaces/{id}/proposals.
 */

interface ProposalsSummary {
  pendingCount: number;
  acceptedCount: number;
}

interface OutcomeRow {
  id: string;
  task: string;
  taskClass: string;
  agent: string;
  passLabel: string;
  passTone: "ok" | "fail" | "none";
}

export default function Usage() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [data, setData] = useState<DogfoodAcceptanceData | null>(null);
  const [tasks, setTasks] = useState<TaskDashboardRow[]>([]);
  const [proposals, setProposals] = useState<ProposalsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
      setTasks([]);
      setProposals(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const stats = await api.getUsageStats(currentWorkspaceId!, controller.signal);
        if (cancelled) return;
        setData(stats);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }

      // Best-effort supplements — failures here shouldn't block the page.
      try {
        const dashboard = await api.getTaskDashboard(currentWorkspaceId!, undefined, controller.signal);
        if (!cancelled) setTasks(dashboard.tasks ?? []);
      } catch {
        if (!cancelled) setTasks([]);
      }

      try {
        const proposalsData = await api.getProposals(currentWorkspaceId!, controller.signal);
        if (cancelled) return;
        const list = asArray(proposalsData["proposals"]) ?? [];
        const history = asArray(proposalsData["reviewed_history"]) ?? [];
        const accepted = history.filter((item) => item["status"] === "accepted").length;
        setProposals({ pendingCount: list.length, acceptedCount: accepted });
      } catch {
        if (!cancelled) setProposals(null);
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentWorkspaceId]);

  const usage = useMemo(() => {
    const operations = data ? (data["operations"] as AnyRecord | undefined) : undefined;
    return operations ? (operations["usage"] as AnyRecord | undefined) : undefined;
  }, [data]);

  const checks = useMemo(() => (data ? asArray(data["checks"]) ?? [] : []), [data]);

  const outcomeRows = useMemo(() => buildOutcomeRows(data, tasks), [data, tasks]);

  const offline = serviceStatus === "offline";

  return (
    <div>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Usage Stats</h1>
            <p>
              Measured quality signals from workspace operations
              {currentWorkspace?.name ? ` · ${currentWorkspace.name}` : ""}. Some HarnessOutcome
              signals aren't exposed by the service yet.
            </p>
          </div>
        </div>
      </div>

      {offline && (
        <div className="banner offline">
          Service is offline — usage stats can't be loaded right now.
        </div>
      )}

      {!offline && error && (
        <div className="banner warn">Couldn't load usage stats ({error.message}).</div>
      )}

      {!currentWorkspaceId ? (
        <div className="card2 usage-card">
          <div className="usage-empty">No workspace selected yet.</div>
        </div>
      ) : loading ? (
        <div className="card2 usage-card">
          <div className="usage-loading">Loading usage stats…</div>
        </div>
      ) : (
        <>
          <div className="usage-stats">
            <StatCard
              label="Test / review pass rate"
              value={reviewPassRate(usage)}
              delta={reviewPassRateDelta(usage)}
            />
            <StatCard label="Avg blast radius" value="—" delta="Not yet available" deltaTone="muted" />
            <StatCard label="Median latency" value="—" delta="Not yet available" deltaTone="muted" />
            <StatCard
              label="Tokens (actual)"
              value={formatTokens(usage)}
              delta={budgetDelta(usage)}
            />
            <StatCard
              label="Policy proposals"
              value={proposals ? String(proposals.pendingCount) : "—"}
              delta={
                proposals
                  ? `${proposals.acceptedCount} accepted`
                  : "Proposals endpoint unavailable"
              }
              deltaTone={proposals ? "up" : "muted"}
            />
          </div>

          <div className="card2 usage-card">
            <div className="usage-card-head">
              <b>Recent task outcomes</b>
              <span className="usage-note usage-card-head">
                derived from operational-views review loops · per-task blast radius, tokens, and
                latency are not yet exposed
              </span>
            </div>
            {outcomeRows.length === 0 ? (
              <div className="usage-empty">No completed task outcomes recorded yet.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Class</th>
                    <th>Agent</th>
                    <th>Pass</th>
                    <th>Blast</th>
                    <th>Tokens</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {outcomeRows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.task}</td>
                      <td>{row.taskClass}</td>
                      <td>{row.agent}</td>
                      <td className={`usage-num ${row.passTone === "fail" ? "usage-fail" : ""}`}>
                        {row.passLabel}
                      </td>
                      <td className="usage-num usage-placeholder-cell">—</td>
                      <td className="usage-num usage-placeholder-cell">—</td>
                      <td className="usage-num usage-placeholder-cell">—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {data && (
            <div className="card2 usage-card" style={{ marginTop: 16 }}>
              <div className="usage-card-head">
                <b>Dogfood acceptance checks</b>
                <span className="usage-note usage-card-head">
                  status: {String(data["status"] ?? "unknown")}
                </span>
              </div>
              {checks.length === 0 ? (
                <div className="usage-empty">No acceptance checks recorded.</div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.map((check) => (
                      <tr key={String(check["id"] ?? check["label"])}>
                        <td>{String(check["label"] ?? check["id"] ?? "—")}</td>
                        <td className={check["status"] === "passed" ? "" : "usage-fail"}>
                          {String(check["status"] ?? "—")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------

function StatCard({
  label,
  value,
  delta,
  deltaTone = "up",
}: {
  label: string;
  value: string;
  delta?: string;
  deltaTone?: "up" | "down" | "muted";
}) {
  return (
    <div className="card2 usage-stat">
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {delta && <div className={`dl ${deltaTone}`}>{delta}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function asArray(value: unknown): AnyRecord[] | null {
  return Array.isArray(value) ? (value as AnyRecord[]) : null;
}

function asRecord(value: unknown): AnyRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : undefined;
}

function reviewPassRate(usage: AnyRecord | undefined): string {
  const reviews = asRecord(usage?.["reviews"]);
  const byStatus = asRecord(reviews?.["by_status"]);
  const total = typeof reviews?.["total"] === "number" ? (reviews["total"] as number) : 0;
  if (!byStatus || total === 0) return "—";
  const approved = (byStatus["approved"] as number | undefined) ?? 0;
  const passed = (byStatus["passed"] as number | undefined) ?? 0;
  const rate = ((approved + passed) / total) * 100;
  return `${rate.toFixed(1)}%`;
}

function reviewPassRateDelta(usage: AnyRecord | undefined): string {
  const reviews = asRecord(usage?.["reviews"]);
  const total = typeof reviews?.["total"] === "number" ? (reviews["total"] as number) : 0;
  if (total === 0) return "No reviews recorded yet";
  return `${total} review run${total === 1 ? "" : "s"} measured`;
}

function formatTokens(usage: AnyRecord | undefined): string {
  const budget = asRecord(usage?.["budget"]);
  const total = budget?.["total_tokens"];
  if (typeof total !== "number") return "—";
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(2)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

function budgetDelta(usage: AnyRecord | undefined): string {
  const budget = asRecord(usage?.["budget"]);
  if (!budget) return "No dispatch usage recorded yet";
  const state = budget["budget_state"];
  const source = budget["usage_source"];
  const remaining = budget["budget_remaining"];
  const parts: string[] = [];
  if (typeof source === "string") parts.push(`source: ${source}`);
  if (typeof state === "string" && state !== "unknown") parts.push(`budget: ${state}`);
  if (typeof remaining === "number") parts.push(`${formatTokens({ budget: { total_tokens: remaining } })} remaining`);
  return parts.length > 0 ? parts.join(" · ") : "Budget not configured";
}

/**
 * Build "recent task outcomes" rows from operational-views `diagrams`
 * (review_loop kind, for pass/fail signal) joined with task dashboard rows
 * (for title/class/agent labels). Per-task blast radius, tokens, and
 * latency aren't exposed by any current endpoint.
 */
function buildOutcomeRows(data: DogfoodAcceptanceData | null, tasks: TaskDashboardRow[]): OutcomeRow[] {
  if (!data) return [];
  const operations = asRecord(data["operations"]);
  const diagrams = asArray(operations?.["diagrams"]) ?? [];
  const reviewLoops = diagrams.filter((d) => d["kind"] === "review_loop");

  const tasksById = new Map<string, TaskDashboardRow>();
  for (const task of tasks) {
    if (typeof task.id === "string") tasksById.set(task.id, task);
  }

  if (reviewLoops.length > 0) {
    return reviewLoops.map((diagram): OutcomeRow => {
      const taskId = String(diagram["task_id"] ?? "");
      const task = tasksById.get(taskId);
      const nodes = asArray(diagram["nodes"]) ?? [];
      const approved = nodes.filter((n) => n["status"] === "approved" || n["status"] === "passed").length;
      const total = nodes.length;
      const failed = total > 0 && approved < total;
      const title = task?.title ?? String(diagram["title"] ?? "").replace(/^Review loop:\s*/i, "");
      const roles = Array.isArray(task?.["roles"]) ? (task["roles"] as unknown[]) : [];
      const providers = Array.isArray(task?.["providers"]) ? (task["providers"] as unknown[]) : [];
      const passTone: OutcomeRow["passTone"] = total === 0 ? "none" : failed ? "fail" : "ok";
      return {
        id: String(diagram["id"] ?? taskId),
        task: title || taskId || "Untitled task",
        taskClass: roles.length > 0 ? roles.map(String).join("/") : "—",
        agent: providers.length > 0 ? String(providers[0]) : "—",
        passLabel: total > 0 ? `${approved}/${total}` : "—",
        passTone,
      };
    });
  }

  // Fallback: no review loops yet — surface task dashboard rows so the
  // table isn't empty while a workspace is still early in its lifecycle.
  return tasks.slice(0, 10).map((task): OutcomeRow => {
    const roles = Array.isArray(task["roles"]) ? (task["roles"] as unknown[]) : [];
    const providers = Array.isArray(task["providers"]) ? (task["providers"] as unknown[]) : [];
    return {
      id: String(task.id),
      task: task.title ?? String(task.id),
      taskClass: roles.length > 0 ? roles.map(String).join("/") : "—",
      agent: providers.length > 0 ? String(providers[0]) : "—",
      passLabel: String(task["status"] ?? "—"),
      passTone: "none",
    };
  });
}
