import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
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
  ClockIcon,
  DashboardIcon,
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
} from "@radix-ui/react-icons";
import {
  attachWorkspaceRepository,
  approveDogfoodLearning,
  approveRepositoryAction,
  approveTaskGate,
  createWorkspace,
  createTaskHandoff,
  createTaskGraphDraft,
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
  metrics,
  templates,
  templateCategories,
  workflows,
  type WorkspaceRepo,
  type Tone,
} from "./mockData";

type Route =
  | "workspace"
  | "orchestrator"
  | "inbox"
  | "tasks"
  | "views"
  | "task"
  | "agents"
  | "lifecycle"
  | "history"
  | "diagrams"
  | "usage"
  | "settings"
  | "templates"
  | "workflows";

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

const routeIcons: Record<Route, ReactNode> = {
  workspace:    <DashboardIcon />,
  orchestrator: <MixIcon />,
  inbox:        <ArchiveIcon />,
  tasks:        <CheckboxIcon />,
  views:        <BarChartIcon />,
  task:         <LayersIcon />,
  agents:       <PersonIcon />,
  lifecycle:    <LoopIcon />,
  history:      <ClockIcon />,
  diagrams:     <Share2Icon />,
  usage:        <ActivityLogIcon />,
  settings:     <GearIcon />,
  templates:    <ArchiveIcon />,
  workflows:    <BarChartIcon />,
};

const routes: Record<Route, string> = {
  workspace: "Workspace",
  orchestrator: "Orchestrator",
  inbox: "Inbox",
  tasks: "Tasks",
  views: "Views",
  task: "Task Studio",
  agents: "Agents",
  lifecycle: "Lifecycle",
  history: "History",
  diagrams: "Diagrams",
  usage: "Usage Stats",
  settings: "Settings",
  templates: "Templates",
  workflows: "Workflows",
};

const navGroups: Array<{ label: string; items: Array<{ id: Route; count?: string }> }> = [
  {
    label: "Workspace",
    items: [
      { id: "workspace", count: "live" },
      { id: "orchestrator", count: "1" },
      { id: "inbox", count: "3" },
      { id: "tasks", count: "2" },
      { id: "views", count: "7" },
    ],
  },
  {
    label: "Library",
    items: [
      { id: "templates" },
      { id: "workflows" },
    ],
  },
  {
    label: "Agents",
    items: [
      { id: "agents", count: "10" },
      { id: "lifecycle", count: "12" },
    ],
  },
  {
    label: "Operate",
    items: [
      { id: "history", count: "48" },
      { id: "diagrams", count: "2" },
      { id: "usage", count: "MVP" },
      { id: "settings" },
    ],
  },
];

