"""SQLite storage primitives for Sarathi UI state."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger("sarathi.storage")


LATEST_SCHEMA_VERSION = 10


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite database connection configured for repository use."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # WAL lets reader threads proceed during writes; the busy timeout
        # avoids immediate "database is locked" errors under concurrent load.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.OperationalError:
        # e.g. read-only or network filesystems that cannot support WAL
        pass
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
    if current_schema_version(conn) < 3:
        conn.executescript(_MIGRATION_003)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (3, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 4:
        conn.executescript(_MIGRATION_004)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (4, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 5:
        conn.executescript(_MIGRATION_005)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (5, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 6:
        conn.executescript(_MIGRATION_006)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (6, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 7:
        conn.executescript(_MIGRATION_007)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (7, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 8:
        conn.executescript(_MIGRATION_008)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (8, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 9:
        conn.executescript(_MIGRATION_009)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (9, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 10:
        conn.executescript(_MIGRATION_010)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (10, _utc_now()),
        )
        conn.commit()


class Storage:
    """Small repository facade for persisted Sarathi UI records.

    ``event_listener`` is an optional observer invoked (best-effort) with each
    lifecycle event dict right after it is committed — used by the service to
    fan events out to notification channels without coupling storage to them.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        event_listener: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.conn = conn
        self._event_listener = event_listener

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

    def update_workspace(
        self,
        workspace_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_workspace(workspace_id)
        if existing is None:
            raise KeyError(workspace_id)
        now = _utc_now()
        next_metadata = metadata if metadata is not None else existing["metadata"]
        self.conn.execute(
            """
            UPDATE workspaces
            SET metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (_dump_json(next_metadata), now, workspace_id),
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

    def create_project(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO projects (id, workspace_id, name, description, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, workspace_id, name, description, "active", _dump_json(metadata), now, now),
        )
        self.conn.commit()
        project = self.get_project(project_id)
        assert project is not None
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, name, description, status, metadata, created_at, updated_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        return _project_from_row(row) if row is not None else None

    def update_project(
        self,
        project_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_project(project_id)
        if existing is None:
            raise KeyError(project_id)
        now = _utc_now()
        next_metadata = metadata if metadata is not None else existing["metadata"]
        self.conn.execute(
            """
            UPDATE projects
            SET metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (_dump_json(next_metadata), now, project_id),
        )
        self.conn.commit()
        project = self.get_project(project_id)
        assert project is not None
        return project

    def list_projects(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, name, description, status, metadata, created_at, updated_at
            FROM projects
            WHERE workspace_id = ?
            ORDER BY created_at, id
            """,
            (workspace_id,),
        ).fetchall()
        return [_project_from_row(row) for row in rows]

    def get_project_stats(self, project_id: str) -> dict[str, Any]:
        if self.get_project(project_id) is None:
            return {
                "task_count": 0,
                "blocked_count": 0,
                "review_needed_count": 0,
                "last_activity": None,
            }
        rows = self.conn.execute(
            """
            SELECT
                t.id,
                MAX(t.updated_at) AS last_activity
            FROM tasks t
            WHERE t.project_id = ?
            GROUP BY t.id
            """,
            (project_id,),
        ).fetchall()
        task_ids = [row["id"] for row in rows]
        task_count = len(task_ids)
        last_activity = max((row["last_activity"] for row in rows), default=None)
        blocked_count = 0
        review_needed_count = 0
        if task_ids:
            placeholders = ",".join(["?" for _ in task_ids])
            blocked_count = self.conn.execute(
                f"""
                SELECT COUNT(DISTINCT task_id)
                FROM lifecycle_events
                WHERE task_id IN ({placeholders}) AND event_type = 'task.blocked'
                """,
                task_ids,
            ).fetchone()[0] or 0
            review_needed_count = self.conn.execute(
                f"""
                SELECT COUNT(DISTINCT task_id)
                FROM approval_gates
                WHERE task_id IN ({placeholders}) AND status = 'pending' AND name != 'PRD/AC'
                """,
                task_ids,
            ).fetchone()[0] or 0
        return {
            "task_count": task_count,
            "blocked_count": int(blocked_count),
            "review_needed_count": int(review_needed_count),
            "last_activity": last_activity,
        }

    def create_brainstorm_session(
        self,
        *,
        workspace_id: str,
        title: str,
        project_id: str | None = None,
        provider: str | None = None,
        output_format: str = "markdown",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO brainstorm_sessions (
                id, workspace_id, project_id, title, provider, output_format,
                dialogue_turns, research_findings, visual_options, metadata,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, workspace_id, project_id, title, provider, output_format,
             "[]", "[]", "[]", _dump_json(metadata), now, now),
        )
        self.conn.commit()
        session = self.get_brainstorm_session(session_id)
        assert session is not None
        return session

    def get_brainstorm_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, project_id, task_id, status, title, provider,
                   spec_path, spec_content, output_format, dialogue_turns,
                   research_findings, visual_options, approved_at, created_at, updated_at
                   , metadata
            FROM brainstorm_sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return _brainstorm_session_from_row(row) if row is not None else None

    def list_brainstorm_sessions(
        self, workspace_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                """
                SELECT id, workspace_id, project_id, task_id, status, title, provider,
                       spec_path, spec_content, output_format, dialogue_turns,
                       research_findings, visual_options, approved_at, created_at, updated_at
                       , metadata
                FROM brainstorm_sessions
                WHERE workspace_id = ? AND status = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT id, workspace_id, project_id, task_id, status, title, provider,
                       spec_path, spec_content, output_format, dialogue_turns,
                       research_findings, visual_options, approved_at, created_at, updated_at
                       , metadata
                FROM brainstorm_sessions
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [_brainstorm_session_from_row(row) for row in rows]

    def append_brainstorm_turn(self, session_id: str, turn: dict[str, Any]) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        turns = session["dialogue_turns"]
        turns.append(turn)
        now = _utc_now()
        self.conn.execute(
            "UPDATE brainstorm_sessions SET dialogue_turns = ?, updated_at = ? WHERE id = ?",
            (_dump_json(turns), now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def append_brainstorm_research(self, session_id: str, finding: dict[str, Any]) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        findings = session["research_findings"]
        findings.append(finding)
        now = _utc_now()
        self.conn.execute(
            "UPDATE brainstorm_sessions SET research_findings = ?, updated_at = ? WHERE id = ?",
            (_dump_json(findings), now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def update_brainstorm_spec(
        self, session_id: str, spec_content: str, spec_path: str | None = None
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE brainstorm_sessions
            SET spec_content = ?, spec_path = COALESCE(?, spec_path), updated_at = ?
            WHERE id = ?
            """,
            (spec_content, spec_path, now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def approve_brainstorm_session(
        self, session_id: str, *, task_id: str | None = None
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE brainstorm_sessions
            SET status = 'approved', approved_at = ?, task_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, task_id, now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def create_task(
        self,
        *,
        workspace_id: str,
        title: str,
        status: str = "pending",
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        task_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO tasks (
                id, workspace_id, title, description, status, metadata, created_at, updated_at, project_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                project_id,
            ),
        )
        self.conn.commit()
        task = self.get_task(task_id)
        assert task is not None
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, title, description, status, metadata, created_at, updated_at, project_id
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
            SELECT id, workspace_id, title, description, status, metadata, created_at, updated_at, project_id
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
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at,
                   claimed_by, claimed_at, heartbeat_at
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
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at,
                   claimed_by, claimed_at, heartbeat_at
            FROM subtasks
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_subtask_from_row(row) for row in rows]

    def list_claimable_subtasks(self, *, status: str = "in_progress") -> list[dict[str, Any]]:
        """List subtasks in ``status`` with no active claim, oldest first."""
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at,
                   claimed_by, claimed_at, heartbeat_at
            FROM subtasks
            WHERE status = ? AND claimed_by IS NULL
            ORDER BY created_at, id
            """,
            (status,),
        ).fetchall()
        return [_subtask_from_row(row) for row in rows]

    def list_stale_claimed_subtasks(
        self, *, status: str = "in_progress", before: str
    ) -> list[dict[str, Any]]:
        """List subtasks in ``status`` whose claim heartbeat is older than ``before``."""
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, title, status, metadata, created_at, updated_at,
                   claimed_by, claimed_at, heartbeat_at
            FROM subtasks
            WHERE status = ?
              AND claimed_by IS NOT NULL
              AND heartbeat_at IS NOT NULL
              AND heartbeat_at < ?
            ORDER BY heartbeat_at, id
            """,
            (status, before),
        ).fetchall()
        return [_subtask_from_row(row) for row in rows]

    def claim_subtask(
        self,
        subtask_id: str,
        *,
        worker_id: str,
        status: str = "in_progress",
    ) -> bool:
        """Atomically claim a subtask for ``worker_id``.

        Returns True if this call won the claim (rowcount == 1), False if the
        subtask was already claimed or no longer in ``status`` (lost the race
        or already moved on).
        """
        now = _utc_now()
        cursor = self.conn.execute(
            """
            UPDATE subtasks
            SET claimed_by = ?, claimed_at = ?, heartbeat_at = ?
            WHERE id = ? AND status = ? AND claimed_by IS NULL
            """,
            (worker_id, now, now, subtask_id, status),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def heartbeat_subtask_claim(self, subtask_id: str, *, worker_id: str) -> bool:
        """Refresh the heartbeat for a subtask claimed by ``worker_id``."""
        now = _utc_now()
        cursor = self.conn.execute(
            """
            UPDATE subtasks
            SET heartbeat_at = ?
            WHERE id = ? AND claimed_by = ?
            """,
            (now, subtask_id, worker_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def clear_subtask_claim(self, subtask_id: str) -> dict[str, Any] | None:
        """Clear claim bookkeeping columns for a subtask."""
        self.conn.execute(
            """
            UPDATE subtasks
            SET claimed_by = NULL, claimed_at = NULL, heartbeat_at = NULL
            WHERE id = ?
            """,
            (subtask_id,),
        )
        self.conn.commit()
        return self.get_subtask(subtask_id)

    def create_message(
        self,
        *,
        workspace_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO messages (
                id, workspace_id, task_id, session_id, role, content, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                workspace_id,
                task_id,
                session_id,
                role,
                content,
                _dump_json(metadata),
                now,
            ),
        )
        self.conn.commit()
        message = self.get_message(message_id)
        assert message is not None
        return message

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, session_id, role, content, metadata, created_at
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
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[str] = []
        if workspace_id is not None:
            filters.append("workspace_id = ?")
            params.append(workspace_id)
        if task_id is not None:
            filters.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            filters.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self.conn.execute(
            f"""
            SELECT id, workspace_id, task_id, session_id, role, content, metadata, created_at
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

    def create_session(
        self,
        *,
        workspace_id: str,
        task_id: str,
        owner: str = "local",
        visibility: str = "private",
        share_token: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = _new_id()
        now = _utc_now()
        if share_token is None:
            share_token = secrets.token_urlsafe(18)
        self.conn.execute(
            """
            INSERT INTO sessions (
                id, workspace_id, task_id, owner, share_token, visibility,
                status, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                workspace_id,
                task_id,
                owner,
                share_token,
                visibility,
                "active",
                _dump_json(metadata),
                now,
                now,
            ),
        )
        self.conn.commit()
        self.add_session_participant(session_id=session_id, user=owner, role="owner")
        session = self.get_session(session_id)
        assert session is not None
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, owner, share_token, visibility,
                   status, metadata, created_at, updated_at
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return _session_from_row(row) if row is not None else None

    def get_session_by_share_token(self, share_token: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, owner, share_token, visibility,
                   status, metadata, created_at, updated_at
            FROM sessions
            WHERE share_token = ?
            """,
            (share_token,),
        ).fetchone()
        return _session_from_row(row) if row is not None else None

    def list_sessions_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, owner, share_token, visibility,
                   status, metadata, created_at, updated_at
            FROM sessions
            WHERE task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_session_from_row(row) for row in rows]

    def update_session(
        self,
        session_id: str,
        *,
        visibility: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_session(session_id)
        if existing is None:
            raise KeyError(session_id)
        now = _utc_now()
        next_visibility = visibility if visibility is not None else existing["visibility"]
        next_status = status if status is not None else existing["status"]
        next_metadata = metadata if metadata is not None else existing["metadata"]
        self.conn.execute(
            """
            UPDATE sessions
            SET visibility = ?, status = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_visibility, next_status, _dump_json(next_metadata), now, session_id),
        )
        self.conn.commit()
        session = self.get_session(session_id)
        assert session is not None
        return session

    def create_user(
        self,
        *,
        username: str,
        token: str | None = None,
        display_name: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_id = _new_id()
        now = _utc_now()
        if token is None:
            token = secrets.token_urlsafe(24)
        self.conn.execute(
            """
            INSERT INTO users (
                id, username, token, display_name, status,
                metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                token,
                display_name,
                status,
                _dump_json(metadata),
                now,
                now,
            ),
        )
        self.conn.commit()
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, username, token, display_name, status,
                   metadata, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        return _user_from_row(row) if row is not None else None

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, username, token, display_name, status,
                   metadata, created_at, updated_at
            FROM users
            WHERE token = ?
            """,
            (token,),
        ).fetchone()
        return _user_from_row(row) if row is not None else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, username, token, display_name, status,
                   metadata, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
        return _user_from_row(row) if row is not None else None

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, username, token, display_name, status,
                   metadata, created_at, updated_at
            FROM users
            ORDER BY created_at, id
            """
        ).fetchall()
        return [_user_from_row(row) for row in rows]

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_user(user_id)
        if existing is None:
            raise KeyError(user_id)
        now = _utc_now()
        next_display_name = (
            display_name if display_name is not None else existing["display_name"]
        )
        next_status = status if status is not None else existing["status"]
        next_metadata = metadata if metadata is not None else existing["metadata"]
        self.conn.execute(
            """
            UPDATE users
            SET display_name = ?, status = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_display_name, next_status, _dump_json(next_metadata), now, user_id),
        )
        self.conn.commit()
        user = self.get_user(user_id)
        assert user is not None
        return user

    def add_session_participant(
        self,
        *,
        session_id: str,
        user: str,
        role: str = "observer",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        existing = self.get_session_participant(session_id, user)
        if existing is not None:
            self.conn.execute(
                """
                UPDATE session_participants
                SET role = ?, status = 'active', updated_at = ?
                WHERE session_id = ? AND user = ?
                """,
                (role, now, session_id, user),
            )
        else:
            participant_id = _new_id()
            self.conn.execute(
                """
                INSERT INTO session_participants (
                    id, session_id, user, role, status, metadata, joined_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    participant_id,
                    session_id,
                    user,
                    role,
                    "active",
                    _dump_json(metadata),
                    now,
                    now,
                ),
            )
        self.conn.commit()
        participant = self.get_session_participant(session_id, user)
        assert participant is not None
        return participant

    def get_session_participant(
        self, session_id: str, user: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, session_id, user, role, status, metadata, joined_at, updated_at
            FROM session_participants
            WHERE session_id = ? AND user = ?
            """,
            (session_id, user),
        ).fetchone()
        return _session_participant_from_row(row) if row is not None else None

    def list_session_participants(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, session_id, user, role, status, metadata, joined_at, updated_at
            FROM session_participants
            WHERE session_id = ?
            ORDER BY joined_at, id
            """,
            (session_id,),
        ).fetchall()
        return [_session_participant_from_row(row) for row in rows]

    def update_session_participant(
        self,
        session_id: str,
        user: str,
        *,
        role: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_session_participant(session_id, user)
        if existing is None:
            raise KeyError((session_id, user))
        now = _utc_now()
        next_role = role if role is not None else existing["role"]
        next_status = status if status is not None else existing["status"]
        self.conn.execute(
            """
            UPDATE session_participants
            SET role = ?, status = ?, updated_at = ?
            WHERE session_id = ? AND user = ?
            """,
            (next_role, next_status, now, session_id, user),
        )
        self.conn.commit()
        participant = self.get_session_participant(session_id, user)
        assert participant is not None
        return participant

    def remove_session_participant(
        self, session_id: str, user: str
    ) -> dict[str, Any]:
        existing = self.get_session_participant(session_id, user)
        if existing is None:
            raise KeyError((session_id, user))
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE session_participants
            SET status = 'left', updated_at = ?
            WHERE session_id = ? AND user = ?
            """,
            (now, session_id, user),
        )
        self.conn.commit()
        participant = self.get_session_participant(session_id, user)
        assert participant is not None
        return participant

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
        if self._event_listener is not None:
            try:
                self._event_listener(event)
            except Exception:
                logger.warning("Lifecycle event listener failed", exc_info=True)
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

    def list_dispatches_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, agent_name, status, metadata, created_at, updated_at
            FROM dispatches
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            """,
            (workspace_id,),
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

    def create_checkpoint_capsule(
        self,
        *,
        workspace_id: str,
        task_id: str,
        summary: str,
        key_decisions: list[str],
        evidence_refs: list[str],
        repository_action_preference: dict[str, Any],
        next_start_point: str,
        created_by: str,
        project_id: str | None = None,
        status: str = "ready",
    ) -> dict[str, Any]:
        checkpoint_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO checkpoint_capsules (
                id,
                workspace_id,
                project_id,
                source_task_id,
                status,
                summary,
                key_decisions,
                evidence_refs,
                repository_action_preference,
                next_start_point,
                created_at,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                workspace_id,
                project_id,
                task_id,
                status,
                summary,
                _dump_json(key_decisions),
                _dump_json(evidence_refs),
                _dump_json(repository_action_preference),
                next_start_point,
                now,
                created_by,
            ),
        )
        self.conn.commit()
        checkpoint = self.get_checkpoint_capsule(checkpoint_id)
        assert checkpoint is not None
        return checkpoint

    def get_checkpoint_capsule(self, checkpoint_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                workspace_id,
                project_id,
                source_task_id,
                status,
                summary,
                key_decisions,
                evidence_refs,
                repository_action_preference,
                next_start_point,
                created_at,
                created_by
            FROM checkpoint_capsules
            WHERE id = ?
            """,
            (checkpoint_id,),
        ).fetchone()
        return _checkpoint_capsule_from_row(row) if row is not None else None

    def list_checkpoint_capsules_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                workspace_id,
                project_id,
                source_task_id,
                status,
                summary,
                key_decisions,
                evidence_refs,
                repository_action_preference,
                next_start_point,
                created_at,
                created_by
            FROM checkpoint_capsules
            WHERE source_task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
        return [_checkpoint_capsule_from_row(row) for row in rows]

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

    def list_task_panel_entries(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if task is None:
            return []

        entries: list[dict[str, Any]] = []
        for message in self.list_messages(task_id=task_id):
            role = str(message["role"])
            kind = "human_message" if role == "user" else "agent_update"
            entries.append(
                _task_panel_entry(
                    id=message["id"],
                    kind=kind,
                    source=role,
                    target=_text_or_none(message["metadata"].get("target")),
                    summary=_task_panel_summary(message["content"]),
                    created_at=message["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=message["metadata"],
                )
            )

        for event in self.list_events(task_id=task_id):
            entries.append(
                _task_panel_entry(
                    id=event["id"],
                    kind=_task_panel_kind_for_event(event["event_type"], event["payload"]),
                    source=_task_panel_event_source(event),
                    target=_task_panel_event_target(event),
                    summary=_task_panel_event_summary(event),
                    created_at=event["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=event["payload"],
                )
            )

        for gate in self.list_approval_gates_for_task(task_id):
            entries.append(
                _task_panel_entry(
                    id=gate["id"],
                    kind="review",
                    source=gate["name"],
                    target=gate["status"],
                    summary=f"{gate['name']} gate {gate['status']}",
                    created_at=gate["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=gate["metadata"],
                )
            )

        for dispatch in self.list_dispatches_for_task(task_id):
            entries.append(
                _task_panel_entry(
                    id=dispatch["id"],
                    kind=_task_panel_kind_for_dispatch(dispatch["status"]),
                    source=dispatch["agent_name"],
                    target=_text_or_none(dispatch["metadata"].get("subtask_id")),
                    summary=f"{dispatch['agent_name']} dispatch {dispatch['status']}",
                    created_at=dispatch["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=dispatch["metadata"],
                )
            )

        for evidence in self.list_evidence_artifacts_for_task(task_id):
            entries.append(
                _task_panel_entry(
                    id=evidence["id"],
                    kind="evidence",
                    source=evidence["artifact_type"],
                    target=_text_or_none(evidence["uri"]),
                    summary=f"{evidence['artifact_type']} evidence attached",
                    created_at=evidence["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=evidence["metadata"],
                )
            )

        for review in self.list_review_runs_for_task(task_id):
            entries.append(
                _task_panel_entry(
                    id=review["id"],
                    kind="review",
                    source="review",
                    target=review["status"],
                    summary=review["summary"] or f"Review {review['status']}",
                    created_at=review["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=review["metadata"],
                )
            )

        for handoff in self.list_handoffs_for_task(task_id):
            entries.append(
                _task_panel_entry(
                    id=handoff["id"],
                    kind="handoff",
                    source=handoff["from_agent"] or "handoff",
                    target=handoff["to_agent"],
                    summary=handoff["summary"],
                    created_at=handoff["created_at"],
                    task_id=task_id,
                    workspace_id=task["workspace_id"],
                    metadata=handoff["metadata"],
                )
            )

        entries.sort(key=lambda entry: (entry["created_at"], entry["id"]))
        return entries

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

    def get_workspace_stats(self, workspace_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS task_count,
                SUM(CASE WHEN status NOT IN ('done', 'skipped') THEN 1 ELSE 0 END) AS active_count,
                MAX(updated_at) AS last_activity
            FROM tasks
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:
            return {"task_count": 0, "active_count": 0, "last_activity": None}
        return {
            "task_count": int(row["task_count"] or 0),
            "active_count": int(row["active_count"] or 0),
            "last_activity": row["last_activity"],
        }

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


def _project_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
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
        "project_id": row["project_id"] if "project_id" in row.keys() else None,
    }


def _subtask_from_row(row: sqlite3.Row) -> dict[str, Any]:
    columns = row.keys()
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "claimed_by": row["claimed_by"] if "claimed_by" in columns else None,
        "claimed_at": row["claimed_at"] if "claimed_at" in columns else None,
        "heartbeat_at": row["heartbeat_at"] if "heartbeat_at" in columns else None,
    }


def _message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "session_id": row["session_id"],
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


def _session_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "owner": row["owner"],
        "share_token": row["share_token"],
        "visibility": row["visibility"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _user_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "token": row["token"],
        "display_name": row["display_name"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _session_participant_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "user": row["user"],
        "role": row["role"],
        "status": row["status"],
        "metadata": _load_json(row["metadata"]),
        "joined_at": row["joined_at"],
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


def _checkpoint_capsule_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "source_task_id": row["source_task_id"],
        "status": row["status"],
        "summary": row["summary"],
        "key_decisions": _load_json_list(row["key_decisions"]),
        "evidence_refs": _load_json_list(row["evidence_refs"]),
        "repository_action_preference": _load_json(row["repository_action_preference"]),
        "next_start_point": row["next_start_point"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }


def _brainstorm_session_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "title": row["title"],
        "provider": row["provider"],
        "spec_path": row["spec_path"],
        "spec_content": row["spec_content"],
        "output_format": row["output_format"],
        "dialogue_turns": _load_json_list(row["dialogue_turns"]),
        "research_findings": _load_json_list(row["research_findings"]),
        "visual_options": _load_json_list(row["visual_options"]),
        "metadata": _load_json(row["metadata"]),
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_panel_entry(
    *,
    id: str,
    kind: str,
    source: str,
    target: str | None,
    summary: str,
    created_at: str,
    task_id: str,
    workspace_id: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "source": source,
        "target": target,
        "summary": summary,
        "created_at": created_at,
        "metadata": metadata or {},
        "task_id": task_id,
        "workspace_id": workspace_id,
    }


def _task_panel_summary(text: str, *, limit: int = 120) -> str:
    summary = " ".join(text.strip().split())
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "…"


def _task_panel_kind_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "task.blocked":
        return "blocked"
    if event_type == "task.unblocked":
        return "unblocked"
    if event_type in {"task.completed", "task.complete"}:
        return "completion"
    if event_type in {"approval.requested", "approval.recorded"}:
        return "review"
    if event_type in {"review.completed", "review.rejected"}:
        return "review"
    if event_type == "task.draft_created":
        return "system_note"
    if event_type == "task.chat_created":
        return "system_note"
    if event_type == "subtask.dispatched":
        return "claimed"
    if event_type == "subtask.scheduled":
        return "claimed"
    if event_type == "subtask.unblocked":
        return "unblocked"
    if event_type == "subtask.transitioned":
        status = str(payload.get("status") or "")
        if status == "blocked":
            return "blocked"
        if status in {"waiting_human", "review"}:
            return "review"
        if status == "complete":
            return "completion"
        if status == "in_progress":
            return "claimed"
    return "system_note"


def _task_panel_event_source(event: dict[str, Any]) -> str:
    payload = event["payload"]
    for key in ("actor", "agent", "provider", "source", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return event["event_type"]


def _task_panel_event_target(event: dict[str, Any]) -> str | None:
    payload = event["payload"]
    for key in ("object_id", "subtask_id", "dispatch_id", "status", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _task_panel_event_summary(event: dict[str, Any]) -> str:
    payload = event["payload"]
    event_type = event["event_type"]
    if event_type == "task.blocked":
        reason = payload.get("reason") or payload.get("message") or "blocked"
        return f"Task blocked: {reason}"
    if event_type == "task.unblocked":
        return "Task unblocked"
    if event_type == "task.completed":
        return "Task completed"
    if event_type == "approval.requested":
        return f"Approval requested for {payload.get('name') or 'gate'}"
    if event_type == "approval.recorded":
        return f"Approval recorded: {payload.get('status') or 'updated'}"
    if event_type == "subtask.scheduled":
        role = payload.get("role") or payload.get("provider") or "subtask"
        return f"{role} scheduled"
    if event_type == "subtask.dispatched":
        return f"Dispatch recorded for {payload.get('object_id') or 'subtask'}"
    if event_type == "subtask.unblocked":
        return f"Unblocked {payload.get('object_id') or 'subtask'}"
    if event_type == "subtask.transitioned":
        status = payload.get("status") or "updated"
        actor = payload.get("actor") or "Subtask"
        return f"{actor} → {status}"
    if event_type == "task.draft_created":
        return "Task draft created"
    if event_type == "task.chat_created":
        return "Task inception chat created a draft"
    if event_type == "review.completed":
        return "Review completed"
    if event_type == "review.rejected":
        return "Review rejected"
    return event_type.replace(".", " ")


def _task_panel_kind_for_dispatch(status: str) -> str:
    if status in {"queued", "claimed", "pending"}:
        return "claimed"
    if status in {"in_progress", "running"}:
        return "in_progress"
    if status == "review":
        return "review"
    if status == "complete":
        return "completion"
    if status == "failed":
        return "blocked"
    return "system_note"


def _text_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


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


def _dump_json(value: Any | None) -> str:
    return json.dumps({} if value is None else value, sort_keys=True)


def _load_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return loaded


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


_MIGRATION_003 = """
CREATE TABLE IF NOT EXISTS checkpoint_capsules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    source_task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_decisions TEXT NOT NULL DEFAULT '[]',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    repository_action_preference TEXT NOT NULL DEFAULT '{}',
    next_start_point TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (source_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (source_task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_capsules_task
    ON checkpoint_capsules(workspace_id, source_task_id);
"""


_MIGRATION_004 = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_workspace
    ON projects(workspace_id);
"""

_MIGRATION_005 = """
CREATE TABLE IF NOT EXISTS brainstorm_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    task_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL,
    provider TEXT,
    spec_path TEXT,
    spec_content TEXT,
    output_format TEXT NOT NULL DEFAULT 'markdown',
    dialogue_turns TEXT NOT NULL DEFAULT '[]',
    research_findings TEXT NOT NULL DEFAULT '[]',
    visual_options TEXT NOT NULL DEFAULT '[]',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_brainstorm_sessions_workspace
    ON brainstorm_sessions(workspace_id);

CREATE INDEX IF NOT EXISTS idx_brainstorm_sessions_status
    ON brainstorm_sessions(workspace_id, status);
"""


_MIGRATION_006 = """
ALTER TABLE brainstorm_sessions ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';
"""


_MIGRATION_007 = """
ALTER TABLE subtasks ADD COLUMN claimed_by TEXT;
ALTER TABLE subtasks ADD COLUMN claimed_at TEXT;
ALTER TABLE subtasks ADD COLUMN heartbeat_at TEXT;

CREATE INDEX IF NOT EXISTS idx_subtasks_claim
    ON subtasks(status, claimed_by);
"""


_MIGRATION_008 = """
ALTER TABLE tasks ADD COLUMN project_id TEXT;

INSERT INTO projects (id, workspace_id, name, description, status, metadata, created_at, updated_at)
SELECT
    w.id || '-default' AS id,
    w.id AS workspace_id,
    'Default' AS name,
    'Default project created during migration' AS description,
    'active' AS status,
    '{}' AS metadata,
    datetime('now') AS created_at,
    datetime('now') AS updated_at
FROM workspaces w
WHERE w.id NOT IN (SELECT DISTINCT workspace_id FROM projects);

UPDATE tasks
SET project_id = workspace_id || '-default'
WHERE project_id IS NULL;
"""


_MIGRATION_009 = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'local',
    share_token TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',   -- 'private' | 'link'
    status TEXT NOT NULL DEFAULT 'active',         -- 'active' | 'closed'
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_share_token ON sessions(share_token);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON sessions(task_id);

CREATE TABLE IF NOT EXISTS session_participants (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'observer',        -- 'owner' | 'driver' | 'observer'
    status TEXT NOT NULL DEFAULT 'active',         -- 'active' | 'left'
    metadata TEXT NOT NULL DEFAULT '{}',
    joined_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_participants_unique ON session_participants(session_id, user);

ALTER TABLE messages ADD COLUMN session_id TEXT;
"""


_MIGRATION_010 = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'disabled'
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_token ON users(token);
"""
