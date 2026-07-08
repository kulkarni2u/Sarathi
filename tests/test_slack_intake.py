"""Tests for Slack slash-command task intake (IMPLEMENTATION-PLAN.md item 3.8).

Covers:
- POST /api/workspaces/{workspace_id}/slack/commands/task
- HMAC signing verification (SARATHI_SLACK_SIGNING_SECRET)
- Task draft creation with PRD/AC gate, messages, and lifecycle events
- Slack metadata preservation in task.metadata.slack_command
"""

from __future__ import annotations

import hmac
import json
import time

import pytest

from src.service import create_app
from src.service.app import RawResponse
from src.service.intake import _parse_slack_body, _verify_slack_request


def slack_request(app, method, path, body=None, raw_body=None,
                  correlation_id="corr-slack", headers=None):
    """Call ``app.handle`` and return ``(status, payload)``.

    Normalises ``RawResponse`` (returned on success for Slack endpoints)
    to ``(status, json_dict)`` so callers get a uniform interface.
    """
    base_headers = {"x-correlation-id": correlation_id}
    if headers:
        base_headers.update(headers)
    result = app.handle(method, path, body=body, raw_body=raw_body, headers=base_headers)
    if isinstance(result, RawResponse):
        return result.status, json.loads(result.body.decode("utf-8"))
    return result


def json_request(app, method, path, body=None, correlation_id="corr-slack"):
    """Call a normal JSON-API endpoint (returns the ok envelope)."""
    status, payload = app.handle(
        method, path, body=body, headers={"x-correlation-id": correlation_id},
    )
    assert payload["ok"] is True
    return status, payload["data"]


def _make_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, data = json_request(
        app,
        "POST",
        "/api/workspaces",
        {"name": "Slack Workspace", "root_path": str(tmp_path)},
    )
    return app, data["workspace"]["id"]


# ---------------------------------------------------------------------------
# _parse_slack_body unit
# ---------------------------------------------------------------------------


def test_parse_slack_body_handles_string():
    raw = "text=hello+world&team_id=T123&user_id=U456"
    result = _parse_slack_body(raw)
    assert result["text"] == "hello world"
    assert result["team_id"] == "T123"
    assert result["user_id"] == "U456"


def test_parse_slack_body_handles_dict():
    result = _parse_slack_body({"text": "hello", "team_id": "T123"})
    assert result["text"] == "hello"
    assert result["team_id"] == "T123"


def test_parse_slack_body_empty():
    assert _parse_slack_body("") == {}
    assert _parse_slack_body({}) == {}


# ---------------------------------------------------------------------------
# _verify_slack_request unit
# ---------------------------------------------------------------------------


def test_verify_slack_request_skipped_when_no_secret(monkeypatch):
    monkeypatch.delenv("SARATHI_SLACK_SIGNING_SECRET", raising=False)
    _verify_slack_request({"x-slack-signature": "v0=abc"}, "raw")


def test_verify_slack_request_rejects_missing_headers(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    with pytest.raises(Exception) as exc:
        _verify_slack_request(None, "raw")
    assert exc.value.status == 400


def test_verify_slack_request_rejects_missing_timestamp(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    with pytest.raises(Exception) as exc:
        _verify_slack_request({"x-slack-signature": "v0=abc"}, "raw")
    assert exc.value.status == 400


def test_verify_slack_request_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    with pytest.raises(Exception) as exc:
        _verify_slack_request(
            {"x-slack-request-timestamp": str(int(time.time()))}, "raw"
        )
    assert exc.value.status == 401


def test_verify_slack_request_rejects_stale_timestamp(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    stale_ts = str(int(time.time()) - 400)
    with pytest.raises(Exception) as exc:
        _verify_slack_request(
            {
                "x-slack-request-timestamp": stale_ts,
                "x-slack-signature": "v0=abc",
            },
            "raw",
        )
    assert exc.value.status == 401
    assert "stale" in exc.value.code


def test_verify_slack_request_rejects_future_timestamp(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    future_ts = str(int(time.time()) + 400)
    with pytest.raises(Exception) as exc:
        _verify_slack_request(
            {
                "x-slack-request-timestamp": future_ts,
                "x-slack-signature": "v0=abc",
            },
            "raw",
        )
    assert exc.value.status == 401
    assert "stale" in exc.value.code


def test_verify_slack_request_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", "secret123")
    ts = str(int(time.time()))
    with pytest.raises(Exception) as exc:
        _verify_slack_request(
            {"x-slack-request-timestamp": ts, "x-slack-signature": "v0=invalid"},
            "raw_body",
        )
    assert exc.value.status == 401
    assert "signature" in exc.value.code


def test_verify_slack_request_accepts_valid_signature(monkeypatch):
    secret = "my_slack_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    raw_body = "text=hello+world&team_id=T123"
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{raw_body}"
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"), sig_basestring.encode("utf-8"), "sha256",
    ).hexdigest()
    _verify_slack_request(
        {"x-slack-request-timestamp": ts, "x-slack-signature": expected},
        raw_body,
    )


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------


def test_slack_command_creates_task_draft(tmp_path):
    app, workspace_id = _make_workspace(tmp_path)
    body = {
        "text": "Build the workspace task initiation flow",
        "team_id": "T001",
        "team_domain": "example",
        "channel_id": "C001",
        "channel_name": "general",
        "user_id": "U001",
        "user_name": "alice",
        "command": "/task",
        "response_url": "https://hooks.slack.com/commands/T001/123",
    }

    status, slack_reply = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
    )

    assert status == 200
    assert slack_reply["response_type"] == "ephemeral"
    assert slack_reply["text"]
    assert slack_reply["text"] != ""
    assert slack_reply["task_id"]
    assert slack_reply["approval_gate_id"]

    # Verify the task was created in storage.
    _, tasks_data = json_request(app, "GET", f"/api/workspaces/{workspace_id}/tasks")
    assert len(tasks_data["tasks"]) == 1
    task = tasks_data["tasks"][0]
    assert task["status"] == "prd_pending"
    assert task["metadata"]["source"] == "slack_command"
    assert task["metadata"]["slack_command"]["team_id"] == "T001"
    assert task["metadata"]["slack_command"]["user_name"] == "alice"


def test_slack_command_missing_text_returns_error(tmp_path):
    app, workspace_id = _make_workspace(tmp_path)
    body = {"team_id": "T001", "user_id": "U001", "command": "/task"}

    status, payload = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
    )

    assert status == 400


def test_slack_command_empty_text_returns_error(tmp_path):
    app, workspace_id = _make_workspace(tmp_path)
    body = {"text": "", "team_id": "T001"}

    status, payload = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
    )

    assert status == 400


