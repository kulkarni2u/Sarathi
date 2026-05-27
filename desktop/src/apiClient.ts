export type RepositoryIntakePreview = {
  path: string;
  name: string;
  exists: boolean;
  is_directory: boolean;
  is_git_repo: boolean;
  branch: string | null;
  remote_url: string | null;
  dirty: boolean;
  changes: string[];
  sarathi_initialized: boolean;
  recommended_mode: string;
  requires_interview: boolean;
  warnings: string[];
  would_create: string[];
};

export type WorkspaceRepositoryRecord = {
  id: string;
  workspace_id: string;
  name: string | null;
  path: string;
  remote_url: string | null;
  metadata: {
    intake?: RepositoryIntakePreview;
    approved?: boolean;
    sarathi_initialization?: RepositoryInitializationResult;
  };
  created_at: string;
  updated_at: string;
};

export type RepositoryActionPreferenceRecord = {
  scope: "default" | "workspace" | "project" | "task" | string;
  mode: "no_action" | "prepare_patch" | "commit" | "draft_pr" | "ready_pr" | string;
  allowed_modes: Array<"no_action" | "prepare_patch" | "commit" | "draft_pr" | "ready_pr" | string>;
  source?: string;
};

export type AutoApprovePreferenceRecord = {
  scope: "default" | "workspace" | "project" | "task" | string;
  mode: "manual_only" | "below_threshold" | string;
  allowed_modes: Array<"manual_only" | "below_threshold" | string>;
  threshold?: {
    complexity?: string;
    max_node_count?: number;
  };
  source?: string;
};

export const defaultRepositoryActionPreference: RepositoryActionPreferenceRecord = {
  scope: "default",
  mode: "no_action",
  allowed_modes: ["no_action", "prepare_patch", "commit", "draft_pr", "ready_pr"],
};

export const defaultAutoApprovePreference: AutoApprovePreferenceRecord = {
  scope: "default",
  mode: "manual_only",
  allowed_modes: ["manual_only", "below_threshold"],
};

export type TaskMetadata = {
  source_prompt?: string;
  complexity?: string;
  phase?: string;
  source?: string;
  prd?: {
    problem?: string;
    goal?: string;
    scope?: string[];
  };
  acceptance_criteria?: string[];
  repository_action_preference?: RepositoryActionPreferenceRecord;
  project_repository_action_preference?: RepositoryActionPreferenceRecord;
  github_issue?: {
    url?: string | null;
    host?: string | null;
    owner?: string | null;
    name?: string | null;
    full_name?: string | null;
    number?: number | null;
    repository_url?: string | null;
    reference?: string | null;
    repository?: Record<string, unknown>;
  };
  repository?: Record<string, unknown>;
  reuse?: {
    reuse_source?: {
      kind?: string;
      id?: string | null;
      name?: string | null;
    };
    workflow_template_id?: string;
    learning_playbook_id?: string;
    recommended_view_ids?: string[];
    recommended_repository_action_mode?: string;
    recommended_auto_approve_mode?: string;
    suggested_provider_priority?: string[];
  };
} & Record<string, unknown>;

export type WorkspaceMetadata = {
  repository_action_preference?: RepositoryActionPreferenceRecord;
  auto_approve_preference?: AutoApprovePreferenceRecord;
  provider_priority?: string[];
  reuse_preferences?: {
    active_saved_view_id?: string;
    custom_saved_views?: Array<{
      id: string;
      name: string;
      role: string;
      route: string;
      description: string;
      metric_label: string;
      filters: Record<string, unknown>;
    }>;
  };
} & Record<string, unknown>;

export type WorkspaceRecord = {
  id: string;
  name: string;
  root_path: string;
  metadata: WorkspaceMetadata;
  created_at: string;
  updated_at: string;
};

export type RepositoryInitializationResult = {
  status: string;
  mode: string;
  created_files: string[];
  interview: Record<string, unknown>;
};

export type TaskRecord = {
  id: string;
  workspace_id: string;
  title: string;
  description: string | null;
  status: string;
  metadata: TaskMetadata;
  created_at: string;
  updated_at: string;
};

export type CheckpointCapsuleRecord = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  source_task_id: string;
  status: string;
  summary: string;
  key_decisions: string[];
  evidence_refs: string[];
  repository_action_preference: RepositoryActionPreferenceRecord;
  next_start_point: string;
  created_at: string;
  created_by: string;
};

