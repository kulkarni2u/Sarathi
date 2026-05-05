# Sarathi Implementation Tracker

Last updated: 2026-05-04

This tracker is the working checkpoint for Sarathi platform implementation progress.
It is intentionally short and practical: what is done, what is in progress, and what is still pending.

## Status Legend

- `Done`: implemented and covered by the current test suite.
- `In Progress`: substantial implementation exists, but the milestone is not fully closed.
- `Pending`: planned but not yet implemented to the target level.

## Milestone Status

| Milestone | Status | Notes |
| --- | --- | --- |
| M1: Runtime Core | Done | Runtime contracts, artifact persistence, dispatcher/provider abstraction, configurable provider routing, and modular phase handlers are in place. |
| M2: Policy As Contract | Done | Compiled policy pack, semantic validation, preflight enforcement, typed policy seams, policy-driven graph execution, quality-loop policy, provider-routing validation, and learning-feedback policy hooks are in place. |
| M3: Task Graph + Resumability | Done | Task graph generation, persisted graph state, paused build semantics, resume flow, node metadata, failed/retryable/blocked/running/waiting-human states, retry-on-resume, child work-unit dispatch, and reusable scheduler API are implemented. |
| M4: Real Build/Verify/Review | Done | Verify/review produce structured artifacts, review consumes build/graph/verify/spec/diff evidence, escalation bundles are surfaced in CLI, and bounded provider-backed recovery-fix dispatch executes. |
| M5: Learn/Evolve | Done | Structured learning records, policy proposals, CLI proposal viewing, proposal accept/reject/apply workflow, provider-failure learning signals, and accepted-proposal feedback into retry policy and provider routing are implemented. |
| M6: Sarathi Desktop Dogfood MVP | Done | UI-00 through UI-15 are implemented: workspace setup, task initiation, graph, scheduling, dispatch, SSE, review, handoff, operational views, dogfood acceptance, and learn-loop closure. |

## Done

### Core runtime

- Extracted lifecycle phase implementations out of `src/engine.py`.
- Added runtime contracts for dispatch and gate/evidence flow.
- Added artifact persistence and task persistence.
- Added provider abstraction plus local deterministic provider path.
- Added configurable deterministic provider routing from model-routing policy.
- Added command-backed provider adapter for local external/runtime tool integration.

### Policy and validation

- Added compiled policy-pack loading.
- Added semantic validation and preflight checks.
- Added CLI-visible preflight summary and enforced blocking mode.
- Added typed policy wrapper seam while preserving backward compatibility.
- Added policy-driven graph execution controls:
  - step limits
  - retry budgets
  - auto-retry behavior
  - pause behavior
  - human-attention behavior after retry exhaustion
- Added validation for malformed graph execution policy blocks.
- Added validation for malformed provider-routing policy blocks.
- Added accepted-proposal feedback into quality-loop retry/autofix policy.

### Task graph and resume

- Added `task_graph` artifacts from planning.
- Persisted `task_graph_state` onto tasks.
- Added graph execution service for build.
- Added child work-unit dispatch for ready graph nodes.
- Added reusable scheduler API for graph work outside a single phase handler.
- Added paused build semantics when graph work remains.
- Added `status` and `resume` CLI flows.
- Added node-level execution metadata:
  - attempts
  - started/completed timestamps
  - latest completed node
- Added node-level failure/retry metadata:
  - failed node tracking
  - retryable node detection
  - retry-on-resume behavior
- Added `waiting_human` handling for exhausted failed graph nodes.

### Verify and review runtime

- Added structured command execution artifacts.
- Added structured review verdicts, totals, and severity summaries.
- Exposed richer verify/review evidence through phase results.
- Added evidence-backed review over graph, verify, and escalation artifacts.
- Added durable escalation bundles for failed or `waiting_human` graph work.
- Surfaced escalation summaries through `sarathi status` and `sarathi log`.
- Added verify/review quality-loop policy hooks for retry and autofix decisions.
- Added executable bounded recovery actions for verify/review retry loops.
- Added provider-backed recovery-fix dispatch contracts for retry loops.
- Added real spec/diff review evidence ingestion.
- Added evidence refs to escalation summaries.

### Learn/evolve baseline

