import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiClientError } from "../../api/client";
import { subscribeToEvents } from "../../api/events";
import type {
  AnyRecord,
  ApprovalGate,
  TaskApprovalsData,
  TaskGraphData,
  TaskMessage,
  TaskMessagesData,
  TaskStudioData,
} from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./TaskStudio.css";

/** Fallback provider id list, mirrors the ids surfaced by GET /providers
 * (see web/src/views/Agents/index.tsx) for environments where the
 * providers fetch hasn't resolved yet. */
const FALLBACK_PROVIDERS = ["local", "claude", "codex", "opencode"];

/** `_REPOSITORY_ACTION_MODES` from src/service/preferences.py, with
 * friendly labels for the action-button row. */
const REPOSITORY_ACTION_LABELS: Record<string, string> = {
  no_action: "No repo action",
  prepare_patch: "Prepare patch",
  commit: "Commit changes",
  draft_pr: "Open draft PR",
  ready_pr: "Open PR for review",
};

const REPOSITORY_ACTION_MODES = [
  "no_action",
  "prepare_patch",
  "commit",
  "draft_pr",
  "ready_pr",
];

/**
 * Task Studio — graph + conversation view for a single task.
 * Route: /task/:id
 *
 * M1 scope: read-only render of GET /tasks/{id}/studio (+graph, messages,
 * approvals, and the Evidence/Review/History/Handoff tab projections). Live
 * updates via subscribeToEvents() trigger a lightweight re-fetch of
 * messages/graph/approvals. Action wiring (approve/reject/send message,
 * graph node actions) is M2 — buttons render but are disabled/no-op.
 */

// ---------------------------------------------------------------------
// Defensive shape helpers
//
// /tasks/{id}/studio, /tasks/{id}/graph, /tasks/{id}/evidence,
// /tasks/{id}/reviews and /tasks/{id}/handoff are all declared
// `additionalProperties: true` in docs/openapi.json — the service-side
// shapes (see src/service/scheduling.py::_graph_from_subtasks and
// src/service/views.py::_task_studio_snapshot) are the best available
// reference, but every field is read defensively here.
// ---------------------------------------------------------------------

interface GraphNode extends AnyRecord {
  id?: string;
  title?: string;
  status?: string;
  role?: string;
  provider?: string;
  blocked_by?: string[];
}

interface GraphEdge extends AnyRecord {
  from?: string;
  to?: string;
  source?: string;
  target?: string;
  type?: string;
}

interface NormalizedGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  activeNodes: Set<string>;
  completeNodes: Set<string>;
}

function asRecord(value: unknown): AnyRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : null;
}

function asArray(value: unknown): AnyRecord[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is AnyRecord => !!item && typeof item === "object");
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function stringField(record: AnyRecord | null | undefined, ...keys: string[]): string | undefined {
  if (!record) return undefined;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length > 0) return value;
    if (typeof value === "number") return String(value);
  }
  return undefined;
}

function numberField(record: AnyRecord | null | undefined, ...keys: string[]): number | undefined {
  if (!record) return undefined;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number") return value;
  }
  return undefined;
}

/** Normalize whatever /tasks/{id}/graph returns into nodes/edges arrays.
 * Expected shape (src/service/scheduling.py::_graph_from_subtasks):
 *   { task_id, nodes: [{id,title,status,role,provider,blocked_by,...}],
 *     edges: [{from,to,type}], active_nodes, complete_nodes, ... }
 * Falls back gracefully if `graph` or `data` wrappers are nested, or if
 * nodes/edges are missing entirely. */
function normalizeGraph(graph: AnyRecord | null | undefined): NormalizedGraph {
  if (!graph) return { nodes: [], edges: [], activeNodes: new Set(), completeNodes: new Set() };

  // Some payloads may nest the graph under a `graph` key.
  const source = asRecord(graph.graph) ?? graph;

  const nodes = asArray(source.nodes);
  const edges = asArray(source.edges);
  const activeNodes = new Set(asStringArray(source.active_nodes));
  const completeNodes = new Set(asStringArray(source.complete_nodes));

  return { nodes, edges, activeNodes, completeNodes };
}

/** Map a node's status (+ derived active/complete sets) to a CSS-class
 * suffix and short label used by the legend / DAG / list view. */
function nodeStatusInfo(
  node: GraphNode,
  graph: NormalizedGraph,
): { key: string; label: string } {
  const id = stringField(node, "id");
  const rawStatus = stringField(node, "status")?.toLowerCase();

  if (rawStatus === "complete" || rawStatus === "done" || (id && graph.completeNodes.has(id))) {
    return { key: "done", label: "done" };
  }
  if (
    rawStatus === "in_progress" ||
    rawStatus === "running" ||
    rawStatus === "review" ||
    (id && graph.activeNodes.has(id))
  ) {
    return { key: "running", label: "in progress" };
  }
  if (rawStatus === "failed" || rawStatus === "rejected") {
    return { key: "failed", label: "failed" };
  }
  if (rawStatus === "blocked") {
    return { key: "blocked", label: "blocked" };
  }
  if (rawStatus === "waiting_human") {
    return { key: "waiting", label: "waiting on you" };
  }
  if (rawStatus === "queued" || rawStatus === "waiting" || !rawStatus) {
    return { key: "waiting", label: rawStatus ?? "waiting" };
  }
  return { key: "default", label: rawStatus ?? "unknown" };
}

/** Best-effort provider badge text, e.g. "claude" -> "CL". */
function providerBadge(provider: string | undefined): string | null {
  if (!provider) return null;
  const cleaned = provider.replace(/[^a-zA-Z]/g, "");
  if (cleaned.length === 0) return provider.slice(0, 2).toUpperCase();
  if (cleaned.length <= 2) return cleaned.toUpperCase();
  return (cleaned[0] + cleaned[cleaned.length - 1]).toUpperCase();
}

/** Resolve an edge's endpoints across plausible field-name variants
 * (`from`/`to` per _graph_from_subtasks, or `source`/`target`). */
function edgeEndpoints(edge: GraphEdge): { from: string | undefined; to: string | undefined } {
  return {
    from: stringField(edge, "from", "source", "parent"),
    to: stringField(edge, "to", "target", "child"),
  };
}

