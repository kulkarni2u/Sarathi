"""Review phase handler."""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Any

try:
    from src.task_graph import graph_summary
    from src.runtime import QualityLoopPolicy, ReviewRunner
    from src.runtime.workspace_evidence import collect_review_context
    from src.review_data import find_diff_review, rejected_paths
except ImportError:
    from task_graph import graph_summary
    from runtime import QualityLoopPolicy, ReviewRunner
    from runtime.workspace_evidence import collect_review_context
    from review_data import find_diff_review, rejected_paths

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class ReviewHandler:
    """Perform code review and quality checks."""

    def __init__(self, policy_pack, dispatcher=None, review_runner: ReviewRunner | None = None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.review_runner = review_runner or ReviewRunner()

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import DispatchRequest, PhaseResult

        review_inputs = self._review_inputs(task)
        diff_summary = review_inputs.get("diff_summary")

        measured_changes = self._collect_build_workspace_evidence(task)
        workspace_root = os.environ.get("SARATHI_WORKDIR", os.getcwd())
        workspace_diff = collect_review_context(workspace_root)
        if measured_changes:
            review_inputs["measured_changes"] = measured_changes
        if workspace_diff.get("measured"):
            review_inputs["workspace_diff"] = workspace_diff

        diff_review = review_inputs.get("diff_review") or {}
        rejected_diff_paths = rejected_paths(diff_review)

        review_inputs_summary = {
            "measured_changes_present": bool(measured_changes),
            "diff_bytes": len((workspace_diff.get("diff") or "").encode("utf-8")),
            "diff_truncated": bool(workspace_diff.get("diff_truncated", False)),
            "diff_review_rejected_files": len(rejected_diff_paths),
        }

        # Attempt a provider-backed review dispatch if dispatcher is available
        dispatch_response = None
        if self.dispatcher is not None:
            build_artifact = self._build_artifact(task)
            rejection_note = (
                "\n\nA human reviewer already rejected these files in an earlier "
                "diff review pass: " + ", ".join(rejected_diff_paths) + ". Treat "
                "their notes in diff_review.decisions as findings that must be "
                "addressed before this can pass."
                if rejected_diff_paths
                else ""
            )
            dispatch_response = self.dispatcher.dispatch(
                DispatchRequest(
                    mode="execute",
                    task_id=task.task_id,
                    phase=phase.value,
                    prompt=(
                        f"Review the implementation for task: {task.description}\n\n"
                        "Evaluate against acceptance criteria, code quality, security, "
                        "and spec compliance. Provide structured findings.\n\n"
                        "Review the MEASURED diff (workspace_diff) and measured_changes "
                        "(workspace_delta / claim_reconciliation), not the builder's "
                        "self-reported summary. Set evidence.spec_met, "
                        "evidence.code_quality_acceptable, and evidence.no_blocking_issues "
                        "based on what was actually measured in the workspace."
                        + rejection_note
                    ),
                    inputs={
                        "task_description": task.description,
                        "build_result": build_artifact,
                        "diff_summary": diff_summary or {},
                        "acceptance_criteria": review_inputs.get("acceptance_criteria", []),
                        "measured_changes": measured_changes,
                        "workspace_diff": workspace_diff,
                        "diff_review": diff_review,
                    },
                    expected_outputs=["findings", "score", "outcome", "summary"],
                    constraints={"provider": "claude"},
                )
            )

        # Fallback: local ReviewRunner
        if dispatch_response is None or not dispatch_response.success:
            verdict = self.review_runner.review(evidence=review_inputs)
            review_artifact = verdict.to_artifact()
        else:
            review_artifact = dispatch_response.outputs.get("review_artifact", {})
            if not isinstance(review_artifact, dict) or "findings" not in review_artifact:
                review_artifact = self._dispatch_to_review_artifact(dispatch_response)

        quality_policy = QualityLoopPolicy.from_escalation(
            getattr(self.policy_pack, "escalation", {}) or {},
            learning_feedback=getattr(self.policy_pack, "learning_feedback", {}) or {},
        )
        has_critical = review_artifact.get("severity_counts", {}).get("critical", 0) > 0
        retry_recommended = (
            review_artifact.get("outcome", "fail") in {"escalate", "fail"}
            and quality_policy.review_retry_budget > 0
            and not (has_critical and quality_policy.hard_stop_on_critical)
        )
        auto_fix_allowed = retry_recommended and quality_policy.auto_fix_attempts > 0
        findings = review_artifact.get("findings", [])
        review_results = {
            finding["check"]: finding["passed"]
            for finding in findings
        }

        evidence = {
            "spec_compliance_checked": review_results.get("spec_compliance", False),
            "code_quality_reviewed": review_results.get("code_quality", False),
            "security_reviewed": review_results.get("security", False),
            "review_score_calculated": review_artifact.get("score", 0) >= 0,
            "review_summary": review_artifact.get("summary", {}),
            "severity_counts": review_artifact.get("severity_counts", {}),
            "failed_review_checks": review_artifact.get("totals", {}).get("failed", 0),
            "review_input_sources": sorted(review_inputs.keys()),
            "provider_review": dispatch_response is not None and dispatch_response.success,
            "retry_recommended": retry_recommended,
            "auto_fix_allowed": auto_fix_allowed,
            "diff_review_rejected_files": rejected_diff_paths,
        }

        artifacts: dict[str, Any] = {
            "review_results": review_results,
            "review_score": review_artifact.get("score", 0),
            "review_verdict": review_artifact,
            "review_summary": review_artifact.get("summary", {}),
            "review_inputs": review_inputs,
            "quality_loop_policy": quality_policy.to_artifact(),
            "retry_recommended": retry_recommended,
            "auto_fix_allowed": auto_fix_allowed,
            "review_inputs_summary": review_inputs_summary,
        }
        if dispatch_response is not None and dispatch_response.usage is not None:
            artifacts["dispatch_usage"] = dispatch_response.usage.to_artifact()

        return PhaseResult(
            phase=phase,
            outcome=review_artifact.get("outcome", "fail"),
            evidence=evidence,
            artifacts=artifacts,
        )

    def _build_artifact(self, task: "TaskContext") -> dict[str, Any]:
        """Extract the build result from the most recent Build phase result."""
        for pr in reversed(task.phase_results):
            if pr.phase.value == "Build":
                return {
                    "outputs": pr.artifacts.get("provider_result", {}),
                    "changed_files": pr.evidence.get("changed_files", []),
                    "graph_summary": pr.artifacts.get("task_graph_execution", {}),
                }
        return {}

    def _collect_build_workspace_evidence(self, task: "TaskContext") -> dict[str, Any]:
        """Collect measured workspace evidence from the most recent Build phase result.

        Searches the Build phase result's artifacts for dispatch-attached
        ``workspace_delta`` / ``claim_reconciliation`` /
        ``workspace_unchanged_on_success`` evidence (top-level dispatch
        evidence first, then per-node ``provider_result.evidence`` entries
        from ``task_graph_execution.events``, most recent first).

        Returns ``{}`` when no Build phase result or no measured evidence is
        found. Never raises — defensive about missing/unexpected shapes.
        """
        if task is None:
            return {}
        phase_results = getattr(task, "phase_results", None)
        if not phase_results:
            return {}

        for pr in reversed(phase_results):
            phase = getattr(pr, "phase", None)
            phase_value = getattr(phase, "value", phase)
            if phase_value != "Build":
                continue

            artifacts = getattr(pr, "artifacts", None)
            if not isinstance(artifacts, dict):
                return {}

            collected: dict[str, Any] = {}

            # Top-level dispatch evidence, if ever attached directly to the
            # Build phase result's artifacts.
            top_level_evidence = artifacts.get("dispatch_evidence")
            if isinstance(top_level_evidence, dict):
                self._merge_workspace_evidence(collected, top_level_evidence)

            # Per-node provider results from graph execution, most recent first.
            graph_execution = artifacts.get("task_graph_execution")
            if isinstance(graph_execution, dict):
                events = graph_execution.get("events")
                if isinstance(events, list):
                    for event in reversed(events):
                        if not isinstance(event, dict):
                            continue
                        provider_result = event.get("provider_result")
                        if not isinstance(provider_result, dict):
                            continue
                        node_evidence = provider_result.get("evidence")
                        if isinstance(node_evidence, dict):
                            self._merge_workspace_evidence(collected, node_evidence)
                        if collected:
                            break

            return collected

        return {}

    @staticmethod
    def _merge_workspace_evidence(collected: dict[str, Any], evidence: dict[str, Any]) -> None:
        """Copy known workspace-evidence keys from ``evidence`` into ``collected``."""
        for key in ("workspace_delta", "claim_reconciliation", "workspace_unchanged_on_success"):
            if key in evidence and key not in collected:
                collected[key] = evidence[key]

    def _dispatch_to_review_artifact(self, response) -> dict[str, Any]:
        """Convert a raw dispatch response into a review artifact dict."""
        outputs = response.outputs if hasattr(response, "outputs") else {}
        findings = []
        for key, value in outputs.items():
            if isinstance(value, dict) and "passed" in value:
                findings.append({
                    "check": key,
                    "passed": bool(value["passed"]),
                    "severity": value.get("severity", "info"),
                    "message": value.get("message", str(value)),
                })
        score = sum(1 for f in findings if f["passed"]) / max(len(findings), 1)
        failed = sum(1 for f in findings if not f["passed"])
        return {
            "findings": findings,
            "score": round(score, 2),
            "outcome": "pass" if failed == 0 else "escalate",
            "summary": {"total": len(findings), "passed": len(findings) - failed, "failed": failed},
            "severity_counts": {"critical": 0, "major": failed, "minor": 0},
            "totals": {"total": len(findings), "passed": len(findings) - failed, "failed": failed},
        }

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
        diff_review = find_diff_review(task)
        if diff_review:
            inputs["diff_review"] = diff_review
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
