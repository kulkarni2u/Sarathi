"""Authorization and idempotent domain workflow for Slack envelopes.

This module is transport-independent: it consumes typed ``SlackEnvelope``
objects plus the Task 2 storage surface and never connects to Slack. The
Socket Mode adapter (Task 6) is responsible for translating raw Slack
payloads into envelopes and acknowledging them only after ``accept`` has
persisted the validated inbox row.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, NoReturn

from src.service.slack.config import SlackSocketConfig
from src.service.slack.security import (
    VALIDATION_VERSION,
    SlackInputRejected,
    validate_slack_text,
)
from src.storage import Storage

logger = logging.getLogger("sarathi.slack.workflow")

COMMAND_NAME = "/sarathi-task"
DECISION_ACTION_ID = "sarathi_gate_decision"
GATE_ACTIONS_KEY = "slack_decision_actions"
PROVISIONAL_PREFIX = "provisional:"
SECURITY_EVENT_TYPE = "slack.security_rejected"


class SlackAuthorizationError(RuntimeError):
    """The envelope is not authorized or its content is rejected.

    ``reason`` is a stable, redacted code. No raw Slack text, tokens, team
    domain, username, or response URL is ever included.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SlackEnvelope:
    """A typed, untrusted Slack input carrying only routing identifiers.

    ``payload`` is the validated subset of the Socket Mode payload relevant
    to the workflow (never the raw envelope). ``kind`` is one of ``command``,
    ``interaction``, or ``reply``.
    """

    kind: str
    envelope_id: str
    event_id: str | None
    team_id: str
    channel_id: str
    actor_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


def _opaque_action_value() -> str:
    return secrets.token_urlsafe(18)


def _derive_task_title(prompt: str) -> str:
    words = prompt.strip().split()
    if not words:
        return "Untitled orchestrated task"
    title = " ".join(words[:8]).strip(" .")
    return title[:80] or "Untitled orchestrated task"