export type ApprovalGateRecord = {
  id: string;
  workspace_id: string;
  task_id: string;
  name: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MessageRecord = {
  id: string;
  workspace_id: string;
  task_id: string | null;
  role: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type LifecycleEventRecord = {
  id: string;
  workspace_id: string;
  task_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type DispatchRecord = {
  id: string;
  workspace_id: string;
  task_id: string;
  agent_name: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvidenceArtifactRecord = {
  id: string;
  workspace_id: string;
  task_id: string;
  artifact_type: string;
  uri: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ProviderHealthRecord = {
  id: string;
  name: string;
  provider_type: string;
  transport_kind?: string;
  transport_posture?: string;
  health: string;
  auth: string;
  path: string;
  capabilities: string[];
  api_key_configured?: boolean;
  base_url?: string | null;
  model?: string | null;
  degraded_reason?: string | null;
  last_checked_at?: string | null;
  last_error?: string | null;
};

export type ProviderConnectionDraft = {
  path: string;
  auth: string;
  api_key?: string;
  base_url?: string;
  model?: string;
};

export type ReviewRunRecord = {
  id: string;
  workspace_id: string;
  task_id: string;
  status: string;
  summary: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type HandoffRecord = {
  id: string;
  workspace_id: string;
  task_id: string;
  from_agent: string | null;
  to_agent: string | null;
  summary: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type TaskDraftResult = {
  task: TaskRecord;
  approval_gate: ApprovalGateRecord;
  messages: MessageRecord[];
};

export type TaskGraphNode = {
  id: string;
  title: string;
  status: string;
  role: string;
  provider: string;
  blocked_by: string[];
  evidence_required: string[];
  task_packet: {
    goal?: string;
    context?: string;
    review_criteria?: string[];
  };
};

export type TaskGraph = {
  task_id: string;
  nodes: TaskGraphNode[];
  edges: Array<{
    from: string;
    to: string;
    type: string;
  }>;
};

export type TaskGraphDraftResult = {
  graph: TaskGraph;
  approval_gate: ApprovalGateRecord;
};

export type TaskStudioSnapshot = {
  task: TaskRecord;
  graph: TaskGraph;
  header?: TaskStudioHeader;
  messages: MessageRecord[];
  approval_gates: ApprovalGateRecord[];
  events: LifecycleEventRecord[];
  dispatches: DispatchRecord[];
  evidence: EvidenceArtifactRecord[];
  reviews: ReviewRunRecord[];
  handoff: HandoffRecord | null;
};

export type TaskPanelEntry = {
  id: string;
  kind:
    | "human_message"
    | "agent_update"
    | "blocked"
    | "unblocked"
    | "claimed"
    | "in_progress"
    | "review"
    | "handoff"
    | "completion"
    | "evidence"
    | "system_note";
  source: string;
  target: string | null;
  summary: string;
  created_at: string;
  metadata: Record<string, unknown>;
  task_id: string;
  workspace_id: string;
};

export type TaskPanelSnapshot = {
  task_id: string;
  entries: TaskPanelEntry[];
};

export type TaskScheduleResult = {
  task: TaskRecord;
  scheduled: Array<{
    id: string;
    workspace_id: string;
    task_id: string;
    title: string;
    status: string;
    metadata: Record<string, unknown>;
    created_at: string;
    updated_at: string;
  }>;
  blocked: string[];
};

export type SubtaskTransitionResult = {
  subtask: TaskScheduleResult["scheduled"][number];
  unblocked: TaskScheduleResult["scheduled"];
};

export type SubtaskDispatchResult = {
  subtask: TaskScheduleResult["scheduled"][number];
  dispatch: DispatchRecord;
  evidence: EvidenceArtifactRecord | null;
};

export type ReviewRunResult = {
  review: ReviewRunRecord;
  completed_subtasks: TaskScheduleResult["scheduled"];
  requeued_subtasks: TaskScheduleResult["scheduled"];
};

export type HandoffResult = {
  handoff: HandoffRecord;
  repository_action_gate: ApprovalGateRecord;
};

export type RepositoryActionResult = {
  handoff: HandoffRecord;
  repository_action: {
    status: string;
    action: string;
    note?: string | null;
  };
  approval_gate: ApprovalGateRecord;
};

export type OperationalLifecycleRole = {
  key: string;
  name: string;
  purpose: string;
  description: string;
  state: string;
  event_count: number;
};

export type OperationalDiagram = {
  id: string;
  kind: string;
  title: string;
  task_id?: string;
  nodes?: unknown[];
  edges?: unknown[];
  summary?: string;
  repository_action?: Record<string, unknown>;
  updated_at?: string;
};

export type TokenBudgetSummary = {
  total_tokens: number;
  budget_limit: number | null;
  budget_remaining: number | null;
  budget_state: string;
  usage_source: string;
};

export type WorkspaceOperationalProjectSummary = {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: string;
  task_count: number;
  blocked_count: number;
  review_needed_count: number;
  approval_pending_count: number;
  checkpoint_ready_count: number;
  handoff_ready_count: number;
  updated_at: string;
  created_at: string;
};

export type GovernanceHistoryEntry = {
  id: string;
  event_type: string;
  task_id?: string | null;
  summary: string;
  severity: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type RepositoryActionGovernanceRecord = {
  id: string;
  task_id: string;
  title: string;
  summary: string;
  status: string;
  action: string;
  mode: string;
  created_at: string;
};

export type WorkspaceGovernanceSnapshot = {
  policy_posture: {
    repository_action_preference: RepositoryActionPreferenceRecord;
    auto_approve_preference: AutoApprovePreferenceRecord;
    provider_priority: string[];
    provider_priority_source: string;
  };
  provider_routing: {
    priority_order: string[];
    selected_provider: string;
    fallback_candidates: string[];
    provider_health: Record<string, string>;
    providers: Array<{
      id: string;
      name: string;
      health: string;
      auth: string;
      transport_posture?: string | null;
      degraded_reason?: string | null;
      last_error?: string | null;
      model?: string | null;
    }>;
  };
  override_history: GovernanceHistoryEntry[];
  repository_action_governance: {
    pending_count: number;
    approved_count: number;
    recent: RepositoryActionGovernanceRecord[];
  };
};

export type OperationalViewsSnapshot = {
  workspace_id: string;
  summary: {
    project_count: number;
    approvals_pending: number;
    checkpoint_ready_count: number;
    handoff_ready_count: number;
    provider_online_count: number;
  };
  projects: WorkspaceOperationalProjectSummary[];
  inbox: InboxQueueItem[];
  history: LifecycleEventRecord[];
  lifecycle: OperationalLifecycleRole[];
  diagrams: OperationalDiagram[];
  governance: WorkspaceGovernanceSnapshot;
  usage: {
    tasks: { total: number; active: number; done: number; by_status: Record<string, number> };
    subtasks: { total: number; by_status: Record<string, number> };
    events: { total: number; by_type: Record<string, number> };
    messages: { total: number; by_role: Record<string, number> };
    repositories: { total: number };
    dispatches: { total: number; by_status: Record<string, number> };
    budget?: TokenBudgetSummary | null;
    evidence: { total: number; by_type: Record<string, number> };
    reviews: { total: number; by_status: Record<string, number> };
    handoffs: { total: number };
    providers: { total: number; online: number; by_health: Record<string, number> };
  };
};

export type WorkflowTemplateSnapshot = {
  id: string;
  name: string;
  category: string;
  summary: string;
  complexity: string;
  starter_title: string;
  recommended_repository_action_mode: string;
  recommended_auto_approve_mode: string;
  suggested_provider_priority: string[];
  recommended_view_ids: string[];
};

export type SavedViewSnapshot = {
  id: string;
  name: string;
  role: string;
  route: string;
  description: string;
  metric_label: string;
  count: number;
  filters: Record<string, unknown>;
  origin?: "builtin" | "custom" | string;
};

export type LearningPlaybookSnapshot = {
  id: string;
  name: string;
  summary: string;
  recommended_template_id: string | null;
  recommended_view_ids: string[];
  source: string;
  provenance: {
    task_id?: string | null;
    source_file?: string | null;
    event_id?: string | null;
    evidence_refs?: string[];
    tags?: string[];
  };
};

export type WorkspaceReuseKitSnapshot = {
  workspace_id: string;
  active_saved_view_id: string;
  templates: WorkflowTemplateSnapshot[];
  saved_views: SavedViewSnapshot[];
  playbooks: LearningPlaybookSnapshot[];
};

export type DogfoodAcceptanceCheck = {
  id: string;
  label: string;
  status: string;
  evidence_refs: string[];
};

export type DogfoodLearningRecord = {
  id: string;
  status: string;
  task_id: string;
  target_file: string;
  summary: string;
  tags: string[];
  evidence_refs: string[];
  acceptance_status: string;
  path?: string;
};

export type DogfoodAcceptanceSnapshot = {
  workspace_id: string;
  status: string;
  checks: DogfoodAcceptanceCheck[];
  release_dossier: {
    title: string;
    built_with: string;
    redacted: boolean;
    summary: string;
    validation_commands: string[];
  };
  learning_record: DogfoodLearningRecord;
  operations: OperationalViewsSnapshot;
};

export type DogfoodLearningResult = {
  learning_record: DogfoodLearningRecord;
  acceptance: DogfoodAcceptanceSnapshot;
};

export type OrganizedQueueState =
  | "intake"
  | "planning"
  | "awaiting_approval"
  | "ready"
  | "running"
  | "under_review"
  | "blocked"
  | "waiting_human"
  | "failed"
  | "handoff_ready"
  | "done";

export type TaskStudioHeader = {
  queue_state: OrganizedQueueState;
  approval_state: string;
  next_safe_action: string;
  repository_action_mode: string;
  checkpoint_ready: boolean;
  handoff_state: string;
};

export type TaskDashboardItem = {
  id: string;
  workspace_id: string;
  title: string;
  status: string;
  phase: string;
  approval_state: string;
  graph_state: string;
  next_gate: string | null;
  node_count: number;
  blocked_count: number;
  review_needed_count: number;
  checkpoint_state: string;
  handoff_state: string;
  roles: string[];
  providers: string[];
  updated_at: string;
};

export type OrganizedTaskSummary = TaskDashboardItem;

export type InboxQueueItem = {
  id: string;
  kind:
    | "approval"
    | "blocked_task"
    | "failed_review"
    | "checkpoint_ready"
    | "handoff_ready"
    | "provider_failure";
  workspace_id: string;
  project_id?: string | null;
  task_id?: string | null;
  title: string;
  summary: string;
  state: OrganizedQueueState;
  next_action?: string | null;
  updated_at: string;
};

type ApiEnvelope<T> =
  | {
      ok: true;
      data: T;
      correlation_id: string;
    }
  | {
      ok: false;
      error: {
        code: string;
        message: string;
        status: number;
      };
      correlation_id: string;
    };

type ApiConfig = {
  baseUrl: string;
  token: string | null;
};

type RuntimeConfig = {
  baseUrl?: string;
  token?: string | null;
};

// Default port when no explicit config is provided
const SARATHI_DEFAULT_BASE_URL = "http://127.0.0.1:8765";

export function getSarathiApiConfig(): ApiConfig | null {
  const runtime = (globalThis as typeof globalThis & {
    __SARATHI_RUNTIME_CONFIG__?: RuntimeConfig;
  }).__SARATHI_RUNTIME_CONFIG__;
  const runtimeBaseUrl = runtime?.baseUrl?.replace(/\/$/, "");
  if (runtimeBaseUrl) {
    return {
      baseUrl: runtimeBaseUrl,
      // Loopback connections don't require a token — service bypasses auth for 127.0.0.1
      token: runtime?.token ?? null,
    };
  }

  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  const baseUrl = env?.VITE_SARATHI_API_BASE_URL?.replace(/\/$/, "");
  if (baseUrl) {
    return {
      baseUrl,
      token: env?.VITE_SARATHI_API_TOKEN ?? null,
    };
  }

  // Auto-discover: default to localhost. Service bypasses token auth for loopback connections,
  // so no token is needed here. If the service isn't running, requests will fail gracefully.
  return { baseUrl: SARATHI_DEFAULT_BASE_URL, token: null };
}

export type WorkspaceProjectRecord = {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: string;
  task_count: number;
  blocked_count: number;
  updated_at: string;
  created_at: string;
};

export async function listWorkspaceProjects(workspaceId: string): Promise<WorkspaceProjectRecord[]> {
  const data = await getJson<{ projects: WorkspaceProjectRecord[] }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/projects`,
  );
  return data.projects;
}

export async function createWorkspaceProject(
  workspaceId: string,
  payload: { name: string; description?: string },
): Promise<WorkspaceProjectRecord> {
  const data = await postJson<{ project: WorkspaceProjectRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/projects`,
    payload,
  );
  return data.project;
}

export async function previewWorkspaceRepository(
  workspaceId: string,
  path: string,
): Promise<RepositoryIntakePreview> {
  const data = await postJson<{ preview: RepositoryIntakePreview }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/repositories/preview`,
    { path },
  );
  return data.preview;
}

export async function listWorkspaces(): Promise<WorkspaceRecord[]> {
  const data = await getJson<{ workspaces: WorkspaceRecord[] }>("/api/workspaces");
  return data.workspaces;
}

export async function createWorkspace(
  name: string,
  rootPath: string,
  metadata: Record<string, unknown> = {},
): Promise<WorkspaceRecord> {
  const data = await postJson<{ workspace: WorkspaceRecord }>("/api/workspaces", {
    name,
    root_path: rootPath,
    metadata,
  });
  return data.workspace;
}

export async function getWorkspace(workspaceId: string): Promise<WorkspaceRecord> {
  const data = await getJson<{ workspace: WorkspaceRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}`,
  );
  return data.workspace;
}

export async function updateWorkspace(
  workspaceId: string,
  metadata: WorkspaceMetadata,
): Promise<WorkspaceRecord> {
  const data = await patchJson<{ workspace: WorkspaceRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}`,
    { metadata },
  );
  return data.workspace;
}

export async function checkNcpAvailable(
  workspaceId: string,
): Promise<{ ncp_available: boolean }> {
  return getJson<{ ncp_available: boolean }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/ncp/status`,
  );
}

export async function ensureWorkspace(
  name: string,
  rootPath: string,
  metadata: Record<string, unknown> = {},
): Promise<WorkspaceRecord> {
  const workspaces = await listWorkspaces();
  return (
    workspaces.find((candidate) => candidate.name === name)
    ?? workspaces[0]
    ?? await createWorkspace(name, rootPath, metadata)
  );
}

export async function createTaskDraft(
  workspaceId: string,
  prompt: string,
  title?: string,
  context?: { projectId?: string; workspaceId?: string },
): Promise<TaskDraftResult> {
  return postJson<TaskDraftResult>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/task-drafts`,
    {
      prompt,
      ...(title ? { title } : {}),
      ...(context ? { context } : {}),
    },
  );
}

export async function approveTaskGate(
  taskId: string,
  name: string,
  status = "approved",
): Promise<ApprovalGateRecord> {
  const data = await postJson<{ approval_gate: ApprovalGateRecord }>(
    `/api/tasks/${encodeURIComponent(taskId)}/approve`,
    { name, status },
  );
  return data.approval_gate;
}

export async function createTaskGraphDraft(taskId: string): Promise<TaskGraphDraftResult> {
  return postJson<TaskGraphDraftResult>(
    `/api/tasks/${encodeURIComponent(taskId)}/graph-draft`,
    {},
  );
}

export async function listTaskDashboard(
  workspaceId: string,
  options: { projectId?: string | null } = {},
): Promise<TaskDashboardItem[]> {
  const params = new URLSearchParams();
  if (options.projectId) {
    params.set("project_id", options.projectId);
  }
  const data = await getJson<{ tasks: TaskDashboardItem[] }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/task-dashboard${params.size > 0 ? `?${params.toString()}` : ""}`,
  );
  return (data.tasks ?? []).map(normalizeTaskDashboardItem);
}

export async function getWorkspaceOperationalViews(
  workspaceId: string,
): Promise<OperationalViewsSnapshot> {
  const data = await getJson<Partial<OperationalViewsSnapshot>>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/operational-views`,
  );
  return normalizeOperationalViewsSnapshot(workspaceId, data);
}

export async function getWorkspaceReuseKit(
  workspaceId: string,
): Promise<WorkspaceReuseKitSnapshot> {
  const data = await getJson<Partial<WorkspaceReuseKitSnapshot>>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/reuse-kit`,
  );
  return {
    workspace_id: String(data.workspace_id ?? workspaceId),
    active_saved_view_id: String(data.active_saved_view_id ?? "all-projects"),
    templates: Array.isArray(data.templates)
      ? data.templates.map((template) => ({
          id: String(template?.id ?? ""),
          name: String(template?.name ?? "Untitled template"),
          category: String(template?.category ?? "workflow"),
          summary: String(template?.summary ?? ""),
          complexity: String(template?.complexity ?? "medium"),
          starter_title: String(template?.starter_title ?? template?.name ?? "Template run"),
          recommended_repository_action_mode: String(template?.recommended_repository_action_mode ?? "no_action"),
          recommended_auto_approve_mode: String(template?.recommended_auto_approve_mode ?? "manual_only"),
          suggested_provider_priority: Array.isArray(template?.suggested_provider_priority)
            ? template.suggested_provider_priority.filter((value): value is string => typeof value === "string")
            : [],
          recommended_view_ids: Array.isArray(template?.recommended_view_ids)
            ? template.recommended_view_ids.filter((value): value is string => typeof value === "string")
            : [],
        }))
      : [],
    saved_views: Array.isArray(data.saved_views)
      ? data.saved_views.map((view) => ({
          id: String(view?.id ?? ""),
          name: String(view?.name ?? "Saved view"),
          role: String(view?.role ?? "operator"),
          route: String(view?.route ?? "workspace"),
          description: String(view?.description ?? ""),
          metric_label: String(view?.metric_label ?? "items"),
          count: typeof view?.count === "number" ? view.count : 0,
          filters: view?.filters && typeof view.filters === "object" ? view.filters as Record<string, unknown> : {},
          origin: typeof view?.origin === "string" ? view.origin : "builtin",
        }))
      : [],
    playbooks: Array.isArray(data.playbooks)
      ? data.playbooks.map((playbook) => ({
          id: String(playbook?.id ?? ""),
          name: String(playbook?.name ?? "Accepted learning"),
          summary: String(playbook?.summary ?? ""),
          recommended_template_id: typeof playbook?.recommended_template_id === "string" ? playbook.recommended_template_id : null,
          recommended_view_ids: Array.isArray(playbook?.recommended_view_ids)
            ? playbook.recommended_view_ids.filter((value): value is string => typeof value === "string")
            : [],
          source: String(playbook?.source ?? "accepted_learning"),
          provenance: playbook?.provenance && typeof playbook.provenance === "object"
            ? {
                task_id: typeof playbook.provenance.task_id === "string" ? playbook.provenance.task_id : null,
                source_file: typeof playbook.provenance.source_file === "string" ? playbook.provenance.source_file : null,
                event_id: typeof playbook.provenance.event_id === "string" ? playbook.provenance.event_id : null,
                evidence_refs: Array.isArray(playbook.provenance.evidence_refs)
                  ? playbook.provenance.evidence_refs.filter((value): value is string => typeof value === "string")
                  : [],
                tags: Array.isArray(playbook.provenance.tags)
                  ? playbook.provenance.tags.filter((value): value is string => typeof value === "string")
                  : [],
              }
            : {},
        }))
      : [],
  };
}

export function activeSavedViewFromReuseKit(
  reuseKit: WorkspaceReuseKitSnapshot | null | undefined,
): SavedViewSnapshot | null {
  if (!reuseKit) return null;
  return reuseKit.saved_views.find((view) => view.id === reuseKit.active_saved_view_id) ?? null;
}

export function filterTaskDashboardItemsBySavedView(
  items: TaskDashboardItem[],
  savedView: SavedViewSnapshot | null | undefined,
): TaskDashboardItem[] {
  if (!savedView) return items;
  const filters = savedView.filters ?? {};
  return items.filter((item) => {
    if (filters.project_state === "blocked") return item.blocked_count > 0;
    if (filters.task_state === "handoff_ready") return item.handoff_state === "ready";
    if (filters.task_state === "checkpoint_ready") return item.checkpoint_state !== "none";
    if (filters.task_state === "approval_pending" || filters.kind === "approval") {
      return item.approval_state !== "approved" && item.approval_state !== "none";
    }
    return true;
  });
}

export function filterInboxItemsBySavedView(
  items: InboxQueueItem[],
  savedView: SavedViewSnapshot | null | undefined,
): InboxQueueItem[] {
  if (!savedView) return items;
  const filters = savedView.filters ?? {};
  return items.filter((item) => {
    if (filters.kind === "approval" || filters.task_state === "approval_pending") return item.kind === "approval";
    if (filters.project_state === "blocked") return item.kind === "blocked_task" || item.kind === "failed_review";
    if (filters.task_state === "handoff_ready") return item.kind === "handoff_ready";
    if (filters.task_state === "checkpoint_ready") return item.kind === "checkpoint_ready";
    return true;
  });
}

export async function getDogfoodAcceptance(
  workspaceId: string,
): Promise<DogfoodAcceptanceSnapshot> {
  return getJson<DogfoodAcceptanceSnapshot>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/dogfood-acceptance`,
  );
}

export async function approveDogfoodLearning(
  workspaceId: string,
): Promise<DogfoodLearningResult> {
  return postJson<DogfoodLearningResult>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/dogfood-learning`,
    { approved: true },
  );
}

export async function getTaskStudio(taskId: string): Promise<TaskStudioSnapshot> {
  const data = await getJson<TaskStudioSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/studio`);
  return {
    ...data,
    header: data.header,
  };
}

export async function getTaskPanel(taskId: string): Promise<TaskPanelSnapshot> {
  return getJson<TaskPanelSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/panel`);
}

function normalizeTaskDashboardItem(task: Partial<TaskDashboardItem>): TaskDashboardItem {
  return {
    id: String(task.id ?? ""),
    workspace_id: String(task.workspace_id ?? ""),
    title: String(task.title ?? "Untitled task"),
    status: String(task.status ?? "pending"),
    phase: String(task.phase ?? task.status ?? "planning"),
    approval_state: String(task.approval_state ?? "none"),
    graph_state: String(task.graph_state ?? "not_started"),
    next_gate: typeof task.next_gate === "string" ? task.next_gate : null,
    node_count: typeof task.node_count === "number" ? task.node_count : 0,
    blocked_count: typeof task.blocked_count === "number" ? task.blocked_count : 0,
    review_needed_count: typeof task.review_needed_count === "number" ? task.review_needed_count : 0,
    checkpoint_state: typeof task.checkpoint_state === "string" ? task.checkpoint_state : "none",
    handoff_state: typeof task.handoff_state === "string" ? task.handoff_state : "none",
    roles: Array.isArray(task.roles) ? task.roles.filter((value): value is string => typeof value === "string") : [],
    providers: Array.isArray(task.providers) ? task.providers.filter((value): value is string => typeof value === "string") : [],
    updated_at: String(task.updated_at ?? new Date(0).toISOString()),
  };
}

function normalizeOperationalViewsSnapshot(
  workspaceId: string,
  snapshot: Partial<OperationalViewsSnapshot> | null | undefined,
): OperationalViewsSnapshot {
  const usage = snapshot?.usage;
  const governance = snapshot?.governance;
  return {
    workspace_id: typeof snapshot?.workspace_id === "string" ? snapshot.workspace_id : workspaceId,
    summary: {
      project_count: typeof snapshot?.summary?.project_count === "number" ? snapshot.summary.project_count : Array.isArray(snapshot?.projects) ? snapshot.projects.length : 0,
      approvals_pending: typeof snapshot?.summary?.approvals_pending === "number" ? snapshot.summary.approvals_pending : 0,
      checkpoint_ready_count: typeof snapshot?.summary?.checkpoint_ready_count === "number" ? snapshot.summary.checkpoint_ready_count : 0,
      handoff_ready_count: typeof snapshot?.summary?.handoff_ready_count === "number" ? snapshot.summary.handoff_ready_count : 0,
      provider_online_count: typeof snapshot?.summary?.provider_online_count === "number" ? snapshot.summary.provider_online_count : usage?.providers?.online ?? 0,
    },
    projects: Array.isArray(snapshot?.projects)
      ? snapshot.projects.map((project) => ({
          id: String(project?.id ?? ""),
          workspace_id: String(project?.workspace_id ?? workspaceId),
          name: String(project?.name ?? "Untitled project"),
          description: typeof project?.description === "string" ? project.description : null,
          status: String(project?.status ?? "active"),
          task_count: typeof project?.task_count === "number" ? project.task_count : 0,
          blocked_count: typeof project?.blocked_count === "number" ? project.blocked_count : 0,
          review_needed_count: typeof project?.review_needed_count === "number" ? project.review_needed_count : 0,
          approval_pending_count: typeof project?.approval_pending_count === "number" ? project.approval_pending_count : 0,
          checkpoint_ready_count: typeof project?.checkpoint_ready_count === "number" ? project.checkpoint_ready_count : 0,
          handoff_ready_count: typeof project?.handoff_ready_count === "number" ? project.handoff_ready_count : 0,
          updated_at: String(project?.updated_at ?? new Date(0).toISOString()),
          created_at: String(project?.created_at ?? new Date(0).toISOString()),
        }))
      : [],
    inbox: Array.isArray(snapshot?.inbox) ? snapshot.inbox : [],
    history: Array.isArray(snapshot?.history) ? snapshot.history : [],
    lifecycle: Array.isArray(snapshot?.lifecycle) ? snapshot.lifecycle : [],
    diagrams: Array.isArray(snapshot?.diagrams) ? snapshot.diagrams : [],
    governance: {
      policy_posture: {
        repository_action_preference: governance?.policy_posture?.repository_action_preference ?? defaultRepositoryActionPreference,
        auto_approve_preference: governance?.policy_posture?.auto_approve_preference ?? defaultAutoApprovePreference,
        provider_priority: Array.isArray(governance?.policy_posture?.provider_priority)
          ? governance.policy_posture.provider_priority.filter((value): value is string => typeof value === "string")
          : ["claude", "codex", "copilot", "opencode"],
        provider_priority_source: typeof governance?.policy_posture?.provider_priority_source === "string"
          ? governance.policy_posture.provider_priority_source
          : "default",
      },
      provider_routing: {
        priority_order: Array.isArray(governance?.provider_routing?.priority_order)
          ? governance.provider_routing.priority_order.filter((value): value is string => typeof value === "string")
          : ["claude", "codex", "copilot", "opencode"],
        selected_provider: typeof governance?.provider_routing?.selected_provider === "string"
          ? governance.provider_routing.selected_provider
          : "local",
        fallback_candidates: Array.isArray(governance?.provider_routing?.fallback_candidates)
          ? governance.provider_routing.fallback_candidates.filter((value): value is string => typeof value === "string")
          : [],
        provider_health: governance?.provider_routing?.provider_health ?? {},
        providers: Array.isArray(governance?.provider_routing?.providers) ? governance.provider_routing.providers : [],
      },
      override_history: Array.isArray(governance?.override_history) ? governance.override_history : [],
      repository_action_governance: {
        pending_count: governance?.repository_action_governance?.pending_count ?? 0,
        approved_count: governance?.repository_action_governance?.approved_count ?? 0,
        recent: Array.isArray(governance?.repository_action_governance?.recent)
          ? governance.repository_action_governance.recent
          : [],
      },
    },
    usage: {
      tasks: {
        total: usage?.tasks?.total ?? 0,
        active: usage?.tasks?.active ?? 0,
        done: usage?.tasks?.done ?? 0,
        by_status: usage?.tasks?.by_status ?? {},
      },
      subtasks: {
        total: usage?.subtasks?.total ?? 0,
        by_status: usage?.subtasks?.by_status ?? {},
      },
      events: {
        total: usage?.events?.total ?? 0,
        by_type: usage?.events?.by_type ?? {},
      },
      messages: {
        total: usage?.messages?.total ?? 0,
        by_role: usage?.messages?.by_role ?? {},
      },
      repositories: {
        total: usage?.repositories?.total ?? 0,
      },
      dispatches: {
        total: usage?.dispatches?.total ?? 0,
        by_status: usage?.dispatches?.by_status ?? {},
      },
      budget: usage?.budget ?? null,
      evidence: {
        total: usage?.evidence?.total ?? 0,
        by_type: usage?.evidence?.by_type ?? {},
      },
      reviews: {
        total: usage?.reviews?.total ?? 0,
        by_status: usage?.reviews?.by_status ?? {},
      },
      handoffs: {
        total: usage?.handoffs?.total ?? 0,
      },
      providers: {
        total: usage?.providers?.total ?? 0,
        online: usage?.providers?.online ?? 0,
        by_health: usage?.providers?.by_health ?? {},
      },
    },
  };
}

export async function getTaskCheckpoint(taskId: string): Promise<CheckpointCapsuleRecord | null> {
  const data = await getJson<{ checkpoint: CheckpointCapsuleRecord | null }>(
    `/api/tasks/${encodeURIComponent(taskId)}/checkpoint`,
  );
  return data.checkpoint;
}

export async function listTaskCheckpoints(taskId: string): Promise<CheckpointCapsuleRecord[]> {
  const data = await getJson<{ checkpoints: CheckpointCapsuleRecord[] }>(
    `/api/tasks/${encodeURIComponent(taskId)}/checkpoints`,
  );
  return data.checkpoints;
}

export async function restartTaskFromCheckpoint(
  taskId: string,
): Promise<{ task: TaskRecord; checkpoint: CheckpointCapsuleRecord }> {
  return postJson<{ task: TaskRecord; checkpoint: CheckpointCapsuleRecord }>(
    `/api/tasks/${encodeURIComponent(taskId)}/checkpoint/restart`,
    {},
  );
}

export async function sendTaskMessage(
  taskId: string,
  content: string,
  target = "Current task agents",
): Promise<MessageRecord> {
  const data = await postJson<{ message: MessageRecord }>(
    `/api/tasks/${encodeURIComponent(taskId)}/messages`,
    { content, target },
  );
  return data.message;
}

export async function sendChatMessage(
  message: string,
  context?: { taskId?: string; workspaceId?: string; projectId?: string },
): Promise<{ taskId: string; agent: string; status: string }> {
  return postJson<{ taskId: string; agent: string; status: string }>("/api/chat", {
    message,
    context: context ?? {},
  });
}

export async function scheduleTask(taskId: string): Promise<TaskScheduleResult> {
  return postJson<TaskScheduleResult>(`/api/tasks/${encodeURIComponent(taskId)}/schedule`, {});
}

export async function transitionSubtask(
  subtaskId: string,
  status: string,
  actor = "Pravaha",
): Promise<SubtaskTransitionResult> {
  return postJson<SubtaskTransitionResult>(
    `/api/subtasks/${encodeURIComponent(subtaskId)}/transition`,
    { status, actor },
  );
}

export async function dispatchSubtask(
  subtaskId: string,
  provider = "local",
): Promise<SubtaskDispatchResult> {
  return postJson<SubtaskDispatchResult>(
    `/api/subtasks/${encodeURIComponent(subtaskId)}/dispatch`,
    { provider },
  );
}

export async function runTaskReview(
  taskId: string,
  reviewType = "code",
): Promise<ReviewRunResult> {
  return postJson<ReviewRunResult>(
    `/api/tasks/${encodeURIComponent(taskId)}/reviews/run`,
    { review_type: reviewType },
  );
}

export async function createTaskHandoff(taskId: string): Promise<HandoffResult> {
  return postJson<HandoffResult>(`/api/tasks/${encodeURIComponent(taskId)}/handoff`, {});
}

export async function approveRepositoryAction(
  taskId: string,
  action: string,
): Promise<RepositoryActionResult> {
  return postJson<RepositoryActionResult>(
    `/api/tasks/${encodeURIComponent(taskId)}/repository-action`,
    { action, approved: true },
  );
}

export type BrainstormTurn = {
  role: "sarathi" | "user";
  content: string;
  options?: string[];
  selected?: string | null;
  spec_update?: string | null;
  timestamp: string;
};

export type BrainstormResearchFinding = {
  agent: string;
  type: "codebase" | "risk" | "pattern" | "reference";
  summary: string;
  refs?: string[];
  timestamp: string;
};

export type BrainstormSession = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  task_id: string | null;
  status: "active" | "approved" | "abandoned";
  title: string;
  provider: string | null;
  spec_path: string | null;
  spec_content: string | null;
  output_format: string;
  dialogue_turns: BrainstormTurn[];
  research_findings: BrainstormResearchFinding[];
  visual_options: unknown[];
  metadata: {
    reuse_source?: {
      kind?: string;
      id?: string | null;
      name?: string | null;
    };
    workflow_template_id?: string;
    learning_playbook_id?: string;
    recommended_view_ids?: string[];
    recommended_repository_action_mode?: string;
    recommended_auto_approve_mode?: string;
    suggested_provider_priority?: string[];
  };
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export async function createBrainstormSession(
  workspaceId: string,
  title: string,
  options: {
    projectId?: string;
    provider?: string;
    outputFormat?: string;
    metadata?: BrainstormSession["metadata"];
  } = {},
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    "/api/brainstorm/sessions",
    {
      workspace_id: workspaceId,
      title,
      ...(options.projectId ? { project_id: options.projectId } : {}),
      ...(options.provider ? { provider: options.provider } : {}),
      ...(options.outputFormat ? { output_format: options.outputFormat } : {}),
      ...(options.metadata ? { metadata: options.metadata } : {}),
    },
  );
  return data.session;
}

