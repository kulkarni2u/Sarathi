from pathlib import Path

from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-dogfood"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-dogfood"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    return status, payload["data"]


def assert_error(response, *, status, code):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def test_dogfood_acceptance_dossier_proves_full_sarathi_loop_without_private_paths(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{task['workspace_id']}/dogfood-acceptance")
    )

    assert status == 200
    assert data["status"] == "passed"
    assert all(check["status"] == "passed" for check in data["checks"])
    assert data["release_dossier"]["redacted"] is True
    assert str(tmp_path) not in data["release_dossier"]["summary"]
    assert data["release_dossier"]["built_with"] == "Sarathi"
    assert data["learning_record"]["status"] == "proposed"
    assert data["learning_record"]["target_file"] == "learnings.md"


def test_approved_dogfood_learning_updates_workspace_learnings_file(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)

    assert_error(
        request(app, "POST", f"/api/workspaces/{task['workspace_id']}/dogfood-learning", {}),
        status=409,
        code="approval_required",
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{task['workspace_id']}/dogfood-learning",
            {"approved": True},
        )
    )

    assert status == 201
    assert data["learning_record"]["status"] == "accepted"
    learning_path = Path(data["learning_record"]["path"])
    assert learning_path == tmp_path / "learnings.md"
    content = learning_path.read_text()
    assert "## Accepted Sarathi Dogfood Learning" in content
    assert task["id"] in content

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={task['workspace_id']}"))
    assert "learning.accepted" in [event["event_type"] for event in events_data["events"]]


def create_completed_task(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Dogfood Sarathi with its own task loop.", "title": "Sarathi dogfood"},
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
    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    first_node = studio_data["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{first_node['id']}/dispatch",
            {"provider": "local"},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/handoff"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/repository-action",
            {"action": "no_action", "approved": True},
        )
    )
    _, completed_task_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}"))
    return completed_task_data["task"]
