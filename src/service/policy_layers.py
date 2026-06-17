"""Service-level glue for three-tier (server -> workspace -> session) policy layering."""

from __future__ import annotations

from typing import Any

from src.policy import compile_policy_pack
from src.policy.layering import (
    caps_would_loosen,
    extract_server_caps,
    normalize_policy_overrides,
    resolve_policy_layers,
)
from src.storage import Storage

from .errors import ServiceError
from .intake import _find_policy_pack_dir


def _compiled_server_caps(storage: Storage, workspace_id: str) -> dict[str, Any]:
    policy_dir = _find_policy_pack_dir(storage, workspace_id)
    if policy_dir is None:
        return extract_server_caps(None)
    try:
        compiled = compile_policy_pack(str(policy_dir))
    except Exception:
        return extract_server_caps(None)
    return extract_server_caps(compiled)


def get_workspace_policy(storage: Storage, workspace_id: str) -> dict[str, Any]:
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    server_caps = _compiled_server_caps(storage, workspace_id)
    workspace_overrides = (workspace.get("metadata") or {}).get("policy_overrides") or {}
    return resolve_policy_layers(server_caps, workspace_overrides, None)


def set_workspace_policy_overrides(
    storage: Storage, workspace_id: str, overrides: Any
) -> dict[str, Any]:
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)

    try:
        normalized_overrides = normalize_policy_overrides(overrides)
    except ValueError as exc:
        raise ServiceError("invalid_request", str(exc), 400)

    server_caps = _compiled_server_caps(storage, workspace_id)
    server_resolved = resolve_policy_layers(server_caps)
    server_effective = server_resolved["effective"]

    rejected = caps_would_loosen(server_effective, normalized_overrides)
    if rejected:
        raise ServiceError(
            "policy_violation",
            f"Workspace policy would loosen server caps: {sorted(rejected)}",
            400,
        )

    metadata = dict(workspace.get("metadata") or {})
    existing_overrides = dict(metadata.get("policy_overrides") or {})
    existing_overrides.update(normalized_overrides)
    metadata["policy_overrides"] = existing_overrides
    storage.update_workspace(workspace_id, metadata=metadata)

    return get_workspace_policy(storage, workspace_id)


def get_session_policy(storage: Storage, session_id: str) -> dict[str, Any]:
    session = storage.get_session(session_id)
    if session is None:
        raise ServiceError("not_found", "Session not found.", 404)

    task = storage.get_task(session["task_id"])
    if task is None:
        raise ServiceError("not_found", "Session not found.", 404)

    workspace = storage.get_workspace(task["workspace_id"])
    if workspace is None:
        raise ServiceError("not_found", "Session not found.", 404)

    server_caps = _compiled_server_caps(storage, workspace["id"])
    workspace_overrides = (workspace.get("metadata") or {}).get("policy_overrides") or {}
    session_overrides = (session.get("metadata") or {}).get("policy_overrides") or {}

    return resolve_policy_layers(server_caps, workspace_overrides, session_overrides)


def set_session_policy_overrides(
    storage: Storage, session_id: str, overrides: Any
) -> dict[str, Any]:
    session = storage.get_session(session_id)
    if session is None:
        raise ServiceError("not_found", "Session not found.", 404)

    task = storage.get_task(session["task_id"])
    if task is None:
        raise ServiceError("not_found", "Session not found.", 404)

    workspace = storage.get_workspace(task["workspace_id"])
    if workspace is None:
        raise ServiceError("not_found", "Session not found.", 404)

    try:
        normalized_overrides = normalize_policy_overrides(overrides)
    except ValueError as exc:
        raise ServiceError("invalid_request", str(exc), 400)

    workspace_policy = get_workspace_policy(storage, workspace["id"])
    workspace_effective = workspace_policy["effective"]

    rejected = caps_would_loosen(workspace_effective, normalized_overrides)
    if rejected:
        raise ServiceError(
            "policy_violation",
            f"Session policy would loosen workspace caps: {sorted(rejected)}",
            400,
        )

    metadata = dict(session.get("metadata") or {})
    existing_overrides = dict(metadata.get("policy_overrides") or {})
    existing_overrides.update(normalized_overrides)
    metadata["policy_overrides"] = existing_overrides
    storage.update_session(session_id, metadata=metadata)

    return get_session_policy(storage, session_id)
