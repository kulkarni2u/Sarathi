import sqlite3

import pytest

from src.storage import LATEST_SCHEMA_VERSION, connect, current_schema_version, run_migrations


REQUIRED_TABLES = {
    "schema_version",
    "workspaces",
    "workspace_repositories",
    "tasks",
    "subtasks",
    "task_dependencies",
    "messages",
    "approval_gates",
    "dispatches",
    "lifecycle_events",
    "evidence_artifacts",
    "review_runs",
    "handoffs",
    "providers",
    "settings",
}


def test_run_migrations_creates_required_tables_and_tracks_version(tmp_path):
    db_path = tmp_path / "sarathi.db"

    with connect(db_path) as conn:
        run_migrations(conn)

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        assert REQUIRED_TABLES <= tables
        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION


def test_required_records_are_workspace_scoped(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        required_workspace_tables = {
            "tasks",
            "subtasks",
            "approval_gates",
            "dispatches",
            "evidence_artifacts",
            "review_runs",
            "handoffs",
            "providers",
            "settings",
        }

        for table_name in required_workspace_tables:
            columns = {
                row["name"]: row
                for row in conn.execute(f"PRAGMA table_info({table_name})")
            }
            assert "workspace_id" in columns
            assert columns["workspace_id"]["notnull"] == 1


def test_child_records_cannot_cross_workspace_boundaries(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)
            """,
            (
                "workspace-a",
                "Workspace A",
                "/work/a",
                "{}",
                "now",
                "now",
                "workspace-b",
                "Workspace B",
                "/work/b",
                "{}",
                "now",
                "now",
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks (id, workspace_id, title, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("task-a", "workspace-a", "Task A", "queued", "{}", "now", "now"),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO subtasks (
                    id, workspace_id, task_id, title, status, metadata, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "subtask-cross",
                    "workspace-b",
                    "task-a",
                    "Cross workspace",
                    "queued",
                    "{}",
                    "now",
                    "now",
                ),
            )


def test_task_dependencies_cannot_cross_workspace_boundaries(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)
            """,
            (
                "workspace-a",
                "Workspace A",
                "/work/a",
                "{}",
                "now",
                "now",
                "workspace-b",
                "Workspace B",
                "/work/b",
                "{}",
                "now",
                "now",
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks (id, workspace_id, title, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-a",
                "workspace-a",
                "Task A",
                "queued",
                "{}",
                "now",
                "now",
                "task-b",
                "workspace-b",
                "Task B",
                "queued",
                "{}",
                "now",
                "now",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO task_dependencies (
                    workspace_id, task_id, depends_on_task_id, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                ("workspace-a", "task-a", "task-b", "now"),
            )


def test_migrations_create_foreign_key_indexes(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        index_names = {
            row["name"]
            for table_name in REQUIRED_TABLES
            for row in conn.execute(f"PRAGMA index_list({table_name})")
        }

        assert {
            "idx_tasks_workspace",
            "idx_subtasks_task",
            "idx_messages_workspace_task",
            "idx_task_dependencies_workspace_task",
            "idx_lifecycle_events_workspace_task",
        } <= index_names


def test_run_migrations_is_idempotent(tmp_path):
    db_path = tmp_path / "sarathi.db"

    with connect(db_path) as conn:
        run_migrations(conn)
        run_migrations(conn)

        versions = conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()

        assert [row["version"] for row in versions] == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_connect_returns_row_factory_connection(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("workspace-1", "Sarathi", "/work/sarathi", "{}", "now", "now"),
        )
        conn.execute(
            "INSERT INTO settings (workspace_id, key, value) VALUES (?, ?, ?)",
            ("workspace-1", "theme", "river"),
        )

        row = conn.execute("SELECT key, value FROM settings").fetchone()

        assert isinstance(conn, sqlite3.Connection)
        assert row["key"] == "theme"
        assert row["value"] == "river"


def test_connect_creates_missing_parent_directories(tmp_path):
    db_path = tmp_path / "nested" / "state" / "sarathi.db"

    with connect(db_path) as conn:
        run_migrations(conn)

    assert db_path.exists()
