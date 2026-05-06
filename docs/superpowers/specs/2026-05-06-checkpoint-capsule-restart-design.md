# Sarathi Checkpoint Capsule and Restart Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-06

## Goal

Sarathi should reduce context bloat by turning a finished task into a compact checkpoint capsule that can be used to start a fresh session later. The restart flow should preserve what matters most from the completed task while avoiding full-history replay by default.

The user should be able to finish a task, keep the full task retrievable by pointer, and begin a new session from the compact checkpoint instead of dragging the entire old conversation forward.

## Design Principles

1. Compact by default
   - The checkpoint stores the minimum useful summary needed to restart work.
   - Full transcripts remain attached to the original task, not duplicated into the new session.

2. Retrievable later
   - Every checkpoint must point back to the original task and its evidence.
   - The user can always reopen the source task if they need full history.

3. Task-panel first
   - The restart action should appear where the task completes, not buried in a separate admin flow.
   - The UI should make the next step obvious: start a new session or open the source task.

4. Policy-backed handoff
   - The checkpoint should preserve the task's decision state, including repository-action preference and any other active handoff constraints.
   - Sarathi should not silently change behavior when moving into a fresh session.

## User-Facing Behavior

When a task reaches `done` or `handoff`, Sarathi should create a checkpoint capsule containing:

- task summary
- key decisions
- linked evidence
- active repository-action preference
- next recommended starting point
- pointer back to the source task

The task panel should then offer:

- `Start new session`
- `Open source task`
- `Copy checkpoint summary`

`Start new session` creates a new task/session context from the capsule summary, not from the full timeline.

## Checkpoint Capsule Model

The checkpoint capsule should be a compact object, not a second transcript store.

Recommended fields:

- `checkpoint_id`
- `source_task_id`
- `workspace_id`
- `project_id`
- `status`
- `summary`
- `key_decisions`
- `evidence_refs`
- `repository_action_preference`
- `next_start_point`
- `created_at`
- `created_by`

Rules:

- `summary` should be short and human-readable.
- `key_decisions` should be a bounded list of the important choices that shaped the task.
- `evidence_refs` should point to the original artifacts, not copy them.
- `repository_action_preference` must carry the active default-off or opt-in posture forward.

## Data Flow

1. Task reaches `done` or `handoff`.
2. Sarathi writes a checkpoint capsule tied to the source task.
3. The task panel shows the compact checkpoint card and restart actions.
4. If the user starts a new session, Sarathi creates a new task or session context using the capsule as the seed.
5. The original task remains retrievable from the checkpoint pointer.

This should keep the new session light while preserving traceability.

## UI Surface

### Task Panel

The completed task panel should show a compact checkpoint card with:

- task summary
- important decisions
- evidence links
- restart action

The panel should not auto-expand into the full previous thread.

### New Session Entry

The new session should begin with a compact prompt seeded from the checkpoint summary, such as:

- `Resume from checkpoint`
- `Start fresh from this result`

The new session should clearly indicate that it is derived from a completed task.

## Error and Safety Rules

- If checkpoint creation fails, the original task must remain usable.
- If the source task is missing evidence links, the checkpoint should still be created with the available summary.
- The restart flow must not lose the source task pointer.
- The checkpoint should not duplicate secrets, raw provider payloads, or verbose transcripts.

## Non-Goals

- Full timeline replay inside the checkpoint
- A second transcript store for every task
- Automatic task continuation without user initiation
- Session branching graphs or multi-branch history trees
- Changing the existing SSE or SQLite supervision model

## Current Gap Summary

Sarathi already has the primitives needed for a clean checkpoint/restart flow:

- task state and handoff tracking
- evidence and review artifacts
- compact supervision state
- workspace/project/task scoping

What is missing is the explicit checkpoint capsule that lets a completed task become the starting point for a new session without carrying forward the whole old context.

