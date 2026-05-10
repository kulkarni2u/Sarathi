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
} & Record<string, unknown>;

export type WorkspaceMetadata = {
  repository_action_preference?: RepositoryActionPreferenceRecord;
  auto_approve_preference?: AutoApprovePreferenceRecord;
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
  health: string;
  auth: string;
  path: string;
  capabilities: string[];
  last_checked_at?: string | null;
  last_error?: string | null;
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

export type OperationalViewsSnapshot = {
  workspace_id: string;
  history: LifecycleEventRecord[];
  lifecycle: OperationalLifecycleRole[];
  diagrams: OperationalDiagram[];
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
  roles: string[];
  providers: string[];
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

export function getSarathiApiConfig(): ApiConfig | null {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  const baseUrl = env?.VITE_SARATHI_API_BASE_URL?.replace(/\/$/, "");
  if (baseUrl) {
    return {
      baseUrl,
      token: env?.VITE_SARATHI_API_TOKEN ?? null,
    };
  }

  const runtime = (globalThis as typeof globalThis & {
    __SARATHI_RUNTIME_CONFIG__?: RuntimeConfig;
  }).__SARATHI_RUNTIME_CONFIG__;
  const runtimeBaseUrl = runtime?.baseUrl?.replace(/\/$/, "");
  if (runtimeBaseUrl) {
    return {
      baseUrl: runtimeBaseUrl,
      token: runtime?.token ?? null,
    };
  }
  return null;
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
  return data.tasks;
}

export async function getWorkspaceOperationalViews(
  workspaceId: string,
): Promise<OperationalViewsSnapshot> {
  return getJson<OperationalViewsSnapshot>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/operational-views`,
  );
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
  return getJson<TaskStudioSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/studio`);
}

export async function getTaskPanel(taskId: string): Promise<TaskPanelSnapshot> {
  return getJson<TaskPanelSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/panel`);
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
  path: string,
  auth: string,
): Promise<ProviderHealthRecord> {
  const data = await postJson<{ provider: ProviderHealthRecord }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/providers/${encodeURIComponent(providerId)}/test`,
    { path, auth },
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
