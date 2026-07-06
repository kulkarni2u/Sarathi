"""Tests for dynamic workflow patterns — NodeType, inject_nodes, graph_from_workflow,
WorkflowPatternsPolicy, and TaskGraphExecutor pattern handlers."""

import subprocess
from pathlib import Path

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
# "Declare before dispatch": FANOUT/JUDGE child dispatch carries harness_id
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    return path


def test_executor_dispatches_execute_node_with_worktree_workspace_constraint(tmp_path):
    from src.harness import HarnessConfig
    from src.runtime.contracts import DispatchResponse

    repo = _init_repo(tmp_path / "repo")

    class RecordingDispatcher:
        def __init__(self):
            self.requests = []
            self.workspace_existed_during_dispatch = []

        def dispatch(self, request):
            self.requests.append(request)
            workspace_dir = request.constraints.get("workspace_dir")
            self.workspace_existed_during_dispatch.append(
                workspace_dir is not None and Path(workspace_dir).exists()
            )
            return DispatchResponse(success=True, outputs={})

    workflow = {
        "nodes": [
            {
                "id": "node-a",
                "title": "Implement branch A",
                "node_type": "execute",
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    dispatcher = RecordingDispatcher()
    harness = HarnessConfig(
        harness_id="h-worktree-parent",
        task_id="task-worktree",
        isolation_mode="worktree",
    )
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        harness_config=harness,
        isolation_repo_root=repo,
    )

    executor.execute_all(graph)

    assert dispatcher.requests
    request = dispatcher.requests[0]
    workspace_dir = Path(request.constraints["workspace_dir"])
    assert request.constraints["isolation_mode"] == "worktree"
    assert "_sarathi_workspace_dir" not in request.inputs["node"]
    assert workspace_dir == repo / ".sarathi" / "worktrees" / "task-worktree" / "node-a"
    assert dispatcher.workspace_existed_during_dispatch == [True]
    assert not workspace_dir.exists()


def test_execute_next_uses_worktree_isolation_and_cleans_up(tmp_path):
    from src.harness import HarnessConfig
    from src.runtime.contracts import DispatchResponse

    repo = _init_repo(tmp_path / "repo")

    class RecordingDispatcher:
        def __init__(self):
            self.requests = []

        def dispatch(self, request):
            self.requests.append(request)
            assert Path(request.constraints["workspace_dir"]).exists()
            return DispatchResponse(success=True, outputs={})

    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "node-a",
                    "title": "Implement branch A",
                    "node_type": "execute",
                }
            ]
        }
    ).to_artifact()
    dispatcher = RecordingDispatcher()
    harness = HarnessConfig(
        harness_id="h-worktree-next",
        task_id="task-worktree-next",
        isolation_mode="worktree",
    )
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        harness_config=harness,
        isolation_repo_root=repo,
    )

    executor.execute_next(graph)

    workspace_dir = Path(dispatcher.requests[0].constraints["workspace_dir"])
    assert workspace_dir == repo / ".sarathi" / "worktrees" / "task-worktree-next" / "node-a"
    assert not workspace_dir.exists()


def test_worktree_is_cleaned_up_when_dispatcher_raises(tmp_path):
    from src.harness import HarnessConfig

    repo = _init_repo(tmp_path / "repo")
    seen_workspace_dirs = []

    class FailingDispatcher:
        def dispatch(self, request):
            workspace_dir = Path(request.constraints["workspace_dir"])
            seen_workspace_dirs.append(workspace_dir)
            assert workspace_dir.exists()
            raise RuntimeError("boom")

    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "node-a",
                    "title": "Implement branch A",
                    "node_type": "execute",
                }
            ]
        }
    ).to_artifact()
    harness = HarnessConfig(
        harness_id="h-worktree-failure",
        task_id="task-worktree-failure",
        isolation_mode="worktree",
    )
    executor = TaskGraphExecutor(
        dispatcher=FailingDispatcher(),
        harness_config=harness,
        isolation_repo_root=repo,
    )

    result = executor.execute_all(graph)

    assert result.graph_state["failed_nodes"] == ["node-a"]
    assert seen_workspace_dirs
    assert not seen_workspace_dirs[0].exists()


