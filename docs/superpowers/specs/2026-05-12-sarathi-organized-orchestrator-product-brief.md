# Sarathi Organized Orchestrator Product Brief

Date: 2026-05-12

Owner role: Product Owner

Product: Sarathi - Charioteer for AI Agents

Status: Proposed direction and release framing

Related artifacts:

- `docs/superpowers/specs/2026-04-27-sarathi-product-requirements.md`
- `docs/superpowers/specs/2026-05-09-sarathi-desktop-orchestration-studio-design.md`
- `docs/superpowers/specs/2026-05-10-sarathi-brainstorm-phase-design.md`
- `../product-owner/references/github-competitive-landscape.md`

## 1. Executive Summary

Sarathi should position itself as the organized control tower for AI-assisted delivery, not as a generic AI dashboard and not as a chat wrapper around coding agents.

The product win is not merely "run multiple agents." The win is:

- turn conversation into durable work objects
- route work through explicit queues and lifecycle states
- require visible review, evidence, and approval gates
- preserve resume, audit, and handoff integrity across desktop, CLI, and skill surfaces

This brief proposes a release sequence that makes Sarathi feel organized early, then deepens orchestration power over time.

## 2. Problem Statement

Today, many AI tools can generate code, plans, or workflows, but serious product and engineering teams still struggle with:

- weak traceability from request to outcome
- hidden or ambiguous execution state
- poor visibility into blocked or waiting-human work
- shallow review and approval controls
- weak resumability after interruptions
- final outputs that do not prove acceptance-criteria coverage

Sarathi should solve these by making work, not chat, the primary organizing model.

## 3. Product Goal

Sarathi helps a human convert rough intent into governed delivery.

The operator should be able to:

- capture an idea or request
- convert it into a work item, PRD, and acceptance criteria
- generate and approve a task graph
- watch execution move through explicit queues
- inspect evidence, reviews, and approvals
- resume or reroute interrupted work safely
- produce a final handoff packet with traceable completion proof

## 4. Competitive Takeaways

This proposal is informed by patterns visible in:

- [OpenHands](https://github.com/OpenHands/OpenHands): strong agent execution platform, model-agnostic runtime, CLI and web surface
- [Open Swarm](https://github.com/openswarm-ai/openswarm): local-first multi-agent orchestration and approval-oriented visibility
- [CLI Agent Orchestrator](https://github.com/awslabs/cli-agent-orchestrator): explicit supervisor-worker coordination primitives
- [Langflow](https://github.com/langflow-ai/langflow): graph and workflow inspection as first-class product behavior
- [Flowise](https://github.com/FlowiseAI/Flowise): reusable templates, workspaces, human-in-the-loop controls

### Table stakes Sarathi must meet

- workspace and provider configuration
- visible execution state and history
- retry and resume flows
- task or graph visualization
- approval and human-in-the-loop controls
- exportable artifacts and logs

### Differentiators Sarathi should own

- PRD to acceptance-criteria to review traceability
- approval and policy gates attached to real work objects
- evidence packs and final handoff artifacts
- consistent bridge across desktop UI, CLI, and skill-driven workflows
- organized operational queues rather than chat-first status guessing

## 5. Product Principles

- Work objects are first-class. Chat is input, not the system of record.
- Every major state change is visible, durable, and attributable.
- Human approvals are explicit, not implied.
- Reviews and evidence are required for trusted completion.
- Resume and recovery are core product behavior, not edge tooling.
- Policy and routing are visible operating controls.
- A serious operator should understand the system in minutes, not by reading prompts.

## 6. Canonical Object Model

Sarathi should standardize the following product objects:

- `workspace`: top-level operating boundary
- `initiative`: optional larger business objective or release container
- `project`: delivery grouping within a workspace
- `work_item`: durable unit created from a request or conversation
- `prd`: structured product or task intent
- `acceptance_criteria_set`: testable completion contract
- `task_graph`: dependency-aware execution plan
- `execution_unit`: graph node assigned to an agent, role, or provider
- `run`: concrete execution attempt against one or more units
- `review`: findings and verdicts against quality, policy, or acceptance criteria
- `approval`: human decision gate
- `artifact`: produced output
- `evidence_pack`: proof bundle tied to completion
- `checkpoint`: resumable continuation point
- `policy_pack`: rule and routing layer
- `provider_profile`: provider capabilities, health, and routing metadata
- `template`: reusable workflow or requirement starter
- `saved_view`: filtered lens for operators
- `handoff`: final delivery packet

### Object integrity requirements

- Every `work_item` must link to a workspace and lifecycle state.
- Every completion-capable object must record evidence and history.
- Every `run` must record who or what started it, what policy governed it, and what state it ended in.
- Every `approval` must record object, decision, actor, timestamp, and note.
- Every `handoff` must link back to PRD, acceptance criteria, reviews, and artifacts.

## 7. Queue and Lifecycle Model

Sarathi should expose these first-class operator queues:

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

### Lifecycle rule

No item should appear simply as "active" unless the detailed state is also visible. Ambiguous state labels make orchestrators feel chaotic.

## 8. Core Product Proposal

### Proposal A: Approval Inbox and Run Control Tower

Create a global operational surface for approvals, blocked items, failed runs, and resumable work.

Why this matters:

- makes the product feel organized quickly
- gives humans a clear control point
- prevents critical work from hiding inside task detail pages

Acceptance criteria:

- The desktop UI shows a unified inbox of pending approvals across workspaces.
- The operator can filter runs by `blocked`, `waiting_human`, `failed`, and `handoff_ready`.
- Each run row shows current state, last event, governing policy, and next safe action.
- A blocked or failed run links directly to its failure reason, checkpoint, and rerun options.
- CLI can list pending approvals and blocked runs in JSON and human-readable modes.

### Proposal B: PRD-to-Handoff Delivery Spine

Treat the request-to-delivery path as the backbone of Sarathi.

Why this matters:

- makes Sarathi more than an agent launcher
- creates a differentiated product story
- improves trust for product and engineering stakeholders

Acceptance criteria:

- A request can become a `work_item`, `prd`, and `acceptance_criteria_set` from one flow.
- Each acceptance criterion can be linked to graph units, reviews, and evidence.
- The system can show an acceptance-criteria coverage view before handoff.
- A final handoff cannot be marked complete without linked review verdicts and evidence.
- The handoff summary includes completed scope, unresolved issues, and follow-up recommendations.

### Proposal C: Canonical Object and State Discipline

Make object model clarity a product requirement, not just a design preference.

Why this matters:

- keeps the product coherent as features expand
- aligns desktop, CLI, and local service semantics
- reduces UI and API drift

Acceptance criteria:

- Every core object has documented states and valid transitions.
- Desktop, CLI, and service APIs use the same object names and lifecycle labels.
- Search, history, and audit views operate on canonical objects.
- Product surfaces never invent conflicting names for the same underlying object.

### Proposal D: Policy and Governance Visibility

Move policy posture, approval rules, and overrides into visible product behavior.

Why this matters:

- strengthens trust and safety
- distinguishes Sarathi from tools that hide orchestration logic
- helps teams govern real repositories and providers

Acceptance criteria:

- Each run shows governing policy pack and key approval posture.
- The operator can see when a route, retry, or override was automatic versus human-directed.
- Override events are visible in history and linked to affected objects.
- Repository-sensitive actions remain blocked until explicit approval is recorded.

### Proposal E: Templates, Saved Views, and Learnings

Turn repeated workflows into reusable operating assets.

Why this matters:

- improves week-two and week-ten usability
- reduces repetitive setup
- makes the product feel systematic rather than experimental

Acceptance criteria:

- Operators can save filtered views such as `needs approval`, `review failed`, and `high risk`.
- Workspace-level templates can seed PRDs, acceptance criteria, task graphs, and policies.
- Learnings can be recorded with provenance and reused in future work.
- New work can start from templates without breaking auditability.

## 9. Prioritized Epics

### Epic 1: Organized Control Tower

Outcome:
Operators can understand system state, approval load, blockers, and resumable work from one place.

Included capabilities:

- approval inbox
- run queue views
- state filters
- blocker and failure detail
- checkpoint visibility

### Epic 2: Delivery Traceability Spine

Outcome:
Every work item remains traceable from request through PRD, acceptance criteria, execution, review, and handoff.

Included capabilities:

- work item creation from conversation
- PRD and AC object model
- AC mapping to graph and evidence
- handoff summary generation

### Epic 3: Canonical Lifecycle Platform

Outcome:
Desktop, CLI, and service share one object model and one lifecycle language.

Included capabilities:

- canonical object schemas
- state machine definitions
- aligned API naming
- lifecycle-aware search and history

### Epic 4: Governance and Policy Posture

Outcome:
Operators understand how policies govern execution and can inspect approvals, overrides, and sensitive actions.

Included capabilities:

- policy posture panels
- override history
- approval enforcement visibility
- repository action gating

### Epic 5: Reuse and Organizational Memory

Outcome:
Sarathi becomes more useful over time through templates, saved views, and proven learnings.

Included capabilities:

- templates
- saved views
- learnings with provenance
- workflow presets

## 10. Release Sequence

### Release 1: Foundation and Control

Goal:
Make Sarathi feel coherent and trustworthy in daily operation.

Scope:

- canonical objects and lifecycle labels
- control tower with approval inbox and run states
- checkpoint visibility
- blocked and failed run inspection

Exit criteria:

- Operators can answer what exists, what is blocked, what needs approval, and what can resume.

### Release 2: Traceable Delivery

Goal:
Make Sarathi own the request-to-handoff spine.

Scope:

- work item to PRD flow
- acceptance criteria object model
- AC coverage view
- evidence pack and handoff summary

Exit criteria:

- A delivered item can prove what was requested, what was accepted, and what evidence supports completion.

### Release 3: Governance Depth

Goal:
Make policy and approval posture visible and dependable for serious repositories.

Scope:

- policy posture visibility
- override history
- provider-routing transparency
- repository action governance

Exit criteria:

- Sensitive actions and overrides are easy to inspect and audit.

### Release 4: Reuse and Scale

Goal:
Reduce repeated setup and support team-level operating discipline.

Scope:

- templates
- saved views
- learnings and provenance
- organizational workflow presets

Exit criteria:

- Teams can reuse successful orchestration patterns without losing traceability.

## 11. Product Risks

- Sarathi may over-expand UI surfaces before locking object semantics.
- The product may drift back toward chat-first interaction if work objects are weak.
- Queue complexity may overwhelm new users unless defaults and saved views are excellent.
- Governance features may become confusing if approval posture is not explained clearly.
- Desktop and CLI may diverge unless API and lifecycle naming stay strict.

## 12. Out of Scope For Near-Term Execution

- full enterprise RBAC model
- remote multi-user collaboration as the primary mode
- autonomous repository mutation without human approval
- marketplace-style public sharing ecosystem
- broad analytics platform beyond operational metrics needed for orchestration

## 13. Recommendation

The next best product move is not adding more isolated screens. It is making Sarathi operationally legible.

If the team has to choose one flagship direction, it should be:

`Sarathi as the organized orchestration control tower with explicit approvals, visible queues, durable traceability, and evidence-backed handoff.`
