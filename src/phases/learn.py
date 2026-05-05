"""Learn phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from src.evolve import Evolver
    from src.runtime import LearningStore
except ImportError:
    from evolve import Evolver
    from runtime import LearningStore

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class LearnHandler:
    """Extract lessons learned from task execution."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.learning_store = LearningStore()
        self.evolver = Evolver()

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        artifacts = self.learning_store.build_artifacts(task)
        proposals = self.evolver.generate_policy_proposals(
            learning_records=[artifacts["learning_record"]],
        )
        artifacts["policy_proposals"] = [proposal.to_artifact() for proposal in proposals]
        artifacts["proposal_count"] = len(proposals)
        lessons = artifacts["lessons_learned"]
        patterns_updated = artifacts["patterns_updated"]
        evidence = {
            "lessons_extracted": len(lessons) > 0,
            "patterns_updated": patterns_updated,
            "execution_analyzed": True,
            "insights_generated": len(lessons) > 0,
            "policy_proposals_generated": len(proposals),
        }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )
