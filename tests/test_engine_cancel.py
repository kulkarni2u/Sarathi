"""Tests for cooperative cancellation and task-level timeout in the engine."""
import json
from pathlib import Path

from src.engine import Complexity, Engine, Phase, TaskContext


def _build_engine(tmp_path: Path) -> Engine:
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = engine.persistence.__class__(str(tmp_path / "tasks"))
    return engine


def _task(task_id: str) -> TaskContext:
    return TaskContext(
        task_id=task_id,
        description="Test task",
        complexity=Complexity.LOW,
    )


def test_run_task_default_runs_to_completion(tmp_path: Path):
    """No kwargs: behavior is unchanged, current_phase is None, no stop_reason."""
    engine = _build_engine(tmp_path)
    task = _task("cancel-default")

    result = engine.run_task(task)

    assert result.current_phase is None
    assert getattr(result, "stop_reason", None) is None


def test_cancel_check_true_immediately_stops_before_first_phase(tmp_path: Path):
    engine = _build_engine(tmp_path)
    task = _task("cancel-immediate")

    result = engine.run_task(task, cancel_check=lambda: True)

    assert result.current_phase is not None
    assert result.current_phase == Phase.ROUTE
    assert result.stop_reason == "cancelled"
    assert result.phase_results == []

    # A normal resume (no cancel) afterwards completes the task.
    resumed = engine.resume_task(result)
    assert resumed.current_phase is None
    assert getattr(resumed, "stop_reason", None) is None


def test_cancel_check_trips_after_second_phase_is_resumable(tmp_path: Path):
    engine = _build_engine(tmp_path)
    task = _task("cancel-partway")

    calls = {"n": 0}

    def cancel_check() -> bool:
        calls["n"] += 1
        # First check (before ROUTE) -> False, runs ROUTE.
        # Second check (before BRAINSTORM) -> True, stop.
        return calls["n"] >= 2

    result = engine.run_task(task, cancel_check=cancel_check)

    assert result.stop_reason == "cancelled"
    assert result.current_phase == Phase.BRAINSTORM
    assert len(result.phase_results) == 1
    assert result.phase_results[0].phase == Phase.ROUTE

    # Resumable: a normal resume (no cancel) completes the task.
    resumed = engine.resume_task(result)
    assert resumed.current_phase is None
    assert getattr(resumed, "stop_reason", None) is None
    assert Phase.LEARN in resumed.get_completed_phases()


def test_task_timeout_stops_early_with_timeout_reason(tmp_path: Path, monkeypatch):
    """A deadline already passed after the first phase boundary stops the run."""
    engine = _build_engine(tmp_path)
    task = _task("cancel-timeout")

    # Counter-based monotonic clock: first call establishes the deadline
    # (t=0 -> deadline = task_timeout), subsequent calls jump past it.
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        value = clock["t"]
        clock["t"] += 1000.0
        return value

    monkeypatch.setattr("src.engine.time.monotonic", fake_monotonic)

    result = engine.run_task(task, task_timeout=10.0)

    assert result.stop_reason == "timeout"
    assert result.current_phase is not None
    # Stopped at the first phase boundary check, before any phase executed.
    assert result.phase_results == []
    assert result.current_phase == Phase.ROUTE


def test_resume_task_cancel_and_timeout_mirror_run_task(tmp_path: Path):
    engine = _build_engine(tmp_path)
    task = _task("resume-cancel")

    # First, run far enough to have phase_results so resume_task doesn't
    # just delegate back to run_task.
    calls = {"n": 0}

    def cancel_first(_=None) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    paused = engine.run_task(task, cancel_check=cancel_first)
    assert paused.stop_reason == "cancelled"
    assert len(paused.phase_results) == 1

    # Resume with a cancel_check that trips immediately.
    resumed = engine.resume_task(paused, cancel_check=lambda: True)

    assert resumed.stop_reason == "cancelled"
    assert resumed.current_phase is not None
    assert resumed.current_phase == Phase.BRAINSTORM
    assert len(resumed.phase_results) == 1

    # A clean resume afterwards completes the task.
    final = engine.resume_task(resumed)
    assert final.current_phase is None
    assert getattr(final, "stop_reason", None) is None


def test_persisted_task_does_not_carry_stop_reason(tmp_path: Path):
    """stop_reason is transient (not a dataclass field) and must not round-trip."""
    engine = _build_engine(tmp_path)
    task = _task("cancel-persist")

    result = engine.run_task(task, cancel_check=lambda: True)
    assert result.stop_reason == "cancelled"

    task_file = engine.persistence.storage_path / f"{result.task_id}.json"
    data = json.loads(task_file.read_text())
    assert "stop_reason" not in data

    reloaded = engine.persistence.load_task(result.task_id)
    assert reloaded is not None
    assert getattr(reloaded, "stop_reason", None) is None
