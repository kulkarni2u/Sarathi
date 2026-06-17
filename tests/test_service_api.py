import http.client
import json
import stat
import uuid
import threading
from urllib.parse import urlparse

import pytest

from src.service import create_app, create_http_server
from src.service.app import RawResponse
from src.service.openapi import build_openapi_spec
from src.service import providers as service_providers
from src.storage import Storage, connect, run_migrations


def request(app, method, path, body=None, correlation_id="corr-test"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-test"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    assert "error" not in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-test"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code
    assert payload["error"]["status"] == status
    assert payload["error"]["message"]
    assert "data" not in payload


class FakeChatSession:
    PROVIDERS = ("claude", "opencode", "codex")
    sent: list[str] = []

    def __init__(self, workspace_root=None):
        self.workspace_root = workspace_root
        self.provider = None

    def set_provider(self, name):
        self.provider = (name, f"/fake/{name}")
        return True

    def resolve_provider(self):
        if self.provider is None:
            self.provider = ("claude", "/fake/claude")
        return self.provider

    def send(self, message):
        self.resolve_provider()
        self.sent.append(message)
        return f"provider reply: {message}"


def test_health_returns_ok_with_correlation_id(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, data = assert_ok(request(app, "GET", "/api/health"))

    assert status == 200
    assert data == {"status": "ok"}


def test_workspace_creation_bootstraps_policy_pack_and_generated_wiki(tmp_path):
    db_path = tmp_path / "state" / "sarathi.db"
    root_path = tmp_path / "repo-to-bootstrap"
    app = create_app(db_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Pravaha UI", "root_path": str(root_path)},
        )
    )
    assert status == 201
    assert data["workspace"]["id"]
    assert data["workspace"]["name"] == "Pravaha UI"
    assert data["workspace"]["root_path"] == str(root_path)
    assert (root_path / "policy-pack" / "commands.md").exists()
    assert (root_path / ".sarathi" / "wiki" / "README.md").exists()
    bootstrap = data["workspace"]["metadata"]["bootstrap"]
    assert bootstrap["policy_pack"]["status"] == "created"
    assert bootstrap["wiki"]["status"] == "created"

    status, data = assert_ok(request(create_app(db_path), "GET", "/api/workspaces"))
    assert status == 200
    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["name"] == "Pravaha UI"


def test_workspace_creation_reuses_existing_init_and_human_wiki(tmp_path):
    db_path = tmp_path / "state" / "sarathi.db"
    root_path = tmp_path / "existing-repo"
    policy_dir = root_path / "policy-pack"
    wiki_dir = root_path / ".sarathi" / "wiki"
    policy_dir.mkdir(parents=True)
    wiki_dir.mkdir(parents=True)
    existing_commands = "# Commands\n\ncustom: true\n"
    human_notes = "# Human Notes\n\nDo not overwrite this.\n"
    (policy_dir / "commands.md").write_text(existing_commands, encoding="utf-8")
    (wiki_dir / "notes.md").write_text(human_notes, encoding="utf-8")
    app = create_app(db_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Existing", "root_path": str(root_path)},
        )
    )

    assert status == 201
    assert (policy_dir / "commands.md").read_text(encoding="utf-8") == existing_commands
    assert (wiki_dir / "notes.md").read_text(encoding="utf-8") == human_notes
    assert data["workspace"]["metadata"]["bootstrap"]["policy_pack"]["status"] == "reused"
    assert data["workspace"]["metadata"]["bootstrap"]["wiki"]["status"] == "refreshed"


def test_workspace_repository_action_preference_can_be_saved(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "repository_action_preference": {
                        "scope": "workspace",
                        "mode": "draft_pr",
                    }
                }
            },
        )
    )

    assert status == 200
    assert data["workspace"]["metadata"]["repository_action_preference"]["scope"] == "workspace"
    assert data["workspace"]["metadata"]["repository_action_preference"]["mode"] == "draft_pr"

    _, workspace_again = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}"))
    assert workspace_again["workspace"]["metadata"]["repository_action_preference"]["mode"] == "draft_pr"


def test_workspace_provider_priority_can_be_saved_and_emits_governance_event(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "provider_priority": ["codex", "claude"],
                }
            },
        )
    )

    assert status == 200
    assert data["workspace"]["metadata"]["provider_priority"] == ["codex", "claude"]

    _, events = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    governance_events = [
        event for event in events["events"] if event["event_type"] == "workspace.governance_updated"
    ]
    assert governance_events
    assert governance_events[-1]["payload"]["changed_keys"] == ["provider_priority"]
    assert governance_events[-1]["payload"]["snapshot"]["provider_priority"] == ["codex", "claude"]


def test_workspace_reuse_preferences_emit_reuse_event(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "reuse_preferences": {
                        "active_saved_view_id": "blocked-projects",
                        "custom_saved_views": [
                            {
                                "id": "ops-handoffs",
                                "name": "Ops handoffs",
                                "role": "operator",
                                "route": "workspace",
                                "description": "Custom reusable view for handoff work.",
                                "metric_label": "ready handoffs",
                                "filters": {"task_state": "handoff_ready"},
                            }
                        ],
                    },
                }
            },
        )
    )

    assert status == 200
    assert data["workspace"]["metadata"]["reuse_preferences"]["active_saved_view_id"] == "blocked-projects"
    assert data["workspace"]["metadata"]["reuse_preferences"]["custom_saved_views"][0]["id"] == "ops-handoffs"

    _, events = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    reuse_events = [event for event in events["events"] if event["event_type"] == "workspace.reuse_updated"]
    governance_events = [event for event in events["events"] if event["event_type"] == "workspace.governance_updated"]
    assert reuse_events
    assert not governance_events
    assert reuse_events[-1]["payload"]["changed_keys"] == ["reuse_preferences"]
    assert reuse_events[-1]["payload"]["snapshot"]["reuse_preferences"]["active_saved_view_id"] == "blocked-projects"
    assert reuse_events[-1]["payload"]["snapshot"]["reuse_preferences"]["custom_saved_views"][0]["id"] == "ops-handoffs"


