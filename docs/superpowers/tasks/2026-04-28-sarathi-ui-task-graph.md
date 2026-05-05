# Sarathi UI Dogfood Task Graph

Date: 2026-04-28
Workspace: Sarathi App
Owner: Sarathi
Planner: Disha
Complexity: High
State: active

## Current Checkpoint

The first UI foundation slice is implemented as a local React/Vite desktop package under `desktop/`.
The SQLite storage foundation and local service API boundary are now in place; workspace repo intake, provider dispatch, durable review loops, final handoff, repository-action mediation, service-backed operational views, dogfood acceptance, and learn-loop closure are implemented. The desktop dogfood MVP task graph is complete.

Fresh evidence:

- `npm --prefix desktop run build` passed on 2026-04-28.
- `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities` on 2026-04-28.
- `python3 -m pytest` passed with `167 passed` on 2026-04-29 after UI-13 handoff/repository-action tests landed.
- `python3 -m pytest` passed with `171 passed` on 2026-04-29 after UI-15 dogfood acceptance tests landed.
- `python3 -m pytest` passed with `177 passed` on 2026-05-01 after V1-03 file-level review annotations landed.
- `npm --prefix desktop run build` passed on 2026-05-01 after V1-03 Task Studio review/evidence rendering landed.
- `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities` on 2026-05-01.
- `python3 -m src.cli validate ./policy-pack` passed on 2026-05-01 with `22 PASS, 2 DRIFT, 0 TODO`.
- `npm --prefix desktop run build` passed on 2026-05-01 after V1-04 100% zoom density tuning landed.
- `python3 -m pytest` passed with `182 passed` on 2026-05-01 after V1-05 desktop launcher tests landed.
- `python3 -m pytest` passed with `185 passed` on 2026-05-01 after P1 provider adapter routing landed.
- `python3 -m pytest` passed with `186 passed` on 2026-05-01 after P2 workspace bootstrap refinement coverage landed.
- `python3 -m pytest` passed with `188 passed` on 2026-05-01 after P3 orchestration coordination coverage landed.
- `python3 -m pytest` passed with `195 passed` on 2026-05-02 after P4 learning-feedback routing and P5 policy-driven auto-cascade scheduling landed.
- `python3 -m pytest` passed with `197 passed` on 2026-05-02 after P6 provider parity hardening landed.
- `python3 -m pytest` passed with `199 passed` on 2026-05-02 after P7 provider-aware recovery classification landed.
- `python3 -m pytest` passed with `200 passed` on 2026-05-02 after P8 provider review-trace depth landed.
- `python3 -m pytest` passed with `201 passed` on 2026-05-02 after P9 provider diff/spec evidence depth landed.
- `python3 -m pytest` passed with `202 passed` on 2026-05-02 after P10 provider-backed spec drift enforcement landed.
- `python3 -m pytest` passed with `203 passed` on 2026-05-02 after P11 provider-backed diff risk synthesis landed.
- `python3 -m pytest` passed with `204 passed` on 2026-05-02 after P12 cross-hunk clustering and review-confidence synthesis landed.
- `npm --prefix desktop run build` passed on 2026-05-02 after P5 scheduler changes.
- `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities` on 2026-05-02.
- `python3 -m src.cli validate ./policy-pack` passed on 2026-05-02 with `22 PASS, 2 DRIFT, 0 TODO`.
- `python3 -m src.service.desktop --print-config --token fixed-token` returned the expected runtime/session configuration on 2026-05-01.
- `python3 -m src.service.desktop --service-port 8876 --vite-port 5174` successfully booted the service and Vite UI together on 2026-05-01 before clean shutdown.
- `python3 -m src.runtime.providers.cli_bridge --provider codex --path /Applications/Codex.app/Contents/Resources/codex --workspace-root /Users/sweethome/Work/Skills/Sarathi` returned a successful normalized child-task dispatch payload on 2026-05-01.
- `python3 -m pytest tests/test_operational_views.py tests/test_handoff_repository_action.py tests/test_review_loop.py` passed with `7 passed` on 2026-04-29 after UI-14 operational-view tests landed.
- `python3 -m pytest tests/test_dogfood_acceptance.py tests/test_operational_views.py tests/test_handoff_repository_action.py` passed with `7 passed` on 2026-04-29 after UI-15 dogfood acceptance tests landed.
- `python3 -m src.cli validate ./policy-pack` passed on 2026-04-29 with `22 PASS, 2 DRIFT, 0 TODO`.
- `npm --prefix desktop run build` passed on 2026-04-29 after UI-08 service-backed Task Studio wiring landed.
- `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities` on 2026-04-29.
- `python3 -m pytest tests/test_service_api.py tests/test_service_launcher.py tests/test_workspace_intake.py` passed with `19 passed` on 2026-04-28.
- `python3 -m pytest tests/test_task_creation.py tests/test_service_api.py tests/test_storage.py` passed with `19 passed` on 2026-04-28.
- `Vichara` reviewed the current UI/data model and identified durable tracking gaps to address in UI-02 through UI-15.
- `Nirnaya` and `Prajna` reviewed UI-02; workspace-scope constraints, parent-directory creation, and FK/query indexes were added before closure.
- `Sutra` implemented the callable local service plus stdlib HTTP adapter with token auth, correlation IDs, typed errors, workspace/task persistence, approval/event persistence, and SSE snapshot endpoint for UI-03.
- `Nirnaya` reviewed UI-03 and confirmed the service boundary; UI-09 through UI-13 have since replaced the MVP-critical graph, evidence, review, handoff, and provider placeholders with durable data contracts.
- `Vichara/Sutra` added UI-04 repository intake storage and service routes: preview, approved attach, list, dirty-state warning, Sarathi-doc readiness, and lifecycle event recording.
- `Pravaha` wired the workspace page to the local service through a typed desktop API client with workspace list/create/select, repository preview, approved attach, persisted repo reload, CORS, and a `python -m src.service` launcher path.
- `Disha/Sarathi` added UI-05 durable task initiation: Orchestrator prompt creates a `prd_pending` task draft, task-scoped user/Sarathi messages, PRD/AC metadata, pending PRD/AC approval gate, and lifecycle events.
- `Disha/Sutra` added UI-06 durable task graph generation: graph creation requires approved PRD/AC, persists subtask nodes with roles/providers/task packets/evidence requirements, returns dependency edges, and opens a pending Task graph approval gate before execution.
- `Pravaha/Samanvaya` added UI-07 service-backed Task Dashboard: workspace task summaries include approval state, graph state, role/provider lanes, blocked counts, quick filters, board/list mode, and click-through selected-task context for Task Studio.
- `Pravaha/Sutra` added UI-08 service-backed Task Studio: selected tasks now load a single studio snapshot with task, graph, task-scoped messages, approval gates, and lifecycle events; graph/list views render persisted nodes and dependency edges; task messages support search and persisted composer sends.
- `Sutra/Pravaha` added UI-09 graph scheduler and subtask lifecycle: scheduling requires approved Task graph, starts all ready sibling units, persists lifecycle events, supports unit transitions, and unblocks downstream units when all blockers complete; Task Studio exposes schedule and transition controls.
- `Marga/Sutra` added UI-10 provider health and local deterministic dispatch: provider health lists local/Codex/Claude/Copilot lanes, in-progress subtasks can dispatch to the local deterministic provider, dispatch/evidence records persist to SQLite, and Task Studio shows provider output evidence.
- `Sutra/Samanvaya` added UI-11 SSE/polling auto-updates: browser EventSource can authenticate through a local stream token, the shell shows live stream state, and workspace/task/provider/studio surfaces refetch when service events arrive or polling detects changes.
- `Nirnaya/Sutra` added UI-12 evidence review loop and AC coverage: review runs persist, dispatch evidence is linked into AC coverage, approved reviews complete evidenced units, rejected reviews requeue missing-evidence units, and Task Studio can run code/functional review.
- `Sarathi/Samanvaya` added UI-13 final handoff and repository-action approval: reviewed tasks create a user-facing handoff dossier, AC coverage and repository-action state persist, pending Git/PR decisions are modeled as explicit approval gates, and Task Studio exposes create/approve controls.
- `Sahayaka/Sutra` added UI-14 operational views: a workspace-scoped service snapshot now powers durable lifecycle, history, diagram, and usage tabs from persisted SQLite records while retaining demo fallbacks.
- `Samanvaya/Sarathi` added UI-15 dogfood acceptance and learn loop: a read-only "Built with Sarathi" acceptance dossier proves the full loop, and an explicit approval action writes accepted reusable learning to workspace `learnings.md`.
- `Marga/Sutra` added V1-02 provider settings hardening: Settings can persist and test Codex/Claude/Copilot/local path/auth state per workspace, provider health is durable, and migration coverage preserves workspace-first isolation.
- `Nirnaya/Pravaha` added V1-03 file-level review annotations: local execution evidence now carries deterministic changed files, review runs persist structured findings linked to subtasks/evidence, and Task Studio renders those findings in evidence/review tabs.
- `Pravaha/Sahayaka` added V1-04 100% zoom density tuning: the cockpit shell, topbar, cards, Task Studio split, graph nodes, and responsive breakpoints are tighter so normal laptop zoom no longer depends on shrinking the browser.
- `Sutra/Pravaha` added V1-05 startup foundation: `sarathi-desktop` now launches the local service and UI as one session, generates a per-run token, writes runtime config for the shell, and restores a safe runtime stub on shutdown.
- `Marga/Sutra` added P1 provider execution routing: non-local subtask dispatch now resolves workspace provider settings into service-backed command adapters, Codex uses a native `codex exec` bridge, and Claude/Copilot/custom command shims can participate through the same normalized dispatch/evidence contract.
- `Vichara/Sutra` added P2 repository bootstrap refinement: preview now exposes repo inspection plus missing/present bootstrap artifacts, and initialize now creates the full canonical policy-pack/wiki scaffold while preserving existing repo-owned docs and policy files.
- `Sutra/Samanvaya` added P3 orchestration semantics: graph snapshots now expose ready/active/blocked/waiting-human frontiers plus fan-out/fan-in coordination metadata, and task status is refreshed from live subtask graph state instead of only manual phase stamps.
- `Vichara/Marga` added P4 learning-feedback routing closure: provider-failure signals now create routing-hint proposals and accepted proposals can steer phase-level provider routing at runtime.
- `Sutra/Samanvaya` added P5 policy-driven auto-cascade scheduling: approved Task graphs can auto-start ready sibling units and newly unblocked ready units can auto-schedule after blocker completion when workspace policy enables it.
- `Marga/Sutra` added P6 provider parity hardening: native Claude and Copilot dispatch now execute from the workspace root, preserve provider-specific CLI invocation shape, and persist native CLI metadata into dispatch evidence/artifacts.
- `Marga/Nirnaya` added P7 provider-aware recovery depth: bounded recovery loops now carry provider context forward, classify auth/offline/native-CLI failures, and emit provider-specific retry guidance instead of generic recovery text.
- `Nirnaya/Sutra` added P8 provider review-trace depth: provider dispatch evidence can now carry structured `review_trace` findings, review runs persist those findings with provider/file/line metadata, and Task Studio surfaces trace summaries and trace-backed findings.
- `Nirnaya/Sutra` added P9 provider diff/spec evidence depth: provider dispatch evidence can now carry `diff_trace` hunks and `spec_trace` requirement mappings, review runs persist those regions/AC links, and AC coverage becomes evidence-aware when structured spec references exist.
- `Nirnaya/Sutra` added P10 provider-backed spec drift enforcement: failing or partial structured `spec_trace` evidence now rejects review, records coverage gaps, and requeues units instead of auto-approving them.
- `Nirnaya/Sutra` added P11 provider-backed diff risk synthesis: diff hunks can now carry category/confidence/suggestion fields, review summaries expose blocker counts and confidence/category rollups, and Task Studio renders patch highlights with remediation hints.
- `Nirnaya/Sutra` added P12 cross-hunk clustering and review-confidence synthesis: related diff hunks now roll into grouped patch regions, review metadata emits an overall confidence verdict plus reasons, and Task Studio surfaces those grouped regions.
- User-observed density issue: the cockpit needed zoom reduction around 67% to view comfortably; UI-07/UI-08 must include a 100% zoom responsive-density pass for normal laptop widths.

