# Sarathi Product Requirements

Date: 2026-04-27

Owner role: Product Owner

Product: Sarathi - Charioteer for AI Agents

Related artifacts:

- `README.md`
- `IMPLEMENTATION_TRACKER.md`
- `docs/superpowers/specs/2026-04-26-sarathi-electron-orchestrator-requirements.md`
- `.superpowers/brainstorm/26677-1777247112/content/sarathi-electron-full-product-mockup.html`

## 1. Product Vision

Sarathi should become the orchestration cockpit for serious AI-assisted work: a local-first desktop and CLI platform where a human describes an outcome, Sarathi converts that outcome into structured PRDs, acceptance criteria, task graphs, agent assignments, execution loops, reviews, evidence, and final delivery requests.

The product must stand apart from generic AI chat tools by making AI work inspectable, durable, resumable, auditable, and review-driven.

Sarathi is not only a CLI and not only a skill. The end product is a coordinated ecosystem:

- CLI: automation engine, policy runner, resumability, validation, headless execution.
- Skill: portable orchestration protocol that Codex, Claude, Copilot, and other agents can follow.
- Desktop UI: calm cockpit for humans to plan, approve, monitor, inspect, and govern work.
- Local service: SQLite-backed runtime, SSE stream, provider bridge, artifact store, and task graph scheduler.

## 2. Positioning

Sarathi is the missing operating layer between human intent and multiple AI agents.

Competing tools often focus on one model, one chat thread, or one coding session. Sarathi should focus on the work itself: task lifecycle, dependencies, evidence, review loops, policy, and final accountable handoff.

Product tagline: `Charioteer for AI Agents`.

Core promise: `Conversation turns into orchestrated work`.

## 2.1 North Star Metrics

Primary north star:

- Percentage of orchestrated tasks that reach reviewed handoff with linked PRD/AC evidence and no missing audit trail.

Supporting product metrics:

- Time from rough request to approved task graph.
- Percentage of subtasks with complete context packets before dispatch.
- Percentage of completed subtasks with required evidence attached.
- Review rejection rate by provider, role, workflow, and policy pack.
- Human intervention rate for blocked, failed, or waiting-human states.
- Resume success rate after app restart or interrupted execution.
- Percentage of final handoffs with explicit AC coverage matrix.
- User override rate for policy, review, or provider routing decisions.

Quality guardrails:

- No repository mutation without recorded human approval.
- No completed task without final handoff artifact.
- No provider fallback without an event in history.
- No accepted learning proposal without evidence references.

## 3. Personas

### 3.1 Solo Builder

Wants to use Codex, Claude, Copilot, local scripts, and custom agents without manually coordinating context across tools.

Success means they can start a feature, approve a plan, let agents work, inspect progress, and get a final reviewed result.

### 3.2 Staff Engineer / Tech Lead

Wants AI work to follow team conventions, include AC coverage, avoid uncontrolled changes, and produce reviewable evidence.

Success means policy packs, review gates, dependency graphs, and final handoff summaries make AI work safe enough for real repositories.

### 3.3 Team / Org Admin

Wants reproducible workspace setup, provider configuration, policy templates, audit history, and secure local defaults.

Success means teams can onboard quickly, reuse policy packs, connect providers safely, and audit all orchestration decisions.

### 3.4 Agent Author

Wants to integrate a new model, CLI, or hosted service into Sarathi’s routing layer.

Success means provider adapters expose health, capabilities, dispatch, evidence, and failure semantics without changing the orchestration model.

### 3.5 Product Owner / Program Lead

Wants features, bugs, releases, and initiatives to stay traceable from intent through PRD, ACs, execution, review, and release communication.

Success means Sarathi can generate and maintain PRDs, AC matrices, dependency maps, and progress summaries that product and engineering can both trust.

## 4. Product Principles

- Workspace is the first-class citizen. Users start by creating or selecting a workspace, and every inbox item, task, provider route, policy pack, repository, artifact, learning, and dashboard view is scoped to that workspace.
- Local-first by default.
- Human approval before persistence-sensitive or repository-mutating actions.
- Policy drives orchestration behavior, not hidden prompts.
- Every task and subtask must have durable context, status, evidence, and review state.
- Providers are interchangeable backends; Sarathi roles are the primary mental model.
- Agents should receive complete task packets so they do not rediscover context.
- Failed, blocked, and waiting-human states must be explicit, not silent.
- Reviews must loop until evidence satisfies acceptance criteria or the human intervenes.
- Visual explanation is first-class: dependency graphs, lifecycle maps, architecture diagrams, and review flows.

## 5. Product Surfaces

### 5.1 CLI

The CLI remains the automation backbone.

Required commands:

- `sarathi init`
- `sarathi validate`
- `sarathi run`
- `sarathi list`
- `sarathi status`
- `sarathi resume`
- `sarathi log`
- `sarathi proposals`
- `sarathi agents`
- `sarathi workspace`
- `sarathi providers`
- `sarathi diagrams`

Command maturity:

- Existing CLI commands such as `init`, `validate`, `run`, `list`, `status`, `resume`, `log`, `proposals`, and `agents` define the current baseline.
- `workspace`, `providers`, and `diagrams` are product requirements for the desktop/local-service era and should be introduced without breaking existing command behavior.
- New commands must have JSON output modes for desktop/local-service integration.

CLI acceptance criteria:

- A user can run Sarathi headlessly without the desktop app.
- Desktop and CLI share policy pack semantics.
- CLI-generated tasks can be opened in the desktop app.
- Desktop-created tasks can be resumed by CLI.
- CLI output is concise but links to durable logs and artifacts.

### 5.2 Skill

The skill is the portable behavior contract for agent environments.

Required capabilities:

- Explain the Sarathi lifecycle.
- Use Sanskrit role names consistently.
- Instruct agents to produce PRDs, ACs, task packets, and evidence.
- Support sub-agent dispatch patterns.
- Support policy-backed routing.
- Preserve the same phase language as the CLI and desktop UI.

Skill acceptance criteria:

- Codex can use the skill to perform Sarathi-style orchestration inside any repo.
- Copilot agent mode can discover Sarathi through `AGENTS.md`.
- Claude or other assistants can follow the same lifecycle from the skill text.
- Skill updates remain compatible with CLI policy pack concepts.

### 5.3 Desktop UI

The desktop UI is the primary human cockpit.

Required areas:

- Orchestrator chat.
- Workspaces.
- Task dashboard.
- Task detail tabs.
- Dependency graph.
- Agents dashboard.
- Agent lifecycle.
- History.
- Usage statistics.
- Diagram center.
- Settings.

Desktop acceptance criteria:

- The user always knows current workspace, route, connection state, storage state, and stream state.
- Every major object is clickable: workspace, task, subtask, dependency, agent, provider, review, artifact, diagram.
- SSE updates keep boards, graphs, messages, and status indicators current without manual refresh.
- The UI feels calm, professional, and operational rather than generic AI-dashboard themed.

Default sidebar navigation:

| Order | Item | Default view | Primary objects |
| --- | --- | --- | --- |
| 1 | Orchestrator | New/current orchestration chat | Work item, PRD, ACs, approvals |
| 2 | Inbox | Raw captured items | Inbox item, source attachment |
| 3 | Tasks | Workspace task board | Work item, task, subtask |
| 4 | Views | Saved filtered views | Saved view, task, subtask |
| 5 | Workspaces | Workspace switcher/settings | Workspace, repository, policy pack |
| 6 | Agents | Agent/provider dashboard | Role, provider, dispatch |
| 7 | Lifecycle | Agent lifecycle map | Role, workflow, review loop |
| 8 | History | Audit trail | Event, artifact, review, dispatch |
| 9 | Diagrams | Generated visual artifacts | Diagram, task, workspace |
| 10 | Usage Stats | Operational metrics | Provider, task, dispatch |
| 11 | Settings | Setup and configuration | Provider, policy, storage, appearance |

Screen interaction requirements:

| Screen | Entry path | MVP critical interaction |
| --- | --- | --- |
| Orchestrator chat | Left nav `Orchestrator` or `New Task` | Create structured work item plus PRD/AC draft from conversation. |
| Inbox | Left nav `Inbox` | Capture raw item and convert it into a work item draft. |
| Tasks dashboard | Left nav `Tasks` | Filter by phase/state and open task detail. |
| Task detail | Click task card/tab | Switch between graph, list, messages, evidence, and review panels. |
| Workspaces | Left nav `Workspaces` | Create workspace and attach repositories. |
| Agents | Left nav `Agents` | Test provider health and inspect role/provider assignments. |
| Lifecycle | Left nav `Lifecycle` | Inspect role flow and rejected-review loop. |
| History | Left nav `History` | Filter audit trail by task/provider/event type. |
| Diagrams | Left nav `Diagrams` or task actions | Open generated dependency/lifecycle diagrams. |
| Settings | Left nav or top-right icon | Configure providers, policy pack, storage, SSE, and appearance. |

