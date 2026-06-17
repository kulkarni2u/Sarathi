import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiClientError } from "../../api/client";
import type { AnyRecord, ContextBundle, ContextBundlesData, KnowledgeCenterData } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Knowledge.css";

/**
 * Knowledge Center — dashboard summarizing the workspace's repo guide, wiki,
 * learnings, skills, and self-evolution proposals, plus a context inspector
 * (selected/omitted sources, token posture) for recent dispatch context
 * bundles.
 * Route: /knowledge
 *
 * Data sources:
 *  - GET /workspaces/{id}/knowledge-center (`additionalProperties: true`,
 *    read defensively below)
 *  - GET /workspaces/{id}/context-bundles
 */

const INITIAL_BUNDLE_LIMIT = 10;

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" ? (value as AnyRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export default function Knowledge() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [data, setData] = useState<KnowledgeCenterData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [bundlesData, setBundlesData] = useState<ContextBundlesData | null>(null);
  const [bundlesLoading, setBundlesLoading] = useState(false);
  const [bundlesError, setBundlesError] = useState<string | null>(null);
  const [showAllBundles, setShowAllBundles] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
      setBundlesData(null);
      return;
    }
    const controller = new AbortController();

    setLoading(true);
    setError(null);
    api
      .getKnowledgeCenter(currentWorkspaceId, controller.signal)
      .then((result) => setData(result))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setData(null);
        setError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    setBundlesLoading(true);
    setBundlesError(null);
    api
      .getContextBundles(currentWorkspaceId, controller.signal)
      .then((result) => setBundlesData(result))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setBundlesData(null);
        setBundlesError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBundlesLoading(false);
      });

    return () => controller.abort();
  }, [currentWorkspaceId]);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const guide = asRecord(data?.guide);
  const sectionHealth = asRecord(data?.section_health);
  const wikiHealth = asRecord(sectionHealth.wiki);
  const contextHealth = asRecord(sectionHealth.context);
  const proposalsHealth = asRecord(sectionHealth.proposals);
  const learningsHealth = asRecord(sectionHealth.learnings);
  const learnings = asRecord(data?.learnings);
  const acceptedLearnings = asArray(learnings.accepted_learnings);
  const skills = asRecord(data?.skills);
  const proposals = asRecord(data?.proposals);
  const contextCompilerGuidance = asArray(data?.context_compiler_guidance);

  const presentFiles = asArray(guide.present_files).map(asString);
  const requiredFiles = asArray(guide.required_files).map(asString);

  const bundles = bundlesData?.bundles ?? [];
  const visibleBundles = showAllBundles ? bundles : bundles.slice(0, INITIAL_BUNDLE_LIMIT);

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Knowledge Center</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · repo guide, wiki
              health, learnings, skills, and context inspector
            </p>
          </div>
          <div className="grow" />
          <Link className="btn" to="/wiki">
            Wiki
          </Link>
          <Link className="btn" to="/skills">
            Skills
          </Link>
          <Link className="btn" to="/proposals">
            Proposals
          </Link>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — knowledge center data may be unavailable.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && loading && (
        <div className="card2 kc-card">
          <div className="kc-loading">Loading knowledge center…</div>
        </div>
      )}

      {currentWorkspaceId && !loading && error && (
        <div className="banner offline">⚠ Failed to load knowledge center: {error}</div>
      )}

      {currentWorkspaceId && !loading && !error && data && (
        <>
          <div className="kc-grid">
            {/* Repo guide */}
            <div className="card2 kc-card">
              <h3>
                Repo guide
                {guide.status ? (
                  <span className={`kc-badge ${asString(guide.status)}`}>{asString(guide.status)}</span>
                ) : null}
              </h3>
              <div className="kc-file-list">
                {requiredFiles.map((file) => (
                  <span
                    key={file}
                    className={`kc-file-tag ${presentFiles.includes(file) ? "present" : "missing"}`}
                  >
                    {presentFiles.includes(file) ? "✓" : "✗"} {file}
                  </span>
                ))}
                {requiredFiles.length === 0 && <span style={{ color: "var(--faint)" }}>No guide files defined.</span>}
              </div>
            </div>

            {/* Wiki health */}
            <div className="card2 kc-card">
              <h3>
                Wiki <Link className="kc-link" to="/wiki">open →</Link>
              </h3>
              <div className="kc-stat-grid">
                <div className="kc-stat">
                  <div className="l">Pages</div>
                  <div className="v">{asNumber(wikiHealth.page_count) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Deep links</div>
                  <div className="v">{asNumber(wikiHealth.deep_links) ?? "—"}</div>
                </div>
              </div>
              <p style={{ color: "var(--faint)", fontSize: 11, marginTop: 8 }}>
                Last updated: {asString(wikiHealth.last_updated) || "—"}
              </p>
            </div>

            {/* Context health */}
            <div className="card2 kc-card">
              <h3>Context bundles</h3>
              <div className="kc-stat-grid">
                <div className="kc-stat">
                  <div className="l">Total</div>
                  <div className="v">{asNumber(contextHealth.total_bundles) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Recent</div>
                  <div className="v">{asNumber(contextHealth.recent_count) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Unique tasks</div>
                  <div className="v">{asNumber(contextHealth.unique_tasks) ?? "—"}</div>
                </div>
              </div>
            </div>

            {/* Proposals */}
            <div className="card2 kc-card">
              <h3>
                Proposals <Link className="kc-link" to="/proposals">open →</Link>
              </h3>
              <div className="kc-stat-grid">
                <div className="kc-stat">
                  <div className="l">Pending</div>
                  <div className="v">{asNumber(proposals.pending_count) ?? asNumber(proposalsHealth.pending) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Accepted</div>
                  <div className="v">{asNumber(proposals.accepted_count) ?? asNumber(proposalsHealth.accepted) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Rejected</div>
                  <div className="v">{asNumber(proposals.rejected_count) ?? asNumber(proposalsHealth.rejected) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Last reviewed</div>
                  <div className="v" style={{ fontSize: 11 }}>
                    {asString(proposals.last_reviewed_at) || asString(proposalsHealth.last_reviewed) || "—"}
                  </div>
                </div>
              </div>
            </div>

            {/* Learnings */}
            <div className="card2 kc-card">
              <h3>Learnings</h3>
              <div className="kc-stat-grid">
                <div className="kc-stat">
                  <div className="l">Accepted</div>
                  <div className="v">{asNumber(learningsHealth.accepted_count) ?? acceptedLearnings.length}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Sections</div>
                  <div className="v">{asNumber(learningsHealth.sections) ?? "—"}</div>
                </div>
              </div>
              {acceptedLearnings.length > 0 && (
                <ul className="kc-list">
                  {acceptedLearnings.slice(0, 5).map((entry, i) => {
                    const rec = asRecord(entry);
                    return <li key={i}>{asString(rec.title) || `Learning ${i + 1}`}</li>;
                  })}
                </ul>
              )}
            </div>

            {/* Skills */}
            <div className="card2 kc-card">
              <h3>
                Skills <Link className="kc-link" to="/skills">open →</Link>
                {skills.status ? (
                  <span className={`kc-badge ${asString(skills.status)}`}>{asString(skills.status)}</span>
                ) : null}
              </h3>
              <div className="kc-stat-grid">
                <div className="kc-stat">
                  <div className="l">Families</div>
                  <div className="v">{asNumber(skills.family_count) ?? "—"}</div>
                </div>
                <div className="kc-stat">
                  <div className="l">Skills</div>
                  <div className="v">{asNumber(skills.skill_count) ?? "—"}</div>
                </div>
              </div>
            </div>

            {/* Context compiler guidance */}
            <div className="card2 kc-card">
              <h3>Context compiler guidance</h3>
              {contextCompilerGuidance.length === 0 ? (
                <p style={{ color: "var(--faint)", fontSize: 12 }}>
                  No accepted context-update proposals yet.
                </p>
              ) : (
                <ul className="kc-list">
                  {contextCompilerGuidance.map((entry, i) => {
                    const rec = asRecord(entry);
                    return <li key={i}>{asString(rec.title) || `Guidance ${i + 1}`}</li>;
                  })}
                </ul>
              )}
              <p style={{ color: "var(--faint)", fontSize: 11, marginTop: 8 }}>
                {contextCompilerGuidance.length} accepted context-compiler proposal(s)
              </p>
            </div>
          </div>

          {/* Context inspector */}
          <div className="card2 kc-bundles">
            <div className="kc-bundles-head">
              <b>Context inspector</b>
              <span className="kc-note">
                {bundlesLoading
                  ? "Loading…"
                  : `${bundles.length} bundle(s) · selected/omitted sources and token posture per dispatch`}
              </span>
            </div>
            {bundlesError && <div className="banner offline" style={{ margin: 12 }}>⚠ {bundlesError}</div>}
            {!bundlesLoading && !bundlesError && bundles.length === 0 && (
              <div className="kc-empty">No context bundles recorded yet for this workspace.</div>
            )}
            {!bundlesLoading &&
              !bundlesError &&
              visibleBundles.map((bundle) => (
                <ContextBundleRow
                  key={bundle.dispatch_id}
                  bundle={bundle}
                  expanded={expanded.has(bundle.dispatch_id)}
                  onToggle={() => toggleExpanded(bundle.dispatch_id)}
                />
              ))}
            {!bundlesLoading && !bundlesError && bundles.length > INITIAL_BUNDLE_LIMIT && (
              <div style={{ padding: 12 }}>
                <button className="btn ghost" onClick={() => setShowAllBundles((v) => !v)}>
                  {showAllBundles ? "Show fewer" : `Show all ${bundles.length}`}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------
// Context bundle row
// ---------------------------------------------------------------------

function ContextBundleRow({
  bundle,
  expanded,
  onToggle,
}: {
  bundle: ContextBundle;
  expanded: boolean;
  onToggle: () => void;
}) {
  const pack = asRecord(bundle.context_pack);
  const agentInput = asRecord(pack.agent_input);
  const estimatedTokens = asNumber(pack.estimated_tokens);
  const tokenBudget = asNumber(agentInput.token_budget);
  const relevantFiles = asArray(agentInput.relevant_files);
  const priorFindings = asArray(agentInput.prior_findings);
  const trimmedSections = asArray(pack.trimmed_sections).map(asString).filter(Boolean);

  const tokenPct =
    estimatedTokens != null && tokenBudget != null && tokenBudget > 0
      ? Math.min(100, Math.round((estimatedTokens / tokenBudget) * 100))
      : null;
  const overBudget = estimatedTokens != null && tokenBudget != null && estimatedTokens > tokenBudget;

  return (
    <div className="kc-bundle">
      <button className="kc-bundle-row" onClick={onToggle}>
        <span>{expanded ? "▾" : "▸"}</span>
        <b>{bundle.agent ?? "unknown agent"}</b>
        <span>{asString(pack.role) || "—"}</span>
        <span>{asString(pack.phase) || "—"}</span>
        <span className="kc-bundle-meta">
          {bundle.task_id && <span>task {bundle.task_id}</span>}
          {bundle.created_at && <span>{bundle.created_at}</span>}
        </span>
      </button>
      {expanded && (
        <div className="kc-bundle-detail">
          <div className="kc-detail-row">
            <span>Token posture</span>
            <div className="kc-token-bar">
              <div
                className={`kc-token-bar-fill ${overBudget ? "over" : ""}`}
                style={{ width: `${tokenPct ?? 0}%` }}
              />
            </div>
            <span>
              {estimatedTokens != null ? estimatedTokens : "—"} /{" "}
              {tokenBudget != null ? tokenBudget : "—"} tokens
            </span>
          </div>
          {Boolean(pack.summary) && (
            <div className="kc-detail-row">
              <span>Summary</span>
              <span>{asString(pack.summary)}</span>
            </div>
          )}
          <div className="kc-detail-row">
            <span>Selected files</span>
            <div className="kc-tag-list">
              {relevantFiles.length === 0 ? (
                <span style={{ color: "var(--faint)" }}>none</span>
              ) : (
                relevantFiles.map((f, i) => (
                  <span className="kc-source-tag" key={i}>
                    {typeof f === "string" ? f : JSON.stringify(f)}
                  </span>
                ))
              )}
            </div>
          </div>
          <div className="kc-detail-row">
            <span>Prior findings</span>
            <div className="kc-tag-list">
              {priorFindings.length === 0 ? (
                <span style={{ color: "var(--faint)" }}>none</span>
              ) : (
                priorFindings.map((f, i) => (
                  <span className="kc-source-tag" key={i}>
                    {typeof f === "string" ? f : JSON.stringify(f)}
                  </span>
                ))
              )}
            </div>
          </div>
          <div className="kc-detail-row">
            <span>Omitted sources</span>
            <div className="kc-tag-list">
              {trimmedSections.length === 0 ? (
                <span style={{ color: "var(--faint)" }}>none trimmed</span>
              ) : (
                trimmedSections.map((section, i) => (
                  <span className="kc-omitted-tag" key={i}>
                    {section}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
