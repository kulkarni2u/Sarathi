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
Engine's own ``TaskContext`` in-process and folds the result back onto the
same row -- so the worker process being long-lived is what makes this
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

import logging
from typing import Any, Mapping

try:
    from src.engine import Complexity, Engine, PersistenceManager, Phase, TaskContext
except ImportError:
    from engine import Complexity, Engine, PersistenceManager, Phase, TaskContext

try:
    from ..storage import Storage
except ImportError:
    from storage import Storage

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


def run_claimed_full_engine_task(
    storage: Storage,
    task: Mapping[str, Any],
    *,
    worker_id: str,
    tasks_dir: str | None = None,
) -> dict[str, Any]:
    """Run (or resume) the Engine lifecycle for a claimed full-Engine task row.

    Always calls ``Engine.resume_task`` -- it transparently falls back to
    ``run_task`` when the loaded ``TaskContext`` has no phase results yet, so
    this one call handles both "never started" and "continuing after a
    previous poll" without the caller needing to know which.

    ``tasks_dir`` overrides where the Engine's ``PersistenceManager`` reads/
    writes ``TaskContext`` JSON (default: ``.sarathi/tasks`` relative to the
    worker process's cwd, same as every other Engine entrypoint). Mainly for
    tests; a real deployment runs the worker from the workspace root.
    """
    metadata = dict(task.get("metadata") or {})
    engine_task_id = str(metadata.get("engine_task_id") or task["id"])
    policy_pack = metadata.get("policy_pack")
    description = str(task.get("description") or task.get("title") or engine_task_id)
    complexity = _COMPLEXITY_BY_NAME.get(
        str(metadata.get("complexity", "medium")).lower(), Complexity.MEDIUM
    )

    engine = Engine(policy_pack_path=policy_pack, enforce_preflight=True)
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
        storage.update_task(
            task["id"],
            status="blocked",
            metadata={**metadata, "engine_error": "raised"},
        )
        raise

    next_status = _next_task_status(result)
    storage.update_task(
        task["id"],
        status=next_status,
        metadata={
            **metadata,
            "engine_current_phase": (
                result.current_phase.value if result.current_phase else None
            ),
            "engine_stop_reason": result.stop_reason,
        },
    )
    logger.info(
        "Full-Engine task %s (engine_task_id=%s) worker=%s -> status=%s current_phase=%s",
        task["id"],
        engine_task_id,
        worker_id,
        next_status,
        result.current_phase.value if result.current_phase else None,
    )
    return {"engine_task_id": engine_task_id, "status": next_status, "result": result}


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
