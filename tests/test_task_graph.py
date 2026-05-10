from src.task_graph import (
    block_graph_node,
    annotate_graph_for_supervision,
    fail_graph_node,
    graph_from_plan,
    graph_summary,
    latest_completed_node,
    latest_failed_node,
    next_ready_node,
    next_retryable_failed_node,
    progress_graph,
    retry_graph_node,
    require_human_for_graph_node,
    supervision_summary,
    start_graph_node,
    task_manifest_from_graph,
)
from src.runtime import TaskGraphExecutor, TaskScheduler
from src.runtime.contracts import DispatchResponse


class RecordingDispatcher:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        return self.response


def test_graph_from_plan_builds_sequential_nodes():
    graph = graph_from_plan(
        {
            "steps": [
                "Analyze requirements",
                "Implement core functionality",
                "Review and refine",
            ]
        }
    ).to_artifact()

    assert len(graph["nodes"]) == 3
    assert graph["ready_nodes"] == ["step-1"]
    assert graph["nodes"][1]["depends_on"] == ["step-1"]


def test_next_ready_node_advances_after_completion():
    graph = graph_from_plan({"steps": ["A", "B", "C"]}).to_artifact()
    assert next_ready_node(graph)["id"] == "step-1"

    progressed = progress_graph(graph, completed_node_id="step-1")
    assert next_ready_node(progressed)["id"] == "step-2"
    assert progressed["completed_nodes"] == ["step-1"]


def test_graph_executor_records_execution_events():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()
    result = TaskGraphExecutor().execute_all(graph)
    artifact = result.to_artifact()

    assert artifact["graph_state"]["completed_nodes"] == ["step-1", "step-2"]
    assert [event["node_id"] for event in artifact["events"]] == ["step-1", "step-2"]


def test_graph_executor_dispatches_ready_nodes_as_child_work_units():
    graph = graph_from_plan({"steps": ["A"]}).to_artifact()
    dispatcher = RecordingDispatcher(
        DispatchResponse(
            success=True,
            outputs={"work_unit_result": "done"},
            evidence={"provider_selected": True},
            artifacts={"provider": "local"},
        )
    )

    result = TaskGraphExecutor(dispatcher=dispatcher).execute_next(graph).to_artifact()

    assert dispatcher.requests[0].constraints["purpose"] == "child_task_execution"
    assert dispatcher.requests[0].inputs["node"]["id"] == "step-1"
    assert result["events"][0]["provider_result"]["success"] is True
    assert result["graph_state"]["completed_nodes"] == ["step-1"]
    assert dispatcher.requests[0].phase == "Build"


def test_graph_executor_marks_provider_failed_node_failed():
    graph = graph_from_plan({"steps": ["A"]}).to_artifact()
    dispatcher = RecordingDispatcher(
        DispatchResponse(success=False, error="provider rejected work unit")
    )

    result = TaskGraphExecutor(dispatcher=dispatcher).execute_next(graph).to_artifact()

    assert result["events"][0]["action"] == "failed"
    assert result["events"][0]["provider_result"]["error"] == "provider rejected work unit"
    assert result["graph_state"]["failed_nodes"] == ["step-1"]


def test_task_scheduler_runs_graph_outside_build_phase():
    graph = graph_from_plan({"steps": ["Coordinate sibling work"]}).to_artifact()
    dispatcher = RecordingDispatcher(
        DispatchResponse(
            success=True,
            outputs={"work_unit_result": "coordinated"},
            evidence={"child_task_executed": True},
            artifacts={"provider": "local"},
        )
    )

    result = TaskScheduler(dispatcher=dispatcher).run_ready(
        graph,
        phase="TaskTracking",
        max_nodes=1,
    ).to_artifact()

    assert result["phase"] == "TaskTracking"
    assert dispatcher.requests[0].phase == "TaskTracking"
    assert result["graph_state"]["completed_nodes"] == ["step-1"]


def test_graph_executor_can_execute_one_node_at_a_time():
    graph = graph_from_plan({"steps": ["A", "B", "C"]}).to_artifact()
    executor = TaskGraphExecutor()

    first = executor.execute_next(graph).to_artifact()
    assert [event["node_id"] for event in first["events"]] == ["step-1"]
    assert first["graph_state"]["completed_nodes"] == ["step-1"]

    second = executor.execute_some(first["graph_state"], max_nodes=1).to_artifact()
    assert [event["node_id"] for event in second["events"]] == ["step-2"]
    assert second["graph_state"]["completed_nodes"] == ["step-1", "step-2"]


def test_progress_graph_records_node_execution_metadata():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()

    progressed = progress_graph(graph, completed_node_id="step-1")
    completed = progressed["nodes"][0]

    assert completed["status"] == "completed"
    assert completed["attempts"] == 1
    assert completed["started_at"] is not None
    assert completed["completed_at"] is not None
    assert progressed["last_completed_node"] == "step-1"
    assert latest_completed_node(progressed)["id"] == "step-1"


