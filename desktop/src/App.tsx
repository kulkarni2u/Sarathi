import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Badge, Theme } from "@radix-ui/themes";
if (typeof globalThis !== "undefined" && !(globalThis as Record<string, unknown>).__SARATHI_RUNTIME_CONFIG__) {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  const baseUrl = env?.VITE_SARATHI_API_BASE_URL;
  if (baseUrl) {
    (globalThis as typeof globalThis & { __SARATHI_RUNTIME_CONFIG__?: unknown }).__SARATHI_RUNTIME_CONFIG__ = {
      baseUrl,
      token: null,
    };
  }
}
import {
  ActivityLogIcon,
  ArchiveIcon,
  BarChartIcon,
  CheckboxIcon,
  ChevronRightIcon,
  CodeIcon,
  ClockIcon,
  DashboardIcon,
  FileIcon,
  FileTextIcon,
  GearIcon,
  LayersIcon,
  LoopIcon,
  MagnifyingGlassIcon,
  MixIcon,
  MoonIcon,
  PersonIcon,
  PlusIcon,
  Share2Icon,
  SunIcon,
  TimerIcon,
  } from "@radix-ui/react-icons";
import {
  addBrainstormTurn,
  attachWorkspaceRepository,
  approveDogfoodLearning,
  approveRepositoryAction,
  approveTaskGate,
  createWorkspace,
  createWorkspaceProject,
  createTaskHandoff,
  createTaskGraphDraft,
  createBrainstormSession,
  createTaskDraft,
  dispatchSubtask,
  ensureWorkspace,
  getSarathiApiConfig,
  getEventsStreamUrl,
  getDogfoodAcceptance,
  getTaskStudio,
  getWorkspaceOperationalViews,
  initializeWorkspaceRepository,
  listEvents,
  listProviders,
  listTaskDashboard,
  listWorkspaceProjects,
  listWorkspaceRepositories,
  listWorkspaces,
  previewWorkspaceRepository,
  runTaskReview,
  scheduleTask,
  sendChatMessage,
  sendTaskMessage,
  testProviderConnection,
  transitionSubtask,
  type ApprovalGateRecord,
  type BrainstormSession,
  type DispatchRecord,
  type DogfoodAcceptanceSnapshot,
  type EvidenceArtifactRecord,
  type HandoffRecord,
  type LifecycleEventRecord,
  type MessageRecord,
  type OperationalViewsSnapshot,
  type ProviderHealthRecord,
  type ReviewRunRecord,
  type RepositoryIntakePreview,
  type TaskDashboardItem,
  type TaskDraftResult,
  type TaskGraphDraftResult,
  type TaskGraphNode,
  type TaskStudioSnapshot,
  type WorkspaceProjectRecord,
  type WorkspaceRecord,
} from "./apiClient";
import {
  approvalGates,
  events,
  evidence,
  messages,
  providers,
  reviews,
  roles,
  subtasks,
  tasks,
  workspace,
  type Tone,
} from "./mockData";

import WorkspacesHome from "./pages/WorkspacesHome";
import WorkspaceDashboard from "./pages/WorkspaceDashboard";
import Dashboard from "./pages/Dashboard";
import InboxPage from "./pages/Inbox";
import AgentsPage from "./pages/Agents";
import SettingsPage from "./pages/Settings";
import ProjectDetail from "./pages/ProjectDetail";
import BrainstormPage from "./pages/Brainstorm";
import KnowledgeCenter, { type KnowledgeCenterSection } from "./pages/KnowledgeCenter";
import SkillsPage from "./pages/Skills";

type BrainstormStarter = string | {
  title: string;
  prompt?: string;
  metadata?: BrainstormSession["metadata"];
};

export type AppRoute = "workspace" | "dashboard" | "inbox" | "agents" | "settings" | "project" | "brainstorm" | "knowledge" | "wiki" | "skills" | "context" | "proposals" | "learnings";

type TaskTab = "messages" | "evidence" | "review" | "history" | "handoff";

type StudioUnit = {
  id: string;
  title: string;
  state: string;
  role: string;
  provider: string;
  blockedBy: string[];
  evidenceCount: number;
  review: string;
  ac: string[];
  goal: string;
  context: string;
  files: string[];
  nextAction: string;
  x: number;
  y: number;
};

const routeIcons: Record<AppRoute, ReactNode> = {
  workspace:   <MixIcon />,
  dashboard:   <MixIcon />,
  inbox:       <ArchiveIcon />,
  agents:      <PersonIcon />,
  settings:    <GearIcon />,
  project:     <LayersIcon />,
  brainstorm:  <MixIcon />,
  knowledge:   <FileTextIcon />,
  wiki:        <FileIcon />,
  skills:      <CodeIcon />,
  context:     <TimerIcon />,
  proposals:   <MixIcon />,
  learnings:   <MixIcon />,
};

const routes: Record<AppRoute, string> = {
  workspace: "Workspace",
  dashboard: "Dashboard",
  inbox: "Inbox",
  agents: "Agents",
  settings: "Settings",
  project: "Project",
  brainstorm: "Brainstorm",
  knowledge: "Knowledge Center",
  wiki: "Wiki",
  skills: "Skills",
  context: "Context",
  proposals: "Proposals",
  learnings: "Learnings",
};

function mergeWorkspaceProjects(
  existing: WorkspaceProjectRecord[],
  incoming: WorkspaceProjectRecord[],
): WorkspaceProjectRecord[] {
  if (existing.length === 0) return incoming;
  if (incoming.length === 0) return existing;
  const merged = [...incoming];
  const seen = new Set(incoming.map((project) => project.id));
  for (const project of existing) {
    if (!seen.has(project.id)) {
      merged.push(project);
    }
  }
  return merged;
}

type NavItem = { id: AppRoute; count?: string };
type NavGroup = { label: string; items: NavItem[] };

function buildNavGroups(counts: { inbox: string; dashboard: string; agents: string }): NavGroup[] {
  return [
    {
      label: "Main",
      items: [
        { id: "workspace", count: "live" },
        { id: "dashboard", count: counts.dashboard || undefined },
        { id: "inbox", count: counts.inbox || undefined },
      ],
    },
    {
      label: "Library",
      items: [
        { id: "agents", count: counts.agents || undefined },
        { id: "knowledge" },
        { id: "skills" },
      ],
    },
    {
      label: "Operate",
      items: [
        { id: "settings" },
      ],
    },
  ];
}

function knowledgeSectionForRoute(route: AppRoute): KnowledgeCenterSection {
  if (route === "wiki") return "wiki";
  if (route === "context") return "context";
  if (route === "proposals") return "proposals";
  if (route === "learnings") return "learnings";
  return "overview";
}

function isKnowledgeRoute(route: AppRoute) {
  return route === "knowledge" || route === "wiki" || route === "context" || route === "proposals" || route === "learnings";
}

function isNavItemActive(route: AppRoute, itemId: AppRoute) {
  if (itemId === "knowledge") {
    return isKnowledgeRoute(route);
  }
  return route === itemId;
}

const WORKSPACE_SELECTION_KEY = "sarathi.desktop.workspace.selection.v1";

function mockProjectTasks(): TaskDashboardItem[] {
  return tasks.map((task) => ({
    id: task.id,
    workspace_id: workspace.id,
    title: task.title,
    status: task.status === "in_progress"
      ? "in_progress"
      : task.status === "complete"
        ? "done"
        : "prd_pending",
    phase: task.phase,
    approval_state: task.reviewState,
    graph_state: "ready",
    next_gate: task.status === "waiting_human" ? "approval required" : null,
    node_count: task.progress > 0 ? Math.ceil(task.progress / 25) : 1,
    blocked_count: 0,
    review_needed_count: 0,
    checkpoint_state: "none",
    handoff_state: "none",
    roles: ["Pravaha"],
    providers: ["Codex"],
    updated_at: new Date(Date.now() - 5 * 60000).toISOString(),
  }));
}

function readSelectedWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(WORKSPACE_SELECTION_KEY);
  } catch {
    return null;
  }
}

function saveSelectedWorkspaceId(workspaceId: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (workspaceId) {
      window.localStorage.setItem(WORKSPACE_SELECTION_KEY, workspaceId);
    } else {
      window.localStorage.removeItem(WORKSPACE_SELECTION_KEY);
    }
  } catch {
    // Ignore persistence failures in the desktop shell.
  }
}

