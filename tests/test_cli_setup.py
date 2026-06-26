"""CLI tests for interactive setup planning."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _repo_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_pythonpath
        else str(PROJECT_ROOT) + os.pathsep + existing_pythonpath
    )
    return env


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd or PROJECT_ROOT),
        env=_repo_env(),
    )


def test_cli_help_lists_setup_command():
    result = _run_cli("--help")

    assert result.returncode == 0
    assert "setup" in result.stdout


def test_setup_yes_dry_run_prints_recommended_plan(tmp_path: Path):
    result = _run_cli("setup", "--yes", "--dry-run", "--workspace", str(tmp_path))
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Sarathi setup plan" in output
    assert "Terminal UI: enabled" in output
    assert "WebUI: enabled" in output
    assert "NCP workspace: enabled" in output
    assert "MCP server: skipped" in output
    assert "Desktop launcher: skipped" in output
    assert 'python3 -m pip install -e ".[tui]"' in output
    assert f"sarathi init {tmp_path} --ncp" in output


def test_setup_dry_run_honors_explicit_component_flags(tmp_path: Path):
    result = _run_cli(
        "setup",
        "--dry-run",
        "--workspace",
        str(tmp_path),
        "--no-tui",
        "--mcp",
        "--no-webui",
        "--no-ncp",
        "--desktop",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Terminal UI: skipped" in output
    assert "MCP server: enabled" in output
    assert "WebUI: skipped" in output
    assert "NCP workspace: skipped" in output
    assert "Desktop launcher: enabled" in output
    assert 'python3 -m pip install -e ".[mcp]"' in output
    assert "sarathi init" not in output


def test_setup_extras_plan_uses_distribution_name_outside_source_checkout(tmp_path: Path):
    from src.cli import _setup_extras_install_plan

    display, command, cwd = _setup_extras_install_plan(["tui", "mcp"], tmp_path)

    assert display == 'python3 -m pip install "sarathi-ai[tui,mcp]"'
    assert command == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "sarathi-ai[tui,mcp]",
    ]
    assert cwd is None
