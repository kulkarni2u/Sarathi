"""Transport-independent Slack approve/reject gate decision tests.

These tests drive ``SlackWorkflow`` directly with typed ``SlackEnvelope``
objects and a local SQLite ``Storage``. They never connect to Slack, access
the network, or use real-looking tokens, webhook URLs, response URLs, or raw
Socket Mode envelopes. The old HMAC/HTTP interaction behavior is intentionally
gone; Task 5 removes the public routes from the main service.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.service.slack.config import SlackSocketConfig
from src.service.slack.workflow import SlackEnvelope, SlackWorkflow
from src.storage import Storage, connect, run_migrations

TEST_TEAM_ID = "T00000000"
TEST_CHANNEL_ID = "C11111111"
TEST_ACTOR_ID = "U33333333"
TEST_APPROVER_ID = "U44444444"
TEST_WS_ID = "ws-0123456789abcdef"
TEST_THREAD_TS = "1700000000.000000"
TEST_APPROVE_ACTION = "v9k2m1q7w4"
TEST_REJECT_ACTION = "n3p8z5r2t6"

SLACK_SECURITY_EVENT = "slack.security_rejected"


def approval_envelope(**overrides: Any) -> SlackEnvelope:
    """Build an approval block-action envelope for the seeded gate."""
    action = overrides.pop("action", "approve")
    data: dict[str, Any] = {
        "kind": "interaction",
        "envelope_id": "env-interaction-1",
        "event_id": None,
        "team_id": TEST_TEAM_ID,
        "channel_id": TEST_CHANNEL_ID,
        "actor_id": TEST_APPROVER_ID,
        "payload": {
            "action_id": "sarathi_gate_decision",
            "value": TEST_APPROVE_ACTION if action == "approve" else TEST_REJECT_ACTION,
            "thread_ts": TEST_THREAD_TS,
            "channel_id": TEST_CHANNEL_ID,
            "team_id": TEST_TEAM_ID,
        },
    }
    data.update(overrides)
    return SlackEnvelope(**data)


class GateProbe:
    def __init__(self, storage: Storage, gate_id: str) -> None:
        self._storage = storage
        self._gate_id = gate_id

    def refresh(self) -> dict:
        gate = self._storage.get_approval_gate(self._gate_id)
        assert gate is not None
        return gate


@pytest.fixture
def storage(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    storage = Storage(conn)
    yield storage
    conn.close()


@pytest.fixture
def config() -> SlackSocketConfig:
    return SlackSocketConfig(
        app_token="sarathi-app-level-a1",
        bot_token="sarathi-bot-level-b2",
        team_id=TEST_TEAM_ID,
        channel_ids=frozenset({TEST_CHANNEL_ID}),
        approver_ids=frozenset({TEST_ACTOR_ID, TEST_APPROVER_ID}),
        workspace_id=TEST_WS_ID,
    )


@pytest.fixture
def workspace(storage):
    storage.conn.execute(
        """
        INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
        VALUES (?, ?, ?, '{}', ?, ?)
        """,
        (
            TEST_WS_ID,
            "Slack interactions",
            "/work/slack",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    storage.conn.commit()
    return storage.get_workspace(TEST_WS_ID)


@pytest.fixture
def workflow(storage, config) -> SlackWorkflow:
    return SlackWorkflow(storage=storage, config=config)


@pytest.fixture
def pending_gate(storage, workspace) -> GateProbe:
    task = storage.create_task(
        workspace_id=TEST_WS_ID,
        title="Approval task",
        status="prd_pending",
        metadata={"source": "slack_command"},
    )
    gate = storage.create_approval_gate(
        workspace_id=TEST_WS_ID,
        task_id=task["id"],
        name="PRD/AC",
        status="pending",
        metadata={
            "requires_human": True,
            "slack_decision_actions": {
                "approve": TEST_APPROVE_ACTION,
                "reject": TEST_REJECT_ACTION,
            },
        },
    )
    storage.bind_slack_task(
        task_id=task["id"],
        workspace_id=TEST_WS_ID,
        team_id=TEST_TEAM_ID,
        channel_id=TEST_CHANNEL_ID,
        thread_ts=TEST_THREAD_TS,
        requester_user_id=TEST_ACTOR_ID,
    )
    return GateProbe(storage, gate["id"])


def _security_events(storage) -> list[dict]:
    return [
        event
        for event in storage.list_events(workspace_id=TEST_WS_ID)
        if event["event_type"] == SLACK_SECURITY_EVENT
    ]


# ---------------------------------------------------------------------------
# Approve / reject transitions
# ---------------------------------------------------------------------------


def test_approved_gate_transition_is_processed(workflow, storage, pending_gate):
    workflow.accept(approval_envelope(envelope_id="env-interaction-1"))
    results = workflow.process_next()
    assert len(results) == 1
    assert results[0]["kind"] == "interaction"
    assert results[0]["status"] == "processed"
    assert results[0]["applied"] is True
    assert results[0]["gate_status"] == "approved"

    assert pending_gate.refresh()["status"] == "approved"

    outbox = storage.claim_slack_outbox()
    assert len(outbox) == 1
    assert outbox[0]["operation_key"].startswith("gate-decision:")
    assert outbox[0]["operation_key"].endswith(":env-interaction-1")
    assert outbox[0]["thread_ts"] == TEST_THREAD_TS

    assert storage.claim_slack_events() == []

    events = _security_events(storage)
    assert events == []


def test_rejected_gate_transition_is_processed(workflow, storage, pending_gate):
    workflow.accept(approval_envelope(action="reject", envelope_id="env-interaction-1"))
    results = workflow.process_next()
    assert len(results) == 1
    assert results[0]["status"] == "processed"
    assert results[0]["applied"] is True
    assert results[0]["gate_status"] == "rejected"

    assert pending_gate.refresh()["status"] == "rejected"


def test_duplicate_envelope_is_applied_at_most_once(workflow, storage, pending_gate):
    workflow.accept(approval_envelope(envelope_id="env-interaction-1"))
    workflow.process_next()
    workflow.accept(approval_envelope(envelope_id="env-interaction-1"))
    workflow.process_next()

    assert pending_gate.refresh()["status"] == "approved"
    outbox = storage.claim_slack_outbox()
    assert len(outbox) == 1
    assert storage.claim_slack_outbox() == []
    assert storage.claim_slack_events() == []


def test_repeat_decision_on_terminal_gate_does_not_second_transition(workflow, storage, pending_gate):
    workflow.accept(approval_envelope(envelope_id="env-interaction-1"))
    workflow.process_next()
    workflow.accept(approval_envelope(envelope_id="env-interaction-2"))
    results = workflow.process_next()
    assert len(results) == 1
    assert results[0]["status"] == "processed"
    assert results[0]["applied"] is False
    assert results[0]["gate_status"] == "approved"

    assert pending_gate.refresh()["status"] == "approved"
    assert len(storage.claim_slack_outbox()) == 1


# ---------------------------------------------------------------------------
# Rejected before any state change
# ---------------------------------------------------------------------------


def test_unknown_action_value_is_rejected(workflow, storage, pending_gate):
    workflow.accept(
        approval_envelope(envelope_id="env-interaction-1", payload={
            "action_id": "sarathi_gate_decision",
            "value": "totally-random-value",
            "thread_ts": TEST_THREAD_TS,
            "channel_id": TEST_CHANNEL_ID,
            "team_id": TEST_TEAM_ID,
        })
    )
    results = workflow.process_next()
    assert results[0]["status"] == "rejected"
    assert results[0]["error_code"] == "unknown-action"

    assert pending_gate.refresh()["status"] == "pending"
    assert storage.claim_slack_outbox() == []
    events = _security_events(storage)
    assert [event["payload"]["reason"] for event in events] == ["unknown-action"]


def test_binding_mismatch_is_rejected(workflow, storage, pending_gate):
    workflow.accept(
        approval_envelope(envelope_id="env-interaction-1", payload={
            "action_id": "sarathi_gate_decision",
            "value": TEST_APPROVE_ACTION,
            "thread_ts": "1700000000.999999",
            "channel_id": TEST_CHANNEL_ID,
            "team_id": TEST_TEAM_ID,
        })
    )
    results = workflow.process_next()
    assert results[0]["status"] == "rejected"
    assert results[0]["error_code"] == "binding-mismatch"

    assert pending_gate.refresh()["status"] == "pending"
    assert storage.claim_slack_outbox() == []
    events = _security_events(storage)
    assert [event["payload"]["reason"] for event in events] == ["binding-mismatch"]


def test_unauthorized_actor_fails_before_persistence(workflow, storage, pending_gate):
    with pytest.raises(Exception):
        workflow.accept(approval_envelope(actor_id="U-nope", envelope_id="env-interaction-1"))
    assert storage.claim_slack_events() == []
    assert storage.claim_slack_outbox() == []
    assert pending_gate.refresh()["status"] == "pending"


def test_only_approver_can_decide_and_first_decision_wins(workflow, pending_gate):
    with pytest.raises(Exception):
        workflow.accept(approval_envelope(actor_id="U-requester", envelope_id="env-interaction-1"))
    workflow.accept(approval_envelope(actor_id=TEST_APPROVER_ID, action="approve"))
    workflow.accept(
        approval_envelope(
            actor_id=TEST_APPROVER_ID, action="reject", envelope_id="env-interaction-2"
        )
    )
    workflow.process_next()
    assert pending_gate.refresh()["status"] == "approved"
