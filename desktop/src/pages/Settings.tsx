import { useState, useEffect } from "react";
import {
  checkNcpAvailable,
  getSarathiApiConfig,
  getWorkspace,
  getWorkspaceOperationalViews,
  getWorkspacePolicyPack,
  listProviders,
  putWorkspacePolicyPackFile,
  testProviderConnection,
  updateWorkspace,
  type AutoApprovePreferenceRecord,
  type OperationalViewsSnapshot,
  type PolicyPackFile,
  type ProviderConnectionDraft,
  type ProviderHealthRecord,
  type RepositoryActionPreferenceRecord,
  type WorkspaceGovernanceSnapshot,
  type WorkspaceRecord,
} from "../apiClient";
import { Badge } from "@radix-ui/themes";
import { providers, type Provider } from "../mockData";

function Pill({ children, tone = "gray" }: { children: React.ReactNode; tone?: string }) {
  const colorMap: Record<string, "green" | "red" | "gray" | "amber" | "blue"> = {
    online: "green",
    configured_by_user: "blue",
    offline: "red",
    degraded: "amber",
  };
  return (
    <Badge color={colorMap[tone] || "gray"} variant="soft" radius="medium" size="1">
      {children}
    </Badge>
  );
}

function ReadinessCard({
  readyItems,
  pendingItems,
}: {
  readyItems: string[];
  pendingItems: string[];
}) {
  const isReady = pendingItems.length === 0;
  return (
    <div className="readiness-card" style={{
      padding: 20,
      borderRadius: "var(--radius-lg)",
      border: `1px solid ${isReady ? "var(--green)" : "var(--amber)"}`,
      background: isReady ? "rgba(22, 163, 74, 0.04)" : "rgba(217, 119, 6, 0.04)",
      marginBottom: 20,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <span style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: isReady ? "var(--green)" : "var(--amber)",
        }} />
        <strong style={{ fontSize: "1rem" }}>
          {isReady ? "Workspace ready" : "Setup in progress"}
        </strong>
      </div>
      {readyItems.length > 0 && (
        <div style={{ marginBottom: pendingItems.length > 0 ? 8 : 0 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Ready
          </span>
          <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
            {readyItems.map((item) => (
              <span key={item} style={{
                fontSize: "0.78rem",
                color: "var(--green)",
                background: "rgba(22, 163, 74, 0.1)",
                padding: "2px 8px",
                borderRadius: 4,
              }}>
                {item}
              </span>
            ))}
          </div>
        </div>
      )}
      {pendingItems.length > 0 && (
        <div>
          <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Needs attention
          </span>
          <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
            {pendingItems.map((item) => (
              <span key={item} style={{
                fontSize: "0.78rem",
                color: "var(--amber)",
                background: "rgba(217, 119, 6, 0.1)",
                padding: "2px 8px",
                borderRadius: 4,
              }}>
                {item}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="field">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div className="card" style={style}>{children}</div>;
}

const repositoryActionModes = ["no_action", "prepare_patch", "commit", "draft_pr", "ready_pr"] as const;

const defaultRepositoryActionPreference: RepositoryActionPreferenceRecord = {
  scope: "default",
  mode: "no_action",
  allowed_modes: [...repositoryActionModes],
};

function normalizeRepositoryActionPreference(
  preference?: WorkspaceRecord["metadata"]["repository_action_preference"] | null,
): RepositoryActionPreferenceRecord {
  if (!preference || !repositoryActionModes.includes(preference.mode as typeof repositoryActionModes[number])) {
    return defaultRepositoryActionPreference;
  }
  return {
    scope: preference.scope ?? "workspace",
    mode: preference.mode,
    allowed_modes: [...repositoryActionModes],
    ...(typeof preference.source === "string" ? { source: preference.source } : {}),
  };
}

function repositoryActionModeLabel(mode: RepositoryActionPreferenceRecord["mode"]): string {
  switch (mode) {
    case "prepare_patch":
      return "Prepare patch";
    case "commit":
      return "Commit (opt-in)";
    case "draft_pr":
      return "Draft PR (opt-in)";
    case "ready_pr":
      return "Ready PR (opt-in)";
    default:
      return "No action (default)";
  }
}

const autoApproveModes = ["manual_only", "below_threshold"] as const;

const defaultAutoApprovePreference: AutoApprovePreferenceRecord = {
  scope: "default",
  mode: "manual_only",
  allowed_modes: [...autoApproveModes],
};

function normalizeAutoApprovePreference(
  preference?: WorkspaceRecord["metadata"]["auto_approve_preference"] | null,
): AutoApprovePreferenceRecord {
  if (!preference || !autoApproveModes.includes(preference.mode as typeof autoApproveModes[number])) {
    return defaultAutoApprovePreference;
  }
  return {
    scope: preference.scope ?? "workspace",
    mode: preference.mode,
    allowed_modes: [...autoApproveModes],
    ...(preference.threshold ? { threshold: preference.threshold } : {}),
    ...(typeof preference.source === "string" ? { source: preference.source } : {}),
  };
}

function autoApproveModeLabel(mode: AutoApprovePreferenceRecord["mode"]): string {
  switch (mode) {
    case "below_threshold":
      return "Auto-approve low complexity";
    default:
      return "Manual approval (default)";
  }
}

interface SettingsProps {
  workspaceId?: string | null;
}

function defaultProviderDraft(provider: ProviderHealthRecord): ProviderConnectionDraft & { api_key_configured?: boolean } {
  return {
    path: provider.path,
    auth: provider.auth,
    api_key: "",
    api_key_configured: provider.api_key_configured ?? false,
    base_url: provider.base_url ?? "",
    model: provider.model ?? "",
  };
}

function providerUsesSdkFields(providerId: string): boolean {
  return providerId === "codex" || providerId === "claude";
}

function providerApiKeyLabel(providerId: string): string {
  return providerId === "claude" ? "Anthropic API key" : "OpenAI API key";
}

function providerModelPlaceholder(providerId: string): string {
  return providerId === "claude" ? "Model (default claude-sonnet-4-0)" : "Model (default gpt-4.1)";
}

function providerSdkHelpText(providerId: string): string {
  if (providerId === "claude") {
    return "Claude can run SDK-first with Anthropic credentials only, or fall back to the real `claude` binary when configured.";
  }
  return "Codex can run SDK-first with API credentials only, or fall back to the real `codex` binary when configured.";
}

export default function Settings({ workspaceId }: SettingsProps) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [workspace, setWorkspace] = useState<WorkspaceRecord | null>(null);
  const [governance, setGovernance] = useState<WorkspaceGovernanceSnapshot | null>(null);
  const [providerHealth, setProviderHealth] = useState<ProviderHealthRecord[]>([]);
  const [providerDrafts, setProviderDrafts] = useState<Record<string, ProviderConnectionDraft & { api_key_configured?: boolean }>>({});
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null);
  const [repositoryPreference, setRepositoryPreference] = useState<RepositoryActionPreferenceRecord>(defaultRepositoryActionPreference);
  const [autoApprovePreference, setAutoApprovePreference] = useState<AutoApprovePreferenceRecord>(defaultAutoApprovePreference);
  const [savingRepositoryPreference, setSavingRepositoryPreference] = useState(false);
  const [savingAutoApprovePreference, setSavingAutoApprovePreference] = useState(false);
  const [savingProviderPriority, setSavingProviderPriority] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState(
    apiConfigured ? "Loading provider settings." : "Demo provider settings.",
  );
  const [providerPriority, setProviderPriority] = useState<string[]>(["claude", "codex", "copilot", "opencode"]);
  const [policyFiles, setPolicyFiles] = useState<PolicyPackFile[]>([]);
  const [expandedPolicyFile, setExpandedPolicyFile] = useState<string | null>(null);
  const [policyDrafts, setPolicyDrafts] = useState<Record<string, string>>({});
  const [savingPolicyFile, setSavingPolicyFile] = useState<string | null>(null);
  const [loadingPolicy, setLoadingPolicy] = useState(false);
  const [ncpEnabled, setNcpEnabled] = useState(false);
  const [ncpAvailable, setNcpAvailable] = useState<boolean | null>(null);
  const [savingNcp, setSavingNcp] = useState(false);

  useEffect(() => {
    if (!apiConfigured) return;
    if (!workspaceId) {
      setWorkspace(null);
      setProviderHealth([]);
      setProviderDrafts({});
      setRepositoryPreference(defaultRepositoryActionPreference);
      setAutoApprovePreference(defaultAutoApprovePreference);
      setGovernance(null);
      setProviderPriority(["claude", "codex", "copilot", "opencode"]);
      setPolicyFiles([]);
      setPolicyDrafts({});
      setSettingsStatus("Select a workspace to configure trust and provider posture.");
      return;
    }
    const activeWorkspaceId = workspaceId;
    let cancelled = false;
    async function loadSettingsProviders() {
      try {
        const [ws, nextProviders, operations] = await Promise.all([
          getWorkspace(activeWorkspaceId),
          listProviders(activeWorkspaceId),
          getWorkspaceOperationalViews(activeWorkspaceId),
        ]);
        if (!cancelled) {
          setWorkspace(ws);
          setRepositoryPreference(normalizeRepositoryActionPreference(ws.metadata.repository_action_preference));
          setAutoApprovePreference(normalizeAutoApprovePreference(ws.metadata.auto_approve_preference));
          setGovernance(operations.governance);
          setProviderPriority(operations.governance.policy_posture.provider_priority);
          setNcpEnabled(ws.metadata.ncp_enabled ?? false);
          setProviderHealth(nextProviders);
          setProviderDrafts(Object.fromEntries(nextProviders.map((p) => [p.id, defaultProviderDraft(p)])));
          setSettingsStatus(`${nextProviders.length} providers loaded from workspace settings.`);
        }
      } catch (error) {
        if (!cancelled) {
          setSettingsStatus(error instanceof Error ? error.message : "Provider settings load failed.");
        }
      }
      setLoadingPolicy(true);
      try {
        const files = await getWorkspacePolicyPack(activeWorkspaceId);
        if (!cancelled) {
          setPolicyFiles(files);
          setPolicyDrafts(Object.fromEntries(files.map((f) => [f.name, f.content])));
        }
      } catch {
        // policy pack unavailable — not a blocking error
      } finally {
        if (!cancelled) setLoadingPolicy(false);
      }
    }
    void loadSettingsProviders();
    return () => { cancelled = true; };
  }, [apiConfigured, workspaceId]);

  useEffect(() => {
    if (!apiConfigured || !workspaceId) return;
    checkNcpAvailable(workspaceId)
      .then((result) => setNcpAvailable(result.ncp_available))
      .catch(() => setNcpAvailable(false));
  }, [apiConfigured, workspaceId]);

  async function testProvider(provider: ProviderHealthRecord) {
    if (!apiConfigured || !workspaceId) {
      setSettingsStatus("Testing providers requires a selected workspace and local service.");
      return;
    }
    setTestingProviderId(provider.id);
    try {
      const ws = await getWorkspace(workspaceId);
      if (!workspace) {
        setWorkspace(ws);
        setRepositoryPreference(normalizeRepositoryActionPreference(ws.metadata.repository_action_preference));
      }
      const draft = providerDrafts[provider.id] ?? defaultProviderDraft(provider);
      const updated = await testProviderConnection(ws.id, provider.id, draft);
      setProviderHealth((current) => current.map((c) => c.id === updated.id ? updated : c));
      setProviderDrafts((current) => ({
        ...current,
        [updated.id]: {
          ...draft,
          path: updated.path,
          auth: updated.auth,
          api_key: "",
          api_key_configured: updated.api_key_configured ?? draft.api_key_configured,
          base_url: updated.base_url ?? draft.base_url ?? "",
          model: updated.model ?? draft.model ?? "",
        },
      }));
      setSettingsStatus(`${updated.name} is ${updated.health}${updated.last_error ? `: ${updated.last_error}` : "."}`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "Provider test failed.");
    } finally {
      setTestingProviderId(null);
    }
  }

  async function saveRepositoryPreference() {
    if (!apiConfigured || !workspaceId) {
      setSettingsStatus("Saving repository actions requires a selected workspace and local service.");
      return;
    }
    const ws = workspace ?? await getWorkspace(workspaceId);
    if (!workspace) {
      setWorkspace(ws);
    }
    setSavingRepositoryPreference(true);
    try {
      const nextPreference = {
        ...repositoryPreference,
        scope: "workspace" as const,
        allowed_modes: [...repositoryActionModes],
      };
      const updated = await updateWorkspace(ws.id, {
        repository_action_preference: nextPreference,
      });
      setWorkspace(updated);
      setRepositoryPreference(normalizeRepositoryActionPreference(updated.metadata.repository_action_preference));
      setSettingsStatus(`Repository actions set to ${repositoryActionModeLabel(nextPreference.mode).toLowerCase()}.`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "Repository preference save failed.");
    } finally {
      setSavingRepositoryPreference(false);
    }
  }

  async function saveAutoApprovePreference() {
    if (!apiConfigured || !workspaceId) {
      setSettingsStatus("Saving approval workflow requires a selected workspace and local service.");
      return;
    }
    const ws = workspace ?? await getWorkspace(workspaceId);
    if (!workspace) {
      setWorkspace(ws);
    }
    setSavingAutoApprovePreference(true);
    try {
      const nextPreference = {
        ...autoApprovePreference,
        scope: "workspace" as const,
        allowed_modes: [...autoApproveModes],
      };
      const updated = await updateWorkspace(ws.id, {
        auto_approve_preference: nextPreference,
      });
      setWorkspace(updated);
      setAutoApprovePreference(normalizeAutoApprovePreference(updated.metadata.auto_approve_preference));
      setSettingsStatus(`Approval workflow set to ${autoApproveModeLabel(nextPreference.mode).toLowerCase()}.`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "Approval preference save failed.");
    } finally {
      setSavingAutoApprovePreference(false);
    }
  }

  async function saveProviderPriorityOrder() {
    if (!apiConfigured || !workspaceId) {
      setSettingsStatus("Saving provider routing requires a selected workspace and local service.");
      return;
    }
    const ws = workspace ?? await getWorkspace(workspaceId);
    if (!workspace) {
      setWorkspace(ws);
    }
    setSavingProviderPriority(true);
    try {
      const updated = await updateWorkspace(ws.id, {
        provider_priority: providerPriority,
      });
      setWorkspace(updated);
      const operations = await getWorkspaceOperationalViews(ws.id);
      setGovernance(operations.governance);
      setProviderPriority(operations.governance.policy_posture.provider_priority);
      setSettingsStatus(`Dispatch order saved. ${operations.governance.provider_routing.selected_provider} is currently first viable.`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "Provider routing save failed.");
    } finally {
      setSavingProviderPriority(false);
    }
  }

  async function saveNcpEnabledSetting() {
    if (!apiConfigured || !workspaceId) {
      setSettingsStatus("Saving NCP setting requires a selected workspace.");
      return;
    }
    const ws = workspace ?? await getWorkspace(workspaceId);
    if (!workspace) setWorkspace(ws);
    setSavingNcp(true);
    try {
      const updated = await updateWorkspace(ws.id, {
        ncp_enabled: ncpEnabled,
      });
      setWorkspace(updated);
      setSettingsStatus(`NCP ${ncpEnabled ? "enabled" : "disabled"}.`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "NCP save failed.");
    } finally {
      setSavingNcp(false);
    }
  }

  async function savePolicyFile(filename: string) {
    if (!apiConfigured || !workspaceId) return;
    setSavingPolicyFile(filename);
    try {
      const content = policyDrafts[filename] ?? "";
      await putWorkspacePolicyPackFile(workspaceId, filename, content);
      setPolicyFiles((current) =>
        current.map((f) => f.name === filename ? { ...f, content } : f),
      );
      setSettingsStatus(`${filename} saved.`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : `Save failed for ${filename}.`);
    } finally {
      setSavingPolicyFile(null);
    }
  }

  const visibleProviders: ProviderHealthRecord[] = providerHealth.length ? providerHealth : providers.map((p: Provider) => ({
    id: p.id,
    name: p.name,
    provider_type: p.type,
    transport_kind: p.id === "local" || p.type === "local" || p.type === "deterministic" ? "deterministic" : "cli",
    transport_posture: p.id === "local" || p.type === "local" || p.type === "deterministic" ? "builtin" : "cli_fallback",
    health: p.health,
    auth: p.auth,
    path: p.path,
    capabilities: p.capabilities,
    api_key_configured: false,
    base_url: null,
    model: null,
    degraded_reason:
      p.id === "local" || p.type === "local" || p.type === "deterministic"
        ? null
        : "Demo provider is shown through the CLI fallback posture.",
    last_checked_at: null,
    last_error: null,
  }));

  const readyItems: string[] = [];
  const pendingItems: string[] = [];

  if (apiConfigured) {
    readyItems.push("CLI connected");
  } else {
    pendingItems.push("CLI service");
  }

  const hasOnlineProviders = visibleProviders.some((p) => p.health === "online");
  if (hasOnlineProviders) {
    readyItems.push(`${visibleProviders.filter((p) => p.health === "online").length} providers`);
  } else {
    pendingItems.push("Provider setup");
  }

  readyItems.push("Policy pack");
  readyItems.push("Database");

  return (
    <div className="grid two">
      <section className="panel">
        <ReadinessCard readyItems={readyItems} pendingItems={pendingItems} />

        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          <div className="section-header">
            <h2 style={{ fontSize: "0.9rem", margin: 0 }}>Governance</h2>
            <span className={`pill-mini ${governance?.override_history?.length ? "warning" : "healthy"}`}>
              {governance?.override_history?.length ? `${governance.override_history.length} overrides` : "steady"}
            </span>
          </div>
          <p className="section-summary">
            Current repository posture, approval mode, and routing leader at a glance so governance stays readable instead of sprawling.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
            <Card style={{ padding: 10 }}>
              <div style={{ fontSize: "0.68rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
                Repo
              </div>
              <div style={{ fontSize: "0.82rem", fontWeight: 500 }}>
                {repositoryActionModeLabel(repositoryPreference.mode)}
              </div>
            </Card>
            <Card style={{ padding: 10 }}>
              <div style={{ fontSize: "0.68rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
                Approvals
              </div>
              <div style={{ fontSize: "0.82rem", fontWeight: 500 }}>
                {autoApproveModeLabel(autoApprovePreference.mode)}
              </div>
            </Card>
            <Card style={{ padding: 10 }}>
              <div style={{ fontSize: "0.68rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
                Leader
              </div>
              <div style={{ fontSize: "0.82rem", fontWeight: 500 }}>
                {governance?.provider_routing.selected_provider ?? providerPriority[0] ?? "local"}
              </div>
            </Card>
          </div>
        </div>

        <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>
            <h2 style={{ fontSize: "0.92rem" }}>Repository safety</h2>
            <Pill tone={repositoryPreference.mode === "no_action" ? "gray" : "blue"}>
              {repositoryPreference.mode === "no_action" ? "Safe mode" : "Active"}
            </Pill>
          </div>
          <p style={{ margin: "0 0 12px", fontSize: "0.83rem", color: "var(--muted)" }}>
            Controls whether Sarathi can modify your repository. Safe mode blocks all changes. Enable specific actions below to grant permissions.
          </p>
          <div style={{ display: "grid", gap: 8, maxWidth: 420 }}>
            <label style={{ display: "grid", gap: 6, fontSize: "0.8rem" }}>
              <span>Permission level</span>
              <select
                aria-label="Repository action mode"
                value={repositoryPreference.mode}
                onChange={(event) => {
                  const mode = event.target.value as RepositoryActionPreferenceRecord["mode"];
                  setRepositoryPreference((current) => ({
                    ...current,
                    mode,
                    scope: current.scope === "default" ? "workspace" : current.scope,
                    allowed_modes: [...repositoryActionModes],
                  }));
                }}
                style={{ padding: "6px 10px", fontSize: "0.82rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)" }}
              >
                {repositoryActionModes.map((mode) => (
                  <option key={mode} value={mode}>
                    {repositoryActionModeLabel(mode)}
                  </option>
                ))}
              </select>
            </label>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button onClick={() => void saveRepositoryPreference()} disabled={savingRepositoryPreference || !workspace}>
                {savingRepositoryPreference ? "Saving..." : "Save permission"}
              </button>
              {repositoryPreference.mode !== "no_action" && (
                <span style={{ fontSize: "0.72rem", color: "var(--amber)" }}>
                  Will modify repository
                </span>
              )}
            </div>
          </div>
        </div>
        <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>
            <h2 style={{ fontSize: "0.92rem" }}>Approval workflow</h2>
            <Pill tone={autoApprovePreference.mode === "manual_only" ? "gray" : "green"}>
              {autoApprovePreference.mode === "manual_only" ? "Manual" : "Auto-approved"}
            </Pill>
          </div>
          <p style={{ margin: "0 0 12px", fontSize: "0.83rem", color: "var(--muted)" }}>
            Controls how Sarathi handles task gate approvals. Critical governance gates (PRD/AC, repository actions, final handoff) always require manual review.
          </p>
          <div style={{ display: "grid", gap: 8, maxWidth: 420 }}>
            <label style={{ display: "grid", gap: 6, fontSize: "0.8rem" }}>
              <span>Approval mode</span>
              <select
                aria-label="Auto-approve mode"
                value={autoApprovePreference.mode}
                onChange={(event) => {
                  const mode = event.target.value as AutoApprovePreferenceRecord["mode"];
                  setAutoApprovePreference((current) => ({
                    ...current,
                    mode,
                    scope: current.scope === "default" ? "workspace" : current.scope,
                    allowed_modes: [...autoApproveModes],
                  }));
                }}
                style={{ padding: "6px 10px", fontSize: "0.82rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)" }}
              >
                {autoApproveModes.map((mode) => (
                  <option key={mode} value={mode}>
                    {autoApproveModeLabel(mode)}
                  </option>
                ))}
              </select>
            </label>
            {autoApprovePreference.mode === "below_threshold" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <label style={{ display: "grid", gap: 4, fontSize: "0.78rem" }}>
                  <span style={{ color: "var(--muted)" }}>Max nodes</span>
                  <input
                    type="number"
                    aria-label="Max node count"
                    min={1}
                    max={20}
                    value={autoApprovePreference.threshold?.max_node_count ?? 3}
                    onChange={(e) => {
                      const val = Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 1));
                      setAutoApprovePreference((current) => ({
                        ...current,
                        threshold: { ...current.threshold, max_node_count: val },
                      }));
                    }}
                    style={{ padding: "5px 8px", fontSize: "0.82rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)" }}
                  />
                </label>
                <label style={{ display: "grid", gap: 4, fontSize: "0.78rem" }}>
                  <span style={{ color: "var(--muted)" }}>Max complexity</span>
                  <select
                    aria-label="Max complexity"
                    value={autoApprovePreference.threshold?.complexity ?? "low"}
                    onChange={(e) => {
                      setAutoApprovePreference((current) => ({
                        ...current,
                        threshold: { ...current.threshold, complexity: e.target.value },
                      }));
                    }}
                    style={{ padding: "5px 8px", fontSize: "0.82rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)" }}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>
            )}
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button onClick={() => void saveAutoApprovePreference()} disabled={savingAutoApprovePreference || !workspace}>
                {savingAutoApprovePreference ? "Saving..." : "Save workflow"}
              </button>
            </div>
          </div>
        </div>
        <small style={{ display: "block", marginTop: 16, color: "var(--muted)" }}>{settingsStatus}</small>
      </section>
      <section className="panel">
        <h2 style={{ marginBottom: 12 }}>Providers</h2>
        {visibleProviders.map((provider) => {
          const draft = providerDrafts[provider.id] ?? defaultProviderDraft(provider);
          const isExpanded = expandedProviders.has(provider.id);
          return (
            <Card
              key={provider.id}
              style={{
                marginBottom: 8,
                padding: isExpanded ? 10 : "10px 12px",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
                onClick={() => {
                  setExpandedProviders((current) => {
                    const next = new Set(current);
                    if (next.has(provider.id)) {
                      next.delete(provider.id);
                    } else {
                      if (!providerDrafts[provider.id]) {
                        setProviderDrafts((drafts) => ({ ...drafts, [provider.id]: draft }));
                      }
                      next.add(provider.id);
                    }
                    return next;
                  });
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: provider.health === "online" ? "var(--green)" : provider.health === "degraded" ? "var(--amber)" : "var(--red)" }} />
                  <strong style={{ fontSize: "0.85rem" }}>{provider.name}</strong>
                  <span className={`pill-mini ${provider.health}`}>{provider.health}</span>
                </div>
                <span style={{ color: "var(--muted)", fontSize: "0.7rem" }}>{isExpanded ? "▲" : "▼"}</span>
              </div>
              {isExpanded && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                  <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                    <input
                      aria-label={`${provider.name} CLI path`}
                      value={draft.path}
                      onChange={(e) => setProviderDrafts({
                        ...providerDrafts,
                        [provider.id]: { ...draft, path: e.target.value },
                      })}
                      style={{ flex: 1, padding: "6px 10px", fontSize: "0.8rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                      placeholder="CLI path"
                    />
                    <select
                      aria-label={`${provider.name} auth`}
                      value={draft.auth}
                      onChange={(e) => setProviderDrafts({
                        ...providerDrafts,
                        [provider.id]: { ...draft, auth: e.target.value },
                      })}
                      style={{ padding: "6px 8px", fontSize: "0.8rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                    >
                      <option value="connected">Connected</option>
                      <option value="missing">Missing</option>
                      <option value="not_required">Not required</option>
                      <option value="workspace_setting">Workspace setting</option>
                      <option value="github_auth">GitHub OAuth</option>
                    </select>
                  </div>
                  {providerUsesSdkFields(provider.id) ? (
                    <div style={{ display: "grid", gap: 8, marginBottom: 8 }}>
                      <input
                        aria-label={`${provider.name} API key`}
                        type="password"
                        value={draft.api_key ?? ""}
                        onChange={(e) => setProviderDrafts({
                          ...providerDrafts,
                          [provider.id]: { ...draft, api_key: e.target.value },
                        })}
                        style={{ padding: "6px 10px", fontSize: "0.8rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                        placeholder={draft.api_key_configured ? "API key configured. Leave blank to keep." : providerApiKeyLabel(provider.id)}
                      />
                      <div style={{ display: "flex", gap: 8 }}>
                        <input
                          aria-label={`${provider.name} base URL`}
                          value={draft.base_url ?? ""}
                          onChange={(e) => setProviderDrafts({
                            ...providerDrafts,
                            [provider.id]: { ...draft, base_url: e.target.value },
                          })}
                          style={{ flex: 1, padding: "6px 10px", fontSize: "0.8rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                          placeholder="Base URL (optional)"
                        />
                        <input
                          aria-label={`${provider.name} model`}
                          value={draft.model ?? ""}
                          onChange={(e) => setProviderDrafts({
                            ...providerDrafts,
                            [provider.id]: { ...draft, model: e.target.value },
                          })}
                          style={{ flex: 1, padding: "6px 10px", fontSize: "0.8rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                          placeholder={providerModelPlaceholder(provider.id)}
                        />
                      </div>
                      <small style={{ color: "var(--muted)", display: "block" }}>
                        {providerSdkHelpText(provider.id)}
                      </small>
                    </div>
                  ) : null}
                  {provider.last_checked_at && (
                    <small style={{ color: "var(--muted)", display: "block", marginBottom: 8 }}>
                      Last checked: {new Date(provider.last_checked_at).toLocaleString()}
                    </small>
                  )}
                  {provider.last_error && (
                    <small style={{ color: "var(--red)", display: "block", marginBottom: 8 }}>
                      {provider.last_error}
                    </small>
                  )}
                  {provider.degraded_reason && (
                    <small style={{ color: "var(--amber)", display: "block", marginBottom: 8 }}>
                      {provider.degraded_reason}
                    </small>
                  )}
                  <button
                    onClick={() => void testProvider(provider)}
                    disabled={testingProviderId !== null}
                    style={{ fontSize: "0.75rem", padding: "4px 10px" }}
                  >
                    {testingProviderId === provider.id ? "Testing..." : "Test connection"}
                  </button>
                </div>
              )}
            </Card>
          );
        })}
      </section>
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="section-header">
          <h2 style={{ fontSize: "0.9rem", margin: 0 }}>Dispatch order</h2>
        </div>
        <p className="section-summary">
          Sarathi tries agents in this workspace order, then falls back. Keep it deliberate so provider routing is obvious during review.
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
          {providerPriority.map((pid, idx) => (
            <div key={pid} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
              <span style={{ fontSize: "0.68rem", fontWeight: 600, color: idx === 0 ? "var(--ink)" : "var(--muted)" }}>
                {idx + 1}
              </span>
              <span style={{ fontSize: "0.8rem", fontWeight: idx === 0 ? 600 : 400 }}>{pid}</span>
              {idx > 0 && (
                <button
                  onClick={() => {
                    const newOrder = [...providerPriority];
                    [newOrder[idx - 1], newOrder[idx]] = [newOrder[idx], newOrder[idx - 1]];
                    setProviderPriority(newOrder);
                  }}
                  style={{ fontSize: "0.6rem", padding: "1px 3px", opacity: 0.4, border: "none", background: "transparent", cursor: "pointer" }}
                >
                  ▲
                </button>
              )}
            </div>
          ))}
        </div>
        <button style={{ height: 28, fontSize: "0.76rem" }} onClick={() => void saveProviderPriorityOrder()} disabled={savingProviderPriority || !workspace}>
          {savingProviderPriority ? "Saving..." : "Save"}
        </button>
      </section>
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="section-header">
          <h2 style={{ fontSize: "0.9rem", margin: 0 }}>Override history</h2>
        </div>
        <p className="section-summary">
          A compact audit trail of the latest governance changes, repository decisions, and posture overrides for this workspace.
        </p>
        {governance?.override_history?.length ? (
          <div style={{ display: "grid", gap: 8 }}>
            {governance.override_history.map((entry) => (
              <Card key={entry.id} style={{ padding: 10, borderRadius: "var(--radius-sm)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                  <strong style={{ fontSize: "0.8rem" }}>{entry.summary}</strong>
                  <span className="pill-mini">{entry.event_type.split(".").pop()}</span>
                </div>
                <div style={{ fontSize: "0.7rem", color: "var(--faint)" }}>
                  {new Date(entry.created_at).toLocaleString()}
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>No overrides recorded.</div>
        )}
      </section>
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title" style={{ marginBottom: 10 }}>
          <h2 style={{ fontSize: "0.92rem" }}>Neural Context Protocol</h2>
          {ncpAvailable !== null && (
            <Pill tone={ncpAvailable ? "green" : "red"}>
              {ncpAvailable ? "Available" : "Not installed"}
            </Pill>
          )}
        </div>
        <p style={{ margin: "0 0 12px", fontSize: "0.83rem", color: "var(--muted)" }}>
          Route context compilation, persistence, and artifacts through NCP (Neural Context
          Protocol) for advanced context management. Requires NCP to be installed and initialized.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              role="switch"
              checked={ncpEnabled}
              onChange={(e) => setNcpEnabled(e.target.checked)}
              style={{ accentColor: "var(--accent)" }}
            />
            Enable NCP
          </label>
          <button onClick={() => void saveNcpEnabledSetting()} disabled={savingNcp || !workspace}>
            {savingNcp ? "Saving..." : "Save"}
          </button>
        </div>
      </section>
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="section-header">
          <h2 style={{ fontSize: "0.9rem", margin: 0 }}>Policy pack</h2>
        </div>
        {loadingPolicy && (
          <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>Loading policy files…</div>
        )}
        {!loadingPolicy && policyFiles.length === 0 && workspaceId && (
          <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>No policy pack found for this workspace.</div>
        )}
        {policyFiles.map((file) => {
          const isExpanded = expandedPolicyFile === file.name;
          const isDirty = policyDrafts[file.name] !== file.content;
          return (
            <div key={file.name} style={{ marginBottom: 8, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", cursor: "pointer" }}
                onClick={() => setExpandedPolicyFile(isExpanded ? null : file.name)}
              >
                <span style={{ fontSize: "0.85rem", fontWeight: 500 }}>{file.name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {isDirty && <span style={{ fontSize: "0.68rem", color: "var(--amber)" }}>unsaved</span>}
                  <span style={{ color: "var(--muted)", fontSize: "0.7rem" }}>{isExpanded ? "▲" : "▼"}</span>
                </div>
              </div>
              {isExpanded && (
                <div style={{ padding: "0 14px 14px" }}>
                  <textarea
                    aria-label={`Edit ${file.name}`}
                    value={policyDrafts[file.name] ?? ""}
                    onChange={(e) => setPolicyDrafts((d) => ({ ...d, [file.name]: e.target.value }))}
                    rows={Math.min(30, Math.max(8, (policyDrafts[file.name] ?? "").split("\n").length + 2))}
                    style={{
                      width: "100%",
                      fontFamily: "monospace",
                      fontSize: "0.78rem",
                      padding: "8px 10px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border)",
                      background: "var(--canvas)",
                      resize: "vertical",
                      boxSizing: "border-box",
                    }}
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                    <button
                      onClick={() => void savePolicyFile(file.name)}
                      disabled={savingPolicyFile !== null || !isDirty}
                      style={{ fontSize: "0.75rem", padding: "4px 10px" }}
                    >
                      {savingPolicyFile === file.name ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={() => setPolicyDrafts((d) => ({ ...d, [file.name]: file.content }))}
                      disabled={!isDirty}
                      style={{ fontSize: "0.75rem", padding: "4px 10px" }}
                    >
                      Revert
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
