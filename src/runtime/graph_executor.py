"""Task graph execution helpers."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

try:
    from src.runtime.context import ContextCompiler
    from src.runtime.contracts import DispatchRequest
    from src.runtime.output_index import build_artifact_index, normalize_agent_output
    from src.runtime.workflow_patterns import WorkflowPattern, WorkflowPatternsPolicy
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
    from runtime.workflow_patterns import WorkflowPattern, WorkflowPatternsPolicy
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
        workflow_patterns_policy: "WorkflowPatternsPolicy | None" = None,
        max_parallel: int | None = None,
        harness_config: Any = None,
    ):
        self.dispatcher = dispatcher
        self.dispatch_phase = dispatch_phase
        self.context_compiler = ContextCompiler()
        self.ncp_context_adapter = ncp_context_adapter
        self.ncp_artifact_adapter = ncp_artifact_adapter
        self.ncp_whisper_router = ncp_whisper_router
        self.ncp_persistence_adapter = ncp_persistence_adapter
        self.workflow_patterns_policy = workflow_patterns_policy
        # The HarnessConfig (src/harness.py) compiled for the parent task,
        # if any. Every node this executor dispatches carries the harness_id
        # of this config on its DispatchRequest — the "declare before
        # dispatch" invariant (see CLAUDE.md) applied to graph nodes, not
        # just the single top-level routed task. Callers that drive many
        # tasks through one long-lived executor (e.g. BuildHandler) should
        # pass a fresher ``harness_config`` into execute_*() per call instead
        # of relying on this constructor default.
        self.harness_config = harness_config
        if max_parallel is None:
            try:
                max_parallel = int(os.environ.get("SARATHI_GRAPH_MAX_PARALLEL", "4"))
            except ValueError:
                max_parallel = 4
        self.max_parallel = max(1, max_parallel)

    def _resolve_harness(self, harness_config: Any) -> Any:
        """Return the effective harness for a dispatch call.

        Falls back to the executor's own ``self.harness_config`` when the
        caller doesn't override it for this specific call.
        """
        return harness_config if harness_config is not None else self.harness_config

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

    def execute_next(
        self,
        graph: dict,
        fail_node_id: str | None = None,
        fail_error: str | None = None,
        harness_config: Any = None,
    ) -> GraphExecutionResult:
        """Execute the next ready node only."""
        current = _copy_graph_state(graph)
        ready = next_ready_node(current)
        if ready is None:
            return GraphExecutionResult(graph_state=current, events=[])

        provider_result = self._dispatch_node(ready, graph=current, harness_config=harness_config)
        updated, event, _failed = self._apply_node_result(
            current, ready, provider_result, fail_node_id=fail_node_id, fail_error=fail_error
        )
        return GraphExecutionResult(graph_state=updated, events=[event])

    def execute_some(
        self,
        graph: dict,
        max_nodes: int | None = None,
        fail_node_id: str | None = None,
        fail_error: str | None = None,
        harness_config: Any = None,
    ) -> GraphExecutionResult:
        """Execute up to `max_nodes` ready nodes in dependency order."""
        if max_nodes is None:
            return self.execute_all(
                graph, fail_node_id=fail_node_id, fail_error=fail_error, harness_config=harness_config
            )
        if max_nodes <= 0:
            current = _copy_graph_state(graph)
            return GraphExecutionResult(graph_state=current, events=[])
        return self._execute_loop(
            graph,
            max_nodes=max_nodes,
            fail_node_id=fail_node_id,
            fail_error=fail_error,
            harness_config=harness_config,
        )

    def execute_all(
        self,
        graph: dict,
        fail_node_id: str | None = None,
        fail_error: str | None = None,
        harness_config: Any = None,
    ) -> GraphExecutionResult:
        return self._execute_loop(
            graph,
            max_nodes=None,
            fail_node_id=fail_node_id,
            fail_error=fail_error,
            harness_config=harness_config,
        )

    def _execute_loop(
        self,
        graph: dict,
        *,
        max_nodes: int | None,
        fail_node_id: str | None,
        fail_error: str | None,
        harness_config: Any = None,
    ) -> GraphExecutionResult:
        """Drive the graph to completion in batches of independent ready nodes.

        Nodes that are simultaneously ready depend only on already-completed
        work, so each batch is dispatched concurrently (bounded by
        ``max_parallel``). Graph mutations stay on this thread: results are
        applied sequentially, in deterministic graph order, after the batch
        returns. On a failure the already-dispatched batch results are still
        recorded (the work really ran), but no further batches are scheduled.
        """
        current = _copy_graph_state(graph)
        events: list[GraphExecutionEvent] = []
        executed = 0
        stop = False

        while not stop:
            remaining = None if max_nodes is None else max_nodes - executed
            if remaining is not None and remaining <= 0:
                break
            batch = self._ready_batch(current, limit=remaining)
            if not batch:
                break
            for ready, provider_result in self._dispatch_batch(batch, current, harness_config=harness_config):
                current, event, failed = self._apply_node_result(
                    current, ready, provider_result, fail_node_id=fail_node_id, fail_error=fail_error
                )
                events.append(event)
                executed += 1
                if failed:
                    stop = True

        return GraphExecutionResult(graph_state=current, events=events)

    def _ready_batch(self, graph: dict, limit: int | None = None) -> list[dict]:
        """All pending nodes whose dependencies are completed, in graph order."""
        nodes = {node.get("id"): node for node in graph.get("nodes", [])}
        batch: list[dict] = []
        for node in graph.get("nodes", []):
            if node.get("status", "pending") != "pending":
                continue
            deps = node.get("depends_on", [])
            if all(nodes.get(dep, {}).get("status") == "completed" for dep in deps):
                batch.append(node)
                if limit is not None and len(batch) >= limit:
                    break
        return batch

    def _dispatch_batch(
        self, batch: list[dict], graph: dict, *, harness_config: Any = None
    ) -> list[tuple[dict, dict | None]]:
        """Dispatch a batch of independent ready nodes, concurrently when possible.

        Provider calls dominate wall-clock time (minutes per CLI agent call);
        the dispatcher and providers run subprocesses/network calls, so threads
        parallelize them effectively. Results are returned in batch order.
        """
        if len(batch) == 1 or self.max_parallel <= 1 or self.dispatcher is None:
            return [
                (node, self._dispatch_node(node, graph=graph, harness_config=harness_config))
                for node in batch
            ]
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(batch))) as pool:
            futures = [
                pool.submit(self._dispatch_node, node, graph=graph, harness_config=harness_config)
                for node in batch
            ]
            return [(node, future.result()) for node, future in zip(batch, futures)]

    def _apply_node_result(
        self,
        current: dict,
        ready: dict,
        provider_result: dict | None,
        *,
        fail_node_id: str | None,
        fail_error: str | None,
    ) -> tuple[dict, GraphExecutionEvent, bool]:
        """Apply one node's execution result to the graph. Returns (graph, event, failed)."""
        node_id = ready["id"]
        provider_failed = provider_result is not None and not provider_result.get("success", False)
        injected_failure = fail_node_id is not None and node_id == fail_node_id

        if provider_failed or injected_failure:
            error = (
                (provider_result or {}).get("error") or "Provider-backed node execution failed"
                if provider_failed
                else (fail_error or "Node execution failed")
            )
            updated = fail_graph_node(current, node_id=node_id, error=error)
            action = "failed"
            finished_key = "failed_at"
            failed = True
        else:
            updated = progress_graph(current, completed_node_id=node_id)
            ncp_err = self._ncp_post_node_complete(ready, provider_result)
            if ncp_err and isinstance(provider_result, dict):
                provider_result.setdefault("ncp_warnings", []).append(f"write_output_failed: {ncp_err}")
            updated = self._post_execute_inject(ready, updated, provider_result)
            action = "completed"
            finished_key = "completed_at"
            failed = False

        updated_node = next(
            (node for node in updated.get("nodes", []) if node.get("id") == node_id),
            {},
        )
        updated = self._annotate_node_result(updated, node_id, provider_result)
        event = GraphExecutionEvent(
            node_id=node_id,
            title=ready.get("title", node_id),
            action=action,
            started_at=updated_node.get("started_at"),
            finished_at=updated_node.get(finished_key) or self._timestamp(),
            attempt=updated_node.get("attempts"),
            provider_result=provider_result,
        )
        return updated, event, failed

    def retry_failed_node(self, graph: dict, node_id: str) -> dict:
        """Reset a failed node so it can be executed again."""
        return retry_graph_node(graph, node_id=node_id)

    def inject_nodes(self, graph: dict, parent_id: str, new_nodes: list[dict]) -> dict:
        """Inject new nodes into a live graph depending on parent_id."""
        return inject_nodes(graph, parent_id=parent_id, new_nodes=new_nodes)

    # ------------------------------------------------------------------
    # Pattern-specific post-execution injection
    # ------------------------------------------------------------------

    def _pattern_allowed(self, *pattern_names: str) -> bool:
        """Return True if any of the named patterns is enabled (or no policy is set)."""
        pol = self.workflow_patterns_policy
        if pol is None:
            return True
        return any(pol.is_enabled(p) for p in pattern_names)

    def _post_execute_inject(
        self, node: dict, graph: dict, provider_result: dict | None
    ) -> dict:
        """After a node completes, inject follow-on nodes and emit NCP signals."""
        node_type = node.get("node_type", NodeType.EXECUTE)

        if node_type == NodeType.FANOUT:
            if not self._pattern_allowed(WorkflowPattern.FANOUT_AND_SYNTHESIZE):
                return graph
            updated = self._inject_fanout_children(node, graph)
            cfg = node.get("pattern_config", {})
            count = int(cfg.get("count", cfg.get("max_branches", 2)))
            branch_ids = [f"{node['id']}-branch-{i}" for i in range(1, count + 1)]
            synthesize_id = f"{node['id']}-synthesize"
            failed = self._ncp_emit_fanout_whispers(node, branch_ids, synthesize_id)
            if failed:
                updated.setdefault("_ncp_warnings", []).append(
                    {"type": "fanout_whisper_failed", "targets": failed}
                )
            return updated

        if node_type == NodeType.JUDGE:
            if not self._pattern_allowed(
                WorkflowPattern.ADVERSARIAL_VERIFICATION, WorkflowPattern.TOURNAMENT
            ):
                return graph
            updated = self._inject_judge_result(node, graph, provider_result)
            winner_id = f"{node['id']}-winner"
            err = self._ncp_emit_judge_whisper(node, winner_id, provider_result)
            if err:
                updated.setdefault("_ncp_warnings", []).append(
                    {"type": "judge_whisper_failed", "error": err}
                )
            return updated

        if node_type == NodeType.LOOP_GATE:
            if not self._pattern_allowed(WorkflowPattern.LOOP_UNTIL_DONE):
                return graph
            err = self._ncp_write_loop_findings(node, provider_result)
            updated = self._inject_loop_iteration(node, graph, provider_result)
            if err:
                updated.setdefault("_ncp_warnings", []).append(
                    {"type": "loop_write_failed", "error": err}
                )
            return updated

        if node_type == NodeType.CLASSIFY:
            if not self._pattern_allowed(WorkflowPattern.CLASSIFY_AND_ACT):
                return graph
            updated = self._inject_classified_branch(node, graph, provider_result)
            outputs = (provider_result or {}).get("outputs", {})
            classification = str(outputs.get("classification", outputs.get("route", "")))
            if classification:
                branch_id = f"{node['id']}-branch-{classification}"
                err = self._ncp_emit_classify_whisper(node, branch_id, classification)
                if err:
                    updated.setdefault("_ncp_warnings", []).append(
                        {"type": "classify_whisper_failed", "error": err}
                    )
            return updated

        return graph

    # ------------------------------------------------------------------
    # NCP side-effect helpers
    # ------------------------------------------------------------------

    def _ncp_post_node_complete(self, node: dict, provider_result: dict | None) -> "str | None":
        """Persist node output to NCP so SYNTHESIZE / JUDGE nodes can fetch it.

        Returns an error string if the write fails, None on success.
        """
        if self.ncp_artifact_adapter is None or not isinstance(provider_result, dict):
            return None
        outputs = provider_result.get("outputs", {})
        if not outputs:
            return None
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
        except Exception as exc:
            return str(exc)
        return None

    def _ncp_emit_fanout_whispers(
        self, node: dict, branch_ids: list[str], synthesize_id: str
    ) -> list[str]:
        """Whisper the fanout objective + sibling list to every branch agent.

        Returns list of branch_ids for which emission failed.
        """
        if self.ncp_whisper_router is None:
            return []
        import json as _json
        failed: list[str] = []
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
                failed.append(branch_id)
        return failed

    def _ncp_emit_classify_whisper(
        self, node: dict, branch_id: str, classification: str
    ) -> "str | None":
        """Whisper why a branch was activated to the classified branch agent.

        Returns an error string if emission fails, None on success.
        """
        if self.ncp_whisper_router is None:
            return None
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
        except Exception as exc:
            return str(exc)
        return None

    def _ncp_emit_judge_whisper(
        self, node: dict, winner_id: str, provider_result: dict | None
    ) -> "str | None":
        """Whisper the judgment decision to the winner node.

        Returns an error string if emission fails, None on success.
        """
        if self.ncp_whisper_router is None:
            return None
        import json as _json
        try:
            outputs = (provider_result or {}).get("outputs", {})
            payload = _json.dumps({
                "parent_id": node.get("id"),
                "judgment": outputs,
                "objective": node.get("title", ""),
            })[:600]
            self.ncp_whisper_router.emit(
                from_agent="s.sarathi",
                target=f"s.{winner_id}",
                whisper_type="judge_context",
                payload=payload,
            )
        except Exception as exc:
            return str(exc)
        return None

    def _ncp_write_loop_findings(
        self, node: dict, provider_result: dict | None
    ) -> "str | None":
        """Write loop-gate findings to NCP episodic memory for the next iteration.

        Returns an error string if the write fails, None on success.
        """
        if self.ncp_persistence_adapter is None or not isinstance(provider_result, dict):
            return None
        outputs = provider_result.get("outputs", {})
        if not outputs:
            return None
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
        except Exception as exc:
            return str(exc)
        return None

    def _inject_fanout_children(self, node: dict, graph: dict) -> dict:
        """FANOUT: spawn N parallel EXECUTE children + one SYNTHESIZE fan-in node."""
        cfg = node.get("pattern_config", {})
        count = int(cfg.get("count", cfg.get("max_branches", 2)))
        title_template = cfg.get("title_template", "Branch {i}: " + node.get("title", "work"))
        synthesize_title = cfg.get("synthesize_title", f"Synthesize: {node.get('title', 'results')}")
        parent_id = node["id"]

        branch_ids = [f"{parent_id}-branch-{i}" for i in range(1, count + 1)]
        synthesize_id = f"{parent_id}-synthesize"

        providers = cfg.get("providers") or []

        children = []
        for i, bid in enumerate(branch_ids, start=1):
            branch_cfg: dict = {}
            if providers:
                branch_cfg["provider"] = providers[(i - 1) % len(providers)]
            children.append(
                {
                    "id": bid,
                    "title": title_template.replace("{i}", str(i)),
                    "node_type": NodeType.EXECUTE,
                    "depends_on": [parent_id],
                    "pattern_config": branch_cfg,
                }
            )
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

    def _dispatch_node(
        self, node: dict, *, graph: dict | None = None, harness_config: Any = None
    ) -> dict | None:
        """Dispatch a ready node as a child work unit when a dispatcher is configured."""
        if self.dispatcher is None:
            return None

        node_type = str(node.get("node_type", NodeType.EXECUTE)).lower()
        ncp = self.ncp_context_adapter

        # Typed nodes and EXECUTE branch nodes get NCP-aware context.
        # Branch nodes have '-branch-' in their id and receive fanout/classify whispers.
        # Fall back to local ContextCompiler on any NCP error.
        is_branch = "-branch-" in str(node.get("id", ""))
        if ncp is not None and (node_type not in (NodeType.EXECUTE, "execute") or is_branch):
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

        constraints = {"purpose": "child_task_execution"}
        node_provider = node.get("pattern_config", {}).get("provider")
        if node_provider:
            constraints["provider"] = node_provider

        # "Declare before dispatch": stamp the harness_id of the HarnessConfig
        # already compiled for the parent task (in ROUTE) onto this node's
        # DispatchRequest. Every graph node — including FANOUT branches and
        # JUDGE candidates — dispatches under the same declared permission /
        # budget contract as the task it belongs to. See src/harness.py.
        effective_harness = self._resolve_harness(harness_config)
        harness_id = getattr(effective_harness, "harness_id", None)

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
            constraints=constraints,
            context_pack=context_pack_artifact,
            token_budget=token_budget,
            retry_budget=0,
            harness_id=harness_id,
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
