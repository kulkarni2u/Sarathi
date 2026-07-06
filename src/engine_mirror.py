"""Best-effort mirror of lifecycle-engine runs into the service SQLite DB.

The lifecycle engine (CLI / TUI / MCP) persists its own view of a task to
flat JSON via ``PersistenceManager`` (``.sarathi/tasks/*.json``). The web
cockpit (``src/service/``) only ever reads ``.sarathi/sarathi.db`` through
``src.storage.Storage``. Without a bridge, tasks started outside the web
stack are invisible to it -- a split brain.

``EngineRunRecorder`` closes that gap the same way ``src/notifications.py``
closes the outbound-notification gap: it is an optional, best-effort side
channel constructed once in ``Engine.__init__`` and invoked from the same
seam as the notifier (``Engine._log_phase``). It mirrors state, it never
drives it -- the web cockpit remains read-only with respect to engine runs.

Design rules (mirrors ``notifications.py``):

- **Best-effort**: any storage failure is logged and swallowed. A mirroring
  failure must never break or slow down a run.
- **Opt-in by existing infrastructure, not by config**: mirroring only
  activates when ``.sarathi/sarathi.db`` already exists, i.e. the service /
  web stack has been bootstrapped for this workspace at some point. Sarathi
  never creates that database on behalf of a CLI-only user.
- **Reuses the service's own vocabulary**: task statuses and lifecycle event
  types are chosen to match values the service already produces elsewhere
  (see ``src/service/scheduling.py`` and ``src/service/projections.py``) --
  no new status vocabulary is invented.
- **Self-disabling**: after a few consecutive failures (e.g. a locked or
  corrupted DB) the recorder stops trying for the rest of the process,
  rather than repeatedly failing and logging noise on every phase.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .notifications import _PHASE_STATUS_EVENTS
    from .storage import Storage, connect, run_migrations
except ImportError:
    from notifications import _PHASE_STATUS_EVENTS
    from storage import Storage, connect, run_migrations

logger = logging.getLogger("sarathi.engine_mirror")

DEFAULT_DB_PATH = ".sarathi/sarathi.db"
DB_PATH_ENV = "SARATHI_MIRROR_DB"
DISABLE_ENV = "SARATHI_NO_MIRROR"

# Stop retrying after this many consecutive storage failures.
_MAX_CONSECUTIVE_FAILURES = 3

# Engine phase-log statuses whose dotted event type (via _PHASE_STATUS_EVENTS)
# starts with "task." represent notable/terminal moments for the mirrored
# task row. Mapped onto the closest existing tasks.status value already used
# elsewhere in the service (see scheduling._task_tracking_status_from_graph
# and projections.task_queue_state) -- the engine has no native concept of
# "blocked"/"waiting_human" at the task level, so terminal states borrow the
# service's own vocabulary for the nearest equivalent meaning:
#   - paused / escalated  -> "waiting_human" (a human decision is needed)
#   - failed / cancelled / timed_out / trust_gate_abort -> "blocked"
#     (the run did not reach a successful terminal state)
_TASK_STATUS_FOR_TERMINAL_STATUS = {
    "paused": "waiting_human",
    "escalated": "waiting_human",
    "failed": "blocked",
    "cancelled": "blocked",
    "timed_out": "blocked",
    "trust_gate_abort": "blocked",
}


class EngineRunRecorder:
    """Mirrors engine task runs into the service SQLite DB, best-effort.

    Construct via ``try_create`` (never instantiate directly outside tests)
    so the "only mirror if the DB already exists" rule is always enforced.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.disabled = False
        self._failure_count = 0
        self._storage: Storage | None = None
        self._workspace_id: str | None = None
        # engine task_id -> service-side tasks.id
        self._task_ids: dict[str, str] = {}

    @classmethod
    def try_create(cls, db_path: str = DEFAULT_DB_PATH) -> "EngineRunRecorder | None":
        """Return a recorder mirroring into ``db_path``, or None when inactive.

        Mirroring is inactive when ``SARATHI_NO_MIRROR`` is set, or when the
        resolved database file does not already exist -- CLI/TUI/MCP-only
        users never get a ``.sarathi/sarathi.db`` created for them.
        """
        if os.environ.get(DISABLE_ENV):
            return None
        resolved = os.environ.get(DB_PATH_ENV) or db_path
        path = Path(resolved)
        if not path.exists():
            return None
        return cls(path)

    # -- lazy storage ------------------------------------------------------

    def _get_storage(self) -> Storage | None:
        if self.disabled:
            return None
        if self._storage is not None:
            return self._storage
        conn: sqlite3.Connection = connect(self.db_path)
        run_migrations(conn)
        self._storage = Storage(conn)
        return self._storage

    def _record_failure(self, action: str, exc: Exception) -> None:
        self._failure_count += 1
        logger.warning(
            "engine_mirror: %s failed (%d/%d consecutive failures): %s",
            action,
            self._failure_count,
            _MAX_CONSECUTIVE_FAILURES,
            exc,
        )
        if self._failure_count >= _MAX_CONSECUTIVE_FAILURES:
            self.disabled = True
            logger.warning(
                "engine_mirror: disabling for the rest of this process after %d consecutive failures",
                self._failure_count,
            )

    # -- workspace / task bootstrap -----------------------------------------

    def _ensure_workspace(self, storage: Storage) -> str:
        if self._workspace_id is not None:
            return self._workspace_id
        root_path = os.environ.get("SARATHI_WORKDIR", os.getcwd())
        for workspace in storage.list_workspaces():
            if workspace.get("root_path") == root_path:
                self._workspace_id = workspace["id"]
                return self._workspace_id
        name = Path(root_path).name or root_path
        workspace = storage.create_workspace(name=name, root_path=root_path)
        self._workspace_id = workspace["id"]
        return self._workspace_id

    def _ensure_task(self, storage: Storage, task: Any) -> str:
        service_task_id = self._task_ids.get(task.task_id)
        if service_task_id is not None:
            return service_task_id
        workspace_id = self._ensure_workspace(storage)
        row = storage.create_task(
            workspace_id=workspace_id,
            title=task.description or task.task_id,
            status="pending",
            metadata={"engine_task_id": task.task_id, "mirrored_from": "engine"},
        )
        self._task_ids[task.task_id] = row["id"]
        return row["id"]

    def _next_task_status(self, event_type: str, status: str) -> str | None:
        if event_type == "task.completed":
            return "done"
        if event_type == "phase.completed":
            return "in_progress"
        if event_type.startswith("task."):
            return _TASK_STATUS_FOR_TERMINAL_STATUS.get(status, "blocked")
        return None  # e.g. "phase.skipped" -- no task-level signal

    # -- public API ----------------------------------------------------------

    def record_phase(self, task: Any, phase: Any, status: str) -> None:
        """Mirror a phase-log transition into the service DB. Never raises."""
        if self.disabled:
            return
        try:
            self._record_phase(task, phase, status)
        except Exception as exc:  # best-effort by contract: never break a run
            self._record_failure("record_phase", exc)
            return
        self._failure_count = 0

    def _record_phase(self, task: Any, phase: Any, status: str) -> None:
        event_type = _PHASE_STATUS_EVENTS.get(status)
        if event_type is None:
            return
        storage = self._get_storage()
        if storage is None:
            return
        is_final_phase = getattr(phase, "name", None) == "LEARN"
        if is_final_phase and status == "completed":
            event_type = "task.completed"
        service_task_id = self._ensure_task(storage, task)
        phase_label = getattr(phase, "value", str(phase))
        storage.create_lifecycle_event(
            workspace_id=self._workspace_id,
            task_id=service_task_id,
            event_type=event_type,
            payload={
                "phase": phase_label,
                "status": status,
                "engine_task_id": task.task_id,
            },
        )
        next_status = self._next_task_status(event_type, status)
        if next_status is not None:
            storage.update_task(service_task_id, status=next_status)
