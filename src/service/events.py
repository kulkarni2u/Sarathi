"""Pure building blocks for a Server-Sent Events (SSE) stream of task events.

This module is intentionally HTTP-free and side-effect-free so it can be
unit tested in isolation. It provides two primitives:

- ``format_sse_event`` turns an event id, event type, and JSON-serializable
  data payload into a correctly framed SSE message (``id:``, ``event:``,
  one or more ``data:`` lines, terminated by a blank line).
- ``replay_events`` reads rows from the ``lifecycle_events`` table for a
  given workspace/task, ordered chronologically, and normalizes them into
  plain dicts. When ``after_id`` is supplied it returns only the events that
  occurred strictly after that event (Last-Event-ID semantics), which lets a
  reconnecting SSE client resume exactly where it left off.

A live "tailing" generator (not implemented here) would build on these two
functions directly: on connect, call ``replay_events`` (using the client's
``Last-Event-ID`` header as ``after_id``) and yield ``format_sse_event(...)``
for each historical row to "catch up" the client. Then it would poll
``lifecycle_events`` for new rows (e.g. every N seconds, or via a notification
mechanism), tracking the id of the most recently emitted event, and yield
``format_sse_event(...)`` for each newly observed row in the same way. Because
both helpers are pure, that loop is just plumbing — no new framing or
filtering logic would be needed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def format_sse_event(event_id: str, event_type: str, data: Any) -> str:
    """Format a single Server-Sent Event message.

    Produces an ``id:`` line, an ``event:`` line, one or more ``data:``
    lines, and a terminating blank line (``\\n\\n``) as required by the SSE
    protocol.

    ``data`` is JSON-encoded if it is a ``dict`` or ``list``; other values
    (e.g. strings) are converted to ``str`` and emitted as-is. If the
    serialized payload contains newlines, it is split across multiple
    ``data:`` lines, one per line of content, per the SSE spec.
    """
    if isinstance(data, (dict, list)):
        serialized = json.dumps(data, sort_keys=True)
    else:
        serialized = str(data)

    lines = [f"id: {event_id}", f"event: {event_type}"]
    for line in serialized.split("\n"):
        lines.append(f"data: {line}")

    return "\n".join(lines) + "\n\n"


def replay_events(
    storage_or_conn: Any,
    workspace_id: str,
    task_id: str,
    after_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return normalized ``lifecycle_events`` rows for a task, in order.

    ``storage_or_conn`` may be either a ``src.storage.Storage`` instance
    (or any object exposing a ``.conn`` attribute) or a raw
    ``sqlite3.Connection``.

    Rows are ordered chronologically by ``(created_at, id)`` to match the
    ordering used elsewhere in the storage layer. Each returned dict has the
    shape::

        {
            "id": str,
            "workspace_id": str,
            "task_id": str | None,
            "event_type": str,
            "payload": dict,
            "created_at": str,
        }

    If ``after_id`` is provided and refers to a known event for this
    workspace/task, only events strictly after it (in ``(created_at, id)``
    order) are returned -- this implements "Last-Event-ID" replay semantics
    for a reconnecting SSE client. If ``after_id`` does not match any known
    event, all events are returned.
    """
    conn = getattr(storage_or_conn, "conn", storage_or_conn)
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("storage_or_conn must be a Storage instance or sqlite3.Connection")

    rows = conn.execute(
        """
        SELECT id, workspace_id, task_id, event_type, payload, created_at
        FROM lifecycle_events
        WHERE workspace_id = ? AND task_id = ?
        ORDER BY created_at, id
        """,
        (workspace_id, task_id),
    ).fetchall()

    events = [_normalize_row(row) for row in rows]

    if after_id is None:
        return events

    for index, event in enumerate(events):
        if event["id"] == after_id:
            return events[index + 1 :]

    # Unknown after_id: nothing to skip, return the full backlog.
    return events


def _normalize_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload_raw = row["payload"]
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    elif isinstance(payload_raw, dict):
        payload = payload_raw
    else:
        payload = {}

    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "event_type": row["event_type"],
        "payload": payload,
        "created_at": row["created_at"],
    }
