import sys
from pathlib import Path

from src.engine import Phase, PolicyPack
from src.phases.verify import VerifyHandler
from src.runtime import CommandRunner


def test_command_runner_respects_opt_in_execution(tmp_path: Path):
    runner = CommandRunner(execute_enabled=False, workdir=str(tmp_path))
    result = runner.run(f"{sys.executable} -c 'print(123)'")

    assert result.source == "declared_not_executed"
    assert result.succeeded is False
    assert result.duration_seconds == 0.0
    assert result.started_at == result.finished_at
    assert result.workdir == str(tmp_path)
    assert result.argv
    assert result.command_name == sys.executable


def test_command_runner_executes_when_enabled(tmp_path: Path):
    runner = CommandRunner(execute_enabled=True, workdir=str(tmp_path), timeout_seconds=5)
    result = runner.run(f"{sys.executable} -c 'print(123)'")

    assert result.source == "shell"
    assert result.succeeded is True
    assert "123" in result.output_tail
    assert result.duration_seconds is not None
    assert result.duration_seconds >= 0.0
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.workdir == str(tmp_path)
    assert result.timeout_seconds == 5
    assert result.argv
    assert result.command_name == sys.executable


def test_command_result_artifact_shape(tmp_path: Path):
    runner = CommandRunner(execute_enabled=True, workdir=str(tmp_path), timeout_seconds=5)
    result = runner.run(f"{sys.executable} -c 'import sys; sys.exit(7)'")
    artifact = result.to_artifact()

    assert artifact["exit_code"] == 7
    assert artifact["succeeded"] is False
    assert artifact["started_at"]
    assert artifact["finished_at"]
    assert artifact["duration_seconds"] >= 0.0
    assert artifact["workdir"] == str(tmp_path)
    assert artifact["timeout_seconds"] == 5
    assert artifact["argv"]
    assert artifact["command_name"] == sys.executable


def test_verify_handler_emits_richer_verification_evidence(tmp_path: Path):
    handler = VerifyHandler(
        PolicyPack(commands={"test": {"command": f"{sys.executable} -c 'print(123)'"}}),
        command_runner=CommandRunner(execute_enabled=True, workdir=str(tmp_path), timeout_seconds=5),
    )

    result = handler.execute(task=None, phase=Phase.VERIFY)

    assert result.outcome == "pass"
    assert result.evidence["command_declared"] is True
    assert result.evidence["command_executed"] is True
    assert result.evidence["command_succeeded"] is True
    assert result.evidence["verification_source"] == "shell"
    assert result.evidence["verification_summary"]["tests_count"] == 1
    assert result.artifacts["verification_summary"]["command_succeeded"] is True


def test_verify_handler_marks_retry_and_autofix_from_policy(tmp_path: Path):
    handler = VerifyHandler(
        PolicyPack(
            commands={"test": {"command": f"{sys.executable} -c 'import sys; sys.exit(7)'"}},
            escalation={"quality_loop": {"verify_retry_budget": 2, "auto_fix_attempts": 1}},
        ),
        command_runner=CommandRunner(execute_enabled=True, workdir=str(tmp_path), timeout_seconds=5),
    )

    result = handler.execute(task=None, phase=Phase.VERIFY)

    assert result.outcome == "fail"
    assert result.artifacts["quality_loop_policy"]["verify_retry_budget"] == 2
    assert result.artifacts["retry_recommended"] is True
    assert result.artifacts["auto_fix_allowed"] is True
