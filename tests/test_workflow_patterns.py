"""Tests for dynamic workflow patterns — NodeType, inject_nodes, graph_from_workflow,
WorkflowPatternsPolicy, and TaskGraphExecutor pattern handlers."""

from src.task_graph import (
    NodeType,
    TaskNode,
    graph_from_plan,
    graph_from_workflow,
    inject_nodes,
    next_ready_node,
    progress_graph,
)
from src.runtime import TaskGraphExecutor, WorkflowPattern, WorkflowPatternsPolicy


# ---------------------------------------------------------------------------
# NodeType on TaskNode
# ---------------------------------------------------------------------------

def test_task_node_defaults_to_execute_type():
    node = TaskNode(id="n1", title="work")
    assert node.node_type == NodeType.EXECUTE


def test_task_node_stores_typed_node_type():
    node = TaskNode(id="n1", title="fan out", node_type=NodeType.FANOUT)
    assert node.node_type == NodeType.FANOUT


def test_task_node_artifact_includes_node_type_and_pattern_config():
    node = TaskNode(
        id="n1",
        title="judge",
        node_type=NodeType.JUDGE,
        pattern_config={"attempts": 4},
    )
    art = node.to_artifact()
    assert art["node_type"] == NodeType.JUDGE
    assert art["pattern_config"] == {"attempts": 4}
    assert art["injected_children"] == []


# ---------------------------------------------------------------------------
# graph_from_workflow
# ---------------------------------------------------------------------------

def test_graph_from_workflow_falls_back_to_sequential_without_nodes():
    g = graph_from_workflow({"steps": ["A", "B"]}).to_artifact()
    assert len(g["nodes"]) == 2
    assert g["ready_nodes"] == ["step-1"]


def test_graph_from_workflow_builds_typed_nodes():
    workflow = {
        "nodes": [
            {"id": "root", "title": "Start", "node_type": "fanout", "config": {"count": 3}},
            {"id": "b1", "title": "Branch 1", "depends_on": ["root"]},
            {"id": "b2", "title": "Branch 2", "depends_on": ["root"]},
            {"id": "b3", "title": "Branch 3", "depends_on": ["root"]},
            {"id": "merge", "title": "Synthesize", "node_type": "synthesize", "depends_on": ["b1", "b2", "b3"]},
        ]
    }
    g = graph_from_workflow(workflow).to_artifact()
    assert len(g["nodes"]) == 5
    assert g["ready_nodes"] == ["root"]

    node_map = {n["id"]: n for n in g["nodes"]}
    assert node_map["root"]["node_type"] == "fanout"
    assert node_map["merge"]["node_type"] == "synthesize"
    assert set(node_map["merge"]["depends_on"]) == {"b1", "b2", "b3"}


def test_graph_from_workflow_wires_child_task_ids():
    workflow = {
        "nodes": [
            {"id": "a", "title": "A"},
            {"id": "b", "title": "B", "depends_on": ["a"]},
        ]
    }
    nodes = graph_from_workflow(workflow).nodes
    a_node = next(n for n in nodes if n.id == "a")
    assert "b" in a_node.child_task_ids


# ---------------------------------------------------------------------------
# inject_nodes
# ---------------------------------------------------------------------------

def test_inject_nodes_adds_nodes_depending_on_parent():
    graph = graph_from_plan({"steps": ["Root"]}).to_artifact()
    graph = progress_graph(graph, completed_node_id="step-1")

    updated = inject_nodes(
        graph,
        parent_id="step-1",
        new_nodes=[
            {"id": "child-1", "title": "Child 1"},
            {"id": "child-2", "title": "Child 2"},
        ],
    )

    node_ids = [n["id"] for n in updated["nodes"]]
    assert "child-1" in node_ids
    assert "child-2" in node_ids

    for node in updated["nodes"]:
        if node["id"] in ("child-1", "child-2"):
            assert "step-1" in node["depends_on"]


def test_inject_nodes_updates_parent_injected_children():
    graph = graph_from_plan({"steps": ["Root"]}).to_artifact()
    graph = progress_graph(graph, completed_node_id="step-1")
    updated = inject_nodes(graph, "step-1", [{"id": "x", "title": "X"}])

    parent = next(n for n in updated["nodes"] if n["id"] == "step-1")
    assert "x" in parent.get("injected_children", [])