export function App() {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [route, setRoute] = useState<AppRoute>("workspace");
  const [workspaces, setWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(apiConfigured);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(apiConfigured ? readSelectedWorkspaceId() : null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectsByWorkspace, setProjectsByWorkspace] = useState<Record<string, WorkspaceProjectRecord[]>>({});
  const [showWorkspaceCreate, setShowWorkspaceCreate] = useState(false);
const [workspaceSwitcherOpen, setWorkspaceSwitcherOpen] = useState(false);
  const [projectCreateRequest, setProjectCreateRequest] = useState(0);
  const [taskCreateRequest, setTaskCreateRequest] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
const [focusedLearningTaskId, setFocusedLearningTaskId] = useState<string | null>(null);
  const [focusedProposalId, setFocusedProposalId] = useState<string | null>(null);
  const [focusedSavedViewId, setFocusedSavedViewId] = useState<string | null>(null);
  const [brainstormSessionId, setBrainstormSessionId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<TaskDashboardItem | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState("ST-02");
  const [taskTab, setTaskTab] = useState<TaskTab>("messages");
  const [showList, setShowList] = useState(false);
  const [dark, setDark] = useState(false);
  const [liveTick, setLiveTick] = useState(0);
  const [streamState, setStreamState] = useState(apiConfigured ? "connecting" : "demo");
  const [streamDetail, setStreamDetail] = useState(apiConfigured ? "SSE connecting" : "Demo mode");
  const [navCounts, setNavCounts] = useState({ inbox: "0", dashboard: "0", agents: "0" });
  const workspacesRef = useRef<WorkspaceRecord[]>([]);
  const selectedWorkspaceIdRef = useRef<string | null>(selectedWorkspaceId);
  const workspaceMutationVersionRef = useRef(0);

  const selectedUnit = useMemo(
    () => subtasks.find((unit) => unit.id === selectedUnitId) ?? subtasks[0],
    [selectedUnitId],
  );

  const selectedWorkspace = useMemo(() => {
    return workspaces.find((candidate) => candidate.id === selectedWorkspaceId) ?? null;
  }, [workspaces, selectedWorkspaceId]);

  const selectedProjects = useMemo(
    () => (selectedWorkspaceId ? projectsByWorkspace[selectedWorkspaceId] ?? [] : []),
    [projectsByWorkspace, selectedWorkspaceId],
  );

  useEffect(() => {
    workspacesRef.current = workspaces;
  }, [workspaces]);

  useEffect(() => {
    selectedWorkspaceIdRef.current = selectedWorkspaceId;
  }, [selectedWorkspaceId]);

  const selectedProject = useMemo(
    () => selectedProjects.find((project) => project.id === selectedProjectId) ?? null,
    [selectedProjects, selectedProjectId],
  );

  useEffect(() => {
    saveSelectedWorkspaceId(selectedWorkspaceId);
  }, [selectedWorkspaceId]);

  useEffect(() => {
    let cancelled = false;
    async function loadWorkspaces() {
      setWorkspaceLoading(true);
      const requestMutationVersion = workspaceMutationVersionRef.current;
      try {
        const list = await listWorkspaces();
        if (cancelled) return;
        if (requestMutationVersion !== workspaceMutationVersionRef.current && list.length === 0) {
          return;
        }
        const currentWorkspaces = workspacesRef.current;
        const preserveLocalSelection = list.length === 0 && currentWorkspaces.length > 0;
        const nextList = preserveLocalSelection ? currentWorkspaces : list;
        setWorkspaces(nextList);
        const preferred = readSelectedWorkspaceId();
        const currentSelection = selectedWorkspaceIdRef.current;
        const nextWorkspace =
          nextList.find((candidate) => candidate.id === preferred)
          ?? nextList.find((candidate) => candidate.id === currentSelection)
          ?? nextList[0]
          ?? null;
        setSelectedWorkspaceId(nextWorkspace?.id ?? null);
        if (nextWorkspace) {
          const nextProjects = projectsByWorkspace[nextWorkspace.id] ?? [];
          setSelectedProjectId(nextProjects[0]?.id ?? null);
          if (nextProjects.length > 0) {
            setRoute("workspace");
          }
        } else {
          setSelectedProjectId(null);
          setRoute("workspace");
        }
      } catch (err) {
        if (!cancelled) {
          setWorkspaces([]);
          setSelectedWorkspaceId(null);
          setSelectedProjectId(null);
          setRoute("workspace");
          // Surface actionable error — connection refused means service not running
          const msg = err instanceof Error ? err.message : String(err);
          const isOffline = msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("ECONNREFUSED");
          if (isOffline) {
            setStreamDetail("Sarathi service not running — start it with: sarathi-desktop");
            setStreamState("offline");
          }
        }
      } finally {
        if (!cancelled) {
          setWorkspaceLoading(false);
        }
      }
    }
    void loadWorkspaces();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured]);

  useEffect(() => {
    if (!apiConfigured || !selectedWorkspaceId) return;
    const workspaceId = selectedWorkspaceId;
    let cancelled = false;
    const requestVersion = workspaceMutationVersionRef.current;
    async function loadProjects() {
      try {
        const projects = await listWorkspaceProjects(workspaceId);
        if (cancelled) return;
        if (workspaceMutationVersionRef.current !== requestVersion) return;
        setProjectsByWorkspace((current) => ({
          ...current,
          [workspaceId]: mergeWorkspaceProjects(current[workspaceId] ?? [], projects),
        }));
        if (projects.length > 0) {
          setSelectedProjectId((prev) => {
            const hasCurrent = projects.some((p) => p.id === prev);
            return hasCurrent && prev ? prev : projects[0].id;
          });
        }
      } catch {
        if (!cancelled) {
          setProjectsByWorkspace((current) => ({
            ...current,
            [workspaceId]: [],
          }));
        }
      }
    }
    void loadProjects();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, selectedWorkspaceId]);

  useEffect(() => {
    if (!apiConfigured || !selectedWorkspaceId) return;
    const workspaceId = selectedWorkspaceId;
    let cancelled = false;
    async function refreshNavCounts() {
      try {
        const operations = await getWorkspaceOperationalViews(workspaceId);
        if (cancelled) return;
        setNavCounts({
          inbox: operations.inbox.length > 0 ? String(operations.inbox.length) : "",
          dashboard: operations.usage.tasks.total > 0 ? String(operations.usage.tasks.total) : "",
          agents: operations.usage.providers.total > 0 ? String(operations.usage.providers.total) : "",
        });
      } catch {
        // fail silently — badges degrade to empty
      }
    }
    void refreshNavCounts();
    return () => { cancelled = true; };
  }, [apiConfigured, selectedWorkspaceId, liveTick]);

  useEffect(() => {
    if (!apiConfigured || !selectedWorkspace) {
      return;
    }
    const workspaceId = selectedWorkspace.id;
    const taskId = route === "project" ? selectedTaskId ?? undefined : undefined;
    let cancelled = false;
    let source: EventSource | null = null;
    let pollInterval: number | undefined;
    let observedEventCount = 0;

    async function startLiveUpdates() {
      try {
        const streamUrl = getEventsStreamUrl(workspaceId, taskId);
        if (!streamUrl || typeof EventSource === "undefined") {
          startPolling(workspaceId, taskId);
          return;
        }
        source = new EventSource(streamUrl);
        source.addEventListener("snapshot", (event) => {
          if (cancelled) return;
          const parsed = JSON.parse((event as MessageEvent).data) as { events?: LifecycleEventRecord[] };
          observedEventCount = parsed.events?.length ?? observedEventCount;
          setStreamState("connected");
          setStreamDetail(`SSE live / ${observedEventCount} events`);
          setLiveTick((tick) => tick + 1);
        });
        source.onerror = () => {
          if (cancelled) return;
          setStreamState("polling");
          setStreamDetail("SSE reconnecting; polling fallback active");
          source?.close();
          startPolling(workspaceId, taskId);
        };
      } catch (error) {
        if (!cancelled) {
          setStreamState("polling");
          setStreamDetail(error instanceof Error ? error.message : "Live updates fallback active");
        }
      }
    }

    function startPolling(workspaceId: string, taskId?: string) {
      if (pollInterval !== undefined) return;
      pollInterval = window.setInterval(() => {
        void listEvents(workspaceId, taskId).then((nextEvents) => {
          if (cancelled) return;
          if (nextEvents.length !== observedEventCount) {
            observedEventCount = nextEvents.length;
            setLiveTick((tick) => tick + 1);
          }
          setStreamState("polling");
          setStreamDetail(`Polling / ${observedEventCount} events`);
        });
      }, 5000);
    }

    void startLiveUpdates();
    return () => {
      cancelled = true;
      source?.close();
      if (pollInterval !== undefined) {
        window.clearInterval(pollInterval);
      }
    };
  }, [apiConfigured, selectedWorkspace, route, selectedTaskId]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setRoute("dashboard");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setRoute]);

  async function handleCreateWorkspace(name: string, rootPath: string): Promise<WorkspaceRecord> {
    workspaceMutationVersionRef.current += 1;
    if (!apiConfigured) {
      const created: WorkspaceRecord = {
        id: name.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `ws-${Date.now()}`,
        name: name.trim(),
        root_path: rootPath,
        metadata: {
          repo_count: 0,
          status: "live",
        },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setWorkspaces((current) => [created, ...current.filter((candidate) => candidate.id !== created.id)]);
      setSelectedWorkspaceId(created.id);
      setSelectedProjectId(null);
      setShowWorkspaceCreate(false);
      setRoute("workspace");
      return created;
    }
    const created = await createWorkspace(name, rootPath, { source: "desktop-ui", display_id: workspace.id });
    setWorkspaces((current) => [created, ...current.filter((candidate) => candidate.id !== created.id)]);
    setSelectedWorkspaceId(created.id);
    setSelectedProjectId(null);
    setShowWorkspaceCreate(false);
    setRoute("workspace");
    return created;
  }

  function handleWorkspaceSelection(workspaceId: string) {
    const nextWorkspace = workspaces.find((candidate) => candidate.id === workspaceId);
    if (!nextWorkspace) return;
    setShowWorkspaceCreate(false);
    setSelectedWorkspaceId(workspaceId);
    setSelectedTaskId(null);
    const nextProjects = projectsByWorkspace[workspaceId] ?? [];
    if (nextProjects.length > 0) {
      setSelectedProjectId(nextProjects[0].id);
    } else {
      setSelectedProjectId(null);
    }
    setRoute("workspace");
  }

async function handleCreateProject(name: string, description: string) {
    const workspaceId = selectedWorkspace?.id;
    if (!workspaceId) {
      throw new Error("Select a workspace first.");
    }
    workspaceMutationVersionRef.current += 1;
    const project = await createWorkspaceProject(workspaceId, { name, description });
    setProjectsByWorkspace((current) => ({
      ...current,
[workspaceId]: [...(current[workspaceId] ?? []), project],
    }));
    setSelectedProjectId(project.id);
    setShowWorkspaceCreate(false);
    setRoute("dashboard");
  }

  function handleOpenProject(projectId: string) {
    setSelectedProjectId(projectId);
    setRoute("dashboard");
  }

  async function handleStartBrainstorm(starter: BrainstormStarter) {
    const workspaceId = selectedWorkspace?.id;
    if (!workspaceId || !getSarathiApiConfig()) return;
    try {
      const title = typeof starter === "string" ? starter : starter.title;
      const session = await createBrainstormSession(workspaceId, title, {
        projectId: selectedProjectId ?? undefined,
        ...(typeof starter === "object" && starter.metadata ? { metadata: starter.metadata } : {}),
      });
      if (typeof starter === "object" && starter.prompt?.trim()) {
        await addBrainstormTurn(session.id, {
          role: "user",
          content: starter.prompt.trim(),
          selected: null,
        });
      }
      setBrainstormSessionId(session.id);
      setRoute("brainstorm");
    } catch {
      // fall back silently — no regression on brainstorm failure
    }
  }

  useEffect(() => {
    if (!selectedWorkspaceId) return;
    const nextProjects = projectsByWorkspace[selectedWorkspaceId] ?? [];
    if (nextProjects.length === 0) {
      return;
    }
    const hasCurrent = nextProjects.some((project) => project.id === selectedProjectId);
    if (!hasCurrent && selectedProjectId !== null) {
      setSelectedProjectId(nextProjects[0].id);
    }
  }, [projectsByWorkspace, selectedProjectId, selectedWorkspaceId]);

  const workspaceLabel = selectedWorkspace?.name ?? "No workspace yet";
  const workspaceMeta = selectedWorkspace ? `${selectedWorkspace.id} / ${selectedWorkspace.root_path || "no path"}` : "Create a workspace to continue";
  const currentProjects = selectedWorkspaceId ? projectsByWorkspace[selectedWorkspaceId] ?? [] : [];
  const showWorkspaceEmpty = !selectedWorkspace || workspaces.length === 0;
  const showProjectEmpty = !!selectedWorkspace && currentProjects.length === 0;
  const showCommandBar = route !== "workspace";
  const showStatusStrip = ["dashboard", "project"].includes(route);
  const primaryActionLabel =
    !selectedWorkspace
      ? "New workspace"
      : route === "workspace"
        ? "New project"
        : showProjectEmpty
          ? "New project"
          : "New task";
  const secondaryActionLabel = route === "dashboard" && selectedWorkspace
    ? "Workspace dashboard"
    : null;

  function openWorkspaceCreate() {
    setShowWorkspaceCreate(true);
  }

  function closeWorkspaceCreate() {
    setShowWorkspaceCreate(false);
  }

  function openProjectCreate() {
    if (!selectedWorkspace) {
      openWorkspaceCreate();
      return;
    }
    setProjectCreateRequest((current) => current + 1);
    setRoute("workspace");
  }

  function openTaskCreate() {
    if (!selectedWorkspace) {
      openWorkspaceCreate();
      return;
    }
    if (showProjectEmpty) {
      openProjectCreate();
      return;
    }
    setTaskCreateRequest((current) => current + 1);
    setRoute("dashboard");
  }

  return (
    <Theme
      accentColor="indigo"
      grayColor="gray"
      appearance={dark ? "dark" : "light"}
      radius="medium"
      scaling="100%"
      panelBackground="translucent"
    >
    <div className={dark ? "app dark" : "app"}>
      <aside className="sidebar hybrid-sidebar">
        <div className="workspace-context">
          <button className="brand" onClick={() => setRoute("workspace")}>
            <div className="brand-mark">S</div>
            <div className="brand-text">
              <strong>Sarathi</strong>
            </div>
          </button>

          <button
            className="workspace-chip hybrid-workspace-chip"
            onClick={() => setWorkspaceSwitcherOpen((open) => !open)}
            aria-expanded={workspaceSwitcherOpen}
            aria-haspopup="menu"
          >
            <span className="chip-status dot live" />
            <span className="chip-label">
              <span className="chip-name">{workspaceLabel}</span>
              {selectedWorkspace && <span className="chip-meta">{selectedWorkspace.id}</span>}
            </span>
            <ChevronRightIcon
              style={{
                color: "var(--h-faint)",
                flexShrink: 0,
                transform: workspaceSwitcherOpen ? "rotate(90deg)" : "none",
                transition: "transform 150ms ease",
              }}
            />
          </button>

          {workspaceSwitcherOpen && (
            <div className="workspace-switcher-popover">
              <div className="ws-popover-header">Switch workspace</div>
              <div className="ws-popover-list">
                {workspaces.map((ws) => {
                  const isCurrent = ws.id === selectedWorkspaceId;
                  return (
                    <button
                      key={ws.id}
                      className={`ws-popover-item${isCurrent ? " current" : ""}`}
                      onClick={() => {
                        handleWorkspaceSelection(ws.id);
                        setWorkspaceSwitcherOpen(false);
                      }}
                    >
                      <span className={`ws-popover-dot ${ws.metadata?.status === "live" ? "live" : ""}`} />
                      <span className="ws-popover-name">{ws.name}</span>
                      {isCurrent && <span className="ws-popover-check">✓</span>}
                    </button>
                  );
                })}
              </div>
              <div className="ws-popover-divider" />
              <button
                className="ws-popover-item ws-popover-create"
                onClick={() => {
                  setWorkspaceSwitcherOpen(false);
                  openWorkspaceCreate();
                }}
              >
                <PlusIcon style={{ width: 14, height: 14, flexShrink: 0 }} />
                <span>New workspace</span>
              </button>
            </div>
          )}
        </div>

        <nav aria-label="Primary" className="hybrid-nav">
          {buildNavGroups(navCounts).map((group) => (
            <section className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.map((item) => (
                <button
                  className={isNavItemActive(route, item.id) ? "nav-item active" : "nav-item"}
                  key={item.id}
                  onClick={() => {
                    if (item.id === "knowledge") {
                      setFocusedLearningTaskId(null);
                      setFocusedProposalId(null);
                    }
                    if (item.id === "workspace") {
                      setFocusedSavedViewId(null);
                    }
                    setRoute(item.id);
                  }}
                >
                  <span>{routeIcons[item.id]}{routes[item.id]}</span>
                  {item.count ? <em>{item.count}</em> : null}
                </button>
              ))}
            </section>
          ))}
        </nav>

        <section className="sidebar-card hybrid-status">
          <StatusLine tone="live" label="Sessions" value="3 active" />
          <StatusLine tone={streamTone(streamState)} label="Stream" value={streamState} />
        </section>
      </aside>

      <main className="main">
        <header
          className="topbar hybrid-topbar"
        >
          <div className="topbar-title">
            <span className="crumb">
              {selectedWorkspace ? `Workspace / ${selectedWorkspace.id}` : "Workspace / none"}
            </span>
            <h1>
              {route === "workspace"
                ? workspaceLabel
                : route === "dashboard" && selectedProject
                  ? selectedProject.name
                  : routes[route]}
            </h1>
          </div>
          {secondaryActionLabel && (
            <button
              className="secondary-action"
              onClick={() => {
                if (!selectedWorkspace) {
                  openWorkspaceCreate();
                  return;
                }
                setRoute("workspace");
              }}
            >
              {secondaryActionLabel}
            </button>
          )}
          <button className="icon-action" title="Toggle dark mode" onClick={() => setDark((value) => !value)}>
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
          <button
            className="primary"
            onClick={() => {
              if (!selectedWorkspace) {
                openWorkspaceCreate();
                return;
              }
              if (route === "workspace" || showProjectEmpty) {
                openProjectCreate();
                return;
              }
              openTaskCreate();
            }}
          >
            <PlusIcon />
            {primaryActionLabel}
          </button>
        </header>

        <div className="page-body">
          {showStatusStrip ? (
            <section className="status-strip" style={{ marginBottom: 18 }}>
              <Pill tone="active">Workspace {workspace.status}</Pill>
              <Pill tone="healthy">SQLite ready</Pill>
              <Pill tone={streamState === "connected" ? "healthy" : "warning"}>{streamDetail}</Pill>
              <Pill tone="warning">Dirty worktree</Pill>
            </section>
          ) : null}

          {!selectedWorkspace && (
            <WorkspacesHome
              workspaces={workspaces}
              loading={workspaceLoading}
              showCreate={showWorkspaceCreate}
              onCreateWorkspace={handleCreateWorkspace}
              onCloseCreate={closeWorkspaceCreate}
              onOpenCreate={openWorkspaceCreate}
              onSelectWorkspace={(selected) => handleWorkspaceSelection(selected.id)}
              selectedWorkspaceId={selectedWorkspaceId}
            />
          )}
          {route === "workspace" && selectedWorkspace && (
            <WorkspaceDashboard
              workspace={selectedWorkspace}
              projects={currentProjects}
              focusedSavedViewId={focusedSavedViewId}
              createRequestedAt={projectCreateRequest}
              onCreateProject={handleCreateProject}
              onOpenProject={handleOpenProject}
              onStartBrainstorm={handleStartBrainstorm}
              onOpenInbox={() => setRoute("inbox")}
              onOpenSavedView={(nextRoute) => setRoute(nextRoute)}
            />
          )}
          {route === "dashboard" && (
            !selectedWorkspace ? (
              <WorkspacesHome
                workspaces={workspaces}
                loading={workspaceLoading}
                showCreate={showWorkspaceCreate}
                onCreateWorkspace={handleCreateWorkspace}
                onCloseCreate={closeWorkspaceCreate}
                onOpenCreate={openWorkspaceCreate}
                onSelectWorkspace={(selected) => handleWorkspaceSelection(selected.id)}
                selectedWorkspaceId={selectedWorkspaceId}
              />
            ) : showProjectEmpty ? (
              <WorkspaceDashboard
                workspace={selectedWorkspace}
                projects={currentProjects}
                focusedSavedViewId={focusedSavedViewId}
                createRequestedAt={projectCreateRequest}
                onCreateProject={handleCreateProject}
                onOpenProject={handleOpenProject}
                onStartBrainstorm={handleStartBrainstorm}
                onOpenInbox={() => setRoute("inbox")}
                onOpenSavedView={(nextRoute) => setRoute(nextRoute)}
              />
            ) : (
<Dashboard
                workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? workspace.id}
                projectId={selectedProjectId ?? null}
                projectName={selectedProject?.name ?? workspaceLabel}
                tasks={null}
                setRoute={setRoute as unknown as (route: string) => void}
                liveTick={liveTick}
                createRequestedAt={taskCreateRequest}
                setSelectedTaskId={setSelectedTaskId}
              />
            )
          )}
          {route === "inbox" && <InboxPage workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? workspace.id} projectId={selectedProject?.id ?? null} setRoute={setRoute as unknown as (route: string) => void} liveTick={liveTick} setSelectedTaskId={setSelectedTaskId} />}
          {route === "agents" && <AgentsPage workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? workspace.id} liveTick={liveTick} />}
          {route === "settings" && <SettingsPage workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? null} />}
          {route === "project" && (
            <ProjectDetail
              workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? workspace.id}
              projectId={selectedProject?.id ?? null}
              selectedTaskId={selectedTaskId}
              setSelectedTaskId={setSelectedTaskId}
              setRoute={setRoute as unknown as (route: string) => void}
              liveTick={liveTick}
              onOpenProposal={(proposalId) => {
                setFocusedProposalId(proposalId);
                setFocusedLearningTaskId(null);
                setRoute("proposals");
              }}
              onOpenWorkspace={(viewId) => {
                setFocusedSavedViewId(viewId ?? null);
                setRoute("workspace");
              }}
            />
          )}
          {route === "brainstorm" && brainstormSessionId && (
            <BrainstormPage
              sessionId={brainstormSessionId}
              workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? workspace.id}
              onApproved={(taskId) => {
                setSelectedTaskId(taskId);
                setBrainstormSessionId(null);
                setRoute("project");
              }}
            />
          )}
          {isKnowledgeRoute(route) && (
            <KnowledgeCenter
              workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? null}
              activeSection={knowledgeSectionForRoute(route)}
              focusedLearningTaskId={focusedLearningTaskId}
              focusedProposalId={focusedProposalId}
              onSectionChange={(section) => {
                setFocusedLearningTaskId(null);
                setFocusedProposalId(null);
                if (section === "overview") {
                  setRoute("knowledge");
                  return;
                }
                setRoute(section);
              }}
              onOpenTask={(taskId) => {
                setSelectedTaskId(taskId);
                setRoute("project");
              }}
              onOpenWorkspace={(viewId) => {
                setFocusedSavedViewId(viewId ?? null);
                setRoute("workspace");
              }}
              onOpenLearning={(taskId) => {
                setFocusedLearningTaskId(taskId);
                setFocusedProposalId(null);
                setRoute("learnings");
              }}
              onOpenProposal={(proposalId) => {
                setFocusedProposalId(proposalId);
                setFocusedLearningTaskId(null);
                setRoute("proposals");
              }}
            />
          )}
          {route === "skills" && (
            <SkillsPage
              workspaceId={selectedWorkspaceId ?? selectedWorkspace?.id ?? null}
            />
          )}
        </div>
      </main>
    </div>
    </Theme>
  );
}

