"""Tests for Slack interactive approve/reject gate decisions.

Covers:
- POST /api/workspaces/{workspace_id}/slack/interactions
- Block actions payload (type: "block_actions")
- Approve/reject button click handling (approve_gate / reject_gate actions)
- Gate status updates and lifecycle events
- HMAC signature verification
- Idempotency of repeated clicks
- Error handling (unknown gate/task, non-block-actions payloads)
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


def _create_task_with_pending_gate(storage, workspace_id):
    """Create a task with a pending PRD/AC approval gate. Returns (task, gate)."""
    task = storage.create_task(
        workspace_id=workspace_id,
        title="Test task for approval",
        status="prd_pending",
    )
    gate = storage.create_approval_gate(
        workspace_id=workspace_id,
        task_id=task["id"],
        name="PRD/AC",
        status="pending",
        metadata={"requires_human": True},
    )
    return task, gate


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_slack_interaction_approve_happy_path(tmp_path):
    """POST a block_actions payload with approve_gate action updates gate status."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    # Build the Slack payload for an approve action
    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
        "response_url": "https://hooks.slack.com/actions/T123/456",
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 200

    # Verify gate status was updated
    with connect(db_path) as conn:
        storage = Storage(conn)
        updated_gate = storage.get_approval_gate(gate["id"])
        assert updated_gate["status"] == "approved"

    # Verify lifecycle event was created
    _, events_data = json_request(app, "GET", f"/api/events?workspace_id={workspace_id}")
    events = events_data["events"]
    approval_events = [e for e in events if e["event_type"] == "approval.recorded"]
    assert len(approval_events) > 0
    latest_event = approval_events[-1]
    assert latest_event["task_id"] == task["id"]
    assert latest_event["payload"]["object_id"] == gate["id"]
    assert latest_event["payload"]["status"] == "approved"


def test_slack_interaction_reject_happy_path(tmp_path):
    """POST a block_actions payload with reject_gate action updates gate and task status."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    # Build the Slack payload for a reject action
    payload = {
        "type": "block_actions",
        "user": {"id": "U456", "username": "bob"},
        "actions": [
            {
                "action_id": "reject_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
        "response_url": "https://hooks.slack.com/actions/T123/789",
    }

    status, response = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 200

    # Verify gate status was updated to rejected
    with connect(db_path) as conn:
        storage = Storage(conn)
        updated_gate = storage.get_approval_gate(gate["id"])
        assert updated_gate["status"] == "rejected"

        # Verify task status changed to rejected
        updated_task = storage.get_task(task["id"])
        assert updated_task["status"] == "rejected"

    # Verify lifecycle events were created
    _, events_data = json_request(app, "GET", f"/api/events?workspace_id={workspace_id}")
    events = events_data["events"]

    # Should have both approval.recorded and task.cancelled events
    approval_events = [e for e in events if e["event_type"] == "approval.recorded"]
    cancelled_events = [e for e in events if e["event_type"] == "task.cancelled"]

    assert len(approval_events) > 0
    assert len(cancelled_events) > 0

    # Verify task.cancelled event has correct payload
    cancel_event = cancelled_events[-1]
    assert cancel_event["task_id"] == task["id"]
    assert cancel_event["payload"]["reason"] == "prd_ac_rejected"
    assert cancel_event["payload"]["gate"] == gate["id"]
    assert cancel_event["payload"]["by"] == "bob"


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


def test_slack_interaction_idempotent_double_approve(tmp_path):
    """POST the same approve action twice; second call is idempotent."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
        "response_url": "https://hooks.slack.com/actions/T123/456",
    }

    # First click
    status1, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )
    assert status1 == 200

    # Get the gate state after first click
    _, events_data1 = json_request(app, "GET", f"/api/events?workspace_id={workspace_id}")
    approval_events1 = [e for e in events_data1["events"] if e["event_type"] == "approval.recorded"]
    event_count_1 = len(approval_events1)

    # Second click (same payload)
    status2, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )
    assert status2 == 200

    # Verify gate still approved and no new event was created
    with connect(db_path) as conn:
        storage = Storage(conn)
        gate_state = storage.get_approval_gate(gate["id"])
        assert gate_state["status"] == "approved"

    # Verify only one approval.recorded event (idempotent)
    _, events_data2 = json_request(app, "GET", f"/api/events?workspace_id={workspace_id}")
    approval_events2 = [e for e in events_data2["events"] if e["event_type"] == "approval.recorded"]
    assert len(approval_events2) == event_count_1


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


