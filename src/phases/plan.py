"""Plan phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from src.task_graph import graph_from_plan, graph_from_workflow
except ImportError:
    from task_graph import graph_from_plan, graph_from_workflow

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class PlanHandler:
    """Handler for the PLAN phase."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import DispatchRequest, PhaseResult

        prev_artifacts = {}
        if task.phase_results:
            prev_artifacts = task.phase_results[-1].artifacts

        response = None
        if self.dispatcher is not None:
            hint = getattr(task, "gate_retry_hint", None)
            extra_constraints: dict = {}
            if isinstance(hint, dict) and hint.get("phase") == phase.value:
                extra_constraints["gate_retry"] = hint
            response = self.dispatcher.dispatch(
                DispatchRequest(
                    mode="execute",
                    task_id=task.task_id,
                    phase=phase.value,
                    prompt=task.description,
                    inputs={
                        "task_description": task.description,
                        "approaches": prev_artifacts.get("approaches", []),
                        "risks": prev_artifacts.get("risks", []),
                        "success_criteria": prev_artifacts.get("success_criteria", []),
                    },
                    expected_outputs=["implementation_plan", "workflow_graph", "effort_estimate"],
                    constraints=extra_constraints,
                )
            )

        if response is not None and response.success:
            plan = response.outputs.get("implementation_plan", {})
            workflow = response.outputs.get("workflow_graph", {})
            effort_estimate = int(response.outputs.get("effort_estimate", 0))
            evidence = {
                "implementation_plan_created": bool(plan.get("steps") or workflow.get("nodes")),
                "effort_estimated": effort_estimate > 0,
                "dependencies_identified": len(plan.get("dependencies", [])) > 0,
                "timeline_defined": "timeline" in plan,
                "checkpoint_list": response.evidence.get("checkpoint_list", False),
                "dependency_map": response.evidence.get("dependency_map", False),
                "rollback_plan": response.evidence.get("rollback_plan", False),
                "workflow_typed": bool(workflow.get("nodes")),
            }
            task_graph = (
                graph_from_workflow(workflow).to_artifact()
                if workflow.get("nodes")
                else graph_from_plan(plan).to_artifact()
            )
            artifacts = {
                "implementation_plan": plan,
                "effort_estimate": effort_estimate,
                "task_graph": task_graph,
                "dispatch_artifacts": response.artifacts,
            }
            if workflow.get("nodes"):
                artifacts["workflow_graph"] = workflow
            if response.usage is not None:
                artifacts["dispatch_usage"] = response.usage.to_artifact()
        else:
            plan = self._create_implementation_plan(task, prev_artifacts)
            effort_estimate = self._estimate_effort(plan)

            deps = plan.get("dependencies", [])
            has_rollback = any("rollback" in str(d).lower() for d in deps) or bool(
                prev_artifacts.get("risks")
            )

            evidence = {
                "implementation_plan_created": len(plan.get("steps", [])) > 0,
                "effort_estimated": effort_estimate > 0,
                "dependencies_identified": len(deps) > 0,
                "timeline_defined": "timeline" in plan,
                "checkpoint_list": len(plan.get("steps", [])) > 0,
                "dependency_map": len(deps) > 0,
                "rollback_plan": has_rollback,
            }
            artifacts = {
                "implementation_plan": plan,
                "effort_estimate": effort_estimate,
                "task_graph": graph_from_plan(plan).to_artifact(),
            }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )

    def _create_implementation_plan(self, task: "TaskContext", prev_artifacts: dict) -> dict[str, Any]:
        approaches = prev_artifacts.get("approaches", [])
        risks = prev_artifacts.get("risks", [])
        return {
            "objective": task.description,
            "approach": approaches[0] if approaches else "Direct implementation",
            "steps": [
                "Analyze requirements and constraints",
                "Design solution architecture",
                "Implement core functionality",
                "Add tests and validation",
                "Review and refine",
            ],
            "dependencies": risks,
            "timeline": "1-2 weeks",
            "success_criteria": prev_artifacts.get("success_criteria", []),
        }

    def _estimate_effort(self, plan: dict[str, Any]) -> int:
        steps = len(plan.get("steps", []))
        deps = len(plan.get("dependencies", []))
        return max(steps + deps, 1)
