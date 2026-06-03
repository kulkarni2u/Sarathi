"""Task graph helpers for dependency-aware execution planning."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """Typed workflow node categories enabling the six Anthropic workflow patterns."""

    EXECUTE = "execute"       # standard work unit — runs a task directly
    FANOUT = "fanout"         # spawns N parallel child nodes at runtime
    SYNTHESIZE = "synthesize" # fan-in: waits for a sibling group, merges results
    JUDGE = "judge"           # tournament: compares competing outputs, picks winner
    LOOP_GATE = "loop_gate"   # loops until a stop condition is met
    CLASSIFY = "classify"     # routes to typed downstream branches


@dataclass
class TaskNode:
    """Single planned unit of work."""

    id: str
    title: str
    status: str = "pending"
    node_type: str = NodeType.EXECUTE
    depends_on: list[str] = field(default_factory=list)
    parent_task_id: str | None = None
    child_task_ids: list[str] = field(default_factory=list)
    needs_from: list[str] = field(default_factory=list)
    block_reason: str | None = None
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    blocked_at: str | None = None
    last_error: str | None = None
    last_touched_at: str | None = None
    pattern_config: dict[str, Any] = field(default_factory=dict)
    injected_children: list[str] = field(default_factory=list)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "node_type": self.node_type,
            "depends_on": self.depends_on,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": self.child_task_ids,
            "needs_from": self.needs_from,
            "block_reason": self.block_reason,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "blocked_at": self.blocked_at,
            "last_error": self.last_error,
            "last_touched_at": self.last_touched_at,
            "pattern_config": self.pattern_config,
            "injected_children": self.injected_children,
        }


@dataclass
class TaskGraph:
    """Minimal task graph artifact built from a plan."""

    nodes: list[TaskNode] = field(default_factory=list)

    def to_artifact(self) -> dict[str, Any]:
        graph = {
            "nodes": [node.to_artifact() for node in self.nodes],
            "ready_nodes": [node.id for node in self.nodes if not node.depends_on],
        }
        return annotate_graph_for_supervision(graph)


def graph_from_plan(plan: dict[str, Any]) -> TaskGraph:
    """Build a simple sequential task graph from a plan's steps."""
    steps = plan.get("steps", [])
    nodes: list[TaskNode] = []
    previous_id: str | None = None
    for index, step in enumerate(steps, start=1):
        node_id = f"step-{index}"
        depends_on = [previous_id] if previous_id is not None else []
        nodes.append(
            TaskNode(
                id=node_id,
                title=str(step),
                depends_on=depends_on,
                parent_task_id=plan.get("task_id"),
                needs_from=list(depends_on),
            )
        )
        previous_id = node_id
    for index, node in enumerate(nodes):
        if index + 1 < len(nodes):
            node.child_task_ids = [nodes[index + 1].id]
    return TaskGraph(nodes=nodes)


def graph_from_workflow(workflow: dict[str, Any]) -> TaskGraph:
    """Build a typed workflow graph from a workflow declaration with node types.

    If the workflow has no ``nodes`` key, falls back to ``graph_from_plan``.
    """
    nodes_spec = workflow.get("nodes", [])
    if not nodes_spec:
        return graph_from_plan(workflow)

    nodes: list[TaskNode] = []
    for spec in nodes_spec:
        node_id = spec.get("id") or f"node-{len(nodes) + 1}"
        nodes.append(
            TaskNode(
                id=node_id,
                title=spec.get("title", node_id),
                node_type=spec.get("node_type", spec.get("type", NodeType.EXECUTE)),
                depends_on=list(spec.get("depends_on", [])),
                parent_task_id=workflow.get("task_id"),
                pattern_config=dict(spec.get("pattern_config", spec.get("config", {}))),
            )
        )

    id_to_node = {n.id: n for n in nodes}
    for node in nodes:
        for dep in node.depends_on:
            parent = id_to_node.get(dep)
            if parent is not None and node.id not in parent.child_task_ids:
                parent.child_task_ids.append(node.id)
    return TaskGraph(nodes=nodes)


