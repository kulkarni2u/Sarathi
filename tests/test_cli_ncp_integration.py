"""Integration tests for CLI --ncp flag."""

import subprocess
import sys
import os
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


def test_cli_run_ncp_dry_run(tmp_path):
    """sarathi run --ncp --dry-run should print phase list without errors."""
    # Set up mock NCP environment so Engine._validate_ncp_available() passes
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir(parents=True, exist_ok=True)
    run_py = ncp_dir / "run.py"
    run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)")
    run_py.chmod(0o755)

    # Set up minimal policy pack (auto-discovered from cwd)
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir(parents=True, exist_ok=True)
    for name in ["commands", "conventions", "complexity",
                  "review", "escalation", "skills", "task-tracking"]:
        (policy_dir / f"{name}.md").write_text(f"# {name.capitalize()}\n")

    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "run", "--ncp", "--dry-run", "test task"],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env=_repo_env(),
    )
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"
    assert "Route" in result.stdout
    assert "Learn" in result.stdout


def test_cli_run_without_ncp_uses_native_adapters(tmp_path):
    """sarathi run without --ncp should not enable NCP adapters."""
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir(parents=True, exist_ok=True)
    for name in ["commands", "conventions", "complexity",
                  "review", "escalation", "skills", "task-tracking"]:
        (policy_dir / f"{name}.md").write_text(f"# {name.capitalize()}\n")

    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "run", "--dry-run", "test task"],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env=_repo_env(),
    )
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"
    assert "Route" in result.stdout
    assert "NCPContextAdapter" not in result.stdout