### 5.4 Local Service

The local service coordinates state between UI, CLI, providers, and SQLite.

Required capabilities:

- SQLite persistence.
- SSE event stream.
- Provider health checks.
- Provider dispatch bridge.
- Task graph scheduling.
- Review loop coordination.
- Artifact and diagram generation.
- Safe repository action mediation.

Service acceptance criteria:

- Renderer never executes provider CLIs directly.
- Service records all state transitions.
- Service can resume after app restart.
- Service exposes a typed API that CLI and UI can share.

### 5.4.1 Local API Boundary

The desktop app, CLI, and skill-driven automation must communicate through a stable local API/service boundary wherever possible.

Required API groups:

- Workspace API: create, update, archive, list, select, validate repos.
- Vault API: sync file-backed artifacts, read/write workspace guide files, export dossiers.
- Provider API: configure, test, health, capabilities, dispatch.
- Task API: create, update, list, open, archive, search.
- Inbox API: capture raw items, classify, convert to work item.
- Saved Views API: create, update, list, apply workspace filters.
- PRD/AC API: draft, approve, version, map, export.
- Properties API: read/update metadata across workspaces, tasks, subtasks, artifacts, and reviews.
- Graph API: generate, update, validate dependencies, schedule ready units.
- Message API: send, search, subscribe, attach artifacts.
- Review API: create run, record findings, verdict, loop, override.
- Artifact API: save, fetch, link, export, redact.
- Diagram API: generate, refresh, open, export.
- Approval API: request, approve, reject, expire, audit.
- Event API: SSE subscribe, replay, checkpoint.

Acceptance criteria:

- API responses include object IDs, correlation IDs, and typed error codes.
- Long-running provider calls return dispatch IDs and stream progress events.
- UI actions are recoverable after service restart.
- CLI can call the same service APIs when running in desktop-connected mode, but can still run standalone.

## 5.5 Product Object Hierarchy

Sarathi must use consistent object language across CLI, skill, desktop UI, SQLite, logs, and artifacts.

Hierarchy:

- Workspace: orchestration boundary containing one or more repositories, policy pack, providers, settings, task history, and diagram artifacts.
- Project: optional grouping inside a workspace for an initiative, product area, release train, or customer effort.
- Work item: feature, bug, task, spike, chore, incident, release, or documentation item.
- Main task: the orchestrated executable unit created from a work item.
- Subtask/unit: graph node assigned to a Sarathi role and provider.
- Task packet: self-contained context bundle sent to an agent/provider.
- Dispatch: one execution attempt against a provider.
- Evidence artifact: output proving what happened.
- Review run: structured verification pass over task, subtask, diff, evidence, or ACs.
- Handoff: final user-facing completion package and repository-action permission gate.

Workspace-owned surfaces:

- Inbox.
- Orchestrator chat.
- Task dashboard.
- Saved views.
- Agents/provider routing.
- Policy pack.
- Workspace vault and wiki.
- Linked repositories.
- Diagrams.
- History.
- Usage statistics.
- Learning records and `learnings.md`.
- Settings.

Acceptance criteria:

- Every UI label maps to one of these objects.
- CLI command output uses the same object names.
- Events reference object IDs consistently.
- Task graph nodes always reference their parent work item and workspace.
- No task, inbox item, dispatch, review, diagram, or learning record exists without a workspace ID.

UI treatment:

| Object | Left nav? | Detail page? | Panel/tab only? | Notes |
| --- | --- | --- | --- | --- |
| Workspace | Yes | Yes | No | Workspace switcher plus setup/detail page. |
| Inbox item | Yes, through Inbox | Yes for converted item | Yes for capture preview | Raw capture can remain lightweight. |
| Saved view | Yes, through Views | Optional | Yes | Views are filtered task lists. |
| Work item / task | Yes, through Tasks | Yes | No | Primary tabbed work surface. |
| Subtask/unit | No | Optional later | Yes | MVP shows in task graph/list and inspector. |
| Provider | Yes, through Agents/Settings | Yes | Yes | Provider detail can mature after MVP. |
| Policy pack | Yes, through Settings/Workspaces | Yes | Yes | MVP can start read-only. |
| Dispatch | No | No | Yes | Visible inside task/provider panels. |
| Evidence/artifact | No | Optional later | Yes | Attached to task, review, message, handoff. |
| Review run | No | Optional later | Yes | Appears inside task detail and history. |
| Diagram | Yes, through Diagrams | Yes | Yes | Can open standalone artifact. |
| Handoff | No | Yes inside task | Yes | Final completion package. |

## 5.6 Human Approval Gates

Sarathi must make approval gates explicit and visible.

Required gates:

- Setup gate: user approves provider and repository access scope.
- Intake gate: user approves work item classification and scope.
- PRD/AC gate: user approves requirements before execution for medium/high complexity work.
- Task graph gate: user approves subtasks, dependencies, owners, and providers.
- Execution gate: user approves any command class that policy marks as risky.
- Review override gate: user approves force-complete or hard-stop override.
- Repository action gate: user approves commit, push, PR, release, or external status update.

Acceptance criteria:

- Each approval records approver, timestamp, object, decision, and optional note.
- The UI shows pending approvals as first-class blockers.
- CLI can list pending approvals for headless workflows.
- A task cannot skip a required gate unless policy explicitly allows the skip and records it.

MVP approval enforcement:

| Gate | MVP enforcement | Trigger |
| --- | --- | --- |
| Setup | Required | Provider or repository scope changes. |
| Intake | Required | New work item classification. |
| PRD/AC | Required for medium/high feature or bug work | Complexity threshold or work item type. |
| Task graph | Required when graph has more than 1 subtask | Multi-unit orchestration. |
| Execution | Required only for policy-marked risky commands | Destructive, network, install, write outside repo. |
| Review override | Required | Force-complete, hard-stop override, unresolved critical finding. |
| Repository action | Always required | Commit, push, PR, release, external update. |

MVP can simulate lower-risk approvals by recording auto-approved decisions when policy allows it. Simulated approvals must still be visible in history.

## 5.7 Repository And Git Workflow

Sarathi must treat repository state as a governed resource.

Functional requirements:

- Detect dirty worktrees before execution.
- Distinguish user changes from Sarathi-created changes when possible.
- Support branch selection or branch creation per task.
- Record base commit, current commit, branch, remote, and changed files.
- Show conflicts, untracked files, and generated files before commit/PR.
- Support no-commit, commit-only, draft PR, ready PR, and patch export handoff modes.
- Never revert user changes without explicit approval.

Acceptance criteria:

- Task start warns when linked repos have unrelated dirty changes.
- Each subtask records changed files and repository path.
- Final handoff separates user pre-existing changes from Sarathi changes when detectable.
- Commit/PR action requires final approval and current Git status snapshot.
- If Git state changes externally during a task, Sarathi emits a conflict/warning event.

## 5.8 Offline, Degraded, And Recovery Modes

Sarathi must remain useful when providers, network, or SSE are unavailable.

Functional requirements:

- Support planning-only mode with no providers connected.
- Support manual dispatch when automatic provider execution is unavailable.
- Support SSE fallback polling.
- Support paused tasks that can resume after app restart.
- Support provider-disabled and provider-offline states.
- Support export of PRD, ACs, graph, and handoff even without execution.

Acceptance criteria:

- Offline provider status does not block workspace setup unless required by policy.
- UI clearly shows degraded mode and what actions remain available.
- Paused tasks preserve graph state, messages, artifacts, approvals, and pending work.
- Recovery flow suggests next action: retry, re-route, manual complete, wait, or cancel.

## 5.9 Workspace Vault And AI-Readable Files

Sarathi should borrow Tolaria's strongest product mechanic: work remains useful as files, not only as app state.

Functional requirements:

- Each workspace can have a Sarathi vault folder.
- Vault contains readable Markdown/JSON exports for PRDs, ACs, task packets, reviews, diagrams, handoffs, learnings, and policy refs.
- Workspace root can include `SARATHI.md` as an AI-readable guide.
- Workspace vault includes a wiki/knowledge area for repository summaries, architecture notes, coding standards, guidelines, decisions, and learnings.
- Repo-local integrations can continue using `AGENTS.md`; Sarathi should be able to generate or update it with user approval.
- File-backed vault artifacts include stable IDs that link back to SQLite records.
- Users can open vault files in external editors without breaking Sarathi.

`SARATHI.md` should include:

