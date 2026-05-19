import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getSarathiApiConfig,
  getWorkspaceOperationalViews,
  listProviders,
  testProviderConnection,
  type OperationalViewsSnapshot,
  type ProviderHealthRecord,
} from "../apiClient";
import { Card, Pill } from "../components/ui";
import { providers as mockProviders } from "../mockData";

interface Props {
  workspaceId?: string | null;
  liveTick?: number;
  setRoute?: (r: string) => void;
}

function healthDot(health: string): React.CSSProperties {
  const colors: Record<string, string> = {
    online: "var(--status-green-fg)",
    offline: "var(--status-red-fg)",
    rate_limited: "var(--status-amber-fg)",
    configured_by_user: "var(--status-blue-fg)",
    degraded: "var(--status-amber-fg)",
  };
  return {
    display: "inline-block",
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: colors[health] ?? "var(--faint)",
    flexShrink: 0,
    verticalAlign: "middle",
  };
}

function healthTone(health: string): string {
  if (health === "online") return "healthy";
  if (health === "offline") return "blocked";
  if (health === "rate_limited") return "warning";
  if (health === "configured_by_user") return "active";
  if (health === "degraded") return "warning";
  return "draft";
}

function transportTone(posture?: string): string {
  if (posture === "builtin") return "healthy";
  if (posture === "sdk" || posture === "api") return "active";
  if (posture === "cli_fallback") return "warning";
  return "draft";
}

function transportLabel(provider: ProviderHealthRecord): string {
  const posture = provider.transport_posture;
  if (posture === "builtin") return "Built in";
  if (posture === "sdk") return "SDK";
  if (posture === "api") return "API";
  if (posture === "cli_fallback") return "CLI fallback";
  if (provider.transport_kind) return provider.transport_kind;
  return "Unknown transport";
}

function authLabel(auth: string): string {
  if (auth === "connected") return "Connected";
  if (auth === "missing") return "Missing";
  if (auth === "not_required") return "Not required";
  if (auth === "workspace_setting") return "Workspace setting";
  if (auth === "github_auth") return "GitHub OAuth";
  return auth;
}

function adaptMock(p: typeof mockProviders[0]): ProviderHealthRecord {
  const isLocal = p.id === "local" || p.type === "local" || p.type === "deterministic";
  return {
    id: p.id,
    name: p.name,
    provider_type: p.type,
    transport_kind: isLocal ? "deterministic" : "cli",
    transport_posture: isLocal ? "builtin" : "cli_fallback",
    health: p.health,
    auth: p.auth,
    path: p.path,
    capabilities: p.capabilities,
    degraded_reason: isLocal ? null : "Demo provider is shown through the CLI fallback posture.",
    last_checked_at: null,
    last_error: null,
  };
}

function byStatus(snapshot: OperationalViewsSnapshot | null, key: string): number {
  return snapshot?.usage.dispatches.by_status[key] ?? 0;
}

function activeDispatchCount(snapshot: OperationalViewsSnapshot | null): number {
  return ["queued", "pending", "running", "in_progress"].reduce((total, key) => total + byStatus(snapshot, key), 0);
}

function failedDispatchCount(snapshot: OperationalViewsSnapshot | null): number {
  return ["failed", "error", "cancelled", "blocked"].reduce((total, key) => total + byStatus(snapshot, key), 0);
}

function budgetSummary(snapshot: OperationalViewsSnapshot | null): { label: string; tone: string } {
  const budget = snapshot?.usage.budget;
  if (!budget) {
    return { label: "No usage captured yet", tone: "draft" };
  }
  const remaining = budget.budget_remaining == null ? "unknown remaining" : `${budget.budget_remaining} left`;
  return {
    label: `${budget.total_tokens} tokens used, ${remaining}`,
    tone: budget.budget_state,
  };
}

function healthCounts(providers: ProviderHealthRecord[]) {
  const counts: Record<string, number> = {};
  for (const provider of providers) {
    counts[provider.health] = (counts[provider.health] ?? 0) + 1;
  }
  return counts;
}

