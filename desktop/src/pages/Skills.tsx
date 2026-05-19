import { useEffect, useMemo, useState } from "react";

import {
  acceptProposal,
  getProposalDetail,
  getSarathiApiConfig,
  getSkills,
  rejectProposal,
  saveSkillsPack,
  type EvolutionHistoryItem,
  type PolicyProposal,
  type ProposalDetailData,
  type SkillRoute,
  type SkillsData,
} from "../apiClient";
import { Card, Pill } from "../components/ui";

interface SkillsProps {
  workspaceId: string | null;
}

const mockSkills: SkillsData = {
  workspace_id: "",
  skills: [
    { name: "typescript-generator", family: "code_generation", source: "policy-pack/skills.md", description: "Generate code from specs." },
    { name: "python-generator", family: "code_generation", source: "policy-pack/skills.md", description: "Generate code from specs." },
    { name: "security-reviewer", family: "code_review", source: "policy-pack/skills.md", description: "Review code quality." },
  ],
  routes: [
    { task_type: "implementation", primary: "codex", secondary: ["local"], always_invoke: false },
    { task_type: "code_review", primary: "codex", secondary: [], always_invoke: true },
  ],
  role_mappings: [
    { role: "Sarathi", phase: "Plan", purpose: "Orchestration and task lifecycle coordination" },
    { role: "Disha", phase: "Plan", purpose: "Requirement analysis and task scoping" },
    { role: "Pravaha", phase: "Build", purpose: "Implementation execution and code generation" },
    { role: "Nirnaya", phase: "Review", purpose: "Quality review and acceptance gates" },
    { role: "Samanvaya", phase: "Review", purpose: "Cross-cutting validation and synthesis" },
  ],
  behavior_assets: [
    { path: "policy-pack/skills.md", exists: true, purpose: "Skill routing and provider selection" },
    { path: "SARATHI.md", exists: true, purpose: "Repository-level orientation and context" },
    { path: "learnings.md", exists: false, purpose: "Accepted learnings and patterns" },
    { path: "wiki/context-compiler.md", exists: false, purpose: "Context compilation guidance" },
  ],
  path: "policy-pack/skills.md",
  source_content: `# Policy Pack: Skill Routing

## Skill Families
\`\`\`yaml
code_generation:
  description: "Generate code from specs"
  skills:
    - typescript-generator
    - python-generator

code_review:
  description: "Review code quality"
  skills:
    - security-reviewer
\`\`\`

## Task Type Routing
\`\`\`yaml
task_type_to_skill:
  implementation:
    primary: codex
    secondary: local
    always_invoke: false
  code_review:
    primary: codex
    always_invoke: true
\`\`\`
`,
  evolution_proposals: [
    { id: "prop-1", title: "Add codex retry skill for Build failures", policy_file: "skills.md", rationale: "Repeated Build failures from codex suggest retry guidance needed.", suggested_change: "Add a retry-with-backoff skill for codex provider.", evidence_refs: ["task-1"], confidence: 0.72, source: "repeated_failures", proposal_kind: "skill_update", impacted_assets: ["policy-pack/skills.md"], risk_level: "low", routing_hint: {} },
    { id: "prop-2", title: "Prefer local for Build phase", policy_file: "model-routing.md", rationale: "codex failing repeatedly in Build phase.", suggested_change: "Set local as primary for Build.", evidence_refs: ["task-2"], confidence: 0.65, source: "provider_failures", proposal_kind: "routing_hint", impacted_assets: ["policy-pack/model-routing.md"], risk_level: "medium", routing_hint: { phase: "Build", preferred_provider: "local" } },
  ],
  evolution_history: [
    { status: "accepted", title: "Add codex retry skill for Build failures", proposal_id: "prop-1", policy_file: "skills.md", proposal_kind: "skill_update", reviewed_at: "2026-05-10T10:00:00Z", reason: "" },
    { status: "rejected", title: "Prefer local for Build phase", proposal_id: "prop-2", policy_file: "model-routing.md", proposal_kind: "routing_hint", reviewed_at: "2026-05-09T10:00:00Z", reason: "Already handled via other means" },
  ],
};