export function App() {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [route, setRoute] = useState<Route>("workspace");
  const [selectedTask, setSelectedTask] = useState<TaskDashboardItem | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState("ST-02");
  const [taskTab, setTaskTab] = useState<TaskTab>("messages");
  const [showList, setShowList] = useState(false);
  const [dark, setDark] = useState(false);
  const [liveTick, setLiveTick] = useState(0);
  const [streamState, setStreamState] = useState(apiConfigured ? "connecting" : "demo");
  const [streamDetail, setStreamDetail] = useState(apiConfigured ? "SSE connecting" : "Demo mode");

  const selectedUnit = useMemo(
    () => subtasks.find((unit) => unit.id === selectedUnitId) ?? subtasks[0],
    [selectedUnitId],
  );

  useEffect(() => {
    if (!apiConfigured) {
      return;
    }
    let cancelled = false;
    let source: EventSource | null = null;
    let pollInterval: number | undefined;
    let observedEventCount = 0;

    async function startLiveUpdates() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const streamUrl = getEventsStreamUrl(selectedWorkspace.id);
        if (!streamUrl || typeof EventSource === "undefined") {
          startPolling(selectedWorkspace.id);
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
          startPolling(selectedWorkspace.id);
        };
      } catch (error) {
        if (!cancelled) {
          setStreamState("polling");
          setStreamDetail(error instanceof Error ? error.message : "Live updates fallback active");
        }
      }
    }

    function startPolling(workspaceId: string) {
      if (pollInterval !== undefined) return;
      pollInterval = window.setInterval(() => {
        void listEvents(workspaceId).then((nextEvents) => {
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
  }, [apiConfigured]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setRoute("orchestrator");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setRoute]);

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
      <aside className="sidebar">
        <button className="brand" onClick={() => setRoute("workspace")}>
          <div className="brand-mark">S</div>
          <div>
            <strong>Sarathi</strong>
            <span>Charioteer for AI Agents</span>
          </div>
        </button>

        <button className="workspace-switch" onClick={() => setRoute("workspace")}>
          <span className="dot live" />
          <span style={{ flex: 1 }}>
            <strong>{workspace.id}</strong>
            <small>{workspace.repos.length} repos linked</small>
          </span>
          <ChevronRightIcon style={{ color: "var(--faint)", flexShrink: 0 }} />
        </button>

        <nav aria-label="Primary">
          {navGroups.map((group) => (
            <section className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.map((item) => (
                <button
                  className={route === item.id ? "nav-item active" : "nav-item"}
                  key={item.id}
                  onClick={() => setRoute(item.id)}
                >
                  <span>{routeIcons[item.id]}{routes[item.id]}</span>
                  {item.count ? <em>{item.count}</em> : null}
                </button>
              ))}
            </section>
          ))}
        </nav>

        <section className="sidebar-card">
          <span className="eyebrow">Environment</span>
          <StatusLine tone="live" label="Sessions" value="3 active" />
          <StatusLine tone="live" label="SQLite" value="ready" />
          <StatusLine tone={streamTone(streamState)} label="Streams" value={streamDetail} />
        </section>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="crumb">Workspace / {workspace.id}</span>
            <h1>{routes[route]}</h1>
          </div>
          <button className="command" onClick={() => setRoute("orchestrator")}>
            <MagnifyingGlassIcon />
            Ask Sarathi to plan, split, dispatch, review...
            <kbd>⌘K</kbd>
          </button>
          <button className="icon-action" title="Toggle dark mode" onClick={() => setDark((value) => !value)}>
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
          <button className="primary" onClick={() => setRoute("orchestrator")}>
            <PlusIcon />
            New task
          </button>
        </header>

        <div className="page-body">
          <section className="status-strip" style={{ marginBottom: 16 }}>
            <Pill tone="active">Workspace {workspace.status}</Pill>
            <Pill tone="healthy">SQLite ready</Pill>
            <Pill tone={streamState === "connected" ? "healthy" : "warning"}>{streamDetail}</Pill>
            <Pill tone="warning">Dirty worktree</Pill>
            <Pill tone="blocked">Claude offline</Pill>
          </section>

          {route === "workspace" && <WorkspaceOverview setRoute={setRoute} liveTick={liveTick} />}
          {route === "orchestrator" && <Orchestrator setRoute={setRoute} />}
          {route === "inbox" && <Inbox />}
          {route === "tasks" && <TaskDashboard liveTick={liveTick} setRoute={setRoute} setSelectedTask={setSelectedTask} />}
          {route === "views" && <SavedViews setRoute={setRoute} />}
          {route === "task" && (
            <TaskStudio
              selectedUnit={selectedUnit}
              selectedTask={selectedTask}
              selectedUnitId={selectedUnitId}
              setSelectedUnitId={setSelectedUnitId}
              taskTab={taskTab}
              setTaskTab={setTaskTab}
              showList={showList}
              setShowList={setShowList}
              liveTick={liveTick}
            />
          )}
          {route === "agents" && <Agents liveTick={liveTick} />}
          {route === "lifecycle" && <Lifecycle liveTick={liveTick} />}
          {route === "history" && <History liveTick={liveTick} />}
          {route === "diagrams" && <Diagrams liveTick={liveTick} setRoute={setRoute} />}
          {route === "usage" && <Usage liveTick={liveTick} />}
          {route === "settings" && <Settings />}
          {route === "templates" && <TemplatesPage />}
          {route === "workflows" && <WorkflowsPage />}
        </div>
      </main>
    </div>
    </Theme>
  );
}