def test_manual_worktree_cleanup_retains_workspace_and_records_metadata(tmp_path):
    from src.harness import HarnessConfig
    from src.runtime.contracts import DispatchResponse
    from src.runtime.isolation import GitWorktreeIsolation

    repo = _init_repo(tmp_path / "repo")

    class RecordingDispatcher:
        def dispatch(self, request):
            workspace_dir = Path(request.constraints["workspace_dir"])
            assert workspace_dir.exists()
            return DispatchResponse(
                success=True,
                outputs={"summary": "candidate complete"},
                evidence={},
                artifacts={"workspace_seen": str(workspace_dir)},
            )

    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "node-a",
                    "title": "Implement branch A",
                    "node_type": "execute",
                }
            ]
        }
    ).to_artifact()
    harness = HarnessConfig(
        harness_id="h-worktree-retain",
        task_id="task-worktree-retain",
        isolation_mode="worktree",
        isolation_cleanup="manual",
    )
    executor = TaskGraphExecutor(
        dispatcher=RecordingDispatcher(),
        harness_config=harness,
        isolation_repo_root=repo,
    )

    result = executor.execute_all(graph)

    workspace_dir = repo / ".sarathi" / "worktrees" / "task-worktree-retain" / "node-a"
    assert workspace_dir.exists()
    node = next(node for node in result.graph_state["nodes"] if node["id"] == "node-a")
    assert node["isolation"]["mode"] == "worktree"
    assert node["isolation"]["cleanup"] == "manual"
    assert node["isolation"]["workspace_dir"] == str(workspace_dir)
    provider_result = node["last_provider_result"]
    assert provider_result["isolation"]["workspace_dir"] == str(workspace_dir)
    assert provider_result["artifacts"]["isolation"]["workspace_dir"] == str(workspace_dir)
    GitWorktreeIsolation(repo).cleanup_task_worktrees("task-worktree-retain")


def test_manual_worktree_cleanup_records_metadata_when_dispatcher_raises(tmp_path):
    from src.harness import HarnessConfig
    from src.runtime.isolation import GitWorktreeIsolation

    repo = _init_repo(tmp_path / "repo")

    class FailingDispatcher:
        def dispatch(self, request):
            workspace_dir = Path(request.constraints["workspace_dir"])
            assert workspace_dir.exists()
            raise RuntimeError("boom")

    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "node-a",
                    "title": "Implement branch A",
                    "node_type": "execute",
                }
            ]
        }
    ).to_artifact()
    harness = HarnessConfig(
        harness_id="h-worktree-retain-failure",
        task_id="task-worktree-retain-failure",
        isolation_mode="worktree",
        isolation_cleanup="manual",
    )
    executor = TaskGraphExecutor(
        dispatcher=FailingDispatcher(),
        harness_config=harness,
        isolation_repo_root=repo,
    )

    result = executor.execute_all(graph)

    workspace_dir = repo / ".sarathi" / "worktrees" / "task-worktree-retain-failure" / "node-a"
    assert workspace_dir.exists()
    node = next(node for node in result.graph_state["nodes"] if node["id"] == "node-a")
    assert result.graph_state["failed_nodes"] == ["node-a"]
    assert node["isolation"]["cleanup"] == "manual"
    assert node["isolation"]["workspace_dir"] == str(workspace_dir)
    provider_result = node["last_provider_result"]
    assert provider_result["success"] is False
    assert provider_result["isolation"]["workspace_dir"] == str(workspace_dir)
    assert provider_result["artifacts"]["isolation"]["workspace_dir"] == str(workspace_dir)
    GitWorktreeIsolation(repo).cleanup_task_worktrees("task-worktree-retain-failure")


def test_apply_judge_winner_worktree_requires_explicit_approval(tmp_path):
    from src.runtime.isolation import GitWorktreeIsolation

    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    winner_worktree = isolation.create_worktree(task_id="task-winner", node_id="candidate-a")
    (winner_worktree / "winner.txt").write_text("winner\n", encoding="utf-8")
    graph = {
        "nodes": [
            {
                "id": "candidate-a",
                "isolation": {"mode": "worktree", "workspace_dir": str(winner_worktree)},
            },
            {
                "id": "judge",
                "node_type": "judge",
                "last_provider_result": {"outputs": {"winner": "candidate-a"}},
            },
        ]
    }
    executor = TaskGraphExecutor(isolation_repo_root=repo)

    result = executor.apply_judge_winner_worktree(
        graph,
        judge_node_id="judge",
        approved=False,
    )

    assert result["applied"] is False
    assert result["approval_required"] is True
    assert result["winner_node_id"] == "candidate-a"
    assert not (repo / "winner.txt").exists()
    isolation.cleanup_task_worktrees("task-winner")


def test_apply_judge_winner_worktree_applies_approved_winner(tmp_path):
    from src.runtime.isolation import GitWorktreeIsolation

    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    loser_worktree = isolation.create_worktree(task_id="task-winner", node_id="candidate-b")
    winner_worktree = isolation.create_worktree(task_id="task-winner", node_id="candidate-a")
    (winner_worktree / "winner.txt").write_text("winner\n", encoding="utf-8")
    (loser_worktree / "loser.txt").write_text("loser\n", encoding="utf-8")
    graph = {
        "nodes": [
            {
                "id": "candidate-a",
                "isolation": {"mode": "worktree", "workspace_dir": str(winner_worktree)},
            },
            {
                "id": "candidate-b",
                "isolation": {"mode": "worktree", "workspace_dir": str(loser_worktree)},
            },
            {
                "id": "judge",
                "node_type": "judge",
                "last_provider_result": {"outputs": {"winner": "candidate-a"}},
            },
        ]
    }
    executor = TaskGraphExecutor(isolation_repo_root=repo)

    result = executor.apply_judge_winner_worktree(
        graph,
        judge_node_id="judge",
        approved=True,
    )

    assert result["applied"] is True
    assert result["files_changed"] == ["winner.txt"]
    assert result["winner_node_id"] == "candidate-a"
    assert (repo / "winner.txt").read_text(encoding="utf-8") == "winner\n"
    assert not (repo / "loser.txt").exists()
    assert not winner_worktree.exists()
    assert not loser_worktree.exists()
    assert "isolation_applications" not in graph
    assert "isolation_apply" not in next(node for node in graph["nodes"] if node["id"] == "candidate-a")
    result_graph = result["graph_state"]
    assert result_graph["isolation_applications"][0]["files_changed"] == ["winner.txt"]
    winner_node = next(node for node in result_graph["nodes"] if node["id"] == "candidate-a")
    assert winner_node["isolation_apply"]["files_changed"] == ["winner.txt"]


