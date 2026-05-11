# Sarathi Brainstorm Phase Implementation Plan

> **For agentic workers (OpenCode / any provider):** Implement task-by-task in order.
> Tasks 1-4 are backend (Python). Tasks 5-10 are frontend (TypeScript/React).
> Task 11 is SKILL.md (markdown only). Backend must be complete before frontend.
> Run verification commands exactly as written. Commit after every task.

**Goal:** Replace Sarathi's evidence-gate Brainstorm phase with a structured,
provider-agnostic dialogue that produces an approved spec, persisted in SQLite,
surfaced in a Desktop overlay — before any Plan or Build phase begins.

**Architecture:** Python service is the hub (5 new endpoints, SSE events extended).
`brainstorm_sessions` SQLite table persists dialogue turns, research findings, and
live spec draft. Desktop gets a full-panel Brainstorm overlay (4 new components).
Skill (any agent runtime) calls the same service API; Desktop shows the overlay.

**Tech Stack:** Python 3.10+, SQLite, React 19, TypeScript, Vite, Radix UI

**Spec:** `docs/superpowers/specs/2026-05-10-sarathi-brainstorm-phase-design.md`

---

## File Map

**Created:**
- `src/storage/__init__.py` — add `_MIGRATION_005`, bump `LATEST_SCHEMA_VERSION` to 5, add brainstorm CRUD
- `src/service/__init__.py` — add 5 brainstorm endpoints + SSE events
- `tests/test_brainstorm_api.py` — new test file
- `src/phases/brainstorm.py` — rewrite session lifecycle driver
- `desktop/src/pages/Brainstorm.tsx` — full-panel overlay page
- `desktop/src/components/BrainstormChat.tsx` — dialogue thread + clickable options
- `desktop/src/components/SpecPreview.tsx` — live markdown → HTML render
- `desktop/src/components/ResearchPanel.tsx` — Explore agent findings panel

**Modified:**
- `desktop/src/apiClient.ts` — 4 new brainstorm client functions + types
- `desktop/src/App.tsx` — `/brainstorm/:id` route + "New Task" entry point change
- `Sarathi-Skill/SKILL.md` — replace brainstorm phase block

---

## Task 1: Storage — brainstorm_sessions migration + CRUD

**Files:**
- Modify: `src/storage/__init__.py`

- [ ] **Step 1: Write the failing storage test**

Create `tests/test_brainstorm_storage.py`:

```python
import pytest
from src.storage import Storage, connect, run_migrations


def make_storage(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    return Storage(conn)


def test_brainstorm_session_can_be_created_and_retrieved(tmp_path):
    storage = make_storage(tmp_path)
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))

    session = storage.create_brainstorm_session(
        workspace_id=ws["id"],
        title="Add OAuth2 login",
    )

    assert session["id"]
    assert session["workspace_id"] == ws["id"]
    assert session["title"] == "Add OAuth2 login"
    assert session["status"] == "active"
    assert session["dialogue_turns"] == []
    assert session["research_findings"] == []
    assert session["spec_content"] is None


def test_brainstorm_session_turns_can_be_appended(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    turn = {"role": "sarathi", "content": "Which approach?", "options": ["A", "B"]}
    updated = storage.append_brainstorm_turn(session["id"], turn)

    assert len(updated["dialogue_turns"]) == 1
    assert updated["dialogue_turns"][0]["content"] == "Which approach?"


def test_brainstorm_session_research_can_be_appended(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    finding = {"agent": "Vichara", "type": "codebase", "summary": "Found src/auth.py"}
    updated = storage.append_brainstorm_research(session["id"], finding)

    assert len(updated["research_findings"]) == 1
    assert updated["research_findings"][0]["agent"] == "Vichara"


def test_brainstorm_session_spec_can_be_updated(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    updated = storage.update_brainstorm_spec(session["id"], "## Goal\nAdd auth")

    assert updated["spec_content"] == "## Goal\nAdd auth"


def test_brainstorm_session_can_be_approved(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    approved = storage.approve_brainstorm_session(session["id"])

    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/sweethome/Work/Skills/Sarathi
python3 -m pytest tests/test_brainstorm_storage.py -v
```

Expected: `FAILED — Storage has no attribute 'create_brainstorm_session'`

- [ ] **Step 3: Bump schema version and add migration**

In `src/storage/__init__.py`, change line 13:
```python
LATEST_SCHEMA_VERSION = 5
```

Add migration block in `run_migrations` after the `< 4` block:
```python
    if current_schema_version(conn) < 5:
        conn.executescript(_MIGRATION_005)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (5, _utc_now()),
        )
        conn.commit()
```

Add at the bottom of the file (after `_MIGRATION_004`):
```python
_MIGRATION_005 = """
CREATE TABLE IF NOT EXISTS brainstorm_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    task_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL,
    provider TEXT,
    spec_path TEXT,
    spec_content TEXT,
    output_format TEXT NOT NULL DEFAULT 'markdown',
    dialogue_turns TEXT NOT NULL DEFAULT '[]',
    research_findings TEXT NOT NULL DEFAULT '[]',
    visual_options TEXT NOT NULL DEFAULT '[]',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_brainstorm_sessions_workspace
    ON brainstorm_sessions(workspace_id);

CREATE INDEX IF NOT EXISTS idx_brainstorm_sessions_status
    ON brainstorm_sessions(workspace_id, status);
"""
```