// ---------------------------------------------------------------------
// Layered DAG layout
// ---------------------------------------------------------------------

interface LayoutNode {
  node: GraphNode;
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface DagLayout {
  nodes: LayoutNode[];
  width: number;
  height: number;
}

const NODE_WIDTH = 200;
const NODE_HEIGHT = 54;
const ROW_GAP = 56;
const COL_GAP = 40;

/** Lay out nodes into vertical "rows" (layers) using a simple longest-path
 * topological layering from blocked_by/edge relationships, then center each
 * row's nodes horizontally. Nodes with no resolvable position are placed in
 * row 0. Defensive against cycles (falls back to insertion order). */
function layoutGraph(graph: NormalizedGraph): DagLayout {
  const { nodes, edges } = graph;
  if (nodes.length === 0) return { nodes: [], width: 0, height: 0 };

  const ids = nodes.map((n) => stringField(n, "id")).filter((id): id is string => !!id);
  const idSet = new Set(ids);

  // Build parent adjacency from edges + blocked_by, restricted to known
  // node ids.
  const parentsOf = new Map<string, Set<string>>();
  const addEdge = (from: string, to: string) => {
    if (!idSet.has(from) || !idSet.has(to) || from === to) return;
    if (!parentsOf.has(to)) parentsOf.set(to, new Set());
    parentsOf.get(to)!.add(from);
  };

  for (const edge of edges) {
    const { from, to } = edgeEndpoints(edge);
    if (from && to) addEdge(from, to);
  }
  for (const node of nodes) {
    const id = stringField(node, "id");
    if (!id) continue;
    for (const blocker of asStringArray(node.blocked_by)) {
      addEdge(blocker, id);
    }
  }

  // Longest-path layering (Kahn-style with cycle guard).
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const resolve = (id: string, depth = 0): number => {
    if (layer.has(id)) return layer.get(id)!;
    if (visiting.has(id) || depth > nodes.length + 1) {
      layer.set(id, 0);
      return 0;
    }
    visiting.add(id);
    const parents = parentsOf.get(id);
    let value = 0;
    if (parents && parents.size > 0) {
      for (const parentId of parents) {
        value = Math.max(value, resolve(parentId, depth + 1) + 1);
      }
    }
    visiting.delete(id);
    layer.set(id, value);
    return value;
  };
  for (const id of ids) resolve(id);

  // Group nodes by layer, preserving original order within a layer.
  const byLayer = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const id = stringField(node, "id");
    const l = id ? layer.get(id) ?? 0 : 0;
    if (!byLayer.has(l)) byLayer.set(l, []);
    byLayer.get(l)!.push(node);
  }

  const layers = Array.from(byLayer.keys()).sort((a, b) => a - b);
  const maxCols = Math.max(...layers.map((l) => byLayer.get(l)!.length));
  const width = Math.max(maxCols * (NODE_WIDTH + COL_GAP) - COL_GAP, NODE_WIDTH);

  const layoutNodes: LayoutNode[] = [];
  layers.forEach((l, rowIndex) => {
    const rowNodes = byLayer.get(l)!;
    const rowWidth = rowNodes.length * (NODE_WIDTH + COL_GAP) - COL_GAP;
    const startX = (width - rowWidth) / 2;
    rowNodes.forEach((node, colIndex) => {
      const id = stringField(node, "id") ?? `node-${rowIndex}-${colIndex}`;
      layoutNodes.push({
        node,
        id,
        x: startX + colIndex * (NODE_WIDTH + COL_GAP),
        y: rowIndex * (NODE_HEIGHT + ROW_GAP),
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      });
    });
  });

  const height = layers.length * (NODE_HEIGHT + ROW_GAP) - ROW_GAP;
  return { nodes: layoutNodes, width: Math.max(width, NODE_WIDTH), height: Math.max(height, NODE_HEIGHT) };
}

/** Cubic-bezier path between a parent's bottom-center and a child's
 * top-center, mirroring the mockup's edge curves. */
function edgePath(from: LayoutNode, to: LayoutNode): string {
  const x1 = from.x + from.width / 2;
  const y1 = from.y + from.height;
  const x2 = to.x + to.width / 2;
  const y2 = to.y;
  const midY = (y1 + y2) / 2;
  return `M${x1} ${y1} C${x1} ${midY} ${x2} ${midY} ${x2} ${y2}`;
}

// ---------------------------------------------------------------------
// Message + header helpers
// ---------------------------------------------------------------------

/** Classify a message's role into one of the three chat-bubble styles. */
function messageRoleClass(message: TaskMessage): "ts-msg-user" | "ts-msg-sarathi" | "ts-msg-agent" {
  const role = stringField(message, "role")?.toLowerCase() ?? "";
  if (role === "user" || role === "human" || role === "operator") return "ts-msg-user";
  if (role === "sarathi" || role === "system" || role === "planner" || role === "judge") {
    return "ts-msg-sarathi";
  }
  return "ts-msg-agent";
}

/** Short avatar initials for a message sender. */
function messageAvatar(message: TaskMessage, roleClass: string): string {
  if (roleClass === "ts-msg-sarathi") return "स";
  const meta = asRecord(message.metadata);
  const sender =
    stringField(message, "sender", "agent", "provider") ?? stringField(meta, "provider", "role", "agent");
  if (roleClass === "ts-msg-user") return "You".slice(0, 2).toUpperCase();
  return providerBadge(sender) ?? (sender ? sender.slice(0, 2).toUpperCase() : "AG");
}

/** Display name for the message sender line. */
function messageSenderName(message: TaskMessage, roleClass: string): string {
  if (roleClass === "ts-msg-user") return "You";
  if (roleClass === "ts-msg-sarathi") return "Sarathi";
  const meta = asRecord(message.metadata);
  return (
    stringField(message, "sender", "agent", "provider") ??
    stringField(meta, "provider", "role", "agent") ??
    stringField(message, "role") ??
    "agent"
  );
}

