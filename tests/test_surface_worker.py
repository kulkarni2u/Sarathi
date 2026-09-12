from __future__ import annotations

import subprocess

import pytest

from src.service import full_engine
from src.service.full_engine import (
    _apply_approval_in_child,
    _registered_workspace_root,
    resume_full_engine_task,
    run_claimed_full_engine_task,
)
from src.engine import Complexity, Phase, PhaseResult, PersistenceManager, TaskContext
from src.service.worker import run_worker
from src.storage import Storage, connect, run_migrations


def _save_pending_approval_context(root, engine_task_id: str) -> None:
    context = TaskContext(task_id=engine_task_id, description="run", complexity=Complexity.LOW)
    context.current_phase = Phase.BUILD
    context.phase_results.append(
        PhaseResult(
            phase=Phase.BUILD, outcome="escalate",
            artifacts={"pause_execution": True}, evidence={"human_attention_required": True},
        )
    )
    PersistenceManager(str(root / ".sarathi" / "tasks")).save_task(context)


def test_full_engine_resolves_registered_workspace_root(tmp_path):
    db_path = tmp_path / "sarathi.db"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="workspace", root_path=str(workspace_root))
        task = storage.create_task(
            workspace_id=workspace["id"], title="run", status="queued",
            metadata={"execution_mode": "full_engine"},
        )
        assert _registered_workspace_root(storage, task) == workspace_root.resolve()


def test_full_engine_fails_closed_when_workspace_is_missing(tmp_path):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="gone", root_path=str(tmp_path / "gone"))
        task = storage.create_task(
            workspace_id=workspace["id"], title="run", status="queued",
            metadata={"execution_mode": "full_engine"},
        )
        with pytest.raises(RuntimeError, match="workspace"):
            _registered_workspace_root(storage, task)


def test_worker_max_items_counts_full_engine_items(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="workspace", root_path=str(tmp_path))
        storage.create_task(
            workspace_id=workspace["id"], title="run", status="queued",
            metadata={"execution_mode": "full_engine"},
        )
    monkeypatch.setattr("src.service.worker.run_claimed_full_engine_task", lambda *a, **k: None)
    summary = run_worker(db_path, worker_id="w", max_items=1, poll_interval=0)
    assert summary["full_engine_claimed"] == 1


def test_resume_full_engine_requires_explicit_approval(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with connect(tmp_path / "db.sqlite") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="ws", root_path=str(root))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="waiting_human",
                                   metadata={"execution_mode": "full_engine", "engine_task_id": "e1"})
        context = TaskContext(task_id="e1", description="run", complexity=Complexity.LOW)
        context.current_phase = Phase.BUILD
        context.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="escalate",
                                                  artifacts={"pause_execution": True},
                                                  evidence={"human_attention_required": True}))
        PersistenceManager(str(root / ".sarathi" / "tasks")).save_task(context)
        with pytest.raises(RuntimeError, match="approval"):
            resume_full_engine_task(storage, task)
        resume_full_engine_task(storage, task, approval={"approved": True, "approved_by": "human"})
        assert storage.get_task(task["id"])["status"] == "queued"


def test_concurrent_full_engine_approval_reservation_is_exclusive(tmp_path):
    """Reviewer repro: two approval calls can both load the same paused
    context and race to write conflicting results, one overwriting a
    newly-claimed 'running' row back to 'queued'. The reservation CAS must
    let only one caller through; a concurrent/duplicate call must fail
    immediately without touching persisted context or claim fields."""
    root = tmp_path / "workspace"
    root.mkdir()
    with connect(tmp_path / "db.sqlite") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="ws", root_path=str(root))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="waiting_human",
                                   metadata={"execution_mode": "full_engine", "engine_task_id": "e2"})
        _save_pending_approval_context(root, "e2")

        # Request A reserves the transition (as resume_full_engine_task would
        # do before spawning its subprocess).
        reserved = storage.reserve_full_engine_approval(task["id"])
        assert reserved is not None

        # Request B, arriving concurrently for the same task, must not also
        # win a reservation, and the public entrypoint must reject it
        # without mutating anything.
        assert storage.reserve_full_engine_approval(task["id"]) is None
        with pytest.raises(RuntimeError, match="already in progress|not awaiting approval"):
            resume_full_engine_task(storage, task, approval={"approved": True})
        assert storage.get_task(task["id"])["status"] == "waiting_human"


