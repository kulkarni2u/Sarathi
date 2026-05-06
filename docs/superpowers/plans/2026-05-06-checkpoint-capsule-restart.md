# Sarathi Checkpoint Capsule and Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact checkpoint capsule when a task completes so users can start a fresh Sarathi session from the summary instead of carrying the full old thread forward.

**Architecture:** Store checkpoints as their own SQLite records so they can be retrieved independently from the source task, then expose a task-panel snapshot endpoint and a restart-from-checkpoint flow in the desktop UI. The source task remains the system of record for full history, evidence, and handoff detail; the checkpoint is just a small restart capsule with pointers back to the original task.

**Tech Stack:** Python service + SQLite, React + TypeScript desktop UI, existing Sarathi task panel, existing SSE stream, Pytest, Playwright/browser validation.

---

## File Structure

- Modify: `src/storage/__init__.py` to add a checkpoint capsule table, storage methods, and migration version bump.
- Modify: `src/service/__init__.py` to create checkpoints when tasks complete or hand off, expose a retrieve endpoint, and add a restart-from-checkpoint endpoint.
- Modify: `desktop/src/apiClient.ts` to add typed checkpoint client helpers and the new restart request shape.
- Modify: `desktop/src/pages/ProjectDetail.tsx` to render the compact checkpoint card and restart actions in the task panel.
- Modify: `desktop/src/App.tsx` if the existing task studio needs a route or tab entry for starting a new session from a checkpoint.
- Modify: `tests/test_storage.py` to verify checkpoint persistence and retrieval ordering.
- Modify: `tests/test_service_api.py` to verify checkpoint creation on `done`/`handoff` and restart behavior.
- Modify: `desktop/scripts/validate-task-panel.mjs` or create a new validation script to cover the completed-task restart flow.

## Task 1: Add checkpoint persistence in SQLite

