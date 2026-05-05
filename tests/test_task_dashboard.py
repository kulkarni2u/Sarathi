from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-dashboard"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-dashboard"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def test_task_dashboard_summarizes_workspace_tasks_and_graph_state(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_id = create_workspace(app, tmp_path)
    prd_task = create_task_draft(app, workspace_id, "Plan UI dashboard", "Dashboard draft")
    graph_task = create_task_draft(app, workspace_id, "Generate graph", "Graph draft")
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{graph_task['id']}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{graph_task['id']}/graph-draft"))

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/task-dashboard"))

    assert status == 200
    summaries = data["tasks"]
    assert [summary["title"] for summary in summaries] == ["Dashboard draft", "Graph draft"]

    prd_summary = summaries[0]
    assert prd_summary["id"] == prd_task["id"]
    assert prd_summary["status"] == "prd_pending"
    assert prd_summary["approval_state"] == "prd_pending"
    assert prd_summary["graph_state"] == "not_started"
    assert prd_summary["node_count"] == 0

    graph_summary = summaries[1]
    assert graph_summary["id"] == graph_task["id"]
    assert graph_summary["approval_state"] == "graph_pending"
    assert graph_summary["graph_state"] == "pending_approval"
    assert graph_summary["node_count"] == 3
    assert graph_summary["blocked_count"] == 2
    assert graph_summary["next_gate"] == "Task graph"
    assert graph_summary["roles"] == ["Disha", "Pravaha", "Nirnaya"]
    assert graph_summary["providers"] == ["Codex", "Claude"]


def create_workspace(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    return workspace_data["workspace"]["id"]


def create_task_draft(app, workspace_id, prompt, title):
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": prompt, "title": title},
        )
    )
    return draft_data["task"]
