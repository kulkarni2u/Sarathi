"""Task tracking phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class TaskTrackingHandler:
    """Task manifest and blocked-sub-agent protocol."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        task_tracking = getattr(self.policy_pack, "task_tracking", {}) or {}
        evidence = {"manifest_considered": bool(task_tracking)}
        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts={
                "execution_surface": "host_agent",
                "agent_checklist": [
                    "Update task manifest / blocked-by per task-tracking.md.",
                    "If blocked on a dependency, record blocker and next action.",
                ],
                "mode": "execute",
            },
        )
