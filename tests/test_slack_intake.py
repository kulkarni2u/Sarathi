"""Tests for inbound Slack slash-command intake (docs/IMPLEMENTATION-PLAN.md 3.8).

Covers:
- `verify_slack_signature`: valid signature, wrong secret, stale timestamp,
  tampered body, and missing headers.
- `POST /slack/commands` disabled (404) when `SARATHI_SLACK_SIGNING_SECRET`
  is unset, and 401 on an invalid signature once it is set.
- `/sarathi run` drafting a task (with `{source: "slack", ...}` metadata and
  the same `task.draft_created` / `approval.requested` lifecycle events the
  other intake paths emit), including single/none/multiple-workspace
  resolution and the `run in <workspace>: <text>` prefix syntax.
- `/sarathi status` on a real and a missing task id.
- `help` / unknown-subcommand usage text.
- Raw-body plumbing end-to-end through the real HTTP server (`http.py`),
  proving the signature is verified over the exact raw bytes Slack would
  send, not a re-serialized/parsed form.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import threading
import time
from urllib.parse import urlencode, urlparse

import pytest

from src.service import create_app, create_http_server
from src.service.slack_intake import (
    SLACK_SIGNING_SECRET_ENV,
    handle_slack_command,
    parse_slack_form_body,
    verify_slack_signature,
)

SIGNING_SECRET = "test-signing-secret"


def _sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Compute a Slack-style `v0=<hex hmac-sha256>` signature (test vector)."""
    base_string = f"v0:{timestamp}:".encode("utf-8") + raw_body
    digest = hmac.new(secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def _slack_form(**fields: str) -> bytes:
    return urlencode(fields).encode("utf-8")


def _slack_headers(secret: str, timestamp: str, raw_body: bytes) -> dict[str, str]:
    return {
        "x-slack-signature": _sign(secret, timestamp, raw_body),
        "x-slack-request-timestamp": timestamp,
    }


def request(app, method, path, *, headers=None, raw_body=None, correlation_id="corr-slack"):
    all_headers = {"x-correlation-id": correlation_id}
    if headers:
        all_headers.update(headers)
    return app.handle(method, path, headers=all_headers, raw_body=raw_body)


def assert_ok(response, correlation_id="corr-slack"):
    status, payload = response
    assert payload["ok"] is True, payload
    assert payload["correlation_id"] == correlation_id
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-slack"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    return payload


def _create_workspace(app, tmp_path, name="Slack Workspace"):
    status, payload = app.handle(
        "POST",
        "/api/workspaces",
        body={"name": name, "root_path": str(tmp_path / name.replace(" ", "-"))},
        headers={"x-correlation-id": "corr-setup"},
    )
    assert status == 201, payload
    return payload["data"]["workspace"]


def _slack_post(app, secret, form_fields, *, timestamp=None, sign_with=None):
    """POST a signed `/slack/commands` request through `app.handle`."""
    raw_body = _slack_form(**form_fields)
    ts = timestamp if timestamp is not None else str(int(time.time()))
    headers = _slack_headers(sign_with if sign_with is not None else secret, ts, raw_body)
    return request(app, "POST", "/slack/commands", headers=headers, raw_body=raw_body)


# ── verify_slack_signature ───────────────────────────────────────────────


def test_verify_slack_signature_valid():
    timestamp = str(int(time.time()))
    raw_body = b"command=%2Fsarathi&text=help"
    signature = _sign(SIGNING_SECRET, timestamp, raw_body)
    assert verify_slack_signature(SIGNING_SECRET, timestamp, raw_body, signature) is True


def test_verify_slack_signature_wrong_secret():
    timestamp = str(int(time.time()))
    raw_body = b"command=%2Fsarathi&text=help"
    signature = _sign("a-different-secret", timestamp, raw_body)
    assert verify_slack_signature(SIGNING_SECRET, timestamp, raw_body, signature) is False


def test_verify_slack_signature_stale_timestamp():
    stale_timestamp = str(int(time.time()) - 301)
    raw_body = b"command=%2Fsarathi&text=help"
    signature = _sign(SIGNING_SECRET, stale_timestamp, raw_body)
    assert verify_slack_signature(SIGNING_SECRET, stale_timestamp, raw_body, signature) is False


def test_verify_slack_signature_accepts_boundary_skew():
    # 300s is the documented threshold: exactly at it should still pass. Use
    # an explicit `now` (rather than the real wall clock) so the assertion
    # isn't flaky against the few milliseconds elapsed between building the
    # timestamp and calling the function.
    fixed_now = 1_700_000_000.0
    timestamp = str(int(fixed_now) - 300)
    raw_body = b"command=%2Fsarathi&text=help"
    signature = _sign(SIGNING_SECRET, timestamp, raw_body)
    assert verify_slack_signature(
        SIGNING_SECRET, timestamp, raw_body, signature, now=fixed_now
    ) is True


def test_verify_slack_signature_tampered_body():
    timestamp = str(int(time.time()))
    raw_body = b"command=%2Fsarathi&text=help"
    signature = _sign(SIGNING_SECRET, timestamp, raw_body)
    tampered_body = b"command=%2Fsarathi&text=malicious"
    assert verify_slack_signature(SIGNING_SECRET, timestamp, tampered_body, signature) is False


def test_verify_slack_signature_missing_signature_or_timestamp():
    raw_body = b"text=help"
    assert verify_slack_signature(SIGNING_SECRET, None, raw_body, "v0=deadbeef") is False
    assert verify_slack_signature(SIGNING_SECRET, "123", raw_body, None) is False
    assert verify_slack_signature(SIGNING_SECRET, "not-a-number", raw_body, "v0=deadbeef") is False


def test_verify_slack_signature_injectable_clock():
    fixed_now = 1_700_000_000.0
    timestamp = str(int(fixed_now) - 10)
    raw_body = b"text=help"
    signature = _sign(SIGNING_SECRET, timestamp, raw_body)
    assert verify_slack_signature(
        SIGNING_SECRET, timestamp, raw_body, signature, now=fixed_now
    ) is True
    assert verify_slack_signature(
        SIGNING_SECRET, timestamp, raw_body, signature, now=fixed_now + 400
    ) is False


# ── parse_slack_form_body ────────────────────────────────────────────────


def test_parse_slack_form_body_extracts_expected_fields():
    raw_body = _slack_form(
        command="/sarathi",
        text="run fix the bug",
        user_id="U123",
        user_name="alice",
        team_id="T456",
        channel_id="C789",
        response_url="https://hooks.slack.example/abc",
    )
    form = parse_slack_form_body(raw_body)
    assert form["command"] == "/sarathi"
    assert form["text"] == "run fix the bug"
    assert form["user_id"] == "U123"
    assert form["user_name"] == "alice"
    assert form["team_id"] == "T456"
    assert form["channel_id"] == "C789"
    assert form["response_url"] == "https://hooks.slack.example/abc"


def test_parse_slack_form_body_handles_empty_bytes():
    assert parse_slack_form_body(b"") == {}


# ── Route-level: disabled by default / signature enforcement ────────────


def test_slack_route_disabled_when_secret_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(SLACK_SIGNING_SECRET_ENV, raising=False)
    app = create_app(tmp_path / "sarathi.db")
    raw_body = _slack_form(command="/sarathi", text="help")
    timestamp = str(int(time.time()))
    headers = _slack_headers("irrelevant-secret", timestamp, raw_body)

    response = request(app, "POST", "/slack/commands", headers=headers, raw_body=raw_body)
    assert_error(response, status=404, code="not_found")


def test_slack_route_rejects_invalid_signature(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    response = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "help"}, sign_with="wrong-secret"
    )
    assert_error(response, status=401, code="unauthorized")


