"""Phase log handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class PhaseLogHandler:
    """Summarize prior phase outcomes."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        table = [
            {
                "phase": pr.phase.value,
                "outcome": pr.outcome,
                "iterations": pr.iterations,
            }
            for pr in task.phase_results
        ]
        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence={"tabular_log_emitted": len(table) > 0},
            artifacts={"phase_summary_table": table, "execution_surface": "cli"},
        )
