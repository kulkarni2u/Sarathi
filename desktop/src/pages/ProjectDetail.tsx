import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  activeSavedViewFromReuseKit,
  approveTaskGate,
  approveRepositoryAction,
  createTaskGraphDraft,
  createTaskHandoff,
  ensureWorkspace,
  filterTaskDashboardItemsBySavedView,
  getKnowledgeCenter,
  getProposals,
  getSarathiApiConfig,
  getTaskCheckpoint,
  getTaskPanel,
  getTaskStudio,
  getWorkspaceOperationalViews,
  getWorkspaceReuseKit,
  listTaskDashboard,
  listTaskCheckpoints,
  restartTaskFromCheckpoint,
  runTaskReview,
  scheduleTask,
  type DispatchRecord,
  type EvidenceArtifactRecord,
  type KnowledgeCenterSummary,
  type LifecycleEventRecord,
  type CheckpointCapsuleRecord,
  type OperationalViewsSnapshot,
  type PolicyProposal,
  type ReviewRunRecord,
  type SavedViewSnapshot,
  type TaskPanelEntry,
  type TaskDashboardItem,
  type TaskGraphNode,
  type TaskRecord,
  type TaskPanelSnapshot,
  type TaskStudioSnapshot,
  type TaskMetadata,
} from "../apiClient";
import TaskPanelTimeline from "../components/TaskPanelTimeline";
import { Card, Field, PanelTitle, Pill, stateTone } from "../components/ui";
import UnitGraph from "../components/UnitGraph";
import {
  approvalGates as mockApprovalGates,
  events as mockEvents,
  messages as mockMessages,
  roles,
  subtasks,
  tasks,
  workspace,
} from "../mockData";

type ProjectTab = "studio" | "lifecycle" | "history" | "usage";

type ArtifactReviewFinding = {
  message: string;
  severity: string | null;
  provider: string | null;
  filePath: string | null;
  check: string | null;
  acId: string | null;
  criterion: string | null;
  lineStart: number | null;
  lineEnd: number | null;
  confidence: number | null;
  source: string | null;
  excerpt: string | null;
  suggestion: string | null;
  status: string | null;
  header: string | null;
  category: string | null;
};

type ArtifactProvenanceEntry = {
  label: string;
  detail: string;
};

type ArtifactProvenance = {
  filesChanged: ArtifactProvenanceEntry[];
  testsRun: ArtifactProvenanceEntry[];
  knownRisks: ArtifactProvenanceEntry[];
  reviewFindings: ArtifactProvenanceEntry[];
};

type ArtifactSnapshot = {
  filesChanged: string[];
  testsRun: string[];
  knownRisks: string[];
  reviewFindings: ArtifactReviewFinding[];
  provenance: ArtifactProvenance;
};

type ArtifactOverviewModel = ArtifactSnapshot & {
  dispatchCount: number;
  evidenceCount: number;
  dispatchSummaries: {
    id: string;
    agent: string;
    status: string;
    summary: string | null;
    nextAgent: string | null;
    filesChangedCount: number;
    testsRunCount: number;
    reviewFindingsCount: number;
    knownRisksCount: number;
    traceSources: ArtifactProvenanceEntry[];
  }[];
};

type AcceptanceCoverageItem = {
  id: string;
  criterion: string;
  covered: boolean;
};

type CompletionContextModel = {
  filesChanged: string[];
  testsRun: string[];
  findings: string[];
  risks: string[];
  summaries: string[];
  decisions: string[];
};

type DeliverySpineModel = {
  prdProblem: string | null;
  prdGoal: string | null;
  prdScope: string[];
  acceptanceCriteria: string[];
  acCoverage: AcceptanceCoverageItem[];
  coveredCriteriaCount: number;
  latestReviewStatus: string | null;
  handoffReady: boolean;
  repositoryActionStatus: string | null;
  missingItems: string[];
  completionContext: CompletionContextModel | null;
  checkpointReady: boolean;
};

type TaskOriginModel = {
  launchSummary: string | null;
  launchDetail: string | null;
  workflowLineage: string[];
  recommendedViews: string[];
  launchPosture: string[];
};

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asStringList(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item).trim())
    .filter((item) => item.length > 0);
}

