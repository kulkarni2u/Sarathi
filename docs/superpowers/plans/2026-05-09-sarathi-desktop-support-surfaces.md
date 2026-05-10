# Sarathi Desktop Support Surfaces Plan

**Goal:** Finish the next ship phase by making `Settings`, `Inbox`, and `Agents` feel like real Sarathi support surfaces instead of generic utility pages, while preserving the now-working `workspace -> project -> task` primary flow.

## Sequence

1. `Settings trust hardening`
2. `Inbox attention queue hardening`
3. `Agents operational hardening`
4. `Task studio cleanup after support-surface changes`
5. `QA stabilization`

## Task 1: Settings Trust Hardening

**Files**
- `desktop/src/App.tsx`
- `desktop/src/pages/Settings.tsx`
- `desktop/src/apiClient.ts` only if a missing contract is discovered

**Work**
- Bind settings to the selected workspace instead of hardcoded workspace discovery.
- Show real workspace trust posture:
  - workspace identity
  - repository action mode
  - provider readiness
  - bootstrap/setup state
- Keep repository safety as the dominant control surface.
- Prepare a clean insertion point for future auto-approve policy controls without implementing them yet.

**Acceptance**
- Switching workspace changes the settings surface truthfully.
- No hardcoded `"Sarathi"` workspace discovery remains in the live settings path.
- Build passes.

## Task 2: Inbox Attention Queue Hardening

**Files**
- `desktop/src/pages/Inbox.tsx`
- `desktop/src/apiClient.ts` only if query shape needs extension
- `src/service/__init__.py` only if a new projection route is justified

**Work**
- Make inbox a real attention queue:
  - blocked tasks
  - approval-needed tasks
  - failed review / escalation signals
  - restart-ready checkpoints if available
- Remove generic notification flavor.
- Improve task/project jump behavior so clicking an inbox item lands in the right task context.

**Acceptance**
- Inbox reads like a human intervention queue, not a message center.
- Empty state is calm and correct.
- Clicking a row lands on the correct project/task.

## Task 3: Agents Operational Hardening

**Files**
- `desktop/src/pages/Agents.tsx`
- `desktop/src/apiClient.ts` only if needed
- `src/service/__init__.py` only if richer provider/dispatch projections are required

**Work**
- Reframe agents around provider health and execution posture:
  - online/offline/degraded
  - capabilities
  - recent health checks
  - dispatch confidence / availability cues using existing signals
- Remove decorative “library” feeling.

**Acceptance**
- Agents page explains whether orchestration actors are healthy.
- Provider testing remains functional.

## Task 4: Task Studio Cleanup

**Files**
- `desktop/src/pages/ProjectDetail.tsx`

**Work**
- Recheck for any remaining workspace-global leakage.
- Tighten empty states, labels, and selected-task clarity after support-surface changes.
- Keep the project-scoped task rail honest.

## Task 5: QA Stabilization

**Files**
- `desktop/scripts/validate-task-panel.mjs`
- `desktop/scripts/validate-task-panel.sh`

**Work**
- Keep the wrapper aligned with the workspace-first shell.
- Consider making QA target a disposable DB/workspace to avoid additive validation noise.

**Acceptance**
- `BASE_URL=http://127.0.0.1:5175 desktop/scripts/validate-task-panel.sh` stays green.
