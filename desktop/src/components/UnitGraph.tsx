import { useState } from "react";
import type { TaskGraphNode } from "../apiClient";
import { dispatchSubtask, transitionSubtask } from "../apiClient";
import { Pill } from "./ui";

interface UnitGraphProps {
  nodes: TaskGraphNode[];
  edges: Array<{ from: string; to: string; type: string }>;
  taskPhase: string | null;
  taskId: string | null;
  onAction: () => void;
}

const PHASES = [
  "Route",
  "Brainstorm",
  "PlanningAdvisor",
  "Plan",
  "Build",
  "Verify",
  "Review",
  "TaskTracking",
  "RiskCheck",
  "Elegance",
  "PhaseLog",
  "Learn",
];

const STATUS_COLORS: Record<string, string> = {
  in_progress: "var(--blue-9)",
  completed: "var(--green-9)",
  blocked: "var(--amber-9)",
  failed: "var(--red-9)",
  queued: "var(--gray-9)",
  review: "var(--violet-9)",
};

function statusDotColor(status: string): string {
  return STATUS_COLORS[status] ?? "var(--gray-8)";
}

function statusTone(status: string): string {
  if (status === "completed") return "healthy";
  if (status === "in_progress") return "active";
  if (status === "blocked" || status === "failed") return "blocked";
  if (status === "review") return "draft";
  return "warning";
}

const TRANSITION_OPTIONS = ["queued", "in_progress", "blocked", "review", "completed", "failed"];

