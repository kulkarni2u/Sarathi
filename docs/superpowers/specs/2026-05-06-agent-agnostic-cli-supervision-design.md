# Sarathi Agent-Agnostic CLI Supervision Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-06

## Goal

Sarathi CLI should supervise work in a way that is independent of the agent provider and efficient in token usage. The CLI should normalize a task into a compact contract, expose live supervision state, and avoid sending verbose history unless the worker explicitly needs it.

This spec fills the gap between Sarathi as a workflow engine and Sarathi as an orchestrator: the CLI is the execution and supervision layer, while the desktop app is the human cockpit.

## Design Principles

1. Agent agnostic by default
   - The supervision contract must work for Claude, OpenCode, Codex, or any future provider.
   - Providers should receive the same compact task shape, with only role-specific fields added when needed.

2. Token efficient by default
   - Send intent, constraints, current step, and blockers.
   - Do not send full transcripts or historical logs unless explicitly requested.
   - Prefer structured fields and deltas over prose dumps.

3. Compact supervision state
   - CLI status output should summarize task progress in one or two short blocks.
   - The watch surface should surface state changes, not a wall of text.

4. Shared task truth
   - Parent/child links, manifest data, block reasons, and `needs_from` should come from the task graph, not from provider-specific memory.
   - The same compact model should drive both CLI output and desktop task panels.

## Canonical Task Contract

Every supervised task should be representable as a compact JSON-like contract:

- `task_id`
- `parent_task_id`
- `role`
- `goal`
- `current_step`
- `acceptance_criteria`
- `recent_changes`
- `next_action`
- `block_reason`
- `needs_from`
- `state`
- `evidence_refs`

Rules:

- `state` must be one of `running`, `blocked`, `waiting_user`, `stale`, or `done`.
- `block_reason` must be short and actionable.
- `needs_from` must list only the missing dependency IDs or the human input needed.
- `recent_changes` should be a short delta, not a transcript.
- `evidence_refs` should be pointers, not copied content.

## CLI Surfaces

### `sarathi status <task_id>`

Print a compact snapshot:

- task identity and parent link
- current state
- latest step or summary
- blocked reason, if any
- next action
- manifest summary

The command should be readable in one screen and should avoid dumping raw graph or provider payloads.

### `sarathi watch <task_id>`

Watch should provide a live supervision snapshot that refreshes the same compact contract.

Expected behavior:

- show state transitions as they happen
- highlight when a task becomes blocked or waiting on the user
- show when a task becomes stale
- keep the output short enough for continuous terminal use

Polling is acceptable as an initial implementation, but the UX should still behave like a live watch surface rather than a transcript tail.

## Manifest Model

The task graph should be able to derive a manifest for supervision.

Manifest entries should include:

- `parent_task_id`
- `child_task_ids`
- `needs_from`
- `block_reason`
- `state`
- `role`
- `next_action`

This lets Sarathi supervise spawned subtasks without introducing a separate persisted orchestration store.

## Data Flow

1. A task is created or resumed.
2. The task graph derives parent/child links and compact supervision state.
3. The CLI prints status or watch output from the manifest.
4. Workers receive only the compact contract they need.
5. Progress updates change the task graph state, which updates the manifest and the watch output.

The CLI should not require provider-specific prompt templates for this core path.

## Error and Block Handling

- `blocked` means a concrete dependency or decision is required.
- `waiting_user` means the next action needs human input.
- `stale` means the task has not progressed recently, but may still recover automatically.
- If a worker cannot continue, the CLI should record a short `block_reason` and a minimal `needs_from` entry.

## Non-Goals

- A second orchestration system separate from the task graph
- Full conversational transcripts in CLI output
- Provider-specific command formats in the supervision contract
- A heavy streaming protocol before the compact snapshot model is proven

## Current Gap Summary

The current CLI/runtime direction is good enough to orchestrate tasks, but the remaining value is in making the contract more explicit and disciplined:

- keep the agent input agent-agnostic
- keep status output compact
- keep block reasons actionable
- keep live watch surfaces short and readable

That is the standard Sarathi should use for supervising Claude, OpenCode, Codex, and future workers.
