"""Durable Slack storage tests: inbox, outbox, task bindings, external inputs.

Covers the Task 2 Slack storage surface with strict TDD: each behavior below
was written and observed failing before the implementation existed. These tests
never contact Slack or any external host.
"""

import json
from pathlib import Path

import pytest

from src.storage import (
    LATEST_SCHEMA_VERSION,
    Storage,
    connect,
    current_schema_version,
    run_migrations,
)


WORKSPACE_ID = "ws-0123456789abcdef"


def validated_event(envelope_id, **overrides):
    data = {
        "envelope_id": envelope_id,
        "event_id": f"E-{envelope_id}",
        "workspace_id": WORKSPACE_ID,
        "team_id": "T00000000",
        "channel_id": "C11111111",
        "actor_id": "U33333333",
        "event_type": "slash_commands",
        "content": {
            "command": "/sarathi-task",
            "text": "ship the parser",
            "trigger_id": "ignored-trigger",
        },
    }
    data.update(overrides)
    return data


def outbox_message(operation_key, **overrides):
    data = {
        "operation_key": operation_key,
        "workspace_id": WORKSPACE_ID,
        "task_id": "task-1",
        "channel_id": "C11111111",
        "thread_ts": "1700000000.000000",
        "operation": "message",
        "payload": {"text": "Draft created", "blocks": []},
    }
    data.update(overrides)
    return data


def reply_input(**overrides):
    data = {
        "envelope_id": "env-reply-1",
        "workspace_id": WORKSPACE_ID,
        "task_id": "task-1",
        "actor_id": "U33333333",
        "channel_id": "C11111111",
        "text": "Use the existing migration pattern",
        "validation_version": "slack-input-v1",
        "digest": "0" * 64,
    }
    data.update(overrides)
    return data


