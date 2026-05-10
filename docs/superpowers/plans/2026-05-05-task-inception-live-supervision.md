# Task Inception and Live Supervision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users start work in chat, convert that chat into a real workspace-scoped task, and supervise the running task in a live SSE-fed task panel with compact SQLite-backed human and agent updates.

**Architecture:** Keep `api/chat` as the task-inception path and `POST /api/tasks/:id/messages` as the running-task communication path. Project detail becomes the task panel surface, backed by a SQLite projection that merges messages, lifecycle events, dispatches, approvals, evidence, reviews, and handoffs into one compact timeline. SSE stays notification-only and updates the panel without manual refresh.

**Tech Stack:** Python service + SQLite, React + TypeScript desktop UI, existing SSE stream, existing Sarathi CLI/runtime, Playwright for browser validation.

---

## File Structure

- Modify `src/service/__init__.py`: add a task-panel projection endpoint, accept project context for task inception, and emit compact panel events from task/message/lifecycle actions.
- Modify `src/storage/__init__.py`: add a pure projection helper for task panel entries over existing SQLite tables; no new schema if the projection is sufficient.
- Modify `desktop/src/apiClient.ts`: add typed client helpers for the task panel snapshot and task-scoped SSE stream, and extend chat context to include project scope.
- Modify `desktop/src/pages/ProjectDetail.tsx`: render the task panel timeline, compact agent updates, and blocked-state rows; keep graph/list on the left.
- Modify `desktop/src/App.tsx`: route orchestrator chat and new-task creation through the current workspace/project context, and open the created task in the current project.
- Modify `desktop/src/pages/Dashboard.tsx`: make the `New task` flow create a task through chat in the active project context when available.
- Modify `tests/test_service_api.py`: cover task inception, task-panel snapshot ordering, and SSE filtering by `task_id`.
- Modify `tests/test_storage.py`: cover task-panel projection ordering and compact entry shaping.
- Create `desktop/scripts/validate-task-panel.mjs`: repeatable Playwright browser validation for the workspace/project/task flow.
- Create `desktop/src/components/TaskPanelTimeline.tsx` if the ProjectDetail panel grows too large during implementation.

## Task 1: Add a SQLite-backed task panel projection

**Files:**
- Modify: `src/storage/__init__.py`
- Modify: `src/service/__init__.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_service_api.py`

- [ ] **Step 1: Write the failing storage test for the projection**

```python
def test_storage_task_panel_projection_merges_messages_events_and_dispatches(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(workspace_id=workspace["id"], title="Panel", status="in_progress")
        storage.create_message(workspace_id=workspace["id"], task_id=task["id"], role="user", content="Start", metadata={"target": "Sarathi"})
        storage.create_lifecycle_event(workspace_id=workspace["id"], task_id=task["id"], event_type="task.blocked", payload={"reason": "waiting_user"})
        entries = storage.list_task_panel_entries(task["id"])
        assert [entry["kind"] for entry in entries] == ["human_message", "blocked"]
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python -m pytest tests/test_storage.py -k task_panel_projection -v`
Expected: fail with `AttributeError` or missing-method error before implementation.

- [ ] **Step 2: Implement the projection helper**

```python
def list_task_panel_entries(self, task_id: str) -> list[dict[str, Any]]:
    # Merge rows from messages, lifecycle_events, dispatches, approval_gates,
    # evidence_artifacts, review_runs, and handoffs, then normalize each row to:
    # {id, kind, source, target, summary, created_at, metadata, task_id, workspace_id}
    ...
```

- [ ] **Step 3: Add the service snapshot endpoint**

```python
if method == "GET" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "panel":
    task = storage.get_task(parts[1])
    if task is None:
        raise ServiceError("not_found", "Task not found.", 404)
    return 200, {"task_id": task["id"], "entries": storage.list_task_panel_entries(task["id"])}
```

- [ ] **Step 4: Run the service tests**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python -m pytest tests/test_storage.py tests/test_service_api.py -k 'task_panel or task_draft or messages' -v`
Expected: projection test passes, existing task/message tests stay green.

## Task 2: Make task inception chat create real project-scoped work

**Files:**
- Modify: `desktop/src/apiClient.ts`
- Modify: `src/service/__init__.py`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/pages/Dashboard.tsx`
- Modify: `tests/test_service_api.py`

- [ ] **Step 1: Add a failing API test for project-scoped task inception**

```python
def test_chat_creates_task_in_project_context(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(request(app, "POST", "/api/workspaces", {"name": "QA", "root_path": "/tmp/qa"}))
    workspace_id = workspace_data["workspace"]["id"]
    status, payload = assert_ok(
        request(
            app,
            "POST",
            "/api/chat",
            {"message": "Build an onboarding flow", "context": {"workspaceId": workspace_id, "projectId": "proj-1"}},
        )
    )
    assert status == 201
    assert payload["taskId"]
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python -m pytest tests/test_service_api.py -k chat_creates_task_in_project_context -v`
Expected: fail until the chat handler accepts and persists project context.

- [ ] **Step 2: Extend the chat and draft payloads**

```typescript
export async function sendChatMessage(
  message: string,
  context?: { taskId?: string; workspaceId?: string; projectId?: string },
): Promise<{ taskId: string; agent: string; status: string }>;
```

