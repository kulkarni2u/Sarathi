from src.runtime.contracts import UsageRecord
from src.service.usage_stats import build_usage_stats
from src.storage import Storage, connect, run_migrations


def _seed_workspace(storage):
    workspace = storage.create_workspace(name="Pravaha UI", root_path="/work/pravaha")

    # Task 1: approved review with a score, dispatch usage recorded.
    task1 = storage.create_task(
        workspace_id=workspace["id"],
        title="Add SQLite storage",
        status="done",
        metadata={"task_class": "implementation/feature"},
    )
    storage.create_dispatch(
        workspace_id=workspace["id"],
        task_id=task1["id"],
        agent_name="Pravaha",
        status="completed",
        metadata={
            "usage": UsageRecord(
                provider_id="claude",
                provider_family="anthropic",
                dispatch_id="dispatch-1",
                input_tokens=800,
                output_tokens=200,
                total_tokens=1000,
                estimated=False,
                usage_source="reported",
            ).to_artifact()
        },
    )
    storage.create_review_run(
        workspace_id=workspace["id"],
        task_id=task1["id"],
        status="approved",
        summary="Looks good.",
        metadata={"review_type": "code", "review_verdict": {"score": 0.9, "outcome": "pass"}},
    )

    # Task 2: rejected review with a lower score, larger dispatch usage.
    task2 = storage.create_task(
        workspace_id=workspace["id"],
        title="Refactor scheduler",
        status="in_progress",
        metadata={"task_class": "mutation/refactor"},
    )
    storage.create_dispatch(
        workspace_id=workspace["id"],
        task_id=task2["id"],
        agent_name="Disha",
        status="completed",
        metadata={
            "usage": UsageRecord(
                provider_id="codex",
                provider_family="openai",
                dispatch_id="dispatch-2",
                input_tokens=1600,
                output_tokens=400,
                total_tokens=2000,
                estimated=False,
                usage_source="reported",
            ).to_artifact()
        },
    )
    storage.create_review_run(
        workspace_id=workspace["id"],
        task_id=task2["id"],
        status="rejected",
        summary="Needs more work.",
        metadata={"review_type": "code", "review_verdict": {"score": 0.4, "outcome": "fail"}},
    )

    # Task 3: no dispatches, no reviews — everything should degrade to None/"—".
    task3 = storage.create_task(
        workspace_id=workspace["id"],
        title="Investigate flaky test",
        status="pending",
    )

    return workspace, task1, task2, task3


def test_build_usage_stats_aggregates_and_per_task(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace, task1, task2, task3 = _seed_workspace(storage)

        stats = build_usage_stats(storage, workspace["id"])

        assert stats["workspace_id"] == workspace["id"]
        assert stats["task_count"] == 3

        # test_pass_rate: 1 of 2 scored tasks passed (task3 has no review).
        assert stats["test_pass_rate"] == 0.5

        # avg_blast_radius: mean of (1 - 0.9) and (1 - 0.4) => mean(0.1, 0.6)
        assert stats["avg_blast_radius"] == pytest_approx(0.35)

        # total_tokens: sum across all dispatches.
        assert stats["total_tokens"] == 3000

        # No proposals table/source available from pure storage.
        assert stats["proposal_counts"] is None

        assert len(stats["tasks"]) == 3

        by_id = {entry["task_id"]: entry for entry in stats["tasks"]}

        entry1 = by_id[task1["id"]]
        assert entry1["title"] == "Add SQLite storage"
        assert entry1["task_class"] == "implementation/feature"
        assert entry1["agent"] == "Pravaha"
        assert entry1["pass"] is True
        assert entry1["blast_radius"] == pytest_approx(0.1)
        assert entry1["tokens"] == 1000
        assert entry1["latency"] is not None

        entry2 = by_id[task2["id"]]
        assert entry2["task_class"] == "mutation/refactor"
        assert entry2["agent"] == "Disha"
        assert entry2["pass"] is False
        assert entry2["blast_radius"] == pytest_approx(0.6)
        assert entry2["tokens"] == 2000

        entry3 = by_id[task3["id"]]
        assert entry3["title"] == "Investigate flaky test"
        assert entry3["task_class"] is None
        assert entry3["agent"] is None
        assert entry3["pass"] is None
        assert entry3["blast_radius"] is None
        assert entry3["tokens"] is None


def test_build_usage_stats_recent_tasks_ordering(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Ordering", root_path="/work/ordering")
        first = storage.create_task(workspace_id=workspace["id"], title="First", status="done")
        second = storage.create_task(workspace_id=workspace["id"], title="Second", status="done")

        stats = build_usage_stats(storage, workspace["id"])

        # Most-recent-first.
        assert [entry["task_id"] for entry in stats["tasks"]] == [second["id"], first["id"]]


def test_build_usage_stats_respects_task_limit(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Limit", root_path="/work/limit")
        for i in range(5):
            storage.create_task(workspace_id=workspace["id"], title=f"Task {i}", status="done")

        stats = build_usage_stats(storage, workspace["id"], task_limit=2)

        assert stats["task_count"] == 5
        assert len(stats["tasks"]) == 2


def test_build_usage_stats_empty_workspace(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Empty", root_path="/work/empty")

        stats = build_usage_stats(storage, workspace["id"])

        assert stats["task_count"] == 0
        assert stats["test_pass_rate"] is None
        assert stats["avg_blast_radius"] is None
        assert stats["total_tokens"] == 0
        assert stats["proposal_counts"] is None
        assert stats["tasks"] == []


def test_build_usage_stats_never_raises_on_missing_storage_methods(tmp_path):
    """A storage-like object missing optional list methods degrades gracefully."""

    class BareStorage:
        def __init__(self, real_storage):
            self._real = real_storage

        def list_tasks_for_workspace(self, workspace_id):
            return self._real.list_tasks_for_workspace(workspace_id)

        # Intentionally no list_review_runs_for_task / list_dispatches_for_task.

    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Bare", root_path="/work/bare")
        storage.create_task(workspace_id=workspace["id"], title="Solo task", status="pending")

        bare = BareStorage(storage)
        stats = build_usage_stats(bare, workspace["id"])

        assert stats["task_count"] == 1
        entry = stats["tasks"][0]
        assert entry["pass"] is None
        assert entry["blast_radius"] is None
        assert entry["tokens"] is None


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)