export async function getBrainstormSession(sessionId: string): Promise<BrainstormSession> {
  const data = await getJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}`,
  );
  return data.session;
}

export async function addBrainstormTurn(
  sessionId: string,
  turn: Omit<BrainstormTurn, "timestamp">,
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/turns`,
    turn as Record<string, unknown>,
  );
  return data.session;
}

export async function addBrainstormResearch(
  sessionId: string,
  finding: Omit<BrainstormResearchFinding, "timestamp">,
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/research`,
    finding as Record<string, unknown>,
  );
  return data.session;
}

export async function approveBrainstormSession(
  sessionId: string,
  options: { exportPath?: string; outputFormat?: string } = {},
): Promise<{ session: BrainstormSession; task: TaskRecord }> {
  return postJson<{ session: BrainstormSession; task: TaskRecord }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/approve`,
    {
      ...(options.exportPath ? { export_path: options.exportPath } : {}),
      ...(options.outputFormat ? { output_format: options.outputFormat } : {}),
    },
  );
}

export type PolicyPackFile = {
  name: string;
  content: string;
};

export async function getWorkspacePolicyPack(workspaceId: string): Promise<PolicyPackFile[]> {
  const data = await getJson<{ files: PolicyPackFile[] }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/policy-pack`,
  );
  return data.files;
}

export async function putWorkspacePolicyPackFile(
  workspaceId: string,
  filename: string,
  content: string,
): Promise<void> {
  await putJson<Record<string, unknown>>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/policy-pack/${encodeURIComponent(filename)}`,
    { content },
  );
}

