"""Tests for sarathi init --from feature."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


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


def test_init_from_local_directory(tmp_path: Path):
    """Test importing from a local directory containing policy files."""
    # Create a source pack with minimal files
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")
    (source_pack / "commands.md").write_text("# Commands\n\ntest")

    # Create target directory
    target = tmp_path / "target"
    target.mkdir()

    # Run init with --from
    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()
    # Should have filled in missing files with defaults
    assert (target / "policy-pack" / "review.md").exists()
    assert (target / "policy-pack" / "escalation.md").exists()


def test_init_from_recipe_bakeoff(tmp_path: Path):
    """Test importing from a shipped recipe by name."""
    target = tmp_path / "target"
    target.mkdir()

    # Run init with --from bakeoff (the shipped recipe)
    result = _run_cli("init", str(target), "--from", "bakeoff")

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Bakeoff recipe files should be copied
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()
    assert (target / "policy-pack" / "workflow-patterns.md").exists()


def test_init_from_with_agents_subdir(tmp_path: Path):
    """Test that agents/ subdirectory is copied."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")
    agents_dir = source_pack / "agents"
    agents_dir.mkdir()
    (agents_dir / "custom.md").write_text("# Custom Agent\n\ntest")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    assert (target / "policy-pack" / "agents" / "custom.md").exists()


def test_init_from_refuses_overwrite_without_force(tmp_path: Path):
    """Test that --from refuses to overwrite without --force."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")

    target = tmp_path / "target"
    target.mkdir()
    pack = target / "policy-pack"
    pack.mkdir()
    (pack / "existing.md").write_text("# Existing\n\nkeep me")

    # Try without --force
    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 1
    assert "Error" in result.stdout or "Error" in result.stderr
    # Existing file should remain
    assert (pack / "existing.md").exists()
    assert (pack / "existing.md").read_text() == "# Existing\n\nkeep me"


def test_init_from_with_force_overwrites(tmp_path: Path):
    """Test that --force overwrites existing pack."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity from source\n\ntest")

    target = tmp_path / "target"
    target.mkdir()
    pack = target / "policy-pack"
    pack.mkdir()
    (pack / "complexity.md").write_text("# Complexity from target\n\nold")

    # Run with --force
    result = _run_cli("init", str(target), "--from", str(source_pack), "--force")

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # File should be overwritten
    assert (pack / "complexity.md").read_text() == "# Complexity from source\n\ntest"


def test_init_from_git_url_file(tmp_path: Path):
    """Test importing from a git URL using file:// for local testing."""
    # Create a git repo with a policy pack
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Initialize as git repo
    subprocess.run(
        ["git", "init"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )

    # Add policy files
    pack_dir = repo_dir / "policy-pack"
    pack_dir.mkdir()
    (pack_dir / "complexity.md").write_text("# Complexity\n\nfrom git")
    (pack_dir / "commands.md").write_text("# Commands\n\nfrom git")

    # Commit
    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )

    # Create target
    target = tmp_path / "target"
    target.mkdir()

    # Use file:// URL to reference the local repo
    git_url = f"file://{repo_dir}"

    result = _run_cli("init", str(target), "--from", git_url)

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Files should be imported from the git repo
    assert (target / "policy-pack" / "complexity.md").exists()
    content = (target / "policy-pack" / "complexity.md").read_text()
    assert "from git" in content


def test_init_from_invalid_source(tmp_path: Path):
    """Test that invalid source gives clear error."""
    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", "/nonexistent/path/to/pack")

    assert result.returncode == 1
    assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


def test_init_from_fills_missing_standard_files(tmp_path: Path):
    """Test that missing standard files are filled with generated defaults."""
    # Create minimal source pack
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\nminimal pack")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    # All standard files should exist
    required_files = [
        "complexity.md",
        "commands.md",
        "review.md",
        "escalation.md",
        "model-routing.md",
        "permissions.md",
        "notifications.md",
    ]
    for fname in required_files:
        fpath = target / "policy-pack" / fname
        assert fpath.exists(), f"Missing {fname}"
        assert fpath.stat().st_size > 0, f"{fname} is empty"


def test_init_from_validates_after_import(tmp_path: Path):
    """Test that validation runs after import."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    # Output should include validation results
    output = result.stdout + result.stderr
    assert "Validate" in output or "validate" in output or "PASS" in output