def test_brainstorm_session_metadata_persists_into_task_reuse_metadata(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, session_data = assert_ok(
        request(
            app,
            "POST",
            "/api/brainstorm/sessions",
            {
                "workspace_id": workspace_id,
                "title": "Template: feature delivery",
                "metadata": {
                    "reuse_source": {"kind": "workflow_template", "id": "feature-delivery", "name": "Feature delivery"},
                    "workflow_template_id": "feature-delivery",
                    "recommended_view_ids": ["approvals-inbox", "handoff-readiness"],
                    "recommended_repository_action_mode": "draft_pr",
                    "recommended_auto_approve_mode": "below_threshold",
                    "suggested_provider_priority": ["codex", "claude"],
                },
            },
        )
    )

    assert status == 200
    assert session_data["session"]["metadata"]["workflow_template_id"] == "feature-delivery"

    _, approved = assert_ok(
        request(app, "POST", f"/api/brainstorm/{session_data['session']['id']}/approve", {})
    )

    reuse_metadata = approved["task"]["metadata"]["reuse"]
    assert reuse_metadata["reuse_source"]["kind"] == "workflow_template"
    assert reuse_metadata["reuse_source"]["id"] == "feature-delivery"
    assert reuse_metadata["workflow_template_id"] == "feature-delivery"
    assert reuse_metadata["recommended_view_ids"] == ["approvals-inbox", "handoff-readiness"]
    assert reuse_metadata["recommended_repository_action_mode"] == "draft_pr"
    assert reuse_metadata["recommended_auto_approve_mode"] == "below_threshold"
    assert reuse_metadata["suggested_provider_priority"] == ["codex", "claude"]


def test_browser_cors_allows_loopback_vite_port(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, payload = app.handle(
        "GET",
        "/api/workspaces",
        headers={
            "origin": "http://127.0.0.1:5174",
            "x-correlation-id": "cors-test",
        },
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["correlation_id"] == "cors-test"
    assert payload["data"]["workspaces"][0]["id"] == workspace_id


def test_task_lifecycle_for_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {
                "title": "Create service boundary",
                "description": "Expose minimal stdlib local API.",
            },
        )
    )
    assert status == 201
    task = task_data["task"]
    assert task["workspace_id"] == workspace_id
    assert task["title"] == "Create service boundary"
    assert task["status"] == "pending"

    status, get_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}"))
    assert status == 200
    assert get_data["task"] == task

    status, list_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/tasks"))
    assert status == 200
    assert list_data["tasks"] == [task]


def test_task_handoff_creates_checkpoint_capsule(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "QA", "root_path": "/tmp/qa"})
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/tasks", {"title": "Checkpoint task"})
    )
    task_id = task_data["task"]["id"]
    storage = Storage(connect(tmp_path / "sarathi.db"))
    storage.create_review_run(workspace_id=workspace_id, task_id=task_id, status="approved", summary="OK")
    status, handoff_data = assert_ok(request(app, "POST", f"/api/tasks/{task_id}/handoff", {}))
    assert status == 201
    checkpoint = handoff_data["checkpoint"]
    assert checkpoint["source_task_id"] == task_id
    assert checkpoint["status"] == "ready"


def test_task_checkpoint_can_be_retrieved_and_restarted(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "QA", "root_path": "/tmp/qa"})
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/tasks", {"title": "Checkpoint task"})
    )
    task_id = task_data["task"]["id"]
    storage = Storage(connect(tmp_path / "sarathi.db"))
    storage.create_review_run(workspace_id=workspace_id, task_id=task_id, status="approved", summary="OK")
    assert_ok(request(app, "POST", f"/api/tasks/{task_id}/handoff", {}))

    status, checkpoint_data = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/checkpoint"))
    assert status == 200
    checkpoint = checkpoint_data["checkpoint"]
    assert checkpoint["source_task_id"] == task_id
    assert checkpoint["status"] == "ready"

    status, restart_data = assert_ok(request(app, "POST", f"/api/tasks/{task_id}/checkpoint/restart", {}))
    assert status == 201
    restarted_task = restart_data["task"]
    assert restarted_task["workspace_id"] == workspace_id
    assert restarted_task["status"] == "prd_pending"
    assert restarted_task["metadata"]["source_checkpoint_id"] == checkpoint["id"]
    assert restarted_task["metadata"]["repository_action_preference"] == checkpoint["repository_action_preference"]


def test_task_checkpoint_history_is_returned_latest_first(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "QA", "root_path": "/tmp/qa"})
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/tasks", {"title": "Checkpoint task"})
    )
    task_id = task_data["task"]["id"]
    storage = Storage(connect(tmp_path / "sarathi.db"))
    storage.create_checkpoint_capsule(
        workspace_id=workspace_id,
        task_id=task_id,
        summary="First checkpoint",
        key_decisions=["A"],
        evidence_refs=["e1"],
        repository_action_preference={"mode": "no_action", "scope": "workspace", "allowed_modes": ["no_action"]},
        next_start_point="Resume from first checkpoint",
        created_by="test",
    )
    storage.create_checkpoint_capsule(
        workspace_id=workspace_id,
        task_id=task_id,
        summary="Second checkpoint",
        key_decisions=["B"],
        evidence_refs=["e2"],
        repository_action_preference={"mode": "no_action", "scope": "workspace", "allowed_modes": ["no_action"]},
        next_start_point="Resume from second checkpoint",
        created_by="test",
    )

    status, checkpoints_data = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/checkpoints"))
    assert status == 200
    checkpoints = checkpoints_data["checkpoints"]
    assert [checkpoint["summary"] for checkpoint in checkpoints] == ["Second checkpoint", "First checkpoint"]


def test_workspace_and_placeholder_task_resources(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace = workspace_data["workspace"]
    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/tasks",
            {"title": "Future orchestration"},
        )
    )
    task = task_data["task"]

    assert_ok(request(app, "GET", f"/api/workspaces/{workspace['id']}"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/graph"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/evidence"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/reviews"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/handoff"))
    assert_ok(request(app, "GET", f"/api/providers?workspace_id={workspace['id']}"))
    assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace['id']}"))


def test_task_panel_snapshot_endpoint_merges_timeline_entries(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task_id = create_task_with_panel_entries(app, tmp_path)

    status, data = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/panel"))

    assert status == 200
    assert data["task_id"] == task_id
    assert [entry["kind"] for entry in data["entries"]] == [
        "human_message",
        "blocked",
        "review",
        "claimed",
        "evidence",
        "review",
        "handoff",
    ]
    assert data["entries"][0]["summary"] == "Start the panel flow."
    assert data["entries"][1]["summary"] == "Task blocked: waiting_user"
    assert data["entries"][3]["target"] == "subtask-1"


def test_dispatch_persists_usage_metadata_for_operational_views(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    first_node = studio_before["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{first_node['id']}/dispatch",
            {"provider": "local"},
        )
    )

    assert status == 201
    assert data["dispatch"]["metadata"]["usage"]["total_tokens"] > 0
    assert data["dispatch"]["metadata"]["usage"]["budget_state"] in {"ok", "warning", "near_limit", "exhausted", "unknown"}
    assert data["dispatch"]["metadata"]["usage"]["usage_source"] in {"reported", "estimated", "mixed"}


def test_approval_endpoint_persists_gate_and_event(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Approve graph"},
        )
    )
    task_id = task_data["task"]["id"]

    status, approval_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    assert status == 201
    approval = approval_data["approval_gate"]
    assert approval["id"]
    assert approval["workspace_id"] == workspace_id
    assert approval["task_id"] == task_id
    assert approval["status"] == "approved"

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    assert events_data["events"]
    assert events_data["events"][-1]["object_id"] == approval["id"]