def test_slack_command_preserves_metadata_and_lifecycle_events(tmp_path):
    app, workspace_id = _make_workspace(tmp_path)
    body = {
        "text": "Refactor the auth module",
        "team_id": "T002",
        "team_domain": "acme-corp",
        "channel_id": "C002",
        "channel_name": "dev",
        "user_id": "U002",
        "user_name": "bob",
        "command": "/task",
        "response_url": "https://hooks.slack.com/commands/T002/456",
    }

    status, slack_reply = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
    )
    assert status == 200
    assert slack_reply["task_id"]
    assert slack_reply["approval_gate_id"]

    # Lifecycle events
    _, events_data = json_request(app, "GET", f"/api/events?workspace_id={workspace_id}")
    event_types = [e["event_type"] for e in events_data["events"]]
    assert "task.draft_created" in event_types
    assert "approval.requested" in event_types

    # Messages
    _, tasks_data = json_request(app, "GET", f"/api/workspaces/{workspace_id}/tasks")
    task_id = tasks_data["tasks"][0]["id"]
    _, msgs_data = json_request(app, "GET", f"/api/tasks/{task_id}/messages")
    messages = msgs_data["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert "Refactor the auth module" in messages[0]["content"]
    assert messages[1]["role"] == "sarathi"
    assert messages[1]["metadata"]["source"] == "slack_command"

    # Approval gate
    _, gates_data = json_request(app, "GET", f"/api/tasks/{task_id}/approvals")
    gates = gates_data["approval_gates"]
    assert len(gates) == 1
    assert gates[0]["name"] == "PRD/AC"
    assert gates[0]["status"] == "pending"

    # Slack metadata on task
    _, task_data = json_request(app, "GET", f"/api/tasks/{task_id}")
    task = task_data["task"]
    slack_cmd = task["metadata"]["slack_command"]
    assert slack_cmd["team_id"] == "T002"
    assert slack_cmd["team_domain"] == "acme-corp"
    assert slack_cmd["channel_id"] == "C002"
    assert slack_cmd["channel_name"] == "dev"
    assert slack_cmd["user_id"] == "U002"
    assert slack_cmd["user_name"] == "bob"
    assert slack_cmd["command"] == "/task"
    assert slack_cmd["response_url"] == "https://hooks.slack.com/commands/T002/456"


def test_slack_command_works_with_signed_request(tmp_path, monkeypatch):
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    raw_body = "text=Build+the+thing&team_id=T003&channel_name=dev&user_name=charlie&command=%2Ftask"
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{raw_body}"
    signature = "v0=" + hmac.new(
        secret.encode("utf-8"), sig_basestring.encode("utf-8"), "sha256",
    ).hexdigest()

    headers = {"x-slack-request-timestamp": ts, "x-slack-signature": signature}

    body = {"text": "Build the thing", "team_id": "T003", "user_name": "charlie", "command": "/task"}

    status, slack_reply = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
        raw_body=raw_body,
        headers=headers,
    )

    assert status == 200
    assert slack_reply["response_type"] == "ephemeral"
    assert slack_reply["task_id"]
    assert slack_reply["approval_gate_id"]


def test_slack_command_rejects_bad_signature(tmp_path, monkeypatch):
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    ts = str(int(time.time()))
    headers = {"x-slack-request-timestamp": ts, "x-slack-signature": "v0=definitely_wrong"}

    status, _ = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body={"text": "anything"}, raw_body="text=anything", headers=headers,
    )
    assert status == 401


def test_slack_command_rejects_stale_timestamp(tmp_path, monkeypatch):
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    stale_ts = str(int(time.time()) - 400)
    headers = {"x-slack-request-timestamp": stale_ts, "x-slack-signature": "v0=does_not_matter"}

    status, _ = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body={"text": "anything"}, raw_body="text=anything", headers=headers,
    )
    assert status == 401


def test_slack_command_works_without_signing_secret_in_local_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("SARATHI_SLACK_SIGNING_SECRET", raising=False)
    app, workspace_id = _make_workspace(tmp_path)

    body = {"text": "Local dev task", "team_id": "T999", "user_name": "dev"}

    status, slack_reply = slack_request(
        app, "POST", f"/api/workspaces/{workspace_id}/slack/commands/task",
        body=body,
    )

    assert status == 200
    assert slack_reply["response_type"] == "ephemeral"
    assert slack_reply["task_id"]
    assert slack_reply["approval_gate_id"]


def test_slack_command_rejects_missing_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    body = {"text": "Orphan task", "team_id": "T001"}

    status, payload = slack_request(
        app, "POST", "/api/workspaces/does-not-exist/slack/commands/task",
        body=body,
    )

    assert status == 404
