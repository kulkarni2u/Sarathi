import { useEffect, useState, useCallback } from "react";
import {
  listProviders,
  testProviderConnection,
  getSarathiApiConfig,
  type ProviderHealthRecord,
} from "../apiClient";
import { providers as mockProviders } from "../mockData";
import { Pill } from "../components/ui";

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

function authLabel(auth: string): string {
  if (auth === "connected") return "conn";
  if (auth === "missing") return "miss";
  if (auth === "not_required") return "n/a";
  if (auth === "workspace_setting") return "ws";
  return auth;
}

// Adapt mock Provider to ProviderHealthRecord shape
function adaptMock(p: typeof mockProviders[0]): ProviderHealthRecord {
  return {
    id: p.id,
    name: p.name,
    provider_type: p.type,
    health: p.health,
    auth: p.auth,
    path: p.path,
    capabilities: p.capabilities,
    last_checked_at: null,
    last_error: null,
  };
}

export default function Agents({ workspaceId, liveTick }: Props) {
  const [providers, setProviders] = useState<ProviderHealthRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState(false);

  const load = useCallback(async () => {
    const config = getSarathiApiConfig();
    if (!config || !workspaceId) {
      setProviders(mockProviders.map(adaptMock));
      setLoading(false);
      return;
    }
    try {
      const data = await listProviders(workspaceId);
      setProviders(data);
    } catch {
      setProviders(mockProviders.map(adaptMock));
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
      const updated = await testProviderConnection(workspaceId, provider.id, provider.path, provider.auth);
      setProviders((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    } catch {
      // ignore
    } finally {
      setTestingId(null);
    }
  }

  async function handleTestAll() {
    if (!workspaceId) return;
    setTestingAll(true);
    try {
      const results = await Promise.allSettled(
        providers.map((p) => testProviderConnection(workspaceId, p.id, p.path, p.auth)),
      );
      setProviders((prev) =>
        prev.map((p, i) => {
          const result = results[i];
          if (result && result.status === "fulfilled") return result.value;
          return p;
        }),
      );
    } finally {
      setTestingAll(false);
    }
  }

  return (
    <div style={{ padding: "24px 28px" }}>
      <h1 style={{ margin: "0 0 20px" }}>Agents</h1>

      {/* ── Providers section ── */}
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          overflow: "hidden",
          marginBottom: 24,
        }}
      >
        {/* Section header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "var(--hover)",
          }}
        >
          <span
            style={{
              fontSize: "0.7rem",
              fontWeight: 600,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--muted)",
            }}
          >
            Providers
          </span>
          <button
            style={{ height: 28, padding: "0 10px", fontSize: "0.78rem" }}
            onClick={() => void handleTestAll()}
            disabled={testingAll || !workspaceId}
          >
            {testingAll ? "Testing…" : "+ Test all"}
          </button>
        </div>

        {loading ? (
          <div className="loading-overlay">
            <div className="spinner" />
            Loading providers…
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Health</th>
                <th>Auth</th>
                <th>Capabilities</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => (
                <>
                  <tr key={p.id} style={{ cursor: "default" }}>
                    <td style={{ fontWeight: 500 }}>{p.name}</td>
                    <td style={{ color: "var(--muted)" }}>{p.provider_type}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={healthDot(p.health)} />
                        <Pill tone={healthTone(p.health)}>{p.health}</Pill>
                      </div>
                    </td>
                    <td>
                      <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                        {authLabel(p.auth)}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {p.capabilities.slice(0, 3).map((cap) => (
                          <span
                            key={cap}
                            style={{
                              fontSize: "0.68rem",
                              padding: "1px 6px",
                              borderRadius: 3,
                              background: "var(--gray-a2)",
                              color: "var(--muted)",
                              border: "1px solid var(--border)",
                            }}
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <button
                        style={{ height: 26, padding: "0 8px", fontSize: "0.75rem" }}
                        disabled={testingId === p.id || !workspaceId}
                        onClick={() => void handleTest(p)}
                      >
                        {testingId === p.id ? "Testing…" : "Test"}
                      </button>
                    </td>
                  </tr>
                  {p.last_error && (
                    <tr key={`${p.id}-err`} style={{ cursor: "default" }}>
                      <td
                        colSpan={6}
                        style={{
                          paddingTop: 0,
                          paddingBottom: 6,
                          fontSize: "0.75rem",
                          color: "var(--status-red-fg)",
                        }}
                      >
                        {p.last_error}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Active dispatches section ── */}
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "var(--hover)",
          }}
        >
          <span
            style={{
              fontSize: "0.7rem",
              fontWeight: 600,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--muted)",
            }}
          >
            Active Dispatches
          </span>
        </div>

        <div className="empty-state" style={{ padding: "28px 16px" }}>
          <p style={{ color: "var(--muted)", fontSize: "0.83rem" }}>No active dispatches.</p>
          <p style={{ fontSize: "0.75rem", color: "var(--faint)", marginTop: 4 }}>
            Running agent tasks will appear here.
          </p>
        </div>
      </div>
    </div>
  );
}
