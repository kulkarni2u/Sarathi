# Sarathi Organized Orchestrator Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first coherent `organized orchestrator` version of Sarathi by making workspace, project, inbox, and task studio share one explicit control-tower model for state, approvals, blockers, checkpoints, and handoff posture.

**Architecture:** Extend the Python service to expose stronger operational projections for workspace, project, inbox, and task-state headers, then rewire the React desktop to consume those contracts as the default source of truth. Use a three-lane execution model: OpenCode owns service/storage contracts, Codex owns desktop integration and UI hierarchy, and Claude owns review, acceptance-criteria audit, and end-to-end ship QA.

**Tech Stack:** Python stdlib service + SQLite (`src/service/__init__.py`, `src/storage/__init__.py`), React 19 + TypeScript desktop (`desktop/src/*`), existing tests in `tests/*`, existing brainstorm/checkpoint/approval/task graph infrastructure.

---

## Sprint Strategy

### Shared contract before coding

All three agents align first on:

- queue labels
- task summary payload shape
- inbox item kinds
- policy/approval visibility labels

### Workstream split

- OpenCode: backend/service/projections/tests
- Codex: desktop shell/pages/client wiring/build verification
- Claude: acceptance review, naming audit, regression checklist, release-readiness review

### Definition of done

- backend projection tests pass
- desktop builds cleanly
- primary surfaces show organized control-tower state from real service data
- end-to-end QA covers workspace -> project -> task -> approval/checkpoint/handoff paths

---

## File Map

**Backend / service / storage**
- Modify: `src/service/__init__.py`
- Modify: `src/storage/__init__.py`
- Modify: `src/cli.py`
- Modify: `tests/test_service_api.py`
- Modify: `tests/test_operational_views.py`
- Modify: `tests/test_task_dashboard.py`
- Modify: `tests/test_task_studio.py`
- Modify: `tests/test_handoff_repository_action.py`

**Desktop / UI integration**
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/pages/WorkspaceDashboard.tsx`
- Modify: `desktop/src/pages/Dashboard.tsx`
- Modify: `desktop/src/pages/Inbox.tsx`
- Modify: `desktop/src/pages/ProjectDetail.tsx`
- Modify: `desktop/src/pages/Agents.tsx`
- Modify: `desktop/src/pages/Settings.tsx`
- Modify: `desktop/src/components/ui.tsx`
- Modify: `desktop/src/styles.css`

**Docs / QA**
- Modify: `docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md`
- Modify if needed after review: `docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-product-brief.md`

---

## Task 1: Lock the Organized-Orchestrator Contract

**Owner:** Claude + Codex + OpenCode

**Files:**
- Modify: `docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md`
- Modify: `desktop/src/apiClient.ts`
- Modify: `src/service/__init__.py`

- [ ] **Step 1: Confirm the queue labels and shared task-summary fields**

The shared contract for this sprint is:

```ts
type OrganizedQueueState =
  | "intake"
  | "planning"
  | "awaiting_approval"
  | "ready"
  | "running"
  | "under_review"
  | "blocked"
  | "waiting_human"
  | "failed"
  | "handoff_ready"
  | "done";

