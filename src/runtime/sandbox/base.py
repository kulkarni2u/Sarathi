"""Abstract sandbox executor interface.

A SandboxExecutor runs a command (argv) in an isolated environment with a
workspace directory available to the command. Today only a Docker-backed
implementation exists, but this interface is intentionally provider-agnostic
so future executors (e.g. Modal, Daytona, or other remote/cloud sandboxes)
can be added behind the SAME abstraction without touching callers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SandboxResult:
    """Structured result from running a command inside a sandbox.

    ``error`` is set only for infrastructure/transport failures (e.g. the
    sandbox could not be launched). A non-zero ``exit_code`` with no ``error``
    means the command itself ran and failed.
    """

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and self.error is None and not self.timed_out


class SandboxExecutor(ABC):
    """Abstract base for command sandbox executors.

    Implementations must never raise from ``run`` for ordinary failures;
    they should map infrastructure problems to ``SandboxResult(error=...)``
    and command failures to a non-zero ``exit_code``. This contract lets
    callers treat any executor (Docker, Modal, Daytona, ...) uniformly.
    """

    @property
    @abstractmethod
    def kind(self) -> str:
        """Short stable identifier for the executor backend (e.g. ``"docker"``)."""
        raise NotImplementedError

    @abstractmethod
    def run(
        self,
        argv: list[str],
        *,
        workdir: str,
        timeout_seconds: int,
    ) -> SandboxResult:
        """Run ``argv`` with ``workdir`` mounted/available; never raise."""
        raise NotImplementedError
