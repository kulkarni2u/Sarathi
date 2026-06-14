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
  EventsData,
  GetWorkspaceData,
  HealthData,
  ListWorkspacesData,
  OperationalViewsData,
  ProjectsData,
  ProposalsData,
  ProvidersData,
  TaskApprovalsData,
  TaskDashboardData,
  TaskDispatchesData,
  TaskEvidenceData,
  TaskGraphData,
  TaskHandoffData,
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
  const url = new URL(path.replace(/^\/+/, "/"), baseUrl + "/");
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
