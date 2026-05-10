from src.service import create_app
from src.storage import Storage, connect, run_migrations


def request(app, method, path, body=None, correlation_id="corr-task-create"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-task-create"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def test_storage_can_create_and_list_task_messages(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Sarathi", root_path=str(tmp_path))
        task = storage.create_task(workspace_id=workspace["id"], title="Plan UI-05")

        message = storage.create_message(
            workspace_id=workspace["id"],
            task_id=task["id"],
            role="user",
            content="Create a task initiation flow.",
            metadata={"target": "Sarathi"},
        )

        assert message["id"]
        assert message["workspace_id"] == workspace["id"]
        assert message["task_id"] == task["id"]
        assert message["role"] == "user"
        assert message["content"] == "Create a task initiation flow."
        assert message["metadata"] == {"target": "Sarathi"}
        assert storage.list_messages(workspace_id=workspace["id"], task_id=task["id"]) == [message]


def test_service_creates_task_draft_from_orchestrator_prompt(tmp_path):
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
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {
                "prompt": "Build the workspace task initiation flow.",
                "title": "Workspace task initiation",
            },
        )
    )

    assert status == 201
    task = data["task"]
    assert task["workspace_id"] == workspace_id
    assert task["title"] == "Workspace task initiation"
    assert task["status"] == "prd_pending"
    assert task["metadata"]["source_prompt"] == "Build the workspace task initiation flow."
    assert task["metadata"]["prd"]["problem"]
    assert task["metadata"]["acceptance_criteria"]
    assert task["metadata"]["complexity"] == "high"

    approval_gate = data["approval_gate"]
    assert approval_gate["task_id"] == task["id"]
    assert approval_gate["name"] == "PRD/AC"
    assert approval_gate["status"] == "pending"

    messages = data["messages"]
    assert [message["role"] for message in messages] == ["user", "sarathi"]
    assert messages[0]["content"] == "Build the workspace task initiation flow."
    assert messages[1]["metadata"]["draft_task_id"] == task["id"]

    _, listed_messages = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/messages"))
    assert listed_messages["messages"] == messages

    _, listed_approvals = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/approvals"))
    assert listed_approvals["approval_gates"] == [approval_gate]

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    event_types = [event["event_type"] for event in events_data["events"]]
    assert "task.draft_created" in event_types
    assert "approval.requested" in event_types


def test_service_imports_github_issue_as_task_draft_with_repository_metadata(tmp_path):
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

    status, issue_url_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/github/issues/import",
            {
                "issue_url": "https://github.com/octo/sarathi/issues/42",
                "title": "Fix default-off repository actions",
            },
        )
    )

    assert status == 201
    issue_url_task = issue_url_data["task"]
    assert issue_url_task["status"] == "prd_pending"
    assert issue_url_task["metadata"]["repository_action_preference"]["mode"] == "no_action"
    assert issue_url_task["metadata"]["repository_action_preference"]["scope"] == "default"
    assert issue_url_task["metadata"]["github_issue"]["url"] == "https://github.com/octo/sarathi/issues/42"
    assert issue_url_task["metadata"]["github_issue"]["number"] == 42
    assert issue_url_task["metadata"]["github_issue"]["repository"]["full_name"] == "octo/sarathi"
    assert issue_url_task["metadata"]["github_issue"]["repository"]["owner"] == "octo"
    assert issue_url_task["metadata"]["github_issue"]["repository"]["name"] == "sarathi"
    assert issue_url_task["metadata"]["repository"]["github"]["full_name"] == "octo/sarathi"
    assert issue_url_task["metadata"]["repository"]["github"]["repository_url"] == "https://github.com/octo/sarathi"

    repository_path = tmp_path / "repo"
    repository_path.mkdir()
    _, repository_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {
                "path": str(repository_path),
                "approved": True,
            },
        )
    )
    repository = repository_data["repository"]

    _, issue_number_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/github/issues/import",
            {
                "issue_number": 7,
                "repository_id": repository["id"],
                "title": "Follow up on #7",
            },
        )
    )

    issue_number_task = issue_number_data["task"]
    assert issue_number_task["metadata"]["github_issue"]["number"] == 7
    assert issue_number_task["metadata"]["repository"]["workspace_repository_id"] == repository["id"]
    assert issue_number_task["metadata"]["repository"]["workspace_repository_path"] == repository["path"]
    assert issue_number_task["metadata"]["repository"]["workspace_repository_name"] == repository["name"]