- Workspace purpose.
- Linked repositories.
- Policy pack location.
- Agent role names and responsibilities.
- Task packet format.
- Review and evidence rules.
- Safe command rules.
- How Codex, Claude, Copilot, and local agents should consume the workspace.

Workspace vault structure:

```text
.sarathi/
  workspace.json
  SARATHI.md
  wiki/
    overview.md
    architecture.md
    repositories.md
    coding-standards.md
    guidelines.md
    decisions.md
  policy-pack/
  inbox/
  tasks/
  diagrams/
  handoffs/
  learnings.md
```

Acceptance criteria:

- A workspace can be understood by an external AI CLI from `SARATHI.md` plus exported task files.
- Vault sync never overwrites user-edited files without conflict handling.
- SQLite remains source of truth for runtime state, while vault files provide portability and inspectability.
- Exported files are redacted according to security settings.
- `learnings.md` is workspace-scoped and updated through the Sarathi learn/evolve loop with evidence references.

## 5.10 Inbox, Saved Views, And Archive

Sarathi should support Tolaria-style capture and retrieval so nothing starts as a perfect task.

Functional requirements:

- Inbox captures raw ideas, screenshots, logs, pasted bug reports, issue links, meeting notes, voice/text snippets, and files.
- Inbox items can be classified into work item types.
- Inbox items can be merged, split, archived, or converted into PRD/task drafts.
- Saved views expose filtered task/workspace states such as blocked units, needs approval, waiting human, review failed, ready for PR, high risk, provider failures, and my active tasks.
- Archive preserves completed, cancelled, duplicate, and no-longer-planned work without deleting history.

Acceptance criteria:

- Inbox item conversion preserves the source reference.
- Saved views are workspace-scoped and can be pinned in navigation.
- Archive search includes tasks, messages, artifacts, reviews, diagrams, and handoffs.
- Archived tasks cannot execute unless explicitly restored.

## 5.11 Properties, Wikilinks, And Context Mentions

Sarathi should make task metadata and context linking as easy as note-taking.

Functional requirements:

- Every major object has editable properties: type, status, priority, owner, provider, role, repo, branch, risk, AC coverage, policy pack, due date, tags, and source.
- A properties panel shows and edits metadata for the selected task, subtask, message, artifact, review, provider, or diagram.
- Messages and PRDs support wikilinks/context mentions such as `[[task:MAIN-042]]`, `[[unit:unit-4]]`, `[[AC-03]]`, `[[repo:Sarathi/src/engine.py]]`, and `[[policy:review]]`.
- Context mentions resolve into task packets and provider prompts.
- Broken links are visible and repairable.

Acceptance criteria:

- Properties can be edited without opening modal-heavy workflows.
- Wikilinks are searchable and navigable.
- Context mentions preserve stable object IDs even if display names change.
- Agent dispatch receives resolved context, not raw unresolved link text.

## 5.12 Command Palette And Quick Prompt

Sarathi should have a fast Tolaria-like command layer for power users.

Functional requirements:

- `Cmd+K` opens command palette.
- Quick prompt mode can address Sarathi, current task agents, selected agents, or a specific role.
- Command palette supports workspace, task, provider, review, diagram, and settings actions.
- Palette commands can include context mentions.
- Recent and suggested commands adapt to current screen and selected object.

Example commands:

- Create task from inbox.
- Generate PRD.
- Generate ACs.
- Ask Nirnaya to review.
- Show blockers.
- Dispatch ready units.
- Generate dependency diagram.
- Export task dossier.
- Create draft PR summary.
- Open workspace vault.

Acceptance criteria:

- Core workflows can be triggered from command palette.
- Commands show required approvals before execution.
- Failed commands produce actionable messages.
- Palette remains usable without provider connections.

## 5.13 Attachments, Dossiers, And Decision Records

Sarathi should treat evidence as product memory.

Functional requirements:

- Attachments support screenshots, logs, diffs, test output, diagrams, markdown, JSON, recordings, and generated files.
- Attachments can be linked to tasks, subtasks, messages, reviews, ACs, and handoffs.
- Task dossier export creates a single Markdown package with PRD, ACs, task graph, unit packets, messages, evidence, reviews, diagrams, commands, risks, and handoff.
- Decision records capture major choices made during planning/review, including alternatives and rationale.
- Snapshots can freeze task state before major transitions such as execution start, review start, and final handoff.

Acceptance criteria:

- Attachments are searchable by task, type, source, and phase.
- Dossiers can be regenerated and diffed across versions.
- Decision records link to the messages/artifacts that justified the decision.
- Snapshot restore never mutates repositories automatically; it restores Sarathi state only unless user approves repository actions.

## 5.14 Role And Provider Execution Model

Sarathi must make the distinction between orchestration roles and execution providers concrete.

Role-to-provider mapping:

| Sarathi role | Responsibility | Typical providers/tools |
| --- | --- | --- |
| Sarathi | Orchestrates user conversation and gates | Local service, Codex, Claude |
| Disha | Plans route, phases, task graph | Claude, Codex |
| Vichara | Gathers repository/context evidence | Codex, Copilot, local grep/index tools |
| Prajna | Evaluates tradeoffs and risk | Claude, Codex |
| Marga | Selects provider and workflow route | Local policy engine |
| Sutra | Coordinates graph state and SSE events | Local service/scheduler |
| Pravaha | Executes implementation units | Codex, Copilot, local shell |
| Nirnaya | Reviews code, QA, AC coverage | Claude, Codex, static tools |
| Samanvaya | Coordinates final handoff | Local service, Codex |
| Sahayaka | Handles support/unblocking tasks | Any available provider |

Example feature flow:

1. Sarathi captures user intent and opens the PRD/AC gate.
2. Disha drafts phases and a task graph.
3. Vichara gathers repo context and relevant files.
4. Prajna checks risk, alternatives, and rollback options.
5. Marga maps units to providers.
6. Sutra dispatches unblocked units.
7. Pravaha executes implementation tasks, often through Codex or Copilot.
8. Nirnaya reviews code, QA evidence, and AC coverage, often through Claude/Codex.
9. Samanvaya prepares final handoff and asks for repository action approval.

Example bug flow:

1. Sarathi captures observed/expected behavior and reproduction gaps.
2. Vichara gathers logs, suspected files, and prior history.
3. Disha creates diagnosis, fix, regression-test, and review units.
4. Pravaha executes the fix.
5. Nirnaya verifies regression evidence and rejects if reproduction is not covered.
6. Samanvaya summarizes fix, risk, and handoff options.

UI acceptance criteria:

- Task detail shows a role lane and provider lane for each subtask.
- Provider badges never replace Sarathi role names.
- Dispatch records explain why a provider was selected for a role.

## 6. End-To-End Product Phases

### Phase 0: Acquisition And Installation

Goal: Make Sarathi easy to install as CLI, skill, and desktop app.

Functional requirements:

- Provide install paths for Python CLI, desktop app, and skill pack.
- Detect Python, Git, Node/Electron runtime when relevant, and provider CLIs.
- Support global skill installation for Codex/Copilot-style environments.
- Support repo-local installation through `AGENTS.md`.
- Provide a first-run diagnostic command.

User stories:

- As a solo builder, I can install Sarathi and verify it works in less than ten minutes.
- As a team admin, I can document one standard installation path for my team.
- As an agent user, I can install the skill into my AI tool without manually copying scattered instructions.

Acceptance criteria:

- `sarathi --help` works after CLI install.
- Desktop first launch detects whether CLI is installed.
- Skill installation status is visible in Settings.
- The app can show missing prerequisites with actionable fix instructions.
- Installation never requires secrets to be entered into plaintext files.

Priority:

- MVP: CLI install, skill install instructions, desktop detection.
- V1: signed desktop installer, guided setup wizard.
- V2: team-managed distribution and policy pack templates.

### Phase 1: First Launch And Setup

Goal: Turn a blank environment into a ready Sarathi cockpit.

Functional requirements:

- Show first-run setup wizard.
- Configure default storage location.
- Require the user to create or select a workspace before accessing orchestration, inbox, task dashboard, agents, history, diagrams, or learnings.
- Validate CLI availability.
- Validate policy pack availability.
- Configure providers.
- Configure theme, transparent nav, and update behavior.
- Explain local-first storage and privacy defaults.

User stories:

- As a new user, I understand what Sarathi is before connecting providers.
- As a cautious user, I know where data is stored and what commands can run.
- As a power user, I can skip wizard steps and configure manually.

Acceptance criteria:

- First launch can finish with only local CLI and no external provider.
- First launch cannot create tasks outside a workspace.
- The first successful setup ends on a workspace home screen, not a global dashboard.
- Setup wizard can be reopened from Settings.
- Each setup section has a status: ready, warning, missing, or blocked.
- Setup state persists per machine and workspace.
- User can export a setup report for debugging.

