from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-reuse"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-reuse"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    return status, payload["data"]


def test_workspace_reuse_kit_includes_templates_and_saved_views(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_data['workspace']['id']}/reuse-kit")
    )

    assert status == 200
    assert data["workspace_id"] == workspace_data["workspace"]["id"]
    assert data["active_saved_view_id"] == "all-projects"
    assert [template["id"] for template in data["templates"]] == [
        "feature-delivery",
        "bugfix-regression",
        "governed-release-handoff",
        "provider-recovery",
    ]
    assert any(view["id"] == "all-projects" for view in data["saved_views"])
    assert any(view["id"] == "approvals-inbox" for view in data["saved_views"])
    assert any(view["id"] == "provider-posture" for view in data["saved_views"])
    assert data["playbooks"] == []


def test_workspace_knowledge_center_reports_real_files_and_context_bundles(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    populate_workspace_knowledge_root(tmp_path)
    seed_workspace_proposal_decision(task["workspace_id"], tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{task['workspace_id']}/knowledge-center")
    )

    assert status == 200
    assert data["guide"]["status"] == "complete"
    assert data["learnings"]["status"] == "populated"
    assert len(data["wiki"]) == 2
    assert data["skills"]["family_count"] == 2
    assert data["skills"]["skill_count"] == 3
    assert data["recent_contexts"]["total_bundles"] >= 1
    assert data["recent_contexts"]["bundles"][0]["agent"]
    assert data["proposals"]["pending_count"] >= 0
    assert data["proposals"]["accepted_count"] == 1
    assert data["proposals"]["rejected_count"] == 0
    assert data["proposals"]["last_reviewed_at"] is not None
    assert data["learnings"]["accepted_learnings"]
    assert data["learnings"]["accepted_learnings"][0]["recommended_template_id"]
    assert isinstance(data["learnings"]["accepted_learnings"][0]["recommended_view_ids"], list)
    assert data["learnings"]["accepted_learnings"][0]["linked_proposal_id"]
    assert data["learnings"]["accepted_learnings"][0]["linked_playbook_id"]


def test_workspace_wiki_and_context_bundle_endpoints_are_readable(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    populate_workspace_knowledge_root(tmp_path)
    workspace_id = task["workspace_id"]

    status, wiki_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/wiki"))
    assert status == 200
    assert [page["path"] for page in wiki_data["pages"]] == ["README.md", "guides/setup.md"]

    status, page_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/wiki/guides%2Fsetup"))
    assert status == 200
    assert page_data["page"] == "guides/setup"
    assert "Setup Guide" in page_data["content"]

    status, skills_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/skills"))
    assert status == 200
    assert [skill["name"] for skill in skills_data["skills"]] == [
        "typescript-generator",
        "python-generator",
        "security-reviewer",
    ]
    assert skills_data["skills"][0]["family"] == "code_generation"

    status, bundles_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/context-bundles"))
    assert status == 200
    assert len(bundles_data["bundles"]) >= 1
    bundle = bundles_data["bundles"][0]
    assert bundle["context_pack"]["agent_input"]["objective"]
    assert isinstance(bundle["context_pack"]["agent_input"]["constraints"], list)
    assert "context_pack" in bundle["provenance"]["sources"]
    assert "agent_output" in bundle["provenance"]["sources"]
    assert "artifact_index" in bundle["provenance"]["sources"]


def test_workspace_wiki_page_can_be_saved_and_read_back(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    workspace_id = task["workspace_id"]

    status, saved = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/wiki",
            {"page": "guides/runtime", "content": "# Runtime Guide\n\nKeep context packs compact.\n"},
        )
    )

    assert status == 200
    assert saved["page"] == "guides/runtime"
    assert saved["path"].endswith("wiki/guides/runtime.md")

    status, page_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/wiki/guides%2Fruntime"))
    assert status == 200
    assert "Keep context packs compact." in page_data["content"]

    status, wiki_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/wiki"))
    assert status == 200
    assert any(page["path"] == "guides/runtime.md" for page in wiki_data["pages"])


def test_workspace_skills_pack_can_be_saved_and_read_back(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    populate_workspace_knowledge_root(tmp_path)
    workspace_id = task["workspace_id"]
    next_content = """# Policy Pack: Skill Routing

## Skill Families
```yaml
code_generation:
  description: "Generate code from specs"
  skills:
    - typescript-generator
    - python-generator

qa_review:
  description: "Review delivery quality"
  skills:
    - qa-advocate
```

## Task Type Routing
```yaml
task_type_to_skill:
  implementation:
    primary: "codex"
    secondary: ["local"]
    always_invoke: false
  code_review:
    primary: "codex"
    always_invoke: true
  analysis:
    primary: "local"
    secondary:
      - "codex"
      - "claude"
```
"""

    status, saved = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/skills",
            {"content": next_content},
        )
    )

    assert status == 200
    assert saved["path"].endswith("policy-pack/skills.md")
    assert saved["source_content"] == next_content
    assert any(skill["name"] == "qa-advocate" for skill in saved["skills"])
    assert len(saved["routes"]) == 3
    impl_route = next((r for r in saved["routes"] if r["task_type"] == "implementation"), None)
    assert impl_route is not None
    assert impl_route["primary"] == "codex"
    assert impl_route["secondary"] == ["local"]
    assert impl_route["always_invoke"] is False
    analysis_route = next((r for r in saved["routes"] if r["task_type"] == "analysis"), None)
    assert analysis_route is not None
    assert analysis_route["secondary"] == ["codex", "claude"]
    assert "role_mappings" in saved
    assert len(saved["role_mappings"]) >= 5
    assert any(item["role"] == "Pravaha" and item["phase"] == "Build" for item in saved["role_mappings"])
    assert any(item["role"] == "Nirnaya" and item["phase"] == "Review" for item in saved["role_mappings"])
    assert "behavior_assets" in saved
    assert len(saved["behavior_assets"]) >= 4
    assert any(a["path"] == "policy-pack/skills.md" and a["exists"] for a in saved["behavior_assets"])

    status, refreshed = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/skills"))
    assert status == 200
    assert refreshed["source_content"] == next_content
    assert any(skill["family"] == "qa_review" for skill in refreshed["skills"])
    assert len(refreshed["routes"]) == 3
    assert "role_mappings" in refreshed
    assert "behavior_assets" in refreshed