export async function listProviders(workspaceId: string): Promise<ProviderHealthRecord[]> {
  const data = await getJson<{ providers: ProviderHealthRecord[] }>(
    `/api/providers?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
  return data.providers;
}

export async function testProviderConnection(
  workspaceId: string,
  providerId: string,
  draft: ProviderConnectionDraft,
): Promise<ProviderHealthRecord> {
  const data = await postJson<{ provider: ProviderHealthRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/providers/${encodeURIComponent(providerId)}/test`,
    draft,
  );
  return data.provider;
}

export async function listEvents(
  workspaceId?: string,
  taskId?: string,
): Promise<LifecycleEventRecord[]> {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  if (taskId) params.set("task_id", taskId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const data = await getJson<{ events: LifecycleEventRecord[] }>(`/api/events${suffix}`);
  return data.events;
}

export function getEventsStreamUrl(workspaceId?: string, taskId?: string): string | null {
  const config = getSarathiApiConfig();
  if (!config) return null;
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  if (taskId) params.set("task_id", taskId);
  if (config.token) params.set("token", config.token);
  return `${config.baseUrl}/api/events/stream?${params.toString()}`;
}

export async function attachWorkspaceRepository(
  workspaceId: string,
  path: string,
): Promise<WorkspaceRepositoryRecord> {
  const data = await postJson<{ repository: WorkspaceRepositoryRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/repositories`,
    { path, approved: true },
  );
  return data.repository;
}

export async function initializeWorkspaceRepository(
  workspaceId: string,
  repositoryId: string,
  interview: Record<string, unknown> = {},
): Promise<{
  repository: WorkspaceRepositoryRecord;
  initialization: RepositoryInitializationResult;
}> {
  return postJson<{
    repository: WorkspaceRepositoryRecord;
    initialization: RepositoryInitializationResult;
  }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/repositories/${encodeURIComponent(repositoryId)}/initialize`,
    { approved: true, interview },
  );
}

export async function listWorkspaceRepositories(
  workspaceId: string,
): Promise<WorkspaceRepositoryRecord[]> {
  const data = await getJson<{ repositories: WorkspaceRepositoryRecord[] }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/repositories`,
  );
  return data.repositories;
}

async function getJson<T>(path: string): Promise<T> {
  const config = getSarathiApiConfig();
  if (!config) {
    throw new Error("Sarathi local service is not configured for this desktop build.");
  }
  const response = await fetch(`${config.baseUrl}${path}`, {
    method: "GET",
    headers: {
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(envelope.error.message);
  }
  return envelope.data;
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const config = getSarathiApiConfig();
  if (!config) {
    throw new Error("Sarathi local service is not configured for this desktop build.");
  }
  const response = await fetch(`${config.baseUrl}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(envelope.error.message);
  }
  return envelope.data;
}

