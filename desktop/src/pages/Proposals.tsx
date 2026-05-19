import { useEffect, useState } from "react";

import {
  acceptProposal,
  getKnowledgeCenter,
  getProposalDetail,
  getProposals,
  getSarathiApiConfig,
  rejectProposal,
  type KnowledgeCenterSummary,
  type ProposalDecision,
  type ProposalDetailData,
  type PolicyProposal,
  type ProposalsData,
} from "../apiClient";
import { Card, Pill } from "../components/ui";

interface ProposalsProps {
  workspaceId: string | null;
  focusedProposalId?: string | null;
  onOpenLearning?: (taskId: string) => void;
}

const mockProposals: ProposalsData = {
  workspace_id: "",
  proposals: [
    {
      id: "abc123def456",
      title: "Add Build failure recovery guidance",
      policy_file: "commands.md",
      proposal_kind: "policy_note",
      impacted_assets: ["policy-pack/commands.md"],
      risk_level: "low",
      rationale: "Build recorded repeated failure signals across multiple tasks.",
      suggested_change: "Add a root-cause and retry checklist before repeating the same implementation lane.",
      evidence_refs: ["task-1:repeated_failures:Build", "task-2:repeated_failures:Build"],
      confidence: 0.67,
      source: "repeated_failures",
      routing_hint: {},
    },
    {
      id: "fed654cba321",
      title: "Reroute Build away from codex",
      policy_file: "model-routing.md",
      proposal_kind: "routing_hint",
      impacted_assets: ["policy-pack/model-routing.md"],
      risk_level: "high",
      rationale: "codex recorded repeated failure signals during Build.",
      suggested_change: "Prefer local as the fallback provider for Build when codex repeatedly fails.",
      evidence_refs: ["task-1:provider_failures:Build:codex", "task-2:provider_failures:Build:codex"],
      confidence: 0.67,
      source: "provider_failures",
      routing_hint: { phase: "Build", preferred_provider: "local" },
    },
  ],
  reviewed_history: [],
  status: "ok",
  source: "demo",
};

function proposalTone(confidence: number) {
  if (confidence >= 0.8) return "healthy";
  if (confidence >= 0.6) return "warning";
  return "draft";
}

function riskTone(riskLevel: string) {
  if (riskLevel === "high") return "blocked";
  if (riskLevel === "medium") return "warning";
  return "draft";
}

function proposalTaskId(proposal: PolicyProposal): string | null {
  const firstRef = proposal.evidence_refs[0];
  if (!firstRef) return null;
  const taskId = firstRef.split(":", 1)[0]?.trim();
  return taskId || null;
}

function reviewedDecisionTaskId(decision: ProposalDecision): string | null {
  const firstRef = decision.evidence_refs?.[0];
  if (!firstRef) return null;
  const taskId = firstRef.split(":", 1)[0]?.trim();
  return taskId || null;
}