def test_workspace_reuse_kit_promotes_accepted_learning_into_playbook(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_completed_task(app, tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{task['workspace_id']}/dogfood-learning",
            {"approved": True},
        )
    )

    status, data = assert_ok(
        request(app, "GET", f"/api/workspaces/{task['workspace_id']}/reuse-kit")
    )

    assert status == 200
    assert len(data["playbooks"]) == 1
    playbook = data["playbooks"][0]
    assert playbook["source"] == "accepted_learning"
    assert playbook["recommended_template_id"] == "governed-release-handoff"
    assert playbook["provenance"]["task_id"] == task["id"]
    assert playbook["provenance"]["source_file"].endswith("learnings.md")
    assert "handoff-readiness" in playbook["recommended_view_ids"]


def test_workspace_reuse_kit_remembers_active_saved_view(tmp_path):
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

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/workspaces/{workspace_id}",
            {"metadata": {"reuse_preferences": {"active_saved_view_id": "blocked-projects"}}},
        )
    )

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/reuse-kit"))

    assert status == 200
    assert data["active_saved_view_id"] == "blocked-projects"


def test_workspace_reuse_kit_includes_custom_saved_views(tmp_path):
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
                    "reuse_preferences": {
                        "active_saved_view_id": "team-handoffs",
                        "custom_saved_views": [
                            {
                                "id": "team-handoffs",
                                "name": "Team handoffs",
                                "role": "qa",
                                "route": "workspace",
                                "description": "Custom handoff posture for the team.",
                                "metric_label": "ready handoffs",
                                "filters": {"task_state": "handoff_ready"},
                            }
                        ],
                    }
                }
            },
        )
    )

    status, data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/reuse-kit"))

    assert status == 200
    assert data["active_saved_view_id"] == "team-handoffs"
    custom_view = next(view for view in data["saved_views"] if view["id"] == "team-handoffs")
    assert custom_view["origin"] == "custom"
    assert custom_view["count"] >= 1
    assert custom_view["filters"]["task_state"] == "handoff_ready"


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
            {"prompt": "Dogfood Sarathi with its own task loop.", "title": "Sarathi dogfood"},
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


