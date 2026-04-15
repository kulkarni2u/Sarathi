import pytest
from src.dispatch import NullDispatcher, TaskSpec


def test_null_dispatcher_execute():
    dispatcher = NullDispatcher()
    spec = TaskSpec(id="test", description="test spec")
    result = dispatcher.dispatch_execute(spec)
    assert result.success is False
    assert result.outputs == {}


def test_task_spec_fields():
    spec = TaskSpec(
        id="task-1",
        description="Test task",
        inputs={"key": "value"},
        expected_outputs={"result": "expected"},
    )
    assert spec.id == "task-1"
    assert spec.inputs == {"key": "value"}
    assert spec.expected_outputs == {"result": "expected"}