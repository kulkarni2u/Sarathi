# Sarathi Electron Orchestrator Technical Requirements

## 1. Purpose

Sarathi Desktop is a local-first orchestration workbench for turning a human request into planned, delegated, reviewed, and completed work across multiple AI providers and subagents.

The product should combine three influences:

- Tolaria-style desktop calm: a file/workspace-oriented shell, clean navigation, focused panes, low-friction command entry, and a sense that work is durable and inspectable.
- The existing HTML Orchestrator screens: operational ticket board, usage statistics, agent lifecycle flow, dependency graph plus message split, and connected/live status.
- Sarathi's core identity: a policy-backed orchestrator that brainstorms, plans, decomposes, dispatches, monitors, reviews, learns, and asks the human for final approval before commit or PR actions.

The end product is not just a dashboard. It is a cockpit where the user collaborates with Sarathi, Sarathi creates structured tasks and subtasks, and agents/models execute those subtasks through explicit lifecycle and review gates.

## 2. Product Principles

Sarathi is the center of gravity. Codex, Claude, Copilot, and local agents are provider backends behind Sarathi's orchestration model, not disconnected tools.

Conversation creates structure. A task begins as a chat with Sarathi and becomes a persisted main task, dependency graph, subtask packets, lifecycle events, messages, reviews, and final evidence.

Every subtask must be self-contained. A subagent should receive enough goal, context, file hints, dependencies, workflow, review criteria, and expected evidence to start without rediscovering the whole project.

The interface should feel operational, not decorative. Prefer quiet light-mode admin ergonomics, clear status, compact controls, and high-density task information over generic AI-dashboard theatrics.

Everything important should be durable and inspectable. Task state, messages, dependencies, review verdicts, artifacts, provider dispatches, and SSE events should persist locally.

Complex work should be explainable visually. Sarathi should include a bundled diagram-generation capability based on the local `architecture-diagram` skill so tasks can produce dependency graphs, lifecycle maps, system architecture diagrams, review loops, and handoff visuals without relying on external design tools.

## 3. Primary User Flows

### 3.1 Start a New Task

The user can start a new task from the Task Dashboard via `New Task`.

The app opens a new task tab in a task-initiation workspace.

Sarathi starts the default orchestration conversation:

1. Brainstorm user intent.
2. Clarify success criteria and constraints.
3. Gather project context through subagents when needed.
4. Produce a plan/design.
5. Propose main task metadata and subtasks.
6. Ask for approval before posting subtasks to the local SQLite store.

After approval, Sarathi persists the main task, subtasks, dependencies, messages, lifecycle events, and review workflow definitions.

### 3.2 Open and Edit Existing Tasks

The Task Dashboard displays existing tasks/tickets as kanban cards and list rows.

Clicking a task opens it as a task tab.

Each task tab supports viewing and editing:

- Title and description.
- Acceptance criteria.
- Subtasks/units.
- Dependencies/blockers.
- Assigned agent/provider.
- Workflow definition.
- Messages.
- Evidence/artifacts.
- Review state.

### 3.3 Task Workspace

Each opened task appears as an independent tab. The tab remains separate from global dashboard views.

The task workspace contains:

- Task header with breadcrumb/back-to-board behavior.
- Graph/List toggle with graph as default.
- Dependency graph of subtasks/units.
- Subtask list table as alternate view.
- Task-scoped messaging area where user, Sarathi, and agents/models communicate.
- Message search.
- Composer with audience selection, such as all agents, Sarathi, selected subtask owner, or specific provider.
- Review and completion status.

The visual pattern should resemble the user's graph/message screen: compact graph on the left, conversation and search on the right, with minimal icon controls.

### 3.4 Subtask Lifecycle

Each subtask follows this core lifecycle:

1. `claim`
2. `in_progress`
3. `review`
4. `complete`

A subtask may also be:

- `blocked`
- `unblocked`
- `paused`
- `failed`
- `waiting_human`

Subtasks can block other subtasks. When blockers complete, the monitor should emit an unblock event and the orchestrator can dispatch the next eligible subtask.

### 3.5 Review Loops

Each subtask follows the workflow Sarathi assigns. Examples:

