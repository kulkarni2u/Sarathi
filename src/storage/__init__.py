"""SQLite storage primitives for Sarathi UI state."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

logger = logging.getLogger("sarathi.storage")


LATEST_SCHEMA_VERSION = 13


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
    if current_schema_version(conn) < 11:
        conn.executescript(_MIGRATION_011)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (11, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 12:
        conn.executescript(_MIGRATION_012)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (12, _utc_now()),
        )
        conn.commit()
    if current_schema_version(conn) < 13:
        # Migration 12 shipped two slack_outbox shapes: the original 6f9605f
        # shape (no attempt_count) and the round-1 shape whose migration was
        # edited in place (attempt_count present). Add the column only when
        # missing so fresh databases and already-v12 databases converge on the
        # same v13 schema without touching prior migrations. SQLite has no
        # "ADD COLUMN IF NOT EXISTS", so guard on PRAGMA table_info.
        outbox_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(slack_outbox)")
        }
        if "attempt_count" not in outbox_columns:
            conn.execute(
                "ALTER TABLE slack_outbox ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (13, _utc_now()),
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

    def list_tasks(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, title, description, status, metadata, created_at, updated_at, project_id
            FROM tasks
            ORDER BY created_at, id
            """
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

    def update_approval_gate(
        self, gate_id: str, *, status: str | None = None, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        existing = self.get_approval_gate(gate_id)
        if existing is None:
            raise KeyError(gate_id)
        next_status = status if status is not None else existing["status"]
        next_metadata = metadata if metadata is not None else existing["metadata"]
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE approval_gates
            SET status = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_status, _dump_json(next_metadata), now, gate_id),
        )
        self.conn.commit()
        gate = self.get_approval_gate(gate_id)
        assert gate is not None
        return gate

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

    def upsert_proposal_decision(
        self,
        *,
        workspace_id: str,
        proposal_id: str,
        status: str,
        policy_file: str | None = None,
        title: str | None = None,
        source: str | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a policy-proposal review decision.

        Keyed by ``(workspace_id, proposal_id)`` so re-recording the same
        decision (e.g. re-importing from the file store, or re-accepting an
        already-accepted proposal) never duplicates a row -- it just updates
        the existing one. ``payload`` stores the full decision dict produced
        by ``evolve.ProposalReviewStore`` so no information is lost even for
        fields not promoted to their own column.
        """
        now = _utc_now()
        reviewed_at = reviewed_at or now
        self.conn.execute(
            """
            INSERT INTO proposal_decisions (
                id, workspace_id, proposal_id, status, policy_file, title,
                source, reason, payload, reviewed_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, proposal_id) DO UPDATE SET
                status = excluded.status,
                policy_file = excluded.policy_file,
                title = excluded.title,
                source = excluded.source,
                reason = excluded.reason,
                payload = excluded.payload,
                reviewed_at = excluded.reviewed_at,
                updated_at = excluded.updated_at
            """,
            (
                _new_id(),
                workspace_id,
                proposal_id,
                status,
                policy_file,
                title,
                source,
                reason,
                _dump_json(payload),
                reviewed_at,
                now,
                now,
            ),
        )
        self.conn.commit()
        decision = self.get_proposal_decision(workspace_id, proposal_id)
        assert decision is not None
        return decision

    def get_proposal_decision(self, workspace_id: str, proposal_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, proposal_id, status, policy_file, title,
                   source, reason, payload, reviewed_at, created_at, updated_at
            FROM proposal_decisions
            WHERE workspace_id = ? AND proposal_id = ?
            """,
            (workspace_id, proposal_id),
        ).fetchone()
        return _proposal_decision_from_row(row) if row is not None else None

    def list_proposal_decisions(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, proposal_id, status, policy_file, title,
                   source, reason, payload, reviewed_at, created_at, updated_at
            FROM proposal_decisions
            WHERE workspace_id = ?
            ORDER BY reviewed_at, id
            """,
            (workspace_id,),
        ).fetchall()
        return [_proposal_decision_from_row(row) for row in rows]

    def enqueue_slack_event(
        self,
        *,
        envelope_id: str,
        event_id: str | None,
        workspace_id: str,
        team_id: str,
        channel_id: str,
        actor_id: str,
        event_type: str,
        content: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Insert a validated Slack event, deduplicated by ``envelope_id``.

        A duplicate insert is a no-op and returns the previously recorded row so
        Socket Mode envelopes are applied at most once.
        """
        _check_no_forbidden_keys(content, kind="slack inbox content")
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO slack_inbox (
                    id, envelope_id, event_id, workspace_id, team_id, channel_id,
                    actor_id, event_type, content, status, error_code, claimed_at,
                    processed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, ?, ?)
                """,
                (
                    _new_id(),
                    envelope_id,
                    event_id,
                    workspace_id,
                    team_id,
                    channel_id,
                    actor_id,
                    event_type,
                    _dump_json(content),
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                """
                SELECT id, envelope_id, event_id, workspace_id, team_id, channel_id,
                       actor_id, event_type, content, status, error_code, claimed_at,
                       processed_at, created_at, updated_at
                FROM slack_inbox
                WHERE envelope_id = ?
                """,
                (envelope_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack inbox row for envelope_id {envelope_id!r}")
        return _slack_inbox_from_row(row)

    def claim_slack_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """Atomically transition up to ``limit`` pending inbox rows to ``processing``."""
        if limit < 0:
            raise ValueError(f"claim_slack_events limit must be >= 0, got {limit}")
        now = _utc_now()
        with self.conn:
            claimed: list[str] = []
            candidates = self.conn.execute(
                """
                SELECT id FROM slack_inbox
                WHERE status = 'pending'
                ORDER BY created_at, id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for candidate in candidates:
                cursor = self.conn.execute(
                    """
                    UPDATE slack_inbox
                    SET status = 'processing', claimed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now, now, candidate["id"]),
                )
                if cursor.rowcount == 1:
                    claimed.append(candidate["id"])
            if not claimed:
                return []
            placeholders = ",".join("?" for _ in claimed)
            rows = self.conn.execute(
                f"""
                SELECT id, envelope_id, event_id, workspace_id, team_id, channel_id,
                       actor_id, event_type, content, status, error_code, claimed_at,
                       processed_at, created_at, updated_at
                FROM slack_inbox
                WHERE id IN ({placeholders})
                ORDER BY created_at, id
                """,
                claimed,
            ).fetchall()
        return [_slack_inbox_from_row(row) for row in rows]

    def finish_slack_event(
        self,
        envelope_id: str,
        *,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """Record a terminal inbox state: ``processed``, ``rejected``, or ``failed``.

        Transitions only from ``pending`` or ``processing``; an already-terminal
        row is returned unchanged so repeated or conflicting finishes never
        overwrite the first terminal result (at-most-once).
        """
        if status not in ("processed", "rejected", "failed"):
            raise ValueError(f"Invalid slack inbox terminal status: {status}")
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE slack_inbox
                SET status = ?, error_code = ?, processed_at = ?, updated_at = ?
                WHERE envelope_id = ? AND status IN ('pending', 'processing')
                """,
                (status, error_code, now, now, envelope_id),
            )
            row = self.conn.execute(
                """
                SELECT id, envelope_id, event_id, workspace_id, team_id, channel_id,
                       actor_id, event_type, content, status, error_code, claimed_at,
                       processed_at, created_at, updated_at
                FROM slack_inbox
                WHERE envelope_id = ?
                """,
                (envelope_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack inbox row for envelope_id {envelope_id!r}")
        return _slack_inbox_from_row(row)

    def bind_slack_task(
        self,
        *,
        task_id: str,
        workspace_id: str,
        team_id: str,
        channel_id: str,
        thread_ts: str,
        requester_user_id: str,
    ) -> dict[str, Any]:
        """Record the exact Slack thread a Sarathi task is bound to.

        Re-binding an already-bound task is a no-op that returns the canonical
        row, keeping the mapping idempotent across retries. Rebinding a thread
        that is already owned by a *different* task raises ``ValueError``; the
        exact thread mapping is never silently reassigned.
        """
        now = _utc_now()
        with self.conn:
            existing = self.conn.execute(
                """
                SELECT task_id FROM slack_task_bindings
                WHERE team_id = ? AND channel_id = ? AND thread_ts = ?
                """,
                (team_id, channel_id, thread_ts),
            ).fetchone()
            if existing is not None and existing["task_id"] != task_id:
                raise ValueError(
                    f"Slack thread {team_id}/{channel_id}/{thread_ts} is already "
                    f"bound to task {existing['task_id']!r}; cannot rebind to task "
                    f"{task_id!r}"
                )
            self.conn.execute(
                """
                INSERT OR IGNORE INTO slack_task_bindings (
                    id, task_id, workspace_id, team_id, channel_id, thread_ts,
                    requester_user_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(),
                    task_id,
                    workspace_id,
                    team_id,
                    channel_id,
                    thread_ts,
                    requester_user_id,
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                """
                SELECT id, task_id, workspace_id, team_id, channel_id, thread_ts,
                       requester_user_id, created_at, updated_at
                FROM slack_task_bindings
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack task binding for task_id {task_id!r}")
        return _slack_task_binding_from_row(row)

    def get_slack_task_binding(
        self,
        *,
        team_id: str,
        channel_id: str,
        thread_ts: str,
    ) -> dict[str, Any] | None:
        """Resolve the exact task binding for a Slack thread, if any."""
        row = self.conn.execute(
            """
            SELECT id, task_id, workspace_id, team_id, channel_id, thread_ts,
                   requester_user_id, created_at, updated_at
            FROM slack_task_bindings
            WHERE team_id = ? AND channel_id = ? AND thread_ts = ?
            """,
            (team_id, channel_id, thread_ts),
        ).fetchone()
        return _slack_task_binding_from_row(row) if row is not None else None

    def enqueue_slack_outbox(
        self,
        *,
        operation_key: str,
        workspace_id: str,
        task_id: str,
        channel_id: str,
        thread_ts: str | None,
        operation: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record outbound Slack intent, deduplicated by ``operation_key``."""
        _check_no_forbidden_keys(payload, kind="slack outbox payload")
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO slack_outbox (
                    id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                    operation, payload, status, error_code, attempt_count,
                    slack_message_ts, claimed_at, processed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 0, NULL, NULL, NULL, ?, ?)
                """,
                (
                    _new_id(),
                    operation_key,
                    workspace_id,
                    task_id,
                    channel_id,
                    thread_ts,
                    operation,
                    _dump_json(payload),
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                """
                SELECT id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                       operation, payload, status, error_code, attempt_count,
                       slack_message_ts, claimed_at, processed_at, created_at, updated_at
                FROM slack_outbox
                WHERE operation_key = ?
                """,
                (operation_key,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack outbox row for operation_key {operation_key!r}")
        return _slack_outbox_from_row(row)

    def claim_slack_outbox(self, limit: int = 20) -> list[dict[str, Any]]:
        """Atomically transition up to ``limit`` pending outbox rows to ``processing``."""
        if limit < 0:
            raise ValueError(f"claim_slack_outbox limit must be >= 0, got {limit}")
        now = _utc_now()
        with self.conn:
            claimed: list[str] = []
            candidates = self.conn.execute(
                """
                SELECT id FROM slack_outbox
                WHERE status = 'pending'
                ORDER BY created_at, id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for candidate in candidates:
                cursor = self.conn.execute(
                    """
                    UPDATE slack_outbox
                    SET status = 'processing', claimed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now, now, candidate["id"]),
                )
                if cursor.rowcount == 1:
                    claimed.append(candidate["id"])
            if not claimed:
                return []
            placeholders = ",".join("?" for _ in claimed)
            rows = self.conn.execute(
                f"""
                SELECT id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                       operation, payload, status, error_code, attempt_count,
                       slack_message_ts, claimed_at, processed_at, created_at, updated_at
                FROM slack_outbox
                WHERE id IN ({placeholders})
                ORDER BY created_at, id
                """,
                claimed,
            ).fetchall()
        return [_slack_outbox_from_row(row) for row in rows]

    def finish_slack_outbox(self, operation_key: str, *, slack_message_ts: str) -> dict[str, Any]:
        """Record successful delivery of an outbox row as ``sent``.

        Transitions only from ``pending`` or ``processing``; an already-terminal
        row is returned unchanged so a repeated or conflicting finish never
        overwrites the first terminal result (at-most-once).
        """
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE slack_outbox
                SET status = 'sent', slack_message_ts = ?, error_code = NULL,
                    processed_at = ?, updated_at = ?
                WHERE operation_key = ? AND status IN ('pending', 'processing')
                """,
                (slack_message_ts, now, now, operation_key),
            )
            row = self.conn.execute(
                """
                SELECT id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                       operation, payload, status, error_code, attempt_count,
                       slack_message_ts, claimed_at, processed_at, created_at, updated_at
                FROM slack_outbox
                WHERE operation_key = ?
                """,
                (operation_key,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack outbox row for operation_key {operation_key!r}")
        return _slack_outbox_from_row(row)

    def fail_slack_outbox(
        self,
        operation_key: str,
        *,
        error_code: str,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Record a failed outbox delivery with bounded retry metadata.

        Increments ``attempt_count``. Below ``max_attempts`` the row is requeued
        to ``pending`` so the worker can claim and retry it; at or above the
        bound it becomes terminal ``failed``. Only applies from ``pending`` or
        ``processing`` — an already-terminal row is returned unchanged.
        """
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE slack_outbox
                SET attempt_count = attempt_count + 1,
                    status = CASE WHEN attempt_count + 1 >= ? THEN 'failed' ELSE 'pending' END,
                    error_code = ?,
                    processed_at = CASE WHEN attempt_count + 1 >= ? THEN ? ELSE NULL END,
                    claimed_at = CASE WHEN attempt_count + 1 >= ? THEN claimed_at ELSE NULL END,
                    updated_at = ?
                WHERE operation_key = ? AND status IN ('pending', 'processing')
                """,
                (max_attempts, error_code, max_attempts, now, max_attempts, now, operation_key),
            )
            row = self.conn.execute(
                """
                SELECT id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                       operation, payload, status, error_code, attempt_count,
                       slack_message_ts, claimed_at, processed_at, created_at, updated_at
                FROM slack_outbox
                WHERE operation_key = ?
                """,
                (operation_key,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack outbox row for operation_key {operation_key!r}")
        return _slack_outbox_from_row(row)

    def create_slack_command_task(
        self,
        *,
        envelope_id: str,
        workspace_id: str,
        team_id: str,
        channel_id: str,
        actor_id: str,
        thread_ts: str,
        title: str,
        prompt: str,
        validation_version: str,
        digest: str,
        approve_action: str,
        reject_action: str,
    ) -> dict[str, Any]:
        """Materialize a validated Slack slash command into one draft unit.

        A single transaction creates the draft task (``prd_pending``), the
        provisional Slack thread binding, the human approval gate with opaque
        decision actions, the two opening messages, the outbound message
        intent, and the ``task.draft_created`` / ``approval.requested``
        lifecycle events, then finishes the inbox event. At-most-once by
        ``envelope_id``: a repeated call returns the canonical ``task_id`` /
        ``gate_id`` with ``duplicate=True`` and creates nothing new.
        """
        action_values = {"approve": approve_action, "reject": reject_action}
        task_metadata = {
            "source": "slack",
            "slack": {
                "team_id": team_id,
                "channel_id": channel_id,
                "requester_user_id": actor_id,
                "thread_ts": thread_ts,
                "thread_ts_provisional": True,
                "source_prompt": prompt,
                "validation": {
                    "validation_version": validation_version,
                    "digest": digest,
                },
            },
        }
        _check_no_forbidden_keys(task_metadata, kind="slack command task metadata")
        now = _utc_now()
        operation_key = f"task-created:{envelope_id}"
        with self.conn:
            existing = self.conn.execute(
                """
                SELECT status FROM slack_inbox
                WHERE envelope_id = ?
                """,
                (envelope_id,),
            ).fetchone()
            if existing is not None and existing["status"] == "processed":
                binding = self.conn.execute(
                    """
                    SELECT task_id FROM slack_task_bindings
                    WHERE team_id = ? AND channel_id = ? AND thread_ts = ?
                    """,
                    (team_id, channel_id, thread_ts),
                ).fetchone()
                outbox = self.conn.execute(
                    """
                    SELECT payload FROM slack_outbox
                    WHERE operation_key = ?
                    """,
                    (operation_key,),
                ).fetchone()
                if binding is not None and outbox is not None:
                    gate_id = _load_json(outbox["payload"]).get("gate_id")
                    if gate_id:
                        return {
                            "task_id": binding["task_id"],
                            "gate_id": gate_id,
                            "duplicate": True,
                        }

            task_id = _new_id()
            gate_id = _new_id()
            self.conn.execute(
                """
                INSERT INTO tasks (
                    id, workspace_id, title, description, status, metadata,
                    created_at, updated_at, project_id
                )
                VALUES (?, ?, ?, NULL, 'prd_pending', ?, ?, ?, NULL)
                """,
                (task_id, workspace_id, title, _dump_json(task_metadata), now, now),
            )
            self.conn.execute(
                """
                INSERT INTO approval_gates (
                    id, workspace_id, task_id, name, status, metadata, created_at, updated_at
                )
                VALUES (?, ?, ?, 'Requires human approval', 'pending', ?, ?, ?)
                """,
                (
                    gate_id,
                    workspace_id,
                    task_id,
                    _dump_json(
                        {"requires_human": True, "slack_decision_actions": action_values}
                    ),
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO slack_task_bindings (
                    id, task_id, workspace_id, team_id, channel_id, thread_ts,
                    requester_user_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(),
                    task_id,
                    workspace_id,
                    team_id,
                    channel_id,
                    thread_ts,
                    actor_id,
                    now,
                    now,
                ),
            )
            for role, content, message_metadata in (
                (
                    "system",
                    "Draft task created from a Slack command",
                    {"source": "slack", "slack": {"team_id": team_id, "channel_id": channel_id}},
                ),
                ("user", prompt, {"source": "slack"}),
            ):
                self.conn.execute(
                    """
                    INSERT INTO messages (
                        id, workspace_id, task_id, session_id, role, content, metadata, created_at
                    )
                    VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        workspace_id,
                        task_id,
                        role,
                        content,
                        _dump_json(message_metadata),
                        now,
                    ),
                )
            outbox_payload = {
                "text": "Draft task created — waiting on human approval.",
                "task_id": task_id,
                "gate_id": gate_id,
                "actions": action_values,
            }
            _check_no_forbidden_keys(outbox_payload, kind="slack command outbox payload")
            self.conn.execute(
                """
                INSERT INTO slack_outbox (
                    id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                    operation, payload, status, error_code, attempt_count,
                    slack_message_ts, claimed_at, processed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'message', ?, 'pending', NULL, 0, NULL, NULL, NULL, ?, ?)
                """,
                (
                    _new_id(),
                    operation_key,
                    workspace_id,
                    task_id,
                    channel_id,
                    thread_ts,
                    _dump_json(outbox_payload),
                    now,
                    now,
                ),
            )
            for event_type, payload in (
                (
                    "task.draft_created",
                    {"object_id": task_id, "source": "slack", "envelope_id": envelope_id},
                ),
                (
                    "approval.requested",
                    {"object_id": gate_id, "task_id": task_id, "envelope_id": envelope_id},
                ),
            ):
                self.conn.execute(
                    """
                    INSERT INTO lifecycle_events (
                        id, workspace_id, task_id, event_type, payload, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        workspace_id,
                        task_id,
                        event_type,
                        _dump_json(payload),
                        now,
                    ),
                )
            self.conn.execute(
                """
                UPDATE slack_inbox
                SET status = 'processed', error_code = NULL, processed_at = ?, updated_at = ?
                WHERE envelope_id = ? AND status IN ('pending', 'processing')
                """,
                (now, now, envelope_id),
            )
        return {"task_id": task_id, "gate_id": gate_id, "duplicate": False}

    def find_slack_gate_by_action_value(self, value: str) -> dict[str, Any] | None:
        """Return the approval gate bound to an opaque Slack decision action.

        Decision actions are stored under ``metadata["slack_decision_actions"]``;
        the value is never persisted anywhere else, so a matching value is
        proof the caller saw the gate's own message.
        """
        if not value:
            return None
        rows = self.conn.execute(
            """
            SELECT id, workspace_id, task_id, name, status, metadata, created_at, updated_at
            FROM approval_gates
            """
        ).fetchall()
        for row in rows:
            gate = _approval_gate_from_row(row)
            actions = gate["metadata"].get("slack_decision_actions")
            if not isinstance(actions, dict):
                continue
            if actions.get("approve") == value or actions.get("reject") == value:
                return gate
        return None

    def apply_slack_gate_decision(
        self,
        *,
        envelope_id: str,
        gate_id: str,
        task_id: str,
        requested_status: str,
        actor_id: str,
        operation_key: str,
        workspace_id: str,
        channel_id: str,
        thread_ts: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Apply a human gate decision atomically and at most once.

        A single transaction CAS-transitions the gate from ``pending`` to the
        requested terminal status; only on a successful transition does it
        enqueue the decision outbox message and the
        ``approval.decision_recorded`` lifecycle event. The inbox event is
        always finished. A repeated or stale decision leaves the gate at its
        first terminal status and returns ``applied=False``.
        """
        if requested_status not in ("approved", "rejected"):
            raise ValueError(f"Invalid gate decision status: {requested_status}")
        _check_no_forbidden_keys(payload, kind="slack decision outbox payload")
        now = _utc_now()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE approval_gates
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (requested_status, now, gate_id),
            )
            applied = cursor.rowcount == 1
            row = self.conn.execute(
                """
                SELECT id, workspace_id, task_id, name, status, metadata, created_at, updated_at
                FROM approval_gates
                WHERE id = ?
                """,
                (gate_id,),
            ).fetchone()
            gate_status = _approval_gate_from_row(row)["status"] if row is not None else None
            if applied:
                self.conn.execute(
                    """
                    INSERT INTO slack_outbox (
                        id, operation_key, workspace_id, task_id, channel_id, thread_ts,
                        operation, payload, status, error_code, attempt_count,
                        slack_message_ts, claimed_at, processed_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'message', ?, 'pending', NULL, 0, NULL, NULL, NULL, ?, ?)
                    """,
                    (
                        _new_id(),
                        operation_key,
                        workspace_id,
                        task_id,
                        channel_id,
                        thread_ts,
                        _dump_json(payload),
                        now,
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO lifecycle_events (
                        id, workspace_id, task_id, event_type, payload, created_at
                    )
                    VALUES (?, ?, ?, 'approval.decision_recorded', ?, ?)
                    """,
                    (
                        _new_id(),
                        workspace_id,
                        task_id,
                        _dump_json(
                            {
                                "object_id": gate_id,
                                "task_id": task_id,
                                "status": requested_status,
                                "actor_id": actor_id,
                                "envelope_id": envelope_id,
                            }
                        ),
                        now,
                    ),
                )
            self.conn.execute(
                """
                UPDATE slack_inbox
                SET status = 'processed', error_code = NULL, processed_at = ?, updated_at = ?
                WHERE envelope_id = ? AND status IN ('pending', 'processing')
                """,
                (now, now, envelope_id),
            )
        return {"gate_status": gate_status, "applied": applied}

    def create_slack_external_input(
        self,
        *,
        envelope_id: str,
        workspace_id: str,
        task_id: str,
        actor_id: str,
        channel_id: str,
        text: str,
        validation_version: str,
        digest: str,
        subtask_id: str | None = None,
    ) -> dict[str, Any]:
        """Store a validated human reply, deduplicated by ``envelope_id``."""
        status = "assigned" if subtask_id is not None else "unassigned"
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO slack_external_inputs (
                    id, envelope_id, workspace_id, task_id, actor_id, channel_id,
                    text, validation_version, digest, subtask_id, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(),
                    envelope_id,
                    workspace_id,
                    task_id,
                    actor_id,
                    channel_id,
                    text,
                    validation_version,
                    digest,
                    subtask_id,
                    status,
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                """
                SELECT id, envelope_id, workspace_id, task_id, actor_id, channel_id,
                       text, validation_version, digest, subtask_id, status,
                       created_at, updated_at
                FROM slack_external_inputs
                WHERE envelope_id = ?
                """,
                (envelope_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No slack external input row for envelope_id {envelope_id!r}")
        return _slack_external_input_from_row(row)

    def assign_slack_external_input(self, input_id: str, subtask_id: str) -> dict[str, Any] | None:
        """Compare-and-set bind an unassigned external input to ``subtask_id``.

        Only the first assignment wins; a later or repeated assignment returns
        None so a stale selection is a no-op.
        """
        now = _utc_now()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE slack_external_inputs
                SET subtask_id = ?, status = 'assigned', updated_at = ?
                WHERE id = ? AND subtask_id IS NULL AND status = 'unassigned'
                """,
                (subtask_id, now, input_id),
            )
            row = self.conn.execute(
                """
                SELECT id, envelope_id, workspace_id, task_id, actor_id, channel_id,
                       text, validation_version, digest, subtask_id, status,
                       created_at, updated_at
                FROM slack_external_inputs
                WHERE id = ?
                """,
                (input_id,),
            ).fetchone()
        if row is None or cursor.rowcount == 0:
            return None
        return _slack_external_input_from_row(row)


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


def _proposal_decision_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "proposal_id": row["proposal_id"],
        "status": row["status"],
        "policy_file": row["policy_file"],
        "title": row["title"],
        "source": row["source"],
        "reason": row["reason"],
        "payload": _load_json(row["payload"]),
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _slack_inbox_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "envelope_id": row["envelope_id"],
        "event_id": row["event_id"],
        "workspace_id": row["workspace_id"],
        "team_id": row["team_id"],
        "channel_id": row["channel_id"],
        "actor_id": row["actor_id"],
        "event_type": row["event_type"],
        "content": _load_json(row["content"]),
        "status": row["status"],
        "error_code": row["error_code"],
        "claimed_at": row["claimed_at"],
        "processed_at": row["processed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _slack_outbox_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "operation_key": row["operation_key"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "channel_id": row["channel_id"],
        "thread_ts": row["thread_ts"],
        "operation": row["operation"],
        "payload": _load_json(row["payload"]),
        "status": row["status"],
        "error_code": row["error_code"],
        "attempt_count": row["attempt_count"],
        "slack_message_ts": row["slack_message_ts"],
        "claimed_at": row["claimed_at"],
        "processed_at": row["processed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _slack_task_binding_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "workspace_id": row["workspace_id"],
        "team_id": row["team_id"],
        "channel_id": row["channel_id"],
        "thread_ts": row["thread_ts"],
        "requester_user_id": row["requester_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _slack_external_input_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "envelope_id": row["envelope_id"],
        "workspace_id": row["workspace_id"],
        "task_id": row["task_id"],
        "actor_id": row["actor_id"],
        "channel_id": row["channel_id"],
        "text": row["text"],
        "validation_version": row["validation_version"],
        "digest": row["digest"],
        "subtask_id": row["subtask_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump_json(value: Any | None) -> str:
    return json.dumps({} if value is None else value, sort_keys=True)


_FORBIDDEN_CONTENT_KEYS = frozenset(
    {"response_url", "raw_envelope", "app_token", "bot_token", "token"}
)


def _check_no_forbidden_keys(value: Any, *, kind: str) -> None:
    """Reject Slack secrets that must never be persisted inside stored JSON.

    ``response_url``, the raw Socket Mode envelope, and app/bot tokens are
    runtime-only credentials; persisting any of them (at any nesting depth)
    would defeat the redaction boundary.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_CONTENT_KEYS:
                raise ValueError(f"{kind} must not contain forbidden key {key!r}")
            _check_no_forbidden_keys(child, kind=kind)
    elif isinstance(value, list):
        for item in value:
            _check_no_forbidden_keys(item, kind=kind)


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


_MIGRATION_011 = """
CREATE TABLE IF NOT EXISTS proposal_decisions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    status TEXT NOT NULL,                    -- 'accepted' | 'rejected'
    policy_file TEXT,
    title TEXT,
    source TEXT,
    reason TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    reviewed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_proposal_decisions_workspace_proposal
    ON proposal_decisions(workspace_id, proposal_id);
"""


_MIGRATION_012 = """
CREATE TABLE IF NOT EXISTS slack_inbox (
    id TEXT PRIMARY KEY,
    envelope_id TEXT NOT NULL,
    event_id TEXT,
    workspace_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    error_code TEXT,
    claimed_at TEXT,
    processed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (envelope_id)
);

CREATE INDEX IF NOT EXISTS idx_slack_inbox_pending
    ON slack_inbox(status);

CREATE TABLE IF NOT EXISTS slack_outbox (
    id TEXT PRIMARY KEY,
    operation_key TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    thread_ts TEXT,
    operation TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    error_code TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    slack_message_ts TEXT,
    claimed_at TEXT,
    processed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (operation_key)
);

CREATE INDEX IF NOT EXISTS idx_slack_outbox_pending
    ON slack_outbox(status);

CREATE INDEX IF NOT EXISTS idx_slack_outbox_task
    ON slack_outbox(task_id);

CREATE TABLE IF NOT EXISTS slack_task_bindings (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    requester_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (task_id),
    UNIQUE (team_id, channel_id, thread_ts)
);

CREATE INDEX IF NOT EXISTS idx_slack_task_bindings_task
    ON slack_task_bindings(task_id);

CREATE TABLE IF NOT EXISTS slack_external_inputs (
    id TEXT PRIMARY KEY,
    envelope_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    text TEXT NOT NULL,
    validation_version TEXT NOT NULL,
    digest TEXT NOT NULL,
    subtask_id TEXT,
    status TEXT NOT NULL DEFAULT 'unassigned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (envelope_id)
);

CREATE INDEX IF NOT EXISTS idx_slack_external_inputs_unassigned
    ON slack_external_inputs(status);

CREATE INDEX IF NOT EXISTS idx_slack_external_inputs_task
    ON slack_external_inputs(task_id);
"""