```python
context = body.get("context") or {}
project_id = context.get("projectId") if isinstance(context, dict) else None
metadata = _task_draft_metadata(message)
if project_id:
    metadata["project_id"] = project_id
```

- [ ] **Step 3: Wire the desktop task entry points to current workspace/project context**

Use the current `workspaceId` and `projectId` from the selected workspace/project when calling `sendChatMessage(...)` and `createTaskDraft(...)`, then open the created task in the project panel.

- [ ] **Step 4: Run the chat path tests**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python -m pytest tests/test_service_api.py -k 'chat_creates_task_in_project_context or task_draft' -v`
Expected: chat creates a persisted task draft with project metadata and the existing draft tests still pass.

## Task 3: Turn ProjectDetail into the live task panel

**Files:**
- Modify: `desktop/src/pages/ProjectDetail.tsx`
- Create: `desktop/src/components/TaskPanelTimeline.tsx`
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Write the browser-facing UI contract in code**

```typescript
export type TaskPanelEntry = {
  id: string;
  kind: "human_message" | "agent_update" | "blocked" | "unblocked" | "claimed" | "in_progress" | "review" | "handoff" | "completion" | "evidence" | "system_note";
  source: string;
  target: string | null;
  summary: string;
  created_at: string;
  metadata: Record<string, unknown>;
};
```

- [ ] **Step 2: Add the failing React expectation**

The panel should render a compact stream where agent rows look like `Pravaha: claimed step 2`, blocked rows are highlighted, and human messages stay in chat-bubble form. The left graph stays intact.

Run: `cd /Users/sweethome/Work/Skills/Sarathi/desktop && npm run build`
Expected: build fails until the new panel types and component wiring exist.

- [ ] **Step 3: Implement the panel component**

Use one focused component for the timeline so `ProjectDetail.tsx` stays readable:

```tsx
<TaskPanelTimeline
  entries={panel.entries}
  onSendMessage={handleSendTaskMessage}
  liveState={streamDetail}
/>
```

Render the newest entries first, hide raw transcript verbosity by default, and expose an expand affordance only on demand.

- [ ] **Step 4: Subscribe the task panel to SSE**

Use the existing live stream and add a `task_id` filter so the task panel updates without manual refresh.

```typescript
const streamUrl = `${baseUrl}/api/events/stream?workspace_id=${workspaceId}&task_id=${taskId}&token=${token}`;
```

- [ ] **Step 5: Run the desktop build**

Run: `cd /Users/sweethome/Work/Skills/Sarathi/desktop && npm run build`
Expected: pass.

## Task 4: Validate the end-to-end inception and supervision loop

**Files:**
- Modify: `tests/test_service_api.py`
- Modify: `tests/test_task_dashboard.py`
- Create: `desktop/scripts/validate-task-panel.mjs`

- [ ] **Step 1: Cover the panel snapshot ordering and SSE filtering**

Add service tests that:

```python
def test_task_panel_stream_filters_by_task_id(tmp_path):
    ...
    status, headers, body = http_raw("GET", f"{base_url}/api/events/stream?workspace_id={workspace_id}&task_id={task_id}&token=secret")
    assert "message.created" in body
    assert "approval.requested" in body
```

The panel should only receive entries for the selected task.

- [ ] **Step 2: Cover the dashboard entry point**

Verify the `New task` action still works from the project dashboard and opens the created task panel:

```python
assert payload["task"]["id"]
assert payload["approval_gate"]["status"] == "pending"
```

- [ ] **Step 3: Run browser validation against the desktop app**

Run:

```bash
cd /Users/sweethome/Work/Skills/Sarathi/desktop
npx -p playwright@1.59.1 playwright install chromium
npx -p playwright@1.59.1 -c 'export NODE_PATH=$(dirname $(dirname $(which playwright))); node scripts/validate-task-panel.mjs'
```

`desktop/scripts/validate-task-panel.mjs` should run the exact flow below:

```javascript
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
await page.getByRole("button", { name: /QA Workspace/i }).first().click();
await page.getByRole("button", { name: /Create first project/i }).click();
await page.getByLabel("Project name").fill("Validation Project");
await page.getByLabel("Project description").fill("Validation run.");
await page.getByRole("button", { name: "Create project", exact: true }).click();
await page.waitForLoadState("networkidle");
console.log(await page.locator("body").innerText());
await browser.close();
```

Expected:
- workspace home loads
- workspace dashboard shows no-project empty state when appropriate
- creating/opening a project works
- task panel shows live SSE-fed rows without refresh
- task inception chat creates a real task from the main Sarathi flow

## Self-Review

- Coverage check: Task 1 covers SQLite projection and service snapshotting. Task 2 covers task inception chat and project scope. Task 3 covers the live task panel UI and SSE subscription. Task 4 covers end-to-end verification.
- Placeholder scan: no `TBD`, `TODO`, or vague implementation steps remain.
- Type consistency: `TaskPanelEntry`, `projectId`, `workspaceId`, `task_id`, and `sendChatMessage` are used consistently across tasks.
- Scope check: this plan stays focused on one product loop. If agent management or settings changes are needed later, they should be separate plans.
