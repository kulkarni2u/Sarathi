# Sarathi Desktop Orchestration Studio Status

Updated: 2026-05-09

## Goal

Turn Sarathi desktop into a trustworthy orchestration cockpit centered on `workspace -> project -> task`, using real persisted SQLite-backed data on primary surfaces and eliminating mock/demo behavior from live flows.

## Current State

- Backend trust slice is complete.
- Workspace projects are now persisted in SQLite.
- Desktop shell now creates and lists projects through the service instead of `localStorage`.
- Dashboard queries are project-scoped instead of workspace-wide.
- Explicit env API config now overrides stale runtime-script config.
- Project detail/task studio now respects project-scoped task resolution in the live flow.
- Support-surface hardening is underway and the first four slices are now real-data aware:
  - `Settings` is workspace-scoped instead of hardcoding a single workspace lookup.
  - `Inbox` is now an operational attention queue instead of a generic pending list.
  - `Agents` now shows provider readiness plus dispatch/budget posture from operational views.
  - `Task Studio` now computes and surfaces a clear next action / current posture instead of showing only raw gate data.
- QA hygiene worker completed: repeated validation can now run against an isolated temp DB instead of polluting the shared SQLite database.
- Backend auto-approve contract worker completed:
  - workspace-level `auto_approve_preference` persistence is now implemented
  - `manual_only` is the enforced safe default
  - `below_threshold` is implemented as the bounded policy-backed mode
  - denylisted governance gates are blocked from auto-approve
  - auditable metadata is recorded for auto-approved gates
- Settings policy-posture worker completed:
  - `Settings` now shows read-only `auto_approve_preference` posture from workspace metadata
  - threshold summary is visible for `below_threshold`
  - critical governance gates remain explicitly described as manual-only
- Live browser QA is in progress against the fresh local pair:
  - API: `http://127.0.0.1:8766`
  - Desktop: `http://127.0.0.1:5175`

## Completed Changes

### Backend

- Added `projects` persistence to [src/storage/__init__.py](/Users/sweethome/Work/Skills/Sarathi/src/storage/__init__.py).
- Added workspace project create/list routes to [src/service/__init__.py](/Users/sweethome/Work/Skills/Sarathi/src/service/__init__.py).
- Added real project summary projections:
  - `task_count`
  - `blocked_count`
  - `review_needed_count`
  - `updated_at` / last activity
- Added project summaries to workspace operational views.
- Added project-aware task dashboard filtering via `project_id`.

### Desktop

- Rewired project state in [desktop/src/App.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/App.tsx) from synthetic local storage to service-backed project records.
- Added project client methods and record types in [desktop/src/apiClient.ts](/Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts).
- Updated [desktop/src/pages/WorkspaceDashboard.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/WorkspaceDashboard.tsx) to use service-backed project fields.
- Fixed API config precedence in [desktop/src/apiClient.ts](/Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts) so explicit env config beats `desktop/public/sarathi-runtime.js`.
- Fixed [desktop/src/pages/Dashboard.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Dashboard.tsx) to:
  - query by `projectId`
  - stop showing mock tasks on empty live projects
- Fixed [desktop/src/pages/ProjectDetail.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/ProjectDetail.tsx) for project-scoped task resolution.
- Fixed [desktop/src/pages/Settings.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Settings.tsx) to use the selected workspace rather than a hardcoded workspace lookup.
- Hardened [desktop/src/pages/Inbox.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Inbox.tsx) into a project-aware human attention queue with real workspace status, gate/blocker summaries, and honest empty states.
- Reworked [desktop/src/pages/Agents.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Agents.tsx) into an operational provider surface with readiness, dispatch posture, budget posture, and per-provider test controls.
- Polished [desktop/src/pages/ProjectDetail.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/ProjectDetail.tsx) so task studio shows a computed next action and clearer current posture for the selected task.
- Added a short QA wrapper:
  - [desktop/scripts/validate-task-panel.sh](/Users/sweethome/Work/Skills/Sarathi/desktop/scripts/validate-task-panel.sh)
  - [desktop/scripts/validate-task-panel.mjs](/Users/sweethome/Work/Skills/Sarathi/desktop/scripts/validate-task-panel.mjs)
- QA hygiene worker updated:
  - [desktop/scripts/validate-task-panel.sh](/Users/sweethome/Work/Skills/Sarathi/desktop/scripts/validate-task-panel.sh)
  - [desktop/scripts/validate-task-panel.mjs](/Users/sweethome/Work/Skills/Sarathi/desktop/scripts/validate-task-panel.mjs)
  - default behavior now uses an isolated temp DB for validation runs
- Wrote backend-first policy contract spec for future auto-approve work:
  - [2026-05-09-auto-approve-policy-contract-design.md](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-09-auto-approve-policy-contract-design.md)
- Backend contract worker implemented:
  - [policy-pack/approval.md](/Users/sweethome/Work/Skills/Sarathi/policy-pack/approval.md)
  - [src/service/__init__.py](/Users/sweethome/Work/Skills/Sarathi/src/service/__init__.py)
  - [tests/test_service_api.py](/Users/sweethome/Work/Skills/Sarathi/tests/test_service_api.py)
- Settings policy-posture worker implemented:
  - [desktop/src/apiClient.ts](/Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts)
  - [desktop/src/pages/Settings.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Settings.tsx)

## Verification Completed

### Tests

