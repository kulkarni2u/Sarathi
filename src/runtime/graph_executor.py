"""Task graph execution helpers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

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

    def __init__(
        self,
        dispatcher=None,
        dispatch_phase: str = "Build",
        ncp_context_adapter=None,
        ncp_artifact_adapter=None,
        ncp_whisper_router=None,
        ncp_persistence_adapter=None,
    ):
        self.dispatcher = dispatcher
        self.dispatch_phase = dispatch_phase
        self.context_compiler = ContextCompiler()
        self.ncp_context_adapter = ncp_context_adapter
        self.ncp_artifact_adapter = ncp_artifact_adapter
        self.ncp_whisper_router = ncp_whisper_router
        self.ncp_persistence_adapter = ncp_persistence_adapter

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
            self._ncp_post_node_complete(ready, provider_result)
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
            self._ncp_post_node_complete(ready, provider_result)
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
            self._ncp_post_node_complete(ready, provider_result)
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
        """After a node completes, inject follow-on nodes and emit NCP signals."""
        node_type = node.get("node_type", NodeType.EXECUTE)

        if node_type == NodeType.FANOUT:
            updated = self._inject_fanout_children(node, graph)
            # Whisper fanout context to every injected branch
            cfg = node.get("pattern_config", {})
            count = int(cfg.get("count", cfg.get("max_branches", 2)))
            branch_ids = [f"{node['id']}-branch-{i}" for i in range(1, count + 1)]
            synthesize_id = f"{node['id']}-synthesize"
            self._ncp_emit_fanout_whispers(node, branch_ids, synthesize_id)
            return updated

        if node_type == NodeType.JUDGE:
            return self._inject_judge_result(node, graph, provider_result)

        if node_type == NodeType.LOOP_GATE:
            # Persist findings before injecting next iteration
            self._ncp_write_loop_findings(node, provider_result)
            return self._inject_loop_iteration(node, graph, provider_result)

        if node_type == NodeType.CLASSIFY:
            updated = self._inject_classified_branch(node, graph, provider_result)
            outputs = (provider_result or {}).get("outputs", {})
            classification = str(outputs.get("classification", outputs.get("route", "")))
            if classification:
                branch_id = f"{node['id']}-branch-{classification}"
                self._ncp_emit_classify_whisper(node, branch_id, classification)
            return updated

        return graph

    # ------------------------------------------------------------------
    # NCP side-effect helpers
    # ------------------------------------------------------------------

    def _ncp_post_node_complete(self, node: dict, provider_result: dict | None) -> None:
        """Persist node output to NCP so SYNTHESIZE / JUDGE nodes can fetch it."""
        if self.ncp_artifact_adapter is None or not isinstance(provider_result, dict):
            return
        outputs = provider_result.get("outputs", {})
        if not outputs:
            return
        import json as _json
        try:
            content = _json.dumps({
                "sarathi_node": node.get("id"),
                "node_type": node.get("node_type", "execute"),
                "title": node.get("title"),
                "outputs": outputs,
            })
            node_id = node.get("id", "unknown")
            self.ncp_artifact_adapter._call_write_memory(
                content[:2000],
                "semantic",
                f"sarathi.node.{node_id}",
                f"sarathi.node.{node_id}",
            )
        except Exception:
            pass

    def _ncp_emit_fanout_whispers(
        self, node: dict, branch_ids: list[str], synthesize_id: str
    ) -> None:
        """Whisper the fanout objective + sibling list to every branch agent."""
        if self.ncp_whisper_router is None:
            return
        import json as _json
        for branch_id in branch_ids:
            try:
                payload = _json.dumps({
                    "parent_id": node.get("id"),
                    "sibling_ids": branch_ids,
                    "synthesize_id": synthesize_id,
                    "objective": node.get("title", ""),
                })[:600]
                self.ncp_whisper_router.emit(
                    from_agent="s.sarathi",
                    target=f"s.{branch_id}",
                    whisper_type="fanout_context",
                    payload=payload,
                )
            except Exception:
                pass

    def _ncp_emit_classify_whisper(
        self, node: dict, branch_id: str, classification: str
    ) -> None:
        """Whisper why a branch was activated to the classified branch agent."""
        if self.ncp_whisper_router is None:
            return
        import json as _json
        try:
            payload = _json.dumps({
                "parent_id": node.get("id"),
                "classification": classification,
                "objective": node.get("title", ""),
            })[:600]
            self.ncp_whisper_router.emit(
                from_agent="s.sarathi",
                target=f"s.{branch_id}",
                whisper_type="classify_context",
                payload=payload,
            )
        except Exception:
            pass

    def _ncp_write_loop_findings(
        self, node: dict, provider_result: dict | None
    ) -> None:
        """Write loop-gate findings to NCP episodic memory for the next iteration."""
        if self.ncp_persistence_adapter is None or not isinstance(provider_result, dict):
            return
        outputs = provider_result.get("outputs", {})
        if not outputs:
            return
        import json as _json
        try:
            cfg = node.get("pattern_config", {})
            iteration = int(cfg.get("iteration", 1))
            node_id = str(node.get("id", ""))
            parent_id = node_id.rsplit("-iter-", 1)[0] if "-iter-" in node_id else node_id
            content = _json.dumps({
                "sarathi_loop": parent_id,
                "iteration": iteration,
                "findings": outputs,
            })
            self.ncp_persistence_adapter._call_write_memory(
                content[:2000],
                "episodic",
                f"sarathi.loop.{parent_id}",
                f"sarathi.loop.{parent_id}",
            )
        except Exception:
            pass

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

    def _local_context(self, node: dict, graph: dict | None) -> tuple[dict, int | None]:
        """Build a context pack using the local ContextCompiler."""
        cp = self.context_compiler.compile_graph_node_context(
            node=node,
            graph=graph,
            phase=self.dispatch_phase,
            available_tools=["task_graph", "workspace_files", "git_diff", "test_results"],
        )
        return cp.to_artifact(), cp.agent_input.token_budget

    def _dispatch_node(self, node: dict, *, graph: dict | None = None) -> dict | None:
        """Dispatch a ready node as a child work unit when a dispatcher is configured."""
        if self.dispatcher is None:
            return None

        node_type = str(node.get("node_type", NodeType.EXECUTE)).lower()
        ncp = self.ncp_context_adapter

        # Typed nodes get NCP-aware context (sibling artifacts, whispers, loop history).
        # Fall back to local ContextCompiler on any NCP error.
        if ncp is not None and node_type not in (NodeType.EXECUTE, "execute"):
            try:
                context_pack_artifact = ncp.compile_typed_node_context(
                    node=node, graph=graph, phase=self.dispatch_phase,
                )
                token_budget = (
                    context_pack_artifact.get("agent_input", {}).get("token_budget")
                )
            except Exception:
                context_pack_artifact, token_budget = self._local_context(node, graph)
                context_pack_artifact.setdefault("compilation", {})["ncp_fallback"] = True
        else:
            context_pack_artifact, token_budget = self._local_context(node, graph)

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
            token_budget=token_budget,
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
                "objective": context_pack_artifact.get("agent_input", {}).get("objective", ""),
                "token_budget": token_budget,
                "estimated_tokens": context_pack_artifact.get("compilation", {}).get("estimated_tokens"),
                "trimmed_sections": context_pack_artifact.get("compilation", {}).get("trimmed_sections"),
            },
        }
        if response.usage:
            result["usage"] = response.usage.to_artifact()
            ncp = self.ncp_context_adapter
            if ncp is not None and hasattr(ncp, "_call_log_cost"):
                try:
                    ncp._call_log_cost(
                        agent_id=f"s.sarathi.node.{node.get('id', 'unknown')}",
                        model=response.usage.provider_id or "unknown",
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        pipeline_id=str(node.get("id")),
                    )
                except Exception:
                    pass
        if response.error:
            result["error"] = response.error
        if response.raw_transcript_ref:
            result["raw_transcript_ref"] = response.raw_transcript_ref
        return result
