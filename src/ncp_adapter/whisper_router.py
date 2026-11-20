"""NCPWhisperRouter — targeted signals between graph nodes via NCP whispers.

A whisper is queued for one target agent (``s.<node_id>``) inside one
pipeline (``sarathi_<task_id>``), so a signal reaches only the node it was
sent to, in the task that sent it. Node ids such as ``n1-branch-1`` repeat
across tasks; the pipeline keeps them apart.

Sarathi's signal kind (``fanout_context``, ``classify_context``,
``judge_context``) travels inside the JSON payload as ``kind``: NCP's own
whisper types are a fixed set, and these signals are ``nudge`` whispers,
which carry free-form payloads (at most 600 characters).

Receiving is supported in direct mode (``.ncp/run.py`` version 4). In MCP
mode whispers are emitted but not read back here, because NCP's MCP surface
returns whisper payloads only inside ``ncp_get_context``'s display block.
"""

from __future__ import annotations

import json
from typing import Any

from ._transport import NCPTransportMixin

MAX_PAYLOAD_CHARS = 600


def pipeline_for_task(task_id: str) -> str:
    """NCP pipeline that scopes one Sarathi task's whispers (as for handoffs)."""
    return f"sarathi_{task_id}"


def agent_for_node(node_id: str) -> str:
    return f"s.{node_id}"


class NCPWhisperRouter(NCPTransportMixin):
    """Emits, reads and acknowledges NCP whispers for graph-node coordination."""

    def emit(
        self,
        from_agent: str,
        target: str,
        whisper_type: str,
        payload: str,
        confidence: float = 0.90,
        *,
        pipeline_id: str | None = None,
    ) -> str | None:
        """Queue a signal of Sarathi kind ``whisper_type`` for ``target``.

        Returns the whisper id. Raises ``ValueError`` when the payload with
        its ``kind`` exceeds NCP's 600-character limit.
        """
        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            body = None
        if not isinstance(body, dict):
            body = {"text": payload}
        body = {"kind": whisper_type, **body}
        encoded = json.dumps(body, separators=(",", ":"))
        if len(encoded) > MAX_PAYLOAD_CHARS:
            raise ValueError(f"payload must be <= {MAX_PAYLOAD_CHARS} characters")
        return self._call_emit_whisper(
            from_agent=from_agent,
            target=target,
            payload=encoded,
            pipeline_id=pipeline_id,
            confidence=confidence,
        )

    def poll(
        self, agent_id: str, max_items: int = 3, *, pipeline_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Signals queued for ``agent_id`` (not consumed), each as a dict.

        Each dict is the decoded payload plus ``whisper_id`` and
        ``from_agent``. Returns an empty list when nothing is queued or the
        transport cannot read whispers.
        """
        signals: list[dict[str, Any]] = []
        for whisper in self._call_peek_whispers(
            agent_id=agent_id, pipeline_id=pipeline_id, max_items=max_items
        ):
            try:
                body = json.loads(str(whisper.get("payload", "")))
            except json.JSONDecodeError:
                body = {"text": whisper.get("payload")}
            if not isinstance(body, dict):
                body = {"text": body}
            signals.append(
                {**body, "whisper_id": whisper.get("whisper_id"), "from_agent": whisper.get("from_agent")}
            )
        return signals

    def ack(self, agent_id: str, whisper_ids: list[str]) -> int:
        """Acknowledge signals the node has acted on, so they are not re-delivered."""
        return self._call_ack_whispers(agent_id=agent_id, whisper_ids=whisper_ids)
