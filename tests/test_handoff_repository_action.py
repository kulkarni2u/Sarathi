from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-handoff"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-handoff"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-handoff"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def test_handoff_requires_approved_review_before_repository_action_gate(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_approved_graph(app, tmp_path)

    assert_error(
        request(app, "POST", f"/api/tasks/{task['id']}/handoff"),
        status=409,
        code="approval_required",
    )


def test_handoff_creates_release_dossier_and_pending_repository_action_gate(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_reviewed_task(app, tmp_path)

    status, data = assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/handoff"))

    assert status == 201
    handoff = data["handoff"]
    assert handoff["summary"].startswith("Sarathi handoff for Review loop")
    assert handoff["metadata"]["ac_coverage"]
    assert handoff["metadata"]["repository_action"]["status"] == "pending"
    assert data["repository_action_gate"]["name"] == "Repository action"
    assert data["repository_action_gate"]["status"] == "pending"

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    assert studio_data["handoff"]["id"] == handoff["id"]
    assert "handoff.created" in {event["event_type"] for event in studio_data["events"]}
    assert studio_data["task"]["status"] == "repository_action_pending"


def test_repository_action_requires_explicit_approval_and_records_decision(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_reviewed_task(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/handoff"))

    assert_error(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/repository-action",
            {"action": "draft_pr"},
        ),
        status=409,
        code="approval_required",
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/repository-action",
            {"action": "draft_pr", "approved": True},
        )
    )

    assert status == 201
    assert data["repository_action"]["action"] == "draft_pr"
    assert data["repository_action"]["status"] == "approved"
    assert data["approval_gate"]["name"] == "Repository action"
    assert data["approval_gate"]["status"] == "approved"

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    assert studio_data["handoff"]["metadata"]["repository_action"]["action"] == "draft_pr"
    assert "repository_action.approved" in {event["event_type"] for event in studio_data["events"]}


def create_reviewed_task(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
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
    return task


def create_task_with_approved_graph(app, tmp_path):
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
            {"prompt": "Create final handoff.", "title": "Review loop"},
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
    return task