- Added `LearningRecord` and `LearningStore`.
- Added structured learn artifacts and retained compatibility fields.
- Added learning history, repeated-failure summaries, escalation summaries, and iteration hotspots.
- Added non-mutating policy proposal generation from learning signals.
- Added `sarathi proposals` to inspect proposals from persisted learnings.
- Added proposal accept/reject/apply workflow that records review decisions and appends accepted proposals to policy files.
- Added YAML-native accepted proposal insertion when policy files contain YAML blocks.
- Added provider-failure learning signals and routing-hint proposals that can steer phase-level provider selection after acceptance.

### Verification

- Current repo test status at this checkpoint: `204 passed` (`python3 -m pytest`, 2026-05-02).

### Documentation

- Added the Sanskrit-inspired agent role naming tranche to runtime artifacts, CLI output, and the companion/installed Sarathi skill files.
- Updated `docs/core-policy-interface-mapping.md` to reflect current implementation status (all phases now show ✓ Implemented/Enhanced)
- Updated `README.md` with documentation for new CLI commands: `sarathi status`, `sarathi resume`, `sarathi proposals`, `sarathi agents`
- Created `docs/HOWTO.md` - Comprehensive how-to guide covering CLI usage, Python API, AI agent integration, policy pack setup, and common workflows
- Created Sarathi product and technical design specs for the desktop/local-service era under `docs/superpowers/specs/`.
- Created the first Sarathi UI foundation plan and dogfood task graph under `docs/superpowers/plans/` and `docs/superpowers/tasks/`.

### Desktop dogfood foundation

