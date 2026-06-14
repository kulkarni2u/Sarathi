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