def test_apply_judge_winner_worktree_skips_without_winner_output(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    graph = {
        "nodes": [
            {
                "id": "judge",
                "node_type": "judge",
                "last_provider_result": {"outputs": {}},
            }
        ]
    }
    executor = TaskGraphExecutor(isolation_repo_root=repo)

    result = executor.apply_judge_winner_worktree(
        graph,
        judge_node_id="judge",
        approved=True,
    )

    assert result == {
        "applied": False,
        "judge_node_id": "judge",
        "reason": "no_winner",
    }


def test_apply_judge_winner_worktree_skips_without_isolation_metadata(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    graph = {
        "nodes": [
            {"id": "candidate-a"},
            {
                "id": "judge",
                "node_type": "judge",
                "last_provider_result": {"outputs": {"winner": "candidate-a"}},
            },
        ]
    }
    executor = TaskGraphExecutor(isolation_repo_root=repo)

    result = executor.apply_judge_winner_worktree(
        graph,
        judge_node_id="judge",
        approved=True,
    )

    assert result == {
        "applied": False,
        "judge_node_id": "judge",
        "winner_node_id": "candidate-a",
        "reason": "no_worktree_isolation",
    }


def test_apply_judge_winner_worktree_skips_when_winner_node_missing(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    graph = {
        "nodes": [
            {
                "id": "judge",
                "node_type": "judge",
                "last_provider_result": {"outputs": {"winner": "candidate-a"}},
            },
        ]
    }
    executor = TaskGraphExecutor(isolation_repo_root=repo)

    result = executor.apply_judge_winner_worktree(
        graph,
        judge_node_id="judge",
        approved=True,
    )

    assert result == {
        "applied": False,
        "judge_node_id": "judge",
        "winner_node_id": "candidate-a",
        "reason": "winner_not_found",
    }


def test_fanout_branch_and_synthesize_dispatch_carry_harness_id():
    """Every node FANOUT spawns — parallel branches and the synthesize
    fan-in — must dispatch under the same harness as the parent task, not
    with no declared context/permission/budget contract at all."""
    from src.harness import HarnessConfig
    from src.runtime.contracts import DispatchResponse

    class RecordingDispatcher:
        def __init__(self):
            self.requests = []

        def dispatch(self, request):
            self.requests.append(request)
            return DispatchResponse(success=True, outputs={})

    workflow = {
        "nodes": [
            {
                "id": "fanout",
                "title": "Explore options",
                "node_type": "fanout",
                "pattern_config": {"count": 2},
            }
        ]
    }
    graph = graph_from_workflow(workflow).to_artifact()
    dispatcher = RecordingDispatcher()
    harness = HarnessConfig(harness_id="h-fanout-parent")
    executor = TaskGraphExecutor(dispatcher=dispatcher, harness_config=harness)

    result = executor.execute_all(graph)

    dispatched_ids = {req.task_id for req in dispatcher.requests}
    assert {"fanout", "fanout-branch-1", "fanout-branch-2", "fanout-synthesize"} <= dispatched_ids
    assert dispatcher.requests, "expected fanout to dispatch nodes"
    assert all(req.harness_id == "h-fanout-parent" for req in dispatcher.requests)
    assert result.graph_state["completed_nodes"]


def test_judge_and_winner_dispatch_carry_harness_id():
    """The JUDGE node and the winner-propagation node it injects must both
    dispatch with the parent harness_id."""
    from src.harness import HarnessConfig
    from src.runtime.contracts import DispatchResponse

    class RecordingDispatcher:
        def __init__(self):
            self.requests = []

        def dispatch(self, request):
            self.requests.append(request)
            return DispatchResponse(success=True, outputs={})

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
    dispatcher = RecordingDispatcher()
    harness = HarnessConfig(harness_id="h-judge-parent")
    executor = TaskGraphExecutor(dispatcher=dispatcher, harness_config=harness)

    executor.execute_all(graph)

    dispatched_ids = {req.task_id for req in dispatcher.requests}
    assert {"judge", "judge-winner"} <= dispatched_ids
    assert all(req.harness_id == "h-judge-parent" for req in dispatcher.requests)


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
