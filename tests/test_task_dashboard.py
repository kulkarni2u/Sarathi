from src.service import create_app
from src.storage import Storage, connect, run_migrations


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
    assert prd_summary["review_needed_count"] == 0
    assert prd_summary["checkpoint_state"] == "none"
    assert prd_summary["handoff_state"] == "none"

    graph_summary = summaries[1]
    assert graph_summary["id"] == graph_task["id"]
    assert graph_summary["approval_state"] == "graph_pending"
    assert graph_summary["graph_state"] == "pending_approval"
    assert graph_summary["node_count"] == 3
    assert graph_summary["blocked_count"] == 2
    assert graph_summary["review_needed_count"] == 0
    assert graph_summary["checkpoint_state"] == "none"
    assert graph_summary["handoff_state"] == "none"
    assert graph_summary["next_gate"] == "Task graph"
    assert graph_summary["roles"] == ["Disha", "Pravaha", "Nirnaya"]
    assert graph_summary["providers"] == ["Codex", "Claude"]


def test_task_dashboard_can_be_filtered_to_a_project(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_id = create_workspace(app, tmp_path)

    _, project_one = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Project One"},
        )
    )
    _, project_two = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Project Two"},
        )
    )

    create_task_draft(
        app,
        workspace_id,
        "Project one task",
        "Project one task",
        project_id=project_one["project"]["id"],
    )
    create_task_draft(
        app,
        workspace_id,
        "Project two task",
        "Project two task",
        project_id=project_two["project"]["id"],
    )

    status, data = assert_ok(
        request(
            app,
            "GET",
            f"/api/workspaces/{workspace_id}/task-dashboard?project_id={project_one['project']['id']}",
        )
    )

    assert status == 200
    assert [summary["title"] for summary in data["tasks"]] == ["Project one task"]


def test_task_dashboard_includes_project_name_for_each_task(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_id = create_workspace(app, tmp_path)

    _, project_one = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Project One"},
        )
    )

    create_task_draft(
        app,
        workspace_id,
        "Project one task",
        "Project one task",
        project_id=project_one["project"]["id"],
    )
    create_task_draft(app, workspace_id, "Unassigned task", "Unassigned task")

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/task-dashboard"))

    assert status == 200
    by_title = {summary["title"]: summary for summary in data["tasks"]}
    assert by_title["Project one task"]["project_name"] == "Project One"
    assert by_title["Unassigned task"]["project_name"] is None


def test_task_dashboard_maps_fan_in_blocked_coordination_state_to_blocked_queue_state(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)

    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Sarathi App", root_path=str(db_path.parent))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Fan-in blocked task",
            status="in_progress",
            metadata={"phase": "TaskTracking"},
        )
        root_a = storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=task["id"],
            title="Root A",
            status="complete",
            metadata={
                "role": "Pravaha",
                "provider": "Codex",
                "blocked_by": [],
                "evidence_required": ["tests"],
                "task_packet": {"goal": "Run A"},
            },
        )
        root_b = storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=task["id"],
            title="Root B",
            status="queued",
            metadata={
                "role": "Pravaha",
                "provider": "Claude",
                "blocked_by": [],
                "evidence_required": ["review"],
                "task_packet": {"goal": "Run B"},
            },
        )
        storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=task["id"],
            title="Join review",
            status="blocked",
            metadata={
                "role": "Nirnaya",
                "provider": "Codex",
                "blocked_by": [root_a["id"], root_b["id"]],
                "evidence_required": ["ac_coverage"],
                "task_packet": {"goal": "Review both"},
            },
        )

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace['id']}/task-dashboard"))

    assert status == 200
    summary = next(item for item in data["tasks"] if item["id"] == task["id"])
    assert summary["coordination_state"] == "fan_in_blocked"
    assert summary["queue_state"] == "blocked"


def test_task_dashboard_items_include_control_tower_fields(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_id = create_workspace(app, tmp_path)
    task = create_task_draft(app, workspace_id, "Control tower task", "Control Tower Task")

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

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/task-dashboard"))

    assert status == 200
    assert len(data["tasks"]) == 1
    task_summary = data["tasks"][0]

    assert "checkpoint_state" in task_summary
    assert "handoff_state" in task_summary
    assert "review_needed_count" in task_summary

    assert task_summary["checkpoint_state"] in {"none", "ready"}
    assert task_summary["handoff_state"] in {"none", "draft", "ready"}
    assert isinstance(task_summary["review_needed_count"], int)


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


def create_task_draft(app, workspace_id, prompt, title, project_id=None):
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {
                "prompt": prompt,
                "title": title,
                **({"context": {"projectId": project_id}} if project_id else {}),
            },
        )
    )
    return draft_data["task"]
