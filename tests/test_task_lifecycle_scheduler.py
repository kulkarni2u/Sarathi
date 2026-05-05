from src.service import create_app
from src.storage import Storage, connect, run_migrations


def request(app, method, path, body=None, correlation_id="corr-task-scheduler"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-task-scheduler"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-task-scheduler"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def test_scheduler_requires_approved_task_graph_before_dispatching_ready_units(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_graph(app, tmp_path)

    assert_error(
        request(app, "POST", f"/api/tasks/{task['id']}/schedule"),
        status=409,
        code="approval_required",
    )


def test_scheduler_starts_all_ready_siblings_and_records_events(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    workspace, task, root_a, root_b, join = create_sibling_graph(db_path)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    status, data = assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    assert status == 200
    assert [unit["id"] for unit in data["scheduled"]] == [root_a["id"], root_b["id"]]
    assert all(unit["status"] == "in_progress" for unit in data["scheduled"])
    assert data["blocked"] == [join["id"]]
    assert data["waiting_human"] == []
    assert data["coordination_state"] == "active"
    assert data["fan_in_nodes"] == [join["id"]]

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    statuses = {node["id"]: node["status"] for node in studio_data["graph"]["nodes"]}
    assert statuses[root_a["id"]] == "in_progress"
    assert statuses[root_b["id"]] == "in_progress"
    assert statuses[join["id"]] == "blocked"
    assert studio_data["graph"]["fan_in_nodes"] == [join["id"]]
    assert studio_data["graph"]["coordination_state"] == "active"
    assert_event_types(
        studio_data["events"],
        ["subtask.scheduled", "subtask.scheduled"],
    )
    assert studio_data["task"]["status"] == "in_progress"
    assert studio_data["task"]["metadata"]["phase"] == "TaskTracking"
    assert workspace["id"] == task["workspace_id"]


def test_task_graph_approval_auto_schedules_ready_units_when_policy_enabled(tmp_path):
    db_path = tmp_path / "sarathi.db"
    write_auto_schedule_policy(tmp_path)
    app = create_app(db_path)
    _, task, root_a, root_b, join = create_sibling_graph(db_path)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    statuses = {node["id"]: node["status"] for node in studio_data["graph"]["nodes"]}

    assert statuses[root_a["id"]] == "in_progress"
    assert statuses[root_b["id"]] == "in_progress"
    assert statuses[join["id"]] == "blocked"
    assert studio_data["task"]["status"] == "in_progress"
    assert_event_types(
        studio_data["events"],
        ["approval.recorded", "subtask.scheduled", "subtask.scheduled"],
    )


def test_subtask_completion_unblocks_downstream_units(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    _, task, root_a, root_b, join = create_sibling_graph(db_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{root_a['id']}/transition",
            {"status": "complete", "actor": "Pravaha"},
        )
    )
    _, first_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    first_statuses = {node["id"]: node["status"] for node in first_snapshot["graph"]["nodes"]}
    assert first_statuses[join["id"]] == "blocked"

    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{root_b['id']}/transition",
            {"status": "complete", "actor": "Pravaha"},
        )
    )
    _, final_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    final_statuses = {node["id"]: node["status"] for node in final_snapshot["graph"]["nodes"]}

    assert final_statuses[root_a["id"]] == "complete"
    assert final_statuses[root_b["id"]] == "complete"
    assert final_statuses[join["id"]] == "queued"
    assert_event_types(
        final_snapshot["events"],
        ["subtask.transitioned", "subtask.transitioned", "subtask.unblocked"],
    )
    assert final_snapshot["task"]["status"] == "queued"
    assert final_snapshot["graph"]["coordination_state"] == "ready"


def test_subtask_completion_auto_schedules_newly_ready_units_when_policy_enabled(tmp_path):
    db_path = tmp_path / "sarathi.db"
    write_auto_schedule_policy(tmp_path)
    app = create_app(db_path)
    _, task, root_a, root_b, join = create_sibling_graph(db_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{root_a['id']}/transition",
            {"status": "complete", "actor": "Pravaha"},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{root_b['id']}/transition",
            {"status": "complete", "actor": "Pravaha"},
        )
    )

    _, final_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    final_statuses = {node["id"]: node["status"] for node in final_snapshot["graph"]["nodes"]}

    assert final_statuses[root_a["id"]] == "complete"
    assert final_statuses[root_b["id"]] == "complete"
    assert final_statuses[join["id"]] == "in_progress"
    assert final_snapshot["task"]["status"] == "in_progress"
    assert_event_types(
        final_snapshot["events"],
        ["subtask.transitioned", "subtask.unblocked", "subtask.scheduled"],
    )


def test_graph_snapshot_reports_fan_out_ready_frontier_before_schedule(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    _, task, root_a, root_b, join = create_sibling_graph(db_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))

    assert studio_data["graph"]["ready_nodes"] == [root_a["id"], root_b["id"]]
    assert studio_data["graph"]["fan_out_ready_nodes"] == [root_a["id"], root_b["id"]]
    assert studio_data["graph"]["fan_in_nodes"] == [join["id"]]
    assert studio_data["graph"]["coordination_state"] == "fan_out_ready"


def test_waiting_human_subtask_moves_task_into_waiting_human_coordination_state(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)
    _, task, root_a, root_b, join = create_sibling_graph(db_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{root_a['id']}/transition",
            {"status": "waiting_human", "actor": "Samanvaya", "reason": "Needs product clarification"},
        )
    )

    assert status == 200
    assert data["task"]["status"] == "waiting_human"
    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    statuses = {node["id"]: node["status"] for node in studio_data["graph"]["nodes"]}
    assert statuses[root_a["id"]] == "waiting_human"
    assert statuses[root_b["id"]] == "in_progress"
    assert statuses[join["id"]] == "blocked"
    assert studio_data["task"]["status"] == "waiting_human"
    assert studio_data["graph"]["waiting_human_nodes"] == [root_a["id"]]
    assert studio_data["graph"]["coordination_state"] == "waiting_human"


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
            {"prompt": "Run lifecycle scheduler.", "title": "Lifecycle scheduler"},
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


def create_sibling_graph(db_path):
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Sarathi App", root_path=str(db_path.parent))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Sibling scheduler",
            status="graph_pending",
            metadata={"phase": "graph_pending"},
        )
        root_a = storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=task["id"],
            title="Root A",
            status="queued",
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
        join = storage.create_subtask(
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
        return workspace, task, root_a, root_b, join


def assert_event_types(events, expected_subset):
    event_types = [event["event_type"] for event in events]
    for expected in expected_subset:
        assert expected in event_types


def write_auto_schedule_policy(root):
    policy_pack = root / "policy-pack"
    policy_pack.mkdir(parents=True, exist_ok=True)
    (policy_pack / "task-tracking.md").write_text(
        """# Policy Pack: Task Tracking

```yaml
graph_execution:
  auto_schedule_ready_nodes: true
```
"""
    )