def test_slack_interaction_rejects_bad_signature(tmp_path, monkeypatch):
    """When SARATHI_SLACK_SIGNING_SECRET is set, reject request with bad signature."""
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
    }

    ts = str(int(time.time()))
    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": "v0=definitely_wrong",
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
        raw_body=f"payload={json.dumps(payload)}",
        headers=headers,
    )

    assert status == 401


def test_slack_interaction_accepts_valid_signature(tmp_path, monkeypatch):
    """When SARATHI_SLACK_SIGNING_SECRET is set, accept request with valid signature."""
    secret = "test_signing_secret"
    monkeypatch.setenv("SARATHI_SLACK_SIGNING_SECRET", secret)
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
    }

    raw_body = f"payload={json.dumps(payload)}"
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{raw_body}"
    expected_sig = "v0=" + hmac.new(
        secret.encode("utf-8"), sig_basestring.encode("utf-8"), "sha256",
    ).hexdigest()

    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": expected_sig,
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
        raw_body=raw_body,
        headers=headers,
    )

    assert status == 200

    # Verify gate was actually updated
    with connect(db_path) as conn:
        storage = Storage(conn)
        updated_gate = storage.get_approval_gate(gate["id"])
        assert updated_gate["status"] == "approved"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_slack_interaction_unknown_gate_returns_404(tmp_path):
    """POST with unknown gate_id returns 404."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:nonexistent-gate-id",
            }
        ],
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 404


def test_slack_interaction_unknown_task_returns_404(tmp_path):
    """POST with unknown task_id returns 404."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"nonexistent-task-id:{gate['id']}",
            }
        ],
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 404


def test_slack_interaction_unknown_workspace_returns_404(tmp_path):
    """POST to unknown workspace returns 404."""
    app = create_app(tmp_path / "sarathi.db")

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": "task-id:gate-id",
            }
        ],
    }

    status, _ = slack_request(
        app,
        "POST",
        "/api/workspaces/nonexistent-workspace/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 404


def test_slack_interaction_non_block_actions_payload_is_no_op(tmp_path):
    """POST with type != 'block_actions' returns 200 without updating anything."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    # Send a "view_submission" payload instead of "block_actions"
    payload = {
        "type": "view_submission",
        "user": {"id": "U123", "username": "alice"},
        "trigger_id": "some-trigger-id",
        "view": {"id": "V123"},
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 200

    # Verify gate status unchanged
    with connect(db_path) as conn:
        storage = Storage(conn)
        gate_state = storage.get_approval_gate(gate["id"])
        assert gate_state["status"] == "pending"


def test_slack_interaction_unknown_action_id_is_no_op(tmp_path):
    """POST with unknown action_id returns 200 without updating anything."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

    # Send a block_actions payload but with an unknown action_id
    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "some_other_action",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    assert status == 200

    # Verify gate status unchanged
    with connect(db_path) as conn:
        storage = Storage(conn)
        gate_state = storage.get_approval_gate(gate["id"])
        assert gate_state["status"] == "pending"


def test_slack_interaction_already_approved_gate_is_idempotent(tmp_path):
    """POST to an already-approved gate is idempotent (no error, no double-record)."""
    app, workspace_id = _make_workspace(tmp_path)

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task, gate = _create_task_with_pending_gate(storage, workspace_id)

        # Pre-approve the gate
        storage.update_approval_gate(gate["id"], status="approved")

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "alice"},
        "actions": [
            {
                "action_id": "approve_gate",
                "value": f"{task['id']}:{gate['id']}",
            }
        ],
    }

    status, _ = slack_request(
        app,
        "POST",
        f"/api/workspaces/{workspace_id}/slack/interactions",
        body={"payload": json.dumps(payload)},
    )

    # Should still return 200 (no error)
    assert status == 200

    # Verify gate is still approved
    with connect(db_path) as conn:
        storage = Storage(conn)
        gate_state = storage.get_approval_gate(gate["id"])
        assert gate_state["status"] == "approved"
