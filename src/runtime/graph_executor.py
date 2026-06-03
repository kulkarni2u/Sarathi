"""Task graph execution helpers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime

try:
    from src.runtime.context import ContextCompiler
    from src.runtime.contracts import DispatchRequest
    from src.runtime.output_index import build_artifact_index, normalize_agent_output
    from src.task_graph import (
        NodeType,
        fail_graph_node,
        inject_nodes,
        next_ready_node,
        progress_graph,
        retry_graph_node,
    )
except ImportError:
    from runtime.context import ContextCompiler
    from runtime.contracts import DispatchRequest
    from runtime.output_index import build_artifact_index, normalize_agent_output
    from task_graph import (
        NodeType,
        fail_graph_node,
        inject_nodes,
        next_ready_node,
        progress_graph,
        retry_graph_node,
    )


_GRAPH_STATE_KEYS = (
    "ready_nodes",
    "completed_nodes",
    "failed_nodes",
    "blocked_nodes",
    "running_nodes",
    "waiting_human_nodes",
)


def _copy_graph_state(graph: dict) -> dict:
    """Copy graph state while preserving scheduler indexes."""
    current = deepcopy(graph)
    current["nodes"] = [dict(node) for node in graph.get("nodes", [])]
    for key in _GRAPH_STATE_KEYS:
        current[key] = list(graph.get(key, []))
    return current


@dataclass
class GraphExecutionEvent:
    """One execution step in the task graph."""

    node_id: str
    title: str
    action: str
    started_at: str | None = None
    finished_at: str | None = None
    attempt: int | None = None
    provider_result: dict | None = None

    def to_artifact(self) -> dict:
        artifact = {
            "node_id": self.node_id,
            "title": self.title,
            "action": self.action,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempt": self.attempt,
        }
        if self.provider_result is not None:
            artifact["provider_result"] = self.provider_result
        return artifact


@dataclass
class GraphExecutionResult:
    """Result of executing a task graph."""

    graph_state: dict
    events: list[GraphExecutionEvent] = field(default_factory=list)

    def to_artifact(self) -> dict:
        return {
            "graph_state": self.graph_state,
            "events": [event.to_artifact() for event in self.events],
        }


class TaskGraphExecutor:
    """Executes a simple dependency graph in ready-node order."""

    def __init__(self, dispatcher=None, dispatch_phase: str = "Build"):
        self.dispatcher = dispatcher
        self.dispatch_phase = dispatch_phase
        self.context_compiler = ContextCompiler()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _annotate_node_result(graph: dict, node_id: str, provider_result: dict | None) -> dict:
        if provider_result is None:
            return graph
        for node in graph.get("nodes", []):
            if node.get("id") != node_id:
                continue
            node["last_provider_result"] = provider_result
            artifact_index = provider_result.get("artifact_index")
            if isinstance(artifact_index, dict):
                node["artifact_index"] = dict(artifact_index)
            agent_output = provider_result.get("agent_output")
            if isinstance(agent_output, dict):
                node["agent_output"] = dict(agent_output)
            summary = provider_result.get("context_pack_summary")
            if isinstance(summary, dict):
                node["context_pack_summary"] = dict(summary)
            context_pack = provider_result.get("context_pack")
            if isinstance(context_pack, dict):
                node["context_pack"] = dict(context_pack)
            break
        return graph

    def execute_next(self, graph: dict, fail_node_id: str | None = None, fail_error: str | None = None) -> GraphExecutionResult:
        """Execute the next ready node only."""
        current = _copy_graph_state(graph)
        ready = next_ready_node(current)
        if ready is None:
            return GraphExecutionResult(graph_state=current, events=[])

        provider_result = self._dispatch_node(ready, graph=current)
        if provider_result is not None and not provider_result.get("success", False):
            updated = fail_graph_node(
                current,
                node_id=ready["id"],
                error=provider_result.get("error") or "Provider-backed node execution failed",
            )
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
            updated = self._annotate_node_result(updated, ready["id"], provider_result)
            event = GraphExecutionEvent(
                node_id=ready["id"],
                title=ready.get("title", ready["id"]),
                action="failed",
                started_at=updated_node.get("started_at"),
                finished_at=updated_node.get("failed_at"),
                attempt=updated_node.get("attempts"),
                provider_result=provider_result,
            )
        elif fail_node_id is not None and ready["id"] == fail_node_id:
            updated = fail_graph_node(current, node_id=ready["id"], error=fail_error or "Node execution failed")
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
            updated = self._annotate_node_result(updated, ready["id"], provider_result)
            event = GraphExecutionEvent(
                node_id=ready["id"],
                title=ready.get("title", ready["id"]),
                action="failed",
                started_at=updated_node.get("started_at"),
                finished_at=updated_node.get("failed_at"),
                attempt=updated_node.get("attempts"),
                provider_result=provider_result,
            )
        else:
            updated = progress_graph(current, completed_node_id=ready["id"])
            updated = self._post_execute_inject(ready, updated, provider_result)
            finished_at = self._timestamp()
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
            updated = self._annotate_node_result(updated, ready["id"], provider_result)
            event = GraphExecutionEvent(
                node_id=ready["id"],
                title=ready.get("title", ready["id"]),
                action="completed",
                started_at=updated_node.get("started_at"),
                finished_at=finished_at,
                attempt=updated_node.get("attempts"),
                provider_result=provider_result,
            )
        return GraphExecutionResult(graph_state=updated, events=[event])

    def execute_some(
        self,
        graph: dict,
        max_nodes: int | None = None,
        fail_node_id: str | None = None,
        fail_error: str | None = None,
    ) -> GraphExecutionResult:
        """Execute up to `max_nodes` ready nodes in dependency order."""
        if max_nodes is None:
            return self.execute_all(graph, fail_node_id=fail_node_id, fail_error=fail_error)
        if max_nodes <= 0:
            current = _copy_graph_state(graph)
            return GraphExecutionResult(graph_state=current, events=[])

        current = _copy_graph_state(graph)
        events: list[GraphExecutionEvent] = []
        executed = 0

        ready = next_ready_node(current)
        while ready is not None and executed < max_nodes:
            provider_result = self._dispatch_node(ready, graph=current)
            if provider_result is not None and not provider_result.get("success", False):
                updated = fail_graph_node(
                    current,
                    node_id=ready["id"],
                    error=provider_result.get("error") or "Provider-backed node execution failed",
                )
                updated_node = next(
                    (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                    {},
                )
                updated = self._annotate_node_result(updated, ready["id"], provider_result)
                events.append(
                    GraphExecutionEvent(
                        node_id=ready["id"],
                        title=ready.get("title", ready["id"]),
                        action="failed",
                        started_at=updated_node.get("started_at"),
                        finished_at=updated_node.get("failed_at"),
                        attempt=updated_node.get("attempts"),
                        provider_result=provider_result,
                    )
                )
                current = updated
                break

            if fail_node_id is not None and ready["id"] == fail_node_id:
                updated = fail_graph_node(current, node_id=ready["id"], error=fail_error or "Node execution failed")
                updated_node = next(
                    (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                    {},
                )
                updated = self._annotate_node_result(updated, ready["id"], provider_result)
                events.append(
                    GraphExecutionEvent(
                        node_id=ready["id"],
                        title=ready.get("title", ready["id"]),
                        action="failed",
                        started_at=updated_node.get("started_at"),
                        finished_at=updated_node.get("failed_at"),
                        attempt=updated_node.get("attempts"),
                        provider_result=provider_result,
                    )
                )
                current = updated
                break

            updated = progress_graph(current, completed_node_id=ready["id"])
            updated = self._post_execute_inject(ready, updated, provider_result)
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
            updated = self._annotate_node_result(updated, ready["id"], provider_result)
            events.append(
                GraphExecutionEvent(
                    node_id=ready["id"],
                    title=ready.get("title", ready["id"]),
                    action="completed",
                    started_at=updated_node.get("started_at"),
                    finished_at=updated_node.get("completed_at"),
                    attempt=updated_node.get("attempts"),
                    provider_result=provider_result,
                )
            )
            current = updated
            executed += 1
            ready = next_ready_node(current)

        return GraphExecutionResult(graph_state=current, events=events)

    def execute_all(
        self,
        graph: dict,
        fail_node_id: str | None = None,
        fail_error: str | None = None,
    ) -> GraphExecutionResult:
        current = _copy_graph_state(graph)
        events: list[GraphExecutionEvent] = []

        ready = next_ready_node(current)
        while ready is not None:
            provider_result = self._dispatch_node(ready, graph=current)
            if provider_result is not None and not provider_result.get("success", False):
                updated = fail_graph_node(
                    current,
                    node_id=ready["id"],
                    error=provider_result.get("error") or "Provider-backed node execution failed",
                )
                updated_node = next(
                    (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                    {},
                )
                updated = self._annotate_node_result(updated, ready["id"], provider_result)
                events.append(
                    GraphExecutionEvent(
                        node_id=ready["id"],
                        title=ready.get("title", ready["id"]),
                        action="failed",
                        started_at=updated_node.get("started_at"),
                        finished_at=updated_node.get("failed_at"),
                        attempt=updated_node.get("attempts"),
                        provider_result=provider_result,
                    )
                )
                current = updated
                break
            if fail_node_id is not None and ready["id"] == fail_node_id:
                updated = fail_graph_node(current, node_id=ready["id"], error=fail_error or "Node execution failed")
                updated_node = next(
                    (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                    {},
                )
                updated = self._annotate_node_result(updated, ready["id"], provider_result)
                events.append(
                    GraphExecutionEvent(
                        node_id=ready["id"],
                        title=ready.get("title", ready["id"]),
                        action="failed",
                        started_at=updated_node.get("started_at"),
                        finished_at=updated_node.get("failed_at"),
                        attempt=updated_node.get("attempts"),
                        provider_result=provider_result,
                    )
                )
                current = updated
                break
            updated = progress_graph(current, completed_node_id=ready["id"])
            updated = self._post_execute_inject(ready, updated, provider_result)
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
            updated = self._annotate_node_result(updated, ready["id"], provider_result)
            events.append(
                GraphExecutionEvent(
                    node_id=ready["id"],
                    title=ready.get("title", ready["id"]),
                    action="completed",
                    started_at=updated_node.get("started_at"),
                    finished_at=updated_node.get("completed_at"),
                    attempt=updated_node.get("attempts"),
                    provider_result=provider_result,
                )
            )
            current = updated
            ready = next_ready_node(current)

        return GraphExecutionResult(graph_state=current, events=events)

    def retry_failed_node(self, graph: dict, node_id: str) -> dict:
        """Reset a failed node so it can be executed again."""
        return retry_graph_node(graph, node_id=node_id)

    def inject_nodes(self, graph: dict, parent_id: str, new_nodes: list[dict]) -> dict:
        """Inject new nodes into a live graph depending on parent_id."""
        return inject_nodes(graph, parent_id=parent_id, new_nodes=new_nodes)

    # ------------------------------------------------------------------
    # Pattern-specific post-execution injection
    # ------------------------------------------------------------------

    def _post_execute_inject(
        self, node: dict, graph: dict, provider_result: dict | None
    ) -> dict:
        """After a node completes, inject follow-on nodes based on its node_type."""
        node_type = node.get("node_type", NodeType.EXECUTE)
        if node_type == NodeType.FANOUT:
            return self._inject_fanout_children(node, graph)
        if node_type == NodeType.JUDGE:
            return self._inject_judge_result(node, graph, provider_result)
        if node_type == NodeType.LOOP_GATE:
            return self._inject_loop_iteration(node, graph, provider_result)
        if node_type == NodeType.CLASSIFY:
            return self._inject_classified_branch(node, graph, provider_result)
        return graph

    def _inject_fanout_children(self, node: dict, graph: dict) -> dict:
        """FANOUT: spawn N parallel EXECUTE children + one SYNTHESIZE fan-in node."""
        cfg = node.get("pattern_config", {})
        count = int(cfg.get("count", cfg.get("max_branches", 2)))
        title_template = cfg.get("title_template", "Branch {i}: " + node.get("title", "work"))
        synthesize_title = cfg.get("synthesize_title", f"Synthesize: {node.get('title', 'results')}")
        parent_id = node["id"]

        branch_ids = [f"{parent_id}-branch-{i}" for i in range(1, count + 1)]
        synthesize_id = f"{parent_id}-synthesize"

        children = [
            {
                "id": bid,
                "title": title_template.replace("{i}", str(i)),
                "node_type": NodeType.EXECUTE,
                "depends_on": [parent_id],
                "pattern_config": {},
            }
            for i, bid in enumerate(branch_ids, start=1)
        ]
        children.append(
            {
                "id": synthesize_id,
                "title": synthesize_title,
                "node_type": NodeType.SYNTHESIZE,
                "depends_on": branch_ids,
                "pattern_config": {"source_ids": branch_ids},
            }
        )
        return inject_nodes(graph, parent_id=parent_id, new_nodes=children)

    def _inject_judge_result(
        self, node: dict, graph: dict, provider_result: dict | None
    ) -> dict:
        """JUDGE: inject a winner-propagation EXECUTE node after judgment."""
        cfg = node.get("pattern_config", {})
        winner_title = cfg.get("winner_title", f"Apply winner: {node.get('title', 'result')}")
        winner_id = f"{node['id']}-winner"
        winner_node = {
            "id": winner_id,
            "title": winner_title,
            "node_type": NodeType.EXECUTE,
            "depends_on": [node["id"]],
            "pattern_config": {
                "winner_from": node["id"],
                "judge_output": (provider_result or {}).get("outputs", {}),
            },
        }
        return inject_nodes(graph, parent_id=node["id"], new_nodes=[winner_node])

    def _inject_loop_iteration(
        self, node: dict, graph: dict, provider_result: dict | None
    ) -> dict:
        """LOOP_GATE: inject next iteration node if condition is met, else done."""
        cfg = node.get("pattern_config", {})
        max_iterations = int(cfg.get("max_iterations", 5))
        iteration = int(cfg.get("iteration", 1))
        condition_key = cfg.get("condition_key", "new_findings")

        outputs = (provider_result or {}).get("outputs", {})
        condition_met = bool(outputs.get(condition_key, False))
        already_done = iteration >= max_iterations

        if condition_met and not already_done:
            next_id = f"{node['id']}-iter-{iteration + 1}"
            next_node = {
                "id": next_id,
                "title": f"{cfg.get('loop_title', node.get('title', 'Loop'))} (iteration {iteration + 1})",
                "node_type": NodeType.LOOP_GATE,
                "depends_on": [node["id"]],
                "pattern_config": {
                    **cfg,
                    "iteration": iteration + 1,
                },
            }
            return inject_nodes(graph, parent_id=node["id"], new_nodes=[next_node])
        return graph

    def _inject_classified_branch(
        self, node: dict, graph: dict, provider_result: dict | None
    ) -> dict:
        """CLASSIFY: activate the branch matching the classification output."""
        cfg = node.get("pattern_config", {})
        branches = cfg.get("branches", {})
        outputs = (provider_result or {}).get("outputs", {})
        classification = str(outputs.get("classification", outputs.get("route", "")))

        branch_spec = branches.get(classification)
        if not branch_spec:
            return graph

        branch_id = f"{node['id']}-branch-{classification}"
        branch_node = {
            "id": branch_id,
            "title": branch_spec if isinstance(branch_spec, str) else branch_spec.get("title", classification),
            "node_type": NodeType.EXECUTE,
            "depends_on": [node["id"]],
            "pattern_config": {"classification": classification},
        }
        return inject_nodes(graph, parent_id=node["id"], new_nodes=[branch_node])

    def _dispatch_node(self, node: dict, *, graph: dict | None = None) -> dict | None:
        """Dispatch a ready node as a child work unit when a dispatcher is configured."""
        if self.dispatcher is None:
            return None
        context_pack = self.context_compiler.compile_graph_node_context(
            node=node,
            graph=graph,
            phase=self.dispatch_phase,
            available_tools=["task_graph", "workspace_files", "git_diff", "test_results"],
        )
        context_pack_artifact = context_pack.to_artifact()
        request = DispatchRequest(
            mode="execute",
            task_id=str(node.get("id", "unknown")),
            phase=self.dispatch_phase,
            prompt=str(node.get("title", node.get("id", "Execute graph node"))),
            inputs={
                "node": dict(node),
                "task_description": str(node.get("title", "")),
                "context_pack": context_pack_artifact,
            },
            expected_outputs=["implementation_plan", "work_unit_result", "evidence"],
            constraints={"purpose": "child_task_execution"},
            context_pack=context_pack_artifact,
            token_budget=context_pack.agent_input.token_budget,
            retry_budget=0,
        )
        try:
            response = self.dispatcher.dispatch(request)
        except Exception as exc:
            return {
                "dispatched": True,
                "success": False,
                "error": f"Dispatcher child-task execution failed: {exc}",
            }
        artifact_index = build_artifact_index(response)
        agent_output = normalize_agent_output(
            response,
            phase=self.dispatch_phase,
            purpose="child_task_execution",
        ).to_artifact()
        result = {
            "dispatched": True,
            "success": response.success,
            "outputs": response.outputs,
            "evidence": response.evidence,
            "artifacts": response.artifacts,
            "agent_output": agent_output,
            "artifact_index": artifact_index,
            "context_pack": context_pack_artifact,
            "context_pack_summary": {
                "objective": context_pack.agent_input.objective,
                "token_budget": context_pack.agent_input.token_budget,
                "estimated_tokens": context_pack_artifact["compilation"]["estimated_tokens"],
                "trimmed_sections": context_pack_artifact["compilation"]["trimmed_sections"],
            },
        }
        if response.usage:
            result["usage"] = response.usage.to_artifact()
        if response.error:
            result["error"] = response.error
        if response.raw_transcript_ref:
            result["raw_transcript_ref"] = response.raw_transcript_ref
        return result