function Orchestrator({ setRoute }: { setRoute: (route: AppRoute) => void }) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [prompt, setPrompt] = useState("Build Sarathi UI through Sarathi dogfood workflow.");
  const [draft, setDraft] = useState<TaskDraftResult | null>(null);
  const [graphDraft, setGraphDraft] = useState<TaskGraphDraftResult | null>(null);
  const [status, setStatus] = useState(
    apiConfigured ? "Ready to create a durable PRD/AC draft." : "Demo mode. Configure local service to persist task drafts.",
  );
  const [isCreating, setIsCreating] = useState(false);

  async function createDraft() {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      setStatus("Describe the task before asking Sarathi to draft it.");
      return;
    }
    setIsCreating(true);
    try {
      if (!apiConfigured) {
        const demoDraft = createDemoTaskDraft(trimmedPrompt);
        setDraft(demoDraft);
        setStatus("Demo draft created locally. Start the local service to persist PRD/AC state.");
        return;
      }
      const selectedWorkspace = await ensureWorkspace(
        workspace.name,
        "/Users/sweethome/Work/Skills/Sarathi",
        { source: "desktop-ui", display_id: workspace.id },
      );
      const createdDraft = await createTaskDraft(
        selectedWorkspace.id,
        trimmedPrompt,
        trimmedPrompt.split(" ").slice(0, 5).join(" "),
      );
      setDraft(createdDraft);
      setStatus(`Durable task draft ${createdDraft.task.id} created with PRD/AC gate.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Task draft creation failed.");
    } finally {
      setIsCreating(false);
    }
  }

  async function approvePrdAndGenerateGraph() {
    if (!draft) {
      setStatus("Create a task draft before graph generation.");
      return;
    }
    setIsCreating(true);
    try {
      if (!apiConfigured) {
        const demoGraph = createDemoTaskGraphDraft(draft.task.id);
        setGraphDraft(demoGraph);
        setStatus("Demo graph created. Start the local service to persist graph approval.");
        return;
      }
      await approveTaskGate(draft.task.id, "PRD/AC", "approved");
      const createdGraph = await createTaskGraphDraft(draft.task.id);
      setGraphDraft(createdGraph);
      setStatus(`Task graph drafted with ${createdGraph.graph.nodes.length} units and approval pending.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Task graph generation failed.");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="grid two">
      <section className="panel">
        <PanelTitle title="Sarathi planning chat" badge="PRD/AC gate" />
        {messages.map((message) => (
          <MessageBubble key={`${message.from}-${message.tag}`} {...message} />
        ))}
        {draft?.messages.map((message) => (
          <MessageBubble
            key={message.id}
            from={message.role === "user" ? "You" : "Sarathi"}
            target={message.role === "user" ? "Sarathi" : "User"}
            tag={message.role === "user" ? "request" : "draft"}
            text={message.content}
            impact={message.task_id ? `linked task ${message.task_id.slice(0, 8)}` : "draft context"}
          />
        ))}
        <form className="composer" onSubmit={(e) => { e.preventDefault(); void createDraft(); }}>
          <span className="pill-mini">Current task agents</span>
          <input value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          <button className="primary" type="submit" disabled={isCreating}>
            {isCreating ? "Drafting" : "Send"}
          </button>
        </form>
        <small>{status}</small>
      </section>
      <section className="panel">
        <PanelTitle title="Draft task" badge={graphDraft ? "graph pending" : draft ? "prd pending" : "sample"} />
        <Field label="Task" value={draft ? draft.task.title : "SA-001 Sarathi UI foundation"} />
        <Field label="Complexity" value={draft?.task.metadata.complexity ?? "High - full lifecycle"} />
        <Field label="Approval" value={draft ? `${draft.approval_gate.name} ${draft.approval_gate.status}` : "PRD/AC and graph approved"} />
        {draft?.task.metadata.acceptance_criteria?.map((criterion) => (
          <Card key={criterion}>
            <strong>Acceptance criterion</strong>
            <p>{criterion}</p>
          </Card>
        ))}
        {graphDraft ? (
          <Card>
            <strong>Task graph approval</strong>
            <Pill tone="warning">{graphDraft.approval_gate.status}</Pill>
            <p>{graphDraft.graph.nodes.length} units generated. Execution remains blocked until graph approval.</p>
            <small>{graphDraft.graph.edges.length} dependency edges</small>
          </Card>
        ) : null}
        {graphDraft?.graph.nodes.map((node) => (
          <Card key={node.id}>
            <strong>{node.title}</strong>
            <Pill tone={node.status === "queued" ? "active" : "warning"}>{node.status}</Pill>
            <p>{node.role} / {node.provider}</p>
            <small>Evidence: {node.evidence_required.join(", ")}</small>
          </Card>
        ))}
        <Field label="Repo action" value="blocked until user approval" />
        <button className="full" onClick={approvePrdAndGenerateGraph} disabled={!draft || isCreating}>
          Approve PRD/AC and generate graph
        </button>
        <button className="primary full" onClick={() => setRoute("project")}>Open Task Studio</button>
      </section>
    </div>
  );
}

function createDemoTaskGraphDraft(taskId: string): TaskGraphDraftResult {
  const now = new Date().toISOString();
  const nodes = [
    {
      id: "demo-node-plan",
      title: "Confirm plan and task packet",
      status: "queued",
      role: "Disha",
      provider: "Codex",
      blocked_by: [],
      evidence_required: ["prd", "acceptance_criteria", "task_packet"],
      task_packet: { goal: "Confirm plan", context: "Demo graph", review_criteria: [] },
    },
    {
      id: "demo-node-build",
      title: "Implement scoped change",
      status: "blocked",
      role: "Pravaha",
      provider: "Codex",
      blocked_by: ["demo-node-plan"],
      evidence_required: ["changed_files", "tests"],
      task_packet: { goal: "Implement", context: "Demo graph", review_criteria: [] },
    },
    {
      id: "demo-node-review",
      title: "Review evidence and AC coverage",
      status: "blocked",
      role: "Nirnaya",
      provider: "Claude",
      blocked_by: ["demo-node-build"],
      evidence_required: ["review_verdict", "ac_coverage"],
      task_packet: { goal: "Review", context: "Demo graph", review_criteria: [] },
    },
  ];
  return {
    graph: {
      task_id: taskId,
      nodes,
      edges: [
        { from: "demo-node-plan", to: "demo-node-build", type: "blocks" },
        { from: "demo-node-build", to: "demo-node-review", type: "blocks" },
      ],
    },
    approval_gate: {
      id: "demo-graph-gate",
      workspace_id: "demo-workspace",
      task_id: taskId,
      name: "Task graph",
      status: "pending",
      metadata: { requires_human: true, node_count: 3 },
      created_at: now,
      updated_at: now,
    },
  };
}

function createDemoTaskDraft(prompt: string): TaskDraftResult {
  const now = new Date().toISOString();
  return {
    task: {
      id: "demo-task-draft",
      workspace_id: "demo-workspace",
      title: prompt.split(" ").slice(0, 5).join(" "),
      description: prompt,
      status: "prd_pending",
      metadata: {
        source_prompt: prompt,
        complexity: "high",
        phase: "prd_ac_draft",
        prd: {
          problem: prompt,
          goal: "Create a durable task draft through Sarathi.",
          scope: ["Capture prompt", "Draft PRD/AC", "Wait for approval"],
        },
        acceptance_criteria: [
          "Task draft exists in the selected workspace.",
          "Source prompt is preserved as a message.",
          "PRD/AC approval gate is pending before graph generation.",
        ],
      },
      created_at: now,
      updated_at: now,
    },
    approval_gate: {
      id: "demo-prd-ac-gate",
      workspace_id: "demo-workspace",
      task_id: "demo-task-draft",
      name: "PRD/AC",
      status: "pending",
      metadata: {},
      created_at: now,
      updated_at: now,
    },
    messages: [
      {
        id: "demo-user-message",
        workspace_id: "demo-workspace",
        task_id: "demo-task-draft",
        role: "user",
        content: prompt,
        metadata: {},
        created_at: now,
      },
      {
        id: "demo-sarathi-message",
        workspace_id: "demo-workspace",
        task_id: "demo-task-draft",
        role: "sarathi",
        content: "I drafted the PRD/AC shell and opened the PRD/AC approval gate.",
        metadata: {},
        created_at: now,
      },
    ],
  };
}

