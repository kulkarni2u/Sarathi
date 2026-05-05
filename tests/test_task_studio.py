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