def test_chat_and_task_draft_persist_project_context(tmp_path, monkeypatch):
    FakeChatSession.sent = []
    monkeypatch.setattr(service_providers, "ChatSession", FakeChatSession)
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    project_id = "project-123"

    status, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {
                "prompt": "Build a project-scoped task draft.",
                "title": "Project-scoped draft",
                "context": {"projectId": project_id},
            },
        )
    )
    assert status == 201
    draft_task = draft_data["task"]
    assert draft_task["metadata"]["project_id"] == project_id

    status, chat_data = assert_ok(
        request(
            app,
            "POST",
            "/api/chat",
            {
                "message": "Plan the workspace onboarding flow.",
                "context": {"workspaceId": workspace_id, "projectId": project_id},
            },
        )
    )
    assert status == 201
    _, task_data = assert_ok(request(app, "GET", f"/api/tasks/{chat_data['taskId']}"))
    assert task_data["task"]["metadata"]["project_id"] == project_id


def test_service_chat_invokes_provider_and_persists_reply(tmp_path, monkeypatch):
    FakeChatSession.sent = []
    monkeypatch.setattr(service_providers, "ChatSession", FakeChatSession)
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "POST",
            "/api/chat",
            {
                "message": "Talk to the model from the service.",
                "context": {"workspaceId": workspace_id},
            },
        )
    )

    assert status == 201
    assert data["agent"] == "claude"
    assert data["status"] == "completed"
    assert FakeChatSession.sent == ["Talk to the model from the service."]
    assert data["reply"]["content"] == "provider reply: Talk to the model from the service."
    _, messages = assert_ok(request(app, "GET", f"/api/tasks/{data['taskId']}/messages"))
    assert [message["role"] for message in messages["messages"]] == ["user", "claude"]


def test_task_message_can_invoke_provider_and_return_reply(tmp_path, monkeypatch):
    FakeChatSession.sent = []
    monkeypatch.setattr(service_providers, "ChatSession", FakeChatSession)
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Provider-backed task chat"},
        )
    )
    task_id = task_data["task"]["id"]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/messages",
            {
                "content": "Continue this task with an agent.",
                "target": "Current task agents",
                "invoke_provider": True,
            },
        )
    )

    assert status == 201
    assert data["agent"] == "claude"
    assert FakeChatSession.sent == ["Continue this task with an agent."]
    assert data["reply"]["content"] == "provider reply: Continue this task with an agent."
    _, messages = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/messages"))
    assert [message["role"] for message in messages["messages"]] == ["user", "claude"]
    _, events = assert_ok(request(app, "GET", f"/api/events?task_id={task_id}"))
    event_types = {event["event_type"] for event in events["events"]}
    assert "message.created" in event_types
    assert "message.provider_replied" in event_types


def test_task_draft_accepts_snake_case_project_context(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, project_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "UI Enhancements"},
        )
    )
    project_id = project_data["project"]["id"]

    status, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {
                "prompt": "Start a project chat from the cockpit.",
                "context": {"project_id": project_id},
            },
        )
    )

    assert status == 201
    assert draft_data["task"]["project_id"] == project_id
    assert draft_data["task"]["metadata"]["project_id"] == project_id


def test_workspace_projects_can_be_created_and_listed(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Orchestration Studio", "root_path": "/tmp/studio"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, created = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Desktop Hardening", "description": "Trustworthy orchestration surfaces"},
        )
    )
    assert status == 201
    assert created["project"]["workspace_id"] == workspace_id
    assert created["project"]["name"] == "Desktop Hardening"
    assert created["project"]["description"] == "Trustworthy orchestration surfaces"
    assert created["project"]["status"] == "active"

    status, listed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/projects"))
    assert status == 200
    project_names = [p["name"] for p in listed["projects"]]
    assert "Desktop Hardening" in project_names


def test_workspace_projects_are_rejected_without_name(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Orchestration Studio", "root_path": "/tmp/studio"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, payload = request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/projects",
        {"description": "Missing name field"},
    )
    assert status == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_request"


def test_workspace_project_list_requires_existing_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, payload = request(app, "GET", "/api/workspaces/nonexistent/projects")
    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_workspace_projects_order_by_created_at(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Orchestration Studio", "root_path": "/tmp/studio"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_ok(request(app, "POST", f"/api/workspaces/{workspace_id}/projects", {"name": "Project Alpha"}))
    assert_ok(request(app, "POST", f"/api/workspaces/{workspace_id}/projects", {"name": "Project Beta"}))

    status, listed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/projects"))
    project_names = [p["name"] for p in listed["projects"]]
    assert project_names == ["Project Alpha", "Project Beta"]


def test_task_draft_preserves_project_id_when_context_provides_it(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, ws = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "Sutra", "root_path": "/tmp/sutra"}),
    )
    workspace_id = ws["workspace"]["id"]
    _, proj = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/projects", {"name": "Task Studio"}),
    )
    project_id = proj["project"]["id"]

    status, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {
                "prompt": "Build the task studio hardening.",
                "context": {"projectId": project_id},
            },
        )
    )
    assert status == 201
    assert draft_data["task"]["metadata"]["project_id"] == project_id


def test_workspace_project_desktop_summary_includes_task_counts_and_last_activity(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, ws = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "Sutra", "root_path": "/tmp/sutra"}),
    )
    workspace_id = ws["workspace"]["id"]
    _, proj = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/projects", {"name": "Desktop Summary"}),
    )
    project_id = proj["project"]["id"]

    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "First task", "context": {"projectId": project_id}},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Second task", "context": {"projectId": project_id}},
        )
    )

    status, listed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/projects"))
    summary = next(p for p in listed["projects"] if p["id"] == project_id)
    assert summary["task_count"] == 2
    assert summary["updated_at"] is not None


