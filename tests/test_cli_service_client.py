"""Tests for CLI service-client mode (item 1.4-C of IMPLEMENTATION-PLAN):

- `sarathi list --all` merges file-store tasks with service tasks and
  dedupes engine-mirrored runs.
- `sarathi status <id>` / `sarathi log <id>` fall through to the service
  when the id isn't a known file-store task.
- `sarathi run --remote` submits to the service instead of running the
  engine in-process, with workspace resolution (flag / cwd-match / single
  workspace / ambiguous error).
- `sarathi pr-body <task-id>` prints (and optionally writes) the PR body.

No real sockets are used: the service HTTP seam
(`_read_service_discovery` / `_service_auth_token` / `_service_get_json` /
`_service_post_json`) is faked the same way `tests/test_cli_watch_follow.py`
fakes it.
"""
from argparse import Namespace

import pytest

from src import cli
from src.engine import PersistenceManager


def _use_persistence(monkeypatch, persistence) -> None:
    monkeypatch.setattr(cli, "PersistenceManager", lambda: persistence, raising=False)


# ---------------------------------------------------------------------------
# sarathi list --all
# ---------------------------------------------------------------------------


def test_list_all_service_down_prints_file_store_only(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    cli.handle_list_tasks(Namespace(all=True))

    out = capsys.readouterr().out
    assert "No saved tasks" in out
    assert "service not running" in out


def test_list_no_all_flag_does_not_touch_service(tmp_path, monkeypatch, capsys):
    """Default `sarathi list` (no --all) must never call the service."""
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)

    def _boom():
        raise AssertionError("service discovery should not be consulted without --all")

    monkeypatch.setattr(cli, "_read_service_discovery", _boom)

    cli.handle_list_tasks(Namespace(all=False))

    out = capsys.readouterr().out
    assert "No saved tasks" in out
    assert "Service tasks" not in out


