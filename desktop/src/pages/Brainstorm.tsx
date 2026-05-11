import { useEffect, useRef, useState } from "react";
import {
  addBrainstormTurn,
  approveBrainstormSession,
  getBrainstormSession,
  getEventsStreamUrl,
  type BrainstormSession,
} from "../apiClient";
import BrainstormChat from "../components/BrainstormChat";
import ResearchPanel from "../components/ResearchPanel";
import SpecPreview from "../components/SpecPreview";

interface BrainstormProps {
  sessionId: string;
  workspaceId: string | null;
  onApproved: (taskId: string) => void;
}

export default function Brainstorm({ sessionId, workspaceId, onApproved }: BrainstormProps) {
  const [session, setSession] = useState<BrainstormSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const sseRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBrainstormSession(sessionId)
      .then((s) => { if (!cancelled) { setSession(s); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    const url = workspaceId ? getEventsStreamUrl(workspaceId) : null;
    if (!url) return;
    const es = new EventSource(url);
    sseRef.current = es;
    es.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data) as { event_type?: string };
        const type = payload.event_type ?? "";
        if (
          type === "brainstorm.turn_added" ||
          type === "brainstorm.research_added" ||
          type === "brainstorm.spec_updated" ||
          type === "brainstorm.approved"
        ) {
          getBrainstormSession(sessionId).then(setSession).catch(() => null);
        }
      } catch {
        // ignore parse errors
      }
    };
    return () => { es.close(); };
  }, [sessionId, workspaceId]);

  async function handleUserTurn(content: string, selected?: string) {
    if (!session) return;
    const updated = await addBrainstormTurn(sessionId, {
      role: "user",
      content,
      selected: selected ?? null,
    });
    setSession(updated);
  }

  async function handleApprove() {
    if (!session) return;
    setApproving(true);
    try {
      const result = await approveBrainstormSession(sessionId);
      setSession(result.session);
      onApproved(result.task.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setApproving(false);
    }
  }

  function handleExport() {
    if (!session?.spec_content) return;
    const blob = new Blob([session.spec_content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${session.title.toLowerCase().replace(/\s+/g, "-")}-spec.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <div style={{ padding: 32, color: "var(--muted)" }}>Loading brainstorm session…</div>;
  if (error || !session) return <div style={{ padding: 32, color: "var(--red)" }}>{error ?? "Session not found"}</div>;

  const approved = session.status === "approved";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 12, padding: "12px 20px",
        borderBottom: "1px solid var(--border)", background: "var(--surface)", flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: "0.68rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Brainstorm · phase 1 of 12
          </div>
          <div style={{ fontSize: "1rem", fontWeight: 600, color: "var(--ink)" }}>{session.title}</div>
        </div>
        {session.provider && (
          <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "var(--muted)" }}>
            provider: {session.provider}
          </span>
        )}
        {approved && (
          <span style={{
            fontSize: "0.72rem", color: "var(--green)", background: "rgba(34,197,94,0.1)",
            padding: "2px 8px", borderRadius: 4, fontWeight: 600,
          }}>
            Approved
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", flex: 1, overflow: "hidden" }}>
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 16,
          borderRight: "1px solid var(--border)", overflow: "auto",
        }}>
          {session.research_findings.length > 0 && (
            <div>
              <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                Research
              </div>
              <ResearchPanel findings={session.research_findings} />
            </div>
          )}
          <div style={{ flex: 1, minHeight: 0 }}>
            <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
              Dialogue
            </div>
            <BrainstormChat
              turns={session.dialogue_turns}
              onUserTurn={handleUserTurn}
              disabled={approved}
            />
          </div>
        </div>

        <div style={{ padding: 16, overflow: "auto", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Spec (live)
          </div>
          <SpecPreview
            content={session.spec_content}
            onApprove={() => void handleApprove()}
            onExport={handleExport}
            approving={approving}
            approved={approved}
          />
        </div>
      </div>
    </div>
  );
}