def test_workspace_project_desktop_summary_includes_blocked_and_review_counts(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, ws = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "Sutra", "root_path": "/tmp/sutra"}),
    )
    workspace_id = ws["workspace"]["id"]
    _, proj = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/projects", {"name": "Summary Counts"}),
    )
    project_id = proj["project"]["id"]

    _, draft1 = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Blocked task", "context": {"projectId": project_id}},
        )
    )
    _, draft2 = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Review task", "context": {"projectId": project_id}},
        )
    )

    from src.storage import Storage, connect, run_migrations
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            task_id=draft1["task"]["id"],
            event_type="task.blocked",
            payload={"reason": "waiting_user"},
        )
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=draft2["task"]["id"],
            name="Review",
            status="pending",
            metadata={"requires_human": True},
        )

    status, listed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/projects"))
    summary = next(p for p in listed["projects"] if p["id"] == project_id)
    assert summary["blocked_count"] == 1
    assert summary["review_needed_count"] == 1


def test_http_sse_stream_returns_persisted_events(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        _, workspace_data = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            body={"name": "Sutra", "root_path": "/tmp/sutra"},
        )
        workspace_id = workspace_data["data"]["workspace"]["id"]

        status, headers, body = http_sse(
            "GET",
            f"{base_url}/api/events/stream?workspace_id={workspace_id}",
            token="secret",
        )

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert headers.get("content-length") is None
        assert "event: snapshot" in body
        assert "workspace.created" in body


def test_http_sse_stream_filters_by_task_id(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        _, workspace_data = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            body={"name": "Sutra", "root_path": "/tmp/sutra"},
        )
        workspace_id = workspace_data["data"]["workspace"]["id"]

        _, task_one = http_json(
            "POST",
            f"{base_url}/api/workspaces/{workspace_id}/tasks",
            token="secret",
            body={"title": "Task one"},
        )
        task_one_id = task_one["data"]["task"]["id"]

        _, task_two = http_json(
            "POST",
            f"{base_url}/api/workspaces/{workspace_id}/tasks",
            token="secret",
            body={"title": "Task two"},
        )
        task_two_id = task_two["data"]["task"]["id"]

        db_path = tmp_path / "sarathi.db"
        with connect(db_path) as conn:
            run_migrations(conn)
            storage = Storage(conn)
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task_one_id,
                event_type="task.blocked",
                payload={"reason": "waiting_task_one"},
            )
            storage.create_lifecycle_event(
                workspace_id=workspace_id,
                task_id=task_two_id,
                event_type="task.blocked",
                payload={"reason": "waiting_task_two"},
            )

        status, headers, body = http_sse(
            "GET",
            f"{base_url}/api/events/stream?workspace_id={workspace_id}&task_id={task_one_id}&token=secret",
            token="secret",
        )

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert headers.get("content-length") is None
        assert "event: snapshot" in body
        assert "waiting_task_one" in body
        assert "waiting_task_two" not in body


def test_http_sse_stream_accepts_query_token_for_browser_eventsource(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        _, workspace_data = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            body={"name": "Sutra", "root_path": "/tmp/sutra"},
        )
        workspace_id = workspace_data["data"]["workspace"]["id"]

        status, headers, body = http_sse(
            "GET",
            f"{base_url}/api/events/stream?workspace_id={workspace_id}&token=secret",
        )

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert headers.get("content-length") is None
        assert "event: snapshot" in body
        assert "workspace.created" in body


