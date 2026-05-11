import type { BrainstormResearchFinding } from "../apiClient";

const typeIcon: Record<string, string> = {
  codebase: "↳",
  risk: "⚠",
  pattern: "◈",
  reference: "→",
};

interface ResearchPanelProps {
  findings: BrainstormResearchFinding[];
}

export default function ResearchPanel({ findings }: ResearchPanelProps) {
  if (findings.length === 0) {
    return (
      <div style={{ fontSize: "0.78rem", color: "var(--muted)", padding: "8px 0" }}>
        Researching…
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {findings.map((f, idx) => (
        <div
          key={idx}
          style={{
            fontSize: "0.75rem",
            padding: "6px 10px",
            borderRadius: "var(--radius-sm)",
            background: "var(--canvas)",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", gap: 6, alignItems: "baseline", marginBottom: 2 }}>
            <span style={{ color: "var(--accent)", fontWeight: 600 }}>
              {typeIcon[f.type] ?? "·"} {f.agent}
            </span>
            <span style={{ color: "var(--faint)", fontSize: "0.68rem" }}>{f.type}</span>
          </div>
          <div style={{ color: "var(--ink)" }}>{f.summary}</div>
          {f.refs && f.refs.length > 0 && (
            <div style={{ marginTop: 3, display: "flex", gap: 4, flexWrap: "wrap" }}>
              {f.refs.map((ref, i) => (
                <code
                  key={i}
                  style={{
                    fontSize: "0.68rem",
                    padding: "1px 5px",
                    background: "var(--border)",
                    borderRadius: 3,
                    color: "var(--muted)",
                  }}
                >
                  {ref}
                </code>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