def test_graph_executor_events_include_attempt_and_timestamps():
    graph = graph_from_plan({"steps": ["A"]}).to_artifact()

    result = TaskGraphExecutor().execute_next(graph).to_artifact()
    event = result["events"][0]

    assert event["attempt"] == 1
    assert event["started_at"] is not None
    assert event["finished_at"] is not None


def test_fail_and_retry_graph_node_tracks_failure_state():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()

    failed = fail_graph_node(graph, node_id="step-1", error="boom")
    failed_node = latest_failed_node(failed)

    assert failed_node["id"] == "step-1"
    assert failed_node["last_error"] == "boom"
    assert failed_node["attempts"] == 1
    assert next_retryable_failed_node(failed)["id"] == "step-1"

    retried = retry_graph_node(failed, node_id="step-1")
    assert retried["failed_nodes"] == []
    assert next_ready_node(retried)["id"] == "step-1"


def test_graph_executor_can_emit_failed_event():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()

    result = TaskGraphExecutor().execute_some(
        graph,
        max_nodes=1,
        fail_node_id="step-1",
        fail_error="configured failure",
    ).to_artifact()

    assert result["events"][0]["action"] == "failed"
    assert result["graph_state"]["failed_nodes"] == ["step-1"]


def test_waiting_human_node_is_not_ready():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()
    failed = fail_graph_node(graph, node_id="step-1", error="boom")

    waiting = require_human_for_graph_node(failed, node_id="step-1")

    assert waiting["nodes"][0]["status"] == "waiting_human"
    assert waiting["ready_nodes"] == []


def test_start_graph_node_marks_ready_node_running():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()

    running = start_graph_node(graph, node_id="step-1")

    assert running["nodes"][0]["status"] == "running"
    assert running["nodes"][0]["started_at"] is not None
    assert running["running_nodes"] == ["step-1"]
    assert running["ready_nodes"] == []
    assert graph_summary(running)["running"] == 1


def test_blocked_fanout_sibling_does_not_block_independent_ready_node():
    graph = {
        "nodes": [
            {"id": "root", "title": "Root", "status": "completed", "depends_on": []},
            {"id": "branch-a", "title": "Branch A", "status": "pending", "depends_on": ["root"]},
            {"id": "branch-b", "title": "Branch B", "status": "pending", "depends_on": ["root"]},
            {"id": "join", "title": "Join", "status": "pending", "depends_on": ["branch-a", "branch-b"]},
        ]
    }

    blocked = block_graph_node(graph, node_id="branch-a", reason="needs external input")

    assert blocked["blocked_nodes"] == ["branch-a"]
    assert blocked["ready_nodes"] == ["branch-b"]
    assert next_ready_node(blocked)["id"] == "branch-b"
    assert blocked["nodes"][1]["blocked_at"] is not None
    assert blocked["nodes"][1]["last_error"] == "needs external input"


def test_graph_summary_counts_scheduler_states():
    graph = {
        "nodes": [
            {"id": "pending", "status": "pending"},
            {"id": "completed", "status": "completed"},
            {"id": "running", "status": "running"},
            {"id": "blocked", "status": "blocked"},
            {"id": "failed", "status": "failed"},
            {"id": "human", "status": "waiting_human"},
        ]
    }

    summary = graph_summary(graph)

    assert summary["pending"] == 1
    assert summary["completed"] == 1
    assert summary["running"] == 1
    assert summary["blocked"] == 1
    assert summary["failed"] == 1
    assert summary["waiting_human"] == 1
    assert summary["total"] == 6


def test_supervision_manifest_includes_parent_child_links_and_block_reasons():
    graph = {
        "parent_task_id": "task-1",
        "nodes": [
            {
                "id": "step-1",
                "title": "Root",
                "status": "completed",
                "depends_on": [],
                "child_task_ids": ["step-2"],
            },
            {
                "id": "step-2",
                "title": "Child",
                "status": "blocked",
                "depends_on": ["step-1"],
                "last_error": "needs external input",
            },
        ],
    }

    annotated = annotate_graph_for_supervision(graph, parent_task_id="task-1")
    manifest = task_manifest_from_graph(annotated, parent_task_id="task-1")

    assert annotated["nodes"][0]["progress_state"] == "done"
    assert annotated["nodes"][1]["progress_state"] == "blocked"
    assert manifest[0]["parent_task_id"] == "task-1"
    assert manifest[0]["child_task_ids"] == ["step-2"]
    assert manifest[1]["needs_from"] == ["step-1"]
    assert manifest[1]["block_reason"] == "needs external input"
    assert supervision_summary(annotated)["done"] == 1