async function patchJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const config = getSarathiApiConfig();
  if (!config) {
    throw new Error("Sarathi local service is not configured for this desktop build.");
  }
  const response = await fetch(`${config.baseUrl}${path}`, {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(envelope.error.message);
  }
  return envelope.data;
}

async function putJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const config = getSarathiApiConfig();
  if (!config) {
    throw new Error("Sarathi local service is not configured for this desktop build.");
  }
  const response = await fetch(`${config.baseUrl}${path}`, {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(envelope.error.message);
  }
  return envelope.data;
}

export type WikiPage = {
  name: string;
  path: string;
  exists: boolean;
};

export type KnowledgeCenterSummary = {
  workspace_id: string;
  guide: {
    status: "complete" | "partial" | "not_initialized";
    present_files: string[];
    required_files: string[];
  };
  wiki: WikiPage[];
  learnings: {
    status: "empty" | "populated";
    path: string;
    sections: number;
    accepted_learnings: Array<{
      title: string;
      summary: string;
      task_id: string;
      tags: string[];
      evidence_refs: string[];
      recommended_template_id: string | null;
      recommended_view_ids: string[];
      source_file: string;
      linked_proposal_id: string | null;
      linked_proposal_title: string | null;
      linked_playbook_id: string | null;
      linked_playbook_name: string | null;
    }>;
  };
  skills: {
    status: "available" | "not_found";
    path: string;
    family_count?: number;
    skill_count: number;
  };
  proposals: {
    pending_count: number;
    accepted_count: number;
    rejected_count: number;
    last_reviewed_at: string | null;
  };
  recent_contexts: {
    total_bundles: number;
    recent_count: number;
    bundles: Array<{
      dispatch_id: string;
      task_id: string;
      agent: string;
      created_at: string;
    }>;
  };
  section_health?: {
    wiki: {
      page_count: number;
      deep_links: number;
      last_updated: string | null;
    };
    context: {
      total_bundles: number;
      recent_count: number;
      unique_tasks: number;
    };
    proposals: {
      pending: number;
      accepted: number;
      rejected: number;
      last_reviewed: string | null;
    };
    learnings: {
      accepted_count: number;
      sections: number;
    };
  };
  context_compiler_guidance?: Array<{
    title: string;
    policy_file: string;
    suggested_change: string;
    impacted_assets: string[];
    reviewed_at: string;
  }>;
};

