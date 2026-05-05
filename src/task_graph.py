"""Task graph helpers for dependency-aware execution planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TaskNode:
    """Single planned unit of work."""

    id: str
    title: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    blocked_at: str | None = None
    last_error: str | None = None

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "depends_on": self.depends_on,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "blocked_at": self.blocked_at,
            "last_error": self.last_error,
        }


@dataclass
class TaskGraph:
    """Minimal task graph artifact built from a plan."""

    nodes: list[TaskNode] = field(default_factory=list)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_artifact() for node in self.nodes],
            "ready_nodes": [node.id for node in self.nodes if not node.depends_on],
        }


def graph_from_plan(plan: dict[str, Any]) -> TaskGraph:
    """Build a simple sequential task graph from a plan's steps."""
    steps = plan.get("steps", [])
    nodes: list[TaskNode] = []
    previous_id: str | None = None
    for index, step in enumerate(steps, start=1):
        node_id = f"step-{index}"
        depends_on = [previous_id] if previous_id is not None else []
        nodes.append(TaskNode(id=node_id, title=str(step), depends_on=depends_on))
        previous_id = node_id
    return TaskGraph(nodes=nodes)


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
    return updated_graph
