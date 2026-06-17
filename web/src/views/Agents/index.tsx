import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { AnyRecord, OperationalViewsData, ProviderHealth } from "../../api/types";
import "./Agents.css";

/**
 * Agents — provider runtime, transport posture, and Sarathi roles.
 * Route: /agents
 *
 * Data sources:
 *  - GET /providers?workspace_id=... (api.getProviders) for provider
 *    runtime/health/transport posture.
 *  - GET /workspaces/{id}/operational-views (api.getWorkspaceOperationalViews)
 *    as a best-effort source of recent dispatch activity per provider
 *    (`history` events of type "subtask.dispatched").
 *
 * The "Sarathi roles" card is illustrative/static, matching the mockup's
 * role → phase mapping (Disha → PLAN, Nirman → BUILD, Pariksha →
 * VERIFY/REVIEW, Smriti → LEARN).
 */

const SARATHI_ROLES: Array<{ role: string; purpose: string; phases: string }> = [
  { role: "Disha", purpose: "planner", phases: "PLAN / PLANNING_ADVISOR" },
  { role: "Nirman", purpose: "builder", phases: "BUILD" },
  { role: "Pariksha", purpose: "verifier", phases: "VERIFY / REVIEW" },
  { role: "Smriti", purpose: "learner", phases: "LEARN" },
];

export default function Agents() {
  const { currentWorkspaceId, serviceStatus } = useWorkspace();
  const [providers, setProviders] = useState<ProviderHealth[] | null>(null);
  const [views, setViews] = useState<OperationalViewsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getProviders(currentWorkspaceId ?? undefined, controller.signal);
        if (cancelled) return;
        setProviders(data.providers ?? []);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setProviders(null);
      } finally {
        if (!cancelled) setLoading(false);
      }

      if (currentWorkspaceId) {
        try {
          const data = await api.getWorkspaceOperationalViews(currentWorkspaceId, controller.signal);
          if (!cancelled) setViews(data);
        } catch {
          if (!cancelled) setViews(null);
        }
      } else {
        setViews(null);
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentWorkspaceId]);

  const dispatchCounts = useMemo(() => recentDispatchCounts(views), [views]);

  const offline = serviceStatus === "offline";

  return (
    <div>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Agents</h1>
            <p>Provider runtime, transport posture, and Sarathi roles</p>
          </div>
        </div>
      </div>

      {offline && (
        <div className="banner offline">
          Service is offline — provider runtime status can't be loaded right now.
        </div>
      )}

      {!offline && error && (
        <div className="banner warn">Couldn't load providers ({error.message}).</div>
      )}

      {loading ? (
        <div className="card2 agt-sect">
          <div className="agt-loading">Loading providers…</div>
        </div>
      ) : !providers || providers.length === 0 ? (
        <div className="card2 agt-sect">
          <div className="agt-empty">No providers configured for this workspace yet.</div>
        </div>
      ) : (
        <div className="agt-grid">
          {providers.map((provider) => (
            <ProviderCard
              key={String(provider["id"] ?? provider.name)}
              provider={provider}
              recentDispatches={dispatchCounts.get(String(provider["id"] ?? provider.name ?? "")) ?? 0}
            />
          ))}
        </div>
      )}

      <div className="card2 agt-sect">
        <h3>Sarathi roles</h3>
        {SARATHI_ROLES.map((entry) => (
          <div className="kvl" key={entry.role}>
            <span>
              {entry.role} · {entry.purpose}
            </span>
            <b>{entry.phases}</b>
          </div>
        ))}
        <p className="agt-note">
          Illustrative mapping of Sarathi's internal agent roles to workflow phases.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Provider card
// ---------------------------------------------------------------------

function ProviderCard({
  provider,
  recentDispatches,
}: {
  provider: ProviderHealth;
  recentDispatches: number;
}) {
  const name = String(provider.name ?? provider["id"] ?? "Unknown");
  const initials = name.slice(0, 2).toUpperCase();
  const health = String(provider.health ?? provider.status ?? "unknown");
  const transportKind = optionalString(provider["transport_kind"]);
  const transportPosture = optionalString(provider["transport_posture"]);
  const authStatus = optionalString(provider["auth"]);
  const lastChecked = optionalString(provider["last_checked_at"]);
  const lastError = optionalString(provider["last_error"]);
  const degradedReason = optionalString(provider["degraded_reason"]);
  const path = optionalString(provider["path"]);
  const model = optionalString(provider["model"]);

  const subtitle = [transportPosture ? humanizeToken(transportPosture) : null, authStatus]
    .filter(Boolean)
    .join(" · ");

  const transportLabel = [transportKind ? humanizeToken(transportKind) : null, path || model]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="card2 agt-card">
      <div className="agt-head">
        <div className="agt-pic">{initials}</div>
        <div className="agt-id">
          <b>{name}</b>
          <span>{subtitle || "—"}</span>
        </div>
        <HealthBadge health={health} />
      </div>
      <div className="kvl">
        <span>Transport</span>
        <b>{transportLabel || "—"}</b>
      </div>
      <div className="kvl">
        <span>Active / recent dispatches</span>
        <b>{recentDispatches}</b>
      </div>
      <div className="kvl">
        <span>Last checked</span>
        <b>{lastChecked ? formatRelative(lastChecked) : "—"}</b>
      </div>
      {(lastError || degradedReason) && (
        <div className="kvl">
          <span>Last error</span>
          <b className={lastError ? "agt-error" : ""}>{lastError || degradedReason}</b>
        </div>
      )}
    </div>
  );
}

function HealthBadge({ health }: { health: string }) {
  const normalized = health.toLowerCase();
  let cls = "of";
  let label = health;

  if (normalized === "online" || normalized === "ready" || normalized === "ok") {
    cls = "ok";
    label = "ready";
  } else if (normalized === "configured_by_user" || normalized === "fallback" || normalized === "degraded") {
    cls = "wn";
    label = normalized === "configured_by_user" ? "configured" : normalized;
  } else if (normalized === "rate_limited" || normalized === "offline" || normalized === "error") {
    cls = "err";
    label = normalized === "rate_limited" ? "rate limited" : normalized;
  } else if (normalized === "not_configured" || normalized === "off" || normalized === "unknown") {
    cls = "of";
    label = normalized === "not_configured" ? "off" : normalized;
  }

  return (
    <span className={`st ${cls}`}>
      <span className="d" />
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function humanizeToken(value: string): string {
  return value.replace(/_/g, " ");
}

function formatRelative(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

/**
 * Count recent "subtask.dispatched" lifecycle events per provider, from the
 * operational-views `history` array. Best-effort: returns an empty map if
 * the projection or its history isn't available.
 */
function recentDispatchCounts(views: OperationalViewsData | null): Map<string, number> {
  const counts = new Map<string, number>();
  if (!views) return counts;
  const history = views["history"];
  if (!Array.isArray(history)) return counts;

  for (const event of history as AnyRecord[]) {
    if (event["event_type"] !== "subtask.dispatched") continue;
    const payload = (event["payload"] as AnyRecord | undefined) ?? {};
    const provider = payload["provider"];
    if (typeof provider !== "string") continue;
    counts.set(provider, (counts.get(provider) ?? 0) + 1);
  }

  return counts;
}
