// Typed fetch wrapper for the Sarathi service API.
//
// - Reads base URL + bearer token from the runtime config contract
//   (see ./runtimeConfig.ts).
// - Unwraps the {ok, data, correlation_id} / {ok, error, correlation_id}
//   envelope described in docs/openapi.json.
// - Throws `ApiClientError` on transport failures or `ok: false` responses
//   so callers can branch on `.code` / `.status` / `.isNetworkError`.

import { getRuntimeConfig } from "./runtimeConfig";
import type {
  ApiEnvelope,
  ApprovalActionData,
  CreateHandoffResult,
  EventsData,
  GetWorkspaceData,
  GraphDraftData,
  HealthData,
  ListWorkspacesData,
  OperationalViewsData,
  ProjectsData,
  ProposalsData,
  ProvidersData,
  RepositoryActionResult,
  ScheduleResult,
  SubtaskDispatchResult,
  SubtaskTransitionResult,
  TaskApprovalsData,
  TaskDashboardData,
  TaskDispatchesData,
  TaskEvidenceData,
  TaskGraphData,
  TaskHandoffData,
  TaskMessageResult,
  TaskMessagesData,
  TaskPanelData,
  TaskReviewsData,
  TaskStudioData,
  UsageStatsData,
  WikiIndexData,
  WikiPageData,
  WorkspaceRepositoriesData,
} from "./types";

export class ApiClientError extends Error {
  code: string;
  status: number;
  correlationId?: string;
  isNetworkError: boolean;

  constructor(opts: {
    message: string;
    code: string;
    status: number;
    correlationId?: string;
    isNetworkError?: boolean;
  }) {
    super(opts.message);
    this.name = "ApiClientError";
    this.code = opts.code;
    this.status = opts.status;
    this.correlationId = opts.correlationId;
    this.isNetworkError = opts.isNetworkError ?? false;
  }
}

export interface RequestOptions {
  method?: string;
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const { baseUrl } = getRuntimeConfig();
  const normalizedPath = path.replace(/^\/+/, "/");

  // An empty `baseUrl` means "same origin as the page" — build a relative
  // URL (e.g. "/workspaces/...") instead of feeding "" to `new URL()`, which
  // would throw since "" is not a valid absolute/base URL.
  if (!baseUrl) {
    const params = new URLSearchParams();
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null) continue;
        params.set(key, String(value));
      }
    }
    const queryString = params.toString();
    return queryString ? `${normalizedPath}?${queryString}` : normalizedPath;
  }

  const url = new URL(normalizedPath, baseUrl + "/");
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Low-level request helper. Resolves to the unwrapped `data` payload on
 * success. Throws `ApiClientError` on network failure or `ok: false`.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token } = getRuntimeConfig();
  const url = buildUrl(path, options.query);

  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (err) {
    throw new ApiClientError({
      message: err instanceof Error ? err.message : "Network request failed",
      code: "network_error",
      status: 0,
      isNetworkError: true,
    });
  }

  let payload: ApiEnvelope<T> | undefined;
  try {
    payload = (await response.json()) as ApiEnvelope<T>;
  } catch {
    // Non-JSON response (e.g. proxy error page).
    throw new ApiClientError({
      message: `Unexpected non-JSON response (HTTP ${response.status})`,
      code: "invalid_response",
      status: response.status,
    });
  }

  if (!payload.ok) {
    throw new ApiClientError({
      message: payload.error.message,
      code: payload.error.code,
      status: payload.error.status ?? response.status,
      correlationId: payload.correlation_id,
    });
  }

  return payload.data;
}

// ---------------------------------------------------------------------
// Typed endpoint methods
// ---------------------------------------------------------------------

