"""Structured learning artifacts for the Learn phase."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable


@dataclass
class LearningRecord:
    """Persistable summary of what Sarathi learned from a task run."""

    task_id: str
    complexity: str
    generated_at: str
    summary: str
    lessons: list[str] = field(default_factory=list)
    repeated_failures: list[dict[str, Any]] = field(default_factory=list)
    provider_failures: list[dict[str, Any]] = field(default_factory=list)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    iteration_hotspots: list[dict[str, Any]] = field(default_factory=list)
    phase_outcomes: list[dict[str, Any]] = field(default_factory=list)

    def to_artifact(self) -> dict[str, Any]:
        """Return a JSON-serializable artifact payload."""
        return {
            "task_id": self.task_id,
            "complexity": self.complexity,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "lessons": self.lessons,
            "repeated_failures": self.repeated_failures,
            "provider_failures": self.provider_failures,
            "escalations": self.escalations,
            "iteration_hotspots": self.iteration_hotspots,
            "phase_outcomes": self.phase_outcomes,
        }


class LearningStore:
    """Build structured learning artifacts and preserve prior learn history."""

    def load_history(self, phase_results: Iterable[Any]) -> list[LearningRecord]:
        """Extract prior learning records from already-recorded phase results."""
        history: list[LearningRecord] = []
        for result in phase_results:
            artifacts = getattr(result, "artifacts", {}) or {}
            record_artifact = artifacts.get("learning_record")
            if isinstance(record_artifact, dict):
                history.append(self._record_from_artifact(record_artifact))
                continue

            legacy_lessons = artifacts.get("lessons_learned")
            if isinstance(legacy_lessons, list) and legacy_lessons:
                history.append(
                    LearningRecord(
                        task_id=artifacts.get("task_id", getattr(result, "phase", "unknown")),
                        complexity=str(artifacts.get("complexity", "unknown")),
                        generated_at=str(artifacts.get("generated_at", datetime.now().isoformat())),
                        summary="Imported legacy learn artifact",
                        lessons=[str(lesson) for lesson in legacy_lessons],
                    )
                )
        return history

    def build_record(self, task: Any) -> LearningRecord:
        """Summarize phase results into a production-shaped learning record."""
        phase_outcomes: list[dict[str, Any]] = []
        failure_counts: Counter[str] = Counter()
        provider_failure_counts: Counter[tuple[str, str]] = Counter()
        escalation_counts: Counter[str] = Counter()
        iteration_hotspots: list[dict[str, Any]] = []

        for result in getattr(task, "phase_results", []):
            phase_name = self._phase_name(getattr(result, "phase", "unknown"))
            outcome = str(getattr(result, "outcome", "unknown"))
            iterations = int(getattr(result, "iterations", 0) or 0)
            phase_outcomes.append(
                {
                    "phase": phase_name,
                    "outcome": outcome,
                    "iterations": iterations,
                    "error": getattr(result, "error", None),
                }
            )
            if outcome == "fail":
                failure_counts[phase_name] += 1
                provider_name = self._provider_name(getattr(result, "artifacts", {}) or {})
                if provider_name:
                    provider_failure_counts[(phase_name, provider_name)] += 1
            if outcome == "escalate":
                escalation_counts[phase_name] += 1
            if iterations > 1:
                iteration_hotspots.append({"phase": phase_name, "iterations": iterations})

        repeated_failures = [
            {"phase": phase, "count": count}
            for phase, count in sorted(failure_counts.items())
        ]
        provider_failures = [
            {"phase": phase, "provider": provider, "count": count}
            for (phase, provider), count in sorted(provider_failure_counts.items())
        ]
        escalations = [
            {"phase": phase, "count": count}
            for phase, count in sorted(escalation_counts.items())
        ]
        iteration_hotspots.sort(key=lambda item: (-item["iterations"], item["phase"]))

        lessons = self._derive_lessons(
            repeated_failures=repeated_failures,
            provider_failures=provider_failures,
            escalations=escalations,
            iteration_hotspots=iteration_hotspots,
            complexity=self._complexity_value(getattr(task, "complexity", "unknown")),
        )
        summary = self._summarize(
            repeated_failures=repeated_failures,
            escalations=escalations,
            iteration_hotspots=iteration_hotspots,
        )

        return LearningRecord(
            task_id=str(getattr(task, "task_id", "unknown")),
            complexity=self._complexity_value(getattr(task, "complexity", "unknown")),
            generated_at=datetime.now().isoformat(),
            summary=summary,
            lessons=lessons,
            repeated_failures=repeated_failures,
            provider_failures=provider_failures,
            escalations=escalations,
            iteration_hotspots=iteration_hotspots,
            phase_outcomes=phase_outcomes,
        )

    def build_artifacts(self, task: Any) -> dict[str, Any]:
        """Return the Learn phase artifact payload including compatibility fields."""
        history = self.load_history(getattr(task, "phase_results", []))
        record = self.build_record(task)
        history_artifacts = [item.to_artifact() for item in history] + [record.to_artifact()]
        return {
            "learning_record": record.to_artifact(),
            "learning_history": history_artifacts,
            "learning_summary": record.summary,
            "lessons_learned": record.lessons,
            "patterns_updated": bool(record.lessons or record.repeated_failures or record.escalations),
        }

    def _derive_lessons(
        self,
        *,
        repeated_failures: list[dict[str, Any]],
        provider_failures: list[dict[str, Any]],
        escalations: list[dict[str, Any]],
        iteration_hotspots: list[dict[str, Any]],
        complexity: str,
    ) -> list[str]:
        lessons: list[str] = []

        for failure in repeated_failures:
            phase = failure["phase"]
            count = failure["count"]
            lessons.append(f"Phase {phase} failed {count} time(s) - investigate root cause before repeating")

        for provider_failure in provider_failures:
            phase = provider_failure["phase"]
            provider = provider_failure["provider"]
            count = provider_failure["count"]
            lessons.append(
                f"Provider {provider} failed {count} time(s) in {phase} - consider a routing fallback"
            )

        for escalation in escalations:
            phase = escalation["phase"]
            count = escalation["count"]
            lessons.append(f"Phase {phase} escalated {count} time(s) - tighten criteria or reduce scope")

        for hotspot in iteration_hotspots:
            phase = hotspot["phase"]
            iterations = hotspot["iterations"]
            lessons.append(f"Phase {phase} required {iterations} iterations - capture a reusable optimization")

        if not repeated_failures:
            lessons.append("Task completed without repeated failure patterns")
        else:
            lessons.append("Task recorded failures - fix root causes before repeating the same pattern")

        lessons.append(f"Complexity classified as {complexity}")
        return lessons

    def _summarize(
        self,
        *,
        repeated_failures: list[dict[str, Any]],
        escalations: list[dict[str, Any]],
        iteration_hotspots: list[dict[str, Any]],
    ) -> str:
        if repeated_failures:
            top_failure = repeated_failures[0]
            return (
                f"Repeated failure pattern detected in {top_failure['phase']} "
                f"({top_failure['count']} occurrence(s))."
            )
        if escalations:
            top_escalation = escalations[0]
            return (
                f"Escalation pattern detected in {top_escalation['phase']} "
                f"({top_escalation['count']} occurrence(s))."
            )
        if iteration_hotspots:
            hotspot = iteration_hotspots[0]
            return (
                f"Execution was stable, but {hotspot['phase']} needed "
                f"{hotspot['iterations']} iterations."
            )
        return "Execution was stable with no repeated failures or escalations."

    def _record_from_artifact(self, artifact: dict[str, Any]) -> LearningRecord:
        return LearningRecord(
            task_id=str(artifact.get("task_id", "unknown")),
            complexity=str(artifact.get("complexity", "unknown")),
            generated_at=str(artifact.get("generated_at", datetime.now().isoformat())),
            summary=str(artifact.get("summary", "")),
            lessons=[str(lesson) for lesson in artifact.get("lessons", [])],
            repeated_failures=list(artifact.get("repeated_failures", [])),
            provider_failures=list(artifact.get("provider_failures", [])),
            escalations=list(artifact.get("escalations", [])),
            iteration_hotspots=list(artifact.get("iteration_hotspots", [])),
            phase_outcomes=list(artifact.get("phase_outcomes", [])),
        )

    def _complexity_value(self, complexity: Any) -> str:
        return str(getattr(complexity, "value", complexity))

    def _phase_name(self, phase: Any) -> str:
        return str(getattr(phase, "value", phase))

    def _provider_name(self, artifacts: dict[str, Any]) -> str | None:
        if not isinstance(artifacts, dict):
            return None
        dispatch_artifacts = artifacts.get("dispatch_artifacts")
        if isinstance(dispatch_artifacts, dict):
            provider = dispatch_artifacts.get("provider")
            if isinstance(provider, str) and provider:
                return provider
        provider_result = artifacts.get("provider_result")
        if isinstance(provider_result, dict):
            nested = provider_result.get("artifacts")
            if isinstance(nested, dict):
                provider = nested.get("provider")
                if isinstance(provider, str) and provider:
                    return provider
        return None