function formatTimestamp(value: unknown): string {
  if (typeof value !== "string") return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Pretty-print "awaiting_approval" -> "awaiting approval". */
function humanize(value: string | undefined | null): string {
  if (!value) return "—";
  return value.replace(/_/g, " ");
}

// ---------------------------------------------------------------------
// Approval gate inline card
// ---------------------------------------------------------------------

/**
 * Shared action-button row for "Repository action" gates — used both by
 * the in-chat ApprovalCard (when the pending gate is "Repository action")
 * and by the Handoff tab (when `handoff.metadata.repository_action.status
 * === "pending"`).
 */
function RepositoryActionButtons({
  taskId,
  allowedActions,
  onChanged,
}: {
  taskId: string;
  allowedActions: string[];
  onChanged: () => void;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const actions = allowedActions.length > 0 ? allowedActions : REPOSITORY_ACTION_MODES;

  const handleClick = async (action: string) => {
    setLoading(action);
    try {
      await api.recordRepositoryAction(taskId, { approved: true, action });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="ts-appr-actions">
      <div className="ts-acts">
        {actions.map((action) => (
          <button
            key={action}
            type="button"
            className="btn ts-ok"
            disabled={loading !== null}
            onClick={() => handleClick(action)}
          >
            {loading === action ? "Working…" : REPOSITORY_ACTION_LABELS[action] ?? humanize(action)}
          </button>
        ))}
      </div>
      {error && <p className="ts-err">{error}</p>}
    </div>
  );
}

function ApprovalCard({
  gate,
  taskId,
  onChanged,
}: {
  gate: ApprovalGate;
  taskId: string;
  onChanged: () => void;
}) {
  const name = stringField(gate, "name") ?? "approval";
  const status = stringField(gate, "status") ?? "pending";
  const meta = asRecord(gate.metadata);
  const description =
    stringField(gate, "description") ??
    stringField(meta, "description", "summary") ??
    "Operator review requested before this unit can proceed.";

  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const runApproval = async (decision: "approved" | "rejected") => {
    setLoading(decision);
    setNote(null);
    try {
      if (name === "PRD/AC") {
        await api.recordApproval(taskId, { name, status: decision });
        if (decision === "approved") {
          await api.createGraphDraft(taskId);
        }
      } else if (name === "Task graph") {
        const result = await api.recordApproval(taskId, { name, status: decision });
        const autoSchedule = asRecord(result.auto_schedule);
        const scheduled = asArray(autoSchedule?.scheduled);
        if (decision === "approved" && scheduled.length > 0) {
          setNote(`Scheduled ${scheduled.length} unit(s).`);
        }
      } else {
        await api.recordApproval(taskId, { name, status: decision });
      }
      onChanged();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  };

  if (name === "Repository action") {
    const allowedActions = asStringArray(meta?.allowed_actions);
    return (
      <div className="ts-appr">
        <h4>
          ⚠ Approval {status === "pending" ? "required" : humanize(status)} — {name}
        </h4>
        <p>{description}</p>
        <RepositoryActionButtons taskId={taskId} allowedActions={allowedActions} onChanged={onChanged} />
      </div>
    );
  }

  return (
    <div className="ts-appr">
      <h4>
        ⚠ Approval {status === "pending" ? "required" : humanize(status)} — {name}
      </h4>
      <p>{description}</p>
      <div className="ts-acts">
        <button
          type="button"
          className="btn ts-ok"
          disabled={loading !== null}
          onClick={() => runApproval("approved")}
        >
          {loading === "approved" ? "Working…" : "Approve & dispatch"}
        </button>
        <button
          type="button"
          className="btn ts-no"
          disabled={loading !== null}
          onClick={() => runApproval("rejected")}
        >
          {loading === "rejected" ? "Working…" : "Reject"}
        </button>
      </div>
      {note && <p className="ts-note">{note}</p>}
      {error && <p className="ts-err">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------
// "Schedule ready units" toolbar button — calls POST /tasks/{id}/schedule,
// the canonical "schedule whatever is ready" action. Idempotent: units
// whose blockers aren't satisfied simply aren't scheduled.
// ---------------------------------------------------------------------

function ScheduleReadyButton({ taskId, onChanged }: { taskId: string; onChanged: () => void }) {
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setLoading(true);
    setError(null);
    setNote(null);
    try {
      const result = await api.scheduleTask(taskId);
      const scheduled = asArray(result.scheduled);
      setNote(`Scheduled ${scheduled.length} unit(s).`);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ts-schedule-tool">
      <button type="button" className="btn ghost" disabled={loading} onClick={handleClick}>
        {loading ? "Working…" : "Schedule ready units"}
      </button>
      {note && <span className="ts-note ts-inline-note">{note}</span>}
      {error && <span className="ts-err ts-inline-note">{error}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------

type GraphViewMode = "graph" | "list";
type StudioTab = "evidence" | "review" | "history" | "handoff";

const TABS: { key: StudioTab; label: string }[] = [
  { key: "evidence", label: "Evidence" },
  { key: "review", label: "Review" },
  { key: "history", label: "History" },
  { key: "handoff", label: "Handoff" },
];

export default function TaskStudio() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { currentWorkspaceId, serviceStatus } = useWorkspace();

  const [studio, setStudio] = useState<TaskStudioData | null>(null);
  const [graphData, setGraphData] = useState<TaskGraphData | null>(null);
  const [messages, setMessages] = useState<TaskMessage[]>([]);
  const [approvals, setApprovals] = useState<ApprovalGate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [graphView, setGraphView] = useState<GraphViewMode>("graph");
  const [messageSearch, setMessageSearch] = useState("");
  const [activeTab, setActiveTab] = useState<StudioTab>("evidence");

  // Composer (chat send box) state.
  const [composerText, setComposerText] = useState("");
  const [composerRole, setComposerRole] = useState<"user" | "assistant">("user");
  const [composerSending, setComposerSending] = useState(false);
  const [composerError, setComposerError] = useState<string | null>(null);

  // Tab-specific data, lazily fetched.
  const [tabData, setTabData] = useState<Record<StudioTab, unknown>>({
    evidence: undefined,
    review: undefined,
    history: undefined,
    handoff: undefined,
  });
  const [tabLoading, setTabLoading] = useState(false);
  const [tabError, setTabError] = useState<string | null>(null);

  const chatBodyRef = useRef<HTMLDivElement | null>(null);

  // -----------------------------------------------------------------
  // Initial load: studio snapshot, graph, messages, approvals.
  // -----------------------------------------------------------------
  const loadCore = useCallback(
    (signal?: AbortSignal) => {
      if (!id) return;
      setLoading(true);
      setError(null);
      Promise.allSettled([
        api.getTaskStudio(id, signal),
        api.getTaskGraph(id, signal),
        api.getTaskMessages(id, signal),
        api.getTaskApprovals(id, signal),
      ])
        .then(([studioRes, graphRes, messagesRes, approvalsRes]) => {
          if (signal?.aborted) return;

          if (studioRes.status === "fulfilled") {
            setStudio(studioRes.value);
          } else if (studioRes.reason instanceof ApiClientError) {
            setError(studioRes.reason.message);
          } else {
            setError(String(studioRes.reason));
          }

          if (graphRes.status === "fulfilled") {
            setGraphData(graphRes.value);
          }

          if (messagesRes.status === "fulfilled") {
            const data = messagesRes.value as TaskMessagesData;
            setMessages(Array.isArray(data?.messages) ? data.messages : []);
          }

          if (approvalsRes.status === "fulfilled") {
            const data = approvalsRes.value as TaskApprovalsData;
            setApprovals(Array.isArray(data?.approval_gates) ? data.approval_gates : []);
          }
        })
        .finally(() => {
          if (!signal?.aborted) setLoading(false);
        });
    },
    [id],
  );

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    loadCore(controller.signal);
    return () => controller.abort();
  }, [id, loadCore]);

  // Re-run the core fetches (studio, graph, messages, approvals). Also
  // invalidate the lazily-fetched Handoff tab data so it refetches after a
  // governed action (e.g. generating a handoff or recording a repository
  // action) — `loadCore` alone doesn't touch `tabData`.
  const refresh = useCallback(() => {
    loadCore();
    setTabData((prev) => ({ ...prev, handoff: undefined }));
  }, [loadCore]);

  // -----------------------------------------------------------------
  // Provider options for the graph list view's dispatch controls.
  // -----------------------------------------------------------------
  const [providerOptions, setProviderOptions] = useState<string[]>(FALLBACK_PROVIDERS);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getProviders(currentWorkspaceId ?? undefined, controller.signal)
      .then((data) => {
        const ids = (data.providers ?? [])
          .map((p) => stringField(p, "id", "name"))
          .filter((p): p is string => !!p);
        if (ids.length > 0) setProviderOptions(ids);
      })
      .catch(() => {
        // Keep the fallback list on error.
      });
    return () => controller.abort();
  }, [currentWorkspaceId]);

  // -----------------------------------------------------------------
  // Live updates: poll /events for this task and re-fetch the
  // message/graph/approval projections on each batch.
  // -----------------------------------------------------------------
  useEffect(() => {
    if (!id) return;
    const unsubscribe = subscribeToEvents(
      { workspaceId: currentWorkspaceId ?? undefined, taskId: id },
      {
        onEvents: (events) => {
          if (events.length === 0) return;
          const controller = new AbortController();
          Promise.allSettled([
            api.getTaskMessages(id, controller.signal),
            api.getTaskGraph(id, controller.signal),
            api.getTaskApprovals(id, controller.signal),
            api.getTaskStudio(id, controller.signal),
          ]).then(([messagesRes, graphRes, approvalsRes, studioRes]) => {
            if (messagesRes.status === "fulfilled") {
              const data = messagesRes.value as TaskMessagesData;
              setMessages(Array.isArray(data?.messages) ? data.messages : []);
            }
            if (graphRes.status === "fulfilled") setGraphData(graphRes.value);
            if (approvalsRes.status === "fulfilled") {
              const data = approvalsRes.value as TaskApprovalsData;
              setApprovals(Array.isArray(data?.approval_gates) ? data.approval_gates : []);
            }
            if (studioRes.status === "fulfilled") setStudio(studioRes.value);
          });
        },
        onError: () => {
          // Polling errors surface via serviceStatus / OfflineBanner already;
          // avoid stacking redundant error UI here.
        },
      },
    );
    return unsubscribe;
  }, [id, currentWorkspaceId]);

  // -----------------------------------------------------------------
  // Tab data: lazily fetch on first activation of each tab.
  // -----------------------------------------------------------------
  useEffect(() => {
    if (!id) return;
    if (tabData[activeTab] !== undefined) return;

    const controller = new AbortController();
    setTabLoading(true);
    setTabError(null);

    let request: Promise<unknown>;
    switch (activeTab) {
      case "evidence":
        request = api.getTaskEvidence(id, controller.signal);
        break;
      case "review":
        request = api.getTaskReviews(id, controller.signal);
        break;
      case "handoff":
        request = api.getTaskHandoff(id, controller.signal);
        break;
      case "history":
      default:
        request = api.getEvents({ taskId: id }, controller.signal);
        break;
    }

    request
      .then((data) => {
        if (controller.signal.aborted) return;
        setTabData((prev) => ({ ...prev, [activeTab]: data }));
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setTabError(err instanceof ApiClientError ? err.message : String(err));
        setTabData((prev) => ({ ...prev, [activeTab]: null }));
      })
      .finally(() => {
        if (!controller.signal.aborted) setTabLoading(false);
      });

    return () => controller.abort();
  }, [id, activeTab, tabData]);

  // -----------------------------------------------------------------
  // Derived data
  // -----------------------------------------------------------------
  const task = useMemo(() => asRecord(studio?.task) ?? asRecord(studio), [studio]);
  const header = useMemo(() => asRecord(studio?.header), [studio]);
  const taskMetadata = useMemo(() => asRecord(task?.metadata), [task]);

  const graph = useMemo(() => {
    // Prefer the dedicated /graph endpoint; fall back to studio.graph.
    // normalizeGraph() also handles a nested `{ graph: {...} }` wrapper.
    const fromGraphEndpoint = asRecord(graphData);
    const hasNodes = fromGraphEndpoint && asArray((asRecord(fromGraphEndpoint.graph) ?? fromGraphEndpoint).nodes).length > 0;
    const source = hasNodes ? fromGraphEndpoint : asRecord(studio?.graph) ?? fromGraphEndpoint;
    return normalizeGraph(source);
  }, [graphData, studio]);

  const layout = useMemo(() => layoutGraph(graph), [graph]);

  const taskTitle = stringField(task, "title", "name") ?? id ?? "Task";
  const queueState = stringField(header, "queue_state") ?? stringField(task, "status");
  const phase = stringField(taskMetadata, "phase") ?? stringField(task, "phase") ?? stringField(task, "status");
  const taskClass =
    stringField(taskMetadata, "classification", "task_class", "class") ?? "—";

  const providers = useMemo(() => {
    const set = new Set<string>();
    for (const node of graph.nodes) {
      const p = stringField(node, "provider");
      if (p) set.add(p);
    }
    return Array.from(set);
  }, [graph.nodes]);
  const providerLabel = providers.length > 0 ? providers.join(", ") : stringField(taskMetadata, "provider") ?? "—";

  const acceptanceCriteria = asArray(taskMetadata?.acceptance_criteria);
  const acTotalMeta = numberField(taskMetadata, "acceptance_criteria_total");
  const acCoveredMeta = numberField(taskMetadata, "acceptance_criteria_covered");
  const acTotal = acceptanceCriteria.length > 0 ? acceptanceCriteria.length : acTotalMeta;
  const acCovered =
    acceptanceCriteria.length > 0
      ? acceptanceCriteria.filter((c) => c.status === "met" || c.met === true || c.passed === true).length
      : acCoveredMeta ?? graph.completeNodes.size;
  const acLabel = acTotal !== undefined ? `${acCovered} / ${acTotal}` : "—";

  const nextSafeAction = stringField(header, "next_safe_action");

  const filteredMessages = useMemo(() => {
    const q = messageSearch.trim().toLowerCase();
    if (!q) return messages;
    return messages.filter((m) => {
      const content = stringField(m, "content")?.toLowerCase() ?? "";
      const sender = messageSenderName(m, messageRoleClass(m)).toLowerCase();
      return content.includes(q) || sender.includes(q);
    });
  }, [messages, messageSearch]);

  // Pending approval gates, used to inject inline approval cards near the
  // end of the conversation (mirrors the mockup's "approval gate" message).
  const pendingApprovals = useMemo(
    () => approvals.filter((g) => stringField(g, "status") === "pending"),
    [approvals],
  );

  // Auto-scroll to the latest message on load / update.
  useEffect(() => {
    const el = chatBodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [filteredMessages.length]);

  // -----------------------------------------------------------------
  // Composer: post a chat message visible to all agents on this task.
  // -----------------------------------------------------------------
  const sendMessage = useCallback(async () => {
    const content = composerText.trim();
    if (!content || composerSending || !id) return;
    setComposerSending(true);
    setComposerError(null);
    try {
      const result = await api.postTaskMessage(id, {
        content,
        role: composerRole,
        target: "Current task agents",
      });
      setMessages((prev) => [...prev, result.message]);
      setComposerText("");
    } catch (err) {
      setComposerError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setComposerSending(false);
    }
  }, [composerText, composerSending, composerRole, id]);

  const offline = serviceStatus === "offline";

  if (!id) {
    return (
      <section className="ts-page">
        <div className="card2 ts-empty">No task id in route.</div>
      </section>
    );
  }

  return (
    <section className="ts-page">
      <div className="ph ts-back">
        <div className="row">
          <button className="btn ghost" type="button" onClick={() => navigate("/")}>
            ← Back to Dashboard
          </button>
        </div>
      </div>

      {offline && (
        <div className="banner offline">
          ⚠ Sarathi service is offline — showing the last known task data, if any.
        </div>
      )}

      {loading && (
        <div className="card2 ts-empty">Loading task studio…</div>
      )}

      {!loading && error && !studio && (
        <div className="banner offline">⚠ Failed to load task studio: {error}</div>
      )}

      {!loading && !studio && !error && (
        <div className="card2 ts-empty">No data available for task “{id}”.</div>
      )}

      {studio && (
        <>
          <div className="ts-studio">
            <div className="ts-left">
              {/* State header */}
              <div className="card2 ts-head">
                <h2>{taskTitle}</h2>
                <div className="ts-kv">
                  <span>Queue</span>
                  <b style={{ color: "var(--blue)" }}>{humanize(queueState)}</b>
                </div>
                <div className="ts-kv">
                  <span>Phase</span>
                  <b>{phase ? phase.toString().toUpperCase() : "—"}</b>
                </div>
                <div className="ts-kv">
                  <span>Class</span>
                  <b>{taskClass}</b>
                </div>
                <div className="ts-kv">
                  <span>Provider</span>
                  <b>{providerLabel}</b>
                </div>
                <div className="ts-kv">
                  <span>AC coverage</span>
                  <b>{acLabel}</b>
                </div>
                {nextSafeAction && (
                  <div className="ts-nextsafe">▶ {nextSafeAction}</div>
                )}
              </div>

              {/* Graph / list panel */}
              <div className="card2 ts-gwrap">
                <div className="ts-gtool">
                  <div className="seg">
                    <button
                      type="button"
                      className={graphView === "graph" ? "on" : ""}
                      onClick={() => setGraphView("graph")}
                    >
                      Graph
                    </button>
                    <button
                      type="button"
                      className={graphView === "list" ? "on" : ""}
                      onClick={() => setGraphView("list")}
                    >
                      List
                    </button>
                  </div>
                  <ScheduleReadyButton taskId={id} onChanged={refresh} />
                  <div className="ts-legend">
                    <span>
                      <i style={{ background: "var(--green)" }} />
                      done
                    </span>
                    <span>
                      <i style={{ background: "var(--blue)" }} />
                      in progress
                    </span>
                    <span>
                      <i style={{ background: "transparent", border: "1.5px solid var(--slate)" }} />
                      waiting
                    </span>
                    {providers.length > 0 && (
                      <>
                        <span style={{ opacity: 0.4 }}>|</span>
                        {providers.map((p) => (
                          <span key={p}>
                            <b className="ts-badge-sample">{providerBadge(p)}</b> → {p}
                          </span>
                        ))}
                      </>
                    )}
                  </div>
                </div>
                <div className="ts-canvas">
                  {graph.nodes.length === 0 ? (
                    <div className="ts-canvas-empty">
                      No graph nodes yet — the task graph hasn&apos;t been generated for this task.
                    </div>
                  ) : graphView === "graph" ? (
                    <TaskGraphSvg graph={graph} layout={layout} />
                  ) : (
                    <TaskGraphList
                      graph={graph}
                      taskId={id}
                      onChanged={refresh}
                      providerOptions={providerOptions}
                    />
                  )}
                </div>
              </div>
            </div>

            {/* Chat / conversation pane */}
            <div className="card2 ts-chat">
              <div className="ts-chh">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth={2}>
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <b>Conversation</b>
                <span className="ts-who">{messages.length} messages</span>
              </div>
              <div className="ts-chat-search">
                <div className="search">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <circle cx="11" cy="11" r="7" />
                    <path d="M21 21l-4-4" />
                  </svg>
                  <input
                    placeholder="Search messages…"
                    value={messageSearch}
                    onChange={(e) => setMessageSearch(e.target.value)}
                  />
                </div>
              </div>
              <div className="ts-chb" ref={chatBodyRef}>
                {filteredMessages.length === 0 && (
                  <div className="ts-chb-empty">
                    {messages.length === 0
                      ? "No messages yet for this task."
                      : "No messages match your search."}
                  </div>
                )}
                {filteredMessages.map((message, idx) => {
                  const roleClass = messageRoleClass(message);
                  const sender = messageSenderName(message, roleClass);
                  const avatar = messageAvatar(message, roleClass);
                  const ts = formatTimestamp(message.created_at);
                  const content = stringField(message, "content") ?? "";
                  return (
                    <div className={`ts-msg ${roleClass}`} key={stringField(message, "id") ?? idx}>
                      <div className="ts-avatar">{avatar}</div>
                      <div className="ts-bd">
                        <div className="ts-nm">
                          <b>{sender}</b>
                          {ts && ` · ${ts}`}
                        </div>
                        <div className="ts-bub">{content || <em>(no content)</em>}</div>
                      </div>
                    </div>
                  );
                })}
                {pendingApprovals.map((gate, idx) => (
                  <div className="ts-msg ts-msg-sarathi" key={stringField(gate, "id", "name") ?? idx}>
                    <div className="ts-avatar">स</div>
                    <div className="ts-bd">
                      <div className="ts-nm">
                        <b>Sarathi</b> · approval gate
                      </div>
                      <ApprovalCard gate={gate} taskId={id} onChanged={refresh} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="ts-comp">
                <select
                  className="ts-sender"
                  value={composerRole}
                  onChange={(e) => setComposerRole(e.target.value === "assistant" ? "assistant" : "user")}
                  title="Sender"
                >
                  <option value="user">You</option>
                  <option value="assistant">Sarathi</option>
                </select>
                <textarea
                  placeholder="Send a message to agents…"
                  value={composerText}
                  onChange={(e) => setComposerText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendMessage();
                    }
                  }}
                  disabled={composerSending}
                />
                <button
                  type="button"
                  className="ts-send"
                  disabled={composerText.trim().length === 0 || composerSending}
                  onClick={() => void sendMessage()}
                  title="Send"
                >
                  {composerSending ? "…" : "↑"}
                </button>
              </div>
              <div className="ts-comp-hint">
                {composerError ? (
                  <span className="ts-err">{composerError}</span>
                ) : (
                  "Enter to send · visible to all agents on this ticket"
                )}
              </div>
            </div>
          </div>

          {/* Tab strip: Evidence / Review / History / Handoff */}
          <div className="ts-tabs-panel">
            <div className="tabs">
              {TABS.map((tab) => (
                <div
                  key={tab.key}
                  className={`tab ${activeTab === tab.key ? "on" : ""}`}
                  onClick={() => setActiveTab(tab.key)}
                  role="button"
                  tabIndex={0}
                >
                  {tab.label}
                </div>
              ))}
            </div>
            <TabPanel
              tab={activeTab}
              data={tabData[activeTab]}
              loading={tabLoading}
              error={tabError}
              taskId={id}
              onChanged={refresh}
              approvals={approvals}
              allComplete={graph.nodes.length > 0 && graph.completeNodes.size === graph.nodes.length}
            />
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------
// Graph (SVG) renderer
// ---------------------------------------------------------------------

function TaskGraphSvg({ graph, layout }: { graph: NormalizedGraph; layout: DagLayout }) {
  const byId = useMemo(() => {
    const map = new Map<string, LayoutNode>();
    for (const ln of layout.nodes) map.set(ln.id, ln);
    return map;
  }, [layout]);

  const PADDING = 20;
  const viewWidth = layout.width + PADDING * 2;
  const viewHeight = layout.height + PADDING * 2;

  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${Math.max(viewHeight, NODE_HEIGHT + PADDING * 2)}`}
      width="100%"
      height={Math.max(viewHeight, 240)}
      preserveAspectRatio="xMidYMid meet"
    >
      <g transform={`translate(${PADDING},${PADDING})`}>
        {/* Edges */}
        {graph.edges.map((edge, idx) => {
          const { from, to } = edgeEndpoints(edge);
          if (!from || !to) return null;
          const fromNode = byId.get(from);
          const toNode = byId.get(to);
          if (!fromNode || !toNode) return null;
          const toStatus = nodeStatusInfo(toNode.node, graph);
          const isFuture = toStatus.key === "waiting" || toStatus.key === "blocked";
          return (
            <path
              key={idx}
              d={edgePath(fromNode, toNode)}
              className={`ts-edge ${isFuture ? "ts-edge-future" : ""}`}
            />
          );
        })}

        {/* Nodes */}
        {layout.nodes.map((ln) => {
          const status = nodeStatusInfo(ln.node, graph);
          const title = stringField(ln.node, "title", "name") ?? ln.id;
          const provider = stringField(ln.node, "provider");
          const badge = providerBadge(provider);
          const isWaiting = status.key === "waiting" || status.key === "blocked";
          return (
            <g key={ln.id} transform={`translate(${ln.x},${ln.y})`} className={`ts-node-${status.key}`}>
              <rect
                className="ts-node-box"
                width={ln.width}
                height={ln.height}
                rx={13}
                strokeWidth={1.7}
                strokeDasharray={isWaiting ? "5 4" : undefined}
              />
              {status.key === "done" ? (
                <rect x={16} y={22} width={10} height={10} rx={2.5} fill="var(--green)" />
              ) : status.key === "running" ? (
                <circle cx={21} cy={27} r={5} fill="var(--blue)" />
              ) : status.key === "failed" ? (
                <circle cx={21} cy={27} r={5} fill="var(--red)" />
              ) : (
                <circle cx={21} cy={27} r={5} fill="none" stroke="var(--slate)" strokeWidth={1.7} />
              )}
              <text x={badge ? 92 : 100} y={31} textAnchor="middle" fontSize={13} className="ts-node-title">
                {title}
              </text>
              {badge && (
                <>
                  <rect className="ts-node-badge-bg" x={ln.width - 45} y={17} width={30} height={20} rx={6} />
                  <text
                    className="ts-node-badge-text"
                    x={ln.width - 30}
                    y={31}
                    textAnchor="middle"
                    fontSize={10}
                  >
                    {badge}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------
// Graph (list) renderer — defensive fallback for unknown graph shapes
// ---------------------------------------------------------------------

function TaskGraphList({
  graph,
  taskId,
  onChanged,
  providerOptions,
}: {
  graph: NormalizedGraph;
  taskId: string;
  onChanged: () => void;
  providerOptions: string[];
}) {
  return (
    <div className="ts-graph-list">
      {graph.nodes.map((node, idx) => (
        <GraphListRow
          key={stringField(node, "id") ?? idx}
          node={node}
          idx={idx}
          graph={graph}
          taskId={taskId}
          onChanged={onChanged}
          providerOptions={providerOptions}
        />
      ))}
    </div>
  );
}

/**
 * A single row in the graph "list" view, plus any per-node governed-action
 * controls appropriate for its current status (see scheduling.py's subtask
 * status machine: queued, in_progress, blocked, waiting_human, review,
 * complete, failed, skipped, paused).
 */
function GraphListRow({
  node,
  idx,
  graph,
  taskId,
  onChanged,
  providerOptions,
}: {
  node: GraphNode;
  idx: number;
  graph: NormalizedGraph;
  taskId: string;
  onChanged: () => void;
  providerOptions: string[];
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>(
    stringField(node, "provider") ?? providerOptions[0] ?? "local",
  );

  const status = nodeStatusInfo(node, graph);
  const rawStatus = stringField(node, "status")?.toLowerCase();
  const title = stringField(node, "title", "name") ?? stringField(node, "id") ?? `Node ${idx + 1}`;
  const provider = stringField(node, "provider");
  const role = stringField(node, "role");
  const badge = providerBadge(provider);
  const nodeId = stringField(node, "id");

  const runAction = async (key: string, action: () => Promise<void>) => {
    setLoading(key);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  };

  let controls: ReactNode = null;
  if (rawStatus === "queued") {
    controls = (
      <button
        type="button"
        className="btn ghost ts-row-btn"
        disabled={loading !== null}
        onClick={() => runAction("dispatch", () => api.scheduleTask(taskId).then(() => undefined))}
      >
        {loading === "dispatch" ? "Working…" : "Dispatch"}
      </button>
    );
  } else if (rawStatus === "in_progress" && nodeId) {
    controls = (
      <>
        <select
          className="ts-row-select"
          value={selectedProvider}
          onChange={(e) => setSelectedProvider(e.target.value)}
          disabled={loading !== null}
        >
          {providerOptions.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn ghost ts-row-btn"
          disabled={loading !== null}
          onClick={() =>
            runAction("run", () => api.dispatchSubtask(nodeId, { provider: selectedProvider }).then(() => undefined))
          }
        >
          {loading === "run" ? "Working…" : "Run"}
        </button>
      </>
    );
  } else if (rawStatus === "review" && nodeId) {
    controls = (
      <>
        <button
          type="button"
          className="btn ghost ts-row-btn"
          disabled={loading !== null}
          onClick={() =>
            runAction("complete", () =>
              api.transitionSubtask(nodeId, { status: "complete", actor: "Operator" }).then(() => undefined),
            )
          }
        >
          {loading === "complete" ? "Working…" : "Mark complete"}
        </button>
        <button
          type="button"
          className="btn ghost ts-row-btn"
          disabled={loading !== null}
          onClick={() =>
            runAction("requeue", () =>
              api
                .transitionSubtask(nodeId, {
                  status: "queued",
                  actor: "Operator",
                  reason: "Sent back for rework by operator",
                })
                .then(() => undefined),
            )
          }
        >
          {loading === "requeue" ? "Working…" : "Send back"}
        </button>
      </>
    );
  } else if (rawStatus === "failed" && nodeId) {
    controls = (
      <button
        type="button"
        className="btn ghost ts-row-btn"
        disabled={loading !== null}
        onClick={() =>
          runAction("retry", async () => {
            await api.transitionSubtask(nodeId, { status: "queued", actor: "Operator", reason: "Retry" });
            try {
              await api.scheduleTask(taskId);
            } catch {
              // best-effort — ignore scheduling errors after a retry requeue
            }
          })
        }
      >
        {loading === "retry" ? "Working…" : "Retry"}
      </button>
    );
  }

  return (
    <div className="ts-graph-row" key={nodeId ?? idx}>
      <span className={`ts-status-dot ts-status-${status.key}`} />
      <span className="ts-row-title">{title}</span>
      <span className="ts-row-meta">
        {role && <span>{role}</span>}
        {badge && <span className="ts-provider-badge">{badge}</span>}
        <span>{status.label}</span>
      </span>
      {controls && <span className="ts-row-actions">{controls}</span>}
      {error && <span className="ts-err ts-row-error">{error}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------
// Tab panels: Evidence / Review / History / Handoff
// ---------------------------------------------------------------------

function TabPanel({
  tab,
  data,
  loading,
  error,
  taskId,
  onChanged,
  approvals,
  allComplete,
}: {
  tab: StudioTab;
  data: unknown;
  loading: boolean;
  error: string | null;
  taskId: string;
  onChanged: () => void;
  approvals: ApprovalGate[];
  allComplete: boolean;
}) {
  if (loading) {
    return <div className="card2 ts-empty">Loading {tab}…</div>;
  }
  if (error) {
    return <div className="banner offline">⚠ Failed to load {tab}: {error}</div>;
  }
  if (data === undefined) {
    return <div className="card2 ts-empty">Select this tab to load {tab} data.</div>;
  }

  switch (tab) {
    case "evidence":
      return <EvidenceTab data={data} />;
    case "review":
      return <ReviewTab data={data} />;
    case "history":
      return <HistoryTab data={data} />;
    case "handoff":
    default:
      return <HandoffTab data={data} taskId={taskId} onChanged={onChanged} approvals={approvals} allComplete={allComplete} />;
  }
}

/** GET /tasks/{id}/evidence — `{ task_id, evidence: [...] }` per
 * src/service/app.py, items are `additionalProperties: true`. */
function EvidenceTab({ data }: { data: unknown }) {
  const record = asRecord(data);
  const items = asArray(record?.evidence ?? record);
  if (items.length === 0) {
    return <div className="card2 ts-empty">No evidence artifacts recorded for this task yet.</div>;
  }
  return (
    <div className="card2 ts-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Kind</th>
            <th>Subtask</th>
            <th>Summary</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={stringField(item, "id") ?? idx}>
              <td>{stringField(item, "kind", "type") ?? "—"}</td>
              <td className="ts-mono">{stringField(item, "subtask_id") ?? "—"}</td>
              <td>
                <p className="ts-pre">
                  {stringField(item, "summary", "description") ??
                    JSON.stringify(item.payload ?? item.content ?? {}, null, 0).slice(0, 240)}
                </p>
              </td>
              <td className="ts-mono">{formatTimestamp(item.created_at) || stringField(item, "created_at") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** GET /tasks/{id}/reviews — `{ task_id, reviews: [...] }`. */
function ReviewTab({ data }: { data: unknown }) {
  const record = asRecord(data);
  const items = asArray(record?.reviews ?? record);
  if (items.length === 0) {
    return <div className="card2 ts-empty">No review runs recorded for this task yet.</div>;
  }
  return (
    <div className="card2 ts-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Subtask</th>
            <th>Confidence</th>
            <th>Notes</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const status = stringField(item, "status") ?? "—";
            return (
              <tr key={stringField(item, "id") ?? idx}>
                <td>
                  <span
                    className={`tag ${status === "rejected" ? "t-block" : status === "approved" ? "t-done" : "t-plan"}`}
                  >
                    <span className="d" />
                    {humanize(status)}
                  </span>
                </td>
                <td className="ts-mono">{stringField(item, "subtask_id") ?? "—"}</td>
                <td>{typeof item.confidence === "number" ? item.confidence.toFixed(2) : "—"}</td>
                <td>
                  <p className="ts-pre">{stringField(item, "notes", "summary") ?? "—"}</p>
                </td>
                <td className="ts-mono">{formatTimestamp(item.created_at) || stringField(item, "created_at") || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** GET /events?task_id= — `{ events: [...] }`, used as the History tab's
 * data source (lifecycle events / phase transitions for this task). */
function HistoryTab({ data }: { data: unknown }) {
  const record = asRecord(data);
  const items = asArray(record?.events ?? record);
  if (items.length === 0) {
    return <div className="card2 ts-empty">No lifecycle events recorded for this task yet.</div>;
  }
  // Most recent first.
  const sorted = [...items].sort((a, b) => {
    const ta = stringField(a, "created_at", "timestamp") ?? "";
    const tb = stringField(b, "created_at", "timestamp") ?? "";
    return tb.localeCompare(ta);
  });
  return (
    <div className="card2 ts-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((item, idx) => (
            <tr key={stringField(item, "id") ?? idx}>
              <td className="ts-mono">
                {formatTimestamp(item.created_at ?? item.timestamp) ||
                  stringField(item, "created_at", "timestamp") ||
                  "—"}
              </td>
              <td>{stringField(item, "event_type", "type") ?? "—"}</td>
              <td>
                <p className="ts-pre">{JSON.stringify(item.payload ?? {}, null, 0).slice(0, 240)}</p>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** GET /tasks/{id}/handoff — latest handoff object, or null. */
function HandoffTab({
  data,
  taskId,
  onChanged,
  approvals,
  allComplete,
}: {
  data: unknown;
  taskId: string;
  onChanged: () => void;
  approvals: ApprovalGate[];
  allComplete: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const record = asRecord(data);
  // app.py wraps the latest handoff as { task_id, handoff: {...} | null };
  // some shapes may return the handoff object directly instead.
  const handoff = record && "handoff" in record ? asRecord(record.handoff) : record;

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.createTaskHandoff(taskId);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  if (!handoff || Object.keys(handoff).length === 0) {
    return (
      <div className="card2 ts-empty ts-handoff-empty">
        <p>No handoff has been produced for this task yet.</p>
        {allComplete && (
          <div className="ts-acts">
            <button type="button" className="btn ts-ok" disabled={loading} onClick={handleGenerate}>
              {loading ? "Working…" : "Generate handoff"}
            </button>
          </div>
        )}
        {error && <p className="ts-err">{error}</p>}
      </div>
    );
  }

  const entries = Object.entries(handoff).filter(([key]) => key !== "id");
  const metadata = asRecord(handoff.metadata);
  const repositoryAction = asRecord(metadata?.repository_action);
  const repositoryActionPending = stringField(repositoryAction, "status") === "pending";

  const repoActionGate = approvals.find(
    (g) => stringField(g, "name") === "Repository action" && stringField(g, "status") === "pending",
  );
  const allowedActions = asStringArray(asRecord(repoActionGate?.metadata)?.allowed_actions);

  return (
    <div className="card2 ts-table-wrap">
      <table>
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <th style={{ width: "180px" }}>{humanize(key)}</th>
              <td>
                {typeof value === "string" ? (
                  value
                ) : (
                  <p className="ts-pre">{JSON.stringify(value, null, 2)}</p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {repositoryActionPending && (
        <div className="ts-handoff-repo-action">
          <p className="ts-handoff-repo-action-label">Repository action required:</p>
          <RepositoryActionButtons taskId={taskId} allowedActions={allowedActions} onChanged={onChanged} />
        </div>
      )}
    </div>
  );
}
