"""ServiceApp router and create_app factory."""

from __future__ import annotations

import hmac
import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

from src.init import bootstrap_workspace
from src.storage import Storage, connect, run_migrations

from .errors import (
    ServiceError,
    _correlation_id,
    _error,
    _first_query,
    _ok,
    _path_parts,
    _query,
)
from .events import format_sse_event, replay_events
from .static_files import resolve_static_file
from .usage_stats import build_usage_stats
from .intake import (
    _build_github_issue_reference,
    _derive_task_title,
    _emit_brainstorm_event,
    _get_policy_pack,
    _github_repository_metadata,
    _initialize_workspace_repository,
    _preview_repository_intake,
    _put_policy_pack_file,
    _task_context_project_id,
    _task_draft_metadata,
    _write_brainstorm_spec,
)
from .openapi import build_openapi_spec
from .policy_layers import (
    get_session_policy,
    get_workspace_policy,
    set_session_policy_overrides,
    set_workspace_policy_overrides,
)
from .preferences import (
    _effective_auto_approve_preference,
    _evaluate_threshold,
    _get_policy_pack_approval_defaults,
    _is_gate_denylisted,
    _merge_task_defaults,
    _normalize_auto_approve_preference,
    _normalize_brainstorm_metadata,
    _normalize_repository_action_preference,
    _normalize_reuse_preferences,
    _optional_dict,
    _optional_text,
    _required_text,
)
from .providers import (
    _claim_is_fresh,
    _dispatch_subtask,
    _handle_chat,
    _provider_health,
    _test_and_store_provider,
)
from .proposals import (
    _accept_proposal,
    _reject_proposal,
    _workspace_proposal_detail,
    _workspace_proposals,
)
from .knowledge import (
    _approve_dogfood_learning,
    _dogfood_acceptance,
    _save_workspace_skills,
    _save_workspace_wiki_page,
    _workspace_context_bundles,
    _workspace_knowledge_center,
    _workspace_skills,
    _workspace_wiki,
    _workspace_wiki_page,
)
from .review import (
    _create_task_handoff,
    _record_repository_action,
    _run_task_review,
)
from .auth import (
    auth_enabled as _auth_enabled,
    Principal,
    require_admin,
    resolve_principal,
)
from .sessions import (
    attach_via_share_token,
    create_task_session,
    fork_session,
    join_session,
    leave_session,
    post_session_message,
    update_task_session,
)
from .scheduling import (
    _create_graph_draft,
    _graph_for_task,
    _has_approved_gate,
    _maybe_auto_schedule_ready_subtasks,
    _schedule_ready_subtasks,
    _service_now,
    _transition_subtask,
)
from .views import (
    _latest_or_none,
    _task_dashboard,
    _task_studio_snapshot,
    _workspace_operational_views,
    _workspace_reuse_kit,
)


# Repository root: src/service/app.py -> src/service -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Default location of the built web bundle (Vite/SPA `dist` output).
DEFAULT_DIST_ROOT = _REPO_ROOT / "web" / "dist"


@dataclass(frozen=True)
class RawResponse:
    """A non-enveloped HTTP response (bypasses the ``{ok, data}`` JSON envelope).

    Used for responses that must be a specific content type at the top
    level — e.g. the OpenAPI document, the `/docs` HTML page, SSE streams,
    and static assets from the built web bundle.
    """

    status: int
    content_type: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


def _html_response(status: int, html: str) -> RawResponse:
    return RawResponse(status, "text/html; charset=utf-8", html.encode("utf-8"))


def _sse_response(status: int, body: str) -> RawResponse:
    return RawResponse(
        status,
        "text/event-stream",
        body.encode("utf-8"),
        headers={"cache-control": "no-cache"},
    )


_DOCS_HTML = """<!DOCTYPE html>
<html>
  <head>
    <title>Sarathi API Docs</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>body { margin: 0; padding: 0; }</style>
  </head>
  <body>
    <redoc spec-url="/openapi.json"></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
  </body>
</html>
"""


