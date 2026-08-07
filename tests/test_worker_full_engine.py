"""Tests for full-Engine tasks driven through the worker (src/service/full_engine.py)."""

from __future__ import annotations

from pathlib import Path

from src.service.full_engine import run_claimed_full_engine_task
from src.service.worker import run_worker
from src.storage import Storage, connect, run_migrations


def _minimal_policy_pack(tmp_path: Path) -> Path:
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": '```yaml\ntest:\n  command: "echo test"\n```\n',
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)
    return policy_dir


def _seed_full_engine_task(
    storage: Storage, *, policy_pack: str, complexity: str = "low"
) -> dict:
    workspace = storage.create_workspace(name="ws", root_path="/tmp/ws")
    return storage.create_task(
        workspace_id=workspace["id"],
        title="Fix bug",
        status="queued",
        description="Fix bug",
        metadata={
            "execution_mode": "full_engine",
            "engine_task_id": "full-engine-1",
            "policy_pack": policy_pack,
            "complexity": complexity,
        },
    )


def test_run_claimed_full_engine_task_runs_to_completion(tmp_path):
    policy_dir = _minimal_policy_pack(tmp_path)
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = _seed_full_engine_task(storage, policy_pack=str(policy_dir))

        claimed = storage.claim_full_engine_task(task["id"], worker_id="w1")
        assert claimed is not None
        assert claimed["status"] == "running"

        outcome = run_claimed_full_engine_task(
            storage, claimed, worker_id="w1", tasks_dir=str(tmp_path / "tasks")
        )

        final = storage.get_task(task["id"])
        assert outcome["status"] in {"done", "blocked", "queued"}
        assert final["status"] == outcome["status"]
        assert final["metadata"]["engine_task_id"] == "full-engine-1"


def test_run_claimed_full_engine_task_resumes_across_calls(tmp_path, monkeypatch):
    # BUILD's graph step limit forces run_task to return early with
    # current_phase still set (not None, no stop_reason) -- the task must be
    # requeued (status='queued') so a later poll resumes it, mirroring
    # test_engine_resume_advances_paused_build_task in tests/test_engine.py.
    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")
    policy_dir = _minimal_policy_pack(tmp_path)
    db_path = tmp_path / "sarathi.db"
    tasks_dir = str(tmp_path / "tasks")
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = _seed_full_engine_task(storage, policy_pack=str(policy_dir))

        claimed = storage.claim_full_engine_task(task["id"], worker_id="w1")
        first = run_claimed_full_engine_task(
            storage, claimed, worker_id="w1", tasks_dir=tasks_dir
        )
        assert first["status"] == "queued"
        assert storage.get_task(task["id"])["status"] == "queued"

        # Second poll: re-claim (status went back to 'queued') and resume.
        reclaimed = storage.claim_full_engine_task(task["id"], worker_id="w1")
        assert reclaimed is not None
        second = run_claimed_full_engine_task(
            storage, reclaimed, worker_id="w1", tasks_dir=tasks_dir
        )

        assert second["status"] in {"done", "blocked", "queued"}


def test_run_worker_claims_and_runs_full_engine_task(tmp_path):
    policy_dir = _minimal_policy_pack(tmp_path)
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        task = _seed_full_engine_task(storage, policy_pack=str(policy_dir))

    summary = run_worker(
        db_path, once=True, worker_id="w1", tasks_dir=str(tmp_path / "tasks")
    )

    assert summary["full_engine_claimed"] == 1
    assert summary["full_engine_failed"] == 0
    assert summary["claimed"] == 0  # subtask queue untouched

    with connect(db_path) as conn:
        storage = Storage(conn)
        final = storage.get_task(task["id"])
    assert (
        final["status"] != "queued"
        or final["metadata"].get("engine_current_phase") is not None
    )


def test_run_worker_prefers_subtasks_over_full_engine_tasks(tmp_path):
    # A ready subtask exists alongside a queued full-Engine task: the worker
    # must claim the subtask first (its own queue is polled every cycle;
    # full-Engine tasks are only tried when nothing else is ready).
    policy_dir = _minimal_policy_pack(tmp_path)
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        _seed_full_engine_task(storage, policy_pack=str(policy_dir))
        workspace = storage.create_workspace(name="ws2", root_path="/tmp/ws2")
        subtask_task = storage.create_task(
            workspace_id=workspace["id"], title="T", status="in_progress"
        )
        storage.create_subtask(
            workspace_id=workspace["id"],
            task_id=subtask_task["id"],
            title="do the thing",
            status="in_progress",
            metadata={"provider": "local", "task_packet": {"goal": "do the thing"}},
        )

    summary = run_worker(
        db_path, once=True, worker_id="w1", tasks_dir=str(tmp_path / "tasks")
    )

    assert summary["claimed"] == 1
    assert summary["full_engine_claimed"] == 0
