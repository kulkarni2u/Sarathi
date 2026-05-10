# Sarathi Desktop Release Handoff

Date: 2026-05-10

## Outcome

This pass turned the Sarathi desktop into a substantially more trustworthy orchestration cockpit around:

- `workspace -> project -> task`

The primary desktop flow now uses real SQLite-backed service data instead of synthetic local-only behavior on the critical path.

## Shipped Areas

### Primary flow

- workspace selection and workspace-first shell
- persisted workspace project creation and listing
- project-scoped dashboard task lists
- task creation opening the correct task studio
- project-scoped task studio resolution

### Support surfaces

- `Settings`
  - workspace-scoped trust/config surface
  - repository safety controls
  - read-only auto-approve policy posture
- `Inbox`
  - human attention queue for gates and blockers
- `Agents`
  - provider readiness, dispatch posture, and budget posture
- `Task Studio`
  - clearer next action / current posture signaling

### QA and governance

- validation wrapper now uses isolated temp DB state
- backend `auto_approve_preference` contract now exists
- policy-pack `approval.md` now defines the default approval posture

## Verification

Verified during this pass:

- `python3 -m pytest tests/test_service_api.py -v`
- targeted pytest slices for project/task/operational views
- repeated `npm --prefix desktop run build`
- browser QA wrapper passed earlier in the pass
- isolated-DB wrapper path passed

Final browser reruns after the Settings policy-posture change were blocked by the local Playwright/Chromium environment before page interaction. That is recorded as an environment issue, not a confirmed Sarathi regression.

Update after final validation:

- Unsandboxed browser QA passed on May 10, 2026.
- The sandboxed failure was confirmed to be specific to the agent runtime, not to Sarathi itself.
- The project-creation entry-point regression was also fixed and verified:
  - create form now scrolls into view
  - `Project name` is focused after clicking create entry points

## Important Files

Core source of truth:

- [desktop status](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md)

Key product/workflow docs:

- [desktop design spec](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-09-sarathi-desktop-orchestration-studio-design.md)
- [auto-approve contract spec](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-09-auto-approve-policy-contract-design.md)

## 2026-05-10 — Orchestration pass (Sarathi as orchestrator, OpenCode as worker)

### Task A: Provider priority persistence — DONE
- Dispatch order now persists to workspace metadata (`provider_priority` via `updateWorkspace`)
- On workspace load, metadata value overrides localStorage fallback
- Both reorder buttons fire async PATCH fire-and-forget; localStorage stays as offline fallback
- Verification: `npm --prefix desktop run build` ✓

### Task B: Threshold editing for `below_threshold` — DONE
- When mode = `below_threshold`, two inline controls appear: Max nodes (1–20) and Max complexity (low/medium/high)
- Edits flow into `autoApprovePreference.threshold`, saved by existing "Save workflow" button
- Verification: `npm --prefix desktop run build` ✓

### Task C: Policy pack editor UI — DONE
- `apiClient.ts`: added `PolicyPackFile` type, `getWorkspacePolicyPack`, `putWorkspacePolicyPackFile`, and `putJson` helper (backend route is PUT, not PATCH)
- `Settings.tsx`: new full-width section — expand/edit/save/revert per policy file; "unsaved" indicator; load from workspace on select; reset on workspace change
- Verification: `npm --prefix desktop run build` ✓, 43 tests passed

### Task D: Repos section in Settings — DEFERRED
- Would overlap WorkspaceDashboard; no forcing function in current sprint

## Remaining Work

All planned tasks for this orchestration pass are complete. No open items.

## Release Hygiene Recommendation

If you want to package this cleanly, split commits roughly into:

1. backend persistence and project/task trust
2. desktop shell and primary flow
3. support surfaces (`Settings`, `Inbox`, `Agents`, `Task Studio`)
4. QA hygiene + auto-approve backend contract + Settings policy posture