export default function Agents({ workspaceId, liveTick }: Props) {
  const [providers, setProviders] = useState<ProviderHealthRecord[]>([]);
  const [operations, setOperations] = useState<OperationalViewsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("Loading provider posture.");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState(false);

  const load = useCallback(async () => {
    const config = getSarathiApiConfig();
    if (!config) {
      setProviders(mockProviders.map(adaptMock));
      setOperations(null);
      setStatus("Demo provider posture. Connect the local service for persisted health and dispatch telemetry.");
      setLoading(false);
      return;
    }
    if (!workspaceId) {
      setProviders([]);
      setOperations(null);
      setStatus("Select a workspace to inspect provider health and dispatch posture.");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [nextProviders, nextOperations] = await Promise.all([
        listProviders(workspaceId),
        getWorkspaceOperationalViews(workspaceId),
      ]);
      setProviders(nextProviders);
      setOperations(nextOperations);
      setStatus(
        `${nextProviders.length} providers, ${activeDispatchCount(nextOperations)} active dispatches, ${nextOperations.usage.events.total} lifecycle events loaded.`,
      );
    } catch {
      setProviders(mockProviders.map(adaptMock));
      setOperations(null);
      setStatus("Provider posture load failed. Showing fallback provider inventory.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load, liveTick]);

  async function handleTest(provider: ProviderHealthRecord) {
    if (!workspaceId) return;
    setTestingId(provider.id);
    try {
      const updated = await testProviderConnection(workspaceId, provider.id, {
        path: provider.path,
        auth: provider.auth,
      });
      setProviders((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
    } finally {
      setTestingId(null);
    }
  }

  async function handleTestAll() {
    if (!workspaceId || providers.length === 0) return;
    setTestingAll(true);
    try {
      const results = await Promise.allSettled(
        providers.map((provider) =>
          testProviderConnection(workspaceId, provider.id, {
            path: provider.path,
            auth: provider.auth,
          }),
        ),
      );
      setProviders((current) =>
        current.map((provider, index) => {
          const result = results[index];
          if (result?.status === "fulfilled") {
            return result.value;
          }
          return provider;
        }),
      );
    } finally {
      setTestingAll(false);
    }
  }

  const providerHealth = useMemo(() => healthCounts(providers), [providers]);
  const budget = useMemo(() => budgetSummary(operations), [operations]);

  return (
    <div style={{ padding: "24px 28px", display: "grid", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h1 style={{ margin: 0 }}>Agents</h1>
          <p style={{ margin: "6px 0 0", fontSize: "0.83rem", color: "var(--muted)" }}>
            Provider readiness, dispatch posture, and operational confidence for the current workspace.
          </p>
        </div>
        <button
          style={{ height: 32, padding: "0 12px", fontSize: "0.78rem" }}
          onClick={() => void handleTestAll()}
          disabled={testingAll || !workspaceId || providers.length === 0}
        >
          {testingAll ? "Testing..." : "Test all providers"}
        </button>
      </div>

      <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--faint)" }}>{status}</p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        <Card style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.73rem", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Ready now
            </span>
            <Pill tone="healthy">{providerHealth.online ?? 0}</Pill>
          </div>
          <p style={{ margin: "10px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
            Providers online and available for dispatch.
          </p>
        </Card>
        <Card style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.73rem", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Attention
            </span>
            <Pill tone={(providerHealth.offline ?? 0) > 0 || (providerHealth.degraded ?? 0) > 0 ? "warning" : "healthy"}>
              {(providerHealth.offline ?? 0) + (providerHealth.degraded ?? 0) + (providerHealth.rate_limited ?? 0)}
            </Pill>
          </div>
          <p style={{ margin: "10px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
            Offline, degraded, or rate-limited providers needing review.
          </p>
        </Card>
        <Card style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.73rem", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Dispatches
            </span>
            <Pill tone={activeDispatchCount(operations) > 0 ? "active" : "draft"}>{activeDispatchCount(operations)}</Pill>
          </div>
          <p style={{ margin: "10px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
            {failedDispatchCount(operations)} failed or blocked, {operations?.usage.dispatches.total ?? 0} total observed.
          </p>
        </Card>
        <Card style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.73rem", letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Budget posture
            </span>
            <Pill tone={budget.tone}>{operations?.usage.budget?.budget_state ?? "draft"}</Pill>
          </div>
          <p style={{ margin: "10px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
            {budget.label}
          </p>
        </Card>
      </div>

      <Card style={{ padding: 16 }}>
        <div className="panel-title" style={{ marginBottom: 10 }}>
          <h2 style={{ fontSize: "0.92rem" }}>Dispatch posture</h2>
          <Pill tone={activeDispatchCount(operations) > 0 ? "active" : "draft"}>
            {activeDispatchCount(operations) > 0 ? "Live" : "Idle"}
          </Pill>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
          }}
        >
          {[
            { label: "Queued", value: byStatus(operations, "queued") + byStatus(operations, "pending") },
            { label: "Running", value: byStatus(operations, "running") + byStatus(operations, "in_progress") },
            { label: "Completed", value: byStatus(operations, "completed") + byStatus(operations, "succeeded") },
            { label: "Failed", value: failedDispatchCount(operations) },
          ].map((item) => (
            <div
              key={item.label}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-md)",
                padding: "10px 12px",
                background: "var(--surface)",
              }}
            >
              <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--muted)" }}>
                {item.label}
              </div>
              <div style={{ marginTop: 6, fontSize: "1.2rem", fontWeight: 600 }}>{item.value}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            padding: "12px 16px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div>
            <strong>Provider inventory</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              Health, transport posture, auth posture, CLI path, and execution capabilities.
            </p>
          </div>
          {providers.length > 0 ? <Pill tone="draft">{providers.length} total</Pill> : null}
        </div>

        {loading ? (
          <div className="loading-overlay">
            <div className="spinner" />
            Loading providers...
          </div>
        ) : providers.length === 0 ? (
          <div className="empty-state" style={{ padding: "36px 18px" }}>
            <p style={{ color: "var(--muted)", fontSize: "0.84rem" }}>No workspace provider posture available.</p>
            <p style={{ fontSize: "0.76rem", color: "var(--faint)", marginTop: 4 }}>
              Select a workspace to test CLI-backed integrations and inspect dispatch readiness.
            </p>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 0 }}>
            {providers.map((provider) => (
              <div
                key={provider.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 0.8fr) minmax(0, 1fr) auto",
                  gap: 14,
                  alignItems: "start",
                  padding: "14px 16px",
                  borderTop: "1px solid var(--border)",
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={healthDot(provider.health)} />
                    <strong>{provider.name}</strong>
                    <Pill tone={healthTone(provider.health)}>{provider.health}</Pill>
                    <Pill tone={transportTone(provider.transport_posture)}>{transportLabel(provider)}</Pill>
                    <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{provider.provider_type}</span>
                  </div>
                  <p style={{ margin: "8px 0 0", fontSize: "0.77rem", color: "var(--muted)" }}>
                    {provider.path || "CLI path not configured"}
                  </p>
                  {provider.degraded_reason ? (
                    <p style={{ margin: "8px 0 0", fontSize: "0.76rem", color: "var(--status-amber-fg)" }}>
                      {provider.degraded_reason}
                    </p>
                  ) : null}
                  {provider.last_error ? (
                    <p style={{ margin: "8px 0 0", fontSize: "0.76rem", color: "var(--status-red-fg)" }}>
                      {provider.last_error}
                    </p>
                  ) : null}
                </div>

                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--muted)" }}>
                    Auth
                  </div>
                  <p style={{ margin: "8px 0 0", fontSize: "0.8rem" }}>{authLabel(provider.auth)}</p>
                  {provider.last_checked_at ? (
                    <p style={{ margin: "6px 0 0", fontSize: "0.74rem", color: "var(--faint)" }}>
                      Checked {new Date(provider.last_checked_at).toLocaleString()}
                    </p>
                  ) : null}
                </div>

                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--muted)" }}>
                    Capabilities
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                    {provider.capabilities.length > 0 ? provider.capabilities.map((capability) => (
                      <span
                        key={capability}
                        style={{
                          fontSize: "0.68rem",
                          padding: "2px 7px",
                          borderRadius: 999,
                          background: "var(--surface)",
                          color: "var(--muted)",
                          border: "1px solid var(--border)",
                        }}
                      >
                        {capability}
                      </span>
                    )) : (
                      <span style={{ fontSize: "0.76rem", color: "var(--faint)" }}>No capability metadata</span>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button
                    style={{ height: 30, padding: "0 12px", fontSize: "0.76rem" }}
                    disabled={testingId === provider.id || !workspaceId}
                    onClick={() => void handleTest(provider)}
                  >
                    {testingId === provider.id ? "Testing..." : "Test"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
