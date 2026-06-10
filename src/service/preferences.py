"""Request body helpers and task/workspace preference normalization."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from .errors import ServiceError


def _required_text(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ServiceError("invalid_request", f"Field '{key}' is required.", 400)
    return value


def _optional_text(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError("invalid_request", f"Field '{key}' must be a string.", 400)
    return value


def _optional_dict(body: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ServiceError("invalid_request", f"Field '{key}' must be an object.", 400)
    return value


_REPOSITORY_ACTION_MODES = ["no_action", "prepare_patch", "commit", "draft_pr", "ready_pr"]


def _default_repository_action_preference() -> dict[str, Any]:
    return {
        "scope": "default",
        "mode": "no_action",
        "allowed_modes": list(_REPOSITORY_ACTION_MODES),
    }


def _default_provider_priority() -> list[str]:
    return ["claude", "codex", "copilot", "opencode"]


def _normalize_saved_view_filters(filters: Any) -> dict[str, Any] | None:
    if not isinstance(filters, Mapping):
        return None
    normalized: dict[str, Any] = {}
    project_state = filters.get("project_state")
    if isinstance(project_state, str) and project_state.strip() in {"all", "blocked"}:
        normalized["project_state"] = project_state.strip()
    task_state = filters.get("task_state")
    if isinstance(task_state, str) and task_state.strip() in {"handoff_ready", "checkpoint_ready", "approval_pending"}:
        normalized["task_state"] = task_state.strip()
    kind = filters.get("kind")
    if isinstance(kind, str) and kind.strip() == "approval":
        normalized["kind"] = "approval"
    provider_health = filters.get("provider_health")
    if isinstance(provider_health, str) and provider_health.strip() == "degraded_or_offline":
        normalized["provider_health"] = "degraded_or_offline"
    governance = filters.get("governance")
    if isinstance(governance, str) and governance.strip() == "overrides":
        normalized["governance"] = "overrides"
    return normalized


def _normalize_custom_saved_view(definition: Any) -> dict[str, Any] | None:
    if not isinstance(definition, Mapping):
        return None
    raw_name = definition.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None
    raw_id = definition.get("id")
    view_id = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else f"custom-view-{uuid4().hex[:8]}"
    role = definition.get("role")
    route = definition.get("route")
    description = definition.get("description")
    metric_label = definition.get("metric_label")
    filters = _normalize_saved_view_filters(definition.get("filters") or {})
    if filters is None:
        return None
    normalized_route = route.strip() if isinstance(route, str) and route.strip() in {"workspace", "inbox", "settings"} else "workspace"
    normalized: dict[str, Any] = {
        "id": view_id,
        "name": raw_name.strip(),
        "role": role.strip() if isinstance(role, str) and role.strip() else "custom",
        "route": normalized_route,
        "description": description.strip() if isinstance(description, str) and description.strip() else "Custom saved view for recurring Sarathi operations.",
        "metric_label": metric_label.strip() if isinstance(metric_label, str) and metric_label.strip() else "matching items",
        "filters": filters,
    }
    return normalized


def _normalize_brainstorm_metadata(metadata: Any) -> dict[str, Any] | None:
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        return None
    normalized: dict[str, Any] = {}
    reuse_source = metadata.get("reuse_source")
    if isinstance(reuse_source, Mapping):
        source_kind = reuse_source.get("kind")
        source_id = reuse_source.get("id")
        source_name = reuse_source.get("name")
        normalized_reuse_source = {
            "kind": source_kind.strip() if isinstance(source_kind, str) and source_kind.strip() else "workflow",
            "id": source_id.strip() if isinstance(source_id, str) and source_id.strip() else None,
            "name": source_name.strip() if isinstance(source_name, str) and source_name.strip() else None,
        }
        normalized["reuse_source"] = normalized_reuse_source
    workflow_template_id = metadata.get("workflow_template_id")
    if isinstance(workflow_template_id, str) and workflow_template_id.strip():
        normalized["workflow_template_id"] = workflow_template_id.strip()
    learning_playbook_id = metadata.get("learning_playbook_id")
    if isinstance(learning_playbook_id, str) and learning_playbook_id.strip():
        normalized["learning_playbook_id"] = learning_playbook_id.strip()
    recommended_view_ids = metadata.get("recommended_view_ids")
    if isinstance(recommended_view_ids, list):
        normalized_ids = [value.strip() for value in recommended_view_ids if isinstance(value, str) and value.strip()]
        if normalized_ids:
            normalized["recommended_view_ids"] = normalized_ids[:4]
    recommended_repository_action_mode = metadata.get("recommended_repository_action_mode")
    if isinstance(recommended_repository_action_mode, str) and recommended_repository_action_mode.strip():
        normalized["recommended_repository_action_mode"] = recommended_repository_action_mode.strip()
    recommended_auto_approve_mode = metadata.get("recommended_auto_approve_mode")
    if isinstance(recommended_auto_approve_mode, str) and recommended_auto_approve_mode.strip():
        normalized["recommended_auto_approve_mode"] = recommended_auto_approve_mode.strip()
    suggested_provider_priority = metadata.get("suggested_provider_priority")
    if isinstance(suggested_provider_priority, list):
        allowed = set(_default_provider_priority())
        normalized_priority = [
            value.strip()
            for value in suggested_provider_priority
            if isinstance(value, str) and value.strip() in allowed
        ]
        if normalized_priority:
            normalized["suggested_provider_priority"] = normalized_priority
    return normalized


def _normalize_reuse_preferences(preferences: Any) -> dict[str, Any] | None:
    if not isinstance(preferences, Mapping):
        return None
    active_saved_view_id = preferences.get("active_saved_view_id")
    if active_saved_view_id is not None and not isinstance(active_saved_view_id, str):
        return None
    normalized: dict[str, Any] = {}
    if isinstance(active_saved_view_id, str) and active_saved_view_id.strip():
        normalized["active_saved_view_id"] = active_saved_view_id.strip()
    custom_saved_views = preferences.get("custom_saved_views")
    if custom_saved_views is not None:
        if not isinstance(custom_saved_views, list):
            return None
        builtin_ids = {
            "all-projects",
            "approvals-inbox",
            "blocked-projects",
            "handoff-readiness",
            "checkpoint-queue",
            "provider-posture",
            "governance-overrides",
        }
        seen_ids: set[str] = set()
        normalized_saved_views: list[dict[str, Any]] = []
        for item in custom_saved_views[:8]:
            normalized_view = _normalize_custom_saved_view(item)
            if normalized_view is None:
                continue
            if normalized_view["id"] in builtin_ids or normalized_view["id"] in seen_ids:
                continue
            seen_ids.add(normalized_view["id"])
            normalized_saved_views.append(normalized_view)
        normalized["custom_saved_views"] = normalized_saved_views
    return normalized


def _normalize_provider_priority(priority: Any) -> list[str] | None:
    if not isinstance(priority, list):
        return None
    allowed = _default_provider_priority()
    seen: set[str] = set()
    normalized: list[str] = []
    for value in priority:
        if not isinstance(value, str):
            continue
        provider_id = value.strip()
        if not provider_id or provider_id not in allowed or provider_id in seen:
            continue
        seen.add(provider_id)
        normalized.append(provider_id)
    if not normalized:
        return None
    for provider_id in allowed:
        if provider_id not in seen:
            normalized.append(provider_id)
    return normalized


def _normalize_repository_action_preference(
    preference: Any,
    *,
    fallback_scope: str,
) -> dict[str, Any] | None:
    if not isinstance(preference, Mapping):
        return None
    mode = preference.get("mode")
    if mode not in _REPOSITORY_ACTION_MODES:
        return None
    scope = preference.get("scope")
    if scope not in {"task", "project", "workspace", "default"}:
        scope = fallback_scope
    normalized = {
        "scope": scope,
        "mode": mode,
        "allowed_modes": list(_REPOSITORY_ACTION_MODES),
    }
    if "source" in preference and isinstance(preference.get("source"), str):
        normalized["source"] = preference["source"]
    return normalized


def _effective_repository_action_preference(
    task: Mapping[str, Any],
    workspace: Mapping[str, Any] | None,
) -> dict[str, Any]:
    task_metadata = task.get("metadata") or {}
    task_preference = _normalize_repository_action_preference(
        task_metadata.get("repository_action_preference"),
        fallback_scope="task",
    )
    if task_preference is not None and task_preference["scope"] != "default":
        return task_preference

    project_preference = _normalize_repository_action_preference(
        task_metadata.get("project_repository_action_preference"),
        fallback_scope="project",
    )
    if project_preference is not None:
        return project_preference

    if workspace is not None:
        workspace_metadata = workspace.get("metadata") or {}
        workspace_preference = _normalize_repository_action_preference(
            workspace_metadata.get("repository_action_preference"),
            fallback_scope="workspace",
        )
        if workspace_preference is not None:
            return workspace_preference

    return task_preference or _default_repository_action_preference()


def _merge_task_defaults(metadata: dict[str, Any] | None) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    next_metadata.setdefault("repository_action_preference", _default_repository_action_preference())
    return next_metadata


_AUTO_APPROVE_MODES = ["manual_only", "below_threshold"]


def _default_auto_approve_preference() -> dict[str, Any]:
    return {
        "scope": "default",
        "mode": "manual_only",
        "allowed_modes": list(_AUTO_APPROVE_MODES),
    }


def _normalize_auto_approve_preference(
    preference: Any,
    *,
    fallback_scope: str,
) -> dict[str, Any] | None:
    if not isinstance(preference, Mapping):
        return None
    mode = preference.get("mode")
    if mode not in _AUTO_APPROVE_MODES:
        return None
    scope = preference.get("scope")
    if scope not in {"task", "project", "workspace", "default"}:
        scope = fallback_scope
    normalized = {
        "scope": scope,
        "mode": mode,
        "allowed_modes": list(_AUTO_APPROVE_MODES),
    }
    if "threshold" in preference and isinstance(preference.get("threshold"), Mapping):
        normalized["threshold"] = preference["threshold"]
    if "source" in preference and isinstance(preference.get("source"), str):
        normalized["source"] = preference["source"]
    return normalized


def _effective_auto_approve_preference(
    task: Mapping[str, Any],
    workspace: Mapping[str, Any] | None,
) -> dict[str, Any]:
    task_metadata = task.get("metadata") or {}
    task_preference = _normalize_auto_approve_preference(
        task_metadata.get("auto_approve_preference"),
        fallback_scope="task",
    )
    if task_preference is not None and task_preference["scope"] != "default":
        return task_preference

    project_preference = _normalize_auto_approve_preference(
        task_metadata.get("project_auto_approve_preference"),
        fallback_scope="project",
    )
    if project_preference is not None:
        return project_preference

    if workspace is not None:
        workspace_metadata = workspace.get("metadata") or {}
        workspace_preference = _normalize_auto_approve_preference(
            workspace_metadata.get("auto_approve_preference"),
            fallback_scope="workspace",
        )
        if workspace_preference is not None:
            return workspace_preference

    return task_preference or _default_auto_approve_preference()


def _get_policy_pack_approval_defaults() -> dict[str, Any]:
    return {
        "default_mode": "manual_only",
        "allowed_modes": list(_AUTO_APPROVE_MODES),
        "max_threshold": {
            "complexity": "low",
            "max_node_count": 3,
        },
        "never_auto_approve_gates": [
            "PRD/AC",
            "Repository action",
            "Final handoff",
            "Task graph",
        ],
    }


def _evaluate_threshold(
    preference: dict[str, Any],
    gate_metadata: dict[str, Any] | None,
) -> bool:
    if preference.get("mode") != "below_threshold":
        return False

    threshold = preference.get("threshold")
    if not threshold:
        return False

    complexity = threshold.get("complexity", "high")
    max_nodes = threshold.get("max_node_count", 0)

    gate_complexity = (gate_metadata or {}).get("complexity", "high")
    gate_node_count = (gate_metadata or {}).get("node_count", 999)

    if complexity == "low" and gate_complexity != "low":
        return False
    if complexity == "medium" and gate_complexity == "high":
        return False

    if max_nodes > 0 and gate_node_count > max_nodes:
        return False

    return True


def _is_gate_denylisted(gate_name: str, denylist: list[str]) -> bool:
    return gate_name in denylist
