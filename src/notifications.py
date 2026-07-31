"""Outbound notification channels for lifecycle events (Slack first).

Sarathi posts a message to a Slack channel when a run reaches an
attention-worthy moment: the task completes or fails, a phase pauses for
human input, the budget is exhausted, or the service records an approval
request. Both execution paths are covered:

- the lifecycle engine (CLI / TUI / MCP) emits via ``Engine._log_phase``,
- the HTTP service (Web / desktop) emits via the ``Storage`` lifecycle-event
  listener wired in ``ServiceApp`` and ``run_worker``.

Design rules:

- **Best-effort**: notification failures are logged and swallowed; they must
  never break or slow a run beyond the configured timeout.
- **Secrets stay in the environment**: policy files only name the env var
  that holds the webhook URL or bot token, never the value.
- **Policy decides what notifies**: the ``notifications.md`` policy file
  declares which event types post to Slack; the engine stays domain-agnostic.

Two Slack transports are supported:

- *Incoming webhook* (simplest): set ``SARATHI_SLACK_WEBHOOK_URL``. The
  channel is fixed by the webhook itself.
- *Bot token*: set ``SARATHI_SLACK_BOT_TOKEN`` plus a ``channel`` (policy key
  or ``SARATHI_SLACK_CHANNEL``); messages go through ``chat.postMessage`` so
  one token can post to any channel the bot is invited to.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Mapping

logger = logging.getLogger("sarathi.notifications")

DEFAULT_WEBHOOK_ENV = "SARATHI_SLACK_WEBHOOK_URL"
DEFAULT_BOT_TOKEN_ENV = "SARATHI_SLACK_BOT_TOKEN"
CHANNEL_ENV = "SARATHI_SLACK_CHANNEL"
EVENTS_ENV = "SARATHI_SLACK_EVENTS"
SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Event types that notify when the policy/env does not narrow the list.
# Patterns are fnmatch-style, so a policy can opt into e.g. "phase.*".
DEFAULT_EVENTS: tuple[str, ...] = (
    "task.completed",
    "task.failed",
    "task.paused",
    "task.escalated",
    "task.cancelled",
    "task.timed_out",
    "task.trust_gate_abort",
    "budget.exhausted",
    "approval.requested",
    "review.rejected",
    "handoff.created",
)

_EVENT_EMOJI = {
    "task.completed": "✅",
    "task.failed": "❌",
    "task.paused": "⏸️",
    "task.escalated": "⚠️",
    "task.cancelled": "\U0001f6d1",
    "task.timed_out": "⏱️",
    "task.trust_gate_abort": "⚠️",
    "budget.exhausted": "\U0001f4b8",
    "approval.requested": "\U0001f64b",
    "review.rejected": "❌",
    "handoff.created": "\U0001f91d",
}
_DEFAULT_EMOJI = "\U0001f514"

# Engine phase-log statuses mapped into the dotted event namespace shared
# with the service's lifecycle_events table.
_PHASE_STATUS_EVENTS = {
    "paused": "task.paused",
    "failed": "task.failed",
    "escalated": "task.escalated",
    "cancelled": "task.cancelled",
    "timed_out": "task.timed_out",
    "trust_gate_abort": "task.trust_gate_abort",
    "completed": "phase.completed",
    "skipped": "phase.skipped",
}

_TITLE_LIMIT = 140


@dataclass
class NotificationEvent:
    """A single notify-worthy moment, transport-agnostic."""

    event_type: str
    title: str
    task_id: str | None = None
    workspace_id: str | None = None
    details: dict[str, str] = field(default_factory=dict)


@dataclass
class SlackConfig:
    """Resolved Slack settings from policy and/or environment."""

    enabled: bool = False
    webhook_env: str = DEFAULT_WEBHOOK_ENV
    bot_token_env: str = DEFAULT_BOT_TOKEN_ENV
    channel: str | None = None
    events: tuple[str, ...] = DEFAULT_EVENTS
    timeout_seconds: float = 5.0

    @classmethod
    def from_policy(cls, section: Mapping[str, Any] | None) -> "SlackConfig":
        """Build from a compiled ``notifications`` policy section.

        Expected shape (all keys optional)::

            slack:
              enabled: true
              webhook_env: SARATHI_SLACK_WEBHOOK_URL
              bot_token_env: SARATHI_SLACK_BOT_TOKEN
              channel: "#sarathi-runs"
              timeout_seconds: 5
              events: [task.completed, task.failed, "approval.*"]
        """
        slack: Mapping[str, Any] = {}
        if isinstance(section, Mapping):
            candidate = section.get("slack")
            if isinstance(candidate, Mapping):
                slack = candidate
        events = _normalize_events(slack.get("events")) or DEFAULT_EVENTS
        try:
            timeout = float(slack.get("timeout_seconds", 5.0))
        except (TypeError, ValueError):
            timeout = 5.0
        channel = slack.get("channel")
        return cls(
            enabled=bool(slack.get("enabled", False)),
            webhook_env=str(slack.get("webhook_env", DEFAULT_WEBHOOK_ENV)),
            bot_token_env=str(slack.get("bot_token_env", DEFAULT_BOT_TOKEN_ENV)),
            channel=str(channel) if channel else None,
            events=events,
            timeout_seconds=timeout,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SlackConfig":
        """Build from environment variables alone (service path / no policy)."""
        env = os.environ if env is None else env
        enabled = bool(env.get(DEFAULT_WEBHOOK_ENV) or env.get(DEFAULT_BOT_TOKEN_ENV))
        events = _normalize_events(env.get(EVENTS_ENV, "").split(",")) or DEFAULT_EVENTS
        return cls(
            enabled=enabled,
            channel=env.get(CHANNEL_ENV) or None,
            events=events,
        )


def _normalize_events(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


class SlackNotifier:
    """Posts NotificationEvents to Slack; never raises out of ``notify``."""

    def __init__(
        self,
        config: SlackConfig,
        env: Mapping[str, str] | None = None,
        opener: Callable[..., Any] | None = None,
    ):
        self.config = config
        self._env = os.environ if env is None else env
        self._opener = opener or urllib.request.urlopen

    @property
    def webhook_url(self) -> str | None:
        return self._env.get(self.config.webhook_env) or None

    @property
    def bot_token(self) -> str | None:
        return self._env.get(self.config.bot_token_env) or None

    def is_configured(self) -> bool:
        if not self.config.enabled:
            return False
        if self.webhook_url:
            return True
        return bool(self.bot_token and self.config.channel)

    def matches(self, event_type: str) -> bool:
        return any(fnmatch(event_type, pattern) for pattern in self.config.events)

    def notify(self, event: NotificationEvent, *, thread_ts: str | None = None) -> bool:
        """Post the event to Slack. Returns True only on confirmed delivery."""
        if not self.is_configured() or not self.matches(event.event_type):
            return False
        message = build_slack_message(event)
        if thread_ts:
            message["thread_ts"] = thread_ts
        try:
            if self.webhook_url:
                return self._post_json(self.webhook_url, message, headers={})
            payload = dict(message)
            payload["channel"] = self.config.channel
            return self._post_json(
                SLACK_POST_MESSAGE_URL,
                payload,
                headers={"Authorization": f"Bearer {self.bot_token}"},
            )
        except Exception as exc:  # best-effort by contract: never break a run
            logger.warning(
                "Slack notification failed for %s: %s", event.event_type, exc
            )
            return False

    def _post_raw(
        self, url: str, payload: dict[str, Any], *, headers: dict[str, str]
    ) -> tuple[int, bytes]:
        """Post a JSON payload and return (status, raw_bytes)."""
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with self._opener(request, timeout=self.config.timeout_seconds) as response:
            status = getattr(response, "status", 200)
            raw = response.read()
        return status, raw

    def _post_json(
        self, url: str, payload: dict[str, Any], *, headers: dict[str, str]
    ) -> bool:
        status, raw = self._post_raw(url, payload, headers=headers)
        if status >= 300:
            logger.warning("Slack returned HTTP %s", status)
            return False
        # chat.postMessage reports errors in the JSON body with HTTP 200.
        if url == SLACK_POST_MESSAGE_URL:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return False
            if not parsed.get("ok", False):
                logger.warning("Slack API error: %s", parsed.get("error", "unknown"))
                return False
        return True

    def post_message(self, channel: str, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Post via chat.postMessage (bot-token mode only). Returns {"channel","ts"} from
        the parsed Slack response on success, or None (webhook-only mode, missing bot
        token/channel, HTTP error, or Slack ok:false). Never raises — same best-effort
        contract as notify()."""
        if not self.bot_token:
            return None

        payload = dict(message)
        payload["channel"] = channel

        try:
            status, raw = self._post_raw(
                SLACK_POST_MESSAGE_URL,
                payload,
                headers={"Authorization": f"Bearer {self.bot_token}"},
            )

            if status >= 300:
                return None

            parsed = json.loads(raw.decode("utf-8"))
            if not parsed.get("ok"):
                return None

            return {"channel": parsed.get("channel"), "ts": parsed.get("ts")}
        except Exception as exc:
            logger.warning("post_message failed: %s", exc)
            return None


