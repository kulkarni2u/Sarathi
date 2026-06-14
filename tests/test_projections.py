"""Tests for the normalized task summary projections in src.service.projections."""

from __future__ import annotations

from typing import Any

from src.service.projections import (
    QUEUE_STATES,
    task_queue_state,
    task_summary_projection,
)


def _task(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "task-1",
        "workspace_id": "ws-1",
        "title": "Example task",
        "description": None,
        "status": "pending",
        "metadata": {},
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _gate(name: str, status: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": f"gate-{name}-{status}",
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "name": name,
        "status": status,
        "metadata": {},
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _subtask(status: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": f"subtask-{status}-{overrides.get('id', '')}",
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "title": "Subtask",
        "status": status,
        "metadata": {},
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
        "claimed_by": None,
        "claimed_at": None,
        "heartbeat_at": None,
    }
    base.update(overrides)
    return base


def _review(status: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": f"review-{status}",
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "status": status,
        "summary": None,
        "metadata": {},
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _event(event_type: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": f"event-{event_type}",
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "event_type": event_type,
        "object_id": None,
        "payload": {},
        "created_at": "2026-06-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# task_queue_state scenarios
# ---------------------------------------------------------------------------


def test_intake_for_brand_new_task():
    task = _task(status="pending")
    state = task_queue_state(
        task,
        subtasks=[],
        approval_gates=[],
        review_runs=[],
        lifecycle_events=[],
    )
    assert state == "intake"


def test_planning_when_task_has_activity_but_no_graph_signal():
    task = _task(status="pending")
    state = task_queue_state(
        task,
        subtasks=[],
        approval_gates=[],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "planning"


def test_awaiting_approval_for_pending_gate():
    task = _task(status="pending")
    state = task_queue_state(
        task,
        subtasks=[],
        approval_gates=[_gate("PRD/AC", "pending")],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "awaiting_approval"


def test_ready_when_subtasks_queued_and_no_blockers():
    task = _task(status="queued")
    state = task_queue_state(
        task,
        subtasks=[_subtask("queued", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "ready"


def test_running_when_subtask_in_progress():
    task = _task(status="in_progress")
    state = task_queue_state(
        task,
        subtasks=[_subtask("in_progress", id="a"), _subtask("queued", id="b")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "running"


def test_blocked_when_subtask_blocked():
    task = _task(status="blocked")
    state = task_queue_state(
        task,
        subtasks=[_subtask("blocked", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[],
        lifecycle_events=[_event("task.blocked")],
    )
    assert state == "blocked"


def test_waiting_human_when_subtask_waiting_human():
    task = _task(status="waiting_human")
    state = task_queue_state(
        task,
        subtasks=[_subtask("waiting_human", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "waiting_human"


def test_under_review_when_review_run_pending():
    task = _task(status="review")
    state = task_queue_state(
        task,
        subtasks=[_subtask("complete", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[_review("pending")],
        lifecycle_events=[_event("review.completed")],
    )
    assert state == "under_review"


def test_under_review_when_subtask_in_review_status():
    task = _task(status="review")
    state = task_queue_state(
        task,
        subtasks=[_subtask("review", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "under_review"


def test_failed_when_latest_review_rejected():
    task = _task(status="blocked")
    state = task_queue_state(
        task,
        subtasks=[_subtask("review", id="a")],
        approval_gates=[_gate("Task graph", "approved")],
        review_runs=[_review("approved"), _review("rejected")],
        lifecycle_events=[_event("review.rejected")],
    )
    assert state == "failed"


def test_handoff_ready_after_handoff_created_without_approval():
    task = _task(status="repository_action_pending")
    state = task_queue_state(
        task,
        subtasks=[_subtask("complete", id="a")],
        approval_gates=[_gate("Repository action", "pending")],
        review_runs=[_review("approved")],
        lifecycle_events=[_event("review.completed"), _event("handoff.created")],
    )
    assert state == "handoff_ready"


def test_done_when_repository_action_approved_after_handoff():
    task = _task(status="done")
    state = task_queue_state(
        task,
        subtasks=[_subtask("complete", id="a")],
        approval_gates=[_gate("Repository action", "approved")],
        review_runs=[_review("approved")],
        lifecycle_events=[
            _event("handoff.created"),
            _event("repository_action.approved"),
        ],
    )
    assert state == "done"


def test_done_when_task_status_done_even_without_subtasks():
    task = _task(status="done")
    state = task_queue_state(
        task,
        subtasks=[],
        approval_gates=[],
        review_runs=[],
        lifecycle_events=[_event("task.draft_created")],
    )
    assert state == "done"


def test_queue_state_is_always_from_canonical_vocabulary():
    scenarios = [
        (_task(status="pending"), [], [], [], []),
        (_task(status="done"), [], [], [], [_event("task.draft_created")]),
    ]
    for task, subtasks, gates, reviews, events in scenarios:
        state = task_queue_state(
            task,
            subtasks=subtasks,
            approval_gates=gates,
            review_runs=reviews,
            lifecycle_events=events,
        )
        assert state in QUEUE_STATES


# ---------------------------------------------------------------------------
# task_summary_projection field coverage
# ---------------------------------------------------------------------------


EXPECTED_FIELDS = {
    "status",
    "phase",
    "queue_state",
    "approval_state",
    "graph_state",
    "next_gate",
    "blocked_count",
    "review_needed_count",
    "checkpoint_state",
    "handoff_state",
    "updated_at",
    "project_id",
}


def test_summary_projection_has_full_field_set_minimal_task():
    task = _task(status="pending")
    summary = task_summary_projection(
        task,
        subtasks=[],
        approval_gates=[],
        review_runs=[],
        lifecycle_events=[],
    )
    assert set(summary.keys()) == EXPECTED_FIELDS
    assert summary["status"] == "pending"
    assert summary["phase"] == "pending"
    assert summary["queue_state"] == "intake"
    assert summary["approval_state"] == "none"
    assert summary["graph_state"] == "not_started"
    assert summary["next_gate"] is None
    assert summary["blocked_count"] == 0
    assert summary["review_needed_count"] == 0
    assert summary["checkpoint_state"] == "none"
    assert summary["handoff_state"] == "none"
    assert summary["updated_at"] == task["updated_at"]
    # project_id column is being added in parallel -- absent on the row
    # should default to None rather than raising.
    assert summary["project_id"] is None


def test_summary_projection_reads_project_id_when_present():
    task = _task(status="pending", project_id="proj-123")
    summary = task_summary_projection(
        task,
        subtasks=[],
        approval_gates=[],
        review_runs=[],
        lifecycle_events=[],
    )
    assert summary["project_id"] == "proj-123"


def test_summary_projection_with_pending_gate_and_blocked_subtask():
    task = _task(status="blocked", metadata={"phase": "TaskTracking"})
    summary = task_summary_projection(
        task,
        subtasks=[_subtask("blocked", id="a"), _subtask("queued", id="b")],
        approval_gates=[_gate("PRD/AC", "approved"), _gate("Task graph", "pending")],
        review_runs=[],
        lifecycle_events=[_event("task.blocked")],
    )
    assert set(summary.keys()) == EXPECTED_FIELDS
    assert summary["phase"] == "TaskTracking"
    assert summary["queue_state"] == "awaiting_approval"
    assert summary["approval_state"] == "graph_pending"
    assert summary["graph_state"] == "pending_approval"
    assert summary["next_gate"] == "Task graph"
    assert summary["blocked_count"] == 1


def test_summary_projection_handoff_and_checkpoint_state():
    task = _task(status="done")
    handoff = {
        "id": "handoff-1",
        "metadata": {"repository_action": {"status": "approved"}},
    }
    checkpoint = {"id": "checkpoint-1", "status": "ready"}
    summary = task_summary_projection(
        task,
        subtasks=[_subtask("complete", id="a")],
        approval_gates=[_gate("Repository action", "approved")],
        review_runs=[_review("approved")],
        lifecycle_events=[
            _event("handoff.created"),
            _event("repository_action.approved"),
        ],
        checkpoint=checkpoint,
        handoff=handoff,
    )
    assert summary["handoff_state"] == "ready"
    assert summary["checkpoint_state"] == "ready"
    assert summary["queue_state"] == "done"


def test_summary_projection_review_needed_count_includes_rejected_reviews():
    task = _task(status="blocked")
    summary = task_summary_projection(
        task,
        subtasks=[_subtask("review", id="a")],
        approval_gates=[_gate("Review", "pending")],
        review_runs=[_review("rejected")],
        lifecycle_events=[_event("review.rejected")],
    )
    assert summary["review_needed_count"] == 2
