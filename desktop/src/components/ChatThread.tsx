import { useState, useRef, useEffect } from "react";
import type { MessageRecord, ApprovalGateRecord } from "../apiClient";
import { approveTaskGate, getSarathiApiConfig, sendTaskMessage } from "../apiClient";
import { Pill } from "./ui";

interface ChatThreadProps {
  taskId: string | null;
  messages: MessageRecord[];
  approvalGates: ApprovalGateRecord[];
  onAction: () => void;
}

function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function getAgentName(msg: MessageRecord): string {
  if (msg.role === "user") return "You";
  if (msg.role === "assistant") return "Sarathi";
  const agent = msg.metadata?.agent;
  if (typeof agent === "string" && agent) return agent;
  return "Agent";
}

export default function ChatThread({ taskId, messages, approvalGates, onAction }: ChatThreadProps) {
  const [input, setInput] = useState("");
  const [localMessages, setLocalMessages] = useState<MessageRecord[]>([]);
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const apiConfigured = getSarathiApiConfig() !== null;

  const allMessages = [...messages, ...localMessages].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  const pendingGates = approvalGates.filter((g) => g.status === "pending");

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allMessages.length]);

  async function handleSend() {
    const content = input.trim();
    if (!content || !taskId) return;
    setInput("");
    setSending(true);
    try {
      if (apiConfigured) {
        await sendTaskMessage(taskId, content);
        onAction();
      } else {
        const fakeMsg: MessageRecord = {
          id: `local-${Date.now()}`,
          task_id: taskId,
          workspace_id: "",
          role: "user",
          content,
          metadata: {},
          created_at: new Date().toISOString(),
        };
        setLocalMessages((prev) => [...prev, fakeMsg]);
      }
    } catch (err) {
      console.error("Failed to send message:", err);
    } finally {
      setSending(false);
    }
  }

  async function handleApprove(gate: ApprovalGateRecord) {
    if (!taskId) return;
    try {
      await approveTaskGate(taskId, gate.name, "approved");
      onAction();
    } catch (err) {
      console.error("Failed to approve gate:", err);
    }
  }

  return (
    <div style={styles.root}>
      {/* Messages area */}
      <div style={styles.messageArea}>
        {allMessages.length === 0 && (
          <div style={styles.emptyState}>
            <p style={{ color: "var(--muted)", fontSize: "0.845rem" }}>
              No messages yet. Send a message to Sarathi to get started.
            </p>
          </div>
        )}
        {allMessages.map((msg) => {
          const isUser = msg.role === "user";
          const isAssistant = msg.role === "assistant";
          const agentName = getAgentName(msg);

          return (
            <div key={msg.id} style={{ ...styles.msgWrapper, justifyContent: isUser ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: "78%", display: "flex", flexDirection: "column", gap: 4, alignItems: isUser ? "flex-end" : "flex-start" }}>
                {/* Sender label */}
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {!isUser && (
                    <div style={{
                      ...styles.senderMark,
                      background: isAssistant ? "linear-gradient(135deg, #6366F1, #8B5CF6)" : "var(--gray-a4)",
                      color: isAssistant ? "#fff" : "var(--muted)",
                    }}>
                      {isAssistant ? "S" : agentName[0]?.toUpperCase() ?? "A"}
                    </div>
                  )}
                  <span style={styles.senderLabel}>{agentName}</span>
                  <span style={styles.timeLabel}>{formatTime(msg.created_at)}</span>
                </div>
                {/* Bubble */}
                <div style={{
                  ...styles.bubble,
                  background: isUser
                    ? "var(--accent-a3)"
                    : isAssistant
                    ? "var(--gray-a2)"
                    : "var(--gray-a3)",
                  border: isUser
                    ? "1px solid var(--accent-a5)"
                    : "1px solid var(--border)",
                }}>
                  <p style={styles.bubbleText}>{msg.content}</p>
                </div>
              </div>
            </div>
          );
        })}

        {/* Pending approval gate actions */}
        {pendingGates.length > 0 && (
          <div style={styles.gateArea}>
            {pendingGates.map((gate) => (
              <div key={gate.id} style={styles.gateCard}>
                <div style={styles.gateHeader}>
                  <Pill tone="warning">{gate.status}</Pill>
                  <span style={styles.gateName}>{gate.name}</span>
                </div>
                <div style={styles.gateActions}>
                  <button
                    style={styles.approveBtn}
                    onClick={() => void handleApprove(gate)}
                  >
                    Approve
                  </button>
                  <button style={styles.viewBtn}>View</button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div style={styles.inputBar}>
        <div style={styles.roleTag}>
          <span style={styles.roleLabel}>You</span>
          <span style={{ color: "var(--muted)", fontSize: "0.72rem" }}>▾</span>
        </div>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void handleSend(); } }}
          placeholder="Type a message to Sarathi..."
          disabled={sending || !taskId}
        />
        <button
          style={{ ...styles.sendBtn, opacity: (!input.trim() || !taskId) ? 0.5 : 1 }}
          onClick={() => void handleSend()}
          disabled={sending || !input.trim() || !taskId}
        >
          {sending ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minHeight: 0,
  },
  messageArea: {
    flex: 1,
    overflowY: "auto",
    padding: "16px",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  emptyState: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flex: 1,
    padding: "32px 0",
  },
  msgWrapper: {
    display: "flex",
    width: "100%",
  },
  senderMark: {
    display: "grid",
    placeItems: "center",
    width: 22,
    height: 22,
    borderRadius: "50%",
    fontSize: "0.65rem",
    fontWeight: 700,
    flexShrink: 0,
  },
  senderLabel: {
    fontSize: "0.75rem",
    fontWeight: 600,
    color: "var(--ink)",
  },
  timeLabel: {
    fontSize: "0.68rem",
    color: "var(--muted)",
  },
  bubble: {
    padding: "10px 14px",
    borderRadius: 8,
    maxWidth: "100%",
  },
  bubbleText: {
    margin: 0,
    fontSize: "0.855rem",
    lineHeight: 1.6,
    color: "var(--ink)",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  gateArea: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    marginTop: 8,
  },
  gateCard: {
    padding: "10px 12px",
    border: "1px solid var(--border)",
    borderRadius: 8,
    background: "var(--surface)",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  gateHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flex: 1,
    minWidth: 0,
  },
  gateName: {
    fontSize: "0.83rem",
    fontWeight: 500,
    color: "var(--ink)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  gateActions: {
    display: "flex",
    gap: 6,
    flexShrink: 0,
  },
  approveBtn: {
    height: 30,
    padding: "0 12px",
    fontSize: "0.78rem",
    background: "var(--green-9)",
    border: "1px solid var(--green-9)",
    borderRadius: 6,
    color: "#fff",
    cursor: "pointer",
    fontWeight: 600,
  },
  viewBtn: {
    height: 30,
    padding: "0 12px",
    fontSize: "0.78rem",
    background: "var(--gray-a2)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    color: "var(--muted)",
    cursor: "pointer",
  },
  inputBar: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "10px 16px",
    borderTop: "1px solid var(--border)",
    background: "var(--surface)",
    flexShrink: 0,
  },
  roleTag: {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "0 8px",
    height: 34,
    border: "1px solid var(--border)",
    borderRadius: 6,
    background: "var(--hover)",
    cursor: "default",
    flexShrink: 0,
  },
  roleLabel: {
    fontSize: "0.8rem",
    fontWeight: 500,
    color: "var(--ink)",
  },
  input: {
    flex: 1,
    height: 34,
    padding: "0 10px",
    border: "1px solid var(--border)",
    borderRadius: 6,
    background: "var(--hover)",
    color: "var(--ink)",
    fontSize: "0.83rem",
    outline: "none",
    minWidth: 0,
  },
  sendBtn: {
    height: 34,
    padding: "0 14px",
    border: "1px solid var(--gray-a6)",
    borderRadius: 6,
    background: "var(--gray-12)",
    color: "var(--color-background)",
    fontSize: "0.83rem",
    fontWeight: 600,
    cursor: "pointer",
    flexShrink: 0,
    letterSpacing: "-0.01em",
  },
};