def build_slack_message(event: NotificationEvent) -> dict[str, Any]:
    """Render a NotificationEvent as a Slack Block Kit payload."""
    emoji = _EVENT_EMOJI.get(event.event_type, _DEFAULT_EMOJI)
    headline = f"{emoji} {event.title}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{emoji} *{event.title}*"},
        },
    ]
    fields = [
        {"type": "mrkdwn", "text": f"*{key}:*\n{value}"}
        for key, value in event.details.items()
        if value
    ]
    if fields:
        # Slack caps section fields at 10 entries.
        blocks.append({"type": "section", "fields": fields[:10]})
    context_bits = ["Sarathi", event.event_type]
    if event.task_id:
        context_bits.append(f"task `{event.task_id}`")
    if event.workspace_id:
        context_bits.append(f"workspace `{event.workspace_id}`")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " · ".join(context_bits)}],
        }
    )
    return {"text": headline, "blocks": blocks}


def build_gate_approval_message(
    *, task_id: str, gate_id: str, title: str,
    acceptance_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """Block Kit payload with an approve/reject action block for a pending gate."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*"},
        },
    ]
    if acceptance_criteria:
        criteria_text = "\n".join(f"• {item}" for item in acceptance_criteria[:10])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": criteria_text},
        })
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "approve_gate",
                "value": f"{task_id}:{gate_id}",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reject"},
                "style": "danger",
                "action_id": "reject_gate",
                "value": f"{task_id}:{gate_id}",
            },
        ],
    })
    return {"text": title, "blocks": blocks}


def build_gate_decision_text(*, status: str, gate_id: str, user: str | None) -> str:
    """Plain text summarizing a resolved decision, e.g. for replace_original updates."""
    user_name = user or "someone"
    if status == "approved":
        return f"✅ Approved by {user_name}"
    else:
        return f"❌ Rejected by {user_name}"


def build_slack_notifier(
    policy_section: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> SlackNotifier | None:
    """Return a ready SlackNotifier, or None when Slack is not configured.

    When a ``notifications`` policy section is present its ``enabled`` flag
    governs. When the policy pack has no notifications section at all, the
    environment auto-enables (exporting ``SARATHI_SLACK_WEBHOOK_URL`` is
    enough for CLI users without a policy edit).
    """
    has_policy = isinstance(policy_section, Mapping) and bool(policy_section)
    config = (
        SlackConfig.from_policy(policy_section)
        if has_policy
        else SlackConfig.from_env(env)
    )
    notifier = SlackNotifier(config, env=env, opener=opener)
    if not notifier.is_configured():
        return None
    return notifier


def post_response_url(
    response_url: str, payload: Mapping[str, Any], *,
    timeout_seconds: float = 5.0, opener: Callable[..., Any] | None = None,
) -> bool:
    """Bare-urllib POST to a Slack response_url (e.g. {"replace_original": True, "text": ...}).
    Never raises; returns True only on HTTP < 300."""
    try:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            response_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        http_opener = opener or urllib.request.urlopen
        with http_opener(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
        return status < 300
    except Exception:
        return False


def phase_event(
    task_id: str,
    description: str,
    phase: str,
    status: str,
    *,
    final_phase: bool = False,
) -> NotificationEvent | None:
    """Map an engine phase-log entry to a NotificationEvent, or None.

    Per-phase "completed"/"skipped" entries map to ``phase.*`` types (off by
    default); the final Learn completion is promoted to ``task.completed``.
    """
    event_type = _PHASE_STATUS_EVENTS.get(status)
    if event_type is None:
        return None
    if final_phase and status == "completed":
        event_type = "task.completed"
    summary = _truncate(description)
    return NotificationEvent(
        event_type=event_type,
        title=f"Task {task_id}: {summary}" if summary else f"Task {task_id}",
        task_id=task_id,
        details={"Phase": phase, "Status": status.replace("_", " ")},
    )


def budget_exhausted_event(
    task_id: str,
    description: str,
    consumed_tokens: int,
    max_total_tokens: int,
) -> NotificationEvent:
    """Event for a run pausing because its token budget ran out."""
    summary = _truncate(description)
    return NotificationEvent(
        event_type="budget.exhausted",
        title=f"Task {task_id} paused — token budget exhausted",
        task_id=task_id,
        details={
            "Task": summary,
            "Tokens": f"{consumed_tokens}/{max_total_tokens}",
        },
    )


def lifecycle_notification(event: Mapping[str, Any]) -> NotificationEvent | None:
    """Convert a service ``lifecycle_events`` row into a NotificationEvent."""
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        return None
    payload = event.get("payload")
    details: dict[str, str] = {}
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)):
                details[str(key).replace("_", " ").title()] = _truncate(str(value))
            if len(details) >= 8:
                break
    label = event_type.replace(".", " ").replace("_", " ").title()
    task_id = event.get("task_id")
    title = f"{label} — task {task_id}" if task_id else label
    return NotificationEvent(
        event_type=event_type,
        title=title,
        task_id=str(task_id) if task_id else None,
        workspace_id=str(event.get("workspace_id") or "") or None,
        details=details,
    )


def lifecycle_event_listener(
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    get_task: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> Callable[[Mapping[str, Any]], None] | None:
    """Storage listener that forwards lifecycle events to Slack, or None.

    Wired into ``Storage(conn, event_listener=...)`` by the HTTP service and
    the work-queue worker. Configuration is environment-only on this path
    (the service is multi-workspace, so there is no single policy pack).
    """
    notifier = build_slack_notifier(None, env=env, opener=opener)
    if notifier is None:
        return None

    def _listen(event: Mapping[str, Any]) -> None:
        notification = lifecycle_notification(event)
        if notification is None:
            return
        thread_ts = None
        if get_task is not None and notification.task_id and notifier.matches(notification.event_type):
            try:
                task = get_task(notification.task_id)
                meta = (task or {}).get("metadata")
                slack = meta.get("slack") if isinstance(meta, Mapping) else None
                if isinstance(slack, Mapping):
                    ts = slack.get("thread_ts")
                    thread_ts = str(ts) if ts else None
            except Exception:
                thread_ts = None
        notifier.notify(notification, thread_ts=thread_ts)

    return _listen


def _truncate(text: str, limit: int = _TITLE_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