def populate_workspace_knowledge_root(root_path):
    (root_path / "wiki" / "guides").mkdir(parents=True, exist_ok=True)
    (root_path / "policy-pack").mkdir(parents=True, exist_ok=True)
    (root_path / "SARATHI.md").write_text("# Sarathi\n", encoding="utf-8")
    (root_path / "coding-standards.md").write_text("# Coding standards\n", encoding="utf-8")
    (root_path / "guidelines.md").write_text("# Guidelines\n", encoding="utf-8")
    (root_path / "learnings.md").write_text("## Accepted learnings\n\n- Keep context packs compact.\n", encoding="utf-8")
    (root_path / "wiki" / "README.md").write_text("# Wiki Home\n", encoding="utf-8")
    (root_path / "wiki" / "guides" / "setup.md").write_text("# Setup Guide\n", encoding="utf-8")
    (root_path / "policy-pack" / "skills.md").write_text(
        """# Policy Pack: Skill Routing

## Skill Families
```yaml
code_generation:
  description: "Generate code from specs"
  skills:
    - typescript-generator
    - python-generator

code_review:
  description: "Review code quality"
  skills:
    - security-reviewer
```
""",
        encoding="utf-8",
    )
    (root_path / "policy-pack" / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: pytest
```
""",
        encoding="utf-8",
    )
    (root_path / "policy-pack" / "model-routing.md").write_text(
        "# Model routing\n",
        encoding="utf-8",
    )
    (root_path / "policy-pack" / "escalation.md").write_text(
        "# Escalation\n",
        encoding="utf-8",
    )


def seed_workspace_proposal_decision(workspace_id, root_path):
    from src.evolve import Evolver, ProposalReviewStore
    from src.storage import Storage, connect

    db_path = root_path / "sarathi.db"
    with connect(db_path) as conn:
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Proposal signal task",
            description=None,
            metadata={"complexity": "high"},
        )
        subtask = storage.create_subtask(
            workspace_id=workspace_id,
            task_id=task["id"],
            title="Failing implementation lane",
            status="failed",
            metadata={"role": "Pravaha"},
        )
        storage.create_dispatch(
            workspace_id=workspace_id,
            task_id=task["id"],
            agent_name="codex",
            status="failed",
            metadata={
                "subtask_id": subtask["id"],
                "agent_output": {"status": "failed", "summary": "codex failed during Build"},
            },
        )
        records = [
            {
                "task_id": task["id"],
                "complexity": "high",
                "generated_at": str(task.get("updated_at") or task.get("created_at") or ""),
                "summary": "Workspace proposal synthesis for proposal signal task",
                "repeated_failures": [{"phase": "Build", "count": 1}],
                "provider_failures": [{"phase": "Build", "provider": "codex", "count": 1}],
                "escalations": [],
                "iteration_hotspots": [],
                "phase_outcomes": [],
            },
            {
                "task_id": f"{task['id']}-2",
                "complexity": "high",
                "generated_at": str(task.get("updated_at") or task.get("created_at") or ""),
                "summary": "Workspace proposal synthesis for second signal",
                "repeated_failures": [{"phase": "Build", "count": 1}],
                "provider_failures": [{"phase": "Build", "provider": "codex", "count": 1}],
                "escalations": [],
                "iteration_hotspots": [],
                "phase_outcomes": [],
            },
        ]
    (root_path / "learnings.md").write_text(
        "\n".join(
            [
                "## Accepted: Keep context packs compact",
                "",
                f"- Task: {task['id']}",
                "- Summary: Build retries should stay compact and evidence-backed.",
                "- Tags: debugging, workflow",
                f"- Evidence: failing build ({task['id']}:repeated_failures:Build, {task['id']}:provider_failures:Build:codex)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    proposals = Evolver().generate_policy_proposals(learning_records=records)
    target = proposals[0] if proposals else None
    assert target is not None
    decision = ProposalReviewStore(root_path / "policy-pack").accept(target)
    return decision
