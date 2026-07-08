"""Best-effort mirror of file-based policy-proposal decisions into the
service SQLite DB.

``evolve.ProposalReviewStore`` is the human review/apply workflow used by the
CLI (``sarathi proposals``), the TUI (``ProposalsScreen``), and the MCP
server (``accept_proposal``/``reject_proposal``). It has always persisted its
decisions as ``.sarathi-proposals/<proposal-id>.json`` files under the policy
pack -- ``src/policy/compiler.py``'s ``_load_learning_feedback`` reads that
directory directly to feed accepted/rejected proposals back into policy
compilation, and must keep doing so unmodified.

The web cockpit (``src/service/``) reviews the *same* proposals through
``src/service/proposals.py``, which already calls straight into
``ProposalReviewStore.accept``/``reject`` -- so the JSON files were never
actually a second copy of the data. The real split-brain was narrower: a
decision made from the CLI/TUI/MCP left no trace in ``sarathi.db``, so the
web Proposals view's activity feed (lifecycle events) never learned about it,
and there was no durable, queryable row for it either.

``ProposalSync`` closes that gap the same way ``src/engine_mirror.py``
closes it for engine task runs: it is an optional, best-effort side channel
constructed once per ``ProposalReviewStore`` and invoked from
``accept``/``reject``. It mirrors decisions, it never drives them -- the
service DB stays a read-visible mirror plus a queryable
``proposal_decisions`` table; the JSON files remain the on-disk source
``_load_learning_feedback`` and ``ProposalReviewStore`` itself read from.

Design rules (mirrors ``engine_mirror.py``):

- **Best-effort**: any storage failure is logged and swallowed. A mirroring
  failure must never break an accept/reject flow.
- **Opt-in by existing infrastructure, not by config**: mirroring only
  activates when ``<workspace_root>/.sarathi/sarathi.db`` already exists,
  i.e. this workspace has been bootstrapped for the service / web stack at
  some point. A CLI-only user never gets that database created for them.
  ``SARATHI_NO_MIRROR`` disables it outright; ``SARATHI_MIRROR_DB`` (the same
  env var ``engine_mirror`` honors) overrides the resolved path, mainly for
  tests.
- **Self-disabling**: after a few consecutive failures (e.g. a locked or
  corrupted DB) the sync stops trying for the lifetime of the
  ``ProposalReviewStore`` instance, rather than repeatedly failing.
- **Idempotent import**: on activation, any ``.sarathi-proposals/*.json``
  decision not yet present in the ``proposal_decisions`` table is imported,
  keyed by proposal id. Because the import (and every subsequent write) goes
  through the same upsert keyed on ``(workspace_id, proposal_id)``, reopening
  the store -- once per CLI invocation, in practice -- never duplicates rows.
- **Callers that already own a ``Storage`` handle opt out**: ``src/service/
  proposals.py`` already knows the exact workspace and already emits its own
  ``proposal.accepted``/``proposal.rejected`` lifecycle events using its own
  (definitely correct) ``Storage`` connection. It constructs
  ``ProposalReviewStore`` with ``mirror=False`` and records the SQLite row
  itself via ``Storage.upsert_proposal_decision`` next to that existing
  event, so a single accept/reject action never produces two events.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    from .storage import Storage, connect, run_migrations
except ImportError:
    from storage import Storage, connect, run_migrations

logger = logging.getLogger("sarathi.proposal_sync")

DEFAULT_DB_RELATIVE_PATH = Path(".sarathi") / "sarathi.db"
DB_PATH_ENV = "SARATHI_MIRROR_DB"
DISABLE_ENV = "SARATHI_NO_MIRROR"

# Stop retrying after this many consecutive storage failures.
_MAX_CONSECUTIVE_FAILURES = 3


class ProposalSync:
    """Mirrors proposal accept/reject decisions into the service SQLite DB.

    Construct via ``try_create`` (never instantiate directly outside tests)
    so the "only mirror if the DB already exists" rule is always enforced.
    """

    def __init__(self, db_path: Path, workspace_root: Path, review_dir: Path):
        self.db_path = db_path
        self.workspace_root = workspace_root
        self.review_dir = review_dir
        self.disabled = False
        self._failure_count = 0
        self._storage: Storage | None = None
        self._workspace_id: str | None = None

    @classmethod
    def try_create(cls, workspace_root: Path, review_dir: Path) -> "ProposalSync | None":
        """Return a sync mirroring ``review_dir`` into the workspace's DB, or None.

        Mirroring is inactive when ``SARATHI_NO_MIRROR`` is set, or when the
        resolved database file does not already exist -- CLI/TUI/MCP-only
        users never get a ``.sarathi/sarathi.db`` created for them.
        """
        if os.environ.get(DISABLE_ENV):
            return None
        override = os.environ.get(DB_PATH_ENV)
        db_path = Path(override) if override else workspace_root / DEFAULT_DB_RELATIVE_PATH
        if not db_path.exists():
            return None
        sync = cls(db_path, workspace_root, review_dir)
        sync._import_existing_json()
        return sync

    # -- lazy storage ------------------------------------------------------

    def _get_storage(self) -> Storage | None:
        if self.disabled:
            return None
        if self._storage is not None:
            return self._storage
        try:
            conn = connect(self.db_path)
            run_migrations(conn)
            self._storage = Storage(conn)
        except Exception as exc:  # best-effort by contract
            self._record_failure("connect", exc)
            return None
        return self._storage

    def _record_failure(self, action: str, exc: Exception) -> None:
        self._failure_count += 1
        logger.warning(
            "proposal_sync: %s failed (%d/%d consecutive failures): %s",
            action,
            self._failure_count,
            _MAX_CONSECUTIVE_FAILURES,
            exc,
        )
        if self._failure_count >= _MAX_CONSECUTIVE_FAILURES:
            self.disabled = True
            logger.warning(
                "proposal_sync: disabling for the rest of this store's lifetime "
                "after %d consecutive failures",
                self._failure_count,
            )

    # -- workspace bootstrap -------------------------------------------------

    def _ensure_workspace(self, storage: Storage) -> str:
        if self._workspace_id is not None:
            return self._workspace_id
        root_path = str(self.workspace_root)
        for workspace in storage.list_workspaces():
            if workspace.get("root_path") == root_path:
                self._workspace_id = workspace["id"]
                return self._workspace_id
        name = self.workspace_root.name or root_path
        workspace = storage.create_workspace(name=name, root_path=root_path)
        self._workspace_id = workspace["id"]
        return self._workspace_id

    # -- public API ----------------------------------------------------------

    def record_decision(self, decision: dict[str, Any]) -> None:
        """Mirror an accept/reject decision. Never raises."""
        if self.disabled:
            return
        try:
            self._record_decision(decision)
        except Exception as exc:  # best-effort by contract: never break a review flow
            self._record_failure("record_decision", exc)
            return
        self._failure_count = 0

    def _record_decision(self, decision: dict[str, Any]) -> None:
        storage = self._get_storage()
        if storage is None:
            return
        workspace_id = self._ensure_workspace(storage)
        proposal_id = str(decision.get("id") or "")
        if not proposal_id:
            return
        status = str(decision.get("status") or "")
        storage.upsert_proposal_decision(
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            status=status,
            policy_file=decision.get("policy_file"),
            title=decision.get("title"),
            source=decision.get("source"),
            reason=decision.get("reason"),
            payload=decision,
            reviewed_at=decision.get("reviewed_at"),
        )
        event_type = "proposal.accepted" if status == "accepted" else "proposal.rejected"
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            event_type=event_type,
            payload={
                "proposal_id": proposal_id,
                "title": decision.get("title"),
                "policy_file": decision.get("policy_file"),
                "reason": decision.get("reason"),
            },
        )

    # -- one-time (but idempotent) JSON -> SQLite import ---------------------

    def _import_existing_json(self) -> None:
        if self.disabled:
            return
        try:
            self._do_import_existing_json()
        except Exception as exc:  # best-effort by contract
            self._record_failure("import_existing_json", exc)

    def _do_import_existing_json(self) -> None:
        storage = self._get_storage()
        if storage is None or not self.review_dir.exists():
            return
        workspace_id = self._ensure_workspace(storage)
        existing_ids = {
            row["proposal_id"] for row in storage.list_proposal_decisions(workspace_id)
        }
        for path in sorted(self.review_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            proposal_id = data.get("id")
            if not isinstance(proposal_id, str) or not proposal_id or proposal_id in existing_ids:
                continue
            storage.upsert_proposal_decision(
                workspace_id=workspace_id,
                proposal_id=proposal_id,
                status=str(data.get("status") or ""),
                policy_file=data.get("policy_file"),
                title=data.get("title"),
                source=data.get("source"),
                reason=data.get("reason"),
                payload=data,
                reviewed_at=data.get("reviewed_at"),
            )
            existing_ids.add(proposal_id)