Priority:

- MVP: setup checklist in Settings.
- V1: guided wizard.
- V2: import/export setup profiles.

### Phase 2: Provider Connection

Goal: Connect Codex, Claude, Copilot, local scripts, and future providers through one provider model.

Functional requirements:

- Support provider records with name, type, path, auth status, health, capabilities, and last check.
- Support provider capability flags: planning, coding, review, research, shell, git, repo-aware, multimodal, browser, diagramming.
- Provide `Test connection` per provider.
- Allow provider routing defaults by workspace and task type.
- Allow provider fallback ordering.
- Track provider execution cost, duration, errors, and evidence returned.

Provider-specific requirements:

- Codex: coding, repo-aware execution, review, local workspace operations.
- Claude: critique, reasoning, long-context planning/review, optional CLI bridge.
- Copilot: GitHub/repo-aware assistance, code suggestions, PR context, agent-mode integration.
- Local: shell commands, test runners, linters, scripts, deterministic providers.
- Future hosted providers: adapter-based with health, dispatch, streaming, and evidence contract.

User stories:

- As a user, I can see if Codex, Claude, and Copilot are configured and healthy.
- As a lead, I can route review to a different model than implementation.
- As an admin, I can disable a provider for a workspace.

Acceptance criteria:

- Provider test returns success/failure with actionable detail.
- Provider failure marks affected tasks as failed, retryable, or waiting-human.
- Routing never silently falls back without logging.
- Provider capabilities are visible before assigning work.
- Provider credentials are never shown in plaintext.

Priority:

- MVP: provider records, health status, manual configuration.
- V1: routing rules and fallback.
- V2: hosted adapters, cost controls, quota-aware routing.

### Phase 3: Workspace Creation

Goal: Make a workspace the durable boundary for repos, policies, providers, tasks, and history.

Functional requirements:

- Create workspace with name, description, icon, storage path, and default policy pack.
- Attach one or more repositories to a workspace.
- Adding a repository triggers a Sarathi repository initialization/intake flow.
- Validate repo paths, Git status, default branches, remotes, and write permissions.
- Associate workspace with SQLite database.
- Associate workspace with provider routing defaults.
- Associate workspace with diagram output path.
- Generate or update workspace wiki, policy pack, coding standards, guidelines, and `SARATHI.md`.
- Support workspace switcher and workspace-scoped navigation.

Repository initialization modes:

- Existing repository: Sarathi inspects files, README/docs, package metadata, tests, conventions, existing agents docs, and scripts; then drafts wiki pages, policy pack, coding standards, guidelines, and repo summary.
- Brand-new repository: Sarathi interviews the user about language/framework, architecture, coding standards, test commands, review rules, branching, release process, and AI-agent constraints; then creates initial wiki pages, policy pack, coding standards, and guidelines.
- Existing Sarathi-enabled repository: Sarathi validates current `.sarathi`, `SARATHI.md`, `AGENTS.md`, policy pack, and learnings; then proposes updates instead of overwriting.

Generated workspace documents:

- `SARATHI.md`.
- `wiki/overview.md`.
- `wiki/architecture.md`.
- `wiki/repositories.md`.
- `wiki/coding-standards.md`.
- `wiki/guidelines.md`.
- `wiki/decisions.md`.
- `policy-pack/*`.
- `learnings.md`.

MVP document quality bar:

- Generated docs may be minimum-useful in MVP: clear headings, repo-specific facts where discoverable, and explicit placeholder bullets for unknowns.
- Sarathi should prefer reviewable drafts over overconfident guesses.
- Placeholder bullets must be actionable, such as `Needs user input: test command`, instead of vague filler.

User stories:

- As a user, I can create a workspace for one repo or a multi-repo initiative.
- As a team lead, I can use one workspace for frontend, backend, docs, and policy repos.
- As a cautious user, I can see exactly which repos Sarathi may touch.

Acceptance criteria:

- Workspace creation works with zero repos for planning-only usage.
- Workspace can add/remove repos without deleting task history.
- Workspace settings show linked repos and health.
- A workspace can be archived.
- Tasks cannot execute repository mutations outside linked repos without explicit approval.
- Existing repo initialization produces a reviewable draft before writing generated docs.
- Brand-new repo initialization asks enough questions to create useful policy/guideline defaults.
- Generated documentation is versioned and linked to the workspace history.

Priority:

- MVP: create workspace, attach repos, run repository intake, and create minimal wiki/policy/guideline docs.
- V1: multi-repo dependency awareness and richer auto-discovered repository documentation.
- V2: workspace templates and team sharing.

### Phase 4: Policy Pack Setup

Goal: Make orchestration behavior explicit and inspectable.

Functional requirements:

- Initialize policy pack from template.
- Validate policy pack.
- Show policy sections in UI.
- Allow policy pack selection per workspace.
- Compile policies into runtime behavior.
- Surface validation issues with actionable guidance.
- Support accepted learning proposals modifying policy.

Policy sections:

- Complexity.
- Conventions.
- Commands.
- Review.
- Escalation.
- Model routing.
- Skills.
- Task tracking.
- Graph execution.
- Quality loop.
- Diagram generation.

Minimal viable policy pack:

- `commands.md`: allowed commands, risky command classes, test/build commands, timeout defaults.
- `review.md`: required evidence, severity thresholds, review verdict schema.
- `task-tracking.md`: task graph format, blocked/unblocked semantics, lifecycle states.
- `model-routing.md`: role-to-provider defaults and fallback order.
- `escalation.md`: retry budgets, hard-stop behavior, waiting-human rules.

Example policy pack layout:

```text
policy-pack/
  commands.md          # build/test commands, risky command classes
  review.md            # evidence requirements, verdict schema, severity rules
  task-tracking.md     # graph format, lifecycle states, blockers
  model-routing.md     # role-to-provider defaults and fallback order
  escalation.md        # retry budgets, hard-stop, waiting-human behavior
  conventions.md       # MVP stub or repo-derived coding standards
  complexity.md        # MVP basic low/medium/high thresholds
  skills.md            # MVP stub for external assistant routing
```

Future or stubbed policy sections:

- `complexity.md` can start with basic low/medium/high thresholds.
- `conventions.md` can start as freeform guidance consumed by review.
- `skills.md` can start as routing notes for external assistants.
- `diagram-generation` can start with default templates only.
- Advanced quality-loop and learning-feedback policies can be commented stubs until V1.

Example MVP policy fragment:

```yaml
graph_execution:
  max_retries: 2
  auto_retry_failed_nodes: true
  pause_on_failed_node: true
  require_human_after_retries: true

repository_actions:
  require_approval:
    - commit
    - push
    - pull_request
  blocked_commands:
    - "git reset --hard"
    - "rm -rf"

routing:
  roles:
    pravaha:
      preferred_provider: codex
      fallback_provider: copilot
    nirnaya:
      preferred_provider: claude
      fallback_provider: codex
```

User stories:

- As a lead, I can encode repo conventions once and make every agent follow them.
- As a user, I can see why Sarathi selected a workflow or provider.
- As an admin, I can validate a policy pack before letting tasks run.

Acceptance criteria:

- Invalid policies block execution when blocking mode is enabled.
- Validation distinguishes warning, drift, todo, and blocking issue.
- UI links policy decisions back to source file and section.
- Accepted learnings create reviewable policy proposals before mutation.

Priority:

- MVP: init, validate, select policy pack.
- V1: UI policy editor/viewer.
- V2: policy diff, approval workflows, org policy inheritance.

### Phase 5: Project And Work Item Intake

Goal: Let users manage features, bugs, tasks, spikes, chores, and release work inside a workspace.

Functional requirements:

- Support work item types: feature, bug, task, spike, chore, incident, release, documentation.
- Support import from plain text, markdown, issue URL, Jira/GitHub issue, local file, or chat.
- Support priority, severity, labels, owner, due date, affected repos, and risk level.
- Support one main task with many subtasks.
- Support dynamic task tabs.
- Support edits before and after orchestration, with audit trail.

User stories:

- As a user, I can paste a rough idea and let Sarathi turn it into a structured feature.
- As an engineer, I can import a bug and have Sarathi ask for reproduction and expected behavior.
- As a lead, I can see all active tasks across a workspace.

Acceptance criteria:

- `New Task` starts a chat with Sarathi.
- Work item type affects required fields and workflow.
- Imported items preserve source references.
- Every task has status, phase, AC state, review state, and completion state.
- Task edits emit history events.

Priority:

- MVP: manual task creation and task dashboard.
- V1: issue import and markdown PRD import.
- V2: bidirectional integrations with Jira/GitHub/Linear.

