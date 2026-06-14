import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiClientError } from "../api/client";
import type { Workspace } from "../api/types";

const STORAGE_KEY = "sarathi.workspaceId";

export type ServiceStatus = "connecting" | "online" | "degraded" | "offline";

interface WorkspaceContextValue {
  workspaces: Workspace[];
  currentWorkspace: Workspace | null;
  currentWorkspaceId: string | null;
  setCurrentWorkspaceId: (id: string | null) => void;
  serviceStatus: ServiceStatus;
  loading: boolean;
  error: ApiClientError | Error | null;
  refresh: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

function readStoredWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentWorkspaceId, setCurrentWorkspaceIdState] = useState<string | null>(readStoredWorkspaceId);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus>("connecting");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const setCurrentWorkspaceId = useCallback((id: string | null) => {
    setCurrentWorkspaceIdState(id);
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(STORAGE_KEY, id);
      else window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const refresh = useCallback(() => setRefreshNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);

      // Health check first: drives the "Connected · Live" / offline /
      // degraded presence indicator in the sidebar, independent of whether
      // workspaces happen to exist yet.
      try {
        const health = await api.getHealth(controller.signal);
        if (!cancelled) {
          setServiceStatus(health.status === "ok" ? "online" : "degraded");
        }
      } catch (err) {
        if (!cancelled) setServiceStatus("offline");
      }

      try {
        const data = await api.listWorkspaces(controller.signal);
        if (cancelled) return;
        setWorkspaces(data.workspaces ?? []);

        // Resolve current workspace selection: keep stored selection if it
        // still exists, otherwise fall back to the first workspace.
        setCurrentWorkspaceIdState((prev) => {
          const list = data.workspaces ?? [];
          if (prev && list.some((ws) => ws.id === prev)) return prev;
          const fallback = list[0]?.id ?? null;
          if (typeof window !== "undefined") {
            if (fallback) window.localStorage.setItem(STORAGE_KEY, fallback);
            else window.localStorage.removeItem(STORAGE_KEY);
          }
          return fallback;
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
          if (err instanceof ApiClientError && err.isNetworkError) {
            setServiceStatus("offline");
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [refreshNonce]);

  const currentWorkspace = useMemo(
    () => workspaces.find((ws) => ws.id === currentWorkspaceId) ?? null,
    [workspaces, currentWorkspaceId],
  );

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      currentWorkspace,
      currentWorkspaceId,
      setCurrentWorkspaceId,
      serviceStatus,
      loading,
      error,
      refresh,
    }),
    [workspaces, currentWorkspace, currentWorkspaceId, setCurrentWorkspaceId, serviceStatus, loading, error, refresh],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within a WorkspaceProvider");
  return ctx;
}