def test_inject_nodes_skips_duplicate_ids():
    graph = graph_from_plan({"steps": ["A", "B"]}).to_artifact()
    graph = progress_graph(graph, completed_node_id="step-1")

    updated = inject_nodes(graph, "step-1", [{"id": "step-2", "title": "Duplicate"}])
    count = sum(1 for n in updated["nodes"] if n["id"] == "step-2")
    assert count == 1  # not duplicated


def test_inject_nodes_does_not_override_explicit_depends_on():
    graph = graph_from_plan({"steps": ["A"]}).to_artifact()
    graph = progress_graph(graph, completed_node_id="step-1")

    updated = inject_nodes(
        graph,
        "step-1",
        [{"id": "child", "title": "C", "depends_on": ["step-1", "other"]}],
    )
    child = next(n for n in updated["nodes"] if n["id"] == "child")
    assert "step-1" in child["depends_on"]
    assert "other" in child["depends_on"]


def test_injected_children_become_ready_when_parent_completes():
    graph = graph_from_plan({"steps": ["Root"]}).to_artifact()
    # Complete root first
    graph = progress_graph(graph, completed_node_id="step-1")
    # Inject children after completion — they should be immediately ready
    updated = inject_nodes(
        graph,
        "step-1",
        [{"id": "c1", "title": "C1"}, {"id": "c2", "title": "C2"}],
    )
    ready = next_ready_node(updated)
    assert ready is not None
    assert ready["id"] in ("c1", "c2")


# ---------------------------------------------------------------------------
# TaskGraphExecutor — FANOUT pattern
# ---------------------------------------------------------------------------