type OrganizedTaskSummary = {
  id: string;
  workspace_id: string;
  title: string;
  status: string;
  phase: string;
  approval_state: string;
  graph_state: string;
  next_gate: string | null;
  blocked_count: number;
  review_needed_count: number;
  checkpoint_state: string;
  handoff_state: string;
  updated_at: string;
};
```

- [ ] **Step 2: Verify current code does not fully expose this shape**

Run:

```bash
cd /Users/sweethome/Work/Skills/Sarathi
rg -n "checkpoint_state|handoff_state|review_needed_count|awaiting_approval|handoff_ready" src/service/__init__.py desktop/src/apiClient.ts
```

Expected:
- Partial matches only, proving this sprint still needs contract work.

- [ ] **Step 3: Add the new client-facing types in `desktop/src/apiClient.ts`**

Add or extend exported types so the desktop can consume:

```ts
export type InboxQueueItem = {
  id: string;
  kind: "approval" | "blocked_task" | "failed_review" | "checkpoint_ready" | "handoff_ready" | "provider_failure";
  workspace_id: string;
  project_id?: string | null;
  task_id?: string | null;
  title: string;
  summary: string;
  state: string;
  next_action?: string | null;
  updated_at: string;
};
```

- [ ] **Step 4: Add matching projection keys to the service response builders**

Update `src/service/__init__.py` projection helpers so task summaries and inbox items can return those same fields consistently.

- [ ] **Step 5: Commit the contract-only alignment slice**

```bash
git add docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md desktop/src/apiClient.ts src/service/__init__.py
git commit -m "chore: lock organized orchestrator sprint contracts"
```

---

## Task 2: Build Service Projections for Workspace, Project, and Inbox

**Owner:** OpenCode

**Files:**
- Modify: `src/service/__init__.py`
- Modify: `tests/test_service_api.py`
- Modify: `tests/test_operational_views.py`
- Modify: `tests/test_task_dashboard.py`

- [ ] **Step 1: Write failing tests for organized workspace and inbox projections**

Add tests that require:

```python
def test_inbox_projection_groups_attention_items(tmp_path):
    app, workspace_id, project_id, task_id = seed_attention_scenario(tmp_path)
    data = request_json(app, "GET", f"/api/workspaces/{workspace_id}/operational-views")
    inbox = data["views"]["inbox"]
    assert any(item["kind"] == "approval" for item in inbox)
    assert any(item["kind"] == "checkpoint_ready" for item in inbox)
    assert any(item["kind"] == "handoff_ready" for item in inbox)


def test_task_dashboard_items_include_control_tower_fields(tmp_path):
    app, workspace_id = seed_dashboard_scenario(tmp_path)
    data = request_json(app, "GET", f"/api/workspaces/{workspace_id}/tasks")
    task = data["tasks"][0]
    assert "checkpoint_state" in task
    assert "handoff_state" in task
    assert "review_needed_count" in task
```

- [ ] **Step 2: Run the service tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_service_api.py -k operational -v
python3 -m pytest tests/test_operational_views.py -v
python3 -m pytest tests/test_task_dashboard.py -v
```

Expected:
- FAIL because the organized projection fields and inbox aggregation are incomplete.

- [ ] **Step 3: Implement queue/state projection helpers in `src/service/__init__.py`**

Add or extend helpers for:

```python
def _organized_task_summary(...): ...
def _checkpoint_state(...): ...
def _handoff_state(...): ...
def _review_needed_count(...): ...
def _build_inbox_items(...): ...
```

Required behavior:
- `checkpoint_state` reflects whether a resumable checkpoint exists
- `handoff_state` distinguishes `none`, `draft`, and `ready`
- inbox items are aggregated from approvals, failed reviews, ready checkpoints, blocked tasks, and handoff-ready tasks

- [ ] **Step 4: Extend the workspace operational views payload**

Ensure the workspace operational response includes:

```python
{
    "workspace_id": workspace_id,
    "summary": {...},
    "projects": [...],
    "inbox": [...],
    "history": [...],
    "usage": {...},
}
```

