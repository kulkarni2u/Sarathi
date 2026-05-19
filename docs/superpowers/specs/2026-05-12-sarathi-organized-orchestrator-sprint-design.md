# Sarathi Organized Orchestrator Sprint Design

Date: 2026-05-12
Status: Proposed
Timebox: 1 to 2 weeks

## Goal

Ship the first version of Sarathi that clearly feels like an organized orchestration cockpit instead of a promising but partially fragmented desktop prototype.

This sprint should make an operator able to answer, within a few seconds:

- what work exists
- what state each work item is in
- what is blocked
- what needs approval
- what can resume safely
- what evidence or handoff posture exists

## Why This Sprint

Sarathi already has meaningful pieces:

- workspaces and projects
- task dashboard and task studio
- approval gates
- checkpoint capsules
- brainstorm sessions
- provider health and runtime concepts

What is still missing is the organizing layer that turns those pieces into one coherent operating model.

This sprint is intentionally not about broad feature expansion. It is about product coherence.

## Product Outcome

At sprint end, Sarathi should present one clear story:

`Conversation becomes work. Work moves through named queues. Humans govern sensitive transitions. Evidence and handoff posture are visible. Interrupted work can resume safely.`

## Scope

### In scope

1. Control tower state across `Workspace -> Project -> Task`
2. Inbox as a real action queue
3. Explicit queue and lifecycle labels
4. Approval and policy posture visibility
5. Checkpoint, resume, and rerun visibility
6. Handoff readiness and evidence posture visibility
7. Basic CLI parity for status and approval inspection where already close to existing service contracts

### Out of scope

1. Full template marketplace or workflow marketplace
2. Full learnings library and long-term memory productization
3. Full org-level RBAC or multi-user collaboration
4. Provider transport rewrite
5. Major runtime refactors outside the service/UI contracts needed for this sprint
6. Full acceptance-criteria auto-mapping engine if it would delay the control-tower ship

## Chosen Sprint Theme

`Organized Orchestrator`

The desktop should behave like a disciplined control tower:

- queues over hidden background work
- named states over vague badges
- real blockers over optimistic summaries
- approvals as first-class operational objects
- checkpoints and reruns as safe recovery controls
- handoff and evidence as part of execution, not afterthoughts

## User Experience Targets

### Workspace

The workspace page should answer:

- is this workspace healthy
- which projects need attention
- whether providers and repositories are ready
- what the dominant next action is

### Project

The project page should answer:

- which tasks are blocked, waiting, active, or handoff-ready
- which task should be opened next
- whether approvals or review failures are piling up

### Task Studio

The task studio should answer:

- current lifecycle state
- current approval or policy gate
- blocker reason
- checkpoint availability
- handoff posture
- next safe action

### Inbox

Inbox becomes the cross-workspace human attention queue:

- approvals needed
- blocked tasks
- failed reviews
- failed runs
- restart-ready checkpoints
- handoff-ready tasks

## Canonical Sprint Contracts

This sprint should make these contracts explicit across service and UI:

### Core queue labels

- `intake`
- `planning`
- `awaiting_approval`
- `ready`
- `running`
- `under_review`
- `blocked`
- `waiting_human`
- `failed`
- `handoff_ready`
- `done`

### Required task summary fields

Every task summary used by workspace, project, inbox, or CLI should expose:

- `status`
- `phase`
- `approval_state`
- `graph_state`
- `next_gate`
- `blocked_count`
- `review_needed_count`
- `checkpoint_state`
- `handoff_state`
- `updated_at`

### Required operational visibility

The operator should be able to see:

- approvals pending by workspace and project
- blocked reasons
- provider failures and degraded health
- repository-action posture
- checkpoint availability
- handoff readiness

## Architecture

This sprint stays within Sarathi's current architecture:

- Python stdlib service remains the contract boundary
- SQLite-backed storage remains the durable state layer
- React desktop remains the main operator surface
- CLI and provider runtime stay intact, with only targeted status/inspection support added where needed

### Service responsibility

The service should own:

- queue and lifecycle projections
- approval queue aggregation
- inbox aggregation
- workspace and project operational summaries
- checkpoint and handoff summary exposure
- policy posture normalization for UI consumption

### Desktop responsibility

The desktop should own:

- clear operational hierarchy
- strong state chips and attention cues
- queue views and filters
- no fake live state on primary surfaces
- one-click path from summary to action surface

## Key Design Decisions

### 1. Organize around projections, not raw tables

The service should provide purpose-built summary payloads for:

- workspace operational overview
- project task overview
- inbox attention queue
- task studio state header

This avoids duplicating business logic in the desktop.

### 2. Keep the current object model, but sharpen it

This sprint does not need a full schema redesign. It needs better use of the existing objects:

- tasks
- approval gates
- lifecycle events
- checkpoints
- handoffs
- provider health
- workspace/project metadata

### 3. Inbox is the control tower surface

Inbox should become the fastest way to see what the human must do next.

### 4. Avoid new "management" pages unless they reduce ambiguity

We should improve the current pages before adding more top-level navigation.

### 5. Favor visible truth over decorative density

If a metric or badge does not change operator decisions, it should be secondary.

## Multi-Agent Execution Model

This sprint is designed for parallel execution by Codex, OpenCode, and Claude.

### Codex ownership

- desktop shell wiring
- React state flow
- page-level UX hierarchy
- integration of service projections into current desktop routes

### OpenCode ownership

- Python service routes and projection helpers
- storage extensions if needed
- CLI/status surfacing where required
- checkpoint, approval, and inbox aggregation contracts

### Claude ownership

- product consistency review
- acceptance-criteria audit
- test-plan review
- design QA and wording of state/queue labels
- end-to-end ship readiness review

### Coordination rules

1. Shared contract first
   - Agree on the queue/state vocabulary and payload fields before parallel coding.
2. Disjoint write surfaces
   - OpenCode owns `src/service/*`, `src/storage/*`, and targeted tests.
   - Codex owns `desktop/src/*`.
   - Claude reviews design, validates naming, and pressure-tests acceptance criteria.
3. Fast integration loop
   - Merge backend contract changes first.
   - Merge desktop consumers second.
   - Run end-to-end QA last.

## Success Criteria

This sprint succeeds when:

1. Workspace, project, inbox, and task studio all use the same visible lifecycle language.
2. Inbox acts as a real action queue rather than a generic surface.
3. A blocked or waiting-human task is visibly different from a running one.
4. Approval posture and repository-action posture are visible without drilling into raw metadata.
5. A checkpoint-capable task clearly exposes resume or rerun options.
6. Handoff-ready work is visibly separated from merely completed internal execution.
7. The desktop no longer relies on mock/demo-only truth for the primary organized-orchestrator surfaces when the service is available.

## Risks

### Scope creep

The product invites expansion into templates, graphs, marketplace, and learnings. Those should stay secondary in this sprint.

### Contract drift

If desktop and service invent different queue labels, the sprint will create more confusion, not less.

### Hidden backend complexity

If projections are spread across too many ad hoc endpoints, the UI will remain fragile.

### Over-design

This sprint should not turn into a giant information architecture rewrite. It should ship the smallest coherent control tower.

## Recommendation

The sprint should focus on one statement:

`Make Sarathi operationally legible.`

If tradeoffs are required, prefer:

- clear state over more features
- real projections over mock richness
- approval and recovery visibility over aesthetic polish
- task coherence over new surface count
