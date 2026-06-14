// Shared response envelope + domain types, derived from docs/openapi.json.
//
// The service wraps every response in a success/error envelope:
//   { ok: true,  data: <payload>, correlation_id: string }
//   { ok: false, error: { code, message, status }, correlation_id: string }
//
// Most resource payloads are typed loosely (`Record<string, unknown>` /
// `additionalProperties: true` in the spec) since the service is still
// evolving. Views built on top of this scaffold should narrow these types
// locally as the corresponding endpoints stabilize.

export interface ApiSuccess<T> {
  ok: true;
  data: T;
  correlation_id: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  status: number;
}

export interface ApiError {
  ok: false;
  error: ApiErrorBody;
  correlation_id: string;
}

export type ApiEnvelope<T> = ApiSuccess<T> | ApiError;

/** Generic loosely-typed resource object (`additionalProperties: true`). */
export type AnyRecord = Record<string, unknown>;

export interface Workspace extends AnyRecord {
  id: string;
  name?: string;
  status?: string;
  health?: string;
  [key: string]: unknown;
}

export interface ListWorkspacesData {
  workspaces: Workspace[];
}

export interface GetWorkspaceData {
  workspace: Workspace;
}

export interface TaskDashboardRow extends AnyRecord {
  id: string;
  title?: string;
  [key: string]: unknown;
}

export interface TaskDashboardData {
  tasks: TaskDashboardRow[];
}

export interface ProviderHealth extends AnyRecord {
  name?: string;
  status?: string;
  [key: string]: unknown;
}

export interface ProvidersData {
  providers: ProviderHealth[];
}

export interface HealthData {
  status: "ok" | string;
}

export interface LifecycleEvent extends AnyRecord {
  id?: string;
  type?: string;
  [key: string]: unknown;
}

export interface EventsData {
  events: LifecycleEvent[];
}

// ---------------------------------------------------------------------
// Task Studio + related task sub-resources
// ---------------------------------------------------------------------

/**
 * GET /tasks/{id}/studio — `additionalProperties: true` in openapi.json.
 * Shape is still evolving; narrow locally as the view stabilizes.
 */
export type TaskStudioData = AnyRecord;

/** GET /tasks/{id}/graph — `additionalProperties: true` in openapi.json. */
export type TaskGraphData = AnyRecord;

export interface TaskMessage extends AnyRecord {
  id?: string;
  role?: string;
  content?: string;
  [key: string]: unknown;
}

export interface TaskMessagesData {
  messages: TaskMessage[];
}

/** GET /tasks/{id}/evidence — `additionalProperties: true` in openapi.json. */
export type TaskEvidenceData = AnyRecord;

/** GET /tasks/{id}/reviews — `additionalProperties: true` in openapi.json. */
export type TaskReviewsData = AnyRecord;

/**
 * GET /tasks/{id}/handoff — "Latest handoff (or null)" per openapi.json.
 * `additionalProperties: true` when present.
 */
export type TaskHandoffData = AnyRecord | null;

export interface ApprovalGate extends AnyRecord {
  id?: string;
  status?: string;
  [key: string]: unknown;
}

export interface TaskApprovalsData {
  approval_gates: ApprovalGate[];
}

/**
 * POST /tasks/{id}/approve and /tasks/{id}/auto-approve — `additionalProperties:
 * true`. Always carries `approval_gate` (or `approved` for auto-approve); may
 * carry `auto_schedule` when approving the "Task graph" gate triggers
 * scheduling of ready units.
 */
export interface ApprovalActionData extends AnyRecord {
  approval_gate?: ApprovalGate;
  approved?: ApprovalGate[];
  auto_schedule?: AnyRecord;
}

/** POST /tasks/{id}/graph-draft — `{ graph, approval_gate }`. */
export interface GraphDraftData extends AnyRecord {
  graph: TaskGraphData;
  approval_gate: ApprovalGate;
}

/** POST /tasks/{id}/messages — `{ message }`. */
export interface TaskMessageResult extends AnyRecord {
  message: TaskMessage;
}

/**
 * POST /subtasks/{id}/transition — `{ subtask, unblocked, auto_scheduled, task }`,
 * `additionalProperties: true`.
 */
export type SubtaskTransitionResult = AnyRecord;

/**
 * POST /subtasks/{id}/dispatch — `{ subtask, dispatch, evidence }`,
 * `additionalProperties: true`.
 */
export type SubtaskDispatchResult = AnyRecord;

/**
 * POST /tasks/{id}/schedule — `{ task, scheduled, blocked, waiting_human,
 * coordination_state, fan_out_ready_nodes, fan_in_nodes }`.
 */
export type ScheduleResult = AnyRecord;

/** POST /tasks/{id}/handoff — `{ handoff, repository_action_gate, checkpoint }`. */
export type CreateHandoffResult = AnyRecord;

/** POST /tasks/{id}/repository-action — updated handoff, `additionalProperties: true`. */
export type RepositoryActionResult = AnyRecord;

export interface Dispatch extends AnyRecord {
  id?: string;
  status?: string;
  [key: string]: unknown;
}

export interface TaskDispatchesData {
  dispatches: Dispatch[];
}

/** GET /tasks/{id}/panel — "Task panel entries", `additionalProperties: true`. */
export type TaskPanelData = AnyRecord;

// ---------------------------------------------------------------------
// Workspace projections: wiki, operational views, repositories, proposals,
// dogfood acceptance
// ---------------------------------------------------------------------

/** GET /workspaces/{id}/operational-views — `additionalProperties: true`. */
export type OperationalViewsData = AnyRecord;

/** GET /workspaces/{id}/wiki — "Wiki index payload", `additionalProperties: true`. */
export type WikiIndexData = AnyRecord;

/** GET /workspaces/{id}/wiki/{page} — "Wiki page payload", `additionalProperties: true`. */
export type WikiPageData = AnyRecord;

/**
 * GET /workspaces/{id}/dogfood-acceptance — `additionalProperties: true`.
 */
export type DogfoodAcceptanceData = AnyRecord;

/** Pending/accepted/rejected counts for a workspace's policy proposals. */
export interface UsageStatsProposalCounts {
  pending: number;
  accepted: number;
  rejected: number;
}

/** Per-task row in the usage stats breakdown. */
export interface UsageStatsTask {
  task_id: string;
  title: string;
  task_class: string | null;
  agent: string | null;
  pass: boolean | null;
  blast_radius: number | null;
  tokens: number | null;
  latency: number | null;
  [key: string]: unknown;
}

/**
 * GET /workspaces/{id}/usage-stats — HarnessOutcome-derived quality signals
 * for a workspace (test pass rate, blast radius, token cost, proposal
 * review activity) plus a per-task breakdown. Backed by
 * `src.service.usage_stats.build_usage_stats`.
 */
export interface UsageStatsData {
  workspace_id?: string;
  test_pass_rate: number | null;
  avg_blast_radius: number | null;
  total_tokens: number | null;
  proposal_counts: UsageStatsProposalCounts | null;
  task_count: number;
  tasks: UsageStatsTask[];
  [key: string]: unknown;
}

export interface WorkspaceRepository extends AnyRecord {
  id?: string;
  repository_id?: string;
  name?: string;
  [key: string]: unknown;
}

export interface WorkspaceRepositoriesData {
  repositories: WorkspaceRepository[];
}

/** GET /workspaces/{id}/proposals — "Proposals payload", `additionalProperties: true`. */
export type ProposalsData = AnyRecord;

export interface Project extends AnyRecord {
  id?: string;
  name?: string;
  [key: string]: unknown;
}

/** GET /workspaces/{id}/projects */
export interface ProjectsData {
  projects: Project[];
}
