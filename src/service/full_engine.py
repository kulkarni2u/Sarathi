"""Drive a full 12-phase Engine lifecycle from inside the resident worker.

The subtask work-queue (``providers._dispatch_subtask``, driven by
``worker.run_worker``) dispatches one provider CLI call per subtask -- it
never drives ``Engine.run_task``. A task submitted via ``sarathi run
--background`` needs the opposite: one resident process that owns the whole
ROUTE-through-LEARN lifecycle for one task and keeps going across worker
polls until it's actually done.

This module is the bridge: a ``tasks`` row flagged
``metadata.execution_mode == "full_engine"`` (see
``Storage.claim_full_engine_task``) is claimed by ``run_worker`` like any
other item, but instead of a provider dispatch it runs (or resumes) the
Engine's own ``TaskContext`` in an isolated child process and folds the result
back onto the same row -- so each job is bound to its registered workspace.
"resident": the task keeps making progress across polls without any client
staying attached, and the JSON-file ``TaskContext`` is what actually
survives a restart (see ``TaskContext.provider_session_ids``).

Deliberately not unified with ``EngineRunRecorder``'s own best-effort mirror
(``src/engine_mirror.py``), which -- being generic across every Engine
entrypoint -- will still create its own separate ``tasks`` row for the same
engine task id the first time it observes a phase transition. That's
accepted duplication, not a bug: this module owns updating the row it
claimed; EngineRunRecorder's mirror is unrelated best-effort observability
for any Engine run, worker-driven or not.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any, Mapping
from pathlib import Path

try:
    from src.engine import Complexity, Engine, PersistenceManager, TaskContext
except ImportError:
    from engine import Complexity, Engine, PersistenceManager, TaskContext

try:
    from ..storage import Storage, connect
except ImportError:
    from storage import Storage, connect

logger = logging.getLogger("sarathi.service.full_engine")

_COMPLEXITY_BY_NAME = {
    "low": Complexity.LOW,
    "medium": Complexity.MEDIUM,
    "high": Complexity.HIGH,
}

# Mirrors EngineRunRecorder's own terminal-status vocabulary
# (src/engine_mirror.py:_TASK_STATUS_FOR_TERMINAL_STATUS) so a full-Engine
# task lands in the same tasks.status values the rest of the service already
# understands.
_TASK_STATUS_FOR_STOP_REASON = {
    "approval_required": "waiting_human",
    "rejected": "waiting_human",
    "cancelled": "blocked",
    "timeout": "blocked",
}

# Bounds how long the approval subprocess (Engine construction + one
# record_approval call, no provider dispatch) may run before the service
# request gives up on it -- see _apply_approval_in_workspace_subprocess.
_APPROVAL_SUBPROCESS_TIMEOUT_SECONDS = 30


def run_claimed_full_engine_task(
    storage: Storage,
    task: Mapping[str, Any],
    *,
    worker_id: str,
    tasks_dir: str | None = None,
    _in_child: bool = False,
    expected_claim_generation: str | None = None,
) -> dict[str, Any]:
    """Run (or resume) the Engine lifecycle for a claimed full-Engine task row.

    Always calls ``Engine.resume_task`` -- it transparently falls back to
    ``run_task`` when the loaded ``TaskContext`` has no phase results yet, so
    this one call handles both "never started" and "continuing after a
    previous poll" without the caller needing to know which.

    ``tasks_dir`` overrides where the Engine's ``PersistenceManager`` reads/
    writes ``TaskContext`` JSON. In production the child process starts in the
    registered workspace, so native persistence resolves there.

    ``expected_claim_generation`` is set only for the ``_in_child`` call: the
    subprocess must verify it still owns the ORIGINAL claim (status/owner/
    generation captured by the parent at spawn time) before constructing
    ``Engine`` -- a stale, slow-to-start child must never run the engine or
    mutate state after the same worker has since re-claimed the row under a
    replacement generation (see ``_run_in_workspace_subprocess``).
    """
    metadata = dict(task.get("metadata") or {})
    claim_generation = str(metadata.get("claim_generation") or "")
    engine_task_id = str(metadata.get("engine_task_id") or task["id"])
    if not _in_child:
        try:
            workspace_root = _registered_workspace_root(storage, task)
        except RuntimeError:
            # Validation failed before any subprocess/bookkeeping ran -- the
            # claimed row would otherwise be stuck "running" forever (worker
            # only counts the failure, it never touches storage). Conditioned
            # on the ORIGINAL claim so a replacement claim is never clobbered.
            storage.update_full_engine_claimed_task(
                task["id"], worker_id=worker_id, status="blocked",
                claim_generation=claim_generation,
                metadata={**metadata, "engine_error": "workspace_unavailable"},
            )
            raise
        return _run_in_workspace_subprocess(
            storage, task, worker_id=worker_id, tasks_dir=tasks_dir, workspace_root=workspace_root
        )
    workspace_root = _registered_workspace_root(storage, task)
    if expected_claim_generation is not None and (
        task.get("status") != "running"
        or metadata.get("claimed_by") != worker_id
        or claim_generation != expected_claim_generation
    ):
        raise RuntimeError(
            f"Full-Engine claim for task {task['id']} no longer matches "
            f"worker={worker_id} generation={expected_claim_generation}; refusing to execute"
        )
    policy_pack = metadata.get("policy_pack")
    description = str(task.get("description") or task.get("title") or engine_task_id)
    complexity = _COMPLEXITY_BY_NAME.get(
        str(metadata.get("complexity", "medium")).lower(), Complexity.MEDIUM
    )

    engine = Engine(policy_pack_path=policy_pack, enforce_preflight=True)
    engine.workspace_root = str(workspace_root)
    if hasattr(engine.dispatcher, "workspace_root"):
        engine.dispatcher.workspace_root = str(workspace_root)
    if tasks_dir is not None:
        engine.persistence = PersistenceManager(tasks_dir)
    # engine.persistence may be an NCPPersistenceAdapter instead of a plain
    # PersistenceManager (see Engine.__init__) -- both implement
    # load_task/save_task, so no narrower annotation is needed here.
    task_context = engine.persistence.load_task(engine_task_id)
    if task_context is None:
        task_context = TaskContext(
            task_id=engine_task_id, description=description, complexity=complexity
        )

    try:
        result = engine.resume_task(task_context)
    except Exception:
        logger.exception(
            "Full-Engine task %s (engine_task_id=%s) raised", task["id"], engine_task_id
        )
        storage.update_full_engine_claimed_task(
            task["id"], worker_id=worker_id, status="blocked",
            claim_generation=claim_generation,
            metadata={**metadata, "engine_error": "raised"},
        )
        raise

    next_status = _next_task_status(result)
    updated = storage.update_full_engine_claimed_task(
        task["id"], worker_id=worker_id, status=next_status,
        claim_generation=claim_generation,
        metadata={
            **metadata,
            "engine_current_phase": result.current_phase.value if result.current_phase else None,
            "engine_stop_reason": result.stop_reason,
        },
    )
    if not updated:
        raise RuntimeError(f"Full-Engine claim lost for task {task['id']}")
    logger.info(
        "Full-Engine task %s (engine_task_id=%s) worker=%s -> status=%s current_phase=%s",
        task["id"],
        engine_task_id,
        worker_id,
        next_status,
        result.current_phase.value if result.current_phase else None,
    )
    return {"engine_task_id": engine_task_id, "status": next_status, "result": result}


def _registered_workspace_root(storage: Storage, task: Mapping[str, Any]) -> Path:
    """Resolve and validate the task's registered workspace before execution."""
    workspace_id = task.get("workspace_id")
    workspace = storage.get_workspace(str(workspace_id)) if workspace_id else None
    raw_root = workspace.get("root_path") if workspace else None
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise RuntimeError(f"Full-Engine task {task.get('id')} has no registered workspace")
    root = Path(raw_root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"Full-Engine task {task.get('id')} workspace is unavailable: {root}")
    return root


