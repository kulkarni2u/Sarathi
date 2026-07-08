// Subscription helper for task lifecycle events.
//
// Transports:
// 1. EventSource (SSE) to `/workspaces/{ws}/tasks/{task}/events/stream`:
//    Receives real-time events as SSE frames. Token is passed as a query
//    parameter since EventSource cannot set custom headers. On error, falls
//    back to the polling transport below.
// 2. JSON polling to `GET /events?workspace_id&task_id` (fallback):
//    Polls the endpoint on an interval and emits the full event list each
//    tick (the caller is responsible for de-duplication if needed).
//
// Both transports emit the same `LifecycleEvent[]` batches via `onEvents`
// and return an `Unsubscribe` function. The EventSource transport is
// attempted first; after two consecutive errors without a successful
// message, it switches to polling permanently.

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
 * Primary transport: connects to the SSE endpoint at
 * `/workspaces/{ws}/tasks/{task}/events/stream` and dispatches each event
 * as a single-element LifecycleEvent[]. On the first error, allows
 * EventSource to auto-retry. On a second consecutive error without an
 * intervening successful message, closes the EventSource and falls back to
 * JSON polling.
 *
 * Fallback transport: polls `GET /events` on an interval and emits the full
 * event list each tick. The two transports share the same signature and
 * return an identical `Unsubscribe` contract.
 */
export function subscribeToEvents(
  params: EventsSubscriptionParams,
  options: EventsSubscriptionOptions,
): Unsubscribe {
  let cancelled = false;
  let currentCleanup: Unsubscribe | null = null;
  const cleanup = (): Unsubscribe => {
    return () => {
      cancelled = true;
      if (currentCleanup) {
        currentCleanup();
      }
    };
  };

  const startPolling = (): void => {
    const intervalMs = options.pollIntervalMs ?? 4000;
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

    currentCleanup = () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  };

  const startSse = (): void => {
    const url = buildEventsUrl(params);
    let eventSource: EventSource | null = null;
    let errorCount = 0;
    let messageReceived = false;
    let fallbackInProgress = false;

    try {
      eventSource = new EventSource(url);

      eventSource.addEventListener("message", (event) => {
        if (cancelled || fallbackInProgress) return;
        // Reset error count on successful message
        messageReceived = true;
        errorCount = 0;

        // Each SSE message represents a single LifecycleEvent
        try {
          const data = JSON.parse(event.data) as LifecycleEvent;
          // Emit as a single-element array to match polling transport shape
          options.onEvents([data]);
        } catch (parseErr) {
          // Silently skip unparseable events
          console.warn("Failed to parse SSE event data:", parseErr);
        }
      });

      eventSource.addEventListener("error", (_event) => {
        if (cancelled || fallbackInProgress) return;

        errorCount++;
        // Allow one auto-retry by EventSource before we close and fall back
        if (errorCount >= 2 || !messageReceived) {
          // Two consecutive errors or error before any message: close SSE and fall back to polling
          fallbackInProgress = true;
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }

          if (!cancelled) {
            // Fall back to polling
            startPolling();
          }
        }
      });
    } catch (err) {
      // EventSource creation failed (e.g., bad URL, unsupported environment)
      if (!cancelled) {
        startPolling();
      }
    }

    currentCleanup = () => {
      cancelled = true;
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };
  };

  // Start with SSE; if it fails to initialize, it will fall back to polling
  startSse();

  return cleanup();
}

/**
 * Build the absolute URL to the SSE events stream endpoint.
 *
 * Path: `/workspaces/{workspace_id}/tasks/{task_id}/events/stream`
 *
 * EventSource cannot send custom Authorization headers, so the bearer token
 * (if present) is passed as a `token` query parameter. The service's
 * _authorize_stream method will check the query param if the Authorization
 * header is absent.
 */
export function buildEventsUrl(params: EventsSubscriptionParams): string {
  const { baseUrl, token } = getRuntimeConfig();

  // Default to same-origin if baseUrl is empty (single-origin deployment)
  if (!baseUrl) {
    const url = new URL(
      `/workspaces/${encodeURIComponent(params.workspaceId || "")}/tasks/${encodeURIComponent(
        params.taskId || "",
      )}/events/stream`,
      "http://localhost", // dummy base for URL construction
    );
    if (token) url.searchParams.set("token", token);
    // Return relative path for same-origin fetch
    return url.pathname + (url.search ? url.search : "");
  }

  // Cross-origin: build absolute URL
  const url = new URL(
    `/workspaces/${encodeURIComponent(params.workspaceId || "")}/tasks/${encodeURIComponent(
      params.taskId || "",
    )}/events/stream`,
    baseUrl + "/",
  );
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

export { ApiClientError };
