from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class Phase(Enum):
    DISCOVER = "discover"
    DEFINE = "define"
    EXPLORE = "explore"
    EVALUATE = "evaluate"
    DECIDE = "decide"
    PLAN = "plan"
    DESIGN = "design"
    BUILD = "build"
    TEST = "test"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    IMPROVE = "improve"


class Complexity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PhaseResult:
    phase: Phase
    outcome: str
    iterations: int = 0
    decisions: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    task_id: str
    description: str
    complexity: Complexity = Complexity.MEDIUM
    phase_results: list[PhaseResult] = field(default_factory=list)
    current_phase: Phase | None = None


class Engine:
    def run_task(self, task: TaskContext) -> TaskContext:
        while task.current_phase is None or task.current_phase != Phase.IMPROVE:
            next_phase = self._next_phase(task)
            if next_phase is None:
                break
            self._execute_phase(task, next_phase)
        return task

    def _next_phase(self, task: TaskContext) -> Phase | None:
        if task.current_phase is None:
            return Phase.DISCOVER
        completed = {pr.phase for pr in task.phase_results}
        for phase in Phase:
            if phase not in completed:
                return phase
        return None

    def _execute_phase(self, task: TaskContext, phase: Phase) -> None:
        task.current_phase = phase
        result = PhaseResult(phase=phase, outcome="completed")
        task.phase_results.append(result)