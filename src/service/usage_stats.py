"""Pure projection of HarnessOutcome-derived quality signals for a workspace.

This module backs the web "Usage Stats" view — Sarathi's differentiator of
surfacing *quality* signals (test pass rate, blast radius, token cost,
proposal review activity) alongside raw cost, rather than cost alone.

All derivations here intentionally mirror ``src.harness.measure_outcome``:

  - ``test_pass_rate``  — derived from review run status (approved/passed
    review runs count as a pass) since stored review runs are the durable
    record of VERIFY/REVIEW outcomes for a task. When a task has no review
    runs, it contributes nothing to the rate (rather than fabricating a
    pass or fail).
  - ``blast_radius``    — ``1 - review_score`` for review runs that carry an
    explicit numeric score in their metadata (``metadata["review_score"]``
    or ``metadata["review_verdict"]["score"]``), matching
    ``harness.measure_outcome``'s "measured" path. Review runs without a
    score are skipped for this aggregate (no fabricated default).
  - ``token_cost``/``total_tokens`` — sum of ``dispatch_usage.total_tokens``
    (or the ``usage`` artifact recorded on a dispatch's metadata), matching
    ``harness.measure_outcome``'s token_cost derivation.
  - ``latency``         — wall-clock delta from a task's ``created_at`` to its
    ``updated_at`` (the storage analogue of harness ``assembled_at`` -> now).

Everything here is pure: no I/O beyond the provided ``storage`` facade, no
side effects, and missing data degrades to ``None``/``"—"`` rather than
raising or fabricating values.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


# Maximum number of most-recent tasks included in the per-task breakdown.
_DEFAULT_TASK_LIMIT = 50


def build_usage_stats(
    storage: Any,
    workspace_id: str,
    *,
    task_limit: int = _DEFAULT_TASK_LIMIT,
) -> dict[str, Any]:
    """Compute workspace-level quality aggregates plus a per-task breakdown.

    Returns a dict shaped as::

        {
            "workspace_id": str,
            "task_count": int,
            "test_pass_rate": float | None,
            "avg_blast_radius": float | None,
            "total_tokens": int,
            "proposal_counts": {"pending": int, "accepted": int, "rejected": int} | None,
            "tasks": [
                {
                    "task_id": str,
                    "title": str,
                    "task_class": str | None,
                    "agent": str | None,
                    "pass": bool | None,
                    "blast_radius": float | None,
                    "tokens": int | None,
                    "latency": float | None,
                },
                ...
            ],
        }

    Defensive by construction: any missing/malformed storage data results in
    ``None`` fields rather than an exception. Never mutates ``storage``.
    """
    tasks = storage.list_tasks_for_workspace(workspace_id) or []

    per_task: list[dict[str, Any]] = []
    pass_flags: list[bool] = []
    blast_radii: list[float] = []
    total_tokens = 0

    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id:
            continue

        reviews = _safe_list(storage, "list_review_runs_for_task", task_id)
        dispatches = _safe_list(storage, "list_dispatches_for_task", task_id)

        task_pass = _task_pass(reviews)
        task_blast_radius = _task_blast_radius(reviews)
        task_tokens = _task_tokens(dispatches)
        task_agent = _task_agent(dispatches)
        task_latency = _task_latency(task)
        task_class = _task_class(task)

        if task_pass is not None:
            pass_flags.append(task_pass)
        if task_blast_radius is not None:
            blast_radii.append(task_blast_radius)
        if task_tokens is not None:
            total_tokens += task_tokens

        per_task.append(
            {
                "task_id": task_id,
                "title": task.get("title") or "—",
                "task_class": task_class,
                "agent": task_agent,
                "pass": task_pass,
                "blast_radius": task_blast_radius,
                "tokens": task_tokens,
                "latency": task_latency,
            }
        )

    # Most-recent-first for the per-task breakdown, capped at task_limit.
    recent_tasks = list(reversed(per_task))[: max(task_limit, 0)]

    test_pass_rate = (sum(1 for ok in pass_flags if ok) / len(pass_flags)) if pass_flags else None
    avg_blast_radius = (sum(blast_radii) / len(blast_radii)) if blast_radii else None

    return {
        "workspace_id": workspace_id,
        "task_count": len(tasks),
        "test_pass_rate": test_pass_rate,
        "avg_blast_radius": avg_blast_radius,
        "total_tokens": total_tokens,
        "proposal_counts": _proposal_counts(storage, workspace_id),
        "tasks": recent_tasks,
    }


def _safe_list(storage: Any, method_name: str, *args: Any) -> list[dict[str, Any]]:
    """Call a storage list method defensively, returning [] on any failure."""
    method = getattr(storage, method_name, None)
    if method is None:
        return []
    try:
        result = method(*args)
    except Exception:
        return []
    return result if isinstance(result, list) else []


def _review_score(review: dict[str, Any]) -> float | None:
    """Extract a numeric review score, matching harness.measure_outcome's lookup.

    Checks ``metadata["review_verdict"]["score"]`` then
    ``metadata["review_score"]`` — the same fields ``measure_outcome`` reads
    from a Review phase's artifacts.
    """
    metadata = review.get("metadata")
    if not isinstance(metadata, dict):
        return None
    verdict = metadata.get("review_verdict")
    raw = None
    if isinstance(verdict, dict):
        raw = verdict.get("score")
    if raw is None:
        raw = metadata.get("review_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _review_passed(review: dict[str, Any]) -> bool | None:
    """Whether a review run counts as a pass.

    A review run with status "approved" is a pass; "rejected" is a fail.
    Any other/unknown status contributes no signal (None).
    """
    status = str(review.get("status") or "").strip().lower()
    if status == "approved":
        return True
    if status == "rejected":
        return False
    return None


def _task_pass(reviews: list[dict[str, Any]]) -> bool | None:
    """Test/review pass signal for a task: True iff every review run passed.

    Mirrors the spirit of harness ``test_pass_rate`` (command_succeeded) using
    review run status as the durable storage-side proxy. Tasks with no
    review runs (or only unscored/unknown-status runs) return None.
    """
    outcomes = [outcome for outcome in (_review_passed(r) for r in reviews) if outcome is not None]
    if not outcomes:
        return None
    return all(outcomes)


def _task_blast_radius(reviews: list[dict[str, Any]]) -> float | None:
    """Mean of ``1 - review_score`` across review runs that carry a score.

    Matches ``harness.measure_outcome``'s "measured" blast_radius derivation.
    Reviews without an explicit numeric score are excluded rather than
    defaulted, to avoid fabricating signal.
    """
    radii: list[float] = []
    for review in reviews:
        score = _review_score(review)
        if score is None:
            continue
        radii.append(round(max(0.0, 1.0 - score), 2))
    if not radii:
        return None
    return sum(radii) / len(radii)


def _dispatch_usage(dispatch: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the usage artifact dict from a dispatch's metadata, if present.

    Dispatches persist usage under ``metadata["usage"]`` (see
    ``UsageRecord.to_artifact``) or, for dispatches that mirror phase
    artifacts directly, ``metadata["dispatch_usage"]``.
    """
    metadata = dispatch.get("metadata")
    if not isinstance(metadata, dict):
        return None
    usage = metadata.get("usage")
    if not isinstance(usage, dict):
        usage = metadata.get("dispatch_usage")
    return usage if isinstance(usage, dict) else None