**Files:**
- Modify: `src/storage/__init__.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write the failing storage test**

```python
def test_storage_checkpoint_capsule_round_trip(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Checkpoint source",
            status="done",
            metadata={"phase": "done"},
        )
        checkpoint = storage.create_checkpoint_capsule(
            workspace_id=workspace["id"],
            task_id=task["id"],
            summary="Task completed and ready for a fresh session.",
            key_decisions=["Keep commit/PR default-off"],
            evidence_refs=["evidence:123"],
            repository_action_preference={"scope": "workspace", "mode": "no_action"},
            next_start_point="Open a new session from the completed result.",
            created_by="Sarathi",
        )
        assert checkpoint["source_task_id"] == task["id"]
        assert checkpoint["summary"] == "Task completed and ready for a fresh session."
        assert storage.get_checkpoint_capsule(checkpoint["id"]) is not None
        assert storage.list_checkpoint_capsules_for_task(task["id"])[0]["id"] == checkpoint["id"]
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_storage.py -k checkpoint_capsule -v`
Expected: fail because the storage methods do not exist yet.

- [ ] **Step 2: Add the checkpoint table and storage methods**

Add a new migration block and set `LATEST_SCHEMA_VERSION = 3`.

```python
CREATE TABLE IF NOT EXISTS checkpoint_capsules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    source_task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_decisions TEXT NOT NULL DEFAULT '[]',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    repository_action_preference TEXT NOT NULL DEFAULT '{}',
    next_start_point TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (source_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (source_task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_capsules_task
    ON checkpoint_capsules(workspace_id, source_task_id);
```

Add these methods to `Storage`:

```python
def create_checkpoint_capsule(
    self,
    *,
    workspace_id: str,
    task_id: str,
    summary: str,
    key_decisions: list[str],
    evidence_refs: list[str],
    repository_action_preference: dict[str, Any],
    next_start_point: str,
    created_by: str,
    project_id: str | None = None,
    status: str = "ready",
) -> dict[str, Any]:
    checkpoint_id = _new_id()
    now = _utc_now()
    self.conn.execute(
        """
        INSERT INTO checkpoint_capsules (
            id, workspace_id, project_id, source_task_id, status,
            summary, key_decisions, evidence_refs,
            repository_action_preference, next_start_point, created_at, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            checkpoint_id,
            workspace_id,
            project_id,
            task_id,
            status,
            summary,
            _dump_json(key_decisions),
            _dump_json(evidence_refs),
            _dump_json(repository_action_preference),
            next_start_point,
            now,
            created_by,
        ),
    )
    self.conn.commit()
    checkpoint = self.get_checkpoint_capsule(checkpoint_id)
    assert checkpoint is not None
    return checkpoint

def get_checkpoint_capsule(self, checkpoint_id: str) -> dict[str, Any] | None:
    row = self.conn.execute(
        """
        SELECT id, workspace_id, project_id, source_task_id, status, summary,
               key_decisions, evidence_refs, repository_action_preference,
               next_start_point, created_at, created_by
        FROM checkpoint_capsules
        WHERE id = ?
        """,
        (checkpoint_id,),
    ).fetchone()
    return _checkpoint_capsule_from_row(row) if row is not None else None

def list_checkpoint_capsules_for_task(self, task_id: str) -> list[dict[str, Any]]:
    rows = self.conn.execute(
        """
        SELECT id, workspace_id, project_id, source_task_id, status, summary,
               key_decisions, evidence_refs, repository_action_preference,
               next_start_point, created_at, created_by
        FROM checkpoint_capsules
        WHERE source_task_id = ?
        ORDER BY created_at, id
        """,
        (task_id,),
    ).fetchall()
    return [_checkpoint_capsule_from_row(row) for row in rows]
```

- [ ] **Step 3: Run the storage test again**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_storage.py -k checkpoint_capsule -v`
Expected: PASS.

## Task 2: Create checkpoints when tasks complete or hand off

**Files:**
- Modify: `src/service/__init__.py`
- Modify: `tests/test_service_api.py`

- [ ] **Step 1: Write the failing API test**

```python
def test_task_handoff_creates_checkpoint_capsule(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(request(app, "POST", "/api/workspaces", {"name": "QA", "root_path": "/tmp/qa"}))
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(request(app, "POST", f"/api/workspaces/{workspace_id}/tasks", {"title": "Checkpoint task"}))
    task_id = task_data["task"]["id"]
    storage = Storage(connect(tmp_path / "sarathi.db"))
    storage.create_review_run(workspace_id=workspace_id, task_id=task_id, status="approved", summary="OK")
    status, handoff_data = assert_ok(request(app, "POST", f"/api/tasks/{task_id}/handoff", {}))
    assert status == 201
    checkpoint = handoff_data["checkpoint"]
    assert checkpoint["source_task_id"] == task_id
    assert checkpoint["status"] == "ready"
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_service_api.py -k checkpoint -v`
Expected: fail until the handoff/completion path writes checkpoints.

- [ ] **Step 2: Implement checkpoint creation and retrieval endpoints**

Add the creation call in the same place the task transitions to `done` or `handoff`, using the latest task summary, evidence IDs, and active repository-action preference.

Expose two minimal routes:

```python
if method == "GET" and len(parts) == 3 and parts[0] == "tasks" and parts[2] == "checkpoint":
    task = storage.get_task(parts[1])
    if task is None:
        raise ServiceError("not_found", "Task not found.", 404)
    checkpoints = storage.list_checkpoint_capsules_for_task(task["id"])
    return 200, {"checkpoint": checkpoints[-1] if checkpoints else None}

if method == "POST" and len(parts) == 4 and parts[0] == "tasks" and parts[2] == "checkpoint" and parts[3] == "restart":
    task = storage.get_task(parts[1])
    if task is None:
        raise ServiceError("not_found", "Task not found.", 404)
    checkpoint = _latest_or_none(storage.list_checkpoint_capsules_for_task(task["id"]))
    if checkpoint is None:
        raise ServiceError("not_found", "Checkpoint not found.", 404)
    new_task = storage.create_task(
        workspace_id=checkpoint["workspace_id"],
        title=f"Resume: {checkpoint['summary'][:80]}",
        description=checkpoint["summary"],
        status="prd_pending",
        metadata={
            "source_checkpoint_id": checkpoint["id"],
            "source_task_id": checkpoint["source_task_id"],
            "project_id": checkpoint["project_id"],
            "repository_action_preference": checkpoint["repository_action_preference"],
        },
    )
    storage.create_lifecycle_event(
        workspace_id=checkpoint["workspace_id"],
        task_id=new_task["id"],
        event_type="task.checkpoint_restarted",
        payload={
            "object_id": checkpoint["id"],
            "source_task_id": checkpoint["source_task_id"],
        },
    )
    return 201, {"task": new_task, "checkpoint": checkpoint}
```

The restart route should create a new task draft in the same workspace/project context and seed its title/description from the checkpoint capsule summary.

- [ ] **Step 3: Run the API test again**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_service_api.py -k checkpoint -v`
Expected: PASS.

## Task 3: Show checkpoint and restart actions in the task panel

**Files:**
- Modify: `desktop/src/apiClient.ts`
- Modify: `desktop/src/pages/ProjectDetail.tsx`
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Add the typed checkpoint client contract**

```typescript
export type CheckpointCapsuleRecord = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  source_task_id: string;
  status: string;
  summary: string;
  key_decisions: string[];
  evidence_refs: string[];
  repository_action_preference: RepositoryActionPreferenceRecord;
  next_start_point: string;
  created_at: string;
  created_by: string;
};

export async function getTaskCheckpoint(taskId: string): Promise<CheckpointCapsuleRecord | null>;
export async function restartTaskFromCheckpoint(taskId: string): Promise<{ task: TaskRecord; checkpoint: CheckpointCapsuleRecord }>;
```

- [ ] **Step 2: Render the checkpoint card**

The task panel should show a compact card when a checkpoint exists:

```tsx
<Card>
  <strong>Checkpoint ready</strong>
  <p>{checkpoint.summary}</p>
  <small>{checkpoint.next_start_point}</small>
  <button onClick={handleStartNewSession}>Start new session</button>
  <button onClick={handleOpenSourceTask}>Open source task</button>
</Card>
```

Keep the panel collapsed by default. Do not expand the full transcript.

- [ ] **Step 3: Wire the restart action to the new session flow**

`Start new session` should create a new task seeded from the checkpoint capsule and navigate the user to the new task panel.

- [ ] **Step 4: Run the desktop build**

Run: `cd /Users/sweethome/Work/Skills/Sarathi/desktop && npm run build`
Expected: PASS.

## Task 4: Validate the completed-task restart loop

**Files:**
- Modify: `tests/test_service_api.py`
- Modify: `desktop/scripts/validate-task-panel.mjs`

- [ ] **Step 1: Add a browser/service test for restart from checkpoint**

Add a service test that verifies:

```python
assert checkpoint["summary"]
assert restart_data["task"]["workspace_id"] == workspace_id
assert restart_data["task"]["metadata"]["source_checkpoint_id"] == checkpoint["id"]
```

- [ ] **Step 2: Update the Playwright validation flow**

Validate the following sequence:

1. Open a completed task.
2. Confirm the checkpoint card is visible.
3. Click `Start new session`.
4. Confirm a new task panel opens with the checkpoint summary seeded into the new task context.

- [ ] **Step 3: Run the validation script**

Run: `cd /Users/sweethome/Work/Skills/Sarathi/desktop && npm run validate:task-panel`
Expected: PASS.

## Spec Coverage Check

- Compact by default: covered by Task 1 and Task 3.
- Retrievable later: covered by Task 1 and Task 2.
- Task-panel first: covered by Task 3.
- Policy-backed handoff: covered by Task 2 and the checkpoint fields.
- Error and safety rules: covered by Task 2 and Task 4.
- Non-goals respected: no full replay, no second transcript store, no SSE redesign.

## Notes for Implementers

- Prefer a dedicated checkpoint table over hiding the capsule in handoff metadata; the restart path will stay simpler and easier to test.
- Keep the source task as the long-form record of history, evidence, and handoff details.
- Use compact summaries in the checkpoint and let the original task carry the heavy context.
