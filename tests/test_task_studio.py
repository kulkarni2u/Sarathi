from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-task-studio"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-task-studio"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def test_task_studio_snapshot_combines_task_graph_messages_gates_and_history(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_graph(app, tmp_path)
    _, posted_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/messages",
            {
                "content": "Please focus Nirnaya on AC coverage.",
                "target": "Nirnaya",
            },
        )
    )

    status, data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))

    assert status == 200
    assert data["task"]["id"] == task["id"]
    assert data["graph"]["task_id"] == task["id"]
    assert [node["role"] for node in data["graph"]["nodes"]] == [
        "Disha",
        "Pravaha",
        "Nirnaya",
    ]
    assert data["graph"]["edges"] == [
        {
            "from": data["graph"]["nodes"][0]["id"],
            "to": data["graph"]["nodes"][1]["id"],
            "type": "blocks",
        },
        {
            "from": data["graph"]["nodes"][1]["id"],
            "to": data["graph"]["nodes"][2]["id"],
            "type": "blocks",
        },
    ]
    assert [message["role"] for message in data["messages"]] == ["user", "sarathi", "user"]
    assert data["messages"][-1]["id"] == posted_data["message"]["id"]
    assert data["messages"][-1]["metadata"]["target"] == "Nirnaya"
    assert {gate["name"] for gate in data["approval_gates"]} == {"PRD/AC", "Task graph"}
    event_types = {event["event_type"] for event in data["events"]}
    assert "task.graph_draft_created" in event_types
    assert "message.created" in event_types


def test_task_studio_exposes_header_state_posture(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_graph(app, tmp_path)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    first_node = studio_before["graph"]["nodes"][0]
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

    from src.storage import Storage, connect, run_migrations
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_checkpoint_capsule(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            project_id=None,
            status="ready",
            summary="Resume from this reviewed handoff.",
            key_decisions=[],
            evidence_refs=[],
            repository_action_preference={
                "scope": "task",
                "mode": "no_action",
                "allowed_modes": ["no_action"],
                "source": "test",
            },
            next_start_point="Resume from checkpoint",
            created_by="Sarathi",
        )

    status, data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))

    assert status == 200
    assert "header" in data
    header = data["header"]
    assert header["queue_state"] == "handoff_ready"
    assert header["next_safe_action"] == "Review handoff"
    assert header["repository_action_mode"] == "no_action"
    assert header["checkpoint_ready"] is True
    assert header["handoff_state"] == "draft"
    assert header["approval_state"] == "approval_pending"


def test_task_studio_header_ignores_superseded_pending_approval_gates(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_graph(app, tmp_path)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    status, data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))

    assert status == 200
    task_graph_gate_statuses = [
        gate["status"] for gate in data["approval_gates"] if gate["name"] == "Task graph"
    ]
    assert task_graph_gate_statuses == ["pending", "approved"]
    assert data["header"]["approval_state"] == "approved"
    assert data["header"]["queue_state"] == "running"
    assert data["header"]["next_safe_action"] == "Monitor execution"


def create_task_with_graph(app, tmp_path):
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
                "prompt": "Build service-backed Task Studio.",
                "title": "Service-backed Task Studio",
            },
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
    return task