@pytest.fixture
def storage(tmp_path: Path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    storage = Storage(conn)
    yield storage
    conn.close()


@pytest.fixture
def workspace(storage):
    return storage.create_workspace(name="Slack intake", root_path="/work/slack")


@pytest.fixture
def task(storage, workspace):
    return storage.create_task(
        workspace_id=workspace["id"], title="Slack task", status="in_progress"
    )


@pytest.fixture
def waiting_subtasks(storage, task):
    return [
        storage.create_subtask(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            title="Wait one",
            status="waiting_human",
        ),
        storage.create_subtask(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            title="Wait two",
            status="waiting_human",
        ),
    ]


def test_run_migrations_creates_slack_tables(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"slack_inbox", "slack_outbox", "slack_task_bindings", "slack_external_inputs"} <= tables


def test_slack_inbox_deduplicates_envelope_and_omits_raw_payload(storage):
    first = storage.enqueue_slack_event(**validated_event("env-1"))
    second = storage.enqueue_slack_event(**validated_event("env-1"))
    assert first["id"] == second["id"]
    assert first["status"] == "pending"
    assert "raw_envelope" not in first
    assert "response_url" not in json.dumps(first)


def test_slack_inbox_stores_validated_content_and_ids(storage):
    row = storage.enqueue_slack_event(**validated_event("env-1"))
    assert row["envelope_id"] == "env-1"
    assert row["event_id"] == "E-env-1"
    assert row["workspace_id"] == WORKSPACE_ID
    assert row["team_id"] == "T00000000"
    assert row["channel_id"] == "C11111111"
    assert row["actor_id"] == "U33333333"
    assert row["event_type"] == "slash_commands"
    assert row["content"]["text"] == "ship the parser"


def test_slack_events_claim_transitions_pending_to_processing(storage):
    for i in range(3):
        storage.enqueue_slack_event(**validated_event(f"env-{i}"))
    claimed = storage.claim_slack_events(limit=2)
    assert [row["envelope_id"] for row in claimed] == ["env-0", "env-1"]
    assert all(row["status"] == "processing" for row in claimed)
    assert all(row["claimed_at"] is not None for row in claimed)
    remaining = storage.claim_slack_events(limit=20)
    assert [row["envelope_id"] for row in remaining] == ["env-2"]
    assert storage.claim_slack_events() == []


def test_slack_event_finish_records_terminal_state_and_redacted_code(storage):
    storage.enqueue_slack_event(**validated_event("env-1"))
    finished = storage.finish_slack_event(
        "env-1", status="failed", error_code="delivery-timeout"
    )
    assert finished["status"] == "failed"
    assert finished["error_code"] == "delivery-timeout"
    assert finished["processed_at"] is not None


@pytest.mark.parametrize("status", ["processed", "rejected", "failed"])
def test_slack_event_finish_accepts_terminal_statuses(storage, status):
    storage.enqueue_slack_event(**validated_event("env-1"))
    finished = storage.finish_slack_event("env-1", status=status)
    assert finished["status"] == status


def test_slack_event_finish_rejects_non_terminal_status(storage):
    storage.enqueue_slack_event(**validated_event("env-1"))
    with pytest.raises(ValueError):
        storage.finish_slack_event("env-1", status="in_progress")


def test_slack_outbox_operation_key_is_unique(storage):
    first = storage.enqueue_slack_outbox(**outbox_message("task-created:1"))
    second = storage.enqueue_slack_outbox(**outbox_message("task-created:1"))
    assert first["id"] == second["id"]


def test_slack_outbox_stores_operation_without_response_url(storage):
    row = storage.enqueue_slack_outbox(**outbox_message("task-created:1"))
    assert row["operation_key"] == "task-created:1"
    assert row["operation"] == "message"
    assert row["channel_id"] == "C11111111"
    assert row["thread_ts"] == "1700000000.000000"
    assert "response_url" not in json.dumps(row)


def test_slack_outbox_claim_and_finish_sent(storage):
    storage.enqueue_slack_outbox(**outbox_message("task-created:1"))
    storage.enqueue_slack_outbox(**outbox_message("task-created:2"))
    claimed = storage.claim_slack_outbox(limit=1)
    assert [row["operation_key"] for row in claimed] == ["task-created:1"]
    assert claimed[0]["status"] == "processing"
    finished = storage.finish_slack_outbox(
        "task-created:1", slack_message_ts="1700000001.000001"
    )
    assert finished["status"] == "sent"
    assert finished["slack_message_ts"] == "1700000001.000001"


def test_slack_task_binding_round_trip_and_rebind_is_idempotent(storage, task):
    first = storage.bind_slack_task(
        task_id=task["id"],
        workspace_id=task["workspace_id"],
        team_id="T00000000",
        channel_id="C11111111",
        thread_ts="1700000000.000000",
        requester_user_id="U33333333",
    )
    second = storage.bind_slack_task(
        task_id=task["id"],
        workspace_id=task["workspace_id"],
        team_id="T00000000",
        channel_id="C11111111",
        thread_ts="1700000000.000000",
        requester_user_id="U33333333",
    )
    assert first["id"] == second["id"]
    found = storage.get_slack_task_binding(
        team_id="T00000000", channel_id="C11111111", thread_ts="1700000000.000000"
    )
    assert found is not None
    assert found["task_id"] == task["id"]
    assert found["requester_user_id"] == "U33333333"


def test_slack_task_binding_get_missing_returns_none(storage):
    assert (
        storage.get_slack_task_binding(
            team_id="T00000000", channel_id="C11111111", thread_ts="1700000000.000000"
        )
        is None
    )


def test_slack_external_input_created_unassigned(storage):
    item = storage.create_slack_external_input(**reply_input())
    assert item["subtask_id"] is None
    assert item["status"] == "unassigned"
    assert item["text"] == "Use the existing migration pattern"
    assert item["validation_version"] == "slack-input-v1"
    assert item["digest"] == "0" * 64


def test_external_input_assignment_has_one_winner(storage, waiting_subtasks):
    item = storage.create_slack_external_input(**reply_input())
    first = storage.assign_slack_external_input(item["id"], waiting_subtasks[0]["id"])
    second = storage.assign_slack_external_input(item["id"], waiting_subtasks[1]["id"])
    assert first["subtask_id"] == waiting_subtasks[0]["id"]
    assert first["status"] == "assigned"
    assert second is None