- Added `desktop/` React/Vite UI package for the first Sarathi cockpit foundation slice.
- Added workspace-first shell, transparent navigation, top command entry, route/status context, and light/dark styling.
- Added typed mock Sarathi data for workspace, repos, providers, roles, tasks, subtasks, approval gates, evidence, reviews, events, and messages.
- Added Task Studio baseline with graph/list toggle, selected unit packet, approval gates, messages, evidence, review, history, and handoff panels.
- Verified `npm --prefix desktop run build` and `npm --prefix desktop audit --omit=dev` on 2026-04-28.
- Added UI-02 SQLite storage foundation with migration tracking, required MVP tables, workspace-scoped durable records, cross-workspace consistency constraints, FK/query indexes, row-factory connections, parent-directory creation, and workspace/task repository methods.
- Added UI-03 local service API boundary with callable app, stdlib HTTP adapter, token auth, JSON envelopes, correlation IDs, typed errors, workspace/task REST routes, approval persistence, lifecycle events, and SSE snapshot endpoint.
- UI-03 originally exposed stable placeholder schemas for graph/evidence/review/handoff/provider surfaces; UI-09 through UI-13 have now replaced the MVP-critical placeholders with durable service-backed records.
- Added UI-04 repository intake backend slice with workspace repository storage methods, preview endpoint, approved attach endpoint, repository listing, dirty-state/Sarathi-doc readiness metadata, and lifecycle event recording.
- Added UI-04 renderer-to-service wiring with typed desktop API client, workspace list/create/select, repository preview, approved attach, persisted repo reload, local-service CORS, and `python -m src.service` launcher support.
- Added a compact workspace-page repository intake preview/attach affordance and reduced desktop shell density so the MVP is more usable at 100% browser zoom.
- Added UI-05 task initiation with durable task-scoped messages, `task-drafts` service endpoint, generated PRD/AC metadata, pending PRD/AC approval gate, lifecycle events, and Orchestrator chat wiring.
- Added UI-06 task graph generation with persisted subtask nodes, role/provider/task-packet/evidence metadata, dependency edges, PRD/AC approval precondition, pending Task graph approval gate, lifecycle events, and Orchestrator graph-generation wiring.
- Added UI-07 service-backed Task Dashboard with workspace task summaries, approval/graph state, role/provider lanes, blocked counts, quick filters, board/list toggle, and selected-task click-through into Task Studio.
- Added UI-08 service-backed Task Studio with a task snapshot endpoint, persisted graph/list rendering, dependency edges, selected unit packets, approval gates, task message search, persisted task-message composer, and lifecycle history.
- Added UI-09 graph scheduler and subtask lifecycle with approved-graph scheduling, ready sibling dispatch, unit transition events, downstream unblock logic, task phase/status updates, and Task Studio schedule/transition controls.
- Added UI-10 provider health and local deterministic dispatch with live provider lane data, local child-work-unit execution, dispatch persistence, evidence artifact persistence, subtask review-state transition, and Task Studio dispatch/evidence rendering.
- Added UI-11 event/SSE auto-updates with browser EventSource query-token support, shell stream status, workspace/task/provider/studio live invalidation, and polling fallback when SSE reconnects.
- Added UI-12 evidence review loop and AC coverage with persisted review runs, dispatch-evidence coverage mapping, approved-review unit completion, rejected-review requeue behavior, and Task Studio code/functional review actions.
- Added UI-13 handoff and repository action approval with persisted final handoff dossiers, AC coverage snapshots, explicit pending/approved repository-action gates, task completion after approved action, lifecycle events, and Task Studio handoff controls.
- Added UI-14 operational views with a workspace-scoped service snapshot for real lifecycle roles, audit history, dependency/review/handoff/lifecycle diagrams, and usage statistics backed by persisted SQLite records.
- Added UI-15 dogfood acceptance and learn-loop closure with a redacted "Built with Sarathi" acceptance dossier, explicit learning approval gate, workspace `learnings.md` update, and Usage-page acceptance panel.
- Added V1-01 repository initialization/interview foundation with approval-gated Sarathi doc generation, interview-required new repo initialization, repository metadata updates, lifecycle events, and Workspace-page init controls.
- Added V1-02 provider settings hardening with workspace-scoped Codex/Claude/Copilot/local provider settings, path/auth/test-connection checks, persisted health state, Settings-page controls, and schema migration coverage for per-workspace provider isolation.
- Added V1-03 richer file-level review annotations with deterministic changed-file evidence, persisted review findings linked to `subtask_id` and `evidence_id`, diff summary metadata, and Task Studio review/evidence rendering for reviewed files.
- Added V1-04 100% zoom UX density pass with a narrower shell, tighter panel spacing, earlier Task Studio/topbar stacking, more compact graph nodes, and responsive dashboard/task surfaces tuned for normal laptop zoom.
- Added V1-05 desktop packaging/startup foundation with a `sarathi-desktop` launcher, per-run runtime config/token wiring, generated `sarathi-runtime.js`, a single-command desktop boot path, and launcher test coverage.
- Added P5 policy-driven auto-cascade scheduling with workspace policy-pack lookup, auto-schedule on Task graph approval, and automatic scheduling of newly unblocked ready units after blocker completion.
- Added P6 provider parity hardening foundation with workspace-root native Claude/Copilot execution, provider-specific CLI invocation semantics, and persisted native CLI metadata in dispatch evidence/artifacts.
- Added P7 provider-aware recovery classification with provider-context propagation, auth/offline/native-CLI recovery classes, and provider-specific retry guidance for bounded recovery loops.
- Added P8 provider review-trace depth with persisted trace-backed review findings, provider trace diff summaries, and Task Studio rendering of provider review-trace metadata.
- Added P9 provider diff/spec evidence depth with persisted provider diff hunks, AC-linked spec references, structured AC coverage mapping, and Task Studio rendering of diff/spec trace summaries.
- Added P10 provider-backed spec drift enforcement with review rejection/requeue when structured provider evidence shows failing requirement mappings or uncovered acceptance criteria.
- Added P11 provider-backed diff risk synthesis with category/confidence/suggestion fields on diff findings plus review summaries for blockers, confidence, categories, and patch-region highlights.
- Added P12 cross-hunk clustering and final review-confidence synthesis with grouped diff regions, confidence reasons, and review-level verdicts over provider patch analysis.

## In Progress

### V1 hardening backlog