def test_stale_approval_reservation_cannot_clobber_fresh_worker_claim(tmp_path, monkeypatch):
    """Direct reproduction of the reviewer's bounded repro: a reservation
    that was still open when the row got requeued and reclaimed by a worker
    must not be able to overwrite that fresh 'running' claim back to
    'queued' -- resolve_full_engine_approval must be a no-op once the
    reservation token no longer matches."""
    root = tmp_path / "workspace"
    root.mkdir()
    # _apply_approval_in_child assumes it's already running with cwd set to
    # the workspace root (normally guaranteed by the approval subprocess);
    # called directly here to inject the race deterministically.
    monkeypatch.chdir(root)
    with connect(tmp_path / "db.sqlite") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="ws", root_path=str(root))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="waiting_human",
                                   metadata={"execution_mode": "full_engine", "engine_task_id": "e3"})
        _save_pending_approval_context(root, "e3")

        reserved = storage.reserve_full_engine_approval(task["id"])
        reservation = reserved["metadata"]["approval_reservation"]

        # The reserved approval completes and requeues the task, which a
        # worker then claims and starts running under a brand-new
        # generation -- simulating a slow/duplicate second write arriving
        # for the SAME original reservation after that point.
        _apply_approval_in_child(storage, reserved, {"approved": True}, reservation=reservation)
        assert storage.get_task(task["id"])["status"] == "queued"
        claimed = storage.claim_full_engine_task(task["id"], worker_id="worker-1")
        assert claimed["status"] == "running"

        with pytest.raises(RuntimeError, match="reservation lost"):
            _apply_approval_in_child(storage, reserved, {"approved": True}, reservation=reservation)
        after = storage.get_task(task["id"])
        assert after["status"] == "running"
        assert after["metadata"]["claimed_by"] == "worker-1"


def test_child_execution_refuses_replaced_claim_generation(tmp_path, monkeypatch):
    """Reviewer repro: the child receives task ID/worker ID then reloads
    whichever generation currently exists in storage -- if the same worker
    reclaims before a slow-to-start old child gets going, that old child
    would silently adopt the replacement generation. It must instead verify
    the ORIGINAL generation before constructing Engine and refuse to run."""
    root = tmp_path / "workspace"
    root.mkdir()
    with connect(tmp_path / "db.sqlite") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="ws", root_path=str(root))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="queued",
                                   metadata={"execution_mode": "full_engine"})
        first_claim = storage.claim_full_engine_task(task["id"], worker_id="worker-1")
        original_generation = first_claim["metadata"]["claim_generation"]

        # The first child is slow to start; meanwhile the row is requeued
        # and the SAME worker reclaims it under a brand-new generation.
        storage.update_task(task["id"], status="queued", metadata=first_claim["metadata"])
        second_claim = storage.claim_full_engine_task(task["id"], worker_id="worker-1")
        assert second_claim["metadata"]["claim_generation"] != original_generation

        def _explode(*_args, **_kwargs):
            raise AssertionError("Delayed child constructed Engine after a replacement claim")

        monkeypatch.setattr(full_engine, "Engine", _explode)

        with pytest.raises(RuntimeError, match="no longer matches"):
            run_claimed_full_engine_task(
                storage, second_claim, worker_id="worker-1", _in_child=True,
                expected_claim_generation=original_generation,
            )
        after = storage.get_task(task["id"])
        assert after["status"] == "running"
        assert after["metadata"]["claim_generation"] == second_claim["metadata"]["claim_generation"]


def test_run_worker_marks_task_blocked_when_workspace_missing(tmp_path):
    """Reviewer repro: workspace validation raises before any bookkeeping,
    so the claimed row was left "running" forever while the worker only
    incremented its failure counter. Exercised through run_worker (not just
    the helper) since that's the code path a real crashed/misconfigured
    workspace hits."""
    db_path = tmp_path / "db.sqlite"
    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="gone", root_path=str(tmp_path / "does-not-exist"))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="queued",
                                   metadata={"execution_mode": "full_engine"})
        task_id = task["id"]

    summary = run_worker(db_path, worker_id="w", max_items=1, poll_interval=0)
    assert summary["full_engine_failed"] == 1

    with connect(db_path) as conn:
        after = Storage(conn).get_task(task_id)
    assert after["status"] == "blocked"
    assert after["metadata"].get("engine_error") == "workspace_unavailable"


def test_full_engine_approval_timeout_releases_reservation_for_retry(tmp_path, monkeypatch):
    """record_approval does no provider dispatch, so a stalled child must be
    bounded rather than holding the calling request forever, and the
    reservation must be released afterward so a retry isn't permanently
    blocked reporting "already in progress"."""
    root = tmp_path / "workspace"
    root.mkdir()
    with connect(tmp_path / "db.sqlite") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        ws = storage.create_workspace(name="ws", root_path=str(root))
        task = storage.create_task(workspace_id=ws["id"], title="run", status="waiting_human",
                                   metadata={"execution_mode": "full_engine", "engine_task_id": "e4"})
        _save_pending_approval_context(root, "e4")

        def _stalled(*_args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="full_engine --approve", timeout=kwargs.get("timeout", 30))

        with monkeypatch.context() as m:
            m.setattr(full_engine.subprocess, "run", _stalled)
            with pytest.raises(RuntimeError, match="timed out"):
                resume_full_engine_task(storage, task, approval={"approved": True})
            after = storage.get_task(task["id"])
            assert after["status"] == "waiting_human"
            assert "approval_reservation" not in after["metadata"]

        # subprocess.run is real again now -- a retry must succeed cleanly.
        resume_full_engine_task(storage, task, approval={"approved": True})
        assert storage.get_task(task["id"])["status"] == "queued"