def test_errors_are_typed_and_include_correlation_id(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    assert_error(
        request(app, "GET", "/api/tasks/missing", correlation_id="corr-missing"),
        status=404,
        code="not_found",
        correlation_id="corr-missing",
    )
    assert_error(
        request(app, "POST", "/api/workspaces", {"name": "No Root"}),
        status=400,
        code="invalid_request",
    )
    assert_error(
        request(app, "DELETE", "/api/workspaces"),
        status=404,
        code="not_found",
    )


def test_callable_api_requires_token_when_configured(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="secret")

    assert_error(
        app.handle("GET", "/api/health", headers={"x-correlation-id": "corr-auth"}),
        status=401,
        code="unauthorized",
        correlation_id="corr-auth",
    )

    status, data = assert_ok(
        app.handle(
            "GET",
            "/api/health",
            headers={
                "authorization": "Bearer secret",
                "x-correlation-id": "corr-authorized",
            },
        ),
        correlation_id="corr-authorized",
    )
    assert status == 200
    assert data == {"status": "ok"}


def test_http_server_requires_token_even_on_loopback(tmp_path):
    # No loopback bypass: on shared machines any local process can reach
    # 127.0.0.1, so the bearer token is required for every connection.
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json("GET", f"{base_url}/api/health")
        assert status == 401
        assert payload["ok"] is False
        assert payload["error"]["code"] == "unauthorized"

        # Token also works
        status, payload = http_json(
            "GET",
            f"{base_url}/api/health",
            token="secret",
            correlation_id="corr-http",
        )
        assert status == 200
        assert payload["ok"] is True
        assert payload["correlation_id"] == "corr-http"


def test_http_server_discovery_includes_auth_and_db_metadata(tmp_path, monkeypatch):
    discovery_path = tmp_path / "home" / ".sarathi" / "service.json"
    db_path = tmp_path / "state" / "sarathi.db"
    monkeypatch.setattr("src.service.http._service_discovery_path", lambda: discovery_path)

    # A stale discovery file with loose permissions must be replaced, not reused.
    discovery_path.parent.mkdir(parents=True)
    discovery_path.write_text("{}", encoding="utf-8")
    discovery_path.chmod(0o644)

    with running_server(db_path, token="secret") as base_url:
        payload = json.loads(discovery_path.read_text(encoding="utf-8"))

        assert payload["url"] == base_url
        assert payload["host"] == "127.0.0.1"
        assert payload["port"]
        assert payload["auth"] == {"type": "bearer", "token": "secret"}
        assert payload["db_path"] == str(db_path.resolve())
        assert stat.S_IMODE(discovery_path.stat().st_mode) == 0o600
        assert not discovery_path.with_name(discovery_path.name + ".tmp").exists()

    assert not discovery_path.exists()


def test_http_server_rejects_invalid_json(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            raw_body=b"{bad json",
        )
        assert status == 400
        assert payload["error"]["code"] == "invalid_json"


def test_http_server_returns_json_for_unsupported_methods(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json("DELETE", f"{base_url}/api/workspaces", token="secret")

        assert status == 404
        assert payload["ok"] is False
        assert payload["error"]["code"] == "not_found"


def test_http_server_supports_browser_cors_preflight(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, headers, body = http_raw(
            "OPTIONS",
            f"{base_url}/api/workspaces",
            correlation_id="corr-preflight",
            extra_headers={
                "origin": "http://127.0.0.1:5173",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization, content-type",
            },
        )

        assert status == 204
        assert body == ""
        assert headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert "POST" in headers["access-control-allow-methods"]
        assert "authorization" in headers["access-control-allow-headers"].lower()


def test_http_server_adds_cors_headers_to_json_responses(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, headers, payload = http_json_with_headers(
            "GET",
            f"{base_url}/api/health",
            token="secret",
            extra_headers={"origin": "http://127.0.0.1:5173"},
        )

        assert status == 200
        assert payload["ok"] is True
        assert headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_http_server_rejects_oversized_body(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            raw_body=b"{" + (b" " * 70_000) + b"}",
        )

        assert status == 413
        assert payload["error"]["code"] == "request_too_large"


class running_server:
    def __init__(self, db_path, token, dist_root=None):
        self.server = create_http_server(
            db_path=db_path, token=token, host="127.0.0.1", port=0, dist_root=dist_root
        )
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def http_json(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    status, _headers, body_text = http_raw(
        method,
        url,
        token=token,
        body=body,
        raw_body=raw_body,
        correlation_id=correlation_id,
        extra_headers=extra_headers,
    )
    return status, json.loads(body_text)


def http_json_with_headers(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    status, headers, body_text = http_raw(
        method,
        url,
        token=token,
        body=body,
        raw_body=raw_body,
        correlation_id=correlation_id,
        extra_headers=extra_headers,
    )
    return status, headers, json.loads(body_text)


def http_raw(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    data = raw_body if raw_body is not None else None
    if data is None and body is not None:
        data = json.dumps(body).encode("utf-8")
    headers = {"x-correlation-id": correlation_id}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if body is not None or raw_body is not None:
        headers["content-type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    try:
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")
    finally:
        connection.close()


def http_sse(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    data = raw_body if raw_body is not None else None
    if data is None and body is not None:
        data = json.dumps(body).encode("utf-8")
    headers = {"x-correlation-id": correlation_id}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if body is not None or raw_body is not None:
        headers["content-type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    try:
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        chunks: list[str] = []
        while True:
            line = response.readline().decode("utf-8")
            if not line:
                break
            chunks.append(line)
            if line in {"\n", "\r\n"}:
                break
        return response.status, dict(response.getheaders()), "".join(chunks)
    finally:
        connection.close()


def create_task_with_panel_entries(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Service-backed task panel",
            description="Panel snapshot fixture.",
            status="in_progress",
        )
        task_id = task["id"]
        storage.create_message(
            workspace_id=workspace_id,
            task_id=task_id,
            role="user",
            content="Start the panel flow.",
            metadata={"target": "Sarathi"},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            task_id=task_id,
            event_type="task.blocked",
            payload={"reason": "waiting_user"},
        )
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=task_id,
            name="PRD/AC",
            status="pending",
            metadata={"requires_human": True},
        )
        storage.create_dispatch(
            workspace_id=workspace_id,
            task_id=task_id,
            agent_name="Pravaha",
            status="queued",
            metadata={"subtask_id": "subtask-1"},
        )
        storage.create_evidence_artifact(
            workspace_id=workspace_id,
            task_id=task_id,
            artifact_type="doc",
            uri="sarathi://evidence/doc-1",
            metadata={"note": "panel evidence"},
        )
        storage.create_review_run(
            workspace_id=workspace_id,
            task_id=task_id,
            status="approved",
            summary="Review approved.",
            metadata={"review_type": "code"},
        )
        storage.create_handoff(
            workspace_id=workspace_id,
            task_id=task_id,
            summary="Handoff to Disha for implementation.",
            from_agent="Pravaha",
            to_agent="Disha",
            metadata={"handoff_type": "panel"},
        )
    return task_id


def create_task_with_ready_graph(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Dispatch ready work unit.", "title": "Service dispatch"},
        )
    )
    task = draft_data["task"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/graph-draft"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    return task


def test_workspace_auto_approve_preference_can_be_saved(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "below_threshold",
                        "threshold": {
                            "complexity": "low",
                            "max_node_count": 3,
                        },
                    }
                }
            },
        )
    )

    assert status == 200
    assert data["workspace"]["metadata"]["auto_approve_preference"]["scope"] == "workspace"
    assert data["workspace"]["metadata"]["auto_approve_preference"]["mode"] == "below_threshold"

    _, workspace_again = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}"))
    assert workspace_again["workspace"]["metadata"]["auto_approve_preference"]["mode"] == "below_threshold"


def test_auto_approve_blocked_when_mode_is_manual_only(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "manual_only",
                    }
                }
            },
        )
    )

    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Test task"},
        )
    )
    task_id = task_data["task"]["id"]

    from src.storage import Storage, connect, run_migrations
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=task_id,
            name="Code review",
            status="pending",
            metadata={"complexity": "low", "node_count": 2},
        )

    assert_error(
        request(app, "POST", f"/api/tasks/{task_id}/auto-approve"),
        status=403,
        code="auto_approve_disabled",
    )


def test_auto_approve_allowed_for_below_threshold_with_eligible_gates(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "below_threshold",
                        "threshold": {
                            "complexity": "low",
                            "max_node_count": 3,
                        },
                    }
                }
            },
        )
    )

    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Test task"},
        )
    )
    task_id = task_data["task"]["id"]

    from src.storage import Storage, connect, run_migrations
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=task_id,
            name="Code review",
            status="pending",
            metadata={"complexity": "low", "node_count": 2},
        )

    _, result = assert_ok(request(app, "POST", f"/api/tasks/{task_id}/auto-approve"))
    assert len(result["approved"]) == 1
    assert result["approved"][0]["name"] == "Code review"
    assert result["approved"][0]["metadata"]["auto_approved"] is True


def test_auto_approve_denied_for_denylisted_gates(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "below_threshold",
                        "threshold": {
                            "complexity": "low",
                            "max_node_count": 10,
                        },
                    }
                }
            },
        )
    )

    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Create a feature"},
        )
    )
    task_id = draft_data["task"]["id"]

    assert_error(
        request(app, "POST", f"/api/tasks/{task_id}/auto-approve"),
        status=403,
        code="auto_approve_denied",
    )


