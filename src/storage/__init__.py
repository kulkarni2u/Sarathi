"""SQLite storage primitives for Sarathi UI state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


LATEST_SCHEMA_VERSION = 2


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite database connection configured for repository use."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("schema_version",),
    ).fetchone()
    if row is None:
        return 0

    version = conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
    return int(version["version"] or 0)


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending SQLite migrations."""
    if current_schema_version(conn) < 1:
        conn.executescript(_MIGRATION_001)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (1, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 2:
        conn.executescript(_MIGRATION_002)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (2, _utc_now()),
        )
        conn.commit()


class Storage:
    """Small repository facade for persisted Sarathi UI records."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_workspace(
        self,
        *,
        name: str,
        root_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, name, root_path, _dump_json(metadata), now, now),
        )
        self.conn.commit()
        workspace = self.get_workspace(workspace_id)
        assert workspace is not None
        return workspace

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, name, root_path, metadata, created_at, updated_at
            FROM workspaces
            WHERE id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return _workspace_from_row(row) if row is not None else None

    def list_workspaces(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, name, root_path, metadata, created_at, updated_at
            FROM workspaces
            ORDER BY created_at, id
            """
        ).fetchall()
        return [_workspace_from_row(row) for row in rows]

    def create_workspace_repository(
        self,
        *,
        workspace_id: str,
        path: str,
        name: str | None = None,
        remote_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repository_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO workspace_repositories (
                id, workspace_id, name, path, remote_url, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository_id,
                workspace_id,
                name,
                path,
                remote_url,
                _dump_json(metadata),
                now,
                now,
            ),
        )
        self.conn.commit()
        repository = self.get_workspace_repository(repository_id)
        assert repository is not None
        return repository

    def get_workspace_repository(self, repository_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, name, path, remote_url, metadata, created_at, updated_at
            FROM workspace_repositories
            WHERE id = ?
            """,
            (repository_id,),
        ).fetchone()
        return _workspace_repository_from_row(row) if row is not None else None

    def update_workspace_repository(
        self,
        repository_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_workspace_repository(repository_id)
        if existing is None:
            raise KeyError(repository_id)
        now = _utc_now()
        next_metadata = metadata if metadata is not None else existing["metadata"]
        self.conn.execute(
            """
            UPDATE workspace_repositories
            SET metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (_dump_json(next_metadata), now, repository_id),
        )
        self.conn.commit()
        repository = self.get_workspace_repository(repository_id)
        assert repository is not None
        return repository

    def list_workspace_repositories(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, name, path, remote_url, metadata, created_at, updated_at
            FROM workspace_repositories
            WHERE workspace_id = ?
            ORDER BY created_at, id
            """,
            (workspace_id,),
        ).fetchall()
        return [_workspace_repository_from_row(row) for row in rows]

    def create_task(
        self,
        *,
        workspace_id: str,
        title: str,
        status: str = "pending",
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO tasks (
                id, workspace_id, title, description, status, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                workspace_id,
                title,
                description,
                status,
                _dump_json(metadata),
                now,
                now,
            ),
        )
        self.conn.commit()
        task = self.get_task(task_id)
        assert task is not None
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, title, description, status, metadata, created_at, updated_at
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        return _task_from_row(row) if row is not None else None

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_task(task_id)
        if existing is None:
            raise KeyError(task_id)
        next_status = status if status is not None else existing["status"]
        next_metadata = metadata if metadata is not None else existing["metadata"]
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE tasks
            SET status = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_status, _dump_json(next_metadata), now, task_id),
        )
        self.conn.commit()
        task = self.get_task(task_id)
        assert task is not None
        return task

    def list_tasks_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, title, description, status, metadata, created_at, updated_at
            FROM tasks
            WHERE workspace_id = ?
            ORDER BY created_at, id
            """,
            (workspace_id,),
        ).fetchall()
        return [_task_from_row(row) for row in rows]

    def create_subtask(
        self,
        *,
        workspace_id: str,
        task_id: str,
        title: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        subtask_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO subtasks (
                id, workspace_id, task_id, title, status, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (subtask_id, workspace_id, task_id, title, status, _dump_json(metadata), now, now),
        )
        self.conn.commit()
        subtask = self.get_subtask(subtask_id)
        assert subtask is not None
        return subtask

    def get_subtask(self, subtask_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at
            FROM subtasks
            WHERE id = ?
            """,
            (subtask_id,),
        ).fetchone()
        return _subtask_from_row(row) if row is not None else None

    def update_subtask(
        self,
        subtask_id: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_subtask(subtask_id)
        if existing is None:
            raise KeyError(subtask_id)
        next_status = status if status is not None else existing["status"]
        next_metadata = metadata if metadata is not None else existing["metadata"]
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE subtasks
            SET status = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_status, _dump_json(next_metadata), now, subtask_id),
        )
        self.conn.commit()
        subtask = self.get_subtask(subtask_id)
        assert subtask is not None
        return subtask

    def list_subtasks_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at
            FROM subtasks
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_subtask_from_row(row) for row in rows]

    def create_message(
        self,
        *,
        workspace_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO messages (
                id, workspace_id, task_id, role, content, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, workspace_id, task_id, role, content, _dump_json(metadata), now),
        )
        self.conn.commit()
        message = self.get_message(message_id)
        assert message is not None
        return message

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, role, content, metadata, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        return _message_from_row(row) if row is not None else None

    def list_messages(
        self,
        *,
        workspace_id: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[str] = []
        if workspace_id is not None:
            filters.append("workspace_id = ?")
            params.append(workspace_id)
        if task_id is not None:
            filters.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self.conn.execute(
            f"""
            SELECT id, workspace_id, task_id, role, content, metadata, created_at
            FROM messages
            {where}
            ORDER BY created_at, id
            """,
            tuple(params),
        ).fetchall()
        return [_message_from_row(row) for row in rows]

    def create_approval_gate(
        self,
        *,
        workspace_id: str,
        task_id: str,
        name: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        gate_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO approval_gates (
                id, workspace_id, task_id, name, status, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (gate_id, workspace_id, task_id, name, status, _dump_json(metadata), now, now),
        )
        self.conn.commit()
        gate = self.get_approval_gate(gate_id)
        assert gate is not None
        return gate

    def get_approval_gate(self, gate_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, name, status, metadata, created_at, updated_at
            FROM approval_gates
            WHERE id = ?
            """,
            (gate_id,),
        ).fetchone()
        return _approval_gate_from_row(row) if row is not None else None

    def list_approval_gates_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, name, status, metadata, created_at, updated_at
            FROM approval_gates
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_approval_gate_from_row(row) for row in rows]

    def create_lifecycle_event(
        self,
        *,
        workspace_id: str,
        event_type: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO lifecycle_events (
                id, workspace_id, task_id, event_type, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, workspace_id, task_id, event_type, _dump_json(payload), now),
        )
        self.conn.commit()
        event = self.get_lifecycle_event(event_id)
        assert event is not None
        return event

    def get_lifecycle_event(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, event_type, payload, created_at
            FROM lifecycle_events
            WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        return _event_from_row(row) if row is not None else None

    def list_events(
        self,
        *,
        workspace_id: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[str] = []
        if workspace_id is not None:
            filters.append("workspace_id = ?")
            params.append(workspace_id)
        if task_id is not None:
            filters.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self.conn.execute(
            f"""
            SELECT id, workspace_id, task_id, event_type, payload, created_at
            FROM lifecycle_events
            {where}
            ORDER BY created_at, id
            """,
            tuple(params),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def create_dispatch(
        self,
        *,
        workspace_id: str,
        task_id: str,
        agent_name: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dispatch_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO dispatches (
                id, workspace_id, task_id, agent_name, status, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dispatch_id, workspace_id, task_id, agent_name, status, _dump_json(metadata), now, now),
        )
        self.conn.commit()
        dispatch = self.get_dispatch(dispatch_id)
        assert dispatch is not None
        return dispatch

    def get_dispatch(self, dispatch_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, agent_name, status, metadata, created_at, updated_at
            FROM dispatches
            WHERE id = ?
            """,
            (dispatch_id,),
        ).fetchone()
        return _dispatch_from_row(row) if row is not None else None

    def list_dispatches_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, agent_name, status, metadata, created_at, updated_at
            FROM dispatches
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_dispatch_from_row(row) for row in rows]

    def create_evidence_artifact(
        self,
        *,
        workspace_id: str,
        task_id: str,
        artifact_type: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO evidence_artifacts (
                id, workspace_id, task_id, artifact_type, uri, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, workspace_id, task_id, artifact_type, uri, _dump_json(metadata), now),
        )
        self.conn.commit()
        evidence = self.get_evidence_artifact(evidence_id)
        assert evidence is not None
        return evidence

    def get_evidence_artifact(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, artifact_type, uri, metadata, created_at
            FROM evidence_artifacts
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()
        return _evidence_from_row(row) if row is not None else None

    def list_evidence_artifacts_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, artifact_type, uri, metadata, created_at
            FROM evidence_artifacts
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_evidence_from_row(row) for row in rows]

    def create_review_run(
        self,
        *,
        workspace_id: str,
        task_id: str,
        status: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        review_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO review_runs (
                id, workspace_id, task_id, status, summary, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, workspace_id, task_id, status, summary, _dump_json(metadata), now, now),
        )
        self.conn.commit()
        review = self.get_review_run(review_id)
        assert review is not None
        return review

    def get_review_run(self, review_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, status, summary, metadata, created_at, updated_at
            FROM review_runs
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()
        return _review_from_row(row) if row is not None else None

    def list_review_runs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, status, summary, metadata, created_at, updated_at
            FROM review_runs
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_review_from_row(row) for row in rows]

    def create_handoff(
        self,
        *,
        workspace_id: str,
        task_id: str,
        summary: str,
        from_agent: str | None = None,
        to_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        handoff_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO handoffs (
                id, workspace_id, task_id, from_agent, to_agent, summary, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                handoff_id,
                workspace_id,
                task_id,
                from_agent,
                to_agent,
                summary,
                _dump_json(metadata),
                now,
            ),
        )
        self.conn.commit()
        handoff = self.get_handoff(handoff_id)
        assert handoff is not None
        return handoff

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, from_agent, to_agent, summary, metadata, created_at
            FROM handoffs
            WHERE id = ?
            """,
            (handoff_id,),
        ).fetchone()
        return _handoff_from_row(row) if row is not None else None

    def list_handoffs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, from_agent, to_agent, summary, metadata, created_at
            FROM handoffs
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_handoff_from_row(row) for row in rows]

    def upsert_provider(
        self,
        *,
        workspace_id: str,
        provider_id: str,
        name: str,
        provider_type: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO providers (id, workspace_id, name, provider_type, config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, id) DO UPDATE SET
                name = excluded.name,
                provider_type = excluded.provider_type,
                config = excluded.config,
                updated_at = excluded.updated_at
            """,
            (provider_id, workspace_id, name, provider_type, _dump_json(config), now, now),
        )
        self.conn.commit()
        provider = self.get_provider(workspace_id, provider_id)
        assert provider is not None
        return provider

    def get_provider(self, workspace_id: str, provider_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, name, provider_type, config, created_at, updated_at
            FROM providers
            WHERE workspace_id = ? AND id = ?
            """,
            (workspace_id, provider_id),
        ).fetchone()
        return _provider_from_row(row) if row is not None else None

    def list_providers_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, name, provider_type, config, created_at, updated_at
            FROM providers
            WHERE workspace_id = ?
            ORDER BY created_at, id
            """,
            (workspace_id,),
        ).fetchall()
        return [_provider_from_row(row) for row in rows]


def _workspace_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "root_path": row["root_path"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _workspace_repository_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "path": row["path"],
        "remote_url": row["remote_url"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _subtask_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "content": row["content"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
    }


def _approval_gate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "name": row["name"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _load_json(row["payload"])
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "event_type": row["event_type"],
        "object_id": payload.get("object_id"),
        "payload": payload,
        "created_at": row["created_at"],
    }


def _dispatch_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "agent_name": row["agent_name"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _evidence_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "artifact_type": row["artifact_type"],
        "uri": row["uri"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
    }


def _review_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "summary": row["summary"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _handoff_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "from_agent": row["from_agent"],
        "to_agent": row["to_agent"],
        "summary": row["summary"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
    }


def _provider_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "provider_type": row["provider_type"],
        "config": _load_json(row["config"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _new_id() -> str:
    return uuid4().hex


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_MIGRATION_001 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_repositories (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT,
    path TEXT NOT NULL,
    remote_url TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    UNIQUE (id, workspace_id)
);

CREATE TABLE IF NOT EXISTS subtasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, task_id, depends_on_task_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS approval_gates (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    uri TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    from_agent TEXT,
    to_agent TEXT,
    summary TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    workspace_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, key),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workspace_repositories_workspace
    ON workspace_repositories(workspace_id);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace
    ON tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_subtasks_task
    ON subtasks(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_workspace_task
    ON task_dependencies(workspace_id, task_id, depends_on_task_id);
CREATE INDEX IF NOT EXISTS idx_messages_workspace_task
    ON messages(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_approval_gates_task
    ON approval_gates(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_dispatches_task
    ON dispatches(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_events_workspace_task
    ON lifecycle_events(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_evidence_artifacts_task
    ON evidence_artifacts(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_review_runs_task
    ON review_runs(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_handoffs_task
    ON handoffs(workspace_id, task_id);
CREATE INDEX IF NOT EXISTS idx_providers_workspace
    ON providers(workspace_id);
"""


_MIGRATION_002 = """
DROP INDEX IF EXISTS idx_providers_workspace;

CREATE TABLE IF NOT EXISTS providers_v2 (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

INSERT OR REPLACE INTO providers_v2 (
    id, workspace_id, name, provider_type, config, created_at, updated_at
)
SELECT id, workspace_id, name, provider_type, config, created_at, updated_at
FROM providers;

DROP TABLE providers;

ALTER TABLE providers_v2 RENAME TO providers;

CREATE INDEX IF NOT EXISTS idx_providers_workspace
    ON providers(workspace_id);
"""
