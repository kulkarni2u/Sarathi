"""Tests for Slack notification channel (src/notifications.py)."""

import json

from src.notifications import (
    DEFAULT_EVENTS,
    SLACK_POST_MESSAGE_URL,
    NotificationEvent,
    SlackConfig,
    SlackNotifier,
    budget_exhausted_event,
    build_slack_message,
    build_slack_notifier,
    lifecycle_event_listener,
    lifecycle_notification,
    phase_event,
)
from src.engine import Complexity, Engine, Phase, TaskContext
from src.storage import Storage, connect, run_migrations


class FakeResponse:
    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Captures urllib requests; returns queued responses."""

    def __init__(self, responses=None, error=None):
        self.requests = []
        self.responses = list(responses or [])
        self.error = error

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse()

    def last_payload(self):
        request, _ = self.requests[-1]
        return json.loads(request.data.decode("utf-8"))


# ---------------------------------------------------------------- config


def test_config_from_policy_reads_slack_block():
    config = SlackConfig.from_policy(
        {
            "slack": {
                "enabled": True,
                "channel": "#deploys",
                "events": ["task.failed", "approval.*"],
                "timeout_seconds": 2,
            }
        }
    )
    assert config.enabled is True
    assert config.channel == "#deploys"
    assert config.events == ("task.failed", "approval.*")
    assert config.timeout_seconds == 2.0


def test_config_from_policy_defaults_disabled():
    config = SlackConfig.from_policy({"slack": {}})
    assert config.enabled is False
    assert config.events == DEFAULT_EVENTS


def test_config_from_env_auto_enables_on_webhook():
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    config = SlackConfig.from_env(env)
    assert config.enabled is True
    assert config.events == DEFAULT_EVENTS

    assert SlackConfig.from_env({}).enabled is False


def test_config_from_env_parses_events_and_channel():
    env = {
        "SARATHI_SLACK_BOT_TOKEN": "xoxb-1",
        "SARATHI_SLACK_CHANNEL": "#runs",
        "SARATHI_SLACK_EVENTS": "task.failed, phase.*",
    }
    config = SlackConfig.from_env(env)
    assert config.channel == "#runs"
    assert config.events == ("task.failed", "phase.*")


# ---------------------------------------------------------------- factory


def test_build_notifier_none_without_secret():
    section = {"slack": {"enabled": True}}
    assert build_slack_notifier(section, env={}) is None


def test_build_notifier_policy_disabled_wins_over_env():
    section = {"slack": {"enabled": False}}
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    assert build_slack_notifier(section, env=env) is None


def test_build_notifier_never_creates_legacy_http_transport_implicitly():
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    notifier = build_slack_notifier(None, env=env)
    assert notifier is None


# ---------------------------------------------------------------- filtering


def test_event_filter_supports_globs():
    config = SlackConfig(enabled=True, events=("approval.*", "task.failed"))
    notifier = SlackNotifier(config, env={"SARATHI_SLACK_WEBHOOK_URL": "https://x"})
    assert notifier.matches("approval.requested")
    assert notifier.matches("task.failed")
    assert not notifier.matches("task.completed")
    assert not notifier.matches("phase.completed")


# ---------------------------------------------------------------- transports


def test_webhook_post_sends_blocks():
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/services/T/B/x"}
    notifier = SlackNotifier(SlackConfig(enabled=True), env=env, opener=opener)
    event = NotificationEvent(
        event_type="task.failed",
        title="Task t-1: fix checkout",
        task_id="t-1",
        details={"Phase": "Build", "Status": "failed"},
    )

    assert notifier.notify(event) is True
    request, timeout = opener.requests[0]
    assert request.full_url == "https://slack.invalid/services/T/B/x"
    assert timeout == 5.0
    payload = opener.last_payload()
    assert payload["text"].endswith("Task t-1: fix checkout")
    assert payload["blocks"][0]["type"] == "section"
    field_texts = [f["text"] for f in payload["blocks"][1]["fields"]]
    assert any("Build" in text for text in field_texts)


def test_bot_token_posts_to_chat_post_message():
    opener = FakeOpener(responses=[FakeResponse(body=b'{"ok": true}')])
    env = {"SARATHI_SLACK_BOT_TOKEN": "bot-test-token"}
    config = SlackConfig(enabled=True, channel="#runs")
    notifier = SlackNotifier(config, env=env, opener=opener)

    assert notifier.notify(NotificationEvent("task.completed", "Task done")) is True
    request, _ = opener.requests[0]
    assert request.full_url == SLACK_POST_MESSAGE_URL
    assert request.get_header("Authorization") == "Bearer bot-test-token"
    assert opener.last_payload()["channel"] == "#runs"


def test_bot_token_api_error_returns_false():
    opener = FakeOpener(
        responses=[FakeResponse(body=b'{"ok": false, "error": "channel_not_found"}')]
    )
    config = SlackConfig(enabled=True, channel="#nope")
    notifier = SlackNotifier(
        config, env={"SARATHI_SLACK_BOT_TOKEN": "xoxb"}, opener=opener
    )
    assert notifier.notify(NotificationEvent("task.completed", "Task done")) is False


def test_bot_token_without_channel_not_configured():
    config = SlackConfig(enabled=True)
    notifier = SlackNotifier(config, env={"SARATHI_SLACK_BOT_TOKEN": "xoxb"})
    assert not notifier.is_configured()


def test_notify_swallows_network_errors():
    opener = FakeOpener(error=OSError("connection refused"))
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    notifier = SlackNotifier(SlackConfig(enabled=True), env=env, opener=opener)
    assert notifier.notify(NotificationEvent("task.failed", "boom")) is False


def test_notify_skips_unmatched_event_without_request():
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    config = SlackConfig(enabled=True, events=("task.failed",))
    notifier = SlackNotifier(config, env=env, opener=opener)
    assert notifier.notify(NotificationEvent("task.completed", "done")) is False
    assert opener.requests == []


# ---------------------------------------------------------------- event mapping


def test_phase_event_maps_engine_statuses():
    event = phase_event("t-1", "Fix the failing checkout test", "Build", "failed")
    assert event is not None
    assert event.event_type == "task.failed"
    assert "t-1" in event.title
    assert event.details["Phase"] == "Build"

    paused = phase_event("t-1", "desc", "Review", "paused")
    assert paused is not None and paused.event_type == "task.paused"


def test_phase_event_promotes_final_learn_completion():
    mid = phase_event("t-1", "desc", "Build", "completed")
    assert mid is not None and mid.event_type == "phase.completed"

    final = phase_event("t-1", "desc", "Learn", "completed", final_phase=True)
    assert final is not None and final.event_type == "task.completed"


def test_phase_event_returns_none_for_unknown_status():
    assert phase_event("t-1", "desc", "Build", "started") is None


def test_phase_event_truncates_long_description():
    event = phase_event("t-1", "x" * 500, "Build", "failed")
    assert event is not None
    assert len(event.title) < 200


def test_budget_exhausted_event_shape():
    event = budget_exhausted_event("t-2", "big refactor", 50000, 50000)
    assert event.event_type == "budget.exhausted"
    assert event.details["Tokens"] == "50000/50000"


def test_lifecycle_notification_from_storage_row():
    notification = lifecycle_notification(
        {
            "event_type": "approval.requested",
            "task_id": "task-9",
            "workspace_id": "ws-1",
            "payload": {"gate": "Repository action", "count": 2},
        }
    )
    assert notification is not None
    assert notification.event_type == "approval.requested"
    assert notification.task_id == "task-9"
    assert notification.workspace_id == "ws-1"
    assert notification.details["Gate"] == "Repository action"


def test_lifecycle_notification_rejects_missing_type():
    assert lifecycle_notification({"payload": {}}) is None


def test_build_slack_message_context_includes_ids():
    message = build_slack_message(
        NotificationEvent("task.failed", "Boom", task_id="t-3", workspace_id="ws-2")
    )
    context = message["blocks"][-1]["elements"][0]["text"]
    assert "t-3" in context and "ws-2" in context


# ---------------------------------------------------------------- storage listener


def test_storage_listener_fires_on_lifecycle_event(tmp_path):
    seen = []
    with connect(tmp_path / "svc.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=seen.append)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            event_type="approval.requested",
            payload={"gate": "g"},
        )
    # workspace creation does not emit; only the explicit lifecycle event does
    assert [e["event_type"] for e in seen] == ["approval.requested"]


def test_storage_listener_errors_do_not_break_writes(tmp_path):
    def explode(_event):
        raise RuntimeError("listener bug")

    with connect(tmp_path / "svc.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=explode)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        event = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            event_type="task.created",
        )
    assert event["event_type"] == "task.created"


def test_lifecycle_event_listener_end_to_end(tmp_path):
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}
    listener = lifecycle_event_listener(env=env, opener=opener)
    assert listener is not None

    with connect(tmp_path / "svc.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            event_type="approval.requested",
            task_id=None,
            payload={"summary": "needs a human"},
        )
        # Filtered-out event type: no Slack call.
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            event_type="message.created",
        )

    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "Approval Requested" in payload["text"]


def test_lifecycle_event_listener_none_when_unconfigured():
    assert lifecycle_event_listener(env={}) is None


# ---------------------------------------------------------------- engine hook


class StubNotifier:
    def __init__(self):
        self.events = []

    def notify(self, event):
        self.events.append(event)
        return True


def test_engine_notifier_defaults_to_none(monkeypatch):
    # No notifications policy in the default pack and no Slack env vars ->
    # the engine runs without a notifier.
    monkeypatch.delenv("SARATHI_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SARATHI_SLACK_BOT_TOKEN", raising=False)
    engine = Engine()
    assert engine.notifier is None
    task = TaskContext(
        task_id="t-quiet", description="quiet", complexity=Complexity.LOW
    )
    # _notify_phase must be a no-op, not an error, when unconfigured.
    engine._notify_phase(task, Phase.BUILD, "failed")


def test_engine_notify_phase_forwards_mapped_events():
    engine = Engine()
    stub = StubNotifier()
    engine.notifier = stub
    task = TaskContext(task_id="t-9", description="fix bug", complexity=Complexity.LOW)

    engine._notify_phase(task, Phase.BUILD, "failed")
    engine._notify_phase(task, Phase.REVIEW, "paused")
    engine._notify_phase(task, Phase.LEARN, "completed")
    engine._notify_phase(task, Phase.BUILD, "started")  # unmapped: dropped

    assert [e.event_type for e in stub.events] == [
        "task.failed",
        "task.paused",
        "task.completed",
    ]
    assert all(e.task_id == "t-9" for e in stub.events)


def test_engine_run_emits_task_completed():
    engine = Engine()
    stub = StubNotifier()
    engine.notifier = stub
    task = TaskContext(
        task_id="t-run", description="Test task", complexity=Complexity.LOW
    )
    engine.run_task(task)
    assert "task.completed" in [e.event_type for e in stub.events]


# ---------------------------------------------------------------- thread linking


def test_notify_with_thread_ts_webhook():
    """Posting to webhook with thread_ts includes it in the JSON payload."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/services/T/B/x"}
    notifier = SlackNotifier(SlackConfig(enabled=True), env=env, opener=opener)
    event = NotificationEvent(
        event_type="task.failed",
        title="Task t-1: fix checkout",
        task_id="t-1",
    )

    assert notifier.notify(event, thread_ts="1700000000.123456") is True
    payload = opener.last_payload()
    assert payload["thread_ts"] == "1700000000.123456"