- Implementation workflow: TDD, implementation, build/test gate, self-review, submit.
- Code-review workflow: reviewer verdict, fix loop, re-review.
- QA workflow: acceptance coverage, behavior verification, test evidence.
- Functional review workflow: final acceptance criteria mapping and regression check.

Review loops continue until criteria are satisfied or the human intervenes.

When all subtasks are complete, Sarathi runs:

1. Overall code review.
2. Overall functional review.
3. Acceptance criteria coverage check.
4. Final evidence summary.

Only after these gates pass does Sarathi mark the main task ready for user review.

### 3.6 Final Handoff

When the main task is complete, Sarathi tells the user:

- What changed.
- Which subtasks completed.
- Which reviews passed.
- Which tests/checks ran.
- Any residual risks.

Sarathi then asks for explicit permission before commit, PR creation, publishing, or any repository integration step.

## 4. Information Architecture

The application shell should include persistent navigation inspired by the existing Orchestrator app:

- Dashboard
- History
- Agents
- Usage Stats
- Wiki or Knowledge
- Diagrams
- Settings

The global dashboard areas should be:

- Task Dashboard
- History List
- Agents Dashboard
- Agents Lifecycle
- Usage Statistics
- Settings

Task tabs are opened dynamically from the Task Dashboard and are independent of global navigation tabs.

## 5. Screen Requirements

### 5.1 Application Shell

The shell must include:

- Left sidebar with grouped navigation.
- Top bar with workspace title, command entry, live/SSE status, and quick actions.
- Footer/status area showing connected/live state, active sessions, workspace path, and current route.
- Theme support for light and dark mode.
- Minimal icon controls for graph/list, refresh, filter, sort, settings, and provider actions.

The default visual direction should be light-first and calm, with dark mode available.

### 5.2 Task Dashboard

The Task Dashboard must support:

- `New Task` action.
- Kanban board with columns such as `In Progress`, `Review`, `Paused`, and `Completed`.
- Task/ticket cards showing title, status, providers, age, message count, unit completion count, and assigned agents.
- Filtering by status, provider, owner, and tag.
- Sorting by recency, priority, blocked state, and review state.
- Clicking a card to open/edit the task as a task tab.

### 5.3 Task Detail Tab

Each task tab must support:

- Graph view as default.
- List view toggle.
- Dependency graph with unit nodes and edges.
- Node status styling for done, in progress, waiting, blocked, and failed.
- Provider/agent badges such as `CL`, `CO`, `CX`, or Sanskrit role names.
- Subtask lifecycle controls where permitted.
- Message search and task-scoped conversation.
- Composer for user-to-agent and agent-to-agent communication.
- Review loop progress.
- Final completion gate.

### 5.4 Orchestrator Chat

The Orchestrator Chat is the conceptual home of Sarathi.

It must support:

- Human-to-Sarathi conversation.
- Sarathi-to-human clarification questions.
- Model council messages from Disha, Vichara, Prajna, Pravaha, Nirnaya, Samanvaya, and other roles.
- Draft task/subtask proposals.
- Approval gates before persistence or execution.
- Links from messages to task graph nodes, artifacts, and review evidence.

### 5.5 Agents Dashboard

The Agents Dashboard must show:

- Active agents.
- Provider mapping.
- Health status.
- Current task/subtask assignment.
- Utilization.
- Success rate.
- Average execution time.
- Recent failures or waiting-human states.

Agents should be presented by Sarathi role and provider capability, not provider brand alone.

### 5.6 Agents Lifecycle

The Agents Lifecycle screen must include:

- Visual flow from task creation to PR-ready completion.
- Role cards explaining triggers and responsibilities.
- Orchestrator, monitor, implementer, reviewer, QA advocate, code-quality reviewer, and functional reviewer roles.
- Loop-back paths from review failure to implementation.
- Final human approval step before commit/PR.

The flow should borrow the clarity of the user's existing lifecycle screenshot.

### 5.7 Usage Statistics

Usage Statistics must include:

- Tickets completed.
- Units executed.
- Total tickets.
- Active tickets.
- Units completed by provider.
- Weekly ticket completion chart.
- Provider share chart.
- Agent leaderboard.
- Success rate, average time, and utilization per agent/provider.

### 5.8 History List

History must provide a chronological audit trail of:

- Task creation.
- Message events.
- Subtask lifecycle changes.
- Blocked/unblocked events.
- Provider dispatches.
- Review verdicts.
- Test/check results.
- Artifact updates.
- Final handoffs.

