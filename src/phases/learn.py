"""Learn phase handler."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

try:
    from src.evolve import EvolutionPolicy, Evolver
    from src.runtime import LearningStore
except ImportError:
    from evolve import EvolutionPolicy, Evolver
    from runtime import LearningStore

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class LearnHandler:
    """Extract lessons learned from task execution."""

    def __init__(
        self,
        policy_pack,
        dispatcher=None,
        provider_health=None,
        workspace_root=None,
        ncp_outcome_reporter=None,
        ncp_improvement_tracker=None,
        state_dir=None,
    ):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.learning_store = LearningStore()
        escalation = getattr(self.policy_pack, "escalation", {}) or {}
        # state_dir (the engine's .sarathi directory) persists per-task-class
        # quality baselines across runs; without it each process starts with
        # no baseline and harness-outcome proposals can never fire.
        self.evolver = Evolver(
            EvolutionPolicy.from_escalation(escalation),
            baseline_path=(Path(state_dir) / "evolve_baselines.json") if state_dir else None,
        )
        self.provider_health = provider_health
        # Optional workspace root so measured JUDGE routing feedback (Piece
        # 2.3) can find `.sarathi/bakeoff_history.json` (written by
        # TaskGraphExecutor -- see src/runtime/judge_scoring.py). None (the
        # default) means "not wired up here" -- generate_policy_proposals
        # simply gets no bake-off history and behaves exactly as before.
        self.workspace_root = workspace_root
        # Optional NCPOutcomeReporter: when NCP is active, the measured
        # outcome is recorded in NCP so it can recalibrate the trust of the
        # memory this task read and wrote. None means NCP is off.
        self.ncp_outcome_reporter = ncp_outcome_reporter
        # Optional NCPImprovementTracker: files proposals as NCP improvement
        # attempts (with their history) and runs the post-accept check of
        # accepted proposals against measured outcomes. None means NCP is off.
        self.ncp_improvement_tracker = ncp_improvement_tracker

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        artifacts = self.learning_store.build_artifacts(task)
        proposals = self.evolver.generate_policy_proposals(
            learning_records=[artifacts["learning_record"]],
            bakeoff_history=self._load_bakeoff_history(),
        )

        # Wire HarnessOutcome into Evolver when harness_config is available (Piece 5)
        harness_proposals, ncp_feedback, outcome = self._ingest_harness_outcome(task)
        proposals.extend(harness_proposals)
        if ncp_feedback is not None:
            artifacts["ncp_outcome"] = ncp_feedback

        artifacts["policy_proposals"] = [proposal.to_artifact() for proposal in proposals]
        post_accept = self._track_improvements(task, outcome, artifacts["policy_proposals"])
        if post_accept is not None:
            artifacts["post_accept_checks"] = post_accept
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
            "ncp_outcome_recorded": bool(ncp_feedback and ncp_feedback.get("recorded")),
            "post_accept_regressions": sum(
                1 for check in post_accept or [] if check.get("verdict") == "regressed"
            ),
        }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )

    def _ingest_harness_outcome(self, task: "TaskContext") -> tuple[list, dict | None, object]:
        """Build a measured HarnessOutcome and feed it into Evolver and NCP.

        Returns the Evolver's proposals, the NCP feedback summary (None when
        NCP is off) and the measured outcome (None when none could be measured).
        """
        harness_config = getattr(task, "harness_config", None)
        if harness_config is None:
            return [], None, None
        try:
            try:
                from src.harness import measure_outcome
            except ImportError:
                from harness import measure_outcome
            outcome = measure_outcome(task, harness_config)
        except Exception:
            return [], None, None
        self._record_provider_health(task, outcome)
        ncp_feedback = None
        if self.ncp_outcome_reporter is not None:
            # report() never raises; feedback must not fail LEARN.
            ncp_feedback = self.ncp_outcome_reporter.report(
                task, outcome, failure_outcomes=self.evolver.policy.failure_outcomes
            )
        try:
            return self.evolver.ingest_harness_outcome(outcome), ncp_feedback, outcome
        except Exception:
            return [], ncp_feedback, outcome

    def _track_improvements(
        self, task: "TaskContext", outcome, proposal_artifacts: list[dict]
    ) -> list[dict] | None:
        """File proposals as NCP attempts; log the outcome; check accepted proposals.

        Annotates each proposal artifact with ``improvement`` (its NCP attempt
        and the problem's earlier attempts). Returns the post-accept verdicts
        for this task's class, or None when tracking is off or no outcome was
        measured. Never raises.
        """
        tracker = self.ncp_improvement_tracker
        if tracker is None:
            return None
        task_class = getattr(getattr(outcome, "task_class", None), "value", None)
        try:
            annotations = tracker.record_proposals(proposal_artifacts, task_class=task_class)
            for proposal in proposal_artifacts:
                if proposal.get("id") in annotations:
                    proposal["improvement"] = annotations[proposal["id"]]
            if outcome is None or not task_class:
                return None
            try:
                from src.ncp_adapter.outcome import derive_ncp_outcome
            except ImportError:
                from ncp_adapter.outcome import derive_ncp_outcome
            derived = derive_ncp_outcome(
                task, outcome, failure_outcomes=self.evolver.policy.failure_outcomes
            )
            tracker.record_task_outcome(
                task_id=str(getattr(task, "task_id", "")),
                task_class=str(task_class),
                success=derived["success"],
                weight=derived["weight"],
                output_tokens=derived["ctx"].get("output_tokens"),
            )
            return tracker.check_accepted(str(task_class))
        except Exception as exc:  # tracking must never fail LEARN
            return [{"verdict": "error", "error": str(exc)[:300]}]

    def _record_provider_health(self, task: "TaskContext", outcome) -> None:
        """Record success/failure of the agent that did the work for health tracking."""
        if self.provider_health is None:
            return
        phase_results = getattr(task, "phase_results", []) or []
        success = not any(getattr(pr, "outcome", "") == "fail" for pr in phase_results)
        try:
            self.provider_health.record(outcome.agent_used, success)
        except Exception:
            pass

    def _load_bakeoff_history(self) -> list | None:
        """Load measured JUDGE bake-off history for routing-feedback proposals.

        Returns ``None`` (not ``[]``) when no ``workspace_root`` was
        configured or the history can't be read, so
        ``Evolver.propose_from_bakeoff_history`` short-circuits exactly like
        it does when no history exists at all.
        """
        if self.workspace_root is None:
            return None
        try:
            try:
                from src.runtime.judge_scoring import BakeoffHistoryStore
            except ImportError:
                from runtime.judge_scoring import BakeoffHistoryStore
            return BakeoffHistoryStore(Path(self.workspace_root) / ".sarathi").load()
        except Exception:
            return None