- [ ] **Step 5: Re-run the service tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_service_api.py -k operational -v
python3 -m pytest tests/test_operational_views.py -v
python3 -m pytest tests/test_task_dashboard.py -v
```

Expected:
- PASS for projection and inbox aggregation coverage.

- [ ] **Step 6: Commit the service projection slice**

```bash
git add src/service/__init__.py tests/test_service_api.py tests/test_operational_views.py tests/test_task_dashboard.py
git commit -m "feat: add organized control tower service projections"
```

---

## Task 3: Add Task-Studio Header Truth for Approvals, Checkpoints, and Handoff

**Owner:** OpenCode

**Files:**
- Modify: `src/service/__init__.py`
- Modify: `tests/test_task_studio.py`
- Modify: `tests/test_handoff_repository_action.py`

- [ ] **Step 1: Write failing task-studio tests for state header posture**

Add tests that require the task-studio response to expose:

```python
def test_task_studio_exposes_next_safe_action_and_posture(tmp_path):
    app, task_id = seed_task_studio_attention_case(tmp_path)
    data = request_json(app, "GET", f"/api/tasks/{task_id}/studio")
    header = data["snapshot"]["header"]
    assert header["queue_state"] in {"blocked", "waiting_human", "handoff_ready"}
    assert header["next_safe_action"]
    assert "repository_action_mode" in header
    assert "checkpoint_ready" in header
```

- [ ] **Step 2: Run the task-studio tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_task_studio.py -v
python3 -m pytest tests/test_handoff_repository_action.py -v
```

Expected:
- FAIL because the studio header contract is still too thin.

- [ ] **Step 3: Add a task-studio header projection**

Implement a normalized header block in `src/service/__init__.py`:

```python
header = {
    "queue_state": queue_state,
    "approval_state": approval_state,
    "next_safe_action": next_safe_action,
    "repository_action_mode": repository_action_mode,
    "checkpoint_ready": checkpoint is not None,
    "handoff_state": handoff_state,
}
```

- [ ] **Step 4: Make handoff and repository-action posture visible without separate deep reads**

Ensure task-studio snapshots can render:
- whether a handoff exists
- whether a checkpoint exists
- whether repository action is blocked, draft-only, or ready for approval

- [ ] **Step 5: Re-run task-studio tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_task_studio.py -v
python3 -m pytest tests/test_handoff_repository_action.py -v
```

Expected:
- PASS with header-level state posture available.

- [ ] **Step 6: Commit the task-studio projection slice**

```bash
git add src/service/__init__.py tests/test_task_studio.py tests/test_handoff_repository_action.py
git commit -m "feat: expose organized task studio state posture"
```

---

## Task 4: Rewire the Desktop Shell to the Organized Projections

**Owner:** Codex

**Files:**
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/pages/WorkspaceDashboard.tsx`
- Modify: `desktop/src/pages/Dashboard.tsx`

- [ ] **Step 1: Verify the current desktop shell still mixes real and demo truth**

Run:

```bash
cd /Users/sweethome/Work/Skills/Sarathi
rg -n "demo|mock|mockData|Demo mode" desktop/src/App.tsx desktop/src/pages/WorkspaceDashboard.tsx desktop/src/pages/Dashboard.tsx
```

Expected:
- Multiple matches proving the shell still needs stronger organized-orchestrator wiring.

- [ ] **Step 2: Add the new fetch helpers in `desktop/src/apiClient.ts`**

Ensure the client can fetch:

```ts
export async function getWorkspaceOperationalViews(workspaceId: string): Promise<OperationalViewsSnapshot> { ... }
export async function listTaskDashboard(workspaceId: string, projectId?: string | null): Promise<TaskDashboardItem[]> { ... }
```

Update the response typing so the shell can render `checkpoint_state`, `handoff_state`, and `review_needed_count`.

- [ ] **Step 3: Rework `App.tsx` loaders to prefer service projections**

Update `App.tsx` so:
- nav counts come from real inbox/dashboard/agents data
- selected project and task state derive from service responses
- demo fallbacks are clearly secondary and only used when no API config exists

Use the existing pattern:

```ts
const apiConfigured = getSarathiApiConfig() !== null;
```

to gate fallback behavior without mixing demo and real state silently.

- [ ] **Step 4: Update workspace and dashboard pages to speak the organized vocabulary**

Adjust the pages so the primary summary cards and table/list rows show:
- blocked counts
- approvals needed
- checkpoint-ready state
- handoff-ready state
- a stronger next-action cue