- [ ] **Step 4: Add CRUD methods to the Storage class**

Add these methods to the `Storage` class in `src/storage/__init__.py` after `list_workspace_repositories`:

```python
    def create_brainstorm_session(
        self,
        *,
        workspace_id: str,
        title: str,
        project_id: str | None = None,
        provider: str | None = None,
        output_format: str = "markdown",
    ) -> dict[str, Any]:
        session_id = _new_id()
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO brainstorm_sessions (
                id, workspace_id, project_id, title, provider, output_format,
                dialogue_turns, research_findings, visual_options,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, workspace_id, project_id, title, provider, output_format,
                "[]", "[]", "[]", now, now,
            ),
        )
        self.conn.commit()
        session = self.get_brainstorm_session(session_id)
        assert session is not None
        return session

    def get_brainstorm_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, workspace_id, project_id, task_id, status, title, provider,
                   spec_path, spec_content, output_format, dialogue_turns,
                   research_findings, visual_options, approved_at, created_at, updated_at
            FROM brainstorm_sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return _brainstorm_session_from_row(row) if row is not None else None

    def list_brainstorm_sessions(
        self, workspace_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                """
                SELECT id, workspace_id, project_id, task_id, status, title, provider,
                       spec_path, spec_content, output_format, dialogue_turns,
                       research_findings, visual_options, approved_at, created_at, updated_at
                FROM brainstorm_sessions
                WHERE workspace_id = ? AND status = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT id, workspace_id, project_id, task_id, status, title, provider,
                       spec_path, spec_content, output_format, dialogue_turns,
                       research_findings, visual_options, approved_at, created_at, updated_at
                FROM brainstorm_sessions
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [_brainstorm_session_from_row(row) for row in rows]

    def append_brainstorm_turn(
        self, session_id: str, turn: dict[str, Any]
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        turns = session["dialogue_turns"]
        turns.append(turn)
        now = _utc_now()
        self.conn.execute(
            "UPDATE brainstorm_sessions SET dialogue_turns = ?, updated_at = ? WHERE id = ?",
            (_dump_json(turns), now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def append_brainstorm_research(
        self, session_id: str, finding: dict[str, Any]
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        findings = session["research_findings"]
        findings.append(finding)
        now = _utc_now()
        self.conn.execute(
            "UPDATE brainstorm_sessions SET research_findings = ?, updated_at = ? WHERE id = ?",
            (_dump_json(findings), now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def update_brainstorm_spec(
        self, session_id: str, spec_content: str, spec_path: str | None = None
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE brainstorm_sessions
            SET spec_content = ?, spec_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (spec_content, spec_path or session["spec_path"], now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated

    def approve_brainstorm_session(
        self, session_id: str, *, task_id: str | None = None
    ) -> dict[str, Any]:
        session = self.get_brainstorm_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE brainstorm_sessions
            SET status = 'approved', approved_at = ?, task_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, task_id, now, session_id),
        )
        self.conn.commit()
        updated = self.get_brainstorm_session(session_id)
        assert updated is not None
        return updated
```

- [ ] **Step 5: Add the row deserialiser helper**

Add this function near the other `_*_from_row` helpers at the bottom of `src/storage/__init__.py`:

```python
def _brainstorm_session_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "title": row["title"],
        "provider": row["provider"],
        "spec_path": row["spec_path"],
        "spec_content": row["spec_content"],
        "output_format": row["output_format"],
        "dialogue_turns": _load_json_list(row["dialogue_turns"]),
        "research_findings": _load_json_list(row["research_findings"]),
        "visual_options": _load_json_list(row["visual_options"]),
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
```

Note: use `_load_json_list` (not `_load_json`) — it already exists in `src/storage/__init__.py:1484`
and handles the JSON array columns correctly.

- [ ] **Step 6: Run storage tests and confirm they pass**

```bash
python3 -m pytest tests/test_brainstorm_storage.py -v
```

Expected: `5 passed`

- [ ] **Step 7: Confirm existing tests still pass**

```bash
python3 -m pytest tests/ -q --tb=short
```

Expected: all passing (count increases by 5)

- [ ] **Step 8: Commit**

```bash
git add src/storage/__init__.py tests/test_brainstorm_storage.py
git commit -m "feat: brainstorm_sessions storage — migration 005 + CRUD"
```

---

## Task 2: Service Endpoints

**Files:**
- Modify: `src/service/__init__.py`
- Create: `tests/test_brainstorm_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_brainstorm_api.py`:

```python
import pytest
from src.service import create_app
from tests.test_service_api import assert_ok, assert_error, request


def make_app_with_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    status, data = assert_ok(
        request(app, "POST", "/api/workspaces", {
            "name": "Test WS", "root_path": str(tmp_path)
        })
    )
    return app, data["workspace"]


def test_brainstorm_session_can_be_created(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)

    status, data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"],
        "title": "Add OAuth2 login",
    }))

    assert status == 200
    assert data["session"]["id"]
    assert data["session"]["title"] == "Add OAuth2 login"
    assert data["session"]["status"] == "active"


def test_brainstorm_session_can_be_retrieved(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test"
    }))
    session_id = create_data["session"]["id"]

    status, data = assert_ok(request(app, "GET", f"/api/brainstorm/{session_id}"))

    assert data["session"]["id"] == session_id


def test_brainstorm_turn_can_be_appended(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test"
    }))
    session_id = create_data["session"]["id"]

    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/turns", {
        "role": "sarathi",
        "content": "Which auth approach?",
        "options": ["JWT", "Sessions"],
    }))

    assert len(data["session"]["dialogue_turns"]) == 1
    assert data["session"]["dialogue_turns"][0]["content"] == "Which auth approach?"


def test_brainstorm_research_can_be_appended(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test"
    }))
    session_id = create_data["session"]["id"]

    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/research", {
        "agent": "Vichara",
        "type": "codebase",
        "summary": "Found existing auth at src/auth.py",
    }))

    assert len(data["session"]["research_findings"]) == 1
    assert data["session"]["research_findings"][0]["agent"] == "Vichara"


def test_brainstorm_session_can_be_approved(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test"
    }))
    session_id = create_data["session"]["id"]

    # Add spec content first
    request(app, "POST", f"/api/brainstorm/{session_id}/turns", {
        "role": "sarathi", "content": "Q", "spec_update": "## Goal\nDo the thing"
    })

    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/approve", {}))

    assert data["session"]["status"] == "approved"
    assert data["session"]["approved_at"] is not None
    assert data["task"]["id"]


def test_brainstorm_session_not_found_returns_404(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    assert_error(
        request(app, "GET", "/api/brainstorm/nonexistent"),
        status=404, code="not_found"
    )
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_brainstorm_api.py -v
```

Expected: `FAILED — 404 on POST /api/brainstorm/sessions`

- [ ] **Step 3: Add the 5 service endpoints**

In `src/service/__init__.py`, find the `create_app` function's main dispatch block.
Add these route handlers **before** the final `raise ServiceError("not_found", ...)`:

```python
        # ── Brainstorm sessions ──────────────────────────────────────
        if (
            method == "POST"
            and len(parts) == 2
            and parts[0] == "brainstorm"
            and parts[1] == "sessions"
        ):
            workspace_id = _required_text(body, "workspace_id")
            if storage.get_workspace(workspace_id) is None:
                raise ServiceError("not_found", "Workspace not found.", 404)
            title = _required_text(body, "title")
            project_id = _optional_text(body, "project_id")
            provider = _optional_text(body, "provider")
            output_format = _optional_text(body, "output_format") or "markdown"
            session = storage.create_brainstorm_session(
                workspace_id=workspace_id,
                title=title,
                project_id=project_id,
                provider=provider,
                output_format=output_format,
            )
            _emit_event(storage, "brainstorm.session_started", {
                "session_id": session["id"],
                "workspace_id": workspace_id,
                "title": title,
            }, workspace_id=workspace_id)
            return 200, {"session": session}

        if (
            method == "GET"
            and len(parts) == 2
            and parts[0] == "brainstorm"
        ):
            session_id = parts[1]
            session = storage.get_brainstorm_session(session_id)
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            return 200, {"session": session}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "brainstorm"
            and parts[2] == "turns"
        ):
            session_id = parts[1]
            session = storage.get_brainstorm_session(session_id)
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            turn = {
                "role": _required_text(body, "role"),
                "content": _required_text(body, "content"),
                "options": body.get("options", []),
                "selected": body.get("selected"),
                "timestamp": _utc_now(),
            }
            updated = storage.append_brainstorm_turn(session_id, turn)
            spec_update = _optional_text(body, "spec_update")
            if spec_update:
                updated = storage.update_brainstorm_spec(session_id, spec_update)
                _emit_event(storage, "brainstorm.spec_updated", {
                    "session_id": session_id,
                }, workspace_id=updated["workspace_id"])
            _emit_event(storage, "brainstorm.turn_added", {
                "session_id": session_id,
                "role": turn["role"],
            }, workspace_id=updated["workspace_id"])
            return 200, {"session": updated}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "brainstorm"
            and parts[2] == "research"
        ):
            session_id = parts[1]
            session = storage.get_brainstorm_session(session_id)
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            finding = {
                "agent": _required_text(body, "agent"),
                "type": _optional_text(body, "type") or "codebase",
                "summary": _required_text(body, "summary"),
                "refs": body.get("refs", []),
                "timestamp": _utc_now(),
            }
            updated = storage.append_brainstorm_research(session_id, finding)
            _emit_event(storage, "brainstorm.research_added", {
                "session_id": session_id,
                "agent": finding["agent"],
            }, workspace_id=updated["workspace_id"])
            return 200, {"session": updated}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "brainstorm"
            and parts[2] == "approve"
        ):
            session_id = parts[1]
            session = storage.get_brainstorm_session(session_id)
            if session is None:
                raise ServiceError("not_found", "Brainstorm session not found.", 404)
            if session["status"] == "approved":
                raise ServiceError("conflict", "Session already approved.", 409)
            # Create a task from the approved spec
            spec_content = session["spec_content"] or f"# {session['title']}\n"
            task = storage.create_task(
                workspace_id=session["workspace_id"],
                title=session["title"],
                description=spec_content,
                metadata={
                    "source": "brainstorm",
                    "brainstorm_session_id": session_id,
                    "project_id": session["project_id"],
                },
            )
            # Write spec to artifact store
            spec_path = _write_brainstorm_spec(session, task["id"])
            approved = storage.approve_brainstorm_session(
                session_id, task_id=task["id"]
            )
            if spec_path:
                approved = storage.update_brainstorm_spec(
                    session_id, spec_content, spec_path=spec_path
                )
            _emit_event(storage, "brainstorm.approved", {
                "session_id": session_id,
                "task_id": task["id"],
            }, workspace_id=session["workspace_id"])
            return 200, {"session": approved, "task": task}
```