- Canonical task graph: `docs/superpowers/tasks/2026-04-28-sarathi-ui-task-graph.md`.
- Completed dogfood MVP units: `UI-00` through `UI-15`.
- UI mockup integration from FlowAI screenshots: **Done** — MetricsStrip, TemplateCards, Templates page, Workflows page, Agent stats bar, MemberTable with filter bar, History category tabs, Library nav group.
- Desktop UI usability hardening (form handlers, loading states, keyboard shortcuts): **Done**
- Recommended V1 order:
  - `V1-01`: after repo attach, run Sarathi init for existing repos or interview the user for new repos, then generate wiki/policy-pack/coding-standards/guidelines/learnings. **Foundation implemented.**
  - `V1-02`: provider settings hardening for Codex, Claude, Copilot, and local shell with path/auth/test-connection checks. **Foundation implemented.**
  - `V1-03`: richer file-level review annotations over diffs, with review findings linked back to subtasks and evidence. **Foundation implemented.**
  - `V1-04`: 100% zoom UX density pass across dashboard, Task Studio, graph, and Usage dogfood panel. **Foundation implemented.**
  - `V1-05`: packaging/startup path for a desktop shell plus bundled local service and DB location. **Foundation implemented.**
- Post-V1 board:
  - `P1`: provider execution adapters that invoke real Codex/Claude/Copilot workflows. **Foundation implemented.**
  - `P2`: repository intake refinements and deeper workspace bootstrap polish. **Foundation implemented.**
  - `P3`: broader orchestration semantics for fan-out/fan-in execution. **Foundation implemented.**
  - `P4`: learn/evolve routing improvements beyond retry/autofix policy. **Foundation implemented.**
  - `P5`: policy-driven auto-cascade scheduling for approved task graphs and newly ready units. **Foundation implemented.**
  - `P6`: provider parity hardening for Claude/Copilot native execution semantics and evidence metadata. **Foundation implemented.**
  - `P7`: provider-aware recovery classification and retry guidance. **Foundation implemented.**
  - `P8`: provider review-trace depth for persisted provider-backed findings and trace summaries. **Foundation implemented.**
  - `P9`: provider diff/spec evidence depth for persisted diff hunks, AC-linked spec references, and coverage mapping. **Foundation implemented.**
  - `P10`: provider-backed spec drift enforcement for review rejection/requeue on failing or incomplete AC mappings. **Foundation implemented.**
  - `P11`: provider-backed diff risk synthesis for reviewer-grade categories, confidence, remediation hints, and patch highlights. **Foundation implemented.**
  - `P12`: cross-hunk clustering and final review-confidence synthesis for grouped patch regions and review-level confidence verdicting. **Foundation implemented.**
- Subagent review notes from `Vichara`: remaining mock-heavy areas are packaging/startup flow and deeper provider execution adapters.
- Subagent review notes from `Vichara`: remaining mock-heavy areas are now deeper provider execution adapters and repository/workspace bootstrap polish.
- Subagent review notes from `Nirnaya`: UI-03 service boundary remains valid; UI-09 through UI-13 now supply persisted fixtures for the MVP-critical graph/evidence/review/handoff/provider flows.
- Storage follow-up from `Prajna`: introduce immutable ordered migration objects/files before the first post-v1 schema change.
- UX follow-up from user testing: normal 100% browser zoom must be a first-class acceptance check for cockpit density and responsive layout.

## Session 2026-05-03/04 — Hardening + Provider Connectivity

### Quality hardening (all 204 tests passing after each change)

- **Policy YAML error surfacing**: `_parse_policy_content` now returns `(data, error_str)` and parse errors are collected into `CompiledPolicyPack.parse_errors` instead of silently dropped. `semantic_issues()` merges parse errors into its output automatically.
- **Evidence weight validation**: Added `_weight_issues()` to `policy/validator.py` — validates `confidence_weights` sums to 1.0 ±0.01 and that `confidence_threshold` is achievable given the weight set.
- **Circuit breaker + timeout on provider dispatch**: `LocalDispatcher.dispatch()` now wraps provider calls in a `ThreadPoolExecutor` with a configurable timeout (`SARATHI_DISPATCH_TIMEOUT` env var, default 60s). Raises `DispatchTimeoutError` on exceeded timeout.
- **Evidence gap fix in engine**: `_attach_gate_result()` now computes `missing` against the canonical gate key sets (catches absent keys, not just `False` values). Logs a `WARNING` with phase, score, threshold, and missing keys when gate fails.
- **Service DB connection reuse**: Migrations now run once at `ServiceApp.__init__()`. Each thread reuses a persistent `threading.local()` connection via `_storage()` — eliminates per-request `connect()` + `run_migrations()` overhead.

