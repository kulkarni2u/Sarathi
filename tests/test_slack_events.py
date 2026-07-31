"""Tests for Slack Events API endpoint (/slack/events).

Covers:
- POST /api/workspaces/{workspace_id}/slack/events
- URL verification handshake (type: "url_verification")
- Threaded message callbacks (type: "event_callback" with message events)
- Thread matching via channel + thread_ts
- Filtering: bot messages, subtypes, non-message events
- HMAC signature verification
- Error handling (unknown workspace, unmatched thread)
"""

from __future__ import annotations

import hmac
import json
import time

import pytest

from src.service import create_app
from src.service.app import RawResponse
from src.storage import Storage, connect, run_migrations


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
    """Create a workspace and return (app, workspace_id)."""
    app = create_app(tmp_path / "sarathi.db")
    _, data = json_request(
        app,
        "POST",
        "/api/workspaces",
        {"name": "Slack Workspace", "root_path": str(tmp_path)},
    )
    return app, data["workspace"]["id"]


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_slack_events_url_verification(tmp_path):
    """POST url_verification payload returns 200 with echoed challenge."""
    app, workspace_id = _make_workspace(tmp_path)

    payload = {
        "type": "url_verification",
        "challenge": "abc123def456",
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200
    assert response == {"challenge": "abc123def456"}


def test_slack_events_threaded_reply_creates_message(tmp_path):
    """POST an event_callback with message event creates a task message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        # Create a task with Slack thread metadata
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task with Slack thread",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Build the Slack event payload
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "here's my answer",
            "user": "U999888777",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify message was created on the task
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id, task_id=task["id"])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "here's my answer"
        assert messages[0]["metadata"]["source"] == "slack_message"
        assert messages[0]["metadata"]["slack_user_id"] == "U999888777"

        # Verify lifecycle event was created
        events = storage.list_events(workspace_id=workspace_id, task_id=task["id"])
        human_reply_events = [e for e in events if e["event_type"] == "task.human_reply"]
        assert len(human_reply_events) == 1
        event = human_reply_events[0]
        assert event["payload"]["object_id"] == messages[0]["id"]
        assert event["payload"]["slack_user_id"] == "U999888777"


def test_slack_events_bot_message_is_no_op(tmp_path):
    """POST an event with bot_id present returns 200 without creating a message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Record message count before
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages_before = len(storage.list_messages(
            workspace_id=workspace_id, task_id=task["id"]
        ))

    # Post event with bot_id
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "I am a bot",
            "user": "U999",
            "bot_id": "B123456789",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages_after = len(storage.list_messages(
            workspace_id=workspace_id, task_id=task["id"]
        ))
    assert messages_after == messages_before


def test_slack_events_subtype_present_is_no_op(tmp_path):
    """POST an event with subtype present returns 200 without creating a message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Record message count before
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages_before = len(storage.list_messages(
            workspace_id=workspace_id, task_id=task["id"]
        ))

    # Post event with subtype (message_changed)
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "edited message",
            "subtype": "message_changed",
            "user": "U999",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages_after = len(storage.list_messages(
            workspace_id=workspace_id, task_id=task["id"]
        ))
    assert messages_after == messages_before


def test_slack_events_unknown_channel_thread_is_no_op(tmp_path):
    """POST an event with unknown channel/thread_ts returns 200 without creating anything."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        # Create a task with different channel/thread
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C9999999",
                    "thread_ts": "9999999999.999999",
                }
            },
        )

    # Post event with different channel/thread
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "CUNKNOWN",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "orphan message",
            "user": "U999",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created on any task
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id)
        assert len(messages) == 0


def test_slack_events_top_level_message_matches_via_ts(tmp_path):
    """POST an event without thread_ts but matching ts creates message (ts fallback)."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        # Create task with thread_ts matching the event's ts
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Post event with no thread_ts, only ts (top-level message)
    # The code falls back to ts if thread_ts is not present
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "ts": "1234567890.001234",  # no thread_ts, only ts
            "text": "top-level message",
            "user": "U999",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id, task_id=task["id"])
        assert len(messages) == 1
        assert messages[0]["content"] == "top-level message"


def test_slack_events_non_message_event_type_is_no_op(tmp_path):
    """POST an event with type != 'message' returns 200 without creating a message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Post a reaction_added event instead of message
    payload = {
        "type": "event_callback",
        "event": {
            "type": "reaction_added",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "user": "U999",
            "reaction": "thumbsup",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id, task_id=task["id"])
        assert len(messages) == 0


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


def test_slack_events_rejects_bad_signature(tmp_path, monkeypatch):
    """When SARATHI_SLACK_SIGNING_SECRET is set, reject request with bad signature."""
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "test message",
            "user": "U999",
        },
    }

    ts = str(int(time.time()))
    raw_body = json.dumps(payload)
    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": "v0=definitely_wrong",
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
        raw_body=raw_body,
        headers=headers,
    )

    assert status == 401


def test_slack_events_accepts_valid_signature(tmp_path, monkeypatch):
    """When SARATHI_SLACK_SIGNING_SECRET is set, accept request with valid signature."""
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "test message",
            "user": "U999",
        },
    }

    raw_body = json.dumps(payload)
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{raw_body}"
    expected_sig = "v0=" + hmac.new(
        secret.encode("utf-8"), sig_basestring.encode("utf-8"), "sha256",
    ).hexdigest()

    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": expected_sig,
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
        raw_body=raw_body,
        headers=headers,
    )

    assert status == 200

    # Verify message was actually created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id, task_id=task["id"])
        assert len(messages) == 1
        assert messages[0]["content"] == "test message"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_slack_events_unknown_workspace_returns_404(tmp_path):
    """POST to unknown workspace returns 404."""
    app = create_app(tmp_path / "sarathi.db")

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "test message",
            "user": "U999",
        },
    }

    status, _ = slack_request(
        app,
        "POST",
        "/api/workspaces/nonexistent-workspace/slack/events",
        body=payload,
    )

    assert status == 404


def test_slack_events_non_event_callback_payload_is_no_op(tmp_path):
    """POST with type != 'event_callback' (and not url_verification) returns 200 without processing."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Send a payload with an unknown type
    payload = {
        "type": "unknown_type",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "text": "test",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200
    assert response == {}


def test_slack_events_missing_channel_is_no_op(tmp_path):
    """POST an event without channel returns 200 without creating a message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Post event without channel
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "text": "test message",
            "user": "U999",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id)
        assert len(messages) == 0


def test_slack_events_missing_text_is_no_op(tmp_path):
    """POST an event without text (or empty text) returns 200 without creating a message."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        storage.create_task(
            workspace_id=workspace_id,
            title="Test task",
            status="pending",
            metadata={
                "slack": {
                    "channel_id": "C1234567",
                    "thread_ts": "1234567890.001234",
                }
            },
        )

    # Post event without text
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567",
            "thread_ts": "1234567890.001234",
            "ts": "1234567890.005678",
            "user": "U999",
        },
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/events",
        body=payload,
    )

    assert status == 200

    # Verify no message was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        messages = storage.list_messages(workspace_id=workspace_id)
        assert len(messages) == 0