## Main Task

Build the Sarathi desktop dogfood MVP: a local-first cockpit where a user can create a workspace-scoped task, approve PRD/AC and task graph gates, inspect subtasks in graph/list form, see messages/evidence/reviews/handoff, and watch persisted SSE-backed state update without the renderer owning orchestration logic.

## Lifecycle States

Main task: `draft -> prd_pending -> graph_pending -> queued -> in_progress -> review -> handoff -> repository_action_pending -> done`

Subtasks: `created -> queued -> in_progress -> review -> completed`

Exception states: `blocked`, `waiting_human`, `failed`, `skipped`, `paused`

## Role Owners

| Role | Responsibility |
| --- | --- |
| Sarathi | orchestration owner and final handoff gate |
| Disha | plan, task graph, acceptance criteria |
| Marga | routing and provider capability decisions |
| Sutra | service boundary, events, task graph state flow |
| Pravaha | implementation execution |
| Vichara | repo/workspace discovery and context packets |
| Prajna | architecture tradeoff checks |
| Nirnaya | review, verification, acceptance coverage |
| Samanvaya | cross-subtask coordination and unblock decisions |
| Sahayaka | docs, fixtures, demo-safe polish |

## Task Graph

| ID | Task | Owner | State | Depends On | Acceptance Criteria | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| UI-00 | Create dogfood workspace seed and tracker | Disha | completed | none | Tracker captures owners, dependencies, gates, verification, learn-loop notes; no non-target files edited. | `git diff -- docs/superpowers/tasks/2026-04-28-sarathi-ui-task-graph.md` |
| UI-01 | Establish desktop shell and navigation | Pravaha | completed | UI-00 | Shell shows workspace, route, service/SSE/storage state, sidebar nav, command entry, and degraded mode. | `npm --prefix desktop run build` |
| UI-02 | Add SQLite storage and migrations | Sutra | completed | UI-00 | Tables exist for workspaces, tasks, subtasks, dependencies, messages, approvals, dispatches, events, evidence, reviews, handoffs, providers, settings; child records enforce workspace/task consistency. | `python3 -m pytest tests/test_storage.py tests/test_migrations.py`; `python3 -m pytest` |
| UI-03 | Add local service API boundary | Sutra | completed | UI-02 | Renderer calls REST/SSE only; workspace, task, approval, and event routes persist/read durable records with correlation IDs and typed errors; graph, evidence, review, handoff, and provider routes expose stable placeholder schemas for later durable wiring; token auth and request-size/JSON safeguards exist. | `python3 -m pytest tests/test_service_api.py`; `python3 -m pytest` |
| UI-04 | Implement workspace setup and repo intake preview | Vichara | completed | UI-02 UI-03 | Storage/service can create/select workspace records, preview repo intake without mutation, require approval before attach, list attached repos, and record lifecycle events; renderer can initialize/select/create service workspaces, preview repos, approve attach, and reload persisted repos when configured with the local service. | `python3 -m pytest tests/test_workspace_intake.py tests/test_service_api.py tests/test_service_launcher.py`; `npm --prefix desktop run build` |
| UI-05 | Implement task initiation chat to PRD/AC draft | Disha | completed | UI-01 UI-03 UI-04 | Chat creates a workspace-scoped `prd_pending` task draft, PRD/AC metadata, pending PRD/AC approval gate, durable user/Sarathi messages, and lifecycle events; renderer calls the local service when configured with demo fallback otherwise. | `python3 -m pytest tests/test_task_creation.py`; `npm --prefix desktop run build` |
| UI-06 | Implement task graph generation and approval gate | Disha | completed | UI-05 | Multi-unit graph includes roles, providers, dependencies, task packets, evidence requirements, and blocks execution until graph approval; graph generation requires approved PRD/AC and records lifecycle/approval events. | `python3 -m pytest tests/test_task_graph_generation.py`; `npm --prefix desktop run build` |
| UI-07 | Build task dashboard and saved filters | Pravaha | completed | UI-05 | Board/list filters by approval state, graph state, blocked units, provider lane, and persisted task status; clicking a task opens Task Studio with selected-task context. | `python3 -m pytest tests/test_task_dashboard.py`; `npm --prefix desktop run build` |
| UI-08 | Build Task Studio graph/list/message surface | Pravaha | completed | UI-06 UI-07 | Graph default plus list toggle, node states, dependency edges, packet inspector, task-scoped messages/search/composer. | `python3 -m pytest tests/test_task_studio.py`; `npm --prefix desktop run build` |
| UI-09 | Wire graph scheduler and subtask lifecycle | Sutra | completed | UI-06 | Ready units dispatch in dependency order; non-blocked siblings continue; block/unblock/waiting-human events persist. | `python3 -m pytest tests/test_task_lifecycle_scheduler.py`; `npm --prefix desktop run build` |
| UI-10 | Add provider health and local deterministic dispatch | Marga | completed | UI-03 UI-09 | Provider settings validate Codex, Claude, Copilot, local; dispatch result records commands, changed files, evidence refs, retryable status. | `python3 -m pytest tests/test_provider_dispatch.py`; `npm --prefix desktop run build` |
| UI-11 | Add event persistence and SSE/polling updates | Sutra | completed | UI-03 UI-09 | Persist before publish; task, subtask, message, dispatch, review, artifact events update UI; polling fallback shown on disconnect. | `python3 -m pytest tests/test_service_api.py::test_http_sse_stream_accepts_query_token_for_browser_eventsource`; `npm --prefix desktop run build` |
| UI-12 | Add evidence, review loop, and AC coverage | Nirnaya | completed | UI-08 UI-09 UI-10 | Subtasks enter review with evidence; rejected review requeues work; final code/functional reviews produce AC coverage matrix. | `python3 -m pytest tests/test_review_loop.py`; `npm --prefix desktop run build` |
| UI-13 | Add handoff and repository action approval | Sarathi | completed | UI-04 UI-12 | Handoff summarizes changes, completed units, checks, risks; commit/PR/export actions require explicit final approval and git snapshot. | `python3 -m pytest tests/test_handoff_repository_action.py`; `npm --prefix desktop run build` |
| UI-14 | Add diagrams, lifecycle, history, usage dogfood views | Sahayaka | completed | UI-08 UI-11 UI-12 | Dependency, lifecycle, review-loop, and handoff diagrams are durable artifacts; history/usage views reflect real events. | `python3 -m pytest tests/test_operational_views.py`; `npm --prefix desktop run build` |
| UI-15 | Run dogfood acceptance and learn loop | Samanvaya | completed | UI-13 UI-14 | Demo-safe dogfood workspace proves PRD/AC, task graph, evidence, review loops, handoff, approved learnings, and redacted release dossier. | `python3 -m pytest tests/test_dogfood_acceptance.py`; `python3 -m src.cli validate ./policy-pack` |

