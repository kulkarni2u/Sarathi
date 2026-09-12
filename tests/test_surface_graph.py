import pytest
from src import task_graph as graph

@pytest.mark.parametrize("transition,args,status", [
    (graph.start_graph_node, (), "pending"),
    (graph.progress_graph, (), "running"),
    (graph.fail_graph_node, ("failure",), "running"),
    (graph.block_graph_node, ("reason",), "running"),
    (graph.retry_graph_node, (), "failed"),
    (graph.require_human_for_graph_node, (), "failed"),
])
def test_transition_preserves_graph_identity_and_warnings(transition, args, status):
    original = {"task_id": "task-123", "_ncp_warnings": ["store unavailable"],
                "custom": {"owner": "workspace-a"},
                "nodes": [{"id": "node-1", "status": status, "depends_on": []}]}
    result = transition(original, "node-1", *args)
    assert result["task_id"] == "task-123"
    assert result["_ncp_warnings"] == ["store unavailable"]
    assert result["custom"] == {"owner": "workspace-a"}
    assert original["nodes"][0]["status"] == status