### Sarathi Skill — global Claude installation

- Symlinked `Sarathi-Skill/` to `~/.claude/skills/sarathi` so `/sarathi` is available globally in Claude Code.
- Sarathi skill now appears in `/skills` and is invocable as a slash command.

### Provider CLI bridges

- **Codex** (`codex exec`): corrected flags — `--dangerously-bypass-approvals-and-sandbox` (was `-a never`), removed invalid `-C` flag (use subprocess `cwd=`), added `stdin=subprocess.DEVNULL` to prevent stdin consumption.
- **Claude** (`claude -p`): added `--output-format json` + `--dangerously-skip-permissions`. Added `_extract_claude_result()` to unwrap the Claude Code JSON envelope (`{"type":"result","result":"...","is_error":...}`). Falls back to raw output for mocks/older versions.
- **OpenCode** (new): bridge implemented using `opencode serve` HTTP API. Starts server on a free port, creates a session via `POST /session`, submits message and reads SSE stream in a background thread, falls back to polling `GET /session/{id}/message`. Server shut down after each call.
- **Copilot**: existing `gh copilot -- -p {prompt}` bridge confirmed correct; needs `gh auth login` to activate.
- **Symlinks**: `~/.local/bin/codex → /Applications/Codex.app/Contents/Resources/codex` and `~/.local/bin/opencode → /Applications/OpenCode.app/Contents/MacOS/opencode-cli` so both are in PATH.

### Live connection test results (2026-05-04)

| Provider | Status | Notes |
|----------|--------|-------|
| Claude | ✅ Connected | `--output-format json` envelope unwrapping works end-to-end |
| Codex | ✅ Bridge correct | Quota exhausted (free tier limit); bridge mechanism verified via output |
| OpenCode | ✅ Fixed | CLI bridge (`opencode run -c --dangerously-skip-permissions`) replaces HTTP |
| Copilot | ✅ Connected | `gh copilot -- -p {prompt}` bridge verified live after `gh auth login` |

## Session 2026-05-04 — Desktop UI Redesign + Radix UI

### Desktop UI — full redesign

- **Theme system**: replaced hand-rolled CSS variables with `@radix-ui/themes` v3.3.0. `<Theme accentColor="indigo" grayColor="gray" appearance={dark?"dark":"light"} radius="medium" scaling="100%" panelBackground="translucent">` wraps the app. Dark/light mode driven entirely by Radix — no manual color overrides needed.
- **Icons**: replaced `lucide-react` with `@radix-ui/react-icons` (15×15 Radix icon set) throughout nav, topbar, graph, and composer.
- **Status badges**: replaced hand-rolled `<Pill>` with Radix `<Badge variant="soft">`. Tone-to-color mapping: green/indigo/orange/red/violet/gray.
- **Layout**: sidebar + main app shell on a gray `--gray-2` canvas. Sidebar flush with right border separator. Main panel = Radix `--color-background`.
- **Button radius**: uses Radix radius scale (`--radius-3` for buttons, `--radius-4`/`--radius-5` for panels/cards) scaled by `--radius-factor` from the theme's `radius="medium"` prop.
- **Typography**: overrides `--default-font-family` and `--heading-font-family` to `Inter, SF Pro Text, -apple-system`. `-webkit-font-smoothing: antialiased`. Tighter letter-spacing on headings (`-0.025em`).

### Desktop UI — tab redesigns