export const api = {
  /** GET /health */
  getHealth(signal?: AbortSignal): Promise<HealthData> {
    return request<HealthData>("/health", { signal });
  },

  /** GET /workspaces */
  listWorkspaces(signal?: AbortSignal): Promise<ListWorkspacesData> {
    return request<ListWorkspacesData>("/workspaces", { signal });
  },

  /** GET /workspaces/{id} */
  getWorkspace(workspaceId: string, signal?: AbortSignal): Promise<GetWorkspaceData> {
    return request<GetWorkspaceData>(`/workspaces/${encodeURIComponent(workspaceId)}`, { signal });
  },

  /** GET /workspaces/{id}/task-dashboard?project_id= */
  getTaskDashboard(
    workspaceId: string,
    projectId?: string,
    signal?: AbortSignal,
  ): Promise<TaskDashboardData> {
    return request<TaskDashboardData>(
      `/workspaces/${encodeURIComponent(workspaceId)}/task-dashboard`,
      { query: { project_id: projectId }, signal },
    );
  },

  /** GET /providers?workspace_id= */
  getProviders(workspaceId?: string, signal?: AbortSignal): Promise<ProvidersData> {
    return request<ProvidersData>("/providers", {
      query: { workspace_id: workspaceId },
      signal,
    });
  },

  /** GET /events?workspace_id&task_id (polling fallback for the SSE helper) */
  getEvents(
    params: { workspaceId?: string; taskId?: string },
    signal?: AbortSignal,
  ): Promise<EventsData> {
    return request<EventsData>("/events", {
      query: { workspace_id: params.workspaceId, task_id: params.taskId },
      signal,
    });
  },

  // -------------------------------------------------------------------
  // Task Studio + task sub-resources
  // -------------------------------------------------------------------

  /** GET /tasks/{id}/studio */
  getTaskStudio(taskId: string, signal?: AbortSignal): Promise<TaskStudioData> {
    return request<TaskStudioData>(`/tasks/${encodeURIComponent(taskId)}/studio`, { signal });
  },

  /** GET /tasks/{id}/graph */
  getTaskGraph(taskId: string, signal?: AbortSignal): Promise<TaskGraphData> {
    return request<TaskGraphData>(`/tasks/${encodeURIComponent(taskId)}/graph`, { signal });
  },

  /** GET /tasks/{id}/messages */
  getTaskMessages(taskId: string, signal?: AbortSignal): Promise<TaskMessagesData> {
    return request<TaskMessagesData>(`/tasks/${encodeURIComponent(taskId)}/messages`, { signal });
  },

  /** GET /tasks/{id}/evidence */
  getTaskEvidence(taskId: string, signal?: AbortSignal): Promise<TaskEvidenceData> {
    return request<TaskEvidenceData>(`/tasks/${encodeURIComponent(taskId)}/evidence`, { signal });
  },

  /** GET /tasks/{id}/reviews */
  getTaskReviews(taskId: string, signal?: AbortSignal): Promise<TaskReviewsData> {
    return request<TaskReviewsData>(`/tasks/${encodeURIComponent(taskId)}/reviews`, { signal });
  },

  /** GET /tasks/{id}/handoff (latest handoff, or null) */
  getTaskHandoff(taskId: string, signal?: AbortSignal): Promise<TaskHandoffData> {
    return request<TaskHandoffData>(`/tasks/${encodeURIComponent(taskId)}/handoff`, { signal });
  },

  /** GET /tasks/{id}/approvals */
  getTaskApprovals(taskId: string, signal?: AbortSignal): Promise<TaskApprovalsData> {
    return request<TaskApprovalsData>(`/tasks/${encodeURIComponent(taskId)}/approvals`, { signal });
  },

  /** GET /tasks/{id}/dispatches */
  getTaskDispatches(taskId: string, signal?: AbortSignal): Promise<TaskDispatchesData> {
    return request<TaskDispatchesData>(`/tasks/${encodeURIComponent(taskId)}/dispatches`, { signal });
  },

  /** GET /tasks/{id}/panel */
  getTaskPanel(taskId: string, signal?: AbortSignal): Promise<TaskPanelData> {
    return request<TaskPanelData>(`/tasks/${encodeURIComponent(taskId)}/panel`, { signal });
  },

  // -------------------------------------------------------------------
  // Governed actions (M2): approvals, messages, transitions, dispatch
  // -------------------------------------------------------------------

  /**
   * POST /tasks/{id}/messages — post a chat message, visible to all agents
   * on the task. `role` defaults to "user"; `target` defaults to
   * "Current task agents".
   */
  postTaskMessage(
    taskId: string,
    body: { content: string; role?: string; target?: string },
    signal?: AbortSignal,
  ): Promise<TaskMessageResult> {
    return request<TaskMessageResult>(`/tasks/${encodeURIComponent(taskId)}/messages`, {
      method: "POST",
      body,
      signal,
    });
  },

  /**
   * POST /tasks/{id}/approve — record an approval-gate decision
   * (`status: "approved" | "rejected"`). Approving the "Task graph" gate
   * triggers `auto_schedule` of ready units server-side.
   */
  recordApproval(
    taskId: string,
    body: { name: string; status: string; metadata?: Record<string, unknown> },
    signal?: AbortSignal,
  ): Promise<ApprovalActionData> {
    return request<ApprovalActionData>(`/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: "POST",
      body,
      signal,
    });
  },

  /**
   * POST /tasks/{id}/graph-draft — generate (or fetch) the task graph after
   * "PRD/AC" is approved; opens a new "Task graph" approval gate.
   */
  createGraphDraft(taskId: string, signal?: AbortSignal): Promise<GraphDraftData> {
    return request<GraphDraftData>(`/tasks/${encodeURIComponent(taskId)}/graph-draft`, {
      method: "POST",
      signal,
    });
  },

  /**
   * POST /tasks/{id}/schedule — schedule all ready units (requires the
   * "Task graph" gate to be approved).
   */
  scheduleTask(taskId: string, signal?: AbortSignal): Promise<ScheduleResult> {
    return request<ScheduleResult>(`/tasks/${encodeURIComponent(taskId)}/schedule`, {
      method: "POST",
      signal,
    });
  },

  /**
   * POST /subtasks/{id}/transition — move a unit to `status` (e.g. requeue a
   * rejected/failed unit back to "queued", or mark "complete"/"skipped").
   */
  transitionSubtask(
    subtaskId: string,
    body: { status: string; actor?: string; reason?: string },
    signal?: AbortSignal,
  ): Promise<SubtaskTransitionResult> {
    return request<SubtaskTransitionResult>(`/subtasks/${encodeURIComponent(subtaskId)}/transition`, {
      method: "POST",
      body,
      signal,
    });
  },

  /**
   * POST /subtasks/{id}/dispatch — dispatch an in-progress unit to
   * `provider` (defaults to "local"). Used for both initial dispatch and
   * "reroute provider" retries.
   */
  dispatchSubtask(
    subtaskId: string,
    body: { provider?: string; worker_id?: string } = {},
    signal?: AbortSignal,
  ): Promise<SubtaskDispatchResult> {
    return request<SubtaskDispatchResult>(`/subtasks/${encodeURIComponent(subtaskId)}/dispatch`, {
      method: "POST",
      body,
      signal,
    });
  },

  /** POST /tasks/{id}/handoff — produce the final handoff dossier. */
  createTaskHandoff(taskId: string, signal?: AbortSignal): Promise<CreateHandoffResult> {
    return request<CreateHandoffResult>(`/tasks/${encodeURIComponent(taskId)}/handoff`, {
      method: "POST",
      signal,
    });
  },

  /**
   * POST /tasks/{id}/repository-action — approve (or no-op) the repo action
   * recorded on the handoff. `approved` must be `true`; `action` is one of
   * the handoff's `repository_action_gate.metadata.allowed_actions`.
   */
  recordRepositoryAction(
    taskId: string,
    body: { approved: boolean; action: string; note?: string },
    signal?: AbortSignal,
  ): Promise<RepositoryActionResult> {
    return request<RepositoryActionResult>(`/tasks/${encodeURIComponent(taskId)}/repository-action`, {
      method: "POST",
      body,
      signal,
    });
  },

  // -------------------------------------------------------------------
  // Wiki
  // -------------------------------------------------------------------

  /** GET /workspaces/{id}/wiki */
  getWiki(workspaceId: string, signal?: AbortSignal): Promise<WikiIndexData> {
    return request<WikiIndexData>(`/workspaces/${encodeURIComponent(workspaceId)}/wiki`, { signal });
  },

  /** GET /workspaces/{id}/wiki/{page} */
  getWikiPage(workspaceId: string, page: string, signal?: AbortSignal): Promise<WikiPageData> {
    return request<WikiPageData>(
      `/workspaces/${encodeURIComponent(workspaceId)}/wiki/${encodeURIComponent(page)}`,
      { signal },
    );
  },

  // -------------------------------------------------------------------
  // Workspace projections: operational views, repositories, proposals,
  // usage stats
  // -------------------------------------------------------------------

  /** GET /workspaces/{id}/operational-views */
  getWorkspaceOperationalViews(
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<OperationalViewsData> {
    return request<OperationalViewsData>(
      `/workspaces/${encodeURIComponent(workspaceId)}/operational-views`,
      { signal },
    );
  },

  /** GET /workspaces/{id}/repositories */
  getWorkspaceRepositories(
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<WorkspaceRepositoriesData> {
    return request<WorkspaceRepositoriesData>(
      `/workspaces/${encodeURIComponent(workspaceId)}/repositories`,
      { signal },
    );
  },

  /** GET /workspaces/{id}/projects */
  getProjects(workspaceId: string, signal?: AbortSignal): Promise<ProjectsData> {
    return request<ProjectsData>(`/workspaces/${encodeURIComponent(workspaceId)}/projects`, {
      signal,
    });
  },

  /** GET /workspaces/{id}/proposals */
  getProposals(workspaceId: string, signal?: AbortSignal): Promise<ProposalsData> {
    return request<ProposalsData>(`/workspaces/${encodeURIComponent(workspaceId)}/proposals`, {
      signal,
    });
  },

  /**
   * GET /workspaces/{id}/usage-stats
   *
   * HarnessOutcome-derived quality signals for a workspace (test pass rate,
   * avg blast radius, total tokens, policy proposal counts) plus a per-task
   * breakdown. Backed by `src.service.usage_stats.build_usage_stats`.
   */
  getUsageStats(workspaceId: string, signal?: AbortSignal): Promise<UsageStatsData> {
    return request<UsageStatsData>(
      `/workspaces/${encodeURIComponent(workspaceId)}/usage-stats`,
      { signal },
    );
  },
};
