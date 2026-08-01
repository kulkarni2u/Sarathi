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


def test_migration_7_adds_subtask_claim_columns_on_fresh_db(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(subtasks)")}
        assert {"claimed_by", "claimed_at", "heartbeat_at"} <= columns


def test_migration_7_applies_on_top_of_v6_db(tmp_path):
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        assert current_schema_version(conn) == 6
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(subtasks)")}
        assert "claimed_by" not in columns

    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(subtasks)")}
        assert {"claimed_by", "claimed_at", "heartbeat_at"} <= columns

        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
        ]
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_migration_8_adds_project_id_column_to_tasks(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "project_id" in columns


def test_migration_8_creates_default_project_for_each_workspace(tmp_path):
    # This test verifies that during migration 8, when run_migrations is called,
    # default projects are created for all existing workspaces
    with connect(tmp_path / "sarathi.db") as conn:
        # Manually run migrations 1-7 to set up v7 schema
        from src.storage import (
            _MIGRATION_001,
            _MIGRATION_002,
            _MIGRATION_003,
            _MIGRATION_004,
            _MIGRATION_005,
            _MIGRATION_006,
            _MIGRATION_007,
            _utc_now,
        )

        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        # Create two workspaces before migration 8
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)
            """,
            (
                "workspace-1",
                "Workspace 1",
                "/work/1",
                "{}",
                "now",
                "now",
                "workspace-2",
                "Workspace 2",
                "/work/2",
                "{}",
                "now",
                "now",
            ),
        )
        conn.commit()

        # Run migrations to apply migration 8
        run_migrations(conn)

        projects = conn.execute(
            "SELECT id, workspace_id, name, status FROM projects ORDER BY workspace_id"
        ).fetchall()

        # Should have 2 default projects, one for each workspace
        default_projects = {
            (row["workspace_id"], row["id"], row["name"], row["status"])
            for row in projects
            if row["id"] == row["workspace_id"] + "-default"
        }

        assert len(default_projects) == 2
        assert ("workspace-1", "workspace-1-default", "Default", "active") in default_projects
        assert ("workspace-2", "workspace-2-default", "Default", "active") in default_projects


def test_migration_8_does_not_duplicate_default_projects(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        # Create workspace and a default project manually
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("workspace-1", "Workspace 1", "/work/1", "{}", "now", "now"),
        )
        conn.execute(
            """
            INSERT INTO projects (id, workspace_id, name, description, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("workspace-1-default", "workspace-1", "Default", "Existing project", "active", "{}", "now", "now"),
        )
        conn.commit()

        # Run migrations again
        run_migrations(conn)

        # Check that there's still only one default project
        projects = conn.execute(
            "SELECT COUNT(*) as count FROM projects WHERE id = 'workspace-1-default'"
        ).fetchone()

        assert projects["count"] == 1


def test_migration_8_backfills_existing_tasks_with_project_id(tmp_path):
    # Test that migration 8 backfills existing tasks with their workspace's default project
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _MIGRATION_007,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        # Run migrations 1-7
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        # Create a workspace
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("workspace-1", "Workspace 1", "/work/1", "{}", "now", "now"),
        )

        # Create tasks (before migration 8, so no project_id column yet)
        conn.execute(
            """
            INSERT INTO tasks (id, workspace_id, title, description, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "workspace-1",
                "Task 1",
                None,
                "pending",
                "{}",
                "now",
                "now",
                "task-2",
                "workspace-1",
                "Task 2",
                None,
                "pending",
                "{}",
                "now",
                "now",
            ),
        )
        conn.commit()

    # Now apply migration 8
    with connect(db_path) as conn:
        run_migrations(conn)

        # Verify tasks are backfilled
        tasks_after = conn.execute(
            "SELECT id, workspace_id, project_id FROM tasks ORDER BY id"
        ).fetchall()

        assert len(tasks_after) == 2
        for row in tasks_after:
            assert row["project_id"] == "workspace-1-default"


def test_migration_8_applies_on_top_of_v7_db(tmp_path):
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _MIGRATION_007,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        assert current_schema_version(conn) == 7
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "project_id" not in columns

        # Create some test data
        conn.execute(
            """
            INSERT INTO workspaces (id, name, root_path, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("workspace-1", "Workspace 1", "/work/1", "{}", "now", "now"),
        )
        conn.execute(
            """
            INSERT INTO tasks (id, workspace_id, title, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("task-1", "workspace-1", "Task 1", "pending", "{}", "now", "now"),
        )
        conn.commit()

    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "project_id" in columns

        # Verify the task was backfilled
        task = conn.execute("SELECT project_id FROM tasks WHERE id = 'task-1'").fetchone()
        assert task["project_id"] == "workspace-1-default"

        # Verify default project was created
        project = conn.execute(
            "SELECT id, name FROM projects WHERE id = 'workspace-1-default'"
        ).fetchone()
        assert project is not None
        assert project["name"] == "Default"

        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
        ]
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_migration_12_creates_slack_tables_on_fresh_db(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "slack_inbox",
            "slack_outbox",
            "slack_task_bindings",
            "slack_external_inputs",
        } <= tables

        outbox_columns = {row["name"] for row in conn.execute("PRAGMA table_info(slack_outbox)")}
        assert "attempt_count" in outbox_columns


def test_migration_10_creates_users_table_on_fresh_db(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "users" in tables

        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        assert {"username", "token"} <= user_columns


def test_migration_11_creates_proposal_decisions_table_on_fresh_db(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        assert LATEST_SCHEMA_VERSION == 12

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "proposal_decisions" in tables

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposal_decisions)")}
        assert {"workspace_id", "proposal_id", "status", "payload", "reviewed_at"} <= columns


def test_migration_11_applies_on_top_of_v10_db(tmp_path):
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _MIGRATION_007,
        _MIGRATION_008,
        _MIGRATION_009,
        _MIGRATION_010,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
            (8, _MIGRATION_008),
            (9, _MIGRATION_009),
            (10, _MIGRATION_010),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        assert current_schema_version(conn) == 10
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "proposal_decisions" not in tables

    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "proposal_decisions" in tables

        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
        ]
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_migration_10_applies_on_top_of_v9_db(tmp_path):
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _MIGRATION_007,
        _MIGRATION_008,
        _MIGRATION_009,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
            (8, _MIGRATION_008),
            (9, _MIGRATION_009),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        assert current_schema_version(conn) == 9
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "users" not in tables

    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "users" in tables

        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
        ]
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_migration_9_creates_session_tables_on_fresh_db(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"sessions", "session_participants"} <= tables

        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        assert "session_id" in message_columns


def test_migration_9_applies_on_top_of_v8_db(tmp_path):
    from src.storage import (
        _MIGRATION_001,
        _MIGRATION_002,
        _MIGRATION_003,
        _MIGRATION_004,
        _MIGRATION_005,
        _MIGRATION_006,
        _MIGRATION_007,
        _MIGRATION_008,
        _utc_now,
    )

    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        for version, script in (
            (1, _MIGRATION_001),
            (2, _MIGRATION_002),
            (3, _MIGRATION_003),
            (4, _MIGRATION_004),
            (5, _MIGRATION_005),
            (6, _MIGRATION_006),
            (7, _MIGRATION_007),
            (8, _MIGRATION_008),
        ):
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            conn.commit()

        assert current_schema_version(conn) == 8
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "sessions" not in tables

    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"sessions", "session_participants"} <= tables

        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        assert "session_id" in message_columns

        versions = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_version ORDER BY version")
        ]
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