export type WikiData = {
  workspace_id: string;
  pages: WikiPage[];
};

export type WikiPageData = {
  workspace_id: string;
  page: string;
  content: string;
  path: string;
};

export type SkillInfo = {
  name: string;
  family?: string;
  source: string;
  description: string;
};

export type SkillRoute = {
  task_type: string;
  primary: string;
  secondary: string[];
  always_invoke: boolean;
};

export type RoleMapping = {
  role: string;
  phase: string;
  purpose: string;
};

export type BehaviorAsset = {
  path: string;
  exists: boolean;
  purpose: string;
};

export type SkillsData = {
  workspace_id: string;
  skills: SkillInfo[];
  routes: SkillRoute[];
  role_mappings: RoleMapping[];
  behavior_assets: BehaviorAsset[];
  evolution_proposals: PolicyProposal[];
  evolution_history: EvolutionHistoryItem[];
  path?: string;
  source_content?: string;
};

export type EvolutionHistoryItem = {
  status: string;
  title: string;
  proposal_id: string;
  policy_file: string;
  proposal_kind: string;
  reviewed_at: string;
  reason: string;
  source?: string;
  impacted_assets?: string[];
};

export type ContextBundleDetail = {
  dispatch_id: string;
  task_id: string;
  agent: string;
  status: string;
  created_at: string;
  context_pack: {
    role: string;
    phase: string;
    summary: string;
    agent_input: {
      objective: string;
      constraints: string[];
      acceptance_criteria: string[];
      relevant_files: string[];
      prior_findings: string[];
      available_tools: string[];
      token_budget: number | null;
    };
    estimated_tokens: number | null;
    trimmed_sections: string[];
    source_artifacts: Array<{ type: string; ref: string }>;
  };
  agent_output: {
    status: string | null;
    summary: string | null;
    artifacts: string[];
    decisions: string[];
    findings: string[];
    next_recommended_agent: string | null;
  };
  artifact_index: {
    files_changed: string[];
    tests_run: string[];
    known_risks: string[];
    review_findings: Array<{
      message?: string | null;
      severity?: string | null;
      check?: string | null;
      file_path?: string | null;
      source?: string | null;
    }>;
  };
  provenance: {
    sources: string[];
  };
};

