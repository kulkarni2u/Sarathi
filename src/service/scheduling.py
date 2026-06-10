"""Subtask scheduling, graph transitions, and task tracking helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.policy import compile_policy_pack
from src.runtime import GraphExecutionPolicy
from src.storage import Storage

from .errors import ServiceError
from .preferences import _optional_text, _required_text


def _service_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _has_approved_gate(storage: Storage, task_id: str, name: str) -> bool:
    return any(
        gate["name"] == name and gate["status"] == "approved"
        for gate in storage.list_approval_gates_for_task(task_id)
    )


def _create_graph_draft(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    workspace_id = task["workspace_id"]
    task_id = task["id"]
    specs = [
        {
            "title": "Confirm plan and task packet",
            "status": "queued",
            "role": "Disha",
            "provider": "Codex",
            "blocked_by": [],
            "evidence_required": ["prd", "acceptance_criteria", "task_packet"],
        },
        {
            "title": "Implement scoped change",
            "status": "blocked",
            "role": "Pravaha",
            "provider": "Codex",
            "blocked_by": ["previous"],
            "evidence_required": ["changed_files", "tests"],
        },
        {
            "title": "Review evidence and AC coverage",
            "status": "blocked",
            "role": "Nirnaya",
            "provider": "Claude",
            "blocked_by": ["previous"],
            "evidence_required": ["review_verdict", "ac_coverage"],
        },
    ]
    created = []
    previous_id = None
    for spec in specs:
        blocked_by = [previous_id] if spec["blocked_by"] == ["previous"] and previous_id else []
        subtask = storage.create_subtask(
            workspace_id=workspace_id,
            task_id=task_id,
            title=spec["title"],
            status=spec["status"],
            metadata={
                "role": spec["role"],
                "provider": spec["provider"],
                "blocked_by": blocked_by,
                "evidence_required": spec["evidence_required"],
                "task_packet": {
                    "goal": spec["title"],
                    "context": task["metadata"].get("source_prompt", task["title"]),
                    "review_criteria": task["metadata"].get("acceptance_criteria", []),
                },
            },
        )
        created.append(subtask)
        previous_id = subtask["id"]
    return _graph_from_subtasks(task_id, created)


def _graph_for_task(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    return _graph_from_subtasks(task["id"], storage.list_subtasks_for_task(task["id"]))


def _schedule_ready_subtasks(
    storage: Storage,
    task: dict[str, Any],
    *,
    only_subtask_ids: set[str] | None = None,
    mode: str = "manual",
) -> dict[str, Any]:
    subtasks = storage.list_subtasks_for_task(task["id"])
    completed = {subtask["id"] for subtask in subtasks if subtask["status"] == "complete"}
    scheduled = []
    blocked = []
    waiting_human = []
    for subtask in subtasks:
        blockers = _blocked_by(subtask)
        should_schedule = (
            subtask["status"] == "queued"
            and all(blocker in completed for blocker in blockers)
            and (only_subtask_ids is None or subtask["id"] in only_subtask_ids)
        )
        if should_schedule:
            metadata = dict(subtask["metadata"])
            metadata["lifecycle"] = {
                **dict(metadata.get("lifecycle", {})),
                "claimed_by": metadata.get("role", "Pravaha"),
                "scheduled_by": "Sutra",
                "schedule_mode": mode,
            }
            updated = storage.update_subtask(subtask["id"], status="in_progress", metadata=metadata)
            scheduled.append(updated)
            storage.create_lifecycle_event(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                event_type="subtask.scheduled",
                payload={
                    "object_id": updated["id"],
                    "status": updated["status"],
                    "role": metadata.get("role"),
                    "provider": metadata.get("provider"),
                    "mode": mode,
                },
            )
        elif subtask["status"] == "blocked":
            blocked.append(subtask["id"])
        elif subtask["status"] == "waiting_human":
            waiting_human.append(subtask["id"])

    refreshed_task = _refresh_task_tracking_state(storage, task["id"])
    graph = _graph_for_task(storage, refreshed_task or task)

    return {
        "task": refreshed_task,
        "scheduled": scheduled,
        "blocked": blocked,
        "waiting_human": waiting_human,
        "coordination_state": graph.get("coordination_state"),
        "fan_out_ready_nodes": graph.get("fan_out_ready_nodes", []),
        "fan_in_nodes": graph.get("fan_in_nodes", []),
    }


def _transition_subtask(
    storage: Storage,
    subtask: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    next_status = _required_text(body, "status")
    if next_status not in {
        "queued",
        "in_progress",
        "blocked",
        "waiting_human",
        "review",
        "complete",
        "failed",
        "skipped",
        "paused",
    }:
        raise ServiceError("invalid_request", "Unsupported subtask status transition.", 400)
    actor = _optional_text(body, "actor") or "Sarathi"
    reason = _optional_text(body, "reason")
    metadata = dict(subtask["metadata"])
    lifecycle = dict(metadata.get("lifecycle", {}))
    lifecycle["last_actor"] = actor
    if reason:
        lifecycle["reason"] = reason
    metadata["lifecycle"] = lifecycle
    updated = storage.update_subtask(subtask["id"], status=next_status, metadata=metadata)
    storage.create_message(
        workspace_id=updated["workspace_id"],
        task_id=updated["task_id"],
        role="assistant",
        content=_sarathi_transition_message(updated, next_status),
    )
    storage.create_lifecycle_event(
        workspace_id=updated["workspace_id"],
        task_id=updated["task_id"],
        event_type="subtask.transitioned",
        payload={
            "object_id": updated["id"],
            "status": updated["status"],
            "actor": actor,
            **({"reason": reason} if reason else {}),
        },
    )
    unblocked = _unblock_ready_dependents(storage, updated["task_id"])
    task = _refresh_task_tracking_state(storage, updated["task_id"])
    auto_schedule = _maybe_auto_schedule_ready_subtasks(
        storage,
        task or {"id": updated["task_id"], "workspace_id": updated["workspace_id"]},
        reason="subtask_completed",
        only_subtask_ids={item["id"] for item in unblocked} if next_status == "complete" else None,
    )
    task = auto_schedule["task"] if auto_schedule["scheduled"] else _refresh_task_tracking_state(
        storage,
        updated["task_id"],
    )
    return {
        "subtask": updated,
        "unblocked": unblocked,
        "auto_scheduled": auto_schedule["scheduled"],
        "task": task,
    }


def _unblock_ready_dependents(storage: Storage, task_id: str) -> list[dict[str, Any]]:
    subtasks = storage.list_subtasks_for_task(task_id)
    completed = {subtask["id"] for subtask in subtasks if subtask["status"] == "complete"}
    unblocked = []
    for subtask in subtasks:
        blockers = _blocked_by(subtask)
        if subtask["status"] == "blocked" and blockers and all(
            blocker in completed for blocker in blockers
        ):
            updated = storage.update_subtask(subtask["id"], status="queued")
            unblocked.append(updated)
            storage.create_lifecycle_event(
                workspace_id=updated["workspace_id"],
                task_id=task_id,
                event_type="subtask.unblocked",
                payload={"object_id": updated["id"], "blocked_by": blockers},
            )
    return unblocked


def _blocked_by(subtask: dict[str, Any]) -> list[str]:
    value = subtask["metadata"].get("blocked_by", [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _graph_from_subtasks(task_id: str, subtasks: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = []
    edges = []
    dependents: dict[str, list[str]] = {}
    for subtask in subtasks:
        metadata = subtask["metadata"]
        blocked_by = _blocked_by(subtask)
        nodes.append(
            {
                "id": subtask["id"],
                "title": subtask["title"],
                "status": subtask["status"],
                "role": metadata.get("role"),
                "provider": metadata.get("provider"),
                "blocked_by": blocked_by,
                "evidence_required": metadata.get("evidence_required", []),
                "task_packet": metadata.get("task_packet", {}),
            }
        )
        for blocker_id in blocked_by:
            edges.append({"from": blocker_id, "to": subtask["id"], "type": "blocks"})
            dependents.setdefault(blocker_id, []).append(subtask["id"])

    ready_nodes = _ready_subtask_ids(subtasks)
    active_nodes = [subtask["id"] for subtask in subtasks if subtask["status"] in {"in_progress", "review"}]
    blocked_nodes = [subtask["id"] for subtask in subtasks if subtask["status"] == "blocked"]
    waiting_human_nodes = [subtask["id"] for subtask in subtasks if subtask["status"] == "waiting_human"]
    complete_nodes = [subtask["id"] for subtask in subtasks if subtask["status"] == "complete"]
    fan_in_nodes = [
        subtask["id"]
        for subtask in subtasks
        if len(_blocked_by(subtask)) > 1
    ]
    fan_out_nodes = [node_id for node_id, children in dependents.items() if len(children) > 1]
    terminal_nodes = [subtask["id"] for subtask in subtasks if not dependents.get(subtask["id"])]
    coordination_state = _coordination_state(
        ready_nodes=ready_nodes,
        active_nodes=active_nodes,
        blocked_nodes=blocked_nodes,
        waiting_human_nodes=waiting_human_nodes,
        fan_in_nodes=fan_in_nodes,
        fan_out_nodes=fan_out_nodes,
    )
    return {
        "task_id": task_id,
        "nodes": nodes,
        "edges": edges,
        "ready_nodes": ready_nodes,
        "active_nodes": active_nodes,
        "blocked_nodes": blocked_nodes,
        "waiting_human_nodes": waiting_human_nodes,
        "complete_nodes": complete_nodes,
        "fan_in_nodes": fan_in_nodes,
        "fan_out_nodes": fan_out_nodes,
        "fan_out_ready_nodes": ready_nodes if len(ready_nodes) > 1 else [],
        "terminal_nodes": terminal_nodes,
        "coordination_state": coordination_state,
    }


def _maybe_auto_schedule_ready_subtasks(
    storage: Storage,
    task: dict[str, Any],
    *,
    reason: str,
    only_subtask_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not _has_approved_gate(storage, task["id"], "Task graph"):
        return {"task": task, "scheduled": []}
    policy = _workspace_graph_execution_policy(storage, task["workspace_id"])
    if not policy.auto_schedule_ready_nodes:
        return {"task": task, "scheduled": []}
    result = _schedule_ready_subtasks(
        storage,
        task,
        only_subtask_ids=only_subtask_ids,
        mode="auto",
    )
    if result["scheduled"]:
        storage.create_lifecycle_event(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            event_type="task.auto_schedule",
            payload={
                "object_id": task["id"],
                "reason": reason,
                "scheduled_subtask_ids": [item["id"] for item in result["scheduled"]],
            },
        )
    return result


def _workspace_graph_execution_policy(
    storage: Storage,
    workspace_id: str,
) -> GraphExecutionPolicy:
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        return GraphExecutionPolicy()
    policy_pack = Path(workspace["root_path"]).expanduser() / "policy-pack"
    compiled = compile_policy_pack(str(policy_pack))
    return GraphExecutionPolicy.from_policy_sections(
        task_tracking=compiled.get("task_tracking"),
        escalation=compiled.get("escalation"),
        use_env_overrides=False,
    )


def _ready_subtask_ids(subtasks: list[dict[str, Any]]) -> list[str]:
    completed = {subtask["id"] for subtask in subtasks if subtask["status"] == "complete"}
    ready: list[str] = []
    for subtask in subtasks:
        if subtask["status"] != "queued":
            continue
        blockers = _blocked_by(subtask)
        if all(blocker in completed for blocker in blockers):
            ready.append(subtask["id"])
    return ready


def _coordination_state(
    *,
    ready_nodes: list[str],
    active_nodes: list[str],
    blocked_nodes: list[str],
    waiting_human_nodes: list[str],
    fan_in_nodes: list[str],
    fan_out_nodes: list[str],
) -> str:
    if waiting_human_nodes:
        return "waiting_human"
    if len(ready_nodes) > 1:
        return "fan_out_ready"
    if active_nodes:
        return "active"
    if fan_in_nodes and blocked_nodes:
        return "fan_in_blocked"
    if blocked_nodes:
        return "blocked"
    if ready_nodes:
        return "ready"
    if fan_out_nodes:
        return "fan_out_complete"
    return "idle"


def _refresh_task_tracking_state(storage: Storage, task_id: str) -> dict[str, Any]:
    task = storage.get_task(task_id)
    if task is None:
        raise ServiceError("not_found", "Task not found.", 404)
    subtasks = storage.list_subtasks_for_task(task_id)
    if not subtasks:
        return task
    graph = _graph_from_subtasks(task_id, subtasks)
    next_status, next_phase = _task_tracking_status_from_graph(graph)
    metadata = dict(task["metadata"])
    metadata["phase"] = next_phase
    metadata["coordination_state"] = graph["coordination_state"]
    metadata["graph_summary"] = {
        "ready": len(graph["ready_nodes"]),
        "active": len(graph["active_nodes"]),
        "blocked": len(graph["blocked_nodes"]),
        "waiting_human": len(graph["waiting_human_nodes"]),
        "complete": len(graph["complete_nodes"]),
        "fan_in": len(graph["fan_in_nodes"]),
        "fan_out": len(graph["fan_out_nodes"]),
    }
    return storage.update_task(task_id, status=next_status, metadata=metadata)


def _task_tracking_status_from_graph(graph: dict[str, Any]) -> tuple[str, str]:
    nodes = graph.get("nodes", [])
    if not nodes:
        return "pending", "pending"
    statuses = {node.get("status") for node in nodes}
    if statuses == {"complete"}:
        return "review", "Review"
    if graph.get("waiting_human_nodes"):
        return "waiting_human", "TaskTracking"
    if graph.get("active_nodes"):
        return "in_progress", "TaskTracking"
    if any(node.get("status") == "review" for node in nodes):
        return "review", "Review"
    if graph.get("ready_nodes"):
        return "queued", "TaskTracking"
    if graph.get("blocked_nodes"):
        return "blocked", "TaskTracking"
    if "failed" in statuses:
        return "blocked", "TaskTracking"
    if "queued" in statuses:
        return "queued", "TaskTracking"
    return "pending", "TaskTracking"


def _sarathi_transition_message(subtask: dict[str, Any], new_status: str) -> str:
    title = subtask.get("title", "Unit")
    msgs = {
        "in_progress": f"Starting: {title}",
        "review": f"Unit complete: {title}. Ready for review.",
        "completed": f"Done: {title}.",
        "failed": f"Unit failed: {title}. Check dispatch log for details.",
    }
    return msgs.get(new_status, f"Unit {title} → {new_status}")

