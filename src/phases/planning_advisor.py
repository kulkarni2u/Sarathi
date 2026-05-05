"""Planning advisor phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class PlanningAdvisorHandler:
    """High-complexity planning advisor."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        checklist = [
            "Challenge scope: smallest shippable slice first?",
            "List top risks with owner and mitigation.",
            "Confirm observability, rollback, and blast radius before Build.",
        ]
        evidence = {
            "advisor_prompts_emitted": True,
            "complexity_high": task.complexity.value == "high",
        }
        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts={
                "execution_surface": "host_agent",
                "agent_checklist": checklist,
                "mode": "explore",
            },
        )
