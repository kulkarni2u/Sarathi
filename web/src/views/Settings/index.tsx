import { useEffect, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import type { AnyRecord, ProviderHealth } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import { FormModal } from "../../components/FormModal";
import type { FormField } from "../../components/FormModal";
import "./Settings.css";

/**
 * Settings — Providers & routing, Policy, Governance, Preferences.
 * Route: /settings
 *
 * Data sources:
 *  - GET /providers?workspace_id= → providers tab (readiness, transport,
 *    auth posture — never secrets).
 *
 * Policy/Governance/Preferences don't have dedicated endpoints wired into
 * the API client yet (policy-pack / governance projections exist on the
 * service but aren't exposed via web/src/api/client.ts for M1), so those
 * tabs render labeled "not available yet" placeholders alongside any
 * governance-ish hints we can read defensively from the workspace record.
 */

type TabId = "providers" | "policy" | "governance" | "preferences";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "providers", label: "Providers", icon: "\u{1F50C}" }, // 🔌
  { id: "policy", label: "Policy", icon: "\u{1F6E1}️" }, // 🛡️
  { id: "governance", label: "Governance", icon: "\u{1F4CB}" }, // 📋
  { id: "preferences", label: "Preferences", icon: "⚙️" }, // ⚙️
];

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/** Map a provider's `health` field to the shared `.st` status pill variant. */
function statusVariant(health: string | undefined): { cls: string; label: string } {
  switch (health) {
    case "online":
      return { cls: "ok", label: "ready" };
    case "configured_by_user":
      return { cls: "wn", label: "fallback" };
    case "degraded":
      return { cls: "wn", label: "degraded" };
    case "offline":
      return { cls: "of", label: "off" };
    case "missing":
    case "error":
      return { cls: "err", label: health };
    default:
      return { cls: "of", label: health ?? "unknown" };
  }
}

/** Two-letter avatar initials for a provider id, e.g. "claude" → "CL". */
function providerInitials(provider: ProviderHealth): string {
  const id = asString(provider.id) ?? asString(provider.name) ?? "??";
  const cleaned = id.replace(/[^a-zA-Z]/g, "");
  if (cleaned.length >= 2) return cleaned.slice(0, 2).toUpperCase();
  return cleaned.toUpperCase().padEnd(2, "?");
}

function providerSubtitle(provider: ProviderHealth): string {
  const transport = asString(provider.transport_posture) ?? asString(provider.transport_kind);
  const auth = asString(provider.auth);
  const apiKeyConfigured = typeof provider.api_key_configured === "boolean" ? provider.api_key_configured : undefined;
  const parts: string[] = [];
  if (transport) parts.push(transport);
  if (auth) parts.push(auth.replace(/_/g, " "));
  if (apiKeyConfigured !== undefined) parts.push(apiKeyConfigured ? "key configured" : "no key configured");
  return parts.length > 0 ? parts.join(" · ") : "not configured";
}

/** The built-in deterministic provider can't be configured or tested. */
function isConfigurable(provider: ProviderHealth): boolean {
  return (asString(provider.id) ?? "") !== "local";
}

/** Build the edit-form fields for a provider, keyed by its capabilities.
 * SDK-backed providers (claude/codex) take an API key, base URL, and model;
 * CLI providers just take an executable path. */
function providerFields(provider: ProviderHealth): FormField[] {
  const id = asString(provider.id) ?? "";
  const fields: FormField[] = [
    {
      name: "path",
      label: "CLI path / command",
      defaultValue: asString(provider.path) ?? "",
      placeholder: id || "executable on PATH or absolute path",
      hint: "Executable name resolved on PATH, or an absolute path.",
    },
  ];
  if (id === "claude" || id === "codex") {
    const keyConfigured = provider.api_key_configured === true;
    fields.push(
      {
        name: "api_key",
        label: "API key",
        type: "password",
        placeholder: keyConfigured ? "•••••• (leave blank to keep current)" : "Paste API key",
        hint: keyConfigured
          ? "A key is already stored. Leave blank to keep it."
          : id === "claude"
            ? "Falls back to the ANTHROPIC_API_KEY env var if blank."
            : "Falls back to the OPENAI_API_KEY env var if blank.",
      },
      {
        name: "base_url",
        label: "Base URL",
        defaultValue: asString(provider.base_url) ?? "",
        placeholder: "Optional — override the API base URL",
      },
      {
        name: "model",
        label: "Model",
        defaultValue: asString(provider.model) ?? "",
        placeholder: "Optional — default model id",
      },
    );
  }
  return fields;
}

