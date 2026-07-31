"""OpenAPI 3.1 contract generation for the Sarathi local HTTP service.

This module describes the routes implemented by ``ServiceApp._route`` in
``src/service/app.py`` as a small internal registry, and turns that registry
into a published OpenAPI 3.1 document via :func:`build_openapi_spec`.

The registry is intentionally lightweight: each entry captures the HTTP
method, a path template (using ``{param}`` placeholders), a short summary,
and minimal request/response JSON schema fragments. It is meant to document
the *shape* of the API for tooling and humans, not to be a fully exhaustive
schema of every field returned by the service.

Run this module directly to (re)write the committed snapshot at
``docs/openapi.json``::

    python3 -m src.service.openapi
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

API_TITLE = "Sarathi Service API"
DEFAULT_API_VERSION = "0.2.0"


def _api_version() -> str:
    """Best-effort read of the project version from pyproject.toml."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_API_VERSION
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version"):
            _, _, value = stripped.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    return DEFAULT_API_VERSION


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

#: Generic JSON object schema used as a placeholder for loosely-typed
#: request/response payloads (e.g. workspace/task records, metadata blobs).
OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}

#: Envelope wrapping every successful response, per ``_ok`` in errors.py.
SUCCESS_ENVELOPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "enum": [True]},
        "data": OBJECT_SCHEMA,
        "correlation_id": {"type": "string"},
    },
    "required": ["ok", "data", "correlation_id"],
}

#: Envelope wrapping every error response, per ``_error`` in errors.py.
ERROR_ENVELOPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "enum": [False]},
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "status": {"type": "integer"},
            },
            "required": ["code", "message", "status"],
        },
        "correlation_id": {"type": "string"},
    },
    "required": ["ok", "error", "correlation_id"],
}

#: Reusable path parameter definitions, keyed by name.
_PATH_PARAMS: dict[str, dict[str, Any]] = {
    "id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Workspace identifier.",
    },
    "workspace_id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Workspace identifier.",
    },
    "task_id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Task identifier.",
    },
    "stream_task_id": {
        "name": "taskId",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Task identifier.",
    },
    "subtask_id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Subtask identifier.",
    },
    "session_id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Brainstorm session identifier.",
    },
    "co_drive_session_id": {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Co-drive session identifier.",
    },
    "proposal_id": {
        "name": "proposal_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Proposal identifier.",
    },
    "page": {
        "name": "page",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Wiki page slug (URL-encoded).",
    },
    "filename": {
        "name": "filename",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Policy pack filename.",
    },
    "provider": {
        "name": "provider",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Provider identifier.",
    },
    "repository_id": {
        "name": "repository_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Workspace repository identifier.",
    },
}