def test_list_all_merges_and_dedupes_engine_mirrored_tasks(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    from src.engine import Complexity, TaskContext

    persistence.save_task(
        TaskContext(task_id="engine-task-1", description="File-store task", complexity=Complexity.LOW)
    )
    _use_persistence(monkeypatch, persistence)

    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        if path == "/api/workspaces":
            return {"workspaces": [{"id": "ws-1", "name": "Default"}]}
        if path == "/api/workspaces/ws-1/tasks":
            return {
                "tasks": [
                    {
                        "id": "svc-task-mirrored",
                        "title": "File-store task",
                        "description": "File-store task",
                        "status": "in_progress",
                        "metadata": {"engine_task_id": "engine-task-1", "mirrored_from": "engine"},
                    },
                    {
                        "id": "svc-task-native",
                        "title": "Service-only task",
                        "description": "Created straight through the service",
                        "status": "pending",
                        "metadata": {},
                    },
                ]
            }
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_list_tasks(Namespace(all=True))

    out = capsys.readouterr().out
    assert "engine-task-1" in out
    assert "Service tasks:" in out
    assert "svc-task-native" in out
    assert "Service-only task" in out
    # The engine-mirrored duplicate must not appear in the service section.
    assert "svc-task-mirrored" not in out


def test_list_all_service_unreachable_notes_failure(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_list_tasks(Namespace(all=True))

    out = capsys.readouterr().out
    assert "failed to reach Sarathi service" in out


# ---------------------------------------------------------------------------
# status / log fallthrough
# ---------------------------------------------------------------------------


def test_status_fallthrough_hits_service_task(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)

    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        if path == "/api/tasks/svc-123":
            return {
                "task": {
                    "id": "svc-123",
                    "title": "Add OAuth2",
                    "description": "Implement OAuth2 login",
                    "status": "in_progress",
                    "workspace_id": "ws-1",
                    "metadata": {},
                }
            }
        if path == "/api/events?task_id=svc-123":
            return {
                "events": [
                    {"event_type": "task.created", "created_at": "2026-07-01T00:00:00Z"},
                    {"event_type": "phase.completed", "created_at": "2026-07-01T00:05:00Z"},
                ]
            }
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_status(Namespace(task_id="svc-123"))

    out = capsys.readouterr().out
    assert "svc-123" in out
    assert "Add OAuth2" in out
    assert "in_progress" in out
    assert "Lifecycle Events: 2" in out


def test_status_fallthrough_miss_falls_back_to_not_found(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)

    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    import urllib.error

    def _fake_get_json(service_url, path, *, token=None):
        raise urllib.error.HTTPError(service_url + path, 404, "Not Found", {}, None)

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_status(Namespace(task_id="does-not-exist"))

    out = capsys.readouterr().out
    assert "Task does-not-exist not found" in out


def test_status_no_service_falls_back_to_not_found(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    cli.handle_status(Namespace(task_id="ghost"))

    out = capsys.readouterr().out
    assert "Task ghost not found" in out


def test_log_fallthrough_hits_service_task(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)

    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        if path == "/api/tasks/svc-456":
            return {
                "task": {
                    "id": "svc-456",
                    "title": "Refactor auth",
                    "description": "",
                    "status": "done",
                    "workspace_id": "ws-1",
                    "metadata": {"engine_task_id": "eng-456"},
                }
            }
        if path == "/api/events?task_id=svc-456":
            return {"events": [{"event_type": "task.completed", "created_at": "t2", "payload": {}}]}
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_log(Namespace(task_id="svc-456"))

    out = capsys.readouterr().out
    assert "svc-456" in out
    assert "Refactor auth" in out
    assert "task.completed" in out


def test_log_fallthrough_miss_falls_back_to_not_found(tmp_path, monkeypatch, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    _use_persistence(monkeypatch, persistence)

    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    import urllib.error

    def _fake_get_json(service_url, path, *, token=None):
        raise urllib.error.HTTPError(service_url + path, 404, "Not Found", {}, None)

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_log(Namespace(task_id="nope"))

    out = capsys.readouterr().out
    assert "Task nope not found" in out


# ---------------------------------------------------------------------------
# run --remote
# ---------------------------------------------------------------------------


def _run_args(**overrides):
    base = dict(
        task_description="Add search filters",
        remote=True,
        workspace=None,
    )
    base.update(overrides)
    return Namespace(**base)


def test_run_remote_no_service_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_run(_run_args())
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Sarathi desktop service not running" in out


def test_run_remote_uses_explicit_workspace_flag(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        assert path == "/api/workspaces"
        return {
            "workspaces": [
                {"id": "ws-a", "name": "A", "root_path": "/repo/a"},
                {"id": "ws-b", "name": "B", "root_path": "/repo/b"},
            ]
        }

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    posted = {}

    def _fake_post_json(service_url, path, body, *, token=None):
        posted["path"] = path
        posted["body"] = body
        return {"task": {"id": "task-999"}}

    monkeypatch.setattr(cli, "_service_post_json", _fake_post_json)

    cli.handle_run(_run_args(workspace="ws-b"))

    assert posted["path"] == "/api/workspaces/ws-b/tasks"
    assert posted["body"]["title"] == "Add search filters"

    out = capsys.readouterr().out
    assert "task-999" in out
    assert "sarathi watch task-999 --follow" in out


def test_run_remote_resolves_workspace_by_cwd_match(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")
    monkeypatch.setattr(cli.os, "getcwd", lambda: "/repo/b")

    def _fake_get_json(service_url, path, *, token=None):
        return {
            "workspaces": [
                {"id": "ws-a", "name": "A", "root_path": "/repo/a"},
                {"id": "ws-b", "name": "B", "root_path": "/repo/b"},
            ]
        }

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    posted = {}

    def _fake_post_json(service_url, path, body, *, token=None):
        posted["path"] = path
        return {"task": {"id": "task-cwd"}}

    monkeypatch.setattr(cli, "_service_post_json", _fake_post_json)

    cli.handle_run(_run_args())

    assert posted["path"] == "/api/workspaces/ws-b/tasks"
    out = capsys.readouterr().out
    assert "task-cwd" in out


def test_run_remote_resolves_single_workspace(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")
    monkeypatch.setattr(cli.os, "getcwd", lambda: "/somewhere/else")

    def _fake_get_json(service_url, path, *, token=None):
        return {"workspaces": [{"id": "ws-only", "name": "Only", "root_path": "/repo/only"}]}

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    posted = {}

    def _fake_post_json(service_url, path, body, *, token=None):
        posted["path"] = path
        return {"task": {"id": "task-only"}}

    monkeypatch.setattr(cli, "_service_post_json", _fake_post_json)

    cli.handle_run(_run_args())

    assert posted["path"] == "/api/workspaces/ws-only/tasks"


def test_run_remote_ambiguous_workspace_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")
    monkeypatch.setattr(cli.os, "getcwd", lambda: "/somewhere/else")

    def _fake_get_json(service_url, path, *, token=None):
        return {
            "workspaces": [
                {"id": "ws-a", "name": "A", "root_path": "/repo/a"},
                {"id": "ws-b", "name": "B", "root_path": "/repo/b"},
            ]
        }

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_run(_run_args())
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Multiple workspaces found" in out
    assert "ws-a" in out
    assert "ws-b" in out


def test_run_remote_unknown_workspace_flag_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        return {"workspaces": [{"id": "ws-a", "name": "A", "root_path": "/repo/a"}]}

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_run(_run_args(workspace="ws-does-not-exist"))
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Workspace not found: ws-does-not-exist" in out


# ---------------------------------------------------------------------------
# pr-body
# ---------------------------------------------------------------------------


def test_pr_body_prints_body(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        assert path == "/api/tasks/task-1/pr-body"
        return {"body": "## Summary\n\nDid the thing.\n"}

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    cli.handle_pr_body(Namespace(task_id="task-1", out=None))

    out = capsys.readouterr().out
    assert "## Summary" in out
    assert "Did the thing." in out


def test_pr_body_writes_out_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"})
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "tok")

    def _fake_get_json(service_url, path, *, token=None):
        return {"body": "## Summary\n\nBody contents.\n"}

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    out_file = tmp_path / "pr-body.md"
    cli.handle_pr_body(Namespace(task_id="task-1", out=str(out_file)))

    assert out_file.read_text() == "## Summary\n\nBody contents.\n"
    out = capsys.readouterr().out
    assert f"Wrote PR body to {out_file}" in out


def test_pr_body_no_service_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_pr_body(Namespace(task_id="task-1", out=None))
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Sarathi desktop service not running" in out
