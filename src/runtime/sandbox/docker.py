"""Docker-backed sandbox executor.

Runs a command inside an ephemeral container with the host workspace
bind-mounted, so the command observes real files and any writes flow back
to the host workspace directory. No host filesystem state outside the
mounted workspace is mutated.
"""
from __future__ import annotations

import subprocess

try:
    from .base import SandboxExecutor, SandboxResult
except ImportError:  # pragma: no cover - direct module import fallback
    from base import SandboxExecutor, SandboxResult


def docker_available(docker_path: str = "docker") -> bool:
    """Return True only if the docker CLI exists AND the daemon responds.

    Implemented by running ``docker info`` with a short timeout. Returns
    False on any non-zero exit or exception. Never raises.
    """
    try:
        proc = subprocess.run(
            [docker_path, "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


class DockerSandboxExecutor(SandboxExecutor):
    """Execute commands inside an ephemeral Docker container."""

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        network: str = "none",
        mount_target: str = "/workspace",
        docker_path: str = "docker",
    ):
        self.image = image
        self.network = network
        self.mount_target = mount_target
        self.docker_path = docker_path

    @property
    def kind(self) -> str:
        return "docker"

    def _build_docker_argv(self, argv: list[str], *, workdir: str) -> list[str]:
        """Build the full ``docker run`` argv. Exposed for unit testing."""
        return [
            self.docker_path,
            "run",
            "--rm",
            "--network",
            self.network,
            "-v",
            f"{workdir}:{self.mount_target}",
            "-w",
            self.mount_target,
            self.image,
            *argv,
        ]

    def run(
        self,
        argv: list[str],
        *,
        workdir: str,
        timeout_seconds: int,
    ) -> SandboxResult:
        docker_argv = self._build_docker_argv(argv, workdir=workdir)
        try:
            proc = subprocess.run(
                docker_argv,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                error=f"Docker sandbox command timed out after {timeout_seconds}s",
                timed_out=True,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return SandboxResult(error=str(exc))

        return SandboxResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
