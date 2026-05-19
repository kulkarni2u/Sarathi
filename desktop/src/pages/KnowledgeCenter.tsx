import { useEffect, useMemo, useState } from "react";

import {
  getKnowledgeCenter,
  getSarathiApiConfig,
  type KnowledgeCenterSummary,
} from "../apiClient";
import { Card, Pill } from "../components/ui";
import WikiPage from "./Wiki";
import ContextInspector from "./ContextInspector";
import Proposals from "./Proposals";

export type KnowledgeCenterSection = "overview" | "wiki" | "context" | "proposals" | "learnings";

interface KnowledgeCenterProps {
  workspaceId: string | null;
  activeSection?: KnowledgeCenterSection;
  focusedLearningTaskId?: string | null;
  focusedProposalId?: string | null;
  onSectionChange?: (section: KnowledgeCenterSection) => void;
  onOpenTask?: (taskId: string) => void;
  onOpenWorkspace?: (savedViewId?: string) => void;
  onOpenLearning?: (taskId: string) => void;
  onOpenProposal?: (proposalId: string) => void;
}

const sections: Array<{ id: KnowledgeCenterSection; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "wiki", label: "Wiki" },
  { id: "context", label: "Context" },
  { id: "learnings", label: "Learnings" },
  { id: "proposals", label: "Proposals" },
];

const mockKnowledgeCenter: KnowledgeCenterSummary = {
  workspace_id: "",
  guide: {
    status: "partial",
    present_files: ["SARATHI.md", "policy-pack/skills.md"],
    required_files: ["SARATHI.md", "coding-standards.md", "guidelines.md"],
  },
  wiki: [{ name: "README", path: "README.md", exists: true }],
learnings: {
    status: "populated",
    path: "learnings.md",
    sections: 3,
    accepted_learnings: [
    { title: "Accepted: Use systematic debugging for complex issues", summary: "Always follow the investigate skill before proposing fixes", task_id: "task-123", tags: ["debugging", "workflow"], evidence_refs: ["debug-log-1", "error-trace-2"], recommended_template_id: "bugfix-regression", recommended_view_ids: ["blocked-projects", "approvals-inbox"], source_file: "learnings.md", linked_proposal_id: "prop-1", linked_proposal_title: "Add debug skill", linked_playbook_id: "pb-1", linked_playbook_name: "Debug workflow" },
    { title: "Accepted: TDD improves code quality", summary: "Write tests before implementation for better design", task_id: "task-456", tags: ["testing", "quality"], evidence_refs: [], recommended_template_id: "feature-delivery", recommended_view_ids: ["approvals-inbox", "checkpoint-queue"], source_file: "learnings.md", linked_proposal_id: null, linked_proposal_title: null, linked_playbook_id: null, linked_playbook_name: null },
  ],
  },
  skills: {
    status: "available",
    path: "policy-pack/skills.md",
    family_count: 3,
    skill_count: 5,
  },
  proposals: {
    pending_count: 2,
    accepted_count: 4,
    rejected_count: 1,
    last_reviewed_at: new Date().toISOString(),
  },
  recent_contexts: {
    total_bundles: 2,
    recent_count: 2,
    bundles: [
      { dispatch_id: "dispatch-1", task_id: "task-1", agent: "Pravaha", created_at: new Date().toISOString() },
      { dispatch_id: "dispatch-2", task_id: "task-1", agent: "Nirnaya", created_at: new Date().toISOString() },
    ],
  },
  section_health: {
    wiki: { page_count: 1, deep_links: 2, last_updated: new Date().toISOString() },
    context: { total_bundles: 2, recent_count: 2, unique_tasks: 1 },
    proposals: { pending: 2, accepted: 4, rejected: 1, last_reviewed: new Date().toISOString() },
    learnings: { accepted_count: 2, sections: 3 },
  },
};

