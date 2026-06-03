"""Escalation bundle artifacts for blocked or failed work."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from typing import Any


@dataclass
class EscalationBundle:
    """Compact case file for work that needs attention."""

    task_id: str
    phase: str
    reason: str
    recommended_action: str
    graph_node: dict[str, Any] | None = None
    verification_summary: dict[str, Any] = field(default_factory=dict)
    review_summary: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def to_artifact(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "graph_node": self.graph_node,
            "verification_summary": self.verification_summary,
            "review_summary": self.review_summary,
            "artifact_refs": self.artifact_refs,
            "generated_at": self.generated_at,
        }


class EscalationBundleBuilder:
    """Build escalation bundles from task phase artifacts."""

    def build_for_phase(
        self,
        *,
        task: Any,
        phase: str,
        reason: str,
        graph_node: dict[str, Any] | None = None,
        recommended_action: str | None = None,
    ) -> EscalationBundle:
        verification_summary = self._latest_artifact(task, "verification_summary")
        review_summary = self._latest_artifact(task, "review_summary")
        artifact_refs = [
            ref
            for result in getattr(task, "phase_results", [])
            for ref in getattr(result, "artifact_refs", [])
        ]
        return EscalationBundle(
            task_id=str(getattr(task, "task_id", "unknown")),
            phase=phase,
            reason=reason,
            graph_node=graph_node,
            verification_summary=verification_summary,
            review_summary=review_summary,
            artifact_refs=artifact_refs,
            recommended_action=recommended_action or self._recommend(reason, graph_node),
        )

    def _latest_artifact(self, task: Any, key: str) -> dict[str, Any]:
        for result in reversed(getattr(task, "phase_results", [])):
            artifact = getattr(result, "artifacts", {}).get(key)
            if isinstance(artifact, dict):
                return artifact
        return {}

    def _recommend(self, reason: str, graph_node: dict[str, Any] | None) -> str:
        if graph_node and graph_node.get("status") == "waiting_human":
            return "Inspect the failed graph node, apply a fix, then resume the task."
        if graph_node and graph_node.get("status") == "failed":
            return "Review the node failure evidence and retry or adjust the implementation."
        if "verify" in reason.lower():
            return "Inspect verification evidence, fix the failing checks, then resume."
        return "Inspect the evidence bundle, resolve the blocker, then resume."
