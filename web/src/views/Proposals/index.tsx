import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import type { PolicyProposal, ProposalDetailData, ProposalsData, ReviewedProposalDecision } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Proposals.css";

/**
 * Proposals — self-evolution proposal review (diff, risk, source evidence,
 * decision audit).
 * Route: /proposals
 *
 * Data sources:
 *  - GET /workspaces/{id}/proposals                       → pending + reviewed history
 *  - GET /workspaces/{id}/proposals/{proposalId}          → detail + policy preview
 *  - POST /workspaces/{id}/proposals/{proposalId}/accept  → accept decision
 *  - POST /workspaces/{id}/proposals/{proposalId}/reject  → reject decision
 *
 * Nothing self-evolves silently: pending proposals only take effect once a
 * human accepts them here, and every decision (accept or reject) is recorded
 * in `reviewed_history` for audit.
 */

function riskClass(risk: string | undefined): string {
  const normalized = (risk ?? "").toLowerCase();
  if (normalized === "low" || normalized === "medium" || normalized === "high") return normalized;
  return "medium";
}

export default function Proposals() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();

  const [data, setData] = useState<ProposalsData | null>(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProposalDetailData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<ReviewedProposalDecision | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const reload = (workspaceId: string, signal?: AbortSignal) => {
    setIndexLoading(true);
    setIndexError(null);
    return api
      .getProposals(workspaceId, signal)
      .then((result) => {
        setData(result);
        const pending = result.proposals ?? [];
        setSelectedId((prev) => {
          if (prev && pending.some((p) => p.id === prev)) return prev;
          return pending[0]?.id ?? null;
        });
      })
      .catch((err) => {
        if (signal?.aborted) return;
        setData(null);
        setSelectedId(null);
        setIndexError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!signal?.aborted) setIndexLoading(false);
      });
  };

  // Load the proposals index whenever the workspace changes.
  useEffect(() => {
    if (!currentWorkspaceId) {
      setData(null);
      setSelectedId(null);
      return;
    }
    const controller = new AbortController();
    void reload(currentWorkspaceId, controller.signal);
    return () => controller.abort();
  }, [currentWorkspaceId]);

  // Load the selected proposal's detail.
  useEffect(() => {
    if (!currentWorkspaceId || !selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError(null);
    setConfirmation(null);
    setActionError(null);
    setRejectOpen(false);
    setRejectReason("");
    api
      .getProposalDetail(currentWorkspaceId, selectedId, controller.signal)
      .then((result) => setDetail(result))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setDetail(null);
        setDetailError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId, selectedId]);

  const pending = useMemo<PolicyProposal[]>(() => data?.proposals ?? [], [data]);
  const reviewedHistory = useMemo<ReviewedProposalDecision[]>(() => data?.reviewed_history ?? [], [data]);

  async function handleAccept() {
    if (!currentWorkspaceId || !selectedId) return;
    setActionPending(true);
    setActionError(null);
    try {
      const result = await api.acceptProposal(currentWorkspaceId, selectedId);
      setConfirmation(result.decision);
      setSelectedId(null);
      setDetail(null);
      await reload(currentWorkspaceId);
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  }

  async function handleReject() {
    if (!currentWorkspaceId || !selectedId) return;
    setActionPending(true);
    setActionError(null);
    try {
      const result = await api.rejectProposal(currentWorkspaceId, selectedId, rejectReason || undefined);
      setConfirmation(result.decision);
      setSelectedId(null);
      setDetail(null);
      setRejectOpen(false);
      setRejectReason("");
      await reload(currentWorkspaceId);
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setActionPending(false);
    }
  }

  const proposal = detail?.proposal;
  const preview = detail?.policy_preview;

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Proposals</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · self-evolution
              proposals — nothing applies until you accept it here.
            </p>
          </div>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — proposals may be unavailable.</div>
      )}

      {confirmation && (
        <div className={`banner ${confirmation.status === "accepted" ? "" : "warn"}`}>
          {confirmation.status === "accepted" ? "✓" : "✕"} Proposal "{confirmation.title}" was{" "}
          {confirmation.status} {confirmation.reason ? `(reason: ${confirmation.reason})` : ""} at{" "}
          {confirmation.reviewed_at}.
        </div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && (
        <div className="prop-layout">
          <nav className="prop-nav">
            {indexLoading && <div className="prop-loading">Loading proposals…</div>}
            {!indexLoading && indexError && (
              <div className="prop-empty">Failed to load proposals: {indexError}</div>
            )}
            {!indexLoading && !indexError && pending.length === 0 && (
              <div className="prop-empty">No pending proposals for this workspace.</div>
            )}
            {!indexLoading &&
              !indexError &&
              pending.map((p) => (
                <button
                  key={p.id}
                  className={`prop-item${p.id === selectedId ? " on" : ""}`}
                  onClick={() => setSelectedId(p.id)}
                  title={p.id}
                >
                  <span className="prop-title">{p.title || p.id}</span>
                  <span className="prop-meta">
                    <span className={`prop-risk ${riskClass(p.risk_level)}`}>{p.risk_level ?? "—"}</span>
                    <span className="prop-tag">{p.proposal_kind}</span>
                  </span>
                  <span className="prop-file">{p.policy_file}</span>
                </button>
              ))}

            {!indexLoading && !indexError && (
              <>
                <button className="prop-history-toggle" onClick={() => setHistoryOpen((open) => !open)}>
                  {historyOpen ? "▾" : "▸"} Reviewed history ({reviewedHistory.length})
                </button>
                {historyOpen &&
                  (reviewedHistory.length === 0 ? (
                    <div className="prop-empty">No reviewed proposals yet.</div>
                  ) : (
                    reviewedHistory.map((h) => (
                      <div className="prop-item" key={h.id} style={{ cursor: "default" }}>
                        <span className="prop-title">{h.title || h.id}</span>
                        <span className="prop-meta">
                          <span className={`prop-status ${h.status}`}>{h.status}</span>
                          <span className="prop-file">{h.reviewed_at}</span>
                        </span>
                        {h.reason && <span className="prop-file">reason: {h.reason}</span>}
                      </div>
                    ))
                  ))}
              </>
            )}
          </nav>

          <div className="prop-detail">
            {!selectedId && !indexLoading && pending.length === 0 && (
              <div className="prop-empty">
                No pending proposals to review. Accepted/rejected decisions appear under "Reviewed history".
              </div>
            )}

            {!selectedId && !indexLoading && pending.length > 0 && (
              <div className="prop-empty">Select a proposal from the list to review its details.</div>
            )}

            {selectedId && detailLoading && <div className="prop-loading">Loading proposal…</div>}

            {selectedId && !detailLoading && detailError && (
              <div className="banner offline">⚠ Failed to load proposal: {detailError}</div>
            )}

            {selectedId && !detailLoading && !detailError && proposal && (
              <>
                <h2>{proposal.title}</h2>
                <div className="prop-detail-meta">
                  <span className={`prop-risk ${riskClass(proposal.risk_level)}`}>
                    {proposal.risk_level} risk
                  </span>
                  <span className="prop-tag">{proposal.proposal_kind}</span>
                  <span>confidence {Math.round((proposal.confidence ?? 0) * 100)}%</span>
                  <span>source: {proposal.source}</span>
                  <span className="prop-file">{proposal.policy_file}</span>
                </div>

                <div className="prop-detail-section">
                  <h3>Rationale</h3>
                  <p>{proposal.rationale || "—"}</p>
                </div>

                <div className="prop-detail-section">
                  <h3>Suggested change</h3>
                  <p>{proposal.suggested_change || "—"}</p>
                </div>

                <div className="prop-detail-section">
                  <h3>Impacted assets</h3>
                  {proposal.impacted_assets?.length > 0 ? (
                    <ul>
                      {proposal.impacted_assets.map((asset, i) => (
                        <li key={i}>{asset}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>—</p>
                  )}
                </div>

                <div className="prop-detail-section">
                  <h3>Evidence</h3>
                  {proposal.evidence_refs?.length > 0 ? (
                    <ul>
                      {proposal.evidence_refs.map((ref, i) => (
                        <li key={i}>{ref}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>—</p>
                  )}
                </div>

                <div className="prop-detail-section">
                  <h3>Policy diff</h3>
                  <div className="prop-diff">
                    <div className="prop-diff-col current">
                      <h4>Current ({preview?.path ?? proposal.policy_file})</h4>
                      <pre>
                        {preview?.exists
                          ? preview.current_content || "(empty file)"
                          : "(file does not exist yet)"}
                      </pre>
                    </div>
                    <div className="prop-diff-col accepted">
                      <h4>If accepted</h4>
                      <pre>{preview?.accepted_preview || "(no preview available)"}</pre>
                    </div>
                  </div>
                </div>

                {actionError && <div className="banner warn">⚠ {actionError}</div>}

                <div className="prop-actions">
                  <button className="btn primary" disabled={actionPending} onClick={() => void handleAccept()}>
                    Accept
                  </button>
                  {!rejectOpen ? (
                    <button className="btn" disabled={actionPending} onClick={() => setRejectOpen(true)}>
                      Reject
                    </button>
                  ) : (
                    <div className="prop-reject-form">
                      <input
                        type="text"
                        placeholder="Reason (optional)"
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                      />
                      <button className="btn" disabled={actionPending} onClick={() => void handleReject()}>
                        Confirm reject
                      </button>
                      <button
                        className="btn ghost"
                        disabled={actionPending}
                        onClick={() => {
                          setRejectOpen(false);
                          setRejectReason("");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
