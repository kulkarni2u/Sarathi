"""Risk check phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class RiskCheckHandler:
    """Devil's advocate pass."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence={"risk_review_emitted": True},
            artifacts={
                "execution_surface": "host_agent",
                "agent_checklist": [
                    "What fails in production for this change?",
                    "Are feature flags / kill switches / rollbacks adequate?",
                ],
                "mode": "explore",
            },
        )