def test_notify_with_thread_ts_bot_token():
    """Posting via bot token with thread_ts includes it in the JSON payload."""
    opener = FakeOpener(responses=[FakeResponse(body=b'{"ok": true}')])
    env = {"SARATHI_SLACK_BOT_TOKEN": "bot-test-token"}
    config = SlackConfig(enabled=True, channel="#runs")
    notifier = SlackNotifier(config, env=env, opener=opener)
    event = NotificationEvent("task.completed", "Task done", task_id="t-1")

    assert notifier.notify(event, thread_ts="1700000000.999") is True
    payload = opener.last_payload()
    assert payload["thread_ts"] == "1700000000.999"
    assert payload["channel"] == "#runs"


def test_notify_without_thread_ts_no_key_in_payload():
    """Posting without thread_ts (default behavior) does not include the key."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/services/T/B/x"}
    notifier = SlackNotifier(SlackConfig(enabled=True), env=env, opener=opener)
    event = NotificationEvent("task.completed", "Task done", task_id="t-1")

    assert notifier.notify(event) is True
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_notify_with_none_thread_ts_no_key_in_payload():
    """Explicitly passing thread_ts=None does not include the key."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/services/T/B/x"}
    notifier = SlackNotifier(SlackConfig(enabled=True), env=env, opener=opener)
    event = NotificationEvent("task.completed", "Task done", task_id="t-1")

    assert notifier.notify(event, thread_ts=None) is True
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_lifecycle_event_listener_with_get_task_thread_ts(tmp_path):
    """Listener with get_task forwards thread_ts from task metadata to notifier."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    def fake_get_task(task_id):
        return {
            "id": task_id,
            "metadata": {
                "slack": {
                    "thread_ts": "1700000000.555",
                    "channel_id": "C-ABC",
                }
            },
        }

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.completed",
            payload={"summary": "success"},
        )

    # Verify notifier was called with thread_ts
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert payload["thread_ts"] == "1700000000.555"


def test_lifecycle_event_listener_get_task_returns_none(tmp_path):
    """When get_task returns None, listener still posts without thread_ts."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    def fake_get_task(task_id):
        return None  # task not found

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.failed",
            payload={"summary": "error"},
        )

    # Post happens without thread_ts
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_lifecycle_event_listener_get_task_missing_slack_metadata(tmp_path):
    """When task metadata lacks 'slack' key, listener posts without thread_ts."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    def fake_get_task(task_id):
        return {
            "id": task_id,
            "metadata": {
                "source": "github_issue",
                # no 'slack' key
            },
        }

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.paused",
            payload={},
        )

    # Post happens without thread_ts
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_lifecycle_event_listener_get_task_metadata_none(tmp_path):
    """When task.metadata is None, listener posts without thread_ts."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    def fake_get_task(task_id):
        return {
            "id": task_id,
            "metadata": None,  # No metadata at all
        }

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.escalated",
            payload={},
        )

    # Post happens without thread_ts
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_lifecycle_event_listener_get_task_raises_exception(tmp_path):
    """When get_task raises an exception, listener still posts without thread_ts."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    def fake_get_task(task_id):
        raise RuntimeError("database error")

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.timed_out",
            payload={},
        )

    # Post happens without thread_ts, no exception raised
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "thread_ts" not in payload


def test_lifecycle_event_listener_unmatched_event_skips_get_task_call(tmp_path):
    """When event type doesn't match notifier config, get_task is not called."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    call_count = 0

    def fake_get_task(task_id):
        nonlocal call_count
        call_count += 1
        return {"id": task_id, "metadata": {"slack": {"thread_ts": "123.456"}}}

    listener = lifecycle_event_listener(env=env, opener=opener, get_task=fake_get_task)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        # Post a non-matching event (message.created is not in DEFAULT_EVENTS)
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="message.created",
            payload={},
        )

    # get_task should never have been called
    assert call_count == 0
    # No Slack request should have been made
    assert len(opener.requests) == 0


def test_lifecycle_event_listener_default_get_task_none(tmp_path):
    """Listener without get_task still works (existing behavior regression test)."""
    opener = FakeOpener()
    env = {"SARATHI_SLACK_WEBHOOK_URL": "https://slack.invalid/x"}

    # No get_task provided (None/default)
    listener = lifecycle_event_listener(env=env, opener=opener)
    assert listener is not None

    with connect(tmp_path / "test.db") as conn:
        run_migrations(conn)
        storage = Storage(conn, event_listener=listener)
        workspace = storage.create_workspace(name="w", root_path=str(tmp_path))
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Test task",
            status="running",
            description="Test",
            metadata={},
        )
        storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.completed",
            payload={},
        )

    # Post happens normally without thread_ts (unchanged behavior)
    assert len(opener.requests) == 1
    payload = opener.last_payload()
    assert "thread_ts" not in payload
