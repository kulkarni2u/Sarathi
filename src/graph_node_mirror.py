"""Best-effort mirror of graph-node execution into the service SQLite DB.

``TaskGraphExecutor`` (``src/runtime/graph_executor.py``) dispatches FANOUT/
JUDGE/SYNTHESIZE nodes through an in-process ``ThreadPoolExecutor`` batch and
only ever applies results back onto the in-memory graph -- nothing about an
individual node (running vs. completed, which provider session it used) is
visible outside that one Python call frame. ``GraphNodeRecorder`` closes that
gap the same way ``engine_mirror.EngineRunRecorder`` closes the task-run gap:
an optional, best-effort side channel that makes nodes addressable via
``.sarathi/sarathi.db`` (``sarathi graph status`` / ``sarathi graph message``)
without changing anything about how the graph itself executes.

Design rules (mirrors ``engine_mirror.py`` / ``proposal_sync.py``):

- **Best-effort**: any storage failure is logged and swallowed. A mirroring
  failure must never break or slow down a run.
- **Opt-in by existing infrastructure, not by config**: mirroring only
  activates when ``.sarathi/sarathi.db`` already exists, i.e. the service /
  web stack has been bootstrapped for this workspace at some point.
- **Self-disabling**: after a few consecutive failures the recorder stops
  trying for the rest of the process, rather than repeatedly failing.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .storage import Storage, connect, run_migrations
except ImportError:
    from storage import Storage, connect, run_migrations

logger = logging.getLogger("sarathi.graph_node_mirror")

DEFAULT_DB_PATH = ".sarathi/sarathi.db"
DB_PATH_ENV = "SARATHI_MIRROR_DB"
DISABLE_ENV = "SARATHI_NO_MIRROR"

_MAX_CONSECUTIVE_FAILURES = 3


class GraphNodeRecorder:
    """Mirrors graph-node status transitions into the service SQLite DB, best-effort.

    Construct via ``try_create`` (never instantiate directly outside tests) so
    the "only mirror if the DB already exists" rule is always enforced.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.disabled = False
        self._failure_count = 0
        self._storage: Storage | None = None
        self._workspace_id: str | None = None

    @classmethod
    def try_create(cls, db_path: str = DEFAULT_DB_PATH) -> "GraphNodeRecorder | None":
        if os.environ.get(DISABLE_ENV):
            return None
        resolved = os.environ.get(DB_PATH_ENV) or db_path
        path = Path(resolved)
        if not path.exists():
            return None
        return cls(path)

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
            "graph_node_mirror: %s failed (%d/%d consecutive failures): %s",
            action,
            self._failure_count,
            _MAX_CONSECUTIVE_FAILURES,
            exc,
        )
        if self._failure_count >= _MAX_CONSECUTIVE_FAILURES:
            self.disabled = True
            logger.warning(
                "graph_node_mirror: disabling for the rest of this process after %d consecutive failures",
                self._failure_count,
            )

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

    # -- public API ----------------------------------------------------------

    def record(
        self,
        *,
        task_id: str,
        node_id: str,
        node_type: str,
        status: str,
        provider: str | None = None,
        session_artifact_key: str | None = None,
        session_artifact_value: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        """Upsert one graph node's status. Never raises."""
        if self.disabled:
            return
        try:
            storage = self._get_storage()
            if storage is None:
                return
            workspace_id = self._ensure_workspace(storage)
            storage.upsert_graph_node(
                workspace_id=workspace_id,
                task_id=task_id,
                node_id=node_id,
                node_type=node_type,
                status=status,
                provider=provider,
                session_artifact_key=session_artifact_key,
                session_artifact_value=session_artifact_value,
                started_at=started_at,
                completed_at=completed_at,
                last_error=last_error,
            )
        except Exception as exc:  # best-effort by contract: never break a run
            self._record_failure("record", exc)
            return
        self._failure_count = 0
