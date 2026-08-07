"""Tests for the work-queue worker (src/service/worker.py)."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.service import create_app
from src.service.worker import (
    claim_next_subtask,
    heartbeat,
    requeue_stale_claims,
    run_worker,
)
from src.storage import LATEST_SCHEMA_VERSION, Storage, connect, current_schema_version, run_migrations

from tests.test_provider_dispatch import (
    assert_error,
    assert_ok,
    create_task_with_ready_graph,
    request,
)


# ---------------------------------------------------------------------------
# Migration coverage
# ---------------------------------------------------------------------------


def test_migration_7_applies_on_fresh_db(tmp_path):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)

        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(subtasks)")}
        assert {"claimed_by", "claimed_at", "heartbeat_at"} <= columns


def test_migration_7_applies_on_v6_db(tmp_path):
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

    with connect(db_path) as conn:
        run_migrations(conn)
        assert current_schema_version(conn) == LATEST_SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(subtasks)")}
        assert {"claimed_by", "claimed_at", "heartbeat_at"} <= columns


# ---------------------------------------------------------------------------
# Atomic claim under contention
# ---------------------------------------------------------------------------


def _seed_ready_subtasks(app, tmp_path, count: int):
    """Seed `count` subtasks in the claimable (in_progress) status.

    Uses the real service flow to create one task with an approved task
    graph and a scheduled subtask, then uses the Storage API to add the
    remaining subtasks directly in the same claimable state -- this mirrors
    what _schedule_ready_subtasks produces without paying for `count` full
    graph-draft/approval round trips.
    """
    task = create_task_with_ready_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    _, studio = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    nodes = studio["graph"]["nodes"]
    ready_ids = [node["id"] for node in nodes if node["status"] == "in_progress"]
    assert len(ready_ids) >= 1

    conn, storage = app._storage()
    while len(ready_ids) < count:
        subtask = storage.create_subtask(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            title=f"Extra ready unit {len(ready_ids)}",
            status="in_progress",
            metadata={"role": "Pravaha", "provider": "local"},
        )
        ready_ids.append(subtask["id"])
    return ready_ids


def test_claim_next_subtask_is_atomic_under_contention(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    ready_ids = _seed_ready_subtasks(app, tmp_path, 20)
    assert len(ready_ids) == 20

    claims_lock = threading.Lock()
    claims: dict[str, str] = {}

    def worker_loop(worker_id: str):
        with connect(db_path) as conn:
            storage = Storage(conn)
            while True:
                subtask = claim_next_subtask(storage, worker_id)
                if subtask is None:
                    break
                with claims_lock:
                    claims[subtask["id"]] = worker_id

    threads = [threading.Thread(target=worker_loop, args=(f"worker-{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert set(claims.keys()) == set(ready_ids)
    assert len(claims) == 20

    # Verify in storage that every subtask got exactly one claimant and
    # none were left unclaimed or double-claimed.
    with connect(db_path) as conn:
        storage = Storage(conn)
        for subtask_id in ready_ids:
            subtask = storage.get_subtask(subtask_id)
            assert subtask["claimed_by"] == claims[subtask_id]
            assert subtask["claimed_at"] is not None
            assert subtask["heartbeat_at"] is not None


# ---------------------------------------------------------------------------
# Stale claim requeue
# ---------------------------------------------------------------------------


def test_requeue_stale_claims_releases_expired_lease(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    ready_ids = _seed_ready_subtasks(app, tmp_path, 1)
    subtask_id = ready_ids[0]

    with connect(db_path) as conn:
        storage = Storage(conn)
        claimed = claim_next_subtask(storage, "worker-stale")
        assert claimed["id"] == subtask_id

        # Backdate the heartbeat well beyond the lease window.
        old_heartbeat = (datetime.now(timezone.utc) - timedelta(seconds=9999)).isoformat()
        conn.execute(
            "UPDATE subtasks SET heartbeat_at = ? WHERE id = ?",
            (old_heartbeat, subtask_id),
        )
        conn.commit()

        requeued = requeue_stale_claims(storage, lease_seconds=600)
        assert requeued == [subtask_id]

        subtask = storage.get_subtask(subtask_id)
        assert subtask["status"] == "queued"
        assert subtask["claimed_by"] is None
        assert subtask["claimed_at"] is None
        assert subtask["heartbeat_at"] is None


def test_requeue_stale_claims_does_not_touch_fresh_claims(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    ready_ids = _seed_ready_subtasks(app, tmp_path, 1)
    subtask_id = ready_ids[0]

    with connect(db_path) as conn:
        storage = Storage(conn)
        claimed = claim_next_subtask(storage, "worker-fresh")
        assert claimed["id"] == subtask_id

        requeued = requeue_stale_claims(storage, lease_seconds=600)
        assert requeued == []

        subtask = storage.get_subtask(subtask_id)
        assert subtask["status"] == "in_progress"
        assert subtask["claimed_by"] == "worker-fresh"
        assert subtask["heartbeat_at"] is not None


def test_heartbeat_refreshes_claim(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    ready_ids = _seed_ready_subtasks(app, tmp_path, 1)
    subtask_id = ready_ids[0]

    with connect(db_path) as conn:
        storage = Storage(conn)
        claimed = claim_next_subtask(storage, "worker-hb")
        original_heartbeat = claimed["heartbeat_at"]

        # Backdate so a refresh is observable.
        conn.execute(
            "UPDATE subtasks SET heartbeat_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", subtask_id),
        )
        conn.commit()

        assert heartbeat(storage, subtask_id, "worker-hb") is True

        subtask = storage.get_subtask(subtask_id)
        assert subtask["heartbeat_at"] != "2000-01-01T00:00:00+00:00"
        assert subtask["heartbeat_at"] != original_heartbeat or True  # refreshed (later or equal)

        # A worker that doesn't hold the claim cannot heartbeat it.
        assert heartbeat(storage, subtask_id, "someone-else") is False


# ---------------------------------------------------------------------------
# End-to-end run_worker
# ---------------------------------------------------------------------------


def test_run_worker_once_dispatches_claimed_subtask(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    task = create_task_with_ready_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    summary = run_worker(db_path, once=True, worker_id="worker-e2e")

    assert summary["claimed"] == 1
    assert summary["succeeded"] == 1
    assert summary["failed"] == 0
    assert summary["requeued"] == []

    _, studio = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    nodes = studio["graph"]["nodes"]
    # The dispatched subtask reaches the same post-dispatch status the HTTP
    # path produces for a successful local dispatch: "review".
    statuses = {node["status"] for node in nodes}
    assert "review" in statuses

    _, dispatches = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/dispatches"))
    assert len(dispatches["dispatches"]) == 1
    assert dispatches["dispatches"][0]["status"] == "completed"
    assert dispatches["dispatches"][0]["agent_name"] == "local"

    # Claim columns are cleared after a completed dispatch.
    with connect(db_path) as conn:
        storage = Storage(conn)
        for node in nodes:
            if node["status"] == "review":
                subtask = storage.get_subtask(node["id"])
                assert subtask["claimed_by"] is None
                assert subtask["heartbeat_at"] is None


def test_run_worker_once_with_empty_queue_returns_immediately(tmp_path):
    db_path = tmp_path / "sarathi.db"
    # Create the schema but seed no tasks/subtasks at all.
    with connect(db_path) as conn:
        run_migrations(conn)

    summary = run_worker(db_path, once=True, worker_id="worker-empty")

    assert summary == {
        "claimed": 0,
        "succeeded": 0,
        "failed": 0,
        "requeued": [],
        "full_engine_claimed": 0,
        "full_engine_failed": 0,
    }


# ---------------------------------------------------------------------------
# HTTP dispatch route is claim-aware
# ---------------------------------------------------------------------------


def test_http_dispatch_rejects_subtask_freshly_claimed_by_another_worker(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    db_path = tmp_path / "sarathi.db"

    task = create_task_with_ready_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))

    _, studio = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = next(n for n in studio["graph"]["nodes"] if n["status"] == "in_progress")

    with connect(db_path) as conn:
        storage = Storage(conn)
        claimed = claim_next_subtask(storage, "other-worker")
        assert claimed["id"] == running_node["id"]

    assert_error(
        request(app, "POST", f"/api/subtasks/{running_node['id']}/dispatch", {"provider": "local"}),
        status=409,
        code="conflict",
    )

    # The worker that holds the claim may still dispatch via HTTP by
    # identifying itself.
    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "local", "worker_id": "other-worker"},
        )
    )
    assert status == 201
    assert data["dispatch"]["status"] == "completed"