def resume_full_engine_task(
    storage: Storage,
    task: Mapping[str, Any],
    approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an approval decision to persisted Engine state and requeue it.

    Reserves the awaiting-approval transition atomically (``reserve_full_engine_approval``)
    BEFORE any persisted context or worker-claim field is touched, so two
    concurrent/duplicate approval calls for the same task can't both load the
    paused context and race to write conflicting results (one overwriting a
    newly-claimed 'running' row back to 'queued', permitting duplicate
    execution). Only the caller that wins the reservation proceeds; the loser
    gets an immediate conflict error with nothing mutated.

    The actual ``Engine``/persistence work happens in a child process scoped
    to the registered workspace (see ``_apply_approval_in_workspace_subprocess``)
    -- constructing ``Engine`` here in the service process's own cwd would
    resolve a relative ``policy_pack`` against the wrong directory and would
    force plain JSON persistence even when the workspace has NCP configured.
    """
    if task.get("status") == "running":
        raise RuntimeError("Cannot resume a running full-Engine task")
    if task.get("status") in {"done", "completed"}:
        raise RuntimeError("Cannot resume a completed full-Engine task")
    if approval is None:
        raise RuntimeError(f"Full-Engine task {task['id']} requires explicit approval")
    if not isinstance(approval.get("approved"), bool):
        raise RuntimeError("Full-Engine approval must include boolean approved")
    reserved = storage.reserve_full_engine_approval(task["id"])
    if reserved is None:
        raise RuntimeError(
            f"Full-Engine task {task['id']} is not awaiting approval, "
            "or another approval for it is already in progress"
        )
    reservation = str(reserved["metadata"]["approval_reservation"])
    try:
        root = _registered_workspace_root(storage, reserved)
        _apply_approval_in_workspace_subprocess(
            storage, reserved, approval=approval, workspace_root=root, reservation=reservation,
        )
    except Exception:
        storage.release_full_engine_approval_reservation(task["id"], reservation=reservation)
        raise
    updated = storage.get_task(task["id"])
    if updated is None:
        raise RuntimeError(f"Full-Engine task {task['id']} vanished during approval")
    return updated


def _apply_approval_in_workspace_subprocess(
    storage: Storage,
    task: Mapping[str, Any],
    *,
    approval: Mapping[str, Any],
    workspace_root: Path,
    reservation: str,
) -> None:
    """Record an approval decision in a process scoped to the registered workspace.

    Bounded by ``_APPROVAL_SUBPROCESS_TIMEOUT_SECONDS``: ``record_approval``
    does no provider dispatch, so a stalled child (wedged persistence, hung
    NCP call) is killed rather than allowed to hold the calling API request
    forever. On any failure the reservation is released by the caller
    (``resume_full_engine_task``) so a retry isn't permanently blocked.
    """
    command = [
        sys.executable,
        "-m",
        "src.service.full_engine",
        "--approve",
        "--db",
        str(_database_path(storage)),
        "--task-id",
        str(task["id"]),
    ]
    env = os.environ.copy()
    env["SARATHI_WORKDIR"] = str(workspace_root)
    project_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    payload = json.dumps({"approval": dict(approval), "reservation": reservation})
    try:
        proc = subprocess.run(
            command,
            cwd=str(workspace_root),
            env=env,
            text=True,
            input=payload,
            capture_output=True,
            timeout=_APPROVAL_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Full-Engine approval subprocess timed out for task %s", task["id"])
        raise RuntimeError(f"Full-Engine approval timed out for task {task['id']}") from exc
    if proc.returncode != 0:
        # Never surface raw child stderr/stdout to the API caller -- an
        # Engine/persistence traceback could echo policy-pack paths or, in
        # principle, provider config. Log the detail server-side only.
        logger.error(
            "Full-Engine approval subprocess failed for task %s: %s",
            task["id"],
            (proc.stderr or proc.stdout).strip()[-2000:],
        )
        raise RuntimeError(f"Full-Engine approval failed for task {task['id']}")


def _apply_approval_in_child(
    storage: Storage,
    task: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    reservation: str,
) -> dict[str, Any]:
    """Load persisted Engine state and record the approval decision.

    Must run with cwd already set to the task's registered workspace root
    (see ``_apply_approval_in_workspace_subprocess``) so that a relative
    ``policy_pack`` and NCP auto-detection resolve against the workspace, not
    whatever process happened to call ``resume_full_engine_task``. The final
    write goes through ``resolve_full_engine_approval``, conditioned on this
    exact reservation token, instead of an unconditional ``update_task`` --
    that unconditional write was the bug: it could clobber a worker's fresh
    'running' claim (which owns entirely different metadata) back to
    'queued', letting the task run twice.
    """
    metadata = dict(task.get("metadata") or {})
    metadata.pop("approval_reservation", None)
    engine_task_id = str(metadata.get("engine_task_id") or task["id"])
    approval_engine = Engine(policy_pack_path=metadata.get("policy_pack"), enforce_preflight=True)
    context = approval_engine.persistence.load_task(engine_task_id)
    if context is None:
        raise RuntimeError(f"Full-Engine task {task['id']} approval state is missing")
    if not context.phase_results or not context.phase_results[-1].artifacts.get("pause_execution"):
        raise RuntimeError(f"Full-Engine task {task['id']} is not awaiting approval")
    last = context.phase_results[-1]
    if not last.evidence.get("human_attention_required"):
        raise RuntimeError(f"Full-Engine task {task['id']} is not awaiting approval")
    context = approval_engine.record_approval(
        context,
        approved_by=str(approval.get("approved_by") or "service"),
        approve=bool(approval["approved"]),
        note=approval.get("note"),
    )
    if approval["approved"]:
        metadata.pop("claimed_by", None)
        metadata.pop("claimed_at", None)
        metadata.pop("heartbeat_at", None)
        next_status = "queued"
    else:
        metadata["engine_stop_reason"] = "rejected"
        next_status = "waiting_human"
    resolved = storage.resolve_full_engine_approval(
        task["id"], reservation=reservation, status=next_status, metadata=metadata
    )
    if not resolved:
        raise RuntimeError(f"Full-Engine approval reservation lost for task {task['id']}")
    updated = storage.get_task(task["id"])
    assert updated is not None
    return updated


def _database_path(storage: Storage) -> Path:
    row = storage.conn.execute("PRAGMA database_list").fetchone()
    if row is None or not row[2]:
        raise RuntimeError("Full-Engine worker database path is unavailable")
    return Path(row[2]).resolve()


def _run_in_workspace_subprocess(
    storage: Storage,
    task: Mapping[str, Any],
    *,
    worker_id: str,
    tasks_dir: str | None,
    workspace_root: Path,
) -> dict[str, Any]:
    """Run one Engine call in a process scoped to the registered workspace.

    Passes the ORIGINAL claim generation (captured from ``task`` at the
    moment this call was made, i.e. what the worker just claimed) down to the
    child via ``--claim-generation``, so a slow-to-start child verifies it
    still owns that exact claim before touching Engine/persistence -- see
    ``run_claimed_full_engine_task``'s ``expected_claim_generation`` check.
    """
    claim_generation = str((task.get("metadata") or {}).get("claim_generation") or "")
    command = [
        sys.executable,
        "-m",
        "src.service.full_engine",
        "--child",
        "--db",
        str(_database_path(storage)),
        "--task-id",
        str(task["id"]),
        "--worker-id",
        worker_id,
        "--claim-generation",
        claim_generation,
    ]
    if tasks_dir is not None:
        command.extend(["--tasks-dir", tasks_dir])
    env = os.environ.copy()
    env["SARATHI_WORKDIR"] = str(workspace_root)
    project_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        command, cwd=str(workspace_root), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout = stderr = ""
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=5)
            break
        except subprocess.TimeoutExpired:
            if not storage.heartbeat_full_engine_task(task["id"], worker_id=worker_id, claim_generation=claim_generation):
                proc.terminate()
                stdout, stderr = proc.communicate()
                raise RuntimeError(f"Full-Engine claim lost for task {task['id']}")
    if proc.returncode != 0:
        storage.update_full_engine_claimed_task(
            task["id"], worker_id=worker_id, status="blocked",
            claim_generation=claim_generation,
            metadata={**dict(task.get("metadata") or {}), "engine_error": "subprocess_failed"},
        )
        detail = (stderr or stdout).strip().splitlines()[-1:] or ["unknown error"]
        raise RuntimeError(f"Full-Engine subprocess failed for task {task['id']}: {detail[0]}")
    updated = storage.get_task(task["id"])
    status = updated["status"] if updated is not None else "blocked"
    return {"engine_task_id": str((task.get("metadata") or {}).get("engine_task_id") or task["id"]), "status": status, "result": None}


def _child_main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--db", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--tasks-dir", default=None)
    parser.add_argument("--claim-generation", default=None)
    args = parser.parse_args(argv)
    with connect(args.db) as conn:
        storage = Storage(conn)
        task = storage.get_task(args.task_id)
        if task is None:
            return 2
        try:
            run_claimed_full_engine_task(
                storage, task, worker_id=args.worker_id, tasks_dir=args.tasks_dir,
                _in_child=True, expected_claim_generation=args.claim_generation,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 3
    return 0


def _approve_child_main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--db", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    payload = json.loads(sys.stdin.read())
    approval = payload["approval"]
    reservation = payload["reservation"]
    with connect(args.db) as conn:
        storage = Storage(conn)
        task = storage.get_task(args.task_id)
        if task is None:
            print(f"Full-Engine task {args.task_id} not found", file=sys.stderr)
            return 2
        try:
            _apply_approval_in_child(storage, task, approval, reservation=reservation)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    return 0


def _next_task_status(result: TaskContext) -> str:
    if result.stop_reason:
        return _TASK_STATUS_FOR_STOP_REASON.get(result.stop_reason, "blocked")
    if result.current_phase is None:
        last = result.phase_results[-1] if result.phase_results else None
        if last is not None and last.outcome == "fail":
            return "blocked"
        return "done"
    # Returned early with no stop_reason and a phase still pending (e.g. BUILD
    # hit its graph step limit) -- there's more work to do but nothing failed;
    # requeue so the next worker poll resumes it via resume_task.
    return "queued"


if __name__ == "__main__":
    if "--approve" in sys.argv[1:]:
        raise SystemExit(_approve_child_main())
    raise SystemExit(_child_main())