def _task_tokens(dispatches: list[dict[str, Any]]) -> int | None:
    """Sum of ``total_tokens`` across a task's dispatches.

    Matches ``harness.measure_outcome``'s token_cost derivation (sum of
    ``dispatch_usage.total_tokens``). Returns None when no dispatch carries
    usage data (vs. 0 when usage is present but zero).
    """
    total = 0
    found = False
    for dispatch in dispatches:
        usage = _dispatch_usage(dispatch)
        if usage is None:
            continue
        found = True
        try:
            total += int(usage.get("total_tokens", 0) or 0)
        except (TypeError, ValueError):
            continue
    return total if found else None


def _task_agent(dispatches: list[dict[str, Any]]) -> str | None:
    """The most recently dispatched agent for a task, if any.

    ``list_dispatches_for_task`` returns dispatches ordered by
    ``created_at, id`` ascending, so the last entry is the most recent.
    """
    if not dispatches:
        return None
    agent_name = dispatches[-1].get("agent_name")
    return str(agent_name) if agent_name else None


def _task_class(task: dict[str, Any]) -> str | None:
    """Task class label, if recorded in task metadata.

    Storage does not currently persist a dedicated ``task_class`` column;
    this reads ``metadata["task_class"]`` defensively for forward
    compatibility with engines that record it there.
    """
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        return None
    task_class = metadata.get("task_class")
    return str(task_class) if task_class else None


def _task_latency(task: dict[str, Any]) -> float | None:
    """Wall-clock latency in milliseconds from task creation to last update.

    Storage analogue of ``harness.measure_outcome``'s
    ``assembled_at -> now`` latency: ``created_at -> updated_at``.
    """
    created_at = task.get("created_at")
    updated_at = task.get("updated_at")
    if not created_at or not updated_at:
        return None
    created = _parse_timestamp(created_at)
    updated = _parse_timestamp(updated_at)
    if created is None or updated is None:
        return None
    delta_ms = (updated - created).total_seconds() * 1000
    return max(0.0, delta_ms)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _proposal_counts(storage: Any, workspace_id: str) -> dict[str, int] | None:
    """Pending/accepted/rejected proposal counts, if storage exposes them.

    Storage has no dedicated proposals table — proposal review state lives
    in a workspace's policy-pack on disk (see ``service.proposals``), which
    this pure module does not touch. If a future storage facade exposes a
    ``list_proposals``/``get_proposal_summary``-style method for a workspace,
    it is used here; otherwise this returns None (unavailable) rather than
    fabricating zeros.
    """
    for method_name in ("get_proposal_summary", "list_proposals"):
        method = getattr(storage, method_name, None)
        if method is None:
            continue
        try:
            result = method(workspace_id)
        except Exception:
            continue
        if method_name == "get_proposal_summary" and isinstance(result, dict):
            return {
                "pending": int(result.get("pending_count", result.get("pending", 0)) or 0),
                "accepted": int(result.get("accepted_count", result.get("accepted", 0)) or 0),
                "rejected": int(result.get("rejected_count", result.get("rejected", 0)) or 0),
            }
        if method_name == "list_proposals" and isinstance(result, list):
            counts = {"pending": 0, "accepted": 0, "rejected": 0}
            for proposal in result:
                if not isinstance(proposal, dict):
                    continue
                status = str(proposal.get("status") or "pending").lower()
                if status in counts:
                    counts[status] += 1
            return counts
    return None
