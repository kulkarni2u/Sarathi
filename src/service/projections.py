"""Normalized task summary projections shared by all dashboard clients.

This module is the single place that derives a task's user-facing "queue
state" and the broader summary fields used by dashboard views (REST
handlers, websocket pushes, CLI summaries, etc.). All projection functions
here are pure: they take storage row dicts (as returned by
``src.storage.Storage``) and return plain values/dicts with no I/O.

The intent is to avoid every client re-deriving its own notion of "what is
this task currently waiting on" from raw rows -- instead they call
``task_queue_state`` / ``task_summary_projection`` and get a single
canonical answer.

Canonical ``queue_state`` vocabulary
-------------------------------------
``intake``           -- task has no graph/subtasks yet and has not started
                         planning (freshly drafted/created).
``planning``         -- task is being planned (graph not yet built/approved,
                         or no coordination signal yet).
``awaiting_approval`` -- a human approval gate is pending (PRD/AC, task
                         graph, review gate, etc).
``ready``            -- the execution graph has work ready to dispatch and
                         nothing is currently blocking it.
``running``          -- subtasks are actively in progress / under execution.
``under_review``     -- review run(s) are pending/in-flight for completed
                         work.
``blocked``          -- one or more subtasks are blocked (and no higher
                         priority signal -- approval/handoff/etc -- applies).
``waiting_human``    -- the graph is waiting on a human decision outside of
                         a formal approval gate (e.g. a subtask flagged
                         ``waiting_human``).
``failed``           -- a review run was rejected (failed verification) and
                         no later signal has superseded it.
``handoff_ready``    -- a handoff record exists and its repository action has
                         been approved, ready to hand off.
``done``             -- the task has reached a terminal completed state.
"""

from __future__ import annotations

from typing import Any, Sequence


# Canonical queue-state vocabulary, in the priority order they are checked.
# Earlier entries take precedence when multiple signals are present.
QUEUE_STATES: tuple[str, ...] = (
    "intake",
    "planning",
    "awaiting_approval",
    "ready",
    "running",
    "under_review",
    "blocked",
    "waiting_human",
    "failed",
    "handoff_ready",
    "done",
)


def task_queue_state(
    task_row: dict[str, Any],
    *,
    subtasks: Sequence[dict[str, Any]],
    approval_gates: Sequence[dict[str, Any]],
    review_runs: Sequence[dict[str, Any]],
    lifecycle_events: Sequence[dict[str, Any]],
) -> str:
    """Derive the canonical queue state for a task.

    Mirrors the precedence used by ``src.service.views._task_studio_queue_state``
    but works from raw storage rows so any client (REST, websocket, CLI) can
    compute the same value without re-deriving a graph view.

    Precedence (highest first):
      1. ``handoff_ready`` -- a handoff exists whose repository action has
         been approved. This is the most "done, just needs sign-off" state
         and should win over any earlier in-flight signals.
      2. ``done`` -- the task itself has reached a terminal status
         (``done``/``complete``) -- or every known subtask is complete.
      3. ``failed`` -- the most recent review run was rejected (verification
         failed) and nothing has cleared it.
      4. ``awaiting_approval`` -- any approval gate is still ``pending``.
      5. ``under_review`` -- review run(s) are pending, or one or more
         subtasks are sitting in the ``review`` status awaiting a verdict.
      6. ``waiting_human`` -- a subtask is stuck in ``waiting_human`` (a
         human decision is needed outside of a formal approval gate).
      7. ``blocked`` -- one or more subtasks are ``blocked``.
      8. ``running`` -- one or more subtasks are actively ``in_progress``.
      9. ``ready`` -- there is queued/ready work and nothing above applies.
      10. ``intake`` -- the task has no subtasks/graph and no lifecycle
          activity yet (freshly created/drafted).
      11. ``planning`` -- fallback: task exists, has some activity, but no
          execution graph signal applies yet (e.g. graph not yet approved).
    """
    # 1. Handoff ready takes top priority -- the work is essentially done and
    # is just waiting on the operator to review/ship the handoff (the
    # "Repository action" approval gate is pending after handoff creation).
    if _handoff_ready(lifecycle_events):
        return "handoff_ready"

    # 2. Terminal completion -- the task row itself has reached a done
    # status. (When every subtask completes, ``_refresh_task_tracking_state``
    # moves the task to status "review"/phase "Review" rather than "done",
    # so that case is handled by the review check below, not here.)
    if task_row.get("status") in {"done", "complete"}:
        return "done"

    # 3. A rejected review run means verification failed and the task needs
    # rework before it can proceed.
    if _latest_review_status(review_runs) == "rejected":
        return "failed"

    # 4. Any pending approval gate blocks forward progress until a human
    # responds (PRD/AC, Task graph, Review gate, etc).
    if any(gate.get("status") == "pending" for gate in approval_gates):
        return "awaiting_approval"

    # 5. Work has been completed and is sitting in review -- either a
    # review_run is pending, the task status itself is "review" (all
    # subtasks completed and are awaiting verification), or individual
    # subtasks are parked in the "review" status.
    if _latest_review_status(review_runs) == "pending":
        return "under_review"
    if task_row.get("status") == "review":
        return "under_review"
    if any(subtask.get("status") == "review" for subtask in subtasks):
        return "under_review"

    # 6. A subtask is waiting on a human outside of the approval-gate flow.
    if any(subtask.get("status") == "waiting_human" for subtask in subtasks):
        return "waiting_human"

    # 7. One or more subtasks are blocked on dependencies/failures.
    if any(subtask.get("status") == "blocked" for subtask in subtasks):
        return "blocked"

    # 8. Active execution in progress.
    if any(subtask.get("status") == "in_progress" for subtask in subtasks):
        return "running"

    # 9. There is queued work with no blockers -- ready to be dispatched.
    if any(subtask.get("status") in {"queued", "ready"} for subtask in subtasks):
        return "ready"

    # 10. Nothing has happened yet: no subtasks/graph and no lifecycle
    # activity recorded -- this is a freshly created/drafted task.
    if not subtasks and not lifecycle_events:
        return "intake"

    # 11. Fallback: the task exists and has some history, but no execution
    # graph signal currently applies (e.g. graph drafted but not approved).
    return "planning"


