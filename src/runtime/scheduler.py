"""Reusable task-graph scheduler outside any single lifecycle phase."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph_executor import GraphExecutionEvent, TaskGraphExecutor


@dataclass
class SchedulerRun:
    """Result of scheduling graph work units."""

    phase: str
    graph_state: dict[str, Any]
    events: list[GraphExecutionEvent]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "graph_state": self.graph_state,
            "events": [event.to_artifact() for event in self.events],
        }


class TaskScheduler:
    """Phase-independent scheduler for ready task-graph work units."""

    def __init__(self, dispatcher=None):
        self.dispatcher = dispatcher

    def run_ready(
        self,
        graph: dict[str, Any],
        *,
        phase: str = "Build",
        max_nodes: int | None = None,
        harness_config: Any = None,
    ) -> SchedulerRun:
        executor = TaskGraphExecutor(dispatcher=self.dispatcher, dispatch_phase=phase)
        result = executor.execute_some(graph, max_nodes=max_nodes, harness_config=harness_config)
        return SchedulerRun(phase=phase, graph_state=result.graph_state, events=result.events)