Work item templates:

- Feature: problem, target users, desired outcome, functional requirements, ACs, rollout and metrics.
- Bug: observed behavior, expected behavior, reproduction, impact, suspected area, regression ACs.
- Task: objective, constraints, expected output, verification command, completion evidence.
- Spike: question, research scope, decision criteria, timebox, resulting recommendation.
- Incident: severity, timeline, mitigation, root cause, follow-up tasks, customer impact.
- Release: included tasks, release criteria, rollback plan, changelog, approval checklist.
- Documentation: audience, topic, source truth, examples, review owner, publishing location.

Template acceptance criteria:

- Each work item type has required fields, optional fields, and recommended workflow.
- Sarathi asks type-specific clarifying questions.
- Work item type influences PRD/AC generation and review policy.
- Users can convert one work item type into another with history preserved.

### Phase 6: PRD And Acceptance Criteria Authoring

Goal: Turn ambiguous requests into clear product requirements before execution.

Functional requirements:

- Sarathi generates a PRD draft for feature-level work.
- Sarathi generates bug report structure for bug-level work.
- Sarathi generates acceptance criteria in testable form.
- User can approve, edit, reject, or ask for alternatives.
- PRD and ACs become durable task artifacts.
- ACs map to subtasks, tests, reviews, and final evidence.

PRD sections:

- Problem statement.
- Goals.
- Non-goals.
- Users/personas.
- User journeys.
- Functional requirements.
- Non-functional requirements.
- Acceptance criteria.
- Dependencies.
- Risks.
- Rollout plan.
- Success metrics.

Bug intake sections:

- Observed behavior.
- Expected behavior.
- Reproduction steps.
- Scope/impact.
- Suspected area.
- Regression risk.
- Fix acceptance criteria.

User stories:

- As a product owner, I can review a PRD before any agent writes code.
- As an engineer, I can trace every implementation unit back to ACs.
- As a reviewer, I can see which ACs passed, failed, or were not covered.

Acceptance criteria:

- Sarathi asks clarifying questions when AC confidence is below threshold.
- Execution cannot start until required PRD/AC approval gates pass.
- Every subtask references at least one goal, AC, risk, or technical requirement.
- Final review shows AC coverage matrix.
- Changes to PRD/ACs after execution begins create versioned artifacts.

Priority:

- MVP: PRD/AC draft and approval.
- V1: AC coverage matrix and versioning.
- V2: generated tests from ACs and import/export to external PM tools.

### Phase 7: Orchestration Planning

Goal: Convert approved PRD/ACs into an executable task graph.

Functional requirements:

- Sarathi routes complexity.
- Disha creates plan and phases.
- Vichara gathers repo and documentation context.
- Prajna evaluates tradeoffs and risks.
- Marga selects roles/providers.
- Sarathi proposes subtasks and dependencies.
- User approves before task graph persistence/execution.

Task packet requirements:

- ID.
- Title.
- Goal.
- Context.
- Relevant files/repos.
- Dependencies.
- Blockers.
- Assigned role.
- Preferred provider.
- Workflow type.
- Expected output.
- Evidence requirements.
- Review criteria.
- Rollback notes.

User stories:

- As a user, I can inspect and modify the task graph before agents start.
- As a subagent, I receive enough context to work without digging through the entire workspace.
- As a lead, I can see why a subtask is assigned to a provider.

Acceptance criteria:

- Graph view is default for planned tasks.
- List view exposes the same graph as rows.
- Blocked/unblocked dependencies are explicit.
- Planning includes rollback and risk notes.
- Sarathi logs confidence and missing evidence.

Priority:

- MVP: task graph generation and approval.
- V1: editable graph.
- V2: plan simulation and cost/time estimates.

### Phase 8: Execution And Agent Dispatch

Goal: Dispatch approved subtasks to the right model/provider while preserving lifecycle discipline.

Functional requirements:

- Sutra monitors task graph state.
- Ready subtasks can be claimed.
- Blocked subtasks wait until dependencies complete.
- Non-blocking siblings can run in parallel.
- Provider dispatch includes full task packet.
- Execution output must include evidence, changed files, commands run, failures, and next state.
- Retry budget and pause behavior follow policy.

Lifecycle states:

- Draft.
- Approved.
- Queued.
- Claim.
- In progress.
- Blocked.
- Waiting human.
- Failed.
- Review.
- Rejected.
- Complete.
- Cancelled.

User stories:

- As a user, I can watch live task progress without refreshing.
- As an agent, I can claim a subtask and know exactly what evidence is required.
- As a reviewer, I can see what happened before a unit entered review.

Acceptance criteria:

- Dispatch creates a durable dispatch record.
- Each state transition emits an SSE event.
- Failed provider calls preserve error detail and retryability.
- Exhausted retry budget marks work waiting-human or failed per policy.
- Parallel execution never violates dependencies.

Priority:

- MVP: manual/semi-automatic dispatch and state transitions.
- V1: automatic dispatch for unblocked units.
- V2: advanced scheduling, cost-aware routing, and concurrency controls.

Provider execution contract:

- Input: task packet, policy refs, workspace refs, allowed repo scope, allowed command classes, expected evidence, and timeout/retry budget.
- Output: status, summary, changed files, commands run, evidence refs, review notes, risks, follow-up tasks, and provider telemetry.
- Error: structured category, retryability, partial evidence, suggested recovery, and whether human attention is required.

Execution acceptance criteria:

- Every provider adapter conforms to the same input/output/error contract.
- Dispatch records include role name and provider name.
- A provider can refuse work with a typed reason instead of failing ambiguously.
- Sarathi can replay a dispatch summary without rerunning the provider.

### Phase 9: Review And Validation

Goal: Make AI-generated work safe enough for real delivery.

Functional requirements:

- Nirnaya performs code review and QA validation.
- Review can run per subtask and overall task.
- Review findings link to files, lines, artifacts, ACs, and evidence.
- Rejected units loop back to implementation with findings.
- Functional review checks AC coverage.
- Risk check identifies regressions, missing tests, scope creep, and unsafe actions.

Review types:

- Self-review.
- Code review.
- QA review.
- Security review.
- Functional AC review.
- Regression review.
- Release readiness review.

Review-run simplification:

- MVP uses one underlying `review_run` model for all review labels.
- `self`, `code`, `QA`, `security`, `functional`, `regression`, and `release` are review types on the same schema, not separate engines.
- MVP must implement code/functional review with structured verdicts and loop budget.
- Other review types can reuse the same schema as labels until specialized behavior is needed.

User stories:

- As a lead, I can require review loops before task completion.
- As a user, I can see why a unit was rejected.
- As an engineer, I can open file-level findings from review.

Acceptance criteria:

- A subtask cannot complete without required evidence.
- Review verdict is structured: approved, rejected, needs-human, blocked.
- Rejected units preserve findings and loop count.
- Review has a hard-stop policy to prevent infinite loops.
- Overall task cannot complete until final code and functional review pass or human overrides.

Priority:

- MVP: structured verdicts and loop state.
- V1: file-level annotations.
- V2: semantic diff review and automated test generation.

### Phase 10: Final Handoff, Commit, And PR

Goal: Deliver completed work with human-controlled repository actions.

Functional requirements:

- Samanvaya coordinates final completion summary.
- Sarathi presents changed files, subtasks completed, tests run, reviews passed, risks, and AC coverage.
- User explicitly approves commit, branch push, PR creation, or no repository action.
- Commit/PR body includes PRD/AC summary and evidence.
- Handoff can export markdown summary.

User stories:

- As a user, I can review final work before Sarathi touches Git.
- As a maintainer, I get a PR body that explains intent, scope, tests, and risks.
- As a cautious user, I can choose no commit and keep changes local.

Acceptance criteria:

- Sarathi never commits or opens PRs without explicit permission.
- Handoff summary is persisted.
- PR body references task ID, ACs, tests, diagrams, and review results.
- Residual risks are never hidden.
- User can request another review loop before PR.

Priority:

- MVP: final summary and explicit permission.
- V1: commit/PR workflow.
- V2: release notes, changelog, and external PM status update.

Repository action modes:

- No action: leave changes local and record handoff.
- Patch export: create a patch file without modifying remote state.
- Commit local: create a local commit only.
- Push branch: push approved branch without PR.
- Draft PR: create PR as draft with generated body.
- Ready PR: create PR ready for review.
- External update: update linked issue/PM item after approval.

Action acceptance criteria:

- Mode selection is explicit in UI and CLI.
- Each mode has a preview of commands/actions before execution.
- Failed repository action preserves handoff and suggests recovery.
- PR body includes traceability: work item, PRD, ACs, subtasks, tests, reviews, diagrams, risks.

