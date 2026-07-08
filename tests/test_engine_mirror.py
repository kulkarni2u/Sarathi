"""Tests for the engine -> service SQLite mirror (src/engine_mirror.py)."""

from src.engine import Complexity, Engine, Phase, TaskContext
from src.engine_mirror import EngineRunRecorder
from src.service import create_app
from src.storage import Storage, connect, run_migrations


# ---------------------------------------------------------------- try_create


def test_try_create_returns_none_without_existing_db(tmp_path, monkeypatch):
    monkeypatch.delenv("SARATHI_NO_MIRROR", raising=False)
    db_path = tmp_path / "sarathi.db"
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))

    recorder = EngineRunRecorder.try_create()

    assert recorder is None
    assert not db_path.exists()


def test_try_create_returns_recorder_when_db_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.delenv("SARATHI_NO_MIRROR", raising=False)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))

    recorder = EngineRunRecorder.try_create()

    assert recorder is not None
    assert recorder.db_path == db_path


def test_try_create_disabled_via_no_mirror_env(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_NO_MIRROR", "1")

    recorder = EngineRunRecorder.try_create()

    assert recorder is None


# --------------------------------------------------------- engine wiring


def test_engine_run_recorder_defaults_to_none_without_db(tmp_path, monkeypatch):
    # No sarathi.db anywhere the recorder would look -> Engine runs fine
    # with run_recorder set to None, exactly like the Slack notifier.
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(tmp_path / "sarathi.db"))
    engine = Engine()
    assert engine.run_recorder is None

    task = TaskContext(task_id="t-mirror-quiet", description="quiet", complexity=Complexity.LOW)
    result = engine.run_task(task)

    assert result.current_phase is None
    assert not (tmp_path / "sarathi.db").exists()


def test_engine_run_mirrors_workspace_task_and_lifecycle_events(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    root_path = str(tmp_path / "workspace-root")
    monkeypatch.setenv("SARATHI_WORKDIR", root_path)

    engine = Engine()
    assert engine.run_recorder is not None

    task = TaskContext(task_id="t-mirror-1", description="Mirror me", complexity=Complexity.LOW)
    engine.run_task(task)

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspaces = storage.list_workspaces()
        assert len(workspaces) == 1
        workspace = workspaces[0]
        assert workspace["root_path"] == root_path

        mirrored_tasks = storage.list_tasks_for_workspace(workspace["id"])
        assert len(mirrored_tasks) == 1
        mirrored_task = mirrored_tasks[0]
        assert mirrored_task["metadata"]["engine_task_id"] == "t-mirror-1"
        assert mirrored_task["metadata"]["mirrored_from"] == "engine"
        # Final Learn "completed" promotes to task.completed -> status "done".
        assert mirrored_task["status"] == "done"

        events = storage.list_events(workspace_id=workspace["id"], task_id=mirrored_task["id"])
        event_types = [event["event_type"] for event in events]
        assert "task.completed" in event_types
        assert "phase.completed" in event_types
        completed_event = next(e for e in events if e["event_type"] == "task.completed")
        assert completed_event["payload"]["engine_task_id"] == "t-mirror-1"
        assert completed_event["payload"]["phase"] == Phase.LEARN.value
        assert completed_event["payload"]["status"] == "completed"


def test_engine_run_mirrors_multiple_tasks_into_same_workspace(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path / "workspace-root"))

    engine = Engine()
    engine.run_task(TaskContext(task_id="t-a", description="task a", complexity=Complexity.LOW))
    engine.run_task(TaskContext(task_id="t-b", description="task b", complexity=Complexity.LOW))

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspaces = storage.list_workspaces()
        assert len(workspaces) == 1
        tasks = storage.list_tasks_for_workspace(workspaces[0]["id"])
        assert len(tasks) == 2
        engine_task_ids = {t["metadata"]["engine_task_id"] for t in tasks}
        assert engine_task_ids == {"t-a", "t-b"}


# --------------------------------------------------------- failure handling


def test_record_phase_swallows_storage_failures_and_self_disables(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)

    def _raise(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Storage, "create_task", _raise)

    recorder = EngineRunRecorder.try_create(db_path=str(db_path))
    assert recorder is not None

    task = TaskContext(task_id="t-broken", description="broken", complexity=Complexity.LOW)

    for _ in range(5):
        # Must never raise, regardless of how many times it is called.
        recorder.record_phase(task, Phase.ROUTE, "completed")

    assert recorder.disabled is True


def test_engine_run_completes_even_when_mirror_storage_is_broken(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))

    def _raise(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Storage, "create_task", _raise)

    engine = Engine()
    assert engine.run_recorder is not None

    task = TaskContext(task_id="t-broken-run", description="broken run", complexity=Complexity.LOW)
    result = engine.run_task(task)

    # The run must complete normally despite every mirror write failing.
    assert result.current_phase is None
    assert engine.run_recorder.disabled is True


# --------------------------------------------------------- event mapping


def test_event_types_match_notifications_namespace(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    recorder = EngineRunRecorder.try_create(db_path=str(db_path))
    assert recorder is not None

    task = TaskContext(task_id="t-events", description="events", complexity=Complexity.LOW)

    recorder.record_phase(task, Phase.BUILD, "failed")
    recorder.record_phase(task, Phase.REVIEW, "paused")
    recorder.record_phase(task, Phase.PLAN, "escalated")
    recorder.record_phase(task, Phase.ROUTE, "completed")  # non-final -> phase.completed
    recorder.record_phase(task, Phase.PLANNING_ADVISOR, "skipped")
    recorder.record_phase(task, Phase.LEARN, "completed")  # final -> task.completed

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspace = storage.list_workspaces()[0]
        mirrored_task = storage.list_tasks_for_workspace(workspace["id"])[0]
        events = storage.list_events(workspace_id=workspace["id"], task_id=mirrored_task["id"])
        assert [event["event_type"] for event in events] == [
            "task.failed",
            "task.paused",
            "task.escalated",
            "phase.completed",
            "phase.skipped",
            "task.completed",
        ]
        # Final task.completed wins and leaves the mirrored task "done".
        assert mirrored_task["status"] == "done"


# --------------------------------------------------------- web cockpit visibility


def test_mirrored_task_visible_through_service_app_api(tmp_path, monkeypatch):
    """End-to-end: an engine-run task shows up through the real ServiceApp API.

    Proves the whole point of the mirror -- a task run via CLI/TUI/MCP (no
    HTTP server involved at all) becomes visible read-only through the same
    REST routes the web cockpit polls.
    """
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path / "workspace-root"))

    engine = Engine()
    assert engine.run_recorder is not None
    task = TaskContext(task_id="t-api-visible", description="API visibility check", complexity=Complexity.LOW)
    engine.run_task(task)

    app = create_app(db_path)

    status, payload = app.handle(
        "GET", "/api/workspaces", body=None, headers={"x-correlation-id": "verify"}
    )
    assert status == 200
    workspaces = payload["data"]["workspaces"]
    assert len(workspaces) == 1
    workspace_id = workspaces[0]["id"]

    status, payload = app.handle(
        "GET",
        f"/api/workspaces/{workspace_id}/tasks",
        body=None,
        headers={"x-correlation-id": "verify"},
    )
    assert status == 200
    tasks = payload["data"]["tasks"]
    assert len(tasks) == 1
    mirrored = tasks[0]
    assert mirrored["status"] == "done"
    assert mirrored["metadata"]["engine_task_id"] == "t-api-visible"

    status, payload = app.handle(
        "GET", f"/api/tasks/{mirrored['id']}", body=None, headers={"x-correlation-id": "verify"}
    )
    assert status == 200
    assert payload["data"]["task"]["status"] == "done"
