from src.service import create_app
from src.storage import Storage, connect, run_migrations


def request(app, method, path, body=None, correlation_id="corr-task-graph"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-task-graph"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-task-graph"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def test_storage_can_create_and_list_subtasks_for_task(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Sarathi", root_path=str(tmp_path))
        task = storage.create_task(workspace_id=workspace["id"], title="Graph task")

        subtask = storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=task["id"],
            title="Draft graph",
            status="queued",
            metadata={
                "role": "Disha",
                "provider": "Codex",
                "blocked_by": [],
                "evidence_required": ["task_packet"],
            },
        )

        assert subtask["id"]
        assert subtask["workspace_id"] == workspace["id"]
        assert subtask["task_id"] == task["id"]
        assert subtask["title"] == "Draft graph"
        assert subtask["status"] == "queued"
        assert subtask["metadata"]["role"] == "Disha"
        assert storage.list_subtasks_for_task(task["id"]) == [subtask]


def test_service_requires_prd_approval_before_task_graph_generation(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_draft(app, tmp_path)

    assert_error(
        request(app, "POST", f"/api/tasks/{task['id']}/graph-draft"),
        status=409,
        code="approval_required",
    )


def test_service_creates_task_graph_and_graph_approval_gate(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_draft(app, tmp_path)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )

    status, data = assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/graph-draft"))

    assert status == 201
    graph = data["graph"]
    assert graph["task_id"] == task["id"]
    assert [node["role"] for node in graph["nodes"]] == ["Disha", "Pravaha", "Nirnaya"]
    assert [node["status"] for node in graph["nodes"]] == ["queued", "blocked", "blocked"]
    assert graph["edges"] == [
        {"from": graph["nodes"][0]["id"], "to": graph["nodes"][1]["id"], "type": "blocks"},
        {"from": graph["nodes"][1]["id"], "to": graph["nodes"][2]["id"], "type": "blocks"},
    ]

    graph_gate = data["approval_gate"]
    assert graph_gate["name"] == "Task graph"
    assert graph_gate["status"] == "pending"
    assert graph_gate["metadata"]["requires_human"] is True
    assert graph_gate["metadata"]["node_count"] == 3

    _, graph_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/graph"))
    assert graph_data["nodes"] == graph["nodes"]
    assert graph_data["edges"] == graph["edges"]

    _, approvals_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/approvals"))
    approval_names = [gate["name"] for gate in approvals_data["approval_gates"]]
    assert "PRD/AC" in approval_names
    assert "Task graph" in approval_names

    _, events_data = assert_ok(request(app, "GET", f"/api/events?task_id={task['id']}"))
    event_types = [event["event_type"] for event in events_data["events"]]
    assert "task.graph_draft_created" in event_types
    assert event_types.count("approval.requested") >= 2


def create_task_draft(app, tmp_path):
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
            {
                "prompt": "Build graph generation and approval.",
                "title": "Task graph generation",
            },
        )
    )
    return draft_data["task"]