- `python3 -m pytest tests/test_service_api.py -k "workspace_projects or project_desktop_summary or task_draft_preserves" -v`
  - pass
- `python3 -m pytest tests/test_operational_views.py -k "project_summaries or operational_views" -v`
  - pass
- `python3 -m pytest tests/test_task_creation.py -v`
  - pass
- `python3 -m pytest tests/test_task_dashboard.py -v`
  - pass

### Build

- `npm --prefix desktop run build`
  - pass
- `npm --prefix desktop run build`
  - pass again after `Settings`, `Inbox`, and `Agents` hardening
- `npm --prefix desktop run build`
  - pass again after task-studio posture polish
- `npm --prefix desktop run build`
  - pass after QA hygiene worker changes
- `python3 -m pytest tests/test_service_api.py -v`
  - pass after auto-approve contract worker changes (`36 passed`)
- `npm --prefix desktop run build`
  - pass after auto-approve contract worker changes
- `npm --prefix desktop run build`
  - pass after Settings policy-posture worker changes

### Browser QA Confirmed

- Workspace landing page loads against fresh API/server pair.
- Project creation works end to end against persisted backend.
- Newly created project now lands on an empty project dashboard instead of showing workspace-global tasks.
- Creating a task from a project dashboard now opens task studio on the newly created project task.
- Primary wrapper still passes after support-surface changes.
- Primary wrapper still passes after task-studio posture polish.
- Primary wrapper passes with isolated DB mode:
  - `BASE_URL=http://127.0.0.1:5175 CLEANUP_DB_PATH=true desktop/scripts/validate-task-panel.sh`
- Final browser QA re-run after Settings pass was blocked inside the sandboxed agent runtime:
  - browser process failed before app interaction with a Chromium `mach_port_rendezvous` permission error
  - this was a sandbox/runtime limitation, not an observed Sarathi desktop regression
  - unsandboxed validation on 2026-05-10 passed end-to-end:
    - `BASE_URL=http://127.0.0.1:5175 CLEANUP_DB_PATH=true desktop/scripts/validate-task-panel.sh`
- Wrapper verification passes:

```bash
BASE_URL=http://127.0.0.1:5175 desktop/scripts/validate-task-panel.sh
```

## Active Findings

### Remaining work

- Optional future editable Settings controls for `auto_approve_preference`

## Next Actions

1. Decide whether editable Settings controls for `auto_approve_preference` belong in a future pass.
2. Use dedicated OpenCode worker prompts:
   - `docs/superpowers/prompts/2026-05-09-sarathi-opencode-worker-qa-hygiene.md`
   - `docs/superpowers/prompts/2026-05-09-sarathi-opencode-worker-policy-controls.md`
   - `docs/superpowers/prompts/2026-05-10-sarathi-opencode-worker-auto-approve-contract.md`
   - `docs/superpowers/prompts/2026-05-10-sarathi-opencode-worker-settings-policy-posture.md`

## Ship Pass State

- **Status**: IN PROGRESS
- **Primary flow** (`workspace -> project -> task`) ✓ end-to-end with SQLite
- **Task studio handoff** ✓ fixed and browser-verified
- **Settings** ✓ workspace-scoped
- **Inbox** ✓ operational attention queue, project-aware
- **Agents** ✓ operational provider posture surface
- **Task studio** ✓ clearer next action / posture signaling
- **QA wrapper** ✓ passes and now defaults to isolated DB mode
- **Settings policy posture** ✓ read-only surface for auto-approve governance
- **Build**: ✓ passing
- **Tests**: ✓ passing
- **Services running**: API on 8766, Desktop on 5175

QA verification:

```bash
BASE_URL=http://127.0.0.1:5175 desktop/scripts/validate-task-panel.sh
```

Remaining before calling the pass fully closed:

- optional editable Settings controls for `auto_approve_preference`

## Regression Notes

- User-reported project-creation entry-point regression addressed in [desktop/src/pages/WorkspaceDashboard.tsx](/Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/WorkspaceDashboard.tsx):
  - `Create Project`
  - `New Project`
  - `Create first project`
- Fix:
  - opening a project-create entry point now scrolls the form into view and focuses the `Project name` field
- Verification:
  - `npm --prefix desktop run build` passed
  - targeted unsandboxed Playwright probe returned:
    - `{\"visible\":true,\"focused\":true}`

## Useful Commands

Fresh API:

```bash
python3 -m src.service --db .sarathi/sarathi.db --token dev --port 8766
```

Fresh connected desktop:

```bash
VITE_SARATHI_API_BASE_URL=http://127.0.0.1:8766 VITE_SARATHI_API_TOKEN=dev npm --prefix desktop run dev -- --port 5175
```

Core verification:

```bash
python3 -m pytest tests/test_service_api.py -k "workspace_projects or project_desktop_summary or task_draft_preserves" -v
python3 -m pytest tests/test_operational_views.py -k "project_summaries or operational_views" -v
python3 -m pytest tests/test_task_dashboard.py -v
npm --prefix desktop run build
```

## Orchestrator Notes

- Prefer thin-controller mode: status, plan, bounded edits, verification, and OpenCode worker dispatch only where the write scope is clean.
- Do not trust the stale runtime script in `desktop/public/sarathi-runtime.js` during QA unless that is the explicit target; env override is now the intended live-testing path.
- Do not revert unrelated user changes; the worktree is dirty.
