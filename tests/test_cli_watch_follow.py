"""Tests for the `sarathi watch --follow` CLI command (item 1.3 of IMPLEMENTATION-PLAN)."""
import argparse
import json

import pytest

import src.cli as cli


def test_parse_sse_stream_single_event():
    """Parse a single complete SSE event."""
    lines = [
        "id: event-1",
        "event: task.created",
        "data: {\"object_id\":\"task-123\"}",
        "",
    ]
    events = list(cli._parse_sse_stream(lines))
    assert len(events) == 1
    event_id, event_type, data = events[0]
    assert event_id == "event-1"
    assert event_type == "task.created"
    assert data == {"object_id": "task-123"}


def test_parse_sse_stream_multiline_data():
    """Parse SSE event with multi-line JSON data payload."""
    lines = [
        "id: event-2",
        "event: task.updated",
        'data: {"object_id":"task-456","status":"running",',
        'data: "details":"in progress"}',
        "",
    ]
    events = list(cli._parse_sse_stream(lines))
    assert len(events) == 1
    event_id, event_type, data = events[0]
    assert event_id == "event-2"
    assert event_type == "task.updated"
    assert data == {"object_id": "task-456", "status": "running", "details": "in progress"}


def test_parse_sse_stream_multiple_events():
    """Parse multiple SSE events from a single stream."""
    lines = [
        "id: event-1",
        "event: task.created",
        "data: {\"object_id\":\"task-1\"}",
        "",
        "id: event-2",
        "event: task.started",
        "data: {\"object_id\":\"task-1\"}",
        "",
        "id: event-3",
        "event: task.completed",
        "data: {\"object_id\":\"task-1\"}",
        "",
    ]
    events = list(cli._parse_sse_stream(lines))
    assert len(events) == 3
    assert events[0][1] == "task.created"
    assert events[1][1] == "task.started"
    assert events[2][1] == "task.completed"


def test_parse_sse_stream_ignores_junk():
    """Parse SSE stream ignoring comment lines and malformed lines."""
    lines = [
        ": this is a comment",
        "id: event-1",
        "event: task.created",
        "junk line without colon",
        "data: {\"object_id\":\"task-1\"}",
        "",
        "some random text",
    ]
    events = list(cli._parse_sse_stream(lines))
    assert len(events) == 1
    event_id, event_type, data = events[0]
    assert event_id == "event-1"
    assert event_type == "task.created"
    assert data == {"object_id": "task-1"}


def test_parse_sse_stream_string_data():
    """Parse SSE event with non-JSON string data."""
    lines = [
        "id: event-1",
        "event: task.log",
        "data: Build failed with exit code 1",
        "",
    ]
    events = list(cli._parse_sse_stream(lines))
    assert len(events) == 1
    event_id, event_type, data = events[0]
    assert event_id == "event-1"
    assert event_type == "task.log"
    assert data == "Build failed with exit code 1"


def test_watch_follow_no_service(monkeypatch, capsys):
    """watch --follow should hint about starting service when not running."""
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    args = argparse.Namespace(
        follow=True,
        workspace=None,
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Sarathi desktop service not running" in out
    assert "sarathi desktop" in out


def test_watch_follow_with_workspace_specified(monkeypatch, capsys):
    """watch --follow with --workspace should stream from service."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    call_log = {}

    def _fake_urlopen(request, timeout=None):
        """Mock urllib.request.urlopen to return a fake SSE stream."""
        call_log["request"] = request
        call_log["headers"] = dict(request.headers)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __iter__(self):
                # Return fake SSE event lines
                return iter([
                    b"id: event-1\n",
                    b"event: task.created\n",
                    b'data: {"object_id":"task-123"}\n',
                    b"\n",
                ])

        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    # Should exit cleanly after stream ends
    assert exc_info.value.code == 0

    # Check that correct URL and auth headers were used
    request = call_log["request"]
    assert "workspaces/ws-123/tasks/task-123/events/stream" in request.full_url
    assert call_log["headers"].get("Authorization") == "Bearer secret-token"

    out = capsys.readouterr().out
    assert "Following task task-123" in out
    assert "task.created" in out


def test_watch_follow_discovers_single_workspace(monkeypatch, capsys):
    """watch --follow should auto-discover workspace when only one exists."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    def _fake_get_json(service_url, path, *, token=None):
        if path == "/api/workspaces":
            return {"workspaces": [{"id": "ws-1", "name": "Default"}]}
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    def _fake_urlopen(request, timeout=None):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __iter__(self):
                return iter([
                    b"id: event-1\n",
                    b"event: task.created\n",
                    b'data: {"object_id":"task-456"}\n',
                    b"\n",
                ])

        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace=None,
        task_id="task-456",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "Following task task-456" in out


def test_watch_follow_prompts_for_workspace_when_multiple(monkeypatch, capsys):
    """watch --follow should prompt when multiple workspaces exist and none specified."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    def _fake_get_json(service_url, path, *, token=None):
        if path == "/api/workspaces":
            return {
                "workspaces": [
                    {"id": "ws-1", "name": "Dev"},
                    {"id": "ws-2", "name": "Prod"},
                ]
            }
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_get_json", _fake_get_json)

    args = argparse.Namespace(
        follow=True,
        workspace=None,
        task_id="task-789",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Multiple workspaces found" in out
    assert "Dev" in out
    assert "Prod" in out


def test_watch_follow_keyboard_interrupt(monkeypatch, capsys):
    """watch --follow should handle KeyboardInterrupt gracefully."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    def _fake_urlopen(request, timeout=None):
        # Simulate KeyboardInterrupt during stream reading
        raise KeyboardInterrupt()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "Stream stopped" in out


def test_watch_follow_http_404(monkeypatch, capsys):
    """watch --follow should handle 404 (not found) gracefully."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    import urllib.error

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="missing-task",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Task or workspace not found" in out


def test_watch_follow_http_401(monkeypatch, capsys):
    """watch --follow should handle 401 (unauthorized) gracefully."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "bad-token")

    import urllib.error

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Authentication failed" in out


def test_watch_follow_connection_drop_with_reconnect(monkeypatch, capsys):
    """watch --follow should reconnect once on connection drop."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    import urllib.error

    call_count = {"count": 0}

    def _fake_urlopen(request, timeout=None):
        call_count["count"] += 1
        if call_count["count"] == 1:
            # First call: drop connection
            raise urllib.error.URLError("Connection refused")
        else:
            # Second call (reconnect): succeed
            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def __iter__(self):
                    return iter([
                        b"id: event-1\n",
                        b"event: task.created\n",
                        b'data: {"object_id":"task-123"}\n',
                        b"\n",
                    ])

            return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "Connection lost" in out
    assert "Reconnecting" in out
    assert "Following task task-123" in out  # Second attempt succeeded


def test_watch_follow_connection_drop_no_reconnect(monkeypatch, capsys):
    """watch --follow should exit after second connection drop."""
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc:8765"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: "secret-token")

    import urllib.error

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    args = argparse.Namespace(
        follow=True,
        workspace="ws-123",
        task_id="task-123",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_watch(args)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "Connection dropped" in out
