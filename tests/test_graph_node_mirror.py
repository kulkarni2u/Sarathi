"""Tests for the graph-node -> service SQLite mirror (src/graph_node_mirror.py)."""

from __future__ import annotations

from src.graph_node_mirror import GraphNodeRecorder
from src.runtime import TaskGraphExecutor
from src.runtime.contracts import DispatchResponse, UsageRecord
from src.storage import Storage, connect, run_migrations
from src.task_graph import graph_from_workflow

# ---------------------------------------------------------------- try_create


def test_try_create_returns_none_without_existing_db(tmp_path, monkeypatch):
    monkeypatch.delenv("SARATHI_NO_MIRROR", raising=False)
    db_path = tmp_path / "sarathi.db"
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))

    recorder = GraphNodeRecorder.try_create()

    assert recorder is None
    assert not db_path.exists()


def test_try_create_returns_recorder_when_db_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.delenv("SARATHI_NO_MIRROR", raising=False)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))

    recorder = GraphNodeRecorder.try_create()

    assert recorder is not None
    assert recorder.db_path == db_path


def test_try_create_disabled_via_no_mirror_env(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_NO_MIRROR", "1")

    recorder = GraphNodeRecorder.try_create()

    assert recorder is None


# --------------------------------------------------------- record()


def test_record_upserts_running_then_completed(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    recorder = GraphNodeRecorder.try_create()
    assert recorder is not None

    recorder.record(
        task_id="task-1",
        node_id="node-a",
        node_type="execute",
        status="running",
        started_at="t0",
    )
    recorder.record(
        task_id="task-1",
        node_id="node-a",
        node_type="execute",
        status="completed",
        provider="claude",
        session_artifact_key="claude_session_id",
        session_artifact_value="sess-1",
        completed_at="t1",
    )

    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        node = storage.get_graph_node("task-1", "node-a")

    assert node is not None
    assert node["status"] == "completed"
    assert node["started_at"] == "t0"
    assert node["completed_at"] == "t1"
    assert node["session_artifact_value"] == "sess-1"


def test_record_swallows_storage_failures_and_self_disables(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)

    def _raise(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Storage, "upsert_graph_node", _raise)

    recorder = GraphNodeRecorder.try_create(db_path=str(db_path))
    assert recorder is not None

    for _ in range(5):
        # Must never raise, regardless of how many times it is called.
        recorder.record(
            task_id="task-1", node_id="node-a", node_type="execute", status="running"
        )

    assert recorder.disabled is True


# --------------------------------------------------------- executor wiring


class RecordingSessionDispatcher:
    """Echoes back a claude_session_id artifact, like a real claude dispatch would."""

    def __init__(self):
        self.calls = 0

    def dispatch(self, request):
        self.calls += 1
        return DispatchResponse(
            success=True,
            outputs={"work_unit_result": "done"},
            artifacts={"claude_session_id": f"sess-{self.calls}"},
            usage=UsageRecord(
                provider_id="claude",
                provider_family="gateway",
                dispatch_id=str(request.task_id),
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                estimated=False,
            ),
        )


def test_task_graph_executor_mirrors_fanout_branches(tmp_path, monkeypatch):
    db_path = tmp_path / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    monkeypatch.setenv("SARATHI_MIRROR_DB", str(db_path))
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "fan",
                    "title": "F",
                    "node_type": "fanout",
                    "pattern_config": {"count": 2},
                }
            ]
        }
    ).to_artifact()
    graph["task_id"] = "task-mirror-1"
    dispatcher = RecordingSessionDispatcher()

    TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph)

    with connect(db_path) as conn:
        run_migrations(conn)
        storage = Storage(conn)
        nodes = {
            node["node_id"]: node for node in storage.list_graph_nodes("task-mirror-1")
        }

    assert "fan-branch-1" in nodes
    assert "fan-branch-2" in nodes
    assert nodes["fan-branch-1"]["status"] == "completed"
    assert nodes["fan-branch-1"]["session_artifact_key"] == "claude_session_id"
    assert nodes["fan-branch-1"]["provider"] == "claude"
    assert nodes["fan-branch-1"]["session_artifact_value"]


def test_task_graph_executor_quiet_without_db():
    # No SARATHI_MIRROR_DB pointed at an existing DB -> recorder is None,
    # execution proceeds exactly as it did before this feature existed.
    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "fan",
                    "title": "F",
                    "node_type": "fanout",
                    "pattern_config": {"count": 2},
                }
            ]
        }
    ).to_artifact()
    dispatcher = RecordingSessionDispatcher()

    result = TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph).to_artifact()

    assert "fan-synthesize" in result["graph_state"]["completed_nodes"]