export default function UnitGraph({ nodes, edges: _edges, taskPhase, taskId: _taskId, onAction }: UnitGraphProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dispatching, setDispatching] = useState(false);
  const [transitioning, setTransitioning] = useState(false);
  const [transitionTarget, setTransitionTarget] = useState<string>("");
  const [showTransitionPicker, setShowTransitionPicker] = useState(false);

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;

  const currentPhaseIdx = PHASES.findIndex(
    (p) => p.toLowerCase() === (taskPhase ?? "").toLowerCase(),
  );

  async function handleDispatch() {
    if (!selectedNode) return;
    setDispatching(true);
    try {
      await dispatchSubtask(selectedNode.id, "opencode");
      onAction();
    } catch (err) {
      console.error("Dispatch failed:", err);
    } finally {
      setDispatching(false);
    }
  }

  async function handleTransition() {
    if (!selectedNode || !transitionTarget) return;
    setTransitioning(true);
    try {
      await transitionSubtask(selectedNode.id, transitionTarget);
      onAction();
      setShowTransitionPicker(false);
      setTransitionTarget("");
    } catch (err) {
      console.error("Transition failed:", err);
    } finally {
      setTransitioning(false);
    }
  }

  return (
    <div style={styles.root}>
      {/* Left: Node list */}
      <div style={styles.listPane}>
        <div style={styles.listHeader}>
          <span style={styles.listHeaderTitle}>Work Units</span>
          <span style={styles.listHeaderCount}>{nodes.length}</span>
        </div>
        <div style={styles.nodeList}>
          {nodes.length === 0 && (
            <div style={styles.empty}>No work units yet.</div>
          )}
          {nodes.map((node) => {
            const isSelected = node.id === selectedId;
            return (
              <button
                key={node.id}
                style={{
                  ...styles.nodeCard,
                  background: isSelected ? "var(--active)" : "var(--surface)",
                  borderColor: isSelected ? "var(--border-strong)" : "var(--border)",
                }}
                onClick={() => setSelectedId(isSelected ? null : node.id)}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    flexShrink: 0,
                    background: statusDotColor(node.status),
                  }} />
                  <div style={styles.nodeId}>{node.id}</div>
                </div>
                <div style={styles.nodeTitle}>{node.title}</div>
                <div style={styles.nodeMeta}>
                  <Pill tone={statusTone(node.status)}>{node.status.replace("_", " ")}</Pill>
                  <span style={styles.roleBadge}>{node.role}</span>
                  <span style={styles.providerBadge}>{node.provider}</span>
                </div>
                {node.blocked_by.length > 0 && (
                  <div style={styles.blockedBy}>
                    blocked by: {node.blocked_by.join(", ")}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Right: Detail panel */}
      <div style={styles.detailPane}>
        {!selectedNode ? (
          <div style={styles.detailEmpty}>
            <p style={{ color: "var(--muted)", fontSize: "0.845rem", textAlign: "center" }}>
              Select a work unit to view details.
            </p>
          </div>
        ) : (
          <div style={styles.detailContent}>
            {/* Header */}
            <div style={styles.detailHeader}>
              <div style={styles.detailTitle}>Unit {selectedNode.id}: {selectedNode.title}</div>
              <div style={styles.detailSubtitle}>
                Role: <strong>{selectedNode.role}</strong>
                {" · "}
                Provider: <strong>{selectedNode.provider}</strong>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                <div style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: statusDotColor(selectedNode.status),
                  flexShrink: 0,
                }} />
                <Pill tone={statusTone(selectedNode.status)}>{selectedNode.status.replace("_", " ")}</Pill>
              </div>
            </div>

            {/* Phase strip */}
            <div style={styles.phaseStripWrap}>
              <div style={styles.phaseStrip}>
                {PHASES.map((phase, idx) => {
                  const isActive = idx === currentPhaseIdx;
                  const isPast = currentPhaseIdx >= 0 && idx < currentPhaseIdx;
                  return (
                    <div
                      key={phase}
                      style={{
                        ...styles.phasePill,
                        background: isActive
                          ? "var(--indigo-9)"
                          : isPast
                          ? "var(--green-a3)"
                          : "var(--gray-a2)",
                        color: isActive ? "#fff" : isPast ? "var(--green-11)" : "var(--muted)",
                        border: isActive
                          ? "1px solid var(--indigo-9)"
                          : "1px solid var(--border)",
                        fontWeight: isActive ? 700 : 400,
                      }}
                      title={phase}
                    >
                      {phase}
                    </div>
                  );
                })}
              </div>
            </div>

            <div style={styles.detailBody}>
              {/* Goal */}
              {selectedNode.task_packet.goal && (
                <div style={styles.section}>
                  <div style={styles.sectionLabel}>Goal</div>
                  <p style={styles.sectionText}>{selectedNode.task_packet.goal}</p>
                </div>
              )}

              {/* Context */}
              {selectedNode.task_packet.context && (
                <div style={styles.section}>
                  <div style={styles.sectionLabel}>Context</div>
                  <p style={styles.sectionText}>{selectedNode.task_packet.context}</p>
                </div>
              )}

              {/* Acceptance Criteria */}
              {selectedNode.task_packet.review_criteria && selectedNode.task_packet.review_criteria.length > 0 && (
                <div style={styles.section}>
                  <div style={styles.sectionLabel}>Acceptance Criteria</div>
                  <ul style={styles.criteriaList}>
                    {selectedNode.task_packet.review_criteria.map((criterion, i) => (
                      <li key={i} style={styles.criteriaItem}>
                        <span style={styles.checkBox}>☐</span>
                        <span style={styles.sectionText}>{criterion}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Evidence */}
              <div style={styles.section}>
                <div style={styles.sectionLabel}>Evidence</div>
                <p style={styles.sectionText}>
                  0 / {selectedNode.evidence_required.length} required
                </p>
              </div>

              {/* Blocked by */}
              {selectedNode.blocked_by.length > 0 && (
                <div style={styles.section}>
                  <div style={styles.sectionLabel}>Blocked by</div>
                  <p style={styles.sectionText}>{selectedNode.blocked_by.join(", ")}</p>
                </div>
              )}
            </div>

            {/* Actions */}
            <div style={styles.detailActions}>
              <button
                style={styles.dispatchBtn}
                onClick={() => void handleDispatch()}
                disabled={dispatching}
              >
                {dispatching ? "Dispatching..." : "Dispatch to OpenCode"}
              </button>

              <div style={styles.transitionGroup}>
                {showTransitionPicker ? (
                  <>
                    <select
                      style={styles.transitionSelect}
                      value={transitionTarget}
                      onChange={(e) => setTransitionTarget(e.target.value)}
                    >
                      <option value="">Pick status...</option>
                      {TRANSITION_OPTIONS.map((s) => (
                        <option key={s} value={s}>{s.replace("_", " ")}</option>
                      ))}
                    </select>
                    <button
                      style={styles.transitionConfirmBtn}
                      disabled={!transitionTarget || transitioning}
                      onClick={() => void handleTransition()}
                    >
                      {transitioning ? "..." : "Apply"}
                    </button>
                    <button
                      style={styles.cancelBtn}
                      onClick={() => { setShowTransitionPicker(false); setTransitionTarget(""); }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    style={styles.transitionBtn}
                    onClick={() => setShowTransitionPicker(true)}
                  >
                    Transition state
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    height: "100%",
    minHeight: 0,
    overflow: "hidden",
  },
  listPane: {
    width: "60%",
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    borderRight: "1px solid var(--border)",
    overflow: "hidden",
  },
  listHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 16px",
    borderBottom: "1px solid var(--border)",
    flexShrink: 0,
  },
  listHeaderTitle: {
    fontSize: "0.8rem",
    fontWeight: 600,
    color: "var(--muted)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  listHeaderCount: {
    fontSize: "0.75rem",
    color: "var(--muted)",
    background: "var(--gray-a3)",
    padding: "1px 7px",
    borderRadius: 4,
  },
  nodeList: {
    flex: 1,
    overflowY: "auto",
    padding: "10px 12px",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  empty: {
    padding: "24px 0",
    textAlign: "center",
    color: "var(--muted)",
    fontSize: "0.845rem",
  },
  nodeCard: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    padding: "10px 12px",
    border: "1px solid var(--border)",
    borderRadius: 8,
    textAlign: "left",
    cursor: "pointer",
    width: "100%",
    transition: "border-color 120ms, background 120ms",
  },
  nodeId: {
    fontSize: "0.68rem",
    fontWeight: 700,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  nodeTitle: {
    fontSize: "0.855rem",
    fontWeight: 500,
    color: "var(--ink)",
    lineHeight: 1.3,
  },
  nodeMeta: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap" as const,
    marginTop: 2,
  },
  roleBadge: {
    fontSize: "0.68rem",
    fontWeight: 600,
    color: "var(--muted)",
    background: "var(--gray-a2)",
    border: "1px solid var(--border)",
    borderRadius: 4,
    padding: "1px 6px",
  },
  providerBadge: {
    fontSize: "0.68rem",
    fontWeight: 500,
    color: "var(--muted)",
    background: "var(--indigo-a2)",
    border: "1px solid var(--indigo-a4)",
    borderRadius: 4,
    padding: "1px 6px",
  },
  blockedBy: {
    fontSize: "0.72rem",
    color: "var(--amber-11)",
    marginTop: 2,
  },
  detailPane: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    minWidth: 0,
  },
  detailEmpty: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  detailContent: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  detailHeader: {
    padding: "16px 16px 12px",
    borderBottom: "1px solid var(--border)",
    flexShrink: 0,
  },
  detailTitle: {
    fontSize: "0.95rem",
    fontWeight: 700,
    color: "var(--ink)",
    letterSpacing: "-0.01em",
    lineHeight: 1.3,
    marginBottom: 4,
  },
  detailSubtitle: {
    fontSize: "0.8rem",
    color: "var(--muted)",
  },
  phaseStripWrap: {
    overflowX: "auto",
    padding: "10px 16px",
    borderBottom: "1px solid var(--border)",
    flexShrink: 0,
  },
  phaseStrip: {
    display: "flex",
    gap: 4,
    minWidth: "max-content",
  },
  phasePill: {
    padding: "3px 8px",
    borderRadius: 6,
    fontSize: "0.65rem",
    fontWeight: 500,
    letterSpacing: "0.01em",
    whiteSpace: "nowrap" as const,
    cursor: "default",
  },
  detailBody: {
    flex: 1,
    overflowY: "auto",
    padding: "12px 16px",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  sectionLabel: {
    fontSize: "0.72rem",
    fontWeight: 700,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  sectionText: {
    fontSize: "0.845rem",
    color: "var(--ink)",
    lineHeight: 1.6,
    margin: 0,
  },
  criteriaList: {
    listStyle: "none",
    padding: 0,
    margin: 0,
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  criteriaItem: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    fontSize: "0.845rem",
  },
  checkBox: {
    flexShrink: 0,
    color: "var(--muted)",
    fontSize: "0.9rem",
  },
  detailActions: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "10px 16px",
    borderTop: "1px solid var(--border)",
    flexShrink: 0,
    flexWrap: "wrap" as const,
  },
  dispatchBtn: {
    height: 32,
    padding: "0 14px",
    fontSize: "0.8rem",
    background: "var(--indigo-9)",
    border: "1px solid var(--indigo-9)",
    borderRadius: 6,
    color: "#fff",
    cursor: "pointer",
    fontWeight: 600,
  },
  transitionGroup: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  transitionBtn: {
    height: 32,
    padding: "0 14px",
    fontSize: "0.8rem",
    background: "var(--gray-a2)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    color: "var(--ink)",
    cursor: "pointer",
  },
  transitionSelect: {
    height: 32,
    padding: "0 8px",
    fontSize: "0.78rem",
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    color: "var(--ink)",
  },
  transitionConfirmBtn: {
    height: 32,
    padding: "0 12px",
    fontSize: "0.78rem",
    background: "var(--gray-12)",
    border: "1px solid var(--gray-12)",
    borderRadius: 6,
    color: "var(--color-background)",
    cursor: "pointer",
    fontWeight: 600,
  },
  cancelBtn: {
    height: 32,
    padding: "0 10px",
    fontSize: "0.78rem",
    background: "var(--gray-a2)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    color: "var(--muted)",
    cursor: "pointer",
  },
};
