import { useState } from "react";
import type { BrainstormTurn } from "../apiClient";

interface BrainstormChatProps {
  turns: BrainstormTurn[];
  onUserTurn: (content: string, selected?: string) => Promise<void>;
  disabled: boolean;
}

export default function BrainstormChat({ turns, onUserTurn, disabled }: BrainstormChatProps) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const lastSarathiTurn = [...turns].reverse().find((t) => t.role === "sarathi");

  async function handleSubmit(selected?: string) {
    const content = selected ?? input.trim();
    if (!content) return;
    setSubmitting(true);
    try {
      await onUserTurn(content, selected);
      setInput("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 12 }}>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {turns.map((turn, idx) => (
          <div
            key={idx}
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius-sm)",
              background: turn.role === "sarathi" ? "var(--canvas)" : "var(--accent)",
              alignSelf: turn.role === "sarathi" ? "flex-start" : "flex-end",
              maxWidth: "85%",
              fontSize: "0.82rem",
              color: turn.role === "sarathi" ? "var(--ink)" : "#fff",
              border: turn.role === "sarathi" ? "1px solid var(--border)" : "none",
            }}
          >
            {turn.role === "sarathi" && (
              <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginBottom: 4, fontWeight: 600 }}>
                Sarathi
              </div>
            )}
            <div>{turn.content}</div>
            {turn.selected && (
              <div style={{ marginTop: 4, fontSize: "0.7rem", opacity: 0.75 }}>
                ✓ {turn.selected}
              </div>
            )}
          </div>
        ))}
      </div>

      {lastSarathiTurn?.options && lastSarathiTurn.options.length > 0 && !disabled && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {lastSarathiTurn.options.map((opt, i) => (
            <button
              key={i}
              onClick={() => void handleSubmit(opt)}
              disabled={submitting}
              style={{
                textAlign: "left",
                padding: "6px 12px",
                fontSize: "0.8rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--surface)",
              }}
            >
              {String.fromCharCode(65 + i)}. {opt}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <input
          style={{
            flex: 1,
            padding: "7px 10px",
            fontSize: "0.82rem",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
          }}
          placeholder={disabled ? "Approved" : "Type your answer…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled || submitting}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
        />
        <button
          onClick={() => void handleSubmit()}
          disabled={!input.trim() || submitting || disabled}
          style={{ padding: "7px 14px", fontSize: "0.82rem" }}
        >
          {submitting ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
