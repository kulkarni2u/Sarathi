"""Work-queue worker: claim and dispatch ready subtasks from the shared DB.

Multiple instances of ``run_worker`` (in separate processes, possibly on
separate machines sharing the SQLite database and workspace) can run
concurrently. Each worker:

1. Requeues any subtasks whose claim lease has expired (crashed workers).
2. Atomically claims the oldest unclaimed, ready-to-execute subtask.
3. Dispatches it through the canonical ``_dispatch_subtask`` path.
4. Records success/failure and clears the claim.

The "ready to execute" status is ``in_progress`` -- this is the status
``_schedule_ready_subtasks`` assigns to subtasks once their dependencies are
satisfied, and the same status ``_dispatch_subtask`` requires before it will
run a subtask. Claiming therefore does not change ``status``; it only sets
``claimed_by`` / ``claimed_at`` / ``heartbeat_at`` via a single atomic guarded
UPDATE. This keeps the claim itself a one-statement, lock-free operation
(SQLite executes a single UPDATE atomically) without needing to route through
``_transition_subtask`` (which would emit a spurious "in_progress ->
in_progress" transition event).

Status changes that *do* need to stay on the canonical path -- e.g. requeuing
a subtask whose worker crashed -- go through ``_transition_subtask`` so the
event/message stream stays consistent.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.notifications import lifecycle_event_listener
from src.storage import Storage, connect, run_migrations

from .providers import DEFAULT_CLAIM_LEASE_SECONDS, _dispatch_subtask
from .scheduling import _transition_subtask
from .full_engine import run_claimed_full_engine_task

logger = logging.getLogger("sarathi.worker")

# Status assigned by _schedule_ready_subtasks to subtasks that are ready to
# execute, and required by _dispatch_subtask before it will run a subtask.
READY_STATUS = "in_progress"
REQUEUED_STATUS = "queued"


def claim_next_subtask(storage: Storage, worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the oldest ready, unclaimed subtask.

    Returns the claimed subtask (re-fetched after the claim) or ``None`` if
    there is nothing claimable right now.
    """
    for candidate in storage.list_claimable_subtasks(status=READY_STATUS):
        if storage.claim_subtask(candidate["id"], worker_id=worker_id, status=READY_STATUS):
            claimed = storage.get_subtask(candidate["id"])
            if claimed is not None:
                return claimed
        # Lost the race (another worker claimed it first) -- try the next one.
    return None


def heartbeat(storage: Storage, subtask_id: str, worker_id: str) -> bool:
    """Refresh the claim heartbeat for ``subtask_id``.

    Returns False if the subtask is no longer claimed by ``worker_id``
    (e.g. it was requeued as stale by another worker).
    """
    return storage.heartbeat_subtask_claim(subtask_id, worker_id=worker_id)