### Phase 11: History, Observability, And Audit

Goal: Make every orchestration decision inspectable.

Functional requirements:

- Chronological event history.
- Task and subtask logs.
- Provider dispatch logs.
- SSE stream status.
- Artifacts by phase.
- Review findings and verdicts.
- Diagrams generated from state.
- Usage statistics and provider metrics.

User stories:

- As a user, I can answer “what happened?” after returning to a task later.
- As a lead, I can compare provider success rates and review quality.
- As an admin, I can audit which agent ran which command.

Acceptance criteria:

- History can be filtered by task, provider, event type, severity, and date.
- Every artifact has a source phase and timestamp.
- Usage stats include completed tasks, executed units, failure rate, retry rate, and average time.
- MVP usage stats may be basic workspace-level counts and durations; provider-level metrics beyond health, dispatch status, success count, and duration can wait until V1.
- Generated diagrams are linked to tasks and review runs.
- Logs can be exported without exposing secrets.

Priority:

- MVP: task history and status.
- V1: dashboard analytics and diagram center.
- V2: org/team analytics.

### Phase 12: Learn And Evolve

Goal: Let Sarathi improve safely from repeated patterns.

Functional requirements:

- Learning records capture repeated failures, hotspots, successful patterns, and policy gaps.
- Learning records are scoped to workspace and can also reference specific repositories, tasks, providers, policies, and reviews.
- Sarathi proposes policy changes.
- User can accept, reject, or defer proposals.
- Accepted proposals update policy with audit trail.
- Accepted learnings update workspace documentation such as `learnings.md`, coding standards, guidelines, and policy pack notes when approved.
- Routing strategy can evolve from accepted learnings.

User stories:

- As a lead, I can make repeated review findings become policy.
- As a user, I can see what Sarathi learned and decide whether to apply it.
- As an admin, I can prevent automatic changes to critical policies.

Acceptance criteria:

- Learnings never mutate policy without review unless explicitly configured.
- Proposals include evidence references.
- Accepted proposals show diff before apply.
- Rejected proposals record reason.
- Evolution can be disabled per workspace.
- `learnings.md` remains human-readable and links back to evidence, tasks, reviews, and policy proposals.
- Documentation updates follow the same approval/audit model as policy updates.

Priority:

- MVP: workspace-scoped `learnings.md` generation/update through approved learn records.
- V1: UI proposal workflow and policy/documentation diff approval.
- V2: routing and workflow optimization from learnings.

## 7. “One Of A Kind” Differentiators

### 7.1 Orchestration Before Execution

Sarathi should not start with “let me code that.” It should start by understanding, structuring, and getting approval.

Requirement:

- Every non-trivial task begins with PRD/AC planning and visible confidence gates.

### 7.2 Role-First, Provider-Second

Users should think in terms of Sarathi, Disha, Vichara, Prajna, Pravaha, Nirnaya, Samanvaya, Marga, Sutra, and Sahayaka.

Requirement:

- UI and logs show role first, provider second.

### 7.3 Context Packets For Every Subtask

Each subtask should be executable by an agent without rediscovering everything.

Requirement:

- Task packets are first-class data and visible in the UI.

### 7.4 Visual Graphs As Product Memory

Dependency graphs, lifecycle diagrams, architecture diagrams, and review loops should be generated from real state.

Requirement:

- Diagram engine must be embedded and linked to task/history artifacts.

### 7.5 Evidence-Driven Completion

Completion should mean evidence exists, not that an agent said it is done.

Requirement:

- Every done state requires evidence aligned to policy and ACs.

### 7.6 Local-First Trust Model

Sarathi should be safe for private repos and enterprise workflows.

Requirement:

- Local SQLite, explicit provider calls, no hidden cloud dependency for core orchestration.

### 7.7 Multi-Agent Message Bus

Conversation should include user-to-agent, agent-to-user, and agent-to-agent coordination.

Requirement:

- Messages have audience, visibility, task/subtask links, and artifact references.

### 7.8 Review Loops With Hard Stops

Review should be systematic, bounded, visible to the user, and capable of improving work without creating endless loops.

Requirement:

- Review loops expose verdicts, findings, retry budget, hard-stop options, and human override choices.
- Review loops have budgets, severity rules, escalation, and human override paths.

### 7.9 Sarathi Builds Sarathi

Sarathi should prove its own core promise by being built through Sarathi. The desktop app is not only a product surface; it is the canonical dogfood workspace that demonstrates the CLI, skill, policy pack, task graph, evidence model, review loops, learnings, and handoff flow working together.

Requirement:

- Sarathi app development must be orchestrated as a Sarathi workspace using the Sarathi CLI and Sarathi skill.
- Product requirements, implementation plans, task graphs, subtask packets, evidence, review findings, final handoffs, and learnings for Sarathi app work are stored as inspectable Sarathi artifacts.
- The app includes a dogfood/demo workspace that can show how Sarathi itself was planned, built, reviewed, and evolved.
- Release notes for public builds include a “Built with Sarathi” section referencing the task graph, review evidence, and accepted learnings used to ship the release.

## 8. Data Model Requirements

Core entities:

- Workspaces.
- Workspace repositories.
- Workspace vaults.
- Workspace guide files.
- Policy packs.
- Providers.
- Provider health checks.
- Inbox items.
- Saved views.
- Tasks.
- Task versions.
- PRD artifacts.
- Acceptance criteria.
- Subtasks.
- Task dependencies.
- Task packets.
- Object properties.
- Dispatches.
- Messages.
- Context links.
- Lifecycle events.
- Review runs.
- Review findings.
- Evidence artifacts.
- Attachments.
- Diagram artifacts.
- Decision records.
- Snapshots.
- Handoff summaries.
- Learning records.
- Policy proposals.
- Settings.

Entity scope tags:

| Entity | Scope tag | Notes |
| --- | --- | --- |
| Workspaces | MVP-hard | Current workspace boundary. |
| Workspace repositories | MVP-hard | One or more linked repos. |
| Providers | MVP-hard | Config, health, capabilities. |
| Tasks | MVP-hard | Main executable work item. |
| Subtasks | MVP-hard | Task graph nodes. |
| Task dependencies | MVP-hard | Blocked/unblocked graph. |
| Task packets | MVP-hard | Context for dispatch. |
| Dispatches | MVP-hard | Provider execution attempts. |
| Messages | MVP-hard | User/agent communication. |
| Lifecycle events | MVP-hard | State transition audit. |
| Review runs | MVP-hard | Structured verdicts. |
| Evidence artifacts | MVP-hard | Proof for completion/review. |
| Handoff summaries | MVP-hard | Final completion package. |
| Settings | MVP-hard | Workspace/app config. |
| PRD artifacts / ACs | MVP-hard | Required for medium/high work. |
| Inbox items | MVP-light | Capture and convert; advanced classification can wait. |
| Saved views | MVP-light | Fixed built-in views first; custom views later. |
| Diagram artifacts | MVP-light | Store generated dependency/lifecycle diagrams; diagram center can mature later. |
| Workspace vaults / guide files | MVP-light | Minimum useful generated files in MVP; richer vault in V1. |
| Learning records | MVP-light | Enough to update workspace `learnings.md`; proposal UI later. |
| Object properties | V1 | MVP can use typed fields on core tables. |
| Context links | V1 | MVP can store raw references and resolve common patterns. |
| Attachments | V1 | MVP can attach basic files as evidence artifacts. |
| Decision records | V1 | MVP can fold major decisions into PRD/review artifacts. |
| Snapshots | V1 | MVP can rely on versioned artifacts and events. |
| Policy proposals | V1/V2 | CLI baseline exists; desktop workflow can follow later. |

Critical relationships:

- Workspace has many repositories.
- Workspace has one vault and many exported files.
- Workspace has many inbox items and saved views.
- Workspace has one active policy pack and many historical policy versions.
- Task belongs to workspace.
- Task has many PRD versions, ACs, subtasks, messages, diagrams, decision records, snapshots, and review runs.
- Subtask has many dependencies, dispatches, lifecycle events, evidence artifacts, and review findings.
- Provider dispatch references provider, role, task packet, and result artifact.
- Review finding references AC, file, line, evidence, or subtask when available.
- Context links connect messages, PRDs, ACs, subtasks, files, policies, artifacts, and diagrams.

## 9. Event Requirements

Required SSE event families:

- `workspace.*`
- `provider.*`
- `vault.*`
- `inbox.*`
- `saved_view.*`
- `task.*`
- `prd.*`
- `acceptance_criteria.*`
- `subtask.*`
- `dependency.*`
- `dispatch.*`
- `message.*`
- `context_link.*`
- `review.*`
- `artifact.*`
- `attachment.*`
- `diagram.*`
- `decision_record.*`
- `snapshot.*`
- `handoff.*`
- `learning.*`
- `policy_proposal.*`

