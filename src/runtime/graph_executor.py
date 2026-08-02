"""Task graph execution helpers."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

try:
    from src.runtime.context import ContextCompiler
    from src.runtime.contracts import DispatchRequest
    from src.runtime.isolation import GitWorktreeIsolation
    from src.runtime.judge_scoring import (
        BakeoffHistoryStore,
        JudgeScoringPolicy,
        assemble_judge_scorecard,
        format_scorecard_for_prompt,
        lone_verified_survivor,
    )
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
    from runtime.isolation import GitWorktreeIsolation
    from runtime.judge_scoring import (
        BakeoffHistoryStore,
        JudgeScoringPolicy,
        assemble_judge_scorecard,
        format_scorecard_for_prompt,
        lone_verified_survivor,
    )
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
        isolation_repo_root: str | Path | None = None,
        judge_scoring_policy: "JudgeScoringPolicy | None" = None,
    ):
        self.dispatcher = dispatcher
        self.dispatch_phase = dispatch_phase
        self.context_compiler = ContextCompiler()
        self.ncp_context_adapter = ncp_context_adapter
        self.ncp_artifact_adapter = ncp_artifact_adapter
        self.ncp_whisper_router = ncp_whisper_router
        self.ncp_persistence_adapter = ncp_persistence_adapter
        self.workflow_patterns_policy = workflow_patterns_policy
        # Measured JUDGE scoring (src/runtime/judge_scoring.py): parsed from a
        # policy pack's `judge_scoring:` review.md block. None (the default)
        # means the feature is off — JUDGE dispatch and post-execution
        # injection stay byte-for-byte what they were before this existed.
        self.judge_scoring_policy = judge_scoring_policy
        # The HarnessConfig (src/harness.py) compiled for the parent task,
        # if any. Every node this executor dispatches carries the harness_id
        # of this config on its DispatchRequest — the "declare before
        # dispatch" invariant (see CLAUDE.md) applied to graph nodes, not
        # just the single top-level routed task. Callers that drive many
        # tasks through one long-lived executor (e.g. BuildHandler) should
        # pass a fresher ``harness_config`` into execute_*() per call instead
        # of relying on this constructor default.
        self.harness_config = harness_config
        self.isolation_repo_root = Path(isolation_repo_root).resolve() if isolation_repo_root else Path.cwd()
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
    def _uses_worktree_isolation(harness_config: Any) -> bool:
        return getattr(harness_config, "isolation_mode", "none") == "worktree"

    @staticmethod
    def _isolation_cleanup_mode(harness_config: Any) -> str:
        mode = getattr(harness_config, "isolation_cleanup", "auto")
        return mode if isinstance(mode, str) and mode else "auto"

    @staticmethod
    def _isolation_task_id(harness_config: Any, graph: dict | None) -> str:
        task_id = getattr(harness_config, "task_id", "") or ""
        if task_id:
            return task_id
        if graph is not None:
            graph_task_id = graph.get("task_id") or graph.get("id")
            if graph_task_id:
                return str(graph_task_id)
        return "graph"

    def _prepare_isolated_batch(
        self,
        batch: list[dict],
        graph: dict | None,
        harness_config: Any,
    ) -> list[dict]:
        task_id = self._isolation_task_id(harness_config, graph)
        isolation = GitWorktreeIsolation(self.isolation_repo_root)
        isolated: list[dict] = []
        for node in batch:
            node_copy = dict(node)
            worktree_path = isolation.create_worktree(
                task_id=task_id,
                node_id=str(node.get("id", "node")),
            )
            node_copy["_sarathi_workspace_dir"] = str(worktree_path)
            isolated.append(node_copy)
        return isolated

    def _cleanup_isolated_task(self, harness_config: Any, graph: dict | None) -> None:
        if not self._uses_worktree_isolation(harness_config):
            return
        if self._isolation_cleanup_mode(harness_config) == "manual":
            return
        task_id = self._isolation_task_id(harness_config, graph)
        GitWorktreeIsolation(self.isolation_repo_root).cleanup_task_worktrees(task_id)

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
            isolation = provider_result.get("isolation")
            if isinstance(isolation, dict):
                node["isolation"] = dict(isolation)
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

        effective_harness = self._resolve_harness(harness_config)
        try:
            [(ready, provider_result)] = self._dispatch_batch([ready], current, harness_config=effective_harness)
            updated, event, _failed = self._apply_node_result(
                current,
                ready,
                provider_result,
                fail_node_id=fail_node_id,
                fail_error=fail_error,
                harness_config=effective_harness,
            )
        finally:
            self._cleanup_isolated_task(effective_harness, current)
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

        effective_harness = self._resolve_harness(harness_config)
        try:
            while not stop:
                remaining = None if max_nodes is None else max_nodes - executed
                if remaining is not None and remaining <= 0:
                    break
                batch = self._ready_batch(current, limit=remaining)
                if not batch:
                    break
                for ready, provider_result in self._dispatch_batch(batch, current, harness_config=effective_harness):
                    current, event, failed = self._apply_node_result(
                        current,
                        ready,
                        provider_result,
                        fail_node_id=fail_node_id,
                        fail_error=fail_error,
                        harness_config=effective_harness,
                    )
                    events.append(event)
                    executed += 1
                    if failed:
                        stop = True
        finally:
            self._cleanup_isolated_task(effective_harness, current)

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
        effective_harness = self._resolve_harness(harness_config)
        if self._uses_worktree_isolation(effective_harness):
            batch = self._prepare_isolated_batch(batch, graph, effective_harness)
        if len(batch) == 1 or self.max_parallel <= 1 or self.dispatcher is None:
            return [
                (node, self._dispatch_node(node, graph=graph, harness_config=effective_harness))
                for node in batch
            ]
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(batch))) as pool:
            futures = [
                pool.submit(self._dispatch_node, node, graph=graph, harness_config=effective_harness)
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
        harness_config: Any = None,
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
            updated = self._post_execute_inject(ready, updated, provider_result, harness_config=harness_config)
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

    def apply_judge_winner_worktree(
        self,
        graph: dict,
        *,
        judge_node_id: str,
        approved: bool,
    ) -> dict[str, Any]:
        """Apply the retained worktree for an explicitly approved JUDGE winner."""
        updated_graph = deepcopy(graph)
        judge_node = self._find_graph_node(updated_graph, judge_node_id)
        judge_outputs = self._node_provider_outputs(judge_node)
        winner_node_id = str(judge_outputs.get("winner", "")).strip()
        if not winner_node_id:
            return {
                "applied": False,
                "judge_node_id": judge_node_id,
                "reason": "no_winner",
            }

        winner_node = self._find_graph_node(updated_graph, winner_node_id)
        if winner_node is None:
            return {
                "applied": False,
                "judge_node_id": judge_node_id,
                "winner_node_id": winner_node_id,
                "reason": "winner_not_found",
            }

        isolation = self._node_isolation_metadata(winner_node)
        workspace_dir = isolation.get("workspace_dir") if isolation else None
        if not workspace_dir:
            return {
                "applied": False,
                "judge_node_id": judge_node_id,
                "winner_node_id": winner_node_id,
                "reason": "no_worktree_isolation",
            }

        result = GitWorktreeIsolation(self.isolation_repo_root).apply_worktree_changes(
            workspace_dir,
            approved=approved,
        )
        result["judge_node_id"] = judge_node_id
        result["winner_node_id"] = winner_node_id
        if result.get("applied") is True and winner_node is not None:
            winner_node["isolation_apply"] = dict(result)
            updated_graph.setdefault("isolation_applications", []).append(dict(result))
            self._cleanup_graph_worktrees(updated_graph)
            result["graph_state"] = updated_graph
        return result

    @staticmethod
    def _find_graph_node(graph: dict, node_id: str) -> dict | None:
        return next(
            (node for node in graph.get("nodes", []) if node.get("id") == node_id),
            None,
        )

    @staticmethod
    def _node_provider_outputs(node: dict | None) -> dict:
        if not isinstance(node, dict):
            return {}
        provider_result = node.get("last_provider_result")
        if isinstance(provider_result, dict) and isinstance(provider_result.get("outputs"), dict):
            return provider_result["outputs"]
        return {}

    @staticmethod
    def _node_isolation_metadata(node: dict | None) -> dict:
        if not isinstance(node, dict):
            return {}
        isolation = node.get("isolation")
        if isinstance(isolation, dict):
            return isolation
        provider_result = node.get("last_provider_result")
        if isinstance(provider_result, dict) and isinstance(provider_result.get("isolation"), dict):
            return provider_result["isolation"]
        return {}

    def _cleanup_graph_worktrees(self, graph: dict) -> None:
        isolation = GitWorktreeIsolation(self.isolation_repo_root)
        for node in graph.get("nodes", []):
            metadata = self._node_isolation_metadata(node)
            workspace_dir = metadata.get("workspace_dir") if metadata else None
            if not isinstance(workspace_dir, str) or not workspace_dir:
                continue
            worktree_path = Path(workspace_dir).resolve()
            try:
                worktree_path.relative_to(isolation.worktrees_root)
            except ValueError:
                continue
            isolation.cleanup_worktree(worktree_path)

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
        self, node: dict, graph: dict, provider_result: dict | None, harness_config: Any = None
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
            self._record_bakeoff_outcome(node, provider_result, harness_config=harness_config)
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

    def _record_bakeoff_outcome(
        self, node: dict, provider_result: dict | None, *, harness_config: Any = None
    ) -> None:
        """Persist a judged-fanout winner into the bake-off history for evolve.py.

        No-ops (never raises) unless a judge scorecard was actually recorded
        on this dispatch (``artifacts["judge_scorecard"]``, only present when
        a ``judge_scoring_policy`` is configured and the JUDGE's outputs name
        a winner matching a scored branch) — absent scoring, this is a pure
        no-op and today's behavior is unchanged.
        """
        if not isinstance(provider_result, dict):
            return
        scorecard = (provider_result.get("artifacts") or {}).get("judge_scorecard")
        if not isinstance(scorecard, list) or not scorecard:
            return
        outputs = provider_result.get("outputs", {})
        winner_ref = str(outputs.get("winner", "")).strip() if isinstance(outputs, dict) else ""
        if not winner_ref:
            return
        winner_entry = next(
            (entry for entry in scorecard if str(entry.get("branch")) == winner_ref), None
        )
        if winner_entry is None:
            return

        effective_harness = harness_config if harness_config is not None else self.harness_config
        task_class_attr = getattr(effective_harness, "task_class", None)
        task_class = getattr(task_class_attr, "value", None) or str(task_class_attr or "") or "unknown"

        try:
            BakeoffHistoryStore(self.isolation_repo_root / ".sarathi").record(
                task_class=task_class,
                judge_node_id=str(node.get("id", "")),
                winner_branch=winner_ref,
                provider=winner_entry.get("provider"),
                weighted_score=winner_entry.get("weighted_score"),
                scorecard=scorecard,
            )
        except Exception:
            # Bake-off history is best-effort observability, never a reason
            # to fail graph execution.
            pass

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
            repo_index_root=str(self.isolation_repo_root),
        )
        return cp.to_artifact(), cp.agent_input.token_budget

    def _dispatch_node(
        self, node: dict, *, graph: dict | None = None, harness_config: Any = None
    ) -> dict | None:
        """Dispatch a ready node as a child work unit when a dispatcher is configured."""
        if self.dispatcher is None:
            return None

        workspace_dir = node.get("_sarathi_workspace_dir")
        node_for_context = dict(node)
        node_for_context.pop("_sarathi_workspace_dir", None)

        node_type = str(node_for_context.get("node_type", NodeType.EXECUTE)).lower()
        ncp = self.ncp_context_adapter

        # Typed nodes and EXECUTE branch nodes get NCP-aware context.
        # Branch nodes have '-branch-' in their id and receive fanout/classify whispers.
        # Fall back to local ContextCompiler on any NCP error.
        is_branch = "-branch-" in str(node_for_context.get("id", ""))
        if ncp is not None and (node_type not in (NodeType.EXECUTE, "execute") or is_branch):
            try:
                context_pack_artifact = ncp.compile_typed_node_context(
                    node=node_for_context, graph=graph, phase=self.dispatch_phase,
                )
                token_budget = (
                    context_pack_artifact.get("agent_input", {}).get("token_budget")
                )
            except Exception:
                context_pack_artifact, token_budget = self._local_context(node_for_context, graph)
                context_pack_artifact.setdefault("compilation", {})["ncp_fallback"] = True
        else:
            context_pack_artifact, token_budget = self._local_context(node_for_context, graph)

        # Measured JUDGE scoring (src/runtime/judge_scoring.py): when this is a
        # JUDGE node and a judge_scoring policy is configured, assemble a
        # deterministic per-branch scorecard from the branches' already-measured
        # dispatch evidence and fold it into the judge's own context/prompt, so
        # the LLM judge sees real cost/latency/blast-radius/test signals
        # alongside the branch outputs it already receives. Absent a policy (the
        # default), this is a no-op and `judge_scorecard` stays unset — today's
        # JUDGE dispatch is unaffected.
        judge_scorecard: list[dict[str, Any]] = []
        if node_type == NodeType.JUDGE and self.judge_scoring_policy is not None:
            judge_scorecard = assemble_judge_scorecard(
                self.judge_scoring_policy, node_for_context, graph
            )
            # Deterministic auto-select (opt-in via judge_scoring.auto_select_
            # lone_survivor): when local verification already eliminated every
            # candidate but one, there's no judgment left to make -- spending a
            # JUDGE dispatch to confirm it would only replay the same
            # already-measured pass/fail signals back at a model. Skips the
            # dispatch entirely and completes the node with a synthesized
            # result shaped exactly like a real one, so every downstream step
            # (bakeoff history, winner-propagation node injection, NCP judge
            # whisper) runs unmodified.
            if judge_scorecard and self.judge_scoring_policy.auto_select_lone_survivor:
                auto_winner = lone_verified_survivor(judge_scorecard)
                if auto_winner is not None:
                    return self._auto_selected_judge_result(judge_scorecard, auto_winner)
            if judge_scorecard:
                context_pack_artifact = dict(context_pack_artifact)
                agent_input = dict(context_pack_artifact.get("agent_input", {}))
                prior_findings = list(agent_input.get("prior_findings", []))
                prior_findings.extend(format_scorecard_for_prompt(judge_scorecard))
                agent_input["prior_findings"] = prior_findings
                context_pack_artifact["agent_input"] = agent_input
                compilation = dict(context_pack_artifact.get("compilation", {}))
                compilation["judge_scorecard_injected"] = True
                context_pack_artifact["compilation"] = compilation

        constraints = {"purpose": "child_task_execution"}
        node_provider = node_for_context.get("pattern_config", {}).get("provider")
        if node_provider:
            constraints["provider"] = node_provider
        if workspace_dir:
            constraints["isolation_mode"] = "worktree"
            constraints["workspace_dir"] = workspace_dir

        # "Declare before dispatch": stamp the harness_id of the HarnessConfig
        # already compiled for the parent task (in ROUTE) onto this node's
        # DispatchRequest. Every graph node — including FANOUT branches and
        # JUDGE candidates — dispatches under the same declared permission /
        # budget contract as the task it belongs to. See src/harness.py.
        effective_harness = self._resolve_harness(harness_config)
        harness_id = getattr(effective_harness, "harness_id", None)
        isolation_metadata = None
        if workspace_dir:
            isolation_metadata = {
                "mode": "worktree",
                "cleanup": self._isolation_cleanup_mode(effective_harness),
                "workspace_dir": workspace_dir,
            }

        request = DispatchRequest(
            mode="execute",
            task_id=str(node_for_context.get("id", "unknown")),
            phase=self.dispatch_phase,
            prompt=str(node_for_context.get("title", node_for_context.get("id", "Execute graph node"))),
            inputs={
                "node": dict(node_for_context),
                "task_description": str(node_for_context.get("title", "")),
                "context_pack": context_pack_artifact,
                **({"judge_scorecard": judge_scorecard} if judge_scorecard else {}),
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
            result = {
                "dispatched": True,
                "success": False,
                "error": f"Dispatcher child-task execution failed: {exc}",
                "artifacts": {},
            }
            if isolation_metadata:
                result["isolation"] = isolation_metadata
                result["artifacts"]["isolation"] = isolation_metadata
            if judge_scorecard:
                result["artifacts"]["judge_scorecard"] = judge_scorecard
            return result
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
            "artifacts": dict(response.artifacts) if judge_scorecard else response.artifacts,
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
        if judge_scorecard:
            result["artifacts"]["judge_scorecard"] = judge_scorecard
        if response.usage:
            result["usage"] = response.usage.to_artifact()
            ncp = self.ncp_context_adapter
            if ncp is not None and hasattr(ncp, "_call_log_cost"):
                try:
                    ncp._call_log_cost(
                        agent_id=f"s.sarathi.node.{node_for_context.get('id', 'unknown')}",
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
        if isolation_metadata:
            result["isolation"] = isolation_metadata
            result.setdefault("artifacts", {}).setdefault("isolation", isolation_metadata)
        return result

    @staticmethod
    def _auto_selected_judge_result(judge_scorecard: list[dict[str, Any]], winner_branch: str) -> dict[str, Any]:
        """Synthesize a JUDGE node result without dispatching, for the lone-survivor case.

        Shaped like a real dispatch result (``outputs["winner"]``,
        ``artifacts["judge_scorecard"]``) so ``_record_bakeoff_outcome``,
        ``_inject_judge_result``, and ``_ncp_emit_judge_whisper`` -- all of
        which only ever read a ``provider_result`` dict, never a real
        ``DispatchResponse`` -- treat it identically to a judged outcome.
        """
        return {
            "dispatched": False,
            "success": True,
            "outputs": {
                "winner": winner_branch,
                "reasoning": (
                    f"Auto-selected {winner_branch}: the only candidate that passed "
                    "local verification, while every other candidate failed it."
                ),
            },
            "evidence": {"auto_selected": True, "reason": "lone_verified_survivor"},
            "artifacts": {"judge_scorecard": judge_scorecard, "auto_selected": True},
        }