- **Task Studio**: restructured from "graph-left + inspector-right" to split graph-pane (45%) + chat-pane (55%) matching reference dashboard style. Graph nodes redesigned to compact horizontal rows: `[● ST-ID  Title  [CO]]` with 3px status-colored left border. Graph/List/Schedule toolbar + progress counter + legend.
- **Tasks**: default view changed to table (ID · Title · Status · Phase · Units · Providers). Filter tabs inline. Card/board toggle still available.
- **History**: event cards replaced with timeline feed — `HH:MM · Agent` · colored severity dot · event title · meta.
- **Lifecycle**: 3-column card grid replaced with compact role table (# · Role · Name · Status · Signals).
- **Agents**: two role tables side by side — Roles (Name/Function/Status/Provider) and Providers (Name/Type/Health/Capabilities).
- **Inbox**: feed-style list with blue unread dot, title, timestamp, tag pill, and description.

### Provider model-routing policy

- `policy-pack/model-routing.md` updated with `Provider Configuration` block — Claude and Copilot configured as `CommandProviderAdapter` via `cli_bridge.main()` stdin/stdout JSON contract. Default provider set to `claude`.
- `SARATHI_DISPATCH_TIMEOUT` default raised from 60s → 300s so `CommandProviderAdapter` subprocess calls (which run real CLI tools) don't time out under the `LocalDispatcher` thread wrapper.
- Phase-aware evidence prompt: `_provider_prompt()` now includes phase-specific evidence key hints and output key hints so dispatched providers know which keys to populate.

### First live dogfood run (2026-05-04)

- `sarathi run "Fix OpenCode bridge..."` executed through Claude dispatcher end-to-end. All 12 phases completed: Route (Marga) → Brainstorm (Vichara) → Plan (Disha) → Build (Pravaha) → Verify (Nirnaya) → Review (Nirnaya) → TaskTracking (Samanvaya) → RiskCheck (Prajna) → Elegance (Sahayaka) → PhaseLog (Sutra) → Learn (Prajna). Phase artifacts persisted under `.sarathi/tasks/`.
- Gate evidence still all-False on first run — provider response format mismatch (Claude returns JSON but evidence keys weren't in the expected structure). Phase-aware prompt partially addresses this; further tuning needed.

### Desktop UI usability hardening

- **Form handlers**: Added `<form onSubmit>` to composer inputs in Orchestrator and Task Studio chat — Enter now submits properly.
- **Loading states**: Added `testingProviderId` state for Settings "Test connection" buttons — shows "Testing..." while running.
- **Card interactivity**: Saved Views cards now navigate to target views on click (Tasks/History/Settings).
- **Keyboard shortcuts**: Added `Cmd+K` global to open Orchestrator, `j/k` navigation in Task Studio graph, `Enter` to claim queued units.
- **Legend hint**: Added keyboard shortcut hint (`j/k nav · Enter claim`) in Task Studio graph legend.

### Desktop UI mockup alignment

- **Evidence tab**: Grouped into sections (Changed files with checkboxes, Tests, Review verdict, Dispatches).
- **AC coverage**: Checkbox-style with ✓/✗ indicators and covered/missing count.
- **Handoff**: Styled action buttons (No action, Prepare patch, Commit, Draft PR) with primary selection state.
- **Review tab**: Grouped into sections (Run review, Review results) with confidence badges and blocker warnings.
- **History tab**: Timeline format matching main History view with payload summary.
- **Messages tab**: Empty state when no messages or search results.
- **Styling**: Added CSS transitions (150ms), spinner animations, empty state styles, Card component supports style prop.

### OpenCode bridge fix

- **Problem**: `opencode serve` HTTP POST /session/{id}/message hangs (no response, uses polling fallback).
- **Solution**: Replaced HTTP bridge with CLI bridge using `opencode run -c --dangerously-skip-permissions --dir <workspace> -- <prompt>`.
- **Result**: Direct CLI invocation is reliable and doesn't require server lifecycle management.

## Session 2026-05-04 — Desktop UI Mockup Integration

### Source mockups (OCR'd from FlowAI reference screenshots)

Six screenshots analyzed: Dashboard-View, Agent-Teams-Lists, Agent-Teams-Details, Agent-Teams-Activity Log, Templates, Workflow-Library.

### UI additions from mockups

**Metrics strip (Dashboard-View)**
- Added `MetricsStrip` component — 4-card row (Total Runs, Success Rate, Active Workflows, AI Tokens) with delta indicators (`▲ +12%`, `▼ -2%`) at top of workspace page.

**Templates page (Templates mockup)**
- Added `TemplatesPage` route with category browser (All, Sales, Support, Marketing, E-commerce, Analytics, Finance, DevOps tabs), recently-used 5-card row, "Browse Templates" section with filter input, and Create/Import buttons.
- Added `TemplateCard` component — icon, name, trigger badge, "used X ago", use count, "Use Template" CTA.

**Workflows page (Workflow-Library mockup)**
- Added `WorkflowsPage` route with 4-metric summary strip, search input, status filter dropdown (All/Active/Paused/Draft/Expired), full workflow table (name, trigger pill, total runs, success rate color-coded, last run, status badge, View/Edit links), and "Showing X of Y" pagination row.

**Agents page — stats bar and member table (Agent-Teams-Lists/Details)**
- Added `agent-stats-bar` — 5 stat items (Total Members, Active Now, Pending Invites, Seats Used, Seats Remaining) above the member table.
- Added `MemberTable` with filter bar (search, Role/Dept/Status dropdowns), avatar initials, name+email, role, department, contact, status badge, joined date, and activity progress bar.
- Added `+ Invite Member` and `Export CSV` action buttons to agents header.
- Renamed left table to "Agent Roles", right table to "Providers".

**History page — activity log enhancements (Agent-Teams-Activity Log)**
- Added `activity-category-tabs` — filter tabs for All, Workflow, Security, Settings, Lifecycle, Billing.
- Added search input for event text filtering.
- Enhanced `timeline-item` rendering to show severity dots, source/task context, and structured metadata for both live (SQLite) and demo events.

**Sidebar — Library nav group**
- Added new "Library" nav group with Templates and Workflows routes.

**New routes and types**
- Added `templates` and `workflows` to `Route` type and `routes`/`routeIcons` maps.
- Added `MetricCard`, `TemplateCard`, `WorkflowItem`, `TeamMember` types and mock data arrays to `mockData.ts`.

**New CSS classes**
- `.metrics-strip`, `.metric-card`, `.metric-card-label`, `.metric-card-value`, `.metric-card-delta` (positive/negative variants)
- `.template-cards`, `.template-card`, `.template-card-icon`, `.template-card-name`, `.template-card-meta`, `.template-card-used`, `.template-card-uses`
- `.workflow-table-wrap`, `.workflow-filter-bar`, `.workflow-trigger`
- `.member-filter-bar`, `.member-avatar`, `.activity-bar`, `.activity-bar-fill`
- `.activity-category-tabs`
- `.agent-stats-bar`, `.agent-stat-item`, `.agent-stat-value`, `.agent-stat-label`
- `.seat-usage`, `.seat-usage-bar`, `.seat-usage-fill`

### Verification

- `npm --prefix desktop run build`: ✓ clean (359 KB bundle)
- `python3 -m pytest`: 204 passed

## Session 2026-05-04 — Hardening + Provider Connectivity

## Next Session Start Here

- Provider-backed full diff annotation depth is the next engineering priority.
- Copilot bridge verified live — add `copilot` as a second provider in `policy-pack/model-routing.md` and run a task through it to validate multi-provider routing.
- **OpenCode bridge FIXED**: Replaced HTTP serve bridge with CLI bridge (`opencode run -c --dangerously-skip-permissions`).
- Gate evidence quality: the dispatched Claude provider needs to return `evidence` dict with phase-specific keys (`alternative_approaches_considered`, `risks_identified`, etc.). Current prompt hints exist; may need a structured schema in the prompt.
- Desktop: `npm --prefix desktop run build` passes cleanly. Re-run `npm --prefix desktop audit --omit=dev` before next ship.
- Desktop usability hardening DONE: form handlers, loading states, card clickability, keyboard shortcuts (`Cmd+K`, `j/k`, `Enter`).

- Use the Sarathi skill and start with provider-backed full diff annotation depth so rich hunks can evolve into deeper reviewer-quality line annotations and patch-region reasoning.
- Do not re-plan MVP: `M6` is complete and verified.
- Provider execution is now service-backed: Codex uses a native CLI bridge, Copilot/Claude can route through native CLI bridges when installed, custom JSON-capable command shims are supported per workspace, and native Claude/Copilot runs now execute from the workspace root with persisted CLI-family/invocation metadata.
- OpenCode now uses CLI bridge instead of HTTP serve: more reliable, no server lifecycle.
- Recovery loops now understand provider context: native/provider artifacts can be classified as `auth`, `provider_offline`, or `native_cli_failure`, and that classification is passed into bounded recovery dispatch/guidance.
- Review loops now understand provider traces: dispatch evidence can carry `review_trace` findings, diff summaries count provider-backed trace findings/providers, and Task Studio renders trace-backed findings instead of only generic changed-file scope entries.
- Review loops now understand provider diff/spec evidence: dispatch evidence can carry `diff_trace` hunks and `spec_trace` references, approved reviews persist those regions plus AC links, and AC coverage now maps to explicit evidence instead of blanket task-level coverage when structured references are present.
- Review gates now enforce provider-backed AC mappings: if structured spec references are partial or failing, the review is rejected and the affected unit is requeued instead of being auto-approved.
- Review summaries now synthesize provider diff risk: persisted diff findings can carry category, confidence, and suggestion data, and review metadata exposes blocker counts, confidence averages, category lists, and patch-region highlights.
- Review summaries now cluster related hunks into patch regions and emit a final review-confidence verdict with explicit reasons, so provider diff analysis is easier to trust and scan.
- Repository intake is now deeper and non-destructive: preview exposes bootstrap status plus repo inspection, and initialize creates the full canonical policy-pack/wiki scaffold while preserving existing repo-owned files.
- Broader orchestration semantics are now in place: graph snapshots expose ready/active/blocked/waiting-human frontiers plus fan-out/fan-in metadata, and task status follows live graph coordination state.
- Learn/routing depth is now closed for the first useful loop: provider-failure learnings can generate accepted routing hints, and those hints now influence runtime phase routing.
- Scheduler depth now has a policy-backed foundation: `graph_execution.auto_schedule_ready_nodes` can auto-start ready units after Task graph approval and after blocker completion.
- Keep repo mutation gated: preview first, explicit approval before creating or updating repo-local Sarathi files.
- Re-run acceptance after each post-V1 tranche: `python3 -m pytest`, `npm --prefix desktop run build`, `npm --prefix desktop audit --omit=dev`, `python3 -m src.cli validate ./policy-pack`.

## Pending

### Learn/evolve closing loop

- Deeper routing strategy changes from accepted learnings beyond retry/autofix policy.

### Provider and review depth

- Deeper line-level review annotations over full diffs once real provider-backed diffs exist.
- Spec-to-code mismatch detection and reviewer verdicting over provider-supplied requirement mappings.
- Automated patch-region scoring and reviewer confidence synthesis over provider-supplied diff hunks. **Foundation implemented.**
- Cross-hunk clustering and final review-confidence verdicting over grouped patch regions. **Foundation implemented.**
- Next: multi-provider confidence fusion and cross-trace region deduplication.

### Scheduler and orchestration depth

- Extend auto-cascade scheduling into policy-driven provider dispatch for fully hands-off fan-out/fan-in flows when a workspace explicitly allows it.

### Desktop orchestration platform

- Workspace bootstrap reconciliation for repo updates beyond the current create-missing/preserve-existing contract.

## Reviewer Validation Notes

Concrete remaining test/doc gaps identified during validation:

- Add provider-backed recovery tests for native Codex/Copilot/Claude dispatch once provider-specific retry semantics are richer than the current shared bridge contract.
- Add review tests for deeper full-diff annotation parsing and spec-to-code mismatch handling once reviewer-grade provider diffs exist.
- User-facing docs for `sarathi status`, `sarathi resume`, `sarathi log` escalation summaries, and `sarathi proposals` - **DONE**: Updated README.md and core-policy-interface-mapping.md
- `docs/core-policy-interface-mapping.md` aligned with compiled policy/runtime seams - **DONE**: All phases now show ✓ Implemented/Enhanced status

## Completed Updates (2026-04-24)

Documentation updates completed:
- `docs/core-policy-interface-mapping.md` - Updated all phase status from "Pending" to "✓ Implemented" where applicable
- `README.md` - Added documentation for new CLI commands (`status`, `resume`, `proposals`, `agents`)

## Suggested Next Step

The next highest-leverage step is:

`Provider-backed full diff annotation depth`

That means teaching Sarathi to produce reviewer-grade line-level diff annotations with provider trace depth, so rich hunks can evolve into deeper line-level reasoning and patch-region scoring.

Multi-provider confidence fusion follows after.