def test_slack_route_rejects_stale_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    stale_timestamp = str(int(time.time()) - 600)

    response = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "help"}, timestamp=stale_timestamp
    )
    assert_error(response, status=401, code="unauthorized")


def test_slack_route_rejects_tampered_body(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    timestamp = str(int(time.time()))
    signed_body = _slack_form(command="/sarathi", text="help")
    headers = _slack_headers(SIGNING_SECRET, timestamp, signed_body)
    tampered_body = _slack_form(command="/sarathi", text="run rm -rf everything")

    response = request(app, "POST", "/slack/commands", headers=headers, raw_body=tampered_body)
    assert_error(response, status=401, code="unauthorized")


def test_slack_route_missing_signature_headers_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    raw_body = _slack_form(command="/sarathi", text="help")

    response = request(app, "POST", "/slack/commands", headers={}, raw_body=raw_body)
    assert_error(response, status=401, code="unauthorized")


# ── /sarathi run ──────────────────────────────────────────────────────────


def test_slack_run_creates_task_draft_with_metadata_and_lifecycle_events(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    workspace = _create_workspace(app, tmp_path)

    response = _slack_post(
        app,
        SIGNING_SECRET,
        {
            "command": "/sarathi",
            "text": "run Fix the checkout timeout bug",
            "user_id": "U123",
            "user_name": "alice",
            "team_id": "T456",
            "channel_id": "C789",
        },
    )
    status, payload = response
    assert status == 200
    assert payload["response_type"] == "in_channel"
    assert "Fix the checkout timeout bug" in payload["text"] or "task draft" in payload["text"].lower()

    _, tasks_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace['id']}/tasks"))
    tasks = tasks_data["tasks"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["metadata"]["source"] == "slack"
    assert task["metadata"]["slack"] == {"user": "alice", "channel": "C789", "team": "T456"}
    assert task["status"] == "prd_pending"

    _, events_data = assert_ok(request(app, "GET", f"/api/events?task_id={task['id']}"))
    event_types = [event["event_type"] for event in events_data["events"]]
    assert "task.draft_created" in event_types
    assert "approval.requested" in event_types


def test_slack_run_when_no_workspaces_exist(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "run Fix the thing"}
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "no sarathi workspaces" in payload["text"].lower()


def test_slack_run_requires_workspace_prefix_when_multiple_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    _create_workspace(app, tmp_path, name="Alpha")
    _create_workspace(app, tmp_path, name="Beta")

    status, payload = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "run Fix the thing"}
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "multiple workspaces" in payload["text"].lower()
    assert "run in <workspace-name-or-id>" in payload["text"]


def test_slack_run_with_workspace_prefix_resolves_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    alpha = _create_workspace(app, tmp_path, name="Alpha")
    _create_workspace(app, tmp_path, name="Beta")

    status, payload = _slack_post(
        app,
        SIGNING_SECRET,
        {"command": "/sarathi", "text": "run in Alpha: Fix the login bug"},
    )
    assert status == 200
    assert payload["response_type"] == "in_channel"

    _, tasks_data = assert_ok(request(app, "GET", f"/api/workspaces/{alpha['id']}/tasks"))
    assert len(tasks_data["tasks"]) == 1
    assert tasks_data["tasks"][0]["description"] == "Fix the login bug"


def test_slack_run_with_workspace_prefix_resolves_by_id(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    alpha = _create_workspace(app, tmp_path, name="Alpha")
    _create_workspace(app, tmp_path, name="Beta")

    status, payload = _slack_post(
        app,
        SIGNING_SECRET,
        {"command": "/sarathi", "text": f"run in {alpha['id']}: Fix the login bug"},
    )
    assert status == 200
    assert payload["response_type"] == "in_channel"

    _, tasks_data = assert_ok(request(app, "GET", f"/api/workspaces/{alpha['id']}/tasks"))
    assert len(tasks_data["tasks"]) == 1


def test_slack_run_with_unknown_workspace_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    _create_workspace(app, tmp_path, name="Alpha")

    status, payload = _slack_post(
        app,
        SIGNING_SECRET,
        {"command": "/sarathi", "text": "run in Nonexistent: Fix the login bug"},
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "no workspace found" in payload["text"].lower()


def test_slack_run_without_description_shows_usage(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    _create_workspace(app, tmp_path)

    status, payload = _slack_post(app, SIGNING_SECRET, {"command": "/sarathi", "text": "run"})
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "usage" in payload["text"].lower()


# ── /sarathi status ───────────────────────────────────────────────────────


def test_slack_status_returns_task_summary(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    workspace = _create_workspace(app, tmp_path)
    _slack_post(app, SIGNING_SECRET, {"command": "/sarathi", "text": "run Ship the thing"})
    _, tasks_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace['id']}/tasks"))
    task_id = tasks_data["tasks"][0]["id"]

    status, payload = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": f"status {task_id}"}
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert task_id in payload["text"]
    assert "prd_pending" in payload["text"]


def test_slack_status_missing_task(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "status does-not-exist"}
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "no task found" in payload["text"].lower()


def test_slack_status_without_task_id_shows_usage(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(app, SIGNING_SECRET, {"command": "/sarathi", "text": "status"})
    assert status == 200
    assert "usage" in payload["text"].lower()


# ── help / unknown ────────────────────────────────────────────────────────


def test_slack_help_command(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(app, SIGNING_SECRET, {"command": "/sarathi", "text": "help"})
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "/sarathi run" in payload["text"]
    assert "/sarathi status" in payload["text"]


def test_slack_empty_text_shows_help(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(app, SIGNING_SECRET, {"command": "/sarathi", "text": ""})
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "/sarathi run" in payload["text"]


def test_slack_unknown_command(tmp_path, monkeypatch):
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")

    status, payload = _slack_post(
        app, SIGNING_SECRET, {"command": "/sarathi", "text": "frobnicate everything"}
    )
    assert status == 200
    assert payload["response_type"] == "ephemeral"
    assert "unknown command" in payload["text"].lower()


def test_handle_slack_command_unit_level(tmp_path, monkeypatch):
    """Direct unit coverage of `handle_slack_command` without HTTP framing."""
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    app = create_app(tmp_path / "sarathi.db")
    _create_workspace(app, tmp_path)
    _conn, storage = app._storage()

    result = handle_slack_command(storage, {"text": "help"})
    assert result["response_type"] == "ephemeral"
    assert "/sarathi run" in result["text"]


# ── Raw-body plumbing end-to-end (real HTTP server) ──────────────────────


class _running_server:
    """Mirrors `tests/test_service_api.py`'s `running_server` helper."""

    def __init__(self, db_path):
        self.server = create_http_server(db_path=db_path, token="secret", host="127.0.0.1", port=0)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _post_raw(url, *, raw_body, headers):
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request("POST", parsed.path, body=raw_body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_raw_body_plumbing_verifies_signature_over_exact_bytes(tmp_path, monkeypatch):
    """End-to-end through the real socket server (http.py), not just
    `ServiceApp.handle` in-process: proves the HTTP layer threads the raw
    `application/x-www-form-urlencoded` bytes to the signature check
    unmodified — a re-serialized/re-encoded body would fail verification.
    """
    monkeypatch.setenv(SLACK_SIGNING_SECRET_ENV, SIGNING_SECRET)
    with _running_server(tmp_path / "sarathi.db") as base_url:
        raw_body = _slack_form(command="/sarathi", text="help")
        timestamp = str(int(time.time()))
        headers = {
            **_slack_headers(SIGNING_SECRET, timestamp, raw_body),
            "content-type": "application/x-www-form-urlencoded",
        }

        status, body = _post_raw(f"{base_url}/slack/commands", raw_body=raw_body, headers=headers)
        assert status == 200
        assert b"/sarathi run" in body

        # A byte-identical form re-encoded in a different key order changes
        # the raw bytes (and therefore the signature base string) even
        # though it would parse to the same field values — proving the
        # signature really is checked against the literal bytes threaded
        # through, not a re-serialized/parsed-then-reencoded version.
        reordered_body = _slack_form(text="help", command="/sarathi")
        assert reordered_body != raw_body
        status2, body2 = _post_raw(
            f"{base_url}/slack/commands", raw_body=reordered_body, headers=headers
        )
        assert status2 == 401


def test_raw_body_plumbing_disabled_returns_404_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv(SLACK_SIGNING_SECRET_ENV, raising=False)
    with _running_server(tmp_path / "sarathi.db") as base_url:
        raw_body = _slack_form(command="/sarathi", text="help")
        timestamp = str(int(time.time()))
        headers = _slack_headers("whatever", timestamp, raw_body)

        status, _body = _post_raw(f"{base_url}/slack/commands", raw_body=raw_body, headers=headers)
        assert status == 404
