"""Review phase handler."""
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

try:
    from src.task_graph import graph_summary
    from src.runtime import QualityLoopPolicy, ReviewRunner
except ImportError:
    from task_graph import graph_summary
    from runtime import QualityLoopPolicy, ReviewRunner

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class ReviewHandler:
    """Perform code review and quality checks."""

    def __init__(self, policy_pack, dispatcher=None, review_runner: ReviewRunner | None = None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.review_runner = review_runner or ReviewRunner()

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        review_inputs = self._review_inputs(task)
        verdict = self.review_runner.review(evidence=review_inputs)
        review_artifact = verdict.to_artifact()
        quality_policy = QualityLoopPolicy.from_escalation(
            getattr(self.policy_pack, "escalation", {}) or {},
            learning_feedback=getattr(self.policy_pack, "learning_feedback", {}) or {},
        )
        has_critical = review_artifact.get("severity_counts", {}).get("critical", 0) > 0
        retry_recommended = (
            review_artifact["outcome"] in {"escalate", "fail"}
            and quality_policy.review_retry_budget > 0
            and not (has_critical and quality_policy.hard_stop_on_critical)
        )
        auto_fix_allowed = retry_recommended and quality_policy.auto_fix_attempts > 0
        review_results = {
            finding["check"]: finding["passed"]
            for finding in review_artifact["findings"]
        }

        evidence = {
            "spec_compliance_checked": review_results.get("spec_compliance", False),
            "code_quality_reviewed": review_results.get("code_quality", False),
            "security_reviewed": review_results.get("security", False),
            "review_score_calculated": review_artifact["score"] >= 0,
            "review_summary": review_artifact.get("summary", {}),
            "severity_counts": review_artifact.get("severity_counts", {}),
            "failed_review_checks": review_artifact.get("totals", {}).get("failed", 0),
            "review_input_sources": sorted(review_inputs.keys()),
            "retry_recommended": retry_recommended,
            "auto_fix_allowed": auto_fix_allowed,
        }

        return PhaseResult(
            phase=phase,
            outcome=review_artifact["outcome"],
            evidence=evidence,
            artifacts={
                "review_results": review_results,
                "review_score": review_artifact["score"],
                "review_verdict": review_artifact,
                "review_summary": review_artifact.get("summary", {}),
                "review_inputs": review_inputs,
                "quality_loop_policy": quality_policy.to_artifact(),
                "retry_recommended": retry_recommended,
                "auto_fix_allowed": auto_fix_allowed,
            },
        )

    def _review_inputs(self, task: "TaskContext") -> dict:
        inputs = {}
        if task is None:
            return inputs
        description = getattr(task, "description", None)
        if isinstance(description, str) and description:
            inputs["spec_text"] = description
        task_graph_state = getattr(task, "task_graph_state", None)
        if isinstance(task_graph_state, dict) and task_graph_state:
            inputs["task_graph_state"] = task_graph_state
            inputs["task_graph_summary"] = graph_summary(task_graph_state)

        for result in reversed(getattr(task, "phase_results", [])):
            artifacts = getattr(result, "artifacts", {})
            plan = artifacts.get("implementation_plan")
            if "acceptance_criteria" not in inputs and isinstance(plan, dict):
                criteria = plan.get("success_criteria")
                if isinstance(criteria, list):
                    inputs["acceptance_criteria"] = criteria
            if "verification_summary" not in inputs and isinstance(artifacts.get("verification_summary"), dict):
                inputs["verification_summary"] = artifacts["verification_summary"]
            if "escalation_bundle" not in inputs and isinstance(artifacts.get("escalation_bundle"), dict):
                inputs["escalation_bundle"] = artifacts["escalation_bundle"]
            if "task_graph_execution" not in inputs and isinstance(artifacts.get("task_graph_execution"), dict):
                inputs["task_graph_execution"] = artifacts["task_graph_execution"]
        diff_summary = self._diff_summary()
        if diff_summary:
            inputs["diff_summary"] = diff_summary
        return inputs

    def _diff_summary(self) -> dict:
        """Collect a small real git diff summary when the task runs in a git worktree."""
        try:
            names = subprocess.run(
                ["git", "diff", "--name-only"],
                check=False,
                capture_output=True,
                text=True,
            )
            shortstat = subprocess.run(
                ["git", "diff", "--shortstat"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return {}
        if names.returncode != 0:
            return {}
        changed_files = [line for line in names.stdout.splitlines() if line.strip()]
        return {
            "changed_files": len(changed_files),
            "files": changed_files,
            "shortstat": shortstat.stdout.strip() if shortstat.returncode == 0 else "",
        }
