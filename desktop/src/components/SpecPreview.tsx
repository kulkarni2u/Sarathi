interface SpecPreviewProps {
  content: string | null;
  onApprove: () => void;
  onExport: () => void;
  approving: boolean;
  approved: boolean;
}

function markdownToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[^<]*<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/\n\n+/g, "</p><p>")
    .trim();
}

export default function SpecPreview({ content, onApprove, onExport, approving, approved }: SpecPreviewProps) {
  const html = content ? markdownToHtml(content) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1, overflow: "auto", paddingBottom: 16 }}>
        {html ? (
          <div
            style={{ fontSize: "0.82rem", lineHeight: 1.6, color: "var(--ink)" }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
            Spec will appear here as the dialogue progresses…
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
        <button
          onClick={onExport}
          disabled={!content || approved}
          style={{ fontSize: "0.75rem", padding: "4px 10px" }}
        >
          Export spec
        </button>
        <button
          className="btn-primary"
          onClick={onApprove}
          disabled={!content || approving || approved}
          style={{ fontSize: "0.75rem", padding: "4px 12px", marginLeft: "auto" }}
        >
          {approved ? "Approved ✓" : approving ? "Approving…" : "Approve →"}
        </button>
      </div>
    </div>
  );
}
