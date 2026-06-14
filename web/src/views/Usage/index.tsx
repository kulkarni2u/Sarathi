import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { UsageStatsData, UsageStatsTask } from "../../api/types";
import "./Usage.css";

/**
 * Usage Stats — HarnessOutcome-derived quality signals (test pass rate,
 * blast radius, tokens, policy proposals) plus a per-task breakdown.
 * Route: /usage
 *
 * Data source: GET /workspaces/{id}/usage-stats (api.getUsageStats), backed
 * by `src.service.usage_stats.build_usage_stats`. Fields may be `null` when
 * a signal hasn't been measured yet (e.g. no review runs recorded); those
 * are rendered as "—" / "Not yet available" rather than fabricated.
 */

const NOT_AVAILABLE = "Not yet available";

export default function Usage() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [data, setData] = useState<UsageStatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
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
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentWorkspaceId]);

  const tasks = useMemo<UsageStatsTask[]>(() => data?.tasks ?? [], [data]);

  const offline = serviceStatus === "offline";

  return (
    <div>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Usage Stats</h1>
            <p>
              Measured quality signals from workspace operations
              {currentWorkspace?.name ? ` · ${currentWorkspace.name}` : ""}. Signals show "—" until
              enough activity has been recorded to measure them.
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
              label="Test pass rate"
              value={formatPercent(data?.test_pass_rate ?? null)}
              delta={data?.test_pass_rate == null ? NOT_AVAILABLE : undefined}
              deltaTone="muted"
            />
            <StatCard
              label="Avg blast radius"
              value={formatRatio(data?.avg_blast_radius ?? null)}
              delta={data?.avg_blast_radius == null ? NOT_AVAILABLE : undefined}
              deltaTone="muted"
            />
            <StatCard
              label="Total tokens"
              value={formatTokens(data?.total_tokens ?? null)}
              delta={data?.total_tokens == null ? NOT_AVAILABLE : undefined}
              deltaTone="muted"
            />
            <StatCard
              label="Policy proposals"
              value={formatProposals(data?.proposal_counts ?? null)}
              delta={proposalsDelta(data?.proposal_counts ?? null)}
              deltaTone={data?.proposal_counts ? "up" : "muted"}
            />
            <StatCard
              label="Task count"
              value={data ? String(data.task_count) : "—"}
              delta={data && data.task_count === 0 ? "No tasks yet" : undefined}
              deltaTone="muted"
            />
          </div>

          <div className="card2 usage-card">
            <div className="usage-card-head">
              <b>Recent task outcomes</b>
              <span className="usage-note usage-card-head">
                per-task test pass, blast radius, tokens, and latency from harness outcomes
              </span>
            </div>
            {tasks.length === 0 ? (
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
                  {tasks.map((task) => (
                    <tr key={task.task_id}>
                      <td>{task.title || task.task_id}</td>
                      <td>{task.task_class ?? "—"}</td>
                      <td>{task.agent ?? "—"}</td>
                      <td className={`usage-num ${task.pass === false ? "usage-fail" : ""}`}>
                        {formatPass(task.pass)}
                      </td>
                      <td className="usage-num">{formatRatio(task.blast_radius)}</td>
                      <td className="usage-num">{formatTokens(task.tokens)}</td>
                      <td className="usage-num">{formatLatency(task.latency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
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
// Formatting helpers
// ---------------------------------------------------------------------

/** Format a 0..1 fraction as a percentage (e.g. 0.875 -> "87.5%"). */
function formatPercent(value: number | null): string {
  if (typeof value !== "number") return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** Format a 0..1 ratio (e.g. blast radius) with two decimal places. */
function formatRatio(value: number | null | undefined): string {
  if (typeof value !== "number") return "—";
  return value.toFixed(2);
}

function formatTokens(total: number | null | undefined): string {
  if (typeof total !== "number") return "—";
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(2)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

function formatPass(pass: boolean | null | undefined): string {
  if (pass === true) return "Pass";
  if (pass === false) return "Fail";
  return "—";
}

/** Format a latency in milliseconds as a human-friendly duration. */
function formatLatency(ms: number | null | undefined): string {
  if (typeof ms !== "number") return "—";
  if (ms >= 3_600_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function formatProposals(counts: UsageStatsData["proposal_counts"] | null): string {
  if (!counts) return "—";
  return String(counts.pending);
}

function proposalsDelta(counts: UsageStatsData["proposal_counts"] | null): string {
  if (!counts) return NOT_AVAILABLE;
  return `${counts.accepted} accepted · ${counts.rejected} rejected`;
}