def test_auto_approve_ignores_gates_not_meeting_threshold(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "below_threshold",
                        "threshold": {
                            "complexity": "low",
                            "max_node_count": 3,
                        },
                    }
                }
            },
        )
    )

    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Test task"},
        )
    )
    task_id = task_data["task"]["id"]

    from src.storage import Storage, connect, run_migrations
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=task_id,
            name="Code review",
            status="pending",
            metadata={"complexity": "low", "node_count": 2},
        )
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=task_id,
            name="Security review",
            status="pending",
            metadata={"complexity": "high", "node_count": 10},
        )

    _, result = assert_ok(request(app, "POST", f"/api/tasks/{task_id}/auto-approve"))
    assert len(result["approved"]) == 1
    assert result["approved"][0]["name"] == "Code review"


def test_workspace_proposals_list_pending_candidates_from_workspace_signals(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))

    assert status == 200
    assert data["workspace_id"] == workspace_id
    titles = {proposal["title"] for proposal in data["proposals"]}
    assert "Add Build failure recovery guidance" in titles
    assert "Reroute Build away from codex" in titles
    assert "Capture Review escalation playbook" in titles
    assert "Add Build iteration guard skill" in titles
    assert "Reduce Build context omission risk" in titles or "Optimize Build context budget pressure" in titles
    repeated_failure = next(item for item in data["proposals"] if item["policy_file"] == "commands.md")
    provider_failure = next(item for item in data["proposals"] if item["policy_file"] == "model-routing.md")
    wiki_proposal = next(item for item in data["proposals"] if item["policy_file"] == "wiki/review-loop.md")
    skill_proposal = next(item for item in data["proposals"] if item["policy_file"] == "skills.md")
    context_proposal = next(item for item in data["proposals"] if item["policy_file"] == "wiki/context-compiler.md")
    assert repeated_failure["proposal_kind"] == "policy_note"
    assert repeated_failure["impacted_assets"] == ["policy-pack/commands.md"]
    assert repeated_failure["risk_level"] == "low"
    assert provider_failure["proposal_kind"] == "routing_hint"
    assert provider_failure["impacted_assets"] == ["policy-pack/model-routing.md"]
    assert provider_failure["risk_level"] == "high"
    assert wiki_proposal["proposal_kind"] == "wiki_update"
    assert wiki_proposal["impacted_assets"] == ["wiki/review-loop.md"]
    assert wiki_proposal["risk_level"] == "medium"
    assert skill_proposal["proposal_kind"] == "skill_update"
    assert skill_proposal["impacted_assets"] == ["policy-pack/skills.md"]
    assert skill_proposal["risk_level"] == "medium"
    assert context_proposal["proposal_kind"] == "context_update"
    assert context_proposal["impacted_assets"] == ["wiki/context-compiler.md"]
    assert context_proposal["risk_level"] == "medium"
    assert "trimmed sections: prior_findings, relevant_files" in context_proposal["rationale"]
    assert "near budget: 118/120 tokens" in context_proposal["rationale"]
    assert "Specifically address: prior_findings, relevant_files." in context_proposal["suggested_change"]
    assert data["reviewed_history"] == []
    assert data["source"] == "synthesized_from_workspace_state"


def test_workspace_skills_payload_filters_evolution_proposals_to_behavior_changes(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/skills"))

    assert status == 200
    titles = {proposal["title"] for proposal in data["evolution_proposals"]}
    assets = {proposal["impacted_assets"][0] for proposal in data["evolution_proposals"]}
    assert "Reroute Build away from codex" in titles
    assert "Add Build iteration guard skill" in titles
    assert "Capture Review escalation playbook" not in titles
    assert "Improve Build context compilation guidance" not in titles
    assert "Reduce Build context omission risk" not in titles
    assert "Optimize Build context budget pressure" not in titles
    assert assets == {"policy-pack/model-routing.md", "policy-pack/skills.md"}


def test_workspace_skills_payload_includes_evolution_history(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, all_proposals = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    skill_proposals = [p for p in all_proposals["proposals"] if p["policy_file"] in ("skills.md", "model-routing.md")]

    accepted_count = 0
    for proposal in skill_proposals:
        accept_status, _ = assert_ok(
            request(app, "POST", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}/accept", {})
        )
        if accept_status == 200:
            accepted_count += 1

    (tmp_path / "policy-pack" / ".sarathi-proposals").mkdir(parents=True, exist_ok=True)
    import uuid
    fake_rejected = {
        "id": str(uuid.uuid4())[:8],
        "status": "rejected",
        "title": "Fake rejected proposal",
        "policy_file": "skills.md",
        "proposal_kind": "skill_update",
        "reviewed_at": "2026-05-15T10:00:00Z",
        "reason": "Test rejection",
    }
    (tmp_path / "policy-pack" / ".sarathi-proposals" / f"{fake_rejected['id']}.json").write_text(
        json.dumps(fake_rejected), encoding="utf-8"
    )

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/skills"))

    assert status == 200
    assert "evolution_history" in data
    assert isinstance(data["evolution_history"], list)

    accepted = [h for h in data["evolution_history"] if h["status"] == "accepted"]
    rejected = [h for h in data["evolution_history"] if h["status"] == "rejected"]

    assert len(accepted) >= 1
    assert len(rejected) >= 1

    for item in data["evolution_history"]:
        assert item["status"] in ("accepted", "rejected")
        assert item["title"]
        assert item["reviewed_at"]
        assert "skills.md" in item["policy_file"].lower() or "model-routing" in item["policy_file"].lower()


def test_workspace_proposals_can_be_accepted_and_filtered_from_pending_list(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    proposal = next(item for item in data["proposals"] if item["policy_file"] == "commands.md")

    status, decision_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/proposals/{proposal['id'][:8]}/accept", {})
    )

    assert status == 200
    assert decision_data["decision"]["status"] == "accepted"
    assert decision_data["decision"]["evidence_refs"]
    commands_text = (tmp_path / "policy-pack" / "commands.md").read_text(encoding="utf-8")
    assert "accepted_proposals:" in commands_text

    _, refreshed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    refreshed_ids = {item["id"] for item in refreshed["proposals"]}
    assert proposal["id"] not in refreshed_ids
    accepted_history = next(item for item in refreshed["reviewed_history"] if item["id"] == proposal["id"])
    assert accepted_history["status"] == "accepted"
    assert accepted_history["evidence_refs"]


def test_workspace_proposal_detail_returns_current_content_and_accept_preview(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    proposal = next(item for item in data["proposals"] if item["policy_file"] == "commands.md")

    status, detail = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}")
    )

    assert status == 200
    assert detail["proposal"]["id"] == proposal["id"]
    assert detail["proposal"]["proposal_kind"] == "policy_note"
    assert detail["proposal"]["impacted_assets"] == ["policy-pack/commands.md"]
    assert detail["proposal"]["risk_level"] == "low"
    assert detail["policy_preview"]["exists"] is True
    assert detail["policy_preview"]["path"].endswith("policy-pack/commands.md")
    assert "command: pytest" in detail["policy_preview"]["current_content"]
    assert "accepted_proposals:" in detail["policy_preview"]["accepted_preview"]
    assert proposal["id"] in detail["policy_preview"]["accepted_preview"]


def test_workspace_wiki_proposal_preview_and_accept_can_create_target_asset(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    proposal = next(item for item in data["proposals"] if item["policy_file"] == "wiki/review-loop.md")

    status, detail = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}")
    )

    assert status == 200
    assert detail["proposal"]["proposal_kind"] == "wiki_update"
    assert detail["policy_preview"]["exists"] is False
    assert detail["policy_preview"]["path"].endswith("wiki/review-loop.md")
    assert "Capture Review escalation playbook" in detail["policy_preview"]["accepted_preview"]

    status, decision_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}/accept", {})
    )

    assert status == 200
    assert decision_data["decision"]["status"] == "accepted"
    created_text = (tmp_path / "wiki" / "review-loop.md").read_text(encoding="utf-8")
    assert "Capture Review escalation playbook" in created_text


