import pytest
from src.engine import Engine, Phase, Complexity, TaskContext, PhaseResult


def test_engine_initialization():
    engine = Engine()
    assert engine is not None


def test_route_phase_sets_complexity():
    task = TaskContext(
        task_id="test-1",
        description="Test task",
        complexity=Complexity.HIGH,
    )
    engine = Engine()
    result = engine.run_task(task)
    assert result.complexity == Complexity.HIGH
    assert len(result.phase_results) == 12


def test_phase_log_format():
    task = TaskContext(
        task_id="test-2",
        description="Test task",
        complexity=Complexity.LOW,
    )
    engine = Engine()
    engine.run_task(task)
    assert len(task.phase_results) == 12
    for pr in task.phase_results:
        assert pr.phase in Phase
        assert pr.outcome == "completed"