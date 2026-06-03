"""Build phase handler."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from src.task_graph import (
        annotate_graph_for_supervision,
        latest_failed_node,
        next_retryable_failed_node,
        require_human_for_graph_node,
    )
    from src.runtime import EscalationBundleBuilder, GraphExecutionPolicy, TaskGraphExecutor
except ImportError:
    from task_graph import (
        annotate_graph_for_supervision,
        latest_failed_node,
        next_retryable_failed_node,
        require_human_for_graph_node,
    )
    from runtime import EscalationBundleBuilder, GraphExecutionPolicy, TaskGraphExecutor

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


def _ncp_build_context(task: "TaskContext", run_path: str = ".ncp/run.py") -> str:
    """Retrieve relevant context from NCP for the Build phase."""
    args = {
        "agent_id": "s.builder",
        "role": "builder",
        "owns": [task.task_id],
        "must_not": [],
        "task": task.description,
        "slot": "Build",
        "intent": f"build:{task.task_id}",
    }
    try:
        result = subprocess.run(
            [sys.executable, run_path, "get_context", json.dumps(args)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


class BuildHandler:
    """Build / TDD phase handler."""

    def __init__(
        self,
        policy_pack,
        dispatcher=None,
        graph_executor: TaskGraphExecutor | None = None,
        ncp_context_adapter=None,
        ncp_artifact_adapter=None,
        ncp_whisper_router=None,
        ncp_persistence_adapter=None,
    ):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.graph_executor = graph_executor or TaskGraphExecutor(
            dispatcher=dispatcher,
            ncp_context_adapter=ncp_context_adapter,
            ncp_artifact_adapter=ncp_artifact_adapter,
            ncp_whisper_router=ncp_whisper_router,
            ncp_persistence_adapter=ncp_persistence_adapter,
        )
        self.escalation_builder = EscalationBundleBuilder()

    def _graph_policy(self) -> GraphExecutionPolicy:
        return GraphExecutionPolicy.from_policy_sections(
            task_tracking=getattr(self.policy_pack, "task_tracking", {}) or {},
            escalation=getattr(self.policy_pack, "escalation", {}) or {},
        )

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import DispatchRequest, PhaseResult

        plan: dict[str, Any] = {}
        for pr in reversed(task.phase_results):
            ip = pr.artifacts.get("implementation_plan")
            if isinstance(ip, dict):
                plan = ip
                break
        task_graph: dict[str, Any] = {}
        if getattr(task, "task_graph_state", {}):
            task_graph = task.task_graph_state
        else:
            for pr in reversed(task.phase_results):
                graph = pr.artifacts.get("task_graph")
                if isinstance(graph, dict):
                    task_graph = graph
                    break
        if task_graph:
            task_graph = annotate_graph_for_supervision(task_graph, parent_task_id=task.task_id)

        evidence = {
            "plan_consumed": bool(plan),
            "tdd_intent_acknowledged": True,
        }

        # --- Real provider dispatch: execute the plan via configured provider ---
        dispatch_response = None
        if self.dispatcher is not None and plan:
            ncp_ctx = _ncp_build_context(task)
            dispatch_response = self.dispatcher.dispatch(
                DispatchRequest(
                    mode="execute",
                    task_id=task.task_id,
                    phase=phase.value,
                    prompt=task.description,
                    inputs={
                        "task_description": task.description,
                        "implementation_plan": plan,
                        "complexity": task.complexity.value if hasattr(task.complexity, "value") else "medium",
                        "ncp_context": ncp_ctx,
                    },
                    expected_outputs=["implementation_result", "changed_files", "test_results"],
                    constraints={"provider": "opencode"},
                )
            )
            if dispatch_response is not None and dispatch_response.success:
                evidence["provider_dispatch"] = True
                evidence["provider"] = dispatch_response.artifacts.get("provider", "opencode")
            elif dispatch_response is not None:
                evidence["provider_dispatch"] = False
                evidence["provider_error"] = dispatch_response.error

        # --- Graph execution for task tracking ---
        graph_policy = self._graph_policy()
        retryable_failed = (
            next_retryable_failed_node(task_graph, max_attempts=graph_policy.max_retries)
            if task_graph and graph_policy.auto_retry_failed_nodes
            else None
        )
        if retryable_failed is not None:
            task_graph = self.graph_executor.retry_failed_node(task_graph, retryable_failed["id"])
            evidence["retried_node"] = retryable_failed["id"]
        graph_execution = (
            self.graph_executor.execute_some(
                task_graph,
                max_nodes=graph_policy.step_limit,
                fail_node_id=os.environ.get("SARATHI_GRAPH_FAIL_NODE"),
                fail_error=os.environ.get("SARATHI_GRAPH_FAIL_ERROR") or "Configured graph node failure",
            )
            if task_graph else None
        )
        pause_execution = False
        next_phase_override = None
        failed_node = None
        human_attention_node = None
        escalation_bundle = None
        if graph_execution is not None:
            failed_node = latest_failed_node(graph_execution.graph_state)
            if (
                failed_node is not None
                and graph_policy.require_human_after_retries
                and int(failed_node.get("attempts", 0) or 0) >= graph_policy.max_retries
            ):
                graph_execution.graph_state = require_human_for_graph_node(
                    graph_execution.graph_state,
                    failed_node["id"],
                )
                human_attention_node = next(
                    (
                        node for node in graph_execution.graph_state.get("nodes", [])
                        if node.get("id") == failed_node.get("id")
                    ),
                    failed_node,
                )
                failed_node = None
            remaining_nodes = [
                node for node in graph_execution.graph_state.get("nodes", [])
                if node.get("status", "pending") != "completed"
            ]
            evidence["graph_nodes_executed"] = len(graph_execution.events)
            evidence["graph_remaining"] = len(remaining_nodes)
            evidence["graph_failed"] = failed_node is not None or human_attention_node is not None
            if failed_node is not None:
                evidence["failed_node_id"] = failed_node.get("id")
                evidence["failed_node_attempts"] = failed_node.get("attempts", 0)
            if human_attention_node is not None:
                evidence["human_attention_node_id"] = human_attention_node.get("id")
                evidence["human_attention_required"] = True
                escalation_bundle = self.escalation_builder.build_for_phase(
                    task=task,
                    phase=phase.value,
                    reason=(
                        f"Graph node {human_attention_node.get('id')} exhausted "
                        "retry budget and requires human attention"
                    ),
                    graph_node=human_attention_node,
                ).to_artifact()
            elif failed_node is not None:
                escalation_bundle = self.escalation_builder.build_for_phase(
                    task=task,
                    phase=phase.value,
                    reason=f"Graph node {failed_node.get('id')} failed during build execution",
                    graph_node=failed_node,
                ).to_artifact()
            if (
                failed_node is not None
                and graph_policy.pause_on_failed_node
            ) or (
                remaining_nodes
                and graph_policy.pause_on_incomplete_graph
            ):
                pause_execution = True
                next_phase_override = phase.value

        artifacts: dict[str, Any] = {
            "execution_surface": "provider",
            "mode": "execute",
            "plan_objective": plan.get("objective", task.description),
            "provider_result": dispatch_response.outputs if dispatch_response and dispatch_response.success else {},
            "dispatch_artifacts": dispatch_response.artifacts if dispatch_response else {},
            "task_graph_state": graph_execution.graph_state if graph_execution else {},
            "task_graph_execution": graph_execution.to_artifact() if graph_execution else {},
            "graph_execution_mode": "incremental" if graph_policy.step_limit is not None else "complete",
            "graph_execution_policy": graph_policy.to_artifact(),
            "graph_retry_limit": graph_policy.max_retries,
            "graph_failed_node": failed_node or human_attention_node,
            "escalation_bundle": escalation_bundle,
            "pause_execution": pause_execution,
            "next_phase_override": next_phase_override,
        }
        if dispatch_response is not None and dispatch_response.usage is not None:
            artifacts["dispatch_usage"] = dispatch_response.usage.to_artifact()

        return PhaseResult(
            phase=phase,
            outcome="escalate" if failed_node is not None or human_attention_node is not None else "pass",
            evidence=evidence,
            artifacts=artifacts,
        )