## Dependency Edges

```text
UI-00 -> UI-01
UI-00 -> UI-02 -> UI-03 -> UI-04
UI-01 + UI-03 + UI-04 -> UI-05 -> UI-06
UI-05 -> UI-07
UI-06 + UI-07 -> UI-08
UI-06 -> UI-09
UI-03 + UI-09 -> UI-10
UI-03 + UI-09 -> UI-11
UI-08 + UI-09 + UI-10 -> UI-12
UI-04 + UI-12 -> UI-13
UI-08 + UI-11 + UI-12 -> UI-14
UI-13 + UI-14 -> UI-15
```

## Approval Gates

| Gate | Blocks | Owner | Evidence Required |
| --- | --- | --- | --- |
| Setup | UI-04 | Sarathi | workspace ID, repo path, policy path, provider scope |
| PRD/AC | UI-06 | Disha | approved PRD, acceptance criteria, complexity route |
| Task graph | UI-09 UI-10 | Disha | graph nodes, dependencies, owners, providers, packet summaries |
| Execution policy | UI-10 UI-13 | Marga | command class, risk level, approval or policy auto-approval event |
| Review override | UI-12 | Nirnaya | finding severity, retry count, human decision |
| Repository action | UI-13 | Sarathi | git status, changed files, handoff, explicit commit/PR decision |

