"""Per-task token budget enforcement, sourced from the escalation policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TaskBudget:
    """Tracks accumulated token usage for a task against a policy ceiling.

    Built from the ``budget:`` section of the escalation policy. When that
    section is absent, enforcement is disabled and ``state()`` always
    returns ``"disabled"``.
    """

    max_total_tokens: int | None = None
    warn_ratio: float = 0.8
    on_exhausted: str = "pause"
    consumed_tokens: int = 0
    enabled: bool = False

    @classmethod
    def from_escalation(cls, escalation: dict[str, Any] | None) -> "TaskBudget":
        """Build a TaskBudget from the escalation policy dict.

        Parsing is lenient: any missing or malformed fields fall back to
        defaults, and a missing ``budget`` section disables enforcement.
        """
        if not isinstance(escalation, dict):
            return cls(enabled=False)

        budget_section = escalation.get("budget")
        if not isinstance(budget_section, dict):
            return cls(enabled=False)

        max_total_tokens = _optional_positive_int(budget_section.get("max_total_tokens"))

        warn_ratio = budget_section.get("warn_ratio", 0.8)
        try:
            warn_ratio = float(warn_ratio)
        except (TypeError, ValueError):
            warn_ratio = 0.8
        if warn_ratio < 0 or warn_ratio > 1:
            warn_ratio = 0.8

        on_exhausted = budget_section.get("on_exhausted", "pause")
        if on_exhausted not in ("pause", "warn"):
            on_exhausted = "pause"

        return cls(
            max_total_tokens=max_total_tokens,
            warn_ratio=warn_ratio,
            on_exhausted=on_exhausted,
            consumed_tokens=0,
            enabled=True,
        )

    def add_usage(self, usage: dict[str, Any] | None) -> None:
        """Accumulate ``total_tokens`` from a usage artifact dict.

        Defensive: anything that isn't a dict with a usable
        ``total_tokens`` value is silently ignored.
        """
        if not isinstance(usage, dict):
            return
        try:
            tokens = int(usage.get("total_tokens", 0) or 0)
        except (TypeError, ValueError):
            return
        if tokens > 0:
            self.consumed_tokens += tokens

    def add_phase_result_usage(self, artifacts: dict[str, Any] | None) -> None:
        """Extract and accumulate usage from a phase result's artifacts.

        Mirrors the traversal in ``Engine._log_phase_cost``: a direct
        ``dispatch_usage`` artifact, plus any nested graph-execution event
        usage under ``task_graph_execution.events[*].provider_result.usage``.
        """
        if not isinstance(artifacts, dict):
            return

        self.add_usage(artifacts.get("dispatch_usage"))

        graph_exec = artifacts.get("task_graph_execution", {})
        if isinstance(graph_exec, dict):
            events = graph_exec.get("events", [])
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    provider_result = event.get("provider_result", {})
                    if isinstance(provider_result, dict):
                        self.add_usage(provider_result.get("usage"))

    def state(self) -> str:
        """Return "disabled" | "ok" | "warning" | "exhausted"."""
        if not self.enabled or self.max_total_tokens is None:
            return "disabled"
        if self.consumed_tokens >= self.max_total_tokens:
            return "exhausted"
        if self.consumed_tokens >= self.warn_ratio * self.max_total_tokens:
            return "warning"
        return "ok"

    def to_artifact(self) -> dict[str, Any]:
        return {
            "enforcement": "enabled" if self.enabled else "disabled",
            "max_total_tokens": self.max_total_tokens,
            "warn_ratio": self.warn_ratio,
            "consumed_tokens": self.consumed_tokens,
            "state": self.state(),
            "on_exhausted": self.on_exhausted,
        }


def _optional_positive_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