MVP event model:

- SQLite is the source of truth for MVP.
- Events are notifications and audit entries, not the only source required to rebuild state.
- The UI should recover from current SQLite snapshots plus recent events.
- Full event sourcing can be revisited after the core desktop workflow is stable.

Acceptance criteria:

- UI can rebuild task state from SQLite snapshots plus persisted events.
- SSE reconnect does not duplicate state.
- Events include correlation IDs.
- Events can be inspected from History.

## 10. Security And Governance Requirements

Functional requirements:

- No plaintext secret display.
- Provider credentials use OS keychain or secure references where possible.
- Repository mutations require explicit user approval.
- Dangerous commands require policy allowance.
- Workspace permissions restrict repo access.
- Audit log records command execution and provider dispatch.
- Export redaction is available.

Acceptance criteria:

- Settings never reveal tokens.
- Commit/PR/publish actions are blocked without approval.
- Commands outside linked repos are blocked or require override.
- Failed security checks mark task waiting-human.

## 11. Non-Functional Requirements

Performance:

- Task dashboard loads within two seconds for 1,000 tasks.
- Task graph remains interactive for 200 subtasks.
- History supports pagination or virtualization.

Reliability:

- App can restart and resume active tasks.
- Provider failures do not corrupt task state.
- SQLite writes are transactional for state transitions.

Usability:

- First-run path works for non-expert users.
- Power users can operate entirely from CLI.
- Every status label has understandable meaning.
- Empty states explain what to do next.
- Keyboard-first navigation is available for command palette, task switching, graph/list toggle, message composer, and approval actions.
- Destructive or repository-mutating actions require clear preview and confirmation.
- Error messages include cause, impact, and next action.

Accessibility:

- Core workflows are usable without relying on color alone.
- Graph nodes expose text equivalents through list view.
- Interactive controls have accessible names.
- Focus states are visible in light and dark themes.
- Motion is subtle and can be disabled through system preference.

Extensibility:

- New providers can be added without changing task lifecycle.
- New workflow types can be added through policy.
- New diagram templates can be added without rebuilding core orchestration.

Portability:

- Core CLI works anywhere Python runs.
- Desktop can use the same local service and policy packs.
- Skill can travel to Codex, Copilot, Claude, and other agent environments.

## 12. Release Scope

### First 3 Months: Dogfood Desktop Build

Goal: ship a narrow, usable local cockpit that proves Sarathi’s core loop without pretending every future capability is production-ready. The first public build should be dogfooded through Sarathi itself: Sarathi CLI plus Sarathi skill must orchestrate Sarathi app requirements, implementation tasks, reviews, evidence, handoff, and learnings.

Build-cycle operating requirement:

- Every Sarathi app milestone starts as a Sarathi workspace task with PRD/ACs, approved graph, subtask packets, and explicit handoff criteria.
- Every implementation slice records evidence through the same task detail model the app exposes: dispatch, changed files, tests/checks, review verdicts, blockers, and repository action approvals.
- The implementation tracker links back to Sarathi-generated task IDs so the roadmap, app UI, CLI artifacts, and handoff dossier stay aligned.
- Dogfood gaps found while building Sarathi are treated as product requirements or learning records, not side notes.

Milestones:

| Milestone | Target outcome | Linked validation scenarios | Notes |
| --- | --- | --- | --- |
| M0: Local cockpit | Install CLI, open desktop shell, create workspace, configure one provider, persist SQLite state. | Fresh install, planning-only | First internal dogfood and `Sarathi App` workspace creation. |
| M1: Workspace knowledge | Add repo, run Sarathi repo intake, generate minimal wiki/policy/coding standards/guidelines. | Planning-only, multi-repo workspace | Workspace becomes useful before task execution. |
| M2: Structured task | Create task from chat, draft PRD/ACs, approve graph, show task detail graph/list/messages. | Single-repo feature, bug fix | Core product loop begins; Sarathi app work uses this path. |
| M3: Provider execution | Dispatch at least one implementation unit through Codex/local provider and record evidence. | Single-repo feature, provider failure | Claude/Copilot can be health/config stubs if needed. |
| M4: Review and handoff | Run one structured review loop, generate final handoff, require repository action approval. | Review rejection, final PR, dirty worktree | Commit/PR can be preview-only if needed. |
| M5: Durability polish | Resume after restart, history filter, built-in saved views, basic dossier export, update `learnings.md`. | Resume, planning-only | Public-alpha readiness gate plus “Built with Sarathi” release dossier. |

Can be simulated in MVP:

- Provider cost metrics.
- Advanced routing optimization.
- Learning proposals in desktop UI.
- Hosted provider adapters.
- Diagram center beyond generated dependency/lifecycle views.
- Fully editable graph layout.
- External PM sync.

### MVP: Local Orchestration Cockpit

Must include:

Hard dependencies:

- MVP-H1: CLI install and validation.
- MVP-H2: Desktop shell.
- MVP-H3: Workspace creation.
- MVP-H4: Repository intake that runs Sarathi initialization for attached repos.
- MVP-H5: Minimal workspace wiki, policy pack, coding standards, guidelines, `SARATHI.md`, and `learnings.md`.
- MVP-H6: At least one configured provider or local deterministic provider.
- MVP-H7: Task dashboard.
- MVP-H8: New task chat.
- MVP-H9: PRD/AC draft and approval for medium/high work.
- MVP-H10: Basic task graph generation.
- MVP-H11: Manual/semi-automatic dispatch.
- MVP-H12: Task detail with graph/list/messages/evidence.
- MVP-H13: One structured review loop.
- MVP-H14: Final handoff summary.
- MVP-H15: SQLite persistence.
- MVP-H16: SSE for task, message, graph, and review state.
- MVP-H17: Dogfood evidence showing Sarathi app work was run through Sarathi CLI/Skill with task graph, reviews, evidence, handoff, and learnings.

MVP stretch, OK to slip:

- Inbox capture.
- Custom saved views beyond built-in filters.
- Markdown task dossier export beyond final handoff markdown.
- Diagram center as a standalone page.
- Provider metrics beyond health and dispatch status.
- Complex graph editing UI.

MVP exit criteria:

- A solo builder can install Sarathi, create a workspace, connect at least one provider, run one feature task end-to-end, review the output, and receive a final handoff.
- Adding an existing repo creates reviewable workspace documentation and policy drafts.
- Adding a brand-new repo triggers an interview and creates initial workspace documentation and policy drafts.
- The same task can survive app restart without losing graph state, messages, evidence, or approvals.
- A repository action is never executed without explicit approval.
- The user can inspect what happened through task detail and history.
- Learnings from the task are written to workspace-scoped `learnings.md` after approval.
- At least one validation fixture passes through CLI path and desktop path.
- Sarathi app development itself has an inspectable dogfood workspace, including task packets, review runs, evidence artifacts, and a “Built with Sarathi” handoff dossier.

Internal dogfood only:

- Multi-provider automatic routing before hosted adapters are stable.
- Learning proposal UI.
- Advanced diagram generation.
- External PM import/export beyond manual markdown or GitHub link references.

MVP non-goals:

- Hosted multi-tenant cloud service.
- Org-wide policy inheritance.
- Automatic external PM synchronization.
- Fully autonomous commit/PR without human approval.
- Cost-optimized hosted model routing.
- Multi-user real-time collaboration.
- Full semantic codebase indexing beyond linked repo context and policy files.

### V1: Production-Ready Multi-Agent Workbench

Must include:

- Provider routing and fallback.
- Editable task graph.
- File-level review findings.
- Commit/PR workflow.
- Diagram center.
- Workspace vault with `SARATHI.md`.
- Properties panel and context mentions.
- Attachment evidence browser.
- Policy viewer/editor.
- Workspace templates.
- AC coverage matrix.
- UI learning proposal workflow.
- Provider metrics.

### V2: Team And Enterprise Platform

Should include:

- Hosted provider adapters.
- Team policy inheritance.
- External PM integrations.
- Org analytics.
- Advanced cost/quota routing.
- Shared workspace profiles.
- Secure credential management.
- Release automation.
- Governance approvals.

## 13. Product-Level Acceptance Criteria

Sarathi becomes “one of a kind” when these are true:

