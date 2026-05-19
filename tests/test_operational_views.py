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


def test_workspace_operational_views_aggregate_token_budget_from_dispatch_metadata(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{task['workspace_id']}/operational-views")
    )

    assert status == 200
    assert data["usage"]["budget"]["total_tokens"] > 0
    assert data["usage"]["budget"]["budget_limit"] is None or data["usage"]["budget"]["budget_limit"] >= data["usage"]["budget"]["total_tokens"]
    assert data["usage"]["budget"]["budget_remaining"] is None or data["usage"]["budget"]["budget_remaining"] >= 0
    assert data["usage"]["budget"]["budget_state"] in {"ok", "warning", "near_limit", "exhausted", "unknown"}
    assert data["usage"]["budget"]["usage_source"] in {"reported", "estimated", "mixed"}


def test_workspace_operational_views_include_governance_summary(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    workspace_id = task["workspace_id"]

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {
                "metadata": {
                    "repository_action_preference": {
                        "scope": "workspace",
                        "mode": "draft_pr",
                    },
                    "auto_approve_preference": {
                        "scope": "workspace",
                        "mode": "below_threshold",
                    },
                    "provider_priority": ["codex", "claude"],
                }
            },
        )
    )

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/operational-views")
    )

    assert status == 200
    governance = data["governance"]
    assert governance["policy_posture"]["repository_action_preference"]["mode"] == "draft_pr"
    assert governance["policy_posture"]["auto_approve_preference"]["mode"] == "below_threshold"
    assert governance["policy_posture"]["provider_priority"] == ["codex", "claude", "copilot", "opencode"]
    assert governance["provider_routing"]["priority_order"][0] == "codex"
    assert governance["provider_routing"]["selected_provider"] in {"codex", "claude", "copilot", "opencode", "local"}
    assert governance["override_history"]
    assert any(item["event_type"] == "workspace.governance_updated" for item in governance["override_history"])
    assert governance["repository_action_governance"]["approved_count"] >= 1
    assert governance["repository_action_governance"]["recent"]


def test_workspace_operational_views_requires_existing_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, payload = request(app, "GET", "/api/workspaces/missing/operational-views")

    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_workspace_operational_views_surface_project_summaries(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    from tests.test_service_api import assert_ok as api_assert_ok, request as api_request

    _, ws = api_assert_ok(
        api_request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = ws["workspace"]["id"]

    _, proj1 = api_assert_ok(
        api_request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Project Alpha"},
        )
    )
    project1_id = proj1["project"]["id"]

    api_assert_ok(
        api_request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Task for Alpha", "context": {"projectId": project1_id}},
        )
    )

    _, proj2 = api_assert_ok(
        api_request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/projects",
            {"name": "Project Beta"},
        )
    )
    project2_id = proj2["project"]["id"]

    api_assert_ok(
        api_request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Task for Beta", "context": {"projectId": project2_id}},
        )
    )
    api_assert_ok(
        api_request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Second task for Beta", "context": {"projectId": project2_id}},
        )
    )

    status, data = api_assert_ok(
        api_request(app, "GET", f"/api/workspaces/{workspace_id}/operational-views")
    )

    assert status == 200
    assert "projects" in data

    proj_summaries = {p["id"]: p for p in data["projects"]}
    assert project1_id in proj_summaries
    assert project2_id in proj_summaries
    assert proj_summaries[project1_id]["task_count"] == 1
    assert proj_summaries[project2_id]["task_count"] == 2


def test_workspace_operational_views_include_attention_inbox(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    from src.storage import Storage, connect, run_migrations

    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    _, approval_task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Approval task", "title": "Approval task"},
        )
    )
    approval_task = approval_task_data["task"]

    _, checkpoint_task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Checkpoint task", "title": "Checkpoint task"},
        )
    )
    checkpoint_task = checkpoint_task_data["task"]

    _, handoff_task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Handoff task", "title": "Handoff task"},
        )
    )
    handoff_task = handoff_task_data["task"]

    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_approval_gate(
            workspace_id=workspace_id,
            task_id=approval_task["id"],
            name="Review",
            status="pending",
            metadata={"requires_human": True},
        )
        storage.create_checkpoint_capsule(
            workspace_id=workspace_id,
            project_id=None,
            task_id=checkpoint_task["id"],
            status="ready",
            summary="Resume from here.",
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
        storage.create_handoff(
            workspace_id=workspace_id,
            task_id=handoff_task["id"],
            summary="Ready for handoff review.",
            metadata={},
        )

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/operational-views")
    )

    assert status == 200
    assert "inbox" in data
    kinds = [item["kind"] for item in data["inbox"]]
    assert "approval" in kinds
    assert "checkpoint_ready" in kinds
    assert "handoff_ready" in kinds
    assert data["summary"]["approvals_pending"] >= 1


def test_inbox_projection_groups_attention_items(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_id, task_id = seed_attention_scenario(app, tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/operational-views")
    )

    assert status == 200
    assert "inbox" in data
    inbox = data["inbox"]
    inbox_kinds = {item["kind"] for item in inbox}

    assert "approval" in inbox_kinds
    assert "checkpoint_ready" in inbox_kinds
    assert "handoff_ready" in inbox_kinds

    approval_items = [item for item in inbox if item["kind"] == "approval"]
    assert any(item["task_id"] == task_id for item in approval_items)

    checkpoint_items = [item for item in inbox if item["kind"] == "checkpoint_ready"]
    assert any(item["task_id"] == task_id for item in checkpoint_items)

    handoff_items = [item for item in inbox if item["kind"] == "handoff_ready"]
    assert any(item["task_id"] == task_id for item in handoff_items)


def seed_attention_scenario(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Attention", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Create attention scenario.", "title": "Attention Task"},
        )
    )
    task_id = draft_data["task"]["id"]

    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task_id}/graph-draft"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task_id}/schedule"))
    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/studio"))
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
            f"/api/tasks/{task_id}/reviews/run",
            {"review_type": "functional"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task_id}/handoff"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/repository-action",
            {"action": "no_action", "approved": True},
        )
    )

    return workspace_id, task_id


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
