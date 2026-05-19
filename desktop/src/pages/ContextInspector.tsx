import { useEffect, useMemo, useState } from "react";

import {
  getContextBundles,
  getKnowledgeCenter,
  getSarathiApiConfig,
  type ContextBundleDetail,
  type ContextBundlesData,
  type KnowledgeCenterSummary,
} from "../apiClient";
import { Card, Pill } from "../components/ui";

interface ContextInspectorProps {
  workspaceId: string | null;
}

const mockBundles: ContextBundlesData = {
  workspace_id: "",
  bundles: [
    {
      dispatch_id: "dispatch-1",
      task_id: "task-1",
      agent: "Pravaha",
      status: "completed",
      created_at: new Date().toISOString(),
      context_pack: {
        role: "Pravaha",
        phase: "TaskTracking",
        summary: "Implement a bounded work unit using a compiled context pack.",
        agent_input: {
          objective: "Implement the scoped work.",
          constraints: ["Use compact context, not transcripts."],
          acceptance_criteria: ["Implementation is complete."],
          relevant_files: ["src/service/__init__.py"],
          prior_findings: [],
          available_tools: ["edit", "test"],
          token_budget: 3200,
        },
        estimated_tokens: 1480,
        trimmed_sections: [],
        source_artifacts: [{ type: "task_packet", ref: "task-1" }],
      },
      agent_output: {
        status: "completed",
        summary: "Scoped implementation completed.",
        artifacts: ["files_changed:1", "tests_run:1"],
        decisions: ["provider:codex"],
        findings: [],
        next_recommended_agent: "Nirnaya",
      },
      artifact_index: {
        files_changed: ["src/service/__init__.py"],
        tests_run: ["pytest tests/test_service_api.py"],
        known_risks: [],
        review_findings: [],
      },
      provenance: {
        sources: ["context_pack", "agent_output", "artifact_index"],
      },
    },
  ],
};

function prettyDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function ContextInspector({ workspaceId }: ContextInspectorProps) {
  const [bundlesData, setBundlesData] = useState<ContextBundlesData | null>(null);
  const [selectedDispatchId, setSelectedDispatchId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("Loading compiled context bundles.");
  const [guidance, setGuidance] = useState<KnowledgeCenterSummary["context_compiler_guidance"]>([]);
  const apiConfigured = getSarathiApiConfig() !== null;

  useEffect(() => {
    if (!workspaceId) {
      setBundlesData(null);
      setSelectedDispatchId(null);
      setLoading(false);
      setStatus("Select a workspace to inspect compiled context bundles.");
      return;
    }
    if (!apiConfigured) {
      setBundlesData(mockBundles);
      setSelectedDispatchId(mockBundles.bundles[0]?.dispatch_id ?? null);
      setLoading(false);
      setStatus("Demo context bundles. Connect the Sarathi service for persisted dispatch metadata.");
      return;
    }
    setLoading(true);
    getContextBundles(workspaceId)
      .then((next) => {
        setBundlesData(next);
        setSelectedDispatchId(next.bundles[0]?.dispatch_id ?? null);
        setStatus(`${next.bundles.length} compiled context bundle${next.bundles.length === 1 ? "" : "s"} loaded.`);
      })
      .catch((error) => {
        setBundlesData(null);
        setSelectedDispatchId(null);
        setStatus(error instanceof Error ? error.message : "Context bundle load failed.");
      })
      .finally(() => setLoading(false));

    getKnowledgeCenter(workspaceId)
      .then((kc) => {
        setGuidance(kc.context_compiler_guidance ?? []);
      })
      .catch(() => {
        setGuidance([]);
      });
  }, [workspaceId, apiConfigured]);

  const selectedBundle = useMemo<ContextBundleDetail | null>(() => {
    return bundlesData?.bundles.find((bundle) => bundle.dispatch_id === selectedDispatchId) ?? null;
  }, [bundlesData, selectedDispatchId]);

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>Loading context bundles...</div>;
  }

  if (!bundlesData) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>{status}</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", height: "100%", overflow: "hidden" }}>
      <aside style={{ borderRight: "1px solid var(--border)", padding: 16, overflow: "auto" }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: "0.86rem", margin: 0, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Context bundles
          </h3>
          <p style={{ margin: "6px 0 0", fontSize: "0.72rem", color: "var(--faint)" }}>{status}</p>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {bundlesData.bundles.map((bundle) => {
            const selected = bundle.dispatch_id === selectedDispatchId;
            return (
              <button
                key={bundle.dispatch_id}
                onClick={() => setSelectedDispatchId(bundle.dispatch_id)}
                style={{
                  textAlign: "left",
                  padding: "10px 12px",
                  background: selected ? "var(--accent-bg)" : "var(--surface)",
                  border: "1px solid",
                  borderColor: selected ? "var(--accent)" : "var(--border)",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: "0.8rem", fontWeight: 500 }}>{bundle.agent}</span>
                  <Pill tone={bundle.status === "completed" ? "healthy" : bundle.status === "in_progress" ? "active" : "draft"}>
                    {bundle.status}
                  </Pill>
                </div>
                <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{bundle.task_id}</div>
                <div style={{ marginTop: 3, fontSize: "0.7rem", color: "var(--faint)" }}>{prettyDate(bundle.created_at)}</div>
              </button>
            );
          })}
        </div>
        {bundlesData.bundles.length === 0 && (
          <p style={{ fontSize: "0.78rem", color: "var(--muted)" }}>No compiled context bundles found.</p>
        )}
      </aside>

      <main style={{ padding: 20, overflow: "auto" }}>
        {(guidance?.length ?? 0) > 0 && (
          <Card style={{ padding: 14, marginBottom: 16, background: "var(--surface-elevated)", borderColor: "var(--green)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <strong style={{ fontSize: "0.86rem", color: "var(--green)" }}>Context compiler guidance</strong>
              <Pill tone="healthy">{guidance?.length ?? 0} rules</Pill>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {(guidance ?? []).slice(0, 3).map((rule, idx) => (
                <div key={idx} style={{ fontSize: "0.76rem", padding: "8px 10px", background: "var(--surface)", borderRadius: "var(--radius-sm)" }}>
                  <div style={{ fontWeight: 500, marginBottom: 2 }}>{rule.title}</div>
                  <div style={{ color: "var(--muted)" }}>{rule.suggested_change}</div>
                </div>
              ))}
              {(guidance?.length ?? 0) > 3 && (
                <div style={{ fontSize: "0.72rem", color: "var(--faint)" }}>...and {(guidance?.length ?? 0) - 3} more guidance rules</div>
              )}
            </div>
          </Card>
        )}
        {selectedBundle ? (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h2 style={{ margin: 0, fontSize: "1.12rem" }}>{selectedBundle.agent} context pack</h2>
              <Pill tone="draft">{selectedBundle.context_pack.phase}</Pill>
              <Pill tone={selectedBundle.status === "completed" ? "healthy" : selectedBundle.status === "in_progress" ? "active" : "draft"}>
                {selectedBundle.status}
              </Pill>
            </div>

            <Card style={{ padding: 16 }}>
              <strong>Objective</strong>
              <p style={{ margin: "8px 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
                {selectedBundle.context_pack.agent_input.objective || "No compiled objective was recorded."}
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                <Pill tone="active">{selectedBundle.context_pack.estimated_tokens ?? "?"} est. tokens</Pill>
                <Pill tone="draft">{selectedBundle.context_pack.agent_input.token_budget ?? "?"} budget</Pill>
                <Pill tone="draft">{selectedBundle.context_pack.source_artifacts.length} sources</Pill>
              </div>
            </Card>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Card style={{ padding: 16 }}>
                <strong>Constraints</strong>
                <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: "0.8rem", color: "var(--muted)" }}>
                  {selectedBundle.context_pack.agent_input.constraints.length > 0
                    ? selectedBundle.context_pack.agent_input.constraints.map((item) => <li key={item}>{item}</li>)
                    : <li>No explicit constraints recorded.</li>}
                </ul>
              </Card>

              <Card style={{ padding: 16 }}>
                <strong>Acceptance criteria</strong>
                <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: "0.8rem", color: "var(--muted)" }}>
                  {selectedBundle.context_pack.agent_input.acceptance_criteria.length > 0
                    ? selectedBundle.context_pack.agent_input.acceptance_criteria.map((item) => <li key={item}>{item}</li>)
                    : <li>No acceptance criteria were compiled for this dispatch.</li>}
                </ul>
              </Card>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Card style={{ padding: 16 }}>
                <strong>Relevant files</strong>
                <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                  {selectedBundle.context_pack.agent_input.relevant_files.length > 0
                    ? selectedBundle.context_pack.agent_input.relevant_files.map((item) => (
                        <span key={item} style={{ fontSize: "0.78rem", color: "var(--muted)" }}>{item}</span>
                      ))
                    : <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>No relevant files were compiled.</span>}
                </div>
              </Card>

              <Card style={{ padding: 16 }}>
                <strong>Source artifacts</strong>
                <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                  {selectedBundle.context_pack.source_artifacts.length > 0
                    ? selectedBundle.context_pack.source_artifacts.map((artifact, index) => (
                        <span key={`${artifact.type}-${artifact.ref}-${index}`} style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                          {artifact.type}: {artifact.ref}
                        </span>
                      ))
                    : <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>No source artifacts recorded.</span>}
                </div>
              </Card>
            </div>

            <Card style={{ padding: 16 }}>
              <strong>Normalized output</strong>
              <p style={{ margin: "8px 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
                {selectedBundle.agent_output.summary || "No normalized summary recorded."}
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
                <div>
                  <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Decisions</div>
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: "0.8rem", color: "var(--muted)" }}>
                    {selectedBundle.agent_output.decisions.length > 0
                      ? selectedBundle.agent_output.decisions.map((item) => <li key={item}>{item}</li>)
                      : <li>No normalized decision trace.</li>}
                  </ul>
                </div>
                <div>
                  <div style={{ fontSize: "0.74rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Findings</div>
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: "0.8rem", color: "var(--muted)" }}>
                    {selectedBundle.agent_output.findings.length > 0
                      ? selectedBundle.agent_output.findings.map((item) => <li key={item}>{item}</li>)
                      : <li>No normalized findings.</li>}
                  </ul>
                </div>
              </div>
            </Card>

            <Card style={{ padding: 16 }}>
              <strong>Artifact index and provenance</strong>
              <div style={{ display: "grid", gap: 10, marginTop: 10, fontSize: "0.8rem", color: "var(--muted)" }}>
                <div>Files changed: {selectedBundle.artifact_index.files_changed.length || 0}</div>
                <div>Tests run: {selectedBundle.artifact_index.tests_run.length || 0}</div>
                <div>Known risks: {selectedBundle.artifact_index.known_risks.length || 0}</div>
                <div>Review findings: {selectedBundle.artifact_index.review_findings.length || 0}</div>
                <div>Trace sources: {selectedBundle.provenance.sources.join(", ") || "none"}</div>
                {selectedBundle.context_pack.trimmed_sections.length > 0 && (
                  <div>Trimmed sections: {selectedBundle.context_pack.trimmed_sections.join(", ")}</div>
                )}
              </div>
            </Card>
          </div>
        ) : (
          <p style={{ color: "var(--muted)" }}>Select a context bundle to inspect its compiled contents.</p>
        )}
      </main>
    </div>
  );
}