def _responses(
    success_status: str,
    success_description: str,
    *,
    data_schema: dict[str, Any] | None = None,
    not_found: bool = False,
    raw_content_type: str | None = None,
    raw_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a responses object for a route.

    ``data_schema``, if given, replaces the generic ``data`` object schema in
    the success envelope so callers can describe a tighter response shape.

    ``raw_content_type``, if given, describes a non-enveloped (raw) success
    response of that content type instead of the usual ``{ok, data,
    correlation_id}`` JSON envelope — e.g. ``text/event-stream`` for SSE
    routes. ``raw_schema`` optionally describes the body for that content
    type (defaults to a plain string).
    """

    if raw_content_type is not None:
        responses: dict[str, Any] = {
            success_status: {
                "description": success_description,
                "content": {
                    raw_content_type: {"schema": raw_schema or {"type": "string"}}
                },
            }
        }
    else:
        envelope = SUCCESS_ENVELOPE
        if data_schema is not None:
            envelope = {
                **SUCCESS_ENVELOPE,
                "properties": {**SUCCESS_ENVELOPE["properties"], "data": data_schema},
            }

        responses = {
            success_status: {
                "description": success_description,
                "content": {"application/json": {"schema": envelope}},
            }
        }
    if not_found:
        responses["404"] = {
            "description": "Resource not found.",
            "content": {"application/json": {"schema": ERROR_ENVELOPE}},
        }
    responses["default"] = {
        "description": "Unexpected error.",
        "content": {"application/json": {"schema": ERROR_ENVELOPE}},
    }
    return responses


# ---------------------------------------------------------------------------
# Route registry
#
# Each entry mirrors a branch of ServiceApp._route in src/service/app.py.
# Fields:
#   method      - HTTP method
#   path        - path template using {param} placeholders
#   summary     - short human-readable summary
#   params      - list of keys into _PATH_PARAMS for path parameters
#   request     - optional JSON schema for the request body (POST/PATCH/PUT)
#   success     - (status_code, description) for the happy-path response
#   data_schema - optional schema for the `data` field of the envelope
#   not_found   - whether a 404 response should be documented
#   tags        - OpenAPI tags for grouping
# ---------------------------------------------------------------------------

ROUTES: list[dict[str, Any]] = [
    # ── Health ────────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/health",
        "summary": "Service health check.",
        "tags": ["meta"],
        "success": ("200", "Service is healthy."),
        "data_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
        },
    },
    # ── Workspaces ────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces",
        "summary": "List workspaces.",
        "tags": ["workspaces"],
        "success": ("200", "List of workspaces."),
        "data_schema": {
            "type": "object",
            "properties": {"workspaces": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["workspaces"],
        },
    },
    {
        "method": "POST",
        "path": "/workspaces",
        "summary": "Create a workspace.",
        "tags": ["workspaces"],
        "request": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "root_path": {"type": "string"},
                "metadata": OBJECT_SCHEMA,
            },
            "required": ["name", "root_path"],
        },
        "success": ("201", "Workspace created."),
        "data_schema": {
            "type": "object",
            "properties": {"workspace": OBJECT_SCHEMA},
            "required": ["workspace"],
        },
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}",
        "summary": "Get a workspace by ID.",
        "tags": ["workspaces"],
        "params": ["id"],
        "success": ("200", "Workspace details."),
        "data_schema": {
            "type": "object",
            "properties": {"workspace": OBJECT_SCHEMA},
            "required": ["workspace"],
        },
        "not_found": True,
    },
    {
        "method": "PATCH",
        "path": "/workspaces/{id}",
        "summary": "Update workspace metadata/governance preferences.",
        "tags": ["workspaces"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {"metadata": OBJECT_SCHEMA},
            "required": ["metadata"],
        },
        "success": ("200", "Workspace updated."),
        "data_schema": {
            "type": "object",
            "properties": {"workspace": OBJECT_SCHEMA},
            "required": ["workspace"],
        },
        "not_found": True,
    },
    # ── Repositories ──────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/repositories",
        "summary": "List repositories attached to a workspace.",
        "tags": ["repositories"],
        "params": ["id"],
        "success": ("200", "List of repositories."),
        "data_schema": {
            "type": "object",
            "properties": {"repositories": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["repositories"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/repositories",
        "summary": "Attach a repository to a workspace (requires prior preview approval).",
        "tags": ["repositories"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "remote_url": {"type": "string"},
                "approved": {"type": "boolean"},
            },
            "required": ["path", "approved"],
        },
        "success": ("201", "Repository attached."),
        "data_schema": {
            "type": "object",
            "properties": {"repository": OBJECT_SCHEMA},
            "required": ["repository"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/repositories/preview",
        "summary": "Preview a repository intake before attaching it.",
        "tags": ["repositories"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "success": ("200", "Repository intake preview."),
        "data_schema": {
            "type": "object",
            "properties": {"preview": OBJECT_SCHEMA},
            "required": ["preview"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/repositories/{repository_id}/initialize",
        "summary": "Initialize an attached repository.",
        "tags": ["repositories"],
        "params": ["id", "repository_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Repository initialized."),
        "not_found": True,
    },
    # ── NCP status ────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/ncp/status",
        "summary": "Check whether the NCP CLI is available for a workspace.",
        "tags": ["workspaces"],
        "params": ["id"],
        "success": ("200", "NCP availability status."),
        "data_schema": {
            "type": "object",
            "properties": {"ncp_available": {"type": "boolean"}},
            "required": ["ncp_available"],
        },
        "not_found": True,
    },
    # ── Projects ──────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/projects",
        "summary": "List projects in a workspace.",
        "tags": ["projects"],
        "params": ["id"],
        "success": ("200", "List of projects."),
        "data_schema": {
            "type": "object",
            "properties": {"projects": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["projects"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/projects",
        "summary": "Create a project in a workspace.",
        "tags": ["projects"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "metadata": OBJECT_SCHEMA,
            },
            "required": ["name"],
        },
        "success": ("201", "Project created."),
        "data_schema": {
            "type": "object",
            "properties": {"project": OBJECT_SCHEMA},
            "required": ["project"],
        },
        "not_found": True,
    },
    # ── Providers ─────────────────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/workspaces/{id}/providers/{provider}/test",
        "summary": "Test and store credentials for a provider.",
        "tags": ["providers"],
        "params": ["id", "provider"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Provider test result."),
        "data_schema": {
            "type": "object",
            "properties": {"provider": OBJECT_SCHEMA},
            "required": ["provider"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/providers",
        "summary": "List provider health, optionally scoped to a workspace.",
        "tags": ["providers"],
        "query": [
            {
                "name": "workspace_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            }
        ],
        "success": ("200", "Provider health information."),
        "data_schema": {
            "type": "object",
            "properties": {"providers": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["providers"],
        },
        "not_found": True,
    },
    # ── Tasks (workspace-scoped) ──────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/tasks",
        "summary": "List tasks for a workspace.",
        "tags": ["tasks"],
        "params": ["id"],
        "success": ("200", "List of tasks."),
        "data_schema": {
            "type": "object",
            "properties": {"tasks": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["tasks"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/tasks",
        "summary": "Create a task in a workspace.",
        "tags": ["tasks"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "metadata": OBJECT_SCHEMA,
            },
            "required": ["title"],
        },
        "success": ("201", "Task created."),
        "data_schema": {
            "type": "object",
            "properties": {"task": OBJECT_SCHEMA},
            "required": ["task"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/task-drafts",
        "summary": "Create a task draft (PRD/AC shell) from a free-form prompt.",
        "tags": ["tasks"],
        "params": ["id"],
        "request": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "title": {"type": "string"},
                "context": OBJECT_SCHEMA,
            },
            "required": ["prompt"],
        },
        "success": ("201", "Task draft created with PRD/AC approval gate."),
        "data_schema": {
            "type": "object",
            "properties": {
                "task": OBJECT_SCHEMA,
                "approval_gate": OBJECT_SCHEMA,
                "messages": {"type": "array", "items": OBJECT_SCHEMA},
            },
            "required": ["task", "approval_gate", "messages"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/github/issues/import",
        "summary": "Import a GitHub issue as a task draft.",
        "tags": ["tasks"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Task draft created from imported GitHub issue."),
        "data_schema": {
            "type": "object",
            "properties": {
                "task": OBJECT_SCHEMA,
                "approval_gate": OBJECT_SCHEMA,
                "messages": {"type": "array", "items": OBJECT_SCHEMA},
            },
            "required": ["task", "approval_gate", "messages"],
        },
        "not_found": True,
    },
    # ── Workspace dashboards / views ─────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/task-dashboard",
        "summary": "Get the task dashboard view for a workspace.",
        "tags": ["views"],
        "params": ["id"],
        "query": [
            {
                "name": "project_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            }
        ],
        "success": ("200", "Task dashboard rows."),
        "data_schema": {
            "type": "object",
            "properties": {"tasks": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["tasks"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/operational-views",
        "summary": "Get operational views for a workspace.",
        "tags": ["views"],
        "params": ["id"],
        "success": ("200", "Operational views payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/usage-stats",
        "summary": "Get provider/token usage stats for a workspace.",
        "tags": ["views"],
        "params": ["id"],
        "success": ("200", "Usage stats payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/reuse-kit",
        "summary": "Get the reuse kit for a workspace.",
        "tags": ["views"],
        "params": ["id"],
        "success": ("200", "Reuse kit payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/dogfood-acceptance",
        "summary": "Get dogfood acceptance status for a workspace.",
        "tags": ["views"],
        "params": ["id"],
        "success": ("200", "Dogfood acceptance payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/knowledge-center",
        "summary": "Get the knowledge center for a workspace.",
        "tags": ["knowledge"],
        "params": ["id"],
        "success": ("200", "Knowledge center payload."),
        "not_found": True,
    },
    # ── Wiki ──────────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/wiki",
        "summary": "Get the workspace wiki index.",
        "tags": ["knowledge"],
        "params": ["id"],
        "success": ("200", "Wiki index payload."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/wiki",
        "summary": "Save a workspace wiki page.",
        "tags": ["knowledge"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Wiki page saved."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/wiki/{page}",
        "summary": "Get a single workspace wiki page.",
        "tags": ["knowledge"],
        "params": ["id", "page"],
        "success": ("200", "Wiki page payload."),
        "not_found": True,
    },
    # ── Skills ────────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/skills",
        "summary": "Get workspace skills.",
        "tags": ["knowledge"],
        "params": ["id"],
        "success": ("200", "Workspace skills payload."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/skills",
        "summary": "Save workspace skills.",
        "tags": ["knowledge"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Workspace skills saved."),
        "not_found": True,
    },
    # ── Context bundles ───────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/context-bundles",
        "summary": "Get context bundles for a workspace.",
        "tags": ["knowledge"],
        "params": ["id"],
        "success": ("200", "Context bundles payload."),
        "not_found": True,
    },
    # ── Proposals ─────────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/proposals",
        "summary": "List proposals for a workspace.",
        "tags": ["proposals"],
        "params": ["id"],
        "success": ("200", "Proposals payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/proposals/{proposal_id}",
        "summary": "Get a proposal's detail.",
        "tags": ["proposals"],
        "params": ["id", "proposal_id"],
        "success": ("200", "Proposal detail payload."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/proposals/{proposal_id}/accept",
        "summary": "Accept a proposal.",
        "tags": ["proposals"],
        "params": ["id", "proposal_id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Proposal accepted."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/proposals/{proposal_id}/reject",
        "summary": "Reject a proposal.",
        "tags": ["proposals"],
        "params": ["id", "proposal_id"],
        "request": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
        "success": ("200", "Proposal rejected."),
        "not_found": True,
    },
    # ── Dogfood learning ──────────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/workspaces/{id}/dogfood-learning",
        "summary": "Approve a dogfood learning entry for a workspace.",
        "tags": ["knowledge"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Dogfood learning approved."),
        "not_found": True,
    },
    # ── Policy pack ───────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/workspaces/{id}/policy-pack",
        "summary": "Get the policy pack for a workspace.",
        "tags": ["workspaces"],
        "params": ["id"],
        "success": ("200", "Policy pack payload."),
        "not_found": True,
    },
    {
        "method": "PUT",
        "path": "/workspaces/{id}/policy-pack/{filename}",
        "summary": "Write a policy pack file for a workspace.",
        "tags": ["workspaces"],
        "params": ["id", "filename"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Policy pack file written."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/policy",
        "summary": "Get the resolved policy caps for a workspace (server -> workspace tiers).",
        "tags": ["workspaces"],
        "params": ["id"],
        "success": ("200", "Resolved policy layering payload."),
        "not_found": True,
    },
    {
        "method": "PATCH",
        "path": "/workspaces/{id}/policy",
        "summary": "Set workspace-tier policy cap overrides (must not loosen server caps).",
        "tags": ["workspaces"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Resolved policy layering payload."),
        "not_found": True,
    },
    # ── Sessions (co-drive policy) ──────────────────────────────────────────
    {
        "method": "GET",
        "path": "/sessions/{id}/policy",
        "summary": "Get the resolved policy caps for a session (server -> workspace -> session tiers).",
        "tags": ["sessions"],
        "params": ["co_drive_session_id"],
        "success": ("200", "Resolved policy layering payload."),
        "not_found": True,
    },
    {
        "method": "PATCH",
        "path": "/sessions/{id}/policy",
        "summary": "Set session-tier policy cap overrides (must not loosen workspace caps).",
        "tags": ["sessions"],
        "params": ["co_drive_session_id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Resolved policy layering payload."),
        "not_found": True,
    },
    # ── Slack slash commands ────────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/workspaces/{id}/slack/commands/task",
        "summary": "Handle a Slack slash-command and create a task draft.",
        "tags": ["slack"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Slack-friendly JSON response with task_id and approval_gate_id."),
        "not_found": True,
        "raw_content_type": "application/json",
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/slack/interactions",
        "summary": "Handle a Slack block_actions callback (Approve/Reject gate buttons).",
        "tags": ["slack"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Empty JSON ack; the visible update, if any, goes via response_url."),
        "not_found": True,
        "raw_content_type": "application/json",
    },
    {
        "method": "POST",
        "path": "/workspaces/{id}/slack/events",
        "summary": "Handle a Slack Events API callback (URL verification + threaded replies).",
        "tags": ["slack"],
        "params": ["id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Empty JSON ack, or {\"challenge\": ...} for url_verification."),
        "not_found": True,
        "raw_content_type": "application/json",
    },
    # ── Tasks (by ID) ─────────────────────────────────────────────────────
    {
        "method": "GET",
        "path": "/tasks/{id}",
        "summary": "Get a task by ID.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task details."),
        "data_schema": {
            "type": "object",
            "properties": {"task": OBJECT_SCHEMA},
            "required": ["task"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/studio",
        "summary": "Get the task studio snapshot.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task studio snapshot."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/panel",
        "summary": "List panel entries for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task panel entries."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/graph",
        "summary": "Get the task graph.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task graph payload."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/evidence",
        "summary": "List evidence artifacts for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Evidence artifacts."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/reviews",
        "summary": "List review runs for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Review runs."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/handoff",
        "summary": "Get the latest handoff for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Latest handoff (or null)."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/checkpoint",
        "summary": "Get the latest checkpoint capsule for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Latest checkpoint capsule (or null)."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/checkpoints",
        "summary": "List checkpoint capsules for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Checkpoint capsules, most recent first."),
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/messages",
        "summary": "List messages for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task messages."),
        "data_schema": {
            "type": "object",
            "properties": {"messages": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["messages"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/approvals",
        "summary": "List approval gates for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Approval gates."),
        "data_schema": {
            "type": "object",
            "properties": {"approval_gates": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["approval_gates"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/tasks/{id}/dispatches",
        "summary": "List dispatches for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "success": ("200", "Task dispatches."),
        "data_schema": {
            "type": "object",
            "properties": {"dispatches": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["dispatches"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/messages",
        "summary": "Create a message on a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "content": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["content"],
        },
        "success": ("201", "Message created."),
        "data_schema": {
            "type": "object",
            "properties": {"message": OBJECT_SCHEMA},
            "required": ["message"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/graph-draft",
        "summary": "Generate (or fetch existing) task graph draft and open the Task graph approval gate.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Graph draft and approval gate."),
        "data_schema": {
            "type": "object",
            "properties": {"graph": OBJECT_SCHEMA, "approval_gate": OBJECT_SCHEMA},
            "required": ["graph", "approval_gate"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/approve",
        "summary": "Record an approval gate decision for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string"},
                "metadata": OBJECT_SCHEMA,
            },
            "required": ["name", "status"],
        },
        "success": ("201", "Approval gate recorded."),
        "data_schema": {
            "type": "object",
            "properties": {
                "approval_gate": OBJECT_SCHEMA,
                "auto_schedule": OBJECT_SCHEMA,
            },
            "required": ["approval_gate"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/auto-approve",
        "summary": "Auto-approve eligible pending gates for a task per workspace policy.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": {
            "type": "object",
            "properties": {"approved_by": {"type": "string"}},
        },
        "success": ("200", "Gates auto-approved."),
        "data_schema": {
            "type": "object",
            "properties": {
                "approved": {"type": "array", "items": OBJECT_SCHEMA},
                "auto_schedule": OBJECT_SCHEMA,
            },
            "required": ["approved", "auto_schedule"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/schedule",
        "summary": "Schedule ready subtasks for a task (requires approved Task graph gate).",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Ready subtasks scheduled."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/reviews/run",
        "summary": "Run a review for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Review run result."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/handoff",
        "summary": "Create a handoff for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Handoff created."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/checkpoint/restart",
        "summary": "Create a new task resumed from the latest checkpoint capsule.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "New task created from checkpoint."),
        "data_schema": {
            "type": "object",
            "properties": {"task": OBJECT_SCHEMA, "checkpoint": OBJECT_SCHEMA},
            "required": ["task", "checkpoint"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/tasks/{id}/repository-action",
        "summary": "Record a repository action for a task.",
        "tags": ["tasks"],
        "params": ["task_id"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Repository action recorded."),
        "not_found": True,
    },
    # ── Subtasks ──────────────────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/subtasks/{id}/transition",
        "summary": "Transition a subtask's status.",
        "tags": ["subtasks"],
        "params": ["subtask_id"],
        "request": OBJECT_SCHEMA,
        "success": ("200", "Subtask transitioned."),
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/subtasks/{id}/dispatch",
        "summary": "Dispatch a subtask to a worker.",
        "tags": ["subtasks"],
        "params": ["subtask_id"],
        "request": {
            "type": "object",
            "properties": {"worker_id": {"type": "string"}},
        },
        "success": ("201", "Subtask dispatched."),
        "not_found": True,
    },
    # ── Chat / events ─────────────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/chat",
        "summary": "Handle a chat request and dispatch to the appropriate provider.",
        "tags": ["chat"],
        "request": OBJECT_SCHEMA,
        "success": ("201", "Chat response."),
    },
    {
        "method": "GET",
        "path": "/events",
        "summary": "List lifecycle events, optionally filtered by workspace and/or task.",
        "tags": ["events"],
        "query": [
            {
                "name": "workspace_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            },
            {
                "name": "task_id",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            },
        ],
        "success": ("200", "Lifecycle events."),
        "data_schema": {
            "type": "object",
            "properties": {"events": {"type": "array", "items": OBJECT_SCHEMA}},
            "required": ["events"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/workspaces/{id}/tasks/{taskId}/events/stream",
        "summary": "Replay a task's lifecycle events as a Server-Sent Events stream.",
        "tags": ["events"],
        "params": ["workspace_id", "stream_task_id"],
        "success": ("200", "Server-Sent Events stream of lifecycle events."),
        "raw_content_type": "text/event-stream",
        "not_found": True,
    },
    # ── Brainstorm sessions ───────────────────────────────────────────────
    {
        "method": "POST",
        "path": "/brainstorm/sessions",
        "summary": "Create a brainstorm session.",
        "tags": ["brainstorm"],
        "request": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "title": {"type": "string"},
                "project_id": {"type": "string"},
                "provider": {"type": "string"},
                "output_format": {"type": "string"},
                "metadata": OBJECT_SCHEMA,
            },
            "required": ["workspace_id", "title"],
        },
        "success": ("200", "Brainstorm session created."),
        "data_schema": {
            "type": "object",
            "properties": {"session": OBJECT_SCHEMA},
            "required": ["session"],
        },
        "not_found": True,
    },
    {
        "method": "GET",
        "path": "/brainstorm/{id}",
        "summary": "Get a brainstorm session by ID.",
        "tags": ["brainstorm"],
        "params": ["session_id"],
        "success": ("200", "Brainstorm session."),
        "data_schema": {
            "type": "object",
            "properties": {"session": OBJECT_SCHEMA},
            "required": ["session"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/brainstorm/{id}/turns",
        "summary": "Append a turn to a brainstorm session.",
        "tags": ["brainstorm"],
        "params": ["session_id"],
        "request": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "content": {"type": "string"},
                "options": {"type": "array", "items": OBJECT_SCHEMA},
                "selected": OBJECT_SCHEMA,
                "spec_update": {"type": "string"},
            },
            "required": ["role", "content"],
        },
        "success": ("200", "Brainstorm session updated."),
        "data_schema": {
            "type": "object",
            "properties": {"session": OBJECT_SCHEMA},
            "required": ["session"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/brainstorm/{id}/research",
        "summary": "Append a research finding to a brainstorm session.",
        "tags": ["brainstorm"],
        "params": ["session_id"],
        "request": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "type": {"type": "string"},
                "summary": {"type": "string"},
                "refs": {"type": "array", "items": OBJECT_SCHEMA},
            },
            "required": ["agent", "summary"],
        },
        "success": ("200", "Brainstorm session updated with research finding."),
        "data_schema": {
            "type": "object",
            "properties": {"session": OBJECT_SCHEMA},
            "required": ["session"],
        },
        "not_found": True,
    },
    {
        "method": "POST",
        "path": "/brainstorm/{id}/approve",
        "summary": "Approve a brainstorm session and convert it into a task.",
        "tags": ["brainstorm"],
        "params": ["session_id"],
        "success": ("200", "Brainstorm session approved and task created."),
        "data_schema": {
            "type": "object",
            "properties": {"session": OBJECT_SCHEMA, "task": OBJECT_SCHEMA},
            "required": ["session", "task"],
        },
        "not_found": True,
    },
]


def _operation(route: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "summary": route["summary"],
        "tags": route.get("tags", []),
        "operationId": _operation_id(route),
    }

    parameters: list[dict[str, Any]] = []
    for param_key in route.get("params", []):
        parameters.append(_PATH_PARAMS[param_key])
    for query_param in route.get("query", []):
        parameters.append(query_param)
    if parameters:
        operation["parameters"] = parameters

    if "request" in route:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": route["request"]}},
        }

    status, description = route["success"]
    operation["responses"] = _responses(
        status,
        description,
        data_schema=route.get("data_schema"),
        not_found=route.get("not_found", False),
        raw_content_type=route.get("raw_content_type"),
        raw_schema=route.get("raw_schema"),
    )
    return operation


def _operation_id(route: dict[str, Any]) -> str:
    path_part = (
        route["path"]
        .strip("/")
        .replace("{", "")
        .replace("}", "")
        .replace("/", "_")
        .replace("-", "_")
    )
    return f"{route['method'].lower()}_{path_part or 'root'}"


def build_openapi_spec() -> dict[str, Any]:
    """Build the OpenAPI 3.1 document describing the Sarathi service API."""

    paths: dict[str, Any] = {}
    for route in ROUTES:
        path_item = paths.setdefault(route["path"], {})
        path_item[route["method"].lower()] = _operation(route)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": API_TITLE,
            "version": _api_version(),
            "description": (
                "Local HTTP service contract for Sarathi's orchestrator. "
                "Generated from the internal route registry in "
                "src/service/openapi.py, mirroring ServiceApp._route in "
                "src/service/app.py."
            ),
        },
        "servers": [{"url": "/api"}, {"url": "/"}],
        "paths": paths,
        "components": {
            "schemas": {
                "SuccessEnvelope": SUCCESS_ENVELOPE,
                "ErrorEnvelope": ERROR_ENVELOPE,
            }
        },
    }


def _docs_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def write_openapi_snapshot(path: Path | None = None) -> Path:
    """Write the current spec to ``docs/openapi.json`` (or ``path``)."""

    target = path or _docs_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    spec = build_openapi_spec()
    target.write_text(json.dumps(spec, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    written = write_openapi_snapshot()
    print(f"Wrote OpenAPI spec to {written}")
