# Changelog

All notable changes to Sarathi are documented here.

## Unreleased

### Added

- Added `sarathi autoresearch` (`register`/`evidence`/`verdict`/`list`) for
  pre-registering hypotheses and recording evidence and verdicts as an
  append-only `.sarathi/autoresearch.jsonl` log.

### Changed

- Made recovery failure classification, engine gate thresholds and
  remediation text, and the learn-evolve deviation threshold
  policy-configurable via `escalation.md`/`review.md` instead of hardcoded in
  the engine and runtime.
- Propagated `HarnessConfig` into graph-node dispatch (FANOUT/JUDGE/
  SYNTHESIZE) so child-task dispatch declares a harness before running,
  matching the single-task ROUTE path.

### Fixed

- Fixed `sarathi autoresearch` crashing on a corrupted store file; malformed
  JSONL lines are now skipped instead of crashing every future invocation,
  and `KeyError` messages no longer print with stray quotes.
- Fixed a `mypy` duplicate-module error caused by the dual `src`/relative
  import pattern, via `[tool.mypy]` config rather than a package rename.
- Fixed stale CLAUDE.md documentation (service-layer file-size claims) and
  added the missing `policy-pack/EXAMPLE/workflow-patterns.md`.

## 0.3.0 - 2026-06-17

### Added

- Added the Sarathi WebUI cockpit: Dashboard, Task Studio, Needs You, History,
  Settings, Agents, Knowledge, Skills, Wiki, Proposals, Usage, and Workspace
  views backed by the local service API.
- Added the Electron desktop shell that launches the shared Sarathi service and
  web cockpit with runtime configuration injection.
- Added project-scoped task chat from the Dashboard and task-scoped chat in
  Task Studio, including provider-backed replies through the same free-form
  chat path used by the TUI.
- Added governed Task Studio workflows for PRD/AC approval, task-graph drafting,
  ready-unit scheduling, provider dispatch, evidence review, final handoff, and
  repository-action gates.
- Added service-owned workspace and project APIs so the WebUI, Electron app,
  TUI, and CLI can share the same persisted state.
- Added provider Settings for Claude, Codex, Copilot, OpenCode, and local
  deterministic execution, including connection testing and provider health.
- Added role-derived provider permissions with `read_only`, `read_write`, and
  `full` modes instead of relying on global provider auto-approval config.
- Added Sarathi session-start hooks and bundled policy guidance for Claude,
  OpenCode, and other agent sessions to auto-detect and collaborate with
  Sarathi.
- Added Docker-compatible sandbox execution with Docker and Podman support,
  environment-based runtime selection, and daemon-gated integration tests.
- Added deterministic repo wiki generation and workspace bootstrap behavior that
  preserves existing human-authored policy and wiki files.
- Added service auth, SSE/event polling, OpenAPI documentation, static file
  serving, session/co-drive APIs, operational projections, and usage stats.

### Changed

- Made the local service the source of truth for cockpit state, task messages,
  approvals, graph projections, evidence, review runs, handoff, projects, and
  workspace knowledge.
- Updated `sarathi init` and desktop workspace bootstrap to create or reuse
  policy packs and local wiki assets without overwriting user-authored files.
- Updated provider dispatch to compile compact task-specific context packs and
  derive permission mode from agent role and task metadata.
- Updated Task Studio provider selection to normalize provider IDs before
  dispatching graph units.
- Updated dashboard task grouping and project filters to use live service
  projections rather than mock data.

### Fixed

- Fixed stale approval-gate handling so superseded pending gates do not keep the
  Task Studio header in `awaiting_approval`.
- Fixed graph approval dispatch so approving the task graph schedules ready work
  when auto-scheduling returns no units.
- Fixed review/handoff flow so an approved review can be created from already
  completed subtasks that have dispatch evidence.
- Fixed Review tab refresh behavior so running a review updates the visible
  review list without requiring a page reload.
- Fixed OpenCode project configuration by removing reliance on the invalid
  legacy `autoapprove` setting.
- Fixed desktop Python runtime selection so the Electron app starts with a usable
  interpreter.

### Validation

- Full Python suite passed locally after merge: `1087 passed, 8 skipped`.
- Web production build passed: `npm --prefix web run build`.
- Live browser walkthrough verified PRD approval, task-graph approval, DAG
  dispatch, review approval, and handoff generation against the local service.
