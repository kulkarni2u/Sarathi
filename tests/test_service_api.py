import http.client
import json
import threading
from urllib.parse import urlparse

import pytest

from src.service import create_app, create_http_server
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


def test_health_returns_ok_with_correlation_id(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, data = assert_ok(request(app, "GET", "/api/health"))

    assert status == 200
    assert data == {"status": "ok"}


def test_workspace_lifecycle_is_persisted_without_touching_repo_paths(tmp_path):
    db_path = tmp_path / "state" / "sarathi.db"
    root_path = tmp_path / "repo-that-service-must-not-create"
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
    assert not root_path.exists()

    status, data = assert_ok(request(create_app(db_path), "GET", "/api/workspaces"))
    assert status == 200
    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["name"] == "Pravaha UI"


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


def test_chat_and_task_draft_persist_project_context(tmp_path):
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


def test_http_server_requires_token_and_returns_json(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, unauthorized = http_json("GET", f"{base_url}/api/health")
        assert status == 401
        assert unauthorized["ok"] is False
        assert unauthorized["error"]["code"] == "unauthorized"

        status, payload = http_json(
            "GET",
            f"{base_url}/api/health",
            token="secret",
            correlation_id="corr-http",
        )
        assert status == 200
        assert payload["ok"] is True
        assert payload["correlation_id"] == "corr-http"
        assert payload["data"] == {"status": "ok"}


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
    def __init__(self, db_path, token):
        self.server = create_http_server(db_path=db_path, token=token, host="127.0.0.1", port=0)
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
