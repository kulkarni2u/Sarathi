"""Verify phase handler."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from src.runtime import CommandRunner, QualityLoopPolicy
except ImportError:
    from runtime import CommandRunner, QualityLoopPolicy

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


class VerifyHandler:
    """Run verification checks and tests.

    Outcomes are derived only from real signals:
      pass        — the declared test command executed and succeeded
      fail        — the declared test command executed and failed (or errored)
      unverified  — no test command is declared (or execution is disabled),
                    so nothing was actually verified
    """

    def __init__(self, policy_pack, dispatcher=None, command_runner: CommandRunner | None = None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher
        self.command_runner = command_runner or CommandRunner()

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        verification_results = self._run_verification()
        command_result = verification_results.get("command_result", {}) or {}
        command_executed = command_result.get("source") == "shell"
        command_succeeded = command_result.get("succeeded")

        if command_executed:
            outcome = "pass" if command_succeeded else "fail"
        elif verification_results.get("verification_source") == "shell_error":
            outcome = "fail"
        else:
            outcome = "unverified"

        quality_policy = QualityLoopPolicy.from_escalation(
            getattr(self.policy_pack, "escalation", {}) or {},
            learning_feedback=getattr(self.policy_pack, "learning_feedback", {}) or {},
        )
        retry_recommended = outcome == "fail" and quality_policy.verify_retry_budget > 0

        evidence = {
            "tests_executed": command_executed,
            "verified": outcome == "pass",
            "verification_source": verification_results.get("verification_source"),
            "verification_summary": verification_results.get("summary", {}),
            "command_declared": bool(verification_results.get("declared_test_command")),
            "command_executed": command_executed,
            "command_succeeded": command_succeeded,
            "command_duration_seconds": command_result.get("duration_seconds"),
            "retry_recommended": retry_recommended,
            "auto_fix_allowed": retry_recommended and quality_policy.auto_fix_attempts > 0,
        }

        return PhaseResult(
            phase=phase,
            outcome=outcome,
            evidence=evidence,
            artifacts={
                "verification_results": verification_results,
                "verification_summary": verification_results.get("summary", {}),
                "quality_loop_policy": quality_policy.to_artifact(),
                "retry_recommended": retry_recommended,
                "auto_fix_allowed": retry_recommended and quality_policy.auto_fix_attempts > 0,
            },
        )

    def _run_verification(self) -> dict[str, Any]:
        commands_policy = getattr(self.policy_pack, "commands", {}) or {}
        test_cfg = commands_policy.get("test")
        cmd: str | None = None
        if isinstance(test_cfg, dict):
            cmd = test_cfg.get("command")

        # No fabricated numbers: coverage/lint stay None unless a real tool
        # produced them. verification_source records what actually happened.
        base: dict[str, Any] = {
            "declared_test_command": cmd,
            "tests": [],
            "coverage": None,
            "lint_results": None,
            "security_scan": None,
            "verification_source": "none",
        }

        if cmd:
            command_result = self.command_runner.run(cmd)
            base["command_result"] = command_result.to_artifact()
            if command_result.source == "declared_not_executed":
                base["verification_source"] = "declared_not_executed"
                base["note"] = command_result.error
            elif command_result.source == "shell":
                base["verification_source"] = "shell"
                base["exit_code"] = command_result.exit_code
                base["tests"] = ["declared_command"]
                base["output_tail"] = command_result.output_tail
            elif command_result.source == "shell_error":
                base["verification_source"] = "shell_error"
                base["shell_error"] = command_result.error
                base["tests"] = []

        command_artifact = base.get("command_result", {})
        base["summary"] = {
            "generated_at": command_artifact.get("finished_at") or command_artifact.get("started_at"),
            "verification_source": base["verification_source"],
            "declared_command_present": bool(cmd),
            "command_executed": command_artifact.get("source") == "shell",
            "command_succeeded": command_artifact.get("succeeded"),
            "tests_count": len(base.get("tests", [])),
            "coverage": base.get("coverage"),
            "duration_seconds": command_artifact.get("duration_seconds", 0.0),
        }

        return base
