"""Service client for Sarathi — discovers the local HTTP service and routes
CLI/TUI operations through HTTP when available, falling back transparently
to in-process engine behavior."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ServiceRequestError(RuntimeError):
    """A service HTTP request failed, with the HTTP status when known.

    Lets callers branch on the actual status code (e.g. treat 404 as "not
    found" for a strict lookup) instead of pattern-matching the human-
    readable message text.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _service_discovery_path() -> Path:
    return Path.home() / ".sarathi" / "service.json"


def _read_service_discovery() -> dict[str, Any] | None:
    discovery_path = _service_discovery_path()
    if not discovery_path.exists():
        return None
    try:
        payload = json.loads(discovery_path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _auth_token(info: dict[str, Any] | None) -> str | None:
    if not isinstance(info, dict):
        return None
    auth = info.get("auth")
    if not isinstance(auth, dict) or auth.get("type") != "bearer":
        return None
    token = auth.get("token")
    return token if isinstance(token, str) and token else None


def _service_get(service_url: str, path: str, *, token: str | None = None) -> Any:
    request = urllib.request.Request(f"{service_url.rstrip('/')}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ServiceRequestError(
            f"Service request failed (HTTP {error.code}).", status_code=error.code
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ServiceRequestError(f"Service request failed: {error}") from error


def _service_post(
    service_url: str,
    path: str,
    body: dict[str, Any],
    *,
    token: str | None = None,
) -> Any:
    request = urllib.request.Request(
        f"{service_url.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        message = None
        try:
            err_payload = json.loads(error.read().decode("utf-8"))
            if isinstance(err_payload, dict):
                err = err_payload.get("error") or {}
                if isinstance(err, dict):
                    message = err.get("message")
        except Exception:
            message = None
        raise ServiceRequestError(
            str(message or f"Service request failed (HTTP {error.code})."), status_code=error.code
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ServiceRequestError(f"Service request failed: {error}") from error


def _unwrap(payload: Any) -> Any:
    """Unwrap the standard ok/data envelope, raising on errors."""
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected service response.")
    if not payload.get("ok"):
        err = payload.get("error") or {}
        raise RuntimeError(str(err.get("message") or "Service request failed."))
    return payload.get("data")


class ServiceClient:
    """Client for the Sarathi HTTP service.

    Discovers the service URL and auth from ``~/.sarathi/service.json``
    and verifies reachability on construction.  All public methods that
    make HTTP calls raise ``RuntimeError`` on failure; callers handle
    the exception to fall back to local persistence.
    """

    def __init__(self, info: dict[str, Any] | None = None):
        self._info = info or _read_service_discovery()
        self._url: str | None = (
            self._info.get("url") if isinstance(self._info, dict) else None
        )
        self._token: str | None = _auth_token(self._info)

    @property
    def available(self) -> bool:
        return self._url is not None

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def workspace_count(self) -> int | None:
        try:
            return len(self.list_workspaces())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        return _unwrap(_service_get(self._url, path, token=self._token))

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        return _unwrap(_service_post(self._url, path, body, token=self._token))

    # ------------------------------------------------------------------
    # Workspace discovery
    # ------------------------------------------------------------------

    def list_workspaces(self) -> list[dict[str, Any]]:
        data = self._get("/api/workspaces")
        return data.get("workspaces") or []

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        try:
            return self._get(f"/api/workspaces/{workspace_id}")
        except RuntimeError:
            return None

    def select_workspace(
        self,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any] | None:
        """Select a workspace by explicit id/name, cwd root_path match,
        or the single workspace when none other is given.

        Returns ``None`` when the selection is ambiguous or no workspace
        exists — callers fall back to local persistence.
        """
        workspaces = self.list_workspaces()
        if not workspaces:
            return None

        # Explicit id
        if workspace_id:
            for ws in workspaces:
                if ws.get("id") == workspace_id:
                    return ws
            return None

        # Explicit name
        if workspace_name:
            for ws in workspaces:
                if ws.get("name") == workspace_name:
                    return ws
            return None

        # Match by cwd root_path
        if cwd:
            cwd_resolved = os.path.abspath(cwd)
            for ws in workspaces:
                ws_path = ws.get("root_path") or ws.get("path") or ""
                if ws_path:
                    ws_resolved = os.path.abspath(os.path.expanduser(ws_path))
                    if os.path.commonpath([cwd_resolved, ws_resolved]) == ws_resolved:
                        return ws

        # Single workspace — use it
        if len(workspaces) == 1:
            return workspaces[0]

        return None

    # ------------------------------------------------------------------
    # Provider discovery and chat
    # ------------------------------------------------------------------

    def list_providers(self, workspace_id: str) -> list[dict[str, Any]]:
        encoded_workspace = urllib.parse.quote(workspace_id, safe="")
        data = self._get(f"/api/providers?workspace_id={encoded_workspace}")
        return data.get("providers") or []

    def test_provider(
        self,
        workspace_id: str,
        provider_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_workspace = urllib.parse.quote(workspace_id, safe="")
        encoded_provider = urllib.parse.quote(provider_id, safe="")
        data = self._post(
            f"/api/workspaces/{encoded_workspace}/providers/{encoded_provider}/test",
            dict(config or {}),
        )
        provider = data.get("provider") if isinstance(data, dict) else None
        if not isinstance(provider, dict):
            raise RuntimeError("Unexpected provider response from service.")
        return provider

    def chat(
        self,
        workspace_id: str,
        message: str,
        *,
        provider: str | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message": message,
            "workspace_id": workspace_id,
        }
        if provider:
            body["provider"] = provider
        if history is not None:
            flattened_history: list[dict[str, str]] = []
            for user, assistant in history:
                flattened_history.extend(
                    [
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": assistant},
                    ]
                )
            body["history"] = flattened_history
        data = self._post("/api/chat", body)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected chat response from service.")
        return data

    # ------------------------------------------------------------------
    # Task operations
    # ------------------------------------------------------------------

    def create_task_draft(
        self,
        workspace_id: str,
        prompt: str,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a service task draft (PRD/AC shell).

        Returns ``{"task": ..., "approval_gate": ..., "messages": [...]}``.
        """
        body: dict[str, Any] = {"prompt": prompt}
        if title:
            body["title"] = title
        if context:
            body["context"] = context
        return self._post(f"/api/workspaces/{workspace_id}/task-drafts", body)

    def list_tasks(self, workspace_id: str) -> list[dict[str, Any]]:
        data = self._get(f"/api/workspaces/{workspace_id}/tasks")
        return data.get("tasks") or []

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        try:
            data = self._get(f"/api/tasks/{task_id}")
            if not isinstance(data, dict):
                return None
            task = data.get("task")
            return task if isinstance(task, dict) else (data if data else None)
        except RuntimeError:
            return None

    def get_task_strict(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a task for mutation; only a genuine 404 returns ``None``."""
        try:
            data = self._get(f"/api/tasks/{urllib.parse.quote(task_id, safe='')}")
        except ServiceRequestError as error:
            if error.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        task = data.get("task")
        return task if isinstance(task, dict) else (data if data else None)

    def get_task_raw(self, task_id: str) -> dict[str, Any] | None:
        try:
            return self._get(f"/api/tasks/{task_id}")
        except RuntimeError:
            return None

    def get_messages(self, task_id: str) -> list[dict[str, Any]]:
        try:
            data = self._get(f"/api/tasks/{task_id}/messages")
            return data.get("messages") or []
        except RuntimeError:
            return []

    def get_approvals(self, task_id: str) -> list[dict[str, Any]]:
        try:
            data = self._get(f"/api/tasks/{task_id}/approvals")
            return data.get("approval_gates") or []
        except RuntimeError:
            return []

    def get_events(self, task_id: str) -> list[dict[str, Any]]:
        try:
            data = self._get(f"/api/events?task_id={urllib.parse.quote(task_id)}")
            return data.get("events") or []
        except RuntimeError:
            return []

    def resume_task(self, task_id: str) -> dict[str, Any]:
        """Resume a service-managed task through the service scheduler."""
        data = self._post(f"/api/tasks/{urllib.parse.quote(task_id, safe='')}/resume", {})
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected resume response from service.")
        return data

    def approve_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        approved_by: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve the current pending gate for a service-managed task."""
        task = self.get_task(task_id)
        metadata = task.get("metadata") if isinstance(task, dict) else None
        if isinstance(metadata, dict) and metadata.get("execution_mode") == "full_engine":
            name = name or "Engine approval"
        if name is None:
            current: dict[str, dict[str, Any]] = {}
            for gate in reversed(self.get_approvals(task_id)):
                gate_name = gate.get("name")
                if isinstance(gate_name, str) and gate_name:
                    # Approval rows are append-only history. The newest row
                    # for a gate name is authoritative; an older pending row
                    # must not be approved again after a newer decision.
                    current.setdefault(gate_name, gate)
            pending = [gate for gate in current.values() if gate.get("status") == "pending"]
            if not pending:
                raise RuntimeError("Service task has no pending approval gate.")
            name = str(pending[-1].get("name") or "")
        decision_metadata: dict[str, Any] = {}
        if approved_by:
            decision_metadata["approved_by"] = approved_by
        if note:
            decision_metadata["note"] = note
        path = f"/api/tasks/{urllib.parse.quote(task_id, safe='')}/approve"
        data = self._post(path, {"name": name, "status": "approved", "metadata": decision_metadata})
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected approval response from service.")
        return data

    def find_task_workspace(self, task_id: str) -> str | None:
        """Determine which workspace a task lives in by fetching it."""
        task = self.get_task(task_id)
        if isinstance(task, dict):
            return task.get("workspace_id")
        return None


# ------------------------------------------------------------------
# Module-level helpers: one-shot "try service, else None"
# ------------------------------------------------------------------

def _try_service() -> ServiceClient | None:
    """Return a ``ServiceClient`` if the local service is reachable,
    ``None`` otherwise."""
    try:
        client = ServiceClient()
        if client.available:
            client.list_workspaces()
            return client
    except Exception:
        pass
    return None


def _service_task_summary(task: dict[str, Any]) -> dict[str, Any]:
    """Convert a service task dict to the same shape ``task_summaries``
    returns for local tasks."""
    metadata = task.get("metadata") or {}
    return {
        "task_id": task.get("id", ""),
        "description": task.get("title") or task.get("description", ""),
        "complexity": metadata.get("complexity", ""),
        "current_phase": task.get("status", "prd_pending"),
        "phases": 0,
        "last_phase": "",
        "last_outcome": "",
        "last_updated": task.get("updated_at") or task.get("created_at", ""),
    }