- A user can install Sarathi, create a workspace, connect providers, and start an orchestrated task without reading source code.
- A rough task can become a PRD, ACs, task graph, agent assignments, review gates, and final handoff.
- Codex, Claude, Copilot, and local providers can participate through one role-first orchestration model.
- Each subtask is self-contained and traceable to PRD/ACs.
- The UI shows live graph state, messages, provider activity, review loops, and evidence.
- All work is resumable after interruption.
- The final handoff explains what changed, why it changed, what passed, what remains risky, and asks before commit/PR.
- Learnings can evolve policy through explicit proposals.
- Complex task state can be visualized as dependency graphs, lifecycle diagrams, architecture maps, and review-loop diagrams.
- The Sarathi app itself can show a dogfood workspace proving that Sarathi CLI/Skill planned, decomposed, executed, reviewed, and learned from Sarathi app development.
- Public-alpha release notes include a “Built with Sarathi” dossier with task graph, evidence, review loop, validation results, and accepted learnings.

## 14. Open Product Decisions

- Which desktop packaging path should be first: Electron-only, Tauri, or web-plus-local-service?
- Should the first desktop MVP execute real provider calls or start with CLI-driven simulation plus manual dispatch?
- Should PRD/AC approval be mandatory for all tasks or only medium/high complexity tasks?
- Should workspace SQLite live inside each workspace or in a global Sarathi app data directory with workspace pointers?
- Which external PM integration should be first: GitHub Issues, Jira, Linear, or plain markdown?
- Should team sharing be file-based policy packs first or a hosted coordination service later?

PO recommended defaults:

Unless explicitly overridden later, engineering should treat these defaults as binding for MVP/V1 implementation planning.

- Use Electron plus local service for the first desktop implementation because the current mockup and local-service mental model already align with it.
- Start MVP with CLI-backed execution, provider health checks, manual/semi-automatic dispatch, and safe simulation paths; add fully automatic live hosted provider dispatch in V1.
- Require PRD/AC approval for medium/high complexity work; allow low complexity tasks to use a lightweight intent/AC confirmation.
- Store SQLite in a Sarathi app data directory by default, with workspace-level pointers and an advanced option for workspace-local `.sarathi` storage.
- Prioritize plain markdown and GitHub Issues import/export first; Jira and Linear can follow once the core object model is stable.
- Use file-based policy packs first; team sharing should begin with templates and exported profiles before any hosted coordination service.

## 15. Validation Plan

The product requirements should be validated through scenario-based acceptance tests before implementation is considered ready.

Required validation scenarios:

- Fresh install: user installs CLI, launches desktop, validates prerequisites, and reaches a ready setup state.
- Planning-only: user creates a workspace with no providers, drafts PRD/ACs, generates a graph, and exports the result.
- Single-repo feature: user creates a feature, approves PRD/ACs, dispatches subtasks, reviews evidence, and receives final handoff.
- Bug fix: user imports a bug, Sarathi asks reproduction questions, creates fix ACs, executes, reviews, and summarizes regression risk.
- Multi-repo workspace: user links frontend/backend repos, creates a task graph with repo-specific subtasks, and sees cross-repo dependencies.
- Provider failure: one provider goes offline, Sarathi marks affected work retryable or waiting-human and offers re-route.
- Dirty worktree: workspace has pre-existing changes, Sarathi warns before execution and separates user changes from Sarathi changes at handoff.
- Review rejection: Nirnaya rejects a unit, findings loop back to implementation, and the second review records the improvement.
- Resume: app exits during an in-progress graph, restarts, reconnects SSE, and resumes from persisted graph state.
- Final PR: user approves draft PR, generated PR body includes PRD, ACs, subtasks, tests, reviews, diagrams, and risks.
- Sarathi builds Sarathi: the Sarathi app repository is attached to a workspace, work is planned through Sarathi CLI/Skill, implementation subtasks are tracked, evidence/reviews are recorded, learnings are updated, and the final release handoff includes a “Built with Sarathi” dossier.

Scenario coverage map:

| Product phase | Validation scenario |
| --- | --- |
| Installation/setup | Fresh install |
| Workspace creation | Planning-only, multi-repo workspace |
| Provider connection | Fresh install, provider failure |
| PRD/AC authoring | Planning-only, single-repo feature, bug fix |
| Orchestration planning | Single-repo feature, multi-repo workspace |
| Execution/dispatch | Single-repo feature, provider failure |
| Review/validation | Review rejection, bug fix |
| Handoff/repository actions | Final PR, dirty worktree |
| History/resume | Resume, dirty worktree |
| Vault/export/diagrams | Planning-only, final PR |
| Dogfood proof | Sarathi builds Sarathi, final PR |

Test fixtures:

- Fixture A: `tiny-feature-repo`
  - Two source files, one test file, simple README, clean Git history.
  - Used for feature PRD/AC, graph generation, dispatch, review, and final handoff.
- Fixture B: `tiny-bug-repo`
  - One intentional failing test, one source bug, reproduction note, and expected behavior.
  - Used for bug intake, diagnosis, regression ACs, review rejection, and fix handoff.
- Fixture C: `multi-repo-demo`
  - One frontend repo and one backend repo with a documented API contract.
  - Used for workspace creation, cross-repo task graph, provider assignment, and dependency visualization.
- Fixture D: `dirty-worktree-repo`
  - Pre-existing user changes plus generated Sarathi changes.
  - Used for Git safety, handoff diff separation, and repository action approval.
- Fixture E: `sarathi-app-dogfood`
  - The Sarathi app workspace itself, with CLI/Skill-generated task graph, review evidence, handoff dossier, and approved learnings.
  - Used to prove the product can build and explain its own development process.

Validation acceptance criteria:

- Each scenario has a scripted CLI path and a desktop UI path where applicable.
- Each scenario leaves inspectable SQLite records, events, artifacts, and history entries.
- Failures produce actionable recovery choices.
- No scenario requires hidden manual file edits outside documented setup.
- The dogfood scenario is good enough to demo in the app without private context: sensitive paths/secrets are redacted, but task graph, review evidence, and learning trail remain understandable.

## 16. Review Loop Audit

This PRD went through three review/address passes.

Loop 1 addressed product definition gaps:

- Added north-star metrics and quality guardrails.
- Added Product Owner / Program Lead persona.
- Added product object hierarchy.
- Added explicit human approval gates.
- Added work item templates.
- Added provider execution contract.

Loop 2 addressed buildability and operational gaps:

- Clarified current versus future CLI command maturity.
- Added local API boundary.
- Added repository and Git workflow requirements.
- Added offline, degraded, and recovery modes.
- Added repository action modes.
- Added MVP non-goals.

Loop 3 addressed final readiness gaps:

- Added usability and accessibility requirements.
- Added PO-recommended defaults for open product decisions.
- Added scenario-based validation plan.
- Added this review loop audit.

Tolaria-inspired product pass added:

- Workspace vault and `SARATHI.md` AI-readable guide.
- Inbox capture, saved views, archive semantics.
- Properties panel, object metadata, wikilinks, and context mentions.
- Command palette and quick prompt mode.
- Attachment evidence, Markdown dossiers, decision records, and state snapshots.

External agent review pass addressed:

- Sharpened first-three-month dogfood scope, MVP hard dependencies, stretch items, and exit criteria.
- Added desktop sidebar/navigation spec and screen-level critical interactions.
- Added UI treatment table for first-class objects versus panel/tab objects.
- Added minimal viable policy pack, approval enforcement ranking, and example pseudo-YAML.
- Added concrete role/provider flows and role-to-provider mapping.
- Clarified MVP data model scope and SQLite-as-source-of-truth event model.
- Added validation scenario coverage map and reusable test fixtures.
- Added entity scope tags, minimum-useful generated-doc quality bar, review-run simplification, MVP usage-stat scope, binding PO defaults, tracker IDs for MVP hard dependencies, milestone validation links, and example policy-pack layout.

Workspace-first pass added:

- Made workspace the first-class product citizen and mandatory setup boundary.
- Required repository intake to trigger Sarathi initialization when repos are attached.
- Added existing-repo inspection and brand-new-repo interview modes.
- Required generated workspace wiki, policy pack, coding standards, guidelines, `SARATHI.md`, and `learnings.md`.
- Made Inbox, Orchestrator, Task Dashboard, Views, History, Diagrams, Settings, and learnings workspace-scoped.
- Required approved learnings to update workspace documentation such as `learnings.md`.

Sarathi-builds-Sarathi pass added:

- Made dogfooding a first-class differentiator and release requirement.
- Required Sarathi app development to be orchestrated through Sarathi CLI and Sarathi skill.
- Added MVP-H17 for inspectable dogfood evidence across task graph, reviews, evidence, handoff, and learnings.
- Added a “Sarathi builds Sarathi” validation scenario and fixture.
- Required public-alpha release notes to include a “Built with Sarathi” dossier.

Next review passes should update this section rather than duplicating rationale elsewhere.
