"""Policy controls for verify/review recovery loops."""
from __future__ import annotations

from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# GateEvidencePolicy: BRAINSTORM/PLAN confidence-gate thresholds, remediation
# copy, and retry-eligible phases, sourced from the `review` policy section.
# ---------------------------------------------------------------------------

# Defaults reproduce the values that used to be hardcoded as module-level
# constants in src/engine.py (_GATE_EVIDENCE_REMEDIATION, _GATE_RETRY_PHASES,
# and the inline 0.80/0.90 threshold literals). Policy packs that don't
# declare a gate_thresholds/gate_remediation/gate_retry_phases block in
# review.md get exactly this behavior — this refactor is a no-op for them.
_DEFAULT_GATE_THRESHOLDS: dict[str, float] = {
    "Brainstorm": 0.80,
    "Plan": 0.90,
}

_DEFAULT_GATE_RETRY_PHASES: frozenset[str] = frozenset({"Brainstorm", "Plan"})

_DEFAULT_GATE_REMEDIATION: dict[str, str] = {
    "alternative_approaches_considered": (
        "Brainstorm did not evaluate multiple approaches; ask the provider to set "
        "evidence.alternative_approaches_considered after considering at least three alternatives."
    ),
    "risks_identified": (
        "Brainstorm did not identify risks; ask the provider to set evidence.risks_identified "
        "after enumerating potential failure modes or concerns."
    ),
    "success_criteria_defined": (
        "Brainstorm has no explicit success criteria; ask the provider to set "
        "evidence.success_criteria_defined after articulating measurable acceptance conditions."
    ),
    "reversibility_assessed": (
        "Brainstorm did not assess how the change could be rolled back; ask the provider to set "
        "evidence.reversibility_assessed after considering reversibility."
    ),
    "checkpoint_list": (
        "Plan has no checkpoint list; the provider should return a sequenced step list and set "
        "evidence.checkpoint_list."
    ),
    "dependency_map": (
        "Plan has no dependency map; the provider should return outputs.checkpoints/dependencies "
        "and set evidence.dependency_map."
    ),
    "rollback_plan": (
        "Plan has no rollback plan; the provider should document a recovery procedure and set "
        "evidence.rollback_plan."
    ),
}


@dataclass(frozen=True)
class GateEvidencePolicy:
    """Runtime policy for confidence-gate thresholds, remediation copy, and retry-eligible phases.

    Mirrors ``QualityLoopPolicy.from_escalation`` but sources its data from the
    `review` policy-pack section (review.md) via a `gate_thresholds` /
    `gate_remediation` / `gate_retry_phases` block, instead of `escalation`.
    Phases are keyed by their ``Phase.value`` string (e.g. "Brainstorm", "Plan")
    so this module has no dependency on the engine's `Phase` enum.
    """

    thresholds: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_GATE_THRESHOLDS))
    remediation: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_GATE_REMEDIATION))
    retry_phases: frozenset[str] = field(default_factory=lambda: frozenset(_DEFAULT_GATE_RETRY_PHASES))

    def threshold_for(self, phase_value: str, default: float = 1.0) -> float:
        """Return the configured gate threshold for a phase, or `default` if unset."""
        return self.thresholds.get(phase_value, default)

    def is_retry_phase(self, phase_value: str) -> bool:
        """Whether the bounded gate-retry loop applies to this phase."""
        return phase_value in self.retry_phases

    def remediation_for(self, key: str) -> str | None:
        """Return the remediation message for a missing-evidence key, if any."""
        return self.remediation.get(key)

    @classmethod
    def from_review(cls, review: dict[str, Any] | None = None) -> "GateEvidencePolicy":
        if not isinstance(review, dict):
            return cls()

        thresholds = dict(_DEFAULT_GATE_THRESHOLDS)
        raw_thresholds = review.get("gate_thresholds")
        if isinstance(raw_thresholds, dict):
            for phase_value, value in raw_thresholds.items():
                parsed = _finite_float(value)
                if parsed is not None:
                    thresholds[str(phase_value)] = parsed

        remediation = dict(_DEFAULT_GATE_REMEDIATION)
        raw_remediation = review.get("gate_remediation")
        if isinstance(raw_remediation, dict):
            for key, message in raw_remediation.items():
                if isinstance(message, str) and message:
                    remediation[str(key)] = message

        raw_retry_phases = review.get("gate_retry_phases")
        if isinstance(raw_retry_phases, (list, tuple, set)) and raw_retry_phases:
            retry_phases = frozenset(str(p) for p in raw_retry_phases)
        else:
            retry_phases = frozenset(_DEFAULT_GATE_RETRY_PHASES)

        return cls(thresholds=thresholds, remediation=remediation, retry_phases=retry_phases)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return parsed
