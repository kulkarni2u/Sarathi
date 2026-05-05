"""Policy controls for task graph execution."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphExecutionPolicy:
    """Runtime policy for graph scheduling, retry, and pause behavior."""

    step_limit: int | None = None
    max_retries: int = 2
    auto_retry_failed_nodes: bool = True
    auto_schedule_ready_nodes: bool = False
    pause_on_incomplete_graph: bool = True
    pause_on_failed_node: bool = True
    require_human_after_retries: bool = True

    @classmethod
    def from_policy_sections(
        cls,
        task_tracking: dict[str, Any] | None = None,
        escalation: dict[str, Any] | None = None,
        *,
        use_env_overrides: bool = True,
    ) -> "GraphExecutionPolicy":
        """Build graph execution policy from compiled policy sections."""
        values: dict[str, Any] = {}
        escalation_graph = _graph_config(escalation)
        task_tracking_graph = _graph_config(task_tracking)
        values.update(escalation_graph)
        values.update(task_tracking_graph)

        policy = cls(
            step_limit=_optional_int(values.get("step_limit"), cls.step_limit),
            max_retries=_int(values.get("max_retries"), cls.max_retries),
            auto_retry_failed_nodes=_bool(
                values.get("auto_retry_failed_nodes"),
                cls.auto_retry_failed_nodes,
            ),
            auto_schedule_ready_nodes=_bool(
                values.get("auto_schedule_ready_nodes"),
                cls.auto_schedule_ready_nodes,
            ),
            pause_on_incomplete_graph=_bool(
                values.get("pause_on_incomplete_graph"),
                cls.pause_on_incomplete_graph,
            ),
            pause_on_failed_node=_bool(
                values.get("pause_on_failed_node"),
                cls.pause_on_failed_node,
            ),
            require_human_after_retries=_bool(
                values.get("require_human_after_retries"),
                cls.require_human_after_retries,
            ),
        )
        return policy.with_env_overrides() if use_env_overrides else policy

    def with_env_overrides(self) -> "GraphExecutionPolicy":
        """Apply explicit developer/test environment overrides."""
        step_limit = self.step_limit
        step_limit_env = os.environ.get("SARATHI_GRAPH_STEP_LIMIT")
        if step_limit_env is not None:
            step_limit = _optional_int(step_limit_env, step_limit)

        max_retries = self.max_retries
        max_retries_env = os.environ.get("SARATHI_GRAPH_MAX_RETRIES")
        if max_retries_env is not None:
            max_retries = _int(max_retries_env, max_retries)

        return GraphExecutionPolicy(
            step_limit=step_limit,
            max_retries=max_retries,
            auto_retry_failed_nodes=self.auto_retry_failed_nodes,
            auto_schedule_ready_nodes=self.auto_schedule_ready_nodes,
            pause_on_incomplete_graph=self.pause_on_incomplete_graph,
            pause_on_failed_node=self.pause_on_failed_node,
            require_human_after_retries=self.require_human_after_retries,
        )

    def to_artifact(self) -> dict[str, Any]:
        return {
            "step_limit": self.step_limit,
            "max_retries": self.max_retries,
            "auto_retry_failed_nodes": self.auto_retry_failed_nodes,
            "auto_schedule_ready_nodes": self.auto_schedule_ready_nodes,
            "pause_on_incomplete_graph": self.pause_on_incomplete_graph,
            "pause_on_failed_node": self.pause_on_failed_node,
            "require_human_after_retries": self.require_human_after_retries,
        }


def validate_graph_execution_config(config: Any) -> list[str]:
    """Return validation issues for a graph_execution policy block."""
    if config is None:
        return []
    if not isinstance(config, dict):
        return ["graph_execution must be a mapping"]

    issues: list[str] = []
    if "step_limit" in config and config["step_limit"] is not None:
        issues.extend(_validate_non_negative_int("graph_execution.step_limit", config["step_limit"]))
    if "max_retries" in config:
        issues.extend(_validate_non_negative_int("graph_execution.max_retries", config["max_retries"]))

    for key in (
        "auto_retry_failed_nodes",
        "auto_schedule_ready_nodes",
        "pause_on_incomplete_graph",
        "pause_on_failed_node",
        "require_human_after_retries",
    ):
        if key in config and not isinstance(config[key], bool):
            issues.append(f"graph_execution.{key} must be a boolean")
    return issues


def _graph_config(section: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    value = section.get("graph_execution")
    return value if isinstance(value, dict) else {}


def _optional_int(value: Any, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _validate_non_negative_int(name: str, value: Any) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return [f"{name} must be a non-negative integer"]
    return []