## Global Acceptance Criteria

- Workspace is mandatory for every task, subtask, event, provider, artifact, review, handoff, and learning record.
- Renderer never invokes provider CLIs or mutates repositories directly.
- SQLite is canonical; vault files and diagrams are portable projections.
- SSE is an invalidation stream only; UI refetches durable state.
- Every completed unit links evidence and review state.
- Final completion includes AC coverage, review verdicts, verification commands, residual risks, and repository-action approval state.
- Dirty worktree and external git changes are surfaced before execution or handoff.
- Core cockpit flows must be usable at 100% browser zoom on laptop-sized screens without requiring the user to zoom out to understand the page.

## Verification Commands

Current package commands:

```bash
python3 -m pytest
npm --prefix desktop run build
npm --prefix desktop audit --omit=dev
git diff -- docs/superpowers/tasks/2026-04-28-sarathi-ui-task-graph.md
```

Future root-workspace commands after package/workspace setup exists:

```bash
sarathi validate ./policy-pack
python -m pytest
npm run lint --workspace desktop
npm run test --workspace desktop -- --run
npm run build --workspace desktop
git diff -- docs/superpowers/tasks/2026-04-28-sarathi-ui-task-graph.md
```

## Learn-Loop Notes

- Record one learning per milestone in workspace `learnings.md` only after Nirnaya links evidence and Samanvaya confirms it is reusable.
- Candidate learning tags: `workspace-first`, `renderer-thin`, `persist-before-publish`, `approval-gate`, `dogfood-fixture`, `provider-routing`.
- Reject learnings without evidence refs, affected task IDs, and a regression command.
- Promote a learning only when the dogfood acceptance test remains green and the pattern improves future task setup or verification.
- UI-03 should introduce immutable ordered migration files or migration objects before the next schema bump; mutating `_MIGRATION_001` is acceptable only while no released SQLite database exists.
- UI-03 avoided a local `HTTPServer` startup stall by bypassing reverse DNS in `server_bind`; keep this as a service harness regression check when the API server is split into modules.
- UI-03 placeholder route smoke tests remain useful for the service boundary; UI-09 through UI-13 now add persisted graph/evidence/review/handoff/provider fixtures for MVP-critical surfaces.
- UI-15 closes the first dogfood MVP loop: future slices should extend this acceptance dossier instead of creating parallel demo-only proof surfaces.

