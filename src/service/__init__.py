"""Minimal stdlib service boundary for Sarathi UI clients."""

from __future__ import annotations

import json
import shutil
import subprocess
import socketserver
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from urllib.parse import parse_qs, urlparse

from src.dispatch import LocalDispatcher
from src.init import InitWorkflow
from src.policy import compile_policy_pack
from src.runtime import DispatchRequest, GraphExecutionPolicy, UsageRecord, list_agent_roles
from src.storage import Storage, connect, run_migrations

MAX_BODY_BYTES = 64 * 1024
_ALLOWED_BROWSER_HOSTS = {"127.0.0.1", "localhost"}


@dataclass(frozen=True)
class ServiceError(Exception):
    code: str
    message: str
    status: int


class ServiceApp:
    """Callable local request handler that does not require a socket server."""

    def __init__(self, db_path: str | Path, token: str | None = None):
        self.db_path = Path(db_path)
        self.token = token
        self._local = threading.local()
        # Run migrations once at startup on the main thread
        with connect(self.db_path) as _conn:
            run_migrations(_conn)

    def _storage(self) -> tuple[Any, Storage]:
        """Return a per-thread (conn, storage), creating if needed."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.db_path).__enter__()  # keep connection open
            self._local.conn = conn
        return conn, Storage(conn)

    def __call__(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self.handle(method, path, body=body, headers=headers)

    def handle(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        skip_auth: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        correlation_id = _correlation_id(headers)
        try:
            if not skip_auth:
                self._authorize(headers)
            status, data = self._route(
                method.upper(),
                _path_parts(path),
                _query(path),
                body or {},
            )
            return status, _ok(data, correlation_id)
        except ServiceError as error:
            return error.status, _error(error, correlation_id)

    def _route(
        self,
        method: str,
        parts: list[str],
        query: Mapping[str, list[str]],
        body: Mapping[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        if parts and parts[0] == "api":
            parts = parts[1:]

        if method == "GET" and parts == ["health"]:
            return 200, {"status": "ok"}

        conn, storage = self._storage()

        if method == "GET" and parts == ["workspaces"]:
            workspaces = storage.list_workspaces()
            for ws in workspaces:
                stats = storage.get_workspace_stats(ws["id"])
                ws["task_count"] = stats["task_count"]
                ws["active_count"] = stats["active_count"]
                ws["last_activity"] = stats["last_activity"]
            return 200, {"workspaces": workspaces}

        if method == "POST" and parts == ["workspaces"]:
            workspace = storage.create_workspace(
                name=_required_text(body, "name"),
                root_path=_required_text(body, "root_path"),
                metadata=_optional_dict(body, "metadata"),
            )
            storage.create_lifecycle_event(
                workspace_id=workspace["id"],
                event_type="workspace.created",
                payload={"object_id": workspace["id"]},
            )
            return 201, {"workspace": workspace}

        if method == "GET" and len(parts) == 2 and parts[0] == "workspaces":
            workspace = storage.get_workspace(parts[1])
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {"workspace": workspace}

        if method == "PATCH" and len(parts) == 2 and parts[0] == "workspaces":
            workspace = storage.get_workspace(parts[1])
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            raw_metadata = _optional_dict(body, "metadata")
            if raw_metadata is None:
                raise ServiceError(
                    "invalid_request",
                    "Field 'metadata' is required.",
                    400,
                )

            next_metadata = dict(workspace.get("metadata") or {})

            if "repository_action_preference" in raw_metadata:
                preference = _normalize_repository_action_preference(
                    raw_metadata["repository_action_preference"],
                    fallback_scope="workspace",
                )
                if preference is None:
                    raise ServiceError(
                        "invalid_request",
                        "Unsupported repository action preference.",
                        400,
                    )
                next_metadata["repository_action_preference"] = preference

            if "auto_approve_preference" in raw_metadata:
                preference = _normalize_auto_approve_preference(
                    raw_metadata["auto_approve_preference"],
                    fallback_scope="workspace",
                )
                if preference is None:
                    raise ServiceError(
                        "invalid_request",
                        "Unsupported auto-approve preference. Allowed modes: manual_only, below_threshold.",
                        400,
                    )
                next_metadata["auto_approve_preference"] = preference

            if "repository_action_preference" not in next_metadata and "auto_approve_preference" not in next_metadata:
                raise ServiceError(
                    "invalid_request",
                    "At least one preference field is required: 'repository_action_preference' or 'auto_approve_preference'.",
                    400,
                )

            updated_workspace = storage.update_workspace(parts[1], metadata=next_metadata)
            return 200, {"workspace": updated_workspace}

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "repositories"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {
                "repositories": storage.list_workspace_repositories(workspace_id)
            }

        if (
            method == "POST"
            and len(parts) == 4
            and parts[0] == "workspaces"
            and parts[2] == "repositories"
            and parts[3] == "preview"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {
                "preview": _preview_repository_intake(_required_text(body, "path"))
            }

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "repositories"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            if body.get("approved") is not True:
                raise ServiceError(
                    "approval_required",
                    "Repository intake must be explicitly approved before attach.",
                    409,
                )
            preview = _preview_repository_intake(_required_text(body, "path"))
            repository = storage.create_workspace_repository(
                workspace_id=workspace_id,
                name=_optional_text(body, "name") or preview["name"],
                path=preview["path"],
                remote_url=_optional_text(body, "remote_url") or preview["remote_url"],
                metadata={
                    "intake": preview,
                    "approved": True,
                },
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                event_type="workspace.repository.attached",
                payload={"object_id": repository["id"], "path": repository["path"]},
            )
            return 201, {"repository": repository}

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "projects"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            projects = storage.list_projects(workspace_id)
            for proj in projects:
                stats = storage.get_project_stats(proj["id"])
                proj["task_count"] = stats["task_count"]
                proj["blocked_count"] = stats["blocked_count"]
                proj["review_needed_count"] = stats["review_needed_count"]
                proj["updated_at"] = stats["last_activity"] or proj["updated_at"]
            return 200, {"projects": projects}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "projects"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            project = storage.create_project(
                workspace_id=workspace_id,
                name=_required_text(body, "name"),
                description=_optional_text(body, "description"),
                metadata=_optional_dict(body, "metadata"),
            )
            return 201, {"project": project}

        if (
            method == "POST"
            and len(parts) == 5
            and parts[0] == "workspaces"
            and parts[2] == "providers"
            and parts[4] == "test"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {
                "provider": _test_and_store_provider(storage, workspace_id, parts[3], body)
            }

        if (
            method == "POST"
            and len(parts) == 5
            and parts[0] == "workspaces"
            and parts[2] == "repositories"
            and parts[4] == "initialize"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            repository = storage.get_workspace_repository(parts[3])
            if repository is None or repository["workspace_id"] != workspace_id:
                raise ServiceError("not_found", "Repository not found.", 404)
            return 201, _initialize_workspace_repository(storage, repository, body)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "tasks"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {"tasks": storage.list_tasks_for_workspace(workspace_id)}

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "task-dashboard"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {
                "tasks": _task_dashboard(
                    storage,
                    workspace_id,
                    project_id=_first_query(query, "project_id"),
                )
            }

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "operational-views"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_operational_views(storage, workspace_id)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "dogfood-acceptance"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _dogfood_acceptance(storage, workspace)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "dogfood-learning"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 201, _approve_dogfood_learning(storage, workspace, body)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "tasks"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            task = storage.create_task(
                workspace_id=workspace_id,
                title=_required_text(body, "title"),
                description=_optional_text(body, "description"),
                metadata=_merge_task_defaults(_optional_dict(body, "metadata")),
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task["id"],
                event_type="task.created",
                payload={"object_id": task["id"]},
            )
            return 201, {"task": task}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "task-drafts"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            prompt = _required_text(body, "prompt")
            title = _optional_text(body, "title") or _derive_task_title(prompt)
            context = _optional_dict(body, "context") or {}
            metadata = _task_draft_metadata(
                prompt,
                project_id=_task_context_project_id(context),
            )
            task = storage.create_task(
                workspace_id=workspace_id,
                title=title,
                status="prd_pending",
                description=metadata["prd"]["problem"],
                metadata=metadata,
            )
            user_message = storage.create_message(
                workspace_id=workspace_id,
                task_id=task["id"],
                role="user",
                content=prompt,
                metadata={"target": "Sarathi", "source": "orchestrator_chat"},
            )
            sarathi_message = storage.create_message(
                workspace_id=workspace_id,
                task_id=task["id"],
                role="sarathi",
                content=(
                    "I drafted the PRD/AC shell and opened the PRD/AC approval gate "
                    "before graph generation."
                ),
                metadata={"draft_task_id": task["id"], "gate": "PRD/AC"},
            )
            gate = storage.create_approval_gate(
                workspace_id=workspace_id,
                task_id=task["id"],
                name="PRD/AC",
                status="pending",
                metadata={
                    "requires_human": True,
                    "source_prompt": prompt,
                    "acceptance_criteria": metadata["acceptance_criteria"],
                },
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task["id"],
                event_type="task.draft_created",
                payload={"object_id": task["id"], "gate": gate["id"]},
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task["id"],
                event_type="approval.requested",
                payload={"object_id": gate["id"], "name": gate["name"]},
            )
            return 201, {
                "task": task,
                "approval_gate": gate,
                "messages": [user_message, sarathi_message],
            }

        if (
            method == "POST"
            and len(parts) == 5
            and parts[0] == "workspaces"
            and parts[2] == "github"
            and parts[3] == "issues"
            and parts[4] == "import"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            context = _optional_dict(body, "context") or {}
            project_id = _task_context_project_id(context)
            issue, repository = _build_github_issue_reference(storage, workspace_id, body)
            task_title = _optional_text(body, "title") or f"GitHub issue #{issue['number']}"
            task_metadata = _task_draft_metadata(
                issue["url"] or f"GitHub issue #{issue['number']}",
                project_id=project_id,
            )
            task_metadata["source"] = "github_issue"
            task_metadata["github_issue"] = issue
            repository_metadata: dict[str, Any] = {}
            if issue["full_name"]:
                repository_metadata["github"] = {
                    "host": issue["host"],
                    "owner": issue["owner"],
                    "name": issue["name"],
                    "full_name": issue["full_name"],
                    "repository_url": issue["repository_url"],
                }
            if repository is not None:
                repository_metadata.update(_github_repository_metadata(repository))
                if repository.get("remote_url"):
                    repository_metadata["remote_url"] = repository["remote_url"]
            if repository_metadata:
                task_metadata["repository"] = repository_metadata
            task = storage.create_task(
                workspace_id=workspace_id,
                title=task_title,
                status="prd_pending",
                description=issue["url"] or f"Imported GitHub issue #{issue['number']}.",
                metadata=task_metadata,
            )
            user_message = storage.create_message(
                workspace_id=workspace_id,
                task_id=task["id"],
                role="user",
                content=issue["url"] or f"GitHub issue #{issue['number']}",
                metadata={"target": "Sarathi", "source": "github_issue_import"},
            )
            sarathi_message = storage.create_message(
                workspace_id=workspace_id,
                task_id=task["id"],
                role="sarathi",
                content=(
                    "I drafted the PRD/AC shell from the GitHub issue reference and opened "
                    "the PRD/AC approval gate before graph generation."
                ),
                metadata={"draft_task_id": task["id"], "gate": "PRD/AC", "source": "github_issue_import"},
            )
            gate = storage.create_approval_gate(
                workspace_id=workspace_id,
                task_id=task["id"],
                name="PRD/AC",
                status="pending",
                metadata={
                    "requires_human": True,
                    "source_issue": issue["url"] or f"GitHub issue #{issue['number']}",
                    "acceptance_criteria": task_metadata["acceptance_criteria"],
                },
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task["id"],
                event_type="task.draft_created",
                payload={"object_id": task["id"], "gate": gate["id"]},
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task["id"],
                event_type="approval.requested",
                payload={"object_id": gate["id"], "name": gate["name"]},
            )
            return 201, {
                "task": task,
                "approval_gate": gate,
                "messages": [user_message, sarathi_message],
            }

        if method == "GET" and len(parts) == 2 and parts[0] == "tasks":
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 200, {"task": task}

        if method == "GET" and len(parts) == 3 and parts[0] == "tasks":
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            resource = parts[2]
            if resource == "studio":
                return 200, _task_studio_snapshot(storage, task)
            if resource == "panel":
                return 200, {
                    "task_id": task["id"],
                    "entries": storage.list_task_panel_entries(task["id"]),
                }
            if resource == "graph":
                return 200, _graph_for_task(storage, task)
            if resource == "evidence":
                return 200, {
                    "task_id": parts[1],
                    "evidence": storage.list_evidence_artifacts_for_task(parts[1]),
                }
            if resource == "reviews":
                return 200, {
                    "task_id": parts[1],
                    "reviews": storage.list_review_runs_for_task(parts[1]),
                }
            if resource == "handoff":
                return 200, {
                    "task_id": parts[1],
                    "handoff": _latest_or_none(storage.list_handoffs_for_task(parts[1])),
                }
            if resource == "checkpoint":
                return 200, {
                    "task_id": parts[1],
                    "checkpoint": _latest_or_none(
                        storage.list_checkpoint_capsules_for_task(parts[1])
                    ),
                }
            if resource == "checkpoints":
                checkpoints = storage.list_checkpoint_capsules_for_task(parts[1])
                checkpoints.reverse()
                return 200, {
                    "task_id": parts[1],
                    "checkpoints": checkpoints,
                }
            if resource == "messages":
                return 200, {"messages": storage.list_messages(task_id=parts[1])}
            if resource == "approvals":
                return 200, {
                    "approval_gates": storage.list_approval_gates_for_task(parts[1])
                }

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "dispatches"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 200, {"dispatches": storage.list_dispatches_for_task(parts[1])}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "messages"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            message = storage.create_message(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                role=_optional_text(body, "role") or "user",
                content=_required_text(body, "content"),
                metadata={"target": _optional_text(body, "target") or "Current task agents"},
            )
            storage.create_lifecycle_event(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                event_type="message.created",
                payload={"object_id": message["id"], "target": message["metadata"]["target"]},
            )
            return 201, {"message": message}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "graph-draft"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            if not _has_approved_gate(storage, task["id"], "PRD/AC"):
                raise ServiceError(
                    "approval_required",
                    "Approve PRD/AC before generating the task graph.",
                    409,
                )
            existing_graph = _graph_for_task(storage, task)
            if existing_graph["nodes"]:
                graph = existing_graph
            else:
                graph = _create_graph_draft(storage, task)
            gate = storage.create_approval_gate(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                name="Task graph",
                status="pending",
                metadata={
                    "requires_human": True,
                    "node_count": len(graph["nodes"]),
                    "edge_count": len(graph["edges"]),
                },
            )
            storage.create_lifecycle_event(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                event_type="task.graph_draft_created",
                payload={"object_id": task["id"], "node_count": len(graph["nodes"])},
            )
            storage.create_lifecycle_event(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                event_type="approval.requested",
                payload={"object_id": gate["id"], "name": gate["name"]},
            )
            return 201, {"graph": graph, "approval_gate": gate}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "approve"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            gate = storage.create_approval_gate(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                name=_required_text(body, "name"),
                status=_required_text(body, "status"),
                metadata=_optional_dict(body, "metadata"),
            )
            storage.create_lifecycle_event(
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                event_type="approval.recorded",
                payload={"object_id": gate["id"], "status": gate["status"]},
            )
            result: dict[str, Any] = {"approval_gate": gate}
            if gate["name"] == "Task graph" and gate["status"] == "approved":
                result["auto_schedule"] = _maybe_auto_schedule_ready_subtasks(
                    storage,
                    task,
                    reason="task_graph_approved",
                )
            return 201, result

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "auto-approve"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)

            workspace = storage.get_workspace(task["workspace_id"])
            preference = _effective_auto_approve_preference(task, workspace)
            policy_defaults = _get_policy_pack_approval_defaults()

            if preference["mode"] == "manual_only":
                raise ServiceError(
                    "auto_approve_disabled",
                    "Auto-approve is disabled. Policy requires manual approval for all gates.",
                    403,
                )

            denylist = policy_defaults["never_auto_approve_gates"]
            pending_gates = [
                g for g in storage.list_approval_gates_for_task(task["id"])
                if g["status"] == "pending"
            ]

            denylisted_gates = [g for g in pending_gates if _is_gate_denylisted(g["name"], denylist)]
            if denylisted_gates:
                denylisted_names = ", ".join(g["name"] for g in denylisted_gates)
                raise ServiceError(
                    "auto_approve_denied",
                    f"Auto-approve is not permitted for the following gates: {denylisted_names}. These gates require manual approval.",
                    403,
                )

            approved = []
            for pending_gate in pending_gates:
                if preference["mode"] == "below_threshold":
                    if not _evaluate_threshold(preference, pending_gate.get("metadata")):
                        continue

                approved_gate = storage.create_approval_gate(
                    workspace_id=task["workspace_id"],
                    task_id=task["id"],
                    name=pending_gate["name"],
                    status="approved",
                    metadata={
                        **(pending_gate.get("metadata") or {}),
                        "auto_approved": True,
                        "preference_scope": preference["scope"],
                        "preference_mode": preference["mode"],
                        "policy_source": "policy-pack/approval.md",
                        "approved_by": _optional_text(body, "approved_by") or "auto",
                    },
                )
                storage.create_lifecycle_event(
                    workspace_id=task["workspace_id"],
                    task_id=task["id"],
                    event_type="approval.recorded",
                    payload={
                        "object_id": approved_gate["id"],
                        "status": "approved",
                        "auto_approved": True,
                        "preference_scope": preference["scope"],
                        "preference_mode": preference["mode"],
                    },
                )
                approved.append(approved_gate)

            if not approved:
                raise ServiceError(
                    "auto_approve_no_eligible_gates",
                    "No gates were eligible for auto-approve under the current policy.",
                    403,
                )

            auto_schedule = _maybe_auto_schedule_ready_subtasks(storage, task, reason="auto_approve")
            return 200, {"approved": approved, "auto_schedule": auto_schedule}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "schedule"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            if not _has_approved_gate(storage, task["id"], "Task graph"):
                raise ServiceError(
                    "approval_required",
                    "Approve Task graph before scheduling ready units.",
                    409,
                )
            return 200, _schedule_ready_subtasks(storage, task)

        if (
            method == "POST"
            and len(parts) == 4
            and parts[0] == "tasks"
            and parts[2] == "reviews"
            and parts[3] == "run"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 201, _run_task_review(storage, task, body)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "handoff"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 201, _create_task_handoff(storage, task)

        if (
            method == "POST"
            and len(parts) == 4
            and parts[0] == "tasks"
            and parts[2] == "checkpoint"
            and parts[3] == "restart"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            checkpoint = _latest_or_none(storage.list_checkpoint_capsules_for_task(task["id"]))
            if checkpoint is None:
                raise ServiceError("not_found", "Checkpoint not found.", 404)
            new_task = storage.create_task(
                workspace_id=checkpoint["workspace_id"],
                title=f"Resume: {checkpoint['summary'][:80]}",
                description=checkpoint["summary"],
                status="prd_pending",
                metadata={
                    "source_checkpoint_id": checkpoint["id"],
                    "source_task_id": checkpoint["source_task_id"],
                    "project_id": checkpoint["project_id"],
                    "repository_action_preference": checkpoint["repository_action_preference"],
                },
            )
            storage.create_lifecycle_event(
                workspace_id=checkpoint["workspace_id"],
                task_id=new_task["id"],
                event_type="task.checkpoint_restarted",
                payload={
                    "object_id": checkpoint["id"],
                    "source_task_id": checkpoint["source_task_id"],
                },
            )
            return 201, {"task": new_task, "checkpoint": checkpoint}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "repository-action"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 201, _record_repository_action(storage, task, body)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "subtasks"
            and parts[2] == "transition"
        ):
            subtask = storage.get_subtask(parts[1])
            if subtask is None:
                raise ServiceError("not_found", "Subtask not found.", 404)
            return 200, _transition_subtask(storage, subtask, body)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "subtasks"
            and parts[2] == "dispatch"
        ):
            subtask = storage.get_subtask(parts[1])
            if subtask is None:
                raise ServiceError("not_found", "Subtask not found.", 404)
            return 201, _dispatch_subtask(storage, subtask, body)

        if method == "GET" and parts == ["providers"]:
            workspace_id = _first_query(query, "workspace_id")
            if workspace_id and storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {"providers": _provider_health(storage, workspace_id)}

        if method == "POST" and parts == ["chat"]:
            return 201, _handle_chat(storage, body)

        if method == "GET" and parts == ["events"]:
            workspace_id = _first_query(query, "workspace_id")
            task_id = _first_query(query, "task_id")
            if workspace_id and storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, {
                "events": storage.list_events(workspace_id=workspace_id, task_id=task_id)
            }

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "policy-pack"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _get_policy_pack(storage, workspace_id)

        if (
            method == "PUT"
            and len(parts) == 4
            and parts[0] == "workspaces"
            and parts[2] == "policy-pack"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            filename = parts[3]
            return 200, _put_policy_pack_file(storage, workspace_id, filename, body)

        # ── Brainstorm sessions ──────────────────────────────────────────────
        if method == "POST" and len(parts) == 2 and parts[0] == "brainstorm" and parts[1] == "sessions":
            workspace_id = _required_text(body, "workspace_id")
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            title = _required_text(body, "title")
            project_id = _optional_text(body, "project_id")
            provider = _optional_text(body, "provider")
            output_format = _optional_text(body, "output_format") or "markdown"
            session = storage.create_brainstorm_session(
                workspace_id=workspace_id,
                title=title,
                project_id=project_id,
                provider=provider,
                output_format=output_format,
            )
            _emit_brainstorm_event(storage, "brainstorm.session_started", {
                "session_id": session["id"], "workspace_id": workspace_id, "title": title,
            }, workspace_id=workspace_id)
            return 200, {"session": session}

        if method == "GET" and len(parts) == 2 and parts[0] == "brainstorm":
            session = storage.get_brainstorm_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            return 200, {"session": session}

        if method == "POST" and len(parts) == 3 and parts[0] == "brainstorm" and parts[2] == "turns":
            session = storage.get_brainstorm_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            turn: dict[str, Any] = {
                "role": _required_text(body, "role"),
                "content": _required_text(body, "content"),
                "options": body.get("options", []),
                "selected": body.get("selected"),
                "timestamp": _service_now(),
            }
            updated = storage.append_brainstorm_turn(session["id"], turn)
            spec_update = _optional_text(body, "spec_update")
            if spec_update:
                updated = storage.update_brainstorm_spec(session["id"], spec_update)
                _emit_brainstorm_event(storage, "brainstorm.spec_updated",
                    {"session_id": session["id"]}, workspace_id=updated["workspace_id"])
            _emit_brainstorm_event(storage, "brainstorm.turn_added",
                {"session_id": session["id"], "role": turn["role"]},
                workspace_id=updated["workspace_id"])
            return 200, {"session": updated}

        if method == "POST" and len(parts) == 3 and parts[0] == "brainstorm" and parts[2] == "research":
            session = storage.get_brainstorm_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            finding: dict[str, Any] = {
                "agent": _required_text(body, "agent"),
                "type": _optional_text(body, "type") or "codebase",
                "summary": _required_text(body, "summary"),
                "refs": body.get("refs", []),
                "timestamp": _service_now(),
            }
            updated = storage.append_brainstorm_research(session["id"], finding)
            _emit_brainstorm_event(storage, "brainstorm.research_added",
                {"session_id": session["id"], "agent": finding["agent"]},
                workspace_id=updated["workspace_id"])
            return 200, {"session": updated}

        if method == "POST" and len(parts) == 3 and parts[0] == "brainstorm" and parts[2] == "approve":
            session = storage.get_brainstorm_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            if session["status"] == "approved":
                raise ServiceError("conflict", "Session already approved.", 409)
            spec_content = session["spec_content"] or f"# {session['title']}\n"
            task = storage.create_task(
                workspace_id=session["workspace_id"],
                title=session["title"],
                description=spec_content,
                metadata={
                    "source": "brainstorm",
                    "brainstorm_session_id": session["id"],
                    "project_id": session["project_id"],
                },
            )
            approved = storage.approve_brainstorm_session(session["id"], task_id=task["id"])
            spec_path = _write_brainstorm_spec(approved)
            if spec_path:
                approved = storage.update_brainstorm_spec(session["id"], spec_content, spec_path=spec_path)
            _emit_brainstorm_event(storage, "brainstorm.approved",
                {"session_id": session["id"], "task_id": task["id"]},
                workspace_id=session["workspace_id"])
            return 200, {"session": approved, "task": task}

        raise ServiceError("not_found", "Endpoint not found.", 404)

    def _authorize(self, headers: Mapping[str, str] | None) -> None:
        if self.token is None:
            return
        for key, value in (headers or {}).items():
            if key.lower() == "authorization" and value == f"Bearer {self.token}":
                return
        raise ServiceError("unauthorized", "Missing or invalid authorization token.", 401)

    def _authorize_stream(
        self,
        headers: Mapping[str, str] | None,
        query: Mapping[str, list[str]],
    ) -> None:
        if self.token is None:
            return
        try:
            self._authorize(headers)
            return
        except ServiceError:
            pass
        if _first_query(query, "token") == self.token:
            return
        raise ServiceError("unauthorized", "Missing or invalid authorization token.", 401)


def create_app(db_path: str | Path, token: str | None = None) -> ServiceApp:
    return ServiceApp(db_path, token=token)


def create_http_server(
    *,
    db_path: str | Path,
    token: str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    app = create_app(db_path, token=token)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_OPTIONS(self) -> None:
            self.send_response(204, "No Content")
            self._write_cors_headers()
            self.send_header("content-length", "0")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_DELETE(self) -> None:
            self._handle()

        def do_PATCH(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self) -> None:
            is_loopback = self.client_address[0] in ("127.0.0.1", "::1", "localhost")

            if self.command == "GET" and _path_parts(self.path) == ["api", "events", "stream"]:
                self._handle_sse(skip_auth=is_loopback)
                return

            body, error = self._read_json_body()
            if error is not None:
                correlation_id = _correlation_id(self.headers)
                self._write_json(error.status, _error(error, correlation_id))
                return

            status, payload = app.handle(
                self.command,
                self.path,
                body=body,
                headers=dict(self.headers.items()),
                skip_auth=is_loopback,
            )
            self._write_json(status, payload)

        def _handle_sse(self, skip_auth: bool = False) -> None:
            correlation_id = _correlation_id(self.headers)
            try:
                if not skip_auth:
                    app._authorize_stream(dict(self.headers.items()), _query(self.path))
                status, data = app._route("GET", ["api", "events"], _query(self.path), {})
                payload = json.dumps(data, sort_keys=True)
                self.send_response(status, HTTPStatus(status).phrase)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "keep-alive")
                self.send_header("x-accel-buffering", "no")
                self._write_cors_headers()
                self.end_headers()
                last_payload = payload
                try:
                    self._write_sse_snapshot(payload)
                    while True:
                        time.sleep(2.0)
                        try:
                            _, next_data = app._route("GET", ["api", "events"], _query(self.path), {})
                        except ServiceError:
                            break
                        next_payload = json.dumps(next_data, sort_keys=True)
                        if next_payload != last_payload:
                            self._write_sse_snapshot(next_payload)
                            last_payload = next_payload
                        else:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            except ServiceError as error:
                self._write_json(error.status, _error(error, correlation_id))

        def _write_sse_snapshot(self, payload: str) -> None:
            encoded = f"event: snapshot\ndata: {payload}\n\n".encode("utf-8")
            self.wfile.write(encoded)
            self.wfile.flush()

        def _read_json_body(self) -> tuple[dict[str, Any] | None, ServiceError | None]:
            try:
                length = int(self.headers.get("content-length") or "0")
            except ValueError:
                return None, ServiceError("invalid_request", "Content-Length must be numeric.", 400)
            if length > MAX_BODY_BYTES:
                return None, ServiceError("request_too_large", "Request body is too large.", 413)
            if length == 0:
                return None, None
            try:
                decoded = self.rfile.read(length).decode("utf-8")
                payload = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, ServiceError("invalid_json", "Request body must be valid JSON.", 400)
            if not isinstance(payload, dict):
                return None, ServiceError("invalid_request", "Request body must be a JSON object.", 400)
            return payload, None

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status, HTTPStatus(status).phrase)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.send_header("connection", "close")
            self._write_cors_headers()
            self.end_headers()
            self.wfile.write(encoded)
            self.close_connection = True

        def _write_cors_headers(self) -> None:
            origin = self.headers.get("origin")
            allowed_origin = origin if _browser_origin_allowed(origin) else "http://127.0.0.1:5173"
            self.send_header("access-control-allow-origin", allowed_origin)
            self.send_header("vary", "Origin")
            self.send_header("access-control-allow-methods", "GET, POST, DELETE, PATCH, PUT, OPTIONS")
            self.send_header(
                "access-control-allow-headers",
                "authorization, content-type, x-correlation-id",
            )

    class LocalThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

        def server_bind(self) -> None:
            # HTTPServer.server_bind performs a reverse DNS lookup for server_name,
            # which can stall local desktop startup on some macOS resolver setups.
            socketserver.TCPServer.server_bind(self)
            host, bound_port = self.server_address[:2]
            self.server_name = str(host)
            self.server_port = int(bound_port)
            _write_service_discovery(str(host), int(bound_port))

        def server_close(self) -> None:
            super().server_close()
            _delete_service_discovery()

    return LocalThreadingHTTPServer((host, port), Handler)


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("?")[0].split("/") if part]


def _query(path: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(path).query)


def _first_query(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _correlation_id(headers: Mapping[str, str] | None) -> str:
    if headers:
        for key, value in headers.items():
            if key.lower() == "x-correlation-id" and value:
                return value
    return uuid4().hex


def _ok(data: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    return {"ok": True, "data": data, "correlation_id": correlation_id}


def _error(error: ServiceError, correlation_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "status": error.status,
        },
        "correlation_id": correlation_id,
    }


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


def _parse_github_issue_url(issue_url: str) -> dict[str, Any]:
    parsed = urlparse(issue_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "issues":
        raise ServiceError(
            "invalid_request",
            "GitHub issue URLs must look like https://github.com/<owner>/<repo>/issues/<number>.",
            400,
        )
    owner, repo, _, number_text = parts[:4]
    try:
        issue_number = int(number_text)
    except ValueError as exc:
        raise ServiceError("invalid_request", "GitHub issue number must be an integer.", 400) from exc
    return {
        "url": issue_url,
        "host": parsed.netloc,
        "owner": owner,
        "name": repo,
        "full_name": f"{owner}/{repo}",
        "number": issue_number,
        "repository_url": f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}",
    }


def _github_repository_metadata(repository: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "workspace_repository_id": repository["id"],
        "workspace_repository_name": repository["name"],
        "workspace_repository_path": repository["path"],
        "workspace_repository_remote_url": repository["remote_url"],
    }
    return metadata


def _resolve_issue_repository(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
) -> dict[str, Any] | None:
    repository_id = _optional_text(body, "repository_id")
    if repository_id is not None:
        repository = storage.get_workspace_repository(repository_id)
        if repository is None or repository["workspace_id"] != workspace_id:
            raise ServiceError("not_found", "Repository not found.", 404)
        return repository

    repositories = storage.list_workspace_repositories(workspace_id)
    if len(repositories) == 1 and body.get("issue_number") is not None:
        return repositories[0]
    return None


def _build_github_issue_reference(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    issue_url = _optional_text(body, "issue_url")
    if issue_url:
        issue = _parse_github_issue_url(issue_url)
        repository = _resolve_issue_repository(storage, workspace_id, body)
        issue["repository"] = {
            "host": issue["host"],
            "owner": issue["owner"],
            "name": issue["name"],
            "full_name": issue["full_name"],
            "repository_url": issue["repository_url"],
        }
        if repository is not None:
            issue["repository"].update(_github_repository_metadata(repository))
            if repository.get("remote_url"):
                issue["repository"]["remote_url"] = repository["remote_url"]
        return issue, repository

    issue_number_value = body.get("issue_number")
    if issue_number_value is None:
        raise ServiceError("invalid_request", "Field 'issue_url' or 'issue_number' is required.", 400)
    if not isinstance(issue_number_value, int):
        raise ServiceError("invalid_request", "Field 'issue_number' must be an integer.", 400)
    repository = _resolve_issue_repository(storage, workspace_id, body)
    if repository is None:
        raise ServiceError(
            "invalid_request",
            "Provide repository_id when importing a GitHub issue by number.",
            400,
        )
    issue = {
        "url": None,
        "host": None,
        "owner": None,
        "name": None,
        "full_name": None,
        "number": issue_number_value,
        "repository_url": None,
    }
    issue["repository"] = _github_repository_metadata(repository)
    if repository.get("remote_url"):
        issue["repository"]["remote_url"] = repository["remote_url"]
    return issue, repository


def _derive_task_title(prompt: str) -> str:
    words = prompt.strip().split()
    if not words:
        return "Untitled orchestrated task"
    title = " ".join(words[:8]).strip(" .")
    return title[:80] or "Untitled orchestrated task"


def _task_draft_metadata(
    prompt: str,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_prompt": prompt,
        "complexity": "high",
        "phase": "prd_ac_draft",
        "prd": {
            "problem": prompt,
            "goal": "Turn the user request into an approved, workspace-scoped Sarathi task.",
            "scope": [
                "Capture source conversation.",
                "Draft acceptance criteria.",
                "Block graph generation until PRD/AC approval.",
            ],
        },
        "acceptance_criteria": [
            "A durable task draft exists in the selected workspace.",
            "The source prompt is preserved as a task-scoped user message.",
            "Sarathi creates a PRD/AC approval gate before task graph generation.",
        ],
        "repository_action_preference": _default_repository_action_preference(),
    }
    if project_id:
        metadata["project_id"] = project_id
    return metadata


def _task_context_project_id(context: Any) -> str | None:
    if not isinstance(context, Mapping):
        return None
    value = context.get("projectId")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _task_context_workspace_id(context: Any) -> str | None:
    if not isinstance(context, Mapping):
        return None
    value = context.get("workspaceId")
    if isinstance(value, str) and value.strip():
        return value
    return None


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


def _task_studio_snapshot(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["id"]
    return {
        "task": task,
        "graph": _graph_for_task(storage, task),
        "messages": storage.list_messages(task_id=task_id),
        "approval_gates": storage.list_approval_gates_for_task(task_id),
        "events": storage.list_events(task_id=task_id),
        "dispatches": storage.list_dispatches_for_task(task_id),
        "evidence": storage.list_evidence_artifacts_for_task(task_id),
        "reviews": storage.list_review_runs_for_task(task_id),
        "handoff": _latest_or_none(storage.list_handoffs_for_task(task_id)),
    }


def _workspace_operational_views(storage: Storage, workspace_id: str) -> dict[str, Any]:
    tasks = storage.list_tasks_for_workspace(workspace_id)
    projects = storage.list_projects(workspace_id)
    repositories = storage.list_workspace_repositories(workspace_id)
    history = storage.list_events(workspace_id=workspace_id)
    messages = storage.list_messages(workspace_id=workspace_id)
    providers = _provider_health(storage, workspace_id)
    all_subtasks: list[dict[str, Any]] = []
    all_dispatches: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []
    all_reviews: list[dict[str, Any]] = []
    all_handoffs: list[dict[str, Any]] = []
    diagrams: list[dict[str, Any]] = []

    for task in tasks:
        graph = _graph_for_task(storage, task)
        subtasks = storage.list_subtasks_for_task(task["id"])
        dispatches = storage.list_dispatches_for_task(task["id"])
        evidence = storage.list_evidence_artifacts_for_task(task["id"])
        reviews = storage.list_review_runs_for_task(task["id"])
        handoffs = storage.list_handoffs_for_task(task["id"])
        all_subtasks.extend(subtasks)
        all_dispatches.extend(dispatches)
        all_evidence.extend(evidence)
        all_reviews.extend(reviews)
        all_handoffs.extend(handoffs)
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
        latest_handoff = _latest_or_none(handoffs)
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
        project_summaries.append(
            {
                **project,
                "task_count": stats["task_count"],
                "blocked_count": stats["blocked_count"],
                "review_needed_count": stats["review_needed_count"],
                "updated_at": stats["last_activity"] or project["updated_at"],
            }
        )

    return {
        "workspace_id": workspace_id,
        "projects": project_summaries,
        "history": history,
        "lifecycle": lifecycle,
        "diagrams": diagrams,
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


def _dogfood_acceptance(storage: Storage, workspace: dict[str, Any]) -> dict[str, Any]:
    operations = _workspace_operational_views(storage, workspace["id"])
    tasks = storage.list_tasks_for_workspace(workspace["id"])
    completed_tasks = [task for task in tasks if task["status"] == "done"]
    graphs = [diagram for diagram in operations["diagrams"] if diagram["kind"] == "dependency_graph"]
    handoff_diagrams = [diagram for diagram in operations["diagrams"] if diagram["kind"] == "handoff"]
    approved_handoff_diagrams = [
        diagram
        for diagram in handoff_diagrams
        if diagram.get("repository_action", {}).get("status") == "approved"
    ]
    checks = [
        _acceptance_check(
            "workspace",
            "Workspace is first-class and contains persisted events.",
            bool(operations["history"]),
            [event["id"] for event in operations["history"][:3]],
        ),
        _acceptance_check(
            "prd_ac",
            "At least one task has PRD/AC metadata.",
            any(task["metadata"].get("acceptance_criteria") for task in tasks),
            [task["id"] for task in tasks if task["metadata"].get("acceptance_criteria")],
        ),
        _acceptance_check(
            "task_graph",
            "A persisted dependency graph exists.",
            bool(graphs),
            [diagram["id"] for diagram in graphs],
        ),
        _acceptance_check(
            "evidence",
            "Execution evidence exists.",
            operations["usage"]["evidence"]["total"] > 0,
            [diagram["id"] for diagram in graphs],
        ),
        _acceptance_check(
            "review_loop",
            "An approved review loop exists.",
            operations["usage"]["reviews"]["by_status"].get("approved", 0) > 0,
            [diagram["id"] for diagram in operations["diagrams"] if diagram["kind"] == "review_loop"],
        ),
        _acceptance_check(
            "handoff",
            "Final handoff and repository-action approval are recorded.",
            bool(approved_handoff_diagrams),
            [diagram["id"] for diagram in approved_handoff_diagrams],
        ),
        _acceptance_check(
            "operational_views",
            "Lifecycle, history, diagrams, and usage are service-backed.",
            bool(operations["lifecycle"]) and bool(operations["diagrams"]),
            [diagram["id"] for diagram in operations["diagrams"][:3]],
        ),
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "blocked"
    completed_task = completed_tasks[-1] if completed_tasks else (tasks[-1] if tasks else None)
    learning_record = _dogfood_learning_record(workspace, checks, completed_task, status)
    return {
        "workspace_id": workspace["id"],
        "status": status,
        "checks": checks,
        "release_dossier": {
            "title": "Built with Sarathi",
            "built_with": "Sarathi",
            "redacted": True,
            "summary": (
                f"Sarathi dogfood acceptance is {status}: "
                f"{operations['usage']['tasks']['total']} tasks, "
                f"{operations['usage']['subtasks']['total']} subtasks, "
                f"{operations['usage']['evidence']['total']} evidence artifacts, "
                f"{operations['usage']['reviews']['total']} reviews, "
                f"{operations['usage']['handoffs']['total']} handoff records."
            ),
            "validation_commands": [
                "python3 -m pytest",
                "npm --prefix desktop run build",
                "npm --prefix desktop audit --omit=dev",
                "sarathi validate ./policy-pack",
            ],
        },
        "learning_record": learning_record,
        "operations": operations,
    }


def _approve_dogfood_learning(
    storage: Storage,
    workspace: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Dogfood learning must be explicitly approved before writing learnings.md.",
            409,
        )
    acceptance = _dogfood_acceptance(storage, workspace)
    if acceptance["status"] != "passed":
        raise ServiceError(
            "acceptance_blocked",
            "Dogfood acceptance must pass before learning can be accepted.",
            409,
        )
    learning_record = dict(acceptance["learning_record"])
    learning_record["status"] = "accepted"
    workspace_root = Path(workspace["root_path"]).expanduser()
    learning_path = workspace_root / "learnings.md"
    learning_path.parent.mkdir(parents=True, exist_ok=True)
    existing = learning_path.read_text() if learning_path.exists() else "# Sarathi Workspace Learnings\n"
    section = _format_dogfood_learning_section(learning_record, acceptance)
    if "## Accepted Sarathi Dogfood Learning" not in existing:
        learning_path.write_text(existing.rstrip() + "\n\n" + section + "\n")
    elif learning_record["task_id"] not in existing:
        learning_path.write_text(existing.rstrip() + "\n\n" + section + "\n")
    learning_record["path"] = str(learning_path)
    storage.create_lifecycle_event(
        workspace_id=workspace["id"],
        event_type="learning.accepted",
        payload={
            "object_id": learning_record["id"],
            "task_id": learning_record["task_id"],
            "target_file": learning_record["target_file"],
        },
    )
    return {"learning_record": learning_record, "acceptance": acceptance}


def _acceptance_check(
    check_id: str,
    label: str,
    passed: bool,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "blocked",
        "evidence_refs": evidence_refs,
    }


def _dogfood_learning_record(
    workspace: dict[str, Any],
    checks: list[dict[str, Any]],
    task: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    task_id = task["id"] if task is not None else "workspace"
    return {
        "id": f"dogfood-{workspace['id']}-{task_id}",
        "status": "proposed",
        "task_id": task_id,
        "target_file": "learnings.md",
        "summary": (
            "A workspace-scoped operational snapshot can prove the full Sarathi loop "
            "without exposing private paths."
        ),
        "tags": ["dogfood-fixture", "workspace-first", "persist-before-publish"],
        "evidence_refs": [
            evidence_ref
            for check in checks
            for evidence_ref in check["evidence_refs"]
        ],
        "acceptance_status": status,
    }


def _format_dogfood_learning_section(
    learning_record: dict[str, Any],
    acceptance: dict[str, Any],
) -> str:
    checks = "\n".join(
        f"- {check['id']}: {check['status']} ({', '.join(check['evidence_refs']) or 'no refs'})"
        for check in acceptance["checks"]
    )
    tags = ", ".join(learning_record["tags"])
    return (
        "## Accepted Sarathi Dogfood Learning\n\n"
        f"- Task: {learning_record['task_id']}\n"
        f"- Status: {learning_record['acceptance_status']}\n"
        f"- Tags: {tags}\n"
        f"- Summary: {learning_record['summary']}\n"
        "- Evidence:\n"
        f"{checks}\n"
    )


def _create_task_handoff(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    reviews = storage.list_review_runs_for_task(task["id"])
    approved_reviews = [review for review in reviews if review["status"] == "approved"]
    if not approved_reviews:
        raise ServiceError(
            "approval_required",
            "An approved review is required before final handoff.",
            409,
    )
    graph = _graph_for_task(storage, task)
    evidence = storage.list_evidence_artifacts_for_task(task["id"])
    dispatches = storage.list_dispatches_for_task(task["id"])
    latest_review = approved_reviews[-1]
    ac_coverage = latest_review["metadata"].get("ac_coverage", [])
    workspace = storage.get_workspace(task["workspace_id"])
    repository_action_preference = _effective_repository_action_preference(task, workspace)
    summary = (
        f"Sarathi handoff for {task['title']}: "
        f"{len([node for node in graph['nodes'] if node['status'] == 'complete'])}/"
        f"{len(graph['nodes'])} units complete, {len(evidence)} evidence artifacts, "
        f"{len(approved_reviews)} approved reviews."
    )
    handoff = storage.create_handoff(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        from_agent="Sarathi",
        to_agent="User",
        summary=summary,
        metadata={
            "task_title": task["title"],
            "completed_units": [node["id"] for node in graph["nodes"] if node["status"] == "complete"],
            "open_units": [node["id"] for node in graph["nodes"] if node["status"] != "complete"],
            "evidence_ids": [item["id"] for item in evidence],
            "dispatch_ids": [item["id"] for item in dispatches],
            "review_ids": [item["id"] for item in approved_reviews],
            "ac_coverage": ac_coverage,
            "repository_action_preference": repository_action_preference,
            "repository_action": {
                "status": "pending",
                "action": None,
                "mode": repository_action_preference["mode"],
            },
        },
    )
    gate = storage.create_approval_gate(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        name="Repository action",
        status="pending",
        metadata={
            "requires_human": True,
            "handoff_id": handoff["id"],
            "allowed_actions": list(_REPOSITORY_ACTION_MODES),
            "default_action": repository_action_preference["mode"],
        },
    )
    task_metadata = dict(task["metadata"])
    task_metadata["phase"] = "repository_action_pending"
    storage.update_task(task["id"], status="repository_action_pending", metadata=task_metadata)
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="handoff.created",
        payload={"object_id": handoff["id"], "repository_action_gate": gate["id"]},
    )
    checkpoint = _create_task_checkpoint(
        storage,
        task,
        handoff,
        approved_reviews,
        next_start_point="Start from the handoff summary and approved review context.",
    )
    return {"handoff": handoff, "repository_action_gate": gate, "checkpoint": checkpoint}


def _record_repository_action(
    storage: Storage,
    task: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Repository actions require explicit approval.",
            409,
        )
    action = _optional_text(body, "action") or "no_action"
    if action not in _REPOSITORY_ACTION_MODES:
        raise ServiceError("invalid_request", "Unsupported repository action.", 400)
    handoff = _latest_or_none(storage.list_handoffs_for_task(task["id"]))
    if handoff is None:
        raise ServiceError("not_found", "Create handoff before repository action.", 404)
    approved_reviews = [
        review
        for review in storage.list_review_runs_for_task(task["id"])
        if review["status"] == "approved"
    ]
    metadata = dict(handoff["metadata"])
    repository_action = {
        "status": "approved",
        "action": action,
        "mode": action,
        "note": _optional_text(body, "note"),
    }
    metadata["repository_action"] = repository_action
    updated_handoff = storage.create_handoff(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        from_agent="Sarathi",
        to_agent="User",
        summary=handoff["summary"],
        metadata=metadata,
    )
    gate = storage.create_approval_gate(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        name="Repository action",
        status="approved",
        metadata={
            "handoff_id": updated_handoff["id"],
            "action": action,
            "requires_human": True,
        },
    )
    task_metadata = dict(task["metadata"])
    task_metadata["phase"] = "done"
    storage.update_task(task["id"], status="done", metadata=task_metadata)
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="repository_action.approved",
        payload={"object_id": updated_handoff["id"], "action": action, "approval_gate": gate["id"]},
    )
    checkpoint = _create_task_checkpoint(
        storage,
        task,
        updated_handoff,
        approved_reviews,
        next_start_point="Start from the completed handoff summary and repository-action result.",
    )
    return {
        "handoff": updated_handoff,
        "repository_action": repository_action,
        "approval_gate": gate,
        "checkpoint": checkpoint,
    }


def _create_task_checkpoint(
    storage: Storage,
    task: dict[str, Any],
    handoff: dict[str, Any],
    approved_reviews: list[dict[str, Any]],
    *,
    next_start_point: str,
) -> dict[str, Any]:
    workspace = storage.get_workspace(task["workspace_id"])
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    handoff_metadata = handoff.get("metadata") or {}
    repository_action_preference = handoff_metadata.get("repository_action_preference")
    if repository_action_preference is None:
        repository_action_preference = _effective_repository_action_preference(task, workspace)
    evidence_refs = handoff_metadata.get("evidence_ids")
    if not isinstance(evidence_refs, list):
        evidence_refs = [item["id"] for item in storage.list_evidence_artifacts_for_task(task["id"])]
    key_decisions = [
        review["summary"]
        for review in approved_reviews
        if review.get("summary")
    ][:3]
    if not key_decisions and handoff["summary"]:
        key_decisions = [handoff["summary"]]
    return storage.create_checkpoint_capsule(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        project_id=task["metadata"].get("project_id"),
        summary=handoff["summary"],
        key_decisions=key_decisions,
        evidence_refs=evidence_refs,
        repository_action_preference=repository_action_preference,
        next_start_point=next_start_point,
        created_by="Sarathi",
    )


def _run_task_review(
    storage: Storage,
    task: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    review_type = _optional_text(body, "review_type") or "code"
    subtasks = storage.list_subtasks_for_task(task["id"])
    review_units = [subtask for subtask in subtasks if subtask["status"] == "review"]
    evidence = storage.list_evidence_artifacts_for_task(task["id"])
    evidence_by_id = {item["id"]: item for item in evidence}
    evidenced_subtask_ids = {
        str(item["metadata"].get("subtask_id"))
        for item in evidence
        if item["metadata"].get("subtask_id")
    }
    missing_evidence = [
        subtask["id"] for subtask in review_units if subtask["id"] not in evidenced_subtask_ids
    ]
    ac_coverage = _acceptance_coverage(task, evidence)
    reviewed_evidence = [
        item
        for item in evidence
        if str(item["metadata"].get("subtask_id")) in {subtask["id"] for subtask in review_units}
    ]
    diff_summary = _review_diff_summary(reviewed_evidence)
    findings = _approved_review_findings(reviewed_evidence)
    coverage_gaps = _coverage_gap_ids(ac_coverage)
    if diff_summary.get("provider_spec_references", 0):
        findings.extend(_coverage_gap_findings(ac_coverage))
    blocking_findings = _blocking_review_findings(findings)

    if review_units and not missing_evidence and not blocking_findings and not coverage_gaps:
        completed = [
            storage.update_subtask(subtask["id"], status="complete") for subtask in review_units
        ]
        review = storage.create_review_run(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            status="approved",
            summary="Review approved with dispatch evidence.",
            metadata={
                "review_type": review_type,
                "reviewed_subtasks": [subtask["id"] for subtask in review_units],
                "ac_coverage": ac_coverage,
                "evidence_ids": [item["id"] for item in evidence],
                "diff_summary": diff_summary,
                "findings": findings,
            },
        )
        storage.create_lifecycle_event(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            event_type="review.completed",
            payload={
                "object_id": review["id"],
                "status": review["status"],
                "completed_subtasks": [subtask["id"] for subtask in completed],
            },
        )
        return {"review": review, "completed_subtasks": completed, "requeued_subtasks": []}

    rejection_summary = "Review rejected because evidence is missing."
    rejection_findings = _missing_evidence_findings(missing_evidence, evidence_by_id)
    rejection_subtask_ids = {
        subtask["id"] for subtask in review_units if subtask["id"] in missing_evidence
    }
    if not missing_evidence and (blocking_findings or coverage_gaps):
        rejection_summary = "Review rejected because provider evidence indicates spec drift."
        rejection_findings = findings
        rejection_subtask_ids = _review_requeue_subtask_ids(
            review_units=review_units,
            blocking_findings=blocking_findings,
            coverage_gaps=coverage_gaps,
        )

    requeued = [
        storage.update_subtask(subtask["id"], status="in_progress")
        for subtask in review_units
        if subtask["id"] in rejection_subtask_ids
    ]
    review = storage.create_review_run(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        status="rejected",
        summary=rejection_summary,
        metadata={
            "review_type": review_type,
            "reviewed_subtasks": [subtask["id"] for subtask in review_units],
            "missing_evidence": missing_evidence,
            "coverage_gaps": coverage_gaps,
            "blocking_finding_ids": [str(item.get("id")) for item in blocking_findings if item.get("id")],
            "ac_coverage": ac_coverage,
            "evidence_ids": [item["id"] for item in evidence],
            "diff_summary": diff_summary,
            "findings": rejection_findings,
        },
    )
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="review.rejected",
        payload={
            "object_id": review["id"],
            "status": review["status"],
            "missing_evidence": missing_evidence,
            "requeued_subtasks": [subtask["id"] for subtask in requeued],
        },
    )
    return {"review": review, "completed_subtasks": [], "requeued_subtasks": requeued}


def _acceptance_coverage(task: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    criteria = task["metadata"].get("acceptance_criteria", [])
    if not isinstance(criteria, list):
        criteria = []
    has_evidence = bool(evidence)
    spec_refs: list[dict[str, Any]] = []
    for item in evidence:
        response_evidence = item["metadata"].get("response_evidence", {})
        if not isinstance(response_evidence, Mapping):
            continue
        spec_trace = _provider_spec_trace(response_evidence)
        if spec_trace is None:
            continue
        for reference in spec_trace.get("references", []):
            if not isinstance(reference, Mapping):
                continue
            spec_refs.append(
                {
                    "ac_id": str(reference.get("ac_id") or "").strip() or None,
                    "criterion": str(reference.get("criterion") or "").strip() or None,
                    "evidence_id": item["id"],
                }
            )
    has_structured_spec_refs = bool(spec_refs)
    return [
        {
            "id": f"AC-{index + 1:02d}",
            "criterion": str(criterion),
            "covered": (
                bool(_matching_spec_reference_ids(spec_refs, f"AC-{index + 1:02d}", str(criterion)))
                if has_structured_spec_refs
                else has_evidence
            ),
            "evidence_ids": (
                _matching_spec_reference_ids(spec_refs, f"AC-{index + 1:02d}", str(criterion))
                if has_structured_spec_refs
                else [item["id"] for item in evidence] if has_evidence else []
            ),
        }
        for index, criterion in enumerate(criteria)
    ]


def _review_diff_summary(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    files: list[str] = []
    provider_trace_findings = 0
    provider_trace_providers: list[str] = []
    provider_diff_hunks = 0
    provider_diff_providers: list[str] = []
    provider_diff_blockers = 0
    provider_diff_confidences: list[float] = []
    provider_diff_risk_categories: list[str] = []
    provider_diff_highlights: list[str] = []
    provider_diff_region_inputs: list[dict[str, Any]] = []
    provider_spec_references = 0
    provider_spec_providers: list[str] = []
    for item in evidence:
        response_evidence = item["metadata"].get("response_evidence", {})
        if not isinstance(response_evidence, Mapping):
            continue
        changed_files = response_evidence.get("changed_files", [])
        if isinstance(changed_files, list):
            files.extend(str(path) for path in changed_files if str(path).strip())
        review_trace = _provider_review_trace(response_evidence)
        if review_trace is not None:
            provider_trace_findings += len(review_trace.get("findings", []))
            provider_name = review_trace.get("provider")
            if isinstance(provider_name, str) and provider_name.strip():
                provider_trace_providers.append(provider_name.strip())
        diff_trace = _provider_diff_trace(response_evidence)
        if diff_trace is not None:
            provider_diff_hunks += len(diff_trace.get("hunks", []))
            provider_name = diff_trace.get("provider")
            if isinstance(provider_name, str) and provider_name.strip():
                provider_diff_providers.append(provider_name.strip())
            for hunk in diff_trace.get("hunks", []):
                if not isinstance(hunk, Mapping):
                    continue
                status = str(hunk.get("status") or "").strip().lower()
                if status in {"fail", "blocked", "rejected"}:
                    provider_diff_blockers += 1
                confidence = hunk.get("confidence")
                if isinstance(confidence, (int, float)):
                    provider_diff_confidences.append(float(confidence))
                category = str(hunk.get("category") or "").strip()
                if category:
                    provider_diff_risk_categories.append(category)
                    file_path = str(hunk.get("file_path") or "").strip()
                    line_start = hunk.get("line_start")
                    line_end = hunk.get("line_end")
                    if file_path and isinstance(line_start, int) and isinstance(line_end, int):
                        provider_diff_highlights.append(
                            f"{category} / {file_path}:{line_start}-{line_end}"
                        )
                provider_diff_region_inputs.append(
                    {
                        "file_path": str(hunk.get("file_path") or "").strip() or None,
                        "category": str(hunk.get("category") or "").strip() or None,
                        "line_start": hunk.get("line_start"),
                        "line_end": hunk.get("line_end"),
                        "severity": str(hunk.get("severity") or "info"),
                        "confidence": (
                            float(hunk.get("confidence"))
                            if isinstance(hunk.get("confidence"), (int, float))
                            else None
                        ),
                    }
                )
        spec_trace = _provider_spec_trace(response_evidence)
        if spec_trace is not None:
            provider_spec_references += len(spec_trace.get("references", []))
            provider_name = spec_trace.get("provider")
            if isinstance(provider_name, str) and provider_name.strip():
                provider_spec_providers.append(provider_name.strip())
    unique_files = _unique_ordered(files)
    provider_diff_regions = _cluster_diff_regions(provider_diff_region_inputs)
    provider_diff_confidence = _average_confidence(provider_diff_confidences)
    review_confidence = _review_confidence_summary(
        provider_diff_blockers=provider_diff_blockers,
        provider_diff_confidence=provider_diff_confidence,
    )
    return {
        "changed_files": len(unique_files),
        "files": unique_files,
        "provider_trace_findings": provider_trace_findings,
        "provider_trace_providers": _unique_ordered(provider_trace_providers),
        "provider_diff_hunks": provider_diff_hunks,
        "provider_diff_providers": _unique_ordered(provider_diff_providers),
        "provider_diff_blockers": provider_diff_blockers,
        "provider_diff_confidence": provider_diff_confidence,
        "provider_diff_risk_categories": _unique_ordered(provider_diff_risk_categories),
        "provider_diff_highlights": _unique_ordered(provider_diff_highlights),
        "provider_diff_regions": provider_diff_regions,
        "review_confidence_verdict": review_confidence["verdict"],
        "review_confidence_reasons": review_confidence["reasons"],
        "provider_spec_references": provider_spec_references,
        "provider_spec_providers": _unique_ordered(provider_spec_providers),
    }


def _approved_review_findings(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    index = 1
    for item in evidence:
        response_evidence = item["metadata"].get("response_evidence", {})
        if not isinstance(response_evidence, Mapping):
            continue
        subtask_id = str(item["metadata"].get("subtask_id") or "")
        provider_name = str(item["metadata"].get("provider") or "") or None
        structured_findings_added = False
        review_trace = _provider_review_trace(response_evidence)
        if review_trace is not None and review_trace.get("findings"):
            provider_name = (
                review_trace.get("provider")
                if isinstance(review_trace.get("provider"), str)
                else provider_name
            )
            for trace_finding in review_trace["findings"]:
                if not isinstance(trace_finding, Mapping):
                    continue
                file_path = trace_finding.get("file_path")
                file_text = str(file_path).strip() if file_path is not None else ""
                line_start = trace_finding.get("line_start")
                line_end = trace_finding.get("line_end")
                findings.append(
                    {
                        "id": f"finding-{index:02d}",
                        "check": str(trace_finding.get("check") or "provider_trace"),
                        "status": str(trace_finding.get("status") or "pass"),
                        "severity": str(trace_finding.get("severity") or "info"),
                        "message": str(trace_finding.get("message") or "Provider review trace finding."),
                        "file_path": file_text or None,
                        "line_start": line_start if isinstance(line_start, int) else None,
                        "line_end": line_end if isinstance(line_end, int) else None,
                        "subtask_id": subtask_id,
                        "evidence_id": item["id"],
                        "provider": provider_name or None,
                    }
                )
                index += 1
                structured_findings_added = True

        diff_trace = _provider_diff_trace(response_evidence)
        if diff_trace is not None and diff_trace.get("hunks"):
            provider_name = (
                diff_trace.get("provider")
                if isinstance(diff_trace.get("provider"), str)
                else provider_name
            )
            for hunk in diff_trace["hunks"]:
                if not isinstance(hunk, Mapping):
                    continue
                file_path = hunk.get("file_path")
                file_text = str(file_path).strip() if file_path is not None else ""
                line_start = hunk.get("line_start")
                line_end = hunk.get("line_end")
                findings.append(
                    {
                        "id": f"finding-{index:02d}",
                        "check": str(hunk.get("check") or "diff_hunk"),
                        "status": str(hunk.get("status") or "pass"),
                        "severity": str(hunk.get("severity") or "info"),
                        "message": str(hunk.get("message") or "Provider diff hunk evidence."),
                        "file_path": file_text or None,
                        "line_start": line_start if isinstance(line_start, int) else None,
                        "line_end": line_end if isinstance(line_end, int) else None,
                        "header": str(hunk.get("header") or "").strip() or None,
                        "excerpt": str(hunk.get("excerpt") or "").strip() or None,
                        "category": str(hunk.get("category") or "").strip() or None,
                        "confidence": (
                            round(float(hunk.get("confidence")), 2)
                            if isinstance(hunk.get("confidence"), (int, float))
                            else None
                        ),
                        "suggestion": str(hunk.get("suggestion") or "").strip() or None,
                        "subtask_id": subtask_id,
                        "evidence_id": item["id"],
                        "provider": provider_name or None,
                    }
                )
                index += 1
                structured_findings_added = True

        spec_trace = _provider_spec_trace(response_evidence)
        if spec_trace is not None and spec_trace.get("references"):
            provider_name = (
                spec_trace.get("provider")
                if isinstance(spec_trace.get("provider"), str)
                else provider_name
            )
            for reference in spec_trace["references"]:
                if not isinstance(reference, Mapping):
                    continue
                file_path = reference.get("file_path")
                file_text = str(file_path).strip() if file_path is not None else ""
                line_start = reference.get("line_start")
                line_end = reference.get("line_end")
                findings.append(
                    {
                        "id": f"finding-{index:02d}",
                        "check": str(reference.get("check") or "spec_reference"),
                        "status": str(reference.get("status") or "pass"),
                        "severity": str(reference.get("severity") or "major"),
                        "message": str(reference.get("message") or "Provider spec reference evidence."),
                        "file_path": file_text or None,
                        "line_start": line_start if isinstance(line_start, int) else None,
                        "line_end": line_end if isinstance(line_end, int) else None,
                        "criterion": str(reference.get("criterion") or "").strip() or None,
                        "ac_id": str(reference.get("ac_id") or "").strip() or None,
                        "subtask_id": subtask_id,
                        "evidence_id": item["id"],
                        "provider": provider_name or None,
                    }
                )
                index += 1
                structured_findings_added = True

        changed_files = response_evidence.get("changed_files", [])
        if structured_findings_added or not isinstance(changed_files, list):
            continue
        for file_path in changed_files:
            file_text = str(file_path).strip()
            if not file_text:
                continue
            findings.append(
                {
                    "id": f"finding-{index:02d}",
                    "check": "diff_file",
                    "status": "pass",
                    "severity": "info",
                    "message": f"{file_text} included in review scope.",
                    "file_path": file_text,
                    "line_start": 1,
                    "line_end": 1,
                    "subtask_id": subtask_id,
                    "evidence_id": item["id"],
                    "provider": str(item["metadata"].get("provider") or "") or None,
                }
            )
            index += 1
    return findings


def _provider_review_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("review_trace")
    return _provider_trace_payload(value, list_key="findings")


def _provider_diff_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("diff_trace")
    return _provider_trace_payload(value, list_key="hunks")


def _provider_spec_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("spec_trace")
    return _provider_trace_payload(value, list_key="references")


def _provider_trace_payload(
    value: Any,
    *,
    list_key: str,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    payload_items = value.get(list_key, [])
    if not isinstance(payload_items, list):
        payload_items = []
    provider = value.get("provider")
    summary = value.get("summary")
    return {
        "provider": provider if isinstance(provider, str) else None,
        "summary": summary if isinstance(summary, str) else None,
        list_key: payload_items,
    }


def _matching_spec_reference_ids(
    references: list[dict[str, Any]],
    ac_id: str,
    criterion: str,
) -> list[str]:
    normalized_criterion = _normalize_requirement_text(criterion)
    evidence_ids: list[str] = []
    for reference in references:
        ref_ac_id = reference.get("ac_id")
        ref_criterion = reference.get("criterion")
        matches_ac_id = isinstance(ref_ac_id, str) and ref_ac_id.strip() == ac_id
        matches_criterion = (
            isinstance(ref_criterion, str)
            and _normalize_requirement_text(ref_criterion) == normalized_criterion
        )
        if matches_ac_id or matches_criterion:
            evidence_id = reference.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id.strip():
                evidence_ids.append(evidence_id)
    return _unique_ordered(evidence_ids)


def _normalize_requirement_text(value: str) -> str:
    return " ".join(value.lower().split())


def _average_confidence(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _cluster_diff_regions(hunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for hunk in hunks:
        file_path = hunk.get("file_path")
        category = hunk.get("category")
        line_start = hunk.get("line_start")
        line_end = hunk.get("line_end")
        if not isinstance(file_path, str) or not file_path.strip():
            continue
        if not isinstance(category, str) or not category.strip():
            continue
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            continue
        grouped.setdefault((file_path.strip(), category.strip()), []).append(hunk)

    regions: list[dict[str, Any]] = []
    for (file_path, category), items in grouped.items():
        sorted_items = sorted(items, key=lambda item: (int(item["line_start"]), int(item["line_end"])))
        clusters: list[list[dict[str, Any]]] = []
        current_cluster: list[dict[str, Any]] = []
        current_end = -1
        for item in sorted_items:
            item_start = int(item["line_start"])
            item_end = int(item["line_end"])
            if not current_cluster or item_start <= current_end + 1:
                current_cluster.append(item)
                current_end = max(current_end, item_end)
            else:
                clusters.append(current_cluster)
                current_cluster = [item]
                current_end = item_end
        if current_cluster:
            clusters.append(current_cluster)

        for cluster in clusters:
            severities = [str(item.get("severity") or "info") for item in cluster]
            confidences = [
                float(item["confidence"])
                for item in cluster
                if isinstance(item.get("confidence"), (int, float))
            ]
            regions.append(
                {
                    "file_path": file_path,
                    "category": category,
                    "line_start": min(int(item["line_start"]) for item in cluster),
                    "line_end": max(int(item["line_end"]) for item in cluster),
                    "hunk_count": len(cluster),
                    "highest_severity": _max_severity(severities),
                    "max_confidence": round(max(confidences), 2) if confidences else None,
                }
            )
    return sorted(regions, key=lambda item: (str(item["file_path"]), str(item["category"]), int(item["line_start"])))


def _max_severity(severities: list[str]) -> str:
    order = {"info": 0, "minor": 1, "major": 2, "critical": 3}
    return max(severities, key=lambda severity: order.get(str(severity), 0), default="info")


def _review_confidence_summary(
    *,
    provider_diff_blockers: int,
    provider_diff_confidence: float | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if provider_diff_blockers > 0:
        reasons.append(f"{provider_diff_blockers} blocking diff hunk(s) remain.")
    if provider_diff_confidence is not None and provider_diff_confidence < 0.75:
        reasons.append(f"Provider diff confidence average is {provider_diff_confidence}.")

    if provider_diff_blockers > 0:
        verdict = "low"
    elif provider_diff_confidence is None:
        verdict = "unknown"
    elif provider_diff_confidence >= 0.85:
        verdict = "high"
    elif provider_diff_confidence >= 0.75:
        verdict = "medium"
    else:
        verdict = "low"

    return {"verdict": verdict, "reasons": reasons}


def _missing_evidence_findings(
    missing_evidence: list[str],
    evidence_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    del evidence_by_id
    return [
        {
            "id": f"finding-{index + 1:02d}",
            "check": "missing_evidence",
            "status": "fail",
            "severity": "major",
            "message": "Review blocked because no dispatch evidence is attached to this subtask.",
            "file_path": None,
            "line_start": None,
            "line_end": None,
            "subtask_id": subtask_id,
            "evidence_id": None,
        }
        for index, subtask_id in enumerate(missing_evidence)
    ]


def _coverage_gap_ids(ac_coverage: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("id"))
        for item in ac_coverage
        if item.get("covered") is False and isinstance(item.get("id"), str)
    ]


def _coverage_gap_findings(ac_coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    index = 1
    for item in ac_coverage:
        if item.get("covered") is not False:
            continue
        ac_id = str(item.get("id") or "").strip() or None
        criterion = str(item.get("criterion") or "").strip() or None
        findings.append(
            {
                "id": f"coverage-gap-{index:02d}",
                "check": "acceptance_coverage",
                "status": "fail",
                "severity": "major",
                "message": "No provider-backed evidence mapped this acceptance criterion.",
                "file_path": None,
                "line_start": None,
                "line_end": None,
                "criterion": criterion,
                "ac_id": ac_id,
                "subtask_id": None,
                "evidence_id": None,
                "provider": None,
            }
        )
        index += 1
    return findings


def _blocking_review_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked_statuses = {"fail", "blocked", "rejected"}
    return [
        finding
        for finding in findings
        if str(finding.get("status") or "").strip().lower() in blocked_statuses
    ]


def _review_requeue_subtask_ids(
    *,
    review_units: list[dict[str, Any]],
    blocking_findings: list[dict[str, Any]],
    coverage_gaps: list[str],
) -> set[str]:
    subtask_ids = {
        str(finding.get("subtask_id"))
        for finding in blocking_findings
        if isinstance(finding.get("subtask_id"), str) and str(finding.get("subtask_id")).strip()
    }
    review_unit_ids = {subtask["id"] for subtask in review_units}
    matched = {subtask_id for subtask_id in subtask_ids if subtask_id in review_unit_ids}
    if matched:
        return matched
    if coverage_gaps:
        return review_unit_ids
    return matched


def _latest_or_none(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[-1] if items else None


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

    response = LocalDispatcher(provider_config=provider_config).dispatch(
        DispatchRequest(
            mode="execute",
            task_id=subtask["id"],
            phase="TaskTracking",
            prompt=subtask["title"],
            inputs={"node": _graph_node_from_subtask(subtask)},
            expected_outputs=["work_unit_result"],
            constraints={"purpose": "child_task_execution", "provider": provider},
        )
    )
    status = "completed" if response.success else "failed"
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
            **({"usage": response.usage.to_artifact()} if response.usage else {}),
            **({"error": response.error} if response.error else {}),
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
    resolved_path = _resolve_provider_path(str(config.get("path", spec["path"])))
    if resolved_path is None:
        raise ServiceError(
            "provider_unavailable",
            f"CLI path not found: {config.get('path', spec['path'])}",
            409,
        )
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    command = _provider_dispatch_command(
        provider_id=provider_id,
        path=resolved_path,
        workspace_root=str(workspace["root_path"]),
    )
    return {
        "provider": provider_id,
        "providers": {
            provider_id: {
                "type": "command",
                "command": command,
                "timeout_seconds": 300,
            }
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
            "health": "online",
            "auth": "not_required",
            "path": "sarathi-local",
            "capabilities": ["child_task_execution", "planning", "review_fixture"],
        },
        {
            "id": "codex",
            "name": "Codex",
            "provider_type": "cli",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "codex",
            "capabilities": ["coding", "planning", "review"],
        },
        {
            "id": "claude",
            "name": "Claude",
            "provider_type": "cli",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "claude",
            "capabilities": ["research", "critique", "review"],
        },
        {
            "id": "copilot",
            "name": "Copilot",
            "provider_type": "agent",
            "health": "configured_by_user",
            "auth": "github_auth",
            "path": "GitHub Copilot",
            "capabilities": ["coding", "pull_request_assist"],
        },
        {
            "id": "opencode",
            "name": "OpenCode",
            "provider_type": "cli",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "opencode",
            "capabilities": ["coding", "planning", "review"],
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
    task = storage.create_task(
        workspace_id=workspace_id,
        title=message[:100],
        status="prd_pending",
        description=message,
        metadata=_task_draft_metadata(
            message,
            project_id=_task_context_project_id(context),
        ),
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="task.chat_created",
        payload={"object_id": task["id"], "agent": provider},
    )
    return {"taskId": task["id"], "agent": provider, "status": "started"}


def _get_provider_priority(storage: Storage, workspace_id: str) -> list[str]:
    workspace = storage.get_workspace(workspace_id)
    if workspace:
        metadata = workspace.get("metadata") or {}
        priority = metadata.get("provider_priority")
        if isinstance(priority, list) and priority:
            return priority
    return ["claude", "codex", "copilot", "opencode"]


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
    path = _optional_text(body, "path") or spec["path"]
    auth = _optional_text(body, "auth") or spec["auth"]
    config = _provider_check_config(spec, path=path, auth=auth)
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


def _provider_check_config(spec: Mapping[str, Any], *, path: str, auth: str) -> dict[str, Any]:
    if spec["id"] == "local":
        return {
            "path": path,
            "auth": "not_required",
            "health": "online",
            "last_checked_at": _service_now(),
            "last_error": None,
        }
    resolved_path = shutil.which(path) if not Path(path).is_absolute() else (path if Path(path).exists() else None)
    if not resolved_path:
        return {
            "path": path,
            "auth": auth,
            "health": "offline",
            "last_checked_at": _service_now(),
            "last_error": f"CLI path not found: {path}",
        }
    if auth == "missing":
        return {
            "path": path,
            "auth": auth,
            "health": "offline",
            "last_checked_at": _service_now(),
            "last_error": "Auth is missing.",
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
            }
    except Exception:
        pass
    return {
        "path": path,
        "auth": auth,
        "health": "online",
        "last_checked_at": _service_now(),
        "last_error": None,
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
        "health": str(override.get("health", spec["health"])),
        "auth": str(override.get("auth", spec["auth"])),
        "path": str(override.get("path", spec["path"])),
        "capabilities": spec["capabilities"],
        "last_checked_at": override.get("last_checked_at"),
        "last_error": override.get("last_error"),
    }


def _service_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _browser_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.hostname in _ALLOWED_BROWSER_HOSTS


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


def _task_dashboard(
    storage: Storage,
    workspace_id: str,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    summaries = []
    for task in storage.list_tasks_for_workspace(workspace_id):
        if project_id is not None and task["metadata"].get("project_id") != project_id:
            continue
        approvals = storage.list_approval_gates_for_task(task["id"])
        graph = _graph_for_task(storage, task)
        next_gate = _next_pending_gate(approvals)
        summaries.append(
            {
                "id": task["id"],
                "workspace_id": task["workspace_id"],
                "title": task["title"],
                "status": task["status"],
                "phase": task["metadata"].get("phase", task["status"]),
                "approval_state": _approval_state(approvals),
                "graph_state": _graph_state(graph, approvals),
                "next_gate": next_gate["name"] if next_gate else None,
                "node_count": len(graph["nodes"]),
                "blocked_count": len(graph.get("blocked_nodes", [])) + len(graph.get("waiting_human_nodes", [])),
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
            }
        )
    return summaries


def _unique_ordered(values: Any) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _next_pending_gate(approvals: list[dict[str, Any]]) -> dict[str, Any] | None:
    for gate in reversed(approvals):
        if gate["status"] == "pending":
            return gate
    return None


def _approval_state(approvals: list[dict[str, Any]]) -> str:
    if any(gate["name"] == "Task graph" and gate["status"] == "pending" for gate in approvals):
        return "graph_pending"
    if any(gate["name"] == "PRD/AC" and gate["status"] == "pending" for gate in approvals):
        return "prd_pending"
    if any(gate["status"] == "pending" for gate in approvals):
        return "approval_pending"
    return "approved" if approvals else "none"


def _graph_state(graph: dict[str, Any], approvals: list[dict[str, Any]]) -> str:
    if not graph["nodes"]:
        return "not_started"
    if any(gate["name"] == "Task graph" and gate["status"] == "pending" for gate in approvals):
        return "pending_approval"
    return "approved"


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


def _find_policy_pack_dir(storage: Storage, workspace_id: str) -> Path | None:
    repos = storage.list_workspace_repositories(workspace_id)
    for repo in repos:
        candidate = Path(repo["path"]).expanduser() / "policy-pack"
        if candidate.is_dir():
            return candidate
    return None


def _service_discovery_path() -> Path:
    return Path.home() / ".sarathi" / "service.json"


def _write_service_discovery(host: str, port: int) -> None:
    try:
        discovery = _service_discovery_path()
        discovery.parent.mkdir(parents=True, exist_ok=True)
        discovery.write_text(
            json.dumps({"url": f"http://{host}:{port}", "host": host, "port": port}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _delete_service_discovery() -> None:
    try:
        _service_discovery_path().unlink(missing_ok=True)
    except Exception:
        pass


def _emit_brainstorm_event(
    storage: Storage,
    event_type: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
) -> None:
    try:
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            task_id=None,
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        pass


def _write_brainstorm_spec(session: dict[str, Any]) -> str | None:
    try:
        sarathi_dir = Path(".sarathi") / "brainstorm" / session["id"]
        sarathi_dir.mkdir(parents=True, exist_ok=True)
        spec_path = sarathi_dir / "spec.md"
        content = session["spec_content"] or f"# {session['title']}\n"
        spec_path.write_text(content, encoding="utf-8")
        return str(spec_path)
    except Exception:
        return None


def _get_policy_pack(storage: Storage, workspace_id: str) -> dict[str, Any]:
    policy_dir = _find_policy_pack_dir(storage, workspace_id)
    if policy_dir is None:
        return {"files": [], "error": "No policy pack found for this workspace"}
    files = []
    for md_file in sorted(policy_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            content = ""
        files.append({"name": md_file.name, "content": content, "size": len(content)})
    return {"files": files}


def _put_policy_pack_file(
    storage: Storage,
    workspace_id: str,
    filename: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if not filename.endswith(".md"):
        raise ServiceError("invalid_request", "Filename must end in .md.", 400)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ServiceError("invalid_request", "Filename must not contain path traversal characters.", 400)
    policy_dir = _find_policy_pack_dir(storage, workspace_id)
    if policy_dir is None:
        raise ServiceError("not_found", "No policy pack found for this workspace.", 404)
    content = body.get("content")
    if not isinstance(content, str):
        raise ServiceError("invalid_request", "Field 'content' must be a string.", 400)
    target = policy_dir / filename
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ServiceError("internal_error", f"Failed to write policy file: {exc}", 500)
    return {"ok": True, "filename": filename}


def _sarathi_transition_message(subtask: dict[str, Any], new_status: str) -> str:
    title = subtask.get("title", "Unit")
    metadata = subtask.get("metadata", {})
    provider = (
        metadata.get("provider", "agent")
        if isinstance(metadata, dict)
        else "agent"
    )
    msgs = {
        "in_progress": f"Starting: {title}",
        "review": f"Unit complete: {title}. Ready for review.",
        "completed": f"Done: {title}.",
        "failed": f"Unit failed: {title}. Check dispatch log for details.",
    }
    return msgs.get(new_status, f"Unit {title} → {new_status}")


def _preview_repository_intake(path: str) -> dict[str, Any]:
    repo_path = Path(path).expanduser()
    exists = repo_path.exists()
    is_directory = repo_path.is_dir()
    is_git_repo = False
    branch = None
    remote_url = None
    changes: list[str] = []

    if is_directory:
        is_git_repo = _git_output(repo_path, "rev-parse", "--is-inside-work-tree") == "true"
        if is_git_repo:
            branch = _git_output(repo_path, "branch", "--show-current") or None
            remote_url = _git_output(repo_path, "config", "--get", "remote.origin.url") or None
            changes = _git_lines(repo_path, "status", "--short")
    inspection = _inspect_repository(repo_path) if is_directory else {}

    sarathi_initialized = (
        (repo_path / "policy-pack").exists()
        or (repo_path / ".sarathi").exists()
        or (repo_path / "learnings.md").exists()
    )

    warnings: list[str] = []
    if not exists:
        warnings.append("Repository path does not exist yet.")
    elif not is_directory:
        warnings.append("Repository path is not a directory.")
    elif changes:
        warnings.append("Repository has uncommitted or untracked changes.")
    if exists and is_directory and not sarathi_initialized:
        warnings.append("Sarathi policy pack is not initialized yet.")

    recommended_mode = "new_repo"
    if exists and is_directory:
        recommended_mode = "existing_repo" if is_git_repo else "directory"
    if sarathi_initialized:
        recommended_mode = "sarathi_enabled_repo"
    bootstrap = _repository_bootstrap_status(repo_path) if is_directory else _repository_bootstrap_status(None)

    return {
        "path": str(repo_path),
        "name": repo_path.name,
        "exists": exists,
        "is_directory": is_directory,
        "is_git_repo": is_git_repo,
        "branch": branch,
        "remote_url": remote_url,
        "dirty": bool(changes),
        "changes": changes,
        "inspection": inspection,
        "sarathi_initialized": sarathi_initialized,
        "recommended_mode": recommended_mode,
        "requires_interview": not exists or not is_git_repo,
        "warnings": warnings,
        "bootstrap": bootstrap,
        "would_create": bootstrap["missing_files"],
        "would_preserve": bootstrap["present_files"],
    }


def _initialize_workspace_repository(
    storage: Storage,
    repository: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Repository initialization must be explicitly approved before files are created.",
            409,
        )
    preview = _preview_repository_intake(repository["path"])
    interview = _optional_dict(body, "interview") or {}
    if preview["requires_interview"] and not interview:
        raise ServiceError(
            "interview_required",
            "New or non-Git repositories require interview answers before Sarathi initialization.",
            409,
        )

    repo_path = Path(repository["path"]).expanduser()
    if preview["recommended_mode"] == "new_repo":
        repo_path.mkdir(parents=True, exist_ok=True)
    elif not repo_path.exists() or not repo_path.is_dir():
        raise ServiceError("invalid_request", "Repository path must be an existing directory.", 400)

    mode = preview["recommended_mode"]
    bootstrap_result = _write_sarathi_repository_docs(repo_path, repository, preview, interview)
    initialization = {
        "status": "completed",
        "mode": mode,
        "created_files": bootstrap_result["created_files"],
        "preserved_files": bootstrap_result["preserved_files"],
        "bootstrap": preview["bootstrap"],
        "inspection": preview.get("inspection", {}),
        "interview": interview,
    }
    metadata = dict(repository["metadata"])
    metadata["sarathi_initialization"] = initialization
    updated_repository = storage.update_workspace_repository(repository["id"], metadata=metadata)
    storage.create_lifecycle_event(
        workspace_id=repository["workspace_id"],
        event_type="workspace.repository.initialized",
        payload={
            "object_id": repository["id"],
            "path": repository["path"],
            "mode": mode,
            "created_files": bootstrap_result["created_files"],
            "preserved_files": bootstrap_result["preserved_files"],
        },
    )
    return {"repository": updated_repository, "initialization": initialization}


def _write_sarathi_repository_docs(
    repo_path: Path,
    repository: dict[str, Any],
    preview: dict[str, Any],
    interview: Mapping[str, Any],
) -> dict[str, list[str]]:
    project_name = str(interview.get("project_name") or repository.get("name") or preview["name"])
    purpose = str(interview.get("purpose") or "Document this repository for Sarathi orchestration.")
    inspection = preview.get("inspection", {}) if isinstance(preview.get("inspection"), Mapping) else {}
    languages = inspection.get("languages") if isinstance(inspection.get("languages"), list) else []
    frameworks = inspection.get("frameworks") if isinstance(inspection.get("frameworks"), list) else []
    build_tools = inspection.get("build_tools") if isinstance(inspection.get("build_tools"), list) else []
    test_patterns = inspection.get("test_patterns") if isinstance(inspection.get("test_patterns"), list) else []
    primary_language = str(interview.get("primary_language") or (languages[0] if languages else "Unknown"))
    file_map = {
        "SARATHI.md": (
            f"# {project_name} Sarathi Context\n\n"
            f"Purpose: {purpose}\n\n"
            f"Primary language: {primary_language}\n\n"
            f"Recommended mode: {preview['recommended_mode']}\n\n"
            "Sarathi uses this file as the repository-level orientation point for agents.\n"
        ),
        "wiki/README.md": (
            f"# {project_name} Wiki\n\n"
            "## Overview\n"
            f"{purpose}\n\n"
            "## Repository Profile\n"
            f"- Languages: {', '.join(languages) or 'Unknown'}\n"
            f"- Frameworks: {', '.join(frameworks) or 'Unknown'}\n"
            f"- Build tools: {', '.join(build_tools) or 'Unknown'}\n"
            f"- Test patterns: {', '.join(test_patterns) or 'Unknown'}\n\n"
            "## Architecture Notes\n"
            "- Add module boundaries, runtime assumptions, and external dependencies here.\n"
        ),
        "wiki/architecture.md": (
            f"# {project_name} Architecture Notes\n\n"
            "- Capture service boundaries, major modules, and runtime dependencies.\n"
            "- Add diagrams or links to diagrams generated from Sarathi task evidence.\n"
        ),
        "wiki/development.md": (
            f"# {project_name} Development Workflow\n\n"
            "- Document local setup, build, test, and release flow.\n"
            "- Record task routing expectations for Codex, Claude, Copilot, or local providers.\n"
        ),
        "coding-standards.md": (
            "# Coding Standards\n\n"
            "- Keep changes scoped to the active Sarathi task.\n"
            "- Add or update tests with behavior changes.\n"
            "- Preserve existing user changes and avoid destructive git commands.\n"
            f"- Primary language focus: {primary_language}.\n"
        ),
        "guidelines.md": (
            "# Repository Guidelines\n\n"
            "- Preview repository mutations before applying them.\n"
            "- Link evidence, review, and handoff records to every completed task.\n"
            "- Ask for explicit approval before commit, PR, or generated file writes.\n"
            "- Treat workspace context, wiki, policy pack, and learnings as first-class artifacts.\n"
        ),
        "learnings.md": (
            "# Repository Learnings\n\n"
            "Accepted learnings from Sarathi runs should be appended here after review approval.\n"
        ),
    }
    file_map.update(_generated_policy_pack_files(repo_path, preview, interview))
    created: list[str] = []
    preserved: list[str] = []
    for relative_path, content in file_map.items():
        target = repo_path / relative_path
        if target.exists():
            preserved.append(relative_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(relative_path)
    return {"created_files": created, "preserved_files": preserved}


def _generated_policy_pack_files(
    repo_path: Path,
    preview: Mapping[str, Any],
    interview: Mapping[str, Any],
) -> dict[str, str]:
    inspection = preview.get("inspection") if isinstance(preview.get("inspection"), Mapping) else {}
    effective_inspection = dict(inspection) if inspection else {}
    if not effective_inspection:
        effective_inspection = _inspect_repository(repo_path)
    with tempfile.TemporaryDirectory(prefix="sarathi-bootstrap-") as tempdir:
        workflow = InitWorkflow(target_path=tempdir)
        generated_path = workflow.generate(effective_inspection, dict(interview))
        files: dict[str, str] = {}
        for source in sorted(generated_path.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(generated_path).as_posix()
            files[f"policy-pack/{relative}"] = source.read_text(encoding="utf-8")
        return files


def _inspect_repository(repo_path: Path) -> dict[str, Any]:
    if not repo_path.exists() or not repo_path.is_dir():
        return {}
    inspection = InitWorkflow(target_path=str(repo_path)).inspect()
    return inspection if isinstance(inspection, dict) and "error" not in inspection else {}


def _repository_bootstrap_status(repo_path: Path | None) -> dict[str, Any]:
    required_files = _required_repository_bootstrap_files()
    if repo_path is None:
        return {
            "required_files": required_files,
            "present_files": [],
            "missing_files": list(required_files),
            "status": "not_initialized",
        }
    present_files = [path for path in required_files if (repo_path / path).exists()]
    missing_files = [path for path in required_files if path not in present_files]
    if not present_files:
        status = "not_initialized"
    elif not missing_files:
        status = "complete"
    else:
        status = "partial"
    return {
        "required_files": required_files,
        "present_files": present_files,
        "missing_files": missing_files,
        "status": status,
    }


def _required_repository_bootstrap_files() -> list[str]:
    return [
        "SARATHI.md",
        "wiki/README.md",
        "wiki/architecture.md",
        "wiki/development.md",
        "coding-standards.md",
        "guidelines.md",
        "learnings.md",
        "policy-pack/commands.md",
        "policy-pack/complexity.md",
        "policy-pack/conventions.md",
        "policy-pack/escalation.md",
        "policy-pack/model-routing.md",
        "policy-pack/review.md",
        "policy-pack/skills.md",
        "policy-pack/task-tracking.md",
    ]


def _git_output(repo_path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_lines(repo_path: Path, *args: str) -> list[str]:
    output = _git_output(repo_path, *args)
    if not output:
        return []
    return output.splitlines()
