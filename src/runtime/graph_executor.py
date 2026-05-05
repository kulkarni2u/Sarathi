"""Task graph execution helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

try:
    from src.runtime.contracts import DispatchRequest
    from src.task_graph import fail_graph_node, next_ready_node, progress_graph, retry_graph_node
except ImportError:
    from runtime.contracts import DispatchRequest
    from task_graph import fail_graph_node, next_ready_node, progress_graph, retry_graph_node


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
    current = {"nodes": [dict(node) for node in graph.get("nodes", [])]}
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

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def execute_next(self, graph: dict, fail_node_id: str | None = None, fail_error: str | None = None) -> GraphExecutionResult:
        """Execute the next ready node only."""
        current = _copy_graph_state(graph)
        ready = next_ready_node(current)
        if ready is None:
            return GraphExecutionResult(graph_state=current, events=[])

        provider_result = self._dispatch_node(ready)
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
            finished_at = self._timestamp()
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
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
            provider_result = self._dispatch_node(ready)
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
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
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
            provider_result = self._dispatch_node(ready)
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
            updated_node = next(
                (node for node in updated.get("nodes", []) if node.get("id") == ready["id"]),
                {},
            )
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

    def _dispatch_node(self, node: dict) -> dict | None:
        """Dispatch a ready node as a child work unit when a dispatcher is configured."""
        if self.dispatcher is None:
            return None
        request = DispatchRequest(
            mode="execute",
            task_id=str(node.get("id", "unknown")),
            phase=self.dispatch_phase,
            prompt=str(node.get("title", node.get("id", "Execute graph node"))),
            inputs={"node": dict(node), "task_description": str(node.get("title", ""))},
            expected_outputs=["implementation_plan", "work_unit_result", "evidence"],
            constraints={"purpose": "child_task_execution"},
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
        result = {
            "dispatched": True,
            "success": response.success,
            "outputs": response.outputs,
            "evidence": response.evidence,
            "artifacts": response.artifacts,
        }
        if response.error:
            result["error"] = response.error
        if response.raw_transcript_ref:
            result["raw_transcript_ref"] = response.raw_transcript_ref
        return result
