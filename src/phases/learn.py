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

        # Wire HarnessOutcome into Evolver when harness_config is available (Piece 5)
        harness_proposals = self._ingest_harness_outcome(task)
        proposals.extend(harness_proposals)

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
            "harness_outcome_ingested": harness_proposals is not None,
        }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )

    def _ingest_harness_outcome(self, task: "TaskContext") -> list:
        """Build a HarnessOutcome from the completed task and feed it into Evolver."""
        harness_config = getattr(task, "harness_config", None)
        if harness_config is None:
            return []
        try:
            try:
                from src.harness import HarnessOutcome
            except ImportError:
                from harness import HarnessOutcome

            outcome = HarnessOutcome(
                harness_id=harness_config.harness_id,
                task_id=task.task_id,
                task_class=harness_config.task_class,
                quality_signals={sig.name: 0.0 for sig in harness_config.quality_signals},
                token_cost_actual=0,
                latency_ms=0,
                human_interventions=0,
                rollback_triggered=False,
                trust_gate_result=harness_config.trust_gate_result,
                agent_used=harness_config.primary_agent.agent_id,
                assembler_version=harness_config.assembler_version,
            )
            return self.evolver.ingest_harness_outcome(outcome)
        except Exception:
            return []