def task_summary_projection(
    task_row: dict[str, Any],
    *,
    subtasks: Sequence[dict[str, Any]],
    approval_gates: Sequence[dict[str, Any]],
    review_runs: Sequence[dict[str, Any]],
    lifecycle_events: Sequence[dict[str, Any]],
    graph: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the normalized task summary dict shared by all dashboard clients.

    Returns a dict with exactly these fields:
      - ``status``: the raw ``tasks.status`` value.
      - ``phase``: ``tasks.metadata.phase`` if present, else ``status``
        (matches ``src.service.views._task_dashboard``).
      - ``queue_state``: see :func:`task_queue_state`.
      - ``approval_state``: one of ``graph_pending``, ``prd_pending``,
        ``approval_pending``, ``approved``, ``none`` -- mirrors
        ``src.service.views._approval_state``.
      - ``graph_state``: one of ``not_started``, ``pending_approval``,
        ``approved`` -- mirrors ``src.service.views._graph_state``. Requires
        a ``graph`` (as produced by ``_graph_for_task``); if omitted, derived
        purely from ``approval_gates``/``subtasks`` presence.
      - ``next_gate``: the name of the next pending approval gate, or
        ``None``.
      - ``blocked_count``: number of subtasks currently ``blocked`` or
        ``waiting_human``.
      - ``review_needed_count``: pending review-named approval gates plus
        rejected review runs -- mirrors
        ``src.service.views._review_needed_count``.
      - ``checkpoint_state``: ``"none"`` or the checkpoint's ``status``
        -- mirrors ``src.service.views._checkpoint_state``.
      - ``handoff_state``: ``"none"``, ``"draft"``, or ``"ready"`` -- mirrors
        ``src.service.views._handoff_state``.
      - ``updated_at``: ``tasks.updated_at``.
      - ``project_id``: ``tasks.project_id`` if present on the row, else
        ``None``. (A ``project_id`` column is being added to ``tasks`` in
        parallel; until every row has it, this defaults to ``None`` rather
        than raising.)
    """
    metadata = task_row.get("metadata") or {}

    current_gates = _current_approval_gates(approval_gates)
    next_gate = _next_pending_gate(current_gates)

    blocked_count = sum(
        1 for subtask in subtasks if subtask.get("status") in {"blocked", "waiting_human"}
    )
    if graph is not None:
        blocked_count = len(graph.get("blocked_nodes", [])) + len(graph.get("waiting_human_nodes", []))

    return {
        "status": task_row.get("status"),
        "phase": metadata.get("phase", task_row.get("status")),
        "queue_state": task_queue_state(
            task_row,
            subtasks=subtasks,
            approval_gates=approval_gates,
            review_runs=review_runs,
            lifecycle_events=lifecycle_events,
        ),
        "approval_state": _approval_state(current_gates),
        "graph_state": _graph_state(graph, subtasks, current_gates),
        "next_gate": next_gate.get("name") if next_gate else None,
        "blocked_count": blocked_count,
        "review_needed_count": _review_needed_count(approval_gates, review_runs),
        "checkpoint_state": _checkpoint_state(checkpoint),
        "handoff_state": _handoff_state(handoff),
        "updated_at": task_row.get("updated_at"),
        # `project_id` is being added to `tasks` in a parallel migration;
        # read it defensively so this module works against both old and new
        # rows.
        "project_id": task_row.get("project_id"),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _handoff_ready(lifecycle_events: Sequence[dict[str, Any]]) -> bool:
    """Return True if a handoff exists and is awaiting an operator decision.

    ``task_queue_state`` does not receive the ``handoffs`` table directly, so
    this is derived from lifecycle events: ``_create_task_handoff`` (see
    ``src.service.review``) records a ``handoff.created`` event and opens a
    pending "Repository action" approval gate. If that gate is later
    approved, ``repository_action.approved`` is recorded and the task moves
    to status ``done``. So "handoff ready" means the most recent of these two
    signals is ``handoff.created`` -- i.e. a handoff was created and has not
    yet been approved/shipped.
    """
    last_signal: str | None = None
    for event in lifecycle_events:
        event_type = event.get("event_type")
        if event_type in {"handoff.created", "repository_action.approved"}:
            last_signal = event_type
    return last_signal == "handoff.created"


def _latest_review_status(review_runs: Sequence[dict[str, Any]]) -> str | None:
    """Return the status of the most recently created review run, if any."""
    if not review_runs:
        return None
    return review_runs[-1].get("status")


def _current_approval_gates(approval_gates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse approval gate history to the latest gate per name.

    Mirrors ``src.service.views._current_approval_gates``: gates are
    returned oldest-first, but only the most recent row for each gate
    ``name`` is kept (a gate can be re-requested after rejection).
    """
    seen: set[str] = set()
    current: list[dict[str, Any]] = []
    for gate in reversed(list(approval_gates)):
        name = str(gate.get("name") or "")
        if name in seen:
            continue
        seen.add(name)
        current.append(gate)
    current.reverse()
    return current


def _next_pending_gate(current_gates: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recently raised pending gate, if any.

    Mirrors ``src.service.views._next_pending_gate``.
    """
    for gate in reversed(list(current_gates)):
        if gate.get("status") == "pending":
            return gate
    return None


def _approval_state(current_gates: Sequence[dict[str, Any]]) -> str:
    """Mirrors ``src.service.views._approval_state``."""
    if any(gate.get("name") == "Task graph" and gate.get("status") == "pending" for gate in current_gates):
        return "graph_pending"
    if any(gate.get("name") == "PRD/AC" and gate.get("status") == "pending" for gate in current_gates):
        return "prd_pending"
    if any(gate.get("status") == "pending" for gate in current_gates):
        return "approval_pending"
    return "approved" if current_gates else "none"


def _graph_state(
    graph: dict[str, Any] | None,
    subtasks: Sequence[dict[str, Any]],
    current_gates: Sequence[dict[str, Any]],
) -> str:
    """Mirrors ``src.service.views._graph_state``.

    When a full ``graph`` view (from ``_graph_for_task``) is available, this
    matches the existing logic exactly. Without one, we fall back to using
    the presence of ``subtasks`` as a proxy for "graph has nodes".
    """
    has_nodes = bool(graph["nodes"]) if graph is not None else bool(subtasks)
    if not has_nodes:
        return "not_started"
    if any(gate.get("name") == "Task graph" and gate.get("status") == "pending" for gate in current_gates):
        return "pending_approval"
    return "approved"


def _review_needed_count(
    approval_gates: Sequence[dict[str, Any]],
    review_runs: Sequence[dict[str, Any]],
) -> int:
    """Mirrors ``src.service.views._review_needed_count``."""
    pending_review_gates = sum(
        1
        for gate in approval_gates
        if gate.get("status") == "pending" and str(gate.get("name") or "").lower() == "review"
    )
    rejected_reviews = sum(1 for review in review_runs if review.get("status") == "rejected")
    return pending_review_gates + rejected_reviews


def _checkpoint_state(checkpoint: dict[str, Any] | None) -> str:
    """Mirrors ``src.service.views._checkpoint_state``."""
    if checkpoint is None:
        return "none"
    return str(checkpoint.get("status") or "ready")


def _handoff_state(handoff: dict[str, Any] | None) -> str:
    """Mirrors ``src.service.views._handoff_state``."""
    if handoff is None:
        return "none"
    metadata = handoff.get("metadata") or {}
    repository_action = metadata.get("repository_action") or {}
    if repository_action.get("status") == "approved":
        return "ready"
    return "draft"