function sectionSummary(section: KnowledgeCenterSection, data: KnowledgeCenterSummary): {
  title: string;
  description: string;
  highlights: string[];
} {
  if (section === "wiki") {
    return {
      title: "Wiki inside Knowledge Center",
      description: "Workspace documents belong under the Knowledge Center model. This section will hold browsing, editing, and provenance-aware wiki review without making Wiki a separate top-level product.",
      highlights: [
        `${data.wiki.length} workspace page${data.wiki.length === 1 ? "" : "s"} currently indexed`,
        `${data.guide.present_files.length}/${data.guide.required_files.length} guide documents present`,
        "Workspace wiki editing and browsing now lives under Knowledge Center",
      ],
    };
  }
  if (section === "context") {
    return {
      title: "Context inside Knowledge Center",
      description: "Compiled context bundles explain what Sarathi selected, omitted, and sent to agents. This section keeps context inspection tied to workspace knowledge instead of leaving it as a separate peer destination.",
      highlights: [
        `${data.recent_contexts.total_bundles} recorded context bundle${data.recent_contexts.total_bundles === 1 ? "" : "s"}`,
        `${data.recent_contexts.recent_count} recent bundle${data.recent_contexts.recent_count === 1 ? "" : "s"} available for inspection`,
        "Compiled context inspection now lives under Knowledge Center",
      ],
    };
  }
  if (section === "learnings") {
    const acceptedLearnings = data.learnings.accepted_learnings || [];
    return {
      title: "Learnings inside Knowledge Center",
      description: "Accepted learnings capture durable operator guidance promoted from task execution. They connect provenance, evidence, and reusable playbooks.",
      highlights: [
        `${acceptedLearnings.length} accepted learning${acceptedLearnings.length === 1 ? "" : "s"} captured`,
        `${data.learnings.sections} section${data.learnings.sections === 1 ? "" : "s"} in learnings.md`,
        "Learnings connect task provenance to reusable playbooks",
      ],
    };
  }
  return {
    title: "Proposals inside Knowledge Center",
    description: "Self-evolution proposals are part of workspace intelligence. They belong under Knowledge Center so teams can review knowledge, context, and wiki changes in one governed surface.",
    highlights: [
      `${data.proposals.pending_count} pending proposal${data.proposals.pending_count === 1 ? "" : "s"}`,
      `${data.proposals.accepted_count + data.proposals.rejected_count} reviewed proposal${data.proposals.accepted_count + data.proposals.rejected_count === 1 ? "" : "s"}`,
      "Proposal review now lives under Knowledge Center",
    ],
  };
}