function WorkspaceOverview({
  liveTick,
  setRoute,
}: {
  liveTick: number;
  setRoute: (route: Route) => void;
}) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [attachedRepos, setAttachedRepos] = useState<WorkspaceRepo[]>(workspace.repos);
  const [repoDraftPath, setRepoDraftPath] = useState("/Users/sweethome/Work/Skills/Sarathi");
  const [repoPreview, setRepoPreview] = useState<RepositoryIntakePreview | null>(null);
  const [serviceWorkspace, setServiceWorkspace] = useState<WorkspaceRecord | null>(null);
  const [serviceWorkspaces, setServiceWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [workspaceDraftName, setWorkspaceDraftName] = useState(workspace.name);
  const [interviewDraft, setInterviewDraft] = useState({
    project_name: "Sarathi workspace repo",
    purpose: "A repository managed through Sarathi orchestration.",
    primary_language: "Unknown",
  });
  const [repoStatus, setRepoStatus] = useState(
    apiConfigured ? "Connected to local service." : "Demo preview mode. Configure local service to persist attach.",
  );
  const [isPreviewing, setIsPreviewing] = useState(false);

  useEffect(() => {
    if (!apiConfigured) {
      return;
    }
    let cancelled = false;
    async function initializeWorkspace() {
      try {
        const workspaces = await listWorkspaces();
        const existing =
          workspaces.find((candidate) => candidate.name === workspace.name)
          ?? workspaces[0]
          ?? await createWorkspace(workspace.name, "/Users/sweethome/Work/Skills/Sarathi", {
            source: "desktop-ui",
            display_id: workspace.id,
          });
        if (!cancelled) {
          setServiceWorkspaces(workspaces.includes(existing) ? workspaces : [existing, ...workspaces]);
          setServiceWorkspace(existing);
          setRepoStatus(`Connected to local service workspace ${existing.id}.`);
        }
      } catch (error) {
        if (!cancelled) {
          setRepoStatus(error instanceof Error ? error.message : "Workspace initialization failed.");
        }
      }
    }
    void initializeWorkspace();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured]);

  useEffect(() => {
    if (!apiConfigured || !serviceWorkspace) {
      return;
    }
    const workspaceId = serviceWorkspace.id;
    let cancelled = false;
    async function loadRepositories() {
      try {
        const repositories = await listWorkspaceRepositories(workspaceId);
        if (!cancelled) {
          setAttachedRepos(repositories.map(repositoryRecordToRepo));
        }
      } catch (error) {
        if (!cancelled) {
          setRepoStatus(error instanceof Error ? error.message : "Repository list refresh failed.");
        }
      }
    }
    void loadRepositories();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, serviceWorkspace, liveTick]);


  async function createServiceWorkspace() {
    if (!apiConfigured) {
      setRepoStatus("Workspace creation requires the local service.");
      return;
    }
    setIsPreviewing(true);
    try {
      const created = await createWorkspace(
        workspaceDraftName.trim() || workspace.name,
        "/Users/sweethome/Work/Skills/Sarathi",
        { source: "desktop-ui", display_id: workspace.id },
      );
      setServiceWorkspaces((current) => [created, ...current]);
      setServiceWorkspace(created);
      setRepoStatus(`Created and selected workspace ${created.id}.`);
    } catch (error) {
      setRepoStatus(error instanceof Error ? error.message : "Workspace creation failed.");
    } finally {
      setIsPreviewing(false);
    }
  }

  async function previewRepository() {
    const trimmedPath = repoDraftPath.trim();
    if (!trimmedPath) {
      setRepoStatus("Enter a repository path before preview.");
      return;
    }
    setIsPreviewing(true);
    try {
      const preview = apiConfigured
        ? await previewWorkspaceRepository(requireServiceWorkspaceId(serviceWorkspace), trimmedPath)
        : createDemoPreview(trimmedPath);
      setRepoPreview(preview);
      setRepoStatus(
        apiConfigured
          ? "Live preview returned from local service. No files were mutated."
          : "Demo preview only. Start the local service to persist repository attach.",
      );
    } catch (error) {
      setRepoStatus(error instanceof Error ? error.message : "Repository preview failed.");
    } finally {
      setIsPreviewing(false);
    }
  }

  async function attachRepository() {
    if (!repoPreview) {
      setRepoStatus("Preview a repository before attaching it.");
      return;
    }
    if (!apiConfigured) {
      setRepoStatus("Attach requires the local service. Preview remains safe and non-mutating.");
      return;
    }
    setIsPreviewing(true);
    try {
      const repository = await attachWorkspaceRepository(
        requireServiceWorkspaceId(serviceWorkspace),
        repoPreview.path,
      );
      setAttachedRepos((current) => [
        ...current,
        {
          id: repository.id,
          name: repository.name ?? repoPreview.name,
          path: repository.path,
          branch: repository.metadata.intake?.branch ?? "unknown",
          gitState: repository.metadata.intake?.dirty ? "dirty" : "clean",
          permission: "write",
        },
      ]);
      setRepoStatus("Repository attached after approval. Sarathi recorded a lifecycle event.");
    } catch (error) {
      setRepoStatus(error instanceof Error ? error.message : "Repository attach failed.");
    } finally {
      setIsPreviewing(false);
    }
  }

  async function initializeRepository(repo: WorkspaceRepo) {
    if (!apiConfigured) {
      setRepoStatus("Repository initialization requires the local service.");
      return;
    }
    setIsPreviewing(true);
    try {
      const result = await initializeWorkspaceRepository(
        requireServiceWorkspaceId(serviceWorkspace),
        repo.id,
        repoPreview?.requires_interview ? interviewDraft : {},
      );
      setAttachedRepos((current) => current.map((candidate) =>
        candidate.id === repo.id ? repositoryRecordToRepo(result.repository) : candidate,
      ));
      setRepoStatus(
        `Sarathi initialized ${repo.name}: ${result.initialization.created_files.length} files created.`,
      );
    } catch (error) {
      setRepoStatus(error instanceof Error ? error.message : "Repository initialization failed.");
    } finally {
      setIsPreviewing(false);
    }
  }

  return (
    <div className="grid two">
      <MetricsStrip />
      <div style={{ display: "flex", flexDirection: "column", gap: 12, gridColumn: "1 / -1" }}>
      <section className="panel hero">
        <span className="eyebrow">Sarathi builds Sarathi</span>
        <h2>Dogfood cockpit for turning intent into verified, reviewable work.</h2>
        <p>
          This workspace proves the app is being developed through the same CLI/Skill model baked into the
          product: PRD, plan, graph, evidence, review, handoff, and learnings.
        </p>
        <div className="actions">
          <button className="primary" onClick={() => setRoute("orchestrator")}>Start with Sarathi</button>
          <button onClick={() => setRoute("task")}>Open Task Studio</button>
        </div>
      </section>

      <section className="panel">
        <PanelTitle title="Workspace readiness" badge="M0" />
        {workspace.docs.map((doc) => (
          <Card key={doc.name}>
            <strong>{doc.name}</strong>
            <Pill tone={doc.state === "valid" || doc.state === "active" ? "healthy" : "warning"}>
              {doc.state}
            </Pill>
            <p>{doc.note}</p>
          </Card>
        ))}
      </section>

      <section className="panel">
        <PanelTitle title="Repository intake preview" badge="UI-04" />
        <p>
          Attach one or more repos to this workspace. Sarathi previews Git state, policy-pack readiness,
          and what it would create before any file mutation.
        </p>
        <Pill tone={apiConfigured ? "healthy" : "warning"}>
          {apiConfigured ? "local service" : "demo mode"}
        </Pill>
        {serviceWorkspace ? (
          <div className="stacked-field">
            <label htmlFor="service-workspace">Service workspace</label>
            <select
              id="service-workspace"
              value={serviceWorkspace.id}
              onChange={(event) => {
                const next = serviceWorkspaces.find((candidate) => candidate.id === event.target.value);
                if (next) {
                  setServiceWorkspace(next);
                  setRepoStatus(`Selected workspace ${next.id}.`);
                }
              }}
            >
              {serviceWorkspaces.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name} / {candidate.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="inline-form">
          <input
            aria-label="Workspace name"
            value={workspaceDraftName}
            onChange={(event) => setWorkspaceDraftName(event.target.value)}
          />
          <button onClick={createServiceWorkspace} disabled={isPreviewing}>
            Create workspace
          </button>
        </div>
        <div className="inline-form">
          <input
            aria-label="Repository path"
            value={repoDraftPath}
            onChange={(event) => setRepoDraftPath(event.target.value)}
          />
          <button className="primary" onClick={previewRepository} disabled={isPreviewing}>
            {isPreviewing ? "Checking" : "Preview"}
          </button>
        </div>
        {repoPreview ? (
          <Card>
            <strong>{repoPreview.name}</strong>
            <Pill tone={repoPreview.dirty ? "warning" : "healthy"}>{repoPreview.recommended_mode}</Pill>
            <Field label="Branch" value={repoPreview.branch ?? "unknown"} />
            <Field label="Git state" value={repoPreview.dirty ? "dirty" : "clean"} />
            <Field label="Sarathi docs" value={repoPreview.sarathi_initialized ? "ready" : "needs setup"} />
            {repoPreview.warnings.map((warning) => <p key={warning}>{warning}</p>)}
            {repoPreview.requires_interview ? (
              <div className="mini-list">
                <input
                  aria-label="Project name"
                  value={interviewDraft.project_name}
                  onChange={(event) => setInterviewDraft({ ...interviewDraft, project_name: event.target.value })}
                />
                <input
                  aria-label="Project purpose"
                  value={interviewDraft.purpose}
                  onChange={(event) => setInterviewDraft({ ...interviewDraft, purpose: event.target.value })}
                />
                <input
                  aria-label="Primary language"
                  value={interviewDraft.primary_language}
                  onChange={(event) => setInterviewDraft({ ...interviewDraft, primary_language: event.target.value })}
                />
              </div>
            ) : null}
            <button className="full" onClick={attachRepository} disabled={isPreviewing}>
              Approve and attach repo
            </button>
          </Card>
        ) : (
          <Card>
            <strong>No preview yet</strong>
            <p>Run a preview to see branch, dirty-state, Sarathi docs, and approval requirements.</p>
          </Card>
        )}
        <small>{repoStatus}</small>
      </section>

      {attachedRepos.map((repo) => (
        <section className="panel" key={repo.id}>
          <PanelTitle title={repo.name} badge={repo.gitState} />
          <Field label="Branch" value={repo.branch} />
          <Field label="Permission" value={repo.permission} />
          <Field label="Path" value={repo.path} />
          <Field label="Sarathi init" value={repo.initializationStatus ?? "not initialized"} />
          <button className="full" onClick={() => void initializeRepository(repo)} disabled={isPreviewing}>
            Approve Sarathi init
          </button>
        </section>
      ))}
      </div>
      </div>
  );
}

function requireServiceWorkspaceId(workspaceRecord: WorkspaceRecord | null): string {
  if (!workspaceRecord) {
    throw new Error("Local service workspace is still initializing.");
  }
  return workspaceRecord.id;
}

function repositoryRecordToRepo(repository: {
  id: string;
  name: string | null;
  path: string;
  metadata: { intake?: RepositoryIntakePreview; sarathi_initialization?: { status?: string } };
}): WorkspaceRepo {
  return {
    id: repository.id,
    name: repository.name ?? repository.metadata.intake?.name ?? "Repository",
    path: repository.path,
    branch: repository.metadata.intake?.branch ?? "unknown",
    gitState: repository.metadata.intake?.dirty ? "dirty" : "clean",
    permission: "write",
    initializationStatus: repository.metadata.sarathi_initialization?.status ?? (
      repository.metadata.intake?.sarathi_initialized ? "completed" : "not initialized"
    ),
  };
}

function createDemoPreview(path: string): RepositoryIntakePreview {
  const name = path.split("/").filter(Boolean).at(-1) ?? "workspace-repo";
  const looksLikeSarathi = path.toLowerCase().includes("sarathi");
  return {
    path,
    name,
    exists: Boolean(path),
    is_directory: Boolean(path),
    is_git_repo: looksLikeSarathi,
    branch: looksLikeSarathi ? "main" : null,
    remote_url: null,
    dirty: looksLikeSarathi,
    changes: looksLikeSarathi ? ["mock: dirty worktree warning"] : [],
    sarathi_initialized: looksLikeSarathi,
    recommended_mode: looksLikeSarathi ? "sarathi_enabled_repo" : "directory",
    requires_interview: !looksLikeSarathi,
    warnings: looksLikeSarathi
      ? ["Demo warning: verify dirty worktree before initialization."]
      : ["Demo warning: policy pack not detected; interview required."],
    would_create: looksLikeSarathi ? [] : ["policy-pack/", "wiki/", "coding-standards.md", "learnings.md"],
  };
}

function Orchestrator({ setRoute }: { setRoute: (route: Route) => void }) {
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
          <button type="button">Current task agents</button>
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
        <button className="primary full" onClick={() => setRoute("task")}>Open Task Studio</button>
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

const inboxItems = [
  { title: "User request: start Sarathi UI", tag: "classified", desc: "Preserve source context before converting into task or evidence.", time: "09:10" },
  { title: "External review feedback", tag: "classified", desc: "Review comments from external stakeholder on UI foundation.", time: "09:18" },
  { title: "Mission Control comparison", tag: "classified", desc: "Reference screenshots for dashboard layout decisions.", time: "09:24" },
];

function Inbox() {
  return (
    <section className="panel">
      <PanelTitle title="Inbox" badge="capture" />
      <div>
        {inboxItems.map((item) => (
          <div className="inbox-item" key={item.title}>
            <span className="inbox-dot" />
            <div className="inbox-body">
              <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "space-between" }}>
                <span className="inbox-title">{item.title}</span>
                <span style={{ fontSize: "0.72rem", color: "var(--faint)", fontFamily: "monospace", flexShrink: 0 }}>{item.time}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                <Pill tone="warning">{item.tag}</Pill>
                <span className="inbox-desc">{item.desc}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TaskDashboard({
  liveTick,
  setRoute,
  setSelectedTask,
}: {
  liveTick: number;
  setRoute: (route: Route) => void;
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
              <tr key={task.id} onClick={() => { setSelectedTask(task); setRoute("task"); }}>
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
            setRoute("task");
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

function SavedViews({ setRoute }: { setRoute: (route: Route) => void }) {
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
          <button className="card" key={view.id} onClick={() => setRoute(view.target as Route)}>
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
      const result = await sendChatMessage(message, { workspaceId: ws.id, taskId: selectedTask?.id });
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
      const allFiles: string[] = [];
      taskEvidence.forEach(e => {
        const files = (e.metadata.response_evidence as { changed_files?: unknown })?.changed_files;
        if (Array.isArray(files)) files.forEach(f => allFiles.push(String(f)));
      });
      const testEv = taskEvidence.filter(e => e.artifact_type === "test" || String(e.metadata.subtask_id)?.includes("test"));
      const reviewEv = taskEvidence.filter(e => e.artifact_type === "review");
      return (
        <>
          {allFiles.length > 0 && (
            <section>
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>Changed files</h3>
                <Pill tone="active">{allFiles.length}</Pill>
              </div>
              <div className="mini-list">
                {allFiles.map((file, i) => (
                  <span key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <input type="checkbox" readOnly defaultChecked style={{ width: 14, height: 14 }} />
                    <span>{file}</span>
                  </span>
                ))}
              </div>
            </section>
          )}
          {testEv.length > 0 && (
            <section style={{ marginTop: 16 }}>
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>Tests</h3>
                <Pill tone="healthy">{testEv.length}</Pill>
              </div>
              {testEv.map(item => (
                <Card key={item.id}><strong>{item.id.slice(0, 8)}</strong><p>{item.uri}</p></Card>
              ))}
            </section>
          )}
          {reviewEv.length > 0 && (
            <section style={{ marginTop: 16 }}>
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>Review verdict</h3>
                <Pill tone="healthy">reviewed</Pill>
              </div>
              {reviewEv.map(item => (
                <Card key={item.id}>
                  <strong>Review {item.id.slice(0, 8)}</strong>
                  <small>{String(item.metadata.provider)} / {item.created_at?.slice(0, 19)}</small>
                </Card>
              ))}
            </section>
          )}
          {dispatches && dispatches.length > 0 && (
            <section style={{ marginTop: 16 }}>
              <div className="panel-title" style={{ paddingBottom: 8, marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.8rem" }}>Dispatches</h3>
                <Pill tone="default">{dispatches.length}</Pill>
              </div>
              {dispatches.map((dispatch) => (
                <Card key={dispatch.id}>
                  <strong>Dispatch {dispatch.id.slice(0, 8)}</strong>
                  <Pill tone={stateTone(dispatch.status)}>{dispatch.status}</Pill>
                  <p>{dispatch.agent_name}</p>
                  <small>{dispatch.created_at?.slice(11, 19)}</small>
                </Card>
              ))}
            </section>
          )}
        </>
      );
    }
    return <>{evidence.map((item) => <Card key={item.id}><strong>{item.id} - {item.title}</strong><Pill tone={stateTone(item.state)}>{item.state}</Pill><p>{item.source} / {item.linkedUnit} / {item.linkedGate} / {item.linkedEvent}</p></Card>)}</>;
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
  const acCoverage = handoff?.metadata.ac_coverage as
    | Array<{ id?: string; criterion?: string; covered?: boolean }>
    | undefined;
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
        <div className="actions" style={{ gap: 8 }}>
          {[
            { id: "no_action", label: "No action", tone: "default" },
            { id: "prepare_patch", label: "Prepare patch", tone: "warning" },
            { id: "commit", label: "Commit", tone: "active" },
            { id: "draft_pr", label: "Draft PR", tone: "healthy" },
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

function Diagrams({ liveTick, setRoute }: { liveTick: number; setRoute: (route: Route) => void }) {
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
            <button onClick={() => setRoute(diagram.kind === "agent_lifecycle" ? "lifecycle" : "task")}>
              Open {diagram.kind === "agent_lifecycle" ? "Lifecycle" : "Task Studio"}
            </button>
          </Card>
        )) : (
          <>
            <Card><strong>Dependency graph</strong><p>Task graph artifact generated from real subtask state.</p><button onClick={() => setRoute("task")}>Open Task Studio</button></Card>
            <Card><strong>Agent lifecycle</strong><p>Role flow, review loop, and handoff state.</p><button onClick={() => setRoute("lifecycle")}>Open Lifecycle</button></Card>
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
  return (
    <>
      <section className="panel">
        <PanelTitle title="Usage statistics" badge={usage ? "SQLite source" : "demo"} />
        <p>{status}</p>
      </section>
      <div className="grid four">
        <Metric label="Tasks complete" value={String(usage?.tasks.done ?? 1)} note={`${usage?.tasks.total ?? 1} total tasks`} />
        <Metric label="Units active" value={String(usage?.subtasks.by_status.in_progress ?? 4)} note={`${usage?.subtasks.total ?? 4} graph units`} />
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

function Settings() {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [providerHealth, setProviderHealth] = useState<ProviderHealthRecord[]>([]);
  const [providerDrafts, setProviderDrafts] = useState<Record<string, { path: string; auth: string }>>({});
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null);
  const [settingsStatus, setSettingsStatus] = useState(
    apiConfigured ? "Loading provider settings." : "Demo provider settings.",
  );
  const [providerPriority, setProviderPriority] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("sarathi_provider_priority") || "null") || ["claude", "codex", "copilot", "opencode"];
    } catch {
      return ["claude", "codex", "copilot", "opencode"];
    }
  });

  useEffect(() => {
    if (!apiConfigured) return;
    let cancelled = false;
    async function loadSettingsProviders() {
      try {
        const selectedWorkspace = await ensureWorkspace(
          workspace.name,
          "/Users/sweethome/Work/Skills/Sarathi",
          { source: "desktop-ui", display_id: workspace.id },
        );
        const nextProviders = await listProviders(selectedWorkspace.id);
        if (!cancelled) {
          setProviderHealth(nextProviders);
          setProviderDrafts(Object.fromEntries(nextProviders.map((provider) => [
            provider.id,
            { path: provider.path, auth: provider.auth },
          ])));
          setSettingsStatus(`${nextProviders.length} providers loaded from workspace settings.`);
        }
      } catch (error) {
        if (!cancelled) {
          setSettingsStatus(error instanceof Error ? error.message : "Provider settings load failed.");
        }
      }
    }
    void loadSettingsProviders();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured]);

  async function testProvider(provider: ProviderHealthRecord) {
    if (!apiConfigured) {
      setSettingsStatus("Testing providers requires the local service.");
      return;
    }
    setTestingProviderId(provider.id);
    try {
      setSettingsStatus(`Testing ${provider.name}...`);
      const selectedWorkspace = await ensureWorkspace(
        workspace.name,
        "/Users/sweethome/Work/Skills/Sarathi",
        { source: "desktop-ui", display_id: workspace.id },
      );
      const draft = providerDrafts[provider.id] ?? { path: provider.path, auth: provider.auth };
      const updated = await testProviderConnection(selectedWorkspace.id, provider.id, draft.path, draft.auth);
      setProviderHealth((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
      setProviderDrafts((current) => ({ ...current, [updated.id]: { path: updated.path, auth: updated.auth } }));
      setSettingsStatus(`${updated.name} is ${updated.health}${updated.last_error ? `: ${updated.last_error}` : "."}`);
    } catch (error) {
      setSettingsStatus(error instanceof Error ? error.message : "Provider test failed.");
    } finally {
      setTestingProviderId(null);
    }
  }

  const visibleProviders: ProviderHealthRecord[] = providerHealth.length ? providerHealth : providers.map((provider) => ({
    id: provider.id,
    name: provider.name,
    provider_type: provider.type,
    health: provider.health,
    auth: provider.auth,
    path: provider.path,
    capabilities: provider.capabilities,
    last_checked_at: null,
    last_error: null,
  }));

  return (
    <div className="grid two">
      <section className="panel">
        <PanelTitle title="Setup checklist" badge="M0" />
        <Field label="CLI validation" value="ready" />
        <Field label="Provider setup" value={providerHealth.some((provider) => provider.health === "online") ? "ready" : "warning"} />
        <Field label="Policy pack" value={workspace.policyPack} />
        <Field label="SQLite" value={workspace.sqlite} />
        <small>{settingsStatus}</small>
      </section>
      <section className="panel">
        <PanelTitle title="Provider health" badge={apiConfigured ? "workspace" : "demo"} />
        {visibleProviders.map((provider) => {
          const draft = providerDrafts[provider.id] ?? { path: provider.path, auth: provider.auth };
          return (
            <Card key={provider.id}>
              <strong>{provider.name}</strong>
              <Pill tone={stateTone(provider.health)}>{provider.health}</Pill>
              <div className="mini-list">
                <input
                  aria-label={`${provider.name} CLI path`}
                  value={draft.path}
                  onChange={(event) => setProviderDrafts({
                    ...providerDrafts,
                    [provider.id]: { ...draft, path: event.target.value },
                  })}
                />
                <select
                  aria-label={`${provider.name} auth`}
                  value={draft.auth}
                  onChange={(event) => setProviderDrafts({
                    ...providerDrafts,
                    [provider.id]: { ...draft, auth: event.target.value },
                  })}
                >
                  <option value="connected">connected</option>
                  <option value="missing">missing</option>
                  <option value="not_required">not_required</option>
                  <option value="workspace_setting">workspace_setting</option>
                  <option value="github_auth">github_auth</option>
                </select>
              </div>
              <small>{provider.last_checked_at ?? "not checked"} {provider.last_error ? `/ ${provider.last_error}` : ""}</small>
              <div className="actions">
                <button onClick={() => void testProvider(provider)} disabled={testingProviderId !== null}>
                  {testingProviderId === provider.id ? "Testing..." : "Test connection"}
                </button>
              </div>
            </Card>
          );
        })}
      </section>
      <section className="panel">
        <PanelTitle title="Dispatch priority" badge="drag to reorder" />
        <div className="mini-list">
          {providerPriority.map((pid, index) => (
            <div key={pid} style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.25rem 0" }}>
              <span style={{ flex: 1 }}>{pid}</span>
              <button
                disabled={index === 0}
                onClick={() => {
                  const newOrder = [...providerPriority];
                  [newOrder[index - 1], newOrder[index]] = [newOrder[index], newOrder[index - 1]];
                  setProviderPriority(newOrder);
                  localStorage.setItem("sarathi_provider_priority", JSON.stringify(newOrder));
                }}
              >
                Up
              </button>
              <button
                disabled={index === providerPriority.length - 1}
                onClick={() => {
                  const newOrder = [...providerPriority];
                  [newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]];
                  setProviderPriority(newOrder);
                  localStorage.setItem("sarathi_provider_priority", JSON.stringify(newOrder));
                }}
              >
                Down
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function WorkflowsPage() {
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [liveWorkflows, setLiveWorkflows] = useState<import("./mockData").WorkflowItem[] | null>(null);

  useEffect(() => {
    if (getSarathiApiConfig() === null) return;
    (async () => {
      try {
        const ws = await ensureWorkspace(workspace.name, "/Users/sweethome/Work/Skills/Sarathi");
        const items = await listTaskDashboard(ws.id);
        const mapped: import("./mockData").WorkflowItem[] = items.map((item) => {
          let status: import("./mockData").WorkflowItem["status"];
          if (item.status === "done") {
            status = "complete";
          } else if (item.status === "in_progress") {
            status = "in_progress";
          } else if (item.status === "graph_pending" || item.status === "prd_pending") {
            status = "paused";
          } else {
            status = "paused";
          }
          return {
            id: item.id,
            name: item.title,
            complexity: "medium" as const,
            phase: item.phase ?? "Build",
            successRate: 0,
            lastRun: item.updated_at,
            status,
          };
        });
        setLiveWorkflows(mapped);
      } catch {
        // fall back to mock data
      }
    })();
  }, []);

  const activeWorkflows = liveWorkflows ?? workflows;
  const visible = activeWorkflows.filter((wf) => {
    const matchesText = !filter || wf.name.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus = statusFilter === "All" || wf.status === statusFilter;
    return matchesText && matchesStatus;
  });
  const statusCounts: Record<string, number> = {};
  for (const wf of activeWorkflows) statusCounts[wf.status] = (statusCounts[wf.status] ?? 0) + 1;
  return (
    <>
      <div className="metrics-strip">
        {(["complete", "in_progress", "paused", "failed"] as const).map((s) => (
          <div className="metric-card" key={s}>
            <span className="metric-card-label">{s.replace("_", " ")}</span>
            <span className="metric-card-value">{statusCounts[s] ?? 0}</span>
          </div>
        ))}
      </div>
      <section className="panel" style={{ padding: 0 }}>
        <div className="workflow-filter-bar">
          <input
            placeholder="Search task runs..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {["All", "in_progress", "complete", "paused", "failed"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="workflow-table-wrap">
          <table>
            <thead>
              <tr><th>Task</th><th>Complexity</th><th>Phase</th><th>Last Run</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {visible.map((wf) => (
                <tr key={wf.id}>
                  <td style={{ fontWeight: 500 }}>{wf.name}</td>
                  <td>
                    <Pill tone={wf.complexity === "high" ? "warning" : wf.complexity === "medium" ? "active" : "healthy"}>
                      {wf.complexity}
                    </Pill>
                  </td>
                  <td style={{ color: "var(--muted)", fontSize: "0.8rem" }}>{wf.phase}</td>
                  <td style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{wf.lastRun}</td>
                  <td><Pill tone={stateTone(wf.status)}>{wf.status.replace("_", " ")}</Pill></td>
                  <td><a href="#">View</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "10px 14px", fontSize: "0.78rem", color: "var(--muted)", borderTop: "1px solid var(--border)" }}>
          Showing {visible.length} of {workflows.length} task runs
        </div>
      </section>
    </>
  );
}

function TemplatesPage() {
  const [category, setCategory] = useState("All");
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState<{ success: boolean; taskId?: string; error?: string } | null>(null);
  const apiConfigured = getSarathiApiConfig() !== null;
  const visible = templates.filter((t) => {
    const matchesCat = category === "All" || t.category === category;
    const matchesText = !filter || t.name.toLowerCase().includes(filter.toLowerCase()) || t.description.toLowerCase().includes(filter.toLowerCase());
    return matchesCat && matchesText;
  });
  const lifecycleTemplates = templates.filter((t) => t.category === "Lifecycle");

  const handleUseTemplate = async (template: import("./mockData").TemplateCard) => {
    if (creating) return;
    setCreating(true);
    setCreateResult(null);
    try {
      if (!apiConfigured) {
        setCreateResult({ success: false, error: "Sarathi service not connected. Start service to create tasks." });
        return;
      }
      const workspace = await ensureWorkspace("Skills", "/Users/sweethome/Work/Skills", { source: "desktop-ui" });
      const prompt = `${template.name}: ${template.description}`;
      const created = await createTaskDraft(workspace.id, prompt, template.name);
      setCreateResult({ success: true, taskId: created.task.id });
    } catch (err) {
      setCreateResult({ success: false, error: err instanceof Error ? err.message : "Failed to create task" });
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      {createResult && (
        <section className="panel" style={{ marginBottom: 16 }}>
          {createResult.success ? (
            <div style={{ padding: 12, background: "var(--success-bg)", borderRadius: "var(--radius-sm)", color: "var(--success)" }}>
              Task created: <strong>{createResult.taskId}</strong>
            </div>
          ) : (
            <div style={{ padding: 12, background: "var(--error-bg)", borderRadius: "var(--radius-sm)", color: "var(--error)" }}>
              {createResult.error}
            </div>
          )}
        </section>
      )}
      <section className="panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <h2>Lifecycle Presets</h2>
          <Pill tone="default">{lifecycleTemplates.length} presets</Pill>
        </div>
        <TemplateCards templates={lifecycleTemplates} compact onUseTemplate={handleUseTemplate} />
      </section>
      <section className="panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2>Browse Templates</h2>
            <input
              style={{ height: 28, padding: "0 8px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--hover)", fontSize: "0.8rem" }}
              placeholder="Filter by name or description..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <Pill tone="default">{visible.length} of {templates.length}</Pill>
        </div>
        <div className="tabs" style={{ marginBottom: 12 }}>
          {templateCategories.map((cat) => (
            <button key={cat} className={category === cat ? "active" : ""} onClick={() => setCategory(cat)}>{cat}</button>
          ))}
        </div>
        <TemplateCards templates={visible} onUseTemplate={handleUseTemplate} />
      </section>
    </>
  );
}

function TemplateCards({ templates: templateList, compact = false, onUseTemplate }: { templates: import("./mockData").TemplateCard[]; compact?: boolean; onUseTemplate?: (template: import("./mockData").TemplateCard) => void }) {
  return (
    <div className={compact ? "template-cards" : "grid three"} style={{ gridTemplateColumns: compact ? "repeat(3, minmax(0, 1fr))" : undefined }}>
      {templateList.map((tmpl) => (
        <button className="template-card" key={tmpl.id} onClick={() => onUseTemplate?.(tmpl)}>
          <span className="template-card-icon">{tmpl.icon}</span>
          <span className="template-card-name">{tmpl.name}</span>
          <div className="template-card-meta" style={{ marginBottom: 6 }}>
            <Pill tone={tmpl.complexity === "high" ? "warning" : tmpl.complexity === "medium" ? "active" : "healthy"}>{tmpl.complexity}</Pill>
            <span style={{ fontSize: "0.72rem", color: "var(--muted)", marginLeft: 6 }}>{tmpl.phases} phases</span>
          </div>
          {!compact && (
            <p style={{ fontSize: "0.73rem", color: "var(--muted)", margin: "4px 0 8px", lineHeight: 1.4, textAlign: "left" }}>{tmpl.description}</p>
          )}
          {!compact && (
            <span className="primary" style={{ height: 28, fontSize: "0.75rem", marginTop: 4, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 12px", borderRadius: "var(--radius-sm)", background: "var(--accent)", color: "var(--accent-contrast)" }}>Use Template</span>
          )}
        </button>
      ))}
    </div>
  );
}

function MetricsStrip() {
  return (
    <div className="metrics-strip">
      {metrics.map((m) => (
        <div className="metric-card" key={m.label}>
          <span className="metric-card-label">{m.label}</span>
          <span className="metric-card-value">{m.value}</span>
          {m.delta && (
            <span className={`metric-card-delta ${m.deltaPositive ? "positive" : "negative"}`}>
              {m.deltaPositive ? "▲" : "▼"} {m.delta}
            </span>
          )}
        </div>
      ))}
    </div>
  );
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