export default function Proposals({ workspaceId, focusedProposalId, onOpenLearning }: ProposalsProps) {
  const [data, setData] = useState<ProposalsData | null>(null);
  const [details, setDetails] = useState<Record<string, ProposalDetailData>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading proposals.");
  const [learnings, setLearnings] = useState<KnowledgeCenterSummary["learnings"] | null>(null);
  const apiConfigured = getSarathiApiConfig() !== null;

  useEffect(() => {
    if (!workspaceId) {
      setData(null);
      setDetails({});
      setExpandedId(null);
      setLoading(false);
      setStatus("Select a workspace to review self-evolution proposals.");
      return;
    }
    if (!apiConfigured) {
      setData(mockProposals);
      setDetails({});
      setExpandedId(null);
      setLoading(false);
      setStatus("Demo proposals. Connect the Sarathi service for workspace-backed proposal review.");
      return;
    }
    setLoading(true);
    getProposals(workspaceId)
      .then((next) => {
        setData(next);
        setDetails({});
        setExpandedId(null);
        setStatus(`${next.proposals.length} pending proposal${next.proposals.length === 1 ? "" : "s"} generated from workspace history.`);
      })
      .catch((error) => {
        setData(null);
        setStatus(error instanceof Error ? error.message : "Proposal load failed.");
      })
      .finally(() => setLoading(false));
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (!workspaceId || !apiConfigured) {
      setLearnings(null);
      return;
    }
    const workspaceKey = workspaceId;
    let cancelled = false;
    async function loadLearnings() {
      try {
        const kc = await getKnowledgeCenter(workspaceKey);
        if (!cancelled) setLearnings(kc.learnings);
      } catch {
        if (!cancelled) setLearnings(null);
      }
    }
    void loadLearnings();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (!focusedProposalId || !data) return;
    const proposal = data.proposals.find((p) => p.id === focusedProposalId || p.id.startsWith(`${focusedProposalId}-`));
    const reviewedDecision = data.reviewed_history.find((decision) => (
      decision.id === focusedProposalId || decision.id.startsWith(`${focusedProposalId}-`)
    ));
    if (!proposal && !reviewedDecision) return;
    if (proposal && expandedId !== proposal.id) {
      setExpandedId(proposal.id);
    }
    if (proposal && !details[proposal.id] && workspaceId && apiConfigured) {
      setDetailLoadingId(proposal.id);
      void getProposalDetail(workspaceId, proposal.id)
        .then((detail) => {
          setDetails((current) => ({ ...current, [proposal.id]: detail }));
        })
        .catch((error) => {
          setStatus(error instanceof Error ? error.message : "Failed to load proposal detail.");
        })
        .finally(() => {
          setDetailLoadingId((current) => (current === proposal.id ? null : current));
        });
    }
    const focusedId = proposal?.id ?? reviewedDecision?.id;
    const frame = window.requestAnimationFrame(() => {
      const node = document.querySelector<HTMLElement>(`[data-proposal-id="${focusedId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusedProposalId, data, expandedId, details, workspaceId, apiConfigured]);

  function findLearningLink(subject: { id: string; evidence_refs?: string[] }): { title: string; matchedOn: string } | null {
    if (!learnings?.accepted_learnings || learnings.accepted_learnings.length === 0) return null;
    const durableMatch = learnings.accepted_learnings.find((learning) => {
      if (!learning.linked_proposal_id) return false;
      return subject.id === learning.linked_proposal_id || subject.id.startsWith(`${learning.linked_proposal_id}-`);
    });
    if (durableMatch) {
      return { title: durableMatch.title, matchedOn: "durable link" };
    }
    for (const ref of subject.evidence_refs ?? []) {
      const taskId = ref.split(":", 1)[0]?.trim();
      if (!taskId) {
        continue;
      }
      const matchedLearning = learnings.accepted_learnings.find((l) => l.task_id === taskId);
      if (matchedLearning) {
        return { title: matchedLearning.title, matchedOn: `task ${taskId}` };
      }
    }
    return null;
  }

  async function handleToggleDetail(proposal: PolicyProposal) {
    if (expandedId === proposal.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(proposal.id);
    if (details[proposal.id] || !workspaceId || !apiConfigured) {
      return;
    }
    setDetailLoadingId(proposal.id);
    try {
      const detail = await getProposalDetail(workspaceId, proposal.id);
      setDetails((current) => ({ ...current, [proposal.id]: detail }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to load proposal detail.");
    } finally {
      setDetailLoadingId(null);
    }
  }

  async function handleDecision(proposal: PolicyProposal, action: "accept" | "reject") {
    if (!workspaceId) return;
    setProcessingId(proposal.id);
    try {
      if (action === "accept") {
        await acceptProposal(workspaceId, proposal.id);
      } else {
        await rejectProposal(workspaceId, proposal.id);
      }
      setData((current) =>
        current
          ? { ...current, proposals: current.proposals.filter((item) => item.id !== proposal.id) }
          : current,
      );
      setDetails((current) => {
        const next = { ...current };
        delete next[proposal.id];
        return next;
      });
      if (expandedId === proposal.id) {
        setExpandedId(null);
      }
      setStatus(`${action === "accept" ? "Accepted" : "Rejected"} proposal: ${proposal.title}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `${action} failed.`);
    } finally {
      setProcessingId(null);
    }
  }

  return (
    <div style={{ padding: "20px 24px", maxWidth: 980, display: "grid", gap: 16 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Proposal Inbox</h1>
        <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
          Reviewable policy, wiki, skills, routing, and context-compiler proposals synthesized from real workspace behavior.
        </p>
        <p style={{ margin: "6px 0 0", fontSize: "0.76rem", color: "var(--faint)" }}>{status}</p>
      </div>

      {loading ? (
        <Card style={{ padding: 20 }}>
          <strong>Loading proposals…</strong>
          <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
            Sarathi is compiling reviewable evolution proposals from workspace history.
          </p>
        </Card>
      ) : !data ? (
        <Card style={{ padding: 20 }}>
          <strong>Proposal load failed.</strong>
          <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>{status}</p>
        </Card>
      ) : data.proposals.length === 0 && data.reviewed_history.length === 0 ? (
        <Card style={{ padding: 20 }}>
          <strong>No pending proposals.</strong>
          <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
            Sarathi will surface new proposals here when repeated failures, provider routing issues, or review escalations show up across tasks.
          </p>
        </Card>
      ) : (
        <div style={{ display: "grid", gap: 16 }}>
          {data.proposals.length > 0 ? (
            <div style={{ display: "grid", gap: 16 }}>
              {data.proposals.map((proposal) => (
          <Card key={proposal.id} data-proposal-id={proposal.id} style={{ padding: 16, borderColor: focusedProposalId === proposal.id ? "var(--active)" : undefined, boxShadow: focusedProposalId === proposal.id ? "0 0 0 1px var(--active) inset" : undefined }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                <strong style={{ fontSize: "0.95rem" }}>{proposal.title}</strong>
                <div style={{ marginTop: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                  Primary target: {proposal.impacted_assets[0] ?? `policy-pack/${proposal.policy_file}`}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <Pill tone="draft">{proposal.proposal_kind.replaceAll("_", " ")}</Pill>
                <Pill tone={riskTone(proposal.risk_level)}>{proposal.risk_level} risk</Pill>
                <Pill tone={proposalTone(proposal.confidence)}>{proposal.confidence.toFixed(2)} confidence</Pill>
                <Pill tone="draft">{proposal.source}</Pill>
              </div>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <div>
                <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  Rationale
                </div>
                <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--muted)" }}>{proposal.rationale}</p>
              </div>

              <div>
                <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  Suggested change
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--ink)", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12 }}>
                  {proposal.suggested_change}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Evidence refs
                  </div>
                  {proposal.evidence_refs.length > 0 ? (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {proposal.evidence_refs.map((ref) => (
                        <span key={ref} style={{ fontSize: "0.72rem", padding: "4px 7px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                          {ref}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>No explicit evidence references were recorded.</p>
                  )}
                  {(() => {
                    const link = findLearningLink(proposal);
                    if (!link) return null;
                    const taskId = proposalTaskId(proposal);
                    return (
                      <button
                        style={{ marginTop: 8, padding: "6px 8px", background: "var(--active-bg)", borderRadius: "var(--radius-sm)", border: "1px solid var(--active)", display: "flex", alignItems: "center", gap: 6, cursor: onOpenLearning && taskId ? "pointer" : "default", width: "100%" }}
                        onClick={() => onOpenLearning && taskId && onOpenLearning(taskId)}
                        disabled={!onOpenLearning || !taskId}
                      >
                        <span style={{ fontSize: "0.68rem", color: "var(--active-fg)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Learning link</span>
                        <span style={{ fontSize: "0.72rem", color: "var(--active-fg)" }}>
                          {link.title.slice(0, 40)}{link.title.length > 40 ? "…" : ""} via {link.matchedOn}
                        </span>
                      </button>
                    );
                  })()}
                </div>

                <div>
                  <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Impacted assets
                  </div>
                  {proposal.impacted_assets.length > 0 ? (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {proposal.impacted_assets.map((asset) => (
                        <span key={asset} style={{ fontSize: "0.72rem", padding: "4px 7px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                          {asset}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>No impacted assets were recorded.</p>
                  )}
                </div>
              </div>

              <div>
                <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  Routing hint
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                  {Object.keys(proposal.routing_hint).length > 0 ? JSON.stringify(proposal.routing_hint) : "No routing hint."}
                </div>
              </div>

              {expandedId === proposal.id ? (
                <div style={{ display: "grid", gap: 12 }}>
                  <div>
                    <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                      Current asset
                    </div>
                    {detailLoadingId === proposal.id && !details[proposal.id] ? (
                      <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Loading asset preview…</div>
                    ) : details[proposal.id] ? (
                      <div style={{ display: "grid", gap: 6 }}>
                        <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                          {details[proposal.id].policy_preview.path}
                        </div>
                        <pre style={{ margin: 0, padding: 12, fontSize: "0.74rem", overflowX: "auto", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", whiteSpace: "pre-wrap" }}>
                          {details[proposal.id].policy_preview.exists ? details[proposal.id].policy_preview.current_content : "Target asset does not exist yet."}
                        </pre>
                      </div>
                    ) : null}
                  </div>

                  <div>
                    <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                      Accepted asset preview
                    </div>
                    {detailLoadingId === proposal.id && !details[proposal.id] ? (
                      <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>Loading acceptance preview…</div>
                    ) : details[proposal.id] ? (
                      <pre style={{ margin: 0, padding: 12, fontSize: "0.74rem", overflowX: "auto", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", whiteSpace: "pre-wrap" }}>
                        {details[proposal.id].policy_preview.accepted_preview || "No preview is available for this asset."}
                      </pre>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button
                className="secondary-action"
                onClick={() => void handleToggleDetail(proposal)}
                disabled={processingId === proposal.id}
              >
                {expandedId === proposal.id ? "Hide preview" : "Preview change"}
              </button>
              <button
                className="primary"
                onClick={() => void handleDecision(proposal, "accept")}
                disabled={processingId === proposal.id || !workspaceId}
              >
                {processingId === proposal.id ? "Applying…" : "Accept"}
              </button>
              <button
                className="secondary-action"
                onClick={() => void handleDecision(proposal, "reject")}
                disabled={processingId === proposal.id || !workspaceId}
              >
                {processingId === proposal.id ? "Working…" : "Reject"}
              </button>
            </div>
          </Card>
        ))}
            </div>
          ) : null}

          {data.reviewed_history.length > 0 ? (
            <Card style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12 }}>
                <strong>Reviewed history</strong>
                <Pill tone="draft">{data.reviewed_history.length}</Pill>
              </div>
              <div style={{ display: "grid", gap: 12 }}>
                {data.reviewed_history.map((decision) => {
                  const learningLink = findLearningLink(decision);
                  const linkedTaskId = reviewedDecisionTaskId(decision);
                  const isFocused = focusedProposalId === decision.id;
                  return (
                    <div
                      key={decision.id}
                      data-proposal-id={decision.id}
                      style={{
                        padding: 12,
                        borderRadius: "var(--radius-sm)",
                        border: `1px solid ${isFocused ? "var(--active)" : "var(--border)"}`,
                        background: "var(--surface)",
                        boxShadow: isFocused ? "0 0 0 1px var(--active) inset" : undefined,
                        display: "grid",
                        gap: 8,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                        <div>
                          <strong style={{ fontSize: "0.85rem" }}>{decision.title}</strong>
                          <div style={{ marginTop: 4, fontSize: "0.74rem", color: "var(--muted)" }}>
                            Target: {(decision.impacted_assets && decision.impacted_assets[0]) || decision.policy_file}
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <Pill tone={decision.status === "accepted" ? "healthy" : "warning"}>{decision.status}</Pill>
                          <Pill tone="draft">{decision.source}</Pill>
                        </div>
                      </div>
                      {decision.suggested_change ? (
                        <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{decision.suggested_change}</div>
                      ) : null}
                      <div style={{ fontSize: "0.72rem", color: "var(--faint)" }}>
                        Reviewed at {decision.reviewed_at}
                        {decision.reason ? ` · Reason: ${decision.reason}` : ""}
                      </div>
                      {learningLink ? (
                        <button
                          style={{ padding: "6px 8px", background: "var(--active-bg)", borderRadius: "var(--radius-sm)", border: "1px solid var(--active)", display: "flex", alignItems: "center", gap: 6, cursor: onOpenLearning && linkedTaskId ? "pointer" : "default", width: "100%" }}
                          onClick={() => onOpenLearning && linkedTaskId && onOpenLearning(linkedTaskId)}
                          disabled={!onOpenLearning || !linkedTaskId}
                        >
                          <span style={{ fontSize: "0.68rem", color: "var(--active-fg)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Learning link</span>
                          <span style={{ fontSize: "0.72rem", color: "var(--active-fg)" }}>
                            {learningLink.title.slice(0, 40)}{learningLink.title.length > 40 ? "…" : ""} via {learningLink.matchedOn}
                          </span>
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </Card>
          ) : null}
        </div>
      )}
    </div>
  );
}