def test_executor_fanout_node_injects_branches_and_synthesize():
    workflow = {
        "nodes": [
            {
                "id": "fanout",
                "title": "Explore options",
                "node_type": "fanout",
                "pattern_config": {"count": 3, "synthesize_title": "Merge"},
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor()

    result = executor.execute_next(graph)
    state = result.graph_state
    node_ids = {n["id"] for n in state["nodes"]}

    assert "fanout-branch-1" in node_ids
    assert "fanout-branch-2" in node_ids
    assert "fanout-branch-3" in node_ids
    assert "fanout-synthesize" in node_ids


def test_executor_fanout_synthesize_node_depends_on_all_branches():
    workflow = {
        "nodes": [
            {
                "id": "fanout",
                "title": "Fan",
                "node_type": "fanout",
                "pattern_config": {"count": 2},
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor()
    result = executor.execute_next(graph)

    synth = next(
        (n for n in result.graph_state["nodes"] if n["id"] == "fanout-synthesize"),
        None,
    )
    assert synth is not None
    assert "fanout-branch-1" in synth["depends_on"]
    assert "fanout-branch-2" in synth["depends_on"]


# ---------------------------------------------------------------------------
# TaskGraphExecutor — LOOP_GATE pattern
# ---------------------------------------------------------------------------

def test_executor_loop_gate_does_not_inject_when_condition_false():
    workflow = {
        "nodes": [
            {
                "id": "loop",
                "title": "Check",
                "node_type": "loop_gate",
                "pattern_config": {"max_iterations": 3, "condition_key": "new_findings"},
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor()
    result = executor.execute_next(graph)

    # No provider result → condition_key absent → condition false → no injection
    node_ids = {n["id"] for n in result.graph_state["nodes"]}
    assert "loop-iter-2" not in node_ids


def test_executor_loop_gate_injects_next_iteration_when_condition_true():
    from src.runtime.contracts import DispatchResponse

    class ConditionTrueDispatcher:
        def dispatch(self, request):
            return DispatchResponse(
                success=True,
                outputs={"new_findings": True},
            )

    workflow = {
        "nodes": [
            {
                "id": "loop",
                "title": "Scan",
                "node_type": "loop_gate",
                "pattern_config": {
                    "max_iterations": 5,
                    "condition_key": "new_findings",
                    "iteration": 1,
                },
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor(dispatcher=ConditionTrueDispatcher())
    result = executor.execute_next(graph)

    node_ids = {n["id"] for n in result.graph_state["nodes"]}
    assert "loop-iter-2" in node_ids


def test_executor_loop_gate_stops_at_max_iterations():
    from src.runtime.contracts import DispatchResponse

    class AlwaysTrueDispatcher:
        def dispatch(self, request):
            return DispatchResponse(success=True, outputs={"new_findings": True})

    workflow = {
        "nodes": [
            {
                "id": "loop",
                "title": "Scan",
                "node_type": "loop_gate",
                "pattern_config": {
                    "max_iterations": 1,
                    "condition_key": "new_findings",
                    "iteration": 1,
                },
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor(dispatcher=AlwaysTrueDispatcher())
    result = executor.execute_next(graph)

    node_ids = {n["id"] for n in result.graph_state["nodes"]}
    # iteration == max_iterations, so no new iteration injected
    assert "loop-iter-2" not in node_ids


# ---------------------------------------------------------------------------
# TaskGraphExecutor — JUDGE pattern
# ---------------------------------------------------------------------------

def test_executor_judge_node_injects_winner_node():
    workflow = {
        "nodes": [
            {
                "id": "judge",
                "title": "Compare",
                "node_type": "judge",
                "pattern_config": {"winner_title": "Apply best result"},
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    executor = TaskGraphExecutor()
    result = executor.execute_next(graph)

    node_ids = {n["id"] for n in result.graph_state["nodes"]}
    assert "judge-winner" in node_ids

    winner = next(n for n in result.graph_state["nodes"] if n["id"] == "judge-winner")
    assert "judge" in winner["depends_on"]


# ---------------------------------------------------------------------------
# WorkflowPatternsPolicy
# ---------------------------------------------------------------------------

def test_policy_parses_dict_of_patterns():
    section = {
        "patterns": {
            "fanout_and_synthesize": {"enabled": True, "max_branches": 3},
            "tournament": {"enabled": False},
            "loop_until_done": True,
        }
    }
    policy = WorkflowPatternsPolicy.from_policy_section(section)
    assert policy.is_enabled(WorkflowPattern.FANOUT_AND_SYNTHESIZE)
    assert not policy.is_enabled(WorkflowPattern.TOURNAMENT)
    assert policy.is_enabled(WorkflowPattern.LOOP_UNTIL_DONE)


def test_policy_parses_list_of_pattern_names():
    section = {"patterns": ["classify_and_act", "generate_and_filter"]}
    policy = WorkflowPatternsPolicy.from_policy_section(section)
    assert policy.is_enabled(WorkflowPattern.CLASSIFY_AND_ACT)
    assert policy.is_enabled(WorkflowPattern.GENERATE_AND_FILTER)
    assert not policy.is_enabled(WorkflowPattern.TOURNAMENT)


def test_policy_config_merges_defaults_with_overrides():
    section = {
        "patterns": {
            "tournament": {"enabled": True, "attempts": 6},
        }
    }
    policy = WorkflowPatternsPolicy.from_policy_section(section)
    cfg = policy.config_for(WorkflowPattern.TOURNAMENT)
    assert cfg["attempts"] == 6          # override
    assert cfg["judge_rounds"] == 2      # default preserved


def test_policy_empty_section_returns_no_enabled_patterns():
    policy = WorkflowPatternsPolicy.from_policy_section(None)
    assert not policy.is_enabled(WorkflowPattern.FANOUT_AND_SYNTHESIZE)


def test_policy_to_artifact_is_serialisable():
    section = {"patterns": {"loop_until_done": {"enabled": True, "max_iterations": 10}}}
    policy = WorkflowPatternsPolicy.from_policy_section(section)
    art = policy.to_artifact()
    assert "loop_until_done" in art["enabled_patterns"]
    assert art["pattern_configs"]["loop_until_done"]["max_iterations"] == 10


# ---------------------------------------------------------------------------
# Backward-compatibility: existing execute_all still works on plain graphs
# ---------------------------------------------------------------------------

def test_execute_all_plain_graph_unaffected():
    graph = graph_from_plan({"steps": ["A", "B", "C"]}).to_artifact()
    result = TaskGraphExecutor().execute_all(graph)
    completed = [n for n in result.graph_state["nodes"] if n["status"] == "completed"]
    assert len(completed) == 3
