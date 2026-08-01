"""Outbound-only Slack Socket Mode adapter.

Slack Bolt is optional and imported only by the executable factory. Tests use
injected app/client doubles and never open a network connection.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from threading import Event
from typing import Any

from src.service.slack.config import SlackSocketConfig
from src.service.slack.workflow import (
    SELECTION_ACTION_ID,
    SlackEnvelope,
    SlackWorkflow,
)
from src.storage import Storage, connect, run_migrations


class SocketModeRunner:
    def __init__(
        self,
        *,
        config: SlackSocketConfig,
        storage: Storage,
        app_factory: Callable[[SlackSocketConfig], object],
    ) -> None:
        self.config = config
        self.storage = storage
        self.workflow = SlackWorkflow(storage=storage, config=config)
        self.app = app_factory(config)

    def handle_envelope(
        self, payload: Mapping[str, Any], ack: Callable[[], None]
    ) -> None:
        """Validate and persist a supported envelope before acknowledging."""
        envelope = self._to_envelope(payload)
        self.workflow.accept(envelope)
        ack()

    def process_inbox_once(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.workflow.process_next(limit=limit)

    def process_outbox_once(self, limit: int = 20) -> list[dict[str, Any]]:
        client = getattr(self.app, "client", None)
        if client is None:
            raise RuntimeError("Slack app client is unavailable")
        results: list[dict[str, Any]] = []
        for row in self.storage.claim_slack_outbox(limit=limit):
            try:
                payload = row["payload"]
                kwargs: dict[str, Any] = {
                    "channel": row["channel_id"],
                    "text": str(payload.get("text") or ""),
                }
                if row.get("thread_ts"):
                    kwargs["thread_ts"] = row["thread_ts"]
                if payload.get("selection_actions"):
                    kwargs["blocks"] = _selection_blocks(payload["selection_actions"])
                if row["operation"] == "update":
                    kwargs.pop("thread_ts", None)
                    kwargs["ts"] = payload["ts"]
                    response = client.chat_update(**kwargs)
                else:
                    response = client.chat_postMessage(**kwargs)
                response_data = (
                    response
                    if isinstance(response, Mapping)
                    else getattr(response, "data", None)
                )
                if not isinstance(response_data, Mapping) or response_data.get("ok") is not True:
                    raise RuntimeError("slack-delivery-failed")
                if (
                    response_data.get("channel") != row["channel_id"]
                    or not response_data.get("ts")
                ):
                    raise RuntimeError("slack-delivery-mismatch")
                results.append(
                    self.storage.finish_slack_outbox(
                        row["operation_key"], slack_message_ts=str(response_data["ts"])
                    )
                )
            except Exception as exc:  # Slack SDK errors may vary by version
                code = "delivery-mismatch" if "mismatch" in str(exc) else "delivery-failed"
                results.append(
                    self.storage.fail_slack_outbox(row["operation_key"], error_code=code)
                )
        return results

    def handle_socket_request(
        self,
        client: object,
        request: object,
        response_factory: Callable[..., object],
    ) -> None:
        """Preserve the Socket Mode envelope identity through persistence/ack."""
        payload = getattr(request, "payload", None)
        if not isinstance(payload, Mapping):
            raise ValueError("invalid-socket-payload")
        envelope_id = str(getattr(request, "envelope_id", "") or "")
        if not envelope_id:
            raise ValueError("missing-envelope-id")
        raw = {
            "type": str(getattr(request, "type", "") or ""),
            "envelope_id": envelope_id,
            "event_id": payload.get("event_id"),
            "payload": payload,
        }

        def ack() -> None:
            client.send_socket_mode_response(response_factory(envelope_id=envelope_id))

        self.handle_envelope(raw, ack)

    @staticmethod
    def _to_envelope(raw: Mapping[str, Any]) -> SlackEnvelope:
        envelope_id = str(raw.get("envelope_id") or raw.get("event_id") or "")
        body = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
        socket_kind = str(raw.get("type") or "")
        kind = (
            str(body.get("type") or "")
            if socket_kind == "interactive"
            else socket_kind or str(body.get("type") or "")
        )
        team = body.get("team") if isinstance(body.get("team"), Mapping) else {}
        user = body.get("user") if isinstance(body.get("user"), Mapping) else {}
        if kind == "slash_commands":
            return SlackEnvelope(
                kind="command", envelope_id=envelope_id,
                event_id=str(raw.get("event_id") or "") or None,
                team_id=str(body.get("team_id") or team.get("id") or ""),
                channel_id=str(body.get("channel_id") or ""),
                actor_id=str(body.get("user_id") or user.get("id") or ""),
                payload={"command": body.get("command"), "text": body.get("text")},
            )
        if kind == "block_actions":
            actions = body.get("actions") if isinstance(body.get("actions"), list) else []
            action = actions[0] if actions and isinstance(actions[0], Mapping) else {}
            channel = body.get("channel") if isinstance(body.get("channel"), Mapping) else {}
            message = body.get("message") if isinstance(body.get("message"), Mapping) else {}
            container = body.get("container") if isinstance(body.get("container"), Mapping) else {}
            return SlackEnvelope(
                kind="interaction", envelope_id=envelope_id,
                event_id=str(raw.get("event_id") or "") or None,
                team_id=str(body.get("team_id") or team.get("id") or ""),
                channel_id=str(body.get("channel_id") or channel.get("id") or ""),
                actor_id=str(body.get("user_id") or user.get("id") or ""),
                payload={
                    "action_id": action.get("action_id"), "value": action.get("value"),
                    "thread_ts": container.get("thread_ts") or message.get("thread_ts") or message.get("ts"),
                },
            )
        event = body.get("event") if isinstance(body.get("event"), Mapping) else {}
        return SlackEnvelope(
            kind="reply", envelope_id=envelope_id,
            event_id=str(raw.get("event_id") or "") or None,
            team_id=str(body.get("team_id") or team.get("id") or ""),
            channel_id=str(event.get("channel") or ""),
            actor_id=str(event.get("user") or ""),
            payload={
                "text": event.get("text"), "thread_ts": event.get("thread_ts") or event.get("ts"),
                "bot_id": event.get("bot_id"), "is_bot": bool(event.get("subtype")),
            },
        )


def _selection_blocks(actions: Mapping[str, Any]) -> list[dict[str, Any]]:
    elements = [
        {
            "type": "button",
            "action_id": SELECTION_ACTION_ID,
            "text": {"type": "plain_text", "text": str(value.get("title") or "Select")[:75]},
            "value": key,
        }
        for key, value in actions.items()
        if isinstance(value, Mapping)
    ]
    return [{"type": "actions", "elements": elements}]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Sarathi Slack Socket Mode")
    parser.add_argument("--db", default=".sarathi/sarathi.db")
    args = parser.parse_args(argv)
    config = SlackSocketConfig.from_env()
    conn = connect(args.db)
    run_migrations(conn)
    try:
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web import WebClient
    except ImportError as exc:
        raise RuntimeError("Slack support is optional; install with: pip install 'sarathi-ai[slack]'") from exc
    web_client = WebClient(token=config.bot_token)
    socket_client = SocketModeClient(app_token=config.app_token, web_client=web_client)

    class _ClientHolder:
        client = web_client

    runner = SocketModeRunner(
        config=config, storage=Storage(conn), app_factory=lambda _: _ClientHolder()
    )
    socket_client.socket_mode_request_listeners.append(
        lambda client, request: runner.handle_socket_request(
            client, request, SocketModeResponse
        )
    )
    socket_client.connect()
    Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
