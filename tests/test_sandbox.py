"""Tests for the sandbox executor abstraction (T3.2).

These tests are designed to pass WITH and WITHOUT a running Docker daemon.
Real-container tests are gated behind ``docker_available()`` and skip cleanly
when the daemon is unavailable. The integration logic (CommandRunner ->
SandboxExecutor delegation, argv shape, factory resolution) is verified
without Docker via a fake in-process executor and argv-shape assertions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime import CommandRunner
from src.runtime.sandbox import (
    DockerSandboxExecutor,
    SandboxExecutor,
    SandboxResult,
    build_sandbox_executor,
    docker_available,
)


class _FakeSandboxExecutor(SandboxExecutor):
    """In-process fake executor for testing delegation without Docker."""

    def __init__(self, result: SandboxResult, kind: str = "fake"):
        self._result = result
        self._kind = kind
        self.received_argv: list[str] | None = None
        self.received_workdir: str | None = None
        self.received_timeout: int | None = None

    @property
    def kind(self) -> str:
        return self._kind

    def run(self, argv, *, workdir, timeout_seconds) -> SandboxResult:
        self.received_argv = argv
        self.received_workdir = workdir
        self.received_timeout = timeout_seconds
        return self._result


# ---------------------------------------------------------------------------
# Docker-gated tests (skip cleanly when the daemon is unavailable)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not docker_available(), reason="docker daemon unavailable")
def test_docker_executor_runs_command(tmp_path: Path):
    executor = DockerSandboxExecutor()
    result = executor.run(
        ["sh", "-c", "echo hi from container"],
        workdir=str(tmp_path),
        timeout_seconds=120,
    )
    assert result.succeeded
    assert result.exit_code == 0
    assert "hi" in result.stdout


@pytest.mark.skipif(not docker_available(), reason="docker daemon unavailable")
def test_docker_executor_workspace_changes_flow_back(tmp_path: Path):
    executor = DockerSandboxExecutor()
    result = executor.run(
        ["sh", "-c", "echo written > /workspace/created_in_container.txt"],
        workdir=str(tmp_path),
        timeout_seconds=120,
    )
    assert result.succeeded
    created = tmp_path / "created_in_container.txt"
    assert created.exists()


# ---------------------------------------------------------------------------
# No-Docker tests (always run)
# ---------------------------------------------------------------------------

def test_docker_available_returns_bool():
    # Must never raise, regardless of whether docker exists.
    assert isinstance(docker_available(), bool)


def test_build_sandbox_executor_resolves_docker_and_none():
    assert build_sandbox_executor(None) is None
    assert isinstance(build_sandbox_executor("docker"), DockerSandboxExecutor)
    assert isinstance(
        build_sandbox_executor({"sandbox": "docker"}), DockerSandboxExecutor
    )
    assert build_sandbox_executor("nope") is None


def test_docker_argv_shape():
    executor = DockerSandboxExecutor(image="img:tag", network="none")
    argv = executor._build_docker_argv(["pytest", "-q"], workdir="/tmp/ws")

    for token in (
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        "/tmp/ws:/workspace",
        "-w",
        "/workspace",
        "img:tag",
    ):
        assert token in argv

    assert argv[-2:] == ["pytest", "-q"]


def test_command_runner_delegates_to_sandbox(tmp_path: Path):
    fake = _FakeSandboxExecutor(
        SandboxResult(exit_code=0, stdout="from fake sandbox"),
        kind="fake",
    )
    runner = CommandRunner(
        execute_enabled=True,
        workdir=str(tmp_path),
        timeout_seconds=5,
        sandbox=fake,
    )
    result = runner.run("pytest -q")

    # The fake received the parsed argv / workdir / timeout.
    assert fake.received_argv == ["pytest", "-q"]
    assert fake.received_workdir == str(tmp_path)
    assert fake.received_timeout == 5

    # CRITICAL: source stays "shell" so VERIFY treats it as a real run.
    assert result.source == "shell"
    assert result.succeeded is True
    assert result.executor == "fake"
    assert "from fake sandbox" in result.output_tail


def test_command_runner_without_sandbox_runs_on_host(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SARATHI_SANDBOX", raising=False)
    runner = CommandRunner(
        execute_enabled=True,
        workdir=str(tmp_path),
        timeout_seconds=5,
    )
    assert runner.sandbox is None

    result = runner.run("python3 -c \"print('host run')\"")
    assert result.source == "shell"
    assert result.succeeded
    assert result.executor in (None, "host")


def test_command_runner_sandbox_infra_error_is_shell_error(tmp_path: Path):
    fake = _FakeSandboxExecutor(
        SandboxResult(error="docker missing", exit_code=None),
        kind="fake",
    )
    runner = CommandRunner(
        execute_enabled=True,
        workdir=str(tmp_path),
        timeout_seconds=5,
        sandbox=fake,
    )
    result = runner.run("pytest -q")

    assert result.source == "shell_error"
    assert result.error == "docker missing"
    assert result.executor == "fake"
