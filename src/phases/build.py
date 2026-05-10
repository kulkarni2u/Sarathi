"""Build phase handler."""
from __future__ import annotations

import os
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


class BuildHandler:
    """Build / TDD phase handler."""

    def __init__(self, policy_pack, dispatcher=None, graph_executor: TaskGraphExecutor | None = None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.graph_executor = graph_executor or TaskGraphExecutor(dispatcher=dispatcher)
        self.escalation_builder = EscalationBundleBuilder()

    def _graph_policy(self) -> GraphExecutionPolicy:
        return GraphExecutionPolicy.from_policy_sections(
            task_tracking=getattr(self.policy_pack, "task_tracking", {}) or {},
            escalation=getattr(self.policy_pack, "escalation", {}) or {},
        )

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

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
        return PhaseResult(
            phase=phase,
            outcome="escalate" if failed_node is not None or human_attention_node is not None else "pass",
            evidence=evidence,
            artifacts={
                "execution_surface": "host_agent",
                "agent_checklist": [
                    "Implement against the plan; keep tests green.",
                    "Prefer the smallest diff that satisfies acceptance criteria.",
                    "Document any plan deviation with rationale.",
                ],
                "mode": "execute",
                "plan_objective": plan.get("objective", task.description),
                "task_graph_state": graph_execution.graph_state if graph_execution else {},
                "task_graph_execution": graph_execution.to_artifact() if graph_execution else {},
                "graph_execution_mode": "incremental" if graph_policy.step_limit is not None else "complete",
                "graph_execution_policy": graph_policy.to_artifact(),
                "graph_retry_limit": graph_policy.max_retries,
                "graph_failed_node": failed_node or human_attention_node,
                "escalation_bundle": escalation_bundle,
                "pause_execution": pause_execution,
                "next_phase_override": next_phase_override,
            },
        )
