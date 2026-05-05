"""Brainstorm phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class BrainstormHandler:
    """Handler for the BRAINSTORM phase."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import DispatchRequest, PhaseResult

        response = None
        if self.dispatcher is not None:
            response = self.dispatcher.dispatch(
                DispatchRequest(
                    mode="explore",
                    task_id=task.task_id,
                    phase=phase.value,
                    prompt=task.description,
                    inputs={
                        "task_description": task.description,
                        "complexity": task.complexity.value,
                    },
                    expected_outputs=["approaches", "risks", "success_criteria"],
                )
            )

        if response is not None and response.success:
            approaches = response.outputs.get("approaches", [])
            risks = response.outputs.get("risks", [])
            success_criteria = response.outputs.get("success_criteria", [])
            evidence = {
                "alternative_approaches_considered": response.evidence.get("alternative_approaches_considered", False),
                "risks_identified": response.evidence.get("risks_identified", False),
                "success_criteria_defined": response.evidence.get("success_criteria_defined", False),
                "reversibility_assessed": response.evidence.get("reversibility_assessed", False),
            }
            artifacts = {
                "approaches": approaches,
                "risks": risks,
                "success_criteria": success_criteria,
                "dispatch_artifacts": response.artifacts,
            }
        else:
            approaches = self._generate_approaches(task)
            risks = self._assess_risks(approaches)
            success_criteria = self._define_success_criteria(task)
            evidence = {
                "alternative_approaches_considered": len(approaches) >= 3,
                "risks_identified": len(risks) > 0,
                "success_criteria_defined": len(success_criteria) > 0,
                "reversibility_assessed": any("rollback" in str(risk) for risk in risks),
            }
            artifacts = {
                "approaches": approaches,
                "risks": risks,
                "success_criteria": success_criteria,
            }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )

    def _generate_approaches(self, task: "TaskContext") -> list[str]:
        base_approaches = [
            f"Direct implementation: {task.description}",
            "Modular approach: Break down into smaller components",
            "Test-driven approach: Write tests first, then implementation",
        ]
        if task.complexity.value == "high":
            base_approaches.extend([
                "Iterative approach: Implement in phases with checkpoints",
                "Spike approach: Create proof-of-concept first",
            ])
        return base_approaches

    def _assess_risks(self, approaches: list[str]) -> list[str]:
        risks = []
        for approach in approaches:
            lower = approach.lower()
            if "direct" in lower:
                risks.append("May miss edge cases without proper analysis")
            if "modular" in lower:
                risks.append("Additional complexity in component interfaces")
            if "test-driven" in lower:
                risks.append("Initial time investment in test writing")
            if "iterative" in lower:
                risks.append("Scope creep if phases not well-defined")
            if "spike" in lower:
                risks.append("Proof-of-concept may not translate to production")
        return risks

    def _define_success_criteria(self, task: "TaskContext") -> list[str]:
        return [
            "Functionality works as specified",
            "No regressions in existing code",
            "Code follows project conventions",
            "Tests pass with adequate coverage",
        ]
