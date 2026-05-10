import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  createTaskHandoff,
  ensureWorkspace,
  getSarathiApiConfig,
  getTaskCheckpoint,
  getTaskPanel,
  getTaskStudio,
  getWorkspaceOperationalViews,
  listTaskDashboard,
  listTaskCheckpoints,
  restartTaskFromCheckpoint,
  runTaskReview,
  scheduleTask,
  type LifecycleEventRecord,
  type CheckpointCapsuleRecord,
  type OperationalViewsSnapshot,
  type ReviewRunRecord,
  type TaskPanelEntry,
  type TaskDashboardItem,
  type TaskGraphNode,
  type TaskRecord,
  type TaskPanelSnapshot,
  type TaskStudioSnapshot,
  type TaskMetadata,
} from "../apiClient";
import TaskPanelTimeline from "../components/TaskPanelTimeline";
import { Card, Field, PanelTitle, Pill, stateTone } from "../components/ui";
import UnitGraph from "../components/UnitGraph";
import {
  approvalGates as mockApprovalGates,
  events as mockEvents,
  messages as mockMessages,
  roles,
  subtasks,
  tasks,
  workspace,
} from "../mockData";

type ProjectTab = "studio" | "lifecycle" | "history" | "usage";

interface Props {
  workspaceId?: string | null;
  projectId?: string | null;
  liveTick?: number;
  selectedTaskId?: string | null;
  setSelectedTaskId?: (id: string | null) => void;
  setRoute?: (route: string) => void;
}

function mockTasksToDashboardItems(): TaskDashboardItem[] {
  const blockedCount = subtasks.filter((unit) => unit.state === "blocked").length;
  return tasks.map((task, index) => ({
    id: task.id,
    workspace_id: workspace.id,
    title: task.title,
    status: task.status === "complete" ? "done" : task.status === "in_progress" ? "in_progress" : "prd_pending",
    phase: task.phase,
    approval_state: task.reviewState,
    graph_state: index === 0 ? "approved" : "pending_approval",
    next_gate: task.status === "complete" ? null : "Task graph",
    node_count: subtasks.length,
    blocked_count: blockedCount,
    roles: Array.from(new Set(subtasks.map((unit) => unit.role))),
    providers: Array.from(new Set(subtasks.map((unit) => unit.provider))),
    updated_at: new Date(Date.now() - index * 6 * 60 * 1000).toISOString(),
  }));
}

function mockTaskToRecord(task: TaskDashboardItem): TaskRecord {
  return {
    id: task.id,
    workspace_id: task.workspace_id,
    title: task.title,
    description: task.title,
    status: task.status === "done" ? "complete" : task.status,
    metadata: {
      source_prompt: task.title,
      complexity: "high",
      phase: task.phase,
      prd: {
        problem: task.title,
        goal: "Restore the task studio route.",
        scope: ["Task selector", "Graph", "Messages", "Lifecycle views"],
      },
      acceptance_criteria: [
        "Selected task loads a task studio snapshot.",
        "Graph, packet, messages, and gates remain visible.",
        "Lifecycle, history, and usage summaries are available.",
      ],
    },
    created_at: task.updated_at,
    updated_at: task.updated_at,
  };
}

function taskRecordToDashboardItem(task: TaskRecord): TaskDashboardItem {
  const metadata = task.metadata ?? {};
  const phase = typeof metadata.phase === "string" ? metadata.phase : "Build";
  const approvalState = task.status === "done" || task.status === "complete"
    ? "approved"
    : task.status === "in_progress"
      ? "in_progress"
      : "draft";
  const nodeCount = typeof metadata.node_count === "number" ? metadata.node_count : 1;
  const blockedCount = typeof metadata.blocked_count === "number" ? metadata.blocked_count : 0;
  return {
    id: task.id,
    workspace_id: task.workspace_id,
    title: task.title,
    status: task.status === "complete" ? "done" : task.status,
    phase,
    approval_state: approvalState,
    graph_state: typeof metadata.graph_state === "string" ? metadata.graph_state : "ready",
    next_gate: typeof metadata.next_gate === "string" ? metadata.next_gate : null,
    node_count: nodeCount,
    blocked_count: blockedCount,
    roles: Array.isArray(metadata.roles) ? metadata.roles.filter((value): value is string => typeof value === "string") : [],
    providers: Array.isArray(metadata.providers) ? metadata.providers.filter((value): value is string => typeof value === "string") : [],
    updated_at: task.updated_at,
  };
}

function createDemoCheckpoint(
  task: TaskDashboardItem,
  title: string,
  workspaceId: string,
  projectId: string | null,
): CheckpointCapsuleRecord {
  return {
    id: `demo-checkpoint-${task.id}`,
    workspace_id: workspaceId,
    project_id: projectId,
    source_task_id: task.id,
    status: "ready",
    summary: `${title} is ready for a fresh session.`,
    key_decisions: [
      "Keep the task panel compact.",
      "Preserve repository-action defaults across the restart.",
    ],
    evidence_refs: [`task:${task.id}`],
    repository_action_preference: {
      scope: "task",
      mode: "no_action",
      allowed_modes: ["no_action"],
      source: "demo",
    },
    next_start_point: "Start a new session from this checkpoint summary.",
    created_at: new Date().toISOString(),
    created_by: "Sarathi",
  };
}

function subtaskToGraphNode(node: (typeof subtasks)[number]): TaskGraphNode {
  return {
    id: node.id,
    title: node.title,
    status: node.state,
    role: node.role,
    provider: node.provider,
    blocked_by: node.blockedBy,
    evidence_required: node.ac.length > 0 ? node.ac : ["evidence"],
    task_packet: {
      goal: node.goal,
      context: node.context,
      review_criteria: node.ac,
    },
  };
}

function createDemoSnapshot(task: TaskDashboardItem): TaskStudioSnapshot {
  const now = new Date().toISOString();
  const nodes = subtasks.map(subtaskToGraphNode);
  const edges = subtasks.flatMap((unit) => unit.blockedBy.map((blockedBy) => ({
    from: blockedBy,
    to: unit.id,
    type: "blocks",
  })));

  return {
    task: mockTaskToRecord(task),
    graph: {
      task_id: task.id,
      nodes,
      edges,
    },
    messages: mockMessages.map((message, index) => ({
      id: `demo-message-${index + 1}`,
      workspace_id: task.workspace_id,
      task_id: task.id,
      role: message.from.toLowerCase() === "user" ? "user" : "assistant",
      content: message.text,
      metadata: {
        target: message.target,
        gate: message.tag,
        source: "demo",
      },
      created_at: now,
    })),
    approval_gates: mockApprovalGates.map((gate) => ({
      id: gate.id,
      workspace_id: task.workspace_id,
      task_id: task.id,
      name: gate.name,
      status: gate.status,
      metadata: {
        requires_human: gate.status === "waiting_human" || gate.status === "blocked",
      },
      created_at: now,
      updated_at: now,
    })),
    events: mockEvents.map((event, index) => ({
      id: `demo-event-${index + 1}`,
      workspace_id: task.workspace_id,
      task_id: task.id,
      event_type: event.event,
      payload: {
        severity: event.severity,
        message: event.object,
        source: event.source,
      },
      created_at: `${now.slice(0, 10)}T${event.time}:00.000Z`,
    })),
    dispatches: [],
    evidence: [],
    reviews: [],
    handoff: null,
  };
}