def test_workspace_context_proposal_preview_and_accept_can_create_target_asset(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    proposal = next(item for item in data["proposals"] if item["policy_file"] == "wiki/context-compiler.md")

    status, detail = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}")
    )

    assert status == 200
    assert detail["proposal"]["proposal_kind"] == "context_update"
    assert detail["policy_preview"]["exists"] is False
    assert detail["policy_preview"]["path"].endswith("wiki/context-compiler.md")
    assert "Reduce Build context omission risk" in detail["policy_preview"]["accepted_preview"]
    assert "prior_findings, relevant_files" in detail["policy_preview"]["accepted_preview"]
    assert "118/120 tokens" in detail["policy_preview"]["accepted_preview"]

    status, decision_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}/accept", {})
    )

    assert status == 200
    assert decision_data["decision"]["status"] == "accepted"
    created_text = (tmp_path / "wiki" / "context-compiler.md").read_text(encoding="utf-8")
    assert "Reduce Build context omission risk" in created_text
    assert "prior_findings, relevant_files" in created_text
    assert "118/120 tokens" in created_text


def test_workspace_proposals_can_be_rejected_and_recorded(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace_id = _seed_workspace_proposal_signals(app, db_path, tmp_path)

    _, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    proposal = next(item for item in data["proposals"] if item["policy_file"] == "model-routing.md")

    status, decision_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}/reject",
            {"reason": "Not needed right now"},
        )
    )

    assert status == 200
    assert decision_data["decision"]["status"] == "rejected"
    assert decision_data["decision"]["evidence_refs"]
    decision_path = tmp_path / "policy-pack" / ".sarathi-proposals" / f"{proposal['id']}.json"
    assert decision_path.exists()
    assert "Not needed right now" in decision_path.read_text(encoding="utf-8")

    _, refreshed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/proposals"))
    rejected_history = next(item for item in refreshed["reviewed_history"] if item["id"] == proposal["id"])
    assert rejected_history["status"] == "rejected"
    assert rejected_history["reason"] == "Not needed right now"


def _seed_workspace_proposal_signals(app, db_path, root_path):
    _write_workspace_proposal_policy_pack(root_path)
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Proposal Workspace", "root_path": str(root_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    with connect(db_path) as conn:
        storage = Storage(conn)
        for index in range(2):
            task = storage.create_task(
                workspace_id=workspace_id,
                title=f"Failing build {index + 1}",
                description=None,
                metadata={"complexity": "high"},
            )
            subtask = storage.create_subtask(
                workspace_id=workspace_id,
                task_id=task["id"],
                title="Implement scoped change",
                status="failed",
                metadata={"role": "Pravaha"},
            )
            storage.create_dispatch(
                workspace_id=workspace_id,
                task_id=task["id"],
                agent_name="codex",
                status="failed",
                metadata={
                    "subtask_id": subtask["id"],
                    "agent_output": {"status": "failed", "summary": "codex failed during Build"},
                },
            )
            storage.create_dispatch(
                workspace_id=workspace_id,
                task_id=task["id"],
                agent_name="codex",
                status="complete",
                metadata={
                    "subtask_id": subtask["id"],
                    "agent_output": {"status": "complete", "summary": "codex needed a second Build pass"},
                    "context_pack": {
                        "phase": "Build",
                        "agent_input": {"token_budget": 120},
                        "compilation": {
                            "estimated_tokens": 118,
                            "trimmed_sections": ["prior_findings", "relevant_files"],
                        },
                    },
                },
            )
            storage.create_review_run(
                workspace_id=workspace_id,
                task_id=task["id"],
                status="rejected",
                summary="Review rejected after repeated drift.",
                metadata={},
            )
    return workspace_id


