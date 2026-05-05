"""Policy controls for verify/review recovery loops."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityLoopPolicy:
    """Runtime policy for bounded verify/review retry and autofix hooks."""

    verify_retry_budget: int = 1
    review_retry_budget: int = 1
    auto_fix_attempts: int = 0
    hard_stop_on_critical: bool = True

    @classmethod
    def from_escalation(
        cls,
        escalation: dict[str, Any] | None = None,
        learning_feedback: dict[str, Any] | None = None,
    ) -> "QualityLoopPolicy":
        if not isinstance(escalation, dict):
            return cls().with_learning_feedback(learning_feedback)
        config = escalation.get("quality_loop")
        if not isinstance(config, dict):
            return cls().with_learning_feedback(learning_feedback)
        policy = cls(
            verify_retry_budget=_non_negative_int(
                config.get("verify_retry_budget"),
                cls.verify_retry_budget,
            ),
            review_retry_budget=_non_negative_int(
                config.get("review_retry_budget"),
                cls.review_retry_budget,
            ),
            auto_fix_attempts=_non_negative_int(
                config.get("auto_fix_attempts"),
                cls.auto_fix_attempts,
            ),
            hard_stop_on_critical=(
                config["hard_stop_on_critical"]
                if isinstance(config.get("hard_stop_on_critical"), bool)
                else cls.hard_stop_on_critical
            ),
        )
        return policy.with_learning_feedback(learning_feedback)

    def with_learning_feedback(self, learning_feedback: dict[str, Any] | None = None) -> "QualityLoopPolicy":
        """Let accepted proposal decisions influence future retry/autofix strategy."""
        if not isinstance(learning_feedback, dict):
            return self
        verify_budget = self.verify_retry_budget
        review_budget = self.review_retry_budget
        auto_fix_attempts = self.auto_fix_attempts
        for proposal in learning_feedback.get("accepted_proposals", []):
            if not isinstance(proposal, dict):
                continue
            title = str(proposal.get("title", ""))
            source = str(proposal.get("source", ""))
            if source == "repeated_failures" and "Verify" in title:
                verify_budget = max(verify_budget, self.verify_retry_budget + 1, 2)
                auto_fix_attempts = max(auto_fix_attempts, 1)
            if source in {"repeated_failures", "escalations"} and "Review" in title:
                review_budget = max(review_budget, self.review_retry_budget + 1, 2)
                auto_fix_attempts = max(auto_fix_attempts, 1)
        return QualityLoopPolicy(
            verify_retry_budget=verify_budget,
            review_retry_budget=review_budget,
            auto_fix_attempts=auto_fix_attempts,
            hard_stop_on_critical=self.hard_stop_on_critical,
        )

    def to_artifact(self) -> dict[str, Any]:
        return {
            "verify_retry_budget": self.verify_retry_budget,
            "review_retry_budget": self.review_retry_budget,
            "auto_fix_attempts": self.auto_fix_attempts,
            "hard_stop_on_critical": self.hard_stop_on_critical,
        }


def validate_quality_loop_config(config: Any) -> list[str]:
    """Return validation issues for a quality_loop policy block."""
    if config is None:
        return []
    if not isinstance(config, dict):
        return ["quality_loop must be a mapping"]

    issues: list[str] = []
    for key in ("verify_retry_budget", "review_retry_budget", "auto_fix_attempts"):
        value = config.get(key)
        if key in config and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            issues.append(f"quality_loop.{key} must be a non-negative integer")
    if "hard_stop_on_critical" in config and not isinstance(config["hard_stop_on_critical"], bool):
        issues.append("quality_loop.hard_stop_on_critical must be a boolean")
    return issues


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)
