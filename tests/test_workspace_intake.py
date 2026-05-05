import subprocess

from src.service import create_app
from src.storage import Storage, connect, run_migrations


def request(app, method, path, body=None, correlation_id="corr-intake"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-intake"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-intake"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def test_storage_can_attach_and_list_workspace_repositories(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(
            name="Sarathi Desktop",
            root_path=str(tmp_path),
        )

        repository = storage.create_workspace_repository(
            workspace_id=workspace["id"],
            name="Sarathi",
            path=str(tmp_path / "Sarathi"),
            remote_url="git@example.com:sarathi.git",
            metadata={"intake_mode": "existing_repo"},
        )

        assert repository["id"]
        assert repository["workspace_id"] == workspace["id"]
        assert repository["name"] == "Sarathi"
        assert repository["path"] == str(tmp_path / "Sarathi")
        assert repository["remote_url"] == "git@example.com:sarathi.git"
        assert repository["metadata"] == {"intake_mode": "existing_repo"}
        assert storage.list_workspace_repositories(workspace["id"]) == [repository]


def test_service_previews_existing_git_repo_without_mutating_it(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "app.py").write_text("print('sarathi')\n", encoding="utf-8")
    (repo_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    before = sorted(path.relative_to(repo_path).as_posix() for path in repo_path.rglob("*"))

    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/preview",
            {"path": str(repo_path)},
        )
    )

    assert status == 200
    preview = data["preview"]
    assert preview["path"] == str(repo_path)
    assert preview["name"] == "repo"
    assert preview["exists"] is True
    assert preview["is_directory"] is True
    assert preview["is_git_repo"] is True
    assert preview["branch"] == "main"
    assert preview["dirty"] is True
    assert preview["changes"] == ["?? app.py", "?? requirements.txt"]
    assert preview["sarathi_initialized"] is False
    assert preview["recommended_mode"] == "existing_repo"
    assert preview["requires_interview"] is False
    assert preview["inspection"]["languages"] == ["Python"]
    assert "SARATHI.md" in preview["bootstrap"]["missing_files"]
    assert preview["bootstrap"]["status"] == "not_initialized"
    assert "policy-pack/complexity.md" in preview["would_create"]
    after = sorted(path.relative_to(repo_path).as_posix() for path in repo_path.rglob("*"))
    assert after == before


def test_service_previews_missing_repo_as_interview_required_without_creating_it(tmp_path):
    repo_path = tmp_path / "brand-new"
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/preview",
            {"path": str(repo_path)},
        )
    )

    assert status == 200
    preview = data["preview"]
    assert preview["exists"] is False
    assert preview["is_directory"] is False
    assert preview["is_git_repo"] is False
    assert preview["recommended_mode"] == "new_repo"
    assert preview["requires_interview"] is True
    assert "Repository path does not exist yet." in preview["warnings"]
    assert not repo_path.exists()


def test_service_requires_approval_before_attaching_repository(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    assert_error(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path)},
        ),
        status=409,
        code="approval_required",
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path), "approved": True},
        )
    )

    assert status == 201
    repository = data["repository"]
    assert repository["workspace_id"] == workspace_id
    assert repository["path"] == str(repo_path)
    assert repository["metadata"]["intake"]["recommended_mode"] == "directory"
    _, list_data = assert_ok(
        request(app, "GET", f"/api/workspaces/{workspace_id}/repositories")
    )
    assert list_data["repositories"] == [repository]

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    assert events_data["events"][-1]["event_type"] == "workspace.repository.attached"
    assert events_data["events"][-1]["object_id"] == repository["id"]


def test_service_initializes_attached_existing_repo_only_after_approval(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, attach_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path), "approved": True},
        )
    )
    repository = attach_data["repository"]

    assert_error(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/{repository['id']}/initialize",
            {},
        ),
        status=409,
        code="approval_required",
    )
    assert not (repo_path / "SARATHI.md").exists()

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/{repository['id']}/initialize",
            {"approved": True},
        )
    )

    assert status == 201
    initialization = data["initialization"]
    assert initialization["status"] == "completed"
    assert initialization["mode"] == "existing_repo"
    assert "SARATHI.md" in initialization["created_files"]
    assert "policy-pack/complexity.md" in initialization["created_files"]
    assert "policy-pack/task-tracking.md" in initialization["created_files"]
    assert (repo_path / "SARATHI.md").exists()
    assert (repo_path / "wiki" / "README.md").exists()
    assert (repo_path / "policy-pack" / "commands.md").exists()
    assert (repo_path / "policy-pack" / "complexity.md").exists()
    assert (repo_path / "policy-pack" / "task-tracking.md").exists()
    assert data["repository"]["metadata"]["sarathi_initialization"]["status"] == "completed"

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    assert events_data["events"][-1]["event_type"] == "workspace.repository.initialized"


def test_service_interviews_before_initializing_brand_new_repo(tmp_path):
    repo_path = tmp_path / "brand-new"
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, attach_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path), "approved": True},
        )
    )
    repository = attach_data["repository"]

    assert_error(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/{repository['id']}/initialize",
            {"approved": True},
        ),
        status=409,
        code="interview_required",
    )
    assert not repo_path.exists()

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/{repository['id']}/initialize",
            {
                "approved": True,
                "interview": {
                    "project_name": "Brand New",
                    "purpose": "A demo-safe Sarathi initialized project.",
                    "primary_language": "Python",
                },
            },
        )
    )

    assert status == 201
    assert repo_path.exists()
    assert (repo_path / "guidelines.md").exists()
    assert (repo_path / "wiki" / "architecture.md").exists()
    assert (repo_path / "policy-pack" / "model-routing.md").exists()
    assert "A demo-safe Sarathi initialized project." in (repo_path / "SARATHI.md").read_text()
    assert data["initialization"]["mode"] == "new_repo"
    assert data["repository"]["metadata"]["sarathi_initialization"]["interview"]["project_name"] == "Brand New"


def test_service_initialization_preserves_existing_repo_docs_and_fills_missing_bootstrap_files(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "SARATHI.md").write_text("# Custom context\n", encoding="utf-8")
    (repo_path / "policy-pack").mkdir()
    (repo_path / "policy-pack" / "review.md").write_text("# Custom review\n", encoding="utf-8")
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi Desktop", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, attach_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path), "approved": True},
        )
    )
    repository = attach_data["repository"]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories/{repository['id']}/initialize",
            {"approved": True},
        )
    )

    assert status == 201
    initialization = data["initialization"]
    assert "SARATHI.md" in initialization["preserved_files"]
    assert "policy-pack/review.md" in initialization["preserved_files"]
    assert "wiki/development.md" in initialization["created_files"]
    assert "policy-pack/complexity.md" in initialization["created_files"]
    assert initialization["bootstrap"]["status"] == "partial"
    assert (repo_path / "SARATHI.md").read_text(encoding="utf-8") == "# Custom context\n"
    assert (repo_path / "policy-pack" / "review.md").read_text(encoding="utf-8") == "# Custom review\n"
    assert (repo_path / "policy-pack" / "skills.md").exists()
