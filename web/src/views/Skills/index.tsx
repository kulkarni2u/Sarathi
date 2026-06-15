import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiClientError } from "../../api/client";
import type { SkillsData } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Skills.css";

/**
 * Skills — workspace skill registry, routing table, role mappings, behavior
 * assets, and self-evolution proposals for the policy pack's `skills.md`.
 * Route: /skills
 *
 * Data source: GET /workspaces/{id}/skills.
 *
 * Evolution proposals affecting skills (skill_update / routing_hint kinds,
 * or skills.md / model-routing.md targets) are surfaced here but reviewed on
 * the Proposals view — accepting/rejecting always happens there so there's a
 * single audited decision path.
 */

function riskClass(risk: string | undefined): string {
  const normalized = (risk ?? "").toLowerCase();
  if (normalized === "low" || normalized === "medium" || normalized === "high") return normalized;
  return "medium";
}

export default function Skills() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();
  const [data, setData] = useState<SkillsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .getSkills(currentWorkspaceId, controller.signal)
      .then((result) => setData(result))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setData(null);
        setError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId]);

  const skills = data?.skills ?? [];
  const routes = data?.routes ?? [];
  const roleMappings = data?.role_mappings ?? [];
  const behaviorAssets = data?.behavior_assets ?? [];
  const evolutionProposals = data?.evolution_proposals ?? [];
  const evolutionHistory = data?.evolution_history ?? [];

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Skills</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · skill registry,
              routing, roles, and behavior assets
            </p>
          </div>
          <div className="grow" />
          <Link className="btn" to="/wiki">
            Wiki
          </Link>
          <Link className="btn" to="/proposals">
            Proposals
          </Link>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — skills data may be unavailable.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && loading && (
        <div className="card2 skl-card">
          <div className="skl-loading">Loading skills…</div>
        </div>
      )}

      {currentWorkspaceId && !loading && error && (
        <div className="banner offline">⚠ Failed to load skills: {error}</div>
      )}

      {currentWorkspaceId && !loading && !error && data && (
        <div className="skl-grid">
          {/* Registry */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Skill registry</b>
              <span className="skl-note">{skills.length} skill(s)</span>
            </div>
            {skills.length === 0 ? (
              <div className="skl-empty">No skills registered for this workspace.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Family</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {skills.map((skill, i) => (
                    <tr key={`${skill.name}-${i}`}>
                      <td>{skill.name}</td>
                      <td>{skill.family}</td>
                      <td>{skill.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Routing */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Routing table</b>
              <span className="skl-note">{routes.length} route(s)</span>
            </div>
            {routes.length === 0 ? (
              <div className="skl-empty">No skill routes configured.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Task type</th>
                    <th>Primary</th>
                    <th>Secondary</th>
                    <th>Always invoke</th>
                  </tr>
                </thead>
                <tbody>
                  {routes.map((route, i) => (
                    <tr key={`${route.task_type}-${i}`}>
                      <td>{route.task_type}</td>
                      <td>{route.primary}</td>
                      <td>{(route.secondary ?? []).join(", ") || "—"}</td>
                      <td>{route.always_invoke ? "✓" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Role mappings */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Role mappings</b>
              <span className="skl-note">{roleMappings.length} role(s)</span>
            </div>
            {roleMappings.length === 0 ? (
              <div className="skl-empty">No role mappings configured.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Phase</th>
                    <th>Role</th>
                    <th>Purpose</th>
                  </tr>
                </thead>
                <tbody>
                  {roleMappings.map((mapping, i) => (
                    <tr key={`${mapping.role}-${i}`}>
                      <td>{mapping.phase}</td>
                      <td>{mapping.role}</td>
                      <td>{mapping.purpose}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Behavior assets */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Behavior assets</b>
              <span className="skl-note">{behaviorAssets.length} asset(s)</span>
            </div>
            {behaviorAssets.length === 0 ? (
              <div className="skl-empty">No behavior assets found.</div>
            ) : (
              <div className="skl-list">
                {behaviorAssets.map((asset, i) => (
                  <div className="skl-list-item" key={`${asset.path}-${i}`}>
                    <span className={`skl-exists ${asset.exists ? "yes" : "no"}`}>
                      {asset.exists ? "✓" : "✗"}
                    </span>
                    <span className="skl-path">{asset.path}</span>
                    <span>{asset.purpose}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Evolution proposals */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Evolution proposals</b>
              <span className="skl-note">{evolutionProposals.length} pending — review on Proposals</span>
            </div>
            {evolutionProposals.length === 0 ? (
              <div className="skl-empty">No pending skill-related proposals.</div>
            ) : (
              <div className="skl-list">
                {evolutionProposals.map((p) => (
                  <div className="skl-list-item" key={p.id}>
                    <span>{p.title}</span>
                    <span className={`skl-risk ${riskClass(p.risk_level)}`}>{p.risk_level}</span>
                    <span className="skl-path">{p.policy_file}</span>
                    <Link to="/proposals">Review →</Link>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Evolution history */}
          <div className="card2 skl-card">
            <div className="skl-card-head">
              <b>Evolution history</b>
              <span className="skl-note">{evolutionHistory.length} decision(s)</span>
            </div>
            {evolutionHistory.length === 0 ? (
              <div className="skl-empty">No skill-related proposals have been reviewed yet.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Title</th>
                    <th>Reviewed at</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {evolutionHistory.map((h) => (
                    <tr key={h.id}>
                      <td>
                        <span className={`skl-status ${h.status}`}>{h.status}</span>
                      </td>
                      <td>{h.title}</td>
                      <td>{h.reviewed_at}</td>
                      <td>{h.reason ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Source */}
          <div className="card2 skl-card skl-source">
            <div className="skl-card-head">
              <b>Source (skills.md)</b>
              <span className="skl-note">{data.path}</span>
            </div>
            <pre>{data.source_content || "(skills.md has no content yet)"}</pre>
          </div>
        </div>
      )}
    </section>
  );
}
