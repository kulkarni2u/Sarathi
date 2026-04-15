from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Pattern:
    name: str
    first_seen: datetime
    validated_in: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    best_seen: str | None = None
    trend: str = "stable"
    evidence_refs: list[str] = field(default_factory=list)
    promotion_date: datetime | None = None


@dataclass
class EvolveBaseline:
    patterns: list[Pattern] = field(default_factory=list)
    total_patterns: int = 0
    promoted_this_month: int = 0
    deprecated_this_month: int = 0


class Evolver:
    PASS_GATE = 0.8

    def detect_pattern(self, baseline: EvolveBaseline, pattern_name: str) -> Pattern | None:
        for pattern in baseline.patterns:
            if pattern.name == pattern_name:
                return pattern
        return None

    def should_promote(self, pattern: Pattern) -> bool:
        return pattern.pass_rate >= self.PASS_GATE

    def apply_evolution(self, baseline: EvolveBaseline, pattern: Pattern) -> EvolveBaseline:
        baseline.patterns.append(pattern)
        baseline.total_patterns = len(baseline.patterns)
        return baseline