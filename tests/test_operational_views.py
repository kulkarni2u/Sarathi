from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-operational"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-operational"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    return status, payload["data"]


def test_workspace_operational_views_are_backed_by_persisted_state(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{task['workspace_id']}/operational-views")
    )

    assert status == 200
    assert data["workspace_id"] == task["workspace_id"]
    assert data["usage"]["tasks"]["total"] == 1
    assert data["usage"]["tasks"]["by_status"]["done"] == 1
    assert data["usage"]["subtasks"]["total"] == 3
    assert data["usage"]["evidence"]["total"] == 1
    assert data["usage"]["reviews"]["total"] == 1
    assert data["usage"]["handoffs"]["total"] == 2
    assert "repository_action.approved" in [event["event_type"] for event in data["history"]]

    dependency = next(diagram for diagram in data["diagrams"] if diagram["kind"] == "dependency_graph")
    assert dependency["task_id"] == task["id"]
    assert len(dependency["nodes"]) == 3
    assert dependency["edges"]

    lifecycle = data["lifecycle"]
    assert lifecycle[0]["name"] == "Sarathi"
    assert any(role["name"] == "Nirnaya" and role["state"] == "active" for role in lifecycle)


def test_workspace_operational_views_requires_existing_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, payload = request(app, "GET", "/api/workspaces/missing/operational-views")

    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


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
            {"prompt": "Create operational views.", "title": "Operational views"},
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
