"""Workspace and task view-model assembly helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.runtime import UsageRecord, list_agent_roles
from src.storage import Storage

from .errors import ServiceError
from .preferences import (
    _default_auto_approve_preference,
    _default_repository_action_preference,
    _effective_repository_action_preference,
    _normalize_auto_approve_preference,
    _normalize_repository_action_preference,
    _normalize_reuse_preferences,
)
from .providers import _get_provider_priority, _provider_health, _select_available_provider
from .scheduling import _graph_for_task


def _latest_or_none(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[-1] if items else None


def _unique_ordered(values: Any) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _task_studio_snapshot(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["id"]
    graph = _graph_for_task(storage, task)
    approvals = storage.list_approval_gates_for_task(task_id)
    reviews = storage.list_review_runs_for_task(task_id)
    latest_handoff = _latest_or_none(storage.list_handoffs_for_task(task_id))
    latest_checkpoint = _latest_or_none(storage.list_checkpoint_capsules_for_task(task_id))
    workspace = storage.get_workspace(task["workspace_id"])
    return {
        "task": task,
        "graph": graph,
        "header": _task_studio_header(
            task,
            graph=graph,
            approvals=approvals,
            reviews=reviews,
            handoff=latest_handoff,
            checkpoint=latest_checkpoint,
            workspace=workspace,
        ),
        "messages": storage.list_messages(task_id=task_id),
        "approval_gates": approvals,
        "events": storage.list_events(task_id=task_id),
        "dispatches": storage.list_dispatches_for_task(task_id),
        "evidence": storage.list_evidence_artifacts_for_task(task_id),
        "reviews": reviews,
        "handoff": latest_handoff,
    }


def _workspace_operational_views(storage: Storage, workspace_id: str) -> dict[str, Any]:
    tasks = storage.list_tasks_for_workspace(workspace_id)
    projects = storage.list_projects(workspace_id)
    repositories = storage.list_workspace_repositories(workspace_id)
    history = storage.list_events(workspace_id=workspace_id)
    messages = storage.list_messages(workspace_id=workspace_id)
    workspace = storage.get_workspace(workspace_id)
    providers = _provider_health(storage, workspace_id)
    all_subtasks: list[dict[str, Any]] = []
    all_dispatches: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []
    all_reviews: list[dict[str, Any]] = []
    all_handoffs: list[dict[str, Any]] = []
    diagrams: list[dict[str, Any]] = []
    project_rollups: dict[str, dict[str, int]] = {
        project["id"]: {
            "approval_pending_count": 0,
            "checkpoint_ready_count": 0,
            "handoff_ready_count": 0,
        }
        for project in projects
    }

    for task in tasks:
        graph = _graph_for_task(storage, task)
        subtasks = storage.list_subtasks_for_task(task["id"])
        approvals = storage.list_approval_gates_for_task(task["id"])
        dispatches = storage.list_dispatches_for_task(task["id"])
        evidence = storage.list_evidence_artifacts_for_task(task["id"])
        reviews = storage.list_review_runs_for_task(task["id"])
        handoffs = storage.list_handoffs_for_task(task["id"])
        latest_checkpoint = _latest_or_none(storage.list_checkpoint_capsules_for_task(task["id"]))
        latest_handoff = _latest_or_none(handoffs)
        all_subtasks.extend(subtasks)
        all_dispatches.extend(dispatches)
        all_evidence.extend(evidence)
        all_reviews.extend(reviews)
        all_handoffs.extend(handoffs)
        project_id = str((task.get("metadata") or {}).get("project_id") or "")
        if project_id and project_id in project_rollups:
            header = _task_studio_header(
                task,
                graph=graph,
                approvals=approvals,
                reviews=reviews,
                handoff=latest_handoff,
                checkpoint=latest_checkpoint,
                workspace=workspace,
            )
            if header["approval_state"] not in {"approved", "none"}:
                project_rollups[project_id]["approval_pending_count"] += 1
            if header["checkpoint_ready"]:
                project_rollups[project_id]["checkpoint_ready_count"] += 1
            if header["handoff_state"] == "ready":
                project_rollups[project_id]["handoff_ready_count"] += 1
        if graph["nodes"]:
            diagrams.append(
                {
                    "id": f"dependency-{task['id']}",
                    "kind": "dependency_graph",
                    "title": task["title"],
                    "task_id": task["id"],
                    "nodes": graph["nodes"],
                    "edges": graph["edges"],
                    "updated_at": task["updated_at"],
                }
            )
        if reviews:
            diagrams.append(
                {
                    "id": f"review-loop-{task['id']}",
                    "kind": "review_loop",
                    "title": f"Review loop: {task['title']}",
                    "task_id": task["id"],
                    "nodes": [
                        {"id": review["id"], "status": review["status"], "summary": review["summary"]}
                        for review in reviews
                    ],
                    "edges": [
                        {"from": reviews[index]["id"], "to": reviews[index + 1]["id"], "type": "iteration"}
                        for index in range(len(reviews) - 1)
                    ],
                }
            )
        if latest_handoff is not None:
            diagrams.append(
                {
                    "id": f"handoff-{task['id']}",
                    "kind": "handoff",
                    "title": f"Handoff: {task['title']}",
                    "task_id": task["id"],
                    "summary": latest_handoff["summary"],
                    "repository_action": latest_handoff["metadata"].get("repository_action", {}),
                }
            )

    lifecycle = _workspace_lifecycle_roles(tasks, all_subtasks, messages, history)
    diagrams.append(
        {
            "id": f"agent-lifecycle-{workspace_id}",
            "kind": "agent_lifecycle",
            "title": "Sarathi agent lifecycle",
            "nodes": lifecycle,
            "edges": [
                {"from": lifecycle[index]["name"], "to": lifecycle[index + 1]["name"], "type": "hands_off_to"}
                for index in range(len(lifecycle) - 1)
            ],
        }
    )

    project_summaries: list[dict[str, Any]] = []
    for project in projects:
        stats = storage.get_project_stats(project["id"])
        rollup = project_rollups.get(project["id"], {})
        project_summaries.append(
            {
                **project,
                "task_count": stats["task_count"],
                "blocked_count": stats["blocked_count"],
                "review_needed_count": stats["review_needed_count"],
                "approval_pending_count": int(rollup.get("approval_pending_count", 0)),
                "checkpoint_ready_count": int(rollup.get("checkpoint_ready_count", 0)),
                "handoff_ready_count": int(rollup.get("handoff_ready_count", 0)),
                "updated_at": stats["last_activity"] or project["updated_at"],
            }
        )

    inbox = _build_inbox_items(storage, tasks)
    workspace_metadata = (workspace.get("metadata") or {}) if workspace else {}

    governance = _workspace_governance(
        storage,
        workspace_id,
        workspace_metadata,
        providers,
        history,
        all_handoffs,
    )

    return {
        "workspace_id": workspace_id,
        "summary": {
            "project_count": len(project_summaries),
            "approvals_pending": sum(1 for item in inbox if item["kind"] == "approval"),
            "checkpoint_ready_count": sum(1 for item in inbox if item["kind"] == "checkpoint_ready"),
            "handoff_ready_count": sum(1 for item in inbox if item["kind"] == "handoff_ready"),
            "provider_online_count": len([provider for provider in providers if provider["health"] == "online"]),
        },
        "projects": project_summaries,
        "inbox": inbox,
        "history": history,
        "lifecycle": lifecycle,
        "diagrams": diagrams,
        "governance": governance,
        "usage": {
            "tasks": {
                "total": len(tasks),
                "active": len([task for task in tasks if task["status"] not in {"done", "skipped"}]),
                "done": len([task for task in tasks if task["status"] == "done"]),
                "by_status": _count_by(tasks, "status"),
            },
            "subtasks": {
                "total": len(all_subtasks),
                "by_status": _count_by(all_subtasks, "status"),
            },
            "events": {"total": len(history), "by_type": _count_by(history, "event_type")},
            "messages": {"total": len(messages), "by_role": _count_by(messages, "role")},
            "repositories": {"total": len(repositories)},
            "dispatches": {"total": len(all_dispatches), "by_status": _count_by(all_dispatches, "status")},
            "budget": _workspace_budget_summary(all_dispatches),
            "evidence": {"total": len(all_evidence), "by_type": _count_by(all_evidence, "artifact_type")},
            "reviews": {"total": len(all_reviews), "by_status": _count_by(all_reviews, "status")},
            "handoffs": {"total": len(all_handoffs)},
            "providers": {
                "total": len(providers),
                "online": len([provider for provider in providers if provider["health"] == "online"]),
                "by_health": _count_by(providers, "health"),
            },
        },
    }


def _workspace_governance(
    storage: Storage,
    workspace_id: str,
    workspace_metadata: dict[str, Any],
    providers: list[dict[str, Any]],
    history: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
) -> dict[str, Any]:
    repository_action_preference = _normalize_repository_action_preference(
        workspace_metadata.get("repository_action_preference"),
        fallback_scope="workspace",
    ) or _default_repository_action_preference()
    auto_approve_preference = _normalize_auto_approve_preference(
        workspace_metadata.get("auto_approve_preference"),
        fallback_scope="workspace",
    ) or _default_auto_approve_preference()
    provider_priority = _get_provider_priority(storage, workspace_id)
    policy_posture = {
        "repository_action_preference": repository_action_preference,
        "auto_approve_preference": auto_approve_preference,
        "provider_priority": provider_priority,
        "provider_priority_source": "workspace" if workspace_metadata.get("provider_priority") else "default",
    }

    provider_map = {p["id"]: p for p in providers}
    provider_health_map = {p["id"]: p.get("health", "offline") for p in providers}

    selected_provider = _select_available_provider(storage, workspace_id, provider_priority)
    fallback_candidates = [
        pid for pid in provider_priority
        if pid != selected_provider and provider_map.get(pid) is not None
    ]

    provider_routing = {
        "priority_order": provider_priority,
        "selected_provider": selected_provider or "local",
        "fallback_candidates": fallback_candidates,
        "provider_health": {
            pid: provider_health_map.get(pid, "unknown") for pid in provider_priority if pid in provider_map
        },
        "providers": [
            {
                "id": provider["id"],
                "name": provider["name"],
                "health": provider["health"],
                "auth": provider["auth"],
                "transport_posture": provider.get("transport_posture"),
                "degraded_reason": provider.get("degraded_reason"),
                "last_error": provider.get("last_error"),
                "model": provider.get("model"),
            }
            for provider in providers
        ],
    }

    override_history: list[dict[str, Any]] = []
    for event in history:
        payload = event.get("payload") or {}
        event_type = str(event.get("event_type") or "")
        if event_type == "workspace.governance_updated":
            changed_keys = payload.get("changed_keys", [])
            override_history.append(
                {
                    "id": event["id"],
                    "event_type": event_type,
                    "task_id": event.get("task_id"),
                    "summary": f"Workspace governance updated: {', '.join(changed_keys) if isinstance(changed_keys, list) and changed_keys else 'governance settings'}",
                    "severity": "warning",
                    "created_at": event["created_at"],
                    "metadata": payload,
                }
            )
        elif event_type == "approval.recorded" and payload.get("auto_approved") is True:
            override_history.append(
                {
                    "id": event["id"],
                    "event_type": event_type,
                    "task_id": event.get("task_id"),
                    "summary": "A pending gate was auto-approved under workspace policy.",
                    "severity": "warning",
                    "created_at": event["created_at"],
                    "metadata": payload,
                }
            )
        elif event_type == "repository_action.approved":
            override_history.append(
                {
                    "id": event["id"],
                    "event_type": event_type,
                    "task_id": event.get("task_id"),
                    "summary": f"Repository action approved: {payload.get('action') or 'no_action'}",
                    "severity": "active",
                    "created_at": event["created_at"],
                    "metadata": payload,
                }
            )
        elif event_type == "provider.health_checked":
            health = str(payload.get("health") or "")
            if health in {"offline", "rate_limited"}:
                override_history.append(
                    {
                        "id": event["id"],
                        "event_type": event_type,
                        "task_id": event.get("task_id"),
                        "summary": f"Provider posture changed: {payload.get('object_id') or 'provider'} is {health}.",
                        "severity": "warning",
                        "created_at": event["created_at"],
                        "metadata": payload,
                    }
                )
    override_history = sorted(override_history, key=lambda item: item["created_at"], reverse=True)[:10]

    task_titles = {task["id"]: task["title"] for task in storage.list_tasks_for_workspace(workspace_id)}
    repository_action_recent = []
    for handoff in sorted(handoffs, key=lambda item: item["created_at"], reverse=True):
        metadata = handoff.get("metadata") or {}
        repository_action = metadata.get("repository_action") or {}
        repository_action_preference = metadata.get("repository_action_preference") or {}
        repository_action_recent.append(
            {
                "id": handoff["id"],
                "task_id": handoff["task_id"],
                "title": task_titles.get(handoff["task_id"], "Unknown task"),
                "summary": handoff["summary"],
                "status": repository_action.get("status", "pending"),
                "action": repository_action.get("action") or repository_action.get("mode") or repository_action_preference.get("mode") or "no_action",
                "mode": repository_action_preference.get("mode") or repository_action.get("mode") or "no_action",
                "created_at": handoff["created_at"],
            }
        )
    repository_action_recent = repository_action_recent[:8]

    repository_action_governance = {
        "pending_count": sum(1 for item in repository_action_recent if item["status"] == "pending"),
        "approved_count": sum(1 for item in repository_action_recent if item["status"] == "approved"),
        "recent": repository_action_recent,
    }

    return {
        "policy_posture": policy_posture,
        "provider_routing": provider_routing,
        "override_history": override_history,
        "repository_action_governance": repository_action_governance,
    }


def _workspace_reuse_kit(storage: Storage, workspace_id: str) -> dict[str, Any]:
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)

    reuse_preferences = _normalize_reuse_preferences((workspace.get("metadata") or {}).get("reuse_preferences")) or {}
    operations = _workspace_operational_views(storage, workspace_id)
    templates = _builtin_workflow_templates()
    saved_views = _workspace_saved_views(
        operations,
        custom_saved_views=reuse_preferences.get("custom_saved_views") or [],
    )
    playbooks = _workspace_learning_playbooks(
        storage,
        workspace,
        templates=templates,
        saved_views=saved_views,
    )
    return {
        "workspace_id": workspace_id,
        "active_saved_view_id": reuse_preferences.get("active_saved_view_id") or "all-projects",
        "templates": templates,
        "saved_views": saved_views,
        "playbooks": playbooks,
    }


def _builtin_workflow_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "feature-delivery",
            "name": "Feature delivery",
            "category": "delivery",
            "summary": "Turn a feature request into PRD, AC coverage, governed execution, review, and final handoff.",
            "complexity": "medium",
            "starter_title": "Template: feature delivery",
            "recommended_repository_action_mode": "draft_pr",
            "recommended_auto_approve_mode": "below_threshold",
            "suggested_provider_priority": ["codex", "claude", "copilot", "opencode"],
            "recommended_view_ids": ["approvals-inbox", "handoff-readiness"],
        },
        {
            "id": "bugfix-regression",
            "name": "Bug fix and regression guard",
            "category": "stability",
            "summary": "Bias the workflow toward root-cause clarity, targeted implementation, and explicit regression proof.",
            "complexity": "low",
            "starter_title": "Template: bug fix and regression guard",
            "recommended_repository_action_mode": "prepare_patch",
            "recommended_auto_approve_mode": "manual_only",
            "suggested_provider_priority": ["claude", "codex", "copilot", "opencode"],
            "recommended_view_ids": ["blocked-projects", "approvals-inbox"],
        },
        {
            "id": "governed-release-handoff",
            "name": "Governed release handoff",
            "category": "handoff",
            "summary": "Focus the team on checklist completion, repository posture, acceptance coverage, and a release-ready dossier.",
            "complexity": "high",
            "starter_title": "Template: governed release handoff",
            "recommended_repository_action_mode": "ready_pr",
            "recommended_auto_approve_mode": "manual_only",
            "suggested_provider_priority": ["claude", "codex", "copilot", "opencode"],
            "recommended_view_ids": ["handoff-readiness", "governance-overrides"],
        },
        {
            "id": "provider-recovery",
            "name": "Provider recovery and fallback",
            "category": "operations",
            "summary": "Stabilize degraded providers, validate fallback order, and capture routing decisions as durable evidence.",
            "complexity": "medium",
            "starter_title": "Template: provider recovery and fallback",
            "recommended_repository_action_mode": "no_action",
            "recommended_auto_approve_mode": "manual_only",
            "suggested_provider_priority": ["claude", "codex", "copilot", "opencode"],
            "recommended_view_ids": ["provider-posture", "governance-overrides"],
        },
    ]


def _saved_view_count(filters: Mapping[str, Any], operations: dict[str, Any]) -> int:
    governance = operations.get("governance") or {}
    provider_routing = governance.get("provider_routing") or {}
    repository_action_governance = governance.get("repository_action_governance") or {}
    override_history = governance.get("override_history") or []
    provider_rows = provider_routing.get("providers") or []
    degraded_provider_count = len(
        [provider for provider in provider_rows if provider.get("health") not in {"online", "unknown"}]
    )
    blocked_projects = len(
        [project for project in operations.get("projects") or [] if int(project.get("blocked_count") or 0) > 0]
    )
    if filters.get("kind") == "approval" or filters.get("task_state") == "approval_pending":
        return int((operations.get("summary") or {}).get("approvals_pending") or 0)
    if filters.get("project_state") == "blocked":
        return blocked_projects
    if filters.get("task_state") == "handoff_ready":
        return int((operations.get("summary") or {}).get("handoff_ready_count") or 0)
    if filters.get("task_state") == "checkpoint_ready":
        return int((operations.get("summary") or {}).get("checkpoint_ready_count") or 0)
    if filters.get("provider_health") == "degraded_or_offline":
        return degraded_provider_count
    if filters.get("governance") == "overrides":
        return len(override_history) + int(repository_action_governance.get("pending_count") or 0)
    return len(operations.get("projects") or [])


def _workspace_saved_views(
    operations: dict[str, Any],
    *,
    custom_saved_views: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    saved_views = [
        {
            "id": "all-projects",
            "name": "All projects",
            "role": "workspace",
            "route": "workspace",
            "description": "Default workspace view with every attached project visible.",
            "metric_label": "visible projects",
            "count": _saved_view_count({"project_state": "all"}, operations),
            "filters": {"project_state": "all"},
            "origin": "builtin",
        },
        {
            "id": "approvals-inbox",
            "name": "Approval inbox",
            "role": "operator",
            "route": "inbox",
            "description": "Review pending gates and human decisions without scanning the full workspace.",
            "metric_label": "pending approvals",
            "count": _saved_view_count({"kind": "approval"}, operations),
            "filters": {"kind": "approval"},
            "origin": "builtin",
        },
        {
            "id": "blocked-projects",
            "name": "Blocked projects",
            "role": "tech_lead",
            "route": "workspace",
            "description": "Jump straight to blocked delivery work that needs routing or repository decisions.",
            "metric_label": "blocked projects",
            "count": _saved_view_count({"project_state": "blocked"}, operations),
            "filters": {"project_state": "blocked"},
            "origin": "builtin",
        },
        {
            "id": "handoff-readiness",
            "name": "Handoff readiness",
            "role": "product_owner",
            "route": "workspace",
            "description": "Track what is ready for governed handoff and where final proof is still missing.",
            "metric_label": "handoff-ready tasks",
            "count": _saved_view_count({"task_state": "handoff_ready"}, operations),
            "filters": {"task_state": "handoff_ready"},
            "origin": "builtin",
        },
        {
            "id": "checkpoint-queue",
            "name": "Checkpoint queue",
            "role": "operator",
            "route": "workspace",
            "description": "Resume work from persisted checkpoints instead of asking agents to rediscover state.",
            "metric_label": "checkpoint-ready tasks",
            "count": _saved_view_count({"task_state": "checkpoint_ready"}, operations),
            "filters": {"task_state": "checkpoint_ready"},
            "origin": "builtin",
        },
        {
            "id": "provider-posture",
            "name": "Provider posture",
            "role": "workspace_admin",
            "route": "settings",
            "description": "Inspect degraded providers, fallback ordering, and SDK or CLI routing posture in one place.",
            "metric_label": "degraded providers",
            "count": _saved_view_count({"provider_health": "degraded_or_offline"}, operations),
            "filters": {"provider_health": "degraded_or_offline"},
            "origin": "builtin",
        },
        {
            "id": "governance-overrides",
            "name": "Governance overrides",
            "role": "owner",
            "route": "settings",
            "description": "Inspect recent auto-approvals, routing changes, and repository-action decisions with audit context.",
            "metric_label": "recent overrides",
            "count": _saved_view_count({"governance": "overrides"}, operations),
            "filters": {"governance": "overrides"},
            "origin": "builtin",
        },
    ]
    for definition in custom_saved_views or []:
        filters = definition.get("filters") or {}
        saved_views.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "role": definition.get("role") or "custom",
                "route": definition.get("route") or "workspace",
                "description": definition.get("description") or "Custom saved view.",
                "metric_label": definition.get("metric_label") or "matching items",
                "count": _saved_view_count(filters, operations),
                "filters": filters,
                "origin": "custom",
            }
        )
    return saved_views


def _workspace_learning_playbooks(
    storage: Storage,
    workspace: dict[str, Any],
    *,
    templates: list[dict[str, Any]],
    saved_views: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    learning_path = workspace_root / "learnings.md"
    if not learning_path.exists():
        return []

    learning_sections = _parse_workspace_learnings(learning_path)
    if not learning_sections:
        return []

    accepted_events = [
        event
        for event in storage.list_events(workspace_id=workspace["id"])
        if event.get("event_type") == "learning.accepted"
    ]
    events_by_task = {
        str((event.get("payload") or {}).get("task_id") or ""): event for event in accepted_events
    }
    template_ids = {template["id"] for template in templates}
    saved_view_ids = {view["id"] for view in saved_views}

    playbooks: list[dict[str, Any]] = []
    for index, section in enumerate(learning_sections[:4]):
        recommended_template_id = _playbook_template_for_learning(section)
        event = events_by_task.get(section.get("task_id") or "")
        recommended_views = [
            view_id
            for view_id in _playbook_saved_views_for_learning(section)
            if view_id in saved_view_ids
        ]
        playbooks.append(
            {
                "id": event["id"] if event is not None else f"learning-playbook-{index + 1}",
                "name": section.get("title") or f"Accepted learning {index + 1}",
                "summary": section.get("summary") or "Accepted learning with reusable operator guidance.",
                "recommended_template_id": recommended_template_id if recommended_template_id in template_ids else None,
                "recommended_view_ids": recommended_views,
                "source": "accepted_learning",
                "provenance": {
                    "task_id": section.get("task_id"),
                    "source_file": str(learning_path),
                    "event_id": event["id"] if event is not None else None,
                    "evidence_refs": section.get("evidence_refs") or [],
                    "tags": section.get("tags") or [],
                },
            }
        )
    return playbooks


def _parse_workspace_learnings(learning_path: Path) -> list[dict[str, Any]]:
    content = learning_path.read_text(encoding="utf-8")
    sections: list[dict[str, Any]] = []
    for raw_section in content.split("\n## "):
        section = raw_section.strip()
        if not section:
            continue
        title_line, _, remainder = section.partition("\n")
        normalized_title = title_line.strip().removeprefix("## ").strip()
        if "Accepted" not in normalized_title:
            continue
        parsed = {
            "title": normalized_title,
            "summary": "",
            "task_id": "",
            "tags": [],
            "evidence_refs": [],
        }
        for line in remainder.splitlines():
            stripped = line.strip()
            if stripped.startswith("- Task:"):
                parsed["task_id"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- Summary:"):
                parsed["summary"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- Tags:"):
                parsed["tags"] = [
                    part.strip()
                    for part in stripped.split(":", 1)[1].split(",")
                    if part.strip()
                ]
            elif stripped.startswith("- ") and ":" in stripped and "(" in stripped and ")" in stripped:
                evidence = stripped.split("(", 1)[1].rstrip(")")
                parsed["evidence_refs"].extend(
                    [part.strip() for part in evidence.split(",") if part.strip() and part.strip() != "no refs"]
                )
        sections.append(parsed)
    return sections


def _playbook_template_for_learning(section: dict[str, Any]) -> str:
    summary = str(section.get("summary") or "").lower()
    tags = {str(tag).lower() for tag in section.get("tags") or []}
    has_dogfood_tag = any("dogfood" in tag for tag in tags)
    if "bug" in summary or "regression" in summary:
        return "bugfix-regression"
    if "provider" in summary or "routing" in summary or "fallback" in summary:
        return "provider-recovery"
    if "handoff" in summary or "release" in summary or has_dogfood_tag:
        return "governed-release-handoff"
    return "feature-delivery"


def _playbook_saved_views_for_learning(section: dict[str, Any]) -> list[str]:
    summary = str(section.get("summary") or "").lower()
    tags = {str(tag).lower() for tag in section.get("tags") or []}
    has_dogfood_tag = any("dogfood" in tag for tag in tags)
    if "provider" in summary or "routing" in summary or "fallback" in summary:
        return ["provider-posture", "governance-overrides"]
    if "release" in summary or "handoff" in summary or has_dogfood_tag:
        return ["handoff-readiness", "governance-overrides"]
    if "bug" in summary or "regression" in summary:
        return ["blocked-projects", "approvals-inbox"]
    return ["approvals-inbox", "checkpoint-queue"]


def _workspace_lifecycle_roles(
    tasks: list[dict[str, Any]],
    subtasks: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    role_counts: dict[str, int] = {}
    for subtask in subtasks:
        role = subtask["metadata"].get("role")
        if isinstance(role, str):
            role_counts[role.lower()] = role_counts.get(role.lower(), 0) + 1
    for message in messages:
        role_counts[message["role"].lower()] = role_counts.get(message["role"].lower(), 0) + 1
        target = message["metadata"].get("target")
        if isinstance(target, str):
            role_counts[target.lower()] = role_counts.get(target.lower(), 0) + 1
    for event in events:
        encoded = json.dumps(event["payload"]).lower()
        for role in list_agent_roles():
            if role.name.lower() in encoded:
                role_counts[role.name.lower()] = role_counts.get(role.name.lower(), 0) + 1
    if tasks:
        role_counts["sarathi"] = role_counts.get("sarathi", 0) + len(tasks)

    return [
        {
            "key": role.key,
            "name": role.name,
            "purpose": role.purpose,
            "description": role.description,
            "state": "active" if role_counts.get(role.name.lower(), 0) else "idle",
            "event_count": role_counts.get(role.name.lower(), 0),
        }
        for role in list_agent_roles()
    ]


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _workspace_budget_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any] | None:
    records = _dispatch_usage_records(dispatches)
    if not records:
        return None

    total_tokens = sum(record.total_tokens for record in records)
    budget_limits = [record.budget_limit for record in records if record.budget_limit is not None]
    budget_limit = sum(budget_limits) if budget_limits else None

    budget_remaining = None
    records_with_limit = [record for record in records if record.budget_limit is not None]
    if budget_limit is not None:
        remaining_values = [record.budget_remaining for record in records_with_limit if record.budget_remaining is not None]
        if remaining_values and len(remaining_values) == len(records_with_limit):
            budget_remaining = sum(remaining_values)
        else:
            budget_remaining = max(budget_limit - total_tokens, 0)

    budget_state = _worst_budget_state(records)
    if budget_state == "unknown" and budget_limit is not None:
        ratio = total_tokens / budget_limit if budget_limit > 0 else 1.0
        if ratio >= 1.0:
            budget_state = "exhausted"
        elif ratio >= 0.9:
            budget_state = "near_limit"
        elif ratio >= 0.75:
            budget_state = "warning"
        else:
            budget_state = "ok"

    usage_sources = {record.usage_source for record in records}
    usage_source = usage_sources.pop() if len(usage_sources) == 1 else "mixed"

    return {
        "total_tokens": total_tokens,
        "budget_limit": budget_limit,
        "budget_remaining": budget_remaining,
        "budget_state": budget_state,
        "usage_source": usage_source,
    }


def _dispatch_usage_records(dispatches: list[dict[str, Any]]) -> list[UsageRecord]:
    records: list[UsageRecord] = []
    for dispatch in dispatches:
        metadata = dispatch.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        usage = metadata.get("usage")
        if not isinstance(usage, Mapping):
            continue
        record = UsageRecord.from_mapping(usage)
        if record is not None:
            records.append(record)
    return records


def _worst_budget_state(records: list[UsageRecord]) -> str:
    severity = {"unknown": 0, "ok": 1, "warning": 2, "near_limit": 3, "exhausted": 4}
    active_states = [record.budget_state for record in records if record.budget_state != "unknown"]
    if not active_states:
        return "unknown"
    return max(active_states, key=lambda state: severity[state])


def _task_dashboard(
    storage: Storage,
    workspace_id: str,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    summaries = []
    for task in storage.list_tasks_for_workspace(workspace_id):
        task_project_id = task.get("project_id") or task["metadata"].get("project_id")
        if project_id is not None and task_project_id != project_id:
            continue
        approvals = storage.list_approval_gates_for_task(task["id"])
        graph = _graph_for_task(storage, task)
        next_gate = _next_pending_gate(approvals)
        checkpoints = storage.list_checkpoint_capsules_for_task(task["id"])
        handoffs = storage.list_handoffs_for_task(task["id"])
        latest_checkpoint = _latest_or_none(checkpoints)
        latest_handoff = _latest_or_none(handoffs)
        reviews = storage.list_review_runs_for_task(task["id"])
        handoff_state = _handoff_state(latest_handoff)
        queue_state = _task_studio_queue_state(task, graph, approvals, reviews, handoff_state)
        summaries.append(
            {
                "id": task["id"],
                "workspace_id": task["workspace_id"],
                "project_id": task_project_id,
                "title": task["title"],
                "status": task["status"],
                "queue_state": queue_state,
                "phase": task["metadata"].get("phase", task["status"]),
                "approval_state": _approval_state(approvals),
                "graph_state": _graph_state(graph, approvals),
                "next_gate": next_gate["name"] if next_gate else None,
                "node_count": len(graph["nodes"]),
                "blocked_count": len(graph.get("blocked_nodes", [])) + len(graph.get("waiting_human_nodes", [])),
                "review_needed_count": _review_needed_count(approvals, reviews),
                "coordination_state": graph.get("coordination_state"),
                "fan_out_ready_count": len(graph.get("fan_out_ready_nodes", [])),
                "fan_in_count": len(graph.get("fan_in_nodes", [])),
                "roles": _unique_ordered(
                    str(node["role"]) for node in graph["nodes"] if node.get("role")
                ),
                "providers": _unique_ordered(
                    str(node["provider"]) for node in graph["nodes"] if node.get("provider")
                ),
                "updated_at": task["updated_at"],
                "checkpoint_state": _checkpoint_state(latest_checkpoint),
                "handoff_state": handoff_state,
            }
        )
    return summaries


def _next_pending_gate(approvals: list[dict[str, Any]]) -> dict[str, Any] | None:
    for gate in reversed(_current_approval_gates(approvals)):
        if gate["status"] == "pending":
            return gate
    return None


def _approval_state(approvals: list[dict[str, Any]]) -> str:
    current = _current_approval_gates(approvals)
    if any(gate["name"] == "Task graph" and gate["status"] == "pending" for gate in current):
        return "graph_pending"
    if any(gate["name"] == "PRD/AC" and gate["status"] == "pending" for gate in current):
        return "prd_pending"
    if any(gate["status"] == "pending" for gate in current):
        return "approval_pending"
    return "approved" if current else "none"


def _graph_state(graph: dict[str, Any], approvals: list[dict[str, Any]]) -> str:
    if not graph["nodes"]:
        return "not_started"
    if any(gate["name"] == "Task graph" and gate["status"] == "pending" for gate in _current_approval_gates(approvals)):
        return "pending_approval"
    return "approved"


def _current_approval_gates(approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    current: list[dict[str, Any]] = []
    for gate in reversed(approvals):
        name = str(gate.get("name") or "")
        if name in seen:
            continue
        seen.add(name)
        current.append(gate)
    current.reverse()
    return current


def _checkpoint_state(checkpoint: dict[str, Any] | None) -> str:
    if checkpoint is None:
        return "none"
    return str(checkpoint.get("status") or "ready")


def _handoff_state(handoff: dict[str, Any] | None) -> str:
    if handoff is None:
        return "none"
    metadata = handoff.get("metadata") or {}
    repository_action = metadata.get("repository_action") or {}
    if repository_action.get("status") == "approved":
        return "ready"
    return "draft"


def _review_needed_count(
    approvals: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> int:
    pending_review_gates = sum(
        1
        for gate in approvals
        if gate["status"] == "pending" and str(gate.get("name") or "").lower() == "review"
    )
    rejected_reviews = sum(1 for review in reviews if review["status"] == "rejected")
    return pending_review_gates + rejected_reviews


def _build_inbox_items(storage: Storage, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inbox: list[dict[str, Any]] = []
    for task in tasks:
        approvals = storage.list_approval_gates_for_task(task["id"])
        reviews = storage.list_review_runs_for_task(task["id"])
        latest_checkpoint = _latest_or_none(storage.list_checkpoint_capsules_for_task(task["id"]))
        latest_handoff = _latest_or_none(storage.list_handoffs_for_task(task["id"]))
        project_id = task["metadata"].get("project_id")

        for gate in approvals:
            if gate["status"] != "pending":
                continue
            inbox.append(
                {
                    "id": f"approval-{gate['id']}",
                    "kind": "approval",
                    "workspace_id": task["workspace_id"],
                    "project_id": project_id,
                    "task_id": task["id"],
                    "title": task["title"],
                    "summary": f"Approval needed: {gate['name']}",
                    "state": "awaiting_approval",
                    "next_action": "Open task",
                    "updated_at": gate["updated_at"],
                }
            )

        if any(review["status"] == "rejected" for review in reviews):
            latest_rejected = next(review for review in reversed(reviews) if review["status"] == "rejected")
            inbox.append(
                {
                    "id": f"failed-review-{latest_rejected['id']}",
                    "kind": "failed_review",
                    "workspace_id": task["workspace_id"],
                    "project_id": project_id,
                    "task_id": task["id"],
                    "title": task["title"],
                    "summary": latest_rejected["summary"] or "Review failed.",
                    "state": "failed",
                    "next_action": "Re-open task review",
                    "updated_at": latest_rejected["updated_at"],
                }
            )

        if latest_checkpoint is not None:
            inbox.append(
                {
                    "id": f"checkpoint-{latest_checkpoint['id']}",
                    "kind": "checkpoint_ready",
                    "workspace_id": task["workspace_id"],
                    "project_id": project_id,
                    "task_id": task["id"],
                    "title": task["title"],
                    "summary": latest_checkpoint["summary"],
                    "state": "ready",
                    "next_action": "Resume from checkpoint",
                    "updated_at": latest_checkpoint["created_at"],
                }
            )

        if latest_handoff is not None:
            inbox.append(
                {
                    "id": f"handoff-{latest_handoff['id']}",
                    "kind": "handoff_ready",
                    "workspace_id": task["workspace_id"],
                    "project_id": project_id,
                    "task_id": task["id"],
                    "title": task["title"],
                    "summary": latest_handoff["summary"],
                    "state": "handoff_ready",
                    "next_action": "Review handoff",
                    "updated_at": latest_handoff["created_at"],
                }
            )

    return sorted(inbox, key=lambda item: item["updated_at"], reverse=True)


def _task_studio_header(
    task: dict[str, Any],
    *,
    graph: dict[str, Any],
    approvals: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    handoff: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None,
    workspace: dict[str, Any] | None,
) -> dict[str, Any]:
    handoff_state = _handoff_state(handoff)
    queue_state = _task_studio_queue_state(task, graph, approvals, reviews, handoff_state)
    repository_action_preference = _effective_repository_action_preference(task, workspace)
    return {
        "queue_state": queue_state,
        "approval_state": _approval_state(approvals),
        "next_safe_action": _task_studio_next_safe_action(queue_state, approvals, checkpoint),
        "repository_action_mode": repository_action_preference["mode"],
        "checkpoint_ready": checkpoint is not None,
        "handoff_state": handoff_state,
    }


def _task_studio_queue_state(
    task: dict[str, Any],
    graph: dict[str, Any],
    approvals: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    handoff_state: str,
) -> str:
    if handoff_state != "none":
        return "handoff_ready"
    if any(review["status"] == "rejected" for review in reviews):
        return "failed"
    if any(gate["status"] == "pending" for gate in approvals):
        return "awaiting_approval"
    coordination_state = graph.get("coordination_state")
    if coordination_state == "waiting_human":
        return "waiting_human"
    if coordination_state == "blocked":
        return "blocked"
    if coordination_state == "active":
        return "running"
    if coordination_state == "ready":
        return "ready"
    if task["status"] in {"done", "complete"}:
        return "done"
    return "planning"


def _task_studio_next_safe_action(
    queue_state: str,
    approvals: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
) -> str:
    if queue_state == "awaiting_approval":
        next_gate = _next_pending_gate(approvals)
        return f"Approve {next_gate['name']}" if next_gate else "Review pending approval"
    if queue_state == "handoff_ready":
        return "Review handoff"
    if queue_state in {"blocked", "waiting_human"}:
        return "Resolve blocker"
    if queue_state == "failed":
        return "Review failed checks"
    if checkpoint is not None:
        return "Resume from checkpoint"
    if queue_state == "running":
        return "Monitor execution"
    if queue_state == "ready":
        return "Dispatch ready work"
    return "Open task"