The list should be searchable and filterable.

### 5.9 Diagram Engine

Sarathi must bundle a first-class diagram-generation engine based on the `architecture-diagram` skill content.

The diagram engine must support:

- Generating standalone, self-contained HTML/SVG diagrams.
- Generating task dependency graphs from persisted `tasks`, `subtasks`, and `task_dependencies`.
- Generating agent lifecycle diagrams from the configured Sarathi roles and workflow policy.
- Generating architecture diagrams from workspace context, repo structure, and task evidence.
- Generating review-loop diagrams that show rejected, blocked, waiting-human, and completed paths.
- Reusing the skill design system: dark technical theme, JetBrains Mono, semantic colors, grid background, rounded components, arrows, legends, summary cards, and footer metadata.
- Saving generated diagrams as durable artifacts linked to a task, workspace, review run, or knowledge entry.
- Opening generated diagrams from Task Detail, Agents Lifecycle, History, and Knowledge views.
- Regenerating diagrams when task state changes, either manually or from SSE-triggered updates.

The bundled diagram templates should be versioned with the app so a workspace can reproduce older diagrams even after the default template evolves.

### 5.10 Settings

Settings must support:

- Codex CLI path and health check.
- Claude CLI path and health check.
- Copilot/GitHub auth status.
- Local provider fallback configuration.
- Default policy pack path.
- Workspace path.
- SQLite database location.
- SSE/event server configuration.
- Diagram engine template/version selection.
- Diagram artifact output location.
- Theme preference.
- Provider routing defaults.

Secrets must not be displayed in plain text.

## 6. Data Model Requirements

Sarathi Desktop must use a local SQLite database for durable app state.

Required entities:

- `workspaces`
- `tasks`
- `subtasks`
- `task_dependencies`
- `messages`
- `agents`
- `providers`
- `dispatches`
- `lifecycle_events`
- `review_runs`
- `review_findings`
- `artifacts`
- `diagram_artifacts`
- `acceptance_criteria`
- `settings`

### 6.1 Task

A task must include:

- `id`
- `title`
- `description`
- `status`
- `phase`
- `created_at`
- `updated_at`
- `completed_at`
- `workspace_id`
- `policy_pack_path`
- `acceptance_criteria`
- `final_review_state`
- `commit_pr_permission_state`

### 6.2 Subtask

A subtask must include:

- `id`
- `task_id`
- `title`
- `description`
- `status`
- `lifecycle_state`
- `assigned_role`
- `assigned_provider`
- `workflow_type`
- `context_packet`
- `expected_output`
- `evidence_requirements`
- `created_at`
- `updated_at`
- `completed_at`

### 6.3 Message

A message must include:

- `id`
- `task_id`
- `subtask_id` when relevant
- `sender_type`
- `sender_name`
- `provider`
- `body`
- `created_at`
- `visibility`
- `artifact_refs`
- `event_refs`

### 6.4 Lifecycle Event

A lifecycle event must include:

- `id`
- `task_id`
- `subtask_id`
- `event_type`
- `from_state`
- `to_state`
- `source`
- `payload`
- `created_at`

### 6.5 Diagram Artifact

A diagram artifact must include:

- `id`
- `workspace_id`
- `task_id` when task-scoped
- `review_run_id` when review-scoped
- `diagram_type`
- `title`
- `template_version`
- `source_context_hash`
- `html_path`
- `svg_snapshot_path` when exported
- `created_by`
- `created_at`
- `updated_at`

Supported `diagram_type` values should include `dependency_graph`, `agent_lifecycle`, `system_architecture`, `review_loop`, and `handoff_summary`.

## 7. Runtime and Backend Requirements

The desktop app should have an Electron main process and a local Sarathi service layer.

The service layer must expose:

- Task CRUD.
- Subtask CRUD.
- Dependency management.
- Message persistence.
- Agent/provider health checks.
- Sarathi CLI/task execution bridge.
- Diagram-generation service using the bundled architecture-diagram template pack.
- SSE event stream.
- Settings persistence.
- SQLite migrations.

The renderer should not call provider CLIs directly. Provider execution should go through Sarathi's service layer.

## 8. Event Streaming Requirements