def _write_workspace_proposal_policy_pack(root_path):
    policy_dir = root_path / "policy-pack"
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: pytest
```
""",
        encoding="utf-8",
    )
    (policy_dir / "model-routing.md").write_text("# Model routing\n", encoding="utf-8")
    (policy_dir / "escalation.md").write_text("# Escalation\n", encoding="utf-8")


# ── Usage stats, SSE replay, /docs, and static serving ─────────────────────


def test_usage_stats_route_returns_projection(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Usage task"},
        )
    )
    task_id = task_data["task"]["id"]

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/usage-stats")
    )

    assert status == 200
    assert data["workspace_id"] == workspace_id
    assert data["task_count"] == 1
    assert data["tasks"][0]["task_id"] == task_id
    # Defensive defaults for a fresh task with no reviews/dispatches.
    assert data["test_pass_rate"] is None
    assert data["avg_blast_radius"] is None
    assert data["total_tokens"] == 0


def test_usage_stats_route_404s_for_unknown_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    assert_error(
        request(app, "GET", "/api/workspaces/nonexistent/usage-stats"),
        status=404,
        code="not_found",
    )


def test_events_stream_route_replays_lifecycle_events_as_sse(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)

    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Streamed task"},
        )
    )
    task_id = task_data["task"]["id"]

    conn, storage = app._storage()
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task_id,
        event_type="task.started",
        payload={"object_id": task_id},
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task_id,
        event_type="task.completed",
        payload={"object_id": task_id},
    )

    result = app.handle(
        "GET", f"/api/workspaces/{workspace_id}/tasks/{task_id}/events/stream"
    )

    assert result.status == 200
    assert result.content_type == "text/event-stream"
    body = result.body.decode("utf-8")
    assert "event: task.created" in body
    assert "event: task.started" in body
    assert "event: task.completed" in body
    # Each SSE frame is terminated by a blank line.
    assert body.count("\n\n") >= 3

    # Honor Last-Event-ID: replay only events strictly after the given id.
    events = storage.list_events(workspace_id=workspace_id, task_id=task_id)
    created_event_id = next(e["id"] for e in events if e["event_type"] == "task.created")

    result_after = app.handle(
        "GET",
        f"/api/workspaces/{workspace_id}/tasks/{task_id}/events/stream",
        headers={"Last-Event-ID": created_event_id},
    )
    body_after = result_after.body.decode("utf-8")
    assert "event: task.created" not in body_after
    assert "event: task.started" in body_after
    assert "event: task.completed" in body_after


def test_events_stream_route_404s_for_unknown_task(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    result = app.handle(
        "GET", f"/api/workspaces/{workspace_id}/tasks/missing/events/stream"
    )

    # 404s are still returned through the normal {ok, error} envelope since
    # the route did not match the raw-SSE special case (task lookup failed
    # before any SSE bytes were written).
    status, payload = result
    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_docs_route_returns_html_referencing_openapi(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    result = app.handle("GET", "/api/docs")

    assert result.status == 200
    assert result.content_type.startswith("text/html")
    body = result.body.decode("utf-8")
    assert "/openapi.json" in body
    assert "<html" in body.lower()


def test_http_docs_route_serves_html_over_the_wire(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, headers, body = http_raw("GET", f"{base_url}/api/docs", token="secret")

        assert status == 200
        assert headers["content-type"].startswith("text/html")
        assert "/openapi.json" in body


def test_static_serving_returns_seeded_file_from_temp_dist_root(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "index.html").write_text("<html><body>SPA shell</body></html>", encoding="utf-8")
    assets_dir = dist_root / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('hi');", encoding="utf-8")

    app = create_app(tmp_path / "sarathi.db", dist_root=dist_root)

    # A direct asset request returns the seeded file with the right content type.
    result = app.handle("GET", "/assets/app.js")
    assert result.status == 200
    assert result.content_type.startswith("text/javascript")
    assert result.body == b"console.log('hi');"

    # A client-side route with no extension falls back to index.html.
    result = app.handle("GET", "/some/spa/route")
    assert result.status == 200
    assert result.content_type.startswith("text/html")
    assert b"SPA shell" in result.body

    # A missing asset (has an extension, no file on disk) 404s.
    result = app.handle("GET", "/assets/missing.js")
    assert result.status == 404


def test_static_serving_does_not_shadow_api_routes(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "index.html").write_text("<html><body>SPA shell</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "sarathi.db", dist_root=dist_root)

    # /api/health must still hit the JSON API, not the static fallback.
    status, data = assert_ok(request(app, "GET", "/api/health"))
    assert status == 200
    assert data == {"status": "ok"}

    # An unknown workspace under /api/workspaces/... still 404s through the
    # normal error envelope rather than falling back to the SPA shell.
    assert_error(
        request(app, "GET", "/api/workspaces/nonexistent"),
        status=404,
        code="not_found",
    )


def test_http_static_serving_over_the_wire(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "index.html").write_text("<html><body>SPA shell</body></html>", encoding="utf-8")
    assets_dir = dist_root / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('hi');", encoding="utf-8")

    with running_server(tmp_path / "sarathi.db", token="secret", dist_root=dist_root) as base_url:
        status, headers, body = http_raw("GET", f"{base_url}/assets/app.js", token="secret")
        assert status == 200
        assert headers["content-type"].startswith("text/javascript")
        assert body == "console.log('hi');"

        status, headers, body = http_raw("GET", f"{base_url}/assets/missing.js", token="secret")
        assert status == 404


def test_root_spa_shell_is_public_even_with_token_configured(tmp_path):
    # The single-origin "installable app" path: a browser navigating to
    # http://127.0.0.1:8765/ has no Authorization header. The SPA shell must
    # be served (200), not rejected with 401.
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "index.html").write_text("<html><body>SPA shell</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "sarathi.db", token="secret", dist_root=dist_root)

    result = app.handle("GET", "/")

    assert isinstance(result, RawResponse)
    assert result.status == 200
    assert result.content_type.startswith("text/html")
    assert b"SPA shell" in result.body


def test_api_routes_still_require_auth_when_token_configured(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "index.html").write_text("<html><body>SPA shell</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "sarathi.db", token="secret", dist_root=dist_root)

    # No Authorization header -> the JSON API is still locked down.
    assert_error(
        app.handle("GET", "/api/workspaces", headers={"x-correlation-id": "corr-test"}),
        status=401,
        code="unauthorized",
    )

    # With the correct bearer token, the API still works as before.
    status, data = assert_ok(
        app.handle(
            "GET",
            "/api/workspaces",
            headers={"authorization": "Bearer secret", "x-correlation-id": "corr-test"},
        )
    )
    assert status == 200
    assert data == {"workspaces": []}


def test_sarathi_runtime_js_is_public_and_contains_token(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="secret")

    result = app.handle("GET", "/sarathi-runtime.js")

    assert isinstance(result, RawResponse)
    assert result.status == 200
    assert result.content_type.startswith("application/javascript")
    body = result.body.decode("utf-8")
    assert "__SARATHI_RUNTIME_CONFIG__" in body
    assert "secret" in body
    assert '"baseUrl": ""' in body or '"baseUrl":""' in body


def test_health_route_is_public_without_token(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="secret")

    status, data = assert_ok(app.handle("GET", "/health", headers={"x-correlation-id": "corr-test"}))

    assert status == 200
    assert data == {"status": "ok"}


def test_docs_and_openapi_routes_are_public_without_token(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="secret")

    docs_result = app.handle("GET", "/docs")
    assert isinstance(docs_result, RawResponse)
    assert docs_result.status == 200
    assert docs_result.content_type.startswith("text/html")

    status, spec = app.handle("GET", "/openapi.json")
    assert status == 200
    assert spec["openapi"].startswith("3.")


def test_openapi_spec_includes_usage_stats_and_event_stream_routes():
    spec = build_openapi_spec()
    paths = spec["paths"]

    assert "/workspaces/{id}/usage-stats" in paths
    assert "get" in paths["/workspaces/{id}/usage-stats"]

    assert "/workspaces/{id}/tasks/{taskId}/events/stream" in paths
    stream_op = paths["/workspaces/{id}/tasks/{taskId}/events/stream"]["get"]
    assert "text/event-stream" in stream_op["responses"]["200"]["content"]
