# Sarathi Desktop Orchestration Studio Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-09

## Goal

Sarathi desktop should ship as a trustworthy orchestration cockpit for governed task execution, not as a generic workflow or marketplace product.

This pass should make the desktop feel production-ready by doing three things together:

1. Recenter the product around `workspace -> project -> task`.
2. Make the task studio and workflow state the clear product centerpiece.
3. Replace mock or local-only behavior on primary surfaces with real persisted service data wherever that behavior weakens trust.

The chosen visual/product direction is `Orchestration Studio`: calm premium shell language, denser operational task surfaces, and explicit lifecycle/gate visibility without turning the product into a noisy control room.

## Product Understanding

Sarathi is a governed orchestration system for real work execution. Its core value is not “templates”, “automation runs”, or a no-code builder. Its core value is that a task moves through a strict lifecycle with policy-governed routing, decomposition, execution, review, escalation, handoff, and learning.

That means the desktop must represent:

- lifecycle phase
- current gate and next action
- blocked and escalation state
- review and evidence posture
- checkpoint and handoff readiness
- provider and repository posture as supporting trust signals

The desktop should feel like a cockpit for strict execution flow, not a chat shell with some badges and not a generic operations dashboard.

## Scope

This pass includes both frontend and backend/API work where needed for desktop trust.

Primary scope:

- shell and information architecture cleanup
- workspace operational landing
- project overview and task selection
- task studio hardening
- inbox, agents, and settings reframing
- real persistence and projections for primary desktop surfaces
- policy/lifecycle/gate visibility improvements in API responses where needed

Out of scope:

- provider transport rewrite from CLI to API
- large CLI/TUI redesign
- marketplace/template-product expansion
- unrelated runtime refactors that do not improve desktop trust

## Design Principles

1. Workflow first
   - The desktop should always answer: what phase is this in, what is blocked, and what happens next?

2. Calm shell, dense studio
   - Workspace and shell surfaces should remain airy and premium.
   - Project and task surfaces should be denser, more operational, and more information-rich.

3. Policy appears at the moment of constraint
   - Policy pack behavior should be visible where it affects execution, not buried only in settings.

4. No fake cockpit
   - Primary surfaces should not pretend to be live if they are actually mock or local-only.
   - When the service is available, real service state must win.

5. Layered disclosure
   - Users should see a concise operational summary first.
   - More detailed lifecycle, evidence, and policy detail should open naturally from there.

## Information Architecture

The desktop should be organized around a simple ladder:

- `Workspace`
- `Project`
- `Task`

Supporting views:

- `Inbox`
- `Agents`
- `Settings`

Contextual views embedded inside project or task surfaces:

- lifecycle
- history
- usage
- checkpoints
- handoff

### Primary surfaces

#### Workspace

Purpose: answer “is this workspace healthy enough to work in?”

The workspace surface should show:

- workspace identity
- bootstrap and repository readiness
- provider readiness
- active projects
- recent interrupts or attention-needed items
- one dominant “next action” block

#### Project

Purpose: answer “which task should I enter next?”

The project surface should show:

- project summary
- active, blocked, done, and review-needed counts
- task list as the dominant element
- recent changes and pending approvals as secondary operational context

#### Task Studio

Purpose: answer “what is happening in this task, and what should happen next?”

The task studio should show, within five seconds:

- current lifecycle phase
- current gate state
- current owner/provider
- blocker or waiting reason
- next action

The task studio is the product centerpiece.

### Secondary surfaces

#### Inbox

This is not generic notifications. It is the human-attention queue.

It should aggregate:

- blocked tasks
- approvals needed
- failed reviews
- provider failures
- restart-ready checkpoints
- handoff-ready tasks

#### Agents

This is the operational provider/role surface.

It should show:

- provider health
- dispatch activity
- failures and degraded state
- role/provider posture
- recent execution flow, not decorative “team” UI

#### Settings

This is pure configuration and trust posture:

- provider configuration
- provider health checks
- repository action defaults
- workspace bootstrap and setup posture
- policy-related defaults that affect execution trust

## Surface Behavior

### Workspace surface

The workspace screen should be the calmest surface in the desktop.

Expected content:

- header with workspace identity and readiness posture
- repo/bootstrap status card
- provider health summary
- project list or grid with strong status cues
- recent interrupts feed
- one dominant next-action card

The screen should feel operational and premium, not empty or generic.

### Project surface

The project screen should stop reading as a generic “dashboard” and instead become a working overview.

Expected content:

- summary strip with active/blocked/done/review-needed counts
- compact “attention now” strip for interruptions
- task list as the primary working object
- direct task entry from each row/card
- recent events and checkpoint/restart visibility as supporting context

### Task Studio

The task studio should become the unmistakable Sarathi surface.