The app must use SSE-style auto-updates for live state.

The event stream must include:

- `task.created`
- `task.updated`
- `task.completed`
- `subtask.created`
- `subtask.claimed`
- `subtask.in_progress`
- `subtask.blocked`
- `subtask.unblocked`
- `diagram.generated`
- `diagram.updated`
- `diagram.failed`
- `subtask.review_requested`
- `subtask.review_passed`
- `subtask.review_failed`
- `subtask.completed`
- `message.created`
- `provider.dispatch_started`
- `provider.dispatch_completed`
- `provider.dispatch_failed`
- `review.started`
- `review.completed`
- `artifact.created`

The UI should update without manual refresh, while retaining a manual refresh fallback.

## 9. Provider and Agent Requirements

Sarathi must support provider configuration for:

- Codex
- Claude
- Copilot
- Local command provider

Provider routing must be policy-backed. The UI should show the effective routing decision and the reason when available.

Sanskrit role names should remain the primary role vocabulary:

- Sarathi: orchestrator.
- Disha: planner.
- Vichara: researcher.
- Prajna: reasoner.
- Pravaha: executor.
- Nirnaya: reviewer.
- Samanvaya: coordinator.
- Sahayaka: support.
- Marga: routing.
- Sutra: workflow spine/message bus.

Provider labels may appear as badges, but the role model should remain provider-neutral.

## 10. UX and Visual Requirements

The interface should merge Tolaria and the existing Orchestrator HTML app:

- Use a calm desktop shell.
- Keep navigation clear and stable.
- Prefer light mode by default, with a polished dark mode.
- Use high-density cards and tables where operationally useful.
- Use graph views for dependencies and lifecycle because they are core to Sarathi.
- Keep messages adjacent to task graph context.
- Use minimal icon controls rather than large decorative buttons.
- Make status visible but quiet.
- Avoid generic AI-glow dashboard styling.

## 11. Non-Functional Requirements

The app must be local-first and work without cloud services for core task orchestration.

The app must avoid storing secrets in plaintext.

The app must preserve a complete audit trail of orchestration decisions.

The app must remain usable with large task histories through search, filters, and pagination/virtualization.

The app must fail safely. Provider failures should mark tasks/subtasks as failed or waiting-human, not silently disappear.

The app must support resumable task execution.

## 12. Acceptance Criteria

The first production-ready tranche is complete when:

- The app opens to the shell with dashboard, history, agents, lifecycle, usage stats, and settings navigation.
- The user can create a new task from the dashboard.
- New task creation starts in Sarathi Orchestrator Chat.
- Sarathi can draft subtasks and wait for approval before persistence.
- Approved subtasks are stored in SQLite.
- Existing tasks can be opened as task tabs.
- Task tabs show graph view by default and list view by toggle.
- Task tabs can generate/open a dependency graph diagram artifact.
- Agent lifecycle can generate/open a lifecycle diagram artifact.
- The app bundles the architecture-diagram skill template pack for complex diagrams.
- Task tabs include task-scoped messages.
- Subtask lifecycle states support claim, in progress, review, complete, blocked, and unblocked.
- Subtasks can depend on other subtasks.
- Review loops can send a subtask back to implementation.
- Overall code review and functional review run after all subtasks complete.
- Main task completion requires final user review and explicit commit/PR permission.
- SSE events update the UI without manual refresh.
- Provider settings can validate Codex, Claude, Copilot, and local provider availability.

## 13. Initial Implementation Slices

1. Electron shell and route structure.
2. SQLite schema and local task store.
3. Task Dashboard with kanban cards and task tabs.
4. Task workspace with graph/list toggle and message panel.
5. Sarathi task initiation flow and approval gate.
6. Subtask lifecycle/dependency engine.
7. SSE event stream.
8. Provider settings and health checks.
9. Agents lifecycle and usage stats.
10. Review loop and final handoff flow.

## 14. Open Design Decisions

- Whether task tabs persist across app restarts or only within the active session.
- Whether Wiki/Knowledge is a first-class MVP feature or a placeholder for later.
- Whether graph rendering should use a custom lightweight SVG/canvas layer or a graph library.
- Whether messages should support markdown, attachments, and code blocks in MVP.
- Whether provider dispatch should run inside the Electron main process, a child Python service, or a separate local daemon.
