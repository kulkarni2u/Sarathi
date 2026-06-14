// Subscription helper for GET /events?workspace_id&task_id.
//
// Today the endpoint returns a single JSON envelope ({ events: [...] }), so
// this helper polls it. The shape is designed so a later worker can swap the
// polling transport for a real `EventSource` (SSE) without changing call
// sites: `subscribeToEvents(...)` returns an `Unsubscribe` function either
// way, and emits the same `LifecycleEvent[]` batches via `onEvents`.
//
// When SSE lands server-side, replace the body of `subscribeToEvents` with
// an `EventSource` against the same URL (the query params are unchanged) and
// parse each `message` as a single LifecycleEvent, batching into arrays of
// length 1 before calling `onEvents`.

import { getRuntimeConfig } from "./runtimeConfig";
import { api, ApiClientError } from "./client";
import type { LifecycleEvent } from "./types";

export interface EventsSubscriptionParams {
  workspaceId?: string;
  taskId?: string;
}

export interface EventsSubscriptionOptions {
  /** Called with each new batch of events. */
  onEvents: (events: LifecycleEvent[]) => void;
  /** Called on transport errors (network failures, non-ok responses). */
  onError?: (error: unknown) => void;
  /** Polling interval in ms while using the JSON fallback transport. Default 4000. */
  pollIntervalMs?: number;
}

export type Unsubscribe = () => void;

/**
 * Subscribe to lifecycle events for a workspace/task.
 *
 * Current transport: polls `GET /events` on an interval and emits the full
 * event list each tick (the caller is responsible for de-duplication if
 * needed). Returns an unsubscribe function that stops polling.
 *
 * Swappable: once the service exposes a real SSE stream at the same path,
 * this function's internals can switch to `new EventSource(url)` while
 * keeping the same signature and `Unsubscribe` contract.
 */
export function subscribeToEvents(
  params: EventsSubscriptionParams,
  options: EventsSubscriptionOptions,
): Unsubscribe {
  const intervalMs = options.pollIntervalMs ?? 4000;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    if (cancelled) return;
    try {
      const data = await api.getEvents({
        workspaceId: params.workspaceId,
        taskId: params.taskId,
      });
      if (!cancelled) {
        options.onEvents(data.events ?? []);
      }
    } catch (err) {
      if (!cancelled) {
        options.onError?.(err);
      }
    } finally {
      if (!cancelled) {
        timer = setTimeout(tick, intervalMs);
      }
    }
  };

  void tick();

  return () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
  };
}

/**
 * Build the absolute /events URL (with auth handled separately, since
 * EventSource cannot set custom headers). Exposed for a future SSE
 * implementation; not used by the polling transport above.
 */
export function buildEventsUrl(params: EventsSubscriptionParams): string {
  const { baseUrl, token } = getRuntimeConfig();
  const url = new URL("/events", baseUrl + "/");
  if (params.workspaceId) url.searchParams.set("workspace_id", params.workspaceId);
  if (params.taskId) url.searchParams.set("task_id", params.taskId);
  // EventSource can't send Authorization headers; if/when SSE auth is
  // needed, the service will likely accept a `token` query param or rely on
  // cookie-based auth. Included here for forward-compatibility.
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

export { ApiClientError };