class ServiceApp:
    """Callable local request handler that does not require a socket server."""

    def __init__(
        self,
        db_path: str | Path,
        token: str | None = None,
        *,
        dist_root: str | Path | None = None,
        auth_enabled: bool | None = None,
    ):
        self.db_path = Path(db_path)
        self.token = token
        self.dist_root = Path(dist_root) if dist_root is not None else DEFAULT_DIST_ROOT
        self.auth_enabled = _auth_enabled() if auth_enabled is None else auth_enabled
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
    ) -> tuple[int, dict[str, Any]] | RawResponse:
        return self.handle(method, path, body=body, headers=headers)

    # First path segments that are served by the JSON API router (`_route`).
    # A GET to any other top-level path falls back to the static web bundle.
    _API_PREFIXES = {
        "health",
        "workspaces",
        "tasks",
        "subtasks",
        "providers",
        "chat",
        "events",
        "brainstorm",
        "sessions",
        "users",
    }

    def handle(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        skip_auth: bool = False,
    ) -> tuple[int, dict[str, Any]] | RawResponse:
        correlation_id = _correlation_id(headers)
        try:
            method = method.upper()
            raw_parts = _path_parts(path)
            is_api_request = bool(raw_parts) and raw_parts[0] == "api"

            # Public, unauthenticated routes for the same-origin "installable
            # app" path: a browser navigating directly to this service (e.g.
            # http://127.0.0.1:8765/) has no `Authorization` header yet, so
            # the SPA shell, its static assets, `/docs`, `/openapi.json`,
            # `/health`, and the runtime-config script must be reachable
            # without a bearer token. Anything under `/api/...` (the JSON
            # API) is never treated as public here and always requires
            # `_authorize` below — this check runs only for non-`/api`
            # GET requests.
            if method == "GET" and not is_api_request:
                public_response = self._public_get_response(raw_parts, correlation_id)
                if public_response is not None:
                    return public_response

            principal = None if skip_auth else self._authorize(headers)
            parts = raw_parts[1:] if is_api_request else raw_parts
            # The OpenAPI document (and its docs page) are returned as-is,
            # without the success envelope, since they must be valid
            # top-level OpenAPI/HTML documents for tooling that fetches them
            # directly (e.g. Redoc, openapi-spec-validator).
            if method == "GET" and parts == ["openapi.json"]:
                return 200, build_openapi_spec()
            if method == "GET" and parts == ["docs"]:
                return _html_response(200, _DOCS_HTML)
            # SSE replay stream for a task's lifecycle events. Like
            # /openapi.json and /docs, this is a raw (non-enveloped)
            # response because its top-level content type must be
            # text/event-stream.
            if (
                method == "GET"
                and len(parts) == 6
                and parts[0] == "workspaces"
                and parts[2] == "tasks"
                and parts[4] == "events"
                and parts[5] == "stream"
            ):
                return self._handle_event_stream(parts[1], parts[3], headers)
            if method == "GET" and (not parts or parts[0] not in self._API_PREFIXES):
                # No matching API route for this GET — fall back to serving
                # the built web bundle (the SPA), if present.
                static_response = self._serve_static(parts)
                if static_response is not None:
                    return static_response
            status, data = self._route(
                method,
                parts,
                _query(path),
                body or {},
                principal=principal,
            )
            return status, _ok(data, correlation_id)
        except ServiceError as error:
            return error.status, _error(error, correlation_id)

    def _public_get_response(
        self, raw_parts: list[str], correlation_id: str
    ) -> tuple[int, dict[str, Any]] | RawResponse | None:
        """Handle public (no bearer token required) GET requests.

        Only called for GET requests whose path does not start with
        `/api/`. Covers the same-origin SPA shell and its static assets, the
        SPA history-mode fallback, `/docs`, `/openapi.json`, `/health`, and
        `/sarathi-runtime.js`. Returns ``None`` if `raw_parts` is an
        unauthenticated request for an API-shaped path (e.g. a bare
        `/workspaces` without the `/api` prefix), which falls through to the
        normal authorized routing below.
        """
        if raw_parts == ["health"]:
            return 200, _ok({"status": "ok"}, correlation_id)
        if raw_parts == ["openapi.json"]:
            return 200, build_openapi_spec()
        if raw_parts == ["docs"]:
            return _html_response(200, _DOCS_HTML)
        if raw_parts == ["sarathi-runtime.js"]:
            return self._serve_runtime_config()
        if not raw_parts or raw_parts[0] not in self._API_PREFIXES:
            # The SPA shell (`/`), its static assets, and extensionless SPA
            # fallback routes (e.g. `/tasks/123`) all live here.
            return self._serve_static(raw_parts)
        return None

    def _serve_runtime_config(self) -> RawResponse:
        """Serve `/sarathi-runtime.js`: the same-origin SPA's bearer token.

        Trust model: like the discovery file written by `desktop.py`
        (`~/.sarathi/service.json`, mode 0600) and the runtime-config script
        it generates for the split-origin desktop UI, this endpoint is only
        safe because the service binds to 127.0.0.1/localhost — any local
        process that can reach this port can already read those files or
        connect directly. This route is the single-origin analogue: it hands
        the same bearer token to the SPA when it is served from this same
        origin (so `baseUrl` is `""`, i.e. same-origin requests).
        """
        payload = {"baseUrl": "", "token": self.token or ""}
        body = (
            "window.__SARATHI_RUNTIME_CONFIG__ = "
            f"{json.dumps(payload, sort_keys=True)};\n"
        )
        return RawResponse(200, "application/javascript", body.encode("utf-8"))

    def _handle_event_stream(
        self,
        workspace_id: str,
        task_id: str,
        headers: Mapping[str, str] | None,
    ) -> RawResponse:
        """Replay a task's lifecycle events as a Server-Sent Events stream.

        MVP behaviour: this writes the full (or `Last-Event-ID`-bounded)
        backlog of events as SSE frames and then closes the stream with a
        200. Continuous tailing of newly-created events is a follow-up (the
        `/api/events/stream` websocket-style polling endpoint in
        `http.py` already provides a live snapshot stream in the meantime).
        """
        conn, storage = self._storage()
        if storage.get_workspace(workspace_id) is None:
            raise ServiceError("not_found", "Workspace not found.", 404)
        if storage.get_task(task_id) is None:
            raise ServiceError("not_found", "Task not found.", 404)

        after_id = None
        if headers:
            for key, value in headers.items():
                if key.lower() == "last-event-id" and value:
                    after_id = value
                    break

        events = replay_events(conn, workspace_id, task_id, after_id=after_id)
        body = "".join(
            format_sse_event(event["id"], event["event_type"], event["payload"])
            for event in events
        )
        return _sse_response(200, body)

    def _serve_static(self, parts: list[str]) -> RawResponse | None:
        """Serve a file from the built web bundle (`self.dist_root`).

        Returns ``None`` when there is no asset to serve (caller should fall
        through to the normal API routing/404 behaviour) or a `RawResponse`
        (200 for a resolved asset/SPA fallback, 404 for a missing asset).
        """
        url_path = "/" + "/".join(parts)
        result = resolve_static_file(self.dist_root, url_path)
        if result is None:
            return RawResponse(404, "text/plain; charset=utf-8", b"Not Found")
        return RawResponse(result.status, result.content_type, result.body)

    def _route(
        self,
        method: str,
        parts: list[str],
        query: Mapping[str, list[str]],
        body: Mapping[str, Any],
        *,
        principal: Principal | None = None,
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
            root_path = _required_text(body, "root_path")
            metadata = _optional_dict(body, "metadata") or {}
            bootstrap = bootstrap_workspace(root_path)
            metadata = {
                **metadata,
                "bootstrap": bootstrap,
            }
            workspace = storage.create_workspace(
                name=_required_text(body, "name"),
                root_path=bootstrap["root_path"],
                metadata=metadata,
            )
            storage.create_lifecycle_event(
                workspace_id=workspace["id"],
                event_type="workspace.created",
                payload={
                    "object_id": workspace["id"],
                    "bootstrap": {
                        "policy_pack": bootstrap["policy_pack"]["status"],
                        "wiki": bootstrap["wiki"]["status"],
                    },
                },
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
            changed_keys: list[str] = []

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
                changed_keys.append("repository_action_preference")

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
                changed_keys.append("auto_approve_preference")

            if "provider_priority" in raw_metadata:
                priority = raw_metadata["provider_priority"]
                if not isinstance(priority, list) or not priority:
                    raise ServiceError(
                        "invalid_request",
                        "Field 'provider_priority' must be a non-empty list of provider identifiers.",
                        400,
                    )
                if not all(isinstance(p, str) for p in priority):
                    raise ServiceError(
                        "invalid_request",
                        "Field 'provider_priority' must contain only string values.",
                        400,
                    )
                next_metadata["provider_priority"] = list(priority)
                changed_keys.append("provider_priority")

            if "reuse_preferences" in raw_metadata:
                preferences = _normalize_reuse_preferences(raw_metadata["reuse_preferences"])
                if preferences is None:
                    raise ServiceError(
                        "invalid_request",
                        "Unsupported reuse preferences.",
                        400,
                    )
                next_metadata["reuse_preferences"] = preferences
                changed_keys.append("reuse_preferences")

            if "ncp_enabled" in raw_metadata:
                if not isinstance(raw_metadata["ncp_enabled"], bool):
                    raise ServiceError(
                        "invalid_request",
                        "Field 'ncp_enabled' must be a boolean.",
                        400,
                    )
                next_metadata["ncp_enabled"] = raw_metadata["ncp_enabled"]
                changed_keys.append("ncp_enabled")

            if not changed_keys:
                raise ServiceError(
                    "invalid_request",
                    "At least one update field is required: 'repository_action_preference', 'auto_approve_preference', 'provider_priority', 'reuse_preferences', or 'ncp_enabled'.",
                    400,
                )

            updated_workspace = storage.update_workspace(parts[1], metadata=next_metadata)

            if changed_keys:
                governance_keys = [
                    key
                    for key in changed_keys
                    if key in {"repository_action_preference", "auto_approve_preference", "provider_priority"}
                ]
                reuse_keys = [key for key in changed_keys if key == "reuse_preferences"]
                if governance_keys:
                    storage.create_lifecycle_event(
                        workspace_id=parts[1],
                        event_type="workspace.governance_updated",
                        payload={
                            "object_id": parts[1],
                            "changed_keys": governance_keys,
                            "snapshot": {key: next_metadata.get(key) for key in governance_keys},
                        },
                    )
                if reuse_keys:
                    storage.create_lifecycle_event(
                        workspace_id=parts[1],
                        event_type="workspace.reuse_updated",
                        payload={
                            "object_id": parts[1],
                            "changed_keys": reuse_keys,
                            "snapshot": {key: next_metadata.get(key) for key in reuse_keys},
                        },
                    )

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
            method == "GET"
            and len(parts) == 4
            and parts[0] == "workspaces"
            and parts[2] == "ncp"
            and parts[3] == "status"
        ):
            workspace = storage.get_workspace(parts[1])
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            import shutil
            ncp_available = shutil.which("ncp") is not None
            return 200, {"ncp_available": ncp_available}

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
            and parts[2] == "usage-stats"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, build_usage_stats(storage, workspace_id)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "reuse-kit"
        ):
            workspace_id = parts[1]
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_reuse_kit(storage, workspace_id)

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
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "knowledge-center"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_knowledge_center(storage, workspace)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "wiki"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_wiki(workspace)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "wiki"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _save_workspace_wiki_page(workspace, body)

        if (
            method == "GET"
            and len(parts) == 4
            and parts[0] == "workspaces"
            and parts[2] == "wiki"
            and parts[3]
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            wiki_page = unquote(parts[3])
            return 200, _workspace_wiki_page(workspace, wiki_page)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "skills"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_skills(storage, workspace)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "skills"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _save_workspace_skills(storage, workspace, body)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "context-bundles"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_context_bundles(storage, workspace)

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "workspaces"
            and parts[2] == "proposals"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            return 200, _workspace_proposals(storage, workspace)

        if (
            method == "GET"
            and len(parts) == 4
            and parts[0] == "workspaces"
            and parts[2] == "proposals"
            and parts[3]
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            proposal_id = parts[3]
            return 200, _workspace_proposal_detail(storage, workspace, proposal_id)

        if (
            method == "POST"
            and len(parts) == 5
            and parts[0] == "workspaces"
            and parts[2] == "proposals"
            and parts[4] == "accept"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            proposal_id = parts[3]
            return 200, _accept_proposal(storage, workspace, proposal_id)

        if (
            method == "POST"
            and len(parts) == 5
            and parts[0] == "workspaces"
            and parts[2] == "proposals"
            and parts[4] == "reject"
        ):
            workspace_id = parts[1]
            workspace = storage.get_workspace(workspace_id)
            if workspace is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            proposal_id = parts[3]
            reason = body.get("reason") if body else None
            return 200, _reject_proposal(storage, workspace, proposal_id, reason)

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
            task_metadata = _merge_task_defaults(_optional_dict(body, "metadata"))
            task = storage.create_task(
                workspace_id=workspace_id,
                title=_required_text(body, "title"),
                description=_optional_text(body, "description"),
                metadata=task_metadata,
                project_id=task_metadata.get("project_id"),
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
                project_id=metadata.get("project_id"),
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
                project_id=task_metadata.get("project_id"),
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
                project_id=checkpoint["project_id"],
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
            requester = _optional_text(body, "worker_id")
            claimed_by = subtask.get("claimed_by")
            if (
                claimed_by
                and claimed_by != requester
                and _claim_is_fresh(subtask)
            ):
                raise ServiceError(
                    "conflict",
                    f"Subtask is claimed by worker '{claimed_by}'.",
                    409,
                )
            return 201, _dispatch_subtask(storage, subtask, body)

        # ── Sessions (sharing & co-drive) ────────────────────────────────────
        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "sessions"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            session = create_task_session(
                storage,
                task,
                owner=_optional_text(body, "owner") or "local",
                visibility=_optional_text(body, "visibility") or "private",
            )
            return 201, {"session": session}

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "tasks"
            and parts[2] == "sessions"
        ):
            task = storage.get_task(parts[1])
            if task is None:
                raise ServiceError("not_found", "Task not found.", 404)
            return 200, {"sessions": storage.list_sessions_for_task(parts[1])}

        if method == "POST" and parts == ["sessions", "attach"]:
            result = attach_via_share_token(
                storage,
                share_token=_required_text(body, "share_token"),
                user=_required_text(body, "user"),
                role=_optional_text(body, "role") or "observer",
            )
            return 201, result

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "participants"
        ):
            session = storage.get_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Session not found.", 404)
            return 200, {"participants": storage.list_session_participants(parts[1])}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "participants"
        ):
            session = storage.get_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Session not found.", 404)
            participant = join_session(
                storage,
                parts[1],
                user=_required_text(body, "user"),
                role=_optional_text(body, "role") or "observer",
            )
            return 201, {"participant": participant}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "leave"
        ):
            participant = leave_session(
                storage,
                parts[1],
                user=_required_text(body, "user"),
            )
            return 200, {"participant": participant}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "fork"
        ):
            return 201, fork_session(
                storage,
                parts[1],
                owner=_optional_text(body, "owner"),
            )

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "messages"
        ):
            session = storage.get_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Session not found.", 404)
            return 200, {"messages": storage.list_messages(session_id=parts[1])}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] == "messages"
        ):
            session = storage.get_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Session not found.", 404)
            # With auth on, the actor is the authenticated principal, not a
            # client-supplied field — so observers cannot post by spoofing a
            # driver's user id in the body.
            actor = (
                principal.username
                if principal is not None and not principal.is_admin
                else _required_text(body, "user")
            )
            message = post_session_message(
                storage,
                session,
                user=actor,
                content=_required_text(body, "content"),
                role=_optional_text(body, "role"),
            )
            return 201, {"message": message}

        if method == "GET" and len(parts) == 2 and parts[0] == "sessions":
            session = storage.get_session(parts[1])
            if session is None:
                raise ServiceError("not_found", "Session not found.", 404)
            return 200, {
                "session": session,
                "participants": storage.list_session_participants(parts[1]),
            }

        if method == "PATCH" and len(parts) == 2 and parts[0] == "sessions":
            session = update_task_session(
                storage,
                parts[1],
                visibility=_optional_text(body, "visibility"),
                status=_optional_text(body, "status"),
            )
            return 200, {"session": session}

        if method == "GET" and len(parts) == 3 and parts[0] == "sessions" and parts[2] == "policy":
            return 200, get_session_policy(storage, parts[1])

        if method == "PATCH" and len(parts) == 3 and parts[0] == "sessions" and parts[2] == "policy":
            return 200, set_session_policy_overrides(storage, parts[1], body.get("overrides"))

        # ── Users (opt-in multi-user auth: admin-only provisioning) ──────────
        if method == "POST" and parts == ["users"]:
            require_admin(principal)
            username = _required_text(body, "username")
            if storage.get_user_by_username(username) is not None:
                raise ServiceError("conflict", "Username already exists.", 409)
            user = storage.create_user(
                username=username,
                display_name=_optional_text(body, "display_name"),
                metadata=_optional_dict(body, "metadata"),
            )
            return 201, {"user": user}

        if method == "GET" and parts == ["users"]:
            require_admin(principal)
            return 200, {"users": storage.list_users()}

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

        if method == "GET" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "policy":
            return 200, get_workspace_policy(storage, parts[1])

        if method == "PATCH" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "policy":
            return 200, set_workspace_policy_overrides(storage, parts[1], body.get("overrides"))

        # ── Brainstorm sessions ──────────────────────────────────────────────
        if method == "POST" and len(parts) == 2 and parts[0] == "brainstorm" and parts[1] == "sessions":
            workspace_id = _required_text(body, "workspace_id")
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            title = _required_text(body, "title")
            project_id = _optional_text(body, "project_id")
            provider = _optional_text(body, "provider")
            output_format = _optional_text(body, "output_format") or "markdown"
            metadata = _normalize_brainstorm_metadata(_optional_dict(body, "metadata"))
            session = storage.create_brainstorm_session(
                workspace_id=workspace_id,
                title=title,
                project_id=project_id,
                provider=provider,
                output_format=output_format,
                metadata=metadata,
            )
            _emit_brainstorm_event(storage, "brainstorm.session_started", {
                "session_id": session["id"], "workspace_id": workspace_id, "title": title,
                "metadata": metadata,
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
            session_metadata = _normalize_brainstorm_metadata(session.get("metadata")) or {}
            task_metadata = {
                "source": "brainstorm",
                "brainstorm_session_id": session["id"],
                "project_id": session["project_id"],
            }
            if session_metadata:
                task_metadata["reuse"] = session_metadata
            task = storage.create_task(
                workspace_id=session["workspace_id"],
                title=session["title"],
                description=spec_content,
                metadata=task_metadata,
                project_id=task_metadata.get("project_id"),
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

    def _authorize(self, headers: Mapping[str, str] | None) -> Principal | None:
        # Opt-in multi-user mode: the bearer must be the admin token or an
        # active user token; the resolved principal is returned for routing.
        if self.auth_enabled:
            _conn, storage = self._storage()
            return resolve_principal(
                storage, headers, admin_token=self.token, enabled=True
            )
        # Default single-user local mode: shared-token check, no principal.
        if self.token is None:
            return None
        expected = f"Bearer {self.token}"
        for key, value in (headers or {}).items():
            if key.lower() == "authorization" and hmac.compare_digest(
                str(value).encode(), expected.encode()
            ):
                return None
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
        candidate = _first_query(query, "token")
        if candidate is not None and hmac.compare_digest(
            str(candidate).encode(), str(self.token).encode()
        ):
            return
        raise ServiceError("unauthorized", "Missing or invalid authorization token.", 401)


def create_app(
    db_path: str | Path,
    token: str | None = None,
    *,
    dist_root: str | Path | None = None,
    auth_enabled: bool | None = None,
) -> ServiceApp:
    return ServiceApp(
        db_path, token=token, dist_root=dist_root, auth_enabled=auth_enabled
    )