## Resume Checkpoint

- MVP task graph is complete: `UI-00` through `UI-15`.
- Last full verification: `python3 -m pytest` passed with `204 passed`; `npm --prefix desktop run build` passed; `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities`; `python3 -m src.cli validate ./policy-pack` passed with `22 PASS, 2 DRIFT, 0 TODO`.
- Local service was restarted on `http://127.0.0.1:8765` and a demo-safe dogfood task was seeded so the "Built with Sarathi" acceptance panel can show `passed`.
- `V1-01 Repository initialization/interview flow` foundation is implemented: attached repos can be explicitly initialized, new repos require interview data, and generated Sarathi docs are written only after approval.
- `V1-02 Provider settings hardening` foundation is implemented: path/auth/test-connection checks persist per workspace and the Settings page can update provider health.
- `V1-03 Richer file-level review annotations` foundation is implemented: review runs now persist file-scoped findings with subtask/evidence links and Task Studio renders them.
- `V1-04 100% zoom UX density pass` foundation is implemented: shell/layout spacing and breakpoints are tuned for normal laptop zoom.
- `V1-05 Desktop packaging and startup path` foundation is implemented: the launcher now boots service and UI together with runtime config/session wiring.
- `P4 Learn/evolve routing improvements` foundation is implemented: accepted provider-failure learnings can now feed phase-level provider routing.
- `P5 Policy-driven auto-cascade scheduling` foundation is implemented: `graph_execution.auto_schedule_ready_nodes` can auto-start ready units after graph approval and downstream unblocks.
- `P6 Provider parity hardening` foundation is implemented: native Claude/Copilot dispatch now runs in the workspace root and records provider-specific invocation metadata.
- `P7 Provider-aware recovery classification` foundation is implemented: bounded recovery loops now understand provider context and retry class.
- `P8 Provider review-trace depth` foundation is implemented: review loops and Task Studio now consume persisted provider-backed trace findings.
- `P9 Provider diff/spec evidence depth` foundation is implemented: review loops and Task Studio now consume persisted provider diff hunks and AC-linked spec references.
- `P10 Provider-backed spec drift enforcement` foundation is implemented: structured provider spec evidence can now block review and requeue work when AC mappings are partial or failing.
- `P11 Provider-backed diff risk synthesis` foundation is implemented: review loops and Task Studio now surface diff blockers, confidence, categories, patch highlights, and remediation hints.
- `P12 Cross-hunk clustering and final review-confidence synthesis` foundation is implemented: review loops and Task Studio now expose grouped patch regions and a final confidence verdict with reasons.
- Next tranche should be tracked separately as multi-provider confidence fusion and cross-trace region deduplication.
- Preserve the key product rule for V1: repository writes require preview plus explicit approval.