export default function Skills({ workspaceId }: SkillsProps) {
  const [skillsData, setSkillsData] = useState<SkillsData | null>(null);
  const [draftContent, setDraftContent] = useState("");
  const [draftRoutes, setDraftRoutes] = useState<SkillRoute[]>([]);
  const [proposals, setProposals] = useState<PolicyProposal[]>([]);
  const [history, setHistory] = useState<EvolutionHistoryItem[]>([]);
  const [proposalDetails, setProposalDetails] = useState<Record<string, ProposalDetailData>>({});
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("Loading workspace skills.");
  const [processingProposal, setProcessingProposal] = useState<string | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [expandedProposalId, setExpandedProposalId] = useState<string | null>(null);
  const [newRoute, setNewRoute] = useState({ task_type: "", primary: "", secondary: "", always_invoke: false });
  const apiConfigured = getSarathiApiConfig() !== null;

  useEffect(() => {
    if (!workspaceId) {
      setSkillsData(null);
      setDraftContent("");
      setDraftRoutes([]);
      setProposals([]);
      setProposalDetails({});
      setExpandedProposalId(null);
      setLoading(false);
      setStatus("Select a workspace to inspect its policy-backed skill pack.");
      return;
    }
    if (!apiConfigured) {
      setSkillsData(mockSkills);
      setDraftContent(mockSkills.source_content ?? "");
      setDraftRoutes(mockSkills.routes ?? []);
      setProposals(mockSkills.evolution_proposals ?? []);
      setHistory(mockSkills.evolution_history ?? []);
      setProposalDetails({});
      setExpandedProposalId(null);
      setLoading(false);
      setStatus("Demo skill registry. Connect the Sarathi service for persisted policy-pack routing.");
      return;
    }
    setLoading(true);
    getSkills(workspaceId)
      .then((next) => {
        setSkillsData(next);
        setDraftContent(next.source_content ?? "");
        setDraftRoutes(next.routes ?? []);
        setProposals(next.evolution_proposals ?? []);
        setHistory(next.evolution_history ?? []);
        setProposalDetails({});
        setExpandedProposalId(null);
        setStatus(`${next.skills.length} routed skills loaded from the workspace policy pack.`);
      })
      .catch((error) => {
        setSkillsData(null);
        setDraftContent("");
        setDraftRoutes([]);
        setProposals([]);
        setHistory([]);
        setProposalDetails({});
        setExpandedProposalId(null);
        setStatus(error instanceof Error ? error.message : "Skill registry load failed.");
      })
      .finally(() => setLoading(false));
  }, [workspaceId, apiConfigured]);

  const groupedSkills = useMemo(() => {
    const groups = new Map<string, SkillsData["skills"]>();
    for (const skill of skillsData?.skills ?? []) {
      const family = skill.family || "uncategorized";
      const existing = groups.get(family) ?? [];
      existing.push(skill);
      groups.set(family, existing);
    }
    return Array.from(groups.entries());
  }, [skillsData]);

  function quoteYaml(value: string): string {
    return JSON.stringify(value);
  }

  function generateSkillsYaml(routes: SkillRoute[]): string {
    if (routes.length === 0) return "";
    const lines: string[] = ["## Task Type Routing", "```yaml", "task_type_to_skill:"];
    for (const route of routes) {
      lines.push(`  ${route.task_type}:`);
      lines.push(`    primary: ${quoteYaml(route.primary || "")}`);
      if (route.secondary.length > 0) {
        if (route.secondary.length === 1) {
          lines.push(`    secondary: [${quoteYaml(route.secondary[0] || "")}]`);
        } else {
          lines.push("    secondary:");
          for (const secondary of route.secondary) {
            lines.push(`      - ${quoteYaml(secondary)}`);
          }
        }
      }
      lines.push(`    always_invoke: ${route.always_invoke ? "true" : "false"}`);
    }
    lines.push("```");
    return lines.join("\n");
  }

  function replaceRoutingSection(source: string, routes: SkillRoute[]): string {
    const trimmed = source.trimEnd();
    const nextSection = generateSkillsYaml(routes);
    const sectionPattern = /\n## (?:Task Type Routing|Routing Rules)\n```yaml[\s\S]*?```\s*$/;
    if (!nextSection) {
      return trimmed.replace(sectionPattern, "").trimEnd() + "\n";
    }
    if (sectionPattern.test(trimmed)) {
      return trimmed.replace(sectionPattern, `\n${nextSection}`) + "\n";
    }
    return `${trimmed}\n\n${nextSection}\n`;
  }

  function parseSecondaryInput(input: string): string[] {
    return input
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  function addRoute() {
    if (!newRoute.task_type.trim() || !newRoute.primary.trim()) return;
    const normalizedTaskType = newRoute.task_type.trim();
    const newRoutes = [
      ...draftRoutes.filter((route) => route.task_type !== normalizedTaskType),
      {
        task_type: normalizedTaskType,
        primary: newRoute.primary.trim(),
        secondary: parseSecondaryInput(newRoute.secondary),
        always_invoke: newRoute.always_invoke,
      },
    ].sort((left, right) => left.task_type.localeCompare(right.task_type));
    setDraftRoutes(newRoutes);
    setDraftContent((current) => replaceRoutingSection(current, newRoutes));
    setNewRoute({ task_type: "", primary: "", secondary: "", always_invoke: false });
    setStatus(`Updated draft routing for ${normalizedTaskType}. Save skills pack to persist it.`);
  }

  function removeRoute(taskType: string) {
    const newRoutes = draftRoutes.filter((r) => r.task_type !== taskType);
    setDraftRoutes(newRoutes);
    setDraftContent((current) => replaceRoutingSection(current, newRoutes));
    setStatus(`Removed draft routing for ${taskType}. Save skills pack to persist it.`);
  }

  function handleReset() {
    if (!skillsData) return;
    setDraftContent(skillsData.source_content ?? "");
    setDraftRoutes(skillsData.routes ?? []);
    setProposals(skillsData.evolution_proposals ?? []);
    setHistory(skillsData.evolution_history ?? []);
    setProposalDetails({});
    setExpandedProposalId(null);
    setNewRoute({ task_type: "", primary: "", secondary: "", always_invoke: false });
    setStatus(`${skillsData.skills.length} routed skills restored from the saved policy pack.`);
  }

  async function handleToggleProposalDetail(proposal: PolicyProposal) {
    if (expandedProposalId === proposal.id) {
      setExpandedProposalId(null);
      return;
    }
    setExpandedProposalId(proposal.id);
    if (proposalDetails[proposal.id] || !workspaceId || !apiConfigured) {
      return;
    }
    setDetailLoadingId(proposal.id);
    try {
      const detail = await getProposalDetail(workspaceId, proposal.id);
      setProposalDetails((current) => ({ ...current, [proposal.id]: detail }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to load proposal preview.");
    } finally {
      setDetailLoadingId(null);
    }
  }

  async function handleProposalDecision(proposal: PolicyProposal, action: "accept" | "reject") {
    if (!workspaceId) return;
    setProcessingProposal(proposal.id);
    try {
      let decision;
      if (action === "accept") {
        ({ decision } = await acceptProposal(workspaceId, proposal.id));
      } else {
        ({ decision } = await rejectProposal(workspaceId, proposal.id));
      }
      setProposals((prev) => prev.filter((p) => p.id !== proposal.id));
      setHistory((prev) => [
        {
          status: decision.status,
          title: decision.title,
          proposal_id: decision.id,
          policy_file: decision.policy_file,
          proposal_kind: proposal.proposal_kind,
          reviewed_at: decision.reviewed_at,
          reason: typeof decision.reason === "string" ? decision.reason : "",
          source: decision.source,
          impacted_assets: proposal.impacted_assets,
        },
        ...prev.filter((item) => item.proposal_id !== decision.id),
      ]);
      setProposalDetails((current) => {
        const next = { ...current };
        delete next[proposal.id];
        return next;
      });
      if (expandedProposalId === proposal.id) {
        setExpandedProposalId(null);
      }
      setStatus(`${action === "accept" ? "Accepted" : "Rejected"}: ${proposal.title}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `${action} failed.`);
    } finally {
      setProcessingProposal(null);
    }
  }

  async function handleSave() {
    if (!workspaceId) return;
    if (!apiConfigured) {
      setStatus("Connect the Sarathi service to persist the skills pack.");
      return;
    }
    setSaving(true);
    try {
      const next = await saveSkillsPack(workspaceId, { content: draftContent });
      setSkillsData(next);
      setDraftContent(next.source_content ?? "");
      setDraftRoutes(next.routes ?? []);
      setProposals(next.evolution_proposals ?? []);
      setHistory(next.evolution_history ?? []);
      setProposalDetails({});
      setExpandedProposalId(null);
      setStatus(`Saved skills pack with ${next.skills.length} routed skill${next.skills.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Skills pack save failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>Loading skills...</div>;
  }

  if (!skillsData) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>{status}</div>;
  }

  function riskTone(riskLevel: string) {
    if (riskLevel === "high") return "blocked";
    if (riskLevel === "medium") return "warning";
    return "draft";
  }

  return (
    <div style={{ padding: "20px 24px", maxWidth: 980, display: "grid", gap: 16 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Skills Registry</h1>
        <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
          Workspace skill pack and its policy-backed routing families.
        </p>
        <p style={{ margin: "6px 0 0", fontSize: "0.76rem", color: "var(--faint)" }}>{status}</p>
      </div>

      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: "0.94rem" }}>Skill pack source</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              {skillsData.path || "policy-pack/skills.md"}
            </p>
          </div>
          <Pill tone="active">editable</Pill>
        </div>
        <textarea
          value={draftContent}
          onChange={(event) => setDraftContent(event.target.value)}
          spellCheck={false}
          style={{
            minHeight: 260,
            width: "100%",
            resize: "vertical",
            fontSize: "0.82rem",
            lineHeight: 1.6,
            fontFamily: "ui-monospace, SFMono-Regular, monospace",
            background: "var(--surface)",
            padding: 16,
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            color: "var(--ink)",
            marginBottom: 12,
          }}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="primary" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving…" : "Save skills pack"}
          </button>
          <button
            className="secondary-action"
            onClick={handleReset}
            disabled={saving}
          >
            Reset changes
          </button>
        </div>
      </Card>

      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: "0.94rem" }}>Pending evolution</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              Governed skill and routing changes synthesized from workspace behavior.
            </p>
          </div>
          <Pill tone={proposals.length > 0 ? "warning" : "draft"}>{proposals.length}</Pill>
        </div>
        {proposals.length === 0 ? (
          <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>
            No pending skill evolution proposals right now. Sarathi will surface routing and skill updates here when repeated failures or provider posture patterns show up.
          </p>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {proposals.map((proposal) => {
              const detail = proposalDetails[proposal.id];
              const isExpanded = expandedProposalId === proposal.id;
              const isWorking = processingProposal === proposal.id;
              return (
                <div
                  key={proposal.id}
                  style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 6 }}>
                    <div style={{ display: "grid", gap: 4, flex: 1 }}>
                      <span style={{ fontSize: "0.82rem", fontWeight: 500 }}>{proposal.title}</span>
                      <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                        Primary asset: {proposal.impacted_assets[0] ?? `policy-pack/${proposal.policy_file}`}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <Pill tone="draft">{proposal.proposal_kind.replaceAll("_", " ")}</Pill>
                      <Pill tone={riskTone(proposal.risk_level)}>{proposal.risk_level} risk</Pill>
                    </div>
                  </div>
                  <p style={{ margin: "0 0 8px", fontSize: "0.78rem", color: "var(--muted)" }}>{proposal.rationale}</p>
                  {isExpanded ? (
                    <div style={{ display: "grid", gap: 10, marginBottom: 10 }}>
                      <div>
                        <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                          Preview change
                        </div>
                        {detailLoadingId === proposal.id && !detail ? (
                          <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Loading preview…</div>
                        ) : detail ? (
                          <pre
                            style={{
                              margin: 0,
                              padding: 12,
                              fontSize: "0.74rem",
                              overflowX: "auto",
                              background: "var(--surface-elevated)",
                              border: "1px solid var(--border)",
                              borderRadius: "var(--radius-sm)",
                              whiteSpace: "pre-wrap",
                            }}
                          >
                            {detail.policy_preview.accepted_preview || "No accepted preview is available for this asset."}
                          </pre>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button
                      className="secondary-action"
                      style={{ height: 24, fontSize: "0.72rem", padding: "0 10px" }}
                      onClick={() => void handleToggleProposalDetail(proposal)}
                      disabled={isWorking}
                    >
                      {isExpanded ? "Hide preview" : "Preview change"}
                    </button>
                    <button
                      className="primary"
                      style={{ height: 24, fontSize: "0.72rem", padding: "0 10px" }}
                      onClick={() => void handleProposalDecision(proposal, "accept")}
                      disabled={isWorking}
                    >
                      {isWorking ? "Applying…" : "Accept"}
                    </button>
                    <button
                      className="secondary-action"
                      style={{ height: 24, fontSize: "0.72rem", padding: "0 10px" }}
                      onClick={() => void handleProposalDecision(proposal, "reject")}
                      disabled={isWorking}
                    >
                      {isWorking ? "Working…" : "Reject"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {history.length > 0 && (
        <Card style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div>
              <strong style={{ fontSize: "0.94rem" }}>Evolution history</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
                Past accept/reject decisions for skill and routing evolution.
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                <span style={{ color: "var(--active)" }}>{history.filter(h => h.status === "accepted").length}</span> accepted
              </span>
              <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                <span style={{ color: "var(--blocked)" }}>{history.filter(h => h.status === "rejected").length}</span> rejected
              </span>
              <Pill tone="active">{history.length} total</Pill>
            </div>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {history.slice(0, 10).map((item) => (
              <div key={item.proposal_id} style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 6 }}>
                  <div style={{ display: "grid", gap: 2, flex: 1 }}>
                    <span style={{ fontSize: "0.82rem", fontWeight: 500 }}>{item.title}</span>
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>
                      {item.policy_file || "policy-pack"} • {new Date(item.reviewed_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <Pill tone="draft">{item.proposal_kind.replaceAll("_", " ")}</Pill>
                    <Pill tone={item.status === "accepted" ? "active" : "blocked"}>{item.status}</Pill>
                  </div>
                </div>
                {item.source && (
                  <div style={{ fontSize: "0.72rem", color: "var(--faint)", marginBottom: 4 }}>
                    Triggered by: {item.source.replaceAll("_", " ")}
                  </div>
                )}
                {item.status === "rejected" && item.reason && (
                  <div style={{ 
                    fontSize: "0.72rem", 
                    color: "var(--blocked)", 
                    background: "var(--surface)", 
                    padding: "6px 8px", 
                    borderRadius: "var(--radius-sm)",
                    borderLeft: "2px solid var(--blocked)",
                    marginTop: 4
                  }}>
                    <span style={{ fontWeight: 500 }}>Reason:</span> {item.reason}
                  </div>
                )}
                {item.impacted_assets && item.impacted_assets.length > 0 && (
                  <div style={{ fontSize: "0.7rem", color: "var(--faint)", marginTop: 4 }}>
                    Affected: {item.impacted_assets.join(", ")}
                  </div>
                )}
              </div>
            ))}
            {history.length > 10 && (
              <p style={{ margin: 0, fontSize: "0.72rem", color: "var(--muted)" }}>…and {history.length - 10} more</p>
            )}
          </div>
        </Card>
      )}

      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: "0.94rem" }}>Task-type routing rules</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              Maps task types to primary/secondary skill providers.
            </p>
          </div>
          <Pill tone="active">{draftRoutes.length} rules</Pill>
        </div>
        {draftRoutes.length > 0 && (
          <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
            {draftRoutes.map((route) => (
              <div key={route.task_type} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                <div style={{ display: "grid", gap: 2 }}>
                  <span style={{ fontSize: "0.82rem", fontWeight: 500 }}>{route.task_type}</span>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                    {route.primary}{route.secondary.length > 0 ? ` → ${route.secondary.join(", ")}` : ""}{route.always_invoke ? " (always)" : ""}
                  </span>
                </div>
                <button
                  className="secondary-action"
                  style={{ fontSize: "0.72rem", padding: "4px 8px", height: 24 }}
                  onClick={() => removeRoute(route.task_type)}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
        {draftRoutes.length === 0 ? (
          <p style={{ margin: "0 0 16px", fontSize: "0.78rem", color: "var(--muted)" }}>
            No routing rules yet. Add one below and Sarathi will regenerate the routing section in the raw skills pack.
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: "0.72rem", color: "var(--muted)" }}>Task type</label>
            <input
              value={newRoute.task_type}
              onChange={(event) => setNewRoute((current) => ({ ...current, task_type: event.target.value }))}
              placeholder="e.g. implementation"
              style={{ height: 28, fontSize: "0.8rem", padding: "0 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
            />
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: "0.72rem", color: "var(--muted)" }}>Primary</label>
            <input
              value={newRoute.primary}
              onChange={(event) => setNewRoute((current) => ({ ...current, primary: event.target.value }))}
              placeholder="e.g. code_generation"
              style={{ height: 28, fontSize: "0.8rem", padding: "0 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
            />
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: "0.72rem", color: "var(--muted)" }}>Secondary</label>
            <input
              value={newRoute.secondary}
              onChange={(event) => setNewRoute((current) => ({ ...current, secondary: event.target.value }))}
              placeholder="comma-separated optional skills"
              style={{ height: 28, fontSize: "0.8rem", padding: "0 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
            />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "0.72rem", marginBottom: 8 }}>
            <input
              type="checkbox"
              checked={newRoute.always_invoke}
              onChange={(event) => setNewRoute((current) => ({ ...current, always_invoke: event.target.checked }))}
            />
            Always
          </label>
          <button
            className="primary"
            style={{ height: 28, fontSize: "0.76rem", marginBottom: 8 }}
            onClick={addRoute}
            disabled={!newRoute.task_type.trim() || !newRoute.primary.trim()}
          >
            Add rule
          </button>
        </div>
      </Card>

      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: "0.94rem" }}>Role mappings</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              Lifecycle phase to Sarathi role to purpose.
            </p>
          </div>
          <Pill tone="active">{(skillsData.role_mappings ?? []).length} roles</Pill>
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {(skillsData.role_mappings ?? []).map((role) => (
            <div key={role.role} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 10px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", fontSize: "0.8rem" }}>
              <span style={{ fontWeight: 500, minWidth: 80 }}>{role.role}</span>
              <span style={{ color: "var(--muted)", minWidth: 50 }}>{role.phase}</span>
              <span style={{ color: "var(--faint)", flex: 1 }}>{role.purpose}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <strong style={{ fontSize: "0.94rem" }}>Behavior provenance</strong>
            <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
              Workspace files shaping execution behavior.
            </p>
          </div>
          <Pill tone="active">{(skillsData.behavior_assets ?? []).length} assets</Pill>
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {(skillsData.behavior_assets ?? []).map((asset) => (
            <div key={asset.path} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 10px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", fontSize: "0.8rem" }}>
              <div style={{ display: "grid", gap: 2 }}>
                <span style={{ fontWeight: 500, minWidth: 160, color: asset.exists ? "var(--ink)" : "var(--muted)" }}>{asset.path}</span>
                <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{asset.purpose}</span>
              </div>
              <Pill tone={asset.exists ? "healthy" : "draft"}>{asset.exists ? "present" : "missing"}</Pill>
            </div>
          ))}
        </div>
      </Card>

      {groupedSkills.length === 0 ? (
        <Card style={{ padding: 20 }}>
          <strong>No workspace skills found.</strong>
          <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
            Sarathi expects skill routing rules in <code>policy-pack/skills.md</code>.
          </p>
        </Card>
      ) : (
        groupedSkills.map(([family, skills]) => (
          <Card key={family} style={{ padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div>
                <strong style={{ fontSize: "0.94rem" }}>{family}</strong>
                <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
                  {skills[0]?.description || "Policy-backed routing family."}
                </p>
              </div>
              <Pill tone="active">{skills.length} skills</Pill>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {skills.map((skill) => (
                <div key={`${family}-${skill.name}`} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                  <div style={{ display: "grid", gap: 2 }}>
                    <span style={{ fontSize: "0.82rem", fontWeight: 500 }}>{skill.name}</span>
                    <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{skill.source}</span>
                  </div>
                  <Pill tone="draft">policy</Pill>
                </div>
              ))}
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
