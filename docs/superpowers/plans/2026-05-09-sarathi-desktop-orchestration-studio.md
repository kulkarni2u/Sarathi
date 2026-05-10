# Sarathi Desktop Orchestration Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Sarathi desktop into a trustworthy orchestration cockpit centered on `workspace -> project -> task`, with real persisted data on primary surfaces and a polished task studio as the product centerpiece.

**Architecture:** Add missing persistence and projection layers for workspace/project/task truth in the Python service and storage layer, then rewire the React desktop shell to consume those real projections instead of local/demo-only state. Keep the existing CLI-backed provider execution model intact and improve how lifecycle, gates, checkpoints, and review posture are surfaced in the UI.

**Tech Stack:** Python service/storage (`src/service/__init__.py`, `src/storage/__init__.py`), React 19 + TypeScript + Vite desktop (`desktop/src/*`), existing Sarathi event/task/checkpoint APIs, existing OpenCode CLI integration for bounded implementation slices.

---

## File Map

**Backend / data contract**
- Modify: `src/storage/__init__.py`
- Modify: `src/service/__init__.py`
- Modify: `tests/test_service_api.py`
- Modify: `tests/test_operational_views.py`
- Modify: `tests/test_task_creation.py`
- Modify: `tests/test_task_graph.py`

**Desktop shell / state / API client**
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/styles.css`

**Primary surfaces**
- Modify: `desktop/src/pages/WorkspaceDashboard.tsx`
- Modify: `desktop/src/pages/Dashboard.tsx`
- Modify: `desktop/src/pages/ProjectDetail.tsx`

**Support surfaces**
- Modify: `desktop/src/pages/Inbox.tsx`
- Modify: `desktop/src/pages/Agents.tsx`
- Modify: `desktop/src/pages/Settings.tsx`
- Modify or delete if dead: `desktop/src/components/Sidebar.tsx`

**Verification**
- Modify or add: `desktop/scripts/*` only if browser QA helpers are needed

---

### Task 1: Persist Projects and Workspace Summaries

**Files:**
- Modify: `src/storage/__init__.py`
- Modify: `src/service/__init__.py`
- Test: `tests/test_service_api.py`
- Test: `tests/test_task_creation.py`

- [ ] **Step 1: Write failing API tests for persisted projects**

Add tests that prove the service can:
- create a project scoped to a workspace
- list projects for a workspace
- include project metadata needed by the desktop
- associate task drafts with persisted project ids

Target shape:

```python
def test_workspace_projects_can_be_created_and_listed(tmp_path):
    app, workspace = create_app_with_workspace(tmp_path)
    created = request_json(
        app,
        "POST",
        f"/api/workspaces/{workspace['id']}/projects",
        {"name": "Desktop Hardening", "description": "Trustworthy orchestration surfaces"},
    )
    assert created["project"]["workspace_id"] == workspace["id"]

    listed = request_json(app, "GET", f"/api/workspaces/{workspace['id']}/projects")
    assert [project["name"] for project in listed["projects"]] == ["Desktop Hardening"]
```

- [ ] **Step 2: Run the new project API tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_service_api.py -k workspace_projects -v
```

Expected:
- FAIL because no project persistence or routes exist yet.

- [ ] **Step 3: Add storage support for projects**

Implement a dedicated `projects` table and CRUD methods in `src/storage/__init__.py`.

Required fields:

```sql
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
```

Required methods:
- `create_project(...)`
- `list_projects(workspace_id)`
- `get_project(project_id)`
- `update_project(...)` if needed for summary metadata

- [ ] **Step 4: Add service routes and task-draft wiring**

Implement in `src/service/__init__.py`:
- `POST /api/workspaces/:id/projects`
- `GET /api/workspaces/:id/projects`

Also ensure task draft creation preserves a real `project_id` on task metadata and any returned desktop summary record.

- [ ] **Step 5: Re-run the project API tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_service_api.py -k workspace_projects -v
python3 -m pytest tests/test_task_creation.py -k project -v
```

Expected:
- PASS for project persistence and task draft project association.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add src/storage/__init__.py src/service/__init__.py tests/test_service_api.py tests/test_task_creation.py
git commit -m "feat: persist workspace projects for desktop surfaces"
```

---

### Task 2: Add Real Workspace and Project Projections for Desktop Trust

**Files:**
- Modify: `src/service/__init__.py`
- Test: `tests/test_operational_views.py`
- Test: `tests/test_service_api.py`

- [ ] **Step 1: Write failing tests for workspace/project desktop summaries**

Add tests that require:
- workspace project summaries with task counts and last activity
- workspace operational summary with repo readiness, provider posture, attention-needed counts
- project task slices with blocked/review-needed visibility

Target shape:

```python
def test_workspace_project_summaries_include_counts_and_last_activity(tmp_path):
    app, workspace, project, tasks = create_workspace_project_and_tasks(tmp_path)
    data = request_json(app, "GET", f"/api/workspaces/{workspace['id']}/projects")
    summary = data["projects"][0]
    assert summary["task_count"] == 2
    assert summary["blocked_count"] == 1
    assert summary["updated_at"]
```

- [ ] **Step 2: Run the summary tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_operational_views.py -k project_summary -v
python3 -m pytest tests/test_service_api.py -k desktop_summary -v
```

Expected:
- FAIL because the projection fields are missing or incomplete.

- [ ] **Step 3: Implement workspace/project summary projection helpers**

In `src/service/__init__.py`, add projection helpers that compute:
- project task counts
- blocked counts
- review-needed counts
- last updated timestamp
- workspace attention summary
- workspace readiness summary from repos/providers/settings

- [ ] **Step 4: Expose projections in the existing or new desktop routes**

Return the new projection fields through:
- workspace projects route
- operational views route
- any task dashboard route that currently under-describes blocked/review posture

- [ ] **Step 5: Re-run summary tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_operational_views.py -k project_summary -v
python3 -m pytest tests/test_service_api.py -k desktop_summary -v
```

Expected:
- PASS with real projection fields.

- [ ] **Step 6: Commit the summary projection slice**

```bash
git add src/service/__init__.py tests/test_operational_views.py tests/test_service_api.py
git commit -m "feat: add workspace and project desktop projections"
```

---

### Task 3: Replace Local Project State in the Desktop Shell

**Files:**
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/App.tsx`
- Test: `desktop/src/App.tsx` build verification

- [ ] **Step 1: Add failing client integration expectations**

Document the required client contract in code comments or local test notes before implementation:
- projects should come from service routes, not `localStorage`
- project creation should call the real API
- selected project should be derived from service data

- [ ] **Step 2: Verify the current shell still depends on local project state**

Run:

```bash
rg -n "PROJECTS_STORAGE_KEY|readProjectStore|saveProjectStore|project-\\$\\{Date.now" desktop/src/App.tsx
```

Expected:
- Output shows local persistence and synthetic project ids still in use.

- [ ] **Step 3: Add project client functions**

Implement in `desktop/src/apiClient.ts`:
- `listWorkspaceProjects(workspaceId)`
- `createWorkspaceProject(workspaceId, payload)`

Target signatures:

```ts
export async function listWorkspaceProjects(workspaceId: string): Promise<ProjectRecord[]>
export async function createWorkspaceProject(
  workspaceId: string,
  payload: { name: string; description?: string },
): Promise<ProjectRecord>
```

- [ ] **Step 4: Rewire `App.tsx` to service-backed project state**

Replace:
- local `PROJECTS_STORAGE_KEY`
- synthetic project ids
- write-through `localStorage` project mutations

With:
- service fetch on workspace selection
- service-backed create flow
- service-backed selected project refresh when tasks change

Keep:
- route model
- existing workspace selection behavior
- offline fallback only if API is unavailable

- [ ] **Step 5: Run desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with no TypeScript or route-state regressions.

- [ ] **Step 6: Commit the shell state slice**

```bash
git add desktop/src/apiClient.ts desktop/src/App.tsx
git commit -m "feat: use persisted projects in desktop shell"
```

---

### Task 4: Rebuild Workspace and Project Surfaces Around Real Operational Data

**Files:**
- Modify: `desktop/src/pages/WorkspaceDashboard.tsx`
- Modify: `desktop/src/pages/Dashboard.tsx`
- Modify: `desktop/src/styles.css`

- [ ] **Step 1: Define the target surface behavior in code comments or scratch notes**

Workspace surface must show:
- readiness posture
- provider posture
- project list
- recent interrupts
- one dominant next action

Project surface must show:
- attention strip
- task list as primary object
- blocked/review-needed clarity

- [ ] **Step 2: Implement workspace surface changes**

In `WorkspaceDashboard.tsx`:
- remove the generic “create project” page feel
- introduce a stronger operational header
- add readiness and attention sections
- keep project creation available but subordinate to the project list and next-action block

- [ ] **Step 3: Implement project dashboard changes**

In `Dashboard.tsx`:
- make the task list the dominant section
- tighten filter/search/composer hierarchy
- show blocked/review-needed signals clearly
- remove generic empty-state wording that confuses project/task scopes

- [ ] **Step 4: Add matching visual system support**

In `styles.css`:
- unify calm shell styling for workspace surfaces
- use denser premium styling for task rows and operational cards
- remove or override lingering generic marketplace/table styles that fight the chosen product direction

- [ ] **Step 5: Run desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with updated workspace and project surfaces.

- [ ] **Step 6: Commit the workspace/project surface slice**

```bash
git add desktop/src/pages/WorkspaceDashboard.tsx desktop/src/pages/Dashboard.tsx desktop/src/styles.css
git commit -m "feat: harden workspace and project orchestration surfaces"
```

---

### Task 5: Make Task Studio the Product Centerpiece

**Files:**
- Modify: `desktop/src/pages/ProjectDetail.tsx`
- Modify: `desktop/src/components/TaskPanelTimeline.tsx`
- Modify: `desktop/src/styles.css`
- Test: `tests/test_operational_views.py` if snapshot contract changes are needed

- [ ] **Step 1: Identify remaining demo-only branches in task studio**

Run:

```bash
rg -n "createDemo|mock|fallback" desktop/src/pages/ProjectDetail.tsx desktop/src/components/TaskPanelTimeline.tsx
```

Expected:
- Output highlights demo/fallback code paths that still shape the primary task experience.

- [ ] **Step 2: Tighten the lifecycle header and next-action hierarchy**

In `ProjectDetail.tsx`:
- make phase, gate, blocker, owner/provider, and next action visible above the fold
- reduce equal-weight chrome
- keep graph, timeline, evidence, checkpoints, review, and handoff, but rebuild hierarchy so the current state reads immediately

- [ ] **Step 3: Improve task panel and checkpoint readability**

In `TaskPanelTimeline.tsx` and related styling:
- make the timeline calmer and more scan-friendly
- keep newest-first behavior
- surface checkpoint restart and review/handoff states without turning the panel into a stack of noisy cards

- [ ] **Step 4: Remove fake-cockpit behavior where real task data exists**

Use service-backed studio/panel/checkpoint/operational data first.
Keep demo data only for true offline/demo states, not for normal service-backed sessions.

- [ ] **Step 5: Run desktop build and targeted Python tests**

Run:

```bash
npm --prefix desktop run build
python3 -m pytest tests/test_operational_views.py tests/test_service_api.py -v
```

Expected:
- PASS for build and relevant service snapshot tests.

- [ ] **Step 6: Commit the task studio slice**

```bash
git add desktop/src/pages/ProjectDetail.tsx desktop/src/components/TaskPanelTimeline.tsx desktop/src/styles.css tests/test_operational_views.py tests/test_service_api.py
git commit -m "feat: center Sarathi desktop on the task studio"
```

---

### Task 6: Reframe Inbox, Agents, and Settings as Support Surfaces

**Files:**
- Modify: `desktop/src/pages/Inbox.tsx`
- Modify: `desktop/src/pages/Agents.tsx`
- Modify: `desktop/src/pages/Settings.tsx`
- Modify or delete if unused: `desktop/src/components/Sidebar.tsx`
- Modify: `desktop/src/styles.css`

- [ ] **Step 1: Reclassify the support surfaces**

Apply these rules:
- Inbox = human attention queue
- Agents = provider and dispatch health
- Settings = configuration and trust posture
- remove or ignore generic team/workflow-product framing

- [ ] **Step 2: Implement inbox changes**

Show:
- blocked work
- approvals needed
- failed reviews
- restart-ready checkpoints
- handoff-ready items

- [ ] **Step 3: Implement agents and settings changes**

Agents:
- provider health
- dispatch posture
- failures/degraded state

Settings:
- provider checks
- repo policy defaults
- workspace bootstrap posture
- no decorative filler

- [ ] **Step 4: Remove dead or misleading shell leftovers**

If `desktop/src/components/Sidebar.tsx` is dead, delete it or leave it unused only if removal risks unrelated churn. Do not leave old route concepts like `home` in active code paths.

- [ ] **Step 5: Run desktop build and verify it passes**

Run:

```bash
npm --prefix desktop run build
```

Expected:
- PASS with coherent support surfaces and no dead-route regressions.

- [ ] **Step 6: Commit the support-surface slice**

```bash
git add desktop/src/pages/Inbox.tsx desktop/src/pages/Agents.tsx desktop/src/pages/Settings.tsx desktop/src/styles.css desktop/src/components/Sidebar.tsx
git commit -m "feat: align support surfaces with Sarathi orchestration workflow"
```

---

### Task 7: Verify, Review, and Close Gaps

**Files:**
- Modify only what verification exposes
- Optional: `desktop/scripts/*` if browser helpers are required

- [ ] **Step 1: Run the consolidated test and build suite**

Run:

```bash
npm --prefix desktop run build
python3 -m pytest tests/test_service_api.py tests/test_operational_views.py tests/test_task_creation.py tests/test_task_graph.py -v
```

Expected:
- PASS across desktop build and relevant service tests.

- [ ] **Step 2: Run browser QA on the primary flow**

Validate:
- workspace selection and readiness
- project creation and project listing
- task creation into a persisted project
- task studio rendering
- checkpoint visibility/restart
- handoff/review visibility

- [ ] **Step 3: Fix any regressions exposed by verification**

Only touch files directly implicated by failing build/tests/QA. Keep the scope aligned with the approved design.

- [ ] **Step 4: Re-run verification until green**

Run the same build/tests/QA commands again and confirm no unresolved failures remain.

- [ ] **Step 5: Commit the verification fixes**

```bash
git add -A
git commit -m "fix: close Sarathi desktop hardening verification gaps"
```

---

## Self-Review

Spec coverage:
- workspace/project/task IA: covered by Tasks 3-5
- policy/lifecycle/gate visibility: covered by Tasks 2 and 5
- support-surface reframing: covered by Task 6
- persistence trust: covered by Tasks 1-3
- verification: covered by Task 7

Placeholder scan:
- No `TODO` or `TBD`
- Every task includes exact files and commands

Type consistency:
- Project persistence is introduced before shell rewiring depends on it
- Projection helpers precede workspace/project surface rebuild
- Task studio polishing depends on existing studio/panel/checkpoint API contracts, with test updates included where needed

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-sarathi-desktop-orchestration-studio.md`.

Execution mode for this run is already chosen: use OpenCode as the bounded implementer and keep this session as the orchestrator/technical lead that scopes, verifies, reviews, and decides the next slice.
