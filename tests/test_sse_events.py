import json

from src.service.events import format_sse_event, replay_events
from src.storage import Storage, connect, run_migrations


def test_format_sse_event_framing_with_dict_data():
    text = format_sse_event("evt-1", "task.updated", {"status": "in_progress"})

    lines = text.split("\n")
    assert lines[0] == "id: evt-1"
    assert lines[1] == "event: task.updated"
    assert lines[2] == 'data: {"status": "in_progress"}'
    # Terminated by a blank line (i.e. the message ends with "\n\n").
    assert text.endswith("\n\n")
    assert json.loads(lines[2][len("data: ") :]) == {"status": "in_progress"}


def test_format_sse_event_framing_with_list_data():
    text = format_sse_event("evt-2", "task.events", [1, 2, 3])

    assert text == 'id: evt-2\nevent: task.events\ndata: [1, 2, 3]\n\n'


def test_format_sse_event_multiline_data_uses_multiple_data_lines():
    text = format_sse_event("evt-3", "log.line", "line one\nline two")

    assert text == "id: evt-3\nevent: log.line\ndata: line one\ndata: line two\n\n"


def test_replay_events_orders_chronologically_and_normalizes(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Do the thing",
            status="in_progress",
        )

        first = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.created",
            payload={"object_id": task["id"]},
        )
        second = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.in_progress",
            payload={"object_id": task["id"], "note": "started"},
        )
        third = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.blocked",
            payload={"object_id": task["id"], "reason": "waiting on approval"},
        )

        events = replay_events(storage, workspace["id"], task["id"])

        assert [event["id"] for event in events] == [
            first["id"],
            second["id"],
            third["id"],
        ]
        assert [event["event_type"] for event in events] == [
            "task.created",
            "task.in_progress",
            "task.blocked",
        ]
        # Payload is normalized to a dict (decoded from JSON storage).
        assert events[1]["payload"] == {"object_id": task["id"], "note": "started"}
        assert events[0]["workspace_id"] == workspace["id"]
        assert events[0]["task_id"] == task["id"]
        assert "created_at" in events[0]


def test_replay_events_after_id_filters_to_later_events(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Do the thing",
            status="in_progress",
        )

        first = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.created",
            payload={"object_id": task["id"]},
        )
        second = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.in_progress",
            payload={"object_id": task["id"]},
        )
        third = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.blocked",
            payload={"object_id": task["id"]},
        )

        # Last-Event-ID == first event -> only events after it are returned.
        after_first = replay_events(storage, workspace["id"], task["id"], after_id=first["id"])
        assert [event["id"] for event in after_first] == [second["id"], third["id"]]

        # Last-Event-ID == last event -> nothing new to replay.
        after_third = replay_events(storage, workspace["id"], task["id"], after_id=third["id"])
        assert after_third == []

        # No after_id -> full backlog.
        all_events = replay_events(storage, workspace["id"], task["id"])
        assert len(all_events) == 3


def test_replay_events_scopes_to_workspace_and_task(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        other_workspace = storage.create_workspace(name="Other", root_path="/tmp/other")

        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Task A",
            status="in_progress",
        )
        other_task = storage.create_task(
            workspace_id=workspace["id"],
            title="Task B",
            status="in_progress",
        )

        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.created",
            payload={"object_id": task["id"]},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=other_task["id"],
            event_type="task.created",
            payload={"object_id": other_task["id"]},
        )
        storage.create_lifecycle_event(
            workspace_id=other_workspace["id"],
            task_id=task["id"],
            event_type="task.created",
            payload={"object_id": task["id"]},
        )

        events = replay_events(storage, workspace["id"], task["id"])

        assert len(events) == 1
        assert events[0]["task_id"] == task["id"]
        assert events[0]["workspace_id"] == workspace["id"]


def test_replay_events_accepts_raw_connection(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Task A",
            status="in_progress",
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.created",
            payload={"object_id": task["id"]},
        )

        # Pass the raw sqlite3.Connection directly (not the Storage wrapper).
        events = replay_events(conn, workspace["id"], task["id"])

        assert len(events) == 1
        assert events[0]["event_type"] == "task.created"
