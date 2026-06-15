"""Command execution runtime for verification and build phases."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

try:
    from .sandbox import build_sandbox_executor
except ImportError:  # pragma: no cover - direct module import fallback
    from sandbox import build_sandbox_executor

if TYPE_CHECKING:
    from .sandbox import SandboxExecutor


@dataclass
class CommandResult:
    """Structured result from executing a command."""

    command: str
    source: str
    exit_code: int | None = None
    output_tail: str = ""
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    workdir: str | None = None
    timeout_seconds: int | None = None
    argv: list[str] | None = None
    executor: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and self.error is None

    @property
    def command_name(self) -> str | None:
        if self.argv:
            return self.argv[0]
        return None

    def to_artifact(self) -> dict:
        return {
            "command": self.command,
            "source": self.source,
            "exit_code": self.exit_code,
            "output_tail": self.output_tail,
            "error": self.error,
            "succeeded": self.succeeded,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "workdir": self.workdir,
            "timeout_seconds": self.timeout_seconds,
            "argv": self.argv or [],
            "command_name": self.command_name,
            "executor": self.executor,
        }


class CommandRunner:
    """Runs declared policy commands with safe opt-in semantics."""

    def __init__(
        self,
        execute_enabled: bool | None = None,
        workdir: str | None = None,
        timeout_seconds: int | None = None,
        sandbox: "SandboxExecutor | None" = None,
    ):
        self.execute_enabled = (
            os.environ.get("SARATHI_EXEC_COMMANDS") == "1"
            if execute_enabled is None
            else execute_enabled
        )
        self.workdir = workdir or os.environ.get("SARATHI_WORKDIR", os.getcwd())
        self.timeout_seconds = timeout_seconds or int(os.environ.get("SARATHI_COMMAND_TIMEOUT", "600"))
        if sandbox is None:
            sandbox = build_sandbox_executor(os.environ.get("SARATHI_SANDBOX"))
        self.sandbox = sandbox

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def run(self, command: str | None) -> CommandResult:
        started_at = self._timestamp()

        if not command:
            return CommandResult(
                command="",
                source="none",
                error="No command declared",
                started_at=started_at,
                finished_at=started_at,
                duration_seconds=0.0,
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
                argv=[],
            )

        try:
            argv = shlex.split(command, posix=os.name != "nt")
        except ValueError as e:
            finished_at = self._timestamp()
            return CommandResult(
                command=command,
                source="shell_error",
                error=str(e),
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=0.0,
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
                argv=[],
            )

        if not self.execute_enabled:
            return CommandResult(
                command=command,
                source="declared_not_executed",
                error=(
                    "Declared command not executed. Set SARATHI_EXEC_COMMANDS=1 "
                    "(and optionally SARATHI_WORKDIR) to run it."
                ),
                started_at=started_at,
                finished_at=started_at,
                duration_seconds=0.0,
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
                argv=argv,
            )

        if self.sandbox is not None:
            started_monotonic = time.monotonic()
            sandbox_result = self.sandbox.run(
                argv,
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
            )
            finished_at = self._timestamp()
            duration = round(time.monotonic() - started_monotonic, 6)
            executor_kind = self.sandbox.kind

            # Infra failure (could not run the command at all): error set and
            # no exit code. Surface as shell_error so VERIFY does not treat it
            # as a real pass/fail signal.
            if sandbox_result.error is not None and sandbox_result.exit_code is None:
                return CommandResult(
                    command=command,
                    source="shell_error",
                    error=sandbox_result.error,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    workdir=self.workdir,
                    timeout_seconds=self.timeout_seconds,
                    argv=argv,
                    executor=executor_kind,
                )

            out = (sandbox_result.stdout or "") + (sandbox_result.stderr or "")
            return CommandResult(
                command=command,
                source="shell",
                exit_code=sandbox_result.exit_code,
                output_tail=out[-2000:],
                error=sandbox_result.error,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
                argv=argv,
                executor=executor_kind,
            )

        started_monotonic = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            finished_at = self._timestamp()
            return CommandResult(
                command=command,
                source="shell_error",
                error=str(e),
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=round(time.monotonic() - started_monotonic, 6),
                workdir=self.workdir,
                timeout_seconds=self.timeout_seconds,
                argv=argv,
            )

        out = (proc.stdout or "") + (proc.stderr or "")
        finished_at = self._timestamp()
        return CommandResult(
            command=command,
            source="shell",
            exit_code=proc.returncode,
            output_tail=out[-2000:],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.monotonic() - started_monotonic, 6),
            workdir=self.workdir,
            timeout_seconds=self.timeout_seconds,
            argv=argv,
            executor="host",
        )
