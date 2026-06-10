"""Crash-safe write-ahead journal for provider dispatches.

Sarathi dispatches mutate a workspace (via provider CLIs). If the orchestrator
process dies mid-dispatch, a resumed task has no record that the dispatch was
ever attempted, let alone whether it touched the workspace.

This module adds a small append-only JSONL journal: an "intent" record is
written (and fsynced) *before* each dispatch, and a "complete" record is
written after. On resume, any intent without a matching complete record is an
"in-flight" dispatch whose fate is unknown — :meth:`DispatchJournal.reconcile`
compares the workspace snapshot taken at intent time against the current
workspace to determine whether anything actually changed.

Design principle (matching ``workspace_evidence``): never fabricate signals,
never raise. All file IO is defensive — corrupt or missing data degrades to
"no journal entries" rather than crashing the engine.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .workspace_evidence import measure_workspace_delta, snapshot_workspace
except ImportError:
    from workspace_evidence import measure_workspace_delta, snapshot_workspace


logger = logging.getLogger("sarathi.dispatch_journal")

# Compaction: when the journal file exceeds this size on init, rewrite it
# keeping only the entries for the most recent _COMPACT_KEEP_JOURNAL_IDS
# distinct journal_ids.
_COMPACT_THRESHOLD_BYTES = 5 * 1024 * 1024
_COMPACT_KEEP_JOURNAL_IDS = 200


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256((prompt or "").encode("utf-8", errors="replace")).hexdigest()


class DispatchJournal:
    """Append-only JSONL write-ahead journal for dispatch intents/completions.

    Persists to ``<base_dir>/dispatch_journal.jsonl``. The file handle is
    kept open only for the duration of each write (open-append-close) so
    multiple processes can safely interleave writes.
    """

    def __init__(self, base_dir: str | os.PathLike[str]):
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / "dispatch_journal.jsonl"
        self._maybe_compact()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def begin(
        self,
        *,
        task_id: str,
        phase: str,
        provider: str | None,
        prompt: str,
        workspace_root: str,
    ) -> str:
        """Record dispatch intent before it runs. Returns the journal_id.

        Never raises — on any failure, logs and returns a journal_id anyway
        so callers always have something to pass to :meth:`complete`.
        """
        journal_id = uuid.uuid4().hex[:12]
        try:
            snapshot = snapshot_workspace(workspace_root)
        except Exception:
            logger.exception("dispatch_journal: snapshot_workspace failed for %s", workspace_root)
            snapshot = {"measured": False, "reason": "snapshot_error"}

        record = {
            "type": "intent",
            "journal_id": journal_id,
            "ts": _utc_now(),
            "task_id": task_id,
            "phase": phase,
            "provider": provider,
            "prompt_sha256": _hash_prompt(prompt),
            "workspace_snapshot": snapshot,
        }
        self._append(record, fsync=True)
        return journal_id

    def complete(self, journal_id: str, *, success: bool, error: str | None = None) -> None:
        """Record dispatch completion. Never raises."""
        record = {
            "type": "complete",
            "journal_id": journal_id,
            "ts": _utc_now(),
            "success": bool(success),
            "error": error,
        }
        self._append(record, fsync=False)

    def mark_reconciled(self, journal_id: str) -> None:
        """Record that ``journal_id`` has been reconciled, so it isn't re-reported."""
        record = {
            "type": "reconciled",
            "journal_id": journal_id,
            "ts": _utc_now(),
        }
        self._append(record, fsync=False)

    def _append(self, record: dict[str, Any], *, fsync: bool) -> None:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record))
                f.write("\n")
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())
        except Exception:
            logger.exception("dispatch_journal: failed to append %s record", record.get("type"))

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _read_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return records
        except OSError:
            logger.exception("dispatch_journal: failed to read %s", self.path)
            return records

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                logger.warning("dispatch_journal: skipping corrupt line in %s", self.path)
                continue
            if not isinstance(record, dict) or "journal_id" not in record or "type" not in record:
                continue
            records.append(record)
        return records

    def incomplete(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """Return intent records with no matching complete/reconciled record.

        Optionally filtered to a single ``task_id``.
        """
        intents: dict[str, dict[str, Any]] = {}
        resolved: set[str] = set()

        for record in self._read_records():
            journal_id = record.get("journal_id")
            record_type = record.get("type")
            if record_type == "intent":
                intents[journal_id] = record
            elif record_type in ("complete", "reconciled"):
                resolved.add(journal_id)

        results = [
            record for journal_id, record in intents.items() if journal_id not in resolved
        ]
        if task_id is not None:
            results = [record for record in results if record.get("task_id") == task_id]
        return results

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self, entry: dict[str, Any], workspace_root: str) -> dict[str, Any]:
        """Compare the workspace state recorded in ``entry`` to the current state.

        Returns a dict with ``journal_id``, ``task_id``, ``phase``,
        ``provider``, ``workspace_delta`` (from
        :func:`measure_workspace_delta`), and ``safe_to_rerun`` — True only
        when the delta is measured and shows zero changes.

        Never raises.
        """
        try:
            current = snapshot_workspace(workspace_root)
        except Exception:
            logger.exception("dispatch_journal: snapshot_workspace failed for %s", workspace_root)
            current = {"measured": False, "reason": "snapshot_error"}

        entry_snapshot = entry.get("workspace_snapshot")
        if not isinstance(entry_snapshot, dict):
            entry_snapshot = {"measured": False, "reason": "missing_snapshot"}

        delta = measure_workspace_delta(entry_snapshot, current)
        safe_to_rerun = bool(delta.get("measured") and delta.get("change_count") == 0)

        return {
            "journal_id": entry.get("journal_id"),
            "task_id": entry.get("task_id"),
            "phase": entry.get("phase"),
            "provider": entry.get("provider"),
            "workspace_delta": delta,
            "safe_to_rerun": safe_to_rerun,
        }

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def _maybe_compact(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= _COMPACT_THRESHOLD_BYTES:
            return
        self._compact()

    def _compact(self) -> None:
        """Rewrite the journal keeping only the most recent N journal_ids.

        Atomic: writes to a temp file then ``os.replace``. Never raises.
        """
        try:
            records = self._read_records()
            if not records:
                return

            # Order of first appearance determines recency (file is append-only).
            seen_order: list[str] = []
            seen: set[str] = set()
            for record in records:
                journal_id = record.get("journal_id")
                if journal_id not in seen:
                    seen.add(journal_id)
                    seen_order.append(journal_id)

            keep_ids = set(seen_order[-_COMPACT_KEEP_JOURNAL_IDS:])
            kept_records = [r for r in records if r.get("journal_id") in keep_ids]

            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                for record in kept_records:
                    f.write(json.dumps(record))
                    f.write("\n")
            os.replace(tmp_path, self.path)
        except Exception:
            logger.exception("dispatch_journal: compaction failed for %s", self.path)