Expected content:

- lifecycle header with phase, gate, blocker, owner/provider, and next action
- graph pane
- selected unit or task detail pane
- timeline/panel feed
- evidence and review state
- checkpoint state and restart affordance
- handoff posture
- repository action posture

The current graph, packet, messages, review, checkpoint, and operations concepts should remain, but the hierarchy should be rebuilt so the current state is obvious immediately.

### Inbox / Agents / Settings

- Inbox becomes an action queue.
- Agents becomes a real provider health and dispatch surface.
- Settings becomes a pure configuration and trust page.

Any generic “workflow SaaS” leftovers should be removed or demoted.

## Policy Pack, Lifecycle, and Strict Workflow Expression

The desktop should expose Sarathi’s strict workflow as product structure, not as process jargon.

### Always-visible workflow state

Every task should have a clear lifecycle header or status cluster exposing:

- current phase
- current gate status
- blocked/waiting/review/handoff state
- current provider or responsible actor
- next required action

### Policy posture

Policy should appear where it constrains execution:

- repo action disabled by policy
- review evidence required
- escalation reason
- spec drift or review failure
- allowed repository action mode

### Layered policy detail

The UI should reveal policy at three levels:

1. top layer: operational summary
2. second layer: gate/evidence/review panel
3. third layer: raw metadata or detailed lifecycle trace when needed

This keeps the product strict without making it visually heavy.

## Data and Backend Requirements

Several current surfaces still mix real state with demo or local fallback behavior. This pass should harden that.

### Persistence trust

Required changes:

- real persisted project behavior where local-only project state still exists
- primary surfaces should use real service-backed data whenever the service is configured
- fallback demo state should remain only for offline or explicit demo scenarios

### Workspace and project projections

The service should provide enough structured data for:

- workspace readiness summary
- project counts by workflow state
- recent workspace/project interrupts
- provider health summaries
- repository/bootstrap summaries

### Task studio completeness

The task studio path should have real, structured snapshots for:

- task
- graph
- messages
- approval gates
- lifecycle events
- dispatches
- evidence
- reviews
- handoff
- task panel entries
- checkpoints
- operational summaries used by lifecycle/history/usage tabs

### Policy and gate visibility

Structured API state should expose, where needed:

- active gate
- evidence requirements
- review outcome and summary
- escalation reason
- repository action preference and scope
- checkpoint readiness and restart path

The frontend should not need to infer core workflow truth from partial metadata when the backend can project it directly.

## Frontend Requirements

### Shell cleanup

- finish the workspace-first shell
- remove dead or legacy route structures
- remove product cues that imply a marketplace or generic workflow product
- keep inbox/agents/settings as supporting surfaces

### Visual system

Use the existing calm premium shell direction as the base:

- quiet monochrome shell
- airy spacing on workspace surfaces
- restrained accent use
- denser premium rows/cards on project/task surfaces
- unified tokens across the shell

Do not revert to purple-gradient or generic AI-dashboard patterns.

### Interaction rules

- one dominant next action per task/workspace surface
- blocked and review-needed states must be unmistakable
- primary actions must be context-correct
- lifecycle state should update the layout hierarchy, not just a small badge

## Acceptance Criteria

### Product understanding

- A user can explain Sarathi as a governed orchestration system after one session.
- The desktop reads as `workspace -> project -> task`, not as a generic dashboard collection.

### Trust

- No primary workflow depends on mock or local-only behavior when real service state exists.
- Blocked, review, checkpoint, and handoff states are visible and actionable.
- Provider integrations continue to work through existing CLI-backed paths.

### Surface quality

- Workspace surface feels operational and calm.
- Project surface is task-first.
- Task Studio is the clear centerpiece.
- Inbox, Agents, and Settings each have a clear role and do not feel like filler.

### Technical quality

- `npm --prefix desktop run build` passes
- relevant Python service tests pass
- browser QA covers workspace -> project -> task -> checkpoint -> handoff
- 100% zoom / laptop viewport quality remains acceptable

## Execution Order

1. Harden data contracts for workspace/project/task reality.
2. Finish shell and information architecture cleanup.
3. Rebuild workspace and project surfaces on real data.
4. Polish the task studio into the main product experience.
5. Reframe inbox, agents, and settings as support surfaces.
6. Validate through build, tests, and browser QA.

## Non-Goals

- provider API migration
- major CLI/TUI changes
- marketplace/template strategy
- unrelated engine/runtime rewrites

## Summary

This design turns Sarathi desktop into a real orchestration studio:

- calm at the shell level
- strict and operational at the task level
- policy-aware without being visually heavy
- trustworthy because primary surfaces use real persisted service state

That is the minimum bar for calling the Sarathi desktop production-ready.
