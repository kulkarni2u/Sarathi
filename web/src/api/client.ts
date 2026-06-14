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
  ProvidersData,
  TaskDashboardData,
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
};
