"""Policy for the six Anthropic-inspired dynamic workflow patterns."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowPattern(str, Enum):
    CLASSIFY_AND_ACT = "classify_and_act"
    FANOUT_AND_SYNTHESIZE = "fanout_and_synthesize"
    ADVERSARIAL_VERIFICATION = "adversarial_verification"
    GENERATE_AND_FILTER = "generate_and_filter"
    TOURNAMENT = "tournament"
    LOOP_UNTIL_DONE = "loop_until_done"


_PATTERN_DEFAULTS: dict[str, dict[str, Any]] = {
    WorkflowPattern.CLASSIFY_AND_ACT: {},
    WorkflowPattern.FANOUT_AND_SYNTHESIZE: {"max_branches": 4},
    WorkflowPattern.ADVERSARIAL_VERIFICATION: {"verifier_count": 3, "pass_threshold": 2},
    WorkflowPattern.GENERATE_AND_FILTER: {"generator_count": 4, "min_score": 0.7},
    WorkflowPattern.TOURNAMENT: {"attempts": 4, "judge_rounds": 2},
    WorkflowPattern.LOOP_UNTIL_DONE: {"max_iterations": 5, "condition_key": "new_findings"},
}


@dataclass
class WorkflowPatternsPolicy:
    """Policy governing which workflow patterns are active and how they behave."""

    enabled_patterns: set[str] = field(default_factory=set)
    pattern_configs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def is_enabled(self, pattern: WorkflowPattern | str) -> bool:
        key = pattern.value if isinstance(pattern, WorkflowPattern) else str(pattern)
        return key in self.enabled_patterns

    def config_for(self, pattern: WorkflowPattern | str) -> dict[str, Any]:
        key = pattern.value if isinstance(pattern, WorkflowPattern) else str(pattern)
        defaults = dict(_PATTERN_DEFAULTS.get(key, {}))
        overrides = self.pattern_configs.get(key, {})
        return {**defaults, **overrides}

    @classmethod
    def from_policy_section(cls, section: dict[str, Any] | None) -> "WorkflowPatternsPolicy":
        """Parse a workflow_patterns policy section into a typed policy object."""
        if not isinstance(section, dict):
            return cls()

        patterns_raw = section.get("patterns", {})
        enabled: set[str] = set()
        configs: dict[str, dict[str, Any]] = {}

        if isinstance(patterns_raw, dict):
            for key, val in patterns_raw.items():
                if isinstance(val, dict):
                    if val.get("enabled", True):
                        enabled.add(key)
                    cfg = {k: v for k, v in val.items() if k != "enabled"}
                    if cfg:
                        configs[key] = cfg
                elif val is True:
                    enabled.add(key)
        elif isinstance(patterns_raw, list):
            for item in patterns_raw:
                if isinstance(item, str):
                    enabled.add(item)
                elif isinstance(item, dict):
                    name = item.get("name")
                    if name:
                        if item.get("enabled", True):
                            enabled.add(name)
                        cfg = {k: v for k, v in item.items() if k not in ("name", "enabled")}
                        if cfg:
                            configs[name] = cfg

        return cls(enabled_patterns=enabled, pattern_configs=configs)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "enabled_patterns": sorted(self.enabled_patterns),
            "pattern_configs": self.pattern_configs,
        }