def inject_nodes(
    graph: dict[str, Any],
    parent_id: str,
    new_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Inject new nodes into a live graph, each depending on parent_id.

    Nodes whose ``id`` already exists in the graph are silently skipped.
    Updates the parent node's ``injected_children`` tracking list.
    """
    existing_ids = {node.get("id") for node in graph.get("nodes", [])}
    nodes = [dict(n) for n in graph.get("nodes", [])]
    injected_ids: list[str] = []

    for spec in new_nodes:
        node_id = spec.get("id")
        if not node_id or node_id in existing_ids:
            continue
        new_node = dict(spec)
        deps = list(new_node.get("depends_on", []))
        if parent_id not in deps:
            deps.insert(0, parent_id)
        new_node["depends_on"] = deps
        new_node.setdefault("status", "pending")
        new_node.setdefault("node_type", NodeType.EXECUTE)
        nodes.append(new_node)
        injected_ids.append(node_id)
        existing_ids.add(node_id)

    updated_nodes = []
    for node in nodes:
        n = dict(node)
        if n.get("id") == parent_id and injected_ids:
            existing = list(n.get("injected_children", []))
            n["injected_children"] = existing + [i for i in injected_ids if i not in existing]
        updated_nodes.append(n)

    return _recompute_graph_state({"nodes": updated_nodes})


def graph_summary(graph: dict[str, Any]) -> dict[str, int]:
    """Summarize node counts by status."""
    counts = {
        "pending": 0,
        "completed": 0,
        "in_progress": 0,
        "running": 0,
        "blocked": 0,
        "failed": 0,
        "waiting_human": 0,
        "waiting_user": 0,
        "stale": 0,
        "done": 0,
    }
    for node in graph.get("nodes", []):
        status = node.get("status", "pending")
        counts.setdefault(status, 0)
        counts[status] += 1
    counts["total"] = len(graph.get("nodes", []))
    return counts


def latest_completed_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most recently completed node if any."""
    completed_nodes = [
        node for node in graph.get("nodes", [])
        if node.get("status") == "completed"
    ]
    if not completed_nodes:
        return None
    return max(
        completed_nodes,
        key=lambda node: (node.get("completed_at") or "", node.get("id") or ""),
    )


def latest_failed_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most recently failed node if any."""
    failed_nodes = [
        node for node in graph.get("nodes", [])
        if node.get("status") == "failed"
    ]
    if not failed_nodes:
        return None
    return max(
        failed_nodes,
        key=lambda node: (node.get("failed_at") or "", node.get("id") or ""),
    )


def complete_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Mark all nodes as completed."""
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        updated["status"] = "completed"
        nodes.append(updated)
    return {
        "nodes": nodes,
        "ready_nodes": [],
        "completed_nodes": [node["id"] for node in nodes],
    }


def next_ready_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    """Return the next ready node that is still pending."""
    nodes = {node.get("id"): node for node in graph.get("nodes", [])}
    for node in graph.get("nodes", []):
        if node.get("status", "pending") != "pending":
            continue
        deps = node.get("depends_on", [])
        if all(nodes.get(dep, {}).get("status") == "completed" for dep in deps):
            return node
    return None


def next_retryable_failed_node(graph: dict[str, Any], max_attempts: int = 2) -> dict[str, Any] | None:
    """Return the next failed node that can still be retried."""
    for node in graph.get("nodes", []):
        if node.get("status") != "failed":
            continue
        if int(node.get("attempts", 0) or 0) < max_attempts:
            return node
    return None


def retry_graph_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Reset a failed node back to pending for another execution attempt."""
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if updated.get("id") == node_id and updated.get("status") == "failed":
            updated["status"] = "pending"
            updated["failed_at"] = None
            updated["last_error"] = None
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def require_human_for_graph_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Move an exhausted failed node into a human-attention state."""
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if updated.get("id") == node_id and updated.get("status") == "failed":
            updated["status"] = "waiting_human"
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def start_graph_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Mark a ready pending node as running."""
    transition_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    ready = {node["id"] for node in _ready_nodes(graph)}
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if updated.get("id") == node_id and updated.get("status", "pending") == "pending" and node_id in ready:
            updated["status"] = "running"
            updated["started_at"] = updated.get("started_at") or transition_time
            updated["completed_at"] = None
            updated["failed_at"] = None
            updated["blocked_at"] = None
            updated["last_error"] = None
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def block_graph_node(graph: dict[str, Any], node_id: str, reason: str | None = None) -> dict[str, Any]:
    """Mark a pending or running node as blocked without blocking independent siblings."""
    transition_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if updated.get("id") == node_id and updated.get("status", "pending") in {"pending", "running", "in_progress"}:
            updated["status"] = "blocked"
            updated["started_at"] = updated.get("started_at")
            updated["completed_at"] = None
            updated["failed_at"] = None
            updated["blocked_at"] = transition_time
            updated["last_error"] = reason
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def fail_graph_node(graph: dict[str, Any], node_id: str, error: str) -> dict[str, Any]:
    """Mark one node as failed and record error details."""
    transition_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if updated.get("id") == node_id:
            updated["status"] = "failed"
            updated["attempts"] = int(updated.get("attempts", 0) or 0) + 1
            updated["started_at"] = updated.get("started_at") or transition_time
            updated["failed_at"] = transition_time
            updated["completed_at"] = None
            updated["blocked_at"] = None
            updated["last_error"] = error
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def progress_graph(graph: dict[str, Any], completed_node_id: str | None = None) -> dict[str, Any]:
    """Advance graph state by optionally completing one node and recomputing readiness."""
    transition_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    nodes = []
    for node in graph.get("nodes", []):
        updated = dict(node)
        if completed_node_id is not None and updated.get("id") == completed_node_id:
            updated["status"] = "completed"
            updated["attempts"] = int(updated.get("attempts", 0) or 0) + 1
            updated["started_at"] = updated.get("started_at") or transition_time
            updated["completed_at"] = transition_time
            updated["failed_at"] = None
            updated["blocked_at"] = None
            updated["last_error"] = None
        nodes.append(updated)
    return _recompute_graph_state({"nodes": nodes})


def _ready_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all pending nodes whose dependencies are complete."""
    nodes = {node.get("id"): node for node in graph.get("nodes", [])}
    ready = []
    for node in graph.get("nodes", []):
        if node.get("status", "pending") != "pending":
            continue
        deps = node.get("depends_on", [])
        if all(nodes.get(dep, {}).get("status") == "completed" for dep in deps):
            ready.append(node)
    return ready


def _recompute_graph_state(graph: dict[str, Any]) -> dict[str, Any]:
    """Recompute graph indexes after a node state transition."""
    nodes = list(graph.get("nodes", []))
    updated_graph = {"nodes": nodes}
    for key, value in graph.items():
        if key != "nodes":
            updated_graph[key] = deepcopy(value)
    completed = []
    failed = []
    blocked = []
    running = []
    waiting_human = []
    for node in nodes:
        status = node.get("status")
        if status == "completed":
            completed.append(node["id"])
            continue
        if status == "failed":
            failed.append(node["id"])
            continue
        if status == "blocked":
            blocked.append(node["id"])
            continue
        if status in {"running", "in_progress"}:
            running.append(node["id"])
            continue
        if status == "waiting_human":
            waiting_human.append(node["id"])
            continue
    updated_graph["ready_nodes"] = [node["id"] for node in _ready_nodes(updated_graph)]
    updated_graph["completed_nodes"] = completed
    updated_graph["failed_nodes"] = failed
    updated_graph["blocked_nodes"] = blocked
    updated_graph["running_nodes"] = running
    updated_graph["waiting_human_nodes"] = waiting_human
    latest_completed = latest_completed_node(updated_graph)
    if latest_completed is not None:
        updated_graph["last_completed_node"] = latest_completed["id"]
    latest_failed = latest_failed_node(updated_graph)
    if latest_failed is not None:
        updated_graph["last_failed_node"] = latest_failed["id"]
    return annotate_graph_for_supervision(updated_graph)


def annotate_graph_for_supervision(
    graph: dict[str, Any],
    *,
    parent_task_id: str | None = None,
    stale_after_seconds: int = 300,
) -> dict[str, Any]:
    """Attach compact supervision metadata to a task graph."""
    updated_graph = deepcopy(graph)
    nodes = [dict(node) for node in updated_graph.get("nodes", [])]
    node_ids = {node.get("id") for node in nodes if node.get("id")}
    dependents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        blockers = _node_blockers(node)
        for blocker in blockers:
            dependents.setdefault(blocker, []).append(node_id)
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        blockers = _node_blockers(node)
        node["parent_task_id"] = node.get("parent_task_id") or parent_task_id
        node["child_task_ids"] = list(node.get("child_task_ids") or dependents.get(node_id, []))
        node["needs_from"] = list(node.get("needs_from") or blockers)
        node["block_reason"] = _block_reason(node)
        node["last_touched_at"] = _last_touched_at(node)
        node["progress_state"] = compact_progress_state(
            node,
            stale_after_seconds=stale_after_seconds,
        )
    updated_graph["nodes"] = nodes
    updated_graph["task_manifest"] = task_manifest_from_graph(
        updated_graph,
        parent_task_id=parent_task_id,
        stale_after_seconds=stale_after_seconds,
    )
    updated_graph["supervision_summary"] = supervision_summary(
        updated_graph,
        stale_after_seconds=stale_after_seconds,
    )
    return updated_graph


def task_manifest_from_graph(
    graph: dict[str, Any],
    *,
    parent_task_id: str | None = None,
    stale_after_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Return a compact manifest for live supervision of spawned subtasks."""
    nodes = [dict(node) for node in graph.get("nodes", [])]
    node_ids = {node.get("id") for node in nodes if node.get("id")}
    dependents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        for blocker in _node_blockers(node):
            dependents.setdefault(blocker, []).append(node_id)

    manifest: list[dict[str, Any]] = []
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        blockers = _node_blockers(node)
        manifest.append(
            {
                "task_id": parent_task_id or graph.get("parent_task_id"),
                "node_id": node_id,
                "title": node.get("title"),
                "status": node.get("status", "pending"),
                "progress_state": compact_progress_state(
                    node,
                    stale_after_seconds=stale_after_seconds,
                ),
                "parent_task_id": node.get("parent_task_id") or parent_task_id or graph.get("parent_task_id"),
                "child_task_ids": list(node.get("child_task_ids") or dependents.get(node_id, [])),
                "needs_from": list(node.get("needs_from") or blockers),
                "block_reason": _block_reason(node),
                "attempts": int(node.get("attempts", 0) or 0),
                "updated_at": _last_touched_at(node),
                "context_pack_summary": (
                    dict(node.get("context_pack_summary"))
                    if isinstance(node.get("context_pack_summary"), dict)
                    else None
                ),
            }
        )
    return manifest


def supervision_summary(graph: dict[str, Any], *, stale_after_seconds: int = 300) -> dict[str, int]:
    """Summarize task graph nodes by compact supervision state."""
    summary = {
        "running": 0,
        "blocked": 0,
        "waiting_user": 0,
        "stale": 0,
        "done": 0,
        "total": 0,
    }
    for node in graph.get("nodes", []):
        summary["total"] += 1
        summary[compact_progress_state(node, stale_after_seconds=stale_after_seconds)] += 1
    return summary


def compact_progress_state(node: dict[str, Any], *, stale_after_seconds: int = 300) -> str:
    """Map a verbose graph node status to the compact supervision set."""
    status = str(node.get("status", "pending")).strip().lower()
    block_reason = _block_reason(node).lower()
    if status in {"completed", "complete"}:
        return "done"
    if status in {"waiting_human", "waiting_user"} or "human" in block_reason or "user" in block_reason:
        return "waiting_user"
    if _is_stale(node, stale_after_seconds=stale_after_seconds):
        return "stale"
    if status in {"blocked", "failed"} or node.get("last_error"):
        return "blocked"
    if status in {"running", "in_progress"}:
        return "running"
    if status == "pending":
        if _node_blockers(node):
            return "blocked"
        return "running"
    return "running"


def _node_blockers(node: dict[str, Any]) -> list[str]:
    blockers = node.get("needs_from")
    if isinstance(blockers, list) and blockers:
        return [str(item) for item in blockers]
    blockers = node.get("blocked_by")
    if isinstance(blockers, list) and blockers:
        return [str(item) for item in blockers]
    blockers = node.get("depends_on")
    if isinstance(blockers, list) and blockers:
        return [str(item) for item in blockers]
    return []


def _block_reason(node: dict[str, Any]) -> str:
    for key in ("block_reason", "last_error", "reason"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    blockers = _node_blockers(node)
    if blockers:
        return f"waiting on {', '.join(blockers)}"
    return ""


def _last_touched_at(node: dict[str, Any]) -> str | None:
    for key in ("last_touched_at", "completed_at", "failed_at", "blocked_at", "started_at"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_stale(node: dict[str, Any], *, stale_after_seconds: int) -> bool:
    timestamp = _last_touched_at(node)
    if not timestamp:
        return False
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(UTC) - parsed.astimezone(UTC)
    return age.total_seconds() >= stale_after_seconds and str(node.get("status", "")).lower() in {
        "running",
        "in_progress",
        "pending",
        "blocked",
    }