def _text_digest(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SlackWorkflow:
    """Authorize, durably accept, and idempotently process Slack envelopes.

    Authorization failures and prompt-injection rejections happen before any
    inbox or task persistence; the only rejection persistence is a redacted
    lifecycle security event (``SECURITY_EVENT_TYPE``).
    """

    def __init__(self, *, storage: Storage, config: SlackSocketConfig) -> None:
        self._storage = storage
        self._config = config

    # -- acceptance ----------------------------------------------------------

    def accept(self, envelope: SlackEnvelope) -> dict[str, Any]:
        """Authorize and durably accept ``envelope``.

        Returns a result suitable for immediate Socket acknowledgement. A
        duplicate ``envelope_id`` returns the canonical inbox result and never
        creates another row.
        """
        self._authorize_kind(envelope)
        self._authorize_routing(envelope)
        self._authorize_actor(envelope)

        if envelope.kind == "command":
            return self._accept_command(envelope)
        return self._accept_interaction(envelope)

    def _authorize_kind(self, envelope: SlackEnvelope) -> None:
        if envelope.kind not in ("command", "interaction"):
            self._reject(envelope, reason="kind-not-supported")

    def _authorize_routing(self, envelope: SlackEnvelope) -> None:
        if envelope.team_id != self._config.team_id:
            self._reject(envelope, reason="team-not-authorized")
        if envelope.channel_id not in self._config.channel_ids:
            self._reject(envelope, reason="channel-not-authorized")

    def _authorize_actor(self, envelope: SlackEnvelope) -> None:
        if self._is_bot(envelope):
            self._reject(envelope, reason="bot-actor")
        if envelope.kind == "interaction" and envelope.actor_id not in self._config.approver_ids:
            self._reject(envelope, reason="not-approver")

    @staticmethod
    def _is_bot(envelope: SlackEnvelope) -> bool:
        payload = envelope.payload
        if payload.get("is_bot") is True or payload.get("user_type") == "bot":
            return True
        if isinstance(payload.get("bot_id"), str) and payload["bot_id"]:
            return True
        return envelope.actor_id.startswith("B")

    def _accept_command(self, envelope: SlackEnvelope) -> dict[str, Any]:
        if envelope.payload.get("command") != COMMAND_NAME:
            self._reject(envelope, reason="unknown-command")
        raw_text = envelope.payload.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            self._reject(envelope, reason="empty-command-text")
        try:
            validated = validate_slack_text(
                raw_text,
                actor_id=envelope.actor_id,
                channel_id=envelope.channel_id,
                event_id=envelope.event_id or envelope.envelope_id,
            )
        except SlackInputRejected as exc:
            self._record_security_event(
                envelope,
                reason=exc.reason,
                length=len(raw_text),
                digest=_text_digest(raw_text),
                validation_version=VALIDATION_VERSION,
            )
            raise SlackAuthorizationError("input-rejected") from exc
        content = {
            "kind": "command",
            "command": COMMAND_NAME,
            "text": validated.text,
            "validation_version": validated.validation_version,
            "digest": validated.digest,
        }
        return self._enqueue(envelope, event_type="slash_commands", content=content)

    def _accept_interaction(self, envelope: SlackEnvelope) -> dict[str, Any]:
        if envelope.payload.get("action_id") != DECISION_ACTION_ID:
            return {
                "acknowledged": True,
                "ignored": True,
                "envelope_id": envelope.envelope_id,
                "reason": "unknown-action-type",
            }
        value = envelope.payload.get("value")
        if not isinstance(value, str) or not value:
            self._reject(envelope, reason="missing-action-value")
        content = {
            "kind": "interaction",
            "action_id": DECISION_ACTION_ID,
            "value": value,
            "thread_ts": envelope.payload.get("thread_ts"),
        }
        return self._enqueue(envelope, event_type="block_actions", content=content)

    def _enqueue(
        self,
        envelope: SlackEnvelope,
        *,
        event_type: str,
        content: Mapping[str, Any],
    ) -> dict[str, Any]:
        row = self._storage.enqueue_slack_event(
            envelope_id=envelope.envelope_id,
            event_id=envelope.event_id,
            workspace_id=self._config.workspace_id,
            team_id=envelope.team_id,
            channel_id=envelope.channel_id,
            actor_id=envelope.actor_id,
            event_type=event_type,
            content=content,
        )
        return {
            "acknowledged": True,
            "envelope_id": envelope.envelope_id,
            "status": row["status"],
            "event_type": row["event_type"],
            "duplicate": row["status"] != "pending",
        }

    def _reject(self, envelope: SlackEnvelope, *, reason: str) -> NoReturn:
        self._record_security_event(envelope, reason=reason)
        raise SlackAuthorizationError(reason)

    def _record_security_event(
        self,
        envelope: SlackEnvelope,
        *,
        reason: str,
        length: int | None = None,
        digest: str | None = None,
        validation_version: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "reason": reason,
            "kind": envelope.kind,
            "envelope_id": envelope.envelope_id,
            "event_id": envelope.event_id,
            "actor_id": envelope.actor_id,
            "channel_id": envelope.channel_id,
        }
        if length is not None:
            payload["length"] = length
        if digest is not None:
            payload["digest"] = digest
        if validation_version is not None:
            payload["validation_version"] = validation_version
        try:
            self._storage.create_lifecycle_event(
                workspace_id=self._config.workspace_id,
                task_id=None,
                event_type=SECURITY_EVENT_TYPE,
                payload=payload,
            )
        except Exception:
            logger.warning("Failed to record Slack security event", exc_info=True)

    # -- processing ----------------------------------------------------------

    def process_next(self, limit: int = 20) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in self._storage.claim_slack_events(limit=limit):
            kind = row["content"].get("kind")
            if kind == "command":
                results.append(self._process_command(row))
            elif kind == "interaction":
                results.append(self._process_interaction(row))
            else:
                self._storage.finish_slack_event(
                    row["envelope_id"], status="rejected", error_code="unknown-kind"
                )
                results.append(
                    {
                        "envelope_id": row["envelope_id"],
                        "kind": kind,
                        "status": "rejected",
                        "error_code": "unknown-kind",
                    }
                )
        return results

    def _process_command(self, row: Mapping[str, Any]) -> dict[str, Any]:
        content = row["content"]
        thread_ts = PROVISIONAL_PREFIX + row["envelope_id"]
        result = self._storage.create_slack_command_task(
            envelope_id=row["envelope_id"],
            workspace_id=row["workspace_id"],
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            actor_id=row["actor_id"],
            thread_ts=thread_ts,
            title=_derive_task_title(content["text"]),
            prompt=content["text"],
            validation_version=content["validation_version"],
            digest=content["digest"],
            approve_action=_opaque_action_value(),
            reject_action=_opaque_action_value(),
        )
        return {
            "envelope_id": row["envelope_id"],
            "kind": "command",
            "status": "processed",
            "task_id": result["task_id"],
            "gate_id": result["gate_id"],
            "duplicate": result["duplicate"],
        }

    def _process_interaction(self, row: Mapping[str, Any]) -> dict[str, Any]:
        content = row["content"]
        value = content.get("value")
        thread_ts = content.get("thread_ts")
        gate = (
            self._storage.find_slack_gate_by_action_value(value)
            if isinstance(value, str)
            else None
        )
        if gate is None:
            self._record_security_event_from_row(row, reason="unknown-action")
            self._storage.finish_slack_event(
                row["envelope_id"], status="rejected", error_code="unknown-action"
            )
            return {
                "envelope_id": row["envelope_id"],
                "kind": "interaction",
                "status": "rejected",
                "error_code": "unknown-action",
            }

        if not self._binding_matches(row, gate, thread_ts):
            self._record_security_event_from_row(row, reason="binding-mismatch")
            self._storage.finish_slack_event(
                row["envelope_id"], status="rejected", error_code="binding-mismatch"
            )
            return {
                "envelope_id": row["envelope_id"],
                "kind": "interaction",
                "status": "rejected",
                "error_code": "binding-mismatch",
            }

        requested = self._requested_status(gate, value)
        if requested is None:
            self._record_security_event_from_row(row, reason="unknown-action")
            self._storage.finish_slack_event(
                row["envelope_id"], status="rejected", error_code="unknown-action"
            )
            return {
                "envelope_id": row["envelope_id"],
                "kind": "interaction",
                "status": "rejected",
                "error_code": "unknown-action",
            }

        result = self._storage.apply_slack_gate_decision(
            envelope_id=row["envelope_id"],
            gate_id=gate["id"],
            task_id=gate["task_id"],
            requested_status=requested,
            actor_id=row["actor_id"],
            operation_key=f"gate-decision:{gate['id']}:{row['envelope_id']}",
            workspace_id=row["workspace_id"],
            channel_id=row["channel_id"],
            thread_ts=thread_ts,
            payload={"text": f"Gate decision recorded: {requested}"},
        )
        return {
            "envelope_id": row["envelope_id"],
            "kind": "interaction",
            "status": "processed",
            "gate_id": gate["id"],
            "gate_status": result["gate_status"],
            "applied": result["applied"],
        }

    def _binding_matches(
        self,
        row: Mapping[str, Any],
        gate: Mapping[str, Any],
        thread_ts: Any,
    ) -> bool:
        if not isinstance(thread_ts, str) or not thread_ts:
            return False
        binding = self._storage.get_slack_task_binding(
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            thread_ts=thread_ts,
        )
        if binding is None:
            return False
        return binding["task_id"] == gate["task_id"]

    @staticmethod
    def _requested_status(gate: Mapping[str, Any], value: str) -> str | None:
        actions = gate["metadata"].get(GATE_ACTIONS_KEY)
        if not isinstance(actions, Mapping):
            return None
        if actions.get("approve") == value:
            return "approved"
        if actions.get("reject") == value:
            return "rejected"
        return None

    def _record_security_event_from_row(
        self,
        row: Mapping[str, Any],
        *,
        reason: str,
    ) -> None:
        content = row["content"]
        payload: dict[str, Any] = {
            "reason": reason,
            "kind": content.get("kind"),
            "envelope_id": row["envelope_id"],
            "event_id": row["event_id"],
            "actor_id": row["actor_id"],
            "channel_id": row["channel_id"],
        }
        try:
            self._storage.create_lifecycle_event(
                workspace_id=row["workspace_id"],
                task_id=None,
                event_type=SECURITY_EVENT_TYPE,
                payload=payload,
            )
        except Exception:
            logger.warning("Failed to record Slack security event", exc_info=True)