def requeue_stale_claims(
    storage: Storage, lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS
) -> list[str]:
    """Release claims whose heartbeat is older than ``lease_seconds``.

    Subtasks are transitioned back to ``queued`` via ``_transition_subtask``
    (so the event/message stream records the requeue) and their claim
    columns are cleared. Returns the ids of requeued subtasks.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).isoformat()
    requeued: list[str] = []
    for stale in storage.list_stale_claimed_subtasks(status=READY_STATUS, before=cutoff):
        worker_id = stale.get("claimed_by")
        logger.warning(
            "Requeuing stale claim: subtask=%s worker=%s heartbeat_at=%s",
            stale["id"],
            worker_id,
            stale.get("heartbeat_at"),
        )
        _transition_subtask(
            storage,
            stale,
            {
                "status": REQUEUED_STATUS,
                "actor": "Sutra",
                "reason": f"Requeued: claim lease expired for worker '{worker_id}'.",
            },
        )
        storage.clear_subtask_claim(stale["id"])
        requeued.append(stale["id"])
    return requeued


def _release_failed_claim(storage: Storage, subtask_id: str, *, reason: str) -> None:
    """Requeue a claimed subtask after a dispatch-time error.

    Mirrors the conservative behavior of the HTTP dispatch path: if dispatch
    itself raises (rather than returning a structured failure), the subtask
    is left in its pre-dispatch state for a retry, so move it back to
    ``queued`` via the canonical transition path and clear the claim.
    """
    subtask = storage.get_subtask(subtask_id)
    if subtask is None:
        return
    if subtask["status"] == READY_STATUS:
        _transition_subtask(
            storage,
            subtask,
            {
                "status": REQUEUED_STATUS,
                "actor": "Sutra",
                "reason": reason,
            },
        )
    storage.clear_subtask_claim(subtask_id)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _try_claim_full_engine_task(storage: Storage, worker_id: str) -> dict[str, Any] | None:
    """Claim the oldest queued full-Engine task, or None if there's nothing claimable.

    No lease/heartbeat reclaim for full-Engine tasks (unlike subtasks): a
    worker crash mid-run leaves the row at status='running' until manually
    requeued. That's an accepted, documented gap for this first cut -- see
    ``src/service/full_engine.py``.
    """
    for candidate in storage.list_claimable_full_engine_tasks():
        claimed = storage.claim_full_engine_task(candidate["id"], worker_id=worker_id)
        if claimed is not None:
            return claimed
        # Lost the race (another worker claimed it first) -- try the next one.
    return None


def run_worker(
    db_path: str | Path,
    *,
    worker_id: str | None = None,
    poll_interval: float = 2.0,
    once: bool = False,
    lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS,
    max_items: int | None = None,
    should_stop: Any = None,
    tasks_dir: str | None = None,
) -> dict[str, Any]:
    """Run the work-queue worker loop.

    Args:
        db_path: Path to the shared SQLite database.
        worker_id: Identity recorded on claims. Defaults to ``hostname-pid``.
        tasks_dir: Override for where full-Engine tasks read/write their
            TaskContext JSON (default: ``.sarathi/tasks`` relative to cwd).
            See ``src/service/full_engine.py``.
        poll_interval: Seconds to sleep between polls when the queue is empty.
        once: If True, process at most one item then return.
        lease_seconds: Claim lease window used by ``requeue_stale_claims``.
        max_items: Optional cap on the number of items processed.
        should_stop: Optional zero-arg callable; when it returns True the
            loop exits after finishing the current item (used for graceful
            SIGINT handling in the CLI).

    Returns:
        Summary dict: ``{"claimed": N, "succeeded": N, "failed": N, "requeued": [...],
        "full_engine_claimed": N, "full_engine_failed": N}``. The subtask
        queue is tried first every poll; a full-Engine task (``sarathi run
        --background``, see ``src/service/full_engine.py``) is only claimed
        when no subtask is ready, and doesn't count toward ``claimed``/
        ``max_items`` -- it's a separate, much lower-throughput queue.
    """
    worker_id = worker_id or default_worker_id()
    summary: dict[str, Any] = {
        "claimed": 0,
        "succeeded": 0,
        "failed": 0,
        "requeued": [],
        "full_engine_claimed": 0,
        "full_engine_failed": 0,
    }
    limit = 1 if once else max_items

    with connect(db_path) as conn:
        run_migrations(conn)
        _lookup = Storage(conn)
        storage = Storage(conn, event_listener=lifecycle_event_listener(get_task=_lookup.get_task))

        while True:
            if should_stop is not None and should_stop():
                break
            if limit is not None and summary["claimed"] >= limit:
                break

            summary["requeued"].extend(requeue_stale_claims(storage, lease_seconds))

            subtask = claim_next_subtask(storage, worker_id)
            if subtask is None:
                full_engine_task = _try_claim_full_engine_task(storage, worker_id)
                if full_engine_task is not None:
                    summary["full_engine_claimed"] += 1
                    try:
                        run_claimed_full_engine_task(
                            storage, full_engine_task, worker_id=worker_id, tasks_dir=tasks_dir
                        )
                    except Exception:
                        summary["full_engine_failed"] += 1
                    if once:
                        break
                    continue
                if once:
                    break
                if should_stop is not None and should_stop():
                    break
                time.sleep(poll_interval)
                continue

            summary["claimed"] += 1
            logger.info("Claimed subtask %s (worker=%s)", subtask["id"], worker_id)

            heartbeat(storage, subtask["id"], worker_id)
            try:
                result = _dispatch_subtask(storage, subtask, {})
            except Exception:
                logger.exception("Dispatch failed for subtask %s", subtask["id"])
                _release_failed_claim(
                    storage,
                    subtask["id"],
                    reason="Requeued: dispatch raised an unexpected error.",
                )
                summary["failed"] += 1
                continue

            # Dispatch completed (success or structured failure); the subtask
            # is no longer in_progress, so release the claim bookkeeping.
            storage.clear_subtask_claim(subtask["id"])
            dispatch = result.get("dispatch") or {}
            if dispatch.get("status") == "completed":
                summary["succeeded"] += 1
                logger.info("Dispatched subtask %s successfully", subtask["id"])
            else:
                summary["failed"] += 1
                logger.warning(
                    "Dispatch for subtask %s finished with status=%s",
                    subtask["id"],
                    dispatch.get("status"),
                )

            if once:
                break

    return summary


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="Sarathi work-queue worker: claim and dispatch ready subtasks.",
    )
    parser.add_argument("--db", required=True, help="Path to the shared sarathi.db SQLite database.")
    parser.add_argument("--once", action="store_true", help="Process at most one item then exit.")
    parser.add_argument(
        "--poll", type=float, default=2.0, dest="poll_interval", help="Seconds between polls when idle."
    )
    parser.add_argument(
        "--lease", type=int, default=DEFAULT_CLAIM_LEASE_SECONDS, dest="lease_seconds",
        help="Seconds before a claim's heartbeat is considered stale.",
    )
    parser.add_argument("--worker-id", dest="worker_id", default=None, help="Worker identity for claims.")
    parser.add_argument(
        "--max-items", type=int, default=None, dest="max_items", help="Stop after processing this many items."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stop_requested = {"flag": False}

    def _handle_sigint(signum, frame):
        if stop_requested["flag"]:
            # Second Ctrl-C: exit immediately.
            raise SystemExit(130)
        logger.info("Received interrupt signal; finishing current item then exiting.")
        stop_requested["flag"] = True

    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        summary = run_worker(
            args.db,
            worker_id=args.worker_id,
            poll_interval=args.poll_interval,
            once=args.once,
            lease_seconds=args.lease_seconds,
            max_items=args.max_items,
            should_stop=lambda: stop_requested["flag"],
        )
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    print(summary)
    return summary


if __name__ == "__main__":
    main()
