from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    id: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    context_ref: str | None = None
    escalation_policy: str | None = None


@dataclass
class ExploreResult:
    messages: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecuteResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    success: bool = False


class Dispatcher(ABC):
    @abstractmethod
    def dispatch_explore(self, spec: TaskSpec) -> ExploreResult:
        raise NotImplementedError

    @abstractmethod
    def dispatch_execute(self, spec: TaskSpec) -> ExecuteResult:
        raise NotImplementedError


class NullDispatcher(Dispatcher):
    def dispatch_explore(self, spec: TaskSpec) -> ExploreResult:
        return ExploreResult()

    def dispatch_execute(self, spec: TaskSpec) -> ExecuteResult:
        return ExecuteResult()