/** Soft, visual-only toggle. Disabled in M1 — no persistence endpoint wired
 * up yet, so flipping it would be misleading. */
function SoftToggle({ on, label }: { on: boolean; label: string }) {
  return (
    <button
      type="button"
      className={`settings-tog${on ? " on" : ""}`}
      disabled
      title={`${label} — preference editing not available in M1`}
      aria-pressed={on}
      aria-label={label}
    >
      <i />
    </button>
  );
}

export default function Settings() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [activeTab, setActiveTab] = useState<TabId>("providers");

  const [providers, setProviders] = useState<ProviderHealth[] | null>(null);
  const [providersLoading, setProvidersLoading] = useState(false);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState<ProviderHealth | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

  // Replace a single provider in the list with the server's updated view
  // (returned by the test endpoint, which both tests and persists config).
  function applyProviderUpdate(updated: ProviderHealth) {
    const id = asString(updated.id);
    setProviders((prev) =>
      prev ? prev.map((p) => (asString(p.id) === id ? updated : p)) : prev,
    );
  }

  async function handleTest(provider: ProviderHealth) {
    const id = asString(provider.id);
    if (!id || !currentWorkspaceId) return;
    setTestingId(id);
    setRowError((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const { provider: updated } = await api.testProvider(currentWorkspaceId, id);
      applyProviderUpdate(updated);
    } catch (err) {
      const message = err instanceof ApiClientError ? err.message : String(err);
      setRowError((prev) => ({ ...prev, [id]: message }));
    } finally {
      setTestingId(null);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setProvidersLoading(true);
    setProvidersError(null);
    api
      .getProviders(currentWorkspaceId ?? undefined, controller.signal)
      .then((data) => setProviders(data.providers ?? []))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setProviders([]);
        setProvidersError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setProvidersLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId]);

  const metadata = (currentWorkspace?.metadata as AnyRecord | undefined) ?? undefined;
  const providerPriority = Array.isArray(metadata?.provider_priority)
    ? (metadata?.provider_priority as unknown[]).map(String)
    : undefined;
  const repositoryActionPreference = metadata?.repository_action_preference as AnyRecord | undefined;
  const autoApprovePreference = metadata?.auto_approve_preference as AnyRecord | undefined;

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Settings</h1>
            <p>
              Providers, policy, and governance for{" "}
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"}
            </p>
          </div>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — settings may be stale or unavailable.</div>
      )}

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab${activeTab === tab.id ? " on" : ""}`}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            <span aria-hidden="true">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && activeTab === "providers" && (
        <div className="settings-grid">
          <div className="card2 settings-sect">
            <h3>
              <span aria-hidden="true">{"\u{1F50C}"}</span> Providers &amp; routing
            </h3>

            {providersLoading && <div className="settings-placeholder">Loading providers…</div>}

            {!providersLoading && providersError && (
              <div className="banner offline">⚠ Failed to load providers: {providersError}</div>
            )}

            {!providersLoading && !providersError && providers && providers.length === 0 && (
              <div className="settings-placeholder">No providers configured.</div>
            )}

            {!providersLoading &&
              !providersError &&
              providers &&
              providers.map((provider) => {
                const variant = statusVariant(asString(provider.health));
                const id = asString(provider.id) ?? "";
                const configurable = isConfigurable(provider);
                const testing = testingId === id;
                const lastError = asString(provider.last_error);
                const error = rowError[id];
                return (
                  <div className="settings-prov-wrap" key={id || providerInitials(provider)}>
                    <div className="settings-prov">
                      <div className="settings-pic">{providerInitials(provider)}</div>
                      <div className="settings-pi">
                        <b>{asString(provider.name) ?? (id || "Unknown provider")}</b>
                        <span>{providerSubtitle(provider)}</span>
                      </div>
                      <span className={`st ${variant.cls}`}>
                        <span className="d" />
                        {variant.label}
                      </span>
                      {configurable && (
                        <div className="settings-prov-actions">
                          <button
                            type="button"
                            className="btn"
                            disabled={testing}
                            onClick={() => handleTest(provider)}
                          >
                            {testing ? "Testing…" : "Test"}
                          </button>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => setConfiguring(provider)}
                          >
                            Configure
                          </button>
                        </div>
                      )}
                    </div>
                    {(error || (lastError && variant.cls !== "ok")) && (
                      <div className="settings-prov-error">⚠ {error ?? lastError}</div>
                    )}
                  </div>
                );
              })}

            <p className="settings-note">
              Secrets are stored by the local service and never rendered here. “Configure” tests the
              connection and saves; “Test” re-checks the stored configuration.
            </p>
          </div>

          <div className="settings-col">
            <div className="card2 settings-sect">
              <h3>Routing priority</h3>
              {providerPriority && providerPriority.length > 0 ? (
                <div className="settings-kvl">
                  <span>Provider priority order</span>
                  <b>{providerPriority.join(" → ")}</b>
                </div>
              ) : (
                <div className="settings-placeholder">No explicit routing priority configured — using defaults.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {currentWorkspaceId && activeTab === "policy" && (
        <div className="settings-tab-panel">
          <div className="card2 settings-sect">
            <h3>
              <span aria-hidden="true">{"\u{1F6E1}️"}</span> Policy pack
            </h3>
            <div className="settings-placeholder">
              Policy pack validation, enabled patterns, approval-gated classes, and cost budgets are not available
              via the M1 web API yet. This tab will populate once a policy-pack projection endpoint is wired up.
            </div>
          </div>
        </div>
      )}

      {currentWorkspaceId && activeTab === "governance" && (
        <div className="settings-tab-panel">
          <div className="card2 settings-sect">
            <h3>
              <span aria-hidden="true">{"\u{1F4CB}"}</span> Governance
            </h3>
            {repositoryActionPreference || autoApprovePreference ? (
              <>
                {repositoryActionPreference && (
                  <div className="settings-kvl">
                    <span>Repository action preference</span>
                    <b>
                      {asString(repositoryActionPreference.mode) ?? JSON.stringify(repositoryActionPreference)}
                    </b>
                  </div>
                )}
                {autoApprovePreference && (
                  <div className="settings-kvl">
                    <span>Auto-approve preference</span>
                    <b>{asString(autoApprovePreference.mode) ?? JSON.stringify(autoApprovePreference)}</b>
                  </div>
                )}
              </>
            ) : (
              <div className="settings-placeholder">
                No governance preferences set for this workspace yet. Approval-gated classes, blast-radius
                thresholds, and reuse preferences will appear here once configured.
              </div>
            )}
          </div>
        </div>
      )}

      {currentWorkspaceId && activeTab === "preferences" && (
        <div className="settings-tab-panel">
          <div className="card2 settings-sect">
            <h3>
              <span aria-hidden="true">{"⚙️"}</span> Preferences
            </h3>
            <div className="settings-kvl">
              <span>Auto-schedule ready nodes</span>
              <SoftToggle on={false} label="Auto-schedule ready nodes" />
            </div>
            <div className="settings-kvl">
              <span>Require approval for irreversible ops</span>
              <SoftToggle on={true} label="Require approval for irreversible ops" />
            </div>
            <div className="settings-kvl">
              <span>Show mock data when offline</span>
              <SoftToggle on={false} label="Show mock data when offline" />
            </div>
            <div className="settings-saved">
              <span aria-hidden="true">ⓘ</span> Preference editing isn't available in M1 — these toggles reflect
              defaults and cannot be changed yet.
            </div>
          </div>
        </div>
      )}

      {configuring && currentWorkspaceId && (
        <FormModal
          title={`Configure ${asString(configuring.name) ?? asString(configuring.id) ?? "provider"}`}
          submitLabel="Test & save"
          fields={providerFields(configuring)}
          onSubmit={async (values) => {
            const id = asString(configuring.id);
            if (!id) return;
            // Only send non-empty fields so a blank API key keeps the stored
            // secret and blank optionals don't clobber existing config.
            const input: { path?: string; api_key?: string; base_url?: string; model?: string } = {};
            if (values.path) input.path = values.path;
            if (values.api_key) input.api_key = values.api_key;
            if (values.base_url) input.base_url = values.base_url;
            if (values.model) input.model = values.model;
            const { provider: updated } = await api.testProvider(currentWorkspaceId, id, input);
            applyProviderUpdate(updated);
            const health = asString(updated.health);
            if (health && health !== "online" && health !== "configured_by_user") {
              throw new Error(asString(updated.last_error) ?? `Connection test failed (${health}).`);
            }
          }}
          onClose={() => setConfiguring(null)}
        />
      )}
    </section>
  );
}