function uniqueStrings(values: Iterable<string>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function uniqueProvenance(entries: Iterable<ArtifactProvenanceEntry>): ArtifactProvenanceEntry[] {
  const seen = new Set<string>();
  const result: ArtifactProvenanceEntry[] = [];
  for (const entry of entries) {
    const key = `${entry.label}::${entry.detail}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(entry);
  }
  return result;
}

function findingSeverityTone(value: string | null): string {
  if (!value) return "draft";
  const normalized = value.toLowerCase();
  if (["critical", "major", "error", "failed"].includes(normalized)) return "blocked";
  if (["warning", "minor"].includes(normalized)) return "warning";
  if (["info", "passed", "ok", "success"].includes(normalized)) return "active";
  return "draft";
}

function findingSeverityRank(value: string | null): number {
  if (!value) return 5;
  const normalized = value.toLowerCase();
  if (["critical", "error"].includes(normalized)) return 0;
  if (["major", "warning"].includes(normalized)) return 1;
  if (["minor"].includes(normalized)) return 2;
  if (["info", "passed", "ok", "success"].includes(normalized)) return 3;
  return 4;
}

function formatFindingLocation(finding: ArtifactReviewFinding): string | null {
  if (!finding.filePath) return null;
  const range = finding.lineStart == null
    ? ""
    : finding.lineEnd != null && finding.lineEnd !== finding.lineStart
      ? `:${finding.lineStart}-${finding.lineEnd}`
      : `:${finding.lineStart}`;
  return `${finding.filePath}${range}`;
}

function formatFindingTraceOrigin(value: string | null): ArtifactProvenanceEntry | null {
  if (!value) return null;
  if (value.startsWith("outputs.")) {
    return { label: "Provider output trace", detail: value };
  }
  if (value.startsWith("evidence.")) {
    return { label: "Normalized evidence trace", detail: value };
  }
  if (value.startsWith("artifacts.")) {
    return { label: "Normalized artifact trace", detail: value };
  }
  return { label: "Trace origin", detail: value };
}

function humanizeIdentifier(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function titleCaseWords(value: string): string {
  return value
    .split(/\s+/)
    .filter((part) => part.length > 0)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeAcceptanceCoverage(
  value: unknown,
  acceptanceCriteria: string[],
): AcceptanceCoverageItem[] {
  const coverage = Array.isArray(value) ? value : [];
  const normalized = coverage
    .map((item, index) => {
      const mapped = asObject(item);
      if (!mapped) return null;
      const criterion = typeof mapped.criterion === "string"
        ? mapped.criterion
        : acceptanceCriteria[index] ?? null;
      if (!criterion?.trim()) return null;
      return {
        id: typeof mapped.id === "string" && mapped.id.trim() ? mapped.id.trim() : `AC-${String(index + 1).padStart(2, "0")}`,
        criterion: criterion.trim(),
        covered: Boolean(mapped.covered),
      };
    })
    .filter((item): item is AcceptanceCoverageItem => item !== null);
  if (normalized.length > 0) {
    return normalized;
  }
  return acceptanceCriteria.map((criterion, index) => ({
    id: `AC-${String(index + 1).padStart(2, "0")}`,
    criterion,
    covered: false,
  }));
}

function readCompletionContext(handoffMetadataValue: unknown): CompletionContextModel | null {
  const metadata = asObject(handoffMetadataValue);
  const context = asObject(metadata?.normalized_completion_context);
  if (!context) return null;
  return {
    filesChanged: uniqueStrings(asStringList(context.files_changed)),
    testsRun: uniqueStrings(asStringList(context.tests_run)),
    findings: uniqueStrings(asStringList(context.findings)),
    risks: uniqueStrings(asStringList(context.risks)),
    summaries: uniqueStrings(asStringList(context.summaries)),
    decisions: uniqueStrings(asStringList(context.decisions)),
  };
}

function buildDeliverySpineModel(
  taskMetadata: TaskMetadata,
  latestReview: ReviewRunRecord | null,
  handoff: Record<string, unknown> | null | undefined,
  checkpointReady: boolean,
): DeliverySpineModel {
  const prd = asObject(taskMetadata.prd);
  const acceptanceCriteria = Array.isArray(taskMetadata.acceptance_criteria)
    ? taskMetadata.acceptance_criteria
      .map((item) => String(item).trim())
      .filter((item) => item.length > 0)
    : [];
  const reviewMetadata = asObject(latestReview?.metadata);
  const handoffMetadata = asObject(handoff?.metadata);
  const acCoverage = normalizeAcceptanceCoverage(
    handoffMetadata?.ac_coverage ?? reviewMetadata?.ac_coverage,
    acceptanceCriteria,
  );
  const coveredCriteriaCount = acCoverage.filter((item) => item.covered).length;
  const repositoryAction = asObject(handoffMetadata?.repository_action);
  const missingItems: string[] = [];
  if (!prd?.problem && !prd?.goal) {
    missingItems.push("PRD summary");
  }
  if (acceptanceCriteria.length === 0) {
    missingItems.push("acceptance criteria");
  }
  if (!latestReview || latestReview.status !== "approved") {
    missingItems.push("approved review");
  }
  if (acceptanceCriteria.length > 0 && acCoverage.some((item) => !item.covered)) {
    missingItems.push("full AC coverage");
  }
  if (!handoff) {
    missingItems.push("final handoff");
  }
  return {
    prdProblem: typeof prd?.problem === "string" ? prd.problem : null,
    prdGoal: typeof prd?.goal === "string" ? prd.goal : null,
    prdScope: uniqueStrings(asStringList(prd?.scope)),
    acceptanceCriteria,
    acCoverage,
    coveredCriteriaCount,
    latestReviewStatus: latestReview?.status ?? null,
    handoffReady: Boolean(handoff) && missingItems.length === 0,
    repositoryActionStatus: typeof repositoryAction?.status === "string" ? repositoryAction.status : null,
    missingItems,
    completionContext: readCompletionContext(handoffMetadata),
    checkpointReady,
  };
}

function buildTaskOriginModel(taskMetadata: TaskMetadata): TaskOriginModel | null {
  const reuse = asObject(taskMetadata.reuse);
  const reuseSource = asObject(reuse?.reuse_source);
  const workflowLineage: string[] = [];
  const recommendedViews = uniqueStrings(asStringList(reuse?.recommended_view_ids));
  const launchPosture: string[] = [];
  const githubReference = githubIssueReference(taskMetadata);

  if (reuseSource?.name && typeof reuseSource.name === "string") {
    const kind = typeof reuseSource.kind === "string" && reuseSource.kind.trim()
      ? titleCaseWords(humanizeIdentifier(reuseSource.kind))
      : "Workflow";
    workflowLineage.push(`${kind}: ${reuseSource.name}`);
  }
  if (typeof reuse?.workflow_template_id === "string" && reuse.workflow_template_id.trim()) {
    workflowLineage.push(`Template id: ${reuse.workflow_template_id}`);
  }
  if (typeof reuse?.learning_playbook_id === "string" && reuse.learning_playbook_id.trim()) {
    workflowLineage.push(`Playbook id: ${reuse.learning_playbook_id}`);
  }
  if (typeof reuse?.recommended_repository_action_mode === "string" && reuse.recommended_repository_action_mode.trim()) {
    launchPosture.push(`Repo posture: ${humanizeIdentifier(reuse.recommended_repository_action_mode)}`);
  }
  if (typeof reuse?.recommended_auto_approve_mode === "string" && reuse.recommended_auto_approve_mode.trim()) {
    launchPosture.push(`Auto-approve: ${humanizeIdentifier(reuse.recommended_auto_approve_mode)}`);
  }
  launchPosture.push(
    ...uniqueStrings(asStringList(reuse?.suggested_provider_priority)).map(
      (provider, index) => `${index === 0 ? "Provider priority" : "Fallback"}: ${provider}`,
    ),
  );

  let launchSummary: string | null = null;
  let launchDetail: string | null = null;
  if (githubReference) {
    launchSummary = "Imported GitHub issue";
    launchDetail = githubReference;
  } else if (taskMetadata.source === "brainstorm") {
    launchSummary = "Approved brainstorm session";
    launchDetail = typeof taskMetadata.brainstorm_session_id === "string"
      ? `Session ${taskMetadata.brainstorm_session_id}`
      : "This task was promoted from a brainstorm session.";
  } else if (typeof taskMetadata.source_prompt === "string" && taskMetadata.source_prompt.trim()) {
    launchSummary = "Created from task draft prompt";
    launchDetail = taskMetadata.source_prompt.trim();
  } else if (typeof taskMetadata.source === "string" && taskMetadata.source.trim()) {
    launchSummary = titleCaseWords(humanizeIdentifier(taskMetadata.source));
  }

  if (!launchSummary && workflowLineage.length === 0 && recommendedViews.length === 0 && launchPosture.length === 0) {
    return null;
  }

  return {
    launchSummary,
    launchDetail,
    workflowLineage,
    recommendedViews,
    launchPosture,
  };
}

function normalizeReviewFindings(value: unknown): ArtifactReviewFinding[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const findings: ArtifactReviewFinding[] = [];
  value.forEach((item) => {
    if (typeof item === "string" && item.trim()) {
      findings.push({
        message: item.trim(),
        severity: null,
        provider: null,
        filePath: null,
        check: null,
        acId: null,
        criterion: null,
        lineStart: null,
        lineEnd: null,
        confidence: null,
        source: null,
        excerpt: null,
        suggestion: null,
        status: null,
        header: null,
        category: null,
      });
      return;
    }
    const finding = asObject(item);
    if (!finding) return;
    const message = typeof finding.message === "string"
      ? finding.message
      : typeof finding.summary === "string"
        ? finding.summary
        : typeof finding.finding === "string"
          ? finding.finding
          : null;
    if (!message?.trim()) return;
    findings.push({
      message: message.trim(),
      severity: typeof finding.severity === "string" ? finding.severity : null,
      provider: typeof finding.provider === "string" ? finding.provider : null,
      filePath: typeof finding.file_path === "string" ? finding.file_path : null,
      check: typeof finding.check === "string" ? finding.check : null,
      acId: typeof finding.ac_id === "string" ? finding.ac_id : null,
      criterion: typeof finding.criterion === "string" ? finding.criterion : null,
      lineStart: typeof finding.line_start === "number" ? finding.line_start : null,
      lineEnd: typeof finding.line_end === "number" ? finding.line_end : null,
      confidence: typeof finding.confidence === "number" ? finding.confidence : null,
      source: typeof finding.source === "string" ? finding.source : null,
      excerpt: typeof finding.excerpt === "string" ? finding.excerpt : null,
      suggestion: typeof finding.suggestion === "string" ? finding.suggestion : null,
      status: typeof finding.status === "string" ? finding.status : null,
      header: typeof finding.header === "string" ? finding.header : null,
      category: typeof finding.category === "string" ? finding.category : null,
    });
  });
  return findings;
}

function readArtifactSnapshot(metadataValue: unknown): ArtifactSnapshot {
  const metadata = asObject(metadataValue) ?? {};
  const artifactIndex = asObject(metadata.artifact_index);
  const responseEvidence = asObject(metadata.response_evidence);
  const artifactFilesChanged = asStringList(artifactIndex?.files_changed);
  const fallbackFilesChanged = artifactFilesChanged.length === 0
    ? asStringList(responseEvidence?.changed_files)
    : [];
  const reviewFindings = normalizeReviewFindings(artifactIndex?.review_findings);
  const testsRun = uniqueStrings(asStringList(artifactIndex?.tests_run));
  const knownRisks = uniqueStrings(asStringList(artifactIndex?.known_risks));
  return {
    filesChanged: uniqueStrings(artifactFilesChanged.length > 0 ? artifactFilesChanged : fallbackFilesChanged),
    testsRun,
    knownRisks,
    reviewFindings,
    provenance: {
      filesChanged: artifactFilesChanged.length > 0
        ? [{ label: "Normalized artifact index", detail: "artifact_index.files_changed" }]
        : fallbackFilesChanged.length > 0
          ? [{ label: "Compatibility fallback", detail: "response_evidence.changed_files" }]
          : [],
      testsRun: testsRun.length > 0
        ? [{ label: "Normalized artifact index", detail: "artifact_index.tests_run" }]
        : [],
      knownRisks: knownRisks.length > 0
        ? [{ label: "Normalized artifact index", detail: "artifact_index.known_risks" }]
        : [],
      reviewFindings: reviewFindings.length > 0
        ? [{ label: "Normalized artifact index", detail: "artifact_index.review_findings" }]
        : [],
    },
  };
}

function readDispatchTraceSources(metadataValue: unknown): ArtifactProvenanceEntry[] {
  const metadata = asObject(metadataValue) ?? {};
  const artifactIndex = asObject(metadata.artifact_index);
  const responseEvidence = asObject(metadata.response_evidence);
  const entries: ArtifactProvenanceEntry[] = [];

  if (asObject(metadata.context_pack)) {
    entries.push({ label: "Compiled context pack", detail: "context_pack.agent_input + compilation" });
  }
  if (asObject(metadata.agent_output)) {
    entries.push({ label: "Normalized agent output", detail: "agent_output.summary/findings/decisions" });
  }
  if (artifactIndex) {
    entries.push({ label: "Normalized artifact index", detail: "artifact_index.files_changed/tests_run/review_findings" });
  }
  if (responseEvidence) {
    entries.push({
      label: artifactIndex ? "Raw provider evidence retained" : "Compatibility fallback",
      detail: "response_evidence.*",
    });
  }

  return uniqueProvenance(entries);
}

function buildArtifactOverview(
  evidence: EvidenceArtifactRecord[],
  dispatches: DispatchRecord[],
): ArtifactOverviewModel {
  const allFiles: string[] = [];
  const allTests: string[] = [];
  const allRisks: string[] = [];
  const allFindings: ArtifactReviewFinding[] = [];
  const allProvenance: ArtifactProvenance = {
    filesChanged: [],
    testsRun: [],
    knownRisks: [],
    reviewFindings: [],
  };

  evidence.forEach((item) => {
    const snapshot = readArtifactSnapshot(item.metadata);
    allFiles.push(...snapshot.filesChanged);
    allTests.push(...snapshot.testsRun);
    allRisks.push(...snapshot.knownRisks);
    allFindings.push(...snapshot.reviewFindings);
    allProvenance.filesChanged.push(...snapshot.provenance.filesChanged);
    allProvenance.testsRun.push(...snapshot.provenance.testsRun);
    allProvenance.knownRisks.push(...snapshot.provenance.knownRisks);
    allProvenance.reviewFindings.push(...snapshot.provenance.reviewFindings);
  });

  const dispatchSummaries = dispatches.map((dispatch) => {
    const snapshot = readArtifactSnapshot(dispatch.metadata);
    allFiles.push(...snapshot.filesChanged);
    allTests.push(...snapshot.testsRun);
    allRisks.push(...snapshot.knownRisks);
    allFindings.push(...snapshot.reviewFindings);
    allProvenance.filesChanged.push(...snapshot.provenance.filesChanged);
    allProvenance.testsRun.push(...snapshot.provenance.testsRun);
    allProvenance.knownRisks.push(...snapshot.provenance.knownRisks);
    allProvenance.reviewFindings.push(...snapshot.provenance.reviewFindings);
    const metadata = asObject(dispatch.metadata) ?? {};
    const agentOutput = asObject(metadata.agent_output);
    const summary = typeof agentOutput?.summary === "string" ? agentOutput.summary : null;
    const nextAgent = typeof agentOutput?.next_recommended_agent === "string"
      ? agentOutput.next_recommended_agent
      : null;
    return {
      id: dispatch.id,
      agent: dispatch.agent_name,
      status: dispatch.status,
      summary,
      nextAgent,
      filesChangedCount: snapshot.filesChanged.length,
      testsRunCount: snapshot.testsRun.length,
      reviewFindingsCount: snapshot.reviewFindings.length,
      knownRisksCount: snapshot.knownRisks.length,
      traceSources: readDispatchTraceSources(dispatch.metadata),
    };
  }).filter((item) => {
    return (
      item.summary !== null ||
      item.nextAgent !== null ||
      item.filesChangedCount > 0 ||
      item.testsRunCount > 0 ||
      item.reviewFindingsCount > 0 ||
      item.knownRisksCount > 0 ||
      item.traceSources.length > 0
    );
  });

  const seenMessages = new Set<string>();
  const dedupedFindings: ArtifactReviewFinding[] = [];
  for (const f of allFindings) {
    const key = `${f.message}::${f.severity ?? ""}::${f.filePath ?? ""}::${f.lineStart ?? ""}::${f.lineEnd ?? ""}::${f.check ?? ""}`;
    if (!seenMessages.has(key)) {
      seenMessages.add(key);
      dedupedFindings.push(f);
    }
  }
  dedupedFindings.sort((left, right) => {
    const severityDelta = findingSeverityRank(left.severity) - findingSeverityRank(right.severity);
    if (severityDelta !== 0) return severityDelta;
    return left.message.localeCompare(right.message);
  });

  return {
    filesChanged: uniqueStrings(allFiles),
    testsRun: uniqueStrings(allTests),
    knownRisks: uniqueStrings(allRisks),
    reviewFindings: dedupedFindings,
    provenance: {
      filesChanged: uniqueProvenance(allProvenance.filesChanged),
      testsRun: uniqueProvenance(allProvenance.testsRun),
      knownRisks: uniqueProvenance(allProvenance.knownRisks),
      reviewFindings: uniqueProvenance(allProvenance.reviewFindings),
    },
    dispatchCount: dispatches.length,
    evidenceCount: evidence.length,
    dispatchSummaries,
  };
}

interface Props {
  workspaceId?: string | null;
  projectId?: string | null;
  liveTick?: number;
  selectedTaskId?: string | null;
  setSelectedTaskId?: (id: string | null) => void;
  setRoute?: (route: string) => void;
  onOpenProposal?: (proposalId: string) => void;
  onOpenWorkspace?: (viewId?: string | null) => void;
}

function mockTasksToDashboardItems(): TaskDashboardItem[] {
  const blockedCount = subtasks.filter((unit) => unit.state === "blocked").length;
  return tasks.map((task, index) => ({
    id: task.id,
    workspace_id: workspace.id,
    title: task.title,
    status: task.status === "complete" ? "done" : task.status === "in_progress" ? "in_progress" : "prd_pending",
    phase: task.phase,
    approval_state: task.reviewState,
    graph_state: index === 0 ? "approved" : "pending_approval",
    next_gate: task.status === "complete" ? null : "Task graph",
    node_count: subtasks.length,
    blocked_count: blockedCount,
    review_needed_count: 0,
    checkpoint_state: "none",
    handoff_state: "none",
    roles: Array.from(new Set(subtasks.map((unit) => unit.role))),
    providers: Array.from(new Set(subtasks.map((unit) => unit.provider))),
    updated_at: new Date(Date.now() - index * 6 * 60 * 1000).toISOString(),
  }));
}

function mockTaskToRecord(task: TaskDashboardItem): TaskRecord {
  return {
    id: task.id,
    workspace_id: task.workspace_id,
    title: task.title,
    description: task.title,
    status: task.status === "done" ? "complete" : task.status,
    metadata: {
      source_prompt: task.title,
      complexity: "high",
      phase: task.phase,
      prd: {
        problem: task.title,
        goal: "Restore the task studio route.",
        scope: ["Task selector", "Graph", "Messages", "Lifecycle views"],
      },
      acceptance_criteria: [
        "Selected task loads a task studio snapshot.",
        "Graph, packet, messages, and gates remain visible.",
        "Lifecycle, history, and usage summaries are available.",
      ],
    },
    created_at: task.updated_at,
    updated_at: task.updated_at,
  };
}

function taskRecordToDashboardItem(task: TaskRecord): TaskDashboardItem {
  const metadata = task.metadata ?? {};
  const phase = typeof metadata.phase === "string" ? metadata.phase : "Build";
  const approvalState = task.status === "done" || task.status === "complete"
    ? "approved"
    : task.status === "in_progress"
      ? "in_progress"
      : "draft";
  const nodeCount = typeof metadata.node_count === "number" ? metadata.node_count : 1;
  const blockedCount = typeof metadata.blocked_count === "number" ? metadata.blocked_count : 0;
  const reviewNeededCount = typeof metadata.review_needed_count === "number" ? metadata.review_needed_count : 0;
  const checkpointState = typeof metadata.checkpoint_state === "string" ? metadata.checkpoint_state : "none";
  const handoffState = typeof metadata.handoff_state === "string" ? metadata.handoff_state : "none";
  return {
    id: task.id,
    workspace_id: task.workspace_id,
    title: task.title,
    status: task.status === "complete" ? "done" : task.status,
    phase,
    approval_state: approvalState,
    graph_state: typeof metadata.graph_state === "string" ? metadata.graph_state : "ready",
    next_gate: typeof metadata.next_gate === "string" ? metadata.next_gate : null,
    node_count: nodeCount,
    blocked_count: blockedCount,
    review_needed_count: reviewNeededCount,
    checkpoint_state: checkpointState,
    handoff_state: handoffState,
    roles: Array.isArray(metadata.roles) ? metadata.roles.filter((value): value is string => typeof value === "string") : [],
    providers: Array.isArray(metadata.providers) ? metadata.providers.filter((value): value is string => typeof value === "string") : [],
    updated_at: task.updated_at,
  };
}

function createDemoCheckpoint(
  task: TaskDashboardItem,
  title: string,
  workspaceId: string,
  projectId: string | null,
): CheckpointCapsuleRecord {
  return {
    id: `demo-checkpoint-${task.id}`,
    workspace_id: workspaceId,
    project_id: projectId,
    source_task_id: task.id,
    status: "ready",
    summary: `${title} is ready for a fresh session.`,
    key_decisions: [
      "Keep the task panel compact.",
      "Preserve repository-action defaults across the restart.",
    ],
    evidence_refs: [`task:${task.id}`],
    repository_action_preference: {
      scope: "task",
      mode: "no_action",
      allowed_modes: ["no_action"],
      source: "demo",
    },
    next_start_point: "Start a new session from this checkpoint summary.",
    created_at: new Date().toISOString(),
    created_by: "Sarathi",
  };
}

function subtaskToGraphNode(node: (typeof subtasks)[number]): TaskGraphNode {
  return {
    id: node.id,
    title: node.title,
    status: node.state,
    role: node.role,
    provider: node.provider,
    blocked_by: node.blockedBy,
    evidence_required: node.ac.length > 0 ? node.ac : ["evidence"],
    task_packet: {
      goal: node.goal,
      context: node.context,
      review_criteria: node.ac,
    },
  };
}

function createDemoSnapshot(task: TaskDashboardItem): TaskStudioSnapshot {
  const now = new Date().toISOString();
  const nodes = subtasks.map(subtaskToGraphNode);
  const edges = subtasks.flatMap((unit) => unit.blockedBy.map((blockedBy) => ({
    from: blockedBy,
    to: unit.id,
    type: "blocks",
  })));

  return {
    task: mockTaskToRecord(task),
    graph: {
      task_id: task.id,
      nodes,
      edges,
    },
    header: deriveStudioHeaderFromTask(task),
    messages: mockMessages.map((message, index) => ({
      id: `demo-message-${index + 1}`,
      workspace_id: task.workspace_id,
      task_id: task.id,
      role: message.from.toLowerCase() === "user" ? "user" : "assistant",
      content: message.text,
      metadata: {
        target: message.target,
        gate: message.tag,
        source: "demo",
      },
      created_at: now,
    })),
    approval_gates: mockApprovalGates.map((gate) => ({
      id: gate.id,
      workspace_id: task.workspace_id,
      task_id: task.id,
      name: gate.name,
      status: gate.status,
      metadata: {
        requires_human: gate.status === "waiting_human" || gate.status === "blocked",
      },
      created_at: now,
      updated_at: now,
    })),
    events: mockEvents.map((event, index) => ({
      id: `demo-event-${index + 1}`,
      workspace_id: task.workspace_id,
      task_id: task.id,
      event_type: event.event,
      payload: {
        severity: event.severity,
        message: event.object,
        source: event.source,
      },
      created_at: `${now.slice(0, 10)}T${event.time}:00.000Z`,
    })),
    dispatches: [],
    evidence: [],
    reviews: [],
    handoff: null,
  };
}

function createDemoOperations(): OperationalViewsSnapshot {
  const totalTasks = tasks.length;
  const activeTasks = tasks.filter((task) => task.status === "in_progress").length;
  const doneTasks = tasks.filter((task) => task.status === "complete").length;
  const nodes = subtasks.map(subtaskToGraphNode);
  const edges = subtasks.flatMap((unit) => unit.blockedBy.map((blockedBy) => ({
    from: blockedBy,
    to: unit.id,
    type: "blocks",
  })));

  return {
    workspace_id: workspace.id,
    summary: {
      project_count: 1,
      approvals_pending: mockApprovalGates.filter((gate) => gate.status === "pending" || gate.status === "waiting_human").length,
      checkpoint_ready_count: tasks.filter((task) => task.status === "complete").length,
      handoff_ready_count: 0,
      provider_online_count: roles.filter((role) => role.state === "active" || role.state === "live").length,
    },
    projects: [
      {
        id: "demo-project",
        workspace_id: workspace.id,
        name: "Sarathi Desktop",
        description: "Demo project",
        status: "active",
        task_count: totalTasks,
        blocked_count: subtasks.filter((task) => task.state === "blocked").length,
        review_needed_count: 1,
        approval_pending_count: mockApprovalGates.filter((gate) => gate.status === "pending").length,
        checkpoint_ready_count: tasks.filter((task) => task.status === "complete").length,
        handoff_ready_count: 0,
        updated_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      },
    ],
    inbox: [
      {
        id: "demo-approval",
        kind: "approval",
        workspace_id: workspace.id,
        task_id: tasks[0]?.id ?? null,
        title: tasks[0]?.title ?? "Task graph",
        summary: "Approval needed: Task graph",
        state: "awaiting_approval",
        next_action: "Open task",
        updated_at: new Date().toISOString(),
      },
    ],
    history: mockEvents.map((event, index) => ({
      id: `history-${index + 1}`,
      workspace_id: workspace.id,
      task_id: index < 3 ? tasks[0]?.id ?? null : tasks[1]?.id ?? null,
      event_type: event.event,
      payload: {
        severity: event.severity,
        message: event.object,
        source: event.source,
      },
      created_at: `${new Date().toISOString().slice(0, 10)}T${event.time}:00.000Z`,
    })),
    lifecycle: roles.map((role) => ({
      key: role.name.toLowerCase(),
      name: role.name,
      purpose: role.function,
      description: role.function,
      state: role.state,
      event_count: mockEvents.filter((event) => event.source === role.name).length,
    })),
    diagrams: [
      {
        id: "diagram-task-studio",
        kind: "dependency_graph",
        title: "Task studio dependency graph",
        task_id: tasks[0]?.id,
        nodes,
        edges,
        summary: "Task packet, dependency graph, and selected unit flow.",
        updated_at: new Date().toISOString(),
      },
      {
        id: "diagram-lifecycle",
        kind: "agent_lifecycle",
        title: "Agent lifecycle",
        summary: "Role flow, review loop, and handoff progression.",
        updated_at: new Date().toISOString(),
      },
    ],
    governance: {
      policy_posture: {
        repository_action_preference: { scope: "workspace", mode: "no_action", allowed_modes: ["no_action", "prepare_patch", "commit", "draft_pr", "ready_pr"] },
        auto_approve_preference: { scope: "workspace", mode: "manual_only", allowed_modes: ["manual_only", "below_threshold"] },
        provider_priority: ["claude", "codex", "copilot", "opencode"],
        provider_priority_source: "default",
      },
      provider_routing: {
        priority_order: ["claude", "codex", "copilot", "opencode"],
        selected_provider: "claude",
        fallback_candidates: ["codex", "copilot", "opencode"],
        provider_health: { claude: "online", codex: "online", copilot: "configured_by_user", opencode: "configured_by_user" },
        providers: [
          { id: "claude", name: "Claude", health: "online", auth: "connected", transport_posture: "sdk" },
          { id: "codex", name: "Codex", health: "online", auth: "connected", transport_posture: "sdk" },
          { id: "copilot", name: "Copilot", health: "configured_by_user", auth: "github_auth", transport_posture: "cli_fallback" },
          { id: "opencode", name: "OpenCode", health: "configured_by_user", auth: "workspace_setting", transport_posture: "sdk" },
        ],
      },
      override_history: [
        {
          id: "demo-governance-1",
          event_type: "workspace.governance_updated",
          summary: "Workspace governance updated: repository action and dispatch order.",
          severity: "warning",
          created_at: new Date().toISOString(),
          metadata: {},
        },
      ],
      repository_action_governance: {
        pending_count: 0,
        approved_count: 1,
        recent: [
          {
            id: "demo-handoff-1",
            task_id: tasks[0]?.id ?? "task-1",
            title: tasks[0]?.title ?? "Task studio",
            summary: "Repository action approved for release handoff.",
            status: "approved",
            action: "no_action",
            mode: "no_action",
            created_at: new Date().toISOString(),
          },
        ],
      },
    },
    usage: {
      tasks: { total: totalTasks, active: activeTasks, done: doneTasks, by_status: { in_progress: activeTasks, complete: doneTasks } },
      subtasks: {
        total: subtasks.length,
        by_status: subtasks.reduce<Record<string, number>>((acc, unit) => {
          acc[unit.state] = (acc[unit.state] ?? 0) + 1;
          return acc;
        }, {}),
      },
      events: { total: mockEvents.length, by_type: mockEvents.reduce<Record<string, number>>((acc, event) => {
        acc[event.severity] = (acc[event.severity] ?? 0) + 1;
        return acc;
      }, {}) },
      messages: { total: mockMessages.length, by_role: mockMessages.reduce<Record<string, number>>((acc, message) => {
        acc[message.from] = (acc[message.from] ?? 0) + 1;
        return acc;
      }, {}) },
      repositories: { total: workspace.repos.length },
      dispatches: { total: 0, by_status: {} },
      evidence: { total: 2, by_type: { doc: 1, plan: 1 } },
      reviews: { total: 1, by_status: { pending: 1 } },
      handoffs: { total: 0 },
      providers: {
        total: roles.length,
        online: roles.filter((role) => role.state === "active" || role.state === "live").length,
        by_health: {
          active: roles.filter((role) => role.state === "active").length,
          live: roles.filter((role) => role.state === "live").length,
          idle: roles.filter((role) => role.state === "idle").length,
          queued: roles.filter((role) => role.state === "queued").length,
          waiting: roles.filter((role) => role.state === "waiting").length,
        },
      },
    },
  };
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}m`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`;
  }
  return String(value);
}

function budgetTone(state?: string | null): "healthy" | "warning" | "blocked" | "draft" {
  if (state === "exhausted") return "blocked";
  if (state === "near_limit" || state === "warning") return "warning";
  if (state === "ok") return "healthy";
  return "draft";
}

function snapshotToPanelEntries(
  snapshot: TaskStudioSnapshot,
  taskId: string,
  workspaceId: string,
): TaskPanelEntry[] {
  const messages = snapshot.messages.map((message) => ({
    id: message.id,
    kind: message.role === "user" ? "human_message" : "agent_update",
    source: message.role,
    target: typeof message.metadata.target === "string" ? message.metadata.target : null,
    summary: message.content,
    created_at: message.created_at,
    metadata: message.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  } satisfies TaskPanelEntry));

  const events = snapshot.events.map((event) => {
    const payload = event.payload;
    const kind: TaskPanelEntry["kind"] =
      event.event_type === "task.blocked" ? "blocked" :
      event.event_type === "task.unblocked" ? "unblocked" :
      event.event_type === "task.completed" ? "completion" :
      event.event_type === "approval.requested" || event.event_type === "approval.recorded" ? "review" :
      event.event_type === "subtask.dispatched" ? "claimed" :
      event.event_type === "subtask.scheduled" ? "claimed" :
      event.event_type === "subtask.unblocked" ? "unblocked" :
      event.event_type === "subtask.transitioned" && payload.status === "blocked" ? "blocked" :
      event.event_type === "subtask.transitioned" && payload.status === "complete" ? "completion" :
      event.event_type === "subtask.transitioned" && (payload.status === "review" || payload.status === "waiting_human") ? "review" :
      event.event_type === "subtask.transitioned" && payload.status === "in_progress" ? "in_progress" :
      event.event_type === "task.draft_created" || event.event_type === "task.chat_created" ? "system_note" :
      "system_note";
    const source = typeof payload.actor === "string"
      ? payload.actor
      : typeof payload.agent === "string"
        ? payload.agent
        : typeof payload.provider === "string"
          ? payload.provider
          : typeof payload.name === "string"
            ? payload.name
            : event.event_type;
    const target = typeof payload.object_id === "string"
      ? payload.object_id
      : typeof payload.subtask_id === "string"
        ? payload.subtask_id
        : typeof payload.dispatch_id === "string"
          ? payload.dispatch_id
          : typeof payload.status === "string"
            ? payload.status
            : typeof payload.name === "string"
              ? payload.name
              : null;
    const summary =
      event.event_type === "task.blocked" ? `Task blocked: ${String(payload.reason ?? payload.message ?? "blocked")}` :
      event.event_type === "task.unblocked" ? "Task unblocked" :
      event.event_type === "task.completed" ? "Task completed" :
      event.event_type === "approval.requested" ? `Approval requested for ${String(payload.name ?? "gate")}` :
      event.event_type === "approval.recorded" ? `Approval recorded: ${String(payload.status ?? "updated")}` :
      event.event_type === "subtask.scheduled" ? `${String(payload.role ?? payload.provider ?? "subtask")} scheduled` :
      event.event_type === "subtask.dispatched" ? `Dispatch recorded for ${String(payload.object_id ?? "subtask")}` :
      event.event_type === "subtask.unblocked" ? `Unblocked ${String(payload.object_id ?? "subtask")}` :
      event.event_type === "subtask.transitioned" ? `${String(payload.actor ?? "Subtask")} → ${String(payload.status ?? "updated")}` :
      event.event_type === "task.draft_created" ? "Task draft created" :
      event.event_type === "task.chat_created" ? "Task inception chat created a draft" :
      event.event_type === "review.completed" ? "Review completed" :
      event.event_type === "review.rejected" ? "Review rejected" :
      event.event_type.replace(".", " ");
    return {
      id: event.id,
      kind,
      source,
      target,
      summary,
      created_at: event.created_at,
      metadata: payload,
      task_id: taskId,
      workspace_id: workspaceId,
    } satisfies TaskPanelEntry;
  });

  const gates = snapshot.approval_gates.map((gate) => ({
    id: gate.id,
    kind: "review" as const,
    source: gate.name,
    target: gate.status,
    summary: `${gate.name} gate ${gate.status}`,
    created_at: gate.created_at,
    metadata: gate.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const dispatches = snapshot.dispatches.map((dispatch) => ({
    id: dispatch.id,
    kind: dispatch.status === "failed" ? "blocked" : dispatch.status === "review" ? "review" : dispatch.status === "in_progress" ? "in_progress" : "claimed",
    source: dispatch.agent_name,
    target: typeof dispatch.metadata.subtask_id === "string" ? dispatch.metadata.subtask_id : null,
    summary: `${dispatch.agent_name} dispatch ${dispatch.status}`,
    created_at: dispatch.created_at,
    metadata: dispatch.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  } satisfies TaskPanelEntry));

  const evidence = snapshot.evidence.map((item) => ({
    id: item.id,
    kind: "evidence" as const,
    source: item.artifact_type,
    target: item.uri,
    summary: `${item.artifact_type} evidence attached`,
    created_at: item.created_at,
    metadata: item.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const reviews = snapshot.reviews.map((review) => ({
    id: review.id,
    kind: "review" as const,
    source: "review",
    target: review.status,
    summary: review.summary ?? `Review ${review.status}`,
    created_at: review.created_at,
    metadata: review.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const handoff = snapshot.handoff ? [{
    id: snapshot.handoff.id,
    kind: "handoff" as const,
    source: snapshot.handoff.from_agent ?? "handoff",
    target: snapshot.handoff.to_agent,
    summary: snapshot.handoff.summary,
    created_at: snapshot.handoff.created_at,
    metadata: snapshot.handoff.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }] : [];

  return [...messages, ...events, ...gates, ...dispatches, ...evidence, ...reviews, ...handoff]
    .sort((a, b) => (a.created_at === b.created_at ? a.id.localeCompare(b.id) : a.created_at.localeCompare(b.created_at)));
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function historySummary(event: LifecycleEventRecord): string {
  const payload = event.payload as Record<string, unknown>;
  return String(payload.message ?? payload.action ?? payload.summary ?? "workspace event");
}

function repositoryActionLabel(mode: string | undefined): string {
  if (!mode || mode === "no_action") {
    return "No action (default)";
  }
  if (mode === "prepare_patch") return "Prepare patch";
  if (mode === "commit") return "Commit (opt-in)";
  if (mode === "draft_pr") return "Draft PR (opt-in)";
  if (mode === "ready_pr") return "Ready PR (opt-in)";
  return mode.replace(/_/g, " ");
}

function githubIssueReference(metadata: TaskMetadata): string | null {
  const issue = metadata.github_issue;
  if (!issue) return null;
  if (typeof issue.reference === "string" && issue.reference.trim()) {
    return issue.reference;
  }
  if (typeof issue.full_name === "string" && issue.full_name.trim() && typeof issue.number === "number") {
    return `${issue.full_name}#${issue.number}`;
  }
  if (issue.repository && typeof issue.repository === "object") {
    const repository = issue.repository as Record<string, unknown>;
    const fullName = typeof repository.full_name === "string" ? repository.full_name : null;
    if (fullName && typeof issue.number === "number") {
      return `${fullName}#${issue.number}`;
    }
    const workspaceRepositoryName = typeof repository.workspace_repository_name === "string"
      ? repository.workspace_repository_name
      : null;
    if (workspaceRepositoryName && typeof issue.number === "number") {
      return `${workspaceRepositoryName} issue #${issue.number}`;
    }
  }
  if (typeof issue.number === "number") {
    return `GitHub issue #${issue.number}`;
  }
  return null;
}

function nextPendingGate(approvalItems: TaskStudioSnapshot["approval_gates"]) {
  return approvalItems.find((gate) => gate.status === "waiting_human")
    ?? approvalItems.find((gate) => gate.status === "pending")
    ?? null;
}

function deriveStudioHeaderFromTask(task: TaskDashboardItem | null): TaskStudioSnapshot["header"] {
  if (!task) return undefined;
  const queueState =
    task.handoff_state !== "none" ? "handoff_ready"
      : task.review_needed_count > 0 ? "failed"
      : task.approval_state !== "approved" && task.approval_state !== "none" ? "awaiting_approval"
      : task.blocked_count > 0 ? "blocked"
      : task.checkpoint_state !== "none" ? "ready"
      : task.status === "in_progress" ? "running"
      : task.status === "done" ? "done"
      : "planning";
  const nextSafeAction =
    queueState === "handoff_ready" ? "Review handoff"
      : queueState === "failed" ? "Review failed checks"
      : queueState === "awaiting_approval" ? `Approve ${task.next_gate ?? "pending gate"}`
      : queueState === "blocked" ? "Resolve blocker"
      : task.checkpoint_state !== "none" ? "Resume from checkpoint"
      : queueState === "running" ? "Monitor execution"
      : "Open task";
  return {
    queue_state: queueState,
    approval_state: task.approval_state,
    next_safe_action: nextSafeAction,
    repository_action_mode: "no_action",
    checkpoint_ready: task.checkpoint_state !== "none",
    handoff_state: task.handoff_state,
  };
}

function queueStateTone(value: string | undefined): "healthy" | "active" | "warning" | "blocked" | "draft" {
  if (!value) return "draft";
  if (["done"].includes(value)) return "healthy";
  if (["ready", "running", "handoff_ready"].includes(value)) return "active";
  if (["awaiting_approval", "waiting_human"].includes(value)) return "warning";
  if (["blocked", "failed"].includes(value)) return "blocked";
  return "draft";
}

function queueStateLabel(value: string | undefined): string {
  if (!value) return "planning";
  return value.replace(/_/g, " ");
}

function handoffStateTone(value: string | undefined): "healthy" | "active" | "warning" | "blocked" | "draft" {
  if (!value || value === "none") return "draft";
  if (["ready", "handoff_ready", "completed"].includes(value)) return "healthy";
  if (["pending", "in_progress"].includes(value)) return "active";
  if (["waiting_human", "awaiting_approval"].includes(value)) return "warning";
  if (["failed", "rejected", "blocked"].includes(value)) return "blocked";
  return "draft";
}

function proposalTone(confidence: number): "healthy" | "warning" | "draft" {
  if (confidence >= 0.8) return "healthy";
  if (confidence >= 0.6) return "warning";
  return "draft";
}

function riskTone(riskLevel: string): "healthy" | "warning" | "blocked" | "draft" {
  if (riskLevel === "high") return "blocked";
  if (riskLevel === "medium") return "warning";
  return "draft";
}

function deriveNextAction(
  task: TaskDashboardItem | null,
  approvalItems: TaskStudioSnapshot["approval_gates"],
  latestReview: ReviewRunRecord | null,
  handoffReady: boolean,
): { label: string; tone: string; detail: string } {
  const pendingGate = nextPendingGate(approvalItems);
  if (task?.blocked_count) {
    return {
      label: "Unblock execution",
      tone: "blocked",
      detail: `${task.blocked_count} unit${task.blocked_count === 1 ? "" : "s"} are blocked. Review dependencies or provider posture before dispatch continues.`,
    };
  }
  if (pendingGate) {
    const requiresHuman = pendingGate.metadata?.requires_human === true || pendingGate.status === "waiting_human";
    return {
      label: `Approve ${pendingGate.name}`,
      tone: requiresHuman ? "warning" : "active",
      detail: requiresHuman
        ? `${pendingGate.name} is waiting on a human decision before Sarathi can continue.`
        : `${pendingGate.name} is the next workflow gate.`,
    };
  }
  if (latestReview && latestReview.status === "approved" && !handoffReady) {
    return {
      label: "Create handoff",
      tone: "active",
      detail: "Execution and review are in a good state. Capture the governed handoff next.",
    };
  }
  if (task?.status === "in_progress") {
    return {
      label: "Monitor execution",
      tone: "active",
      detail: "Units are in flight. Watch the task panel and evidence feed for failures or review triggers.",
    };
  }
  return {
    label: "Schedule ready units",
    tone: "warning",
    detail: "Sarathi is ready for the next dispatch cycle.",
  };
}

export default function ProjectDetail({
  workspaceId,
  projectId,
  liveTick = 0,
  selectedTaskId,
  setSelectedTaskId,
  setRoute,
  onOpenProposal,
  onOpenWorkspace,
}: Props) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [resolvedWorkspaceId, setResolvedWorkspaceId] = useState<string | null>(
    workspaceId ?? (!apiConfigured ? workspace.id : null),
  );
  const [taskItems, setTaskItems] = useState<TaskDashboardItem[]>(mockTasksToDashboardItems());
  const [activeSavedView, setActiveSavedView] = useState<SavedViewSnapshot | null>(null);
  const [selectedTaskIdState, setSelectedTaskIdState] = useState<string | null>(selectedTaskId ?? null);
  const [selectedTab, setSelectedTab] = useState<ProjectTab>("studio");
  const [snapshot, setSnapshot] = useState<TaskStudioSnapshot | null>(null);
  const [panelSnapshot, setPanelSnapshot] = useState<TaskPanelSnapshot | null>(null);
  const [taskCheckpoint, setTaskCheckpoint] = useState<CheckpointCapsuleRecord | null>(null);
  const [taskCheckpointHistory, setTaskCheckpointHistory] = useState<CheckpointCapsuleRecord[]>([]);
  const [operations, setOperations] = useState<OperationalViewsSnapshot | null>(null);
  const [taskLoadStatus, setTaskLoadStatus] = useState(apiConfigured ? "Loading task studio." : "Demo task studio.");
  const [panelLoadStatus, setPanelLoadStatus] = useState(apiConfigured ? "Loading task panel." : "Demo task panel.");
  const [opsLoadStatus, setOpsLoadStatus] = useState(apiConfigured ? "Loading lifecycle views." : "Demo lifecycle views.");
  const [actionStatus, setActionStatus] = useState("");
  const [checkpointExpanded, setCheckpointExpanded] = useState(false);
  const [learnings, setLearnings] = useState<KnowledgeCenterSummary["learnings"] | null>(null);
  const [proposals, setProposals] = useState<PolicyProposal[]>([]);

  useEffect(() => {
    if (workspaceId) {
      setResolvedWorkspaceId(workspaceId);
      return;
    }
    if (!apiConfigured) {
      setResolvedWorkspaceId(workspace.id);
      return;
    }
    let cancelled = false;
    async function resolve() {
      try {
        const ws = await ensureWorkspace(workspace.name, "/Users/sweethome/Work/Skills/Sarathi", {
          source: "desktop-ui",
          display_id: workspace.id,
        });
        if (!cancelled) setResolvedWorkspaceId(ws.id);
      } catch {
        if (!cancelled) setResolvedWorkspaceId(workspace.id);
      }
    }
    void resolve();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (!resolvedWorkspaceId || !apiConfigured) {
      setLearnings(null);
      return;
    }
    const workspaceKey = resolvedWorkspaceId;
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
  }, [resolvedWorkspaceId, apiConfigured]);

  useEffect(() => {
    if (!resolvedWorkspaceId || !apiConfigured) {
      setProposals([]);
      return;
    }
    const workspaceKey = resolvedWorkspaceId;
    let cancelled = false;
    async function loadProposals() {
      try {
        const data = await getProposals(workspaceKey);
        if (!cancelled) setProposals(data.proposals);
      } catch {
        if (!cancelled) setProposals([]);
      }
    }
    void loadProposals();
    return () => {
      cancelled = true;
    };
  }, [resolvedWorkspaceId, apiConfigured]);

  useEffect(() => {
    if (selectedTaskId) {
      setSelectedTaskIdState(selectedTaskId);
    }
  }, [selectedTaskId]);

  async function fetchTaskItems(workspaceKey: string): Promise<{
    items: TaskDashboardItem[];
    fallbackReason: "demo" | "empty" | "error" | null;
    fromApi: boolean;
  }> {
    if (!apiConfigured) {
      return { items: mockTasksToDashboardItems(), fallbackReason: "demo", fromApi: false };
    }
    try {
      const [list, reuseKit] = await Promise.all([
        listTaskDashboard(workspaceKey, { projectId }),
        getWorkspaceReuseKit(workspaceKey),
      ]);
      const savedView = activeSavedViewFromReuseKit(reuseKit);
      setActiveSavedView(savedView);
      const filteredList = filterTaskDashboardItemsBySavedView(list, savedView);
      return {
        items: filteredList,
        fallbackReason: filteredList.length === 0 ? "empty" : null,
        fromApi: true,
      };
    } catch {
      setActiveSavedView(null);
      return { items: [], fallbackReason: "error", fromApi: true };
    }
  }

  async function reloadTaskItems(workspaceKey: string): Promise<TaskDashboardItem[]> {
    const next = await fetchTaskItems(workspaceKey);
    setTaskItems(next.items);
    if (!next.fromApi || next.fallbackReason === "demo") {
      setTaskLoadStatus("Demo task studio.");
    } else if (next.fallbackReason === "empty") {
      setTaskLoadStatus("No persisted tasks yet.");
    } else if (next.fallbackReason === "error") {
      setTaskLoadStatus("Task load failed.");
    } else {
      setTaskLoadStatus(`${next.items.length} persisted tasks loaded.`);
    }
    return next.items;
  }

  useEffect(() => {
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!workspaceKey) return;
    let cancelled = false;
    async function loadTasks() {
      const next = await fetchTaskItems(workspaceKey);
      if (!cancelled) {
        setTaskItems(next.items);
        if (!next.fromApi || next.fallbackReason === "demo") {
          setTaskLoadStatus("Demo task studio.");
        } else if (next.fallbackReason === "empty") {
          setTaskLoadStatus("No persisted tasks yet.");
        } else if (next.fallbackReason === "error") {
          setTaskLoadStatus("Task load failed.");
        } else {
          setTaskLoadStatus(`${next.items.length} persisted tasks loaded.`);
        }
      }
    }
    void loadTasks();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, projectId, resolvedWorkspaceId, liveTick, selectedTaskId]);

  const selectedTask = useMemo(() => {
    if (!taskItems.length) return null;
    if (selectedTaskIdState) {
      const found = taskItems.find((item) => item.id === selectedTaskIdState);
      if (found) return found;
      return null;
    }
    return taskItems[0];
  }, [selectedTaskIdState, taskItems]);

  useEffect(() => {
    if (!selectedTask?.id) return;
    if (selectedTaskIdState !== selectedTask.id) {
      setSelectedTaskIdState(selectedTask.id);
      setSelectedTaskId?.(selectedTask.id);
    }
  }, [selectedTask?.id, selectedTaskIdState, setSelectedTaskId]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId;
    if (!task || !workspaceKey) {
      setSnapshot(null);
      return;
    }
    if (!apiConfigured) {
      setSnapshot(createDemoSnapshot(task));
      return;
    }
    let cancelled = false;
    async function loadStudio() {
      try {
        const next = await getTaskStudio(task.id);
        if (!cancelled) {
          setSnapshot(next);
          setTaskLoadStatus(`${next.graph.nodes.length} units, ${next.messages.length} messages, ${next.approval_gates.length} gates loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setSnapshot(createDemoSnapshot(task));
          setTaskLoadStatus("Studio load failed. Using demo snapshot.");
        }
      }
    }
    void loadStudio();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, selectedTask?.id, liveTick]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!task || !workspaceKey) {
      setPanelSnapshot(null);
      return;
    }
    if (!apiConfigured) {
      setPanelSnapshot({ task_id: task.id, entries: snapshotToPanelEntries(createDemoSnapshot(task), task.id, workspaceKey) });
      setPanelLoadStatus("Demo task panel.");
      return;
    }
    let cancelled = false;
    async function loadPanel() {
      try {
        const next = await getTaskPanel(task.id);
        if (!cancelled) {
          setPanelSnapshot(next);
          setPanelLoadStatus(`${next.entries.length} task panel entries loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setPanelSnapshot({ task_id: task.id, entries: snapshotToPanelEntries(createDemoSnapshot(task), task.id, workspaceKey) });
          setPanelLoadStatus("Task panel load failed. Using demo panel.");
        }
      }
    }
    void loadPanel();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, selectedTask?.id, liveTick]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!task || !workspaceKey) {
      setTaskCheckpoint(null);
      setTaskCheckpointHistory([]);
      return;
    }
    if (!apiConfigured) {
      const demoCheckpoint = task.status === "done"
        ? createDemoCheckpoint(task, selectedTask?.title ?? "Task studio", workspaceKey, projectId ?? null)
        : null;
      setTaskCheckpoint(demoCheckpoint);
      setTaskCheckpointHistory(demoCheckpoint ? [demoCheckpoint] : []);
      return;
    }
    let cancelled = false;
    setTaskCheckpoint(null);
    setTaskCheckpointHistory([]);
    async function loadCheckpoint() {
      try {
        const [next, history] = await Promise.all([
          getTaskCheckpoint(task.id),
          listTaskCheckpoints(task.id),
        ]);
        if (!cancelled) {
          setTaskCheckpoint(next);
          setTaskCheckpointHistory(history);
        }
      } catch {
        if (!cancelled) {
          setTaskCheckpoint(null);
          setTaskCheckpointHistory([]);
        }
      }
    }
    void loadCheckpoint();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, projectId, resolvedWorkspaceId, selectedTask?.id, selectedTask?.title]);

  useEffect(() => {
    const workspaceKey = resolvedWorkspaceId;
    if (!workspaceKey) return;
    if (!apiConfigured) {
      setOperations(createDemoOperations());
      setOpsLoadStatus("Demo lifecycle views.");
      return;
    }
    let cancelled = false;
    async function loadOps() {
      try {
        const next = await getWorkspaceOperationalViews(workspaceKey!);
        if (!cancelled) {
          setOperations(next);
          setOpsLoadStatus(`${next.history.length} events, ${next.diagrams.length} diagrams, ${next.usage.tasks.total} tasks loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setOperations(createDemoOperations());
          setOpsLoadStatus("Lifecycle views load failed. Using demo data.");
        }
      }
    }
    void loadOps();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, liveTick]);

  const liveSnapshot = snapshot ?? (selectedTask ? createDemoSnapshot(selectedTask) : null);
  const liveOps = operations ?? createDemoOperations();

  const graphNodes = liveSnapshot?.graph.nodes ?? [];
  const graphEdges = liveSnapshot?.graph.edges ?? [];
  const taskMessages = liveSnapshot?.messages ?? [];
  const approvalItems = liveSnapshot?.approval_gates ?? [];
  const taskReviews = liveSnapshot?.reviews ?? [];
  const taskHandoff = liveSnapshot?.handoff ?? null;
  const latestReview = taskReviews.length > 0 ? taskReviews[taskReviews.length - 1] : null;
  const taskMetadata = (liveSnapshot?.task.metadata ?? {}) as TaskMetadata;
  const repositoryPreference = taskMetadata.repository_action_preference ?? {
    scope: "default",
    mode: "no_action",
    allowed_modes: ["no_action"],
  };
  const githubIssueReferenceText = githubIssueReference(taskMetadata);
  const panelEntries = panelSnapshot?.entries ?? (selectedTask && resolvedWorkspaceId
    ? snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, resolvedWorkspaceId)
    : []);
  const selectedPhase = liveSnapshot?.task.metadata.phase ?? selectedTask?.phase ?? "Build";
  const selectedTaskTitle = liveSnapshot?.task.title ?? selectedTask?.title ?? "Task studio";
  const pendingGate = nextPendingGate(approvalItems);
  const fallbackHeader = deriveStudioHeaderFromTask(selectedTask ?? null);
  const studioHeader = liveSnapshot?.header ?? fallbackHeader;
  const taskDispatches = liveSnapshot?.dispatches ?? [];
  const taskEvidence = liveSnapshot?.evidence ?? [];
  const artifactOverview = buildArtifactOverview(taskEvidence, taskDispatches);
  const deliverySpine = buildDeliverySpineModel(taskMetadata, latestReview, taskHandoff, Boolean(studioHeader?.checkpoint_ready));
  const taskOrigin = buildTaskOriginModel(taskMetadata);
  const nextAction = deriveNextAction(selectedTask ?? null, approvalItems, latestReview, Boolean(taskHandoff));
  const postureAction = studioHeader?.next_safe_action ?? nextAction.label;
  const postureTone = queueStateTone(studioHeader?.queue_state) ?? nextAction.tone;
  const pendingRepositoryAction = taskHandoff?.metadata?.repository_action
    && typeof taskHandoff.metadata.repository_action === "object"
      ? taskHandoff.metadata.repository_action as Record<string, unknown>
      : null;

  async function reloadStudio() {
    if (!selectedTask) return;
    if (!apiConfigured || !resolvedWorkspaceId) {
      setSnapshot(createDemoSnapshot(selectedTask));
      return;
    }
    try {
      const next = await getTaskStudio(selectedTask.id);
      setSnapshot(next);
      setTaskLoadStatus(`${next.graph.nodes.length} units, ${next.messages.length} messages, ${next.approval_gates.length} gates loaded from SQLite.`);
    } catch {
      setSnapshot(createDemoSnapshot(selectedTask));
      setTaskLoadStatus("Studio refresh failed. Using demo snapshot.");
    }
  }

  async function reloadPanel() {
    if (!selectedTask) return;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!apiConfigured || !resolvedWorkspaceId) {
      setPanelSnapshot({ task_id: selectedTask.id, entries: snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, workspaceKey) });
      return;
    }
    try {
      const next = await getTaskPanel(selectedTask.id);
      setPanelSnapshot(next);
      setPanelLoadStatus(`${next.entries.length} task panel entries loaded from SQLite.`);
    } catch {
      setPanelSnapshot({ task_id: selectedTask.id, entries: snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, workspaceKey) });
      setPanelLoadStatus("Task panel refresh failed. Using demo panel.");
    }
  }

  async function handleSchedule() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to schedule units.");
      return;
    }
    try {
      setActionStatus("Scheduling ready units through Sutra.");
      const result = await scheduleTask(selectedTask.id);
      setActionStatus(`${result.scheduled.length} ready units scheduled; ${result.blocked.length} remain blocked.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Schedule failed.");
    }
  }

  async function handleReview() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to run reviews.");
      return;
    }
    try {
      setActionStatus("Running review.");
      const result = await runTaskReview(selectedTask.id, "code");
      setActionStatus(`Review ${result.review.status}; ${result.completed_subtasks.length} units completed.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Review failed.");
    }
  }

  async function handleHandoff() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to create a handoff.");
      return;
    }
    try {
      setActionStatus("Creating handoff.");
      const result = await createTaskHandoff(selectedTask.id);
      setActionStatus(`Handoff ${result.handoff.id.slice(0, 8)} created.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Handoff failed.");
    }
  }

  async function handleApproveGate(gateName: string) {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to approve gates.");
      return;
    }
    try {
      setActionStatus(`Approving ${gateName}…`);
      await approveTaskGate(selectedTask.id, gateName, "approved");
      setActionStatus(`${gateName} approved.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Gate approval failed.");
    }
  }

  async function handleRejectGate(gateName: string) {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to reject gates.");
      return;
    }
    try {
      setActionStatus(`Rejecting ${gateName}…`);
      await approveTaskGate(selectedTask.id, gateName, "rejected");
      setActionStatus(`${gateName} rejected.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Gate rejection failed.");
    }
  }

  async function handleApproveGraph() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to approve the task graph.");
      return;
    }
    try {
      setActionStatus("Generating task graph…");
      await createTaskGraphDraft(selectedTask.id);
      setActionStatus("Task graph approved and scheduled.");
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Graph approval failed.");
    }
  }

  async function handleApproveRepositoryAction(action: string) {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to approve repository actions.");
      return;
    }
    try {
      setActionStatus(`Approving repository action: ${action}…`);
      const result = await approveRepositoryAction(selectedTask.id, action);
      setActionStatus(`Repository action ${result.repository_action.action} ${result.repository_action.status}.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Repository action failed.");
    }
  }

  async function handleStartNewSession() {
    if (!selectedTask || !taskCheckpoint) {
      setActionStatus("No checkpoint is available for this task.");
      return;
    }
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!apiConfigured) {
      const restartedTask = {
        id: `restart-${selectedTask.id}-${Date.now().toString(36)}`,
        workspace_id: workspaceKey,
        title: `Resume: ${selectedTask.title}`,
        status: "prd_pending",
        phase: "Plan",
        approval_state: "draft",
        graph_state: "ready",
        next_gate: "Resume from checkpoint",
        node_count: 1,
        blocked_count: 0,
        review_needed_count: 0,
        checkpoint_state: "ready",
        handoff_state: "none",
        roles: [],
        providers: [],
        updated_at: new Date().toISOString(),
      } satisfies TaskDashboardItem;
      setTaskItems((current) => [restartedTask, ...current.filter((item) => item.id !== restartedTask.id)]);
      setSnapshot(null);
      setPanelSnapshot(null);
      setTaskCheckpoint(null);
      setSelectedTaskIdState(restartedTask.id);
      setSelectedTaskId?.(restartedTask.id);
      setSelectedTab("studio");
      setRoute?.("project");
      setActionStatus("Demo session restarted from checkpoint.");
      return;
    }
    try {
      setActionStatus("Starting a new session from checkpoint.");
      const result = await restartTaskFromCheckpoint(selectedTask.id);
      const refreshedTasks = await reloadTaskItems(workspaceKey);
      const restartTask = refreshedTasks.find((item) => item.id === result.task.id) ?? taskRecordToDashboardItem(result.task);
      if (!refreshedTasks.some((item) => item.id === result.task.id)) {
        setTaskItems([restartTask, ...refreshedTasks.filter((item) => item.id !== restartTask.id)]);
      }
      setSnapshot(null);
      setPanelSnapshot(null);
      setTaskCheckpoint(null);
      setSelectedTaskIdState(restartTask.id);
      setSelectedTaskId?.(restartTask.id);
      setSelectedTab("studio");
      setRoute?.("project");
      setActionStatus(`Started new session from checkpoint ${result.checkpoint.id.slice(0, 8)}.`);
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Checkpoint restart failed.");
    }
  }

  function handleOpenSourceTask() {
    if (!taskCheckpoint) {
      setActionStatus("No checkpoint is available for this task.");
      return;
    }
    setSnapshot(null);
    setPanelSnapshot(null);
    setTaskCheckpoint(null);
    setSelectedTaskIdState(taskCheckpoint.source_task_id);
    setSelectedTaskId?.(taskCheckpoint.source_task_id);
    setSelectedTab("studio");
    setRoute?.("project");
    setActionStatus(`Opened source task ${taskCheckpoint.source_task_id}.`);
  }

  const lifecycleRows = liveOps.lifecycle ?? [];
  const historyRows = liveOps.history ?? [];
  const governance = liveOps.governance;
  const taskGovernanceOverrides = (governance?.override_history ?? []).filter((entry) => !entry.task_id || entry.task_id === selectedTask?.id);
  const taskRepositoryGovernance = (governance?.repository_action_governance?.recent ?? []).filter((entry) => entry.task_id === selectedTask?.id);
  const usage = liveOps.usage;
  const budget = usage?.budget ?? null;
  const budgetLabel = budget
    ? budget.budget_limit != null
      ? `${formatTokenCount(budget.total_tokens)} / ${formatTokenCount(budget.budget_limit)}`
      : `${formatTokenCount(budget.total_tokens)} total`
    : "n/a";

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <div style={styles.eyebrow}>Workspace / {workspaceId ?? workspace.id}</div>
          <h1 style={styles.title}>{selectedTaskTitle}</h1>
          <p style={styles.subtitle}>Task studio: dependency graph, selected unit packet, lifecycle gates, and task-scoped conversation in one place.</p>
          {activeSavedView ? (
            <p style={{ ...styles.subtitle, marginTop: 8 }}>
              Active saved view: <strong>{activeSavedView.name}</strong>. {activeSavedView.description}
            </p>
          ) : null}
        </div>
        <div style={styles.headerActions}>
          <button style={styles.secondaryButton} onClick={() => setRoute?.("dashboard")}>Back to Dashboard</button>
          <button style={styles.primaryButton} onClick={() => setRoute?.("workspace")}>Workspaces</button>
        </div>
      </div>

      <section style={styles.cockpitStrip}>
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Queue</div>
          <Pill tone={queueStateTone(studioHeader?.queue_state)}>{queueStateLabel(studioHeader?.queue_state)}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Approval</div>
          <Pill tone={stateTone(studioHeader?.approval_state ?? selectedTask?.approval_state ?? "draft")}>
            {studioHeader?.approval_state ?? selectedTask?.approval_state ?? "draft"}
          </Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Next Action</div>
          <Pill tone={postureTone}>{postureAction}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Checkpoint</div>
          <Pill tone={studioHeader?.checkpoint_ready ? "healthy" : "draft"}>
            {studioHeader?.checkpoint_ready ? "Ready" : "None"}
          </Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Handoff</div>
          <Pill tone={queueStateTone(studioHeader?.handoff_state)}>
            {queueStateLabel(studioHeader?.handoff_state)}
          </Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Repo Action</div>
          <Pill tone={stateTone(studioHeader?.repository_action_mode ?? repositoryPreference.mode)}>
            {repositoryActionLabel(studioHeader?.repository_action_mode ?? repositoryPreference.mode)}
          </Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Blocked</div>
          <Pill tone={selectedTask?.blocked_count ? "blocked" : "healthy"}>{selectedTask?.blocked_count ?? 0}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Units</div>
          <div style={styles.cockpitValue}>{graphNodes.length}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Budget</div>
          <Pill tone={budgetTone(budget?.budget_state)}>{budgetLabel}</Pill>
        </div>
      </section>

      <section style={styles.statusStrip}>
        <Pill tone={apiConfigured ? "healthy" : "warning"}>Workspace {apiConfigured ? "live" : "demo"}</Pill>
        <Pill tone={snapshot ? "healthy" : "warning"}>{taskLoadStatus}</Pill>
        <Pill tone={panelSnapshot ? "healthy" : "warning"}>{panelLoadStatus}</Pill>
        <Pill tone={operations ? "healthy" : "warning"}>{opsLoadStatus}</Pill>
        <Pill tone="active">{taskItems.length} tasks</Pill>
        <Pill tone={selectedTask?.status === "done" ? "healthy" : "warning"}>{selectedTask?.status ?? "pending"}</Pill>
      </section>

      <section style={styles.taskRail}>
        {taskItems.map((task) => (
          <button
            key={task.id}
            style={{ ...styles.taskCard, ...(task.id === selectedTask?.id ? styles.taskCardActive : {}) }}
            onClick={() => {
              setSelectedTaskIdState(task.id);
              setSelectedTaskId?.(task.id);
              setSelectedTab("studio");
            }}
          >
            <div style={styles.taskCardRow}>
              <span style={styles.taskCardId}>{task.id.split("-")[0]}</span>
              <Pill tone={queueStateTone(deriveStudioHeaderFromTask(task)?.queue_state)}>
                {queueStateLabel(deriveStudioHeaderFromTask(task)?.queue_state)}
              </Pill>
            </div>
            <div style={styles.taskCardTitleRow}>
              <span style={styles.taskCardTitle}>{task.title.length > 32 ? task.title.slice(0, 32) + "…" : task.title}</span>
            </div>
            <div style={styles.taskCardMetaRow}>
              <span style={styles.taskCardMeta}>
                {task.phase} · {task.node_count} units · {deriveStudioHeaderFromTask(task)?.next_safe_action ?? "Open task"}
              </span>
            </div>
          </button>
        ))}
      </section>

      <section style={styles.tabBar}>
        {(["studio", "lifecycle", "history", "usage"] as ProjectTab[]).map((tab) => (
          <button
            key={tab}
            style={{ ...styles.tabButton, ...(selectedTab === tab ? styles.tabButtonActive : {}) }}
            onClick={() => setSelectedTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </section>

      {selectedTab === "studio" && (
        <div style={styles.studioGrid}>
          <section style={styles.leftColumn}>
            <div style={styles.panel}>
              <PanelTitle title="Dependency graph" badge={selectedTask?.approval_state ?? "draft"} />
              <div style={styles.metaRow}>
                <Field label="Phase" value={selectedPhase} />
                <Field label="Task" value={selectedTask ? `${selectedTask.id} / ${selectedTask.title}` : "No task selected"} />
                <Field label="Graph" value={`${graphNodes.length} nodes / ${graphEdges.length} edges`} />
              </div>
              <UnitGraph
                nodes={graphNodes}
                edges={graphEdges}
                taskPhase={selectedPhase}
                taskId={selectedTask?.id ?? null}
                onAction={() => {
                  void reloadStudio();
                }}
              />
            </div>

            <div style={styles.panel}>
              <PanelTitle title="Task actions" badge="Sutra" />
              <Card style={styles.summaryCard}>
                <strong>Current posture</strong>
                <Pill tone={postureTone}>{postureAction}</Pill>
                <p>{nextAction.detail}</p>
                <small>
                  Queue: {queueStateLabel(studioHeader?.queue_state)}
                  {" / "}
                  Approval: {studioHeader?.approval_state ?? "clear"}
                  {" / "}
                  Repo action: {repositoryActionLabel(studioHeader?.repository_action_mode ?? repositoryPreference.mode)}
                </small>
                {pendingGate && (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button
                      style={styles.primaryButton}
                      onClick={() => void handleApproveGate(pendingGate.name)}
                      disabled={!selectedTask || !apiConfigured}
                    >
                      Approve {pendingGate.name}
                    </button>
                    <button
                      style={styles.secondaryButton}
                      onClick={() => void handleRejectGate(pendingGate.name)}
                      disabled={!selectedTask || !apiConfigured}
                    >
                      Reject
                    </button>
                  </div>
                )}
                {!pendingGate && studioHeader?.checkpoint_ready && taskCheckpoint && (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button style={styles.primaryButton} onClick={() => void handleStartNewSession()} disabled={!selectedTask || !taskCheckpoint}>
                      Start from checkpoint
                    </button>
                    <button style={styles.secondaryButton} onClick={() => handleOpenSourceTask()} disabled={!taskCheckpoint}>
                      Open source task
                    </button>
                  </div>
                )}
                {!pendingGate && studioHeader?.queue_state === "handoff_ready" && (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button style={styles.primaryButton} onClick={() => setSelectedTab("history")}>
                      Review handoff
                    </button>
                  </div>
                )}
                {!pendingGate && pendingRepositoryAction?.status === "pending" && typeof pendingRepositoryAction.action === "string" && (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button
                      style={styles.secondaryButton}
                      onClick={() => void handleApproveRepositoryAction(pendingRepositoryAction.action as string)}
                      disabled={!apiConfigured}
                    >
                      Approve {repositoryActionLabel(pendingRepositoryAction.action as string)}
                    </button>
                  </div>
                )}
              </Card>
              <Card style={styles.summaryCard}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <strong>Governance posture</strong>
                  <Pill tone={governance?.override_history?.length ? "warning" : "healthy"}>
                    {governance?.provider_routing?.selected_provider ?? "local"}
                  </Pill>
                </div>
                <p style={{ marginTop: 8, marginBottom: 8 }}>
                  Repository policy: {repositoryActionLabel(governance?.policy_posture?.repository_action_preference?.mode ?? studioHeader?.repository_action_mode ?? repositoryPreference.mode)}
                  {" / "}
                  Approval policy: {governance?.policy_posture?.auto_approve_preference?.mode ?? "manual_only"}
                </p>
                <small>
                  Dispatch order: {(governance?.provider_routing?.priority_order ?? []).join(" → ") || "not set"}
                </small>
                {(governance?.provider_routing?.fallback_candidates?.length ?? 0) > 0 && (
                  <small style={{ display: "block", marginTop: 6 }}>
                    Fallbacks: {governance?.provider_routing?.fallback_candidates.join(", ")}
                  </small>
                )}
                {(taskGovernanceOverrides.length > 0 || taskRepositoryGovernance.length > 0) && (
                  <small style={{ display: "block", marginTop: 6 }}>
                    {taskGovernanceOverrides.length} governance event{taskGovernanceOverrides.length === 1 ? "" : "s"} and {taskRepositoryGovernance.length} repository decision{taskRepositoryGovernance.length === 1 ? "" : "s"} in scope.
                  </small>
                )}
              </Card>
              {learnings?.accepted_learnings && learnings.accepted_learnings.length > 0 && selectedTask && (
                (() => {
                  const relatedLearnings = learnings.accepted_learnings.filter((l) => l.task_id === selectedTask.id);
                  if (relatedLearnings.length === 0) return null;
                  const durableProposalIds = Array.from(new Set(
                    relatedLearnings
                      .map((learning) => learning.linked_proposal_id)
                      .filter((value): value is string => typeof value === "string" && value.length > 0),
                  ));
                  const linkedProposals = durableProposalIds.length > 0
                    ? proposals.filter((proposal) => durableProposalIds.some((proposalId) => (
                      proposal.id === proposalId || proposal.id.startsWith(`${proposalId}-`)
                    )))
                    : proposals.filter((proposal) =>
                      proposal.evidence_refs.some((ref) => ref.startsWith(selectedTask.id)),
                    );
                  const reuseMetadata = asObject(taskMetadata.reuse);
                  const playbookId = typeof reuseMetadata?.learning_playbook_id === "string"
                    ? reuseMetadata.learning_playbook_id
                    : null;
                  const recommendedViews = asStringList(reuseMetadata?.recommended_view_ids);
                  const primaryRecommendedView = recommendedViews[0] ?? relatedLearnings.flatMap((learning) => learning.recommended_view_ids ?? [])[0] ?? null;
                  const primaryLinkedProposal = linkedProposals[0] ?? null;
                  return (
                    <Card style={styles.summaryCard}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                        <strong>Related learnings</strong>
                        <Pill tone="active">{relatedLearnings.length}</Pill>
                      </div>
                      <div style={{ display: "grid", gap: 8 }}>
                        {relatedLearnings.slice(0, 3).map((learning, idx) => (
                          <div key={idx} style={{ padding: "8px 10px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                            <div style={{ fontSize: "0.82rem", fontWeight: 500, marginBottom: 4 }}>{learning.title}</div>
                            {learning.summary && (
                              <p style={{ margin: 0, fontSize: "0.74rem", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {learning.summary}
                              </p>
                            )}
                            {learning.tags && learning.tags.length > 0 && (
                              <div style={{ display: "flex", gap: 4, marginTop: 6, flexWrap: "wrap" }}>
                                {learning.tags.slice(0, 3).map((tag) => (
                                  <span key={tag} style={{ fontSize: "0.66rem", padding: "2px 5px", background: "var(--surface-2)", borderRadius: 3, color: "var(--faint)" }}>
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                        {relatedLearnings.length > 3 && (
                          <small style={{ color: "var(--muted)", fontSize: "0.72rem" }}>+ {relatedLearnings.length - 3} more learnings</small>
                        )}
                      </div>
                      {primaryLinkedProposal && (
                        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
                          <div style={{ fontSize: "0.72rem", color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                            Linked proposal
                          </div>
                          <div style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", display: "grid", gap: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
                              <strong style={{ fontSize: "0.82rem" }}>{primaryLinkedProposal.title}</strong>
                              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                <Pill tone={riskTone(primaryLinkedProposal.risk_level)}>{primaryLinkedProposal.risk_level} risk</Pill>
                                <Pill tone={proposalTone(primaryLinkedProposal.confidence)}>{primaryLinkedProposal.confidence.toFixed(2)} confidence</Pill>
                              </div>
                            </div>
                            <p style={{ margin: 0, fontSize: "0.74rem", color: "var(--muted)" }}>{primaryLinkedProposal.rationale}</p>
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                              {(primaryLinkedProposal.impacted_assets.length > 0 ? primaryLinkedProposal.impacted_assets : [primaryLinkedProposal.policy_file]).slice(0, 3).map((asset) => (
                                <span key={asset} style={{ fontSize: "0.66rem", padding: "2px 6px", background: "var(--surface-2)", borderRadius: 3, color: "var(--faint)" }}>
                                  {asset}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                      {(linkedProposals.length > 0 || playbookId) && (
                        <div style={{ display: "grid", gap: 8, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
                          {primaryLinkedProposal && (
                            <div
                              style={{
                                padding: "10px 12px",
                                background: "var(--surface)",
                                borderRadius: "var(--radius-sm)",
                                border: "1px solid var(--active)",
                                cursor: onOpenProposal ? "pointer" : "default",
                              }}
                              onClick={() => onOpenProposal ? onOpenProposal(primaryLinkedProposal.id) : setRoute?.("proposals")}
                            >
                              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                                <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--active-fg)" }}>Linked proposal</span>
                                <div style={{ display: "flex", gap: 4 }}>
                                  <Pill tone="draft">{primaryLinkedProposal.proposal_kind.replaceAll("_", " ")}</Pill>
                                  <Pill tone={riskTone(primaryLinkedProposal.risk_level)}>{primaryLinkedProposal.risk_level} risk</Pill>
                                </div>
                              </div>
                              <div style={{ fontSize: "0.82rem", fontWeight: 500, marginBottom: 4, color: "var(--ink)" }}>
                                {primaryLinkedProposal.title}
                              </div>
                              {primaryLinkedProposal.rationale && (
                                <p style={{ margin: 0, fontSize: "0.72rem", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {primaryLinkedProposal.rationale}
                                </p>
                              )}
                              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                                <Pill tone={proposalTone(primaryLinkedProposal.confidence)}>{primaryLinkedProposal.confidence.toFixed(2)} confidence</Pill>
                                {primaryLinkedProposal.impacted_assets[0] && (
                                  <span style={{ fontSize: "0.68rem", color: "var(--faint)" }}>
                                    Target: {primaryLinkedProposal.impacted_assets[0]}
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                          {linkedProposals.length > 1 && (
                            <button
                              style={{ ...styles.secondaryButton, padding: "4px 10px", fontSize: "0.72rem" }}
                              onClick={() => setRoute?.("proposals")}
                            >
                              View {linkedProposals.length - 1} more proposal{linkedProposals.length > 2 ? "s" : ""}
                            </button>
                          )}
                          {playbookId && (
                            <button
                              style={{ ...styles.secondaryButton, padding: "4px 10px", fontSize: "0.72rem" }}
                              onClick={() => onOpenWorkspace ? onOpenWorkspace(primaryRecommendedView) : setRoute?.("workspace")}
                            >
                              {primaryRecommendedView
                                ? `Open playbook view: ${primaryRecommendedView}`
                                : `Open playbook ${playbookId.slice(0, 8)}…`}
                            </button>
                          )}
                        </div>
                      )}
                    </Card>
                  );
                })()
              )}
              <div style={styles.actionRow}>
                <button style={styles.secondaryButton} onClick={() => void handleApproveGraph()} disabled={!selectedTask || !apiConfigured}>Approve graph</button>
                <button style={styles.secondaryButton} onClick={() => void handleSchedule()} disabled={!selectedTask || !apiConfigured}>Schedule units</button>
                <button style={styles.secondaryButton} onClick={() => void handleReview()} disabled={!selectedTask || !apiConfigured}>Run review</button>
                <button style={styles.secondaryButton} onClick={() => void handleHandoff()} disabled={!selectedTask || !apiConfigured}>Create handoff</button>
              </div>
              <p style={styles.helperText}>{actionStatus || "Use Sarathi's lifecycle actions to move the selected task forward."}</p>
              {latestReview ? (
                <Card style={styles.summaryCard}>
                  <strong>Latest review</strong>
                  <Pill tone={stateTone(latestReview.status)}>{latestReview.status}</Pill>
                  <p>{latestReview.summary ?? "Review result captured from SQLite."}</p>
                  <small>{latestReview.created_at}</small>
                </Card>
              ) : (
                <Card style={styles.summaryCard}>
                  <strong>Latest review</strong>
                  <p>No review has been run for this task yet.</p>
                </Card>
              )}
{taskHandoff ? (
                <Card style={styles.summaryCard}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                    <strong>Final handoff dossier</strong>
                    <Pill tone={deliverySpine.repositoryActionStatus === "approved" ? "healthy" : "warning"}>
                      Repo action {deliverySpine.repositoryActionStatus ?? "pending"}
                    </Pill>
                  </div>
                  <p style={{ marginBottom: 8 }}>{taskHandoff.summary}</p>
                  <small style={{ color: "var(--muted)" }}>
                    {taskHandoff.from_agent ?? "Samanvaya"} → {taskHandoff.to_agent ?? "User"} / {taskHandoff.created_at?.slice(0, 19) ?? "recorded"}
                  </small>
                  {deliverySpine.acCoverage.length > 0 && (
                    <section style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                      <div style={{ paddingBottom: 8, marginBottom: 8 }}>
                        <h3 style={{ fontSize: "0.8rem", fontWeight: 600 }}>AC Coverage</h3>
                        <Pill tone={deliverySpine.coveredCriteriaCount === deliverySpine.acCoverage.length ? "healthy" : "warning"}>
                          {deliverySpine.coveredCriteriaCount}/{deliverySpine.acCoverage.length} covered
                        </Pill>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {deliverySpine.acCoverage.slice(0, 6).map((item) => (
                          <div key={`${taskHandoff.id}-ac-${item.id}`} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8rem" }}>
                            <span style={{ color: item.covered ? "var(--green-11)" : "var(--red-11)", fontWeight: 500, width: 14 }}>
                              {item.covered ? "✓" : "✗"}
                            </span>
                            <span style={{ color: "var(--muted)", minWidth: 40 }}>{item.id}</span>
                            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.criterion}</span>
                          </div>
                        ))}
                        {deliverySpine.acCoverage.length > 6 && (
                          <small style={{ color: "var(--muted)", fontSize: "0.75rem" }}>+ {deliverySpine.acCoverage.length - 6} more criteria</small>
                        )}
                      </div>
                    </section>
                  )}
                  {deliverySpine.completionContext && (
                    <section style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                      <div style={{ paddingBottom: 8, marginBottom: 8 }}>
                        <h3 style={{ fontSize: "0.8rem", fontWeight: 600 }}>Completion context</h3>
                        <Pill tone="default">normalized</Pill>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
                        <div style={{ textAlign: "center", padding: 8, background: "var(--surface-2)", borderRadius: 4 }}>
                          <div style={{ fontSize: "1rem", fontWeight: 600 }}>{deliverySpine.completionContext.filesChanged.length}</div>
                          <div style={{ fontSize: "0.65rem", color: "var(--muted)" }}>Files</div>
                        </div>
                        <div style={{ textAlign: "center", padding: 8, background: "var(--surface-2)", borderRadius: 4 }}>
                          <div style={{ fontSize: "1rem", fontWeight: 600 }}>{deliverySpine.completionContext.testsRun.length}</div>
                          <div style={{ fontSize: "0.65rem", color: "var(--muted)" }}>Tests</div>
                        </div>
                        <div style={{ textAlign: "center", padding: 8, background: "var(--surface-2)", borderRadius: 4 }}>
                          <div style={{ fontSize: "1rem", fontWeight: 600 }}>{deliverySpine.completionContext.findings.length}</div>
                          <div style={{ fontSize: "0.65rem", color: "var(--muted)" }}>Findings</div>
                        </div>
                        <div style={{ textAlign: "center", padding: 8, background: "var(--surface-2)", borderRadius: 4 }}>
                          <div style={{ fontSize: "1rem", fontWeight: 600 }}>{deliverySpine.completionContext.decisions.length}</div>
                          <div style={{ fontSize: "0.65rem", color: "var(--muted)" }}>Decisions</div>
                        </div>
                      </div>
                      {deliverySpine.completionContext.summaries.length > 0 && (
                        <div style={{ marginBottom: 8 }}>
                          <small style={{ color: "var(--muted)", fontWeight: 500 }}>Summaries</small>
                          <div style={{ fontSize: "0.8rem" }}>
                            {deliverySpine.completionContext.summaries.slice(0, 2).map((s, i) => (
                              <div key={`sum-${i}`} style={{ marginTop: 4 }}>{s}</div>
                            ))}
                          </div>
                        </div>
                      )}
                      {deliverySpine.completionContext.risks.length > 0 && (
                        <div>
                          <small style={{ color: "var(--warning)", fontWeight: 500 }}>Known risks</small>
                          <div style={{ fontSize: "0.8rem" }}>
                            {deliverySpine.completionContext.risks.slice(0, 2).map((r, i) => (
                              <div key={`risk-${i}`} style={{ marginTop: 4, color: "var(--warning)" }}>{r}</div>
                            ))}
                          </div>
                        </div>
                      )}
                    </section>
                  )}
                </Card>
              ) : (
                <Card style={styles.summaryCard}>
                  <strong>Handoff</strong>
                  <Pill tone="warning">not created</Pill>
                  <p>Run the final review loop first, then create a handoff to capture AC coverage, evidence, and repository-action choices in one dossier.</p>
                </Card>
              )}
              <Card style={styles.summaryCard}>
                <div style={styles.deliveryHeader}>
                  <h3 style={styles.artifactHeading}>Delivery spine</h3>
                  <Pill tone={deliverySpine.handoffReady ? "healthy" : "warning"}>
                    {deliverySpine.handoffReady ? "handoff ready" : "in progress"}
                  </Pill>
                </div>
                <p style={styles.deliverySummary}>
                  Traceability from PRD through acceptance criteria, review, evidence, and handoff for this task.
                </p>
                <div style={styles.deliveryMetricGrid}>
                  <Card style={styles.deliveryMetricCard}>
                    <strong>Acceptance coverage</strong>
                    <p>
                      {deliverySpine.coveredCriteriaCount}/{deliverySpine.acCoverage.length || deliverySpine.acceptanceCriteria.length} covered
                    </p>
                    <small style={styles.helperText}>
                      {deliverySpine.latestReviewStatus ? `Latest review: ${deliverySpine.latestReviewStatus}` : "No approved review recorded yet."}
                    </small>
                  </Card>
                  <Card style={styles.deliveryMetricCard}>
                    <strong>Evidence posture</strong>
                    <p>{artifactOverview.evidenceCount} artifacts linked</p>
                    <small style={styles.helperText}>
                      {artifactOverview.filesChanged.length} files · {artifactOverview.testsRun.length} tests · {artifactOverview.reviewFindings.length} findings
                    </small>
                  </Card>
                  <Card style={styles.deliveryMetricCard}>
                    <strong>Handoff posture</strong>
                    <p>{taskHandoff ? "Recorded" : "Not created"}</p>
                    <small style={styles.helperText}>
                      {deliverySpine.repositoryActionStatus ? `Repository action ${deliverySpine.repositoryActionStatus}` : "Repository action starts after handoff."}
                    </small>
                  </Card>
                </div>
                <section style={styles.deliverySection}>
                  <div style={styles.artifactHeader}>
                    <h3 style={styles.artifactHeading}>PRD brief</h3>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Pill tone={deliverySpine.prdProblem || deliverySpine.prdGoal ? "active" : "draft"}>
                        {deliverySpine.prdProblem || deliverySpine.prdGoal ? "captured" : "missing"}
                      </Pill>
                      <Pill tone={deliverySpine.checkpointReady ? "healthy" : "warning"}>
                        checkpoint {deliverySpine.checkpointReady ? "ready" : "n/a"}
                      </Pill>
                    </div>
                  </div>
                  {deliverySpine.prdProblem || deliverySpine.prdGoal || deliverySpine.prdScope.length > 0 ? (
                    <div style={styles.deliveryCopyBlock}>
                      {deliverySpine.prdProblem ? (
                        <div style={styles.deliveryDetailRow}>
                          <strong>Problem</strong>
                          <span>{deliverySpine.prdProblem}</span>
                        </div>
                      ) : null}
                      {deliverySpine.prdGoal ? (
                        <div style={styles.deliveryDetailRow}>
                          <strong>Goal</strong>
                          <span>{deliverySpine.prdGoal}</span>
                        </div>
                      ) : null}
                      {deliverySpine.prdScope.length > 0 ? (
                        <div style={styles.deliveryDetailRow}>
                          <strong>Scope</strong>
                          <span>{deliverySpine.prdScope.join(" · ")}</span>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div style={styles.artifactEmpty}>No PRD summary has been captured for this task yet.</div>
                  )}
                </section>
                <section style={styles.deliverySection}>
                  <div style={styles.artifactHeader}>
                    <h3 style={styles.artifactHeading}>Acceptance criteria</h3>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Pill tone={deliverySpine.acCoverage.length > 0 && deliverySpine.acCoverage.every((item) => item.covered) ? "healthy" : "warning"}>
                        {deliverySpine.coveredCriteriaCount}/{deliverySpine.acCoverage.length || deliverySpine.acceptanceCriteria.length}
                      </Pill>
                      <Pill tone={deliverySpine.checkpointReady ? "healthy" : "warning"}>
                        checkpoint {deliverySpine.checkpointReady ? "ready" : "n/a"}
                      </Pill>
                    </div>
                  </div>
                  {deliverySpine.acCoverage.length > 0 ? (
                    <div style={styles.deliveryChecklist}>
                      {deliverySpine.acCoverage.map((item) => (
                        <div key={`${selectedTask?.id ?? "task"}-${item.id}`} style={styles.deliveryChecklistItem}>
                          <div style={styles.deliveryChecklistLead}>
                            <span style={styles.deliveryChecklistMark}>{item.covered ? "✓" : "○"}</span>
                            <span style={styles.deliveryChecklistId}>{item.id}</span>
                          </div>
                          <span>{item.criterion}</span>
                        </div>
                      ))}
                    </div>
                  ) : deliverySpine.acceptanceCriteria.length > 0 ? (
                    <div style={styles.deliveryChecklist}>
                      {deliverySpine.acceptanceCriteria.map((criterion, index) => (
                        <div key={`${selectedTask?.id ?? "task"}-criterion-${index}`} style={styles.deliveryChecklistItem}>
                          <div style={styles.deliveryChecklistLead}>
                            <span style={styles.deliveryChecklistMark}>○</span>
                            <span style={styles.deliveryChecklistId}>{`AC-${String(index + 1).padStart(2, "0")}`}</span>
                          </div>
                          <span>{criterion}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={styles.artifactEmpty}>No acceptance criteria have been drafted yet.</div>
                  )}
                </section>
                <section style={styles.deliverySection}>
                  <div style={styles.artifactHeader}>
                    <h3 style={styles.artifactHeading}>Ready for governed handoff</h3>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Pill tone={deliverySpine.handoffReady ? "healthy" : "warning"}>
                        {deliverySpine.handoffReady ? "yes" : "not yet"}
                      </Pill>
                      <Pill tone={deliverySpine.checkpointReady ? "healthy" : "warning"}>
                        checkpoint {deliverySpine.checkpointReady ? "ready" : "missing"}
                      </Pill>
                    </div>
                  </div>
                  {deliverySpine.missingItems.length > 0 ? (
                    <div style={styles.deliveryMissingList}>
                      {deliverySpine.missingItems.map((item) => (
                        <div key={item} style={styles.deliveryMissingItem}>{item}</div>
                      ))}
                    </div>
                  ) : (
                    <div style={styles.deliveryCopyBlock}>
                      <div style={styles.deliveryDetailRow}>
                        <strong>Status</strong>
                        <span>PRD, acceptance criteria, review coverage, evidence, and handoff are all linked.</span>
                      </div>
                    </div>
                  )}
                </section>
                {deliverySpine.completionContext ? (
                  <section style={styles.deliverySection}>
                    <div style={styles.artifactHeader}>
                      <h3 style={styles.artifactHeading}>Completion context</h3>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <Pill tone="default">normalized</Pill>
                        <Pill tone={deliverySpine.checkpointReady ? "healthy" : "warning"}>
                          checkpoint {deliverySpine.checkpointReady ? "ready" : "missing"}
                        </Pill>
                      </div>
                    </div>
                    <div style={styles.deliveryMetricGrid}>
                      <Card style={styles.deliveryMetricCard}>
                        <strong>Files</strong>
                        <p>{deliverySpine.completionContext.filesChanged.length}</p>
                        <small style={styles.helperText}>Completion-ready file scope.</small>
                      </Card>
                      <Card style={styles.deliveryMetricCard}>
                        <strong>Tests</strong>
                        <p>{deliverySpine.completionContext.testsRun.length}</p>
                        <small style={styles.helperText}>Recorded verification traces.</small>
                      </Card>
                      <Card style={styles.deliveryMetricCard}>
                        <strong>Signals</strong>
                        <p>{deliverySpine.completionContext.findings.length}</p>
                        <small style={styles.helperText}>Reviewer findings and risks.</small>
                      </Card>
                    </div>
                  </section>
                ) : null}
              </Card>
              {taskCheckpoint ? (
                <Card style={styles.summaryCard}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <strong>Checkpoint</strong>
                      <Pill tone="healthy">Ready</Pill>
                    </div>
                    <button
                      style={{ padding: "4px 8px", height: "auto", fontSize: "0.7rem" }}
                      onClick={() => setCheckpointExpanded(!checkpointExpanded)}
                    >
                      {checkpointExpanded ? "Hide" : "Show"}
                    </button>
                  </div>
                  {checkpointExpanded && (
                    <>
                      <p>{taskCheckpoint.summary}</p>
                      <small>{taskCheckpoint.next_start_point}</small>
                      <div style={{ ...styles.actionRow, marginTop: 12 }}>
                        <button style={styles.primaryButton} onClick={() => void handleStartNewSession()} disabled={!selectedTask || !taskCheckpoint}>
                          Start new session
                        </button>
                        <button style={styles.secondaryButton} onClick={() => handleOpenSourceTask()} disabled={!taskCheckpoint}>
                          Open source
                        </button>
                      </div>
                    </>
                  )}
                </Card>
              ) : null}
              {taskCheckpointHistory.length > 1 && checkpointExpanded && (
                <Card style={styles.summaryCard}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <strong>Checkpoint history</strong>
                    <Pill tone="active">{taskCheckpointHistory.length}</Pill>
                  </div>
                  <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                    {taskCheckpointHistory.slice(1).map((checkpoint, index) => {
                      return (
                        <div key={checkpoint.id} style={styles.checkpointHistoryItem}>
                          <div style={styles.checkpointHistoryHeader}>
                            <strong>Checkpoint {taskCheckpointHistory.length - index}</strong>
                            <Pill tone="draft">{checkpoint.status}</Pill>
                          </div>
                          <p style={styles.checkpointSummary}>{checkpoint.summary}</p>
                          <div style={styles.checkpointMetaRow}>
                            <span>{new Date(checkpoint.created_at).toLocaleString()}</span>
                            <span>{checkpoint.created_by}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Card>
              )}
              <Card style={styles.summaryCard}>
                <strong>Repository actions</strong>
                <Pill tone={stateTone(studioHeader?.repository_action_mode ?? repositoryPreference.mode)}>
                  {repositoryActionLabel(studioHeader?.repository_action_mode ?? repositoryPreference.mode)}
                </Pill>
                <p>Commit and PR stay disabled until you explicitly opt in from Settings.</p>
                <small>Scope: {repositoryPreference.scope}</small>
                {pendingRepositoryAction?.status === "pending" && typeof pendingRepositoryAction.action === "string" ? (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button
                      style={styles.secondaryButton}
                      onClick={() => void handleApproveRepositoryAction(pendingRepositoryAction.action as string)}
                      disabled={!apiConfigured}
                    >
                      Approve {repositoryActionLabel(pendingRepositoryAction.action as string)}
                    </button>
                  </div>
                ) : repositoryPreference.mode !== "no_action" && selectedTask ? (
                  <div style={{ ...styles.actionRow, marginTop: 10 }}>
                    <button
                      style={styles.secondaryButton}
                      onClick={() => void handleApproveRepositoryAction(repositoryPreference.mode)}
                      disabled={!apiConfigured}
                    >
                      Approve {repositoryActionLabel(repositoryPreference.mode)}
                    </button>
                  </div>
                ) : null}
              </Card>
              {githubIssueReferenceText ? (
                <Card style={styles.summaryCard}>
                  <strong>Imported GitHub issue</strong>
                  <Pill tone="active">github issue</Pill>
                  <p>{githubIssueReferenceText}</p>
                  <small>{taskMetadata.github_issue?.url ?? taskMetadata.github_issue?.repository_url ?? "GitHub source recorded in task metadata."}</small>
                  {taskMetadata.github_issue?.repository ? (
                    <small style={{ display: "block", marginTop: 4 }}>
                      Repository: {String((taskMetadata.github_issue.repository as Record<string, unknown>).full_name ?? (taskMetadata.github_issue.repository as Record<string, unknown>).workspace_repository_name ?? taskMetadata.github_issue.name ?? "unknown")}
                    </small>
                  ) : null}
                </Card>
              ) : null}
            </div>
          </section>

          <section style={styles.rightColumn}>
            <div style={styles.panel}>
              <PanelTitle title="Task panel" badge={projectId ? "project" : "task"} />
              <TaskPanelTimeline entries={panelEntries} loading={!panelSnapshot} />
            </div>

            <div style={styles.panel}>
              <PanelTitle title="Evidence and events" badge="ledger" />
              <p className="artifact-subtle-copy">
                Summary-first operator view of what Sarathi knows, what it proved, and what still depends on raw provider evidence.
              </p>
              <div style={styles.ledgerGrid}>
                <Card style={styles.summaryCard}><strong>Messages</strong><p>{taskMessages.length} conversation entries</p></Card>
                <Card style={styles.summaryCard}><strong>Approval gates</strong><p>{approvalItems.length} gates tracked</p></Card>
                <Card style={styles.summaryCard}><strong>Events</strong><p>{liveSnapshot?.events.length ?? 0} lifecycle events</p></Card>
                <Card style={styles.summaryCard}><strong>Selected task</strong><p>{selectedTask?.phase ?? "pending"}</p></Card>
              </div>
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Artifact overview</h3>
                  <Pill tone="default">{artifactOverview.evidenceCount} records</Pill>
                </div>
                <p className="artifact-inline-summary">
                  Normalized traces are surfaced first so later agents and operators do not have to reconstruct completion state from provider blobs.
                </p>
                <div style={styles.ledgerGrid}>
                  <Card style={styles.summaryCard}>
                    <strong>Changed files</strong>
                    <p>{artifactOverview.filesChanged.length} normalized entries</p>
                    <small style={styles.helperText}>Artifact index first.</small>
                  </Card>
                  <Card style={styles.summaryCard}>
                    <strong>Tests run</strong>
                    <p>{artifactOverview.testsRun.length} verification traces</p>
                    <small style={styles.helperText}>Pulled from evidence and dispatches.</small>
                  </Card>
                  <Card style={styles.summaryCard}>
                    <strong>Review findings</strong>
                    <p>{artifactOverview.reviewFindings.length} captured findings</p>
                    <small style={styles.helperText}>Only shows normalized findings.</small>
                  </Card>
                  <Card style={styles.summaryCard}>
                    <strong>Known risks</strong>
                    <p>{artifactOverview.knownRisks.length} tracked risks</p>
                    <small style={styles.helperText}>{artifactOverview.dispatchCount} dispatches inspected.</small>
                  </Card>
                </div>
              </section>
              {taskOrigin ? (
                <section style={styles.artifactSection}>
                  <div style={styles.artifactHeader}>
                    <h3 style={styles.artifactHeading}>Task origin</h3>
                    <Pill tone="default">reuse-aware</Pill>
                  </div>
                  <p className="artifact-inline-summary">
                    Launch context is preserved as durable task metadata so reused workflows remain legible long after the original session ends.
                  </p>
                  <Card style={styles.summaryCard}>
                    <strong>{taskOrigin.launchSummary ?? "Recorded task origin"}</strong>
                    <p>{taskOrigin.launchDetail ?? "Sarathi preserved this task's launch and reuse context so later operators do not have to reconstruct it from chat history."}</p>
                    <div style={styles.provenanceDetailList}>
                      {taskOrigin.workflowLineage.length > 0 ? (
                        <div style={styles.findingDetailItem}>
                          <strong>Workflow lineage</strong>
                          <span>{taskOrigin.workflowLineage.join(" · ")}</span>
                        </div>
                      ) : null}
                      {taskOrigin.recommendedViews.length > 0 ? (
                        <div style={styles.findingDetailItem}>
                          <strong>Recommended views</strong>
                          <span>{taskOrigin.recommendedViews.join(", ")}</span>
                        </div>
                      ) : null}
                      {taskOrigin.launchPosture.length > 0 ? (
                        <div style={styles.findingDetailItem}>
                          <strong>Launch posture</strong>
                          <span>{taskOrigin.launchPosture.join(" · ")}</span>
                        </div>
                      ) : null}
                    </div>
                  </Card>
                </section>
              ) : null}
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Changed files</h3>
                  <Pill tone="active">{artifactOverview.filesChanged.length}</Pill>
                </div>
                <div style={styles.artifactList}>
                  {artifactOverview.filesChanged.length > 0 ? artifactOverview.filesChanged.map((file) => (
                    <div key={file} style={styles.artifactListItem}>{file}</div>
                  )) : (
                    <div style={styles.artifactEmpty}>No normalized changed-file list is attached yet.</div>
                  )}
                </div>
              </section>
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Tests run</h3>
                  <Pill tone="healthy">{artifactOverview.testsRun.length}</Pill>
                </div>
                <div style={styles.artifactList}>
                  {artifactOverview.testsRun.length > 0 ? artifactOverview.testsRun.map((test) => (
                    <div key={test} style={styles.artifactListItem}>{test}</div>
                  )) : (
                    <div style={styles.artifactEmpty}>No normalized test trace is attached yet.</div>
                  )}
                </div>
              </section>
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Known risks</h3>
                  <Pill tone="warning">{artifactOverview.knownRisks.length}</Pill>
                </div>
                <div style={styles.artifactList}>
                  {artifactOverview.knownRisks.length > 0 ? artifactOverview.knownRisks.map((risk) => (
                    <div key={risk} style={styles.artifactListItem}>{risk}</div>
                  )) : (
                    <div style={styles.artifactEmpty}>No normalized risk list is attached yet.</div>
                  )}
                </div>
              </section>
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Review findings</h3>
                  <Pill tone="default">{artifactOverview.reviewFindings.length}</Pill>
                </div>
                <div style={styles.artifactList}>
                  {artifactOverview.reviewFindings.length > 0 ? artifactOverview.reviewFindings.map((finding, index) => {
                    const location = formatFindingLocation(finding);
                    const traceOrigin = formatFindingTraceOrigin(finding.source);
                    const hasExpandedDetails = Boolean(
                      finding.excerpt ||
                      finding.suggestion ||
                      finding.acId ||
                      finding.criterion ||
                      finding.confidence != null ||
                      traceOrigin ||
                      finding.provider ||
                      finding.category ||
                      finding.header,
                    );
                    return (
                      <Card key={`${finding.message.slice(0, 48)}-${index}`} style={styles.findingCard}>
                        <div style={styles.findingHeader}>
                          <Pill tone={findingSeverityTone(finding.severity)}>
                            {finding.severity ?? "finding"}
                          </Pill>
                          {location ? <span style={styles.findingMeta}>{location}</span> : null}
                          {finding.check ? <span style={styles.findingMeta}>{finding.check}</span> : null}
                        </div>
                        <p style={styles.findingMessage}>{finding.message}</p>
                        {hasExpandedDetails ? (
                          <details style={styles.findingDetails}>
                            <summary style={styles.findingDetailsSummary}>Trace and remediation</summary>
                            <div style={styles.findingDetailGrid}>
                              {traceOrigin ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>{traceOrigin.label}</strong>
                                  <span>{traceOrigin.detail}</span>
                                </div>
                              ) : null}
                              {finding.provider ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Provider</strong>
                                  <span>{finding.provider}</span>
                                </div>
                              ) : null}
                              {finding.header ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Header</strong>
                                  <span>{finding.header}</span>
                                </div>
                              ) : null}
                              {finding.category ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Category</strong>
                                  <span>{finding.category}</span>
                                </div>
                              ) : null}
                              {finding.acId ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Acceptance criteria</strong>
                                  <span>{finding.acId}</span>
                                </div>
                              ) : null}
                              {finding.criterion ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Criterion</strong>
                                  <span>{finding.criterion}</span>
                                </div>
                              ) : null}
                              {finding.confidence != null ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Confidence</strong>
                                  <span>{Math.round(finding.confidence * 100)}%</span>
                                </div>
                              ) : null}
                              {finding.excerpt ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Excerpt</strong>
                                  <span>{finding.excerpt}</span>
                                </div>
                              ) : null}
                              {finding.suggestion ? (
                                <div style={styles.findingDetailItem}>
                                  <strong>Suggestion</strong>
                                  <span>{finding.suggestion}</span>
                                </div>
                              ) : null}
                            </div>
                          </details>
                        ) : null}
                      </Card>
                    );
                  }) : (
                    <div style={styles.artifactEmpty}>No normalized review findings are attached yet.</div>
                  )}
                </div>
              </section>
              <section style={styles.artifactSection}>
                <div style={styles.artifactHeader}>
                  <h3 style={styles.artifactHeading}>Artifact provenance</h3>
                  <Pill tone="default">normalized-first</Pill>
                </div>
                <p className="artifact-inline-summary">
                  Every category shows whether Sarathi is reading from normalized contracts first or falling back to lower-level provider evidence.
                </p>
                <div style={styles.artifactList}>
                  {([
                    ["Changed files", artifactOverview.provenance.filesChanged],
                    ["Tests run", artifactOverview.provenance.testsRun],
                    ["Known risks", artifactOverview.provenance.knownRisks],
                    ["Review findings", artifactOverview.provenance.reviewFindings],
                  ] as Array<[string, ArtifactProvenanceEntry[]]>).map(([label, provenanceEntries]) => (
                    <details key={label} style={styles.provenanceCard}>
                      <summary style={styles.provenanceSummary}>
                        <strong>{label}</strong>
                        <span style={styles.provenanceSummaryText}>
                          {provenanceEntries.length > 0
                            ? provenanceEntries.map((entry) => entry.label).join(" · ")
                            : "No artifact source recorded yet."}
                        </span>
                      </summary>
                      <div style={styles.provenanceDetailList}>
                        {provenanceEntries.length > 0 ? provenanceEntries.map((entry) => (
                          <div key={`${label}-${entry.detail}`} style={styles.findingDetailItem}>
                            <strong>{entry.label}</strong>
                            <span>{entry.detail}</span>
                          </div>
                        )) : (
                          <div style={styles.artifactEmpty}>This category has not emitted normalized provenance yet.</div>
                        )}
                      </div>
                    </details>
                  ))}
                </div>
              </section>
              {artifactOverview.dispatchSummaries.length > 0 ? (
                <section style={styles.artifactSection}>
                  <div style={styles.artifactHeader}>
                    <h3 style={styles.artifactHeading}>Dispatch inspectors</h3>
                    <Pill tone="default">{artifactOverview.dispatchSummaries.length}</Pill>
                  </div>
                  <p className="artifact-inline-summary">
                    Each dispatch card keeps the headline outcome visible first, with richer trace origin preserved below for deeper inspection.
                  </p>
                  <div style={styles.artifactList}>
                    {artifactOverview.dispatchSummaries.map((dispatch) => (
                      <Card key={dispatch.id} style={styles.summaryCard}>
                        <div style={styles.dispatchInspectorHeader}>
                          <strong>{dispatch.agent} · {dispatch.status}</strong>
                          {dispatch.nextAgent ? <Pill tone="draft">Next {dispatch.nextAgent}</Pill> : null}
                        </div>
                        <p>{dispatch.summary ?? "No summary recorded."}</p>
                        <small style={styles.helperText}>
                          {dispatch.filesChangedCount} files · {dispatch.testsRunCount} tests · {dispatch.reviewFindingsCount} findings · {dispatch.knownRisksCount} risks
                        </small>
                        {dispatch.traceSources.length > 0 ? (
                          <div style={styles.provenanceDetailList}>
                            {dispatch.traceSources.map((entry) => (
                              <div key={`${dispatch.id}-${entry.label}-${entry.detail}`} style={styles.findingDetailItem}>
                                <strong>{entry.label}</strong>
                                <span>{entry.detail}</span>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </Card>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          </section>
        </div>
      )}

      {selectedTab === "lifecycle" && (
        <section style={styles.panel}>
          <PanelTitle title="Agent lifecycle" badge={operations ? "SQLite" : "demo"} />
          <p style={styles.helperText}>Role flow, review loop, and handoff state for this workspace. Sarathi's spine is visible here.</p>
          <table style={styles.table}>
            <thead>
              <tr>
                <th>Role</th>
                <th>Name</th>
                <th>Status</th>
                <th>Signals</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              {lifecycleRows.map((role, index) => (
                <tr key={role.name}>
                  <td style={styles.mono}>{String(index + 1).padStart(2, "0")}</td>
                  <td>{role.name}</td>
                  <td><Pill tone={stateTone(role.state)}>{role.state}</Pill></td>
                  <td style={styles.mono}>{role.event_count}</td>
                  <td style={styles.muted}>{role.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ marginTop: 24, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
            <PanelTitle title="Task governance" badge="live" />
            <p style={styles.helperText}>Governance posture for this task including repository actions and routing.</p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginTop: 12 }}>
              <Card style={{ padding: 14 }}>
                <strong style={{ fontSize: "0.8rem" }}>Repository action</strong>
                <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: "0.82rem" }}>
                  {(liveSnapshot?.task.metadata?.repository_action_preference as { mode?: string })?.mode ?? "no_action"} - {(liveSnapshot?.task.metadata?.repository_action_preference as { scope?: string })?.scope ?? "default"}
                </p>
              </Card>
              <Card style={{ padding: 14 }}>
                <strong style={{ fontSize: "0.8rem" }}>Routing leader</strong>
                <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: "0.82rem" }}>
                  {liveOps.governance?.provider_routing.selected_provider ?? "local"}
                </p>
              </Card>
              <Card style={{ padding: 14 }}>
                <strong style={{ fontSize: "0.8rem" }}>Repository actions</strong>
                <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: "0.82rem" }}>
                  {liveOps.governance?.repository_action_governance.approved_count ?? 0} approved / {liveOps.governance?.repository_action_governance.pending_count ?? 0} pending
                </p>
              </Card>
              <Card style={{ padding: 14 }}>
                <strong style={{ fontSize: "0.8rem" }}>Policy source</strong>
                <p style={{ margin: "8px 0 0", color: "var(--muted)", fontSize: "0.82rem" }}>
                  {liveOps.governance?.policy_posture.provider_priority_source ?? "default"}
                </p>
              </Card>
            </div>
            {liveOps.governance?.override_history && liveOps.governance.override_history.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <strong style={{ fontSize: "0.8rem" }}>Recent governance overrides</strong>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                  {liveOps.governance.override_history.slice(0, 5).map((entry) => (
                    <span key={entry.id} style={{ fontSize: "0.72rem", padding: "4px 8px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                      {entry.event_type}: {entry.summary}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {selectedTab === "history" && (
        <section style={styles.panel}>
          <PanelTitle title="Audit trail" badge={operations ? "SQLite" : "demo"} />
          <p style={styles.helperText}>Chronological record of task, provider, review, and artifact events.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 16 }}>
            <Card style={styles.summaryCard}>
              <strong>Governance overrides</strong>
              <p style={{ margin: "8px 0 0" }}>{taskGovernanceOverrides.length} recent governance event{taskGovernanceOverrides.length === 1 ? "" : "s"} affect this task or workspace.</p>
            </Card>
            <Card style={styles.summaryCard}>
              <strong>Repository actions</strong>
              <p style={{ margin: "8px 0 0" }}>{taskRepositoryGovernance.length} decision record{taskRepositoryGovernance.length === 1 ? "" : "s"} captured for the selected task.</p>
            </Card>
          </div>
          {(taskGovernanceOverrides.length > 0 || taskRepositoryGovernance.length > 0) && (
            <div style={{ ...styles.timeline, marginBottom: 18 }}>
              {taskGovernanceOverrides.map((event) => (
                <div key={event.id} style={styles.timelineItem}>
                  <span style={styles.timelineTime}>{formatTime(event.created_at)}</span>
                  <span style={{ ...styles.timelineDot, background: event.severity === "warning" ? "#d97706" : "#2f6fdf" }} />
                  <div style={styles.timelineBody}>
                    <div style={styles.timelineTitle}>{event.event_type}</div>
                    <div style={styles.timelineMeta}>{event.summary}</div>
                  </div>
                </div>
              ))}
              {taskRepositoryGovernance.map((entry) => (
                <div key={entry.id} style={styles.timelineItem}>
                  <span style={styles.timelineTime}>{formatTime(entry.created_at)}</span>
                  <span style={{ ...styles.timelineDot, background: entry.status === "approved" ? "#1f8f5f" : "#d97706" }} />
                  <div style={styles.timelineBody}>
                    <div style={styles.timelineTitle}>repository_action.{entry.status}</div>
                    <div style={styles.timelineMeta}>{entry.summary}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={styles.timeline}>
            {historyRows.map((event) => {
              const payload = event.payload as Record<string, unknown>;
              const severity = String(payload.severity ?? "info");
              return (
                <div key={event.id} style={styles.timelineItem}>
                  <span style={styles.timelineTime}>{formatTime(event.created_at)}</span>
                  <span style={{ ...styles.timelineDot, background: severity === "warning" ? "#d97706" : severity === "active" ? "#2f6fdf" : "#6b7280" }} />
                  <div style={styles.timelineBody}>
                    <div style={styles.timelineTitle}>{event.event_type}</div>
                    <div style={styles.timelineMeta}>{historySummary(event)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {selectedTab === "usage" && (
        <>
          <div style={styles.metricGrid}>
            <Card style={styles.metricCard}><strong>{usage.tasks.total}</strong><p>Tasks total</p></Card>
            <Card style={styles.metricCard}><strong>{usage.tasks.active}</strong><p>Active tasks</p></Card>
            <Card style={styles.metricCard}><strong>{usage.tasks.done}</strong><p>Completed tasks</p></Card>
            <Card style={styles.metricCard}><strong>{usage.subtasks.total}</strong><p>Graph units</p></Card>
            <Card style={styles.metricCard}><strong>{usage.providers.online}/{usage.providers.total}</strong><p>Providers online</p></Card>
            <Card style={styles.metricCard}><strong>{usage.events.total}</strong><p>Events</p></Card>
            <Card style={styles.metricCard}><strong>{usage.messages.total}</strong><p>Messages</p></Card>
            <Card style={styles.metricCard}><strong>{usage.handoffs.total}</strong><p>Handoffs</p></Card>
            <Card style={styles.metricCard}><strong>{governance?.override_history?.length ?? 0}</strong><p>Overrides</p></Card>
            <Card style={styles.metricCard}><strong>{governance?.repository_action_governance?.approved_count ?? 0}</strong><p>Repo actions approved</p></Card>
          </div>
          <section style={styles.panel}>
            <PanelTitle title="Workspace usage" badge={operations ? "SQLite" : "demo"} />
            <div style={styles.helperText}>
              <p style={{ margin: 0 }}>Repositories: {usage.repositories.total}</p>
              <p style={{ margin: 0 }}>Reviews: {usage.reviews.total}</p>
              <p style={{ margin: 0 }}>Evidence artifacts: {usage.evidence.total}</p>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    paddingBottom: 28,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "flex-start",
  },
  eyebrow: {
    fontSize: "0.76rem",
    color: "var(--faint)",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    marginBottom: 8,
  },
  title: {
    margin: 0,
    fontSize: "2rem",
    lineHeight: 1.1,
    letterSpacing: "-0.03em",
  },
  subtitle: {
    margin: "10px 0 0",
    color: "var(--muted)",
    maxWidth: 760,
  },
  headerActions: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    flexShrink: 0,
  },
  statusStrip: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  cockpitStrip: {
    display: "flex",
    alignItems: "center",
    gap: 0,
    padding: "12px 16px",
    borderRadius: "var(--radius-lg)",
    border: "1px solid var(--border)",
    background: "var(--surface)",
    overflowX: "auto",
  },
  cockpitSection: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 4,
    padding: "4px 12px",
    minWidth: 70,
  },
  cockpitLabel: {
    fontSize: "0.65rem",
    fontWeight: 600,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  cockpitValue: {
    fontSize: "1.1rem",
    fontWeight: 700,
    color: "var(--ink)",
    letterSpacing: "-0.02em",
  },
  cockpitDivider: {
    width: 1,
    height: 32,
    background: "var(--border)",
  },
  taskRail: {
    display: "flex",
    flexDirection: "row",
    gap: 10,
    overflowX: "auto",
    paddingBottom: 8,
    maxWidth: "100%",
  },
  taskCard: {
    textAlign: "left",
    padding: "10px 14px",
    borderRadius: 14,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    boxShadow: "var(--shadow-sm)",
    minWidth: 200,
    maxWidth: 260,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    gap: 4,
    height: "auto",
    whiteSpace: "normal",
    lineHeight: "inherit",
  },
  taskCardActive: {
    borderColor: "var(--accent)",
    background: "var(--active)",
    boxShadow: "0 0 0 1px var(--accent)",
  },
  taskCardRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  taskCardId: {
    fontWeight: 700,
    fontSize: "0.78rem",
    color: "var(--ink)",
    fontFamily: "var(--mono)",
    letterSpacing: "0.02em",
  },
  taskCardStatus: {
    fontSize: "0.66rem",
    padding: "2px 6px",
  },
  taskCardTitleRow: {
    minWidth: 0,
  },
  taskCardTitle: {
    fontWeight: 600,
    color: "var(--ink)",
    fontSize: "0.86rem",
    lineHeight: 1.3,
  },
  taskCardMetaRow: {
    marginTop: 2,
  },
  taskCardMeta: {
    color: "var(--muted)",
    fontSize: "0.72rem",
    lineHeight: 1.3,
  },
  tabBar: {
    display: "inline-flex",
    gap: 6,
    padding: 4,
    borderRadius: 14,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    width: "fit-content",
  },
  tabButton: {
    border: "none",
    background: "transparent",
    padding: "8px 14px",
    borderRadius: 10,
    color: "var(--muted)",
    fontWeight: 600,
  },
  tabButtonActive: {
    background: "var(--accent-a3)",
    color: "var(--ink)",
  },
  studioGrid: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.2fr) minmax(340px, 0.8fr)",
    gap: 16,
    alignItems: "start",
  },
  leftColumn: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0,
  },
  rightColumn: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0,
  },
  panel: {
    borderRadius: 20,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    padding: 16,
    boxShadow: "var(--shadow-sm)",
  },
  metaRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 10,
    marginBottom: 12,
  },
  actionRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  helperText: {
    color: "var(--muted)",
    fontSize: "0.82rem",
    margin: "12px 0 0",
  },
  summaryCard: {
    padding: 12,
    marginTop: 10,
  },
  deliveryHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  deliverySummary: {
    margin: "8px 0 0",
  },
  deliveryMetricGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 10,
    marginTop: 12,
  },
  deliveryMetricCard: {
    padding: 12,
    marginTop: 0,
  },
  deliverySection: {
    display: "grid",
    gap: 10,
    marginTop: 14,
    paddingTop: 12,
    borderTop: "1px solid var(--border)",
  },
  deliveryCopyBlock: {
    display: "grid",
    gap: 10,
  },
  deliveryDetailRow: {
    display: "grid",
    gap: 4,
  },
  deliveryChecklist: {
    display: "grid",
    gap: 8,
  },
  deliveryChecklistItem: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: "10px 12px",
    background: "var(--canvas)",
    fontSize: "0.82rem",
    color: "var(--ink)",
    display: "grid",
    gap: 6,
  },
  deliveryChecklistLead: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    color: "var(--muted)",
    fontSize: "0.74rem",
    fontFamily: "var(--mono)",
  },
  deliveryChecklistMark: {
    color: "var(--ink)",
    fontWeight: 600,
  },
  deliveryChecklistId: {
    color: "var(--muted)",
  },
  deliveryMissingList: {
    display: "grid",
    gap: 8,
  },
  deliveryMissingItem: {
    border: "1px dashed var(--border)",
    borderRadius: 12,
    padding: "10px 12px",
    background: "var(--canvas)",
    fontSize: "0.8rem",
    color: "var(--muted)",
  },
  checkpointHistoryItem: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: 10,
    background: "var(--canvas)",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  checkpointHistoryHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  checkpointSummary: {
    margin: 0,
  },
  checkpointMetaRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    color: "var(--muted)",
    fontSize: "0.75rem",
  },
  checkpointDecisions: {
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
  },
  checkpointDecisionPill: {
    display: "inline-flex",
    alignItems: "center",
    padding: "3px 8px",
    borderRadius: 999,
    background: "var(--surface-2)",
    color: "var(--ink)",
    fontSize: "0.75rem",
    border: "1px solid var(--border)",
  },
  ledgerGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 10,
  },
  artifactSection: {
    display: "grid",
    gap: 8,
    marginTop: 12,
  },
  artifactHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  artifactHeading: {
    margin: 0,
    fontSize: "0.86rem",
  },
  artifactList: {
    display: "grid",
    gap: 8,
  },
  artifactListItem: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: "10px 12px",
    background: "var(--canvas)",
    fontSize: "0.82rem",
    color: "var(--ink)",
  },
  artifactEmpty: {
    border: "1px dashed var(--border)",
    borderRadius: 12,
    padding: "12px",
    background: "var(--canvas)",
    fontSize: "0.8rem",
    color: "var(--muted)",
  },
  findingCard: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: "10px 12px",
    background: "var(--surface)",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  findingHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  findingMeta: {
    fontSize: "0.72rem",
    color: "var(--muted)",
    fontFamily: "var(--mono)",
  },
  findingMessage: {
    margin: 0,
    fontSize: "0.82rem",
    color: "var(--ink)",
    lineHeight: 1.4,
  },
  findingDetails: {
    borderTop: "1px solid var(--border)",
    paddingTop: 8,
  },
  findingDetailsSummary: {
    cursor: "pointer",
    color: "var(--muted)",
    fontSize: "0.76rem",
    listStyle: "none",
  },
  findingDetailGrid: {
    display: "grid",
    gap: 8,
    marginTop: 8,
  },
  findingDetailItem: {
    display: "grid",
    gap: 4,
    border: "1px solid var(--border)",
    borderRadius: 10,
    padding: "8px 10px",
    background: "var(--canvas)",
    fontSize: "0.76rem",
    color: "var(--muted)",
  },
  provenanceCard: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: "10px 12px",
    background: "var(--surface)",
  },
  provenanceSummary: {
    cursor: "pointer",
    display: "grid",
    gap: 4,
    color: "var(--ink)",
  },
  provenanceSummaryText: {
    color: "var(--muted)",
    fontSize: "0.76rem",
  },
  provenanceDetailList: {
    display: "grid",
    gap: 8,
    marginTop: 10,
  },
  dispatchInspectorHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  metricGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 12,
  },
  metricCard: {
    padding: 16,
    textAlign: "left",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    marginTop: 8,
  },
  mono: {
    fontFamily: "var(--mono)",
    color: "var(--muted)",
    fontSize: "0.8rem",
    whiteSpace: "nowrap",
  },
  muted: {
    color: "var(--muted)",
  },
  timeline: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    marginTop: 10,
  },
  timelineItem: {
    display: "grid",
    gridTemplateColumns: "72px 10px 1fr",
    gap: 12,
    alignItems: "start",
  },
  timelineTime: {
    color: "var(--faint)",
    fontFamily: "var(--mono)",
    fontSize: "0.75rem",
    paddingTop: 2,
  },
  timelineDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    marginTop: 6,
  },
  timelineBody: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
  },
  timelineTitle: {
    fontWeight: 600,
    color: "var(--ink)",
  },
  timelineMeta: {
    color: "var(--muted)",
    fontSize: "0.82rem",
  },
  secondaryButton: {
    border: "1px solid var(--border)",
    background: "var(--panel)",
    color: "var(--ink)",
    borderRadius: 12,
    height: 36,
    padding: "0 14px",
    fontWeight: 600,
  },
  primaryButton: {
    border: "1px solid var(--accent)",
    background: "var(--accent)",
    color: "#fff",
    borderRadius: 12,
    height: 36,
    padding: "0 14px",
    fontWeight: 700,
  },
};
