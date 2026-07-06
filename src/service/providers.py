"""Provider dispatch, configuration, and health-check helpers."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.dispatch import LocalDispatcher
from src.harness import derive_permission_mode
from src.permissions import PermissionMode
from src.runtime import (
    ContextCompiler,
    DispatchRequest,
    build_artifact_index,
    normalize_agent_output,
)
from src.storage import Storage
from src.task_class import TASK_CLASS_DEFAULTS, TaskClass, classify_task_class, from_legacy_type
from src.tui_data import ChatSession, is_error_reply

from .errors import ServiceError
from .intake import _task_context_project_id, _task_context_workspace_id, _task_draft_metadata
from .preferences import (
    _default_provider_priority,
    _normalize_provider_priority,
    _optional_text,
    _required_text,
)
from .scheduling import _service_now


# Default worker claim lease window, in seconds. A claim older than this is
# considered stale and may be requeued or re-dispatched by another worker.
DEFAULT_CLAIM_LEASE_SECONDS = 600


def _claim_is_fresh(
    subtask: Mapping[str, Any], *, lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS
) -> bool:
    """Return True if ``subtask`` has an active, non-expired worker claim."""
    if not subtask.get("claimed_by"):
        return False
    heartbeat_at = subtask.get("heartbeat_at") or subtask.get("claimed_at")
    if not heartbeat_at:
        return True
    try:
        heartbeat = datetime.fromisoformat(str(heartbeat_at))
    except ValueError:
        return True
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - heartbeat
    return age <= timedelta(seconds=lease_seconds)


def _dispatch_subtask(
    storage: Storage,
    subtask: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if subtask["status"] != "in_progress":
        raise ServiceError(
            "invalid_state",
            "Only in-progress subtasks can be dispatched to a provider.",
            409,
        )
    provider = _optional_text(body, "provider") or "local"
    provider_config = _provider_dispatch_adapter_config(
        storage,
        workspace_id=subtask["workspace_id"],
        provider_id=provider,
    )
    task = storage.get_task(subtask["task_id"])
    if task is None:
        raise ServiceError("not_found", "Task not found.", 404)
    context_pack = ContextCompiler().compile_task_tracking_context(
        task=task,
        subtask=subtask,
        evidence_artifacts=storage.list_evidence_artifacts_for_task(task["id"]),
        review_runs=storage.list_review_runs_for_task(task["id"]),
        available_tools=["workspace_files", "git_diff", "test_results", "provider_dispatch"],
    )
    context_pack_artifact = context_pack.to_artifact()
    workspace = storage.get_workspace(subtask["workspace_id"])
    workspace_root = Path(workspace["root_path"]).expanduser() if workspace is not None else None
    use_ncp_handoff = bool(
        provider in {"claude", "opencode"}
        and workspace_root is not None
        and (workspace_root / ".ncp" / "config.toml").exists()
    )

    ncp_run_path = workspace_root / ".ncp" / "run.py" if workspace_root is not None else None
    ncp_config_present = bool(
        workspace_root is not None
        and (workspace_root / ".ncp" / "config.toml").exists()
        and ncp_run_path is not None
        and ncp_run_path.exists()
    )

    ncp_adapter = None
    ncp_available = False
    ncp_prior_findings_fetched = 0
    if ncp_config_present:
        from src.ncp_adapter.persistence_adapter import NCPPersistenceAdapter

        ncp_adapter = NCPPersistenceAdapter(run_path=ncp_run_path)
        try:
            fetch_chunks = ncp_adapter._call_fetch(
                f"{task['title']} {subtask['title']}", k=3
            )
            ncp_available = True
            for chunk in fetch_chunks:
                text = ncp_adapter._reconstruct_chunk_text(chunk).strip()
                if not text:
                    continue
                ncp_prior_findings_fetched += 1
                agent_input = context_pack_artifact.setdefault("agent_input", {})
                prior_findings = list(agent_input.get("prior_findings", []))
                prior_findings = [text[:200]] + prior_findings
                agent_input["prior_findings"] = prior_findings[:8]
            context_pack_artifact.setdefault("compilation", {})["ncp_prior_findings"] = (
                ncp_prior_findings_fetched
            )
        except Exception:
            ncp_available = False
            ncp_prior_findings_fetched = 0
            context_pack_artifact.setdefault("compilation", {})["ncp_prior_findings"] = 0

    storage.create_lifecycle_event(
        workspace_id=subtask["workspace_id"],
        task_id=subtask["task_id"],
        event_type="context.compiled",
        payload={
            "object_id": subtask["id"],
            "provider": provider,
            "phase": context_pack.phase,
            "role": context_pack.role,
            "token_budget": context_pack.agent_input.token_budget,
            "estimated_tokens": context_pack_artifact["compilation"]["estimated_tokens"],
        },
    )

    response = LocalDispatcher(provider_config=provider_config).dispatch(
        DispatchRequest(
            mode="execute",
            task_id=subtask["id"],
            phase="TaskTracking",
            prompt=subtask["title"],
            inputs={
                "node": _graph_node_from_subtask(subtask),
                "context_pack": context_pack_artifact,
            },
            expected_outputs=["work_unit_result"],
            constraints={
                "purpose": "child_task_execution",
                "provider": provider,
                "permission_mode": _permission_mode_for_service_dispatch(task, subtask),
                **(
                    {
                        "ncp_handoff_enabled": True,
                        "ncp_pipeline_id": f"sarathi_{subtask['id']}",
                        "ncp_emit_to": "opencode" if provider == "claude" else "claude",
                    }
                    if use_ncp_handoff
                    else {}
                ),
            },
            context_pack=context_pack_artifact,
            token_budget=context_pack.agent_input.token_budget,
        )
    )
    artifact_index = build_artifact_index(response)
    agent_output = normalize_agent_output(
        response,
        phase="TaskTracking",
        purpose="child_task_execution",
    ).to_artifact()
    status = "completed" if response.success else "failed"

    phase_log_written = False
    cost_logged = False
    if ncp_config_present and ncp_available and ncp_adapter is not None:
        try:
            ncp_adapter.save_phase_log(
                task={"task_id": task["id"]}, phase="TaskTracking", status=status,
            )
            phase_log_written = True
        except Exception:
            pass
        if response.usage:
            try:
                ncp_adapter.log_cost(
                    usage_record=response.usage.to_artifact(),
                    pipeline_id=f"sarathi_{subtask['id']}",
                )
                cost_logged = True
            except Exception:
                pass

    dispatch = storage.create_dispatch(
        workspace_id=subtask["workspace_id"],
        task_id=subtask["task_id"],
        agent_name=provider,
        status=status,
        metadata={
            "subtask_id": subtask["id"],
            "outputs": response.outputs,
            "evidence": response.evidence,
            "artifacts": response.artifacts,
            "context_pack": context_pack_artifact,
            "agent_output": agent_output,
            "artifact_index": artifact_index,
            **({"usage": response.usage.to_artifact()} if response.usage else {}),
            **({"error": response.error} if response.error else {}),
            **(
                {
                    "ncp": {
                        "config_present": True,
                        "available": ncp_available,
                        "prior_findings_fetched": ncp_prior_findings_fetched,
                        "phase_log_written": phase_log_written,
                        "cost_logged": cost_logged,
                    }
                }
                if ncp_config_present
                else {}
            ),
        },
    )
    next_status = "review" if response.success else "failed"
    updated_subtask = storage.update_subtask(subtask["id"], status=next_status)
    storage.create_lifecycle_event(
        workspace_id=subtask["workspace_id"],
        task_id=subtask["task_id"],
        event_type="subtask.dispatched",
        payload={
            "object_id": subtask["id"],
            "dispatch_id": dispatch["id"],
            "provider": provider,
            "status": status,
        },
    )

    if ncp_config_present:
        storage.create_lifecycle_event(
            workspace_id=subtask["workspace_id"],
            task_id=subtask["task_id"],
            event_type="ncp.memory_written",
            payload={
                "object_id": subtask["id"],
                "dispatch_id": dispatch["id"],
                "phase_log_written": phase_log_written,
                "cost_logged": cost_logged,
                "prior_findings_fetched": ncp_prior_findings_fetched,
            },
        )

    evidence = None
    if response.success:
        evidence = storage.create_evidence_artifact(
            workspace_id=subtask["workspace_id"],
            task_id=subtask["task_id"],
            artifact_type="dispatch_result",
            uri=f"sarathi://dispatches/{dispatch['id']}",
            metadata={
                "subtask_id": subtask["id"],
                "dispatch_id": dispatch["id"],
                "provider": provider,
                "response_evidence": response.evidence,
                "agent_output": agent_output,
                "artifact_index": artifact_index,
            },
        )
        storage.create_lifecycle_event(
            workspace_id=subtask["workspace_id"],
            task_id=subtask["task_id"],
            event_type="evidence.created",
            payload={
                "object_id": evidence["id"],
                "dispatch_id": dispatch["id"],
                "subtask_id": subtask["id"],
            },
        )

    return {
        "subtask": updated_subtask,
        "dispatch": dispatch,
        "evidence": evidence,
    }


def _invoke_task_chat_provider(
    storage: Storage,
    task: Mapping[str, Any],
    user_message: Mapping[str, Any],
    *,
    target: str = "Current task agents",
) -> dict[str, Any]:
    """Invoke the same free-form provider chat path used by the TUI.

    This is intentionally separate from TaskTracking dispatch: chat messages
    should get conversational provider replies, while graph nodes still use the
    governed subtask dispatch contract.
    """
    workspace = storage.get_workspace(str(task["workspace_id"]))
    workspace_root = workspace["root_path"] if workspace is not None else None
    session = ChatSession(workspace_root=workspace_root)
    preferred_provider = _prefer_chat_session_provider(storage, str(task["workspace_id"]), session)
    reply_text = session.send(str(user_message["content"]))
    provider = (session.provider[0] if session.provider else preferred_provider) or "unavailable"
    error = is_error_reply(reply_text) or provider == "unavailable"
    reply = storage.create_message(
        workspace_id=str(task["workspace_id"]),
        task_id=str(task["id"]),
        role=provider if provider != "unavailable" else "sarathi",
        content=reply_text,
        metadata={
            "source": "provider_chat",
            "provider": provider,
            "target": target,
            "reply_to": user_message["id"],
            **({"error": True} if error else {}),
        },
    )
    storage.create_lifecycle_event(
        workspace_id=str(task["workspace_id"]),
        task_id=str(task["id"]),
        event_type="message.provider_replied",
        payload={
            "object_id": reply["id"],
            "reply_to": user_message["id"],
            "provider": provider,
            "status": "error" if error else "completed",
        },
    )
    return {
        "message": reply,
        "agent": provider,
        "status": "error" if error else "completed",
    }


def _prefer_chat_session_provider(
    storage: Storage,
    workspace_id: str,
    session: ChatSession,
) -> str | None:
    priority = [provider for provider in _get_provider_priority(storage, workspace_id) if provider in ChatSession.PROVIDERS]
    for provider in priority:
        if session.set_provider(provider):
            return provider
    resolved = session.resolve_provider()
    return resolved[0] if resolved else None


_READ_ONLY_ROLES = {"disha", "vichara", "prajna", "nirnaya", "marga", "sahayaka"}
_EXECUTOR_ROLES = {"pravaha", "samanvaya"}


def _permission_mode_for_service_dispatch(
    task: Mapping[str, Any],
    subtask: Mapping[str, Any],
) -> str:
    """Derive provider permissions for service-triggered child-agent dispatch."""
    subtask_metadata = _mapping(subtask.get("metadata"))
    task_metadata = _mapping(task.get("metadata"))

    explicit = _explicit_permission_mode(subtask_metadata)
    if explicit is not None:
        return explicit.value

    role = str(subtask_metadata.get("role") or "").strip().lower()
    if role in _READ_ONLY_ROLES:
        return PermissionMode.READ_ONLY.value
    if role in _EXECUTOR_ROLES:
        return _task_permission_mode(task, task_metadata, default=PermissionMode.READ_WRITE).value

    explicit = _explicit_permission_mode(task_metadata)
    if explicit is not None:
        return explicit.value
    return _task_permission_mode(task, task_metadata, default=PermissionMode.READ_ONLY).value


def _task_permission_mode(
    task: Mapping[str, Any],
    task_metadata: Mapping[str, Any],
    *,
    default: PermissionMode,
) -> PermissionMode:
    harness_config = _mapping(task_metadata.get("harness_config"))
    mode = _explicit_permission_mode(harness_config)
    if mode is not None:
        return mode

    task_class = _task_class_from_metadata(task_metadata)
    if task_class is None:
        task_class = classify_task_class(
            " ".join(
                str(part)
                for part in [
                    task_metadata.get("source_prompt"),
                    task.get("description"),
                    task.get("title"),
                ]
                if part
            )
        )
    defaults = TASK_CLASS_DEFAULTS.get(task_class)
    if defaults is None:
        return default
    return derive_permission_mode(defaults.permission_scope)


def _explicit_permission_mode(metadata: Mapping[str, Any]) -> PermissionMode | None:
    raw_mode = metadata.get("permission_mode")
    if isinstance(raw_mode, str):
        normalized = raw_mode.strip().lower()
        for mode in PermissionMode:
            if normalized == mode.value:
                return mode
    raw_scope = metadata.get("permission_scope")
    if isinstance(raw_scope, str) and raw_scope.strip():
        return derive_permission_mode(raw_scope)
    return None


def _task_class_from_metadata(metadata: Mapping[str, Any]) -> TaskClass | None:
    raw_task_class = metadata.get("task_class")
    if not isinstance(raw_task_class, str) or not raw_task_class.strip():
        return None
    value = raw_task_class.strip()
    try:
        return TaskClass(value)
    except ValueError:
        return from_legacy_type(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _provider_dispatch_adapter_config(
    storage: Storage,
    *,
    workspace_id: str,
    provider_id: str,
) -> Mapping[str, Any] | None:
    if provider_id == "local":
        return None
    specs = _provider_specs()
    spec = specs.get(provider_id)
    if spec is None:
        raise ServiceError("not_found", "Provider not found.", 404)
    provider_record = storage.get_provider(workspace_id, provider_id)
    config = (
        dict(provider_record["config"])
        if provider_record is not None
        else _provider_check_config(
            spec,
            path=str(spec["path"]),
            auth=str(spec["auth"]),
        )
    )
    if config.get("health") != "online":
        detail = config.get("last_error") or f"Provider '{provider_id}' is offline."
        raise ServiceError("provider_unavailable", detail, 409)
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    path_value = str(config.get("path", spec["path"]) or "")
    resolved_path = _resolve_provider_path(path_value) if path_value else None
    command = (
        _provider_dispatch_command(
            provider_id=provider_id,
            path=resolved_path,
            workspace_root=str(workspace["root_path"]),
        )
        if resolved_path is not None
        else None
    )
    provider_payload: dict[str, Any] = {
        "type": "command",
        "command": command or [],
        "timeout_seconds": 300,
    }
    if provider_id == "claude" and (config.get("api_key_configured") or _native_bridge_provider(provider_id, resolved_path or "") == "claude"):
        provider_payload = {
            "type": "anthropic_sdk",
            "workspace_root": str(workspace["root_path"]),
            "provider_path": resolved_path,
            **({"api_key": config.get("api_key")} if isinstance(config.get("api_key"), str) and config.get("api_key") else {}),
            **({"base_url": config.get("base_url")} if isinstance(config.get("base_url"), str) and config.get("base_url") else {}),
            **({"model": config.get("model")} if isinstance(config.get("model"), str) and config.get("model") else {}),
            "timeout_seconds": 300,
            "fallback_to_cli": resolved_path is not None,
        }
    elif provider_id == "codex" and (config.get("api_key_configured") or _native_bridge_provider(provider_id, resolved_path or "") == "codex"):
        provider_payload = {
            "type": "openai_sdk",
            "workspace_root": str(workspace["root_path"]),
            "provider_path": resolved_path,
            **({"api_key": config.get("api_key")} if isinstance(config.get("api_key"), str) and config.get("api_key") else {}),
            **({"base_url": config.get("base_url")} if isinstance(config.get("base_url"), str) and config.get("base_url") else {}),
            **({"model": config.get("model")} if isinstance(config.get("model"), str) and config.get("model") else {}),
            "timeout_seconds": 300,
            "fallback_to_cli": resolved_path is not None,
        }
    elif provider_id == "opencode":
        if resolved_path is None:
            raise ServiceError(
                "provider_unavailable",
                f"CLI path not found: {config.get('path', spec['path'])}",
                409,
            )
        provider_payload = {
            "type": "opencode_sdk",
            "workspace_root": str(workspace["root_path"]),
            "provider_path": resolved_path,
            "timeout_seconds": 300,
            "fallback_to_cli": True,
        }
    elif resolved_path is None:
        raise ServiceError(
            "provider_unavailable",
            f"CLI path not found: {config.get('path', spec['path'])}",
            409,
        )
    return {
        "provider": provider_id,
        "providers": {
            provider_id: provider_payload
        },
    }


def _provider_dispatch_command(
    *,
    provider_id: str,
    path: str,
    workspace_root: str,
) -> list[str]:
    native_bridge_provider = _native_bridge_provider(provider_id, path)
    if native_bridge_provider is not None:
        return [
            sys.executable,
            "-m",
            "src.runtime.providers.cli_bridge",
            "--provider",
            native_bridge_provider,
            "--path",
            path,
            "--workspace-root",
            workspace_root,
        ]
    return [path]


def _native_bridge_provider(provider_id: str, path: str) -> str | None:
    executable = Path(path).name.lower()
    if provider_id == "codex" and executable == "codex":
        return "codex"
    if provider_id == "copilot" and executable in {"gh", "github-copilot", "copilot"}:
        return "copilot"
    if provider_id == "claude" and executable == "claude":
        return "claude"
    if provider_id == "opencode" and executable in {"opencode", "opencode-cli"}:
        return "opencode"
    return None


def _resolve_provider_path(path: str) -> str | None:
    if Path(path).is_absolute():
        return path if Path(path).exists() else None
    resolved = shutil.which(path)
    return resolved if resolved else None


def _graph_node_from_subtask(subtask: dict[str, Any]) -> dict[str, Any]:
    metadata = subtask["metadata"]
    return {
        "id": subtask["id"],
        "title": subtask["title"],
        "status": subtask["status"],
        "role": metadata.get("role"),
        "provider": metadata.get("provider"),
        "blocked_by": metadata.get("blocked_by", []),
        "evidence_required": metadata.get("evidence_required", []),
        "task_packet": metadata.get("task_packet", {}),
    }


def _provider_specs() -> dict[str, dict[str, Any]]:
    specs = [
        {
            "id": "local",
            "name": "Local deterministic",
            "provider_type": "deterministic",
            "transport_kind": "deterministic",
            "transport_posture": "builtin",
            "health": "online",
            "auth": "not_required",
            "path": "sarathi-local",
            "capabilities": ["child_task_execution", "planning", "review_fixture"],
            "degraded_reason": None,
        },
        {
            "id": "codex",
            "name": "Codex",
            "provider_type": "cli",
            "transport_kind": "sdk",
            "transport_posture": "sdk",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "codex",
            "capabilities": ["coding", "planning", "review"],
            "degraded_reason": "OpenAI SDK is the primary path with automatic Codex CLI fallback when credentials are unavailable.",
        },
        {
            "id": "claude",
            "name": "Claude",
            "provider_type": "cli",
            "transport_kind": "sdk",
            "transport_posture": "sdk",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "claude",
            "capabilities": ["research", "critique", "review"],
            "degraded_reason": "Anthropic SDK is the primary path with automatic Claude CLI fallback when credentials are unavailable.",
        },
        {
            "id": "copilot",
            "name": "Copilot",
            "provider_type": "agent",
            "transport_kind": "cli",
            "transport_posture": "cli_fallback",
            "health": "configured_by_user",
            "auth": "github_auth",
            "path": "GitHub Copilot",
            "capabilities": ["coding", "pull_request_assist"],
            "degraded_reason": "GitHub-native integration is planned, but current transport remains CLI-oriented.",
        },
        {
            "id": "opencode",
            "name": "OpenCode",
            "provider_type": "cli",
            "transport_kind": "sdk",
            "transport_posture": "sdk",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "opencode",
            "capabilities": ["coding", "planning", "review"],
            "degraded_reason": None,
        },
    ]
    return {spec["id"]: spec for spec in specs}


def _provider_health(storage: Storage, workspace_id: str | None = None) -> list[dict[str, Any]]:
    specs = _provider_specs()
    overrides = {
        provider["id"]: provider["config"]
        for provider in (storage.list_providers_for_workspace(workspace_id) if workspace_id else [])
    }
    return [_provider_view(provider_id, specs[provider_id], overrides.get(provider_id)) for provider_id in specs]


def _handle_chat(storage: Storage, body: Mapping[str, Any]) -> dict[str, Any]:
    message = _required_text(body, "message")
    context = body.get("context") or {}
    workspace_id = _task_context_workspace_id(context)
    if not workspace_id:
        workspace_id = _optional_text(body, "workspace_id")
    if not workspace_id:
        # Use first available workspace
        workspaces = storage.list_workspaces()
        if not workspaces:
            raise ServiceError("not_found", "No workspace found.", 404)
        workspace_id = workspaces[0]["id"]
    if storage.get_workspace(workspace_id) is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    priority = _get_provider_priority(storage, workspace_id)
    provider = _select_available_provider(storage, workspace_id, priority)
    if provider is None:
        provider = priority[0] if priority else "local"
    metadata = _task_draft_metadata(
        message,
        project_id=_task_context_project_id(context),
    )
    task = storage.create_task(
        workspace_id=workspace_id,
        title=message[:100],
        status="prd_pending",
        description=message,
        metadata=metadata,
        project_id=metadata.get("project_id"),
    )
    user_message = storage.create_message(
        workspace_id=workspace_id,
        task_id=task["id"],
        role="user",
        content=message,
        metadata={"target": "Current task agents", "source": "service_chat"},
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="task.chat_created",
        payload={"object_id": task["id"], "agent": provider},
    )
    provider_reply = _invoke_task_chat_provider(storage, task, user_message)
    return {
        "taskId": task["id"],
        "agent": provider_reply["agent"],
        "status": provider_reply["status"],
        "message": user_message,
        "reply": provider_reply["message"],
    }


def _get_provider_priority(storage: Storage, workspace_id: str) -> list[str]:
    workspace = storage.get_workspace(workspace_id)
    if workspace:
        metadata = workspace.get("metadata") or {}
        priority = _normalize_provider_priority(metadata.get("provider_priority"))
        if priority:
            return priority
    return _default_provider_priority()


def _select_available_provider(
    storage: Storage, workspace_id: str, priority: list[str]
) -> str | None:
    providers = storage.list_providers_for_workspace(workspace_id)
    provider_map = {p["id"]: p for p in providers}
    for pid in priority:
        p = provider_map.get(pid)
        if p:
            cfg = p.get("config") or {}
            health = cfg.get("health", "offline")
            last_error = cfg.get("last_error") or ""
            if health in ("online", "configured_by_user") and "rate_limit" not in last_error.lower():
                return pid
    return None


def _test_and_store_provider(
    storage: Storage,
    workspace_id: str,
    provider_id: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    specs = _provider_specs()
    if provider_id not in specs:
        raise ServiceError("not_found", "Provider not found.", 404)
    spec = specs[provider_id]
    existing = storage.get_provider(workspace_id, provider_id)
    existing_config = dict(existing["config"]) if existing is not None else {}
    path = spec["path"]
    if "path" in body and isinstance(body.get("path"), str):
        path = str(body.get("path") or "").strip()
    elif isinstance(existing_config.get("path"), str):
        path = str(existing_config.get("path") or "")
    auth = _optional_text(body, "auth") or spec["auth"]
    api_key = existing_config.get("api_key") if isinstance(existing_config.get("api_key"), str) else None
    if "api_key" in body:
        value = body.get("api_key")
        api_key = str(value).strip() if isinstance(value, str) and str(value).strip() else None
    base_url = existing_config.get("base_url") if isinstance(existing_config.get("base_url"), str) else None
    if "base_url" in body:
        value = body.get("base_url")
        base_url = str(value).strip() if isinstance(value, str) and str(value).strip() else None
    model = existing_config.get("model") if isinstance(existing_config.get("model"), str) else None
    if "model" in body:
        value = body.get("model")
        model = str(value).strip() if isinstance(value, str) and str(value).strip() else None
    config = _provider_check_config(spec, path=path, auth=auth, api_key=api_key, base_url=base_url, model=model)
    storage.upsert_provider(
        workspace_id=workspace_id,
        provider_id=provider_id,
        name=spec["name"],
        provider_type=spec["provider_type"],
        config=config,
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        event_type="provider.health_checked",
        payload={"object_id": provider_id, "health": config["health"], "auth": config["auth"]},
    )
    return _provider_view(provider_id, spec, config)


def _check_provider_auth(provider_id: str, resolved_path: str) -> tuple[str, str | None]:
    """Check provider authentication status via CLI probes.

    Returns: (auth_status, degraded_reason)
    where auth_status is "ok", "needs_auth", or "unknown"
    and degraded_reason is a human-readable message or None.

    Probe errors (timeout, OSError, missing subcommand) yield "unknown" with
    no degraded_reason, allowing the provider to remain online.
    """
    if provider_id == "claude":
        # Claude has no reliable non-interactive auth check
        return "unknown", None

    if provider_id == "codex":
        try:
            import subprocess as _sp
            result = _sp.run(
                [resolved_path, "login", "status"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            if result.returncode == 0:
                return "ok", None
            output = (result.stdout or "") + (result.stderr or "")
            if "not logged in" in output.lower():
                return "needs_auth", "CLI installed but not logged in (run: codex login)"
            # Non-zero exit without clear "not logged in" message: treat as unknown
            # (could be missing subcommand on older versions)
            return "unknown", None
        except Exception:
            return "unknown", None

    if provider_id == "opencode":
        try:
            import subprocess as _sp
            result = _sp.run(
                [resolved_path, "auth", "list"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            if result.returncode == 0 and (result.stdout or "").strip():
                return "ok", None
            if result.returncode != 0:
                # Non-zero exit from auth list command suggests not logged in
                return "needs_auth", "CLI installed but not logged in (run: opencode auth login)"
            # Zero exit but empty output means not logged in
            return "needs_auth", "CLI installed but not logged in (run: opencode auth login)"
        except Exception:
            return "unknown", None

    return "unknown", None


def _provider_check_config(
    spec: Mapping[str, Any],
    *,
    path: str,
    auth: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    if spec["id"] == "local":
        return {
            "path": path,
            "auth": "not_required",
            "health": "online",
            "last_checked_at": _service_now(),
            "last_error": None,
        }
    sdk_key_available = False
    if spec["id"] == "codex":
        sdk_key_available = bool(api_key or os.getenv("OPENAI_API_KEY"))
    elif spec["id"] == "claude":
        sdk_key_available = bool(api_key or os.getenv("ANTHROPIC_API_KEY"))
    resolved_path = shutil.which(path) if not Path(path).is_absolute() else (path if Path(path).exists() else None)
    if spec["id"] in {"codex", "claude"} and sdk_key_available:
        if auth == "missing":
            return {
                "path": path,
                "auth": auth,
                "health": "offline",
                "last_checked_at": _service_now(),
                "last_error": "Auth is missing.",
                **({"api_key": api_key} if api_key else {}),
                "api_key_configured": True,
                "base_url": base_url,
                "model": model,
            }
        return {
            "path": path,
            "auth": auth,
            "health": "online",
            "last_checked_at": _service_now(),
            "last_error": None,
            **({"api_key": api_key} if api_key else {}),
            "api_key_configured": True,
            "base_url": base_url,
            "model": model,
        }
    if not resolved_path:
        return {
            "path": path,
            "auth": auth,
            "health": "offline",
            "last_checked_at": _service_now(),
            "last_error": f"CLI path not found: {path}",
            **({"api_key": api_key} if api_key else {}),
            "api_key_configured": sdk_key_available,
            "base_url": base_url,
            "model": model,
        }
    if auth == "missing":
        return {
            "path": path,
            "auth": auth,
            "health": "offline",
            "last_checked_at": _service_now(),
            "last_error": "Auth is missing.",
            **({"api_key": api_key} if api_key else {}),
            "api_key_configured": sdk_key_available,
            "base_url": base_url,
            "model": model,
        }
    try:
        import subprocess as _sp
        result = _sp.run([resolved_path, "--version"], capture_output=True, timeout=5)
        stderr_out = (result.stderr or b"").decode("utf-8", errors="ignore").lower()
        stdout_out = (result.stdout or b"").decode("utf-8", errors="ignore").lower()
        combined = stderr_out + stdout_out
        if "rate limit" in combined or "too many requests" in combined or "429" in combined:
            return {
                "path": path,
                "auth": auth,
                "health": "rate_limited",
                "last_checked_at": _service_now(),
                "last_error": "Provider rate limited",
                **({"api_key": api_key} if api_key else {}),
                "api_key_configured": sdk_key_available,
                "base_url": base_url,
                "model": model,
            }
    except Exception:
        pass

    auth_status, degraded_reason = _check_provider_auth(spec["id"], resolved_path)
    if auth_status == "needs_auth":
        return {
            "path": path,
            "auth": "needs_auth",
            "health": "online",
            "last_checked_at": _service_now(),
            "last_error": degraded_reason,
            "degraded_reason": degraded_reason,
            **({"api_key": api_key} if api_key else {}),
            "api_key_configured": sdk_key_available,
            "base_url": base_url,
            "model": model,
        }

    return {
        "path": path,
        "auth": auth,
        "health": "online",
        "last_checked_at": _service_now(),
        "last_error": None,
        **({"api_key": api_key} if api_key else {}),
        "api_key_configured": sdk_key_available,
        "base_url": base_url,
        "model": model,
    }


def _provider_view(
    provider_id: str,
    spec: Mapping[str, Any],
    override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    override = override or {}
    return {
        "id": provider_id,
        "name": spec["name"],
        "provider_type": spec["provider_type"],
        "transport_kind": str(spec.get("transport_kind", "external")),
        "transport_posture": str(spec.get("transport_posture", "unknown")),
        "health": str(override.get("health", spec["health"])),
        "auth": str(override.get("auth", spec["auth"])),
        "path": str(override.get("path", spec["path"])),
        "capabilities": spec["capabilities"],
        "api_key_configured": bool(override.get("api_key_configured", False)),
        "base_url": override.get("base_url"),
        "model": override.get("model"),
        "degraded_reason": override.get("degraded_reason", spec.get("degraded_reason")),
        "last_checked_at": override.get("last_checked_at"),
        "last_error": override.get("last_error"),
    }
