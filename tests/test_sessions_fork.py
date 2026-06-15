"""Service-layer tests for session forking (T4.2), including NCP seeding."""

import stat

from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-sessions-fork"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-sessions-fork"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def create_workspace(app, root_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Fork App", "root_path": str(root_path)},
        )
    )
    return workspace_data["workspace"]


def create_task(app, root_path):
    workspace = create_workspace(app, root_path)
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/task-drafts",
            {"prompt": "Fork a session.", "title": "Fork task"},
        )
    )
    return draft_data["task"]


def create_session(app, root_path, *, owner="local"):
    task = create_task(app, root_path)
    status, data = assert_ok(
        request(app, "POST", f"/api/tasks/{task['id']}/sessions", {"owner": owner})
    )
    assert status == 201
    return task, data["session"]


def _post_driver_message(app, session_id, *, user, content):
    # The owner participant is a driver-equivalent owner; post as the owner.
    return assert_ok(
        request(
            app,
            "POST",
            f"/api/sessions/{session_id}/messages",
            {"user": user, "content": content},
        )
    )


def _write_ncp_run_stub(workspace_root):
    """Write a minimal `.ncp/` bridge: config + an executable run.py stub."""
    ncp_dir = workspace_root / ".ncp"
    ncp_dir.mkdir(parents=True, exist_ok=True)
    (ncp_dir / "config.toml").write_text("[store]\ntype = 'sqlite'\n", encoding="utf-8")
    script = ncp_dir / "run.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "command = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if command == 'status':\n"
        "    sys.exit(0)\n"
        "elif command == 'fetch':\n"
        "    print('chunk:prior-1')\n"
        "    print('  {\"note\": \"parent run found X\"}')\n"
        "    sys.exit(0)\n"
        "elif command == 'write_memory':\n"
        "    sys.exit(0)\n"
        "elif command == 'log_cost':\n"
        "    sys.exit(0)\n"
        "else:\n"
        "    sys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_fork_creates_independent_task(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    source_task, session = create_session(app, tmp_path, owner="alice")

    status, data = assert_ok(
        request(app, "POST", f"/api/sessions/{session['id']}/fork", {})
    )
    assert status == 201
    assert data["task"]["id"] != source_task["id"]
    assert data["task"]["metadata"]["fork"]["forked_from_task"] == source_task["id"]
    assert data["task"]["metadata"]["fork"]["forked_from_session"] == session["id"]


def test_fork_creates_new_session_with_owner(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    _, data = assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    new_session_id = data["session"]["id"]

    _, detail = assert_ok(request(app, "GET", f"/api/sessions/{new_session_id}"))
    owners = [p for p in detail["participants"] if p["role"] == "owner"]
    assert len(owners) == 1
    assert owners[0]["user"] == "alice"


def test_fork_copies_message_history(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")
    _post_driver_message(app, session["id"], user="alice", content="hello fork")

    _, data = assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    assert data["messages_copied"] == 1

    new_session_id = data["session"]["id"]
    _, msgs = assert_ok(request(app, "GET", f"/api/sessions/{new_session_id}/messages"))
    contents = [m["content"] for m in msgs["messages"]]
    assert "hello fork" in contents
    forked = [m for m in msgs["messages"] if m["metadata"].get("forked_from_message")]
    assert forked


def test_fork_creates_checkpoint(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path)

    _, data = assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    assert data["checkpoint"]["id"]


def test_fork_missing_session_404(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    status, payload = request(app, "POST", "/api/sessions/does-not-exist/fork", {})
    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_fork_logs_lifecycle_event(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    source_task, session = create_session(app, tmp_path)

    assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    _, studio = assert_ok(request(app, "GET", f"/api/tasks/{source_task['id']}/studio"))
    event_types = [e["event_type"] for e in studio["events"]]
    assert "session.forked" in event_types


def test_fork_without_ncp_omits_ncp_block(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path)

    _, data = assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    assert "ncp" not in data


def test_fork_with_ncp_seeds_memory(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    # The workspace root_path is tmp_path; place the NCP bridge there.
    _write_ncp_run_stub(tmp_path)
    _, session = create_session(app, tmp_path)

    _, data = assert_ok(request(app, "POST", f"/api/sessions/{session['id']}/fork", {}))
    assert data["ncp"]["config_present"] is True
    assert data["ncp"]["available"] is True
    assert data["ncp"]["seed_written"] is True
    assert data["ncp"]["parent_findings_carried"] >= 1
    # The carried findings are baked into the new task's metadata.
    seed = data["task"]["metadata"]["fork"]["ncp_seed_findings"]
    assert any("parent run found X" in finding for finding in seed)