export type ContextBundlesData = {
  workspace_id: string;
  bundles: ContextBundleDetail[];
};

export async function getKnowledgeCenter(workspaceId: string): Promise<KnowledgeCenterSummary> {
  const data = await getJson<KnowledgeCenterSummary>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/knowledge-center`,
  );
  return data;
}

export async function getWiki(workspaceId: string): Promise<WikiData> {
  const data = await getJson<WikiData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/wiki`,
  );
  return data;
}

export async function getWikiPage(workspaceId: string, page: string): Promise<WikiPageData> {
  const data = await getJson<WikiPageData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/wiki/${encodeURIComponent(page)}`,
  );
  return data;
}

export async function saveWikiPage(
  workspaceId: string,
  payload: { page: string; content: string },
): Promise<WikiPageData> {
  const data = await postJson<WikiPageData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/wiki`,
    payload,
  );
  return data;
}

export async function getSkills(workspaceId: string): Promise<SkillsData> {
  const data = await getJson<SkillsData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/skills`,
  );
  return data;
}

export async function saveSkillsPack(
  workspaceId: string,
  payload: { content: string },
): Promise<SkillsData> {
  const data = await postJson<SkillsData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/skills`,
    payload,
  );
  return data;
}

export async function getContextBundles(workspaceId: string): Promise<ContextBundlesData> {
  const data = await getJson<ContextBundlesData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/context-bundles`,
  );
  return data;
}

export type PolicyProposal = {
  id: string;
  title: string;
  policy_file: string;
  proposal_kind: string;
  impacted_assets: string[];
  risk_level: string;
  rationale: string;
  suggested_change: string;
  evidence_refs: string[];
  confidence: number;
  source: string;
  routing_hint: Record<string, unknown>;
};

export type ProposalsData = {
  workspace_id: string;
  proposals: PolicyProposal[];
  reviewed_history: ProposalDecision[];
  status: string;
  source?: string;
};

export type ProposalDecision = {
  id: string;
  status: string;
  policy_file: string;
  title: string;
  source: string;
  proposal_kind?: string;
  impacted_assets?: string[];
  risk_level?: string;
  confidence?: number;
  suggested_change?: string;
  evidence_refs?: string[];
  routing_hint: Record<string, unknown>;
  reason?: string | null;
  reviewed_at: string;
};

export type ProposalDetailData = {
  workspace_id: string;
  proposal: PolicyProposal;
  policy_preview: {
    path: string;
    exists: boolean;
    current_content: string;
    accepted_preview: string;
  };
};

export async function getProposals(workspaceId: string): Promise<ProposalsData> {
  const data = await getJson<ProposalsData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/proposals`,
  );
  return {
    ...data,
    reviewed_history: Array.isArray(data.reviewed_history)
      ? data.reviewed_history.map((decision) => ({
          ...decision,
          proposal_kind: typeof decision?.proposal_kind === "string" ? decision.proposal_kind : undefined,
          impacted_assets: Array.isArray(decision?.impacted_assets)
            ? decision.impacted_assets.filter((value): value is string => typeof value === "string")
            : [],
          risk_level: typeof decision?.risk_level === "string" ? decision.risk_level : undefined,
          confidence: typeof decision?.confidence === "number" ? decision.confidence : undefined,
          suggested_change: typeof decision?.suggested_change === "string" ? decision.suggested_change : undefined,
          evidence_refs: Array.isArray(decision?.evidence_refs)
            ? decision.evidence_refs.filter((value): value is string => typeof value === "string")
            : [],
        }))
      : [],
  };
}

export async function getProposalDetail(
  workspaceId: string,
  proposalId: string,
): Promise<ProposalDetailData> {
  const data = await getJson<ProposalDetailData>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/proposals/${encodeURIComponent(proposalId)}`,
  );
  return data;
}

export async function acceptProposal(workspaceId: string, proposalId: string): Promise<{ decision: ProposalDecision }> {
  const data = await postJson<{ decision: ProposalDecision }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/proposals/${encodeURIComponent(proposalId)}/accept`,
    {},
  );
  return data;
}

export async function rejectProposal(workspaceId: string, proposalId: string, reason?: string): Promise<{ decision: ProposalDecision }> {
  const data = await postJson<{ decision: ProposalDecision }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/proposals/${encodeURIComponent(proposalId)}/reject`,
    { reason: reason ?? null },
  );
  return data;
}