export default function KnowledgeCenter({
  workspaceId,
  activeSection = "overview",
  focusedLearningTaskId = null,
  focusedProposalId = null,
  onSectionChange,
  onOpenTask,
  onOpenWorkspace,
  onOpenLearning,
  onOpenProposal,
}: KnowledgeCenterProps) {
  const [data, setData] = useState<KnowledgeCenterSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("Loading workspace knowledge.");
  const apiConfigured = getSarathiApiConfig() !== null;
  const acceptedLearnings = data?.learnings.accepted_learnings ?? [];
  const summary = data && activeSection !== "overview" ? sectionSummary(activeSection, data) : null;
  const learningHealth = data?.section_health?.learnings ?? {
    accepted_count: acceptedLearnings.length,
    sections: data?.learnings.sections ?? 0,
  };
  const orderedLearnings = useMemo(() => {
    if (!focusedLearningTaskId) return acceptedLearnings;
    return [...acceptedLearnings].sort((left, right) => {
      const leftMatch = left.task_id === focusedLearningTaskId ? 1 : 0;
      const rightMatch = right.task_id === focusedLearningTaskId ? 1 : 0;
      return rightMatch - leftMatch;
    });
  }, [acceptedLearnings, focusedLearningTaskId]);

  useEffect(() => {
    if (!workspaceId) {
      setData(null);
      setLoading(false);
      setStatus("Select a workspace to inspect its guide, wiki, skills, and context bundles.");
      return;
    }
    if (!apiConfigured) {
      setData(mockKnowledgeCenter);
      setLoading(false);
      setStatus("Demo knowledge center. Connect the Sarathi service for persisted workspace data.");
      return;
    }
    setLoading(true);
    getKnowledgeCenter(workspaceId)
      .then((next) => {
        setData(next);
        setStatus("Workspace knowledge center loaded.");
      })
      .catch((error) => {
        setData(null);
        setStatus(error instanceof Error ? error.message : "Knowledge center load failed.");
      })
      .finally(() => setLoading(false));
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (activeSection !== "learnings" || !focusedLearningTaskId) return;
    const frame = window.requestAnimationFrame(() => {
      const node = document.querySelector<HTMLElement>(`[data-learning-task-id="${focusedLearningTaskId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeSection, focusedLearningTaskId, orderedLearnings.length]);

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>Loading knowledge center...</div>;
  }

  if (!data) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>{status}</div>;
  }

  return (
    <div style={{ padding: "20px 24px", maxWidth: 980, display: "grid", gap: 16 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Knowledge Center</h1>
        <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
          Workspace guide, wiki, learnings, proposals, and compiled context provenance.
        </p>
        <p style={{ margin: "6px 0 0", fontSize: "0.76rem", color: "var(--faint)" }}>{status}</p>
      </div>

      <Card style={{ padding: 12 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {sections.map((section) => {
            const selected = activeSection === section.id;
            return (
              <button
                key={section.id}
                className={selected ? "primary" : "secondary-action"}
                onClick={() => onSectionChange?.(section.id)}
                style={{ minHeight: 30, fontSize: "0.78rem" }}
              >
                {section.label}
              </button>
            );
          })}
        </div>
      </Card>

      {summary ? (
        <>
        <Card style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <strong style={{ fontSize: "0.96rem" }}>{summary.title}</strong>
            <Pill tone="active">{activeSection}</Pill>
          </div>
          <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--muted)" }}>{summary.description}</p>
          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {summary.highlights.map((item) => (
              <div
                key={item}
                style={{
                  fontSize: "0.78rem",
                  color: "var(--muted)",
                  padding: "10px 12px",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                {item}
              </div>
            ))}
          </div>
        </Card>
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
            minHeight: 560,
            background: "var(--panel)",
          }}
        >
          {activeSection === "wiki" ? <WikiPage workspaceId={workspaceId} /> : null}
          {activeSection === "context" ? <ContextInspector workspaceId={workspaceId} /> : null}
          {activeSection === "learnings" ? (
            <div style={{ padding: 16 }}>
              {acceptedLearnings.length === 0 ? (
                <div style={{ color: "var(--muted)", fontSize: "0.86rem", textAlign: "center", padding: 40 }}>
                  No accepted learnings captured yet. Learnings are captured when operator guidance is promoted from task execution.
                </div>
              ) : (
                <div style={{ display: "grid", gap: 12 }}>
                  {orderedLearnings.map((learning, idx) => {
                    const isFocused = focusedLearningTaskId !== null && learning.task_id === focusedLearningTaskId;
                    return (
                    <Card
                      key={idx}
                      data-learning-task-id={learning.task_id ?? undefined}
                      style={{
                        padding: 14,
                        borderColor: isFocused ? "var(--active)" : undefined,
                        boxShadow: isFocused ? "0 0 0 1px var(--active) inset" : undefined,
                        background: isFocused ? "color-mix(in srgb, var(--active-bg) 35%, var(--panel))" : undefined,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                        <strong style={{ fontSize: "0.9rem" }}>{learning.title}</strong>
                        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                          {(isFocused || learning.linked_proposal_id) ? (
                            <span style={{ fontSize: "0.68rem", padding: "2px 6px", background: "var(--active)", color: "white", borderRadius: "var(--radius-sm)" }}>
                              {learning.linked_proposal_id ? `Linked to: ${learning.linked_proposal_title?.slice(0, 20) || 'proposal'}` : "Linked from proposal"}
                            </span>
                          ) : null}
                          {learning.task_id && (
                            <span style={{ fontSize: "0.68rem", padding: "2px 6px", background: "var(--active-bg)", color: "var(--active-fg)", borderRadius: "var(--radius-sm)" }}>
                              task: {learning.task_id.slice(0, 8)}
                            </span>
                          )}
                        </div>
                      </div>
                      {learning.summary && (
                        <p style={{ margin: "0 0 10px", fontSize: "0.8rem", color: "var(--muted)" }}>{learning.summary}</p>
                      )}
                      {learning.tags && learning.tags.length > 0 && (
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                          {learning.tags.map((tag) => (
                            <span key={tag} style={{ fontSize: "0.7rem", padding: "2px 8px", background: "var(--surface)", borderRadius: "var(--radius-sm)", color: "var(--muted)" }}>
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      {learning.evidence_refs && learning.evidence_refs.length > 0 && (
                        <div style={{ fontSize: "0.72rem", color: "var(--faint)" }}>
                          <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>Evidence: </span>
                          {learning.evidence_refs.slice(0, 3).join(", ")}
                          {learning.evidence_refs.length > 3 && ` +${learning.evidence_refs.length - 3} more`}
                        </div>
                      )}
                      {(learning.recommended_template_id || learning.recommended_view_ids.length > 0 || learning.linked_playbook_name) && (
                        <div style={{ display: "grid", gap: 4, marginTop: 10, fontSize: "0.72rem", color: "var(--faint)" }}>
                          {learning.linked_playbook_name ? (
                            <div>
                              <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>Promoted playbook: </span>
                              {learning.linked_playbook_name}
                            </div>
                          ) : learning.recommended_template_id ? (
                            <div>
                              <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>Promoted playbook: </span>
                              {learning.recommended_template_id}
                            </div>
                          ) : null}
                          {learning.recommended_view_ids.length > 0 ? (
                            <div>
                              <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>Suggested views: </span>
                              {learning.recommended_view_ids.join(", ")}
                            </div>
                          ) : null}
                        </div>
                      )}
                      {(learning.task_id && onOpenTask) || (learning.linked_proposal_id && onOpenProposal) || ((learning.recommended_template_id || learning.recommended_view_ids.length > 0) && onOpenWorkspace) ? (
                        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                          {learning.task_id && onOpenTask ? (
                            <button
                              className="btn-secondary"
                              style={{ height: 26, fontSize: "0.72rem", padding: "0 10px" }}
                              onClick={() => onOpenTask(learning.task_id)}
                            >
                              Open task
                            </button>
                          ) : null}
                          {learning.linked_proposal_id && onOpenProposal ? (
                            <button
                              className="btn-secondary"
                              style={{ height: 26, fontSize: "0.72rem", padding: "0 10px" }}
                              onClick={() => onOpenProposal(learning.linked_proposal_id as string)}
                            >
                              Open proposal
                            </button>
                          ) : null}
{(learning.recommended_template_id || learning.recommended_view_ids.length > 0) && onOpenWorkspace ? (
                            <button
                              className="btn-secondary"
                              style={{ height: 26, fontSize: "0.72rem", padding: "0 10px" }}
                              onClick={() => onOpenWorkspace(learning.recommended_view_ids[0] ?? undefined)}
                            >
                              Open playbooks
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </Card>
                  )})}
                </div>
              )}
            </div>
          ) : null}
          {activeSection === "proposals" ? (
            <Proposals
              workspaceId={workspaceId}
              focusedProposalId={focusedProposalId}
              onOpenLearning={onOpenLearning}
            />
          ) : null}
        </div>
        </>
      ) : null}

      {activeSection === "overview" ? (
        <>
          {data.section_health ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 8 }}>
              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: "0.86rem" }}>Wiki</strong>
                  <Pill tone={data.section_health.wiki.page_count > 0 ? "healthy" : "draft"}>{data.section_health.wiki.page_count} pages</Pill>
                </div>
                <div style={{ display: "grid", gap: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Deep links</span>
                    <span style={{ fontWeight: 500 }}>{data.section_health.wiki.deep_links}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Last updated</span>
                    <span style={{ fontWeight: 500 }}>
                      {data.section_health.wiki.last_updated ? new Date(data.section_health.wiki.last_updated).toLocaleDateString() : "Never"}
                    </span>
                  </div>
                </div>
              </Card>
              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: "0.86rem" }}>Context</strong>
                  <Pill tone={data.section_health.context.total_bundles > 0 ? "healthy" : "draft"}>{data.section_health.context.total_bundles} bundles</Pill>
                </div>
                <div style={{ display: "grid", gap: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Unique tasks</span>
                    <span style={{ fontWeight: 500 }}>{data.section_health.context.unique_tasks}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Recent</span>
                    <span style={{ fontWeight: 500 }}>{data.section_health.context.recent_count}</span>
                  </div>
                  {(data.context_compiler_guidance?.length ?? 0) > 0 && (
                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                      <span>Guidance</span>
                      <span style={{ fontWeight: 500, color: "var(--green)" }}>{(data.context_compiler_guidance ?? []).length} rules</span>
                    </div>
                  )}
                </div>
              </Card>
              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: "0.86rem" }}>Proposals</strong>
                  <Pill tone={data.section_health.proposals.pending > 0 ? "warning" : "healthy"}>{data.section_health.proposals.pending} pending</Pill>
                </div>
                <div style={{ display: "grid", gap: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Accepted</span>
                    <span style={{ fontWeight: 500, color: "var(--green)" }}>{data.section_health.proposals.accepted}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Rejected</span>
                    <span style={{ fontWeight: 500, color: "var(--muted)" }}>{data.section_health.proposals.rejected}</span>
                  </div>
                </div>
              </Card>
              <Card style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: "0.86rem" }}>Learnings</strong>
                  <Pill tone={learningHealth.accepted_count > 0 ? "healthy" : "draft"}>{learningHealth.accepted_count} accepted</Pill>
                </div>
                <div style={{ display: "grid", gap: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Sections</span>
                    <span style={{ fontWeight: 500 }}>{learningHealth.sections}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>Status</span>
                    <span style={{ fontWeight: 500 }}>{data.learnings.status}</span>
                  </div>
                </div>
              </Card>
            </div>
          ) : null}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <strong>Workspace guide</strong>
                <Pill tone={data.guide.status === "complete" ? "healthy" : data.guide.status === "partial" ? "warning" : "draft"}>
                  {data.guide.status}
                </Pill>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                {data.guide.present_files.length} of {data.guide.required_files.length} expected operating docs are present.
              </p>
            </Card>

            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <strong>Wiki pages</strong>
                <Pill tone={data.wiki.length > 0 ? "healthy" : "draft"}>{data.wiki.length}</Pill>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                {data.wiki.length > 0 ? "Workspace knowledge pages are available." : "No workspace wiki pages found yet."}
              </p>
            </Card>

            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <strong>Learnings</strong>
                <Pill tone={data.learnings.status === "populated" ? "healthy" : "draft"}>{data.learnings.status}</Pill>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                {data.learnings.sections > 0 ? `${data.learnings.sections} sections available for retrieval and reuse.` : "No accepted learnings captured yet."}
              </p>
            </Card>

            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <strong>Skills pack</strong>
                <Pill tone={data.skills.status === "available" ? "healthy" : "draft"}>{data.skills.skill_count}</Pill>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                {data.skills.family_count ? `${data.skills.family_count} routing families in policy-pack/skills.md.` : "No skill routing pack found."}
              </p>
            </Card>

            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <strong>Evolution inbox</strong>
                <Pill tone={data.proposals.pending_count > 0 ? "warning" : "healthy"}>{data.proposals.pending_count}</Pill>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
                {data.proposals.pending_count > 0
                  ? `${data.proposals.pending_count} pending proposal${data.proposals.pending_count === 1 ? "" : "s"} need review.`
                  : "No pending proposal reviews right now."}
              </p>
            </Card>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 12 }}>
            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <strong>Guide coverage</strong>
                <Pill tone="active">{data.guide.present_files.length}/{data.guide.required_files.length}</Pill>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {data.guide.required_files.map((file) => {
                  const present = data.guide.present_files.includes(file);
                  return (
                    <div key={file} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
                      <span>{file}</span>
                      <span style={{ color: present ? "var(--green)" : "var(--muted)" }}>{present ? "present" : "missing"}</span>
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <strong>Recent context bundles</strong>
                <Pill tone="active">{data.recent_contexts.total_bundles}</Pill>
              </div>
              {data.recent_contexts.bundles.length === 0 ? (
                <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>No compiled context packs recorded yet.</p>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.recent_contexts.bundles.map((bundle) => (
                    <div key={bundle.dispatch_id} style={{ display: "grid", gap: 2, padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }}>
                        <strong>{bundle.agent}</strong>
                        <span style={{ color: "var(--muted)" }}>{bundle.task_id}</span>
                      </div>
                      <span style={{ fontSize: "0.72rem", color: "var(--faint)" }}>{new Date(bundle.created_at).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Card style={{ padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <strong>Proposal posture</strong>
              <Pill tone="draft">{data.proposals.accepted_count + data.proposals.rejected_count} reviewed</Pill>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
              <div style={{ padding: "10px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Pending</div>
                <div style={{ marginTop: 4, fontSize: "1rem", fontWeight: 600 }}>{data.proposals.pending_count}</div>
              </div>
              <div style={{ padding: "10px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Accepted</div>
                <div style={{ marginTop: 4, fontSize: "1rem", fontWeight: 600 }}>{data.proposals.accepted_count}</div>
              </div>
              <div style={{ padding: "10px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Rejected</div>
                <div style={{ marginTop: 4, fontSize: "1rem", fontWeight: 600 }}>{data.proposals.rejected_count}</div>
              </div>
              <div style={{ padding: "10px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Last review</div>
                <div style={{ marginTop: 4, fontSize: "0.82rem", color: "var(--muted)" }}>
                  {data.proposals.last_reviewed_at ? new Date(data.proposals.last_reviewed_at).toLocaleString() : "None yet"}
                </div>
              </div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