- [ ] **Step 4: Add `_emit_event` and `_write_brainstorm_spec` helpers**

Add these helper functions near the other private helpers in `src/service/__init__.py`:

```python
def _emit_event(
    storage: Storage,
    event_type: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
    task_id: str | None = None,
) -> None:
    """Persist a lifecycle event so SSE subscribers receive it."""
    try:
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        pass  # event emission is best-effort


def _write_brainstorm_spec(
    session: dict[str, Any], task_id: str
) -> str | None:
    """Write spec content to .sarathi/brainstorm/<session_id>/spec.md."""
    try:
        import os
        sarathi_dir = Path(".sarathi") / "brainstorm" / session["id"]
        sarathi_dir.mkdir(parents=True, exist_ok=True)
        spec_path = sarathi_dir / "spec.md"
        content = session["spec_content"] or f"# {session['title']}\n"
        spec_path.write_text(content, encoding="utf-8")
        return str(spec_path)
    except Exception:
        return None
```

Check if `storage.create_event` exists — search for it:
```bash
grep -n "def create_event" src/storage/__init__.py
```
If it doesn't exist, replace `_emit_event` body with a no-op comment and add a TODO.
If it does exist, use it as-is.

- [ ] **Step 5: Run API tests**

```bash
python3 -m pytest tests/test_brainstorm_api.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest tests/ -q --tb=short
```

Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add src/service/__init__.py tests/test_brainstorm_api.py
git commit -m "feat: brainstorm service endpoints — create, get, turns, research, approve"
```

---

## Task 3: brainstorm.py — Session Lifecycle Driver

**Files:**
- Modify: `src/phases/brainstorm.py`

- [ ] **Step 1: Read the current file**

```bash
cat src/phases/brainstorm.py
```

Note the existing `BrainstormPhase` class structure and `TaskContext` import paths.

- [ ] **Step 2: Rewrite brainstorm.py**

Replace the full contents of `src/phases/brainstorm.py`:

```python
"""Brainstorm phase — structured dialogue driver."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.engine import TaskContext


_EVIDENCE_DIMENSIONS = [
    "alternative_approaches_considered",
    "risks_identified",
    "success_criteria_defined",
    "reversibility_assessed",
]

_EVIDENCE_WEIGHTS = {
    "alternative_approaches_considered": 0.3,
    "risks_identified": 0.3,
    "success_criteria_defined": 0.2,
    "reversibility_assessed": 0.2,
}

_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "alternative_approaches_considered": ["approach", "option", "alternative", "instead", "versus", "vs"],
    "risks_identified": ["risk", "concern", "caveat", "danger", "break", "regression"],
    "success_criteria_defined": ["success", "goal", "criterion", "criteria", "done when", "acceptance"],
    "reversibility_assessed": ["revert", "rollback", "undo", "reversible", "migration", "backward"],
}


class BrainstormPhase:
    """Drive a brainstorm session to an approved spec before allowing Plan."""

    def run(self, context: "TaskContext") -> dict[str, Any]:
        session = self._get_or_create_session(context)
        self._dispatch_research_agents(context, session)
        result = self._wait_for_approval(context, session)
        coverage = self._check_evidence_coverage(result.get("spec_content") or "")
        confidence = sum(
            _EVIDENCE_WEIGHTS[dim]
            for dim in _EVIDENCE_DIMENSIONS
            if coverage.get(dim, False)
        )
        return {
            "outcome": "pass" if confidence >= 0.9 else "escalate",
            "confidence": confidence,
            "evidence_coverage": coverage,
            "spec_path": result.get("spec_path"),
            "session_id": session["id"],
            "task_id": result.get("task_id"),
        }

    def _get_or_create_session(self, context: "TaskContext") -> dict[str, Any]:
        """Resume an active session or create a new one."""
        existing_id = context.metadata.get("brainstorm_session_id")
        if existing_id:
            session = self._get_session(context, existing_id)
            if session and session["status"] == "active":
                return session
        return self._create_session(context)

    def _create_session(self, context: "TaskContext") -> dict[str, Any]:
        import urllib.request
        import urllib.error
        import json as _json
        base_url = context.config.get("service_url", "http://127.0.0.1:8765")
        token = context.config.get("service_token")
        payload = _json.dumps({
            "workspace_id": context.workspace_id,
            "title": context.task_title or context.prompt[:80],
            "project_id": context.metadata.get("project_id"),
            "provider": context.config.get("provider"),
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/sessions",
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {token}"} if token else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        return data["data"]["session"]

    def _get_session(self, context: "TaskContext", session_id: str) -> dict[str, Any] | None:
        import urllib.request
        import json as _json
        base_url = context.config.get("service_url", "http://127.0.0.1:8765")
        token = context.config.get("service_token")
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/{session_id}",
            headers={**({"authorization": f"Bearer {token}"} if token else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            return data["data"]["session"]
        except Exception:
            return None

    def _dispatch_research_agents(
        self, context: "TaskContext", session: dict[str, Any]
    ) -> None:
        """Post initial research findings from Explore-mode sub-agents."""
        findings = []
        # Complexity classification
        complexity = context.metadata.get("complexity", "medium")
        findings.append({
            "agent": "Marga",
            "type": "pattern",
            "summary": f"Task classified as {complexity} complexity",
            "refs": [],
        })
        # Existing codebase context (prompt-derived)
        if context.workspace_root:
            findings.append({
                "agent": "Vichara",
                "type": "reference",
                "summary": f"Workspace root: {context.workspace_root}",
                "refs": [],
            })
        for finding in findings:
            self._post_research(context, session["id"], finding)

    def _post_research(
        self, context: "TaskContext", session_id: str, finding: dict[str, Any]
    ) -> None:
        import urllib.request
        import json as _json
        base_url = context.config.get("service_url", "http://127.0.0.1:8765")
        token = context.config.get("service_token")
        payload = _json.dumps(finding).encode()
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/{session_id}/research",
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass  # best-effort

    def _wait_for_approval(
        self, context: "TaskContext", session: dict[str, Any]
    ) -> dict[str, Any]:
        """Poll until session.status == 'approved' or timeout."""
        timeout_seconds = int(context.config.get("brainstorm_timeout", 3600))
        poll_interval = 5
        elapsed = 0
        while elapsed < timeout_seconds:
            current = self._get_session(context, session["id"])
            if current and current["status"] == "approved":
                return current
            time.sleep(poll_interval)
            elapsed += poll_interval
        # Timeout — escalate for human decision
        return {"spec_content": "", "spec_path": None, "task_id": None}

    def _check_evidence_coverage(self, spec: str) -> dict[str, bool]:
        spec_lower = spec.lower()
        return {
            dim: any(kw in spec_lower for kw in keywords)
            for dim, keywords in _EVIDENCE_KEYWORDS.items()
        }
```

- [ ] **Step 3: Verify no import errors**

```bash
python3 -c "from src.phases.brainstorm import BrainstormPhase; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -q --tb=short
```

Expected: all passing (brainstorm.py changes don't break existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/phases/brainstorm.py
git commit -m "feat: brainstorm phase — session lifecycle driver with service integration"
```

---

## Task 4: apiClient.ts — Brainstorm Client Functions

**Files:**
- Modify: `desktop/src/apiClient.ts`

- [ ] **Step 1: Add types and functions**

In `desktop/src/apiClient.ts`, add after the `PolicyPackFile` type and before `listProviders`:

```typescript
export type BrainstormTurn = {
  role: "sarathi" | "user";
  content: string;
  options?: string[];
  selected?: string | null;
  spec_update?: string | null;
  timestamp: string;
};

export type BrainstormResearchFinding = {
  agent: string;
  type: "codebase" | "risk" | "pattern" | "reference";
  summary: string;
  refs?: string[];
  timestamp: string;
};

export type BrainstormSession = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  task_id: string | null;
  status: "active" | "approved" | "abandoned";
  title: string;
  provider: string | null;
  spec_path: string | null;
  spec_content: string | null;
  output_format: string;
  dialogue_turns: BrainstormTurn[];
  research_findings: BrainstormResearchFinding[];
  visual_options: unknown[];
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export async function createBrainstormSession(
  workspaceId: string,
  title: string,
  options: { projectId?: string; provider?: string; outputFormat?: string } = {},
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    "/api/brainstorm/sessions",
    {
      workspace_id: workspaceId,
      title,
      ...(options.projectId ? { project_id: options.projectId } : {}),
      ...(options.provider ? { provider: options.provider } : {}),
      ...(options.outputFormat ? { output_format: options.outputFormat } : {}),
    },
  );
  return data.session;
}

export async function getBrainstormSession(sessionId: string): Promise<BrainstormSession> {
  const data = await getJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}`,
  );
  return data.session;
}

export async function addBrainstormTurn(
  sessionId: string,
  turn: Omit<BrainstormTurn, "timestamp">,
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/turns`,
    turn as Record<string, unknown>,
  );
  return data.session;
}

export async function addBrainstormResearch(
  sessionId: string,
  finding: Omit<BrainstormResearchFinding, "timestamp">,
): Promise<BrainstormSession> {
  const data = await postJson<{ session: BrainstormSession }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/research`,
    finding as Record<string, unknown>,
  );
  return data.session;
}

export async function approveBrainstormSession(
  sessionId: string,
  options: { exportPath?: string; outputFormat?: string } = {},
): Promise<{ session: BrainstormSession; task: TaskRecord }> {
  return postJson<{ session: BrainstormSession; task: TaskRecord }>(
    `/api/brainstorm/${encodeURIComponent(sessionId)}/approve`,
    {
      ...(options.exportPath ? { export_path: options.exportPath } : {}),
      ...(options.outputFormat ? { output_format: options.outputFormat } : {}),
    },
  );
}
```

- [ ] **Step 2: Build to verify types**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -6
```

Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add desktop/src/apiClient.ts
git commit -m "feat: brainstorm apiClient — session, turns, research, approve"
```

---

## Task 5: ResearchPanel.tsx

**Files:**
- Create: `desktop/src/components/ResearchPanel.tsx`

- [ ] **Step 1: Create the component**

```typescript
// desktop/src/components/ResearchPanel.tsx
import type { BrainstormResearchFinding } from "../apiClient";

const typeIcon: Record<string, string> = {
  codebase: "↳",
  risk: "⚠",
  pattern: "◈",
  reference: "→",
};

interface ResearchPanelProps {
  findings: BrainstormResearchFinding[];
}

export default function ResearchPanel({ findings }: ResearchPanelProps) {
  if (findings.length === 0) {
    return (
      <div style={{ fontSize: "0.78rem", color: "var(--muted)", padding: "8px 0" }}>
        Researching…
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {findings.map((f, idx) => (
        <div
          key={idx}
          style={{
            fontSize: "0.75rem",
            padding: "6px 10px",
            borderRadius: "var(--radius-sm)",
            background: "var(--canvas)",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", gap: 6, alignItems: "baseline", marginBottom: 2 }}>
            <span style={{ color: "var(--accent)", fontWeight: 600 }}>
              {typeIcon[f.type] ?? "·"} {f.agent}
            </span>
            <span style={{ color: "var(--faint)", fontSize: "0.68rem" }}>{f.type}</span>
          </div>
          <div style={{ color: "var(--ink)" }}>{f.summary}</div>
          {f.refs && f.refs.length > 0 && (
            <div style={{ marginTop: 3, display: "flex", gap: 4, flexWrap: "wrap" }}>
              {f.refs.map((ref, i) => (
                <code
                  key={i}
                  style={{
                    fontSize: "0.68rem",
                    padding: "1px 5px",
                    background: "var(--border)",
                    borderRadius: 3,
                    color: "var(--muted)",
                  }}
                >
                  {ref}
                </code>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add desktop/src/components/ResearchPanel.tsx
git commit -m "feat: ResearchPanel component — Explore agent findings"
```

---

## Task 6: SpecPreview.tsx

**Files:**
- Create: `desktop/src/components/SpecPreview.tsx`

- [ ] **Step 1: Create the component**

```typescript
// desktop/src/components/SpecPreview.tsx

interface SpecPreviewProps {
  content: string | null;
  onApprove: () => void;
  onExport: () => void;
  approving: boolean;
  approved: boolean;
}

function markdownToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/^(?!<[h|u|p])/gm, "")
    .trim();
}

export default function SpecPreview({
  content,
  onApprove,
  onExport,
  approving,
  approved,
}: SpecPreviewProps) {
  const html = content ? markdownToHtml(content) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1, overflow: "auto", padding: "0 0 16px" }}>
        {html ? (
          <div
            style={{
              fontSize: "0.82rem",
              lineHeight: 1.6,
              color: "var(--ink)",
            }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <div style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
            Spec will appear here as the dialogue progresses…
          </div>
        )}
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          paddingTop: 12,
          borderTop: "1px solid var(--border)",
        }}
      >
        <button
          onClick={onExport}
          disabled={!content || approved}
          style={{ fontSize: "0.75rem", padding: "4px 10px" }}
        >
          Export spec
        </button>
        <button
          className="btn-primary"
          onClick={onApprove}
          disabled={!content || approving || approved}
          style={{ fontSize: "0.75rem", padding: "4px 12px", marginLeft: "auto" }}
        >
          {approved ? "Approved ✓" : approving ? "Approving…" : "Approve →"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add desktop/src/components/SpecPreview.tsx
git commit -m "feat: SpecPreview component — live markdown render + approve/export"
```

---

## Task 7: BrainstormChat.tsx

**Files:**
- Create: `desktop/src/components/BrainstormChat.tsx`

- [ ] **Step 1: Create the component**

```typescript
// desktop/src/components/BrainstormChat.tsx
import { useState } from "react";
import type { BrainstormTurn } from "../apiClient";

interface BrainstormChatProps {
  turns: BrainstormTurn[];
  onUserTurn: (content: string, selected?: string) => Promise<void>;
  disabled: boolean;
}

export default function BrainstormChat({
  turns,
  onUserTurn,
  disabled,
}: BrainstormChatProps) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const lastSarathiTurn = [...turns].reverse().find((t) => t.role === "sarathi");

  async function handleSubmit(selected?: string) {
    const content = selected ?? input.trim();
    if (!content) return;
    setSubmitting(true);
    try {
      await onUserTurn(content, selected);
      setInput("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 12 }}>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {turns.map((turn, idx) => (
          <div
            key={idx}
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius-sm)",
              background: turn.role === "sarathi" ? "var(--canvas)" : "var(--accent)",
              alignSelf: turn.role === "sarathi" ? "flex-start" : "flex-end",
              maxWidth: "85%",
              fontSize: "0.82rem",
              color: turn.role === "sarathi" ? "var(--ink)" : "#fff",
              border: turn.role === "sarathi" ? "1px solid var(--border)" : "none",
            }}
          >
            {turn.role === "sarathi" && (
              <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginBottom: 4, fontWeight: 600 }}>
                Sarathi
              </div>
            )}
            <div>{turn.content}</div>
            {turn.selected && (
              <div style={{ marginTop: 4, fontSize: "0.7rem", color: turn.role === "sarathi" ? "var(--accent)" : "rgba(255,255,255,0.8)" }}>
                ✓ {turn.selected}
              </div>
            )}
          </div>
        ))}
      </div>

      {lastSarathiTurn?.options && lastSarathiTurn.options.length > 0 && !disabled && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {lastSarathiTurn.options.map((opt, i) => (
            <button
              key={i}
              onClick={() => void handleSubmit(opt)}
              disabled={submitting || disabled}
              style={{
                textAlign: "left",
                padding: "6px 12px",
                fontSize: "0.8rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--surface)",
              }}
            >
              {String.fromCharCode(65 + i)}. {opt}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <input
          style={{
            flex: 1,
            padding: "7px 10px",
            fontSize: "0.82rem",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
          }}
          placeholder={disabled ? "Approved" : "Type your answer…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled || submitting}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
        />
        <button
          onClick={() => void handleSubmit()}
          disabled={!input.trim() || submitting || disabled}
          style={{ padding: "7px 14px", fontSize: "0.82rem" }}
        >
          {submitting ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add desktop/src/components/BrainstormChat.tsx
git commit -m "feat: BrainstormChat component — dialogue thread + clickable options"
```

---

## Task 8: Brainstorm.tsx — Main Overlay Page

**Files:**
- Create: `desktop/src/pages/Brainstorm.tsx`

- [ ] **Step 1: Create the page**

```typescript
// desktop/src/pages/Brainstorm.tsx
import { useEffect, useRef, useState } from "react";
import {
  addBrainstormTurn,
  approveBrainstormSession,
  getBrainstormSession,
  getEventsStreamUrl,
  type BrainstormSession,
} from "../apiClient";
import BrainstormChat from "../components/BrainstormChat";
import ResearchPanel from "../components/ResearchPanel";
import SpecPreview from "../components/SpecPreview";

interface BrainstormProps {
  sessionId: string;
  workspaceId: string | null;
  onApproved: (taskId: string) => void;
}

export default function Brainstorm({ sessionId, workspaceId, onApproved }: BrainstormProps) {
  const [session, setSession] = useState<BrainstormSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const sseRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBrainstormSession(sessionId)
      .then((s) => { if (!cancelled) { setSession(s); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    const url = workspaceId ? getEventsStreamUrl(workspaceId) : null;
    if (!url) return;
    const es = new EventSource(url);
    sseRef.current = es;
    es.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data) as { event_type?: string };
        const type = payload.event_type ?? "";
        if (
          type === "brainstorm.turn_added" ||
          type === "brainstorm.research_added" ||
          type === "brainstorm.spec_updated" ||
          type === "brainstorm.approved"
        ) {
          getBrainstormSession(sessionId).then(setSession).catch(() => null);
        }
      } catch {
        // ignore parse errors
      }
    };
    return () => { es.close(); };
  }, [sessionId, workspaceId]);

  async function handleUserTurn(content: string, selected?: string) {
    if (!session) return;
    const updated = await addBrainstormTurn(sessionId, {
      role: "user",
      content,
      selected: selected ?? null,
    });
    setSession(updated);
  }

  async function handleApprove() {
    if (!session) return;
    setApproving(true);
    try {
      const result = await approveBrainstormSession(sessionId);
      setSession(result.session);
      onApproved(result.task.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setApproving(false);
    }
  }

  function handleExport() {
    if (!session?.spec_content) return;
    const blob = new Blob([session.spec_content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${session.title.toLowerCase().replace(/\s+/g, "-")}-spec.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>Loading brainstorm session…</div>;
  }
  if (error || !session) {
    return <div style={{ padding: 32, color: "var(--red)" }}>{error ?? "Session not found"}</div>;
  }

  const approved = session.status === "approved";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 20px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: "0.68rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Brainstorm · phase 1 of 12
          </div>
          <div style={{ fontSize: "1rem", fontWeight: 600, color: "var(--ink)" }}>
            {session.title}
          </div>
        </div>
        {session.provider && (
          <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "var(--muted)" }}>
            provider: {session.provider}
          </span>
        )}
        {approved && (
          <span style={{
            fontSize: "0.72rem",
            color: "var(--green)",
            background: "rgba(34,197,94,0.1)",
            padding: "2px 8px",
            borderRadius: 4,
            fontWeight: 600,
          }}>
            Approved
          </span>
        )}
      </div>

      {/* Body — two panes */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", flex: 1, overflow: "hidden" }}>
        {/* Left: Research + Dialogue */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          padding: 16,
          borderRight: "1px solid var(--border)",
          overflow: "auto",
        }}>
          {session.research_findings.length > 0 && (
            <div>
              <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                Research
              </div>
              <ResearchPanel findings={session.research_findings} />
            </div>
          )}
          <div style={{ flex: 1, minHeight: 0 }}>
            <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
              Dialogue
            </div>
            <BrainstormChat
              turns={session.dialogue_turns}
              onUserTurn={handleUserTurn}
              disabled={approved}
            />
          </div>
        </div>

        {/* Right: Spec preview */}
        <div style={{ padding: 16, overflow: "auto", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Spec (live)
          </div>
          <SpecPreview
            content={session.spec_content}
            onApprove={() => void handleApprove()}
            onExport={handleExport}
            approving={approving}
            approved={approved}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add desktop/src/pages/Brainstorm.tsx
git commit -m "feat: Brainstorm overlay page — SSE-driven, two-pane layout"
```

---

## Task 9: App.tsx — Route Wiring + New Task Entry Point

**Files:**
- Modify: `desktop/src/App.tsx`

- [ ] **Step 1: Read the current routing section**

```bash
grep -n "route\|setRoute\|WorkspaceDashboard\|ProjectDetail\|dashboard" desktop/src/App.tsx | head -30
```

Note the current route state type and how navigation works.

- [ ] **Step 2: Add brainstorm route to the route type**

Find the route state type definition (look for `useState<"home" | "dashboard"` or similar).
Add `"brainstorm"` to the union and add `brainstormSessionId` state:

```typescript
// Find and extend the existing route state — example:
const [route, setRoute] = useState<
  "home" | "dashboard" | "inbox" | "agents" | "settings" | "project" | "brainstorm"
>("home");
const [brainstormSessionId, setBrainstormSessionId] = useState<string | null>(null);
```

- [ ] **Step 3: Import Brainstorm page**

Add near the other page imports:
```typescript
import Brainstorm from "./pages/Brainstorm";
```

- [ ] **Step 4: Add brainstorm route to the render switch**

In the main content render block, add a case for `"brainstorm"`:

```typescript
{route === "brainstorm" && brainstormSessionId && (
  <Brainstorm
    sessionId={brainstormSessionId}
    workspaceId={selectedWorkspaceId ?? null}
    onApproved={(taskId) => {
      setSelectedTaskId(taskId);
      setRoute("project");
    }}
  />
)}
```

- [ ] **Step 5: Update "New Task" / create task entry points to go through brainstorm**

Find where `WorkspaceDashboard`'s `onCreateProject` or task creation is wired.
Find where `createTaskDraft` is called directly. Change those entry points to:

1. Call `createBrainstormSession` instead
2. Navigate to `"brainstorm"` with the new session id

```typescript
// Add import at top:
import { createBrainstormSession } from "./apiClient";

// Replace direct task creation in handlers with:
async function handleStartBrainstorm(title: string) {
  if (!selectedWorkspaceId) return;
  try {
    const session = await createBrainstormSession(
      selectedWorkspaceId,
      title,
      { projectId: selectedProjectId ?? undefined },
    );
    setBrainstormSessionId(session.id);
    setRoute("brainstorm");
  } catch (e) {
    console.error("Failed to start brainstorm", e);
  }
}
```

Wire `handleStartBrainstorm` wherever "New Task" or the chat composer currently creates tasks directly.

- [ ] **Step 6: Build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

If TypeScript errors appear, fix types to match existing state variable names — the exact variable names in App.tsx may differ from the examples above.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/App.tsx
git commit -m "feat: wire brainstorm route + redirect New Task through brainstorm phase"
```

---

## Task 10: SKILL.md — Brainstorm Phase Block

**Files:**
- Modify: `Sarathi-Skill/SKILL.md`

- [ ] **Step 1: Read the current brainstorm section**

```bash
grep -n -A 20 "Brainstorm\|brainstorm" Sarathi-Skill/SKILL.md | head -50
```

Note the current evidence-gate description location and surrounding context.

- [ ] **Step 2: Replace the brainstorm phase description**

Find the section describing the Brainstorm phase (will mention evidence weights or confidence gate).
Replace it entirely with:

```markdown
## Brainstorm Phase

Every task starts here. No Plan, no Build until an approved spec exists.
This phase is conducted by the configured provider — the process is identical
regardless of which provider is active (Claude, Codex, OpenCode, Copilot, or custom).

### Process

1. **Research first** — before asking the user anything, dispatch Explore sub-agents:
   - Vichara: scan relevant files, existing patterns, prior decisions
   - Marga: classify complexity, identify affected surfaces
   - POST findings to `/api/brainstorm/:id/research`

2. **One question at a time** — informed by research, not abstract:
   - Multiple choice preferred when options are enumerable
   - Never ask what the code already answers
   - Never ask two questions in one message

3. **Propose 2-3 approaches** with tradeoffs, lead with recommendation

4. **Build spec live** — POST spec_update with each turn:
   - Goal, constraints, success criteria
   - Chosen approach + rationale
   - Explicit out-of-scope
   - Risks identified

5. **Hard gate** — no transition to Plan until:
   - All four evidence dimensions covered in spec
   - User approves (Desktop Approve button or terminal `y`)
   - `POST /api/brainstorm/:id/approve` called and returns `{ session, task }`
   - Task record exists in SQLite

### Evidence Dimensions (auto-checked)
- `alternative_approaches_considered` — weight 0.3
- `risks_identified` — weight 0.3
- `success_criteria_defined` — weight 0.2
- `reversibility_assessed` — weight 0.2

Confidence must reach 0.9 before phase passes.

### Output
- Spec: `.sarathi/brainstorm/<id>/spec.md`
- Task: SQLite `tasks` table, linked to session via `brainstorm_session_id`
- Export: offered, never forced

### Provider Contract
The provider receives a `brainstorm_turn` payload (current context + evidence
coverage + dialogue so far) and returns `{ question, options?, spec_update }`.
The provider does not need to know it is inside a Sarathi lifecycle.
```

- [ ] **Step 3: Verify file is valid markdown**

```bash
head -5 Sarathi-Skill/SKILL.md && grep -c "Brainstorm Phase" Sarathi-Skill/SKILL.md
```

Expected: header shown, count = 1

- [ ] **Step 4: Commit**

```bash
git add Sarathi-Skill/SKILL.md
git commit -m "feat: SKILL.md — provider-agnostic brainstorm phase process"
```

---

## Final Verification

- [ ] **Run full backend test suite**

```bash
python3 -m pytest tests/ -q --tb=short
```

Expected: all passing

- [ ] **Run full desktop build**

```bash
npm --prefix /Users/sweethome/Work/Skills/Sarathi/desktop run build 2>&1 | tail -4
```

Expected: `✓ built`

- [ ] **Smoke test brainstorm API end-to-end**

```bash
python3 -m pytest tests/test_brainstorm_api.py tests/test_brainstorm_storage.py -v
```

Expected: all passing