function TaskDashboard({
  liveTick,
  setRoute,
  setSelectedTask,
}: {
  liveTick: number;
  setRoute: (route: AppRoute) => void;
  setSelectedTask: (task: TaskDashboardItem | null) => void;
}) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [dashboardTasks, setDashboardTasks] = useState<TaskDashboardItem[]>(() =>
    tasks.map(mockTaskToDashboardItem),
  );
  const [filter, setFilter] = useState("all");
  const [showTable, setShowTable] = useState(true);
  const [status, setStatus] = useState(
    apiConfigured ? "Loading workspace tasks from local service." : "Demo task cards. Connect service for persisted tasks.",
  );

  useEffect(() => {
    if (!apiConfigured) {
      return;
    }
    let cancelled = false;
    async function loadDashboard() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const summaries = await listTaskDashboard(selectedWorkspace.id);
        if (!cancelled) {
          setDashboardTasks(summaries);
          setStatus(`${summaries.length} persisted tasks loaded from ${selectedWorkspace.id}.`);
        }
      } catch (error) {
        if (!cancelled) {
          setStatus(error instanceof Error ? error.message : "Task dashboard load failed.");
        }
      }
    }
    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, liveTick]);

  const filteredTasks = dashboardTasks.filter((task) => {
    if (filter === "all") return true;
    if (filter === "needs-approval") return task.approval_state.includes("pending");
    if (filter === "blocked") return task.blocked_count > 0;
    if (filter === "graph") return task.graph_state !== "not_started";
    if (filter === "codex") return task.providers.includes("Codex");
    return task.status === filter;
  });

  return (
    <section className="panel">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h2 style={{ fontSize: "0.9rem" }}>Tasks</h2>
          <Pill tone="default">{filteredTasks.length}</Pill>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div className="tabs" style={{ padding: "2px" }}>
            {[["all", "All"], ["needs-approval", "Needs approval"], ["blocked", "Blocked"], ["graph", "Has graph"]].map(([id, label]) => (
              <button className={filter === id ? "active" : ""} key={id} onClick={() => setFilter(id)} style={{ height: 26, fontSize: "0.78rem" }}>
                {label}
              </button>
            ))}
          </div>
          <button onClick={() => setShowTable((v) => !v)} style={{ height: 28, padding: "0 10px", fontSize: "0.78rem" }}>
            {showTable ? "Board" : "List"}
          </button>
        </div>
      </div>
      {showTable ? (
        <table>
          <thead>
            <tr><th>ID</th><th>Title</th><th>Status</th><th>Phase</th><th>Units</th><th>Providers</th></tr>
          </thead>
          <tbody>
            {filteredTasks.map((task) => (
              <tr key={task.id} onClick={() => { setSelectedTask(task); setRoute("project"); }}>
                <td style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "var(--muted)" }}>{task.id}</td>
                <td style={{ fontWeight: 500 }}>{task.title}</td>
                <td><Pill tone={stateTone(task.status)}>{task.status}</Pill></td>
                <td style={{ color: "var(--muted)" }}>{task.phase}</td>
                <td style={{ color: "var(--muted)" }}>{task.node_count} / {task.blocked_count} blocked</td>
                <td style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{task.providers.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="grid three">
        {filteredTasks.map((task) => (
        <button
          className="task-card"
          key={task.id}
          onClick={() => {
            setSelectedTask(task);
            setRoute("project");
          }}
        >
          <PanelTitle title={task.id} badge={task.status} />
          <h3>{task.title}</h3>
          <p>{task.next_gate ? `Next gate: ${task.next_gate}` : "No pending gate"}</p>
          <small>{task.roles.join(", ") || "No graph roles yet"} / {task.providers.join(", ") || "No provider"}</small>
          <div className="actions">
            <Pill tone="active">{task.phase}</Pill>
            <Pill tone={task.approval_state.includes("pending") ? "warning" : "healthy"}>
              {task.approval_state}
            </Pill>
            <Pill tone={task.blocked_count > 0 ? "blocked" : "active"}>
              {task.node_count} units / {task.blocked_count} blocked
            </Pill>
          </div>
        </button>
        ))}
      </div>
      )}
    </section>
  );
}

function mockTaskToDashboardItem(task: (typeof tasks)[number]): TaskDashboardItem {
  return {
    id: task.id,
    workspace_id: workspace.id,
    title: task.title,
    status: task.status,
    phase: task.phase,
    approval_state: task.reviewState,
    graph_state: task.status === "complete" ? "approved" : "pending_approval",
    next_gate: task.status === "complete" ? null : "Task graph",
    node_count: subtasks.length,
    blocked_count: subtasks.filter((unit) => unit.state === "blocked").length,
    review_needed_count: 0,
    checkpoint_state: "none",
    handoff_state: "none",
    roles: Array.from(new Set(subtasks.map((unit) => unit.role))),
    providers: Array.from(new Set(subtasks.map((unit) => unit.provider))),
    updated_at: new Date().toISOString(),
  };
}

function mapGraphNodeToStudioUnit(node: TaskGraphNode, index: number): StudioUnit {
  const positions = [
    { x: 120, y: 64 },
    { x: 360, y: 64 },
    { x: 240, y: 250 },
    { x: 120, y: 420 },
    { x: 360, y: 420 },
  ];
  const position = positions[index % positions.length];
  const reviewCriteria = node.task_packet.review_criteria ?? [];
  return {
    id: node.id,
    title: node.title,
    state: node.status,
    role: node.role || "Sahayaka",
    provider: node.provider || "Local deterministic",
    blockedBy: node.blocked_by,
    evidenceCount: node.evidence_required.length,
    review: node.status === "blocked" ? "waiting on dependency" : "not started",
    ac: reviewCriteria.length ? reviewCriteria : node.evidence_required,
    goal: node.task_packet.goal ?? node.title,
    context: node.task_packet.context ?? "Task packet context will be generated by Sarathi.",
    files: ["Task packet"],
    nextAction: nextActionForUnitState(node.status),
    x: position.x,
    y: position.y,
  };
}

function nextActionForUnitState(state: string): string {
  if (state === "blocked") return "Wait for blocker or request Sarathi intervention.";
  if (state === "queued") return "Claim when dependencies are clear.";
  if (state === "in_progress") return "Continue execution and attach evidence.";
  if (state === "complete") return "Await review or downstream unblock.";
  return "Review current lifecycle state.";
}

function formatRole(role: string): string {
  return role
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function SavedViews({ setRoute }: { setRoute: (route: AppRoute) => void }) {
  return (
    <section className="panel">
      <PanelTitle title="Built-in saved views" badge="MVP" />
      <div className="grid three">
        {[
          { id: "needs-approval", label: "Needs approval", target: "tasks" },
          { id: "blocked", label: "Blocked units", target: "tasks" },
          { id: "waiting_human", label: "Waiting human", target: "tasks" },
          { id: "review-failed", label: "Review failed", target: "history" },
          { id: "ready-pr", label: "Ready for PR", target: "history" },
          { id: "provider-failures", label: "Provider failures", target: "settings" },
        ].map((view) => (
          <button className="card" key={view.id} onClick={() => setRoute(view.target as AppRoute)}>
            <strong>{view.label}</strong>
            <p>Workspace-scoped filter for Tasks and History.</p>
          </button>
        ))}
      </div>
    </section>
  );
}

function TaskStudio({
  selectedUnit,
  selectedTask,
  projectId,
  selectedUnitId,
  setSelectedUnitId,
  taskTab,
  setTaskTab,
  showList,
  setShowList,
  liveTick,
}: {
  selectedUnit: StudioUnit;
  selectedTask: TaskDashboardItem | null;
  projectId?: string | null;
  selectedUnitId: string;
  setSelectedUnitId: (id: string) => void;
  taskTab: TaskTab;
  setTaskTab: (tab: TaskTab) => void;
  showList: boolean;
  setShowList: (value: boolean) => void;
  liveTick: number;
}) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [snapshot, setSnapshot] = useState<TaskStudioSnapshot | null>(null);
  const [loadStatus, setLoadStatus] = useState(
    apiConfigured ? "Select a persisted task to load its studio snapshot." : "Demo Task Studio. Connect service for persisted data.",
  );
  const [actionStatus, setActionStatus] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatStatus, setChatStatus] = useState("");

  async function handleChatSubmit(e: FormEvent) {
    e.preventDefault();
    if (!chatInput.trim()) return;
    const message = chatInput.trim();
    setChatInput("");
    setChatStatus("Dispatching…");
    try {
      const config = getSarathiApiConfig();
      console.log("[Chat] API Config:", config);
      if (!config) { setChatStatus("Connect service to use chat."); return; }
      const ws = await ensureWorkspace(workspace.name, "/Users/sweethome/Work/Skills/Sarathi");
      console.log("[Chat] Workspace:", ws.id);
      const result = await sendChatMessage(message, {
        workspaceId: ws.id,
        taskId: selectedTask?.id,
        projectId: projectId ?? undefined,
      });
      console.log("[Chat] Result:", result);
      setChatStatus(`Task ${result.taskId.slice(0, 8)} → ${result.agent}`);
    } catch (err) {
      console.error("[Chat] Error:", err);
      setChatStatus(err instanceof Error ? err.message : "Chat dispatch failed.");
    }
  }

  useEffect(() => {
    if (!apiConfigured || !selectedTask) {
      setSnapshot(null);
      return;
    }
    const taskId = selectedTask.id;
    let cancelled = false;
    async function loadStudio() {
      try {
        setLoadStatus(`Loading Task Studio for ${taskId}.`);
        const nextSnapshot = await getTaskStudio(taskId);
        if (!cancelled) {
          setSnapshot(nextSnapshot);
          setLoadStatus(
            `${nextSnapshot.graph.nodes.length} units, ${nextSnapshot.messages.length} messages, ${nextSnapshot.approval_gates.length} gates loaded from SQLite.`,
          );
          if (nextSnapshot.graph.nodes[0]) {
            setSelectedUnitId(nextSnapshot.graph.nodes[0].id);
          }
        }
      } catch (error) {
        if (!cancelled) {
          setSnapshot(null);
          setLoadStatus(error instanceof Error ? error.message : "Task Studio load failed.");
        }
      }
    }
    void loadStudio();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, selectedTask?.id, setSelectedUnitId, liveTick]);

  const studioUnits = snapshot ? snapshot.graph.nodes.map(mapGraphNodeToStudioUnit) : subtasks;
  const activeUnit =
    studioUnits.find((unit) => unit.id === selectedUnitId) ?? studioUnits[0] ?? selectedUnit;
  const graphEdges = snapshot?.graph.edges ?? [
    { from: "ST-01", to: "ST-02", type: "blocks" },
    { from: "ST-02", to: "ST-03", type: "blocks" },
    { from: "ST-03", to: "ST-04", type: "blocks" },
  ];
  const studioMessages = snapshot?.messages;
  const studioGates = snapshot?.approval_gates;
  const studioEvents = snapshot?.events;
  const studioDispatches = snapshot?.dispatches;
  const studioEvidence = snapshot?.evidence;
  const studioReviews = snapshot?.reviews;
  const studioHandoff = snapshot?.handoff;
  async function reloadStudioSnapshot() {
    if (!apiConfigured || !selectedTask) return;
    const nextSnapshot = await getTaskStudio(selectedTask.id);
    setSnapshot(nextSnapshot);
    setLoadStatus(
      `${nextSnapshot.graph.nodes.length} units, ${nextSnapshot.messages.length} messages, ${nextSnapshot.approval_gates.length} gates loaded from SQLite.`,
    );
  }
  async function scheduleReadyUnits() {
    if (!selectedTask) return;
    try {
      setActionStatus("Sutra is scheduling ready units.");
      const result = await scheduleTask(selectedTask.id);
      setActionStatus(`${result.scheduled.length} ready units scheduled; ${result.blocked.length} remain blocked.`);
      await reloadStudioSnapshot();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Schedule failed.");
    }
  }
  async function transitionSelectedUnit(status: string) {
    if (!activeUnit?.id || !selectedTask) return;
    try {
      setActionStatus(`Moving ${activeUnit.title} to ${status}.`);
      const result = await transitionSubtask(activeUnit.id, status);
      setActionStatus(
        `${result.subtask.title} is ${result.subtask.status}; ${result.unblocked.length} downstream units unblocked.`,
      );
      await reloadStudioSnapshot();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Lifecycle transition failed.");
    }
  }
  async function dispatchSelectedUnit() {
    if (!activeUnit?.id || !selectedTask) return;
    try {
      setActionStatus(`Dispatching ${activeUnit.title} to Local deterministic.`);
      const result = await dispatchSubtask(activeUnit.id, "local");
      setActionStatus(
        `${result.subtask.title} moved to ${result.subtask.status}; evidence ${result.evidence?.id.slice(0, 8) ?? "not created"}.`,
      );
      await reloadStudioSnapshot();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Dispatch failed.");
    }
  }

  const doneCount = studioUnits.filter((u) => u.state === "complete").length;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
        return;
      }
      if (studioUnits.length === 0) return;
      const currentIndex = studioUnits.findIndex((u) => u.id === selectedUnitId);
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        const nextIndex = (currentIndex + 1) % studioUnits.length;
        setSelectedUnitId(studioUnits[nextIndex].id);
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        const prevIndex = (currentIndex - 1 + studioUnits.length) % studioUnits.length;
        setSelectedUnitId(studioUnits[prevIndex].id);
      } else if (event.key === "Enter" && activeUnit?.state === "queued") {
        event.preventDefault();
        void transitionSelectedUnit("in_progress");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [studioUnits, selectedUnitId, setSelectedUnitId, activeUnit, selectedTask]);

  return (
    <div className="task-studio">
      {/* ── Left: graph pane ── */}
      <div className="graph-pane">
        <div className="graph-pane-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h3>{selectedTask ? selectedTask.title : "Dependency graph"}</h3>
            {selectedTask && (
              <Pill tone={selectedTask.approval_state === "approved" ? "healthy" : "warning"}>
                {selectedTask.approval_state}
              </Pill>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="graph-progress">{doneCount}/{studioUnits.length} done</span>
            <div className="tabs" style={{ padding: "2px", borderRadius: 6 }}>
              <button className={!showList ? "active" : ""} onClick={() => setShowList(false)}>Graph</button>
              <button className={showList ? "active" : ""} onClick={() => setShowList(true)}>List</button>
            </div>
            <button style={{ height: 28, padding: "0 8px", fontSize: "0.78rem" }}
              disabled={!selectedTask} onClick={scheduleReadyUnits}>
              Schedule
            </button>
          </div>
        </div>

        {showList ? (
          <div style={{ padding: "0 14px 14px" }}>
            <UnitTable units={studioUnits} selectedUnitId={selectedUnitId} setSelectedUnitId={setSelectedUnitId} />
          </div>
        ) : (
          <UnitGraph
            edges={graphEdges}
            units={studioUnits}
            selectedUnitId={selectedUnitId}
            setSelectedUnitId={setSelectedUnitId}
          />
        )}

        <div className="graph-legend">
          <span><span className="dot live" />done</span>
          <span><span className="dot" style={{ background: "var(--status-blue-fg)" }} />in progress</span>
          <span><span className="dot warn" />waiting</span>
          <span style={{ marginLeft: 4, borderLeft: "1px solid var(--border)", paddingLeft: 12 }}>
            <span className="graph-node-badge" style={{ position: "static" }}>CL</span> claude
          </span>
          <span>
            <span className="graph-node-badge" style={{ position: "static" }}>CO</span> codex
          </span>
          <span>
            <span className="graph-node-badge" style={{ position: "static" }}>CP</span> copilot
          </span>
          <span style={{ marginLeft: "auto", borderLeft: "1px solid var(--border)", paddingLeft: 12, fontSize: "0.68rem" }}>
            <kbd>j</kbd>/<kbd>k</kbd> nav · <kbd>Enter</kbd> claim
          </span>
        </div>
        {actionStatus && <div style={{ padding: "6px 14px", fontSize: "0.78rem", color: "var(--muted)", borderTop: "1px solid var(--border)" }}>{actionStatus}</div>}
      </div>

      {/* ── Right: chat pane ── */}
      <div className="chat-pane">
        <div className="chat-pane-header">
          <MagnifyingGlassIcon style={{ color: "var(--faint)", flexShrink: 0 }} />
          <input
            placeholder="Search messages..."
            style={{ flex: 1, border: 0, background: "transparent", outline: "none", fontSize: "0.83rem", color: "var(--ink)" }}
          />
        </div>
        <div className="chat-pane-tabs">
          {(["messages", "evidence", "review", "history", "handoff"] as TaskTab[]).map((tab) => (
            <button className={taskTab === tab ? "active" : ""} key={tab} onClick={() => setTaskTab(tab)}>
              {tab}
            </button>
          ))}
        </div>
        <div className="chat-pane-body">
          <UnitPacket
            unit={activeUnit}
            onDispatch={dispatchSelectedUnit}
            onTransition={transitionSelectedUnit}
          />
          <ApprovalGates gates={studioGates} />
          <TaskTabPanel
            tab={taskTab}
            taskId={selectedTask?.id}
            messages={studioMessages}
            events={studioEvents}
            dispatches={studioDispatches}
            evidence={studioEvidence}
            reviews={studioReviews}
            handoff={studioHandoff}
            onMessageSent={reloadStudioSnapshot}
            onReviewRun={reloadStudioSnapshot}
            onHandoffChange={reloadStudioSnapshot}
          />
        </div>
        <form className="chat-composer" onSubmit={(e) => void handleChatSubmit(e)}>
          <span style={{ fontSize: "0.78rem", color: "var(--muted)", whiteSpace: "nowrap" }}>You ▾</span>
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder={chatStatus || "Send a message to agents…"}
          />
          <button className="primary" type="submit" disabled={!chatInput.trim()} style={{ height: 30, padding: "0 10px", fontSize: "0.78rem" }}>
            <PlusIcon />
          </button>
        </form>
      </div>
    </div>
  );
}

function providerTag(provider: string): string {
  const p = provider.toLowerCase();
  if (p.includes("claude")) return "CL";
  if (p.includes("codex")) return "CO";
  if (p.includes("copilot")) return "CP";
  if (p.includes("local")) return "LC";
  return provider.slice(0, 2).toUpperCase();
}

function UnitGraph({
  edges,
  units,
  selectedUnitId,
  setSelectedUnitId,
}: {
  edges: Array<{ from: string; to: string; type: string }>;
  units: StudioUnit[];
  selectedUnitId: string;
  setSelectedUnitId: (id: string) => void;
}) {
  const nodeW = 210, nodeH = 44;
  return (
    <div className="graph">
      <svg className="graph-edges" aria-hidden="true">
        {edges.map((edge) => {
          const from = units.find((u) => u.id === edge.from);
          const to = units.find((u) => u.id === edge.to);
          if (!from || !to) return null;
          const fx = from.x + nodeW / 2, fy = from.y + nodeH;
          const tx = to.x + nodeW / 2, ty = to.y;
          const mid = (fy + ty) / 2;
          const isWaiting = to.state === "queued" || to.state === "waiting_human";
          return (
            <path
              className={isWaiting ? "waiting" : undefined}
              d={`M ${fx} ${fy} C ${fx} ${mid}, ${tx} ${mid}, ${tx} ${ty}`}
              key={`${edge.from}-${edge.to}`}
            />
          );
        })}
      </svg>
      {units.map((unit) => (
        <button
          className={unit.id === selectedUnitId ? "graph-node selected" : `graph-node ${unit.state}`}
          key={unit.id}
          style={{ left: unit.x, top: unit.y }}
          onClick={() => setSelectedUnitId(unit.id)}
        >
          <span className="graph-node-dot" />
          <span className="graph-node-body">
            <span className="graph-node-id">{unit.id}</span>
            <span className="graph-node-title">{unit.title}</span>
          </span>
          <span className="graph-node-badge">{providerTag(unit.provider)}</span>
        </button>
      ))}
    </div>
  );
}

function UnitTable({
  units,
  selectedUnitId,
  setSelectedUnitId,
}: {
  units: StudioUnit[];
  selectedUnitId: string;
  setSelectedUnitId: (id: string) => void;
}) {
  return (
    <table>
      <thead>
        <tr><th>Unit</th><th>State</th><th>Role / Provider</th><th>Blocked by</th><th>Evidence</th></tr>
      </thead>
      <tbody>
        {units.map((unit) => (
          <tr className={unit.id === selectedUnitId ? "selected-row" : ""} key={unit.id} onClick={() => setSelectedUnitId(unit.id)}>
            <td>{unit.id} - {unit.title}</td>
            <td>{unit.state}</td>
            <td>{unit.role} / {unit.provider}</td>
            <td>{unit.blockedBy.join(", ") || "None"}</td>
            <td>{unit.evidenceCount}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function UnitPacket({
  unit,
  onDispatch,
  onTransition,
}: {
  unit: StudioUnit;
  onDispatch?: () => Promise<void>;
  onTransition?: (status: string) => Promise<void>;
}) {
  return (
    <section className="panel">
      <PanelTitle title="Selected unit packet" badge={unit.state} />
      <Field label="Goal" value={unit.goal} />
      <Field label="Context" value={unit.context} />
      <Field label="Role lane" value={unit.role} />
      <Field label="Provider lane" value={unit.provider} />
      <Field label="Dependencies" value={unit.blockedBy.join(", ") || "None"} />
      <Field label="AC links" value={unit.ac.join(", ")} />
      <Field label="Files" value={unit.files.join(", ")} />
      <Field label="Next action" value={unit.nextAction} />
      {onTransition ? (
        <div className="actions">
          {onDispatch ? <button onClick={() => void onDispatch()}>Dispatch local</button> : null}
          <button onClick={() => void onTransition("in_progress")}>Claim</button>
          <button onClick={() => void onTransition("review")}>Review</button>
          <button onClick={() => void onTransition("complete")}>Complete</button>
          <button onClick={() => void onTransition("blocked")}>Block</button>
          <button onClick={() => void onTransition("waiting_human")}>Needs human</button>
        </div>
      ) : null}
    </section>
  );
}

function ApprovalGates({ gates }: { gates?: ApprovalGateRecord[] }) {
  if (gates) {
    return (
      <section className="panel">
        <PanelTitle title="Named approval gates" badge="SQLite" />
        {gates.map((gate) => (
          <Card key={gate.id}>
            <strong>{gate.name}</strong>
            <Pill tone={stateTone(gate.status)}>{gate.status}</Pill>
            <p>{gate.metadata.requires_human ? "Human approval required." : "Recorded approval state."}</p>
            <small>{gate.id} / {gate.created_at}</small>
          </Card>
        ))}
      </section>
    );
  }
  return (
    <section className="panel">
      <PanelTitle title="Named approval gates" badge="audited" />
      {approvalGates.map((gate) => (
        <Card key={gate.id}>
          <strong>{gate.id} - {gate.name}</strong>
          <Pill tone={stateTone(gate.status)}>{gate.status}</Pill>
          <p>{gate.help}</p>
          <small>Audit {gate.auditEventId} / {gate.linkedObjects.join(", ")}</small>
        </Card>
      ))}
    </section>
  );
}

type ArtifactReviewFinding = {
  message: string;
  severity: string | null;
  provider: string | null;
  filePath: string | null;
  check: string | null;
  acId: string | null;
  criterion: string | null;
  lineStart: number | null;
  lineEnd: number | null;
  confidence: number | null;
  source: string | null;
};

type ArtifactSnapshot = {
  filesChanged: string[];
  testsRun: string[];
  knownRisks: string[];
  reviewFindings: ArtifactReviewFinding[];
};

type DispatchTraceSource = {
  label: string;
  detail: string;
};

type DispatchInspectorModel = {
  objective: string | null;
  tokenBudget: number | null;
  estimatedTokens: number | null;
  summary: string | null;
  nextAgent: string | null;
  findings: string[];
  decisions: string[];
  artifacts: ArtifactSnapshot;
  traceSources: DispatchTraceSource[];
};

type ArtifactOverviewModel = ArtifactSnapshot & {
  dispatchCount: number;
  evidenceCount: number;
  reviewEvidenceCount: number;
  testEvidenceCount: number;
};

type CompletionContextModel = {
  filesChanged: string[];
  testsRun: string[];
  findings: string[];
  risks: string[];
  summaries: string[];
  decisions: string[];
};

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringList(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item).trim())
    .filter((item) => item.length > 0);
}

function uniqueStrings(values: Iterable<string>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function uniqueTraceSources(values: Iterable<DispatchTraceSource>): DispatchTraceSource[] {
  const seen = new Set<string>();
  const result: DispatchTraceSource[] = [];
  for (const entry of values) {
    const key = `${entry.label}::${entry.detail}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(entry);
  }
  return result;
}

function dedupeReviewFindings(values: Iterable<ArtifactReviewFinding>): ArtifactReviewFinding[] {
  const seen = new Set<string>();
  const result: ArtifactReviewFinding[] = [];
  for (const value of values) {
    const key = [
      value.message,
      value.filePath ?? "",
      value.lineStart ?? "",
      value.lineEnd ?? "",
      value.acId ?? "",
      value.provider ?? "",
    ].join("|");
    if (!value.message.trim() || seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}

function normalizeReviewFindings(value: unknown): ArtifactReviewFinding[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const findings: ArtifactReviewFinding[] = [];
  value.forEach((item) => {
    if (typeof item === "string" && item.trim()) {
      findings.push({
        message: item.trim(),
        severity: null,
        provider: null,
        filePath: null,
        check: null,
        acId: null,
        criterion: null,
        lineStart: null,
        lineEnd: null,
        confidence: null,
        source: null,
      });
      return;
    }
    const finding = asObject(item);
    if (!finding) return;
    const message = typeof finding.message === "string"
      ? finding.message
      : typeof finding.summary === "string"
        ? finding.summary
        : typeof finding.finding === "string"
          ? finding.finding
          : null;
    if (!message?.trim()) return;
    findings.push({
      message: message.trim(),
      severity: typeof finding.severity === "string" ? finding.severity : null,
      provider: typeof finding.provider === "string" ? finding.provider : null,
      filePath: typeof finding.file_path === "string" ? finding.file_path : null,
      check: typeof finding.check === "string" ? finding.check : null,
      acId: typeof finding.ac_id === "string" ? finding.ac_id : null,
      criterion: typeof finding.criterion === "string" ? finding.criterion : null,
      lineStart: asFiniteNumber(finding.line_start),
      lineEnd: asFiniteNumber(finding.line_end),
      confidence: asFiniteNumber(finding.confidence),
      source: typeof finding.source === "string" ? finding.source : null,
    });
  });
  return dedupeReviewFindings(findings);
}

function readArtifactSnapshot(metadataValue: unknown): ArtifactSnapshot {
  const metadata = asObject(metadataValue) ?? {};
  const artifactIndex = asObject(metadata.artifact_index);
  const responseEvidence = asObject(metadata.response_evidence);
  const filesChanged = artifactIndex
    ? asStringList(artifactIndex.files_changed)
    : asStringList(responseEvidence?.changed_files);
  return {
    filesChanged: uniqueStrings(filesChanged),
    testsRun: uniqueStrings(asStringList(artifactIndex?.tests_run)),
    knownRisks: uniqueStrings(asStringList(artifactIndex?.known_risks)),
    reviewFindings: normalizeReviewFindings(artifactIndex?.review_findings),
  };
}

function readDispatchTraceSources(metadataValue: unknown): DispatchTraceSource[] {
  const metadata = asObject(metadataValue) ?? {};
  const artifactIndex = asObject(metadata.artifact_index);
  const responseEvidence = asObject(metadata.response_evidence);
  const entries: DispatchTraceSource[] = [];

  if (asObject(metadata.context_pack)) {
    entries.push({ label: "Compiled context pack", detail: "context_pack.agent_input + compilation" });
  }
  if (asObject(metadata.agent_output)) {
    entries.push({ label: "Normalized agent output", detail: "agent_output.summary/findings/decisions" });
  }
  if (artifactIndex) {
    entries.push({ label: "Normalized artifact index", detail: "artifact_index.files_changed/tests_run/review_findings" });
  }
  if (responseEvidence) {
    entries.push({
      label: artifactIndex ? "Raw provider evidence retained" : "Compatibility fallback",
      detail: "response_evidence.*",
    });
  }

  return uniqueTraceSources(entries);
}

function readDispatchInspector(dispatch: DispatchRecord): DispatchInspectorModel | null {
  const metadata = asObject(dispatch.metadata) ?? {};
  const contextPack = asObject(metadata.context_pack);
  const agentInput = asObject(contextPack?.agent_input);
  const compilation = asObject(contextPack?.compilation);
  const agentOutput = asObject(metadata.agent_output);
  const artifacts = readArtifactSnapshot(metadata);
  const objective = typeof agentInput?.objective === "string" ? agentInput.objective : null;
  const tokenBudget = asFiniteNumber(agentInput?.token_budget);
  const estimatedTokens = asFiniteNumber(compilation?.estimated_tokens);
  const summary = typeof agentOutput?.summary === "string" ? agentOutput.summary : null;
  const nextAgent = typeof agentOutput?.next_recommended_agent === "string"
    ? agentOutput.next_recommended_agent
    : null;
  const findings = uniqueStrings(asStringList(agentOutput?.findings));
  const decisions = uniqueStrings(asStringList(agentOutput?.decisions));
  const traceSources = readDispatchTraceSources(metadata);

  if (
    !objective &&
    !summary &&
    !nextAgent &&
    findings.length === 0 &&
    decisions.length === 0 &&
    traceSources.length === 0 &&
    artifacts.filesChanged.length === 0 &&
    artifacts.testsRun.length === 0 &&
    artifacts.reviewFindings.length === 0 &&
    artifacts.knownRisks.length === 0
  ) {
    return null;
  }

  return {
    objective,
    tokenBudget,
    estimatedTokens,
    summary,
    nextAgent,
    findings,
    decisions,
    artifacts,
    traceSources,
  };
}

function buildArtifactOverview(
  evidence: EvidenceArtifactRecord[],
  dispatches: DispatchRecord[],
): ArtifactOverviewModel {
  const allFiles: string[] = [];
  const allTests: string[] = [];
  const allRisks: string[] = [];
  const allFindings: ArtifactReviewFinding[] = [];

  evidence.forEach((item) => {
    const snapshot = readArtifactSnapshot(item.metadata);
    allFiles.push(...snapshot.filesChanged);
    allTests.push(...snapshot.testsRun);
    allRisks.push(...snapshot.knownRisks);
    allFindings.push(...snapshot.reviewFindings);
  });

  dispatches.forEach((dispatch) => {
    const snapshot = readArtifactSnapshot(dispatch.metadata);
    allFiles.push(...snapshot.filesChanged);
    allTests.push(...snapshot.testsRun);
    allRisks.push(...snapshot.knownRisks);
    allFindings.push(...snapshot.reviewFindings);
  });

  return {
    filesChanged: uniqueStrings(allFiles),
    testsRun: uniqueStrings(allTests),
    knownRisks: uniqueStrings(allRisks),
    reviewFindings: dedupeReviewFindings(allFindings),
    dispatchCount: dispatches.length,
    evidenceCount: evidence.length,
    reviewEvidenceCount: evidence.filter((item) => item.artifact_type === "review").length,
    testEvidenceCount: evidence.filter(
      (item) => item.artifact_type === "test" || String(item.metadata.subtask_id ?? "").includes("test"),
    ).length,
  };
}

function readCompletionContext(handoff: HandoffRecord | null | undefined): CompletionContextModel | null {
  const metadata = asObject(handoff?.metadata);
  const context = asObject(metadata?.normalized_completion_context);
  if (!context) return null;
  return {
    filesChanged: uniqueStrings(asStringList(context.files_changed)),
    testsRun: uniqueStrings(asStringList(context.tests_run)),
    findings: uniqueStrings(asStringList(context.findings)),
    risks: uniqueStrings(asStringList(context.risks)),
    summaries: uniqueStrings(asStringList(context.summaries)),
    decisions: uniqueStrings(asStringList(context.decisions)),
  };
}

function formatTokenBudget(estimatedTokens: number | null, tokenBudget: number | null): string | null {
  if (estimatedTokens === null && tokenBudget === null) return null;
  if (estimatedTokens !== null && tokenBudget !== null) return `${estimatedTokens}/${tokenBudget} tokens`;
  if (tokenBudget !== null) return `${tokenBudget} token budget`;
  return `${estimatedTokens} estimated tokens`;
}

function formatFindingMeta(finding: ArtifactReviewFinding): string | null {
  const parts: string[] = [];
  if (finding.filePath) {
    const lineSuffix = finding.lineStart !== null
      ? `:${finding.lineStart}${finding.lineEnd !== null && finding.lineEnd !== finding.lineStart ? `-${finding.lineEnd}` : ""}`
      : "";
    parts.push(`${finding.filePath}${lineSuffix}`);
  }
  if (finding.check) parts.push(finding.check);
  if (finding.acId) parts.push(finding.acId);
  if (finding.provider) parts.push(finding.provider);
  return parts.length ? parts.join(" · ") : null;
}

function ArtifactStatCard({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="artifact-stat-card">
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{note}</span>
    </div>
  );
}

function ArtifactStringSection({
  title,
  items,
  tone = "default",
  emptyLabel,
}: {
  title: string;
  items: string[];
  tone?: Tone | string;
  emptyLabel?: string;
}) {
  if (items.length === 0 && !emptyLabel) return null;
  return (
    <section className="artifact-section">
      <div className="panel-title artifact-section-title">
        <h3 style={{ fontSize: "0.8rem" }}>{title}</h3>
        <Pill tone={tone}>{items.length}</Pill>
      </div>
      {items.length > 0 ? (
        <div className="artifact-list">
          {items.map((item) => (
            <div className="artifact-list-item" key={`${title}-${item}`}>
              <span>{item}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="artifact-empty">{emptyLabel}</div>
      )}
    </section>
  );
}

function ArtifactFindingSection({ findings }: { findings: ArtifactReviewFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <section className="artifact-section">
      <div className="panel-title artifact-section-title">
        <h3 style={{ fontSize: "0.8rem" }}>Review findings</h3>
        <Pill tone="warning">{findings.length}</Pill>
      </div>
      <div className="artifact-list">
        {findings.map((finding, index) => {
          const meta = formatFindingMeta(finding);
          return (
            <div className="artifact-list-item artifact-list-item-detail" key={`${finding.message}-${index}`}>
              <div>
                <strong>{finding.message}</strong>
                {meta ? <small>{meta}</small> : null}
              </div>
              <div className="artifact-pill-row">
                {finding.severity ? <Pill tone={stateTone(finding.severity)}>{finding.severity}</Pill> : null}
                {finding.confidence !== null ? <Pill tone="default">{Math.round(finding.confidence * 100)}%</Pill> : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DispatchInspector({ dispatch }: { dispatch: DispatchRecord }) {
  const inspector = readDispatchInspector(dispatch);
  if (!inspector) return null;

  const tokenLabel = formatTokenBudget(inspector.estimatedTokens, inspector.tokenBudget);
  return (
    <div className="dispatch-inspector">
      <div className="dispatch-inspector-header">
        <div className="dispatch-inspector-copy">
          {inspector.objective ? <p className="dispatch-inspector-objective">{inspector.objective}</p> : null}
          {inspector.summary ? <p className="dispatch-inspector-summary">{inspector.summary}</p> : null}
        </div>
        {tokenLabel ? <span className="dispatch-token-badge">{tokenLabel}</span> : null}
      </div>
      <div className="artifact-pill-row">
        {inspector.artifacts.filesChanged.length > 0 ? <Pill tone="draft">{inspector.artifacts.filesChanged.length} files</Pill> : null}
        {inspector.artifacts.testsRun.length > 0 ? <Pill tone="draft">{inspector.artifacts.testsRun.length} tests</Pill> : null}
        {inspector.artifacts.reviewFindings.length > 0 ? <Pill tone="warning">{inspector.artifacts.reviewFindings.length} findings</Pill> : null}
        {inspector.artifacts.knownRisks.length > 0 ? <Pill tone="warning">{inspector.artifacts.knownRisks.length} risks</Pill> : null}
      </div>
      {inspector.nextAgent || inspector.decisions.length > 0 || inspector.findings.length > 0 ? (
        <div className="dispatch-inspector-detail">
          {inspector.nextAgent ? (
            <small>
              Next recommended agent: <strong>{inspector.nextAgent}</strong>
            </small>
          ) : null}
          {inspector.decisions.length > 0 ? (
            <small>Decisions: {inspector.decisions.slice(0, 3).join(" · ")}</small>
          ) : null}
          {inspector.findings[0] ? (
            <small>Signal: {inspector.findings[0]}</small>
          ) : null}
        </div>
      ) : null}
      {inspector.traceSources.length > 0 ? (
        <div className="dispatch-inspector-detail">
          <small>Trace sources: {inspector.traceSources.map((entry) => entry.label).join(" · ")}</small>
        </div>
      ) : null}
      {inspector.artifacts.reviewFindings.length > 0 ? (
        <div className="dispatch-preview-list">
          {inspector.artifacts.reviewFindings.slice(0, 2).map((finding, index) => (
            <div className="dispatch-preview-row" key={`${dispatch.id}-finding-${index}`}>
              <strong>{finding.message}</strong>
              {formatFindingMeta(finding) ? <small>{formatFindingMeta(finding)}</small> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TaskTabPanel({
  tab,
  taskId,
  messages: taskMessages,
  events: taskEvents,
  dispatches,
  evidence: taskEvidence,
  reviews: taskReviews,
  handoff,
  onMessageSent,
  onReviewRun,
  onHandoffChange,
}: {
  tab: TaskTab;
  taskId?: string;
  messages?: MessageRecord[];
  events?: LifecycleEventRecord[];
  dispatches?: DispatchRecord[];
  evidence?: EvidenceArtifactRecord[];
  reviews?: ReviewRunRecord[];
  handoff?: HandoffRecord | null;
  onMessageSent?: () => Promise<void>;
  onReviewRun?: () => Promise<void>;
  onHandoffChange?: () => Promise<void>;
}) {
  const [messageSearch, setMessageSearch] = useState("");
  const [draftMessage, setDraftMessage] = useState("");
  const [messageTarget, setMessageTarget] = useState("Current task agents");
  const [sendStatus, setSendStatus] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [handoffStatus, setHandoffStatus] = useState("");

  if (tab === "messages") {
    if (taskMessages) {
      const visibleMessages = taskMessages.filter((message) => {
        const haystack = `${message.role} ${message.content} ${JSON.stringify(message.metadata)}`.toLowerCase();
        return haystack.includes(messageSearch.toLowerCase());
      });
      async function submitMessage(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!taskId || !draftMessage.trim()) return;
        try {
          setSendStatus("Sending message to Sutra.");
          await sendTaskMessage(taskId, draftMessage.trim(), messageTarget);
          setDraftMessage("");
          setSendStatus("Message persisted.");
          await onMessageSent?.();
        } catch (error) {
          setSendStatus(error instanceof Error ? error.message : "Message send failed.");
        }
      }
      return (
        <>
          <div className="message-tools">
            <input
              aria-label="Search task messages"
              placeholder="Search task messages..."
              value={messageSearch}
              onChange={(event) => setMessageSearch(event.target.value)}
            />
          </div>
          {visibleMessages.length > 0 ? (
            visibleMessages.map((message) => (
              <MessageBubble
                key={message.id}
                from={formatRole(message.role)}
                target={String(message.metadata.target ?? "Current task agents")}
                tag={String(message.metadata.gate ?? message.metadata.source ?? "Task")}
                text={message.content}
                impact={message.created_at}
              />
            ))
          ) : (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
              <p>{messageSearch ? "No messages match your search." : "No messages yet."}</p>
              <small>Send a message to start the conversation.</small>
            </div>
          )}
          <form className="composer" onSubmit={submitMessage}>
            <select value={messageTarget} onChange={(event) => setMessageTarget(event.target.value)}>
              <option>Current task agents</option>
              <option>Sarathi</option>
              <option>Disha</option>
              <option>Pravaha</option>
              <option>Nirnaya</option>
            </select>
            <input
              placeholder="Send a message to this task..."
              value={draftMessage}
              onChange={(event) => setDraftMessage(event.target.value)}
            />
            <button disabled={!draftMessage.trim() || !taskId}>Send</button>
          </form>
          {sendStatus ? <small>{sendStatus}</small> : null}
        </>
      );
    }
    return <>{messages.map((message) => <MessageBubble key={`${message.from}-${message.tag}`} {...message} />)}</>;
  }
  if (tab === "evidence") {
    if (taskEvidence) {
      const artifactOverview = buildArtifactOverview(taskEvidence, dispatches ?? []);
      const dispatchInspectors = (dispatches ?? [])
        .map((dispatch) => ({ dispatch, inspector: readDispatchInspector(dispatch) }))
        .filter((item): item is { dispatch: DispatchRecord; inspector: DispatchInspectorModel } => item.inspector !== null);
      const testEv = taskEvidence.filter(
        (item) => item.artifact_type === "test" || String(item.metadata.subtask_id ?? "").includes("test"),
      );
      const reviewEv = taskEvidence.filter((item) => item.artifact_type === "review");
      return (
        <>
          <section className="artifact-section">
            <div className="panel-title artifact-section-title">
              <h3 style={{ fontSize: "0.82rem" }}>Artifact overview</h3>
              <Pill tone="default">{artifactOverview.evidenceCount} records</Pill>
            </div>
            <div className="artifact-summary-grid">
              <ArtifactStatCard
                label="Changed files"
                value={String(artifactOverview.filesChanged.length)}
                note="Normalized from artifact index first."
              />
              <ArtifactStatCard
                label="Tests run"
                value={String(artifactOverview.testsRun.length)}
                note={`${artifactOverview.testEvidenceCount} captured test artifact${artifactOverview.testEvidenceCount === 1 ? "" : "s"}.`}
              />
              <ArtifactStatCard
                label="Review findings"
                value={String(artifactOverview.reviewFindings.length)}
                note={`${artifactOverview.reviewEvidenceCount} review artifact${artifactOverview.reviewEvidenceCount === 1 ? "" : "s"}.`}
              />
              <ArtifactStatCard
                label="Known risks"
                value={String(artifactOverview.knownRisks.length)}
                note={`${artifactOverview.dispatchCount} dispatch${artifactOverview.dispatchCount === 1 ? "" : "es"} inspected.`}
              />
            </div>
          </section>
          <ArtifactStringSection
            title="Changed files"
            items={artifactOverview.filesChanged}
            tone="active"
            emptyLabel="No normalized changed-file list is attached yet."
          />
          <ArtifactStringSection
            title="Tests run"
            items={artifactOverview.testsRun}
            tone="healthy"
          />
          <ArtifactFindingSection findings={artifactOverview.reviewFindings} />
          <ArtifactStringSection
            title="Known risks"
            items={artifactOverview.knownRisks}
            tone="warning"
          />
          {dispatchInspectors.length > 0 && (
            <section className="artifact-section">
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>Dispatch inspectors</h3>
                <Pill tone="default">{dispatchInspectors.length}</Pill>
              </div>
              <div className="artifact-card-stack">
                {dispatchInspectors.map(({ dispatch }) => (
                  <Card key={dispatch.id} style={{ display: "grid", gap: 10 }}>
                    <div className="dispatch-card-header">
                      <div>
                        <strong>Dispatch {dispatch.id.slice(0, 8)}</strong>
                        <small>{dispatch.agent_name} · {dispatch.created_at?.slice(0, 19)}</small>
                      </div>
                      <Pill tone={stateTone(dispatch.status)}>{dispatch.status}</Pill>
                    </div>
                    <DispatchInspector dispatch={dispatch} />
                  </Card>
                ))}
              </div>
            </section>
          )}
          {(testEv.length > 0 || reviewEv.length > 0) && (
            <section className="artifact-section">
              <div className="panel-title artifact-section-title">
                <h3 style={{ fontSize: "0.8rem" }}>Captured evidence records</h3>
                <Pill tone="default">{testEv.length + reviewEv.length}</Pill>
              </div>
              <div className="artifact-card-stack">
                {testEv.map((item) => (
                  <Card key={item.id}>
                    <strong>Test artifact {item.id.slice(0, 8)}</strong>
                    <p>{item.uri}</p>
                    <small>{item.created_at?.slice(0, 19)}</small>
                  </Card>
                ))}
                {reviewEv.map((item) => (
                  <Card key={item.id}>
                    <strong>Review artifact {item.id.slice(0, 8)}</strong>
                    <p>{item.uri}</p>
                    <small>{String(item.metadata.provider ?? "provider")} · {item.created_at?.slice(0, 19)}</small>
                  </Card>
                ))}
              </div>
            </section>
          )}
        </>
      );
    }
    return (
      <>
        {evidence.map((item) => (
          <Card key={item.id}>
            <strong>{item.id} - {item.title}</strong>
            <Pill tone={stateTone(item.state)}>{item.state}</Pill>
            <p>{item.source} / {item.linkedUnit} / {item.linkedGate} / {item.linkedEvent}</p>
          </Card>
        ))}
      </>
    );
  }
  if (tab === "review") {
    if (taskReviews) {
      async function submitReview(reviewType: string) {
        if (!taskId) return;
        try {
          setReviewStatus(`Nirnaya is running ${reviewType} review.`);
          const result = await runTaskReview(taskId, reviewType);
          setReviewStatus(
            `${result.review.status}: ${result.completed_subtasks.length} completed, ${result.requeued_subtasks.length} requeued.`,
          );
          await onReviewRun?.();
        } catch (error) {
          setReviewStatus(error instanceof Error ? error.message : "Review run failed.");
        }
      }
      return (
        <>
          <section style={{ marginBottom: 16 }}>
            <div className="panel-title" style={{ paddingBottom: 8 }}>
              <h3 style={{ fontSize: "0.85rem" }}>Run review</h3>
            </div>
            <div className="actions" style={{ gap: 8 }}>
              <button disabled={!taskId} onClick={() => void submitReview("code")}>
                Run code review
              </button>
              <button disabled={!taskId} onClick={() => void submitReview("functional")}>
                Run functional review
              </button>
            </div>
            {reviewStatus ? <small style={{ display: "block", marginTop: 8 }}>{reviewStatus}</small> : null}
          </section>
          {taskReviews.length > 0 && (
            <section>
              <div className="panel-title" style={{ paddingBottom: 8 }}>
                <h3 style={{ fontSize: "0.85rem" }}>Review results</h3>
                <Pill tone="default">{taskReviews.length}</Pill>
              </div>
              {taskReviews.map((review) => {
                const diffSummary = review.metadata.diff_summary as Record<string, unknown> | undefined;
                const confidence = diffSummary?.review_confidence_verdict;
                const reasons = diffSummary?.review_confidence_reasons as string[] | undefined;
                const blockers = diffSummary?.provider_diff_blockers as number | undefined;
                return (
                  <Card key={review.id} style={{ marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                      <strong>{String(review.metadata.review_type ?? "review")}</strong>
                      <Pill tone={stateTone(review.status)}>{review.status}</Pill>
                    </div>
                    <p style={{ marginBottom: 8 }}>{review.summary ?? "No summary recorded."}</p>
                    <small style={{ color: "var(--muted)", display: "block", marginBottom: 8 }}>
                      {review.created_at?.slice(0, 19)}
                    </small>
                    {typeof confidence === "string" && (
                      <div style={{ paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                        <div className="panel-title">
                          <h4 style={{ fontSize: "0.75rem" }}>Confidence</h4>
                        </div>
                        <Pill tone={confidence === "high" ? "healthy" : confidence === "medium" ? "warning" : "blocked"}>
                          {confidence}
                        </Pill>
                        {Array.isArray(reasons) && reasons.length > 0 && (
                          <div className="mini-list" style={{ marginTop: 6 }}>
                            {reasons.map((r, i) => <span key={i}>{r}</span>)}
                          </div>
                        )}
                      </div>
                    )}
                    {typeof blockers === "number" && blockers > 0 && (
                      <div style={{ marginTop: 8, padding: "6px 10px", background: "var(--red-a2)", borderRadius: 4, fontSize: "0.78rem" }}>
                        ⚠️ {blockers} blocker(s) found
                      </div>
                    )}
                  </Card>
                );
              })}
            </section>
          )}
        </>
      );
    }
    return <>{reviews.map((review) => <Card key={review.id}><strong>{review.id} - {review.type}</strong><Pill tone={stateTone(review.verdict)}>{review.verdict}</Pill><p>{review.reviewer}: {review.finding}</p><small>{review.loop} / {review.linkedUnit} / {review.linkedGate}</small></Card>)}</>;
  }
  if (tab === "history") {
    if (taskEvents) {
      return (
        <div className="timeline">
          {taskEvents.map((event) => {
            const payload = event.payload as Record<string, unknown>;
            const summary = payload?.summary ?? payload?.message ?? payload?.action ?? JSON.stringify(payload).slice(0, 100);
            return (
              <div className="timeline-item" key={event.id}>
                <span className="timeline-time">{event.created_at?.slice(11, 19) ?? "—"}</span>
                <span className={`timeline-dot ${payload?.severity ?? "info"}`} />
                <div className="timeline-content">
                  <span className="timeline-title">{event.event_type}</span>
                  <span className="timeline-meta">{String(summary)}</span>
                </div>
              </div>
            );
          })}
        </div>
      );
    }
    return <History compact />;
  }
  async function submitHandoff() {
    if (!taskId) return;
    try {
      setHandoffStatus("Samanvaya is preparing the final handoff dossier.");
      await createTaskHandoff(taskId);
      setHandoffStatus("Handoff created. Repository action now requires approval.");
      await onHandoffChange?.();
    } catch (error) {
      setHandoffStatus(error instanceof Error ? error.message : "Handoff creation failed.");
    }
  }
  async function submitRepositoryAction(action: string) {
    if (!taskId) return;
    try {
      setHandoffStatus(`Requesting approval for repository action: ${action}.`);
      await approveRepositoryAction(taskId, action);
      setHandoffStatus(`Repository action approved: ${action}. Main task is ready for user review.`);
      await onHandoffChange?.();
    } catch (error) {
      setHandoffStatus(error instanceof Error ? error.message : "Repository action approval failed.");
    }
  }
  const repositoryAction = handoff?.metadata.repository_action as
    | { status?: string; action?: string; note?: string | null }
    | undefined;
  const repositoryActionPreference = handoff?.metadata.repository_action_preference as
    | { scope?: string; mode?: string; allowed_modes?: string[] }
    | undefined;
  const acCoverage = handoff?.metadata.ac_coverage as
    | Array<{ id?: string; criterion?: string; covered?: boolean }>
    | undefined;
  const normalizedCompletionContext = readCompletionContext(handoff);
  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <button disabled={!taskId} onClick={() => void submitHandoff()}>Create final handoff</button>
        {handoffStatus ? <small>{handoffStatus}</small> : null}
      </div>
      {handoff ? (
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <strong>Final handoff dossier</strong>
            <Pill tone={repositoryAction?.status === "approved" ? "healthy" : "warning"}>
              Repository action {repositoryAction?.status ?? "pending"}
            </Pill>
          </div>
          <p style={{ marginBottom: 8 }}>{handoff.summary}</p>
          <small style={{ color: "var(--muted)" }}>{handoff.from_agent ?? "Samanvaya"} to {handoff.to_agent ?? "User"} / {handoff.created_at?.slice(0, 19)}</small>
          {acCoverage?.length ? (
            <section style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>AC Coverage</h3>
                <Pill tone={acCoverage.every(a => a.covered) ? "healthy" : "warning"}>
                  {acCoverage.filter(a => a.covered).length}/{acCoverage.length} covered
                </Pill>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {acCoverage.map((item, index) => (
                  <label key={`${handoff.id}-ac-${index}`} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.83rem" }}>
                    <input type="checkbox" checked={item.covered} readOnly style={{ width: 14, height: 14 }} />
                    <span style={{ color: item.covered ? "var(--green-11)" : "var(--red-11)", fontWeight: 500 }}>
                      {item.covered ? "✓" : "✗"}
                    </span>
                    <span style={{ color: "var(--muted)" }}>{item.id ?? `AC-${index + 1}`}</span>
                    <span style={{ flex: 1 }}>{item.criterion}</span>
                  </label>
                ))}
              </div>
            </section>
          ) : null}
          {normalizedCompletionContext && (
            <section className="artifact-section artifact-section-inset">
              <div className="panel-title artifact-section-title">
                <h3 style={{ fontSize: "0.8rem" }}>Completion context</h3>
                <Pill tone="default">normalized</Pill>
              </div>
              <div className="artifact-summary-grid">
                <ArtifactStatCard
                  label="Files"
                  value={String(normalizedCompletionContext.filesChanged.length)}
                  note="Completion-ready file scope."
                />
                <ArtifactStatCard
                  label="Tests"
                  value={String(normalizedCompletionContext.testsRun.length)}
                  note="Recorded verification traces."
                />
                <ArtifactStatCard
                  label="Findings"
                  value={String(normalizedCompletionContext.findings.length)}
                  note="Signals handed to the reviewer."
                />
                <ArtifactStatCard
                  label="Decisions"
                  value={String(normalizedCompletionContext.decisions.length)}
                  note="Recent orchestration decisions."
                />
              </div>
              <ArtifactStringSection title="Completion summaries" items={normalizedCompletionContext.summaries} tone="default" />
              <ArtifactStringSection title="Decision trace" items={normalizedCompletionContext.decisions} tone="default" />
              <ArtifactStringSection title="Files changed" items={normalizedCompletionContext.filesChanged} tone="active" />
              <ArtifactStringSection title="Tests run" items={normalizedCompletionContext.testsRun} tone="healthy" />
              <ArtifactStringSection title="Known risks" items={normalizedCompletionContext.risks} tone="warning" />
              <ArtifactStringSection title="Reviewer signals" items={normalizedCompletionContext.findings} tone="warning" />
            </section>
          )}
        </Card>
      ) : (
        <Card>
          <strong>Handoff not created yet</strong>
          <Pill tone="warning">review gate required</Pill>
          <p>Run the final review loop first, then create a handoff so the user gets AC coverage, evidence, and repository-action choices in one place.</p>
        </Card>
      )}
      <section style={{ marginTop: 16 }}>
        <div className="panel-title" style={{ paddingBottom: 8 }}>
          <h3 style={{ fontSize: "0.85rem" }}>Repository action</h3>
          <Pill tone="default">after handoff approval</Pill>
        </div>
        <p style={{ marginBottom: 12, fontSize: "0.83rem", color: "var(--muted)" }}>
          Choose the safest next action for this task before Sarathi touches Git.
        </p>
        <p style={{ marginBottom: 12, fontSize: "0.8rem", color: "var(--muted)" }}>
          Default posture: <strong>{repositoryActionPreference?.mode?.replace(/_/g, " ") ?? "no action"}</strong>. Commit and PR remain off until you opt in from Settings.
        </p>
        <div className="actions" style={{ gap: 8 }}>
          {[
            { id: "no_action", label: "No action", tone: "default" },
            { id: "prepare_patch", label: "Prepare patch", tone: "warning" },
            { id: "commit", label: "Commit (opt-in)", tone: "active" },
            { id: "draft_pr", label: "Draft PR (opt-in)", tone: "healthy" },
            { id: "ready_pr", label: "Ready PR (opt-in)", tone: "healthy" },
          ].map((action) => (
            <button
              disabled={!taskId || !handoff || repositoryAction?.status === "approved"}
              key={action.id}
              onClick={() => void submitRepositoryAction(action.id)}
              className={repositoryAction?.action === action.id ? "primary" : ""}
              style={{ minWidth: 100 }}
            >
              {action.label}
            </button>
          ))}
        </div>
        {repositoryAction?.action ? (
          <small style={{ display: "block", marginTop: 8, color: "var(--muted)" }}>
            Selected: <strong>{repositoryAction.action.replace(/_/g, " ")}</strong>
          </small>
        ) : null}
      </section>
    </>
  );
}

const PHASE_ROLE_MAP: Record<string, string> = {
  Route: "Marga",
  Brainstorm: "Vichara",
  PlanningAdvisor: "Disha",
  Plan: "Disha",
  Build: "Pravaha",
  Verify: "Nirnaya",
  Review: "Nirnaya",
  TaskTracking: "Samanvaya",
  RiskCheck: "Prajna",
  Elegance: "Sahayaka",
  PhaseLog: "Sutra",
  Learn: "Prajna",
};

function Agents({ liveTick }: { liveTick: number }) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [providerHealth, setProviderHealth] = useState<ProviderHealthRecord[]>([]);
  const [providerStatus, setProviderStatus] = useState(
    apiConfigured ? "Loading provider health from local service." : "Demo provider lane.",
  );
  const [searchFilter, setSearchFilter] = useState("");

  const filteredRoles = roles.filter((r) =>
    !searchFilter ||
    r.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
    r.function.toLowerCase().includes(searchFilter.toLowerCase()),
  );

  const activeCount = roles.filter((r) => r.state === "active" || r.state === "live").length;
  const idleCount = roles.filter((r) => r.state === "idle").length;
  const waitingCount = roles.filter((r) => r.state === "waiting" || r.state === "queued").length;

  const agentStats = [
    { label: "Total Agents", value: String(roles.length) },
    { label: "Active", value: String(activeCount) },
    { label: "Idle", value: String(idleCount) },
    { label: "Waiting", value: String(waitingCount) },
    { label: "Providers", value: String(providers.length) },
  ];

  useEffect(() => {
    if (!apiConfigured) {
      return;
    }
    let cancelled = false;
    async function loadProviderHealth() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const nextProviders = await listProviders(selectedWorkspace.id);
        if (!cancelled) {
          setProviderHealth(nextProviders);
          setProviderStatus(`${nextProviders.length} provider health records loaded.`);
        }
      } catch (error) {
        if (!cancelled) {
          setProviderStatus(error instanceof Error ? error.message : "Provider health load failed.");
        }
      }
    }
    void loadProviderHealth();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, liveTick]);

  const displayProviders = providerHealth.length ? providerHealth : providers;

  return (
    <div>
      {/* Agent stats bar */}
      <div className="agent-stats-bar">
        {agentStats.map((stat) => (
          <div className="agent-stat-item" key={stat.label}>
            <span className="agent-stat-value">{stat.value}</span>
            <span className="agent-stat-label">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* Primary: Sanskrit agent roster */}
      <section className="panel" style={{ padding: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2 style={{ fontSize: "0.9rem" }}>Sarathi Agents</h2>
            <Pill tone="default">{roles.length} roles</Pill>
          </div>
          <input
            style={{ height: 28, padding: "0 8px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--hover)", fontSize: "0.8rem" }}
            placeholder="Search agents..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
          />
        </div>
        <div style={{ overflow: "auto" }}>
          <table className="role-table">
            <thead>
              <tr><th>Agent</th><th>Sanskrit name</th><th>Function</th><th>Lifecycle phases</th><th>Status</th><th>Provider</th></tr>
            </thead>
            <tbody>
              {filteredRoles.map((role) => {
                const phases = Object.entries(PHASE_ROLE_MAP)
                  .filter(([, r]) => r === role.name)
                  .map(([phase]) => phase);
                return (
                  <tr key={role.name}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span className="member-avatar" style={{ background: "var(--indigo-3)", color: "var(--indigo-11)" }}>
                          {role.name.slice(0, 2)}
                        </span>
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.83rem" }}>{role.name}</div>
                          <div style={{ fontSize: "0.71rem", color: "var(--muted)" }}>{role.function}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ fontSize: "0.78rem", color: "var(--muted)", fontStyle: "italic" }}>{role.name}</td>
                    <td style={{ fontSize: "0.78rem" }}>{role.function}</td>
                    <td style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                      {phases.length ? phases.join(", ") : <span style={{ opacity: 0.4 }}>—</span>}
                    </td>
                    <td><Pill tone={stateTone(role.state)}>{role.state}</Pill></td>
                    <td style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{role.provider}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Providers */}
      <section className="panel" style={{ marginTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
          <h2 style={{ fontSize: "0.9rem" }}>Providers</h2>
          <Pill tone={apiConfigured ? "healthy" : "default"}>{apiConfigured ? "live" : "demo"} · {providerStatus}</Pill>
        </div>
        <table className="role-table">
          <thead><tr><th>Name</th><th>Type</th><th>Health</th><th>Auth</th><th>Capabilities</th></tr></thead>
          <tbody>
            {displayProviders.map((provider) => (
              <tr key={provider.id}>
                <td className="role-name">{provider.name}</td>
                <td className="role-desc">{"provider_type" in provider ? provider.provider_type : (provider as { type?: string }).type}</td>
                <td><Pill tone={stateTone(provider.health)}>{provider.health}</Pill></td>
                <td><Pill tone={provider.auth === "connected" || provider.auth === "not required" ? "healthy" : "blocked"}>{provider.auth}</Pill></td>
                <td style={{ color: "var(--muted)", fontSize: "0.75rem" }}>{provider.capabilities.slice(0, 3).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Lifecycle({ liveTick }: { liveTick: number }) {
  const { snapshot, status } = useWorkspaceOperationalViews(liveTick);
  const lifecycleRoles = snapshot?.lifecycle ?? roles.map((role) => ({
    key: role.name.toLowerCase(),
    name: role.name,
    purpose: role.function.toLowerCase(),
    description: role.function,
    state: role.state,
    event_count: 0,
  }));
  return (
    <section className="panel">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: "0.9rem" }}>Agent lifecycle</h2>
        <Pill tone={snapshot ? "healthy" : "default"}>{snapshot ? "SQLite" : `${lifecycleRoles.length} roles`}</Pill>
      </div>
      <table className="role-table">
        <thead>
          <tr><th>#</th><th>Role</th><th>Name</th><th>Status</th><th>Signals</th></tr>
        </thead>
        <tbody>
          {lifecycleRoles.map((role, index) => (
            <tr key={role.name}>
              <td className="step-num">{String(index + 1).padStart(2, "0")}</td>
              <td style={{ color: "var(--muted)", fontSize: "0.78rem", textTransform: "capitalize" }}>{role.purpose}</td>
              <td className="role-name">{role.name}</td>
              <td><Pill tone={stateTone(role.state)}>{role.state}</Pill></td>
              <td style={{ color: "var(--faint)", fontFamily: "monospace", fontSize: "0.75rem" }}>{role.event_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function History({ compact = false, liveTick = 0 }: { compact?: boolean; liveTick?: number }) {
  const { snapshot, status } = useWorkspaceOperationalViews(liveTick);
  const liveEvents = snapshot?.history;
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [searchText, setSearchText] = useState("");

  const allCategories = ["All", "Workflow", "Security", "Settings", "Lifecycle", "Billing"];

  const filteredLiveEvents = liveEvents?.filter((event) => {
    const search = searchText.toLowerCase();
    const matchesCat = categoryFilter === "All" || event.event_type.toLowerCase().includes(categoryFilter.toLowerCase());
    const matchesSearch = !search ||
      event.event_type.toLowerCase().includes(search) ||
      String(event.payload?.message ?? event.payload?.action ?? "").toLowerCase().includes(search);
    return matchesCat && matchesSearch;
  });

  const filteredDemoEvents = events.filter((event) => {
    const search = searchText.toLowerCase();
    const matchesCat = categoryFilter === "All" || event.event.toLowerCase().includes(categoryFilter.toLowerCase());
    const matchesSearch = !search ||
      event.event.toLowerCase().includes(search) ||
      event.source?.toLowerCase().includes(search);
    return matchesCat && matchesSearch;
  });

  return (
    <section className={compact ? "" : "panel"}>
      {!compact && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
          <h2 style={{ fontSize: "0.9rem" }}>Audit trail</h2>
          <Pill tone={liveEvents ? "healthy" : "default"}>{liveEvents ? "SQLite" : "demo"}</Pill>
        </div>
      )}
      {!compact && (
        <div className="activity-category-tabs">
          {allCategories.map((cat) => (
            <button
              key={cat}
              className={categoryFilter === cat ? "active" : ""}
              onClick={() => setCategoryFilter(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
      )}
      {!compact && (
        <div style={{ marginBottom: 12 }}>
          <input
            style={{ width: "100%", height: 32, padding: "0 10px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--hover)", fontSize: "0.83rem" }}
            placeholder="Search events..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </div>
      )}
      <div className="timeline">
        {liveEvents ? filteredLiveEvents?.map((event) => {
          const payload = event.payload as Record<string, unknown>;
          const title = event.event_type;
          const summary = String(payload?.message ?? payload?.action ?? payload?.summary ?? "");
          const time = event.created_at?.slice(11, 19) ?? "—";
          const source = event.task_id ?? "workspace";
          const severity = String(payload?.severity ?? "info");
          return (
            <div className="timeline-item" key={event.id}>
              <span className="timeline-time">{time}{source !== "workspace" ? ` · ${source}` : ""}</span>
              <span className={`timeline-dot ${severity}`} />
              <div className="timeline-content">
                <span className="timeline-title">{title}</span>
                <span className="timeline-meta">{summary}</span>
              </div>
            </div>
          );
        }) : filteredDemoEvents.map((event) => (
          <div className="timeline-item" key={event.id}>
            <span className="timeline-time">{event.time} · {event.source}</span>
            <span className={`timeline-dot ${event.severity}`} />
            <div className="timeline-content">
              <span className="timeline-title">{event.event}</span>
              <span className="timeline-meta"><Pill tone={stateTone(event.severity)}>{event.object}</Pill></span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Diagrams({ liveTick, setRoute }: { liveTick: number; setRoute: (route: AppRoute) => void }) {
  const { snapshot, status } = useWorkspaceOperationalViews(liveTick);
  const liveDiagrams = snapshot?.diagrams;
  return (
    <section className="panel">
      <PanelTitle title="Diagram artifacts" badge={liveDiagrams ? "SQLite generated" : "generated"} />
      <p>{status}</p>
      <div className="grid two">
        {liveDiagrams ? liveDiagrams.map((diagram) => (
          <Card key={diagram.id}>
            <strong>{diagram.title}</strong>
            <Pill tone="active">{diagram.kind}</Pill>
            <p>{diagram.summary ?? `${diagram.nodes?.length ?? 0} nodes / ${diagram.edges?.length ?? 0} edges`}</p>
            {diagram.repository_action ? (
              <small>Repository action: {String(diagram.repository_action.action ?? diagram.repository_action.status ?? "pending")}</small>
            ) : (
              <small>{diagram.task_id ?? diagram.updated_at ?? "workspace artifact"}</small>
            )}
            <button onClick={() => setRoute(diagram.kind === "agent_lifecycle" ? "workspace" : "project")}>
              Open {diagram.kind === "agent_lifecycle" ? "Lifecycle" : "Task Studio"}
            </button>
          </Card>
        )) : (
          <>
            <Card><strong>Dependency graph</strong><p>Task graph artifact generated from real subtask state.</p><button onClick={() => setRoute("project")}>Open Task Studio</button></Card>
            <Card><strong>Agent lifecycle</strong><p>Role flow, review loop, and handoff state.</p><button onClick={() => setRoute("workspace")}>Open Lifecycle</button></Card>
          </>
        )}
      </div>
    </section>
  );
}

function Usage({ liveTick }: { liveTick: number }) {
  const { snapshot, status } = useWorkspaceOperationalViews(liveTick);
  const {
    acceptance,
    status: acceptanceStatus,
    approveLearning,
  } = useDogfoodAcceptance(liveTick);
  const usage = snapshot?.usage;
  const budget = usage?.budget ?? null;
  return (
    <>
      <section className="panel">
        <PanelTitle title="Usage statistics" badge={usage ? "SQLite source" : "demo"} />
        <p>{status}</p>
      </section>
      <div className="grid four">
        <Metric label="Tasks complete" value={String(usage?.tasks.done ?? 1)} note={`${usage?.tasks.total ?? 1} total tasks`} />
        <Metric label="Units active" value={String(usage?.subtasks.by_status.in_progress ?? 4)} note={`${usage?.subtasks.total ?? 4} graph units`} />
        <Metric
          label="Token budget"
          value={budget ? (budget.budget_limit != null ? `${formatTokenCount(budget.total_tokens)} / ${formatTokenCount(budget.budget_limit)}` : formatTokenCount(budget.total_tokens)) : "n/a"}
          note={budget ? `${budget.budget_state} · ${budget.usage_source}` : "no usage data yet"}
        />
        <Metric label="Reviews" value={String(usage?.reviews.total ?? 1)} note={`${usage?.evidence.total ?? 0} evidence artifacts`} />
        <Metric label="Provider health" value={`${usage?.providers.online ?? 2}/${usage?.providers.total ?? 4}`} note="online" />
        <Metric label="Events" value={String(usage?.events.total ?? events.length)} note="persisted lifecycle signals" />
        <Metric label="Messages" value={String(usage?.messages.total ?? messages.length)} note="workspace conversation" />
        <Metric label="Handoffs" value={String(usage?.handoffs.total ?? 0)} note="final dossiers" />
        <Metric label="Repositories" value={String(usage?.repositories.total ?? workspace.repos.length)} note="linked repos" />
      </div>
      <section className="panel">
        <PanelTitle
          title="Built with Sarathi"
          badge={acceptance ? acceptance.status : "dogfood"}
        />
        <p>{acceptance?.release_dossier.summary ?? acceptanceStatus}</p>
        {acceptance ? (
          <>
            <div className="grid three">
              {acceptance.checks.map((check) => (
                <Card key={check.id}>
                  <strong>{check.label}</strong>
                  <Pill tone={stateTone(check.status)}>{check.status}</Pill>
                  <small>{check.evidence_refs.join(", ") || "No evidence refs yet"}</small>
                </Card>
              ))}
            </div>
            <Card>
              <strong>Learn loop proposal</strong>
              <Pill tone={acceptance.learning_record.status === "accepted" ? "healthy" : "warning"}>
                {acceptance.learning_record.status}
              </Pill>
              <p>{acceptance.learning_record.summary}</p>
              <small>{acceptance.learning_record.tags.join(", ")} / {acceptance.learning_record.target_file}</small>
              <div className="actions">
                <button
                  disabled={acceptance.status !== "passed" || acceptance.learning_record.status === "accepted"}
                  onClick={() => void approveLearning()}
                >
                  Accept learning
                </button>
              </div>
            </Card>
          </>
        ) : null}
      </section>
    </>
  );
}

function useWorkspaceOperationalViews(liveTick: number) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [snapshot, setSnapshot] = useState<OperationalViewsSnapshot | null>(null);
  const [status, setStatus] = useState(
    apiConfigured ? "Loading persisted workspace operations." : "Demo mode. Connect service for persisted operations.",
  );

  useEffect(() => {
    if (!apiConfigured) {
      setSnapshot(null);
      return;
    }
    let cancelled = false;
    async function loadOperationalViews() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const nextSnapshot = await getWorkspaceOperationalViews(selectedWorkspace.id);
        if (!cancelled) {
          setSnapshot(nextSnapshot);
          setStatus(
            `${nextSnapshot.history.length} events, ${nextSnapshot.diagrams.length} diagrams, ${nextSnapshot.usage.tasks.total} tasks loaded from SQLite.`,
          );
        }
      } catch (error) {
        if (!cancelled) {
          setSnapshot(null);
          setStatus(error instanceof Error ? error.message : "Operational views load failed.");
        }
      }
    }
    void loadOperationalViews();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, liveTick]);

  return { snapshot, status };
}

function useDogfoodAcceptance(liveTick: number) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [acceptance, setAcceptance] = useState<DogfoodAcceptanceSnapshot | null>(null);
  const [status, setStatus] = useState(
    apiConfigured ? "Loading dogfood acceptance dossier." : "Demo mode. Connect service for dogfood acceptance.",
  );

  useEffect(() => {
    if (!apiConfigured) {
      setAcceptance(null);
      return;
    }
    let cancelled = false;
    async function loadAcceptance() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const nextAcceptance = await getDogfoodAcceptance(selectedWorkspace.id);
        if (!cancelled) {
          setAcceptance(nextAcceptance);
          setStatus(`${nextAcceptance.status}: ${nextAcceptance.checks.length} dogfood checks loaded.`);
        }
      } catch (error) {
        if (!cancelled) {
          setAcceptance(null);
          setStatus(error instanceof Error ? error.message : "Dogfood acceptance load failed.");
        }
      }
    }
    void loadAcceptance();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, liveTick]);

  async function approveLearning() {
    if (!apiConfigured || !acceptance) return;
    try {
      setStatus("Writing approved dogfood learning to learnings.md.");
      const result = await approveDogfoodLearning(acceptance.workspace_id);
      setAcceptance(result.acceptance);
      setAcceptance((current) => current ? {
        ...current,
        learning_record: result.learning_record,
      } : current);
      setStatus(`Learning accepted in ${result.learning_record.target_file}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Dogfood learning approval failed.");
    }
  }

  return { acceptance, status, approveLearning };
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}m`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`;
  }
  return String(value);
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return <section className="panel metric"><span className="eyebrow">{label}</span><strong>{value}</strong><p>{note}</p></section>;
}

function PanelTitle({ title, badge }: { title: string; badge: string }) {
  return <div className="panel-title"><h2>{title}</h2><Pill tone={stateTone(badge)}>{badge}</Pill></div>;
}

function Card({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return <div className="card" style={style}>{children}</div>;
}

function Field({ label, value }: { label: string; value: string }) {
  return <div className="field"><span>{label}</span><strong>{value}</strong></div>;
}

function MessageBubble({ from, target, tag, text, impact }: { from: string; target: string; tag: string; text: string; impact: string }) {
  return <div className="message"><small>{from} to {target} / {tag} / {impact}</small><p>{text}</p></div>;
}

function StatusLine({ label, value, tone }: { label: string; value: string; tone: "live" | "warn" | "bad" }) {
  return <div className="status-line"><span><i className={`dot ${tone}`} />{label}</span><strong>{value}</strong></div>;
}

function streamTone(state: string): "live" | "warn" | "bad" {
  if (state === "connected") return "live";
  if (state === "demo" || state === "connecting" || state === "polling") return "warn";
  return "bad";
}

function toneToRadixColor(tone: string): "green" | "blue" | "orange" | "red" | "violet" | "gray" | "indigo" {
  if (["healthy", "complete", "online", "approved", "accepted", "valid"].includes(tone)) return "green";
  if (["active", "live"].includes(tone)) return "indigo";
  if (["warning", "pending", "queued", "waiting", "waiting_human", "dirty", "degraded"].includes(tone)) return "orange";
  if (["blocked", "bad", "offline", "rejected", "failed", "missing"].includes(tone)) return "red";
  if (["draft"].includes(tone)) return "violet";
  return "gray";
}

function Pill({ children, tone = "draft" }: { children: ReactNode; tone?: Tone | string }) {
  const color = toneToRadixColor(stateTone(tone));
  return <Badge color={color} variant="soft" radius="medium" size="1">{children}</Badge>;
}

function stateTone(value: string): Tone {
  if (["complete", "healthy", "online", "approved", "accepted", "valid", "active", "live"].includes(value)) {
    return value === "active" || value === "live" ? "active" : "healthy";
  }
  if (["warning", "pending", "queued", "waiting", "waiting_human", "dirty", "draft", "degraded"].includes(value)) {
    return value === "draft" ? "draft" : "warning";
  }
  if (["blocked", "offline", "rejected", "failed", "missing"].includes(value)) {
    return "blocked";
  }
  return "draft";
}
