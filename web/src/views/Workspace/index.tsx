import { useEffect, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import type { AnyRecord, ProviderHealth, WorkspaceRepository } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Workspace.css";

/**
 * Workspace — "Manage workspace…" page (linked from the sidebar workspace
 * switcher menu).
 * Route: /workspace
 *
 * Data sources:
 *  - GET /workspaces/{id}                 → workspace record (health, metadata)
 *  - GET /workspaces/{id}/repositories    → attached repos
 *  - GET /providers?workspace_id=         → provider readiness
 *
 * Policy posture is read defensively from the workspace's `metadata` (e.g.
 * `repository_action_preference`, `auto_approve_preference`,
 * `provider_priority`) — a dedicated policy-pack projection isn't wired into
 * the API client yet, so this falls back to a labeled placeholder when those
 * fields are absent.
 */

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function healthDot(health: string | undefined): { color: string; label: string } {
  switch (health) {
    case "healthy":
    case "ok":
    case "online":
      return { color: "var(--green)", label: "healthy" };
    case "degraded":
    case "warn":
    case "configured_by_user":
      return { color: "var(--amber)", label: "degraded" };
    case "offline":
    case "error":
      return { color: "var(--red)", label: "offline" };
    default:
      return { color: "var(--faint)", label: health ?? "unknown" };
  }
}

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

function providerInitials(provider: ProviderHealth): string {
  const id = asString(provider.id) ?? asString(provider.name) ?? "??";
  const cleaned = id.replace(/[^a-zA-Z]/g, "");
  if (cleaned.length >= 2) return cleaned.slice(0, 2).toUpperCase();
  return cleaned.toUpperCase().padEnd(2, "?");
}

export default function WorkspaceManage() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus, refresh } = useWorkspace();

  const [workspaceDetail, setWorkspaceDetail] = useState<AnyRecord | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const [repositories, setRepositories] = useState<WorkspaceRepository[] | null>(null);
  const [reposLoading, setReposLoading] = useState(false);
  const [reposError, setReposError] = useState<string | null>(null);

  const [providers, setProviders] = useState<ProviderHealth[] | null>(null);
  const [providersLoading, setProvidersLoading] = useState(false);
  const [providersError, setProvidersError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setWorkspaceDetail(null);
      setRepositories(null);
      return;
    }
    const controller = new AbortController();

    setWorkspaceLoading(true);
    setWorkspaceError(null);
    api
      .getWorkspace(currentWorkspaceId, controller.signal)
      .then((data) => setWorkspaceDetail((data?.workspace as AnyRecord) ?? null))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setWorkspaceDetail(null);
        setWorkspaceError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setWorkspaceLoading(false);
      });

    setReposLoading(true);
    setReposError(null);
    api
      .getWorkspaceRepositories(currentWorkspaceId, controller.signal)
      .then((data) => setRepositories(data.repositories ?? []))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setRepositories([]);
        setReposError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setReposLoading(false);
      });

    setProvidersLoading(true);
    setProvidersError(null);
    api
      .getProviders(currentWorkspaceId, controller.signal)
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

  const metadata = (workspaceDetail?.metadata as AnyRecord | undefined) ?? undefined;
  const workspaceHealth =
    asString(workspaceDetail?.health) ?? asString(metadata?.health) ?? asString(currentWorkspace?.health);
  const health = healthDot(workspaceHealth);

  const providerPriority = Array.isArray(metadata?.provider_priority)
    ? (metadata?.provider_priority as unknown[]).map(String)
    : undefined;
  const repositoryActionPreference = metadata?.repository_action_preference as AnyRecord | undefined;
  const autoApprovePreference = metadata?.auto_approve_preference as AnyRecord | undefined;
  const reusePreferences = metadata?.reuse_preferences as AnyRecord | undefined;

  const onlineProviders = providers?.filter((p) => asString(p.health) === "online").length;

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Manage Workspace</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · health, repositories,
              provider readiness, and policy posture
            </p>
          </div>
          <div className="grow" />
          <button className="btn" onClick={refresh} type="button">
            Refresh
          </button>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — workspace data may be unavailable.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && (
        <>
          {/* ---- health overview ---- */}
          <div className="card2 ws-sect" style={{ marginBottom: 14 }}>
            <h3>Overview</h3>
            {workspaceLoading && <div className="ws-placeholder">Loading workspace…</div>}
            {!workspaceLoading && workspaceError && (
              <div className="banner offline">⚠ Failed to load workspace: {workspaceError}</div>
            )}
            {!workspaceLoading && !workspaceError && (
              <>
                <div className="ws-health-row">
                  <span className="dot" style={{ background: health.color }} />
                  <b>{health.label}</b>
                </div>
                <div className="ws-kvl">
                  <span>Name</span>
                  <b>{asString(workspaceDetail?.name) ?? currentWorkspace?.name ?? currentWorkspaceId}</b>
                </div>
                <div className="ws-kvl">
                  <span>Workspace ID</span>
                  <b>{asString(workspaceDetail?.id) ?? currentWorkspaceId}</b>
                </div>
                {asString(workspaceDetail?.root_path) && (
                  <div className="ws-kvl">
                    <span>Root path</span>
                    <b>{asString(workspaceDetail?.root_path)}</b>
                  </div>
                )}
                {asString(workspaceDetail?.created_at) && (
                  <div className="ws-kvl">
                    <span>Created</span>
                    <b>{asString(workspaceDetail?.created_at)}</b>
                  </div>
                )}
                {asString(workspaceDetail?.updated_at) && (
                  <div className="ws-kvl">
                    <span>Last updated</span>
                    <b>{asString(workspaceDetail?.updated_at)}</b>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="ws-grid">
            {/* ---- attached repositories ---- */}
            <div className="card2 ws-sect">
              <h3>Repositories</h3>
              {reposLoading && <div className="ws-placeholder">Loading repositories…</div>}
              {!reposLoading && reposError && (
                <div className="banner offline">⚠ Failed to load repositories: {reposError}</div>
              )}
              {!reposLoading && !reposError && repositories && repositories.length === 0 && (
                <div className="ws-empty">No repositories attached to this workspace yet.</div>
              )}
              {!reposLoading &&
                !reposError &&
                repositories &&
                repositories.map((repo) => (
                  <div className="ws-repo" key={asString(repo.id) ?? asString(repo.repository_id) ?? asString(repo.name)}>
                    <div className="ws-repo-icon" aria-hidden="true">
                      {"\u{1F4E6}"}
                    </div>
                    <div className="ws-repo-info">
                      <b>{asString(repo.name) ?? asString(repo.path) ?? "(unnamed repository)"}</b>
                      <span>{asString(repo.path) ?? asString(repo.remote_url) ?? "—"}</span>
                    </div>
                  </div>
                ))}
            </div>

            {/* ---- provider readiness ---- */}
            <div className="card2 ws-sect">
              <h3>Provider readiness</h3>
              {providersLoading && <div className="ws-placeholder">Loading providers…</div>}
              {!providersLoading && providersError && (
                <div className="banner offline">⚠ Failed to load providers: {providersError}</div>
              )}
              {!providersLoading && !providersError && providers && providers.length === 0 && (
                <div className="ws-empty">No providers configured.</div>
              )}
              {!providersLoading && !providersError && providers && providers.length > 0 && (
                <>
                  <div className="ws-kvl">
                    <span>Online</span>
                    <b>
                      {onlineProviders} / {providers.length}
                    </b>
                  </div>
                  {providers.map((provider) => {
                    const variant = statusVariant(asString(provider.health));
                    return (
                      <div className="ws-provider" key={asString(provider.id) ?? providerInitials(provider)}>
                        <div className="ws-provider-pic">{providerInitials(provider)}</div>
                        <div className="ws-provider-info">
                          <b>{asString(provider.name) ?? asString(provider.id) ?? "Unknown"}</b>
                          <span>{asString(provider.transport_posture) ?? asString(provider.transport_kind) ?? "—"}</span>
                        </div>
                        <span className={`st ${variant.cls}`}>
                          <span className="d" />
                          {variant.label}
                        </span>
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </div>

          {/* ---- policy posture ---- */}
          <div className="card2 ws-sect">
            <h3>Policy posture</h3>
            {providerPriority || repositoryActionPreference || autoApprovePreference || reusePreferences ? (
              <>
                {providerPriority && providerPriority.length > 0 && (
                  <div className="ws-kvl">
                    <span>Provider priority order</span>
                    <b>{providerPriority.join(" → ")}</b>
                  </div>
                )}
                {repositoryActionPreference && (
                  <div className="ws-kvl">
                    <span>Repository action preference</span>
                    <b>{asString(repositoryActionPreference.mode) ?? JSON.stringify(repositoryActionPreference)}</b>
                  </div>
                )}
                {autoApprovePreference && (
                  <div className="ws-kvl">
                    <span>Auto-approve preference</span>
                    <b>{asString(autoApprovePreference.mode) ?? JSON.stringify(autoApprovePreference)}</b>
                  </div>
                )}
                {reusePreferences && (
                  <div className="ws-kvl">
                    <span>Reuse preferences</span>
                    <b>{JSON.stringify(reusePreferences)}</b>
                  </div>
                )}
              </>
            ) : (
              <div className="ws-placeholder">
                No explicit policy configuration found for this workspace. Approval-gated classes, blast-radius
                thresholds, and cost budgets are managed via the policy pack and are not yet exposed by the M1 web
                API.
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