- [ ] **Step 5: Run the desktop build and verify it passes**

Run:

```bash
cd /Users/sweethome/Work/Skills/Sarathi
npm --prefix desktop run build
```

Expected:
- PASS with no TypeScript errors.

- [ ] **Step 6: Commit the shell integration slice**

```bash
git add desktop/src/apiClient.ts desktop/src/App.tsx desktop/src/pages/WorkspaceDashboard.tsx desktop/src/pages/Dashboard.tsx
git commit -m "feat: wire desktop shell to organized control tower projections"
```

---

## Task 5: Turn Inbox into the Human Attention Queue

**Owner:** Codex

**Files:**
- Modify: `desktop/src/pages/Inbox.tsx`
- Modify: `desktop/src/components/ui.tsx`
- Modify: `desktop/src/styles.css`

- [ ] **Step 1: Replace generic inbox assumptions with queue-item rendering**

Render the new queue kinds directly:

```ts
const toneByKind = {
  approval: "warning",
  blocked_task: "danger",
  failed_review: "danger",
  checkpoint_ready: "active",
  handoff_ready: "healthy",
  provider_failure: "danger",
} as const;
```

- [ ] **Step 2: Add clear next-action affordances**

Each inbox row should show:
- kind
- title
- summary
- state
- next action
- deep link target such as task or project route

- [ ] **Step 3: Ensure empty state is meaningful**

Empty-state copy should reinforce the product promise:

```tsx
<p>No approvals, blockers, failed reviews, or restart-ready work are waiting on you.</p>
```

- [ ] **Step 4: Run the desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with inbox queue rendering integrated cleanly.

- [ ] **Step 5: Commit the inbox slice**

```bash
git add desktop/src/pages/Inbox.tsx desktop/src/components/ui.tsx desktop/src/styles.css
git commit -m "feat: turn inbox into organized attention queue"
```

---

## Task 6: Rebuild the Task Studio Header and Right-Rail Posture

**Owner:** Codex

**Files:**
- Modify: `desktop/src/pages/ProjectDetail.tsx`
- Modify: `desktop/src/components/TaskPanelTimeline.tsx`
- Modify: `desktop/src/components/ui.tsx`

- [ ] **Step 1: Use the new task-studio header payload**

Render the service-provided posture fields at the top of the page:

```ts
const header = snapshot?.header;
```

Display:
- queue state
- approval state
- next safe action
- checkpoint readiness
- handoff state
- repository action posture

- [ ] **Step 2: Reduce ambiguity in state labels**

Replace any generic "ready" or "active" copy that hides the true status when a more specific queue state is available.

- [ ] **Step 3: Make checkpoint and handoff actions visible without hunting**

Ensure the task studio exposes the main actions directly when present:
- start from checkpoint
- open source task
- review handoff
- approve repo action if pending

- [ ] **Step 4: Run the desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with the task studio using the organized-orchestrator header.

- [ ] **Step 5: Commit the task-studio UI slice**

```bash
git add desktop/src/pages/ProjectDetail.tsx desktop/src/components/TaskPanelTimeline.tsx desktop/src/components/ui.tsx
git commit -m "feat: surface organized task state in studio header"
```

---

## Task 7: Expose Operational Health in Agents and Settings Without UI Sprawl

**Owner:** Codex

**Files:**
- Modify: `desktop/src/pages/Agents.tsx`
- Modify: `desktop/src/pages/Settings.tsx`
- Modify: `desktop/src/apiClient.ts`

- [ ] **Step 1: Show provider health as operator trust posture**

Agents should emphasize:
- online/degraded/offline
- last check time
- recent dispatch posture
- failures or missing auth

- [ ] **Step 2: Show settings as trust posture, not just forms**

Settings should make repository action defaults and auto-approve posture easy to inspect.

Use existing metadata contracts such as:

```ts
type RepositoryActionPreferenceRecord = { ... }
type AutoApprovePreferenceRecord = { ... }
```

- [ ] **Step 3: Run the desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with no regressions in support surfaces.

- [ ] **Step 4: Commit the support-surface slice**

```bash
git add desktop/src/pages/Agents.tsx desktop/src/pages/Settings.tsx desktop/src/apiClient.ts
git commit -m "feat: clarify provider and trust posture on support surfaces"
```

---

## Task 8: Add Minimal CLI Status Parity for the Control Tower

**Owner:** OpenCode

**Files:**
- Modify: `src/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_cli_default_home.py`

- [ ] **Step 1: Add a failing CLI test for approval and blocked visibility**

Add a test that expects CLI status output to surface:

```python
def test_status_shows_approval_and_blocked_counts(tmp_path):
    result = run_cli(tmp_path, ["status"])
    assert "Approvals pending" in result.stdout
    assert "Blocked tasks" in result.stdout
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_cli.py -k status -v
python3 -m pytest tests/test_cli_default_home.py -v
```

Expected:
- FAIL because the status output is not yet aligned to the control-tower framing.

- [ ] **Step 3: Update `src/cli.py` status rendering**

Add a compact status summary that reports:
- workspace
- approvals pending
- blocked tasks
- handoff-ready tasks
- checkpoint-ready tasks if available

- [ ] **Step 4: Re-run CLI tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_cli.py -k status -v
python3 -m pytest tests/test_cli_default_home.py -v
```

Expected:
- PASS with new control-tower wording.

- [ ] **Step 5: Commit the CLI parity slice**

```bash
git add src/cli.py tests/test_cli.py tests/test_cli_default_home.py
git commit -m "feat: add control tower status parity to cli"
```

---

## Task 9: End-to-End QA and Product Readiness Review

**Owner:** Claude

**Files:**
- Modify if needed: `docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md`
- Modify if needed: `docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-product-brief.md`

- [ ] **Step 1: Run backend verification**

Run:

```bash
cd /Users/sweethome/Work/Skills/Sarathi
python3 -m pytest tests/test_service_api.py tests/test_operational_views.py tests/test_task_dashboard.py tests/test_task_studio.py tests/test_handoff_repository_action.py tests/test_cli.py tests/test_cli_default_home.py -v
```

Expected:
- PASS for the organized-orchestrator contract tests.

- [ ] **Step 2: Run desktop build verification**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS.

- [ ] **Step 3: Run manual product QA**

Verify this path in the running desktop:

1. open workspace
2. open project
3. identify a blocked or approval-pending task
4. open task studio
5. inspect checkpoint and handoff posture
6. confirm inbox shows the same task in the attention queue

- [ ] **Step 4: Record findings and tighten wording if needed**

If queue labels, empty states, or posture language are confusing, fix the copy before ship.

- [ ] **Step 5: Commit any final wording or QA fixes**

```bash
git add docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-product-brief.md
git commit -m "docs: finalize organized orchestrator sprint readiness"
```

---

## Suggested 10-Day Execution Cadence

### Days 1-2

- Task 1
- Task 2 start

### Days 3-4

- Task 2 finish
- Task 3

### Days 5-7

- Task 4
- Task 5
- Task 6

### Days 8-9

- Task 7
- Task 8

### Day 10

- Task 9

---

## Notes For Parallel Agents

- OpenCode should not edit `desktop/src/*` unless a backend contract absolutely requires a companion type change in `desktop/src/apiClient.ts`.
- Codex should not change storage/service logic outside the agreed projection surfaces.
- Claude should review state names, acceptance criteria, and QA outcomes before final merge decisions.
- Merge order should be: Task 1 -> Tasks 2 and 3 -> Tasks 4/5/6/7 -> Task 8 -> Task 9.

Plan complete and saved to `docs/superpowers/plans/2026-05-12-sarathi-organized-orchestrator-sprint.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
