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
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, NoReturn, Sequence

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
SELECTION_ACTION_ID = "sarathi_reply_selection"
GATE_ACTIONS_KEY = "slack_decision_actions"
REPLY_SELECTIONS_KEY = "reply_selections"
PROVISIONAL_PREFIX = "provisional:"
SECURITY_EVENT_TYPE = "slack.security_rejected"
MAX_THREAD_TS_LENGTH = 64


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


def _stable_error_code(exc: Exception) -> str:
    """Map an exception to a stable, redacted code for inbox error_code.

    The raw exception message can contain task text, IDs, or secrets and is
    never persisted; only the bounded code below reaches the database.
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return "integrity-error"
    if isinstance(exc, sqlite3.OperationalError):
        return "database-locked"
    if isinstance(exc, sqlite3.DatabaseError):
        return "database-error"
    if isinstance(exc, ValueError):
        return "value-error"
    if isinstance(exc, KeyError):
        return "missing-row"
    return "internal-error"


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

        if envelope.kind == "command":
            self._authorize_actor(envelope)
            return self._accept_command(envelope)
        if envelope.kind == "reply":
            return self._accept_reply(envelope)
        if envelope.payload.get("action_id") == SELECTION_ACTION_ID:
            return self._accept_reply_selection(envelope)
        self._authorize_actor(envelope)
        return self._accept_interaction(envelope)

    def _authorize_kind(self, envelope: SlackEnvelope) -> None:
        if envelope.kind not in ("command", "interaction", "reply"):
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
        thread_ts = envelope.payload.get("thread_ts")
        if (
            not isinstance(thread_ts, str)
            or not thread_ts
            or len(thread_ts) > MAX_THREAD_TS_LENGTH
        ):
            self._reject(envelope, reason="invalid-thread-ts")
        content = {
            "kind": "interaction",
            "action_id": DECISION_ACTION_ID,
            "value": value,
            "thread_ts": thread_ts,
        }
        return self._enqueue(envelope, event_type="block_actions", content=content)

    def _accept_reply_selection(self, envelope: SlackEnvelope) -> dict[str, Any]:
        """Authorize a reply-selection click before any inbox persistence.

        The button value is an opaque token resolved against the bound task's
        stored ambiguity selections. Authorization is bound to the exact
        ``(team_id, channel_id, thread_ts)`` task binding, the same
        workspace, and the intended actor (the replier who triggered the
        ambiguity message). Processing revalidates all of these.
        """
        if self._is_bot(envelope):
            self._reject(envelope, reason="bot-actor")
        value = envelope.payload.get("value")
        if not isinstance(value, str) or not value:
            self._reject(envelope, reason="missing-action-value")
        thread_ts = envelope.payload.get("thread_ts")
        if (
            not isinstance(thread_ts, str)
            or not thread_ts
            or len(thread_ts) > MAX_THREAD_TS_LENGTH
        ):
            self._reject(envelope, reason="invalid-thread-ts")
        binding = self._storage.get_slack_task_binding(
            team_id=envelope.team_id,
            channel_id=envelope.channel_id,
            thread_ts=thread_ts,
        )
        if binding is None or binding["workspace_id"] != self._config.workspace_id:
            self._reject(envelope, reason="unknown-thread-binding")
        task = self._storage.get_task(binding["task_id"])
        if task is None:
            self._reject(envelope, reason="unknown-thread-binding")
        selection = self._selections_for_task(task).get(value)
        if selection is None:
            self._reject(envelope, reason="unknown-selection")
        if envelope.actor_id != selection.get("actor_id"):
            self._reject(envelope, reason="not-authorized-selector")
        content = {
            "kind": "interaction",
            "action_id": SELECTION_ACTION_ID,
            "value": value,
            "thread_ts": thread_ts,
        }
        return self._enqueue(envelope, event_type="block_actions", content=content)

    def _accept_reply(self, envelope: SlackEnvelope) -> dict[str, Any]:
        """Authorize and durably accept a human thread reply.

        The exact ``(team_id, channel_id, thread_ts)`` binding is resolved
        before any persistence so replies to unknown threads fail closed.
        """
        thread_ts = envelope.payload.get("thread_ts")
        if (
            not isinstance(thread_ts, str)
            or not thread_ts
            or len(thread_ts) > MAX_THREAD_TS_LENGTH
        ):
            self._reject(envelope, reason="invalid-thread-ts")
        if self._is_bot(envelope):
            self._reject(envelope, reason="bot-actor")
        binding = self._storage.get_slack_task_binding(
            team_id=envelope.team_id,
            channel_id=envelope.channel_id,
            thread_ts=thread_ts,
        )
        if binding is None or binding["workspace_id"] != self._config.workspace_id:
            self._reject(envelope, reason="unknown-thread-binding")
        if (
            envelope.actor_id not in self._config.approver_ids
            and binding.get("requester_user_id") != envelope.actor_id
        ):
            self._reject(envelope, reason="not-authorized-replier")
        raw_text = envelope.payload.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            self._reject(envelope, reason="empty-reply-text")
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
            "kind": "reply",
            "task_id": binding["task_id"],
            "thread_ts": thread_ts,
            "text": validated.text,
            "validation_version": validated.validation_version,
            "digest": validated.digest,
        }
        return self._enqueue(envelope, event_type="message", content=content)

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
            "duplicate": bool(row.get("duplicate", False)),
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
            try:
                if kind == "command":
                    results.append(self._process_command(row))
                elif kind == "interaction":
                    results.append(self._process_interaction(row))
                elif kind == "reply":
                    results.append(self._process_reply(row))
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
            except Exception as exc:  # noqa: BLE001 - per-row isolation
                # A processing failure must never strand the row in
                # 'processing' nor stop the remaining rows. Persist only a
                # stable redacted code, requeue below the bound, and terminal-
                # fail at the bound (mirrors the outbox retry semantics).
                error_code = _stable_error_code(exc)
                try:
                    failed = self._storage.fail_slack_event(
                        row["envelope_id"], error_code=error_code
                    )
                except Exception:
                    logger.warning(
                        "Failed to mark Slack inbox row failed", exc_info=True
                    )
                    results.append(
                        {
                            "envelope_id": row["envelope_id"],
                            "kind": kind,
                            "status": "failed",
                            "error_code": error_code,
                        }
                    )
                    continue
                results.append(
                    {
                        "envelope_id": row["envelope_id"],
                        "kind": kind,
                        "status": failed["status"],
                        "error_code": error_code,
                        "attempt_count": failed["attempt_count"],
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
        if content.get("action_id") == SELECTION_ACTION_ID:
            return self._process_reply_selection(row)
        value = content.get("value")
        thread_ts = content.get("thread_ts")
        gate = (
            self._storage.find_slack_gate_by_action_value(
                value, workspace_id=row["workspace_id"]
            )
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
            workspace_id=gate["workspace_id"],
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

    def _process_reply(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Apply one validated human reply to the bound task's waiters.

        Zero waiters store an unassigned validated input; one waiter is
        atomically assigned and resumed; multiple waiters create an ambiguity
        message with authorization-bound selection buttons and resume none.
        """
        content = row["content"]
        thread_ts = content.get("thread_ts")
        if not isinstance(thread_ts, str) or not thread_ts:
            return self._reject_reply_row(row, reason="invalid-thread-ts")
        binding = self._storage.get_slack_task_binding(
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            thread_ts=thread_ts,
        )
        if (
            binding is None
            or binding["workspace_id"] != row["workspace_id"]
            or binding["task_id"] != content.get("task_id")
        ):
            return self._reject_reply_row(row, reason="binding-mismatch")
        if row["actor_id"].startswith("B") or (
            row["actor_id"] not in self._config.approver_ids
            and binding.get("requester_user_id") != row["actor_id"]
        ):
            return self._reject_reply_row(row, reason="not-authorized-replier")

        waiting = [
            subtask
            for subtask in self._storage.list_subtasks_for_task(binding["task_id"])
            if subtask["status"] == "waiting_human"
        ]
        if len(waiting) == 1:
            applied = self._resume_single_waiter(row, binding, content, waiting[0])
            self._storage.finish_slack_event(row["envelope_id"], status="processed")
            return {
                "envelope_id": row["envelope_id"],
                "kind": "reply",
                "status": "processed",
                "task_id": binding["task_id"],
                "subtask_id": waiting[0]["id"],
                "waiter_count": 1,
                "applied": applied,
            }
        if len(waiting) == 0:
            self._store_unassigned_input(row, binding, content)
            self._storage.enqueue_slack_outbox(
                operation_key=f"reply-ack:{row['envelope_id']}",
                workspace_id=row["workspace_id"],
                task_id=binding["task_id"],
                channel_id=row["channel_id"],
                thread_ts=content.get("thread_ts"),
                operation="message",
                payload={"text": "Your reply was received and stored."},
            )
            self._storage.finish_slack_event(row["envelope_id"], status="processed")
            return {
                "envelope_id": row["envelope_id"],
                "kind": "reply",
                "status": "processed",
                "task_id": binding["task_id"],
                "waiter_count": 0,
                "applied": False,
            }
        self._create_ambiguity(row, binding, content, waiting)
        self._storage.finish_slack_event(row["envelope_id"], status="processed")
        return {
            "envelope_id": row["envelope_id"],
            "kind": "reply",
            "status": "processed",
            "task_id": binding["task_id"],
            "waiter_count": len(waiting),
            "applied": False,
        }

    def _reject_reply_row(self, row: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
        self._record_security_event_from_row(row, reason=reason)
        self._storage.finish_slack_event(
            row["envelope_id"], status="rejected", error_code=reason
        )
        return {
            "envelope_id": row["envelope_id"],
            "kind": "reply",
            "status": "rejected",
            "error_code": reason,
        }

    def _resume_single_waiter(
        self,
        row: Mapping[str, Any],
        binding: Mapping[str, Any],
        content: Mapping[str, Any],
        subtask: Mapping[str, Any],
    ) -> bool:
        """Create the validated reply unassigned, then atomically resume one waiter.

        The input row is always created ``unassigned`` and the storage
        transaction performs the compare-and-set assignment plus the
        ``waiting_human`` → ``in_progress`` transition in one commit; a lost
        race returns False and leaves the input unassigned for later selection.
        """
        created = self._storage.create_slack_external_input(
            envelope_id=row["envelope_id"],
            workspace_id=row["workspace_id"],
            task_id=binding["task_id"],
            actor_id=row["actor_id"],
            channel_id=row["channel_id"],
            text=content["text"],
            validation_version=content["validation_version"],
            digest=content["digest"],
            subtask_id=None,
        )
        result = self._storage.assign_slack_external_input_and_resume_subtask(
            created["id"], subtask["id"]
        )
        return result is not None

    def _store_unassigned_input(
        self,
        row: Mapping[str, Any],
        binding: Mapping[str, Any],
        content: Mapping[str, Any],
    ) -> None:
        self._storage.create_slack_external_input(
            envelope_id=row["envelope_id"],
            workspace_id=row["workspace_id"],
            task_id=binding["task_id"],
            actor_id=row["actor_id"],
            channel_id=row["channel_id"],
            text=content["text"],
            validation_version=content["validation_version"],
            digest=content["digest"],
            subtask_id=None,
        )

    def _create_ambiguity(
        self,
        row: Mapping[str, Any],
        binding: Mapping[str, Any],
        content: Mapping[str, Any],
        waiting_subtasks: Sequence[Mapping[str, Any]],
    ) -> None:
        """Store an unassigned reply and post one opaque button per waiter."""
        input_row = self._storage.create_slack_external_input(
            envelope_id=row["envelope_id"],
            workspace_id=row["workspace_id"],
            task_id=binding["task_id"],
            actor_id=row["actor_id"],
            channel_id=row["channel_id"],
            text=content["text"],
            validation_version=content["validation_version"],
            digest=content["digest"],
            subtask_id=None,
        )
        selections: dict[str, Any] = {}
        for subtask in waiting_subtasks:
            selections[_opaque_action_value()] = {
                "subtask_id": subtask["id"],
                "input_id": input_row["id"],
                "title": subtask.get("title") or subtask.get("id"),
                "actor_id": row["actor_id"],
            }
        task = self._storage.get_task(binding["task_id"])
        if task is None:
            raise RuntimeError("missing task for reply ambiguity")
        raw_metadata = task.get("metadata")
        if not isinstance(raw_metadata, Mapping):
            raw_metadata = {}
        task_metadata = dict(raw_metadata)
        raw_slack = task_metadata.get("slack")
        if not isinstance(raw_slack, Mapping):
            raw_slack = {}
        slack_meta = dict(raw_slack)
        slack_meta[REPLY_SELECTIONS_KEY] = selections
        task_metadata["slack"] = slack_meta
        self._storage.update_task(task_id=task["id"], metadata=task_metadata)
        self._storage.enqueue_slack_outbox(
            operation_key=f"reply-ambiguity:{row['envelope_id']}",
            workspace_id=row["workspace_id"],
            task_id=binding["task_id"],
            channel_id=row["channel_id"],
            thread_ts=content.get("thread_ts"),
            operation="message",
            payload={
                "text": "Multiple subtasks are waiting for your input. Choose one:",
                "selection_actions": selections,
            },
        )

    def _process_reply_selection(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Atomically bind a stored reply to exactly one still-waiting subtask."""
        content = row["content"]
        value = content.get("value")
        thread_ts = content.get("thread_ts")
        if not isinstance(value, str) or not value:
            return self._reject_selection_row(row, reason="missing-selection-value")
        binding = self._storage.get_slack_task_binding(
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            thread_ts=thread_ts,
        )
        if binding is None or binding["workspace_id"] != row["workspace_id"]:
            return self._reject_selection_row(row, reason="binding-mismatch")
        task = self._storage.get_task(binding["task_id"])
        if task is None:
            return self._reject_selection_row(row, reason="binding-mismatch")
        selection = self._selections_for_task(task).get(value)
        if selection is None:
            return self._reject_selection_row(row, reason="unknown-selection")
        if row["actor_id"].startswith("B") or (
            row["actor_id"] != selection.get("actor_id")
        ):
            return self._reject_selection_row(row, reason="not-authorized-selector")
        subtask = self._storage.get_subtask(selection["subtask_id"])
        if subtask is None or subtask["status"] != "waiting_human":
            self._storage.finish_slack_event(row["envelope_id"], status="processed")
            return {
                "envelope_id": row["envelope_id"],
                "kind": "interaction",
                "status": "processed",
                "applied": False,
                "reason": "stale-selection",
            }
        assigned = self._storage.assign_slack_external_input_and_resume_subtask(
            selection["input_id"], selection["subtask_id"]
        )
        if assigned is None:
            self._storage.finish_slack_event(row["envelope_id"], status="processed")
            return {
                "envelope_id": row["envelope_id"],
                "kind": "interaction",
                "status": "processed",
                "applied": False,
                "reason": "already-assigned",
            }
        self._storage.finish_slack_event(row["envelope_id"], status="processed")
        return {
            "envelope_id": row["envelope_id"],
            "kind": "interaction",
            "status": "processed",
            "applied": True,
            "subtask_id": selection["subtask_id"],
        }

    def _reject_selection_row(self, row: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
        self._record_security_event_from_row(row, reason=reason)
        self._storage.finish_slack_event(
            row["envelope_id"], status="rejected", error_code=reason
        )
        return {
            "envelope_id": row["envelope_id"],
            "kind": "interaction",
            "status": "rejected",
            "error_code": reason,
        }

    @staticmethod
    def _selections_for_task(task: Mapping[str, Any]) -> Mapping[str, Any]:
        raw_metadata = task.get("metadata")
        if not isinstance(raw_metadata, Mapping):
            raw_metadata = {}
        raw_slack = raw_metadata.get("slack")
        if not isinstance(raw_slack, Mapping):
            raw_slack = {}
        selections = raw_slack.get(REPLY_SELECTIONS_KEY)
        if isinstance(selections, Mapping):
            return selections
        return {}

    def _binding_matches(
        self,
        row: Mapping[str, Any],
        gate: Mapping[str, Any],
        thread_ts: Any,
    ) -> bool:
        if not isinstance(thread_ts, str) or not thread_ts:
            return False
        if gate["workspace_id"] != row["workspace_id"]:
            return False
        binding = self._storage.get_slack_task_binding(
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            thread_ts=thread_ts,
        )
        if binding is None:
            return False
        if binding["workspace_id"] != row["workspace_id"]:
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