function createDemoOperations(): OperationalViewsSnapshot {
  const totalTasks = tasks.length;
  const activeTasks = tasks.filter((task) => task.status === "in_progress").length;
  const doneTasks = tasks.filter((task) => task.status === "complete").length;
  const nodes = subtasks.map(subtaskToGraphNode);
  const edges = subtasks.flatMap((unit) => unit.blockedBy.map((blockedBy) => ({
    from: blockedBy,
    to: unit.id,
    type: "blocks",
  })));

  return {
    workspace_id: workspace.id,
    history: mockEvents.map((event, index) => ({
      id: `history-${index + 1}`,
      workspace_id: workspace.id,
      task_id: index < 3 ? tasks[0]?.id ?? null : tasks[1]?.id ?? null,
      event_type: event.event,
      payload: {
        severity: event.severity,
        message: event.object,
        source: event.source,
      },
      created_at: `${new Date().toISOString().slice(0, 10)}T${event.time}:00.000Z`,
    })),
    lifecycle: roles.map((role) => ({
      key: role.name.toLowerCase(),
      name: role.name,
      purpose: role.function,
      description: role.function,
      state: role.state,
      event_count: mockEvents.filter((event) => event.source === role.name).length,
    })),
    diagrams: [
      {
        id: "diagram-task-studio",
        kind: "dependency_graph",
        title: "Task studio dependency graph",
        task_id: tasks[0]?.id,
        nodes,
        edges,
        summary: "Task packet, dependency graph, and selected unit flow.",
        updated_at: new Date().toISOString(),
      },
      {
        id: "diagram-lifecycle",
        kind: "agent_lifecycle",
        title: "Agent lifecycle",
        summary: "Role flow, review loop, and handoff progression.",
        updated_at: new Date().toISOString(),
      },
    ],
    usage: {
      tasks: { total: totalTasks, active: activeTasks, done: doneTasks, by_status: { in_progress: activeTasks, complete: doneTasks } },
      subtasks: {
        total: subtasks.length,
        by_status: subtasks.reduce<Record<string, number>>((acc, unit) => {
          acc[unit.state] = (acc[unit.state] ?? 0) + 1;
          return acc;
        }, {}),
      },
      events: { total: mockEvents.length, by_type: mockEvents.reduce<Record<string, number>>((acc, event) => {
        acc[event.severity] = (acc[event.severity] ?? 0) + 1;
        return acc;
      }, {}) },
      messages: { total: mockMessages.length, by_role: mockMessages.reduce<Record<string, number>>((acc, message) => {
        acc[message.from] = (acc[message.from] ?? 0) + 1;
        return acc;
      }, {}) },
      repositories: { total: workspace.repos.length },
      dispatches: { total: 0, by_status: {} },
      evidence: { total: 2, by_type: { doc: 1, plan: 1 } },
      reviews: { total: 1, by_status: { pending: 1 } },
      handoffs: { total: 0 },
      providers: {
        total: roles.length,
        online: roles.filter((role) => role.state === "active" || role.state === "live").length,
        by_health: {
          active: roles.filter((role) => role.state === "active").length,
          live: roles.filter((role) => role.state === "live").length,
          idle: roles.filter((role) => role.state === "idle").length,
          queued: roles.filter((role) => role.state === "queued").length,
          waiting: roles.filter((role) => role.state === "waiting").length,
        },
      },
    },
  };
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

function budgetTone(state?: string | null): "healthy" | "warning" | "blocked" | "draft" {
  if (state === "exhausted") return "blocked";
  if (state === "near_limit" || state === "warning") return "warning";
  if (state === "ok") return "healthy";
  return "draft";
}

function snapshotToPanelEntries(
  snapshot: TaskStudioSnapshot,
  taskId: string,
  workspaceId: string,
): TaskPanelEntry[] {
  const messages = snapshot.messages.map((message) => ({
    id: message.id,
    kind: message.role === "user" ? "human_message" : "agent_update",
    source: message.role,
    target: typeof message.metadata.target === "string" ? message.metadata.target : null,
    summary: message.content,
    created_at: message.created_at,
    metadata: message.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  } satisfies TaskPanelEntry));

  const events = snapshot.events.map((event) => {
    const payload = event.payload;
    const kind: TaskPanelEntry["kind"] =
      event.event_type === "task.blocked" ? "blocked" :
      event.event_type === "task.unblocked" ? "unblocked" :
      event.event_type === "task.completed" ? "completion" :
      event.event_type === "approval.requested" || event.event_type === "approval.recorded" ? "review" :
      event.event_type === "subtask.dispatched" ? "claimed" :
      event.event_type === "subtask.scheduled" ? "claimed" :
      event.event_type === "subtask.unblocked" ? "unblocked" :
      event.event_type === "subtask.transitioned" && payload.status === "blocked" ? "blocked" :
      event.event_type === "subtask.transitioned" && payload.status === "complete" ? "completion" :
      event.event_type === "subtask.transitioned" && (payload.status === "review" || payload.status === "waiting_human") ? "review" :
      event.event_type === "subtask.transitioned" && payload.status === "in_progress" ? "in_progress" :
      event.event_type === "task.draft_created" || event.event_type === "task.chat_created" ? "system_note" :
      "system_note";
    const source = typeof payload.actor === "string"
      ? payload.actor
      : typeof payload.agent === "string"
        ? payload.agent
        : typeof payload.provider === "string"
          ? payload.provider
          : typeof payload.name === "string"
            ? payload.name
            : event.event_type;
    const target = typeof payload.object_id === "string"
      ? payload.object_id
      : typeof payload.subtask_id === "string"
        ? payload.subtask_id
        : typeof payload.dispatch_id === "string"
          ? payload.dispatch_id
          : typeof payload.status === "string"
            ? payload.status
            : typeof payload.name === "string"
              ? payload.name
              : null;
    const summary =
      event.event_type === "task.blocked" ? `Task blocked: ${String(payload.reason ?? payload.message ?? "blocked")}` :
      event.event_type === "task.unblocked" ? "Task unblocked" :
      event.event_type === "task.completed" ? "Task completed" :
      event.event_type === "approval.requested" ? `Approval requested for ${String(payload.name ?? "gate")}` :
      event.event_type === "approval.recorded" ? `Approval recorded: ${String(payload.status ?? "updated")}` :
      event.event_type === "subtask.scheduled" ? `${String(payload.role ?? payload.provider ?? "subtask")} scheduled` :
      event.event_type === "subtask.dispatched" ? `Dispatch recorded for ${String(payload.object_id ?? "subtask")}` :
      event.event_type === "subtask.unblocked" ? `Unblocked ${String(payload.object_id ?? "subtask")}` :
      event.event_type === "subtask.transitioned" ? `${String(payload.actor ?? "Subtask")} → ${String(payload.status ?? "updated")}` :
      event.event_type === "task.draft_created" ? "Task draft created" :
      event.event_type === "task.chat_created" ? "Task inception chat created a draft" :
      event.event_type === "review.completed" ? "Review completed" :
      event.event_type === "review.rejected" ? "Review rejected" :
      event.event_type.replace(".", " ");
    return {
      id: event.id,
      kind,
      source,
      target,
      summary,
      created_at: event.created_at,
      metadata: payload,
      task_id: taskId,
      workspace_id: workspaceId,
    } satisfies TaskPanelEntry;
  });

  const gates = snapshot.approval_gates.map((gate) => ({
    id: gate.id,
    kind: "review" as const,
    source: gate.name,
    target: gate.status,
    summary: `${gate.name} gate ${gate.status}`,
    created_at: gate.created_at,
    metadata: gate.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const dispatches = snapshot.dispatches.map((dispatch) => ({
    id: dispatch.id,
    kind: dispatch.status === "failed" ? "blocked" : dispatch.status === "review" ? "review" : dispatch.status === "in_progress" ? "in_progress" : "claimed",
    source: dispatch.agent_name,
    target: typeof dispatch.metadata.subtask_id === "string" ? dispatch.metadata.subtask_id : null,
    summary: `${dispatch.agent_name} dispatch ${dispatch.status}`,
    created_at: dispatch.created_at,
    metadata: dispatch.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  } satisfies TaskPanelEntry));

  const evidence = snapshot.evidence.map((item) => ({
    id: item.id,
    kind: "evidence" as const,
    source: item.artifact_type,
    target: item.uri,
    summary: `${item.artifact_type} evidence attached`,
    created_at: item.created_at,
    metadata: item.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const reviews = snapshot.reviews.map((review) => ({
    id: review.id,
    kind: "review" as const,
    source: "review",
    target: review.status,
    summary: review.summary ?? `Review ${review.status}`,
    created_at: review.created_at,
    metadata: review.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }));

  const handoff = snapshot.handoff ? [{
    id: snapshot.handoff.id,
    kind: "handoff" as const,
    source: snapshot.handoff.from_agent ?? "handoff",
    target: snapshot.handoff.to_agent,
    summary: snapshot.handoff.summary,
    created_at: snapshot.handoff.created_at,
    metadata: snapshot.handoff.metadata,
    task_id: taskId,
    workspace_id: workspaceId,
  }] : [];

  return [...messages, ...events, ...gates, ...dispatches, ...evidence, ...reviews, ...handoff]
    .sort((a, b) => (a.created_at === b.created_at ? a.id.localeCompare(b.id) : a.created_at.localeCompare(b.created_at)));
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function historySummary(event: LifecycleEventRecord): string {
  const payload = event.payload as Record<string, unknown>;
  return String(payload.message ?? payload.action ?? payload.summary ?? "workspace event");
}

function repositoryActionLabel(mode: string | undefined): string {
  if (!mode || mode === "no_action") {
    return "No action (default)";
  }
  if (mode === "prepare_patch") return "Prepare patch";
  if (mode === "commit") return "Commit (opt-in)";
  if (mode === "draft_pr") return "Draft PR (opt-in)";
  if (mode === "ready_pr") return "Ready PR (opt-in)";
  return mode.replace(/_/g, " ");
}

function githubIssueReference(metadata: TaskMetadata): string | null {
  const issue = metadata.github_issue;
  if (!issue) return null;
  if (typeof issue.reference === "string" && issue.reference.trim()) {
    return issue.reference;
  }
  if (typeof issue.full_name === "string" && issue.full_name.trim() && typeof issue.number === "number") {
    return `${issue.full_name}#${issue.number}`;
  }
  if (issue.repository && typeof issue.repository === "object") {
    const repository = issue.repository as Record<string, unknown>;
    const fullName = typeof repository.full_name === "string" ? repository.full_name : null;
    if (fullName && typeof issue.number === "number") {
      return `${fullName}#${issue.number}`;
    }
    const workspaceRepositoryName = typeof repository.workspace_repository_name === "string"
      ? repository.workspace_repository_name
      : null;
    if (workspaceRepositoryName && typeof issue.number === "number") {
      return `${workspaceRepositoryName} issue #${issue.number}`;
    }
  }
  if (typeof issue.number === "number") {
    return `GitHub issue #${issue.number}`;
  }
  return null;
}

function nextPendingGate(approvalItems: TaskStudioSnapshot["approval_gates"]) {
  return approvalItems.find((gate) => gate.status === "waiting_human")
    ?? approvalItems.find((gate) => gate.status === "pending")
    ?? null;
}

function deriveNextAction(
  task: TaskDashboardItem | null,
  approvalItems: TaskStudioSnapshot["approval_gates"],
  latestReview: ReviewRunRecord | null,
  handoffReady: boolean,
): { label: string; tone: string; detail: string } {
  const pendingGate = nextPendingGate(approvalItems);
  if (task?.blocked_count) {
    return {
      label: "Unblock execution",
      tone: "blocked",
      detail: `${task.blocked_count} unit${task.blocked_count === 1 ? "" : "s"} are blocked. Review dependencies or provider posture before dispatch continues.`,
    };
  }
  if (pendingGate) {
    const requiresHuman = pendingGate.metadata?.requires_human === true || pendingGate.status === "waiting_human";
    return {
      label: `Approve ${pendingGate.name}`,
      tone: requiresHuman ? "warning" : "active",
      detail: requiresHuman
        ? `${pendingGate.name} is waiting on a human decision before Sarathi can continue.`
        : `${pendingGate.name} is the next workflow gate.`,
    };
  }
  if (latestReview && latestReview.status === "approved" && !handoffReady) {
    return {
      label: "Create handoff",
      tone: "active",
      detail: "Execution and review are in a good state. Capture the governed handoff next.",
    };
  }
  if (task?.status === "in_progress") {
    return {
      label: "Monitor execution",
      tone: "active",
      detail: "Units are in flight. Watch the task panel and evidence feed for failures or review triggers.",
    };
  }
  return {
    label: "Schedule ready units",
    tone: "warning",
    detail: "Sarathi is ready for the next dispatch cycle.",
  };
}

export default function ProjectDetail({
  workspaceId,
  projectId,
  liveTick = 0,
  selectedTaskId,
  setSelectedTaskId,
  setRoute,
}: Props) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [resolvedWorkspaceId, setResolvedWorkspaceId] = useState<string | null>(
    workspaceId ?? (!apiConfigured ? workspace.id : null),
  );
  const [taskItems, setTaskItems] = useState<TaskDashboardItem[]>(mockTasksToDashboardItems());
  const [selectedTaskIdState, setSelectedTaskIdState] = useState<string | null>(selectedTaskId ?? null);
  const [selectedTab, setSelectedTab] = useState<ProjectTab>("studio");
  const [snapshot, setSnapshot] = useState<TaskStudioSnapshot | null>(null);
  const [panelSnapshot, setPanelSnapshot] = useState<TaskPanelSnapshot | null>(null);
  const [taskCheckpoint, setTaskCheckpoint] = useState<CheckpointCapsuleRecord | null>(null);
  const [taskCheckpointHistory, setTaskCheckpointHistory] = useState<CheckpointCapsuleRecord[]>([]);
  const [operations, setOperations] = useState<OperationalViewsSnapshot | null>(null);
  const [taskLoadStatus, setTaskLoadStatus] = useState(apiConfigured ? "Loading task studio." : "Demo task studio.");
  const [panelLoadStatus, setPanelLoadStatus] = useState(apiConfigured ? "Loading task panel." : "Demo task panel.");
  const [opsLoadStatus, setOpsLoadStatus] = useState(apiConfigured ? "Loading lifecycle views." : "Demo lifecycle views.");
  const [actionStatus, setActionStatus] = useState("");
  const [checkpointExpanded, setCheckpointExpanded] = useState(false);

  useEffect(() => {
    if (workspaceId) {
      setResolvedWorkspaceId(workspaceId);
      return;
    }
    if (!apiConfigured) {
      setResolvedWorkspaceId(workspace.id);
      return;
    }
    let cancelled = false;
    async function resolve() {
      try {
        const ws = await ensureWorkspace(workspace.name, "/Users/sweethome/Work/Skills/Sarathi", {
          source: "desktop-ui",
          display_id: workspace.id,
        });
        if (!cancelled) setResolvedWorkspaceId(ws.id);
      } catch {
        if (!cancelled) setResolvedWorkspaceId(workspace.id);
      }
    }
    void resolve();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (selectedTaskId) {
      setSelectedTaskIdState(selectedTaskId);
    }
  }, [selectedTaskId]);

  async function fetchTaskItems(workspaceKey: string): Promise<{
    items: TaskDashboardItem[];
    fallbackReason: "demo" | "empty" | "error" | null;
    fromApi: boolean;
  }> {
    if (!apiConfigured) {
      return { items: mockTasksToDashboardItems(), fallbackReason: "demo", fromApi: false };
    }
    try {
      const list = await listTaskDashboard(workspaceKey, { projectId });
      return {
        items: list,
        fallbackReason: list.length === 0 ? "empty" : null,
        fromApi: true,
      };
    } catch {
      return { items: [], fallbackReason: "error", fromApi: true };
    }
  }

  async function reloadTaskItems(workspaceKey: string): Promise<TaskDashboardItem[]> {
    const next = await fetchTaskItems(workspaceKey);
    setTaskItems(next.items);
    if (!next.fromApi || next.fallbackReason === "demo") {
      setTaskLoadStatus("Demo task studio.");
    } else if (next.fallbackReason === "empty") {
      setTaskLoadStatus("No persisted tasks yet.");
    } else if (next.fallbackReason === "error") {
      setTaskLoadStatus("Task load failed.");
    } else {
      setTaskLoadStatus(`${next.items.length} persisted tasks loaded.`);
    }
    return next.items;
  }

  useEffect(() => {
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!workspaceKey) return;
    let cancelled = false;
    async function loadTasks() {
      const next = await fetchTaskItems(workspaceKey);
      if (!cancelled) {
        setTaskItems(next.items);
        if (!next.fromApi || next.fallbackReason === "demo") {
          setTaskLoadStatus("Demo task studio.");
        } else if (next.fallbackReason === "empty") {
          setTaskLoadStatus("No persisted tasks yet.");
        } else if (next.fallbackReason === "error") {
          setTaskLoadStatus("Task load failed.");
        } else {
          setTaskLoadStatus(`${next.items.length} persisted tasks loaded.`);
        }
      }
    }
    void loadTasks();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, projectId, resolvedWorkspaceId, liveTick, selectedTaskId]);

  const selectedTask = useMemo(() => {
    if (!taskItems.length) return null;
    if (selectedTaskIdState) {
      const found = taskItems.find((item) => item.id === selectedTaskIdState);
      if (found) return found;
      return null;
    }
    return taskItems[0];
  }, [selectedTaskIdState, taskItems]);

  useEffect(() => {
    if (!selectedTask?.id) return;
    if (selectedTaskIdState !== selectedTask.id) {
      setSelectedTaskIdState(selectedTask.id);
      setSelectedTaskId?.(selectedTask.id);
    }
  }, [selectedTask?.id, selectedTaskIdState, setSelectedTaskId]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId;
    if (!task || !workspaceKey) {
      setSnapshot(null);
      return;
    }
    if (!apiConfigured) {
      setSnapshot(createDemoSnapshot(task));
      return;
    }
    let cancelled = false;
    async function loadStudio() {
      try {
        const next = await getTaskStudio(task.id);
        if (!cancelled) {
          setSnapshot(next);
          setTaskLoadStatus(`${next.graph.nodes.length} units, ${next.messages.length} messages, ${next.approval_gates.length} gates loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setSnapshot(createDemoSnapshot(task));
          setTaskLoadStatus("Studio load failed. Using demo snapshot.");
        }
      }
    }
    void loadStudio();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, selectedTask?.id, liveTick]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!task || !workspaceKey) {
      setPanelSnapshot(null);
      return;
    }
    if (!apiConfigured) {
      setPanelSnapshot({ task_id: task.id, entries: snapshotToPanelEntries(createDemoSnapshot(task), task.id, workspaceKey) });
      setPanelLoadStatus("Demo task panel.");
      return;
    }
    let cancelled = false;
    async function loadPanel() {
      try {
        const next = await getTaskPanel(task.id);
        if (!cancelled) {
          setPanelSnapshot(next);
          setPanelLoadStatus(`${next.entries.length} task panel entries loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setPanelSnapshot({ task_id: task.id, entries: snapshotToPanelEntries(createDemoSnapshot(task), task.id, workspaceKey) });
          setPanelLoadStatus("Task panel load failed. Using demo panel.");
        }
      }
    }
    void loadPanel();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, selectedTask?.id, liveTick]);

  useEffect(() => {
    const task = selectedTask as TaskDashboardItem;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!task || !workspaceKey) {
      setTaskCheckpoint(null);
      setTaskCheckpointHistory([]);
      return;
    }
    if (!apiConfigured) {
      const demoCheckpoint = task.status === "done"
        ? createDemoCheckpoint(task, selectedTask?.title ?? "Task studio", workspaceKey, projectId ?? null)
        : null;
      setTaskCheckpoint(demoCheckpoint);
      setTaskCheckpointHistory(demoCheckpoint ? [demoCheckpoint] : []);
      return;
    }
    let cancelled = false;
    setTaskCheckpoint(null);
    setTaskCheckpointHistory([]);
    async function loadCheckpoint() {
      try {
        const [next, history] = await Promise.all([
          getTaskCheckpoint(task.id),
          listTaskCheckpoints(task.id),
        ]);
        if (!cancelled) {
          setTaskCheckpoint(next);
          setTaskCheckpointHistory(history);
        }
      } catch {
        if (!cancelled) {
          setTaskCheckpoint(null);
          setTaskCheckpointHistory([]);
        }
      }
    }
    void loadCheckpoint();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, projectId, resolvedWorkspaceId, selectedTask?.id, selectedTask?.title]);

  useEffect(() => {
    const workspaceKey = resolvedWorkspaceId;
    if (!workspaceKey) return;
    if (!apiConfigured) {
      setOperations(createDemoOperations());
      setOpsLoadStatus("Demo lifecycle views.");
      return;
    }
    let cancelled = false;
    async function loadOps() {
      try {
        const next = await getWorkspaceOperationalViews(workspaceKey!);
        if (!cancelled) {
          setOperations(next);
          setOpsLoadStatus(`${next.history.length} events, ${next.diagrams.length} diagrams, ${next.usage.tasks.total} tasks loaded from SQLite.`);
        }
      } catch {
        if (!cancelled) {
          setOperations(createDemoOperations());
          setOpsLoadStatus("Lifecycle views load failed. Using demo data.");
        }
      }
    }
    void loadOps();
    return () => {
      cancelled = true;
    };
  }, [apiConfigured, resolvedWorkspaceId, liveTick]);

  const liveSnapshot = snapshot ?? (selectedTask ? createDemoSnapshot(selectedTask) : null);
  const liveOps = operations ?? createDemoOperations();

  const graphNodes = liveSnapshot?.graph.nodes ?? [];
  const graphEdges = liveSnapshot?.graph.edges ?? [];
  const taskMessages = liveSnapshot?.messages ?? [];
  const approvalItems = liveSnapshot?.approval_gates ?? [];
  const taskReviews = liveSnapshot?.reviews ?? [];
  const taskHandoff = liveSnapshot?.handoff ?? null;
  const latestReview = taskReviews.length > 0 ? taskReviews[taskReviews.length - 1] : null;
  const taskMetadata = (liveSnapshot?.task.metadata ?? {}) as TaskMetadata;
  const repositoryPreference = taskMetadata.repository_action_preference ?? {
    scope: "default",
    mode: "no_action",
    allowed_modes: ["no_action"],
  };
  const githubIssueReferenceText = githubIssueReference(taskMetadata);
  const panelEntries = panelSnapshot?.entries ?? (selectedTask && resolvedWorkspaceId
    ? snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, resolvedWorkspaceId)
    : []);
  const selectedPhase = liveSnapshot?.task.metadata.phase ?? selectedTask?.phase ?? "Build";
  const selectedTaskTitle = liveSnapshot?.task.title ?? selectedTask?.title ?? "Task studio";
  const pendingGate = nextPendingGate(approvalItems);
  const nextAction = deriveNextAction(selectedTask ?? null, approvalItems, latestReview, Boolean(taskHandoff));

  async function reloadStudio() {
    if (!selectedTask) return;
    if (!apiConfigured || !resolvedWorkspaceId) {
      setSnapshot(createDemoSnapshot(selectedTask));
      return;
    }
    try {
      const next = await getTaskStudio(selectedTask.id);
      setSnapshot(next);
      setTaskLoadStatus(`${next.graph.nodes.length} units, ${next.messages.length} messages, ${next.approval_gates.length} gates loaded from SQLite.`);
    } catch {
      setSnapshot(createDemoSnapshot(selectedTask));
      setTaskLoadStatus("Studio refresh failed. Using demo snapshot.");
    }
  }

  async function reloadPanel() {
    if (!selectedTask) return;
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!apiConfigured || !resolvedWorkspaceId) {
      setPanelSnapshot({ task_id: selectedTask.id, entries: snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, workspaceKey) });
      return;
    }
    try {
      const next = await getTaskPanel(selectedTask.id);
      setPanelSnapshot(next);
      setPanelLoadStatus(`${next.entries.length} task panel entries loaded from SQLite.`);
    } catch {
      setPanelSnapshot({ task_id: selectedTask.id, entries: snapshotToPanelEntries(createDemoSnapshot(selectedTask), selectedTask.id, workspaceKey) });
      setPanelLoadStatus("Task panel refresh failed. Using demo panel.");
    }
  }

  async function handleSchedule() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to schedule units.");
      return;
    }
    try {
      setActionStatus("Scheduling ready units through Sutra.");
      const result = await scheduleTask(selectedTask.id);
      setActionStatus(`${result.scheduled.length} ready units scheduled; ${result.blocked.length} remain blocked.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Schedule failed.");
    }
  }

  async function handleReview() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to run reviews.");
      return;
    }
    try {
      setActionStatus("Running review.");
      const result = await runTaskReview(selectedTask.id, "code");
      setActionStatus(`Review ${result.review.status}; ${result.completed_subtasks.length} units completed.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Review failed.");
    }
  }

  async function handleHandoff() {
    if (!selectedTask || !apiConfigured) {
      setActionStatus("Connect the local service to create a handoff.");
      return;
    }
    try {
      setActionStatus("Creating handoff.");
      const result = await createTaskHandoff(selectedTask.id);
      setActionStatus(`Handoff ${result.handoff.id.slice(0, 8)} created.`);
      await reloadStudio();
      await reloadPanel();
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Handoff failed.");
    }
  }

  async function handleStartNewSession() {
    if (!selectedTask || !taskCheckpoint) {
      setActionStatus("No checkpoint is available for this task.");
      return;
    }
    const workspaceKey = resolvedWorkspaceId ?? workspace.id;
    if (!apiConfigured) {
      const restartedTask = {
        id: `restart-${selectedTask.id}-${Date.now().toString(36)}`,
        workspace_id: workspaceKey,
        title: `Resume: ${selectedTask.title}`,
        status: "prd_pending",
        phase: "Plan",
        approval_state: "draft",
        graph_state: "ready",
        next_gate: "Resume from checkpoint",
        node_count: 1,
        blocked_count: 0,
        roles: [],
        providers: [],
        updated_at: new Date().toISOString(),
      } satisfies TaskDashboardItem;
      setTaskItems((current) => [restartedTask, ...current.filter((item) => item.id !== restartedTask.id)]);
      setSnapshot(null);
      setPanelSnapshot(null);
      setTaskCheckpoint(null);
      setSelectedTaskIdState(restartedTask.id);
      setSelectedTaskId?.(restartedTask.id);
      setSelectedTab("studio");
      setRoute?.("project");
      setActionStatus("Demo session restarted from checkpoint.");
      return;
    }
    try {
      setActionStatus("Starting a new session from checkpoint.");
      const result = await restartTaskFromCheckpoint(selectedTask.id);
      const refreshedTasks = await reloadTaskItems(workspaceKey);
      const restartTask = refreshedTasks.find((item) => item.id === result.task.id) ?? taskRecordToDashboardItem(result.task);
      if (!refreshedTasks.some((item) => item.id === result.task.id)) {
        setTaskItems([restartTask, ...refreshedTasks.filter((item) => item.id !== restartTask.id)]);
      }
      setSnapshot(null);
      setPanelSnapshot(null);
      setTaskCheckpoint(null);
      setSelectedTaskIdState(restartTask.id);
      setSelectedTaskId?.(restartTask.id);
      setSelectedTab("studio");
      setRoute?.("project");
      setActionStatus(`Started new session from checkpoint ${result.checkpoint.id.slice(0, 8)}.`);
    } catch (error) {
      setActionStatus(error instanceof Error ? error.message : "Checkpoint restart failed.");
    }
  }

  function handleOpenSourceTask() {
    if (!taskCheckpoint) {
      setActionStatus("No checkpoint is available for this task.");
      return;
    }
    setSnapshot(null);
    setPanelSnapshot(null);
    setTaskCheckpoint(null);
    setSelectedTaskIdState(taskCheckpoint.source_task_id);
    setSelectedTaskId?.(taskCheckpoint.source_task_id);
    setSelectedTab("studio");
    setRoute?.("project");
    setActionStatus(`Opened source task ${taskCheckpoint.source_task_id}.`);
  }

  const lifecycleRows = liveOps.lifecycle ?? [];
  const historyRows = liveOps.history ?? [];
  const usage = liveOps.usage;
  const budget = usage?.budget ?? null;
  const budgetLabel = budget
    ? budget.budget_limit != null
      ? `${formatTokenCount(budget.total_tokens)} / ${formatTokenCount(budget.budget_limit)}`
      : `${formatTokenCount(budget.total_tokens)} total`
    : "n/a";

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <div style={styles.eyebrow}>Workspace / {workspaceId ?? workspace.id}</div>
          <h1 style={styles.title}>{selectedTaskTitle}</h1>
          <p style={styles.subtitle}>Task studio: dependency graph, selected unit packet, lifecycle gates, and task-scoped conversation in one place.</p>
        </div>
        <div style={styles.headerActions}>
          <button style={styles.secondaryButton} onClick={() => setRoute?.("dashboard")}>Back to Dashboard</button>
          <button style={styles.primaryButton} onClick={() => setRoute?.("workspace")}>Workspaces</button>
        </div>
      </div>

      <section style={styles.cockpitStrip}>
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Task</div>
          <div style={styles.cockpitValue}>{selectedTask?.status ?? "pending"}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Phase</div>
          <div style={styles.cockpitValue}>{selectedPhase}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Next Action</div>
          <Pill tone={nextAction.tone}>{nextAction.label}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Blocked</div>
          <Pill tone={selectedTask?.blocked_count ? "blocked" : "healthy"}>{selectedTask?.blocked_count ?? 0}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Checkpoint</div>
          <Pill tone={taskCheckpoint ? "healthy" : "draft"}>{taskCheckpoint ? "Ready" : "None"}</Pill>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Units</div>
          <div style={styles.cockpitValue}>{graphNodes.length}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Messages</div>
          <div style={styles.cockpitValue}>{taskMessages.length}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Gates</div>
          <div style={styles.cockpitValue}>{approvalItems.length}</div>
        </div>
        <div style={styles.cockpitDivider} />
        <div style={styles.cockpitSection}>
          <div style={styles.cockpitLabel}>Budget</div>
          <Pill tone={budgetTone(budget?.budget_state)}>{budgetLabel}</Pill>
        </div>
      </section>

      <section style={styles.statusStrip}>
        <Pill tone={apiConfigured ? "healthy" : "warning"}>Workspace {apiConfigured ? "live" : "demo"}</Pill>
        <Pill tone={snapshot ? "healthy" : "warning"}>{taskLoadStatus}</Pill>
        <Pill tone={panelSnapshot ? "healthy" : "warning"}>{panelLoadStatus}</Pill>
        <Pill tone={operations ? "healthy" : "warning"}>{opsLoadStatus}</Pill>
        <Pill tone="active">{taskItems.length} tasks</Pill>
        <Pill tone={selectedTask?.status === "done" ? "healthy" : "warning"}>{selectedTask?.status ?? "pending"}</Pill>
      </section>

      <section style={styles.taskRail}>
        {taskItems.map((task) => (
          <button
            key={task.id}
            style={{ ...styles.taskCard, ...(task.id === selectedTask?.id ? styles.taskCardActive : {}) }}
            onClick={() => {
              setSelectedTaskIdState(task.id);
              setSelectedTaskId?.(task.id);
              setSelectedTab("studio");
            }}
          >
            <div style={styles.taskCardRow}>
              <span style={styles.taskCardId}>{task.id.split("-")[0]}</span>
              <Pill tone={task.status === "done" ? "healthy" : task.status === "in_progress" ? "active" : "warning"}>{task.status}</Pill>
            </div>
            <div style={styles.taskCardTitleRow}>
              <span style={styles.taskCardTitle}>{task.title.length > 32 ? task.title.slice(0, 32) + "…" : task.title}</span>
            </div>
            <div style={styles.taskCardMetaRow}>
              <span style={styles.taskCardMeta}>{task.phase} · {task.node_count} units</span>
            </div>
          </button>
        ))}
      </section>

      <section style={styles.tabBar}>
        {(["studio", "lifecycle", "history", "usage"] as ProjectTab[]).map((tab) => (
          <button
            key={tab}
            style={{ ...styles.tabButton, ...(selectedTab === tab ? styles.tabButtonActive : {}) }}
            onClick={() => setSelectedTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </section>

      {selectedTab === "studio" && (
        <div style={styles.studioGrid}>
          <section style={styles.leftColumn}>
            <div style={styles.panel}>
              <PanelTitle title="Dependency graph" badge={selectedTask?.approval_state ?? "draft"} />
              <div style={styles.metaRow}>
                <Field label="Phase" value={selectedPhase} />
                <Field label="Task" value={selectedTask ? `${selectedTask.id} / ${selectedTask.title}` : "No task selected"} />
                <Field label="Graph" value={`${graphNodes.length} nodes / ${graphEdges.length} edges`} />
              </div>
              <UnitGraph
                nodes={graphNodes}
                edges={graphEdges}
                taskPhase={selectedPhase}
                taskId={selectedTask?.id ?? null}
                onAction={() => {
                  void reloadStudio();
                }}
              />
            </div>

            <div style={styles.panel}>
              <PanelTitle title="Task actions" badge="Sutra" />
              <Card style={styles.summaryCard}>
                <strong>Current posture</strong>
                <Pill tone={nextAction.tone}>{nextAction.label}</Pill>
                <p>{nextAction.detail}</p>
                <small>
                  Phase: {selectedPhase}
                  {" / "}
                  Gate: {pendingGate?.name ?? "clear"}
                  {" / "}
                  Review: {latestReview?.status ?? "not run"}
                </small>
              </Card>
              <div style={styles.actionRow}>
                <button style={styles.secondaryButton} onClick={() => void handleSchedule()} disabled={!selectedTask || !apiConfigured}>Schedule ready units</button>
                <button style={styles.secondaryButton} onClick={() => void handleReview()} disabled={!selectedTask || !apiConfigured}>Run review</button>
                <button style={styles.secondaryButton} onClick={() => void handleHandoff()} disabled={!selectedTask || !apiConfigured}>Create handoff</button>
              </div>
              <p style={styles.helperText}>{actionStatus || "Use Sarathi's lifecycle actions to move the selected task forward."}</p>
              {latestReview ? (
                <Card style={styles.summaryCard}>
                  <strong>Latest review</strong>
                  <Pill tone={stateTone(latestReview.status)}>{latestReview.status}</Pill>
                  <p>{latestReview.summary ?? "Review result captured from SQLite."}</p>
                  <small>{latestReview.created_at}</small>
                </Card>
              ) : (
                <Card style={styles.summaryCard}>
                  <strong>Latest review</strong>
                  <p>No review has been run for this task yet.</p>
                </Card>
              )}
              {taskHandoff ? (
                <Card style={styles.summaryCard}>
                  <strong>Handoff</strong>
                  <Pill tone="active">recorded</Pill>
                  <p>{taskHandoff.summary}</p>
                  <small>{taskHandoff.from_agent ?? "from"} → {taskHandoff.to_agent ?? "to"}</small>
                </Card>
              ) : (
                <Card style={styles.summaryCard}>
                  <strong>Handoff</strong>
                  <p>No handoff has been recorded yet for this task.</p>
                </Card>
              )}
              {taskCheckpoint ? (
                <Card style={styles.summaryCard}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <strong>Checkpoint</strong>
                      <Pill tone="healthy">Ready</Pill>
                    </div>
                    <button
                      style={{ padding: "4px 8px", height: "auto", fontSize: "0.7rem" }}
                      onClick={() => setCheckpointExpanded(!checkpointExpanded)}
                    >
                      {checkpointExpanded ? "Hide" : "Show"}
                    </button>
                  </div>
                  {checkpointExpanded && (
                    <>
                      <p>{taskCheckpoint.summary}</p>
                      <small>{taskCheckpoint.next_start_point}</small>
                      <div style={{ ...styles.actionRow, marginTop: 12 }}>
                        <button style={styles.primaryButton} onClick={() => void handleStartNewSession()} disabled={!selectedTask || !taskCheckpoint}>
                          Start new session
                        </button>
                        <button style={styles.secondaryButton} onClick={() => handleOpenSourceTask()} disabled={!taskCheckpoint}>
                          Open source
                        </button>
                      </div>
                    </>
                  )}
                </Card>
              ) : null}
              {taskCheckpointHistory.length > 1 && checkpointExpanded && (
                <Card style={styles.summaryCard}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <strong>Checkpoint history</strong>
                    <Pill tone="active">{taskCheckpointHistory.length}</Pill>
                  </div>
                  <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                    {taskCheckpointHistory.slice(1).map((checkpoint, index) => {
                      return (
                        <div key={checkpoint.id} style={styles.checkpointHistoryItem}>
                          <div style={styles.checkpointHistoryHeader}>
                            <strong>Checkpoint {taskCheckpointHistory.length - index}</strong>
                            <Pill tone="draft">{checkpoint.status}</Pill>
                          </div>
                          <p style={styles.checkpointSummary}>{checkpoint.summary}</p>
                          <div style={styles.checkpointMetaRow}>
                            <span>{new Date(checkpoint.created_at).toLocaleString()}</span>
                            <span>{checkpoint.created_by}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Card>
              )}
              <Card style={styles.summaryCard}>
                <strong>Repository actions</strong>
                <Pill tone={repositoryPreference.mode === "no_action" ? "draft" : "warning"}>
                  {repositoryActionLabel(repositoryPreference.mode)}
                </Pill>
                <p>Commit and PR stay disabled until you explicitly opt in from Settings.</p>
                <small>Scope: {repositoryPreference.scope}</small>
              </Card>
              {githubIssueReferenceText ? (
                <Card style={styles.summaryCard}>
                  <strong>Imported GitHub issue</strong>
                  <Pill tone="active">github issue</Pill>
                  <p>{githubIssueReferenceText}</p>
                  <small>{taskMetadata.github_issue?.url ?? taskMetadata.github_issue?.repository_url ?? "GitHub source recorded in task metadata."}</small>
                  {taskMetadata.github_issue?.repository ? (
                    <small style={{ display: "block", marginTop: 4 }}>
                      Repository: {String((taskMetadata.github_issue.repository as Record<string, unknown>).full_name ?? (taskMetadata.github_issue.repository as Record<string, unknown>).workspace_repository_name ?? taskMetadata.github_issue.name ?? "unknown")}
                    </small>
                  ) : null}
                </Card>
              ) : null}
            </div>
          </section>

          <section style={styles.rightColumn}>
            <div style={styles.panel}>
              <PanelTitle title="Task panel" badge={projectId ? "project" : "task"} />
              <TaskPanelTimeline entries={panelEntries} loading={!panelSnapshot} />
            </div>

            <div style={styles.panel}>
              <PanelTitle title="Evidence and events" badge="ledger" />
              <div style={styles.ledgerGrid}>
                <Card style={styles.summaryCard}><strong>Messages</strong><p>{taskMessages.length} conversation entries</p></Card>
                <Card style={styles.summaryCard}><strong>Approval gates</strong><p>{approvalItems.length} gates tracked</p></Card>
                <Card style={styles.summaryCard}><strong>Events</strong><p>{liveSnapshot?.events.length ?? 0} lifecycle events</p></Card>
                <Card style={styles.summaryCard}><strong>Selected task</strong><p>{selectedTask?.phase ?? "pending"}</p></Card>
              </div>
            </div>
          </section>
        </div>
      )}

      {selectedTab === "lifecycle" && (
        <section style={styles.panel}>
          <PanelTitle title="Agent lifecycle" badge={operations ? "SQLite" : "demo"} />
          <p style={styles.helperText}>Role flow, review loop, and handoff state for this workspace. Sarathi's spine is visible here.</p>
          <table style={styles.table}>
            <thead>
              <tr>
                <th>Role</th>
                <th>Name</th>
                <th>Status</th>
                <th>Signals</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              {lifecycleRows.map((role, index) => (
                <tr key={role.name}>
                  <td style={styles.mono}>{String(index + 1).padStart(2, "0")}</td>
                  <td>{role.name}</td>
                  <td><Pill tone={stateTone(role.state)}>{role.state}</Pill></td>
                  <td style={styles.mono}>{role.event_count}</td>
                  <td style={styles.muted}>{role.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {selectedTab === "history" && (
        <section style={styles.panel}>
          <PanelTitle title="Audit trail" badge={operations ? "SQLite" : "demo"} />
          <p style={styles.helperText}>Chronological record of task, provider, review, and artifact events.</p>
          <div style={styles.timeline}>
            {historyRows.map((event) => {
              const payload = event.payload as Record<string, unknown>;
              const severity = String(payload.severity ?? "info");
              return (
                <div key={event.id} style={styles.timelineItem}>
                  <span style={styles.timelineTime}>{formatTime(event.created_at)}</span>
                  <span style={{ ...styles.timelineDot, background: severity === "warning" ? "#d97706" : severity === "active" ? "#2f6fdf" : "#6b7280" }} />
                  <div style={styles.timelineBody}>
                    <div style={styles.timelineTitle}>{event.event_type}</div>
                    <div style={styles.timelineMeta}>{historySummary(event)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {selectedTab === "usage" && (
        <>
          <div style={styles.metricGrid}>
            <Card style={styles.metricCard}><strong>{usage.tasks.total}</strong><p>Tasks total</p></Card>
            <Card style={styles.metricCard}><strong>{usage.tasks.active}</strong><p>Active tasks</p></Card>
            <Card style={styles.metricCard}><strong>{usage.tasks.done}</strong><p>Completed tasks</p></Card>
            <Card style={styles.metricCard}><strong>{usage.subtasks.total}</strong><p>Graph units</p></Card>
            <Card style={styles.metricCard}><strong>{usage.providers.online}/{usage.providers.total}</strong><p>Providers online</p></Card>
            <Card style={styles.metricCard}><strong>{usage.events.total}</strong><p>Events</p></Card>
            <Card style={styles.metricCard}><strong>{usage.messages.total}</strong><p>Messages</p></Card>
            <Card style={styles.metricCard}><strong>{usage.handoffs.total}</strong><p>Handoffs</p></Card>
          </div>
          <section style={styles.panel}>
            <PanelTitle title="Workspace usage" badge={operations ? "SQLite" : "demo"} />
            <div style={styles.helperText}>
              <p style={{ margin: 0 }}>Repositories: {usage.repositories.total}</p>
              <p style={{ margin: 0 }}>Reviews: {usage.reviews.total}</p>
              <p style={{ margin: 0 }}>Evidence artifacts: {usage.evidence.total}</p>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    paddingBottom: 28,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "flex-start",
  },
  eyebrow: {
    fontSize: "0.76rem",
    color: "var(--faint)",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    marginBottom: 8,
  },
  title: {
    margin: 0,
    fontSize: "2rem",
    lineHeight: 1.1,
    letterSpacing: "-0.03em",
  },
  subtitle: {
    margin: "10px 0 0",
    color: "var(--muted)",
    maxWidth: 760,
  },
  headerActions: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    flexShrink: 0,
  },
  statusStrip: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  cockpitStrip: {
    display: "flex",
    alignItems: "center",
    gap: 0,
    padding: "12px 16px",
    borderRadius: "var(--radius-lg)",
    border: "1px solid var(--border)",
    background: "var(--surface)",
    overflowX: "auto",
  },
  cockpitSection: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 4,
    padding: "4px 12px",
    minWidth: 70,
  },
  cockpitLabel: {
    fontSize: "0.65rem",
    fontWeight: 600,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  cockpitValue: {
    fontSize: "1.1rem",
    fontWeight: 700,
    color: "var(--ink)",
    letterSpacing: "-0.02em",
  },
  cockpitDivider: {
    width: 1,
    height: 32,
    background: "var(--border)",
  },
  taskRail: {
    display: "flex",
    flexDirection: "row",
    gap: 10,
    overflowX: "auto",
    paddingBottom: 8,
    maxWidth: "100%",
  },
  taskCard: {
    textAlign: "left",
    padding: "10px 14px",
    borderRadius: 14,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    boxShadow: "var(--shadow-sm)",
    minWidth: 200,
    maxWidth: 260,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    gap: 4,
    height: "auto",
    whiteSpace: "normal",
    lineHeight: "inherit",
  },
  taskCardActive: {
    borderColor: "var(--accent)",
    background: "var(--active)",
    boxShadow: "0 0 0 1px var(--accent)",
  },
  taskCardRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  taskCardId: {
    fontWeight: 700,
    fontSize: "0.78rem",
    color: "var(--ink)",
    fontFamily: "var(--mono)",
    letterSpacing: "0.02em",
  },
  taskCardStatus: {
    fontSize: "0.66rem",
    padding: "2px 6px",
  },
  taskCardTitleRow: {
    minWidth: 0,
  },
  taskCardTitle: {
    fontWeight: 600,
    color: "var(--ink)",
    fontSize: "0.86rem",
    lineHeight: 1.3,
  },
  taskCardMetaRow: {
    marginTop: 2,
  },
  taskCardMeta: {
    color: "var(--muted)",
    fontSize: "0.72rem",
    lineHeight: 1.3,
  },
  tabBar: {
    display: "inline-flex",
    gap: 6,
    padding: 4,
    borderRadius: 14,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    width: "fit-content",
  },
  tabButton: {
    border: "none",
    background: "transparent",
    padding: "8px 14px",
    borderRadius: 10,
    color: "var(--muted)",
    fontWeight: 600,
  },
  tabButtonActive: {
    background: "var(--accent-a3)",
    color: "var(--ink)",
  },
  studioGrid: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.2fr) minmax(340px, 0.8fr)",
    gap: 16,
    alignItems: "start",
  },
  leftColumn: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0,
  },
  rightColumn: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0,
  },
  panel: {
    borderRadius: 20,
    border: "1px solid var(--border)",
    background: "var(--panel)",
    padding: 18,
    boxShadow: "var(--shadow-sm)",
  },
  metaRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 10,
    marginBottom: 12,
  },
  actionRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  helperText: {
    color: "var(--muted)",
    fontSize: "0.82rem",
    margin: "12px 0 0",
  },
  summaryCard: {
    padding: 14,
    marginTop: 12,
  },
  checkpointHistoryItem: {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: 10,
    background: "var(--canvas)",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  checkpointHistoryHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  checkpointSummary: {
    margin: 0,
  },
  checkpointMetaRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    color: "var(--muted)",
    fontSize: "0.75rem",
  },
  checkpointDecisions: {
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
  },
  checkpointDecisionPill: {
    display: "inline-flex",
    alignItems: "center",
    padding: "3px 8px",
    borderRadius: 999,
    background: "var(--surface-2)",
    color: "var(--ink)",
    fontSize: "0.75rem",
    border: "1px solid var(--border)",
  },
  ledgerGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 10,
  },
  metricGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 12,
  },
  metricCard: {
    padding: 16,
    textAlign: "left",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    marginTop: 8,
  },
  mono: {
    fontFamily: "var(--mono)",
    color: "var(--muted)",
    fontSize: "0.8rem",
    whiteSpace: "nowrap",
  },
  muted: {
    color: "var(--muted)",
  },
  timeline: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    marginTop: 10,
  },
  timelineItem: {
    display: "grid",
    gridTemplateColumns: "72px 10px 1fr",
    gap: 12,
    alignItems: "start",
  },
  timelineTime: {
    color: "var(--faint)",
    fontFamily: "var(--mono)",
    fontSize: "0.75rem",
    paddingTop: 2,
  },
  timelineDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    marginTop: 6,
  },
  timelineBody: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
  },
  timelineTitle: {
    fontWeight: 600,
    color: "var(--ink)",
  },
  timelineMeta: {
    color: "var(--muted)",
    fontSize: "0.82rem",
  },
  secondaryButton: {
    border: "1px solid var(--border)",
    background: "var(--panel)",
    color: "var(--ink)",
    borderRadius: 12,
    height: 36,
    padding: "0 14px",
    fontWeight: 600,
  },
  primaryButton: {
    border: "1px solid var(--accent)",
    background: "var(--accent)",
    color: "#fff",
    borderRadius: 12,
    height: 36,
    padding: "0 14px",
    fontWeight: 700,
  },
};
